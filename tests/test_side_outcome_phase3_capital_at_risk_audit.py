from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.side_outcome_phase3_capital_at_risk_audit import (
    REPORT_TYPE,
    build_phase3_capital_at_risk_audit,
    evaluate_capital_row,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


class SideOutcomePhase3CapitalAtRiskAuditTests(unittest.TestCase):
    def test_buy_yes_and_buy_no_use_cash_paid_semantics(self) -> None:
        buy_yes = evaluate_capital_row(
            {
                "id": "buy-yes",
                "side": "BUY",
                "outcome": "YES",
                "price": "0.20",
                "size": "100",
                "trade_state": "increase",
                "capital_at_risk_usdc": "20",
            }
        )
        buy_no = evaluate_capital_row(
            {
                "id": "buy-no",
                "side": "BUY",
                "outcome": "NO",
                "price": "0.20",
                "size": "100",
                "trade_state": "increase",
                "capital_at_risk_usdc": "20",
            }
        )

        self.assertEqual(buy_yes["hypotheticalEconomicCapitalAtRisk"], "20.00")
        self.assertEqual(buy_no["hypotheticalEconomicCapitalAtRisk"], "20.00")
        self.assertEqual(buy_yes["capitalDelta"], "0.00")
        self.assertEqual(buy_no["capitalDelta"], "0.00")

    def test_sell_yes_and_sell_no_use_complement_max_loss(self) -> None:
        sell_yes = evaluate_capital_row(
            {
                "id": "sell-yes",
                "side": "SELL",
                "outcome": "YES",
                "price": "0.20",
                "size": "100",
                "trade_state": "increase",
                "capital_at_risk_usdc": "20",
                "existingModelClass": "Strong Risk",
            }
        )
        sell_no = evaluate_capital_row(
            {
                "id": "sell-no",
                "side": "SELL",
                "outcome": "NO",
                "price": "0.20",
                "size": "100",
                "trade_state": "increase",
                "capital_at_risk_usdc": "20",
            }
        )

        self.assertEqual(sell_yes["hypotheticalEconomicCapitalAtRisk"], "80.00")
        self.assertEqual(sell_no["hypotheticalEconomicCapitalAtRisk"], "80.00")
        self.assertEqual(sell_yes["capitalDelta"], "60.00")
        self.assertEqual(sell_no["capitalDelta"], "60.00")
        self.assertTrue(sell_yes["sensitivePhase2Context"])
        self.assertIn("opening_sell_complement_exposure_requires_accounting_gate", sell_yes["qualityNotes"])

    def test_sell_yes_near_certainty_can_reduce_economic_max_loss(self) -> None:
        evaluated = evaluate_capital_row(
            {
                "id": "sell-yes-near",
                "side": "SELL",
                "outcome": "YES",
                "price": "0.98",
                "size": "100",
                "trade_state": "increase",
                "capital_at_risk_usdc": "98",
            }
        )

        self.assertEqual(evaluated["currentReportedCapitalAtRisk"], "98.00")
        self.assertEqual(evaluated["hypotheticalEconomicCapitalAtRisk"], "2.00")
        self.assertEqual(evaluated["capitalDelta"], "-96.00")

    def test_usdc_size_is_cash_source_but_sell_still_needs_complement_gate(self) -> None:
        buy = evaluate_capital_row(
            {
                "id": "buy-usdc",
                "side": "BUY",
                "outcome": "YES",
                "price": "0.20",
                "size": "100",
                "usdcSize": "21",
                "trade_state": "increase",
                "capital_at_risk_usdc": "20",
            }
        )
        sell = evaluate_capital_row(
            {
                "id": "sell-usdc",
                "side": "SELL",
                "outcome": "YES",
                "price": "0.20",
                "size": "100",
                "usdcSize": "20",
                "trade_state": "increase",
                "capital_at_risk_usdc": "20",
            }
        )

        self.assertEqual(buy["observedCashSource"], "usdcSize")
        self.assertEqual(buy["hypotheticalEconomicCapitalAtRisk"], "21.00")
        self.assertIn("source_cash_disagreement", buy["qualityNotes"])
        self.assertEqual(sell["hypotheticalEconomicCapitalAtRisk"], "80.00")
        self.assertIn("sell_usdc_size_recorded_as_observed_cash_not_max_loss", sell["qualityNotes"])

    def test_percent_price_and_malformed_rows_stay_deterministic(self) -> None:
        percent = evaluate_capital_row(
            {
                "id": "percent",
                "side": "SELL",
                "outcome": "NO",
                "price": "20%",
                "size": "100",
                "trade_state": "increase",
                "capital_at_risk_usdc": "20",
            }
        )
        malformed = evaluate_capital_row(
            {
                "id": "malformed",
                "side": "SELL",
                "outcome": "YES",
                "price": "bad",
                "size": "100",
                "trade_state": "increase",
                "capital_at_risk_usdc": "20",
            }
        )

        self.assertEqual(percent["rawTokenPrice"], "0.2")
        self.assertEqual(percent["hypotheticalEconomicCapitalAtRisk"], "80.00")
        self.assertEqual(malformed["hypotheticalEconomicCapitalAtRisk"], "unknown")
        self.assertIn("missing_or_malformed_raw_token_price", malformed["qualityNotes"])

    def test_missing_size_and_old_report_notional_only_are_not_rescored(self) -> None:
        missing_size = evaluate_capital_row(
            {
                "id": "missing-size",
                "side": "SELL",
                "outcome": "YES",
                "price": "0.20",
                "trade_state": "increase",
            }
        )
        old_report = evaluate_capital_row(
            {
                "id": "old-report",
                "trade_state": "increase",
                "trade_notional_usdc": "20",
                "capital_at_risk_usdc": "20",
                "price_implied_probability": "20.0%",
            }
        )

        self.assertEqual(missing_size["hypotheticalEconomicCapitalAtRisk"], "unknown")
        self.assertIn("missing_or_unknown_size", missing_size["qualityNotes"])
        self.assertEqual(old_report["hypotheticalEconomicCapitalAtRisk"], "unknown")
        self.assertIn("old_report_notional_only_not_safe_for_rescoring", old_report["qualityNotes"])

    def test_build_report_blocks_phase3_when_sell_rows_change(self) -> None:
        records = [
            {
                "id": "buy",
                "side": "BUY",
                "outcome": "YES",
                "price": "0.20",
                "size": "100",
                "trade_state": "increase",
                "capital_at_risk_usdc": "20",
            },
            {
                "id": "sell",
                "side": "SELL",
                "outcome": "YES",
                "price": "0.20",
                "size": "100",
                "trade_state": "increase",
                "capital_at_risk_usdc": "20",
            },
        ]

        report = build_phase3_capital_at_risk_audit(records)

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertEqual(report["gateDecision"], "keep_phase3_blocked")
        self.assertFalse(report["implementationAllowed"])
        self.assertEqual(report["summary"]["affectedCounts"]["sellRowsWithCapitalDelta"], 1)

    def test_cli_writes_outputs_and_runtime_paths_do_not_import_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_md = Path(tmp) / "phase3.md"
            output_json = Path(tmp) / "phase3.json"
            exit_code = main(
                [
                    "--root",
                    str(ROOT),
                    "--output-md",
                    str(output_md),
                    "--output-json",
                    str(output_json),
                    "--max-files",
                    "30",
                    "--max-rows-per-file",
                    "25",
                    "--quiet",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_md.exists())
            self.assertTrue(output_json.exists())
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["gateDecision"], "keep_phase3_blocked")
            self.assertFalse(payload["phase3RuntimeImplementationAllowed"])

        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/browser_ui.html",
            "app/browser_event_forensic_ui.html",
            "app/storage.py",
            "app/polymarket.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("side_outcome_phase3_capital_at_risk_audit", source)


if __name__ == "__main__":
    unittest.main()
