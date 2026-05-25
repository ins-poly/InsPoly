from __future__ import annotations

import json
from pathlib import Path
import unittest

from app.shadow_metrics import (
    ADVISORY_CONTEXT,
    ADVISORY_NONE,
    ADVISORY_NOTABLE,
    SHADOW_ENTRY_PRICE_EDGE,
    SHADOW_LOW_ODDS_POSITION_SIZE,
    SHADOW_MICROSTRUCTURE_CONTEXT,
    SHADOW_NET_POSITION_PNL,
    SHADOW_PUBLIC_VOLUME_CAUTION,
    SHADOW_STRUCTURAL_CONTEXT,
    SHADOW_TIMING_CONTEXT,
    SHADOW_WIN_RATE_CONFIDENCE,
    STATUS_AVAILABLE,
    STATUS_NOT_TRIGGERED,
    STATUS_UNKNOWN,
    assert_no_production_fields,
    compute_shadow_metrics,
    compute_shadow_metrics_from_payload,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shadow_metrics"


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class ShadowMetricsTests(unittest.TestCase):
    def test_low_odds_large_position_is_advisory_notable_only(self) -> None:
        report = compute_shadow_metrics_from_payload(fixture("low_probability_large_buy"))
        low_odds = report.metric(SHADOW_LOW_ODDS_POSITION_SIZE)
        edge = report.metric(SHADOW_ENTRY_PRICE_EDGE)
        pnl = report.metric(SHADOW_NET_POSITION_PNL)

        self.assertEqual(low_odds.status, STATUS_AVAILABLE)
        self.assertEqual(low_odds.advisory_level, ADVISORY_NOTABLE)
        self.assertEqual(low_odds.value, "5700")
        self.assertEqual(edge.advisory_level, ADVISORY_CONTEXT)
        self.assertEqual(pnl.status, STATUS_AVAILABLE)
        assert_no_production_fields(report.to_dict())

    def test_low_odds_with_timing_context_remains_context_not_verdict(self) -> None:
        report = compute_shadow_metrics_from_payload(fixture("low_probability_timing_context"))

        self.assertEqual(report.metric(SHADOW_LOW_ODDS_POSITION_SIZE).advisory_level, ADVISORY_CONTEXT)
        self.assertEqual(report.metric(SHADOW_TIMING_CONTEXT).advisory_level, ADVISORY_CONTEXT)
        self.assertNotIn("risk_level", json.dumps(report.to_dict()))
        self.assertNotIn("Hard Evidence Review", json.dumps(report.to_dict()))

    def test_high_volume_diversified_wallet_is_negative_control(self) -> None:
        report = compute_shadow_metrics_from_payload(fixture("public_high_volume_negative"))

        self.assertEqual(report.metric(SHADOW_LOW_ODDS_POSITION_SIZE).status, STATUS_NOT_TRIGGERED)
        self.assertEqual(report.metric(SHADOW_PUBLIC_VOLUME_CAUTION).advisory_level, ADVISORY_CONTEXT)
        self.assertEqual(report.metric(SHADOW_WIN_RATE_CONFIDENCE).advisory_level, ADVISORY_NONE)

    def test_stale_resolution_arbitrage_is_not_low_odds_advisory(self) -> None:
        report = compute_shadow_metrics_from_payload(fixture("stale_resolution_arbitrage_negative"))
        low_odds = report.metric(SHADOW_LOW_ODDS_POSITION_SIZE)

        self.assertEqual(low_odds.status, STATUS_NOT_TRIGGERED)
        self.assertEqual(low_odds.advisory_level, ADVISORY_NONE)
        self.assertIn("stale_resolution_context_only", low_odds.notes)

    def test_split_wallet_shared_funder_context_is_input_only(self) -> None:
        report = compute_shadow_metrics_from_payload(fixture("split_wallet_input_only"))
        structural = report.metric(SHADOW_STRUCTURAL_CONTEXT)

        self.assertEqual(structural.status, STATUS_AVAILABLE)
        self.assertEqual(structural.advisory_level, ADVISORY_CONTEXT)
        assert_no_production_fields(report.to_dict())

    def test_small_sample_perfect_win_rate_is_discounted(self) -> None:
        report = compute_shadow_metrics_from_payload(fixture("small_sample_win_rate_discount"))
        win_rate = report.metric(SHADOW_WIN_RATE_CONFIDENCE)

        self.assertEqual(win_rate.status, STATUS_NOT_TRIGGERED)
        self.assertEqual(win_rate.advisory_level, ADVISORY_NONE)
        self.assertIn("small_sample_discounted", win_rate.notes)

    def test_larger_sample_win_rate_anomaly_is_advisory_context(self) -> None:
        report = compute_shadow_metrics_from_payload(fixture("larger_sample_win_rate_anomaly"))
        win_rate = report.metric(SHADOW_WIN_RATE_CONFIDENCE)

        self.assertEqual(win_rate.status, STATUS_AVAILABLE)
        self.assertEqual(win_rate.advisory_level, ADVISORY_CONTEXT)
        self.assertEqual(win_rate.details["resolvedTrades"], "80")

    def test_microstructure_wide_spread_is_context_only(self) -> None:
        report = compute_shadow_metrics_from_payload(fixture("microstructure_wide_spread"))
        micro = report.metric(SHADOW_MICROSTRUCTURE_CONTEXT)

        self.assertEqual(micro.status, STATUS_AVAILABLE)
        self.assertEqual(micro.advisory_level, ADVISORY_CONTEXT)
        self.assertEqual(micro.details["maxSpreadBps"], "650")

    def test_missing_fields_remain_unknown(self) -> None:
        report = compute_shadow_metrics(
            [{"wallet": "wallet-a", "side": "BUY", "size": "10"}],
            wallet_stats={},
        )

        self.assertEqual(report.metric(SHADOW_LOW_ODDS_POSITION_SIZE).status, STATUS_UNKNOWN)
        self.assertEqual(report.metric(SHADOW_WIN_RATE_CONFIDENCE).status, STATUS_UNKNOWN)
        self.assertEqual(report.metric(SHADOW_NET_POSITION_PNL).status, STATUS_UNKNOWN)

    def test_near_certainty_add_on_is_negative_control(self) -> None:
        report = compute_shadow_metrics(
            [
                {
                    "wallet": "wallet-a",
                    "condition_id": "cond-a",
                    "token_id": "yes-a",
                    "outcome": "YES",
                    "side": "BUY",
                    "size": "10000",
                    "price": "0.91",
                    "usdcSize": "9100",
                }
            ],
            wallet_stats={"resolved_trades": 10, "winning_trades": 5},
        )

        low_odds = report.metric(SHADOW_LOW_ODDS_POSITION_SIZE)
        self.assertEqual(low_odds.status, STATUS_NOT_TRIGGERED)
        self.assertIn("near_certainty_context_only", low_odds.notes)

    def test_assert_no_production_fields_rejects_forbidden_payloads(self) -> None:
        with self.assertRaises(ValueError):
            assert_no_production_fields({"shadowMetrics": [], "risk_level": "Strong Risk"})


class ShadowMetricIsolationTests(unittest.TestCase):
    def test_shadow_metrics_helper_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
            "app/browser_desktop.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("shadow_metrics", source)


if __name__ == "__main__":
    unittest.main()
