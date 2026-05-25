#!/usr/bin/env python3
"""Build a bounded local target inventory for Event Forensic measurement."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.event_forensic_bounded_performance_measurement import (
    DEFAULT_INVENTORY,
    MeasurementBounds,
    _load_inventory_rows,
)


REPORT_TYPE = "event_forensic_measurement_target_inventory"
SCHEMA_VERSION = "event_forensic_measurement_target_inventory_v1"
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_measurement_target_inventory_20260525.json")
DEFAULT_MAX_CANDIDATES = 8


def build_target_inventory(
    *,
    root: str | Path = ROOT,
    inventory_path: str | Path = DEFAULT_INVENTORY,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    bounds: MeasurementBounds = MeasurementBounds(),
) -> dict[str, object]:
    rows = _load_inventory_rows(root=root, inventory_path=inventory_path)
    candidates_by_event: dict[str, dict[str, object]] = {}
    skipped_reasons: Counter[str] = Counter()
    for row in rows:
        candidate = _candidate_from_row(row, bounds)
        event_slug = str(candidate.get("eventSlug") or "")
        if not event_slug:
            skipped_reasons["missing_event_slug"] += 1
            continue
        if candidate.get("analysisScope") != "whole_event":
            skipped_reasons["not_whole_event_scope"] += 1
            continue
        previous = candidates_by_event.get(event_slug)
        if previous is None or _candidate_priority(candidate) > _candidate_priority(previous):
            candidates_by_event[event_slug] = candidate

    candidates = sorted(candidates_by_event.values(), key=_candidate_priority, reverse=True)[:max_candidates]
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "bounds": bounds.to_dict(),
        "sourceInventoryPath": str(inventory_path),
        "maxCandidates": max_candidates,
        "summary": {
            "sourceRowsEvaluated": len(rows),
            "candidateCount": len(candidates),
            "likelyWithinBoundCount": sum(1 for item in candidates if item.get("likelyWithinLiveMarketBound")),
            "savedLocalSafeCount": sum(1 for item in candidates if item.get("savedLocalMeasurementSafe")),
            "skippedReasonCounts": dict(sorted(skipped_reasons.items())),
        },
        "candidates": candidates,
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _candidate_from_row(row: Mapping[str, object], bounds: MeasurementBounds) -> dict[str, object]:
    event_slug = _text(row.get("eventSlug"))
    saved_markets = _int_or_zero(row.get("analysisMarketCount"))
    saved_total_markets = _int_or_zero(row.get("totalEventMarketCount"))
    saved_raw_rows = _int_or_zero(row.get("rawTradeCount"))
    saved_candidate_rows = _int_or_zero(row.get("candidateTradeCount"))
    saved_candidate_wallets = _int_or_zero(row.get("candidateWalletCount"))
    saved_truncated = _int_or_zero(row.get("truncatedMarketCount"))
    saved_seconds = _float_or_zero(row.get("totalSeconds"))
    bound_reasons = _saved_bound_risk_reasons(
        saved_markets=saved_markets,
        saved_raw_rows=saved_raw_rows,
        saved_candidate_wallets=saved_candidate_wallets,
        bounds=bounds,
    )
    return {
        "eventSlug": event_slug,
        "eventTitle": _text(row.get("eventTitle")),
        "inputValue": f"https://polymarket.com/event/{event_slug}" if event_slug else "",
        "analysisScope": _text(row.get("analysisScope")),
        "selectedMarketSlug": _text(row.get("selectedMarketSlug")),
        "savedAnalysisMarketCount": saved_markets,
        "savedTotalEventMarketCount": saved_total_markets,
        "savedRawTradeCount": saved_raw_rows,
        "savedCandidateTradeCount": saved_candidate_rows,
        "savedCandidateWalletCount": saved_candidate_wallets,
        "savedWalletContextCount": _int_or_zero(row.get("walletContextCount")),
        "savedTruncatedMarketCount": saved_truncated,
        "savedTotalSeconds": saved_seconds,
        "savedDominantBottleneck": _text(row.get("dominantBottleneck")) or "unknown",
        "sourceReportPath": _text(row.get("path")),
        "likelyWithinLiveMarketBound": 0 < saved_markets <= bounds.max_markets,
        "savedLocalMeasurementSafe": not bound_reasons,
        "savedBoundRiskReasons": bound_reasons,
        "whyUseful": _why_useful(saved_markets, saved_raw_rows, saved_candidate_rows, saved_truncated, saved_seconds),
        "selectionSource": "local_performance_inventory",
    }


def _saved_bound_risk_reasons(
    *,
    saved_markets: int,
    saved_raw_rows: int,
    saved_candidate_wallets: int,
    bounds: MeasurementBounds,
) -> list[str]:
    reasons: list[str] = []
    if saved_markets <= 0:
        reasons.append("saved_market_count_missing")
    elif saved_markets > bounds.max_markets:
        reasons.append("saved_market_count_exceeds_bound")
    if saved_raw_rows > bounds.max_total_trade_rows:
        reasons.append("saved_raw_rows_exceed_bound")
    if saved_markets > 0 and saved_candidate_wallets > saved_markets * bounds.max_candidate_wallets_per_market:
        reasons.append("saved_candidate_wallets_exceed_per_market_bound")
    return reasons


def _why_useful(markets: int, raw_rows: int, candidate_rows: int, truncated: int, seconds: float) -> str:
    parts: list[str] = []
    if markets > 1:
        parts.append(f"{markets} saved whole-event markets")
    else:
        parts.append("single-market whole-event scope")
    if raw_rows:
        parts.append(f"{raw_rows:,} saved raw rows")
    if candidate_rows:
        parts.append(f"{candidate_rows:,} saved candidate rows")
    if truncated:
        parts.append(f"{truncated} saved truncated markets")
    if seconds:
        parts.append(f"{seconds:.2f}s saved runtime")
    return "; ".join(parts)


def _candidate_priority(candidate: Mapping[str, object]) -> tuple[int, int, float, int, int, int]:
    safe = 1 if candidate.get("savedLocalMeasurementSafe") else 0
    likely = 1 if candidate.get("likelyWithinLiveMarketBound") else 0
    return (
        safe,
        likely,
        float(candidate.get("savedTotalSeconds") or 0.0),
        _int_or_zero(candidate.get("savedTruncatedMarketCount")),
        _int_or_zero(candidate.get("savedCandidateWalletCount")),
        _int_or_zero(candidate.get("savedRawTradeCount")),
    )


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
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payload = build_target_inventory(
        root=Path(args.root),
        inventory_path=args.inventory,
        max_candidates=args.max_candidates,
    )
    write_json(payload, args.output)
    if not args.quiet:
        print(json.dumps({"output": args.output, "candidateCount": payload["summary"]["candidateCount"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
