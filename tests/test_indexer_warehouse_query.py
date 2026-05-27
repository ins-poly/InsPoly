from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.indexer_warehouse_query import (
    GATE_BLOCKED_MALFORMED_REGISTRY,
    GATE_EMPTY_REGISTRY,
    GATE_READY,
    MODE_AGGREGATE,
    MODE_BLOCKED_SCOPES,
    MODE_HEALTH,
    MODE_LIST_RUNS,
    MODE_RETENTION_STATUS,
    MODE_TARGET_COVERAGE,
    run_warehouse_query,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "indexer_warehouse_query"
VALID_REGISTRY = FIXTURES / "registry_valid.json"
EMPTY_REGISTRY = FIXTURES / "registry_empty.json"
MALFORMED_REGISTRY = FIXTURES / "registry_malformed.json"
NOW = datetime.fromisoformat("2026-05-27T10:45:00+00:00")


class IndexerWarehouseQueryTests(unittest.TestCase):
    def test_valid_registry_list_runs(self) -> None:
        report = run_warehouse_query(VALID_REGISTRY, query_mode=MODE_LIST_RUNS, now=NOW)

        self.assertEqual(report["summary"]["gateDecision"], GATE_READY)
        self.assertEqual(report["summary"]["runCount"], 3)
        self.assertEqual(len(report["runs"]), 3)
        self.assertEqual(report["runs"][0]["retentionClassification"], "active_review_candidate")
        self.assertTrue(report["runs"][0]["sourceDbPathLocalOnly"])

    def test_aggregate_query(self) -> None:
        report = run_warehouse_query(VALID_REGISTRY, query_mode=MODE_AGGREGATE, now=NOW)

        self.assertEqual(report["summary"]["gateDecision"], GATE_READY)
        self.assertEqual(report["queryResult"]["totalMarkets"], 5)
        self.assertEqual(report["queryResult"]["totalTrades"], 580)
        self.assertEqual(report["queryResult"]["totalCursors"], 6)
        self.assertFalse(report["queryResult"]["scoringSignal"])

    def test_target_coverage_query(self) -> None:
        report = run_warehouse_query(VALID_REGISTRY, query_mode=MODE_TARGET_COVERAGE, now=NOW)

        targets = {item["targetSlug"]: item["totalRows"] for item in report["queryResult"]["targets"]}
        self.assertEqual(report["summary"]["targetCoverageCount"], 3)
        self.assertEqual(targets["russia-x-ukraine-ceasefire-by-january-31-2026"], 60)
        self.assertEqual(targets["maduro-in-us-custody-by-january-31"], 60)
        self.assertEqual(targets["khamenei-out-as-supreme-leader-of-iran-by-february-28"], 60)
        self.assertIn("first_one_target", report["queryResult"]["runsMissingTargetMetadata"])

    def test_health_query(self) -> None:
        report = run_warehouse_query(VALID_REGISTRY, query_mode=MODE_HEALTH, now=NOW)

        self.assertEqual(report["queryResult"]["w0ReadyRuns"], 3)
        self.assertEqual(report["queryResult"]["malformedRawJsonCount"], 0)
        self.assertEqual(report["queryResult"]["duplicateIndicatorCount"], 0)
        self.assertEqual(report["queryResult"]["healthStatus"], "ready_with_stale_historical_warning")

    def test_retention_status_query(self) -> None:
        report = run_warehouse_query(VALID_REGISTRY, query_mode=MODE_RETENTION_STATUS, now=NOW)

        distribution = report["queryResult"]["classificationDistribution"]
        self.assertEqual(distribution["active_review_candidate"], 1)
        self.assertEqual(distribution["retained_reference"], 2)
        self.assertTrue(report["queryResult"]["manualCleanupOnly"])
        self.assertFalse(report["queryResult"]["artifactDeletionPerformed"])

    def test_blocked_scopes_query(self) -> None:
        report = run_warehouse_query(VALID_REGISTRY, query_mode=MODE_BLOCKED_SCOPES, now=NOW)

        self.assertIn("live_ingestion", report["queryResult"]["blockedScopes"])
        self.assertIn("production_runtime_imports", report["queryResult"]["blockedScopes"])
        self.assertIn("report_browser_integration", report["queryResult"]["blockedScopes"])

    def test_malformed_registry_fails_closed(self) -> None:
        report = run_warehouse_query(MALFORMED_REGISTRY, query_mode=MODE_AGGREGATE, now=NOW)

        self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED_MALFORMED_REGISTRY)
        self.assertTrue(report["errors"])
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])

    def test_empty_registry_is_explicit(self) -> None:
        report = run_warehouse_query(EMPTY_REGISTRY, query_mode=MODE_LIST_RUNS, now=NOW)

        self.assertEqual(report["summary"]["gateDecision"], GATE_EMPTY_REGISTRY)
        self.assertEqual(report["summary"]["runCount"], 0)
        self.assertEqual(report["summary"]["nextAllowedAction"], "regenerate_registry_from_w1_summaries_before_analyst_query")

    def test_query_warnings_make_local_advisory_boundaries_explicit(self) -> None:
        report = run_warehouse_query(VALID_REGISTRY, query_mode=MODE_AGGREGATE, now=NOW)

        self.assertIn("sidecar_only", report["warnings"])
        self.assertIn("advisory_only", report["warnings"])
        self.assertIn("not_scoring_signal", report["warnings"])
        self.assertIn("not_report_integrated", report["warnings"])
        self.assertIn("local_paths_may_be_machine_specific", report["warnings"])

    def test_input_file_unchanged_after_query_and_outputs_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            registry_path = tmp_path / "registry.json"
            registry_path.write_text(VALID_REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
            before = registry_path.read_text(encoding="utf-8")
            output_json = tmp_path / "query.json"
            output_md = tmp_path / "query.md"

            report = run_warehouse_query(
                registry_path,
                query_mode=MODE_TARGET_COVERAGE,
                output_json=output_json,
                output_markdown=output_md,
                now=NOW,
            )

            self.assertEqual(report["summary"]["gateDecision"], GATE_READY)
            self.assertEqual(before, registry_path.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(output_json.read_text(encoding="utf-8"))["reportType"], "indexer_warehouse_query")
            self.assertTrue(output_md.exists())

    def test_cli_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_json = Path(tmp) / "query.json"

            with redirect_stdout(StringIO()):
                exit_code = main([
                    "--registry-json",
                    str(VALID_REGISTRY),
                    "--query-mode",
                    MODE_AGGREGATE,
                    "--output-json",
                    str(output_json),
                ])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output_json.read_text(encoding="utf-8"))["queryMode"], MODE_AGGREGATE)

    def test_no_network_behavior_by_design(self) -> None:
        with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
            with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                report = run_warehouse_query(VALID_REGISTRY, query_mode=MODE_AGGREGATE, now=NOW)

        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["inputDbsMutated"])
        self.assertFalse(report["savedReportsMutated"])

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
            self.assertNotIn("indexer_warehouse_query", source)


if __name__ == "__main__":
    unittest.main()
