from __future__ import annotations

from contextlib import closing
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.indexer import IndexedMarket, IndexedTrade, IndexerStorage
from tools.indexer_warehouse_manual_command import (
    GATE_EMPTY_OR_LOW_VALUE,
    GATE_MISSING_DB,
    GATE_READY,
    GATE_SCHEMA_OR_CURSOR_RISK,
    run_warehouse_manual_command,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-05-27T08:10:00+00:00")


class IndexerWarehouseManualCommandTests(unittest.TestCase):
    def test_missing_db_path_is_blocked_without_creating_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.sqlite3"

            report = run_warehouse_manual_command(db_path, now=NOW)

            self.assertEqual(report["summary"]["gateDecision"], GATE_MISSING_DB)
            self.assertFalse(db_path.exists())
            self.assertTrue(report["readOnly"])
            self.assertFalse(report["networkUsed"])

    def test_w0_ready_db_summary_is_ready_for_local_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / ".inspoly_indexer" / "indexer.sqlite3"
            _write_ready_db(db_path)
            run_summary = _write_run_summary(tmp)
            before = db_path.stat().st_mtime_ns

            report = run_warehouse_manual_command(db_path, run_summary_json=run_summary, now=NOW)

            self.assertEqual(report["summary"]["gateDecision"], GATE_READY)
            self.assertEqual(before, db_path.stat().st_mtime_ns)
            self.assertFalse(report["inputDbMutated"])
            self.assertEqual(report["summary"]["marketCount"], 1)
            self.assertEqual(report["summary"]["tradeCount"], 2)
            self.assertEqual(report["summary"]["cursorCount"], 2)
            self.assertEqual(report["summary"]["collectionMetadataStatus"], "per_target_metadata_ready")
            self.assertIn("live_ingestion", report["blockedRuntimeScopes"])

    def test_w0_not_ready_db_blocks_for_missing_cursor_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / ".inspoly_indexer" / "indexer.sqlite3"
            storage = IndexerStorage(db_path)
            storage.init()
            storage.upsert_market(
                IndexedMarket(
                    condition_id="cond-a",
                    slug="market-a",
                    event_slug="event-a",
                    question="Fixture?",
                    active=True,
                    closed=False,
                    end_date="",
                    raw={"fixture": True},
                    updated_at="2026-05-27T08:00:00+00:00",
                )
            )

            report = run_warehouse_manual_command(db_path, now=NOW)

            self.assertEqual(report["summary"]["gateDecision"], GATE_SCHEMA_OR_CURSOR_RISK)
            self.assertFalse(report["summary"]["warehouseW0Ready"])
            self.assertIn("missing_indexer_cursors", report["warehouseW0"]["warehouseW0BlockingReasons"])

    def test_empty_or_low_value_db_blocks_after_w0_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / ".inspoly_indexer" / "indexer.sqlite3"
            storage = IndexerStorage(db_path)
            storage.init()
            storage.upsert_cursor(
                source="bounded_live_sidecar",
                cursor_key="markets",
                cursor_value="marketSlugs:empty:0",
                updated_at="2026-05-27T08:00:00+00:00",
            )
            storage.upsert_cursor(
                source="bounded_live_sidecar",
                cursor_key="public_trades",
                cursor_value="conditions:0:rows:0",
                updated_at="2026-05-27T08:00:00+00:00",
            )

            report = run_warehouse_manual_command(db_path, now=NOW)

            self.assertEqual(report["summary"]["gateDecision"], GATE_EMPTY_OR_LOW_VALUE)
            self.assertTrue(report["summary"]["warehouseW0Ready"])

    def test_malformed_raw_json_is_reported_and_blocks_schema_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / ".inspoly_indexer" / "indexer.sqlite3"
            storage = IndexerStorage(db_path)
            storage.init()
            storage.upsert_cursor(
                source="bounded_live_sidecar",
                cursor_key="markets",
                cursor_value="marketSlugs:market-a:1",
                updated_at="2026-05-27T08:00:00+00:00",
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO indexed_markets (
                        condition_id, slug, event_slug, question, active, closed,
                        end_date, raw_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("cond-a", "market-a", "event-a", "Fixture?", 1, 0, "", "{bad", "2026-05-27T08:00:00+00:00"),
                )
                conn.commit()

            report = run_warehouse_manual_command(db_path, now=NOW)

            self.assertEqual(report["summary"]["gateDecision"], GATE_SCHEMA_OR_CURSOR_RISK)
            self.assertEqual(report["summary"]["malformedRawJsonCount"], 1)

    def test_output_json_and_markdown_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / ".inspoly_indexer" / "indexer.sqlite3"
            output_json = Path(tmp) / "summary.json"
            output_md = Path(tmp) / "summary.md"
            _write_ready_db(db_path)

            report = run_warehouse_manual_command(
                db_path,
                output_json=output_json,
                output_markdown=output_md,
                now=NOW,
            )

            self.assertEqual(report["reportType"], "indexer_warehouse_manual_command")
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            self.assertEqual(json.loads(output_json.read_text(encoding="utf-8"))["schemaVersion"], "indexer_warehouse_manual_command_v1")

    def test_cli_prints_report_and_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / ".inspoly_indexer" / "indexer.sqlite3"
            output_json = Path(tmp) / "summary.json"
            _write_ready_db(db_path)

            with redirect_stdout(StringIO()):
                exit_code = main(["--db-path", str(db_path), "--output-json", str(output_json)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output_json.read_text(encoding="utf-8"))["reportType"], "indexer_warehouse_manual_command")

    def test_no_network_behavior_by_design(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / ".inspoly_indexer" / "indexer.sqlite3"
            _write_ready_db(db_path)

            with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
                with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                    report = run_warehouse_manual_command(db_path, now=NOW)

            self.assertFalse(report["networkUsed"])
            self.assertFalse(report["productionIntegration"])

    def test_old_minimal_sidecar_db_is_compatible_but_limited_without_summary_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / ".inspoly_indexer" / "indexer.sqlite3"
            _write_ready_db(db_path)

            report = run_warehouse_manual_command(db_path, now=NOW)

            self.assertEqual(report["summary"]["gateDecision"], GATE_READY)
            self.assertEqual(report["summary"]["collectionMetadataStatus"], "external_summary_required")
            self.assertEqual(report["warehouseW0"]["oldDbCompatibility"]["status"], "sidecar_readable_w0_limited")

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
            self.assertNotIn("indexer_warehouse_manual_command", source)


def _write_ready_db(db_path: Path) -> None:
    storage = IndexerStorage(db_path)
    storage.init()
    storage.upsert_cursor(
        source="bounded_live_sidecar",
        cursor_key="markets",
        cursor_value="marketSlugs:market-a:1",
        updated_at="2026-05-27T08:00:00+00:00",
    )
    storage.upsert_cursor(
        source="bounded_live_sidecar",
        cursor_key="public_trades",
        cursor_value="conditions:1:rows:2",
        updated_at="2026-05-27T08:00:00+00:00",
    )
    storage.upsert_market(
        IndexedMarket(
            condition_id="cond-a",
            slug="market-a",
            event_slug="event-a",
            question="Fixture?",
            active=True,
            closed=False,
            end_date="",
            raw={"fixture": True},
            updated_at="2026-05-27T08:00:00+00:00",
        )
    )
    for index in range(2):
        storage.upsert_trade(
            IndexedTrade(
                stable_trade_id=f"0xtx{index}:0",
                transaction_hash=f"0xtx{index}",
                order_hash=f"0xorder{index}",
                condition_id="cond-a",
                token_id="yes-a",
                wallet="0xwallet",
                side="BUY",
                outcome="YES",
                size="10",
                price="0.5",
                usdc_size="5",
                timestamp="2026-05-27T08:00:00+00:00",
                source="fixture",
                raw={"fixture": True, "index": index},
            )
        )


def _write_run_summary(tmp: str) -> Path:
    path = Path(tmp) / "raw_run_summary.json"
    path.write_text(
        json.dumps(
            {
                "summary": {
                    "publicTradeCollection": {
                        "collectionPolicy": "per_target_public_trade_cap",
                        "rowsByTarget": {"market-a": 2},
                        "perTargetPublicTradeLimit": 2,
                        "aggregatePublicTradeLimit": 2,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
