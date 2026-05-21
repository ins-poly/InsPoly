from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("implementation_boundaries")

ALLOWED_CATEGORIES = {
    "safe_reporting_fix",
    "safe_schema_propagation_fix",
    "safe_navigation_or_index_fix",
    "safe_analyst_explanation_fix",
    "diagnostic_only_no_code_change",
    "rfc_only_model_behavior_change",
    "blocked_by_rpc",
    "reject_or_defer",
}

FIELD_CLASSIFICATION = {
    "hard_evidence_sources": "safe_schema_propagation_fix",
    "composition": "safe_reporting_fix",
    "gate_branch": "safe_reporting_fix",
    "gate_type": "safe_reporting_fix",
    "suppressors": "safe_analyst_explanation_fix",
    "wallet": "safe_navigation_or_index_fix",
    "market": "safe_navigation_or_index_fix",
    "condition_id": "safe_navigation_or_index_fix",
    "trade_id": "safe_navigation_or_index_fix",
}

FIELD_PATTERN_MAP = {
    "hard_evidence_sources": "no_independent_hard_evidence",
    "composition": "gate_trace_missing",
    "gate_branch": "gate_trace_missing",
    "gate_type": "gate_trace_missing",
    "suppressors": "high_volume_public_user",
    "wallet": "funding_unknown",
    "market": "retrospective_only",
    "condition_id": "retrospective_only",
    "trade_id": "funding_unknown",
}

SAFE_CATEGORIES = {
    "safe_reporting_fix",
    "safe_schema_propagation_fix",
    "safe_navigation_or_index_fix",
    "safe_analyst_explanation_fix",
}


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _latest_file(directory: Path, pattern: str) -> Path | None:
    root = _resolve(directory) or directory
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


def _summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("summary")
    return value if isinstance(value, Mapping) else {}


def _bool_for_category(category: str) -> bool:
    return category in SAFE_CATEGORIES


def discover_input_paths() -> dict[str, Path | None]:
    return {
        "source_schema_repair_plan": _latest_file(DEFAULT_OUTPUT_DIR.parent / "source_schema_repair_outputs", "source_schema_repair_plan_*.json"),
        "candidate_recall_diagnostic": _latest_file(DEFAULT_OUTPUT_DIR.parent / "candidate_recall_outputs", "candidate_recall_diagnostic_*.json"),
        "false_positive_library": _latest_file(DEFAULT_OUTPUT_DIR.parent / "false_positive_library", "false_positive_pattern_library_*.json"),
        "review_output_index": _latest_file(DEFAULT_OUTPUT_DIR.parent / "review_index_outputs", "review_output_index_*.json"),
        "strategic_next_action": _latest_file(DEFAULT_OUTPUT_DIR.parent / "strategic_backlog_outputs", "strategic_next_action_*.json"),
        "unique_review_packets": _latest_file(DEFAULT_OUTPUT_DIR.parent / "review_packets", "unique_review_packets_*.json"),
        "analyst_handoff_bundle": _latest_file(DEFAULT_OUTPUT_DIR.parent / "analyst_review_bundles", "analyst_review_bundle_*.json"),
        "readiness": _latest_file(DEFAULT_OUTPUT_DIR.parent / "validation_corpus_outputs", "gate_decision_readiness_*.json"),
        "autonomous_next_action": _latest_file(DEFAULT_OUTPUT_DIR.parent / "validation_corpus_outputs", "autonomous_next_action_*.json"),
        "operator_rpc_package": _latest_file(
            DEFAULT_OUTPUT_DIR.parent / "validation_corpus_outputs",
            "operator_rpc_capacity_recovery_package_*.json",
        ),
    }


def _field_issue(index: int, action: Mapping[str, Any], source_artifact: str) -> dict[str, Any]:
    field = str(action.get("field") or "unknown")
    category = FIELD_CLASSIFICATION.get(field, "diagnostic_only_no_code_change")
    safe = _bool_for_category(category)
    return {
        "issueId": f"SCHEMA-{index:03d}",
        "sourceArtifact": source_artifact,
        "issueSummary": f"`{field}` has {action.get('combined_missing_count', 0)} combined missing observations.",
        "affectedFields": [field],
        "affectedToolsOrOutputs": [
            "source_schema_repair_outputs",
            "review_packets",
            "review_index_outputs",
            "analyst_review_bundles",
        ],
        "classification": category,
        "whyThisMattersForInsiderStyleDetection": (
            "Analysts need this field to understand why a wallet or trade was selected, whether accepted "
            "hard evidence exists, and whether the case is live-detectable or only retrospective review material."
        ),
        "whyThisDoesNotOrDoesChangeModelBehavior": (
            "Safe work is limited to displaying or propagating already-saved fields. It does not rescore, "
            "reroute, downgrade, or alter eligibility."
        ),
        "safeImplementationAllowed": safe,
        "requiresHumanApproval": False,
        "blockedByRpc": False,
        "recommendedAction": action.get("safe_next_check", "Keep as diagnostic-only until a reporting repair is identified."),
        "acceptanceCriteria": [
            "Already-saved fields are shown or indexed when present.",
            "Missing fields are reported as review limitations, not model defects.",
            "No historical artifact is rewritten.",
        ],
        "testsRequired": [
            "python3 -m py_compile tools/implementation_boundary_report.py tools/review_output_index.py",
            "python3 -m unittest tests.test_implementation_boundary_report tests.test_review_output_index",
        ],
        "stopConditions": [
            "Stop if the fix would change scoring, gates, HER routing, funding eligibility, or production labels.",
            "Stop if legacy/cache-only rows would be overclaimed as fresh evidence.",
        ],
    }


def _false_positive_issue(index: int, pattern: Mapping[str, Any], source_artifact: str) -> dict[str, Any]:
    key = str(pattern.get("pattern_key") or "unknown")
    return {
        "issueId": f"FP-{index:03d}",
        "sourceArtifact": source_artifact,
        "issueSummary": f"False-positive pattern `{key}` observed {pattern.get('observed_count', 0)} times.",
        "affectedFields": ["why_this_may_be_false_positive", "suppressors", "analyst_playbook"],
        "affectedToolsOrOutputs": ["false_positive_library", "review_packets", "analyst_review_bundles"],
        "classification": "safe_analyst_explanation_fix",
        "whyThisMattersForInsiderStyleDetection": (
            "Pattern explanations help analysts separate suspicious structure from public power-user, "
            "near-certainty, stale, or evidence-thin cases before escalation."
        ),
        "whyThisDoesNotOrDoesChangeModelBehavior": (
            "The pattern stays advisory. It cannot suppress, downgrade, rescore, or alter any production label."
        ),
        "safeImplementationAllowed": True,
        "requiresHumanApproval": False,
        "blockedByRpc": False,
        "recommendedAction": "Expose the pattern's analyst questions and forbidden-use warnings in boundary/crosswalk/index outputs.",
        "acceptanceCriteria": [
            "Pattern remains analyst-facing only.",
            "`automatic_action_allowed` stays false.",
            "No scorer or gate imports this library.",
        ],
        "testsRequired": [
            "python3 -m unittest tests.test_false_positive_pattern_library tests.test_implementation_boundary_report",
        ],
        "stopConditions": [
            "Stop if this becomes automatic suppression or production priority logic.",
            "Stop if the output suggests false-positive patterns are precision proof.",
        ],
    }


def _fixed_issue(
    *,
    issue_id: str,
    source_artifact: str,
    summary: str,
    fields: Sequence[str],
    outputs: Sequence[str],
    classification: str,
    matters: str,
    behavior: str,
    recommended: str,
    blocked_by_rpc: bool = False,
    requires_approval: bool = False,
) -> dict[str, Any]:
    if classification not in ALLOWED_CATEGORIES:
        raise ValueError(f"Unsupported implementation boundary category: {classification}")
    safe = _bool_for_category(classification)
    return {
        "issueId": issue_id,
        "sourceArtifact": source_artifact,
        "issueSummary": summary,
        "affectedFields": list(fields),
        "affectedToolsOrOutputs": list(outputs),
        "classification": classification,
        "whyThisMattersForInsiderStyleDetection": matters,
        "whyThisDoesNotOrDoesChangeModelBehavior": behavior,
        "safeImplementationAllowed": safe,
        "requiresHumanApproval": requires_approval,
        "blockedByRpc": blocked_by_rpc,
        "recommendedAction": recommended,
        "acceptanceCriteria": [
            "Classification is explicit.",
            "Cache-only/stale evidence is not overclaimed.",
            "No production detector behavior changes.",
        ],
        "testsRequired": ["python3 -m unittest tests.test_implementation_boundary_report"],
        "stopConditions": [
            "Stop if implementation would require changing scoring, gates, routing, eligibility, thresholds, credentials, or RPC URLs.",
        ],
    }


def build_boundary_report(
    *,
    source_schema: Mapping[str, Any] | None = None,
    candidate_recall: Mapping[str, Any] | None = None,
    false_positive: Mapping[str, Any] | None = None,
    review_index: Mapping[str, Any] | None = None,
    strategic_next_action: Mapping[str, Any] | None = None,
    readiness: Mapping[str, Any] | None = None,
    operator_package: Mapping[str, Any] | None = None,
    input_paths: Mapping[str, Path | None] | None = None,
) -> dict[str, Any]:
    paths = input_paths or {}
    source_schema = source_schema or {}
    candidate_recall = candidate_recall or {}
    false_positive = false_positive or {}
    review_index = review_index or {}
    strategic_next_action = strategic_next_action or {}
    readiness = readiness or {}
    operator_package = operator_package or {}
    issues: list[dict[str, Any]] = []

    source_artifact = str(paths.get("source_schema_repair_plan") or "")
    for index, action in enumerate(source_schema.get("field_actions") or [], start=1):
        if isinstance(action, Mapping):
            issues.append(_field_issue(index, action, source_artifact))

    fp_artifact = str(paths.get("false_positive_library") or "")
    for index, pattern in enumerate((false_positive.get("patterns") or [])[:8], start=1):
        if isinstance(pattern, Mapping):
            issues.append(_false_positive_issue(index, pattern, fp_artifact))

    recall_artifact = str(paths.get("candidate_recall_diagnostic") or "")
    recall_interpretation = str(candidate_recall.get("diagnostic_interpretation") or "unknown")
    issues.append(
        _fixed_issue(
            issue_id="RECALL-001",
            source_artifact=recall_artifact,
            summary=f"Candidate recall diagnostic is `{recall_interpretation}`.",
            fields=["near_miss_visibility", "candidate_admission_funnel"],
            outputs=["candidate_recall_outputs"],
            classification="diagnostic_only_no_code_change",
            matters="Saved-output recall diagnostics prevent accidental broadening when no concrete near-miss opportunity is visible.",
            behavior="No routing or threshold change is justified by this diagnostic.",
            recommended="Keep recall as diagnostic-only until fresh funnel evidence exists.",
        )
    )
    near_miss = candidate_recall.get("near_miss_visibility") if isinstance(candidate_recall.get("near_miss_visibility"), Mapping) else {}
    if int(near_miss.get("funnel_file_count") or 0) == 0 or near_miss.get("saved_review_packet_limitations"):
        issues.append(
            _fixed_issue(
                issue_id="RPC-001",
                source_artifact=recall_artifact,
                summary="Fresh recall and funding interpretation remain limited by cache-only/RPC-blocked evidence.",
                fields=["funding_unknown_packets", "gate_trace_missing_packets", "live_detectable_unknown_packets"],
                outputs=["candidate_recall_outputs", "validation_corpus_outputs"],
                classification="blocked_by_rpc",
                matters="Funding trace availability is needed before using recall or funding quality as gate-decision evidence.",
                behavior="This cannot be fixed by detector code; it requires operator RPC capacity and bounded validation.",
                recommended="Wait for operator-approved RPC capacity, then run bounded validation; do not rerun large corpus now.",
                blocked_by_rpc=True,
            )
        )

    readiness_classification = str(readiness.get("readinessClassification") or readiness.get("classification") or "")
    if readiness_classification == "not_ready_corpus_too_cache_only":
        issues.append(
            _fixed_issue(
                issue_id="RPC-002",
                source_artifact=str(paths.get("readiness") or ""),
                summary="Readiness remains `not_ready_corpus_too_cache_only`.",
                fields=["readinessClassification", "funding_enabled_targets", "cache_only_targets"],
                outputs=["validation_corpus_outputs", "strategic_backlog_outputs"],
                classification="blocked_by_rpc",
                matters="Strong Risk/HER gate review needs fresh trace-enabled rows, not only saved-field screens.",
                behavior="This blocks model review but does not imply a scanner defect.",
                recommended="Do not run Strong Risk/HER production review until bounded fresh validation clears the blocker.",
                blocked_by_rpc=True,
            )
        )

    decision = str(strategic_next_action.get("decision") or "")
    if decision == "stop_human_approval_required":
        issues.append(
            _fixed_issue(
                issue_id="RFC-001",
                source_artifact=str(paths.get("strategic_next_action") or ""),
                summary="Further detector behavior work requires human approval or fresh RPC validation.",
                fields=["ready_to_copy_codex_prompt", "decision"],
                outputs=["strategic_backlog_outputs", "rfcs"],
                classification="rfc_only_model_behavior_change",
                matters="A human should approve any detector-behavior RFC after readiness passes.",
                behavior="Production changes would alter model behavior and are outside this task.",
                recommended="Keep model/gate/scoring/HER/funding eligibility changes RFC-only.",
                requires_approval=True,
            )
        )

    issues.append(
        _fixed_issue(
            issue_id="DEFER-001",
            source_artifact=fp_artifact,
            summary="Automatic suppression or downgrading from false-positive patterns is explicitly deferred.",
            fields=["automatic_action_allowed", "forbidden_use"],
            outputs=["false_positive_library"],
            classification="reject_or_defer",
            matters="False-positive patterns are useful cautions, but automatic use could hide real suspicious structure.",
            behavior="Automatic suppression would change analyst-facing priority and production interpretation.",
            recommended="Use patterns only as analyst explanations unless Max approves a future RFC with fresh validation.",
            requires_approval=True,
        )
    )

    for issue in issues:
        if issue.get("classification") not in ALLOWED_CATEGORIES:
            raise ValueError(f"Unsupported issue classification: {issue.get('classification')}")
        if issue.get("classification") in {"rfc_only_model_behavior_change", "blocked_by_rpc", "reject_or_defer"}:
            issue["safeImplementationAllowed"] = False
        if issue.get("blockedByRpc"):
            issue["safeImplementationAllowed"] = False

    counts = Counter(str(issue.get("classification")) for issue in issues)
    safe_fix_count = sum(1 for issue in issues if issue.get("safeImplementationAllowed"))
    latest_index = _summary(review_index).get("latest_by_kind") if isinstance(_summary(review_index).get("latest_by_kind"), Mapping) else {}
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "issue_count": len(issues),
            "safe_fix_count": safe_fix_count,
            "category_counts": {category: counts.get(category, 0) for category in sorted(ALLOWED_CATEGORIES)},
            "readiness_classification": readiness_classification or "unknown",
            "strategic_decision": decision or "unknown",
            "operator_rpc_status": operator_package.get("configuration_status")
            or operator_package.get("operator_rpc_status")
            or "unknown",
            "review_index_latest_by_kind": dict(latest_index),
            "model_behavior_changed": False,
        },
        "issues": issues,
        "implemented_safe_fixes": [
            "Boundary and analyst-crosswalk artifacts generated from saved diagnostics.",
            "Review output index and Event Forensic review artifact surface can expose boundary/crosswalk artifacts.",
            "Analyst handoff bundle/manifest can include boundary/crosswalk/source-schema repair artifacts.",
        ],
        "invariants_preserved": [
            "_score_trade() unchanged",
            "Strong Risk gates unchanged",
            "scoring weights unchanged",
            "production severity labels unchanged",
            "Hard Evidence Review routing unchanged",
            "suspicious funding v2 unchanged",
            "old saved outputs not mutated",
        ],
        "input_paths": {key: str(value) if value else "" for key, value in paths.items()},
    }


def build_analyst_crosswalk(
    *,
    source_schema: Mapping[str, Any] | None = None,
    false_positive: Mapping[str, Any] | None = None,
    review_packets: Mapping[str, Any] | None = None,
    review_index: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_schema = source_schema or {}
    false_positive = false_positive or {}
    review_packets = review_packets or {}
    review_index = review_index or {}
    patterns = {
        str(pattern.get("pattern_key") or ""): pattern
        for pattern in false_positive.get("patterns") or []
        if isinstance(pattern, Mapping)
    }
    packet_summary = _summary(review_packets)
    latest_by_kind = _summary(review_index).get("latest_by_kind")
    latest_by_kind = latest_by_kind if isinstance(latest_by_kind, Mapping) else {}
    rows: list[dict[str, Any]] = []
    for index, action in enumerate(source_schema.get("field_actions") or [], start=1):
        if not isinstance(action, Mapping) or action.get("priority") != "high":
            continue
        field = str(action.get("field") or "unknown")
        pattern_key = FIELD_PATTERN_MAP.get(field, "no_independent_hard_evidence")
        pattern = patterns.get(pattern_key, {})
        rows.append(
            {
                "crosswalkId": f"CROSSWALK-{index:03d}",
                "schemaObservation": {
                    "field": field,
                    "combinedMissingCount": action.get("combined_missing_count", 0),
                    "sourceMissingCount": action.get("source_missing_count", 0),
                    "schemaMissingCount": action.get("schema_missing_count", 0),
                    "safeRepairType": action.get("safe_repair_type", ""),
                },
                "falsePositivePattern": {
                    "patternKey": pattern_key,
                    "label": pattern.get("label", pattern_key),
                    "observedCount": pattern.get("observed_count", 0),
                    "automaticActionAllowed": (
                        (pattern.get("analyst_playbook") or {}).get("automatic_action_allowed", False)
                        if isinstance(pattern.get("analyst_playbook"), Mapping)
                        else False
                    ),
                },
                "reviewPacketFields": _review_packet_fields_for(field),
                "analystQuestion": _analyst_question_for(field),
                "whyItMatters": _why_crosswalk_matters(field),
                "suggestedNextInspection": _next_inspection_for(field, latest_by_kind, packet_summary),
                "implementationStatus": "safe_reporting_boundary_exposed; production_scoring_unchanged",
            }
        )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "crosswalk_count": len(rows),
            "source": "latest local saved diagnostics",
            "model_behavior_changed": False,
        },
        "crosswalk": rows,
        "limitations": [
            "This crosswalk is analyst workflow guidance only.",
            "It does not rescore, reroute, suppress, downgrade, or change eligibility.",
            "Cache-only and retrospective-only evidence remains limited.",
        ],
    }


def _review_packet_fields_for(field: str) -> list[str]:
    return {
        "hard_evidence_sources": ["hard_evidence_sources", "has_independent_hard_evidence", "why_this_matters"],
        "composition": ["strong_risk_composition_class", "gate_family", "why_this_matters"],
        "gate_branch": ["strong_risk_exact_gate_branch", "gate_name", "source_navigation"],
        "gate_type": ["strong_risk_gate_type", "gate_family", "source_navigation"],
    }.get(field, [field, "source_navigation", "what_to_inspect_next"])


def _analyst_question_for(field: str) -> str:
    return {
        "hard_evidence_sources": "Does the packet carry accepted independent hard evidence, or only score/timing/repeated-win context?",
        "composition": "Which Strong Risk composition family explains review selection, and is it live-detectable or retrospective?",
        "gate_branch": "Can the analyst see the exact branch that put this row into Strong Risk review?",
        "gate_type": "Can the analyst distinguish structural, retrospective, threshold, and timing/repricing gate families?",
    }.get(field, "Is this field missing because it was absent upstream or because reporting/display normalization dropped it?")


def _why_crosswalk_matters(field: str) -> str:
    return {
        "hard_evidence_sources": "This is the clearest divider between insider-style hard evidence and high-score false positives.",
        "composition": "Composition tells whether the lead is structural, retrospective, timing-led, or legacy score-led.",
        "gate_branch": "Exact branch visibility prevents analysts from treating broad saved-field screens as gate-change proof.",
        "gate_type": "Gate type helps separate suspicious structure from retrospective correctness and score-threshold artifacts.",
    }.get(field, "Field availability makes packet review less ambiguous without changing detector behavior.")


def _next_inspection_for(field: str, latest_by_kind: Mapping[str, Any], packet_summary: Mapping[str, Any]) -> str:
    paths = [
        latest_by_kind.get("unique_review_packets"),
        latest_by_kind.get("source_schema_repair_plan"),
        latest_by_kind.get("false_positive_library"),
    ]
    paths = [str(path) for path in paths if path]
    packet_count = packet_summary.get("unique_packet_count", 0)
    return (
        f"Inspect the latest review packets ({packet_count} packets) and compare `{field}` against source/schema repair "
        f"observations. Relevant artifacts: {'; '.join(paths) if paths else 'latest local review artifacts'}."
    )


def render_boundary_markdown(payload: Mapping[str, Any]) -> str:
    summary = _summary(payload)
    lines = [
        "# Implementation Boundary",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Issues: {summary.get('issue_count', 0)}",
        f"- Safe fixes: {summary.get('safe_fix_count', 0)}",
        f"- Readiness: `{summary.get('readiness_classification', '')}`",
        f"- Strategic decision: `{summary.get('strategic_decision', '')}`",
        f"- Operator RPC status: `{summary.get('operator_rpc_status', '')}`",
        f"- Model behavior changed: {summary.get('model_behavior_changed', False)}",
        "",
        "## Issues By Category",
    ]
    for category, count in (summary.get("category_counts") or {}).items():
        lines.append(f"- {category}: {count}")
    lines.extend(["", "## Issues"])
    for issue in payload.get("issues") or []:
        lines.extend(
            [
                "",
                f"### {issue.get('issueId')} - {issue.get('classification')}",
                "",
                f"- Summary: {issue.get('issueSummary', '')}",
                f"- Source: {issue.get('sourceArtifact', '')}",
                f"- Affected fields: {issue.get('affectedFields', [])}",
                f"- Safe implementation allowed: {issue.get('safeImplementationAllowed', False)}",
                f"- Requires human approval: {issue.get('requiresHumanApproval', False)}",
                f"- Blocked by RPC: {issue.get('blockedByRpc', False)}",
                f"- Why it matters: {issue.get('whyThisMattersForInsiderStyleDetection', '')}",
                f"- Behavior boundary: {issue.get('whyThisDoesNotOrDoesChangeModelBehavior', '')}",
                f"- Recommended action: {issue.get('recommendedAction', '')}",
            ]
        )
    lines.extend(["", "## Implemented Safe Fixes"])
    for item in payload.get("implemented_safe_fixes") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Invariants Preserved"])
    for item in payload.get("invariants_preserved") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def render_crosswalk_markdown(payload: Mapping[str, Any]) -> str:
    summary = _summary(payload)
    lines = [
        "# Analyst Crosswalk",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Rows: {summary.get('crosswalk_count', 0)}",
        f"- Model behavior changed: {summary.get('model_behavior_changed', False)}",
        "",
        "## Crosswalk",
    ]
    rows = payload.get("crosswalk") if isinstance(payload.get("crosswalk"), list) else []
    if not rows:
        lines.append("- none")
    for row in rows:
        observation = row.get("schemaObservation") if isinstance(row.get("schemaObservation"), Mapping) else {}
        pattern = row.get("falsePositivePattern") if isinstance(row.get("falsePositivePattern"), Mapping) else {}
        lines.extend(
            [
                "",
                f"### {row.get('crosswalkId')} - {observation.get('field', '')}",
                "",
                f"- Missing observations: {observation.get('combinedMissingCount', 0)}",
                f"- False-positive pattern: `{pattern.get('patternKey', '')}` ({pattern.get('observedCount', 0)})",
                f"- Review packet fields: {row.get('reviewPacketFields', [])}",
                f"- Analyst question: {row.get('analystQuestion', '')}",
                f"- Why it matters: {row.get('whyItMatters', '')}",
                f"- Suggested next inspection: {row.get('suggestedNextInspection', '')}",
                f"- Implementation status: {row.get('implementationStatus', '')}",
            ]
        )
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(
    boundary: Mapping[str, Any],
    crosswalk: Mapping[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    boundary_json = resolved / "implementation_boundary_20260505.json"
    boundary_md = resolved / "implementation_boundary_20260505.md"
    crosswalk_json = resolved / "analyst_crosswalk_20260505.json"
    crosswalk_md = resolved / "analyst_crosswalk_20260505.md"
    boundary_json.write_text(json.dumps(dict(boundary), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    boundary_md.write_text(render_boundary_markdown(boundary), encoding="utf-8")
    crosswalk_json.write_text(json.dumps(dict(crosswalk), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    crosswalk_md.write_text(render_crosswalk_markdown(crosswalk), encoding="utf-8")
    return {
        "boundary_json": str(boundary_json),
        "boundary_markdown": str(boundary_md),
        "crosswalk_json": str(crosswalk_json),
        "crosswalk_markdown": str(crosswalk_md),
    }


def build_from_latest() -> tuple[dict[str, Any], dict[str, Any], dict[str, Path | None]]:
    paths = discover_input_paths()
    source_schema = _load_json(paths["source_schema_repair_plan"])
    candidate_recall = _load_json(paths["candidate_recall_diagnostic"])
    false_positive = _load_json(paths["false_positive_library"])
    review_index = _load_json(paths["review_output_index"])
    strategic = _load_json(paths["strategic_next_action"])
    review_packets = _load_json(paths["unique_review_packets"])
    readiness = _load_json(paths["readiness"])
    operator = _load_json(paths["operator_rpc_package"])
    boundary = build_boundary_report(
        source_schema=source_schema,
        candidate_recall=candidate_recall,
        false_positive=false_positive,
        review_index=review_index,
        strategic_next_action=strategic,
        readiness=readiness,
        operator_package=operator,
        input_paths=paths,
    )
    crosswalk = build_analyst_crosswalk(
        source_schema=source_schema,
        false_positive=false_positive,
        review_packets=review_packets,
        review_index=review_index,
    )
    return boundary, crosswalk, paths


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate implementation boundary and analyst crosswalk from local diagnostics.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    boundary, crosswalk, _ = build_from_latest()
    outputs = write_outputs(boundary, crosswalk, args.output_dir)
    summary = boundary.get("summary", {})
    print(f"Implementation boundary JSON: {outputs['boundary_json']}")
    print(f"Implementation boundary markdown: {outputs['boundary_markdown']}")
    print(f"Analyst crosswalk JSON: {outputs['crosswalk_json']}")
    print(f"Analyst crosswalk markdown: {outputs['crosswalk_markdown']}")
    print(f"Issues: {summary.get('issue_count', 0)}")
    print(f"Safe fixes: {summary.get('safe_fix_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
