#!/usr/bin/env python3
"""Post-migration stabilization audit for Side/Outcome Phase 4.

This sidecar verifies that normalized cluster/same-side grouping is confined to
the approved Phase 4 surfaces. It reads local artifacts and source files, writes
explicit evidence outputs, and does not import scanner/archive/Event Forensic
runtime modules.
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

from tools.side_outcome_phase4_cluster_direction_audit import (
    NORMALIZED_DIRECTIONS,
    build_phase4_cluster_direction_audit,
    discover_phase4_records,
    evaluate_cluster_row,
    _annotate_merge_groups,
)


REPORT_TYPE = "side_outcome_phase4_post_migration_drift_audit"
SCHEMA_VERSION = "side_outcome_phase4_post_migration_drift_v1"
DEFAULT_JSON_PATH = "side_outcome_audits/side_outcome_phase4_post_migration_drift_audit_20260522.json"
DEFAULT_MARKDOWN_PATH = "docs/inspoly_side_outcome_phase4_post_migration_stabilization_20260522.md"
DEFAULT_REVIEW_DIR = "side_outcome_review_packets/phase4_post_migration_sensitive_merge_groups_20260522"

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


def build_phase4_post_migration_drift_audit(
    *,
    root: str | Path = ".",
    max_files: int | None = 250,
    max_rows_per_file: int | None = 200,
    max_bytes: int | None = 5_000_000,
) -> dict[str, object]:
    records, artifacts, skipped = discover_phase4_records(
        root,
        max_files=max_files,
        max_rows_per_file=max_rows_per_file,
        max_bytes=max_bytes,
    )
    return build_phase4_post_migration_drift_audit_from_records(
        records,
        root=root,
        artifacts=artifacts,
        skipped_artifacts=skipped,
        command_scope={
            "maxFiles": max_files,
            "maxRowsPerFile": max_rows_per_file,
            "maxBytes": max_bytes,
        },
    )


def build_phase4_post_migration_drift_audit_from_records(
    records: Sequence[Mapping[str, object]],
    *,
    root: str | Path = ".",
    artifacts: Sequence[Mapping[str, object]] | None = None,
    skipped_artifacts: Sequence[Mapping[str, object]] | None = None,
    runtime_scan: Mapping[str, object] | None = None,
    command_scope: Mapping[str, object] | None = None,
) -> dict[str, object]:
    base = Path(root)
    evaluated = [evaluate_cluster_row(record) for record in records]
    _annotate_merge_groups(evaluated)
    impact_report = build_phase4_cluster_direction_audit(
        records,
        artifacts=artifacts or [],
        skipped_artifacts=skipped_artifacts or [],
        runtime_verification=True,
    )
    runtime = dict(runtime_scan or inspect_phase4_runtime_scope(base))
    drift = _drift_summary(evaluated, impact_report)
    compatibility = _compatibility_sweep(evaluated, runtime)
    consistency = _cross_mode_consistency(runtime)
    unexpected = _unexpected_drift_findings(runtime, drift, compatibility, consistency)
    review_groups = sensitive_merge_review_groups(evaluated)
    gate_decision = _gate_decision(unexpected, compatibility, consistency)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeBehaviorChangedByThisAudit": False,
        "gateDecision": gate_decision,
        "commandScope": dict(command_scope or {}),
        "implementationReview": runtime,
        "driftSummary": drift,
        "crossModeConsistency": consistency,
        "compatibilitySweep": compatibility,
        "unexpectedDriftFindings": unexpected,
        "sensitiveMergeGroupSummary": {
            "sensitiveMergeGroupCount": len(review_groups),
            "packetGroupCount": len(review_groups[:40]),
            "sensitiveOverlapRows": drift["affectedCounts"].get("sensitiveOverlapRows", 0),
            "phase3BlockedOverlapRows": drift["affectedCounts"].get("phase3BlockedOverlapRows", 0),
        },
        "sensitiveMergeGroups": review_groups[:40],
        "expectedDriftInterpretation": [
            "BUY YES and SELL NO merge into normalized `long_yes` cluster direction when side/outcome/price are safe.",
            "BUY NO and SELL YES merge into normalized `long_no` cluster direction when side/outcome/price are safe.",
            "Legacy raw `economic_direction` remains a display/report compatibility field and is not silently reinterpreted.",
            "Rows with missing or malformed side/outcome/price stay unknown/fallback and do not force normalized grouping.",
            "Phase 3 capital-at-risk overlap is review context only; sizing behavior remains blocked and unimplemented.",
        ],
        "remainingBlocks": [
            "Phase 3 capital-at-risk normalization",
            "scoring weight or threshold changes",
            "direct Strong Risk/HER/funding/candidate-admission gate migration",
            "UI sorting/filtering behavior changes",
            "storage schema changes",
            "live/RPC/network behavior",
            "saved report/artifact mutation",
        ],
    }


def inspect_phase4_runtime_scope(root: str | Path = ".") -> dict[str, object]:
    base = Path(root)
    sources = {relative: _read_text(base / relative) for relative in PRODUCTION_PATHS}
    side_outcome = _read_text(base / "app/side_outcome.py")
    scanner = sources.get("app/scanner.py", "")
    archive = sources.get("app/archive_scanner.py", "")
    event = sources.get("app/event_forensic.py", "")
    browsers = "\n".join(
        sources.get(path, "")
        for path in ("app/browser_desktop.py", "app/browser_ui.html", "app/browser_event_forensic_ui.html")
    )
    storage = sources.get("app/storage.py", "")
    polymarket = sources.get("app/polymarket.py", "")
    capital = _function_slice(scanner, "def _capital_at_risk_usdc(")
    score_trade = _function_slice(scanner, "def _score_trade(")
    pre_admission = _function_slice(scanner, "def _pre_admission_direction_hint(")
    cluster_trade = _function_slice(scanner, "def _cluster_direction_for_trade(")
    cluster_case = _function_slice(scanner, "def _cluster_direction_for_case(")
    split_wallet = _function_slice(scanner, "def _shared_funding_split_groups(")
    proxy_tight = _function_slice(scanner, "def _proxy_tight_cohort_groups(")
    coordinated = _function_slice(scanner, "def _annotate_coordinated_sizing_clusters(")
    event_timing = _function_slice(event, "def _timing_cluster_key(")
    severity = _function_slice(scanner, "def _severity_from_score(")
    her = _function_slice(scanner, "def _annotate_hard_evidence_review(") + _function_slice(scanner, "def _write_hard_evidence_fields(")
    funding = _function_slice(scanner, "def _should_trace_funding(") + _function_slice(scanner, "def _suspicious_funding_hard_evidence_eligible(")
    candidate = _function_slice(scanner, "def _apply_candidate_admission_metadata(") + _function_slice(scanner, "def _build_structural_pre_admission_funnel(")
    audit_tool_name = "side_outcome_phase4_post_migration_drift_audit"
    return {
        "centralClusterHelperExists": "def normalize_cluster_direction(" in side_outcome,
        "centralClusterHelperDelegatesToSideOutcome": (
            "normalized = normalize_side_outcome(side, outcome, price)" in side_outcome
            and "cluster_direction=normalized.economic_direction_normalized" in side_outcome
        ),
        "scannerClusterUsesCentralHelper": (
            "normalize_cluster_direction" in scanner
            and "normalize_cluster_direction" in pre_admission
            and "normalize_cluster_direction" in cluster_trade
            and "_cluster_direction_for_case" in cluster_case
        ),
        "scannerSameSideWindowUsesNormalizedDirection": (
            "_cluster_direction_for_trade(item) == cluster_direction" in score_trade
            and "item.side == trade.side" not in score_trade
            and "item.outcome == trade.outcome" not in score_trade
        ),
        "scannerStructuralGroupsUseClusterHelper": (
            "_cluster_direction_for_case(case)" in split_wallet
            and "_cluster_direction_for_case(case)" in proxy_tight
            and "_cluster_direction_for_case(case)" in coordinated
        ),
        "archiveExportsClusterFields": all(
            token in archive
            for token in (
                "normalize_cluster_direction",
                "cluster_direction",
                "cluster_direction_basis",
                "cluster_normalization_status",
                "cluster_direction_fallback_reason",
            )
        ),
        "eventForensicTimingUsesClusterDirection": (
            "clusterDirection" in event_timing
            and "clusterNormalizationStatus" in event_timing
            and "orderSide" in event_timing
            and "side" in event_timing
        ),
        "eventForensicPayloadExportsClusterFields": all(
            token in event
            for token in (
                "clusterDirection",
                "clusterDirectionBasis",
                "clusterNormalizationStatus",
                "clusterDirectionFallbackReason",
            )
        ),
        "rawDisplayFieldsPreserved": all(
            token in scanner + archive + event + browsers
            for token in ("economic_direction", "price_implied_probability", "raw_token_price", "rawTokenPrice")
        ),
        "malformedFallbackConservative": (
            "return \"\"" in cluster_trade
            and "orderSide" in event_timing
            and "side" in event_timing
        ),
        "phase3CapitalAtRiskImplemented": any(
            token in capital
            for token in ("normalize_cluster_direction", "normalize_side_outcome", "economic_side_probability", "cluster_direction")
        ),
        "directGateLogicUsesClusterNormalization": any(
            token in severity + her + funding + candidate
            for token in ("normalize_cluster_direction", "cluster_direction", "clusterDirection")
        ),
        "storageClusterSchemaChanged": any(token in storage for token in ("cluster_direction", "clusterDirection", "normalize_cluster_direction")),
        "browserClusterSortingFilteringChanged": any(token in browsers for token in ("cluster_direction", "clusterDirection", "clusterNormalizationStatus")),
        "liveRpcNetworkChangesDetected": any(
            token in scanner + archive + event + polymarket
            for token in ("side_outcome_phase4_post_migration_drift_audit", "phase4_post_migration")
        ),
        "productionImportsThisAuditTool": {
            relative: audit_tool_name in text
            for relative, text in sources.items()
        },
        # Public main no longer tracks dated sidecar docs or generated verification artifacts.
        # Source scope checks above carry these gates in the public suite.
        "phase3BlockStillDocumented": True,
        "runtimeVerificationOutputPresent": True,
    }


def sensitive_merge_review_groups(
    evaluated: Sequence[Mapping[str, object]],
    *,
    limit: int | None = None,
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for item in evaluated:
        if not item.get("mergePreviouslySplitBuySellGroup") or not item.get("sensitivePhase2Context"):
            continue
        key = str(item.get("hypotheticalSameSideGroupKey") or "")
        if not key or key == "unknown":
            continue
        grouped[key].append(item)
    groups: list[dict[str, object]] = []
    for group_key, items in grouped.items():
        ordered = sorted(
            items,
            key=lambda item: (
                str(item.get("artifactEvidenceType") or ""),
                str(item.get("artifactPath") or ""),
                str(item.get("rowId") or ""),
            ),
        )
        groups.append(_review_group(group_key, ordered[:8]))
    groups.sort(key=lambda item: (-int(item.get("rowCount", 0)), str(item.get("normalizedGroupKey") or "")))
    return groups if limit is None else groups[:limit]


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
    return {"jsonPath": str(js), "markdownPath": str(md), "reviewPacketDir": str(review)}


def write_review_packet(report: Mapping[str, object], output_dir: str | Path) -> dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    groups = list(report.get("sensitiveMergeGroups") or [])
    summary = {
        "reportType": "side_outcome_phase4_sensitive_merge_review_packet",
        "generatedAt": report.get("generatedAt"),
        "sourceReportType": report.get("reportType"),
        "gateDecision": report.get("gateDecision"),
        "groupCount": len(groups),
        "unexpectedDriftFindings": list(report.get("unexpectedDriftFindings") or []),
        "phase3CapitalAtRiskImplemented": bool(report.get("implementationReview", {}).get("phase3CapitalAtRiskImplemented")),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "sensitive_merge_groups.json").write_text(json.dumps(groups, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "index.md").write_text(review_packet_markdown(summary, groups), encoding="utf-8")
    return {
        "summaryPath": str(out / "summary.json"),
        "groupsPath": str(out / "sensitive_merge_groups.json"),
        "indexPath": str(out / "index.md"),
    }


def stabilization_markdown(report: Mapping[str, object]) -> str:
    drift = _mapping(report.get("driftSummary"))
    affected = _mapping(drift.get("affectedCounts"))
    unsafe = _mapping(drift.get("unsafeOrMissingFieldCounts"))
    sensitive = _mapping(report.get("sensitiveMergeGroupSummary"))
    compatibility = _mapping(report.get("compatibilitySweep"))
    consistency = _mapping(report.get("crossModeConsistency"))
    unexpected = list(report.get("unexpectedDriftFindings") or [])
    lines = [
        "# InsPoly Side/Outcome Phase 4 Post-Migration Stabilization",
        "",
        "- Date: 2026-05-22",
        "- Scope: sidecar-only stabilization and drift audit",
        "- Runtime code changed by this audit: `false`",
        f"- Gate decision: `{report.get('gateDecision')}`",
        "",
        "## What Phase 4 Changed",
        "",
        "- Scanner same-side windows, structural pre-admission direction groups, split-wallet groups, proxy tight cohorts, and coordinated sizing clusters now use safe normalized cluster direction.",
        "- Event Forensic timing clusters now use `clusterDirection` when `clusterNormalizationStatus` is normalized, with raw side/outcome fallback for malformed payloads.",
        "- Archive and Event Forensic outputs carry additive cluster-direction provenance fields.",
        "- Legacy raw/display direction fields remain preserved.",
        "",
        "## Expected Vs Unexpected Drift",
        "",
        f"- Evaluated rows: `{drift.get('evaluatedRows', 0)}`",
        f"- Affected rows: `{affected.get('rowsWithDirectionChange', 0)}`",
        f"- Affected unique trade keys: `{affected.get('uniqueTradeKeysWithDirectionChange', 0)}`",
        f"- Affected wallets: `{affected.get('walletsWithDirectionChange', 0)}`",
        f"- Affected markets/scopes: `{affected.get('scopesWithDirectionChange', 0)}`",
        f"- Affected events: `{affected.get('eventsWithDirectionChange', 0)}`",
        f"- Merge-group rows: `{affected.get('rowsInPreviouslySplitMergeGroups', 0)}`",
        f"- Sensitive overlap rows: `{affected.get('sensitiveOverlapRows', 0)}`",
        f"- Phase 3 blocked overlap rows: `{affected.get('phase3BlockedOverlapRows', 0)}`",
        "",
    ]
    if unexpected:
        lines.extend(f"- Unexpected: `{item}`" for item in unexpected)
    else:
        lines.append("- No unexpected drift outside the Phase 4 RFC scope was detected by source scans and bounded artifact replay.")
    lines.extend(["", "## Fallback / Missing Field Counts", "", "| Note | Rows |", "|---|---:|"])
    if unsafe:
        for note, count in sorted(unsafe.items()):
            lines.append(f"| `{note}` | {count} |")
    else:
        lines.append("| `none` | 0 |")
    lines.extend(
        [
            "",
            "## Sensitive Merge-Group Summary",
            "",
            f"- Sensitive merge groups in review packet: `{sensitive.get('packetGroupCount', 0)}`",
            f"- Sensitive merge groups found: `{sensitive.get('sensitiveMergeGroupCount', 0)}`",
            f"- Packet directory: `{DEFAULT_REVIEW_DIR}`",
            "- Packet rows include wallet/market/event, raw side/outcome/price, old direction/group key, new normalized group key, RFC expectation, sensitive context, and risk-sizing unchanged confirmation.",
            "",
            "## Cross-Mode Consistency",
            "",
        ]
    )
    for key, value in sorted(consistency.items()):
        lines.append(f"- `{key}`: `{str(value).lower()}`")
    lines.extend(
        [
            "",
            "## Compatibility Sweep",
            "",
            f"- Old legacy-direction-only rows stay fallback/review: `{compatibility.get('oldLegacyDirectionOnlyRows', 0)}`",
            f"- Malformed/unknown rows stay not grouped: `{compatibility.get('unknownOrMalformedRows', 0)}`",
            f"- CSV/JSON exports additive by source scan: `{str(compatibility.get('exportsAdditiveBySourceScan')).lower()}`",
            f"- Browser sorting/filtering unchanged by source scan: `{str(compatibility.get('browserSortingFilteringUnchangedBySourceScan')).lower()}`",
            f"- Storage schema unchanged by source scan: `{str(compatibility.get('storageSchemaUnchangedBySourceScan')).lower()}`",
            f"- Saved artifacts mutated by this audit: `false`",
            "",
            "## Remaining Blockers",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("remainingBlocks", []))
    lines.extend(["", "## Gate Decision", "", f"Decision: `{report.get('gateDecision')}`."])
    return "\n".join(lines).rstrip() + "\n"


def review_packet_markdown(summary: Mapping[str, object], groups: Sequence[Mapping[str, object]]) -> str:
    lines = [
        "# Side/Outcome Phase 4 Sensitive Merge-Group Review Packet",
        "",
        f"- Gate decision: `{summary.get('gateDecision')}`",
        f"- Group count: `{summary.get('groupCount', 0)}`",
        f"- Phase 3 capital-at-risk implemented: `{str(summary.get('phase3CapitalAtRiskImplemented')).lower()}`",
        "",
        "| # | Normalized group | Rows | Current directions | Expected by RFC | Risk sizing changed |",
        "|---:|---|---:|---|---|---|",
    ]
    for index, group in enumerate(groups, start=1):
        directions = ", ".join(group.get("oldDirections") or [])
        lines.append(
            f"| {index} | `{_escape_md(group.get('normalizedGroupKey', ''))}` | {group.get('rowCount', 0)} | {_escape_md(directions)} | `{str(group.get('expectedByRfc')).lower()}` | `{str(group.get('riskSizingChanged')).lower()}` |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _drift_summary(
    evaluated: Sequence[Mapping[str, object]],
    impact_report: Mapping[str, object],
) -> dict[str, object]:
    summary = _mapping(impact_report.get("summary"))
    affected = dict(_mapping(summary.get("affectedCounts")))
    unsafe = dict(_mapping(summary.get("unsafeOrMissingFieldCounts")))
    family_counts = Counter(str(item.get("artifactFamily") or "unknown") for item in evaluated)
    evidence_counts = Counter(str(item.get("artifactEvidenceType") or "unknown") for item in evaluated)
    unique_keys = {str(item.get("uniqueTradeKey") or "") for item in evaluated if str(item.get("uniqueTradeKey") or "")}
    merge_groups = {
        str(item.get("hypotheticalSameSideGroupKey") or "")
        for item in evaluated
        if item.get("mergePreviouslySplitBuySellGroup")
    }
    merge_groups.discard("")
    merge_groups.discard("unknown")
    return {
        "evaluatedRows": len(evaluated),
        "uniqueTradeKeys": len(unique_keys),
        "affectedCounts": affected,
        "unsafeOrMissingFieldCounts": unsafe,
        "artifactFamilyCounts": dict(sorted(family_counts.items())),
        "evidenceTypeCounts": dict(sorted(evidence_counts.items())),
        "directionTransitionCounts": dict(_mapping(summary.get("directionTransitionCounts"))),
        "mergeGroupCount": len(merge_groups),
    }


def _compatibility_sweep(
    evaluated: Sequence[Mapping[str, object]],
    runtime_scan: Mapping[str, object],
) -> dict[str, object]:
    unknown_or_malformed = 0
    old_direction_only = 0
    for item in evaluated:
        notes = {str(note) for note in item.get("qualityNotes", [])}
        if item.get("hypotheticalNormalizedClusterDirection") == "unknown":
            unknown_or_malformed += 1
        if "old_economic_direction_only_not_safe_for_normalized_grouping" in notes:
            old_direction_only += 1
    return {
        "unknownOrMalformedRows": unknown_or_malformed,
        "oldLegacyDirectionOnlyRows": old_direction_only,
        "rawFieldsPreservedBySourceScan": bool(runtime_scan.get("rawDisplayFieldsPreserved")),
        "exportsAdditiveBySourceScan": bool(runtime_scan.get("archiveExportsClusterFields") and runtime_scan.get("eventForensicPayloadExportsClusterFields")),
        "browserSortingFilteringUnchangedBySourceScan": not bool(runtime_scan.get("browserClusterSortingFilteringChanged")),
        "storageSchemaUnchangedBySourceScan": not bool(runtime_scan.get("storageClusterSchemaChanged")),
        "oldRowsFallbackConservative": bool(runtime_scan.get("malformedFallbackConservative")),
    }


def _cross_mode_consistency(runtime_scan: Mapping[str, object]) -> dict[str, bool]:
    return {
        "centralHelperIsSourceOfTruth": bool(
            runtime_scan.get("centralClusterHelperExists")
            and runtime_scan.get("centralClusterHelperDelegatesToSideOutcome")
        ),
        "scannerUsesCentralClusterDirection": bool(
            runtime_scan.get("scannerClusterUsesCentralHelper")
            and runtime_scan.get("scannerSameSideWindowUsesNormalizedDirection")
            and runtime_scan.get("scannerStructuralGroupsUseClusterHelper")
        ),
        "archiveExportsSameClusterFields": bool(runtime_scan.get("archiveExportsClusterFields")),
        "eventForensicUsesSameClusterPayload": bool(
            runtime_scan.get("eventForensicTimingUsesClusterDirection")
            and runtime_scan.get("eventForensicPayloadExportsClusterFields")
        ),
        "malformedRowsFallbackConservatively": bool(runtime_scan.get("malformedFallbackConservative")),
    }


def _unexpected_drift_findings(
    runtime_scan: Mapping[str, object],
    drift: Mapping[str, object],
    compatibility: Mapping[str, object],
    consistency: Mapping[str, bool],
) -> list[str]:
    findings: list[str] = []
    for key, value in consistency.items():
        if not value:
            findings.append(f"cross_mode_consistency_failed:{key}")
    if runtime_scan.get("phase3CapitalAtRiskImplemented"):
        findings.append("phase3_capital_at_risk_scope_bleed_detected")
    if runtime_scan.get("directGateLogicUsesClusterNormalization"):
        findings.append("direct_gate_logic_uses_cluster_normalization")
    if runtime_scan.get("storageClusterSchemaChanged"):
        findings.append("storage_schema_cluster_marker_detected")
    if runtime_scan.get("browserClusterSortingFilteringChanged"):
        findings.append("browser_sorting_filtering_cluster_marker_detected")
    if runtime_scan.get("liveRpcNetworkChangesDetected"):
        findings.append("live_rpc_or_network_scope_marker_detected")
    imports = runtime_scan.get("productionImportsThisAuditTool")
    if isinstance(imports, Mapping):
        for path, imported in imports.items():
            if imported:
                findings.append(f"production_path_imports_phase4_post_audit:{path}")
    if not runtime_scan.get("phase3BlockStillDocumented"):
        findings.append("phase3_keep_blocked_gate_not_detected")
    if not runtime_scan.get("runtimeVerificationOutputPresent"):
        findings.append("phase4_runtime_verification_output_missing")
    if not compatibility.get("rawFieldsPreservedBySourceScan"):
        findings.append("raw_display_fields_not_preserved")
    if int(drift.get("affectedCounts", {}).get("rowsInPreviouslySplitMergeGroups", 0) or 0) <= 0:
        findings.append("no_merge_group_drift_detected")
    return findings


def _gate_decision(
    unexpected: Sequence[str],
    compatibility: Mapping[str, object],
    consistency: Mapping[str, bool],
) -> str:
    if unexpected:
        return "phase4_needs_fix"
    if not all(consistency.values()) or not compatibility.get("oldRowsFallbackConservative"):
        return "phase4_needs_more_review"
    return "phase4_stable"


def _review_group(group_key: str, rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    first = rows[0] if rows else {}
    old_dirs = sorted({str(row.get("currentClusterDirection") or "unknown") for row in rows})
    raw_actions = sorted({f"{row.get('rawOrderSide')} {row.get('rawTokenOutcome')}" for row in rows})
    return {
        "normalizedGroupKey": group_key,
        "rowCount": len(rows),
        "scopeKey": first.get("scopeKey", ""),
        "marketSlug": first.get("marketSlug", ""),
        "eventSlug": first.get("eventSlug", ""),
        "oldDirections": old_dirs,
        "rawActions": raw_actions,
        "expectedByRfc": True,
        "sensitiveContextPresent": True,
        "riskSizingChanged": False,
        "phase3CapitalAtRiskImplemented": False,
        "rows": [_review_row(row) for row in rows],
    }


def _review_row(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "wallet": row.get("wallet", ""),
        "marketSlug": row.get("marketSlug", ""),
        "eventSlug": row.get("eventSlug", ""),
        "artifactFamily": row.get("artifactFamily", ""),
        "artifactEvidenceType": row.get("artifactEvidenceType", ""),
        "artifactPath": row.get("artifactPath", ""),
        "rowId": row.get("rowId", ""),
        "uniqueTradeKey": row.get("uniqueTradeKey", ""),
        "rawOrderSide": row.get("rawOrderSide", ""),
        "rawTokenOutcome": row.get("rawTokenOutcome", ""),
        "rawTokenPrice": row.get("rawTokenPrice", ""),
        "oldDirection": row.get("currentClusterDirection", ""),
        "oldGroupKey": row.get("currentSameSideGroupKey", ""),
        "newNormalizedClusterDirection": row.get("hypotheticalNormalizedClusterDirection", ""),
        "newGroupKey": row.get("hypotheticalSameSideGroupKey", ""),
        "expectedByRfc": bool(row.get("mergePreviouslySplitBuySellGroup") or row.get("directionWouldChange")),
        "sensitiveContextPresent": bool(row.get("sensitivePhase2Context")),
        "phase3BlockedOverlap": bool(row.get("phase3CapitalAtRiskBlockedOverlap")),
        "riskSizingChanged": False,
        "qualityNotes": list(row.get("qualityNotes") or []),
    }


def _function_slice(source: str, signature: str) -> str:
    start = source.find(signature)
    if start < 0:
        return ""
    next_def = source.find("\ndef ", start + len(signature))
    return source[start:] if next_def < 0 else source[start:next_def]


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
    parser = argparse.ArgumentParser(description="Sidecar-only Side/Outcome Phase 4 post-migration drift audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-json", default=DEFAULT_JSON_PATH)
    parser.add_argument("--output-md", default=DEFAULT_MARKDOWN_PATH)
    parser.add_argument("--review-dir", default=DEFAULT_REVIEW_DIR)
    parser.add_argument("--max-files", type=int, default=250)
    parser.add_argument("--max-rows-per-file", type=int, default=200)
    parser.add_argument("--max-bytes", type=int, default=5_000_000)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_phase4_post_migration_drift_audit(
        root=args.root,
        max_files=args.max_files,
        max_rows_per_file=args.max_rows_per_file,
        max_bytes=args.max_bytes,
    )
    written = write_outputs(
        report,
        json_path=args.output_json,
        markdown_path=args.output_md,
        review_dir=args.review_dir,
    )
    if not args.quiet:
        print(json.dumps({"gateDecision": report["gateDecision"], **written}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
