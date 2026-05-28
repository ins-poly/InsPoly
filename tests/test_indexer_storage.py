from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.indexer import (
    IndexedMarket,
    IndexedTrade,
    IndexerStorage,
    OrderbookSnapshot,
    ScoreHistoryEntry,
)


ROOT = Path(__file__).resolve().parents[1]


class IndexerStorageTests(unittest.TestCase):
    def test_schema_initializes_in_temp_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = IndexerStorage(Path(tmp) / "indexer.sqlite3")
            storage.init()

            self.assertEqual(
                storage.table_counts(),
                {
                    "indexer_cursors": 0,
                    "indexed_markets": 0,
                    "indexed_trades": 0,
                    "orderbook_snapshots": 0,
                    "wallet_index_snapshots": 0,
                    "score_history": 0,
                },
            )

    def test_schema_init_is_repeatable_without_dropping_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = IndexerStorage(Path(tmp) / "indexer.sqlite3")
            storage.init()
            storage.upsert_cursor(
                source="fixture",
                cursor_key="markets",
                cursor_value="done",
                updated_at="2026-05-21T10:00:00+00:00",
            )

            storage.init()

            self.assertEqual(storage.table_counts()["indexer_cursors"], 1)
            cursor = storage.get_cursor("fixture", "markets")
            assert cursor is not None
            self.assertEqual(cursor.cursor_value, "done")

    def test_cursor_upsert_and_resume_preserves_latest_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = IndexerStorage(Path(tmp) / "indexer.sqlite3")
            storage.init()
            storage.upsert_cursor(
                source="clob",
                cursor_key="markets",
                cursor_value="cursor-1",
                updated_at="2026-05-21T10:00:00+00:00",
            )
            storage.upsert_cursor(
                source="clob",
                cursor_key="markets",
                cursor_value="cursor-2",
                status="idle",
                updated_at="2026-05-21T10:05:00+00:00",
            )

            cursor = storage.get_cursor("clob", "markets")

        assert cursor is not None
        self.assertEqual(cursor.cursor_value, "cursor-2")
        self.assertEqual(cursor.status, "idle")
        self.assertEqual(cursor.updated_at, "2026-05-21T10:05:00+00:00")

    def test_duplicate_trade_upsert_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = IndexerStorage(Path(tmp) / "indexer.sqlite3")
            storage.init()
            trade = IndexedTrade(
                stable_trade_id="0xtx:7",
                transaction_hash="0xtx",
                order_hash="0xorder",
                condition_id="cond-a",
                token_id="yes-a",
                wallet="0xwallet",
                side="BUY",
                outcome="Yes",
                size="100",
                price="0.40",
                usdc_size="41",
                timestamp="2026-05-21T10:00:00+00:00",
                source="activity",
                raw={"unexpected": {"preserved": True}},
            )
            storage.upsert_trade(trade)
            storage.upsert_trade(
                replace(
                    trade,
                    price="0.41",
                    raw={"updated": True},
                )
            )

            with closing(sqlite3.connect(Path(tmp) / "indexer.sqlite3")) as conn:
                count = conn.execute("SELECT COUNT(*) FROM indexed_trades").fetchone()[0]
            stored = storage.get_trade("0xtx:7")

        self.assertEqual(count, 1)
        assert stored is not None
        self.assertEqual(stored["price"], "0.41")
        self.assertEqual(stored["raw"], {"updated": True})

    def test_non_serializable_raw_payload_is_rejected_predictably(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = IndexerStorage(Path(tmp) / "indexer.sqlite3")
            storage.init()
            market = IndexedMarket(
                condition_id="cond-a",
                slug="market-a",
                event_slug="event-a",
                question="Fixture?",
                active=True,
                closed=False,
                end_date="",
                raw={"bad": object()},
                updated_at="2026-05-21T10:00:00+00:00",
            )

            with self.assertRaises(TypeError):
                storage.upsert_market(market)

    def test_malformed_stored_raw_json_is_rejected_predictably(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            storage = IndexerStorage(db_path)
            storage.init()
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO indexed_markets (
                        condition_id, slug, event_slug, question, active, closed,
                        end_date, raw_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "cond-a",
                        "market-a",
                        "event-a",
                        "Fixture?",
                        1,
                        0,
                        "",
                        "{not-json",
                        "2026-05-21T10:00:00+00:00",
                    ),
                )
                conn.commit()

            with self.assertRaisesRegex(ValueError, "malformed JSON"):
                storage.get_market("cond-a")

    def test_indexed_market_upsert_preserves_raw_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = IndexerStorage(Path(tmp) / "indexer.sqlite3")
            storage.init()
            storage.upsert_market(
                IndexedMarket(
                    condition_id="cond-a",
                    slug="market-a",
                    event_slug="event-a",
                    question="Will fixture happen?",
                    active=True,
                    closed=False,
                    end_date="2026-12-31T00:00:00Z",
                    raw={"tokens": ["yes-a", "no-a"], "nested": {"keep": 1}},
                    updated_at="2026-05-21T10:00:00+00:00",
                )
            )

            market = storage.get_market("cond-a")

        assert market is not None
        self.assertTrue(market["active"])
        self.assertFalse(market["closed"])
        self.assertEqual(market["raw"]["tokens"], ["yes-a", "no-a"])
        self.assertEqual(market["raw"]["nested"], {"keep": 1})

    def test_orderbook_snapshot_insert_preserves_spread_and_depth_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = IndexerStorage(Path(tmp) / "indexer.sqlite3")
            storage.init()
            snapshot_id = storage.insert_orderbook_snapshot(
                OrderbookSnapshot(
                    token_id="yes-a",
                    condition_id="cond-a",
                    timestamp="2026-05-21T10:00:00+00:00",
                    best_bid="0.40",
                    best_ask="0.42",
                    spread_bps="500",
                    bid_depth="1000",
                    ask_depth="850",
                    liquidity_imbalance="0.081081",
                    raw={"bids": [["0.40", "1000"]], "asks": [["0.42", "850"]]},
                )
            )

            snapshot = storage.latest_orderbook_snapshot("yes-a")

        self.assertEqual(snapshot_id, 1)
        assert snapshot is not None
        self.assertEqual(snapshot["best_bid"], "0.40")
        self.assertEqual(snapshot["best_ask"], "0.42")
        self.assertEqual(snapshot["spread_bps"], "500")
        self.assertEqual(snapshot["bid_depth"], "1000")
        self.assertEqual(snapshot["ask_depth"], "850")
        self.assertEqual(snapshot["raw"]["bids"], [["0.40", "1000"]])

    def test_duplicate_orderbook_snapshot_replay_updates_without_duplicate_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            storage = IndexerStorage(db_path)
            storage.init()
            first_id = storage.insert_orderbook_snapshot(
                OrderbookSnapshot(
                    token_id="yes-a",
                    condition_id="cond-a",
                    timestamp="2026-05-21T10:00:00+00:00",
                    best_bid="0.40",
                    best_ask="0.42",
                    spread_bps="500",
                    bid_depth="1000",
                    ask_depth="850",
                    liquidity_imbalance="0.081081",
                    raw={"version": 1},
                )
            )
            second_id = storage.insert_orderbook_snapshot(
                OrderbookSnapshot(
                    token_id="yes-a",
                    condition_id="cond-a",
                    timestamp="2026-05-21T10:00:00+00:00",
                    best_bid="0.41",
                    best_ask="0.43",
                    spread_bps="476.190476",
                    bid_depth="900",
                    ask_depth="800",
                    liquidity_imbalance="0.058824",
                    raw={"version": 2},
                )
            )

            with closing(sqlite3.connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM orderbook_snapshots").fetchone()[0]
            snapshot = storage.latest_orderbook_snapshot("yes-a")

        self.assertEqual(first_id, second_id)
        self.assertEqual(count, 1)
        assert snapshot is not None
        self.assertEqual(snapshot["best_bid"], "0.41")
        self.assertEqual(snapshot["raw"], {"version": 2})

    def test_stale_cursor_health_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = IndexerStorage(Path(tmp) / "indexer.sqlite3")
            storage.init()
            storage.upsert_cursor(
                source="gamma",
                cursor_key="markets",
                cursor_value="offset:100",
                updated_at="2026-05-21T09:00:00+00:00",
            )

            health = storage.cursor_health(
                now=datetime(2026, 5, 21, 10, 30, tzinfo=UTC),
                stale_after_seconds=3600,
            )

        self.assertEqual(len(health), 1)
        self.assertTrue(health[0].is_stale)
        self.assertEqual(health[0].age_seconds, timedelta(minutes=90).total_seconds())

    def test_cursor_error_status_is_stale_even_when_recent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = IndexerStorage(Path(tmp) / "indexer.sqlite3")
            storage.init()
            storage.upsert_cursor(
                source="gamma",
                cursor_key="markets",
                cursor_value="offset:100",
                status="error",
                last_error="fixture parse failed",
                updated_at="2026-05-21T10:00:00+00:00",
            )

            health = storage.cursor_health(
                now=datetime(2026, 5, 21, 10, 0, tzinfo=UTC),
                stale_after_seconds=3600,
            )

        self.assertEqual(len(health), 1)
        self.assertEqual(health[0].age_seconds, 0)
        self.assertTrue(health[0].is_stale)
        self.assertEqual(health[0].last_error, "fixture parse failed")

    def test_score_history_is_append_only_and_latest_can_be_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = IndexerStorage(Path(tmp) / "indexer.sqlite3")
            storage.init()
            first_id = storage.append_score_history(
                ScoreHistoryEntry(
                    subject_type="wallet",
                    subject_id="wallet-a",
                    score_type="shadow_low_odds_position_size",
                    score="1200",
                    label="shadow_context",
                    computed_at="2026-05-21T10:00:00+00:00",
                    input_hash="hash-a",
                    raw_metrics={"version": 1},
                )
            )
            second_id = storage.append_score_history(
                ScoreHistoryEntry(
                    subject_type="wallet",
                    subject_id="wallet-a",
                    score_type="shadow_low_odds_position_size",
                    score="5700",
                    label="shadow_notable",
                    computed_at="2026-05-21T11:00:00+00:00",
                    input_hash="hash-b",
                    raw_metrics={"version": 2},
                )
            )

            rows = storage.list_score_history(subject_type="wallet", subject_id="wallet-a")
            latest = storage.latest_score_history(
                subject_type="wallet",
                subject_id="wallet-a",
                score_type="shadow_low_odds_position_size",
            )

        self.assertNotEqual(first_id, second_id)
        self.assertEqual(len(rows), 2)
        assert latest is not None
        self.assertEqual(latest["score"], "5700")
        self.assertEqual(latest["raw_metrics"], {"version": 2})

    def test_score_history_limit_must_be_positive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = IndexerStorage(Path(tmp) / "indexer.sqlite3")
            storage.init()

            with self.assertRaises(ValueError):
                storage.list_score_history(limit=0)

    def test_score_history_malformed_raw_json_fails_predictably(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            storage = IndexerStorage(db_path)
            storage.init()
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO score_history (
                        subject_type, subject_id, score_type, score, label,
                        computed_at, input_hash, raw_metrics_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "wallet",
                        "wallet-a",
                        "shadow_metric",
                        "unknown",
                        "shadow_context",
                        "2026-05-21T10:00:00+00:00",
                        "hash-a",
                        "[not-object]",
                    ),
                )
                conn.commit()

            with self.assertRaisesRegex(ValueError, "malformed JSON"):
                storage.list_score_history(subject_type="wallet", subject_id="wallet-a")


class IndexerIsolationTests(unittest.TestCase):
    def test_indexer_sidecar_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
            "app/browser_desktop.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("app.indexer", source)
            self.assertNotIn("from app import indexer", source)


if __name__ == "__main__":
    unittest.main()
