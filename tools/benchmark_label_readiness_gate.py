from __future__ import annotations

import argparse
import csv
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


def _merged_labels(row: Mapping[str, Any], csv_overlay: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
    labels = row.get("labelFields") if isinstance(row.get("labelFields"), Mapping) else {}
    merged = {field: _text(labels.get(field)) for field in (*REQUIRED_LABEL_FIELDS, *OPTIONAL_LABEL_FIELDS)}
    overlay = csv_overlay.get(_text(row.get("localCaseId"))) or {}
    for field in (*REQUIRED_LABEL_FIELDS, *OPTIONAL_LABEL_FIELDS):
        if _text(overlay.get(field)):
            merged[field] = _text(overlay.get(field))
    return merged


def _row_readiness(row: Mapping[str, Any], labels: Mapping[str, str]) -> dict[str, Any]:
    label_row = dict(labels)
    missing_required = label_schema.missing_required_label_fields(label_row)
    invalid = label_schema.invalid_label_fields(label_row)
    disposition = _text(labels.get("expectedAnalystDisposition"))
    confidence = _text(labels.get("humanLabelConfidence")).lower()
    status, status_fields = label_schema.label_status(label_row)
    usable = status == "usable_label"
    if status == "draft_assisted_label":
        missing_required = []
        invalid = []
    elif status == "partial_required_label":
        missing_required = status_fields
    return {
        "localCaseId": row.get("localCaseId", ""),
        "caseId": row.get("localCaseId", ""),
        "sourceType": row.get("sourceType", ""),
        "eventSlug": row.get("eventSlug", ""),
        "market": row.get("market", ""),
        "wallet": row.get("wallet", ""),
        "expectedAnalystDisposition": disposition,
        "humanLabelConfidence": confidence,
        "freshValidationRequired": _text(labels.get("freshValidationRequired")) or "unknown",
        "labelStatus": status,
        "draftAssisted": status == "draft_assisted_label",
        "missingRequiredLabelFields": missing_required,
        "invalidLabelFields": invalid,
        "allowedUse": "reporting_regression_expectation_only" if usable else "draft_dry_run_only" if status == "draft_assisted_label" else "labeling_workbench_only",
        "forbiddenUse": "Do not change scoring, gates, HER routing, funding eligibility, candidate admission, suppressors, or thresholds from these labels without separate approval and fresh validation.",
        "modelBehaviorChanged": False,
    }


def _case_level_readiness_row(row: Mapping[str, str]) -> dict[str, Any]:
    status, status_fields = label_schema.label_status(row)
    invalid = status_fields if status == "invalid_label" else []
    missing = status_fields if status in {"missing_required_label", "partial_required_label"} else []
    return {
        "benchmarkCaseId": row.get("benchmarkCaseId", ""),
        "caseId": row.get("benchmarkCaseId", ""),
        "sourceType": label_schema.case_source_type(row),
        "eventSlug": row.get("eventSlug", ""),
        "market": row.get("marketQuestion", ""),
        "marketSlug": row.get("marketSlug", ""),
        "conditionId": row.get("conditionId", ""),
        "wallet": row.get("wallet", ""),
        "tradeId": row.get("tradeId", ""),
        "expectedAnalystDisposition": _text(row.get("expectedAnalystDisposition")),
        "humanLabelConfidence": _text(row.get("humanLabelConfidence")).lower(),
        "freshValidationRequired": _text(row.get("freshValidationRequired")) or "unknown",
        "labelStatus": status,
        "draftAssisted": status == "draft_assisted_label",
        "missingRequiredLabelFields": missing,
        "invalidLabelFields": invalid,
        "allowedUse": (
            "reporting_regression_expectation_only"
            if status == "usable_label"
            else "draft_dry_run_only"
            if status == "draft_assisted_label"
            else "labeling_workbench_only"
        ),
        "forbiddenUse": "Do not change scoring, gates, HER routing, funding eligibility, candidate admission, suppressors, or thresholds from these labels without separate approval and fresh validation.",
        "modelBehaviorChanged": False,
    }


def _build_case_level_readiness(
    *,
    labels_csv_path: Path | None,
    min_usable_labels: int,
) -> dict[str, Any]:
    fieldnames, rows = label_schema.read_csv(_resolve(labels_csv_path) if labels_csv_path else None)
    schema = label_schema.detect_schema(fieldnames)
    readiness_rows = [_case_level_readiness_row(row) for row in rows]
    usable_count = sum(1 for row in readiness_rows if row.get("labelStatus") == "usable_label")
    draft_count = sum(1 for row in readiness_rows if row.get("labelStatus") == "draft_assisted_label")
    invalid_count = sum(1 for row in readiness_rows if row.get("labelStatus") == "invalid_label")
    missing_count = sum(1 for row in readiness_rows if row.get("labelStatus") in {"missing_required_label", "partial_required_label"})
    fresh_required = sum(1 for row in readiness_rows if str(row.get("freshValidationRequired") or "").lower() in {"yes", "true", "1"})
    if usable_count <= 0 and draft_count > 0 and invalid_count == 0:
        status = "draft_assisted_only_not_human_valid"
    elif usable_count <= 0:
        status = "unlabeled_template_only"
    elif invalid_count > 0:
        status = "partially_labeled_with_invalid_rows"
    elif usable_count < min_usable_labels:
        status = "partially_labeled_needs_more_rows"
    else:
        status = "ready_for_reporting_regression_only"
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_label_readiness_gate",
        "schemaType": schema.get("schemaType", label_schema.SCHEMA_UNKNOWN_OR_INVALID),
        "sourceWorkbenchPath": "",
        "sourceLabelsCsvPath": str(labels_csv_path or ""),
        "summary": {
            "schemaType": schema.get("schemaType", label_schema.SCHEMA_UNKNOWN_OR_INVALID),
            "sourceRowCount": len(rows),
            "usableLabeledRows": usable_count,
            "finalHumanUsableLabelRows": usable_count,
            "draftAssistedLabelRows": draft_count,
            "draftAssistedLabelsCountedUsable": False,
            "invalidLabelRows": invalid_count,
            "missingRequiredLabelRows": missing_count,
            "freshValidationRequiredRows": fresh_required,
            "minUsableLabelsForReportingRegression": min_usable_labels,
            "readinessStatus": status,
            "assumesManualFinalizationForNonDraftRows": usable_count > 0,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "readinessRows": readiness_rows,
        "allowedUses": [
            "Human-final case-level rows may support future reporting/regression expectations only.",
            "Rows marked DRAFT_ASSISTED_NOT_FINAL are dry-run workflow rows only and are not final human labels.",
            "This gate can say whether the label set is usable as analyst evidence; it cannot authorize detector changes.",
        ],
        "stopConditions": [
            "Stop before treating draft-assisted rows as final human labels.",
            "Stop before treating unlabeled template rows as truth.",
            "Stop before changing scoring, Strong Risk gates, HER routing, funding eligibility, or candidate admission.",
            "Stop before using cache-only labels as production detector approval without fresh validation.",
        ],
    }


def build_readiness(
    payload: Mapping[str, Any],
    *,
    source_path: Path | None = None,
    labels_csv_path: Path | None = None,
    min_usable_labels: int = 12,
) -> dict[str, Any]:
    labels_schema = label_schema.detect_csv_schema(_resolve(labels_csv_path) if labels_csv_path else None)
    if labels_schema.get("candidateSchemaType") == label_schema.SCHEMA_CASE_LEVEL_BENCHMARK:
        return _build_case_level_readiness(labels_csv_path=labels_csv_path, min_usable_labels=min_usable_labels)
    rows = _label_rows(payload)
    csv_overlay = _read_csv_labels(labels_csv_path)
    readiness_rows = [_row_readiness(row, _merged_labels(row, csv_overlay)) for row in rows]
    usable_count = sum(1 for row in readiness_rows if row.get("labelStatus") == "usable_label")
    draft_count = sum(1 for row in readiness_rows if row.get("labelStatus") == "draft_assisted_label")
    invalid_count = sum(1 for row in readiness_rows if row.get("labelStatus") == "invalid_label")
    missing_count = sum(1 for row in readiness_rows if row.get("labelStatus") in {"missing_required_label", "partial_required_label"})
    fresh_required = sum(1 for row in readiness_rows if str(row.get("freshValidationRequired") or "").lower() in {"yes", "true", "1"})
    if usable_count <= 0 and draft_count > 0 and invalid_count == 0:
        status = "draft_assisted_only_not_human_valid"
    elif usable_count <= 0:
        status = "unlabeled_template_only"
    elif invalid_count > 0:
        status = "partially_labeled_with_invalid_rows"
    elif usable_count < min_usable_labels:
        status = "partially_labeled_needs_more_rows"
    else:
        status = "ready_for_reporting_regression_only"
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_label_readiness_gate",
        "schemaType": label_schema.SCHEMA_LEGACY_LOCAL_CASE,
        "sourceWorkbenchPath": str(source_path or ""),
        "sourceLabelsCsvPath": str(labels_csv_path or ""),
        "summary": {
            "schemaType": label_schema.SCHEMA_LEGACY_LOCAL_CASE,
            "sourceRowCount": len(rows),
            "usableLabeledRows": usable_count,
            "finalHumanUsableLabelRows": usable_count,
            "draftAssistedLabelRows": draft_count,
            "draftAssistedLabelsCountedUsable": False,
            "invalidLabelRows": invalid_count,
            "missingRequiredLabelRows": missing_count,
            "freshValidationRequiredRows": fresh_required,
            "minUsableLabelsForReportingRegression": min_usable_labels,
            "readinessStatus": status,
            "assumesManualFinalizationForNonDraftRows": usable_count > 0,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "readinessRows": readiness_rows,
        "allowedUses": [
            "Human-labeled rows may support future reporting/regression expectations only.",
            "This gate can say whether the label set is usable as analyst evidence; it cannot authorize detector changes.",
        ],
        "stopConditions": [
            "Stop before treating unlabeled template rows as truth.",
            "Stop before changing scoring, Strong Risk gates, HER routing, funding eligibility, or candidate admission.",
            "Stop before using cache-only labels as production detector approval without fresh validation.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Benchmark Label Readiness Gate",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Schema type: `{summary.get('schemaType', payload.get('schemaType', ''))}`",
        f"- Source rows: {summary.get('sourceRowCount', 0)}",
        f"- Usable labeled rows: {summary.get('usableLabeledRows', 0)}",
        f"- Draft-assisted rows: {summary.get('draftAssistedLabelRows', 0)}",
        f"- Invalid label rows: {summary.get('invalidLabelRows', 0)}",
        f"- Missing required label rows: {summary.get('missingRequiredLabelRows', 0)}",
        f"- Readiness status: `{summary.get('readinessStatus', '')}`",
        f"- Draft-assisted labels counted usable: {summary.get('draftAssistedLabelsCountedUsable', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## First Rows",
    ]
    for row in (payload.get("readinessRows") or [])[:30]:
        if isinstance(row, Mapping):
            case_id = row.get("localCaseId") or row.get("benchmarkCaseId") or row.get("caseId", "")
            lines.append(
                f"- `{case_id}` status={row.get('labelStatus', '')} "
                f"disposition={row.get('expectedAnalystDisposition') or 'missing'}"
            )
    lines.extend(["", "## Stop Conditions"])
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"benchmark_label_readiness_{stamp}.json"
    markdown_path = resolved / f"benchmark_label_readiness_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check whether human benchmark labels are usable for reporting-only regression evidence.")
    parser.add_argument("--workbench", type=Path, default=None)
    parser.add_argument("--labels-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-usable-labels", type=int, default=12)
    args = parser.parse_args(argv)
    source = args.workbench or _latest_file(DEFAULT_INPUT_DIR, "benchmark_labeling_workbench_*.json")
    payload = build_readiness(
        _load_json(source),
        source_path=source,
        labels_csv_path=args.labels_csv,
        min_usable_labels=args.min_usable_labels,
    )
    outputs = write_outputs(payload, args.output_dir)
    print(f"Benchmark label readiness JSON: {outputs['json_path']}")
    print(f"Benchmark label readiness markdown: {outputs['markdown_path']}")
    print(f"Readiness status: {payload.get('summary', {}).get('readinessStatus', '')}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
