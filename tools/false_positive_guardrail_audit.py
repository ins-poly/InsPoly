from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("false_positive_library")
ARTIFACT_PATTERNS = {
    "false_positive_library": (Path("false_positive_library"), "false_positive_pattern_library_*.json"),
    "false_positive_explanation_report": (Path("false_positive_library"), "false_positive_explanation_report_*.json"),
    "packet_quality_report": (Path("analyst_quality_outputs"), "packet_quality_report_*.json"),
    "candidate_recall_diagnostic": (Path("candidate_recall_outputs"), "candidate_recall_diagnostic_*.json"),
    "analyst_decision_sidecar": (Path("analyst_sidecars"), "analyst_decision_sidecar_*.json"),
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


def discover_inputs() -> dict[str, Path | None]:
    return {name: _latest_file(directory, pattern) for name, (directory, pattern) in ARTIFACT_PATTERNS.items()}


def _summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("summary")
    return value if isinstance(value, Mapping) else {}


def _bool(summary: Mapping[str, Any], *keys: str) -> bool:
    for key in keys:
        if key in summary:
            return bool(summary.get(key))
    return False


def _library_violations(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    violations = []
    patterns = payload.get("patterns")
    if not isinstance(patterns, list):
        return violations
    for pattern in patterns:
        if not isinstance(pattern, Mapping):
            continue
        playbook = pattern.get("analyst_playbook") if isinstance(pattern.get("analyst_playbook"), Mapping) else {}
        if playbook.get("automatic_action_allowed") is not False:
            violations.append(
                {
                    "artifactKind": "false_positive_library",
                    "patternKey": pattern.get("pattern_key", "unknown"),
                    "violation": "automatic_action_allowed_not_false",
                }
            )
    return violations


def build_guardrail_audit(
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    input_paths: Mapping[str, Path | None] | None = None,
) -> dict[str, Any]:
    rows = []
    violations = []
    for kind in ARTIFACT_PATTERNS:
        payload = payloads.get(kind, {})
        summary = _summary(payload)
        path = (input_paths or {}).get(kind)
        if kind == "false_positive_library":
            artifact_violations = _library_violations(payload)
            violations.extend(artifact_violations)
            automatic = bool(artifact_violations)
            used_for_scoring = False
        elif kind == "false_positive_explanation_report":
            automatic = _bool(summary, "automaticActionAllowed", "automatic_action_allowed")
            used_for_scoring = _bool(summary, "falsePositiveLibraryUsedForScoring", "false_positive_library_used_for_scoring")
        elif kind == "packet_quality_report":
            warnings = payload.get("warningsSummary") if isinstance(payload.get("warningsSummary"), Mapping) else {}
            automatic = _bool(warnings, "automaticActionAllowed", "automatic_action_allowed")
            used_for_scoring = _bool(warnings, "falsePositiveLibraryUsedForScoring", "false_positive_library_used_for_scoring")
        elif kind == "candidate_recall_diagnostic":
            automatic = _bool(summary, "automatic_routing_allowed")
            used_for_scoring = False
        elif kind == "analyst_decision_sidecar":
            automatic = _bool(summary, "productionUseAllowed", "scoringUseAllowed", "routingUseAllowed")
            used_for_scoring = _bool(summary, "scoringChanged")
        else:
            automatic = False
            used_for_scoring = False
        if automatic:
            violations.append({"artifactKind": kind, "violation": "automatic_action_or_routing_allowed"})
        if used_for_scoring:
            violations.append({"artifactKind": kind, "violation": "false_positive_library_used_for_scoring"})
        rows.append(
            {
                "artifactKind": kind,
                "path": str(path or ""),
                "exists": bool(path and path.exists()),
                "automaticActionAllowed": automatic,
                "falsePositiveLibraryUsedForScoring": used_for_scoring,
                "modelBehaviorChanged": _bool(summary, "modelBehaviorChanged", "model_behavior_changed"),
                "scoringChanged": _bool(summary, "scoringChanged", "scoring_changed"),
                "gatesChanged": _bool(summary, "gatesChanged", "gates_changed"),
                "herRoutingChanged": _bool(summary, "herRoutingChanged", "her_routing_changed"),
                "fundingEligibilityChanged": _bool(summary, "fundingEligibilityChanged", "funding_eligibility_changed"),
                "candidateAdmissionChanged": _bool(summary, "candidateAdmissionChanged", "candidate_admission_changed"),
            }
        )
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "summary": {
            "artifactCount": len(rows),
            "existingArtifactCount": sum(1 for row in rows if row["exists"]),
            "violationCount": len(violations),
            "guardrailsPassed": len(violations) == 0,
            "automaticActionAllowed": False,
            "falsePositiveLibraryUsedForScoring": False,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
        },
        "artifactRows": rows,
        "violations": violations,
        "requiredGuardrails": [
            "false-positive patterns may explain analyst caution only",
            "false-positive matches must not suppress, downgrade, reroute, rescore, admit, or reject candidates",
            "any production suppressor use requires a separate RFC, fresh validation, and explicit approval",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# False-Positive Guardrail Audit",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Artifacts: {summary.get('existingArtifactCount', 0)}/{summary.get('artifactCount', 0)}",
        f"- Guardrails passed: {summary.get('guardrailsPassed', False)}",
        f"- Violations: {summary.get('violationCount', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Artifact Rows",
    ]
    for row in payload.get("artifactRows") or []:
        if isinstance(row, Mapping):
            lines.append(
                f"- `{row.get('artifactKind', '')}`: exists={row.get('exists', False)}, "
                f"automaticActionAllowed={row.get('automaticActionAllowed', False)}, "
                f"usedForScoring={row.get('falsePositiveLibraryUsedForScoring', False)}"
            )
    lines.extend(["", "## Violations"])
    violations = payload.get("violations") if isinstance(payload.get("violations"), list) else []
    if not violations:
        lines.append("- none")
    for item in violations:
        if isinstance(item, Mapping):
            lines.append(f"- {item.get('artifactKind', '')}: {item.get('violation', '')}")
    lines.extend(["", "## Required Guardrails"])
    for item in payload.get("requiredGuardrails") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"false_positive_guardrail_audit_{stamp}.json"
    markdown_path = resolved / f"false_positive_guardrail_audit_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit false-positive advisory guardrails without changing detector behavior.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    paths = discover_inputs()
    payloads = {name: _load_json(path) for name, path in paths.items()}
    payload = build_guardrail_audit(payloads, input_paths=paths)
    outputs = write_outputs(payload, args.output_dir)
    print(f"False-positive guardrail audit JSON: {outputs['json_path']}")
    print(f"False-positive guardrail audit markdown: {outputs['markdown_path']}")
    print(f"Guardrails passed: {payload.get('summary', {}).get('guardrailsPassed', False)}")
    print(f"Violations: {payload.get('summary', {}).get('violationCount', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
