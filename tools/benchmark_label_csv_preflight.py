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
IMMUTABLE_FIELDS = label_schema.LEGACY_IMMUTABLE_FIELDS
ALLOWED_ANALYST_DISPOSITIONS = label_schema.ALLOWED_ANALYST_DISPOSITIONS
ALLOWED_DETECTOR_DISPOSITIONS = label_schema.ALLOWED_DETECTOR_DISPOSITIONS
ALLOWED_CONFIDENCE = label_schema.ALLOWED_CONFIDENCE
ALLOWED_FRESH_VALIDATION = label_schema.ALLOWED_FRESH_VALIDATION


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


def _read_csv(path: Path | None) -> tuple[list[str], list[dict[str, str]]]:
    resolved = _resolve(path)
    if not resolved or not resolved.exists():
        return [], []
    try:
        with resolved.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = [{key: _text(value) for key, value in row.items()} for row in reader]
    except OSError:
        return [], []
    return fieldnames, rows


def _path_from_completion(completion_payload: Mapping[str, Any]) -> Path | None:
    summary = completion_payload.get("summary") if isinstance(completion_payload.get("summary"), Mapping) else {}
    selected = _text(summary.get("selectedLabelsCsvPath"))
    return Path(selected) if selected else None


def _row_by_case(rows: Sequence[Mapping[str, str]]) -> dict[str, Mapping[str, str]]:
    result: dict[str, Mapping[str, str]] = {}
    for row in rows:
        case_id = _text(row.get("localCaseId"))
        if case_id and case_id not in result:
            result[case_id] = row
    return result


def _duplicates(rows: Sequence[Mapping[str, str]]) -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for row in rows:
        case_id = _text(row.get("localCaseId"))
        if not case_id:
            continue
        if case_id in seen and case_id not in dupes:
            dupes.append(case_id)
        seen.add(case_id)
    return dupes


def _row_by_id(rows: Sequence[Mapping[str, str]], id_field: str) -> dict[str, Mapping[str, str]]:
    result: dict[str, Mapping[str, str]] = {}
    for row in rows:
        case_id = _text(row.get(id_field))
        if case_id and case_id not in result:
            result[case_id] = row
    return result


def _duplicates_for_id(rows: Sequence[Mapping[str, str]], id_field: str) -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for row in rows:
        case_id = _text(row.get(id_field))
        if not case_id:
            continue
        if case_id in seen and case_id not in dupes:
            dupes.append(case_id)
        seen.add(case_id)
    return dupes


def _blank_ids(rows: Sequence[Mapping[str, str]], id_field: str) -> int:
    return sum(1 for row in rows if not _text(row.get(id_field)))


def _label_row_status(row: Mapping[str, str]) -> tuple[str, list[str]]:
    return label_schema.label_status(row)


def _status_counts(rows: Sequence[Mapping[str, str]]) -> dict[str, int]:
    counts = {
        "usableLabelRows": 0,
        "draftAssistedLabelRows": 0,
        "invalidLabelRows": 0,
        "missingRequiredLabelRows": 0,
        "partialRequiredLabelRows": 0,
        "filledRequiredLabelRows": 0,
    }
    for row in rows:
        status, _fields = _label_row_status(row)
        if not label_schema.missing_required_label_fields(row):
            counts["filledRequiredLabelRows"] += 1
        if status == "usable_label":
            counts["usableLabelRows"] += 1
        elif status == "draft_assisted_label":
            counts["draftAssistedLabelRows"] += 1
        elif status == "invalid_label":
            counts["invalidLabelRows"] += 1
        elif status == "partial_required_label":
            counts["partialRequiredLabelRows"] += 1
        else:
            counts["missingRequiredLabelRows"] += 1
    return counts


def _standard_label_validation_status(counts: Mapping[str, int]) -> str:
    if int(counts.get("usableLabelRows") or 0) > 0:
        return "structure_ok_human_labeled"
    if int(counts.get("draftAssistedLabelRows") or 0) > 0:
        return "structure_ok_draft_assisted_only"
    return "structure_ok_unlabeled"


def _case_level_preflight(
    *,
    template_csv_path: Path | None,
    labels_csv_path: Path | None,
    template_fields: Sequence[str],
    template_rows: Sequence[Mapping[str, str]],
    label_fields: Sequence[str],
    label_rows: Sequence[Mapping[str, str]],
    label_detection: Mapping[str, Any],
    template_detection: Mapping[str, Any],
) -> dict[str, Any]:
    id_field = "benchmarkCaseId"
    missing_columns = list(label_detection.get("missingRequiredColumns") or [])
    duplicate_case_ids = _duplicates_for_id(label_rows, id_field)
    blank_id_count = _blank_ids(label_rows, id_field)
    label_by_case = _row_by_id(label_rows, id_field)
    template_by_case = _row_by_id(template_rows, id_field) if template_detection.get("schemaType") == label_schema.SCHEMA_CASE_LEVEL_BENCHMARK else {}
    missing_case_ids = sorted(set(template_by_case) - set(label_by_case)) if template_by_case else []
    unexpected_case_ids = sorted(set(label_by_case) - set(template_by_case)) if template_by_case else []
    immutable_mismatches: list[dict[str, Any]] = []
    if template_by_case:
        factual_fields = [field for field in label_schema.CASE_LEVEL_FACTUAL_FIELDS if field != id_field]
        for case_id, row in label_by_case.items():
            template_row = template_by_case.get(case_id, {})
            changed_fields = [
                field
                for field in factual_fields
                if _text(row.get(field)) != _text(template_row.get(field))
            ]
            if changed_fields:
                immutable_mismatches.append({"benchmarkCaseId": case_id, "changedFields": changed_fields})
    invalid_rows: list[dict[str, Any]] = []
    partial_rows: list[dict[str, Any]] = []
    for row in label_rows:
        status, fields = _label_row_status(row)
        if status == "invalid_label":
            invalid_rows.append({"benchmarkCaseId": _text(row.get(id_field)), "invalidFields": fields})
        elif status == "partial_required_label":
            partial_rows.append({"benchmarkCaseId": _text(row.get(id_field)), "missingRequiredFields": fields})
    counts = _status_counts(label_rows)
    structural_issue_count = (
        len(missing_columns)
        + len(duplicate_case_ids)
        + blank_id_count
        + len(missing_case_ids)
        + len(unexpected_case_ids)
        + len(immutable_mismatches)
        + len(partial_rows)
    )
    if not label_rows:
        status = "missing_inputs"
    elif structural_issue_count or invalid_rows:
        status = "structure_or_values_need_fix"
    else:
        status = _standard_label_validation_status(counts)
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_label_csv_preflight",
        "schemaType": label_schema.SCHEMA_CASE_LEVEL_BENCHMARK if not missing_columns else label_schema.SCHEMA_UNKNOWN_OR_INVALID,
        "templateSchemaType": template_detection.get("schemaType", label_schema.SCHEMA_UNKNOWN_OR_INVALID),
        "labelSchemaType": label_detection.get("schemaType", label_schema.SCHEMA_UNKNOWN_OR_INVALID),
        "sourceTemplateCsvPath": str(template_csv_path or ""),
        "sourceLabelsCsvPath": str(labels_csv_path or ""),
        "effectiveTemplateCsvPath": str(template_csv_path if template_by_case else labels_csv_path or ""),
        "summary": {
            "preflightStatus": status,
            "labelValidationStatus": status if status.startswith("structure_ok_") else "structure_or_values_need_fix",
            "schemaType": label_schema.SCHEMA_CASE_LEVEL_BENCHMARK if not missing_columns else label_schema.SCHEMA_UNKNOWN_OR_INVALID,
            "templateSchemaType": template_detection.get("schemaType", label_schema.SCHEMA_UNKNOWN_OR_INVALID),
            "labelSchemaType": label_detection.get("schemaType", label_schema.SCHEMA_UNKNOWN_OR_INVALID),
            "templateRowCount": len(template_rows) if template_by_case else len(label_rows),
            "labelRowCount": len(label_rows),
            "usableLabelRows": counts["usableLabelRows"],
            "finalHumanUsableLabelRows": counts["usableLabelRows"],
            "draftAssistedLabelRows": counts["draftAssistedLabelRows"],
            "filledRequiredLabelRows": counts["filledRequiredLabelRows"],
            "missingRequiredLabelRows": counts["missingRequiredLabelRows"],
            "partialRequiredLabelRows": counts["partialRequiredLabelRows"],
            "invalidLabelRows": len(invalid_rows),
            "missingRequiredColumnCount": len(missing_columns),
            "duplicateBenchmarkCaseIdCount": len(duplicate_case_ids),
            "blankBenchmarkCaseIdCount": blank_id_count,
            "missingTemplateCaseIdCount": len(missing_case_ids),
            "unexpectedCaseIdCount": len(unexpected_case_ids),
            "immutableFieldMismatchCount": len(immutable_mismatches),
            "readinessGateRecommended": counts["usableLabelRows"] >= 12 and not structural_issue_count and not invalid_rows,
            "draftAssistedLabelsCountedUsable": False,
            "assumesManualFinalizationForNonDraftRows": counts["usableLabelRows"] > 0,
            "labelsAssignedByThisTool": 0,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "templateFieldnames": list(template_fields),
        "labelFieldnames": list(label_fields),
        "missingRequiredColumns": missing_columns,
        "duplicateBenchmarkCaseIds": duplicate_case_ids,
        "blankBenchmarkCaseIdCount": blank_id_count,
        "missingTemplateCaseIds": missing_case_ids,
        "unexpectedCaseIds": unexpected_case_ids,
        "immutableFieldMismatches": immutable_mismatches,
        "invalidRows": invalid_rows,
        "partialRequiredRows": partial_rows,
        "recommendedNextCommand": (
            f"python3 tools/benchmark_label_readiness_gate.py --labels-csv \"{labels_csv_path}\""
            if counts["usableLabelRows"] >= 12 and status == "structure_ok_human_labeled"
            else "Fill or finalize case-level labels manually before using readiness as reporting evidence."
        ),
        "stopConditions": [
            "Do not infer labels automatically.",
            "Do not count DRAFT_ASSISTED_NOT_FINAL rows as final human labels.",
            "Do not repair CSV values by changing detector outputs.",
            "Do not use labels to change scoring, gates, HER routing, funding eligibility, or candidate admission.",
            "Do not treat saved-output/cache-only rows as fresh trace-enabled proof.",
        ],
    }


def build_preflight(
    *,
    template_csv_path: Path | None,
    labels_csv_path: Path | None,
) -> dict[str, Any]:
    template_fields, template_rows = _read_csv(template_csv_path)
    label_fields, label_rows = _read_csv(labels_csv_path)
    label_detection = label_schema.detect_schema(label_fields)
    template_detection = label_schema.detect_schema(template_fields)
    if label_detection.get("candidateSchemaType") == label_schema.SCHEMA_CASE_LEVEL_BENCHMARK:
        return _case_level_preflight(
            template_csv_path=template_csv_path,
            labels_csv_path=labels_csv_path,
            template_fields=template_fields,
            template_rows=template_rows,
            label_fields=label_fields,
            label_rows=label_rows,
            label_detection=label_detection,
            template_detection=template_detection,
        )
    template_by_case = _row_by_case(template_rows)
    label_by_case = _row_by_case(label_rows)
    missing_columns = [field for field in (*IMMUTABLE_FIELDS, *REQUIRED_LABEL_FIELDS) if field not in label_fields]
    duplicate_case_ids = _duplicates(label_rows)
    missing_case_ids = sorted(set(template_by_case) - set(label_by_case))
    unexpected_case_ids = sorted(set(label_by_case) - set(template_by_case))
    immutable_mismatches: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []
    usable = 0
    missing_required = 0
    for case_id, row in label_by_case.items():
        template_row = template_by_case.get(case_id, {})
        changed_fields = [
            field
            for field in IMMUTABLE_FIELDS
            if field != "localCaseId" and _text(row.get(field)) != _text(template_row.get(field))
        ]
        if changed_fields:
            immutable_mismatches.append({"localCaseId": case_id, "changedFields": changed_fields})
        disposition = _text(row.get("expectedAnalystDisposition"))
        confidence = _text(row.get("humanLabelConfidence")).lower()
        detector = _text(row.get("expectedDetectorDisposition"))
        fresh = _text(row.get("freshValidationRequired")).lower()
        invalid_fields: list[str] = []
        if disposition and disposition not in ALLOWED_ANALYST_DISPOSITIONS:
            invalid_fields.append("expectedAnalystDisposition")
        if confidence and confidence not in ALLOWED_CONFIDENCE:
            invalid_fields.append("humanLabelConfidence")
        if detector and detector not in ALLOWED_DETECTOR_DISPOSITIONS:
            invalid_fields.append("expectedDetectorDisposition")
        if fresh not in ALLOWED_FRESH_VALIDATION:
            invalid_fields.append("freshValidationRequired")
        if invalid_fields:
            invalid_rows.append({"localCaseId": case_id, "invalidFields": invalid_fields})
            continue
        if not disposition or not confidence:
            missing_required += 1
            continue
        usable += 1
    structural_issue_count = (
        len(missing_columns)
        + len(duplicate_case_ids)
        + len(missing_case_ids)
        + len(unexpected_case_ids)
        + len(immutable_mismatches)
    )
    if not template_rows or not label_rows:
        status = "missing_inputs"
    elif structural_issue_count or invalid_rows:
        status = "structure_or_values_need_fix"
    elif usable >= 12:
        status = "ready_for_readiness_gate"
    elif usable > 0:
        status = "partially_labeled_structure_ok"
    else:
        status = "structure_ok_unlabeled"
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_label_csv_preflight",
        "schemaType": label_schema.SCHEMA_LEGACY_LOCAL_CASE if not missing_columns else label_schema.SCHEMA_UNKNOWN_OR_INVALID,
        "templateSchemaType": template_detection.get("schemaType", label_schema.SCHEMA_UNKNOWN_OR_INVALID),
        "labelSchemaType": label_detection.get("schemaType", label_schema.SCHEMA_UNKNOWN_OR_INVALID),
        "sourceTemplateCsvPath": str(template_csv_path or ""),
        "sourceLabelsCsvPath": str(labels_csv_path or ""),
        "summary": {
            "preflightStatus": status,
            "labelValidationStatus": (
                "structure_ok_human_labeled"
                if usable > 0 and not structural_issue_count and not invalid_rows
                else "structure_ok_unlabeled"
                if status == "structure_ok_unlabeled"
                else "structure_or_values_need_fix"
                if status in {"missing_inputs", "structure_or_values_need_fix"}
                else status
            ),
            "schemaType": label_schema.SCHEMA_LEGACY_LOCAL_CASE if not missing_columns else label_schema.SCHEMA_UNKNOWN_OR_INVALID,
            "templateSchemaType": template_detection.get("schemaType", label_schema.SCHEMA_UNKNOWN_OR_INVALID),
            "labelSchemaType": label_detection.get("schemaType", label_schema.SCHEMA_UNKNOWN_OR_INVALID),
            "templateRowCount": len(template_rows),
            "labelRowCount": len(label_rows),
            "usableLabelRows": usable,
            "finalHumanUsableLabelRows": usable,
            "draftAssistedLabelRows": 0,
            "filledRequiredLabelRows": usable,
            "missingRequiredLabelRows": missing_required,
            "partialRequiredLabelRows": 0,
            "invalidLabelRows": len(invalid_rows),
            "missingRequiredColumnCount": len(missing_columns),
            "duplicateLocalCaseIdCount": len(duplicate_case_ids),
            "missingTemplateCaseIdCount": len(missing_case_ids),
            "unexpectedCaseIdCount": len(unexpected_case_ids),
            "immutableFieldMismatchCount": len(immutable_mismatches),
            "readinessGateRecommended": status == "ready_for_readiness_gate",
            "draftAssistedLabelsCountedUsable": False,
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
        "templateFieldnames": template_fields,
        "labelFieldnames": label_fields,
        "missingRequiredColumns": missing_columns,
        "duplicateLocalCaseIds": duplicate_case_ids,
        "missingTemplateCaseIds": missing_case_ids,
        "unexpectedCaseIds": unexpected_case_ids,
        "immutableFieldMismatches": immutable_mismatches,
        "invalidRows": invalid_rows,
        "recommendedNextCommand": (
            f"python3 tools/benchmark_label_readiness_gate.py --labels-csv \"{labels_csv_path}\""
            if status == "ready_for_readiness_gate"
            else "Fix CSV structure/values or fill required labels before running readiness as evidence."
        ),
        "stopConditions": [
            "Do not infer labels automatically.",
            "Do not repair CSV values by changing detector outputs.",
            "Do not use labels to change scoring, gates, HER routing, funding eligibility, or candidate admission.",
            "Do not treat saved-output/cache-only rows as fresh trace-enabled proof.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Benchmark Label CSV Preflight",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Template CSV: {payload.get('sourceTemplateCsvPath', '')}",
        f"- Labels CSV: {payload.get('sourceLabelsCsvPath', '')}",
        f"- Schema type: `{summary.get('schemaType', payload.get('schemaType', ''))}`",
        f"- Preflight status: `{summary.get('preflightStatus', '')}`",
        f"- Label validation status: `{summary.get('labelValidationStatus', '')}`",
        f"- Template rows: {summary.get('templateRowCount', 0)}",
        f"- Label rows: {summary.get('labelRowCount', 0)}",
        f"- Usable labels: {summary.get('usableLabelRows', 0)}",
        f"- Draft-assisted labels: {summary.get('draftAssistedLabelRows', 0)}",
        f"- Invalid label rows: {summary.get('invalidLabelRows', 0)}",
        f"- Missing required labels: {summary.get('missingRequiredLabelRows', 0)}",
        f"- Duplicate localCaseIds: {summary.get('duplicateLocalCaseIdCount', 0)}",
        f"- Duplicate benchmarkCaseIds: {summary.get('duplicateBenchmarkCaseIdCount', 0)}",
        f"- Immutable mismatches: {summary.get('immutableFieldMismatchCount', 0)}",
        f"- Readiness gate recommended: {summary.get('readinessGateRecommended', False)}",
        f"- Draft-assisted labels counted usable: {summary.get('draftAssistedLabelsCountedUsable', False)}",
        f"- Labels assigned by this tool: {summary.get('labelsAssignedByThisTool', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Recommended Next Command",
        "",
        str(payload.get("recommendedNextCommand", "")),
        "",
        "## Stop Conditions",
    ]
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"benchmark_label_csv_preflight_{stamp}.json"
    markdown_path = resolved / f"benchmark_label_csv_preflight_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight-check a benchmark label CSV before readiness gate use.")
    parser.add_argument("--template-csv", type=Path, default=None)
    parser.add_argument("--labels-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    completion = _load_json(_latest_file(DEFAULT_INPUT_DIR, "benchmark_label_completion_status_*.json"))
    template_csv = args.template_csv or _latest_file(DEFAULT_INPUT_DIR, "benchmark_label_priority_template_*.csv")
    labels_csv = args.labels_csv or _path_from_completion(completion) or template_csv
    labels_schema = label_schema.detect_csv_schema(_resolve(labels_csv) if labels_csv else None)
    if args.template_csv is None and labels_schema.get("candidateSchemaType") == label_schema.SCHEMA_CASE_LEVEL_BENCHMARK:
        template_csv = labels_csv
    payload = build_preflight(template_csv_path=template_csv, labels_csv_path=labels_csv)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Benchmark label CSV preflight JSON: {outputs['json_path']}")
    print(f"Benchmark label CSV preflight markdown: {outputs['markdown_path']}")
    print(f"Preflight status: {payload.get('summary', {}).get('preflightStatus', '')}")
    print(f"Usable labels: {payload.get('summary', {}).get('usableLabelRows', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
