from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.post_side_outcome_benchmark_replay import (
    REPORT_TYPE,
    build_benchmark_replay,
    build_corpus_inventory,
    evaluate_post_side_outcome_record,
    inspect_source_safety,
    load_generated_audit_summaries,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


class PostSideOutcomeBenchmarkReplayTests(unittest.TestCase):
    def test_offline_replay_has_no_network_or_production_integration(self) -> None:
        report = build_benchmark_replay(ROOT, max_files=3, max_rows_per_file=20, max_bytes=500_000)

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertFalse(report["runtimeCodeChanged"])
        self.assertGreater(report["summary"]["recordsEvaluated"], 0)

    def test_buy_yes_and_sell_no_share_economic_cluster(self) -> None:
        buy_yes = evaluate_post_side_outcome_record(
            {
                "artifactFamily": "test_fixture",
                "id": "buy-yes",
                "condition_id": "cond",
                "side": "BUY",
                "outcome": "YES",
                "price": "0.20",
                "economic_direction": "long_yes",
            }
        )
        sell_no = evaluate_post_side_outcome_record(
            {
                "artifactFamily": "test_fixture",
                "id": "sell-no",
                "condition_id": "cond",
                "side": "SELL",
                "outcome": "NO",
                "price": "0.20",
                "economic_direction": "short_no",
            }
        )

        self.assertEqual(buy_yes["clusterDirection"], "long_yes")
        self.assertEqual(sell_no["clusterDirection"], "long_yes")
        self.assertTrue(sell_no["phase4DirectionChanged"])

    def test_buy_no_and_sell_yes_share_economic_cluster(self) -> None:
        buy_no = evaluate_post_side_outcome_record(
            {
                "artifactFamily": "test_fixture",
                "id": "buy-no",
                "condition_id": "cond",
                "side": "BUY",
                "outcome": "NO",
                "price": "0.20",
                "economic_direction": "long_no",
            }
        )
        sell_yes = evaluate_post_side_outcome_record(
            {
                "artifactFamily": "test_fixture",
                "id": "sell-yes",
                "condition_id": "cond",
                "side": "SELL",
                "outcome": "YES",
                "price": "0.20",
                "economic_direction": "short_yes",
            }
        )

        self.assertEqual(buy_no["clusterDirection"], "long_no")
        self.assertEqual(sell_yes["clusterDirection"], "long_no")
        self.assertTrue(sell_yes["phase4DirectionChanged"])

    def test_sell_yes_low_price_is_not_low_probability_yes_after_phase2(self) -> None:
        row = evaluate_post_side_outcome_record(
            {
                "artifactFamily": "test_fixture",
                "id": "sell-yes-low",
                "condition_id": "cond",
                "side": "SELL",
                "outcome": "YES",
                "price": "0.20",
                "trade_state": "increase",
                "economic_direction": "short_yes",
            }
        )

        self.assertEqual(row["economicSide"], "NO")
        self.assertEqual(row["economicSideProbability"], "0.80")
        self.assertTrue(row["phase2LowProbabilityChanged"])
        self.assertTrue(row["phase2ModelRelevantChange"])

    def test_malformed_row_falls_back_without_guessing(self) -> None:
        row = evaluate_post_side_outcome_record(
            {
                "artifactFamily": "test_fixture",
                "id": "bad-row",
                "condition_id": "cond",
                "side": "SELL",
                "outcome": "MAYBE",
                "price": "bad",
            }
        )

        self.assertEqual(row["economicSide"], "unknown")
        self.assertEqual(row["economicSideProbability"], "unknown")
        self.assertEqual(row["clusterDirection"], "unknown")
        self.assertTrue(row["missingOrMalformed"])

    def test_phase3_capital_at_risk_remains_blocked_overlap_only(self) -> None:
        row = evaluate_post_side_outcome_record(
            {
                "artifactFamily": "test_fixture",
                "id": "sell-risk",
                "condition_id": "cond",
                "side": "SELL",
                "outcome": "YES",
                "price": "0.20",
                "size": "100",
                "trade_state": "increase",
                "capital_at_risk_usdc": "20",
            }
        )

        self.assertTrue(row["phase3CapitalAtRiskBlockedOverlap"])
        self.assertFalse(row["phase3RuntimeImplementationAllowed"])

    def test_generated_audit_output_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audits = root / "side_outcome_audits"
            audits.mkdir()
            (audits / "audit.json").write_text(
                json.dumps(
                    {
                        "reportType": "example_audit",
                        "schemaVersion": "v1",
                        "gateDecision": "example_gate",
                        "summary": {"rows": 3},
                    }
                ),
                encoding="utf-8",
            )

            summaries = load_generated_audit_summaries(root)

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["reportType"], "example_audit")
        self.assertEqual(summaries[0]["gateDecision"], "example_gate")

    def test_inventory_classifies_side_outcome_fixtures_without_requiring_generated_outputs(self) -> None:
        inventory = build_corpus_inventory(ROOT)
        summary = inventory["summary"]
        counts = inventory["summary"]["classificationCounts"]

        self.assertGreater(counts.get("synthetic_fixture", 0), 0)
        self.assertEqual(summary["generatedAuditOutputCount"], counts.get("generated_audit_output", 0))

    def test_old_report_row_safe_load_shape(self) -> None:
        row = evaluate_post_side_outcome_record(
            {
                "artifactFamily": "scanner_report_json",
                "artifactPath": "old/scan.json",
                "trade_id": "old-sell-yes",
                "wallet": "0xold",
                "condition_id": "cond",
                "side": "SELL",
                "outcome": "YES",
                "price_implied_probability": "20.0%",
                "trade_state": "increase",
            }
        )

        self.assertEqual(row["rawTokenPrice"], "0.2")
        self.assertEqual(row["economicSide"], "NO")
        self.assertEqual(row["economicSideProbability"], "0.8")

    def test_source_scan_confirms_no_forbidden_runtime_surfaces(self) -> None:
        scan = inspect_source_safety(ROOT)

        self.assertFalse(scan["phase3CapitalHelperUsesSideOutcome"])
        self.assertFalse(scan["storageSchemaSideOutcomeMarker"])
        self.assertFalse(scan["polymarketLiveSideOutcomeMarker"])
        self.assertFalse(scan["browserClusterSortFilterMarker"])

    def test_cli_writes_inventory_and_replay_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.json"
            replay = Path(tmp) / "replay.json"
            exit_code = main(
                [
                    "--root",
                    str(ROOT),
                    "--inventory-json",
                    str(inventory),
                    "--replay-json",
                    str(replay),
                    "--max-files",
                    "4",
                    "--max-rows-per-file",
                    "10",
                    "--quiet",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(inventory.exists())
            self.assertTrue(replay.exists())
            payload = json.loads(replay.read_text(encoding="utf-8"))
            self.assertIn(payload["gateDecision"], {"post_side_outcome_needs_live_rpc_validation", "post_side_outcome_needs_more_corpus"})


if __name__ == "__main__":
    unittest.main()
