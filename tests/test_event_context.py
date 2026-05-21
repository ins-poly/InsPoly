from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from app.event_context import EventContextResolver
from app.models import Market, Trade


def _market(**overrides: object) -> Market:
    payload = {
        "market_id": "market-1",
        "condition_id": "cond-1",
        "slug": "example-market",
        "question": "Will example outcome happen?",
        "category": "Politics",
        "end_date": None,
        "liquidity": Decimal("1000"),
        "volume": Decimal("5000"),
        "outcomes": ["Yes", "No"],
        "token_ids": ["asset-yes", "asset-no"],
        "tags": [],
    }
    payload.update(overrides)
    return Market(**payload)


def _trade(**overrides: object) -> Trade:
    payload = {
        "trade_id": "tx-1",
        "condition_id": "cond-1",
        "asset_id": "asset-yes",
        "wallet": "0xabc",
        "side": "BUY",
        "outcome": "Yes",
        "price": Decimal("0.25"),
        "size": Decimal("1000"),
        "timestamp": datetime(2026, 1, 1, 12, 30, tzinfo=UTC),
        "title": "Will example outcome happen?",
        "slug": "example-market",
        "event_slug": "example-event",
    }
    payload.update(overrides)
    return Trade(**payload)


class EventContextResolverTests(unittest.TestCase):
    def test_resolver_matches_condition_id_and_sets_public_timeline_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "event_timelines.csv").write_text(
                "\n".join(
                    [
                        "timeline_id,condition_id,event_timezone,broad_report_at,official_confirmation_at,public_outcome_at,stale_resolution,reality_oracle_gap_label",
                        "tl-1,cond-1,Asia/Tehran,2026-01-01T11:00:00Z,2026-01-01T11:30:00Z,2026-01-01T12:00:00Z,false,oracle_lag",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            context = EventContextResolver(data_dir).resolve(
                trade=_trade(),
                market=_market(),
                trade_domain="Geopolitics",
                market_deadline_flag=False,
            )

        self.assertTrue(context.matched_offline_row)
        self.assertEqual(context.timeline_id, "tl-1")
        self.assertEqual(context.timeline_source, "event_timelines.csv")
        self.assertEqual(context.event_timezone, "Asia/Tehran")
        self.assertEqual(context.public_knowledge_at, datetime(2026, 1, 1, 11, 0, tzinfo=UTC))
        self.assertEqual(context.public_outcome_at, datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
        self.assertTrue(context.stale_resolution_annotation)
        self.assertEqual(context.reality_oracle_gap_label, "oracle_lag")

    def test_resolver_without_timeline_file_preserves_no_match_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = EventContextResolver(Path(tmp)).resolve(
                trade=_trade(title="Will Iran event happen?", event_slug="iran-event"),
                market=_market(question="Will Iran event happen?", slug="iran-event"),
                trade_domain="Geopolitics",
                market_deadline_flag=True,
            )

        self.assertFalse(context.matched_offline_row)
        self.assertIsNone(context.timeline_id)
        self.assertIsNone(context.public_knowledge_at)
        self.assertEqual(context.event_timezone, "Asia/Tehran")
        self.assertTrue(context.market_deadline_flag)


if __name__ == "__main__":
    unittest.main()
