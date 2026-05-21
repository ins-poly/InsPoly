from __future__ import annotations

import argparse
import csv
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
CSV_FIELDS = (
    "queueRank",
    "localCaseId",
    "sourceType",
    "eventSlug",
    "market",
    "conditionId",
    "wallet",
    *LABEL_FIELDS,
    "priorityClass",
    "labelPriorityScore",
    "priorityReasons",
    "recommendedHumanQuestion",
    "sourceArtifact",
)


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


def _reasons_text(value: Any) -> str:
    if isinstance(value, list):
        return " | ".join(str(item) for item in value if str(item).strip())
    return str(value or "")


def build_template(queue_payload: Mapping[str, Any], *, source_path: Path | None = None) -> dict[str, Any]:
    rows = [dict(row) for row in queue_payload.get("priorityRows", []) if isinstance(row, Mapping)]
    template_rows: list[dict[str, Any]] = []
    for row in rows:
        template_rows.append(
            {
                "queueRank": row.get("queueRank", ""),
                "localCaseId": row.get("localCaseId", ""),
                "sourceType": row.get("sourceType", ""),
                "eventSlug": row.get("eventSlug", ""),
                "market": row.get("market", ""),
                "conditionId": row.get("conditionId", ""),
                "wallet": row.get("wallet", ""),
                "expectedAnalystDisposition": "",
                "expectedDetectorDisposition": "",
                "humanLabelConfidence": "",
                "humanFalsePositiveReason": "",
                "humanInsiderStyleReason": "",
                "freshValidationRequired": "yes",
                "notes": "",
                "priorityClass": row.get("priorityClass", ""),
                "labelPriorityScore": row.get("labelPriorityScore", 0),
                "priorityReasons": _reasons_text(row.get("priorityReasons")),
                "recommendedHumanQuestion": row.get("recommendedHumanQuestion", ""),
                "sourceArtifact": row.get("sourceArtifact", ""),
                "modelBehaviorChanged": False,
            }
        )
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_label_priority_template",
        "sourcePriorityQueuePath": str(source_path or ""),
        "summary": {
            "templateRowCount": len(template_rows),
            "requiredLabelFieldCount": 2,
            "optionalLabelFieldCount": len(LABEL_FIELDS) - 2,
            "humanLabelsAssignedByThisTool": 0,
            "readyForBenchmarkReadinessGate": True,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "allowedValues": {
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
        },
        "templateRows": template_rows,
        "instructions": [
            "Fill only the label fields; do not edit localCaseId.",
            "Use this CSV as --labels-csv for tools/benchmark_label_readiness_gate.py with the full benchmark workbench.",
            "These labels support reporting/regression expectations only and do not authorize detector changes.",
        ],
        "stopConditions": [
            "Do not infer labels automatically.",
            "Do not use labels to change scoring, gates, HER routing, funding eligibility, or candidate admission.",
            "Do not treat saved-output/cache-only rows as fresh trace-enabled proof.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Benchmark Label Priority Template",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Template rows: {summary.get('templateRowCount', 0)}",
        f"- Human labels assigned by this tool: {summary.get('humanLabelsAssignedByThisTool', 0)}",
        f"- Ready for readiness gate: {summary.get('readyForBenchmarkReadinessGate', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## How To Use",
    ]
    for item in payload.get("instructions") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## First Rows"])
    for row in (payload.get("templateRows") or [])[:20]:
        if isinstance(row, Mapping):
            label = row.get("eventSlug") or row.get("market") or "unknown"
            lines.append(f"- #{row.get('queueRank', '')} `{row.get('localCaseId', '')}`: {label} / {row.get('wallet') or 'event-run'}")
    lines.extend(["", "## Stop Conditions"])
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def _write_csv(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"benchmark_label_priority_template_{stamp}.json"
    markdown_path = resolved / f"benchmark_label_priority_template_{stamp}.md"
    csv_path = resolved / f"benchmark_label_priority_template_{stamp}.csv"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    _write_csv([row for row in payload.get("templateRows", []) if isinstance(row, Mapping)], csv_path)
    return {"json_path": str(json_path), "markdown_path": str(markdown_path), "csv_path": str(csv_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a readiness-gate-compatible CSV template from the benchmark priority queue.")
    parser.add_argument("--queue", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    source = args.queue or _latest_file(DEFAULT_INPUT_DIR, "benchmark_label_priority_queue_*.json")
    payload = build_template(_load_json(source), source_path=source)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Benchmark label priority template JSON: {outputs['json_path']}")
    print(f"Benchmark label priority template markdown: {outputs['markdown_path']}")
    print(f"Benchmark label priority template CSV: {outputs['csv_path']}")
    print(f"Template rows: {payload.get('summary', {}).get('templateRowCount', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
