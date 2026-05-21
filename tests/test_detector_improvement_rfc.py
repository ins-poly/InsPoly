from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.generate_detector_improvement_rfc import (
    HARD_CONSTRAINTS,
    build_rfc_package,
    write_outputs,
)


class DetectorImprovementRfcTests(unittest.TestCase):
    def test_rfc_file_generation(self) -> None:
        package = build_rfc_package()
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_outputs(package, Path(tmp))
            self.assertTrue(Path(outputs["rfc_json_path"]).exists())
            self.assertTrue(Path(outputs["rfc_markdown_path"]).exists())
            self.assertTrue(Path(outputs["prompt_pack_json_path"]).exists())
            self.assertTrue(Path(outputs["prompt_pack_markdown_path"]).exists())
            json.loads(Path(outputs["rfc_json_path"]).read_text(encoding="utf-8"))
            json.loads(Path(outputs["prompt_pack_json_path"]).read_text(encoding="utf-8"))

    def test_proposal_schema_completeness_and_count(self) -> None:
        package = build_rfc_package()
        required = {
            "proposalId",
            "title",
            "category",
            "problem",
            "currentEvidence",
            "evidenceClass",
            "wouldChangeModelBehavior",
            "wouldChangeScoringWeights",
            "wouldChangeStrongRiskGate",
            "wouldChangeHEREligibility",
            "wouldChangeFundingEligibility",
            "wouldChangeCandidateAdmission",
            "riskOfFalsePositiveIncrease",
            "riskOfFalseNegativeIncrease",
            "expectedAnalystValue",
            "implementationRisk",
            "requiredValidationBeforeImplementation",
            "minimumFreshEvidenceRequired",
            "recommendedDecision",
            "safeNextStep",
            "forbiddenNextStep",
            "decisionMatrixBucket",
        }
        proposals = package["proposals"]
        self.assertGreaterEqual(len(proposals), 15)
        for proposal in proposals:
            self.assertTrue(required.issubset(proposal.keys()))

    def test_model_changing_proposals_are_never_green(self) -> None:
        package = build_rfc_package()
        for proposal in package["proposals"]:
            changes_detector = any(
                proposal[key]
                for key in (
                    "wouldChangeModelBehavior",
                    "wouldChangeScoringWeights",
                    "wouldChangeStrongRiskGate",
                    "wouldChangeHEREligibility",
                    "wouldChangeFundingEligibility",
                    "wouldChangeCandidateAdmission",
                )
            )
            if changes_detector:
                self.assertNotEqual(proposal["decisionMatrixBucket"], "green_reporting_only_can_implement")

    def test_cache_only_model_changing_proposals_are_deferred(self) -> None:
        package = build_rfc_package()
        weak_classes = {"cache_only", "saved_output_only", "retrospective_only", "insufficient"}
        allowed = {"rfc_only_needs_fresh_validation", "defer_until_rpc_available", "reject_for_now"}
        for proposal in package["proposals"]:
            changes_detector = any(
                proposal[key]
                for key in (
                    "wouldChangeModelBehavior",
                    "wouldChangeScoringWeights",
                    "wouldChangeStrongRiskGate",
                    "wouldChangeHEREligibility",
                    "wouldChangeFundingEligibility",
                    "wouldChangeCandidateAdmission",
                )
            )
            if changes_detector and proposal["evidenceClass"] in weak_classes:
                self.assertIn(proposal["recommendedDecision"], allowed)

    def test_required_proposal_categories_are_present(self) -> None:
        package = build_rfc_package()
        categories = {}
        for proposal in package["proposals"]:
            categories[proposal["category"]] = categories.get(proposal["category"], 0) + 1
        self.assertGreaterEqual(categories.get("reporting_ui_analyst_workflow", 0), 3)
        self.assertGreaterEqual(categories.get("source_schema_attribution", 0), 3)
        self.assertGreaterEqual(categories.get("false_positive_control", 0), 3)
        self.assertGreaterEqual(categories.get("false_negative_recall_diagnostic", 0), 3)
        self.assertGreaterEqual(categories.get("strong_risk_gate_rfc", 0), 2)
        self.assertGreaterEqual(categories.get("her_routing_rfc", 0), 1)
        self.assertGreaterEqual(categories.get("suspicious_funding_rfc", 0), 1)

    def test_decision_matrix_uses_required_buckets(self) -> None:
        package = build_rfc_package()
        allowed = {
            "green_reporting_only_can_implement",
            "yellow_diagnostic_only_can_prepare",
            "orange_rfc_requires_fresh_validation",
            "red_do_not_implement_now",
        }
        self.assertEqual(set(package["decision_matrix"].keys()), allowed)

    def test_prompt_pack_includes_hard_constraints(self) -> None:
        package = build_rfc_package()
        prompts = package["prompt_pack"]["prompts"]
        self.assertGreaterEqual(len(prompts), 10)
        prompt_ids = {prompt["promptId"] for prompt in prompts}
        self.assertIn("rfc_only_her_routing_review", prompt_ids)
        self.assertIn("rfc_only_suspicious_funding_review", prompt_ids)
        for prompt in prompts:
            text = prompt["readyToCopyPrompt"]
            for constraint in HARD_CONSTRAINTS[:8]:
                self.assertIn(constraint, text)
            self.assertIn("Current status assumptions:", text)
            self.assertIn("Implementation policy:", text)
            self.assertIn("Stop conditions:", text)

    def test_prompt_pack_does_not_authorize_production_scoring_or_gate_changes(self) -> None:
        package = build_rfc_package()
        prompts = package["prompt_pack"]["prompts"]
        forbidden_authorizations = [
            "production detector implementation is approved",
            "you may edit scoring weights",
            "you may edit strong risk gates",
            "you may lower thresholds",
            "you may broaden structural pre-admission",
            "you may change her eligibility",
            "you may change funding eligibility",
            "implementation allowed for scoring",
            "implementation allowed for gates",
        ]
        for prompt in prompts:
            lower = prompt["readyToCopyPrompt"].lower()
            for phrase in forbidden_authorizations:
                self.assertNotIn(phrase, lower)

    def test_missing_optional_artifacts_do_not_crash(self) -> None:
        package = build_rfc_package()
        self.assertIn("artifact_paths", package)
        self.assertIn("evidence_summary", package)


if __name__ == "__main__":
    unittest.main()
