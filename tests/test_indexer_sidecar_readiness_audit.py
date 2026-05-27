from __future__ import annotations

from contextlib import closing
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.indexer import IndexedMarket, IndexedTrade, IndexerStorage, OrderbookSnapshot
from tools.indexer_sidecar_readiness_audit import audit_indexer_sidecar_readiness, main, write_audit_output


ROOT = Path(__file__).resolve().parents[1]


class IndexerSidecarReadinessAuditTests(unittest.TestCase):
    def test_missing_db_does_not_create_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.sqlite3"

            report = audit_indexer_sidecar_readiness(db_path)

            self.assertFalse(db_path.exists())
            self.assertEqual(report["summary"]["readinessGate"], "indexer_sidecar_db_missing")
            self.assertTrue(report["readOnly"])
            self.assertFalse(report["networkUsed"])
            self.assertFalse(report["productionIntegration"])

    def test_complete_fixture_db_reports_ready_without_mutating_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            storage = IndexerStorage(db_path)
            storage.init()
            storage.upsert_cursor(
                source="fixture",
                cursor_key="markets",
                cursor_value="done",
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
                    raw={"source": "fixture"},
                    updated_at="2026-05-27T08:00:00+00:00",
                )
            )
            storage.upsert_trade(
                IndexedTrade(
                    stable_trade_id="0xtx:1",
                    transaction_hash="0xtx",
                    order_hash="0xorder",
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
                    raw={"source": "fixture"},
                )
            )
            storage.insert_orderbook_snapshot(
                OrderbookSnapshot(
                    token_id="yes-a",
                    condition_id="cond-a",
                    timestamp="2026-05-27T08:00:00+00:00",
                    best_bid="0.49",
                    best_ask="0.51",
                    spread_bps="400",
                    bid_depth="10",
                    ask_depth="12",
                    liquidity_imbalance="0.09",
                    raw={"source": "fixture"},
                )
            )
            before = db_path.stat().st_mtime_ns

            report = audit_indexer_sidecar_readiness(
                db_path,
                now=storage_time("2026-05-27T08:10:00+00:00"),
            )

            self.assertEqual(before, db_path.stat().st_mtime_ns)
            self.assertEqual(report["schema"]["status"], "complete")
            self.assertEqual(report["summary"]["readinessGate"], "indexer_sidecar_readiness_ready_no_runtime")
            self.assertTrue(report["summary"]["warehouseW0Ready"])
            self.assertEqual(report["summary"]["tableContractStatus"], "complete")
            self.assertEqual(report["summary"]["cursorContractStatus"], "ready")
            self.assertEqual(report["summary"]["collectionMetadataStatus"], "external_summary_required")
            self.assertEqual(report["summary"]["tableCounts"]["indexed_trades"], 1)
            self.assertEqual(report["summary"]["malformedRawJsonCount"], 0)
            self.assertEqual(report["warehouseW0"]["oldDbCompatibility"]["status"], "sidecar_readable_w0_limited")

    def test_stale_cursor_and_malformed_json_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            storage = IndexerStorage(db_path)
            storage.init()
            storage.upsert_cursor(
                source="fixture",
                cursor_key="markets",
                cursor_value="offset:1",
                updated_at="2026-05-27T06:00:00+00:00",
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO indexed_markets (
                        condition_id, slug, event_slug, question, active, closed,
                        end_date, raw_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("cond-a", "market-a", "event-a", "Fixture?", 1, 0, "", "{bad-json", "2026-05-27T08:00:00+00:00"),
                )
                conn.commit()

            report = audit_indexer_sidecar_readiness(
                db_path,
                now=storage_time("2026-05-27T08:00:00+00:00"),
            )

            self.assertEqual(report["summary"]["readinessGate"], "indexer_sidecar_readiness_blocked_malformed_json")
            self.assertFalse(report["summary"]["warehouseW0Ready"])
            self.assertIn("malformed_raw_json_count:1", report["summary"]["warehouseW0BlockingReasons"])
            self.assertEqual(report["summary"]["staleCursorCount"], 1)
            self.assertEqual(report["malformedRawJson"]["indexed_markets.raw_json"], 1)

    def test_warehouse_w0_blocks_missing_cursor_contract_without_changing_readiness_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
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
                    raw={"source": "fixture"},
                    updated_at="2026-05-27T08:00:00+00:00",
                )
            )

            report = audit_indexer_sidecar_readiness(
                db_path,
                now=storage_time("2026-05-27T08:10:00+00:00"),
            )

            self.assertEqual(report["summary"]["readinessGate"], "indexer_sidecar_readiness_ready_no_runtime")
            self.assertFalse(report["summary"]["warehouseW0Ready"])
            self.assertEqual(report["summary"]["cursorContractStatus"], "missing_cursors")
            self.assertIn("missing_indexer_cursors", report["summary"]["warehouseW0BlockingReasons"])

    def test_cli_writes_explicit_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            output_path = Path(tmp) / "audit.json"
            IndexerStorage(db_path).init()

            with redirect_stdout(StringIO()):
                exit_code = main(["--db-path", str(db_path), "--output-json", str(output_path)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["reportType"], "indexer_sidecar_readiness_audit")

    def test_write_output_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "audit.json"
            write_audit_output({"reportType": "test"}, target)
            self.assertTrue(target.exists())

    def test_audit_does_not_use_network_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            IndexerStorage(db_path).init()

            with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
                with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                    report = audit_indexer_sidecar_readiness(db_path)

        self.assertFalse(report["networkUsed"])

    def test_readiness_tool_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
            "app/browser_desktop.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("indexer_sidecar_readiness_audit", source)


def storage_time(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value)


if __name__ == "__main__":
    unittest.main()
