#!/usr/bin/env python3
"""Read-only audit for Phase 2 Polymarket ledger helpers.

This sidecar validates `app.polymarket_ledger` against reconstruction-style
artifacts already produced by local tools. It does not fetch network data,
modify artifacts, or integrate the helper into scanner/report runtime paths.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.polymarket_ledger import (  # noqa: E402
    DEFAULT_CASH_DISAGREEMENT_TOLERANCE,
    QUALITY_CURRENT_PRICE_UNAVAILABLE,
    QUALITY_MISSING_CASH_FIELD,
    QUALITY_POSITION_RECONCILIATION_MISMATCH,
    QUALITY_SELL_EXCEEDS_TRACKED_HOLDINGS,
    QUALITY_SOURCE_CASH_DISAGREEMENT,
    QUALITY_UNKNOWN_CASH_SOURCE,
    LedgerBook,
    LedgerKey,
    PositionLedger,
    build_position_ledgers,
)


STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_MISMATCH = "mismatch"
STATUS_UNKNOWN = "unknown"
ARTIFACT_AUDIT_TOLERANCE = Decimal("0.0001")


QUALITY_NOTE_MESSAGES = {
    QUALITY_MISSING_CASH_FIELD: (
        "A trade row did not expose explicit API cash. The audit keeps cash "
        "unknown or falls back to size*price only when price is present."
    ),
    QUALITY_UNKNOWN_CASH_SOURCE: (
        "A trade row had no usable cash source. The audit does not coerce "
        "missing cash to zero."
    ),
    QUALITY_SOURCE_CASH_DISAGREEMENT: (
        "Explicit API cash differs from size*price. API cash remains preferred, "
        "and the discrepancy is surfaced for reconciliation."
    ),
    QUALITY_POSITION_RECONCILIATION_MISMATCH: (
        "Ledger remaining shares differ from saved current-position shares "
        "outside tolerance."
    ),
    QUALITY_SELL_EXCEEDS_TRACKED_HOLDINGS: (
        "A sell exceeds tracked helper holdings. The helper caps realized PnL "
        "to tracked shares and records the ignored amount."
    ),
    QUALITY_CURRENT_PRICE_UNAVAILABLE: (
        "Current price is unavailable for an open position, so unrealized PnL "
        "remains unknown."
    ),
}


@dataclass(frozen=True, slots=True)
class AuditCheck:
    name: str
    status: str
    expected: str | None
    actual: str | None
    tolerance: str
    details: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "expected": self.expected,
            "actual": self.actual,
            "tolerance": self.tolerance,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class AuditPosition:
    wallet: str
    condition_id: str
    token_id: str
    outcome: str
    remaining_shares: str
    total_bought_shares: str
    total_sold_shares: str
    total_buy_cash: str | None
    total_sell_cash: str | None
    source_cash_disagreement_count: int
    quality_notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "wallet": self.wallet,
            "condition_id": self.condition_id,
            "token_id": self.token_id,
            "outcome": self.outcome,
            "remaining_shares": self.remaining_shares,
            "total_bought_shares": self.total_bought_shares,
            "total_sold_shares": self.total_sold_shares,
            "total_buy_cash": self.total_buy_cash,
            "total_sell_cash": self.total_sell_cash,
            "source_cash_disagreement_count": self.source_cash_disagreement_count,
            "quality_notes": list(self.quality_notes),
        }


@dataclass(frozen=True, slots=True)
class LedgerArtifactAudit:
    artifact_dir: str
    status: str
    rows_loaded: int
    position_count: int
    wallet: str
    checks: tuple[AuditCheck, ...]
    quality_notes: tuple[dict[str, str], ...]
    positions: tuple[AuditPosition, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_dir": self.artifact_dir,
            "status": self.status,
            "rows_loaded": self.rows_loaded,
            "position_count": self.position_count,
            "wallet": self.wallet,
            "checks": [check.to_dict() for check in self.checks],
            "quality_notes": list(self.quality_notes),
            "positions": [position.to_dict() for position in self.positions],
        }


def audit_artifact_dir(
    artifact_dir: str | Path,
    *,
    wallet: str | None = None,
    tolerance: Decimal = ARTIFACT_AUDIT_TOLERANCE,
    cash_disagreement_tolerance: Decimal = DEFAULT_CASH_DISAGREEMENT_TOLERANCE,
) -> LedgerArtifactAudit:
    """Validate helper ledger output against local reconstruction artifacts."""

    root = Path(artifact_dir)
    normalized_rows = _read_csv(root / "normalized_trades.csv")
    summary = _read_summary(root / "summary_calculations.csv")
    current_positions = _read_json_rows(root / "raw_positions_current.json")
    current_payload = _read_json_object(root / "raw_positions_current.json")
    inferred_wallet = _infer_wallet(wallet, normalized_rows, current_positions, current_payload)
    rows = _inject_wallet(normalized_rows, inferred_wallet)
    current_prices, expected_positions = _position_maps(current_positions, inferred_wallet)

    book = build_position_ledgers(
        rows,
        current_prices=current_prices,
        expected_positions=expected_positions,
        reconciliation_tolerance=tolerance,
        cash_disagreement_tolerance=cash_disagreement_tolerance,
    )
    checks = tuple(
        _build_checks(
            book=book,
            summary=summary,
            expected_positions=expected_positions,
            tolerance=tolerance,
        )
    )
    quality_notes = _quality_note_payload(book)
    status = _overall_status(checks, quality_notes)
    return LedgerArtifactAudit(
        artifact_dir=str(root),
        status=status,
        rows_loaded=len(rows),
        position_count=len(book.positions),
        wallet=inferred_wallet,
        checks=checks,
        quality_notes=quality_notes,
        positions=tuple(_audit_position(position) for position in book.positions),
    )


def write_audit_output(audit: LedgerArtifactAudit, output_dir: str | Path) -> Path:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    target = target_dir / f"polymarket_ledger_audit_{stamp}.json"
    target.write_text(json.dumps(audit.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return target


def _build_checks(
    *,
    book: LedgerBook,
    summary: Mapping[str, Decimal],
    expected_positions: Mapping[object, object],
    tolerance: Decimal,
) -> Iterable[AuditCheck]:
    aggregates = _aggregate_positions(book.positions)

    for key, expected in expected_positions.items():
        if not isinstance(key, tuple) or len(key) != 4:
            continue
        actual_position = _position_for_key(book.positions, key)
        name = f"current_position:{key[1]}:{key[2]}:{key[3]}"
        actual = actual_position.remaining_shares if actual_position is not None else None
        yield _compare_decimal(
            name=name,
            expected=_decimal_or_none(expected),
            actual=actual,
            tolerance=tolerance,
            source_disagreement=False,
        )

    summary_checks = (
        ("summary:total_yes_bought", "total_yes_bought", aggregates["yes_bought"]),
        ("summary:total_no_bought", "total_no_bought", aggregates["no_bought"]),
        ("summary:total_yes_sold", "total_yes_sold", aggregates["yes_sold"]),
        ("summary:total_no_sold", "total_no_sold", aggregates["no_sold"]),
        ("summary:remaining_yes_shares", "remaining_yes_shares", aggregates["yes_remaining"]),
        ("summary:remaining_no_shares", "remaining_no_shares", aggregates["no_remaining"]),
        ("summary:current_yes_size_api", "current_yes_size_api", aggregates["yes_remaining"]),
        ("summary:current_no_size_api", "current_no_size_api", aggregates["no_remaining"]),
        ("summary:current_position_size_api", "current_position_size_api", aggregates["remaining_all"]),
        ("summary:total_yes_buy_cost", "total_yes_buy_cost", aggregates["yes_buy_cash"]),
        ("summary:total_no_buy_cost", "total_no_buy_cost", aggregates["no_buy_cash"]),
        ("summary:total_yes_sale_proceeds", "total_yes_sale_proceeds", aggregates["yes_sell_cash"]),
        ("summary:total_no_sale_proceeds", "total_no_sale_proceeds", aggregates["no_sell_cash"]),
        ("summary:total_buy_api_cash", "total_buy_api_cash", aggregates["buy_cash_all"]),
        ("summary:total_sell_api_cash", "total_sell_api_cash", aggregates["sell_cash_all"]),
    )
    source_disagreement = any(position.source_cash_disagreement_count for position in book.positions)
    cash_summary_keys = {
        "total_yes_buy_cost",
        "total_no_buy_cost",
        "total_yes_sale_proceeds",
        "total_no_sale_proceeds",
        "total_buy_api_cash",
        "total_sell_api_cash",
    }
    for check_name, summary_key, actual in summary_checks:
        if summary_key not in summary:
            continue
        yield _compare_decimal(
            name=check_name,
            expected=summary[summary_key],
            actual=actual,
            tolerance=tolerance,
            source_disagreement=source_disagreement and summary_key in cash_summary_keys,
        )


def _aggregate_positions(positions: Sequence[PositionLedger]) -> dict[str, Decimal | None]:
    yes = [position for position in positions if position.key.outcome.lower() == "yes"]
    no = [position for position in positions if position.key.outcome.lower() == "no"]
    return {
        "yes_bought": _sum_decimal(position.total_bought_shares for position in yes),
        "no_bought": _sum_decimal(position.total_bought_shares for position in no),
        "yes_sold": _sum_decimal(position.total_sold_shares for position in yes),
        "no_sold": _sum_decimal(position.total_sold_shares for position in no),
        "yes_remaining": _sum_decimal(position.remaining_shares for position in yes),
        "no_remaining": _sum_decimal(position.remaining_shares for position in no),
        "remaining_all": _sum_decimal(position.remaining_shares for position in positions),
        "yes_buy_cash": _sum_optional_cash(position.total_buy_cash for position in yes),
        "no_buy_cash": _sum_optional_cash(position.total_buy_cash for position in no),
        "yes_sell_cash": _sum_optional_cash(position.total_sell_cash for position in yes),
        "no_sell_cash": _sum_optional_cash(position.total_sell_cash for position in no),
        "buy_cash_all": _sum_optional_cash(position.total_buy_cash for position in positions),
        "sell_cash_all": _sum_optional_cash(position.total_sell_cash for position in positions),
    }


def _compare_decimal(
    *,
    name: str,
    expected: Decimal | None,
    actual: Decimal | None,
    tolerance: Decimal,
    source_disagreement: bool,
) -> AuditCheck:
    if actual is None:
        return AuditCheck(
            name=name,
            status=STATUS_UNKNOWN,
            expected=_decimal_text(expected),
            actual=None,
            tolerance=_decimal_text(tolerance) or "0",
            details="Helper value is unknown; missing fields were not coerced to zero.",
        )
    if expected is None:
        return AuditCheck(
            name=name,
            status=STATUS_UNKNOWN,
            expected=None,
            actual=_decimal_text(actual),
            tolerance=_decimal_text(tolerance) or "0",
            details="Saved artifact did not expose an expected value for this check.",
        )
    delta = abs(actual - expected)
    if delta <= tolerance:
        return AuditCheck(
            name=name,
            status=STATUS_OK,
            expected=_decimal_text(expected),
            actual=_decimal_text(actual),
            tolerance=_decimal_text(tolerance) or "0",
            details="Within tolerance.",
        )
    if source_disagreement:
        return AuditCheck(
            name=name,
            status=STATUS_WARNING,
            expected=_decimal_text(expected),
            actual=_decimal_text(actual),
            tolerance=_decimal_text(tolerance) or "0",
            details=(
                "Mismatch is accompanied by source_cash_disagreement; inspect "
                "API cash versus size*price before treating it as a ledger bug."
            ),
        )
    return AuditCheck(
        name=name,
        status=STATUS_MISMATCH,
        expected=_decimal_text(expected),
        actual=_decimal_text(actual),
        tolerance=_decimal_text(tolerance) or "0",
        details="Outside tolerance with no source-cash explanation.",
    )


def _position_for_key(positions: Sequence[PositionLedger], key: tuple[object, ...]) -> PositionLedger | None:
    for position in positions:
        if (
            position.key.wallet,
            position.key.condition_id,
            position.key.token_id,
            position.key.outcome,
        ) == key:
            return position
    return None


def _audit_position(position: PositionLedger) -> AuditPosition:
    return AuditPosition(
        wallet=position.key.wallet,
        condition_id=position.key.condition_id,
        token_id=position.key.token_id,
        outcome=position.key.outcome,
        remaining_shares=_decimal_text(position.remaining_shares) or "0",
        total_bought_shares=_decimal_text(position.total_bought_shares) or "0",
        total_sold_shares=_decimal_text(position.total_sold_shares) or "0",
        total_buy_cash=_decimal_text(position.total_buy_cash),
        total_sell_cash=_decimal_text(position.total_sell_cash),
        source_cash_disagreement_count=position.source_cash_disagreement_count,
        quality_notes=position.quality_notes,
    )


def _quality_note_payload(book: LedgerBook) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "note": note,
            "message": QUALITY_NOTE_MESSAGES.get(note, "Ledger helper surfaced this note for audit review."),
        }
        for note in book.quality_notes
    )


def _overall_status(checks: Sequence[AuditCheck], quality_notes: Sequence[Mapping[str, str]]) -> str:
    if any(check.status == STATUS_MISMATCH for check in checks):
        return STATUS_MISMATCH
    if quality_notes or any(check.status in {STATUS_WARNING, STATUS_UNKNOWN} for check in checks):
        return STATUS_WARNING
    return STATUS_OK


def _position_maps(
    rows: Sequence[Mapping[str, Any]],
    wallet: str,
) -> tuple[dict[object, Decimal], dict[object, Decimal]]:
    current_prices: dict[object, Decimal] = {}
    expected_positions: dict[object, Decimal] = {}
    for row in rows:
        condition_id = _text(row.get("conditionId") or row.get("condition_id"))
        token_id = _text(row.get("asset") or row.get("asset_id") or row.get("token_id"))
        outcome = _text(row.get("outcome"))
        if not condition_id or not token_id or not outcome:
            continue
        key = (wallet, condition_id, token_id, outcome)
        size = _decimal_or_none(row.get("size"))
        if size is not None:
            expected_positions[key] = size
        current_price = _decimal_or_none(row.get("curPrice") or row.get("current_price"))
        if current_price is not None:
            current_prices[key] = current_price
    return current_prices, expected_positions


def _infer_wallet(
    override: str | None,
    normalized_rows: Sequence[Mapping[str, Any]],
    current_positions: Sequence[Mapping[str, Any]],
    current_payload: Mapping[str, Any],
) -> str:
    if override:
        return override
    for row in normalized_rows:
        wallet = _text(row.get("wallet") or row.get("proxyWallet") or row.get("proxy_wallet") or row.get("user"))
        if wallet:
            return wallet
    for row in current_positions:
        wallet = _text(row.get("proxyWallet") or row.get("wallet") or row.get("user"))
        if wallet:
            return wallet
    base_params = current_payload.get("base_params")
    if isinstance(base_params, Mapping):
        wallet = _text(base_params.get("user"))
        if wallet:
            return wallet
    return "artifact_wallet"


def _inject_wallet(rows: Sequence[Mapping[str, Any]], wallet: str) -> list[dict[str, Any]]:
    injected: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        if not _text(copied.get("wallet") or copied.get("proxyWallet") or copied.get("proxy_wallet") or copied.get("user")):
            copied["wallet"] = wallet
        injected.append(copied)
    return injected


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required artifact: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_summary(path: Path) -> dict[str, Decimal]:
    if not path.exists():
        return {}
    summary: dict[str, Decimal] = {}
    for row in _read_csv(path):
        metric = _text(row.get("metric"))
        value = _decimal_or_none(row.get("value"))
        if metric and value is not None:
            summary[metric] = value
    return summary


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    payload = _read_json_object(path)
    if not payload:
        return []
    rows = payload.get("rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _sum_decimal(values: Iterable[Decimal]) -> Decimal:
    total = Decimal("0")
    for value in values:
        total += value
    return total


def _sum_optional_cash(values: Iterable[Decimal | None]) -> Decimal | None:
    total = Decimal("0")
    for value in values:
        if value is None:
            return None
        total += value
    return total


def _decimal_or_none(value: object) -> Decimal | None:
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
    return str(value).strip() if value not in (None, "") else ""


def _parse_decimal_arg(value: str) -> Decimal:
    parsed = _decimal_or_none(value)
    if parsed is None:
        raise argparse.ArgumentTypeError(f"Invalid decimal value: {value}")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate app.polymarket_ledger against local reconstruction artifacts."
    )
    parser.add_argument("artifact_dir", help="Directory containing normalized_trades.csv and related artifacts.")
    parser.add_argument("--wallet", help="Wallet override when artifact rows do not expose one.")
    parser.add_argument(
        "--tolerance",
        type=_parse_decimal_arg,
        default=ARTIFACT_AUDIT_TOLERANCE,
        help="Decimal tolerance for share/cash comparisons.",
    )
    parser.add_argument(
        "--cash-disagreement-tolerance",
        type=_parse_decimal_arg,
        default=DEFAULT_CASH_DISAGREEMENT_TOLERANCE,
        help="Decimal tolerance before API cash versus size*price is reported.",
    )
    parser.add_argument("--output-dir", help="Optional directory for a timestamped JSON audit copy.")
    args = parser.parse_args(argv)

    audit = audit_artifact_dir(
        args.artifact_dir,
        wallet=args.wallet,
        tolerance=args.tolerance,
        cash_disagreement_tolerance=args.cash_disagreement_tolerance,
    )
    if args.output_dir:
        write_audit_output(audit, args.output_dir)
    print(json.dumps(audit.to_dict(), indent=2, sort_keys=True))
    return 1 if audit.status == STATUS_MISMATCH else 0


if __name__ == "__main__":
    raise SystemExit(main())
