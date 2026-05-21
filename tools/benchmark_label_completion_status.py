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
REQUIRED_FIELDS = label_schema.REQUIRED_LABEL_FIELDS
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


def _candidate_csvs(directory: Path) -> list[Path]:
    root = _resolve(directory) or directory
    if not root.exists():
        return []
    patterns = (
        "benchmark_label_priority_template_*.csv",
        "benchmark_case_level_template_*.csv",
        "benchmark_case_level_draft_labels_*.csv",
        "*benchmark*label*.csv",
        "*human*label*.csv",
    )
    seen: dict[Path, None] = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.name.startswith("benchmark_labeling_workbench_"):
                continue
            seen[path] = None
    return sorted(seen, key=lambda item: (item.stat().st_mtime, item.name), reverse=True)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _status_for_csv(path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = [{key: _text(value) for key, value in row.items()} for row in reader]
    except OSError:
        fieldnames = []
        rows = []
    schema = label_schema.detect_schema(fieldnames)
    schema_type = schema.get("schemaType", label_schema.SCHEMA_UNKNOWN_OR_INVALID)
    missing_columns = list(schema.get("missingRequiredColumns") or [])
    usable = 0
    draft_assisted = 0
    invalid = 0
    missing = 0
    partial = 0
    filled_required = 0
    for row in rows:
        if missing_columns:
            missing += 1
            continue
        if not label_schema.missing_required_label_fields(row):
            filled_required += 1
        status, _fields = label_schema.label_status(row)
        if status == "usable_label":
            usable += 1
        elif status == "draft_assisted_label":
            draft_assisted += 1
        elif status == "invalid_label":
            invalid += 1
        elif status == "partial_required_label":
            partial += 1
            missing += 1
        else:
            missing += 1
    if usable >= 12 and invalid == 0:
        status = "ready_for_readiness_gate"
    elif usable > 0 and invalid == 0:
        status = "partially_labeled_needs_more_rows"
    elif draft_assisted > 0 and invalid == 0:
        status = "draft_assisted_only"
    elif invalid > 0:
        status = "invalid_labels_need_fix"
    elif rows:
        status = "blank_or_unlabeled_template"
    else:
        status = "empty_or_unreadable_csv"
    has_required_columns = not missing_columns and schema_type != label_schema.SCHEMA_UNKNOWN_OR_INVALID
    appears_final_human_filled = usable > 0
    appears_human_filled = appears_final_human_filled
    recommended_command = (
        f"python3 tools/benchmark_label_readiness_gate.py --labels-csv \"{path}\""
        if usable > 0 and invalid == 0
        else ""
    )
    return {
        "path": str(path),
        "rowCount": len(rows),
        "fieldnames": fieldnames,
        "schemaType": schema_type,
        "candidateSchemaType": schema.get("candidateSchemaType", ""),
        "idField": schema.get("idField", ""),
        "missingRequiredColumns": missing_columns,
        "hasRequiredColumns": has_required_columns,
        "appearsHumanFilled": appears_human_filled,
        "appearsLabelFieldsFilled": filled_required > 0,
        "appearsFinalHumanFilled": appears_final_human_filled,
        "appearsDraftAssisted": draft_assisted > 0,
        "filledRequiredLabelRows": filled_required,
        "usableLabelRows": usable,
        "finalHumanUsableLabelRows": usable,
        "draftAssistedLabelRows": draft_assisted,
        "invalidLabelRows": invalid,
        "partialRequiredLabelRows": partial,
        "missingRequiredLabelRows": missing,
        "completionStatus": status,
        "draftAssistedLabelsCountedUsable": False,
        "recommendedReadinessCommand": recommended_command,
        "modelBehaviorChanged": False,
    }


def build_status(*, input_dir: Path = DEFAULT_INPUT_DIR, labels_csv_path: Path | None = None) -> dict[str, Any]:
    explicit = _resolve(labels_csv_path) if labels_csv_path else None
    if explicit:
        csv_rows = [_status_for_csv(explicit)]
    else:
        csv_rows = [_status_for_csv(path) for path in _candidate_csvs(input_dir)]
    best_ready = next((row for row in csv_rows if row.get("completionStatus") == "ready_for_readiness_gate"), None)
    partial = next((row for row in csv_rows if row.get("completionStatus") == "partially_labeled_needs_more_rows"), None)
    draft = next((row for row in csv_rows if row.get("completionStatus") == "draft_assisted_only"), None)
    selected = best_ready or partial or draft or (csv_rows[0] if csv_rows else None)
    latest_template = _latest_file(input_dir, "benchmark_label_priority_template_*.csv")
    selected_usable = int(selected.get("usableLabelRows", 0) if selected else 0)
    selected_invalid = int(selected.get("invalidLabelRows", 0) if selected else 0)
    selected_missing = int(selected.get("missingRequiredLabelRows", 0) if selected else 0)
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_label_completion_status",
        "summary": {
            "csvFileCount": len(csv_rows),
            "candidateCsvCount": len(csv_rows),
            "candidateFilledCsvCount": sum(1 for row in csv_rows if row.get("appearsHumanFilled")),
            "candidateFinalHumanFilledCsvCount": sum(1 for row in csv_rows if row.get("appearsFinalHumanFilled")),
            "candidateDraftAssistedCsvCount": sum(1 for row in csv_rows if row.get("appearsDraftAssisted")),
            "latestTemplateCsvPath": str(latest_template or ""),
            "bestLabelsCsvPath": str(selected.get("path", "") if selected and selected_usable > 0 else ""),
            "selectedLabelsCsvPath": str(selected.get("path", "") if selected else ""),
            "selectedSchemaType": str(selected.get("schemaType", "") if selected else ""),
            "selectedCompletionStatus": str(selected.get("completionStatus", "missing") if selected else "missing"),
            "selectedUsableLabelRows": selected_usable,
            "usableLabelRows": selected_usable,
            "selectedDraftAssistedLabelRows": int(selected.get("draftAssistedLabelRows", 0) if selected else 0),
            "draftAssistedLabelRows": int(selected.get("draftAssistedLabelRows", 0) if selected else 0),
            "draftAssistedLabelsCountedUsable": False,
            "invalidLabelRows": selected_invalid,
            "blankTemplateRows": selected_missing if selected and selected.get("completionStatus") == "blank_or_unlabeled_template" else 0,
            "readyCsvCount": sum(1 for row in csv_rows if row.get("completionStatus") == "ready_for_readiness_gate"),
            "partialCsvCount": sum(1 for row in csv_rows if row.get("completionStatus") == "partially_labeled_needs_more_rows"),
            "draftAssistedCsvCount": sum(1 for row in csv_rows if row.get("completionStatus") == "draft_assisted_only"),
            "blankTemplateCsvCount": sum(1 for row in csv_rows if row.get("completionStatus") == "blank_or_unlabeled_template"),
            "readinessGateRecommended": selected_usable > 0 and selected_invalid == 0,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "allowedValues": {
            "expectedAnalystDisposition": sorted(ALLOWED_ANALYST_DISPOSITIONS),
            "humanLabelConfidence": sorted(ALLOWED_CONFIDENCE),
        },
        "csvRows": csv_rows,
        "recommendedNextCommand": (
            f"python3 tools/benchmark_label_readiness_gate.py --labels-csv \"{selected.get('path')}\""
            if selected and selected_usable > 0
            else "Fill the latest benchmark_label_priority_template_*.csv before running label readiness as evidence."
        ),
        "stopConditions": [
            "Do not infer labels automatically.",
            "Do not treat blank templates as human labels.",
            "Do not use labels to change scoring, gates, HER routing, funding eligibility, or candidate admission.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Benchmark Label Completion Status",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Candidate CSVs: {summary.get('candidateCsvCount', 0)}",
        f"- Latest template CSV: {summary.get('latestTemplateCsvPath', '')}",
        f"- Selected CSV: {summary.get('selectedLabelsCsvPath', '')}",
        f"- Selected schema: `{summary.get('selectedSchemaType', '')}`",
        f"- Selected status: `{summary.get('selectedCompletionStatus', '')}`",
        f"- Selected usable labels: {summary.get('selectedUsableLabelRows', 0)}",
        f"- Selected draft-assisted labels: {summary.get('selectedDraftAssistedLabelRows', 0)}",
        f"- Ready CSVs: {summary.get('readyCsvCount', 0)}",
        f"- Partial CSVs: {summary.get('partialCsvCount', 0)}",
        f"- Draft-assisted CSVs: {summary.get('draftAssistedCsvCount', 0)}",
        f"- Blank templates: {summary.get('blankTemplateCsvCount', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## CSV Rows",
    ]
    for row in payload.get("csvRows") or []:
        if isinstance(row, Mapping):
            lines.append(
                f"- `{row.get('completionStatus', '')}` usable={row.get('usableLabelRows', 0)} "
                f"draft={row.get('draftAssistedLabelRows', 0)} invalid={row.get('invalidLabelRows', 0)} "
                f"schema={row.get('schemaType', '')}: {row.get('path', '')}"
            )
    lines.extend(["", "## Recommended Next Command", "", str(payload.get("recommendedNextCommand", "")), "", "## Stop Conditions"])
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"benchmark_label_completion_status_{stamp}.json"
    markdown_path = resolved / f"benchmark_label_completion_status_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect whether benchmark label CSVs have human-filled labels.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--labels-csv", type=Path, default=None)
    args = parser.parse_args(argv)
    payload = build_status(input_dir=args.input_dir, labels_csv_path=args.labels_csv)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Benchmark label completion status JSON: {outputs['json_path']}")
    print(f"Benchmark label completion status markdown: {outputs['markdown_path']}")
    print(f"Selected status: {payload.get('summary', {}).get('selectedCompletionStatus', '')}")
    print(f"Usable labels: {payload.get('summary', {}).get('selectedUsableLabelRows', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
