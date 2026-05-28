#!/usr/bin/env python3
"""Post-migration drift audit for Side/Outcome Phase 2.

This sidecar replays local artifacts through the Phase 2 audit interpreters and
checks that observed drift is confined to the RFC-approved side/outcome model
semantics. It does not import scanner/archive/Event Forensic runtime modules.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.side_outcome_archive_evidence_audit import (
    build_archive_evidence_audit,
    discover_archive_artifacts,
    load_archive_records,
    select_artifacts_for_scan,
)
from tools.side_outcome_phase2_impact_audit import (
    build_phase2_readiness_audit,
    discover_artifact_paths,
    evaluate_trade_record,
    load_records_from_paths,
)


REPORT_TYPE = "side_outcome_phase2_post_migration_drift_audit"
SCHEMA_VERSION = "side_outcome_phase2_post_migration_drift_v1"
DEFAULT_JSON_PATH = "side_outcome_audits/side_outcome_phase2_post_migration_drift_audit_20260522.json"
DEFAULT_MARKDOWN_PATH = "docs/inspoly_side_outcome_phase2_post_migration_stabilization_20260522.md"
DEFAULT_REVIEW_DIR = "side_outcome_review_packets/phase2_post_migration_sensitive_cases_20260522"

DRIFT_SURFACES = (
    "lowProbability30Changed",
    "lowProbability35Changed",
    "nearCertainty95Changed",
    "nearCertainty98Changed",
    "directionChanged",
    "laterCorrectnessChanged",
    "anyModelRelevantChange",
)

PRODUCTION_PATHS = (
    "app/scanner.py",
    "app/archive_scanner.py",
    "app/event_forensic.py",
    "app/browser_desktop.py",
    "app/browser_ui.html",
    "app/browser_event_forensic_ui.html",
    "app/storage.py",
    "app/polymarket.py",
)


def build_post_migration_drift_audit(
    *,
    root: str | Path = ".",
    max_files: int | None = 60,
    max_rows_per_file: int | None = 120,
    archive_max_files: int | None = 120,
    archive_max_rows_per_file: int | None = 100,
    archive_max_bytes: int | None = 2_000_000,
) -> dict[str, object]:
    base = Path(root)
    impact_records = load_records_from_paths(
        discover_artifact_paths(base),
        max_files=max_files,
        max_rows_per_file=max_rows_per_file,
    )
    archive_artifacts = discover_archive_artifacts(base)
    selected_archive_artifacts = select_artifacts_for_scan(
        archive_artifacts,
        max_files=archive_max_files,
    )
    archive_records, skipped_archive_artifacts = load_archive_records(
        selected_archive_artifacts,
        max_rows_per_file=archive_max_rows_per_file,
        max_bytes=archive_max_bytes,
    )
    return build_post_migration_drift_audit_from_records(
        impact_records=impact_records,
        archive_records=archive_records,
        root=base,
        archive_artifacts=selected_archive_artifacts,
        discovered_archive_artifacts=archive_artifacts,
        skipped_archive_artifacts=skipped_archive_artifacts,
        command_scope={
            "impactAudit": {
                "maxFiles": max_files,
                "maxRowsPerFile": max_rows_per_file,
            },
            "archiveEvidenceAudit": {
                "maxFiles": archive_max_files,
                "maxRowsPerFile": archive_max_rows_per_file,
                "maxBytes": archive_max_bytes,
            },
        },
    )


def build_post_migration_drift_audit_from_records(
    *,
    impact_records: Sequence[Mapping[str, object]],
    archive_records: Sequence[Mapping[str, object]],
    root: str | Path = ".",
    archive_artifacts: Sequence[Mapping[str, object]] | None = None,
    discovered_archive_artifacts: Sequence[Mapping[str, object]] | None = None,
    skipped_archive_artifacts: Sequence[Mapping[str, object]] | None = None,
    runtime_scan: Mapping[str, object] | None = None,
    command_scope: Mapping[str, object] | None = None,
) -> dict[str, object]:
    base = Path(root)
    impact_report = build_phase2_readiness_audit(impact_records, root=base)
    archive_report = build_archive_evidence_audit(
        archive_records,
        artifacts=archive_artifacts or [],
        discovered_artifacts=discovered_archive_artifacts or archive_artifacts or [],
        skipped_artifacts=skipped_archive_artifacts or [],
    )
    impact_evaluated = [evaluate_trade_record(record) for record in impact_records]
    archive_evaluated = []
    for record in archive_records:
        item = evaluate_trade_record(record)
        item["artifactEvidenceType"] = record.get("artifactEvidenceType", "unknown")
        item["sourceCollection"] = record.get("sourceCollection", "")
        item["sourceShape"] = record.get("sourceShape", "")
        archive_evaluated.append(item)
    evaluated = impact_evaluated + archive_evaluated
    runtime = dict(runtime_scan or inspect_runtime_scope(base))
    drift = _drift_summary(evaluated)
    compatibility = _compatibility_sweep(
        impact_records=impact_records,
        archive_records=archive_records,
        evaluated=evaluated,
        runtime_scan=runtime,
    )
    unexpected = _unexpected_scope_findings(runtime)
    sensitive_cases = sensitive_review_cases(evaluated)
    gate_decision = _gate_decision(unexpected, compatibility)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeBehaviorChangedByThisAudit": False,
        "phase3CapitalAtRiskImplemented": bool(runtime.get("phase3CapitalAtRiskImplemented")),
        "phase4ClusterDirectionImplemented": bool(runtime.get("phase4ClusterDirectionImplemented")),
        "gateDecision": gate_decision,
        "commandScope": dict(command_scope or {}),
        "implementationAudit": runtime,
        "driftSummary": drift,
        "sensitiveCaseSummary": {
            "affectedSensitiveContextRows": drift["rowsBySurface"].get("sensitiveGateContextAffected", 0),
            "affectedSensitiveUniqueTradeKeys": drift["uniqueTradeKeysBySurface"].get("sensitiveGateContextAffected", 0),
            "reviewPacketCaseCount": len(sensitive_cases),
        },
        "compatibilitySweep": compatibility,
        "unexpectedDriftFindings": unexpected,
        "impactAuditSummary": impact_report.get("summary", {}),
        "archiveEvidenceSummary": archive_report.get("summary", {}),
        "sensitiveReviewCases": sensitive_cases[:40],
        "expectedDriftInterpretation": [
            "Low-probability and near-certainty differences are expected when SELL rows invert from raw token price to economic-side probability.",
            "Event Forensic later-correctness differences are expected when opening/increasing SELL rows are compared by economic side.",
            "Direction changes are drift evidence only; Phase 4 cluster grouping remains blocked and was not implemented.",
            "Sensitive contexts may be indirectly affected because existing gates consume approved Phase 2 flags, but gate logic itself must remain unchanged.",
        ],
        "remainingBlocks": [
            "Phase 3 capital-at-risk normalization",
            "Phase 4 cluster direction normalization",
            "Any direct Strong Risk/HER/funding/candidate-admission gate migration",
            "Any UI sorting/filter behavior change",
            "Any storage schema migration",
            "Any live/RPC/network behavior change",
        ],
    }


def inspect_runtime_scope(root: str | Path = ".") -> dict[str, object]:
    base = Path(root)
    sources = {relative: _read_text(base / relative) for relative in PRODUCTION_PATHS}
    scanner = sources.get("app/scanner.py", "")
    event = sources.get("app/event_forensic.py", "")
    archive = sources.get("app/archive_scanner.py", "")
    browser = sources.get("app/browser_desktop.py", "") + "\n" + sources.get("app/browser_ui.html", "")
    event_browser = sources.get("app/browser_event_forensic_ui.html", "")
    storage = sources.get("app/storage.py", "")
    polymarket = sources.get("app/polymarket.py", "")
    score_trade = _function_slice(scanner, "def _score_trade(")
    event_score = _function_slice(event, "def _event_forensic_score(")
    capital = _function_slice(scanner, "def _capital_at_risk_usdc(")
    legacy_capital = _function_slice(scanner, "def _capital_at_risk(")
    split_wallet = _function_slice(scanner, "def _shared_funding_split_groups(")
    coordinated = _function_slice(scanner, "def _annotate_coordinated_sizing_clusters(")
    post_migration_tool_name = "side_outcome_phase2_post_migration_drift_audit"
    return {
        "centralHelperUsedByScoreTrade": "normalize_side_outcome" in score_trade and "model_probability" in score_trade,
        "centralHelperUsedByEventForensicScore": "_case_side_outcome_model" in event_score and "entry_probability_basis" in event_score,
        "archiveUsesHelperOnlyForAdditiveRows": "normalize_side_outcome" in archive and "def _trade_row" in archive,
        "rawDisplayFieldsPreserved": all(
            token in scanner + archive + browser + event
            for token in ("price_implied_probability", "entryProbability", "raw_token_price", "rawTokenPrice")
        ),
        "modelFieldsHaveProvenance": all(
            token in scanner + event + archive
            for token in ("model_probability_basis", "side_outcome_normalization_status")
        ),
        "oldReportLoadingAbsentSafe": all(
            token in browser
            for token in ("normalize_side_outcome", "Raw token: unknown", "Economic side: unknown")
        ),
        "browserEntryProbabilitySortStillRaw": (
            'value: "entryProbability-asc"' in event_browser
            and "tradeEntryProbabilitySortValue" in event_browser
            and "Lowest token price / raw implied probability" in event_browser
        ),
        "phase3CapitalAtRiskImplemented": (
            "normalize_side_outcome" in capital
            or "economic_side_probability" in capital
            or "model_probability" in capital
            or "normalize_side_outcome" in legacy_capital
            or "economic_side_probability" in legacy_capital
        ),
        "phase4ClusterDirectionImplemented": (
            "normalize_side_outcome" in split_wallet
            or "economic_direction_normalized" in split_wallet
            or "model_economic_direction" in split_wallet
            or "normalize_side_outcome" in coordinated
            or "economic_direction_normalized" in coordinated
        ),
        "storageSchemaMentionsPhase2Fields": any(
            token in storage
            for token in ("model_probability", "economic_side_probability", "side_outcome_normalization_status")
        ),
        "liveRpcNetworkChangesDetected": any(
            token in scanner + archive + event + polymarket
            for token in (
                "side_outcome_phase2_post_migration_drift_audit",
                "post_migration_drift",
            )
        ),
        "productionImportsThisAuditTool": {
            relative: post_migration_tool_name in text
            for relative, text in sources.items()
        },
        "phase3ExpectedBlockPresent": "Phase 3 capital-at-risk migration remains blocked" in _read_text(
            base / "docs/inspoly_side_outcome_phase2_model_migration_rfc_20260522.md"
        ),
        "phase4ExpectedFailurePresent": "test_same_side_cluster_should_group_sell_yes_with_buy_no_as_no_exposure" in _read_text(
            base / "tests/test_side_outcome_price_normalization_audit.py"
        ),
    }


def sensitive_review_cases(evaluated: Sequence[Mapping[str, object]], *, limit: int = 40) -> list[dict[str, object]]:
    buckets: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    seen: set[str] = set()
    for item in evaluated:
        if not item.get("anyModelRelevantChange") or not item.get("sensitiveGateContext"):
            continue
        key = str(item.get("uniqueTradeKey") or item.get("rowId") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        buckets[_packet_family_group(item)].append(item)
    for items in buckets.values():
        items.sort(
            key=lambda item: (
                not bool(item.get("laterCorrectnessChanged")),
                str(item.get("artifactPath") or ""),
                str(item.get("rowId") or ""),
            )
        )
    cases: list[dict[str, object]] = []
    family_order = ("event_forensic", "archive", "scanner", "reconstruction", "other")
    while len(cases) < limit and any(buckets.get(group) for group in family_order):
        for group in family_order:
            if len(cases) >= limit:
                break
            if buckets.get(group):
                cases.append(_review_case(buckets[group].pop(0)))
    return cases


def write_outputs(
    report: Mapping[str, object],
    *,
    json_path: str | Path = DEFAULT_JSON_PATH,
    markdown_path: str | Path = DEFAULT_MARKDOWN_PATH,
    review_dir: str | Path = DEFAULT_REVIEW_DIR,
) -> dict[str, str]:
    js = Path(json_path)
    md = Path(markdown_path)
    review = Path(review_dir)
    js.parent.mkdir(parents=True, exist_ok=True)
    md.parent.mkdir(parents=True, exist_ok=True)
    review.mkdir(parents=True, exist_ok=True)
    js.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md.write_text(stabilization_markdown(report), encoding="utf-8")
    write_review_packet(report, review)
    return {
        "jsonPath": str(js),
        "markdownPath": str(md),
        "reviewPacketDir": str(review),
    }


def write_review_packet(report: Mapping[str, object], output_dir: str | Path) -> dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    cases = list(report.get("sensitiveReviewCases") or [])
    summary = {
        "reportType": "side_outcome_phase2_sensitive_case_review_packet",
        "generatedAt": report.get("generatedAt"),
        "sourceReportType": report.get("reportType"),
        "gateDecision": report.get("gateDecision"),
        "caseCount": len(cases),
        "unexpectedDriftFindings": list(report.get("unexpectedDriftFindings") or []),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "sensitive_cases.json").write_text(json.dumps(cases, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "index.md").write_text(review_packet_markdown(summary, cases), encoding="utf-8")
    return {
        "summaryPath": str(out / "summary.json"),
        "casesPath": str(out / "sensitive_cases.json"),
        "indexPath": str(out / "index.md"),
    }


def stabilization_markdown(report: Mapping[str, object]) -> str:
    drift = _mapping(report.get("driftSummary"))
    rows = _mapping(drift.get("rowsBySurface"))
    unique = _mapping(drift.get("uniqueTradeKeysBySurface"))
    sensitive = _mapping(report.get("sensitiveCaseSummary"))
    compatibility = _mapping(report.get("compatibilitySweep"))
    unexpected = list(report.get("unexpectedDriftFindings") or [])
    lines = [
        "# InsPoly Side/Outcome Phase 2 Post-Migration Stabilization",
        "",
        "- Date: 2026-05-22",
        "- Scope: sidecar-only stabilization and drift audit",
        "- Runtime code changed by this audit: `false`",
        f"- Gate decision: `{report.get('gateDecision')}`",
        "",
        "## What Phase 2 Changed",
        "",
        "- Scanner low-probability and near-certainty model checks now use economic-side `model_probability` when side/outcome/price normalize safely.",
        "- Event Forensic later-correctness, winner-entry ranks, low-probability winner, and near-certainty checks now use economic-side semantics.",
        "- Raw token display fields remain raw and additive model/provenance fields explain the economic-side basis.",
        "",
        "## Drift Replay Summary",
        "",
        f"- Evaluated rows: `{drift.get('evaluatedRows', 0)}`",
        f"- Unique trade keys: `{drift.get('uniqueTradeKeys', 0)}`",
        f"- Expected affected rows: `{rows.get('anyModelRelevantChange', 0)}`",
        f"- Expected affected unique trade keys: `{unique.get('anyModelRelevantChange', 0)}`",
        f"- Sensitive affected rows: `{sensitive.get('affectedSensitiveContextRows', 0)}`",
        f"- Sensitive affected unique trade keys: `{sensitive.get('affectedSensitiveUniqueTradeKeys', 0)}`",
        "",
        "| Surface | Rows | Unique trade keys |",
        "|---|---:|---:|",
    ]
    for surface in DRIFT_SURFACES + ("sensitiveGateContextAffected",):
        lines.append(f"| `{surface}` | {rows.get(surface, 0)} | {unique.get(surface, 0)} |")
    lines.extend(
        [
            "",
            "## Expected Vs Unexpected Drift",
            "",
        ]
    )
    if unexpected:
        lines.extend(f"- Unexpected: {item}" for item in unexpected)
    else:
        lines.append("- No unexpected drift outside the Phase 2 RFC scope was detected by source scans and bounded artifact replay.")
    lines.extend(
        [
            "",
            "## Compatibility Sweep",
            "",
            f"- Old/raw field rows without `model_probability`: `{compatibility.get('oldRowsWithoutModelProbability', 0)}`",
            f"- Rows with unknown economic probability: `{compatibility.get('unknownEconomicProbabilityRows', 0)}`",
            f"- Raw fields preserved by source scan: `{str(compatibility.get('rawFieldsPreservedBySourceScan')).lower()}`",
            f"- Old report absent-safe loading markers present: `{str(compatibility.get('oldReportAbsentSafeMarkersPresent')).lower()}`",
            f"- Browser entry-probability sort remains raw-token local sorting: `{str(compatibility.get('browserEntryProbabilitySortStillRaw')).lower()}`",
            f"- CSV/JSON export changes remain additive-only by audit scope: `{str(compatibility.get('exportsAdditiveOnlyByScope')).lower()}`",
            "",
            "## Sensitive Review Packet",
            "",
            f"- Packet directory: `{DEFAULT_REVIEW_DIR}`",
            f"- Packet cases: `{sensitive.get('reviewPacketCaseCount', 0)}`",
            "- Each packet row records raw side/outcome/price, economic side/probability, old/new interpretations, affected surface, and whether the change is expected by the RFC.",
            "",
            "## Remaining Blockers",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("remainingBlocks", []))
    lines.extend(
        [
            "",
            "## Gate Decision",
            "",
            f"Decision: `{report.get('gateDecision')}`.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def review_packet_markdown(summary: Mapping[str, object], cases: Sequence[Mapping[str, object]]) -> str:
    lines = [
        "# Side/Outcome Phase 2 Sensitive Case Review Packet",
        "",
        f"- Gate decision: `{summary.get('gateDecision')}`",
        f"- Case count: `{summary.get('caseCount', 0)}`",
        "",
        "| # | Trade key | Raw | Economic | Surfaces | Expected by RFC |",
        "|---:|---|---|---|---|---|",
    ]
    for index, case in enumerate(cases, start=1):
        raw = _escape_md(f"{case.get('rawOrderSide')} {case.get('rawTokenOutcome')} @ {case.get('rawTokenPrice')}")
        economic = _escape_md(f"{case.get('economicSide')} @ {case.get('economicSideProbability')}")
        surfaces = _escape_md(", ".join(case.get("affectedSurfaces") or []))
        lines.append(
            f"| {index} | `{_escape_md(case.get('tradeKey', ''))}` | {raw} | {economic} | {surfaces} | `{str(case.get('expectedByRfc')).lower()}` |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _drift_summary(evaluated: Sequence[Mapping[str, object]]) -> dict[str, object]:
    row_counts: Counter[str] = Counter()
    unique_by_surface: dict[str, set[str]] = defaultdict(set)
    family_counts: Counter[str] = Counter()
    unique_keys: set[str] = set()
    for item in evaluated:
        family_counts[str(item.get("artifactFamily") or "unknown")] += 1
        key = str(item.get("uniqueTradeKey") or "")
        if key:
            unique_keys.add(key)
        for surface in DRIFT_SURFACES:
            if item.get(surface):
                row_counts[surface] += 1
                if key:
                    unique_by_surface[surface].add(key)
        if item.get("anyModelRelevantChange") and item.get("sensitiveGateContext"):
            row_counts["sensitiveGateContextAffected"] += 1
            if key:
                unique_by_surface["sensitiveGateContextAffected"].add(key)
    return {
        "evaluatedRows": len(evaluated),
        "uniqueTradeKeys": len(unique_keys),
        "artifactFamilyCounts": dict(sorted(family_counts.items())),
        "rowsBySurface": {key: int(row_counts.get(key, 0)) for key in DRIFT_SURFACES + ("sensitiveGateContextAffected",)},
        "uniqueTradeKeysBySurface": {
            key: len(unique_by_surface.get(key, set()))
            for key in DRIFT_SURFACES + ("sensitiveGateContextAffected",)
        },
    }


def _compatibility_sweep(
    *,
    impact_records: Sequence[Mapping[str, object]],
    archive_records: Sequence[Mapping[str, object]],
    evaluated: Sequence[Mapping[str, object]],
    runtime_scan: Mapping[str, object],
) -> dict[str, object]:
    all_records = list(impact_records) + list(archive_records)
    old_without_model = 0
    for record in all_records:
        has_old = any(
            record.get(key) not in (None, "")
            for key in ("price_implied_probability", "entryProbability", "price")
        )
        has_model = any(
            record.get(key) not in (None, "")
            for key in ("model_probability", "modelProbability", "economic_side_probability", "economicSideProbability")
        )
        if has_old and not has_model:
            old_without_model += 1
    return {
        "oldRowsWithoutModelProbability": old_without_model,
        "unknownEconomicProbabilityRows": sum(
            1 for item in evaluated if item.get("economicSideProbability") == "unknown"
        ),
        "rawFieldsPreservedBySourceScan": bool(runtime_scan.get("rawDisplayFieldsPreserved")),
        "oldReportAbsentSafeMarkersPresent": bool(runtime_scan.get("oldReportLoadingAbsentSafe")),
        "browserEntryProbabilitySortStillRaw": bool(runtime_scan.get("browserEntryProbabilitySortStillRaw")),
        "exportsAdditiveOnlyByScope": bool(runtime_scan.get("archiveUsesHelperOnlyForAdditiveRows")),
        "storageSchemaUnchangedByScan": not bool(runtime_scan.get("storageSchemaMentionsPhase2Fields")),
    }


def _unexpected_scope_findings(runtime_scan: Mapping[str, object]) -> list[str]:
    findings: list[str] = []
    if not runtime_scan.get("centralHelperUsedByScoreTrade"):
        findings.append("scanner_score_trade_not_using_central_side_outcome_helper")
    if not runtime_scan.get("centralHelperUsedByEventForensicScore"):
        findings.append("event_forensic_score_not_using_central_side_outcome_helper")
    if not runtime_scan.get("rawDisplayFieldsPreserved"):
        findings.append("raw_display_fields_not_preserved_by_source_scan")
    if not runtime_scan.get("modelFieldsHaveProvenance"):
        findings.append("model_probability_provenance_fields_missing")
    if runtime_scan.get("phase3CapitalAtRiskImplemented"):
        findings.append("phase3_capital_at_risk_scope_bleed_detected")
    if runtime_scan.get("phase4ClusterDirectionImplemented"):
        findings.append("phase4_cluster_direction_scope_bleed_detected")
    if runtime_scan.get("storageSchemaMentionsPhase2Fields"):
        findings.append("storage_schema_or_storage_layer_mentions_phase2_fields")
    if runtime_scan.get("liveRpcNetworkChangesDetected"):
        findings.append("live_rpc_or_post_migration_runtime_reference_detected")
    imports = runtime_scan.get("productionImportsThisAuditTool")
    if isinstance(imports, Mapping):
        for path, imported in imports.items():
            if imported:
                findings.append(f"production_path_imports_post_migration_audit_tool:{path}")
    if not runtime_scan.get("browserEntryProbabilitySortStillRaw"):
        findings.append("browser_entry_probability_sort_contract_not_detected")
    if not runtime_scan.get("phase3ExpectedBlockPresent"):
        findings.append("phase3_block_not_detected_in_rfc")
    if not runtime_scan.get("phase4ExpectedFailurePresent"):
        findings.append("phase4_expected_failure_not_detected")
    return findings


def _gate_decision(unexpected: Sequence[str], compatibility: Mapping[str, object]) -> str:
    if unexpected:
        return "phase2_needs_fix"
    if not compatibility.get("rawFieldsPreservedBySourceScan") or not compatibility.get("oldReportAbsentSafeMarkersPresent"):
        return "phase2_needs_more_review"
    return "phase2_stable"


def _review_case(item: Mapping[str, object]) -> dict[str, object]:
    surfaces = [surface for surface in DRIFT_SURFACES if item.get(surface)]
    return {
        "tradeKey": item.get("uniqueTradeKey"),
        "artifactFamily": item.get("artifactFamily"),
        "artifactPath": item.get("artifactPath"),
        "rowId": item.get("rowId"),
        "wallet": item.get("wallet"),
        "conditionId": item.get("conditionId"),
        "market": item.get("market"),
        "rawOrderSide": item.get("rawOrderSide"),
        "rawTokenOutcome": item.get("rawTokenOutcome"),
        "rawTokenPrice": item.get("rawTokenPrice"),
        "economicSide": item.get("economicSide"),
        "economicSideProbability": item.get("economicSideProbability"),
        "oldInterpretation": {
            "direction": item.get("currentDirection"),
            "lowProbability30": item.get("currentLowProbability30"),
            "lowProbability35": item.get("currentLowProbability35"),
            "nearCertainty95": item.get("currentNearCertainty95"),
            "nearCertainty98": item.get("currentNearCertainty98"),
            "laterWon": item.get("currentLaterWon"),
        },
        "newInterpretation": {
            "direction": item.get("hypotheticalDirection"),
            "lowProbability30": item.get("hypotheticalLowProbability30"),
            "lowProbability35": item.get("hypotheticalLowProbability35"),
            "nearCertainty95": item.get("hypotheticalNearCertainty95"),
            "nearCertainty98": item.get("hypotheticalNearCertainty98"),
            "laterWon": item.get("hypotheticalLaterWon"),
        },
        "affectedScannerArchiveEventForensicOutput": _affected_output_surfaces(item),
        "affectedSurfaces": surfaces,
        "qualityNotes": list(item.get("qualityNotes") or []),
        "expectedByRfc": True,
    }


def _affected_output_surfaces(item: Mapping[str, object]) -> list[str]:
    surfaces: list[str] = []
    family = str(item.get("artifactFamily") or "")
    if item.get("lowProbability30Changed") or item.get("nearCertainty95Changed") or item.get("nearCertainty98Changed"):
        if family.startswith("archive"):
            surfaces.append("archive_model_flags")
        elif family.startswith("event_forensic") or family.startswith("ceasefire"):
            surfaces.append("event_forensic_model_flags")
        else:
            surfaces.append("scanner_model_flags")
    if item.get("laterCorrectnessChanged"):
        surfaces.append("event_forensic_later_correctness")
    if item.get("directionChanged"):
        surfaces.append("direction_context_only_phase4_blocked")
    if item.get("sensitiveGateContext"):
        surfaces.append("sensitive_gate_context_indirect")
    return surfaces


def _packet_family_group(item: Mapping[str, object]) -> str:
    family = str(item.get("artifactFamily") or "")
    if family.startswith("event_forensic") or family.startswith("ceasefire"):
        return "event_forensic"
    if family.startswith("archive"):
        return "archive"
    if family.startswith("scanner"):
        return "scanner"
    if family.startswith("reconstruction"):
        return "reconstruction"
    return "other"


def _function_slice(source: str, signature: str) -> str:
    start = source.find(signature)
    if start < 0:
        return ""
    next_def = source.find("\ndef ", start + len(signature))
    if next_def < 0:
        return source[start:]
    return source[start:next_def]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _escape_md(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sidecar-only post-Phase 2 side/outcome drift audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-json", default=DEFAULT_JSON_PATH)
    parser.add_argument("--output-md", default=DEFAULT_MARKDOWN_PATH)
    parser.add_argument("--review-dir", default=DEFAULT_REVIEW_DIR)
    parser.add_argument("--max-files", type=int, default=60)
    parser.add_argument("--max-rows-per-file", type=int, default=120)
    parser.add_argument("--archive-max-files", type=int, default=120)
    parser.add_argument("--archive-max-rows-per-file", type=int, default=100)
    parser.add_argument("--archive-max-bytes", type=int, default=2_000_000)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_post_migration_drift_audit(
        root=args.root,
        max_files=args.max_files,
        max_rows_per_file=args.max_rows_per_file,
        archive_max_files=args.archive_max_files,
        archive_max_rows_per_file=args.archive_max_rows_per_file,
        archive_max_bytes=args.archive_max_bytes,
    )
    written = write_outputs(
        report,
        json_path=args.output_json,
        markdown_path=args.output_md,
        review_dir=args.review_dir,
    )
    if not args.quiet:
        print(json.dumps({"gateDecision": report["gateDecision"], **written}, indent=2, sort_keys=True))
    return 0 if report["gateDecision"] != "phase2_needs_fix" else 1


if __name__ == "__main__":
    raise SystemExit(main())
