from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.model_behavior_audit import collect_records, normalize_record
from tools.model_behavior_audit import _listish, _lookup, _number, _string_value
from tools.report_dedupe import (
    annotate_dedupe,
    count_hygiene_warnings,
    dedupe_key as report_dedupe_key,
    dedupe_summary as report_dedupe_summary,
    unique_records as report_unique_records,
)


DEFAULT_OUTPUT_DIR = Path("validation_corpus_outputs")
SUPPRESSOR_CODES = (
    "bot_like_execution",
    "high_volume_public_user",
    "domain_specialist",
    "stale_or_resolution_gap",
    "near_certainty",
    "yield_farm",
    "theta_decay",
)
HER_STRUCTURAL_SOURCES = (
    "split_wallet_pattern",
    "strict_shared_funding_source",
    "strict_shared_funding",
    "non_proxy_shared_funding",
    "dormant_wallet_reactivation",
    "low_probability_early_winner",
    "event_family_repeat_narrow_context",
)
RECOMMENDATIONS = (
    "no_model_change_continue_autonomous_validation",
    "source_attribution_repair_needed",
    "strong_risk_composition_diagnostic_needed",
    "hard_evidence_routing_repair_needed",
    "corpus_expansion_needed",
    "public_rpc_infrastructure_needed",
    "manual_review_of_specific_packets_needed",
)


def _load_json(path: Path | None) -> Mapping[str, Any]:
    if not path:
        return {}
    candidate = _resolve_path(path)
    if not candidate.exists():
        return {}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _resolve_path(path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return REPO_ROOT / candidate


def _path_key(path: Path | str) -> str:
    try:
        return str(_resolve_path(path).resolve())
    except OSError:
        return str(_resolve_path(path))


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on", "present"}


def _normalize_label(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _selected_paths_from_corpus(corpus: Mapping[str, Any]) -> list[Path]:
    selected: list[Path] = []
    for value in corpus.get("selected_output_paths") or []:
        if value:
            selected.append(_resolve_path(str(value)))
    if selected:
        return selected
    for target in corpus.get("target_results") or []:
        if not isinstance(target, Mapping):
            continue
        for value in target.get("audit_paths") or target.get("output_paths") or []:
            if value:
                selected.append(_resolve_path(str(value)))
    return selected


def _target_path_values(target: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("audit_paths", "output_paths", "selected_outputs"):
        values.extend(str(value) for value in target.get(key) or [] if value)
    export_files = target.get("export_files")
    if isinstance(export_files, Mapping):
        values.extend(str(value) for value in export_files.values() if value)
    report_path = target.get("report_json_path")
    if report_path:
        values.append(str(report_path))
    return values


def _target_info(target: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "label": str(target.get("label") or target.get("validationTargetLabel") or "unknown"),
        "status": str(target.get("status") or target.get("validationBundleStatus") or "unknown"),
        "mode": str(target.get("mode") or "unknown"),
        "run_mode": str(target.get("validationRunMode") or ""),
        "tags": [str(tag) for tag in target.get("tags") or []],
        "input_type": str(target.get("inputType") or target.get("input_type") or ""),
        "input_value": str(target.get("inputValue") or target.get("input_value") or ""),
    }


def _build_target_index(corpus: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], list[tuple[Path, dict[str, Any]]]]:
    exact: dict[str, dict[str, Any]] = {}
    roots: list[tuple[Path, dict[str, Any]]] = []
    for target in corpus.get("target_results") or []:
        if not isinstance(target, Mapping):
            continue
        info = _target_info(target)
        for value in _target_path_values(target):
            path = _resolve_path(value)
            exact[_path_key(path)] = info
            roots.append((path if path.is_dir() else path.parent, info))
    roots.sort(key=lambda item: len(str(item[0])), reverse=True)
    return exact, roots


def _target_for_source(
    source_path: str,
    exact: Mapping[str, dict[str, Any]],
    roots: Sequence[tuple[Path, dict[str, Any]]],
) -> dict[str, Any]:
    if not source_path:
        return {
            "label": "unknown",
            "status": "unknown",
            "mode": "unknown",
            "run_mode": "",
            "tags": [],
            "input_type": "",
            "input_value": "",
        }
    key = _path_key(source_path)
    if key in exact:
        return exact[key]
    path = _resolve_path(source_path)
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    for root, info in roots:
        try:
            root_resolved = root.resolve()
        except OSError:
            root_resolved = root
        if resolved == root_resolved or root_resolved in resolved.parents:
            return info
    return {
        "label": path.parent.name or "unknown",
        "status": "unknown",
        "mode": "unknown",
        "run_mode": "",
        "tags": [],
        "input_type": "",
        "input_value": "",
    }


def _collect_rows(corpus: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    selected = _selected_paths_from_corpus(corpus)
    missing = [str(path) for path in selected if not path.exists()]
    exact, roots = _build_target_index(corpus)
    raw_records = collect_records(selected)
    normalized_rows: list[dict[str, Any]] = []
    for raw in raw_records:
        record = normalize_record(raw)
        target = _target_for_source(record.get("source_path", ""), exact, roots)
        record["target_label"] = target["label"]
        record["target_status"] = target["status"]
        record["target_mode"] = target["mode"]
        record["target_run_mode"] = target["run_mode"]
        record["target_tags"] = target["tags"]
        record["_raw_record"] = raw
        normalized_rows.append(record)
    return list(annotate_dedupe(normalized_rows)), missing


def _opening_status(record: Mapping[str, Any]) -> str:
    if record.get("strong_risk_opening_exposure_confirmed") or record.get("opening_exposure_confirmed"):
        return "confirmed"
    if record.get("schema_has_new_fields") or record.get("strong_risk_exact_gate_branch_present"):
        return "not_confirmed"
    return "unknown"


def _has_source(record: Mapping[str, Any], *sources: str) -> bool:
    normalized_sources = {_normalize_label(source) for source in sources}
    fields = (
        "hard_evidence_sources",
        "raw_independent_support_sources",
        "strong_risk_structural_sources_resolved",
        "strong_risk_hard_evidence_eligible_sources",
        "suspicious_funding_independent_support_sources",
    )
    for field in fields:
        for value in record.get(field) or []:
            if _normalize_label(value) in normalized_sources:
                return True
    return False


def _evidence_sources_for_strong(record: Mapping[str, Any]) -> list[str]:
    sources: list[str] = []
    for field in (
        "hard_evidence_sources",
        "strong_risk_gate_evidence_sources",
        "strong_risk_structural_sources_resolved",
        "strong_risk_timing_proof_sources",
        "raw_independent_support_sources",
    ):
        sources.extend(str(value) for value in record.get(field) or [] if value)
    if not sources:
        sources.append("none")
    return sorted(dict.fromkeys(sources))


def _is_cache_only_funding_derived(record: Mapping[str, Any]) -> bool:
    if record.get("target_status") != "completed_cache_only" and record.get("target_run_mode") != "cache_only":
        return False
    if record.get("funding_trace_from_persistent_cache"):
        return True
    if record.get("funding_trace_persistent_cache_hit_count", 0) and record.get("funding_evidence_grade") != "unknown":
        return True
    return False


def _timestamp_bucket(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 16:
        return text[:16]
    return text


def _first_raw_value(raw: Mapping[str, Any], *keys: str) -> str:
    return _string_value(raw, *keys)


def strong_risk_dedupe_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return report_dedupe_key(record)


def unique_records(records: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return list(report_unique_records(records))


def _dedupe_summary(records: Sequence[Mapping[str, Any]], *, row_type: str) -> dict[str, Any]:
    return report_dedupe_summary(records, row_type=row_type)


def _hard_invalid_flags(record: Mapping[str, Any]) -> list[str]:
    flags: list[str] = []
    if (
        record.get("hard_evidence_review")
        and record.get("proxy_funding_present")
        and not record.get("strict_funding_present")
        and not record.get("raw_independent_support_sources")
    ):
        flags.append("cex_bridge_proxy_only_hard_evidence_review")
    if (
        record.get("hard_evidence_review")
        and record.get("high_impact_repricing_present")
        and not record.get("raw_independent_support_sources")
    ):
        flags.append("high_impact_repricing_only_hard_evidence_review")
    if (
        record.get("hard_evidence_review")
        and "suspicious_recent_funding" in (record.get("hard_evidence_sources") or [])
        and record.get("suspicious_funding_quality") == "weak"
    ):
        flags.append("weak_suspicious_funding_hard_evidence_review")
    if (
        record.get("hard_evidence_review")
        and "suspicious_recent_funding" in (record.get("hard_evidence_sources") or [])
        and record.get("suspicious_funding_quality") == "unknown"
    ):
        flags.append("unknown_suspicious_funding_hard_evidence_review")
    if (
        record.get("hard_evidence_review")
        and record.get("funding_evidence_grade") == "multi_hop_unknown"
        and "suspicious_recent_funding" in (record.get("hard_evidence_sources") or [])
        and not record.get("suspicious_funding_independent_support")
    ):
        flags.append("multi_hop_unknown_hard_evidence_without_independent_support")
    if (
        record.get("suspicious_funding_only_hard_review")
        and record.get("suppressors")
        and not record.get("suspicious_funding_independent_support")
    ):
        flags.append("suspicious_funding_only_hard_evidence_review_with_suppressors")
    return flags


def _score_sort_key(record: Mapping[str, Any]) -> tuple[float, float]:
    raw = record.get("_raw_record") if isinstance(record.get("_raw_record"), Mapping) else {}
    notional = _number(
        _lookup(
            raw,
            "notional",
            "notionalUsd",
            "notional_usd",
            "amountUsd",
            "amount_usd",
            "sizeUsd",
            "size_usd",
            "tradeNotionalUsd",
            "trade_notional_usd",
        )
    ) or 0.0
    return (float(record.get("score") or 0.0), float(notional))


def _example_packet(record: Mapping[str, Any]) -> dict[str, Any]:
    raw = record.get("_raw_record") if isinstance(record.get("_raw_record"), Mapping) else {}
    notional = _number(
        _lookup(
            raw,
            "notional",
            "notionalUsd",
            "notional_usd",
            "amountUsd",
            "amount_usd",
            "sizeUsd",
            "size_usd",
            "tradeNotionalUsd",
            "trade_notional_usd",
        )
    )
    timestamp = _string_value(
        raw,
        "timestamp",
        "tradeTimestamp",
        "trade_timestamp",
        "createdAt",
        "created_at",
        "time",
    )
    suppressors = list(record.get("suppressors") or [])
    hard_sources = list(record.get("hard_evidence_sources") or [])
    rationale_parts: list[str] = []
    if record.get("strong_risk"):
        rationale_parts.append(
            f"Strong Risk via {record.get('strong_risk_gate_type') or 'unknown'}"
        )
    if record.get("hard_evidence_review"):
        rationale_parts.append(
            "HER via " + (", ".join(hard_sources) if hard_sources else "missing sources")
        )
    if suppressors:
        rationale_parts.append("suppressors=" + ",".join(suppressors))
    if not rationale_parts:
        rationale_parts.append("Saved fields show contextual row; no new judgment added.")
    return {
        "target": record.get("target_label", ""),
        "bundle": Path(str(record.get("source_path") or "")).parent.name,
        "sourcePath": record.get("source_path", ""),
        "sourceRow": record.get("source_row", ""),
        "wallet": record.get("wallet", ""),
        "market": record.get("market_title", ""),
        "conditionId": record.get("condition_id", ""),
        "tradeId": record.get("row_id", ""),
        "timestamp": timestamp,
        "notional": notional if notional is not None else "unknown",
        "score": record.get("score"),
        "severity": record.get("severity", ""),
        "judgment": record.get("judgment", ""),
        "hardEvidenceSources": hard_sources,
        "hardEvidenceStrength": record.get("hard_evidence_strength", ""),
        "fundingEvidenceGrade": record.get("funding_evidence_grade", ""),
        "suspiciousFundingQuality": record.get("suspicious_funding_quality", ""),
        "suspiciousFundingIndependentSupport": record.get("suspicious_funding_independent_support", False),
        "suppressors": suppressors,
        "openingExposureStatus": _opening_status(record),
        "repricingSourceQuality": record.get("repricing_source_quality", ""),
        "candidateAdmissionStage": record.get("candidate_admission_stage", ""),
        "strongRiskGateType": record.get("strong_risk_gate_type", ""),
        "strongRiskExactGateBranch": record.get("strong_risk_exact_gate_branch", ""),
        "strongRiskCompositionClass": record.get("strong_risk_composition_class", ""),
        "shortSavedFieldRationale": "; ".join(rationale_parts),
    }


def _top_examples(records: Iterable[Mapping[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    ordered = sorted(records, key=_score_sort_key, reverse=True)
    return [_example_packet(record) for record in ordered[:limit]]


def _target_family_summary(corpus: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    target_results = [
        target for target in corpus.get("target_results") or [] if isinstance(target, Mapping)
    ]
    status_counts = Counter(str(target.get("status") or "unknown") for target in target_results)
    tag_counts: Counter[str] = Counter()
    fresh = 0
    audit_only = 0
    for target in target_results:
        tags = [str(tag) for tag in target.get("tags") or []]
        tag_counts.update(tags)
        if "fresh_rerunnable" in tags:
            fresh += 1
        if str(target.get("status") or "") == "audit_only_saved_output" or "audit_only_saved_output" in tags:
            audit_only += 1
    strong_by_tag: Counter[str] = Counter()
    hard_by_tag: Counter[str] = Counter()
    strong_by_target = Counter(record.get("target_label", "unknown") for record in rows if record.get("strong_risk"))
    hard_by_target = Counter(record.get("target_label", "unknown") for record in rows if record.get("hard_evidence_review"))
    for record in rows:
        tags = [str(tag) for tag in record.get("target_tags") or []]
        if record.get("strong_risk"):
            strong_by_tag.update(tags)
        if record.get("hard_evidence_review"):
            hard_by_tag.update(tags)
    strong_total = sum(strong_by_target.values())
    hard_total = sum(hard_by_target.values())
    top_strong = strong_by_target.most_common(1)[0] if strong_by_target else ("none", 0)
    top_hard = hard_by_target.most_common(1)[0] if hard_by_target else ("none", 0)
    one_family_dominates = bool(
        (strong_total and top_strong[1] / strong_total >= 0.5)
        or (hard_total and top_hard[1] / hard_total >= 0.5)
    )
    public_rpc_limited = False
    classification = "cache_only_provenance_acceptable"
    if str(corpus.get("final_classification") or "").endswith("cache-only corpus"):
        classification = "cache_only_limits_model_interpretation"
    if one_family_dominates:
        classification = "one_family_dominates"
    if int(status_counts.get("aborted_rpc_stall") or 0) or corpus.get("cacheOnlyFallbackUsed"):
        public_rpc_limited = True
        classification = "funding_network_bottleneck_blocks_full_validation"
    meaningful_categories = {
        tag
        for tag, count in tag_counts.items()
        if count
        and tag
        in {
            "politics_world",
            "sports_crypto",
            "gta_or_known_cluster",
            "non_gta",
            "archive",
            "event_forensic",
            "live_or_unresolved",
            "resolved_or_partial",
        }
    }
    if len(target_results) < 8 or len(meaningful_categories) < 3:
        classification = "corpus_too_narrow"
    return {
        "targetCount": len(target_results),
        "statusCounts": _counter_dict(status_counts),
        "targetCountByTag": _counter_dict(tag_counts),
        "freshRerunnableTargets": fresh,
        "auditOnlyTargets": audit_only,
        "cacheOnlyTargets": int(status_counts.get("completed_cache_only") or 0),
        "networkBlockedTargets": int(status_counts.get("aborted_rpc_stall") or 0)
        + int(status_counts.get("completed_funding_blocked") or 0)
        + int(status_counts.get("aborted_timeout") or 0),
        "strongRiskRowsByTarget": _counter_dict(strong_by_target),
        "hardEvidenceReviewRowsByTarget": _counter_dict(hard_by_target),
        "strongRiskRowsByTargetTag": _counter_dict(strong_by_tag),
        "hardEvidenceReviewRowsByTargetTag": _counter_dict(hard_by_tag),
        "topStrongRiskTarget": {"target": top_strong[0], "rows": top_strong[1]},
        "topHardEvidenceReviewTarget": {"target": top_hard[0], "rows": top_hard[1]},
        "oneFamilyDominatesCounts": one_family_dominates,
        "cacheOnlyLimitsConclusions": str(corpus.get("final_classification") or "").endswith("cache-only corpus"),
        "publicRpcLimited": public_rpc_limited,
        "classification": classification,
    }


def _strong_risk_summary(rows: Sequence[Mapping[str, Any]], audit_summary: Mapping[str, Any]) -> dict[str, Any]:
    strong_rows = [record for record in rows if record.get("strong_risk")]
    unique_strong_rows = list(unique_records(strong_rows))
    by_evidence: Counter[str] = Counter()
    by_hard: Counter[str] = Counter()
    suppressors: Counter[str] = Counter()
    opening = Counter()
    driven = Counter()
    by_gate_family = Counter()
    by_gate_name = Counter()
    by_trace_independent = Counter()
    by_trace_timing_only = Counter()
    by_trace_retrospective_only = Counter()
    by_trace_score_only = Counter()
    by_trace_suppressor = Counter()
    by_trace_opening = Counter()
    def _compose(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        hard_counter: Counter[str] = Counter()
        gate_family_counter: Counter[str] = Counter()
        gate_name_counter: Counter[str] = Counter()
        driven_counter: Counter[str] = Counter()
        suppressor_counter: Counter[str] = Counter()
        for item in records:
            hard_counter.update(item.get("hard_evidence_sources") or ["none"])
            gate_family_counter[str(item.get("strong_risk_gate_family") or "unknown")] += 1
            gate_name_counter[str(item.get("strong_risk_gate_name") or item.get("strong_risk_exact_gate_branch") or "unknown")] += 1
            suppressor_counter.update(item.get("suppressors") or [])
            if item.get("raw_independent_support_sources") or item.get("strong_risk_structural_sources_resolved"):
                driven_counter["structure"] += 1
            if item.get("suspicious_funding_hard_eligible") or "suspicious_recent_funding" in (item.get("hard_evidence_sources") or []):
                driven_counter["suspicious_funding"] += 1
            if _has_source(item, "dormant_wallet_reactivation"):
                driven_counter["dormant_reactivation"] += 1
            if _has_source(item, "split_wallet_pattern"):
                driven_counter["split_wallet"] += 1
            if _has_source(item, "strict_shared_funding_source", "strict_shared_funding", "non_proxy_shared_funding"):
                driven_counter["strict_shared_funding"] += 1
            if _has_source(item, "low_probability_early_winner"):
                driven_counter["low_probability_early_winner"] += 1
            if _has_source(item, "event_family_repeat_narrow_context"):
                driven_counter["event_family_repeat"] += 1
            if item.get("strong_risk_timing_repricing_only") or (
                item.get("strong_risk_gate_type") == "timing_led"
                and not item.get("strong_risk_structural_sources_resolved")
            ):
                driven_counter["timing_repricing_only"] += 1
            if item.get("strong_risk_score_only") or item.get("strong_risk_composition_class") == "score_only":
                driven_counter["score_only_or_unclear_saved_provenance"] += 1
        return {
            "hardEvidenceSources": _counter_dict(hard_counter),
            "gateFamily": _counter_dict(gate_family_counter),
            "gateName": _counter_dict(gate_name_counter),
            "drivenBy": _counter_dict(driven_counter),
            "suppressors": _counter_dict(suppressor_counter),
        }

    for record in strong_rows:
        by_evidence.update(_evidence_sources_for_strong(record))
        hard_sources = record.get("hard_evidence_sources") or ["none"]
        by_hard.update(str(source) for source in hard_sources)
        suppressors.update(record.get("suppressors") or [])
        opening[_opening_status(record)] += 1
        by_gate_family[str(record.get("strong_risk_gate_family") or "unknown")] += 1
        by_gate_name[str(record.get("strong_risk_gate_name") or record.get("strong_risk_exact_gate_branch") or "unknown")] += 1
        by_trace_independent["true" if record.get("strong_risk_has_independent_hard_evidence") else "false"] += 1
        by_trace_timing_only["true" if record.get("strong_risk_timing_repricing_only") else "false"] += 1
        by_trace_retrospective_only["true" if record.get("strong_risk_retrospective_only") else "false"] += 1
        by_trace_score_only["true" if record.get("strong_risk_score_only") else "false"] += 1
        by_trace_suppressor["true" if record.get("strong_risk_suppressor_conflict") else "false"] += 1
        by_trace_opening[str(record.get("strong_risk_opening_exposure_status") or _opening_status(record))] += 1
        if record.get("raw_independent_support_sources") or record.get("strong_risk_structural_sources_resolved"):
            driven["structure"] += 1
        if record.get("suspicious_funding_hard_eligible") or "suspicious_recent_funding" in hard_sources:
            driven["suspicious_funding"] += 1
        if _has_source(record, "dormant_wallet_reactivation"):
            driven["dormant_reactivation"] += 1
        if _has_source(record, "split_wallet_pattern"):
            driven["split_wallet"] += 1
        if _has_source(record, "strict_shared_funding_source", "strict_shared_funding", "non_proxy_shared_funding"):
            driven["strict_shared_funding"] += 1
        if _has_source(record, "low_probability_early_winner"):
            driven["low_probability_early_winner"] += 1
        if _has_source(record, "event_family_repeat_narrow_context"):
            driven["event_family_repeat"] += 1
        if (
            record.get("strong_risk_gate_type") == "timing_led"
            and not record.get("strong_risk_structural_sources_resolved")
        ) or (
            record.get("high_impact_repricing_present")
            and not record.get("raw_independent_support_sources")
            and not record.get("suspicious_funding_hard_eligible")
        ):
            driven["timing_repricing_only"] += 1
        if record.get("strong_risk_composition_class") == "score_only" or (
            record.get("strong_risk_gate_type") == "legacy_unknown"
            and not record.get("strong_risk_gate_evidence_sources")
        ):
            driven["score_only_or_unclear_saved_provenance"] += 1
    for code in SUPPRESSOR_CODES:
        suppressors.setdefault(code, 0)
    composition = audit_summary.get("strong_risk_composition")
    if not isinstance(composition, Mapping):
        composition = {}
    score_after_exact = int(composition.get("strong_risk_score_only_after_exact_provenance_rows") or 0)
    gate_leakage = int(composition.get("strong_risk_gate_leakage_candidate_rows") or 0)
    weak_repricing = int(composition.get("strong_risk_weak_mechanical_unknown_repricing_rows") or 0)
    suppressor_no_structure = int(composition.get("strong_risk_suppressor_conflict_without_structure_rows") or 0)
    saved_insufficient = int(composition.get("strong_risk_rows_with_no_gate_evidence_sources") or 0)
    issue_dist = composition.get("strong_risk_rows_by_source_attribution_issue")
    if isinstance(issue_dist, Mapping):
        saved_insufficient += int(issue_dist.get("legacy_unknown") or 0) + int(issue_dist.get("inference_insufficient") or 0)
    saved_insufficient += sum(
        1
        for record in strong_rows
        if record.get("strong_risk_gate_type") == "legacy_unknown"
        or record.get("strong_risk_source_attribution_issue") in {"legacy_unknown", "inference_insufficient"}
        or not record.get("strong_risk_gate_evidence_sources")
    )
    if score_after_exact or gate_leakage:
        classification = "strong_risk_score_only_concern"
    elif weak_repricing and int(driven.get("timing_repricing_only") or 0):
        classification = "strong_risk_timing_repricing_concern"
    elif strong_rows and suppressor_no_structure / len(strong_rows) > 0.2:
        classification = "strong_risk_suppressor_conflict_concern"
    elif saved_insufficient:
        classification = "strong_risk_saved_fields_insufficient"
    else:
        classification = "strong_risk_provenance_clear"
    return {
        "totalStrongRiskRows": len(strong_rows),
        "uniqueStrongRiskRows": len(unique_strong_rows),
        "strongRiskDuplication": _dedupe_summary(strong_rows, row_type="StrongRisk"),
        "strongRiskCompositionBeforeDeduplication": _compose(strong_rows),
        "strongRiskCompositionAfterDeduplication": _compose(unique_strong_rows),
        "strongRiskRowsByTarget": _counter_dict(Counter(record.get("target_label", "unknown") for record in strong_rows)),
        "uniqueStrongRiskRowsByTarget": _counter_dict(Counter(record.get("target_label", "unknown") for record in unique_strong_rows)),
        "strongRiskRowsByEvidenceSource": _counter_dict(by_evidence),
        "strongRiskRowsByHardEvidenceSources": _counter_dict(by_hard),
        "strongRiskRowsWithNoHardEvidenceSources": sum(1 for record in strong_rows if not record.get("hard_evidence_sources")),
        "uniqueStrongRiskRowsWithNoHardEvidenceSources": sum(1 for record in unique_strong_rows if not record.get("hard_evidence_sources")),
        "strongRiskRowsByOpeningExposureStatus": _counter_dict(opening),
        "strongRiskRowsWithSuppressors": _counter_dict(suppressors),
        "strongRiskRowsDrivenBy": _counter_dict(driven),
        "strongRiskRowsByGateFamily": _counter_dict(by_gate_family),
        "strongRiskRowsByGateName": _counter_dict(by_gate_name),
        "strongRiskRowsByHasIndependentHardEvidence": _counter_dict(by_trace_independent),
        "strongRiskRowsByTimingRepricingOnly": _counter_dict(by_trace_timing_only),
        "strongRiskRowsByRetrospectiveOnly": _counter_dict(by_trace_retrospective_only),
        "strongRiskRowsByScoreOnly": _counter_dict(by_trace_score_only),
        "strongRiskRowsBySuppressorConflict": _counter_dict(by_trace_suppressor),
        "strongRiskRowsByTraceOpeningExposureStatus": _counter_dict(by_trace_opening),
        "strongRiskRowsWithGateTraceAvailable": sum(1 for record in strong_rows if record.get("strong_risk_gate_trace_available")),
        "strongRiskRowsWithoutGateTrace": sum(1 for record in strong_rows if not record.get("strong_risk_gate_trace_available")),
        "strongRiskRedFlagGroups": {
            "noHardSourcesNoIndependentEvidence": sum(
                1
                for record in strong_rows
                if not record.get("hard_evidence_sources")
                and not record.get("strong_risk_has_independent_hard_evidence")
            ),
            "suppressorConflictNoIndependentEvidence": sum(
                1
                for record in strong_rows
                if record.get("strong_risk_suppressor_conflict")
                and not record.get("strong_risk_has_independent_hard_evidence")
            ),
            "timingRepricingOnly": sum(1 for record in strong_rows if record.get("strong_risk_timing_repricing_only")),
            "retrospectiveOnly": sum(1 for record in strong_rows if record.get("strong_risk_retrospective_only")),
            "scoreOnlyOrUnclear": sum(
                1
                for record in strong_rows
                if record.get("strong_risk_score_only")
                or record.get("strong_risk_gate_type") == "legacy_unknown"
            ),
            "openingExposureNotConfirmed": sum(
                1
                for record in strong_rows
                if str(record.get("strong_risk_opening_exposure_status") or _opening_status(record)) == "not_confirmed"
            ),
            "nearCertaintyAndHighVolume": sum(
                1
                for record in strong_rows
                if "near_certainty" in (record.get("suppressors") or [])
                and "high_volume_public_user" in (record.get("suppressors") or [])
            ),
            "staleNoIndependentEvidence": sum(
                1
                for record in strong_rows
                if "stale_or_resolution_gap" in (record.get("suppressors") or [])
                and not record.get("strong_risk_has_independent_hard_evidence")
            ),
            "fundingUnknownWhenRelevant": sum(
                1
                for record in strong_rows
                if record.get("funding_evidence_grade") == "unknown"
                and any("funding" in str(source) for source in record.get("strong_risk_gate_evidence_sources") or [])
            ),
            "repricingUnknownWhenRelevant": sum(
                1
                for record in strong_rows
                if record.get("repricing_source_quality") == "unknown"
                and (
                    record.get("strong_risk_timing_repricing_only")
                    or "rapid_favorable_repricing" in (record.get("strong_risk_timing_proof_sources") or [])
                )
            ),
        },
        "strongRiskRowsWithFundingEvidenceGradeUnknown": sum(
            1 for record in strong_rows if record.get("funding_evidence_grade") == "unknown"
        ),
        "strongRiskRowsWithRepricingSourceQualityUnknown": sum(
            1 for record in strong_rows if record.get("repricing_source_quality") == "unknown"
        ),
        "strongRiskRowsCacheOnlyFundingDerived": sum(1 for record in strong_rows if _is_cache_only_funding_derived(record)),
        "strongRiskGateTypeDistribution": composition.get("strong_risk_rows_by_gate_type", {}),
        "strongRiskCompositionClassDistribution": composition.get("strong_risk_rows_by_composition_class", {}),
        "strongRiskSourceAttributionIssueDistribution": composition.get("strong_risk_rows_by_source_attribution_issue", {}),
        "diagnosticClassification": classification,
    }


def _hard_evidence_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    hard_rows = [record for record in rows if record.get("hard_evidence_review")]
    unique_hard_rows = list(unique_records(hard_rows))
    source_counter: Counter[str] = Counter()
    strength_counter = Counter(str(record.get("hard_evidence_strength") or "unknown") for record in hard_rows)
    unique_source_counter: Counter[str] = Counter()
    unique_strength_counter = Counter(str(record.get("hard_evidence_strength") or "unknown") for record in unique_hard_rows)
    suppressors: Counter[str] = Counter()
    invalid: Counter[str] = Counter()
    for record in hard_rows:
        source_counter.update(record.get("hard_evidence_sources") or ["none"])
        suppressors.update(record.get("suppressors") or [])
        invalid.update(_hard_invalid_flags(record))
    for record in unique_hard_rows:
        unique_source_counter.update(record.get("hard_evidence_sources") or ["none"])
    for code in SUPPRESSOR_CODES:
        suppressors.setdefault(code, 0)
    suspicious_funding_hard = [
        record for record in hard_rows if "suspicious_recent_funding" in (record.get("hard_evidence_sources") or [])
    ]
    multi_hop_hard = [
        record
        for record in suspicious_funding_hard
        if record.get("funding_evidence_grade") == "multi_hop_unknown"
    ]
    return {
        "totalHardEvidenceReviewRows": len(hard_rows),
        "uniqueHardEvidenceReviewRows": len(unique_hard_rows),
        "hardEvidenceReviewDuplication": _dedupe_summary(hard_rows, row_type="HardEvidenceReview"),
        "hardEvidenceReviewCompositionBeforeDeduplication": {
            "hardEvidenceSources": _counter_dict(source_counter),
            "hardEvidenceStrength": _counter_dict(strength_counter),
        },
        "hardEvidenceReviewCompositionAfterDeduplication": {
            "hardEvidenceSources": _counter_dict(unique_source_counter),
            "hardEvidenceStrength": _counter_dict(unique_strength_counter),
        },
        "hardEvidenceReviewRowsByTarget": _counter_dict(Counter(record.get("target_label", "unknown") for record in hard_rows)),
        "hardEvidenceReviewRowsByHardEvidenceSources": _counter_dict(source_counter),
        "hardEvidenceReviewRowsByHardEvidenceStrength": _counter_dict(strength_counter),
        "splitWalletHardEvidenceReviewRows": sum(1 for record in hard_rows if _has_source(record, "split_wallet_pattern")),
        "strictSharedFundingHardEvidenceReviewRows": sum(
            1 for record in hard_rows if _has_source(record, "strict_shared_funding_source", "strict_shared_funding", "non_proxy_shared_funding")
        ),
        "suspiciousFundingHardEvidenceReviewRows": len(suspicious_funding_hard),
        "suspiciousFundingOnlyHardEvidenceReviewRows": sum(
            1 for record in hard_rows if set(record.get("hard_evidence_sources") or []) == {"suspicious_recent_funding"}
        ),
        "suspiciousFundingOnlyHardEvidenceReviewRowsWithSuppressors": sum(
            1
            for record in hard_rows
            if set(record.get("hard_evidence_sources") or []) == {"suspicious_recent_funding"}
            and record.get("suppressors")
        ),
        "multiHopUnknownHardEvidenceReviewRows": len(multi_hop_hard),
        "multiHopUnknownHardEvidenceReviewRowsWithoutIndependentSupport": sum(
            1 for record in multi_hop_hard if not record.get("suspicious_funding_independent_support")
        ),
        "directSuspiciousFundingHardEvidenceReviewRows": sum(
            1 for record in suspicious_funding_hard if record.get("funding_evidence_grade") == "suspicious_direct"
        ),
        "dormantReactivationHardEvidenceReviewRows": sum(
            1 for record in hard_rows if _has_source(record, "dormant_wallet_reactivation")
        ),
        "lowProbabilityEarlyWinnerHardEvidenceReviewRows": sum(
            1 for record in hard_rows if _has_source(record, "low_probability_early_winner")
        ),
        "eventFamilyRepeatNarrowContextHardEvidenceReviewRows": sum(
            1 for record in hard_rows if _has_source(record, "event_family_repeat_narrow_context")
        ),
        "highImpactRepricingOnlyHardEvidenceReviewRows": invalid.get("high_impact_repricing_only_hard_evidence_review", 0),
        "cexBridgeProxyOnlyHardEvidenceReviewRows": invalid.get("cex_bridge_proxy_only_hard_evidence_review", 0),
        "hardEvidenceReviewRowsWithSuppressors": _counter_dict(suppressors),
        "hardEvidenceReviewRowsWithFundingEvidenceGradeUnknown": sum(
            1 for record in hard_rows if record.get("funding_evidence_grade") == "unknown"
        ),
        "hardEvidenceReviewRowsWithRepricingSourceQualityUnknown": sum(
            1 for record in hard_rows if record.get("repricing_source_quality") == "unknown"
        ),
        "hardEvidenceReviewRowsWithOpeningExposureUnknown": sum(
            1 for record in hard_rows if _opening_status(record) == "unknown"
        ),
        "hardInvalidConditionCounts": _counter_dict(invalid),
    }


def _stratified_examples(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    strong_rows = [record for record in rows if record.get("strong_risk")]
    hard_rows = [record for record in rows if record.get("hard_evidence_review")]
    examples: dict[str, Any] = {
        "topStrongRiskWithStructuralEvidence": _top_examples(
            record
            for record in strong_rows
            if record.get("raw_independent_support_sources") or record.get("strong_risk_structural_sources_resolved")
        ),
        "topStrongRiskWithNoHardEvidenceSources": _top_examples(
            record for record in strong_rows if not record.get("hard_evidence_sources")
        ),
        "topStrongRiskWithSuppressors": _top_examples(
            record for record in strong_rows if record.get("suppressors")
        ),
        "topStrongRiskTimingRepricingDriven": _top_examples(
            record
            for record in strong_rows
            if (
                record.get("strong_risk_gate_type") == "timing_led"
                or record.get("high_impact_repricing_present")
                or "rapid_favorable_repricing" in (record.get("strong_risk_timing_proof_sources") or [])
            )
            and not record.get("strong_risk_structural_sources_resolved")
        ),
        "topSuspiciousFundingHardEvidenceReview": _top_examples(
            record for record in hard_rows if "suspicious_recent_funding" in (record.get("hard_evidence_sources") or [])
        ),
        "topHardEvidenceReviewWithSuppressors": _top_examples(
            record for record in hard_rows if record.get("suppressors")
        ),
        "topCacheOnlyFundingDerivedRows": _top_examples(
            record for record in rows if _is_cache_only_funding_derived(record)
        ),
        "topInvalidOrUnderspecifiedRows": _top_examples(
            record
            for record in rows
            if _hard_invalid_flags(record)
            or (
                record.get("strong_risk")
                and record.get("strong_risk_source_attribution_issue") in {"legacy_unknown", "inference_insufficient"}
            )
        ),
        "topHardEvidenceReviewBySource": {},
    }
    by_source: dict[str, list[dict[str, Any]]] = {}
    for source in HER_STRUCTURAL_SOURCES:
        matches = [record for record in hard_rows if _has_source(record, source)]
        if matches:
            by_source[source] = _top_examples(matches)
    examples["topHardEvidenceReviewBySource"] = by_source
    return examples


def _recommendation(
    *,
    strong_summary: Mapping[str, Any],
    hard_summary: Mapping[str, Any],
    target_summary: Mapping[str, Any],
    recall: Mapping[str, Any],
    consistency: Mapping[str, Any],
    public_rpc_limit: Mapping[str, Any],
) -> str:
    invalid_total = sum(int(value or 0) for value in (hard_summary.get("hardInvalidConditionCounts") or {}).values())
    if invalid_total:
        return "hard_evidence_routing_repair_needed"
    if consistency and consistency.get("classification") not in {"consistent", "count_reporting_consistent", "", None}:
        return "source_attribution_repair_needed"
    strong_class = str(strong_summary.get("diagnosticClassification") or "")
    if strong_class in {
        "strong_risk_score_only_concern",
        "strong_risk_timing_repricing_concern",
        "strong_risk_suppressor_conflict_concern",
    }:
        return "strong_risk_composition_diagnostic_needed"
    if strong_class == "strong_risk_saved_fields_insufficient":
        return "manual_review_of_specific_packets_needed"
    if str(target_summary.get("classification") or "") in {"corpus_too_narrow", "one_family_dominates"}:
        return "corpus_expansion_needed"
    if public_rpc_limit and str(public_rpc_limit.get("classification") or "").startswith("public RPC insufficient"):
        return "public_rpc_infrastructure_needed"
    if str(recall.get("classification") or "") not in {"", "no recall opportunity observed"}:
        return "manual_review_of_specific_packets_needed"
    return "no_model_change_continue_autonomous_validation"


def build_drilldown(
    *,
    corpus_path: Path,
    acceptance_path: Path | None = None,
    recall_path: Path | None = None,
    consistency_path: Path | None = None,
    public_rpc_limit_path: Path | None = None,
) -> dict[str, Any]:
    corpus = _load_json(corpus_path)
    acceptance = _load_json(acceptance_path)
    recall = _load_json(recall_path)
    consistency = _load_json(consistency_path)
    public_rpc_limit = _load_json(public_rpc_limit_path)
    rows, missing = _collect_rows(corpus)
    audit_summary = corpus.get("audit_summary") if isinstance(corpus.get("audit_summary"), Mapping) else {}
    strong_summary = _strong_risk_summary(rows, audit_summary)
    hard_summary = _hard_evidence_summary(rows)
    visible_summary = report_dedupe_summary([record for record in rows if record.get("visible")], row_type="Visible")
    duplicate_targets = Counter()
    duplicate_targets.update((strong_summary.get("strongRiskDuplication") or {}).get("topDuplicateTargets") or {})
    duplicate_targets.update((hard_summary.get("hardEvidenceReviewDuplication") or {}).get("topDuplicateTargets") or {})
    count_hygiene = {
        "rawVisibleRows": visible_summary["rawVisibleRows"],
        "uniqueVisibleRows": visible_summary["uniqueVisibleRows"],
        "visibleDedupeRatio": visible_summary["visibleDedupeRatio"],
        "rawStrongRiskRows": strong_summary["totalStrongRiskRows"],
        "uniqueStrongRiskRows": strong_summary["uniqueStrongRiskRows"],
        "strongRiskDedupeRatio": (strong_summary.get("strongRiskDuplication") or {}).get("strongRiskDuplicationRatio", 0),
        "rawHardEvidenceReviewRows": hard_summary["totalHardEvidenceReviewRows"],
        "uniqueHardEvidenceReviewRows": hard_summary["uniqueHardEvidenceReviewRows"],
        "hardEvidenceReviewDedupeRatio": (hard_summary.get("hardEvidenceReviewDuplication") or {}).get("hardEvidenceReviewDuplicationRatio", 0),
        "topDuplicateStrongRiskKeys": (strong_summary.get("strongRiskDuplication") or {}).get("topDuplicateKeys", []),
        "topDuplicateHardEvidenceReviewKeys": (hard_summary.get("hardEvidenceReviewDuplication") or {}).get("topDuplicateKeys", []),
        "topDuplicateTargets": _counter_dict(duplicate_targets),
        "visibleDedupe": visible_summary,
        "strongRiskDedupe": strong_summary.get("strongRiskDuplication") or {},
        "hardEvidenceReviewDedupe": hard_summary.get("hardEvidenceReviewDuplication") or {},
    }
    target_summary = _target_family_summary(corpus, rows)
    examples = _stratified_examples(rows)
    recommendation = _recommendation(
        strong_summary=strong_summary,
        hard_summary=hard_summary,
        target_summary=target_summary,
        recall=recall,
        consistency=consistency,
        public_rpc_limit=public_rpc_limit,
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_artifacts": {
            "corpus": str(corpus_path),
            "acceptance": str(acceptance_path or ""),
            "recall": str(recall_path or ""),
            "consistency": str(consistency_path or ""),
            "public_rpc_limit": str(public_rpc_limit_path or ""),
        },
        "artifact_classifications": {
            "corpus": corpus.get("final_classification", ""),
            "acceptance": acceptance.get("classification", ""),
            "recall": recall.get("classification", ""),
            "consistency": consistency.get("classification", ""),
            "public_rpc_limit": public_rpc_limit.get("classification", ""),
        },
        "rowsLoadedFromSavedOutputs": len(rows),
        **{key: count_hygiene[key] for key in (
            "rawVisibleRows",
            "uniqueVisibleRows",
            "visibleDedupeRatio",
            "rawStrongRiskRows",
            "uniqueStrongRiskRows",
            "strongRiskDedupeRatio",
            "rawHardEvidenceReviewRows",
            "uniqueHardEvidenceReviewRows",
            "hardEvidenceReviewDedupeRatio",
            "topDuplicateStrongRiskKeys",
            "topDuplicateHardEvidenceReviewKeys",
            "topDuplicateTargets",
        )},
        "countHygiene": count_hygiene,
        "countHygieneWarnings": count_hygiene_warnings(count_hygiene),
        "missingReferencedOutputPaths": missing,
        "consistencyStatus": consistency.get("classification", "unknown"),
        "strongRisk": strong_summary,
        "hardEvidenceReview": hard_summary,
        "targetFamilyAndCacheInterpretation": target_summary,
        "stratifiedExamples": examples,
        "finalRecommendation": recommendation,
        "allowedRecommendations": list(RECOMMENDATIONS),
    }


def _render_counter(counter: Mapping[str, Any], *, limit: int | None = None) -> list[str]:
    items = list(counter.items())
    items.sort(key=lambda item: (-int(item[1] or 0), str(item[0])))
    if limit is not None:
        items = items[:limit]
    return [f"  - {key}: {value}" for key, value in items] or ["  - none: 0"]


def render_markdown(summary: Mapping[str, Any]) -> str:
    strong = summary.get("strongRisk") if isinstance(summary.get("strongRisk"), Mapping) else {}
    hard = summary.get("hardEvidenceReview") if isinstance(summary.get("hardEvidenceReview"), Mapping) else {}
    target = (
        summary.get("targetFamilyAndCacheInterpretation")
        if isinstance(summary.get("targetFamilyAndCacheInterpretation"), Mapping)
        else {}
    )
    artifacts = summary.get("artifact_classifications") if isinstance(summary.get("artifact_classifications"), Mapping) else {}
    lines = [
        "# Corpus Provenance Drilldown",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Final recommendation: {summary.get('finalRecommendation', '')}",
        f"- Corpus classification: {artifacts.get('corpus', '')}",
        f"- Acceptance classification: {artifacts.get('acceptance', '')}",
        f"- Recall classification: {artifacts.get('recall', '')}",
        f"- Consistency status: {summary.get('consistencyStatus', '')}",
        f"- Public RPC classification: {artifacts.get('public_rpc_limit', '')}",
        f"- Rows loaded from saved outputs: {summary.get('rowsLoadedFromSavedOutputs', 0)}",
        f"- Missing referenced output paths: {len(summary.get('missingReferencedOutputPaths') or [])}",
        "",
        "## Strong Risk Composition",
        "",
        f"- Strong Risk rows: {strong.get('totalStrongRiskRows', 0)} raw / {strong.get('uniqueStrongRiskRows', 0)} unique (dedupe ratio {(strong.get('strongRiskDuplication') or {}).get('strongRiskDuplicationRatio', 0)})",
        f"- Diagnostic classification: {strong.get('diagnosticClassification', '')}",
        f"- Strong Risk rows with no hardEvidenceSources: {strong.get('strongRiskRowsWithNoHardEvidenceSources', 0)}",
        f"- Strong Risk rows with gate trace: {strong.get('strongRiskRowsWithGateTraceAvailable', 0)}",
        f"- Strong Risk rows without gate trace: {strong.get('strongRiskRowsWithoutGateTrace', 0)}",
        f"- Strong Risk rows with fundingEvidenceGrade unknown: {strong.get('strongRiskRowsWithFundingEvidenceGradeUnknown', 0)}",
        f"- Strong Risk rows with repricingSourceQuality unknown: {strong.get('strongRiskRowsWithRepricingSourceQualityUnknown', 0)}",
        f"- Cache-only funding-derived Strong Risk rows: {strong.get('strongRiskRowsCacheOnlyFundingDerived', 0)}",
        "",
        "Strong Risk by hardEvidenceSources:",
        *_render_counter(strong.get("strongRiskRowsByHardEvidenceSources") or {}, limit=20),
        "",
        "Strong Risk driven by:",
        *_render_counter(strong.get("strongRiskRowsDrivenBy") or {}, limit=20),
        "",
        "Strong Risk by gate family:",
        *_render_counter(strong.get("strongRiskRowsByGateFamily") or {}, limit=20),
        "",
        "Strong Risk by gate name:",
        *_render_counter(strong.get("strongRiskRowsByGateName") or {}, limit=20),
        "",
        "Strong Risk red-flag groups:",
        *_render_counter((strong.get("strongRiskRedFlagGroups") or {}), limit=20),
        "",
        "Strong Risk suppressors:",
        *_render_counter(strong.get("strongRiskRowsWithSuppressors") or {}, limit=20),
        "",
        "## Hard Evidence Review Composition",
        "",
        f"- Hard Evidence Review rows: {hard.get('totalHardEvidenceReviewRows', 0)} raw / {hard.get('uniqueHardEvidenceReviewRows', 0)} unique (dedupe ratio {(hard.get('hardEvidenceReviewDuplication') or {}).get('hardEvidenceReviewDuplicationRatio', 0)})",
        f"- Split-wallet HER rows: {hard.get('splitWalletHardEvidenceReviewRows', 0)}",
        f"- Strict shared funding HER rows: {hard.get('strictSharedFundingHardEvidenceReviewRows', 0)}",
        f"- Suspicious funding HER rows: {hard.get('suspiciousFundingHardEvidenceReviewRows', 0)}",
        f"- Suspicious-funding-only HER rows: {hard.get('suspiciousFundingOnlyHardEvidenceReviewRows', 0)}",
        f"- Multi-hop unknown HER rows without independent support: {hard.get('multiHopUnknownHardEvidenceReviewRowsWithoutIndependentSupport', 0)}",
        f"- Dormant reactivation HER rows: {hard.get('dormantReactivationHardEvidenceReviewRows', 0)}",
        f"- Low-probability early winner HER rows: {hard.get('lowProbabilityEarlyWinnerHardEvidenceReviewRows', 0)}",
        f"- Event-family repeat narrow-context HER rows: {hard.get('eventFamilyRepeatNarrowContextHardEvidenceReviewRows', 0)}",
        f"- CEX/bridge proxy-only HER rows: {hard.get('cexBridgeProxyOnlyHardEvidenceReviewRows', 0)}",
        f"- High-impact-repricing-only HER rows: {hard.get('highImpactRepricingOnlyHardEvidenceReviewRows', 0)}",
        "",
        "HER by hardEvidenceSources:",
        *_render_counter(hard.get("hardEvidenceReviewRowsByHardEvidenceSources") or {}, limit=20),
        "",
        "HER invalid condition counts:",
        *_render_counter(hard.get("hardInvalidConditionCounts") or {}, limit=20),
        "",
        "## Target Family And Cache Interpretation",
        "",
        f"- Classification: {target.get('classification', '')}",
        f"- Targets: {target.get('targetCount', 0)}",
        f"- Fresh-rerunnable targets: {target.get('freshRerunnableTargets', 0)}",
        f"- Audit-only targets: {target.get('auditOnlyTargets', 0)}",
        f"- Cache-only targets: {target.get('cacheOnlyTargets', 0)}",
        f"- Network-blocked targets: {target.get('networkBlockedTargets', 0)}",
        f"- One family dominates counts: {target.get('oneFamilyDominatesCounts', False)}",
        f"- Cache-only limits conclusions: {target.get('cacheOnlyLimitsConclusions', False)}",
        "",
        "Target tags:",
        *_render_counter(target.get("targetCountByTag") or {}, limit=30),
        "",
        "Top Strong Risk targets:",
        *_render_counter(target.get("strongRiskRowsByTarget") or {}, limit=10),
        "",
        "Top HER targets:",
        *_render_counter(target.get("hardEvidenceReviewRowsByTarget") or {}, limit=10),
        "",
        "## Stratified Examples",
        "",
    ]
    examples = summary.get("stratifiedExamples") if isinstance(summary.get("stratifiedExamples"), Mapping) else {}
    for key, value in examples.items():
        lines.append(f"### {key}")
        if isinstance(value, Mapping):
            if not value:
                lines.append("- none")
            for source, packets in value.items():
                lines.append(f"- {source}: {len(packets) if isinstance(packets, list) else 0} packet(s)")
        elif isinstance(value, list):
            if not value:
                lines.append("- none")
            for packet in value[:5]:
                if not isinstance(packet, Mapping):
                    continue
                lines.append(
                    "- "
                    f"{packet.get('tradeId', 'unknown')} | {packet.get('wallet', '')} | "
                    f"{packet.get('score', '')} | {packet.get('shortSavedFieldRationale', '')}"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(summary: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    output_dir = _resolve_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"corpus_provenance_drilldown_{stamp}.json"
    markdown_path = output_dir / f"corpus_provenance_drilldown_{stamp}.md"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    markdown_path.write_text(render_markdown(summary), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Produce a read-only provenance drilldown for a validation corpus.")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path)
    parser.add_argument("--recall", type=Path)
    parser.add_argument("--consistency", type=Path)
    parser.add_argument("--public-rpc-limit", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    summary = build_drilldown(
        corpus_path=args.corpus,
        acceptance_path=args.acceptance,
        recall_path=args.recall,
        consistency_path=args.consistency,
        public_rpc_limit_path=args.public_rpc_limit,
    )
    outputs = write_outputs(summary, args.output_dir)
    print(f"Corpus provenance drilldown JSON: {outputs['json_path']}")
    print(f"Corpus provenance drilldown markdown: {outputs['markdown_path']}")
    print(f"Final recommendation: {summary.get('finalRecommendation', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
