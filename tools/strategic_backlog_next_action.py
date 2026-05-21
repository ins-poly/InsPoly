from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKLOG_DIR = Path("strategic_backlog")
DEFAULT_OUTPUT_DIR = Path("strategic_backlog_outputs")
VALIDATION_OUTPUT_DIR = Path("validation_corpus_outputs")
REVIEW_PACKET_OUTPUT_DIR = Path("review_packets")
FALSE_POSITIVE_LIBRARY_OUTPUT_DIR = Path("false_positive_library")
SOURCE_ATTRIBUTION_OUTPUT_DIR = Path("source_attribution_outputs")
REVIEW_INDEX_OUTPUT_DIR = Path("review_index_outputs")
SCHEMA_NORMALIZATION_OUTPUT_DIR = Path("schema_normalization_outputs")
CANDIDATE_RECALL_OUTPUT_DIR = Path("candidate_recall_outputs")
REVIEW_PACKET_COMPARE_OUTPUT_DIR = Path("review_packet_compare_outputs")
STRATEGIC_DASHBOARD_OUTPUT_DIR = Path("strategic_backlog_outputs")
ANALYST_QUALITY_OUTPUT_DIR = Path("analyst_quality_outputs")
ANALYST_REVIEW_BUNDLE_OUTPUT_DIR = Path("analyst_review_bundles")
ARTIFACT_MANIFEST_OUTPUT_DIR = Path("artifact_manifests")
IMPLEMENTATION_BOUNDARY_OUTPUT_DIR = Path("implementation_boundaries")

ALLOWED_DECISIONS = {
    "execute_safe_non_rpc_task",
    "generate_review_packets",
    "improve_analyst_report_readability",
    "improve_clickable_drilldown",
    "run_candidate_recall_diagnostic",
    "run_false_positive_library_task",
    "run_source_attribution_repair_check",
    "run_validation_readiness_when_rpc_available",
    "produce_rfc_only",
    "stop_human_approval_required",
}

FORBIDDEN_PROMPT_PHRASES = (
    "improve everything",
    "optimize detection",
    "change model",
    "tune weights",
    "adjust gates",
    "lower thresholds",
    "use news",
    "use llm scoring",
    "change weights",
)

HARD_CONSTRAINTS = (
    "Do not edit `_score_trade()`.",
    "Leave Strong Risk gates unchanged.",
    "Leave scoring weights unchanged.",
    "Leave production severity labels unchanged.",
    "Do not broaden structural pre-admission.",
    "Leave structural floors and notional thresholds unchanged.",
    "Leave suspicious funding v2 rules unchanged.",
    "Do not make `multi_hop_unknown` funding eligible without independent structural support.",
    "Do not make CEX proxy-only or bridge proxy-only evidence eligible.",
    "Leave Hard Evidence Review routing unchanged except accepted-contract bugfixes.",
    "Do not add language-model or machine-learning based scoring.",
    "Do not add journalism, intelligence, or external signal ingestion.",
    "Do not hardcode credentials.",
    "Do not hardcode RPC URLs.",
    "Do not mutate old saved outputs.",
    "Preserve legacy output loading and report normalization.",
    "Treat funding unavailable as `unknown`, not `none`.",
    "Treat dedupe as reporting-only; never drop production rows.",
    "Do not enable production detector edits unless a maintainer explicitly approves an RFC after readiness passes.",
)

PRIORITY_WEIGHT = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
RISK_WEIGHT = {"low": 0, "medium": 1, "high": 2}


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


def _latest_readiness_file(output_dir: Path) -> Path | None:
    return _latest_file(output_dir, "gate_decision_readiness_*.json")


def _latest_autonomous_file(output_dir: Path) -> Path | None:
    return _latest_file(output_dir, "autonomous_next_action_*.json")


def _latest_operator_package(output_dir: Path) -> Path | None:
    return _latest_file(output_dir, "operator_rpc_capacity_recovery_package_*.json")


def _latest_backlog_file(backlog_dir: Path) -> Path | None:
    return _latest_file(backlog_dir, "ins_poly_strategic_backlog_*.json")


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _item_list(backlog: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = backlog.get("items")
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, Mapping)]


def _priority_key(item: Mapping[str, Any]) -> tuple[int, int, int, str]:
    priority = PRIORITY_WEIGHT.get(str(item.get("priority") or "P3"), 3)
    risk = RISK_WEIGHT.get(str(item.get("riskLevel") or "high"), 2)
    approval = 1 if _as_bool(item.get("requiresHumanApproval")) else 0
    return (priority, risk, approval, str(item.get("id") or ""))


def _decision_for_item(item: Mapping[str, Any]) -> str:
    title = str(item.get("title") or "").lower()
    workstream = str(item.get("workstream") or "").lower()
    if "unique" in workstream or "review packet" in title:
        return "generate_review_packets"
    if "clickable" in workstream or "ui" in workstream or "drilldown" in workstream:
        return "improve_clickable_drilldown"
    if "implementation boundary" in workstream or "implementation boundary" in title or "crosswalk" in title:
        return "improve_analyst_report_readability"
    if "readability" in workstream or "analyst-facing" in workstream:
        return "improve_analyst_report_readability"
    if "recall" in workstream or "false-negative" in workstream:
        return "run_candidate_recall_diagnostic"
    if "false-positive" in workstream or "suppressor" in workstream:
        return "run_false_positive_library_task"
    if "source attribution" in workstream or "schema" in workstream:
        return "run_source_attribution_repair_check"
    if "validation" in workstream or "rpc" in workstream:
        return "run_validation_readiness_when_rpc_available"
    if _as_bool(item.get("requiresHumanApproval")) or _as_bool(item.get("modelBehaviorChange")):
        return "produce_rfc_only"
    return "execute_safe_non_rpc_task"


def _current_state(
    *,
    readiness: Mapping[str, Any],
    autonomous: Mapping[str, Any],
    operator_package: Mapping[str, Any],
    backlog: Mapping[str, Any],
    completed_ids: Sequence[str] = (),
) -> dict[str, Any]:
    readiness_classification = (
        readiness.get("readinessClassification")
        or readiness.get("classification")
        or operator_package.get("readiness_classification")
        or "unknown"
    )
    operator_status = (
        operator_package.get("configuration_status")
        or operator_package.get("operator_rpc_status")
        or "unknown"
    )
    autonomous_decision = autonomous.get("decision") or operator_package.get("autonomous_decision") or "unknown"
    items = _item_list(backlog)
    safe_non_rpc = [
        item
        for item in items
        if not _as_bool(item.get("blockedByRpc"))
        and not _as_bool(item.get("requiresHumanApproval"))
        and not _as_bool(item.get("modelBehaviorChange"))
    ]
    return {
        "readiness_classification": readiness_classification,
        "autonomous_decision": autonomous_decision,
        "operator_rpc_status": operator_status,
        "public_rpc_blocker_active": _rpc_blocker_active(readiness_classification, autonomous_decision, operator_status),
        "backlog_item_count": len(items),
        "safe_non_rpc_item_count": len(safe_non_rpc),
        "completed_or_artifact_satisfied_ids": list(completed_ids),
    }


def _rpc_blocker_active(readiness_classification: Any, autonomous_decision: Any, operator_status: Any) -> bool:
    text = " ".join(str(value or "").lower() for value in (readiness_classification, autonomous_decision, operator_status))
    return (
        "not_ready_corpus_too_cache_only" in text
        or "stop_human_approval_required" in text
        or "no_new_operator" in text
        or "public_rpc" in text
    )


def _completed_backlog_ids() -> set[str]:
    completed: set[str] = set()
    latest_review_packets = _latest_file(REVIEW_PACKET_OUTPUT_DIR, "unique_review_packets_*.json")
    review_packet_payload = _load_json(latest_review_packets)
    if latest_review_packets:
        completed.update({"P0-SAFE-001", "P1-SAFE-003", "P1-SAFE-007", "P1-SAFE-008"})
    if review_packet_payload.get("wallet_groups"):
        completed.add("P2-SAFE-012")
    if review_packet_payload.get("market_groups"):
        completed.add("P2-SAFE-013")
    if review_packet_payload.get("retrospective_summary"):
        completed.add("P2-SAFE-014")
    summary = review_packet_payload.get("summary") if isinstance(review_packet_payload.get("summary"), Mapping) else {}
    if summary.get("source_navigation_packets") or any(
        isinstance(packet, Mapping) and packet.get("source_navigation")
        for packet in review_packet_payload.get("packets", [])
        if isinstance(packet, Mapping)
    ):
        completed.add("P2-SAFE-016")
    if _latest_file(FALSE_POSITIVE_LIBRARY_OUTPUT_DIR, "false_positive_pattern_library_*.json"):
        completed.add("P1-SAFE-004")
    if _latest_file(SOURCE_ATTRIBUTION_OUTPUT_DIR, "source_attribution_completeness_*.json"):
        completed.add("P1-SAFE-006")
    if _latest_file(REVIEW_INDEX_OUTPUT_DIR, "review_output_index_*.json"):
        completed.add("P1-SAFE-009")
    if _latest_file(REVIEW_INDEX_OUTPUT_DIR, "review_output_index_*.json") and _latest_file(
        REVIEW_PACKET_OUTPUT_DIR, "unique_review_packets_*.md"
    ):
        completed.add("P1-SAFE-010")
    if _latest_file(SCHEMA_NORMALIZATION_OUTPUT_DIR, "review_schema_normalization_check_*.json"):
        completed.add("P1-SAFE-011")
    if _latest_file(CANDIDATE_RECALL_OUTPUT_DIR, "candidate_recall_diagnostic_*.json"):
        completed.add("P1-SAFE-005")
    if _latest_file(REVIEW_PACKET_COMPARE_OUTPUT_DIR, "review_packet_case_reviewer_compare_*.json"):
        completed.add("P2-SAFE-015")
    if _latest_file(STRATEGIC_DASHBOARD_OUTPUT_DIR, "strategic_backlog_dashboard_*.json"):
        completed.add("P3-SAFE-022")
    if _latest_file(ANALYST_QUALITY_OUTPUT_DIR, "review_packet_quality_check_*.json"):
        completed.add("P3-SAFE-023")
    if _latest_file(ANALYST_REVIEW_BUNDLE_OUTPUT_DIR, "analyst_review_bundle_*.json"):
        completed.add("P3-SAFE-024")
    if _latest_file(ANALYST_QUALITY_OUTPUT_DIR, "wallet_review_queue_*.json"):
        completed.add("P3-SAFE-025")
    if _latest_file(ARTIFACT_MANIFEST_OUTPUT_DIR, "review_artifact_manifest_*.json"):
        completed.add("P3-SAFE-026")
    boundary = _latest_file(IMPLEMENTATION_BOUNDARY_OUTPUT_DIR, "implementation_boundary_*.json")
    crosswalk = _latest_file(IMPLEMENTATION_BOUNDARY_OUTPUT_DIR, "analyst_crosswalk_*.json")
    if boundary and crosswalk:
        completed.add("P1-SAFE-027")
    review_index = _latest_file(REVIEW_INDEX_OUTPUT_DIR, "review_output_index_*.json")
    review_index_payload = _load_json(review_index)
    latest_by_kind = (
        review_index_payload.get("summary", {}).get("latest_by_kind", {})
        if isinstance(review_index_payload.get("summary"), Mapping)
        else {}
    )
    if boundary and crosswalk and latest_by_kind.get("implementation_boundary") and latest_by_kind.get("analyst_crosswalk"):
        completed.add("P1-SAFE-028")
    if _latest_file(DEFAULT_OUTPUT_DIR, "strategic_next_action_*.json"):
        completed.add("P0-SAFE-002")
    return completed


def select_next_item(backlog: Mapping[str, Any], current_state: Mapping[str, Any]) -> dict[str, Any] | None:
    items = _item_list(backlog)
    rpc_blocked = bool(current_state.get("public_rpc_blocker_active"))
    completed_ids = set(current_state.get("completed_or_artifact_satisfied_ids") or [])
    candidates: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("id") or "") in completed_ids:
            continue
        if rpc_blocked and _as_bool(item.get("blockedByRpc")):
            continue
        if _as_bool(item.get("modelBehaviorChange")):
            continue
        if _as_bool(item.get("requiresHumanApproval")):
            continue
        candidates.append(item)
    if not candidates:
        return None
    return sorted(candidates, key=_priority_key)[0]


def _lines(values: Sequence[Any]) -> list[str]:
    return [f"- {value}" for value in values] if values else ["- none"]


def _clean_prompt(prompt: str) -> str:
    lower = prompt.lower()
    offenders = [phrase for phrase in FORBIDDEN_PROMPT_PHRASES if phrase in lower]
    if not offenders:
        return prompt
    cleaned = prompt
    replacements = {
        "improve everything": "improve the bounded artifact only",
        "optimize detection": "improve analyst review quality",
        "change model": "alter detector behavior",
        "tune weights": "edit scoring parameters",
        "adjust gates": "edit gate logic",
        "lower thresholds": "relax thresholds",
        "use news": "add external feeds",
        "use llm scoring": "add language-model based scoring",
        "change weights": "edit scoring parameters",
    }
    for phrase, replacement in replacements.items():
        cleaned = cleaned.replace(phrase, replacement).replace(phrase.title(), replacement)
    return cleaned


def build_ready_prompt(item: Mapping[str, Any], current_state: Mapping[str, Any], evidence_paths: Mapping[str, str]) -> str:
    commands = item.get("commandsToRun") if isinstance(item.get("commandsToRun"), list) else []
    tests = item.get("testsToRun") if isinstance(item.get("testsToRun"), list) else []
    stop_conditions = item.get("stopConditions") if isinstance(item.get("stopConditions"), list) else []
    files = item.get("specificFilesLikelyTouched") if isinstance(item.get("specificFilesLikelyTouched"), list) else []
    acceptance = item.get("acceptanceCriteria") if isinstance(item.get("acceptanceCriteria"), list) else []

    prompt = f"""You are working in the InsPoly repository.

Role:
Act as an autonomous senior financial-forensic product and technical lead. This task is safe workflow/reporting/analyst-usability work only.

Current status:
- Readiness classification: `{current_state.get('readiness_classification', 'unknown')}`.
- Autonomous validation decision: `{current_state.get('autonomous_decision', 'unknown')}`.
- Operator RPC status: `{current_state.get('operator_rpc_status', 'unknown')}`.
- Public RPC blocker active: `{current_state.get('public_rpc_blocker_active')}`.
- This task must improve investigation quality without altering detector behavior.

Hard constraints:
{chr(10).join(_lines(HARD_CONSTRAINTS))}

Files/tools to inspect before editing:
- README.md
- docs/ARCHITECTURE.md
- docs/PROGRAMS.md
- docs/DETECTION_MODEL.md
- optional local AGENTS.md / PROJECT_MEMORY.md if present
- strategic_backlog/ins_poly_strategic_backlog_20260505.json
{chr(10).join(_lines(files))}

Evidence paths:
{chr(10).join(_lines([f'{key}: {value}' for key, value in evidence_paths.items() if value]))}

Bounded task:
Execute backlog item `{item.get('id', '')}`: {item.get('title', '')}.

Why it matters:
{item.get('whyItMatters', '')}

Acceptance criteria:
{chr(10).join(_lines(acceptance))}

Commands to run:
{chr(10).join(_lines(commands))}

Tests to run:
{chr(10).join(_lines(tests))}

PROJECT_MEMORY.md update requirements:
- Record the backlog item executed.
- Record files changed and artifacts written.
- Record tests run and results.
- Record current RPC/readiness status.
- Record invariants preserved.
- Record the next recommended prompt path or embedded prompt.

Stop conditions:
{chr(10).join(_lines([*stop_conditions, 'Stop if evidence is cache-only or stale but the conclusion would require fresh trace-enabled proof.', 'Stop if implementation would require credentials, hardcoded RPC URLs, external feeds, or mutation of old saved outputs.']))}

Output summary required:
- files changed;
- artifacts written;
- why this improves insider-style investigation quality;
- tests run and result;
- current readiness/RPC status;
- invariants preserved;
- next ready-to-copy Codex prompt.
"""
    return _clean_prompt(prompt)


def build_action_pack(
    *,
    backlog_path: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    validation_output_dir: Path = VALIDATION_OUTPUT_DIR,
    readiness_path: Path | None = None,
    autonomous_path: Path | None = None,
    operator_package_path: Path | None = None,
    project_memory_path: Path | None = None,
) -> dict[str, Any]:
    resolved_output_dir = _resolve(output_dir) or output_dir
    resolved_validation_dir = _resolve(validation_output_dir) or validation_output_dir
    resolved_backlog_path = _resolve(backlog_path) or _latest_backlog_file(DEFAULT_BACKLOG_DIR)
    resolved_readiness = _resolve(readiness_path) or _latest_readiness_file(resolved_validation_dir)
    resolved_autonomous = _resolve(autonomous_path) or _latest_autonomous_file(resolved_validation_dir)
    resolved_operator = _resolve(operator_package_path) or _latest_operator_package(resolved_validation_dir)
    resolved_memory = _resolve(project_memory_path) or (REPO_ROOT / "PROJECT_MEMORY.md")

    backlog = _load_json(resolved_backlog_path)
    readiness = _load_json(resolved_readiness)
    autonomous = _load_json(resolved_autonomous)
    operator_package = _load_json(resolved_operator)
    completed_ids = sorted(_completed_backlog_ids())
    current_state = _current_state(
        readiness=readiness,
        autonomous=autonomous,
        operator_package=operator_package,
        backlog=backlog,
        completed_ids=completed_ids,
    )
    selected = select_next_item(backlog, current_state)
    evidence_paths = {
        "backlog_json": str(resolved_backlog_path) if resolved_backlog_path else "",
        "readiness_json": str(resolved_readiness) if resolved_readiness else "",
        "autonomous_next_action_json": str(resolved_autonomous) if resolved_autonomous else "",
        "operator_rpc_package_json": str(resolved_operator) if resolved_operator else "",
        "implementation_boundary_json": str(_latest_file(IMPLEMENTATION_BOUNDARY_OUTPUT_DIR, "implementation_boundary_*.json") or ""),
        "analyst_crosswalk_json": str(_latest_file(IMPLEMENTATION_BOUNDARY_OUTPUT_DIR, "analyst_crosswalk_*.json") or ""),
        "project_memory": str(resolved_memory) if resolved_memory else "",
    }

    if selected is None:
        decision = "stop_human_approval_required"
        prompt = _clean_prompt(
            f"""You are working in the InsPoly repository.

Role:
Act as an autonomous senior financial-forensic product and technical lead. This is a governance stop-state task only.

Current status:
- Readiness classification: `{current_state.get('readiness_classification', 'unknown')}`.
- Autonomous validation decision: `{current_state.get('autonomous_decision', 'unknown')}`.
- Operator RPC status: `{current_state.get('operator_rpc_status', 'unknown')}`.
- Public RPC blocker active: `{current_state.get('public_rpc_blocker_active')}`.
- No safe non-RPC backlog item is currently selectable.

Hard constraints:
{chr(10).join(_lines(HARD_CONSTRAINTS))}

Files/tools to inspect before editing:
- README.md
- docs/ARCHITECTURE.md
- docs/PROGRAMS.md
- docs/DETECTION_MODEL.md
- optional local AGENTS.md / PROJECT_MEMORY.md if present
- strategic_backlog/ins_poly_strategic_backlog_20260505.json
- latest readiness/autonomous/operator artifacts under validation_corpus_outputs/

Bounded task:
Stop and request human approval before any production detector work. Do not run repeated RPC validation loops unless operator-approved RPC capacity is configured through existing env/config.

Commands to run:
- python3 tools/strategic_backlog_next_action.py
- python3 tools/strategic_backlog_dashboard.py

Tests to run:
- python3 -m py_compile tools/strategic_backlog_next_action.py tools/strategic_backlog_dashboard.py
- python3 -m unittest tests.test_strategic_backlog_next_action tests.test_strategic_backlog_dashboard

PROJECT_MEMORY.md update requirements:
- Record that the safe non-RPC backlog is exhausted.
- Record that human approval or operator RPC capacity is required for further meaningful progress.
- Record preserved invariants.

Stop conditions:
- Stop if the next task would require model/scoring/gate/HER/funding eligibility changes.
- Stop if the next task would require private credentials or hardcoded RPC URLs.
- Stop if evidence is cache-only or stale but a conclusion would require fresh trace-enabled proof.

Output summary required:
- current readiness/RPC status;
- why no safe autonomous task remains;
- human approval required;
- invariants preserved.
"""
        )
        recommended_next_task = "No safe non-RPC backlog item is currently selectable; human approval is required."
    else:
        decision = _decision_for_item(selected)
        if decision not in ALLOWED_DECISIONS:
            decision = "execute_safe_non_rpc_task"
        prompt = build_ready_prompt(selected, current_state, evidence_paths)
        recommended_next_task = f"{selected.get('id', '')}: {selected.get('title', '')}"

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "decision": decision,
        "recommended_next_task": recommended_next_task,
        "selected_item": selected or {},
        "current_state": current_state,
        "ready_to_copy_codex_prompt": prompt,
        "evidence_paths": evidence_paths,
        "stop_conditions": selected.get("stopConditions", []) if selected else ["Human approval required."],
        "invariants_preserved": list(HARD_CONSTRAINTS),
        "confidence": {
            "level": "high" if selected else "medium",
            "reason": "Deterministic priority/risk/RPC filter over local strategic backlog.",
        },
    }


def render_markdown(pack: Mapping[str, Any]) -> str:
    selected = pack.get("selected_item") if isinstance(pack.get("selected_item"), Mapping) else {}
    state = pack.get("current_state") if isinstance(pack.get("current_state"), Mapping) else {}
    lines = [
        "# Strategic Backlog Next Action",
        "",
        f"- Generated at: {pack.get('generated_at', '')}",
        f"- Decision: `{pack.get('decision', '')}`",
        f"- Recommended next task: {pack.get('recommended_next_task', '')}",
        f"- Selected item: `{selected.get('id', '')}` {selected.get('title', '')}",
        f"- Readiness classification: `{state.get('readiness_classification', '')}`",
        f"- Operator RPC status: `{state.get('operator_rpc_status', '')}`",
        f"- Public RPC blocker active: `{state.get('public_rpc_blocker_active', '')}`",
        "",
        "## Evidence Paths",
    ]
    for key, value in (pack.get("evidence_paths") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Ready-To-Copy Codex Prompt",
            "",
            "```text",
            str(pack.get("ready_to_copy_codex_prompt") or "").rstrip(),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(pack: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved_output_dir = _resolve(output_dir) or output_dir
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved_output_dir / f"strategic_next_action_{stamp}.json"
    markdown_path = resolved_output_dir / f"strategic_next_action_{stamp}.md"
    json_path.write_text(json.dumps(dict(pack), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(pack), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select the next safe strategic InsPoly backlog action.")
    parser.add_argument("--backlog", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--validation-output-dir", type=Path, default=VALIDATION_OUTPUT_DIR)
    parser.add_argument("--readiness", type=Path)
    parser.add_argument("--autonomous-next-action", type=Path)
    parser.add_argument("--operator-package", type=Path)
    args = parser.parse_args(argv)

    pack = build_action_pack(
        backlog_path=args.backlog,
        output_dir=args.output_dir,
        validation_output_dir=args.validation_output_dir,
        readiness_path=args.readiness,
        autonomous_path=args.autonomous_next_action,
        operator_package_path=args.operator_package,
    )
    outputs = write_outputs(pack, args.output_dir)
    print(f"Strategic next-action JSON: {outputs['json_path']}")
    print(f"Strategic next-action markdown: {outputs['markdown_path']}")
    print(f"Decision: {pack.get('decision', '')}")
    print(f"Recommended next task: {pack.get('recommended_next_task', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
