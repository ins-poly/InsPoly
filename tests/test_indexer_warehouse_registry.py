from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.indexer_warehouse_registry import (
    CLASS_ACTIVE,
    CLASS_BLOCKED,
    CLASS_CLEANUP,
    CLASS_RETAINED,
    GATE_BLOCKED_MALFORMED_INPUT,
    GATE_NO_INPUTS,
    GATE_READY,
    build_warehouse_registry,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-05-27T09:30:00+00:00")


class IndexerWarehouseRegistryTests(unittest.TestCase):
    def test_builds_registry_from_w1_aggregate_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = _write_summary(Path(tmp))

            registry = build_warehouse_registry([summary_path], now=NOW)

            self.assertEqual(registry["summary"]["gateDecision"], GATE_READY)
            self.assertEqual(registry["summary"]["runCount"], 3)
            self.assertEqual(registry["summary"]["activeReviewCandidates"], 1)
            self.assertEqual(registry["summary"]["retainedReferences"], 2)
            self.assertEqual(registry["summary"]["totalMarkets"], 5)
            self.assertEqual(registry["summary"]["totalTrades"], 580)
            classes = {run["label"]: run["retentionClassification"] for run in registry["runs"]}
            self.assertEqual(classes["per_target_multitarget"], CLASS_ACTIVE)
            self.assertEqual(classes["first_one_target"], CLASS_RETAINED)
            self.assertTrue(registry["summary"]["localOnlyRawDbReferences"])

    def test_explicit_manual_command_summary_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "manual.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "reportType": "indexer_warehouse_manual_command",
                        "schemaVersion": "indexer_warehouse_manual_command_v1",
                        "generatedAt": "2026-05-27T00:00:00+00:00",
                        "inputDbPath": ".inspoly_indexer/manual/indexer.sqlite3",
                        "runSummaryPath": ".inspoly_indexer/manual/raw_run_summary.json",
                        "collectionMetadata": {"rowsByTarget": {"slug-a": 3}},
                        "summary": {
                            "gateDecision": "ready_for_local_warehouse_review",
                            "marketCount": 1,
                            "tradeCount": 3,
                            "cursorCount": 2,
                            "malformedRawJsonCount": 0,
                            "duplicateIndicatorCount": 0,
                            "warehouseW0Ready": True,
                            "collectionMetadataStatus": "per_target_metadata_ready",
                        },
                    }
                ),
                encoding="utf-8",
            )

            registry = build_warehouse_registry([summary_path], now=NOW)

            self.assertEqual(registry["summary"]["gateDecision"], GATE_READY)
            run = registry["runs"][0]
            self.assertEqual(run["retentionClassification"], CLASS_ACTIVE)
            self.assertEqual(run["targetSlugs"], ["slug-a"])
            self.assertEqual(run["rowsByTarget"], {"slug-a": 3})

    def test_malformed_input_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "bad.json"
            summary_path.write_text("[]", encoding="utf-8")

            registry = build_warehouse_registry([summary_path], now=NOW)

            self.assertEqual(registry["summary"]["gateDecision"], GATE_BLOCKED_MALFORMED_INPUT)
            self.assertEqual(registry["summary"]["runCount"], 0)
            self.assertTrue(registry["errors"])

    def test_no_input_paths_are_blocked(self) -> None:
        registry = build_warehouse_registry([], now=NOW)

        self.assertEqual(registry["summary"]["gateDecision"], GATE_NO_INPUTS)
        self.assertEqual(registry["summary"]["nextAllowedAction"], "provide_w1_summary_json_before_w2_registry_review")

    def test_blocked_not_w0_ready_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = _write_summary(
                Path(tmp),
                runs=[
                    {
                        "label": "blocked",
                        "dbPath": ".inspoly_indexer/blocked/indexer.sqlite3",
                        "gateDecision": "blocked_w0_not_ready",
                        "marketCount": 1,
                        "tradeCount": 100,
                        "cursorCount": 0,
                        "malformedRawJsonCount": 0,
                        "duplicateIndicatorCount": 0,
                        "warehouseW0Ready": False,
                        "collectionMetadataStatus": "external_summary_required",
                    }
                ],
            )

            registry = build_warehouse_registry([summary_path], now=NOW)

            self.assertEqual(registry["summary"]["blockedNotW0Ready"], 1)
            self.assertEqual(registry["runs"][0]["retentionClassification"], CLASS_BLOCKED)

    def test_low_value_ready_db_is_cleanup_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = _write_summary(
                Path(tmp),
                runs=[
                    {
                        "label": "empty",
                        "dbPath": ".inspoly_indexer/empty/indexer.sqlite3",
                        "gateDecision": "ready_for_local_warehouse_review",
                        "marketCount": 1,
                        "tradeCount": 0,
                        "cursorCount": 2,
                        "malformedRawJsonCount": 0,
                        "duplicateIndicatorCount": 0,
                        "warehouseW0Ready": True,
                        "collectionMetadataStatus": "external_summary_required",
                    }
                ],
            )

            registry = build_warehouse_registry([summary_path], now=NOW)

            self.assertEqual(registry["summary"]["cleanupCandidates"], 1)
            self.assertEqual(registry["runs"][0]["retentionClassification"], CLASS_CLEANUP)

    def test_cli_writes_registry_without_mutating_input_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            summary_path = _write_summary(tmp_path)
            before = summary_path.read_text(encoding="utf-8")
            output_json = tmp_path / "registry.json"

            with redirect_stdout(StringIO()):
                exit_code = main([
                    "--w1-summary-json",
                    str(summary_path),
                    "--output-json",
                    str(output_json),
                    "--dry-run",
                ])

            self.assertEqual(exit_code, 0)
            self.assertEqual(before, summary_path.read_text(encoding="utf-8"))
            written = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertTrue(written["dryRun"])
            self.assertEqual(written["reportType"], "indexer_warehouse_registry")

    def test_no_network_behavior_by_design(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = _write_summary(Path(tmp))

            with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
                with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                    registry = build_warehouse_registry([summary_path], now=NOW)

            self.assertFalse(registry["networkUsed"])
            self.assertFalse(registry["productionIntegration"])
            self.assertFalse(registry["artifactDeletionPerformed"])

    def test_tool_is_not_imported_by_production_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
            "app/browser_desktop.py",
            "app/browser_ui.html",
            "app/browser_event_forensic_ui.html",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("indexer_warehouse_registry", source)


def _write_summary(path: Path, *, runs: list[dict[str, object]] | None = None) -> Path:
    summary_path = path / "w1_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "reportType": "indexer_warehouse_w1_manual_command_summary",
                "schemaVersion": "indexer_warehouse_w1_manual_command_summary_v1",
                "generatedAt": "2026-05-27T00:00:00+00:00",
                "runs": runs
                if runs is not None
                else [
                    {
                        "label": "first_one_target",
                        "dbPath": ".inspoly_indexer/bounded_live_20260527/indexer.sqlite3",
                        "rawSummaryPath": ".inspoly_indexer/bounded_live_20260527/raw_run_summary.json",
                        "gateDecision": "ready_for_local_warehouse_review",
                        "marketCount": 1,
                        "tradeCount": 200,
                        "cursorCount": 2,
                        "malformedRawJsonCount": 0,
                        "duplicateIndicatorCount": 0,
                        "warehouseW0Ready": True,
                        "collectionMetadataStatus": "external_summary_required",
                        "warnings": ["stale_cursor_count:2", "aggregate_public_trade_cursor_only"],
                    },
                    {
                        "label": "same_slug_repeat",
                        "dbPath": ".inspoly_indexer/bounded_live_repeat_20260527/indexer.sqlite3",
                        "rawSummaryPath": ".inspoly_indexer/bounded_live_repeat_20260527/raw_run_summary.json",
                        "gateDecision": "ready_for_local_warehouse_review",
                        "marketCount": 1,
                        "tradeCount": 200,
                        "cursorCount": 2,
                        "malformedRawJsonCount": 0,
                        "duplicateIndicatorCount": 0,
                        "warehouseW0Ready": True,
                        "collectionMetadataStatus": "external_summary_required",
                        "warnings": ["stale_cursor_count:2", "aggregate_public_trade_cursor_only"],
                    },
                    {
                        "label": "per_target_multitarget",
                        "dbPath": ".inspoly_indexer/bounded_live_multitarget_per_target_20260527/indexer.sqlite3",
                        "rawSummaryPath": ".inspoly_indexer/bounded_live_multitarget_per_target_20260527/raw_run_summary.json",
                        "gateDecision": "ready_for_local_warehouse_review",
                        "marketCount": 3,
                        "tradeCount": 180,
                        "cursorCount": 2,
                        "malformedRawJsonCount": 0,
                        "duplicateIndicatorCount": 0,
                        "warehouseW0Ready": True,
                        "collectionMetadataStatus": "per_target_metadata_ready",
                        "rowsByTarget": {
                            "khamenei-out-as-supreme-leader-of-iran-by-february-28": 60,
                            "maduro-in-us-custody-by-january-31": 60,
                            "russia-x-ukraine-ceasefire-by-january-31-2026": 60,
                        },
                        "warnings": ["stale_cursor_count:2", "aggregate_public_trade_cursor_only"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return summary_path


if __name__ == "__main__":
    unittest.main()
