from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("review_index_outputs")
SEARCH_DIRS = {
    "unique_review_packets": (Path("review_packets"), "unique_review_packets_*.json"),
    "review_packet_quality": (Path("analyst_quality_outputs"), "review_packet_quality_check_*.json"),
    "packet_quality_report": (Path("analyst_quality_outputs"), "packet_quality_report_*.json"),
    "packet_group_drilldown": (Path("analyst_quality_outputs"), "packet_group_drilldown_*.json"),
    "analyst_evidence_limitation_digest": (Path("analyst_quality_outputs"), "analyst_evidence_limitation_digest_*.json"),
    "analyst_readiness_cycle_summary": (Path("analyst_quality_outputs"), "analyst_readiness_cycle_summary_*.json"),
    "wallet_review_queue": (Path("analyst_quality_outputs"), "wallet_review_queue_*.json"),
    "analyst_decision_sidecar": (Path("analyst_sidecars"), "analyst_decision_sidecar_*.json"),
    "analyst_handoff_bundle": (Path("analyst_review_bundles"), "analyst_review_bundle_*.json"),
    "artifact_manifest": (Path("artifact_manifests"), "review_artifact_manifest_*.json"),
    "review_artifact_freshness_report": (Path("artifact_manifests"), "review_artifact_freshness_report_*.json"),
    "false_positive_library": (Path("false_positive_library"), "false_positive_pattern_library_*.json"),
    "false_positive_explanation_report": (Path("false_positive_library"), "false_positive_explanation_report_*.json"),
    "false_positive_guardrail_audit": (Path("false_positive_library"), "false_positive_guardrail_audit_*.json"),
    "candidate_recall_diagnostic": (Path("candidate_recall_outputs"), "candidate_recall_diagnostic_*.json"),
    "source_attribution_completeness": (Path("source_attribution_outputs"), "source_attribution_completeness_*.json"),
    "source_schema_repair_plan": (Path("source_schema_repair_outputs"), "source_schema_repair_plan_*.json"),
    "gate_trace_availability_audit": (Path("source_schema_repair_outputs"), "gate_trace_availability_audit_*.json"),
    "implementation_boundary": (Path("implementation_boundaries"), "implementation_boundary_*.json"),
    "analyst_crosswalk": (Path("implementation_boundaries"), "analyst_crosswalk_*.json"),
    "reporting_schema_patch_report": (Path("implementation_boundaries"), "reporting_schema_patch_report_*.json"),
    "case_reviewer_cases": (Path("ai_review_outputs"), "AI_CASE_REVIEW_CASES_*.json"),
    "case_reviewer_report": (Path("ai_review_outputs"), "AI_CASE_REVIEW_REPORT_*.md"),
    "case_reviewer_model_changes": (Path("ai_review_outputs"), "AI_CASE_REVIEW_MODEL_CHANGES_*.md"),
    "strategic_next_action": (Path("strategic_backlog_outputs"), "strategic_next_action_*.json"),
    "local_known_case_benchmark": (Path("known_case_benchmarks"), "local_known_case_benchmark_*.json"),
    "benchmark_labeling_workbench": (Path("known_case_benchmarks"), "benchmark_labeling_workbench_*.json"),
    "benchmark_label_readiness": (Path("known_case_benchmarks"), "benchmark_label_readiness_*.json"),
    "benchmark_label_priority_queue": (Path("known_case_benchmarks"), "benchmark_label_priority_queue_*.json"),
    "benchmark_label_priority_template": (Path("known_case_benchmarks"), "benchmark_label_priority_template_*.json"),
    "benchmark_label_handoff_pack": (Path("known_case_benchmarks"), "benchmark_label_handoff_pack_*.json"),
    "benchmark_label_worksheet": (Path("known_case_benchmarks"), "benchmark_label_worksheet_*.json"),
    "benchmark_label_action_pack": (Path("known_case_benchmarks"), "benchmark_label_action_pack_*.json"),
    "benchmark_label_csv_preflight": (Path("known_case_benchmarks"), "benchmark_label_csv_preflight_*.json"),
    "benchmark_label_completion_status": (Path("known_case_benchmarks"), "benchmark_label_completion_status_*.json"),
    "benchmark_label_expectation_report": (Path("known_case_benchmarks"), "benchmark_label_expectation_report_*.json"),
    "benchmark_label_cycle": (Path("known_case_benchmarks"), "benchmark_label_cycle_*.json"),
    "autonomous_branch_decision_report": (Path("autonomous_branch_outputs"), "autonomous_branch_decision_report_*.json"),
    "event_forensic_performance_audit": (Path("event_forensic_performance_outputs"), "event_forensic_performance_audit_*.json"),
    "event_forensic_performance_rfc": (Path("rfcs"), "EVENT_FORENSIC_PERFORMANCE_RFC_*.json"),
    "event_forensic_trade_collection_profile": (Path("event_forensic_performance_outputs"), "event_forensic_trade_collection_profile_*.json"),
    "event_forensic_perf001_progress_spec": (Path("event_forensic_performance_outputs"), "event_forensic_perf001_progress_spec_*.json"),
    "event_forensic_perf001_implementation_report": (Path("event_forensic_performance_outputs"), "event_forensic_perf001_implementation_report_*.json"),
    "event_forensic_scope_semantics_audit": (Path("event_forensic_scope_outputs"), "event_forensic_scope_semantics_audit_*.json"),
    "archive_visibility_doc_drift_audit": (Path("docs_audit_outputs"), "archive_visibility_doc_drift_audit_*.json"),
    "offline_timeline_coverage_audit": (Path("timeline_context_outputs"), "offline_timeline_coverage_audit_*.json"),
    "offline_timeline_template_pack": (Path("timeline_context_outputs"), "offline_timeline_template_pack_*.json"),
    "offline_timeline_csv_validation": (Path("timeline_context_outputs"), "offline_timeline_csv_validation_*.json"),
    "ui_runtime_dependency_audit": (Path("ui_readiness_outputs"), "ui_runtime_dependency_audit_*.json"),
    "ui_offline_readiness_plan": (Path("ui_readiness_outputs"), "ui_offline_readiness_plan_*.json"),
    "ui_offline_asset_manifest": (Path("ui_readiness_outputs"), "ui_offline_asset_manifest_*.json"),
    "ui_offline_implementation_preflight": (Path("ui_readiness_outputs"), "ui_offline_implementation_preflight_*.json"),
    "direct_script_import_audit": (Path("tooling_audit_outputs"), "direct_script_import_audit_*.json"),
    "direct_script_cli_smoke_audit": (Path("tooling_audit_outputs"), "direct_script_cli_smoke_audit_*.json"),
    "test_coverage_inventory_audit": (Path("tooling_audit_outputs"), "test_coverage_inventory_audit_*.json"),
    "autonomous_progress_chain": (Path("autonomous_progress_outputs"), "autonomous_progress_chain_*.json"),
    "autonomous_change_log": (Path("docs"), "INS_POLY_AUTONOMOUS_CHANGELOG_*.md"),
}

RELATED_KIND_MAP = {
    "unique_review_packets": (
        "packet_quality_report",
        "packet_group_drilldown",
        "analyst_evidence_limitation_digest",
        "analyst_readiness_cycle_summary",
        "analyst_decision_sidecar",
        "review_packet_quality",
        "analyst_handoff_bundle",
        "implementation_boundary",
        "analyst_crosswalk",
        "source_schema_repair_plan",
        "gate_trace_availability_audit",
        "false_positive_library",
        "false_positive_explanation_report",
        "false_positive_guardrail_audit",
        "candidate_recall_diagnostic",
        "reporting_schema_patch_report",
    ),
    "packet_quality_report": (
        "unique_review_packets",
        "packet_group_drilldown",
        "analyst_evidence_limitation_digest",
        "analyst_readiness_cycle_summary",
        "false_positive_library",
        "false_positive_explanation_report",
        "false_positive_guardrail_audit",
        "source_schema_repair_plan",
        "gate_trace_availability_audit",
        "candidate_recall_diagnostic",
        "analyst_handoff_bundle",
        "review_packet_quality",
    ),
    "packet_group_drilldown": (
        "unique_review_packets",
        "packet_quality_report",
        "analyst_evidence_limitation_digest",
        "analyst_decision_sidecar",
        "wallet_review_queue",
        "analyst_handoff_bundle",
        "false_positive_library",
        "false_positive_explanation_report",
        "false_positive_guardrail_audit",
        "source_schema_repair_plan",
        "gate_trace_availability_audit",
    ),
    "analyst_decision_sidecar": (
        "packet_quality_report",
        "unique_review_packets",
        "packet_group_drilldown",
        "analyst_handoff_bundle",
    ),
    "implementation_boundary": (
        "packet_quality_report",
        "analyst_crosswalk",
        "source_schema_repair_plan",
        "gate_trace_availability_audit",
        "false_positive_library",
        "false_positive_explanation_report",
        "false_positive_guardrail_audit",
        "candidate_recall_diagnostic",
        "unique_review_packets",
        "reporting_schema_patch_report",
    ),
    "analyst_crosswalk": (
        "packet_quality_report",
        "implementation_boundary",
        "source_schema_repair_plan",
        "gate_trace_availability_audit",
        "false_positive_library",
        "false_positive_explanation_report",
        "false_positive_guardrail_audit",
        "candidate_recall_diagnostic",
        "unique_review_packets",
        "reporting_schema_patch_report",
    ),
    "analyst_handoff_bundle": (
        "packet_quality_report",
        "packet_group_drilldown",
        "analyst_decision_sidecar",
        "artifact_manifest",
        "review_artifact_freshness_report",
        "unique_review_packets",
        "implementation_boundary",
        "analyst_crosswalk",
        "source_schema_repair_plan",
        "gate_trace_availability_audit",
        "false_positive_library",
        "false_positive_explanation_report",
        "false_positive_guardrail_audit",
        "candidate_recall_diagnostic",
        "reporting_schema_patch_report",
    ),
    "artifact_manifest": (
        "packet_quality_report",
        "packet_group_drilldown",
        "analyst_decision_sidecar",
        "unique_review_packets",
        "analyst_handoff_bundle",
        "false_positive_library",
        "false_positive_explanation_report",
        "false_positive_guardrail_audit",
        "source_schema_repair_plan",
        "gate_trace_availability_audit",
        "candidate_recall_diagnostic",
    ),
    "review_artifact_freshness_report": (
        "artifact_manifest",
        "analyst_handoff_bundle",
        "unique_review_packets",
        "packet_quality_report",
        "analyst_evidence_limitation_digest",
        "ui_offline_implementation_preflight",
    ),
    "gate_trace_availability_audit": (
        "source_schema_repair_plan",
        "source_attribution_completeness",
        "unique_review_packets",
        "packet_quality_report",
        "packet_group_drilldown",
        "analyst_evidence_limitation_digest",
        "analyst_readiness_cycle_summary",
        "analyst_handoff_bundle",
    ),
    "false_positive_explanation_report": (
        "false_positive_library",
        "false_positive_guardrail_audit",
        "packet_quality_report",
        "analyst_evidence_limitation_digest",
        "unique_review_packets",
        "wallet_review_queue",
        "analyst_handoff_bundle",
    ),
    "false_positive_guardrail_audit": (
        "false_positive_library",
        "false_positive_explanation_report",
        "packet_quality_report",
        "analyst_evidence_limitation_digest",
        "candidate_recall_diagnostic",
        "analyst_decision_sidecar",
    ),
    "analyst_evidence_limitation_digest": (
        "packet_quality_report",
        "candidate_recall_diagnostic",
        "gate_trace_availability_audit",
        "false_positive_explanation_report",
        "false_positive_guardrail_audit",
        "analyst_handoff_bundle",
    ),
    "analyst_readiness_cycle_summary": (
        "analyst_evidence_limitation_digest",
        "candidate_recall_diagnostic",
        "offline_timeline_coverage_audit",
        "false_positive_guardrail_audit",
        "review_artifact_freshness_report",
        "review_output_index",
        "artifact_manifest",
        "local_known_case_benchmark",
        "event_forensic_performance_audit",
        "archive_visibility_doc_drift_audit",
        "ui_runtime_dependency_audit",
        "autonomous_progress_chain",
    ),
    "local_known_case_benchmark": (
        "benchmark_labeling_workbench",
        "benchmark_label_readiness",
        "benchmark_label_priority_queue",
        "benchmark_label_worksheet",
        "benchmark_label_action_pack",
        "unique_review_packets",
        "case_reviewer_cases",
        "candidate_recall_diagnostic",
        "false_positive_library",
        "analyst_readiness_cycle_summary",
        "autonomous_progress_chain",
    ),
    "benchmark_labeling_workbench": (
        "local_known_case_benchmark",
        "benchmark_label_readiness",
        "benchmark_label_priority_queue",
        "unique_review_packets",
        "candidate_recall_diagnostic",
        "autonomous_progress_chain",
    ),
    "benchmark_label_readiness": (
        "benchmark_labeling_workbench",
        "benchmark_label_priority_queue",
        "benchmark_label_expectation_report",
        "local_known_case_benchmark",
        "candidate_recall_diagnostic",
        "autonomous_progress_chain",
    ),
    "benchmark_label_priority_queue": (
        "benchmark_labeling_workbench",
        "benchmark_label_priority_template",
        "benchmark_label_handoff_pack",
        "benchmark_label_worksheet",
        "benchmark_label_action_pack",
        "benchmark_label_csv_preflight",
        "benchmark_label_expectation_report",
        "benchmark_label_readiness",
        "local_known_case_benchmark",
        "candidate_recall_diagnostic",
        "unique_review_packets",
        "autonomous_branch_decision_report",
        "autonomous_progress_chain",
    ),
    "benchmark_label_priority_template": (
        "benchmark_label_priority_queue",
        "benchmark_label_handoff_pack",
        "benchmark_label_worksheet",
        "benchmark_label_action_pack",
        "benchmark_label_csv_preflight",
        "benchmark_label_expectation_report",
        "benchmark_label_completion_status",
        "benchmark_labeling_workbench",
        "benchmark_label_readiness",
        "autonomous_branch_decision_report",
        "autonomous_progress_chain",
    ),
    "benchmark_label_handoff_pack": (
        "benchmark_label_priority_queue",
        "benchmark_label_priority_template",
        "benchmark_label_worksheet",
        "benchmark_label_action_pack",
        "benchmark_label_csv_preflight",
        "benchmark_label_expectation_report",
        "benchmark_label_completion_status",
        "benchmark_labeling_workbench",
        "benchmark_label_readiness",
        "autonomous_branch_decision_report",
        "autonomous_progress_chain",
    ),
    "benchmark_label_worksheet": (
        "benchmark_label_priority_template",
        "benchmark_label_handoff_pack",
        "benchmark_label_completion_status",
        "benchmark_label_priority_queue",
        "benchmark_label_readiness",
        "benchmark_label_action_pack",
        "benchmark_label_csv_preflight",
        "benchmark_label_expectation_report",
        "autonomous_branch_decision_report",
        "autonomous_progress_chain",
    ),
    "benchmark_label_action_pack": (
        "benchmark_label_worksheet",
        "benchmark_label_priority_template",
        "benchmark_label_handoff_pack",
        "benchmark_label_csv_preflight",
        "benchmark_label_expectation_report",
        "benchmark_label_completion_status",
        "benchmark_label_readiness",
        "autonomous_branch_decision_report",
        "autonomous_progress_chain",
    ),
    "benchmark_label_csv_preflight": (
        "benchmark_label_priority_template",
        "benchmark_label_worksheet",
        "benchmark_label_action_pack",
        "benchmark_label_completion_status",
        "benchmark_label_expectation_report",
        "benchmark_label_readiness",
        "autonomous_progress_chain",
        "autonomous_branch_decision_report",
    ),
    "benchmark_label_completion_status": (
        "benchmark_label_priority_template",
        "benchmark_label_handoff_pack",
        "benchmark_label_worksheet",
        "benchmark_label_action_pack",
        "benchmark_label_csv_preflight",
        "benchmark_label_expectation_report",
        "benchmark_label_readiness",
        "benchmark_labeling_workbench",
        "autonomous_branch_decision_report",
        "autonomous_progress_chain",
    ),
    "benchmark_label_expectation_report": (
        "benchmark_labeling_workbench",
        "benchmark_label_readiness",
        "benchmark_label_csv_preflight",
        "benchmark_label_expectation_report",
        "benchmark_label_completion_status",
        "benchmark_label_cycle",
        "benchmark_label_action_pack",
        "benchmark_label_worksheet",
        "autonomous_progress_chain",
        "autonomous_branch_decision_report",
    ),
    "benchmark_label_cycle": (
        "benchmark_label_action_pack",
        "benchmark_label_csv_preflight",
        "benchmark_label_completion_status",
        "benchmark_label_readiness",
        "benchmark_label_expectation_report",
        "benchmark_label_priority_template",
        "benchmark_label_worksheet",
        "autonomous_progress_chain",
        "autonomous_branch_decision_report",
    ),
    "event_forensic_performance_audit": (
        "local_known_case_benchmark",
        "event_forensic_performance_rfc",
        "event_forensic_trade_collection_profile",
        "event_forensic_perf001_progress_spec",
        "event_forensic_perf001_implementation_report",
        "analyst_evidence_limitation_digest",
        "autonomous_progress_chain",
    ),
    "event_forensic_performance_rfc": (
        "event_forensic_performance_audit",
        "event_forensic_trade_collection_profile",
        "event_forensic_perf001_progress_spec",
        "event_forensic_perf001_implementation_report",
        "autonomous_progress_chain",
    ),
    "event_forensic_trade_collection_profile": (
        "event_forensic_performance_audit",
        "event_forensic_performance_rfc",
        "event_forensic_perf001_progress_spec",
        "event_forensic_perf001_implementation_report",
        "event_forensic_scope_semantics_audit",
        "autonomous_progress_chain",
    ),
    "event_forensic_perf001_progress_spec": (
        "event_forensic_trade_collection_profile",
        "event_forensic_performance_rfc",
        "event_forensic_performance_audit",
        "event_forensic_perf001_implementation_report",
        "autonomous_progress_chain",
    ),
    "event_forensic_perf001_implementation_report": (
        "event_forensic_perf001_progress_spec",
        "event_forensic_trade_collection_profile",
        "event_forensic_performance_rfc",
        "autonomous_progress_chain",
    ),
    "event_forensic_scope_semantics_audit": (
        "event_forensic_performance_audit",
        "autonomous_progress_chain",
    ),
    "archive_visibility_doc_drift_audit": (
        "analyst_readiness_cycle_summary",
        "autonomous_progress_chain",
    ),
    "offline_timeline_coverage_audit": (
        "offline_timeline_template_pack",
        "analyst_readiness_cycle_summary",
        "unique_review_packets",
        "candidate_recall_diagnostic",
        "autonomous_progress_chain",
    ),
    "offline_timeline_template_pack": (
        "offline_timeline_coverage_audit",
        "offline_timeline_csv_validation",
        "analyst_readiness_cycle_summary",
        "autonomous_progress_chain",
    ),
    "offline_timeline_csv_validation": (
        "offline_timeline_template_pack",
        "offline_timeline_coverage_audit",
        "analyst_readiness_cycle_summary",
        "autonomous_progress_chain",
    ),
    "ui_runtime_dependency_audit": (
        "ui_offline_readiness_plan",
        "ui_offline_asset_manifest",
        "ui_offline_implementation_preflight",
        "review_artifact_freshness_report",
        "analyst_handoff_bundle",
        "autonomous_progress_chain",
    ),
    "ui_offline_readiness_plan": (
        "ui_runtime_dependency_audit",
        "ui_offline_asset_manifest",
        "ui_offline_implementation_preflight",
        "autonomous_progress_chain",
    ),
    "ui_offline_asset_manifest": (
        "ui_runtime_dependency_audit",
        "ui_offline_readiness_plan",
        "ui_offline_implementation_preflight",
        "autonomous_progress_chain",
    ),
    "ui_offline_implementation_preflight": (
        "ui_runtime_dependency_audit",
        "ui_offline_readiness_plan",
        "ui_offline_asset_manifest",
        "autonomous_progress_chain",
    ),
    "direct_script_import_audit": (
        "direct_script_cli_smoke_audit",
        "autonomous_progress_chain",
        "autonomous_change_log",
    ),
    "direct_script_cli_smoke_audit": (
        "direct_script_import_audit",
        "test_coverage_inventory_audit",
        "autonomous_progress_chain",
        "autonomous_change_log",
    ),
    "test_coverage_inventory_audit": (
        "direct_script_cli_smoke_audit",
        "direct_script_import_audit",
        "autonomous_progress_chain",
        "autonomous_change_log",
    ),
    "autonomous_progress_chain": (
        "local_known_case_benchmark",
        "benchmark_labeling_workbench",
        "benchmark_label_readiness",
        "benchmark_label_priority_queue",
        "benchmark_label_priority_template",
        "benchmark_label_handoff_pack",
        "benchmark_label_worksheet",
        "benchmark_label_action_pack",
        "benchmark_label_csv_preflight",
        "benchmark_label_expectation_report",
        "benchmark_label_completion_status",
        "benchmark_label_cycle",
        "autonomous_branch_decision_report",
            "event_forensic_performance_audit",
            "event_forensic_performance_rfc",
            "event_forensic_trade_collection_profile",
            "event_forensic_perf001_progress_spec",
            "event_forensic_perf001_implementation_report",
        "event_forensic_scope_semantics_audit",
        "archive_visibility_doc_drift_audit",
        "offline_timeline_coverage_audit",
        "offline_timeline_template_pack",
        "offline_timeline_csv_validation",
        "ui_runtime_dependency_audit",
        "ui_offline_readiness_plan",
        "ui_offline_asset_manifest",
        "ui_offline_implementation_preflight",
        "direct_script_import_audit",
        "direct_script_cli_smoke_audit",
        "test_coverage_inventory_audit",
        "analyst_readiness_cycle_summary",
        "strategic_next_action",
        "autonomous_change_log",
    ),
    "autonomous_change_log": (
        "autonomous_progress_chain",
        "benchmark_label_readiness",
        "benchmark_label_priority_queue",
        "benchmark_label_priority_template",
        "benchmark_label_handoff_pack",
        "benchmark_label_worksheet",
        "benchmark_label_action_pack",
        "benchmark_label_csv_preflight",
        "benchmark_label_expectation_report",
        "benchmark_label_completion_status",
        "benchmark_label_cycle",
        "autonomous_branch_decision_report",
        "event_forensic_scope_semantics_audit",
        "event_forensic_performance_audit",
        "event_forensic_trade_collection_profile",
        "event_forensic_perf001_progress_spec",
        "event_forensic_perf001_implementation_report",
        "ui_offline_readiness_plan",
        "ui_offline_asset_manifest",
        "direct_script_import_audit",
        "direct_script_cli_smoke_audit",
        "test_coverage_inventory_audit",
        "strategic_next_action",
    ),
    "reporting_schema_patch_report": (
        "unique_review_packets",
        "packet_quality_report",
        "review_packet_quality",
        "analyst_handoff_bundle",
        "implementation_boundary",
        "analyst_crosswalk",
    ),
    "autonomous_branch_decision_report": (
        "autonomous_progress_chain",
        "strategic_next_action",
        "benchmark_label_priority_queue",
        "benchmark_label_priority_template",
        "benchmark_label_handoff_pack",
        "benchmark_label_worksheet",
        "benchmark_label_action_pack",
        "benchmark_label_csv_preflight",
        "benchmark_label_expectation_report",
        "benchmark_label_completion_status",
        "benchmark_label_cycle",
        "benchmark_label_readiness",
        "ui_offline_asset_manifest",
        "ui_runtime_dependency_audit",
        "direct_script_import_audit",
    ),
}


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _latest_files(directory: Path, pattern: str, limit: int) -> list[Path]:
    root = _resolve(directory) or directory
    if not root.exists():
        return []
    return sorted(root.glob(pattern), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)[:limit]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _summary_for_json(path: Path, kind: str) -> dict[str, Any]:
    payload = _load_json(path)
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    result: dict[str, Any] = {}
    if kind == "unique_review_packets":
        result = {
            "unique_packet_count": summary.get("unique_packet_count", 0),
            "strong_risk_packets": summary.get("strong_risk_packets", 0),
            "hard_evidence_review_packets": summary.get("hard_evidence_review_packets", 0),
            "overlap_packets": summary.get("overlap_packets", 0),
        }
    elif kind == "review_packet_quality":
        result = {
            "packet_count": summary.get("packet_count", 0),
            "packets_with_any_missing_quality_field": summary.get("packets_with_any_missing_quality_field", 0),
            "read_only": summary.get("read_only", True),
        }
    elif kind == "packet_quality_report":
        quality_summary = payload.get("qualitySummary") if isinstance(payload.get("qualitySummary"), Mapping) else {}
        warnings = payload.get("warningsSummary") if isinstance(payload.get("warningsSummary"), Mapping) else {}
        result = {
            "packet_count": payload.get("packetCount", quality_summary.get("packetCount", 0)),
            "priority_review_queue_count": quality_summary.get("priorityReviewQueueCount", 0),
            "packets_with_missing_high_value_fields": quality_summary.get("packetsWithMissingHighValueFields", 0),
            "packets_with_cache_only_evidence": quality_summary.get("packetsWithCacheOnlyEvidence", 0),
            "packets_with_retrospective_only_evidence": quality_summary.get("packetsWithRetrospectiveOnlyEvidence", 0),
            "packets_with_false_positive_advisory_matches": quality_summary.get("packetsWithFalsePositiveAdvisoryMatches", 0),
            "warning_counts": warnings.get("warningCounts", {}),
            "read_only": quality_summary.get("readOnly", True),
            "model_behavior_changed": quality_summary.get("modelBehaviorChanged", False),
        }
    elif kind == "packet_group_drilldown":
        group_summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
        result = {
            "wallet_group_count": group_summary.get("walletGroupCount", 0),
            "market_group_count": group_summary.get("marketGroupCount", 0),
            "high_priority_group_count": group_summary.get("highPriorityGroupCount", 0),
            "medium_priority_group_count": group_summary.get("mediumPriorityGroupCount", 0),
            "read_only": group_summary.get("readOnly", True),
            "model_behavior_changed": group_summary.get("modelBehaviorChanged", False),
            "production_priority_changed": group_summary.get("productionPriorityChanged", False),
        }
    elif kind == "analyst_evidence_limitation_digest":
        result = {
            "limitation_row_count": summary.get("limitationRowCount", 0),
            "active_limitation_count": summary.get("activeLimitationCount", 0),
            "packet_count": summary.get("packetCount", 0),
            "readiness_classification": summary.get("readinessClassification", "unknown"),
            "guardrails_passed": summary.get("guardrailsPassed", False),
            "automatic_action_allowed": summary.get("automaticActionAllowed", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "analyst_readiness_cycle_summary":
        result = {
            "cycle_count": summary.get("cycleCount", 0),
            "readiness_classification": summary.get("readinessClassification", "unknown"),
            "review_index_entry_count": summary.get("reviewIndexEntryCount", 0),
            "manifest_artifact_count": summary.get("manifestArtifactCount", 0),
            "guardrails_passed": summary.get("guardrailsPassed", False),
            "active_limitation_count": summary.get("activeLimitationCount", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
            "old_outputs_mutated": summary.get("oldOutputsMutated", False),
        }
    elif kind == "wallet_review_queue":
        result = {
            "wallet_count": summary.get("wallet_count", 0),
            "advisory_only": summary.get("advisory_only", True),
            "production_priority_changed": summary.get("production_priority_changed", False),
        }
    elif kind == "analyst_decision_sidecar":
        result = {
            "sidecar_row_count": summary.get("sidecarRowCount", 0),
            "production_use_allowed": summary.get("productionUseAllowed", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
            "scoring_changed": summary.get("scoringChanged", False),
            "gates_changed": summary.get("gatesChanged", False),
            "candidate_admission_changed": summary.get("candidateAdmissionChanged", False),
        }
    elif kind == "analyst_handoff_bundle":
        result = {
            "packet_count": summary.get("packet_count", 0),
            "wallet_group_count": summary.get("wallet_group_count", 0),
            "market_group_count": summary.get("market_group_count", 0),
            "model_behavior_changed": summary.get("model_behavior_changed", False),
        }
    elif kind == "artifact_manifest":
        result = {
            "artifact_count": summary.get("artifact_count", 0),
            "existing_artifact_count": summary.get("existing_artifact_count", 0),
            "missing_artifact_count": summary.get("missing_artifact_count", 0),
            "hash_covered_artifact_count": summary.get("hash_covered_artifact_count", 0),
            "missing_required_artifacts": summary.get("missing_required_artifacts", []),
            "required_artifact_status": summary.get("required_artifact_status", {}),
            "old_outputs_mutated": summary.get("old_outputs_mutated", False),
        }
    elif kind == "review_artifact_freshness_report":
        result = {
            "indexed_kind_count": summary.get("indexedKindCount", 0),
            "index_entry_count": summary.get("indexEntryCount", 0),
            "missing_latest_artifact_count": summary.get("missingLatestArtifactCount", 0),
            "stale_over_24h_count": summary.get("staleOver24hCount", 0),
            "related_reference_count": summary.get("relatedReferenceCount", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
            "old_outputs_mutated": summary.get("oldOutputsMutated", False),
        }
    elif kind == "false_positive_library":
        result = {
            "pattern_count": summary.get("pattern_count", 0),
            "likely_false_positive_examples": summary.get("case_reviewer_likely_false_positive_examples", 0),
            "top_patterns": summary.get("top_patterns", [])[:5],
        }
    elif kind == "false_positive_explanation_report":
        result = {
            "pattern_count": summary.get("patternCount", 0),
            "packet_count": summary.get("packetCount", 0),
            "packets_with_false_positive_advisory_matches": summary.get("packetsWithFalsePositiveAdvisoryMatches", 0),
            "automatic_action_allowed": summary.get("automaticActionAllowed", False),
            "false_positive_library_used_for_scoring": summary.get("falsePositiveLibraryUsedForScoring", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "false_positive_guardrail_audit":
        result = {
            "artifact_count": summary.get("artifactCount", 0),
            "existing_artifact_count": summary.get("existingArtifactCount", 0),
            "violation_count": summary.get("violationCount", 0),
            "guardrails_passed": summary.get("guardrailsPassed", False),
            "automatic_action_allowed": summary.get("automaticActionAllowed", False),
            "false_positive_library_used_for_scoring": summary.get("falsePositiveLibraryUsedForScoring", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "candidate_recall_diagnostic":
        near_miss = payload.get("near_miss_visibility") if isinstance(payload.get("near_miss_visibility"), Mapping) else {}
        stratified = (
            payload.get("stratified_saved_output_recall")
            if isinstance(payload.get("stratified_saved_output_recall"), Mapping)
            else {}
        )
        stratified_summary = stratified.get("summary") if isinstance(stratified.get("summary"), Mapping) else {}
        result = {
            "diagnostic_interpretation": payload.get("diagnostic_interpretation", ""),
            "fresh_validation_required": summary.get("fresh_validation_required", False),
            "funnel_file_count": near_miss.get("funnel_file_count", 0),
            "stratified_slice_count": summary.get("stratified_slice_count", stratified_summary.get("slice_count", 0)),
            "packet_rows_inspected": summary.get("packet_rows_inspected", stratified_summary.get("packet_rows_inspected", 0)),
            "cache_only_or_funding_unknown_packets": summary.get("cache_only_or_funding_unknown_packets", 0),
            "retrospective_only_packets": summary.get("retrospective_only_packets", 0),
            "gate_trace_missing_packets": summary.get("gate_trace_missing_packets", 0),
            "model_behavior_changed": summary.get("model_behavior_changed", False),
        }
    elif kind == "source_attribution_completeness":
        result = {
            "rows_inspected": summary.get("rows_inspected", 0),
            "rows_with_missing_fields": summary.get("rows_with_missing_fields", 0),
            "missing_field_counts": summary.get("missing_field_counts", {}),
        }
    elif kind == "source_schema_repair_plan":
        result = {
            "field_count": summary.get("field_count", 0),
            "high_priority_field_count": summary.get("high_priority_field_count", 0),
            "total_combined_missing_fields": summary.get("total_combined_missing_fields", 0),
            "detector_behavior_changed": summary.get("detector_behavior_changed", False),
        }
    elif kind == "gate_trace_availability_audit":
        result = {
            "packet_count": summary.get("packetCount", 0),
            "strong_risk_packet_count": summary.get("strongRiskPacketCount", 0),
            "strong_risk_gate_trace_available_count": summary.get("strongRiskGateTraceAvailableCount", 0),
            "strong_risk_gate_trace_missing_count": summary.get("strongRiskGateTraceMissingCount", 0),
            "strong_risk_gate_trace_coverage_ratio": summary.get("strongRiskGateTraceCoverageRatio", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
            "gates_changed": summary.get("gatesChanged", False),
        }
    elif kind == "implementation_boundary":
        result = {
            "issue_count": summary.get("issue_count", 0),
            "safe_fix_count": summary.get("safe_fix_count", 0),
            "category_counts": summary.get("category_counts", {}),
            "model_behavior_changed": summary.get("model_behavior_changed", False),
        }
    elif kind == "analyst_crosswalk":
        result = {
            "crosswalk_count": summary.get("crosswalk_count", 0),
            "model_behavior_changed": summary.get("model_behavior_changed", False),
        }
    elif kind == "reporting_schema_patch_report":
        result = {
            "selected_issue_count": summary.get("selected_issue_count", 0),
            "safe_fixes_implemented": summary.get("safe_fixes_implemented", 0),
            "model_behavior_changed": summary.get("model_behavior_changed", False),
            "rfc_only_issues_left_untouched": summary.get("rfc_only_issues_left_untouched", 0),
            "rpc_blocked_issues_left_untouched": summary.get("rpc_blocked_issues_left_untouched", 0),
        }
    elif kind == "case_reviewer_cases":
        result = dict(summary) if summary else {
            "case_packets": len(payload.get("case_packets") or []),
            "reviews": len(payload.get("reviews") or []),
        }
    elif kind == "strategic_next_action":
        result = {
            "decision": payload.get("decision", ""),
            "recommended_next_task": payload.get("recommended_next_task", ""),
            "selected_item": (payload.get("selected_item") or {}).get("id") if isinstance(payload.get("selected_item"), Mapping) else "",
        }
    elif kind == "local_known_case_benchmark":
        result = {
            "row_count": summary.get("rowCount", 0),
            "packet_candidate_rows": summary.get("packetCandidateRows", 0),
            "event_run_rows": summary.get("eventRunRows", 0),
            "human_labeled_rows": summary.get("humanLabeledRows", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "benchmark_labeling_workbench":
        result = {
            "source_row_count": summary.get("sourceRowCount", 0),
            "label_template_row_count": summary.get("labelTemplateRowCount", 0),
            "required_label_field_count": summary.get("requiredLabelFieldCount", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "benchmark_label_readiness":
        result = {
            "source_row_count": summary.get("sourceRowCount", 0),
            "usable_labeled_rows": summary.get("usableLabeledRows", 0),
            "invalid_label_rows": summary.get("invalidLabelRows", 0),
            "missing_required_label_rows": summary.get("missingRequiredLabelRows", 0),
            "readiness_status": summary.get("readinessStatus", "unknown"),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "benchmark_label_priority_queue":
        result = {
            "source_row_count": summary.get("sourceRowCount", 0),
            "queue_row_count": summary.get("queueRowCount", 0),
            "high_priority_row_count": summary.get("highPriorityRowCount", 0),
            "medium_priority_row_count": summary.get("mediumPriorityRowCount", 0),
            "packet_row_count": summary.get("packetRowCount", 0),
            "event_run_row_count": summary.get("eventRunRowCount", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "benchmark_label_priority_template":
        result = {
            "template_row_count": summary.get("templateRowCount", 0),
            "required_label_field_count": summary.get("requiredLabelFieldCount", 0),
            "human_labels_assigned_by_this_tool": summary.get("humanLabelsAssignedByThisTool", 0),
            "ready_for_benchmark_readiness_gate": summary.get("readyForBenchmarkReadinessGate", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "benchmark_label_handoff_pack":
        result = {
            "queue_row_count": summary.get("queueRowCount", 0),
            "high_priority_row_count": summary.get("highPriorityRowCount", 0),
            "packet_row_count": summary.get("packetRowCount", 0),
            "event_run_row_count": summary.get("eventRunRowCount", 0),
            "human_labels_assigned_by_this_tool": summary.get("humanLabelsAssignedByThisTool", 0),
            "readiness_compatible_template_present": summary.get("readinessCompatibleTemplatePresent", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "benchmark_label_worksheet":
        result = {
            "worksheet_row_count": summary.get("worksheetRowCount", 0),
            "high_priority_row_count": summary.get("highPriorityRowCount", 0),
            "packet_row_count": summary.get("packetRowCount", 0),
            "event_run_row_count": summary.get("eventRunRowCount", 0),
            "labels_assigned_by_this_tool": summary.get("labelsAssignedByThisTool", 0),
            "readiness_gate_compatible": summary.get("readinessGateCompatible", False),
            "completion_status_at_generation": summary.get("completionStatusAtGeneration", "unknown"),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "benchmark_label_action_pack":
        result = {
            "template_row_count": summary.get("templateRowCount", 0),
            "worksheet_row_count": summary.get("worksheetRowCount", 0),
            "completion_status": summary.get("completionStatus", "unknown"),
            "csv_preflight_status": summary.get("csvPreflightStatus", "unknown"),
            "usable_label_rows": summary.get("usableLabelRows", 0),
            "invalid_label_rows": summary.get("invalidLabelRows", 0),
            "readiness_status": summary.get("readinessStatus", "unknown"),
            "human_action_required": summary.get("humanActionRequired", True),
            "labels_assigned_by_this_tool": summary.get("labelsAssignedByThisTool", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "benchmark_label_csv_preflight":
        result = {
            "preflight_status": summary.get("preflightStatus", "unknown"),
            "template_row_count": summary.get("templateRowCount", 0),
            "label_row_count": summary.get("labelRowCount", 0),
            "usable_label_rows": summary.get("usableLabelRows", 0),
            "invalid_label_rows": summary.get("invalidLabelRows", 0),
            "missing_required_label_rows": summary.get("missingRequiredLabelRows", 0),
            "immutable_field_mismatch_count": summary.get("immutableFieldMismatchCount", 0),
            "readiness_gate_recommended": summary.get("readinessGateRecommended", False),
            "labels_assigned_by_this_tool": summary.get("labelsAssignedByThisTool", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "benchmark_label_expectation_report":
        result = {
            "expectation_status": summary.get("expectationStatus", "unknown"),
            "source_row_count": summary.get("sourceRowCount", 0),
            "usable_labeled_rows": summary.get("usableLabeledRows", 0),
            "invalid_label_rows": summary.get("invalidLabelRows", 0),
            "missing_required_label_rows": summary.get("missingRequiredLabelRows", 0),
            "fresh_validation_required_rows": summary.get("freshValidationRequiredRows", 0),
            "disposition_counts": summary.get("dispositionCounts", {}),
            "review_flag_counts": summary.get("reviewFlagCounts", {}),
            "labels_assigned_by_this_tool": summary.get("labelsAssignedByThisTool", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "benchmark_label_completion_status":
        result = {
            "csv_file_count": summary.get("csvFileCount", summary.get("candidateCsvCount", 0)),
            "candidate_csv_count": summary.get("candidateCsvCount", 0),
            "candidate_filled_csv_count": summary.get("candidateFilledCsvCount", 0),
            "selected_completion_status": summary.get("selectedCompletionStatus", "unknown"),
            "selected_usable_label_rows": summary.get("selectedUsableLabelRows", 0),
            "readiness_gate_recommended": summary.get("readinessGateRecommended", False),
            "ready_csv_count": summary.get("readyCsvCount", 0),
            "partial_csv_count": summary.get("partialCsvCount", 0),
            "blank_template_csv_count": summary.get("blankTemplateCsvCount", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "benchmark_label_cycle":
        result = {
            "cycle_status": summary.get("cycleStatus", "unknown"),
            "completion_status": summary.get("completionStatus", "unknown"),
            "preflight_status": summary.get("preflightStatus", "unknown"),
            "readiness_status": summary.get("readinessStatus", "unknown"),
            "expectation_status": summary.get("expectationStatus", "unknown"),
            "usable_labeled_rows": summary.get("usableLabeledRows", 0),
            "invalid_label_rows": summary.get("invalidLabelRows", 0),
            "human_action_required": summary.get("humanActionRequired", True),
            "labels_assigned_by_this_tool": summary.get("labelsAssignedByThisTool", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "autonomous_branch_decision_report":
        result = {
            "selected_branch": summary.get("selectedBranch", ""),
            "readiness_classification": summary.get("readinessClassification", "unknown"),
            "operator_rpc_status": summary.get("operatorRpcStatus", "unknown"),
            "benchmark_priority_queue_rows": summary.get("benchmarkPriorityQueueRows", 0),
            "benchmark_label_worksheet_rows": summary.get("benchmarkLabelWorksheetRows", 0),
            "benchmark_label_action_pack_present": summary.get("benchmarkLabelActionPackPresent", False),
            "benchmark_label_csv_preflight_status": summary.get("benchmarkLabelCsvPreflightStatus", "unknown"),
            "benchmark_label_expectation_status": summary.get("benchmarkLabelExpectationStatus", "unknown"),
            "benchmark_usable_labeled_rows": summary.get("benchmarkUsableLabeledRows", 0),
            "ui_offline_missing_runtime_asset_count": summary.get("uiOfflineMissingRuntimeAssetCount", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "event_forensic_performance_audit":
        result = {
            "run_count": summary.get("runCount", 0),
            "slow_run_count_over_120s": summary.get("slowRunCountOver120s", 0),
            "funding_rpc_blocked_run_count": summary.get("fundingRpcBlockedRunCount", 0),
            "truncated_run_count": summary.get("truncatedRunCount", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "event_forensic_performance_rfc":
        result = {
            "proposal_count": summary.get("proposalCount", 0),
            "source_run_count": summary.get("sourceRunCount", 0),
            "implementation_approved": summary.get("implementationApproved", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "event_forensic_trade_collection_profile":
        result = {
            "run_count": summary.get("runCount", 0),
            "truncated_run_count": summary.get("truncatedRunCount", 0),
            "slow_collection_run_count_over_30s": summary.get("slowCollectionRunCountOver30s", 0),
            "single_market_sibling_context_run_count": summary.get("singleMarketSiblingContextRunCount", 0),
            "max_collect_event_trades_seconds": summary.get("maxCollectEventTradesSeconds", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "event_forensic_perf001_progress_spec":
        result = {
            "source_run_count": summary.get("sourceRunCount", 0),
            "source_truncated_run_count": summary.get("sourceTruncatedRunCount", 0),
            "implementation_priority": summary.get("implementationPriority", ""),
            "proposed_field_count": summary.get("proposedFieldCount", 0),
            "implementation_approved": summary.get("implementationApproved", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "event_forensic_perf001_implementation_report":
        behavior = payload.get("behaviorBoundary") if isinstance(payload.get("behaviorBoundary"), Mapping) else {}
        result = {
            "implementation_scope": payload.get("implementationScope", ""),
            "persisted_performance_fields_added": summary.get("persistedPerformanceFieldsAdded", False),
            "live_progress_metadata_added": summary.get("liveProgressMetadataAdded", False),
            "ui_status_metrics_added": summary.get("uiStatusMetricsAdded", False),
            "model_behavior_changed": behavior.get("modelBehaviorChanged", summary.get("modelBehaviorChanged", False)),
            "scoring_changed": behavior.get("scoringChanged", False),
            "gates_changed": behavior.get("gatesChanged", False),
        }
    elif kind == "event_forensic_scope_semantics_audit":
        result = {
            "run_count": summary.get("runCount", 0),
            "single_market_with_sibling_context_count": summary.get("singleMarketWithSiblingContextCount", 0),
            "truncated_event_collection_count": summary.get("truncatedEventCollectionCount", 0),
            "missing_scope_note_count": summary.get("missingScopeNoteCount", 0),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "archive_visibility_doc_drift_audit":
        result = {
            "check_count": summary.get("checkCount", 0),
            "contract_check_count": summary.get("contractCheckCount", 0),
            "drift_observed_count": summary.get("driftObservedCount", 0),
            "stale_archive_hard_hide_phrase_count": summary.get("staleArchiveHardHidePhraseCount", 0),
            "docs_require_visibility_reconciliation": summary.get("docsRequireVisibilityReconciliation", False),
            "archive_visibility_changed": summary.get("archiveVisibilityChanged", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "offline_timeline_coverage_audit":
        result = {
            "coverage_status": summary.get("coverageStatus", "unknown"),
            "existing_timeline_file_count": summary.get("existingTimelineFileCount", 0),
            "timeline_row_count": summary.get("timelineRowCount", 0),
            "review_artifact_count": summary.get("reviewArtifactCount", 0),
            "review_rows_inspected": summary.get("reviewRowsInspected", 0),
            "offline_timeline_matched_yes_count": summary.get("offlineTimelineMatchedYesCount", 0),
            "public_knowledge_at_present_count": summary.get("publicKnowledgeAtPresentCount", 0),
            "timeline_data_changed": summary.get("timelineDataChanged", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "offline_timeline_template_pack":
        result = {
            "source_coverage_status": summary.get("sourceCoverageStatus", "unknown"),
            "template_field_count": summary.get("templateFieldCount", 0),
            "template_rows_pre_filled": summary.get("templateRowsPreFilled", 0),
            "human_curation_required": summary.get("humanCurationRequired", True),
            "timeline_data_changed": summary.get("timelineDataChanged", False),
            "external_feeds_added": summary.get("externalFeedsAdded", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "offline_timeline_csv_validation":
        result = {
            "validation_status": summary.get("validationStatus", "unknown"),
            "row_count": summary.get("rowCount", 0),
            "valid_approved_row_count": summary.get("validApprovedRowCount", 0),
            "invalid_row_count": summary.get("invalidRowCount", 0),
            "missing_required_column_count": summary.get("missingRequiredColumnCount", 0),
            "runtime_data_changed": summary.get("runtimeDataChanged", False),
            "timeline_data_changed": summary.get("timelineDataChanged", False),
            "external_feeds_added": summary.get("externalFeedsAdded", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "ui_runtime_dependency_audit":
        result = {
            "file_count": summary.get("fileCount", 0),
            "runtime_required_dependency_count": summary.get("runtimeRequiredDependencyCount", 0),
            "offline_risk": summary.get("offlineRisk", "unknown"),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "ui_offline_readiness_plan":
        result = {
            "offline_risk": summary.get("offlineRisk", "unknown"),
            "runtime_required_dependency_count": summary.get("runtimeRequiredDependencyCount", 0),
            "plan_step_count": summary.get("planStepCount", 0),
            "implementation_approved": summary.get("implementationApproved", False),
            "ui_runtime_changed": summary.get("uiRuntimeChanged", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "ui_offline_asset_manifest":
        result = {
            "offline_risk": summary.get("offlineRisk", "unknown"),
            "runtime_required_dependency_count": summary.get("runtimeRequiredDependencyCount", 0),
            "unique_runtime_asset_count": summary.get("uniqueRuntimeAssetCount", 0),
            "missing_runtime_asset_count": summary.get("missingRuntimeAssetCount", 0),
            "analyst_navigation_link_count": summary.get("analystNavigationLinkCount", 0),
            "implementation_approved": summary.get("implementationApproved", False),
            "ui_runtime_changed": summary.get("uiRuntimeChanged", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "ui_offline_implementation_preflight":
        result = {
            "preflight_status": summary.get("preflightStatus", "unknown"),
            "offline_risk": summary.get("offlineRisk", "unknown"),
            "runtime_required_dependency_count": summary.get("runtimeRequiredDependencyCount", 0),
            "unique_runtime_asset_count": summary.get("uniqueRuntimeAssetCount", 0),
            "missing_runtime_asset_count": summary.get("missingRuntimeAssetCount", 0),
            "approval_required_before_runtime_change": summary.get("approvalRequiredBeforeRuntimeChange", True),
            "implementation_approved": summary.get("implementationApproved", False),
            "ui_runtime_changed": summary.get("uiRuntimeChanged", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "direct_script_import_audit":
        result = {
            "tool_file_count": summary.get("toolFileCount", 0),
            "repo_root_import_tool_count": summary.get("repoRootImportToolCount", 0),
            "guarded_repo_root_import_tool_count": summary.get("guardedRepoRootImportToolCount", 0),
            "missing_guard_tool_count": summary.get("missingGuardToolCount", 0),
            "direct_run_risk_status": summary.get("directRunRiskStatus", "unknown"),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "direct_script_cli_smoke_audit":
        result = {
            "argparse_cli_candidate_count": summary.get("argparseCliCandidateCount", 0),
            "help_ok_count": summary.get("helpOkCount", 0),
            "help_failure_count": summary.get("helpFailureCount", 0),
            "help_timeout_count": summary.get("helpTimeoutCount", 0),
            "direct_cli_risk_status": summary.get("directCliRiskStatus", "unknown"),
            "network_calls_intended": summary.get("networkCallsIntended", False),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "test_coverage_inventory_audit":
        result = {
            "test_file_count": summary.get("testFileCount", 0),
            "app_module_count": summary.get("appModuleCount", 0),
            "app_module_with_direct_test_reference_count": summary.get("appModuleWithDirectTestReferenceCount", 0),
            "app_module_without_direct_test_reference_count": summary.get("appModuleWithoutDirectTestReferenceCount", 0),
            "high_priority_app_module_without_direct_test_reference_count": summary.get(
                "highPriorityAppModuleWithoutDirectTestReferenceCount", 0
            ),
            "tool_module_count": summary.get("toolModuleCount", 0),
            "tool_module_with_direct_test_reference_count": summary.get("toolModuleWithDirectTestReferenceCount", 0),
            "coverage_inventory_status": summary.get("coverageInventoryStatus", "unknown"),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "autonomous_progress_chain":
        result = {
            "benchmark_rows": summary.get("benchmarkRows", 0),
            "performance_runs_inspected": summary.get("performanceRunsInspected", 0),
            "archive_doc_drift_observed": summary.get("archiveDocDriftObserved", 0),
            "ui_offline_risk": summary.get("uiOfflineRisk", "unknown"),
            "ui_offline_manifest_asset_count": summary.get("uiOfflineManifestAssetCount", 0),
            "readiness_classification": summary.get("readinessClassification", "unknown"),
            "model_behavior_changed": summary.get("modelBehaviorChanged", False),
        }
    elif kind == "autonomous_change_log":
        text = path.read_text(encoding="utf-8", errors="replace")
        result = {
            "line_count": len(text.splitlines()),
            "preserved_invariants_section": "## Preserved Invariants" in text,
            "current_state_section": "## Current State" in text,
            "model_behavior_changed": False,
        }
    return result


def _entry(path: Path, kind: str) -> dict[str, Any]:
    markdown = path.with_suffix(".md")
    return {
        "kind": kind,
        "path": str(path),
        "markdown_path": str(markdown) if markdown.exists() else str(path) if path.suffix == ".md" else "",
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        "summary": _summary_for_json(path, kind) if path.suffix == ".json" else {},
    }


def _attach_related_diagnostics(entries: list[dict[str, Any]], latest_by_kind: Mapping[str, str]) -> None:
    for entry in entries:
        related = []
        for kind in RELATED_KIND_MAP.get(str(entry.get("kind") or ""), ()):
            path = str(latest_by_kind.get(kind) or "")
            if not path or path == entry.get("path"):
                continue
            related.append({"kind": kind, "path": path})
        entry["related_diagnostics"] = related


def build_review_output_index(limit_per_kind: int = 5) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    by_kind: dict[str, int] = {}
    for kind, (directory, pattern) in SEARCH_DIRS.items():
        paths = _latest_files(directory, pattern, limit_per_kind)
        by_kind[kind] = len(paths)
        entries.extend(_entry(path, kind) for path in paths)
    entries.sort(key=lambda item: item.get("modified_at", ""), reverse=True)
    latest_by_kind = {
        kind: next((entry["path"] for entry in entries if entry["kind"] == kind), "")
        for kind in SEARCH_DIRS
    }
    _attach_related_diagnostics(entries, latest_by_kind)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "entry_count": len(entries),
            "kind_counts": by_kind,
            "latest_by_kind": latest_by_kind,
            "related_reference_count": sum(len(entry.get("related_diagnostics") or []) for entry in entries),
        },
        "entries": entries,
        "limitations": [
            "This is a local index of generated review artifacts only.",
            "It does not modify historical outputs.",
            "It does not run validation or change model behavior.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Review Output Index",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Entries: {summary.get('entry_count', 0)}",
        "",
        "## Latest By Kind",
    ]
    for kind, path in (summary.get("latest_by_kind") or {}).items():
        lines.append(f"- {kind}: {path or 'none'}")
    lines.extend(["", "## Entries"])
    for entry in payload.get("entries") or []:
        lines.append(f"- `{entry.get('kind', '')}`: {entry.get('path', '')}")
        if entry.get("summary"):
            lines.append(f"  - summary: {entry.get('summary')}")
        related = entry.get("related_diagnostics") if isinstance(entry.get("related_diagnostics"), list) else []
        if related:
            lines.append("  - related diagnostics:")
            for item in related[:8]:
                if isinstance(item, Mapping):
                    lines.append(f"    - {item.get('kind', '')}: {item.get('path', '')}")
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved_output_dir = _resolve(output_dir) or output_dir
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved_output_dir / f"review_output_index_{stamp}.json"
    markdown_path = resolved_output_dir / f"review_output_index_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index latest local review outputs.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit-per-kind", type=int, default=5)
    args = parser.parse_args(argv)
    payload = build_review_output_index(limit_per_kind=args.limit_per_kind)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Review output index JSON: {outputs['json_path']}")
    print(f"Review output index markdown: {outputs['markdown_path']}")
    print(f"Entries: {payload.get('summary', {}).get('entry_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
