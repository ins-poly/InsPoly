#!/usr/bin/env python3
"""Read-only ledger cross-check for Phase 3 capital-at-risk semantics."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.polymarket_ledger import build_position_ledgers, normalize_ledger_trade  # noqa: E402
from app.side_outcome import UNKNOWN, normalize_side_outcome  # noqa: E402


REPORT_TYPE = "phase3_capital_ledger_crosscheck"
SCHEMA_VERSION = "phase3_capital_ledger_crosscheck_v1"
DEFAULT_OUTPUT = Path("validation_outputs/phase3_capital_ledger_crosscheck_20260525.json")
CENT = Decimal("0.01")


def evaluate_ledger_capital_row(row: Mapping[str, object], *, artifact_path: str = "", input_index: int = 0) -> dict[str, object]:
    normalized_trade = normalize_ledger_trade(row, input_index=input_index)
    side_outcome = normalize_side_outcome(normalized_trade.side, normalized_trade.key.outcome, normalized_trade.price)
    size = normalized_trade.size
    price = normalized_trade.price
    raw_notional = _quantize(size * price) if price is not None else None
    observed_cash = normalized_trade.cash
    economic_exposure, exposure_source = _economic_exposure(normalized_trade.side, size, price, observed_cash)
    delta = (
        _quantize(economic_exposure - raw_notional)
        if economic_exposure is not None and raw_notional is not None
        else None
    )
    notes = list(normalized_trade.quality_notes)
    if normalized_trade.side == "SELL" and normalized_trade.explicit_cash is not None:
        notes.append("usdcSize_is_observed_cash_not_sell_max_loss")
    if normalized_trade.side == "SELL" and economic_exposure is not None:
        notes.append("sell_max_loss_computed_from_complement_formula")
    if economic_exposure is None:
        notes.append("economic_exposure_unknown")
    return {
        "artifactPath": artifact_path,
        "inputIndex": input_index,
        "wallet": normalized_trade.key.wallet,
        "conditionId": normalized_trade.key.condition_id,
        "tokenId": normalized_trade.key.token_id,
        "outcome": normalized_trade.key.outcome,
        "rawOrderSide": side_outcome.raw_order_side,
        "rawTokenOutcome": side_outcome.raw_token_outcome,
        "rawTokenPrice": _decimal_text(price),
        "size": _decimal_text(size),
        "cashSource": normalized_trade.cash_source,
        "observedCash": _decimal_text(observed_cash),
        "currentRawNotionalAssumption": _decimal_text(raw_notional),
        "ledgerDerivedEconomicExposure": _decimal_text(economic_exposure),
        "ledgerExposureSource": exposure_source,
        "capitalDelta": _decimal_text(delta),
        "safeForSellMaxLoss": normalized_trade.side == "SELL" and economic_exposure is not None,
        "qualityNotes": sorted(set(notes)),
    }


def build_ledger_crosscheck(artifact_dirs: Sequence[str | Path]) -> dict[str, object]:
    artifact_reports: list[dict[str, object]] = []
    all_rows: list[dict[str, object]] = []
    for artifact_dir in artifact_dirs:
        root = Path(artifact_dir)
        csv_path = root / "normalized_trades.csv"
        rows = _read_csv(csv_path)
        book = build_position_ledgers(rows)
        row_reports = [
            evaluate_ledger_capital_row(row, artifact_path=str(csv_path), input_index=index)
            for index, row in enumerate(rows)
        ]
        artifact_reports.append(
            {
                "artifactDir": str(root),
                "rowsLoaded": len(rows),
                "positionCount": len(book.positions),
                "safeSellMaxLossRows": sum(1 for row in row_reports if row["safeForSellMaxLoss"]),
                "cashSources": sorted({row["cashSource"] for row in row_reports}),
                "qualityNotes": sorted({note for position in book.positions for note in position.quality_notes}),
            }
        )
        all_rows.extend(row_reports)

    source_counts = Counter(row["ledgerExposureSource"] for row in all_rows)
    note_counts = Counter(note for row in all_rows for note in row["qualityNotes"])
    summary = {
        "artifactDirsEvaluated": len(artifact_reports),
        "rowsEvaluated": len(all_rows),
        "sellRows": sum(1 for row in all_rows if row["rawOrderSide"] == "SELL"),
        "safeSellMaxLossRows": sum(1 for row in all_rows if row["safeForSellMaxLoss"]),
        "rowsWhereUsdcSizeIsObservedCashNotMaxLoss": sum(
            1 for row in all_rows if "usdcSize_is_observed_cash_not_sell_max_loss" in row["qualityNotes"]
        ),
        "unknownExposureRows": sum(1 for row in all_rows if row["ledgerDerivedEconomicExposure"] == UNKNOWN),
        "ledgerExposureSourceCounts": dict(sorted(source_counts.items())),
        "qualityNoteCounts": dict(sorted(note_counts.items())),
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
        "artifacts": artifact_reports,
        "rows": all_rows,
    }


def discover_ledger_artifact_dirs(root: str | Path = ".") -> list[Path]:
    base = Path(root)
    dirs: set[Path] = set()
    for csv_path in base.glob("tests/fixtures/polymarket_ledger_artifacts/*/normalized_trades.csv"):
        dirs.add(csv_path.parent)
    for csv_path in base.glob("tests/fixtures/reconstruction_shadow_pnl/*/normalized_trades.csv"):
        dirs.add(csv_path.parent)
    for csv_path in base.glob("tests/fixtures/shadow_field_coverage/reconstruction_report/normalized_trades.csv"):
        dirs.add(csv_path.parent)
    for csv_path in base.glob("tests/fixtures/shadow_input_normalization/reconstruction_report/normalized_trades.csv"):
        dirs.add(csv_path.parent)
    return sorted(dirs)


def write_crosscheck_output(report: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _economic_exposure(side: str, size: Decimal, price: Decimal | None, observed_cash: Decimal | None) -> tuple[Decimal | None, str]:
    if side == "BUY":
        if observed_cash is not None:
            return _quantize(observed_cash), "observed_cash_paid"
        if price is not None:
            return _quantize(size * price), "size_price_cash_paid"
        return None, "unknown"
    if side == "SELL":
        if price is None:
            return None, "unknown"
        return _quantize(size * (Decimal("1") - price)), "size_complement_price_max_loss"
    return None, "unknown"


def _read_csv(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def _decimal_text(value: Decimal | None) -> str:
    return str(value) if value is not None else UNKNOWN


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--artifact-dir", action="append", default=[])
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    artifact_dirs = [Path(path) for path in args.artifact_dir] if args.artifact_dir else discover_ledger_artifact_dirs(args.root)
    report = build_ledger_crosscheck(artifact_dirs)
    output = write_crosscheck_output(report, args.output_json)
    if not args.quiet:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
