#!/usr/bin/env python3
"""Sidecar-only readiness audit for Side/Outcome Phase 2 model migration.

This tool reads local artifacts and compares current raw-token price semantics
with hypothetical economic-side probability semantics. It does not import or
modify production scanner/archive/Event Forensic runtime paths.
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


REPORT_TYPE = "side_outcome_phase2_readiness_impact_audit"
SCHEMA_VERSION = "side_outcome_phase2_readiness_v1"
LOW_PROBABILITY_SCANNER = Decimal("0.30")
LOW_PROBABILITY_FORENSIC = Decimal("0.35")
NEAR_CERTAINTY = Decimal("0.95")
VERY_NEAR_CERTAINTY = Decimal("0.98")


def discover_artifact_paths(root: str | Path) -> list[tuple[str, Path]]:
    base = Path(root)
    patterns = [
        ("scanner_report_json", ".inspoly/reports/scan_*.json"),
        ("reconstruction_normalized_trades_csv", "polymarket*_report/normalized_trades.csv"),
        ("ceasefire_event_json", "ceasefire_forensic_outputs/*/event_analysis.json"),
        ("ceasefire_suspicious_csv", "ceasefire_forensic_outputs/*/suspicious_trades.csv"),
        ("ceasefire_ranked_csv", "ceasefire_forensic_outputs/*/ranked_suspicious_trades.csv"),
        ("ceasefire_all_opening_csv", "ceasefire_forensic_outputs/*/all_yes_opening_trades_prefinal_48h.csv"),
        ("event_forensic_json", "event_forensic_outputs/*/event_analysis.json"),
        ("event_forensic_suspicious_csv", "event_forensic_outputs/*/suspicious_trades.csv"),
        ("event_forensic_candidate_csv", "event_forensic_outputs/*/candidate_trades.csv"),
    ]
    discovered: list[tuple[str, Path]] = []
    for family, pattern in patterns:
        for path in sorted(base.glob(pattern)):
            if path.is_file():
                discovered.append((family, path))
    return discovered


def load_records_from_paths(
    paths: Sequence[tuple[str, Path]],
    *,
    max_files: int | None = None,
    max_rows_per_file: int | None = None,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for file_index, (family, path) in enumerate(paths):
        if max_files is not None and file_index >= max_files:
            break
        if path.suffix.lower() == ".json":
            records.extend(_records_from_json(path, family=family, max_rows=max_rows_per_file))
        elif path.suffix.lower() == ".csv":
            records.extend(_records_from_csv(path, family=family, max_rows=max_rows_per_file))
    return records


def build_phase2_readiness_audit(records: Sequence[Mapping[str, object]], *, root: str | Path = ".") -> dict[str, object]:
    evaluated = [evaluate_trade_record(record) for record in records]
    summary = _summarize_evaluated(evaluated)
    baseline = inspect_phase1_baseline(root)
    decision = _gate_decision(summary)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "implementationAllowed": False,
        "phase2ImplementationAllowed": False,
        "gateDecision": decision,
        "baseline": baseline,
        "summary": summary,
        "affectedExamples": _affected_examples(evaluated),
        "unsafeOrMissingFieldExamples": _unsafe_examples(evaluated),
        "modelBehaviorDeltas": {
            "lowProbabilityConviction": "Would use economic-side probability instead of raw token price; SELL rows can flip in both directions.",
            "nearCertaintyInterpretation": "Would use economic-side probability; SELL Yes at low Yes-token price can become near-certain No exposure.",
            "eventForensicLaterCorrectness": "Would compare economic side to winning outcome; opening SELL rows can invert laterWon.",
            "winnerRank": "Would rank economic-side winners; opening shorts need separate rank reconstruction before migration.",
            "clusterDirection": "Would group by normalized economic direction such as long_no instead of short_yes vs long_no.",
            "capitalAtRisk": "Opening SELL rows need verified accounting semantics before replacing raw notional.",
            "fundingHerStrongRisk": "Funding/HER/Strong Risk can be affected indirectly when low-probability, winner-rank, or near-certainty meanings change; separate approval gate required.",
        },
        "blockedWithoutSeparateApproval": [
            "_score_trade() changes",
            "_event_forensic_score() changes",
            "scoring weights or severity labels",
            "Strong Risk/HER routing",
            "funding eligibility",
            "candidate admission",
            "browser runtime sorting/filter behavior",
            "storage schema or saved artifact mutation",
            "Phase 3 capital-at-risk migration",
            "Phase 4 cluster-direction migration",
        ],
    }


def evaluate_trade_record(record: Mapping[str, object]) -> dict[str, object]:
    artifact_family = str(record.get("artifactFamily") or "unknown")
    artifact_path = str(record.get("artifactPath") or "")
    order_side = _order_side(record)
    token_outcome = _token_outcome(record, artifact_family)
    price_value = _first_nonblank(
        record.get("price"),
        record.get("rawTokenPrice"),
        record.get("raw_token_price"),
        record.get("entry_probability_pct"),
        record.get("price_implied_probability"),
    )
    normalized = normalize_side_outcome(order_side, token_outcome, price_value)
    raw_probability = normalized.raw_token_price
    economic_probability = normalized.economic_side_probability
    current_direction = _current_direction(record, order_side, token_outcome)
    hypothetical_direction = normalized.economic_direction_normalized
    current_low_30 = _threshold(raw_probability, "<=", LOW_PROBABILITY_SCANNER)
    hypothetical_low_30 = _threshold(economic_probability, "<=", LOW_PROBABILITY_SCANNER)
    current_low_35 = _threshold(raw_probability, "<=", LOW_PROBABILITY_FORENSIC)
    hypothetical_low_35 = _threshold(economic_probability, "<=", LOW_PROBABILITY_FORENSIC)
    current_near_95 = _threshold(raw_probability, ">=", NEAR_CERTAINTY)
    hypothetical_near_95 = _threshold(economic_probability, ">=", NEAR_CERTAINTY)
    current_near_98 = _threshold(raw_probability, ">=", VERY_NEAR_CERTAINTY)
    hypothetical_near_98 = _threshold(economic_probability, ">=", VERY_NEAR_CERTAINTY)
    winning_outcome = _normalize_outcome(_first_nonblank(record.get("winningOutcome"), record.get("winning_outcome")))
    current_later_won = _bool_or_none(_first_nonblank(record.get("laterWon"), record.get("later_won")))
    if current_later_won is None and winning_outcome != UNKNOWN and normalized.raw_token_outcome != UNKNOWN:
        current_later_won = normalized.raw_token_outcome == winning_outcome
    hypothetical_later_won = None
    if winning_outcome != UNKNOWN and normalized.economic_side != UNKNOWN:
        hypothetical_later_won = normalized.economic_side == winning_outcome
    opening = _opening_exposure(record)
    size = _decimal_or_none(_first_nonblank(record.get("size"), record.get("shares")))
    notional = _decimal_or_none(
        _first_nonblank(
            record.get("notional"),
            record.get("notional_usdc"),
            record.get("positionSize"),
            record.get("trade_notional_usdc"),
        )
    )
    inferred_size = size
    if inferred_size is None and notional is not None and raw_probability not in (None, Decimal("0")):
        inferred_size = notional / raw_probability
    hypothetical_sell_exposure = None
    if normalized.raw_order_side == "SELL" and inferred_size is not None and raw_probability is not None:
        hypothetical_sell_exposure = (Decimal("1") - raw_probability) * inferred_size
    quality_notes = _quality_notes(
        normalized=normalized,
        record=record,
        opening=opening,
        size=size,
        inferred_size=inferred_size,
        notional=notional,
        current_later_won=current_later_won,
        hypothetical_later_won=hypothetical_later_won,
    )
    changed_flags = {
        "lowProbability30Changed": _changed(current_low_30, hypothetical_low_30),
        "lowProbability35Changed": _changed(current_low_35, hypothetical_low_35),
        "nearCertainty95Changed": _changed(current_near_95, hypothetical_near_95),
        "nearCertainty98Changed": _changed(current_near_98, hypothetical_near_98),
        "directionChanged": bool(
            current_direction
            and hypothetical_direction != UNKNOWN
            and current_direction != hypothetical_direction
        ),
        "laterCorrectnessChanged": _changed(current_later_won, hypothetical_later_won),
    }
    changed_flags["anyModelRelevantChange"] = any(changed_flags.values())
    sensitive_gate_context = _sensitive_gate_context(record)
    return {
        "artifactFamily": artifact_family,
        "artifactPath": artifact_path,
        "rowId": str(_first_nonblank(record.get("id"), record.get("trade_id"), record.get("transactionHash"), record.get("sequence"), "")),
        "uniqueTradeKey": _unique_trade_key(record, normalized),
        "wallet": str(record.get("wallet") or ""),
        "conditionId": str(_first_nonblank(record.get("conditionId"), record.get("condition_id"), "")),
        "market": str(_first_nonblank(record.get("market"), record.get("market_title"), record.get("title"), "")),
        "rawOrderSide": normalized.raw_order_side,
        "rawTokenOutcome": normalized.raw_token_outcome,
        "rawTokenPrice": _decimal_text(raw_probability),
        "economicSide": normalized.economic_side,
        "economicSideProbability": _decimal_text(economic_probability),
        "currentDirection": current_direction or UNKNOWN,
        "hypotheticalDirection": hypothetical_direction,
        "openingExposure": opening,
        "currentLowProbability30": current_low_30,
        "hypotheticalLowProbability30": hypothetical_low_30,
        "currentLowProbability35": current_low_35,
        "hypotheticalLowProbability35": hypothetical_low_35,
        "currentNearCertainty95": current_near_95,
        "hypotheticalNearCertainty95": hypothetical_near_95,
        "currentNearCertainty98": current_near_98,
        "hypotheticalNearCertainty98": hypothetical_near_98,
        "currentLaterWon": current_later_won,
        "hypotheticalLaterWon": hypothetical_later_won,
        "winningOutcome": winning_outcome,
        "winnerRank": _first_nonblank(record.get("winnerRank"), record.get("winner_rank"), ""),
        "currentNotional": _decimal_text(notional),
        "currentSize": _decimal_text(size),
        "inferredSize": _decimal_text(inferred_size),
        "hypotheticalSellComplementExposure": _decimal_text(hypothetical_sell_exposure),
        "phase1FieldsPresent": _phase1_fields_present(record),
        "sensitiveGateContext": sensitive_gate_context,
        "qualityNotes": quality_notes,
        **changed_flags,
    }


def inspect_phase1_baseline(root: str | Path = ".") -> dict[str, object]:
    base = Path(root)
    scanner = (base / "app/scanner.py").read_text(encoding="utf-8")
    event = (base / "app/event_forensic.py").read_text(encoding="utf-8")
    score_trade_body = _function_slice(scanner, "def _score_trade(")
    event_score_body = _function_slice(event, "def _event_forensic_score(")
    return {
        "phase1AdditiveOnly": True,
        "oldFieldsPreserved": [
            "price_implied_probability",
            "entryProbability",
            "economic_direction",
            "side",
            "outcome",
            "orderSide",
            "existing CSV/report fields",
        ],
        "scoreTradeImportsOrCallsSideOutcome": "normalize_side_outcome" in score_trade_body or "app.side_outcome" in score_trade_body,
        "eventForensicScoreImportsOrCallsSideOutcome": (
            "normalize_side_outcome" in event_score_body
            or "_case_side_outcome_model" in event_score_body
            or "app.side_outcome" in event_score_body
        ),
        "rawTokenPriceModelSignalInventory": [
            "app/scanner.py: price_implied_probability = trade.price * 100",
            "app/scanner.py: low_probability_conviction uses economic-side model_probability <= 0.30 when side/outcome/price normalize safely",
            "app/scanner.py: near_certainty_trade uses economic-side model_probability >= 0.95/0.98 when side/outcome/price normalize safely",
            "app/scanner.py: suspicious funding support/suppressors still read preserved raw price_implied_probability and existing funding fields",
            "app/scanner.py: same-side clusters use raw side/outcome or legacy economic_direction",
            "app/event_forensic.py: laterWon and winner ranks compare economic side to winning outcome for opening/increasing rows",
            "app/event_forensic.py: _event_forensic_score uses economic-side model probability for low-probability and near-certainty checks",
            "app/event_forensic.py: wallet hard-evidence attribution uses economic-side model probability for low_probability_early_winner where payload context is available",
            "app/browser*.html: entryProbability sort/filter values remain raw token price",
        ],
    }


def write_audit_outputs(report: Mapping[str, object], *, markdown_path: str | Path, json_path: str | Path | None = None) -> dict[str, str]:
    md_path = Path(markdown_path)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(readiness_markdown(report), encoding="utf-8")
    paths = {"markdownPath": str(md_path)}
    if json_path is not None:
        js_path = Path(json_path)
        js_path.parent.mkdir(parents=True, exist_ok=True)
        js_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        paths["jsonPath"] = str(js_path)
    return paths


def readiness_markdown(report: Mapping[str, object]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    baseline = report.get("baseline") if isinstance(report.get("baseline"), Mapping) else {}
    affected = summary.get("affectedUniqueTradeKeys") if isinstance(summary.get("affectedUniqueTradeKeys"), Mapping) else {}
    family_counts = summary.get("artifactFamilyCounts") if isinstance(summary.get("artifactFamilyCounts"), Mapping) else {}
    unsafe = summary.get("unsafeOrMissingFieldCounts") if isinstance(summary.get("unsafeOrMissingFieldCounts"), Mapping) else {}
    examples = report.get("affectedExamples") if isinstance(report.get("affectedExamples"), list) else []
    unsafe_examples = report.get("unsafeOrMissingFieldExamples") if isinstance(report.get("unsafeOrMissingFieldExamples"), list) else []
    lines = [
        "# InsPoly Side/Outcome Phase 2 Readiness Impact Audit",
        "",
        "- Date: 2026-05-22",
        "- Scope: sidecar-only evidence audit",
        "- Runtime implementation allowed: `false`",
        f"- Gate decision: `{report.get('gateDecision')}`",
        "",
        "## Phase 1 Baseline",
        "",
        "- Phase 1 added additive raw-token/economic-side fields to new reports, exports, and browser payloads.",
        "- Old raw fields remain preserved: `price_implied_probability`, `entryProbability`, `economic_direction`, and existing CSV/report fields.",
        f"- `_score_trade()` calls/imports side-outcome helper inside scorer body: `{str(baseline.get('scoreTradeImportsOrCallsSideOutcome')).lower()}`.",
        f"- `_event_forensic_score()` calls/imports side-outcome helper inside scorer body: `{str(baseline.get('eventForensicScoreImportsOrCallsSideOutcome')).lower()}`.",
        "- Phase 1 is therefore reporting/display/schema clarity only, not model migration.",
        "",
        "## Current Model Signal Inventory",
        "",
    ]
    lines.extend(f"- {item}" for item in baseline.get("rawTokenPriceModelSignalInventory", []))
    lines.extend(
        [
            "",
            "## Artifact Coverage",
            "",
            f"- Records scanned: `{summary.get('recordsScanned')}`",
            f"- Evaluable records: `{summary.get('evaluableRecords')}`",
            f"- Unique trade keys: `{summary.get('uniqueTradeKeys')}`",
            f"- Phase 1 field coverage records: `{summary.get('phase1FieldPresentRecords')}`",
            "",
            "| Artifact family | Records |",
            "|---|---:|",
        ]
    )
    for family, count in sorted(family_counts.items()):
        lines.append(f"| `{family}` | {count} |")
    missing_families = summary.get("artifactFamiliesMissingOrNotFoundInSample")
    if isinstance(missing_families, list) and missing_families:
        lines.extend(
            [
                "",
                "Missing or not found in this bounded local sample:",
            ]
        )
        lines.extend(f"- `{item}`" for item in missing_families)
    lines.extend(
        [
            "",
            "## Affected / Unaffected Cases",
            "",
            "| Impact surface | Unique affected trade keys |",
            "|---|---:|",
        ]
    )
    for key in (
        "lowProbability30Changed",
        "lowProbability35Changed",
        "nearCertainty95Changed",
        "nearCertainty98Changed",
        "directionChanged",
        "laterCorrectnessChanged",
        "anyModelRelevantChange",
        "sensitiveGateContextAffected",
    ):
        lines.append(f"| `{key}` | {affected.get(key, 0)} |")
    lines.extend(
        [
            "",
            f"- Unaffected unique trade keys: `{summary.get('unaffectedUniqueTradeKeys')}`",
            "",
            "## Unsafe / Missing Fields",
            "",
            "| Issue | Records |",
            "|---|---:|",
        ]
    )
    for key, count in sorted(unsafe.items()):
        lines.append(f"| `{key}` | {count} |")
    lines.extend(
        [
            "",
            "## What Would Change In Phase 2",
            "",
            "- Low-probability conviction would stop treating every low raw token price as low economic-side probability.",
            "- Near-certainty suppressors would be evaluated on the trader's economic side, so opening `SELL Yes @ 0.05` becomes near-certain No exposure rather than low-probability Yes exposure.",
            "- Event Forensic `laterWon`, winner-rank, and low-probability winner attribution could invert for opening `SELL Yes` / `SELL No` rows.",
            "- Same-side cluster logic would need normalized economic direction to group `SELL Yes` with `BUY No` and `SELL No` with `BUY Yes`.",
            "- Capital-at-risk requires a separate accounting migration because opening SELL complement exposure cannot be safely inferred for all artifact shapes.",
            "- Funding/HER/Strong Risk must remain gated because they consume low-probability, winner-rank, near-certainty, and hard-evidence meanings.",
            "",
            "## Event Forensic Impact",
            "",
            "- Current `laterWon` and `winnerRank` semantics are traded-token-outcome based.",
            "- Hypothetical Phase 2 would need economic-side correctness for opening/increasing SELL rows.",
            "- This audit marks row-level later-correctness inversions when `winningOutcome` is present, but full winner-rank migration still needs full chronological market candidate sets, not only top/display rows.",
            "- Browser sort/filter labels may remain raw token price unless a separate UI behavior change is approved; Phase 2 should not silently change sorting.",
            "",
            "## Cluster Direction Pre-Audit",
            "",
            "- Current scanner/Event grouping uses raw side/outcome or legacy directions such as `short_yes`.",
            "- Hypothetical normalized grouping would use `long_yes` / `long_no` economic direction.",
            "- This audit counts direction changes as cluster-relevant evidence only; it does not alter cluster logic.",
            "",
            "## Capital-At-Risk Pre-Audit",
            "",
            "- Current `capital_at_risk_usdc` and notional fields are raw execution/notional context.",
            "- Opening SELL complement exposure can be estimated when size/price are available, but this remains unsafe for production until Polymarket accounting semantics are verified across artifacts.",
            "- Missing size/notional or inferred-size rows are blockers for Phase 3, not reasons to change Phase 2 scoring now.",
            "",
            "## Funding / HER / Strong Risk Safety",
            "",
            "- Funding support, suppressor conflicts, HER routing, and Strong Risk traces can consume low-probability, near-certainty, winner-rank, or hard-evidence meanings.",
            "- Any migration that changes those meanings requires a separate approval gate and targeted gate-preservation tests.",
            "- This report does not permit funding, HER, Strong Risk, candidate-admission, severity-label, or sorting changes.",
            "",
            "## Affected Examples",
            "",
        ]
    )
    if examples:
        for item in examples:
            lines.append(
                f"- `{item.get('artifactFamily')}` `{item.get('rowId') or item.get('uniqueTradeKey')}`: "
                f"{item.get('rawOrderSide')} {item.get('rawTokenOutcome')} raw={item.get('rawTokenPrice')} "
                f"economic={item.get('economicSide')}@{item.get('economicSideProbability')} "
                f"changes={', '.join(item.get('changedFields', []))}"
            )
    else:
        lines.append("- No affected examples found in scanned artifacts.")
    lines.extend(["", "## Unsafe Examples", ""])
    if unsafe_examples:
        for item in unsafe_examples:
            lines.append(
                f"- `{item.get('artifactFamily')}` `{item.get('rowId') or item.get('uniqueTradeKey')}`: "
                f"{'; '.join(item.get('qualityNotes', []))}"
            )
    else:
        lines.append("- No unsafe/missing examples found.")
    lines.extend(
        [
            "",
            "## Gate Decision",
            "",
            f"Decision: `{report.get('gateDecision')}`.",
            "",
            "This audit does not authorize Phase 2 implementation. It is enough to justify a narrow Phase 2 RFC only if the gate is `ready_for_phase2_rfc`; implementation still requires separate explicit approval and tests that preserve all existing gates until migration semantics are accepted.",
            "",
            "## Explicit Blocks",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("blockedWithoutSeparateApproval", []))
    return "\n".join(lines).rstrip() + "\n"


def _records_from_json(path: Path, *, family: str, max_rows: int | None) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows: list[dict[str, object]] = []
    if not isinstance(payload, Mapping):
        return rows
    if family == "scanner_report_json":
        for index, case in enumerate(payload.get("cases") or []):
            if not isinstance(case, Mapping):
                continue
            trade = case.get("trade") if isinstance(case.get("trade"), Mapping) else {}
            raw = case.get("raw_metrics") if isinstance(case.get("raw_metrics"), Mapping) else {}
            row = {**trade, **raw}
            row.update(
                {
                    "artifactFamily": family,
                    "artifactPath": str(path),
                    "rowIndex": index,
                    "id": trade.get("trade_id") or case.get("id") or index,
                    "severity": case.get("severity"),
                    "flags": case.get("flags"),
                }
            )
            rows.append(row)
            if max_rows is not None and len(rows) >= max_rows:
                return rows
        return rows
    for key in ("suspicious_trades", "display_trades", "candidate_trades", "trades"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for index, item in enumerate(values):
            if not isinstance(item, Mapping):
                continue
            raw = item.get("rawMetrics") if isinstance(item.get("rawMetrics"), Mapping) else {}
            row = {**raw, **item}
            row.update({"artifactFamily": family, "artifactPath": str(path), "rowIndex": index})
            rows.append(row)
            if max_rows is not None and len(rows) >= max_rows:
                return rows
    return rows


def _records_from_csv(path: Path, *, family: str, max_rows: int | None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader):
                row["artifactFamily"] = family
                row["artifactPath"] = str(path)
                row["rowIndex"] = index
                rows.append(row)
                if max_rows is not None and len(rows) >= max_rows:
                    break
    except OSError:
        return []
    return rows


def _summarize_evaluated(evaluated: Sequence[Mapping[str, object]]) -> dict[str, object]:
    family_counts = Counter(str(item.get("artifactFamily") or "unknown") for item in evaluated)
    unique_keys = {str(item.get("uniqueTradeKey")) for item in evaluated if item.get("uniqueTradeKey")}
    affected_by_surface: dict[str, set[str]] = defaultdict(set)
    unsafe_counts: Counter[str] = Counter()
    side_counts: Counter[str] = Counter()
    phase1_count = 0
    evaluable = 0
    for item in evaluated:
        key = str(item.get("uniqueTradeKey") or "")
        if item.get("rawTokenPrice") != UNKNOWN and item.get("economicSideProbability") != UNKNOWN:
            evaluable += 1
        if item.get("phase1FieldsPresent"):
            phase1_count += 1
        side_counts[f"{item.get('rawOrderSide')}_{item.get('rawTokenOutcome')}"] += 1
        for note in item.get("qualityNotes", []):
            unsafe_counts[str(note)] += 1
        for surface in (
            "lowProbability30Changed",
            "lowProbability35Changed",
            "nearCertainty95Changed",
            "nearCertainty98Changed",
            "directionChanged",
            "laterCorrectnessChanged",
            "anyModelRelevantChange",
        ):
            if item.get(surface) and key:
                affected_by_surface[surface].add(key)
        if item.get("anyModelRelevantChange") and item.get("sensitiveGateContext") and key:
            affected_by_surface["sensitiveGateContextAffected"].add(key)
    affected_any = affected_by_surface.get("anyModelRelevantChange", set())
    return {
        "recordsScanned": len(evaluated),
        "evaluableRecords": evaluable,
        "uniqueTradeKeys": len(unique_keys),
        "phase1FieldPresentRecords": phase1_count,
        "artifactFamilyCounts": dict(sorted(family_counts.items())),
        "artifactFamiliesExpected": [
            "scanner_report_json",
            "archive_report_or_csv",
            "event_forensic_json",
            "event_forensic_suspicious_csv",
            "reconstruction_normalized_trades_csv",
            "ceasefire_case_specific_outputs",
        ],
        "artifactFamiliesMissingOrNotFoundInSample": _missing_artifact_families(family_counts),
        "sideOutcomeCounts": dict(sorted(side_counts.items())),
        "affectedUniqueTradeKeys": {
            surface: len(keys)
            for surface, keys in sorted(affected_by_surface.items())
        },
        "unaffectedUniqueTradeKeys": max(len(unique_keys) - len(affected_any), 0),
        "unsafeOrMissingFieldCounts": dict(sorted(unsafe_counts.items())),
    }


def _missing_artifact_families(family_counts: Counter[str]) -> list[str]:
    missing: list[str] = []
    if not family_counts.get("scanner_report_json"):
        missing.append("scanner_report_json")
    if not any(name.startswith("archive") for name in family_counts):
        missing.append("archive_report_or_csv")
    if not any(name.startswith("event_forensic") for name in family_counts):
        missing.append("event_forensic_outputs")
    if not family_counts.get("reconstruction_normalized_trades_csv"):
        missing.append("reconstruction_normalized_trades_csv")
    if not any(name.startswith("ceasefire") for name in family_counts):
        missing.append("ceasefire_case_specific_outputs")
    return missing


def _affected_examples(evaluated: Sequence[Mapping[str, object]], limit: int = 12) -> list[dict[str, object]]:
    examples: list[dict[str, object]] = []
    seen: set[str] = set()
    surfaces = [
        "lowProbability30Changed",
        "lowProbability35Changed",
        "nearCertainty95Changed",
        "nearCertainty98Changed",
        "directionChanged",
        "laterCorrectnessChanged",
    ]
    for item in evaluated:
        key = str(item.get("uniqueTradeKey") or "")
        if not key or key in seen or not item.get("anyModelRelevantChange"):
            continue
        seen.add(key)
        examples.append(
            {
                "artifactFamily": item.get("artifactFamily"),
                "artifactPath": item.get("artifactPath"),
                "rowId": item.get("rowId"),
                "uniqueTradeKey": key,
                "rawOrderSide": item.get("rawOrderSide"),
                "rawTokenOutcome": item.get("rawTokenOutcome"),
                "rawTokenPrice": item.get("rawTokenPrice"),
                "economicSide": item.get("economicSide"),
                "economicSideProbability": item.get("economicSideProbability"),
                "changedFields": [surface for surface in surfaces if item.get(surface)],
            }
        )
        if len(examples) >= limit:
            break
    return examples


def _unsafe_examples(evaluated: Sequence[Mapping[str, object]], limit: int = 12) -> list[dict[str, object]]:
    examples: list[dict[str, object]] = []
    for item in evaluated:
        notes = item.get("qualityNotes")
        if not notes:
            continue
        examples.append(
            {
                "artifactFamily": item.get("artifactFamily"),
                "artifactPath": item.get("artifactPath"),
                "rowId": item.get("rowId"),
                "uniqueTradeKey": item.get("uniqueTradeKey"),
                "qualityNotes": list(notes),
            }
        )
        if len(examples) >= limit:
            break
    return examples


def _gate_decision(summary: Mapping[str, object]) -> str:
    records = int(summary.get("recordsScanned") or 0)
    evaluable = int(summary.get("evaluableRecords") or 0)
    affected = summary.get("affectedUniqueTradeKeys") if isinstance(summary.get("affectedUniqueTradeKeys"), Mapping) else {}
    affected_any = int(affected.get("anyModelRelevantChange") or 0)
    if records < 20 or evaluable < 10:
        return "needs_more_fixtures"
    if affected_any > 0:
        return "ready_for_phase2_rfc"
    return "keep_phase1_only"


def _quality_notes(
    *,
    normalized: object,
    record: Mapping[str, object],
    opening: bool,
    size: Decimal | None,
    inferred_size: Decimal | None,
    notional: Decimal | None,
    current_later_won: bool | None,
    hypothetical_later_won: bool | None,
) -> list[str]:
    notes: list[str] = []
    if normalized.raw_order_side == UNKNOWN:
        notes.append("missing_or_unknown_order_side")
    if normalized.raw_token_outcome == UNKNOWN:
        notes.append("missing_or_unknown_token_outcome")
    if normalized.raw_token_price is None:
        notes.append("missing_or_unknown_token_price")
    if normalized.raw_order_side == "SELL" and opening:
        notes.append("opening_sell_requires_accounting_verification_before_capital_migration")
        if size is None and inferred_size is None:
            notes.append("opening_sell_missing_size_or_inferable_notional")
        elif size is None and inferred_size is not None and notional is not None:
            notes.append("opening_sell_size_inferred_from_notional_and_price")
    if (
        _first_nonblank(record.get("winningOutcome"), record.get("winning_outcome"))
        and current_later_won is not None
        and hypothetical_later_won is not None
        and current_later_won != hypothetical_later_won
    ):
        notes.append("event_forensic_later_correctness_would_invert")
    return notes


def _sensitive_gate_context(record: Mapping[str, object]) -> bool:
    text_fields = [
        record.get("severity"),
        record.get("existingModelClass"),
        record.get("finalEventJudgment"),
        record.get("hardEvidenceReviewTier"),
        record.get("hardEvidenceSources"),
        record.get("strongRiskGatePassed"),
        record.get("strongRiskGateEvidenceSources"),
        record.get("fundingEvidenceGrade"),
        record.get("funding_evidence_grade"),
        record.get("suspiciousFundingQuality"),
        record.get("suspiciousFundingIndependentSupport"),
        record.get("candidateAdmissionReason"),
    ]
    text = " ".join(str(item or "") for item in text_fields)
    return any(
        needle in text
        for needle in (
            "Strong Risk",
            "Hard Evidence Review",
            "suspicious",
            "direct_strict",
            "low_probability",
            "strict_shared_funding",
        )
    )


def _phase1_fields_present(record: Mapping[str, object]) -> bool:
    return any(
        key in record and record.get(key) not in (None, "")
        for key in (
            "rawTokenPriceLabel",
            "economicSideProbabilityLabel",
            "raw_token_price_label",
            "economic_side_probability_label",
            "economicDirectionNormalized",
            "economic_direction_normalized",
        )
    )


def _order_side(record: Mapping[str, object]) -> object:
    return _first_nonblank(
        record.get("orderSide"),
        record.get("order_side"),
        record.get("rawOrderSide"),
        record.get("raw_order_side"),
        record.get("side") if _side_looks_order_side(record.get("side")) else "",
    )


def _token_outcome(record: Mapping[str, object], family: str) -> object:
    if family.startswith("event_forensic"):
        return _first_nonblank(record.get("rawTokenOutcome"), record.get("side"), record.get("outcome"))
    return _first_nonblank(
        record.get("outcome"),
        record.get("rawTokenOutcome"),
        record.get("raw_token_outcome"),
        record.get("side") if not _side_looks_order_side(record.get("side")) else "",
    )


def _current_direction(record: Mapping[str, object], order_side: object, outcome: object) -> str:
    raw_direction = str(
        _first_nonblank(
            record.get("economic_direction"),
            record.get("economicDirection"),
            record.get("currentDirection"),
            "",
        )
    ).strip().lower()
    if raw_direction:
        if raw_direction.startswith("buy_"):
            return "long_" + raw_direction.split("_", 1)[1]
        if raw_direction.startswith("sell_"):
            return "short_" + raw_direction.split("_", 1)[1]
        return raw_direction
    side = str(order_side or "").strip().upper()
    token = _normalize_outcome(outcome)
    if token == UNKNOWN or side not in {"BUY", "SELL"}:
        return UNKNOWN
    return ("long_" if side == "BUY" else "short_") + token.lower()


def _opening_exposure(record: Mapping[str, object]) -> bool:
    value = _first_nonblank(
        record.get("openingExposure"),
        record.get("opening_exposure"),
        record.get("opening_exposure_flag"),
        record.get("trade_state"),
        record.get("tradeState"),
    )
    text = str(value or "").strip().lower()
    return text in {"true", "yes", "increase", "opening", "1"}


def _unique_trade_key(record: Mapping[str, object], normalized: object) -> str:
    parts = [
        _first_nonblank(record.get("id"), record.get("trade_id"), record.get("transactionHash"), ""),
        _first_nonblank(record.get("wallet"), ""),
        _first_nonblank(record.get("conditionId"), record.get("condition_id"), ""),
        _first_nonblank(record.get("timestamp"), record.get("timestamp_utc"), ""),
        normalized.raw_order_side,
        normalized.raw_token_outcome,
        _decimal_text(normalized.raw_token_price),
    ]
    return "|".join(str(part or "") for part in parts)


def _function_slice(source: str, signature: str) -> str:
    start = source.find(signature)
    if start < 0:
        return ""
    next_def = source.find("\ndef ", start + len(signature))
    if next_def < 0:
        return source[start:]
    return source[start:next_def]


def _side_looks_order_side(value: object) -> bool:
    return str(value or "").strip().upper() in {"BUY", "SELL"}


def _normalize_outcome(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"YES", "Y"}:
        return "YES"
    if text in {"NO", "N"}:
        return "NO"
    return UNKNOWN


def _threshold(value: Decimal | None, operator: str, threshold: Decimal) -> bool | None:
    if value is None:
        return None
    if operator == "<=":
        return value <= threshold
    if operator == ">=":
        return value >= threshold
    raise ValueError(f"unsupported operator: {operator}")


def _changed(left: object, right: object) -> bool:
    return left is not None and right is not None and left != right


def _bool_or_none(value: object) -> bool | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def _decimal_or_none(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        text = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
        if not text:
            return None
        value_decimal = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value_decimal if value_decimal.is_finite() else None


def _decimal_text(value: Decimal | None) -> str:
    return str(value) if value is not None else UNKNOWN


def _first_nonblank(*values: object) -> object:
    for value in values:
        if value not in (None, ""):
            return value
    return ""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sidecar-only Side/Outcome Phase 2 readiness impact audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-md", default="docs/inspoly_side_outcome_phase2_readiness_impact_audit_20260522.md")
    parser.add_argument("--output-json", default="side_outcome_audits/side_outcome_phase2_readiness_impact_audit_20260522.json")
    parser.add_argument("--max-files", type=int, default=250)
    parser.add_argument("--max-rows-per-file", type=int, default=500)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    paths = discover_artifact_paths(args.root)
    records = load_records_from_paths(paths, max_files=args.max_files, max_rows_per_file=args.max_rows_per_file)
    report = build_phase2_readiness_audit(records, root=args.root)
    written = write_audit_outputs(report, markdown_path=args.output_md, json_path=args.output_json)
    if not args.quiet:
        print(json.dumps({"gateDecision": report["gateDecision"], **written}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
