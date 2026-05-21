from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.corpus_provenance_drilldown import (  # noqa: E402
    DEFAULT_OUTPUT_DIR as DEFAULT_CORPUS_OUTPUT_DIR,
    _collect_rows,
    _counter_dict,
    _hard_invalid_flags,
    _load_json,
    _resolve_path,
    _selected_paths_from_corpus,
)
from tools.model_behavior_audit import collect_records, normalize_record  # noqa: E402
from tools.report_dedupe import (  # noqa: E402
    build_count_hygiene_summary,
    count_hygiene_warnings,
    dedupe_key,
    dedupe_summary,
    unique_records,
)


DEFAULT_OUTPUT_DIR = Path("strong_risk_diagnostic_outputs")
RECOMMENDATIONS = (
    "no_gate_change_needed_source_attribution_clear",
    "source_attribution_repair_needed",
    "dedupe_inflation_repair_needed",
    "strong_risk_gate_review_needed",
    "strong_risk_timing_repricing_gate_review_needed",
    "strong_risk_retrospective_gate_review_needed",
    "saved_fields_insufficient_rerun_with_trace_needed",
    "corpus_too_cache_only_for_gate_decision",
)


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _score(record: Mapping[str, Any]) -> float:
    for key in ("score", "event_forensic_score", "existing_model_score"):
        value = record.get(key)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _opening_status(record: Mapping[str, Any]) -> str:
    return str(
        record.get("strong_risk_opening_exposure_status")
        or ("confirmed" if record.get("opening_exposure_confirmed") else "unknown")
    )


def _target_family(record: Mapping[str, Any]) -> str:
    tags = [str(tag) for tag in record.get("target_tags") or []]
    if "sports_crypto" in tags:
        return "sports_crypto"
    if "politics_world" in tags:
        return "politics_world"
    if "archive" in tags:
        return "archive"
    if "event_forensic" in tags:
        return "event_forensic"
    return str(record.get("target_mode") or "unknown")


def _packet(record: Mapping[str, Any]) -> dict[str, Any]:
    raw = record.get("_raw_record") if isinstance(record.get("_raw_record"), Mapping) else {}
    return {
        "target": record.get("target_label", "unknown"),
        "sourcePath": record.get("source_path", ""),
        "dedupeKey": record.get("dedupe_key") or dedupe_key(record)[0],
        "wallet": record.get("wallet", ""),
        "conditionId": record.get("condition_id", ""),
        "market": record.get("market_title") or raw.get("market") or raw.get("question") or "",
        "tradeId": record.get("row_id", ""),
        "timestamp": raw.get("timestamp") or raw.get("tradeTimestamp") or raw.get("createdAt") or "",
        "notional": raw.get("notionalUsd") or raw.get("notional_usd") or raw.get("notional") or "",
        "score": _score(record),
        "severity": record.get("severity", ""),
        "judgment": record.get("judgment", ""),
        "hardEvidenceSources": record.get("hard_evidence_sources") or [],
        "gateFamily": record.get("strong_risk_gate_family", "unknown"),
        "gateName": record.get("strong_risk_gate_name", "unknown"),
        "gateTraceAvailable": bool(record.get("strong_risk_gate_trace_available")),
        "hasIndependentHardEvidence": bool(record.get("strong_risk_has_independent_hard_evidence")),
        "independentEvidenceSources": record.get("strong_risk_independent_evidence_sources") or [],
        "suppressors": record.get("suppressors") or [],
        "suppressorConflict": bool(record.get("strong_risk_suppressor_conflict")),
        "openingExposureStatus": _opening_status(record),
        "repricingSourceQuality": record.get("repricing_source_quality", "unknown"),
        "fundingEvidenceGrade": record.get("funding_evidence_grade", "unknown"),
        "timingRepricingOnly": bool(record.get("strong_risk_timing_repricing_only")),
        "retrospectiveOnly": bool(record.get("strong_risk_retrospective_only")),
        "scoreOnly": bool(record.get("strong_risk_score_only")),
    }


def _potential_gate_leakage(record: Mapping[str, Any]) -> bool:
    if not record.get("strong_risk"):
        return False
    if record.get("hard_evidence_sources"):
        return False
    if record.get("strong_risk_has_independent_hard_evidence"):
        return False
    suppressors = set(record.get("suppressors") or [])
    opening_not_confirmed = _opening_status(record) not in {"confirmed", "yes"}
    return bool(
        record.get("strong_risk_timing_repricing_only")
        or record.get("strong_risk_score_only")
        or opening_not_confirmed
        or suppressors.intersection(
            {
                "near_certainty",
                "stale_or_resolution_gap",
                "hard_resolution_gap",
                "high_volume_public_user",
                "domain_specialist",
            }
        )
    )


def _rows_from_inputs(*, corpus_path: Path | None, input_paths: Sequence[Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    corpus = _load_json(corpus_path) if corpus_path else {}
    if corpus:
        rows, missing = _collect_rows(corpus)
        return rows, {"corpus": str(corpus_path), "selectedPaths": [str(path) for path in _selected_paths_from_corpus(corpus)], "missing": missing}
    selected = [_resolve_path(path) for path in input_paths]
    raw_records = collect_records(selected)
    rows: list[dict[str, Any]] = []
    for raw in raw_records:
        record = normalize_record(raw)
        record["_raw_record"] = raw
        record["target_label"] = Path(str(record.get("source_path") or "")).parent.name or "input"
        record["target_tags"] = []
        key, key_source = dedupe_key(record)
        record["dedupe_key"] = key
        record["dedupe_key_source"] = key_source
        rows.append(record)
    return rows, {"corpus": "", "selectedPaths": [str(path) for path in selected], "missing": [str(path) for path in selected if not path.exists()]}


def _recommend(summary: Mapping[str, Any]) -> str:
    raw = int(summary.get("rawStrongRiskRows") or 0)
    if not raw:
        return "no_gate_change_needed_source_attribution_clear"
    without_trace = int(summary.get("strongRiskRowsWithoutGateTrace") or 0)
    if without_trace / raw > 0.5:
        return "saved_fields_insufficient_rerun_with_trace_needed"
    duplication = summary.get("deduplication") if isinstance(summary.get("deduplication"), Mapping) else {}
    unique_rows = int(summary.get("uniqueStrongRiskRows") or 0)
    if unique_rows and (raw - unique_rows) / raw >= 0.2:
        return "dedupe_inflation_repair_needed"
    if int(summary.get("strongRiskIndependentEvidenceMissingHardSources") or 0):
        return "source_attribution_repair_needed"
    timing_only = int((summary.get("strongRiskByTimingRepricingOnly") or {}).get("true") or 0)
    if timing_only / raw > 0.5:
        return "strong_risk_timing_repricing_gate_review_needed"
    retrospective_only = int((summary.get("strongRiskByRetrospectiveOnly") or {}).get("true") or 0)
    retro_suppressed = int(summary.get("retrospectiveOnlyWithSuppressors") or 0)
    if retrospective_only / raw > 0.5 and retro_suppressed:
        return "strong_risk_retrospective_gate_review_needed"
    if int(summary.get("potentialGateLeakageCandidateRows") or 0):
        return "strong_risk_gate_review_needed"
    return "no_gate_change_needed_source_attribution_clear"


def build_diagnostic(
    *,
    corpus_path: Path | None = None,
    input_paths: Sequence[Path] = (),
    drilldown_path: Path | None = None,
) -> dict[str, Any]:
    rows, input_summary = _rows_from_inputs(corpus_path=corpus_path, input_paths=input_paths)
    drilldown = _load_json(drilldown_path) if drilldown_path else {}
    strong_rows = [record for record in rows if record.get("strong_risk")]
    unique_strong = list(unique_records(strong_rows))
    duplicate_summary = dedupe_summary(strong_rows, row_type="StrongRisk")
    count_hygiene = build_count_hygiene_summary(rows)
    potential = [record for record in strong_rows if _potential_gate_leakage(record)]
    manual = sorted(
        strong_rows,
        key=lambda record: (
            not record.get("strong_risk_gate_trace_available"),
            bool(record.get("strong_risk_suppressor_conflict")),
            _score(record),
        ),
        reverse=True,
    )[:25]

    by_gate_family = Counter(str(record.get("strong_risk_gate_family") or "unknown") for record in strong_rows)
    by_gate_name = Counter(str(record.get("strong_risk_gate_name") or record.get("strong_risk_exact_gate_branch") or "unknown") for record in strong_rows)
    by_support = Counter("true" if record.get("strong_risk_has_independent_hard_evidence") else "false" for record in strong_rows)
    by_suppressor = Counter("true" if record.get("strong_risk_suppressor_conflict") else "false" for record in strong_rows)
    by_opening = Counter(_opening_status(record) for record in strong_rows)
    by_repricing = Counter(str(record.get("repricing_source_quality") or "unknown") for record in strong_rows)
    by_funding = Counter(str(record.get("funding_evidence_grade") or "unknown") for record in strong_rows)
    by_family = Counter(_target_family(record) for record in strong_rows)
    by_timing_only = Counter("true" if record.get("strong_risk_timing_repricing_only") else "false" for record in strong_rows)
    by_retrospective = Counter("true" if record.get("strong_risk_retrospective_only") else "false" for record in strong_rows)
    by_score_only = Counter("true" if record.get("strong_risk_score_only") else "false" for record in strong_rows)
    independent_missing_hard = [
        record
        for record in strong_rows
        if record.get("strong_risk_has_independent_hard_evidence")
        and not record.get("hard_evidence_sources")
    ]
    retrospective_suppressed = [
        record
        for record in strong_rows
        if record.get("strong_risk_retrospective_only") and record.get("suppressors")
    ]

    target_status = Counter(str(record.get("target_status") or "unknown") for record in rows)
    target_status_by_label: dict[str, str] = {}
    for record in rows:
        label = str(record.get("target_label") or "unknown")
        target_status_by_label.setdefault(label, str(record.get("target_status") or "unknown"))
    summary: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "inputArtifacts": input_summary,
        "drilldownArtifact": str(drilldown_path or ""),
        "drilldownRecommendation": drilldown.get("finalRecommendation", ""),
        "totalRowsInspected": len(rows),
        "rawStrongRiskRows": len(strong_rows),
        "uniqueStrongRiskRows": len(unique_strong),
        "strongRiskDedupeRatio": duplicate_summary.get("strongRiskDuplicationRatio", 0),
        "rawVisibleRows": count_hygiene["rawVisibleRows"],
        "uniqueVisibleRows": count_hygiene["uniqueVisibleRows"],
        "visibleDedupeRatio": count_hygiene["visibleDedupeRatio"],
        "rawHardEvidenceReviewRows": count_hygiene["rawHardEvidenceReviewRows"],
        "uniqueHardEvidenceReviewRows": count_hygiene["uniqueHardEvidenceReviewRows"],
        "hardEvidenceReviewDedupeRatio": count_hygiene["hardEvidenceReviewDedupeRatio"],
        "deduplication": duplicate_summary,
        "countHygiene": count_hygiene,
        "countHygieneWarnings": count_hygiene_warnings(count_hygiene),
        "topDuplicateHardEvidenceReviewKeys": count_hygiene["topDuplicateHardEvidenceReviewKeys"],
        "topDuplicateTargets": count_hygiene["topDuplicateTargets"],
        "strongRiskRowsWithGateTraceAvailable": sum(1 for record in strong_rows if record.get("strong_risk_gate_trace_available")),
        "strongRiskRowsWithoutGateTrace": sum(1 for record in strong_rows if not record.get("strong_risk_gate_trace_available")),
        "strongRiskByGateFamily": _counter_dict(by_gate_family),
        "strongRiskByGateName": _counter_dict(by_gate_name),
        "strongRiskByEvidenceSupport": _counter_dict(by_support),
        "strongRiskBySuppressorConflict": _counter_dict(by_suppressor),
        "strongRiskByOpeningExposureStatus": _counter_dict(by_opening),
        "strongRiskByRepricingSourceQuality": _counter_dict(by_repricing),
        "strongRiskByFundingEvidenceGrade": _counter_dict(by_funding),
        "strongRiskByTargetFamily": _counter_dict(by_family),
        "strongRiskByTimingRepricingOnly": _counter_dict(by_timing_only),
        "strongRiskByRetrospectiveOnly": _counter_dict(by_retrospective),
        "strongRiskByScoreOnly": _counter_dict(by_score_only),
        "strongRiskIndependentEvidenceMissingHardSources": len(independent_missing_hard),
        "retrospectiveOnlyWithSuppressors": len(retrospective_suppressed),
        "potentialGateLeakageCandidateRows": len(potential),
        "targetCount": len(target_status_by_label),
        "cacheOnlyTargets": sum(1 for status in target_status_by_label.values() if status == "completed_cache_only"),
        "targetStatusDistribution": _counter_dict(target_status),
        "topManualInspectionRows": [_packet(record) for record in manual],
        "topDuplicatedStrongRiskKeys": duplicate_summary.get("topDuplicateKeys", [])[:25],
        "topPotentialGateLeakageCandidates": [_packet(record) for record in sorted(potential, key=_score, reverse=True)[:25]],
        "hardInvalidConditionCounts": _counter_dict(Counter(flag for record in rows for flag in _hard_invalid_flags(record))),
        "allowedRecommendations": list(RECOMMENDATIONS),
    }
    summary["recommendation"] = _recommend(summary)
    return summary


def render_markdown(summary: Mapping[str, Any]) -> str:
    def counter_lines(counter: Mapping[str, Any], limit: int = 20) -> list[str]:
        items = sorted(counter.items(), key=lambda item: (-int(item[1] or 0), str(item[0])))[:limit]
        return [f"  - {key}: {value}" for key, value in items] or ["  - none: 0"]

    lines = [
        "# Strong Risk Gate Diagnostic",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Recommendation: {summary.get('recommendation', '')}",
        f"- Total rows inspected: {summary.get('totalRowsInspected', 0)}",
        f"- Strong Risk rows: {summary.get('rawStrongRiskRows', 0)} raw / {summary.get('uniqueStrongRiskRows', 0)} unique (dedupe ratio {summary.get('strongRiskDedupeRatio', 0)})",
        f"- Hard Evidence Review rows: {summary.get('rawHardEvidenceReviewRows', 0)} raw / {summary.get('uniqueHardEvidenceReviewRows', 0)} unique (dedupe ratio {summary.get('hardEvidenceReviewDedupeRatio', 0)})",
        f"- Strong Risk rows with gate trace: {summary.get('strongRiskRowsWithGateTraceAvailable', 0)}",
        f"- Strong Risk rows without gate trace: {summary.get('strongRiskRowsWithoutGateTrace', 0)}",
        f"- Potential gate-leakage candidates: {summary.get('potentialGateLeakageCandidateRows', 0)}",
        "",
        "## Gate Families",
        *counter_lines(summary.get("strongRiskByGateFamily") or {}),
        "",
        "## Gate Names",
        *counter_lines(summary.get("strongRiskByGateName") or {}),
        "",
        "## Evidence And Suppressors",
        "",
        "Independent hard evidence support:",
        *counter_lines(summary.get("strongRiskByEvidenceSupport") or {}),
        "",
        "Suppressor conflict:",
        *counter_lines(summary.get("strongRiskBySuppressorConflict") or {}),
        "",
        "Opening exposure:",
        *counter_lines(summary.get("strongRiskByOpeningExposureStatus") or {}),
        "",
        "Repricing quality:",
        *counter_lines(summary.get("strongRiskByRepricingSourceQuality") or {}),
        "",
        "Funding grade:",
        *counter_lines(summary.get("strongRiskByFundingEvidenceGrade") or {}),
        "",
        "## Duplicates",
        "",
        "Top duplicate Strong Risk keys:",
        *([
            f"  - {item.get('count', 0)}x {item.get('dedupeKey', '')}"
            for item in (summary.get("topDuplicatedStrongRiskKeys") or [])[:25]
        ] or ["  - none: 0"]),
        "",
        "## Potential Gate-Leakage Packets",
    ]
    packets = summary.get("topPotentialGateLeakageCandidates") or []
    if not packets:
        lines.append("- none")
    for packet in packets[:25]:
        if not isinstance(packet, Mapping):
            continue
        lines.append(
            "- "
            f"{packet.get('tradeId', 'unknown')} | {packet.get('wallet', '')} | "
            f"{packet.get('gateFamily', '')}/{packet.get('gateName', '')} | "
            f"score={packet.get('score', '')} | suppressors={';'.join(packet.get('suppressors') or [])}"
        )
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(summary: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    output_dir = _resolve_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"strong_risk_gate_diagnostic_{stamp}.json"
    markdown_path = output_dir / f"strong_risk_gate_diagnostic_{stamp}.md"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    markdown_path.write_text(render_markdown(summary), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Strong Risk gate provenance diagnostic.")
    parser.add_argument("inputs", nargs="*", type=Path, help="Saved output files/directories to inspect when --corpus is omitted.")
    parser.add_argument("--corpus", type=Path, help="Validation corpus JSON to inspect.")
    parser.add_argument("--drilldown", type=Path, help="Optional corpus provenance drilldown JSON for context.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    if not args.corpus and not args.inputs:
        latest = sorted(DEFAULT_CORPUS_OUTPUT_DIR.glob("post_v2_corpus_*.json"))
        if latest:
            args.corpus = latest[-1]
    summary = build_diagnostic(corpus_path=args.corpus, input_paths=args.inputs, drilldown_path=args.drilldown)
    outputs = write_outputs(summary, args.output_dir)
    print(f"Strong Risk gate diagnostic JSON: {outputs['json_path']}")
    print(f"Strong Risk gate diagnostic markdown: {outputs['markdown_path']}")
    print(f"Recommendation: {summary.get('recommendation', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
