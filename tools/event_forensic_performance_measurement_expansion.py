#!/usr/bin/env python3
"""Build an expanded bounded Event Forensic performance target pool."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.event_forensic_bounded_performance_measurement import MeasurementBounds
from tools.event_forensic_measurement_target_inventory import build_target_inventory


REPORT_TYPE = "event_forensic_performance_measurement_expansion_candidates"
SCHEMA_VERSION = "event_forensic_performance_measurement_expansion_candidates_v1"
DEFAULT_PREVIOUS_INVENTORY = Path("validation_outputs/event_forensic_measurement_target_inventory_20260525.json")
DEFAULT_PREVIOUS_RESOLUTION = Path("validation_outputs/event_forensic_measurement_target_resolution_20260525.json")
DEFAULT_PREVIOUS_MEASUREMENT = Path("validation_outputs/event_forensic_safe_target_performance_measurement_20260525.json")
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_performance_expansion_candidates_20260525.json")
DEFAULT_MAX_CANDIDATES = 12


def build_expansion_candidates(
    *,
    previous_inventory: Mapping[str, object],
    previous_resolution: Mapping[str, object],
    previous_measurement: Mapping[str, object],
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    bounds: MeasurementBounds = MeasurementBounds(),
    include_local_inventory: bool = True,
) -> dict[str, object]:
    measured_slugs = _measured_event_slugs(previous_measurement)
    candidates_by_slug: dict[str, dict[str, object]] = {}
    source_notes: dict[str, list[str]] = {}

    for row in _safe_unmeasured_resolution_rows(previous_resolution, measured_slugs):
        slug = _text(row.get("eventSlug"))
        if not slug:
            continue
        candidate = _candidate_from_resolution_row(row)
        candidates_by_slug[slug] = candidate
        source_notes.setdefault(slug, []).append("previous_safe_target_not_yet_measured")

    local_inventory = (
        build_target_inventory(max_candidates=max(max_candidates * 4, 24), bounds=bounds)
        if include_local_inventory
        else {"candidates": []}
    )
    for row in _candidate_rows(previous_inventory):
        _add_candidate(row, candidates_by_slug, source_notes, measured_slugs, "previous_target_inventory")
    for row in _candidate_rows(local_inventory):
        _add_candidate(row, candidates_by_slug, source_notes, measured_slugs, "rebuilt_local_performance_inventory")

    candidates = []
    for slug, candidate in candidates_by_slug.items():
        candidate["expansionSources"] = sorted(set(source_notes.get(slug, [])))
        candidate["alreadyMeasured"] = slug in measured_slugs
        candidate["expansionPriority"] = _candidate_priority(candidate)
        candidate["whySelectedForExpansion"] = _why_selected(candidate)
        candidates.append(candidate)
    candidates.sort(key=_sort_key, reverse=True)
    candidates = candidates[:max_candidates]
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "bounds": {
            **bounds.to_dict(),
            "maxNewTargetCandidatesToResolve": max_candidates,
        },
        "previousMeasuredEventSlugs": sorted(measured_slugs),
        "summary": {
            "candidateCount": len(candidates),
            "previousSafeUnmeasuredCount": sum(
                1 for item in candidates if "previous_safe_target_not_yet_measured" in item.get("expansionSources", [])
            ),
            "savedLocalSafeCount": sum(1 for item in candidates if item.get("savedLocalMeasurementSafe")),
            "withTruncationMarkerCount": sum(1 for item in candidates if _int_or_zero(item.get("savedTruncatedMarketCount")) > 0),
        },
        "candidates": candidates,
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def load_json_object(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _add_candidate(
    row: Mapping[str, object],
    candidates_by_slug: dict[str, dict[str, object]],
    source_notes: dict[str, list[str]],
    measured_slugs: set[str],
    source: str,
) -> None:
    slug = _text(row.get("eventSlug"))
    if not slug or slug in measured_slugs:
        return
    candidate = _candidate_from_inventory_row(row)
    existing = candidates_by_slug.get(slug)
    if existing is None or _candidate_priority(candidate) > _candidate_priority(existing):
        candidates_by_slug[slug] = candidate
    source_notes.setdefault(slug, []).append(source)


def _candidate_from_resolution_row(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "eventSlug": _text(row.get("eventSlug")),
        "eventTitle": _text(row.get("liveEventTitle")),
        "inputValue": _text(row.get("inputValue")),
        "analysisScope": "whole_event",
        "selectedMarketSlug": "",
        "savedAnalysisMarketCount": _int_or_zero(row.get("savedAnalysisMarketCount")),
        "savedTotalEventMarketCount": _int_or_zero(row.get("liveMarketCount")),
        "savedRawTradeCount": _int_or_zero(row.get("savedRawTradeCount")),
        "savedCandidateTradeCount": _int_or_zero(row.get("savedCandidateTradeCount")),
        "savedCandidateWalletCount": _int_or_zero(row.get("savedCandidateWalletCount")),
        "savedWalletContextCount": _int_or_zero(row.get("savedCandidateWalletCount")),
        "savedTruncatedMarketCount": _int_or_zero(row.get("savedTruncatedMarketCount")),
        "savedTotalSeconds": 0.0,
        "savedDominantBottleneck": "unknown",
        "sourceReportPath": _text(row.get("sourceReportPath")),
        "likelyWithinLiveMarketBound": True,
        "savedLocalMeasurementSafe": True,
        "savedBoundRiskReasons": [],
        "selectionSource": "previous_target_resolution",
    }


def _candidate_from_inventory_row(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "eventSlug": _text(row.get("eventSlug")),
        "eventTitle": _text(row.get("eventTitle")),
        "inputValue": _text(row.get("inputValue")),
        "analysisScope": _text(row.get("analysisScope")),
        "selectedMarketSlug": _text(row.get("selectedMarketSlug")),
        "savedAnalysisMarketCount": _int_or_zero(row.get("savedAnalysisMarketCount")),
        "savedTotalEventMarketCount": _int_or_zero(row.get("savedTotalEventMarketCount")),
        "savedRawTradeCount": _int_or_zero(row.get("savedRawTradeCount")),
        "savedCandidateTradeCount": _int_or_zero(row.get("savedCandidateTradeCount")),
        "savedCandidateWalletCount": _int_or_zero(row.get("savedCandidateWalletCount")),
        "savedWalletContextCount": _int_or_zero(row.get("savedWalletContextCount")),
        "savedTruncatedMarketCount": _int_or_zero(row.get("savedTruncatedMarketCount")),
        "savedTotalSeconds": _float_or_zero(row.get("savedTotalSeconds")),
        "savedDominantBottleneck": _text(row.get("savedDominantBottleneck")) or "unknown",
        "sourceReportPath": _text(row.get("sourceReportPath")),
        "likelyWithinLiveMarketBound": bool(row.get("likelyWithinLiveMarketBound")),
        "savedLocalMeasurementSafe": bool(row.get("savedLocalMeasurementSafe")),
        "savedBoundRiskReasons": list(row.get("savedBoundRiskReasons") or []),
        "selectionSource": _text(row.get("selectionSource")) or "local_performance_inventory",
    }


def _candidate_rows(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    rows = payload.get("candidates")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def _safe_unmeasured_resolution_rows(payload: Mapping[str, object], measured_slugs: set[str]) -> list[Mapping[str, object]]:
    rows = payload.get("resolvedCandidates")
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("safeForFullMeasurement"):
            continue
        if _text(row.get("eventSlug")) in measured_slugs:
            continue
        result.append(row)
    return result


def _measured_event_slugs(payload: Mapping[str, object]) -> set[str]:
    slugs: set[str] = set()
    measurement = payload.get("measurement") if isinstance(payload.get("measurement"), Mapping) else {}
    slug = _text(measurement.get("eventSlug"))
    if slug and payload.get("measurementGate") == "performance_measurement_complete":
        slugs.add(slug)
    return slugs


def _candidate_priority(candidate: Mapping[str, object]) -> int:
    safe = 1 if candidate.get("savedLocalMeasurementSafe") else 0
    likely = 1 if candidate.get("likelyWithinLiveMarketBound") else 0
    truncated = 1 if _int_or_zero(candidate.get("savedTruncatedMarketCount")) else 0
    multi_market = 1 if _int_or_zero(candidate.get("savedAnalysisMarketCount")) > 1 else 0
    return (
        safe * 10_000_000
        + likely * 1_000_000
        + multi_market * 100_000
        + truncated * 50_000
        + _int_or_zero(candidate.get("savedCandidateTradeCount")) * 10
        + _int_or_zero(candidate.get("savedRawTradeCount"))
    )


def _sort_key(candidate: Mapping[str, object]) -> tuple[int, int, int, int]:
    return (
        1 if candidate.get("savedLocalMeasurementSafe") else 0,
        _candidate_priority(candidate),
        _int_or_zero(candidate.get("savedCandidateWalletCount")),
        _int_or_zero(candidate.get("savedRawTradeCount")),
    )


def _why_selected(candidate: Mapping[str, object]) -> str:
    parts = []
    markets = _int_or_zero(candidate.get("savedAnalysisMarketCount"))
    raw_rows = _int_or_zero(candidate.get("savedRawTradeCount"))
    candidate_rows = _int_or_zero(candidate.get("savedCandidateTradeCount"))
    truncated = _int_or_zero(candidate.get("savedTruncatedMarketCount"))
    if markets:
        parts.append(f"{markets} saved analysis market(s)")
    if raw_rows:
        parts.append(f"{raw_rows:,} saved raw rows")
    if candidate_rows:
        parts.append(f"{candidate_rows:,} saved candidate rows")
    if truncated:
        parts.append(f"{truncated} saved truncation marker(s)")
    if not parts:
        parts.append("prior safe target with sparse saved evidence")
    return "; ".join(parts)


def _text(value: object) -> str:
    return str(value or "").strip()


def _int_or_zero(value: object) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _float_or_zero(value: object) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-inventory", default=str(DEFAULT_PREVIOUS_INVENTORY))
    parser.add_argument("--previous-resolution", default=str(DEFAULT_PREVIOUS_RESOLUTION))
    parser.add_argument("--previous-measurement", default=str(DEFAULT_PREVIOUS_MEASUREMENT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payload = build_expansion_candidates(
        previous_inventory=load_json_object(args.previous_inventory),
        previous_resolution=load_json_object(args.previous_resolution),
        previous_measurement=load_json_object(args.previous_measurement),
        max_candidates=args.max_candidates,
    )
    write_json(payload, args.output)
    if not args.quiet:
        print(json.dumps({"output": args.output, "candidateCount": payload["summary"]["candidateCount"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
