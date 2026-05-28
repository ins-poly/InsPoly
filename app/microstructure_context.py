from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence


STATUS_AVAILABLE = "available"
STATUS_UNKNOWN = "unknown"
STATUS_NOT_TRIGGERED = "not_triggered"


@dataclass(frozen=True, slots=True)
class MicrostructureContext:
    status: str
    snapshot_count: int
    latest_spread_bps: str | None
    spread_change_bps: str | None
    latest_total_depth: str | None
    depth_change: str | None
    latest_liquidity_imbalance: str | None
    liquidity_shock: bool
    quality_notes: tuple[str, ...]
    production_integration: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "snapshotCount": self.snapshot_count,
            "latestSpreadBps": self.latest_spread_bps,
            "spreadChangeBps": self.spread_change_bps,
            "latestTotalDepth": self.latest_total_depth,
            "depthChange": self.depth_change,
            "latestLiquidityImbalance": self.latest_liquidity_imbalance,
            "liquidityShock": self.liquidity_shock,
            "qualityNotes": list(self.quality_notes),
            "productionIntegration": self.production_integration,
        }


def summarize_microstructure_snapshots(snapshots: Sequence[object]) -> MicrostructureContext:
    rows = [_snapshot_payload(snapshot) for snapshot in snapshots]
    parsed = [_parse_snapshot(row) for row in rows]
    valid = [item for item in parsed if item is not None]
    notes = []
    if len(valid) != len(rows):
        notes.append("malformed_snapshot_ignored")
    if not valid:
        return MicrostructureContext(
            status=STATUS_UNKNOWN,
            snapshot_count=len(rows),
            latest_spread_bps=None,
            spread_change_bps=None,
            latest_total_depth=None,
            depth_change=None,
            latest_liquidity_imbalance=None,
            liquidity_shock=False,
            quality_notes=tuple(notes or ["microstructure_unavailable_unknown"]),
        )
    valid.sort(key=lambda item: str(item["timestamp"]))
    first = valid[0]
    latest = valid[-1]
    spread_change = _subtract(latest["spread_bps"], first["spread_bps"])
    depth_change = _subtract(latest["total_depth"], first["total_depth"])
    liquidity_shock = False
    if spread_change is not None and first["spread_bps"] is not None:
        liquidity_shock = spread_change >= max(Decimal("250"), first["spread_bps"])
    if depth_change is not None and first["total_depth"] is not None and first["total_depth"] > 0:
        liquidity_shock = liquidity_shock or depth_change <= -(first["total_depth"] * Decimal("0.5"))
    latest_imbalance = latest["liquidity_imbalance"]
    if latest_imbalance is not None and abs(latest_imbalance) >= Decimal("0.5"):
        liquidity_shock = True
    status = STATUS_AVAILABLE if liquidity_shock else STATUS_NOT_TRIGGERED
    return MicrostructureContext(
        status=status,
        snapshot_count=len(valid),
        latest_spread_bps=_decimal_text(latest["spread_bps"]),
        spread_change_bps=_decimal_text(spread_change),
        latest_total_depth=_decimal_text(latest["total_depth"]),
        depth_change=_decimal_text(depth_change),
        latest_liquidity_imbalance=_decimal_text(latest_imbalance),
        liquidity_shock=liquidity_shock,
        quality_notes=tuple(notes),
    )


def _snapshot_payload(snapshot: object) -> Mapping[str, object]:
    if isinstance(snapshot, Mapping):
        return snapshot
    payload: dict[str, object] = {}
    for attr in (
        "timestamp",
        "spread_bps",
        "spreadBps",
        "bid_depth",
        "bidDepth",
        "ask_depth",
        "askDepth",
        "liquidity_imbalance",
        "liquidityImbalance",
    ):
        if hasattr(snapshot, attr):
            payload[attr] = getattr(snapshot, attr)
    return payload


def _parse_snapshot(row: Mapping[str, object]) -> dict[str, Decimal | str | None] | None:
    spread = _decimal(row.get("spread_bps") or row.get("spreadBps"))
    bid_depth = _decimal(row.get("bid_depth") or row.get("bidDepth"))
    ask_depth = _decimal(row.get("ask_depth") or row.get("askDepth"))
    imbalance = _decimal(row.get("liquidity_imbalance") or row.get("liquidityImbalance"))
    if spread is None and bid_depth is None and ask_depth is None and imbalance is None:
        return None
    return {
        "timestamp": str(row.get("timestamp") or ""),
        "spread_bps": spread,
        "total_depth": (bid_depth or Decimal("0")) + (ask_depth or Decimal("0")),
        "liquidity_imbalance": imbalance,
    }


def _subtract(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return left - right


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
