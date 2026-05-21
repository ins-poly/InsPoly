from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = Path("timeline_context_outputs")
DEFAULT_OUTPUT_DIR = Path("timeline_context_outputs")
CSV_FIELDS = [
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
]
REQUIRED_FOR_STRONG_MATCH = ("condition_id", "market_id", "market_slug", "slug", "event_slug", "question")
TIMESTAMP_FIELDS = ("broad_report_at", "official_confirmation_at", "public_outcome_at")


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


def build_template_pack(audit_payload: Mapping[str, Any] | None = None, *, audit_path: Path | None = None) -> dict[str, Any]:
    audit_payload = audit_payload or {}
    audit_summary = audit_payload.get("summary") if isinstance(audit_payload.get("summary"), Mapping) else {}
    field_rows = []
    for field in CSV_FIELDS:
        if field in REQUIRED_FOR_STRONG_MATCH:
            purpose = "Matcher identifier; at least one strong identifier should be filled for each real timeline row."
        elif field in TIMESTAMP_FIELDS:
            purpose = "UTC ISO timestamp used to distinguish public-lag context from suspicious pre-public timing."
        elif field == "event_timezone":
            purpose = "IANA timezone override for local event-time/off-hours interpretation."
        elif field == "stale_resolution":
            purpose = "Human-curated boolean indicating the market was stale relative to known public information."
        elif field in {"timeline_source", "source_note", "curator", "review_status"}:
            purpose = "Provenance/review field for human auditability; not a scoring input by itself."
        else:
            purpose = "Optional matching/context field used by app.event_context.EventContextResolver."
        field_rows.append(
            {
                "field": field,
                "required": field == "timeline_id",
                "purpose": purpose,
                "autoFilledByThisTool": False,
            }
        )
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "offline_timeline_template_pack",
        "sourceCoverageAuditPath": str(audit_path or ""),
        "summary": {
            "sourceCoverageStatus": audit_summary.get("coverageStatus", "unknown"),
            "templateFieldCount": len(CSV_FIELDS),
            "timestampFieldCount": len(TIMESTAMP_FIELDS),
            "strongMatcherFieldCount": len(REQUIRED_FOR_STRONG_MATCH),
            "templateRowsPreFilled": 0,
            "humanCurationRequired": True,
            "implementationApproved": False,
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
        "fieldRows": field_rows,
        "workflow": [
            "Copy the generated header-only CSV to a working file outside app data dirs.",
            "Have a human curator fill only verified public-timeline facts with source notes.",
            "Run a future validator before placing curated rows into .inspoly*/event_timelines.csv.",
            "Do not use this template as evidence until rows are manually filled and validated.",
        ],
        "stopConditions": [
            "Stop before adding journalism/news/intelligence feeds or automatic external ingestion.",
            "Stop before inferring timestamps from market prices or model outputs.",
            "Stop before changing scoring, gates, HER routing, funding eligibility, or candidate admission.",
            "Stop before placing unreviewed rows into runtime data dirs.",
        ],
        "readyToCopyNextPrompt": (
            "Create a validator for human-curated offline timeline CSV files. Inspect app/event_context.py and "
            "timeline_context_outputs/offline_timeline_template_pack_*.json/.csv. Validate required identifiers, "
            "IANA timezones, UTC timestamp parseability, duplicate timeline_id values, and review_status. "
            "Do not add external feeds, infer facts, change scoring/gates/HER/funding/candidate admission, or move "
            "rows into runtime data dirs."
        ),
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Offline Timeline Template Pack",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Source coverage status: `{summary.get('sourceCoverageStatus', '')}`",
        f"- Template fields: {summary.get('templateFieldCount', 0)}",
        f"- Template rows pre-filled: {summary.get('templateRowsPreFilled', 0)}",
        f"- Human curation required: {summary.get('humanCurationRequired', True)}",
        f"- Timeline data changed: {summary.get('timelineDataChanged', False)}",
        f"- External feeds added: {summary.get('externalFeedsAdded', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Fields",
    ]
    for row in payload.get("fieldRows") or []:
        if isinstance(row, Mapping):
            lines.append(f"- `{row.get('field', '')}` required={row.get('required', False)}: {row.get('purpose', '')}")
    lines.extend(["", "## Workflow"])
    for item in payload.get("workflow") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Stop Conditions"])
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Ready-To-Copy Next Prompt", "", str(payload.get("readyToCopyNextPrompt", ""))])
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"offline_timeline_template_pack_{stamp}.json"
    markdown_path = resolved / f"offline_timeline_template_pack_{stamp}.md"
    csv_path = resolved / f"offline_event_timelines_template_{stamp}.csv"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
    return {"json_path": str(json_path), "markdown_path": str(markdown_path), "csv_path": str(csv_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a header-only offline timeline template pack.")
    parser.add_argument("--audit", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    audit_path = args.audit or _latest_file(DEFAULT_INPUT_DIR, "offline_timeline_coverage_audit_*.json")
    payload = build_template_pack(_load_json(audit_path), audit_path=audit_path)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Offline timeline template JSON: {outputs['json_path']}")
    print(f"Offline timeline template markdown: {outputs['markdown_path']}")
    print(f"Offline timeline template CSV: {outputs['csv_path']}")
    print(f"Template rows pre-filled: {payload.get('summary', {}).get('templateRowsPreFilled', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
