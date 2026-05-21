from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("source_schema_repair_outputs")
SOURCE_ATTRIBUTION_DIR = Path("source_attribution_outputs")
SCHEMA_NORMALIZATION_DIR = Path("schema_normalization_outputs")

HIGH_PRIORITY_FIELDS = {"hard_evidence_sources", "gate_branch", "gate_type", "composition"}
MEDIUM_PRIORITY_FIELDS = {"suppressors", "wallet", "market", "condition_id", "trade_id"}

FIELD_REPAIR_TYPES = {
    "hard_evidence_sources": "accepted-source propagation/display audit",
    "gate_branch": "Strong Risk gate-branch display normalization audit",
    "gate_type": "Strong Risk gate-family display normalization audit",
    "composition": "Strong Risk composition display normalization audit",
    "suppressors": "false-positive caution propagation/display audit",
    "wallet": "wallet navigation field normalization audit",
    "market": "market/event navigation field normalization audit",
    "condition_id": "market identity normalization audit",
    "trade_id": "transaction/source-row navigation normalization audit",
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


def _summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("summary")
    return value if isinstance(value, Mapping) else {}


def _counter(value: Any) -> Counter[str]:
    counter: Counter[str] = Counter()
    if isinstance(value, Mapping):
        for key, count in value.items():
            try:
                counter[str(key)] += int(count or 0)
            except (TypeError, ValueError):
                continue
    return counter


def discover_input_paths(
    *,
    source_attribution_path: Path | None = None,
    schema_normalization_path: Path | None = None,
) -> dict[str, Path | None]:
    source_path = _resolve(source_attribution_path) if source_attribution_path else None
    schema_path = _resolve(schema_normalization_path) if schema_normalization_path else None
    return {
        "source_attribution_completeness": source_path
        if source_path and source_path.exists()
        else _latest_file(SOURCE_ATTRIBUTION_DIR, "source_attribution_completeness_*.json"),
        "schema_normalization_check": schema_path
        if schema_path and schema_path.exists()
        else _latest_file(SCHEMA_NORMALIZATION_DIR, "review_schema_normalization_check_*.json"),
    }


def _priority(field: str) -> str:
    if field in HIGH_PRIORITY_FIELDS:
        return "high"
    if field in MEDIUM_PRIORITY_FIELDS:
        return "medium"
    return "low"


def _field_action(field: str, source_missing: int, schema_missing: int) -> dict[str, Any]:
    combined = source_missing + schema_missing
    priority = _priority(field)
    return {
        "field": field,
        "priority": priority,
        "source_missing_count": source_missing,
        "schema_missing_count": schema_missing,
        "combined_missing_count": combined,
        "safe_repair_type": FIELD_REPAIR_TYPES.get(field, "read-only schema/reporting audit"),
        "safe_next_check": (
            "Trace this field through saved artifact generation and display/export aliases; "
            "repair only dropped or inconsistently named report fields."
        ),
        "forbidden_repair": (
            "Do not change scoring, gates, production severity labels, HER eligibility, "
            "funding eligibility, structural thresholds, or historical saved outputs."
        ),
    }


def build_repair_plan(
    source_payload: Mapping[str, Any],
    schema_payload: Mapping[str, Any],
    *,
    input_paths: Mapping[str, Path | None] | None = None,
) -> dict[str, Any]:
    source_summary = _summary(source_payload)
    schema_summary = _summary(schema_payload)
    source_missing = _counter(source_summary.get("missing_field_counts"))
    schema_missing = _counter(schema_summary.get("missing_by_field"))
    all_fields = sorted(set(source_missing) | set(schema_missing))
    actions = [
        _field_action(field, source_missing.get(field, 0), schema_missing.get(field, 0))
        for field in all_fields
    ]
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    actions.sort(key=lambda item: (priority_rank.get(str(item["priority"]), 9), -int(item["combined_missing_count"]), item["field"]))

    total_combined = sum(int(item["combined_missing_count"]) for item in actions)
    high_priority = [item for item in actions if item["priority"] == "high"]
    paths = input_paths or {}
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "source_attribution_path": str(paths.get("source_attribution_completeness") or ""),
            "schema_normalization_path": str(paths.get("schema_normalization_check") or ""),
            "source_rows_inspected": int(source_summary.get("rows_inspected") or 0),
            "source_rows_with_missing_fields": int(source_summary.get("rows_with_missing_fields") or 0),
            "schema_rows_inspected": int(schema_summary.get("rows_inspected") or 0),
            "total_combined_missing_fields": total_combined,
            "field_count": len(actions),
            "high_priority_field_count": len(high_priority),
            "detector_behavior_changed": False,
            "implementation_allowed": "reporting/schema propagation checks only",
        },
        "field_actions": actions,
        "recommended_audit_sequence": [
            "Start with high-priority source/gate fields because they explain why a case entered review.",
            "Confirm whether missing fields are truly absent upstream or only lost through alias/display normalization.",
            "Patch only read-only export/display propagation if a field is dropped after it already exists in saved rows.",
            "Keep cache-only and legacy rows labeled as limited evidence; do not use them as production gate proof.",
            "Rerun source attribution completeness and schema normalization checks after any reporting-only repair.",
        ],
        "human_approval_required_for": [
            "_score_trade() changes",
            "Strong Risk gate changes",
            "scoring weight changes",
            "production severity label changes",
            "HER eligibility or routing changes",
            "funding eligibility changes",
            "structural threshold or pre-admission changes",
        ],
        "limitations": [
            "This plan reads saved local diagnostics only.",
            "It proposes audit/repair targets for reporting and schema propagation, not detector behavior.",
            "Missing fields in old/cache-only artifacts do not prove a model bug.",
        ],
        "invariants_preserved": [
            "_score_trade() unchanged",
            "Strong Risk gates unchanged",
            "scoring weights unchanged",
            "production severity labels unchanged",
            "Hard Evidence Review routing unchanged",
            "suspicious funding v2 unchanged",
            "old saved outputs not mutated",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = _summary(payload)
    lines = [
        "# Source/Schema Repair Plan",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Source rows inspected: {summary.get('source_rows_inspected', 0)}",
        f"- Source rows with missing fields: {summary.get('source_rows_with_missing_fields', 0)}",
        f"- Schema rows inspected: {summary.get('schema_rows_inspected', 0)}",
        f"- Combined missing field observations: {summary.get('total_combined_missing_fields', 0)}",
        f"- High-priority fields: {summary.get('high_priority_field_count', 0)}",
        f"- Detector behavior changed: {summary.get('detector_behavior_changed', False)}",
        "",
        "## Field Actions",
    ]
    actions = payload.get("field_actions") if isinstance(payload.get("field_actions"), list) else []
    if not actions:
        lines.append("- none")
    for action in actions:
        lines.extend(
            [
                f"- `{action.get('field', '')}` [{action.get('priority', '')}]",
                f"  - source missing: {action.get('source_missing_count', 0)}",
                f"  - schema missing: {action.get('schema_missing_count', 0)}",
                f"  - safe repair type: {action.get('safe_repair_type', '')}",
                f"  - forbidden repair: {action.get('forbidden_repair', '')}",
            ]
        )
    lines.extend(["", "## Recommended Audit Sequence"])
    for item in payload.get("recommended_audit_sequence") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Input Paths"])
    for key in ("source_attribution_path", "schema_normalization_path"):
        lines.append(f"- {key}: {summary.get(key, '')}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved_output_dir = _resolve(output_dir) or output_dir
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved_output_dir / f"source_schema_repair_plan_{stamp}.json"
    markdown_path = resolved_output_dir / f"source_schema_repair_plan_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a read-only source/schema repair plan from latest diagnostics.")
    parser.add_argument("--source-attribution", type=Path)
    parser.add_argument("--schema-normalization", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    paths = discover_input_paths(
        source_attribution_path=args.source_attribution,
        schema_normalization_path=args.schema_normalization,
    )
    payload = build_repair_plan(
        _load_json(paths["source_attribution_completeness"]),
        _load_json(paths["schema_normalization_check"]),
        input_paths=paths,
    )
    outputs = write_outputs(payload, args.output_dir)
    summary = payload.get("summary", {})
    print(f"Source/schema repair plan JSON: {outputs['json_path']}")
    print(f"Source/schema repair plan markdown: {outputs['markdown_path']}")
    print(f"High-priority fields: {summary.get('high_priority_field_count', 0)}")
    print(f"Detector behavior changed: {summary.get('detector_behavior_changed', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
