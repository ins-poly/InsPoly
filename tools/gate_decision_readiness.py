from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CORPUS_CONFIG = Path("validation_corpus/post_v2_validation_corpus.json")
DEFAULT_OUTPUT_DIR = Path("validation_corpus_outputs")
STRONG_RISK_DIAGNOSTIC_DIR = Path("strong_risk_diagnostic_outputs")

COMPLETED_STATUSES = {
    "completed_funding_enabled",
    "completed_cache_only",
    "completed_no_funding_candidates",
    "completed_funding_blocked",
    "audit_only_saved_output",
}
MODEL_EVIDENCE_STATUSES = COMPLETED_STATUSES - {"audit_only_saved_output"}

READINESS_CLASSIFICATIONS = (
    "ready_no_gate_issue_observed",
    "ready_for_strong_risk_gate_review",
    "not_ready_corpus_too_cache_only",
    "not_ready_public_rpc_bottleneck",
    "not_ready_corpus_too_narrow",
    "source_attribution_repair_needed",
    "hard_evidence_routing_repair_needed",
)
RECOMMENDATIONS = (
    "continue_validation_no_model_change",
    "expand_corpus_more",
    "public_rpc_or_private_rpc_needed",
    "source_attribution_repair_needed",
    "hard_evidence_routing_repair_needed",
    "strong_risk_gate_review_ready",
    "strong_risk_gate_review_not_ready_cache_only",
    "candidate_recall_diagnostic_needed",
)


def _resolve(path: Path | str | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _load_json(path: Path | str | None) -> dict[str, Any]:
    resolved = _resolve(path)
    if not resolved or not resolved.exists():
        return {}
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _latest_file(directory: Path, pattern: str, *, exclude: tuple[str, ...] = ()) -> Path | None:
    root = _resolve(directory) or directory
    candidates = [
        path
        for path in root.glob(pattern)
        if all(token not in path.name for token in exclude)
    ]
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name)) if candidates else None


def _latest_corpus_output() -> Path | None:
    root = _resolve(DEFAULT_OUTPUT_DIR) or DEFAULT_OUTPUT_DIR
    candidates = [
        path
        for path in root.glob("post_v2_corpus_*.json")
        if "_audit_" not in path.name
    ]
    usable: list[Path] = []
    for path in candidates:
        payload = _load_json(path)
        if payload.get("validationPolicy") == "network_probe":
            continue
        usable.append(path)
    readiness_basis = [path for path in usable if _is_default_readiness_basis(_load_json(path))]
    candidates = readiness_basis or usable or candidates
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name)) if candidates else None


def _is_default_readiness_basis(payload: Mapping[str, Any]) -> bool:
    """Avoid letting tiny smoke artifacts shadow the latest broader readiness basis."""
    corpus_name = str(payload.get("corpus_name") or payload.get("corpusName") or "")
    if corpus_name.endswith("_smoke") or "_smoke" in corpus_name:
        return False
    interpreted = _as_int(payload.get("interpretableModelEvidenceTargets"))
    completed = _as_int(payload.get("completed_targets"))
    total = _as_int(payload.get("total_targets"))
    if interpreted >= 8 or completed >= 8 or total >= 8:
        return True
    status_counts = payload.get("target_status_counts")
    if isinstance(status_counts, Mapping):
        counted = sum(_as_int(value) for value in status_counts.values())
        return counted >= 8
    return False


def _same_artifact_path(value: Any, expected: Path | None) -> bool:
    if not value or expected is None:
        return False
    resolved_expected = _resolve(expected)
    resolved_value = _resolve(str(value))
    if resolved_expected and resolved_value and resolved_expected == resolved_value:
        return True
    return Path(str(value)).name == expected.name


def _report_references_corpus(payload: Mapping[str, Any], corpus_path: Path | None) -> bool:
    for key in ("inputArtifacts", "input_artifacts"):
        artifacts = payload.get(key)
        if isinstance(artifacts, Mapping):
            for artifact_key in ("corpus", "corpus_output", "corpusOutput"):
                if _same_artifact_path(artifacts.get(artifact_key), corpus_path):
                    return True
    sources = payload.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if isinstance(source, Mapping) and str(source.get("kind") or "") == "corpus":
                if _same_artifact_path(source.get("json_path"), corpus_path):
                    return True
    return False


def _report_metric_matches_corpus(payload: Mapping[str, Any], corpus_payload: Mapping[str, Any]) -> bool:
    metric_keys = (
        "rawVisibleRows",
        "uniqueVisibleRows",
        "rawStrongRiskRows",
        "uniqueStrongRiskRows",
        "rawHardEvidenceReviewRows",
        "uniqueHardEvidenceReviewRows",
    )
    present = 0
    for key in metric_keys:
        if key not in payload or key not in corpus_payload:
            continue
        present += 1
        if _as_int(payload.get(key)) != _as_int(corpus_payload.get(key)):
            return False
    return present >= 2


def _report_matches_corpus(payload: Mapping[str, Any], corpus_path: Path | None, corpus_payload: Mapping[str, Any]) -> bool:
    return _report_references_corpus(payload, corpus_path) or _report_metric_matches_corpus(payload, corpus_payload)


def _latest_matching_file(
    directory: Path,
    pattern: str,
    *,
    corpus_path: Path | None,
    corpus_payload: Mapping[str, Any],
) -> Path | None:
    root = _resolve(directory) or directory
    candidates = sorted(
        root.glob(pattern),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for path in candidates:
        payload = _load_json(path)
        if _report_matches_corpus(payload, corpus_path, corpus_payload):
            return path
    return None


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _target_family(target: Mapping[str, Any]) -> str:
    explicit = str(target.get("targetFamily") or "").strip()
    if explicit:
        return explicit
    tags = {str(tag) for tag in target.get("tags") or []}
    mode = str(target.get("mode") or "")
    if "gta_or_known_cluster" in tags:
        return "gta_or_known_cluster"
    if "sports_crypto" in tags:
        return "sports_crypto"
    if mode == "archive":
        return "archive_politics_world" if "politics_world" in tags else "archive"
    if "politics_world" in tags:
        return "politics_world_event_forensic"
    if "funding_candidate" in tags:
        return "funding_candidate_other"
    return "non_gta_other" if "non_gta" in tags else "unknown"


def _corpus_config_summary(config: Mapping[str, Any]) -> dict[str, Any]:
    targets = [target for target in config.get("targets") or [] if isinstance(target, Mapping)]
    tag_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()
    for target in targets:
        tags = {str(tag) for tag in target.get("tags") or []}
        tag_counts.update(tags)
        family_counts[_target_family(target)] += 1
        mode_counts[str(target.get("mode") or "unknown")] += 1
    fresh = sum(
        1
        for target in targets
        if bool(target.get("freshRerunnable")) or "fresh_rerunnable" in {str(tag) for tag in target.get("tags") or []}
    )
    audit_only = sum(
        1
        for target in targets
        if bool(target.get("auditOnly")) or str(target.get("inputType") or "") == "saved_output_replay"
    )
    return {
        "totalTargets": len(targets),
        "freshRerunnableTargets": fresh,
        "auditOnlyTargets": audit_only,
        "archiveTargets": mode_counts.get("archive", 0),
        "eventForensicTargets": mode_counts.get("event_forensic", 0),
        "resolvedOrPartialTargets": tag_counts.get("resolved_or_partial", 0),
        "liveOrUnresolvedTargets": tag_counts.get("live_or_unresolved", 0),
        "fundingCandidateTargets": tag_counts.get("funding_candidate", 0),
        "targetFamilyDistribution": dict(sorted(family_counts.items())),
        "tagCounts": dict(sorted(tag_counts.items())),
    }


def _run_summary(corpus_run: Mapping[str, Any]) -> dict[str, Any]:
    target_results = [
        target for target in corpus_run.get("target_results") or [] if isinstance(target, Mapping)
    ]
    status_counts = Counter(str(target.get("status") or "unknown") for target in target_results)
    completed_fresh = 0
    completed_families: Counter[str] = Counter()
    archive_completed = 0
    for target in target_results:
        status = str(target.get("status") or "")
        tags = {str(tag) for tag in target.get("tags") or []}
        if status not in COMPLETED_STATUSES:
            continue
        if "fresh_rerunnable" in tags and status != "audit_only_saved_output":
            completed_fresh += 1
        completed_families[_target_family(target)] += 1
        if "archive" in tags or target.get("mode") == "archive":
            archive_completed += 1
    interpreted = sum(status_counts.get(status, 0) for status in MODEL_EVIDENCE_STATUSES)
    audit = corpus_run.get("audit_summary") if isinstance(corpus_run.get("audit_summary"), Mapping) else {}
    return {
        "targetStatusCounts": dict(sorted(status_counts.items())),
        "completedTargets": _as_int(corpus_run.get("completed_targets")),
        "skippedTargets": _as_int(corpus_run.get("skipped_targets")),
        "abortedTargets": _as_int(corpus_run.get("aborted_targets")),
        "fundingEnabledTargets": _as_int(corpus_run.get("funding_enabled_targets")),
        "cacheOnlyTargets": _as_int(corpus_run.get("cache_only_targets")),
        "fundingBlockedTargets": _as_int(corpus_run.get("funding_blocked_targets")),
        "interpretableModelEvidenceTargets": interpreted,
        "completedFreshRerunnableTargets": completed_fresh,
        "completedArchiveTargets": archive_completed,
        "completedTargetFamilyDistribution": dict(sorted(completed_families.items())),
        "rowsInspected": _as_int(audit.get("total_rows_inspected")),
        "rawVisibleRows": _as_int(corpus_run.get("rawVisibleRows", audit.get("rawVisibleRows", audit.get("visible_rows")))),
        "uniqueVisibleRows": _as_int(corpus_run.get("uniqueVisibleRows", audit.get("uniqueVisibleRows"))),
        "rawStrongRiskRows": _as_int(corpus_run.get("rawStrongRiskRows", audit.get("rawStrongRiskRows", audit.get("strong_risk_rows")))),
        "uniqueStrongRiskRows": _as_int(corpus_run.get("uniqueStrongRiskRows", audit.get("uniqueStrongRiskRows"))),
        "strongRiskDedupeRatio": corpus_run.get("strongRiskDedupeRatio", audit.get("strongRiskDedupeRatio", 0)),
        "rawHardEvidenceReviewRows": _as_int(corpus_run.get("rawHardEvidenceReviewRows", audit.get("rawHardEvidenceReviewRows", audit.get("hard_evidence_review_rows")))),
        "uniqueHardEvidenceReviewRows": _as_int(corpus_run.get("uniqueHardEvidenceReviewRows", audit.get("uniqueHardEvidenceReviewRows"))),
        "hardEvidenceReviewDedupeRatio": corpus_run.get("hardEvidenceReviewDedupeRatio", audit.get("hardEvidenceReviewDedupeRatio", 0)),
        "cacheOnlyFallbackUsed": bool(corpus_run.get("cacheOnlyFallbackUsed")),
        "networkProbeStatus": str(corpus_run.get("networkProbeStatus") or ""),
        "finalClassification": str(corpus_run.get("final_classification") or ""),
        "auditSummary": dict(audit),
    }


def _hard_invalid_counts(drilldown: Mapping[str, Any], diagnostic: Mapping[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for source in (
        diagnostic.get("hardInvalidConditionCounts"),
        ((drilldown.get("hardEvidenceReview") or {}).get("hardInvalidConditionCounts") if isinstance(drilldown.get("hardEvidenceReview"), Mapping) else {}),
    ):
        if isinstance(source, Mapping):
            for key, value in source.items():
                counts[str(key)] += _as_int(value)
    return {key: counts[key] for key in sorted(counts) if counts[key]}


def _fresh_source_repair_count(run: Mapping[str, Any], diagnostic: Mapping[str, Any]) -> int:
    audit = run.get("auditSummary") if isinstance(run.get("auditSummary"), Mapping) else {}
    split = audit.get("strong_risk_exact_provenance_by_target_status")
    fresh = split.get("fresh_generated") if isinstance(split, Mapping) and isinstance(split.get("fresh_generated"), Mapping) else {}
    issues = fresh.get("source_attribution_issue_distribution") if isinstance(fresh, Mapping) else {}
    count = 0
    if isinstance(issues, Mapping):
        count += _as_int(issues.get("schema_propagation_gap"))
        count += _as_int(issues.get("hard_evidence_source_missing"))
    count += _as_int(diagnostic.get("freshStructuralHardEvidenceMissingSourceRows"))
    return count


def _gate_trace_summary(diagnostic: Mapping[str, Any], drilldown: Mapping[str, Any]) -> dict[str, Any]:
    strong = drilldown.get("strongRisk") if isinstance(drilldown.get("strongRisk"), Mapping) else {}
    traced = _as_int(
        diagnostic.get("strongRiskRowsWithGateTraceAvailable")
        or strong.get("strongRiskRowsWithGateTraceAvailable")
    )
    raw = _as_int(diagnostic.get("rawStrongRiskRows") or strong.get("totalStrongRiskRows"))
    without = _as_int(
        diagnostic.get("strongRiskRowsWithoutGateTrace")
        or strong.get("strongRiskRowsWithoutGateTrace")
    )
    if not raw and (traced or without):
        raw = traced + without
    return {
        "strongRiskRowsWithGateTrace": traced,
        "strongRiskRowsWithoutGateTrace": without,
        "strongRiskGateTraceCoverage": _ratio(traced, raw),
    }


def _funding_summary(prewarm: Mapping[str, Any], run: Mapping[str, Any]) -> dict[str, Any]:
    found = _as_int(prewarm.get("wallet_time_windows_found"))
    attempted = _as_int(prewarm.get("wallet_time_windows_attempted") or prewarm.get("traces_requested"))
    failures = _as_int(prewarm.get("rpc_failures") or prewarm.get("failures_observed"))
    funding_candidates = _as_int(prewarm.get("funding_candidate_targets"))
    if not prewarm:
        coverage = 0.0
        adequate = _as_int(run.get("fundingEnabledTargets")) > 0 or funding_candidates == 0
    else:
        coverage = _ratio(attempted, found)
        adequate = bool((found == 0 and funding_candidates == 0) or (coverage >= 0.75 and failures <= max(1, attempted // 5)))
    resolver_health = prewarm.get("resolver_health") if isinstance(prewarm.get("resolver_health"), Mapping) else {}
    cache_writes = prewarm.get("cache_writes")
    if cache_writes in {None, ""}:
        cache_writes = resolver_health.get("fundingTracePersistentCacheWriteCount", 0)
    return {
        "fundingCandidateTargets": funding_candidates,
        "tracesRequested": attempted,
        "cacheHits": _as_int(prewarm.get("cache_hits_observed") or prewarm.get("cache_hits")),
        "cacheMisses": _as_int(prewarm.get("cache_misses_observed") or prewarm.get("cache_misses")),
        "cacheWrites": _as_int(cache_writes),
        "rpcFailures": failures,
        "rateLimits": _as_int(prewarm.get("rate_limits")),
        "targetsLeftUnprewarmed": _as_int(prewarm.get("targets_left_unprewarmed")),
        "traceTimeoutsObserved": _as_int(prewarm.get("trace_timeouts_observed")),
        "maxTraceTimeouts": _as_int(prewarm.get("max_trace_timeouts")),
        "prewarmCoverage": coverage,
        "prewarmCoverageByTargetFamily": dict(prewarm.get("prewarm_coverage_by_target_family") or {}),
        "stopReason": str(prewarm.get("stop_reason") or ""),
        "fundingCoverageAdequate": adequate,
    }


def _classification_and_recommendation(summary: Mapping[str, Any]) -> tuple[str, str]:
    run = summary["run"]
    config = summary["corpusConfig"]
    trace = summary["strongRiskGateTrace"]
    funding = summary["funding"]
    consistency = summary["reportConsistency"]
    hard_invalid_total = sum(summary["herInvalidConditionCounts"].values())

    if hard_invalid_total:
        return "hard_evidence_routing_repair_needed", "hard_evidence_routing_repair_needed"
    if _as_int(summary.get("freshSourceAttributionRepairRows")):
        return "source_attribution_repair_needed", "source_attribution_repair_needed"

    completed_fresh = _as_int(run.get("completedFreshRerunnableTargets"))
    family_count = len(run.get("completedTargetFamilyDistribution") or config.get("targetFamilyDistribution") or {})
    archive_completed = _as_int(run.get("completedArchiveTargets"))
    if completed_fresh < 8 or family_count < 3 or archive_completed < 1:
        return "not_ready_corpus_too_narrow", "expand_corpus_more"

    interpreted = _as_int(run.get("interpretableModelEvidenceTargets"))
    cache_only = _as_int(run.get("cacheOnlyTargets"))
    cache_majority = interpreted > 0 and cache_only / interpreted > 0.5
    trace_coverage = float(trace.get("strongRiskGateTraceCoverage") or 0.0)
    raw_strong = _as_int(run.get("rawStrongRiskRows"))
    if cache_majority or (raw_strong > 0 and trace_coverage < 0.8):
        return "not_ready_corpus_too_cache_only", "strong_risk_gate_review_not_ready_cache_only"

    public_rpc_blocked = (
        _as_int(run.get("fundingBlockedTargets")) >= max(1, _as_int(run.get("fundingEnabledTargets")))
        and _as_int(run.get("fundingBlockedTargets")) > 0
    )
    prewarm_blocked = (
        funding.get("stopReason") in {"trace_timeout", "timeout"}
        and not funding.get("fundingCoverageAdequate")
    )
    if public_rpc_blocked or prewarm_blocked:
        return "not_ready_public_rpc_bottleneck", "public_rpc_or_private_rpc_needed"

    thresholds_pass = bool(summary["baseReadinessThresholdsPass"])
    if not thresholds_pass:
        return "not_ready_corpus_too_cache_only", "strong_risk_gate_review_not_ready_cache_only"

    if consistency.get("classification") not in {"count_reporting_consistent", "consistent", "", None}:
        return "not_ready_corpus_too_cache_only", "strong_risk_gate_review_not_ready_cache_only"

    fresh_gate_issues = _as_int(summary.get("freshUniqueGateLeakageCandidates"))
    if fresh_gate_issues:
        return "ready_for_strong_risk_gate_review", "strong_risk_gate_review_ready"
    return "ready_no_gate_issue_observed", "continue_validation_no_model_change"


def build_readiness(
    *,
    corpus_config_path: Path | None = None,
    corpus_output_path: Path | None = None,
    audit_output_path: Path | None = None,
    drilldown_path: Path | None = None,
    strong_risk_diagnostic_path: Path | None = None,
    prewarm_path: Path | None = None,
    consistency_path: Path | None = None,
) -> dict[str, Any]:
    resolved_paths = {
        "corpus_config": _resolve(corpus_config_path or DEFAULT_CORPUS_CONFIG),
        "corpus_output": _resolve(corpus_output_path) or _latest_corpus_output(),
        "model_behavior_audit": _resolve(audit_output_path),
        "corpus_provenance_drilldown": _resolve(drilldown_path)
        or _latest_file(DEFAULT_OUTPUT_DIR, "corpus_provenance_drilldown_*.json"),
        "strong_risk_diagnostic": _resolve(strong_risk_diagnostic_path)
        or _latest_file(STRONG_RISK_DIAGNOSTIC_DIR, "strong_risk_gate_diagnostic_*.json"),
        "prewarm_report": _resolve(prewarm_path)
        or _latest_file(DEFAULT_OUTPUT_DIR, "funding_cache_prewarm_*.json"),
        "report_consistency": _resolve(consistency_path)
        or _latest_file(DEFAULT_OUTPUT_DIR, "report_consistency_*.json"),
    }
    corpus_config = _load_json(resolved_paths["corpus_config"])
    corpus_run_payload = _load_json(resolved_paths["corpus_output"])
    if drilldown_path is None:
        resolved_paths["corpus_provenance_drilldown"] = (
            _latest_matching_file(
                DEFAULT_OUTPUT_DIR,
                "corpus_provenance_drilldown_*.json",
                corpus_path=resolved_paths["corpus_output"],
                corpus_payload=corpus_run_payload,
            )
            or resolved_paths["corpus_provenance_drilldown"]
        )
    if strong_risk_diagnostic_path is None:
        resolved_paths["strong_risk_diagnostic"] = (
            _latest_matching_file(
                STRONG_RISK_DIAGNOSTIC_DIR,
                "strong_risk_gate_diagnostic_*.json",
                corpus_path=resolved_paths["corpus_output"],
                corpus_payload=corpus_run_payload,
            )
            or resolved_paths["strong_risk_diagnostic"]
        )
    if consistency_path is None:
        resolved_paths["report_consistency"] = (
            _latest_matching_file(
                DEFAULT_OUTPUT_DIR,
                "report_consistency_*.json",
                corpus_path=resolved_paths["corpus_output"],
                corpus_payload=corpus_run_payload,
            )
            or resolved_paths["report_consistency"]
        )
    if resolved_paths["model_behavior_audit"] is None:
        audit_paths = corpus_run_payload.get("audit_output_paths")
        if isinstance(audit_paths, Mapping):
            resolved_paths["model_behavior_audit"] = _resolve(audit_paths.get("json_path"))
    if resolved_paths["model_behavior_audit"] is None:
        resolved_paths["model_behavior_audit"] = (
            _latest_matching_file(
                DEFAULT_OUTPUT_DIR,
                "post_v2_corpus_audit_*.json",
                corpus_path=resolved_paths["corpus_output"],
                corpus_payload=corpus_run_payload,
            )
            or _latest_file(DEFAULT_OUTPUT_DIR, "post_v2_corpus_audit_*.json")
        )
    audit_payload = _load_json(resolved_paths["model_behavior_audit"])
    if audit_payload and not corpus_run_payload.get("audit_summary"):
        corpus_run_payload["audit_summary"] = audit_payload
    drilldown = _load_json(resolved_paths["corpus_provenance_drilldown"])
    diagnostic = _load_json(resolved_paths["strong_risk_diagnostic"])
    prewarm = _load_json(resolved_paths["prewarm_report"])
    consistency = _load_json(resolved_paths["report_consistency"])

    config_summary = _corpus_config_summary(corpus_config)
    run = _run_summary(corpus_run_payload)
    trace = _gate_trace_summary(diagnostic, drilldown)
    funding = _funding_summary(prewarm, run)
    her_invalid = _hard_invalid_counts(drilldown, diagnostic)
    fresh_source_repair = _fresh_source_repair_count(run, diagnostic)
    fresh_unique_leakage = _as_int(diagnostic.get("freshUniqueGateLeakageCandidateRows"))
    broad_saved_leakage = _as_int(diagnostic.get("potentialGateLeakageCandidateRows"))
    strong_risk_too_rare = _as_int(run.get("uniqueStrongRiskRows")) < 20
    consistency_class = str(consistency.get("classification") or "")

    thresholds = {
        "freshRerunnableCompletedAtLeast8": _as_int(run.get("completedFreshRerunnableTargets")) >= 8,
        "targetFamiliesAtLeast3": len(run.get("completedTargetFamilyDistribution") or config_summary.get("targetFamilyDistribution") or {}) >= 3,
        "uniqueVisibleRowsAtLeast50": _as_int(run.get("uniqueVisibleRows")) >= 50,
        "uniqueStrongRiskRowsAtLeast20OrRare": _as_int(run.get("uniqueStrongRiskRows")) >= 20 or strong_risk_too_rare,
        "strongRiskGateTraceCoverageAtLeast80Pct": (
            _as_int(run.get("rawStrongRiskRows")) == 0
            or float(trace.get("strongRiskGateTraceCoverage") or 0.0) >= 0.8
        ),
        "herInvalidConditionCountsZero": not her_invalid,
        "reportConsistencyPasses": consistency_class in {"count_reporting_consistent", "consistent", ""},
        "fundingCoverageAdequate": bool(funding.get("fundingCoverageAdequate")),
        "noFreshUniqueGateLeakageObserved": fresh_unique_leakage == 0,
    }
    base_threshold_keys = [
        key for key in thresholds if key != "noFreshUniqueGateLeakageObserved"
    ]

    questions = {
        "corpusBroadEnough": config_summary["totalTargets"] >= 48,
        "enoughFreshRerunnableTargets": config_summary["freshRerunnableTargets"] >= 32,
        "enoughTargetFamiliesRepresented": len(config_summary["targetFamilyDistribution"]) >= 4,
        "archiveCoverageMeaningful": config_summary["archiveTargets"] >= 8,
        "fundingCoverageAdequate": bool(funding["fundingCoverageAdequate"]),
        "runTooCacheOnlyForGateDecisions": (
            _as_int(run["interpretableModelEvidenceTargets"]) > 0
            and _as_int(run["cacheOnlyTargets"]) / max(1, _as_int(run["interpretableModelEvidenceTargets"])) > 0.5
        ),
        "rawVsUniqueCountsConsistent": consistency_class in {"count_reporting_consistent", "consistent", ""},
        "strongRiskGateTraceCoverageAdequate": thresholds["strongRiskGateTraceCoverageAtLeast80Pct"],
        "herInvalidConditionCountsZero": not her_invalid,
        "gateLeakageCandidatesAreFreshTraceEnabledUniqueRows": fresh_unique_leakage > 0,
        "sourceAttributionRepairNeedObserved": fresh_source_repair > 0,
        "herRoutingRepairNeedObserved": bool(her_invalid),
        "strongRiskGateReviewNeedObserved": fresh_unique_leakage > 0,
    }

    summary: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "inputArtifacts": {key: str(value or "") for key, value in resolved_paths.items()},
        "allowedReadinessClassifications": list(READINESS_CLASSIFICATIONS),
        "allowedRecommendations": list(RECOMMENDATIONS),
        "corpusConfig": config_summary,
        "run": run,
        "strongRiskGateTrace": trace,
        "funding": funding,
        "reportConsistency": {"classification": consistency_class},
        "herInvalidConditionCounts": her_invalid,
        "freshSourceAttributionRepairRows": fresh_source_repair,
        "freshUniqueGateLeakageCandidates": fresh_unique_leakage,
        "broadSavedFieldGateLeakageCandidates": broad_saved_leakage,
        "strongRiskTooRareInSample": strong_risk_too_rare,
        "readinessThresholds": thresholds,
        "readinessThresholdsPass": all(thresholds.values()),
        "baseReadinessThresholdsPass": all(thresholds[key] for key in base_threshold_keys),
        "questions": questions,
    }
    classification, recommendation = _classification_and_recommendation(summary)
    summary["readinessClassification"] = classification
    summary["recommendation"] = recommendation
    return summary


def render_markdown(summary: Mapping[str, Any]) -> str:
    run = summary.get("run") if isinstance(summary.get("run"), Mapping) else {}
    config = summary.get("corpusConfig") if isinstance(summary.get("corpusConfig"), Mapping) else {}
    trace = summary.get("strongRiskGateTrace") if isinstance(summary.get("strongRiskGateTrace"), Mapping) else {}
    funding = summary.get("funding") if isinstance(summary.get("funding"), Mapping) else {}
    lines = [
        "# Gate Decision Readiness",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Final readiness classification: `{summary.get('readinessClassification', '')}`",
        f"- Recommendation: `{summary.get('recommendation', '')}`",
        f"- Corpus targets: {config.get('totalTargets', 0)} total / {config.get('freshRerunnableTargets', 0)} fresh-rerunnable / {config.get('archiveTargets', 0)} archive",
        f"- Completed/skipped/aborted targets: {run.get('completedTargets', 0)}/{run.get('skippedTargets', 0)}/{run.get('abortedTargets', 0)}",
        f"- Funding-enabled/cache-only/funding-blocked targets: {run.get('fundingEnabledTargets', 0)}/{run.get('cacheOnlyTargets', 0)}/{run.get('fundingBlockedTargets', 0)}",
        f"- Visible rows: {run.get('rawVisibleRows', 0)} raw / {run.get('uniqueVisibleRows', 0)} unique",
        f"- Strong Risk rows: {run.get('rawStrongRiskRows', 0)} raw / {run.get('uniqueStrongRiskRows', 0)} unique (dedupe ratio {run.get('strongRiskDedupeRatio', 0)})",
        f"- Hard Evidence Review rows: {run.get('rawHardEvidenceReviewRows', 0)} raw / {run.get('uniqueHardEvidenceReviewRows', 0)} unique (dedupe ratio {run.get('hardEvidenceReviewDedupeRatio', 0)})",
        f"- Strong Risk gate trace coverage: {trace.get('strongRiskRowsWithGateTrace', 0)} / {run.get('rawStrongRiskRows', 0)} ({trace.get('strongRiskGateTraceCoverage', 0)})",
        f"- HER invalid condition counts: {summary.get('herInvalidConditionCounts', {})}",
        f"- Fresh unique gate-leakage candidates: {summary.get('freshUniqueGateLeakageCandidates', 0)}",
        f"- Broad saved-field gate-leakage candidates: {summary.get('broadSavedFieldGateLeakageCandidates', 0)}",
        "",
        "## Target Families",
    ]
    for family, count in (config.get("targetFamilyDistribution") or {}).items():
        lines.append(f"- {family}: {count}")
    lines.extend(["", "## Funding Prewarm"])
    lines.extend(
        [
            f"- Funding-candidate targets: {funding.get('fundingCandidateTargets', 0)}",
            f"- Traces requested: {funding.get('tracesRequested', 0)}",
            f"- Cache hits/misses/writes: {funding.get('cacheHits', 0)}/{funding.get('cacheMisses', 0)}/{funding.get('cacheWrites', 0)}",
            f"- RPC failures/rate limits: {funding.get('rpcFailures', 0)}/{funding.get('rateLimits', 0)}",
            f"- Targets left unprewarmed: {funding.get('targetsLeftUnprewarmed', 0)}",
            f"- Trace timeouts observed/limit: {funding.get('traceTimeoutsObserved', 0)}/{funding.get('maxTraceTimeouts', 0)}",
            f"- Stop reason: {funding.get('stopReason', '') or 'none'}",
            f"- Coverage: {funding.get('prewarmCoverage', 0)}",
        ]
    )
    lines.extend(["", "## Readiness Questions"])
    for key, value in (summary.get("questions") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Thresholds"])
    for key, value in (summary.get("readinessThresholds") or {}).items():
        lines.append(f"- {key}: {value}")
    next_action = summary.get("autonomousNextAction")
    if isinstance(next_action, Mapping):
        lines.extend(["", "## Autonomous Next Action"])
        if next_action.get("error"):
            lines.append(f"- Error: {next_action.get('error')}")
            missing = next_action.get("missingInputs")
            if missing:
                lines.append(f"- Missing inputs: {missing}")
        else:
            lines.extend(
                [
                    f"- JSON: {next_action.get('json_path', '')}",
                    f"- Markdown: {next_action.get('markdown_path', '')}",
                    f"- Decision: `{next_action.get('decision', '')}`",
                    f"- Next task: {next_action.get('recommended_next_task', '')}",
                    "",
                    "### Ready-To-Copy Codex Prompt",
                    "",
                    "```text",
                    str(next_action.get("ready_to_copy_codex_prompt") or "").rstrip(),
                    "```",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _path_from_summary(summary: Mapping[str, Any], key: str) -> Path | None:
    artifacts = summary.get("inputArtifacts") if isinstance(summary.get("inputArtifacts"), Mapping) else {}
    value = str(artifacts.get(key) or "").strip()
    return Path(value) if value else None


def _emit_autonomous_next_action(
    summary: Mapping[str, Any],
    *,
    readiness_json_path: Path,
    readiness_markdown_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    try:
        try:
            from tools.autonomous_next_action import (
                build_action_pack,
                write_outputs as write_next_action_outputs,
            )
        except ModuleNotFoundError:
            from autonomous_next_action import (  # type: ignore
                build_action_pack,
                write_outputs as write_next_action_outputs,
            )

        pack = build_action_pack(
            output_dir=output_dir,
            readiness_json_path=readiness_json_path,
            readiness_md_path=readiness_markdown_path,
            prewarm_path=_path_from_summary(summary, "prewarm_report"),
            corpus_output_path=_path_from_summary(summary, "corpus_output"),
            consistency_path=_path_from_summary(summary, "report_consistency"),
            strong_risk_diagnostic_path=_path_from_summary(summary, "strong_risk_diagnostic"),
            project_memory_path=Path("PROJECT_MEMORY.md"),
        )
        outputs = write_next_action_outputs(pack, output_dir)
        return {
            "json_path": outputs["json_path"],
            "markdown_path": outputs["markdown_path"],
            "decision": pack.get("decision", ""),
            "recommended_next_task": pack.get("recommended_next_task", ""),
            "ready_to_copy_codex_prompt": pack.get("ready_to_copy_codex_prompt", ""),
        }
    except Exception as exc:  # pragma: no cover - defensive CLI integration path.
        missing = []
        for key in ("corpus_output", "prewarm_report", "report_consistency", "strong_risk_diagnostic"):
            path = _path_from_summary(summary, key)
            if not path or not path.exists():
                missing.append(key)
        return {
            "error": str(exc),
            "missingInputs": missing,
        }


def write_outputs(
    summary: Mapping[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    emit_next_action: bool = False,
) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = _unique_output_stamp(
        resolved,
        "gate_decision_readiness",
        datetime.now(UTC).strftime("%Y%m%d_%H%M%S"),
    )
    json_path = resolved / f"gate_decision_readiness_{stamp}.json"
    markdown_path = resolved / f"gate_decision_readiness_{stamp}.md"
    summary_to_write = dict(summary)
    json_path.write_text(json.dumps(summary_to_write, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(summary_to_write), encoding="utf-8")
    outputs = {"json_path": str(json_path), "markdown_path": str(markdown_path)}
    if emit_next_action:
        next_action = _emit_autonomous_next_action(
            summary_to_write,
            readiness_json_path=json_path,
            readiness_markdown_path=markdown_path,
            output_dir=resolved,
        )
        summary_to_write["autonomousNextAction"] = next_action
        json_path.write_text(json.dumps(summary_to_write, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        markdown_path.write_text(render_markdown(summary_to_write), encoding="utf-8")
        if next_action.get("json_path"):
            outputs["autonomous_next_action_json_path"] = str(next_action["json_path"])
        if next_action.get("markdown_path"):
            outputs["autonomous_next_action_markdown_path"] = str(next_action["markdown_path"])
        if next_action.get("decision"):
            outputs["autonomous_next_action_decision"] = str(next_action["decision"])
    return outputs


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
    parser = argparse.ArgumentParser(description="Classify whether the current validation evidence is ready for Strong Risk/HER gate decisions.")
    parser.add_argument("--corpus-config", type=Path, default=DEFAULT_CORPUS_CONFIG)
    parser.add_argument("--corpus-output", type=Path)
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument("--drilldown", type=Path)
    parser.add_argument("--strong-risk-diagnostic", type=Path)
    parser.add_argument("--prewarm", type=Path)
    parser.add_argument("--consistency", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--emit-next-action", action="store_true", help="Emit an autonomous next-action pack and reference it in the readiness markdown.")
    args = parser.parse_args(argv)
    summary = build_readiness(
        corpus_config_path=args.corpus_config,
        corpus_output_path=args.corpus_output,
        audit_output_path=args.audit_output,
        drilldown_path=args.drilldown,
        strong_risk_diagnostic_path=args.strong_risk_diagnostic,
        prewarm_path=args.prewarm,
        consistency_path=args.consistency,
    )
    outputs = write_outputs(summary, args.output_dir, emit_next_action=args.emit_next_action)
    print(f"Gate readiness JSON: {outputs['json_path']}")
    print(f"Gate readiness markdown: {outputs['markdown_path']}")
    print(f"Final readiness classification: {summary.get('readinessClassification', '')}")
    print(f"Recommendation: {summary.get('recommendation', '')}")
    if args.emit_next_action:
        print(f"Autonomous next-action JSON: {outputs.get('autonomous_next_action_json_path', '')}")
        print(f"Autonomous next-action markdown: {outputs.get('autonomous_next_action_markdown_path', '')}")
        print(f"Autonomous decision: {outputs.get('autonomous_next_action_decision', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
