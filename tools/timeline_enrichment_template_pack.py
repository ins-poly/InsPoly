#!/usr/bin/env python3
"""Create and validate human-curated timeline enrichment templates."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "timeline_enrichment_template_pack"
SCHEMA_VERSION = "timeline_enrichment_template_pack_v1"
DEFAULT_OUTPUT = Path("validation_outputs/timeline_enrichment_template_pack_20260525.json")
DEFAULT_TEMPLATE = Path("validation_outputs/timeline_enrichment_template_20260525.csv")
FIELDS = (
    "timeline_id",
    "event_slug",
    "market_slug",
    "condition_id",
    "source_url",
    "source_timestamp_utc",
    "catalyst",
    "public_outcome_at",
    "curator",
    "review_status",
    "notes",
)
REQUIRED_FIELDS = ("timeline_id", "source_url", "source_timestamp_utc", "catalyst")


def build_template_pack(rows: Sequence[Mapping[str, object]] | None = None) -> dict[str, object]:
    rows = list(rows or [])
    validation_rows = [_validate_row(row, index + 2) for index, row in enumerate(rows)]
    summary = {
        "templateFieldCount": len(FIELDS),
        "sampleRowCount": len(rows),
        "invalidSampleRowCount": sum(1 for row in validation_rows if row["errorCount"] > 0),
        "sourceUrlRequired": True,
        "timestampRequired": True,
        "catalystRequired": True,
        "timestampsInferred": False,
        "webFetched": False,
        "runtimeBehaviorChanged": False,
        "scoringChanged": False,
    }
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "gateDecision": "timeline_template_pack_ready",
        "summary": summary,
        "fields": [
            {
                "name": field,
                "required": field in REQUIRED_FIELDS,
                "purpose": _purpose(field),
            }
            for field in FIELDS
        ],
        "validationRows": validation_rows,
        "followUpGate": "timeline_enrichment_needs_human_curation",
    }


def write_outputs(
    payload: Mapping[str, object],
    *,
    output_path: str | Path = DEFAULT_OUTPUT,
    template_path: str | Path = DEFAULT_TEMPLATE,
) -> tuple[Path, Path]:
    output = Path(output_path)
    template = Path(template_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    template.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with template.open("w", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n").writeheader()
    return output, template


def load_rows(path: str | Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _validate_row(row: Mapping[str, object], line: int) -> dict[str, object]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if not str(row.get(field) or "").strip():
            errors.append(f"missing_required:{field}")
    timestamp = str(row.get("source_timestamp_utc") or "").strip()
    if timestamp:
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            errors.append("invalid_source_timestamp_utc")
    url = str(row.get("source_url") or "").strip()
    if url and not (url.startswith("https://") or url.startswith("http://")):
        errors.append("source_url_not_http")
    return {
        "csvLine": line,
        "timelineId": str(row.get("timeline_id") or "").strip(),
        "errorCount": len(errors),
        "errors": errors,
        "runtimeUseAllowed": False,
    }


def _purpose(field: str) -> str:
    if field == "source_url":
        return "Human-supplied citation URL; never fetched or inferred by this tool."
    if field == "source_timestamp_utc":
        return "Human-supplied UTC timestamp for the public source."
    if field == "catalyst":
        return "Human-readable public catalyst label."
    if field == "review_status":
        return "Human review marker; template rows are not runtime evidence by default."
    return "Optional matching/provenance field for future offline timeline enrichment."


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payload = build_template_pack(load_rows(args.input_csv) if args.input_csv else [])
    output, template = write_outputs(payload, output_path=args.output, template_path=args.template)
    if not args.quiet:
        print(f"gate: {payload['gateDecision']}")
        print(f"output: {output}")
        print(f"template: {template}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
