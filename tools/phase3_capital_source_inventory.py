#!/usr/bin/env python3
"""Read-only Phase 3 capital source-field inventory.

This sidecar classifies local artifacts and fixtures for whether their fields
are sufficient to reason about BUY cash or SELL max-loss semantics. It does not
import scanner/archive/Event Forensic runtime paths and does not perform any
network calls.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.side_outcome import UNKNOWN, normalize_side_outcome  # noqa: E402
from tools.side_outcome_phase3_capital_at_risk_audit import discover_phase3_records  # noqa: E402


REPORT_TYPE = "phase3_capital_source_inventory"
SCHEMA_VERSION = "phase3_capital_source_inventory_v1"
DEFAULT_OUTPUT = Path("validation_outputs/phase3_capital_source_inventory_20260525.json")

QUALITY_SAFE_BUY_CASH = "safe_for_buy_cash"
QUALITY_SAFE_SELL_MAX_LOSS = "safe_for_sell_max_loss"
QUALITY_DISPLAY_ONLY = "safe_for_display_only"
QUALITY_UNSAFE_OLD_NOTIONAL_ONLY = "unsafe_old_notional_only"
QUALITY_UNKNOWN_MISSING_FIELDS = "unknown_missing_fields"

_SIDE_KEYS = ("raw_order_side", "rawOrderSide", "side", "order_side", "orderSide")
_OUTCOME_KEYS = ("raw_token_outcome", "rawTokenOutcome", "outcome", "tokenOutcome", "direction")
_PRICE_KEYS = ("raw_token_price", "rawTokenPrice", "price", "entry_probability_pct", "price_implied_probability")
_SIZE_KEYS = ("size", "shares", "amount")
_USDC_KEYS = ("usdcSize", "usdc_size", "api_usdc_size")
_CASH_KEYS = _USDC_KEYS + ("cash_amount", "api_cash_amount", "trade_notional_usdc", "tradeNotionalUsd")
_NOTIONAL_KEYS = ("trade_notional_usdc", "tradeNotionalUsd", "positionSize", "position_size", "notional", "capital_at_risk_usdc")
_COLLATERAL_KEYS = (
    "collateral",
    "collateral_usdc",
    "collateralUsd",
    "max_loss",
    "maxLoss",
    "max_loss_usdc",
    "maxLossUsd",
    "economic_capital_at_risk_usdc",
)
_TOKEN_KEYS = ("token_id", "tokenId", "asset_id", "assetId", "asset")
_CONDITION_KEYS = ("condition_id", "conditionId", "condition", "market", "market_id")
_DIRECTION_KEYS = ("model_economic_direction", "modelEconomicDirection", "economic_direction", "cluster_direction")


def classify_source_row(record: Mapping[str, object]) -> dict[str, object]:
    side_input = _first_present(record, _SIDE_KEYS)
    outcome_input = _first_present(record, _OUTCOME_KEYS)
    price_input = _first_present(record, _PRICE_KEYS)
    normalized = normalize_side_outcome(side_input, outcome_input, price_input)
    size = _decimal_or_none(_first_present(record, _SIZE_KEYS))
    usdc_size = _decimal_or_none(_first_present(record, _USDC_KEYS))
    cash_paid = _decimal_or_none(_first_present(record, _CASH_KEYS))
    collateral = _decimal_or_none(_first_present(record, _COLLATERAL_KEYS))
    notional = _decimal_or_none(_first_present(record, _NOTIONAL_KEYS))
    source_type = _source_type(record)
    evidence_type = str(record.get("artifactEvidenceType") or record.get("source_type") or "unknown")
    direct_raw_trade = _is_direct_raw_trade_source(source_type)

    has_side = normalized.raw_order_side != UNKNOWN
    has_outcome = normalized.raw_token_outcome != UNKNOWN
    has_price = normalized.raw_token_price is not None
    has_size = size is not None
    has_token_id = bool(_text(_first_present(record, _TOKEN_KEYS)))
    has_condition_id = bool(_text(_first_present(record, _CONDITION_KEYS)))
    has_direction = bool(_text(_first_present(record, _DIRECTION_KEYS)))
    has_usdc_size = usdc_size is not None
    has_cash_paid = cash_paid is not None
    has_collateral = collateral is not None
    has_notional = notional is not None
    has_required_trade_fields = has_side and has_outcome and has_price and has_size
    old_notional_only = has_notional and not has_required_trade_fields

    notes: list[str] = []
    if old_notional_only:
        source_quality = QUALITY_UNSAFE_OLD_NOTIONAL_ONLY
        notes.append("notional_only_cannot_be_reinterpreted")
    elif not has_required_trade_fields:
        source_quality = QUALITY_UNKNOWN_MISSING_FIELDS
        notes.extend(_missing_notes(has_side, has_outcome, has_price, has_size))
    elif normalized.raw_order_side == "BUY":
        source_quality = QUALITY_SAFE_BUY_CASH
        notes.append("buy_cash_can_use_explicit_cash_or_size_price")
    elif normalized.raw_order_side == "SELL":
        if direct_raw_trade or has_collateral:
            source_quality = QUALITY_SAFE_SELL_MAX_LOSS
            notes.append("sell_max_loss_can_use_auditable_complement_formula")
        else:
            source_quality = QUALITY_DISPLAY_ONLY
            notes.append("saved_report_row_is_audit_evidence_not_runtime_source")
        if has_usdc_size:
            notes.append("usdcSize_is_observed_cash_not_max_loss")
    else:
        source_quality = QUALITY_UNKNOWN_MISSING_FIELDS
        notes.append("unknown_side")

    return {
        "rowId": str(_first_present(record, ("id", "trade_id", "transactionHash", "rowIndex")) or ""),
        "sourceType": source_type,
        "artifactFamily": str(record.get("artifactFamily") or "unknown"),
        "artifactEvidenceType": evidence_type,
        "artifactPath": str(record.get("artifactPath") or record.get("source_path") or ""),
        "rawOrderSide": normalized.raw_order_side,
        "rawTokenOutcome": normalized.raw_token_outcome,
        "rawTokenPrice": _decimal_text(normalized.raw_token_price),
        "size": _decimal_text(size),
        "hasSide": has_side,
        "hasOutcome": has_outcome,
        "hasPrice": has_price,
        "hasSize": has_size,
        "hasUsdcSize": has_usdc_size,
        "hasCashPaid": has_cash_paid,
        "hasCollateralOrMaxLoss": has_collateral,
        "hasTokenId": has_token_id,
        "hasConditionId": has_condition_id,
        "hasPositionDirection": has_direction,
        "directRawTradeSource": direct_raw_trade,
        "sourceQuality": source_quality,
        "runtimeSafeCandidate": source_quality in {QUALITY_SAFE_BUY_CASH, QUALITY_SAFE_SELL_MAX_LOSS} and direct_raw_trade,
        "qualityNotes": notes,
    }


def build_source_inventory(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    rows = [classify_source_row(record) for record in records]
    quality_counts = Counter(row["sourceQuality"] for row in rows)
    source_type_counts = Counter(row["sourceType"] for row in rows)
    evidence_counts = Counter(row["artifactEvidenceType"] for row in rows)
    family_counts = Counter(row["artifactFamily"] for row in rows)
    field_counts = Counter()
    for field in (
        "hasSide",
        "hasOutcome",
        "hasPrice",
        "hasSize",
        "hasUsdcSize",
        "hasCashPaid",
        "hasCollateralOrMaxLoss",
        "hasTokenId",
        "hasConditionId",
        "hasPositionDirection",
    ):
        field_counts[field] = sum(1 for row in rows if row[field])
    real_rows = [row for row in rows if row["artifactEvidenceType"] == "real_local"]
    summary = {
        "recordsEvaluated": len(rows),
        "sourceQualityCounts": dict(sorted(quality_counts.items())),
        "sourceTypeCounts": dict(sorted(source_type_counts.items())),
        "evidenceTypeCounts": dict(sorted(evidence_counts.items())),
        "artifactFamilyCounts": dict(sorted(family_counts.items())),
        "fieldCoverageCounts": dict(sorted(field_counts.items())),
        "realLocalRows": len(real_rows),
        "realLocalSafeForSellMaxLoss": sum(1 for row in real_rows if row["sourceQuality"] == QUALITY_SAFE_SELL_MAX_LOSS),
        "runtimeSafeCandidateRows": sum(1 for row in rows if row["runtimeSafeCandidate"]),
        "oldNotionalOnlyRows": quality_counts[QUALITY_UNSAFE_OLD_NOTIONAL_ONLY],
        "unknownMissingFieldRows": quality_counts[QUALITY_UNKNOWN_MISSING_FIELDS],
    }
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeImplementationAllowed": False,
        "summary": summary,
        "rows": rows,
    }


def discover_inventory_records(
    root: str | Path = ".",
    *,
    max_files: int | None = 250,
    max_rows_per_file: int | None = 200,
) -> list[dict[str, object]]:
    base = Path(root)
    records, _artifacts, _skipped = discover_phase3_records(
        base,
        max_files=max_files,
        max_rows_per_file=max_rows_per_file,
    )
    records = [dict(record) for record in records]
    records.extend(_ledger_fixture_records(base))
    records.extend(_known_case_records(base))
    return records


def write_inventory_output(report: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def compact_inventory_report(report: Mapping[str, object], *, max_sample_rows: int = 200) -> dict[str, object]:
    compact = dict(report)
    rows = report.get("rows")
    if isinstance(rows, list):
        compact["sampleRows"] = rows[:max_sample_rows]
        compact["rowsOmittedFromOutput"] = max(len(rows) - max_sample_rows, 0)
        compact.pop("rows", None)
    return compact


def _ledger_fixture_records(root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for csv_path in sorted(root.glob("tests/fixtures/polymarket_ledger_artifacts/*/normalized_trades.csv")):
        records.extend(_read_csv_records(csv_path, "polymarket_ledger_fixture", "existing_test_fixture"))
    for csv_path in sorted(root.glob("tests/fixtures/reconstruction_shadow_pnl/*/normalized_trades.csv")):
        records.extend(_read_csv_records(csv_path, "reconstruction_ledger_fixture", "existing_test_fixture"))
    return records


def _known_case_records(root: Path) -> list[dict[str, object]]:
    path = root / "tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases", []) if isinstance(payload, Mapping) else []
    records: list[dict[str, object]] = []
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        row = dict(case)
        row["side"] = case.get("raw_side")
        row["outcome"] = case.get("raw_outcome")
        row["price"] = case.get("raw_token_price")
        row["artifactFamily"] = "known_case_benchmark"
        row["artifactEvidenceType"] = case.get("source_type") or "synthetic_fixture"
        row["artifactPath"] = str(path)
        records.append(row)
    return records


def _read_csv_records(path: Path, family: str, evidence_type: str) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            record: dict[str, object] = dict(row)
            record.setdefault("rowIndex", index)
            record["artifactFamily"] = family
            record["artifactEvidenceType"] = evidence_type
            record["artifactPath"] = str(path)
            rows.append(record)
    return rows


def _source_type(record: Mapping[str, object]) -> str:
    explicit = _text(record.get("source_type"))
    if explicit:
        return explicit
    family = str(record.get("artifactFamily") or "")
    if family in {"polymarket_ledger_fixture", "reconstruction_ledger_fixture", "reconstruction_normalized_trades_csv"}:
        return "normalized_trade"
    if family.endswith("_csv") and "trade" in family:
        return "raw_trade"
    if family in {"scanner_report_json", "archive_report_json", "event_forensic_json"}:
        return family
    if family:
        return family
    return "unknown"


def _is_direct_raw_trade_source(source_type: str) -> bool:
    return source_type in {"raw_trade", "normalized_trade", "reconstruction_ledger", "reconstruction_ledger_fixture"}


def _missing_notes(has_side: bool, has_outcome: bool, has_price: bool, has_size: bool) -> list[str]:
    notes: list[str] = []
    if not has_side:
        notes.append("missing_side")
    if not has_outcome:
        notes.append("missing_outcome")
    if not has_price:
        notes.append("missing_price")
    if not has_size:
        notes.append("missing_size")
    return notes


def _first_present(record: Mapping[str, object], keys: Iterable[str]) -> object:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _text(value: object) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _decimal_or_none(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        text = str(value).replace("%", "").replace(",", "").strip()
        decimal = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite():
        return None
    return decimal


def _decimal_text(value: Decimal | None) -> str:
    return str(value) if value is not None else UNKNOWN


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-files", type=int, default=250)
    parser.add_argument("--max-rows-per-file", type=int, default=200)
    parser.add_argument("--max-output-rows", type=int, default=200)
    parser.add_argument("--include-all-rows", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    records = discover_inventory_records(
        args.root,
        max_files=args.max_files,
        max_rows_per_file=args.max_rows_per_file,
    )
    report = build_source_inventory(records)
    output_report = report if args.include_all_rows else compact_inventory_report(report, max_sample_rows=args.max_output_rows)
    output = write_inventory_output(output_report, args.output_json)
    if not args.quiet:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
