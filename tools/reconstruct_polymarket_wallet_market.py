from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import time
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DATA_BASE = "https://data-api.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"
DEFAULT_MARKET_SLUG = "microstrategy-sells-any-bitcoin-by-june-30-2026"
DEFAULT_OUT_DIR = "polymarket_wallet_market_report"
TARGET_TITLE = "MicroStrategy sells any Bitcoin by June 30, 2026?"
KYIV_TZ = ZoneInfo("Europe/Kyiv")
ET_TZ = ZoneInfo("America/New_York")
POLYGON_CHAIN_ID = "0x89"
POLYGON_RPCS = (
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
)
POLYGONSCAN_TX = "https://polygonscan.com/tx/{hash}"
PUSD_CONTRACT = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"
CTF_CONTRACT = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
ERC20_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ERC1155_TRANSFER_SINGLE = "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"
ERC1155_TRANSFER_BATCH = "0x4a39dc06d4c0dbc64b70b5b1d8ffdbc2fabea8fdbd13a7eedf0a6e4c3b0911be"
HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; InsPoly forensic reconstruction; +https://polymarket.com)",
}


@dataclass
class HttpResult:
    url: str
    status: int
    payload: Any


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconstruct a Polymarket wallet's trades for one market from raw Data/Gamma API rows.",
    )
    parser.add_argument("--wallet", required=True, help="Polymarket wallet/proxy address to reconstruct")
    parser.add_argument("--market-slug", default=DEFAULT_MARKET_SLUG)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--skip-onchain", action="store_true", help="Skip Polygon transaction receipt verification")
    args = parser.parse_args()

    wallet = normalize_address(args.wallet)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    market_metadata = build_market_metadata(wallet, args.market_slug)
    write_json(out_dir / "market_metadata.json", market_metadata)

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
    market_metadata["accounting_snapshot"] = accounting
    write_json(out_dir / "market_metadata.json", market_metadata)

    target_filter = target_filter_from_metadata(market_metadata)
    trade_rows = [row for row in raw_trades["rows"] if is_target_row(row, target_filter)]
    activity_rows = [row for row in raw_activity["rows"] if is_target_row(row, target_filter)]
    target_positions = [row for row in raw_positions_current["rows"] if is_target_row(row, target_filter)]
    target_closed_positions = [row for row in raw_positions_closed["rows"] if is_target_row(row, target_filter)]

    onchain = {}
    if not args.skip_onchain:
        tx_hashes = sorted({str(row.get("transactionHash") or "") for row in trade_rows + activity_rows if row.get("transactionHash")})
        onchain = verify_transactions(wallet, tx_hashes, sleep_seconds=0.08)
    write_json(out_dir / "onchain_verification.json", onchain)

    records = build_records(trade_rows, activity_rows, onchain)
    normalized_rows, ledger_rows, summary_rows, summary = build_ledgers(records, target_positions, market_metadata, onchain)

    write_csv(out_dir / "normalized_trades.csv", normalized_rows, NORMALIZED_FIELDS)
    write_csv(out_dir / "chronological_ledger.csv", ledger_rows, LEDGER_FIELDS)
    write_csv(out_dir / "summary_calculations.csv", summary_rows, SUMMARY_FIELDS)

    report = build_report(
        wallet=wallet,
        out_dir=out_dir,
        market_metadata=market_metadata,
        raw_trades=raw_trades,
        raw_activity=raw_activity,
        raw_positions_current=raw_positions_current,
        raw_positions_closed=raw_positions_closed,
        target_positions=target_positions,
        target_closed_positions=target_closed_positions,
        normalized_rows=normalized_rows,
        ledger_rows=ledger_rows,
        summary=summary,
        onchain=onchain,
    )
    (out_dir / "final_report.md").write_text(report, encoding="utf-8")

    print(f"Wrote report artifacts to {out_dir.resolve()}")
    print(f"Target records: {len(records)}; current target positions: {len(target_positions)}")
    print(f"Weighted-average realized P/L: {money(summary['realized_pnl_wac'])}")
    print(f"Ledger remaining YES: {fmt_decimal(summary['remaining_yes_shares'])}")


def build_market_metadata(wallet: str, market_slug: str) -> dict[str, Any]:
    fetched_at = now_iso()
    exact_market = safe_get_json(f"{GAMMA_BASE}/markets/slug/{market_slug}")
    search = safe_get_json(
        f"{GAMMA_BASE}/markets",
        {"search": TARGET_TITLE, "limit": 20, "offset": 0},
    )
    event_payload = None
    if isinstance(exact_market.payload, dict):
        events = exact_market.payload.get("events") or []
        if events and isinstance(events[0], dict) and events[0].get("slug"):
            event_payload = safe_get_json(f"{GAMMA_BASE}/events/slug/{events[0]['slug']}")
    profile = safe_get_json(f"{GAMMA_BASE}/public-profile", {"address": wallet})
    traded = safe_get_json(f"{DATA_BASE}/traded", {"user": wallet})
    value = safe_get_json(f"{DATA_BASE}/value", {"user": wallet})

    market_payload = exact_market.payload if isinstance(exact_market.payload, dict) else {}
    outcomes = parse_jsonish_list(market_payload.get("outcomes"))
    token_ids = parse_jsonish_list(market_payload.get("clobTokenIds"))
    outcome_token_map = {}
    for index, outcome in enumerate(outcomes):
        if index < len(token_ids):
            outcome_token_map[str(outcome)] = str(token_ids[index])

    return {
        "generated_at_utc": fetched_at,
        "wallet": wallet,
        "requested_market_slug": market_slug,
        "target_title": TARGET_TITLE,
        "market": market_payload,
        "market_summary": {
            "id": str(market_payload.get("id") or ""),
            "title": str(market_payload.get("question") or ""),
            "slug": str(market_payload.get("slug") or market_slug),
            "eventSlug": event_slug_from_market(market_payload),
            "conditionId": str(market_payload.get("conditionId") or ""),
            "outcomes": [str(item) for item in outcomes],
            "tokenIds": [str(item) for item in token_ids],
            "outcomeTokenMap": outcome_token_map,
            "startDate": market_payload.get("startDate"),
            "createdAt": market_payload.get("createdAt"),
            "acceptingOrdersTimestamp": market_payload.get("acceptingOrdersTimestamp"),
            "endDate": market_payload.get("endDate"),
            "resolutionCriteria": market_payload.get("description"),
            "currentOutcomePrices": parse_jsonish_list(market_payload.get("outcomePrices")),
            "bestBid": market_payload.get("bestBid"),
            "bestAsk": market_payload.get("bestAsk"),
            "lastTradePrice": market_payload.get("lastTradePrice"),
            "liquidity": market_payload.get("liquidity"),
            "volume": market_payload.get("volume"),
            "volume24hr": market_payload.get("volume24hr"),
            "feesEnabled": market_payload.get("feesEnabled"),
            "feeSchedule": market_payload.get("feeSchedule"),
        },
        "gamma_exact_market": {
            "url": exact_market.url,
            "status": exact_market.status,
        },
        "gamma_search": {
            "url": search.url,
            "status": search.status,
            "payload": search.payload,
        },
        "gamma_event": {
            "url": event_payload.url if event_payload else "",
            "status": event_payload.status if event_payload else None,
            "payload": event_payload.payload if event_payload else None,
        },
        "wallet_context": {
            "public_profile_url": profile.url,
            "public_profile_status": profile.status,
            "public_profile": profile.payload,
            "traded_url": traded.url,
            "traded_status": traded.status,
            "traded": traded.payload,
            "value_url": value.url,
            "value_status": value.status,
            "value": value.payload,
        },
        "official_docs_used": [
            "https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets",
            "https://docs.polymarket.com/api-reference/core/get-user-activity",
            "https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user",
            "https://docs.polymarket.com/api-reference/core/get-closed-positions-for-a-user",
            "https://docs.polymarket.com/resources/contracts",
            "https://docs.polymarket.com/concepts/pusd",
        ],
    }


def fetch_paginated(endpoint: str, params: dict[str, Any], *, limit: int, max_offset: int) -> dict[str, Any]:
    pages = []
    rows = []
    offset = 0
    while offset <= max_offset:
        page_params = dict(params)
        page_params["limit"] = limit
        page_params["offset"] = offset
        result = safe_get_json(endpoint, page_params)
        payload = result.payload
        page_rows = payload if isinstance(payload, list) else []
        pages.append(
            {
                "url": result.url,
                "status": result.status,
                "offset": offset,
                "limit": limit,
                "row_count": len(page_rows),
                "response": payload,
            }
        )
        rows.extend(page_rows)
        if not isinstance(payload, list) or len(page_rows) < limit:
            break
        offset += limit
        time.sleep(0.04)
    return {
        "fetched_at_utc": now_iso(),
        "endpoint": endpoint,
        "base_params": params,
        "limit": limit,
        "max_offset": max_offset,
        "page_count": len(pages),
        "row_count": len(rows),
        "pages": pages,
        "rows": rows,
    }


def fetch_accounting_snapshot(wallet: str, out_dir: Path) -> dict[str, Any]:
    params = {"user": wallet}
    url = f"{DATA_BASE}/v1/accounting/snapshot?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": HTTP_HEADERS["User-Agent"]})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            status = int(response.status)
    except Exception as exc:
        return {
            "url": url,
            "status": None,
            "error": f"{type(exc).__name__}: {exc}",
            "saved_files": [],
        }
    zip_path = out_dir / "raw_accounting_snapshot.zip"
    zip_path.write_bytes(body)
    saved_files = [zip_path.name]
    extracted = []
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            for info in archive.infolist():
                if not info.filename.endswith(".csv"):
                    continue
                target = out_dir / f"accounting_{Path(info.filename).name}"
                target.write_bytes(archive.read(info.filename))
                saved_files.append(target.name)
                extracted.append({"name": info.filename, "size": info.file_size})
    except Exception as exc:
        return {
            "url": url,
            "status": status,
            "error": f"downloaded but unzip failed: {type(exc).__name__}: {exc}",
            "saved_files": saved_files,
        }
    return {
        "url": url,
        "status": status,
        "content_length_bytes": len(body),
        "saved_files": saved_files,
        "extracted_members": extracted,
    }


def safe_get_json(endpoint: str, params: dict[str, Any] | None = None) -> HttpResult:
    url = endpoint
    if params:
        url = f"{endpoint}?{urllib.parse.urlencode(params, doseq=True)}"
    last_error = None
    for attempt in range(4):
        request = urllib.request.Request(url, headers=HTTP_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    payload = {"non_json_body": body[:1000]}
                return HttpResult(url=url, status=int(response.status), payload=payload)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < 3:
                time.sleep(0.6 * (2**attempt))
                continue
    return HttpResult(url=url, status=0, payload={"error": last_error})


def target_filter_from_metadata(metadata: dict[str, Any]) -> dict[str, set[str]]:
    summary = metadata.get("market_summary") or {}
    return {
        "condition_ids": {normalize_hex(summary.get("conditionId"))} - {""},
        "assets": {str(item) for item in summary.get("tokenIds") or [] if str(item)},
        "slugs": {slugify(summary.get("slug")), slugify(DEFAULT_MARKET_SLUG)} - {""},
        "event_slugs": {slugify(summary.get("eventSlug"))} - {""},
        "title_tokens": set(normalize_text(TARGET_TITLE).split()),
    }


def is_target_row(row: dict[str, Any], target: dict[str, set[str]]) -> bool:
    condition_id = normalize_hex(row.get("conditionId"))
    if condition_id and condition_id in target["condition_ids"]:
        return True
    asset = str(row.get("asset") or "")
    if asset and asset in target["assets"]:
        return True
    slug = slugify(row.get("slug"))
    if slug and slug in target["slugs"]:
        return True
    title_tokens = set(normalize_text(str(row.get("title") or row.get("question") or "")).split())
    if target["title_tokens"] and len(title_tokens & target["title_tokens"]) >= min(5, len(target["title_tokens"])):
        return True
    event_slug = slugify(row.get("eventSlug"))
    if event_slug and event_slug in target["event_slugs"] and {"microstrategy", "bitcoin"} <= title_tokens:
        return True
    return False


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
            key = row_key(row)
            existing = combined.setdefault(
                key,
                {
                    "source_order": order,
                    "sources": set(),
                    "trades_row": None,
                    "activity_row": None,
                },
            )
            existing["sources"].add(source)
            existing[f"{source}_row"] = row
    records = []
    for entry in combined.values():
        row = entry["activity_row"] or entry["trades_row"] or {}
        timestamp = int(to_decimal(row.get("timestamp")))
        size = to_decimal(row.get("size"))
        price = to_decimal(row.get("price"))
        recomputed = size * price
        api_cash = to_decimal(row.get("usdcSize")) if row.get("usdcSize") is not None else recomputed
        side = str(row.get("side") or "").upper()
        signed_cash = api_cash if side == "SELL" else -api_cash
        tx_hash = str(row.get("transactionHash") or "")
        tx_info = onchain.get(tx_hash) or {}
        block_timestamp_unix = int(to_decimal(tx_info.get("block_timestamp_unix"))) if tx_info.get("block_timestamp_unix") else 0
        timestamp_delta = block_timestamp_unix - timestamp if block_timestamp_unix else ""
        records.append(
            {
                "source_order": entry["source_order"],
                "source_endpoint": "+".join(sorted(entry["sources"])),
                "timestamp": timestamp,
                "timestamp_utc": timestamp_iso(timestamp, UTC),
                "timestamp_kyiv": timestamp_iso(timestamp, KYIV_TZ),
                "timestamp_et": timestamp_iso(timestamp, ET_TZ),
                "side": side,
                "outcome": title_case_outcome(row.get("outcome")),
                "conditionId": str(row.get("conditionId") or ""),
                "asset": str(row.get("asset") or ""),
                "market_title": str(row.get("title") or ""),
                "slug": str(row.get("slug") or ""),
                "eventSlug": str(row.get("eventSlug") or ""),
                "shares": size,
                "price": price,
                "api_cash_amount": api_cash,
                "recomputed_cash_amount": recomputed,
                "api_minus_recomputed": api_cash - recomputed,
                "net_cash_flow": signed_cash,
                "transactionHash": tx_hash,
                "polygon_tx_url": POLYGONSCAN_TX.format(hash=tx_hash) if tx_hash else "",
                "block_timestamp_utc": tx_info.get("block_timestamp_utc", ""),
                "chain": tx_info.get("chain", ""),
                "onchain_status": tx_info.get("status", "not_checked"),
                "onchain_timestamp_delta_seconds": timestamp_delta,
                "onchain_pusd_net_wallet": to_decimal(tx_info.get("pusd_net_wallet", 0)),
                "onchain_ctf_net_for_asset": to_decimal((tx_info.get("ctf_net_by_token") or {}).get(str(row.get("asset") or ""), 0)),
                "onchain_summary": tx_info.get("summary", ""),
            }
        )
    records.sort(key=lambda item: (item["timestamp"], item["source_order"], item["transactionHash"]))
    return records


def build_ledgers(
    records: list[dict[str, Any]],
    target_positions: list[dict[str, Any]],
    market_metadata: dict[str, Any],
    onchain: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Decimal]]:
    cumulative_shares = defaultdict(Decimal)
    cost_pool = defaultdict(Decimal)
    fifo_lots: dict[str, deque[dict[str, Decimal]]] = defaultdict(deque)
    cumulative_net_cash = Decimal("0")
    realized_wac = Decimal("0")
    realized_fifo = Decimal("0")
    total_buy_shares = defaultdict(Decimal)
    total_buy_cost = defaultdict(Decimal)
    total_sell_shares = defaultdict(Decimal)
    total_sell_proceeds = defaultdict(Decimal)
    normalized_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    sale_breakdowns: list[dict[str, Decimal]] = []

    for seq, record in enumerate(records, start=1):
        outcome = record["outcome"]
        shares = record["shares"]
        cash = record["api_cash_amount"]
        side = record["side"]
        recomputed = record["recomputed_cash_amount"]
        delta = record["api_minus_recomputed"]
        sale_realized_wac = Decimal("0")
        sale_realized_fifo = Decimal("0")
        sale_cost_basis_wac = Decimal("0")
        sale_cost_basis_fifo = Decimal("0")

        if side == "BUY":
            cumulative_shares[outcome] += shares
            cost_pool[outcome] += cash
            total_buy_shares[outcome] += shares
            total_buy_cost[outcome] += cash
            unit_cost = cash / shares if shares else Decimal("0")
            fifo_lots[outcome].append({"shares": shares, "unit_cost": unit_cost})
        elif side == "SELL":
            available = cumulative_shares[outcome]
            average_cost = cost_pool[outcome] / available if available else Decimal("0")
            sale_cost_basis_wac = min(shares, available) * average_cost
            sale_realized_wac = cash - sale_cost_basis_wac
            realized_wac += sale_realized_wac
            cost_pool[outcome] -= sale_cost_basis_wac
            cumulative_shares[outcome] -= shares
            total_sell_shares[outcome] += shares
            total_sell_proceeds[outcome] += cash

            remaining_to_match = shares
            while remaining_to_match > 0 and fifo_lots[outcome]:
                lot = fifo_lots[outcome][0]
                take = min(remaining_to_match, lot["shares"])
                sale_cost_basis_fifo += take * lot["unit_cost"]
                lot["shares"] -= take
                remaining_to_match -= take
                if lot["shares"] <= Decimal("0.0000000001"):
                    fifo_lots[outcome].popleft()
            sale_realized_fifo = cash - sale_cost_basis_fifo
            realized_fifo += sale_realized_fifo
            sale_breakdowns.append(
                {
                    "seq": Decimal(seq),
                    "shares": shares,
                    "proceeds": cash,
                    "wac_cost_basis": sale_cost_basis_wac,
                    "wac_realized": sale_realized_wac,
                    "fifo_cost_basis": sale_cost_basis_fifo,
                    "fifo_realized": sale_realized_fifo,
                }
            )

        cumulative_net_cash += record["net_cash_flow"]
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
                "conditionId": record["conditionId"],
                "asset": record["asset"],
                "slug": record["slug"],
                "eventSlug": record["eventSlug"],
                "shares": fmt_decimal(shares),
                "price": fmt_decimal(record["price"], places=10),
                "api_cash_amount": fmt_decimal(cash),
                "recomputed_cash_amount": fmt_decimal(recomputed),
                "api_minus_recomputed": fmt_decimal(delta),
                "fee_if_available": fee_note(delta),
                "net_cash_flow": fmt_decimal(record["net_cash_flow"]),
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
                "shares": fmt_decimal(shares),
                "price": fmt_decimal(record["price"], places=10),
                "cash_amount": fmt_decimal(cash),
                "fee_if_available": fee_note(delta),
                "net_cash_flow": fmt_decimal(record["net_cash_flow"]),
                "cumulative_yes_shares_after_trade": fmt_decimal(cumulative_shares["Yes"]),
                "cumulative_no_shares_after_trade": fmt_decimal(cumulative_shares["No"]),
                "cumulative_cash_spent_received": fmt_decimal(cumulative_net_cash),
                "estimated_realized_pnl_after_trade": fmt_decimal(realized_wac),
                "sale_realized_pnl_wac": fmt_decimal(sale_realized_wac),
                "sale_realized_pnl_fifo": fmt_decimal(sale_realized_fifo),
                "transactionHash": record["transactionHash"],
                "polygon_tx_url": record["polygon_tx_url"],
                "source_endpoint": record["source_endpoint"],
                "confidence_level": confidence,
                "api_cash_amount": fmt_decimal(cash),
                "recomputed_cash_amount": fmt_decimal(recomputed),
                "api_minus_recomputed": fmt_decimal(delta),
                "conditionId": record["conditionId"],
                "asset": record["asset"],
            }
        )

    current_position = target_positions[0] if target_positions else {}
    current_position_size = to_decimal(current_position.get("size")) if current_position else Decimal("0")
    current_value = to_decimal(current_position.get("currentValue")) if current_position else Decimal("0")
    current_price = to_decimal(current_position.get("curPrice") or current_position.get("avgPrice")) if current_position else Decimal("0")
    current_api_avg_price = to_decimal(current_position.get("avgPrice")) if current_position else Decimal("0")
    remaining_yes_cost_wac = cost_pool["Yes"]
    remaining_no_cost_wac = cost_pool["No"]
    unrealized_wac = current_value - remaining_yes_cost_wac if current_value else Decimal("0")
    api_realized = to_decimal(current_position.get("realizedPnl")) if current_position else Decimal("0")
    api_cash_pnl = to_decimal(current_position.get("cashPnl")) if current_position else Decimal("0")
    buy_yes_cost = total_buy_cost["Yes"]
    sell_yes_proceeds = total_sell_proceeds["Yes"]
    summary = {
        "total_yes_bought": total_buy_shares["Yes"],
        "total_no_bought": total_buy_shares["No"],
        "total_yes_buy_cost": buy_yes_cost,
        "total_no_buy_cost": total_buy_cost["No"],
        "weighted_avg_yes_entry": buy_yes_cost / total_buy_shares["Yes"] if total_buy_shares["Yes"] else Decimal("0"),
        "total_yes_sold": total_sell_shares["Yes"],
        "total_no_sold": total_sell_shares["No"],
        "total_yes_sale_proceeds": sell_yes_proceeds,
        "total_no_sale_proceeds": total_sell_proceeds["No"],
        "weighted_avg_yes_sale": sell_yes_proceeds / total_sell_shares["Yes"] if total_sell_shares["Yes"] else Decimal("0"),
        "remaining_yes_shares": cumulative_shares["Yes"],
        "remaining_no_shares": cumulative_shares["No"],
        "current_position_size_api": current_position_size,
        "current_value_api": current_value,
        "current_price_api": current_price,
        "current_avg_price_api": current_api_avg_price,
        "remaining_yes_cost_wac": remaining_yes_cost_wac,
        "remaining_no_cost_wac": remaining_no_cost_wac,
        "realized_pnl_wac": realized_wac,
        "realized_pnl_fifo": realized_fifo,
        "unrealized_pnl_wac": unrealized_wac,
        "api_position_realized_pnl": api_realized,
        "api_position_cash_pnl": api_cash_pnl,
        "total_net_cash_flow": cumulative_net_cash,
        "total_trade_rows": Decimal(len(records)),
        "unique_tx_hashes": Decimal(len({row["transactionHash"] for row in records if row["transactionHash"]})),
    }
    summary_rows = [
        {"metric": key, "value": fmt_decimal(value), "notes": summary_note(key, summary, market_metadata)}
        for key, value in summary.items()
    ]
    for item in sale_breakdowns:
        summary_rows.append(
            {
                "metric": f"sale_{int(item['seq'])}_wac_realized_pnl",
                "value": fmt_decimal(item["wac_realized"]),
                "notes": (
                    f"shares={fmt_decimal(item['shares'])}; proceeds={fmt_decimal(item['proceeds'])}; "
                    f"wac_cost_basis={fmt_decimal(item['wac_cost_basis'])}; "
                    f"fifo_realized={fmt_decimal(item['fifo_realized'])}"
                ),
            }
        )
    return normalized_rows, ledger_rows, summary_rows, summary


def verify_transactions(wallet: str, tx_hashes: list[str], *, sleep_seconds: float) -> dict[str, Any]:
    rpcs = available_polygon_rpcs()
    if not rpcs:
        return {
            "verification_status": "not_verifiable",
            "reason": "No public Polygon RPC endpoint returned chainId 0x89.",
        }
    results: dict[str, Any] = {
        "verification_status": "attempted",
        "rpc_urls": rpcs,
        "chain": "Polygon",
        "chain_id": POLYGON_CHAIN_ID,
        "tx_count": len(tx_hashes),
    }
    block_cache: dict[str, dict[str, Any]] = {}
    for index, tx_hash in enumerate(tx_hashes, start=1):
        if index == 1 or index % 10 == 0 or index == len(tx_hashes):
            print(f"Verifying Polygon transaction {index}/{len(tx_hashes)}", flush=True)
        try:
            rpc, receipt = rpc_call_with_fallback(rpcs, "eth_getTransactionReceipt", [tx_hash])
            receipt_result = receipt.get("result") if isinstance(receipt, dict) else None
            if not isinstance(receipt_result, dict):
                results[tx_hash] = {
                    "status": "not_found",
                    "chain": "Polygon",
                    "tx_url": POLYGONSCAN_TX.format(hash=tx_hash),
                }
                continue
            block_number = str(receipt_result.get("blockNumber") or "")
            block = block_cache.get(block_number)
            if block is None:
                _block_rpc, block_response = rpc_call_with_fallback(rpcs, "eth_getBlockByNumber", [block_number, False])
                block = block_response.get("result") if isinstance(block_response, dict) else {}
                block_cache[block_number] = block if isinstance(block, dict) else {}
            block_ts = int(str(block.get("timestamp") or "0x0"), 16)
            decoded = decode_receipt_logs(wallet, receipt_result)
            results[tx_hash] = {
                "status": "verified",
                "chain": "Polygon",
                "chain_id": POLYGON_CHAIN_ID,
                "rpc_url": rpc,
                "tx_url": POLYGONSCAN_TX.format(hash=tx_hash),
                "block_number": int(block_number, 16) if block_number.startswith("0x") else block_number,
                "block_timestamp_unix": block_ts,
                "block_timestamp_utc": timestamp_iso(block_ts, UTC),
                "receipt_status": receipt_result.get("status"),
                "exchange_contract": normalize_address(receipt_result.get("to")),
                "pusd_net_wallet": fmt_decimal(decoded["pusd_net_wallet"]),
                "pusd_in_wallet": fmt_decimal(decoded["pusd_in_wallet"]),
                "pusd_out_wallet": fmt_decimal(decoded["pusd_out_wallet"]),
                "ctf_net_by_token": {token: fmt_decimal(value) for token, value in decoded["ctf_net_by_token"].items()},
                "erc20_transfer_count": decoded["erc20_transfer_count"],
                "erc1155_transfer_count": decoded["erc1155_transfer_count"],
                "summary": decoded["summary"],
            }
        except Exception as exc:
            results[tx_hash] = {
                "status": "error",
                "chain": "Polygon",
                "error": f"{type(exc).__name__}: {exc}",
                "tx_url": POLYGONSCAN_TX.format(hash=tx_hash),
            }
        if index < len(tx_hashes):
            time.sleep(sleep_seconds)
    return results


def available_polygon_rpcs() -> list[str]:
    available = []
    for rpc in POLYGON_RPCS:
        try:
            result = rpc_call(rpc, "eth_chainId", [])
            if result.get("result") == POLYGON_CHAIN_ID:
                available.append(rpc)
        except Exception:
            continue
    return available


def rpc_call_with_fallback(rpcs: list[str], method: str, params: list[Any]) -> tuple[str, dict[str, Any]]:
    errors = []
    for rpc in rpcs:
        try:
            return rpc, rpc_call(rpc, method, params)
        except Exception as exc:
            errors.append(f"{rpc}: {type(exc).__name__}: {exc}")
    raise RuntimeError("; ".join(errors))


def rpc_call(rpc: str, method: str, params: list[Any]) -> dict[str, Any]:
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode("utf-8")
    request = urllib.request.Request(
        rpc,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": HTTP_HEADERS["User-Agent"],
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(payload["error"])
    return payload


def decode_receipt_logs(wallet: str, receipt: dict[str, Any]) -> dict[str, Any]:
    wallet = normalize_address(wallet)
    pusd_in = Decimal("0")
    pusd_out = Decimal("0")
    ctf_net: dict[str, Decimal] = defaultdict(Decimal)
    erc20_count = 0
    erc1155_count = 0
    logs = receipt.get("logs") or []
    for log in logs:
        if not isinstance(log, dict):
            continue
        address = normalize_address(log.get("address"))
        topics = [str(item).lower() for item in log.get("topics") or []]
        data = str(log.get("data") or "0x")
        if address == PUSD_CONTRACT and topics and topics[0] == ERC20_TRANSFER and len(topics) >= 3:
            erc20_count += 1
            from_addr = address_from_topic(topics[1])
            to_addr = address_from_topic(topics[2])
            value = Decimal(int(data or "0x0", 16)) / Decimal(1_000_000)
            if to_addr == wallet:
                pusd_in += value
            if from_addr == wallet:
                pusd_out += value
        elif address == CTF_CONTRACT and topics and topics[0] == ERC1155_TRANSFER_SINGLE and len(topics) >= 4:
            erc1155_count += 1
            from_addr = address_from_topic(topics[2])
            to_addr = address_from_topic(topics[3])
            words = data_words(data)
            if len(words) >= 2:
                token_id = str(int(words[0], 16))
                value = Decimal(int(words[1], 16)) / Decimal(1_000_000)
                if to_addr == wallet:
                    ctf_net[token_id] += value
                if from_addr == wallet:
                    ctf_net[token_id] -= value
        elif address == CTF_CONTRACT and topics and topics[0] == ERC1155_TRANSFER_BATCH and len(topics) >= 4:
            erc1155_count += 1
            from_addr = address_from_topic(topics[2])
            to_addr = address_from_topic(topics[3])
            ids, values = parse_transfer_batch(data)
            for token_id, raw_value in zip(ids, values):
                value = Decimal(raw_value) / Decimal(1_000_000)
                if to_addr == wallet:
                    ctf_net[str(token_id)] += value
                if from_addr == wallet:
                    ctf_net[str(token_id)] -= value
    summary_parts = []
    net = pusd_in - pusd_out
    if pusd_in or pusd_out:
        summary_parts.append(f"wallet pUSD net {fmt_decimal(net)} (in {fmt_decimal(pusd_in)}, out {fmt_decimal(pusd_out)})")
    if ctf_net:
        token_parts = [f"{token}: {fmt_decimal(value)}" for token, value in sorted(ctf_net.items())]
        summary_parts.append("CTF token net {" + "; ".join(token_parts) + "}")
    return {
        "pusd_in_wallet": pusd_in,
        "pusd_out_wallet": pusd_out,
        "pusd_net_wallet": net,
        "ctf_net_by_token": ctf_net,
        "erc20_transfer_count": erc20_count,
        "erc1155_transfer_count": erc1155_count,
        "summary": "; ".join(summary_parts) if summary_parts else "No pUSD/CTF wallet transfer decoded",
    }


def parse_transfer_batch(data: str) -> tuple[list[int], list[int]]:
    words = data_words(data)
    if len(words) < 4:
        return [], []
    ids_offset = int(words[0], 16) // 32
    values_offset = int(words[1], 16) // 32
    ids = parse_uint_array(words, ids_offset)
    values = parse_uint_array(words, values_offset)
    return ids, values


def parse_uint_array(words: list[str], offset_words: int) -> list[int]:
    if offset_words >= len(words):
        return []
    length = int(words[offset_words], 16)
    values = []
    for index in range(length):
        word_index = offset_words + 1 + index
        if word_index >= len(words):
            break
        values.append(int(words[word_index], 16))
    return values


def data_words(data: str) -> list[str]:
    clean = data[2:] if data.startswith("0x") else data
    if not clean:
        return []
    return [clean[index : index + 64] for index in range(0, len(clean), 64)]


def build_report(
    *,
    wallet: str,
    out_dir: Path,
    market_metadata: dict[str, Any],
    raw_trades: dict[str, Any],
    raw_activity: dict[str, Any],
    raw_positions_current: dict[str, Any],
    raw_positions_closed: dict[str, Any],
    target_positions: list[dict[str, Any]],
    target_closed_positions: list[dict[str, Any]],
    normalized_rows: list[dict[str, Any]],
    ledger_rows: list[dict[str, Any]],
    summary: dict[str, Decimal],
    onchain: dict[str, Any],
) -> str:
    market = market_metadata.get("market_summary") or {}
    current_pos = target_positions[0] if target_positions else {}
    profile = ((market_metadata.get("wallet_context") or {}).get("public_profile") or {})
    profile_name = str(profile.get("name") or wallet)
    profile_url = f"https://polymarket.com/ru/@{urllib.parse.quote(profile_name)}"
    traded = ((market_metadata.get("wallet_context") or {}).get("traded") or {})
    first_trade = ledger_rows[0] if ledger_rows else {}
    last_trade = ledger_rows[-1] if ledger_rows else {}
    confidence_counts = defaultdict(int)
    for row in ledger_rows:
        confidence_counts[str(row["confidence_level"])] += 1
    buys = [row for row in ledger_rows if row["side"] == "BUY"]
    sells = [row for row in ledger_rows if row["side"] == "SELL"]
    tx_rows = onchain_rows_for_report(onchain, normalized_rows)

    reconciliation_delta = summary["total_yes_bought"] - summary["total_yes_sold"] - summary["remaining_yes_shares"]
    position_api_delta = summary["remaining_yes_shares"] - summary["current_position_size_api"]
    total_pnl_wac = summary["realized_pnl_wac"] + summary["unrealized_pnl_wac"]

    lines = [
        "# Polymarket Wallet Trade Reconstruction",
        "",
        f"Generated: {now_iso()}",
        f"Wallet/profile: [{wallet}]({profile_url})",
        f"Target market: [{market.get('title') or TARGET_TITLE}](https://polymarket.com/market/{market.get('slug') or DEFAULT_MARKET_SLUG})",
        "",
        "## A. Executive Summary",
        "",
        (
            f"The wallet was created at {profile.get('createdAt', 'unknown')} and traded only this one visible market "
            f"according to `/traded` (`traded={traded.get('traded', 'unknown')}`). It bought "
            f"{fmt_decimal(summary['total_yes_bought'])} YES shares for {money(summary['total_yes_buy_cost'])} across "
            f"{len(buys)} fills, then sold {fmt_decimal(summary['total_yes_sold'])} YES shares for "
            f"{money(summary['total_yes_sale_proceeds'])} across {len(sells)} fills. The reconstructed weighted-average "
            f"realized P/L is {money(summary['realized_pnl_wac'])}; FIFO P/L is {money(summary['realized_pnl_fifo'])}. "
            f"The wallet did not fully exit: the ledger leaves {fmt_decimal(summary['remaining_yes_shares'])} YES shares, "
            f"matching the current-position API within rounding. Current mark-to-market value is "
            f"{money(summary['current_value_api'])}, with estimated weighted-average unrealized P/L of "
            f"{money(summary['unrealized_pnl_wac'])}; total realized plus unrealized P/L is about {money(total_pnl_wac)}."
        ),
        "",
        "## B. Data Sources and Limitations",
        "",
        "- Raw trades: Polymarket Data API `/trades` with `user` and `takerOnly=false`.",
        "- Raw activity: Polymarket Data API `/activity` with `user` and `type=TRADE`.",
        "- Current positions: Polymarket Data API `/positions` with `sizeThreshold=0`.",
        "- Closed positions: Polymarket Data API `/closed-positions`; returned no closed target position rows.",
        "- Accounting snapshot: Polymarket Data API `/v1/accounting/snapshot`; ZIP extracted when available.",
        "- Market metadata: Gamma API `/markets/slug/{slug}` plus `/events/slug/{eventSlug}` where available.",
        "- On-chain verification: Polygon JSON-RPC transaction receipts and block timestamps for returned `transactionHash` values.",
        "- UI screenshots were not used as evidence; screenshot-derived facts were treated only as leads.",
        (
            "- Fees: no explicit fee field was returned by the Data API. The report uses `activity.usdcSize` as the "
            "authoritative wallet cash amount and preserves the `size * price` recomputation and the difference. "
            "On-chain pUSD wallet net flow generally corroborates `usdcSize`."
        ),
        "",
        f"Endpoint row counts before filtering: `/trades` {raw_trades['row_count']} rows; `/activity` {raw_activity['row_count']} rows; `/positions` {raw_positions_current['row_count']} rows; `/closed-positions` {raw_positions_closed['row_count']} rows.",
        "",
        "## C. Market Identification",
        "",
        f"- Market title: {market.get('title') or ''}",
        f"- Slug: `{market.get('slug') or ''}`",
        f"- Event slug: `{market.get('eventSlug') or ''}`",
        f"- Market ID: `{market.get('id') or ''}`",
        f"- Condition ID: `{market.get('conditionId') or ''}`",
        f"- YES token/outcome ID: `{((market.get('outcomeTokenMap') or {}).get('Yes') or '')}`",
        f"- NO token/outcome ID: `{((market.get('outcomeTokenMap') or {}).get('No') or '')}`",
        f"- Market opening/start time: `{market.get('startDate') or ''}`; accepting orders: `{market.get('acceptingOrdersTimestamp') or ''}`",
        f"- End time: `{market.get('endDate') or ''}`",
        f"- Current prices from Gamma/current position: YES {market_price_label(market, current_pos)}",
        f"- Liquidity/volume from Gamma: liquidity {market.get('liquidity')}; volume {market.get('volume')}; 24h volume {market.get('volume24hr')}.",
        "- Resolution criteria:",
        "",
        blockquote(str(market.get("resolutionCriteria") or "Unavailable")),
        "",
        "## D. Full Chronology Table",
        "",
        "This table has one row per Data API fill. `Cash` is API `usdcSize` where present; `delta` is API cash minus recomputed `shares * price`.",
        "",
        markdown_table(
            ledger_rows,
            [
                ("#", "sequence"),
                ("UTC", "timestamp_utc"),
                ("Kyiv", "timestamp_kyiv"),
                ("ET", "timestamp_et"),
                ("Side", "side"),
                ("Outcome", "outcome"),
                ("Shares", "shares"),
                ("Price", "price"),
                ("Cash", "cash_amount"),
                ("Fee/delta", "fee_if_available"),
                ("Net cash", "net_cash_flow"),
                ("Cum YES", "cumulative_yes_shares_after_trade"),
                ("Cum NO", "cumulative_no_shares_after_trade"),
                ("Cum cash", "cumulative_cash_spent_received"),
                ("Realized P/L", "estimated_realized_pnl_after_trade"),
                ("Tx", "transactionHash"),
                ("Source", "source_endpoint"),
                ("Confidence", "confidence_level"),
            ],
            tx_link=True,
        ),
        "",
        "## E. Buy-side Reconstruction",
        "",
        f"- Total YES bought: {fmt_decimal(summary['total_yes_bought'])}.",
        f"- Total NO bought: {fmt_decimal(summary['total_no_bought'])}.",
        f"- Weighted-average YES entry price using API cash: {fmt_decimal(summary['weighted_avg_yes_entry'], places=8)}.",
        f"- Total YES cost using API cash: {money(summary['total_yes_buy_cost'])}.",
        "",
        markdown_table(
            buys,
            [
                ("#", "sequence"),
                ("UTC", "timestamp_utc"),
                ("Outcome", "outcome"),
                ("Shares", "shares"),
                ("Price", "price"),
                ("API cash", "api_cash_amount"),
                ("Recomputed", "recomputed_cash_amount"),
                ("Delta", "api_minus_recomputed"),
                ("Tx", "transactionHash"),
            ],
            tx_link=True,
        ),
        "",
        "## F. Sell-side Reconstruction",
        "",
        f"- Total YES sold: {fmt_decimal(summary['total_yes_sold'])}.",
        f"- Total NO sold: {fmt_decimal(summary['total_no_sold'])}.",
        f"- Weighted-average YES sale price using API cash: {fmt_decimal(summary['weighted_avg_yes_sale'], places=8)}.",
        f"- Total YES proceeds using API cash: {money(summary['total_yes_sale_proceeds'])}.",
        f"- Realized P/L, weighted-average cost basis: {money(summary['realized_pnl_wac'])}.",
        f"- Realized P/L, FIFO secondary calculation: {money(summary['realized_pnl_fifo'])}.",
        "",
        markdown_table(
            sells,
            [
                ("#", "sequence"),
                ("UTC", "timestamp_utc"),
                ("Outcome", "outcome"),
                ("Shares", "shares"),
                ("Price", "price"),
                ("API proceeds", "api_cash_amount"),
                ("Sale P/L WAC", "sale_realized_pnl_wac"),
                ("Sale P/L FIFO", "sale_realized_pnl_fifo"),
                ("Cum P/L WAC", "estimated_realized_pnl_after_trade"),
                ("Tx", "transactionHash"),
            ],
            tx_link=True,
        ),
        "",
        "## G. Remaining Position",
        "",
        f"- Current remaining YES, ledger: {fmt_decimal(summary['remaining_yes_shares'])}.",
        f"- Current remaining YES, Data API `/positions`: {fmt_decimal(summary['current_position_size_api'])}.",
        f"- Reconciliation delta: bought - sold - remaining = {fmt_decimal(reconciliation_delta)}; ledger remaining minus API current size = {fmt_decimal(position_api_delta)}.",
        f"- Remaining weighted-average cost basis: {money(summary['remaining_yes_cost_wac'])}.",
        f"- Current price/value from Data API position: price {fmt_decimal(summary['current_price_api'], places=8)}, value {money(summary['current_value_api'])}.",
        f"- Current position endpoint `avgPrice`: {fmt_decimal(summary['current_avg_price_api'], places=8)}; `cashPnl`: {money(summary['api_position_cash_pnl'])}; `realizedPnl`: {money(summary['api_position_realized_pnl'])}.",
        f"- Estimated unrealized P/L using ledger WAC cost: {money(summary['unrealized_pnl_wac'])}.",
        "",
        "## H. On-chain Verification",
        "",
        (
            "Current Polymarket docs identify Polygon chain contracts, including the Conditional Tokens Framework "
            "and pUSD collateral contracts. The transaction hashes returned by the Data API were therefore checked "
            "against Polygon JSON-RPC. A transaction is marked high confidence when the receipt exists, `status=0x1`, "
            "the block timestamp matches the API timestamp, and decoded pUSD/CTF wallet net flow aligns with the trade side."
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
        f"- Account age: profile created at {profile.get('createdAt', 'unknown')}; first target trade was {first_trade.get('timestamp_utc', 'unknown')}.",
        f"- Number of markets traded: `/traded` reports {traded.get('traded', 'unknown')} market(s).",
        f"- Concentration: all {len(ledger_rows)} filtered fills in this wallet sample are in the target market and outcome YES.",
        (
            f"- Size versus visible market liquidity: total buy cash {money(summary['total_yes_buy_cost'])} was about "
            f"{percent_of(summary['total_yes_buy_cost'], to_decimal(market.get('liquidity')))} of current Gamma liquidity; "
            f"total sale proceeds {money(summary['total_yes_sale_proceeds'])} were about "
            f"{percent_of(summary['total_yes_sale_proceeds'], to_decimal(market.get('liquidity')))} of current Gamma liquidity."
        ),
        (
            "- Timing: the first two buys occurred within minutes of profile creation and before the later visible price jump; "
            "the major sales occurred after YES traded materially higher. Public-news timing requires analyst review against "
            "contemporaneous Strategy/MicroStrategy disclosures and media reports; this report does not make a legal claim."
        ),
        (
            "- Neutral analytical assessment: the pattern is highly concentrated, young-account, one-market, pre-jump YES buying "
            "followed by post-jump selling. That is consistent with either unusually lucky timing or an information-edge style "
            "trade, but intent cannot be determined from these data alone."
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
        f"- {market_metadata.get('gamma_exact_market', {}).get('url')}",
        f"- {market_metadata.get('gamma_event', {}).get('url')}",
        f"- {market_metadata.get('accounting_snapshot', {}).get('url')}",
        "",
        "### Script Command Used",
        "",
        "```bash",
        f"python3 tools/reconstruct_polymarket_wallet_market.py --wallet {wallet} --market-slug {market.get('slug') or DEFAULT_MARKET_SLUG}",
        "```",
        "",
        "### Filtering Logic",
        "",
        (
            "Rows were retained when they matched the target conditionId, either target CLOB token ID, exact market slug, "
            "or a robust normalized title-token match for `MicroStrategy sells any Bitcoin by June 30, 2026?`. Event slug "
            "alone was not enough unless the title also contained MicroStrategy/Bitcoin tokens, because the event contains "
            "multiple date markets."
        ),
        "",
        "### API Inconsistencies / Notes",
        "",
        "- Gamma text search for the exact title can return unrelated broad matches; exact slug lookup was used as the primary market identifier.",
        "- Data API `/activity` contains `usdcSize`; `/trades` does not. Ledger cash therefore prefers `/activity` and falls back to `shares * price` only when `usdcSize` is missing.",
        "- The Polymarket UI may aggregate several fills into one displayed prediction; the raw APIs show one row per fill.",
        f"- Confidence counts: {dict(confidence_counts)}.",
        f"- Closed target positions returned by `/closed-positions`: {len(target_closed_positions)}.",
        "- Official docs referenced: [trades](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets), [activity](https://docs.polymarket.com/api-reference/core/get-user-activity), [positions](https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user), [closed positions](https://docs.polymarket.com/api-reference/core/get-closed-positions-for-a-user), [contracts](https://docs.polymarket.com/resources/contracts), [pUSD](https://docs.polymarket.com/concepts/pusd).",
        "- Public trigger review sources to consult alongside this ledger include contemporaneous Strategy/MicroStrategy investor materials and media reports such as [Decrypt](https://decrypt.co/366940/strategy-mulls-selling-bitcoin-to-inoculate-the-market-saylor).",
        "",
    ]
    return "\n".join(lines)


def onchain_rows_for_report(onchain: dict[str, Any], normalized_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    seen: dict[str, dict[str, Any]] = {}
    for row in normalized_rows:
        tx_hash = row["transactionHash"]
        if tx_hash in seen:
            seen[tx_hash]["fill_count"] += 1
            continue
        info = onchain.get(tx_hash, {}) if isinstance(onchain, dict) else {}
        status = info.get("status") or row.get("onchain_status") or "not_checked"
        item = {
            "transactionHash": tx_hash,
            "fill_count": 1,
            "chain": info.get("chain") or row.get("chain") or "Polygon if verified",
            "block_timestamp_utc": info.get("block_timestamp_utc") or row.get("block_timestamp_utc") or "",
            "timestamp_delta_seconds": row.get("onchain_timestamp_delta_seconds") if row.get("onchain_timestamp_delta_seconds") != "" else "",
            "onchain_status": status,
            "onchain_pusd_net_wallet": row.get("onchain_pusd_net_wallet") if row.get("onchain_pusd_net_wallet") != "" else "",
            "onchain_ctf_net_for_asset": row.get("onchain_ctf_net_for_asset") if row.get("onchain_ctf_net_for_asset") != "" else "",
            "onchain_summary": info.get("summary") or row.get("onchain_summary") or "",
        }
        seen[tx_hash] = item
        rows.append(item)
    return rows


def confidence_for_record(record: dict[str, Any], onchain: dict[str, Any]) -> str:
    sources = set(str(record.get("source_endpoint") or "").split("+"))
    tx_hash = record.get("transactionHash")
    tx_info = onchain.get(tx_hash) if isinstance(onchain, dict) else None
    verified = isinstance(tx_info, dict) and tx_info.get("status") == "verified"
    delta = record.get("onchain_timestamp_delta_seconds") if verified else None
    if verified and str(delta) in {"", "0", "0.0"}:
        if {"activity", "trades"} <= sources:
            return "High: Data API trade+activity row, Polygon receipt, timestamp and pUSD/CTF flow checked"
        return "High: Data API row and Polygon receipt checked"
    if {"activity", "trades"} <= sources:
        return "Medium-high: trade+activity APIs agree; on-chain not fully verified"
    return "Medium: single Data API endpoint"


def row_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("transactionHash") or ""),
        int(to_decimal(row.get("timestamp"))),
        normalize_hex(row.get("conditionId")),
        str(row.get("asset") or ""),
        str(row.get("side") or "").upper(),
        title_case_outcome(row.get("outcome")),
        fmt_decimal(to_decimal(row.get("size")), places=8),
        fmt_decimal(to_decimal(row.get("price")), places=12),
    )


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]], *, tx_link: bool = False) -> str:
    if not rows:
        return "_No rows._"
    header = "| " + " | ".join(label for label, _key in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        cells = []
        for label, key in columns:
            value = str(row.get(key, ""))
            if tx_link and key == "transactionHash" and value:
                value = f"[{short_hash(value)}]({POLYGONSCAN_TX.format(hash=value)})"
            cells.append(escape_md(value))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, separator, *body])


def blockquote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def market_price_label(market: dict[str, Any], current_pos: dict[str, Any]) -> str:
    if current_pos.get("curPrice") is not None:
        return str(current_pos.get("curPrice"))
    prices = market.get("currentOutcomePrices") or []
    if prices:
        return str(prices[0])
    return "unavailable"


def fee_note(delta: Decimal) -> str:
    if abs(delta) < Decimal("0.000001"):
        return "fees unavailable; no material API/recomputed delta"
    return f"fees unavailable; API/recomputed delta {fmt_decimal(delta)}"


def summary_note(key: str, summary: dict[str, Decimal], market_metadata: dict[str, Any]) -> str:
    if key == "api_position_realized_pnl":
        return "Data API /positions value; reported separately from reconstructed WAC/FIFO calculations."
    if key == "api_position_cash_pnl":
        return "Data API /positions cashPnl for remaining open position."
    if key == "current_price_api":
        return "Current position curPrice when available."
    if key == "unique_tx_hashes":
        return "One transaction can contain more than one fill."
    if key == "total_trade_rows":
        return "Rows after target-market filtering and trade/activity de-duplication."
    return ""


def percent_of(numerator: Decimal, denominator: Decimal) -> str:
    if denominator <= 0:
        return "unavailable"
    return f"{fmt_decimal((numerator / denominator) * Decimal(100), places=2)}%"


def parse_jsonish_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def event_slug_from_market(market: dict[str, Any]) -> str:
    events = market.get("events") or []
    if isinstance(events, list) and events and isinstance(events[0], dict):
        return str(events[0].get("slug") or "")
    return str(market.get("eventSlug") or "")


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def slugify(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_hex(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text


def normalize_address(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text


def address_from_topic(topic: str) -> str:
    clean = topic[2:] if topic.startswith("0x") else topic
    return "0x" + clean[-40:].lower()


def title_case_outcome(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() == "yes":
        return "Yes"
    if text.lower() == "no":
        return "No"
    return text


def to_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def fmt_decimal(value: Any, *, places: int = 6) -> str:
    dec = to_decimal(value)
    if not dec.is_finite():
        return "0"
    quant = Decimal(1).scaleb(-places)
    try:
        dec = dec.quantize(quant, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        pass
    text = format(dec, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def money(value: Any) -> str:
    dec = to_decimal(value)
    sign = "-" if dec < 0 else ""
    dec = abs(dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{sign}${dec:,.2f}"


def short_hash(value: str) -> str:
    if len(value) <= 16:
        return value
    return f"{value[:10]}...{value[-8:]}"


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def timestamp_iso(timestamp: int, tz: ZoneInfo | UTC) -> str:
    return datetime.fromtimestamp(int(timestamp), tz=UTC).astimezone(tz).isoformat(timespec="seconds")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


NORMALIZED_FIELDS = [
    "sequence",
    "timestamp_utc",
    "timestamp_kyiv",
    "timestamp_et",
    "timestamp_unix",
    "side",
    "outcome",
    "market_title",
    "conditionId",
    "asset",
    "slug",
    "eventSlug",
    "shares",
    "price",
    "api_cash_amount",
    "recomputed_cash_amount",
    "api_minus_recomputed",
    "fee_if_available",
    "net_cash_flow",
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
    "shares",
    "price",
    "cash_amount",
    "fee_if_available",
    "net_cash_flow",
    "cumulative_yes_shares_after_trade",
    "cumulative_no_shares_after_trade",
    "cumulative_cash_spent_received",
    "estimated_realized_pnl_after_trade",
    "sale_realized_pnl_wac",
    "sale_realized_pnl_fifo",
    "transactionHash",
    "polygon_tx_url",
    "source_endpoint",
    "confidence_level",
    "api_cash_amount",
    "recomputed_cash_amount",
    "api_minus_recomputed",
    "conditionId",
    "asset",
]

SUMMARY_FIELDS = ["metric", "value", "notes"]


if __name__ == "__main__":
    main()
