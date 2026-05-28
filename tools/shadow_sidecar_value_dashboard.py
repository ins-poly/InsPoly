#!/usr/bin/env python3
"""Build a consolidated sidecar dashboard from Phase 10A-10D outputs."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "shadow_sidecar_value_dashboard"
SCHEMA_VERSION = "shadow_sidecar_value_dashboard_v1"

DECISION_KEEP_SIDECAR_ONLY = "keep_sidecar_only"
DECISION_EXPAND_SIDECAR_NORMALIZATION = "expand_sidecar_normalization"
DECISION_RFC_ONLY_LATER = "draft_rfc_only_later"
DECISION_NEVER_INTEGRATE = "never_integrate_specific_metrics"


def build_dashboard(
    *,
    inventory: Mapping[str, object],
    normalization: Mapping[str, object],
    evaluation: Mapping[str, object],
    taxonomy: Mapping[str, object],
) -> dict[str, object]:
    inventory_summary = _mapping(inventory.get("summary"))
    normalization_summary = _mapping(normalization.get("summary"))
    evaluation_summary = _mapping(evaluation.get("summary"))
    taxonomy_summary = _mapping(taxonomy.get("summary"))
    category_summary = taxonomy.get("categorySummary") if isinstance(taxonomy.get("categorySummary"), list) else []

    decisions = _decisions(evaluation_summary, category_summary)
    dashboard = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "networkUsed": False,
        "productionIntegration": False,
        "inputs": {
            "inventoryReportType": inventory.get("reportType"),
            "normalizationReportType": normalization.get("reportType"),
            "evaluationReportType": evaluation.get("reportType"),
            "taxonomyReportType": taxonomy.get("reportType"),
        },
        "summary": {
            "artifactInventoryCount": inventory_summary.get("artifactCount", 0),
            "normalizerSupportedArtifacts": _count_supported(inventory_summary),
            "batchArtifactsConsidered": normalization_summary.get("artifactCount", 0),
            "batchNormalizedArtifacts": normalization_summary.get("normalizedArtifactCount", 0),
            "batchNormalizedRecords": normalization_summary.get("normalizedRecordCount", 0),
            "batchUsefulMetrics": evaluation_summary.get("usefulMetricCount", 0),
            "batchMetricStatusCounts": evaluation_summary.get("metricStatusCounts", {}),
            "topUnknownCategory": taxonomy_summary.get("topCategory"),
            "overallDuplicateConfusionRisk": evaluation_summary.get("overallDuplicateConfusionRisk"),
            "decision": decisions["primaryDecision"],
        },
        "decisions": decisions,
        "phaseHighlights": _phase_highlights(
            inventory_summary,
            normalization_summary,
            evaluation_summary,
            taxonomy_summary,
            category_summary,
        ),
        "rollbackMap": {
            "phase10a": "delete shadow_artifact_corpus_inventory tool/tests/fixtures and phase10a outputs/docs",
            "phase10b": "delete batch_normalize_shadow_inputs tool/tests and phase10b outputs/docs",
            "phase10c": "delete batch_evaluate_normalized_shadow_context tool/tests and phase10c outputs/docs",
            "phase10d": "delete shadow_unknown_reason_taxonomy tool/tests and phase10d outputs/docs",
            "phase10e": "delete shadow_sidecar_value_dashboard tool/tests and phase10e outputs/docs",
        },
    }
    return dashboard


def write_dashboard_outputs(report: Mapping[str, object], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"shadow_sidecar_value_dashboard_{stamp}.json"
    md_path = target / f"shadow_sidecar_value_dashboard_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: Mapping[str, object]) -> str:
    summary = _mapping(report.get("summary"))
    decisions = _mapping(report.get("decisions"))
    lines = [
        "# Shadow Sidecar Value Dashboard",
        "",
        f"- Schema: `{report.get('schemaVersion')}`",
        f"- Network used: {str(report.get('networkUsed')).lower()}",
        f"- Production integration: {str(report.get('productionIntegration')).lower()}",
        f"- Decision: `{summary.get('decision')}`",
        f"- Inventory artifacts: {summary.get('artifactInventoryCount', 0)}",
        f"- Batch normalized records: {summary.get('batchNormalizedRecords', 0)}",
        f"- Useful advisory metrics: {summary.get('batchUsefulMetrics', 0)}",
        f"- Duplicate/confusion risk: `{summary.get('overallDuplicateConfusionRisk')}`",
        f"- Top unknown category: `{summary.get('topUnknownCategory')}`",
        "",
        "## Decision Outputs",
        "",
        "| Decision | Status | Rationale |",
        "| --- | --- | --- |",
    ]
    for key in (
        DECISION_KEEP_SIDECAR_ONLY,
        DECISION_EXPAND_SIDECAR_NORMALIZATION,
        DECISION_RFC_ONLY_LATER,
        DECISION_NEVER_INTEGRATE,
    ):
        payload = _mapping(decisions.get(key))
        lines.append(f"| `{key}` | `{payload.get('status')}` | {payload.get('rationale')} |")
    lines.extend(["", "## Phase Highlights"])
    for item in report.get("phaseHighlights", []):
        if isinstance(item, Mapping):
            lines.append(f"- {item.get('phase')}: {item.get('summary')}")
    lines.extend(["", "## Rollback Map"])
    rollback = _mapping(report.get("rollbackMap"))
    for key, value in rollback.items():
        lines.append(f"- `{key}`: {value}")
    return "\n".join(lines).rstrip() + "\n"


def _decisions(
    evaluation_summary: Mapping[str, object],
    category_summary: Sequence[object],
) -> dict[str, object]:
    useful_metrics = int(evaluation_summary.get("usefulMetricCount") or 0)
    risk = str(evaluation_summary.get("overallDuplicateConfusionRisk") or "unknown")
    top_sidecar_fix = _first_sidecar_fix(category_summary)
    report_change_needed = any(
        isinstance(item, Mapping) and bool(item.get("productionReportChangeRequired"))
        for item in category_summary
    )
    rfc_ready = useful_metrics >= 10 and risk == "low" and not report_change_needed
    return {
        "primaryDecision": DECISION_RFC_ONLY_LATER if rfc_ready else DECISION_KEEP_SIDECAR_ONLY,
        DECISION_KEEP_SIDECAR_ONLY: {
            "status": "selected" if not rfc_ready else "not_selected",
            "rationale": "Useful metrics remain narrow or duplicate/confusion risk is not low.",
        },
        DECISION_EXPAND_SIDECAR_NORMALIZATION: {
            "status": "candidate",
            "rationale": f"Highest sidecar-only backlog category is `{top_sidecar_fix}`.",
        },
        DECISION_RFC_ONLY_LATER: {
            "status": "not_ready" if not rfc_ready else "candidate",
            "rationale": "Requires high useful-metric coverage, low unknown rate, and low duplicate/confusion risk.",
        },
        DECISION_NEVER_INTEGRATE: {
            "status": "selected_for_unsafe_hindsight_metrics",
            "rationale": "Unsafe hindsight/outcome mappings must remain excluded regardless of frequency.",
        },
    }


def _phase_highlights(
    inventory_summary: Mapping[str, object],
    normalization_summary: Mapping[str, object],
    evaluation_summary: Mapping[str, object],
    taxonomy_summary: Mapping[str, object],
    category_summary: Sequence[object],
) -> list[dict[str, object]]:
    return [
        {
            "phase": "10A",
            "summary": (
                f"Inventory found {inventory_summary.get('artifactCount', 0)} artifacts; "
                f"{_count_supported(inventory_summary)} were normalizer-supported."
            ),
        },
        {
            "phase": "10B",
            "summary": (
                f"Batch normalization considered {normalization_summary.get('artifactCount', 0)} artifacts and "
                f"emitted {normalization_summary.get('emittedRecordCount', 0)} sidecar records."
            ),
        },
        {
            "phase": "10C",
            "summary": (
                f"Batch evaluation found {evaluation_summary.get('usefulMetricCount', 0)} useful advisory metrics "
                f"with duplicate/confusion risk `{evaluation_summary.get('overallDuplicateConfusionRisk')}`."
            ),
        },
        {
            "phase": "10D",
            "summary": (
                f"Taxonomy ranked `{taxonomy_summary.get('topCategory')}` first; "
                f"{taxonomy_summary.get('productionReportChangeCategoryCount', 0)} categories need a report-schema gate."
            ),
        },
        {
            "phase": "next",
            "summary": f"Next safe sidecar focus: `{_first_sidecar_fix(category_summary)}`.",
        },
    ]


def _count_supported(summary: Mapping[str, object]) -> int:
    counts = summary.get("supportStatusCounts") if isinstance(summary.get("supportStatusCounts"), Mapping) else {}
    return int(counts.get("normalizer_supported") or 0)


def _first_sidecar_fix(category_summary: Sequence[object]) -> str:
    for item in category_summary:
        if isinstance(item, Mapping) and item.get("sidecarOnlyFixPossible") and not item.get("productionReportChangeRequired"):
            return str(item.get("category"))
    return "none"


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _read_json(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Input JSON root must be an object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a consolidated Phase 10 shadow sidecar dashboard.")
    parser.add_argument("--inventory-json", required=True)
    parser.add_argument("--normalization-json", required=True)
    parser.add_argument("--evaluation-json", required=True)
    parser.add_argument("--taxonomy-json", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_dashboard(
        inventory=_read_json(args.inventory_json),
        normalization=_read_json(args.normalization_json),
        evaluation=_read_json(args.evaluation_json),
        taxonomy=_read_json(args.taxonomy_json),
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
        write_dashboard_outputs(report, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
