from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_forensic_weak_history_policy_simulation import (
    PolicyRow,
    build_policy_evidence,
    collect_policy_rows,
    simulate_policy_options,
    write_outputs,
)


class EventForensicWeakHistoryPolicySimulationTests(unittest.TestCase):
    def test_simulation_options_are_offline_and_schema_stable(self) -> None:
        rows = [_weak_high_rank_row(), _control_row()]

        report = simulate_policy_options(rows)

        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["runtimeBehaviorChanged"])
        self.assertEqual(set(report["policyOptions"]), {"current", "stronger_reducer", "review_bucket_demotion", "explanation_only"})
        self.assertEqual(report["summary"]["gateDecision"], "policy_ready_for_product_decision")

    def test_current_option_preserves_baseline(self) -> None:
        report = simulate_policy_options([_weak_high_rank_row(), _control_row()])

        current = report["policyOptions"]["current"]
        self.assertEqual(current["rowsThatWouldBeDemoted"], 0)
        self.assertEqual(current["rowsWithScoreAdjustmentOnly"], 0)
        self.assertEqual(current["rowsWithExplanationWarningOnly"], 0)

    def test_stronger_reducer_changes_score_only_in_simulation(self) -> None:
        report = simulate_policy_options([_weak_high_rank_row(), _control_row()])

        stronger = report["policyOptions"]["stronger_reducer"]
        self.assertEqual(stronger["rowsWithScoreAdjustmentOnly"], 1)
        self.assertEqual(stronger["rowsThatWouldBeDemoted"], 0)
        self.assertFalse(stronger["runtimeMutation"])

    def test_review_bucket_demotion_marks_rows_without_runtime_mutation(self) -> None:
        report = simulate_policy_options([_weak_high_rank_row(), _control_row()])

        demotion = report["policyOptions"]["review_bucket_demotion"]
        self.assertEqual(demotion["rowsThatWouldBeDemoted"], 1)
        self.assertTrue(demotion["requiresProductApproval"])
        self.assertFalse(demotion["runtimeMutation"])

    def test_explanation_only_marks_warning_without_placement_change(self) -> None:
        report = simulate_policy_options([_weak_high_rank_row(), _control_row()])

        explanation = report["policyOptions"]["explanation_only"]
        self.assertEqual(explanation["rowsWithExplanationWarningOnly"], 1)
        self.assertEqual(explanation["rowsThatWouldBeDemoted"], 0)

    def test_missing_fields_produce_unknown_bucket(self) -> None:
        report = simulate_policy_options([_missing_fields_row()])

        self.assertEqual(report["summary"]["unknownOrMissingFieldRows"], 1)
        for option in report["policyOptions"].values():
            self.assertEqual(option["unknownMissingFieldRows"], 1)

    def test_output_writer_uses_existing_artifacts_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live_report = root / "event_analysis.json"
            live_report.write_text(
                json.dumps(
                    {
                        "display_trades": [_weak_high_rank_payload()],
                        "suspicious_trades": [],
                        "summary": {"raw_trade_count": 1, "candidate_trade_count": 1},
                    }
                ),
                encoding="utf-8",
            )
            live_summary = root / "summary.json"
            live_summary.write_text(
                json.dumps(
                    {
                        "summary": {
                            "gateDecision": "weak_history_live_validation_needs_model_rfc",
                            "selectedEventCount": 1,
                            "selectedMarketCount": 1,
                            "totalRawTradeRows": 1,
                            "totalCandidateRows": 1,
                            "weakHistoryNearCertainLaterWinRows": 1,
                            "highRankWeakHistoryNearCertainLaterWinRows": 1,
                        },
                        "reportSummaries": [{"eventAnalysisJsonPath": str(live_report)}],
                    }
                ),
                encoding="utf-8",
            )
            saved_audit = root / "saved_audit.json"
            saved_audit.write_text(
                json.dumps(
                    {
                        "gateDecision": "weak_history_needs_live_rpc_validation",
                        "summary": {
                            "rowsEvaluated": 1,
                            "realWeakHistoryNearCertainLaterWinRows": 1,
                            "sufficientRealWeakHistoryNearCertainLaterWinRows": 1,
                            "localBlockerClosed": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            corpus = root / "corpus.json"
            corpus.write_text(
                json.dumps(
                    {
                        "cases": [{"category": "event_forensic_later_correctness_affected"}],
                        "networkUsed": False,
                        "runtimeBehaviorChanged": False,
                    }
                ),
                encoding="utf-8",
            )
            evidence_path = root / "evidence.json"
            simulation_path = root / "simulation.json"

            evidence, simulation = write_outputs(
                evidence_output=evidence_path,
                simulation_output=simulation_path,
                live_summary_path=live_summary,
                saved_audit_path=saved_audit,
                known_case_corpus_path=corpus,
            )

            self.assertTrue(evidence_path.exists())
            self.assertTrue(simulation_path.exists())
            self.assertFalse(evidence["networkUsed"])
            self.assertFalse(simulation["networkUsed"])
            self.assertEqual(simulation["summary"]["weakHistoryNearCertainLaterWinRows"], 1)

    def test_collect_policy_rows_reads_live_summary_report_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "event_analysis.json"
            report.write_text(json.dumps({"display_trades": [_weak_high_rank_payload()]}), encoding="utf-8")
            summary = root / "summary.json"
            summary.write_text(json.dumps({"reportSummaries": [{"eventAnalysisJsonPath": str(report)}]}), encoding="utf-8")

            rows = collect_policy_rows(live_summary_path=summary)

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].weak_history_near_certainty_later_win)

    def test_build_policy_evidence_explains_not_narrow_bug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live_report = root / "event_analysis.json"
            live_report.write_text(json.dumps({"display_trades": [_weak_high_rank_payload()]}), encoding="utf-8")
            live_summary = root / "summary.json"
            live_summary.write_text(
                json.dumps(
                    {
                        "summary": {"gateDecision": "weak_history_live_validation_needs_model_rfc"},
                        "reportSummaries": [{"eventAnalysisJsonPath": str(live_report)}],
                    }
                ),
                encoding="utf-8",
            )
            saved_audit = root / "saved.json"
            saved_audit.write_text(json.dumps({"summary": {}}), encoding="utf-8")
            corpus = root / "corpus.json"
            corpus.write_text(json.dumps({"cases": []}), encoding="utf-8")

            evidence = build_policy_evidence(
                live_summary_path=live_summary,
                saved_audit_path=saved_audit,
                known_case_corpus_path=corpus,
            )

        self.assertIn("missing reducer", " ".join(evidence["whyNotNarrowRuntimeBug"]).lower())
        self.assertEqual(evidence["policyRowsCollected"], 1)


def _weak_high_rank_payload() -> dict[str, object]:
    return {
        "id": "weak-near-1",
        "wallet": "0xweak",
        "market": "Example",
        "parentEventSlug": "event",
        "orderSide": "BUY",
        "side": "No",
        "price": 0.96,
        "laterWon": True,
        "winnerRank": 4,
        "eventForensicScore": 6,
        "existingModelClass": "Strong Risk",
        "strongRiskGatePassed": "Yes",
        "eventForensicFlags": ["weak_wallet_track_record", "near_certainty_winner"],
        "eventForensicReducers": ["weak economic history", "near certainty"],
    }


def _weak_high_rank_row() -> PolicyRow:
    return PolicyRow(
        source="test",
        source_path="fixture",
        trade_key="weak-near-1",
        wallet="0xweak",
        market="Example",
        event_slug="event",
        raw_order_side="BUY",
        raw_token_outcome="NO",
        raw_token_price="0.96",
        economic_side="NO",
        economic_side_probability="0.96",
        cluster_direction="long_no",
        event_forensic_score=6,
        display_rank=7,
        existing_model_class="Strong Risk",
        strong_risk_gate_passed="Yes",
        hard_evidence_review_tier="",
        later_won=True,
        winner_rank=4,
        weak_history_classification="weak_history",
        near_certain_economic_entry=True,
        weak_history_reducer_present=True,
        near_certainty_reducer_present=True,
        quality_notes=(),
    )


def _control_row() -> PolicyRow:
    return PolicyRow(
        source="test",
        source_path="fixture",
        trade_key="control",
        wallet="0xcontrol",
        market="Example",
        event_slug="event",
        raw_order_side="BUY",
        raw_token_outcome="YES",
        raw_token_price="0.40",
        economic_side="YES",
        economic_side_probability="0.40",
        cluster_direction="long_yes",
        event_forensic_score=45,
        display_rank=12,
        existing_model_class="Worth a Look",
        strong_risk_gate_passed="No",
        hard_evidence_review_tier="",
        later_won=False,
        winner_rank=None,
        weak_history_classification="not_weak_history",
        near_certain_economic_entry=False,
        weak_history_reducer_present=False,
        near_certainty_reducer_present=False,
        quality_notes=(),
    )


def _missing_fields_row() -> PolicyRow:
    return PolicyRow(
        source="test",
        source_path="fixture",
        trade_key="missing",
        wallet="",
        market="",
        event_slug="",
        raw_order_side="unknown",
        raw_token_outcome="unknown",
        raw_token_price="unknown",
        economic_side="unknown",
        economic_side_probability="unknown",
        cluster_direction="unknown",
        event_forensic_score=None,
        display_rank=None,
        existing_model_class="",
        strong_risk_gate_passed="",
        hard_evidence_review_tier="",
        later_won=None,
        winner_rank=None,
        weak_history_classification="unknown",
        near_certain_economic_entry=False,
        weak_history_reducer_present=False,
        near_certainty_reducer_present=False,
        quality_notes=("missing_fields",),
    )


if __name__ == "__main__":
    unittest.main()
