from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.side_outcome_phase4_cluster_direction_audit import (
    REPORT_TYPE,
    build_phase4_cluster_direction_audit,
    discover_phase4_records,
    evaluate_cluster_row,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


class SideOutcomePhase4ClusterDirectionAuditTests(unittest.TestCase):
    def test_truth_table_maps_buy_sell_expressions_to_normalized_direction(self) -> None:
        rows = [
            ("BUY", "YES", "long_yes", "long_yes", False),
            ("SELL", "NO", "short_no", "long_yes", True),
            ("BUY", "NO", "long_no", "long_no", False),
            ("SELL", "YES", "short_yes", "long_no", True),
        ]

        for side, outcome, current, expected, changed in rows:
            with self.subTest(side=side, outcome=outcome):
                evaluated = evaluate_cluster_row(
                    {
                        "id": f"{side}-{outcome}",
                        "condition_id": "cond",
                        "side": side,
                        "outcome": outcome,
                        "price": "0.20",
                        "economic_direction": current,
                    }
                )

                self.assertEqual(evaluated["hypotheticalNormalizedClusterDirection"], expected)
                self.assertEqual(evaluated["directionWouldChange"], changed)

    def test_same_side_grouping_audit_merges_buy_yes_with_sell_no(self) -> None:
        report = build_phase4_cluster_direction_audit(
            [
                {
                    "id": "buy-yes",
                    "condition_id": "cond-yes",
                    "wallet": "0x1",
                    "side": "BUY",
                    "outcome": "YES",
                    "price": "0.20",
                    "economic_direction": "long_yes",
                },
                {
                    "id": "sell-no",
                    "condition_id": "cond-yes",
                    "wallet": "0x2",
                    "side": "SELL",
                    "outcome": "NO",
                    "price": "0.20",
                    "economic_direction": "short_no",
                    "hardEvidenceReviewTier": "Hard Evidence Review",
                },
            ]
        )

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertEqual(report["summary"]["affectedCounts"]["rowsWithDirectionChange"], 1)
        self.assertEqual(report["summary"]["affectedCounts"]["rowsInPreviouslySplitMergeGroups"], 2)
        self.assertEqual(report["summary"]["affectedCounts"]["sensitiveOverlapRows"], 1)

    def test_buy_yes_does_not_group_with_buy_no(self) -> None:
        report = build_phase4_cluster_direction_audit(
            [
                {
                    "id": "buy-yes",
                    "condition_id": "cond",
                    "wallet": "0x1",
                    "side": "BUY",
                    "outcome": "YES",
                    "price": "0.20",
                    "economic_direction": "long_yes",
                },
                {
                    "id": "buy-no",
                    "condition_id": "cond",
                    "wallet": "0x2",
                    "side": "BUY",
                    "outcome": "NO",
                    "price": "0.20",
                    "economic_direction": "long_no",
                },
            ]
        )

        self.assertNotIn("rowsInPreviouslySplitMergeGroups", report["summary"]["affectedCounts"])

    def test_old_row_fallback_is_not_safely_normalized_without_model_provenance(self) -> None:
        evaluated = evaluate_cluster_row(
            {
                "id": "old-row",
                "condition_id": "cond-old",
                "economic_direction": "short_yes",
            }
        )

        self.assertEqual(evaluated["currentClusterDirection"], "short_yes")
        self.assertEqual(evaluated["hypotheticalNormalizedClusterDirection"], "unknown")
        self.assertIn("old_economic_direction_only_not_safe_for_normalized_grouping", evaluated["qualityNotes"])

    def test_phase2_model_direction_can_be_audit_input_when_provenance_is_normalized(self) -> None:
        evaluated = evaluate_cluster_row(
            {
                "id": "phase2-row",
                "condition_id": "cond-model",
                "economic_direction": "short_yes",
                "model_economic_direction": "long_no",
                "side_outcome_normalization_status": "normalized",
            }
        )

        self.assertEqual(evaluated["currentClusterDirection"], "short_yes")
        self.assertEqual(evaluated["hypotheticalNormalizedClusterDirection"], "long_no")
        self.assertTrue(evaluated["directionWouldChange"])

    def test_malformed_row_does_not_crash_or_guess(self) -> None:
        evaluated = evaluate_cluster_row(
            {
                "id": "bad-row",
                "condition_id": "cond",
                "side": "SELL",
                "outcome": "MAYBE",
                "price": "0.20",
                "economic_direction": "short_yes",
            }
        )

        self.assertEqual(evaluated["hypotheticalNormalizedClusterDirection"], "unknown")
        self.assertFalse(evaluated["directionWouldChange"])
        self.assertIn("missing_or_malformed_raw_token_outcome", evaluated["qualityNotes"])

    def test_synthetic_fixtures_are_classified_separately(self) -> None:
        records, _artifacts, _skipped = discover_phase4_records(ROOT, max_files=1, max_rows_per_file=50)
        synthetic = [row for row in records if row.get("artifactEvidenceType") == "synthetic_fixture"]

        self.assertGreaterEqual(len(synthetic), 12)
        self.assertTrue(any(row.get("id") == "phase4-sell-yes-long-no" for row in synthetic))

    def test_phase3_capital_at_risk_is_not_applied_by_phase4_audit(self) -> None:
        evaluated = evaluate_cluster_row(
            {
                "id": "sell-yes",
                "condition_id": "cond",
                "side": "SELL",
                "outcome": "YES",
                "price": "0.20",
                "size": "100",
                "trade_state": "increase",
                "economic_direction": "short_yes",
                "capital_at_risk_usdc": "20",
            }
        )

        self.assertTrue(evaluated["phase3CapitalAtRiskBlockedOverlap"])
        self.assertFalse(evaluated["phase3CapitalAtRiskApplied"])

    def test_cli_writes_outputs_and_runtime_paths_do_not_import_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_md = Path(tmp) / "phase4.md"
            output_json = Path(tmp) / "phase4.json"
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
            self.assertEqual(payload["gateDecision"], "ready_for_phase4_implementation")
            self.assertFalse(payload["phase4RuntimeImplementationAllowed"])

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
            self.assertNotIn("side_outcome_phase4_cluster_direction_audit", source)


if __name__ == "__main__":
    unittest.main()
