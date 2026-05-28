from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from app.polymarket_ledger import (
    QUALITY_CURRENT_PRICE_UNAVAILABLE,
    build_position_ledgers,
)
from app.polymarket_protocol import UNKNOWN_PROTOCOL_VALUE


SHADOW_LOW_ODDS_POSITION_SIZE = "shadow_low_odds_position_size"
SHADOW_ENTRY_PRICE_EDGE = "shadow_entry_price_edge"
SHADOW_NET_POSITION_PNL = "shadow_net_position_pnl"
SHADOW_WIN_RATE_CONFIDENCE = "shadow_win_rate_confidence"
SHADOW_MICROSTRUCTURE_CONTEXT = "shadow_microstructure_context"
SHADOW_TIMING_CONTEXT = "shadow_timing_context"
SHADOW_STRUCTURAL_CONTEXT = "shadow_structural_context"
SHADOW_PUBLIC_VOLUME_CAUTION = "shadow_public_volume_caution"

STATUS_AVAILABLE = "available"
STATUS_NOT_TRIGGERED = "not_triggered"
STATUS_UNKNOWN = "unknown"

ADVISORY_NONE = "none"
ADVISORY_CONTEXT = "context"
ADVISORY_NOTABLE = "notable"

LOW_ODDS_PRICE_CEILING = Decimal("0.15")
LOW_ODDS_NOTIONAL_CONTEXT = Decimal("1000")
LOW_ODDS_NOTIONAL_NOTABLE = Decimal("5000")
ENTRY_EDGE_CONTEXT = Decimal("0.05")
WIN_RATE_BASELINE = Decimal("0.5")
WIN_RATE_CONTEXT = Decimal("0.1")
MICROSTRUCTURE_WIDE_SPREAD_BPS = Decimal("500")
MICROSTRUCTURE_LOW_DEPTH = Decimal("100")
MICROSTRUCTURE_IMBALANCE = Decimal("0.5")

PRODUCTION_FIELD_DENYLIST = {
    "risk_level",
    "riskLevel",
    "Strong Risk",
    "strongRisk",
    "Hard Evidence Review",
    "hardEvidenceReview",
    "candidateAdmission",
    "candidate_admission",
    "severity",
}


@dataclass(frozen=True, slots=True)
class ShadowMetric:
    name: str
    status: str
    advisory_level: str
    value: str | None = None
    notes: tuple[str, ...] = ()
    details: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "advisoryLevel": self.advisory_level,
            "value": self.value,
            "notes": list(self.notes),
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ShadowMetricsReport:
    metrics: tuple[ShadowMetric, ...]
    quality_notes: tuple[str, ...]
    network_used: bool = False
    production_integration: bool = False

    def metric(self, name: str) -> ShadowMetric:
        for metric in self.metrics:
            if metric.name == name:
                return metric
        raise KeyError(name)

    def to_dict(self) -> dict[str, object]:
        return {
            "shadowMetrics": [metric.to_dict() for metric in self.metrics],
            "qualityNotes": list(self.quality_notes),
            "networkUsed": self.network_used,
            "productionIntegration": self.production_integration,
        }


def compute_shadow_metrics(
    trades: Sequence[Mapping[str, object]],
    *,
    wallet_stats: Mapping[str, object] | None = None,
    current_prices: Mapping[object, object] | None = None,
    microstructure: Sequence[Mapping[str, object]] | None = None,
) -> ShadowMetricsReport:
    rows = tuple(trades)
    metrics = (
        _low_odds_position_size(rows),
        _entry_price_edge(rows),
        _net_position_pnl(rows, current_prices or {}),
        _win_rate_confidence(wallet_stats or {}),
        _microstructure_context(tuple(microstructure or ())),
        _timing_context(rows),
        _structural_context(rows),
        _public_volume_caution(wallet_stats or {}),
    )
    quality_notes = tuple(sorted({note for metric in metrics for note in metric.notes}))
    return ShadowMetricsReport(metrics=metrics, quality_notes=quality_notes)


def compute_shadow_metrics_from_payload(payload: Mapping[str, object]) -> ShadowMetricsReport:
    trades = payload.get("trades")
    wallet_stats = payload.get("wallet_stats") or payload.get("walletStats")
    current_prices = payload.get("current_prices") or payload.get("currentPrices")
    microstructure = payload.get("microstructure") or payload.get("orderbooks") or payload.get("orderbookSnapshots")
    return compute_shadow_metrics(
        trades if isinstance(trades, list) else [],
        wallet_stats=wallet_stats if isinstance(wallet_stats, Mapping) else {},
        current_prices=current_prices if isinstance(current_prices, Mapping) else {},
        microstructure=microstructure if isinstance(microstructure, list) else [],
    )


def assert_no_production_fields(payload: Mapping[str, object]) -> None:
    found = _find_denied_keys(payload)
    if found:
        raise ValueError(f"Shadow metric payload contains production field(s): {', '.join(sorted(found))}")


def _low_odds_position_size(rows: Sequence[Mapping[str, object]]) -> ShadowMetric:
    notes: set[str] = set()
    low_odds_cash = Decimal("0")
    low_odds_count = 0
    max_price: Decimal | None = None
    for row in rows:
        side = _text(row.get("side") or row.get("order_side")).upper()
        if side and side != "BUY":
            continue
        price = _decimal(row.get("price") or row.get("avg_price") or row.get("average_price"))
        cash = _cash(row)
        if _truthy(row.get("stale_resolution") or row.get("staleResolution")):
            notes.add("stale_resolution_context_only")
            continue
        if price is None or cash is None:
            notes.add("missing_low_odds_inputs_unknown")
            continue
        if price >= Decimal("0.85"):
            notes.add("near_certainty_context_only")
            continue
        if price <= LOW_ODDS_PRICE_CEILING:
            low_odds_cash += cash
            low_odds_count += 1
            max_price = price if max_price is None else max(max_price, price)
    if low_odds_count == 0:
        status = STATUS_UNKNOWN if "missing_low_odds_inputs_unknown" in notes and rows else STATUS_NOT_TRIGGERED
        return ShadowMetric(
            SHADOW_LOW_ODDS_POSITION_SIZE,
            status,
            ADVISORY_NONE,
            None,
            tuple(sorted(notes)),
            {"tradeCount": 0},
        )
    advisory = ADVISORY_NOTABLE if low_odds_cash >= LOW_ODDS_NOTIONAL_NOTABLE else ADVISORY_CONTEXT
    if low_odds_cash < LOW_ODDS_NOTIONAL_CONTEXT:
        advisory = ADVISORY_NONE
    return ShadowMetric(
        SHADOW_LOW_ODDS_POSITION_SIZE,
        STATUS_AVAILABLE,
        advisory,
        _decimal_text(low_odds_cash),
        tuple(sorted(notes)),
        {"tradeCount": low_odds_count, "maxEntryPrice": _decimal_text(max_price)},
    )


def _entry_price_edge(rows: Sequence[Mapping[str, object]]) -> ShadowMetric:
    notes: set[str] = set()
    max_edge: Decimal | None = None
    edge_count = 0
    for row in rows:
        entry = _decimal(row.get("entry_price") or row.get("entryPrice") or row.get("price"))
        reference = _decimal(
            row.get("reference_price")
            or row.get("referencePrice")
            or row.get("post_entry_price")
            or row.get("postEntryPrice")
        )
        if entry is None or reference is None:
            notes.add("missing_entry_edge_inputs_unknown")
            continue
        side = _text(row.get("side") or row.get("order_side")).upper()
        edge = reference - entry if side != "SELL" else entry - reference
        max_edge = edge if max_edge is None else max(max_edge, edge)
        if edge > 0:
            edge_count += 1
    if max_edge is None:
        return ShadowMetric(SHADOW_ENTRY_PRICE_EDGE, STATUS_UNKNOWN, ADVISORY_NONE, None, tuple(sorted(notes)), {})
    advisory = ADVISORY_CONTEXT if max_edge >= ENTRY_EDGE_CONTEXT else ADVISORY_NONE
    return ShadowMetric(
        SHADOW_ENTRY_PRICE_EDGE,
        STATUS_AVAILABLE if advisory != ADVISORY_NONE else STATUS_NOT_TRIGGERED,
        advisory,
        _decimal_text(max_edge),
        tuple(sorted(notes)),
        {"positiveEdgeCount": edge_count},
    )


def _net_position_pnl(rows: Sequence[Mapping[str, object]], current_prices: Mapping[object, object]) -> ShadowMetric:
    if not rows:
        return ShadowMetric(SHADOW_NET_POSITION_PNL, STATUS_UNKNOWN, ADVISORY_NONE, None, ("missing_trades_unknown",), {})
    prices = _normalize_current_prices(current_prices)
    book = build_position_ledgers(rows, current_prices=prices)
    notes = set(book.quality_notes)
    known_values = [position.total_pnl for position in book.positions if position.total_pnl is not None]
    if not known_values:
        status = STATUS_UNKNOWN
        value = None
    else:
        status = STATUS_AVAILABLE
        value = _decimal_text(sum(known_values, Decimal("0")))
    if any(QUALITY_CURRENT_PRICE_UNAVAILABLE in position.quality_notes for position in book.positions):
        notes.add("unrealized_pnl_unknown_without_current_price")
    return ShadowMetric(
        SHADOW_NET_POSITION_PNL,
        status,
        ADVISORY_CONTEXT if status == STATUS_AVAILABLE else ADVISORY_NONE,
        value,
        tuple(sorted(notes)),
        {"positionCount": len(book.positions)},
    )


def _win_rate_confidence(wallet_stats: Mapping[str, object]) -> ShadowMetric:
    resolved = _decimal(wallet_stats.get("resolved_trades") or wallet_stats.get("resolvedTrades"))
    wins = _decimal(wallet_stats.get("winning_trades") or wallet_stats.get("winningTrades") or wallet_stats.get("wins"))
    baseline = _decimal(wallet_stats.get("baseline_win_rate") or wallet_stats.get("baselineWinRate")) or WIN_RATE_BASELINE
    if resolved is None or wins is None or resolved <= 0:
        return ShadowMetric(
            SHADOW_WIN_RATE_CONFIDENCE,
            STATUS_UNKNOWN,
            ADVISORY_NONE,
            None,
            ("missing_win_rate_inputs_unknown",),
            {},
        )
    win_rate = wins / resolved
    discount = resolved / (resolved + Decimal("20"))
    adjusted = max(Decimal("0"), win_rate - baseline) * discount
    notes = []
    if resolved < 10:
        notes.append("small_sample_discounted")
    advisory = ADVISORY_CONTEXT if adjusted >= WIN_RATE_CONTEXT and resolved >= 10 else ADVISORY_NONE
    return ShadowMetric(
        SHADOW_WIN_RATE_CONFIDENCE,
        STATUS_AVAILABLE if advisory != ADVISORY_NONE else STATUS_NOT_TRIGGERED,
        advisory,
        _decimal_text(adjusted),
        tuple(notes),
        {
            "resolvedTrades": _decimal_text(resolved),
            "winRate": _decimal_text(win_rate),
            "sampleDiscount": _decimal_text(discount),
        },
    )


def _microstructure_context(rows: Sequence[Mapping[str, object]]) -> ShadowMetric:
    if not rows:
        return ShadowMetric(
            SHADOW_MICROSTRUCTURE_CONTEXT,
            STATUS_UNKNOWN,
            ADVISORY_NONE,
            None,
            ("missing_microstructure_unknown",),
            {},
        )
    spreads = [_decimal(row.get("spread_bps") or row.get("spreadBps")) for row in rows]
    bid_depths = [_decimal(row.get("bid_depth") or row.get("bidDepth")) for row in rows]
    ask_depths = [_decimal(row.get("ask_depth") or row.get("askDepth")) for row in rows]
    imbalances = [_decimal(row.get("liquidity_imbalance") or row.get("liquidityImbalance")) for row in rows]
    spreads = [item for item in spreads if item is not None]
    depths = [item for item in [*_none_filtered(bid_depths), *_none_filtered(ask_depths)] if item is not None]
    imbalances = [abs(item) for item in imbalances if item is not None]
    notes = set()
    if not spreads and not depths and not imbalances:
        notes.add("malformed_microstructure_unknown")
        return ShadowMetric(SHADOW_MICROSTRUCTURE_CONTEXT, STATUS_UNKNOWN, ADVISORY_NONE, None, tuple(notes), {})
    max_spread = max(spreads) if spreads else None
    min_depth = min(depths) if depths else None
    max_imbalance = max(imbalances) if imbalances else None
    triggered = (
        (max_spread is not None and max_spread >= MICROSTRUCTURE_WIDE_SPREAD_BPS)
        or (min_depth is not None and min_depth <= MICROSTRUCTURE_LOW_DEPTH)
        or (max_imbalance is not None and max_imbalance >= MICROSTRUCTURE_IMBALANCE)
    )
    return ShadowMetric(
        SHADOW_MICROSTRUCTURE_CONTEXT,
        STATUS_AVAILABLE if triggered else STATUS_NOT_TRIGGERED,
        ADVISORY_CONTEXT if triggered else ADVISORY_NONE,
        _decimal_text(max_spread),
        tuple(sorted(notes)),
        {
            "maxSpreadBps": _decimal_text(max_spread),
            "minDepth": _decimal_text(min_depth),
            "maxAbsImbalance": _decimal_text(max_imbalance),
        },
    )


def _timing_context(rows: Sequence[Mapping[str, object]]) -> ShadowMetric:
    count = sum(1 for row in rows if _truthy(row.get("suspicious_timing_context") or row.get("timingContext")))
    return ShadowMetric(
        SHADOW_TIMING_CONTEXT,
        STATUS_AVAILABLE if count else STATUS_NOT_TRIGGERED,
        ADVISORY_CONTEXT if count else ADVISORY_NONE,
        str(count) if count else None,
        (),
        {"contextTradeCount": count},
    )


def _structural_context(rows: Sequence[Mapping[str, object]]) -> ShadowMetric:
    count = sum(
        1
        for row in rows
        if _truthy(row.get("shared_funder_context") or row.get("sharedFunderContext") or row.get("split_wallet_context"))
    )
    return ShadowMetric(
        SHADOW_STRUCTURAL_CONTEXT,
        STATUS_AVAILABLE if count else STATUS_NOT_TRIGGERED,
        ADVISORY_CONTEXT if count else ADVISORY_NONE,
        str(count) if count else None,
        (),
        {"contextTradeCount": count},
    )


def _public_volume_caution(wallet_stats: Mapping[str, object]) -> ShadowMetric:
    trade_count = _decimal(wallet_stats.get("trade_count") or wallet_stats.get("tradeCount"))
    distinct_markets = _decimal(wallet_stats.get("distinct_markets") or wallet_stats.get("distinctMarkets"))
    if trade_count is None or distinct_markets is None:
        return ShadowMetric(SHADOW_PUBLIC_VOLUME_CAUTION, STATUS_UNKNOWN, ADVISORY_NONE, None, (), {})
    triggered = trade_count >= 100 and distinct_markets >= 20
    return ShadowMetric(
        SHADOW_PUBLIC_VOLUME_CAUTION,
        STATUS_AVAILABLE if triggered else STATUS_NOT_TRIGGERED,
        ADVISORY_CONTEXT if triggered else ADVISORY_NONE,
        _decimal_text(trade_count),
        ("high_volume_diversified_wallet_caution",) if triggered else (),
        {"distinctMarkets": _decimal_text(distinct_markets)},
    )


def _normalize_current_prices(current_prices: Mapping[object, object]) -> dict[object, object]:
    normalized: dict[object, object] = {}
    for key, value in current_prices.items():
        if isinstance(key, str) and "|" in key:
            parts = tuple(key.split("|"))
            if len(parts) == 4:
                normalized[parts] = value
                continue
        normalized[key] = value
    return normalized


def _cash(row: Mapping[str, object]) -> Decimal | None:
    explicit = _decimal(
        row.get("usdcSize")
        or row.get("usdc_size")
        or row.get("api_usdc_size")
        or row.get("api_cash_amount")
        or row.get("cash_amount")
    )
    if explicit is not None:
        return explicit
    size = _decimal(row.get("size") or row.get("shares") or row.get("amount"))
    price = _decimal(row.get("price") or row.get("avg_price") or row.get("average_price"))
    if size is None or price is None:
        return None
    return size * price


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _text(value: object) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _none_filtered(values: Sequence[Decimal | None]) -> tuple[Decimal, ...]:
    return tuple(value for value in values if value is not None)


def _find_denied_keys(payload: object) -> set[str]:
    found: set[str] = set()
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key)
            if key_text in PRODUCTION_FIELD_DENYLIST:
                found.add(key_text)
            found.update(_find_denied_keys(value))
    elif isinstance(payload, list):
        for item in payload:
            found.update(_find_denied_keys(item))
    return found
