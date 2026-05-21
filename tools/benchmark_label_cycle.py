from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import benchmark_label_schema as label_schema  # noqa: E402
from tools.benchmark_label_action_pack import (  # noqa: E402
    build_action_pack,
    discover_inputs as discover_action_inputs,
    write_outputs as write_action_outputs,
)
from tools.benchmark_label_completion_status import build_status, write_outputs as write_completion_outputs  # noqa: E402
from tools.benchmark_label_csv_preflight import build_preflight, write_outputs as write_preflight_outputs  # noqa: E402
from tools.benchmark_label_expectation_report import (  # noqa: E402
    build_expectation_report,
    write_outputs as write_expectation_outputs,
)
from tools.benchmark_label_readiness_gate import build_readiness, write_outputs as write_readiness_outputs  # noqa: E402


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
    resolved = _resolve(path)
    if not resolved or not resolved.exists():
        return {}
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("summary")
    return value if isinstance(value, Mapping) else {}


def _selected_csv(completion_payload: Mapping[str, Any], labels_csv_path: Path | None, template_csv_path: Path | None) -> Path | None:
    if labels_csv_path is not None:
        return labels_csv_path
    summary = _summary(completion_payload)
    selected = str(summary.get("selectedLabelsCsvPath") or "").strip()
    if selected:
        return Path(selected)
    return template_csv_path


def _cycle_status(
    completion_summary: Mapping[str, Any],
    preflight_summary: Mapping[str, Any],
    readiness_summary: Mapping[str, Any],
    expectation_summary: Mapping[str, Any],
) -> str:
    if readiness_summary.get("readinessStatus") == "ready_for_reporting_regression_only":
        return "ready_for_reporting_regression_only"
    if (
        preflight_summary.get("preflightStatus") == "structure_ok_draft_assisted_only"
        or readiness_summary.get("readinessStatus") == "draft_assisted_only_not_human_valid"
        or expectation_summary.get("expectationStatus") == "draft_assisted_only_not_human_evidence"
    ):
        return "draft_assisted_only_not_human_valid"
    if int(preflight_summary.get("usableLabelRows") or 0) > 0 or int(readiness_summary.get("usableLabeledRows") or 0) > 0:
        return "human_labels_present_but_not_ready"
    if completion_summary.get("selectedCompletionStatus") in {"missing", ""}:
        return "missing_label_csv_inputs"
    if expectation_summary.get("expectationStatus") == "no_human_labels_available":
        return "waiting_for_human_labels"
    return "waiting_for_human_labels"


def build_cycle(
    *,
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    template_csv_path: Path | None = None,
    labels_csv_path: Path | None = None,
    workbench_path: Path | None = None,
    min_usable_labels: int = 12,
) -> dict[str, Any]:
    template_csv = template_csv_path or _latest_file(input_dir, "benchmark_label_priority_template_*.csv")
    workbench = workbench_path or _latest_file(input_dir, "benchmark_labeling_workbench_*.json")

    completion_payload = build_status(input_dir=input_dir, labels_csv_path=labels_csv_path)
    completion_outputs = write_completion_outputs(completion_payload, output_dir)
    selected_labels_csv = _selected_csv(completion_payload, labels_csv_path, template_csv)

    labels_schema = label_schema.detect_csv_schema(_resolve(selected_labels_csv) if selected_labels_csv else None)
    effective_template_csv = (
        selected_labels_csv
        if labels_schema.get("candidateSchemaType") == label_schema.SCHEMA_CASE_LEVEL_BENCHMARK
        and template_csv_path is None
        else template_csv
    )

    preflight_payload = build_preflight(template_csv_path=effective_template_csv, labels_csv_path=selected_labels_csv)
    preflight_outputs = write_preflight_outputs(preflight_payload, output_dir)

    readiness_payload = build_readiness(
        _load_json(workbench),
        source_path=workbench,
        labels_csv_path=selected_labels_csv,
        min_usable_labels=min_usable_labels,
    )
    readiness_outputs = write_readiness_outputs(readiness_payload, output_dir)

    expectation_payload = build_expectation_report(
        _load_json(workbench),
        source_path=workbench,
        labels_csv_path=selected_labels_csv,
        preflight_payload=preflight_payload,
        readiness_payload=readiness_payload,
    )
    expectation_outputs = write_expectation_outputs(expectation_payload, output_dir)

    action_paths = discover_action_inputs(input_dir)
    action_payloads = {key: _load_json(path) for key, path in action_paths.items()}
    action_payload = build_action_pack(action_payloads, input_paths=action_paths)
    action_outputs = write_action_outputs(action_payload, output_dir)

    completion_summary = _summary(completion_payload)
    preflight_summary = _summary(preflight_payload)
    readiness_summary = _summary(readiness_payload)
    expectation_summary = _summary(expectation_payload)
    action_summary = _summary(action_payload)
    status = _cycle_status(completion_summary, preflight_summary, readiness_summary, expectation_summary)
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_label_cycle",
        "sourceTemplateCsvPath": str(template_csv or ""),
        "sourceLabelsCsvPath": str(selected_labels_csv or ""),
        "sourceWorkbenchPath": str(workbench or ""),
        "componentArtifacts": {
            "completionStatus": completion_outputs,
            "csvPreflight": preflight_outputs,
            "readinessGate": readiness_outputs,
            "expectationReport": expectation_outputs,
            "actionPack": action_outputs,
        },
        "summary": {
            "cycleStatus": status,
            "schemaType": preflight_summary.get("schemaType", labels_schema.get("schemaType", "")),
            "selectedLabelsCsvPath": str(selected_labels_csv or ""),
            "templateCsvPath": str(effective_template_csv or ""),
            "completionStatus": completion_summary.get("selectedCompletionStatus", "unknown"),
            "preflightStatus": preflight_summary.get("preflightStatus", "unknown"),
            "readinessStatus": readiness_summary.get("readinessStatus", "unknown"),
            "expectationStatus": expectation_summary.get("expectationStatus", "unknown"),
            "usableLabeledRows": readiness_summary.get("usableLabeledRows", 0),
            "finalHumanUsableLabelRows": readiness_summary.get("finalHumanUsableLabelRows", readiness_summary.get("usableLabeledRows", 0)),
            "draftAssistedLabelRows": readiness_summary.get("draftAssistedLabelRows", preflight_summary.get("draftAssistedLabelRows", 0)),
            "draftAssistedLabelsCountedUsable": False,
            "invalidLabelRows": readiness_summary.get("invalidLabelRows", 0),
            "missingRequiredLabelRows": readiness_summary.get("missingRequiredLabelRows", 0),
            "humanActionRequired": action_summary.get("humanActionRequired", True) or status == "draft_assisted_only_not_human_valid",
            "labelsAssignedByThisTool": 0,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "nextHumanAction": (
            "Draft-assisted rows require human finalization before benchmark use."
            if status == "draft_assisted_only_not_human_valid"
            else
            "Use the action pack and worksheet to fill the selected CSV, then rerun this cycle."
            if status != "ready_for_reporting_regression_only"
            else "Use the expectation report for reporting-only regression analysis. Do not implement detector changes from labels alone."
        ),
        "readyToCopyCommand": (
            f"python3 tools/benchmark_label_cycle.py --labels-csv \"{selected_labels_csv}\""
            if selected_labels_csv
            else "python3 tools/benchmark_label_cycle.py"
        ),
        "stopConditions": [
            "Do not infer or auto-fill human labels.",
            "Do not treat DRAFT_ASSISTED_NOT_FINAL rows as final human labels.",
            "Do not treat blank templates as analyst truth.",
            "Do not use human labels to change scoring, gates, HER routing, funding eligibility, candidate admission, or production labels.",
            "Do not overclaim cache-only or saved-output labels as fresh trace-enabled validation.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Benchmark Label Cycle",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Cycle status: `{summary.get('cycleStatus', '')}`",
        f"- Schema type: `{summary.get('schemaType', '')}`",
        f"- Template CSV: {summary.get('templateCsvPath', '')}",
        f"- Selected labels CSV: {summary.get('selectedLabelsCsvPath', '')}",
        f"- Completion status: `{summary.get('completionStatus', '')}`",
        f"- Preflight status: `{summary.get('preflightStatus', '')}`",
        f"- Readiness status: `{summary.get('readinessStatus', '')}`",
        f"- Expectation status: `{summary.get('expectationStatus', '')}`",
        f"- Usable labels: {summary.get('usableLabeledRows', 0)}",
        f"- Draft-assisted labels: {summary.get('draftAssistedLabelRows', 0)}",
        f"- Draft-assisted labels counted usable: {summary.get('draftAssistedLabelsCountedUsable', False)}",
        f"- Invalid labels: {summary.get('invalidLabelRows', 0)}",
        f"- Human action required: {summary.get('humanActionRequired', True)}",
        f"- Labels assigned by this tool: {summary.get('labelsAssignedByThisTool', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Component Artifacts",
    ]
    artifacts = payload.get("componentArtifacts") if isinstance(payload.get("componentArtifacts"), Mapping) else {}
    for name, paths in artifacts.items():
        if isinstance(paths, Mapping):
            lines.append(f"- {name}: {paths.get('json_path', '')}")
            if paths.get("markdown_path"):
                lines.append(f"  - markdown: {paths.get('markdown_path', '')}")
    lines.extend(
        [
            "",
            "## Next Human Action",
            "",
            str(payload.get("nextHumanAction", "")),
            "",
            "## Ready-To-Copy Command",
            "",
            "```bash",
            str(payload.get("readyToCopyCommand", "")),
            "```",
            "",
            "## Stop Conditions",
        ]
    )
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"benchmark_label_cycle_{stamp}.json"
    markdown_path = resolved / f"benchmark_label_cycle_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the full reporting-only benchmark label workflow cycle.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--template-csv", type=Path, default=None)
    parser.add_argument("--labels-csv", type=Path, default=None)
    parser.add_argument("--workbench", type=Path, default=None)
    parser.add_argument("--min-usable-labels", type=int, default=12)
    args = parser.parse_args(argv)
    payload = build_cycle(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        template_csv_path=args.template_csv,
        labels_csv_path=args.labels_csv,
        workbench_path=args.workbench,
        min_usable_labels=args.min_usable_labels,
    )
    outputs = write_outputs(payload, args.output_dir)
    summary = payload.get("summary", {})
    print(f"Benchmark label cycle JSON: {outputs['json_path']}")
    print(f"Benchmark label cycle markdown: {outputs['markdown_path']}")
    print(f"Cycle status: {summary.get('cycleStatus', '')}")
    print(f"Usable labels: {summary.get('usableLabeledRows', 0)}")
    print(f"Human action required: {summary.get('humanActionRequired', True)}")
    print(f"Model behavior changed: {summary.get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
