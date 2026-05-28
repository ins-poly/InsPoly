#!/usr/bin/env python3
"""Evaluate advisory shadow metrics from Phase 9D normalized inputs.

This is a sidecar-only evaluator. It reads local artifacts through the Phase 9D
normalizer, computes existing advisory shadow metrics where safe, and writes
explicit evaluation outputs only when requested. It does not mutate reports or
import scanner/archive/event-forensic runtime paths.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.shadow_metrics import (  # noqa: E402
    ADVISORY_NONE,
    SHADOW_LOW_ODDS_POSITION_SIZE,
    SHADOW_MICROSTRUCTURE_CONTEXT,
    SHADOW_NET_POSITION_PNL,
    SHADOW_WIN_RATE_CONFIDENCE,
    STATUS_AVAILABLE as SHADOW_STATUS_AVAILABLE,
    STATUS_NOT_TRIGGERED,
    STATUS_UNKNOWN,
    compute_shadow_metrics,
)
from tools.normalize_shadow_inputs_from_artifacts import (  # noqa: E402
    METRIC_ENTRY_EDGE,
    METRIC_LOW_ODDS,
    METRIC_MICROSTRUCTURE,
    METRIC_NET_PNL,
    METRIC_WIN_RATE,
    RECORD_LEDGER_TRADE,
    RECORD_TRADE_EXPOSURE,
    RECORD_WALLET_HISTORY,
    normalize_artifact,
    supported_families,
)
from tools.shadow_field_coverage_mapping import coverage_for_artifact  # noqa: E402


REPORT_TYPE = "normalized_shadow_context_evaluation"
SCHEMA_VERSION = "normalized_shadow_context_evaluation_v1"
STATUS_NOT_COMPUTED = "not_computed"

METRIC_ORDER = (
    METRIC_LOW_ODDS,
    METRIC_ENTRY_EDGE,
    METRIC_NET_PNL,
    METRIC_WIN_RATE,
    METRIC_MICROSTRUCTURE,
)

FORBIDDEN_OUTPUT_TEXT = (
    "risk_level",
    "riskLevel",
    "Strong Risk",
    "strongRisk",
    "Hard Evidence Review",
    "hardEvidenceReview",
    "HER",
    "candidateAdmission",
    "candidate_admission",
    "fundingEligibility",
    "funding_eligibility",
    "eventForensicScore",
    "existingModelScore",
    "laterWon",
    "winnerRank",
    "sortKey",
)


@dataclass(frozen=True, slots=True)
class MetricEvaluation:
    metric: str
    coverage_before: str
    normalization_readiness: str
    evaluated_status: str
    advisory_level: str
    value: str | None
    useful_advisory: bool
    record_count: int
    reason: str
    quality_notes: tuple[str, ...] = ()
    details: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "coverageBefore": self.coverage_before,
            "normalizationReadiness": self.normalization_readiness,
            "evaluatedStatus": self.evaluated_status,
            "advisoryLevel": self.advisory_level,
            "value": self.value,
            "usefulAdvisory": self.useful_advisory,
            "recordCount": self.record_count,
            "reason": self.reason,
            "qualityNotes": list(self.quality_notes),
            "details": dict(self.details or {}),
        }


def evaluate_artifact(family: str, path: str | Path) -> dict[str, object]:
    artifact_path = Path(path)
    coverage = coverage_for_artifact(family, artifact_path)
    normalization = normalize_artifact(family, artifact_path)
    normalized = normalization.to_dict()
    coverage_before = {metric.metric: metric.status for metric in coverage.metrics}
    readiness = {
        str(item["metric"]): dict(item)
        for item in normalized["metricReadiness"]
        if isinstance(item, Mapping)
    }
    records = tuple(
        record
        for record in normalized["normalizedRecords"]
        if isinstance(record, Mapping)
    )
    evaluations = tuple(
        _evaluate_metric(
            metric,
            coverage_before=coverage_before,
            readiness=readiness,
            records=records,
            current_prices=normalized.get("currentPrices") if isinstance(normalized.get("currentPrices"), Mapping) else {},
        )
        for metric in METRIC_ORDER
    )
    result = {
        "family": family,
        "artifactPath": str(artifact_path),
        "normalizedRecordCount": normalized["recordCount"],
        "skippedUnsafeFieldCount": normalized["skippedUnsafeFieldCount"],
        "normalizationQualityNotes": normalized["qualityNotes"],
        "metricEvaluations": [evaluation.to_dict() for evaluation in evaluations],
        "usefulMetricCount": sum(1 for evaluation in evaluations if evaluation.useful_advisory),
    }
    _assert_output_safe(result)
    return result


def evaluate_artifacts(family_paths: Sequence[tuple[str, str | Path]]) -> dict[str, object]:
    artifacts = [evaluate_artifact(family, path) for family, path in family_paths]
    report = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "networkUsed": False,
        "productionIntegration": False,
        "summary": _summary(artifacts),
        "artifacts": artifacts,
    }
    _assert_output_safe(report)
    return report


def write_evaluation_outputs(report: Mapping[str, object], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"normalized_shadow_context_evaluation_{stamp}.json"
    md_path = target / f"normalized_shadow_context_evaluation_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: Mapping[str, object]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# Normalized Shadow Context Evaluation",
        "",
        f"- Schema: `{report.get('schemaVersion')}`",
        f"- Network used: {str(report.get('networkUsed')).lower()}",
        f"- Production integration: {str(report.get('productionIntegration')).lower()}",
        f"- Artifacts evaluated: {summary.get('artifactCount', 0)}",
        f"- Normalized records: {summary.get('normalizedRecordCount', 0)}",
        f"- Useful advisory metrics: {summary.get('usefulMetricCount', 0)}",
        "",
    ]
    for artifact in report.get("artifacts", []):
        if not isinstance(artifact, Mapping):
            continue
        lines.extend(
            [
                f"## {artifact.get('family')}",
                "",
                f"- Artifact: `{artifact.get('artifactPath')}`",
                f"- Normalized records: {artifact.get('normalizedRecordCount')}",
                f"- Useful metrics: {artifact.get('usefulMetricCount')}",
                "",
                "| Metric | Before | Readiness | Evaluated | Advisory | Value |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for metric in artifact.get("metricEvaluations", []):
            if isinstance(metric, Mapping):
                lines.append(
                    f"| `{metric.get('metric')}` | `{metric.get('coverageBefore')}` | "
                    f"`{metric.get('normalizationReadiness')}` | `{metric.get('evaluatedStatus')}` | "
                    f"`{metric.get('advisoryLevel')}` | {metric.get('value') or 'unknown'} |"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _evaluate_metric(
    metric: str,
    *,
    coverage_before: Mapping[str, str],
    readiness: Mapping[str, Mapping[str, object]],
    records: Sequence[Mapping[str, object]],
    current_prices: Mapping[str, object],
) -> MetricEvaluation:
    ready = readiness.get(metric, {})
    readiness_status = str(ready.get("status") or STATUS_NOT_COMPUTED)
    reason = str(ready.get("reason") or "not normalized")
    if metric == METRIC_LOW_ODDS and readiness_status == SHADOW_STATUS_AVAILABLE:
        return _evaluate_low_odds(coverage_before, readiness_status, reason, records)
    if metric == METRIC_WIN_RATE and readiness_status == SHADOW_STATUS_AVAILABLE:
        return _evaluate_win_rate(coverage_before, readiness_status, reason, records)
    if metric == METRIC_NET_PNL and readiness_status == SHADOW_STATUS_AVAILABLE:
        return _evaluate_pnl(coverage_before, readiness_status, reason, records, current_prices)
    return MetricEvaluation(
        metric=metric,
        coverage_before=coverage_before.get(metric, STATUS_NOT_COMPUTED),
        normalization_readiness=readiness_status,
        evaluated_status=STATUS_NOT_COMPUTED if readiness_status == STATUS_NOT_COMPUTED else readiness_status,
        advisory_level=ADVISORY_NONE,
        value=None,
        useful_advisory=False,
        record_count=0,
        reason=reason,
    )


def _evaluate_low_odds(
    coverage_before: Mapping[str, str],
    readiness_status: str,
    reason: str,
    records: Sequence[Mapping[str, object]],
) -> MetricEvaluation:
    rows = _record_fields(records, RECORD_TRADE_EXPOSURE)
    report = compute_shadow_metrics(rows)
    metric = report.metric(SHADOW_LOW_ODDS_POSITION_SIZE)
    return MetricEvaluation(
        metric=METRIC_LOW_ODDS,
        coverage_before=coverage_before.get(METRIC_LOW_ODDS, STATUS_NOT_COMPUTED),
        normalization_readiness=readiness_status,
        evaluated_status=metric.status,
        advisory_level=metric.advisory_level,
        value=metric.value,
        useful_advisory=_is_useful(metric.status, metric.advisory_level),
        record_count=len(rows),
        reason=reason,
        quality_notes=tuple(sorted({*metric.notes, *_record_notes(records, RECORD_TRADE_EXPOSURE)})),
        details=metric.details,
    )


def _evaluate_win_rate(
    coverage_before: Mapping[str, str],
    readiness_status: str,
    reason: str,
    records: Sequence[Mapping[str, object]],
) -> MetricEvaluation:
    rows = _record_fields(records, RECORD_WALLET_HISTORY)
    metric_dicts = []
    useful_count = 0
    best_value: Decimal | None = None
    status = STATUS_UNKNOWN
    advisory = ADVISORY_NONE
    notes: set[str] = set(_record_notes(records, RECORD_WALLET_HISTORY))
    for row in rows:
        report = compute_shadow_metrics([], wallet_stats=row)
        metric = report.metric(SHADOW_WIN_RATE_CONFIDENCE)
        metric_dicts.append(metric.to_dict())
        notes.update(metric.notes)
        if metric.status == SHADOW_STATUS_AVAILABLE:
            status = SHADOW_STATUS_AVAILABLE
        elif status != SHADOW_STATUS_AVAILABLE and metric.status == STATUS_NOT_TRIGGERED:
            status = STATUS_NOT_TRIGGERED
        if _is_useful(metric.status, metric.advisory_level):
            useful_count += 1
            advisory = metric.advisory_level
        value = _decimal(metric.value)
        if value is not None:
            best_value = value if best_value is None else max(best_value, value)
    return MetricEvaluation(
        metric=METRIC_WIN_RATE,
        coverage_before=coverage_before.get(METRIC_WIN_RATE, STATUS_NOT_COMPUTED),
        normalization_readiness=readiness_status,
        evaluated_status=status,
        advisory_level=advisory,
        value=_decimal_text(best_value),
        useful_advisory=useful_count > 0,
        record_count=len(rows),
        reason=reason,
        quality_notes=tuple(sorted(notes)),
        details={"usefulRecordCount": useful_count, "evaluatedRecordCount": len(metric_dicts)},
    )


def _evaluate_pnl(
    coverage_before: Mapping[str, str],
    readiness_status: str,
    reason: str,
    records: Sequence[Mapping[str, object]],
    current_prices: Mapping[str, object],
) -> MetricEvaluation:
    rows = _record_fields(records, RECORD_LEDGER_TRADE)
    report = compute_shadow_metrics(rows, current_prices=current_prices)
    metric = report.metric(SHADOW_NET_POSITION_PNL)
    return MetricEvaluation(
        metric=METRIC_NET_PNL,
        coverage_before=coverage_before.get(METRIC_NET_PNL, STATUS_NOT_COMPUTED),
        normalization_readiness=readiness_status,
        evaluated_status=metric.status,
        advisory_level=metric.advisory_level,
        value=metric.value,
        useful_advisory=_is_useful(metric.status, metric.advisory_level),
        record_count=len(rows),
        reason=reason,
        quality_notes=tuple(sorted({*metric.notes, *_record_notes(records, RECORD_LEDGER_TRADE)})),
        details=metric.details,
    )


def _record_fields(records: Sequence[Mapping[str, object]], record_type: str) -> list[dict[str, object]]:
    rows = []
    for record in records:
        if record.get("recordType") != record_type:
            continue
        fields = record.get("fields")
        if isinstance(fields, Mapping):
            rows.append(dict(fields))
    return rows


def _record_notes(records: Sequence[Mapping[str, object]], record_type: str) -> tuple[str, ...]:
    notes: set[str] = set()
    for record in records:
        if record.get("recordType") != record_type:
            continue
        values = record.get("qualityNotes")
        if isinstance(values, list):
            notes.update(str(value) for value in values)
    return tuple(sorted(notes))


def _is_useful(status: str, advisory_level: str) -> bool:
    return status == SHADOW_STATUS_AVAILABLE and advisory_level != ADVISORY_NONE


def _summary(artifacts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    useful_metric_count = 0
    normalized_record_count = 0
    available_after_count = 0
    not_computed_after_count = 0
    for artifact in artifacts:
        normalized_record_count += int(artifact.get("normalizedRecordCount") or 0)
        for metric in artifact.get("metricEvaluations", []):
            if not isinstance(metric, Mapping):
                continue
            useful_metric_count += 1 if metric.get("usefulAdvisory") else 0
            status = metric.get("evaluatedStatus")
            available_after_count += 1 if status == SHADOW_STATUS_AVAILABLE else 0
            not_computed_after_count += 1 if status == STATUS_NOT_COMPUTED else 0
    return {
        "artifactCount": len(artifacts),
        "normalizedRecordCount": normalized_record_count,
        "usefulMetricCount": useful_metric_count,
        "availableMetricCount": available_after_count,
        "notComputedMetricCount": not_computed_after_count,
    }


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _assert_output_safe(payload: object) -> None:
    text = json.dumps(payload)
    found = [item for item in FORBIDDEN_OUTPUT_TEXT if item in text]
    if found:
        raise ValueError(f"Evaluation output contains forbidden production text: {', '.join(sorted(found))}")


def _parse_artifact_arg(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Artifact must use FAMILY=PATH format")
    family, path = value.split("=", 1)
    family = family.strip()
    if family not in supported_families():
        raise argparse.ArgumentTypeError(f"Unsupported Phase 9E family: {family}")
    return family, path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate advisory metrics from normalized shadow inputs.")
    parser.add_argument(
        "--artifact",
        action="append",
        type=_parse_artifact_arg,
        default=[],
        metavar="FAMILY=PATH",
        help="Artifact family/path pair. Repeat for multiple artifacts.",
    )
    parser.add_argument("--list-families", action="store_true", help="Print supported Phase 9E families.")
    parser.add_argument("--output-dir", help="Optional explicit output directory for JSON and Markdown artifacts.")
    parser.add_argument("--output-json", help="Optional explicit JSON output path.")
    parser.add_argument("--output-md", help="Optional explicit Markdown output path.")
    args = parser.parse_args(argv)

    if args.list_families:
        print("\n".join(supported_families()))
        return 0
    if not args.artifact:
        parser.error("At least one --artifact FAMILY=PATH is required unless --list-families is used.")

    report = evaluate_artifacts(args.artifact)
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(markdown_report(report), encoding="utf-8")
    if args.output_dir:
        write_evaluation_outputs(report, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
