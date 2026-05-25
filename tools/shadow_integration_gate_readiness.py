#!/usr/bin/env python3
"""Evaluate whether sidecar shadow context is ready for any report-copying RFC."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "shadow_integration_gate_readiness"
SCHEMA_VERSION = "shadow_integration_gate_readiness_v1"


def build_shadow_integration_gate_readiness(
    *,
    dashboard: Mapping[str, object],
    taxonomy: Mapping[str, object],
    archive_overlap: Mapping[str, object],
    packet_previews: Mapping[str, object],
) -> dict[str, object]:
    dashboard_summary = dashboard.get("summary") if isinstance(dashboard.get("summary"), Mapping) else {}
    dashboard_decisions = dashboard.get("decisions") if isinstance(dashboard.get("decisions"), Mapping) else {}
    overlap_summary = archive_overlap.get("summary") if isinstance(archive_overlap.get("summary"), Mapping) else {}
    preview_count = _int(packet_previews.get("packetCount"))
    useful_metrics = _int(dashboard_summary.get("batchUsefulMetrics"))
    normalized_records = _int(dashboard_summary.get("batchNormalizedRecords"))
    status_counts = dashboard_summary.get("batchMetricStatusCounts") if isinstance(dashboard_summary.get("batchMetricStatusCounts"), Mapping) else {}
    unknown_not_computed = _int(status_counts.get("unknown")) + _int(status_counts.get("not_computed"))
    duplicate_ratio = _decimal(overlap_summary.get("duplicateRatio"))
    report_schema_categories = [
        item.get("category")
        for item in taxonomy.get("categorySummary", [])
        if isinstance(item, Mapping) and item.get("productionReportChangeRequired")
    ]
    blocking_reasons = _blocking_reasons(
        dashboard_summary=dashboard_summary,
        dashboard_decisions=dashboard_decisions,
        overlap_summary=overlap_summary,
        duplicate_ratio=duplicate_ratio,
        report_schema_categories=report_schema_categories,
        useful_metrics=useful_metrics,
        normalized_records=normalized_records,
        preview_count=preview_count,
        unknown_not_computed=unknown_not_computed,
    )
    decision = "keep_sidecar_only" if blocking_reasons else "rfc_only_candidate"
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "decision": decision,
        "reportCopyingRfcAllowed": decision == "rfc_only_candidate",
        "implementationAllowed": False,
        "approvalGate": "separate_human_approval_required_before_any_report_or_runtime_change",
        "criteria": {
            "dashboardDecision": dashboard_summary.get("decision") or dashboard_decisions.get("primaryDecision"),
            "duplicateConfusionRisk": dashboard_summary.get("overallDuplicateConfusionRisk"),
            "normalizedRecords": normalized_records,
            "usefulMetrics": useful_metrics,
            "usefulMetricPerRecord": _ratio_string(useful_metrics, normalized_records),
            "unknownOrNotComputedMetricCount": unknown_not_computed,
            "archiveDuplicateRatio": str(duplicate_ratio) if duplicate_ratio is not None else "unknown",
            "packetPreviewCount": preview_count,
            "productionReportChangeRequiredCategories": report_schema_categories,
        },
        "blockingReasons": blocking_reasons,
        "allowedNextSteps": [
            "continue sidecar-only evidence work",
            "add explicit local microstructure/reference/current-price fixtures if available",
            "keep reconstruction PnL as sidecar accounting context",
            "keep archive wallet-history overlap as benchmark-only unless duplication risk drops",
        ],
        "forbiddenWithoutApproval": [
            "copy shadowContext into production reports",
            "modify scanner/archive/Event Forensic report writers or loaders",
            "modify UI visibility, sorting, labels, HER, funding, candidate admission, or scoring",
            "start live/network indexing or add background workers",
            "add production imports from sidecar tools",
        ],
    }


def write_shadow_integration_gate_readiness(report: Mapping[str, object], output_dir: str | Path) -> dict[str, object]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"shadow_integration_gate_readiness_{stamp}.json"
    md_path = target / f"shadow_integration_gate_readiness_{stamp}.md"
    latest_json = target / "shadow_integration_gate_readiness_latest.json"
    latest_md = target / "shadow_integration_gate_readiness_latest.md"
    json_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    markdown = gate_markdown(report)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")
    latest_md.write_text(markdown, encoding="utf-8")
    return {**report, "outputPaths": [str(json_path), str(md_path)], "latestPaths": [str(latest_json), str(latest_md)]}


def gate_markdown(report: Mapping[str, object]) -> str:
    criteria = report.get("criteria") if isinstance(report.get("criteria"), Mapping) else {}
    lines = [
        "# Shadow Integration Gate Readiness",
        "",
        "- Scope: sidecar_only",
        f"- Decision: `{report.get('decision')}`",
        f"- Report-copying RFC allowed: `{str(report.get('reportCopyingRfcAllowed')).lower()}`",
        f"- Implementation allowed: `{str(report.get('implementationAllowed')).lower()}`",
        "",
        "## Criteria",
        "",
        f"- Dashboard decision: `{criteria.get('dashboardDecision')}`",
        f"- Duplicate/confusion risk: `{criteria.get('duplicateConfusionRisk')}`",
        f"- Normalized records: `{criteria.get('normalizedRecords')}`",
        f"- Useful metrics: `{criteria.get('usefulMetrics')}`",
        f"- Useful metric per record: `{criteria.get('usefulMetricPerRecord')}`",
        f"- Unknown/not-computed metric count: `{criteria.get('unknownOrNotComputedMetricCount')}`",
        f"- Archive duplicate ratio: `{criteria.get('archiveDuplicateRatio')}`",
        f"- Packet preview count: `{criteria.get('packetPreviewCount')}`",
        "",
        "## Blocking Reasons",
    ]
    reasons = report.get("blockingReasons") if isinstance(report.get("blockingReasons"), list) else []
    lines.extend(f"- {reason}" for reason in reasons)
    lines.extend(["", "## Allowed Next Steps"])
    lines.extend(f"- {step}" for step in report.get("allowedNextSteps", []))
    lines.extend(["", "## Forbidden Without Approval"])
    lines.extend(f"- {step}" for step in report.get("forbiddenWithoutApproval", []))
    return "\n".join(lines).rstrip() + "\n"


def _blocking_reasons(
    *,
    dashboard_summary: Mapping[str, object],
    dashboard_decisions: Mapping[str, object],
    overlap_summary: Mapping[str, object],
    duplicate_ratio: Decimal | None,
    report_schema_categories: Sequence[object],
    useful_metrics: int,
    normalized_records: int,
    preview_count: int,
    unknown_not_computed: int,
) -> list[str]:
    reasons = []
    primary_decision = dashboard_summary.get("decision") or dashboard_decisions.get("primaryDecision")
    if primary_decision == "keep_sidecar_only":
        reasons.append("dashboard primary decision remains `keep_sidecar_only`")
    elif primary_decision not in ("rfc_only_candidate", "draft_rfc_only_later"):
        reasons.append(f"dashboard primary decision `{primary_decision}` is not an integration-readiness signal")
    if dashboard_summary.get("overallDuplicateConfusionRisk") != "low":
        reasons.append(f"duplicate/confusion risk is `{dashboard_summary.get('overallDuplicateConfusionRisk')}`, not `low`")
    if normalized_records and Decimal(useful_metrics) / Decimal(normalized_records) < Decimal("0.05"):
        reasons.append("useful advisory metric density is below 5 percent of normalized records")
    if unknown_not_computed > useful_metrics:
        reasons.append("unknown/not-computed metric count exceeds useful metric count")
    if duplicate_ratio is not None and duplicate_ratio > Decimal("0.25"):
        reasons.append(f"archive wallet-history duplicate ratio is high: {duplicate_ratio}")
    if report_schema_categories:
        reasons.append(
            "some useful-looking gaps require a production report-schema gate: "
            + ", ".join(str(item) for item in report_schema_categories)
        )
    if preview_count < 20:
        reasons.append("sidecar review packet sample is still narrow")
    if _int(overlap_summary.get("usefulShadowRows")) <= _int(overlap_summary.get("duplicateProductionSemanticRows")):
        reasons.append("archive overlap shows useful rows do not exceed duplicate production-semantics rows")
    return reasons


def _read_json(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _int(value: object) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _ratio_string(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "unknown"
    return str(Decimal(numerator) / Decimal(denominator))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate sidecar shadow context integration readiness.")
    parser.add_argument("--dashboard-json", required=True)
    parser.add_argument("--taxonomy-json", required=True)
    parser.add_argument("--archive-overlap-json", required=True)
    parser.add_argument("--packet-preview-json", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_shadow_integration_gate_readiness(
        dashboard=_read_json(args.dashboard_json),
        taxonomy=_read_json(args.taxonomy_json),
        archive_overlap=_read_json(args.archive_overlap_json),
        packet_previews=_read_json(args.packet_preview_json),
    )
    written = write_shadow_integration_gate_readiness(report, args.output_dir)
    if not args.quiet:
        print(json.dumps(written, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
