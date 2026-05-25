#!/usr/bin/env python3
"""Normalize selected local artifacts into advisory shadow-metric inputs.

This sidecar tool is intentionally narrow. It reads local saved artifacts or
static fixtures and emits normalized shadow input records with provenance and
quality notes. It does not mutate source artifacts, write production reports,
or import scanner/archive/event-forensic runtime paths.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.shadow_field_coverage_mapping import CLASS_AVAILABLE, CLASS_DERIVABLE  # noqa: E402


REPORT_TYPE = "shadow_input_normalization"
SCHEMA_VERSION = "shadow_input_normalization_v1"

STATUS_AVAILABLE = "available"
STATUS_UNKNOWN = "unknown"
STATUS_NOT_COMPUTED = "not_computed"

RECORD_TRADE_EXPOSURE = "trade_exposure"
RECORD_LEDGER_TRADE = "ledger_trade"
RECORD_WALLET_HISTORY = "wallet_history"
RECORD_CURRENT_PRICE = "current_price"

METRIC_LOW_ODDS = "shadow_low_odds_position_size"
METRIC_ENTRY_EDGE = "shadow_entry_price_edge"
METRIC_NET_PNL = "shadow_net_position_pnl"
METRIC_WIN_RATE = "shadow_win_rate_confidence"
METRIC_MICROSTRUCTURE = "shadow_microstructure_context"

SUPPORTED_FAMILIES = (
    "recent_scanner_report_json",
    "archive_report_json",
    "event_forensic_event_analysis_json",
    "reconstruction_report_dir",
)

METRIC_ORDER = (
    METRIC_LOW_ODDS,
    METRIC_ENTRY_EDGE,
    METRIC_NET_PNL,
    METRIC_WIN_RATE,
    METRIC_MICROSTRUCTURE,
)

FORBIDDEN_OUTPUT_KEYS = {
    "risk_level",
    "riskLevel",
    "severity",
    "Strong Risk",
    "strongRisk",
    "Hard Evidence Review",
    "hardEvidenceReview",
    "HER",
    "candidateAdmission",
    "candidate_admission",
    "fundingEligibility",
    "funding_eligibility",
    "eventForensicScore",
    "existingModelScore",
    "sorting",
    "sortKey",
    "laterWon",
    "winnerRank",
    "liquidity_shock_signal",
    "liquidityShockSignal",
}

SAFE_SKIP_KEYS = {
    "risk_level",
    "riskLevel",
    "severity",
    "suspicion_score",
    "Strong Risk",
    "strongRisk",
    "Hard Evidence Review",
    "hardEvidenceReview",
    "HER",
    "candidateAdmission",
    "candidate_admission",
    "fundingEligibility",
    "funding_eligibility",
    "eventForensicScore",
    "existingModelScore",
    "laterWon",
    "winnerRank",
    "liquidity_shock_signal",
    "liquidityShockSignal",
    "finalEventJudgment",
    "walletStatisticalPriorLabel",
}


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    field: str
    source_field: str
    classification: str
    note: str

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "sourceField": self.source_field,
            "classification": self.classification,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class NormalizedInputRecord:
    record_id: str
    record_type: str
    target_metrics: tuple[str, ...]
    fields: Mapping[str, object]
    provenance: tuple[FieldProvenance, ...]
    quality_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "recordId": self.record_id,
            "recordType": self.record_type,
            "targetMetrics": list(self.target_metrics),
            "fields": dict(self.fields),
            "provenance": [item.to_dict() for item in self.provenance],
            "qualityNotes": list(self.quality_notes),
        }


@dataclass(frozen=True, slots=True)
class MetricReadiness:
    metric: str
    status: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {"metric": self.metric, "status": self.status, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ArtifactNormalization:
    family: str
    artifact_path: str
    normalized_records: tuple[NormalizedInputRecord, ...]
    metric_readiness: tuple[MetricReadiness, ...]
    current_prices: Mapping[str, object] = field(default_factory=dict)
    quality_notes: tuple[str, ...] = ()
    skipped_unsafe_field_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "artifactPath": self.artifact_path,
            "recordCount": len(self.normalized_records),
            "normalizedRecords": [record.to_dict() for record in self.normalized_records],
            "currentPrices": dict(self.current_prices),
            "metricReadiness": [item.to_dict() for item in self.metric_readiness],
            "qualityNotes": list(self.quality_notes),
            "skippedUnsafeFieldCount": self.skipped_unsafe_field_count,
        }


def supported_families() -> tuple[str, ...]:
    return SUPPORTED_FAMILIES


def normalize_artifact(family: str, path: str | Path) -> ArtifactNormalization:
    if family not in SUPPORTED_FAMILIES:
        raise ValueError(f"Unsupported Phase 9D artifact family: {family}")
    artifact_path = Path(path)
    if family == "recent_scanner_report_json":
        return _normalize_recent_or_archive(
            family,
            artifact_path,
            include_wallet_history=False,
            source_label="recent scanner report",
        )
    if family == "archive_report_json":
        return _normalize_recent_or_archive(
            family,
            artifact_path,
            include_wallet_history=True,
            source_label="archive report",
        )
    if family == "event_forensic_event_analysis_json":
        return _normalize_event_forensic_json(artifact_path)
    if family == "reconstruction_report_dir":
        return _normalize_reconstruction_report_dir(artifact_path)
    raise AssertionError(f"Unhandled family: {family}")


def normalize_artifacts(family_paths: Sequence[tuple[str, str | Path]]) -> dict[str, object]:
    artifacts = [normalize_artifact(family, path).to_dict() for family, path in family_paths]
    report: dict[str, object] = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "networkUsed": False,
        "productionIntegration": False,
        "artifacts": artifacts,
    }
    _assert_no_forbidden_output_keys(report)
    return report


def write_normalization_outputs(report: Mapping[str, object], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"shadow_input_normalization_{stamp}.json"
    md_path = target / f"shadow_input_normalization_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: Mapping[str, object]) -> str:
    lines = [
        "# Shadow Input Normalization",
        "",
        f"- Schema: `{report.get('schemaVersion')}`",
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
                f"- Records: {artifact.get('recordCount')}",
                f"- Skipped unsafe fields: {artifact.get('skippedUnsafeFieldCount')}",
                "",
                "| Metric | Status | Reason |",
                "| --- | --- | --- |",
            ]
        )
        for item in artifact.get("metricReadiness", []):
            if isinstance(item, Mapping):
                lines.append(f"| `{item.get('metric')}` | `{item.get('status')}` | {item.get('reason')} |")
        notes = artifact.get("qualityNotes")
        if isinstance(notes, list) and notes:
            lines.extend(["", "Quality notes:"])
            lines.extend(f"- {note}" for note in notes)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _normalize_recent_or_archive(
    family: str,
    artifact_path: Path,
    *,
    include_wallet_history: bool,
    source_label: str,
) -> ArtifactNormalization:
    payload = _read_json_object(artifact_path)
    cases = payload.get("cases")
    case_rows = cases if isinstance(cases, list) else []
    records: list[NormalizedInputRecord] = []
    notes: set[str] = set()
    skipped = _count_skipped_unsafe(payload)

    for index, case in enumerate(case_rows):
        if not isinstance(case, Mapping):
            continue
        trade = case.get("trade")
        raw_metrics = case.get("raw_metrics")
        if not isinstance(trade, Mapping):
            continue
        raw_metrics = raw_metrics if isinstance(raw_metrics, Mapping) else {}

        exposure = _scanner_trade_exposure_record(
            index=index,
            family=family,
            trade=trade,
            raw_metrics=raw_metrics,
            source_label=source_label,
        )
        if exposure is not None:
            records.append(exposure)
            notes.update(exposure.quality_notes)

        if include_wallet_history:
            history = _archive_wallet_history_record(index=index, trade=trade, raw_metrics=raw_metrics)
            if history is not None:
                records.append(history)
                notes.update(history.quality_notes)

    readiness = _readiness(
        available={
            METRIC_LOW_ODDS: "safe low-odds exposure records normalized"
        }
        | (
            {METRIC_WIN_RATE: "archive wallet-history records normalized from closed-position counts"}
            if include_wallet_history and any(record.record_type == RECORD_WALLET_HISTORY for record in records)
            else {}
        ),
        not_computed={
            METRIC_ENTRY_EDGE: "reference price is missing or ambiguous in Phase 9C mapping",
            METRIC_NET_PNL: "current price is missing from scanner/archive report artifacts",
            METRIC_MICROSTRUCTURE: "liquidity fields are incompatible or unsafe, not orderbook snapshots",
        },
    )
    if include_wallet_history and not any(record.record_type == RECORD_WALLET_HISTORY for record in records):
        readiness = _replace_readiness(
            readiness,
            MetricReadiness(METRIC_WIN_RATE, STATUS_UNKNOWN, "wallet closed-position win counts unavailable"),
        )
    return ArtifactNormalization(
        family=family,
        artifact_path=str(artifact_path),
        normalized_records=tuple(records),
        metric_readiness=readiness,
        quality_notes=tuple(sorted(notes)),
        skipped_unsafe_field_count=skipped,
    )


def _scanner_trade_exposure_record(
    *,
    index: int,
    family: str,
    trade: Mapping[str, object],
    raw_metrics: Mapping[str, object],
    source_label: str,
) -> NormalizedInputRecord | None:
    fields: dict[str, object] = {}
    provenance: list[FieldProvenance] = []
    notes: set[str] = set()

    _map_available(fields, provenance, "wallet", trade, "wallet", f"cases[{index}].trade.wallet")
    _map_available(fields, provenance, "condition_id", trade, "condition_id", f"cases[{index}].trade.condition_id")
    _map_available(fields, provenance, "token_id", trade, "asset_id", f"cases[{index}].trade.asset_id")
    _map_available(fields, provenance, "outcome", trade, "outcome", f"cases[{index}].trade.outcome")
    _map_available(fields, provenance, "side", trade, "side", f"cases[{index}].trade.side")
    _map_available(fields, provenance, "price", trade, "price", f"cases[{index}].trade.price")
    _map_available(fields, provenance, "size", trade, "size", f"cases[{index}].trade.size")
    _map_optional_available(fields, provenance, "timestamp", trade, "timestamp", f"cases[{index}].trade.timestamp")

    cash_source = None
    if _has_value(trade.get("notional")):
        cash_source = (trade, "notional", f"cases[{index}].trade.notional")
    elif _has_value(raw_metrics.get("trade_notional_usdc")):
        cash_source = (raw_metrics, "trade_notional_usdc", f"cases[{index}].raw_metrics.trade_notional_usdc")
    if cash_source is None:
        notes.add("cash_amount_missing_not_normalized")
    else:
        source, source_key, source_field = cash_source
        _map_derivable(
            fields,
            provenance,
            "cash_amount",
            source,
            source_key,
            source_field,
            f"cash amount derived from {source_label} notional; cash source is not Data API usdcSize",
        )
        notes.add("cash_amount_from_report_notional_derivable")

    required = ("side", "price", "cash_amount")
    if any(not _has_value(fields.get(key)) for key in required):
        return None
    return NormalizedInputRecord(
        record_id=f"{family}:case:{index}:low_odds",
        record_type=RECORD_TRADE_EXPOSURE,
        target_metrics=(METRIC_LOW_ODDS,),
        fields=fields,
        provenance=tuple(provenance),
        quality_notes=tuple(sorted(notes)),
    )


def _archive_wallet_history_record(
    *,
    index: int,
    trade: Mapping[str, object],
    raw_metrics: Mapping[str, object],
) -> NormalizedInputRecord | None:
    fields: dict[str, object] = {}
    provenance: list[FieldProvenance] = []
    notes: set[str] = set()

    _map_available(fields, provenance, "wallet", trade, "wallet", f"cases[{index}].trade.wallet")
    _map_derivable(
        fields,
        provenance,
        "resolved_trades",
        raw_metrics,
        "wallet_closed_positions",
        f"cases[{index}].raw_metrics.wallet_closed_positions",
        "resolved trade sample count derived from existing archive wallet-history field",
    )
    _map_derivable(
        fields,
        provenance,
        "winning_trades",
        raw_metrics,
        "wallet_closed_wins",
        f"cases[{index}].raw_metrics.wallet_closed_wins",
        "winning trade count derived from existing archive wallet-history field",
    )
    notes.add("wallet_history_from_existing_archive_fields_derivable")

    if any(not _has_value(fields.get(key)) for key in ("wallet", "resolved_trades", "winning_trades")):
        return None
    return NormalizedInputRecord(
        record_id=f"archive_report_json:case:{index}:wallet_history",
        record_type=RECORD_WALLET_HISTORY,
        target_metrics=(METRIC_WIN_RATE,),
        fields=fields,
        provenance=tuple(provenance),
        quality_notes=tuple(sorted(notes)),
    )


def _normalize_event_forensic_json(artifact_path: Path) -> ArtifactNormalization:
    payload = _read_json_object(artifact_path)
    rows = payload.get("display_trades")
    fallback_rows = payload.get("suspicious_trades")
    fallback_used = False
    if isinstance(rows, list) and rows:
        rows = rows
    elif isinstance(fallback_rows, list) and fallback_rows:
        rows = fallback_rows
        fallback_used = True
    else:
        rows = []
    records: list[NormalizedInputRecord] = []
    notes: set[str] = set()
    skipped = _count_skipped_unsafe(payload)

    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        fields: dict[str, object] = {}
        provenance: list[FieldProvenance] = []
        record_notes: set[str] = {"cash_amount_from_position_size_derivable_not_shares"}
        row_prefix = "suspicious_trades" if fallback_used else "display_trades"
        if fallback_used:
            record_notes.add("event_forensic_suspicious_trades_fallback_price_required")
        _map_available(fields, provenance, "wallet", row, "wallet", f"{row_prefix}[{index}].wallet")
        _map_available(fields, provenance, "condition_id", row, "conditionId", f"{row_prefix}[{index}].conditionId")
        _map_available(fields, provenance, "outcome", row, "side", f"{row_prefix}[{index}].side")
        _map_available(fields, provenance, "side", row, "orderSide", f"{row_prefix}[{index}].orderSide")
        _map_available(fields, provenance, "price", row, "price", f"{row_prefix}[{index}].price")
        _map_derivable(
            fields,
            provenance,
            "cash_amount",
            row,
            "positionSize",
            f"{row_prefix}[{index}].positionSize",
            "cash exposure derived from Event Forensic display position size; not a share-size field",
        )
        _map_optional_available(fields, provenance, "timestamp", row, "timestamp", f"{row_prefix}[{index}].timestamp")
        if any(not _has_value(fields.get(key)) for key in ("side", "price", "cash_amount")):
            record_notes.add("low_odds_required_field_missing_not_normalized")
            continue
        records.append(
            NormalizedInputRecord(
                record_id=f"event_forensic_event_analysis_json:display_trade:{index}:low_odds",
                record_type=RECORD_TRADE_EXPOSURE,
                target_metrics=(METRIC_LOW_ODDS,),
                fields=fields,
                provenance=tuple(provenance),
                quality_notes=tuple(sorted(record_notes)),
            )
        )
        notes.update(record_notes)

    if skipped:
        notes.add("unsafe_production_or_hindsight_fields_skipped")
    if fallback_used:
        notes.add("event_forensic_suspicious_trades_fallback_used")
    available = {METRIC_LOW_ODDS: "safe Event Forensic low-odds exposure records normalized"} if records else {}
    unknown = {METRIC_LOW_ODDS: "no safe Event Forensic exposure rows normalized"} if not records else {}
    return ArtifactNormalization(
        family="event_forensic_event_analysis_json",
        artifact_path=str(artifact_path),
        normalized_records=tuple(records),
        metric_readiness=_readiness(
            available=available,
            not_computed={
                METRIC_ENTRY_EDGE: "outcome/winner fields are unsafe and reference price is unavailable",
                METRIC_NET_PNL: "token/current-price/share semantics are incomplete in Event Forensic display rows",
                METRIC_WIN_RATE: "win count would require ambiguous inference from wallet win rate",
                METRIC_MICROSTRUCTURE: "no local orderbook snapshot is present",
            },
            unknown=unknown,
        ),
        quality_notes=tuple(sorted(notes)),
        skipped_unsafe_field_count=skipped,
    )


def _normalize_reconstruction_report_dir(artifact_path: Path) -> ArtifactNormalization:
    normalized_path = artifact_path / "normalized_trades.csv"
    raw_current_path = artifact_path / "raw_positions_current.json"
    rows = _read_csv_rows(normalized_path) if normalized_path.exists() else []
    current_payload = _read_json_object(raw_current_path) if raw_current_path.exists() else {}
    wallet = _extract_reconstruction_wallet(current_payload)
    current_prices, current_price_records = _extract_reconstruction_current_prices(
        current_payload=current_payload,
        wallet=wallet,
        artifact_path=artifact_path,
    )
    records: list[NormalizedInputRecord] = []
    notes: set[str] = set()
    skipped = _count_skipped_unsafe(rows) + _count_skipped_unsafe(current_payload)

    for index, row in enumerate(rows):
        record = _reconstruction_ledger_record(index=index, row=row, wallet=wallet, artifact_path=artifact_path)
        if record is not None:
            records.append(record)
            notes.update(record.quality_notes)
    records.extend(current_price_records)
    for record in current_price_records:
        notes.update(record.quality_notes)

    if not rows:
        notes.add("normalized_trades_missing_or_empty")
    if not current_prices:
        notes.add("current_prices_missing_not_computed")
    return ArtifactNormalization(
        family="reconstruction_report_dir",
        artifact_path=str(artifact_path),
        normalized_records=tuple(records),
        current_prices=current_prices,
        metric_readiness=_readiness(
            available={METRIC_NET_PNL: "ledger trade records and current prices normalized from reconstruction artifacts"}
            if rows and current_prices
            else {},
            not_computed={
                METRIC_LOW_ODDS: "not in Phase 9D reconstruction scope; reconstruction family is used for ledger/PnL input",
                METRIC_ENTRY_EDGE: "reference price is unavailable",
                METRIC_WIN_RATE: "winning trade count is unavailable",
                METRIC_MICROSTRUCTURE: "no local orderbook snapshot is present",
            },
            unknown={
                METRIC_NET_PNL: "missing normalized trades or current prices"
            }
            if not (rows and current_prices)
            else {},
        ),
        quality_notes=tuple(sorted(notes)),
        skipped_unsafe_field_count=skipped,
    )


def _reconstruction_ledger_record(
    *,
    index: int,
    row: Mapping[str, object],
    wallet: object,
    artifact_path: Path,
) -> NormalizedInputRecord | None:
    fields: dict[str, object] = {}
    provenance: list[FieldProvenance] = []
    notes: set[str] = set()

    if _has_value(wallet):
        fields["wallet"] = wallet
        provenance.append(
            FieldProvenance(
                "wallet",
                "raw_positions_current.json:base_params.user",
                CLASS_DERIVABLE,
                "wallet derived from raw positions request parameters",
            )
        )
        notes.add("wallet_from_raw_positions_base_params_derivable")
    else:
        notes.add("wallet_missing_unknown")

    _map_available(
        fields,
        provenance,
        "condition_id",
        row,
        "conditionId",
        f"normalized_trades.csv[{index}].conditionId",
    )
    _map_available(fields, provenance, "token_id", row, "asset", f"normalized_trades.csv[{index}].asset")
    _map_available(fields, provenance, "outcome", row, "outcome", f"normalized_trades.csv[{index}].outcome")
    _map_available(fields, provenance, "side", row, "side", f"normalized_trades.csv[{index}].side")
    _map_available(fields, provenance, "price", row, "price", f"normalized_trades.csv[{index}].price")
    _map_available(fields, provenance, "size", row, "shares", f"normalized_trades.csv[{index}].shares")
    _map_optional_available(fields, provenance, "timestamp", row, "timestamp_utc", f"normalized_trades.csv[{index}].timestamp_utc")

    if _has_value(row.get("api_usdc_size")):
        _map_available(
            fields,
            provenance,
            "usdcSize",
            row,
            "api_usdc_size",
            f"normalized_trades.csv[{index}].api_usdc_size",
        )
    elif _has_value(row.get("recomputed_size_x_price")):
        _map_derivable(
            fields,
            provenance,
            "cash_amount",
            row,
            "recomputed_size_x_price",
            f"normalized_trades.csv[{index}].recomputed_size_x_price",
            "cash amount recomputed from size and price because API usdcSize is missing",
        )
        notes.add("cash_amount_from_size_price_derivable")
    else:
        notes.add("cash_amount_missing_unknown")

    required = ("wallet", "condition_id", "token_id", "outcome", "side", "price", "size")
    if any(not _has_value(fields.get(key)) for key in required):
        return None
    if not _has_value(fields.get("usdcSize")) and not _has_value(fields.get("cash_amount")):
        return None

    return NormalizedInputRecord(
        record_id=f"reconstruction_report_dir:{artifact_path.name}:trade:{index}:ledger",
        record_type=RECORD_LEDGER_TRADE,
        target_metrics=(METRIC_NET_PNL,),
        fields=fields,
        provenance=tuple(provenance),
        quality_notes=tuple(sorted(notes)),
    )


def _extract_reconstruction_current_prices(
    *,
    current_payload: Mapping[str, object],
    wallet: object,
    artifact_path: Path,
) -> tuple[dict[str, object], tuple[NormalizedInputRecord, ...]]:
    rows = current_payload.get("rows")
    rows = rows if isinstance(rows, list) else []
    current_prices: dict[str, object] = {}
    records: list[NormalizedInputRecord] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        condition_id = row.get("conditionId")
        token_id = row.get("asset")
        outcome = row.get("outcome")
        price = row.get("curPrice")
        if any(not _has_value(item) for item in (wallet, condition_id, token_id, outcome, price)):
            continue
        key = "|".join(str(item) for item in (wallet, condition_id, token_id, outcome))
        current_prices[key] = price
        records.append(
            NormalizedInputRecord(
                record_id=f"reconstruction_report_dir:{artifact_path.name}:current_price:{index}",
                record_type=RECORD_CURRENT_PRICE,
                target_metrics=(METRIC_NET_PNL,),
                fields={
                    "wallet": wallet,
                    "condition_id": condition_id,
                    "token_id": token_id,
                    "outcome": outcome,
                    "current_price": price,
                    "currentPriceKey": key,
                },
                provenance=(
                    FieldProvenance(
                        "wallet",
                        "raw_positions_current.json:base_params.user",
                        CLASS_DERIVABLE,
                        "wallet derived from raw positions request parameters",
                    ),
                    FieldProvenance(
                        "current_price",
                        f"raw_positions_current.json:rows[{index}].curPrice",
                        CLASS_AVAILABLE,
                        "current price from raw current-position row",
                    ),
                ),
                quality_notes=("wallet_from_raw_positions_base_params_derivable",),
            )
        )
    return current_prices, tuple(records)


def _extract_reconstruction_wallet(payload: Mapping[str, object]) -> object:
    base_params = payload.get("base_params")
    if isinstance(base_params, Mapping):
        return base_params.get("user")
    return None


def _readiness(
    *,
    available: Mapping[str, str] | None = None,
    not_computed: Mapping[str, str] | None = None,
    unknown: Mapping[str, str] | None = None,
) -> tuple[MetricReadiness, ...]:
    available = available or {}
    not_computed = not_computed or {}
    unknown = unknown or {}
    rows: list[MetricReadiness] = []
    for metric in METRIC_ORDER:
        if metric in available:
            rows.append(MetricReadiness(metric, STATUS_AVAILABLE, available[metric]))
        elif metric in unknown:
            rows.append(MetricReadiness(metric, STATUS_UNKNOWN, unknown[metric]))
        else:
            rows.append(
                MetricReadiness(
                    metric,
                    STATUS_NOT_COMPUTED,
                    not_computed.get(metric, "not supported by this Phase 9D artifact normalizer"),
                )
            )
    return tuple(rows)


def _replace_readiness(
    readiness: tuple[MetricReadiness, ...],
    replacement: MetricReadiness,
) -> tuple[MetricReadiness, ...]:
    return tuple(replacement if item.metric == replacement.metric else item for item in readiness)


def _map_available(
    fields: dict[str, object],
    provenance: list[FieldProvenance],
    target: str,
    source: Mapping[str, object],
    source_key: str,
    source_field: str,
) -> None:
    if not _has_value(source.get(source_key)):
        return
    fields[target] = source[source_key]
    provenance.append(FieldProvenance(target, source_field, CLASS_AVAILABLE, "direct available field"))


def _map_optional_available(
    fields: dict[str, object],
    provenance: list[FieldProvenance],
    target: str,
    source: Mapping[str, object],
    source_key: str,
    source_field: str,
) -> None:
    if _has_value(source.get(source_key)):
        _map_available(fields, provenance, target, source, source_key, source_field)


def _map_derivable(
    fields: dict[str, object],
    provenance: list[FieldProvenance],
    target: str,
    source: Mapping[str, object],
    source_key: str,
    source_field: str,
    note: str,
) -> None:
    if not _has_value(source.get(source_key)):
        return
    fields[target] = source[source_key]
    provenance.append(FieldProvenance(target, source_field, CLASS_DERIVABLE, note))


def _count_skipped_unsafe(payload: object) -> int:
    if isinstance(payload, Mapping):
        count = 0
        for key, value in payload.items():
            count += 1 if str(key) in SAFE_SKIP_KEYS else 0
            count += _count_skipped_unsafe(value)
        return count
    if isinstance(payload, list):
        return sum(_count_skipped_unsafe(item) for item in payload)
    return 0


def _assert_no_forbidden_output_keys(payload: object) -> None:
    found = _find_forbidden_output_keys(payload)
    if found:
        raise ValueError(f"Normalizer output contains forbidden production fields: {', '.join(sorted(found))}")


def _find_forbidden_output_keys(payload: object) -> set[str]:
    found: set[str] = set()
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if str(key) in FORBIDDEN_OUTPUT_KEYS:
                found.add(str(key))
            found.update(_find_forbidden_output_keys(value))
    elif isinstance(payload, list):
        for item in payload:
            found.update(_find_forbidden_output_keys(item))
    return found


def _read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _read_csv_rows(path: Path) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _has_value(value: object) -> bool:
    return value not in (None, "")


def _parse_artifact_arg(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Artifact must use FAMILY=PATH format")
    family, path = value.split("=", 1)
    family = family.strip()
    if family not in SUPPORTED_FAMILIES:
        raise argparse.ArgumentTypeError(f"Unsupported Phase 9D family: {family}")
    return family, path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize local artifacts into sidecar shadow input records.")
    parser.add_argument(
        "--artifact",
        action="append",
        type=_parse_artifact_arg,
        default=[],
        metavar="FAMILY=PATH",
        help="Artifact family/path pair. Repeat for multiple artifacts.",
    )
    parser.add_argument("--list-families", action="store_true", help="Print supported Phase 9D families.")
    parser.add_argument("--output-json", help="Optional explicit JSON output path.")
    parser.add_argument("--output-md", help="Optional explicit Markdown output path.")
    parser.add_argument("--output-dir", help="Optional output directory for timestamped JSON and Markdown files.")
    args = parser.parse_args(argv)

    if args.list_families:
        print("\n".join(supported_families()))
        return 0
    if not args.artifact:
        parser.error("At least one --artifact FAMILY=PATH is required unless --list-families is used.")

    report = normalize_artifacts(args.artifact)
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(markdown_report(report), encoding="utf-8")
    if args.output_dir:
        write_normalization_outputs(report, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
