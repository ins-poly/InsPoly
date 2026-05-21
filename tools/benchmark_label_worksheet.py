from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = Path("known_case_benchmarks")
DEFAULT_OUTPUT_DIR = Path("known_case_benchmarks")
LABEL_FIELDS = (
    "expectedAnalystDisposition",
    "expectedDetectorDisposition",
    "humanLabelConfidence",
    "humanFalsePositiveReason",
    "humanInsiderStyleReason",
    "freshValidationRequired",
    "notes",
)
DEFAULT_ALLOWED_VALUES = {
    "expectedAnalystDisposition": [
        "likely_false_positive",
        "plausible_insider_style",
        "needs_fresh_validation",
        "inconclusive",
        "reporting_only_control",
        "ignore_not_benchmark",
    ],
    "expectedDetectorDisposition": [
        "keep_current_behavior",
        "reporting_only_note",
        "rfc_only_review_candidate",
        "needs_fresh_validation_before_decision",
    ],
    "humanLabelConfidence": ["low", "medium", "high"],
    "freshValidationRequired": ["yes", "no"],
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


def _csv_path(path: Path | None) -> str:
    if not path:
        return ""
    csv_path = path.with_suffix(".csv")
    return str(csv_path) if csv_path.exists() else ""


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split("|") if part.strip()]
    return []


def _allowed_values(template_payload: Mapping[str, Any]) -> dict[str, list[str]]:
    values = template_payload.get("allowedValues")
    if not isinstance(values, Mapping):
        return {key: list(items) for key, items in DEFAULT_ALLOWED_VALUES.items()}
    resolved: dict[str, list[str]] = {}
    for key, defaults in DEFAULT_ALLOWED_VALUES.items():
        raw = values.get(key)
        if isinstance(raw, list):
            resolved[key] = [str(item) for item in raw if str(item).strip()]
        else:
            resolved[key] = list(defaults)
    return resolved


def _evidence_focus(row: Mapping[str, Any]) -> list[str]:
    source_type = str(row.get("sourceType") or "")
    reasons = " ".join(_list(row.get("priorityReasons"))).lower()
    focus = []
    if source_type == "unique_review_packet":
        focus.append("Review wallet-level packet fields before assigning a disposition.")
        focus.append("Separate why the row is suspicious from why it may be a false positive.")
    elif source_type == "event_forensic_run":
        focus.append("Treat this as event/run scope evidence, not as a single wallet truth label.")
        focus.append("Check whether truncation or count limitations affect the label.")
    else:
        focus.append("Use the source artifact and priority reasons before assigning a label.")
    if "strong risk" in reasons:
        focus.append("Check whether the Strong Risk evidence is live-detectable or only saved-output context.")
    if "her" in reasons or "hard evidence" in reasons:
        focus.append("Check whether hard-evidence routing is actually supported by saved fields.")
    if "truncated" in reasons:
        focus.append("Mark freshValidationRequired=yes when truncation limits confidence.")
    return focus


def build_worksheet(
    template_payload: Mapping[str, Any],
    *,
    source_path: Path | None = None,
    completion_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [dict(row) for row in template_payload.get("templateRows", []) if isinstance(row, Mapping)]
    allowed = _allowed_values(template_payload)
    completion_summary = (
        completion_payload.get("summary") if isinstance(completion_payload, Mapping) and isinstance(completion_payload.get("summary"), Mapping) else {}
    )
    worksheet_rows = []
    for row in rows:
        worksheet_rows.append(
            {
                "queueRank": row.get("queueRank", ""),
                "localCaseId": row.get("localCaseId", ""),
                "sourceType": row.get("sourceType", ""),
                "eventSlug": row.get("eventSlug", ""),
                "market": row.get("market", ""),
                "conditionId": row.get("conditionId", ""),
                "wallet": row.get("wallet", ""),
                "priorityClass": row.get("priorityClass", ""),
                "labelPriorityScore": row.get("labelPriorityScore", 0),
                "priorityReasons": _list(row.get("priorityReasons")),
                "recommendedHumanQuestion": row.get("recommendedHumanQuestion", ""),
                "evidenceFocus": _evidence_focus(row),
                "blankLabelFields": {field: row.get(field, "") for field in LABEL_FIELDS},
                "allowedAnalystDispositions": allowed.get("expectedAnalystDisposition", []),
                "allowedConfidenceValues": allowed.get("humanLabelConfidence", []),
                "sourceArtifact": row.get("sourceArtifact", ""),
                "modelBehaviorChanged": False,
            }
        )
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_label_worksheet",
        "sourcePriorityTemplatePath": str(source_path or ""),
        "sourcePriorityTemplateCsvPath": _csv_path(source_path),
        "sourceCompletionStatusPath": str(completion_payload.get("sourcePath", "") if isinstance(completion_payload, Mapping) else ""),
        "summary": {
            "worksheetRowCount": len(worksheet_rows),
            "highPriorityRowCount": sum(1 for row in worksheet_rows if row.get("priorityClass") == "high"),
            "packetRowCount": sum(1 for row in worksheet_rows if row.get("sourceType") == "unique_review_packet"),
            "eventRunRowCount": sum(1 for row in worksheet_rows if row.get("sourceType") == "event_forensic_run"),
            "labelsAssignedByThisTool": 0,
            "readinessGateCompatible": True,
            "completionStatusAtGeneration": completion_summary.get("selectedCompletionStatus", "unknown"),
            "usableLabelsAtGeneration": completion_summary.get("selectedUsableLabelRows", 0),
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "allowedValues": allowed,
        "humanWorkflow": [
            "Open the source priority template CSV and fill only the label fields.",
            "Use this worksheet to understand each row before editing the CSV.",
            "Run tools/benchmark_label_completion_status.py after saving the human-edited CSV.",
            "Run tools/benchmark_label_readiness_gate.py --labels-csv <human-edited-csv> only after labels are filled.",
        ],
        "worksheetRows": worksheet_rows,
        "stopConditions": [
            "Do not infer labels automatically.",
            "Do not edit localCaseId in the CSV.",
            "Do not use benchmark labels to change scoring, gates, HER routing, funding eligibility, or candidate admission.",
            "Do not treat saved-output/cache-only rows as fresh trace-enabled proof.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    allowed = payload.get("allowedValues") if isinstance(payload.get("allowedValues"), Mapping) else {}
    lines = [
        "# Benchmark Label Worksheet",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Worksheet rows: {summary.get('worksheetRowCount', 0)}",
        f"- High-priority rows: {summary.get('highPriorityRowCount', 0)}",
        f"- Packet rows: {summary.get('packetRowCount', 0)}",
        f"- Event-run rows: {summary.get('eventRunRowCount', 0)}",
        f"- Labels assigned by this tool: {summary.get('labelsAssignedByThisTool', 0)}",
        f"- Completion status at generation: {summary.get('completionStatusAtGeneration', 'unknown')}",
        f"- Source template CSV: {payload.get('sourcePriorityTemplateCsvPath', '')}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Allowed Values",
    ]
    for field, values in allowed.items():
        if isinstance(values, list):
            lines.append(f"- `{field}`: {', '.join(str(value) for value in values)}")
    lines.extend(["", "## Human Workflow"])
    for item in payload.get("humanWorkflow") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Worksheet Rows"])
    for row in payload.get("worksheetRows") or []:
        if not isinstance(row, Mapping):
            continue
        label = row.get("eventSlug") or row.get("market") or "unknown"
        lines.append(
            f"- #{row.get('queueRank', '')} `{row.get('localCaseId', '')}` "
            f"{row.get('priorityClass', '')} score={row.get('labelPriorityScore', 0)}: "
            f"{label} / {row.get('wallet') or 'event-run'}"
        )
        focus = row.get("evidenceFocus") if isinstance(row.get("evidenceFocus"), list) else []
        for item in focus[:2]:
            lines.append(f"  - inspect: {item}")
    lines.extend(["", "## Stop Conditions"])
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"benchmark_label_worksheet_{stamp}.json"
    markdown_path = resolved / f"benchmark_label_worksheet_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a human worksheet for benchmark label priority template rows.")
    parser.add_argument("--template", type=Path, default=None)
    parser.add_argument("--completion-status", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    template = args.template or _latest_file(DEFAULT_INPUT_DIR, "benchmark_label_priority_template_*.json")
    completion = args.completion_status or _latest_file(DEFAULT_INPUT_DIR, "benchmark_label_completion_status_*.json")
    completion_payload = _load_json(completion)
    if completion_payload and completion:
        completion_payload["sourcePath"] = str(completion)
    payload = build_worksheet(_load_json(template), source_path=template, completion_payload=completion_payload)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Benchmark label worksheet JSON: {outputs['json_path']}")
    print(f"Benchmark label worksheet markdown: {outputs['markdown_path']}")
    print(f"Worksheet rows: {payload.get('summary', {}).get('worksheetRowCount', 0)}")
    print(f"Labels assigned by this tool: {payload.get('summary', {}).get('labelsAssignedByThisTool', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
