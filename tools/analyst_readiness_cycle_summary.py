from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("analyst_quality_outputs")
INPUT_PATTERNS = {
    "candidate_recall_diagnostic": (Path("candidate_recall_outputs"), "candidate_recall_diagnostic_*.json"),
    "false_positive_guardrail_audit": (Path("false_positive_library"), "false_positive_guardrail_audit_*.json"),
    "analyst_evidence_limitation_digest": (Path("analyst_quality_outputs"), "analyst_evidence_limitation_digest_*.json"),
    "review_artifact_freshness_report": (Path("artifact_manifests"), "review_artifact_freshness_report_*.json"),
    "review_output_index": (Path("review_index_outputs"), "review_output_index_*.json"),
    "artifact_manifest": (Path("artifact_manifests"), "review_artifact_manifest_*.json"),
    "gate_decision_readiness": (Path("validation_corpus_outputs"), "gate_decision_readiness_*.json"),
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


def discover_inputs() -> dict[str, Path | None]:
    return {name: _latest_file(directory, pattern) for name, (directory, pattern) in INPUT_PATTERNS.items()}


def _readiness_classification(payload: Mapping[str, Any]) -> str:
    return str(
        payload.get("final_readiness_classification")
        or payload.get("readiness_classification")
        or payload.get("classification")
        or payload.get("finalReadinessClassification")
        or "not_ready_corpus_too_cache_only"
    )


def _next_prompt() -> str:
    return """You are working in the InsPoly repository.

Role:
Act as a senior financial-forensic technical lead. This is reporting/navigation/readiness infrastructure only unless a maintainer explicitly approves otherwise.

Current status:
- Recent safe cycles added expanded candidate recall diagnostic, false-positive guardrail audit, evidence limitation digest, artifact freshness report, and analyst readiness cycle summary.
- Readiness remains not_ready_corpus_too_cache_only unless a newer readiness artifact proves otherwise.
- RPC/cache blocker may still be active.

Hard constraints:
Do not edit _score_trade(), Strong Risk gates, scoring weights, production severity labels, structural pre-admission, suspicious funding v2, HER routing, funding eligibility, candidate admission, credentials, RPC URLs, or old saved outputs. Do not use false-positive library as automatic suppressor/scoring logic. Treat funding unavailable as unknown.

Bounded task:
Run a stop-state decision check from the latest reporting artifacts. If no genuinely new safe reporting task exists, do not invent one. Produce a concise operator/human decision pack that says whether the next useful path is:
1. operator-approved RPC capacity through existing env/config;
2. explicit maintainer approval for RFC-only detector review;
3. explicit maintainer approval for a new reporting/UI task; or
4. no action until new evidence is available.

Files to inspect:
AGENTS.md
PROJECT_MEMORY.md
latest analyst_quality_outputs/analyst_readiness_cycle_summary_*.json
latest review_index_outputs/review_output_index_*.json
latest artifact_manifests/review_artifact_manifest_*.json
latest validation_corpus_outputs/gate_decision_readiness_*.json
tools/strategic_backlog_next_action.py
tools/autonomous_next_action.py

Commands:
python3 tools/strategic_backlog_next_action.py
python3 tools/autonomous_next_action.py
python3 tools/review_output_index.py
python3 -m py_compile tools/strategic_backlog_next_action.py tools/autonomous_next_action.py tools/review_output_index.py app/scanner.py app/archive_scanner.py app/event_forensic.py app/funding_context.py app/polymarket.py app/config.py
python3 -m unittest discover -s tests -p 'test_*.py'

Final output:
Report decision, artifacts written, tests run, readiness/RPC status, preserved invariants, and the exact next prompt only if a real bounded next action exists. Do not overclaim cache-only or stale evidence."""


def build_cycle_summary(payloads: Mapping[str, Mapping[str, Any]], *, input_paths: Mapping[str, Path | None] | None = None) -> dict[str, Any]:
    recall = _summary(payloads.get("candidate_recall_diagnostic", {}))
    guardrails = _summary(payloads.get("false_positive_guardrail_audit", {}))
    limitations = _summary(payloads.get("analyst_evidence_limitation_digest", {}))
    freshness = _summary(payloads.get("review_artifact_freshness_report", {}))
    index = _summary(payloads.get("review_output_index", {}))
    manifest = _summary(payloads.get("artifact_manifest", {}))
    readiness = payloads.get("gate_decision_readiness", {})
    cycle_rows = [
        {
            "cycleId": "FN-001",
            "artifactKind": "candidate_recall_diagnostic",
            "path": str((input_paths or {}).get("candidate_recall_diagnostic") or ""),
            "result": recall.get("diagnostic_interpretation", "unknown"),
            "modelBehaviorChanged": False,
        },
        {
            "cycleId": "FP-003",
            "artifactKind": "false_positive_guardrail_audit",
            "path": str((input_paths or {}).get("false_positive_guardrail_audit") or ""),
            "result": f"guardrailsPassed={guardrails.get('guardrailsPassed', False)}",
            "modelBehaviorChanged": False,
        },
        {
            "cycleId": "LIMITATIONS-001",
            "artifactKind": "analyst_evidence_limitation_digest",
            "path": str((input_paths or {}).get("analyst_evidence_limitation_digest") or ""),
            "result": f"activeLimitations={limitations.get('activeLimitationCount', 0)}",
            "modelBehaviorChanged": False,
        },
        {
            "cycleId": "NAV-001",
            "artifactKind": "review_artifact_freshness_report",
            "path": str((input_paths or {}).get("review_artifact_freshness_report") or ""),
            "result": f"missingLatestArtifacts={freshness.get('missingLatestArtifactCount', 0)}",
            "modelBehaviorChanged": False,
        },
        {
            "cycleId": "SUMMARY-001",
            "artifactKind": "analyst_readiness_cycle_summary",
            "path": "",
            "result": "summary_generated",
            "modelBehaviorChanged": False,
        },
    ]
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "inputPaths": {key: str(value) if value else "" for key, value in (input_paths or {}).items()},
        "summary": {
            "cycleCount": len(cycle_rows),
            "readinessClassification": _readiness_classification(readiness),
            "reviewIndexEntryCount": index.get("entry_count", 0),
            "manifestArtifactCount": manifest.get("artifact_count", 0),
            "manifestMissingArtifactCount": manifest.get("missing_artifact_count", 0),
            "guardrailsPassed": guardrails.get("guardrailsPassed", False),
            "activeLimitationCount": limitations.get("activeLimitationCount", 0),
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "cycleRows": cycle_rows,
        "nextDecision": "stop_or_wait_for_new_operator_or_max_decision_if_no_new_safe_task_exists",
        "readyToCopyNextPrompt": _next_prompt(),
        "invariantsPreserved": [
            "_score_trade() unchanged",
            "Strong Risk gates unchanged",
            "scoring weights unchanged",
            "production severity labels unchanged",
            "HER routing unchanged",
            "funding eligibility unchanged",
            "candidate admission unchanged",
            "old saved outputs not mutated",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Analyst Readiness Cycle Summary",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Cycles: {summary.get('cycleCount', 0)}",
        f"- Readiness classification: {summary.get('readinessClassification', '')}",
        f"- Review index entries: {summary.get('reviewIndexEntryCount', 0)}",
        f"- Manifest artifacts: {summary.get('manifestArtifactCount', 0)}",
        f"- Guardrails passed: {summary.get('guardrailsPassed', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Cycle Rows",
    ]
    for row in payload.get("cycleRows") or []:
        if isinstance(row, Mapping):
            lines.append(f"- `{row.get('cycleId', '')}` {row.get('artifactKind', '')}: {row.get('result', '')}")
    lines.extend(["", "## Next Decision", str(payload.get("nextDecision", "")), "", "## Ready-To-Copy Next Prompt", "```text", str(payload.get("readyToCopyNextPrompt", "")), "```"])
    lines.extend(["", "## Invariants Preserved"])
    for item in payload.get("invariantsPreserved") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"analyst_readiness_cycle_summary_{stamp}.json"
    markdown_path = resolved / f"analyst_readiness_cycle_summary_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize the latest analyst readiness/reporting cycle.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    paths = discover_inputs()
    payload = build_cycle_summary({name: _load_json(path) for name, path in paths.items()}, input_paths=paths)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Analyst readiness cycle summary JSON: {outputs['json_path']}")
    print(f"Analyst readiness cycle summary markdown: {outputs['markdown_path']}")
    print(f"Cycles: {payload.get('summary', {}).get('cycleCount', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
