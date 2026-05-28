#!/usr/bin/env python3
"""Inventory local Event Forensic performance evidence.

This sidecar reads saved report JSON files only. It intentionally skips raw
event bundles and never runs Event Forensic analysis or performs network calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "event_forensic_performance_inventory"
SCHEMA_VERSION = "event_forensic_performance_inventory_v1"
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_performance_inventory_20260525.json")
DEFAULT_MAX_BYTES = 5_500_000
DEFAULT_MAX_FILES = 160

REPORT_FILENAMES = {
    "event_analysis.json",
}
REPORT_PREFIX = "event_forensic_"
TIMING_FIELDS = (
    "resolve_input_seconds",
    "collect_event_trades_seconds",
    "trade_collection_elapsed_seconds",
    "prefetch_wallet_context_seconds",
    "prepare_candidate_context_seconds",
    "prefetch_funding_context_seconds",
    "score_candidates_seconds",
    "collect_price_history_seconds",
    "related_market_scan_seconds",
    "assemble_report_rows_seconds",
    "total_seconds",
)
BOTTLENECK_FIELDS = (
    "collect_event_trades_seconds",
    "prefetch_wallet_context_seconds",
    "prepare_candidate_context_seconds",
    "prefetch_funding_context_seconds",
    "score_candidates_seconds",
    "collect_price_history_seconds",
    "related_market_scan_seconds",
    "assemble_report_rows_seconds",
)


def discover_report_paths(root: str | Path = ".", *, max_files: int = DEFAULT_MAX_FILES) -> list[Path]:
    base = Path(root)
    paths: list[Path] = []
    patterns = (
        ".inspoly/reports/event_forensic_*.json",
        "event_forensic_outputs/event_forensic_*/event_analysis.json",
        "event_forensic_outputs/event_forensic_*.json",
        "validation_outputs/*event_forensic*.json",
        "tests/fixtures/**/event_analysis.json",
        "tests/fixtures/**/event_forensic*.json",
    )
    for pattern in patterns:
        for path in base.glob(pattern):
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "raw_event_bundle" in path.parts:
                continue
            paths.append(path)
            if len(paths) >= max_files:
                return sorted(set(paths))
    return sorted(set(paths))


def build_performance_inventory(
    root: str | Path = ".",
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, object]:
    report_rows: list[dict[str, object]] = []
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
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            skipped_invalid += 1
            continue
        if not _looks_like_event_forensic_report(payload):
            continue
        report_rows.append(_report_row(path, payload, size))

    summary = _summary(report_rows, skipped_large, skipped_invalid)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "root": str(Path(root)),
        "maxFiles": max_files,
        "maxBytes": max_bytes,
        "summary": summary,
        "timingFieldStats": _timing_field_stats(report_rows),
        "slowestReports": sorted(
            report_rows,
            key=lambda row: float(row.get("totalSeconds") or 0.0),
            reverse=True,
        )[:25],
        "largestSkippedFiles": sorted(skipped_large, key=lambda row: int(row["sizeBytes"]), reverse=True)[:25],
    }


def write_inventory(report: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _looks_like_event_forensic_report(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if isinstance(payload.get("performance"), Mapping) and (
        "event" in payload or "analysis_scope" in payload or "analysisScope" in payload
    ):
        return True
    export_files = payload.get("export_files")
    return isinstance(export_files, Mapping) and "event_analysis_json_path" in export_files


def _report_row(path: Path, payload: Mapping[str, object], size: int) -> dict[str, object]:
    performance = payload.get("performance") if isinstance(payload.get("performance"), Mapping) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    event = payload.get("event") if isinstance(payload.get("event"), Mapping) else {}
    settings = payload.get("analysis_settings") if isinstance(payload.get("analysis_settings"), Mapping) else {}
    scope = _scope_label(payload)
    timings = {field: _float_or_none(performance.get(field)) for field in TIMING_FIELDS}
    total = timings.get("total_seconds")
    if total is None:
        total = _float_or_none(performance.get("totalSeconds"))
    bottleneck = _dominant_bottleneck(timings)
    candidate_count = _int_or_none(
        summary.get("normal_candidate_trade_count")
        or summary.get("candidate_trade_count")
        or performance.get("candidate_trade_count_visible")
    )
    return {
        "path": str(path),
        "sizeBytes": size,
        "generatedAt": str(payload.get("generated_at") or payload.get("generatedAt") or ""),
        "status": str(payload.get("status") or ""),
        "analysisScope": scope,
        "primaryScoringScope": str(payload.get("primaryScoringScope") or summary.get("primaryScoringScope") or ""),
        "legacyAnalysisScope": str(payload.get("analysis_scope") or settings.get("analysis_scope") or ""),
        "eventSlug": str(payload.get("eventSlug") or event.get("slug") or payload.get("parent_event_slug") or ""),
        "eventTitle": str(event.get("title") or ""),
        "selectedMarketSlug": str(
            payload.get("selectedMarketSlug")
            or payload.get("selected_market_slug")
            or settings.get("selected_market_slug")
            or ""
        ),
        "analysisMarketCount": _int_or_none(summary.get("analysis_market_count") or event.get("analysisMarketCount")),
        "totalEventMarketCount": _int_or_none(summary.get("total_event_market_count") or event.get("marketCount")),
        "candidateTradeCount": candidate_count,
        "candidateWalletCount": _int_or_none(performance.get("candidate_wallet_count")),
        "visibleCandidateCount": _int_or_none(summary.get("display_trade_count")),
        "walletContextCount": _int_or_none(summary.get("wallet_context_count") or performance.get("wallet_context_count")),
        "rawTradeCount": _int_or_none(summary.get("raw_trade_count") or performance.get("trade_collection_raw_trade_rows")),
        "truncatedMarketCount": _int_or_none(
            summary.get("truncated_market_count")
            or performance.get("trade_collection_truncated_markets")
            or performance.get("truncated_market_count")
        ),
        "collectionRiskClass": str(performance.get("trade_collection_risk_class") or ""),
        "dominantBottleneck": bottleneck,
        "totalSeconds": total,
        "timings": {field: value for field, value in timings.items() if value is not None},
    }


def _scope_label(payload: Mapping[str, object]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    settings = payload.get("analysis_settings") if isinstance(payload.get("analysis_settings"), Mapping) else {}
    product = str(payload.get("analysisScope") or summary.get("analysisScope") or "").strip()
    if product:
        return product
    legacy = str(payload.get("analysis_scope") or settings.get("analysis_scope") or "").strip()
    if legacy == "market":
        return "selected_market"
    if legacy == "event":
        return "whole_event"
    return "unknown"


def _dominant_bottleneck(timings: Mapping[str, float | None]) -> str:
    present = {field: timings.get(field) for field in BOTTLENECK_FIELDS if timings.get(field) is not None}
    if not present:
        return "unknown"
    return max(present.items(), key=lambda item: float(item[1] or 0.0))[0]


def _summary(rows: Sequence[Mapping[str, object]], skipped_large: Sequence[Mapping[str, object]], skipped_invalid: int) -> dict[str, object]:
    scope_counts = Counter(str(row.get("analysisScope") or "unknown") for row in rows)
    bottleneck_counts = Counter(str(row.get("dominantBottleneck") or "unknown") for row in rows)
    whole_event = [row for row in rows if row.get("analysisScope") == "whole_event"]
    selected_market = [row for row in rows if row.get("analysisScope") == "selected_market"]
    slowest = max((float(row.get("totalSeconds") or 0.0) for row in rows), default=0.0)
    return {
        "reportsDiscovered": len(rows) + len(skipped_large) + skipped_invalid,
        "reportsLoaded": len(rows),
        "skippedTooLarge": len(skipped_large),
        "skippedInvalid": skipped_invalid,
        "selectedMarketRunCount": len(selected_market),
        "wholeEventRunCount": len(whole_event),
        "unknownScopeRunCount": scope_counts["unknown"],
        "scopeCounts": dict(sorted(scope_counts.items())),
        "dominantBottleneckCounts": dict(sorted(bottleneck_counts.items())),
        "slowestTotalSeconds": round(slowest, 2),
        "slowestWholeEventSeconds": round(max((float(row.get("totalSeconds") or 0.0) for row in whole_event), default=0.0), 2),
        "maxCandidateTradeCount": max((_int_or_none(row.get("candidateTradeCount")) or 0 for row in rows), default=0),
        "maxWalletContextCount": max((_int_or_none(row.get("walletContextCount")) or 0 for row in rows), default=0),
        "maxAnalysisMarketCount": max((_int_or_none(row.get("analysisMarketCount")) or 0 for row in rows), default=0),
        "runsWithTruncatedMarkets": sum(1 for row in rows if (_int_or_none(row.get("truncatedMarketCount")) or 0) > 0),
    }


def _timing_field_stats(rows: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    values_by_field: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        timings = row.get("timings")
        if not isinstance(timings, Mapping):
            continue
        for field, value in timings.items():
            numeric = _float_or_none(value)
            if numeric is not None:
                values_by_field[field].append(numeric)
    stats: dict[str, dict[str, object]] = {}
    for field in TIMING_FIELDS:
        values = values_by_field.get(field, [])
        if not values:
            stats[field] = {"count": 0, "max": None, "average": None}
            continue
        stats[field] = {
            "count": len(values),
            "max": round(max(values), 2),
            "average": round(sum(values) / len(values), 2),
        }
    return stats


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_performance_inventory(args.root, max_files=args.max_files, max_bytes=args.max_bytes)
    output = write_inventory(report, args.output)
    if not args.quiet:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
