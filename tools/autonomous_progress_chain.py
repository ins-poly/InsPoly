from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("autonomous_progress_outputs")
INPUT_PATTERNS = {
    "local_known_case_benchmark": (Path("known_case_benchmarks"), "local_known_case_benchmark_*.json"),
    "benchmark_labeling_workbench": (Path("known_case_benchmarks"), "benchmark_labeling_workbench_*.json"),
    "benchmark_label_readiness": (Path("known_case_benchmarks"), "benchmark_label_readiness_*.json"),
    "benchmark_label_priority_queue": (Path("known_case_benchmarks"), "benchmark_label_priority_queue_*.json"),
    "benchmark_label_priority_template": (Path("known_case_benchmarks"), "benchmark_label_priority_template_*.json"),
    "benchmark_label_handoff_pack": (Path("known_case_benchmarks"), "benchmark_label_handoff_pack_*.json"),
    "benchmark_label_worksheet": (Path("known_case_benchmarks"), "benchmark_label_worksheet_*.json"),
    "benchmark_label_action_pack": (Path("known_case_benchmarks"), "benchmark_label_action_pack_*.json"),
    "benchmark_label_csv_preflight": (Path("known_case_benchmarks"), "benchmark_label_csv_preflight_*.json"),
    "benchmark_label_completion_status": (Path("known_case_benchmarks"), "benchmark_label_completion_status_*.json"),
    "benchmark_label_expectation_report": (Path("known_case_benchmarks"), "benchmark_label_expectation_report_*.json"),
    "benchmark_label_cycle": (Path("known_case_benchmarks"), "benchmark_label_cycle_*.json"),
    "event_forensic_performance_audit": (Path("event_forensic_performance_outputs"), "event_forensic_performance_audit_*.json"),
    "event_forensic_performance_rfc": (Path("rfcs"), "EVENT_FORENSIC_PERFORMANCE_RFC_*.json"),
    "event_forensic_trade_collection_profile": (Path("event_forensic_performance_outputs"), "event_forensic_trade_collection_profile_*.json"),
    "event_forensic_perf001_progress_spec": (Path("event_forensic_performance_outputs"), "event_forensic_perf001_progress_spec_*.json"),
    "event_forensic_perf001_implementation_report": (Path("event_forensic_performance_outputs"), "event_forensic_perf001_implementation_report_*.json"),
    "event_forensic_scope_semantics_audit": (Path("event_forensic_scope_outputs"), "event_forensic_scope_semantics_audit_*.json"),
    "archive_visibility_doc_drift_audit": (Path("docs_audit_outputs"), "archive_visibility_doc_drift_audit_*.json"),
    "offline_timeline_coverage_audit": (Path("timeline_context_outputs"), "offline_timeline_coverage_audit_*.json"),
    "offline_timeline_template_pack": (Path("timeline_context_outputs"), "offline_timeline_template_pack_*.json"),
    "offline_timeline_csv_validation": (Path("timeline_context_outputs"), "offline_timeline_csv_validation_*.json"),
    "ui_runtime_dependency_audit": (Path("ui_readiness_outputs"), "ui_runtime_dependency_audit_*.json"),
    "ui_offline_readiness_plan": (Path("ui_readiness_outputs"), "ui_offline_readiness_plan_*.json"),
    "ui_offline_asset_manifest": (Path("ui_readiness_outputs"), "ui_offline_asset_manifest_*.json"),
    "ui_offline_implementation_preflight": (Path("ui_readiness_outputs"), "ui_offline_implementation_preflight_*.json"),
    "direct_script_import_audit": (Path("tooling_audit_outputs"), "direct_script_import_audit_*.json"),
    "direct_script_cli_smoke_audit": (Path("tooling_audit_outputs"), "direct_script_cli_smoke_audit_*.json"),
    "test_coverage_inventory_audit": (Path("tooling_audit_outputs"), "test_coverage_inventory_audit_*.json"),
    "analyst_readiness_cycle_summary": (Path("analyst_quality_outputs"), "analyst_readiness_cycle_summary_*.json"),
    "operator_rpc_recovery_package": (Path("validation_corpus_outputs"), "operator_rpc_capacity_recovery_package_*.json"),
    "autonomous_branch_decision_report": (Path("autonomous_branch_outputs"), "autonomous_branch_decision_report_*.json"),
}


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _latest_file(directory: Path, pattern: str) -> Path | None:
    root = _resolve(directory) or directory
    if not root.exists():
        return None
    candidates = sorted(root.glob(pattern), key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
    return candidates[0] if candidates else None


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def discover_inputs() -> dict[str, Path | None]:
    return {name: _latest_file(directory, pattern) for name, (directory, pattern) in INPUT_PATTERNS.items()}


def _summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("summary")
    return value if isinstance(value, Mapping) else {}


def build_chain(payloads: Mapping[str, Mapping[str, Any]], *, input_paths: Mapping[str, Path | None] | None = None) -> dict[str, Any]:
    benchmark = _summary(payloads.get("local_known_case_benchmark", {}))
    labeling = _summary(payloads.get("benchmark_labeling_workbench", {}))
    label_readiness = _summary(payloads.get("benchmark_label_readiness", {}))
    label_priority = _summary(payloads.get("benchmark_label_priority_queue", {}))
    label_template = _summary(payloads.get("benchmark_label_priority_template", {}))
    label_handoff = _summary(payloads.get("benchmark_label_handoff_pack", {}))
    label_worksheet = _summary(payloads.get("benchmark_label_worksheet", {}))
    label_action_pack = _summary(payloads.get("benchmark_label_action_pack", {}))
    label_preflight = _summary(payloads.get("benchmark_label_csv_preflight", {}))
    label_completion = _summary(payloads.get("benchmark_label_completion_status", {}))
    label_expectation = _summary(payloads.get("benchmark_label_expectation_report", {}))
    label_cycle = _summary(payloads.get("benchmark_label_cycle", {}))
    performance = _summary(payloads.get("event_forensic_performance_audit", {}))
    performance_rfc = _summary(payloads.get("event_forensic_performance_rfc", {}))
    trade_profile = _summary(payloads.get("event_forensic_trade_collection_profile", {}))
    perf001_spec = _summary(payloads.get("event_forensic_perf001_progress_spec", {}))
    perf001_implementation = _summary(payloads.get("event_forensic_perf001_implementation_report", {}))
    scope_audit = _summary(payloads.get("event_forensic_scope_semantics_audit", {}))
    doc_drift = _summary(payloads.get("archive_visibility_doc_drift_audit", {}))
    timeline_audit = _summary(payloads.get("offline_timeline_coverage_audit", {}))
    timeline_template = _summary(payloads.get("offline_timeline_template_pack", {}))
    timeline_validation = _summary(payloads.get("offline_timeline_csv_validation", {}))
    ui = _summary(payloads.get("ui_runtime_dependency_audit", {}))
    ui_plan = _summary(payloads.get("ui_offline_readiness_plan", {}))
    ui_manifest = _summary(payloads.get("ui_offline_asset_manifest", {}))
    ui_preflight = _summary(payloads.get("ui_offline_implementation_preflight", {}))
    direct_import_audit = _summary(payloads.get("direct_script_import_audit", {}))
    direct_cli_smoke_audit = _summary(payloads.get("direct_script_cli_smoke_audit", {}))
    test_coverage_audit = _summary(payloads.get("test_coverage_inventory_audit", {}))
    readiness = _summary(payloads.get("analyst_readiness_cycle_summary", {}))
    operator = payloads.get("operator_rpc_recovery_package", {})
    branch_decision = _summary(payloads.get("autonomous_branch_decision_report", {}))
    prompts = [
        {
            "promptId": "NEXT-001",
            "title": "Human-label local benchmark scaffold rows",
            "allowedImplementation": "reporting_only",
            "prompt": "Inspect known_case_benchmarks/local_known_case_benchmark_*.json and add a separate human-label proposal file. Do not change scoring or gates.",
        },
        {
            "promptId": "NEXT-002",
            "title": "Prioritize event-forensic performance bottleneck fixes as RFC/reporting only",
            "allowedImplementation": "rfc_or_reporting_only",
            "prompt": "Use event_forensic_performance_outputs/event_forensic_performance_audit_*.json to draft a bounded performance RFC. Do not change detector behavior.",
        },
        {
            "promptId": "NEXT-006",
            "title": "Run benchmark label readiness gate",
            "allowedImplementation": "reporting_only",
            "prompt": "Run tools/benchmark_label_readiness_gate.py against the latest benchmark labeling workbench. Do not treat unlabeled rows as truth and do not change detector behavior.",
        },
        {
            "promptId": "NEXT-010",
            "title": "Create benchmark label priority queue",
            "allowedImplementation": "reporting_only",
            "prompt": "Run tools/benchmark_label_priority_queue.py to select a small human-labeling queue from the existing workbench. Do not assign labels or change detector behavior.",
        },
        {
            "promptId": "NEXT-011",
            "title": "Create benchmark label priority template",
            "allowedImplementation": "reporting_only",
            "prompt": "Run tools/benchmark_label_priority_template.py from the latest priority queue. Do not assign labels or change detector behavior.",
        },
        {
            "promptId": "NEXT-012",
            "title": "Create benchmark label handoff pack",
            "allowedImplementation": "reporting_only",
            "prompt": "Run tools/benchmark_label_handoff_pack.py from the latest priority queue. Do not assign labels or change detector behavior.",
        },
        {
            "promptId": "NEXT-013",
            "title": "Check benchmark label completion status",
            "allowedImplementation": "reporting_only",
            "prompt": "Run tools/benchmark_label_completion_status.py to detect whether a human-filled label CSV exists. Do not infer labels or change detector behavior.",
        },
        {
            "promptId": "NEXT-014",
            "title": "Create benchmark label worksheet",
            "allowedImplementation": "reporting_only",
            "prompt": "Run tools/benchmark_label_worksheet.py to generate a human-readable worksheet from the latest label template. Do not infer labels or change detector behavior.",
        },
        {
            "promptId": "NEXT-015",
            "title": "Create benchmark label expectation report",
            "allowedImplementation": "reporting_only",
            "prompt": "Run tools/benchmark_label_expectation_report.py after human labels pass readiness. Do not treat labels as production truth or change detector behavior.",
        },
        {
            "promptId": "NEXT-023",
            "title": "Run full benchmark label cycle",
            "allowedImplementation": "reporting_only",
            "prompt": "Run tools/benchmark_label_cycle.py to refresh completion, CSV preflight, readiness, expectation report, and action pack in one bounded reporting-only pass. Do not infer labels or change detector behavior.",
        },
        {
            "promptId": "NEXT-003",
            "title": "Build PERF-001 trade collection profile",
            "allowedImplementation": "reporting_only",
            "prompt": "Run tools/event_forensic_trade_collection_profile.py and refresh the review index/progress chain. Do not change event scope, fetch behavior, scoring, or gates.",
        },
        {
            "promptId": "NEXT-007",
            "title": "Generate PERF-001 progress instrumentation spec",
            "allowedImplementation": "reporting_spec_only",
            "prompt": "Run tools/event_forensic_perf001_progress_spec.py from the latest trade collection profile. Do not implement app/runtime changes unless separately approved.",
        },
        {
            "promptId": "NEXT-008",
            "title": "Reconcile archive visibility documentation",
            "allowedImplementation": "documentation_or_tests_only",
            "prompt": "Use docs_audit_outputs/archive_visibility_doc_drift_audit_*.json to update docs or add read-only tests. Do not change archive visibility behavior.",
        },
        {
            "promptId": "NEXT-017",
            "title": "Audit offline timeline coverage",
            "allowedImplementation": "reporting_only",
            "prompt": "Run tools/offline_timeline_coverage_audit.py to check local timeline files and saved-output timeline coverage. Do not add external feeds, infer timestamps, or change scoring/gates.",
        },
        {
            "promptId": "NEXT-018",
            "title": "Create offline timeline template pack",
            "allowedImplementation": "template_only",
            "prompt": "Run tools/offline_timeline_template_pack.py from the latest offline timeline coverage audit. Create only header/template docs; do not add external feeds, infer timestamps, or change scoring/gates.",
        },
        {
            "promptId": "NEXT-019",
            "title": "Validate offline timeline CSV template",
            "allowedImplementation": "validation_only",
            "prompt": "Run tools/offline_timeline_csv_validator.py against the latest offline timeline CSV template. Do not move rows into runtime data dirs, add external feeds, infer timestamps, or change scoring/gates.",
        },
        {
            "promptId": "NEXT-004",
            "title": "Plan offline UI dependency work",
            "allowedImplementation": "reporting_or_separate_approved_ui_task",
            "prompt": "Use ui_readiness_outputs/ui_runtime_dependency_audit_*.json to draft an offline UI vendoring plan. Do not vendor or alter UI behavior without explicit approval.",
        },
        {
            "promptId": "NEXT-009",
            "title": "Create UI offline asset manifest",
            "allowedImplementation": "manifest_only",
            "prompt": "Use the latest UI runtime audit and offline readiness plan to generate a manifest-only asset boundary. Do not download assets, vendor files, or alter UI behavior without explicit approval.",
        },
        {
            "promptId": "NEXT-016",
            "title": "Preflight UI offline implementation boundary",
            "allowedImplementation": "preflight_only",
            "prompt": "Run tools/ui_offline_implementation_preflight.py from the latest UI runtime audit, offline plan, and asset manifest. Do not download assets, vendor files, or alter UI behavior without explicit approval.",
        },
        {
            "promptId": "NEXT-020",
            "title": "Audit direct-run imports for local tools",
            "allowedImplementation": "read_only_tooling_audit",
            "prompt": "Run tools/direct_script_import_audit.py to check whether directly executed tools that import app/tools modules have the repo-root sys.path guard before those imports. Do not change scoring, gates, HER routing, funding eligibility, credentials, RPC URLs, or old outputs.",
        },
        {
            "promptId": "NEXT-021",
            "title": "Run direct CLI --help smoke audit",
            "allowedImplementation": "read_only_tooling_audit",
            "prompt": "Run tools/direct_script_cli_smoke_audit.py to smoke-test --help startup for argparse tools. Do not run validation workloads, RPC calls, scanner analysis, or detector changes.",
        },
        {
            "promptId": "NEXT-022",
            "title": "Inventory direct test references",
            "allowedImplementation": "read_only_tooling_audit",
            "prompt": "Run tools/test_coverage_inventory_audit.py to inventory direct test references to app/tools modules. Do not change production behavior, scoring, gates, HER routing, funding eligibility, or saved outputs.",
        },
        {
            "promptId": "NEXT-005",
            "title": "Choose the next approved implementation branch",
            "allowedImplementation": "branch_selection_only",
            "prompt": "Choose one explicit next branch: operator-approved RPC recovery, approved benchmark labeling review, approved PERF-001 reporting instrumentation, approved UI offline implementation, or pause. Do not change detector behavior without explicit approval.",
        },
    ]
    label_rows = int(labeling.get("labelTemplateRowCount") or 0)
    label_readiness_status = str(label_readiness.get("readinessStatus") or "")
    label_priority_rows = int(label_priority.get("queueRowCount") or 0)
    label_template_rows = int(label_template.get("templateRowCount") or 0)
    label_handoff_rows = int(label_handoff.get("queueRowCount") or 0)
    label_worksheet_rows = int(label_worksheet.get("worksheetRowCount") or 0)
    label_action_pack_present = bool(label_action_pack.get("humanActionRequired") is not None)
    label_completion_candidate_csv_count = int(label_completion.get("candidateCsvCount") or 0)
    label_expectation_usable = int(label_expectation.get("usableLabeledRows") or 0)
    label_cycle_status = str(label_cycle.get("cycleStatus") or "")
    performance_runs = int(performance.get("runCount") or 0)
    performance_rfc_count = int(performance_rfc.get("proposalCount") or 0)
    trade_profile_runs = int(trade_profile.get("runCount") or 0)
    perf001_spec_fields = int(perf001_spec.get("proposedFieldCount") or 0)
    perf001_implemented = bool(perf001_implementation.get("persistedPerformanceFieldsAdded"))
    doc_check_count = int(doc_drift.get("checkCount") or 0)
    timeline_coverage_status = str(timeline_audit.get("coverageStatus") or "")
    timeline_template_fields = int(timeline_template.get("templateFieldCount") or 0)
    timeline_validation_status = str(timeline_validation.get("validationStatus") or "")
    ui_plan_step_count = int(ui_plan.get("planStepCount") or 0)
    ui_manifest_asset_count = int(ui_manifest.get("uniqueRuntimeAssetCount") or 0)
    ui_preflight_status = str(ui_preflight.get("preflightStatus") or "")
    direct_import_status = str(direct_import_audit.get("directRunRiskStatus") or "")
    direct_cli_status = str(direct_cli_smoke_audit.get("directCliRiskStatus") or "")
    test_coverage_status = str(test_coverage_audit.get("coverageInventoryStatus") or "")
    if label_rows <= 0:
        recommended = "NEXT-001"
    elif not label_readiness_status:
        recommended = "NEXT-006"
    elif label_readiness_status == "unlabeled_template_only" and label_priority_rows <= 0:
        recommended = "NEXT-010"
    elif label_readiness_status == "unlabeled_template_only" and label_priority_rows > 0 and label_template_rows <= 0:
        recommended = "NEXT-011"
    elif label_readiness_status == "unlabeled_template_only" and label_priority_rows > 0 and label_handoff_rows <= 0:
        recommended = "NEXT-012"
    elif label_readiness_status == "unlabeled_template_only" and label_priority_rows > 0 and label_template_rows > 0 and label_worksheet_rows <= 0:
        recommended = "NEXT-014"
    elif label_readiness_status == "unlabeled_template_only" and label_completion_candidate_csv_count <= 0:
        recommended = "NEXT-013"
    elif label_readiness_status == "ready_for_reporting_regression_only" and label_expectation_usable <= 0:
        recommended = "NEXT-015"
    elif performance_runs > 0 and performance_rfc_count <= 0:
        recommended = "NEXT-002"
    elif performance_rfc_count > 0 and trade_profile_runs <= 0:
        recommended = "NEXT-003"
    elif trade_profile_runs > 0 and perf001_spec_fields <= 0:
        recommended = "NEXT-007"
    elif perf001_spec_fields > 0 and not perf001_implemented:
        recommended = "NEXT-005"
    elif doc_check_count <= 0:
        recommended = "NEXT-008"
    elif not timeline_coverage_status:
        recommended = "NEXT-017"
    elif timeline_coverage_status == "no_local_timeline_files" and timeline_template_fields <= 0:
        recommended = "NEXT-018"
    elif timeline_coverage_status == "no_local_timeline_files" and timeline_template_fields > 0 and not timeline_validation_status:
        recommended = "NEXT-019"
    elif ui_plan_step_count <= 0:
        recommended = "NEXT-004"
    elif ui.get("offlineRisk") == "high" and ui_manifest_asset_count <= 0:
        recommended = "NEXT-009"
    elif ui.get("offlineRisk") == "high" and ui_manifest_asset_count > 0 and not ui_preflight_status:
        recommended = "NEXT-016"
    elif not direct_import_status:
        recommended = "NEXT-020"
    elif direct_import_status == "repo_root_import_guards_ok" and not direct_cli_status:
        recommended = "NEXT-021"
    elif direct_cli_status == "direct_cli_help_ok" and not test_coverage_status:
        recommended = "NEXT-022"
    elif label_completion_candidate_csv_count > 0 and not label_cycle_status:
        recommended = "NEXT-023"
    else:
        recommended = "NEXT-005"
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "autonomous_progress_chain",
        "inputPaths": {key: str(value) if value else "" for key, value in (input_paths or {}).items()},
        "summary": {
            "benchmarkRows": benchmark.get("rowCount", 0),
            "benchmarkLabelTemplateRows": labeling.get("labelTemplateRowCount", 0),
            "benchmarkLabelReadinessStatus": label_readiness.get("readinessStatus", "unknown"),
            "benchmarkUsableLabeledRows": label_readiness.get("usableLabeledRows", 0),
            "benchmarkLabelPriorityQueueRows": label_priority.get("queueRowCount", 0),
            "benchmarkLabelPriorityTemplateRows": label_template.get("templateRowCount", 0),
            "benchmarkLabelHandoffRows": label_handoff.get("queueRowCount", 0),
            "benchmarkLabelWorksheetRows": label_worksheet.get("worksheetRowCount", 0),
            "benchmarkLabelActionPackPresent": label_action_pack_present,
            "benchmarkLabelActionPackHumanActionRequired": label_action_pack.get("humanActionRequired", True),
            "benchmarkLabelCsvPreflightStatus": label_preflight.get("preflightStatus", "unknown"),
            "benchmarkLabelCompletionStatus": label_completion.get("selectedCompletionStatus", "unknown"),
            "benchmarkLabelCompletionUsableRows": label_completion.get("selectedUsableLabelRows", 0),
            "benchmarkLabelExpectationStatus": label_expectation.get("expectationStatus", "unknown"),
            "benchmarkLabelExpectationUsableRows": label_expectation.get("usableLabeledRows", 0),
            "benchmarkLabelCycleStatus": label_cycle.get("cycleStatus", "missing"),
            "benchmarkLabelCycleUsableRows": label_cycle.get("usableLabeledRows", 0),
            "performanceRunsInspected": performance.get("runCount", 0),
            "performanceSlowRunsOver120s": performance.get("slowRunCountOver120s", 0),
            "performanceRfcProposalCount": performance_rfc.get("proposalCount", 0),
            "tradeCollectionProfileRuns": trade_profile.get("runCount", 0),
            "tradeCollectionProfileTruncatedRuns": trade_profile.get("truncatedRunCount", 0),
            "perf001ProgressSpecProposedFields": perf001_spec.get("proposedFieldCount", 0),
            "perf001ImplementationReportPresent": perf001_implemented,
            "scopeSingleMarketSiblingContextCount": scope_audit.get("singleMarketWithSiblingContextCount", 0),
            "archiveDocDriftObserved": doc_drift.get("driftObservedCount", 0),
            "offlineTimelineCoverageStatus": timeline_audit.get("coverageStatus", "missing"),
            "offlineTimelineFileCount": timeline_audit.get("existingTimelineFileCount", 0),
            "offlineTimelineMatchedRows": timeline_audit.get("offlineTimelineMatchedYesCount", 0),
            "offlineTimelineTemplateFieldCount": timeline_template.get("templateFieldCount", 0),
            "offlineTimelineTemplateRowsPreFilled": timeline_template.get("templateRowsPreFilled", 0),
            "offlineTimelineCsvValidationStatus": timeline_validation.get("validationStatus", "missing"),
            "offlineTimelineCsvValidApprovedRows": timeline_validation.get("validApprovedRowCount", 0),
            "uiOfflineRisk": ui.get("offlineRisk", "unknown"),
            "uiOfflinePlanStepCount": ui_plan.get("planStepCount", 0),
            "uiOfflineManifestAssetCount": ui_manifest.get("uniqueRuntimeAssetCount", 0),
            "uiOfflineManifestMissingAssetCount": ui_manifest.get("missingRuntimeAssetCount", 0),
            "uiOfflineImplementationPreflightStatus": ui_preflight.get("preflightStatus", "missing"),
            "uiOfflineImplementationPreflightMissingAssetCount": ui_preflight.get("missingRuntimeAssetCount", 0),
            "directScriptImportAuditStatus": direct_import_audit.get("directRunRiskStatus", "missing"),
            "directScriptImportMissingGuardTools": direct_import_audit.get("missingGuardToolCount", 0),
            "directScriptImportRepoRootImportTools": direct_import_audit.get("repoRootImportToolCount", 0),
            "directScriptCliSmokeAuditStatus": direct_cli_smoke_audit.get("directCliRiskStatus", "missing"),
            "directScriptCliSmokeHelpFailures": direct_cli_smoke_audit.get("helpFailureCount", 0),
            "directScriptCliSmokeHelpTimeouts": direct_cli_smoke_audit.get("helpTimeoutCount", 0),
            "testCoverageInventoryStatus": test_coverage_audit.get("coverageInventoryStatus", "missing"),
            "testCoverageHighPriorityAppModulesWithoutDirectReference": test_coverage_audit.get(
                "highPriorityAppModuleWithoutDirectTestReferenceCount", 0
            ),
            "readinessClassification": readiness.get("readinessClassification", "not_ready_corpus_too_cache_only"),
            "operatorRpcStatus": operator.get("configuration_status") or operator.get("operator_rpc_status") or "unknown",
            "operatorDecisionRequired": bool(operator.get("operator_decision_required", True)),
            "autonomousBranchSelectedBranch": branch_decision.get("selectedBranch", ""),
            "autonomousBranchReportPresent": bool(branch_decision.get("selectedBranch")),
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
        },
        "completedChainSteps": [
            "local_known_case_benchmark_scaffold",
            "benchmark_labeling_workbench",
            "benchmark_label_readiness_gate",
            "benchmark_label_priority_queue",
            "benchmark_label_priority_template",
            "benchmark_label_handoff_pack",
            "benchmark_label_worksheet",
            "benchmark_label_action_pack",
            "benchmark_label_csv_preflight",
            "benchmark_label_completion_status",
            "benchmark_label_expectation_report",
            "benchmark_label_cycle",
            "event_forensic_performance_audit",
            "event_forensic_performance_rfc",
            "event_forensic_trade_collection_profile",
            "event_forensic_perf001_progress_spec",
            "event_forensic_perf001_implementation_report",
            "event_forensic_scope_semantics_audit",
            "archive_visibility_doc_drift_audit",
            "offline_timeline_coverage_audit",
            "offline_timeline_template_pack",
            "offline_timeline_csv_validation",
            "ui_runtime_dependency_audit",
            "ui_offline_readiness_plan",
            "ui_offline_asset_manifest",
            "ui_offline_implementation_preflight",
            "direct_script_import_audit",
            "direct_script_cli_smoke_audit",
            "test_coverage_inventory_audit",
            "autonomous_branch_decision_report",
            "autonomous_progress_chain_summary",
        ],
        "nextPromptOptions": prompts,
        "recommendedNextPromptId": recommended,
        "stopConditions": [
            "Stop before changing detector scoring, gates, HER routing, funding eligibility, candidate admission, credentials, RPC URLs, or old saved outputs.",
            "Stop before using scaffold rows as labeled truth.",
            "Stop before running long validation without operator-approved RPC capacity.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Autonomous Progress Chain",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Benchmark rows: {summary.get('benchmarkRows', 0)}",
        f"- Benchmark label readiness: {summary.get('benchmarkLabelReadinessStatus', 'unknown')}",
        f"- Benchmark usable labeled rows: {summary.get('benchmarkUsableLabeledRows', 0)}",
        f"- Benchmark label priority queue rows: {summary.get('benchmarkLabelPriorityQueueRows', 0)}",
        f"- Benchmark label priority template rows: {summary.get('benchmarkLabelPriorityTemplateRows', 0)}",
        f"- Benchmark label handoff rows: {summary.get('benchmarkLabelHandoffRows', 0)}",
        f"- Benchmark label worksheet rows: {summary.get('benchmarkLabelWorksheetRows', 0)}",
        f"- Benchmark label action pack present: {summary.get('benchmarkLabelActionPackPresent', False)}",
        f"- Benchmark label CSV preflight: {summary.get('benchmarkLabelCsvPreflightStatus', 'unknown')}",
        f"- Benchmark label completion status: {summary.get('benchmarkLabelCompletionStatus', 'unknown')}",
        f"- Benchmark label expectation status: {summary.get('benchmarkLabelExpectationStatus', 'unknown')}",
        f"- Benchmark label cycle status: {summary.get('benchmarkLabelCycleStatus', 'unknown')}",
        f"- Performance runs inspected: {summary.get('performanceRunsInspected', 0)}",
        f"- Slow performance runs: {summary.get('performanceSlowRunsOver120s', 0)}",
        f"- Trade collection profile runs: {summary.get('tradeCollectionProfileRuns', 0)}",
        f"- Trade collection truncated runs: {summary.get('tradeCollectionProfileTruncatedRuns', 0)}",
        f"- PERF-001 proposed fields: {summary.get('perf001ProgressSpecProposedFields', 0)}",
        f"- PERF-001 implementation report present: {summary.get('perf001ImplementationReportPresent', False)}",
        f"- Archive doc drift observed: {summary.get('archiveDocDriftObserved', 0)}",
        f"- Offline timeline coverage: {summary.get('offlineTimelineCoverageStatus', '')}",
        f"- Offline timeline template fields: {summary.get('offlineTimelineTemplateFieldCount', 0)}",
        f"- Offline timeline CSV validation: {summary.get('offlineTimelineCsvValidationStatus', '')}",
        f"- UI offline risk: {summary.get('uiOfflineRisk', '')}",
        f"- UI offline manifest assets: {summary.get('uiOfflineManifestAssetCount', 0)}",
        f"- UI offline implementation preflight: {summary.get('uiOfflineImplementationPreflightStatus', '')}",
        f"- Direct script import audit: {summary.get('directScriptImportAuditStatus', '')}",
        f"- Direct script missing guards: {summary.get('directScriptImportMissingGuardTools', 0)}",
        f"- Direct CLI smoke audit: {summary.get('directScriptCliSmokeAuditStatus', '')}",
        f"- Direct CLI smoke failures/timeouts: {summary.get('directScriptCliSmokeHelpFailures', 0)}/{summary.get('directScriptCliSmokeHelpTimeouts', 0)}",
        f"- Test coverage inventory: {summary.get('testCoverageInventoryStatus', '')}",
        f"- High-priority app modules without direct references: {summary.get('testCoverageHighPriorityAppModulesWithoutDirectReference', 0)}",
        f"- Autonomous branch selected: {summary.get('autonomousBranchSelectedBranch', '')}",
        f"- Readiness: {summary.get('readinessClassification', '')}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Next Prompt Options",
    ]
    for item in payload.get("nextPromptOptions") or []:
        if isinstance(item, Mapping):
            lines.append(f"- `{item.get('promptId', '')}` {item.get('title', '')}: {item.get('prompt', '')}")
    lines.extend(["", "## Stop Conditions"])
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"autonomous_progress_chain_{stamp}.json"
    markdown_path = resolved / f"autonomous_progress_chain_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize safe autonomous progress chain outputs.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    paths = discover_inputs()
    payloads = {name: _load_json(path) for name, path in paths.items()}
    payload = build_chain(payloads, input_paths=paths)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Autonomous progress chain JSON: {outputs['json_path']}")
    print(f"Autonomous progress chain markdown: {outputs['markdown_path']}")
    print(f"Recommended next prompt: {payload.get('recommendedNextPromptId', '')}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
