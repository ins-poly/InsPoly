from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("implementation_boundaries")
SELECTED_ISSUE_IDS = ("SCHEMA-001", "SCHEMA-002", "SCHEMA-003")
SAFE_CATEGORIES = {
    "safe_reporting_fix",
    "safe_schema_propagation_fix",
    "safe_navigation_or_index_fix",
    "safe_analyst_explanation_fix",
}
CHANGED_FILES = [
    "tools/generate_unique_review_packets.py",
    "tools/review_output_index.py",
    "tools/analyst_review_quality_suite.py",
    "tools/reporting_schema_patch_report.py",
    "tests/test_unique_review_packets.py",
    "tests/test_review_output_index.py",
    "tests/test_analyst_review_quality_suite.py",
    "tests/test_reporting_schema_patch_report.py",
    "PROJECT_MEMORY.md",
]

BEHAVIOR_BY_ISSUE = {
    "SCHEMA-001": {
        "behaviorAdded": (
            "Review packets emit `critical_field_warnings` when accepted hard-evidence source labels are absent, "
            "and the packet summary counts those warnings."
        ),
        "whyItHelps": "Analysts can separate a strong-looking row from a row with confirmed independent hard evidence before escalation.",
        "whyNoModelBehaviorChange": (
            "The warning is derived from saved packet fields only and never changes score, severity, HER routing, or eligibility."
        ),
    },
    "SCHEMA-002": {
        "behaviorAdded": (
            "Review packets normalize saved `composition` aliases into `strong_risk_composition_class` and warn if the "
            "composition remains unavailable on Strong Risk packets."
        ),
        "whyItHelps": "Analysts can see which evidence family is represented instead of reading a score as a reason.",
        "whyNoModelBehaviorChange": "This is display/schema normalization only; Strong Risk gates are not recalculated.",
    },
    "SCHEMA-003": {
        "behaviorAdded": (
            "Review packets normalize saved `gateBranch`/`gate_branch` aliases into `strong_risk_exact_gate_branch` and "
            "warn if branch provenance remains missing."
        ),
        "whyItHelps": "Analysts can trace a packet back to the exact saved branch or know when branch-level proof is missing.",
        "whyNoModelBehaviorChange": "This exposes existing provenance and does not alter gate admission or labels.",
    },
    "SCHEMA-004": {
        "behaviorAdded": (
            "Review packets normalize saved `gateType`/`gate_type` aliases into `strong_risk_gate_type` and warn when "
            "Strong Risk gate-type provenance is absent."
        ),
        "whyItHelps": "Analysts can distinguish the broad gate family from score-only or retrospective-looking rows.",
        "whyNoModelBehaviorChange": "This exposes saved provenance and does not modify any Strong Risk gate.",
    },
    "SCHEMA-005": {
        "behaviorAdded": (
            "Review packets now include `false_positive_advisory` entries derived from saved suppressors, and warn when "
            "suppressor/conflict reasons are missing."
        ),
        "whyItHelps": "Analysts get an explicit checklist for public power-user, near-certainty, stale, or specialist context.",
        "whyNoModelBehaviorChange": "Suppressor advice is advisory only and never suppresses, downgrades, rescoring, or reroutes a case.",
    },
    "SCHEMA-006": {
        "behaviorAdded": (
            "Review packets normalize additional condition-id aliases and warn when condition-level navigation is missing."
        ),
        "whyItHelps": "Analysts can anchor packet review to the correct market or know when source-path navigation must be used instead.",
        "whyNoModelBehaviorChange": "This is navigation metadata only and does not broaden market scope or single-market condition handling.",
    },
    "SCHEMA-007": {
        "behaviorAdded": (
            "Review packets normalize transaction/hash aliases into `trade_id`, copy trade identifiers into source navigation, "
            "and warn when trade-level navigation is unavailable."
        ),
        "whyItHelps": "Analysts can jump from a packet to the exact trade/transaction when saved fields allow it.",
        "whyNoModelBehaviorChange": "This is navigation metadata only and does not infer transaction evidence.",
    },
    "SCHEMA-008": {
        "behaviorAdded": (
            "Review packets normalize market title/question aliases into `market`, copy market text into source navigation, "
            "and warn when market display text is unavailable."
        ),
        "whyItHelps": "Analysts can orient the packet to the correct market without relying on score text.",
        "whyNoModelBehaviorChange": "This is display/navigation metadata only and does not broaden event or market scope.",
    },
    "SCHEMA-009": {
        "behaviorAdded": (
            "Review packets normalize additional wallet aliases, copy wallet identifiers into source navigation, and warn "
            "when wallet address is unavailable."
        ),
        "whyItHelps": "Analysts can inspect wallet-specific evidence when present and avoid inferring wallet linkage when absent.",
        "whyNoModelBehaviorChange": "This is navigation metadata only and does not create linkage, reroute, or rescore cases.",
    },
    "FP-001": {
        "behaviorAdded": (
            "Review packets add a `no_independent_hard_evidence` advisory when hard-evidence source labels are absent."
        ),
        "whyItHelps": "Analysts get an explicit reminder to verify accepted independent evidence before escalation.",
        "whyNoModelBehaviorChange": "The advisory is reporting-only and cannot suppress, downgrade, rescore, reroute, or change eligibility.",
    },
    "FP-002": {
        "behaviorAdded": (
            "Review packets attach a `high_volume_public_user` advisory with analyst questions and forbidden-use guardrails."
        ),
        "whyItHelps": "Analysts can separate public power-user behavior from insider-style structure.",
        "whyNoModelBehaviorChange": "The advisory is reporting-only and cannot alter any detector output.",
    },
    "FP-003": {
        "behaviorAdded": "Review packets attach a `near_certainty` advisory with analyst questions and forbidden-use guardrails.",
        "whyItHelps": "Analysts are prompted to check whether the entry was already effectively obvious.",
        "whyNoModelBehaviorChange": "The advisory is reporting-only and does not alter timing, repricing, or gate logic.",
    },
    "FP-004": {
        "behaviorAdded": (
            "Review packets attach a `stale_or_resolution_gap` advisory with analyst questions and forbidden-use guardrails."
        ),
        "whyItHelps": "Analysts are prompted to distinguish public-lag or stale-resolution exploitation from private-information behavior.",
        "whyNoModelBehaviorChange": "The advisory is reporting-only and does not alter labels, gates, or resolution-gap handling.",
    },
    "FP-005": {
        "behaviorAdded": (
            "Review packets preserve `weak_economic_history` suppressor context as an advisory pattern when saved fields expose it."
        ),
        "whyItHelps": "Analysts are prompted to check whether the wallet history is too thin to support escalation.",
        "whyNoModelBehaviorChange": "The advisory is reporting-only and does not alter wallet history scoring or thresholds.",
    },
    "FP-006": {
        "behaviorAdded": (
            "Review packets add a `funding_unknown` advisory when saved funding evidence is absent or unknown."
        ),
        "whyItHelps": "Analysts are reminded that funding cannot be claimed until fresh trace-enabled evidence exists.",
        "whyNoModelBehaviorChange": "Funding unavailable remains `unknown`, not `none`; no funding eligibility or HER routing changes.",
    },
    "FP-007": {
        "behaviorAdded": "Review packets add a `gate_trace_missing` advisory when saved gate trace provenance is absent.",
        "whyItHelps": "Analysts are warned not to interpret exact gate behavior when trace evidence is missing.",
        "whyNoModelBehaviorChange": "The advisory is reporting-only and does not alter Strong Risk gate traces or gate behavior.",
    },
    "FP-008": {
        "behaviorAdded": "Review packets add a `retrospective_only` advisory when saved evidence is marked retrospective-only.",
        "whyItHelps": "Analysts are prompted to separate live-detectable leads from after-the-fact correctness.",
        "whyNoModelBehaviorChange": "The advisory is reporting-only and does not alter live/replay routing, scoring, or labels.",
    },
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
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("summary")
    return value if isinstance(value, Mapping) else {}


def _issues(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("issues")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def build_patch_report(
    *,
    boundary: Mapping[str, Any] | None = None,
    boundary_path: Path | None = None,
    review_packets_path: Path | None = None,
    review_index_path: Path | None = None,
    analyst_bundle_path: Path | None = None,
    selected_issue_ids: Sequence[str] = SELECTED_ISSUE_IDS,
    previously_implemented_issue_ids: Sequence[str] = (),
) -> dict[str, Any]:
    boundary = boundary or {}
    issues = _issues(boundary)
    selected_issue_ids = tuple(str(issue_id) for issue_id in selected_issue_ids)
    previously_implemented_issue_ids = tuple(str(issue_id) for issue_id in previously_implemented_issue_ids)
    selected = [issue for issue in issues if issue.get("issueId") in selected_issue_ids]
    completed_ids = {str(issue.get("issueId")) for issue in selected}
    completed_ids.update(previously_implemented_issue_ids)
    remaining_safe = [
        issue
        for issue in issues
        if issue.get("classification") in SAFE_CATEGORIES
        and issue.get("safeImplementationAllowed") is True
        and issue.get("issueId") not in completed_ids
    ]
    rfc_only = [issue for issue in issues if issue.get("classification") == "rfc_only_model_behavior_change"]
    rpc_blocked = [issue for issue in issues if issue.get("classification") == "blocked_by_rpc"]
    exact_behavior = [
        {"issueId": issue_id, **BEHAVIOR_BY_ISSUE.get(issue_id, {
            "behaviorAdded": "Selected reporting/schema/navigation issue is documented as safely handled.",
            "whyItHelps": "The analyst-facing output is easier to interpret.",
            "whyNoModelBehaviorChange": "The change is reporting-only.",
        })}
        for issue_id in selected_issue_ids
    ]
    return {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(),
            "selected_issue_count": len(selected),
            "selected_issue_ids": list(selected_issue_ids),
            "previously_implemented_issue_ids": list(previously_implemented_issue_ids),
            "safe_fixes_implemented": len(exact_behavior),
            "remaining_safe_fix_count": len(remaining_safe),
            "rfc_only_issues_left_untouched": len(rfc_only),
            "rpc_blocked_issues_left_untouched": len(rpc_blocked),
            "model_behavior_changed": False,
            "false_positive_library_used_for_scoring": False,
            "read_only_reporting_patch": True,
        },
        "selected_issues": selected,
        "source_boundary_categories": {str(issue.get("issueId")): issue.get("classification") for issue in selected},
        "files_changed": CHANGED_FILES,
        "exact_behavior_added": exact_behavior,
        "tests_added_updated": [
            "tests/test_unique_review_packets.py",
            "tests/test_review_output_index.py",
            "tests/test_analyst_review_quality_suite.py",
            "tests/test_reporting_schema_patch_report.py",
        ],
        "remaining_safe_fixes": remaining_safe,
        "rfc_only_issues_left_untouched": rfc_only,
        "rpc_blocked_issues_left_untouched": rpc_blocked,
        "artifacts_consulted": {
            "implementation_boundary": str(boundary_path or ""),
            "review_packets": str(review_packets_path or ""),
            "review_output_index": str(review_index_path or ""),
            "analyst_handoff_bundle": str(analyst_bundle_path or ""),
        },
        "limitations": [
            "This patch report describes reporting/schema/navigation changes only.",
            "It does not approve model, scoring, gate, HER, funding eligibility, or false-positive suppressor behavior changes.",
            "RPC/funding readiness remains governed by the latest gate decision readiness artifacts.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = _summary(payload)
    lines = [
        "# Reporting / Schema / Navigation Patch Report",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Selected issues: {', '.join(summary.get('selected_issue_ids') or [])}",
        f"- Safe fixes implemented: {summary.get('safe_fixes_implemented', 0)}",
        f"- Remaining safe fixes: {summary.get('remaining_safe_fix_count', 0)}",
        f"- RFC-only issues left untouched: {summary.get('rfc_only_issues_left_untouched', 0)}",
        f"- RPC-blocked issues left untouched: {summary.get('rpc_blocked_issues_left_untouched', 0)}",
        f"- Model behavior changed: {summary.get('model_behavior_changed', False)}",
        "",
        "## Selected Boundary Issues",
    ]
    for issue in payload.get("selected_issues") or []:
        lines.append(
            f"- {issue.get('issueId')}: {issue.get('classification')} - {issue.get('issueSummary')}"
        )
    lines.extend(["", "## Behavior Added"])
    for behavior in payload.get("exact_behavior_added") or []:
        lines.append(f"- {behavior.get('issueId')}: {behavior.get('behaviorAdded')}")
        lines.append(f"  - Analyst value: {behavior.get('whyItHelps')}")
        lines.append(f"  - Model boundary: {behavior.get('whyNoModelBehaviorChange')}")
    lines.extend(["", "## Files Changed"])
    for path in payload.get("files_changed") or []:
        lines.append(f"- {path}")
    lines.extend(["", "## Tests Added Or Updated"])
    for path in payload.get("tests_added_updated") or []:
        lines.append(f"- {path}")
    lines.extend(["", "## Remaining Safe Fixes"])
    remaining = payload.get("remaining_safe_fixes") if isinstance(payload.get("remaining_safe_fixes"), list) else []
    if not remaining:
        lines.append("- none")
    for issue in remaining[:20]:
        lines.append(f"- {issue.get('issueId')}: {issue.get('classification')} - {issue.get('issueSummary')}")
    lines.extend(["", "## RFC-Only Issues Left Untouched"])
    rfc_only = payload.get("rfc_only_issues_left_untouched") if isinstance(payload.get("rfc_only_issues_left_untouched"), list) else []
    if not rfc_only:
        lines.append("- none")
    for issue in rfc_only:
        lines.append(f"- {issue.get('issueId')}: {issue.get('issueSummary')}")
    lines.extend(["", "## RPC-Blocked Issues Left Untouched"])
    rpc_blocked = payload.get("rpc_blocked_issues_left_untouched") if isinstance(payload.get("rpc_blocked_issues_left_untouched"), list) else []
    if not rpc_blocked:
        lines.append("- none")
    for issue in rpc_blocked:
        lines.append(f"- {issue.get('issueId')}: {issue.get('issueSummary')}")
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(
    payload: Mapping[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    output_stem: str = "reporting_schema_patch_report_20260505",
) -> dict[str, str]:
    resolved_output_dir = _resolve(output_dir) or output_dir
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    json_path = resolved_output_dir / f"{output_stem}.json"
    markdown_path = resolved_output_dir / f"{output_stem}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the approved bounded reporting/schema/navigation patch report.")
    parser.add_argument("--boundary", type=Path, default=None)
    parser.add_argument("--review-packets", type=Path, default=None)
    parser.add_argument("--review-index", type=Path, default=None)
    parser.add_argument("--analyst-bundle", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--selected-issues", default=",".join(SELECTED_ISSUE_IDS))
    parser.add_argument("--previously-implemented-issues", default="")
    parser.add_argument("--output-stem", default="reporting_schema_patch_report_20260505")
    args = parser.parse_args(argv)
    selected_issue_ids = tuple(item.strip() for item in args.selected_issues.split(",") if item.strip())
    previously_implemented_issue_ids = tuple(item.strip() for item in args.previously_implemented_issues.split(",") if item.strip())
    boundary_path = _resolve(args.boundary) if args.boundary else _latest_file(DEFAULT_OUTPUT_DIR, "implementation_boundary_*.json")
    review_packets_path = _resolve(args.review_packets) if args.review_packets else _latest_file(Path("review_packets"), "unique_review_packets_*.json")
    review_index_path = _resolve(args.review_index) if args.review_index else _latest_file(Path("review_index_outputs"), "review_output_index_*.json")
    analyst_bundle_path = _resolve(args.analyst_bundle) if args.analyst_bundle else _latest_file(
        Path("analyst_review_bundles"), "analyst_review_bundle_*.json"
    )
    payload = build_patch_report(
        boundary=_load_json(boundary_path),
        boundary_path=boundary_path,
        review_packets_path=review_packets_path,
        review_index_path=review_index_path,
        analyst_bundle_path=analyst_bundle_path,
        selected_issue_ids=selected_issue_ids or SELECTED_ISSUE_IDS,
        previously_implemented_issue_ids=previously_implemented_issue_ids,
    )
    outputs = write_outputs(payload, args.output_dir, output_stem=args.output_stem)
    print(f"Reporting/schema patch report JSON: {outputs['json_path']}")
    print(f"Reporting/schema patch report markdown: {outputs['markdown_path']}")
    print(f"Selected issues: {', '.join(payload['summary']['selected_issue_ids'])}")
    print(f"Model behavior changed: {payload['summary']['model_behavior_changed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
