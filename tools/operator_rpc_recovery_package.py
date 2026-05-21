from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import load_runtime_env, runtime_env_float, runtime_env_int
from app.funding_context import endpoint_label
from app.polymarket import polygon_rpc_urls

DEFAULT_OUTPUT_DIR = Path("validation_corpus_outputs")
DEFAULT_HEALTHCHECK_DIR = Path("funding_health_outputs")


def _resolve(path: Path | str | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _latest_file(directory: Path, pattern: str) -> Path | None:
    root = _resolve(directory) or directory
    if not root.exists():
        return None
    candidates = list(root.glob(pattern))
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name)) if candidates else None


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _runtime_config(*, repo_root: Path = REPO_ROOT, endpoint_urls: list[str] | None = None) -> dict[str, Any]:
    load_runtime_env(repo_root)
    urls = endpoint_urls if endpoint_urls is not None else polygon_rpc_urls()
    return {
        "runtime_env_file_present": bool((repo_root / ".inspoly_runtime.env").exists()),
        "configured_endpoint_count": len(urls),
        "active_endpoint_labels": [endpoint_label(url) for url in urls],
        "runtime_config_observed_without_secrets": {
            "configured_endpoint_count": len(urls),
            "INSPOLY_POLYGON_RPC_GETLOGS_BLOCK_CHUNK": runtime_env_int(
                "INSPOLY_POLYGON_RPC_GETLOGS_BLOCK_CHUNK", 1500, minimum=0
            ),
            "INSPOLY_POLYGON_RPC_MAX_CONCURRENCY": runtime_env_int(
                "INSPOLY_POLYGON_RPC_MAX_CONCURRENCY", 1, minimum=0
            ),
            "INSPOLY_POLYGON_RPC_MAX_RETRIES": runtime_env_int("INSPOLY_POLYGON_RPC_MAX_RETRIES", 3, minimum=0),
            "INSPOLY_POLYGON_RPC_MIN_INTERVAL_SECONDS": runtime_env_float(
                "INSPOLY_POLYGON_RPC_MIN_INTERVAL_SECONDS", 1.0, minimum=0.0
            ),
            "INSPOLY_POLYGON_RPC_REQUEST_TIMEOUT_SECONDS": runtime_env_float(
                "INSPOLY_POLYGON_RPC_REQUEST_TIMEOUT_SECONDS", 10.0, minimum=0.0
            ),
            "INSPOLY_VALIDATION_MAX_FUNDING_TRACES_PER_BUNDLE": runtime_env_int(
                "INSPOLY_VALIDATION_MAX_FUNDING_TRACES_PER_BUNDLE", 50, minimum=0
            ),
            "INSPOLY_VALIDATION_MAX_FUNDING_TRACE_FAILURES_PER_BUNDLE": runtime_env_int(
                "INSPOLY_VALIDATION_MAX_FUNDING_TRACE_FAILURES_PER_BUNDLE", 10, minimum=0
            ),
            "INSPOLY_VALIDATION_MAX_LOG_CHUNKS_PER_TRACE": runtime_env_int(
                "INSPOLY_VALIDATION_MAX_LOG_CHUNKS_PER_TRACE", 4, minimum=0
            ),
            "INSPOLY_VALIDATION_MAX_CONSECUTIVE_RPC_FAILURES": runtime_env_int(
                "INSPOLY_VALIDATION_MAX_CONSECUTIVE_RPC_FAILURES", 5, minimum=0
            ),
        },
    }


def _latest_paths(
    *,
    output_dir: Path,
    healthcheck: Path | None = None,
    trace_diagnostic: Path | None = None,
    prewarm: Path | None = None,
    smoke_corpus: Path | None = None,
    terminal_failure: Path | None = None,
    readiness: Path | None = None,
    action: Path | None = None,
) -> dict[str, Path | None]:
    return {
        "healthcheck": _resolve(healthcheck) or _latest_file(DEFAULT_HEALTHCHECK_DIR, "funding_resolver_healthcheck_*.json"),
        "trace_method_diagnostic": _resolve(trace_diagnostic)
        or _latest_file(output_dir, "trace_method_diagnostic_*.json"),
        "prewarm": _resolve(prewarm) or _latest_file(output_dir, "funding_cache_prewarm_*.json"),
        "smoke_corpus": _resolve(smoke_corpus) or _latest_file(output_dir, "post_v2_corpus_*.json"),
        "terminal_failure": _resolve(terminal_failure)
        or _latest_file(output_dir, "validation_corpus_terminal_failure_*.json"),
        "readiness": _resolve(readiness) or _latest_file(output_dir, "gate_decision_readiness_*.json"),
        "autonomous_next_action": _resolve(action) or _latest_file(output_dir, "autonomous_next_action_*.json"),
    }


def _configuration_status(
    *,
    operator_approved_config_present: bool,
    previous_package: Mapping[str, Any],
    active_endpoint_labels: list[str],
) -> str:
    if operator_approved_config_present:
        return "operator_approved_rpc_configuration_present"
    previous_labels = previous_package.get("active_endpoint_labels")
    if isinstance(previous_labels, list) and [str(item) for item in previous_labels] != active_endpoint_labels:
        return "rpc_endpoint_labels_changed_operator_approval_not_recorded"
    return "existing_env_config_rechecked_no_new_operator_approved_rpc_configuration_detected"


def _trace_observations(trace: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "classification": trace.get("classification", ""),
        "recommended_next_step": trace.get("recommended_next_step", ""),
        "configured_getlogs_block_chunk": trace.get("configured_getlogs_block_chunk", ""),
        "method_summary": trace.get("method_summary", {}),
        "interpretation": (
            "The trace method exists, but endpoint errors or prior broad-workload failures still require "
            "operator RPC capacity/configuration before broader validation evidence is claimed."
        ),
    }


def _prewarm_observations(prewarm: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "windows_found": prewarm.get("wallet_time_windows_found", prewarm.get("windows_found", "")),
        "windows_attempted": prewarm.get("wallet_time_windows_attempted", prewarm.get("traces_requested", "")),
        "cache_hits": prewarm.get("cache_hits_observed", prewarm.get("cache_hits", "")),
        "cache_misses": prewarm.get("cache_misses_observed", prewarm.get("cache_misses", "")),
        "cache_writes": prewarm.get("cache_writes", ""),
        "trace_outcome_status_counts": prewarm.get("trace_outcome_status_counts", {}),
        "rpc_failures": prewarm.get("rpc_failures", ""),
        "trace_timeouts_observed": prewarm.get("trace_timeouts_observed", ""),
        "targets_left_unprewarmed": prewarm.get("targets_left_unprewarmed", ""),
        "stop_reason": prewarm.get("stop_reason", ""),
    }


def _family_coverage(prewarm: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = prewarm.get("prewarm_coverage_by_target_family")
    if not isinstance(raw, Mapping):
        return {}
    coverage: dict[str, dict[str, Any]] = {}
    for family, values in raw.items():
        if not isinstance(values, Mapping):
            continue
        coverage[str(family)] = {
            "windows_found": values.get("windowsFound", values.get("windows_found", "")),
            "windows_attempted": values.get("windowsAttempted", values.get("windows_attempted", "")),
            "trace_outcome_success": values.get("traceOutcome_success", values.get("trace_outcome_success", 0)),
            "trace_outcome_failure": values.get("traceOutcome_failure", values.get("trace_outcome_failure", 0)),
            "trace_timeouts": values.get("traceTimeouts", values.get("trace_timeouts", 0)),
            "targets_left_unprewarmed": values.get("targetsLeftUnprewarmed", values.get("targets_left_unprewarmed", "")),
        }
    return coverage


def _smoke_observations(smoke: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "network_probe_status": smoke.get("networkProbeStatus", ""),
        "cache_only_fallback_used": smoke.get("cacheOnlyFallbackUsed", ""),
        "funding_enabled_targets": smoke.get("funding_enabled_targets", smoke.get("fundingEnabledTargets", "")),
        "cache_only_targets": smoke.get("cache_only_targets", smoke.get("cacheOnlyTargets", "")),
        "funding_trace_attempted": smoke.get("funding_trace_attempted", smoke.get("fundingTraceAttempted", "")),
    }


def build_recovery_package(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    healthcheck: Path | None = None,
    trace_diagnostic: Path | None = None,
    prewarm: Path | None = None,
    smoke_corpus: Path | None = None,
    terminal_failure: Path | None = None,
    readiness: Path | None = None,
    action: Path | None = None,
    previous_package: Path | None = None,
    operator_approved_config_present: bool = False,
    repo_root: Path = REPO_ROOT,
    endpoint_urls: list[str] | None = None,
) -> dict[str, Any]:
    paths = _latest_paths(
        output_dir=output_dir,
        healthcheck=healthcheck,
        trace_diagnostic=trace_diagnostic,
        prewarm=prewarm,
        smoke_corpus=smoke_corpus,
        terminal_failure=terminal_failure,
        readiness=readiness,
        action=action,
    )
    runtime = _runtime_config(repo_root=repo_root, endpoint_urls=endpoint_urls)
    previous = _load_json(_resolve(previous_package) or _latest_file(output_dir, "operator_rpc_capacity_recovery_package_*.json"))
    readiness_payload = _load_json(paths["readiness"])
    action_payload = _load_json(paths["autonomous_next_action"])
    trace_payload = _load_json(paths["trace_method_diagnostic"])
    prewarm_payload = _load_json(paths["prewarm"])
    health_payload = _load_json(paths["healthcheck"])
    smoke_payload = _load_json(paths["smoke_corpus"])
    active_labels = [str(item) for item in runtime["active_endpoint_labels"]]
    config_status = _configuration_status(
        operator_approved_config_present=operator_approved_config_present,
        previous_package=previous,
        active_endpoint_labels=active_labels,
    )
    operator_required = config_status != "operator_approved_rpc_configuration_present"
    return {
        "artifact_type": "operator_rpc_capacity_recovery_package",
        "generated_at": datetime.now(UTC).isoformat(),
        "readiness_classification": readiness_payload.get("readinessClassification", readiness_payload.get("classification", "")),
        "recommendation": readiness_payload.get("recommendation", ""),
        "autonomous_decision": action_payload.get("decision", ""),
        "operator_decision_required": operator_required,
        "configuration_status": config_status,
        "blocker": "public_rpc_or_cache_capacity_insufficient_for_fresh_trace_enabled_validation",
        "runtime_env_file_present": runtime["runtime_env_file_present"],
        "active_endpoint_labels": active_labels,
        "runtime_config_observed_without_secrets": runtime["runtime_config_observed_without_secrets"],
        "latest_artifacts": {key: str(value or "") for key, value in paths.items()},
        "observations": {
            "healthcheck": {
                "overall_status": health_payload.get("overall_status", ""),
                "interpretation": (
                    "Lightweight/narrow funding trace checks can be available while broader validation "
                    "still remains blocked by RPC/cache capacity."
                ),
            },
            "trace_method_diagnostic": _trace_observations(trace_payload),
            "prewarm": _prewarm_observations(prewarm_payload),
            "prewarm_coverage_by_target_family": _family_coverage(prewarm_payload),
            "smoke_runs": _smoke_observations(smoke_payload),
        },
        "operator_options": [
            "Provide a stronger Polygon RPC endpoint or capacity through existing .inspoly_runtime.env / environment variables without hardcoding credentials.",
            "Explicitly accept that readiness remains cache-only/not-ready and pause Strong Risk gate review.",
            "Approve only further bounded validation infrastructure diagnostics; do not approve model/gate/scoring changes from this evidence.",
        ],
        "stop_reason": "no_new_operator_approved_rpc_configuration_present" if operator_required else "",
        "do_not_do": [
            "Do not run the full 48-target validation until the bounded smoke clears the RPC/cache blocker.",
            "Do not rerun the same prewarm/12-target loop without a new operator RPC configuration or explicit operator capacity decision.",
            "Do not edit _score_trade(), Strong Risk gates, scoring weights, severity labels, suspicious funding v2, structural eligibility, or HER routing.",
            "Do not add private credentials or hardcoded RPC URLs.",
            "Do not treat cache-only or stale evidence as fresh gate-decision proof.",
        ],
        "ready_to_copy_codex_prompt_path": str(paths["autonomous_next_action"].with_suffix(".md"))
        if paths.get("autonomous_next_action")
        else "",
        "invariants_preserved": [
            "_score_trade() unchanged",
            "Strong Risk gates unchanged",
            "Scoring weights unchanged",
            "Production severity labels unchanged",
            "Structural eligibility unchanged",
            "Suspicious funding v2 unchanged",
            "Hard Evidence Review routing unchanged",
            "No LLM scoring or external signal ingestion",
            "No credentials or hardcoded RPC URLs",
            "Old saved outputs not mutated",
            "Funding unavailable remains unknown, not none",
            "Dedupe remains reporting-only",
        ],
    }


def render_markdown(package: Mapping[str, Any]) -> str:
    lines = [
        "# Operator RPC Capacity Recovery Package",
        "",
        f"- Generated at: `{package.get('generated_at', '')}`",
        f"- Readiness classification: `{package.get('readiness_classification', '')}`",
        f"- Recommendation: `{package.get('recommendation', '')}`",
        f"- Autonomous decision: `{package.get('autonomous_decision', '')}`",
        f"- Configuration status: `{package.get('configuration_status', '')}`",
        f"- Operator decision required: `{package.get('operator_decision_required', True)}`",
        f"- Blocker: `{package.get('blocker', '')}`",
        "",
        "## Runtime Config Rechecked",
        "",
        f"- Runtime env file present: `{package.get('runtime_env_file_present', False)}`",
        f"- Active endpoint labels: `{', '.join(package.get('active_endpoint_labels', []) or []) or 'none'}`",
    ]
    runtime = package.get("runtime_config_observed_without_secrets", {})
    if isinstance(runtime, Mapping):
        for key, value in runtime.items():
            if key == "configured_endpoint_count" or key.startswith("INSPOLY_"):
                lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Latest Evidence"])
    artifacts = package.get("latest_artifacts", {})
    if isinstance(artifacts, Mapping):
        for key, path in artifacts.items():
            lines.append(f"- {key}: `{path or 'missing'}`")
    observations = package.get("observations", {})
    trace = observations.get("trace_method_diagnostic", {}) if isinstance(observations, Mapping) else {}
    prewarm = observations.get("prewarm", {}) if isinstance(observations, Mapping) else {}
    smoke = observations.get("smoke_runs", {}) if isinstance(observations, Mapping) else {}
    lines.extend(
        [
            "",
            "## Current Diagnostic Result",
            "",
            f"- Healthcheck: `{(observations.get('healthcheck') or {}).get('overall_status', '') if isinstance(observations, Mapping) else ''}`",
            f"- Trace diagnostic: `{trace.get('classification', '') if isinstance(trace, Mapping) else ''}`",
            f"- Trace diagnostic next step: `{trace.get('recommended_next_step', '') if isinstance(trace, Mapping) else ''}`",
            f"- Prewarm stop reason: `{prewarm.get('stop_reason', '') if isinstance(prewarm, Mapping) else ''}`",
            f"- Targets left unprewarmed: `{prewarm.get('targets_left_unprewarmed', '') if isinstance(prewarm, Mapping) else ''}`",
            f"- Latest smoke network probe status: `{smoke.get('network_probe_status', '') if isinstance(smoke, Mapping) else ''}`",
            f"- Latest smoke cache-only fallback used: `{smoke.get('cache_only_fallback_used', '') if isinstance(smoke, Mapping) else ''}`",
            "",
            "## Prewarm Coverage By Target Family",
        ]
    )
    family = observations.get("prewarm_coverage_by_target_family", {}) if isinstance(observations, Mapping) else {}
    if isinstance(family, Mapping) and family:
        for name, values in sorted(family.items()):
            if not isinstance(values, Mapping):
                continue
            lines.append(
                f"- `{name}`: windows `{values.get('windows_found', '')}/{values.get('windows_attempted', '')}`, "
                f"trace outcomes success/failure `{values.get('trace_outcome_success', 0)}/{values.get('trace_outcome_failure', 0)}`, "
                f"trace timeouts `{values.get('trace_timeouts', 0)}`, "
                f"targets left unprewarmed `{values.get('targets_left_unprewarmed', '')}`"
            )
    else:
        lines.append("- no family coverage found")
    lines.extend(["", "## Operator Options"])
    for option in package.get("operator_options", []) or []:
        lines.append(f"- {option}")
    lines.extend(["", "## Do Not Do"])
    for item in package.get("do_not_do", []) or []:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Ready-To-Copy Prompt",
            "",
            f"Use the prompt embedded in `{package.get('ready_to_copy_codex_prompt_path', '') or 'missing'}`.",
            "",
            "## Invariants Preserved",
        ]
    )
    for invariant in package.get("invariants_preserved", []) or []:
        lines.append(f"- {invariant}")
    lines.append("")
    return "\n".join(lines)


def _unique_output_stamp(directory: Path, prefix: str, base_stamp: str) -> str:
    stamp = base_stamp
    counter = 2
    while (
        (directory / f"{prefix}_{stamp}.json").exists()
        or (directory / f"{prefix}_{stamp}.md").exists()
    ):
        stamp = f"{base_stamp}_{counter:02d}"
        counter += 1
    return stamp


def write_outputs(
    package: Mapping[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    timestamp: str | None = None,
) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = _unique_output_stamp(
        resolved,
        "operator_rpc_capacity_recovery_package",
        timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S"),
    )
    json_path = resolved / f"operator_rpc_capacity_recovery_package_{stamp}.json"
    markdown_path = resolved / f"operator_rpc_capacity_recovery_package_{stamp}.md"
    json_path.write_text(json.dumps(dict(package), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(package), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit an operator RPC capacity recovery package for the latest validation cycle.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--healthcheck", type=Path)
    parser.add_argument("--trace-diagnostic", type=Path)
    parser.add_argument("--prewarm", type=Path)
    parser.add_argument("--smoke-corpus", type=Path)
    parser.add_argument("--terminal-failure", type=Path)
    parser.add_argument("--readiness", type=Path)
    parser.add_argument("--action", type=Path)
    parser.add_argument("--previous-package", type=Path)
    parser.add_argument(
        "--operator-approved-config-present",
        action="store_true",
        help="Record that an operator-approved RPC configuration is present through existing env/config.",
    )
    args = parser.parse_args(argv)
    package = build_recovery_package(
        output_dir=args.output_dir,
        healthcheck=args.healthcheck,
        trace_diagnostic=args.trace_diagnostic,
        prewarm=args.prewarm,
        smoke_corpus=args.smoke_corpus,
        terminal_failure=args.terminal_failure,
        readiness=args.readiness,
        action=args.action,
        previous_package=args.previous_package,
        operator_approved_config_present=args.operator_approved_config_present,
    )
    outputs = write_outputs(package, args.output_dir)
    print(f"Operator RPC recovery JSON: {outputs['json_path']}")
    print(f"Operator RPC recovery markdown: {outputs['markdown_path']}")
    print(f"Configuration status: {package.get('configuration_status', '')}")
    print(f"Operator decision required: {package.get('operator_decision_required', True)}")
    print(f"Readiness classification: {package.get('readiness_classification', '')}")
    print(f"Autonomous decision: {package.get('autonomous_decision', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
