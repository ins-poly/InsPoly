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

from app.event_context import TIMELINE_FILENAMES

DEFAULT_OUTPUT_DIR = Path("timeline_context_outputs")
DEFAULT_DATA_DIRS = (
    Path(".inspoly"),
    Path(".inspoly_archive_researcher"),
    Path(".inspoly_event_forensic_analyzer"),
)
DEFAULT_REVIEW_PATTERNS = (
    (Path("review_packets"), "unique_review_packets_*.json"),
    (Path("event_forensic_outputs"), "event_forensic_*/event_analysis.json"),
    (Path("archive_outputs"), "archive_research_*.json"),
    (Path(".inspoly") / "reports", "scan_*.json"),
)


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _latest_files(directory: Path, pattern: str, *, limit: int = 3) -> list[Path]:
    root = _resolve(directory) or directory
    if not root.exists():
        return []
    return sorted(root.glob(pattern), key=lambda item: (item.stat().st_mtime, item.name), reverse=True)[:limit]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _timeline_rows(path: Path) -> tuple[int, str]:
    try:
        if path.suffix.lower() == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return len([row for row in raw if isinstance(row, Mapping)]), ""
            if isinstance(raw, Mapping):
                rows = raw.get("rows") if isinstance(raw.get("rows"), list) else raw.get("events")
                if isinstance(rows, list):
                    return len([row for row in rows if isinstance(row, Mapping)]), ""
            return 0, "json_has_no_rows_or_events"
        with path.open("r", encoding="utf-8", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle)), ""
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, csv.Error) as exc:
        return 0, type(exc).__name__


def _iter_mappings(value: Any) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        rows.append(value)
        for key, nested in value.items():
            if str(key) == "raw_metrics":
                continue
            if isinstance(nested, (Mapping, list)):
                rows.extend(_iter_mappings(nested))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (Mapping, list)):
                rows.extend(_iter_mappings(item))
    return rows


def _is_yes(value: Any) -> bool:
    return str(value or "").strip().lower() in {"yes", "true", "1"}


def _has_value(value: Any) -> bool:
    return str(value or "").strip() not in {"", "None", "none", "null"}


def _row_timeline_metrics(row: Mapping[str, Any]) -> dict[str, int]:
    raw = row.get("raw_metrics") if isinstance(row.get("raw_metrics"), Mapping) else {}
    source = {**{str(key): value for key, value in row.items()}, **{str(key): value for key, value in raw.items()}}
    return {
        "offlineTimelineMatchedYes": int(_is_yes(source.get("offline_timeline_matched"))),
        "offlineTimelineMatchedNo": int(str(source.get("offline_timeline_matched", "")).strip().lower() == "no"),
        "timelineIdPresent": int(_has_value(source.get("timeline_id"))),
        "timelineSourcePresent": int(_has_value(source.get("timeline_source"))),
        "publicKnowledgeAtPresent": int(_has_value(source.get("public_knowledge_at"))),
        "publicOutcomeAtPresent": int(_has_value(source.get("public_outcome_at"))),
        "staleResolutionAnnotationYes": int(_is_yes(source.get("stale_resolution_annotation"))),
    }


def _inspect_review_artifact(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    rows = _iter_mappings(payload)
    metrics = {
        "rowsInspected": 0,
        "offlineTimelineMatchedYes": 0,
        "offlineTimelineMatchedNo": 0,
        "timelineIdPresent": 0,
        "timelineSourcePresent": 0,
        "publicKnowledgeAtPresent": 0,
        "publicOutcomeAtPresent": 0,
        "staleResolutionAnnotationYes": 0,
    }
    for row in rows:
        row_metrics = _row_timeline_metrics(row)
        if any(row_metrics.values()) or "offline_timeline_matched" in row or "raw_metrics" in row:
            metrics["rowsInspected"] += 1
            for key, value in row_metrics.items():
                metrics[key] += value
    return {"path": str(path), **metrics}


def build_audit(
    data_dirs: Sequence[Path] = DEFAULT_DATA_DIRS,
    review_patterns: Sequence[tuple[Path, str]] = DEFAULT_REVIEW_PATTERNS,
) -> dict[str, Any]:
    data_dir_rows: list[dict[str, Any]] = []
    timeline_file_rows: list[dict[str, Any]] = []
    existing_timeline_file_count = 0
    timeline_row_count = 0
    malformed_file_count = 0
    for directory in data_dirs:
        resolved_dir = _resolve(directory) or directory
        expected_paths = [resolved_dir / filename for filename in TIMELINE_FILENAMES]
        existing_paths = [path for path in expected_paths if path.exists()]
        data_dir_rows.append(
            {
                "dataDir": str(resolved_dir),
                "exists": resolved_dir.exists(),
                "expectedTimelineFiles": [str(path) for path in expected_paths],
                "existingTimelineFileCount": len(existing_paths),
            }
        )
        for path in existing_paths:
            row_count, error = _timeline_rows(path)
            existing_timeline_file_count += 1
            timeline_row_count += row_count
            malformed_file_count += int(bool(error))
            timeline_file_rows.append(
                {
                    "path": str(path),
                    "rowCount": row_count,
                    "loadError": error,
                }
            )
    artifact_rows: list[dict[str, Any]] = []
    for directory, pattern in review_patterns:
        for path in _latest_files(directory, pattern):
            artifact_rows.append(_inspect_review_artifact(path))
    review_rows_inspected = sum(int(row.get("rowsInspected") or 0) for row in artifact_rows)
    offline_matched_yes = sum(int(row.get("offlineTimelineMatchedYes") or 0) for row in artifact_rows)
    public_knowledge_count = sum(int(row.get("publicKnowledgeAtPresent") or 0) for row in artifact_rows)
    stale_annotation_count = sum(int(row.get("staleResolutionAnnotationYes") or 0) for row in artifact_rows)
    if existing_timeline_file_count <= 0:
        coverage_status = "no_local_timeline_files"
    elif malformed_file_count > 0:
        coverage_status = "timeline_files_present_with_load_errors"
    elif timeline_row_count <= 0:
        coverage_status = "timeline_files_present_empty"
    elif offline_matched_yes <= 0 and review_rows_inspected > 0:
        coverage_status = "timeline_files_present_no_saved_matches_observed"
    else:
        coverage_status = "timeline_coverage_observed"
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "offline_timeline_coverage_audit",
        "summary": {
            "coverageStatus": coverage_status,
            "dataDirCount": len(data_dir_rows),
            "existingTimelineFileCount": existing_timeline_file_count,
            "timelineRowCount": timeline_row_count,
            "malformedTimelineFileCount": malformed_file_count,
            "reviewArtifactCount": len(artifact_rows),
            "reviewRowsInspected": review_rows_inspected,
            "offlineTimelineMatchedYesCount": offline_matched_yes,
            "publicKnowledgeAtPresentCount": public_knowledge_count,
            "staleResolutionAnnotationYesCount": stale_annotation_count,
            "implementationApproved": False,
            "timelineDataChanged": False,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "dataDirRows": data_dir_rows,
        "timelineFileRows": timeline_file_rows,
        "reviewArtifactRows": artifact_rows,
        "recommendedActions": [
            "If public-lag quality is important, prepare a separate human-curated timeline data task.",
            "Do not ingest news, journalism, intelligence feeds, or external signals automatically from this audit.",
            "Do not change scoring or gates because timeline files are absent.",
        ],
        "readyToCopyNextPrompt": (
            "Create a human-curated offline timeline data RFC/template only. Inspect app/event_context.py and "
            "timeline_context_outputs/offline_timeline_coverage_audit_*.json. Define allowed CSV/JSON fields, "
            "example rows, validation checks, and stop conditions. Do not add external feeds, infer public timestamps, "
            "or change scoring/gates/HER/funding/candidate admission."
        ),
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Offline Timeline Coverage Audit",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Coverage status: `{summary.get('coverageStatus', '')}`",
        f"- Existing timeline files: {summary.get('existingTimelineFileCount', 0)}",
        f"- Timeline rows: {summary.get('timelineRowCount', 0)}",
        f"- Review artifacts inspected: {summary.get('reviewArtifactCount', 0)}",
        f"- Review rows inspected: {summary.get('reviewRowsInspected', 0)}",
        f"- Offline timeline matched rows: {summary.get('offlineTimelineMatchedYesCount', 0)}",
        f"- Public knowledge timestamps present: {summary.get('publicKnowledgeAtPresentCount', 0)}",
        f"- Timeline data changed: {summary.get('timelineDataChanged', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Data Directories",
    ]
    for row in payload.get("dataDirRows") or []:
        if isinstance(row, Mapping):
            lines.append(
                f"- `{row.get('dataDir', '')}` exists={row.get('exists', False)} "
                f"timelineFiles={row.get('existingTimelineFileCount', 0)}"
            )
    lines.extend(["", "## Timeline Files"])
    for row in payload.get("timelineFileRows") or []:
        if isinstance(row, Mapping):
            lines.append(f"- `{row.get('path', '')}` rows={row.get('rowCount', 0)} error={row.get('loadError', '')}")
    if not payload.get("timelineFileRows"):
        lines.append("- No local timeline files found.")
    lines.extend(["", "## Review Artifact Timeline Signals"])
    for row in payload.get("reviewArtifactRows") or []:
        if isinstance(row, Mapping):
            lines.append(
                f"- `{row.get('path', '')}` rows={row.get('rowsInspected', 0)}, "
                f"matched={row.get('offlineTimelineMatchedYes', 0)}, "
                f"publicKnowledge={row.get('publicKnowledgeAtPresent', 0)}"
            )
    lines.extend(["", "## Recommended Actions"])
    for item in payload.get("recommendedActions") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Ready-To-Copy Next Prompt", "", str(payload.get("readyToCopyNextPrompt", ""))])
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"offline_timeline_coverage_audit_{stamp}.json"
    markdown_path = resolved / f"offline_timeline_coverage_audit_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit offline timeline coverage without changing detector behavior.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    payload = build_audit()
    outputs = write_outputs(payload, args.output_dir)
    print(f"Offline timeline coverage JSON: {outputs['json_path']}")
    print(f"Offline timeline coverage markdown: {outputs['markdown_path']}")
    print(f"Coverage status: {payload.get('summary', {}).get('coverageStatus', '')}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
