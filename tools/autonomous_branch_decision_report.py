from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("autonomous_branch_outputs")
INPUT_PATTERNS = {
    "autonomous_progress_chain": (Path("autonomous_progress_outputs"), "autonomous_progress_chain_*.json"),
    "review_output_index": (Path("review_index_outputs"), "review_output_index_*.json"),
    "operator_rpc_recovery_package": (Path("validation_corpus_outputs"), "operator_rpc_capacity_recovery_package_*.json"),
    "gate_decision_readiness": (Path("validation_corpus_outputs"), "gate_decision_readiness_*.json"),
    "benchmark_label_priority_queue": (Path("known_case_benchmarks"), "benchmark_label_priority_queue_*.json"),
    "benchmark_label_priority_template": (Path("known_case_benchmarks"), "benchmark_label_priority_template_*.json"),
    "benchmark_label_worksheet": (Path("known_case_benchmarks"), "benchmark_label_worksheet_*.json"),
    "benchmark_label_action_pack": (Path("known_case_benchmarks"), "benchmark_label_action_pack_*.json"),
    "benchmark_label_csv_preflight": (Path("known_case_benchmarks"), "benchmark_label_csv_preflight_*.json"),
    "benchmark_label_completion_status": (Path("known_case_benchmarks"), "benchmark_label_completion_status_*.json"),
    "benchmark_label_expectation_report": (Path("known_case_benchmarks"), "benchmark_label_expectation_report_*.json"),
    "benchmark_label_readiness": (Path("known_case_benchmarks"), "benchmark_label_readiness_*.json"),
    "ui_offline_asset_manifest": (Path("ui_readiness_outputs"), "ui_offline_asset_manifest_*.json"),
    "ui_offline_implementation_preflight": (Path("ui_readiness_outputs"), "ui_offline_implementation_preflight_*.json"),
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


def _readiness_classification(readiness: Mapping[str, Any], progress_summary: Mapping[str, Any]) -> str:
    return str(
        readiness.get("readinessClassification")
        or readiness.get("classification")
        or progress_summary.get("readinessClassification")
        or "unknown"
    )


def _operator_status(operator: Mapping[str, Any], progress_summary: Mapping[str, Any]) -> str:
    return str(
        operator.get("configuration_status")
        or operator.get("operator_rpc_status")
        or progress_summary.get("operatorRpcStatus")
        or "unknown"
    )


def _branch(
    *,
    branch_id: str,
    title: str,
    status: str,
    blocked: bool,
    requires_human_action: bool,
    why: str,
    next_prompt: str,
) -> dict[str, Any]:
    return {
        "branchId": branch_id,
        "title": title,
        "status": status,
        "blocked": blocked,
        "requiresHumanAction": requires_human_action,
        "why": why,
        "nextPrompt": next_prompt,
        "modelBehaviorChanged": False,
    }


def build_report(
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    input_paths: Mapping[str, Path | None] | None = None,
) -> dict[str, Any]:
    progress_summary = _summary(payloads.get("autonomous_progress_chain", {}))
    readiness_payload = payloads.get("gate_decision_readiness", {})
    operator_payload = payloads.get("operator_rpc_recovery_package", {})
    queue_summary = _summary(payloads.get("benchmark_label_priority_queue", {}))
    template_summary = _summary(payloads.get("benchmark_label_priority_template", {}))
    worksheet_summary = _summary(payloads.get("benchmark_label_worksheet", {}))
    action_pack_summary = _summary(payloads.get("benchmark_label_action_pack", {}))
    preflight_summary = _summary(payloads.get("benchmark_label_csv_preflight", {}))
    completion_summary = _summary(payloads.get("benchmark_label_completion_status", {}))
    expectation_summary = _summary(payloads.get("benchmark_label_expectation_report", {}))
    label_summary = _summary(payloads.get("benchmark_label_readiness", {}))
    ui_summary = _summary(payloads.get("ui_offline_asset_manifest", {}))
    ui_preflight_summary = _summary(payloads.get("ui_offline_implementation_preflight", {}))
    readiness = _readiness_classification(readiness_payload, progress_summary)
    recommendation = str(readiness_payload.get("recommendation") or operator_payload.get("recommendation") or "")
    operator_status = _operator_status(operator_payload, progress_summary)
    operator_decision_required = bool(operator_payload.get("operator_decision_required", progress_summary.get("operatorDecisionRequired", True)))
    queue_rows = int(queue_summary.get("queueRowCount") or 0)
    template_rows = int(template_summary.get("templateRowCount") or 0)
    worksheet_rows = int(worksheet_summary.get("worksheetRowCount") or 0)
    action_pack_present = bool(action_pack_summary.get("humanActionRequired") is not None)
    preflight_status = str(preflight_summary.get("preflightStatus") or "unknown")
    completion_status = str(completion_summary.get("selectedCompletionStatus") or "unknown")
    expectation_status = str(expectation_summary.get("expectationStatus") or "unknown")
    completion_usable = int(completion_summary.get("selectedUsableLabelRows") or 0)
    usable_labels = int(label_summary.get("usableLabeledRows") or progress_summary.get("benchmarkUsableLabeledRows") or 0)
    ui_missing_assets = int(ui_summary.get("missingRuntimeAssetCount") or progress_summary.get("uiOfflineManifestMissingAssetCount") or 0)
    ui_preflight_status = str(
        ui_preflight_summary.get("preflightStatus")
        or progress_summary.get("uiOfflineImplementationPreflightStatus")
        or "missing"
    )
    ui_preflight_missing_assets = int(
        ui_preflight_summary.get("missingRuntimeAssetCount")
        or progress_summary.get("uiOfflineImplementationPreflightMissingAssetCount")
        or ui_missing_assets
        or 0
    )
    ui_runtime_changed = bool(ui_summary.get("uiRuntimeChanged"))
    operator_config_present = operator_status not in {
        "",
        "unknown",
        "existing_env_config_rechecked_no_new_operator_approved_rpc_configuration_detected",
        "no_new_operator_rpc_config_detected",
    }
    branches = [
        _branch(
            branch_id="operator_rpc_recovery",
            title="Operator-approved RPC recovery",
            status="ready_to_probe" if operator_config_present else "blocked_waiting_operator_rpc_config",
            blocked=not operator_config_present,
            requires_human_action=not operator_config_present,
            why=(
                "Operator-approved RPC configuration appears present; use bounded recovery ladder only."
                if operator_config_present
                else "Readiness remains cache-only and no new operator-approved RPC configuration is detected."
            ),
            next_prompt=(
                "Run funding healthcheck, trace diagnostic, 3-target network probe, prewarm, 12-target auto-policy smoke, "
                "readiness, and autonomous next action. Do not run 48 targets until 12-target smoke clears cache-only status."
            ),
        ),
        _branch(
            branch_id="human_benchmark_labeling",
            title="Human-label benchmark priority queue",
            status="ready_for_human_labeling" if queue_rows > 0 and usable_labels <= 0 else "labels_available_or_queue_missing",
            blocked=queue_rows <= 0,
            requires_human_action=True,
            why=(
                f"{queue_rows} priority rows, {template_rows} readiness-gate template rows, and {worksheet_rows} worksheet rows are ready for human labeling; usable labels are still {usable_labels}; completion status is {completion_status}."
                if queue_rows > 0
                else "No benchmark priority queue is available yet."
            ),
            next_prompt=(
                "Open known_case_benchmarks/benchmark_label_worksheet_*.md for row context, then fill "
                "known_case_benchmarks/benchmark_label_priority_template_*.csv manually. "
                "The latest benchmark_label_action_pack_*.md gives the file list and commands. "
                "Then rerun benchmark label readiness with the human-edited CSV. Do not use labels as production truth."
            ),
        ),
        _branch(
            branch_id="ui_offline_implementation",
            title="UI offline implementation from manifest",
            status="requires_explicit_ui_runtime_approval" if ui_missing_assets > 0 and not ui_runtime_changed else "not_needed_or_already_changed",
            blocked=ui_missing_assets > 0,
            requires_human_action=ui_missing_assets > 0,
            why=(
                f"UI offline manifest/preflight shows {ui_preflight_missing_assets} missing runtime assets; preflight status is {ui_preflight_status}; manifest generation did not change runtime behavior."
                if ui_missing_assets > 0
                else "UI manifest does not show missing runtime assets."
            ),
            next_prompt=(
                "If explicitly approved, vendor only manifest-listed public UI boot assets and add fallback loading. "
                "Do not change detector behavior or Python report payload contracts."
            ),
        ),
        _branch(
            branch_id="rfc_only_detector_review",
            title="RFC-only detector review",
            status="available_but_human_approval_required",
            blocked=False,
            requires_human_action=True,
            why="Detector-behavior ideas must remain RFC-only until fresh validation and explicit approval exist.",
            next_prompt=(
                "Draft or update an RFC-only detector review. Do not implement model, scoring, gate, HER, funding, "
                "candidate-admission, or threshold changes."
            ),
        ),
        _branch(
            branch_id="refresh_governance_only",
            title="Refresh governance artifacts only",
            status="always_safe_low_value",
            blocked=False,
            requires_human_action=False,
            why="Safe when no branch input exists, but it should not be repeated as fake progress.",
            next_prompt="Regenerate review output index, autonomous progress chain, and this branch report only.",
        ),
    ]
    if operator_config_present:
        selected = "operator_rpc_recovery"
    elif queue_rows > 0 and usable_labels <= 0:
        selected = "human_benchmark_labeling"
    elif ui_missing_assets > 0 and not ui_runtime_changed:
        selected = "ui_offline_implementation_requires_approval"
    else:
        selected = "refresh_governance_only"
    next_prompt = _ready_prompt(selected)
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "autonomous_branch_decision_report",
        "inputPaths": {key: str(value) if value else "" for key, value in (input_paths or {}).items()},
        "summary": {
            "selectedBranch": selected,
            "readinessClassification": readiness,
            "recommendation": recommendation,
            "operatorRpcStatus": operator_status,
            "operatorDecisionRequired": operator_decision_required,
            "benchmarkPriorityQueueRows": queue_rows,
            "benchmarkPriorityTemplateRows": template_rows,
            "benchmarkLabelWorksheetRows": worksheet_rows,
            "benchmarkLabelActionPackPresent": action_pack_present,
            "benchmarkLabelCsvPreflightStatus": preflight_status,
            "benchmarkLabelCompletionStatus": completion_status,
            "benchmarkLabelExpectationStatus": expectation_status,
            "benchmarkLabelCompletionUsableRows": completion_usable,
            "benchmarkUsableLabeledRows": usable_labels,
            "uiOfflineMissingRuntimeAssetCount": ui_missing_assets,
            "uiOfflineImplementationPreflightStatus": ui_preflight_status,
            "uiOfflineImplementationPreflightMissingAssetCount": ui_preflight_missing_assets,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "branchOptions": branches,
        "selectedNextPrompt": next_prompt,
        "stopConditions": [
            "Stop before changing model/scoring/gates/HER/funding/candidate-admission behavior.",
            "Stop before running long validation without new operator-approved RPC capacity.",
            "Stop before treating benchmark queue rows as human labels.",
            "Stop before vendoring UI assets without explicit UI runtime implementation approval.",
        ],
    }


def _ready_prompt(selected: str) -> str:
    common = (
        "Hard constraints: do not edit _score_trade(); do not change Strong Risk gates, scoring weights, severity labels, "
        "HER routing, funding eligibility, candidate admission, structural eligibility, suspicious funding v2, credentials, "
        "RPC URLs, or old saved outputs. Do not overclaim cache-only evidence."
    )
    if selected == "operator_rpc_recovery":
        task = (
            "Use only existing env/config RPC mechanisms. Run bounded recovery: healthcheck, trace diagnostic, "
            "3-target network probe, prewarm, 12-target auto-policy smoke, readiness, autonomous next action. "
            "Stop before a 48-target run unless the 12-target smoke clears cache-only status."
        )
    elif selected == "human_benchmark_labeling":
        task = (
            "Open the latest known_case_benchmarks/benchmark_label_worksheet_*.md for row context, then open the latest "
            "known_case_benchmarks/benchmark_label_priority_template_*.csv and have a human fill labels "
            "for expectedAnalystDisposition, humanLabelConfidence, false-positive/insider-style reasons, and notes. "
            "Use the latest known_case_benchmarks/benchmark_label_action_pack_*.md for the exact files and commands. "
            "Then rerun benchmark label readiness against the human-edited CSV and generate reporting-only summaries."
        )
    elif selected == "ui_offline_implementation_requires_approval":
        task = (
            "If and only if a maintainer explicitly approves UI runtime implementation, use the latest "
            "ui_readiness_outputs/ui_offline_implementation_preflight_*.json and ui_offline_asset_manifest_*.json "
            "to vendor only listed UI boot assets and add fallback loading. "
            "Otherwise refresh governance artifacts only."
        )
    else:
        task = (
            "Refresh review_output_index, autonomous_progress_chain, and autonomous_branch_decision_report. "
            "Do not repeat RPC smoke loops or create new detector-change work without branch input."
        )
    return (
        "You are working in the InsPoly repository as an autonomous validation/workflow engineer. "
        f"{common} Task: {task} Verification: run py_compile for touched files, run "
        "python3 -m unittest discover -s tests -p 'test_*.py', and validate generated JSON. "
        "Final output: branch chosen, artifacts read/written, tests, readiness/RPC status, invariants preserved, and next prompt."
    )


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Autonomous Branch Decision Report",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Selected branch: `{summary.get('selectedBranch', '')}`",
        f"- Readiness: `{summary.get('readinessClassification', '')}`",
        f"- Recommendation: `{summary.get('recommendation', '')}`",
        f"- Operator RPC status: `{summary.get('operatorRpcStatus', '')}`",
        f"- Benchmark priority queue rows: {summary.get('benchmarkPriorityQueueRows', 0)}",
        f"- Benchmark priority template rows: {summary.get('benchmarkPriorityTemplateRows', 0)}",
        f"- Benchmark label completion status: `{summary.get('benchmarkLabelCompletionStatus', '')}`",
        f"- Benchmark usable labels: {summary.get('benchmarkUsableLabeledRows', 0)}",
        f"- UI missing runtime assets: {summary.get('uiOfflineMissingRuntimeAssetCount', 0)}",
        f"- UI offline preflight: `{summary.get('uiOfflineImplementationPreflightStatus', '')}`",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Branch Options",
    ]
    for branch in payload.get("branchOptions") or []:
        if isinstance(branch, Mapping):
            lines.append(
                f"- `{branch.get('branchId', '')}` status={branch.get('status', '')} "
                f"blocked={branch.get('blocked', False)}: {branch.get('why', '')}"
            )
    lines.extend(["", "## Selected Next Prompt", "", str(payload.get("selectedNextPrompt", "")), "", "## Stop Conditions"])
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"autonomous_branch_decision_report_{stamp}.json"
    markdown_path = resolved / f"autonomous_branch_decision_report_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a deterministic branch-decision report for the current InsPoly safe chain.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    paths = discover_inputs()
    payloads = {name: _load_json(path) for name, path in paths.items()}
    payload = build_report(payloads, input_paths=paths)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Autonomous branch decision JSON: {outputs['json_path']}")
    print(f"Autonomous branch decision markdown: {outputs['markdown_path']}")
    print(f"Selected branch: {payload.get('summary', {}).get('selectedBranch', '')}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
