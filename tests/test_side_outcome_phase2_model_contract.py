from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path
import unittest

from app.models import FlaggedCase, Market, Trade, WalletInspection
from app.side_outcome import UNKNOWN, normalize_side_outcome
import app.event_forensic as event_forensic
import app.scanner as scanner


ROOT = Path(__file__).resolve().parents[1]


def _trade(*, trade_id: str, side: str, outcome: str, price: str) -> Trade:
    from datetime import UTC, datetime

    return Trade(
        trade_id=trade_id,
        condition_id="cond-phase2",
        asset_id=f"asset-{outcome.lower()}",
        wallet="0xphase2",
        side=side,
        outcome=outcome,
        price=Decimal(price),
        size=Decimal("100"),
        timestamp=datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
        title="Phase 2 contract market",
        slug="phase2-contract-market",
        event_slug="phase2-contract-event",
    )


def _case(*, trade_id: str, side: str, outcome: str, price: str) -> FlaggedCase:
    trade = _trade(trade_id=trade_id, side=side, outcome=outcome, price=price)
    market = Market(
        market_id="market-phase2",
        condition_id=trade.condition_id,
        slug=trade.slug,
        question=trade.title,
        category="Politics",
        end_date=None,
        liquidity=Decimal("100000"),
        volume=Decimal("1000000"),
        outcomes=["Yes", "No"],
        token_ids=["asset-yes", "asset-no"],
        tags=[],
        site_categories=["Politics"],
    )
    return FlaggedCase(
        severity="Worth a Look",
        suspicion_score=40,
        confidence_score=80,
        review_priority="Medium",
        verdict="Needs review",
        trade_count_window=1,
        window_start=trade.timestamp.isoformat(),
        window_end=trade.timestamp.isoformat(),
        trade=trade,
        market=market,
        wallet_inspection=WalletInspection(
            address=trade.wallet,
            polygon_nonce=10,
            traded_market_count=10,
            recent_trade_count=10,
            unique_market_count=8,
            focus_market_count=2,
            first_trade_at=trade.timestamp.isoformat(),
            last_trade_at=trade.timestamp.isoformat(),
        ),
        subscores={},
        flags=[],
        explanation=[],
        reasons_against=[],
        raw_metrics={"trade_state": "increase", "opening_exposure_flag": "Yes"},
    )


def _phase2_probability(side: object, outcome: object, price: object) -> Decimal | None:
    return normalize_side_outcome(side, outcome, price).economic_side_probability


def _current_low_probability(raw_price: Decimal, threshold: Decimal = Decimal("0.30")) -> bool:
    return raw_price <= threshold


def _phase2_low_probability(side: object, outcome: object, price: object, threshold: Decimal = Decimal("0.30")) -> bool:
    probability = _phase2_probability(side, outcome, price)
    return bool(probability is not None and probability <= threshold)


def _current_near_certainty(raw_price: Decimal, threshold: Decimal = Decimal("0.95")) -> bool:
    return raw_price >= threshold


def _phase2_near_certainty(side: object, outcome: object, price: object, threshold: Decimal = Decimal("0.95")) -> bool:
    probability = _phase2_probability(side, outcome, price)
    return bool(probability is not None and probability >= threshold)


def _current_later_correctness(order_side: str, raw_outcome: str, price: object, winning_outcome: str) -> bool:
    del order_side, price
    return raw_outcome.strip().upper() == winning_outcome.strip().upper()


def _phase2_later_correctness(order_side: str, raw_outcome: str, price: object, winning_outcome: str) -> bool:
    normalized = normalize_side_outcome(order_side, raw_outcome, price)
    return normalized.economic_side != UNKNOWN and normalized.economic_side == winning_outcome.strip().upper()


class SideOutcomePhase2ModelContractTests(unittest.TestCase):
    def test_phase2_target_truth_table_for_buy_sell_yes_no(self) -> None:
        rows = [
            ("BUY", "YES", "0.20", "YES", Decimal("0.20"), "long_yes"),
            ("BUY", "NO", "0.80", "NO", Decimal("0.80"), "long_no"),
            ("SELL", "YES", "0.20", "NO", Decimal("0.80"), "long_no"),
            ("SELL", "NO", "0.80", "YES", Decimal("0.20"), "long_yes"),
        ]

        for side, outcome, price, economic_side, probability, direction in rows:
            with self.subTest(side=side, outcome=outcome):
                normalized = normalize_side_outcome(side, outcome, price)

                self.assertEqual(normalized.raw_order_side, side)
                self.assertEqual(normalized.raw_token_outcome, outcome)
                self.assertEqual(normalized.economic_side, economic_side)
                self.assertEqual(normalized.economic_side_probability, probability)
                self.assertEqual(normalized.economic_direction_normalized, direction)

    def test_malformed_or_missing_inputs_remain_unknown_not_zero(self) -> None:
        rows = [
            ("", "YES", "0.20"),
            ("BUY", "", "0.20"),
            ("SELL", "YES", ""),
            ("SELL", "MAYBE", "0.20"),
            ("SELL", "YES", "not-a-price"),
            ("SELL", "YES", "101%"),
        ]

        for side, outcome, price in rows:
            with self.subTest(side=side, outcome=outcome, price=price):
                normalized = normalize_side_outcome(side, outcome, price)

                self.assertEqual(normalized.economic_side, UNKNOWN)
                self.assertIsNone(normalized.economic_side_probability)
                self.assertEqual(normalized.economic_direction_normalized, UNKNOWN)

    def test_percent_and_decimal_inputs_share_the_same_contract(self) -> None:
        decimal_input = normalize_side_outcome("SELL", "YES", Decimal("0.199"))
        percent_input = normalize_side_outcome("SELL", "YES", "19.9%")
        whole_percent_input = normalize_side_outcome("SELL", "YES", "19.9")

        self.assertEqual(decimal_input.raw_token_price, Decimal("0.199"))
        self.assertEqual(percent_input.raw_token_price, Decimal("0.199"))
        self.assertEqual(whole_percent_input.raw_token_price, Decimal("0.199"))
        self.assertEqual(decimal_input.economic_side_probability, Decimal("0.801"))
        self.assertEqual(percent_input.economic_side_probability, Decimal("0.801"))
        self.assertEqual(whole_percent_input.economic_side_probability, Decimal("0.801"))

    def test_low_probability_threshold_inverts_for_opening_sells(self) -> None:
        sell_yes_raw_price = Decimal("0.20")
        sell_no_raw_price = Decimal("0.80")

        self.assertTrue(_current_low_probability(sell_yes_raw_price))
        self.assertFalse(_phase2_low_probability("SELL", "YES", sell_yes_raw_price))

        self.assertFalse(_current_low_probability(sell_no_raw_price))
        self.assertTrue(_phase2_low_probability("SELL", "NO", sell_no_raw_price))

    def test_near_certainty_threshold_inverts_for_opening_sells(self) -> None:
        sell_yes_raw_price = Decimal("0.05")
        sell_no_raw_price = Decimal("0.99")

        self.assertFalse(_current_near_certainty(sell_yes_raw_price))
        self.assertTrue(_phase2_near_certainty("SELL", "YES", sell_yes_raw_price))

        self.assertTrue(_current_near_certainty(sell_no_raw_price))
        self.assertFalse(_phase2_near_certainty("SELL", "NO", sell_no_raw_price))

    def test_event_forensic_later_correctness_inverts_for_opening_sells(self) -> None:
        self.assertFalse(_current_later_correctness("SELL", "YES", "0.20", "NO"))
        self.assertTrue(_phase2_later_correctness("SELL", "YES", "0.20", "NO"))

        self.assertFalse(_current_later_correctness("SELL", "NO", "0.80", "YES"))
        self.assertTrue(_phase2_later_correctness("SELL", "NO", "0.80", "YES"))

    def test_event_forensic_runtime_winner_rank_uses_economic_side(self) -> None:
        sell_yes = _case(trade_id="sell-yes-winner", side="SELL", outcome="YES", price="0.20")
        buy_yes = _case(trade_id="buy-yes-loser", side="BUY", outcome="YES", price="0.20")

        ranks = event_forensic._winning_entry_ranks(
            [sell_yes, buy_yes],
            {"cond-phase2": "No"},
        )

        self.assertEqual(ranks, {"sell-yes-winner": 1})

    def test_event_forensic_runtime_low_probability_winner_uses_economic_probability(self) -> None:
        sell_no = _case(trade_id="sell-no-low-economic", side="SELL", outcome="NO", price="0.80")

        score, flags, notes, reducers = event_forensic._event_forensic_score(
            case=sell_no,
            later_won=True,
            winner_rank=1,
            related_market_count=0,
            wallet_winning_entries=1,
            wallet_opening_entries=1,
        )

        self.assertGreater(score, 0)
        self.assertIn("later_correct", flags)
        self.assertIn("low_probability_winner", flags)
        self.assertIn("early_winning_entry", flags)
        self.assertTrue(notes)
        self.assertIsInstance(reducers, list)
        self.assertEqual(sell_no.raw_metrics["event_forensic_model_probability"], "0.2")
        self.assertEqual(sell_no.raw_metrics["event_forensic_model_probability_basis"], "economic_side_probability")

    def test_phase2_contract_keeps_phase3_out_of_scope_and_phase4_separate(self) -> None:
        capital_source = inspect.getsource(scanner._capital_at_risk_usdc)
        split_wallet_source = inspect.getsource(scanner._shared_funding_split_groups)
        timing_key_source = inspect.getsource(event_forensic._timing_cluster_key)

        self.assertNotIn("normalize_side_outcome", capital_source)
        self.assertNotIn("economic_side_probability", capital_source)
        self.assertIn("_cluster_direction_for_case", split_wallet_source)
        self.assertIn("clusterDirection", timing_key_source)

    def test_runtime_scorers_use_phase2_model_probability_without_phase3(self) -> None:
        score_trade_source = inspect.getsource(scanner._score_trade)
        event_score_source = inspect.getsource(event_forensic._event_forensic_score)
        split_wallet_source = inspect.getsource(scanner._shared_funding_split_groups)
        capital_source = inspect.getsource(scanner._capital_at_risk_usdc)

        self.assertIn("normalize_side_outcome", score_trade_source)
        self.assertIn("model_probability", score_trade_source)
        self.assertIn("_case_side_outcome_model", event_score_source)
        self.assertIn("entry_probability_basis", event_score_source)
        self.assertIn("_cluster_direction_for_case", split_wallet_source)
        self.assertNotIn("normalize_side_outcome", capital_source)
        self.assertNotIn("normalize_cluster_direction", capital_source)

    def test_event_forensic_timing_cluster_key_uses_phase4_cluster_direction(self) -> None:
        buy_no = {
            "marketSlug": "phase4-market",
            "orderSide": "BUY",
            "side": "NO",
            "clusterDirection": "long_no",
            "clusterNormalizationStatus": "normalized",
        }
        sell_yes = {
            "marketSlug": "phase4-market",
            "orderSide": "SELL",
            "side": "YES",
            "clusterDirection": "long_no",
            "clusterNormalizationStatus": "normalized",
        }
        malformed = {
            "marketSlug": "phase4-market",
            "orderSide": "SELL",
            "side": "MAYBE",
            "clusterDirection": UNKNOWN,
            "clusterNormalizationStatus": UNKNOWN,
        }

        self.assertEqual(event_forensic._timing_cluster_key(buy_no), event_forensic._timing_cluster_key(sell_yes))
        self.assertNotEqual(event_forensic._timing_cluster_key(sell_yes), event_forensic._timing_cluster_key(malformed))


if __name__ == "__main__":
    unittest.main()
