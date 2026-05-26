#!/usr/bin/env python3
"""Bounded sidecar deeper trade collection for Event Forensic pagination.

Default mode is plan-only/offline. Live collection requires ``--run-live`` and
writes compact validation summaries only; it does not score candidates, mutate
saved reports, or change production pagination behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import AppConfig
from app.event_forensic import (
    EventForensicAnalyzer,
    _analysis_time_bounds,
    _dedupe_trades,
    _event_closed_for_report,
)
from app.models import Trade
from app.polymarket import MAX_TRADES_OFFSET, PolymarketClient
from app.storage import Storage
from tools.event_forensic_bounded_performance_measurement import runtime_env_status


REPORT_TYPE = "event_forensic_bounded_deeper_collection"
SCHEMA_VERSION = "event_forensic_bounded_deeper_collection_v1"
DEFAULT_SELECTION = Path("validation_outputs/event_forensic_subset_measurement_selection_20260525.json")
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_pagination_deeper_collection_20260526.json")


@dataclass(frozen=True, slots=True)
class PaginationCollectionBounds:
    max_events: int = 1
    max_markets: int = 6
    max_time_chunks_per_market: int = 2
    max_pages_per_slice: int = 31
    page_size: int = 100
    max_total_rows: int = 50_000
    max_wall_minutes: int = 30
    min_notional: Decimal = Decimal("250")

    @property
    def max_wall_seconds(self) -> int:
        return self.max_wall_minutes * 60

    @property
    def max_rows_per_slice(self) -> int:
        return min(self.max_pages_per_slice * self.page_size, MAX_TRADES_OFFSET + self.page_size)

    def to_dict(self) -> dict[str, object]:
        return {
            "maxEvents": self.max_events,
            "maxMarkets": self.max_markets,
            "maxTimeChunksPerMarket": self.max_time_chunks_per_market,
            "maxPagesPerSlice": self.max_pages_per_slice,
            "pageSize": self.page_size,
            "maxRowsPerSlice": self.max_rows_per_slice,
            "maxTotalRows": self.max_total_rows,
            "maxWallMinutes": self.max_wall_minutes,
            "maxWallSeconds": self.max_wall_seconds,
            "minNotional": str(self.min_notional),
        }


def build_collection_plan(
    *,
    selection: Mapping[str, object],
    bounds: PaginationCollectionBounds,
    env_status: Mapping[str, object] | None = None,
) -> dict[str, object]:
    selected_count = len(_selected_condition_ids(selection))
    violations = validate_bounds(selection, bounds)
    gate = "bounded_collection_plan_ready" if not violations else "bounded_collection_blocked"
    return {
        "reportType": f"{REPORT_TYPE}_plan",
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "productionPaginationChanged": False,
        "savedArtifactsMutated": False,
        "wholeEventCompletenessClaim": False,
        "eventSlug": str(selection.get("eventSlug") or ""),
        "selectedMarketCount": selected_count,
        "gateDecision": gate,
        "boundViolations": violations,
        "bounds": bounds.to_dict(),
        "envStatus": dict(env_status or {}),
        "collectionDesign": {
            "baselineWindow": "current_single_window_offset_pagination",
            "deeperWindow": "same selected markets split into bounded time chunks",
            "scoringReplay": False,
            "rankClaimsSupported": False,
            "candidateMetric": "candidate_floor_rows_not_full_scored_candidates",
            "outputPolicy": "compact_summary_only_no_raw_trade_dump",
        },
        "forbiddenActions": _forbidden_actions(),
    }


def validate_bounds(selection: Mapping[str, object], bounds: PaginationCollectionBounds) -> list[str]:
    violations: list[str] = []
    if bounds.max_events != 1:
        violations.append("max_events_must_be_1")
    if bounds.max_markets > 8:
        violations.append("max_markets_exceeds_campaign_bound")
    if bounds.max_time_chunks_per_market < 1 or bounds.max_time_chunks_per_market > 4:
        violations.append("max_time_chunks_per_market_outside_safe_range")
    if bounds.max_pages_per_slice < 1 or bounds.max_pages_per_slice * bounds.page_size > MAX_TRADES_OFFSET + bounds.page_size:
        violations.append("max_pages_per_slice_exceeds_public_offset_cap")
    if bounds.max_total_rows > 50_000:
        violations.append("max_total_rows_exceeds_campaign_bound")
    if bounds.max_wall_minutes > 30:
        violations.append("max_wall_time_exceeds_campaign_bound")
    selected_count = len(_selected_condition_ids(selection))
    if selected_count <= 0:
        violations.append("missing_selected_condition_ids")
    if selected_count > bounds.max_markets:
        violations.append("selected_market_count_exceeds_bound")
    if bool(selection.get("wholeEventCompletenessClaim")):
        violations.append("whole_event_completeness_claim_not_allowed")
    return violations


def run_live_deeper_collection(
    *,
    selection: Mapping[str, object],
    bounds: PaginationCollectionBounds,
    output_dir: Path,
) -> dict[str, object]:
    started = time.monotonic()
    env_status = runtime_env_status(root=ROOT)
    violations = validate_bounds(selection, bounds)
    if violations:
        return _blocked_summary(selection, bounds, env_status, "bounded_collection_blocked", violations, output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    isolated = output_dir / "isolated_app_data"
    config = AppConfig(
        data_dir=isolated,
        db_path=isolated / "event_forensic_pagination_deeper_collection.sqlite3",
        reports_dir=output_dir / "reports",
        outputs_dir=output_dir / "event_forensic_outputs",
        default_lookback="event",
        max_trade_pages=bounds.max_pages_per_slice,
        trade_page_size=bounds.page_size,
    )
    config.ensure_dirs()
    storage = Storage(config.db_path)
    storage.init()
    client = PolymarketClient()
    analyzer = EventForensicAnalyzer(client, storage, config)
    input_value = str(selection.get("inputValue") or f"https://polymarket.com/event/{selection.get('eventSlug', '')}")
    resolved = analyzer.resolve_input(input_value)
    live_market_count = len(resolved.markets)
    selected_conditions = _match_selected_conditions(selection, resolved.markets)
    if not selected_conditions:
        return _blocked_summary(
            selection,
            bounds,
            env_status,
            "bounded_collection_blocked",
            ["selected_conditions_not_found_in_live_event"],
            output_dir,
        )
    if len(selected_conditions) > bounds.max_markets:
        return _blocked_summary(
            selection,
            bounds,
            env_status,
            "bounded_collection_blocked",
            ["live_selected_market_count_exceeds_bound"],
            output_dir,
        )
    resolved.markets = {condition_id: resolved.markets[condition_id] for condition_id in selected_conditions}
    resolved.market_payloads = {
        condition_id: resolved.market_payloads[condition_id]
        for condition_id in selected_conditions
        if condition_id in resolved.market_payloads
    }
    if isinstance(resolved.event_payload, dict):
        filtered_payload = dict(resolved.event_payload)
        filtered_payload["markets"] = [
            resolved.market_payloads[condition_id]
            for condition_id in selected_conditions
            if condition_id in resolved.market_payloads
        ]
        resolved.event_payload = filtered_payload

    start_ts, end_ts = _collection_time_bounds(resolved)
    market_rows: list[dict[str, object]] = []
    baseline_all: list[Trade] = []
    deeper_all: list[Trade] = []
    bounds_hit = False
    stop_reason = ""

    for condition_id in selected_conditions:
        if _elapsed(started) > bounds.max_wall_seconds:
            bounds_hit = True
            stop_reason = "max_wall_time_elapsed"
            break
        market = resolved.markets[condition_id]
        baseline = _collect_window(
            client,
            condition_id=condition_id,
            start_ts=start_ts,
            end_ts=end_ts,
            min_notional=bounds.min_notional,
            bounds=bounds,
        )
        deeper_trades: list[Trade] = []
        chunk_rows: list[dict[str, object]] = []
        for chunk_start, chunk_end in _time_chunks(start_ts, end_ts, bounds.max_time_chunks_per_market):
            if _elapsed(started) > bounds.max_wall_seconds:
                bounds_hit = True
                stop_reason = "max_wall_time_elapsed"
                break
            chunk = _collect_window(
                client,
                condition_id=condition_id,
                start_ts=chunk_start,
                end_ts=chunk_end,
                min_notional=bounds.min_notional,
                bounds=bounds,
            )
            deeper_trades.extend(chunk["trades"])
            chunk_rows.append({key: value for key, value in chunk.items() if key != "trades"})
            if len(_dedupe_trades([*deeper_all, *deeper_trades])) > bounds.max_total_rows:
                bounds_hit = True
                stop_reason = "max_total_rows_elapsed"
                break
        deeper = _dedupe_trades(deeper_trades)
        baseline_trades = baseline["trades"]
        baseline_keys = _trade_keys(baseline_trades)
        deeper_keys = _trade_keys(deeper)
        added = [trade for trade in deeper if _trade_key(trade) not in baseline_keys]
        removed_count = len([key for key in baseline_keys if key not in deeper_keys])
        baseline_all.extend(baseline_trades)
        deeper_all.extend(deeper)
        market_rows.append(
            {
                "conditionId": condition_id,
                "marketSlug": market.slug,
                "marketTitle": market.question,
                "baselineRows": len(baseline_trades),
                "deeperRows": len(deeper),
                "addedRows": len(added),
                "baselineOnlyRows": removed_count,
                "baselineCandidateFloorRows": _candidate_floor_count(baseline_trades, bounds.min_notional),
                "deeperCandidateFloorRows": _candidate_floor_count(deeper, bounds.min_notional),
                "addedCandidateFloorRows": _candidate_floor_count(added, bounds.min_notional),
                "baselineTruncated": bool(baseline["truncated"]),
                "deeperStillTruncated": any(bool(row.get("truncated")) for row in chunk_rows),
                "chunkCount": len(chunk_rows),
                "chunkRows": chunk_rows,
                "topAddedRows": _top_added_rows(added, limit=10),
            }
        )
        if bounds_hit:
            break

    baseline_all = _dedupe_trades(baseline_all)
    deeper_all = _dedupe_trades(deeper_all)
    baseline_candidate = _candidate_floor_count(baseline_all, bounds.min_notional)
    deeper_candidate = _candidate_floor_count(deeper_all, bounds.min_notional)
    raw_delta = len(deeper_all) - len(baseline_all)
    candidate_delta = deeper_candidate - baseline_candidate
    gate = "bounded_collection_complete"
    if bounds_hit:
        gate = "bounded_collection_blocked"
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "outputDir": str(output_dir),
        "sidecarOnly": True,
        "networkUsed": True,
        "runtimeBehaviorChanged": False,
        "productionPaginationChanged": False,
        "savedArtifactsMutated": False,
        "storageScope": "validation_output_dir_only",
        "privateKeyUsed": False,
        "clobAuthUsed": False,
        "ordersPlaced": False,
        "wholeEventCompletenessClaim": False,
        "scoringReplay": False,
        "rankClaimsSupported": False,
        "envStatus": env_status,
        "bounds": bounds.to_dict(),
        "summary": {
            "gateDecision": gate,
            "eventSlug": resolved.event_slug,
            "liveResolvedMarketCount": live_market_count,
            "selectedMarketCount": len(selected_conditions),
            "baselineRows": len(baseline_all),
            "deeperRows": len(deeper_all),
            "rawRowsDelta": raw_delta,
            "baselineCandidateFloorRows": baseline_candidate,
            "deeperCandidateFloorRows": deeper_candidate,
            "candidateFloorRowsDelta": candidate_delta,
            "baselineWalletCount": len({trade.wallet for trade in baseline_all if trade.wallet}),
            "deeperWalletCount": len({trade.wallet for trade in deeper_all if trade.wallet}),
            "baselineTruncatedMarkets": sum(1 for row in market_rows if row.get("baselineTruncated")),
            "deeperStillTruncatedMarkets": sum(1 for row in market_rows if row.get("deeperStillTruncated")),
            "boundsHit": bounds_hit,
            "stopReason": stop_reason,
            "wallClockSeconds": round(_elapsed(started), 3),
        },
        "selectedConditionIds": selected_conditions,
        "marketRows": market_rows,
        "claimsNotSupported": [
            "whole_event_completeness",
            "scored_candidate_admission_delta",
            "rank_or_review_bucket_delta",
            "production_pagination_migration_ready",
        ],
        "forbiddenActionsPreserved": _forbidden_actions(),
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _collect_window(
    client: PolymarketClient,
    *,
    condition_id: str,
    start_ts: int,
    end_ts: int,
    min_notional: Decimal,
    bounds: PaginationCollectionBounds,
) -> dict[str, object]:
    unfiltered = client.fetch_trades_in_range(
        start_ts=start_ts,
        end_ts=end_ts,
        max_pages=bounds.max_pages_per_slice,
        page_size=bounds.page_size,
        condition_ids=[condition_id],
    )
    filtered = client.fetch_trades_in_range(
        start_ts=start_ts,
        end_ts=end_ts,
        max_pages=bounds.max_pages_per_slice,
        page_size=bounds.page_size,
        condition_ids=[condition_id],
        filter_cash_amount=min_notional,
    )
    combined = _dedupe_trades([*unfiltered, *filtered])
    truncated = len(unfiltered) >= bounds.max_rows_per_slice or len(filtered) >= bounds.max_rows_per_slice
    return {
        "startTs": start_ts,
        "endTs": end_ts,
        "unfilteredRows": len(unfiltered),
        "filteredRows": len(filtered),
        "rows": len(combined),
        "candidateFloorRows": _candidate_floor_count(combined, min_notional),
        "truncated": truncated,
        "trades": combined,
    }


def _collection_time_bounds(resolved: object) -> tuple[int, int]:
    event_start, event_end = _analysis_time_bounds(resolved)  # type: ignore[arg-type]
    now = datetime.now(UTC)
    event_closed = _event_closed_for_report(resolved)  # type: ignore[arg-type]
    if not event_closed:
        event_end = now
    if not event_closed and event_start is not None and event_end is not None and event_start >= event_end:
        event_start = None
    if event_start is None and event_end is not None and event_closed:
        event_start = event_end - timedelta(days=14)
    if event_start is None:
        event_start = now - timedelta(days=365)
    if event_end is None:
        event_end = now
    end_padding = timedelta(days=7) if event_closed else timedelta()
    return max(0, int((event_start - timedelta(days=1)).timestamp())), int((event_end + end_padding).timestamp())


def _time_chunks(start_ts: int, end_ts: int, count: int) -> list[tuple[int, int]]:
    if count <= 1 or end_ts <= start_ts:
        return [(start_ts, end_ts)]
    span = end_ts - start_ts + 1
    chunk = max(1, span // count)
    chunks: list[tuple[int, int]] = []
    cursor = start_ts
    for index in range(count):
        chunk_end = end_ts if index == count - 1 else min(end_ts, cursor + chunk - 1)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + 1
        if cursor > end_ts:
            break
    return chunks


def _match_selected_conditions(selection: Mapping[str, object], markets: Mapping[str, object]) -> list[str]:
    requested_ids = _selected_condition_ids(selection)
    slug_to_condition = {
        str(getattr(market, "slug", "") or ""): condition_id
        for condition_id, market in markets.items()
    }
    result: list[str] = []
    for index, slug in enumerate(_selected_slugs(selection)):
        condition_id = requested_ids[index] if index < len(requested_ids) else ""
        if condition_id and condition_id in markets:
            result.append(condition_id)
        elif slug in slug_to_condition:
            result.append(slug_to_condition[slug])
    return result


def _selected_condition_ids(selection: Mapping[str, object]) -> list[str]:
    rows = selection.get("selectedMarkets")
    if isinstance(rows, list):
        return [
            str(row.get("conditionId") or "").strip()
            for row in rows
            if isinstance(row, Mapping) and str(row.get("conditionId") or "").strip()
        ]
    return []


def _selected_slugs(selection: Mapping[str, object]) -> list[str]:
    slugs = selection.get("selectedMarketSlugs")
    if isinstance(slugs, list):
        return [str(slug).strip() for slug in slugs if str(slug).strip()]
    rows = selection.get("selectedMarkets")
    if isinstance(rows, list):
        return [
            str(row.get("marketSlug") or "").strip()
            for row in rows
            if isinstance(row, Mapping) and str(row.get("marketSlug") or "").strip()
        ]
    return []


def _candidate_floor_count(trades: Sequence[Trade], minimum: Decimal) -> int:
    return sum(1 for trade in trades if trade.notional >= minimum)


def _trade_keys(trades: Sequence[Trade]) -> set[tuple[str, str, str]]:
    return {_trade_key(trade) for trade in trades}


def _trade_key(trade: Trade) -> tuple[str, str, str]:
    return (trade.trade_id, trade.wallet, trade.condition_id)


def _top_added_rows(trades: Sequence[Trade], *, limit: int) -> list[dict[str, object]]:
    ordered = sorted(trades, key=lambda trade: trade.notional, reverse=True)
    return [
        {
            "tradeId": trade.trade_id,
            "conditionId": trade.condition_id,
            "wallet": trade.wallet,
            "side": trade.side,
            "outcome": trade.outcome,
            "price": str(trade.price),
            "size": str(trade.size),
            "notional": str(trade.notional),
            "timestamp": trade.timestamp.isoformat(),
            "marketSlug": trade.slug,
        }
        for trade in ordered[:limit]
    ]


def _blocked_summary(
    selection: Mapping[str, object],
    bounds: PaginationCollectionBounds,
    env_status: Mapping[str, object],
    gate: str,
    violations: Sequence[str],
    output_dir: Path,
) -> dict[str, object]:
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "outputDir": str(output_dir),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "productionPaginationChanged": False,
        "savedArtifactsMutated": False,
        "wholeEventCompletenessClaim": False,
        "envStatus": dict(env_status),
        "bounds": bounds.to_dict(),
        "summary": {
            "gateDecision": gate,
            "eventSlug": str(selection.get("eventSlug") or ""),
            "boundViolations": list(violations),
            "boundsHit": True,
            "rawRowsDelta": 0,
            "candidateFloorRowsDelta": 0,
        },
        "forbiddenActionsPreserved": _forbidden_actions(),
    }


def _forbidden_actions() -> list[str]:
    return [
        "No production pagination expansion.",
        "No scoring, threshold, gate, Phase 3, storage schema, or UI sorting changes.",
        "No saved artifact mutation.",
        "No private keys, CLOB auth, trading credentials, or order placement.",
        "No whole-event completeness claim from subset-only collection.",
    ]


def _load_json_object(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _decimal(value: object, default: Decimal) -> Decimal:
    try:
        text = str(value or "").strip()
        return Decimal(text) if text else default
    except (InvalidOperation, ValueError):
        return default


def _elapsed(started: float) -> float:
    return time.monotonic() - started


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", default=str(DEFAULT_SELECTION))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--max-markets", type=int, default=6)
    parser.add_argument("--max-time-chunks-per-market", type=int, default=2)
    parser.add_argument("--max-pages-per-slice", type=int, default=31)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-total-rows", type=int, default=50_000)
    parser.add_argument("--max-wall-minutes", type=int, default=30)
    parser.add_argument("--min-notional", default="250")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    selection = _load_json_object(args.selection)
    bounds = PaginationCollectionBounds(
        max_markets=args.max_markets,
        max_time_chunks_per_market=args.max_time_chunks_per_market,
        max_pages_per_slice=args.max_pages_per_slice,
        page_size=args.page_size,
        max_total_rows=args.max_total_rows,
        max_wall_minutes=args.max_wall_minutes,
        min_notional=_decimal(args.min_notional, Decimal("250")),
    )
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else ROOT / "validation_outputs" / f"event_forensic_pagination_deeper_collection_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    if args.run_live:
        payload = run_live_deeper_collection(selection=selection, bounds=bounds, output_dir=output_dir)
    else:
        payload = build_collection_plan(selection=selection, bounds=bounds, env_status=runtime_env_status(root=ROOT))
    write_json(payload, args.output)
    if args.run_live:
        write_json(payload, output_dir / "summary.json")
    if not args.quiet:
        summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
        print(f"gate: {summary.get('gateDecision') or payload.get('gateDecision')}")
        print(f"output: {args.output}")
    return 0 if (payload.get("summary") or payload).get("gateDecision") not in {"bounded_collection_blocked"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
