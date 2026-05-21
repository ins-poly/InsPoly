#!/usr/bin/env python3
"""Read-only ceasefire event leak-risk investigation exporter.

This tool is intentionally separate from the production InsPoly scanner and
Event Forensic scorer. It resolves one Polymarket event, fetches full Data API
trade windows, computes a case-specific read-only score, and writes analyst
review files without changing production scoring, schemas, UI, or saved runs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import AppConfig
from app.event_forensic import EventForensicAnalyzer, _winning_outcome_from_payload
from app.models import Market, Trade
from app.polymarket import CLOB_BASE, DATA_BASE, MAX_TRADES_OFFSET, PolymarketClient, _get_json
from app.storage import Storage


EVENT_SLUG_SAFE = "russia_ukraine_ceasefire_before_2027"
DEFAULT_EVENT_URL = "https://polymarket.com/event/russia-x-ukraine-ceasefire-before-2027"
TRUTH_SOCIAL_STATUS_ID = 116540259118606629
FINAL_T0_WORKING = "2026-05-08T18:00:31Z"
FINAL_T0_FALLBACK = "2026-05-08T18:12:00Z"
PRIMARY_YES = "Yes"
PRIMARY_NO = "No"
MAX_TRADE_PAGES = 40
TRADE_PAGE_SIZE = 100
MAX_RETRIEVABLE_ROWS = min(MAX_TRADE_PAGES * TRADE_PAGE_SIZE, MAX_TRADES_OFFSET + TRADE_PAGE_SIZE)

KYIV_TZ = ZoneInfo("Europe/Kyiv")
EASTERN_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class WindowSpec:
    window_id: str
    label: str
    anchor_id: str
    start: datetime
    end: datetime
    classification: str


@dataclass
class WalletContext:
    wallet: str
    total_predictions: int | None
    trades: list[Trade]
    loaded_unique_market_count: int
    first_loaded_trade: datetime | None
    last_loaded_trade: datetime | None
    fetch_error: str = ""


def parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if re.search(r"[+-]\d{2}$", text):
        text = text + ":00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def iso_z(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def local_iso(value: datetime | None, tz: ZoneInfo) -> str:
    if value is None:
        return ""
    return value.astimezone(tz).replace(microsecond=0).isoformat()


def decimal_value(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def serialize_cell(value: Any) -> str | int | float | bool:
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return iso_z(value)
    if isinstance(value, (list, dict, tuple, set)):
        return json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True)
    return str(value)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return iso_z(value)
    if isinstance(value, Trade):
        return value.to_dict()
    if isinstance(value, Market):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return value


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = list(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in materialized:
            writer.writerow({field: serialize_cell(row.get(field, "")) for field in fieldnames})


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def decode_truth_social_status_time(status_id: int) -> datetime:
    # Truth Social/Mastodon-style status IDs encode millisecond epoch time in
    # the high 48 bits. The low 16 bits are sequence bits.
    timestamp_ms = status_id >> 16
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)


def fetch_text(url: str, timeout: int = 15) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; InsPoly/0.1; +https://polymarket.com)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.5",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "ignore")


def build_timeline_anchors(*, verify_timeline: bool) -> tuple[list[dict[str, Any]], datetime, dict[str, Any]]:
    final_working = parse_dt(FINAL_T0_WORKING)
    if final_working is None:
        raise RuntimeError("FINAL_T0_WORKING is malformed")
    truth_decoded = decode_truth_social_status_time(TRUTH_SOCIAL_STATUS_ID)
    truth_delta_seconds = abs((truth_decoded - final_working).total_seconds())
    truth_verified = truth_delta_seconds < 1.5
    archive_seen = False
    archive_error = ""
    archive_url = "https://trumpstruth.org/statuses/38279"
    if verify_timeline:
        try:
            archive_text = fetch_text(archive_url)
            archive_seen = str(TRUTH_SOCIAL_STATUS_ID) in archive_text and "May 8, 2026" in archive_text
        except Exception as exc:  # noqa: BLE001 - verification must not crash the run.
            archive_error = f"{type(exc).__name__}: {exc}"

    if truth_verified:
        final_t0 = final_working
        final_status = "verified_status_id_decode"
        final_notes = (
            f"Truth Social status ID {TRUTH_SOCIAL_STATUS_ID} decodes to "
            f"{truth_decoded.isoformat()}; direct Truth Social endpoints may return 403."
        )
        if archive_seen:
            final_status = "verified_status_id_decode_and_archive_page_seen"
            final_notes += " Trump's Truth archive page contained the status ID and date."
        elif archive_error:
            final_notes += f" Archive fetch failed: {archive_error}."
    else:
        final_t0 = parse_dt(FINAL_T0_FALLBACK) or final_working
        final_status = "fallback_used_truth_status_decode_mismatch"
        final_notes = (
            f"Truth Social status ID decoded to {truth_decoded.isoformat()}, not the working timestamp; "
            "using Ukrainska Pravda fallback."
        )

    source_user = "user-provided timeline anchor; requires manual review"
    anchors = [
        {
            "anchor_id": "early_call_t0",
            "anchor_name": "Kremlin/Ushakov says Putin told Trump he was ready to announce a Victory Day truce",
            "utc_time": "2026-04-29T17:45:00Z",
            "source_url_or_source_name": source_user,
            "verified_status": "not_independently_verified_in_tool",
            "notes": "Used as supplied; included for price/trade cross-checking.",
        },
        {
            "anchor_id": "russian_first_truce_t0",
            "anchor_name": "Russian MoD announces unilateral truce for 8-9 May",
            "utc_time": "2026-05-04T17:33:00Z",
            "source_url_or_source_name": source_user,
            "verified_status": "not_independently_verified_in_tool",
            "notes": "Used as supplied; public-signal contamination begins after this anchor for affected trades.",
        },
        {
            "anchor_id": "ukraine_counter_t0",
            "anchor_name": "Zelenskyy says Ukraine will introduce ceasefire regime and act reciprocally",
            "utc_time": "2026-05-04T18:49:00Z",
            "source_url_or_source_name": source_user,
            "verified_status": "not_independently_verified_in_tool",
            "notes": "Used as supplied; public-signal contamination begins after this anchor for affected trades.",
        },
        {
            "anchor_id": "ukraine_ceasefire_start",
            "anchor_name": "Ukraine ceasefire start, 00:00 Kyiv on 6 May",
            "utc_time": "2026-05-05T21:00:00Z",
            "source_url_or_source_name": source_user,
            "verified_status": "calendar_conversion_verified",
            "notes": "00:00 Kyiv on 2026-05-06 converts to 2026-05-05T21:00:00Z.",
        },
        {
            "anchor_id": "ukraine_violation_negative_signal",
            "anchor_name": "Air alerts / first reports of Russia violating the ceasefire within minutes",
            "utc_time": "2026-05-05T21:09:00Z",
            "source_url_or_source_name": source_user,
            "verified_status": "not_independently_verified_in_tool",
            "notes": "Negative signal used for contamination/reducer context.",
        },
        {
            "anchor_id": "russian_reaffirm_t0",
            "anchor_name": "Russian MoD re-declares truce from 00:00 May 8 through May 10",
            "utc_time": "2026-05-07T16:22:00Z",
            "source_url_or_source_name": source_user,
            "verified_status": "not_independently_verified_in_tool",
            "notes": "Trades after this anchor and before the Trump statement are treated as public-info contaminated.",
        },
        {
            "anchor_id": "zelensky_negative_morning_signal",
            "anchor_name": "Zelenskyy says Russia did not make even a token attempt to cease fire",
            "utc_time": "2026-05-08T05:10:00Z",
            "source_url_or_source_name": source_user,
            "verified_status": "not_independently_verified_in_tool",
            "notes": "Negative signal used as a reducer/context row.",
        },
        {
            "anchor_id": "final_t0_truthsocial_working",
            "anchor_name": "Trump Truth Social announcement of three-day ceasefire and prisoner swap",
            "utc_time": iso_z(final_t0),
            "source_url_or_source_name": archive_url,
            "verified_status": final_status,
            "notes": final_notes,
        },
        {
            "anchor_id": "final_t0_public_media_fallback",
            "anchor_name": "Ukrainska Pravda had published Trump-statement story by 21:12 Kyiv",
            "utc_time": FINAL_T0_FALLBACK,
            "source_url_or_source_name": "https://www.pravda.com.ua/news/2026/05/08/8033886/",
            "verified_status": "fallback_not_used" if truth_verified else "fallback_used",
            "notes": "Fallback anchor only if Truth Social timestamp cannot be technically verified.",
        },
        {
            "anchor_id": "zelensky_confirmation_working",
            "anchor_name": "Zelenskyy confirmation working timestamp inferred from X status ID",
            "utc_time": "2026-05-08T18:22:51Z",
            "source_url_or_source_name": source_user,
            "verified_status": "not_independently_verified_in_tool",
            "notes": "X status ID was not supplied to this tool, so timestamp remains working/unverified.",
        },
        {
            "anchor_id": "ap_wide_public_timestamp",
            "anchor_name": "AP wide public article timestamp",
            "utc_time": "2026-05-08T18:26:46Z",
            "source_url_or_source_name": "https://apnews.com/article/007c385a9b81ba81b4b51c1a5b8ace9b",
            "verified_status": "media_timestamp_seen_in_web_search",
            "notes": "AP search result exposed 2026-05-08 18:26:46 UTC.",
        },
    ]
    for anchor in anchors:
        dt = parse_dt(str(anchor["utc_time"]))
        anchor["kyiv_time"] = local_iso(dt, KYIV_TZ)
        anchor["eastern_time"] = local_iso(dt, EASTERN_TZ)
    verification = {
        "truthSocialStatusId": TRUTH_SOCIAL_STATUS_ID,
        "decodedUtc": truth_decoded,
        "workingUtc": final_working,
        "deltaSeconds": truth_delta_seconds,
        "verified": truth_verified,
        "archiveUrl": archive_url,
        "archiveSeen": archive_seen,
        "archiveError": archive_error,
        "fallbackUsed": not truth_verified,
        "finalT0Used": final_t0,
    }
    return anchors, final_t0, verification


def build_windows(final_t0: datetime, resolution_boundary: datetime | None) -> list[WindowSpec]:
    windows = [
        WindowSpec(
            "primary_final_pre_public_48h",
            "Primary final-announcement pre-public window",
            "final_t0_truthsocial_working",
            parse_dt("2026-05-06T18:00:31Z") or final_t0 - timedelta(hours=48),
            parse_dt("2026-05-08T17:45:31Z") or final_t0 - timedelta(minutes=15),
            "pre_announcement",
        ),
        WindowSpec(
            "primary_high_risk_band",
            "Primary high-risk band",
            "final_t0_truthsocial_working",
            parse_dt("2026-05-08T06:00:31Z") or final_t0 - timedelta(hours=12),
            parse_dt("2026-05-08T17:45:31Z") or final_t0 - timedelta(minutes=15),
            "pre_announcement",
        ),
        WindowSpec(
            "very_high_risk_non_immediate_band",
            "Very-high-risk non-immediate band",
            "final_t0_truthsocial_working",
            parse_dt("2026-05-08T16:00:31Z") or final_t0 - timedelta(hours=2),
            parse_dt("2026-05-08T17:45:31Z") or final_t0 - timedelta(minutes=15),
            "pre_announcement",
        ),
        WindowSpec(
            "public_bot_news_reaction_band",
            "Public bot / news reaction band",
            "final_t0_truthsocial_working",
            parse_dt("2026-05-08T17:45:31Z") or final_t0 - timedelta(minutes=15),
            parse_dt("2026-05-08T19:00:31Z") or final_t0 + timedelta(hours=1),
            "public_reaction",
        ),
        WindowSpec(
            "pre_russian_reaffirmation_window",
            "Pre-Russian-reaffirmation window",
            "russian_reaffirm_t0",
            parse_dt("2026-05-05T16:22:00Z") or final_t0,
            parse_dt("2026-05-07T16:07:00Z") or final_t0,
            "pre_announcement",
        ),
        WindowSpec(
            "pre_first_russian_truce_window",
            "Pre-first-Russian-truce window",
            "russian_first_truce_t0",
            parse_dt("2026-05-02T17:33:00Z") or final_t0,
            parse_dt("2026-05-04T17:18:00Z") or final_t0,
            "pre_announcement",
        ),
        WindowSpec(
            "pre_ukraine_counter_ceasefire_window",
            "Pre-Ukraine-counter-ceasefire window",
            "ukraine_counter_t0",
            parse_dt("2026-05-02T18:49:00Z") or final_t0,
            parse_dt("2026-05-04T18:34:00Z") or final_t0,
            "pre_announcement",
        ),
        WindowSpec(
            "early_putin_trump_ushakov_signal_window",
            "Early Putin-Trump / Ushakov signal window",
            "early_call_t0",
            parse_dt("2026-04-27T17:45:00Z") or final_t0,
            parse_dt("2026-04-29T17:30:00Z") or final_t0,
            "pre_announcement",
        ),
    ]
    if resolution_boundary is not None:
        start = final_t0 + timedelta(minutes=30)
        end = resolution_boundary - timedelta(minutes=15)
        if end > start:
            windows.append(
                WindowSpec(
                    "resolution_arbitrage_window",
                    "Resolution-arbitrage window",
                    "resolution_boundary",
                    start,
                    end,
                    "resolution_arbitrage_candidate",
                )
            )
    return windows


def resolve_event(event_url: str) -> Any:
    cfg = AppConfig.load_event_forensic_analyzer()
    analyzer = EventForensicAnalyzer(PolymarketClient(), Storage(cfg.db_path), cfg)
    return analyzer.resolve_input(event_url)


def relevant_markets(resolved: Any) -> dict[str, Market]:
    matches: dict[str, Market] = {}
    for condition_id, market in resolved.markets.items():
        text = f"{market.slug} {market.question}".lower()
        if "ceasefire" in text and ("russia" in text or "ukraine" in text):
            matches[condition_id] = market
    return matches or dict(resolved.markets)


def market_detail_rows(resolved: Any, markets: Mapping[str, Market]) -> list[dict[str, Any]]:
    rows = []
    for condition_id, market in markets.items():
        payload = resolved.market_payloads.get(condition_id, {})
        rows.append(
            {
                "condition_id": condition_id,
                "market_id": market.market_id,
                "market_slug": market.slug,
                "question": market.question,
                "outcomes": market.outcomes,
                "token_ids": market.token_ids,
                "final_outcome": _winning_outcome_from_payload(payload),
                "closed": bool(payload.get("closed")),
                "active": bool(payload.get("active")),
                "accepting_orders": bool(payload.get("acceptingOrders")),
                "end_date": payload.get("endDate"),
                "closed_time": payload.get("closedTime"),
                "uma_end_date": payload.get("umaEndDate"),
                "uma_resolution_status": payload.get("umaResolutionStatus"),
                "automatically_resolved": payload.get("automaticallyResolved"),
                "rules": payload.get("description") or resolved.event_description,
                "outcome_prices": payload.get("outcomePrices"),
            }
        )
    return rows


def detect_resolution_boundary(resolved: Any, markets: Mapping[str, Market]) -> tuple[datetime | None, dict[str, Any]]:
    candidates: list[tuple[str, datetime]] = []
    for condition_id in markets:
        payload = resolved.market_payloads.get(condition_id, {})
        for key in ("resolutionProposedAt", "umaProposedAt", "umaEndDate", "closedTime"):
            parsed = parse_dt(payload.get(key))
            if parsed is not None:
                candidates.append((f"market.{condition_id}.{key}", parsed))
    parsed_event_closed = parse_dt(resolved.event_payload.get("closedTime"))
    if parsed_event_closed is not None:
        candidates.append(("event.closedTime", parsed_event_closed))
    if not candidates:
        return None, {
            "resolutionProposalStatus": "not_found",
            "notes": "No UMA proposal or close timestamp fields were available in Gamma payloads.",
        }
    chosen_source, chosen_time = max(candidates, key=lambda item: item[1])
    return chosen_time, {
        "resolutionProposalStatus": (
            "proposal_timestamp_not_independently_confirmed_gamma_resolution_boundary_used"
        ),
        "resolutionBoundaryUtc": chosen_time,
        "resolutionBoundarySourceField": chosen_source,
        "availableResolutionFields": [
            {"source": source, "utc": timestamp} for source, timestamp in sorted(candidates, key=lambda item: item[1])
        ],
        "notes": (
            "Gamma exposed umaEndDate/closedTime but not an independently named proposal timestamp. "
            "The resolution-arbitrage end uses the best available Gamma resolution boundary minus 15 minutes."
        ),
    }


def fetch_price_history(asset_id: str, start: datetime, end: datetime) -> tuple[list[dict[str, Any]], str]:
    params = {
        "market": asset_id,
        "startTs": int(start.timestamp()),
        "endTs": int(end.timestamp()),
        "interval": "max",
        "fidelity": 5,
    }
    try:
        payload = _get_json(f"{CLOB_BASE}/prices-history", params, timeout=15)
    except Exception as exc:  # noqa: BLE001 - price history is diagnostic, not fatal.
        return [], f"{type(exc).__name__}: {exc}"
    if not isinstance(payload, dict):
        return [], "unexpected_non_dict_payload"
    history = payload.get("history")
    if not isinstance(history, list):
        return [], "missing_history_list"
    points = []
    for point in history:
        if not isinstance(point, dict):
            continue
        timestamp = parse_price_time(point)
        price = decimal_value(point.get("p"), Decimal("-1"))
        if timestamp is None or price < 0:
            continue
        points.append({"t": int(timestamp.timestamp()), "time": timestamp, "p": price})
    points.sort(key=lambda item: item["time"])
    return points, ""


def parse_price_time(point: Mapping[str, Any]) -> datetime | None:
    raw = point.get("t")
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def price_at(history: list[dict[str, Any]], when: datetime) -> Decimal | None:
    if not history:
        return None
    before = [point for point in history if point["time"] <= when]
    if before:
        return decimal_value(before[-1]["p"])
    after = [point for point in history if point["time"] > when]
    return decimal_value(after[0]["p"]) if after else None


def price_move(history: list[dict[str, Any]], start: datetime, end: datetime) -> Decimal | None:
    start_price = price_at(history, start)
    end_price = price_at(history, end)
    if start_price is None or end_price is None:
        return None
    return end_price - start_price


def max_move_between(history: list[dict[str, Any]], start: datetime, end: datetime) -> Decimal | None:
    points = [decimal_value(point["p"]) for point in history if start <= point["time"] <= end]
    if len(points) < 2:
        return None
    low = points[0]
    best = Decimal("0")
    for price in points[1:]:
        if price - low > best:
            best = price - low
        if price < low:
            low = price
    return best


def first_jump_time(history: list[dict[str, Any]], *, min_move: Decimal = Decimal("0.05"), max_minutes: int = 60) -> str:
    if len(history) < 2:
        return ""
    for index, point in enumerate(history):
        start_time = point["time"]
        start_price = decimal_value(point["p"])
        for later in history[index + 1 :]:
            if later["time"] - start_time > timedelta(minutes=max_minutes):
                break
            if decimal_value(later["p"]) - start_price >= min_move:
                return iso_z(later["time"])
    return ""


def largest_window_jump(history: list[dict[str, Any]], minutes: int) -> dict[str, Any]:
    best = {"move": Decimal("0"), "start": "", "end": ""}
    for index, point in enumerate(history):
        start_time = point["time"]
        start_price = decimal_value(point["p"])
        for later in history[index + 1 :]:
            if later["time"] - start_time > timedelta(minutes=minutes):
                break
            move = decimal_value(later["p"]) - start_price
            if move > best["move"]:
                best = {"move": move, "start": iso_z(start_time), "end": iso_z(later["time"])}
    return best


def price_reaction_rows(
    anchors: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    global_first_jump = first_jump_time(history)
    largest_15m = largest_window_jump(history, 15)
    largest_30m = largest_window_jump(history, 30)
    largest_1h = largest_window_jump(history, 60)
    for anchor in anchors:
        anchor_dt = parse_dt(str(anchor.get("utc_time") or ""))
        if anchor_dt is None:
            continue
        rows.append(
            {
                "anchor_id": anchor["anchor_id"],
                "price_24h_before": price_at(history, anchor_dt - timedelta(hours=24)),
                "price_12h_before": price_at(history, anchor_dt - timedelta(hours=12)),
                "price_6h_before": price_at(history, anchor_dt - timedelta(hours=6)),
                "price_1h_before": price_at(history, anchor_dt - timedelta(hours=1)),
                "price_at_anchor": price_at(history, anchor_dt),
                "price_1h_after": price_at(history, anchor_dt + timedelta(hours=1)),
                "max_yes_move_before_anchor": max_move_between(history, anchor_dt - timedelta(hours=24), anchor_dt),
                "max_yes_move_after_anchor": max_move_between(history, anchor_dt, anchor_dt + timedelta(hours=24)),
                "first_detected_jump_time": global_first_jump,
                "notes": "Prices use CLOB prices-history interval=max fidelity=5; max moves are within +/-24h of anchor.",
            }
        )
    diagnostics = {
        "firstSignificantYesJumpTime": global_first_jump,
        "largest15mYesJump": largest_15m,
        "largest30mYesJump": largest_30m,
        "largest1hYesJump": largest_1h,
    }
    return rows, diagnostics


def fetch_trades_for_window(
    client: PolymarketClient,
    condition_id: str,
    window: WindowSpec,
    *,
    large_backfill_notional: Decimal,
) -> tuple[list[Trade], dict[str, Any]]:
    start_ts = int(window.start.timestamp())
    end_ts = int(window.end.timestamp())
    error = ""
    large_error = ""
    try:
        base = client.fetch_trades_in_range(
            start_ts=start_ts,
            end_ts=end_ts,
            max_pages=MAX_TRADE_PAGES,
            page_size=TRADE_PAGE_SIZE,
            condition_ids=[condition_id],
        )
    except Exception as exc:  # noqa: BLE001 - write partial outputs.
        base = []
        error = f"{type(exc).__name__}: {exc}"
    try:
        large = client.fetch_trades_in_range(
            start_ts=start_ts,
            end_ts=end_ts,
            max_pages=MAX_TRADE_PAGES,
            page_size=TRADE_PAGE_SIZE,
            condition_ids=[condition_id],
            filter_cash_amount=large_backfill_notional,
        )
    except Exception as exc:  # noqa: BLE001
        large = []
        large_error = f"{type(exc).__name__}: {exc}"
    rows = dedupe_trade_objects([*base, *large])
    raw_truncated = len(base) >= MAX_RETRIEVABLE_ROWS
    large_truncated = len(large) >= MAX_RETRIEVABLE_ROWS
    return rows, {
        "window_id": window.window_id,
        "condition_id": condition_id,
        "start_utc": window.start,
        "end_utc": window.end,
        "base_rows": len(base),
        "large_backfill_rows": len(large),
        "deduped_rows": len(rows),
        "raw_truncation_risk": raw_truncated,
        "large_backfill_truncation_risk": large_truncated,
        "large_backfill_notional": large_backfill_notional,
        "error": error,
        "large_backfill_error": large_error,
    }


def dedupe_trade_objects(trades: Iterable[Trade]) -> list[Trade]:
    unique: dict[tuple[str, str, str, str, str, str, str, str], Trade] = {}
    for trade in trades:
        key = (
            trade.trade_id,
            trade.wallet,
            trade.condition_id,
            trade.asset_id,
            trade.side,
            trade.outcome,
            iso_z(trade.timestamp),
            f"{trade.price}:{trade.size}",
        )
        unique[key] = trade
    return sorted(unique.values(), key=lambda item: (item.timestamp, item.trade_id, item.wallet))


def trade_key(trade: Trade) -> tuple[str, str, str, str, str, str, str, str]:
    return (
        trade.trade_id,
        trade.wallet,
        trade.condition_id,
        trade.asset_id,
        trade.side,
        trade.outcome,
        iso_z(trade.timestamp),
        f"{trade.price}:{trade.size}",
    )


def fetch_wallet_context(wallet: str, trade_limit: int = 500) -> WalletContext:
    total_predictions: int | None = None
    trades: list[Trade] = []
    fetch_error = ""
    try:
        traded_payload = _get_json(f"{DATA_BASE}/traded", {"user": wallet}, timeout=12)
        if isinstance(traded_payload, dict) and traded_payload.get("traded") is not None:
            total_predictions = int_value(traded_payload.get("traded"))
    except Exception as exc:  # noqa: BLE001
        fetch_error = f"traded:{type(exc).__name__}: {exc}"
    try:
        trade_payload = _get_json(
            f"{DATA_BASE}/trades",
            {"user": wallet, "limit": trade_limit, "offset": 0},
            timeout=15,
        )
        if isinstance(trade_payload, list):
            trades = [Trade.from_api(item) for item in trade_payload if isinstance(item, dict)]
    except Exception as exc:  # noqa: BLE001
        suffix = f"trades:{type(exc).__name__}: {exc}"
        fetch_error = f"{fetch_error}; {suffix}" if fetch_error else suffix
    unique_markets = {trade.condition_id for trade in trades if trade.condition_id}
    ordered = sorted(trades, key=lambda item: item.timestamp)
    return WalletContext(
        wallet=wallet,
        total_predictions=total_predictions,
        trades=ordered,
        loaded_unique_market_count=len(unique_markets),
        first_loaded_trade=ordered[0].timestamp if ordered else None,
        last_loaded_trade=ordered[-1].timestamp if ordered else None,
        fetch_error=fetch_error,
    )


def fetch_wallet_contexts(wallets: Iterable[str], workers: int = 8) -> dict[str, WalletContext]:
    wallet_list = sorted({wallet for wallet in wallets if wallet})
    if not wallet_list:
        return {}
    results: dict[str, WalletContext] = {}
    with ThreadPoolExecutor(max_workers=min(workers, len(wallet_list))) as executor:
        futures = {executor.submit(fetch_wallet_context, wallet): wallet for wallet in wallet_list}
        for future in as_completed(futures):
            wallet = futures[future]
            try:
                results[wallet] = future.result()
            except Exception as exc:  # noqa: BLE001
                results[wallet] = WalletContext(wallet=wallet, total_predictions=None, trades=[], loaded_unique_market_count=0, first_loaded_trade=None, last_loaded_trade=None, fetch_error=f"{type(exc).__name__}: {exc}")
    return results


def prior_position(trade: Trade, wallet_context: WalletContext | None, event_trades: list[Trade]) -> Decimal:
    candidates = []
    if wallet_context is not None:
        candidates.extend(
            item
            for item in wallet_context.trades
            if item.asset_id == trade.asset_id and item.trade_id != trade.trade_id and item.timestamp < trade.timestamp
        )
    candidates.extend(
        item
        for item in event_trades
        if item.wallet == trade.wallet
        and item.asset_id == trade.asset_id
        and item.trade_id != trade.trade_id
        and item.timestamp < trade.timestamp
    )
    deduped = dedupe_trade_objects(candidates)
    position = Decimal("0")
    for item in sorted(deduped, key=lambda row: (row.timestamp, row.trade_id)):
        if item.side == "BUY":
            position += item.size
        elif item.side == "SELL":
            position -= item.size
    return position


def assess_trade_direction(
    trade: Trade,
    *,
    wallet_context: WalletContext | None,
    event_trades: list[Trade],
) -> dict[str, Any]:
    prior = prior_position(trade, wallet_context, event_trades)
    outcome = trade.outcome.strip().lower()
    side = trade.side.upper()
    yes_equiv = Decimal("0")
    entry_probability = trade.price
    opening = False
    direction = "other"
    confidence = "not_yes_equivalent"
    if side == "BUY" and outcome == PRIMARY_YES.lower():
        yes_equiv = trade.notional
        entry_probability = trade.price
        opening = True
        direction = "buy_yes"
        confidence = "direct_buy_yes"
    elif side == "SELL" and outcome == PRIMARY_NO.lower():
        yes_equiv = max(Decimal("0"), (Decimal("1") - trade.price) * trade.size)
        entry_probability = max(Decimal("0"), Decimal("1") - trade.price)
        direction = "sell_no_yes_equivalent"
        if prior <= Decimal("0.01"):
            opening = True
            confidence = "opening_short_no_from_loaded_inventory_logic"
        else:
            opening = False
            confidence = "sell_no_reduces_loaded_no_inventory"
    elif side == "SELL" and outcome == PRIMARY_YES.lower():
        direction = "sell_yes_reduce_or_close"
        confidence = "pure_close_or_reduce_candidate"
    elif side == "BUY" and outcome == PRIMARY_NO.lower():
        direction = "buy_no_opposite_direction"
        confidence = "opposite_direction"
    return {
        "economic_direction": direction,
        "yes_equivalent_exposure": yes_equiv,
        "entry_probability": entry_probability,
        "opening_exposure": opening,
        "prior_loaded_asset_position": prior,
        "position_logic_confidence": confidence,
    }


def public_contamination_for_trade(timestamp: datetime) -> str:
    russian_first = parse_dt("2026-05-04T17:33:00Z") or timestamp
    ukrainian_counter = parse_dt("2026-05-04T18:49:00Z") or timestamp
    russian_reaffirm = parse_dt("2026-05-07T16:22:00Z") or timestamp
    final_t0 = parse_dt(FINAL_T0_WORKING) or timestamp
    if timestamp >= final_t0 - timedelta(minutes=15):
        return "public_or_immediate_news_reaction"
    if timestamp >= russian_reaffirm:
        return "after_russian_reaffirmation_public_info_contaminated"
    if timestamp >= ukrainian_counter:
        return "after_ukraine_counter_and_before_russian_reaffirmation"
    if timestamp >= russian_first:
        return "after_first_russian_truce_public_info_contaminated"
    return "clean_before_listed_public_truce_signals"


def window_priority(window_id: str) -> int:
    order = {
        "very_high_risk_non_immediate_band": 90,
        "primary_high_risk_band": 80,
        "primary_final_pre_public_48h": 70,
        "pre_russian_reaffirmation_window": 60,
        "early_putin_trump_ushakov_signal_window": 55,
        "pre_first_russian_truce_window": 50,
        "pre_ukraine_counter_ceasefire_window": 49,
        "public_bot_news_reaction_band": 20,
        "resolution_arbitrage_window": 10,
    }
    return order.get(window_id, 0)


def choose_primary_assessment(assessments: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        assessments,
        key=lambda row: (
            1 if row.get("window_classification") == "pre_announcement" else 0,
            window_priority(str(row.get("source_window") or "")),
            -abs(float_value(row.get("minutes_before_anchor"), 999999)),
        ),
    )


def base_trade_row(
    trade: Trade,
    market: Market,
    payload: Mapping[str, Any],
    window: WindowSpec,
    anchors_by_id: Mapping[str, Mapping[str, Any]],
    direction: Mapping[str, Any],
    price_history: list[dict[str, Any]],
) -> dict[str, Any]:
    anchor_dt = parse_dt(str(anchors_by_id.get(window.anchor_id, {}).get("utc_time") or ""))
    if window.anchor_id == "resolution_boundary":
        anchor_dt = window.end + timedelta(minutes=15)
    minutes_before = ""
    price_move_to_anchor = ""
    price_move_after_entry = ""
    if anchor_dt is not None:
        minutes_before = round((anchor_dt - trade.timestamp).total_seconds() / 60.0, 3)
        move = price_move(price_history, trade.timestamp, anchor_dt)
        if move is not None:
            price_move_to_anchor = move
            price_move_after_entry = move
    profile_url = f"https://polymarket.com/profile/{trade.wallet}" if trade.wallet else ""
    entry_probability = decimal_value(direction.get("entry_probability"))
    return {
        "wallet": trade.wallet,
        "username": trade.trader_name or trade.trader_pseudonym,
        "profile_url": profile_url,
        "trade_id": trade.trade_id,
        "timestamp_utc": iso_z(trade.timestamp),
        "timestamp_kyiv": local_iso(trade.timestamp, KYIV_TZ),
        "timestamp_eastern": local_iso(trade.timestamp, EASTERN_TZ),
        "anchor_id": window.anchor_id,
        "minutes_before_anchor": minutes_before,
        "market": market.question,
        "market_slug": market.slug,
        "condition_id": market.condition_id,
        "side": trade.side,
        "outcome": trade.outcome,
        "order_side": trade.side,
        "price": trade.price,
        "entry_probability_pct": entry_probability * Decimal("100"),
        "size": trade.size,
        "notional_usdc": trade.notional,
        "yes_equivalent_exposure": direction.get("yes_equivalent_exposure", Decimal("0")),
        "opening_exposure": bool(direction.get("opening_exposure")),
        "economic_direction": direction.get("economic_direction", ""),
        "position_logic_confidence": direction.get("position_logic_confidence", ""),
        "prior_loaded_asset_position": direction.get("prior_loaded_asset_position", ""),
        "later_won": _winning_outcome_from_payload(dict(payload)) == PRIMARY_YES
        and bool(direction.get("opening_exposure")),
        "price_move_to_anchor": price_move_to_anchor,
        "price_move_after_entry": price_move_after_entry,
        "existingModelScore": "",
        "eventForensicScore": "",
        "source_window": window.window_id,
        "window_classification": window.classification,
        "public_contamination_level": public_contamination_for_trade(trade.timestamp),
    }


def score_trade_row(row: dict[str, Any], wallet_metrics: Mapping[str, Any]) -> dict[str, Any]:
    exposure = decimal_value(row.get("yes_equivalent_exposure"))
    price_pct = decimal_value(row.get("entry_probability_pct")) / Decimal("100")
    minutes = float_value(row.get("minutes_before_anchor"), 999999)
    score = 0.0
    reasons: list[str] = []
    reducers: list[str] = []

    if row.get("source_window") == "very_high_risk_non_immediate_band":
        score += 25
        reasons.append("T0-2h_to_T0-15m")
    elif row.get("source_window") == "primary_high_risk_band":
        score += 22
        reasons.append("T0-12h_to_T0-15m")
    elif row.get("source_window") == "primary_final_pre_public_48h":
        score += 16
        reasons.append("T0-48h_to_T0-15m")
    elif row.get("window_classification") == "pre_announcement":
        score += 14
        reasons.append("pre_public_anchor_window")

    if exposure >= Decimal("100000"):
        score += 30
        reasons.append("critical_value_candidate")
    elif exposure >= Decimal("25000"):
        score += 24
        reasons.append("high_value_candidate")
    elif exposure >= Decimal("5000"):
        score += 17
        reasons.append("single_large_candidate")
    elif exposure >= Decimal("2500"):
        score += 10
        reasons.append("notable_size")
    elif exposure > 0:
        score += min(8.0, math.log10(float(exposure) + 1) * 2.2)

    aggregate = decimal_value(wallet_metrics.get("aggregate_yes_exposure"))
    count = int_value(wallet_metrics.get("yes_trade_count"))
    buy_yes_count = int_value(wallet_metrics.get("buy_yes_trade_count"))
    if buy_yes_count >= 5 and aggregate >= Decimal("2500"):
        score += 15
        reasons.append("repeated_small_candidate")
    elif buy_yes_count >= 3 and aggregate >= Decimal("5000"):
        score += 13
        reasons.append("alternative_repeated_candidate")

    if price_pct <= Decimal("0.35"):
        score += 20
        reasons.append("very_strong_low_entry_probability")
    elif price_pct <= Decimal("0.60"):
        score += 12
        reasons.append("strong_low_entry_probability")
    elif price_pct <= Decimal("0.85"):
        score += 5
        reasons.append("moderate_entry_probability")
    else:
        reducers.append("near_certainty_or_high_entry_probability")
        score -= 8

    move = decimal_value(row.get("price_move_after_entry"))
    if move >= Decimal("0.25"):
        score += 18
        reasons.append("large_yes_repricing_after_entry")
    elif move >= Decimal("0.10"):
        score += 10
        reasons.append("meaningful_yes_repricing_after_entry")
    elif move >= Decimal("0.05"):
        score += 5
        reasons.append("some_yes_repricing_after_entry")

    contamination = str(row.get("public_contamination_level") or "")
    if contamination == "clean_before_listed_public_truce_signals":
        score += 12
        reasons.append("clean_before_listed_public_truce_signals")
    elif contamination == "after_russian_reaffirmation_public_info_contaminated":
        score -= 8
        reducers.append("after_russian_reaffirmation_public_signal")
    elif "public_info_contaminated" in contamination:
        score -= 5
        reducers.append(contamination)

    if bool(wallet_metrics.get("dormant_reactivation_flag")):
        score += 7
        reasons.append("dormant_or_reactivated_wallet")
    if bool(wallet_metrics.get("timing_cluster_flag")):
        score += 5
        reasons.append("same_side_timing_cluster")
    if bool(wallet_metrics.get("related_market_repeat_flag")):
        score += 4
        reasons.append("related_market_repeat_exposure")
    if bool(wallet_metrics.get("public_power_user_flag")):
        score -= 12
        reducers.append("high_volume_public_power_user_without_independent_hard_evidence")
    if row.get("economic_direction") == "sell_no_yes_equivalent":
        reducers.append("sell_no_requires_manual_inventory_review")
    if row.get("position_logic_confidence") != "direct_buy_yes":
        reducers.append(str(row.get("position_logic_confidence") or "position_logic_limited"))

    score = max(0.0, min(100.0, score))
    risk_tier = risk_tier_for_score(score, exposure)
    row.update(
        {
            "ceasefireLeakRiskScore": round(score, 2),
            "risk_tier": risk_tier,
            "reason_codes": sorted(set(reasons)),
            "reducers": sorted(set(item for item in reducers if item)),
            "why_suspicious": build_why_suspicious(row, reasons),
        }
    )
    return row


def risk_tier_for_score(score: float, exposure: Decimal) -> str:
    if score >= 85 or exposure >= Decimal("100000"):
        return "critical_review_candidate"
    if score >= 70 or exposure >= Decimal("25000"):
        return "high_review_candidate"
    if score >= 50 or exposure >= Decimal("5000"):
        return "medium_review_candidate"
    return "watchlist_requires_manual_review"


def build_why_suspicious(row: Mapping[str, Any], reasons: Iterable[str]) -> str:
    reason_text = ", ".join(sorted(set(reasons))[:6])
    return (
        "Insider-risk candidate requiring manual review: pre-announcement YES exposure "
        f"of {serialize_cell(row.get('yes_equivalent_exposure'))} USDC-equivalent in "
        f"{row.get('source_window')} before {row.get('anchor_id')}. Reasons: {reason_text}."
    )


def build_wallet_metrics(
    candidate_rows: list[dict[str, Any]],
    wallet_contexts: Mapping[str, WalletContext],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_rows:
        grouped[str(row.get("wallet") or "")].append(row)
    result: dict[str, dict[str, Any]] = {}
    for wallet, rows in grouped.items():
        exposures = [decimal_value(row.get("yes_equivalent_exposure")) for row in rows]
        probabilities = [decimal_value(row.get("entry_probability_pct")) for row in rows]
        timestamps = [parse_dt(str(row.get("timestamp_utc") or "")) for row in rows]
        timestamps = [ts for ts in timestamps if ts is not None]
        context = wallet_contexts.get(wallet)
        loaded_trades = context.trades if context is not None else []
        first_trade = min(timestamps) if timestamps else None
        prior_loaded = [trade for trade in loaded_trades if first_trade is not None and trade.timestamp < first_trade]
        prior_gap_days = None
        if prior_loaded and first_trade is not None:
            prior_gap_days = (first_trade - max(trade.timestamp for trade in prior_loaded)).total_seconds() / 86400.0
        related_repeat = any(
            trade.condition_id not in {str(row.get("condition_id") or "") for row in rows}
            and any(token in f"{trade.slug} {trade.title}".lower() for token in ("russia", "ukraine", "ceasefire"))
            for trade in loaded_trades
        )
        total_predictions = context.total_predictions if context is not None else None
        loaded_unique = context.loaded_unique_market_count if context is not None else 0
        public_power = (total_predictions or 0) >= 100 or loaded_unique >= 100 or len(loaded_trades) >= 400
        result[wallet] = {
            "wallet": wallet,
            "username": next((str(row.get("username") or "") for row in rows if row.get("username")), ""),
            "profile_url": f"https://polymarket.com/profile/{wallet}" if wallet else "",
            "aggregate_yes_exposure": sum(exposures, Decimal("0")),
            "largest_single_yes_trade": max(exposures) if exposures else Decimal("0"),
            "yes_trade_count": len(rows),
            "buy_yes_trade_count": sum(1 for row in rows if row.get("economic_direction") == "buy_yes"),
            "first_yes_trade_utc": iso_z(min(timestamps)) if timestamps else "",
            "last_yes_trade_before_anchor_utc": iso_z(max(timestamps)) if timestamps else "",
            "avg_entry_probability_pct": (sum(probabilities, Decimal("0")) / Decimal(len(probabilities))) if probabilities else "",
            "min_entry_probability_pct": min(probabilities) if probabilities else "",
            "wallet_total_predictions": total_predictions if total_predictions is not None else "",
            "loaded_unique_market_count": loaded_unique,
            "public_power_user_flag": public_power,
            "dormant_reactivation_flag": bool(prior_gap_days is None or prior_gap_days >= 30),
            "dormant_reactivation_gap_days": "" if prior_gap_days is None else round(prior_gap_days, 2),
            "related_market_repeat_flag": related_repeat,
            "wallet_fetch_error": context.fetch_error if context is not None else "not_loaded",
        }
    return result


def candidate_wallet_filter(metrics: Mapping[str, Any], *, min_single: Decimal, min_aggregate: Decimal) -> bool:
    largest = decimal_value(metrics.get("largest_single_yes_trade"))
    aggregate = decimal_value(metrics.get("aggregate_yes_exposure"))
    count = int_value(metrics.get("buy_yes_trade_count"))
    return (
        largest >= min_single
        or aggregate >= Decimal("25000")
        or (count >= 5 and aggregate >= min_aggregate)
        or (count >= 3 and aggregate >= Decimal("5000"))
    )


def build_timing_clusters(candidate_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_rows:
        timestamp = parse_dt(str(row.get("timestamp_utc") or ""))
        if timestamp is None:
            continue
        bucket_minute = (timestamp.minute // 15) * 15
        bucket = timestamp.replace(minute=bucket_minute, second=0, microsecond=0)
        key = (
            str(row.get("anchor_id") or ""),
            str(row.get("condition_id") or ""),
            str(row.get("economic_direction") or ""),
            iso_z(bucket),
        )
        grouped[key].append(row)
    rows = []
    wallet_flags: dict[str, set[str]] = defaultdict(set)
    for index, ((anchor_id, condition_id, direction, bucket), items) in enumerate(grouped.items(), start=1):
        wallets = sorted({str(item.get("wallet") or "") for item in items if item.get("wallet")})
        if len(wallets) < 2:
            continue
        aggregate = sum((decimal_value(item.get("yes_equivalent_exposure")) for item in items), Decimal("0"))
        timestamps = [parse_dt(str(item.get("timestamp_utc") or "")) for item in items]
        timestamps = [item for item in timestamps if item is not None]
        for wallet in wallets:
            wallet_flags[wallet].add("timing_cluster")
        rows.append(
            {
                "cluster_id": f"timing_cluster_{index:03d}",
                "cluster_type": "same_side_timing_cluster",
                "wallets": wallets,
                "wallet_count": len(wallets),
                "shared_funder": "unknown_not_traced",
                "same_side_timing_pattern": f"{direction} trades in 15m bucket {bucket}",
                "same_market_or_related_markets": condition_id,
                "aggregate_yes_exposure": aggregate,
                "earliest_trade_utc": iso_z(min(timestamps)) if timestamps else "",
                "latest_trade_utc": iso_z(max(timestamps)) if timestamps else "",
                "anchor_id": anchor_id,
                "cluster_score": min(100, 40 + len(wallets) * 8 + int(min(float(aggregate) / 1000, 30))),
                "explanation": (
                    "Same-side timing cluster requiring manual review; funding linkage was not established "
                    "by this read-only run."
                ),
            }
        )
    rows.sort(key=lambda row: (int_value(row.get("cluster_score")), decimal_value(row.get("aggregate_yes_exposure"))), reverse=True)
    return rows, wallet_flags


def row_is_near_certainty(row: Mapping[str, Any]) -> bool:
    return decimal_value(row.get("entry_probability_pct")) >= Decimal("94")


def build_excluded_rows(all_rows: list[dict[str, Any]], suspicious_keys: set[tuple[str, str]]) -> list[dict[str, Any]]:
    rows = []
    for row in all_rows:
        key = (str(row.get("trade_id") or ""), str(row.get("wallet") or ""))
        reasons = []
        if key in suspicious_keys:
            continue
        if row.get("window_classification") == "public_reaction":
            reasons.append("public_or_news_reaction_band")
        if row.get("window_classification") == "resolution_arbitrage_candidate":
            reasons.append("resolution_arbitrage_after_public_announcement")
        if row_is_near_certainty(row):
            reasons.append("near_certainty_entry")
        if not row.get("opening_exposure"):
            reasons.append("pure_close_reduce_or_opposite_direction")
        contamination = str(row.get("public_contamination_level") or "")
        if "public" in contamination or "contaminated" in contamination:
            reasons.append(contamination)
        if reasons:
            rows.append({**row, "exclusion_or_downrank_reason": sorted(set(reasons))})
    return rows


def output_trade_fieldnames() -> list[str]:
    return [
        "rank",
        "ceasefireLeakRiskScore",
        "wallet",
        "username",
        "profile_url",
        "trade_id",
        "timestamp_utc",
        "timestamp_kyiv",
        "timestamp_eastern",
        "anchor_id",
        "minutes_before_anchor",
        "market",
        "market_slug",
        "condition_id",
        "side",
        "outcome",
        "order_side",
        "price",
        "entry_probability_pct",
        "size",
        "notional_usdc",
        "yes_equivalent_exposure",
        "opening_exposure",
        "economic_direction",
        "position_logic_confidence",
        "later_won",
        "price_move_to_anchor",
        "price_move_after_entry",
        "existingModelScore",
        "eventForensicScore",
        "risk_tier",
        "reason_codes",
        "why_suspicious",
        "reducers",
        "source_window",
        "public_contamination_level",
        "prior_loaded_asset_position",
    ]


def wallet_fieldnames() -> list[str]:
    return [
        "rank",
        "ceasefireLeakRiskScore",
        "wallet",
        "username",
        "profile_url",
        "aggregate_yes_exposure",
        "largest_single_yes_trade",
        "yes_trade_count",
        "first_yes_trade_utc",
        "last_yes_trade_before_anchor_utc",
        "avg_entry_probability_pct",
        "min_entry_probability_pct",
        "main_anchor",
        "clean_pre_public_window_flag",
        "public_contamination_level",
        "wallet_total_predictions",
        "loaded_unique_market_count",
        "public_power_user_flag",
        "dormant_reactivation_flag",
        "shared_funding_flag",
        "split_wallet_flag",
        "timing_cluster_flag",
        "related_market_repeat_flag",
        "risk_tier",
        "reason_codes",
        "why_suspicious",
        "reducers",
    ]


def classify_wallet_rows(
    suspicious_trade_rows: list[dict[str, Any]],
    wallet_metrics: dict[str, dict[str, Any]],
    timing_flags: Mapping[str, set[str]],
) -> list[dict[str, Any]]:
    by_wallet_trades: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in suspicious_trade_rows:
        by_wallet_trades[str(row.get("wallet") or "")].append(row)
    wallet_rows = []
    for wallet, metrics in wallet_metrics.items():
        trades = by_wallet_trades.get(wallet, [])
        if not trades:
            continue
        max_score = max(float_value(row.get("ceasefireLeakRiskScore")) for row in trades)
        reasons = sorted({reason for row in trades for reason in row.get("reason_codes", [])})
        reducers = sorted({reason for row in trades for reason in row.get("reducers", [])})
        contamination_values = Counter(str(row.get("public_contamination_level") or "") for row in trades)
        main_anchor = Counter(str(row.get("anchor_id") or "") for row in trades).most_common(1)[0][0]
        timing_cluster = "timing_cluster" in timing_flags.get(wallet, set())
        if timing_cluster:
            metrics["timing_cluster_flag"] = True
        exposure = decimal_value(metrics.get("aggregate_yes_exposure"))
        wallet_row = {
            **metrics,
            "ceasefireLeakRiskScore": round(max_score, 2),
            "main_anchor": main_anchor,
            "clean_pre_public_window_flag": all(
                str(row.get("public_contamination_level") or "") == "clean_before_listed_public_truce_signals"
                for row in trades
            ),
            "public_contamination_level": contamination_values.most_common(1)[0][0] if contamination_values else "",
            "shared_funding_flag": "unknown_not_traced",
            "split_wallet_flag": "unknown_not_traced",
            "timing_cluster_flag": timing_cluster,
            "risk_tier": risk_tier_for_score(max_score, exposure),
            "reason_codes": reasons,
            "why_suspicious": (
                "Wallet-level insider-risk candidate requiring manual review: pre-announcement YES exposure "
                f"aggregates to {serialize_cell(exposure)} USDC-equivalent across {metrics.get('yes_trade_count')} trade(s)."
            ),
            "reducers": reducers,
        }
        wallet_rows.append(wallet_row)
    wallet_rows.sort(
        key=lambda row: (
            float_value(row.get("ceasefireLeakRiskScore")),
            decimal_value(row.get("aggregate_yes_exposure")),
            decimal_value(row.get("largest_single_yes_trade")),
        ),
        reverse=True,
    )
    for index, row in enumerate(wallet_rows, start=1):
        row["rank"] = index
    return wallet_rows


def write_wallet_packets(run_dir: Path, wallet_rows: list[dict[str, Any]], trade_rows: list[dict[str, Any]]) -> None:
    packet_dir = run_dir / "top_wallet_packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    trades_by_wallet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trade_rows:
        trades_by_wallet[str(row.get("wallet") or "")].append(row)
    for row in wallet_rows[:25]:
        wallet = str(row.get("wallet") or "")
        rank = int_value(row.get("rank"))
        safe_wallet = wallet[:10] if wallet else f"wallet_{rank}"
        packet = {
            "rank": rank,
            "walletProfile": {
                "wallet": wallet,
                "username": row.get("username", ""),
                "profileUrl": row.get("profile_url", ""),
                "walletTotalPredictions": row.get("wallet_total_predictions", ""),
                "loadedUniqueMarketCount": row.get("loaded_unique_market_count", ""),
                "publicPowerUserFlag": row.get("public_power_user_flag", ""),
            },
            "exposureSummary": {key: row.get(key, "") for key in wallet_fieldnames() if key in row},
            "tradeList": trades_by_wallet.get(wallet, []),
            "manualReviewChecklist": [
                "Confirm the wallet's full inventory before treating SELL No as YES-equivalent opening exposure.",
                "Check whether public Russian/Ukrainian truce statements were already available before each trade.",
                "Check whether the wallet had earlier accumulation outside the listed windows.",
                "Check funding/source linkage independently if RPC or explorer data is available.",
                "Treat this packet as an insider-risk candidate, not proof of insider trading.",
            ],
            "links": {
                "profile": row.get("profile_url", ""),
            },
        }
        write_json(packet_dir / f"{rank:02d}_{safe_wallet}.json", packet)
        lines = [
            f"# Wallet Packet {rank}: {wallet}",
            "",
            "## Summary",
            f"- Ceasefire leak risk score: {row.get('ceasefireLeakRiskScore')}",
            f"- Risk tier: {row.get('risk_tier')}",
            f"- Aggregate YES exposure: {serialize_cell(row.get('aggregate_yes_exposure'))}",
            f"- Largest single YES trade: {serialize_cell(row.get('largest_single_yes_trade'))}",
            f"- First YES trade UTC: {row.get('first_yes_trade_utc')}",
            f"- Last YES trade before anchor UTC: {row.get('last_yes_trade_before_anchor_utc')}",
            f"- Reason codes: {', '.join(row.get('reason_codes') or [])}",
            f"- Reducers: {', '.join(row.get('reducers') or [])}",
            "",
            "## Trades",
        ]
        for trade in trades_by_wallet.get(wallet, []):
            lines.append(
                "- "
                f"{trade.get('timestamp_utc')} {trade.get('side')} {trade.get('outcome')} "
                f"at {trade.get('price')} for {serialize_cell(trade.get('yes_equivalent_exposure'))} "
                f"YES-equivalent in {trade.get('source_window')}"
            )
        lines.extend(
            [
                "",
                "## Manual Review Checklist",
                "- Confirm the wallet's full inventory before treating SELL No as YES-equivalent opening exposure.",
                "- Check whether public Russian/Ukrainian truce statements were already available before each trade.",
                "- Check whether the wallet had earlier accumulation outside the listed windows.",
                "- Check funding/source linkage independently if RPC or explorer data is available.",
                "- These rows are suspicious candidates, not proof of insider trading.",
            ]
        )
        (packet_dir / f"{rank:02d}_{safe_wallet}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_wallet_graph(wallet_rows: list[dict[str, Any]], clusters: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = [
        {
            "id": row.get("wallet", ""),
            "label": row.get("username") or str(row.get("wallet", ""))[:10],
            "score": row.get("ceasefireLeakRiskScore", ""),
            "riskTier": row.get("risk_tier", ""),
            "aggregateYesExposure": row.get("aggregate_yes_exposure", ""),
        }
        for row in wallet_rows
    ]
    edges = []
    for cluster in clusters:
        wallets = cluster.get("wallets") or []
        if isinstance(wallets, str):
            try:
                parsed = json.loads(wallets)
                wallets = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                wallets = []
        wallet_list = [str(wallet) for wallet in wallets if wallet]
        for index, left in enumerate(wallet_list):
            for right in wallet_list[index + 1 :]:
                edges.append(
                    {
                        "source": left,
                        "target": right,
                        "type": cluster.get("cluster_type", ""),
                        "clusterId": cluster.get("cluster_id", ""),
                        "weight": cluster.get("cluster_score", ""),
                    }
                )
    return {
        "nodes": nodes,
        "edges": edges,
        "notes": "Graph contains read-only timing/linkage candidates only; no funding edge is proof of insider trading.",
    }


def render_summary(summary: Mapping[str, Any], wallet_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Russia-Ukraine Ceasefire Before 2027 Forensic Run Summary",
        "",
        f"- Event URL: {summary.get('eventUrl')}",
        f"- Event final outcome: {summary.get('eventFinalOutcome')}",
        f"- Relevant market count: {summary.get('relevantMarketCount')}",
        f"- Truth Social timestamp verification: {summary.get('truthSocialVerificationStatus')}",
        f"- Resolution boundary status: {summary.get('resolutionProposalStatus')}",
        f"- Data API truncation risk: {summary.get('dataApiTruncationStatus')}",
        f"- All collected trade rows: {summary.get('allCollectedTradeRows')}",
        f"- Main 48h YES opening rows: {summary.get('main48hYesOpeningTradeCount')}",
        f"- Suspicious trade candidates: {summary.get('suspiciousTradeCount')}",
        f"- Suspicious wallet candidates: {summary.get('suspiciousWalletCount')}",
        f"- Timing clusters: {summary.get('clusterCount')}",
        "",
        "## Windows Used",
    ]
    for window in summary.get("windowsUsed", []):
        lines.append(
            f"- {window['window_id']}: {window['start_utc']} to {window['end_utc']} "
            f"({window['classification']})"
        )
    lines.extend(["", "## Top Wallets"])
    for row in wallet_rows[:20]:
        lines.append(
            f"- #{row.get('rank')} {row.get('wallet')}: score {row.get('ceasefireLeakRiskScore')}, "
            f"{row.get('risk_tier')}, aggregate YES exposure {serialize_cell(row.get('aggregate_yes_exposure'))}"
        )
    lines.extend(
        [
            "",
            "## Methodology",
            "- The tool used full Data API window fetches per condition ID and wrote raw bundles; it did not rely on the Event Forensic UI visible top slice.",
            "- Primary candidate logic focuses on BUY Yes opening exposure before public anchors. SELL No is only included when loaded inventory logic supports YES-equivalent opening exposure and is still marked for manual review.",
            "- `ceasefireLeakRiskScore` is a read-only investigation score for this export only. It does not alter InsPoly production scoring.",
            "- Public/news-reaction trades and resolution-arbitrage trades are separated from pre-announcement insider-risk candidates.",
            "",
            "## Limitations",
            "- Wallet inventory is based on loaded Data API history and may be incomplete for old positions.",
            "- Funding linkage is marked unknown unless independently traced; no finding should be treated as proof.",
            "- Some non-final timeline anchors were accepted from the user-provided timeline and marked as not independently verified in-tool.",
            "",
            "Rows are suspicious candidates, not proof of insider trading. Each requires manual review.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-url", default=DEFAULT_EVENT_URL)
    parser.add_argument("--output-dir", default="ceasefire_forensic_outputs")
    parser.add_argument("--include-blockchain", action="store_true", help="Reserved for guarded enrichment; failures remain unknown.")
    parser.add_argument("--min-single-notional", type=Decimal, default=Decimal("5000"))
    parser.add_argument("--min-aggregate-notional", type=Decimal, default=Decimal("2500"))
    parser.add_argument("--verify-timeline", action="store_true")
    parser.add_argument("--no-network", action="store_true", help="Fail unless cached inputs are added in a future version.")
    args = parser.parse_args(argv)

    if args.no_network:
        raise SystemExit("--no-network is not supported yet for this targeted investigation; no cached-input path exists.")

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = REPO_ROOT / output_root
    run_dir = output_root / f"{EVENT_SLUG_SAFE}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=False)

    anchors, final_t0, timeline_verification = build_timeline_anchors(verify_timeline=args.verify_timeline)
    anchors_by_id = {str(anchor["anchor_id"]): anchor for anchor in anchors}

    resolved = resolve_event(args.event_url)
    markets = relevant_markets(resolved)
    market_rows = market_detail_rows(resolved, markets)
    resolution_boundary, resolution_info = detect_resolution_boundary(resolved, markets)
    windows = build_windows(final_t0, resolution_boundary)

    yes_asset_id = ""
    if markets:
        first_market = next(iter(markets.values()))
        if PRIMARY_YES in first_market.outcomes:
            yes_index = first_market.outcomes.index(PRIMARY_YES)
            if yes_index < len(first_market.token_ids):
                yes_asset_id = first_market.token_ids[yes_index]
        elif first_market.token_ids:
            yes_asset_id = first_market.token_ids[0]

    price_start = min(window.start for window in windows) - timedelta(hours=30)
    price_end = max(window.end for window in windows) + timedelta(hours=2)
    price_history, price_error = fetch_price_history(yes_asset_id, price_start, price_end) if yes_asset_id else ([], "missing_yes_asset_id")
    price_rows, price_diagnostics = price_reaction_rows(anchors, price_history)

    client = PolymarketClient()
    all_window_trades: dict[str, list[Trade]] = {}
    collection_log: list[dict[str, Any]] = []
    for window in windows:
        collected: list[Trade] = []
        for condition_id in markets:
            rows, log = fetch_trades_for_window(
                client,
                condition_id,
                window,
                large_backfill_notional=min(args.min_single_notional, args.min_aggregate_notional),
            )
            collected.extend(rows)
            collection_log.append(log)
        all_window_trades[window.window_id] = dedupe_trade_objects(collected)

    all_event_trades = dedupe_trade_objects(trade for trades in all_window_trades.values() for trade in trades)
    preliminary_wallets = {
        trade.wallet
        for window_id, trades in all_window_trades.items()
        for trade in trades
        if trade.wallet and ((trade.side == "BUY" and trade.outcome == PRIMARY_YES) or (trade.side == "SELL" and trade.outcome == PRIMARY_NO))
    }
    wallet_contexts = fetch_wallet_contexts(preliminary_wallets)

    assessed_by_key: dict[tuple[str, str, str, str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    all_assessed_rows: list[dict[str, Any]] = []
    for window in windows:
        for trade in all_window_trades.get(window.window_id, []):
            market = markets.get(trade.condition_id) or next(iter(markets.values()))
            payload = resolved.market_payloads.get(market.condition_id, {})
            direction = assess_trade_direction(
                trade,
                wallet_context=wallet_contexts.get(trade.wallet),
                event_trades=all_event_trades,
            )
            row = base_trade_row(trade, market, payload, window, anchors_by_id, direction, price_history)
            assessed_by_key[trade_key(trade)].append(row)
            all_assessed_rows.append(row)

    primary_rows = [choose_primary_assessment(rows) for rows in assessed_by_key.values()]
    pre_public_yes_rows = [
        row
        for row in primary_rows
        if row.get("window_classification") == "pre_announcement"
        and row.get("opening_exposure")
        and decimal_value(row.get("yes_equivalent_exposure")) > 0
    ]
    wallet_metrics = build_wallet_metrics(pre_public_yes_rows, wallet_contexts)
    candidate_wallets = {
        wallet
        for wallet, metrics in wallet_metrics.items()
        if candidate_wallet_filter(
            metrics,
            min_single=args.min_single_notional,
            min_aggregate=args.min_aggregate_notional,
        )
    }

    scored_candidate_rows = []
    for row in pre_public_yes_rows:
        wallet = str(row.get("wallet") or "")
        single = decimal_value(row.get("yes_equivalent_exposure")) >= args.min_single_notional
        if wallet not in candidate_wallets and not single:
            continue
        scored_candidate_rows.append(score_trade_row(dict(row), wallet_metrics.get(wallet, {})))
    clusters, timing_flags = build_timing_clusters(scored_candidate_rows)
    for row in scored_candidate_rows:
        wallet = str(row.get("wallet") or "")
        if "timing_cluster" in timing_flags.get(wallet, set()):
            metrics = wallet_metrics.get(wallet, {})
            metrics["timing_cluster_flag"] = True
            score_trade_row(row, metrics)
    scored_candidate_rows.sort(
        key=lambda row: (
            float_value(row.get("ceasefireLeakRiskScore")),
            decimal_value(row.get("yes_equivalent_exposure")),
        ),
        reverse=True,
    )
    for rank, row in enumerate(scored_candidate_rows, start=1):
        row["rank"] = rank

    wallet_rows = classify_wallet_rows(scored_candidate_rows, wallet_metrics, timing_flags)
    suspicious_keys = {(str(row.get("trade_id") or ""), str(row.get("wallet") or "")) for row in scored_candidate_rows}
    excluded_rows = build_excluded_rows(primary_rows, suspicious_keys)

    main_48h_rows = [
        row
        for row in all_assessed_rows
        if row.get("source_window") == "primary_final_pre_public_48h"
        and row.get("opening_exposure")
        and decimal_value(row.get("yes_equivalent_exposure")) > 0
    ]
    main_48h_rows.sort(key=lambda row: (parse_dt(str(row.get("timestamp_utc") or "")) or datetime.min.replace(tzinfo=UTC), str(row.get("trade_id") or "")))
    public_rows = [
        row
        for row in all_assessed_rows
        if row.get("source_window") == "public_bot_news_reaction_band"
    ]
    resolution_rows = [
        {
            **row,
            "classification_note": "resolution_arbitrage_candidate_not_pre_announcement_insider_risk",
            "had_earlier_pre_public_accumulation": str(row.get("wallet") or "") in candidate_wallets,
        }
        for row in all_assessed_rows
        if row.get("source_window") == "resolution_arbitrage_window"
    ]

    timeline_fieldnames = [
        "anchor_id",
        "anchor_name",
        "utc_time",
        "kyiv_time",
        "eastern_time",
        "source_url_or_source_name",
        "verified_status",
        "notes",
    ]
    price_fieldnames = [
        "anchor_id",
        "price_24h_before",
        "price_12h_before",
        "price_6h_before",
        "price_1h_before",
        "price_at_anchor",
        "price_1h_after",
        "max_yes_move_before_anchor",
        "max_yes_move_after_anchor",
        "first_detected_jump_time",
        "notes",
    ]
    cluster_fieldnames = [
        "cluster_id",
        "cluster_type",
        "wallets",
        "wallet_count",
        "shared_funder",
        "same_side_timing_pattern",
        "same_market_or_related_markets",
        "aggregate_yes_exposure",
        "earliest_trade_utc",
        "latest_trade_utc",
        "anchor_id",
        "cluster_score",
        "explanation",
    ]

    write_csv(run_dir / "timeline_anchors.csv", anchors, timeline_fieldnames)
    write_json(run_dir / "timeline_anchors.json", anchors)
    write_csv(run_dir / "price_reaction_anchors.csv", price_rows, price_fieldnames)
    write_csv(run_dir / "all_yes_opening_trades_prefinal_48h.csv", main_48h_rows, output_trade_fieldnames()[2:])
    write_csv(run_dir / "ranked_suspicious_trades.csv", scored_candidate_rows, output_trade_fieldnames())
    write_csv(run_dir / "ranked_suspicious_wallets.csv", wallet_rows, wallet_fieldnames())
    write_csv(run_dir / "wallet_clusters.csv", clusters, cluster_fieldnames)
    write_csv(run_dir / "suspicious_trades.csv", scored_candidate_rows, output_trade_fieldnames())
    write_csv(run_dir / "suspicious_wallets.csv", wallet_rows, wallet_fieldnames())
    write_csv(run_dir / "public_bot_or_news_reaction_trades.csv", public_rows, output_trade_fieldnames()[2:])
    write_csv(run_dir / "resolution_arbitrage_candidates.csv", resolution_rows, output_trade_fieldnames()[2:] + ["classification_note", "had_earlier_pre_public_accumulation"])
    write_csv(run_dir / "excluded_or_downranked.csv", excluded_rows, output_trade_fieldnames()[2:] + ["exclusion_or_downrank_reason"])
    write_wallet_packets(run_dir, wallet_rows, scored_candidate_rows)
    write_json(
        run_dir / "related_markets.json",
        {
            "relatedMarkets": [],
            "note": "This targeted read-only investigation scoped the single resolved ceasefire child market; no external related-market expansion was run.",
        },
    )
    write_json(run_dir / "wallet_graph.json", build_wallet_graph(wallet_rows, clusters))

    raw_dir = run_dir / "raw_bundle"
    write_json(raw_dir / "event_payload.json", resolved.event_payload)
    write_json(raw_dir / "market_details.json", market_rows)
    write_json(raw_dir / "windows.json", [{"window_id": w.window_id, "label": w.label, "anchor_id": w.anchor_id, "start_utc": w.start, "end_utc": w.end, "classification": w.classification} for w in windows])
    write_json(raw_dir / "collection_log.json", collection_log)
    write_json(raw_dir / "trades_by_window.json", {window_id: [trade.to_dict() for trade in trades] for window_id, trades in all_window_trades.items()})
    write_json(raw_dir / "all_collected_trades.json", [trade.to_dict() for trade in all_event_trades])
    write_json(raw_dir / "price_history_yes.json", {"asset_id": yes_asset_id, "error": price_error, "points": price_history})
    write_json(raw_dir / "wallet_context_summary.json", {wallet: {"total_predictions": ctx.total_predictions, "loaded_unique_market_count": ctx.loaded_unique_market_count, "loaded_trade_count": len(ctx.trades), "first_loaded_trade": ctx.first_loaded_trade, "last_loaded_trade": ctx.last_loaded_trade, "fetch_error": ctx.fetch_error} for wallet, ctx in wallet_contexts.items()})
    write_json(raw_dir / "timeline_verification.json", timeline_verification)
    write_json(raw_dir / "resolution_detection.json", resolution_info)

    truncation_risk = any(log.get("raw_truncation_risk") or log.get("large_backfill_truncation_risk") for log in collection_log)
    data_api_status = (
        "truncation_risk_present_see_raw_collection_log"
        if truncation_risk
        else "no_window_reached_data_api_offset_cap_large_trade_backfill_also_below_cap"
    )
    final_outcomes = sorted({str(row.get("final_outcome") or "") for row in market_rows if row.get("final_outcome")})
    summary = {
        "generatedAt": datetime.now(UTC),
        "eventUrl": args.event_url,
        "canonicalEventUrl": resolved.canonical_url,
        "eventTitle": resolved.event_title,
        "eventFinalOutcome": ", ".join(final_outcomes) or "unknown",
        "resolvedMarketRulesSummary": market_rows[0].get("rules", "") if market_rows else "",
        "relevantMarketCount": len(markets),
        "marketDetails": market_rows,
        "truthSocialVerificationStatus": anchors_by_id["final_t0_truthsocial_working"]["verified_status"],
        "truthSocialFallbackUsed": timeline_verification.get("fallbackUsed"),
        "resolutionProposalStatus": resolution_info.get("resolutionProposalStatus"),
        "resolutionBoundaryUtc": resolution_info.get("resolutionBoundaryUtc", ""),
        "windowsUsed": [
            {
                "window_id": w.window_id,
                "label": w.label,
                "anchor_id": w.anchor_id,
                "start_utc": iso_z(w.start),
                "end_utc": iso_z(w.end),
                "classification": w.classification,
            }
            for w in windows
        ],
        "dataApiTruncationStatus": data_api_status,
        "dataCompletenessNotes": [
            "Each required window was fetched per condition ID through the Data API.",
            f"Large-trade backfill used filter_cash_amount={min(args.min_single_notional, args.min_aggregate_notional)}.",
            "If a collection_log row is marked truncated, repeated-small candidates below the backfill threshold may be incomplete.",
        ],
        "priceDiagnostics": price_diagnostics,
        "priceHistoryError": price_error,
        "allCollectedTradeRows": len(all_event_trades),
        "candidateTradeCount": len(pre_public_yes_rows),
        "main48hYesOpeningTradeCount": len(main_48h_rows),
        "suspiciousTradeCount": len(scored_candidate_rows),
        "suspiciousWalletCount": len(wallet_rows),
        "clusterCount": len(clusters),
        "publicReactionTradeCount": len(public_rows),
        "resolutionArbitrageTradeCount": len(resolution_rows),
        "excludedOrDownrankedCount": len(excluded_rows),
        "topWallets": wallet_rows[:20],
        "methodology": {
            "primaryTarget": "BUY Yes opening exposure before public anchors",
            "sellNoTreatment": "Included only when loaded inventory logic supports YES-equivalent opening exposure; requires manual review.",
            "scoreName": "ceasefireLeakRiskScore",
            "scoreScope": "read_only_investigation_only_not_production_inspoly_scoring",
        },
        "limitations": [
            "Rows are suspicious candidates, not proof of insider trading.",
            "Some source anchors remain user-provided and unverified in-tool.",
            "Wallet inventory can be incomplete if Data API wallet history does not include older positions.",
            "Funding linkage is unknown unless separately traced; include-blockchain is currently guarded and does not change scoring.",
        ],
        "productionSafety": {
            "productionScorerChanged": False,
            "eventForensicScoreChanged": False,
            "scoringThresholdsChanged": False,
            "schemaChanged": False,
            "uiChanged": False,
            "oldSavedOutputsMutated": False,
        },
    }
    write_json(run_dir / "run_summary.json", summary)
    write_json(run_dir / "event_analysis.json", summary)
    (run_dir / "run_summary.md").write_text(render_summary(summary, wallet_rows), encoding="utf-8")

    print(f"output_dir={run_dir}")
    print(f"truth_social_status={summary['truthSocialVerificationStatus']}")
    print(f"fallback_used={summary['truthSocialFallbackUsed']}")
    print(f"suspicious_trades={len(scored_candidate_rows)}")
    print(f"suspicious_wallets={len(wallet_rows)}")
    print(f"clusters={len(clusters)}")
    print(f"data_api_truncation_status={data_api_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
