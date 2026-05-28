#!/usr/bin/env python3
"""Sidecar-only capital-at-risk audit for Side/Outcome Phase 3.

The audit compares current raw-token notional capital-at-risk with a
hypothetical economic exposure formula. It is intentionally read-only and does
not import scanner/archive/Event Forensic runtime modules.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.side_outcome import UNKNOWN, normalize_side_outcome
from tools.side_outcome_archive_evidence_audit import (
    discover_archive_artifacts,
    load_archive_records,
    select_artifacts_for_scan,
)
from tools.side_outcome_phase2_impact_audit import (
    discover_artifact_paths,
    load_records_from_paths,
)


REPORT_TYPE = "side_outcome_phase3_capital_at_risk_audit"
SCHEMA_VERSION = "side_outcome_phase3_capital_at_risk_v1"
PHASE3_FIXTURE_DIR = Path("tests/fixtures/side_outcome_phase3_capital_at_risk")
DEFAULT_JSON_OUTPUT = Path("side_outcome_audits/side_outcome_phase3_capital_at_risk_audit_20260522.json")
DEFAULT_MARKDOWN_OUTPUT = Path("docs/inspoly_side_outcome_phase3_capital_at_risk_impact_audit_20260522.md")
CENT = Decimal("0.01")


def evaluate_capital_row(record: Mapping[str, object]) -> dict[str, object]:
    """Evaluate one artifact row without changing production interpretation."""

    row_id = str(_first_nonblank(record.get("id"), record.get("trade_id"), record.get("transactionHash"), record.get("rowIndex"), ""))
    artifact_family = str(record.get("artifactFamily") or "unknown")
    artifact_type = str(record.get("artifactEvidenceType") or "real_local")
    order_side = _order_side(record)
    token_outcome = _token_outcome(record)
    price_input = _first_nonblank(
        record.get("raw_token_price"),
        record.get("rawTokenPrice"),
        record.get("price"),
        record.get("entry_probability_pct"),
        record.get("price_implied_probability"),
    )
    normalized = normalize_side_outcome(order_side, token_outcome, price_input)
    price = normalized.raw_token_price
    size, size_source, size_notes = _size_from_record(record, price)
    raw_size_price = _mul(size, price)
    current_notional, current_notional_source = _current_notional(record, raw_size_price)
    explicit_cash, explicit_cash_source = _explicit_cash(record)
    observed_cash = explicit_cash if explicit_cash is not None else raw_size_price
    observed_cash_source = explicit_cash_source if explicit_cash is not None else ("size_price" if raw_size_price is not None else "unknown")
    opening = _opening_exposure(record)
    current_capital, current_capital_source = _current_capital(record, opening, raw_size_price, current_notional)
    hypothetical, hypothetical_source = _hypothetical_economic_capital(
        normalized.raw_order_side,
        opening,
        size,
        price,
        explicit_cash,
        raw_size_price,
    )
    delta = None
    if current_capital is not None and hypothetical is not None:
        delta = hypothetical - current_capital
    notes = _quality_notes(
        record=record,
        normalized=normalized,
        opening=opening,
        size=size,
        size_source=size_source,
        raw_size_price=raw_size_price,
        current_notional=current_notional,
        explicit_cash=explicit_cash,
        observed_cash=observed_cash,
        hypothetical=hypothetical,
        delta=delta,
    )
    bucket = f"{normalized.raw_order_side}_{normalized.raw_token_outcome}"
    sensitive = _sensitive_context(record)
    return {
        "rowId": row_id,
        "artifactFamily": artifact_family,
        "artifactEvidenceType": artifact_type,
        "artifactPath": str(record.get("artifactPath") or ""),
        "uniqueTradeKey": _unique_trade_key(record, normalized, row_id),
        "wallet": str(record.get("wallet") or ""),
        "conditionId": str(_first_nonblank(record.get("conditionId"), record.get("condition_id"), "")),
        "buySellOutcomeBucket": bucket,
        "rawOrderSide": normalized.raw_order_side,
        "rawTokenOutcome": normalized.raw_token_outcome,
        "rawTokenPrice": _decimal_text(price),
        "economicSide": normalized.economic_side,
        "economicSideProbability": _decimal_text(normalized.economic_side_probability),
        "modelEconomicDirection": normalized.economic_direction_normalized,
        "openingExposure": opening,
        "size": _decimal_text(size),
        "sizeSource": size_source,
        "rawSizePriceNotional": _decimal_text(raw_size_price),
        "currentReportedNotional": _decimal_text(current_notional),
        "currentReportedNotionalSource": current_notional_source,
        "observedCashAmount": _decimal_text(observed_cash),
        "observedCashSource": observed_cash_source,
        "currentReportedCapitalAtRisk": _decimal_text(current_capital),
        "currentReportedCapitalSource": current_capital_source,
        "hypotheticalEconomicCapitalAtRisk": _decimal_text(hypothetical),
        "hypotheticalCapitalSource": hypothetical_source,
        "capitalDelta": _decimal_text(delta),
        "capitalDeltaAbs": _decimal_text(abs(delta) if delta is not None else None),
        "capitalDeltaDirection": _delta_direction(delta),
        "dataQualityStatus": _data_quality_status(notes, hypothetical),
        "qualityNotes": notes + size_notes,
        "sensitivePhase2Context": sensitive,
        "phase3RuntimeImplementationAllowed": False,
        "phase4ClusterNormalizationApplied": False,
    }


def build_phase3_capital_at_risk_audit(
    records: Sequence[Mapping[str, object]],
    *,
    artifacts: Sequence[Mapping[str, object]] | None = None,
    skipped_artifacts: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    evaluated = [evaluate_capital_row(record) for record in records]
    summary = _summary(evaluated, records, artifacts or [], skipped_artifacts or [])
    gate_decision = _gate_decision(summary)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "implementationAllowed": False,
        "phase3RuntimeImplementationAllowed": False,
        "phase4ClusterNormalizationApplied": False,
        "gateDecision": gate_decision,
        "summary": summary,
        "formulaContract": {
            "currentProductionOpeningCapitalAtRisk": "opening exposure currently uses raw token notional, normally size * price",
            "buyEconomicCapitalAtRisk": "BUY max loss is cash paid; prefer explicit usdcSize as observed cash when present, otherwise size * price",
            "sellEconomicCapitalAtRisk": "Opening SELL max loss is complement exposure, size * (1 - price), while raw fill cash remains size * price or explicit usdcSize",
            "missingFields": "missing or malformed side/outcome/price/size remains unknown, not zero",
        },
        "affectedExamples": _examples(evaluated, require_delta=True),
        "unsafeExamples": _examples(evaluated, require_notes=True),
        "explicitBlocks": [
            "runtime capital-at-risk behavior changes",
            "_score_trade() or _event_forensic_score() Phase 3 edits",
            "scoring weights or thresholds",
            "Strong Risk/HER/funding eligibility/candidate admission changes",
            "Phase 4 cluster direction normalization",
            "storage schema, UI sorting/filter, live/RPC/network behavior",
            "saved report or artifact mutation",
        ],
        "implementationGuardrailsIfLaterApproved": [
            "Introduce a central capital-at-risk selector rather than duplicating SELL complement math across runtime paths.",
            "Keep raw fill notional and observed cash fields separate from economic max-loss fields.",
            "Treat lossy old reports as unknown unless side/outcome/price/size can be safely reconstructed.",
            "Run scanner/archive/Event Forensic before/after audits and preserve Phase 2 model probability semantics.",
            "Keep Phase 4 same-side cluster normalization out of Phase 3.",
        ],
    }


def discover_phase3_records(
    root: str | Path = ".",
    *,
    max_files: int | None = 250,
    max_rows_per_file: int | None = 200,
    max_bytes: int | None = 5_000_000,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    base = Path(root)
    records: list[dict[str, object]] = []
    artifacts: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []

    generic_paths = discover_artifact_paths(base)
    if max_files is not None:
        generic_paths = generic_paths[: max(max_files // 2, 1)]
    generic_records = load_records_from_paths(generic_paths, max_rows_per_file=max_rows_per_file)
    for family, path in generic_paths:
        artifacts.append(_artifact_ref(base, path, family=family, evidence_type="real_local"))
    for row in generic_records:
        row.setdefault("artifactEvidenceType", "real_local")
        records.append(row)

    archive_artifacts = discover_archive_artifacts(base)
    selected_archive = select_artifacts_for_scan(archive_artifacts, max_files=max_files)
    archive_records, archive_skipped = load_archive_records(
        selected_archive,
        max_files=None,
        max_rows_per_file=max_rows_per_file,
        max_bytes=max_bytes,
    )
    artifacts.extend(dict(item) for item in selected_archive)
    skipped.extend(dict(item) for item in archive_skipped)
    records.extend(archive_records)

    fixture_artifacts = _phase3_fixture_artifacts(base)
    fixture_records, fixture_skipped = _load_phase3_fixture_records(fixture_artifacts, max_rows_per_file=max_rows_per_file)
    artifacts.extend(fixture_artifacts)
    skipped.extend(fixture_skipped)
    records.extend(fixture_records)
    return records, artifacts, skipped


def write_outputs(report: Mapping[str, object], *, markdown_path: str | Path, json_path: str | Path) -> dict[str, str]:
    md = Path(markdown_path)
    js = Path(json_path)
    md.parent.mkdir(parents=True, exist_ok=True)
    js.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(capital_audit_markdown(report), encoding="utf-8")
    js.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"markdownPath": str(md), "jsonPath": str(js)}


def capital_audit_markdown(report: Mapping[str, object]) -> str:
    summary = _mapping(report.get("summary"))
    affected = _mapping(summary.get("affectedCounts"))
    unsafe = _mapping(summary.get("unsafeOrMissingFieldCounts"))
    family_counts = _mapping(summary.get("artifactFamilyCounts"))
    evidence_counts = _mapping(summary.get("evidenceTypeCounts"))
    source_counts = _mapping(summary.get("sourceFieldCounts"))
    lines = [
        "# InsPoly Side/Outcome Phase 3 Capital-at-Risk Impact Audit",
        "",
        "- Date: 2026-05-22",
        "- Scope: sidecar-only RFC evidence and impact audit",
        "- Runtime implementation allowed: `false`",
        f"- Gate decision: `{report.get('gateDecision')}`",
        "",
        "## Current Behavior Inventory",
        "",
        "- `Trade.notional` is raw token notional: `price * size`.",
        "- Scanner opening capital-at-risk currently uses raw token notional for opening exposure.",
        "- Archive and Event Forensic reuse that raw capital context for candidate/report metadata.",
        "- Funding-quality helpers compare funding amounts to preserved raw `trade_notional_usdc`.",
        "- Event Forensic display `positionSize` remains raw trade notional, not economic max loss.",
        "",
        "## Proposed Economic Formula",
        "",
        "- BUY YES/NO: economic capital-at-risk is cash paid, preferring explicit `usdcSize` only as observed cash when present; otherwise `size * price`.",
        "- SELL YES/NO: economic max loss is complement exposure, `size * (1 - price)`, while raw fill cash remains separate.",
        "- Missing or malformed side/outcome/price/size remains `unknown`, not zero.",
        "",
        "## Audit Counts",
        "",
        f"- Records scanned: `{summary.get('recordsScanned', 0)}`",
        f"- Evaluable rows: `{summary.get('evaluableRows', 0)}`",
        f"- Affected rows: `{affected.get('rowsWithCapitalDelta', 0)}`",
        f"- Affected unique trade keys: `{affected.get('uniqueTradeKeysWithCapitalDelta', 0)}`",
        f"- Sensitive overlap rows: `{affected.get('sensitiveOverlapRows', 0)}`",
        "",
        "| Evidence type | Rows | Affected rows |",
        "|---|---:|---:|",
    ]
    for evidence_type, values in sorted(evidence_counts.items()):
        counts = _mapping(values)
        lines.append(f"| `{evidence_type}` | {counts.get('records', 0)} | {counts.get('affectedRows', 0)} |")
    lines.extend(["", "| Artifact family | Rows |", "|---|---:|"])
    for family, count in sorted(family_counts.items()):
        lines.append(f"| `{family}` | {count} |")
    lines.extend(["", "## Source Field Usage", "", "| Source | Rows |", "|---|---:|"])
    for source, count in sorted(source_counts.items()):
        lines.append(f"| `{source}` | {count} |")
    lines.extend(["", "## Unsafe / Missing Field Taxonomy", "", "| Note | Rows |", "|---|---:|"])
    if unsafe:
        for note, count in sorted(unsafe.items()):
            lines.append(f"| `{note}` | {count} |")
    else:
        lines.append("| `none` | 0 |")
    lines.extend(
        [
            "",
            "## Compatibility Risks",
            "",
            "- Old reports that only preserve raw notional cannot be safely reinterpreted as economic max loss.",
            "- Existing raw display fields must remain raw-token fields after any future migration.",
            "- Phase 3 would change downstream size/liquidity/funding-sensitive semantics if applied inside scoring.",
            "- Archive CSV rows without side/outcome/price/size must stay unknown and must not be rescored from notional alone.",
            "",
            "## Implementation Plan If Later Approved",
            "",
            "1. Add a central runtime capital selector with explicit source/provenance fields.",
            "2. Use BUY cash-paid semantics only where explicit fields are available or `size * price` is safe.",
            "3. Use SELL complement max-loss semantics only for opening/increasing exposure with validated size and price.",
            "4. Preserve raw fill notional, observed cash, and display fields separately.",
            "5. Re-run scanner/archive/Event Forensic before/after audits and gate-sensitive tests.",
            "6. Keep Phase 4 cluster normalization separate.",
            "",
            "## Gate Decision",
            "",
            f"Decision: `{report.get('gateDecision')}`.",
            "",
            "This audit does not authorize runtime implementation. A separate approval gate is required before changing `_score_trade()`, `_event_forensic_score()`, archive candidate metadata, funding/HER/Strong Risk semantics, or any report/UI runtime path.",
            "",
            "## Explicit Blocks",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("explicitBlocks", []))
    return "\n".join(lines).rstrip() + "\n"


def _hypothetical_economic_capital(
    order_side: str,
    opening: bool | None,
    size: Decimal | None,
    price: Decimal | None,
    explicit_cash: Decimal | None,
    raw_size_price: Decimal | None,
) -> tuple[Decimal | None, str]:
    if opening is False:
        return Decimal("0"), "non_opening_zero"
    if order_side == "BUY":
        if explicit_cash is not None:
            return explicit_cash, "explicit_usdc_size_cash_paid"
        if raw_size_price is not None:
            return raw_size_price, "size_price_cash_paid"
        return None, "unknown"
    if order_side == "SELL":
        if size is None or price is None:
            return None, "unknown"
        return _quantize(size * (Decimal("1") - price)), "size_complement_price_max_loss"
    return None, "unknown"


def _current_capital(
    record: Mapping[str, object],
    opening: bool | None,
    raw_size_price: Decimal | None,
    current_notional: Decimal | None,
) -> tuple[Decimal | None, str]:
    explicit = _decimal_or_none(_first_nonblank(record.get("capital_at_risk_usdc"), record.get("capitalAtRiskUsd")))
    if explicit is not None:
        return _quantize(explicit), "capital_at_risk_usdc"
    if opening is False:
        return Decimal("0"), "non_opening_zero"
    if raw_size_price is not None:
        return raw_size_price, "current_runtime_size_price"
    if current_notional is not None:
        return current_notional, "reported_raw_notional"
    return None, "unknown"


def _current_notional(record: Mapping[str, object], raw_size_price: Decimal | None) -> tuple[Decimal | None, str]:
    for key in ("trade_notional_usdc", "tradeNotionalUsd", "notional", "notional_usdc", "positionSize"):
        value = _decimal_or_none(record.get(key))
        if value is not None:
            return _quantize(value), key
    if raw_size_price is not None:
        return raw_size_price, "size_price"
    return None, "unknown"


def _explicit_cash(record: Mapping[str, object]) -> tuple[Decimal | None, str]:
    for key in ("usdcSize", "usdc_size", "api_usdc_size", "api_cash_amount", "cash_amount"):
        value = _decimal_or_none(record.get(key))
        if value is not None:
            return _quantize(value), key
    return None, "unknown"


def _size_from_record(record: Mapping[str, object], price: Decimal | None) -> tuple[Decimal | None, str, list[str]]:
    notes: list[str] = []
    for key in ("size", "shares", "amount"):
        value = _decimal_or_none(record.get(key))
        if value is not None:
            return value, key, notes
    notional = _decimal_or_none(_first_nonblank(record.get("trade_notional_usdc"), record.get("notional"), record.get("positionSize")))
    if notional is not None and price not in (None, Decimal("0")):
        notes.append("size_inferred_from_reported_notional_and_price")
        return _quantize(notional / price), "inferred_from_notional_price", notes
    return None, "unknown", notes


def _quality_notes(
    *,
    record: Mapping[str, object],
    normalized,
    opening: bool | None,
    size: Decimal | None,
    size_source: str,
    raw_size_price: Decimal | None,
    current_notional: Decimal | None,
    explicit_cash: Decimal | None,
    observed_cash: Decimal | None,
    hypothetical: Decimal | None,
    delta: Decimal | None,
) -> list[str]:
    notes: list[str] = []
    if normalized.normalization_status != "normalized":
        notes.append(normalized.fallback_reason or "side_outcome_unknown")
    if opening is None:
        notes.append("opening_exposure_unknown")
    if size is None:
        notes.append("missing_or_unknown_size")
    if current_notional is None:
        notes.append("current_reported_notional_missing")
    if hypothetical is None:
        notes.append("hypothetical_economic_capital_unknown")
    if _old_report_notional_only(record):
        notes.append("old_report_notional_only_not_safe_for_rescoring")
    if explicit_cash is not None and raw_size_price is not None and abs(explicit_cash - raw_size_price) > CENT:
        notes.append("source_cash_disagreement")
    if normalized.raw_order_side == "SELL" and explicit_cash is not None:
        notes.append("sell_usdc_size_recorded_as_observed_cash_not_max_loss")
    if normalized.raw_order_side == "SELL" and hypothetical is not None:
        notes.append("opening_sell_complement_exposure_requires_accounting_gate")
    if delta is not None and delta != 0:
        notes.append("capital_at_risk_would_change")
    if size_source == "inferred_from_notional_price":
        notes.append("size_inferred_not_direct")
    if observed_cash is None:
        notes.append("observed_cash_unknown")
    return _dedupe(notes)


def _summary(
    evaluated: Sequence[Mapping[str, object]],
    original_records: Sequence[Mapping[str, object]],
    artifacts: Sequence[Mapping[str, object]],
    skipped: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    family_counts = Counter(str(item.get("artifactFamily") or "unknown") for item in evaluated)
    evidence_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"records": 0, "affectedRows": 0})
    bucket_counts = Counter(str(item.get("buySellOutcomeBucket") or "unknown") for item in evaluated)
    source_counts = Counter(str(item.get("hypotheticalCapitalSource") or "unknown") for item in evaluated)
    unsafe = Counter()
    affected = Counter()
    affected_keys: set[str] = set()
    sensitive_examples = 0
    evaluable = 0
    for item in evaluated:
        evidence_type = str(item.get("artifactEvidenceType") or "unknown")
        evidence_counts[evidence_type]["records"] += 1
        if item.get("hypotheticalEconomicCapitalAtRisk") != UNKNOWN:
            evaluable += 1
        if item.get("capitalDelta") not in (UNKNOWN, "0", "0.00"):
            affected["rowsWithCapitalDelta"] += 1
            evidence_counts[evidence_type]["affectedRows"] += 1
            if item.get("uniqueTradeKey"):
                affected_keys.add(str(item.get("uniqueTradeKey")))
            if item.get("rawOrderSide") == "SELL":
                affected["sellRowsWithCapitalDelta"] += 1
            if item.get("rawOrderSide") == "BUY":
                affected["buyRowsWithCapitalDelta"] += 1
            if item.get("sensitivePhase2Context"):
                sensitive_examples += 1
        for note in item.get("qualityNotes", []):
            unsafe[str(note)] += 1
    affected["uniqueTradeKeysWithCapitalDelta"] = len(affected_keys)
    affected["sensitiveOverlapRows"] = sensitive_examples
    return {
        "recordsScanned": len(evaluated),
        "artifactsSelected": len(artifacts),
        "artifactsSkipped": len(skipped),
        "evaluableRows": evaluable,
        "artifactFamilyCounts": dict(sorted(family_counts.items())),
        "evidenceTypeCounts": {key: dict(value) for key, value in sorted(evidence_counts.items())},
        "buySellOutcomeCounts": dict(sorted(bucket_counts.items())),
        "sourceFieldCounts": dict(sorted(source_counts.items())),
        "affectedCounts": dict(sorted(affected.items())),
        "unsafeOrMissingFieldCounts": dict(sorted(unsafe.items())),
        "sampledArtifacts": [dict(item) for item in artifacts[:30]],
        "skippedArtifacts": [dict(item) for item in skipped[:30]],
    }


def _gate_decision(summary: Mapping[str, object]) -> str:
    affected = _mapping(summary.get("affectedCounts"))
    sources = _mapping(summary.get("sourceFieldCounts"))
    unsafe = _mapping(summary.get("unsafeOrMissingFieldCounts"))
    sell_affected = int(affected.get("sellRowsWithCapitalDelta") or 0)
    evaluable = int(summary.get("evaluableRows") or 0)
    if sell_affected > 0:
        return "keep_phase3_blocked"
    if evaluable < 8 or int(sources.get("size_complement_price_max_loss") or 0) < 2:
        return "needs_more_capital_fixtures"
    if unsafe:
        return "needs_more_capital_fixtures"
    return "ready_for_phase3_implementation"


def _examples(
    evaluated: Sequence[Mapping[str, object]],
    *,
    require_delta: bool = False,
    require_notes: bool = False,
    limit: int = 12,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in evaluated:
        if require_delta and item.get("capitalDelta") in (UNKNOWN, "0", "0.00"):
            continue
        if require_notes and not item.get("qualityNotes"):
            continue
        rows.append(
            {
                "artifactEvidenceType": item.get("artifactEvidenceType"),
                "artifactFamily": item.get("artifactFamily"),
                "artifactPath": item.get("artifactPath"),
                "rowId": item.get("rowId"),
                "rawOrderSide": item.get("rawOrderSide"),
                "rawTokenOutcome": item.get("rawTokenOutcome"),
                "rawTokenPrice": item.get("rawTokenPrice"),
                "size": item.get("size"),
                "currentReportedCapitalAtRisk": item.get("currentReportedCapitalAtRisk"),
                "hypotheticalEconomicCapitalAtRisk": item.get("hypotheticalEconomicCapitalAtRisk"),
                "capitalDelta": item.get("capitalDelta"),
                "qualityNotes": list(item.get("qualityNotes") or []),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _phase3_fixture_artifacts(base: Path) -> list[dict[str, object]]:
    fixture_root = base / PHASE3_FIXTURE_DIR
    refs: list[dict[str, object]] = []
    for path in sorted(fixture_root.glob("*")):
        if path.suffix.lower() not in {".json", ".csv"}:
            continue
        refs.append(_artifact_ref(base, path, family=f"phase3_synthetic_{path.suffix.lower().lstrip('.')}", evidence_type="synthetic_fixture"))
    return refs


def _load_phase3_fixture_records(
    artifacts: Sequence[Mapping[str, object]],
    *,
    max_rows_per_file: int | None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for artifact in artifacts:
        path = Path(str(artifact["path"]))
        try:
            if path.suffix.lower() == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
                items = payload.get("rows") if isinstance(payload, Mapping) else []
                for index, item in enumerate(items if isinstance(items, list) else []):
                    if max_rows_per_file is not None and index >= max_rows_per_file:
                        break
                    if not isinstance(item, Mapping):
                        continue
                    row = dict(item)
                    row.setdefault("artifactFamily", artifact.get("artifactFamily"))
                    row.setdefault("artifactEvidenceType", artifact.get("artifactEvidenceType"))
                    row["artifactPath"] = str(path)
                    row["rowIndex"] = index
                    rows.append(row)
            elif path.suffix.lower() == ".csv":
                with path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    for index, item in enumerate(reader):
                        if max_rows_per_file is not None and index >= max_rows_per_file:
                            break
                        row = dict(item)
                        row.setdefault("artifactFamily", artifact.get("artifactFamily"))
                        row.setdefault("artifactEvidenceType", artifact.get("artifactEvidenceType"))
                        row["artifactPath"] = str(path)
                        row["rowIndex"] = index
                        rows.append(row)
        except (OSError, json.JSONDecodeError) as exc:
            skipped.append({**artifact, "reason": f"load_failed:{type(exc).__name__}"})
    return rows, skipped


def _artifact_ref(base: Path, path: Path, *, family: str, evidence_type: str) -> dict[str, object]:
    try:
        rel = path.resolve().relative_to(base.resolve())
    except ValueError:
        rel = path
    return {
        "path": str(path),
        "relativePath": str(rel),
        "artifactFamily": family,
        "artifactEvidenceType": evidence_type,
    }


def _order_side(record: Mapping[str, object]) -> object:
    for key in ("raw_order_side", "rawOrderSide", "orderSide", "order_side", "type"):
        value = _first_nonblank(record.get(key))
        if str(value).strip().upper() in {"BUY", "SELL"}:
            return value
    side = _first_nonblank(record.get("side"))
    return side if str(side).strip().upper() in {"BUY", "SELL"} else UNKNOWN


def _token_outcome(record: Mapping[str, object]) -> object:
    for key in ("raw_token_outcome", "rawTokenOutcome", "tokenOutcome", "token_outcome", "outcome"):
        value = _first_nonblank(record.get(key))
        if str(value).strip().upper() in {"YES", "NO", "Y", "N"}:
            return value
    side = _first_nonblank(record.get("side"))
    return side if str(side).strip().upper() in {"YES", "NO", "Y", "N"} else UNKNOWN


def _opening_exposure(record: Mapping[str, object]) -> bool | None:
    for key in ("openingExposure", "opening_exposure", "opening_exposure_flag"):
        parsed = _bool_or_none(record.get(key))
        if parsed is not None:
            return parsed
    state = str(_first_nonblank(record.get("execution_state"), record.get("trade_state"), record.get("positionEffect"), "")).strip().lower()
    if state in {"increase", "increase_long", "increase_short", "open", "opening"}:
        return True
    if state in {"reduce", "reduce_long", "reduce_short", "close", "closing"}:
        return False
    return None


def _sensitive_context(record: Mapping[str, object]) -> bool:
    text = " ".join(str(value) for value in record.values() if value not in (None, ""))
    lowered = text.lower()
    markers = ("strong risk", "hard evidence", "her", "funding", "candidate", "suppression")
    return any(marker in lowered for marker in markers)


def _old_report_notional_only(record: Mapping[str, object]) -> bool:
    has_notional = _first_nonblank(record.get("trade_notional_usdc"), record.get("notional"), record.get("positionSize")) not in (None, "")
    has_side_outcome_size = all(
        _first_nonblank(record.get(key)) not in (None, "")
        for key in ("side", "outcome", "price", "size")
    )
    has_phase1 = any(
        _first_nonblank(record.get(key)) not in (None, "")
        for key in ("raw_token_price", "rawTokenPrice", "economic_side_probability", "economicSideProbability")
    )
    return bool(has_notional and not has_side_outcome_size and not has_phase1)


def _unique_trade_key(record: Mapping[str, object], normalized, row_id: str) -> str:
    explicit = _first_nonblank(record.get("trade_id"), record.get("id"), record.get("transactionHash"), record.get("hash"))
    if explicit not in (None, ""):
        return str(explicit)
    parts = [
        str(record.get("wallet") or ""),
        str(_first_nonblank(record.get("conditionId"), record.get("condition_id"), "")),
        normalized.raw_order_side,
        normalized.raw_token_outcome,
        _decimal_text(normalized.raw_token_price),
        row_id,
    ]
    return "|".join(parts)


def _mul(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return _quantize(left * right)


def _decimal_or_none(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1].strip()
        try:
            return Decimal(text) / Decimal("100")
        except (InvalidOperation, ValueError):
            return None
    try:
        value_decimal = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not value_decimal.is_finite():
        return None
    return value_decimal


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def _first_nonblank(*values: object) -> object:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _bool_or_none(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _decimal_text(value: Decimal | None) -> str:
    return str(value) if value is not None else UNKNOWN


def _delta_direction(delta: Decimal | None) -> str:
    if delta is None:
        return UNKNOWN
    if delta > 0:
        return "increase"
    if delta < 0:
        return "decrease"
    return "unchanged"


def _data_quality_status(notes: Sequence[str], hypothetical: Decimal | None) -> str:
    if hypothetical is None:
        return "not_computable"
    if any(note.startswith("missing_or_malformed") or note.startswith("missing_or_unknown") for note in notes):
        return "partial"
    if any(note in {"source_cash_disagreement", "opening_exposure_unknown", "size_inferred_not_direct"} for note in notes):
        return "review"
    return "ok"


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sidecar-only Side/Outcome Phase 3 capital-at-risk impact audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-json", default=str(DEFAULT_JSON_OUTPUT))
    parser.add_argument("--output-md", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--max-files", type=int, default=250)
    parser.add_argument("--max-rows-per-file", type=int, default=200)
    parser.add_argument("--max-bytes", type=int, default=5_000_000)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    records, artifacts, skipped = discover_phase3_records(
        args.root,
        max_files=args.max_files,
        max_rows_per_file=args.max_rows_per_file,
        max_bytes=args.max_bytes,
    )
    report = build_phase3_capital_at_risk_audit(records, artifacts=artifacts, skipped_artifacts=skipped)
    written = write_outputs(report, markdown_path=args.output_md, json_path=args.output_json)
    if not args.quiet:
        print(json.dumps({"gateDecision": report["gateDecision"], **written}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
