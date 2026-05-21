from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.candidate_recall_audit import summarize_candidate_recall

DEFAULT_VALIDATION_OUTPUT_DIR = Path("validation_corpus_outputs")
DEFAULT_REVIEW_PACKET_DIR = Path("review_packets")
DEFAULT_FALSE_POSITIVE_DIR = Path("false_positive_library")
DEFAULT_QUALITY_DIR = Path("analyst_quality_outputs")
DEFAULT_SCHEMA_DIR = Path("source_schema_repair_outputs")
DEFAULT_OUTPUT_DIR = Path("candidate_recall_outputs")


def _resolve(path: str | Path | None) -> Path | None:
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
    candidates.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return candidates[0] if candidates else None


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def discover_inputs() -> dict[str, Path | None]:
    return {
        "corpus": _latest_file(DEFAULT_VALIDATION_OUTPUT_DIR, "post_v2_corpus_*.json", exclude=("_audit_", "network_probe")),
        "review_packets": _latest_file(DEFAULT_REVIEW_PACKET_DIR, "unique_review_packets_*.json"),
        "false_positive_library": _latest_file(DEFAULT_FALSE_POSITIVE_DIR, "false_positive_pattern_library_*.json"),
        "packet_quality_report": _latest_file(DEFAULT_QUALITY_DIR, "packet_quality_report_*.json"),
        "gate_trace_availability_audit": _latest_file(DEFAULT_SCHEMA_DIR, "gate_trace_availability_audit_*.json"),
        "false_positive_explanation_report": _latest_file(
            DEFAULT_FALSE_POSITIVE_DIR, "false_positive_explanation_report_*.json"
        ),
    }


def _string(value: Any) -> str:
    return str(value or "").strip()


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    return [value]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "confirmed"}


def _packet_quality_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("packetQualityRows")
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _review_packet_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    packets = payload.get("packets")
    if not isinstance(packets, list):
        return []
    rows = []
    for packet in packets:
        if not isinstance(packet, Mapping):
            continue
        group = _string(packet.get("group")).lower()
        false_positive_matches = []
        for item in _listify(packet.get("false_positive_advisory")):
            if isinstance(item, Mapping):
                false_positive_matches.append(
                    {
                        "pattern": _string(item.get("pattern")),
                        "message": _string(item.get("message")),
                        "analystQuestion": _string(item.get("analyst_question") or item.get("analystQuestion")),
                    }
                )
        rows.append(
            {
                "packetId": packet.get("packet_id", "unknown"),
                "wallet": packet.get("wallet", "unknown"),
                "marketOrEvent": packet.get("market") or packet.get("target") or "unknown",
                "strongRiskFlag": group in {"strong_risk", "overlap"},
                "hardEvidenceReviewFlag": group in {"hard_evidence_review", "overlap"},
                "overlapFlag": group == "overlap",
                "cacheOnlyWarning": "Funding/source context is unavailable." if packet.get("funding_evidence_grade") == "unknown" else "",
                "retrospectiveOnlyWarning": "Retrospective-only evidence." if _truthy(packet.get("retrospective_only")) else "",
                "sourceAttributionWarning": "Gate/source attribution is incomplete."
                if packet.get("gate_trace_available") is False
                else "",
                "falsePositiveAdvisoryMatches": false_positive_matches,
                "dedupeGroupSize": packet.get("dedupe_group_size", 1),
                "analystPriority": "unranked",
            }
        )
    return rows


def _first_rows(rows: Sequence[Mapping[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    samples = []
    for row in rows[:limit]:
        samples.append(
            {
                "packetId": _string(row.get("packetId")) or "unknown",
                "wallet": _string(row.get("wallet")) or "unknown",
                "marketOrEvent": _string(row.get("marketOrEvent")) or "unknown",
                "analystPriority": _string(row.get("analystPriority")) or "unknown",
                "strongRiskFlag": bool(row.get("strongRiskFlag")),
                "hardEvidenceReviewFlag": bool(row.get("hardEvidenceReviewFlag")),
                "overlapFlag": bool(row.get("overlapFlag")),
                "falsePositivePatterns": [
                    _string(item.get("pattern"))
                    for item in _listify(row.get("falsePositiveAdvisoryMatches"))
                    if isinstance(item, Mapping) and _string(item.get("pattern"))
                ],
            }
        )
    return samples


def _slice(
    slice_id: str,
    label: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    why_matters: str,
    why_insufficient: str,
    fresh_validation_needed: str,
) -> dict[str, Any]:
    return {
        "sliceId": slice_id,
        "label": label,
        "packetCount": len(rows),
        "strongRiskCount": sum(1 for row in rows if row.get("strongRiskFlag")),
        "hardEvidenceReviewCount": sum(1 for row in rows if row.get("hardEvidenceReviewFlag")),
        "overlapCount": sum(1 for row in rows if row.get("overlapFlag")),
        "cacheOnlyOrFundingUnknownCount": sum(1 for row in rows if _string(row.get("cacheOnlyWarning"))),
        "retrospectiveOnlyCount": sum(1 for row in rows if _string(row.get("retrospectiveOnlyWarning"))),
        "gateTraceOrSourceWeakCount": sum(1 for row in rows if _string(row.get("sourceAttributionWarning"))),
        "falsePositiveAdvisoryCount": sum(1 for row in rows if row.get("falsePositiveAdvisoryMatches")),
        "whyMissedOrNearMissMatters": why_matters,
        "whyEvidenceIsInsufficientForRecallChange": why_insufficient,
        "freshValidationNeeded": fresh_validation_needed,
        "automaticRoutingAllowed": False,
        "modelBehaviorChanged": False,
        "samplePackets": _first_rows(rows),
    }


def build_stratified_saved_output_slices(
    *,
    packet_quality_payload: Mapping[str, Any],
    review_packet_payload: Mapping[str, Any],
    audit: Mapping[str, Any],
    gate_trace_payload: Mapping[str, Any],
    false_positive_explanation_payload: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _packet_quality_rows(packet_quality_payload) or _review_packet_rows(review_packet_payload)
    strong = [row for row in rows if row.get("strongRiskFlag")]
    her = [row for row in rows if row.get("hardEvidenceReviewFlag")]
    overlap = [row for row in rows if row.get("overlapFlag")]
    cache_only = [row for row in rows if _string(row.get("cacheOnlyWarning"))]
    retrospective = [row for row in rows if _string(row.get("retrospectiveOnlyWarning"))]
    gate_missing = [row for row in rows if _string(row.get("sourceAttributionWarning"))]
    fp_advisory = [row for row in rows if row.get("falsePositiveAdvisoryMatches")]
    large_dedupe = []
    for row in rows:
        try:
            if int(row.get("dedupeGroupSize") or 0) >= 5:
                large_dedupe.append(row)
        except (TypeError, ValueError):
            continue

    near_miss_groups = int(audit.get("near_miss_groups") or 0)
    funnel_count = int(audit.get("funnel_file_count") or 0)
    gate_summary = gate_trace_payload.get("summary") if isinstance(gate_trace_payload.get("summary"), Mapping) else {}
    fp_summary = (
        false_positive_explanation_payload.get("summary")
        if isinstance(false_positive_explanation_payload.get("summary"), Mapping)
        else {}
    )
    slices = [
        _slice(
            "strong_risk_saved_packets",
            "Saved Strong Risk packets",
            strong,
            why_matters="These are current high-priority saved leads and define what recall expansion must not dilute.",
            why_insufficient="Saved Strong Risk rows are not false negatives; they are reference positives and may be cache-only.",
            fresh_validation_needed="Use fresh trace-enabled rows before comparing missed cases against this baseline.",
        ),
        _slice(
            "hard_evidence_review_saved_packets",
            "Saved Hard Evidence Review packets",
            her,
            why_matters="HER packets show accepted evidence-routing material already visible to analysts.",
            why_insufficient="HER visibility does not prove broader recall is missing; it only shows current review material.",
            fresh_validation_needed="Fresh rows with accepted HER sources and zero invalid conditions are needed before routing changes.",
        ),
        _slice(
            "strong_risk_her_overlap",
            "Strong Risk and HER overlap packets",
            overlap,
            why_matters="Overlap packets are useful precision anchors when present.",
            why_insufficient="A zero or small overlap count is not recall failure by itself in saved-output-only evidence.",
            fresh_validation_needed="Fresh trace-enabled overlap cases are needed before changing gates or HER routing.",
        ),
        _slice(
            "cache_only_or_funding_unknown",
            "Cache-only or funding-unknown packets",
            cache_only,
            why_matters="These packets explain why recall/gate conclusions remain blocked by RPC/funding evidence.",
            why_insufficient="Unknown funding cannot be treated as no funding or as suspicious funding.",
            fresh_validation_needed="Operator-approved RPC capacity and successful bounded prewarm/smoke validation.",
        ),
        _slice(
            "retrospective_only",
            "Retrospective-only packets",
            retrospective,
            why_matters="Retrospective correctness helps audit saved output quality but can overstate live detectability.",
            why_insufficient="Outcome-known evidence cannot justify broader live recall without live-detectable support.",
            fresh_validation_needed="Fresh live/fresh-rerunnable rows with explicit pre-outcome signals.",
        ),
        _slice(
            "gate_trace_or_source_weak",
            "Gate trace or source attribution weak packets",
            gate_missing,
            why_matters="Missing gate/source traces make it hard to compare included and missed candidates.",
            why_insufficient="A missing display/source field is a schema/readiness issue, not proof of recall failure.",
            fresh_validation_needed="Repair/report field propagation and rerun diagnostics; then use fresh trace-enabled validation.",
        ),
        _slice(
            "false_positive_advisory",
            "Packets with false-positive advisory matches",
            fp_advisory,
            why_matters="These rows identify where recall expansion could increase noise if treated as production evidence.",
            why_insufficient="Advisory patterns are analyst cautions only and cannot suppress or admit candidates automatically.",
            fresh_validation_needed="Human-reviewed labels and fresh validation before any suppressor/recall proposal.",
        ),
        _slice(
            "large_dedupe_groups",
            "Large dedupe-group packets",
            large_dedupe,
            why_matters="Duplicate-inflated rows can make saved evidence look broader than it is.",
            why_insufficient="Dedupe is reporting-only and cannot remove production rows or justify recall changes.",
            fresh_validation_needed="Unique-row, trace-enabled review packets before measuring recall/precision.",
        ),
    ]
    if near_miss_groups:
        slices.append(
            {
                "sliceId": "candidate_funnel_near_misses",
                "label": "Candidate-funnel near misses",
                "packetCount": near_miss_groups,
                "strongRiskCount": 0,
                "hardEvidenceReviewCount": 0,
                "overlapCount": 0,
                "cacheOnlyOrFundingUnknownCount": int(audit.get("near_miss_groups_funding_not_assessable") or 0),
                "retrospectiveOnlyCount": 0,
                "gateTraceOrSourceWeakCount": 0,
                "falsePositiveAdvisoryCount": 0,
                "whyMissedOrNearMissMatters": "Candidate funnel near misses can identify possible false negatives.",
                "whyEvidenceIsInsufficientForRecallChange": "Near misses remain diagnostic-only until deduped, source-traced, and human-reviewed.",
                "freshValidationNeeded": "Fresh candidate funnel files with funding-enabled targets and unique-wallet review.",
                "automaticRoutingAllowed": False,
                "modelBehaviorChanged": False,
                "samplePackets": [],
            }
        )
    else:
        slices.append(
            {
                "sliceId": "candidate_funnel_absent_or_empty",
                "label": "Candidate funnel absent or empty",
                "packetCount": 0,
                "strongRiskCount": 0,
                "hardEvidenceReviewCount": 0,
                "overlapCount": 0,
                "cacheOnlyOrFundingUnknownCount": 0,
                "retrospectiveOnlyCount": 0,
                "gateTraceOrSourceWeakCount": 0,
                "falsePositiveAdvisoryCount": 0,
                "whyMissedOrNearMissMatters": "The saved outputs do not expose enough candidate-funnel near misses for recall expansion.",
                "whyEvidenceIsInsufficientForRecallChange": "Without funnel files, this diagnostic cannot prove which candidates were missed.",
                "freshValidationNeeded": "Fresh validation runs that write candidate admission funnels.",
                "automaticRoutingAllowed": False,
                "modelBehaviorChanged": False,
                "samplePackets": [],
            }
        )

    return {
        "summary": {
            "slice_count": len(slices),
            "packet_rows_inspected": len(rows),
            "candidate_funnel_file_count": funnel_count,
            "candidate_funnel_near_miss_groups": near_miss_groups,
            "gate_trace_missing_packets": gate_summary.get("strongRiskGateTraceMissingCount", 0),
            "false_positive_explanation_patterns": fp_summary.get("patternCount", 0),
            "false_positive_packet_matches": fp_summary.get("totalPacketPatternMatches", 0),
            "model_behavior_changed": False,
            "routing_changed": False,
            "candidate_admission_changed": False,
        },
        "slices": slices,
    }


def build_candidate_recall_diagnostic(corpus_path: Path | None = None) -> dict[str, Any]:
    paths = discover_inputs()
    if corpus_path:
        paths["corpus"] = _resolve(corpus_path)
    audit = summarize_candidate_recall([paths["corpus"]]) if paths.get("corpus") else summarize_candidate_recall([])
    review_packets = _load_json(paths.get("review_packets"))
    packet_summary = review_packets.get("summary") if isinstance(review_packets.get("summary"), Mapping) else {}
    false_positive = _load_json(paths.get("false_positive_library"))
    false_positive_summary = false_positive.get("summary") if isinstance(false_positive.get("summary"), Mapping) else {}
    packet_quality = _load_json(paths.get("packet_quality_report"))
    gate_trace_audit = _load_json(paths.get("gate_trace_availability_audit"))
    false_positive_explanation = _load_json(paths.get("false_positive_explanation_report"))
    retrospective_summary = (
        review_packets.get("retrospective_summary")
        if isinstance(review_packets.get("retrospective_summary"), Mapping)
        else {}
    )
    stratified = build_stratified_saved_output_slices(
        packet_quality_payload=packet_quality,
        review_packet_payload=review_packets,
        audit=audit,
        gate_trace_payload=gate_trace_audit,
        false_positive_explanation_payload=false_positive_explanation,
    )
    classification = audit.get("classification", "unknown")
    if classification == "funding coverage issue":
        diagnostic_interpretation = "candidate_recall_blocked_by_funding_coverage"
    elif classification == "rules too strict but requires human approval":
        diagnostic_interpretation = "candidate_recall_rfc_only_if_owner_approves"
    elif classification == "admission schema bug":
        diagnostic_interpretation = "candidate_recall_schema_investigation_needed"
    else:
        diagnostic_interpretation = "no_recall_change_indicated_from_saved_outputs"

    summary = {
        "diagnostic_interpretation": diagnostic_interpretation,
        "audit_classification": classification,
        "fresh_validation_required": True,
        "funnel_file_count": audit.get("funnel_file_count", 0),
        "near_miss_groups": audit.get("near_miss_groups", 0),
        "stratified_slice_count": stratified["summary"]["slice_count"],
        "packet_rows_inspected": stratified["summary"]["packet_rows_inspected"],
        "cache_only_or_funding_unknown_packets": retrospective_summary.get("funding_unknown_packets", 0),
        "retrospective_only_packets": retrospective_summary.get("retrospective_only_packets", 0),
        "gate_trace_missing_packets": retrospective_summary.get("gate_trace_missing_packets", 0),
        "false_positive_packet_matches": stratified["summary"].get("false_positive_packet_matches", 0),
        "model_behavior_changed": False,
        "scoring_changed": False,
        "gates_changed": False,
        "her_routing_changed": False,
        "funding_eligibility_changed": False,
        "candidate_admission_changed": False,
        "automatic_routing_allowed": False,
    }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "input_paths": {key: str(value) if value else "" for key, value in paths.items()},
        "audit": audit,
        "review_packet_context": {
            "unique_packet_count": packet_summary.get("unique_packet_count", 0),
            "strong_risk_packets": packet_summary.get("strong_risk_packets", 0),
            "hard_evidence_review_packets": packet_summary.get("hard_evidence_review_packets", 0),
        },
        "false_positive_context": {
            "pattern_count": false_positive_summary.get("pattern_count", 0),
            "likely_false_positive_examples": false_positive_summary.get("case_reviewer_likely_false_positive_examples", 0),
            "top_patterns": false_positive_summary.get("top_patterns", [])[:8],
        },
        "near_miss_visibility": {
            "near_miss_groups": audit.get("near_miss_groups", 0),
            "grouped_subthreshold_groups": audit.get("grouped_subthreshold_groups", 0),
            "subthreshold_above_floor_trades": audit.get("subthreshold_above_floor_trades", 0),
            "rejected_after_scoring": audit.get("rejected_after_scoring", 0),
            "near_miss_groups_funding_not_assessable": audit.get("near_miss_groups_funding_not_assessable", 0),
            "funnel_file_count": audit.get("funnel_file_count", 0),
            "top_non_admission_reasons": audit.get("top_non_admission_reasons", {}),
            "saved_review_packet_limitations": {
                "retrospective_only_packets": retrospective_summary.get("retrospective_only_packets", 0),
                "gate_trace_missing_packets": retrospective_summary.get("gate_trace_missing_packets", 0),
                "funding_unknown_packets": retrospective_summary.get("funding_unknown_packets", 0),
                "live_detectable_unknown_packets": retrospective_summary.get("live_detectable_unknown_packets", 0),
            },
            "diagnostic_quality": (
                "limited_no_candidate_funnel_files"
                if not audit.get("funnel_file_count")
                else "candidate_funnel_files_available"
            ),
        },
        "stratified_saved_output_recall": stratified,
        "recall_triage_guidance": [
            "Use Strong Risk and HER slices as current saved-output baselines, not as false-negative proof.",
            "Use cache-only, retrospective-only, gate-trace-missing, and false-positive advisory slices to explain why recall changes are not production-ready.",
            "Treat candidate-funnel near misses as diagnostic-only until fresh trace-enabled validation writes complete funnel files.",
            "Do not broaden routing, admission, scoring, gates, HER eligibility, or funding eligibility from this saved-output report.",
        ],
        "diagnostic_interpretation": diagnostic_interpretation,
        "safe_next_step": {
            "no_recall_change_indicated_from_saved_outputs": "Continue analyst-quality diagnostics; no recall/routing change is indicated.",
            "candidate_recall_blocked_by_funding_coverage": "Improve funding/RPC coverage before recall interpretation.",
            "candidate_recall_rfc_only_if_owner_approves": "Prepare an RFC-only recall review; do not change routing.",
            "candidate_recall_schema_investigation_needed": "Inspect schema/export paths before changing admission rules.",
        }[diagnostic_interpretation],
        "limitations": [
            "This diagnostic reads saved local artifacts only.",
            "It does not broaden recall, change routing, or lower thresholds.",
            "Cache-only evidence cannot support production recall changes.",
            "False-positive advisory patterns are manual review cautions only and do not suppress or admit candidates.",
        ],
        "fresh_validation_requirements_before_recall_change": [
            "fresh-rerunnable corpus output with funding-enabled targets above zero",
            "candidate admission funnel files available for inspected targets",
            "near-miss examples deduped to unique wallets/markets",
            "human-approved RFC before any routing, gate, threshold, or scoring change",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    audit = payload.get("audit") if isinstance(payload.get("audit"), Mapping) else {}
    lines = [
        "# Candidate Recall Diagnostic",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Diagnostic interpretation: `{payload.get('diagnostic_interpretation', '')}`",
        f"- Safe next step: {payload.get('safe_next_step', '')}",
        f"- Audit classification: `{audit.get('classification', '')}`",
        f"- Recommended audit playbook: {audit.get('recommended_next_playbook', '')}",
        f"- Near-miss groups: {audit.get('near_miss_groups', 0)}",
        f"- Grouped sub-threshold groups: {audit.get('grouped_subthreshold_groups', 0)}",
        f"- Validated pre-admissions: {audit.get('validated_pre_admissions', 0)}",
        f"- Funding-not-assessable near misses: {audit.get('near_miss_groups_funding_not_assessable', 0)}",
        "",
        "## Review Packet Context",
    ]
    for key, value in (payload.get("review_packet_context") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## False-Positive Context"])
    for key, value in (payload.get("false_positive_context") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Near-Miss Visibility"])
    for key, value in (payload.get("near_miss_visibility") or {}).items():
        lines.append(f"- {key}: {value}")
    stratified = payload.get("stratified_saved_output_recall") if isinstance(payload.get("stratified_saved_output_recall"), Mapping) else {}
    stratified_summary = stratified.get("summary") if isinstance(stratified.get("summary"), Mapping) else {}
    lines.extend(
        [
            "",
            "## Stratified Saved-Output Recall Slices",
            f"- Slice count: {stratified_summary.get('slice_count', 0)}",
            f"- Packet rows inspected: {stratified_summary.get('packet_rows_inspected', 0)}",
            f"- Candidate funnel files: {stratified_summary.get('candidate_funnel_file_count', 0)}",
        ]
    )
    for item in stratified.get("slices") or []:
        if not isinstance(item, Mapping):
            continue
        lines.extend(
            [
                f"- `{item.get('sliceId', '')}`: {item.get('label', '')}",
                f"  - packet count: {item.get('packetCount', 0)}",
                f"  - why it matters: {item.get('whyMissedOrNearMissMatters', '')}",
                f"  - why insufficient: {item.get('whyEvidenceIsInsufficientForRecallChange', '')}",
                f"  - fresh validation needed: {item.get('freshValidationNeeded', '')}",
                f"  - automatic routing allowed: {item.get('automaticRoutingAllowed', False)}",
            ]
        )
    lines.extend(["", "## Recall Triage Guidance"])
    for item in payload.get("recall_triage_guidance") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Fresh Validation Required Before Recall Changes"])
    for item in payload.get("fresh_validation_requirements_before_recall_change") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Input Paths"])
    for key, value in (payload.get("input_paths") or {}).items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"candidate_recall_diagnostic_{stamp}.json"
    md_path = resolved / f"candidate_recall_diagnostic_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(md_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a saved-output candidate recall diagnostic.")
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    payload = build_candidate_recall_diagnostic(args.corpus)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Candidate recall diagnostic JSON: {outputs['json_path']}")
    print(f"Candidate recall diagnostic markdown: {outputs['markdown_path']}")
    print(f"Diagnostic interpretation: {payload.get('diagnostic_interpretation', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
