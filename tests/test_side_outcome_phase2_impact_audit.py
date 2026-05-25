from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from tools.side_outcome_phase2_impact_audit import (
    REPORT_TYPE,
    build_phase2_readiness_audit,
    evaluate_trade_record,
    load_records_from_paths,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


class SideOutcomePhase2ImpactAuditTests(unittest.TestCase):
    def test_sell_yes_low_probability_and_later_correctness_would_flip(self) -> None:
        row = {
            "artifactFamily": "event_forensic_json",
            "artifactPath": "fixture/event_analysis.json",
            "id": "sell-yes",
            "wallet": "0xabc",
            "conditionId": "cond",
            "orderSide": "SELL",
            "side": "YES",
            "price": "0.20",
            "openingExposure": True,
            "winningOutcome": "No",
            "laterWon": False,
            "existingModelClass": "Strong Risk",
            "hardEvidenceReviewTier": "Hard Evidence Review",
        }

        evaluated = evaluate_trade_record(row)

        self.assertEqual(evaluated["rawOrderSide"], "SELL")
        self.assertEqual(evaluated["rawTokenOutcome"], "YES")
        self.assertEqual(evaluated["rawTokenPrice"], "0.20")
        self.assertEqual(evaluated["economicSide"], "NO")
        self.assertEqual(evaluated["economicSideProbability"], "0.80")
        self.assertTrue(evaluated["lowProbability30Changed"])
        self.assertTrue(evaluated["lowProbability35Changed"])
        self.assertTrue(evaluated["directionChanged"])
        self.assertTrue(evaluated["laterCorrectnessChanged"])
        self.assertTrue(evaluated["sensitiveGateContext"])
        self.assertIn("event_forensic_later_correctness_would_invert", evaluated["qualityNotes"])

    def test_sell_yes_near_certainty_would_flip_from_low_raw_price(self) -> None:
        evaluated = evaluate_trade_record(
            {
                "artifactFamily": "scanner_report_json",
                "artifactPath": "fixture/scan.json",
                "trade_id": "near-sell-yes",
                "wallet": "0xabc",
                "condition_id": "cond",
                "side": "SELL",
                "outcome": "YES",
                "price": "0.05",
                "trade_state": "increase",
                "size": "1000",
                "price_implied_probability": "5.0%",
            }
        )

        self.assertTrue(evaluated["lowProbability30Changed"])
        self.assertTrue(evaluated["nearCertainty95Changed"])
        self.assertFalse(evaluated["nearCertainty98Changed"])
        self.assertEqual(evaluated["hypotheticalSellComplementExposure"], "950.00")
        self.assertIn(
            "opening_sell_requires_accounting_verification_before_capital_migration",
            evaluated["qualityNotes"],
        )

    def test_missing_fields_remain_unknown_not_zero(self) -> None:
        evaluated = evaluate_trade_record(
            {
                "artifactFamily": "event_forensic_suspicious_csv",
                "artifactPath": "fixture/suspicious_trades.csv",
                "side": "YES",
                "orderSide": "SELL",
            }
        )

        self.assertEqual(evaluated["rawTokenPrice"], "unknown")
        self.assertEqual(evaluated["economicSideProbability"], "unknown")
        self.assertFalse(evaluated["anyModelRelevantChange"])
        self.assertIn("missing_or_unknown_token_price", evaluated["qualityNotes"])

    def test_build_audit_reports_runtime_migration_baseline_without_side_effects(self) -> None:
        records = [
            {
                "artifactFamily": "scanner_report_json",
                "artifactPath": "fixture/scan.json",
                "trade_id": f"sell-yes-{index}",
                "wallet": f"0x{index}",
                "condition_id": "cond",
                "side": "SELL",
                "outcome": "YES",
                "price": "0.20",
                "trade_state": "increase",
            }
            for index in range(20)
        ]

        report = build_phase2_readiness_audit(records, root=ROOT)

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertEqual(report["gateDecision"], "ready_for_phase2_rfc")
        self.assertFalse(report["implementationAllowed"])
        self.assertFalse(report["phase2ImplementationAllowed"])
        self.assertTrue(report["baseline"]["scoreTradeImportsOrCallsSideOutcome"])
        self.assertTrue(report["baseline"]["eventForensicScoreImportsOrCallsSideOutcome"])
        self.assertGreater(report["summary"]["affectedUniqueTradeKeys"]["anyModelRelevantChange"], 0)

    def test_loads_static_json_and_csv_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scan = root / "scan.json"
            scan.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "severity": "Worth a Look",
                                "trade": {
                                    "trade_id": "scan-sell-yes",
                                    "wallet": "0xscan",
                                    "condition_id": "cond",
                                    "side": "SELL",
                                    "outcome": "YES",
                                    "price": "0.20",
                                },
                                "raw_metrics": {"trade_state": "increase"},
                                "flags": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            csv_path = root / "normalized_trades.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["trade_id", "wallet", "side", "outcome", "price"])
                writer.writeheader()
                writer.writerow({"trade_id": "recon-buy-no", "wallet": "0xrecon", "side": "BUY", "outcome": "No", "price": "0.80"})

            rows = load_records_from_paths(
                [
                    ("scanner_report_json", scan),
                    ("reconstruction_normalized_trades_csv", csv_path),
                ]
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["artifactFamily"], "scanner_report_json")
        self.assertEqual(rows[1]["artifactFamily"], "reconstruction_normalized_trades_csv")

    def test_cli_writes_outputs_and_runtime_paths_do_not_import_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_md = Path(tmp) / "audit.md"
            output_json = Path(tmp) / "audit.json"
            exit_code = main(
                [
                    "--root",
                    str(ROOT),
                    "--output-md",
                    str(output_md),
                    "--output-json",
                    str(output_json),
                    "--max-files",
                    "3",
                    "--max-rows-per-file",
                    "20",
                    "--quiet",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_md.exists())
            self.assertTrue(output_json.exists())
            self.assertIn("Gate decision", output_md.read_text(encoding="utf-8"))

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
            self.assertNotIn("side_outcome_phase2_impact_audit", source)


if __name__ == "__main__":
    unittest.main()
