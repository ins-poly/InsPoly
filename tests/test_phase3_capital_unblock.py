from __future__ import annotations

from pathlib import Path
import unittest

from tools.phase3_capital_ledger_crosscheck import build_ledger_crosscheck, evaluate_ledger_capital_row
from tools.phase3_capital_source_inventory import (
    QUALITY_SAFE_BUY_CASH,
    QUALITY_SAFE_SELL_MAX_LOSS,
    QUALITY_UNSAFE_OLD_NOTIONAL_ONLY,
    QUALITY_UNKNOWN_MISSING_FIELDS,
    build_source_inventory,
    classify_source_row,
)
from tools.phase3_capital_unblock_impact_audit import build_unblock_impact_audit


ROOT = Path(__file__).resolve().parents[1]


class Phase3CapitalUnblockTests(unittest.TestCase):
    def test_source_inventory_classifies_buy_cash_safe_case(self) -> None:
        row = classify_source_row(
            {
                "side": "BUY",
                "outcome": "YES",
                "price": "0.20",
                "size": "100",
                "artifactFamily": "archive_trades_csv",
                "artifactEvidenceType": "real_local",
            }
        )

        self.assertEqual(row["sourceQuality"], QUALITY_SAFE_BUY_CASH)
        self.assertTrue(row["hasSize"])
        self.assertIn("buy_cash_can_use_explicit_cash_or_size_price", row["qualityNotes"])

    def test_source_inventory_classifies_sell_max_loss_safe_for_direct_raw_source(self) -> None:
        row = classify_source_row(
            {
                "side": "SELL",
                "outcome": "NO",
                "price": "0.20",
                "size": "100",
                "usdcSize": "20",
                "artifactFamily": "archive_trades_csv",
                "artifactEvidenceType": "real_local",
            }
        )

        self.assertEqual(row["sourceQuality"], QUALITY_SAFE_SELL_MAX_LOSS)
        self.assertTrue(row["runtimeSafeCandidate"])
        self.assertIn("usdcSize_is_observed_cash_not_max_loss", row["qualityNotes"])

    def test_old_notional_only_row_is_unsafe(self) -> None:
        row = classify_source_row(
            {
                "trade_notional_usdc": "20",
                "capital_at_risk_usdc": "20",
                "artifactFamily": "scanner_report_json",
                "artifactEvidenceType": "real_local",
            }
        )

        self.assertEqual(row["sourceQuality"], QUALITY_UNSAFE_OLD_NOTIONAL_ONLY)
        self.assertIn("notional_only_cannot_be_reinterpreted", row["qualityNotes"])

    def test_missing_fields_remain_unknown(self) -> None:
        row = classify_source_row({"side": "SELL", "outcome": "YES", "artifactFamily": "known_case_benchmark"})

        self.assertEqual(row["sourceQuality"], QUALITY_UNKNOWN_MISSING_FIELDS)
        self.assertIn("missing_price", row["qualityNotes"])
        self.assertIn("missing_size", row["qualityNotes"])

    def test_ledger_crosscheck_treats_sell_usdc_size_as_observed_cash_not_max_loss(self) -> None:
        row = evaluate_ledger_capital_row(
            {
                "wallet": "wallet-a",
                "condition_id": "cond-a",
                "token_id": "yes-a",
                "outcome": "YES",
                "side": "SELL",
                "size": "100",
                "price": "0.20",
                "usdcSize": "20",
            }
        )

        self.assertEqual(row["ledgerDerivedEconomicExposure"], "80.00")
        self.assertEqual(row["ledgerExposureSource"], "size_complement_price_max_loss")
        self.assertIn("usdcSize_is_observed_cash_not_sell_max_loss", row["qualityNotes"])

    def test_ledger_crosscheck_runs_offline_against_fixture_dirs(self) -> None:
        report = build_ledger_crosscheck([ROOT / "tests/fixtures/polymarket_ledger_artifacts/profile_like_good"])

        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertGreaterEqual(report["summary"]["rowsEvaluated"], 1)

    def test_impact_audit_gate_stays_partial_when_old_notional_rows_remain(self) -> None:
        inventory = build_source_inventory(
            [
                {
                    "side": "SELL",
                    "outcome": "YES",
                    "price": "0.20",
                    "size": "100",
                    "artifactFamily": "archive_trades_csv",
                    "artifactEvidenceType": "real_local",
                },
                {
                    "trade_notional_usdc": "20",
                    "artifactFamily": "scanner_report_json",
                    "artifactEvidenceType": "real_local",
                },
            ]
        )
        ledger = {
            "summary": {
                "safeSellMaxLossRows": 1,
                "rowsWhereUsdcSizeIsObservedCashNotMaxLoss": 1,
            }
        }
        old = {
            "summary": {
                "affectedCounts": {
                    "rowsWithCapitalDelta": 1,
                    "sensitiveOverlapRows": 1,
                }
            }
        }

        report = build_unblock_impact_audit(old_audit=old, source_inventory=inventory, ledger_crosscheck=ledger)

        self.assertEqual(report["gateDecision"], "phase3_ready_for_partial_safe_sidecar_only")
        self.assertFalse(report["runtimeImplementationAllowed"])

    def test_unblock_tools_are_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/browser_ui.html",
            "app/browser_event_forensic_ui.html",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("phase3_capital_source_inventory", source)
            self.assertNotIn("phase3_capital_ledger_crosscheck", source)
            self.assertNotIn("phase3_capital_unblock_impact_audit", source)


if __name__ == "__main__":
    unittest.main()
