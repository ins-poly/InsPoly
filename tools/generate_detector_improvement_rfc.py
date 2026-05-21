from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("rfcs")
RFC_STEM = "DETECTOR_IMPROVEMENT_RFC_20260505"
PROMPT_PACK_STEM = "DETECTOR_IMPROVEMENT_PROMPT_PACK_20260505"

EVIDENCE_CLASSES = {
    "fresh_trace_enabled",
    "cache_only",
    "saved_output_only",
    "retrospective_only",
    "analyst_quality_only",
    "insufficient",
}

RECOMMENDED_DECISIONS = {
    "implement_now_reporting_only",
    "prepare_diagnostic_only",
    "rfc_only_needs_fresh_validation",
    "rfc_only_needs_human_approval",
    "reject_for_now",
    "defer_until_rpc_available",
}

DECISION_MATRIX_BUCKETS = {
    "green_reporting_only_can_implement",
    "yellow_diagnostic_only_can_prepare",
    "orange_rfc_requires_fresh_validation",
    "red_do_not_implement_now",
}

HARD_CONSTRAINTS = [
    "Do not change `_score_trade()`.",
    "Do not change Strong Risk gates.",
    "Do not change scoring weights.",
    "Do not change production severity labels.",
    "Do not broaden structural pre-admission.",
    "Do not lower structural floors or notional thresholds.",
    "Do not weaken suspicious funding v2.",
    "Do not make `multi_hop_unknown` funding eligible without independent structural support.",
    "Do not make CEX proxy-only or bridge proxy-only evidence eligible.",
    "Do not change Hard Evidence Review routing.",
    "Do not add LLM scoring.",
    "Do not add ML scoring.",
    "Do not add news, journalism, intelligence feeds, or external signal ingestion.",
    "Do not hardcode credentials.",
    "Do not hardcode RPC URLs.",
    "Do not mutate old saved outputs.",
    "Preserve legacy output loading and report normalization.",
    "Treat funding unavailable as `unknown`, not `none`.",
    "Treat dedupe as reporting-only; never drop production rows.",
    "Do not overclaim cache-only, stale, duplicate-inflated, or retrospective-only evidence.",
    "Do not convert RFC recommendations into code changes.",
]

ARTIFACT_PATTERNS = {
    "decision_boundary_stop_state": ("validation_corpus_outputs", "decision_boundary_stop_state_*.json"),
    "strategic_backlog_dashboard": ("strategic_backlog_outputs", "strategic_backlog_dashboard_*.json"),
    "strategic_next_action": ("strategic_backlog_outputs", "strategic_next_action_*.json"),
    "readiness": ("validation_corpus_outputs", "gate_decision_readiness_*.json"),
    "autonomous_next_action": ("validation_corpus_outputs", "autonomous_next_action_*.json"),
    "operator_rpc_recovery_package": ("validation_corpus_outputs", "operator_rpc_capacity_recovery_package_*.json"),
    "model_behavior_audit": ("validation_corpus_outputs", "post_v2_corpus_audit_*.json"),
    "corpus_provenance_drilldown": ("validation_corpus_outputs", "corpus_provenance_drilldown_*.json"),
    "strong_risk_gate_diagnostic": ("strong_risk_diagnostic_outputs", "strong_risk_gate_diagnostic_*.json"),
    "report_consistency": ("validation_corpus_outputs", "report_consistency_*.json"),
    "unique_review_packets": ("review_packets", "unique_review_packets_*.json"),
    "case_reviewer_comparison": ("review_packet_compare_outputs", "review_packet_case_reviewer_compare_*.json"),
    "review_packet_quality_check": ("analyst_quality_outputs", "review_packet_quality_check_*.json"),
    "advisory_wallet_queue": ("analyst_quality_outputs", "wallet_review_queue_*.json"),
    "analyst_handoff_bundle": ("analyst_review_bundles", "analyst_review_bundle_*.json"),
    "artifact_manifest": ("artifact_manifests", "review_artifact_manifest_*.json"),
    "implementation_boundary": ("implementation_boundaries", "implementation_boundary_*.json"),
    "analyst_crosswalk": ("implementation_boundaries", "analyst_crosswalk_*.json"),
    "reporting_schema_patch_report": ("implementation_boundaries", "reporting_schema_patch_report_*.json"),
    "false_positive_library": ("false_positive_library", "false_positive_pattern_library_*.json"),
    "source_schema_repair_plan": ("source_schema_repair_outputs", "source_schema_repair_plan_*.json"),
    "source_attribution_completeness": ("source_attribution_outputs", "source_attribution_completeness_*.json"),
    "candidate_recall_diagnostic": ("candidate_recall_outputs", "candidate_recall_diagnostic_*.json"),
    "schema_normalization_check": ("schema_normalization_outputs", "review_schema_normalization_check_*.json"),
}


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _latest_file(directory: str | Path, pattern: str) -> Path | None:
    root = _resolve(directory) or Path(directory)
    if not root.exists():
        return None
    candidates = sorted(root.glob(pattern), key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
    return candidates[0] if candidates else None


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("summary"), Mapping):
        return dict(payload.get("summary") or {})
    keys = (
        "readinessClassification",
        "recommendation",
        "decision",
        "recommended_next_task",
        "classification",
        "finalRecommendation",
    )
    return {key: payload.get(key) for key in keys if key in payload}


def discover_artifacts() -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for name, (directory, pattern) in ARTIFACT_PATTERNS.items():
        path = _latest_file(directory, pattern)
        payload = _load_json(path)
        artifacts[name] = {
            "path": str(path) if path else "",
            "summary": _summary(payload),
            "payload": payload,
        }
    return artifacts


def _artifact_summary_value(artifacts: Mapping[str, Mapping[str, Any]], artifact: str, key: str, default: Any = 0) -> Any:
    summary = artifacts.get(artifact, {}).get("summary")
    if isinstance(summary, Mapping):
        return summary.get(key, default)
    return default


def _artifact_payload_value(artifacts: Mapping[str, Mapping[str, Any]], artifact: str, key: str, default: Any = 0) -> Any:
    payload = artifacts.get(artifact, {}).get("payload")
    if isinstance(payload, Mapping):
        return payload.get(key, default)
    return default


def build_evidence_summary(artifacts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    readiness_payload = artifacts.get("readiness", {}).get("payload", {})
    strong_payload = artifacts.get("strong_risk_gate_diagnostic", {}).get("payload", {})
    return {
        "readiness_classification": readiness_payload.get("readinessClassification", "unknown"),
        "readiness_recommendation": readiness_payload.get("recommendation", "unknown"),
        "public_rpc_blocker_active": _artifact_summary_value(artifacts, "strategic_backlog_dashboard", "public_rpc_blocker_active", True),
        "safe_non_rpc_available_items": _artifact_summary_value(artifacts, "strategic_backlog_dashboard", "available_items", 0),
        "completed_backlog_items": _artifact_summary_value(artifacts, "strategic_backlog_dashboard", "completed_items", 0),
        "human_approval_required_items": _artifact_summary_value(
            artifacts, "strategic_backlog_dashboard", "human_approval_required_items", 0
        ),
        "rpc_blocked_items": _artifact_summary_value(artifacts, "strategic_backlog_dashboard", "rpc_blocked_items", 0),
        "decision_boundary_decision": _artifact_payload_value(artifacts, "decision_boundary_stop_state", "decision", "unknown"),
        "operator_rpc_configuration_status": _artifact_payload_value(
            artifacts, "operator_rpc_recovery_package", "configuration_status", "unknown"
        ),
        "final_safe_boundary_remaining": _artifact_summary_value(
            artifacts, "reporting_schema_patch_report", "remaining_safe_fix_count", 0
        ),
        "rfc_only_issues_left": _artifact_summary_value(
            artifacts, "reporting_schema_patch_report", "rfc_only_issues_left_untouched", 0
        ),
        "rpc_blocked_issues_left": _artifact_summary_value(
            artifacts, "reporting_schema_patch_report", "rpc_blocked_issues_left_untouched", 0
        ),
        "unique_review_packets": _artifact_summary_value(artifacts, "unique_review_packets", "unique_packet_count", 0),
        "strong_risk_packets": _artifact_summary_value(artifacts, "unique_review_packets", "strong_risk_packets", 0),
        "hard_evidence_review_packets": _artifact_summary_value(artifacts, "unique_review_packets", "hard_evidence_review_packets", 0),
        "wallet_group_count": _artifact_summary_value(artifacts, "unique_review_packets", "wallet_group_count", 0),
        "market_group_count": _artifact_summary_value(artifacts, "unique_review_packets", "market_group_count", 0),
        "funding_unknown_packets": _artifact_summary_value(artifacts, "unique_review_packets", "funding_unknown_packets", 0),
        "gate_trace_missing_packets": _artifact_summary_value(artifacts, "unique_review_packets", "gate_trace_missing_packets", 0),
        "retrospective_only_packets": _artifact_summary_value(artifacts, "unique_review_packets", "retrospective_only_packets", 0),
        "case_reviewer_false_positive_count": _artifact_summary_value(
            artifacts, "case_reviewer_comparison", "case_reviewer_false_positive_count", 0
        ),
        "case_reviewer_plausible_count": _artifact_summary_value(artifacts, "case_reviewer_comparison", "case_reviewer_plausible_count", 0),
        "artifact_manifest_count": _artifact_summary_value(artifacts, "artifact_manifest", "artifact_count", 0),
        "packet_quality_missing_count": _artifact_summary_value(
            artifacts, "review_packet_quality_check", "packets_with_any_missing_quality_field", 0
        ),
        "source_schema_high_priority_field_count": _artifact_summary_value(
            artifacts, "source_schema_repair_plan", "high_priority_field_count", 0
        ),
        "source_schema_field_count": _artifact_summary_value(artifacts, "source_schema_repair_plan", "field_count", 0),
        "source_missing_field_counts": _artifact_summary_value(artifacts, "source_attribution_completeness", "missing_field_counts", {}),
        "schema_missing_by_field": _artifact_summary_value(artifacts, "schema_normalization_check", "missing_by_field", {}),
        "false_positive_top_patterns": _artifact_summary_value(artifacts, "false_positive_library", "top_patterns", []),
        "candidate_recall_interpretation": _artifact_payload_value(
            artifacts, "candidate_recall_diagnostic", "diagnostic_interpretation", "unknown"
        ),
        "report_consistency": _artifact_payload_value(artifacts, "report_consistency", "classification", "unknown"),
        "fresh_unique_gate_leakage_candidates": readiness_payload.get("freshUniqueGateLeakageCandidates", 0),
        "broad_saved_field_gate_leakage_candidates": readiness_payload.get("broadSavedFieldGateLeakageCandidates", 0),
        "her_invalid_condition_counts": readiness_payload.get("herInvalidConditionCounts", {}),
        "strong_risk_gate_trace": readiness_payload.get("strongRiskGateTrace", {}),
        "strong_risk_by_gate_family": strong_payload.get("strongRiskByGateFamily", {}),
        "strong_risk_diagnostic_recommendation": strong_payload.get("recommendation", "unknown"),
    }


def proposal(
    *,
    proposal_id: str,
    title: str,
    category: str,
    problem: str,
    current_evidence: str,
    evidence_class: str,
    would_change_model_behavior: bool,
    would_change_scoring_weights: bool,
    would_change_strong_risk_gate: bool,
    would_change_her_eligibility: bool,
    would_change_funding_eligibility: bool,
    would_change_candidate_admission: bool,
    risk_fp: str,
    risk_fn: str,
    analyst_value: str,
    implementation_risk: str,
    required_validation: list[str],
    minimum_fresh_evidence: str,
    recommended_decision: str,
    safe_next_step: str,
    forbidden_next_step: str,
    decision_matrix: str,
) -> dict[str, Any]:
    item = {
        "proposalId": proposal_id,
        "title": title,
        "category": category,
        "problem": problem,
        "currentEvidence": current_evidence,
        "evidenceClass": evidence_class,
        "wouldChangeModelBehavior": would_change_model_behavior,
        "wouldChangeScoringWeights": would_change_scoring_weights,
        "wouldChangeStrongRiskGate": would_change_strong_risk_gate,
        "wouldChangeHEREligibility": would_change_her_eligibility,
        "wouldChangeFundingEligibility": would_change_funding_eligibility,
        "wouldChangeCandidateAdmission": would_change_candidate_admission,
        "riskOfFalsePositiveIncrease": risk_fp,
        "riskOfFalseNegativeIncrease": risk_fn,
        "expectedAnalystValue": analyst_value,
        "implementationRisk": implementation_risk,
        "requiredValidationBeforeImplementation": required_validation,
        "minimumFreshEvidenceRequired": minimum_fresh_evidence,
        "recommendedDecision": recommended_decision,
        "safeNextStep": safe_next_step,
        "forbiddenNextStep": forbidden_next_step,
        "decisionMatrixBucket": decision_matrix,
    }
    validate_proposal(item)
    return item


def validate_proposal(item: Mapping[str, Any]) -> None:
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
    missing = required.difference(item)
    if missing:
        raise ValueError(f"proposal missing required keys: {sorted(missing)}")
    if item["evidenceClass"] not in EVIDENCE_CLASSES:
        raise ValueError(f"invalid evidenceClass: {item['evidenceClass']}")
    if item["recommendedDecision"] not in RECOMMENDED_DECISIONS:
        raise ValueError(f"invalid recommendedDecision: {item['recommendedDecision']}")
    if item["decisionMatrixBucket"] not in DECISION_MATRIX_BUCKETS:
        raise ValueError(f"invalid decision matrix bucket: {item['decisionMatrixBucket']}")
    changes_detector = any(
        bool(item.get(key))
        for key in (
            "wouldChangeModelBehavior",
            "wouldChangeScoringWeights",
            "wouldChangeStrongRiskGate",
            "wouldChangeHEREligibility",
            "wouldChangeFundingEligibility",
            "wouldChangeCandidateAdmission",
        )
    )
    if changes_detector and item["decisionMatrixBucket"] == "green_reporting_only_can_implement":
        raise ValueError(f"model-changing proposal cannot be green: {item['proposalId']}")
    if changes_detector and item["evidenceClass"] in {"cache_only", "saved_output_only", "retrospective_only", "insufficient"}:
        if item["recommendedDecision"] not in {"rfc_only_needs_fresh_validation", "defer_until_rpc_available", "reject_for_now"}:
            raise ValueError(f"model-changing weak-evidence proposal must be deferred: {item['proposalId']}")


def build_proposals(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    packet_count = evidence.get("unique_review_packets", 0)
    wallet_groups = evidence.get("wallet_group_count", 0)
    market_groups = evidence.get("market_group_count", 0)
    funding_unknown = evidence.get("funding_unknown_packets", 0)
    gate_missing = evidence.get("gate_trace_missing_packets", 0)
    retrospective = evidence.get("retrospective_only_packets", 0)
    fp_count = evidence.get("case_reviewer_false_positive_count", 0)
    source_missing = evidence.get("source_missing_field_counts", {})
    schema_missing = evidence.get("schema_missing_by_field", {})
    strong_by_family = evidence.get("strong_risk_by_gate_family", {})
    broad_saved = evidence.get("broad_saved_field_gate_leakage_candidates", 0)

    return [
        proposal(
            proposal_id="REPORT-001",
            title="Keep review packet quality checks as a first-class report",
            category="reporting_ui_analyst_workflow",
            problem="Analysts need to know whether packets have wallet, market, source, link, and explanation fields before relying on them.",
            current_evidence=f"The latest quality check covered {packet_count} packets and found {evidence.get('packet_quality_missing_count', 0)} packet(s) with missing quality fields.",
            evidence_class="analyst_quality_only",
            would_change_model_behavior=False,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="low",
            analyst_value="high",
            implementation_risk="low",
            required_validation=["Unit tests for missing optional fields.", "Manual open of generated Markdown."],
            minimum_fresh_evidence="None; reporting-only.",
            recommended_decision="implement_now_reporting_only",
            safe_next_step="Add this report to the Event Forensic saved-review drilldown or review index.",
            forbidden_next_step="Do not use quality coverage to alter scoring, severity, gates, or routing.",
            decision_matrix="green_reporting_only_can_implement",
        ),
        proposal(
            proposal_id="REPORT-002",
            title="Add immutable review artifact manifests to handoff workflow",
            category="reporting_ui_analyst_workflow",
            problem="Analysts and external reviewers need confidence that old saved outputs were not silently mutated.",
            current_evidence=f"The latest manifest listed {evidence.get('artifact_manifest_count', 'the current')} review artifacts; the handoff bundle is read-only.",
            evidence_class="analyst_quality_only",
            would_change_model_behavior=False,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="low",
            analyst_value="medium",
            implementation_risk="low",
            required_validation=["Hash existing latest artifacts.", "Confirm missing directories do not crash."],
            minimum_fresh_evidence="None; provenance/reporting-only.",
            recommended_decision="implement_now_reporting_only",
            safe_next_step="Surface latest manifest path in the review output index.",
            forbidden_next_step="Do not rewrite historical artifacts to make hashes match.",
            decision_matrix="green_reporting_only_can_implement",
        ),
        proposal(
            proposal_id="WORKFLOW-001",
            title="Promote wallet and market packet groups into analyst drilldown",
            category="reporting_ui_analyst_workflow",
            problem="Single packets are useful, but repeated wallet/market patterns are easier to triage in grouped views.",
            current_evidence=f"Latest packets produced {wallet_groups} wallet groups and {market_groups} market groups from {packet_count} unique packets.",
            evidence_class="analyst_quality_only",
            would_change_model_behavior=False,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="low",
            analyst_value="high",
            implementation_risk="medium",
            required_validation=["UI/backend drilldown smoke tests.", "Verify row-level packets remain accessible."],
            minimum_fresh_evidence="None; analyst-navigation-only.",
            recommended_decision="implement_now_reporting_only",
            safe_next_step="Add links/buttons from Event Forensic saved-review panel to latest grouped packet report.",
            forbidden_next_step="Do not hide or drop individual production rows based on grouping.",
            decision_matrix="green_reporting_only_can_implement",
        ),
        proposal(
            proposal_id="WORKFLOW-002",
            title="Add analyst sidecar decisions without feeding production scoring",
            category="reporting_ui_analyst_workflow",
            problem="The system lacks a durable way for Max or an analyst to mark packet review outcomes for later evaluation.",
            current_evidence="The advisory wallet queue is already separate from production priority and can support human review notes as a sidecar.",
            evidence_class="analyst_quality_only",
            would_change_model_behavior=False,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="low",
            analyst_value="high",
            implementation_risk="medium",
            required_validation=["Create sidecar-only schema tests.", "Confirm no scanner/archive/event-forensic code consumes sidecar labels for scoring."],
            minimum_fresh_evidence="None for sidecar capture; fresh evidence required before using labels to change detectors.",
            recommended_decision="implement_now_reporting_only",
            safe_next_step="Draft a local JSON sidecar format for analyst labels and review notes.",
            forbidden_next_step="Do not train, score, route, or suppress cases from sidecar labels without a separate approved RFC.",
            decision_matrix="green_reporting_only_can_implement",
        ),
        proposal(
            proposal_id="SCHEMA-001",
            title="Repair source attribution display gaps without broadening eligibility",
            category="source_schema_attribution",
            problem="Missing gate, source, and suppressor fields make strong cases harder to explain and weak cases harder to reject.",
            current_evidence=f"Source completeness found missing field counts {source_missing}; schema normalization found missing field counts {schema_missing}.",
            evidence_class="saved_output_only",
            would_change_model_behavior=False,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="low",
            analyst_value="high",
            implementation_risk="medium",
            required_validation=["Golden fixture for old and new saved outputs.", "Confirm repair only propagates already accepted source labels."],
            minimum_fresh_evidence="None for display/schema propagation; fresh validation required only if routing semantics change.",
            recommended_decision="rfc_only_needs_human_approval",
            safe_next_step="Prepare a source-propagation patch limited to report fields and tests.",
            forbidden_next_step="Do not add new HER-eligible source classes or broaden accepted HER routing.",
            decision_matrix="yellow_diagnostic_only_can_prepare",
        ),
        proposal(
            proposal_id="SCHEMA-002",
            title="Add gate-trace availability audit to review packet generation",
            category="source_schema_attribution",
            problem="Packets with missing gate trace force analysts to infer why Strong Risk appeared.",
            current_evidence=f"Latest packet summary reported {gate_missing} gate-trace-missing packets.",
            evidence_class="saved_output_only",
            would_change_model_behavior=False,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="low",
            analyst_value="medium",
            implementation_risk="low",
            required_validation=["Packet tests for gate_trace_available false/unknown.", "Report consistency remains count_reporting_consistent."],
            minimum_fresh_evidence="None; diagnostic-only.",
            recommended_decision="implement_now_reporting_only",
            safe_next_step="Emit a gate-trace coverage table by artifact and target family.",
            forbidden_next_step="Do not infer missing gate branches as proof of gate leakage.",
            decision_matrix="green_reporting_only_can_implement",
        ),
        proposal(
            proposal_id="SCHEMA-003",
            title="Keep source/navigation alias propagation as reporting-only schema repair",
            category="source_schema_attribution",
            problem="Saved outputs use multiple aliases for wallet, market, trade, source, and gate fields; analysts need a normalized packet view without changing detector logic.",
            current_evidence=f"The latest source/schema repair plan reported {evidence.get('source_schema_field_count', 0)} field actions, including {evidence.get('source_schema_high_priority_field_count', 0)} high-priority observations, and the final reporting patch has {evidence.get('final_safe_boundary_remaining', 0)} safe boundary fixes remaining.",
            evidence_class="saved_output_only",
            would_change_model_behavior=False,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="low",
            analyst_value="high",
            implementation_risk="low",
            required_validation=["Legacy saved-output fixture load.", "Assert normalized display aliases do not feed scoring or routing."],
            minimum_fresh_evidence="None for reporting-only alias propagation.",
            recommended_decision="prepare_diagnostic_only",
            safe_next_step="Keep alias propagation covered by packet/index quality tests and source-schema diagnostics.",
            forbidden_next_step="Do not treat missing aliases as evidence of detector failure or new HER eligibility.",
            decision_matrix="yellow_diagnostic_only_can_prepare",
        ),
        proposal(
            proposal_id="FP-001",
            title="Expand high-volume public-user false-positive explanations",
            category="false_positive_control",
            problem="High-volume public users can create repeated wins and high generic wallet scores without insider-style evidence.",
            current_evidence=f"Case Reviewer comparison has {fp_count} likely false-positive cases in the latest reviewed event, while the false-positive library shows recurring high-volume/public-user patterns.",
            evidence_class="saved_output_only",
            would_change_model_behavior=False,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="low",
            analyst_value="high",
            implementation_risk="low",
            required_validation=["False-positive library fixture tests.", "Verify warnings do not alter severity labels."],
            minimum_fresh_evidence="None for explanations; fresh evidence required for demotion rules.",
            recommended_decision="implement_now_reporting_only",
            safe_next_step="Add false-positive pattern snippets to wallet queue and review packet summaries.",
            forbidden_next_step="Do not auto-demote production Strong Risk rows from this saved-output-only evidence.",
            decision_matrix="green_reporting_only_can_implement",
        ),
        proposal(
            proposal_id="FP-002",
            title="RFC-only cap for high generic wallet score with zero insider-style score",
            category="false_positive_control",
            problem="A generic wallet score can look severe when insider-style evidence is absent.",
            current_evidence="Earlier Case Reviewer runs identified high walletScore, zero insiderStyleWalletScore, and no independent hard evidence as misleading for top insider-style ranking.",
            evidence_class="saved_output_only",
            would_change_model_behavior=True,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=True,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="medium",
            analyst_value="high",
            implementation_risk="high",
            required_validation=[
                "Fresh trace-enabled corpus with at least 8 completed fresh targets.",
                "Manual packet review proving no true linked/funding cases are demoted.",
                "Before/after severity distribution without duplicate inflation.",
            ],
            minimum_fresh_evidence="Fresh unique trace-enabled rows with independent-hard-evidence separation and reviewed high-volume wallet examples.",
            recommended_decision="rfc_only_needs_fresh_validation",
            safe_next_step="Draft only a decision memo and test plan; keep current production behavior unchanged.",
            forbidden_next_step="Do not implement a cap, demotion, gate edit, or weight edit from cache-only evidence.",
            decision_matrix="orange_rfc_requires_fresh_validation",
        ),
        proposal(
            proposal_id="FP-003",
            title="Keep false-positive pattern matches as analyst advisories only",
            category="false_positive_control",
            problem="False-positive patterns are useful as review questions, but using them as automatic suppressors would hide potentially valuable leads.",
            current_evidence=f"The false-positive library reports recurring advisory patterns and {evidence.get('case_reviewer_false_positive_count', 0)} Case Reviewer likely false-positive examples; latest review packets already mark advisory entries with automatic action disabled.",
            evidence_class="analyst_quality_only",
            would_change_model_behavior=False,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="low",
            analyst_value="high",
            implementation_risk="low",
            required_validation=["Assert `automatic_action_allowed` remains false.", "Assert advisory patterns do not alter severity or packet inclusion."],
            minimum_fresh_evidence="None for advisory display; fresh validation required before suppressor proposals.",
            recommended_decision="implement_now_reporting_only",
            safe_next_step="Continue exposing pattern-specific analyst questions and forbidden-use guardrails in reports.",
            forbidden_next_step="Do not auto-downgrade, suppress, reroute, or rescore cases from false-positive pattern matches.",
            decision_matrix="green_reporting_only_can_implement",
        ),
        proposal(
            proposal_id="FN-001",
            title="Broaden saved-output candidate recall diagnostics, not routing",
            category="false_negative_recall_diagnostic",
            problem="Potential near-miss candidates should be visible as diagnostics even when production routing remains unchanged.",
            current_evidence=f"Candidate recall diagnostic currently reports `{evidence.get('candidate_recall_interpretation', 'unknown')}` from saved outputs.",
            evidence_class="saved_output_only",
            would_change_model_behavior=False,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="low",
            analyst_value="medium",
            implementation_risk="medium",
            required_validation=["Fixtures for subthreshold structural/timing rows.", "Assert diagnostics do not modify routing."],
            minimum_fresh_evidence="None for diagnostics; fresh evidence required for recall/routing proposals.",
            recommended_decision="implement_now_reporting_only",
            safe_next_step="Add more stratified near-miss slices to the diagnostic output.",
            forbidden_next_step="Do not route additional rows to Strong Risk or HER.",
            decision_matrix="green_reporting_only_can_implement",
        ),
        proposal(
            proposal_id="FN-002",
            title="Create a local known-case benchmark scaffold",
            category="false_negative_recall_diagnostic",
            problem="Without a curated local benchmark, recall claims are anecdotal and hard to regression-test.",
            current_evidence="PROJECT_MEMORY notes that known public-case material is not yet represented as a full machine-readable benchmark in this checkout.",
            evidence_class="insufficient",
            would_change_model_behavior=False,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="low",
            analyst_value="high",
            implementation_risk="medium",
            required_validation=["Use repository/local artifacts only.", "Schema tests for benchmark rows and missing exact-wallet cases."],
            minimum_fresh_evidence="None for scaffold; exact recall conclusions require fresh runs and validated labels.",
            recommended_decision="rfc_only_needs_human_approval",
            safe_next_step="Create an empty/local-only benchmark schema and documentation.",
            forbidden_next_step="Do not ingest external journalism/news feeds or invent cases.",
            decision_matrix="yellow_diagnostic_only_can_prepare",
        ),
        proposal(
            proposal_id="FN-003",
            title="Export near-miss review cohorts with reason codes",
            category="false_negative_recall_diagnostic",
            problem="Analysts need to see why plausible near-misses stayed below visible review without changing thresholds.",
            current_evidence=f"Candidate recall diagnostic interpretation is `{evidence.get('candidate_recall_interpretation', 'unknown')}` and current artifacts are saved-output-only, so no recall change is indicated.",
            evidence_class="saved_output_only",
            would_change_model_behavior=False,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="low",
            analyst_value="high",
            implementation_risk="medium",
            required_validation=["Near-miss fixture with missing funding and missing gate trace.", "Assert exported cohorts are not used by scanner/archive/event-forensic routing."],
            minimum_fresh_evidence="None for diagnostic export; fresh trace-enabled evidence required before routing changes.",
            recommended_decision="prepare_diagnostic_only",
            safe_next_step="Prepare diagnostic-only near-miss slices by market, wallet, missing source, funding unknown, and gate-family reason.",
            forbidden_next_step="Do not admit near-misses into Strong Risk or HER from this diagnostic.",
            decision_matrix="yellow_diagnostic_only_can_prepare",
        ),
        proposal(
            proposal_id="SR-001",
            title="RFC-only review of retrospective correctness Strong Risk branches",
            category="strong_risk_gate_rfc",
            problem="Retrospective correctness can inflate apparent precision when outcome information was not live-detectable.",
            current_evidence=f"Latest packets include {retrospective} retrospective-only packets; Strong Risk by gate family includes {strong_by_family}; broad saved-field gate-leakage candidates are {broad_saved}, but fresh unique candidates are 0.",
            evidence_class="retrospective_only",
            would_change_model_behavior=True,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=True,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="high",
            analyst_value="high",
            implementation_risk="high",
            required_validation=[
                "Fresh trace-enabled unique rows, not broad saved-field screens.",
                "Gate trace coverage >= 80 percent on fresh rows.",
                "Manual branch-level review excluding duplicate inflation.",
            ],
            minimum_fresh_evidence="Fresh unique trace-enabled Strong Risk rows with exact gate branches and live-detectable flags.",
            recommended_decision="defer_until_rpc_available",
            safe_next_step="Keep as RFC-only hypothesis; prepare branch-level review worksheet.",
            forbidden_next_step="Do not edit Strong Risk gates while readiness is not_ready_corpus_too_cache_only.",
            decision_matrix="orange_rfc_requires_fresh_validation",
        ),
        proposal(
            proposal_id="SR-002",
            title="RFC-only review of score-threshold/legacy Strong Risk branch",
            category="strong_risk_gate_rfc",
            problem="Score-threshold or legacy branch cases may be less explainable than structural or trace-supported cases.",
            current_evidence=f"Strong Risk diagnostic by gate family includes {strong_by_family}; saved fields are insufficient and rerun with trace is recommended.",
            evidence_class="saved_output_only",
            would_change_model_behavior=True,
            would_change_scoring_weights=True,
            would_change_strong_risk_gate=True,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="medium",
            risk_fn="high",
            analyst_value="medium",
            implementation_risk="high",
            required_validation=["Fresh validation that isolates score-threshold rows.", "Before/after recall and false-positive review packets."],
            minimum_fresh_evidence="Fresh trace-enabled unique rows showing a repeat score-threshold issue not explainable by stale fields.",
            recommended_decision="defer_until_rpc_available",
            safe_next_step="Document branch-specific questions only.",
            forbidden_next_step="Do not change weights or score thresholds from saved-output evidence.",
            decision_matrix="orange_rfc_requires_fresh_validation",
        ),
        proposal(
            proposal_id="HER-001",
            title="Accepted-contract HER source propagation repair check",
            category="her_routing_rfc",
            problem="HER review value drops when accepted evidence source labels do not survive aggregation.",
            current_evidence=f"HER invalid condition counts are {evidence.get('her_invalid_condition_counts', {})}; only {evidence.get('hard_evidence_review_packets', 0)} HER packet appears in latest unique packets, while source gaps remain.",
            evidence_class="saved_output_only",
            would_change_model_behavior=False,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=False,
            risk_fp="low",
            risk_fn="low",
            analyst_value="high",
            implementation_risk="medium",
            required_validation=["Fixtures preserving accepted HER source labels through wallet aggregation.", "Assert no new HER-eligible sources are introduced."],
            minimum_fresh_evidence="None for accepted-source propagation; fresh evidence required for eligibility review.",
            recommended_decision="rfc_only_needs_human_approval",
            safe_next_step="Prepare a repair-only schema/source propagation RFC.",
            forbidden_next_step="Do not broaden HER eligibility or accepted source classes.",
            decision_matrix="yellow_diagnostic_only_can_prepare",
        ),
        proposal(
            proposal_id="HER-002",
            title="Reject HER routing broadening from saved-output-only evidence",
            category="her_routing_rfc",
            problem="Broadening HER routing from source-display gaps would convert a reporting/schema issue into detector behavior without fresh proof.",
            current_evidence=f"HER invalid condition counts remain {evidence.get('her_invalid_condition_counts', {})}; there is no accepted-contract violation shown by current cache-only artifacts.",
            evidence_class="insufficient",
            would_change_model_behavior=True,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=True,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=True,
            risk_fp="high",
            risk_fn="medium",
            analyst_value="medium",
            implementation_risk="high",
            required_validation=["Fresh accepted-contract violation examples.", "Manual review proving current HER routing drops eligible evidence.", "Regression tests showing no broadening of accepted HER rules."],
            minimum_fresh_evidence="Fresh trace-enabled rows with accepted HER sources missing from routing for reasons other than report propagation.",
            recommended_decision="reject_for_now",
            safe_next_step="Keep HER work limited to accepted-source propagation checks unless fresh violations appear.",
            forbidden_next_step="Do not broaden HER routing or add accepted source classes from saved-output-only evidence.",
            decision_matrix="red_do_not_implement_now",
        ),
        proposal(
            proposal_id="FUND-001",
            title="RFC-only suspicious funding quality review after RPC capacity",
            category="suspicious_funding_rfc",
            problem="Funding unknown dominates current packets, blocking reliable funding-based detector review.",
            current_evidence=f"Latest packet summary has {funding_unknown} funding-unknown packets and readiness remains `{evidence.get('readiness_classification')}`.",
            evidence_class="cache_only",
            would_change_model_behavior=True,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=False,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=True,
            would_change_candidate_admission=False,
            risk_fp="high",
            risk_fn="high",
            analyst_value="high",
            implementation_risk="high",
            required_validation=["Operator-approved RPC capacity.", "12-target and 24-target fresh smoke with funding-enabled targets > 0.", "Funding cache coverage by target family."],
            minimum_fresh_evidence="Fresh funding traces across multiple target families with success/failure separated from unknown.",
            recommended_decision="defer_until_rpc_available",
            safe_next_step="Keep funding review parked until RPC blocker clears.",
            forbidden_next_step="Do not make multi_hop_unknown, CEX proxy-only, or bridge proxy-only funding eligible.",
            decision_matrix="red_do_not_implement_now",
        ),
        proposal(
            proposal_id="STRUCT-001",
            title="RFC-only structural pre-admission precision review",
            category="structural_pre_admission_rfc",
            problem="Structural admission is powerful but fragile; widening it can flood analysts with coordinated-looking noise.",
            current_evidence="PROJECT_MEMORY identifies structural pre-admission and split-wallet/funder grouping as fragile; latest readiness is not fresh enough for branch changes.",
            evidence_class="insufficient",
            would_change_model_behavior=True,
            would_change_scoring_weights=False,
            would_change_strong_risk_gate=True,
            would_change_her_eligibility=False,
            would_change_funding_eligibility=False,
            would_change_candidate_admission=True,
            risk_fp="high",
            risk_fn="medium",
            analyst_value="medium",
            implementation_risk="high",
            required_validation=["Fresh trace-enabled structural cohort review.", "Manual examples of true/false structural clusters.", "No lowering floors or notional thresholds."],
            minimum_fresh_evidence="Fresh unique structural rows with independent support and exact source attribution.",
            recommended_decision="reject_for_now",
            safe_next_step="Document what evidence would be needed; do not implement.",
            forbidden_next_step="Do not broaden structural pre-admission or lower thresholds.",
            decision_matrix="red_do_not_implement_now",
        ),
    ]


def decision_matrix(proposals: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    matrix: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in sorted(DECISION_MATRIX_BUCKETS)}
    for item in proposals:
        matrix[str(item["decisionMatrixBucket"])].append(
            {
                "proposalId": item["proposalId"],
                "title": item["title"],
                "category": item["category"],
                "recommendedDecision": item["recommendedDecision"],
                "evidenceClass": item["evidenceClass"],
                "expectedAnalystValue": item["expectedAnalystValue"],
            }
        )
    return matrix


def build_prompt_pack(proposals: Sequence[Mapping[str, Any]], artifacts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    prompts = [
        prompt_item(
            "green_reporting_only_implementation",
            "Green reporting-only implementation",
            "Implementation allowed only for reporting/UI/output artifacts. Production detector behavior is forbidden.",
            [
                "AGENTS.md",
                "PROJECT_MEMORY.md",
                "tools/generate_unique_review_packets.py",
                "tools/analyst_review_quality_suite.py",
                "app/event_forensic_desktop.py",
                "app/browser_event_forensic_ui.html",
            ],
            "Implement one green reporting-only proposal from the RFC, such as surfacing packet quality, manifest, or handoff bundle paths in the UI/index.",
            [
                "python3 tools/analyst_review_quality_suite.py --only all",
                "python3 tools/strategic_backlog_dashboard.py",
            ],
            [
                "python3 -m py_compile tools/analyst_review_quality_suite.py app/event_forensic_desktop.py",
                "python3 -m unittest discover -s tests -p 'test_*.py'",
            ],
        ),
        prompt_item(
            "yellow_diagnostic_only_implementation",
            "Yellow diagnostic-only implementation",
            "Implementation allowed only for diagnostics. Production detector behavior is forbidden.",
            [
                "tools/source_attribution_completeness.py",
                "tools/review_schema_normalization_check.py",
                "tools/candidate_recall_diagnostic.py",
            ],
            "Prepare one yellow diagnostic output that improves review visibility without changing routing or labels.",
            [
                "python3 tools/source_attribution_completeness.py",
                "python3 tools/review_schema_normalization_check.py",
            ],
            ["python3 -m unittest discover -s tests -p 'test_*.py'"],
        ),
        prompt_item(
            "source_attribution_schema_audit",
            "Source attribution/schema audit",
            "Implementation allowed only for accepted-source propagation or reporting checks. HER eligibility changes are forbidden.",
            [
                "tools/source_attribution_completeness.py",
                "tools/review_schema_normalization_check.py",
                "tools/ai_case_reviewer.py",
                "app/event_forensic.py",
            ],
            "Audit source propagation from saved rows to packets and Case Reviewer output; propose repair-only patches if labels are dropped.",
            [
                "python3 tools/source_attribution_completeness.py",
                "python3 tools/review_schema_normalization_check.py",
            ],
            ["python3 -m unittest discover -s tests -p 'test_*.py'"],
        ),
        prompt_item(
            "candidate_recall_diagnostic",
            "Candidate recall diagnostic",
            "Implementation allowed only for diagnostic reporting. Routing or threshold changes are forbidden.",
            ["tools/candidate_recall_diagnostic.py", "review_packets/", "validation_corpus_outputs/"],
            "Expand saved-output near-miss diagnostics and clearly mark cache-only limitations.",
            ["python3 tools/candidate_recall_diagnostic.py"],
            ["python3 -m py_compile tools/candidate_recall_diagnostic.py", "python3 -m unittest discover -s tests -p 'test_*.py'"],
        ),
        prompt_item(
            "false_positive_library_expansion",
            "False-positive library expansion",
            "Implementation allowed only for explanations and reports. Automatic suppression is forbidden.",
            ["tools/false_positive_pattern_library.py", "tools/generate_unique_review_packets.py", "ai_review_outputs/"],
            "Expand false-positive pattern summaries for high-volume, near-certainty, stale/resolution-gap, and funding-unknown cases.",
            ["python3 tools/false_positive_pattern_library.py", "python3 tools/generate_unique_review_packets.py"],
            ["python3 -m unittest discover -s tests -p 'test_*.py'"],
        ),
        prompt_item(
            "fresh_validation_after_rpc_available",
            "Fresh validation after RPC becomes available",
            "Implementation allowed only for bounded validation once operator-approved RPC capacity is present. Detector edits are forbidden.",
            [
                ".inspoly_runtime.env",
                "tools/funding_resolver_healthcheck.py",
                "tools/trace_method_diagnostic.py",
                "tools/run_validation_corpus.py",
                "tools/gate_decision_readiness.py",
            ],
            "Run the bounded recovery ladder only after operator-approved RPC capacity is configured through existing env/config.",
            [
                "python3 tools/funding_resolver_healthcheck.py",
                "python3 tools/trace_method_diagnostic.py --timeout-seconds 90 --per-request-timeout-seconds 8",
                "python3 tools/run_validation_corpus.py --network-probe --max-targets 3 --timeout-seconds 300",
                "python3 tools/run_validation_corpus.py --auto-policy --max-targets 12 --timeout-seconds 900",
                "python3 tools/gate_decision_readiness.py --emit-next-action",
            ],
            ["python3 -m unittest discover -s tests -p 'test_*.py'"],
        ),
        prompt_item(
            "rfc_only_strong_risk_gate_review",
            "RFC-only Strong Risk gate review",
            "Production implementation is forbidden. Write an RFC only.",
            ["tools/strong_risk_gate_diagnostic.py", "tools/gate_decision_readiness.py", "review_packets/"],
            "If readiness thresholds pass in the future, isolate fresh unique trace-enabled Strong Risk gate issues and draft an RFC only.",
            ["python3 tools/strong_risk_gate_diagnostic.py", "python3 tools/gate_decision_readiness.py --emit-next-action"],
            ["python3 -m unittest discover -s tests -p 'test_*.py'"],
        ),
        prompt_item(
            "rfc_only_her_routing_review",
            "RFC-only HER routing review",
            "Production implementation is forbidden. HER routing or eligibility changes are forbidden without a future approval.",
            ["app/scanner.py", "app/archive_scanner.py", "app/event_forensic.py", "tools/source_schema_repair_plan.py"],
            "Review whether fresh accepted-contract HER evidence shows routing violations and write an RFC only; do not broaden HER eligibility.",
            ["python3 tools/source_schema_repair_plan.py"],
            ["python3 -m unittest discover -s tests -p 'test_*.py'"],
        ),
        prompt_item(
            "rfc_only_suspicious_funding_review",
            "RFC-only suspicious funding review",
            "Production implementation is forbidden. Funding eligibility changes are forbidden without a future approval.",
            ["app/funding_context.py", "tools/prewarm_funding_cache.py", "tools/gate_decision_readiness.py"],
            "After RPC capacity clears, review funding-quality evidence and write an RFC only; do not alter funding eligibility.",
            ["python3 tools/prewarm_funding_cache.py --corpus validation_corpus/post_v2_validation_corpus.json --max-targets 48 --timeout-seconds 900 --max-trace-timeouts 3"],
            ["python3 -m unittest discover -s tests -p 'test_*.py'"],
        ),
        prompt_item(
            "stop_state_governance_refresh",
            "Stop-state governance refresh",
            "Implementation is limited to governance artifacts. Detector edits are forbidden.",
            ["PROJECT_MEMORY.md", "tools/strategic_backlog_next_action.py", "tools/strategic_backlog_dashboard.py"],
            "Refresh next-action/dashboard artifacts and stop if no operator RPC capacity or explicit maintainer approval is present.",
            ["python3 tools/strategic_backlog_next_action.py", "python3 tools/strategic_backlog_dashboard.py"],
            ["python3 -m unittest tests.test_strategic_backlog_next_action tests.test_strategic_backlog_dashboard"],
        ),
    ]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_rfc": f"rfcs/{RFC_STEM}.md",
        "prompts": prompts,
        "invariants": HARD_CONSTRAINTS,
        "artifact_paths": {name: str(value.get("path") or "") for name, value in artifacts.items()},
    }


def prompt_item(
    prompt_id: str,
    title: str,
    implementation_policy: str,
    files_to_inspect: list[str],
    bounded_task: str,
    commands: list[str],
    tests: list[str],
) -> dict[str, Any]:
    prompt = f"""You are working in the InsPoly repository.

Role:
Act as a senior financial-forensic and technical analyst for InsPoly.

Current status assumptions:
- Use the latest local InsPoly artifacts before acting.
- If readiness is still `not_ready_corpus_too_cache_only`, do not overclaim detector evidence.
- If no operator-approved RPC config is present through existing env/config, do not run large fresh validation.
- A maintainer has not approved production detector/model/scoring/gate/HER/funding eligibility changes unless the current user message explicitly says so.

Implementation policy:
{implementation_policy}

Hard constraints:
{chr(10).join(f"- {item}" for item in HARD_CONSTRAINTS)}

Files to inspect:
{chr(10).join(f"- {item}" for item in files_to_inspect)}

Bounded task:
{bounded_task}

Commands:
{chr(10).join(f"- `{item}`" for item in commands)}

Tests:
{chr(10).join(f"- `{item}`" for item in tests)}

Stop conditions:
- Stop if work would change scoring, gates, production severity labels, HER routing, funding eligibility, structural thresholds, credentials, RPC URLs, or old saved outputs.
- Stop if evidence is cache-only, stale, duplicate-inflated, or retrospective-only but the conclusion requires fresh trace-enabled proof.
- Stop if implementation would require LLM/ML scoring or external signal ingestion.

Required final output:
- files changed;
- artifacts written;
- tests run and results;
- invariants preserved;
- whether implementation was allowed or forbidden;
- next ready-to-copy prompt.
"""
    return {
        "promptId": prompt_id,
        "title": title,
        "implementationPolicy": implementation_policy,
        "filesToInspect": files_to_inspect,
        "commands": commands,
        "tests": tests,
        "readyToCopyPrompt": prompt,
    }


def build_rfc_package() -> dict[str, Any]:
    artifacts = discover_artifacts()
    evidence = build_evidence_summary(artifacts)
    proposals = build_proposals(evidence)
    matrix = decision_matrix(proposals)
    prompt_pack = build_prompt_pack(proposals, artifacts)
    counts = Counter(item["decisionMatrixBucket"] for item in proposals)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "rfc_type": "RFC-only detector improvement review",
        "authorization": {
            "max_approved_rfc_only_detector_review": True,
            "production_detector_implementation_approved": False,
            "allowed_work": "analysis, recommendations, decision matrices, and ready-to-copy future prompts only",
            "forbidden_work": "production model, scoring, gate, HER routing, funding eligibility, candidate admission, threshold, or suppressor changes",
        },
        "artifact_paths": {name: str(value.get("path") or "") for name, value in artifacts.items()},
        "evidence_summary": evidence,
        "proposal_count": len(proposals),
        "decision_matrix_counts": dict(counts),
        "proposals": proposals,
        "decision_matrix": matrix,
        "prompt_pack": prompt_pack,
        "do_not_change": HARD_CONSTRAINTS,
        "safety": {
            "production_code_modified": False,
            "model_behavior_changed": False,
            "scoring_changed": False,
            "gates_changed": False,
            "her_or_funding_eligibility_changed": False,
            "old_outputs_mutated": False,
        },
    }


def render_rfc_markdown(package: Mapping[str, Any]) -> str:
    evidence = package.get("evidence_summary", {})
    proposals = package.get("proposals", [])
    matrix = package.get("decision_matrix", {})
    artifacts = package.get("artifact_paths", {})
    lines = [
        "# Detector Improvement RFC 20260505",
        "",
        "Status: RFC-only. No production detector implementation is approved in this document.",
        "",
        "## 1. Executive Summary",
        "",
        f"Max approved RFC-only detector review, not production detector implementation. InsPoly has strong local forensic reporting, but readiness remains `{evidence.get('readiness_classification')}` with recommendation `{evidence.get('readiness_recommendation')}`. The package therefore separates green reporting/workflow work from orange/red detector-behavior hypotheses that require fresh validation or explicit approval.",
        "",
        "## 2. Current Detector State",
        "",
        f"- Completed safe backlog items: {evidence.get('completed_backlog_items')}",
        f"- Available safe non-RPC items: {evidence.get('safe_non_rpc_available_items')}",
        f"- Human-approval/RFC backlog items: {evidence.get('human_approval_required_items')}",
        f"- RPC-blocked backlog items: {evidence.get('rpc_blocked_items')}",
        f"- Operator RPC configuration status: `{evidence.get('operator_rpc_configuration_status')}`",
        f"- Decision boundary state: `{evidence.get('decision_boundary_decision')}`",
        f"- Remaining safe boundary fixes: {evidence.get('final_safe_boundary_remaining')}",
        f"- Unique review packets: {evidence.get('unique_review_packets')}",
        f"- Wallet groups: {evidence.get('wallet_group_count')}",
        f"- Market groups: {evidence.get('market_group_count')}",
        f"- Report consistency: `{evidence.get('report_consistency')}`",
        "",
        "## 3. What InsPoly Already Does Well",
        "",
        "- Produces saved local artifacts for scanner, archive, event-forensic, Case Reviewer, packet review, false-positive patterns, and readiness.",
        "- Separates analyst workflow/reporting from production detector behavior.",
        "- Preserves strict invariants around Strong Risk, HER, funding eligibility, dedupe, and old saved outputs.",
        "- Now exposes packet grouping, source navigation, quality checks, wallet queues, handoff bundles, and artifact manifests.",
        "",
        "## 4. What Is Blocked By RPC And Cannot Be Concluded Yet",
        "",
        "- Fresh funding-enabled validation remains unavailable.",
        "- Suspicious funding quality and funding eligibility cannot be reviewed from cache-only evidence.",
        "- Strong Risk gate review is not production-ready.",
        "- Broad saved-field gate-leakage candidates are not enough to claim fresh gate leakage.",
        "",
        "## 5. What Current Artifacts Reveal About Suspicious Lead Quality",
        "",
        f"- Review packets: {evidence.get('unique_review_packets')} unique packets, including {evidence.get('strong_risk_packets')} Strong Risk packets and {evidence.get('hard_evidence_review_packets')} HER packets.",
        f"- Funding unknown remains high: {evidence.get('funding_unknown_packets')} packets.",
        f"- Gate trace gaps remain material: {evidence.get('gate_trace_missing_packets')} packets.",
        f"- Retrospective-only evidence is material: {evidence.get('retrospective_only_packets')} packets.",
        f"- Case Reviewer comparison found {evidence.get('case_reviewer_false_positive_count')} likely false-positive cases and {evidence.get('case_reviewer_plausible_count')} plausible cases in the latest Case Reviewer event, but 0 wallet matches with the latest broad review packet set.",
        "",
        "## 6. Main False-Positive Risks",
        "",
        "- High-volume public users can look suspicious from repeated wins without independent hard evidence.",
        "- Near-certainty and stale/resolution-gap cases can look strong retrospectively.",
        "- Domain specialists can appear sharp without private information.",
        "- Funding unknown can be misread as clean or suspicious; it is neither.",
        "",
        "## 7. Main False-Negative / Recall Risks",
        "",
        "- Candidate recall is not fully benchmarked against a curated known-case corpus.",
        "- Some source/schema gaps can hide why a case was routed or why a near-miss was rejected.",
        "- RPC blockage prevents fresh funding-supported recall diagnostics.",
        "",
        "## 8. Strong Risk Observations",
        "",
        f"- Strong Risk gate family counts from latest diagnostic: `{evidence.get('strong_risk_by_gate_family')}`.",
        f"- Fresh unique gate-leakage candidates: {evidence.get('fresh_unique_gate_leakage_candidates')}.",
        f"- Broad saved-field gate-leakage candidates: {evidence.get('broad_saved_field_gate_leakage_candidates')}.",
        "- Interpretation: gate review is RFC-only and must wait for fresh trace-enabled rows.",
        "",
        "## 9. Hard Evidence Review Observations",
        "",
        f"- HER invalid condition counts: `{evidence.get('her_invalid_condition_counts')}`.",
        "- Current concern is source propagation/explainability, not evidence of accepted-contract HER violation.",
        "",
        "## 10. Funding Evidence Observations",
        "",
        f"- Funding-unknown packets: {evidence.get('funding_unknown_packets')}.",
        "- Funding unavailable must remain `unknown`; no funding eligibility review is supportable until RPC capacity clears.",
        "",
        "## 11. Structural Pre-Admission Observations",
        "",
        "- Structural pre-admission is known fragile and should not be widened from cache-only evidence.",
        "- Any structural review must preserve existing floors, thresholds, and independent-support requirements.",
        "",
        "## 12. Retrospective/Cache-Only Limitations",
        "",
        f"- Retrospective-only packets: {evidence.get('retrospective_only_packets')}.",
        f"- Readiness classification: `{evidence.get('readiness_classification')}`.",
        "- Cache-only and retrospective-only evidence can generate hypotheses and review packets, not production detector conclusions.",
        "",
        "## 13. Candidate Detector Improvement Proposals",
        "",
    ]
    for item in proposals:
        lines.extend(render_proposal_markdown(item))
    lines.extend(
        [
            "## 14. Proposals Rejected Or Deferred",
            "",
        ]
    )
    for item in proposals:
        if item["recommendedDecision"] in {"reject_for_now", "defer_until_rpc_available", "rfc_only_needs_fresh_validation"}:
            lines.append(f"- `{item['proposalId']}` {item['title']}: {item['recommendedDecision']}.")
    lines.extend(
        [
            "",
            "## 15. Required Fresh Validation Before Any Model Change",
            "",
            "- Operator-approved RPC capacity through existing env/config.",
            "- 3-target network probe that does not stall.",
            "- 12-target and 24-target smoke runs with funding-enabled targets above zero.",
            "- Readiness no longer `not_ready_corpus_too_cache_only`.",
            "- Fresh unique trace-enabled rows with gate trace coverage at or above readiness thresholds.",
            "- Manual review packets isolating duplicate inflation, cache-only fields, and retrospective-only proof.",
            "",
            "## 16. Recommended Next Human Decisions",
            "",
            "- Decide whether to provide operator-approved RPC capacity.",
            "- Decide whether to approve green reporting-only UI/index implementation.",
            "- Decide whether to authorize a source-attribution repair-only patch.",
            "- Do not approve production detector edits from this RFC alone.",
            "",
            "## 17. Exact Next Prompts For Each Future Path",
            "",
            "See `rfcs/DETECTOR_IMPROVEMENT_PROMPT_PACK_20260505.md`.",
            "",
            "## 18. Do-Not-Change List",
            "",
        ]
    )
    for item in HARD_CONSTRAINTS:
        lines.append(f"- {item}")
    lines.extend(["", "## Decision Matrix", ""])
    for bucket, entries in matrix.items():
        lines.append(f"### {bucket}")
        if not entries:
            lines.append("- none")
        for entry in entries:
            lines.append(f"- `{entry['proposalId']}` {entry['title']} -> {entry['recommendedDecision']}")
        lines.append("")
    lines.extend(["## Evidence Paths", ""])
    for name, path in artifacts.items():
        lines.append(f"- {name}: {path or 'missing'}")
    return "\n".join(lines).rstrip() + "\n"


def render_proposal_markdown(item: Mapping[str, Any]) -> list[str]:
    lines = [
        f"### {item['proposalId']}: {item['title']}",
        "",
        f"- problem: {item['problem']}",
        f"- category: `{item['category']}`",
        f"- currentEvidence: {item['currentEvidence']}",
        f"- evidenceClass: `{item['evidenceClass']}`",
        f"- wouldChangeModelBehavior: `{item['wouldChangeModelBehavior']}`",
        f"- wouldChangeScoringWeights: `{item['wouldChangeScoringWeights']}`",
        f"- wouldChangeStrongRiskGate: `{item['wouldChangeStrongRiskGate']}`",
        f"- wouldChangeHEREligibility: `{item['wouldChangeHEREligibility']}`",
        f"- wouldChangeFundingEligibility: `{item['wouldChangeFundingEligibility']}`",
        f"- wouldChangeCandidateAdmission: `{item['wouldChangeCandidateAdmission']}`",
        f"- riskOfFalsePositiveIncrease: `{item['riskOfFalsePositiveIncrease']}`",
        f"- riskOfFalseNegativeIncrease: `{item['riskOfFalseNegativeIncrease']}`",
        f"- expectedAnalystValue: `{item['expectedAnalystValue']}`",
        f"- implementationRisk: `{item['implementationRisk']}`",
        f"- recommendedDecision: `{item['recommendedDecision']}`",
        f"- decisionMatrixBucket: `{item['decisionMatrixBucket']}`",
        f"- minimumFreshEvidenceRequired: {item['minimumFreshEvidenceRequired']}",
        "- requiredValidationBeforeImplementation:",
    ]
    for validation in item.get("requiredValidationBeforeImplementation", []):
        lines.append(f"  - {validation}")
    lines.extend(
        [
            f"- safeNextStep: {item['safeNextStep']}",
            f"- forbiddenNextStep: {item['forbiddenNextStep']}",
            "",
        ]
    )
    return lines


def render_prompt_pack_markdown(prompt_pack: Mapping[str, Any]) -> str:
    lines = [
        "# Detector Improvement Prompt Pack 20260505",
        "",
        "Use these prompts only under the implementation policy stated inside each prompt.",
        "",
    ]
    for item in prompt_pack.get("prompts", []):
        lines.extend(
            [
                f"## {item['title']}",
                "",
                f"- Prompt ID: `{item['promptId']}`",
                f"- Implementation policy: {item['implementationPolicy']}",
                "",
                "```text",
                item["readyToCopyPrompt"].rstrip(),
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(package: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved_output_dir = _resolve(output_dir) or output_dir
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    rfc_json_path = resolved_output_dir / f"{RFC_STEM}.json"
    rfc_md_path = resolved_output_dir / f"{RFC_STEM}.md"
    prompt_json_path = resolved_output_dir / f"{PROMPT_PACK_STEM}.json"
    prompt_md_path = resolved_output_dir / f"{PROMPT_PACK_STEM}.md"
    prompt_pack = package.get("prompt_pack") if isinstance(package.get("prompt_pack"), Mapping) else {}
    rfc_json_path.write_text(json.dumps(dict(package), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rfc_md_path.write_text(render_rfc_markdown(package), encoding="utf-8")
    prompt_json_path.write_text(json.dumps(dict(prompt_pack), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    prompt_md_path.write_text(render_prompt_pack_markdown(prompt_pack), encoding="utf-8")
    return {
        "rfc_json_path": str(rfc_json_path),
        "rfc_markdown_path": str(rfc_md_path),
        "prompt_pack_json_path": str(prompt_json_path),
        "prompt_pack_markdown_path": str(prompt_md_path),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate RFC-only detector improvement review documents.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    package = build_rfc_package()
    outputs = write_outputs(package, args.output_dir)
    counts = package.get("decision_matrix_counts", {})
    print(f"RFC JSON: {outputs['rfc_json_path']}")
    print(f"RFC markdown: {outputs['rfc_markdown_path']}")
    print(f"Prompt pack JSON: {outputs['prompt_pack_json_path']}")
    print(f"Prompt pack markdown: {outputs['prompt_pack_markdown_path']}")
    print(f"Proposal count: {package.get('proposal_count')}")
    print(f"Decision matrix counts: {json.dumps(counts, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
