#!/usr/bin/env python3
"""Audit local archive/Event Forensic completeness markers.

This sidecar reads bounded local report JSON files only. It does not run
scanners, fetch pages, mutate artifacts, or change runtime behavior.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "archive_event_completeness_audit"
SCHEMA_VERSION = "archive_event_completeness_audit_v1"
DEFAULT_OUTPUT = Path("validation_outputs/archive_event_completeness_audit_20260525.json")
DEFAULT_MAX_BYTES = 5_500_000
DEFAULT_MAX_FILES = 80


def discover_report_paths(root: str | Path = ".", *, max_files: int = DEFAULT_MAX_FILES) -> list[Path]:
    base = Path(root)
    patterns = (
        ".inspoly_archive_researcher/reports/archive_research_*.json",
        "archive_outputs/archive_research_*.json",
        "validation_outputs/*archive*.json",
        "tests/fixtures/**/*archive*.json",
        ".inspoly/reports/event_forensic_*.json",
        ".inspoly_event_forensic_analyzer/reports/event_forensic_*.json",
        "event_forensic_outputs/event_forensic_*/event_analysis.json",
        "event_forensic_outputs/event_forensic_*.json",
        "validation_outputs/*event_forensic*.json",
        "tests/fixtures/**/event_analysis.json",
        "tests/fixtures/**/*event_forensic*.json",
    )
    paths: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(base.glob(pattern)):
            if not path.is_file() or path.suffix.lower() != ".json":
                continue
            if ".git" in path.parts or "__pycache__" in path.parts or "raw_event_bundle" in path.parts:
                continue
            if path not in seen:
                seen.add(path)
                paths.append(path)
    if len(paths) <= max_files:
        return paths
    archive_paths = [path for path in paths if "archive" in str(path).lower()]
    event_paths = [path for path in paths if path not in archive_paths]
    archive_limit = max_files // 2
    event_limit = max_files - archive_limit
    selected = archive_paths[:archive_limit] + event_paths[:event_limit]
    if len(selected) < max_files:
        selected.extend(path for path in paths if path not in selected)
    return selected[:max_files]


def build_completeness_audit(
    root: str | Path = ".",
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    skipped_large: list[dict[str, object]] = []
    skipped_invalid = 0
    for path in discover_report_paths(root, max_files=max_files):
        try:
            size = path.stat().st_size
        except OSError:
            skipped_invalid += 1
            continue
        if size > max_bytes:
            skipped_large.append({"path": str(path), "sizeBytes": size})
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            skipped_invalid += 1
            continue
        if not isinstance(payload, Mapping):
            continue
        row = _audit_row(path, payload, size)
        if row["artifactFamily"] != "unknown":
            rows.append(row)
    summary = _summary(rows, skipped_large, skipped_invalid)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "root": str(Path(root)),
        "maxFiles": max_files,
        "maxBytes": max_bytes,
        "gateDecision": _gate(summary),
        "summary": summary,
        "artifactRows": rows[:120],
        "largestSkippedFiles": sorted(skipped_large, key=lambda item: int(item["sizeBytes"]), reverse=True)[:25],
        "limitations": [
            "Bounded local report scan only; raw event bundles are intentionally skipped.",
            "Likely truncation without markers is a heuristic requiring bounded live/API measurement before runtime changes.",
            "Selected-market scope is not treated as incomplete merely because sibling markets exist.",
        ],
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _audit_row(path: Path, payload: Mapping[str, object], size: int) -> dict[str, object]:
    family = _artifact_family(payload, path)
    scope = _scope(payload, family)
    counts = _counts(payload)
    marker_status = _truncation_marker_status(counts)
    classification, reasons = _classification(family, scope, counts, marker_status)
    risk = classification in {"truncated_reported", "likely_truncated_no_marker"}
    return {
        "path": str(path),
        "sizeBytes": size,
        "artifactFamily": family,
        "sourceType": "test_fixture" if "tests/fixtures" in path.parts else "local_report_or_output",
        "scope": scope,
        "completenessClassification": classification,
        "completenessReasons": reasons,
        "paginationMarkerStatus": marker_status,
        "candidateAdmissionMayBeAffected": bool(risk and family in {"archive", "event_forensic"}),
        "rankingMayBeAffected": bool(risk and family == "event_forensic"),
        **counts,
    }


def _artifact_family(payload: Mapping[str, object], path: Path) -> str:
    path_text = str(path).lower()
    if "archive" in path_text or "topic_scope" in payload or "range_start" in payload:
        return "archive"
    if "event_forensic" in path_text or "analysis_scope" in payload or "event" in payload:
        return "event_forensic"
    return "unknown"


def _scope(payload: Mapping[str, object], family: str) -> str:
    if family == "archive":
        return "archive_category"
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    settings = payload.get("analysis_settings") if isinstance(payload.get("analysis_settings"), Mapping) else {}
    value = str(payload.get("analysisScope") or summary.get("analysisScope") or "").strip()
    if value:
        return value
    legacy = str(payload.get("analysis_scope") or settings.get("analysis_scope") or "").strip()
    if legacy == "market":
        return "selected_market"
    if legacy == "event":
        return "whole_event"
    return "unknown"


def _counts(payload: Mapping[str, object]) -> dict[str, int | None]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    performance = payload.get("performance") if isinstance(payload.get("performance"), Mapping) else {}
    event = payload.get("event") if isinstance(payload.get("event"), Mapping) else {}
    return {
        "rawTradeCount": _int_or_none(
            _first_present(
                payload.get("raw_trade_count"),
                summary.get("raw_trade_count"),
                performance.get("trade_collection_raw_trade_rows"),
            )
        ),
        "filteredTradeCount": _int_or_none(_first_present(payload.get("filtered_trade_count"), summary.get("filtered_trade_count"))),
        "candidateTradeCount": _int_or_none(
            _first_present(
                payload.get("candidate_trade_count"),
                summary.get("candidate_trade_count"),
                summary.get("normal_candidate_trade_count"),
            )
        ),
        "analysisMarketCount": _int_or_none(
            _first_present(
                payload.get("analysis_market_count"),
                summary.get("analysis_market_count"),
                event.get("analysisMarketCount"),
                performance.get("trade_collection_market_total"),
            )
        ),
        "totalEventMarketCount": _int_or_none(
            _first_present(
                payload.get("total_event_market_count"),
                summary.get("total_event_market_count"),
                event.get("marketCount"),
            )
        ),
        "uniqueMarketCount": _int_or_none(_first_present(payload.get("unique_market_count"), summary.get("unique_market_count"))),
        "truncatedMarketCount": _int_or_none(
            _first_present(
                payload.get("truncated_market_count"),
                summary.get("truncated_market_count"),
                performance.get("truncated_market_count"),
                performance.get("trade_collection_truncated_markets"),
            )
        ),
    }


def _truncation_marker_status(counts: Mapping[str, int | None]) -> str:
    value = counts.get("truncatedMarketCount")
    if value is None:
        return "missing"
    if value > 0:
        return "present_positive"
    return "present_zero"


def _classification(
    family: str,
    scope: str,
    counts: Mapping[str, int | None],
    marker_status: str,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if marker_status == "present_positive":
        return "truncated_reported", ["truncated_market_count_positive"]
    has_any_count = any(value is not None for value in counts.values())
    if marker_status == "missing" and not has_any_count:
        return "insufficient_metadata", ["no_counts_or_truncation_marker"]
    raw_count = counts.get("rawTradeCount") or 0
    analysis_markets = counts.get("analysisMarketCount")
    total_markets = counts.get("totalEventMarketCount")
    if marker_status == "missing":
        if raw_count >= 3000:
            reasons.append("raw_trade_count_at_or_above_single_market_page_cap_heuristic")
        if scope == "whole_event" and analysis_markets is not None and total_markets is not None and analysis_markets < total_markets:
            reasons.append("whole_event_analysis_market_count_below_total_event_market_count")
        if reasons:
            return "likely_truncated_no_marker", reasons
        return "unknown_legacy", ["truncation_marker_missing_on_legacy_or_sidecar_payload"]
    if marker_status == "present_zero":
        if family == "event_forensic" and scope == "unknown":
            return "unknown_legacy", ["scope_unknown_even_with_zero_truncation_marker"]
        return "complete_local", ["zero_truncation_marker_present"]
    return "insufficient_metadata", ["unclassified_completeness_state"]


def _summary(rows: Sequence[Mapping[str, object]], skipped_large: Sequence[Mapping[str, object]], skipped_invalid: int) -> dict[str, object]:
    classifications = Counter(str(row.get("completenessClassification") or "unknown") for row in rows)
    families = Counter(str(row.get("artifactFamily") or "unknown") for row in rows)
    scopes = Counter(str(row.get("scope") or "unknown") for row in rows)
    return {
        "reportsEvaluated": len(rows),
        "skippedLargeReportCount": len(skipped_large),
        "skippedInvalidReportCount": skipped_invalid,
        "artifactFamilyCounts": dict(sorted(families.items())),
        "scopeCounts": dict(sorted(scopes.items())),
        "classificationCounts": dict(sorted(classifications.items())),
        "truncatedReportedCount": classifications.get("truncated_reported", 0),
        "likelyTruncatedNoMarkerCount": classifications.get("likely_truncated_no_marker", 0),
        "unknownLegacyCount": classifications.get("unknown_legacy", 0),
        "candidateAdmissionRiskReportCount": sum(1 for row in rows if row.get("candidateAdmissionMayBeAffected")),
        "rankingRiskReportCount": sum(1 for row in rows if row.get("rankingMayBeAffected")),
    }


def _gate(summary: Mapping[str, object]) -> str:
    if int(summary.get("likelyTruncatedNoMarkerCount") or 0) > 0:
        return "archive_event_completeness_needs_bounded_live_measurement"
    return "archive_event_completeness_local_ready"


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _first_present(*values: object) -> object:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payload = build_completeness_audit(args.root, max_files=args.max_files, max_bytes=args.max_bytes)
    write_json(payload, args.output)
    if not args.quiet:
        print(f"gate: {payload['gateDecision']}")
        print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
