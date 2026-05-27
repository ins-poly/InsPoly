from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from app.indexer import IndexedMarket, IndexedTrade, IndexerStorage
from tools.indexer_sidecar_db_compare import (
    GATE_MISSING_INPUT,
    GATE_PROVIDER_DRIFT,
    GATE_READY,
    GATE_STORAGE_RISK,
    compare_indexer_sidecar_dbs,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-05-27T08:10:00+00:00")


class IndexerSidecarDbCompareTests(unittest.TestCase):
    def test_missing_inputs_do_not_create_db_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_db = Path(tmp) / "base.sqlite3"
            candidate_db = Path(tmp) / "candidate.sqlite3"

            report = compare_indexer_sidecar_dbs(
                base_db,
                candidate_db,
                comparison_mode="self_compare",
                now=NOW,
            )

            self.assertEqual(report["summary"]["gateDecision"], GATE_MISSING_INPUT)
            self.assertFalse(base_db.exists())
            self.assertFalse(candidate_db.exists())
            self.assertTrue(report["readOnly"])
            self.assertFalse(report["networkUsed"])
            self.assertFalse(report["productionIntegration"])

    def test_self_compare_reports_ready_for_identical_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            _write_fixture_db(db_path, trade_count=3)
            before = db_path.stat().st_mtime_ns

            report = compare_indexer_sidecar_dbs(
                db_path,
                db_path,
                comparison_mode="self_compare",
                now=NOW,
            )

            self.assertEqual(before, db_path.stat().st_mtime_ns)
            self.assertEqual(report["summary"]["gateDecision"], GATE_READY)
            self.assertEqual(report["tradeComparison"]["status"], "match")
            self.assertEqual(report["summary"]["storageRiskCount"], 0)

    def test_idempotent_replay_blocks_trade_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_db = Path(tmp) / "base.sqlite3"
            candidate_db = Path(tmp) / "candidate.sqlite3"
            _write_fixture_db(base_db, trade_count=3)
            _write_fixture_db(candidate_db, trade_count=4)

            report = compare_indexer_sidecar_dbs(
                base_db,
                candidate_db,
                comparison_mode="idempotent_replay",
                now=NOW,
            )

            self.assertEqual(report["summary"]["gateDecision"], GATE_STORAGE_RISK)
            self.assertEqual(report["tradeComparison"]["status"], "exact_drift_blocked")
            self.assertGreater(report["summary"]["storageRiskCount"], 0)

    def test_fresh_live_allows_trade_drift_within_tolerance_as_provider_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_db = Path(tmp) / "base.sqlite3"
            candidate_db = Path(tmp) / "candidate.sqlite3"
            _write_fixture_db(base_db, trade_count=10, cursor_trade_count=10)
            _write_fixture_db(candidate_db, trade_count=12, cursor_trade_count=12)

            report = compare_indexer_sidecar_dbs(
                base_db,
                candidate_db,
                comparison_mode="fresh_live",
                trade_row_drift_tolerance_abs=25,
                trade_row_drift_tolerance_pct=10,
                now=NOW,
            )

            self.assertEqual(report["summary"]["gateDecision"], GATE_PROVIDER_DRIFT)
            self.assertEqual(report["tradeComparison"]["status"], "provider_drift_within_tolerance")
            self.assertEqual(report["summary"]["storageRiskCount"], 0)
            self.assertGreater(report["summary"]["providerDriftCount"], 0)

    def test_fresh_live_blocks_market_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_db = Path(tmp) / "base.sqlite3"
            candidate_db = Path(tmp) / "candidate.sqlite3"
            _write_fixture_db(base_db, condition_id="cond-a", slug="market-a")
            _write_fixture_db(candidate_db, condition_id="cond-b", slug="market-b")

            report = compare_indexer_sidecar_dbs(
                base_db,
                candidate_db,
                comparison_mode="fresh_live",
                now=NOW,
            )

            self.assertEqual(report["summary"]["gateDecision"], GATE_STORAGE_RISK)
            self.assertIn("market_identity_mismatch", report["findings"])

    def test_duplicate_indicator_blocks_even_when_self_comparing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            _write_fixture_db(db_path, condition_id="cond-a", slug="market-a")
            storage = IndexerStorage(db_path)
            storage.upsert_market(
                IndexedMarket(
                    condition_id="cond-b",
                    slug="market-a",
                    event_slug="event-a",
                    question="Duplicate slug?",
                    active=True,
                    closed=False,
                    end_date="",
                    raw={"fixture": "duplicate"},
                    updated_at="2026-05-27T08:00:00+00:00",
                )
            )

            report = compare_indexer_sidecar_dbs(
                db_path,
                db_path,
                comparison_mode="self_compare",
                now=NOW,
            )

            self.assertEqual(report["summary"]["gateDecision"], GATE_STORAGE_RISK)
            self.assertIn("base:duplicate_indicators", report["findings"])

    def test_cli_writes_output_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            output_path = Path(tmp) / "compare.json"
            _write_fixture_db(db_path, trade_count=1)

            with redirect_stdout(StringIO()):
                exit_code = main(
                    [
                        "--base-db",
                        str(db_path),
                        "--candidate-db",
                        str(db_path),
                        "--comparison-mode",
                        "self_compare",
                        "--output-json",
                        str(output_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reportType"], "indexer_sidecar_db_compare")
            self.assertEqual(payload["summary"]["gateDecision"], GATE_READY)

    def test_compare_tool_is_not_imported_by_runtime_paths(self) -> None:
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
            self.assertNotIn("indexer_sidecar_db_compare", source)


def _write_fixture_db(
    db_path: Path,
    *,
    condition_id: str = "cond-a",
    slug: str = "market-a",
    trade_count: int = 2,
    cursor_trade_count: int | None = None,
) -> None:
    storage = IndexerStorage(db_path)
    storage.init()
    storage.upsert_market(
        IndexedMarket(
            condition_id=condition_id,
            slug=slug,
            event_slug="event-a",
            question="Fixture?",
            active=True,
            closed=False,
            end_date="2026-01-31T00:00:00Z",
            raw={"fixture": slug},
            updated_at="2026-05-27T08:00:00+00:00",
        )
    )
    storage.upsert_cursor(
        source="bounded_live_sidecar",
        cursor_key="markets",
        cursor_value=f"marketSlugs:{slug}:1",
        updated_at="2026-05-27T08:00:00+00:00",
    )
    storage.upsert_cursor(
        source="bounded_live_sidecar",
        cursor_key="public_trades",
        cursor_value=f"conditions:1:rows:{cursor_trade_count if cursor_trade_count is not None else trade_count}",
        updated_at="2026-05-27T08:00:00+00:00",
    )
    for index in range(trade_count):
        storage.upsert_trade(
            IndexedTrade(
                stable_trade_id=f"0xtx:{index}",
                transaction_hash=f"0xtx-{index}",
                order_hash=f"0xorder-{index}",
                condition_id=condition_id,
                token_id="yes-a",
                wallet=f"0xwallet-{index}",
                side="BUY",
                outcome="YES",
                size=str(index + 1),
                price="0.5",
                usdc_size=str(index + 1),
                timestamp=f"2026-05-27T08:{index:02d}:00+00:00",
                source="fixture",
                raw={"fixtureTrade": index},
            )
        )


if __name__ == "__main__":
    unittest.main()
