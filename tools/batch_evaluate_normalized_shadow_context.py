#!/usr/bin/env python3
"""Batch-evaluate advisory shadow metrics over a local artifact corpus.

This sidecar evaluator expands Phase 9E from a small hand-picked sample to a
bounded corpus. It never writes production reports and never imports scanner,
archive, or Event Forensic runtime paths.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.shadow_metrics import (  # noqa: E402
    ADVISORY_NONE,
    STATUS_AVAILABLE,
    STATUS_NOT_TRIGGERED,
    STATUS_UNKNOWN,
)
from tools.batch_normalize_shadow_inputs import (  # noqa: E402
    NORMALIZER_FAMILY_BY_INVENTORY,
    NORMALIZER_FAMILY_EVENT_FORENSIC,
    _select_artifacts,
)
from tools.evaluate_normalized_shadow_context import (  # noqa: E402
    STATUS_NOT_COMPUTED,
    evaluate_artifact,
)
from tools.shadow_artifact_corpus_inventory import (  # noqa: E402
    FAMILY_ARCHIVE_REPORT_JSON,
    FAMILY_EVENT_FORENSIC_BUNDLE,
    FAMILY_EVENT_FORENSIC_REPORT_JSON,
    FAMILY_RECONSTRUCTION_REPORT_DIR,
    REPORT_TYPE as INVENTORY_REPORT_TYPE,
    discover_corpus_inventory,
)


REPORT_TYPE = "batch_normalized_shadow_context_evaluation"
SCHEMA_VERSION = "batch_normalized_shadow_context_evaluation_v1"

STATUS_EVALUATED = "evaluated"
STATUS_SKIPPED = "skipped"
STATUS_ERROR = "error"

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

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


def batch_evaluate_from_inventory(
    inventory_report: Mapping[str, object],
    *,
    root: str | Path,
    max_artifacts_per_family: int = 10,
) -> dict[str, object]:
    root_path = Path(root)
    artifacts = inventory_report.get("artifacts") if isinstance(inventory_report.get("artifacts"), list) else []
    selected = _select_artifacts(artifacts, max_artifacts_per_family=max_artifacts_per_family)
    results = [_evaluate_inventory_item(item, root=root_path) for item in selected]
    report = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sourceInventoryType": inventory_report.get("reportType"),
        "root": str(root_path),
        "networkUsed": False,
        "productionIntegration": False,
        "limits": {"maxArtifactsPerFamily": max_artifacts_per_family},
        "summary": _summary(results),
        "artifacts": results,
    }
    _assert_output_safe(report)
    return report


def batch_evaluate_from_root(
    root: str | Path,
    *,
    max_artifacts_per_family: int = 10,
) -> dict[str, object]:
    inventory = discover_corpus_inventory(root, max_per_family=max_artifacts_per_family)
    return batch_evaluate_from_inventory(
        inventory.to_dict(),
        root=root,
        max_artifacts_per_family=max_artifacts_per_family,
    )


def write_batch_evaluation_outputs(report: Mapping[str, object], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"batch_normalized_shadow_context_evaluation_{stamp}.json"
    md_path = target / f"batch_normalized_shadow_context_evaluation_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: Mapping[str, object]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# Batch Normalized Shadow Context Evaluation",
        "",
        f"- Schema: `{report.get('schemaVersion')}`",
        f"- Root: `{report.get('root')}`",
        f"- Network used: {str(report.get('networkUsed')).lower()}",
        f"- Production integration: {str(report.get('productionIntegration')).lower()}",
        f"- Artifacts considered: {summary.get('artifactCount', 0)}",
        f"- Evaluated artifacts: {summary.get('evaluatedArtifactCount', 0)}",
        f"- Useful advisory metrics: {summary.get('usefulMetricCount', 0)}",
        f"- Duplicate/confusion risk: `{summary.get('overallDuplicateConfusionRisk')}`",
        "",
        "## Metric Status Counts",
        "",
        "| Status | Count |",
        "| --- | ---: |",
    ]
    metric_status_counts = summary.get("metricStatusCounts") if isinstance(summary.get("metricStatusCounts"), Mapping) else {}
    for status, count in sorted(metric_status_counts.items()):
        lines.append(f"| `{status}` | {count} |")
    lines.extend(
        [
            "",
            "## Value By Family",
            "",
            "| Family | Evaluated | Records | Useful metrics | Duplicate risk | Confusion risk |",
            "| --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    by_family = summary.get("valueByFamily") if isinstance(summary.get("valueByFamily"), Mapping) else {}
    for family, payload in sorted(by_family.items()):
        if not isinstance(payload, Mapping):
            continue
        lines.append(
            f"| `{family}` | {payload.get('evaluatedArtifactCount', 0)} | "
            f"{payload.get('normalizedRecordCount', 0)} | {payload.get('usefulMetricCount', 0)} | "
            f"`{payload.get('duplicateRisk')}` | `{payload.get('confusionRisk')}` |"
        )
    lines.extend(["", "## Useful Examples"])
    useful = summary.get("usefulExamples") if isinstance(summary.get("usefulExamples"), list) else []
    if useful:
        for item in useful:
            if isinstance(item, Mapping):
                lines.append(
                    f"- `{item.get('metric')}` from `{item.get('artifactPath')}`: "
                    f"{item.get('value') or 'context'} ({item.get('reason')})"
                )
    else:
        lines.append("- None.")
    lines.extend(["", "## Clutter Or Misleading Examples"])
    clutter = summary.get("clutterExamples") if isinstance(summary.get("clutterExamples"), list) else []
    if clutter:
        for item in clutter:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('artifactPath')}`: {item.get('reason')}")
    else:
        lines.append("- None.")
    return "\n".join(lines).rstrip() + "\n"


def _evaluate_inventory_item(item: Mapping[str, object], *, root: Path) -> dict[str, object]:
    inventory_family = str(item.get("family") or "unknown")
    artifact_path = str(item.get("artifactPath") or "")
    eval_family, eval_path, skip_reason = _evaluation_target(item, root=root)
    base = {
        "inventoryFamily": inventory_family,
        "artifactPath": artifact_path,
        "evaluationFamily": eval_family,
    }
    if skip_reason:
        return {
            **base,
            "status": STATUS_SKIPPED,
            "skipReason": skip_reason,
            "normalizedRecordCount": 0,
            "metricEvaluations": [],
            "usefulMetricCount": 0,
            "duplicateRisk": _duplicate_risk(inventory_family, ()),
            "confusionRisk": _confusion_risk(inventory_family, ()),
        }
    try:
        evaluated = evaluate_artifact(str(eval_family), eval_path)
    except Exception as exc:  # pragma: no cover - local artifact drift only.
        return {
            **base,
            "status": STATUS_ERROR,
            "skipReason": f"evaluation_error: {type(exc).__name__}: {exc}",
            "normalizedRecordCount": 0,
            "metricEvaluations": [],
            "usefulMetricCount": 0,
            "duplicateRisk": _duplicate_risk(inventory_family, ()),
            "confusionRisk": _confusion_risk(inventory_family, ()),
        }
    metrics = tuple(
        metric
        for metric in evaluated.get("metricEvaluations", [])
        if isinstance(metric, Mapping)
    )
    return {
        **base,
        "status": STATUS_EVALUATED,
        "reason": "evaluated through Phase 9E advisory metric helper",
        "normalizedRecordCount": evaluated.get("normalizedRecordCount", 0),
        "skippedUnsafeFieldCount": evaluated.get("skippedUnsafeFieldCount", 0),
        "usefulMetricCount": evaluated.get("usefulMetricCount", 0),
        "duplicateRisk": _duplicate_risk(inventory_family, metrics),
        "confusionRisk": _confusion_risk(inventory_family, metrics),
        "metricEvaluations": list(metrics),
        "normalizationQualityNotes": evaluated.get("normalizationQualityNotes", []),
    }


def _evaluation_target(item: Mapping[str, object], *, root: Path) -> tuple[str | None, Path, str | None]:
    inventory_family = str(item.get("family") or "")
    artifact_path = str(item.get("artifactPath") or "")
    path = root / artifact_path
    if inventory_family in NORMALIZER_FAMILY_BY_INVENTORY:
        return NORMALIZER_FAMILY_BY_INVENTORY[inventory_family], path, None
    if inventory_family == FAMILY_EVENT_FORENSIC_BUNDLE:
        detected = set(str(name) for name in item.get("detectedFiles", []))
        if "event_analysis.json" in detected:
            return NORMALIZER_FAMILY_EVENT_FORENSIC, path / "event_analysis.json", None
        return None, path, "event_forensic_bundle_missing_event_analysis_json"
    support = str(item.get("supportStatus") or "unknown")
    reason = str(item.get("supportReason") or "unsupported artifact family")
    return None, path, f"{support}: {reason}"


def _duplicate_risk(inventory_family: str, metrics: Sequence[Mapping[str, object]]) -> str:
    metric_names = {str(metric.get("metric")) for metric in metrics}
    if inventory_family == FAMILY_ARCHIVE_REPORT_JSON and "shadow_win_rate_confidence" in metric_names:
        return RISK_HIGH
    if inventory_family == FAMILY_RECONSTRUCTION_REPORT_DIR:
        return RISK_LOW
    if inventory_family in {FAMILY_EVENT_FORENSIC_REPORT_JSON, FAMILY_EVENT_FORENSIC_BUNDLE}:
        return RISK_MEDIUM
    return RISK_MEDIUM if metric_names else RISK_LOW


def _confusion_risk(inventory_family: str, metrics: Sequence[Mapping[str, object]]) -> str:
    if inventory_family == FAMILY_RECONSTRUCTION_REPORT_DIR:
        return RISK_MEDIUM
    if inventory_family in {FAMILY_EVENT_FORENSIC_REPORT_JSON, FAMILY_EVENT_FORENSIC_BUNDLE}:
        return RISK_HIGH
    if any(metric.get("evaluatedStatus") in {STATUS_UNKNOWN, STATUS_NOT_COMPUTED} for metric in metrics):
        return RISK_MEDIUM
    return RISK_LOW


def _summary(results: Sequence[Mapping[str, object]]) -> dict[str, object]:
    status_counts = Counter(str(item.get("status")) for item in results)
    metric_status_counts: Counter[str] = Counter()
    value_by_family: dict[str, dict[str, object]] = {}
    useful_examples: list[dict[str, object]] = []
    clutter_examples: list[dict[str, object]] = []
    normalized_record_count = 0
    useful_metric_count = 0
    for item in results:
        family = str(item.get("inventoryFamily") or "unknown")
        bucket = value_by_family.setdefault(
            family,
            {
                "artifactCount": 0,
                "evaluatedArtifactCount": 0,
                "normalizedRecordCount": 0,
                "usefulMetricCount": 0,
                "duplicateRisk": RISK_LOW,
                "confusionRisk": RISK_LOW,
            },
        )
        bucket["artifactCount"] = int(bucket["artifactCount"]) + 1
        if item.get("status") == STATUS_EVALUATED:
            bucket["evaluatedArtifactCount"] = int(bucket["evaluatedArtifactCount"]) + 1
        record_count = int(item.get("normalizedRecordCount") or 0)
        normalized_record_count += record_count
        bucket["normalizedRecordCount"] = int(bucket["normalizedRecordCount"]) + record_count
        item_useful = int(item.get("usefulMetricCount") or 0)
        useful_metric_count += item_useful
        bucket["usefulMetricCount"] = int(bucket["usefulMetricCount"]) + item_useful
        bucket["duplicateRisk"] = _max_risk(str(bucket["duplicateRisk"]), str(item.get("duplicateRisk") or RISK_LOW))
        bucket["confusionRisk"] = _max_risk(str(bucket["confusionRisk"]), str(item.get("confusionRisk") or RISK_LOW))
        metrics = [metric for metric in item.get("metricEvaluations", []) if isinstance(metric, Mapping)]
        for metric in metrics:
            metric_status_counts[str(metric.get("evaluatedStatus") or "unknown")] += 1
            if metric.get("usefulAdvisory") and len(useful_examples) < 10:
                useful_examples.append(
                    {
                        "artifactPath": item.get("artifactPath"),
                        "family": family,
                        "metric": metric.get("metric"),
                        "value": metric.get("value"),
                        "reason": metric.get("reason"),
                    }
                )
        if _is_clutter_or_misleading(item, metrics) and len(clutter_examples) < 10:
            clutter_examples.append(
                {
                    "artifactPath": item.get("artifactPath"),
                    "family": family,
                    "reason": _clutter_reason(item, metrics),
                }
            )
    return {
        "artifactCount": len(results),
        "evaluatedArtifactCount": status_counts.get(STATUS_EVALUATED, 0),
        "skippedArtifactCount": status_counts.get(STATUS_SKIPPED, 0),
        "errorArtifactCount": status_counts.get(STATUS_ERROR, 0),
        "normalizedRecordCount": normalized_record_count,
        "usefulMetricCount": useful_metric_count,
        "metricStatusCounts": dict(sorted(metric_status_counts.items())),
        "statusCounts": dict(sorted(status_counts.items())),
        "valueByFamily": value_by_family,
        "usefulExamples": useful_examples,
        "clutterExamples": clutter_examples,
        "overallDuplicateConfusionRisk": _overall_risk(value_by_family),
        "decisionHint": _decision_hint(useful_metric_count, value_by_family),
    }


def _is_clutter_or_misleading(item: Mapping[str, object], metrics: Sequence[Mapping[str, object]]) -> bool:
    if item.get("status") != STATUS_EVALUATED:
        return True
    if not metrics:
        return True
    if int(item.get("usefulMetricCount") or 0) == 0:
        return True
    high_unknowns = sum(1 for metric in metrics if metric.get("evaluatedStatus") in {STATUS_UNKNOWN, STATUS_NOT_COMPUTED})
    return high_unknowns >= 4


def _clutter_reason(item: Mapping[str, object], metrics: Sequence[Mapping[str, object]]) -> str:
    if item.get("status") != STATUS_EVALUATED:
        return str(item.get("skipReason") or "not evaluated")
    if not metrics:
        return "no metric evaluations emitted"
    if int(item.get("usefulMetricCount") or 0) == 0:
        return "evaluated metrics were unknown, not computed, or not triggered"
    return "useful context exists but unknown/not-computed metrics still dominate the row"


def _max_risk(left: str, right: str) -> str:
    order = {RISK_LOW: 0, RISK_MEDIUM: 1, RISK_HIGH: 2}
    return left if order.get(left, 0) >= order.get(right, 0) else right


def _overall_risk(value_by_family: Mapping[str, Mapping[str, object]]) -> str:
    risk = RISK_LOW
    for item in value_by_family.values():
        risk = _max_risk(risk, str(item.get("duplicateRisk") or RISK_LOW))
        risk = _max_risk(risk, str(item.get("confusionRisk") or RISK_LOW))
    return risk


def _decision_hint(useful_metric_count: int, value_by_family: Mapping[str, Mapping[str, object]]) -> str:
    high_risk = any(
        item.get("duplicateRisk") == RISK_HIGH or item.get("confusionRisk") == RISK_HIGH
        for item in value_by_family.values()
    )
    if useful_metric_count <= 0:
        return "keep_sidecar_only_no_useful_batch_metrics"
    if high_risk:
        return "keep_sidecar_only_useful_but_duplication_or_confusion_risk_high"
    return "sidecar_evidence_improved_but_requires_later_gate_review"


def _read_inventory(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Inventory root must be a JSON object")
    if payload.get("reportType") != INVENTORY_REPORT_TYPE:
        raise ValueError("Input JSON is not a shadow artifact corpus inventory")
    return payload


def _assert_output_safe(payload: object) -> None:
    text = json.dumps(payload)
    found = [item for item in FORBIDDEN_OUTPUT_TEXT if item in text]
    if found:
        raise ValueError(f"Batch evaluation output contains forbidden production text: {', '.join(sorted(found))}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch-evaluate normalized shadow context over a local corpus.")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository/artifact root to inspect.")
    parser.add_argument("--inventory-json", help="Optional Phase 10A inventory JSON to reuse.")
    parser.add_argument("--max-artifacts-per-family", type=int, default=10, help="Representative cap per inventory family.")
    parser.add_argument("--output-dir", help="Optional explicit output directory for JSON and Markdown artifacts.")
    parser.add_argument("--output-json", help="Optional explicit JSON output path.")
    parser.add_argument("--output-md", help="Optional explicit Markdown output path.")
    parser.add_argument("--quiet", action="store_true", help="Do not print the full JSON report to stdout.")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if args.inventory_json:
        inventory_report = _read_inventory(args.inventory_json)
    else:
        inventory_report = discover_corpus_inventory(root, max_per_family=args.max_artifacts_per_family).to_dict()
    report = batch_evaluate_from_inventory(
        inventory_report,
        root=root,
        max_artifacts_per_family=args.max_artifacts_per_family,
    )
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
        write_batch_evaluation_outputs(report, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
