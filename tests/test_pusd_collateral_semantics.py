from __future__ import annotations

import json
from pathlib import Path
import unittest

from app.polymarket_collateral_semantics import (
    classify_collateral_source_fact,
    classify_trade_collateral_semantics,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "pusd_collateral_semantics" / "static_fixture_facts.json"


class PusdCollateralSemanticsTests(unittest.TestCase):
    def test_pusd_symbol_without_verified_source_remains_unknown(self) -> None:
        row = classify_trade_collateral_semantics({"collateralTokenSymbol": "pUSD"})

        self.assertEqual(row["collateralStatus"], "unknown")
        self.assertFalse(row["fundingRuntimeSafe"])
        self.assertFalse(row["capitalRuntimeSafe"])
        self.assertIn("pusd_symbol_without_verified_address_remains_unknown", row["qualityNotes"])

    def test_unverified_blog_source_is_rejected(self) -> None:
        fact = classify_collateral_source_fact(
            {
                "sourceType": "blog",
                "role": "pusd_token",
                "symbol": "pUSD",
                "address": "0x3333333333333333333333333333333333333333",
            }
        )

        self.assertEqual(fact["factStatus"], "rejected")
        self.assertFalse(fact["productionTruth"])
        self.assertFalse(fact["runtimeIntegrationAllowed"])
        self.assertIn("source_type_not_acceptable_for_collateral_truth", fact["qualityNotes"])

    def test_static_fixture_fact_can_match_without_becoming_production_truth(self) -> None:
        facts = json.loads(FIXTURE.read_text(encoding="utf-8"))["facts"]

        row = classify_trade_collateral_semantics({"collateralTokenSymbol": "pUSD"}, source_facts=facts)

        self.assertEqual(row["collateralStatus"], "known_static_fixture_only")
        self.assertFalse(row["matchedSourceFact"]["productionTruth"])
        self.assertFalse(row["runtimeIntegrationAllowed"])
        self.assertIn("fixture_collateral_context_not_production_truth", row["qualityNotes"])

    def test_verified_source_still_requires_explicit_runtime_approval(self) -> None:
        row = classify_trade_collateral_semantics(
            {"collateralTokenSymbol": "pUSD"},
            source_facts=[
                {
                    "sourceType": "verified_contract",
                    "role": "pusd_token",
                    "symbol": "pUSD",
                    "address": "0x4444444444444444444444444444444444444444",
                    "productionTruth": True,
                }
            ],
        )

        self.assertEqual(row["collateralStatus"], "verified_static_source_no_runtime")
        self.assertFalse(row["fundingRuntimeSafe"])
        self.assertFalse(row["capitalRuntimeSafe"])
        self.assertFalse(row["runtimeIntegrationAllowed"])
        self.assertIn("verified_source_still_requires_runtime_approval", row["qualityNotes"])

    def test_missing_address_is_unknown_not_none(self) -> None:
        fact = classify_collateral_source_fact(
            {
                "sourceType": "official_docs",
                "sourceUrl": "https://example.invalid/docs",
                "role": "clob_collateral",
                "symbol": "pUSD",
            }
        )

        self.assertEqual(fact["factStatus"], "unknown")
        self.assertEqual(fact["address"], "unknown")
        self.assertIn("missing_contract_address", fact["qualityNotes"])

    def test_collateral_semantics_helper_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/funding_context.py",
            "app/polymarket.py",
            "app/storage.py",
            "app/browser_desktop.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("polymarket_collateral_semantics", source)


if __name__ == "__main__":
    unittest.main()
