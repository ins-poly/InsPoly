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


def _csv_path(path: Path | None) -> str:
    if not path:
        return ""
    csv_path = path.with_suffix(".csv")
    return str(csv_path) if csv_path.exists() else ""


READINESS_GATE_ANALYST_DISPOSITIONS = [
    "likely_false_positive",
    "plausible_insider_style",
    "needs_fresh_validation",
    "inconclusive",
    "reporting_only_control",
    "ignore_not_benchmark",
]


def build_handoff(
    queue_payload: Mapping[str, Any],
    *,
    source_path: Path | None = None,
    template_path: Path | None = None,
) -> dict[str, Any]:
    rows = [dict(row) for row in queue_payload.get("priorityRows", []) if isinstance(row, Mapping)]
    summary = queue_payload.get("summary") if isinstance(queue_payload.get("summary"), Mapping) else {}
    label_values = {
        "expectedAnalystDisposition": READINESS_GATE_ANALYST_DISPOSITIONS,
        "expectedDetectorDisposition": [
            "keep_current_behavior",
            "reporting_only_note",
            "rfc_only_review_candidate",
            "needs_fresh_validation_before_decision",
        ],
        "humanLabelConfidence": ["low", "medium", "high"],
        "freshValidationRequired": ["yes", "no"],
    }
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_label_handoff_pack",
        "sourcePriorityQueuePath": str(source_path or ""),
        "sourcePriorityQueueCsvPath": _csv_path(source_path),
        "sourcePriorityTemplatePath": str(template_path or ""),
        "sourcePriorityTemplateCsvPath": _csv_path(template_path),
        "summary": {
            "queueRowCount": len(rows),
            "highPriorityRowCount": sum(1 for row in rows if row.get("priorityClass") == "high"),
            "mediumPriorityRowCount": sum(1 for row in rows if row.get("priorityClass") == "medium"),
            "packetRowCount": sum(1 for row in rows if row.get("sourceType") == "unique_review_packet"),
            "eventRunRowCount": sum(1 for row in rows if row.get("sourceType") == "event_forensic_run"),
            "humanLabelsAssignedByThisTool": 0,
            "readinessCompatibleTemplatePresent": bool(template_path and _csv_path(template_path)),
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "labelingInstructions": {
            "plainLanguageGoal": (
                "A human analyst should label whether each saved-output row looks like a likely false positive, "
                "a plausible insider-style lead, inconclusive/reporting-only context, a row to ignore as a benchmark, "
                "or a row that needs fresh validation."
            ),
            "allowedValues": label_values,
            "minimumUsefulBatch": "Label at least 10 high-priority rows before treating the batch as a useful reporting checkpoint.",
            "importantCaution": (
                "These labels are analyst expectations for future reporting/regression checks only. "
                "They are not production scoring truth and must not change gates or weights."
            ),
        },
        "handoffRows": [
            {
                "queueRank": row.get("queueRank", 0),
                "localCaseId": row.get("localCaseId", ""),
                "priorityClass": row.get("priorityClass", ""),
                "labelPriorityScore": row.get("labelPriorityScore", 0),
                "sourceType": row.get("sourceType", ""),
                "eventSlug": row.get("eventSlug", ""),
                "market": row.get("market", ""),
                "wallet": row.get("wallet", ""),
                "priorityReasons": row.get("priorityReasons", []),
                "recommendedQuestion": row.get("recommendedHumanQuestion", ""),
                "sourceArtifact": row.get("sourceArtifact", ""),
            }
            for row in rows
        ],
        "stopConditions": [
            "Do not infer labels automatically.",
            "Do not use labels to change production scoring, gates, HER routing, funding eligibility, or candidate admission.",
            "Do not treat saved-output/cache-only rows as fresh trace-enabled proof.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    instructions = payload.get("labelingInstructions") if isinstance(payload.get("labelingInstructions"), Mapping) else {}
    allowed = instructions.get("allowedValues") if isinstance(instructions.get("allowedValues"), Mapping) else {}
    lines = [
        "# Benchmark Label Handoff Pack",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Queue rows: {summary.get('queueRowCount', 0)}",
        f"- High-priority rows: {summary.get('highPriorityRowCount', 0)}",
        f"- Packet rows: {summary.get('packetRowCount', 0)}",
        f"- Event-run rows: {summary.get('eventRunRowCount', 0)}",
        f"- Human labels assigned by this tool: {summary.get('humanLabelsAssignedByThisTool', 0)}",
        f"- Readiness-compatible template present: {summary.get('readinessCompatibleTemplatePresent', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        f"- Queue CSV: {payload.get('sourcePriorityQueueCsvPath', '')}",
        f"- Label template CSV: {payload.get('sourcePriorityTemplateCsvPath', '')}",
        "",
        "## Plain-Language Goal",
        "",
        str(instructions.get("plainLanguageGoal", "")),
        "",
        "## Allowed Label Values",
    ]
    for field, values in allowed.items():
        lines.append(f"- `{field}`: {', '.join(str(value) for value in values)}")
    lines.extend(["", "## Handoff Rows"])
    for row in payload.get("handoffRows") or []:
        if not isinstance(row, Mapping):
            continue
        label = row.get("eventSlug") or row.get("market") or "unknown"
        lines.append(
            f"- #{row.get('queueRank', '')} `{row.get('localCaseId', '')}` "
            f"{row.get('priorityClass', '')} score={row.get('labelPriorityScore', 0)}: "
            f"{label} / {row.get('wallet') or 'event-run'}"
        )
        reasons = row.get("priorityReasons") if isinstance(row.get("priorityReasons"), list) else []
        for reason in reasons[:2]:
            lines.append(f"  - {reason}")
    lines.extend(["", "## Stop Conditions"])
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"benchmark_label_handoff_pack_{stamp}.json"
    markdown_path = resolved / f"benchmark_label_handoff_pack_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a human-facing labeling handoff pack from the priority queue.")
    parser.add_argument("--queue", type=Path, default=None)
    parser.add_argument("--template", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    source = args.queue or _latest_file(DEFAULT_INPUT_DIR, "benchmark_label_priority_queue_*.json")
    template = args.template or _latest_file(DEFAULT_INPUT_DIR, "benchmark_label_priority_template_*.json")
    payload = build_handoff(_load_json(source), source_path=source, template_path=template)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Benchmark label handoff JSON: {outputs['json_path']}")
    print(f"Benchmark label handoff markdown: {outputs['markdown_path']}")
    print(f"Queue rows: {payload.get('summary', {}).get('queueRowCount', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
