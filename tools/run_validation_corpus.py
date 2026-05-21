from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import signal
import sys
import time
from typing import Any, Callable, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import load_runtime_env, runtime_env_int
from tools.funding_resolver_healthcheck import run_healthcheck, write_health_outputs

DEFAULT_CORPUS_PATH = Path("validation_corpus/post_v2_validation_corpus.json")
DEFAULT_OUTPUT_DIR = Path("validation_corpus_outputs")
DEFAULT_BUNDLE_TIMEOUT_SECONDS = 900
DEFAULT_FUNDING_TIMEOUT_SECONDS = 300
DEFAULT_MAX_FUNDING_TRACES_PER_BUNDLE = 50
DEFAULT_MAX_FUNDING_TRACE_FAILURES_PER_BUNDLE = 10
DEFAULT_MAX_CONSECUTIVE_RPC_FAILURES = 5
DEFAULT_MAX_LOG_CHUNKS_PER_TRACE = 4
DEFAULT_APPROXIMATE_BLOCK_LOOKUP = 1
DEFAULT_ABORT_ON_FUNDING_STALL_SECONDS = 120
DEFAULT_CACHE_FIRST = 1
DEFAULT_ALLOW_NETWORK_FUNDING = 1
DEFAULT_STALL_HEARTBEAT_SECONDS = 30
DEFAULT_MAX_RPC_STALL_TARGETS = 3
DEFAULT_AUTO_CACHE_FALLBACK = 1
DEFAULT_NETWORK_PROBE_TARGETS = 3

VALIDATION_ENV_DEFAULTS = {
    "INSPOLY_VALIDATION_TARGET_TIMEOUT_SECONDS": str(DEFAULT_BUNDLE_TIMEOUT_SECONDS),
    "INSPOLY_VALIDATION_BUNDLE_TIMEOUT_SECONDS": str(DEFAULT_BUNDLE_TIMEOUT_SECONDS),
    "INSPOLY_VALIDATION_FUNDING_TIMEOUT_SECONDS": str(DEFAULT_FUNDING_TIMEOUT_SECONDS),
    "INSPOLY_VALIDATION_MAX_FUNDING_TRACES_PER_BUNDLE": str(DEFAULT_MAX_FUNDING_TRACES_PER_BUNDLE),
    "INSPOLY_VALIDATION_MAX_FUNDING_TRACE_FAILURES_PER_BUNDLE": str(DEFAULT_MAX_FUNDING_TRACE_FAILURES_PER_BUNDLE),
    "INSPOLY_VALIDATION_MAX_CONSECUTIVE_RPC_FAILURES": str(DEFAULT_MAX_CONSECUTIVE_RPC_FAILURES),
    "INSPOLY_VALIDATION_MAX_LOG_CHUNKS_PER_TRACE": str(DEFAULT_MAX_LOG_CHUNKS_PER_TRACE),
    "INSPOLY_VALIDATION_APPROXIMATE_BLOCK_LOOKUP": str(DEFAULT_APPROXIMATE_BLOCK_LOOKUP),
    "INSPOLY_VALIDATION_ABORT_ON_FUNDING_STALL_SECONDS": str(DEFAULT_ABORT_ON_FUNDING_STALL_SECONDS),
    "INSPOLY_VALIDATION_STALL_HEARTBEAT_SECONDS": str(DEFAULT_STALL_HEARTBEAT_SECONDS),
    "INSPOLY_VALIDATION_MAX_RPC_STALL_TARGETS": str(DEFAULT_MAX_RPC_STALL_TARGETS),
    "INSPOLY_VALIDATION_AUTO_CACHE_FALLBACK": str(DEFAULT_AUTO_CACHE_FALLBACK),
    "INSPOLY_VALIDATION_NETWORK_PROBE_TARGETS": str(DEFAULT_NETWORK_PROBE_TARGETS),
    "INSPOLY_VALIDATION_CACHE_FIRST": str(DEFAULT_CACHE_FIRST),
    "INSPOLY_VALIDATION_ALLOW_NETWORK_FUNDING": str(DEFAULT_ALLOW_NETWORK_FUNDING),
}

FUNDING_PROGRESS_TOKENS = (
    "funding",
    "blockchain",
    "rpc",
    "trace",
    "tracing blockchain linkage",
)

TARGET_COMPLETED_STATUSES = {
    "completed_funding_enabled",
    "completed_cache_only",
    "completed_no_funding_candidates",
    "completed_funding_blocked",
    "audit_only_saved_output",
}

TARGET_FAMILY_TAGS = {
    "politics_world",
    "sports_crypto",
    "gaming",
    "religion",
    "crypto",
    "middle_east",
    "latin_america",
    "gta_or_known_cluster",
    "non_gta",
}


@dataclass(frozen=True)
class ValidationSettings:
    timeout_seconds: int
    funding_timeout_seconds: int
    max_funding_traces_per_bundle: int
    max_funding_trace_failures_per_bundle: int
    max_consecutive_rpc_failures: int
    abort_on_funding_stall_seconds: int
    stall_heartbeat_seconds: int
    max_rpc_stall_targets: int
    auto_cache_fallback: bool
    network_probe_targets: int
    cache_first: bool
    allow_network_funding: bool
    output_dir: Path


class ValidationRunInterrupted(BaseException):
    def __init__(self, signum: int) -> None:
        super().__init__(f"validation_run_interrupted_signal_{signum}")
        self.signum = signum


def ensure_validation_runtime_defaults(
    env_path: Path | None = None,
    *,
    defaults: Mapping[str, str] = VALIDATION_ENV_DEFAULTS,
) -> list[str]:
    path = env_path or (REPO_ROOT / ".inspoly_runtime.env")
    existing = ""
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
    present = set()
    for line in existing.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        present.add(stripped.split("=", 1)[0].strip())
    added: list[str] = []
    with path.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        for key, value in defaults.items():
            if key in present:
                continue
            handle.write(f"{key}={value}\n")
            added.append(key)
    return added


def load_corpus_config(path: Path = DEFAULT_CORPUS_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise ValueError("Corpus config must contain a targets list.")
    for index, target in enumerate(targets, start=1):
        if not isinstance(target, Mapping):
            raise ValueError(f"Corpus target {index} must be an object.")
        if not str(target.get("label") or "").strip():
            raise ValueError(f"Corpus target {index} is missing label.")
        if str(target.get("mode") or "") not in {"event_forensic", "archive"}:
            raise ValueError(f"Corpus target {target.get('label')} has unsupported mode.")
        if str(target.get("inputType") or "") not in {
            "event_url",
            "market_url",
            "slug",
            "saved_output_replay",
            "archive_window",
        }:
            raise ValueError(f"Corpus target {target.get('label')} has unsupported inputType.")
    return payload


def normalize_target_tags(target: Mapping[str, Any]) -> list[str]:
    tags = {str(tag).strip() for tag in target.get("tags") or [] if str(tag).strip()}
    mode = str(target.get("mode") or "")
    input_type = str(target.get("inputType") or "")
    if mode == "event_forensic":
        tags.add("event_forensic")
    if mode == "archive":
        tags.add("archive")
    if input_type == "saved_output_replay":
        tags.add("audit_only_saved_output")
        tags.add("cached_only")
    else:
        tags.add("fresh_rerunnable")
    return sorted(tags)


def validation_settings_from_env(
    *,
    timeout_seconds: int | None,
    output_dir: Path,
    allow_network_funding: bool,
) -> ValidationSettings:
    load_runtime_env(REPO_ROOT)
    legacy_bundle_timeout = runtime_env_int(
        "INSPOLY_VALIDATION_BUNDLE_TIMEOUT_SECONDS",
        DEFAULT_BUNDLE_TIMEOUT_SECONDS,
        minimum=1,
    )
    bundle_timeout = timeout_seconds or runtime_env_int(
        "INSPOLY_VALIDATION_TARGET_TIMEOUT_SECONDS",
        legacy_bundle_timeout,
        minimum=1,
    )
    return ValidationSettings(
        timeout_seconds=bundle_timeout,
        funding_timeout_seconds=runtime_env_int(
            "INSPOLY_VALIDATION_FUNDING_TIMEOUT_SECONDS",
            DEFAULT_FUNDING_TIMEOUT_SECONDS,
            minimum=1,
        ),
        max_funding_traces_per_bundle=runtime_env_int(
            "INSPOLY_VALIDATION_MAX_FUNDING_TRACES_PER_BUNDLE",
            DEFAULT_MAX_FUNDING_TRACES_PER_BUNDLE,
            minimum=0,
        ),
        max_funding_trace_failures_per_bundle=runtime_env_int(
            "INSPOLY_VALIDATION_MAX_FUNDING_TRACE_FAILURES_PER_BUNDLE",
            DEFAULT_MAX_FUNDING_TRACE_FAILURES_PER_BUNDLE,
            minimum=0,
        ),
        max_consecutive_rpc_failures=runtime_env_int(
            "INSPOLY_VALIDATION_MAX_CONSECUTIVE_RPC_FAILURES",
            DEFAULT_MAX_CONSECUTIVE_RPC_FAILURES,
            minimum=0,
        ),
        abort_on_funding_stall_seconds=runtime_env_int(
            "INSPOLY_VALIDATION_ABORT_ON_FUNDING_STALL_SECONDS",
            DEFAULT_ABORT_ON_FUNDING_STALL_SECONDS,
            minimum=1,
        ),
        stall_heartbeat_seconds=runtime_env_int(
            "INSPOLY_VALIDATION_STALL_HEARTBEAT_SECONDS",
            DEFAULT_STALL_HEARTBEAT_SECONDS,
            minimum=1,
        ),
        max_rpc_stall_targets=runtime_env_int(
            "INSPOLY_VALIDATION_MAX_RPC_STALL_TARGETS",
            DEFAULT_MAX_RPC_STALL_TARGETS,
            minimum=0,
        ),
        auto_cache_fallback=bool(
            runtime_env_int("INSPOLY_VALIDATION_AUTO_CACHE_FALLBACK", DEFAULT_AUTO_CACHE_FALLBACK, minimum=0)
        ),
        network_probe_targets=runtime_env_int(
            "INSPOLY_VALIDATION_NETWORK_PROBE_TARGETS",
            DEFAULT_NETWORK_PROBE_TARGETS,
            minimum=1,
        ),
        cache_first=bool(
            runtime_env_int("INSPOLY_VALIDATION_CACHE_FIRST", DEFAULT_CACHE_FIRST, minimum=0)
        ),
        allow_network_funding=allow_network_funding,
        output_dir=output_dir,
    )


def _validation_env_overrides(settings: ValidationSettings) -> dict[str, str]:
    return {
        "INSPOLY_VALIDATION_MODE": "1",
        "INSPOLY_VALIDATION_FUNDING_TIMEOUT_SECONDS": str(settings.funding_timeout_seconds),
        "INSPOLY_VALIDATION_TARGET_TIMEOUT_SECONDS": str(settings.timeout_seconds),
        "INSPOLY_VALIDATION_MAX_FUNDING_TRACES_PER_BUNDLE": str(settings.max_funding_traces_per_bundle),
        "INSPOLY_VALIDATION_MAX_FUNDING_TRACE_FAILURES_PER_BUNDLE": str(
            settings.max_funding_trace_failures_per_bundle
        ),
        "INSPOLY_VALIDATION_MAX_CONSECUTIVE_RPC_FAILURES": str(settings.max_consecutive_rpc_failures),
        "INSPOLY_VALIDATION_ABORT_ON_FUNDING_STALL_SECONDS": str(
            settings.abort_on_funding_stall_seconds
        ),
        "INSPOLY_VALIDATION_STALL_HEARTBEAT_SECONDS": str(settings.stall_heartbeat_seconds),
        "INSPOLY_VALIDATION_MAX_RPC_STALL_TARGETS": str(settings.max_rpc_stall_targets),
        "INSPOLY_VALIDATION_AUTO_CACHE_FALLBACK": "1" if settings.auto_cache_fallback else "0",
        "INSPOLY_VALIDATION_NETWORK_PROBE_TARGETS": str(settings.network_probe_targets),
        "INSPOLY_VALIDATION_CACHE_FIRST": "1" if settings.cache_first else "0",
        "INSPOLY_VALIDATION_ALLOW_NETWORK_FUNDING": "1" if settings.allow_network_funding else "0",
        "INSPOLY_FUNDING_TRACE_MODE": "live_rpc" if settings.allow_network_funding else "cache_only",
    }


def run_corpus(
    corpus: Mapping[str, Any],
    *,
    max_targets: int | None,
    skip_rerun: bool,
    audit_only: bool,
    settings: ValidationSettings,
    validation_policy: str = "direct",
    network_probe_status: str = "",
    network_probe_output_path: str = "",
    full_network_attempted: bool | None = None,
    cache_only_fallback_used: bool = False,
    fallback_reason: str = "",
    fallback_source_summary: Mapping[str, Any] | None = None,
    terminal_artifact_label: str = "",
    terminal_artifact_timestamp: str | None = None,
) -> dict[str, Any]:
    targets = [dict(item) for item in corpus.get("targets", []) if isinstance(item, Mapping)]
    if max_targets is not None:
        targets = targets[: max(0, max_targets)]
    target_results: list[dict[str, Any]] = []
    selected_output_paths: list[str] = []
    stopped_early_reason = ""
    rpc_stall_or_blocked_count = 0
    current_target: dict[str, Any] | None = None
    current_index = 0
    current_target_started_at = ""
    current_target_started_monotonic: float | None = None
    terminal_writer = (
        _TerminalFailureWriter(
            corpus=corpus,
            output_dir=settings.output_dir,
            timestamp=terminal_artifact_timestamp,
            label=terminal_artifact_label,
            validation_policy=validation_policy,
            network_probe_status=network_probe_status,
            network_probe_output_path=network_probe_output_path,
            full_network_attempted=settings.allow_network_funding if full_network_attempted is None else full_network_attempted,
            cache_only_fallback_used=cache_only_fallback_used,
            fallback_reason=fallback_reason,
            total_targets=len(targets),
        )
        if terminal_artifact_label
        else None
    )
    previous_handlers = _install_terminal_signal_handlers() if terminal_writer else {}
    try:
        for index, target in enumerate(targets, start=1):
            current_target = dict(target)
            current_index = index
            current_target_started_at = datetime.now(UTC).isoformat()
            current_target_started_monotonic = time.monotonic()
            result = run_target(
                target,
                index=index,
                skip_rerun=skip_rerun,
                audit_only=audit_only,
                settings=settings,
            )
            target_results.append(result)
            for path in result.get("audit_paths", []):
                if isinstance(path, str) and path:
                    selected_output_paths.append(path)
            if terminal_writer:
                terminal_writer.write_checkpoint(
                    current_target=current_target,
                    current_index=current_index,
                    target_results=target_results,
                    selected_output_paths=selected_output_paths,
                    stopped_early_reason=stopped_early_reason,
                )
            if str(result.get("status") or "") in {"aborted_rpc_stall", "aborted_timeout", "completed_funding_blocked"}:
                rpc_stall_or_blocked_count += 1
            if (
                settings.allow_network_funding
                and settings.max_rpc_stall_targets > 0
                and rpc_stall_or_blocked_count >= settings.max_rpc_stall_targets
            ):
                stopped_early_reason = "max_rpc_stall_targets_hit"
                break
    except ValidationRunInterrupted as exc:
        terminal_paths: dict[str, str] = {}
        if terminal_writer:
            terminal_paths = terminal_writer.write(
                reason=f"signal_{exc.signum}",
                current_target=current_target,
                current_index=current_index,
                current_target_started_at=current_target_started_at,
                current_target_runtime_seconds=_elapsed_seconds_since(current_target_started_monotonic),
                target_results=target_results,
                selected_output_paths=selected_output_paths,
                stopped_early_reason=stopped_early_reason or "signal_interrupted",
            )
        if terminal_paths:
            print(
                "Validation interrupted; explicit terminal failure artifact written: "
                f"{terminal_paths.get('json_path', '')}",
                file=sys.stderr,
            )
        raise SystemExit(130) from None
    except BaseException as exc:
        if terminal_writer:
            terminal_writer.write(
                reason=f"{type(exc).__name__}: {exc}",
                current_target=current_target,
                current_index=current_index,
                current_target_started_at=current_target_started_at,
                current_target_runtime_seconds=_elapsed_seconds_since(current_target_started_monotonic),
                target_results=target_results,
                selected_output_paths=selected_output_paths,
                stopped_early_reason=stopped_early_reason or "exception_interrupted",
            )
        raise
    finally:
        if terminal_writer:
            _restore_terminal_signal_handlers(previous_handlers)
    audit_summary, audit_paths = run_selected_audit(selected_output_paths, settings.output_dir)
    return build_corpus_summary(
        corpus=corpus,
        target_results=target_results,
        selected_output_paths=selected_output_paths,
        audit_summary=audit_summary,
        audit_output_paths=audit_paths,
        validation_policy=validation_policy,
        network_probe_status=network_probe_status,
        network_probe_output_path=network_probe_output_path,
        full_network_attempted=settings.allow_network_funding if full_network_attempted is None else full_network_attempted,
        cache_only_fallback_used=cache_only_fallback_used,
        fallback_reason=fallback_reason,
        fallback_source_summary=fallback_source_summary,
        stopped_early_reason=stopped_early_reason,
    )


class _TerminalFailureWriter:
    def __init__(
        self,
        *,
        corpus: Mapping[str, Any],
        output_dir: Path,
        timestamp: str | None,
        label: str,
        validation_policy: str,
        network_probe_status: str,
        network_probe_output_path: str,
        full_network_attempted: bool,
        cache_only_fallback_used: bool,
        fallback_reason: str,
        total_targets: int,
    ) -> None:
        self.corpus = corpus
        self.output_dir = output_dir
        self.timestamp = timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        self.label = label
        self.validation_policy = validation_policy
        self.network_probe_status = network_probe_status
        self.network_probe_output_path = network_probe_output_path
        self.full_network_attempted = full_network_attempted
        self.cache_only_fallback_used = cache_only_fallback_used
        self.fallback_reason = fallback_reason
        self.total_targets = total_targets
        self.started_at = datetime.now(UTC).isoformat()
        self.started_monotonic = time.monotonic()
        self.checkpoint_json_path = self.output_dir / f"validation_corpus_checkpoint_{self.timestamp}.json"
        self.checkpoint_markdown_path = self.output_dir / f"validation_corpus_checkpoint_{self.timestamp}.md"

    def write(
        self,
        *,
        reason: str,
        current_target: Mapping[str, Any] | None,
        current_index: int,
        target_results: list[dict[str, Any]],
        selected_output_paths: list[str],
        stopped_early_reason: str,
        current_target_started_at: str = "",
        current_target_runtime_seconds: float | None = None,
    ) -> dict[str, str]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.output_dir / f"validation_corpus_terminal_failure_{self.timestamp}.json"
        markdown_path = self.output_dir / f"validation_corpus_terminal_failure_{self.timestamp}.md"
        payload = _terminal_failure_payload(
            corpus=self.corpus,
            label=self.label,
            reason=reason,
            validation_policy=self.validation_policy,
            network_probe_status=self.network_probe_status,
            network_probe_output_path=self.network_probe_output_path,
            full_network_attempted=self.full_network_attempted,
            cache_only_fallback_used=self.cache_only_fallback_used,
            fallback_reason=self.fallback_reason,
            stopped_early_reason=stopped_early_reason,
            total_targets=self.total_targets,
            current_target=current_target,
            current_index=current_index,
            current_target_started_at=current_target_started_at,
            current_target_runtime_seconds=current_target_runtime_seconds,
            run_started_at=self.started_at,
            runtime_seconds=_elapsed_seconds_since(self.started_monotonic),
            checkpoint_json_path=str(self.checkpoint_json_path),
            checkpoint_markdown_path=str(self.checkpoint_markdown_path),
            target_results=target_results,
            selected_output_paths=selected_output_paths,
        )
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        markdown_path.write_text(_render_terminal_failure_markdown(payload), encoding="utf-8")
        return {"json_path": str(json_path), "markdown_path": str(markdown_path)}

    def write_checkpoint(
        self,
        *,
        current_target: Mapping[str, Any] | None,
        current_index: int,
        target_results: list[dict[str, Any]],
        selected_output_paths: list[str],
        stopped_early_reason: str,
    ) -> dict[str, str]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        payload = _terminal_failure_payload(
            corpus=self.corpus,
            label=self.label,
            reason="checkpoint_after_target",
            validation_policy=self.validation_policy,
            network_probe_status=self.network_probe_status,
            network_probe_output_path=self.network_probe_output_path,
            full_network_attempted=self.full_network_attempted,
            cache_only_fallback_used=self.cache_only_fallback_used,
            fallback_reason=self.fallback_reason,
            stopped_early_reason=stopped_early_reason,
            total_targets=self.total_targets,
            current_target=current_target,
            current_index=current_index,
            current_target_started_at="",
            current_target_runtime_seconds=None,
            run_started_at=self.started_at,
            runtime_seconds=_elapsed_seconds_since(self.started_monotonic),
            checkpoint_json_path=str(self.checkpoint_json_path),
            checkpoint_markdown_path=str(self.checkpoint_markdown_path),
            target_results=target_results,
            selected_output_paths=selected_output_paths,
        )
        payload["terminalState"] = "running_checkpoint"
        payload["terminalArtifactKind"] = "progress_checkpoint"
        payload["checkpointReason"] = "after_target_completed"
        payload["interpretation"] = (
            "This checkpoint records validation progress after a completed target. "
            "It is not a final corpus artifact and must not be used for gate decisions."
        )
        self.checkpoint_json_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.checkpoint_markdown_path.write_text(
            _render_terminal_failure_markdown(payload),
            encoding="utf-8",
        )
        return {"json_path": str(self.checkpoint_json_path), "markdown_path": str(self.checkpoint_markdown_path)}


def _elapsed_seconds_since(started_monotonic: float | None) -> float | None:
    if started_monotonic is None:
        return None
    return round(max(0.0, time.monotonic() - started_monotonic), 3)


def _install_terminal_signal_handlers() -> dict[int, Any]:
    previous: dict[int, Any] = {}

    def _raise_interrupted(signum: int, _frame: Any) -> None:
        raise ValidationRunInterrupted(signum)

    for name in ("SIGTERM", "SIGINT"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, _raise_interrupted)
    return previous


def _restore_terminal_signal_handlers(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)
        except Exception:
            pass


def _terminal_failure_payload(
    *,
    corpus: Mapping[str, Any],
    label: str,
    reason: str,
    validation_policy: str,
    network_probe_status: str,
    network_probe_output_path: str,
    full_network_attempted: bool,
    cache_only_fallback_used: bool,
    fallback_reason: str,
    stopped_early_reason: str,
    total_targets: int,
    current_target: Mapping[str, Any] | None,
    current_index: int,
    target_results: list[dict[str, Any]],
    selected_output_paths: list[str],
    current_target_started_at: str = "",
    current_target_runtime_seconds: float | None = None,
    run_started_at: str = "",
    runtime_seconds: float | None = None,
    checkpoint_json_path: str = "",
    checkpoint_markdown_path: str = "",
) -> dict[str, Any]:
    status_counts = Counter(str(result.get("status") or "unknown") for result in target_results)
    last_completed_target = dict(target_results[-1]) if target_results else {}
    slowest_targets = sorted(
        (dict(result) for result in target_results),
        key=lambda item: float(item.get("validationWallClockSeconds") or 0),
        reverse=True,
    )[:5]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "runStartedAt": run_started_at,
        "runtimeSeconds": runtime_seconds,
        "corpus_name": corpus.get("corpusName") or corpus.get("corpus_name") or "post_v2_validation_corpus",
        "terminalState": "terminal_failure",
        "terminalReason": reason,
        "terminalArtifactLabel": label,
        "terminalArtifactKind": "explicit_terminal_failure",
        "validationPolicy": validation_policy,
        "networkProbeStatus": network_probe_status,
        "networkProbeOutputPath": network_probe_output_path,
        "fullNetworkAttempted": full_network_attempted,
        "cacheOnlyFallbackUsed": cache_only_fallback_used,
        "fallbackReason": fallback_reason,
        "stoppedEarlyReason": stopped_early_reason,
        "totalConfiguredTargets": total_targets,
        "currentTargetIndex": current_index,
        "currentTarget": dict(current_target or {}),
        "currentTargetStartedAt": current_target_started_at,
        "currentTargetRuntimeSeconds": current_target_runtime_seconds,
        "lastCompletedTargetIndex": len(target_results),
        "lastCompletedTarget": last_completed_target,
        "partialTargetResultsCount": len(target_results),
        "completed_targets": sum(status_counts.get(status, 0) for status in TARGET_COMPLETED_STATUSES),
        "skipped_targets": status_counts.get("skipped_missing_input", 0),
        "aborted_targets": status_counts.get("aborted_timeout", 0) + status_counts.get("aborted_rpc_stall", 0),
        "target_status_counts": dict(sorted(status_counts.items())),
        "selected_output_paths": list(selected_output_paths),
        "checkpointJsonPath": checkpoint_json_path,
        "checkpointMarkdownPath": checkpoint_markdown_path,
        "slowestCompletedTargets": [
            {
                "label": str(result.get("label") or ""),
                "status": str(result.get("status") or ""),
                "validationWallClockSeconds": result.get("validationWallClockSeconds", 0),
                "validationPhase": str(result.get("validationPhase") or ""),
                "validationLastProgressMessage": str(result.get("validationLastProgressMessage") or ""),
                "validationAbortReason": str(result.get("validationAbortReason") or ""),
            }
            for result in slowest_targets
        ],
        "target_results": [dict(result) for result in target_results],
        "orphanWorkerCleanup": {
            "cleanupPath": "_run_target_in_process catches interrupts/exceptions and terminates the active child process before re-raising",
            "cleanupReported": True,
        },
        "interpretation": (
            "This terminal failure artifact records partial validation progress only. "
            "It is not a completed model-evidence corpus and must not be used for gate decisions."
        ),
    }


def _render_terminal_failure_markdown(payload: Mapping[str, Any]) -> str:
    title = (
        "# Validation Corpus Progress Checkpoint"
        if payload.get("terminalState") == "running_checkpoint"
        else "# Validation Corpus Terminal Failure"
    )
    lines = [
        title,
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Run started at: {payload.get('runStartedAt', '')}",
        f"- Runtime seconds: {payload.get('runtimeSeconds', '')}",
        f"- Label: {payload.get('terminalArtifactLabel', '')}",
        f"- Reason: {payload.get('terminalReason', '')}",
        f"- Artifact kind: {payload.get('terminalArtifactKind', '')}",
        f"- Policy: {payload.get('validationPolicy', '')}",
        f"- Probe status: {payload.get('networkProbeStatus', '')}",
        f"- Full network attempted: {payload.get('fullNetworkAttempted', False)}",
        f"- Cache-only fallback used: {payload.get('cacheOnlyFallbackUsed', False)}",
        f"- Fallback reason: {payload.get('fallbackReason', '')}",
        f"- Configured targets: {payload.get('totalConfiguredTargets', 0)}",
        f"- Current target index: {payload.get('currentTargetIndex', 0)}",
        f"- Current target started at: {payload.get('currentTargetStartedAt', '')}",
        f"- Current target runtime seconds: {payload.get('currentTargetRuntimeSeconds', '')}",
        f"- Last completed target index: {payload.get('lastCompletedTargetIndex', 0)}",
        f"- Completed/skipped/aborted partial targets: {payload.get('completed_targets', 0)}/{payload.get('skipped_targets', 0)}/{payload.get('aborted_targets', 0)}",
        f"- Target statuses: {payload.get('target_status_counts', {})}",
        f"- Checkpoint JSON: {payload.get('checkpointJsonPath', '')}",
        f"- Checkpoint Markdown: {payload.get('checkpointMarkdownPath', '')}",
        "",
        "## Current Target",
        "",
        "```json",
        json.dumps(payload.get("currentTarget", {}), indent=2, sort_keys=True),
        "```",
        "",
        "## Last Completed Target",
        "",
        "```json",
        json.dumps(payload.get("lastCompletedTarget", {}), indent=2, sort_keys=True),
        "```",
        "",
        "## Slowest Completed Targets",
        "",
        "```json",
        json.dumps(payload.get("slowestCompletedTargets", []), indent=2, sort_keys=True),
        "```",
        "",
        "## Interpretation",
        "",
        f"- {payload.get('interpretation', '')}",
    ]
    return "\n".join(lines).rstrip() + "\n"


def run_target(
    target: Mapping[str, Any],
    *,
    index: int,
    skip_rerun: bool,
    audit_only: bool,
    settings: ValidationSettings,
) -> dict[str, Any]:
    label = str(target.get("label") or f"target_{index}")
    input_type = str(target.get("inputType") or "")
    input_value = str(target.get("inputValue") or "").strip()
    base = {
        "label": label,
        "mode": str(target.get("mode") or ""),
        "inputType": input_type,
        "inputValue": input_value,
        "tags": normalize_target_tags(target),
        "validationTargetLabel": label,
        "validationRunMode": "network_funding" if settings.allow_network_funding else "cache_only",
        "validationPhase": "queued",
        "validationPhaseStartedAt": "",
        "validationLastProgressAt": "",
        "validationLastProgressMessage": "",
        "validationBundleTimeoutSeconds": settings.timeout_seconds,
        "validationFundingTimeoutSeconds": settings.funding_timeout_seconds,
        "validationBundleStatus": "",
        "validationFundingStatus": "",
        "validationAbortReason": "",
        "validationTimedOut": False,
        "validationFundingTimedOut": False,
        "validationRpcFailureLimitHit": False,
        "validationFundingTraceLimitHit": False,
        "validationKilledProcess": False,
        "validationProcessExitCode": "",
        "validationWallClockSeconds": 0.0,
        "fundingTracePhaseStartedAt": "",
        "fundingTraceLastProgressAt": "",
        "fundingTraceLastWallet": "",
        "fundingTraceLastEndpointLabel": "",
        "fundingTraceRequestCount": 0,
        "fundingTraceSucceededCount": 0,
        "fundingTraceFailedCount": 0,
        "fundingTraceRateLimitedCount": 0,
        "fundingTraceNetworkErrorCount": 0,
        "fundingTraceCacheHitCount": 0,
        "fundingTraceCacheMissCount": 0,
        "fundingTraceStallReason": "",
        "audit_paths": [],
        "output_paths": [],
        "error": "",
    }
    if not input_value:
        return {**base, "status": "skipped_missing_input", "validationAbortReason": "missing_input"}
    if input_type == "saved_output_replay" or skip_rerun or audit_only:
        path = Path(input_value)
        if not path.exists():
            return {**base, "status": "skipped_missing_input", "validationAbortReason": "missing_saved_output"}
        audit_paths = _bounded_saved_output_audit_paths(path)
        return {
            **base,
            "status": "audit_only_saved_output",
            "validationBundleStatus": "audit_only_saved_output",
            "validationFundingStatus": "not_assessed",
            "audit_paths": [str(item) for item in audit_paths],
            "output_paths": [str(path)],
        }

    target_timeout = _int_or_none(target.get("timeoutSeconds") or target.get("timeout_seconds"))
    target_settings = (
        replace(settings, timeout_seconds=min(settings.timeout_seconds, max(1, target_timeout)))
        if target_timeout is not None
        else settings
    )
    return _run_target_in_process(target, base, target_settings)


def _run_target_in_process(
    target: Mapping[str, Any],
    base: Mapping[str, Any],
    settings: ValidationSettings,
) -> dict[str, Any]:
    ctx = mp.get_context("spawn")
    events: mp.Queue = ctx.Queue()
    process = ctx.Process(
        target=_worker_entry,
        args=(dict(target), _validation_env_overrides(settings), str(REPO_ROOT), events),
        daemon=True,
    )
    process.start()
    try:
        return _monitor_worker_process(process, events, base, settings)
    except BaseException:
        _terminate_process_tree(process)
        raise


def _monitor_worker_process(
    process: Any,
    events: Any,
    base: Mapping[str, Any],
    settings: ValidationSettings,
    *,
    now_func: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    started = now_func()
    started_at = datetime.now(UTC).isoformat()
    last_progress_at = started
    last_progress_iso = started_at
    last_progress_message = ""
    validation_phase = "started"
    validation_phase_started_at = started_at
    funding_started_at = ""
    funding_started_monotonic: float | None = None
    funding_last_progress_at = ""
    in_funding_stage = False
    final_payload: dict[str, Any] | None = None
    while process.is_alive():
        now = now_func()
        if now - started > settings.timeout_seconds:
            killed = _terminate_process_tree(process)
            return {
                **base,
                "status": "aborted_timeout",
                "validationBundleStatus": "aborted_timeout",
                "validationFundingStatus": "unknown",
                "validationAbortReason": "validation_bundle_timeout",
                "validationPhase": validation_phase,
                "validationPhaseStartedAt": validation_phase_started_at,
                "validationLastProgressAt": last_progress_iso,
                "validationLastProgressMessage": last_progress_message,
                "validationTimedOut": True,
                "validationKilledProcess": killed,
                "validationProcessExitCode": getattr(process, "exitcode", ""),
                "validationWallClockSeconds": round(now - started, 3),
                "fundingTracePhaseStartedAt": funding_started_at,
                "fundingTraceLastProgressAt": funding_last_progress_at,
                "fundingTraceStallReason": "validation_bundle_timeout",
            }
        if in_funding_stage and funding_started_monotonic is not None and now - funding_started_monotonic > settings.funding_timeout_seconds:
            killed = _terminate_process_tree(process)
            return {
                **base,
                "status": "aborted_rpc_stall",
                "validationBundleStatus": "aborted_rpc_stall",
                "validationFundingStatus": "funding_blocked",
                "validationAbortReason": "validation_funding_phase_timeout",
                "validationPhase": validation_phase,
                "validationPhaseStartedAt": validation_phase_started_at,
                "validationLastProgressAt": last_progress_iso,
                "validationLastProgressMessage": last_progress_message,
                "validationFundingTimedOut": True,
                "validationKilledProcess": killed,
                "validationProcessExitCode": getattr(process, "exitcode", ""),
                "validationWallClockSeconds": round(now - started, 3),
                "fundingTracePhaseStartedAt": funding_started_at,
                "fundingTraceLastProgressAt": funding_last_progress_at,
                "fundingTraceStallReason": "validation_funding_phase_timeout",
            }
        if (
            in_funding_stage
            and now - last_progress_at > settings.abort_on_funding_stall_seconds
        ):
            killed = _terminate_process_tree(process)
            return {
                **base,
                "status": "aborted_rpc_stall",
                "validationBundleStatus": "aborted_rpc_stall",
                "validationFundingStatus": "funding_blocked",
                "validationAbortReason": "validation_funding_stall_timeout",
                "validationPhase": validation_phase,
                "validationPhaseStartedAt": validation_phase_started_at,
                "validationLastProgressAt": last_progress_iso,
                "validationLastProgressMessage": last_progress_message,
                "validationFundingTimedOut": True,
                "validationKilledProcess": killed,
                "validationProcessExitCode": getattr(process, "exitcode", ""),
                "validationWallClockSeconds": round(now - started, 3),
                "fundingTracePhaseStartedAt": funding_started_at,
                "fundingTraceLastProgressAt": funding_last_progress_at,
                "fundingTraceStallReason": "validation_funding_stall_timeout",
            }
        try:
            event = events.get(timeout=1)
        except queue.Empty:
            continue
        if not isinstance(event, Mapping):
            continue
        if event.get("type") == "progress":
            last_progress_at = now
            last_progress_iso = str(event.get("at") or datetime.now(UTC).isoformat())
            stage = str(event.get("stage") or "")
            detail = str(event.get("detail") or "")
            message = " ".join(item for item in (stage, detail) if item).strip()
            last_progress_message = message
            if stage and stage != validation_phase:
                validation_phase = stage
                validation_phase_started_at = last_progress_iso
            stage_text = f"{event.get('stage', '')} {event.get('detail', '')}".lower()
            if any(token in stage_text for token in FUNDING_PROGRESS_TOKENS):
                in_funding_stage = True
                funding_last_progress_at = last_progress_iso
                if funding_started_monotonic is None:
                    funding_started_monotonic = now
                    funding_started_at = last_progress_iso
        elif event.get("type") == "result":
            final_payload = dict(event.get("payload") or {})
        elif event.get("type") == "error":
            final_payload = {
                "status": "failed_runtime_error",
                "error": str(event.get("error") or ""),
            }
    process.join(timeout=5)
    while True:
        try:
            event = events.get_nowait()
        except queue.Empty:
            break
        if isinstance(event, Mapping) and event.get("type") == "result":
            final_payload = dict(event.get("payload") or {})
        elif isinstance(event, Mapping) and event.get("type") == "error":
            final_payload = {"status": "failed_runtime_error", "error": str(event.get("error") or "")}
    if final_payload is None:
        finished = now_func()
        return {
            **base,
            "status": "failed_runtime_error",
            "validationBundleStatus": "failed_runtime_error",
            "validationAbortReason": f"worker_exit_{process.exitcode}",
            "validationPhase": validation_phase,
            "validationPhaseStartedAt": validation_phase_started_at,
            "validationLastProgressAt": last_progress_iso,
            "validationLastProgressMessage": last_progress_message,
            "validationProcessExitCode": getattr(process, "exitcode", ""),
            "validationWallClockSeconds": round(finished - started, 3),
            "fundingTracePhaseStartedAt": funding_started_at,
            "fundingTraceLastProgressAt": funding_last_progress_at,
        }
    finished = now_func()
    return {
        **base,
        **final_payload,
        "validationPhase": final_payload.get("validationPhase") or validation_phase,
        "validationPhaseStartedAt": final_payload.get("validationPhaseStartedAt") or validation_phase_started_at,
        "validationLastProgressAt": final_payload.get("validationLastProgressAt") or last_progress_iso,
        "validationLastProgressMessage": final_payload.get("validationLastProgressMessage") or last_progress_message,
        "validationProcessExitCode": getattr(process, "exitcode", ""),
        "validationWallClockSeconds": round(finished - started, 3),
        "fundingTracePhaseStartedAt": final_payload.get("fundingTracePhaseStartedAt") or funding_started_at,
        "fundingTraceLastProgressAt": final_payload.get("fundingTraceLastProgressAt") or funding_last_progress_at,
    }


def _terminate_process_tree(process: Any) -> bool:
    killed = False
    pid = getattr(process, "pid", None)
    if pid:
        try:
            pgid = os.getpgid(pid)
            if pgid and pgid != os.getpgrp():
                os.killpg(pgid, signal.SIGTERM)
                killed = True
        except Exception:
            pass
    try:
        if hasattr(process, "terminate") and process.is_alive():
            process.terminate()
            killed = True
    except Exception:
        pass
    try:
        process.join(timeout=5)
    except Exception:
        pass
    try:
        still_alive = bool(process.is_alive())
    except Exception:
        still_alive = False
    if still_alive:
        if pid:
            try:
                pgid = os.getpgid(pid)
                if pgid and pgid != os.getpgrp():
                    os.killpg(pgid, signal.SIGKILL)
                    killed = True
            except Exception:
                pass
        try:
            if hasattr(process, "kill"):
                process.kill()
                killed = True
        except Exception:
            pass
        try:
            process.join(timeout=5)
        except Exception:
            pass
    return killed


def _worker_entry(
    target: dict[str, Any],
    env_overrides: dict[str, str],
    repo_root: str,
    events: Any,
) -> None:
    try:
        if hasattr(os, "setsid"):
            try:
                os.setsid()
            except Exception:
                pass
        os.chdir(repo_root)
        for key, value in env_overrides.items():
            os.environ[key] = value
        load_runtime_env(Path(repo_root))

        def progress(*args: Any, **kwargs: Any) -> None:
            if len(args) == 1 and not kwargs:
                event = args[0]
                percent = getattr(event, "percent", 0)
                stage = getattr(event, "stage", "")
                detail = getattr(event, "detail", "")
            else:
                percent = args[0] if len(args) > 0 else kwargs.get("percent", 0)
                stage = args[1] if len(args) > 1 else kwargs.get("stage", "")
                detail = args[2] if len(args) > 2 else kwargs.get("detail", "")
            events.put(
                {
                    "type": "progress",
                    "percent": percent,
                    "stage": stage,
                    "detail": detail,
                    "at": datetime.now(UTC).isoformat(),
                }
            )

        mode = str(target.get("mode") or "")
        if mode == "event_forensic":
            payload = _run_event_forensic_worker(target, progress)
        elif mode == "archive":
            payload = _run_archive_worker(target, progress)
        else:
            payload = {"status": "failed_runtime_error", "error": f"Unsupported mode: {mode}"}
        events.put({"type": "result", "payload": payload})
    except Exception as exc:
        events.put({"type": "error", "error": f"{type(exc).__name__}: {exc}"})


def _run_event_forensic_worker(
    target: Mapping[str, Any],
    progress_callback: Callable[[float, str, str], None],
) -> dict[str, Any]:
    from app.config import AppConfig
    from app.event_forensic import EventForensicAnalyzer
    from app.polymarket import PolymarketClient
    from app.storage import Storage

    config = AppConfig.load_event_forensic_analyzer()
    config.ensure_dirs()
    analyzer = EventForensicAnalyzer(PolymarketClient(), Storage(config.db_path), config)
    scope = target.get("scopeSettings") or {}
    if not isinstance(scope, Mapping):
        scope = {}
    min_notional = _decimal_or_none(target.get("minNotional"))
    report = analyzer.analyze(
        str(target.get("inputValue") or ""),
        config.reports_dir,
        min_notional=min_notional,
        include_related_markets=bool(scope.get("includeRelatedMarkets", False)),
        include_blockchain=bool(scope.get("includeBlockchain", True)),
        analysis_scope=_optional_str(scope.get("analysisScope")),
        selected_condition_id=_optional_str(scope.get("selectedConditionId")),
        selected_market_slug=_optional_str(scope.get("selectedMarketSlug")),
        progress_callback=progress_callback,
    )
    return _completed_payload(report, mode="event_forensic")


def _run_archive_worker(
    target: Mapping[str, Any],
    progress_callback: Callable[[float, str, str], None],
) -> dict[str, Any]:
    from app.archive_scanner import ArchiveResearchScanner
    from app.config import AppConfig
    from app.polymarket import PolymarketClient
    from app.storage import Storage

    config = AppConfig.load_archive_researcher()
    config.ensure_dirs()
    client = PolymarketClient()
    scanner = ArchiveResearchScanner(client, Storage(config.db_path), config)
    start_at, end_at = _parse_archive_window(str(target.get("inputValue") or ""))
    scope = target.get("scopeSettings") or {}
    categories = _selected_categories(client, list((scope or {}).get("categories") or []))
    report = scanner.scan(
        start_at,
        end_at,
        config.reports_dir,
        selected_categories=categories,
        min_notional=_decimal_or_none(target.get("minNotional")),
        max_notional=_decimal_or_none(target.get("maxNotional")),
        progress_callback=progress_callback,
    )
    return _completed_payload(report, mode="archive")


def _completed_payload(report: Mapping[str, Any], *, mode: str) -> dict[str, Any]:
    export_files = report.get("export_files") if isinstance(report, Mapping) else {}
    output_paths = _output_paths_from_report(report)
    audit_paths = _audit_paths_from_report(report, mode=mode)
    funding_health = _find_funding_health(report)
    validation_status = _derive_completed_status(funding_health)
    return {
        "status": validation_status,
        "validationBundleStatus": funding_health.get("validationBundleStatus") or validation_status,
        "validationFundingStatus": funding_health.get("validationFundingStatus") or _funding_status_from_health(funding_health),
        "validationAbortReason": funding_health.get("validationAbortReason") or "",
        "validationTimedOut": False,
        "validationFundingTimedOut": False,
        "validationRpcFailureLimitHit": bool(funding_health.get("validationRpcFailureLimitHit")),
        "validationFundingTraceLimitHit": bool(funding_health.get("validationFundingTraceLimitHit")),
        "fundingTraceRequestCount": int(funding_health.get("fundingTraceAttemptedCount") or 0),
        "fundingTraceSucceededCount": int(funding_health.get("fundingTraceSucceededCount") or 0),
        "fundingTraceFailedCount": int(funding_health.get("fundingTraceFailedCount") or 0),
        "fundingTraceRateLimitedCount": int(funding_health.get("fundingTraceRateLimitedCount") or 0),
        "fundingTraceNetworkErrorCount": int(
            (funding_health.get("fundingTraceEndpointFailureDistribution") or {}).get("network_error", 0)
            if isinstance(funding_health.get("fundingTraceEndpointFailureDistribution"), Mapping)
            else 0
        ),
        "fundingTraceCacheHitCount": int(funding_health.get("fundingTracePersistentCacheHitCount") or funding_health.get("fundingTraceCacheHitCount") or 0),
        "fundingTraceCacheMissCount": int(funding_health.get("fundingTracePersistentCacheMissCount") or funding_health.get("fundingTraceCacheMissCount") or 0),
        "fundingTraceLastEndpointLabel": _last_endpoint_label(funding_health),
        "fundingTraceStallReason": funding_health.get("validationAbortReason") or "",
        "output_paths": output_paths,
        "audit_paths": audit_paths,
        "report_json_path": str(report.get("report_json_path") or ""),
        "export_files": dict(export_files) if isinstance(export_files, Mapping) else {},
        "funding_resolver_health": dict(funding_health),
    }


def _last_endpoint_label(funding_health: Mapping[str, Any]) -> str:
    summary = funding_health.get("fundingTraceEndpointSummary")
    if not isinstance(summary, list):
        return ""
    for item in reversed(summary):
        if isinstance(item, Mapping) and item.get("requestCount"):
            return str(item.get("endpointLabel") or item.get("endpoint_label") or "")
    return ""


def _find_funding_health(report: Mapping[str, Any]) -> dict[str, Any]:
    direct = report.get("funding_resolver_health")
    if isinstance(direct, Mapping):
        return dict(direct)
    performance = report.get("performance")
    if isinstance(performance, Mapping):
        nested = performance.get("funding_resolver_health")
        if isinstance(nested, Mapping):
            return dict(nested)
    return {}


def _derive_completed_status(funding_health: Mapping[str, Any]) -> str:
    validation_status = str(funding_health.get("validationBundleStatus") or "")
    if validation_status:
        return validation_status
    attempted = int(funding_health.get("fundingTraceAttemptedCount") or 0)
    succeeded = int(funding_health.get("fundingTraceSucceededCount") or 0)
    failed = int(funding_health.get("fundingTraceFailedCount") or 0)
    skipped = int(funding_health.get("fundingTraceSkippedCount") or 0)
    persistent_hits = int(funding_health.get("fundingTracePersistentCacheHitCount") or 0)
    trace_limit = bool(funding_health.get("validationFundingTraceLimitHit"))
    rpc_limit = bool(funding_health.get("validationRpcFailureLimitHit"))
    if trace_limit or rpc_limit:
        return "completed_funding_blocked"
    if attempted == 0:
        return "completed_no_funding_candidates"
    if succeeded > 0:
        if persistent_hits >= attempted and failed == 0 and skipped == 0:
            return "completed_cache_only"
        return "completed_funding_enabled"
    if failed > 0 or skipped > 0:
        return "completed_funding_blocked"
    return "completed_no_funding_candidates"


def _funding_status_from_health(funding_health: Mapping[str, Any]) -> str:
    status = str(funding_health.get("validationFundingStatus") or "")
    if status:
        return status
    bundle = _derive_completed_status(funding_health)
    if bundle == "completed_funding_enabled":
        return "funding_enabled"
    if bundle == "completed_cache_only":
        return "cache_only"
    if bundle == "completed_funding_blocked":
        return "funding_blocked"
    return "not_assessed"


def _output_paths_from_report(report: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    export_files = report.get("export_files")
    if isinstance(export_files, Mapping):
        for key, value in export_files.items():
            if not isinstance(value, str) or not value:
                continue
            if key.endswith("_path") or key.endswith("_dir"):
                paths.append(value)
    for key in ("report_json_path", "report_md_path", "report_txt_path"):
        value = report.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    return sorted(set(paths))


def _audit_paths_from_report(report: Mapping[str, Any], *, mode: str) -> list[str]:
    export_files = report.get("export_files")
    if not isinstance(export_files, Mapping):
        return _output_paths_from_report(report)
    if mode == "event_forensic":
        raw_dir = str(export_files.get("raw_event_bundle_dir") or "")
        if raw_dir:
            return [str(path) for path in _bounded_event_audit_paths(Path(raw_dir).parent)]
    if mode == "archive":
        report_json = str(export_files.get("report_json_path") or report.get("report_json_path") or "")
        if report_json:
            return [report_json]
    return _output_paths_from_report(report)


def _bounded_saved_output_audit_paths(path: Path) -> list[Path]:
    if path.is_dir() and path.name.startswith("event_forensic_"):
        return _bounded_event_audit_paths(path)
    return [path]


def _bounded_event_audit_paths(bundle_dir: Path) -> list[Path]:
    names = (
        "event_analysis.json",
        "suspicious_trades.csv",
        "wallet_context.csv",
        "suspicious_wallets.csv",
        "candidate_admission_funnel.json",
    )
    return [bundle_dir / name for name in names if (bundle_dir / name).exists()]


def _selected_categories(client: Any, labels: list[str]) -> tuple[Any, ...]:
    selected = {str(label).strip() for label in labels if str(label).strip()}
    if not selected:
        raise ValueError("Archive target requires at least one category label.")
    categories = tuple(category for category in client.fetch_site_categories() if category.label in selected)
    if not categories:
        raise ValueError(f"No configured archive categories matched: {', '.join(sorted(selected))}")
    return categories


def _parse_archive_window(value: str) -> tuple[datetime, datetime]:
    if "/" not in value:
        raise ValueError("Archive window must be start/end ISO values separated by '/'.")
    start_raw, end_raw = value.split("/", 1)
    return _parse_datetime(start_raw), _parse_datetime(end_raw)


def _parse_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _decimal_or_none(value: Any) -> Decimal | None:
    text = str(value or "").replace(",", "").replace("$", "").strip()
    return Decimal(text) if text else None


def _int_or_none(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def run_selected_audit(paths: Iterable[str], output_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
    selected_paths = [Path(path) for path in paths if str(path or "").strip()]
    if not selected_paths:
        return _empty_audit_summary(), {}
    from tools.model_behavior_audit import (
        audit_records,
        collect_funnels,
        collect_records,
        write_audit_outputs,
        write_strong_risk_deep_dive_outputs,
    )

    records = collect_records(selected_paths)
    funnels = collect_funnels(selected_paths)
    summary = audit_records(records, funnels=funnels)
    audit_paths = write_audit_outputs(
        summary,
        output_dir=output_dir,
        filename_prefix="post_v2_corpus_audit",
    )
    deep_dive_paths = write_strong_risk_deep_dive_outputs(summary, output_dir=output_dir)
    audit_paths = {
        **audit_paths,
        "strong_risk_deep_dive_markdown_path": deep_dive_paths["markdown_path"],
        "strong_risk_deep_dive_json_path": deep_dive_paths["json_path"],
    }
    return summary, audit_paths


def strong_risk_exact_provenance_by_target_status(
    target_results: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    from tools.model_behavior_audit import normalize_record

    result: dict[str, Counter[str]] = {}
    exact_distributions: dict[str, Counter[str]] = {}
    issue_distributions: dict[str, Counter[str]] = {}
    for target in target_results:
        status = str(target.get("status") or "unknown")
        bucket = (
            "audit_only_saved_output"
            if status == "audit_only_saved_output"
            else "fresh_generated"
            if status in TARGET_COMPLETED_STATUSES
            else status
        )
        result.setdefault(bucket, Counter())
        exact_distributions.setdefault(bucket, Counter())
        issue_distributions.setdefault(bucket, Counter())
        for row in _iter_target_status_audit_rows(target):
            normalized = normalize_record(row)
            if not normalized["strong_risk"]:
                continue
            counts = result[bucket]
            counts["strong_risk_rows"] += 1
            if normalized["schema_has_new_fields"] and not normalized["strong_risk_exact_gate_branch_present"]:
                counts["exact_gate_branch_missing_new_format_rows"] += 1
            if not normalized["schema_has_new_fields"]:
                counts["legacy_strong_risk_rows"] += 1
            if normalized["strong_risk_score_only_resolution"] == "actual_score_only_gate_leakage_candidate":
                counts["score_only_after_exact_provenance_rows"] += 1
            if normalized["strong_risk_gate_leakage_candidate"]:
                counts["gate_leakage_candidate_rows"] += 1
            if normalized["strong_risk_exact_inferred_gate_disagree"]:
                counts["exact_inferred_gate_disagree_rows"] += 1
            if normalized["strong_risk_structural_but_not_hard_evidence"]:
                counts["structural_but_not_hard_evidence_rows"] += 1
            if normalized["strong_risk_suppressor_conflict"]:
                counts["suppressor_conflict_rows"] += 1
            if normalized["strong_risk_suppressor_conflict"] and not normalized["strong_risk_structural_sources_resolved"]:
                counts["suppressor_conflict_without_structural_support_rows"] += 1
            if normalized["strong_risk_gate_type"] == "timing_led" and not normalized["strong_risk_structural_sources_resolved"]:
                counts["timing_led_without_structural_support_rows"] += 1
            if (
                normalized["repricing_source_quality"] in {"weak", "mechanical", "unknown"}
                and "rapid_favorable_repricing" in normalized["strong_risk_timing_proof_sources"]
                and not normalized["strong_risk_structural_sources_resolved"]
            ):
                counts["weak_mechanical_unknown_repricing_without_structural_support_rows"] += 1
            if normalized["strong_risk_live_detectable"]:
                counts["live_detectable_rows"] += 1
            if normalized["strong_risk_retrospective_only"]:
                counts["retrospective_only_rows"] += 1
            if not normalized["hard_evidence_sources"]:
                counts["no_hard_evidence_sources_rows"] += 1
            exact_distributions[bucket][normalized["strong_risk_exact_gate_branch"]] += 1
            issue_distributions[bucket][normalized["strong_risk_source_attribution_issue"]] += 1

    summary: dict[str, dict[str, Any]] = {}
    for bucket, counts in result.items():
        summary[bucket] = {
            **dict(sorted(counts.items())),
            "exact_gate_branch_distribution": dict(sorted(exact_distributions[bucket].items())),
            "source_attribution_issue_distribution": dict(sorted(issue_distributions[bucket].items())),
        }
    return summary


def _iter_target_status_audit_rows(target: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    for path in _target_status_audit_files(target):
        yield from _iter_rows_from_status_file(path)


def _target_status_audit_files(target: Mapping[str, Any]) -> list[Path]:
    output_paths = target.get("output_paths") or target.get("selected_outputs") or []
    files: list[Path] = []
    seen: set[str] = set()
    for value in output_paths:
        path = Path(str(value))
        candidates: list[Path] = []
        if path.is_dir() and path.name.startswith("event_forensic_"):
            candidates.extend(
                child
                for name in ("event_analysis.json", "suspicious_trades.csv", "wallet_context.csv", "suspicious_wallets.csv")
                if (child := path / name).exists()
            )
        elif path.name in {"event_analysis.json", "suspicious_trades.csv", "wallet_context.csv", "suspicious_wallets.csv"}:
            candidates.append(path)
        elif path.name.endswith(("_flagged.csv", "_candidates.csv")):
            candidates.append(path)
        elif path.suffix == ".json" and path.name.startswith("archive_research_") and "candidate_admission" not in path.name:
            candidates.append(path)
        for candidate in candidates:
            key = str(candidate)
            if candidate.exists() and key not in seen:
                files.append(candidate)
                seen.add(key)
    return files


def _iter_rows_from_status_file(path: Path) -> Iterable[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle), start=1):
                item = dict(row)
                item["_audit_source_path"] = str(path)
                item["_audit_source_row"] = str(index)
                yield item
        return
    if path.suffix.lower() != ".json":
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    for index, row in enumerate(_iter_status_json_records(payload), start=1):
        item = dict(row)
        item["_audit_source_path"] = str(path)
        item["_audit_source_row"] = str(index)
        yield item


def _iter_status_json_records(payload: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_status_json_records(item)
        return
    if not isinstance(payload, Mapping):
        return
    keys = set(payload)
    if (
        keys
        & {
            "severity",
            "finalEventJudgment",
            "existingModelClass",
            "strongRiskGateType",
            "strongRiskExactGateBranch",
            "hardEvidenceSources",
        }
        and keys
        & {"id", "tradeId", "wallet", "conditionId", "market", "eventForensicScore", "rawMetrics"}
    ):
        yield payload
    for value in payload.values():
        if isinstance(value, (list, Mapping)):
            yield from _iter_status_json_records(value)


def _empty_audit_summary() -> dict[str, Any]:
    return {
        "total_rows_inspected": 0,
        "event_forensic_rows_inspected": 0,
        "archive_rows_inspected": 0,
        "visible_rows": 0,
        "rawVisibleRows": 0,
        "uniqueVisibleRows": 0,
        "visibleDedupeRatio": 0.0,
        "strong_risk_rows": 0,
        "rawStrongRiskRows": 0,
        "uniqueStrongRiskRows": 0,
        "strongRiskDedupeRatio": 0.0,
        "hard_evidence_review_rows": 0,
        "rawHardEvidenceReviewRows": 0,
        "uniqueHardEvidenceReviewRows": 0,
        "hardEvidenceReviewDedupeRatio": 0.0,
        "normal_candidate_rows": 0,
        "pre_admitted_candidate_rows": 0,
        "warnings": [],
        "distributions": {},
        "hard_evidence_pathway_counts": {},
        "strong_risk_composition": {},
        "strong_risk_deep_dive": {},
        "hard_evidence_starvation": {},
        "pre_admission_funnel": {},
    }


def build_corpus_summary(
    *,
    corpus: Mapping[str, Any],
    target_results: list[Mapping[str, Any]],
    selected_output_paths: list[str],
    audit_summary: Mapping[str, Any],
    audit_output_paths: Mapping[str, str],
    validation_policy: str = "direct",
    network_probe_status: str = "",
    network_probe_output_path: str = "",
    full_network_attempted: bool = False,
    cache_only_fallback_used: bool = False,
    fallback_reason: str = "",
    fallback_source_summary: Mapping[str, Any] | None = None,
    stopped_early_reason: str = "",
) -> dict[str, Any]:
    status_counts = Counter(str(result.get("status") or "unknown") for result in target_results)
    tag_counts: Counter[str] = Counter()
    completed_tags: Counter[str] = Counter()
    for result in target_results:
        tags = [str(tag) for tag in result.get("tags") or []]
        tag_counts.update(tags)
        if str(result.get("status") or "") in TARGET_COMPLETED_STATUSES:
            completed_tags.update(tags)
    audit_summary_dict = dict(audit_summary)
    provenance_split = strong_risk_exact_provenance_by_target_status(target_results)
    audit_summary_dict["strong_risk_exact_provenance_by_target_status"] = provenance_split
    classification = classify_corpus_result(
        target_results=target_results,
        audit_summary=audit_summary_dict,
        completed_tags=completed_tags,
    )
    interpreted_model_evidence_targets = sum(
        1
        for result in target_results
        if str(result.get("status") or "") in TARGET_COMPLETED_STATUSES
        and str(result.get("status") or "") != "audit_only_saved_output"
    )
    final_classification = _policy_adjusted_classification(
        classification,
        validation_policy=validation_policy,
        network_probe_status=network_probe_status,
        full_network_attempted=full_network_attempted,
        cache_only_fallback_used=cache_only_fallback_used,
        target_results=target_results,
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus_name": corpus.get("corpusName") or corpus.get("corpus_name") or "post_v2_validation_corpus",
        "terminalState": "completed",
        "terminalArtifactKind": "final_corpus",
        "validationPolicy": validation_policy,
        "networkProbeStatus": network_probe_status,
        "networkProbeOutputPath": network_probe_output_path,
        "fullNetworkAttempted": full_network_attempted,
        "cacheOnlyFallbackUsed": cache_only_fallback_used,
        "fallbackReason": fallback_reason,
        "fallbackSourceSummary": dict(fallback_source_summary or {}),
        "stoppedEarlyReason": stopped_early_reason,
        "interpretableModelEvidenceTargets": interpreted_model_evidence_targets,
        "target_status_counts": dict(sorted(status_counts.items())),
        "target_tag_counts": dict(sorted(tag_counts.items())),
        "completed_target_tag_counts": dict(sorted(completed_tags.items())),
        "total_targets": len(target_results),
        "completed_targets": sum(status_counts.get(status, 0) for status in TARGET_COMPLETED_STATUSES),
        "skipped_targets": status_counts.get("skipped_missing_input", 0),
        "aborted_targets": status_counts.get("aborted_timeout", 0) + status_counts.get("aborted_rpc_stall", 0),
        "funding_enabled_targets": status_counts.get("completed_funding_enabled", 0),
        "cache_only_targets": status_counts.get("completed_cache_only", 0),
        "funding_blocked_targets": status_counts.get("completed_funding_blocked", 0),
        "timeout_targets": status_counts.get("aborted_timeout", 0),
        "rpc_stall_targets": status_counts.get("aborted_rpc_stall", 0),
        "selected_output_paths": selected_output_paths,
        "audit_output_paths": dict(audit_output_paths),
        "audit_summary": audit_summary_dict,
        "rawVisibleRows": audit_summary_dict.get("rawVisibleRows", audit_summary_dict.get("visible_rows", 0)),
        "uniqueVisibleRows": audit_summary_dict.get("uniqueVisibleRows", "unknown"),
        "visibleDedupeRatio": audit_summary_dict.get("visibleDedupeRatio", "unknown"),
        "rawStrongRiskRows": audit_summary_dict.get("rawStrongRiskRows", audit_summary_dict.get("strong_risk_rows", 0)),
        "uniqueStrongRiskRows": audit_summary_dict.get("uniqueStrongRiskRows", "unknown"),
        "strongRiskDedupeRatio": audit_summary_dict.get("strongRiskDedupeRatio", "unknown"),
        "rawHardEvidenceReviewRows": audit_summary_dict.get("rawHardEvidenceReviewRows", audit_summary_dict.get("hard_evidence_review_rows", 0)),
        "uniqueHardEvidenceReviewRows": audit_summary_dict.get("uniqueHardEvidenceReviewRows", "unknown"),
        "hardEvidenceReviewDedupeRatio": audit_summary_dict.get("hardEvidenceReviewDedupeRatio", "unknown"),
        "topDuplicateStrongRiskKeys": audit_summary_dict.get("topDuplicateStrongRiskKeys", []),
        "topDuplicateHardEvidenceReviewKeys": audit_summary_dict.get("topDuplicateHardEvidenceReviewKeys", []),
        "topDuplicateTargets": audit_summary_dict.get("topDuplicateTargets", {}),
        "target_results": [dict(result) for result in target_results],
        "final_classification": final_classification,
        "base_model_classification": classification,
        "recommended_next_task": recommended_next_task(final_classification),
    }


def _policy_adjusted_classification(
    classification: str,
    *,
    validation_policy: str,
    network_probe_status: str,
    full_network_attempted: bool,
    cache_only_fallback_used: bool,
    target_results: Iterable[Mapping[str, Any]],
) -> str:
    if classification != "post-v2 behavior acceptable":
        return classification
    if cache_only_fallback_used:
        return "post-v2 behavior acceptable on cache-only corpus"
    if validation_policy == "network_probe":
        return network_probe_status or classification
    if full_network_attempted:
        statuses = Counter(str(result.get("status") or "") for result in target_results)
        if statuses.get("completed_funding_enabled", 0) > 0 and not (
            statuses.get("aborted_rpc_stall", 0)
            or statuses.get("aborted_timeout", 0)
            or statuses.get("completed_funding_blocked", 0)
        ):
            return "network validation stable"
    return classification


def _compact_fallback_source_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    target_results = [result for result in summary.get("target_results", []) if isinstance(result, Mapping)]
    statuses = Counter(str(result.get("status") or "unknown") for result in target_results)
    target_samples = []
    for result in target_results[:8]:
        target_samples.append(
            {
                "label": str(result.get("label") or ""),
                "status": str(result.get("status") or ""),
                "validationAbortReason": str(result.get("validationAbortReason") or ""),
                "fundingTraceStallReason": str(result.get("fundingTraceStallReason") or ""),
                "fundingResolverFunctionalStatus": str(result.get("fundingResolverFunctionalStatus") or ""),
            }
        )
    return {
        "validationPolicy": summary.get("validationPolicy", ""),
        "finalClassification": summary.get("final_classification", ""),
        "stoppedEarlyReason": summary.get("stoppedEarlyReason", ""),
        "targetStatusCounts": dict(sorted(statuses.items())),
        "completedTargets": summary.get("completed_targets", 0),
        "abortedTargets": summary.get("aborted_targets", 0),
        "fundingEnabledTargets": summary.get("funding_enabled_targets", 0),
        "fundingBlockedTargets": summary.get("funding_blocked_targets", 0),
        "timeoutTargets": summary.get("timeout_targets", 0),
        "rpcStallTargets": summary.get("rpc_stall_targets", 0),
        "sampleTargets": target_samples,
    }


def classify_corpus_result(
    *,
    target_results: Iterable[Mapping[str, Any]],
    audit_summary: Mapping[str, Any],
    completed_tags: Mapping[str, int] | None = None,
) -> str:
    results = list(target_results)
    status_counts = Counter(str(result.get("status") or "unknown") for result in results)
    warning_codes = {
        str(warning.get("code") or "")
        for warning in audit_summary.get("warnings", [])
        if isinstance(warning, Mapping)
    }
    pathway = audit_summary.get("hard_evidence_pathway_counts") or {}
    starvation = audit_summary.get("hard_evidence_starvation") or {}
    strong = audit_summary.get("strong_risk_composition") or {}
    funnel = audit_summary.get("pre_admission_funnel") or {}
    provenance_split = audit_summary.get("strong_risk_exact_provenance_by_target_status") or {}
    fresh_provenance = provenance_split.get("fresh_generated") if isinstance(provenance_split, Mapping) else {}

    overbroad_codes = {
        "suspicious_funding_only_suppressor_conflict",
        "multi_hop_unknown_hard_evidence_without_independent_support",
        "weak_suspicious_funding_only_hard_evidence_review",
        "unknown_suspicious_funding_hard_evidence_review",
        "cex_proxy_only_hard_evidence_review",
        "cex_bridge_proxy_suspicious_funding_hard_evidence_review",
    }
    if warning_codes & overbroad_codes or any(
        int(pathway.get(key) or 0) > 0
        for key in (
            "suspicious_funding_only_hard_evidence_review_with_suppressors",
            "multi_hop_unknown_hard_evidence_review_without_independent_support",
        )
    ):
        return "suspicious funding still overbroad"

    if int(starvation.get("independent_sources_not_routed_to_hard_evidence_review_rows") or 0) > 0:
        return "hard-evidence starvation suspected"

    strong_risk_rows = int(audit_summary.get("strong_risk_rows") or 0)
    fresh_strong_rows = int(fresh_provenance.get("strong_risk_rows") or 0) if isinstance(fresh_provenance, Mapping) else 0
    if fresh_strong_rows:
        fresh_missing_exact = int(fresh_provenance.get("exact_gate_branch_missing_new_format_rows") or 0)
        fresh_leakage = int(fresh_provenance.get("gate_leakage_candidate_rows") or 0)
        fresh_score_only_after_exact = int(fresh_provenance.get("score_only_after_exact_provenance_rows") or 0)
        fresh_weak_repricing = int(
            fresh_provenance.get("weak_mechanical_unknown_repricing_without_structural_support_rows") or 0
        )
        fresh_timing_no_structure = int(
            fresh_provenance.get("timing_led_without_structural_support_rows") or 0
        )
        fresh_suppressor_no_structure = int(
            fresh_provenance.get("suppressor_conflict_without_structural_support_rows") or 0
        )
        issue_dist = fresh_provenance.get("source_attribution_issue_distribution") or {}
        if isinstance(issue_dist, Mapping):
            source_export_gap = int(issue_dist.get("schema_propagation_gap") or 0) + int(
                issue_dist.get("hard_evidence_source_missing") or 0
            )
            if source_export_gap:
                return "source-attribution repair needed"
        if fresh_missing_exact or fresh_leakage or fresh_score_only_after_exact:
            return "strong-risk composition concern"
        if fresh_weak_repricing and (fresh_timing_no_structure / fresh_strong_rows) > 0.5:
            return "strong-risk composition concern"
        if (fresh_suppressor_no_structure / fresh_strong_rows) > 0.2:
            non_hard = int(fresh_provenance.get("structural_but_not_hard_evidence_rows") or 0)
            if non_hard < fresh_suppressor_no_structure:
                return "strong-risk composition concern"
        # Fresh generated Strong Risk rows are interpretable; let legacy/audit-only warnings inform reporting but not
        # force a gate-leakage classification.
        if int(fresh_provenance.get("structural_but_not_hard_evidence_rows") or 0) >= max(1, fresh_strong_rows // 2):
            pass

    if strong_risk_rows and not fresh_strong_rows:
        leakage = int(strong.get("strong_risk_gate_leakage_candidate_rows") or 0)
        missing_exact = int(strong.get("strong_risk_new_format_missing_exact_gate_branch_rows") or 0)
        issue_dist = strong.get("strong_risk_rows_by_source_attribution_issue")
        if isinstance(issue_dist, Mapping):
            propagation_or_export = int(issue_dist.get("schema_propagation_gap") or 0) + int(
                issue_dist.get("hard_evidence_source_missing") or 0
            )
            problematic = propagation_or_export + int(issue_dist.get("inference_insufficient") or 0)
            if propagation_or_export and propagation_or_export >= max(1, problematic // 2):
                return "source-attribution repair needed"
        suppressor_no_structure = int(
            strong.get("strong_risk_suppressor_conflict_without_structure_rows") or 0
        )
        timing_only_attributed = int(strong.get("strong_risk_timing_only_rows") or 0)
        weak_repricing = int(strong.get("strong_risk_weak_mechanical_unknown_repricing_rows") or 0)
        if (
            leakage
            or missing_exact
            or (suppressor_no_structure / strong_risk_rows) > 0.2
            or (timing_only_attributed / strong_risk_rows > 0.5 and weak_repricing)
        ):
            return "strong-risk composition concern"
        no_sources = int(strong.get("strong_risk_rows_with_no_hard_evidence_sources") or 0)
        timing_only = int(strong.get("strong_risk_rows_driven_by_timing_repricing_only") or 0)
        opening_not_confirmed = int(strong.get("strong_risk_rows_opening_exposure_not_confirmed") or 0)
        if opening_not_confirmed or (no_sources + timing_only) / strong_risk_rows >= 0.5:
            return "strong-risk composition concern"

    blocked = (
        status_counts.get("completed_funding_blocked", 0)
        + status_counts.get("aborted_timeout", 0)
        + status_counts.get("aborted_rpc_stall", 0)
    )
    interpreted = (
        status_counts.get("completed_funding_enabled", 0)
        + status_counts.get("completed_cache_only", 0)
        + status_counts.get("completed_no_funding_candidates", 0)
        + status_counts.get("audit_only_saved_output", 0)
    )
    if blocked and blocked >= max(1, interpreted):
        return "funding infrastructure bottleneck"

    funding_enabled = status_counts.get("completed_funding_enabled", 0) + status_counts.get("completed_cache_only", 0)
    completed = sum(status_counts.get(status, 0) for status in TARGET_COMPLETED_STATUSES)
    tags = completed_tags or {}
    fresh_rerunnable_completed = sum(
        1
        for result in results
        if str(result.get("status") or "") in TARGET_COMPLETED_STATUSES
        and str(result.get("status") or "") != "audit_only_saved_output"
        and "fresh_rerunnable" in {str(tag) for tag in result.get("tags") or []}
    )
    audit_only_completed = status_counts.get("audit_only_saved_output", 0)
    category_markers = {
        key
        for key, count in tags.items()
        if count and key in TARGET_FAMILY_TAGS
    }
    archive_rows = int(audit_summary.get("archive_rows_inspected") or 0)
    archive_targets = int(tags.get("archive") or 0)
    non_gta_targets = int(tags.get("non_gta") or 0)
    if (
        fresh_rerunnable_completed < 8
        or completed < 8
        or len(category_markers) < 3
        or archive_targets < 4
        or non_gta_targets < 4
        or archive_rows < 10
        or (audit_only_completed and fresh_rerunnable_completed < audit_only_completed)
    ):
        return "corpus still too narrow"

    near_miss = int(funnel.get("total_near_miss_groups") or 0)
    trace_attempts = int(funnel.get("funding_trace_attempted_count") or 0)
    validated_pre_admissions = int(funnel.get("total_validated") or 0)
    if near_miss > 0 and trace_attempts == 0:
        return "candidate recall concern"
    if near_miss >= 50 and validated_pre_admissions == 0:
        return "candidate recall concern"

    return "post-v2 behavior acceptable"


def select_network_probe_corpus(
    corpus: Mapping[str, Any],
    max_targets: int,
    *,
    preserve_order: bool = False,
) -> dict[str, Any]:
    targets = [dict(item) for item in corpus.get("targets", []) if isinstance(item, Mapping)]
    network_allowed = [
        target
        for target in targets
        if str(target.get("inputType") or "") != "saved_output_replay"
        and "network_allowed" in {str(tag) for tag in target.get("tags") or []}
    ]
    if not network_allowed:
        network_allowed = [target for target in targets if str(target.get("inputType") or "") != "saved_output_replay"]
    if preserve_order:
        payload = dict(corpus)
        payload["targets"] = network_allowed[: max(1, max_targets)]
        payload["corpusName"] = f"{corpus.get('corpusName') or 'post_v2_validation_corpus'}_network_probe"
        return payload
    payload = select_smoke_corpus({**dict(corpus), "targets": network_allowed}, max_targets)
    payload["corpusName"] = f"{corpus.get('corpusName') or 'post_v2_validation_corpus'}_network_probe"
    return payload


def select_smoke_corpus(
    corpus: Mapping[str, Any],
    max_targets: int,
    *,
    prewarm_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    targets = [dict(item) for item in corpus.get("targets", []) if isinstance(item, Mapping)]
    prewarmed_labels = _prewarmed_target_rank(prewarm_summary or {})

    def _sort_key(index_target: tuple[int, dict[str, Any]]) -> tuple[int, int, float, int, int]:
        index, target = index_target
        label = str(target.get("label") or "")
        tags = {str(tag) for tag in target.get("tags") or []}
        input_type = str(target.get("inputType") or "")
        mode = str(target.get("mode") or "")
        hours = _archive_window_hours(target)
        high_volume_penalty = 2 if "high_volume" in tags else 0
        fresh_penalty = 0 if bool(target.get("freshRerunnable")) or "fresh_rerunnable" in tags else 1
        prewarm_rank = prewarmed_labels.get(label, 9)
        if mode == "archive" and input_type == "archive_window" and hours is not None:
            if hours <= 24:
                band = 0
            elif hours <= 72:
                band = 1
            else:
                band = 5
            archive_prewarm_rank = prewarm_rank
            if prewarm_rank < 3 and hours > 6:
                archive_prewarm_rank += 2 if hours <= 24 else 4
            return (archive_prewarm_rank, band + high_volume_penalty, hours, fresh_penalty, index)
        if input_type == "saved_output_replay":
            return (prewarm_rank, 6 + high_volume_penalty, 0.0, fresh_penalty, index)
        return (
            prewarm_rank,
            3 + high_volume_penalty,
            hours if hours is not None else 999999.0,
            fresh_penalty,
            index,
        )

    selected = [
        target
        for _index, target in sorted(enumerate(targets), key=_sort_key)
    ][: max(1, max_targets)]
    payload = dict(corpus)
    payload["targets"] = selected
    payload["corpusName"] = f"{corpus.get('corpusName') or 'post_v2_validation_corpus'}_smoke"
    return payload


def _prewarmed_target_rank(prewarm_summary: Mapping[str, Any]) -> dict[str, int]:
    ranks: dict[str, int] = {}
    target_results = prewarm_summary.get("target_results")
    if not isinstance(target_results, list):
        return ranks
    for result in target_results:
        if not isinstance(result, Mapping):
            continue
        label = str(result.get("label") or "")
        if not label:
            continue
        status = str(result.get("status") or "")
        trace_succeeded = _as_int(result.get("traceSucceededDelta"))
        cache_hits = _as_int(result.get("cacheHitsObserved"))
        failures = _as_int(result.get("failuresObserved"))
        windows_attempted = _as_int(result.get("windowsAttempted"))
        if status == "completed" and trace_succeeded > 0:
            rank = 0
        elif status == "completed" and cache_hits > 0 and failures < max(1, windows_attempted):
            rank = 1
        elif status == "completed":
            rank = 2
        elif status in {"skipped_no_metadata", "skipped_global_limit"}:
            rank = 8
        else:
            rank = 7
        ranks[label] = min(rank, ranks.get(label, rank))
    return ranks


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _latest_prewarm_summary(output_dir: Path) -> dict[str, Any]:
    root = output_dir if output_dir.is_absolute() else REPO_ROOT / output_dir
    candidates = sorted(
        root.glob("funding_cache_prewarm_*.json"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping):
            return dict(payload)
    return {}


def _archive_window_hours(target: Mapping[str, Any]) -> float | None:
    if str(target.get("inputType") or "") != "archive_window":
        return None
    value = str(target.get("inputValue") or "")
    if "/" not in value:
        return None
    start_raw, end_raw = value.split("/", 1)
    try:
        start = _parse_datetime(start_raw)
        end = _parse_datetime(end_raw)
    except Exception:
        return None
    return max((end - start).total_seconds() / 3600, 0.0)


def classify_network_probe(summary: Mapping[str, Any]) -> str:
    statuses = Counter(str(result.get("status") or "") for result in summary.get("target_results", []))
    if statuses.get("failed_runtime_error", 0):
        return "network_probe_runtime_error"
    if statuses.get("aborted_rpc_stall", 0) or statuses.get("aborted_timeout", 0):
        return "network_probe_stalled"
    if statuses.get("completed_funding_blocked", 0):
        reasons = Counter(
            str(result.get("validationAbortReason") or result.get("fundingTraceStallReason") or "")
            for result in summary.get("target_results", [])
        )
        if any("rate" in reason.lower() or "rpc" in reason.lower() for reason in reasons):
            return "network_probe_rate_limited"
        return "network_probe_funding_blocked"
    if (
        statuses.get("completed_funding_enabled", 0)
        or statuses.get("completed_cache_only", 0)
        or statuses.get("completed_no_funding_candidates", 0)
    ):
        return "network_probe_passed"
    return "network_probe_runtime_error"


def _network_probe_should_allow_full_network(status: str) -> bool:
    return status == "network_probe_passed"


def run_network_probe(
    corpus: Mapping[str, Any],
    *,
    max_targets: int | None,
    settings: ValidationSettings,
    terminal_artifact_label: str = "",
    preserve_order: bool = False,
) -> tuple[dict[str, Any], dict[str, str], str]:
    probe_count = max_targets if max_targets is not None else settings.network_probe_targets
    probe_corpus = select_network_probe_corpus(corpus, probe_count, preserve_order=preserve_order)
    probe_summary = run_corpus(
        probe_corpus,
        max_targets=probe_count,
        skip_rerun=False,
        audit_only=False,
        settings=settings,
        validation_policy="network_probe",
        full_network_attempted=True,
        terminal_artifact_label=terminal_artifact_label,
    )
    probe_status = classify_network_probe(probe_summary)
    probe_summary["networkProbeStatus"] = probe_status
    probe_summary["final_classification"] = probe_status
    probe_summary["recommended_next_task"] = recommended_next_task(probe_status)
    output_paths = write_corpus_outputs(probe_summary, settings.output_dir)
    return probe_summary, output_paths, probe_status


def run_auto_policy(
    corpus: Mapping[str, Any],
    *,
    max_targets: int | None,
    skip_rerun: bool,
    audit_only: bool,
    settings: ValidationSettings,
    fallback_corpus: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    cache_fallback_corpus = fallback_corpus or corpus
    health_report = run_healthcheck()
    health_outputs = write_health_outputs(health_report)
    if health_report.get("overall_status") != "available_for_funding_trace":
        cache_settings = replace(settings, allow_network_funding=False)
        summary = run_corpus(
            cache_fallback_corpus,
            max_targets=max_targets,
            skip_rerun=skip_rerun,
            audit_only=audit_only,
            settings=cache_settings,
            validation_policy="auto_policy",
            network_probe_status=str(health_report.get("overall_status") or "not_available"),
            full_network_attempted=False,
            cache_only_fallback_used=True,
            fallback_reason="healthcheck_not_available_for_funding_trace",
            fallback_source_summary={
                "validationPolicy": "healthcheck",
                "overallStatus": health_report.get("overall_status", ""),
                "authError": health_report.get("auth_error", False),
                "lightweightAvailable": health_report.get("lightweight_available", False),
                "fundingTraceAvailable": health_report.get("funding_trace_available", False),
            },
            terminal_artifact_label="auto_policy_healthcheck_cache_fallback",
        )
        output_paths = write_corpus_outputs(summary, settings.output_dir)
        return summary, output_paths, {"healthcheck_json_path": health_outputs["json_path"], "healthcheck_markdown_path": health_outputs["markdown_path"]}

    probe_settings = replace(
        settings,
        allow_network_funding=True,
        timeout_seconds=min(settings.timeout_seconds, 300),
    )
    probe_summary, probe_outputs, probe_status = run_network_probe(
        corpus,
        max_targets=min(settings.network_probe_targets, max_targets or settings.network_probe_targets),
        settings=probe_settings,
        terminal_artifact_label="auto_policy_network_probe",
        preserve_order=str(corpus.get("corpusName") or "").endswith("_smoke"),
    )
    if _network_probe_should_allow_full_network(probe_status):
        network_summary = run_corpus(
            corpus,
            max_targets=max_targets,
            skip_rerun=skip_rerun,
            audit_only=audit_only,
            settings=replace(settings, allow_network_funding=True),
            validation_policy="auto_policy",
            network_probe_status=probe_status,
            network_probe_output_path=probe_outputs["json_path"],
            full_network_attempted=True,
            cache_only_fallback_used=False,
            terminal_artifact_label="auto_policy_full_network",
        )
        statuses = Counter(str(result.get("status") or "") for result in network_summary.get("target_results", []))
        stalls = statuses.get("aborted_rpc_stall", 0) + statuses.get("aborted_timeout", 0)
        blocked = statuses.get("completed_funding_blocked", 0)
        if settings.auto_cache_fallback and (
            network_summary.get("stoppedEarlyReason")
            or stalls >= max(1, settings.max_rpc_stall_targets)
            or blocked >= max(1, settings.max_rpc_stall_targets)
        ):
            cache_settings = replace(settings, allow_network_funding=False)
            summary = run_corpus(
                cache_fallback_corpus,
                max_targets=max_targets,
                skip_rerun=skip_rerun,
                audit_only=audit_only,
                settings=cache_settings,
                validation_policy="auto_policy",
                network_probe_status=probe_status,
                network_probe_output_path=probe_outputs["json_path"],
                full_network_attempted=True,
                cache_only_fallback_used=True,
                fallback_reason="full_network_stalled_or_blocked",
                fallback_source_summary=_compact_fallback_source_summary(network_summary),
                terminal_artifact_label="auto_policy_cache_fallback",
            )
            output_paths = write_corpus_outputs(summary, settings.output_dir)
            return summary, output_paths, {
                "healthcheck_json_path": health_outputs["json_path"],
                "healthcheck_markdown_path": health_outputs["markdown_path"],
                "network_probe_json_path": probe_outputs["json_path"],
                "network_probe_markdown_path": probe_outputs["markdown_path"],
            }
        output_paths = write_corpus_outputs(network_summary, settings.output_dir)
        return network_summary, output_paths, {
            "healthcheck_json_path": health_outputs["json_path"],
            "healthcheck_markdown_path": health_outputs["markdown_path"],
            "network_probe_json_path": probe_outputs["json_path"],
            "network_probe_markdown_path": probe_outputs["markdown_path"],
        }

    cache_settings = replace(settings, allow_network_funding=False)
    summary = run_corpus(
        cache_fallback_corpus,
        max_targets=max_targets,
        skip_rerun=skip_rerun,
        audit_only=audit_only,
        settings=cache_settings,
        validation_policy="auto_policy",
        network_probe_status=probe_status,
        network_probe_output_path=probe_outputs["json_path"],
        full_network_attempted=False,
        cache_only_fallback_used=True,
        fallback_reason=probe_status,
        fallback_source_summary=_compact_fallback_source_summary(probe_summary),
        terminal_artifact_label="auto_policy_cache_fallback",
    )
    output_paths = write_corpus_outputs(summary, settings.output_dir)
    return summary, output_paths, {
        "healthcheck_json_path": health_outputs["json_path"],
        "healthcheck_markdown_path": health_outputs["markdown_path"],
        "network_probe_json_path": probe_outputs["json_path"],
        "network_probe_markdown_path": probe_outputs["markdown_path"],
    }


def recommended_next_task(classification: str) -> str:
    return {
        "post-v2 behavior acceptable": "Continue with validation corpus expansion only if a broader category mix is needed before the next production model change.",
        "post-v2 behavior acceptable on cache-only corpus": "Treat model evidence as cache-only; rerun a small network probe periodically before attempting full public-RPC validation.",
        "network validation stable": "Run acceptance and recall reports on the funding-enabled corpus before any production model change.",
        "public RPC insufficient for full network corpus": "Use cache-only validation for model interpretation and periodically rerun network probes.",
        "network_probe_passed": "A small network probe passed; full network corpus can be attempted if runtime budget allows.",
        "network_probe_rate_limited": "Skip full network corpus and use cache-only validation unless a stronger RPC endpoint is configured.",
        "network_probe_stalled": "Skip full network corpus and use cache-only validation; inspect network funding diagnostics.",
        "network_probe_funding_blocked": "Skip full network corpus and use cache-only validation; inspect funding health and endpoint accounting.",
        "network_probe_runtime_error": "Fix validation target/runtime errors before using network corpus evidence.",
        "runtime harness bug": "Repair validation timeout/status accounting before interpreting model behavior.",
        "corpus still too narrow": "Add or recover more diverse saved inputs and pre-warm cache for non-GTA Event/Archive targets before interpreting model rarity.",
        "funding infrastructure bottleneck": "Improve public-RPC capacity or cache prewarming before further model interpretation.",
        "hard-evidence starvation suspected": "Inspect saved rows with independent support not routed to Hard Evidence Review before changing rules.",
        "suspicious funding still overbroad": "Inspect suspicious-funding-only Hard Evidence Review rows and fix routing/schema parity before broad validation.",
        "strong-risk composition concern": "Manually inspect Strong Risk rows and saved gate fields without changing gates in this validation task.",
        "source-attribution repair needed": "Repair Strong Risk source export/schema propagation before changing gates.",
        "candidate recall concern": "Run a read-only false-negative opportunity audit before changing admission rules.",
    }.get(classification, "Inspect corpus and audit warnings before making model changes.")


def write_corpus_outputs(
    summary: Mapping[str, Any],
    output_dir: Path,
    *,
    timestamp: str | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"post_v2_corpus_{stamp}.json"
    markdown_path = output_dir / f"post_v2_corpus_{stamp}.md"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    markdown_path.write_text(render_corpus_markdown(summary), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def render_corpus_markdown(summary: Mapping[str, Any]) -> str:
    audit = summary.get("audit_summary") if isinstance(summary.get("audit_summary"), Mapping) else {}
    funnel = audit.get("pre_admission_funnel", {}) if isinstance(audit, Mapping) else {}
    pathway = audit.get("hard_evidence_pathway_counts", {}) if isinstance(audit, Mapping) else {}
    strong = audit.get("strong_risk_composition", {}) if isinstance(audit, Mapping) else {}
    starvation = audit.get("hard_evidence_starvation", {}) if isinstance(audit, Mapping) else {}
    provenance_split = audit.get("strong_risk_exact_provenance_by_target_status", {}) if isinstance(audit, Mapping) else {}
    lines = [
        "# Post-v2 Validation Corpus",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Corpus: {summary.get('corpus_name', '')}",
        f"- Final classification: {summary.get('final_classification', '')}",
        f"- Base model classification: {summary.get('base_model_classification', '')}",
        f"- Terminal state: {summary.get('terminalState', '')}",
        f"- Validation policy: {summary.get('validationPolicy', '')}",
        f"- Network probe status: {summary.get('networkProbeStatus', '')}",
        f"- Network probe output: {summary.get('networkProbeOutputPath', '')}",
        f"- Full network attempted: {summary.get('fullNetworkAttempted', False)}",
        f"- Cache-only fallback used: {summary.get('cacheOnlyFallbackUsed', False)}",
        f"- Fallback reason: {summary.get('fallbackReason', '')}",
        f"- Stopped early reason: {summary.get('stoppedEarlyReason', '')}",
        f"- Fallback source summary: {summary.get('fallbackSourceSummary', {})}",
        f"- Interpretable model-evidence targets: {summary.get('interpretableModelEvidenceTargets', 0)}",
        f"- Recommended next task: {summary.get('recommended_next_task', '')}",
        f"- Total targets: {summary.get('total_targets', 0)}",
        f"- Completed/skipped/aborted targets: {summary.get('completed_targets', 0)}/{summary.get('skipped_targets', 0)}/{summary.get('aborted_targets', 0)}",
        f"- Funding-enabled/cache-only/funding-blocked targets: {summary.get('funding_enabled_targets', 0)}/{summary.get('cache_only_targets', 0)}/{summary.get('funding_blocked_targets', 0)}",
        f"- Timeout/RPC-stall targets: {summary.get('timeout_targets', 0)}/{summary.get('rpc_stall_targets', 0)}",
        f"- Completed target tags: {summary.get('completed_target_tag_counts', {})}",
        "",
        "## Audit Summary",
        f"- Rows inspected: {audit.get('total_rows_inspected', 0)}",
        f"- Event rows: {audit.get('event_forensic_rows_inspected', 0)}",
        f"- Archive rows: {audit.get('archive_rows_inspected', 0)}",
        f"- Visible rows: {audit.get('rawVisibleRows', audit.get('visible_rows', 0))} raw / {audit.get('uniqueVisibleRows', 'unknown')} unique (dedupe ratio {audit.get('visibleDedupeRatio', 'unknown')})",
        f"- Strong Risk rows: {audit.get('rawStrongRiskRows', audit.get('strong_risk_rows', 0))} raw / {audit.get('uniqueStrongRiskRows', 'unknown')} unique (dedupe ratio {audit.get('strongRiskDedupeRatio', 'unknown')})",
        f"- Hard Evidence Review rows: {audit.get('rawHardEvidenceReviewRows', audit.get('hard_evidence_review_rows', 0))} raw / {audit.get('uniqueHardEvidenceReviewRows', 'unknown')} unique (dedupe ratio {audit.get('hardEvidenceReviewDedupeRatio', 'unknown')})",
        f"- Strong Risk score-only rows: {strong.get('strong_risk_score_only_rows', 0)}",
        f"- Strong Risk timing-only rows: {strong.get('strong_risk_timing_only_rows', 0)}",
        f"- Strong Risk suppressor-conflict rows: {strong.get('strong_risk_suppressor_conflict_rows', 0)}",
        f"- Strong Risk no-opening-exposure rows: {strong.get('strong_risk_rows_opening_exposure_not_confirmed', 0)}",
        f"- Strong Risk no-gate-evidence rows: {strong.get('strong_risk_rows_with_no_gate_evidence_sources', 0)}",
        f"- Strong Risk hardEvidenceSources=none rows: {strong.get('strong_risk_rows_with_no_hard_evidence_sources', 0)}",
        f"- Strong Risk exact gate missing rows: {strong.get('strong_risk_new_format_missing_exact_gate_branch_rows', 0)}",
        f"- Strong Risk gate leakage candidates: {strong.get('strong_risk_gate_leakage_candidate_rows', 0)}",
        f"- Live-detectable/retrospective-only Strong Risk rows: {strong.get('strong_risk_live_detectable_rows', 0)}/{strong.get('strong_risk_retrospective_only_rows_exact', strong.get('strong_risk_retrospective_only_rows', 0))}",
        f"- Normal candidates: {audit.get('normal_candidate_rows', 0)}",
        f"- Pre-admitted candidates: {audit.get('pre_admitted_candidate_rows', 0)}",
        f"- Funding trace attempted/succeeded/failed/skipped: {funnel.get('funding_trace_attempted_count', 0)}/{funnel.get('funding_trace_succeeded_count', 0)}/{funnel.get('funding_trace_failed_count', 0)}/{funnel.get('funding_trace_skipped_count', 0)}",
        f"- Funding coverage: {funnel.get('funding_trace_coverage_ratio', 0)}",
        f"- Persistent cache hits/misses/writes: {funnel.get('funding_trace_persistent_cache_hit_count', 0)}/{funnel.get('funding_trace_persistent_cache_miss_count', 0)}/{funnel.get('funding_trace_persistent_cache_write_count', 0)}",
        f"- Resolver available/unavailable bundles: {funnel.get('funding_resolver_availability', {})}",
        f"- Top duplicate targets: {audit.get('topDuplicateTargets', {})}",
        "",
        "## Target Statuses",
    ]
    for status, count in (summary.get("target_status_counts") or {}).items():
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Hard-Evidence Pathways"])
    if isinstance(pathway, Mapping) and pathway:
        for key, count in pathway.items():
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Strong Risk Composition"])
    if isinstance(strong, Mapping) and strong:
        gate_dist = strong.get("strong_risk_rows_by_gate_type")
        class_dist = strong.get("strong_risk_rows_by_composition_class")
        if isinstance(gate_dist, Mapping):
            lines.append(f"- gate_type_distribution: {dict(gate_dist)}")
        if isinstance(class_dist, Mapping):
            lines.append(f"- composition_class_distribution: {dict(class_dist)}")
        exact_dist = strong.get("strong_risk_rows_by_exact_gate_branch")
        if isinstance(exact_dist, Mapping):
            lines.append(f"- exact_gate_branch_distribution: {dict(exact_dist)}")
        issue_dist = strong.get("strong_risk_rows_by_source_attribution_issue")
        if isinstance(issue_dist, Mapping):
            lines.append(f"- source_attribution_issue_distribution: {dict(issue_dist)}")
        for key, value in strong.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")
    lines.extend(["", "## Exact Provenance By Target Status"])
    if isinstance(provenance_split, Mapping) and provenance_split:
        for status, values in provenance_split.items():
            lines.append(f"### {status}")
            if isinstance(values, Mapping):
                for key, value in values.items():
                    lines.append(f"- {key}: {value}")
            else:
                lines.append(f"- {values}")
    else:
        lines.append("- none")
    lines.extend(["", "## Starvation"])
    if isinstance(starvation, Mapping) and starvation:
        for key, value in starvation.items():
            if key.startswith("examples_"):
                continue
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")
    lines.extend(["", "## Audit Warnings"])
    warnings = audit.get("warnings", []) if isinstance(audit, Mapping) else []
    if warnings:
        for warning in warnings:
            if isinstance(warning, Mapping):
                lines.append(f"- {warning.get('code')}: {warning.get('count', 0)}")
    else:
        lines.append("- none")
    lines.extend(["", "## Output Paths"])
    paths = summary.get("audit_output_paths") or {}
    if isinstance(paths, Mapping) and paths:
        for key, value in paths.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def _print_summary(summary: Mapping[str, Any], output_paths: Mapping[str, str]) -> None:
    audit = summary.get("audit_summary") if isinstance(summary.get("audit_summary"), Mapping) else {}
    funnel = audit.get("pre_admission_funnel", {}) if isinstance(audit, Mapping) else {}
    print(f"Corpus classification: {summary.get('final_classification', '')}")
    print(f"Validation policy: {summary.get('validationPolicy', '')}")
    print(f"Network probe status: {summary.get('networkProbeStatus', '')}")
    print(f"Full network attempted: {summary.get('fullNetworkAttempted', False)}")
    print(f"Cache-only fallback used: {summary.get('cacheOnlyFallbackUsed', False)}")
    if summary.get("fallbackReason"):
        print(f"Fallback reason: {summary.get('fallbackReason', '')}")
    if summary.get("stoppedEarlyReason"):
        print(f"Stopped early reason: {summary.get('stoppedEarlyReason', '')}")
    print(f"Recommended next task: {summary.get('recommended_next_task', '')}")
    print(f"Corpus outputs: {output_paths.get('markdown_path', '')} {output_paths.get('json_path', '')}")
    print(f"Targets completed/skipped/aborted: {summary.get('completed_targets', 0)}/{summary.get('skipped_targets', 0)}/{summary.get('aborted_targets', 0)}")
    print(f"Funding-enabled/cache-only/funding-blocked targets: {summary.get('funding_enabled_targets', 0)}/{summary.get('cache_only_targets', 0)}/{summary.get('funding_blocked_targets', 0)}")
    print(f"Rows inspected: {audit.get('total_rows_inspected', 0)}")
    print(
        "Visible rows: "
        f"{audit.get('rawVisibleRows', audit.get('visible_rows', 0))} raw / "
        f"{audit.get('uniqueVisibleRows', 'unknown')} unique "
        f"(dedupe ratio {audit.get('visibleDedupeRatio', 'unknown')})"
    )
    print(
        "Strong Risk rows: "
        f"{audit.get('rawStrongRiskRows', audit.get('strong_risk_rows', 0))} raw / "
        f"{audit.get('uniqueStrongRiskRows', 'unknown')} unique "
        f"(dedupe ratio {audit.get('strongRiskDedupeRatio', 'unknown')})"
    )
    print(
        "Hard Evidence Review rows: "
        f"{audit.get('rawHardEvidenceReviewRows', audit.get('hard_evidence_review_rows', 0))} raw / "
        f"{audit.get('uniqueHardEvidenceReviewRows', 'unknown')} unique "
        f"(dedupe ratio {audit.get('hardEvidenceReviewDedupeRatio', 'unknown')})"
    )
    strong = audit.get("strong_risk_composition", {}) if isinstance(audit, Mapping) else {}
    if isinstance(strong, Mapping):
        print(f"Strong Risk gate types: {strong.get('strong_risk_rows_by_gate_type', {})}")
        print(f"Strong Risk exact gate branches: {strong.get('strong_risk_rows_by_exact_gate_branch', {})}")
        print(f"Strong Risk composition classes: {strong.get('strong_risk_rows_by_composition_class', {})}")
    split = audit.get("strong_risk_exact_provenance_by_target_status", {}) if isinstance(audit, Mapping) else {}
    if isinstance(split, Mapping) and split:
        print(f"Strong Risk exact provenance by target status: {split}")
    print(
        "Funding trace attempted/succeeded/failed/skipped: "
        f"{funnel.get('funding_trace_attempted_count', 0)}/"
        f"{funnel.get('funding_trace_succeeded_count', 0)}/"
        f"{funnel.get('funding_trace_failed_count', 0)}/"
        f"{funnel.get('funding_trace_skipped_count', 0)}"
    )
    print(f"Audit warnings: {len(audit.get('warnings', []) if isinstance(audit, Mapping) else [])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded post-v2 InsPoly validation corpus targets.")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--max-targets", type=int, default=None)
    parser.add_argument(
        "--smoke-targets",
        type=int,
        default=None,
        help="Bounded reliability smoke size; used as --max-targets when --max-targets is omitted.",
    )
    parser.add_argument("--cache-only", action="store_true", help="Use persistent cache first and block network funding misses.")
    parser.add_argument("--network-funding", action="store_true", help="Allow network funding traces in validation mode.")
    parser.add_argument("--network-probe", action="store_true", help="Run a small network-funded probe corpus before full validation.")
    parser.add_argument("--auto-policy", action="store_true", help="Run healthcheck, network probe, and automatic cache-only fallback policy.")
    parser.add_argument("--skip-rerun", action="store_true", help="Audit saved-output targets only; skip live reruns.")
    parser.add_argument("--audit-only", action="store_true", help="Do not rerun targets; audit saved-output targets only.")
    parser.add_argument("--timeout-seconds", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    if args.smoke_targets is not None:
        if args.smoke_targets < 1:
            parser.error("--smoke-targets must be at least 1")
        if args.max_targets is None:
            args.max_targets = args.smoke_targets

    ensure_validation_runtime_defaults()
    load_runtime_env(REPO_ROOT)
    allow_network = bool(args.network_funding or not args.cache_only)
    if args.cache_only:
        allow_network = False
    settings = validation_settings_from_env(
        timeout_seconds=args.timeout_seconds,
        output_dir=args.output_dir,
        allow_network_funding=allow_network,
    )
    corpus = load_corpus_config(args.corpus)
    fallback_corpus: dict[str, Any] | None = None
    if args.smoke_targets is not None:
        fallback_corpus = select_smoke_corpus(corpus, args.smoke_targets) if args.auto_policy else None
        corpus = select_smoke_corpus(
            corpus,
            args.smoke_targets,
            prewarm_summary=_latest_prewarm_summary(args.output_dir) if args.auto_policy else None,
        )
    elif (
        args.max_targets is not None
        and args.max_targets <= 12
        and (args.auto_policy or args.cache_only)
    ):
        fallback_corpus = select_smoke_corpus(corpus, args.max_targets) if args.auto_policy else None
        corpus = select_smoke_corpus(
            corpus,
            args.max_targets,
            prewarm_summary=_latest_prewarm_summary(args.output_dir) if args.auto_policy else None,
        )
    if args.network_probe:
        probe_settings = replace(settings, allow_network_funding=True)
        summary, output_paths, _status = run_network_probe(
            corpus,
            max_targets=args.max_targets,
            settings=probe_settings,
            terminal_artifact_label="network_probe",
        )
    elif args.auto_policy:
        summary, output_paths, policy_paths = run_auto_policy(
            corpus,
            max_targets=args.max_targets,
            skip_rerun=args.skip_rerun,
            audit_only=args.audit_only,
            settings=settings,
            fallback_corpus=fallback_corpus,
        )
        if policy_paths:
            summary["policyOutputPaths"] = dict(policy_paths)
            # Rewrite with policy path references included.
            output_paths = write_corpus_outputs(summary, args.output_dir)
    else:
        summary = run_corpus(
            corpus,
            max_targets=args.max_targets,
            skip_rerun=args.skip_rerun,
            audit_only=args.audit_only,
            settings=settings,
            validation_policy="cache_only" if not settings.allow_network_funding else "network_funding",
            full_network_attempted=settings.allow_network_funding,
            terminal_artifact_label="cache_only" if not settings.allow_network_funding else "network_funding",
        )
        output_paths = write_corpus_outputs(summary, args.output_dir)
    _print_summary(summary, output_paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
