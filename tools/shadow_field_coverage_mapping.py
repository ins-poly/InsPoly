#!/usr/bin/env python3
"""Sidecar-only field coverage mapping for advisory shadow metrics.

This tool reads local artifacts or static fixtures and reports whether their
existing field names can support the current shadow-metric input contract. It
does not compute production scores, mutate reports, or import scanner/archive/
event-forensic runtime paths.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


CLASS_AVAILABLE = "available"
CLASS_DERIVABLE = "derivable"
CLASS_MISSING = "missing"
CLASS_AMBIGUOUS = "ambiguous"
CLASS_INCOMPATIBLE = "incompatible"
CLASS_UNSAFE = "unsafe"

METRIC_COVERED = "covered"
METRIC_COVERED_WITH_DERIVATIONS = "covered_with_derivations"
METRIC_PARTIAL = "partial"
METRIC_MISSING = "missing"


@dataclass(frozen=True, slots=True)
class FieldCandidate:
    field: str
    classification: str
    note: str


@dataclass(frozen=True, slots=True)
class SlotCoverage:
    slot: str
    classification: str
    field: str | None
    note: str

    def to_dict(self) -> dict[str, object]:
        return {
            "slot": self.slot,
            "classification": self.classification,
            "field": self.field,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class MetricCoverage:
    metric: str
    status: str
    slots: tuple[SlotCoverage, ...]
    duplicate_production_semantics: tuple[str, ...]
    confusion_risks: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "status": self.status,
            "slots": [slot.to_dict() for slot in self.slots],
            "duplicateProductionSemantics": list(self.duplicate_production_semantics),
            "confusionRisks": list(self.confusion_risks),
        }


@dataclass(frozen=True, slots=True)
class ArtifactCoverage:
    family: str
    artifact_path: str
    observed_key_count: int
    metrics: tuple[MetricCoverage, ...]
    network_used: bool = False
    production_integration: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "artifactPath": self.artifact_path,
            "observedKeyCount": self.observed_key_count,
            "metrics": [metric.to_dict() for metric in self.metrics],
            "networkUsed": self.network_used,
            "productionIntegration": self.production_integration,
        }


METRIC_REQUIREMENTS: Mapping[str, tuple[str, ...]] = {
    "shadow_low_odds_position_size": ("order_side", "entry_price", "cash_amount"),
    "shadow_entry_price_edge": ("order_side", "entry_price", "reference_price"),
    "shadow_net_position_pnl": (
        "wallet",
        "condition_id",
        "token_id",
        "outcome",
        "order_side",
        "entry_price",
        "share_size",
        "cash_amount",
        "current_price",
    ),
    "shadow_win_rate_confidence": ("resolved_count", "win_count"),
    "shadow_microstructure_context": ("microstructure_snapshot",),
}


DUPLICATE_PRODUCTION_SEMANTICS: Mapping[str, tuple[str, ...]] = {
    "shadow_low_odds_position_size": ("trade_notional_usdc and positionSize already appear in reports",),
    "shadow_entry_price_edge": ("entry_vs_consensus and favorable_move fields already express timing/repricing context",),
    "shadow_net_position_pnl": ("wallet performance and open/closed position summaries already appear in several report paths",),
    "shadow_win_rate_confidence": ("wallet statistical prior and win-rate fields already exist in Event Forensic wallet context",),
    "shadow_microstructure_context": ("liquidity_ratio and liquidity_shock_signal are production context, not orderbook snapshots",),
}


CONFUSION_RISKS: Mapping[str, tuple[str, ...]] = {
    "shadow_low_odds_position_size": ("not_triggered may mean field mapping missing, not clean evidence",),
    "shadow_entry_price_edge": ("reference-price fields can encode hindsight or public-news reaction",),
    "shadow_net_position_pnl": ("PnL can be mistaken for proof instead of outcome context",),
    "shadow_win_rate_confidence": ("sample-size metrics can be confused with production labels",),
    "shadow_microstructure_context": ("stale snapshots can be confused with information edge",),
}


def candidate(field: str, classification: str, note: str) -> FieldCandidate:
    return FieldCandidate(field=field, classification=classification, note=note)


FAMILY_FIELD_CANDIDATES: Mapping[str, Mapping[str, tuple[FieldCandidate, ...]]] = {
    "recent_scanner_report_json": {
        "wallet": (candidate("cases[].trade.wallet", CLASS_AVAILABLE, "Exact wallet field."),),
        "condition_id": (candidate("cases[].trade.condition_id", CLASS_AVAILABLE, "Exact condition id field."),),
        "token_id": (candidate("cases[].trade.asset_id", CLASS_AVAILABLE, "Asset/token id field."),),
        "outcome": (candidate("cases[].trade.outcome", CLASS_AVAILABLE, "Outcome token label."),),
        "order_side": (candidate("cases[].trade.side", CLASS_AVAILABLE, "Order side is BUY/SELL."),),
        "entry_price": (candidate("cases[].trade.price", CLASS_AVAILABLE, "Trade entry price."),),
        "share_size": (candidate("cases[].trade.size", CLASS_AVAILABLE, "Trade share size."),),
        "cash_amount": (
            candidate("cases[].trade.notional", CLASS_DERIVABLE, "Trade notional is usable cash context but not source-distinguished."),
            candidate("cases[].raw_metrics.trade_notional_usdc", CLASS_DERIVABLE, "Report notional is usable but not Data API usdcSize."),
        ),
        "reference_price": (
            candidate("cases[].raw_metrics.favorable_move_1h", CLASS_AMBIGUOUS, "Move field is not a reference price."),
            candidate("cases[].raw_metrics.entry_vs_consensus_15m", CLASS_AMBIGUOUS, "Consensus edge is not a post-entry price."),
        ),
        "current_price": (),
        "resolved_count": (
            candidate("cases[].raw_metrics.wallet_closed_positions", CLASS_DERIVABLE, "Existing wallet-history sample count; duplicates production context."),
        ),
        "win_count": (
            candidate("cases[].raw_metrics.wallet_closed_wins", CLASS_DERIVABLE, "Existing wallet-history win count; duplicates production context."),
        ),
        "microstructure_snapshot": (
            candidate("cases[].raw_metrics.liquidity_ratio", CLASS_INCOMPATIBLE, "Market liquidity ratio is not an orderbook snapshot."),
        ),
    },
    "archive_report_json": {
        "wallet": (candidate("cases[].trade.wallet", CLASS_AVAILABLE, "Exact wallet field."),),
        "condition_id": (candidate("cases[].trade.condition_id", CLASS_AVAILABLE, "Exact condition id field."),),
        "token_id": (candidate("cases[].trade.asset_id", CLASS_AVAILABLE, "Asset/token id field."),),
        "outcome": (candidate("cases[].trade.outcome", CLASS_AVAILABLE, "Outcome token label."),),
        "order_side": (candidate("cases[].trade.side", CLASS_AVAILABLE, "Order side is BUY/SELL."),),
        "entry_price": (candidate("cases[].trade.price", CLASS_AVAILABLE, "Trade entry price."),),
        "share_size": (candidate("cases[].trade.size", CLASS_AVAILABLE, "Trade share size."),),
        "cash_amount": (
            candidate("cases[].trade.notional", CLASS_DERIVABLE, "Trade notional is usable cash context but not source-distinguished."),
            candidate("cases[].raw_metrics.trade_notional_usdc", CLASS_DERIVABLE, "Report notional is usable but not Data API usdcSize."),
        ),
        "reference_price": (
            candidate("cases[].raw_metrics.favorable_move_1h", CLASS_AMBIGUOUS, "Move field is not a reference price."),
            candidate("cases[].raw_metrics.entry_vs_consensus_15m", CLASS_AMBIGUOUS, "Consensus edge is not a post-entry price."),
        ),
        "current_price": (),
        "resolved_count": (
            candidate("cases[].raw_metrics.wallet_closed_positions", CLASS_DERIVABLE, "Existing wallet-history sample count; duplicates production context."),
            candidate("cases[].raw_metrics.wallet_economic_sample_size", CLASS_DERIVABLE, "Economic sample count is already production context."),
        ),
        "win_count": (
            candidate("cases[].raw_metrics.wallet_closed_wins", CLASS_DERIVABLE, "Existing wallet-history win count; duplicates production context."),
        ),
        "microstructure_snapshot": (
            candidate("cases[].raw_metrics.liquidity_shock_signal", CLASS_UNSAFE, "Production liquidity-shock boolean is not raw microstructure."),
            candidate("cases[].raw_metrics.liquidity_ratio", CLASS_INCOMPATIBLE, "Market liquidity ratio is not an orderbook snapshot."),
        ),
    },
    "archive_flagged_csv": {
        "wallet": (candidate("wallet", CLASS_AVAILABLE, "Wallet column."),),
        "condition_id": (),
        "token_id": (),
        "outcome": (candidate("outcome", CLASS_AVAILABLE, "Outcome token label."),),
        "order_side": (candidate("side", CLASS_AVAILABLE, "Archive CSV side is order side."),),
        "entry_price": (),
        "share_size": (),
        "cash_amount": (candidate("trade_notional_usdc", CLASS_DERIVABLE, "Notional cash is present but not source-distinguished."),),
        "reference_price": (
            candidate("favorable_move_1h", CLASS_AMBIGUOUS, "Move field is not a reference price."),
            candidate("entry_vs_consensus_15m", CLASS_AMBIGUOUS, "Consensus edge is not a post-entry price."),
        ),
        "current_price": (),
        "resolved_count": (candidate("wallet_closed_positions", CLASS_DERIVABLE, "Existing production wallet sample count."),),
        "win_count": (),
        "microstructure_snapshot": (
            candidate("liquidity_shock_signal", CLASS_UNSAFE, "Production signal, not raw orderbook snapshot."),
        ),
    },
    "event_forensic_event_analysis_json": {
        "wallet": (candidate("display_trades[].wallet", CLASS_AVAILABLE, "Display trade wallet."),),
        "condition_id": (candidate("display_trades[].conditionId", CLASS_AVAILABLE, "Display trade condition id."),),
        "token_id": (),
        "outcome": (candidate("display_trades[].side", CLASS_AVAILABLE, "Event display side is outcome label."),),
        "order_side": (candidate("display_trades[].orderSide", CLASS_AVAILABLE, "Order side is BUY/SELL."),),
        "entry_price": (candidate("display_trades[].price", CLASS_AVAILABLE, "Event display trade entry price."),),
        "share_size": (candidate("display_trades[].positionSize", CLASS_AMBIGUOUS, "Position size is notional-like exposure, not shares."),),
        "cash_amount": (candidate("display_trades[].positionSize", CLASS_DERIVABLE, "Position size is usable cash/exposure context."),),
        "reference_price": (
            candidate("display_trades[].laterWon", CLASS_UNSAFE, "Outcome correctness is production forensic context, not a reference price."),
            candidate("display_trades[].winnerRank", CLASS_UNSAFE, "Winner rank is production retrospective context."),
        ),
        "current_price": (),
        "resolved_count": (
            candidate("display_wallets[].walletResolvedSampleSize", CLASS_DERIVABLE, "Existing wallet statistical-prior sample size."),
        ),
        "win_count": (
            candidate("display_wallets[].walletResolvedWinRate", CLASS_AMBIGUOUS, "Win count would be inferred from a rounded rate."),
        ),
        "microstructure_snapshot": (),
    },
    "event_forensic_suspicious_trades_csv": {
        "wallet": (candidate("wallet", CLASS_AVAILABLE, "Wallet column."),),
        "condition_id": (candidate("conditionId", CLASS_AVAILABLE, "Condition id column."),),
        "token_id": (),
        "outcome": (candidate("side", CLASS_AVAILABLE, "Event CSV side is outcome label."),),
        "order_side": (candidate("orderSide", CLASS_AVAILABLE, "Order side is BUY/SELL."),),
        "entry_price": (candidate("price", CLASS_AVAILABLE, "Present in newer Event Forensic CSVs; absent in older slim exports."),),
        "share_size": (candidate("positionSize", CLASS_AMBIGUOUS, "Position size is notional-like exposure, not shares."),),
        "cash_amount": (candidate("positionSize", CLASS_DERIVABLE, "Position size is usable cash/exposure context."),),
        "reference_price": (
            candidate("laterWon", CLASS_UNSAFE, "Outcome correctness is production forensic context, not reference price."),
        ),
        "current_price": (),
        "resolved_count": (),
        "win_count": (),
        "microstructure_snapshot": (),
    },
    "event_forensic_wallet_context_csv": {
        "wallet": (candidate("wallet", CLASS_AVAILABLE, "Wallet column."),),
        "condition_id": (),
        "token_id": (),
        "outcome": (),
        "order_side": (),
        "entry_price": (),
        "share_size": (),
        "cash_amount": (),
        "reference_price": (),
        "current_price": (),
        "resolved_count": (
            candidate("walletResolvedSampleSize", CLASS_DERIVABLE, "Existing wallet statistical-prior sample size."),
        ),
        "win_count": (
            candidate("walletResolvedWinRate", CLASS_AMBIGUOUS, "Win count would be inferred from rounded win rate."),
        ),
        "microstructure_snapshot": (),
    },
    "case_specific_ceasefire_suspicious_trades_csv": {
        "wallet": (candidate("wallet", CLASS_AVAILABLE, "Wallet column."),),
        "condition_id": (candidate("condition_id", CLASS_AVAILABLE, "Condition id column."),),
        "token_id": (),
        "outcome": (candidate("outcome", CLASS_AVAILABLE, "Outcome token label."),),
        "order_side": (candidate("order_side", CLASS_AVAILABLE, "Order side is BUY/SELL."), candidate("side", CLASS_AVAILABLE, "Side also carries BUY/SELL in this case-specific file.")),
        "entry_price": (candidate("price", CLASS_AVAILABLE, "Trade entry price."),),
        "share_size": (candidate("size", CLASS_AVAILABLE, "Share size column."),),
        "cash_amount": (candidate("notional_usdc", CLASS_DERIVABLE, "Cash exposure is present but not source-distinguished."),),
        "reference_price": (
            candidate("price_move_after_entry", CLASS_AMBIGUOUS, "Move field is not a reference price without reconstruction."),
            candidate("price_move_to_anchor", CLASS_AMBIGUOUS, "Anchor move is case-specific timing context."),
        ),
        "current_price": (),
        "resolved_count": (),
        "win_count": (),
        "microstructure_snapshot": (),
    },
    "reconstruction_normalized_trades_csv": {
        "wallet": (),
        "condition_id": (candidate("conditionId", CLASS_AVAILABLE, "Condition id column."),),
        "token_id": (candidate("asset", CLASS_AVAILABLE, "Token/asset id column."),),
        "outcome": (candidate("outcome", CLASS_AVAILABLE, "Outcome token label."),),
        "order_side": (candidate("side", CLASS_AVAILABLE, "Order side is BUY/SELL."),),
        "entry_price": (candidate("price", CLASS_AVAILABLE, "Trade entry price."),),
        "share_size": (candidate("shares", CLASS_AVAILABLE, "Share size column."),),
        "cash_amount": (
            candidate("api_usdc_size", CLASS_AVAILABLE, "Explicit Data API usdcSize/cash source."),
            candidate("recomputed_size_x_price", CLASS_DERIVABLE, "Recomputed cash is available for reconciliation."),
        ),
        "reference_price": (),
        "current_price": (),
        "resolved_count": (),
        "win_count": (),
        "microstructure_snapshot": (),
    },
    "reconstruction_report_dir": {
        "wallet": (candidate("raw_positions_current.json:base_params.user", CLASS_DERIVABLE, "Wallet is available from raw positions request parameters."),),
        "condition_id": (
            candidate("normalized_trades.csv:conditionId", CLASS_AVAILABLE, "Condition id in normalized trades."),
            candidate("raw_positions_current.json:rows[].conditionId", CLASS_AVAILABLE, "Condition id in current positions."),
        ),
        "token_id": (
            candidate("normalized_trades.csv:asset", CLASS_AVAILABLE, "Asset id in normalized trades."),
            candidate("raw_positions_current.json:rows[].asset", CLASS_AVAILABLE, "Asset id in current positions."),
        ),
        "outcome": (
            candidate("normalized_trades.csv:outcome", CLASS_AVAILABLE, "Outcome in normalized trades."),
            candidate("raw_positions_current.json:rows[].outcome", CLASS_AVAILABLE, "Outcome in current positions."),
        ),
        "order_side": (candidate("normalized_trades.csv:side", CLASS_AVAILABLE, "Order side is BUY/SELL."),),
        "entry_price": (candidate("normalized_trades.csv:price", CLASS_AVAILABLE, "Trade entry price."),),
        "share_size": (candidate("normalized_trades.csv:shares", CLASS_AVAILABLE, "Share size column."),),
        "cash_amount": (
            candidate("normalized_trades.csv:api_usdc_size", CLASS_AVAILABLE, "Explicit Data API usdcSize/cash source."),
            candidate("normalized_trades.csv:recomputed_size_x_price", CLASS_DERIVABLE, "Recomputed cash is available for source disagreement checks."),
        ),
        "reference_price": (),
        "current_price": (
            candidate("raw_positions_current.json:rows[].curPrice", CLASS_AVAILABLE, "Current price from Data API positions."),
            candidate("summary_calculations.csv:metric:current_price_yes_api", CLASS_AVAILABLE, "Summary current price metric."),
        ),
        "resolved_count": (candidate("summary_calculations.csv:metric:closed_position_rows", CLASS_DERIVABLE, "Closed row count is available but not win count."),),
        "win_count": (),
        "microstructure_snapshot": (),
    },
}


def coverage_for_artifact(family: str, path: str | Path) -> ArtifactCoverage:
    if family not in FAMILY_FIELD_CANDIDATES:
        raise ValueError(f"Unsupported artifact family: {family}")
    artifact_path = Path(path)
    keys = _observed_keys(family, artifact_path)
    metrics = tuple(_metric_coverage(metric, keys, FAMILY_FIELD_CANDIDATES[family]) for metric in METRIC_REQUIREMENTS)
    return ArtifactCoverage(
        family=family,
        artifact_path=str(artifact_path),
        observed_key_count=len(keys),
        metrics=metrics,
    )


def artifact_families() -> tuple[str, ...]:
    return tuple(FAMILY_FIELD_CANDIDATES)


def _metric_coverage(
    metric: str,
    observed_keys: set[str],
    field_candidates: Mapping[str, tuple[FieldCandidate, ...]],
) -> MetricCoverage:
    slots = tuple(_slot_coverage(slot, observed_keys, field_candidates) for slot in METRIC_REQUIREMENTS[metric])
    classifications = {slot.classification for slot in slots}
    if classifications <= {CLASS_AVAILABLE}:
        status = METRIC_COVERED
    elif classifications <= {CLASS_AVAILABLE, CLASS_DERIVABLE}:
        status = METRIC_COVERED_WITH_DERIVATIONS
    elif CLASS_MISSING in classifications:
        status = METRIC_MISSING
    else:
        status = METRIC_PARTIAL
    return MetricCoverage(
        metric=metric,
        status=status,
        slots=slots,
        duplicate_production_semantics=DUPLICATE_PRODUCTION_SEMANTICS.get(metric, ()),
        confusion_risks=CONFUSION_RISKS.get(metric, ()),
    )


def _slot_coverage(
    slot: str,
    observed_keys: set[str],
    field_candidates: Mapping[str, tuple[FieldCandidate, ...]],
) -> SlotCoverage:
    candidates = field_candidates.get(slot, ())
    matched = [candidate for candidate in candidates if candidate.field in observed_keys]
    if not matched:
        return SlotCoverage(slot=slot, classification=CLASS_MISSING, field=None, note="No compatible field observed.")
    matched.sort(key=lambda item: _classification_rank(item.classification))
    best = matched[0]
    return SlotCoverage(slot=slot, classification=best.classification, field=best.field, note=best.note)


def _classification_rank(classification: str) -> int:
    return {
        CLASS_AVAILABLE: 0,
        CLASS_DERIVABLE: 1,
        CLASS_AMBIGUOUS: 2,
        CLASS_INCOMPATIBLE: 3,
        CLASS_UNSAFE: 4,
    }.get(classification, 99)


def _observed_keys(family: str, path: Path) -> set[str]:
    if family == "reconstruction_report_dir":
        return _observed_reconstruction_dir(path)
    if path.suffix.lower() == ".json":
        return _flatten_json_keys(json.loads(path.read_text(encoding="utf-8")))
    if path.suffix.lower() == ".csv":
        return _csv_keys(path)
    raise ValueError(f"Unsupported artifact file for {family}: {path}")


def _observed_reconstruction_dir(path: Path) -> set[str]:
    keys: set[str] = set()
    normalized = path / "normalized_trades.csv"
    if normalized.exists():
        keys.update(f"normalized_trades.csv:{key}" for key in _csv_keys(normalized))
    summary = path / "summary_calculations.csv"
    if summary.exists():
        keys.update(_summary_metric_keys(summary))
    raw_current = path / "raw_positions_current.json"
    if raw_current.exists():
        payload = json.loads(raw_current.read_text(encoding="utf-8"))
        keys.update(f"raw_positions_current.json:{key}" for key in _flatten_json_keys(payload))
    raw_closed = path / "raw_positions_closed.json"
    if raw_closed.exists():
        payload = json.loads(raw_closed.read_text(encoding="utf-8"))
        keys.update(f"raw_positions_closed.json:{key}" for key in _flatten_json_keys(payload))
    return keys


def _csv_keys(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return set(reader.fieldnames or ())


def _summary_metric_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            metric = str(row.get("metric") or "").strip()
            if metric:
                keys.add(f"summary_calculations.csv:metric:{metric}")
    return keys


def _flatten_json_keys(payload: object, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            keys.add(path)
            keys.update(_flatten_json_keys(value, path))
    elif isinstance(payload, list):
        list_prefix = f"{prefix}[]" if prefix else "[]"
        keys.add(list_prefix)
        for item in payload:
            keys.update(_flatten_json_keys(item, list_prefix))
    return keys


def coverage_report(family_paths: Sequence[tuple[str, str | Path]]) -> dict[str, object]:
    coverages = [coverage_for_artifact(family, path).to_dict() for family, path in family_paths]
    return {
        "reportType": "shadow_field_coverage_mapping",
        "networkUsed": False,
        "productionIntegration": False,
        "artifacts": coverages,
    }


def markdown_report(report: Mapping[str, object]) -> str:
    lines = [
        "# Shadow Field Coverage Mapping",
        "",
        f"- Network used: {str(report.get('networkUsed')).lower()}",
        f"- Production integration: {str(report.get('productionIntegration')).lower()}",
        "",
    ]
    for artifact in report.get("artifacts", []):
        if not isinstance(artifact, Mapping):
            continue
        lines.extend(
            [
                f"## {artifact.get('family')}",
                "",
                f"- Artifact: `{artifact.get('artifactPath')}`",
                f"- Observed keys: {artifact.get('observedKeyCount')}",
                "",
                "| Metric | Status | Missing / ambiguous / unsafe slots |",
                "| --- | --- | --- |",
            ]
        )
        for metric in artifact.get("metrics", []):
            if not isinstance(metric, Mapping):
                continue
            slots = [
                str(slot.get("slot"))
                for slot in metric.get("slots", [])
                if isinstance(slot, Mapping)
                and slot.get("classification") not in {CLASS_AVAILABLE, CLASS_DERIVABLE}
            ]
            lines.append(
                f"| `{metric.get('metric')}` | `{metric.get('status')}` | {', '.join(slots) or 'none'} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _parse_artifact_arg(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Artifact must use FAMILY=PATH format")
    family, path = value.split("=", 1)
    family = family.strip()
    if family not in FAMILY_FIELD_CANDIDATES:
        raise argparse.ArgumentTypeError(f"Unsupported family: {family}")
    return family, path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate sidecar shadow field coverage for local artifacts.")
    parser.add_argument(
        "--artifact",
        action="append",
        type=_parse_artifact_arg,
        default=[],
        metavar="FAMILY=PATH",
        help="Artifact family/path pair. Repeat for multiple artifacts.",
    )
    parser.add_argument("--list-families", action="store_true", help="Print supported artifact families.")
    parser.add_argument("--output-json", help="Optional path for JSON coverage output.")
    parser.add_argument("--output-md", help="Optional path for Markdown coverage output.")
    args = parser.parse_args(argv)

    if args.list_families:
        print("\n".join(artifact_families()))
        return 0
    if not args.artifact:
        parser.error("At least one --artifact FAMILY=PATH is required unless --list-families is used.")

    report = coverage_report(args.artifact)
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(markdown_report(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
