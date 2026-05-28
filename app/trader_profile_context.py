from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence


UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TraderProfileContext:
    wallet: str
    position_count: int
    open_position_count: int
    trade_count: int
    total_remaining_shares: str
    total_pnl: str | None
    pnl_status: str
    advisory_metrics: tuple[str, ...]
    caution_notes: tuple[str, ...]
    production_integration: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "wallet": self.wallet,
            "positionCount": self.position_count,
            "openPositionCount": self.open_position_count,
            "tradeCount": self.trade_count,
            "totalRemainingShares": self.total_remaining_shares,
            "totalPnl": self.total_pnl,
            "pnlStatus": self.pnl_status,
            "advisoryMetrics": list(self.advisory_metrics),
            "cautionNotes": list(self.caution_notes),
            "productionIntegration": self.production_integration,
        }


def build_trader_profile_context(
    *,
    wallet: str,
    positions: Sequence[object],
    shadow_metrics: Sequence[Mapping[str, object]] | None = None,
    trade_count: int = 0,
    high_volume_public_user: bool = False,
) -> TraderProfileContext:
    normalized_positions = [_position_payload(position) for position in positions]
    remaining_values = [_decimal(position.get("remaining_shares") or position.get("remainingShares")) for position in normalized_positions]
    pnl_values = [_decimal(position.get("total_pnl") or position.get("totalPnl")) for position in normalized_positions]
    open_count = sum(1 for value in remaining_values if value is not None and value > 0)
    known_pnl_values = [value for value in pnl_values if value is not None]
    total_pnl = sum(known_pnl_values, Decimal("0")) if len(known_pnl_values) == len(normalized_positions) else None
    notes = []
    if total_pnl is None and normalized_positions:
        notes.append("pnl_unknown_when_any_position_missing_total_pnl")
    if high_volume_public_user:
        notes.append("high_volume_public_user_context")
    total_remaining = sum((value or Decimal("0") for value in remaining_values), Decimal("0"))
    advisory_metrics = tuple(
        str(metric.get("name"))
        for metric in shadow_metrics or ()
        if isinstance(metric, Mapping)
        and str(metric.get("advisoryLevel") or "none") != "none"
        and str(metric.get("status") or "") != UNKNOWN
    )
    return TraderProfileContext(
        wallet=wallet,
        position_count=len(normalized_positions),
        open_position_count=open_count,
        trade_count=int(trade_count),
        total_remaining_shares=_decimal_text(total_remaining),
        total_pnl=_decimal_text(total_pnl),
        pnl_status="known" if total_pnl is not None else UNKNOWN,
        advisory_metrics=advisory_metrics,
        caution_notes=tuple(notes),
    )


def _position_payload(position: object) -> Mapping[str, object]:
    if isinstance(position, Mapping):
        return position
    payload: dict[str, object] = {}
    for attr in ("remaining_shares", "remainingShares", "total_pnl", "totalPnl"):
        if hasattr(position, attr):
            payload[attr] = getattr(position, attr)
    return payload


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
