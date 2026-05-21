from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("validation_corpus_outputs")
STRONG_RISK_DIAGNOSTIC_DIR = Path("strong_risk_diagnostic_outputs")
PROJECT_MEMORY_PATH = Path("PROJECT_MEMORY.md")

OUTPUT_SECTIONS = (
    "current_state",
    "blocking_issue",
    "decision",
    "recommended_next_task",
    "ready_to_copy_codex_prompt",
    "stop_conditions",
    "human_approval_required_for",
    "invariants_preserved",
    "evidence_paths",
    "confidence",
)

ALLOWED_DECISIONS = {
    "run_rpc_cache_reliability_path",
    "run_cache_only_regression_path",
    "run_fresh_trace_validation_path",
    "produce_unique_review_packets",
    "run_candidate_recall_diagnostic",
    "source_attribution_repair_path",
    "her_routing_repair_path",
    "strong_risk_gate_review_ready_rfc_only",
    "stop_human_approval_required",
}

CONSISTENT_REPORT_STATES = {"count_reporting_consistent", "consistent", ""}

OPERATOR_RPC_DECISION_TRACE_CLASSES = {
    "operator_rpc_configuration_required",
    "operator_rpc_auth_or_configuration_required",
    "public_rpc_lightweight_unavailable",
    "public_rpc_lightweight_timeout",
    "public_rpc_rate_limited",
    "public_rpc_lightweight_only",
    "public_rpc_trace_timeout",
    "public_rpc_trace_rate_limited",
    "public_rpc_trace_unavailable",
    "public_rpc_trace_chunk_bottleneck",
}

FORBIDDEN_PROMPT_PHRASES = (
    "improve everything",
    "optimize detection",
    "change model",
    "tune weights",
    "adjust gates",
    "lower thresholds",
    "use news",
    "use llm scoring",
    "change weights",
)

INVARIANTS = (
    "Do not edit `_score_trade()`.",
    "Leave Strong Risk gates unchanged.",
    "Leave scoring weights unchanged.",
    "Leave production severity labels unchanged.",
    "Do not broaden structural pre-admission.",
    "Do not reduce structural floors or notional thresholds.",
    "Leave suspicious funding v2 rules unchanged.",
    "Do not make `multi_hop_unknown` funding eligible without independent structural support.",
    "Do not make CEX proxy-only or bridge proxy-only evidence eligible.",
    "Leave Hard Evidence Review routing unchanged.",
    "Do not add scoring that relies on an LLM.",
    "Do not add news, journalism, intelligence feeds, or external signal ingestion.",
    "Do not hardcode private credentials.",
    "Do not mutate old saved outputs.",
    "Preserve legacy output loading and report normalization.",
    "Treat funding unavailable as `unknown`, not `none`.",
    "Treat dedupe as reporting-only; never drop production rows.",
    "Do not propose enabled production detector edits unless they are framed as a human-approved RFC and readiness thresholds pass.",
)

LATEST_READINESS_CORPUS_COMMAND = (
    "LATEST_CORPUS=\"$(python3 -c 'from tools.gate_decision_readiness import "
    "_latest_corpus_output; p=_latest_corpus_output(); print(p if p else \"\")')\""
)


def _resolve(path: Path | str | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _latest_file(directory: Path, pattern: str, *, exclude: tuple[str, ...] = ()) -> Path | None:
    root = _resolve(directory) or directory
    if not root.exists():
        return None
    candidates = [
        path
        for path in root.glob(pattern)
        if all(token not in path.name for token in exclude)
    ]
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name)) if candidates else None


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _is_smoke_corpus_path(path: Path | None) -> bool:
    payload = _load_json(path)
    corpus_name = str(payload.get("corpus_name") or payload.get("corpusName") or "")
    return corpus_name.endswith("_smoke") or "_smoke" in corpus_name


def _latest_readiness_file(directory: Path) -> Path | None:
    root = _resolve(directory) or directory
    if not root.exists():
        return None
    candidates = sorted(
        root.glob("gate_decision_readiness_*.json"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for path in candidates:
        payload = _load_json(path)
        artifacts = payload.get("inputArtifacts") if isinstance(payload.get("inputArtifacts"), Mapping) else {}
        corpus_path = _resolve(str(artifacts.get("corpus_output") or "").strip() or None)
        if _is_smoke_corpus_path(corpus_path):
            continue
        return path
    return candidates[0] if candidates else None


def _latest_corpus_output(directory: Path) -> Path | None:
    root = _resolve(directory) or directory
    if not root.exists():
        return None
    candidates = sorted(
        [path for path in root.glob("post_v2_corpus_*.json") if "_audit_" not in path.name],
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for path in candidates:
        payload = _load_json(path)
        if payload.get("validationPolicy") == "network_probe":
            continue
        if _is_smoke_corpus_path(path):
            continue
        return path
    return candidates[0] if candidates else None


def _read_text(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _matching_markdown(json_path: Path | None, fallback_dir: Path, pattern: str) -> Path | None:
    if json_path:
        candidate = json_path.with_suffix(".md")
        if candidate.exists():
            return candidate
    return _latest_file(fallback_dir, pattern)


def _latest_paths(
    *,
    output_dir: Path,
    readiness_json_path: Path | None = None,
    readiness_md_path: Path | None = None,
    prewarm_path: Path | None = None,
    corpus_output_path: Path | None = None,
    consistency_path: Path | None = None,
    strong_risk_diagnostic_path: Path | None = None,
    project_memory_path: Path | None = None,
) -> dict[str, Path | None]:
    resolved_output_dir = _resolve(output_dir) or output_dir
    readiness_json = _resolve(readiness_json_path) or _latest_readiness_file(resolved_output_dir)
    return {
        "gate_decision_readiness_json": readiness_json,
        "gate_decision_readiness_md": _resolve(readiness_md_path)
        or _matching_markdown(readiness_json, resolved_output_dir, "gate_decision_readiness_*.md"),
        "funding_cache_prewarm_json": _resolve(prewarm_path)
        or _latest_file(resolved_output_dir, "funding_cache_prewarm_*.json"),
        "trace_method_diagnostic_json": _latest_file(resolved_output_dir, "trace_method_diagnostic_*.json"),
        "post_v2_corpus_json": _resolve(corpus_output_path)
        or _latest_corpus_output(resolved_output_dir),
        "report_consistency_json": _resolve(consistency_path)
        or _latest_file(resolved_output_dir, "report_consistency_*.json"),
        "strong_risk_gate_diagnostic_json": _resolve(strong_risk_diagnostic_path)
        or _latest_file(STRONG_RISK_DIAGNOSTIC_DIR, "strong_risk_gate_diagnostic_*.json"),
        "project_memory": _resolve(project_memory_path or PROJECT_MEMORY_PATH),
    }


def _readiness_classification(readiness: Mapping[str, Any]) -> str:
    for key in (
        "readinessClassification",
        "final_readiness_classification",
        "finalReadinessClassification",
        "finalClassification",
        "classification",
    ):
        value = str(readiness.get(key) or "").strip()
        if value:
            return value
    return ""


def _recommendation(readiness: Mapping[str, Any]) -> str:
    for key in ("recommendation", "finalRecommendation", "recommended_next_task"):
        value = str(readiness.get(key) or "").strip()
        if value:
            return value
    return ""


def _consistency_classification(
    readiness: Mapping[str, Any],
    consistency: Mapping[str, Any],
) -> str:
    if consistency:
        return str(consistency.get("classification") or "").strip()
    report = readiness.get("reportConsistency")
    if isinstance(report, Mapping):
        return str(report.get("classification") or "").strip()
    return ""


def _decision_for(
    *,
    readiness: Mapping[str, Any],
    consistency: Mapping[str, Any],
    prewarm: Mapping[str, Any],
    trace_method_diagnostic: Mapping[str, Any],
    missing_inputs: list[str],
) -> str:
    classification = _readiness_classification(readiness)
    recommendation = _recommendation(readiness)
    consistency_class = _consistency_classification(readiness, consistency)

    if "gate_decision_readiness_json" in missing_inputs or not classification:
        return "run_cache_only_regression_path"
    if consistency_class and consistency_class not in CONSISTENT_REPORT_STATES:
        return "run_cache_only_regression_path"
    if classification in {"not_ready_corpus_too_cache_only", "not_ready_public_rpc_bottleneck"} and _operator_rpc_decision_required(
        prewarm,
        trace_method_diagnostic,
    ):
        return "stop_human_approval_required"
    if classification == "not_ready_corpus_too_cache_only":
        return "run_rpc_cache_reliability_path"
    if classification == "not_ready_public_rpc_bottleneck":
        return "run_rpc_cache_reliability_path"
    if classification == "not_ready_corpus_too_narrow":
        return "run_fresh_trace_validation_path"
    if classification == "ready_no_gate_issue_observed":
        return "produce_unique_review_packets"
    if classification == "ready_for_strong_risk_gate_review":
        return "strong_risk_gate_review_ready_rfc_only"
    if classification == "source_attribution_repair_needed":
        return "source_attribution_repair_path"
    if classification == "hard_evidence_routing_repair_needed":
        return "her_routing_repair_path"
    if recommendation == "candidate_recall_diagnostic_needed":
        return "run_candidate_recall_diagnostic"
    return "run_cache_only_regression_path"


def _operator_rpc_decision_required(
    prewarm: Mapping[str, Any],
    trace_method_diagnostic: Mapping[str, Any],
) -> bool:
    trace_class = str(trace_method_diagnostic.get("classification") or "").strip()
    trace_next = str(trace_method_diagnostic.get("recommended_next_step") or "").strip()
    if trace_class in {"trace_method_path_available", "trace_method_path_available_with_endpoint_errors"} and _prewarm_failure_dominates(prewarm):
        return True
    if not trace_class and not trace_next:
        return False
    if trace_class not in OPERATOR_RPC_DECISION_TRACE_CLASSES and trace_next != "operator_rpc_configuration_or_capacity_decision":
        return False
    stop_reason = str(prewarm.get("stop_reason") or prewarm.get("stopReason") or "").strip()
    targets_left = _as_int(prewarm.get("targets_left_unprewarmed") or prewarm.get("targetsLeftUnprewarmed"))
    attempted = _as_int(
        prewarm.get("wallet_time_windows_attempted")
        or prewarm.get("traces_requested")
        or prewarm.get("tracesRequested")
    )
    failures = _as_int(prewarm.get("rpc_failures") or prewarm.get("rpcFailures") or prewarm.get("failures_observed"))
    if stop_reason in {"trace_timeout", "timeout"} or (targets_left > 0 and attempted <= 1):
        return True
    if (
        stop_reason == "max_total_traces"
        and targets_left > 0
        and attempted >= 12
        and failures >= max(3, attempted // 2)
    ):
        return True
    return False


def _prewarm_failure_dominates(prewarm: Mapping[str, Any]) -> bool:
    stop_reason = str(prewarm.get("stop_reason") or prewarm.get("stopReason") or "").strip()
    targets_left = _as_int(prewarm.get("targets_left_unprewarmed") or prewarm.get("targetsLeftUnprewarmed"))
    attempted = _as_int(
        prewarm.get("wallet_time_windows_attempted")
        or prewarm.get("traces_requested")
        or prewarm.get("tracesRequested")
    )
    failures = _as_int(prewarm.get("rpc_failures") or prewarm.get("rpcFailures") or prewarm.get("failures_observed"))
    outcomes = prewarm.get("trace_outcome_status_counts") or prewarm.get("traceOutcomeStatusCounts")
    if isinstance(outcomes, Mapping):
        failures = max(failures, _as_int(outcomes.get("failure")))
        attempted = max(
            attempted,
            sum(_as_int(value) for value in outcomes.values()),
        )
    if stop_reason not in {"max_total_traces", "trace_timeout", "timeout"}:
        return False
    if targets_left <= 0 or attempted < 12:
        return False
    return failures >= max(3, int(attempted * 0.6))


def _current_state(
    readiness: Mapping[str, Any],
    corpus: Mapping[str, Any],
    prewarm: Mapping[str, Any],
    trace_method_diagnostic: Mapping[str, Any],
    diagnostic: Mapping[str, Any],
    consistency: Mapping[str, Any],
    project_memory_text: str,
) -> dict[str, Any]:
    run = _dict(readiness.get("run"))
    config = _dict(readiness.get("corpusConfig"))
    trace = _dict(readiness.get("strongRiskGateTrace"))
    funding = _dict(readiness.get("funding"))
    return {
        "readiness_classification": _readiness_classification(readiness),
        "recommendation": _recommendation(readiness),
        "readiness_generated_at": readiness.get("generated_at", ""),
        "corpus_targets": {
            "total": config.get("totalTargets", corpus.get("total_targets", "")),
            "fresh_rerunnable": config.get("freshRerunnableTargets", ""),
            "archive": config.get("archiveTargets", ""),
            "target_family_distribution": config.get("targetFamilyDistribution", {}),
        },
        "completed_skipped_aborted": {
            "completed": run.get("completedTargets", corpus.get("completed_targets", "")),
            "skipped": run.get("skippedTargets", corpus.get("skipped_targets", "")),
            "aborted": run.get("abortedTargets", corpus.get("aborted_targets", "")),
        },
        "fresh_rerunnable_completed": run.get("completedFreshRerunnableTargets", ""),
        "funding_enabled_cache_only_blocked": {
            "funding_enabled": run.get("fundingEnabledTargets", corpus.get("funding_enabled_targets", "")),
            "cache_only": run.get("cacheOnlyTargets", corpus.get("cache_only_targets", "")),
            "funding_blocked": run.get("fundingBlockedTargets", corpus.get("funding_blocked_targets", "")),
        },
        "visible_rows": {
            "raw": run.get("rawVisibleRows", corpus.get("rawVisibleRows", "")),
            "unique": run.get("uniqueVisibleRows", corpus.get("uniqueVisibleRows", "")),
        },
        "strong_risk_rows": {
            "raw": run.get("rawStrongRiskRows", diagnostic.get("rawStrongRiskRows", corpus.get("rawStrongRiskRows", ""))),
            "unique": run.get("uniqueStrongRiskRows", diagnostic.get("uniqueStrongRiskRows", corpus.get("uniqueStrongRiskRows", ""))),
            "dedupe_ratio": run.get("strongRiskDedupeRatio", corpus.get("strongRiskDedupeRatio", "")),
        },
        "hard_evidence_review_rows": {
            "raw": run.get("rawHardEvidenceReviewRows", corpus.get("rawHardEvidenceReviewRows", "")),
            "unique": run.get("uniqueHardEvidenceReviewRows", corpus.get("uniqueHardEvidenceReviewRows", "")),
            "dedupe_ratio": run.get("hardEvidenceReviewDedupeRatio", corpus.get("hardEvidenceReviewDedupeRatio", "")),
        },
        "strong_risk_gate_trace_coverage": {
            "traced": trace.get(
                "strongRiskRowsWithGateTrace",
                diagnostic.get("strongRiskRowsWithGateTraceAvailable", ""),
            ),
            "raw": run.get("rawStrongRiskRows", diagnostic.get("rawStrongRiskRows", "")),
            "coverage": trace.get("strongRiskGateTraceCoverage", ""),
        },
        "fresh_unique_gate_leakage_candidates": readiness.get(
            "freshUniqueGateLeakageCandidates",
            diagnostic.get("freshUniqueGateLeakageCandidateRows", ""),
        ),
        "broad_saved_field_gate_leakage_candidates": readiness.get(
            "broadSavedFieldGateLeakageCandidates",
            diagnostic.get("potentialGateLeakageCandidateRows", ""),
        ),
        "her_invalid_condition_counts": readiness.get(
            "herInvalidConditionCounts",
            diagnostic.get("hardInvalidConditionCounts", {}),
        ),
        "report_consistency": _consistency_classification(readiness, consistency),
        "prewarm": {
            "funding_candidate_targets": funding.get("fundingCandidateTargets", prewarm.get("funding_candidate_targets", "")),
            "traces_requested": funding.get("tracesRequested", prewarm.get("wallet_time_windows_attempted", prewarm.get("traces_requested", ""))),
            "cache_hits": funding.get("cacheHits", prewarm.get("cache_hits_observed", prewarm.get("cache_hits", ""))),
            "cache_misses": funding.get("cacheMisses", prewarm.get("cache_misses_observed", prewarm.get("cache_misses", ""))),
            "cache_writes": funding.get("cacheWrites", prewarm.get("cache_writes", "")),
            "rpc_failures": funding.get("rpcFailures", prewarm.get("rpc_failures", "")),
            "rate_limits": funding.get("rateLimits", prewarm.get("rate_limits", "")),
            "targets_left_unprewarmed": funding.get("targetsLeftUnprewarmed", prewarm.get("targets_left_unprewarmed", "")),
            "trace_timeouts_observed": funding.get("traceTimeoutsObserved", prewarm.get("trace_timeouts_observed", "")),
            "max_trace_timeouts": funding.get("maxTraceTimeouts", prewarm.get("max_trace_timeouts", "")),
            "stop_reason": funding.get("stopReason", prewarm.get("stop_reason", "")),
            "coverage_by_target_family": funding.get(
                "prewarmCoverageByTargetFamily",
                prewarm.get("prewarm_coverage_by_target_family", {}),
            ),
        },
        "trace_method_diagnostic": {
            "classification": trace_method_diagnostic.get("classification", ""),
            "recommended_next_step": trace_method_diagnostic.get("recommended_next_step", ""),
            "endpoint_labels": trace_method_diagnostic.get("endpoint_labels", []),
            "method_summary": trace_method_diagnostic.get("method_summary", {}),
        },
        "latest_corpus_policy": corpus.get("validationPolicy", ""),
        "latest_corpus_network_probe_status": corpus.get("networkProbeStatus", ""),
        "project_memory_loaded": bool(project_memory_text),
        "project_memory_mentions_autonomous_next_action": "autonomous next-action" in project_memory_text.lower(),
    }


def _blocking_issue(decision: str, current_state: Mapping[str, Any], missing_inputs: list[str]) -> str:
    classification = str(current_state.get("readiness_classification") or "")
    consistency = str(current_state.get("report_consistency") or "")
    if missing_inputs and "gate_decision_readiness_json" in missing_inputs:
        return (
            "No gate-decision readiness JSON was available, so the next action is to regenerate "
            "the cache-only validation reports and rebuild readiness before interpreting evidence."
        )
    if consistency and consistency not in CONSISTENT_REPORT_STATES:
        return (
            f"Report consistency is `{consistency}`, so count hygiene must be repaired or regenerated "
            "before any validation conclusion is used."
        )
    if decision == "run_rpc_cache_reliability_path":
        return (
            f"Latest readiness is `{classification}`: the corpus is broad, but interpreted evidence is "
            "still cache-only or public-RPC constrained. The validation harness must reliably produce a "
            "final artifact or explicit terminal failure before gate-readiness evidence can be interpreted."
        )
    if decision == "stop_human_approval_required":
        return (
            "The bounded RPC/cache reliability path has already produced operator-blocked evidence: "
            "trace-method diagnostics and prewarm output point to RPC configuration/capacity rather than "
            "a model, gate, or validation-reporting code issue."
        )
    if decision == "run_fresh_trace_validation_path":
        return (
            "The corpus does not yet meet breadth/family/archive thresholds for a gate-decision basis."
        )
    if decision == "produce_unique_review_packets":
        return (
            "Readiness thresholds pass with no fresh unique gate issue observed; the next bounded work is "
            "human-readable unique-row evidence packet production."
        )
    if decision == "strong_risk_gate_review_ready_rfc_only":
        return (
            "Readiness thresholds pass and fresh unique trace-enabled rows show gate issues; the next work "
            "is an RFC-only review packet, not enabled production edits."
        )
    if decision == "source_attribution_repair_path":
        return (
            "Fresh rows show accepted hard-evidence source attribution missing from exported fields."
        )
    if decision == "her_routing_repair_path":
        return (
            "Fresh rows show violations of the accepted Hard Evidence Review routing contract."
        )
    if decision == "run_candidate_recall_diagnostic":
        return "Readiness points to a recall diagnostic before any production detector edits."
    return "Key validation reports are missing, stale, or inconsistent."


def _prewarm_budget_reached_with_artifacts(current_state: Mapping[str, Any]) -> bool:
    prewarm = _dict(current_state.get("prewarm"))
    return (
        str(prewarm.get("stop_reason") or "") == "max_total_traces"
        and _as_int(prewarm.get("traces_requested")) >= 12
        and _as_int(prewarm.get("cache_writes")) > 1
    )


def _recommended_task(decision: str, current_state: Mapping[str, Any] | None = None) -> str:
    current_state = current_state or {}
    if decision == "run_rpc_cache_reliability_path" and _prewarm_budget_reached_with_artifacts(current_state):
        return (
            "Advance from first-pass RPC reliability repair to a bounded family-balanced cache/prewarm "
            "coverage cycle, then rerun the 12-target smoke/readiness sequence and decide whether public "
            "RPC or remaining cache coverage still blocks broad fresh trace validation."
        )
    tasks = {
        "run_rpc_cache_reliability_path": (
            "Diagnose and repair validation RPC/cache reliability so the expanded corpus either finishes a "
            "bounded smoke run or writes an explicit terminal fallback/failure artifact, then regenerate "
            "readiness and the next action pack."
        ),
        "run_cache_only_regression_path": (
            "Regenerate missing or inconsistent cache-only validation reports, validate count consistency, "
            "and emit a fresh autonomous next-action pack."
        ),
        "run_fresh_trace_validation_path": (
            "Recover or expand fresh-rerunnable validation targets only from local metadata and repository "
            "artifacts, then rerun bounded readiness reporting."
        ),
        "produce_unique_review_packets": (
            "Produce unique-row review packets for the current ready corpus without altering production "
            "scoring or routing behavior."
        ),
        "run_candidate_recall_diagnostic": (
            "Run a read-only candidate recall diagnostic on the latest fresh corpus outputs."
        ),
        "source_attribution_repair_path": (
            "Repair schema/source propagation for accepted hard-evidence sources only, then rerun readiness."
        ),
        "her_routing_repair_path": (
            "Repair accepted Hard Evidence Review contract violations only, then rerun readiness."
        ),
        "strong_risk_gate_review_ready_rfc_only": (
            "Produce a human-approval RFC isolating fresh unique trace-enabled Strong Risk gate evidence."
        ),
        "stop_human_approval_required": (
            "Produce an operator RPC capacity and readiness recovery package, then stop validation until "
            "a new operator-approved RPC configuration is recorded."
        ),
    }
    return tasks[decision]


def _stop_conditions(decision: str) -> list[str]:
    common = [
        "Stop if the requested work would require editing `_score_trade()`, Strong Risk gates, scoring weights, production severity labels, suspicious funding v2 rules, or Hard Evidence Review routing.",
        "Stop if evidence is cache-only or stale but a conclusion would require fresh trace-enabled proof.",
        "Stop if a command would require private credentials, hardcoded endpoint URLs, unbounded network calls, or mutation of old saved outputs.",
        "Stop if report consistency is not `count_reporting_consistent` after regeneration.",
    ]
    if decision == "run_rpc_cache_reliability_path":
        return common + [
            "Stop after the 12-target smoke if public RPC stalls still dominate; classify the blocker instead of escalating to the full 48-target run.",
            "Stop if fallback cannot write either a final corpus artifact or an explicit terminal failure artifact.",
        ]
    if decision == "stop_human_approval_required":
        return common + [
            "Stop if no operator-approved RPC endpoint/configuration has been provided through existing env/config.",
            "Do not rerun the same bounded RPC/cache loop until the operator decision is recorded.",
            "Do not run the full 48-target validation from cache-only or stalled evidence.",
        ]
    if decision == "strong_risk_gate_review_ready_rfc_only":
        return common + [
            "Stop before enabling any production detector edit; the deliverable is an RFC and evidence packet only.",
        ]
    return common


def _human_approval_required(decision: str) -> list[str]:
    approvals = [
        "Any enabled production detector edit.",
        "Any private credential, paid RPC, or endpoint configuration decision.",
        "Any mutation, migration, deletion, or rewriting of old saved outputs.",
        "Any interpretation that upgrades cache-only or stale evidence into a gate-decision basis.",
    ]
    if decision == "strong_risk_gate_review_ready_rfc_only":
        approvals.append("Turning the RFC into enabled production code.")
    return approvals


def _status_lines(current_state: Mapping[str, Any]) -> list[str]:
    completed = _dict(current_state.get("completed_skipped_aborted"))
    funding = _dict(current_state.get("funding_enabled_cache_only_blocked"))
    visible = _dict(current_state.get("visible_rows"))
    strong = _dict(current_state.get("strong_risk_rows"))
    her = _dict(current_state.get("hard_evidence_review_rows"))
    trace = _dict(current_state.get("strong_risk_gate_trace_coverage"))
    corpus = _dict(current_state.get("corpus_targets"))
    prewarm = _dict(current_state.get("prewarm"))
    trace_method = _dict(current_state.get("trace_method_diagnostic"))
    return [
        f"- Readiness classification: `{current_state.get('readiness_classification', '') or 'missing'}`.",
        f"- Recommendation: `{current_state.get('recommendation', '') or 'missing'}`.",
        f"- Corpus targets: {corpus.get('total', '')} total / {corpus.get('fresh_rerunnable', '')} fresh-rerunnable / {corpus.get('archive', '')} archive.",
        f"- Completed/skipped/aborted: {completed.get('completed', '')}/{completed.get('skipped', '')}/{completed.get('aborted', '')}.",
        f"- Funding-enabled/cache-only/funding-blocked: {funding.get('funding_enabled', '')}/{funding.get('cache_only', '')}/{funding.get('funding_blocked', '')}.",
        f"- Visible rows: {visible.get('raw', '')} raw / {visible.get('unique', '')} unique.",
        f"- Strong Risk rows: {strong.get('raw', '')} raw / {strong.get('unique', '')} unique, dedupe ratio {strong.get('dedupe_ratio', '')}.",
        f"- Hard Evidence Review rows: {her.get('raw', '')} raw / {her.get('unique', '')} unique, dedupe ratio {her.get('dedupe_ratio', '')}.",
        f"- Strong Risk gate trace coverage: {trace.get('traced', '')}/{trace.get('raw', '')} ({trace.get('coverage', '')}).",
        f"- Fresh unique gate-leakage candidates: {current_state.get('fresh_unique_gate_leakage_candidates', '')}.",
        f"- Broad saved-field gate-leakage candidates: {current_state.get('broad_saved_field_gate_leakage_candidates', '')}.",
        f"- HER invalid conditions: {current_state.get('her_invalid_condition_counts', {})}.",
        f"- Prewarm: funding candidates {prewarm.get('funding_candidate_targets', '')}, traces requested {prewarm.get('traces_requested', '')}, cache hits/misses/writes {prewarm.get('cache_hits', '')}/{prewarm.get('cache_misses', '')}/{prewarm.get('cache_writes', '')}, RPC failures {prewarm.get('rpc_failures', '')}, trace timeouts {prewarm.get('trace_timeouts_observed', '')}/{prewarm.get('max_trace_timeouts', '')}, targets left unprewarmed {prewarm.get('targets_left_unprewarmed', '')}, stop reason `{prewarm.get('stop_reason', '')}`.",
        f"- Trace-method diagnostic: `{trace_method.get('classification', '') or 'missing'}`, next step `{trace_method.get('recommended_next_step', '') or 'missing'}`.",
    ]


def _files_to_inspect(decision: str, evidence_paths: Mapping[str, Any]) -> list[str]:
    base = [
        "AGENTS.md",
        "PROJECT_MEMORY.md",
        "validation_corpus/post_v2_validation_corpus.json",
        "tools/gate_decision_readiness.py",
        "tools/autonomous_next_action.py",
        str(evidence_paths.get("gate_decision_readiness_json") or ""),
        str(evidence_paths.get("gate_decision_readiness_md") or ""),
        str(evidence_paths.get("post_v2_corpus_json") or ""),
        str(evidence_paths.get("funding_cache_prewarm_json") or ""),
        str(evidence_paths.get("trace_method_diagnostic_json") or ""),
        str(evidence_paths.get("report_consistency_json") or ""),
        str(evidence_paths.get("strong_risk_gate_diagnostic_json") or ""),
    ]
    if decision == "run_rpc_cache_reliability_path":
        base.extend(
            [
                "tools/run_validation_corpus.py",
                "tools/prewarm_funding_cache.py",
                "tools/funding_resolver_healthcheck.py",
                "tools/network_funding_diagnostics.py",
                "tools/validate_report_consistency.py",
                "tools/corpus_provenance_drilldown.py",
                "tools/strong_risk_gate_diagnostic.py",
            ]
        )
    elif decision == "stop_human_approval_required":
        base.extend(
            [
                "tools/operator_rpc_recovery_package.py",
                "tools/trace_method_diagnostic.py",
                "tools/funding_resolver_healthcheck.py",
                "tools/prewarm_funding_cache.py",
                "tools/run_validation_corpus.py",
                ".inspoly_runtime.env",
            ]
        )
    elif decision == "run_fresh_trace_validation_path":
        base.extend(["tools/discover_validation_targets.py", "tools/run_validation_corpus.py"])
    elif decision == "source_attribution_repair_path":
        base.extend(["tools/model_behavior_audit.py", "tools/corpus_provenance_drilldown.py", "tools/strong_risk_gate_diagnostic.py"])
    elif decision == "her_routing_repair_path":
        base.extend(["tools/model_behavior_audit.py", "tools/corpus_provenance_drilldown.py"])
    return [item for item in dict.fromkeys(base) if item]


def _commands_for(decision: str) -> list[str]:
    if decision == "run_rpc_cache_reliability_path":
        return [
            "python3 tools/funding_resolver_healthcheck.py",
            "python3 tools/trace_method_diagnostic.py --timeout-seconds 90 --per-request-timeout-seconds 8",
            "python3 tools/run_validation_corpus.py --network-probe --max-targets 3 --timeout-seconds 300",
            "python3 tools/prewarm_funding_cache.py --corpus validation_corpus/post_v2_validation_corpus.json --max-targets 48 --max-total-traces 48 --max-trace-timeouts 3 --timeout-seconds 900",
            "python3 tools/run_validation_corpus.py --auto-policy --max-targets 12 --timeout-seconds 900",
            "python3 tools/run_validation_corpus.py --cache-only --max-targets 12 --timeout-seconds 900",
            LATEST_READINESS_CORPUS_COMMAND,
            "python3 tools/model_behavior_audit.py \"$LATEST_CORPUS\" --output-dir validation_corpus_outputs --output-prefix post_v2_corpus_audit",
            "python3 tools/validate_report_consistency.py --corpus-json \"$LATEST_CORPUS\"",
            "python3 tools/corpus_provenance_drilldown.py --corpus \"$LATEST_CORPUS\"",
            "LATEST_DRILLDOWN=\"$(ls -t validation_corpus_outputs/corpus_provenance_drilldown_*.json | head -n 1)\"",
            "python3 tools/strong_risk_gate_diagnostic.py --corpus \"$LATEST_CORPUS\" --drilldown \"$LATEST_DRILLDOWN\"",
            "LATEST_DIAGNOSTIC=\"$(ls -t strong_risk_diagnostic_outputs/strong_risk_gate_diagnostic_*.json | head -n 1)\"",
            "LATEST_CONSISTENCY=\"$(ls -t validation_corpus_outputs/report_consistency_*.json | head -n 1)\"",
            "LATEST_PREWARM=\"$(ls -t validation_corpus_outputs/funding_cache_prewarm_*.json | head -n 1)\"",
            "python3 tools/gate_decision_readiness.py --corpus-output \"$LATEST_CORPUS\" --drilldown \"$LATEST_DRILLDOWN\" --strong-risk-diagnostic \"$LATEST_DIAGNOSTIC\" --prewarm \"$LATEST_PREWARM\" --consistency \"$LATEST_CONSISTENCY\" --emit-next-action",
            "python3 tools/autonomous_next_action.py",
        ]
    if decision == "run_fresh_trace_validation_path":
        return [
            "python3 tools/discover_validation_targets.py",
            "python3 tools/run_validation_corpus.py --network-probe --max-targets 3 --timeout-seconds 300",
            "python3 tools/run_validation_corpus.py --auto-policy --max-targets 12 --timeout-seconds 900",
            "python3 tools/validate_report_consistency.py",
            "python3 tools/gate_decision_readiness.py --emit-next-action",
            "python3 tools/autonomous_next_action.py",
        ]
    if decision == "produce_unique_review_packets":
        return [
            LATEST_READINESS_CORPUS_COMMAND,
            "python3 tools/corpus_provenance_drilldown.py --corpus \"$LATEST_CORPUS\"",
            "python3 tools/strong_risk_gate_diagnostic.py --corpus \"$LATEST_CORPUS\"",
            "python3 tools/gate_decision_readiness.py --emit-next-action",
            "python3 tools/autonomous_next_action.py",
        ]
    if decision == "strong_risk_gate_review_ready_rfc_only":
        return [
            LATEST_READINESS_CORPUS_COMMAND,
            "python3 tools/corpus_provenance_drilldown.py --corpus \"$LATEST_CORPUS\"",
            "LATEST_DRILLDOWN=\"$(ls -t validation_corpus_outputs/corpus_provenance_drilldown_*.json | head -n 1)\"",
            "python3 tools/strong_risk_gate_diagnostic.py --corpus \"$LATEST_CORPUS\" --drilldown \"$LATEST_DRILLDOWN\"",
            "python3 tools/gate_decision_readiness.py --emit-next-action",
        ]
    if decision == "source_attribution_repair_path":
        return [
            LATEST_READINESS_CORPUS_COMMAND,
            "python3 tools/model_behavior_audit.py \"$LATEST_CORPUS\" --output-dir validation_corpus_outputs --output-prefix post_v2_corpus_audit",
            "python3 tools/corpus_provenance_drilldown.py --corpus \"$LATEST_CORPUS\"",
            "python3 tools/strong_risk_gate_diagnostic.py --corpus \"$LATEST_CORPUS\"",
            "python3 tools/gate_decision_readiness.py --emit-next-action",
        ]
    if decision == "her_routing_repair_path":
        return [
            LATEST_READINESS_CORPUS_COMMAND,
            "python3 tools/model_behavior_audit.py \"$LATEST_CORPUS\" --output-dir validation_corpus_outputs --output-prefix post_v2_corpus_audit",
            "python3 tools/corpus_provenance_drilldown.py --corpus \"$LATEST_CORPUS\"",
            "python3 tools/gate_decision_readiness.py --emit-next-action",
        ]
    if decision == "run_candidate_recall_diagnostic":
        return [
            LATEST_READINESS_CORPUS_COMMAND,
            "python3 tools/candidate_recall_audit.py \"$LATEST_CORPUS\"",
            "python3 tools/gate_decision_readiness.py --emit-next-action",
        ]
    if decision == "stop_human_approval_required":
        return [
            "# Phase 1: inspect current operator/config state without changing detector behavior.",
            "python3 tools/autonomous_next_action.py",
            "python3 tools/funding_resolver_healthcheck.py",
            "python3 tools/trace_method_diagnostic.py --timeout-seconds 90 --per-request-timeout-seconds 8",
            "python3 tools/operator_rpc_recovery_package.py",
            "# Phase 2: stop here unless a new operator-approved RPC endpoint/configuration is present through existing env/config.",
            "# Phase 3: only after that operator decision, run the bounded recovery sequence below.",
            "python3 tools/run_validation_corpus.py --network-probe --max-targets 3 --timeout-seconds 300",
            "python3 tools/prewarm_funding_cache.py --corpus validation_corpus/post_v2_validation_corpus.json --max-targets 48 --timeout-seconds 900",
            "python3 tools/run_validation_corpus.py --auto-policy --max-targets 12 --timeout-seconds 900",
            "python3 tools/gate_decision_readiness.py --emit-next-action",
            "python3 tools/autonomous_next_action.py",
        ]
    return [
        "python3 tools/validate_report_consistency.py",
        "python3 tools/gate_decision_readiness.py --emit-next-action",
        "python3 tools/autonomous_next_action.py",
    ]


def _bounded_task_for(decision: str, current_state: Mapping[str, Any] | None = None) -> list[str]:
    current_state = current_state or {}
    if decision == "run_rpc_cache_reliability_path":
        if _prewarm_budget_reached_with_artifacts(current_state):
            return [
                "Treat the previous missing-final-artifact failure as repaired unless a new run proves otherwise.",
                "Do not rerun the expanded 48-target auto-policy validation yet; keep validation to the bounded 12-target smoke unless RPC/cache coverage clearly clears.",
                "Run a family-balanced prewarm expansion with explicit `--max-total-traces`, `--max-trace-timeouts`, and wall-clock limits.",
                "Inspect cache writes, cache hit rate, RPC failures, trace timeouts, skipped families, and targets left unprewarmed by target family.",
                "Determine why the 12-target auto-policy still falls back to cache-only despite improved prewarm writes.",
                "If the 12-target smoke remains cache-only, classify the remaining blocker as public RPC capacity or cache coverage, not model evidence.",
                "Regenerate readiness and the autonomous next-action pack with the new prewarm coverage fields preserved.",
            ]
        return [
            "Diagnose why the expanded 48-target auto-policy run did not produce a final fallback artifact.",
            "Add better bounded diagnostics around public RPC stalls and validation terminal states.",
            "Ensure fallback always writes either a final corpus artifact or an explicit terminal failure artifact.",
            "Improve bounded timeout and orphan-worker cleanup reporting if the evidence points there.",
            "Improve prewarm coverage accounting by target family if fields are missing or ambiguous.",
            "Use the validation RPC one-shot request and endpoint-cooldown quarantine path to avoid repeatedly routing `eth_getLogs` through endpoints that already showed bounded network errors.",
            "Retry only the bounded sequence listed under Commands; do not start a long 48-target validation run unless a prior bounded smoke proves the harness is stable.",
            "Classify public RPC as the blocker if the bounded sequence stalls again.",
        ]
    if decision == "run_fresh_trace_validation_path":
        return [
            "Expand or recover corpus targets only from local saved metadata, previous run metadata, saved slugs, saved output directories, known prior inputs, and repository artifacts.",
            "Mark missing rerun inputs as audit-only instead of inventing targets.",
            "Regenerate readiness and the autonomous next action pack.",
        ]
    if decision == "produce_unique_review_packets":
        return [
            "Generate unique-row review packets from the latest ready corpus.",
            "Separate fresh trace-enabled rows from duplicate or saved-field-only rows.",
            "Do not alter production scoring, routing, or labels.",
        ]
    if decision == "strong_risk_gate_review_ready_rfc_only":
        return [
            "Produce an RFC only.",
            "Isolate fresh unique trace-enabled evidence and exclude duplicate inflation, legacy/audit-only missing fields, and broad saved-field screens.",
            "List exact Strong Risk gate branches implicated by the evidence.",
            "Do not enable production edits.",
        ]
    if decision == "source_attribution_repair_path":
        return [
            "Repair schema/source propagation for accepted hard-evidence sources only.",
            "Do not alter scoring, gates, weights, severity labels, funding eligibility, or HER eligibility.",
            "Rerun the bounded readiness/reporting checks.",
        ]
    if decision == "her_routing_repair_path":
        return [
            "Repair only violations of the accepted Hard Evidence Review contract.",
            "Do not broaden HER eligibility.",
            "Rerun the bounded readiness/reporting checks.",
        ]
    if decision == "run_candidate_recall_diagnostic":
        return [
            "Run a read-only recall diagnostic on current corpus outputs.",
            "Report candidate-recall opportunity counts without production detector edits.",
        ]
    if decision == "stop_human_approval_required":
        return [
            "Build a complete operator RPC capacity decision packet from the latest trace diagnostic, prewarm, network probe, smoke, readiness, and action-pack artifacts.",
            "Inspect `.inspoly_runtime.env` and active environment-derived endpoint labels without printing secrets or adding endpoint URLs.",
            "Separate three outcomes explicitly: no new operator configuration present, new operator-approved configuration present, or operator accepts cache-only/not-ready status.",
            "If no new operator-approved RPC endpoint/configuration is available through existing env/config, write or refresh an operator decision artifact, stop, and report validation remains blocked.",
            "If an operator-approved endpoint/configuration is present, apply only that existing env/config change and rerun the bounded recovery sequence.",
            "After any bounded rerun, regenerate readiness and autonomous next-action outputs, then include the next ready-to-copy Codex prompt in full.",
            "Do not run a larger validation corpus unless the bounded sequence clears the RPC/cache blocker and readiness no longer depends on cache-only evidence.",
        ]
    return [
        "Regenerate missing or inconsistent validation/readiness reports.",
        "Validate raw-vs-unique count consistency.",
        "Emit a fresh autonomous next action pack.",
    ]


def _output_summary_required(decision: str) -> list[str]:
    base = [
        "files changed",
        "artifacts read",
        "artifacts written",
        "tests run and results",
        "invariants preserved",
        "PROJECT_MEMORY.md update made",
        "final readiness classification",
        "autonomous decision",
        "ready-to-copy next Codex prompt path",
    ]
    if decision == "run_rpc_cache_reliability_path":
        base.extend(
            [
                "healthcheck status",
                "3-target network probe classification",
                "prewarm output path and coverage by target family",
                "12-target auto-policy smoke output path",
                "cache-only fallback output path or explicit terminal failure artifact",
                "orphan-worker cleanup / timeout accounting result",
                "whether public RPC is the blocker",
            ]
        )
    if decision == "stop_human_approval_required":
        base.extend(
            [
                "operator RPC configuration status",
                "latest trace-method diagnostic classification",
                "prewarm stop reason and target-family coverage",
                "whether the bounded sequence cleared the RPC/cache blocker",
                "whether human approval is required before any further validation run",
                "operator decision artifact path",
                "full ready-to-copy comprehensive Codex prompt",
            ]
        )
    return base


def _tests_required(decision: str) -> list[str]:
    tests = [
        "python3 -m py_compile tools/operator_rpc_recovery_package.py tools/autonomous_next_action.py tools/gate_decision_readiness.py tools/run_validation_corpus.py tools/prewarm_funding_cache.py tools/funding_resolver_healthcheck.py tools/validate_report_consistency.py tools/corpus_provenance_drilldown.py tools/strong_risk_gate_diagnostic.py tools/ai_case_reviewer.py app/scanner.py app/archive_scanner.py app/event_forensic.py app/funding_context.py app/polymarket.py app/config.py",
        "python3 -m unittest discover -s tests -p 'test_*.py'",
        "python3 tools/autonomous_next_action.py",
    ]
    if decision == "run_rpc_cache_reliability_path":
        tests.append("python3 tools/gate_decision_readiness.py --emit-next-action")
    return tests


def _prompt_for(
    *,
    decision: str,
    current_state: Mapping[str, Any],
    recommended_task: str,
    stop_conditions: list[str],
    evidence_paths: Mapping[str, Any],
) -> str:
    files = "\n".join(f"- {item}" for item in _files_to_inspect(decision, evidence_paths))
    status = "\n".join(_status_lines(current_state))
    constraints = "\n".join(f"- {item}" for item in INVARIANTS)
    bounded_task = "\n".join(f"- {item}" for item in _bounded_task_for(decision, current_state))
    commands = "\n".join(f"- `{item}`" for item in _commands_for(decision))
    output_summary = "\n".join(f"- {item}" for item in _output_summary_required(decision))
    tests = "\n".join(f"- `{item}`" for item in _tests_required(decision))
    stops = "\n".join(f"- {item}" for item in stop_conditions)

    prompt = "\n".join(
        [
            "You are working in the InsPoly repository.",
            "",
            "Role:",
            "Act as an autonomous validation/readiness engineer. This is workflow, reliability, and reporting infrastructure only.",
            "",
            "Current status:",
            status,
            "",
            "Hard constraints:",
            constraints,
            "",
            "Files and tools to inspect before editing:",
            files,
            "",
            "Bounded task:",
            recommended_task,
            "",
            "Detailed scope:",
            bounded_task,
            "",
            "Commands to run:",
            commands,
            "",
            "Tests to run:",
            tests,
            "",
            "Required output summary:",
            output_summary,
            "",
            "PROJECT_MEMORY.md update requirements:",
            "- Record files changed.",
            "- Record readiness classification and autonomous decision.",
            "- Record artifact paths written.",
            "- Record current RPC/cache blocker or why it cleared.",
            "- Record preserved invariants and recommended next step.",
            "",
            "Stop conditions:",
            stops,
            "",
            "Evidence handling:",
            "- Do not overclaim cache-only or stale evidence.",
            "- Treat duplicate inflation as reporting context only.",
            "- Report uncertainty explicitly when fresh trace-enabled evidence is below threshold.",
        ]
    ).strip()
    lowered = prompt.lower()
    for phrase in FORBIDDEN_PROMPT_PHRASES:
        if phrase in lowered:
            raise ValueError(f"Generated prompt contains forbidden phrase: {phrase}")
    return prompt + "\n"


def build_action_pack(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    readiness_json_path: Path | None = None,
    readiness_md_path: Path | None = None,
    prewarm_path: Path | None = None,
    corpus_output_path: Path | None = None,
    consistency_path: Path | None = None,
    strong_risk_diagnostic_path: Path | None = None,
    project_memory_path: Path | None = None,
) -> dict[str, Any]:
    paths = _latest_paths(
        output_dir=output_dir,
        readiness_json_path=readiness_json_path,
        readiness_md_path=readiness_md_path,
        prewarm_path=prewarm_path,
        corpus_output_path=corpus_output_path,
        consistency_path=consistency_path,
        strong_risk_diagnostic_path=strong_risk_diagnostic_path,
        project_memory_path=project_memory_path,
    )
    readiness = _load_json(paths["gate_decision_readiness_json"])
    artifacts = readiness.get("inputArtifacts") if isinstance(readiness.get("inputArtifacts"), Mapping) else {}
    artifact_key_map = {
        "funding_cache_prewarm_json": "prewarm_report",
        "post_v2_corpus_json": "corpus_output",
        "report_consistency_json": "report_consistency",
        "strong_risk_gate_diagnostic_json": "strong_risk_diagnostic",
    }
    explicit_paths = {
        "funding_cache_prewarm_json": prewarm_path,
        "post_v2_corpus_json": corpus_output_path,
        "report_consistency_json": consistency_path,
        "strong_risk_gate_diagnostic_json": strong_risk_diagnostic_path,
    }
    for path_key, artifact_key in artifact_key_map.items():
        if explicit_paths[path_key] is not None:
            continue
        artifact_path = str(artifacts.get(artifact_key) or "").strip()
        if artifact_path:
            resolved_artifact = _resolve(artifact_path)
            if resolved_artifact and resolved_artifact.exists():
                paths[path_key] = resolved_artifact
    prewarm = _load_json(paths["funding_cache_prewarm_json"])
    trace_method_diagnostic = _load_json(paths["trace_method_diagnostic_json"])
    corpus = _load_json(paths["post_v2_corpus_json"])
    consistency = _load_json(paths["report_consistency_json"])
    diagnostic = _load_json(paths["strong_risk_gate_diagnostic_json"])
    project_memory_text = _read_text(paths["project_memory"])
    _ = _read_text(paths["gate_decision_readiness_md"])

    missing_inputs = [
        key
        for key in (
            "gate_decision_readiness_json",
            "post_v2_corpus_json",
            "project_memory",
        )
        if not paths.get(key) or not Path(paths[key]).exists()
    ]
    if not consistency and not _dict(readiness.get("reportConsistency")):
        missing_inputs.append("report_consistency_json")
    if not diagnostic and not _as_int(readiness.get("freshUniqueGateLeakageCandidates")):
        missing_inputs.append("strong_risk_gate_diagnostic_json")

    decision = _decision_for(
        readiness=readiness,
        consistency=consistency,
        prewarm=prewarm,
        trace_method_diagnostic=trace_method_diagnostic,
        missing_inputs=missing_inputs,
    )
    if decision not in ALLOWED_DECISIONS:
        decision = "stop_human_approval_required"

    current = _current_state(
        readiness,
        corpus,
        prewarm,
        trace_method_diagnostic,
        diagnostic,
        consistency,
        project_memory_text,
    )
    evidence_paths = {
        key: str(value or "")
        for key, value in paths.items()
    }
    evidence_paths["missing_inputs"] = missing_inputs
    recommended_task = _recommended_task(decision, current)
    stops = _stop_conditions(decision)
    prompt = _prompt_for(
        decision=decision,
        current_state=current,
        recommended_task=recommended_task,
        stop_conditions=stops,
        evidence_paths=evidence_paths,
    )
    confidence_level = "high"
    confidence_reason = "Deterministic mapping from readiness classification and consistency state."
    if "gate_decision_readiness_json" in missing_inputs:
        confidence_level = "low"
        confidence_reason = "No readiness report was available; selected safe regeneration path."
    elif missing_inputs:
        confidence_level = "medium"
        confidence_reason = "Readiness report was available, but optional supporting artifacts were missing."

    pack: dict[str, Any] = {
        "current_state": current,
        "blocking_issue": _blocking_issue(decision, current, missing_inputs),
        "decision": decision,
        "recommended_next_task": recommended_task,
        "ready_to_copy_codex_prompt": prompt,
        "stop_conditions": stops,
        "human_approval_required_for": _human_approval_required(decision),
        "invariants_preserved": list(INVARIANTS),
        "evidence_paths": evidence_paths,
        "confidence": {
            "level": confidence_level,
            "reason": confidence_reason,
        },
    }
    return {section: pack[section] for section in OUTPUT_SECTIONS}


def render_markdown(pack: Mapping[str, Any]) -> str:
    lines = ["# Autonomous Next Action Pack", ""]
    for section in OUTPUT_SECTIONS:
        lines.append(f"## {section}")
        value = pack.get(section)
        if section == "ready_to_copy_codex_prompt":
            lines.extend(["", "```text", str(value or "").rstrip(), "```"])
        elif isinstance(value, Mapping):
            lines.extend(["", "```json", json.dumps(value, indent=2, sort_keys=True), "```"])
        elif isinstance(value, list):
            for item in value:
                lines.append(f"- {item}")
        else:
            lines.append(str(value or ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(
    pack: Mapping[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    timestamp: str | None = None,
) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = _unique_output_stamp(
        resolved,
        "autonomous_next_action",
        timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S"),
    )
    json_path = resolved / f"autonomous_next_action_{stamp}.json"
    markdown_path = resolved / f"autonomous_next_action_{stamp}.md"
    json_path.write_text(json.dumps(dict(pack), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(pack), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def _unique_output_stamp(directory: Path, prefix: str, base_stamp: str) -> str:
    stamp = base_stamp
    counter = 2
    while (
        (directory / f"{prefix}_{stamp}.json").exists()
        or (directory / f"{prefix}_{stamp}.md").exists()
    ):
        stamp = f"{base_stamp}_{counter:02d}"
        counter += 1
    return stamp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit an autonomous next-action pack for the latest validation readiness cycle.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--readiness-json", type=Path)
    parser.add_argument("--readiness-md", type=Path)
    parser.add_argument("--prewarm", type=Path)
    parser.add_argument("--corpus-output", type=Path)
    parser.add_argument("--consistency", type=Path)
    parser.add_argument("--strong-risk-diagnostic", type=Path)
    parser.add_argument("--project-memory", type=Path, default=PROJECT_MEMORY_PATH)
    args = parser.parse_args(argv)

    pack = build_action_pack(
        output_dir=args.output_dir,
        readiness_json_path=args.readiness_json,
        readiness_md_path=args.readiness_md,
        prewarm_path=args.prewarm,
        corpus_output_path=args.corpus_output,
        consistency_path=args.consistency,
        strong_risk_diagnostic_path=args.strong_risk_diagnostic,
        project_memory_path=args.project_memory,
    )
    outputs = write_outputs(pack, args.output_dir)
    print(f"Autonomous next-action JSON: {outputs['json_path']}")
    print(f"Autonomous next-action markdown: {outputs['markdown_path']}")
    print(f"Decision: {pack.get('decision', '')}")
    print(f"Next task: {pack.get('recommended_next_task', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
