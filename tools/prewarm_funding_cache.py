from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import signal
import sys
import time
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import load_runtime_env, runtime_env_int
from app.funding_context import FundingResolver
from tools.run_validation_corpus import DEFAULT_CORPUS_PATH, load_corpus_config

DEFAULT_OUTPUT_DIR = Path("validation_corpus_outputs")
DEFAULT_MAX_TRACES_PER_TARGET = 4
DEFAULT_MAX_TOTAL_TRACES = 24
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_TRACE_TIMEOUT_SECONDS = 20
DEFAULT_MAX_TRACE_TIMEOUTS = 3
TARGET_ROW_FILES = (
    "suspicious_trades.csv",
    "wallet_context.csv",
    "suspicious_wallets.csv",
    "raw_event_bundle/source_trades.json",
    "raw_event_bundle/trades.json",
    "event_analysis.json",
)
WALLET_KEYS = (
    "wallet",
    "walletId",
    "wallet_id",
    "traderWallet",
    "trader_wallet",
    "proxyWallet",
    "proxy_wallet",
)
TIMESTAMP_KEYS = (
    "timestamp",
    "tradeTimestamp",
    "trade_timestamp",
    "createdAt",
    "created_at",
    "time",
    "tradeTime",
    "trade_time",
)


@dataclass(frozen=True)
class FundingWindow:
    wallet: str
    as_of: datetime
    source_path: str
    source_row: str
    notional: float = 0.0

    @property
    def cache_bucket(self) -> str:
        return self.as_of.astimezone(UTC).strftime("%Y%m%d%H")


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


def target_family(target: Mapping[str, Any], tags: Iterable[str] | None = None) -> str:
    explicit = str(target.get("targetFamily") or "").strip()
    if explicit:
        return explicit
    tag_set = {str(tag) for tag in (tags if tags is not None else normalize_target_tags(target))}
    mode = str(target.get("mode") or "")
    if "gta_or_known_cluster" in tag_set:
        return "gta_or_known_cluster"
    if "sports_crypto" in tag_set:
        return "sports_crypto"
    if mode == "archive":
        return "archive_politics_world" if "politics_world" in tag_set else "archive"
    if "politics_world" in tag_set:
        return "politics_world_event_forensic"
    if "funding_candidate" in tag_set:
        return "funding_candidate_other"
    return "non_gta_other" if "non_gta" in tag_set else "unknown"


def _target_paths(target: Mapping[str, Any], *, repo_root: Path = REPO_ROOT) -> list[Path]:
    values: list[Any] = []
    for key in ("priorOutputPath", "prior_output_path", "inputValue"):
        value = target.get(key)
        if value:
            values.append(value)
    for key in ("priorOutputPaths", "prior_output_paths", "savedOutputPaths", "saved_output_paths"):
        value = target.get(key)
        if isinstance(value, list):
            values.extend(value)
    paths: list[Path] = []
    seen: set[str] = set()
    for value in values:
        path = Path(str(value))
        if not path.is_absolute():
            path = repo_root / path
        if not path.exists():
            continue
        key = str(path.resolve())
        if key not in seen:
            paths.append(path)
            seen.add(key)
    return paths


def discover_funding_windows(
    target: Mapping[str, Any],
    *,
    max_windows: int = DEFAULT_MAX_TRACES_PER_TARGET,
    repo_root: Path = REPO_ROOT,
) -> list[FundingWindow]:
    windows: list[FundingWindow] = []
    seen: set[tuple[str, str]] = set()
    for path in _target_paths(target, repo_root=repo_root):
        for window in _iter_windows_from_path(path):
            key = (window.wallet.lower(), window.cache_bucket)
            if key in seen:
                continue
            seen.add(key)
            windows.append(window)
    windows.sort(key=lambda item: item.notional, reverse=True)
    return windows[: max(0, max_windows)]


def _iter_windows_from_path(path: Path) -> Iterable[FundingWindow]:
    if path.is_dir():
        for name in TARGET_ROW_FILES:
            child = path / name
            if child.exists():
                yield from _iter_windows_from_path(child)
        return
    suffix = path.suffix.lower()
    if suffix == ".csv":
        yield from _iter_csv_windows(path)
    elif suffix == ".json":
        yield from _iter_json_windows(path)


def _iter_csv_windows(path: Path) -> Iterable[FundingWindow]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle), start=1):
                window = _window_from_row(row, source_path=path, source_row=str(index))
                if window is not None:
                    yield window
    except (OSError, UnicodeDecodeError, csv.Error):
        return


def _iter_json_windows(path: Path) -> Iterable[FundingWindow]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return
    for index, row in enumerate(_iter_json_records(payload), start=1):
        window = _window_from_row(row, source_path=path, source_row=str(index))
        if window is not None:
            yield window


def _iter_json_records(payload: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_json_records(item)
        return
    if not isinstance(payload, Mapping):
        return
    if any(key in payload for key in WALLET_KEYS) and any(key in payload for key in TIMESTAMP_KEYS):
        yield payload
    for value in payload.values():
        if isinstance(value, (list, Mapping)):
            yield from _iter_json_records(value)


def _window_from_row(row: Mapping[str, Any], *, source_path: Path, source_row: str) -> FundingWindow | None:
    wallet = _first_text(row, WALLET_KEYS).lower()
    if not _looks_like_wallet(wallet):
        return None
    timestamp = _parse_timestamp(_first_text(row, TIMESTAMP_KEYS))
    if timestamp is None:
        return None
    return FundingWindow(
        wallet=wallet,
        as_of=timestamp,
        source_path=str(source_path),
        source_row=source_row,
        notional=_float_or_zero(_first_text(row, ("notional", "positionSize", "position_size", "size"))),
    )


def _first_text(row: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _looks_like_wallet(value: str) -> bool:
    return value.startswith("0x") and len(value) >= 10


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromtimestamp(float(text), UTC)
        except (TypeError, ValueError, OSError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _float_or_zero(value: str) -> float:
    try:
        return float(str(value).replace(",", "").replace("$", "").strip() or 0)
    except ValueError:
        return 0.0


def _prewarm_target_sort_key(target: Mapping[str, Any]) -> tuple[int, float, int, str]:
    tags = {str(tag) for tag in target.get("tags") or []}
    funding_candidate_penalty = 0 if "funding_candidate" in tags else 1
    hours = _archive_window_hours(target)
    if hours is not None:
        runtime_cost = hours
    elif str(target.get("mode") or "") == "event_forensic":
        runtime_cost = 48.0
    else:
        runtime_cost = 999999.0
    high_volume_penalty = 1 if "high_volume" in tags else 0
    return (funding_candidate_penalty, runtime_cost, high_volume_penalty, str(target.get("label") or ""))


def _family_balanced_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    families: dict[str, list[dict[str, Any]]] = {}
    for target in targets:
        tags = normalize_target_tags(target)
        family = target_family(target, tags)
        families.setdefault(family, []).append(target)
    for family_targets in families.values():
        family_targets.sort(key=_prewarm_target_sort_key)
    family_order = sorted(
        families,
        key=lambda family: (
            _prewarm_target_sort_key(families[family][0]) if families[family] else (9, 999999.0, 9, family),
            family,
        ),
    )
    balanced: list[dict[str, Any]] = []
    index = 0
    while True:
        added = False
        for family in family_order:
            family_targets = families[family]
            if index < len(family_targets):
                balanced.append(family_targets[index])
                added = True
        if not added:
            break
        index += 1
    return balanced


def _archive_window_hours(target: Mapping[str, Any]) -> float | None:
    if str(target.get("inputType") or "") != "archive_window":
        return None
    value = str(target.get("inputValue") or "")
    if "/" not in value:
        return None
    start_raw, end_raw = value.split("/", 1)
    start = _parse_timestamp(start_raw)
    end = _parse_timestamp(end_raw)
    if start is None or end is None:
        return None
    return max((end - start).total_seconds() / 3600, 0.0)


def _health_dict(resolver: Any) -> dict[str, Any]:
    health = resolver.health()
    if hasattr(health, "to_dict"):
        return dict(health.to_dict())
    if isinstance(health, Mapping):
        return dict(health)
    return {}


def _delta(after: Mapping[str, Any], before: Mapping[str, Any], key: str) -> int:
    return int(after.get(key) or 0) - int(before.get(key) or 0)


def run_prewarm(
    corpus: Mapping[str, Any],
    *,
    max_targets: int | None,
    max_traces_per_target: int,
    max_total_traces: int,
    timeout_seconds: int,
    trace_timeout_seconds: int = DEFAULT_TRACE_TIMEOUT_SECONDS,
    max_trace_timeouts: int = DEFAULT_MAX_TRACE_TIMEOUTS,
    resolver_factory: Any = FundingResolver,
    repo_root: Path = REPO_ROOT,
    now_func: Any = time.monotonic,
) -> dict[str, Any]:
    targets = [dict(target) for target in corpus.get("targets", []) if isinstance(target, Mapping)]
    targets = _family_balanced_targets(targets)
    if max_targets is not None:
        targets = targets[: max(0, max_targets)]
    use_trace_workers = resolver_factory is FundingResolver
    resolver = None if use_trace_workers else resolver_factory()
    started = now_func()
    totals: Counter[str] = Counter()
    health_totals: Counter[str] = Counter()
    target_results: list[dict[str, Any]] = []
    total_trace_windows = 0
    total_trace_timeouts = 0
    max_trace_timeouts = max(1, int(max_trace_timeouts))
    stop_reason = ""
    family_totals: dict[str, Counter[str]] = {}

    def family_counter(family: str) -> Counter[str]:
        return family_totals.setdefault(family, Counter())

    for target in targets:
        label = str(target.get("label") or "")
        tags = normalize_target_tags(target)
        family = target_family(target, tags)
        family_counter(family)["targets"] += 1
        if "funding_candidate" in tags:
            totals["funding_candidate_targets"] += 1
            family_counter(family)["fundingCandidateTargets"] += 1
        if stop_reason:
            target_results.append(
                {
                    "label": label,
                    "status": "skipped_global_limit",
                    "tags": tags,
                    "targetFamily": family,
                    "reason": stop_reason,
                    "windowsFound": 0,
                    "windowsAttempted": 0,
                }
            )
            totals["skipped_targets"] += 1
            family_counter(family)["skipped"] += 1
            continue
        windows = discover_funding_windows(
            target,
            max_windows=max_traces_per_target,
            repo_root=repo_root,
        )
        family_counter(family)["windowsFound"] += len(windows)
        if not windows:
            target_results.append(
                {
                    "label": label,
                    "status": "skipped_no_metadata",
                    "tags": tags,
                    "targetFamily": family,
                    "windowsFound": 0,
                    "windowsAttempted": 0,
                }
            )
            totals["skipped_targets"] += 1
            family_counter(family)["skipped"] += 1
            continue

        attempted = 0
        failures = 0
        cache_hits = 0
        cache_misses = 0
        target_health: Counter[str] = Counter()
        target_trace_outcomes: Counter[str] = Counter()
        last_error = ""
        target_stop_reason = ""
        target_trace_timeouts = 0
        functional_status = ""
        resolver_available: Any = ""
        for window in windows:
            if now_func() - started > timeout_seconds:
                stop_reason = "timeout"
                target_stop_reason = stop_reason
                break
            if total_trace_windows >= max_total_traces:
                stop_reason = "max_total_traces"
                target_stop_reason = stop_reason
                break
            attempted += 1
            total_trace_windows += 1
            if use_trace_workers:
                outcome = _analyze_window_in_process(window, timeout_seconds=trace_timeout_seconds)
                if outcome.get("timed_out"):
                    failures += 1
                    target_trace_timeouts += 1
                    total_trace_timeouts += 1
                    last_error = "funding_trace_timeout"
                    target_stop_reason = "trace_timeout"
                    if total_trace_timeouts >= max_trace_timeouts:
                        stop_reason = "trace_timeout"
                    break
                context_info = outcome.get("context") if isinstance(outcome.get("context"), Mapping) else {}
                health_info = outcome.get("health") if isinstance(outcome.get("health"), Mapping) else {}
            else:
                assert resolver is not None
                try:
                    context = _call_with_timeout(
                        lambda: resolver.analyze(window.wallet, window.as_of),
                        timeout_seconds=trace_timeout_seconds,
                    )
                except TimeoutError:
                    failures += 1
                    target_trace_timeouts += 1
                    total_trace_timeouts += 1
                    last_error = "funding_trace_timeout"
                    target_stop_reason = "trace_timeout"
                    if total_trace_timeouts >= max_trace_timeouts:
                        stop_reason = "trace_timeout"
                    break
                context_info = {
                    "funding_trace_from_persistent_cache": bool(
                        getattr(context, "funding_trace_from_persistent_cache", False)
                    ),
                    "funding_trace_cache_status": str(getattr(context, "funding_trace_cache_status", "") or ""),
                    "funding_found": bool(getattr(context, "funding_found", False)),
                    "funding_evidence_grade": str(getattr(context, "funding_evidence_grade", "") or ""),
                    "error": getattr(context, "error", None),
                }
                health_info = _health_dict(resolver)
            _accumulate_health(target_health, health_info)
            outcome_status = _trace_context_status(context_info)
            target_trace_outcomes[outcome_status] += 1
            functional_status = str(health_info.get("fundingResolverFunctionalStatus") or functional_status)
            resolver_available = health_info.get("fundingResolverAvailable", resolver_available)
            if context_info.get("funding_trace_from_persistent_cache"):
                cache_hits += 1
            else:
                cache_misses += 1
            if context_info.get("error"):
                failures += 1
                last_error = str(context_info.get("error") or "")
                if "funding_trace_timeout" in last_error:
                    target_trace_timeouts += 1
                    total_trace_timeouts += 1
                    target_stop_reason = "trace_timeout"
                    if total_trace_timeouts >= max_trace_timeouts:
                        stop_reason = "trace_timeout"
                    break
        health_totals.update(target_health)
        status = "completed"
        if failures and failures >= attempted:
            status = "funding_blocked"
            totals["funding_blocked_targets"] += 1
            family_counter(family)["fundingBlocked"] += 1
        else:
            totals["completed_targets"] += 1
            family_counter(family)["completed"] += 1
        result = {
            "label": label,
            "status": status,
            "tags": tags,
            "targetFamily": family,
            "windowsFound": len(windows),
            "windowsAttempted": attempted,
            "cacheHitsObserved": cache_hits,
            "cacheMissesObserved": cache_misses,
            "failuresObserved": failures,
            "traceTimeoutsObserved": target_trace_timeouts,
            "traceAttemptedDelta": target_health["fundingTraceAttemptedCount"],
            "traceSucceededDelta": target_health["fundingTraceSucceededCount"],
            "traceFailedDelta": target_health["fundingTraceFailedCount"],
            "traceSkippedDelta": target_health["fundingTraceSkippedCount"],
            "persistentCacheHitDelta": target_health["fundingTracePersistentCacheHitCount"],
            "persistentCacheMissDelta": target_health["fundingTracePersistentCacheMissCount"],
            "persistentCacheWriteDelta": target_health["fundingTracePersistentCacheWriteCount"],
            "traceOutcomeStatusCounts": dict(sorted(target_trace_outcomes.items())),
            "fundingResolverAvailable": resolver_available,
            "fundingResolverFunctionalStatus": functional_status,
            "lastError": last_error,
            "targetStopReason": target_stop_reason,
        }
        target_results.append(result)
        totals["wallet_time_windows_found"] += len(windows)
        totals["wallet_time_windows_attempted"] += attempted
        totals["cache_hits"] += cache_hits
        totals["cache_misses"] += cache_misses
        totals["failures"] += failures
        totals["trace_timeouts"] += target_trace_timeouts
        for status_name, status_count in target_trace_outcomes.items():
            totals[f"traceOutcome_{status_name}"] += status_count
        family_counter(family)["windowsAttempted"] += attempted
        family_counter(family)["cacheHits"] += cache_hits
        family_counter(family)["cacheMisses"] += cache_misses
        family_counter(family)["failures"] += failures
        family_counter(family)["traceTimeouts"] += target_trace_timeouts
        for status_name, status_count in target_trace_outcomes.items():
            family_counter(family)[f"traceOutcome_{status_name}"] += status_count

    targets_left = sum(
        1
        for result in target_results
        if str(result.get("status") or "") != "completed"
        or int(result.get("windowsAttempted") or 0) < int(result.get("windowsFound") or 0)
    )
    family_left: Counter[str] = Counter()
    for result in target_results:
        family = str(result.get("targetFamily") or "unknown")
        if str(result.get("status") or "") != "completed" or int(result.get("windowsAttempted") or 0) < int(result.get("windowsFound") or 0):
            family_left[family] += 1
    final_health = _summary_health_dict(health_totals)
    prewarm_by_family = {}
    for family, counter in sorted(family_totals.items()):
        windows_found = int(counter.get("windowsFound") or 0)
        windows_attempted = int(counter.get("windowsAttempted") or 0)
        cache_hits = int(counter.get("cacheHits") or 0)
        cache_misses = int(counter.get("cacheMisses") or 0)
        values = Counter(counter)
        values["targetsLeftUnprewarmed"] = family_left[family]
        prewarm_by_family[family] = {
            **dict(sorted(values.items())),
            "windowCoverageRatio": round(windows_attempted / windows_found, 4) if windows_found else 0.0,
            "cacheHitRate": round(cache_hits / (cache_hits + cache_misses), 4) if cache_hits + cache_misses else 0.0,
        }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus_name": corpus.get("corpusName") or corpus.get("corpus_name") or "post_v2_validation_corpus",
        "targets_scanned": len(targets),
        "funding_candidate_targets": totals["funding_candidate_targets"],
        "completed_targets": totals["completed_targets"],
        "skipped_targets": totals["skipped_targets"],
        "funding_blocked_targets": totals["funding_blocked_targets"],
        "wallet_time_windows_found": totals["wallet_time_windows_found"],
        "wallet_time_windows_attempted": totals["wallet_time_windows_attempted"],
        "traces_requested": totals["wallet_time_windows_attempted"],
        "cache_hits_observed": totals["cache_hits"],
        "cache_misses_observed": totals["cache_misses"],
        "cache_hits": totals["cache_hits"],
        "cache_misses": totals["cache_misses"],
        "cache_writes": final_health.get("fundingTracePersistentCacheWriteCount", 0),
        "trace_outcome_status_counts": {
            key.replace("traceOutcome_", ""): value
            for key, value in sorted(totals.items())
            if key.startswith("traceOutcome_")
        },
        "failures_observed": totals["failures"],
        "trace_timeouts_observed": totals["trace_timeouts"],
        "max_trace_timeouts": max_trace_timeouts,
        "rpc_failures": final_health.get("fundingTraceFailedCount", totals["failures"]),
        "rate_limits": final_health.get("fundingTraceRateLimitedCount", 0),
        "targets_left_unprewarmed": targets_left,
        "stop_reason": stop_reason,
        "trace_timeout_seconds": trace_timeout_seconds,
        "runtime_seconds": round(max(0.0, now_func() - started), 3),
        "resolver_health": final_health,
        "prewarm_coverage_by_target_family": prewarm_by_family,
        "target_results": target_results,
    }


def _accumulate_health(counter: Counter[str], health: Mapping[str, Any]) -> None:
    for key in (
        "fundingTraceAttemptedCount",
        "fundingTraceSucceededCount",
        "fundingTraceFailedCount",
        "fundingTraceSkippedCount",
        "fundingTracePersistentCacheHitCount",
        "fundingTracePersistentCacheMissCount",
        "fundingTracePersistentCacheWriteCount",
    ):
        counter[key] += int(health.get(key) or 0)


def _trace_context_status(context: Mapping[str, Any]) -> str:
    cached_status = str(context.get("funding_trace_cache_status") or "").strip().lower()
    if cached_status in {"success", "none", "failure"}:
        return cached_status
    if context.get("error"):
        return "failure"
    if str(context.get("funding_evidence_grade") or "").strip().lower() == "unknown":
        return "failure"
    if bool(context.get("funding_found")):
        return "success"
    return "none"


def _summary_health_dict(counter: Counter[str]) -> dict[str, Any]:
    attempted = counter["fundingTraceAttemptedCount"]
    succeeded = counter["fundingTraceSucceededCount"]
    failed = counter["fundingTraceFailedCount"]
    skipped = counter["fundingTraceSkippedCount"]
    return {
        "fundingResolverFunctionalStatus": "available_for_funding_trace" if succeeded else "unknown",
        "fundingResolverAvailable": bool(succeeded),
        "fundingTraceAttemptedCount": attempted,
        "fundingTraceSucceededCount": succeeded,
        "fundingTraceFailedCount": failed,
        "fundingTraceSkippedCount": skipped,
        "fundingTracePersistentCacheEnabled": True,
        "fundingTracePersistentCacheHitCount": counter["fundingTracePersistentCacheHitCount"],
        "fundingTracePersistentCacheMissCount": counter["fundingTracePersistentCacheMissCount"],
        "fundingTracePersistentCacheWriteCount": counter["fundingTracePersistentCacheWriteCount"],
    }


def _analyze_window_in_process(window: FundingWindow, *, timeout_seconds: int) -> dict[str, Any]:
    ctx = mp.get_context("spawn")
    output: mp.Queue = ctx.Queue()
    process = ctx.Process(
        target=_analyze_window_worker,
        args=(window.wallet, window.as_of.isoformat(), str(REPO_ROOT), dict(os.environ), output),
        daemon=True,
    )
    process.start()
    process.join(timeout=max(1, timeout_seconds))
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        return {"timed_out": True, "context": {"error": "funding_trace_timeout"}, "health": {}}
    try:
        return dict(output.get_nowait())
    except queue.Empty:
        return {
            "timed_out": False,
            "context": {"error": f"worker_exit_{process.exitcode}"},
            "health": {},
        }


def _analyze_window_worker(
    wallet: str,
    as_of_iso: str,
    repo_root: str,
    env: Mapping[str, str],
    output: Any,
) -> None:
    os.chdir(repo_root)
    os.environ.update({str(key): str(value) for key, value in env.items()})
    load_runtime_env(Path(repo_root))
    resolver = FundingResolver()
    as_of = datetime.fromisoformat(as_of_iso)
    context = resolver.analyze(wallet, as_of)
    output.put(
        {
            "timed_out": False,
            "context": {
                "funding_trace_from_persistent_cache": bool(
                    getattr(context, "funding_trace_from_persistent_cache", False)
                ),
                "funding_trace_cache_status": str(getattr(context, "funding_trace_cache_status", "") or ""),
                "funding_found": bool(getattr(context, "funding_found", False)),
                "funding_evidence_grade": str(getattr(context, "funding_evidence_grade", "") or ""),
                "error": getattr(context, "error", None),
            },
            "health": _health_dict(resolver),
        }
    )


def _call_with_timeout(callback: Any, *, timeout_seconds: int) -> Any:
    if timeout_seconds <= 0 or not hasattr(signal, "SIGALRM"):
        return callback()
    previous_handler = signal.getsignal(signal.SIGALRM)

    def _raise_timeout(_signum: int, _frame: Any) -> None:
        raise TimeoutError("funding_trace_timeout")

    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return callback()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def write_outputs(summary: Mapping[str, Any], output_dir: Path, *, timestamp: str | None = None) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"funding_cache_prewarm_{stamp}.json"
    markdown_path = output_dir / f"funding_cache_prewarm_{stamp}.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(summary), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def render_markdown(summary: Mapping[str, Any]) -> str:
    health = summary.get("resolver_health") if isinstance(summary.get("resolver_health"), Mapping) else {}
    lines = [
        "# Funding Cache Prewarm",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Corpus: {summary.get('corpus_name', '')}",
        f"- Targets scanned: {summary.get('targets_scanned', 0)}",
        f"- Funding-candidate targets: {summary.get('funding_candidate_targets', 0)}",
        f"- Completed/skipped/funding-blocked targets: {summary.get('completed_targets', 0)}/{summary.get('skipped_targets', 0)}/{summary.get('funding_blocked_targets', 0)}",
        f"- Wallet/time windows found: {summary.get('wallet_time_windows_found', 0)}",
        f"- Wallet/time windows attempted: {summary.get('wallet_time_windows_attempted', 0)}",
        f"- Cache hits/misses observed: {summary.get('cache_hits_observed', 0)}/{summary.get('cache_misses_observed', 0)}",
        f"- Cache writes: {summary.get('cache_writes', 0)}",
        f"- Trace outcome statuses: {summary.get('trace_outcome_status_counts', {})}",
        f"- RPC failures/rate limits: {summary.get('rpc_failures', 0)}/{summary.get('rate_limits', 0)}",
        f"- Targets left unprewarmed: {summary.get('targets_left_unprewarmed', 0)}",
        f"- Failures observed: {summary.get('failures_observed', 0)}",
        f"- Trace timeouts observed/limit: {summary.get('trace_timeouts_observed', 0)}/{summary.get('max_trace_timeouts', 0)}",
        f"- Stop reason: {summary.get('stop_reason', '') or 'none'}",
        f"- Runtime seconds: {summary.get('runtime_seconds', 0)}",
        "",
        "## Resolver Health",
        f"- Functional status: {health.get('fundingResolverFunctionalStatus', '')}",
        f"- Available: {health.get('fundingResolverAvailable', '')}",
        f"- Trace attempted/succeeded/failed/skipped: {health.get('fundingTraceAttemptedCount', 0)}/{health.get('fundingTraceSucceededCount', 0)}/{health.get('fundingTraceFailedCount', 0)}/{health.get('fundingTraceSkippedCount', 0)}",
        f"- Persistent cache enabled/hits/misses/writes: {health.get('fundingTracePersistentCacheEnabled', '')}/{health.get('fundingTracePersistentCacheHitCount', 0)}/{health.get('fundingTracePersistentCacheMissCount', 0)}/{health.get('fundingTracePersistentCacheWriteCount', 0)}",
        "",
        "## Coverage By Target Family",
    ]
    for family, values in (summary.get("prewarm_coverage_by_target_family") or {}).items():
        if not isinstance(values, Mapping):
            continue
        lines.append(
            "- "
            f"{family}: targets={values.get('targets', 0)}, completed={values.get('completed', 0)}, "
            f"skipped={values.get('skipped', 0)}, blocked={values.get('fundingBlocked', 0)}, "
            f"left={values.get('targetsLeftUnprewarmed', 0)}, "
            f"windows={values.get('windowsAttempted', 0)}/{values.get('windowsFound', 0)}, "
            f"timeouts={values.get('traceTimeouts', 0)}, "
            f"coverage={values.get('windowCoverageRatio', 0)}, "
            f"cache={values.get('cacheHits', 0)}/{values.get('cacheMisses', 0)} "
            f"outcomes={{success:{values.get('traceOutcome_success', 0)}, "
            f"none:{values.get('traceOutcome_none', 0)}, failure:{values.get('traceOutcome_failure', 0)}}} "
            f"(hitRate={values.get('cacheHitRate', 0)})"
        )
    lines.extend([
        "",
        "## Targets",
    ])
    for target in summary.get("target_results") or []:
        if not isinstance(target, Mapping):
            continue
        lines.append(
            "- "
            f"{target.get('label', '')}: {target.get('status', '')}, "
            f"windows {target.get('windowsAttempted', 0)}/{target.get('windowsFound', 0)}, "
            f"cache {target.get('cacheHitsObserved', 0)}/{target.get('cacheMissesObserved', 0)}, "
            f"failures {target.get('failuresObserved', 0)}, "
            f"timeouts {target.get('traceTimeoutsObserved', 0)}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prewarm the InsPoly persistent funding trace cache for validation corpus targets.")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--max-targets", type=int, default=None)
    parser.add_argument("--max-traces-per-target", type=int, default=DEFAULT_MAX_TRACES_PER_TARGET)
    parser.add_argument("--max-total-traces", type=int, default=DEFAULT_MAX_TOTAL_TRACES)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--trace-timeout-seconds", type=int, default=DEFAULT_TRACE_TIMEOUT_SECONDS)
    parser.add_argument("--max-trace-timeouts", type=int, default=DEFAULT_MAX_TRACE_TIMEOUTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    load_runtime_env(REPO_ROOT)
    os.environ.setdefault("INSPOLY_VALIDATION_MODE", "1")
    os.environ.setdefault("INSPOLY_VALIDATION_CACHE_FIRST", "1")
    os.environ.setdefault("INSPOLY_VALIDATION_ALLOW_NETWORK_FUNDING", "1")
    os.environ["INSPOLY_VALIDATION_MAX_FUNDING_TRACES_PER_BUNDLE"] = str(
        max(0, args.max_total_traces)
    )
    os.environ.setdefault("INSPOLY_FUNDING_TRACE_CACHE_ENABLED", "1")
    runtime_env_int("INSPOLY_VALIDATION_MAX_FUNDING_TRACES_PER_BUNDLE", args.max_total_traces, minimum=0)
    corpus = load_corpus_config(args.corpus)
    summary = run_prewarm(
        corpus,
        max_targets=args.max_targets,
        max_traces_per_target=args.max_traces_per_target,
        max_total_traces=args.max_total_traces,
        timeout_seconds=args.timeout_seconds,
        trace_timeout_seconds=args.trace_timeout_seconds,
        max_trace_timeouts=args.max_trace_timeouts,
    )
    paths = write_outputs(summary, args.output_dir)
    print(f"Funding cache prewarm: {paths['markdown_path']} {paths['json_path']}")
    print(
        "Targets completed/skipped/funding-blocked: "
        f"{summary.get('completed_targets', 0)}/{summary.get('skipped_targets', 0)}/{summary.get('funding_blocked_targets', 0)}"
    )
    print(
        "Windows found/attempted: "
        f"{summary.get('wallet_time_windows_found', 0)}/{summary.get('wallet_time_windows_attempted', 0)}"
    )
    print(
        "Cache hits/misses/writes: "
        f"{summary.get('cache_hits_observed', 0)}/{summary.get('cache_misses_observed', 0)}/"
        f"{(summary.get('resolver_health') or {}).get('fundingTracePersistentCacheWriteCount', 0)}"
    )
    print(
        "Trace timeouts observed/limit: "
        f"{summary.get('trace_timeouts_observed', 0)}/{summary.get('max_trace_timeouts', 0)}"
    )
    print(f"Stop reason: {summary.get('stop_reason', '') or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
