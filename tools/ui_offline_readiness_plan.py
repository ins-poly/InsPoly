from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = Path("ui_readiness_outputs")
DEFAULT_OUTPUT_DIR = Path("ui_readiness_outputs")


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


def build_plan(audit_payload: Mapping[str, Any], *, source_path: Path | None = None) -> dict[str, Any]:
    summary = audit_payload.get("summary") if isinstance(audit_payload.get("summary"), Mapping) else {}
    dependency_rows = audit_payload.get("dependencyRows") if isinstance(audit_payload.get("dependencyRows"), list) else []
    runtime_dependencies = [row for row in dependency_rows if isinstance(row, Mapping) and row.get("runtimeRequiredForUiBoot")]
    plan_steps = [
        {
            "stepId": "UI-OFFLINE-001",
            "title": "Document current CDN boot dependencies",
            "allowedNow": True,
            "implementationType": "documentation_only",
            "acceptanceCriteria": "Operator handoff names React, ReactDOM, Babel, and Google Fonts as runtime boot dependencies.",
        },
        {
            "stepId": "UI-OFFLINE-002",
            "title": "Create a separate approved vendoring plan before code changes",
            "allowedNow": True,
            "implementationType": "plan_only",
            "acceptanceCriteria": "Plan identifies target local asset paths and rollback strategy without editing UI files.",
        },
        {
            "stepId": "UI-OFFLINE-003",
            "title": "Vendor or bundle frontend dependencies",
            "allowedNow": False,
            "implementationType": "requires_explicit_ui_implementation_approval",
            "acceptanceCriteria": "Only after approval: UI can boot without CDN while preserving browser contracts.",
        },
    ]
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "ui_offline_readiness_plan",
        "sourceUiAuditPath": str(source_path or ""),
        "summary": {
            "offlineRisk": summary.get("offlineRisk", "unknown"),
            "runtimeRequiredDependencyCount": summary.get("runtimeRequiredDependencyCount", 0),
            "cdnRuntimeDependencyCount": summary.get("cdnRuntimeDependencyCount", 0),
            "googleFontDependencyCount": summary.get("googleFontDependencyCount", 0),
            "planStepCount": len(plan_steps),
            "implementationApproved": False,
            "modelBehaviorChanged": False,
            "uiRuntimeChanged": False,
            "oldOutputsMutated": False,
        },
        "runtimeDependencies": runtime_dependencies,
        "planSteps": plan_steps,
        "forbiddenWithoutApproval": [
            "Do not rewrite the browser UI.",
            "Do not vendor CDN assets or change script tags without explicit UI implementation approval.",
            "Do not change Python report payload contracts as part of offline-readiness planning.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# UI Offline Readiness Plan",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Offline risk: {summary.get('offlineRisk', '')}",
        f"- Runtime dependencies: {summary.get('runtimeRequiredDependencyCount', 0)}",
        f"- Implementation approved: {summary.get('implementationApproved', False)}",
        f"- UI runtime changed: {summary.get('uiRuntimeChanged', False)}",
        "",
        "## Plan Steps",
    ]
    for step in payload.get("planSteps") or []:
        if isinstance(step, Mapping):
            lines.append(f"- `{step.get('stepId', '')}` allowedNow={step.get('allowedNow', False)}: {step.get('title', '')}")
    lines.extend(["", "## Forbidden Without Approval"])
    for item in payload.get("forbiddenWithoutApproval") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"ui_offline_readiness_plan_{stamp}.json"
    markdown_path = resolved / f"ui_offline_readiness_plan_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a plan-only offline UI readiness package from runtime dependency audit.")
    parser.add_argument("--audit", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    source = args.audit or _latest_file(DEFAULT_INPUT_DIR, "ui_runtime_dependency_audit_*.json")
    payload = build_plan(_load_json(source), source_path=source)
    outputs = write_outputs(payload, args.output_dir)
    print(f"UI offline readiness plan JSON: {outputs['json_path']}")
    print(f"UI offline readiness plan markdown: {outputs['markdown_path']}")
    print(f"Offline risk: {payload.get('summary', {}).get('offlineRisk', '')}")
    print(f"UI runtime changed: {payload.get('summary', {}).get('uiRuntimeChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
