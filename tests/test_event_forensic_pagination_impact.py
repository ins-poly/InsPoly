from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from app.models import Trade
from tools.event_forensic_bounded_deeper_collection import (
    PaginationCollectionBounds,
    _collect_window,
    _time_chunks,
    build_collection_plan,
    validate_bounds,
)
from tools.event_forensic_pagination_impact import (
    REPORT_TYPE,
    build_impact_assessment,
    build_truncation_inventory,
)


ROOT = Path(__file__).resolve().parents[1]


def _trade(trade_id: str, *, wallet: str = "0xabc", condition_id: str = "0xcond", notional: str = "300") -> Trade:
    price = Decimal("0.50")
    size = Decimal(notional) / price
    return Trade(
        trade_id=trade_id,
        condition_id=condition_id,
        asset_id="asset",
        wallet=wallet,
        side="BUY",
        outcome="Yes",
        price=price,
        size=size,
        timestamp=datetime(2026, 5, 1, tzinfo=UTC),
        title="Market",
        slug="market-slug",
        event_slug="event-slug",
    )


class FakeTradeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch_trades_in_range(self, **kwargs: object) -> list[Trade]:
        self.calls.append(dict(kwargs))
        condition_id = (kwargs.get("condition_ids") or ["0xcond"])[0]  # type: ignore[index]
        filtered = kwargs.get("filter_cash_amount") is not None
        rows = [_trade(f"base-{index}", condition_id=condition_id) for index in range(3)]
        if filtered:
            rows.append(_trade("extra-filtered", condition_id=condition_id, notional="600"))
        return rows


class EventForensicPaginationImpactTests(unittest.TestCase):
    def test_inventory_counts_truncated_market_review_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "event_forensic_outputs/event_forensic_20260526_010203"
            report_dir.mkdir(parents=True)
            report = {
                "analysis_scope": "event",
                "event": {"slug": "event-slug", "marketCount": 2},
                "summary": {
                    "analysis_market_count": 2,
                    "total_event_market_count": 2,
                    "raw_trade_count": 6200,
                    "candidate_trade_count": 3,
                    "truncated_market_count": 1,
                },
                "markets": [
                    {
                        "conditionId": "0xcond",
                        "marketSlug": "market-slug",
                        "market": "Market",
                        "tradeCount": 3100,
                        "candidateTradeCount": 3,
                    }
                ],
                "evidence_warnings": ["1 market(s) hit the public trade pagination cap."],
                "display_trades": [
                    {
                        "id": "t1",
                        "conditionId": "0xcond",
                        "marketSlug": "market-slug",
                        "eventForensicScore": 80,
                        "weakHistoryNearCertaintyReviewDemotion": True,
                        "hardEvidenceSources": ["funding"],
                    }
                ],
            }
            (report_dir / "event_analysis.json").write_text(json.dumps(report), encoding="utf-8")

            payload = build_truncation_inventory(root)

        self.assertEqual(payload["reportType"], REPORT_TYPE)
        self.assertFalse(payload["networkUsed"])
        self.assertEqual(payload["summary"]["truncatedReportCount"], 1)
        self.assertEqual(payload["summary"]["truncatedMarketRows"], 1)
        self.assertEqual(payload["summary"]["highReviewRowsAffectedByTruncation"], 1)
        self.assertEqual(payload["summary"]["weakHistoryDemotionRowsAffectedByTruncation"], 1)
        self.assertEqual(payload["summary"]["sensitiveRowsAffectedByTruncation"], 1)

    def test_inventory_preserves_old_report_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / ".inspoly_event_forensic_analyzer/reports"
            reports.mkdir(parents=True)
            (reports / "event_forensic_20260526_010203.json").write_text(
                json.dumps({"analysis_scope": "event", "event": {"slug": "legacy"}, "summary": {"candidate_trade_count": 1}}),
                encoding="utf-8",
            )

            payload = build_truncation_inventory(root)

        self.assertEqual(payload["summary"]["reportsEvaluated"], 1)
        self.assertEqual(payload["summary"]["truncatedReportCount"], 0)
        self.assertFalse(payload["savedArtifactsMutated"])

    def test_collection_plan_blocks_unsafe_bounds(self) -> None:
        selection = {
            "eventSlug": "event",
            "selectedMarkets": [{"conditionId": f"0x{i}", "marketSlug": f"m{i}"} for i in range(9)],
            "wholeEventCompletenessClaim": False,
        }
        bounds = PaginationCollectionBounds(max_markets=8)
        self.assertIn("selected_market_count_exceeds_bound", validate_bounds(selection, bounds))

        plan = build_collection_plan(selection=selection, bounds=bounds)

        self.assertEqual(plan["gateDecision"], "bounded_collection_blocked")
        self.assertFalse(plan["networkUsed"])

    def test_time_chunks_cover_window_without_overlap(self) -> None:
        self.assertEqual(_time_chunks(10, 19, 2), [(10, 14), (15, 19)])
        self.assertEqual(_time_chunks(10, 19, 1), [(10, 19)])

    def test_collect_window_dedupes_filtered_backfill(self) -> None:
        client = FakeTradeClient()
        bounds = PaginationCollectionBounds(max_pages_per_slice=4, page_size=100)

        result = _collect_window(
            client,  # type: ignore[arg-type]
            condition_id="0xcond",
            start_ts=1,
            end_ts=2,
            min_notional=Decimal("250"),
            bounds=bounds,
        )

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(result["rows"], 4)
        self.assertEqual(result["candidateFloorRows"], 4)
        self.assertFalse(result["truncated"])

    def test_impact_assessment_material_delta_requires_rfc(self) -> None:
        inventory = {
            "summary": {
                "reportsEvaluated": 1,
                "truncatedReportCount": 1,
                "truncatedMarketRows": 1,
                "highReviewRowsAffectedByTruncation": 1,
            }
        }
        collection = {
            "networkUsed": True,
            "summary": {
                "gateDecision": "bounded_collection_complete",
                "rawRowsDelta": 42,
                "candidateFloorRowsDelta": 3,
                "boundsHit": False,
            },
        }

        assessment = build_impact_assessment(inventory_payload=inventory, collection_payload=collection)

        self.assertEqual(assessment["gateDecision"], "pagination_material_impact_found_needs_rfc")
        self.assertTrue(assessment["summary"]["materialImpactObserved"])

    def test_inventory_tool_source_has_no_network_imports(self) -> None:
        source = (ROOT / "tools/event_forensic_pagination_impact.py").read_text(encoding="utf-8")
        self.assertNotIn("urllib", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("PolymarketClient", source)


if __name__ == "__main__":
    unittest.main()
