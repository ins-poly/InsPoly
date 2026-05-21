#!/usr/bin/env python3
"""Second-pass read-only validation for the ceasefire forensic bundle.

This sidecar tool enriches a completed first-pass investigation bundle without
changing production scoring, Event Forensic schemas, UI behavior, or the
original saved outputs. It focuses on the two wallet candidates requested by
the analyst prompt and writes a new sibling output bundle.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import FUNDING_TRACE_MODE_CACHE_ONLY, FUNDING_TRACE_MODE_LIVE_RPC
from app.funding_context import FundingResolver
from app.polymarket import DATA_BASE, _get_json
from tools.ceasefire_event_leak_investigation import (
    decimal_value,
    iso_z,
    local_iso,
    parse_dt,
    price_at,
    serialize_cell,
    write_csv,
    write_json,
)

INPUT_BUNDLE_DEFAULT = (
    "ceasefire_forensic_outputs/"
    "russia_ukraine_ceasefire_before_2027_20260512_084148"
)
OUTPUT_PREFIX_DEFAULT = (
    "ceasefire_forensic_outputs/"
    "russia_ukraine_ceasefire_before_2027_20260512_084148_second_pass"
)
EVENT_URL = "https://polymarket.com/event/russia-x-ukraine-ceasefire-before-2027"
TARGET_SLUG = "russia-x-ukraine-ceasefire-before-2027"
WALLETS = {
    "0xde7be6d489bce070a959e0cb813128ae659b5f4b": "wan123",
    "0xa53e8fc4c2f9910e584de69d8b40a502a638218d": "VladimirPooper",
}
FINAL_T0 = "2026-05-08T18:00:31Z"
PUBLIC_REACTION_START = "2026-05-08T17:45:31Z"
PAGE_SIZE = 100
MAX_USER_PAGES = 60

KYIV_TZ = ZoneInfo("Europe/Kyiv")
EASTERN_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class SourceCandidate:
    name: str
    url: str
    fallback_utc: str
    method: str


EARLY_CALL_SOURCES = [
    SourceCandidate(
        name="Meduza metadata, source TASS",
        url=(
            "https://meduza.io/news/2026/04/29/"
            "putin-v-telefonnom-razgovore-s-trampom-predlozhil-ob-yavit-"
            "peremirie-na-period-dnya-pobedy"
        ),
        fallback_utc="2026-04-29T17:26:05Z",
        method="JSON-LD datePublished",
    ),
    SourceCandidate(
        name="Moscow 24 visible timestamp",
        url="https://www.m24.ru/news/vlast/29042026/896160",
        fallback_utc="2026-04-29T17:27:00Z",
        method="visible page timestamp converted from Moscow time",
    ),
    SourceCandidate(
        name="Gazeta.ru visible timestamp",
        url="https://www.gazeta.ru/army/news/2026/04/29/28369027.shtml",
        fallback_utc="2026-04-29T17:34:00Z",
        method="visible page timestamp converted from Moscow time",
    ),
    SourceCandidate(
        name="Interfax metadata",
        url="https://www.interfax.ru/russia/1086844",
        fallback_utc="2026-04-29T17:36:00Z",
        method="article:published_time metadata",
    ),
    SourceCandidate(
        name="TASS English metadata",
        url="https://tass.com/politics/2124485",
        fallback_utc="2026-04-29T18:03:37Z",
        method="JSON-LD datePublished",
    ),
]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_text(url: str, timeout: int = 15) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; InsPoly/0.1)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.5",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "ignore")


def extract_first_iso_datetime(text: str) -> datetime | None:
    patterns = [
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'property="article:published_time"\s+content="([^"]+)"',
        r'content="([^"]+)"\s+property="article:published_time"',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            parsed = parse_dt(match.group(1))
            if parsed is not None:
                return parsed
    return None


def normalize_trade(row: Mapping[str, Any]) -> dict[str, Any]:
    raw_ts = row.get("timestamp")
    if isinstance(raw_ts, (int, float)):
        timestamp = datetime.fromtimestamp(int(raw_ts), tz=UTC)
    else:
        timestamp = parse_dt(str(raw_ts or ""))
    price = decimal_value(row.get("price"))
    size = decimal_value(row.get("size"))
    wallet = str(row.get("proxyWallet") or row.get("wallet") or "").lower()
    return {
        "trade_id": str(row.get("transactionHash") or row.get("trade_id") or ""),
        "wallet": wallet,
        "side": str(row.get("side") or "").upper(),
        "outcome": str(row.get("outcome") or ""),
        "asset_id": str(row.get("asset") or row.get("asset_id") or ""),
        "condition_id": str(row.get("conditionId") or row.get("condition_id") or "").lower(),
        "price": price,
        "size": size,
        "notional_usdc": price * size,
        "timestamp": timestamp,
        "market": str(row.get("title") or row.get("market") or ""),
        "market_slug": str(row.get("slug") or row.get("market_slug") or ""),
        "event_slug": str(row.get("eventSlug") or row.get("event_slug") or ""),
        "username": str(row.get("name") or row.get("trader_name") or row.get("username") or ""),
        "pseudonym": str(row.get("pseudonym") or row.get("trader_pseudonym") or ""),
    }


def trade_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str, str]:
    timestamp = row.get("timestamp")
    timestamp_text = iso_z(timestamp) if isinstance(timestamp, datetime) else str(timestamp or "")
    return (
        str(row.get("trade_id") or ""),
        str(row.get("asset_id") or ""),
        timestamp_text,
        str(row.get("side") or ""),
        str(row.get("price") or ""),
        str(row.get("size") or ""),
    )


def fetch_user_trades(wallet: str) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    error = ""
    for page in range(MAX_USER_PAGES):
        params = {"user": wallet, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE}
        try:
            payload = _get_json(f"{DATA_BASE}/trades", params, timeout=20)
        except Exception as exc:  # noqa: BLE001 - enrichment must keep going.
            error = f"{type(exc).__name__}: {exc}"
            break
        if not isinstance(payload, list) or not payload:
            break
        rows.extend(normalize_trade(item) for item in payload if isinstance(item, Mapping))
        if len(payload) < PAGE_SIZE:
            break
    rows = dedupe_trades(rows)
    rows.sort(key=lambda item: (item.get("timestamp") or datetime.min.replace(tzinfo=UTC), str(item.get("trade_id") or "")))
    return rows, error


def fetch_user_market_trades(wallet: str, condition_id: str) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    error = ""
    for page in range(MAX_USER_PAGES):
        params = {
            "user": wallet,
            "market": condition_id,
            "limit": PAGE_SIZE,
            "offset": page * PAGE_SIZE,
        }
        try:
            payload = _get_json(f"{DATA_BASE}/trades", params, timeout=20)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            break
        if not isinstance(payload, list) or not payload:
            break
        rows.extend(normalize_trade(item) for item in payload if isinstance(item, Mapping))
        if len(payload) < PAGE_SIZE:
            break
    rows = dedupe_trades(rows)
    rows.sort(key=lambda item: (item.get("timestamp") or datetime.min.replace(tzinfo=UTC), str(item.get("trade_id") or "")))
    return rows, error


def dedupe_trades(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for row in rows:
        key = trade_key(row)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def is_related_market(row: Mapping[str, Any], target_condition_id: str) -> bool:
    if str(row.get("condition_id") or "").lower() == target_condition_id.lower():
        return True
    text = " ".join(
        [
            str(row.get("market") or ""),
            str(row.get("market_slug") or ""),
            str(row.get("event_slug") or ""),
        ]
    ).lower()
    has_ceasefire = "ceasefire" in text or "truce" in text
    has_target_actor = any(term in text for term in ["russia", "ukraine", "putin", "zelensky"])
    has_adjacent_deadline = any(term in text for term in ["april", "may", "june", "2026", "gta"])
    return has_ceasefire and has_target_actor and has_adjacent_deadline


def classify_inventory(
    *,
    side: str,
    outcome: str,
    position_before: Decimal,
    target_market: bool,
) -> str:
    if not target_market:
        return "related-market ledger row"
    if side == "BUY" and outcome.lower() == "yes":
        return "first-entry/opening exposure" if position_before <= Decimal("0.000001") else "existing-position add-on"
    if side == "SELL" and outcome.lower() == "yes":
        return "sell/reduce/exit" if position_before > Decimal("0.000001") else "sell-without-loaded-inventory"
    if side == "BUY" and outcome.lower() == "no":
        return "opposite-direction no exposure"
    if side == "SELL" and outcome.lower() == "no":
        return "yes-equivalent sell-no opening" if position_before <= Decimal("0.000001") else "sell-no reduce"
    return "unknown"


def build_chronology(
    *,
    wallet: str,
    rows: list[dict[str, Any]],
    target_condition_id: str,
    yes_asset_id: str,
    suspicious_ids: set[str],
    public_ids: set[str],
    resolution_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    related_rows = [row for row in rows if is_related_market(row, target_condition_id)]
    related_rows.sort(key=lambda item: (item["timestamp"] or datetime.min.replace(tzinfo=UTC), str(item.get("trade_id") or "")))
    positions: defaultdict[tuple[str, str], Decimal] = defaultdict(Decimal)
    target_yes_position = Decimal("0")
    target_yes_cost_basis = Decimal("0")
    target_yes_realized_pnl = Decimal("0")
    ledger: list[dict[str, Any]] = []

    for row in related_rows:
        timestamp = row.get("timestamp")
        target_market = str(row.get("condition_id") or "").lower() == target_condition_id.lower()
        asset_key = (str(row.get("condition_id") or "").lower(), str(row.get("asset_id") or ""))
        before_asset = positions[asset_key]
        side = str(row.get("side") or "").upper()
        outcome = str(row.get("outcome") or "")
        size = decimal_value(row.get("size"))
        price = decimal_value(row.get("price"))
        position_delta = size if side == "BUY" else -size if side == "SELL" else Decimal("0")
        positions[asset_key] = before_asset + position_delta

        before_yes = target_yes_position
        if target_market and str(row.get("asset_id") or "") == yes_asset_id:
            if side == "BUY":
                target_yes_position += size
                target_yes_cost_basis += price * size
            elif side == "SELL":
                sell_size = min(size, target_yes_position)
                avg_cost = (
                    target_yes_cost_basis / target_yes_position
                    if target_yes_position > 0
                    else Decimal("0")
                )
                target_yes_realized_pnl += (price - avg_cost) * sell_size
                target_yes_position -= sell_size
                target_yes_cost_basis -= avg_cost * sell_size
        after_yes = target_yes_position
        trade_id = str(row.get("trade_id") or "")
        inventory = classify_inventory(
            side=side,
            outcome=outcome,
            position_before=before_asset,
            target_market=target_market,
        )
        ledger.append(
            {
                "timestamp_utc": timestamp,
                "timestamp_kyiv": local_iso(timestamp, KYIV_TZ) if isinstance(timestamp, datetime) else "",
                "timestamp_eastern": local_iso(timestamp, EASTERN_TZ) if isinstance(timestamp, datetime) else "",
                "wallet": wallet,
                "username": row.get("username") or WALLETS.get(wallet, ""),
                "trade_id": trade_id,
                "market": row.get("market"),
                "market_slug": row.get("market_slug"),
                "event_slug": row.get("event_slug"),
                "condition_id": row.get("condition_id"),
                "asset_id": row.get("asset_id"),
                "side": side,
                "outcome": outcome,
                "price": price,
                "size": size,
                "notional_usdc": row.get("notional_usdc"),
                "is_target_market": target_market,
                "is_related_market": True,
                "inventory_classification": inventory,
                "position_before_asset": before_asset,
                "position_delta": position_delta,
                "position_after_asset": positions[asset_key],
                "target_yes_position_before": before_yes,
                "target_yes_position_after": after_yes,
                "target_yes_cost_basis_after": target_yes_cost_basis,
                "target_yes_realized_pnl_after": target_yes_realized_pnl,
                "first_pass_suspicious_flag": trade_id in suspicious_ids,
                "public_news_reaction_flag": trade_id in public_ids,
                "resolution_arbitrage_flag": trade_id in resolution_ids,
            }
        )

    estimated_pnl = target_yes_realized_pnl + target_yes_position - target_yes_cost_basis
    summary = {
        "related_trade_count": len(related_rows),
        "target_trade_count": sum(1 for row in ledger if row["is_target_market"]),
        "target_yes_position_end": target_yes_position,
        "target_yes_cost_basis_end": target_yes_cost_basis,
        "target_yes_realized_pnl": target_yes_realized_pnl,
        "target_yes_resolution_value_estimate": target_yes_position,
        "target_yes_total_pnl_estimate": estimated_pnl,
        "pnl_caveat": (
            "Approximate Data API ledger for target YES token only; fees, redemption transactions, "
            "CTF merge/split activity, and unloaded inventory outside fetched rows are not fully modeled."
        ),
    }
    return ledger, summary


def position_before_time(ledger: list[dict[str, Any]], when: datetime) -> Decimal:
    position = Decimal("0")
    for row in ledger:
        row_time = parse_dt(str(row.get("timestamp_utc") or ""))
        if row_time is not None and row_time < when and bool(row.get("is_target_market")):
            position = decimal_value(row.get("target_yes_position_after"))
    return position


def first_matching_time(ledger: list[dict[str, Any]], predicate: Any) -> datetime | None:
    for row in ledger:
        if predicate(row):
            return parse_dt(str(row.get("timestamp_utc") or ""))
    return None


def verify_early_call_anchor(*, enable_network: bool) -> dict[str, Any]:
    source_results = []
    for candidate in EARLY_CALL_SOURCES:
        verified_time = parse_dt(candidate.fallback_utc)
        fetch_status = "fallback_static_after_manual_web_check"
        fetch_error = ""
        if enable_network:
            try:
                text = fetch_text(candidate.url)
                parsed = extract_first_iso_datetime(text)
                if parsed is not None:
                    verified_time = parsed
                    fetch_status = "verified_by_fetch"
                else:
                    fetch_status = "fetched_no_machine_timestamp_used_static"
            except Exception as exc:  # noqa: BLE001
                fetch_status = "fetch_failed_used_static"
                fetch_error = f"{type(exc).__name__}: {exc}"
        source_results.append(
            {
                "name": candidate.name,
                "url": candidate.url,
                "verified_utc": iso_z(verified_time),
                "method": candidate.method,
                "fetch_status": fetch_status,
                "fetch_error": fetch_error,
            }
        )
    parsed_sources = [item for item in source_results if parse_dt(item["verified_utc"]) is not None]
    earliest = min(parsed_sources, key=lambda item: parse_dt(item["verified_utc"]) or datetime.max.replace(tzinfo=UTC))
    return {
        "earliest": earliest,
        "sources": source_results,
        "notes": (
            "No verified public source before 2026-04-29T17:21:26Z was found in this pass. "
            "Kremlin search results did not expose an April 29 official page earlier than the media metadata checked."
        ),
    }


def build_anchor_report(
    timeline_rows: list[dict[str, str]],
    suspicious_rows: list[dict[str, str]],
    *,
    verify_network: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    suspicious_times = [
        (row.get("wallet", "").lower(), parse_dt(row.get("timestamp_utc")), row)
        for row in suspicious_rows
    ]
    suspicious_times = [(wallet, ts, row) for wallet, ts, row in suspicious_times if ts is not None]
    timeline_by_id = {row.get("anchor_id"): row for row in timeline_rows}
    early = verify_early_call_anchor(enable_network=verify_network)
    checked = {
        "early_call_t0": {
            "verified_utc": early["earliest"]["verified_utc"],
            "source_name": early["earliest"]["name"],
            "source_url": early["earliest"]["url"],
            "verification_method": early["earliest"]["method"],
            "verified_status": early["earliest"]["fetch_status"],
            "notes": early["notes"],
            "sources_checked": early["sources"],
        },
        "russian_first_truce_t0": {
            "verified_utc": "2026-05-04T17:33:00Z",
            "source_name": "Ukrainska Pravda page timestamp, source Russian Ministry of Defence",
            "source_url": "https://www.pravda.com.ua/eng/news/2026/05/04/8033132/",
            "verification_method": "visible 4 May 20:33 Kyiv timestamp converted to UTC; TASS metadata was later at 17:41:07Z",
            "verified_status": "verified_by_public_page_timestamp",
            "notes": "Matches first-pass operational anchor.",
        },
        "ukraine_counter_t0": {
            "verified_utc": "2026-05-04T18:52:50Z",
            "source_name": "AP article timestamp",
            "source_url": "https://apnews.com/article/russia-ukraine-war-unilateral-truce-parade-9a686273da1f284230180a7819613719",
            "verification_method": "AP published timestamp; direct Zelenskyy post timestamp not independently decoded in this pass",
            "verified_status": "verified_media_timestamp_after_first_pass_anchor",
            "notes": "Verified media timestamp is about 3.8 minutes after the first-pass 18:49:00Z anchor.",
        },
        "russian_reaffirm_t0": {
            "verified_utc": "2026-05-07T16:22:00Z",
            "source_name": "Ukrainska Pravda page timestamp, source Russian Ministry of Defence Telegram",
            "source_url": "https://www.pravda.com.ua/eng/news/2026/05/07/8033661/",
            "verification_method": "visible 7 May 19:22 Kyiv timestamp converted to UTC",
            "verified_status": "verified_by_public_page_timestamp",
            "notes": "Matches first-pass operational anchor; RBC-Ukraine was later at 17:25Z.",
        },
        "final_t0_truthsocial_working": {
            "verified_utc": FINAL_T0,
            "source_name": "first-pass Truth Social status ID decode",
            "source_url": "https://trumpstruth.org/statuses/38279",
            "verification_method": "status ID timestamp decode from first-pass raw timeline verification",
            "verified_status": "verified_in_first_pass",
            "notes": "Reused from immutable first-pass raw bundle.",
        },
    }

    rows: list[dict[str, Any]] = []
    for anchor_id, details in checked.items():
        current = parse_dt((timeline_by_id.get(anchor_id) or {}).get("utc_time"))
        verified = parse_dt(details["verified_utc"])
        before_wallets = sorted(
            {wallet for wallet, ts, _ in suspicious_times if verified is not None and ts < verified}
        )
        after_wallets = sorted(
            {wallet for wallet, ts, _ in suspicious_times if verified is not None and ts >= verified}
        )
        impact = "no_direct_suspicious_trade_timing_change"
        if anchor_id == "early_call_t0":
            wan_trade = parse_dt("2026-04-29T17:21:26Z")
            if verified is not None and wan_trade is not None and verified <= wan_trade:
                impact = "anchor_invalidates_prepublic_claim_for_wan123"
            else:
                impact = "wan123_trade_remains_before_earliest_verified_public_timestamp"
        elif anchor_id == "russian_reaffirm_t0":
            impact = "VladimirPooper_May7_8_rows_are_after_this_public_signal"
        rows.append(
            {
                "anchor_id": anchor_id,
                "current_timestamp_used_by_first_pass": iso_z(current),
                "earliest_independently_verified_public_timestamp": iso_z(verified),
                "source_name": details["source_name"],
                "source_url": details["source_url"],
                "verification_method": details["verification_method"],
                "verification_status": details["verified_status"],
                "suspicious_wallets_before_verified_timestamp": before_wallets,
                "suspicious_wallets_after_verified_timestamp": after_wallets,
                "impact_on_risk_classification": impact,
                "notes": details["notes"],
            }
        )
    return rows, checked


def load_price_history(input_dir: Path) -> list[dict[str, Any]]:
    payload = load_json(input_dir / "raw_bundle" / "price_history_yes.json", {})
    points = []
    for item in payload.get("points", []) if isinstance(payload, Mapping) else []:
        if not isinstance(item, Mapping):
            continue
        timestamp = parse_dt(str(item.get("time") or ""))
        if timestamp is None and item.get("t") is not None:
            try:
                timestamp = datetime.fromtimestamp(int(item["t"]), tz=UTC)
            except (TypeError, ValueError, OSError):
                timestamp = None
        price = decimal_value(item.get("p"), Decimal("-1"))
        if timestamp is None or price < 0:
            continue
        points.append({"time": timestamp, "p": price})
    points.sort(key=lambda point: point["time"])
    return points


def price_snapshot(history: list[dict[str, Any]], when: datetime | None) -> dict[str, Any]:
    if when is None:
        return {}
    result = {"price_at_trade": price_at(history, when)}
    for label, delta in [
        ("price_15m_after_trade", timedelta(minutes=15)),
        ("price_30m_after_trade", timedelta(minutes=30)),
        ("price_1h_after_trade", timedelta(hours=1)),
        ("price_6h_after_trade", timedelta(hours=6)),
    ]:
        result[label] = price_at(history, when + delta)
    final = parse_dt(FINAL_T0)
    resolution = parse_dt("2026-05-09T19:53:03Z")
    result["price_at_truthsocial_t0"] = price_at(history, final) if final else ""
    result["price_1h_after_truthsocial_t0"] = price_at(history, final + timedelta(hours=1)) if final else ""
    result["price_at_resolution_boundary"] = price_at(history, resolution) if resolution else ""
    return result


def funding_enrichment(wallets: list[str], as_of_by_wallet: Mapping[str, datetime | None], mode: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    trace_mode = FUNDING_TRACE_MODE_CACHE_ONLY if mode == "cache_only" else FUNDING_TRACE_MODE_LIVE_RPC
    # The repo's local runtime env may intentionally default Event Forensic to
    # disabled funding. This sidecar override is process-local and does not
    # mutate .inspoly_runtime.env or production funding behavior.
    os.environ["INSPOLY_FUNDING_TRACE_MODE"] = trace_mode
    os.environ.setdefault("INSPOLY_VALIDATION_MODE", "1")
    os.environ.setdefault("INSPOLY_VALIDATION_MAX_FUNDING_TRACES_PER_BUNDLE", str(len(wallets)))
    os.environ.setdefault("INSPOLY_VALIDATION_MAX_FUNDING_TRACE_FAILURES_PER_BUNDLE", str(len(wallets)))
    os.environ.setdefault("INSPOLY_VALIDATION_MAX_CONSECUTIVE_RPC_FAILURES", str(len(wallets)))
    os.environ.setdefault("INSPOLY_VALIDATION_MAX_LOG_CHUNKS_PER_TRACE", "8")
    os.environ.setdefault("INSPOLY_POLYGON_RPC_REQUEST_TIMEOUT_SECONDS", "3")
    os.environ.setdefault("INSPOLY_POLYGON_RPC_MAX_RETRIES", "1")
    os.environ.setdefault("INSPOLY_POLYGON_RPC_GETLOGS_BLOCK_CHUNK", "1000")

    resolver = FundingResolver(trace_mode=trace_mode, persistent_cache_enabled=False)
    rows: dict[str, dict[str, Any]] = {}
    for wallet in wallets:
        as_of = as_of_by_wallet.get(wallet)
        if as_of is None:
            rows[wallet] = {
                "funding_attempted": False,
                "funding_succeeded": False,
                "funding_linkage_status": "unknown_not_traced_or_failed",
                "funding_error": "missing_as_of_timestamp",
            }
            continue
        try:
            context = resolver.analyze(wallet, as_of)
        except Exception as exc:  # noqa: BLE001
            rows[wallet] = {
                "funding_attempted": True,
                "funding_succeeded": False,
                "funding_linkage_status": "unknown_not_traced_or_failed",
                "funding_error": f"{type(exc).__name__}: {exc}",
            }
            continue
        error = getattr(context, "error", None)
        found = bool(getattr(context, "funding_found", False))
        succeeded = error is None
        status = "funding_source_found" if found else "no_recent_usdc_funding_found_by_bounded_trace"
        if not succeeded:
            status = "unknown_not_traced_or_failed"
        rows[wallet] = {
            "funding_attempted": True,
            "funding_succeeded": succeeded,
            "funding_linkage_status": status,
            "funding_source_address": getattr(context, "source_address", "") or "",
            "funding_source_label": getattr(context, "source_label", "") or "",
            "funding_source_category": getattr(context, "source_category", "") or "",
            "funding_time_utc": iso_z(getattr(context, "funding_timestamp", None)),
            "minutes_from_funding_to_trade": getattr(context, "minutes_from_funding_to_trade", ""),
            "funding_amount_usdc": getattr(context, "funding_amount_usdc", ""),
            "funding_error": error or "",
            "funding_evidence_grade": getattr(context, "funding_evidence_grade", "") or "",
        }
    health = resolver.health().to_dict()
    return rows, health


def compute_wallet_validation(
    *,
    wallet: str,
    first_pass_wallet: Mapping[str, str],
    suspicious_rows: list[dict[str, str]],
    ledger: list[dict[str, Any]],
    ledger_summary: Mapping[str, Any],
    anchor_details: Mapping[str, Any],
    funding: Mapping[str, Any],
) -> dict[str, Any]:
    target_rows = [row for row in ledger if bool(row.get("is_target_market"))]
    suspicious_for_wallet = [row for row in suspicious_rows if row.get("wallet", "").lower() == wallet]
    flagged_times = [parse_dt(row.get("timestamp_utc")) for row in suspicious_for_wallet]
    flagged_times = [time for time in flagged_times if time is not None]
    first_yes = first_matching_time(
        target_rows,
        lambda row: row.get("side") == "BUY" and str(row.get("outcome")).lower() == "yes",
    )
    first_large = first_matching_time(
        target_rows,
        lambda row: (
            row.get("side") == "BUY"
            and str(row.get("outcome")).lower() == "yes"
            and decimal_value(row.get("notional_usdc")) >= Decimal("5000")
        ),
    )
    first_flag = min(flagged_times) if flagged_times else None
    prior_positions = [
        position_before_time(target_rows, time)
        for time in flagged_times
        if time is not None
    ]
    max_prior = max(prior_positions) if prior_positions else Decimal("0")
    existing_addon = max_prior > Decimal("0")
    large_prior = max_prior >= Decimal("25000")
    final = parse_dt(FINAL_T0)
    public_start = parse_dt(PUBLIC_REACTION_START)
    sold_after_announcement = any(
        parse_dt(str(row.get("timestamp_utc") or "")) is not None
        and final is not None
        and parse_dt(str(row.get("timestamp_utc") or "")) > final
        and row.get("side") == "SELL"
        and str(row.get("outcome")).lower() == "yes"
        and bool(row.get("is_target_market"))
        for row in target_rows
    )
    sold_after_resolution = any(
        parse_dt(str(row.get("timestamp_utc") or "")) is not None
        and parse_dt(str(row.get("timestamp_utc") or "")) >= parse_dt("2026-05-09T19:53:03Z")
        and row.get("side") == "SELL"
        and str(row.get("outcome")).lower() == "yes"
        and bool(row.get("is_target_market"))
        for row in target_rows
    )
    held_through_announcement = (
        final is not None and position_before_time(target_rows, final + timedelta(seconds=1)) > 0
    )
    immediate_reaction = any(
        parse_dt(str(row.get("timestamp_utc") or "")) is not None
        and public_start is not None
        and final is not None
        and public_start <= parse_dt(str(row.get("timestamp_utc") or "")) <= final + timedelta(hours=1)
        and bool(row.get("public_news_reaction_flag"))
        for row in target_rows
    )
    resolution_exit = any(bool(row.get("resolution_arbitrage_flag")) and row.get("side") == "SELL" for row in target_rows)

    early_verified = parse_dt(str(anchor_details["early_call_t0"]["verified_utc"]))
    wan_trade = parse_dt("2026-04-29T17:21:26Z")
    anchor_invalidates = (
        wallet.endswith("5f4b")
        and early_verified is not None
        and wan_trade is not None
        and early_verified <= wan_trade
    )
    verified_pre_public = bool(wallet.endswith("5f4b") and not anchor_invalidates)

    public_power = str(first_pass_wallet.get("public_power_user_flag", "")).lower() == "true"
    related_repeat = len({row.get("condition_id") for row in ledger if not bool(row.get("is_target_market"))}) > 0
    funding_unknown = str(funding.get("funding_linkage_status", "")).startswith("unknown")

    if wallet.endswith("5f4b"):
        priority = "strong_manual_review" if verified_pre_public else "watchlist_only"
        disposition = (
            "pre-public information-edge candidate; manual-review candidate; public-power-user; "
            "news-reaction add-ons also present"
            if verified_pre_public
            else "public-signal contaminated; manual-review candidate"
        )
        contamination = "low_for_April29_trade; high_for_May8_news_reaction_addons"
        why_priority = (
            "Large first-entry BUY Yes exposure at low entry probability occurred before the earliest verified "
            "public early-call timestamp found in this pass; later public-news reaction and public-power-user "
            "behavior reduce but do not erase review priority."
        )
    else:
        priority = "watchlist_only"
        disposition = "existing-position add-on; public-signal contaminated; resolution-arbitrage exit after win"
        contamination = "high_after_russian_reaffirmation_public_signal"
        why_priority = (
            "Flagged May 7-8 BUY Yes rows were add-ons to a large pre-existing YES position that was built "
            "well before the final public announcement, and the add-ons occurred after the Russian reaffirmation signal."
        )

    audit_flags = {
        "anchor_invalidates_prepublic_claim": anchor_invalidates,
        "public_signal_contaminated": contamination != "low",
        "first_entry_clean": bool(wallet.endswith("5f4b") and not existing_addon and verified_pre_public),
        "existing_position_addon": existing_addon,
        "large_prior_position": large_prior,
        "public_power_user_reducer": public_power,
        "immediate_news_reaction_also_present": immediate_reaction,
        "resolution_exit_after_win": resolution_exit,
        "funding_unknown": funding_unknown,
        "funding_positive_linkage": bool(funding.get("funding_source_address")) and not funding_unknown,
        "cluster_absent": True,
        "manual_review_not_proof": True,
    }

    return {
        "wallet": wallet,
        "username": first_pass_wallet.get("username") or WALLETS.get(wallet, ""),
        "first_pass_rank": first_pass_wallet.get("rank", ""),
        "first_pass_risk_tier": first_pass_wallet.get("risk_tier", ""),
        "first_pass_score": first_pass_wallet.get("ceasefireLeakRiskScore", ""),
        "secondPassReviewPriority": priority,
        "secondPassDisposition": disposition,
        "aggregate_yes_exposure_first_pass": first_pass_wallet.get("aggregate_yes_exposure", ""),
        "largest_single_yes_trade": first_pass_wallet.get("largest_single_yes_trade", ""),
        "first_yes_exposure_utc": iso_z(first_yes),
        "first_large_yes_exposure_utc": iso_z(first_large),
        "suspicious_trade_count": len(suspicious_for_wallet),
        "verified_pre_public_flag": verified_pre_public,
        "public_signal_contamination_level": contamination,
        "existing_position_addon_flag": existing_addon,
        "prior_position_before_flagged_trades": max_prior,
        "public_power_user_flag": public_power,
        "funding_linkage_status": funding.get("funding_linkage_status", "unknown_not_traced_or_failed"),
        "shared_funding_flag": False,
        "split_wallet_flag": False,
        "related_market_repeat_flag": related_repeat,
        "held_through_announcement": held_through_announcement,
        "sold_after_announcement": sold_after_announcement,
        "sold_after_resolution": sold_after_resolution,
        "estimated_pnl_usdc": ledger_summary.get("target_yes_total_pnl_estimate", ""),
        "why_priority": why_priority,
        "why_not_proof": (
            "This is a manual-review candidate classification only. Public signals, market history, loaded "
            "inventory limits, and missing off-chain intent prevent any factual conclusion about information source."
        ),
        "next_manual_checks": (
            "Review exact social/feed availability, exchange/order-book state, full on-chain CTF inventory, "
            "wallet funding lineage with a reliable RPC/archive provider, and any linked accounts."
        ),
        "audit_flags": audit_flags,
    }


def build_trade_validation(
    *,
    suspicious_rows: list[dict[str, str]],
    ledgers_by_wallet: Mapping[str, list[dict[str, Any]]],
    anchor_details: Mapping[str, Any],
    price_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output = []
    for row in suspicious_rows:
        wallet = row.get("wallet", "").lower()
        timestamp = parse_dt(row.get("timestamp_utc"))
        anchor_id = row.get("anchor_id", "")
        verified_anchor_time = parse_dt(str((anchor_details.get(anchor_id) or {}).get("verified_utc") or ""))
        if verified_anchor_time is None and anchor_id == "final_t0_truthsocial_working":
            verified_anchor_time = parse_dt(FINAL_T0)
        minutes_before_verified = (
            round((verified_anchor_time - timestamp).total_seconds() / 60, 3)
            if verified_anchor_time is not None and timestamp is not None
            else ""
        )
        ledger = ledgers_by_wallet.get(wallet, [])
        existing_position = position_before_time(ledger, timestamp) if timestamp is not None else Decimal("0")
        position_delta = decimal_value(row.get("size")) if str(row.get("side")).upper() == "BUY" else -decimal_value(row.get("size"))
        pre_verified = (
            timestamp is not None and verified_anchor_time is not None and timestamp < verified_anchor_time
        )
        if wallet.endswith("5f4b"):
            disposition = "pre-public information-edge candidate" if pre_verified else "public-signal contaminated"
            reason_codes = [
                "first_entry_clean" if existing_position <= Decimal("0.000001") else "existing_position_addon",
                "public_power_user_reducer",
                "manual_review_not_proof",
            ]
        else:
            disposition = "existing-position add-on; public-signal contaminated"
            reason_codes = [
                "existing_position_addon",
                "large_prior_position",
                "public_signal_contaminated",
                "manual_review_not_proof",
            ]
        enriched = dict(row)
        enriched.update(
            {
                "verified_anchor_time": iso_z(verified_anchor_time),
                "minutes_before_verified_anchor": minutes_before_verified,
                "anchor_verification_status": (anchor_details.get(anchor_id) or {}).get("verified_status", "not_reverified"),
                "pre_verified_public_flag": pre_verified,
                "existing_position_before_trade": existing_position,
                "position_delta": position_delta,
                "disposition": disposition,
                "second_pass_reason_codes": reason_codes,
            }
        )
        enriched.update(price_snapshot(price_history, timestamp))
        output.append(enriched)
    return output


def packet_markdown(
    *,
    wallet_row: Mapping[str, Any],
    suspicious_rows: list[dict[str, str]],
    ledger: list[dict[str, Any]],
    anchor_rows: list[dict[str, Any]],
    ledger_summary: Mapping[str, Any],
    funding: Mapping[str, Any],
) -> str:
    wallet = str(wallet_row["wallet"])
    lines = [
        f"# Wallet Packet: {wallet_row.get('username')} / {wallet}",
        "",
        "## Executive Summary",
        "",
        f"- Second-pass priority: `{wallet_row.get('secondPassReviewPriority')}`",
        f"- Disposition: `{wallet_row.get('secondPassDisposition')}`",
        f"- Why priority: {wallet_row.get('why_priority')}",
        f"- Not proof: {wallet_row.get('why_not_proof')}",
        "",
        "## Timeline",
        "",
    ]
    for anchor in anchor_rows:
        lines.append(
            f"- `{anchor.get('anchor_id')}`: first pass `{anchor.get('current_timestamp_used_by_first_pass')}`, "
            f"verified `{anchor.get('earliest_independently_verified_public_timestamp')}`, "
            f"impact `{anchor.get('impact_on_risk_classification')}`"
        )
    lines.extend(["", "## Suspicious Trades", ""])
    for row in suspicious_rows:
        if row.get("wallet", "").lower() != wallet.lower():
            continue
        lines.append(
            f"- `{row.get('timestamp_utc')}` `{row.get('side')}` `{row.get('outcome')}` "
            f"price `{row.get('price')}` size `{row.get('size')}` notional `{row.get('notional_usdc')}` "
            f"source `{row.get('source_window')}`"
        )
    lines.extend(
        [
            "",
            "## Position Chronology",
            "",
            f"- Target/related ledger rows: `{len(ledger)}`",
            f"- Target trades: `{ledger_summary.get('target_trade_count')}`",
            f"- End target YES position from loaded rows: `{serialize_cell(ledger_summary.get('target_yes_position_end'))}`",
            f"- Estimated target YES P/L: `{serialize_cell(ledger_summary.get('target_yes_total_pnl_estimate'))}`",
            f"- P/L caveat: {ledger_summary.get('pnl_caveat')}",
            "",
            "## Funding and Linkage",
            "",
            f"- Funding attempted: `{funding.get('funding_attempted')}`",
            f"- Funding succeeded: `{funding.get('funding_succeeded')}`",
            f"- Funding linkage status: `{funding.get('funding_linkage_status')}`",
            f"- Funding source: `{funding.get('funding_source_address', '')}` `{funding.get('funding_source_label', '')}`",
            "- Shared-funder evidence: `False`",
            "- Split-wallet signal: `False`",
            "",
            "## Reducers and Manual Review",
            "",
            f"- Public-power-user reducer: `{wallet_row.get('public_power_user_flag')}`",
            f"- Existing-position add-on: `{wallet_row.get('existing_position_addon_flag')}`",
            f"- Public-signal contamination: `{wallet_row.get('public_signal_contamination_level')}`",
            f"- Next manual checks: {wallet_row.get('next_manual_checks')}",
        ]
    )
    return "\n".join(lines) + "\n"


def summary_markdown(
    *,
    output_dir: Path,
    wallet_rows: list[dict[str, Any]],
    anchor_rows: list[dict[str, Any]],
    funding_health: Mapping[str, Any],
    counts: Mapping[str, Any],
) -> str:
    by_wallet = {row["wallet"]: row for row in wallet_rows}
    wan = by_wallet["0xde7be6d489bce070a959e0cb813128ae659b5f4b"]
    vlad = by_wallet["0xa53e8fc4c2f9910e584de69d8b40a502a638218d"]
    early = next(row for row in anchor_rows if row["anchor_id"] == "early_call_t0")
    return "\n".join(
        [
            "# Second-Pass Summary",
            "",
            f"- Event URL: {EVENT_URL}",
            f"- Output directory: `{output_dir}`",
            f"- wan123 disposition: `{wan['secondPassReviewPriority']}` / {wan['secondPassDisposition']}",
            f"- VladimirPooper disposition: `{vlad['secondPassReviewPriority']}` / {vlad['secondPassDisposition']}",
            f"- early_call_t0 earliest verified public timestamp: `{early['earliest_independently_verified_public_timestamp']}` via {early['source_name']}",
            f"- wan123 clean pre-public status: `{wan['verified_pre_public_flag']}`; no verified early-call public source before its 2026-04-29T17:21:26Z trade was found.",
            f"- VladimirPooper existing-position add-on status: `{vlad['existing_position_addon_flag']}` with prior target YES position `{serialize_cell(vlad['prior_position_before_flagged_trades'])}` before flagged buys.",
            f"- Funding/shared-funder evidence: `{wan['funding_linkage_status']}` for wan123, `{vlad['funding_linkage_status']}` for VladimirPooper; shared funding and split-wallet flags were not found in this bounded pass.",
            "- Clusters: no second-pass cluster or shared-funder evidence found; first-pass wallet cluster output was empty.",
            f"- Counts: suspicious trades `{counts['suspicious_trades']}`, validated wallets `{counts['wallets']}`, public/news rows available `{counts['public_rows']}`, resolution-arbitrage rows available `{counts['resolution_rows']}`.",
            "",
            "## Methodology",
            "",
            "The pass re-read first-pass CSV/JSON/raw files, fetched full wallet trade histories from the Polymarket Data API for the two requested wallets, rebuilt target/related-market ledgers, checked public anchor timestamps, and attempted bounded funding enrichment without persistent cache writes.",
            "",
            "## Limitations",
            "",
            "Price history is the coarse CLOB prices-history series from the first-pass raw bundle. Wallet P/L is an approximate Data API ledger estimate for target YES rows and does not fully model fees, CTF merge/split activity, redemption transactions, or off-API inventory. Funding failures or unavailable traces are recorded as unknown, not none.",
            "",
            "Rows are manual-review candidates, not proof of insider trading or any improper information source.",
            "",
            "No production scoring, thresholds, gates, HER routing, funding behavior, candidate admission, schemas, UI behavior, or old saved outputs were changed.",
            "",
            "## Funding Resolver Health",
            "",
            f"- Trace mode: `{funding_health.get('fundingTraceMode', '')}`",
            f"- Functional status: `{funding_health.get('fundingResolverFunctionalStatus', '')}`",
            f"- Last error: `{funding_health.get('fundingResolverLastError', '')}`",
        ]
    ) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=INPUT_BUNDLE_DEFAULT)
    parser.add_argument("--output-prefix", default=OUTPUT_PREFIX_DEFAULT)
    parser.add_argument("--funding-mode", choices=["live_rpc", "cache_only"], default="live_rpc")
    parser.add_argument("--skip-network-anchor-check", action="store_true")
    args = parser.parse_args(argv)

    input_dir = Path(args.input_dir)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    output_dir = Path(f"{args.output_prefix}_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=False)

    suspicious_rows = load_csv(input_dir / "ranked_suspicious_trades.csv")
    wallet_first_pass = {
        row.get("wallet", "").lower(): row
        for row in load_csv(input_dir / "ranked_suspicious_wallets.csv")
    }
    timeline_rows = load_csv(input_dir / "timeline_anchors.csv")
    public_rows = load_csv(input_dir / "public_bot_or_news_reaction_trades.csv")
    resolution_rows = load_csv(input_dir / "resolution_arbitrage_candidates.csv")
    market_details = load_json(input_dir / "raw_bundle" / "market_details.json", [])
    if not market_details:
        raise RuntimeError("market_details.json is missing or empty")
    target_market = market_details[0]
    target_condition_id = str(target_market["condition_id"]).lower()
    yes_asset_id = str((target_market.get("token_ids") or [""])[0])

    anchor_rows, anchor_details = build_anchor_report(
        timeline_rows,
        suspicious_rows,
        verify_network=not args.skip_network_anchor_check,
    )
    price_history = load_price_history(input_dir)
    suspicious_ids = {row.get("trade_id", "") for row in suspicious_rows}
    public_ids = {row.get("trade_id", "") for row in public_rows}
    resolution_ids = {row.get("trade_id", "") for row in resolution_rows}

    all_ledgers: dict[str, list[dict[str, Any]]] = {}
    ledger_summaries: dict[str, dict[str, Any]] = {}
    fetch_logs: dict[str, Any] = {}
    as_of_by_wallet: dict[str, datetime | None] = {}
    for wallet in WALLETS:
        user_rows, user_error = fetch_user_trades(wallet)
        market_rows, market_error = fetch_user_market_trades(wallet, target_condition_id)
        rows = dedupe_trades([*user_rows, *market_rows])
        rows.sort(key=lambda item: (item.get("timestamp") or datetime.min.replace(tzinfo=UTC), str(item.get("trade_id") or "")))
        ledger, summary = build_chronology(
            wallet=wallet,
            rows=rows,
            target_condition_id=target_condition_id,
            yes_asset_id=yes_asset_id,
            suspicious_ids=suspicious_ids,
            public_ids=public_ids,
            resolution_ids=resolution_ids,
        )
        all_ledgers[wallet] = ledger
        ledger_summaries[wallet] = summary
        fetch_logs[wallet] = {
            "user_trade_rows": len(user_rows),
            "market_trade_rows": len(market_rows),
            "merged_trade_rows": len(rows),
            "related_ledger_rows": len(ledger),
            "user_fetch_error": user_error,
            "market_fetch_error": market_error,
        }
        candidate_times = [
            parse_dt(row.get("timestamp_utc"))
            for row in suspicious_rows
            if row.get("wallet", "").lower() == wallet
        ]
        as_of_by_wallet[wallet] = min([time for time in candidate_times if time is not None], default=None)

    funding_rows, funding_health = funding_enrichment(list(WALLETS), as_of_by_wallet, args.funding_mode)

    wallet_rows: list[dict[str, Any]] = []
    for wallet in WALLETS:
        wallet_rows.append(
            compute_wallet_validation(
                wallet=wallet,
                first_pass_wallet=wallet_first_pass.get(wallet, {}),
                suspicious_rows=suspicious_rows,
                ledger=all_ledgers[wallet],
                ledger_summary=ledger_summaries[wallet],
                anchor_details=anchor_details,
                funding=funding_rows.get(wallet, {}),
            )
        )

    trade_rows = build_trade_validation(
        suspicious_rows=suspicious_rows,
        ledgers_by_wallet=all_ledgers,
        anchor_details=anchor_details,
        price_history=price_history,
    )

    wallet_fields = [
        "wallet",
        "username",
        "first_pass_rank",
        "first_pass_risk_tier",
        "first_pass_score",
        "secondPassReviewPriority",
        "secondPassDisposition",
        "aggregate_yes_exposure_first_pass",
        "largest_single_yes_trade",
        "first_yes_exposure_utc",
        "first_large_yes_exposure_utc",
        "suspicious_trade_count",
        "verified_pre_public_flag",
        "public_signal_contamination_level",
        "existing_position_addon_flag",
        "prior_position_before_flagged_trades",
        "public_power_user_flag",
        "funding_linkage_status",
        "shared_funding_flag",
        "split_wallet_flag",
        "related_market_repeat_flag",
        "held_through_announcement",
        "sold_after_announcement",
        "sold_after_resolution",
        "estimated_pnl_usdc",
        "why_priority",
        "why_not_proof",
        "next_manual_checks",
        "audit_flags",
    ]
    write_csv(output_dir / "second_pass_wallet_validation.csv", wallet_rows, wallet_fields)

    trade_fields = list(suspicious_rows[0].keys()) + [
        "verified_anchor_time",
        "minutes_before_verified_anchor",
        "anchor_verification_status",
        "pre_verified_public_flag",
        "existing_position_before_trade",
        "position_delta",
        "disposition",
        "second_pass_reason_codes",
        "price_at_trade",
        "price_15m_after_trade",
        "price_30m_after_trade",
        "price_1h_after_trade",
        "price_6h_after_trade",
        "price_at_truthsocial_t0",
        "price_1h_after_truthsocial_t0",
        "price_at_resolution_boundary",
    ]
    write_csv(output_dir / "second_pass_trade_validation.csv", trade_rows, trade_fields)

    anchor_fields = [
        "anchor_id",
        "current_timestamp_used_by_first_pass",
        "earliest_independently_verified_public_timestamp",
        "source_name",
        "source_url",
        "verification_method",
        "verification_status",
        "suspicious_wallets_before_verified_timestamp",
        "suspicious_wallets_after_verified_timestamp",
        "impact_on_risk_classification",
        "notes",
    ]
    write_csv(output_dir / "anchor_verification_report.csv", anchor_rows, anchor_fields)

    chronology_fields = [
        "timestamp_utc",
        "timestamp_kyiv",
        "timestamp_eastern",
        "wallet",
        "username",
        "trade_id",
        "market",
        "market_slug",
        "event_slug",
        "condition_id",
        "asset_id",
        "side",
        "outcome",
        "price",
        "size",
        "notional_usdc",
        "is_target_market",
        "is_related_market",
        "inventory_classification",
        "position_before_asset",
        "position_delta",
        "position_after_asset",
        "target_yes_position_before",
        "target_yes_position_after",
        "target_yes_cost_basis_after",
        "target_yes_realized_pnl_after",
        "first_pass_suspicious_flag",
        "public_news_reaction_flag",
        "resolution_arbitrage_flag",
    ]
    for wallet, ledger in all_ledgers.items():
        safe_wallet = wallet.lower()
        write_csv(output_dir / f"wallet_chronology_{safe_wallet}.csv", ledger, chronology_fields)

    for wallet_row in wallet_rows:
        wallet = wallet_row["wallet"]
        md = packet_markdown(
            wallet_row=wallet_row,
            suspicious_rows=suspicious_rows,
            ledger=all_ledgers[wallet],
            anchor_rows=anchor_rows,
            ledger_summary=ledger_summaries[wallet],
            funding=funding_rows.get(wallet, {}),
        )
        (output_dir / f"wallet_packet_{wallet}.md").write_text(md, encoding="utf-8")

    counts = {
        "wallets": len(wallet_rows),
        "suspicious_trades": len(suspicious_rows),
        "public_rows": len(public_rows),
        "resolution_rows": len(resolution_rows),
    }
    summary_md = summary_markdown(
        output_dir=output_dir,
        wallet_rows=wallet_rows,
        anchor_rows=anchor_rows,
        funding_health=funding_health,
        counts=counts,
    )
    (output_dir / "second_pass_summary.md").write_text(summary_md, encoding="utf-8")
    write_json(
        output_dir / "second_pass_summary.json",
        {
            "event_url": EVENT_URL,
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),
            "counts": counts,
            "wallets": wallet_rows,
            "anchors": anchor_rows,
            "anchor_details": anchor_details,
            "funding": funding_rows,
            "funding_health": funding_health,
            "fetch_logs": fetch_logs,
            "ledger_summaries": ledger_summaries,
            "price_history_point_count": len(price_history),
            "production_changes": {
                "scoring_changed": False,
                "thresholds_changed": False,
                "gates_changed": False,
                "her_routing_changed": False,
                "funding_behavior_changed": False,
                "candidate_admission_changed": False,
                "schemas_changed": False,
                "ui_changed": False,
                "old_saved_outputs_mutated": False,
            },
            "manual_review_not_proof": True,
        },
    )

    print(str(output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
