#!/usr/bin/env python3
"""Sidecar-only cluster-direction audit for Side/Outcome Phase 4.

This tool compares current raw/legacy cluster direction keys with hypothetical
economic-side normalized direction keys. It does not import scanner/archive/
Event Forensic runtime modules or change production behavior.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
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
from tools.side_outcome_phase3_capital_at_risk_audit import evaluate_capital_row


REPORT_TYPE = "side_outcome_phase4_cluster_direction_audit"
SCHEMA_VERSION = "side_outcome_phase4_cluster_direction_v1"
PHASE4_FIXTURE_DIR = Path("tests/fixtures/side_outcome_phase4_cluster_direction")
DEFAULT_JSON_OUTPUT = Path("side_outcome_audits/side_outcome_phase4_cluster_direction_audit_20260522.json")
DEFAULT_MARKDOWN_OUTPUT = Path("docs/inspoly_side_outcome_phase4_cluster_direction_impact_audit_20260522.md")
NORMALIZED_DIRECTIONS = {"long_yes", "long_no"}
LEGACY_DIRECTIONS = {"long_yes", "long_no", "short_yes", "short_no"}


def evaluate_cluster_row(record: Mapping[str, object]) -> dict[str, object]:
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
    current_direction, current_source = _current_cluster_direction(record, order_side, token_outcome)
    hypothetical_direction, hypothetical_source = _hypothetical_cluster_direction(record, normalized)
    scope_key = _scope_key(record)
    current_group_key = _group_key(scope_key, current_direction)
    hypothetical_group_key = _group_key(scope_key, hypothetical_direction)
    current_same_side_key = _raw_same_side_key(scope_key, normalized.raw_order_side, normalized.raw_token_outcome)
    affected = (
        current_direction != UNKNOWN
        and hypothetical_direction != UNKNOWN
        and current_direction != hypothetical_direction
    )
    phase3 = evaluate_capital_row(record)
    phase3_overlap = _phase3_blocked_overlap(phase3)
    quality_notes = _quality_notes(
        record=record,
        normalized=normalized,
        current_direction=current_direction,
        current_source=current_source,
        hypothetical_direction=hypothetical_direction,
        hypothetical_source=hypothetical_source,
        scope_key=scope_key,
        phase3_overlap=phase3_overlap,
    )
    return {
        "rowId": row_id,
        "artifactFamily": artifact_family,
        "artifactEvidenceType": artifact_type,
        "artifactPath": str(record.get("artifactPath") or ""),
        "uniqueTradeKey": _unique_trade_key(record, normalized, row_id),
        "wallet": str(record.get("wallet") or ""),
        "conditionId": str(_first_nonblank(record.get("conditionId"), record.get("condition_id"), "")),
        "marketSlug": str(_first_nonblank(record.get("marketSlug"), record.get("market_slug"), record.get("slug"), "")),
        "eventSlug": str(_first_nonblank(record.get("eventSlug"), record.get("event_slug"), record.get("parentEventSlug"), "")),
        "scopeKey": scope_key,
        "rawOrderSide": normalized.raw_order_side,
        "rawTokenOutcome": normalized.raw_token_outcome,
        "rawTokenPrice": str(normalized.raw_token_price) if normalized.raw_token_price is not None else UNKNOWN,
        "economicSide": normalized.economic_side,
        "economicSideProbability": str(normalized.economic_side_probability) if normalized.economic_side_probability is not None else UNKNOWN,
        "currentClusterDirection": current_direction,
        "currentClusterDirectionSource": current_source,
        "hypotheticalNormalizedClusterDirection": hypothetical_direction,
        "hypotheticalClusterDirectionSource": hypothetical_source,
        "currentSameSideGroupKey": current_group_key,
        "currentRawSameSideGroupKey": current_same_side_key,
        "hypotheticalSameSideGroupKey": hypothetical_group_key,
        "directionWouldChange": affected,
        "mergePreviouslySplitBuySellGroup": False,
        "mergeGroupCurrentDirections": [],
        "sensitivePhase2Context": _sensitive_context(record),
        "phase3CapitalAtRiskBlockedOverlap": phase3_overlap,
        "phase3CapitalDelta": phase3.get("capitalDelta"),
        "qualityNotes": quality_notes,
        "dataQualityStatus": _data_quality_status(quality_notes, hypothetical_direction),
        "phase4RuntimeImplementationAllowed": False,
        "phase3CapitalAtRiskApplied": False,
    }


def build_phase4_cluster_direction_audit(
    records: Sequence[Mapping[str, object]],
    *,
    artifacts: Sequence[Mapping[str, object]] | None = None,
    skipped_artifacts: Sequence[Mapping[str, object]] | None = None,
    runtime_verification: bool = False,
) -> dict[str, object]:
    evaluated = [evaluate_cluster_row(record) for record in records]
    _annotate_merge_groups(evaluated)
    summary = _summary(evaluated, artifacts or [], skipped_artifacts or [])
    gate_decision = _gate_decision(summary)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "implementationAllowed": runtime_verification,
        "phase4RuntimeImplementationAllowed": runtime_verification,
        "runtimeVerification": runtime_verification,
        "phase3CapitalAtRiskApplied": False,
        "gateDecision": gate_decision,
        "summary": summary,
        "truthTable": [
            {"rawOrderSide": "BUY", "rawTokenOutcome": "YES", "normalizedDirection": "long_yes"},
            {"rawOrderSide": "SELL", "rawTokenOutcome": "NO", "normalizedDirection": "long_yes"},
            {"rawOrderSide": "BUY", "rawTokenOutcome": "NO", "normalizedDirection": "long_no"},
            {"rawOrderSide": "SELL", "rawTokenOutcome": "YES", "normalizedDirection": "long_no"},
        ],
        "affectedExamples": _examples(evaluated, require_affected=True),
        "mergeExamples": _examples(evaluated, require_merge=True),
        "unsafeExamples": _examples(evaluated, require_notes=True),
        "implementationGuardrailsIfLaterApproved": [
            "Use one central normalized cluster-direction selector; do not duplicate BUY/SELL inversion across scanner/archive/Event Forensic paths.",
            "Keep legacy raw `economic_direction` and raw side/outcome fields for compatibility and display.",
            "Use normalized grouping only when side/outcome/price normalize safely or a trusted Phase 2 `model_economic_direction` provenance field is present.",
            "Do not change scoring weights, thresholds, candidate admission limits, Strong Risk/HER/funding gates, storage schema, or UI sorting/filter behavior in the same patch.",
            "Keep Phase 3 capital-at-risk normalization separate and blocked.",
        ],
        "explicitBlocks": [
            "Additional Phase 4 changes beyond normalized cluster/same-side grouping",
            "scoring weights or thresholds",
            "Strong Risk/HER/funding eligibility/candidate admission direct changes",
            "Phase 3 capital-at-risk normalization",
            "storage schema, UI sorting/filter, live/RPC/network behavior",
            "saved report or artifact mutation",
        ] if runtime_verification else [
            "Phase 4 runtime implementation",
            "_score_trade() or _event_forensic_score() Phase 4 edits",
            "scoring weights or thresholds",
            "Strong Risk/HER/funding eligibility/candidate admission direct changes",
            "Phase 3 capital-at-risk normalization",
            "storage schema, UI sorting/filter, live/RPC/network behavior",
            "saved report or artifact mutation",
        ],
    }


def discover_phase4_records(
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
    records.extend(load_records_from_paths(generic_paths, max_rows_per_file=max_rows_per_file))
    for family, path in generic_paths:
        artifacts.append(_artifact_ref(base, path, family=family, evidence_type="real_local"))
    for row in records:
        row.setdefault("artifactEvidenceType", "real_local")

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

    fixture_artifacts = _phase4_fixture_artifacts(base)
    fixture_records, fixture_skipped = _load_phase4_fixture_records(fixture_artifacts, max_rows_per_file=max_rows_per_file)
    artifacts.extend(fixture_artifacts)
    skipped.extend(fixture_skipped)
    records.extend(fixture_records)
    return records, artifacts, skipped


def write_outputs(report: Mapping[str, object], *, markdown_path: str | Path, json_path: str | Path) -> dict[str, str]:
    md = Path(markdown_path)
    js = Path(json_path)
    md.parent.mkdir(parents=True, exist_ok=True)
    js.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(cluster_audit_markdown(report), encoding="utf-8")
    js.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"markdownPath": str(md), "jsonPath": str(js)}


def cluster_audit_markdown(report: Mapping[str, object]) -> str:
    summary = _mapping(report.get("summary"))
    affected = _mapping(summary.get("affectedCounts"))
    unsafe = _mapping(summary.get("unsafeOrMissingFieldCounts"))
    family_counts = _mapping(summary.get("artifactFamilyCounts"))
    evidence_counts = _mapping(summary.get("evidenceTypeCounts"))
    direction_counts = _mapping(summary.get("directionTransitionCounts"))
    runtime_verification = bool(report.get("runtimeVerification"))
    lines = [
        "# InsPoly Side/Outcome Phase 4 Runtime Migration Verification"
        if runtime_verification
        else "# InsPoly Side/Outcome Phase 4 Cluster Direction Impact Audit",
        "",
        "- Date: 2026-05-22",
        "- Scope: post-implementation sidecar verification"
        if runtime_verification
        else "- Scope: sidecar-only RFC evidence and impact audit",
        f"- Runtime implementation verified: `{str(runtime_verification).lower()}`",
        f"- Gate decision: `{report.get('gateDecision')}`",
        "",
        "## Current Behavior Inventory",
        "",
        (
            "- Scanner same-side windows, structural pre-admission, split-wallet grouping, proxy tight cohorts, and coordinated sizing clusters now use safe normalized cluster direction."
            if runtime_verification
            else "- Scanner same-side windows currently group by raw `side` + `outcome`."
        ),
        (
            "- Legacy raw `economic_direction` remains preserved as a display/report compatibility field."
            if runtime_verification
            else "- Structural pre-admission, split-wallet grouping, proxy tight cohorts, and coordinated sizing clusters currently use legacy `economic_direction` such as `short_yes` / `long_no`."
        ),
        (
            "- Event Forensic timing clusters now use `clusterDirection` when normalization status is safe, with raw side/outcome fallback for malformed payloads."
            if runtime_verification
            else "- Phase 2 writes `model_economic_direction`, but cluster paths do not use it yet."
        ),
        "- Archive exports preserve both legacy direction and Phase 2 additive model direction fields.",
        (
            "- Phase 3 capital-at-risk remains blocked and is not applied by this audit."
            if runtime_verification
            else "- Event Forensic timing clusters currently group by `marketSlug`, `orderSide`, and token `side`."
        ),
        "",
        "## Target Semantics",
        "",
        "| Raw order | Raw token outcome | Normalized cluster direction |",
        "|---|---|---|",
        "| `BUY` | `YES` | `long_yes` |",
        "| `SELL` | `NO` | `long_yes` |",
        "| `BUY` | `NO` | `long_no` |",
        "| `SELL` | `YES` | `long_no` |",
        "",
        "## Audit Counts",
        "",
        f"- Records scanned: `{summary.get('recordsScanned', 0)}`",
        f"- Evaluable rows: `{summary.get('evaluableRows', 0)}`",
        f"- Rows where direction would change: `{affected.get('rowsWithDirectionChange', 0)}`",
        f"- Affected unique trade keys: `{affected.get('uniqueTradeKeysWithDirectionChange', 0)}`",
        f"- Affected wallets: `{affected.get('walletsWithDirectionChange', 0)}`",
        f"- Affected markets/scopes: `{affected.get('scopesWithDirectionChange', 0)}`",
        f"- Affected events: `{affected.get('eventsWithDirectionChange', 0)}`",
        f"- Rows in merge groups: `{affected.get('rowsInPreviouslySplitMergeGroups', 0)}`",
        f"- Sensitive overlap rows: `{affected.get('sensitiveOverlapRows', 0)}`",
        f"- Phase 3 capital-at-risk blocked overlap rows: `{affected.get('phase3BlockedOverlapRows', 0)}`",
        "",
        "| Evidence type | Rows | Direction-change rows |",
        "|---|---:|---:|",
    ]
    for evidence_type, values in sorted(evidence_counts.items()):
        counts = _mapping(values)
        lines.append(f"| `{evidence_type}` | {counts.get('records', 0)} | {counts.get('affectedRows', 0)} |")
    lines.extend(["", "| Artifact family | Rows |", "|---|---:|"])
    for family, count in sorted(family_counts.items()):
        lines.append(f"| `{family}` | {count} |")
    lines.extend(["", "## Direction Transitions", "", "| Transition | Rows |", "|---|---:|"])
    for key, count in sorted(direction_counts.items()):
        lines.append(f"| `{key}` | {count} |")
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
            "- Legacy `economic_direction` must remain raw/legacy for old reports and exports.",
            "- Old rows with only `economic_direction` are not safe for normalized cluster grouping unless a trusted Phase 2 `model_economic_direction` provenance field is present.",
            "- Normalized grouping can merge previously split BUY/SELL expressions and affect cluster-derived evidence.",
            "- Any downstream Strong Risk/HER/funding/candidate-admission movement must be treated as expected drift and guarded by tests, not hidden.",
            "- Phase 3 capital-at-risk remains blocked and must not be bundled into Phase 4.",
            "",
        "## Implemented Runtime Scope" if runtime_verification else "## Implementation Outline If Later Approved",
        "",
        (
            "1. Added a central cluster-direction selector that returns normalized direction plus provenance."
            if runtime_verification
            else "1. Add a central cluster-direction selector that returns normalized direction plus provenance."
        ),
        (
            "2. Migrated scanner same-side window grouping from raw side/outcome to normalized direction only when safe."
            if runtime_verification
            else "2. Migrate scanner same-side window grouping from raw side/outcome to normalized direction only when safe."
        ),
        (
            "3. Migrated structural pre-admission diagnostics and grouped-candidate IDs to normalized direction with old-field compatibility."
            if runtime_verification
            else "3. Migrate structural pre-admission diagnostics and grouped-candidate IDs to normalized direction with old-field compatibility."
        ),
        (
            "4. Migrated split-wallet, proxy tight cohort, coordinated sizing, and Event Forensic timing cluster grouping in focused patches."
            if runtime_verification
            else "4. Migrate split-wallet, proxy tight cohort, coordinated sizing, and Event Forensic timing cluster grouping in focused patches."
        ),
        (
            "5. Kept raw/display direction fields and CSV/report keys additive/compatible."
            if runtime_verification
            else "5. Keep raw/display direction fields and CSV/report keys additive/compatible."
        ),
        (
            "6. Phase 3 capital-at-risk remains blocked; this verification does not apply exposure normalization."
            if runtime_verification
            else "6. Re-run side/outcome, Phase 2 drift, Phase 3 audit, scanner/archive/Event Forensic, and cross-mode scoring tests."
        ),
        "",
        "## Verification Result" if runtime_verification else "## Gate Decision",
        "",
        f"Decision: `{report.get('gateDecision')}`.",
        "",
        (
            "Runtime implementation was approved separately and this output verifies the bounded Phase 4 cluster/same-side migration. Further Phase 3, scoring-weight, threshold, storage, live/RPC, or UI sorting changes remain blocked."
            if runtime_verification
            else "This audit does not authorize runtime implementation. A separate approval gate is required before changing scanner/archive/Event Forensic cluster behavior."
        ),
            "",
            "## Explicit Blocks",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("explicitBlocks", []))
    return "\n".join(lines).rstrip() + "\n"


def _annotate_merge_groups(evaluated: list[dict[str, object]]) -> None:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in evaluated:
        key = str(item.get("hypotheticalSameSideGroupKey") or "")
        if not key or key.endswith("|unknown"):
            continue
        groups[key].append(item)
    for items in groups.values():
        current_dirs = sorted(
            {
                str(item.get("currentClusterDirection") or UNKNOWN)
                for item in items
                if item.get("currentClusterDirection") != UNKNOWN
            }
        )
        if len(current_dirs) < 2:
            continue
        raw_actions = {
            f"{item.get('rawOrderSide')}_{item.get('rawTokenOutcome')}"
            for item in items
            if item.get("rawOrderSide") != UNKNOWN and item.get("rawTokenOutcome") != UNKNOWN
        }
        if not _has_buy_sell_equivalent_pair(raw_actions):
            continue
        for item in items:
            item["mergePreviouslySplitBuySellGroup"] = True
            item["mergeGroupCurrentDirections"] = current_dirs


def _summary(
    evaluated: Sequence[Mapping[str, object]],
    artifacts: Sequence[Mapping[str, object]],
    skipped: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    family_counts = Counter(str(item.get("artifactFamily") or "unknown") for item in evaluated)
    evidence_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"records": 0, "affectedRows": 0})
    unsafe = Counter()
    affected = Counter()
    affected_keys: set[str] = set()
    affected_wallets: set[str] = set()
    affected_scopes: set[str] = set()
    affected_events: set[str] = set()
    transitions = Counter()
    current_direction_counts = Counter()
    hypothetical_direction_counts = Counter()
    evaluable = 0
    for item in evaluated:
        evidence_type = str(item.get("artifactEvidenceType") or "unknown")
        evidence_counts[evidence_type]["records"] += 1
        current = str(item.get("currentClusterDirection") or UNKNOWN)
        hypothetical = str(item.get("hypotheticalNormalizedClusterDirection") or UNKNOWN)
        current_direction_counts[current] += 1
        hypothetical_direction_counts[hypothetical] += 1
        if hypothetical != UNKNOWN:
            evaluable += 1
        if item.get("directionWouldChange"):
            affected["rowsWithDirectionChange"] += 1
            evidence_counts[evidence_type]["affectedRows"] += 1
            transitions[f"{current}->{hypothetical}"] += 1
            if item.get("uniqueTradeKey"):
                affected_keys.add(str(item.get("uniqueTradeKey")))
            if item.get("wallet"):
                affected_wallets.add(str(item.get("wallet")))
            if item.get("scopeKey"):
                affected_scopes.add(str(item.get("scopeKey")))
            if item.get("eventSlug"):
                affected_events.add(str(item.get("eventSlug")))
            if item.get("sensitivePhase2Context"):
                affected["sensitiveOverlapRows"] += 1
            if item.get("phase3CapitalAtRiskBlockedOverlap"):
                affected["phase3BlockedOverlapRows"] += 1
        if item.get("mergePreviouslySplitBuySellGroup"):
            affected["rowsInPreviouslySplitMergeGroups"] += 1
        for note in item.get("qualityNotes", []):
            unsafe[str(note)] += 1
    affected["uniqueTradeKeysWithDirectionChange"] = len(affected_keys)
    affected["walletsWithDirectionChange"] = len(affected_wallets)
    affected["scopesWithDirectionChange"] = len(affected_scopes)
    affected["eventsWithDirectionChange"] = len(affected_events)
    return {
        "recordsScanned": len(evaluated),
        "artifactsSelected": len(artifacts),
        "artifactsSkipped": len(skipped),
        "evaluableRows": evaluable,
        "artifactFamilyCounts": dict(sorted(family_counts.items())),
        "evidenceTypeCounts": {key: dict(value) for key, value in sorted(evidence_counts.items())},
        "affectedCounts": dict(sorted(affected.items())),
        "directionTransitionCounts": dict(sorted(transitions.items())),
        "currentDirectionCounts": dict(sorted(current_direction_counts.items())),
        "hypotheticalDirectionCounts": dict(sorted(hypothetical_direction_counts.items())),
        "unsafeOrMissingFieldCounts": dict(sorted(unsafe.items())),
        "sampledArtifacts": [dict(item) for item in artifacts[:30]],
        "skippedArtifacts": [dict(item) for item in skipped[:30]],
    }


def _gate_decision(summary: Mapping[str, object]) -> str:
    affected = _mapping(summary.get("affectedCounts"))
    evidence = _mapping(summary.get("evidenceTypeCounts"))
    synthetic = _mapping(evidence.get("synthetic_fixture"))
    evaluable = int(summary.get("evaluableRows") or 0)
    if evaluable < 8 or int(synthetic.get("records") or 0) < 8:
        return "needs_more_cluster_fixtures"
    if int(affected.get("rowsInPreviouslySplitMergeGroups") or 0) <= 0:
        return "needs_more_cluster_fixtures"
    return "ready_for_phase4_implementation"


def _examples(
    evaluated: Sequence[Mapping[str, object]],
    *,
    require_affected: bool = False,
    require_merge: bool = False,
    require_notes: bool = False,
    limit: int = 12,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in evaluated:
        if require_affected and not item.get("directionWouldChange"):
            continue
        if require_merge and not item.get("mergePreviouslySplitBuySellGroup"):
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
                "currentClusterDirection": item.get("currentClusterDirection"),
                "hypotheticalNormalizedClusterDirection": item.get("hypotheticalNormalizedClusterDirection"),
                "currentSameSideGroupKey": item.get("currentSameSideGroupKey"),
                "hypotheticalSameSideGroupKey": item.get("hypotheticalSameSideGroupKey"),
                "mergePreviouslySplitBuySellGroup": item.get("mergePreviouslySplitBuySellGroup"),
                "qualityNotes": list(item.get("qualityNotes") or []),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _current_cluster_direction(record: Mapping[str, object], order_side: object, token_outcome: object) -> tuple[str, str]:
    explicit = _normalize_direction(
        _first_nonblank(
            record.get("economic_direction"),
            record.get("economicDirection"),
            record.get("currentClusterDirection"),
            record.get("current_cluster_direction"),
        )
    )
    if explicit != UNKNOWN:
        return explicit, "legacy_economic_direction_field"
    side = str(order_side or "").strip().upper()
    outcome = str(token_outcome or "").strip().upper()
    if side in {"BUY", "SELL"} and outcome in {"YES", "NO"}:
        prefix = "short" if side == "SELL" else "long"
        return f"{prefix}_{outcome.lower()}", "raw_side_outcome"
    return UNKNOWN, "unknown"


def _hypothetical_cluster_direction(record: Mapping[str, object], normalized) -> tuple[str, str]:
    if normalized.economic_direction_normalized in NORMALIZED_DIRECTIONS:
        return normalized.economic_direction_normalized, "normalize_side_outcome"
    model_direction = _normalize_direction(
        _first_nonblank(record.get("model_economic_direction"), record.get("modelEconomicDirection"))
    )
    status = str(_first_nonblank(record.get("side_outcome_normalization_status"), record.get("sideOutcomeNormalizationStatus"), "")).strip().lower()
    if model_direction in NORMALIZED_DIRECTIONS and status == "normalized":
        return model_direction, "trusted_phase2_model_economic_direction"
    return UNKNOWN, "unknown"


def _quality_notes(
    *,
    record: Mapping[str, object],
    normalized,
    current_direction: str,
    current_source: str,
    hypothetical_direction: str,
    hypothetical_source: str,
    scope_key: str,
    phase3_overlap: bool,
) -> list[str]:
    notes: list[str] = []
    if not scope_key:
        notes.append("missing_scope_key")
    if current_direction == UNKNOWN:
        notes.append("current_cluster_direction_unknown")
    if hypothetical_direction == UNKNOWN:
        notes.append(normalized.fallback_reason or "normalized_cluster_direction_unknown")
    if _old_direction_only(record):
        notes.append("old_economic_direction_only_not_safe_for_normalized_grouping")
    if current_source == "legacy_economic_direction_field" and hypothetical_source == "trusted_phase2_model_economic_direction":
        notes.append("phase2_model_direction_available_for_audit_only")
    if hypothetical_source == "unknown" and _normalize_direction(record.get("model_economic_direction")) in NORMALIZED_DIRECTIONS:
        notes.append("model_direction_without_trusted_normalization_status")
    if phase3_overlap:
        notes.append("overlaps_phase3_blocked_capital_at_risk_row")
    return _dedupe(notes)


def _data_quality_status(notes: Sequence[str], hypothetical_direction: str) -> str:
    if hypothetical_direction == UNKNOWN:
        return "not_computable"
    if any(note in {"missing_scope_key", "old_economic_direction_only_not_safe_for_normalized_grouping"} for note in notes):
        return "review"
    if notes:
        return "partial"
    return "ok"


def _phase3_blocked_overlap(phase3_eval: Mapping[str, object]) -> bool:
    if phase3_eval.get("capitalDelta") not in (UNKNOWN, "0", "0.00", None):
        return True
    notes = {str(note) for note in phase3_eval.get("qualityNotes", [])}
    return bool({"capital_at_risk_would_change", "opening_sell_complement_exposure_requires_accounting_gate"} & notes)


def _has_buy_sell_equivalent_pair(actions: set[str]) -> bool:
    return (
        {"BUY_YES", "SELL_NO"}.issubset(actions)
        or {"BUY_NO", "SELL_YES"}.issubset(actions)
    )


def _scope_key(record: Mapping[str, object]) -> str:
    return str(
        _first_nonblank(
            record.get("conditionId"),
            record.get("condition_id"),
            record.get("marketSlug"),
            record.get("market_slug"),
            record.get("slug"),
            record.get("market"),
            "",
        )
        or ""
    )


def _group_key(scope_key: str, direction: str) -> str:
    if not scope_key or direction == UNKNOWN:
        return UNKNOWN
    return f"{scope_key}|{direction}"


def _raw_same_side_key(scope_key: str, order_side: str, token_outcome: str) -> str:
    if not scope_key or order_side == UNKNOWN or token_outcome == UNKNOWN:
        return UNKNOWN
    return f"{scope_key}|{order_side}|{token_outcome}"


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


def _normalize_direction(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in LEGACY_DIRECTIONS else UNKNOWN


def _old_direction_only(record: Mapping[str, object]) -> bool:
    has_old_direction = _normalize_direction(record.get("economic_direction")) != UNKNOWN
    has_raw = all(_first_nonblank(record.get(key)) not in (None, "") for key in ("side", "outcome", "price"))
    has_model = _normalize_direction(record.get("model_economic_direction")) in NORMALIZED_DIRECTIONS
    return bool(has_old_direction and not has_raw and not has_model)


def _sensitive_context(record: Mapping[str, object]) -> bool:
    text = " ".join(str(value) for value in record.values() if value not in (None, ""))
    lowered = text.lower()
    markers = ("strong risk", "hard evidence", "her", "funding", "candidate", "suppression", "coordinated", "cluster")
    return any(marker in lowered for marker in markers)


def _unique_trade_key(record: Mapping[str, object], normalized, row_id: str) -> str:
    explicit = _first_nonblank(record.get("trade_id"), record.get("id"), record.get("transactionHash"), record.get("hash"))
    if explicit not in (None, ""):
        return str(explicit)
    parts = [
        str(record.get("wallet") or ""),
        str(_first_nonblank(record.get("conditionId"), record.get("condition_id"), "")),
        normalized.raw_order_side,
        normalized.raw_token_outcome,
        str(normalized.raw_token_price) if normalized.raw_token_price is not None else UNKNOWN,
        row_id,
    ]
    return "|".join(parts)


def _phase4_fixture_artifacts(base: Path) -> list[dict[str, object]]:
    fixture_root = base / PHASE4_FIXTURE_DIR
    refs: list[dict[str, object]] = []
    for path in sorted(fixture_root.glob("*")):
        if path.suffix.lower() not in {".json", ".csv"}:
            continue
        refs.append(_artifact_ref(base, path, family=f"phase4_synthetic_{path.suffix.lower().lstrip('.')}", evidence_type="synthetic_fixture"))
    return refs


def _load_phase4_fixture_records(
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
                values = payload.get("rows") if isinstance(payload, Mapping) else []
                for index, item in enumerate(values if isinstance(values, list) else []):
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


def _first_nonblank(*values: object) -> object:
    for value in values:
        if value not in (None, ""):
            return value
    return None


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
    parser = argparse.ArgumentParser(description="Sidecar-only Side/Outcome Phase 4 cluster direction impact audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-json", default=str(DEFAULT_JSON_OUTPUT))
    parser.add_argument("--output-md", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--max-files", type=int, default=250)
    parser.add_argument("--max-rows-per-file", type=int, default=200)
    parser.add_argument("--max-bytes", type=int, default=5_000_000)
    parser.add_argument("--runtime-verification", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    records, artifacts, skipped = discover_phase4_records(
        args.root,
        max_files=args.max_files,
        max_rows_per_file=args.max_rows_per_file,
        max_bytes=args.max_bytes,
    )
    report = build_phase4_cluster_direction_audit(
        records,
        artifacts=artifacts,
        skipped_artifacts=skipped,
        runtime_verification=args.runtime_verification,
    )
    written = write_outputs(report, markdown_path=args.output_md, json_path=args.output_json)
    if not args.quiet:
        print(json.dumps({"gateDecision": report["gateDecision"], **written}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
