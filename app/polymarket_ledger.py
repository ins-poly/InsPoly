from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.polymarket_protocol import LedgerPosition, UNKNOWN_PROTOCOL_VALUE, apply_ledger_fill


QUALITY_MISSING_CASH_FIELD = "missing_cash_field"
QUALITY_UNKNOWN_CASH_SOURCE = "unknown_cash_source"
QUALITY_SELL_EXCEEDS_TRACKED_HOLDINGS = "sell_exceeds_tracked_holdings"
QUALITY_CURRENT_PRICE_UNAVAILABLE = "current_price_unavailable"
QUALITY_POSITION_RECONCILIATION_MISMATCH = "position_reconciliation_mismatch"
QUALITY_SOURCE_CASH_DISAGREEMENT = "source_cash_disagreement"
QUALITY_UNKNOWN_SIDE = "unknown_side"
QUALITY_MISSING_SIZE_FIELD = "missing_size_field"

CASH_SOURCE_USDC_SIZE = "usdcSize"
CASH_SOURCE_SIZE_PRICE = "size_price"
CASH_SOURCE_UNKNOWN = "unknown"

DEFAULT_RECONCILIATION_TOLERANCE = Decimal("0.000001")
DEFAULT_CASH_DISAGREEMENT_TOLERANCE = Decimal("0.000001")

_EXPLICIT_CASH_KEYS = (
    "usdcSize",
    "usdc_size",
    "api_usdc_size",
    "api_cash_amount",
    "cash_amount",
)
_SIZE_KEYS = ("size", "shares", "amount")
_PRICE_KEYS = ("price", "avg_price", "average_price")


@dataclass(frozen=True, slots=True)
class LedgerKey:
    wallet: str
    condition_id: str
    token_id: str
    outcome: str


@dataclass(frozen=True, slots=True)
class NormalizedLedgerTrade:
    key: LedgerKey
    side: str
    size: Decimal
    price: Decimal | None
    explicit_cash: Decimal | None
    size_price_cash: Decimal | None
    cash: Decimal | None
    cash_source: str
    effective_price: Decimal | None
    quality_notes: tuple[str, ...]
    raw: Mapping[str, object]
    input_index: int
    sort_key: tuple[int, Decimal | str, int]


@dataclass(frozen=True, slots=True)
class PositionLedger:
    key: LedgerKey
    total_bought_shares: Decimal
    requested_sold_shares: Decimal
    total_sold_shares: Decimal
    ignored_sell_shares: Decimal
    remaining_shares: Decimal
    total_buy_cash: Decimal | None
    total_sell_cash: Decimal | None
    weighted_average_entry: Decimal | None
    realized_pnl: Decimal | None
    unrealized_pnl: Decimal | None
    total_pnl: Decimal | None
    current_price: Decimal | None
    expected_remaining_shares: Decimal | None
    cash_sources: tuple[str, ...]
    source_cash_disagreement_count: int
    quality_notes: tuple[str, ...]
    raw_trade_count: int


@dataclass(frozen=True, slots=True)
class LedgerBook:
    positions: tuple[PositionLedger, ...]
    quality_notes: tuple[str, ...]

    def get(
        self,
        *,
        wallet: str,
        condition_id: str,
        token_id: str,
        outcome: str = UNKNOWN_PROTOCOL_VALUE,
    ) -> PositionLedger | None:
        key = LedgerKey(
            wallet=str(wallet),
            condition_id=str(condition_id),
            token_id=str(token_id),
            outcome=str(outcome),
        )
        for position in self.positions:
            if position.key == key:
                return position
        return None


@dataclass
class _LedgerAccumulator:
    key: LedgerKey
    protocol_position: LedgerPosition = field(default_factory=LedgerPosition)
    calculation_known: bool = True
    remaining_shares: Decimal = Decimal("0")
    total_bought_shares: Decimal = Decimal("0")
    requested_sold_shares: Decimal = Decimal("0")
    total_sold_shares: Decimal = Decimal("0")
    ignored_sell_shares: Decimal = Decimal("0")
    total_buy_cash_value: Decimal = Decimal("0")
    total_sell_cash_value: Decimal = Decimal("0")
    total_buy_cash_known: bool = True
    total_sell_cash_known: bool = True
    quality_notes: set[str] = field(default_factory=set)
    cash_sources: set[str] = field(default_factory=set)
    source_cash_disagreement_count: int = 0
    raw_trade_count: int = 0


def normalize_ledger_trade(
    row: Mapping[str, object],
    *,
    input_index: int = 0,
    cash_disagreement_tolerance: Decimal = DEFAULT_CASH_DISAGREEMENT_TOLERANCE,
) -> NormalizedLedgerTrade:
    wallet = _first_text(row, ("wallet", "proxyWallet", "proxy_wallet", "user"))
    condition_id = _first_text(row, ("condition_id", "conditionId", "market", "market_id"))
    token_id = _first_text(row, ("token_id", "asset_id", "asset"))
    outcome = _first_text(row, ("outcome", "direction"))
    side = _first_text(row, ("side", "order_side")).upper()
    notes: set[str] = set()
    if side not in {"BUY", "SELL"}:
        notes.add(QUALITY_UNKNOWN_SIDE)

    size = _optional_decimal(_first_present(row, _SIZE_KEYS))
    if size is None:
        size = Decimal("0")
        notes.add(QUALITY_MISSING_SIZE_FIELD)
    price = _optional_decimal(_first_present(row, _PRICE_KEYS))
    explicit_cash = _optional_decimal(_first_present(row, _EXPLICIT_CASH_KEYS))
    size_price_cash = size * price if price is not None else None

    if explicit_cash is not None:
        cash = explicit_cash
        cash_source = CASH_SOURCE_USDC_SIZE
        effective_price = cash / size if size > 0 else price
        if (
            size_price_cash is not None
            and abs(explicit_cash - size_price_cash) > cash_disagreement_tolerance
        ):
            notes.add(QUALITY_SOURCE_CASH_DISAGREEMENT)
    elif size_price_cash is not None:
        cash = size_price_cash
        cash_source = CASH_SOURCE_SIZE_PRICE
        effective_price = price
        notes.add(QUALITY_MISSING_CASH_FIELD)
    else:
        cash = None
        cash_source = CASH_SOURCE_UNKNOWN
        effective_price = None
        notes.update({QUALITY_MISSING_CASH_FIELD, QUALITY_UNKNOWN_CASH_SOURCE})

    return NormalizedLedgerTrade(
        key=LedgerKey(
            wallet=wallet or UNKNOWN_PROTOCOL_VALUE,
            condition_id=condition_id or UNKNOWN_PROTOCOL_VALUE,
            token_id=token_id or UNKNOWN_PROTOCOL_VALUE,
            outcome=outcome or UNKNOWN_PROTOCOL_VALUE,
        ),
        side=side,
        size=size,
        price=price,
        explicit_cash=explicit_cash,
        size_price_cash=size_price_cash,
        cash=cash,
        cash_source=cash_source,
        effective_price=effective_price,
        quality_notes=tuple(sorted(notes)),
        raw=row,
        input_index=input_index,
        sort_key=_row_sort_key(row, input_index),
    )


def build_position_ledgers(
    rows: Sequence[Mapping[str, object]],
    *,
    current_prices: Mapping[object, object] | None = None,
    expected_positions: Mapping[object, object] | None = None,
    reconciliation_tolerance: Decimal = DEFAULT_RECONCILIATION_TOLERANCE,
    cash_disagreement_tolerance: Decimal = DEFAULT_CASH_DISAGREEMENT_TOLERANCE,
) -> LedgerBook:
    normalized = [
        normalize_ledger_trade(
            row,
            input_index=index,
            cash_disagreement_tolerance=cash_disagreement_tolerance,
        )
        for index, row in enumerate(rows)
    ]
    normalized.sort(key=lambda item: item.sort_key)

    accumulators: dict[LedgerKey, _LedgerAccumulator] = {}
    for trade in normalized:
        accumulator = accumulators.setdefault(trade.key, _LedgerAccumulator(trade.key))
        _apply_trade(accumulator, trade)

    positions = tuple(
        _finalize_position(
            accumulator,
            current_prices=current_prices or {},
            expected_positions=expected_positions or {},
            reconciliation_tolerance=reconciliation_tolerance,
        )
        for accumulator in sorted(
            accumulators.values(),
            key=lambda item: (
                item.key.wallet,
                item.key.condition_id,
                item.key.token_id,
                item.key.outcome,
            ),
        )
    )
    quality_notes = tuple(sorted({note for position in positions for note in position.quality_notes}))
    return LedgerBook(positions=positions, quality_notes=quality_notes)


def _apply_trade(accumulator: _LedgerAccumulator, trade: NormalizedLedgerTrade) -> None:
    accumulator.raw_trade_count += 1
    accumulator.cash_sources.add(trade.cash_source)
    accumulator.quality_notes.update(trade.quality_notes)
    if QUALITY_SOURCE_CASH_DISAGREEMENT in trade.quality_notes:
        accumulator.source_cash_disagreement_count += 1

    if trade.side == "BUY":
        accumulator.total_bought_shares += trade.size
        accumulator.remaining_shares += trade.size
        if trade.cash is None or trade.effective_price is None:
            accumulator.total_buy_cash_known = False
            accumulator.calculation_known = False
            return
        accumulator.total_buy_cash_value += trade.cash
        if accumulator.calculation_known:
            update = apply_ledger_fill(
                accumulator.protocol_position,
                side="BUY",
                amount=trade.size,
                price=trade.effective_price,
            )
            accumulator.protocol_position = update.position
        return

    if trade.side == "SELL":
        accumulator.requested_sold_shares += trade.size
        adjusted_amount = min(trade.size, accumulator.remaining_shares)
        ignored_amount = trade.size - adjusted_amount
        accumulator.remaining_shares -= adjusted_amount
        accumulator.total_sold_shares += adjusted_amount
        accumulator.ignored_sell_shares += ignored_amount
        if ignored_amount > 0:
            accumulator.quality_notes.add(QUALITY_SELL_EXCEEDS_TRACKED_HOLDINGS)

        if trade.cash is None or trade.effective_price is None:
            accumulator.total_sell_cash_known = False
            accumulator.calculation_known = False
            return
        accumulator.total_sell_cash_value += trade.effective_price * adjusted_amount
        if accumulator.calculation_known:
            update = apply_ledger_fill(
                accumulator.protocol_position,
                side="SELL",
                amount=trade.size,
                price=trade.effective_price,
            )
            accumulator.protocol_position = update.position
        return

    accumulator.calculation_known = False


def _finalize_position(
    accumulator: _LedgerAccumulator,
    *,
    current_prices: Mapping[object, object],
    expected_positions: Mapping[object, object],
    reconciliation_tolerance: Decimal,
) -> PositionLedger:
    notes = set(accumulator.quality_notes)
    key = accumulator.key
    current_price = _lookup_decimal(current_prices, key)
    expected_remaining = _lookup_decimal(expected_positions, key)

    if expected_remaining is not None and abs(accumulator.remaining_shares - expected_remaining) > reconciliation_tolerance:
        notes.add(QUALITY_POSITION_RECONCILIATION_MISMATCH)

    if accumulator.calculation_known:
        weighted_average_entry: Decimal | None = (
            accumulator.protocol_position.avg_price
            if accumulator.protocol_position.amount > 0
            else Decimal("0")
        )
        realized_pnl: Decimal | None = accumulator.protocol_position.realized_pnl
    else:
        weighted_average_entry = None
        realized_pnl = None

    if accumulator.remaining_shares > 0:
        if current_price is None:
            unrealized_pnl = None
            notes.add(QUALITY_CURRENT_PRICE_UNAVAILABLE)
        elif weighted_average_entry is None:
            unrealized_pnl = None
        else:
            unrealized_pnl = (current_price - weighted_average_entry) * accumulator.remaining_shares
    else:
        unrealized_pnl = Decimal("0") if accumulator.calculation_known else None

    total_pnl = (
        realized_pnl + unrealized_pnl
        if realized_pnl is not None and unrealized_pnl is not None
        else None
    )

    return PositionLedger(
        key=key,
        total_bought_shares=accumulator.total_bought_shares,
        requested_sold_shares=accumulator.requested_sold_shares,
        total_sold_shares=accumulator.total_sold_shares,
        ignored_sell_shares=accumulator.ignored_sell_shares,
        remaining_shares=accumulator.remaining_shares,
        total_buy_cash=(
            accumulator.total_buy_cash_value
            if accumulator.total_buy_cash_known or accumulator.total_bought_shares == 0
            else None
        ),
        total_sell_cash=(
            accumulator.total_sell_cash_value
            if accumulator.total_sell_cash_known or accumulator.requested_sold_shares == 0
            else None
        ),
        weighted_average_entry=weighted_average_entry,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_pnl=total_pnl,
        current_price=current_price,
        expected_remaining_shares=expected_remaining,
        cash_sources=tuple(sorted(accumulator.cash_sources)),
        source_cash_disagreement_count=accumulator.source_cash_disagreement_count,
        quality_notes=tuple(sorted(notes)),
        raw_trade_count=accumulator.raw_trade_count,
    )


def _lookup_decimal(values: Mapping[object, object], key: LedgerKey) -> Decimal | None:
    value = _lookup_value(values, key)
    return _optional_decimal(value)


def _lookup_value(values: Mapping[object, object], key: LedgerKey) -> object | None:
    candidates: tuple[object, ...] = (
        key,
        (key.wallet, key.condition_id, key.token_id, key.outcome),
        (key.wallet, key.condition_id, key.token_id),
        (key.condition_id, key.token_id, key.outcome),
        (key.condition_id, key.token_id),
        key.token_id,
    )
    for candidate in candidates:
        if candidate in values:
            return values[candidate]
    return None


def _first_text(row: Mapping[str, object], keys: Sequence[str]) -> str:
    value = _first_present(row, keys)
    return str(value).strip() if value is not None else ""


def _first_present(row: Mapping[str, object], keys: Sequence[str]) -> object | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _row_sort_key(row: Mapping[str, object], input_index: int) -> tuple[int, Decimal | str, int]:
    timestamp = _first_present(row, ("timestamp", "timestamp_unix", "timestamp_utc", "created_at"))
    if timestamp is None:
        return (2, "", input_index)
    numeric = _optional_decimal(timestamp)
    if numeric is not None:
        return (0, numeric, input_index)
    return (1, str(timestamp), input_index)
