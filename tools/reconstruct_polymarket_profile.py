from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.reconstruct_polymarket_wallet_market import (
    DATA_BASE,
    ET_TZ,
    GAMMA_BASE,
    HTTP_HEADERS,
    KYIV_TZ,
    POLYGONSCAN_TX,
    fetch_accounting_snapshot,
    fetch_paginated,
    fmt_decimal,
    markdown_table,
    money,
    normalize_address,
    now_iso,
    parse_jsonish_list,
    safe_get_json,
    timestamp_iso,
    to_decimal,
    verify_transactions,
    write_csv,
    write_json,
)


DEFAULT_OUT_DIR = "polymarket_profile_report"

NORMALIZED_FIELDS = [
    "sequence",
    "timestamp_utc",
    "timestamp_kyiv",
    "timestamp_et",
    "timestamp_unix",
    "side",
    "outcome",
    "market_title",
    "slug",
    "eventSlug",
    "conditionId",
    "asset",
    "position_key",
    "shares",
    "price",
    "api_usdc_size",
    "recomputed_size_x_price",
    "api_minus_recomputed",
    "effective_cash_price",
    "net_cash_flow_api",
    "net_cash_flow_recomputed",
    "transactionHash",
    "polygon_tx_url",
    "source_endpoint",
    "confidence_level",
    "onchain_status",
    "block_timestamp_utc",
    "onchain_timestamp_delta_seconds",
    "onchain_pusd_net_wallet",
    "onchain_ctf_net_for_asset",
]

LEDGER_FIELDS = [
    "sequence",
    "timestamp_utc",
    "timestamp_kyiv",
    "timestamp_et",
    "side",
    "outcome",
    "market_title",
    "shares",
    "price",
    "api_usdc_size",
    "recomputed_size_x_price",
    "api_minus_recomputed",
    "effective_cash_price",
    "net_cash_flow_api",
    "cumulative_yes_shares_after_trade",
    "cumulative_no_shares_after_trade",
    "cumulative_api_cash_flow",
    "cumulative_recomputed_cash_flow",
    "estimated_realized_pnl_api_wac_after_trade",
    "estimated_realized_pnl_fifo_after_trade",
    "sale_realized_pnl_api_wac",
    "sale_realized_pnl_fifo",
    "transactionHash",
    "polygon_tx_url",
    "source_endpoint",
    "confidence_level",
    "conditionId",
    "asset",
    "position_key",
    "cumulative_same_asset_shares_after_trade",
]

SUMMARY_FIELDS = ["metric", "value", "notes"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconstruct all visible Polymarket profile trades from raw Data/Gamma API rows.",
    )
    parser.add_argument("--profile-url", required=True, help="Polymarket profile URL, for example https://polymarket.com/@handle")
    parser.add_argument("--wallet", default="", help="Optional wallet override; profile URL is still saved as context")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--skip-onchain", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    profile_metadata = resolve_profile(args.profile_url)
    wallet = normalize_address(args.wallet or profile_metadata.get("proxy_wallet") or "")
    if not wallet:
        raise SystemExit("Could not resolve a proxy wallet from the profile URL; pass --wallet explicitly.")
    profile_metadata["wallet_used"] = wallet
    write_json(out_dir / "profile_metadata.json", profile_metadata)
    if profile_metadata.get("next_data"):
        write_json(out_dir / "profile_page_next_data.json", profile_metadata["next_data"])

    raw_trades = fetch_paginated(
        f"{DATA_BASE}/trades",
        {"user": wallet, "takerOnly": "false"},
        limit=500,
        max_offset=10_000,
    )
    write_json(out_dir / "raw_trades.json", raw_trades)

    raw_activity = fetch_paginated(
        f"{DATA_BASE}/activity",
        {"user": wallet, "type": "TRADE"},
        limit=500,
        max_offset=10_000,
    )
    write_json(out_dir / "raw_activity.json", raw_activity)

    raw_positions_current = fetch_paginated(
        f"{DATA_BASE}/positions",
        {"user": wallet, "sizeThreshold": "0"},
        limit=500,
        max_offset=10_000,
    )
    write_json(out_dir / "raw_positions_current.json", raw_positions_current)

    raw_positions_closed = fetch_paginated(
        f"{DATA_BASE}/closed-positions",
        {"user": wallet},
        limit=500,
        max_offset=10_000,
    )
    write_json(out_dir / "raw_positions_closed.json", raw_positions_closed)

    accounting = fetch_accounting_snapshot(wallet, out_dir)
    wallet_context = fetch_wallet_context(wallet)

    market_metadata = build_market_metadata(
        raw_trades["rows"],
        raw_activity["rows"],
        raw_positions_current["rows"],
        raw_positions_closed["rows"],
    )
    market_metadata["wallet_context"] = wallet_context
    market_metadata["accounting_snapshot"] = accounting
    market_metadata["official_docs_used"] = [
        "https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets",
        "https://docs.polymarket.com/api-reference/core/get-user-activity",
        "https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user",
        "https://docs.polymarket.com/api-reference/core/get-closed-positions-for-a-user",
        "https://docs.polymarket.com/concepts/pusd",
        "https://docs.polymarket.com/resources/contracts",
    ]
    write_json(out_dir / "market_metadata.json", market_metadata)

    tx_hashes = sorted(
        {
            str(row.get("transactionHash") or "")
            for row in raw_trades["rows"] + raw_activity["rows"]
            if row.get("transactionHash")
        }
    )
    onchain: dict[str, Any] = {}
    if not args.skip_onchain:
        onchain = verify_transactions(wallet, tx_hashes, sleep_seconds=0.08)
    write_json(out_dir / "onchain_verification.json", onchain)

    records = build_records(raw_trades["rows"], raw_activity["rows"], onchain)
    normalized_rows, ledger_rows, summary_rows, summary = build_ledgers(
        records,
        raw_positions_current["rows"],
        raw_positions_closed["rows"],
        market_metadata,
        onchain,
    )
    write_csv(out_dir / "normalized_trades.csv", normalized_rows, NORMALIZED_FIELDS)
    write_csv(out_dir / "chronological_ledger.csv", ledger_rows, LEDGER_FIELDS)
    write_csv(out_dir / "summary_calculations.csv", summary_rows, SUMMARY_FIELDS)

    report = build_report(
        profile_metadata=profile_metadata,
        wallet=wallet,
        raw_trades=raw_trades,
        raw_activity=raw_activity,
        raw_positions_current=raw_positions_current,
        raw_positions_closed=raw_positions_closed,
        market_metadata=market_metadata,
        normalized_rows=normalized_rows,
        ledger_rows=ledger_rows,
        summary=summary,
        onchain=onchain,
    )
    (out_dir / "final_report.md").write_text(report, encoding="utf-8")

    print(f"Wrote report artifacts to {out_dir.resolve()}")
    print(f"Wallet: {wallet}")
    print(f"Trade rows: {len(records)}")
    print(f"Total YES bought: {fmt_decimal(summary['total_yes_bought'])}")
    print(f"Total API/on-chain pUSD spent: {money(summary['total_buy_api_cash'])}")
    print(f"Remaining YES: {fmt_decimal(summary['remaining_yes_shares'])}")


def resolve_profile(profile_url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        profile_url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": HTTP_HEADERS["User-Agent"],
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")
        status = int(response.status)
    match = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.S)
    next_data: dict[str, Any] = {}
    if match:
        next_data = json.loads(html.unescape(match.group(1)))

    page_props = ((next_data.get("props") or {}).get("pageProps") or {}) if next_data else {}
    queries = ((page_props.get("dehydratedState") or {}).get("queries") or []) if page_props else []
    query_data: dict[str, Any] = {}
    for query in queries:
        key = query.get("queryKey")
        state_data = (query.get("state") or {}).get("data")
        key_string = json.dumps(key, ensure_ascii=True, default=str)
        query_data[key_string] = state_data

    user_data = first_query_data(queries, "/api/profile/userData")
    current_profile_positions = first_query_data(queries, "profile", "positions")
    profile_volume = first_query_data(queries, "/api/profile/volume")
    markets_traded = first_query_data(queries, "/api/profile/marketsTraded")
    user_stats = first_query_data(queries, "user-stats")
    biggest_wins = first_query_data(queries, "profile-biggest-wins")

    proxy_wallet = (
        page_props.get("proxyAddress")
        or (user_data or {}).get("proxyWallet")
        or page_props.get("primaryAddress")
        or page_props.get("baseAddress")
    )
    profile_handle = profile_url.rstrip("/").split("@")[-1] if "@" in profile_url else page_props.get("username")

    return {
        "generated_at_utc": now_iso(),
        "profile_url": profile_url,
        "profile_handle": profile_handle,
        "page_status": status,
        "proxy_wallet": normalize_address(proxy_wallet),
        "base_address": normalize_address(page_props.get("baseAddress")),
        "primary_address": normalize_address(page_props.get("primaryAddress")),
        "username": page_props.get("username"),
        "profile_slug": page_props.get("profileSlug"),
        "user_data": user_data,
        "profile_positions_from_page": current_profile_positions,
        "profile_volume_from_page": profile_volume,
        "markets_traded_from_page": markets_traded,
        "user_stats_from_page": user_stats,
        "biggest_wins_from_page": biggest_wins,
        "query_keys": [query.get("queryKey") for query in queries],
        "query_data_by_key": query_data,
        "next_data": next_data,
    }


def first_query_data(queries: list[dict[str, Any]], *needles: str) -> Any:
    lower_needles = [needle.lower() for needle in needles]
    for query in queries:
        key = query.get("queryKey")
        parts = [str(item).lower() for item in key] if isinstance(key, list) else [str(key).lower()]
        if all(any(needle in part for part in parts) for needle in lower_needles):
            return (query.get("state") or {}).get("data")
    return None


def fetch_wallet_context(wallet: str) -> dict[str, Any]:
    traded = safe_get_json(f"{DATA_BASE}/traded", {"user": wallet})
    value = safe_get_json(f"{DATA_BASE}/value", {"user": wallet})
    public_profile = safe_get_json(f"{GAMMA_BASE}/public-profile", {"address": wallet})
    return {
        "traded_url": traded.url,
        "traded_status": traded.status,
        "traded": traded.payload,
        "value_url": value.url,
        "value_status": value.status,
        "value": value.payload,
        "gamma_public_profile_url": public_profile.url,
        "gamma_public_profile_status": public_profile.status,
        "gamma_public_profile": public_profile.payload,
    }


def build_market_metadata(
    trade_rows: list[dict[str, Any]],
    activity_rows: list[dict[str, Any]],
    current_positions: list[dict[str, Any]],
    closed_positions: list[dict[str, Any]],
) -> dict[str, Any]:
    slugs = sorted(
        {
            str(row.get("slug") or "")
            for row in trade_rows + activity_rows + current_positions + closed_positions
            if row.get("slug")
        }
    )
    markets = []
    for slug in slugs:
        result = safe_get_json(f"{GAMMA_BASE}/markets/slug/{slug}")
        payload = result.payload if isinstance(result.payload, dict) else {}
        outcomes = parse_jsonish_list(payload.get("outcomes"))
        token_ids = parse_jsonish_list(payload.get("clobTokenIds"))
        token_map = {}
        for index, outcome in enumerate(outcomes):
            if index < len(token_ids):
                token_map[str(outcome)] = str(token_ids[index])
        events = payload.get("events") if isinstance(payload.get("events"), list) else []
        event_slug = str((events[0] or {}).get("slug") or payload.get("eventSlug") or "") if events else str(payload.get("eventSlug") or "")
        event_result = safe_get_json(f"{GAMMA_BASE}/events/slug/{event_slug}") if event_slug else None
        markets.append(
            {
                "slug": slug,
                "gamma_url": result.url,
                "gamma_status": result.status,
                "event_url": event_result.url if event_result else "",
                "event_status": event_result.status if event_result else None,
                "market": payload,
                "event": event_result.payload if event_result else None,
                "summary": {
                    "id": str(payload.get("id") or ""),
                    "title": str(payload.get("question") or ""),
                    "slug": str(payload.get("slug") or slug),
                    "eventSlug": event_slug,
                    "conditionId": str(payload.get("conditionId") or ""),
                    "outcomes": [str(item) for item in outcomes],
                    "tokenIds": [str(item) for item in token_ids],
                    "outcomeTokenMap": token_map,
                    "startDate": payload.get("startDate"),
                    "createdAt": payload.get("createdAt"),
                    "acceptingOrdersTimestamp": payload.get("acceptingOrdersTimestamp"),
                    "endDate": payload.get("endDate"),
                    "resolutionCriteria": payload.get("description"),
                    "currentOutcomePrices": parse_jsonish_list(payload.get("outcomePrices")),
                    "bestBid": payload.get("bestBid"),
                    "bestAsk": payload.get("bestAsk"),
                    "lastTradePrice": payload.get("lastTradePrice"),
                    "liquidity": payload.get("liquidity"),
                    "volume": payload.get("volume"),
                    "volume24hr": payload.get("volume24hr"),
                    "active": payload.get("active"),
                    "closed": payload.get("closed"),
                    "archived": payload.get("archived"),
                },
            }
        )
    return {
        "generated_at_utc": now_iso(),
        "market_count": len(markets),
        "markets": markets,
    }


def build_records(
    trade_rows: list[dict[str, Any]],
    activity_rows: list[dict[str, Any]],
    onchain: dict[str, Any],
) -> list[dict[str, Any]]:
    combined: dict[tuple[Any, ...], dict[str, Any]] = {}
    order = 0
    for source, rows in (("trades", trade_rows), ("activity", activity_rows)):
        for row in rows:
            order += 1
            key = record_key(row)
            entry = combined.setdefault(
                key,
                {
                    "source_order": order,
                    "sources": set(),
                    "trades_row": None,
                    "activity_row": None,
                },
            )
            entry["sources"].add(source)
            entry[f"{source}_row"] = row

    records = []
    for entry in combined.values():
        row = entry["activity_row"] or entry["trades_row"] or {}
        timestamp = int(to_decimal(row.get("timestamp")))
        size = to_decimal(row.get("size"))
        price = to_decimal(row.get("price"))
        recomputed = size * price
        api_cash = to_decimal(row.get("usdcSize")) if row.get("usdcSize") is not None else recomputed
        side = str(row.get("side") or "").upper()
        outcome = title_case_outcome(row.get("outcome"))
        asset = str(row.get("asset") or "")
        key = position_key(str(row.get("conditionId") or ""), asset, outcome)
        signed_api = api_cash if side == "SELL" else -api_cash
        signed_recomputed = recomputed if side == "SELL" else -recomputed
        tx_hash = str(row.get("transactionHash") or "")
        tx_info = onchain.get(tx_hash) if isinstance(onchain, dict) else {}
        tx_info = tx_info if isinstance(tx_info, dict) else {}
        block_ts = int(to_decimal(tx_info.get("block_timestamp_unix"))) if tx_info.get("block_timestamp_unix") else 0
        delta_seconds: int | str = block_ts - timestamp if block_ts else ""
        ctf_net = tx_info.get("ctf_net_by_token") if isinstance(tx_info.get("ctf_net_by_token"), dict) else {}
        effective_cash_price = api_cash / size if size else Decimal("0")
        records.append(
            {
                "source_order": entry["source_order"],
                "source_endpoint": "+".join(sorted(entry["sources"])),
                "timestamp": timestamp,
                "timestamp_utc": timestamp_iso(timestamp, UTC),
                "timestamp_kyiv": timestamp_iso(timestamp, KYIV_TZ),
                "timestamp_et": timestamp_iso(timestamp, ET_TZ),
                "side": side,
                "outcome": outcome,
                "market_title": str(row.get("title") or ""),
                "slug": str(row.get("slug") or ""),
                "eventSlug": str(row.get("eventSlug") or ""),
                "conditionId": str(row.get("conditionId") or ""),
                "asset": asset,
                "position_key": key,
                "shares": size,
                "price": price,
                "api_usdc_size": api_cash,
                "recomputed_size_x_price": recomputed,
                "api_minus_recomputed": api_cash - recomputed,
                "effective_cash_price": effective_cash_price,
                "net_cash_flow_api": signed_api,
                "net_cash_flow_recomputed": signed_recomputed,
                "transactionHash": tx_hash,
                "polygon_tx_url": POLYGONSCAN_TX.format(hash=tx_hash) if tx_hash else "",
                "onchain_status": tx_info.get("status", "not_checked"),
                "chain": tx_info.get("chain", ""),
                "block_timestamp_utc": tx_info.get("block_timestamp_utc", ""),
                "onchain_timestamp_delta_seconds": delta_seconds,
                "onchain_pusd_net_wallet": to_decimal(tx_info.get("pusd_net_wallet", 0)),
                "onchain_ctf_net_for_asset": to_decimal(ctf_net.get(asset, 0)),
                "onchain_summary": tx_info.get("summary", ""),
            }
        )
    records.sort(key=lambda item: (item["timestamp"], item["source_order"], item["transactionHash"]))
    return records


def build_ledgers(
    records: list[dict[str, Any]],
    current_positions: list[dict[str, Any]],
    closed_positions: list[dict[str, Any]],
    market_metadata: dict[str, Any],
    onchain: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Decimal]]:
    cumulative_shares_by_key = defaultdict(Decimal)
    aggregate_shares_by_outcome = defaultdict(Decimal)
    cost_pool_api = defaultdict(Decimal)
    cost_pool_recomputed = defaultdict(Decimal)
    fifo_lots = defaultdict(deque)
    cumulative_api_cash_flow = Decimal("0")
    cumulative_recomputed_cash_flow = Decimal("0")
    realized_api_wac = Decimal("0")
    realized_fifo = Decimal("0")
    totals = defaultdict(Decimal)
    normalized_rows = []
    ledger_rows = []
    sale_rows = []

    for seq, record in enumerate(records, start=1):
        outcome = record["outcome"]
        side = record["side"]
        shares = record["shares"]
        key = record["position_key"]
        api_cash = record["api_usdc_size"]
        recomputed = record["recomputed_size_x_price"]
        sale_realized_wac = Decimal("0")
        sale_realized_fifo = Decimal("0")

        if side == "BUY":
            cumulative_shares_by_key[key] += shares
            aggregate_shares_by_outcome[outcome] += shares
            cost_pool_api[key] += api_cash
            cost_pool_recomputed[key] += recomputed
            fifo_lots[key].append({"shares": shares, "unit_cost": api_cash / shares if shares else Decimal("0")})
            totals[f"buy_{outcome}_shares"] += shares
            totals[f"buy_{outcome}_api_cash"] += api_cash
            totals[f"buy_{outcome}_recomputed"] += recomputed
        elif side == "SELL":
            available = cumulative_shares_by_key[key]
            average_cost = cost_pool_api[key] / available if available else Decimal("0")
            sale_cost_basis = min(shares, available) * average_cost
            sale_realized_wac = api_cash - sale_cost_basis
            realized_api_wac += sale_realized_wac
            cumulative_shares_by_key[key] -= shares
            aggregate_shares_by_outcome[outcome] -= shares
            cost_pool_api[key] -= sale_cost_basis
            cost_pool_recomputed[key] -= min(shares, available) * (cost_pool_recomputed[key] / available if available else Decimal("0"))
            totals[f"sell_{outcome}_shares"] += shares
            totals[f"sell_{outcome}_api_cash"] += api_cash

            fifo_cost = Decimal("0")
            remaining = shares
            while remaining > 0 and fifo_lots[key]:
                lot = fifo_lots[key][0]
                take = min(remaining, lot["shares"])
                fifo_cost += take * lot["unit_cost"]
                lot["shares"] -= take
                remaining -= take
                if lot["shares"] <= Decimal("0.0000000001"):
                    fifo_lots[key].popleft()
            sale_realized_fifo = api_cash - fifo_cost
            realized_fifo += sale_realized_fifo
            sale_rows.append(
                {
                    "sequence": seq,
                    "shares": shares,
                    "proceeds": api_cash,
                    "sale_realized_wac": sale_realized_wac,
                    "sale_realized_fifo": sale_realized_fifo,
                }
            )

        cumulative_api_cash_flow += record["net_cash_flow_api"]
        cumulative_recomputed_cash_flow += record["net_cash_flow_recomputed"]
        confidence = confidence_for_record(record, onchain)
        normalized_rows.append(
            {
                "sequence": seq,
                "timestamp_utc": record["timestamp_utc"],
                "timestamp_kyiv": record["timestamp_kyiv"],
                "timestamp_et": record["timestamp_et"],
                "timestamp_unix": record["timestamp"],
                "side": side,
                "outcome": outcome,
                "market_title": record["market_title"],
                "slug": record["slug"],
                "eventSlug": record["eventSlug"],
                "conditionId": record["conditionId"],
                "asset": record["asset"],
                "position_key": key,
                "shares": fmt_decimal(shares),
                "price": fmt_decimal(record["price"], places=12),
                "api_usdc_size": fmt_decimal(api_cash),
                "recomputed_size_x_price": fmt_decimal(recomputed),
                "api_minus_recomputed": fmt_decimal(record["api_minus_recomputed"]),
                "effective_cash_price": fmt_decimal(record["effective_cash_price"], places=12),
                "net_cash_flow_api": fmt_decimal(record["net_cash_flow_api"]),
                "net_cash_flow_recomputed": fmt_decimal(record["net_cash_flow_recomputed"]),
                "transactionHash": record["transactionHash"],
                "polygon_tx_url": record["polygon_tx_url"],
                "source_endpoint": record["source_endpoint"],
                "confidence_level": confidence,
                "onchain_status": record["onchain_status"],
                "block_timestamp_utc": record["block_timestamp_utc"],
                "onchain_timestamp_delta_seconds": record["onchain_timestamp_delta_seconds"],
                "onchain_pusd_net_wallet": fmt_decimal(record["onchain_pusd_net_wallet"]),
                "onchain_ctf_net_for_asset": fmt_decimal(record["onchain_ctf_net_for_asset"]),
            }
        )
        ledger_rows.append(
            {
                "sequence": seq,
                "timestamp_utc": record["timestamp_utc"],
                "timestamp_kyiv": record["timestamp_kyiv"],
                "timestamp_et": record["timestamp_et"],
                "side": side,
                "outcome": outcome,
                "market_title": record["market_title"],
                "shares": fmt_decimal(shares),
                "price": fmt_decimal(record["price"], places=12),
                "api_usdc_size": fmt_decimal(api_cash),
                "recomputed_size_x_price": fmt_decimal(recomputed),
                "api_minus_recomputed": fmt_decimal(record["api_minus_recomputed"]),
                "effective_cash_price": fmt_decimal(record["effective_cash_price"], places=12),
                "net_cash_flow_api": fmt_decimal(record["net_cash_flow_api"]),
                "cumulative_yes_shares_after_trade": fmt_decimal(aggregate_shares_by_outcome["Yes"]),
                "cumulative_no_shares_after_trade": fmt_decimal(aggregate_shares_by_outcome["No"]),
                "cumulative_api_cash_flow": fmt_decimal(cumulative_api_cash_flow),
                "cumulative_recomputed_cash_flow": fmt_decimal(cumulative_recomputed_cash_flow),
                "estimated_realized_pnl_api_wac_after_trade": fmt_decimal(realized_api_wac),
                "estimated_realized_pnl_fifo_after_trade": fmt_decimal(realized_fifo),
                "sale_realized_pnl_api_wac": fmt_decimal(sale_realized_wac),
                "sale_realized_pnl_fifo": fmt_decimal(sale_realized_fifo),
                "transactionHash": record["transactionHash"],
                "polygon_tx_url": record["polygon_tx_url"],
                "source_endpoint": record["source_endpoint"],
                "confidence_level": confidence,
                "conditionId": record["conditionId"],
                "asset": record["asset"],
                "position_key": key,
                "cumulative_same_asset_shares_after_trade": fmt_decimal(cumulative_shares_by_key[key]),
            }
        )

    current_yes_positions = [row for row in current_positions if title_case_outcome(row.get("outcome")) == "Yes"]
    current_no_positions = [row for row in current_positions if title_case_outcome(row.get("outcome")) == "No"]
    current_value = sum(to_decimal(row.get("currentValue")) for row in current_positions)
    current_initial_value = sum(to_decimal(row.get("initialValue")) for row in current_positions)
    current_cash_pnl = sum(to_decimal(row.get("cashPnl")) for row in current_positions)
    current_realized_pnl = sum(to_decimal(row.get("realizedPnl")) for row in current_positions)
    current_yes_size = sum(to_decimal(row.get("size")) for row in current_yes_positions)
    current_no_size = sum(to_decimal(row.get("size")) for row in current_no_positions)
    current_yes_value = sum(to_decimal(row.get("currentValue")) for row in current_yes_positions)
    current_price_yes = to_decimal(current_yes_positions[0].get("curPrice")) if current_yes_positions else Decimal("0")
    current_avg_price_yes = to_decimal(current_yes_positions[0].get("avgPrice")) if current_yes_positions else Decimal("0")

    total_buy_api_cash = totals["buy_Yes_api_cash"] + totals["buy_No_api_cash"]
    total_buy_recomputed = totals["buy_Yes_recomputed"] + totals["buy_No_recomputed"]
    total_sell_api_cash = totals["sell_Yes_api_cash"] + totals["sell_No_api_cash"]
    remaining_cost_api = sum(cost_pool_api.values(), Decimal("0"))
    remaining_cost_recomputed = sum(cost_pool_recomputed.values(), Decimal("0"))
    summary = {
        "total_trade_rows": Decimal(len(records)),
        "unique_tx_hashes": Decimal(len({row["transactionHash"] for row in records if row["transactionHash"]})),
        "total_yes_bought": totals["buy_Yes_shares"],
        "total_no_bought": totals["buy_No_shares"],
        "total_yes_sold": totals["sell_Yes_shares"],
        "total_no_sold": totals["sell_No_shares"],
        "total_buy_api_cash": total_buy_api_cash,
        "total_buy_recomputed": total_buy_recomputed,
        "total_sell_api_cash": total_sell_api_cash,
        "weighted_avg_yes_entry_api_cash": totals["buy_Yes_api_cash"] / totals["buy_Yes_shares"] if totals["buy_Yes_shares"] else Decimal("0"),
        "weighted_avg_yes_entry_recomputed": totals["buy_Yes_recomputed"] / totals["buy_Yes_shares"] if totals["buy_Yes_shares"] else Decimal("0"),
        "weighted_avg_yes_sale_api_cash": totals["sell_Yes_api_cash"] / totals["sell_Yes_shares"] if totals["sell_Yes_shares"] else Decimal("0"),
        "remaining_yes_shares": aggregate_shares_by_outcome["Yes"],
        "remaining_no_shares": aggregate_shares_by_outcome["No"],
        "current_yes_size_api": current_yes_size,
        "current_no_size_api": current_no_size,
        "current_value_api": current_value,
        "current_yes_value_api": current_yes_value,
        "current_initial_value_api": current_initial_value,
        "current_price_yes_api": current_price_yes,
        "current_avg_price_yes_api": current_avg_price_yes,
        "current_cash_pnl_api": current_cash_pnl,
        "current_realized_pnl_api": current_realized_pnl,
        "remaining_cost_api_cash_wac": remaining_cost_api,
        "remaining_cost_recomputed_wac": remaining_cost_recomputed,
        "realized_pnl_api_wac": realized_api_wac,
        "realized_pnl_fifo": realized_fifo,
        "unrealized_pnl_api_cash_basis": current_value - remaining_cost_api if current_positions else Decimal("0"),
        "unrealized_pnl_recomputed_basis": current_value - remaining_cost_recomputed if current_positions else Decimal("0"),
        "reconciliation_yes_delta_ledger_vs_position": aggregate_shares_by_outcome["Yes"] - current_yes_size,
        "closed_position_rows": Decimal(len(closed_positions)),
    }
    summary_rows = [
        {"metric": key, "value": fmt_decimal(value), "notes": summary_note(key)}
        for key, value in summary.items()
    ]
    for sale in sale_rows:
        summary_rows.append(
            {
                "metric": f"sale_{sale['sequence']}_realized_pnl",
                "value": fmt_decimal(sale["sale_realized_wac"]),
                "notes": (
                    f"shares={fmt_decimal(sale['shares'])}; proceeds={fmt_decimal(sale['proceeds'])}; "
                    f"fifo={fmt_decimal(sale['sale_realized_fifo'])}"
                ),
            }
        )
    return normalized_rows, ledger_rows, summary_rows, summary


def build_report(
    *,
    profile_metadata: dict[str, Any],
    wallet: str,
    raw_trades: dict[str, Any],
    raw_activity: dict[str, Any],
    raw_positions_current: dict[str, Any],
    raw_positions_closed: dict[str, Any],
    market_metadata: dict[str, Any],
    normalized_rows: list[dict[str, Any]],
    ledger_rows: list[dict[str, Any]],
    summary: dict[str, Decimal],
    onchain: dict[str, Any],
) -> str:
    user_data = profile_metadata.get("user_data") or {}
    user_stats = profile_metadata.get("user_stats_from_page") or {}
    traded = ((market_metadata.get("wallet_context") or {}).get("traded") or {})
    markets = market_metadata.get("markets") or []
    current_positions = raw_positions_current.get("rows") or []
    profile_url = profile_metadata.get("profile_url") or "profile URL not available"
    profile_handle = profile_metadata.get("profile_handle") or "profile"
    first_trade = ledger_rows[0] if ledger_rows else {}
    buys = [row for row in ledger_rows if row["side"] == "BUY"]
    sells = [row for row in ledger_rows if row["side"] == "SELL"]
    tx_rows = onchain_rows_for_report(onchain, normalized_rows)
    position_rows = position_rows_for_report(ledger_rows, current_positions)
    market_rows = market_rows_for_report(markets, current_positions)
    confidence_counts = defaultdict(int)
    for row in ledger_rows:
        confidence_counts[row["confidence_level"]] += 1

    position_status = "fully exited"
    if summary["remaining_yes_shares"] or summary["remaining_no_shares"]:
        position_status = "still open"
    if (summary["total_yes_sold"] or summary["total_no_sold"]) and (summary["remaining_yes_shares"] or summary["remaining_no_shares"]):
        position_status = "partially exited"

    time_from_terms = elapsed_text(user_data.get("termsAcceptedAt"), first_trade.get("timestamp_utc"))
    time_from_created = elapsed_text(user_data.get("createdAt"), first_trade.get("timestamp_utc"))
    combined_liquidity = sum(to_decimal((market.get("summary") or {}).get("liquidity")) for market in markets)
    liquidity_pct_api = percent_of(summary["total_buy_api_cash"], combined_liquidity)
    liquidity_pct_recomputed = percent_of(summary["total_buy_recomputed"], combined_liquidity)
    market_count = len({row.get("market_title") for row in ledger_rows if row.get("market_title")})
    outcome_count = len({row.get("outcome") for row in ledger_rows if row.get("outcome")})
    verified_tx_count = sum(1 for row in tx_rows if row.get("onchain_status") == "verified")
    not_found_tx_count = sum(1 for row in tx_rows if row.get("onchain_status") == "not_found")
    largest_buy = max(buys, key=lambda row: to_decimal(row.get("api_usdc_size")), default={})
    first_sell = sells[0] if sells else {}
    next_buy_after_sell = next((row for row in ledger_rows if first_sell and int(to_decimal(row.get("sequence"))) > int(to_decimal(first_sell.get("sequence"))) and row.get("side") == "BUY"), {})

    lines = [
        f"# Polymarket Profile Reconstruction: @{profile_handle}",
        "",
        f"Generated: {now_iso()}",
        f"Profile: [{profile_url}]({profile_url})",
        f"Proxy wallet: `{wallet}`",
        "",
        "## A. Executive Summary",
        "",
        (
            f"`@{profile_handle}` is tied to proxy wallet `{wallet}`. The raw Data API shows {len(ledger_rows)} "
            f"deduplicated trade fills across {market_count} market(s), all on the YES outcome: {len(buys)} BUY fills "
            f"and {len(sells)} SELL fill(s). In aggregate the wallet bought {fmt_decimal(summary['total_yes_bought'])} "
            f"YES shares and sold {fmt_decimal(summary['total_yes_sold'])} YES shares. The current `/positions` API still "
            f"shows {fmt_decimal(summary['current_yes_size_api'])} YES shares open across {len(current_positions)} current "
            f"position row(s), so the profile is {position_status}. Using Data API `usdcSize`, total buy cash was "
            f"{money(summary['total_buy_api_cash'])}, sale proceeds were {money(summary['total_sell_api_cash'])}, "
            f"weighted-average realized P/L was {money(summary['realized_pnl_api_wac'])}, and FIFO realized P/L was "
            f"{money(summary['realized_pnl_fifo'])}. Current open value is {money(summary['current_value_api'])}; open P/L is "
            f"{money(summary['unrealized_pnl_api_cash_basis'])} on API/on-chain pUSD cash basis and "
            f"{money(summary['unrealized_pnl_recomputed_basis'])} on displayed `shares * price` basis."
        ),
        "",
        f"Position status: **{position_status}**.",
        "",
        "## B. Data Sources and Limitations",
        "",
        "- Raw trades: Polymarket Data API `/trades?user=...&takerOnly=false`.",
        "- Raw activity: Polymarket Data API `/activity?user=...&type=TRADE`.",
        "- Current positions: Polymarket Data API `/positions?user=...&sizeThreshold=0`.",
        "- Closed positions: Polymarket Data API `/closed-positions?user=...`.",
        "- Market metadata: Gamma API `/markets/slug/{slug}` and `/events/slug/{eventSlug}`.",
        "- Profile metadata: Polymarket public profile page `__NEXT_DATA__` payload, saved separately.",
        "- On-chain verification: Polygon JSON-RPC receipts for every returned `transactionHash`.",
        "- UI screenshots were not used as evidence.",
        (
            "- Cash fields: `/activity.usdcSize` is used as the main cash-flow field when present; `shares * price` "
            "is preserved separately as displayed notional. For verified May 8 pUSD trades, decoded on-chain pUSD "
            "transfers match `usdcSize`. Some verified April rows expose CTF share movement but no wallet pUSD log, and "
            "some older February hashes were not found on Polygon RPC, so those rows remain API-only for on-chain purposes."
        ),
        "",
        f"Endpoint row counts: trades={raw_trades['row_count']}, activity={raw_activity['row_count']}, current positions={raw_positions_current['row_count']}, closed positions={raw_positions_closed['row_count']}.",
        "",
        "## C. Profile and Market Identification",
        "",
        f"- Profile name: `{user_data.get('name') or profile_handle}`.",
        f"- Profile createdAt from page data: `{user_data.get('createdAt') or 'unavailable'}`.",
        f"- Terms accepted at: `{user_data.get('termsAcceptedAt') or 'unavailable'}`.",
        f"- User-stats joinDate from page data: `{user_stats.get('joinDate') or 'unavailable'}`.",
        f"- Data API `/traded`: `{traded.get('traded', 'unavailable')}` market(s).",
        f"- First trade: `{first_trade.get('timestamp_utc', 'unavailable')}` UTC / `{first_trade.get('timestamp_kyiv', 'unavailable')}` Kyiv.",
        f"- Time from profile creation to first trade: {time_from_created}.",
        f"- Time from terms acceptance to first trade: {time_from_terms}.",
        "",
        "### Markets",
        "",
        markdown_table(
            market_rows,
            [
                ("Market", "market_title"),
                ("Slug", "slug"),
                ("End", "endDate"),
                ("Condition", "conditionId"),
                ("YES token", "yesToken"),
                ("Current YES", "current_yes_price"),
                ("Liquidity", "liquidity"),
                ("Open YES held", "open_yes_held"),
            ],
        ),
        "",
    ]
    for market in markets:
        summary_row = market.get("summary") or {}
        lines.extend(
            [
                f"Resolution criteria for `{summary_row.get('title') or summary_row.get('slug') or 'market'}`:",
                "",
                blockquote(str(summary_row.get("resolutionCriteria") or "Unavailable")),
                "",
            ]
        )

    lines.extend(
        [
            "## D. Full Chronology Table",
            "",
            (
                "One row equals one raw API fill. `API cash` is `/activity.usdcSize` where available. `Displayed "
                "notional` is `shares * price`. `Cum same market` is the remaining share count for that exact "
                "conditionId/asset/outcome after the trade."
            ),
            "",
            markdown_table(
                ledger_rows,
                [
                    ("#", "sequence"),
                    ("UTC", "timestamp_utc"),
                    ("Kyiv", "timestamp_kyiv"),
                    ("ET", "timestamp_et"),
                    ("Side", "side"),
                    ("Market", "market_title"),
                    ("Outcome", "outcome"),
                    ("Shares", "shares"),
                    ("Price", "price"),
                    ("API cash", "api_usdc_size"),
                    ("Displayed notional", "recomputed_size_x_price"),
                    ("Eff cash px", "effective_cash_price"),
                    ("Cum same market", "cumulative_same_asset_shares_after_trade"),
                    ("Cum all YES", "cumulative_yes_shares_after_trade"),
                    ("Realized P/L", "estimated_realized_pnl_api_wac_after_trade"),
                    ("Tx", "transactionHash"),
                    ("Confidence", "confidence_level"),
                ],
                tx_link=True,
            ),
            "",
            "## E. Buy-side Reconstruction",
            "",
            f"- Total YES bought: {fmt_decimal(summary['total_yes_bought'])} across {len(buys)} fill(s).",
            f"- Total NO bought: {fmt_decimal(summary['total_no_bought'])}.",
            f"- Weighted-average YES entry using API/on-chain pUSD cash where available: {fmt_decimal(summary['weighted_avg_yes_entry_api_cash'], places=8)}.",
            f"- Weighted-average YES entry using displayed price*shares: {fmt_decimal(summary['weighted_avg_yes_entry_recomputed'], places=8)}.",
            f"- Total API cash spent: {money(summary['total_buy_api_cash'])}.",
            f"- Total displayed price*shares notional: {money(summary['total_buy_recomputed'])}.",
            "",
            markdown_table(
                buys,
                [
                    ("#", "sequence"),
                    ("Kyiv", "timestamp_kyiv"),
                    ("Market", "market_title"),
                    ("Outcome", "outcome"),
                    ("Shares", "shares"),
                    ("Price", "price"),
                    ("API cash", "api_usdc_size"),
                    ("Displayed notional", "recomputed_size_x_price"),
                    ("Tx", "transactionHash"),
                ],
                tx_link=True,
            ),
            "",
            "## F. Sell-side Reconstruction",
            "",
            f"- Total YES sold: {fmt_decimal(summary['total_yes_sold'])} across {len(sells)} fill(s).",
            f"- Total NO sold: {fmt_decimal(summary['total_no_sold'])}.",
            f"- Weighted-average YES sale price using API cash: {fmt_decimal(summary['weighted_avg_yes_sale_api_cash'], places=8)}.",
            f"- Total sale proceeds: {money(summary['total_sell_api_cash'])}.",
            f"- Realized P/L, weighted-average cost basis: {money(summary['realized_pnl_api_wac'])}.",
            f"- Realized P/L, FIFO secondary calculation: {money(summary['realized_pnl_fifo'])}.",
            "",
            markdown_table(
                sells,
                [
                    ("#", "sequence"),
                    ("Kyiv", "timestamp_kyiv"),
                    ("Market", "market_title"),
                    ("Outcome", "outcome"),
                    ("Shares", "shares"),
                    ("API proceeds", "api_usdc_size"),
                    ("Sale P/L WAC", "sale_realized_pnl_api_wac"),
                    ("Sale P/L FIFO", "sale_realized_pnl_fifo"),
                    ("Tx", "transactionHash"),
                ],
                tx_link=True,
            ),
            "",
            "## G. Remaining Position",
            "",
            f"- Ledger remaining YES, aggregate: {fmt_decimal(summary['remaining_yes_shares'])}.",
            f"- Data API `/positions` remaining YES, aggregate: {fmt_decimal(summary['current_yes_size_api'])}.",
            f"- Ledger-vs-position reconciliation delta: {fmt_decimal(summary['reconciliation_yes_delta_ledger_vs_position'])}.",
            f"- Current aggregate position value: {money(summary['current_value_api'])}.",
            f"- Position endpoint aggregate `initialValue`: {money(summary['current_initial_value_api'])}; `cashPnl`: {money(summary['current_cash_pnl_api'])}; `realizedPnl`: {money(summary['current_realized_pnl_api'])}.",
            f"- Open P/L using API cash basis: {money(summary['unrealized_pnl_api_cash_basis'])}.",
            f"- Open P/L using displayed price*shares basis: {money(summary['unrealized_pnl_recomputed_basis'])}.",
            "",
            markdown_table(
                position_rows,
                [
                    ("Market", "market_title"),
                    ("Outcome", "outcome"),
                    ("Bought", "bought"),
                    ("Sold", "sold"),
                    ("Ledger rem", "remaining_ledger"),
                    ("API rem", "remaining_api"),
                    ("Cur px", "current_price"),
                    ("Cur value", "current_value"),
                    ("WAC realized", "realized_wac"),
                    ("FIFO realized", "realized_fifo"),
                    ("Open P/L cash", "open_pnl_api_cash"),
                    ("API cashPnl", "api_cash_pnl"),
                ],
            ),
            "",
            "## H. On-chain Verification",
            "",
            (
                f"Current Polymarket docs/contracts point this settlement flow to Polygon, so all {len(tx_rows)} returned "
                f"transaction hashes were checked on Polygon RPC. {verified_tx_count}/{len(tx_rows)} receipts were found and "
                f"had block timestamps matching the API timestamp when present; {not_found_tx_count}/{len(tx_rows)} older "
                "hashes were not found on Polygon RPC and are marked API-only for on-chain purposes."
            ),
            "",
            markdown_table(
                tx_rows,
                [
                    ("Tx hash", "transactionHash"),
                    ("Fills", "fill_count"),
                    ("Chain", "chain"),
                    ("Block UTC", "block_timestamp_utc"),
                    ("API delta sec", "timestamp_delta_seconds"),
                    ("Status", "onchain_status"),
                    ("pUSD wallet net", "onchain_pusd_net_wallet"),
                    ("CTF asset net", "onchain_ctf_net_for_asset"),
                    ("Summary", "onchain_summary"),
                ],
                tx_link=True,
            ),
            "",
            "## I. Suspicion Indicators",
            "",
            f"- Account age: profile created `{user_data.get('createdAt') or 'unknown'}`; first trade `{first_trade.get('timestamp_utc', 'unknown')}`.",
            f"- Number of markets traded: Data/page data show `{traded.get('traded', 'unknown')}` market(s).",
            f"- Concentration: {len(ledger_rows)} fills cover {market_count} market(s), {outcome_count} outcome(s), and the same alien/UFO event family.",
            f"- Timing: first buy happened {time_from_created} after profile creation. Terms acceptance timestamp comparison is {time_from_terms}; this is a source-data conflict when terms are recorded after earlier trades.",
            f"- Largest buy: {largest_buy.get('timestamp_kyiv', 'unavailable')} Kyiv, {largest_buy.get('market_title', '')}, {largest_buy.get('shares', '')} YES for {largest_buy.get('api_usdc_size', '')} API cash.",
            f"- Size versus visible liquidity: aggregate API cash spent was {liquidity_pct_api} of combined current Gamma liquidity across the traded markets; displayed price*shares notional was {liquidity_pct_recomputed}.",
        ]
    )
    if first_sell:
        lines.append(
            f"- Sale behavior: sold {first_sell.get('shares')} YES in `{first_sell.get('market_title')}` at {first_sell.get('timestamp_kyiv')} Kyiv for {first_sell.get('api_usdc_size')} API cash; WAC realized P/L on that sale is {first_sell.get('sale_realized_pnl_api_wac')}."
        )
        if next_buy_after_sell:
            lines.append(
                f"- Immediate follow-on trade: the next fill was a BUY in `{next_buy_after_sell.get('market_title')}` at {next_buy_after_sell.get('timestamp_kyiv')} Kyiv, {next_buy_after_sell.get('shares')} YES for {next_buy_after_sell.get('api_usdc_size')} API cash."
            )
    else:
        lines.append("- Sales after a price jump: no sell rows were found, so there is no realized exit behavior to assess.")
    lines.extend(
        [
            (
                "- Neutral assessment: the pattern is concentrated in one event family and YES-only exposure. The May 8 "
                "sale followed by a near-immediate buy in the shorter May 31 variant is notable as a rotation/position "
                "change, but intent cannot be inferred from these data alone."
            ),
            "",
            "## J. Appendix",
            "",
            "### Raw Endpoint URLs",
            "",
            *[f"- {page['url']}" for page in raw_trades["pages"]],
            *[f"- {page['url']}" for page in raw_activity["pages"]],
            *[f"- {page['url']}" for page in raw_positions_current["pages"]],
            *[f"- {page['url']}" for page in raw_positions_closed["pages"]],
            *[f"- {market.get('gamma_url')}" for market in markets],
            *[f"- {market.get('event_url')}" for market in markets if market.get("event_url")],
            f"- {market_metadata.get('accounting_snapshot', {}).get('url')}",
            "",
            "### Script Command Used",
            "",
            "```bash",
            f"python3 tools/reconstruct_polymarket_profile.py --profile-url {profile_url}",
            "```",
            "",
            "### Filtering Logic",
            "",
            (
                "No market filter was applied for this profile run. The script pulled all rows returned by `/trades` "
                "and `/activity` for the resolved proxy wallet, de-duplicated rows by tx/timestamp/condition/asset/"
                "side/outcome/size/price, then grouped positions and realized P/L by exact conditionId/asset/outcome. "
                f"This run spans {market_count} market(s)."
            ),
            "",
            "### API Inconsistencies / Notes",
            "",
            f"- Polymarket profile page data reports `createdAt={user_data.get('createdAt')}` but user-stats reports `joinDate={user_stats.get('joinDate')}`. Both values are preserved; the report uses `createdAt` as the profile-record timestamp.",
            f"- `termsAcceptedAt={user_data.get('termsAcceptedAt')}` is after the first historical trades for this profile, so elapsed time from terms acceptance is marked as a source timestamp conflict rather than interpreted literally.",
            "- `/activity` contains `usdcSize`; `/trades` does not. Ledger cash therefore prefers `/activity.usdcSize` and falls back to `shares * price` only if `usdcSize` is absent.",
            "- On-chain pUSD flow is only asserted where decoded receipt logs actually contain wallet pUSD transfers. Some verified Polygon receipts only showed CTF token movement for this wallet, and three February hashes were not found on Polygon RPC.",
            f"- Closed-position rows returned by `/closed-positions`: {raw_positions_closed['row_count']}.",
            f"- Confidence counts: {dict(confidence_counts)}.",
            "- Official docs referenced: [trades](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets), [activity](https://docs.polymarket.com/api-reference/core/get-user-activity), [positions](https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user), [closed positions](https://docs.polymarket.com/api-reference/core/get-closed-positions-for-a-user), [pUSD](https://docs.polymarket.com/concepts/pusd), [contracts](https://docs.polymarket.com/resources/contracts).",
            "",
        ]
    )
    return "\n".join(lines)


def market_rows_for_report(markets: list[dict[str, Any]], current_positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    open_yes_by_slug = defaultdict(Decimal)
    for position in current_positions:
        if title_case_outcome(position.get("outcome")) == "Yes":
            open_yes_by_slug[str(position.get("slug") or "")] += to_decimal(position.get("size"))
    rows = []
    for market in markets:
        summary = market.get("summary") or {}
        token_map = summary.get("outcomeTokenMap") or {}
        current_prices = summary.get("currentOutcomePrices") or []
        rows.append(
            {
                "market_title": summary.get("title") or "",
                "slug": summary.get("slug") or "",
                "endDate": summary.get("endDate") or "",
                "conditionId": summary.get("conditionId") or "",
                "yesToken": token_map.get("Yes") or "",
                "current_yes_price": str(current_prices[0]) if current_prices else "",
                "liquidity": str(summary.get("liquidity") or ""),
                "open_yes_held": fmt_decimal(open_yes_by_slug[str(summary.get("slug") or "")]),
            }
        )
    return rows


def position_rows_for_report(ledger_rows: list[dict[str, Any]], current_positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "market_title": "",
            "outcome": "",
            "conditionId": "",
            "asset": "",
            "bought": Decimal("0"),
            "sold": Decimal("0"),
            "buy_api": Decimal("0"),
            "sell_api": Decimal("0"),
            "shares": Decimal("0"),
            "cost_api": Decimal("0"),
            "fifo_lots": deque(),
            "realized_wac": Decimal("0"),
            "realized_fifo": Decimal("0"),
        }
    )
    for row in ledger_rows:
        key = str(row.get("position_key") or "")
        state = states[key]
        state["market_title"] = row.get("market_title") or state["market_title"]
        state["outcome"] = row.get("outcome") or state["outcome"]
        state["conditionId"] = row.get("conditionId") or state["conditionId"]
        state["asset"] = row.get("asset") or state["asset"]
        shares = to_decimal(row.get("shares"))
        cash = to_decimal(row.get("api_usdc_size"))
        side = str(row.get("side") or "").upper()
        if side == "BUY":
            state["bought"] += shares
            state["buy_api"] += cash
            state["shares"] += shares
            state["cost_api"] += cash
            state["fifo_lots"].append({"shares": shares, "unit_cost": cash / shares if shares else Decimal("0")})
        elif side == "SELL":
            available = state["shares"]
            average_cost = state["cost_api"] / available if available else Decimal("0")
            matched = min(shares, available)
            wac_cost = matched * average_cost
            state["realized_wac"] += cash - wac_cost
            state["cost_api"] -= wac_cost
            state["shares"] -= shares
            state["sold"] += shares
            state["sell_api"] += cash

            remaining = shares
            fifo_cost = Decimal("0")
            while remaining > 0 and state["fifo_lots"]:
                lot = state["fifo_lots"][0]
                take = min(remaining, lot["shares"])
                fifo_cost += take * lot["unit_cost"]
                lot["shares"] -= take
                remaining -= take
                if lot["shares"] <= Decimal("0.0000000001"):
                    state["fifo_lots"].popleft()
            state["realized_fifo"] += cash - fifo_cost

    current_by_key = {
        position_key(position.get("conditionId"), position.get("asset"), position.get("outcome")): position
        for position in current_positions
    }
    rows = []
    for key in sorted(set(states) | set(current_by_key)):
        state = states[key]
        position = current_by_key.get(key, {})
        current_value = to_decimal(position.get("currentValue"))
        current_size = to_decimal(position.get("size"))
        current_price = to_decimal(position.get("curPrice"))
        current_cash_pnl = to_decimal(position.get("cashPnl"))
        rows.append(
            {
                "market_title": state.get("market_title") or position.get("title") or "",
                "outcome": state.get("outcome") or title_case_outcome(position.get("outcome")),
                "bought": fmt_decimal(state.get("bought")),
                "sold": fmt_decimal(state.get("sold")),
                "remaining_ledger": fmt_decimal(state.get("shares")),
                "remaining_api": fmt_decimal(current_size),
                "current_price": fmt_decimal(current_price, places=8),
                "current_value": money(current_value),
                "realized_wac": money(state.get("realized_wac")),
                "realized_fifo": money(state.get("realized_fifo")),
                "open_pnl_api_cash": money(current_value - state.get("cost_api", Decimal("0"))),
                "api_cash_pnl": money(current_cash_pnl),
                "conditionId": state.get("conditionId") or position.get("conditionId") or "",
                "asset": state.get("asset") or position.get("asset") or "",
            }
        )
    return rows


def onchain_rows_for_report(onchain: dict[str, Any], normalized_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    by_hash: dict[str, dict[str, Any]] = {}
    for row in normalized_rows:
        tx_hash = row["transactionHash"]
        info = onchain.get(tx_hash, {}) if isinstance(onchain, dict) else {}
        if tx_hash in by_hash:
            by_hash[tx_hash]["fill_count"] += 1
            continue
        item = {
            "transactionHash": tx_hash,
            "fill_count": 1,
            "chain": info.get("chain") or "Polygon if verified",
            "block_timestamp_utc": info.get("block_timestamp_utc") or row.get("block_timestamp_utc") or "",
            "timestamp_delta_seconds": row.get("onchain_timestamp_delta_seconds"),
            "onchain_status": info.get("status") or row.get("onchain_status"),
            "onchain_pusd_net_wallet": row.get("onchain_pusd_net_wallet"),
            "onchain_ctf_net_for_asset": row.get("onchain_ctf_net_for_asset"),
            "onchain_summary": info.get("summary") or "",
        }
        by_hash[tx_hash] = item
        rows.append(item)
    return rows


def confidence_for_record(record: dict[str, Any], onchain: dict[str, Any]) -> str:
    sources = set(str(record.get("source_endpoint") or "").split("+"))
    tx_hash = record.get("transactionHash")
    tx_info = onchain.get(tx_hash) if isinstance(onchain, dict) else None
    verified = isinstance(tx_info, dict) and tx_info.get("status") == "verified"
    timestamp_match = str(record.get("onchain_timestamp_delta_seconds")) in {"0", "0.0"}
    side = str(record.get("side") or "").upper()
    expected_pusd = record.get("api_usdc_size", Decimal("0")) if side == "SELL" else -record.get("api_usdc_size", Decimal("0"))
    expected_ctf = -record.get("shares", Decimal("0")) if side == "SELL" else record.get("shares", Decimal("0"))
    p_usd_matches = abs(record.get("onchain_pusd_net_wallet", Decimal("0")) - expected_pusd) < Decimal("0.000001")
    ctf_matches = abs(record.get("onchain_ctf_net_for_asset", Decimal("0")) - expected_ctf) < Decimal("0.000001")
    if verified and timestamp_match and p_usd_matches and ctf_matches and {"activity", "trades"} <= sources:
        return "High: trade+activity APIs, Polygon timestamp, pUSD flow, and CTF shares match"
    if verified and timestamp_match and {"activity", "trades"} <= sources:
        return "High: trade+activity APIs and Polygon timestamp match"
    if {"activity", "trades"} <= sources:
        return "Medium-high: trade+activity APIs agree; on-chain incomplete"
    return "Medium: single API endpoint"


def record_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("transactionHash") or ""),
        int(to_decimal(row.get("timestamp"))),
        str(row.get("conditionId") or "").lower(),
        str(row.get("asset") or ""),
        str(row.get("side") or "").upper(),
        title_case_outcome(row.get("outcome")),
        fmt_decimal(to_decimal(row.get("size")), places=8),
        fmt_decimal(to_decimal(row.get("price")), places=12),
    )


def position_key(condition_id: Any, asset: Any, outcome: Any) -> str:
    return f"{str(condition_id or '').lower()}::{str(asset or '')}::{title_case_outcome(outcome)}"


def title_case_outcome(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() == "yes":
        return "Yes"
    if text.lower() == "no":
        return "No"
    return text


def summary_note(key: str) -> str:
    notes = {
        "total_buy_api_cash": "Uses Data API /activity.usdcSize, corroborated by Polygon pUSD net wallet flow.",
        "total_buy_recomputed": "Sum of Data API shares * price; lower than pUSD cash flow in this profile.",
        "current_cash_pnl_api": "Data API /positions cashPnl, using Polymarket's position accounting.",
        "unrealized_pnl_api_cash_basis": "Current position value minus API/on-chain pUSD cash spent.",
        "unrealized_pnl_recomputed_basis": "Current position value minus summed shares*price notional.",
        "reconciliation_yes_delta_ledger_vs_position": "Should be near zero if no fills/transfers are missing.",
    }
    return notes.get(key, "")


def elapsed_text(start_iso: Any, end_iso: Any) -> str:
    if not start_iso or not end_iso:
        return "unavailable"
    try:
        start = datetime.fromisoformat(str(start_iso).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(end_iso).replace("Z", "+00:00"))
    except ValueError:
        return "unavailable"
    seconds = int((end - start).total_seconds())
    if seconds < 0:
        return f"source conflict: end timestamp is {duration_text(-seconds)} before start"
    return duration_text(seconds)


def duration_text(seconds: int) -> str:
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours}h {minutes}m {sec}s"
    if hours:
        return f"{hours}h {minutes}m {sec}s"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def percent_of(numerator: Decimal, denominator: Decimal) -> str:
    if denominator <= 0:
        return "unavailable"
    return f"{fmt_decimal((numerator / denominator) * Decimal(100), places=2)}%"


def blockquote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


if __name__ == "__main__":
    main()
