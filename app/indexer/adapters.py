from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence

from app.indexer.models import IndexedMarket, IndexedTrade, OrderbookSnapshot
from app.polymarket_protocol import UNKNOWN_PROTOCOL_VALUE, build_token_condition_map


def normalize_gamma_market(row: Mapping[str, object], *, updated_at: str = "") -> IndexedMarket:
    condition_id = _first_text(row, "conditionId", "condition_id")
    event_slug = _first_text(row, "eventSlug", "event_slug")
    if not event_slug:
        event_slug = _event_slug_from_events(row.get("events"))
    return IndexedMarket(
        condition_id=condition_id or UNKNOWN_PROTOCOL_VALUE,
        slug=_first_text(row, "slug") or UNKNOWN_PROTOCOL_VALUE,
        event_slug=event_slug or UNKNOWN_PROTOCOL_VALUE,
        question=_first_text(row, "question", "title") or UNKNOWN_PROTOCOL_VALUE,
        active=_bool_value(row.get("active")),
        closed=_bool_value(row.get("closed")),
        end_date=_first_text(row, "endDate", "end_date"),
        raw=dict(row),
        updated_at=updated_at,
    )


def token_condition_mapping_from_gamma_market(row: Mapping[str, object]) -> dict[str, object]:
    condition_id = _first_text(row, "conditionId", "condition_id")
    token_ids = _parse_jsonish_list(row.get("clobTokenIds") or row.get("token_ids"))
    outcomes = [str(item).strip().upper() for item in _parse_jsonish_list(row.get("outcomes"))]
    if not condition_id or len(token_ids) < 2:
        return {}
    yes_index = outcomes.index("YES") if "YES" in outcomes else 0
    no_index = outcomes.index("NO") if "NO" in outcomes else 1
    if yes_index >= len(token_ids) or no_index >= len(token_ids):
        return {}
    return build_token_condition_map(
        condition_id=condition_id,
        yes_token_id=str(token_ids[yes_index]),
        no_token_id=str(token_ids[no_index]),
    )


def normalize_data_trade(row: Mapping[str, object], *, source: str = "data_api") -> IndexedTrade:
    condition_id = _first_text(row, "conditionId", "condition_id", "market")
    token_id = _first_text(row, "asset", "asset_id", "token_id")
    wallet = _first_text(row, "proxyWallet", "wallet", "user").lower()
    side = _first_text(row, "side", "order_side").upper()
    outcome = _first_text(row, "outcome", "direction")
    size = _decimal_text(_first_decimal(row, "size", "shares", "amount"))
    price = _decimal_text(_first_decimal(row, "price", "avg_price", "average_price"))
    usdc_size = _optional_decimal_text(_first_decimal(row, "usdcSize", "usdc_size", "api_usdc_size", "api_cash_amount"))
    timestamp = _first_text(row, "timestamp_utc", "timestamp", "created_at")
    transaction_hash = _first_text(row, "transactionHash", "transaction_hash", "txHash", "tx_hash")
    order_hash = _first_text(row, "orderHash", "order_hash")
    normalized = IndexedTrade(
        stable_trade_id=stable_data_trade_id(row, source=source),
        transaction_hash=transaction_hash,
        order_hash=order_hash,
        condition_id=condition_id or UNKNOWN_PROTOCOL_VALUE,
        token_id=token_id or UNKNOWN_PROTOCOL_VALUE,
        wallet=wallet or UNKNOWN_PROTOCOL_VALUE,
        side=side or UNKNOWN_PROTOCOL_VALUE,
        outcome=outcome or UNKNOWN_PROTOCOL_VALUE,
        size=size,
        price=price,
        usdc_size=usdc_size,
        timestamp=timestamp or UNKNOWN_PROTOCOL_VALUE,
        source=source,
        raw=dict(row),
    )
    return normalized


def stable_data_trade_id(row: Mapping[str, object], *, source: str = "data_api") -> str:
    transaction_hash = _first_text(row, "transactionHash", "transaction_hash", "txHash", "tx_hash")
    order_hash = _first_text(row, "orderHash", "order_hash")
    log_index = _first_text(row, "logIndex", "log_index")
    if transaction_hash and log_index:
        return f"{source}:{transaction_hash}:{log_index}"
    parts = [
        source,
        transaction_hash or order_hash or UNKNOWN_PROTOCOL_VALUE,
        _first_text(row, "conditionId", "condition_id", "market") or UNKNOWN_PROTOCOL_VALUE,
        _first_text(row, "asset", "asset_id", "token_id") or UNKNOWN_PROTOCOL_VALUE,
        _first_text(row, "side", "order_side").upper() or UNKNOWN_PROTOCOL_VALUE,
        _first_text(row, "outcome", "direction") or UNKNOWN_PROTOCOL_VALUE,
        _first_text(row, "timestamp_utc", "timestamp", "created_at") or UNKNOWN_PROTOCOL_VALUE,
        _decimal_text(_first_decimal(row, "size", "shares", "amount")),
        _decimal_text(_first_decimal(row, "price", "avg_price", "average_price")),
    ]
    return ":".join(parts)


def normalize_orderbook_snapshot(
    row: Mapping[str, object],
    *,
    token_id: str,
    condition_id: str,
    timestamp: str,
) -> OrderbookSnapshot:
    bids = _levels(row.get("bids") or row.get("buy") or row.get("book_bids"))
    asks = _levels(row.get("asks") or row.get("sell") or row.get("book_asks"))
    best_bid = max((price for price, _size in bids), default=None)
    best_ask = min((price for price, _size in asks), default=None)
    bid_depth = sum((size for _price, size in bids), Decimal("0"))
    ask_depth = sum((size for _price, size in asks), Decimal("0"))
    spread_bps = None
    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / Decimal("2")
        if mid > 0:
            spread_bps = ((best_ask - best_bid) / mid) * Decimal("10000")
    liquidity_imbalance = None
    if bid_depth + ask_depth > 0:
        liquidity_imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
    return OrderbookSnapshot(
        token_id=str(token_id),
        condition_id=str(condition_id),
        timestamp=str(timestamp),
        best_bid=_optional_decimal_text(best_bid),
        best_ask=_optional_decimal_text(best_ask),
        spread_bps=_optional_decimal_text(spread_bps, places=Decimal("0.000001")),
        bid_depth=_optional_decimal_text(bid_depth),
        ask_depth=_optional_decimal_text(ask_depth),
        liquidity_imbalance=_optional_decimal_text(liquidity_imbalance, places=Decimal("0.000001")),
        raw=dict(row),
    )


def _levels(value: object) -> tuple[tuple[Decimal, Decimal], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    levels: list[tuple[Decimal, Decimal]] = []
    for item in value:
        price: Decimal | None = None
        size: Decimal | None = None
        if isinstance(item, Mapping):
            price = _optional_decimal(item.get("price") or item.get("p"))
            size = _optional_decimal(item.get("size") or item.get("s"))
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)) and len(item) >= 2:
            price = _optional_decimal(item[0])
            size = _optional_decimal(item[1])
        if price is not None and size is not None:
            levels.append((price, size))
    return tuple(levels)


def _first_text(row: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _first_decimal(row: Mapping[str, object], *keys: str) -> Decimal | None:
    for key in keys:
        value = _optional_decimal(row.get(key))
        if value is not None:
            return value
    return None


def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _decimal_text(value: Decimal | None) -> str:
    return _optional_decimal_text(value) if value is not None else UNKNOWN_PROTOCOL_VALUE


def _optional_decimal_text(value: Decimal | None, *, places: Decimal | None = None) -> str | None:
    if value is None:
        return None
    if places is not None:
        value = value.quantize(places)
    return format(value.normalize(), "f")


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _parse_jsonish_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _event_slug_from_events(value: object) -> str:
    if not isinstance(value, list):
        return ""
    for item in value:
        if isinstance(item, Mapping):
            slug = str(item.get("slug") or "").strip()
            if slug:
                return slug
    return ""
