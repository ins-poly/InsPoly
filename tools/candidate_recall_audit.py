from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_OUTPUT_DIR = Path("candidate_recall_audit_outputs")


def _number(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    return int(_number(value))


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _candidate_funnel_from_audit(audit_summary: Mapping[str, Any]) -> Mapping[str, Any]:
    return _as_mapping(audit_summary.get("pre_admission_funnel"))


def _iter_selected_paths(inputs: Iterable[Path]) -> tuple[list[Path], list[Mapping[str, Any]], Mapping[str, Any]]:
    selected: list[Path] = []
    corpus_summaries: list[Mapping[str, Any]] = []
    latest_audit_summary: Mapping[str, Any] = {}
    for path in inputs:
        if not path.exists():
            continue
        if path.is_dir():
            selected.append(path)
            continue
        if path.suffix.lower() != ".json":
            selected.append(path)
            continue
        payload = _read_json(path)
        if isinstance(payload, Mapping) and "selected_output_paths" in payload:
            corpus_summaries.append(payload)
            latest_audit_summary = _as_mapping(payload.get("audit_summary")) or latest_audit_summary
            for selected_path in payload.get("selected_output_paths") or []:
                selected.append(Path(str(selected_path)))
        elif isinstance(payload, Mapping) and "pre_admission_funnel" in payload:
            latest_audit_summary = payload
            selected.append(path)
        else:
            selected.append(path)
    return selected, corpus_summaries, latest_audit_summary


def _load_funnel_files(paths: Iterable[Path]) -> list[Mapping[str, Any]]:
    funnels: list[Mapping[str, Any]] = []
    seen: set[Path] = set()
    for path in paths:
        candidates: list[Path] = []
        if path.is_dir():
            candidates.extend(path.glob("candidate_admission_funnel.json"))
            candidates.extend(path.glob("raw_event_bundle/candidate_admission_funnel.json"))
        elif path.name.endswith("candidate_admission_funnel.json"):
            candidates.append(path)
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen or not candidate.exists():
                continue
            seen.add(resolved)
            try:
                payload = _read_json(candidate)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, Mapping):
                funnels.append(payload)
    return funnels


def _sum_funnel_value(funnels: Iterable[Mapping[str, Any]], *keys: str) -> int:
    total = 0
    for funnel in funnels:
        for key in keys:
            if key in funnel:
                total += _int(funnel.get(key))
                break
    return total


def _rejection_counter(funnels: Iterable[Mapping[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for funnel in funnels:
        reasons = funnel.get("rejectionReasons") or funnel.get("topRejectionReasons") or {}
        if isinstance(reasons, Mapping):
            for reason, count in reasons.items():
                counts[str(reason)] += _int(count)
        for record in funnel.get("records") or []:
            if isinstance(record, Mapping):
                reason = str(record.get("candidateAdmissionRejectedReason") or "").strip()
                if reason:
                    counts[reason] += 1
    return counts


def _classify_recall(summary: Mapping[str, Any]) -> str:
    near_miss = _int(summary.get("near_miss_groups"))
    strict_groups = _int(summary.get("strict_funding_groups_found"))
    attempts = _int(summary.get("structural_pre_admission_attempts"))
    validated = _int(summary.get("validated_pre_admissions"))
    funding_not_assessable = _int(summary.get("near_miss_groups_funding_not_assessable"))
    if strict_groups and attempts == 0:
        return "admission schema bug"
    if funding_not_assessable:
        return "funding coverage issue"
    if near_miss >= 50 and validated == 0:
        return "rules too strict but requires human approval"
    return "no recall opportunity observed"


def summarize_candidate_recall(inputs: Iterable[Path]) -> dict[str, Any]:
    input_paths = list(inputs)
    selected_paths, corpus_summaries, audit_summary = _iter_selected_paths(input_paths)
    funnels = _load_funnel_files(selected_paths)
    audit_funnel = _candidate_funnel_from_audit(audit_summary)
    rejection_counts = _rejection_counter(funnels)
    if not rejection_counts and isinstance(audit_funnel.get("top_rejection_reasons"), Mapping):
        rejection_counts.update({str(k): _int(v) for k, v in audit_funnel["top_rejection_reasons"].items()})

    near_miss_groups = _sum_funnel_value(funnels, "nearMissGroups", "near_miss_groups")
    if not near_miss_groups:
        near_miss_groups = _int(audit_funnel.get("total_near_miss_groups"))
    subthreshold_above_floor = _sum_funnel_value(
        funnels,
        "subThresholdAboveFloorTrades",
        "subthresholdAboveFloorTrades",
        "sub_threshold_above_floor_trades",
    ) or _int(audit_funnel.get("subthreshold_above_floor_trades"))
    grouped_subthreshold = _sum_funnel_value(
        funnels,
        "groupedSubthresholdGroups",
        "grouped_subthreshold_groups",
    ) or _int(audit_funnel.get("grouped_subthreshold_groups"))
    strict_groups = _sum_funnel_value(funnels, "strictFundingGroupsFound", "strict_funding_groups_found") or _int(
        audit_funnel.get("strict_funding_groups_found")
    )
    proxy_groups = _sum_funnel_value(funnels, "proxyOnlyGroupsFound", "proxy_only_groups_found") or _int(
        audit_funnel.get("proxy_only_groups_found")
    )
    attempts = _sum_funnel_value(
        funnels,
        "preAdmissionAttempts",
        "structuralPreAdmissionAttempts",
        "totalStructuralPreAdmissionAttempts",
    ) or _int(audit_funnel.get("total_structural_pre_admission_attempts"))
    validated = _sum_funnel_value(funnels, "validatedAfterScoring", "totalValidated") or _int(
        audit_funnel.get("total_validated")
    )
    rejected_after_scoring = _sum_funnel_value(
        funnels,
        "rejectedAfterScoring",
        "totalRejectedAfterScoring",
    ) or _int(audit_funnel.get("total_rejected_after_scoring"))
    funding_not_assessable = _int(audit_funnel.get("near_miss_groups_funding_not_assessable"))
    resolver_availability = _as_mapping(audit_funnel.get("funding_resolver_availability"))
    resolver_unavailable = _int(resolver_availability.get("unavailable"))

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_count": len(input_paths),
        "selected_path_count": len(selected_paths),
        "corpus_count": len(corpus_summaries),
        "funnel_file_count": len(funnels),
        "subthreshold_above_floor_trades": subthreshold_above_floor,
        "grouped_subthreshold_groups": grouped_subthreshold,
        "near_miss_groups": near_miss_groups,
        "strict_funding_groups_found": strict_groups,
        "proxy_only_groups_found": proxy_groups,
        "structural_pre_admission_attempts": attempts,
        "validated_pre_admissions": validated,
        "rejected_after_scoring": rejected_after_scoring,
        "near_miss_groups_funding_not_assessable": funding_not_assessable,
        "resolver_unavailable_runs": resolver_unavailable,
        "top_non_admission_reasons": dict(rejection_counts.most_common(20)),
    }
    summary["classification"] = _classify_recall(summary)
    summary["recommended_next_playbook"] = {
        "admission schema bug": "Inspect pre-admission discovery/export code before changing admission rules.",
        "funding coverage issue": "Improve funding coverage/cache/runtime before interpreting recall opportunities.",
        "rules too strict but requires human approval": "Prepare product-owner review; do not broaden admission autonomously.",
        "no recall opportunity observed": "Proceed with available corpus; no admission change is indicated by this sample.",
    }[summary["classification"]]
    return summary


def render_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Candidate Recall Audit",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Classification: {summary.get('classification', '')}",
        f"- Recommended next playbook: {summary.get('recommended_next_playbook', '')}",
        f"- Inputs/corpus/funnels: {summary.get('input_count', 0)}/{summary.get('corpus_count', 0)}/{summary.get('funnel_file_count', 0)}",
        f"- Selected paths inspected: {summary.get('selected_path_count', 0)}",
        f"- Sub-threshold above-floor trades: {summary.get('subthreshold_above_floor_trades', 0)}",
        f"- Grouped sub-threshold groups: {summary.get('grouped_subthreshold_groups', 0)}",
        f"- Near-miss groups: {summary.get('near_miss_groups', 0)}",
        f"- Strict funding groups found: {summary.get('strict_funding_groups_found', 0)}",
        f"- Proxy-only groups found: {summary.get('proxy_only_groups_found', 0)}",
        f"- Structural pre-admission attempts: {summary.get('structural_pre_admission_attempts', 0)}",
        f"- Validated pre-admissions: {summary.get('validated_pre_admissions', 0)}",
        f"- Rejected after scoring: {summary.get('rejected_after_scoring', 0)}",
        f"- Near-miss groups with funding not assessable: {summary.get('near_miss_groups_funding_not_assessable', 0)}",
        f"- Resolver-unavailable runs: {summary.get('resolver_unavailable_runs', 0)}",
        "",
        "## Top Non-Admission Reasons",
    ]
    reasons = summary.get("top_non_admission_reasons") or {}
    if isinstance(reasons, Mapping) and reasons:
        for reason, count in reasons.items():
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Scope",
            "- Read-only audit of saved corpus/audit/funnel files.",
            "- Does not rescore trades, call RPC, mutate outputs, or change admission rules.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(summary: Mapping[str, Any], output_dir: Path, timestamp: str | None = None) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"candidate_recall_audit_{stamp}.json"
    md_path = output_dir / f"candidate_recall_audit_{stamp}.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    return md_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only candidate recall / false-negative opportunity audit.")
    parser.add_argument("inputs", nargs="+", help="Corpus JSON, audit JSON, output directories, or funnel files.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    summary = summarize_candidate_recall(Path(value) for value in args.inputs)
    md_path, json_path = write_outputs(summary, Path(args.output_dir))
    print(f"Candidate recall classification: {summary['classification']}")
    print(f"Recommended next playbook: {summary['recommended_next_playbook']}")
    print(f"Candidate recall outputs: {md_path} {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
