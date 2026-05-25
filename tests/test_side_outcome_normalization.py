from __future__ import annotations

from decimal import Decimal
import unittest

from app.side_outcome import UNKNOWN, normalize_cluster_direction, normalize_side_outcome


class SideOutcomeNormalizationTests(unittest.TestCase):
    def test_truth_table_for_binary_buy_sell_rows(self) -> None:
        rows = [
            ("BUY", "Yes", Decimal("0.20"), "YES", Decimal("0.20"), "long_yes"),
            ("SELL", "Yes", Decimal("0.20"), "NO", Decimal("0.80"), "long_no"),
            ("BUY", "No", Decimal("0.80"), "NO", Decimal("0.80"), "long_no"),
            ("SELL", "No", Decimal("0.80"), "YES", Decimal("0.20"), "long_yes"),
        ]

        for side, outcome, price, economic_side, economic_probability, direction in rows:
            normalized = normalize_side_outcome(side, outcome, price)
            self.assertEqual(normalized.raw_order_side, side)
            self.assertEqual(normalized.raw_token_outcome, outcome.upper())
            self.assertEqual(normalized.raw_token_price, price)
            self.assertEqual(normalized.economic_side, economic_side)
            self.assertEqual(normalized.economic_side_probability, economic_probability)
            self.assertEqual(normalized.economic_direction_normalized, direction)

    def test_unknown_side_outcome_or_price_stays_unknown_not_zero(self) -> None:
        for side, outcome, price in (
            ("MINT", "Yes", Decimal("0.20")),
            ("BUY", "Maybe", Decimal("0.20")),
            ("BUY", "Yes", "not-a-price"),
            ("BUY", "Yes", Decimal("120.0")),
        ):
            normalized = normalize_side_outcome(side, outcome, price)
            self.assertEqual(normalized.economic_side, UNKNOWN)
            self.assertIsNone(normalized.economic_side_probability)
            self.assertEqual(normalized.economic_direction_normalized, UNKNOWN)
            self.assertEqual(normalized.economic_side_probability_label, "Economic side: unknown")

    def test_percent_input_and_decimal_labels_are_stable(self) -> None:
        normalized = normalize_side_outcome("sell", "yes", "19.9%")

        self.assertEqual(normalized.raw_token_price, Decimal("0.199"))
        self.assertEqual(normalized.economic_side_probability, Decimal("0.801"))
        self.assertEqual(normalized.raw_token_price_label, "Raw token: Yes @ 19.9%")
        self.assertEqual(normalized.economic_side_probability_label, "Economic side: No @ 80.1%")
        self.assertEqual(
            normalized.to_raw_metrics(),
            {
                "raw_token_outcome": "YES",
                "raw_order_side": "SELL",
                "raw_token_price": "0.199",
                "raw_token_price_label": "Raw token: Yes @ 19.9%",
                "economic_side": "NO",
                "economic_side_probability": "0.801",
                "economic_side_probability_label": "Economic side: No @ 80.1%",
                "economic_direction_normalized": "long_no",
                "model_probability_basis": "economic_side_probability",
                "model_economic_direction": "long_no",
                "side_outcome_normalization_status": "normalized",
                "side_outcome_fallback_reason": "",
            },
        )

    def test_cluster_direction_helper_uses_phase4_truth_table(self) -> None:
        rows = [
            ("BUY", "YES", "0.20", "long_yes"),
            ("SELL", "NO", "0.20", "long_yes"),
            ("BUY", "NO", "0.20", "long_no"),
            ("SELL", "YES", "0.20", "long_no"),
        ]

        for side, outcome, price, expected in rows:
            with self.subTest(side=side, outcome=outcome):
                normalized = normalize_cluster_direction(side, outcome, price)
                self.assertEqual(normalized.cluster_direction, expected)
                self.assertEqual(normalized.cluster_direction_basis, "economic_direction_normalized")
                self.assertEqual(normalized.cluster_normalization_status, "normalized")
                self.assertEqual(normalized.cluster_direction_fallback_reason, "")

    def test_cluster_direction_helper_keeps_unknown_inputs_out_of_grouping(self) -> None:
        normalized = normalize_cluster_direction("SELL", "MAYBE", "0.20")

        self.assertEqual(normalized.cluster_direction, UNKNOWN)
        self.assertEqual(normalized.cluster_direction_basis, UNKNOWN)
        self.assertEqual(normalized.cluster_normalization_status, UNKNOWN)
        self.assertIn("raw_token_outcome", normalized.cluster_direction_fallback_reason)


if __name__ == "__main__":
    unittest.main()
