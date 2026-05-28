#!/usr/bin/env python3
"""One-market granular Event Forensic pagination probe.

Default mode is offline plan-only. Live probing requires ``--run-live`` and
collects compact sidecar evidence for one selected market. It does not score
candidates, mutate saved reports, or change production pagination behavior.
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
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import AppConfig
from app.event_forensic import EventForensicAnalyzer, _analysis_time_bounds, _event_closed_for_report
from app.models import Trade
from app.polymarket import DATA_BASE, MAX_TRADES_OFFSET, PolymarketClient, _get_json
from app.storage import Storage
from tools.event_forensic_bounded_deeper_collection import _selected_condition_ids, _selected_slugs
from tools.event_forensic_bounded_performance_measurement import runtime_env_status


REPORT_TYPE = "event_forensic_granular_pagination_probe"
SCHEMA_VERSION = "event_forensic_granular_pagination_probe_v1"
DEFAULT_SELECTION = Path("validation_outputs/event_forensic_subset_measurement_selection_20260525.json")
DEFAULT_PREVIOUS_COLLECTION = Path("validation_outputs/event_forensic_pagination_deeper_collection_20260526.json")
DEFAULT_REFERENCE_REPORT = Path(
    "validation_outputs/event_forensic_wallet_api_boundary_trace_live_20260526_122643/"
    "live_run/event_forensic_outputs/event_forensic_20260526_092643/event_analysis.json"
)
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_granular_pagination_probe_20260526.json")


JsonFetcher = Callable[[str, dict[str, object]], object]


@dataclass(frozen=True, slots=True)
class GranularProbeBounds:
    max_events: int = 1
    max_markets: int = 1
    max_time_chunks: int = 8
    max_pages_per_window: int = 31
    page_size: int = 100
    max_total_unique_rows: int = 50_000
    max_wall_minutes: int = 30
    max_no_new_pages: int = 2
    min_notional: Decimal = Decimal("250")

    @property
    def max_wall_seconds(self) -> int:
        return self.max_wall_minutes * 60

    @property
    def max_rows_per_window(self) -> int:
        return min(self.max_pages_per_window * self.page_size, MAX_TRADES_OFFSET + self.page_size)

    def to_dict(self) -> dict[str, object]:
        return {
            "maxEvents": self.max_events,
            "maxMarkets": self.max_markets,
            "maxTimeChunks": self.max_time_chunks,
            "maxPagesPerWindow": self.max_pages_per_window,
            "pageSize": self.page_size,
            "maxRowsPerWindow": self.max_rows_per_window,
            "maxTotalUniqueRows": self.max_total_unique_rows,
            "maxWallMinutes": self.max_wall_minutes,
            "maxWallSeconds": self.max_wall_seconds,
            "maxNoNewPages": self.max_no_new_pages,
            "minNotional": str(self.min_notional),
        }


def build_probe_plan(
    *,
    selection: Mapping[str, object],
    previous_collection: Mapping[str, object] | None = None,
    reference_report: Mapping[str, object] | None = None,
    explicit_market_slug: str = "",
    bounds: GranularProbeBounds = GranularProbeBounds(),
    env_status: Mapping[str, object] | None = None,
) -> dict[str, object]:
    selected_market = select_probe_market(
        selection=selection,
        previous_collection=previous_collection or {},
        reference_report=reference_report or {},
        explicit_market_slug=explicit_market_slug,
    )
    violations = validate_probe_plan(selection=selection, selected_market=selected_market, bounds=bounds)
    gate = "granular_probe_plan_ready" if not violations else "granular_probe_blocked_by_bounds"
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
        "gateDecision": gate,
        "boundViolations": violations,
        "eventSlug": str(selection.get("eventSlug") or ""),
        "selectedMarket": selected_market,
        "bounds": bounds.to_dict(),
        "envStatus": dict(env_status or {}),
        "truncationInterpretations": _truncation_interpretations(),
        "probeDesign": {
            "baseline": "single full analysis window with current offset pagination",
            "granular": "one market split into bounded non-overlapping time chunks",
            "pageMetrics": [
                "pages attempted",
                "rows returned",
                "accepted rows",
                "new unique rows",
                "duplicate page signatures",
                "cursor stall signatures",
                "provider hard-cap markers",
                "no-new-row plateau",
            ],
            "scoringReplay": False,
            "candidateMetric": "candidate_floor_rows_only_not_full_scored_candidates",
        },
        "forbiddenActions": _forbidden_actions(),
    }


def validate_probe_plan(
    *,
    selection: Mapping[str, object],
    selected_market: Mapping[str, object] | None,
    bounds: GranularProbeBounds,
) -> list[str]:
    violations: list[str] = []
    if bounds.max_events != 1:
        violations.append("max_events_must_be_1")
    if bounds.max_markets != 1:
        violations.append("max_markets_must_be_1")
    if bounds.max_time_chunks < 1 or bounds.max_time_chunks > 12:
        violations.append("max_time_chunks_outside_safe_range")
    if bounds.max_pages_per_window < 1 or bounds.max_pages_per_window * bounds.page_size > MAX_TRADES_OFFSET + bounds.page_size:
        violations.append("max_pages_per_window_exceeds_public_offset_cap")
    if bounds.max_total_unique_rows > 50_000:
        violations.append("max_total_unique_rows_exceeds_campaign_bound")
    if bounds.max_wall_minutes > 30:
        violations.append("max_wall_time_exceeds_campaign_bound")
    if bounds.max_no_new_pages < 1:
        violations.append("max_no_new_pages_must_be_positive")
    if bool(selection.get("wholeEventCompletenessClaim")):
        violations.append("whole_event_completeness_claim_not_allowed")
    if not selected_market:
        violations.append("missing_selected_market")
    elif not str(selected_market.get("conditionId") or "").strip():
        violations.append("selected_market_missing_condition_id")
    return violations


def select_probe_market(
    *,
    selection: Mapping[str, object],
    previous_collection: Mapping[str, object],
    reference_report: Mapping[str, object],
    explicit_market_slug: str = "",
) -> dict[str, object] | None:
    rows = _selection_market_rows(selection)
    previous = {
        str(row.get("conditionId") or row.get("marketSlug") or ""): row
        for row in previous_collection.get("marketRows", [])
        if isinstance(row, Mapping)
    }
    reference_counts = _reference_market_counts(reference_report)
    candidates: list[dict[str, object]] = []
    for row in rows:
        slug = str(row.get("marketSlug") or "")
        condition_id = str(row.get("conditionId") or "")
        if explicit_market_slug and explicit_market_slug not in {slug, condition_id}:
            continue
        prev = previous.get(condition_id) or previous.get(slug) or {}
        ref = reference_counts.get(condition_id) or reference_counts.get(slug) or {}
        candidates.append(
            {
                **row,
                "baselineRows": _int(prev.get("baselineRows")),
                "baselineCandidateFloorRows": _int(prev.get("baselineCandidateFloorRows")),
                "baselineTruncated": bool(prev.get("baselineTruncated")),
                "deeperStillTruncated": bool(prev.get("deeperStillTruncated")),
                "referenceHighReviewRows": _int(ref.get("highReviewRows")),
                "referenceWeakHistoryRows": _int(ref.get("weakHistoryRows")),
                "referenceSensitiveRows": _int(ref.get("sensitiveRows")),
                "selectionReason": "",
            }
        )
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            _int(item.get("referenceHighReviewRows")),
            _int(item.get("referenceWeakHistoryRows")),
            _int(item.get("referenceSensitiveRows")),
            _int(item.get("baselineCandidateFloorRows")),
            _int(item.get("baselineRows")),
        ),
        reverse=True,
    )
    selected = dict(candidates[0])
    selected["selectionReason"] = (
        "highest reference high-review overlap among the approved selected markets, "
        "with truncation and high candidate-floor volume in the prior bounded collection"
    )
    return selected


def run_live_probe(
    *,
    selection: Mapping[str, object],
    selected_market: Mapping[str, object],
    bounds: GranularProbeBounds,
    output_dir: Path,
    fetch_json: JsonFetcher = _get_json,
) -> dict[str, object]:
    started = time.monotonic()
    env_status = runtime_env_status(root=ROOT)
    violations = validate_probe_plan(selection=selection, selected_market=selected_market, bounds=bounds)
    if violations:
        return _blocked_payload(selected_market, bounds, env_status, output_dir, violations)

    output_dir.mkdir(parents=True, exist_ok=True)
    isolated = output_dir / "isolated_app_data"
    config = AppConfig(
        data_dir=isolated,
        db_path=isolated / "event_forensic_granular_pagination_probe.sqlite3",
        reports_dir=output_dir / "reports",
        outputs_dir=output_dir / "event_forensic_outputs",
        default_lookback="event",
        max_trade_pages=bounds.max_pages_per_window,
        trade_page_size=bounds.page_size,
    )
    config.ensure_dirs()
    storage = Storage(config.db_path)
    storage.init()
    analyzer = EventForensicAnalyzer(PolymarketClient(), storage, config)
    input_value = str(selection.get("inputValue") or f"https://polymarket.com/event/{selection.get('eventSlug', '')}")
    resolved = analyzer.resolve_input(input_value)
    live_market_count = len(resolved.markets)
    condition_id = _match_market_condition(selected_market, resolved.markets)
    if not condition_id:
        return _blocked_payload(
            selected_market,
            bounds,
            env_status,
            output_dir,
            ["selected_market_not_found_in_live_event"],
        )
    start_ts, end_ts = _collection_time_bounds(resolved)
    baseline_unfiltered = collect_trade_window_pages(
        fetch_json=fetch_json,
        condition_id=condition_id,
        start_ts=start_ts,
        end_ts=end_ts,
        filter_cash_amount=None,
        bounds=bounds,
    )
    baseline_filtered = collect_trade_window_pages(
        fetch_json=fetch_json,
        condition_id=condition_id,
        start_ts=start_ts,
        end_ts=end_ts,
        filter_cash_amount=bounds.min_notional,
        bounds=bounds,
    )
    baseline = _combine_window_results([baseline_unfiltered, baseline_filtered], bounds=bounds)

    granular_windows: list[dict[str, object]] = []
    granular_results: list[dict[str, object]] = []
    bounds_hit = False
    stop_reason = ""
    for index, (chunk_start, chunk_end) in enumerate(_time_chunks(start_ts, end_ts, bounds.max_time_chunks), start=1):
        if time.monotonic() - started > bounds.max_wall_seconds:
            bounds_hit = True
            stop_reason = "max_wall_time_elapsed"
            break
        unfiltered = collect_trade_window_pages(
            fetch_json=fetch_json,
            condition_id=condition_id,
            start_ts=chunk_start,
            end_ts=chunk_end,
            filter_cash_amount=None,
            bounds=bounds,
        )
        filtered = collect_trade_window_pages(
            fetch_json=fetch_json,
            condition_id=condition_id,
            start_ts=chunk_start,
            end_ts=chunk_end,
            filter_cash_amount=bounds.min_notional,
            bounds=bounds,
        )
        combined = _combine_window_results([unfiltered, filtered], bounds=bounds)
        granular_results.append(combined)
        granular_windows.append(
            {
                "chunkIndex": index,
                "startTs": chunk_start,
                "endTs": chunk_end,
                **_summary_without_trades(combined),
            }
        )
        if _unique_trade_count_from_results(granular_results) > bounds.max_total_unique_rows:
            bounds_hit = True
            stop_reason = "max_total_unique_rows_elapsed"
            break
    granular = _combine_window_results(granular_results, bounds=bounds)
    baseline_keys = _trade_keys(baseline["trades"])
    granular_keys = _trade_keys(granular["trades"])
    added = [trade for trade in granular["trades"] if _trade_key(trade) not in baseline_keys]
    baseline_only = [key for key in baseline_keys if key not in granular_keys]
    gate = _gate(
        bounds_hit=bounds_hit,
        added_rows=len(added),
        candidate_delta=_candidate_floor_count(added, bounds.min_notional),
        provider_or_query_bound=bool(granular["providerHardCapDetected"] or granular["cursorStallDetected"] or granular["noNewRowPlateauDetected"]),
        baseline_truncated=bool(baseline["truncated"]),
    )
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
        "wholeEventCompletenessClaim": False,
        "scoringReplay": False,
        "rankClaimsSupported": False,
        "privateKeyUsed": False,
        "clobAuthUsed": False,
        "ordersPlaced": False,
        "envStatus": env_status,
        "bounds": bounds.to_dict(),
        "selectedMarket": {
            **dict(selected_market),
            "liveConditionId": condition_id,
            "liveMarketSlug": getattr(resolved.markets[condition_id], "slug", ""),
        },
        "summary": {
            "gateDecision": gate,
            "eventSlug": resolved.event_slug,
            "liveResolvedMarketCount": live_market_count,
            "baselineRows": len(baseline["trades"]),
            "granularRows": len(granular["trades"]),
            "rawRowsDelta": len(granular["trades"]) - len(baseline["trades"]),
            "addedRows": len(added),
            "baselineOnlyRows": len(baseline_only),
            "baselineCandidateFloorRows": _candidate_floor_count(baseline["trades"], bounds.min_notional),
            "granularCandidateFloorRows": _candidate_floor_count(granular["trades"], bounds.min_notional),
            "addedCandidateFloorRows": _candidate_floor_count(added, bounds.min_notional),
            "baselineTruncated": bool(baseline["truncated"]),
            "granularStillTruncated": bool(granular["truncated"]),
            "providerHardCapDetected": bool(granular["providerHardCapDetected"]),
            "duplicatePageCount": _int(granular["duplicatePageCount"]),
            "cursorStallCount": _int(granular["cursorStallCount"]),
            "noNewRowPlateauCount": _int(granular["noNewRowPlateauCount"]),
            "noNewRowPlateauDetected": bool(granular["noNewRowPlateauDetected"]),
            "boundsHit": bounds_hit,
            "stopReason": stop_reason,
            "wallClockSeconds": round(time.monotonic() - started, 3),
        },
        "baseline": _summary_without_trades(baseline),
        "granular": _summary_without_trades(granular),
        "granularWindows": granular_windows,
        "topAddedRows": _top_added_rows(added, limit=25),
        "claimsNotSupported": [
            "whole_event_completeness",
            "full_scored_candidate_delta",
            "rank_or_review_bucket_delta",
            "production_pagination_migration_ready",
        ],
        "forbiddenActionsPreserved": _forbidden_actions(),
    }


def collect_trade_window_pages(
    *,
    fetch_json: JsonFetcher,
    condition_id: str,
    start_ts: int,
    end_ts: int,
    filter_cash_amount: Decimal | None,
    bounds: GranularProbeBounds,
) -> dict[str, object]:
    rows: list[Trade] = []
    pages: list[dict[str, object]] = []
    seen_trade_keys: set[tuple[str, str, str]] = set()
    seen_page_signatures: set[tuple[tuple[str, str, str], ...]] = set()
    previous_signature: tuple[tuple[str, str, str], ...] | None = None
    duplicate_pages = 0
    cursor_stalls = 0
    no_new_plateau_count = 0
    max_no_new_streak = 0
    provider_hard_cap = False
    stop_reason = ""
    for page in range(bounds.max_pages_per_window):
        offset = page * bounds.page_size
        if offset > MAX_TRADES_OFFSET:
            provider_hard_cap = True
            stop_reason = "max_trades_offset_exceeded"
            break
        params: dict[str, object] = {"limit": bounds.page_size, "offset": offset}
        params["market"] = condition_id
        if filter_cash_amount is not None and filter_cash_amount > 0:
            params["filterType"] = "CASH"
            params["filterAmount"] = str(filter_cash_amount)
        try:
            batch = fetch_json(f"{DATA_BASE}/trades", params)
        except HTTPError as exc:
            if exc.code == 400 and offset >= MAX_TRADES_OFFSET:
                provider_hard_cap = True
                stop_reason = "provider_offset_400"
                break
            raise
        if not isinstance(batch, list) or not batch:
            stop_reason = "empty_page"
            break
        page_trades: list[Trade] = []
        older_stop = False
        too_new_rows = 0
        for item in batch:
            if not isinstance(item, Mapping):
                continue
            trade = Trade.from_api(dict(item))
            trade_ts = int(trade.timestamp.timestamp())
            if trade_ts > end_ts:
                too_new_rows += 1
                continue
            if trade_ts < start_ts:
                older_stop = True
                break
            page_trades.append(trade)
        signature = tuple(_trade_key(trade) for trade in page_trades)
        duplicate_page = bool(signature and signature in seen_page_signatures)
        cursor_stall = bool(signature and previous_signature == signature)
        if duplicate_page:
            duplicate_pages += 1
        if cursor_stall:
            cursor_stalls += 1
        seen_page_signatures.add(signature)
        previous_signature = signature
        new_unique = 0
        duplicate_rows = 0
        for trade in page_trades:
            key = _trade_key(trade)
            if key in seen_trade_keys:
                duplicate_rows += 1
                continue
            seen_trade_keys.add(key)
            rows.append(trade)
            new_unique += 1
        if new_unique == 0:
            no_new_plateau_count += 1
            max_no_new_streak = max(max_no_new_streak, no_new_plateau_count)
        else:
            no_new_plateau_count = 0
        pages.append(
            {
                "pageIndex": page,
                "offset": offset,
                "rowsReturned": len(batch),
                "acceptedRows": len(page_trades),
                "tooNewRows": too_new_rows,
                "newUniqueRows": new_unique,
                "duplicateRows": duplicate_rows,
                "duplicatePage": duplicate_page,
                "cursorStall": cursor_stall,
                "olderThanWindowStop": older_stop,
            }
        )
        if len(batch) >= bounds.page_size and offset >= MAX_TRADES_OFFSET:
            provider_hard_cap = True
            stop_reason = "provider_hard_cap_full_last_page"
            break
        if older_stop:
            stop_reason = "older_than_window"
            break
        if len(batch) < bounds.page_size:
            stop_reason = "short_page"
            break
        if max_no_new_streak >= bounds.max_no_new_pages:
            stop_reason = "no_new_row_plateau"
            break
    return {
        "filterCashAmount": str(filter_cash_amount) if filter_cash_amount is not None else "",
        "pagesAttempted": len(pages),
        "rows": rows,
        "uniqueRows": len(rows),
        "candidateFloorRows": _candidate_floor_count(rows, bounds.min_notional),
        "duplicatePageCount": duplicate_pages,
        "cursorStallCount": cursor_stalls,
        "noNewRowPlateauCount": max_no_new_streak,
        "noNewRowPlateauDetected": max_no_new_streak >= bounds.max_no_new_pages,
        "providerHardCapDetected": provider_hard_cap,
        "truncated": provider_hard_cap or (len(pages) >= bounds.max_pages_per_window and not stop_reason),
        "stopReason": stop_reason or "page_limit_reached",
        "pages": pages,
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _combine_window_results(results: Sequence[Mapping[str, object]], *, bounds: GranularProbeBounds) -> dict[str, object]:
    trades: list[Trade] = []
    seen: set[tuple[str, str, str]] = set()
    pages: list[dict[str, object]] = []
    duplicate_page_count = 0
    cursor_stall_count = 0
    no_new_row_plateau_count = 0
    provider_hard_cap = False
    truncated = False
    stop_reasons: list[str] = []
    for result in results:
        raw_trades = result.get("rows")
        if not isinstance(raw_trades, list):
            raw_trades = result.get("trades")
        for trade in raw_trades if isinstance(raw_trades, list) else []:
            if not isinstance(trade, Trade):
                continue
            key = _trade_key(trade)
            if key not in seen:
                seen.add(key)
                trades.append(trade)
        pages.extend(page for page in result.get("pages", []) if isinstance(page, Mapping))
        duplicate_page_count += _int(result.get("duplicatePageCount"))
        cursor_stall_count += _int(result.get("cursorStallCount"))
        no_new_row_plateau_count = max(no_new_row_plateau_count, _int(result.get("noNewRowPlateauCount")))
        provider_hard_cap = provider_hard_cap or bool(result.get("providerHardCapDetected"))
        truncated = truncated or bool(result.get("truncated"))
        reason = str(result.get("stopReason") or "")
        if reason:
            stop_reasons.append(reason)
    return {
        "trades": trades,
        "uniqueRows": len(trades),
        "candidateFloorRows": _candidate_floor_count(trades, bounds.min_notional),
        "pageRequests": len(pages),
        "duplicatePageCount": duplicate_page_count,
        "cursorStallCount": cursor_stall_count,
        "cursorStallDetected": cursor_stall_count > 0,
        "noNewRowPlateauCount": no_new_row_plateau_count,
        "noNewRowPlateauDetected": no_new_row_plateau_count >= bounds.max_no_new_pages,
        "providerHardCapDetected": provider_hard_cap,
        "truncated": truncated,
        "stopReasons": sorted(set(stop_reasons)),
        "pages": pages,
    }


def _summary_without_trades(result: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in result.items()
        if key not in {"trades", "pages"}
    } | {"pages": list(result.get("pages", []))[:20] if isinstance(result.get("pages"), list) else []}


def _selection_market_rows(selection: Mapping[str, object]) -> list[dict[str, object]]:
    rows = selection.get("selectedMarkets")
    if isinstance(rows, list):
        return [dict(row) for row in rows if isinstance(row, Mapping)]
    return []


def _reference_market_counts(report: Mapping[str, object]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    rows: list[Mapping[str, object]] = []
    for key in ("display_trades", "display_review_required_trades", "suspicious_trades", "review_required_trades"):
        value = report.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, Mapping))
    for row in rows:
        keys = [str(row.get("conditionId") or ""), str(row.get("marketSlug") or "")]
        for key in [item for item in keys if item]:
            bucket = counts.setdefault(key, {"highReviewRows": 0, "weakHistoryRows": 0, "sensitiveRows": 0})
            if _is_high_review(row):
                bucket["highReviewRows"] += 1
            if bool(row.get("weakHistoryNearCertaintyReviewDemotion")):
                bucket["weakHistoryRows"] += 1
            if _is_sensitive(row):
                bucket["sensitiveRows"] += 1
    return counts


def _match_market_condition(selected_market: Mapping[str, object], markets: Mapping[str, object]) -> str:
    requested_condition = str(selected_market.get("conditionId") or "").strip()
    if requested_condition and requested_condition in markets:
        return requested_condition
    requested_slug = str(selected_market.get("marketSlug") or "").strip()
    for condition_id, market in markets.items():
        if str(getattr(market, "slug", "") or "") == requested_slug:
            return condition_id
    return ""


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
    chunk_size = max(1, span // count)
    chunks: list[tuple[int, int]] = []
    cursor = start_ts
    for index in range(count):
        chunk_end = end_ts if index == count - 1 else min(end_ts, cursor + chunk_size - 1)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + 1
        if cursor > end_ts:
            break
    return chunks


def _gate(
    *,
    bounds_hit: bool,
    added_rows: int,
    candidate_delta: int,
    provider_or_query_bound: bool,
    baseline_truncated: bool,
) -> str:
    if bounds_hit:
        return "granular_probe_blocked_by_bounds"
    if added_rows > 0 or candidate_delta > 0:
        return "granular_probe_found_material_new_rows"
    if provider_or_query_bound:
        return "granular_probe_no_new_rows_provider_or_query_bound"
    if baseline_truncated:
        return "granular_probe_marker_conservative_monitor_only"
    return "granular_probe_needs_provider_semantics_rfc"


def _blocked_payload(
    selected_market: Mapping[str, object] | None,
    bounds: GranularProbeBounds,
    env_status: Mapping[str, object],
    output_dir: Path,
    violations: Sequence[str],
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
        "selectedMarket": dict(selected_market or {}),
        "summary": {
            "gateDecision": "granular_probe_blocked_by_bounds",
            "boundViolations": list(violations),
            "addedRows": 0,
            "addedCandidateFloorRows": 0,
        },
        "forbiddenActionsPreserved": _forbidden_actions(),
    }


def _truncation_interpretations() -> list[dict[str, str]]:
    return [
        {
            "status": "provider_or_local_page_cap",
            "meaning": "The current production slice reached the bounded page/offset cap.",
        },
        {
            "status": "report_inferred",
            "meaning": "Older reports may expose aggregate truncation without per-page evidence.",
        },
        {
            "status": "duplicate_cursor_or_plateau",
            "meaning": "A granular probe can show repeated page signatures or no-new-row plateaus.",
        },
        {
            "status": "scope_mismatch",
            "meaning": "Selected-market or subset evidence must not be interpreted as whole-event complete.",
        },
    ]


def _forbidden_actions() -> list[str]:
    return [
        "No production pagination expansion.",
        "No scoring, threshold, gate, Phase 3, storage schema, or UI sorting changes.",
        "No saved artifact mutation.",
        "No private keys, CLOB auth, trading credentials, or order placement.",
        "No whole-event completeness claim from a one-market probe.",
    ]


def _candidate_floor_count(trades: Sequence[Trade], minimum: Decimal) -> int:
    return sum(1 for trade in trades if trade.notional >= minimum)


def _unique_trade_count_from_results(results: Sequence[Mapping[str, object]]) -> int:
    seen: set[tuple[str, str, str]] = set()
    for result in results:
        for trade in result.get("trades", []):
            if isinstance(trade, Trade):
                seen.add(_trade_key(trade))
    return len(seen)


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


def _is_high_review(row: Mapping[str, object]) -> bool:
    if str(row.get("hardEvidenceReviewTier") or "").strip():
        return True
    return _int(row.get("eventForensicScore")) >= 70


def _is_sensitive(row: Mapping[str, object]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in (
            "hardEvidenceSources",
            "fundingEvidenceGrade",
            "suspiciousFundingQuality",
            "strongRiskGateReasons",
        )
    ).lower()
    return any(marker in text for marker in ("funding", "strong risk", "hard evidence", "her"))


def _load_json_object(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _try_load_json_object(path: str | Path) -> dict[str, object]:
    try:
        return _load_json_object(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _decimal(value: object, default: Decimal) -> Decimal:
    try:
        text = str(value or "").strip()
        return Decimal(text) if text else default
    except (InvalidOperation, ValueError):
        return default


def _int(value: object) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", default=str(DEFAULT_SELECTION))
    parser.add_argument("--previous-collection", default=str(DEFAULT_PREVIOUS_COLLECTION))
    parser.add_argument("--reference-report", default=str(DEFAULT_REFERENCE_REPORT))
    parser.add_argument("--market-slug", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--max-time-chunks", type=int, default=8)
    parser.add_argument("--max-pages-per-window", type=int, default=31)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-total-unique-rows", type=int, default=50_000)
    parser.add_argument("--max-wall-minutes", type=int, default=30)
    parser.add_argument("--max-no-new-pages", type=int, default=2)
    parser.add_argument("--min-notional", default="250")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    selection = _load_json_object(args.selection)
    previous_collection = _try_load_json_object(args.previous_collection)
    reference_report = _try_load_json_object(args.reference_report)
    bounds = GranularProbeBounds(
        max_time_chunks=args.max_time_chunks,
        max_pages_per_window=args.max_pages_per_window,
        page_size=args.page_size,
        max_total_unique_rows=args.max_total_unique_rows,
        max_wall_minutes=args.max_wall_minutes,
        max_no_new_pages=args.max_no_new_pages,
        min_notional=_decimal(args.min_notional, Decimal("250")),
    )
    plan = build_probe_plan(
        selection=selection,
        previous_collection=previous_collection,
        reference_report=reference_report,
        explicit_market_slug=args.market_slug,
        bounds=bounds,
        env_status=runtime_env_status(root=ROOT),
    )
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else ROOT / "validation_outputs" / f"event_forensic_granular_pagination_probe_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    if args.run_live and plan["gateDecision"] == "granular_probe_plan_ready":
        payload = run_live_probe(
            selection=selection,
            selected_market=plan["selectedMarket"],  # type: ignore[arg-type]
            bounds=bounds,
            output_dir=output_dir,
        )
    else:
        payload = plan
    write_json(payload, args.output)
    if args.run_live:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(payload, output_dir / "summary.json")
    gate = payload.get("gateDecision") or (payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}).get("gateDecision")
    if not args.quiet:
        print(f"gate: {gate}")
        print(f"output: {args.output}")
    return 0 if gate not in {"granular_probe_blocked_by_bounds"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
