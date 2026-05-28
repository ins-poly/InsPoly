from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal


CLOB_INITIAL_CURSOR = "MA=="
CLOB_END_CURSOR = "LTE="
UNKNOWN_PROTOCOL_VALUE = "unknown"
ZERO_ASSET_ID = "0"


@dataclass(slots=True)
class ClobPageCollection:
    rows: list[Mapping[str, object]]
    page_count: int
    cursors: list[str]
    next_cursor: str
    stopped_reason: str


@dataclass(frozen=True, slots=True)
class TokenConditionMapping:
    condition_id: str
    outcome: str


@dataclass(frozen=True, slots=True)
class InterpretedOrderFill:
    side: str
    token_id: str
    base_amount: Decimal
    quote_amount: Decimal
    price: Decimal
    stable_trade_id: str
    raw: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class LedgerPosition:
    amount: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    total_bought: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class LedgerUpdate:
    position: LedgerPosition
    adjusted_amount: Decimal
    ignored_amount: Decimal
    realized_pnl_delta: Decimal


@dataclass(frozen=True, slots=True)
class PnlDisplay:
    position_status: str
    source: str
    pnl: Decimal | None
    pnl_percent: Decimal | None


def collect_clob_cursor_pages(
    fetch_page: Callable[[str], Mapping[str, object]],
    *,
    initial_cursor: str = CLOB_INITIAL_CURSOR,
    max_pages: int = 100,
) -> ClobPageCollection:
    """Collect CLOB cursor pages without normalizing away raw row fields."""

    if max_pages <= 0:
        raise ValueError("max_pages must be positive")

    cursor = initial_cursor
    seen_cursors: set[str] = set()
    cursors: list[str] = []
    rows: list[Mapping[str, object]] = []
    next_cursor = cursor

    for _page_index in range(max_pages):
        if cursor in seen_cursors:
            return ClobPageCollection(
                rows=rows,
                page_count=len(cursors),
                cursors=cursors,
                next_cursor=cursor,
                stopped_reason="repeated_cursor",
            )
        seen_cursors.add(cursor)
        cursors.append(cursor)

        payload = fetch_page(cursor)
        page_rows = payload.get("data", [])
        if not isinstance(page_rows, list):
            raise TypeError("CLOB page payload must expose a list under data")
        for row in page_rows:
            if not isinstance(row, Mapping):
                raise TypeError("CLOB page rows must be mappings")
            rows.append(row)

        next_cursor = str(payload.get("next_cursor") or "")
        if _cursor_is_terminal(next_cursor):
            return ClobPageCollection(
                rows=rows,
                page_count=len(cursors),
                cursors=cursors,
                next_cursor=next_cursor,
                stopped_reason="end_cursor",
            )
        if next_cursor in seen_cursors:
            return ClobPageCollection(
                rows=rows,
                page_count=len(cursors),
                cursors=cursors,
                next_cursor=next_cursor,
                stopped_reason="repeated_cursor",
            )
        cursor = next_cursor

    return ClobPageCollection(
        rows=rows,
        page_count=len(cursors),
        cursors=cursors,
        next_cursor=next_cursor,
        stopped_reason="max_pages_reached",
    )


def build_market_socket_subscription(
    asset_ids: Sequence[str],
    *,
    initial_dump: bool = True,
    custom_feature_enabled: bool = True,
) -> dict[str, object]:
    return {
        "type": "market",
        "assets_ids": [str(asset_id) for asset_id in asset_ids],
        "initial_dump": bool(initial_dump),
        "custom_feature_enabled": bool(custom_feature_enabled),
    }


def build_user_socket_subscription_shape(condition_ids: Sequence[str]) -> dict[str, object]:
    return {
        "type": "user",
        "markets": [str(condition_id) for condition_id in condition_ids],
        "auth": {
            "apiKey": "<api-key>",
            "secret": "<api-secret>",
            "passphrase": "<api-passphrase>",
        },
    }


def build_token_condition_map(
    *,
    condition_id: str,
    yes_token_id: str,
    no_token_id: str,
) -> dict[str, TokenConditionMapping]:
    mapping: dict[str, TokenConditionMapping] = {}
    if yes_token_id:
        mapping[str(yes_token_id)] = TokenConditionMapping(str(condition_id), "YES")
    if no_token_id:
        mapping[str(no_token_id)] = TokenConditionMapping(str(condition_id), "NO")
    return mapping


def token_mapping_for_token_id(
    token_id: str,
    mapping: Mapping[str, TokenConditionMapping],
) -> TokenConditionMapping:
    return mapping.get(
        str(token_id),
        TokenConditionMapping(UNKNOWN_PROTOCOL_VALUE, UNKNOWN_PROTOCOL_VALUE),
    )


def interpret_order_filled(event: Mapping[str, object]) -> InterpretedOrderFill:
    maker_asset_id = str(event.get("makerAssetId") or "")
    taker_asset_id = str(event.get("takerAssetId") or "")
    maker_amount = _to_decimal(event.get("makerAmountFilled"))
    taker_amount = _to_decimal(event.get("takerAmountFilled"))

    if maker_asset_id == ZERO_ASSET_ID:
        side = "BUY"
        token_id = taker_asset_id
        base_amount = taker_amount
        quote_amount = maker_amount
    else:
        side = "SELL"
        token_id = maker_asset_id
        base_amount = maker_amount
        quote_amount = taker_amount

    price = quote_amount / base_amount if base_amount > 0 else Decimal("0")
    return InterpretedOrderFill(
        side=side,
        token_id=token_id,
        base_amount=base_amount,
        quote_amount=quote_amount,
        price=price,
        stable_trade_id=stable_order_fill_trade_id(event),
        raw=event,
    )


def stable_order_fill_trade_id(event: Mapping[str, object]) -> str:
    transaction_hash = str(event.get("transactionHash") or event.get("transaction_hash") or "").strip()
    log_index = str(event.get("logIndex") or event.get("log_index") or "").strip()
    order_hash = str(event.get("orderHash") or event.get("order_hash") or "").strip()
    if transaction_hash and log_index:
        return f"{transaction_hash}:{log_index}"
    if transaction_hash and order_hash:
        return f"{transaction_hash}:{order_hash}"
    if order_hash:
        return order_hash
    return UNKNOWN_PROTOCOL_VALUE


def apply_ledger_fill(
    position: LedgerPosition,
    *,
    side: str,
    amount: Decimal | str | int | float,
    price: Decimal | str | int | float,
) -> LedgerUpdate:
    normalized_side = str(side or "").upper()
    amount_decimal = _to_decimal(amount)
    price_decimal = _to_decimal(price)
    if amount_decimal < 0:
        raise ValueError("amount must be non-negative")
    if price_decimal < 0:
        raise ValueError("price must be non-negative")
    if normalized_side == "BUY":
        return _apply_buy(position, amount_decimal, price_decimal)
    if normalized_side == "SELL":
        return _apply_sell(position, amount_decimal, price_decimal)
    raise ValueError("side must be BUY or SELL")


def pnl_display(
    position: LedgerPosition,
    *,
    current_price: Decimal | str | int | float | None = None,
) -> PnlDisplay:
    if position.amount > 0:
        if current_price is None or position.avg_price <= 0:
            return PnlDisplay("open", UNKNOWN_PROTOCOL_VALUE, None, None)
        current_price_decimal = _to_decimal(current_price)
        cost_basis = position.avg_price * position.amount
        pnl = (current_price_decimal - position.avg_price) * position.amount
        return PnlDisplay("open", "unrealized", pnl, _capped_loss_percent(pnl, cost_basis))

    percent = (
        _capped_loss_percent(position.realized_pnl, position.total_bought)
        if position.total_bought > 0
        else None
    )
    return PnlDisplay("closed", "realized", position.realized_pnl, percent)


def _apply_buy(
    position: LedgerPosition,
    amount: Decimal,
    price: Decimal,
) -> LedgerUpdate:
    new_amount = position.amount + amount
    previous_cost = position.avg_price * position.amount
    added_cost = price * amount
    avg_price = (previous_cost + added_cost) / new_amount if new_amount > 0 else Decimal("0")
    return LedgerUpdate(
        position=LedgerPosition(
            amount=new_amount,
            avg_price=avg_price,
            realized_pnl=position.realized_pnl,
            total_bought=position.total_bought + added_cost,
        ),
        adjusted_amount=amount,
        ignored_amount=Decimal("0"),
        realized_pnl_delta=Decimal("0"),
    )


def _apply_sell(
    position: LedgerPosition,
    amount: Decimal,
    price: Decimal,
) -> LedgerUpdate:
    adjusted_amount = min(amount, position.amount)
    ignored_amount = amount - adjusted_amount
    realized_delta = adjusted_amount * (price - position.avg_price)
    remaining_amount = position.amount - adjusted_amount
    return LedgerUpdate(
        position=LedgerPosition(
            amount=remaining_amount,
            avg_price=position.avg_price if remaining_amount > 0 else Decimal("0"),
            realized_pnl=position.realized_pnl + realized_delta,
            total_bought=position.total_bought,
        ),
        adjusted_amount=adjusted_amount,
        ignored_amount=ignored_amount,
        realized_pnl_delta=realized_delta,
    )


def _capped_loss_percent(pnl: Decimal, cost_basis: Decimal) -> Decimal | None:
    if cost_basis <= 0:
        return None
    return max((pnl / cost_basis) * Decimal("100"), Decimal("-100"))


def _cursor_is_terminal(cursor: str) -> bool:
    return cursor in {"", CLOB_END_CURSOR}


def _to_decimal(value: object) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))
