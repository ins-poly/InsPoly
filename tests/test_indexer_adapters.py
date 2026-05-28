from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.indexer import (
    IndexerStorage,
    normalize_data_trade,
    normalize_gamma_market,
    normalize_orderbook_snapshot,
    token_condition_mapping_from_gamma_market,
)
from app.polymarket_protocol import token_mapping_for_token_id


ROOT = Path(__file__).resolve().parents[1]


class IndexerAdapterTests(unittest.TestCase):
    def test_gamma_market_normalization_preserves_raw_and_token_mapping(self) -> None:
        row = {
            "conditionId": "cond-a",
            "slug": "market-a",
            "question": "Will fixture happen?",
            "active": True,
            "closed": False,
            "endDate": "2026-12-31T00:00:00Z",
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": '["yes-token", "no-token"]',
            "events": [{"slug": "event-a"}],
            "unexpected": {"preserve": True},
        }

        market = normalize_gamma_market(row, updated_at="2026-05-21T10:00:00+00:00")
        mapping = token_condition_mapping_from_gamma_market(row)

        self.assertEqual(market.condition_id, "cond-a")
        self.assertEqual(market.event_slug, "event-a")
        self.assertTrue(market.active)
        self.assertFalse(market.closed)
        self.assertEqual(market.raw["unexpected"], {"preserve": True})
        self.assertEqual(token_mapping_for_token_id("yes-token", mapping).condition_id, "cond-a")
        self.assertEqual(token_mapping_for_token_id("yes-token", mapping).outcome, "YES")
        self.assertEqual(token_mapping_for_token_id("no-token", mapping).outcome, "NO")
        self.assertEqual(token_mapping_for_token_id("missing-token", mapping).condition_id, "unknown")

    def test_data_trade_normalization_prefers_usdc_size_and_builds_stable_id(self) -> None:
        row = {
            "transactionHash": "0xtx",
            "conditionId": "cond-a",
            "asset": "yes-token",
            "proxyWallet": "0xABCDEF",
            "side": "buy",
            "outcome": "Yes",
            "size": "100",
            "price": "0.40",
            "usdcSize": "41",
            "timestamp": "1770000000",
            "rawField": {"preserve": True},
        }

        trade = normalize_data_trade(row, source="activity")

        self.assertEqual(
            trade.stable_trade_id,
            "activity:0xtx:cond-a:yes-token:BUY:Yes:1770000000:100:0.4",
        )
        self.assertEqual(trade.wallet, "0xabcdef")
        self.assertEqual(trade.side, "BUY")
        self.assertEqual(trade.usdc_size, "41")
        self.assertEqual(trade.raw["rawField"], {"preserve": True})

    def test_unknown_trade_fields_remain_unknown_not_guessed(self) -> None:
        trade = normalize_data_trade({"transactionHash": "0xtx", "size": "5"}, source="trades")

        self.assertEqual(trade.condition_id, "unknown")
        self.assertEqual(trade.token_id, "unknown")
        self.assertEqual(trade.wallet, "unknown")
        self.assertEqual(trade.outcome, "unknown")
        self.assertIsNone(trade.usdc_size)
        self.assertIn(":unknown:unknown:unknown:unknown:", trade.stable_trade_id)

    def test_missing_market_optional_fields_remain_unknown_not_guessed(self) -> None:
        market = normalize_gamma_market({})

        self.assertEqual(market.condition_id, "unknown")
        self.assertEqual(market.slug, "unknown")
        self.assertEqual(market.event_slug, "unknown")
        self.assertEqual(market.question, "unknown")
        self.assertFalse(market.active)
        self.assertFalse(market.closed)
        self.assertEqual(market.raw, {})

    def test_invalid_token_mapping_payload_returns_unknown_mapping(self) -> None:
        mapping = token_condition_mapping_from_gamma_market(
            {
                "conditionId": "cond-a",
                "outcomes": '["Yes", "No"]',
                "clobTokenIds": "not-json",
            }
        )

        self.assertEqual(mapping, {})
        self.assertEqual(token_mapping_for_token_id("yes-token", mapping).condition_id, "unknown")

    def test_orderbook_snapshot_calculates_spread_depth_and_imbalance(self) -> None:
        snapshot = normalize_orderbook_snapshot(
            {
                "bids": [["0.40", "1000"], {"price": "0.39", "size": "200"}],
                "asks": [["0.42", "850"], {"price": "0.43", "size": "150"}],
                "raw": "preserved",
            },
            token_id="yes-token",
            condition_id="cond-a",
            timestamp="2026-05-21T10:00:00+00:00",
        )

        self.assertEqual(snapshot.best_bid, "0.4")
        self.assertEqual(snapshot.best_ask, "0.42")
        self.assertEqual(snapshot.spread_bps, "487.804878")
        self.assertEqual(snapshot.bid_depth, "1200")
        self.assertEqual(snapshot.ask_depth, "1000")
        self.assertEqual(snapshot.liquidity_imbalance, "0.090909")
        self.assertEqual(snapshot.raw["raw"], "preserved")

    def test_empty_orderbook_keeps_metrics_unknown(self) -> None:
        snapshot = normalize_orderbook_snapshot(
            {"bids": [], "asks": []},
            token_id="yes-token",
            condition_id="cond-a",
            timestamp="2026-05-21T10:00:00+00:00",
        )

        self.assertIsNone(snapshot.best_bid)
        self.assertIsNone(snapshot.best_ask)
        self.assertIsNone(snapshot.spread_bps)
        self.assertEqual(snapshot.bid_depth, "0")
        self.assertEqual(snapshot.ask_depth, "0")
        self.assertIsNone(snapshot.liquidity_imbalance)

    def test_malformed_orderbook_levels_are_ignored_but_raw_payload_is_preserved(self) -> None:
        snapshot = normalize_orderbook_snapshot(
            {
                "bids": [["not-a-price", "100"], ["0.40"]],
                "asks": [{"price": "0.42", "size": "bad-size"}],
                "unexpected": {"preserve": True},
            },
            token_id="yes-token",
            condition_id="cond-a",
            timestamp="2026-05-21T10:00:00+00:00",
        )

        self.assertIsNone(snapshot.best_bid)
        self.assertIsNone(snapshot.best_ask)
        self.assertEqual(snapshot.bid_depth, "0")
        self.assertEqual(snapshot.ask_depth, "0")
        self.assertEqual(snapshot.raw["unexpected"], {"preserve": True})

    def test_adapter_outputs_can_be_written_to_sidecar_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = IndexerStorage(Path(tmp) / "indexer.sqlite3")
            storage.init()
            storage.upsert_market(
                normalize_gamma_market(
                    {
                        "conditionId": "cond-a",
                        "slug": "market-a",
                        "eventSlug": "event-a",
                        "question": "Fixture?",
                        "active": "true",
                        "closed": "false",
                    }
                )
            )
            storage.upsert_trade(
                normalize_data_trade(
                    {
                        "transactionHash": "0xtx",
                        "conditionId": "cond-a",
                        "asset": "yes-token",
                        "proxyWallet": "0xabc",
                        "side": "BUY",
                        "outcome": "Yes",
                        "size": "10",
                        "price": "0.5",
                        "timestamp": "1770000000",
                    }
                )
            )
            storage.insert_orderbook_snapshot(
                normalize_orderbook_snapshot(
                    {"bids": [["0.49", "10"]], "asks": [["0.51", "12"]]},
                    token_id="yes-token",
                    condition_id="cond-a",
                    timestamp="2026-05-21T10:00:00+00:00",
                )
            )

            counts = storage.table_counts()

        self.assertEqual(counts["indexed_markets"], 1)
        self.assertEqual(counts["indexed_trades"], 1)
        self.assertEqual(counts["orderbook_snapshots"], 1)


class IndexerAdapterIsolationTests(unittest.TestCase):
    def test_indexer_adapters_are_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("app.indexer.adapters", source)
            self.assertNotIn("normalize_data_trade", source)


if __name__ == "__main__":
    unittest.main()
