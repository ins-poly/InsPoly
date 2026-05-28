from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import unittest

from tools.event_forensic_granular_pagination_probe import (
    GranularProbeBounds,
    _combine_window_results,
    _time_chunks,
    build_probe_plan,
    collect_trade_window_pages,
    select_probe_market,
    validate_probe_plan,
)


def _api_trade(
    trade_id: str,
    *,
    condition_id: str = "0xcond",
    wallet: str = "0xabc",
    timestamp: int = 1_777_000_000,
    price: str = "0.50",
    size: str = "1000",
) -> dict[str, object]:
    return {
        "transactionHash": trade_id,
        "conditionId": condition_id,
        "asset": "asset",
        "proxyWallet": wallet,
        "side": "BUY",
        "outcome": "Yes",
        "price": price,
        "size": size,
        "timestamp": timestamp,
        "title": "Market",
        "slug": "market-slug",
        "eventSlug": "event-slug",
    }


class EventForensicGranularPaginationProbeTests(unittest.TestCase):
    def test_selects_market_with_highest_reference_overlap(self) -> None:
        selection = {
            "eventSlug": "event",
            "selectedMarkets": [
                {"conditionId": "0xa", "marketSlug": "a"},
                {"conditionId": "0xb", "marketSlug": "b"},
            ],
        }
        previous = {
            "marketRows": [
                {"conditionId": "0xa", "baselineRows": 6000, "baselineCandidateFloorRows": 3100, "baselineTruncated": True},
                {"conditionId": "0xb", "baselineRows": 5000, "baselineCandidateFloorRows": 3100, "baselineTruncated": True},
            ]
        }
        reference = {
            "display_trades": [
                {"conditionId": "0xb", "marketSlug": "b", "eventForensicScore": 90, "weakHistoryNearCertaintyReviewDemotion": True}
            ]
        }

        selected = select_probe_market(selection=selection, previous_collection=previous, reference_report=reference)

        self.assertIsNotNone(selected)
        self.assertEqual(selected["conditionId"], "0xb")
        self.assertEqual(selected["referenceHighReviewRows"], 1)

    def test_probe_plan_enforces_one_market_bounds(self) -> None:
        selection = {"eventSlug": "event", "selectedMarkets": [{"conditionId": "0xa", "marketSlug": "a"}]}
        selected_market = {"conditionId": "0xa", "marketSlug": "a"}

        violations = validate_probe_plan(
            selection=selection,
            selected_market=selected_market,
            bounds=GranularProbeBounds(max_markets=2),
        )

        self.assertIn("max_markets_must_be_1", violations)

    def test_build_probe_plan_is_offline_and_sidecar_only(self) -> None:
        selection = {"eventSlug": "event", "selectedMarkets": [{"conditionId": "0xa", "marketSlug": "a"}]}

        plan = build_probe_plan(selection=selection)

        self.assertEqual(plan["gateDecision"], "granular_probe_plan_ready")
        self.assertFalse(plan["networkUsed"])
        self.assertFalse(plan["productionPaginationChanged"])
        self.assertFalse(plan["wholeEventCompletenessClaim"])

    def test_time_chunks_are_non_overlapping(self) -> None:
        self.assertEqual(_time_chunks(10, 17, 4), [(10, 11), (12, 13), (14, 15), (16, 17)])
        self.assertEqual(_time_chunks(10, 17, 1), [(10, 17)])

    def test_collect_pages_detects_duplicate_page_and_cursor_stall(self) -> None:
        repeated = [_api_trade("t1"), _api_trade("t2", wallet="0xdef")]

        def fetch_json(_url: str, params: dict[str, object]) -> object:
            offset = int(params["offset"])
            if offset in {0, 2, 4}:
                return list(repeated)
            return []

        result = collect_trade_window_pages(
            fetch_json=fetch_json,
            condition_id="0xcond",
            start_ts=1_776_000_000,
            end_ts=1_778_000_000,
            filter_cash_amount=None,
            bounds=GranularProbeBounds(max_pages_per_window=4, page_size=2, max_no_new_pages=2),
        )

        self.assertEqual(result["uniqueRows"], 2)
        self.assertGreaterEqual(result["duplicatePageCount"], 2)
        self.assertGreaterEqual(result["cursorStallCount"], 2)
        self.assertTrue(result["noNewRowPlateauDetected"])
        self.assertEqual(result["stopReason"], "no_new_row_plateau")

    def test_collect_pages_detects_provider_hard_cap(self) -> None:
        def fetch_json(_url: str, params: dict[str, object]) -> object:
            offset = int(params["offset"])
            page = offset // 100
            return [_api_trade(f"t{page}-{index}", wallet=f"0x{page:02x}{index:02x}") for index in range(100)]

        result = collect_trade_window_pages(
            fetch_json=fetch_json,
            condition_id="0xcond",
            start_ts=1_776_000_000,
            end_ts=1_778_000_000,
            filter_cash_amount=Decimal("250"),
            bounds=GranularProbeBounds(max_pages_per_window=31, page_size=100),
        )

        self.assertEqual(result["pagesAttempted"], 31)
        self.assertTrue(result["providerHardCapDetected"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["stopReason"], "provider_hard_cap_full_last_page")

    def test_combine_window_results_accepts_nested_combined_results(self) -> None:
        def fetch_json(_url: str, params: dict[str, object]) -> object:
            offset = int(params["offset"])
            if offset == 0:
                return [_api_trade("t1"), _api_trade("t2")]
            return []

        bounds = GranularProbeBounds(max_pages_per_window=3, page_size=2)
        leaf = collect_trade_window_pages(
            fetch_json=fetch_json,
            condition_id="0xcond",
            start_ts=1_776_000_000,
            end_ts=1_778_000_000,
            filter_cash_amount=None,
            bounds=bounds,
        )
        nested = _combine_window_results([leaf], bounds=bounds)
        combined = _combine_window_results([nested], bounds=bounds)

        self.assertEqual(nested["uniqueRows"], 2)
        self.assertEqual(combined["uniqueRows"], 2)

    def test_collect_pages_respects_time_window_stop(self) -> None:
        old = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())

        def fetch_json(_url: str, _params: dict[str, object]) -> object:
            return [_api_trade("old", timestamp=old)]

        result = collect_trade_window_pages(
            fetch_json=fetch_json,
            condition_id="0xcond",
            start_ts=1_776_000_000,
            end_ts=1_778_000_000,
            filter_cash_amount=None,
            bounds=GranularProbeBounds(max_pages_per_window=3, page_size=100),
        )

        self.assertEqual(result["uniqueRows"], 0)
        self.assertEqual(result["stopReason"], "older_than_window")


if __name__ == "__main__":
    unittest.main()
