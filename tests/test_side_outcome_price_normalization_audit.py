from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.event_context import EventContext
from app.funding_context import FundingContext
from app.models import Market, Trade, WalletInspection
from app.archive_scanner import _trade_row
from app.scanner import (
    _annotate_side_outcome_raw_metrics,
    _capital_at_risk_usdc,
    _classify_execution_state,
    _economic_direction,
    _favorable_moves_after_entry,
    _score_trade,
)
from app.wallet_analytics import (
    ActivitySummary,
    ClosedPositionSummary,
    OpenPositionSummary,
    WalletPerformance,
)


def _trade(
    *,
    trade_id: str,
    side: str,
    outcome: str,
    price: str,
    asset_id: str,
    timestamp: datetime | None = None,
    wallet: str = "0xaudit",
) -> Trade:
    return Trade(
        trade_id=trade_id,
        condition_id="cond-side-audit",
        asset_id=asset_id,
        wallet=wallet,
        side=side,
        outcome=outcome,
        price=Decimal(price),
        size=Decimal("1000"),
        timestamp=timestamp or datetime(2026, 5, 7, 12, 0, tzinfo=UTC),
        title="Will the U.S. invade Iran before 2027?",
        slug="will-the-us-invade-iran-before-2027",
        event_slug="will-the-us-invade-iran-before-2027",
    )


def _market() -> Market:
    return Market(
        market_id="market-side-audit",
        condition_id="cond-side-audit",
        slug="will-the-us-invade-iran-before-2027",
        question="Will the U.S. invade Iran before 2027?",
        category="Politics",
        end_date=datetime(2027, 1, 1, tzinfo=UTC).isoformat(),
        liquidity=Decimal("250000"),
        volume=Decimal("2000000"),
        outcomes=["YES", "NO"],
        token_ids=["asset-yes", "asset-no"],
        tags=[],
        site_categories=["Middle East"],
    )


def _wallet_inspection() -> WalletInspection:
    return WalletInspection(
        address="0xaudit",
        polygon_nonce=12,
        traded_market_count=12,
        recent_trade_count=12,
        unique_market_count=10,
        focus_market_count=3,
        first_trade_at=datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        last_trade_at=datetime(2026, 5, 7, tzinfo=UTC).isoformat(),
        dominant_domain_label="Middle East",
        domain_concentration_score=0.60,
        public_model_specialist_flag=False,
        domain_counts={"Middle East": 3},
    )


def _wallet_performance() -> WalletPerformance:
    return WalletPerformance(
        closed_positions=[],
        closed_summary=ClosedPositionSummary(
            total=0,
            wins=0,
            losses=0,
            win_rate_value=0.0,
            win_rate_threshold=50.0,
            win_rate_clears_threshold=False,
            total_realized_pnl=0.0,
            average_return=0.0,
            economic_sample_size=0,
            economic_win_rate_value=0.0,
            economic_win_rate_threshold=50.0,
            economic_win_rate_clears_threshold=False,
            zombie_loss_count=0,
            zombie_loss_notional=0.0,
            redemption_avoidance_ratio=0.0,
            de_facto_loss_count=0,
            formal_win_rate_may_be_overstated=False,
        ),
        open_summary=OpenPositionSummary(
            count=0,
            notional=0.0,
            unrealized_pnl=0.0,
            unrealized_pct=0.0,
            zombie_positions=0,
            zombie_notional=0.0,
        ),
        activity_summary=ActivitySummary(
            bot_likeness_score=0.0,
            microtrade_ratio=0.0,
            median_trade_size=1000.0,
            trade_burst_rate=1.0,
            median_intertrade_interval_minutes=60.0,
            market_breadth=10,
            manual_review_value_score=80.0,
            low_analyst_value_flag=False,
        ),
    )


def _event_context() -> EventContext:
    return EventContext(
        trade_domain="Middle East",
        event_timezone="Asia/Tehran",
        local_event_time="2026-05-07 15:30",
        local_event_hour=15,
        off_hours_flag=False,
        market_deadline_flag=False,
        matched_offline_row=False,
    )


def _scored_case(trade: Trade, market_window_trades: list[Trade] | None = None):
    trades = market_window_trades or [trade]
    case = _score_trade(
        trade=trade,
        market=_market(),
        trade_domain="Middle East",
        wallet_inspection=_wallet_inspection(),
        wallet_performance=_wallet_performance(),
        wallet_window_trades=[trade],
        wallet_history_trades=[trade],
        market_window_trades=trades,
        domain_window_trades=trades,
        event_context=_event_context(),
        funding_context=FundingContext(funding_found=False),
        include_below_threshold=True,
    )
    assert case is not None
    return case


class SideOutcomePriceNormalizationAuditTests(unittest.TestCase):
    def test_current_execution_state_truth_table_for_opening_rows(self) -> None:
        rows = [
            ("BUY", "YES", "0.20", "asset-yes", "increase_long", "long_yes", Decimal("200.00")),
            ("SELL", "YES", "0.20", "asset-yes", "increase_short", "short_yes", Decimal("200.00")),
            ("BUY", "NO", "0.80", "asset-no", "increase_long", "long_no", Decimal("800.00")),
            ("SELL", "NO", "0.80", "asset-no", "increase_short", "short_no", Decimal("800.00")),
        ]

        for side, outcome, price, asset_id, state, direction, capital in rows:
            trade = _trade(
                trade_id=f"{side}-{outcome}",
                side=side,
                outcome=outcome,
                price=price,
                asset_id=asset_id,
            )
            execution_state = _classify_execution_state(trade, [], [])
            self.assertEqual(execution_state, state)
            self.assertEqual(_economic_direction(trade, execution_state), direction)
            self.assertEqual(_capital_at_risk_usdc(trade, execution_state), capital)

    def test_buy_token_probabilities_match_current_raw_price_field(self) -> None:
        buy_yes = _scored_case(_trade(trade_id="buy-yes", side="BUY", outcome="YES", price="0.20", asset_id="asset-yes"))
        buy_no = _scored_case(_trade(trade_id="buy-no", side="BUY", outcome="NO", price="0.80", asset_id="asset-no"))

        self.assertEqual(buy_yes.raw_metrics["price_implied_probability"], "20.0%")
        self.assertEqual(buy_no.raw_metrics["price_implied_probability"], "80.0%")

    def test_phase1_additive_fields_preserve_raw_probability_and_expose_economic_side(self) -> None:
        case = _scored_case(_trade(trade_id="sell-yes", side="SELL", outcome="YES", price="0.20", asset_id="asset-yes"))
        _annotate_side_outcome_raw_metrics([case])

        self.assertEqual(case.raw_metrics["price_implied_probability"], "20.0%")
        self.assertEqual(case.raw_metrics["economic_direction"], "short_yes")
        self.assertEqual(case.raw_metrics["raw_token_outcome"], "YES")
        self.assertEqual(case.raw_metrics["raw_order_side"], "SELL")
        self.assertEqual(case.raw_metrics["raw_token_price"], "0.20")
        self.assertEqual(case.raw_metrics["raw_token_price_label"], "Raw token: Yes @ 20.0%")
        self.assertEqual(case.raw_metrics["economic_side"], "NO")
        self.assertEqual(case.raw_metrics["economic_side_probability"], "0.80")
        self.assertEqual(case.raw_metrics["economic_side_probability_label"], "Economic side: No @ 80.0%")
        self.assertEqual(case.raw_metrics["economic_direction_normalized"], "long_no")
        self.assertEqual(case.raw_metrics["model_probability"], "0.80")
        self.assertEqual(case.raw_metrics["model_probability_basis"], "economic_side_probability")
        self.assertEqual(case.raw_metrics["side_outcome_normalization_status"], "normalized")
        self.assertNotIn("low_probability_conviction", case.flags)

    def test_repricing_move_for_opening_sell_uses_short_token_direction(self) -> None:
        entry = _trade(
            trade_id="sell-yes-entry",
            side="SELL",
            outcome="YES",
            price="0.20",
            asset_id="asset-yes",
        )
        future = _trade(
            trade_id="yes-price-down",
            side="BUY",
            outcome="YES",
            price="0.10",
            asset_id="asset-yes",
            timestamp=entry.timestamp + timedelta(minutes=20),
            wallet="0xpeer",
        )
        later_observed = _trade(
            trade_id="yes-window-observed",
            side="BUY",
            outcome="YES",
            price="0.12",
            asset_id="asset-yes",
            timestamp=entry.timestamp + timedelta(minutes=70),
            wallet="0xlate",
        )

        moves = _favorable_moves_after_entry([entry, future, later_observed], entry)

        self.assertEqual(moves["15m"], Decimal("0"))
        self.assertEqual(moves["1h"], Decimal("0.10"))

    def test_opening_sell_yes_preserves_raw_price_field_and_adds_model_probability(self) -> None:
        case = _scored_case(_trade(trade_id="sell-yes", side="SELL", outcome="YES", price="0.20", asset_id="asset-yes"))

        self.assertEqual(case.raw_metrics["price_implied_probability"], "20.0%")
        self.assertEqual(case.raw_metrics["economic_side_probability"], "0.80")
        self.assertEqual(case.raw_metrics["model_probability"], "0.80")

    def test_opening_sell_no_preserves_raw_price_field_and_adds_model_probability(self) -> None:
        case = _scored_case(_trade(trade_id="sell-no", side="SELL", outcome="NO", price="0.80", asset_id="asset-no"))

        self.assertEqual(case.raw_metrics["price_implied_probability"], "80.0%")
        self.assertEqual(case.raw_metrics["economic_side_probability"], "0.20")
        self.assertEqual(case.raw_metrics["model_probability"], "0.20")

    def test_low_probability_flags_should_use_economic_side_probability_for_sell_yes(self) -> None:
        case = _scored_case(_trade(trade_id="sell-yes-low-prob", side="SELL", outcome="YES", price="0.20", asset_id="asset-yes"))

        self.assertNotIn("low_probability_conviction", case.flags)

    def test_near_certainty_flags_should_use_economic_side_probability_for_sell_yes(self) -> None:
        case = _scored_case(_trade(trade_id="sell-yes-near", side="SELL", outcome="YES", price="0.05", asset_id="asset-yes"))

        self.assertIn("near_certainty_trade", case.flags)
        self.assertEqual(case.raw_metrics["price_implied_probability"], "5.0%")
        self.assertEqual(case.raw_metrics["model_probability"], "0.95")

    def test_same_side_cluster_should_group_sell_yes_with_buy_no_as_no_exposure(self) -> None:
        entry = _trade(
            trade_id="sell-yes-cluster",
            side="SELL",
            outcome="YES",
            price="0.20",
            asset_id="asset-yes",
        )
        buy_no_peer = _trade(
            trade_id="buy-no-peer",
            side="BUY",
            outcome="NO",
            price="0.80",
            asset_id="asset-no",
            timestamp=entry.timestamp + timedelta(minutes=5),
            wallet="0xpeer",
        )

        case = _scored_case(entry, [entry, buy_no_peer])

        self.assertEqual(case.raw_metrics["cluster_wallets_30m_same_side"], "1")
        self.assertEqual(case.raw_metrics["economic_direction"], "short_yes")
        self.assertEqual(case.raw_metrics["cluster_direction"], "long_no")
        self.assertEqual(case.raw_metrics["cluster_normalization_status"], "normalized")

    def test_same_side_cluster_groups_buy_yes_with_sell_no_as_yes_exposure(self) -> None:
        entry = _trade(
            trade_id="buy-yes-cluster",
            side="BUY",
            outcome="YES",
            price="0.20",
            asset_id="asset-yes",
        )
        sell_no_peer = _trade(
            trade_id="sell-no-peer",
            side="SELL",
            outcome="NO",
            price="0.80",
            asset_id="asset-no",
            timestamp=entry.timestamp + timedelta(minutes=5),
            wallet="0xpeer",
        )

        case = _scored_case(entry, [entry, sell_no_peer])

        self.assertEqual(case.raw_metrics["cluster_wallets_30m_same_side"], "1")
        self.assertEqual(case.raw_metrics["economic_direction"], "long_yes")
        self.assertEqual(case.raw_metrics["cluster_direction"], "long_yes")

    def test_same_side_cluster_does_not_group_buy_yes_with_buy_no(self) -> None:
        entry = _trade(
            trade_id="buy-yes-no-cluster",
            side="BUY",
            outcome="YES",
            price="0.20",
            asset_id="asset-yes",
        )
        buy_no_peer = _trade(
            trade_id="buy-no-not-peer",
            side="BUY",
            outcome="NO",
            price="0.80",
            asset_id="asset-no",
            timestamp=entry.timestamp + timedelta(minutes=5),
            wallet="0xpeer",
        )

        case = _scored_case(entry, [entry, buy_no_peer])

        self.assertEqual(case.raw_metrics["cluster_wallets_30m_same_side"], "0")

    def test_archive_trade_row_exports_additive_cluster_direction_fields(self) -> None:
        row = _trade_row(
            _trade(
                trade_id="archive-sell-yes-cluster",
                side="SELL",
                outcome="YES",
                price="0.20",
                asset_id="asset-yes",
            )
        )

        self.assertEqual(row["economic_direction_normalized"], "long_no")
        self.assertEqual(row["cluster_direction"], "long_no")
        self.assertEqual(row["cluster_direction_basis"], "economic_direction_normalized")
        self.assertEqual(row["cluster_normalization_status"], "normalized")

    def test_browser_scanner_display_should_label_entry_as_token_price_when_un_normalized(self) -> None:
        html = Path("app/browser_ui.html").read_text(encoding="utf-8")

        self.assertIn("Token price", html)
        self.assertIn("Raw token:", html)
        self.assertIn("Economic side:", html)
        self.assertNotIn("Entry chance", html)
