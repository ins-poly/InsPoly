from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import benchmark_label_schema as label_schema  # noqa: E402

DEFAULT_INPUT_DIR = Path("known_case_benchmarks")
DEFAULT_OUTPUT_DIR = Path("known_case_benchmarks")
REQUIRED_LABEL_FIELDS = label_schema.REQUIRED_LABEL_FIELDS
OPTIONAL_LABEL_FIELDS = (
    "expectedDetectorDisposition",
    "humanFalsePositiveReason",
    "humanInsiderStyleReason",
    "freshValidationRequired",
    "notes",
)
ALLOWED_ANALYST_DISPOSITIONS = label_schema.ALLOWED_ANALYST_DISPOSITIONS
ALLOWED_CONFIDENCE = label_schema.ALLOWED_CONFIDENCE


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _latest_file(directory: Path, pattern: str) -> Path | None:
    root = _resolve(directory) or directory
    if not root.exists():
        return None
    candidates = sorted(root.glob(pattern), key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
    return candidates[0] if candidates else None


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _label_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("labelRows")
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _read_csv_labels(path: Path | None) -> dict[str, dict[str, str]]:
    resolved = _resolve(path) if path else None
    if not resolved or not resolved.exists():
        return {}
    rows: dict[str, dict[str, str]] = {}
    with resolved.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            local_id = _text(row.get("localCaseId"))
            if local_id:
                rows[local_id] = {key: _text(value) for key, value in row.items()}
    return rows


def _path_from_completion(payload: Mapping[str, Any]) -> Path | None:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    selected = _text(summary.get("selectedLabelsCsvPath"))
    return Path(selected) if selected else None


def _merged_labels(row: Mapping[str, Any], csv_overlay: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
    labels = row.get("labelFields") if isinstance(row.get("labelFields"), Mapping) else {}
    merged = {field: _text(labels.get(field)) for field in (*REQUIRED_LABEL_FIELDS, *OPTIONAL_LABEL_FIELDS)}
    overlay = csv_overlay.get(_text(row.get("localCaseId"))) or {}
    for field in (*REQUIRED_LABEL_FIELDS, *OPTIONAL_LABEL_FIELDS):
        if _text(overlay.get(field)):
            merged[field] = _text(overlay.get(field))
    return merged


def _label_status(labels: Mapping[str, str]) -> tuple[str, list[str]]:
    return label_schema.label_status(labels)


def _observed(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("observedLabels")
    return value if isinstance(value, Mapping) else {}


def _review_flags(disposition: str, observed: Mapping[str, Any], fresh_required: str) -> list[str]:
    flags: list[str] = []
    strong = bool(observed.get("strongRisk"))
    her = bool(observed.get("hardEvidenceReview"))
    if disposition == "likely_false_positive" and (strong or her):
        flags.append("human_likely_false_positive_on_observed_high_risk_row")
    if disposition == "plausible_insider_style" and not (strong or her):
        flags.append("human_plausible_insider_without_observed_strong_or_her")
    if disposition == "needs_fresh_validation" or fresh_required.lower() in {"yes", "true", "1"}:
        flags.append("fresh_validation_required")
    return flags


def _interpretation(disposition: str, status: str) -> str:
    if status == "draft_assisted_label":
        return "Draft-assisted suggestion only; not final human benchmark evidence."
    if status != "usable_label":
        return "No reporting expectation until a valid human label is present."
    if disposition == "likely_false_positive":
        return "Human expectation says this should be tracked as a likely false-positive reporting case."
    if disposition == "plausible_insider_style":
        return "Human expectation says this remains a plausible insider-style lead for reporting/regression review."
    if disposition == "needs_fresh_validation":
        return "Human expectation says no detector conclusion should be drawn until fresh validation exists."
    if disposition == "inconclusive":
        return "Human expectation says the row is inconclusive reporting context."
    if disposition == "reporting_only_control":
        return "Human expectation says this row is useful as a reporting control, not a detector change."
    if disposition == "ignore_not_benchmark":
        return "Human expectation says this row should be ignored as a benchmark row."
    return "Unknown reporting expectation."


def _case_level_observed(row: Mapping[str, Any]) -> dict[str, bool]:
    strong = _text(row.get("strongRiskFlag")).lower() == "yes"
    her = _text(row.get("hardEvidenceReviewFlag")).lower() == "yes"
    return {"strongRisk": strong, "hardEvidenceReview": her, "overlap": strong and her}


def _case_level_expectation_report(
    *,
    labels_csv_path: Path | None,
    preflight_payload: Mapping[str, Any] | None,
    readiness_payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    fieldnames, rows = label_schema.read_csv(_resolve(labels_csv_path) if labels_csv_path else None)
    schema = label_schema.detect_schema(fieldnames)
    expectation_rows: list[dict[str, Any]] = []
    disposition_counts: Counter[str] = Counter()
    detector_counts: Counter[str] = Counter()
    confidence_counts: Counter[str] = Counter()
    flag_counts: Counter[str] = Counter()
    usable = invalid = missing = draft = fresh_required_count = 0
    for row in rows:
        status, status_fields = _label_status(row)
        disposition = _text(row.get("expectedAnalystDisposition"))
        detector = _text(row.get("expectedDetectorDisposition"))
        confidence = _text(row.get("humanLabelConfidence")).lower()
        fresh_required = _text(row.get("freshValidationRequired")) or "unknown"
        observed = _case_level_observed(row)
        if status == "usable_label":
            usable += 1
            disposition_counts[disposition] += 1
            if detector:
                detector_counts[detector] += 1
            confidence_counts[confidence] += 1
        elif status == "draft_assisted_label":
            draft += 1
        elif status == "invalid_label":
            invalid += 1
        else:
            missing += 1
        if fresh_required.lower() in {"yes", "true", "1"}:
            fresh_required_count += 1
        flags = _review_flags(disposition, observed, fresh_required) if status == "usable_label" else []
        flag_counts.update(flags)
        expectation_rows.append(
            {
                "benchmarkCaseId": row.get("benchmarkCaseId", ""),
                "caseId": row.get("benchmarkCaseId", ""),
                "sourceType": label_schema.case_source_type(row),
                "sourceArtifact": row.get("sourceArtifact", ""),
                "eventSlug": row.get("eventSlug", ""),
                "market": row.get("marketQuestion", ""),
                "marketSlug": row.get("marketSlug", ""),
                "conditionId": row.get("conditionId", ""),
                "wallet": row.get("wallet", ""),
                "tradeId": row.get("tradeId", ""),
                "observedStrongRisk": observed["strongRisk"],
                "observedHardEvidenceReview": observed["hardEvidenceReview"],
                "observedOverlap": observed["overlap"],
                "observedSeverity": "case_level_saved_artifact",
                "expectedAnalystDisposition": disposition,
                "expectedDetectorDisposition": detector,
                "humanLabelConfidence": confidence,
                "freshValidationRequired": fresh_required,
                "labelStatus": status,
                "draftAssisted": status == "draft_assisted_label",
                "labelStatusFields": status_fields,
                "humanFalsePositiveReason": _text(row.get("humanFalsePositiveReason")),
                "humanInsiderStyleReason": _text(row.get("humanInsiderStyleReason")),
                "notes": _text(row.get("notes")),
                "reportingOnlyInterpretation": _interpretation(disposition, status),
                "reviewFlags": flags,
                "allowedUse": "reporting_regression_expectation_only" if status == "usable_label" else "draft_dry_run_only" if status == "draft_assisted_label" else "labeling_workbench_only",
                "forbiddenUse": "Do not use this row to change scoring, gates, HER routing, funding eligibility, or candidate admission without separate approval and fresh validation.",
                "modelBehaviorChanged": False,
            }
        )
    preflight_summary = preflight_payload.get("summary") if isinstance(preflight_payload, Mapping) and isinstance(preflight_payload.get("summary"), Mapping) else {}
    readiness_summary = readiness_payload.get("summary") if isinstance(readiness_payload, Mapping) and isinstance(readiness_payload.get("summary"), Mapping) else {}
    if usable <= 0 and draft > 0 and invalid == 0:
        expectation_status = "draft_assisted_only_not_human_evidence"
    elif usable <= 0:
        expectation_status = "no_human_labels_available"
    elif invalid > 0:
        expectation_status = "labels_present_with_invalid_rows"
    elif usable < 12:
        expectation_status = "partial_reporting_expectations"
    else:
        expectation_status = "reporting_expectations_ready"
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_label_expectation_report",
        "schemaType": schema.get("schemaType", label_schema.SCHEMA_UNKNOWN_OR_INVALID),
        "sourceWorkbenchPath": "",
        "sourceLabelsCsvPath": str(labels_csv_path or ""),
        "summary": {
            "schemaType": schema.get("schemaType", label_schema.SCHEMA_UNKNOWN_OR_INVALID),
            "expectationStatus": expectation_status,
            "sourceRowCount": len(rows),
            "usableLabeledRows": usable,
            "finalHumanUsableLabelRows": usable,
            "draftAssistedLabelRows": draft,
            "draftAssistedLabelsCountedUsable": False,
            "invalidLabelRows": invalid,
            "missingRequiredLabelRows": missing,
            "freshValidationRequiredRows": fresh_required_count,
            "dispositionCounts": dict(sorted(disposition_counts.items())),
            "expectedDetectorDispositionCounts": dict(sorted(detector_counts.items())),
            "confidenceCounts": dict(sorted(confidence_counts.items())),
            "reviewFlagCounts": dict(sorted(flag_counts.items())),
            "observedStrongRiskRows": sum(1 for row in expectation_rows if row.get("observedStrongRisk")),
            "observedHardEvidenceReviewRows": sum(1 for row in expectation_rows if row.get("observedHardEvidenceReview")),
            "observedOverlapRows": sum(1 for row in expectation_rows if row.get("observedOverlap")),
            "preflightStatus": preflight_summary.get("preflightStatus", "unknown"),
            "readinessStatus": readiness_summary.get("readinessStatus", "unknown"),
            "assumesManualFinalizationForNonDraftRows": usable > 0,
            "labelsAssignedByThisTool": 0,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "expectationRows": expectation_rows,
        "allowedUses": [
            "Use this report to understand human-final reporting/regression expectations after labels exist.",
            "Rows marked DRAFT_ASSISTED_NOT_FINAL remain dry-run workflow rows only.",
            "Use review flags as analyst review prompts only.",
        ],
        "stopConditions": [
            "Do not infer missing labels automatically.",
            "Do not count draft-assisted labels as final human evidence.",
            "Do not use human labels as production truth.",
            "Do not change scoring, gates, HER routing, funding eligibility, candidate admission, suppressors, or thresholds from this report.",
            "Do not treat saved-output/cache-only labels as fresh trace-enabled proof.",
        ],
    }


def build_expectation_report(
    workbench_payload: Mapping[str, Any],
    *,
    source_path: Path | None = None,
    labels_csv_path: Path | None = None,
    preflight_payload: Mapping[str, Any] | None = None,
    readiness_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    labels_schema = label_schema.detect_csv_schema(_resolve(labels_csv_path) if labels_csv_path else None)
    if labels_schema.get("candidateSchemaType") == label_schema.SCHEMA_CASE_LEVEL_BENCHMARK:
        return _case_level_expectation_report(
            labels_csv_path=labels_csv_path,
            preflight_payload=preflight_payload,
            readiness_payload=readiness_payload,
        )
    rows = _label_rows(workbench_payload)
    overlay = _read_csv_labels(labels_csv_path)
    expectation_rows: list[dict[str, Any]] = []
    disposition_counts: Counter[str] = Counter()
    detector_counts: Counter[str] = Counter()
    confidence_counts: Counter[str] = Counter()
    flag_counts: Counter[str] = Counter()
    usable = invalid = missing = fresh_required_count = 0
    for row in rows:
        labels = _merged_labels(row, overlay)
        status, status_fields = _label_status(labels)
        disposition = _text(labels.get("expectedAnalystDisposition"))
        detector = _text(labels.get("expectedDetectorDisposition"))
        confidence = _text(labels.get("humanLabelConfidence")).lower()
        fresh_required = _text(labels.get("freshValidationRequired")) or "unknown"
        observed = _observed(row)
        if status == "usable_label":
            usable += 1
            disposition_counts[disposition] += 1
            if detector:
                detector_counts[detector] += 1
            confidence_counts[confidence] += 1
        elif status == "draft_assisted_label":
            missing += 1
        elif status == "invalid_label":
            invalid += 1
        else:
            missing += 1
        if fresh_required.lower() in {"yes", "true", "1"}:
            fresh_required_count += 1
        flags = _review_flags(disposition, observed, fresh_required) if status == "usable_label" else []
        flag_counts.update(flags)
        expectation_rows.append(
            {
                "localCaseId": row.get("localCaseId", ""),
                "caseId": row.get("localCaseId", ""),
                "sourceType": row.get("sourceType", ""),
                "sourceArtifact": row.get("sourceArtifact", ""),
                "eventSlug": row.get("eventSlug", ""),
                "market": row.get("market", ""),
                "conditionId": row.get("conditionId", ""),
                "wallet": row.get("wallet", ""),
                "observedStrongRisk": bool(observed.get("strongRisk")),
                "observedHardEvidenceReview": bool(observed.get("hardEvidenceReview")),
                "observedOverlap": bool(observed.get("overlap")),
                "observedSeverity": observed.get("severity", "unknown"),
                "expectedAnalystDisposition": disposition,
                "expectedDetectorDisposition": detector,
                "humanLabelConfidence": confidence,
                "freshValidationRequired": fresh_required,
                "labelStatus": status,
                "draftAssisted": status == "draft_assisted_label",
                "labelStatusFields": status_fields,
                "humanFalsePositiveReason": _text(labels.get("humanFalsePositiveReason")),
                "humanInsiderStyleReason": _text(labels.get("humanInsiderStyleReason")),
                "notes": _text(labels.get("notes")),
                "reportingOnlyInterpretation": _interpretation(disposition, status),
                "reviewFlags": flags,
                "allowedUse": "reporting_regression_expectation_only" if status == "usable_label" else "labeling_workbench_only",
                "forbiddenUse": "Do not use this row to change scoring, gates, HER routing, funding eligibility, or candidate admission without separate approval and fresh validation.",
                "modelBehaviorChanged": False,
            }
        )
    preflight_summary = preflight_payload.get("summary") if isinstance(preflight_payload, Mapping) and isinstance(preflight_payload.get("summary"), Mapping) else {}
    readiness_summary = readiness_payload.get("summary") if isinstance(readiness_payload, Mapping) and isinstance(readiness_payload.get("summary"), Mapping) else {}
    if usable <= 0:
        expectation_status = "no_human_labels_available"
    elif invalid > 0:
        expectation_status = "labels_present_with_invalid_rows"
    elif usable < 12:
        expectation_status = "partial_reporting_expectations"
    else:
        expectation_status = "reporting_expectations_ready"
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_label_expectation_report",
        "schemaType": label_schema.SCHEMA_LEGACY_LOCAL_CASE,
        "sourceWorkbenchPath": str(source_path or ""),
        "sourceLabelsCsvPath": str(labels_csv_path or ""),
        "summary": {
            "schemaType": label_schema.SCHEMA_LEGACY_LOCAL_CASE,
            "expectationStatus": expectation_status,
            "sourceRowCount": len(rows),
            "usableLabeledRows": usable,
            "finalHumanUsableLabelRows": usable,
            "draftAssistedLabelRows": sum(1 for row in expectation_rows if row.get("draftAssisted")),
            "draftAssistedLabelsCountedUsable": False,
            "invalidLabelRows": invalid,
            "missingRequiredLabelRows": missing,
            "freshValidationRequiredRows": fresh_required_count,
            "dispositionCounts": dict(sorted(disposition_counts.items())),
            "expectedDetectorDispositionCounts": dict(sorted(detector_counts.items())),
            "confidenceCounts": dict(sorted(confidence_counts.items())),
            "reviewFlagCounts": dict(sorted(flag_counts.items())),
            "observedStrongRiskRows": sum(1 for row in expectation_rows if row.get("observedStrongRisk")),
            "observedHardEvidenceReviewRows": sum(1 for row in expectation_rows if row.get("observedHardEvidenceReview")),
            "observedOverlapRows": sum(1 for row in expectation_rows if row.get("observedOverlap")),
            "preflightStatus": preflight_summary.get("preflightStatus", "unknown"),
            "readinessStatus": readiness_summary.get("readinessStatus", "unknown"),
            "labelsAssignedByThisTool": 0,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "expectationRows": expectation_rows,
        "allowedUses": [
            "Use this report to understand human reporting/regression expectations after labels exist.",
            "Use review flags as analyst review prompts only.",
        ],
        "stopConditions": [
            "Do not infer missing labels automatically.",
            "Do not use human labels as production truth.",
            "Do not change scoring, gates, HER routing, funding eligibility, candidate admission, suppressors, or thresholds from this report.",
            "Do not treat saved-output/cache-only labels as fresh trace-enabled proof.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Benchmark Label Expectation Report",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Schema type: `{summary.get('schemaType', payload.get('schemaType', ''))}`",
        f"- Expectation status: `{summary.get('expectationStatus', '')}`",
        f"- Source rows: {summary.get('sourceRowCount', 0)}",
        f"- Usable labels: {summary.get('usableLabeledRows', 0)}",
        f"- Draft-assisted labels: {summary.get('draftAssistedLabelRows', 0)}",
        f"- Invalid labels: {summary.get('invalidLabelRows', 0)}",
        f"- Missing required labels: {summary.get('missingRequiredLabelRows', 0)}",
        f"- Fresh validation required rows: {summary.get('freshValidationRequiredRows', 0)}",
        f"- Preflight status: `{summary.get('preflightStatus', 'unknown')}`",
        f"- Readiness status: `{summary.get('readinessStatus', 'unknown')}`",
        f"- Draft-assisted labels counted usable: {summary.get('draftAssistedLabelsCountedUsable', False)}",
        f"- Labels assigned by this tool: {summary.get('labelsAssignedByThisTool', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Disposition Counts",
    ]
    disposition_counts = summary.get("dispositionCounts") if isinstance(summary.get("dispositionCounts"), Mapping) else {}
    if disposition_counts:
        for key, value in disposition_counts.items():
            lines.append(f"- `{key}`: {value}")
    else:
        lines.append("- No usable human labels yet.")
    lines.extend(["", "## Review Flag Counts"])
    flag_counts = summary.get("reviewFlagCounts") if isinstance(summary.get("reviewFlagCounts"), Mapping) else {}
    if flag_counts:
        for key, value in flag_counts.items():
            lines.append(f"- `{key}`: {value}")
    else:
        lines.append("- No review flags because no usable human labels are present.")
    lines.extend(["", "## First Rows"])
    for row in (payload.get("expectationRows") or [])[:25]:
        if isinstance(row, Mapping):
            case_id = row.get("localCaseId") or row.get("benchmarkCaseId") or row.get("caseId", "")
            lines.append(
                f"- `{case_id}` status={row.get('labelStatus', '')} "
                f"disposition={row.get('expectedAnalystDisposition') or 'missing'} "
                f"observedSR={row.get('observedStrongRisk', False)} observedHER={row.get('observedHardEvidenceReview', False)}"
            )
    lines.extend(["", "## Stop Conditions"])
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"benchmark_label_expectation_report_{stamp}.json"
    markdown_path = resolved / f"benchmark_label_expectation_report_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize reporting-only expectations from human benchmark labels.")
    parser.add_argument("--workbench", type=Path, default=None)
    parser.add_argument("--labels-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    workbench = args.workbench or _latest_file(DEFAULT_INPUT_DIR, "benchmark_labeling_workbench_*.json")
    completion = _load_json(_latest_file(DEFAULT_INPUT_DIR, "benchmark_label_completion_status_*.json"))
    preflight = _load_json(_latest_file(DEFAULT_INPUT_DIR, "benchmark_label_csv_preflight_*.json"))
    readiness = _load_json(_latest_file(DEFAULT_INPUT_DIR, "benchmark_label_readiness_*.json"))
    labels_csv = args.labels_csv or _path_from_completion(completion)
    payload = build_expectation_report(
        _load_json(workbench),
        source_path=workbench,
        labels_csv_path=labels_csv,
        preflight_payload=preflight,
        readiness_payload=readiness,
    )
    outputs = write_outputs(payload, args.output_dir)
    print(f"Benchmark label expectation report JSON: {outputs['json_path']}")
    print(f"Benchmark label expectation report markdown: {outputs['markdown_path']}")
    print(f"Expectation status: {payload.get('summary', {}).get('expectationStatus', '')}")
    print(f"Usable labels: {payload.get('summary', {}).get('usableLabeledRows', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
