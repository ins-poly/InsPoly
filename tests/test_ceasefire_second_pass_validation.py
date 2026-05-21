from __future__ import annotations

from decimal import Decimal
import unittest

from tools.ceasefire_second_pass_validation import (
    classify_inventory,
    extract_first_iso_datetime,
    normalize_trade,
)


class CeasefireSecondPassValidationTests(unittest.TestCase):
    def test_extract_first_iso_datetime_reads_json_ld_date(self) -> None:
        parsed = extract_first_iso_datetime('{"datePublished":"2026-04-29T17:26:05Z"}')
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.isoformat(), "2026-04-29T17:26:05+00:00")

    def test_inventory_classifies_yes_first_entry_and_addon(self) -> None:
        self.assertEqual(
            classify_inventory(side="BUY", outcome="Yes", position_before=Decimal("0"), target_market=True),
            "first-entry/opening exposure",
        )
        self.assertEqual(
            classify_inventory(side="BUY", outcome="Yes", position_before=Decimal("10"), target_market=True),
            "existing-position add-on",
        )

    def test_normalize_trade_uses_transaction_hash_and_notional(self) -> None:
        row = normalize_trade(
            {
                "proxyWallet": "0xABC",
                "transactionHash": "0xtrade",
                "side": "BUY",
                "outcome": "Yes",
                "asset": "yes-token",
                "conditionId": "0xCOND",
                "size": 10,
                "price": 0.25,
                "timestamp": 1777483286,
                "title": "Russia x Ukraine ceasefire by end of 2026?",
                "slug": "russia-x-ukraine-ceasefire-before-2027",
            }
        )
        self.assertEqual(row["wallet"], "0xabc")
        self.assertEqual(row["trade_id"], "0xtrade")
        self.assertEqual(row["condition_id"], "0xcond")
        self.assertEqual(row["notional_usdc"], Decimal("2.50"))


if __name__ == "__main__":
    unittest.main()
