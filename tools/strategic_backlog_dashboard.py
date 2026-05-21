from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.strategic_backlog_next_action import (
    DEFAULT_BACKLOG_DIR,
    DEFAULT_OUTPUT_DIR,
    VALIDATION_OUTPUT_DIR,
    _as_bool,
    _completed_backlog_ids,
    _item_list,
    _latest_backlog_file,
    _latest_file,
    _load_json,
    _resolve,
    build_action_pack,
)


def _latest_readiness(path: Path = VALIDATION_OUTPUT_DIR) -> Path | None:
    return _latest_file(path, "gate_decision_readiness_*.json")


def _latest_operator_package(path: Path = VALIDATION_OUTPUT_DIR) -> Path | None:
    return _latest_file(path, "operator_rpc_capacity_recovery_package_*.json")


def _status_for_item(item: Mapping[str, Any], completed_ids: set[str], rpc_blocker_active: bool) -> str:
    item_id = str(item.get("id") or "")
    if item_id in completed_ids:
        return "completed"
    if _as_bool(item.get("modelBehaviorChange")) or _as_bool(item.get("requiresHumanApproval")):
        return "human_approval_required"
    if rpc_blocker_active and _as_bool(item.get("blockedByRpc")):
        return "blocked_by_rpc"
    return "available"


def build_dashboard(
    *,
    backlog_path: Path | None = None,
    validation_output_dir: Path = VALIDATION_OUTPUT_DIR,
    completed_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    resolved_backlog_path = _resolve(backlog_path) or _latest_backlog_file(DEFAULT_BACKLOG_DIR)
    resolved_validation_dir = _resolve(validation_output_dir) or validation_output_dir
    backlog = _load_json(resolved_backlog_path)
    readiness_path = _latest_readiness(resolved_validation_dir)
    operator_path = _latest_operator_package(resolved_validation_dir)
    readiness = _load_json(readiness_path)
    operator_package = _load_json(operator_path)
    next_action = build_action_pack(
        backlog_path=resolved_backlog_path,
        output_dir=DEFAULT_OUTPUT_DIR,
        validation_output_dir=resolved_validation_dir,
        readiness_path=readiness_path,
        operator_package_path=operator_path,
    )
    state = next_action.get("current_state") if isinstance(next_action.get("current_state"), Mapping) else {}
    rpc_blocker_active = bool(state.get("public_rpc_blocker_active"))
    completed = set(completed_ids) if completed_ids is not None else _completed_backlog_ids()
    items = _item_list(backlog)

    rows: list[dict[str, Any]] = []
    for item in items:
        status = _status_for_item(item, completed, rpc_blocker_active)
        rows.append(
            {
                "id": item.get("id", ""),
                "title": item.get("title", ""),
                "workstream": item.get("workstream", ""),
                "priority": item.get("priority", ""),
                "riskLevel": item.get("riskLevel", ""),
                "status": status,
                "blockedByRpc": bool(_as_bool(item.get("blockedByRpc"))),
                "requiresHumanApproval": bool(_as_bool(item.get("requiresHumanApproval"))),
                "modelBehaviorChange": bool(_as_bool(item.get("modelBehaviorChange"))),
            }
        )

    status_counts = Counter(row["status"] for row in rows)
    priority_counts = Counter(str(row["priority"] or "unknown") for row in rows)
    workstream_counts = Counter(str(row["workstream"] or "unknown") for row in rows)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "backlog_path": str(resolved_backlog_path) if resolved_backlog_path else "",
        "readiness_path": str(readiness_path) if readiness_path else "",
        "operator_package_path": str(operator_path) if operator_path else "",
        "readiness_classification": readiness.get("readinessClassification") or readiness.get("classification") or "unknown",
        "operator_rpc_status": operator_package.get("configuration_status")
        or operator_package.get("operator_rpc_status")
        or "unknown",
        "public_rpc_blocker_active": rpc_blocker_active,
        "total_items": len(rows),
        "completed_items": status_counts.get("completed", 0),
        "available_items": status_counts.get("available", 0),
        "rpc_blocked_items": status_counts.get("blocked_by_rpc", 0),
        "human_approval_required_items": status_counts.get("human_approval_required", 0),
        "next_action_decision": next_action.get("decision", ""),
        "next_action_task": next_action.get("recommended_next_task", ""),
    }
    return {
        "summary": summary,
        "status_counts": dict(sorted(status_counts.items())),
        "priority_counts": dict(sorted(priority_counts.items())),
        "workstream_counts": dict(sorted(workstream_counts.items())),
        "items": rows,
        "next_action": {
            "decision": next_action.get("decision", ""),
            "recommended_next_task": next_action.get("recommended_next_task", ""),
            "ready_to_copy_codex_prompt": next_action.get("ready_to_copy_codex_prompt", ""),
        },
        "read_only_safety": {
            "validation_runs_triggered": False,
            "model_behavior_changed": False,
            "old_outputs_mutated": False,
        },
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Strategic Backlog Progress Dashboard",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Backlog: {summary.get('backlog_path', '')}",
        f"- Readiness: `{summary.get('readiness_classification', '')}`",
        f"- Operator RPC status: `{summary.get('operator_rpc_status', '')}`",
        f"- Public RPC blocker active: `{summary.get('public_rpc_blocker_active', '')}`",
        f"- Total items: {summary.get('total_items', 0)}",
        f"- Completed items: {summary.get('completed_items', 0)}",
        f"- Available safe items: {summary.get('available_items', 0)}",
        f"- RPC-blocked items: {summary.get('rpc_blocked_items', 0)}",
        f"- Human-approval items: {summary.get('human_approval_required_items', 0)}",
        "",
        "## Next Action",
        "",
        f"- Decision: `{summary.get('next_action_decision', '')}`",
        f"- Task: {summary.get('next_action_task', '')}",
        "",
        "## Status Counts",
    ]
    for key, value in (payload.get("status_counts") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Items"])
    for item in payload.get("items") or []:
        lines.append(
            f"- `{item.get('id')}` [{item.get('status')}] {item.get('priority')} "
            f"{item.get('title')} ({item.get('workstream')})"
        )
    lines.extend(
        [
            "",
            "## Ready-To-Copy Codex Prompt",
            "",
            "```text",
            str((payload.get("next_action") or {}).get("ready_to_copy_codex_prompt") or "").rstrip(),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved_output_dir = _resolve(output_dir) or output_dir
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved_output_dir / f"strategic_backlog_dashboard_{stamp}.json"
    markdown_path = resolved_output_dir / f"strategic_backlog_dashboard_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a read-only strategic backlog progress dashboard.")
    parser.add_argument("--backlog", type=Path)
    parser.add_argument("--validation-output-dir", type=Path, default=VALIDATION_OUTPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    payload = build_dashboard(backlog_path=args.backlog, validation_output_dir=args.validation_output_dir)
    outputs = write_outputs(payload, args.output_dir)
    summary = payload.get("summary", {})
    print(f"Strategic backlog dashboard JSON: {outputs['json_path']}")
    print(f"Strategic backlog dashboard markdown: {outputs['markdown_path']}")
    print(f"Completed items: {summary.get('completed_items', 0)}")
    print(f"Available safe items: {summary.get('available_items', 0)}")
    print(f"Next task: {summary.get('next_action_task', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
