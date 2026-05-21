from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = Path("timeline_context_outputs")
DEFAULT_OUTPUT_DIR = Path("timeline_context_outputs")
REQUIRED_COLUMNS = (
    "timeline_id",
    "condition_id",
    "market_id",
    "market_slug",
    "slug",
    "event_slug",
    "question",
    "question_contains",
    "event_timezone",
    "broad_report_at",
    "official_confirmation_at",
    "public_outcome_at",
    "stale_resolution",
    "reality_oracle_gap_label",
    "timeline_source",
    "source_note",
    "curator",
    "review_status",
)
IDENTIFIER_COLUMNS = ("condition_id", "market_id", "market_slug", "slug", "event_slug", "question", "question_contains")
TIMESTAMP_COLUMNS = ("broad_report_at", "official_confirmation_at", "public_outcome_at")
ALLOWED_REVIEW_STATUSES = {"draft", "reviewed", "approved", "rejected", ""}
ALLOWED_BOOL_VALUES = {"true", "false", "yes", "no", "1", "0", ""}


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


def _parse_timestamp(value: str) -> bool:
    if not value.strip():
        return True
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _valid_timezone(value: str) -> bool:
    if not value.strip():
        return True
    try:
        ZoneInfo(value.strip())
    except ZoneInfoNotFoundError:
        return False
    return True


def _read_csv(path: Path | None) -> tuple[list[str], list[dict[str, str]], str]:
    if not path:
        return [], [], "missing_csv_path"
    resolved = _resolve(path) or path
    try:
        with resolved.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return list(reader.fieldnames or []), [dict(row) for row in reader], ""
    except OSError as exc:
        return [], [], type(exc).__name__


def validate_csv(csv_path: Path | None = None) -> dict[str, Any]:
    source = csv_path or _latest_file(DEFAULT_INPUT_DIR, "offline_event_timelines_template_*.csv")
    headers, rows, load_error = _read_csv(source)
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in headers]
    unexpected_columns = [column for column in headers if column not in REQUIRED_COLUMNS]
    row_results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for index, row in enumerate(rows, start=2):
        errors: list[str] = []
        warnings: list[str] = []
        timeline_id = str(row.get("timeline_id") or "").strip()
        if not timeline_id:
            errors.append("missing_timeline_id")
        elif timeline_id in seen_ids:
            errors.append("duplicate_timeline_id")
            duplicate_ids.add(timeline_id)
        seen_ids.add(timeline_id)
        if not any(str(row.get(column) or "").strip() for column in IDENTIFIER_COLUMNS):
            errors.append("missing_match_identifier")
        if not any(str(row.get(column) or "").strip() for column in TIMESTAMP_COLUMNS):
            warnings.append("no_public_timeline_timestamp")
        for column in TIMESTAMP_COLUMNS:
            if not _parse_timestamp(str(row.get(column) or "")):
                errors.append(f"invalid_timestamp:{column}")
        if not _valid_timezone(str(row.get("event_timezone") or "")):
            errors.append("invalid_event_timezone")
        status = str(row.get("review_status") or "").strip().lower()
        if status not in ALLOWED_REVIEW_STATUSES:
            errors.append("invalid_review_status")
        stale = str(row.get("stale_resolution") or "").strip().lower()
        if stale not in ALLOWED_BOOL_VALUES:
            errors.append("invalid_stale_resolution")
        if status != "approved":
            warnings.append("row_not_approved_for_runtime_use")
        row_results.append(
            {
                "csvLine": index,
                "timelineId": timeline_id,
                "errorCount": len(errors),
                "warningCount": len(warnings),
                "errors": errors,
                "warnings": warnings,
                "runtimeUseAllowed": len(errors) == 0 and status == "approved",
            }
        )
    invalid_rows = [row for row in row_results if row["errorCount"] > 0]
    runtime_allowed_rows = [row for row in row_results if row["runtimeUseAllowed"]]
    if load_error:
        validation_status = "csv_load_error"
    elif missing_columns:
        validation_status = "invalid_missing_required_columns"
    elif not rows:
        validation_status = "template_only_no_rows"
    elif invalid_rows:
        validation_status = "invalid_rows_present"
    elif not runtime_allowed_rows:
        validation_status = "valid_rows_not_approved_for_runtime"
    else:
        validation_status = "valid_approved_rows_present"
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "offline_timeline_csv_validation",
        "sourceCsvPath": str(source or ""),
        "summary": {
            "validationStatus": validation_status,
            "rowCount": len(rows),
            "validApprovedRowCount": len(runtime_allowed_rows),
            "invalidRowCount": len(invalid_rows),
            "missingRequiredColumnCount": len(missing_columns),
            "unexpectedColumnCount": len(unexpected_columns),
            "duplicateTimelineIdCount": len(duplicate_ids),
            "csvLoadError": load_error,
            "runtimeDataChanged": False,
            "timelineDataChanged": False,
            "externalFeedsAdded": False,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "missingRequiredColumns": missing_columns,
        "unexpectedColumns": unexpected_columns,
        "rowResults": row_results,
        "stopConditions": [
            "Stop before copying rows into .inspoly*/event_timelines.csv unless validationStatus is valid_approved_rows_present.",
            "Stop before using non-approved rows as runtime evidence.",
            "Stop before adding external feeds or inferring timestamps automatically.",
            "Stop before changing scoring, gates, HER routing, funding eligibility, or candidate admission.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Offline Timeline CSV Validation",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Source CSV: {payload.get('sourceCsvPath', '')}",
        f"- Validation status: `{summary.get('validationStatus', '')}`",
        f"- Rows: {summary.get('rowCount', 0)}",
        f"- Valid approved rows: {summary.get('validApprovedRowCount', 0)}",
        f"- Invalid rows: {summary.get('invalidRowCount', 0)}",
        f"- Missing required columns: {summary.get('missingRequiredColumnCount', 0)}",
        f"- Runtime data changed: {summary.get('runtimeDataChanged', False)}",
        f"- External feeds added: {summary.get('externalFeedsAdded', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Row Results",
    ]
    for row in payload.get("rowResults") or []:
        if isinstance(row, Mapping):
            lines.append(
                f"- line {row.get('csvLine', '')} `{row.get('timelineId', '')}` "
                f"errors={row.get('errorCount', 0)} warnings={row.get('warningCount', 0)} "
                f"runtimeUseAllowed={row.get('runtimeUseAllowed', False)}"
            )
    if not payload.get("rowResults"):
        lines.append("- No rows to validate.")
    lines.extend(["", "## Stop Conditions"])
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"offline_timeline_csv_validation_{stamp}.json"
    markdown_path = resolved / f"offline_timeline_csv_validation_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a human-curated offline timeline CSV without applying it.")
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    payload = validate_csv(args.csv)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Offline timeline CSV validation JSON: {outputs['json_path']}")
    print(f"Offline timeline CSV validation markdown: {outputs['markdown_path']}")
    print(f"Validation status: {payload.get('summary', {}).get('validationStatus', '')}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
