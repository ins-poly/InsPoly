#!/usr/bin/env python3
"""Batch-run Phase 9D shadow input normalization over a local corpus.

The runner reads a corpus inventory or discovers one locally, normalizes only
artifact families already approved by Phase 9D, and emits sidecar output only.
Unsupported artifacts are skipped with structured reasons.
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

from tools.normalize_shadow_inputs_from_artifacts import (  # noqa: E402
    STATUS_AVAILABLE,
    normalize_artifact,
)
from tools.shadow_artifact_corpus_inventory import (  # noqa: E402
    FAMILY_ARCHIVE_REPORT_JSON,
    FAMILY_EVENT_FORENSIC_BUNDLE,
    FAMILY_EVENT_FORENSIC_REPORT_JSON,
    FAMILY_RECENT_SCANNER_JSON,
    FAMILY_RECONSTRUCTION_REPORT_DIR,
    REPORT_TYPE as INVENTORY_REPORT_TYPE,
    discover_corpus_inventory,
)


REPORT_TYPE = "batch_shadow_input_normalization"
SCHEMA_VERSION = "batch_shadow_input_normalization_v1"

STATUS_NORMALIZED = "normalized"
STATUS_SKIPPED = "skipped"
STATUS_ERROR = "error"

NORMALIZER_FAMILY_EVENT_FORENSIC = "event_forensic_event_analysis_json"

NORMALIZER_FAMILY_BY_INVENTORY = {
    FAMILY_RECENT_SCANNER_JSON: "recent_scanner_report_json",
    FAMILY_ARCHIVE_REPORT_JSON: "archive_report_json",
    FAMILY_EVENT_FORENSIC_REPORT_JSON: NORMALIZER_FAMILY_EVENT_FORENSIC,
    FAMILY_RECONSTRUCTION_REPORT_DIR: "reconstruction_report_dir",
}

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


def batch_normalize_from_inventory(
    inventory_report: Mapping[str, object],
    *,
    root: str | Path,
    max_artifacts_per_family: int = 10,
    max_records_per_artifact: int = 200,
) -> dict[str, object]:
    root_path = Path(root)
    artifacts = inventory_report.get("artifacts") if isinstance(inventory_report.get("artifacts"), list) else []
    selected = _select_artifacts(artifacts, max_artifacts_per_family=max_artifacts_per_family)
    results = [
        _normalize_inventory_item(
            item,
            root=root_path,
            max_records_per_artifact=max_records_per_artifact,
        )
        for item in selected
    ]
    report = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sourceInventoryType": inventory_report.get("reportType"),
        "root": str(root_path),
        "networkUsed": False,
        "productionIntegration": False,
        "limits": {
            "maxArtifactsPerFamily": max_artifacts_per_family,
            "maxRecordsPerArtifact": max_records_per_artifact,
        },
        "summary": _summary(results),
        "artifacts": results,
    }
    _assert_output_safe(report)
    return report


def batch_normalize_from_root(
    root: str | Path,
    *,
    max_artifacts_per_family: int = 10,
    max_records_per_artifact: int = 200,
) -> dict[str, object]:
    inventory = discover_corpus_inventory(root, max_per_family=max_artifacts_per_family)
    return batch_normalize_from_inventory(
        inventory.to_dict(),
        root=root,
        max_artifacts_per_family=max_artifacts_per_family,
        max_records_per_artifact=max_records_per_artifact,
    )


def write_batch_outputs(report: Mapping[str, object], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"batch_shadow_input_normalization_{stamp}.json"
    md_path = target / f"batch_shadow_input_normalization_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: Mapping[str, object]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# Batch Shadow Input Normalization",
        "",
        f"- Schema: `{report.get('schemaVersion')}`",
        f"- Root: `{report.get('root')}`",
        f"- Network used: {str(report.get('networkUsed')).lower()}",
        f"- Production integration: {str(report.get('productionIntegration')).lower()}",
        f"- Artifacts considered: {summary.get('artifactCount', 0)}",
        f"- Normalized artifacts: {summary.get('normalizedArtifactCount', 0)}",
        f"- Normalized records: {summary.get('normalizedRecordCount', 0)}",
        f"- Emitted records: {summary.get('emittedRecordCount', 0)}",
        f"- Skipped artifacts: {summary.get('skippedArtifactCount', 0)}",
        "",
        "## Coverage By Family",
        "",
        "| Family | Artifacts | Normalized | Records | Available metrics | Skipped unsafe fields |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    coverage = summary.get("coverageByFamily") if isinstance(summary.get("coverageByFamily"), Mapping) else {}
    for family, payload in sorted(coverage.items()):
        if not isinstance(payload, Mapping):
            continue
        lines.append(
            f"| `{family}` | {payload.get('artifactCount', 0)} | "
            f"{payload.get('normalizedArtifactCount', 0)} | {payload.get('normalizedRecordCount', 0)} | "
            f"{payload.get('availableMetricCount', 0)} | {payload.get('skippedUnsafeFieldCount', 0)} |"
        )
    lines.extend(["", "## Unknown / Not-Computed Reasons", "", "| Reason | Count |", "| --- | ---: |"])
    reason_counts = summary.get("unknownReasonCounts") if isinstance(summary.get("unknownReasonCounts"), Mapping) else {}
    for reason, count in sorted(reason_counts.items(), key=lambda item: (-int(item[1]), str(item[0]))):
        lines.append(f"| {reason} | {count} |")
    lines.extend(["", "## Artifacts", "", "| Status | Family | Artifact | Records | Reason |", "| --- | --- | --- | ---: | --- |"])
    for artifact in report.get("artifacts", []):
        if not isinstance(artifact, Mapping):
            continue
        lines.append(
            f"| `{artifact.get('status')}` | `{artifact.get('inventoryFamily')}` | "
            f"`{artifact.get('artifactPath')}` | {artifact.get('normalizedRecordCount', 0)} | "
            f"{artifact.get('reason') or artifact.get('skipReason') or ''} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _select_artifacts(
    artifacts: Sequence[object],
    *,
    max_artifacts_per_family: int,
) -> list[Mapping[str, object]]:
    counts: defaultdict[str, int] = defaultdict(int)
    selected: list[Mapping[str, object]] = []
    for item in artifacts:
        if not isinstance(item, Mapping):
            continue
        family = str(item.get("family") or "unknown")
        if max_artifacts_per_family > 0 and counts[family] >= max_artifacts_per_family:
            continue
        selected.append(item)
        counts[family] += 1
    return selected


def _normalize_inventory_item(
    item: Mapping[str, object],
    *,
    root: Path,
    max_records_per_artifact: int,
) -> dict[str, object]:
    inventory_family = str(item.get("family") or "unknown")
    artifact_path = str(item.get("artifactPath") or "")
    normalizer_family, normalizer_path, skip_reason = _normalizer_target(item, root=root)
    base = {
        "inventoryFamily": inventory_family,
        "artifactPath": artifact_path,
        "normalizerFamily": normalizer_family,
    }
    if skip_reason:
        return {
            **base,
            "status": STATUS_SKIPPED,
            "skipReason": skip_reason,
            "normalizedRecordCount": 0,
            "emittedRecordCount": 0,
            "metricReadiness": [],
            "unknownReasons": [skip_reason],
        }
    try:
        normalized = normalize_artifact(str(normalizer_family), normalizer_path).to_dict()
    except Exception as exc:  # pragma: no cover - exercised through malformed local artifacts, not fixtures.
        return {
            **base,
            "status": STATUS_ERROR,
            "skipReason": f"normalization_error: {type(exc).__name__}: {exc}",
            "normalizedRecordCount": 0,
            "emittedRecordCount": 0,
            "metricReadiness": [],
            "unknownReasons": [f"normalization_error: {type(exc).__name__}"],
        }
    records = normalized.get("normalizedRecords") if isinstance(normalized.get("normalizedRecords"), list) else []
    emitted_records = records
    truncated = False
    if max_records_per_artifact > 0 and len(records) > max_records_per_artifact:
        emitted_records = records[:max_records_per_artifact]
        truncated = True
    readiness = normalized.get("metricReadiness") if isinstance(normalized.get("metricReadiness"), list) else []
    unknown_reasons = _unknown_reasons(readiness)
    return {
        **base,
        "status": STATUS_NORMALIZED,
        "reason": "normalized through Phase 9D sidecar normalizer",
        "normalizedRecordCount": normalized.get("recordCount", len(records)),
        "emittedRecordCount": len(emitted_records),
        "recordOutputTruncated": truncated,
        "skippedUnsafeFieldCount": normalized.get("skippedUnsafeFieldCount", 0),
        "metricReadiness": readiness,
        "unknownReasons": unknown_reasons,
        "qualityNotes": normalized.get("qualityNotes", []),
        "normalization": {
            key: value
            for key, value in normalized.items()
            if key not in {"normalizedRecords", "metricReadiness", "qualityNotes"}
        },
        "normalizedRecords": emitted_records,
    }


def _normalizer_target(item: Mapping[str, object], *, root: Path) -> tuple[str | None, Path, str | None]:
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


def _unknown_reasons(readiness: Sequence[object]) -> list[str]:
    reasons = []
    for item in readiness:
        if not isinstance(item, Mapping):
            continue
        if item.get("status") == STATUS_AVAILABLE:
            continue
        reasons.append(str(item.get("reason") or "unknown_reason"))
    return reasons


def _summary(results: Sequence[Mapping[str, object]]) -> dict[str, object]:
    status_counts = Counter(str(item.get("status")) for item in results)
    coverage: dict[str, dict[str, object]] = {}
    reason_counts: Counter[str] = Counter()
    normalized_records = 0
    emitted_records = 0
    skipped_unsafe = 0
    available_metric_count = 0
    for item in results:
        family = str(item.get("inventoryFamily") or "unknown")
        bucket = coverage.setdefault(
            family,
            {
                "artifactCount": 0,
                "normalizedArtifactCount": 0,
                "normalizedRecordCount": 0,
                "emittedRecordCount": 0,
                "availableMetricCount": 0,
                "skippedUnsafeFieldCount": 0,
            },
        )
        bucket["artifactCount"] = int(bucket["artifactCount"]) + 1
        if item.get("status") == STATUS_NORMALIZED:
            bucket["normalizedArtifactCount"] = int(bucket["normalizedArtifactCount"]) + 1
        record_count = int(item.get("normalizedRecordCount") or 0)
        emitted_count = int(item.get("emittedRecordCount") or 0)
        unsafe_count = int(item.get("skippedUnsafeFieldCount") or 0)
        normalized_records += record_count
        emitted_records += emitted_count
        skipped_unsafe += unsafe_count
        bucket["normalizedRecordCount"] = int(bucket["normalizedRecordCount"]) + record_count
        bucket["emittedRecordCount"] = int(bucket["emittedRecordCount"]) + emitted_count
        bucket["skippedUnsafeFieldCount"] = int(bucket["skippedUnsafeFieldCount"]) + unsafe_count
        for readiness in item.get("metricReadiness", []):
            if isinstance(readiness, Mapping) and readiness.get("status") == STATUS_AVAILABLE:
                available_metric_count += 1
                bucket["availableMetricCount"] = int(bucket["availableMetricCount"]) + 1
        for reason in item.get("unknownReasons", []):
            reason_counts[str(reason)] += 1
    return {
        "artifactCount": len(results),
        "normalizedArtifactCount": status_counts.get(STATUS_NORMALIZED, 0),
        "skippedArtifactCount": status_counts.get(STATUS_SKIPPED, 0),
        "errorArtifactCount": status_counts.get(STATUS_ERROR, 0),
        "normalizedRecordCount": normalized_records,
        "emittedRecordCount": emitted_records,
        "skippedUnsafeFieldCount": skipped_unsafe,
        "availableMetricCount": available_metric_count,
        "statusCounts": dict(sorted(status_counts.items())),
        "coverageByFamily": coverage,
        "unknownReasonCounts": dict(sorted(reason_counts.items())),
    }


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
        raise ValueError(f"Batch normalization output contains forbidden production text: {', '.join(sorted(found))}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch-normalize local artifact corpus into shadow sidecar inputs.")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository/artifact root to inspect.")
    parser.add_argument("--inventory-json", help="Optional Phase 10A inventory JSON to reuse.")
    parser.add_argument("--max-artifacts-per-family", type=int, default=10, help="Representative cap per inventory family.")
    parser.add_argument("--max-records-per-artifact", type=int, default=200, help="Cap normalized records emitted per artifact; 0 disables.")
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

    report = batch_normalize_from_inventory(
        inventory_report,
        root=root,
        max_artifacts_per_family=args.max_artifacts_per_family,
        max_records_per_artifact=args.max_records_per_artifact,
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
        write_batch_outputs(report, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
