from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("validation_corpus_outputs")


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _latest(pattern: str, base: Path) -> Path | None:
    candidates = list(base.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))


def _default_inputs() -> list[Path]:
    outputs = REPO_ROOT / DEFAULT_OUTPUT_DIR
    candidates = sorted(outputs.glob("post_v2_corpus_*.json"), key=lambda path: path.stat().st_mtime)
    return candidates[-5:]


def _latest_health() -> Mapping[str, Any]:
    path = _latest("funding_resolver_healthcheck_*.json", REPO_ROOT / "funding_health_outputs")
    return _load_json(path) if path else {}


def _latest_prewarm() -> Mapping[str, Any]:
    path = _latest("funding_cache_prewarm_*.json", REPO_ROOT / DEFAULT_OUTPUT_DIR)
    return _load_json(path) if path else {}


def _latest_terminal_failure() -> tuple[Path | None, Mapping[str, Any]]:
    path = _latest("validation_corpus_terminal_failure_*.json", REPO_ROOT / DEFAULT_OUTPUT_DIR)
    return path, (_load_json(path) if path else {})


def summarize_network_funding_diagnostics(inputs: Iterable[Path] | None = None) -> dict[str, Any]:
    paths = list(inputs or _default_inputs())
    corpus_summaries: list[dict[str, Any]] = []
    target_status_counts: Counter[str] = Counter()
    phase_counts: Counter[str] = Counter()
    stalled_targets: list[dict[str, Any]] = []
    network_targets = 0
    network_stalled = 0
    fallback_used = 0
    killed = 0
    for path in paths:
        payload = _load_json(path)
        if not payload:
            continue
        status_counts = Counter(str(item.get("status") or "") for item in payload.get("target_results", []) if isinstance(item, Mapping))
        target_status_counts.update(status_counts)
        if payload.get("cacheOnlyFallbackUsed"):
            fallback_used += 1
        if payload.get("fullNetworkAttempted"):
            network_targets += int(payload.get("total_targets") or 0)
        for target in payload.get("target_results", []):
            if not isinstance(target, Mapping):
                continue
            status = str(target.get("status") or "")
            phase = str(target.get("validationPhase") or "unknown")
            phase_counts[phase] += 1
            if target.get("validationKilledProcess"):
                killed += 1
            if status in {"aborted_rpc_stall", "aborted_timeout", "completed_funding_blocked"}:
                network_stalled += 1
                stalled_targets.append(
                    {
                        "corpus_path": str(path),
                        "label": target.get("label") or target.get("validationTargetLabel") or "",
                        "status": status,
                        "phase": phase,
                        "validationRunMode": target.get("validationRunMode", ""),
                        "validationAbortReason": target.get("validationAbortReason", ""),
                        "validationLastProgressAt": target.get("validationLastProgressAt", ""),
                        "validationLastProgressMessage": target.get("validationLastProgressMessage", ""),
                        "validationKilledProcess": bool(target.get("validationKilledProcess")),
                        "validationProcessExitCode": target.get("validationProcessExitCode", ""),
                        "validationWallClockSeconds": target.get("validationWallClockSeconds", 0),
                        "fundingTracePhaseStartedAt": target.get("fundingTracePhaseStartedAt", ""),
                        "fundingTraceLastProgressAt": target.get("fundingTraceLastProgressAt", ""),
                        "fundingTraceLastWallet": target.get("fundingTraceLastWallet", ""),
                        "fundingTraceLastEndpointLabel": target.get("fundingTraceLastEndpointLabel", ""),
                        "fundingTraceRequestCount": target.get("fundingTraceRequestCount", 0),
                        "fundingTraceSucceededCount": target.get("fundingTraceSucceededCount", 0),
                        "fundingTraceFailedCount": target.get("fundingTraceFailedCount", 0),
                        "fundingTraceRateLimitedCount": target.get("fundingTraceRateLimitedCount", 0),
                        "fundingTraceNetworkErrorCount": target.get("fundingTraceNetworkErrorCount", 0),
                        "fundingTraceCacheHitCount": target.get("fundingTraceCacheHitCount", 0),
                        "fundingTraceCacheMissCount": target.get("fundingTraceCacheMissCount", 0),
                        "fundingTraceStallReason": target.get("fundingTraceStallReason", ""),
                    }
                )
        audit = payload.get("audit_summary") if isinstance(payload.get("audit_summary"), Mapping) else {}
        funnel = audit.get("pre_admission_funnel") if isinstance(audit.get("pre_admission_funnel"), Mapping) else {}
        corpus_summaries.append(
            {
                "path": str(path),
                "classification": payload.get("final_classification", ""),
                "validationPolicy": payload.get("validationPolicy", ""),
                "networkProbeStatus": payload.get("networkProbeStatus", ""),
                "fullNetworkAttempted": bool(payload.get("fullNetworkAttempted")),
                "cacheOnlyFallbackUsed": bool(payload.get("cacheOnlyFallbackUsed")),
                "fallbackReason": payload.get("fallbackReason", ""),
                "targetStatusCounts": dict(sorted(status_counts.items())),
                "rowsInspected": audit.get("total_rows_inspected", 0),
                "fundingTraceAttempted": funnel.get("funding_trace_attempted_count", 0),
                "fundingTraceSucceeded": funnel.get("funding_trace_succeeded_count", 0),
                "fundingTraceFailed": funnel.get("funding_trace_failed_count", 0),
                "fundingTraceSkipped": funnel.get("funding_trace_skipped_count", 0),
            }
        )
    health = _latest_health()
    prewarm = _latest_prewarm()
    terminal_failure_path, terminal_failure = _latest_terminal_failure()
    classification = "network_diagnostics_complete"
    latest = corpus_summaries[-1] if corpus_summaries else {}
    if latest.get("cacheOnlyFallbackUsed"):
        classification = "cache_only_fallback_active"
    if network_stalled:
        classification = "public_rpc_or_network_stall_detected"
    if latest.get("networkProbeStatus") in {
        "network_probe_rate_limited",
        "network_probe_stalled",
        "network_probe_funding_blocked",
    }:
        classification = "public_rpc_insufficient_for_full_network_corpus"
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "classification": classification,
        "input_paths": [str(path) for path in paths],
        "targets_inspected": sum(sum(item["targetStatusCounts"].values()) for item in corpus_summaries),
        "network_targets_stalled": network_stalled,
        "processes_killed_by_timeout": killed,
        "fallback_used_count": fallback_used,
        "target_status_counts": dict(sorted(target_status_counts.items())),
        "stall_phase_distribution": dict(sorted(phase_counts.items())),
        "stalled_targets": stalled_targets[:50],
        "corpus_summaries": corpus_summaries,
        "funding_health": {
            "overall_status": health.get("overall_status", "unknown"),
            "auth_error": health.get("auth_error", "unknown"),
            "funding_trace_available": health.get("funding_trace_available", "unknown"),
            "selected_funding_trace_endpoint_label": health.get("selected_funding_trace_endpoint_label", ""),
        },
        "latest_prewarm": {
            "stop_reason": prewarm.get("stop_reason", ""),
            "targets_completed": prewarm.get("targets_completed", prewarm.get("completed_targets", "")),
            "targets_funding_blocked": prewarm.get("funding_blocked_targets", ""),
            "wallet_time_windows_attempted": prewarm.get("wallet_time_windows_attempted", ""),
        },
        "latest_terminal_failure": {
            "path": str(terminal_failure_path or ""),
            "label": terminal_failure.get("terminalArtifactLabel", ""),
            "reason": terminal_failure.get("terminalReason", ""),
            "policy": terminal_failure.get("validationPolicy", ""),
            "currentTargetIndex": terminal_failure.get("currentTargetIndex", ""),
            "targetStatusCounts": terminal_failure.get("target_status_counts", {}),
            "orphanWorkerCleanup": terminal_failure.get("orphanWorkerCleanup", {}),
        },
    }


def render_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Network Funding Diagnostics",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Classification: {summary.get('classification', '')}",
        f"- Targets inspected: {summary.get('targets_inspected', 0)}",
        f"- Network targets stalled: {summary.get('network_targets_stalled', 0)}",
        f"- Processes killed by timeout: {summary.get('processes_killed_by_timeout', 0)}",
        f"- Fallback used count: {summary.get('fallback_used_count', 0)}",
        f"- Target statuses: {summary.get('target_status_counts', {})}",
        f"- Stall phase distribution: {summary.get('stall_phase_distribution', {})}",
        f"- Funding health: {summary.get('funding_health', {})}",
        f"- Latest prewarm: {summary.get('latest_prewarm', {})}",
        f"- Latest terminal failure: {summary.get('latest_terminal_failure', {})}",
        "",
        "## Corpus Summaries",
    ]
    for item in summary.get("corpus_summaries", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"- {item.get('path', '')}: classification={item.get('classification', '')}, "
            f"policy={item.get('validationPolicy', '')}, probe={item.get('networkProbeStatus', '')}, "
            f"fallback={item.get('cacheOnlyFallbackUsed', False)}, statuses={item.get('targetStatusCounts', {})}"
        )
    lines.extend(["", "## Stalled Targets"])
    stalled = summary.get("stalled_targets")
    if isinstance(stalled, list) and stalled:
        for item in stalled:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"- {item.get('label', '')}: status={item.get('status', '')}, "
                f"phase={item.get('phase', '')}, reason={item.get('validationAbortReason', '')}, "
                f"killed={item.get('validationKilledProcess', False)}"
            )
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def write_outputs(summary: Mapping[str, Any], output_dir: Path = REPO_ROOT / DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"network_funding_diagnostics_{stamp}.json"
    markdown_path = output_dir / f"network_funding_diagnostics_{stamp}.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(summary), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose InsPoly network-funded validation stalls.")
    parser.add_argument("inputs", nargs="*", type=Path)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    summary = summarize_network_funding_diagnostics(args.inputs or None)
    outputs = write_outputs(summary, args.output_dir)
    print(f"Network funding diagnostics: {summary['classification']}")
    print(f"JSON: {outputs['json_path']}")
    print(f"Markdown: {outputs['markdown_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
