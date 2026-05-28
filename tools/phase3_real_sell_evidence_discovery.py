#!/usr/bin/env python3
"""Discover real/local SELL evidence for Phase 3 capital-at-risk.

This sidecar scans local artifacts and fixtures only. It classifies SELL rows
by provenance and whether max-loss can be computed from direct side/outcome,
price, and size fields. It does not fetch data or import production
scanner/archive/Event Forensic runtime modules.
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
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.side_outcome import UNKNOWN, normalize_side_outcome  # noqa: E402
from tools.phase3_capital_source_inventory import (  # noqa: E402
    QUALITY_SAFE_SELL_MAX_LOSS,
    QUALITY_UNSAFE_OLD_NOTIONAL_ONLY,
    classify_source_row,
    discover_inventory_records,
)


REPORT_TYPE = "phase3_real_sell_evidence_discovery"
SCHEMA_VERSION = "phase3_real_sell_evidence_discovery_v1"
DEFAULT_OUTPUT = Path("validation_outputs/phase3_real_sell_evidence_discovery_20260525.json")
CENT = Decimal("0.01")

PROVENANCE_REAL_RECONSTRUCTION = "real_local_reconstruction"
PROVENANCE_REAL_PROFILE = "real_local_profile"
PROVENANCE_GENERATED_AUDIT = "generated_audit"
PROVENANCE_EXISTING_FIXTURE = "existing_fixture"
PROVENANCE_SYNTHETIC_FIXTURE = "synthetic_fixture"
PROVENANCE_OLD_DISPLAY_ONLY = "old_saved_report_display_only"


def discover_sell_evidence_records(
    root: str | Path = ".",
    *,
    max_files: int | None = 250,
    max_rows_per_file: int | None = 200,
) -> list[dict[str, object]]:
    base = Path(root)
    records: list[dict[str, object]] = []

    for record in discover_inventory_records(base, max_files=max_files, max_rows_per_file=max_rows_per_file):
        records.append(dict(record))

    for csv_path in _normalized_trade_paths(base):
        provenance = classify_artifact_provenance(csv_path)
        for index, row in enumerate(_read_csv_rows(csv_path)):
            record = dict(row)
            record.setdefault("rowIndex", index)
            record["artifactPath"] = str(csv_path)
            record["artifactFamily"] = "normalized_trades_csv"
            record["artifactEvidenceType"] = provenance
            record["source_type"] = "normalized_trade"
            records.append(record)

    return records


def build_real_sell_evidence_discovery(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    evaluated = [evaluate_sell_evidence_row(record) for record in records]
    sell_rows = [row for row in evaluated if row["rawOrderSide"] == "SELL"]
    provenance_counts = Counter(row["sourceProvenance"] for row in sell_rows)
    quality_counts = Counter(row["sourceQuality"] for row in sell_rows)
    recommendation_counts = Counter(row["recommendation"] for row in sell_rows)
    safe_real = [
        row
        for row in sell_rows
        if row["safeForSellMaxLoss"]
        and row["sourceProvenance"] in {PROVENANCE_REAL_RECONSTRUCTION, PROVENANCE_REAL_PROFILE}
    ]
    sensitive = [row for row in sell_rows if row["sensitiveOverlap"]]
    summary = {
        "recordsEvaluated": len(evaluated),
        "sellRows": len(sell_rows),
        "realSellRows": sum(1 for row in sell_rows if str(row["sourceProvenance"]).startswith("real_local_")),
        "safeSellMaxLossRows": sum(1 for row in sell_rows if row["safeForSellMaxLoss"]),
        "safeRealSellMaxLossRows": len(safe_real),
        "safeProfileSellRows": sum(1 for row in safe_real if row["sourceProvenance"] == PROVENANCE_REAL_PROFILE),
        "safeReconstructionSellRows": sum(1 for row in safe_real if row["sourceProvenance"] == PROVENANCE_REAL_RECONSTRUCTION),
        "sensitiveOverlapRows": len(sensitive),
        "sensitiveSafeSellRows": sum(1 for row in sensitive if row["safeForSellMaxLoss"]),
        "oldDisplayOnlySellRows": provenance_counts[PROVENANCE_OLD_DISPLAY_ONLY],
        "syntheticSellRows": provenance_counts[PROVENANCE_SYNTHETIC_FIXTURE],
        "fixtureSellRows": provenance_counts[PROVENANCE_EXISTING_FIXTURE],
        "generatedAuditSellRows": provenance_counts[PROVENANCE_GENERATED_AUDIT],
        "sourceProvenanceCounts": dict(sorted(provenance_counts.items())),
        "sourceQualityCounts": dict(sorted(quality_counts.items())),
        "recommendationCounts": dict(sorted(recommendation_counts.items())),
    }
    review_candidates = _review_candidates(sell_rows)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeImplementationAllowed": False,
        "summary": summary,
        "sampleRows": sell_rows[:300],
        "sampleRowsOmitted": max(len(sell_rows) - 300, 0),
        "reviewCandidates": review_candidates,
        "reviewCandidatesOmitted": max(len(sensitive) - len(review_candidates), 0),
    }


def evaluate_sell_evidence_row(record: Mapping[str, object]) -> dict[str, object]:
    classified = classify_source_row(record)
    side = classified["rawOrderSide"]
    outcome = classified["rawTokenOutcome"]
    price = _price_decimal_or_none(classified.get("rawTokenPrice"))
    size = _plain_decimal_or_none(classified.get("size"))
    normalized = normalize_side_outcome(side, outcome, price)
    raw_notional = _quantize(size * price) if size is not None and price is not None else None
    observed_cash = _observed_cash(record)
    max_loss = _quantize(size * (Decimal("1") - price)) if side == "SELL" and size is not None and price is not None else None
    provenance = _record_provenance(record, classified)
    source_quality = str(classified["sourceQuality"])
    safe_for_sell = side == "SELL" and source_quality == QUALITY_SAFE_SELL_MAX_LOSS
    recommendation = _recommendation(source_quality, safe_for_sell)
    sensitive = _sensitive_context(record)
    return {
        "rowId": classified.get("rowId", ""),
        "sourceProvenance": provenance,
        "sourceType": classified.get("sourceType", "unknown"),
        "artifactFamily": classified.get("artifactFamily", "unknown"),
        "artifactPath": classified.get("artifactPath", ""),
        "wallet": _first_text(record, ("wallet", "proxyWallet", "proxy_wallet", "user")),
        "market": _first_text(record, ("market", "marketSlug", "market_slug", "marketQuestion", "conditionId", "condition_id")),
        "event": _first_text(record, ("event", "eventSlug", "event_slug", "eventTitle")),
        "rawOrderSide": side,
        "rawTokenOutcome": outcome,
        "rawTokenPrice": _decimal_text(price),
        "size": _decimal_text(size),
        "usdcSize": _decimal_text(_plain_decimal_or_none(_first_present(record, ("usdcSize", "usdc_size", "api_usdc_size")))),
        "economicSide": normalized.economic_side,
        "economicSideProbability": _decimal_text(normalized.economic_side_probability),
        "currentRawNotional": _decimal_text(raw_notional),
        "hypotheticalSellMaxLoss": _decimal_text(max_loss),
        "observedCash": _decimal_text(observed_cash),
        "safeForSellMaxLoss": safe_for_sell,
        "sourceQuality": source_quality,
        "sensitiveOverlap": sensitive,
        "recommendation": recommendation,
        "qualityNotes": sorted(set(classified.get("qualityNotes", []))),
    }


def classify_artifact_provenance(path: str | Path) -> str:
    text = str(path)
    parts = Path(path).parts
    if "tests" in parts and "fixtures" in parts:
        if "synthetic" in text or "known_case" in text:
            return PROVENANCE_SYNTHETIC_FIXTURE
        return PROVENANCE_EXISTING_FIXTURE
    if text.startswith("validation_outputs/") or text.startswith("side_outcome_audits/"):
        return PROVENANCE_GENERATED_AUDIT
    name = Path(path).name
    parent = Path(path).parent.name
    if parent.startswith("polymarket_profile_"):
        return PROVENANCE_REAL_PROFILE
    if parent.startswith("polymarket_wallet_") or "reconstruction" in parent:
        return PROVENANCE_REAL_RECONSTRUCTION
    if name in {"normalized_trades.csv", "raw_activity.json"} and not text.startswith("tests/"):
        return PROVENANCE_REAL_RECONSTRUCTION
    return PROVENANCE_OLD_DISPLAY_ONLY


def write_discovery_output(report: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _normalized_trade_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.glob("**/normalized_trades.csv"):
        if ".git" in path.parts:
            continue
        paths.append(path)
    return sorted(set(paths))


def _read_csv_rows(path: Path) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _review_candidates(rows: Sequence[Mapping[str, object]], *, limit: int = 12) -> list[Mapping[str, object]]:
    sensitive = [row for row in rows if row.get("sensitiveOverlap")]
    safe = [row for row in sensitive if row.get("safeForSellMaxLoss")]
    unsafe = [row for row in sensitive if not row.get("safeForSellMaxLoss")]
    selected = safe[: limit // 2] + unsafe[: limit - len(safe[: limit // 2])]
    return list(selected[:limit])


def _recommendation(source_quality: str, safe_for_sell: bool) -> str:
    if source_quality == QUALITY_UNSAFE_OLD_NOTIONAL_ONLY:
        return "unsafe_old_notional"
    if safe_for_sell:
        return "safe_sidecar_only"
    return "needs_source_fields"


def _sensitive_context(record: Mapping[str, object]) -> bool:
    sensitive_keys = (
        "existingModelClass",
        "risk_level",
        "riskLevel",
        "strongRisk",
        "Strong Risk",
        "hardEvidenceReview",
        "her",
        "fundingEvidenceGrade",
        "funding_support",
        "sensitivePhase2Context",
    )
    for key in sensitive_keys:
        value = record.get(key)
        text = str(value).strip().lower() if value not in (None, "") else ""
        if text and text not in {"false", "0", "none", "unknown", "no"}:
            return True
    return False


def _observed_cash(record: Mapping[str, object]) -> Decimal | None:
    return _plain_decimal_or_none(_first_present(record, ("usdcSize", "usdc_size", "api_usdc_size", "cash_amount", "api_cash_amount")))


def _first_text(record: Mapping[str, object], keys: Iterable[str]) -> str:
    value = _first_present(record, keys)
    return str(value).strip() if value not in (None, "") else ""


def _first_present(record: Mapping[str, object], keys: Iterable[str]) -> object:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _plain_decimal_or_none(value: object) -> Decimal | None:
    if value in (None, "", UNKNOWN):
        return None
    try:
        text = str(value).replace(",", "").strip()
        decimal = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite():
        return None
    return decimal


def _price_decimal_or_none(value: object) -> Decimal | None:
    if value in (None, "", UNKNOWN):
        return None
    try:
        text = str(value).replace("%", "").replace(",", "").strip()
        decimal = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite():
        return None
    if decimal > Decimal("1") and decimal <= Decimal("100"):
        decimal = decimal / Decimal("100")
    return decimal


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def _decimal_text(value: Decimal | None) -> str:
    return str(value) if value is not None else UNKNOWN


def _record_provenance(record: Mapping[str, object], classified: Mapping[str, object]) -> str:
    artifact_path = str(classified.get("artifactPath") or record.get("artifactPath") or "")
    evidence_type = str(record.get("artifactEvidenceType") or classified.get("artifactEvidenceType") or "")
    source_quality = str(classified.get("sourceQuality") or "")
    source_type = str(classified.get("sourceType") or "")
    if evidence_type == "synthetic_fixture":
        return PROVENANCE_SYNTHETIC_FIXTURE
    if evidence_type in {"existing_test_fixture", "real_local_artifact"}:
        return PROVENANCE_EXISTING_FIXTURE
    if evidence_type == "generated_audit_evidence" or artifact_path.startswith("validation_outputs/"):
        return PROVENANCE_GENERATED_AUDIT
    if source_quality == "safe_for_display_only" or source_type in {"scanner_report_json", "archive_report_json", "event_forensic_json"}:
        return PROVENANCE_OLD_DISPLAY_ONLY
    if artifact_path:
        return classify_artifact_provenance(artifact_path)
    return PROVENANCE_OLD_DISPLAY_ONLY


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-files", type=int, default=250)
    parser.add_argument("--max-rows-per-file", type=int, default=200)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    records = discover_sell_evidence_records(
        args.root,
        max_files=args.max_files,
        max_rows_per_file=args.max_rows_per_file,
    )
    report = build_real_sell_evidence_discovery(records)
    output = write_discovery_output(report, args.output_json)
    if not args.quiet:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
