from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = Path("known_case_benchmarks")
DEFAULT_OUTPUT_DIR = Path("known_case_benchmarks")


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


def _summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("summary")
    return value if isinstance(value, Mapping) else {}


def _sibling(path: Path | None, suffix: str) -> str:
    if not path:
        return ""
    sibling = path.with_suffix(suffix)
    return str(sibling) if sibling.exists() else ""


def discover_inputs(input_dir: Path = DEFAULT_INPUT_DIR) -> dict[str, Path | None]:
    return {
        "priorityTemplateJson": _latest_file(input_dir, "benchmark_label_priority_template_*.json"),
        "worksheetJson": _latest_file(input_dir, "benchmark_label_worksheet_*.json"),
        "handoffJson": _latest_file(input_dir, "benchmark_label_handoff_pack_*.json"),
        "csvPreflightJson": _latest_file(input_dir, "benchmark_label_csv_preflight_*.json"),
        "completionStatusJson": _latest_file(input_dir, "benchmark_label_completion_status_*.json"),
        "readinessJson": _latest_file(input_dir, "benchmark_label_readiness_*.json"),
        "expectationReportJson": _latest_file(input_dir, "benchmark_label_expectation_report_*.json"),
    }


def build_action_pack(
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    input_paths: Mapping[str, Path | None] | None = None,
) -> dict[str, Any]:
    paths = input_paths or {}
    template_summary = _summary(payloads.get("priorityTemplateJson", {}))
    worksheet_summary = _summary(payloads.get("worksheetJson", {}))
    handoff_summary = _summary(payloads.get("handoffJson", {}))
    preflight_summary = _summary(payloads.get("csvPreflightJson", {}))
    completion_summary = _summary(payloads.get("completionStatusJson", {}))
    readiness_summary = _summary(payloads.get("readinessJson", {}))
    expectation_summary = _summary(payloads.get("expectationReportJson", {}))
    template_payload = payloads.get("priorityTemplateJson", {})
    allowed_values = template_payload.get("allowedValues") if isinstance(template_payload.get("allowedValues"), Mapping) else {}
    template_json = paths.get("priorityTemplateJson")
    worksheet_json = paths.get("worksheetJson")
    completion_json = paths.get("completionStatusJson")
    selected_csv = str(completion_summary.get("selectedLabelsCsvPath") or _sibling(template_json, ".csv"))
    usable_labels = int(completion_summary.get("selectedUsableLabelRows") or readiness_summary.get("usableLabeledRows") or 0)
    invalid_labels = int(completion_summary.get("invalidLabelRows") or readiness_summary.get("invalidLabelRows") or 0)
    human_action_required = usable_labels <= 0 or invalid_labels > 0
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_label_action_pack",
        "inputPaths": {key: str(value) if value else "" for key, value in paths.items()},
        "summary": {
            "templateRowCount": template_summary.get("templateRowCount", 0),
            "worksheetRowCount": worksheet_summary.get("worksheetRowCount", 0),
            "handoffRowCount": handoff_summary.get("queueRowCount", 0),
            "completionStatus": completion_summary.get("selectedCompletionStatus", "unknown"),
            "csvPreflightStatus": preflight_summary.get("preflightStatus", "unknown"),
            "usableLabelRows": usable_labels,
            "invalidLabelRows": invalid_labels,
            "readinessStatus": readiness_summary.get("readinessStatus", "unknown"),
            "expectationStatus": expectation_summary.get("expectationStatus", "unknown"),
            "humanActionRequired": human_action_required,
            "labelsAssignedByThisTool": 0,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "filesToOpen": {
            "worksheetMarkdown": _sibling(worksheet_json, ".md"),
            "templateCsvToEdit": selected_csv,
            "templateJson": str(template_json or ""),
            "completionStatusMarkdown": _sibling(completion_json, ".md"),
        },
        "allowedValues": allowed_values,
        "manualSteps": [
            "Open worksheetMarkdown first and review row context.",
            "Open templateCsvToEdit and fill only label fields.",
            "Use expectedAnalystDisposition and humanLabelConfidence from allowedValues.",
            "Save the CSV under a clear human-edited name if preserving the blank template matters.",
            "Run the commandsAfterFilling in order.",
        ],
        "commandsAfterFilling": [
            "python3 tools/benchmark_label_csv_preflight.py",
            "python3 tools/benchmark_label_completion_status.py",
            f"python3 tools/benchmark_label_readiness_gate.py --labels-csv \"{selected_csv}\"",
            f"python3 tools/benchmark_label_expectation_report.py --labels-csv \"{selected_csv}\"",
            "python3 tools/autonomous_progress_chain.py",
            "python3 tools/autonomous_branch_decision_report.py",
            "python3 tools/review_output_index.py",
        ],
        "nextCodexPrompt": (
            "You are working in the InsPoly repository. Inspect the latest benchmark_label_action_pack_*.json, "
            "benchmark_label_completion_status_*.json, and benchmark_label_readiness_*.json. If a human-filled CSV "
            "has usable labels, run the readiness gate against that CSV and refresh progress/branch/index. If labels "
            "are still missing, report human action required. Do not infer labels or change detector behavior."
        ),
        "stopConditions": [
            "Do not infer labels automatically.",
            "Do not use labels as production truth.",
            "Do not change scoring, gates, HER routing, funding eligibility, candidate admission, credentials, RPC URLs, or old outputs.",
            "Do not treat saved-output/cache-only rows as fresh trace-enabled proof.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    files = payload.get("filesToOpen") if isinstance(payload.get("filesToOpen"), Mapping) else {}
    lines = [
        "# Benchmark Label Action Pack",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Template rows: {summary.get('templateRowCount', 0)}",
        f"- Worksheet rows: {summary.get('worksheetRowCount', 0)}",
        f"- Completion status: `{summary.get('completionStatus', 'unknown')}`",
        f"- CSV preflight status: `{summary.get('csvPreflightStatus', 'unknown')}`",
        f"- Usable label rows: {summary.get('usableLabelRows', 0)}",
        f"- Invalid label rows: {summary.get('invalidLabelRows', 0)}",
        f"- Readiness status: `{summary.get('readinessStatus', 'unknown')}`",
        f"- Expectation status: `{summary.get('expectationStatus', 'unknown')}`",
        f"- Human action required: {summary.get('humanActionRequired', True)}",
        f"- Labels assigned by this tool: {summary.get('labelsAssignedByThisTool', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Files To Open",
    ]
    for key, value in files.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Manual Steps"])
    for item in payload.get("manualSteps") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Commands After Filling"])
    for item in payload.get("commandsAfterFilling") or []:
        lines.append(f"- `{item}`")
    lines.extend(["", "## Next Codex Prompt", "", str(payload.get("nextCodexPrompt", "")), "", "## Stop Conditions"])
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"benchmark_label_action_pack_{stamp}.json"
    markdown_path = resolved / f"benchmark_label_action_pack_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create one operational action pack for human benchmark labeling.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    paths = discover_inputs(args.input_dir)
    payloads = {key: _load_json(path) for key, path in paths.items()}
    payload = build_action_pack(payloads, input_paths=paths)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Benchmark label action pack JSON: {outputs['json_path']}")
    print(f"Benchmark label action pack markdown: {outputs['markdown_path']}")
    print(f"Human action required: {payload.get('summary', {}).get('humanActionRequired', True)}")
    print(f"Labels assigned by this tool: {payload.get('summary', {}).get('labelsAssignedByThisTool', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
