from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from app.scanner import _strong_risk_attribution_metrics
from tools.model_behavior_audit import (
    audit_records,
    normalize_record,
    write_strong_risk_deep_dive_outputs,
)
from tools.run_validation_corpus import (
    classify_corpus_result,
    render_corpus_markdown,
    strong_risk_exact_provenance_by_target_status,
)


def _completed_targets() -> list[dict[str, object]]:
    return [
        {
            "status": "completed_cache_only",
            "tags": ["fresh_rerunnable", "event_forensic", "live_or_unresolved", "politics_world", "non_gta"],
        }
    ] * 8 + [
        {
            "status": "completed_cache_only",
            "tags": ["fresh_rerunnable", "archive", "resolved_or_partial", "sports_crypto", "non_gta"],
        }
    ] * 4


def _completed_tags() -> dict[str, int]:
    return {
        "fresh_rerunnable": 12,
        "event_forensic": 8,
        "archive": 4,
        "live_or_unresolved": 8,
        "resolved_or_partial": 4,
        "politics_world": 8,
        "sports_crypto": 4,
        "non_gta": 12,
    }


class StrongRiskAttributionTests(unittest.TestCase):
    def test_timing_led_strong_risk_fixture(self) -> None:
        metrics = _strong_risk_attribution_metrics(
            severity="Strong Risk",
            score=45,
            confidence_score=80,
            raw_metrics={
                "opening_exposure_flag": "Yes",
                "decisive_timing_edge_flag": "Yes",
                "strong_timing_proof_count": "1",
                "supporting_booster_count": "1",
                "structural_concern_count": "0",
                "beat_consensus_flag": "Yes",
                "off_hours_flag": "Yes",
                "hardEvidenceSources": "",
            },
            flags=[],
        )

        self.assertEqual(metrics["strongRiskGateType"], "timing_led")
        self.assertEqual(metrics["strongRiskExactGateBranch"], "timing_led_gate")
        self.assertEqual(metrics["strongRiskGateName"], "timing_led_gate")
        self.assertEqual(metrics["strongRiskGateFamily"], "timing_repricing")
        self.assertEqual(metrics["strongRiskOpeningExposureStatus"], "confirmed")
        self.assertIn("beat_local_consensus", metrics["strongRiskTimingProofSources"])
        self.assertEqual(metrics["strongRiskCompositionClass"], "timing_with_support")

    def test_structure_led_strong_risk_fixture(self) -> None:
        metrics = _strong_risk_attribution_metrics(
            severity="Strong Risk",
            score=38,
            confidence_score=80,
            raw_metrics={
                "opening_exposure_flag": "Yes",
                "decisive_timing_edge_flag": "No",
                "strong_timing_proof_count": "0",
                "supporting_booster_count": "0",
                "structural_concern_count": "2",
                "split_wallet_pattern_flag": "Yes",
                "shared_funding_source_flag": "Yes",
                "funding_graph_key_strict": "strict:abc",
                "hardEvidenceSources": "split_wallet_pattern",
            },
            flags=[],
        )

        self.assertEqual(metrics["strongRiskGateType"], "structure_led")
        self.assertEqual(metrics["strongRiskExactGateBranch"], "structure_led_gate")
        self.assertEqual(metrics["strongRiskGateName"], "structure_led_gate")
        self.assertEqual(metrics["strongRiskGateFamily"], "structural")
        self.assertEqual(metrics["strongRiskHasIndependentHardEvidence"], "Yes")
        self.assertIn("split_wallet_pattern", metrics["strongRiskIndependentEvidenceSources"])
        self.assertEqual(metrics["strongRiskCompositionClass"], "structural")
        self.assertIn("split_wallet_pattern", metrics["strongRiskStructuralSources"])

    def test_gate_trace_score_threshold_fallback_is_diagnostic_only(self) -> None:
        metrics = _strong_risk_attribution_metrics(
            severity="Strong Risk",
            score=45,
            confidence_score=80,
            raw_metrics={},
            flags=[],
        )

        self.assertEqual(metrics["strongRiskGateName"], "score_threshold_unclear")
        self.assertEqual(metrics["strongRiskGateFamily"], "score_threshold")
        self.assertEqual(metrics["strongRiskScoreOnly"], "Yes")
        self.assertEqual(metrics["strongRiskDiagnosticOnly"], "Yes")

    def test_gate_trace_suppressor_conflict_reasons_are_captured(self) -> None:
        metrics = _strong_risk_attribution_metrics(
            severity="Strong Risk",
            score=45,
            confidence_score=80,
            raw_metrics={
                "opening_exposure_flag": "Yes",
                "decisive_timing_edge_flag": "Yes",
                "strong_timing_proof_count": "1",
                "supporting_booster_count": "1",
                "beat_consensus_flag": "Yes",
                "walletPublicPowerUserFlag": "Yes",
            },
            flags=[],
        )

        self.assertEqual(metrics["strongRiskSuppressorConflict"], "Yes")
        self.assertIn("high_volume_public_user", metrics["strongRiskSuppressorConflictReasons"])

    def test_same_wallet_shared_funding_is_not_strict_shared_hard_evidence(self) -> None:
        metrics = _strong_risk_attribution_metrics(
            severity="Strong Risk",
            score=42,
            confidence_score=100,
            raw_metrics={
                "opening_exposure_flag": "Yes",
                "decisive_timing_edge_flag": "No",
                "strong_timing_proof_count": "0",
                "supporting_booster_count": "0",
                "structural_concern_count": "2",
                "shared_funding_source_flag": "Yes",
                "shared_funding_source_cluster_size": "2",
                "shared_funding_source_wallet_count": "1",
                "funding_graph_key_strict": "strict:abc",
                "cex_proxy_cluster_flag": "No",
                "hardEvidenceSources": "",
            },
            flags=["domain_peer_outlier", "wallet_size_anomaly"],
        )

        self.assertNotIn("strict_shared_funding_source", metrics["strongRiskStructuralSources"])
        self.assertNotIn("strict_shared_funding_source", metrics["strongRiskHardEvidenceEligibleSources"])
        self.assertEqual(metrics["strongRiskSourceAttributionIssue"], "structural_but_not_hard_evidence")

    def test_distinct_wallet_shared_funding_is_strict_shared_hard_evidence_source(self) -> None:
        metrics = _strong_risk_attribution_metrics(
            severity="Strong Risk",
            score=42,
            confidence_score=100,
            raw_metrics={
                "opening_exposure_flag": "Yes",
                "decisive_timing_edge_flag": "No",
                "strong_timing_proof_count": "0",
                "supporting_booster_count": "0",
                "structural_concern_count": "2",
                "shared_funding_source_flag": "Yes",
                "shared_funding_source_cluster_size": "2",
                "shared_funding_source_wallet_count": "2",
                "funding_graph_key_strict": "strict:abc",
                "cex_proxy_cluster_flag": "No",
                "hardEvidenceSources": "",
            },
            flags=["domain_peer_outlier"],
        )

        self.assertIn("strict_shared_funding_source", metrics["strongRiskStructuralSources"])
        self.assertIn("strict_shared_funding_source", metrics["strongRiskHardEvidenceEligibleSources"])
        self.assertEqual(metrics["strongRiskSourceAttributionIssue"], "hard_evidence_source_missing")

    def test_mixed_strong_risk_fixture(self) -> None:
        metrics = _strong_risk_attribution_metrics(
            severity="Strong Risk",
            score=48,
            confidence_score=80,
            raw_metrics={
                "opening_exposure_flag": "Yes",
                "decisive_timing_edge_flag": "Yes",
                "strong_timing_proof_count": "1",
                "supporting_booster_count": "1",
                "structural_concern_count": "2",
                "favorable_repricing_flag": "Yes",
                "split_wallet_pattern_flag": "Yes",
                "hardEvidenceSources": "split_wallet_pattern",
            },
            flags=[],
        )

        self.assertEqual(metrics["strongRiskGateType"], "mixed_timing_structure")
        self.assertIn("rapid_favorable_repricing", metrics["strongRiskTimingProofSources"])
        self.assertIn("split_wallet_pattern", metrics["strongRiskStructuralSources"])

    def test_retrospective_event_forensic_strong_risk_normalizes(self) -> None:
        record = normalize_record(
            {
                "id": "retro",
                "finalEventJudgment": "Strong Risk: Retrospective",
                "eventForensicScore": "78",
                "laterWon": "Yes",
                "openingExposure": "Yes",
                "fundingEvidenceGrade": "none",
                "repricingSourceQuality": "none",
            }
        )

        self.assertTrue(record["strong_risk"])
        self.assertEqual(record["strong_risk_gate_type"], "retrospective_event_forensic")
        self.assertEqual(record["strong_risk_composition_class"], "retrospective_correctness")

    def test_exact_retrospective_event_forensic_branch_is_not_live_detectable(self) -> None:
        record = normalize_record(
            {
                "id": "exact-retro",
                "severity": "Strong Risk",
                "strongRiskGateType": "retrospective_event_forensic",
                "strongRiskExactGateBranch": "retrospective_event_forensic_gate",
                "strongRiskRetrospectiveOnly": "Yes",
                "strongRiskLiveDetectable": "No",
                "strongRiskRetrospectiveSources": "winner_rank; later_correctness",
                "fundingEvidenceGrade": "none",
                "repricingSourceQuality": "none",
            }
        )

        self.assertTrue(record["strong_risk_retrospective_only"])
        self.assertFalse(record["strong_risk_live_detectable"])
        self.assertEqual(record["strong_risk_exact_gate_branch"], "retrospective_event_forensic_gate")

    def test_score_only_strong_risk_warns(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "score-only",
                    "severity": "Strong Risk",
                    "strongRiskGatePassed": "Yes",
                    "strongRiskGateType": "legacy_unknown",
                    "strongRiskCompositionClass": "score_only",
                    "openingExposure": "Yes",
                    "fundingEvidenceGrade": "none",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        codes = {warning["code"] for warning in summary["warnings"]}
        self.assertIn("strong_risk_score_only", codes)
        self.assertEqual(summary["strong_risk_composition"]["strong_risk_score_only_rows"], 1)

    def test_no_gate_evidence_sources_warns(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "no-gate-sources",
                    "severity": "Strong Risk",
                    "strongRiskGatePassed": "Yes",
                    "strongRiskGateType": "timing_led",
                    "openingExposure": "Yes",
                    "fundingEvidenceGrade": "none",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        codes = {warning["code"] for warning in summary["warnings"]}
        self.assertIn("strong_risk_no_gate_evidence_sources", codes)

    def test_strong_risk_without_opening_exposure_warns(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "no-opening",
                    "severity": "Strong Risk",
                    "strongRiskGateType": "timing_led",
                    "strongRiskGateEvidenceSources": "beat_local_consensus",
                    "strongRiskTimingProofSources": "beat_local_consensus",
                    "strongRiskOpeningExposureConfirmed": "No",
                    "fundingEvidenceGrade": "none",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        codes = {warning["code"] for warning in summary["warnings"]}
        self.assertIn("strong_risk_opening_exposure_not_confirmed", codes)

    def test_weak_repricing_without_structure_warns(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "weak-repricing",
                    "severity": "Strong Risk",
                    "strongRiskGateType": "timing_led",
                    "strongRiskGateEvidenceSources": "rapid_favorable_repricing",
                    "strongRiskTimingProofSources": "rapid_favorable_repricing",
                    "openingExposure": "Yes",
                    "fundingEvidenceGrade": "none",
                    "repricingSourceQuality": "weak",
                }
            ]
        )

        codes = {warning["code"] for warning in summary["warnings"]}
        self.assertIn("strong_risk_weak_repricing_without_structure", codes)

    def test_suppressor_without_structure_warns(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "suppressed",
                    "severity": "Strong Risk",
                    "strongRiskGateType": "timing_led",
                    "strongRiskGateEvidenceSources": "beat_local_consensus",
                    "strongRiskTimingProofSources": "beat_local_consensus",
                    "strongRiskSuppressorConflict": "Yes",
                    "strongRiskSuppressorConflictReasons": "high_volume_public_user",
                    "openingExposure": "Yes",
                    "fundingEvidenceGrade": "none",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        codes = {warning["code"] for warning in summary["warnings"]}
        self.assertIn("strong_risk_suppressor_conflict_without_structure", codes)

    def test_structure_led_without_hard_sources_warns(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "structure-missing",
                    "severity": "Strong Risk",
                    "strongRiskGateType": "structure_led",
                    "strongRiskGateEvidenceSources": "split_wallet_pattern",
                    "strongRiskStructuralSources": "split_wallet_pattern",
                    "hardEvidenceSources": "",
                    "openingExposure": "Yes",
                    "fundingEvidenceGrade": "direct_strict",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        codes = {warning["code"] for warning in summary["warnings"]}
        self.assertIn("structure_led_strong_risk_missing_hard_sources", codes)
        self.assertIn("structure_led_hard_evidence_source_missing", codes)

    def test_exact_structure_gate_without_resolved_sources_warns(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "exact-structure-no-source",
                    "severity": "Strong Risk",
                    "strongRiskGateType": "structure_led",
                    "strongRiskExactGateBranch": "structure_led_gate",
                    "strongRiskStructuralConcernCount": "2",
                    "hardEvidenceSources": "",
                    "openingExposure": "Yes",
                    "fundingEvidenceGrade": "none",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        codes = {warning["code"] for warning in summary["warnings"]}
        self.assertIn("exact_structure_gate_missing_structural_sources", codes)

    def test_non_hard_structural_source_is_not_forced_into_hard_sources(self) -> None:
        record = normalize_record(
            {
                "id": "non-hard-structure",
                "severity": "Strong Risk",
                "strongRiskGateType": "structure_led",
                "strongRiskExactGateBranch": "structure_led_gate",
                "strongRiskStructuralSources": "coordinated_cluster",
                "strongRiskStructuralSourcesResolved": "coordinated_cluster",
                "strongRiskStructuralConcernCount": "2",
                "hardEvidenceSources": "",
                "openingExposure": "Yes",
                "fundingEvidenceGrade": "none",
                "repricingSourceQuality": "none",
            }
        )

        self.assertEqual(record["strong_risk_source_attribution_issue"], "structural_but_not_hard_evidence")
        self.assertEqual(record["strong_risk_hard_evidence_eligible_sources"], [])

    def test_structural_but_not_hard_fields_are_exported_by_scanner_metrics(self) -> None:
        metrics = _strong_risk_attribution_metrics(
            severity="Strong Risk",
            score=38,
            confidence_score=80,
            raw_metrics={
                "opening_exposure_flag": "Yes",
                "decisive_timing_edge_flag": "No",
                "strong_timing_proof_count": "0",
                "supporting_booster_count": "0",
                "structural_concern_count": "2",
                "hardEvidenceSources": "",
            },
            flags=["domain_peer_outlier", "wallet_size_anomaly"],
        )

        self.assertEqual(metrics["strongRiskSourceAttributionIssue"], "structural_but_not_hard_evidence")
        self.assertEqual(metrics["strongRiskStructuralButNotHardEvidence"], "Yes")
        self.assertIn("domain_peer_outlier", metrics["strongRiskStructuralButNotHardEvidenceSources"])
        self.assertIn("Strong Risk structural concerns", metrics["strongRiskWhyNoHardEvidence"])

    def test_score_only_after_exact_provenance_is_gate_leakage_candidate(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "exact-leak",
                    "severity": "Strong Risk",
                    "strongRiskGatePassed": "Yes",
                    "strongRiskGateType": "legacy_unknown",
                    "strongRiskCompositionClass": "score_only",
                    "strongRiskExactGateBranch": "legacy_unknown",
                    "openingExposure": "Yes",
                    "fundingEvidenceGrade": "none",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        record = normalize_record(
            {
                "id": "exact-leak",
                "severity": "Strong Risk",
                "strongRiskGatePassed": "Yes",
                "strongRiskGateType": "legacy_unknown",
                "strongRiskCompositionClass": "score_only",
                "strongRiskExactGateBranch": "legacy_unknown",
                "openingExposure": "Yes",
                "fundingEvidenceGrade": "none",
                "repricingSourceQuality": "none",
            }
        )
        codes = {warning["code"] for warning in summary["warnings"]}
        self.assertIn("strong_risk_gate_leakage_candidate", codes)
        self.assertTrue(record["strong_risk_gate_leakage_candidate"])

    def test_attribution_parser_miss_resolves_score_only_when_timing_source_exists(self) -> None:
        record = normalize_record(
            {
                "id": "parser-miss",
                "severity": "Strong Risk",
                "strongRiskGateType": "legacy_unknown",
                "strongRiskCompositionClass": "score_only",
                "strongRiskExactGateBranch": "legacy_unknown",
                "strongRiskTimingProofSources": "beat_local_consensus",
                "openingExposure": "Yes",
                "fundingEvidenceGrade": "none",
                "repricingSourceQuality": "none",
            }
        )

        self.assertEqual(record["strong_risk_score_only_resolution"], "attribution_parser_miss")
        self.assertFalse(record["strong_risk_gate_leakage_candidate"])

    def test_timing_led_without_hard_sources_does_not_raise_structure_missing_warning(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "timing-no-hard",
                    "severity": "Strong Risk",
                    "strongRiskGateType": "timing_led",
                    "strongRiskGateEvidenceSources": "beat_local_consensus",
                    "strongRiskTimingProofSources": "beat_local_consensus",
                    "hardEvidenceSources": "",
                    "openingExposure": "Yes",
                    "fundingEvidenceGrade": "none",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        codes = {warning["code"] for warning in summary["warnings"]}
        self.assertNotIn("structure_led_strong_risk_missing_hard_sources", codes)

    def test_new_format_legacy_unknown_strong_risk_warns(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "new-unknown",
                    "severity": "Strong Risk",
                    "strongRiskGatePassed": "Yes",
                    "strongRiskGateType": "legacy_unknown",
                    "hardEvidenceSources": "",
                    "fundingEvidenceGrade": "none",
                    "repricingSourceQuality": "none",
                    "openingExposure": "Yes",
                }
            ]
        )

        codes = {warning["code"] for warning in summary["warnings"]}
        self.assertIn("new_format_strong_risk_legacy_unknown_gate", codes)
        self.assertIn("new_format_strong_risk_missing_exact_gate_branch", codes)

    def test_direct_strong_no_suppressor_lead_does_not_warn(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "clean-direct",
                    "severity": "Strong Risk",
                    "strongRiskGateType": "timing_led",
                    "strongRiskGateEvidenceSources": "beat_local_consensus",
                    "strongRiskTimingProofSources": "beat_local_consensus",
                    "strongRiskSuppressorConflict": "No",
                    "openingExposure": "Yes",
                    "hardEvidenceSources": "",
                    "fundingEvidenceGrade": "suspicious_direct",
                    "suspiciousFundingQuality": "strong",
                    "suspiciousFundingHardEvidenceEligible": "Yes",
                    "repricingSourceQuality": "strong",
                }
            ]
        )

        codes = {warning["code"] for warning in summary["warnings"]}
        self.assertNotIn("strong_risk_score_only", codes)
        self.assertNotIn("strong_risk_suppressor_conflict_without_structure", codes)

    def test_deep_dive_outputs_are_written(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "structure",
                    "severity": "Strong Risk",
                    "strongRiskGateType": "structure_led",
                    "strongRiskGateEvidenceSources": "split_wallet_pattern",
                    "strongRiskStructuralSources": "split_wallet_pattern",
                    "hardEvidenceSources": "split_wallet_pattern",
                    "openingExposure": "Yes",
                    "fundingEvidenceGrade": "direct_strict",
                    "repricingSourceQuality": "none",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = write_strong_risk_deep_dive_outputs(
                summary,
                Path(tmpdir),
                timestamp="20260503_000000",
            )
            self.assertTrue(Path(outputs["markdown_path"]).exists())
            self.assertTrue(Path(outputs["json_path"]).exists())

    def test_legacy_strong_risk_loads_as_legacy_unknown(self) -> None:
        record = normalize_record({"id": "legacy", "severity": "Strong Risk"})

        self.assertEqual(record["strong_risk_gate_type"], "legacy_unknown")
        self.assertEqual(record["strong_risk_composition_class"], "legacy_unknown")

    def test_audit_does_not_treat_same_wallet_shared_funding_as_independent_support(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "same-wallet-shared-funding",
                    "severity": "Strong Risk",
                    "strongRiskGateType": "structure_led",
                    "strongRiskExactGateBranch": "structure_led_gate",
                    "strongRiskStructuralSources": "domain_peer_outlier; wallet_size_anomaly",
                    "strongRiskStructuralConcernCount": "2",
                    "hardEvidenceSources": "",
                    "hardEvidenceReviewTier": "",
                    "shared_funding_source_flag": "Yes",
                    "shared_funding_source_cluster_size": "2",
                    "shared_funding_source_wallet_count": "1",
                    "funding_graph_key_strict": "strict:abc",
                    "fundingEvidenceGrade": "multi_hop_unknown",
                    "repricingSourceQuality": "none",
                    "opening_exposure_flag": "Yes",
                }
            ]
        )

        starvation = summary["hard_evidence_starvation"]
        self.assertFalse(starvation["independent_hard_evidence_sources_appeared"])
        self.assertEqual(starvation["independent_sources_not_routed_to_hard_evidence_review_rows"], 0)

    def test_audit_requires_distinct_wallets_for_strict_shared_funding_support(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "distinct-wallet-shared-funding",
                    "severity": "Strong Risk",
                    "strongRiskGateType": "structure_led",
                    "strongRiskExactGateBranch": "structure_led_gate",
                    "strongRiskStructuralSources": "strict_shared_funding_source; domain_peer_outlier",
                    "strongRiskStructuralConcernCount": "2",
                    "hardEvidenceSources": "",
                    "hardEvidenceReviewTier": "",
                    "shared_funding_source_flag": "Yes",
                    "shared_funding_source_cluster_size": "2",
                    "shared_funding_source_wallet_count": "2",
                    "funding_graph_key_strict": "strict:abc",
                    "fundingEvidenceGrade": "multi_hop_unknown",
                    "repricingSourceQuality": "none",
                    "opening_exposure_flag": "Yes",
                }
            ]
        )

        warning_codes = {warning["code"] for warning in summary["warnings"]}
        starvation = summary["hard_evidence_starvation"]
        self.assertIn("independent_evidence_not_routed_hard_evidence_review", warning_codes)
        self.assertEqual(starvation["independent_sources_observed"]["strict_shared_funding_source"], 1)
        self.assertEqual(starvation["independent_sources_not_routed_to_hard_evidence_review_rows"], 1)


class StrongRiskCorpusIntegrationTests(unittest.TestCase):
    def test_corpus_report_includes_gate_type_distribution(self) -> None:
        markdown = render_corpus_markdown(
            {
                "generated_at": "2026-05-03T00:00:00+00:00",
                "corpus_name": "test",
                "final_classification": "post-v2 behavior acceptable",
                "recommended_next_task": "none",
                "target_status_counts": {"completed_cache_only": 6},
                "audit_summary": {
                    "strong_risk_rows": 1,
                    "pre_admission_funnel": {},
                    "hard_evidence_pathway_counts": {},
                    "strong_risk_composition": {
                        "strong_risk_rows_by_gate_type": {"structure_led": 1},
                        "strong_risk_rows_by_composition_class": {"structural": 1},
                    },
                    "hard_evidence_starvation": {},
                    "warnings": [],
                },
            }
        )

        self.assertIn("gate_type_distribution", markdown)
        self.assertIn("structure_led", markdown)

    def test_corpus_classification_gate_leakage_is_composition_concern(self) -> None:
        classification = classify_corpus_result(
            target_results=_completed_targets(),
            audit_summary={
                "warnings": [],
                "archive_rows_inspected": 20,
                "strong_risk_rows": 1,
                "strong_risk_composition": {"strong_risk_gate_leakage_candidate_rows": 1},
                "pre_admission_funnel": {"total_near_miss_groups": 1, "funding_trace_attempted_count": 1},
            },
            completed_tags=_completed_tags(),
        )

        self.assertEqual(classification, "strong-risk composition concern")

    def test_corpus_classification_source_attribution_repair_needed(self) -> None:
        classification = classify_corpus_result(
            target_results=_completed_targets(),
            audit_summary={
                "warnings": [],
                "archive_rows_inspected": 20,
                "strong_risk_rows": 2,
                "strong_risk_composition": {
                    "strong_risk_rows_by_source_attribution_issue": {"hard_evidence_source_missing": 2},
                    "strong_risk_gate_leakage_candidate_rows": 0,
                    "strong_risk_new_format_missing_exact_gate_branch_rows": 0,
                    "strong_risk_suppressor_conflict_without_structure_rows": 0,
                    "strong_risk_timing_only_rows": 0,
                    "strong_risk_weak_mechanical_unknown_repricing_rows": 0,
                },
                "pre_admission_funnel": {"total_near_miss_groups": 1, "funding_trace_attempted_count": 1},
            },
            completed_tags=_completed_tags(),
        )

        self.assertEqual(classification, "source-attribution repair needed")

    def test_corpus_distinguishes_fresh_and_audit_only_exact_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fresh_dir = root / "event_forensic_20260503_fresh"
            audit_dir = root / "event_forensic_20260502_saved"
            fresh_dir.mkdir()
            audit_dir.mkdir()
            (fresh_dir / "event_analysis.json").write_text(
                """{"display_trades":[{"id":"fresh","severity":"Strong Risk","wallet":"0x1","openingExposure":"Yes","strongRiskGateType":"structure_led","strongRiskExactGateBranch":"structure_led_gate","strongRiskStructuralSources":"domain_peer_outlier; wallet_size_anomaly","strongRiskStructuralSourcesResolved":"domain_peer_outlier; wallet_size_anomaly","strongRiskStructuralButNotHardEvidence":"Yes","fundingEvidenceGrade":"none","repricingSourceQuality":"none"}]}""",
                encoding="utf-8",
            )
            (audit_dir / "event_analysis.json").write_text(
                """{"display_trades":[{"id":"saved","severity":"Strong Risk","wallet":"0x2","openingExposure":"Yes","strongRiskGateType":"legacy_unknown","fundingEvidenceGrade":"none","repricingSourceQuality":"none"}]}""",
                encoding="utf-8",
            )

            split = strong_risk_exact_provenance_by_target_status(
                [
                    {"status": "completed_cache_only", "output_paths": [str(fresh_dir)]},
                    {"status": "audit_only_saved_output", "selected_outputs": [str(audit_dir)]},
                ]
            )

        self.assertEqual(split["fresh_generated"]["strong_risk_rows"], 1)
        self.assertEqual(split["fresh_generated"].get("exact_gate_branch_missing_new_format_rows", 0), 0)
        self.assertEqual(split["audit_only_saved_output"]["exact_gate_branch_missing_new_format_rows"], 1)

    def test_structural_but_not_hard_fresh_rows_are_not_composition_concern(self) -> None:
        classification = classify_corpus_result(
            target_results=_completed_targets(),
            audit_summary={
                "warnings": [],
                "archive_rows_inspected": 20,
                "strong_risk_rows": 2,
                "strong_risk_composition": {
                    "strong_risk_rows_by_source_attribution_issue": {"structural_but_not_hard_evidence": 2},
                    "strong_risk_gate_leakage_candidate_rows": 0,
                    "strong_risk_new_format_missing_exact_gate_branch_rows": 0,
                    "strong_risk_suppressor_conflict_without_structure_rows": 2,
                    "strong_risk_timing_only_rows": 0,
                    "strong_risk_weak_mechanical_unknown_repricing_rows": 0,
                    "strong_risk_rows_with_no_hard_evidence_sources": 2,
                    "strong_risk_rows_driven_by_timing_repricing_only": 0,
                    "strong_risk_rows_driven_by_structure": 2,
                    "strong_risk_rows_opening_exposure_not_confirmed": 0,
                },
                "strong_risk_exact_provenance_by_target_status": {
                    "fresh_generated": {
                        "strong_risk_rows": 2,
                        "structural_but_not_hard_evidence_rows": 2,
                        "suppressor_conflict_without_structural_support_rows": 0,
                        "exact_gate_branch_missing_new_format_rows": 0,
                        "gate_leakage_candidate_rows": 0,
                        "score_only_after_exact_provenance_rows": 0,
                        "weak_mechanical_unknown_repricing_without_structural_support_rows": 0,
                        "source_attribution_issue_distribution": {"structural_but_not_hard_evidence": 2},
                    }
                },
                "pre_admission_funnel": {"total_near_miss_groups": 1, "funding_trace_attempted_count": 1},
            },
            completed_tags=_completed_tags(),
        )

        self.assertEqual(classification, "post-v2 behavior acceptable")

    def test_corpus_classification_accepts_attributed_structural_strong_risk(self) -> None:
        classification = classify_corpus_result(
            target_results=_completed_targets(),
            audit_summary={
                "warnings": [],
                "archive_rows_inspected": 20,
                "strong_risk_rows": 1,
                "strong_risk_composition": {
                    "strong_risk_score_only_rows": 0,
                    "strong_risk_rows_with_no_gate_evidence_sources": 0,
                    "strong_risk_suppressor_conflict_without_structure_rows": 0,
                    "strong_risk_timing_only_rows": 0,
                    "strong_risk_weak_mechanical_unknown_repricing_rows": 0,
                    "strong_risk_rows_with_no_hard_evidence_sources": 0,
                    "strong_risk_rows_driven_by_timing_repricing_only": 0,
                    "strong_risk_rows_driven_by_structure": 1,
                    "strong_risk_rows_opening_exposure_not_confirmed": 0,
                },
                "pre_admission_funnel": {"total_near_miss_groups": 1, "funding_trace_attempted_count": 1},
            },
            completed_tags=_completed_tags(),
        )

        self.assertEqual(classification, "post-v2 behavior acceptable")


if __name__ == "__main__":
    unittest.main()
