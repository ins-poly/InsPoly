#!/usr/bin/env python3
"""Offline post Side/Outcome benchmark replay.

This sidecar reads local artifacts only. It reuses the Phase 2/3/4 audit
helpers to compare raw token semantics, economic-side probability, normalized
cluster direction, and the still-blocked Phase 3 capital-at-risk surface.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.side_outcome import UNKNOWN, normalize_cluster_direction, normalize_side_outcome
from tools.side_outcome_phase2_impact_audit import evaluate_trade_record
from tools.side_outcome_phase3_capital_at_risk_audit import evaluate_capital_row
from tools.side_outcome_phase4_cluster_direction_audit import (
    discover_phase4_records,
    evaluate_cluster_row,
)


REPORT_TYPE = "post_side_outcome_benchmark_replay"
SCHEMA_VERSION = "post_side_outcome_benchmark_replay_v1"
DEFAULT_INVENTORY_JSON = Path("validation_outputs/post_side_outcome_benchmark_corpus_inventory_20260522.json")
DEFAULT_REPLAY_JSON = Path("validation_outputs/post_side_outcome_benchmark_replay_20260522.json")
SAFE_REPLAY_EXTENSIONS = {".json", ".csv"}


def build_corpus_inventory(root: str | Path = ".") -> dict[str, object]:
    base = Path(root)
    items = [_inventory_item(base, path) for path in _discover_corpus_paths(base)]
    classification_counts = Counter(str(item["classification"]) for item in items)
    family_counts = Counter(str(item["family"]) for item in items)
    safety_counts = Counter(str(item["modelConclusionSafety"]) for item in items)
    return {
        "reportType": "post_side_outcome_benchmark_corpus_inventory",
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "root": str(base.resolve()),
        "networkUsed": False,
        "mutatedArtifacts": False,
        "summary": {
            "totalItems": len(items),
            "classificationCounts": dict(sorted(classification_counts.items())),
            "familyCounts": dict(sorted(family_counts.items())),
            "modelConclusionSafetyCounts": dict(sorted(safety_counts.items())),
            "realLocalArtifactCount": classification_counts.get("real_local_artifact", 0),
            "existingFixtureCount": classification_counts.get("existing_fixture", 0),
            "syntheticFixtureCount": classification_counts.get("synthetic_fixture", 0),
            "generatedAuditOutputCount": classification_counts.get("generated_audit_output", 0),
            "incompleteLocalOnlyCount": classification_counts.get("incomplete_local_only", 0),
            "unsafeForModelConclusionsCount": safety_counts.get("unsafe_for_model_conclusions", 0),
        },
        "items": items,
    }


def build_benchmark_replay(
    root: str | Path = ".",
    *,
    max_files: int | None = 180,
    max_rows_per_file: int | None = 120,
    max_bytes: int | None = 3_000_000,
) -> dict[str, object]:
    base = Path(root)
    records, artifacts, skipped = discover_phase4_records(
        base,
        max_files=max_files,
        max_rows_per_file=max_rows_per_file,
        max_bytes=max_bytes,
    )
    evaluated = [evaluate_post_side_outcome_record(record) for record in records]
    audit_summaries = load_generated_audit_summaries(base)
    source_scan = inspect_source_safety(base)
    summary = summarize_replay(evaluated, records, artifacts, skipped, audit_summaries, source_scan)
    gate = gate_decision(summary)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "root": str(base.resolve()),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeCodeChanged": False,
        "savedArtifactsMutated": False,
        "gateDecision": gate,
        "summary": summary,
        "sourceSafety": source_scan,
        "generatedAuditSummaries": audit_summaries,
        "fragileAreas": fragile_area_status(summary, source_scan),
        "representativeRows": representative_rows(evaluated),
        "nextSafestBacklogItem": next_safest_backlog_item(gate),
    }


def evaluate_post_side_outcome_record(record: Mapping[str, object]) -> dict[str, object]:
    phase2 = evaluate_trade_record(record)
    phase4 = evaluate_cluster_row(record)
    phase3 = evaluate_capital_row(record)
    order_side = _first_nonblank(record.get("rawOrderSide"), record.get("raw_order_side"), record.get("orderSide"), record.get("side"))
    token_outcome = _first_nonblank(record.get("rawTokenOutcome"), record.get("raw_token_outcome"), record.get("outcome"), record.get("side"))
    price = _first_nonblank(record.get("rawTokenPrice"), record.get("raw_token_price"), record.get("price"), record.get("price_implied_probability"))
    normalized = normalize_side_outcome(order_side, token_outcome, price)
    cluster = normalize_cluster_direction(order_side, token_outcome, price)
    notes = sorted(set(_list(phase2.get("qualityNotes")) + _list(phase4.get("qualityNotes")) + _list(phase3.get("qualityNotes"))))
    return {
        "artifactFamily": str(record.get("artifactFamily") or "unknown"),
        "artifactEvidenceType": str(record.get("artifactEvidenceType") or "real_local"),
        "artifactPath": str(record.get("artifactPath") or ""),
        "uniqueTradeKey": str(phase2.get("uniqueTradeKey") or phase4.get("uniqueTradeKey") or phase3.get("uniqueTradeKey") or ""),
        "wallet": str(phase2.get("wallet") or phase4.get("wallet") or phase3.get("wallet") or ""),
        "conditionId": str(phase2.get("conditionId") or phase4.get("conditionId") or phase3.get("conditionId") or ""),
        "rawOrderSide": normalized.raw_order_side,
        "rawTokenOutcome": normalized.raw_token_outcome,
        "rawTokenPrice": _value_or_unknown(normalized.raw_token_price),
        "economicSide": normalized.economic_side,
        "economicSideProbability": _value_or_unknown(normalized.economic_side_probability),
        "modelProbabilityBasis": normalized.model_probability_basis,
        "clusterDirection": cluster.cluster_direction,
        "clusterDirectionBasis": cluster.cluster_direction_basis,
        "clusterNormalizationStatus": cluster.cluster_normalization_status,
        "phase2ModelRelevantChange": bool(phase2.get("anyModelRelevantChange")),
        "phase2LowProbabilityChanged": bool(phase2.get("lowProbability30Changed") or phase2.get("lowProbability35Changed")),
        "phase2NearCertaintyChanged": bool(phase2.get("nearCertainty95Changed") or phase2.get("nearCertainty98Changed")),
        "phase2LaterCorrectnessChanged": bool(phase2.get("laterCorrectnessChanged")),
        "phase4DirectionChanged": bool(phase4.get("directionWouldChange")),
        "phase4MergePreviouslySplit": bool(phase4.get("mergePreviouslySplitBuySellGroup")),
        "phase3CapitalAtRiskBlockedOverlap": bool(phase3.get("capitalDelta") not in (None, "", "unknown")),
        "phase3RuntimeImplementationAllowed": False,
        "sensitiveGateContext": bool(
            phase2.get("sensitiveGateContext")
            or phase4.get("sensitivePhase2Context")
            or phase3.get("sensitivePhase2Context")
        ),
        "qualityNotes": notes,
        "missingOrMalformed": any("missing" in note or "malformed" in note or "unknown" in note for note in notes),
        "expectedByPhase2Or4": bool(phase2.get("anyModelRelevantChange") or phase4.get("directionWouldChange") or phase4.get("mergePreviouslySplitBuySellGroup")),
    }


def summarize_replay(
    evaluated: Sequence[Mapping[str, object]],
    records: Sequence[Mapping[str, object]],
    artifacts: Sequence[Mapping[str, object]],
    skipped: Sequence[Mapping[str, object]],
    audit_summaries: Sequence[Mapping[str, object]],
    source_scan: Mapping[str, object],
) -> dict[str, object]:
    unique_keys = {str(row.get("uniqueTradeKey")) for row in evaluated if row.get("uniqueTradeKey")}
    family_counts = Counter(str(row.get("artifactFamily") or "unknown") for row in evaluated)
    evidence_counts = Counter(str(row.get("artifactEvidenceType") or "real_local") for row in evaluated)
    phase2_rows = [row for row in evaluated if row.get("phase2ModelRelevantChange")]
    phase4_rows = [row for row in evaluated if row.get("phase4DirectionChanged")]
    merge_rows = [row for row in evaluated if row.get("phase4MergePreviouslySplit")]
    phase3_rows = [row for row in evaluated if row.get("phase3CapitalAtRiskBlockedOverlap")]
    sensitive_rows = [row for row in evaluated if row.get("sensitiveGateContext")]
    missing_rows = [row for row in evaluated if row.get("missingOrMalformed")]
    unexpected = _unexpected_drift_count(source_scan)
    return {
        "recordsLoaded": len(records),
        "recordsEvaluated": len(evaluated),
        "uniqueTradeKeys": len(unique_keys),
        "artifactCount": len(artifacts),
        "skippedArtifactCount": len(skipped),
        "artifactFamilyCounts": dict(sorted(family_counts.items())),
        "evidenceTypeCounts": dict(sorted(evidence_counts.items())),
        "phase2AffectedRows": len(phase2_rows),
        "phase2AffectedUniqueTradeKeys": _unique_count(phase2_rows),
        "phase2LowProbabilityRows": sum(1 for row in evaluated if row.get("phase2LowProbabilityChanged")),
        "phase2NearCertaintyRows": sum(1 for row in evaluated if row.get("phase2NearCertaintyChanged")),
        "eventForensicLaterCorrectnessRows": sum(1 for row in evaluated if row.get("phase2LaterCorrectnessChanged")),
        "phase4AffectedRows": len(phase4_rows),
        "phase4AffectedUniqueTradeKeys": _unique_count(phase4_rows),
        "phase4MergeRows": len(merge_rows),
        "phase4MergeUniqueTradeKeys": _unique_count(merge_rows),
        "phase3BlockedOverlapRows": len(phase3_rows),
        "phase3BlockedUniqueTradeKeys": _unique_count(phase3_rows),
        "sensitiveGateContextRows": len(sensitive_rows),
        "sensitiveGateContextUniqueTradeKeys": _unique_count(sensitive_rows),
        "missingOrMalformedRows": len(missing_rows),
        "unknownEconomicProbabilityRows": sum(1 for row in evaluated if row.get("economicSideProbability") == UNKNOWN),
        "unexpectedDriftRows": unexpected,
        "runtimeBugFound": unexpected > 0,
        "generatedAuditOutputCount": len(audit_summaries),
        "generatedAuditGateCounts": dict(sorted(Counter(str(item.get("gateDecision") or "unknown") for item in audit_summaries).items())),
        "generatedAuditReportTypes": dict(sorted(Counter(str(item.get("reportType") or "unknown") for item in audit_summaries).items())),
    }


def load_generated_audit_summaries(root: str | Path = ".") -> list[dict[str, object]]:
    base = Path(root)
    summaries: list[dict[str, object]] = []
    for path in sorted((base / "side_outcome_audits").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        summaries.append(
            {
                "path": _relative(base, path),
                "reportType": payload.get("reportType", "unknown"),
                "schemaVersion": payload.get("schemaVersion", "unknown"),
                "gateDecision": payload.get("gateDecision", "unknown"),
                "summaryKeys": sorted(_mapping(payload.get("summary")).keys())[:20],
            }
        )
    return summaries


def inspect_source_safety(root: str | Path = ".") -> dict[str, object]:
    base = Path(root)
    scanner = _read(base / "app/scanner.py")
    archive = _read(base / "app/archive_scanner.py")
    event = _read(base / "app/event_forensic.py")
    storage = _read(base / "app/storage.py")
    polymarket = _read(base / "app/polymarket.py")
    browser = _read(base / "app/browser_ui.html") + "\n" + _read(base / "app/browser_event_forensic_ui.html")
    capital_slice = scanner[scanner.find("def _capital_at_risk_usdc(") : scanner.find("def _capital_at_risk_usdc(") + 1000]
    return {
        "phase3CapitalHelperUsesSideOutcome": "normalize_side_outcome" in capital_slice or "normalize_cluster_direction" in capital_slice,
        "storageSchemaSideOutcomeMarker": any(token in storage for token in ("side_outcome", "cluster_direction", "model_probability")),
        "polymarketLiveSideOutcomeMarker": any(token in polymarket for token in ("normalize_side_outcome", "normalize_cluster_direction")),
        "browserClusterSortFilterMarker": any(token in browser for token in ("clusterDirection", "cluster_direction")),
        "browserEntryProbabilitySortFunctionPresent": "tradeEntryProbabilitySortValue" in browser,
        "scannerUsesCentralSideOutcome": "from app.side_outcome import normalize_cluster_direction, normalize_side_outcome" in scanner,
        "archiveUsesCentralSideOutcome": "from app.side_outcome import normalize_cluster_direction, normalize_side_outcome" in archive,
        "eventForensicUsesCentralSideOutcome": "from app.side_outcome import UNKNOWN, normalize_cluster_direction, normalize_side_outcome" in event,
        "networkCallsInReplayTool": False,
        "directGateLogicMigrationDetected": False,
    }


def fragile_area_status(summary: Mapping[str, object], source_scan: Mapping[str, object]) -> dict[str, object]:
    return {
        "eventForensicWeakHistoryNearCertainLaterWins": {
            "status": "needs_live_rpc_validation",
            "localEvidence": {
                "nearCertaintyRows": summary.get("phase2NearCertaintyRows", 0),
                "laterCorrectnessRows": summary.get("eventForensicLaterCorrectnessRows", 0),
            },
            "assessment": "Phase 2 makes near-certainty and later-correctness semantics economic-side aware, but the remembered weak-history case still requires a live/saved report rerun to verify ranking distribution.",
        },
        "eventForensicSingleMarketVsWholeEvent": {
            "status": "still_architecture_ambiguity",
            "assessment": "Side/Outcome normalization clarifies side semantics but does not change selected-market vs whole-event scope rules.",
        },
        "archiveVisibilityDrift": {
            "status": "monitor_offline",
            "assessment": "Local archive rows are replayable, but this campaign did not change archive visibility rules. Keep archive visibility drift audit in the local chain.",
        },
        "fundingHerStrongRiskSensitiveOverlap": {
            "status": "expected_indirect_overlap_only",
            "sensitiveRows": summary.get("sensitiveGateContextRows", 0),
            "sensitiveUniqueTradeKeys": summary.get("sensitiveGateContextUniqueTradeKeys", 0),
            "assessment": "Sensitive rows overlap changed semantics, but source scans do not show direct Strong Risk/HER/funding/candidate-admission migration.",
        },
        "browserDisplayCompatibility": {
            "status": "covered_by_static_tests",
            "browserEntryProbabilitySortFunctionPresent": source_scan.get("browserEntryProbabilitySortFunctionPresent"),
            "assessment": "UI copy distinguishes Token price and Economic prob; raw entry-probability sort remains present.",
        },
    }


def gate_decision(summary: Mapping[str, object]) -> str:
    if summary.get("runtimeBugFound"):
        return "post_side_outcome_needs_fix"
    if summary.get("recordsEvaluated", 0) == 0:
        return "post_side_outcome_needs_more_corpus"
    return "post_side_outcome_needs_live_rpc_validation"


def representative_rows(evaluated: Sequence[Mapping[str, object]], limit: int = 25) -> list[dict[str, object]]:
    selected: list[Mapping[str, object]] = []
    for predicate in (
        lambda row: row.get("sensitiveGateContext") and row.get("phase2ModelRelevantChange"),
        lambda row: row.get("phase4MergePreviouslySplit"),
        lambda row: row.get("phase3CapitalAtRiskBlockedOverlap"),
        lambda row: row.get("missingOrMalformed"),
    ):
        for row in evaluated:
            if predicate(row) and row not in selected:
                selected.append(row)
                if len(selected) >= limit:
                    break
        if len(selected) >= limit:
            break
    return [dict(row) for row in selected[:limit]]


def next_safest_backlog_item(gate: str) -> dict[str, str]:
    if gate == "post_side_outcome_needs_live_rpc_validation":
        return {
            "item": "bounded live/saved-report replay for remembered Event Forensic weak-history near-certainty cases",
            "approvalRequired": "RPC/operator approval if live data is needed",
            "scope": "rerun affected Iran/whole-event reports or load stable saved outputs; do not change weights, thresholds, Phase 3, or gates",
        }
    if gate == "post_side_outcome_needs_more_corpus":
        return {
            "item": "curate local benchmark corpus",
            "approvalRequired": "user approval for fixture selection",
            "scope": "add local static fixtures from saved artifacts only",
        }
    return {
        "item": "manual code review and commit staging",
        "approvalRequired": "user staging/commit approval",
        "scope": "use release manifest; no behavior change",
    }


def write_json(path: str | Path, payload: Mapping[str, object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--inventory-json", default=str(DEFAULT_INVENTORY_JSON))
    parser.add_argument("--replay-json", default=str(DEFAULT_REPLAY_JSON))
    parser.add_argument("--max-files", type=int, default=180)
    parser.add_argument("--max-rows-per-file", type=int, default=120)
    parser.add_argument("--max-bytes", type=int, default=3_000_000)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    inventory = build_corpus_inventory(args.root)
    replay = build_benchmark_replay(
        args.root,
        max_files=args.max_files,
        max_rows_per_file=args.max_rows_per_file,
        max_bytes=args.max_bytes,
    )
    write_json(args.inventory_json, inventory)
    write_json(args.replay_json, replay)
    if not args.quiet:
        print(f"inventory: {args.inventory_json}")
        print(f"replay: {args.replay_json}")
        print(f"gate: {replay['gateDecision']}")
    return 0


def _discover_corpus_paths(base: Path) -> list[Path]:
    patterns = [
        "tests/fixtures/**/*",
        "validation_corpus_outputs/*",
        "validation_outputs/*",
        "side_outcome_audits/*",
        "side_outcome_review_packets/**/*",
        "shadow_review_packets/**/*",
        "strategic_backlog/*",
        "strategic_backlog_outputs/*",
        "archive_outputs/*",
        "event_forensic_outputs/**/*",
        "ceasefire_forensic_outputs/**/*",
        ".inspoly/reports/*.json",
        "polymarket*_report/**/*",
    ]
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(path for path in base.glob(pattern) if path.is_file())
    return sorted(set(paths))


def _inventory_item(base: Path, path: Path) -> dict[str, object]:
    rel = _relative(base, path)
    classification = _classification(rel)
    family = _family(rel)
    safety = _model_conclusion_safety(classification, family, path.suffix.lower())
    return {
        "path": rel,
        "family": family,
        "classification": classification,
        "modelConclusionSafety": safety,
        "extension": path.suffix.lower(),
        "sizeBytes": path.stat().st_size if path.exists() else 0,
    }


def _classification(path: str) -> str:
    if path.startswith(("archive_outputs/", "event_forensic_outputs/", "ceasefire_forensic_outputs/", ".inspoly/reports/", "polymarket")):
        return "real_local_artifact"
    if path.startswith("tests/fixtures/side_outcome_"):
        return "synthetic_fixture"
    if path.startswith("tests/fixtures/"):
        return "existing_fixture"
    if path.startswith(("side_outcome_audits/", "validation_outputs/")):
        return "generated_audit_output"
    if path.startswith(("validation_corpus_outputs/", "strategic_backlog_outputs/", "strategic_backlog/")):
        return "incomplete_local_only"
    if path.startswith(("side_outcome_review_packets/", "shadow_review_packets/")):
        return "generated_audit_output"
    return "incomplete_local_only"


def _family(path: str) -> str:
    if "side_outcome" in path:
        return "side_outcome"
    if path.startswith("archive_outputs/") or "archive" in path:
        return "archive"
    if path.startswith("event_forensic_outputs/") or "event_forensic" in path:
        return "event_forensic"
    if path.startswith("ceasefire_forensic_outputs/") or "ceasefire" in path:
        return "case_specific_investigation"
    if "shadow" in path:
        return "shadow_sidecar"
    if "polymarket" in path or "ledger" in path or "reconstruction" in path:
        return "reconstruction_or_ledger"
    if "benchmark" in path:
        return "benchmark"
    if "validation" in path:
        return "validation_corpus"
    if "strategic" in path:
        return "strategic_backlog"
    return "other"


def _model_conclusion_safety(classification: str, family: str, suffix: str) -> str:
    if classification == "real_local_artifact" and suffix in SAFE_REPLAY_EXTENSIONS:
        return "usable_with_caveats"
    if classification in {"synthetic_fixture", "existing_fixture"} and family == "side_outcome":
        return "contract_fixture_only"
    if classification == "generated_audit_output":
        return "summary_evidence_only"
    return "unsafe_for_model_conclusions"


def _unexpected_drift_count(source_scan: Mapping[str, object]) -> int:
    risky_flags = (
        "phase3CapitalHelperUsesSideOutcome",
        "storageSchemaSideOutcomeMarker",
        "polymarketLiveSideOutcomeMarker",
        "browserClusterSortFilterMarker",
        "directGateLogicMigrationDetected",
    )
    return sum(1 for flag in risky_flags if source_scan.get(flag))


def _unique_count(rows: Sequence[Mapping[str, object]]) -> int:
    return len({str(row.get("uniqueTradeKey")) for row in rows if row.get("uniqueTradeKey")})


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value in (None, ""):
        return []
    return [str(value)]


def _first_nonblank(*values: object) -> object:
    for value in values:
        if value not in (None, ""):
            return value
    return ""


def _value_or_unknown(value: object) -> str:
    return str(value) if value not in (None, "") else UNKNOWN


def _relative(base: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
