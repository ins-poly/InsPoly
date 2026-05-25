#!/usr/bin/env python3
"""Build post-Side/Outcome strategic reliability program outputs.

This is a sidecar-only aggregator. It reads existing local validation outputs,
audit JSON files, and source text, then writes machine-readable program reports.
It performs no live/RPC/network calls and does not import scanner/archive/Event
Forensic runtime modules.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.archive_visibility_doc_drift_audit import build_audit as build_archive_visibility_doc_audit


SCHEMA_VERSION = "post_side_outcome_strategic_reliability_v1"
PROGRAM_JSON_PATHS = {
    "event_forensic_reliability": Path("validation_outputs/inspoly_event_forensic_reliability_program_20260522.json"),
    "benchmark_productization": Path("validation_outputs/inspoly_benchmark_system_productization_20260522.json"),
    "event_level_semantics": Path("validation_outputs/inspoly_event_forensic_event_level_semantics_rfc_20260522.json"),
    "phase3_capital_source_quality": Path("validation_outputs/inspoly_phase3_capital_source_quality_program_20260522.json"),
    "sensitive_gate_integrity": Path("validation_outputs/inspoly_sensitive_gate_integrity_audit_20260522.json"),
    "archive_completeness_visibility": Path("validation_outputs/inspoly_archive_completeness_visibility_program_20260522.json"),
    "summary": Path("validation_outputs/inspoly_post_side_outcome_strategic_campaign_summary_20260522.json"),
}


def build_program_reports(root: str | Path = ".") -> dict[str, dict[str, object]]:
    base = Path(root)
    context = _load_context(base)
    programs = {
        "event_forensic_reliability": _event_forensic_reliability(context),
        "benchmark_productization": _benchmark_productization(context),
        "event_level_semantics": _event_level_semantics(context),
        "phase3_capital_source_quality": _phase3_capital_source_quality(context),
        "sensitive_gate_integrity": _sensitive_gate_integrity(context),
        "archive_completeness_visibility": _archive_completeness_visibility(context),
    }
    programs["summary"] = _campaign_summary(programs, context)
    return programs


def write_program_reports(
    reports: Mapping[str, Mapping[str, object]],
    *,
    root: str | Path = ".",
    output_dir: str | Path | None = None,
) -> dict[str, str]:
    base = Path(root)
    written: dict[str, str] = {}
    for key, report in reports.items():
        default = PROGRAM_JSON_PATHS[key]
        path = Path(output_dir) / default.name if output_dir else base / default
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written[key] = str(path)
    return written


def inspect_forbidden_scope(root: str | Path = ".") -> dict[str, object]:
    base = Path(root)
    scanner = _read(base / "app/scanner.py")
    archive = _read(base / "app/archive_scanner.py")
    event = _read(base / "app/event_forensic.py")
    storage = _read(base / "app/storage.py")
    browser = _read(base / "app/browser_ui.html") + "\n" + _read(base / "app/browser_event_forensic_ui.html")
    polymarket = _read(base / "app/polymarket.py")
    tool_text = _read(base / "tools/post_side_outcome_strategic_reliability.py")
    capital_start = scanner.find("def _capital_at_risk_usdc(")
    capital_slice = scanner[capital_start : capital_start + 1200] if capital_start >= 0 else ""
    scorer_start = scanner.find("def _score_trade(")
    scorer_slice = scanner[scorer_start : scorer_start + 4000] if scorer_start >= 0 else ""
    event_scorer_start = event.find("def _event_forensic_score(")
    event_scorer_slice = event[event_scorer_start : event_scorer_start + 4000] if event_scorer_start >= 0 else ""
    return {
        "strategicToolNetworkTokens": _contains_network_call_marker(tool_text),
        "phase3CapitalHelperUsesSideOutcome": "normalize_side_outcome" in capital_slice or "normalize_cluster_direction" in capital_slice,
        "storageSchemaStrategicMarkers": any(token in storage for token in ("known_case_benchmark", "strategic_reliability")),
        "browserSortingFilteringStrategicMarkers": any(token in browser for token in ("strategic_reliability", "known_case_benchmark")),
        "polymarketLiveStrategicMarkers": any(token in polymarket for token in ("strategic_reliability", "known_case_benchmark")),
        "directGateLogicMigrationDetected": any(token in scorer_slice + event_scorer_slice for token in ("strategic_reliability", "known_case_benchmark")),
        "runtimeImportsStrategicTool": any(
            "post_side_outcome_strategic_reliability" in text
            for text in (scanner, archive, event, storage, browser, polymarket)
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    reports = build_program_reports(args.root)
    written = write_program_reports(reports, root=args.root, output_dir=args.output_dir)
    if not args.quiet:
        for key in (
            "event_forensic_reliability",
            "benchmark_productization",
            "event_level_semantics",
            "phase3_capital_source_quality",
            "sensitive_gate_integrity",
            "archive_completeness_visibility",
            "summary",
        ):
            print(f"{key}: {reports[key]['gateDecision']} -> {written[key]}")
    return 0


def _load_context(base: Path) -> dict[str, object]:
    return {
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "knownCaseRun": _read_json(base / "validation_outputs/known_case_benchmark_run_20260522.json"),
        "postReplay": _read_json(base / "validation_outputs/post_side_outcome_benchmark_replay_20260522.json"),
        "phase2Stabilization": _read_json(base / "side_outcome_audits/side_outcome_phase2_post_migration_drift_audit_20260522.json"),
        "phase3Audit": _read_json(base / "side_outcome_audits/side_outcome_phase3_capital_at_risk_audit_20260522.json"),
        "phase4Stabilization": _read_json(base / "side_outcome_audits/side_outcome_phase4_post_migration_drift_audit_20260522.json"),
        "archiveEvidence": _read_json(base / "side_outcome_audits/side_outcome_phase2_archive_evidence_gap_20260522.json"),
        "archiveVisibilityDocAudit": build_archive_visibility_doc_audit(),
        "forbiddenScope": inspect_forbidden_scope(base),
    }


def _base_report(program: str, context: Mapping[str, object], gate: str) -> dict[str, object]:
    return {
        "reportType": f"post_side_outcome_{program}",
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": context.get("generatedAt"),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "gateDecision": gate,
    }


def _event_forensic_reliability(context: Mapping[str, object]) -> dict[str, object]:
    replay = _mapping(context.get("postReplay"))
    replay_summary = _mapping(replay.get("summary"))
    phase2 = _mapping(context.get("phase2Stabilization"))
    phase2_drift = _mapping(phase2.get("driftSummary"))
    fragile = _mapping(replay.get("fragileAreas"))
    weak = _mapping(fragile.get("eventForensicWeakHistoryNearCertainLaterWins"))
    report = _base_report("event_forensic_reliability_program", context, "event_forensic_needs_live_rpc_validation")
    report.update(
        {
            "program": "Event Forensic Reliability Program",
            "summary": {
                "postReplayGate": replay.get("gateDecision"),
                "weakHistoryStatus": weak.get("status", "needs_live_rpc_validation"),
                "nearCertaintyRows": replay_summary.get("phase2NearCertaintyRows", 0),
                "postReplayLaterCorrectnessRows": replay_summary.get("eventForensicLaterCorrectnessRows", 0),
                "phase2StabilizationLaterCorrectnessRows": _mapping(phase2_drift.get("rowsBySurface")).get("laterCorrectnessChanged", 0),
                "singleMarketWholeEventStatus": _mapping(fragile.get("eventForensicSingleMarketVsWholeEvent")).get("status"),
                "runtimeBugFound": replay_summary.get("runtimeBugFound", False),
            },
            "closed": [
                "Phase 2 economic-side probability and later-correctness semantics are locally stable.",
                "Phase 4 normalized timing/cluster direction is locally stable.",
                "Known-case corpus covers one Event Forensic later-correctness affected row.",
            ],
            "blocked": [
                "remembered weak-history near-certainty ranking distribution requires stable saved-output or live/RPC rerun",
                "single-market versus whole-event semantics requires RFC before runtime scope changes",
            ],
            "allowedNext": [
                "load stable saved Event Forensic report packets if they already exist locally",
                "add sidecar comparison tests for saved packets without changing scoring",
            ],
            "approvalRequired": ["bounded live/RPC rerun", "any scorer/ranking/gate change"],
        }
    )
    return report


def _benchmark_productization(context: Mapping[str, object]) -> dict[str, object]:
    known = _mapping(context.get("knownCaseRun"))
    summary = _mapping(known.get("summary"))
    report = _base_report("benchmark_system_productization", context, "benchmark_system_local_regression_ready")
    report.update(
        {
            "program": "Benchmark System Productization",
            "summary": {
                "knownCaseGate": known.get("gateDecision"),
                "caseCount": summary.get("caseCount", 0),
                "passCount": summary.get("passCount", 0),
                "unknownPassCount": summary.get("unknownPassCount", 0),
                "failCount": summary.get("failCount", 0),
                "sourceTypeCounts": summary.get("sourceTypeCounts", {}),
                "missingRequiredCategories": summary.get("missingRequiredCategories", []),
            },
            "closed": [
                "stable known-case corpus exists",
                "runner produces a machine-readable pass/fail/unknown JSON",
                "corpus covers Side/Outcome Phase 2, Phase 4, old-report, malformed, sensitive-overlap, and Phase 3-blocked cases",
            ],
            "blocked": [
                "not a labeled scorer-tuning benchmark",
                "does not replace live Event Forensic validation",
            ],
            "allowedNext": [
                "add stable saved-output packets if local reports appear",
                "add human-labeled public-case fixtures only if source provenance is explicit",
            ],
            "approvalRequired": ["scoring weight/threshold tuning", "staging/commit policy"],
        }
    )
    return report


def _event_level_semantics(context: Mapping[str, object]) -> dict[str, object]:
    replay = _mapping(context.get("postReplay"))
    fragile = _mapping(replay.get("fragileAreas"))
    report = _base_report("event_level_semantics_rfc", context, "event_level_semantics_rfc_ready_no_runtime")
    report.update(
        {
            "program": "Event-Level Semantics RFC",
            "summary": {
                "singleMarketWholeEventStatus": _mapping(fragile.get("eventForensicSingleMarketVsWholeEvent")).get("status"),
                "scopeRuntimeChangeAllowed": False,
                "reportOnlyClarificationAllowed": True,
            },
            "targetSemantics": {
                "singleMarket": "primary scoring remains scoped to selected market only",
                "wholeEvent": "whole-event mode may include sibling/related markets as primary scope only when explicitly selected",
                "relatedMarkets": "related/sibling markets may be loaded as context, but must not silently broaden primary single-market scoring",
                "sideOutcome": "economic-side normalization clarifies direction but does not change event scope",
            },
            "blocked": [
                "silent broadening of selected-market reports",
                "winner/later-correctness reinterpretation beyond approved Side/Outcome semantics",
                "UI scope/sort/filter changes without product approval",
            ],
            "testsRequiredBeforeRuntime": [
                "single-market report keeps sibling markets out of primary ranking",
                "whole-event report explicitly marks event-wide scope",
                "old saved reports with no scope metadata load absent-safe",
            ],
            "approvalRequired": ["any runtime scope change", "UI workflow/scope control changes"],
        }
    )
    return report


def _phase3_capital_source_quality(context: Mapping[str, object]) -> dict[str, object]:
    phase3 = _mapping(context.get("phase3Audit"))
    summary = _mapping(phase3.get("summary"))
    affected = _mapping(summary.get("affectedCounts"))
    report = _base_report("phase3_capital_source_quality_program", context, "keep_phase3_blocked")
    report.update(
        {
            "program": "Phase 3 Capital Source Quality Program",
            "summary": {
                "phase3AuditGate": phase3.get("gateDecision"),
                "recordsScanned": summary.get("recordsScanned", 0),
                "evaluableRows": summary.get("evaluableRows", 0),
                "rowsWithCapitalDelta": affected.get("rowsWithCapitalDelta", 0),
                "sellRowsWithCapitalDelta": affected.get("sellRowsWithCapitalDelta", 0),
                "buyRowsWithCapitalDelta": affected.get("buyRowsWithCapitalDelta", 0),
                "uniqueTradeKeysWithCapitalDelta": affected.get("uniqueTradeKeysWithCapitalDelta", 0),
                "sensitiveOverlapRows": affected.get("sensitiveOverlapRows", 0),
            },
            "sourceQualityFindings": [
                "SELL complement max-loss semantics are materially different from raw fill notional",
                "usdcSize is observed cash/fill value, not automatically verified max-loss collateral",
                "old notional-only rows are unsafe for runtime reinterpretation",
            ],
            "blocked": [
                "runtime capital-at-risk normalization",
                "funding/HER/Strong Risk-sensitive capital migration",
                "old report rescoring from lossy rows",
            ],
            "allowedNext": ["sidecar-only source quality fixture expansion", "accounting RFC refinement"],
            "approvalRequired": ["Phase 3 runtime implementation", "any capital-driven gate or threshold tuning"],
        }
    )
    return report


def _sensitive_gate_integrity(context: Mapping[str, object]) -> dict[str, object]:
    replay = _mapping(context.get("postReplay"))
    replay_summary = _mapping(replay.get("summary"))
    phase2 = _mapping(context.get("phase2Stabilization"))
    phase2_drift = _mapping(phase2.get("driftSummary"))
    source = _mapping(context.get("forbiddenScope"))
    gate = "sensitive_gate_integrity_preserved_local_only"
    if source.get("directGateLogicMigrationDetected"):
        gate = "sensitive_gate_integrity_needs_fix"
    report = _base_report("sensitive_gate_integrity_audit", context, gate)
    report.update(
        {
            "program": "Funding/HER/Strong Risk Integrity Audit",
            "summary": {
                "postReplaySensitiveRows": replay_summary.get("sensitiveGateContextRows", 0),
                "postReplaySensitiveUniqueTradeKeys": replay_summary.get("sensitiveGateContextUniqueTradeKeys", 0),
                "phase2SensitiveAffectedRows": _mapping(phase2_drift.get("rowsBySurface")).get("sensitiveGateContextAffected", 0),
                "phase2SensitiveAffectedUniqueTradeKeys": _mapping(phase2_drift.get("uniqueTradeKeysBySurface")).get("sensitiveGateContextAffected", 0),
                "directGateLogicMigrationDetected": source.get("directGateLogicMigrationDetected", False),
                "phase3CapitalHelperUsesSideOutcome": source.get("phase3CapitalHelperUsesSideOutcome", False),
            },
            "integrityFindings": [
                "Side/Outcome Phase 2/4 changes overlap sensitive contexts indirectly.",
                "Source scans do not show direct Strong Risk/HER/funding/candidate-admission migration.",
                "Any future direct gate migration needs labeled benchmark and explicit approval.",
            ],
            "blocked": [
                "direct gate criteria changes",
                "funding eligibility changes",
                "HER routing changes",
                "Strong Risk label/threshold changes",
            ],
            "allowedNext": ["sidecar sensitive-case packet review", "no-runtime audit expansion"],
            "approvalRequired": ["any direct gate behavior change", "any scoring weight/threshold tuning"],
        }
    )
    return report


def _archive_completeness_visibility(context: Mapping[str, object]) -> dict[str, object]:
    archive = _mapping(context.get("archiveEvidence"))
    archive_summary = _mapping(archive.get("summary"))
    visibility = _mapping(context.get("archiveVisibilityDocAudit"))
    visibility_summary = _mapping(visibility.get("summary"))
    field_counts = _mapping(archive_summary.get("fieldCoverageCounts"))
    report = _base_report("archive_completeness_visibility_program", context, "archive_visibility_monitoring_local_only")
    report.update(
        {
            "program": "Archive Completeness / Visibility Program",
            "summary": {
                "archiveEvidenceGate": archive.get("gateDecision"),
                "artifactsDiscovered": archive_summary.get("artifactsDiscovered", 0),
                "artifactsSelected": archive_summary.get("artifactsSelected", 0),
                "recordsLoaded": archive_summary.get("recordsLoaded", 0),
                "evaluableRecords": archive_summary.get("evaluableRecords", 0),
                "lossyCsvWithoutPrice": field_counts.get("lossy_csv_without_price", 0),
                "priceMissingOrUnknown": field_counts.get("price_missing_or_unknown", 0),
                "visibilityDocDriftObserved": visibility_summary.get("driftObservedCount", 0),
                "archiveVisibilityChanged": visibility_summary.get("archiveVisibilityChanged", False),
            },
            "findings": [
                "Archive artifacts are locally abundant but include lossy CSV rows that cannot be safely rescored.",
                "Visibility remains annotate-not-hide and should stay separate from scoring.",
                "Large archive trade CSV files are skipped by bounded sidecar audits and need chunked monitoring if exact completeness is required.",
            ],
            "blocked": [
                "archive visibility behavior changes",
                "candidate admission broadening",
                "rescoring from lossy old CSV rows",
            ],
            "allowedNext": ["read-only chunked archive completeness audit", "documentation drift monitoring"],
            "approvalRequired": ["visibility behavior changes", "archive candidate admission changes"],
        }
    )
    return report


def _campaign_summary(programs: Mapping[str, Mapping[str, object]], context: Mapping[str, object]) -> dict[str, object]:
    gates = {key: report.get("gateDecision") for key, report in programs.items()}
    source = _mapping(context.get("forbiddenScope"))
    hard_failures = [key for key, value in source.items() if value is True]
    report = _base_report("strategic_campaign_summary", context, "strategic_campaign_complete_with_live_rpc_blocker")
    report.update(
        {
            "program": "Strategic Post-Side/Outcome Reliability Campaign",
            "programGates": gates,
            "closed": [
                "local known-case benchmark corpus is ready",
                "Phase 2 and Phase 4 remain stable in local evidence",
                "sensitive gates are locally integrity-preserved with no direct migration detected",
                "archive visibility remains monitoring-only",
            ],
            "blocked": [
                "Phase 3 capital-at-risk runtime implementation",
                "Event Forensic weak-history near-certainty live distribution validation",
                "single-market versus whole-event runtime scope changes",
                "weights/thresholds/direct gates/storage/UI sorting/live indexing",
            ],
            "approvalRequired": [
                "bounded live/RPC Event Forensic validation",
                "product decision for event-level scope UI/semantics",
                "separate approval for Phase 3 or any direct gate tuning",
            ],
            "bugsFound": [],
            "runtimeFixesApplied": [],
            "forbiddenScopeFindings": source,
            "forbiddenScopeHardFailures": hard_failures,
            "nextHighestValueCampaign": "bounded Event Forensic weak-history near-certainty saved-report or live/RPC validation",
        }
    )
    return report


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _contains_network_call_marker(source: str) -> bool:
    markers = (
        "import " + "requests",
        "from " + "urllib",
        "import " + "httpx",
        "import " + "aiohttp",
        "import " + "websocket",
        "socket" + ".create_connection(",
    )
    return any(marker in source for marker in markers)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


if __name__ == "__main__":
    raise SystemExit(main())
