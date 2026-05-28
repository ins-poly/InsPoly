#!/usr/bin/env python3
"""Classify shadow-metric unknown/not-computed reasons into a sidecar backlog."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "shadow_unknown_reason_taxonomy"
SCHEMA_VERSION = "shadow_unknown_reason_taxonomy_v1"

CATEGORY_MISSING_CURRENT_PRICE = "missing_current_price"
CATEGORY_MISSING_REFERENCE_PRICE = "missing_reference_price"
CATEGORY_MISSING_TOKEN_ID = "missing_token_id"
CATEGORY_AMBIGUOUS_SHARE_CASH = "ambiguous_share_cash_semantics"
CATEGORY_WALLET_HISTORY_DUPLICATE = "wallet_history_duplicate"
CATEGORY_UNSAFE_HINDSIGHT = "unsafe_hindsight_or_outcome_field"
CATEGORY_LOSSY_CSV = "lossy_csv"
CATEGORY_MISSING_MICROSTRUCTURE = "missing_microstructure_snapshot"
CATEGORY_UNSUPPORTED_FAMILY = "unsupported_artifact_family"
CATEGORY_QUALITY_DERIVATION = "quality_note_only_derivation"
CATEGORY_OTHER = "other_unknown_reason"

ANALYST_VALUE = {
    CATEGORY_MISSING_CURRENT_PRICE: "high",
    CATEGORY_MISSING_REFERENCE_PRICE: "high",
    CATEGORY_MISSING_TOKEN_ID: "medium",
    CATEGORY_AMBIGUOUS_SHARE_CASH: "medium",
    CATEGORY_WALLET_HISTORY_DUPLICATE: "low",
    CATEGORY_UNSAFE_HINDSIGHT: "none",
    CATEGORY_LOSSY_CSV: "low",
    CATEGORY_MISSING_MICROSTRUCTURE: "medium",
    CATEGORY_UNSUPPORTED_FAMILY: "low",
    CATEGORY_QUALITY_DERIVATION: "low",
    CATEGORY_OTHER: "low",
}

REGRESSION_RISK = {
    CATEGORY_MISSING_CURRENT_PRICE: "medium",
    CATEGORY_MISSING_REFERENCE_PRICE: "medium",
    CATEGORY_MISSING_TOKEN_ID: "high",
    CATEGORY_AMBIGUOUS_SHARE_CASH: "high",
    CATEGORY_WALLET_HISTORY_DUPLICATE: "medium",
    CATEGORY_UNSAFE_HINDSIGHT: "high",
    CATEGORY_LOSSY_CSV: "medium",
    CATEGORY_MISSING_MICROSTRUCTURE: "medium",
    CATEGORY_UNSUPPORTED_FAMILY: "medium",
    CATEGORY_QUALITY_DERIVATION: "low",
    CATEGORY_OTHER: "medium",
}

SIDECAR_ONLY_FIX_POSSIBLE = {
    CATEGORY_MISSING_CURRENT_PRICE: True,
    CATEGORY_MISSING_REFERENCE_PRICE: True,
    CATEGORY_MISSING_TOKEN_ID: True,
    CATEGORY_AMBIGUOUS_SHARE_CASH: True,
    CATEGORY_WALLET_HISTORY_DUPLICATE: True,
    CATEGORY_UNSAFE_HINDSIGHT: False,
    CATEGORY_LOSSY_CSV: False,
    CATEGORY_MISSING_MICROSTRUCTURE: True,
    CATEGORY_UNSUPPORTED_FAMILY: False,
    CATEGORY_QUALITY_DERIVATION: True,
    CATEGORY_OTHER: False,
}

PRODUCTION_REPORT_CHANGE_REQUIRED = {
    CATEGORY_MISSING_CURRENT_PRICE: False,
    CATEGORY_MISSING_REFERENCE_PRICE: False,
    CATEGORY_MISSING_TOKEN_ID: True,
    CATEGORY_AMBIGUOUS_SHARE_CASH: True,
    CATEGORY_WALLET_HISTORY_DUPLICATE: False,
    CATEGORY_UNSAFE_HINDSIGHT: False,
    CATEGORY_LOSSY_CSV: False,
    CATEGORY_MISSING_MICROSTRUCTURE: False,
    CATEGORY_UNSUPPORTED_FAMILY: False,
    CATEGORY_QUALITY_DERIVATION: False,
    CATEGORY_OTHER: False,
}

RECOMMENDED_ACTION = {
    CATEGORY_MISSING_CURRENT_PRICE: "Prefer reconstruction/indexer sidecar current-price context; do not coerce missing prices to zero.",
    CATEGORY_MISSING_REFERENCE_PRICE: "Use only explicit sidecar reference snapshots; do not use outcome or move fields as reference price.",
    CATEGORY_MISSING_TOKEN_ID: "Keep production reports unchanged; use raw bundle or sidecar sources when token id is explicit.",
    CATEGORY_AMBIGUOUS_SHARE_CASH: "Preserve cash/share provenance and avoid PnL unless exact size/cash semantics are explicit.",
    CATEGORY_WALLET_HISTORY_DUPLICATE: "Keep as sidecar/benchmark context unless duplication wording is resolved.",
    CATEGORY_UNSAFE_HINDSIGHT: "Do not fix by mapping hindsight fields; keep excluded.",
    CATEGORY_LOSSY_CSV: "Prefer JSON/raw artifacts over CSV exports; use CSV only as negative-control coverage evidence.",
    CATEGORY_MISSING_MICROSTRUCTURE: "Use optional local sidecar snapshots only; no live indexing without approval.",
    CATEGORY_UNSUPPORTED_FAMILY: "Skip until a narrower sidecar mapper is justified by evidence.",
    CATEGORY_QUALITY_DERIVATION: "Keep quality notes visible; no production report integration needed.",
    CATEGORY_OTHER: "Inspect manually before adding mapping logic.",
}


def build_taxonomy_report(
    batch_normalization: Mapping[str, object],
    *,
    batch_evaluation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    reasons = Counter()
    reasons.update(_reason_counts_from_summary(batch_normalization))
    reasons.update(_quality_note_counts(batch_normalization))
    if batch_evaluation:
        reasons.update(_evaluation_reason_counts(batch_evaluation))

    reason_rows = [_reason_row(reason, count) for reason, count in sorted(reasons.items())]
    category_summary = _category_summary(reason_rows)
    priority_queue = sorted(
        category_summary.values(),
        key=lambda item: (-int(item["priorityScore"]), str(item["category"])),
    )
    report = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "networkUsed": False,
        "productionIntegration": False,
        "summary": {
            "reasonCount": len(reason_rows),
            "totalObservations": sum(int(row["count"]) for row in reason_rows),
            "categoryCount": len(category_summary),
            "topCategory": priority_queue[0]["category"] if priority_queue else "none",
            "sidecarOnlyFixableCategoryCount": sum(1 for item in priority_queue if item["sidecarOnlyFixPossible"]),
            "productionReportChangeCategoryCount": sum(1 for item in priority_queue if item["productionReportChangeRequired"]),
            "decisionHint": _decision_hint(priority_queue),
        },
        "reasonRows": reason_rows,
        "categorySummary": list(priority_queue),
    }
    return report


def write_taxonomy_outputs(report: Mapping[str, object], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"shadow_unknown_reason_taxonomy_{stamp}.json"
    md_path = target / f"shadow_unknown_reason_taxonomy_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: Mapping[str, object]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# Shadow Unknown Reason Taxonomy",
        "",
        f"- Schema: `{report.get('schemaVersion')}`",
        f"- Network used: {str(report.get('networkUsed')).lower()}",
        f"- Production integration: {str(report.get('productionIntegration')).lower()}",
        f"- Total observations: {summary.get('totalObservations', 0)}",
        f"- Decision hint: `{summary.get('decisionHint')}`",
        "",
        "## Priority Queue",
        "",
        "| Category | Count | Analyst value | Regression risk | Sidecar-only fix | Production report change | Priority |",
        "| --- | ---: | --- | --- | --- | --- | ---: |",
    ]
    for item in report.get("categorySummary", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"| `{item.get('category')}` | {item.get('count')} | `{item.get('analystValueIfFixed')}` | "
            f"`{item.get('regressionRisk')}` | {str(item.get('sidecarOnlyFixPossible')).lower()} | "
            f"{str(item.get('productionReportChangeRequired')).lower()} | {item.get('priorityScore')} |"
        )
    lines.extend(["", "## Reasons", "", "| Category | Count | Reason |", "| --- | ---: | --- |"])
    for row in report.get("reasonRows", []):
        if isinstance(row, Mapping):
            lines.append(f"| `{row.get('category')}` | {row.get('count')} | {row.get('reason')} |")
    return "\n".join(lines).rstrip() + "\n"


def classify_reason(reason: str) -> str:
    text = reason.lower()
    if "quality_note:" in text or "derivable" in text or "derived" in text:
        return CATEGORY_QUALITY_DERIVATION
    if "csv" in text or "lossy" in text:
        return CATEGORY_LOSSY_CSV
    if "microstructure" in text or "orderbook" in text:
        return CATEGORY_MISSING_MICROSTRUCTURE
    if "outcome" in text or "winner" in text or "hindsight" in text:
        return CATEGORY_UNSAFE_HINDSIGHT
    if "token" in text:
        return CATEGORY_MISSING_TOKEN_ID
    if "share" in text or "cash" in text or "position size" in text:
        return CATEGORY_AMBIGUOUS_SHARE_CASH
    if "current price" in text or "current-price" in text or "current prices" in text:
        return CATEGORY_MISSING_CURRENT_PRICE
    if "reference price" in text or "reference-price" in text:
        return CATEGORY_MISSING_REFERENCE_PRICE
    if "win count" in text or "wallet closed-position" in text or "wallet-history" in text or "wallet history" in text:
        return CATEGORY_WALLET_HISTORY_DUPLICATE
    if "unsupported" in text or "not supported" in text or "not in phase" in text or "sidecar_output_only" in text:
        return CATEGORY_UNSUPPORTED_FAMILY
    return CATEGORY_OTHER


def _reason_counts_from_summary(payload: Mapping[str, object]) -> Counter[str]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    values = summary.get("unknownReasonCounts") if isinstance(summary.get("unknownReasonCounts"), Mapping) else {}
    return Counter({str(reason): int(count) for reason, count in values.items()})


def _quality_note_counts(payload: Mapping[str, object]) -> Counter[str]:
    counts: Counter[str] = Counter()
    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        for note in artifact.get("qualityNotes", []):
            counts[f"quality_note:{note}"] += 1
    return counts


def _evaluation_reason_counts(payload: Mapping[str, object]) -> Counter[str]:
    counts: Counter[str] = Counter()
    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        for metric in artifact.get("metricEvaluations", []):
            if not isinstance(metric, Mapping):
                continue
            if metric.get("evaluatedStatus") not in {"unknown", "not_computed"}:
                continue
            reason = metric.get("reason")
            if reason:
                counts[str(reason)] += 1
    return counts


def _reason_row(reason: str, count: int) -> dict[str, object]:
    category = classify_reason(reason)
    return {
        "reason": reason,
        "count": count,
        "category": category,
        "analystValueIfFixed": ANALYST_VALUE[category],
        "regressionRisk": REGRESSION_RISK[category],
        "sidecarOnlyFixPossible": SIDECAR_ONLY_FIX_POSSIBLE[category],
        "productionReportChangeRequired": PRODUCTION_REPORT_CHANGE_REQUIRED[category],
        "recommendedAction": RECOMMENDED_ACTION[category],
        "priorityScore": _priority_score(category, count),
    }


def _category_summary(reason_rows: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    buckets: dict[str, dict[str, object]] = {}
    examples: defaultdict[str, list[str]] = defaultdict(list)
    for row in reason_rows:
        category = str(row["category"])
        bucket = buckets.setdefault(
            category,
            {
                "category": category,
                "count": 0,
                "analystValueIfFixed": ANALYST_VALUE[category],
                "regressionRisk": REGRESSION_RISK[category],
                "sidecarOnlyFixPossible": SIDECAR_ONLY_FIX_POSSIBLE[category],
                "productionReportChangeRequired": PRODUCTION_REPORT_CHANGE_REQUIRED[category],
                "recommendedAction": RECOMMENDED_ACTION[category],
                "priorityScore": 0,
                "exampleReasons": [],
            },
        )
        count = int(row["count"])
        bucket["count"] = int(bucket["count"]) + count
        bucket["priorityScore"] = int(bucket["priorityScore"]) + int(row["priorityScore"])
        if len(examples[category]) < 3:
            examples[category].append(str(row["reason"]))
    for category, bucket in buckets.items():
        bucket["exampleReasons"] = examples[category]
    return buckets


def _priority_score(category: str, count: int) -> int:
    value_weight = {"none": 0, "low": 1, "medium": 2, "high": 3}[ANALYST_VALUE[category]]
    risk_penalty = {"low": 0, "medium": 1, "high": 2}[REGRESSION_RISK[category]]
    sidecar_bonus = 2 if SIDECAR_ONLY_FIX_POSSIBLE[category] else 0
    production_penalty = 3 if PRODUCTION_REPORT_CHANGE_REQUIRED[category] else 0
    return max(0, count * value_weight + sidecar_bonus - risk_penalty - production_penalty)


def _decision_hint(priority_queue: Sequence[Mapping[str, object]]) -> str:
    if not priority_queue:
        return "no_unknown_reason_backlog"
    top = priority_queue[0]
    if top.get("productionReportChangeRequired"):
        return "keep_sidecar_only_top_fix_requires_report_schema_gate"
    if not top.get("sidecarOnlyFixPossible"):
        return "keep_sidecar_only_top_reason_not_safely_fixable"
    return "continue_sidecar_only_highest_priority_fix"


def _read_json(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Input JSON root must be an object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify shadow unknown/not-computed reasons into a sidecar backlog.")
    parser.add_argument("--batch-normalization-json", required=True, help="Phase 10B batch normalization JSON.")
    parser.add_argument("--batch-evaluation-json", help="Optional Phase 10C batch evaluation JSON.")
    parser.add_argument("--output-dir", help="Optional explicit output directory for JSON and Markdown artifacts.")
    parser.add_argument("--output-json", help="Optional explicit JSON output path.")
    parser.add_argument("--output-md", help="Optional explicit Markdown output path.")
    parser.add_argument("--quiet", action="store_true", help="Do not print the full JSON report to stdout.")
    args = parser.parse_args(argv)

    normalization = _read_json(args.batch_normalization_json)
    evaluation = _read_json(args.batch_evaluation_json) if args.batch_evaluation_json else None
    report = build_taxonomy_report(normalization, batch_evaluation=evaluation)
    text = json.dumps(report, indent=2, sort_keys=True)
    if not args.quiet:
        print(text)
    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(markdown_report(report), encoding="utf-8")
    if args.output_dir:
        write_taxonomy_outputs(report, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
