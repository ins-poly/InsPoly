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

from app.scanner import _suspicious_funding_quality_metrics
from tools.model_behavior_audit import (
    collect_records,
    normalize_record,
    _listish,
    _lookup,
    _truthy,
)

DEFAULT_OUTPUT_DIR = Path("suspicious_funding_quality_replay_outputs")
SUSPICIOUS_FUNDING_SOURCE = "suspicious_recent_funding"
PROXY_GRADES = {"cex_proxy", "bridge_proxy"}
REQUIRED_REPLAY_KEYS = (
    "fundingEvidenceGrade",
    "suspicious_funding_flag",
    "funding_amount_usdc",
    "trade_notional_usdc",
    "minutes_from_funding_to_trade",
)


def replay_records(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    row_summaries: list[dict[str, Any]] = []
    quality_counts: Counter[str] = Counter()
    retained_quality_counts: Counter[str] = Counter()
    downgrade_reasons: Counter[str] = Counter()
    retained_suppressors: Counter[str] = Counter()
    downgraded_suppressors: Counter[str] = Counter()
    multi_hop_quality: Counter[str] = Counter()
    grade_quality: Counter[str] = Counter()
    warnings: Counter[str] = Counter()

    prior_suspicious_her = 0
    replayed_suspicious_her = 0
    retained_rows = 0
    downgraded_rows = 0
    insufficient_rows = 0
    eligible_count = 0
    prior_suspicious_source_rows = 0
    enough_saved_fields = 0

    for row in records:
        normalized = normalize_record(row)
        raw = _flatten_saved_row(row)
        flags = _saved_flags(row)
        metrics = _suspicious_funding_quality_metrics(raw, flags=flags)
        quality = str(metrics.get("suspiciousFundingQuality") or "unknown")
        eligible = str(metrics.get("suspiciousFundingHardEvidenceEligible") or "") == "Yes"
        quality_counts[quality] += 1
        if eligible:
            eligible_count += 1

        prior_sources = normalized["hard_evidence_sources"]
        prior_has_suspicious_source = SUSPICIOUS_FUNDING_SOURCE in prior_sources
        if prior_has_suspicious_source:
            prior_suspicious_source_rows += 1
        prior_suspicious_hard_review = bool(
            normalized["hard_evidence_review"] and prior_has_suspicious_source
        )
        if prior_suspicious_hard_review:
            prior_suspicious_her += 1

        replay_keep = bool(prior_has_suspicious_source and eligible)
        if replay_keep:
            replayed_suspicious_her += 1
        if prior_suspicious_hard_review and replay_keep:
            retained_rows += 1
            retained_quality_counts[quality] += 1
            retained_suppressors.update(normalized["suppressors"])
        elif prior_suspicious_hard_review and not replay_keep:
            downgraded_rows += 1
            reason = _primary_downgrade_reason(metrics)
            downgrade_reasons[reason] += 1
            downgraded_suppressors.update(normalized["suppressors"])

        grade = normalized["funding_evidence_grade"]
        grade_quality[f"{grade} | {quality}"] += 1
        if grade == "multi_hop_unknown":
            multi_hop_quality[quality] += 1
        insufficient = _missing_required_fields(row, raw, prior_has_suspicious_source)
        if insufficient:
            insufficient_rows += 1
            warnings["missing_required_saved_fields"] += 1
        else:
            enough_saved_fields += 1

        if quality == "weak" and replay_keep:
            warnings["weak_funding_would_remain_hard_evidence"] += 1
        if quality == "unknown" and replay_keep:
            warnings["unknown_funding_would_remain_hard_evidence"] += 1
        if grade in PROXY_GRADES and replay_keep:
            warnings["proxy_funding_would_remain_hard_evidence"] += 1
        if (
            grade == "multi_hop_unknown"
            and quality == "strong"
            and (
                metrics.get("suspiciousFundingRecentEnough") != "Yes"
                or metrics.get("suspiciousFundingAmountAligned") != "Yes"
                or not _truthy(_lookup(row, "opening_exposure_flag", "openingExposureFlag", "openingExposure"))
                or metrics.get("suspiciousFundingIndependentSupport") != "Yes"
            )
        ):
            warnings["multi_hop_unknown_strong_without_support"] += 1

        row_summaries.append(
            {
                "rowId": normalized["row_id"],
                "sourcePath": normalized["source_path"],
                "wallet": normalized["wallet"],
                "priorHardEvidenceSources": prior_sources,
                "priorHardEvidenceStrength": normalized["hard_evidence_strength"],
                "priorHardEvidenceReview": normalized["hard_evidence_review"],
                "currentSuspiciousFundingQuality": quality,
                "currentSuspiciousFundingHardEvidenceEligible": eligible,
                "currentWouldKeepSuspiciousFundingHardEvidence": replay_keep,
                "independentSupport": metrics.get("suspiciousFundingIndependentSupport") == "Yes",
                "independentSupportSources": metrics.get("suspiciousFundingIndependentSupportSources", ""),
                "suppressorConflict": metrics.get("suspiciousFundingSuppressorConflict") == "Yes",
                "suppressorConflictReasons": metrics.get("suspiciousFundingSuppressorConflictReasons", ""),
                "missingRequiredFields": insufficient,
                "qualityReasons": metrics.get("suspiciousFundingQualityReasons", ""),
                "fundingEvidenceGrade": grade,
                "suppressors": normalized["suppressors"],
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_rows_inspected": len(records),
        "rows_with_prior_suspicious_recent_funding_source": prior_suspicious_source_rows,
        "rows_with_enough_saved_fields_to_replay_quality": enough_saved_fields,
        "rows_missing_required_saved_fields": insufficient_rows,
        "suspiciousFundingQuality": _counter_dict(quality_counts),
        "suspiciousFundingHardEvidenceEligibleCount": eligible_count,
        "prior_suspicious_funding_hard_evidence_review_count": prior_suspicious_her,
        "replayed_suspicious_funding_hard_evidence_review_count": replayed_suspicious_her,
        "rows_downgraded_from_suspicious_funding_hard_evidence_to_contextual": downgraded_rows,
        "rows_retained_as_hard_evidence_review": retained_rows,
        "retained_rows_by_quality": _counter_dict(retained_quality_counts),
        "downgraded_rows_by_reason": _counter_dict(downgrade_reasons),
        "suppressor_overlap_retained": _counter_dict(retained_suppressors),
        "suppressor_overlap_downgraded": _counter_dict(downgraded_suppressors),
        "multi_hop_unknown_rows_by_quality": _counter_dict(multi_hop_quality),
        "fundingEvidenceGrade_rows_by_quality": _counter_dict(grade_quality),
        "warnings": [
            {"code": code, "count": count}
            for code, count in sorted(warnings.items())
        ],
        "rows": row_summaries[:500],
    }


def write_outputs(summary: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"replay_{stamp}.json"
    md_path = output_dir / f"replay_{stamp}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(summary), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(md_path)}


def _flatten_saved_row(row: Mapping[str, Any]) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for source in (
        row,
        row.get("rawMetrics") if isinstance(row.get("rawMetrics"), Mapping) else {},
        row.get("raw_metrics") if isinstance(row.get("raw_metrics"), Mapping) else {},
        row.get("supportingEvidence") if isinstance(row.get("supportingEvidence"), Mapping) else {},
        row.get("supporting_evidence") if isinstance(row.get("supporting_evidence"), Mapping) else {},
    ):
        if isinstance(source, Mapping):
            raw.update(source)
    for camel, snake in (
        ("fundingEvidenceGrade", "funding_evidence_grade"),
        ("openingExposureFlag", "opening_exposure_flag"),
    ):
        value = _lookup(row, camel, snake)
        if value != "":
            raw[camel] = value
            raw[snake] = value
    return raw


def _saved_flags(row: Mapping[str, Any]) -> list[str]:
    return _listish(
        _lookup(
            row,
            "eventForensicFlags",
            "event_forensic_flags",
            "walletEvidenceSourceFlags",
            "wallet_evidence_source_flags",
            "flags",
        )
    )


def _missing_required_fields(
    row: Mapping[str, Any],
    raw: Mapping[str, Any],
    prior_has_suspicious_source: bool,
) -> bool:
    if not prior_has_suspicious_source:
        return False
    for key in REQUIRED_REPLAY_KEYS:
        if raw.get(key) in {"", None} and _lookup(row, key) == "":
            return True
    if _lookup(row, "opening_exposure_flag", "openingExposureFlag", "openingExposure", "trade_state") == "":
        return True
    return False


def _primary_downgrade_reason(metrics: Mapping[str, str]) -> str:
    if metrics.get("suspiciousFundingSuppressorConflict") == "Yes":
        reasons = str(metrics.get("suspiciousFundingSuppressorConflictReasons") or "").strip()
        return f"suppressor_conflict: {reasons}" if reasons else "suppressor_conflict"
    if (
        metrics.get("suspiciousFundingQuality") in {"moderate", "weak"}
        and metrics.get("suspiciousFundingIndependentSupport") != "Yes"
    ):
        text = str(metrics.get("suspiciousFundingQualityReasons") or "")
        if "multi-hop unknown" in text:
            return "multi_hop_unknown_without_independent_support"
    text = str(metrics.get("suspiciousFundingQualityReasons") or "")
    if not text:
        return "not_hard_evidence_eligible"
    return text.split(";", 1)[0].strip() or "not_hard_evidence_eligible"


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Suspicious Funding Quality Offline Replay",
        "",
        f"- Total rows inspected: {summary.get('total_rows_inspected', 0)}",
        f"- Prior suspicious-funding Hard Evidence Review rows: {summary.get('prior_suspicious_funding_hard_evidence_review_count', 0)}",
        f"- Replayed suspicious-funding Hard Evidence Review rows: {summary.get('replayed_suspicious_funding_hard_evidence_review_count', 0)}",
        f"- Retained rows: {summary.get('rows_retained_as_hard_evidence_review', 0)}",
        f"- Downgraded rows: {summary.get('rows_downgraded_from_suspicious_funding_hard_evidence_to_contextual', 0)}",
        f"- Insufficient-field rows: {summary.get('rows_missing_required_saved_fields', 0)}",
        f"- Suspicious funding hard-evidence eligible count: {summary.get('suspiciousFundingHardEvidenceEligibleCount', 0)}",
        "",
        "## Suspicious Funding Quality",
    ]
    for key, count in (summary.get("suspiciousFundingQuality") or {}).items():
        lines.append(f"- {key}: {count}")
    lines.extend(["", "## Downgrade Reasons"])
    reasons = summary.get("downgraded_rows_by_reason") or {}
    if reasons:
        for key, count in reasons.items():
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Retained Rows By Quality"])
    retained = summary.get("retained_rows_by_quality") or {}
    if retained:
        for key, count in retained.items():
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Multi-Hop Unknown By Quality"])
    multi = summary.get("multi_hop_unknown_rows_by_quality") or {}
    if multi:
        for key, count in multi.items():
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings"])
    warnings = summary.get("warnings") or []
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning.get('code')}: {warning.get('count')}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay suspicious funding quality from saved InsPoly outputs without RPC or rescoring."
    )
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--prior-audit", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    records = collect_records(args.paths)
    summary = replay_records(records)
    summary["input_paths"] = [str(path) for path in args.paths]
    if args.prior_audit:
        summary["prior_audit_path"] = str(args.prior_audit)
    outputs = write_outputs(summary, args.output_dir)
    print(f"Rows inspected: {summary['total_rows_inspected']}")
    print(f"Prior suspicious-funding Hard Evidence Review rows: {summary['prior_suspicious_funding_hard_evidence_review_count']}")
    print(f"Replayed suspicious-funding Hard Evidence Review rows: {summary['replayed_suspicious_funding_hard_evidence_review_count']}")
    print(f"Downgraded rows: {summary['rows_downgraded_from_suspicious_funding_hard_evidence_to_contextual']}")
    print(f"Insufficient-field rows: {summary['rows_missing_required_saved_fields']}")
    print(f"Markdown: {outputs['markdown_path']}")
    print(f"JSON: {outputs['json_path']}")


if __name__ == "__main__":
    main()
