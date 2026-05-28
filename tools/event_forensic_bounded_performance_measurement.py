#!/usr/bin/env python3
"""Bounded Event Forensic performance measurement helper.

The default mode is plan-only and offline. Live execution requires
``--run-live`` and writes only to a timestamped validation output directory.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import FUNDING_TRACE_MODE_DISABLED, AppConfig, load_runtime_env


REPORT_TYPE = "event_forensic_bounded_performance_measurement"
SCHEMA_VERSION = "event_forensic_bounded_performance_measurement_v2"
DEFAULT_PLAN_OUTPUT = Path("validation_outputs/event_forensic_performance_measurement_plan_20260525.json")
DEFAULT_INVENTORY = Path("validation_outputs/event_forensic_performance_inventory_20260525.json")
DEFAULT_MAX_EVENTS = 1
DEFAULT_MAX_MARKETS = 8
DEFAULT_MAX_CANDIDATE_WALLETS_PER_MARKET = 150
DEFAULT_MAX_TOTAL_TRADE_ROWS = 50_000
DEFAULT_MAX_WALL_MINUTES = 30
SECRET_ENV_KEYS = (
    "OPENAI_API_KEY",
    "POLYGON_RPC_URL",
    "POLYGON_RPC_URLS",
    "INSPOLY_POLYGON_RPC_URLS",
    "INSPOLY_POLYGON_RPC_URL",
    "CLOB_API_KEY",
    "CLOB_SECRET",
    "CLOB_PASSPHRASE",
    "PRIVATE_KEY",
)
SAFE_ENV_KEYS = (
    "INSPOLY_FUNDING_TRACE_MODE",
    "INSPOLY_DISABLE_LIVE_FUNDING_TRACES",
    "INSPOLY_VALIDATION_MODE",
    "INSPOLY_VALIDATION_ALLOW_NETWORK_FUNDING",
)


@dataclass(frozen=True, slots=True)
class MeasurementBounds:
    max_events: int = DEFAULT_MAX_EVENTS
    max_markets: int = DEFAULT_MAX_MARKETS
    max_candidate_wallets_per_market: int = DEFAULT_MAX_CANDIDATE_WALLETS_PER_MARKET
    max_total_trade_rows: int = DEFAULT_MAX_TOTAL_TRADE_ROWS
    max_wall_minutes: int = DEFAULT_MAX_WALL_MINUTES

    @property
    def max_wall_seconds(self) -> int:
        return self.max_wall_minutes * 60

    def to_dict(self) -> dict[str, int]:
        return {
            "maxEvents": self.max_events,
            "maxMarkets": self.max_markets,
            "maxCandidateWalletsPerMarket": self.max_candidate_wallets_per_market,
            "maxTotalTradeRows": self.max_total_trade_rows,
            "maxWallMinutes": self.max_wall_minutes,
            "maxWallSeconds": self.max_wall_seconds,
        }


def default_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def build_measurement_plan(
    *,
    event_slug: str = "",
    market_slug: str = "",
    max_events: int = DEFAULT_MAX_EVENTS,
    max_markets: int = DEFAULT_MAX_MARKETS,
    max_candidate_wallets_per_market: int = DEFAULT_MAX_CANDIDATE_WALLETS_PER_MARKET,
    max_total_trade_rows: int = DEFAULT_MAX_TOTAL_TRADE_ROWS,
    max_wall_minutes: int = DEFAULT_MAX_WALL_MINUTES,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    bounds = MeasurementBounds(
        max_events=max_events,
        max_markets=max_markets,
        max_candidate_wallets_per_market=max_candidate_wallets_per_market,
        max_total_trade_rows=max_total_trade_rows,
        max_wall_minutes=max_wall_minutes,
    )
    env_status = runtime_env_status(env=env)
    violations = bound_violations(bounds)
    gate = _plan_gate(violations, env_status, event_slug, market_slug)
    return {
        "reportType": f"{REPORT_TYPE}_plan",
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "measurementExecuted": False,
        "gateDecision": gate,
        "summary": {
            "measurementExecuted": False,
            "rpcConfigured": bool(env_status.get("rpcConfigured")),
            "boundViolationCount": len(violations),
            **bounds.to_dict(),
        },
        "target": {
            "eventSlug": event_slug,
            "marketSlug": market_slug,
            "selectionSource": "operator_supplied_or_existing_saved_report",
        },
        "bounds": bounds.to_dict(),
        "boundViolations": violations,
        "envStatus": env_status,
        "nextAction": _plan_next_action(gate),
        "forbiddenActions": _forbidden_actions(),
    }


def runtime_env_status(*, root: Path = ROOT, env: Mapping[str, str] | None = None) -> dict[str, object]:
    if env is None:
        loaded = load_runtime_env(root)
        env_view = os.environ
    else:
        loaded = {}
        env_view = env
    keys = sorted(set(SAFE_ENV_KEYS).union(SECRET_ENV_KEYS).union(loaded.keys()))
    configured = {key: bool(str(env_view.get(key) or "").strip()) for key in keys}
    return {
        "runtimeEnvFilePresent": (root / ".inspoly_runtime.env").exists() if env is None else False,
        "loadedRuntimeEnvKeys": sorted(loaded.keys()),
        "configuredEnvKeys": configured,
        "rpcConfigured": any(
            configured.get(key, False)
            for key in (
                "POLYGON_RPC_URL",
                "POLYGON_RPC_URLS",
                "INSPOLY_POLYGON_RPC_URLS",
                "INSPOLY_POLYGON_RPC_URL",
            )
        ),
        "clobAuthConfiguredButUnused": any(
            configured.get(key, False)
            for key in ("CLOB_API_KEY", "CLOB_SECRET", "CLOB_PASSPHRASE", "PRIVATE_KEY")
        ),
        "secretValuesPrinted": False,
        "secretsPrinted": False,
    }


def bound_violations(bounds: MeasurementBounds) -> list[str]:
    violations: list[str] = []
    if bounds.max_events > DEFAULT_MAX_EVENTS:
        violations.append("max_events_exceeds_campaign_bound")
    if bounds.max_markets > DEFAULT_MAX_MARKETS:
        violations.append("max_markets_exceeds_campaign_bound")
    if bounds.max_candidate_wallets_per_market > DEFAULT_MAX_CANDIDATE_WALLETS_PER_MARKET:
        violations.append("max_candidate_wallets_per_market_exceeds_campaign_bound")
    if bounds.max_total_trade_rows > DEFAULT_MAX_TOTAL_TRADE_ROWS:
        violations.append("max_total_trade_rows_exceeds_campaign_bound")
    if bounds.max_wall_minutes > DEFAULT_MAX_WALL_MINUTES:
        violations.append("max_wall_time_exceeds_campaign_bound")
    return violations


def select_bounded_target(
    *,
    root: str | Path = ROOT,
    inventory_path: str | Path = DEFAULT_INVENTORY,
    bounds: MeasurementBounds = MeasurementBounds(),
    explicit_event_slug: str = "",
    explicit_market_slug: str = "",
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    rows = _load_inventory_rows(root=root, inventory_path=inventory_path)
    eligible: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    for row in rows:
        candidate = _target_candidate(row)
        if explicit_event_slug and candidate.get("eventSlug") != explicit_event_slug:
            continue
        if explicit_market_slug and candidate.get("selectedMarketSlug") != explicit_market_slug:
            continue
        reason = _target_rejection_reason(candidate, bounds)
        if reason:
            rejected.append({**candidate, "rejectionReason": reason})
            continue
        eligible.append(candidate)
    if not eligible:
        return None, rejected
    eligible.sort(key=_target_priority, reverse=True)
    return eligible[0], rejected[:50]


def build_target_selection_payload(
    *,
    target: Mapping[str, object] | None,
    rejected_targets: Sequence[Mapping[str, object]],
    bounds: MeasurementBounds,
    env_status: Mapping[str, object],
) -> dict[str, object]:
    return {
        "reportType": f"{REPORT_TYPE}_target_selection",
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "bounds": bounds.to_dict(),
        "envStatus": dict(env_status),
        "selectedTarget": dict(target or {}),
        "selectedTargetCount": 1 if target else 0,
        "rejectedTargets": [dict(row) for row in rejected_targets],
        "selectionSource": "validation_outputs/event_forensic_performance_inventory_20260525.json",
    }


def run_bounded_measurement(
    target: Mapping[str, object],
    *,
    output_dir: Path,
    bounds: MeasurementBounds,
) -> dict[str, object]:
    ctx = mp.get_context("spawn")
    queue: mp.Queue = ctx.Queue()
    process = ctx.Process(
        target=_live_worker_entry,
        args=(dict(target), str(output_dir), bounds.to_dict(), queue),
        daemon=True,
    )
    started = time.monotonic()
    process.start()
    process.join(timeout=max(1, bounds.max_wall_seconds))
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        return {
            **_target_result_base(target),
            "status": "aborted_timeout",
            "gateDecision": "performance_measurement_blocked_scope_exceeded",
            "error": "max_wall_time_elapsed",
            "wallClockSeconds": round(time.monotonic() - started, 3),
        }
    payload: dict[str, object] | None = None
    while not queue.empty():
        message = queue.get()
        if isinstance(message, Mapping):
            payload = dict(message)
    if payload is None:
        return {
            **_target_result_base(target),
            "status": "failed_runtime_error",
            "gateDecision": "performance_measurement_inconclusive",
            "error": f"worker_exit_{process.exitcode}",
            "wallClockSeconds": round(time.monotonic() - started, 3),
        }
    payload["wallClockSeconds"] = round(time.monotonic() - started, 3)
    return payload


def build_summary(
    *,
    output_dir: Path,
    bounds: MeasurementBounds,
    env_status: Mapping[str, object],
    target_selection: Mapping[str, object],
    live_result: Mapping[str, object] | None,
) -> dict[str, object]:
    result = dict(live_result or {})
    report_summary = _report_summary_from_result(result)
    gate = _summary_gate(target_selection, result, report_summary, bounds)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "outputDir": str(output_dir),
        "sidecarOnly": True,
        "networkUsed": bool(live_result),
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "appStorageMutated": False,
        "productionIntegration": False,
        "privateKeyUsed": False,
        "clobAuthUsed": False,
        "ordersPlaced": False,
        "broadCrawlingUsed": False,
        "bounds": bounds.to_dict(),
        "envStatus": dict(env_status),
        "targetSelection": dict(target_selection),
        "liveResult": result,
        "reportSummary": report_summary,
        "summary": {
            "gateDecision": gate,
            "measurementExecuted": bool(live_result),
            "eventSlug": report_summary.get("eventSlug", ""),
            "analysisScope": report_summary.get("analysisScope", ""),
            "marketCount": report_summary.get("analysisMarketCount", 0),
            "totalEventMarketCount": report_summary.get("totalEventMarketCount", 0),
            "rawTradeRows": report_summary.get("rawTradeCount", 0),
            "candidateRows": report_summary.get("candidateTradeCount", 0),
            "candidateWalletCount": report_summary.get("candidateWalletCount", 0),
            "truncatedMarketCount": report_summary.get("truncatedMarketCount", 0),
            "dominantBottleneck": report_summary.get("dominantBottleneck", "unknown"),
            "totalSeconds": report_summary.get("totalSeconds", 0.0),
        },
        "forbiddenActionsPreserved": _forbidden_actions(),
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_PLAN_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-slug", default="")
    parser.add_argument("--market-slug", default="")
    parser.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    parser.add_argument("--max-events", type=int, default=DEFAULT_MAX_EVENTS)
    parser.add_argument("--max-markets", type=int, default=DEFAULT_MAX_MARKETS)
    parser.add_argument("--max-candidate-wallets-per-market", type=int, default=DEFAULT_MAX_CANDIDATE_WALLETS_PER_MARKET)
    parser.add_argument("--max-total-trade-rows", type=int, default=DEFAULT_MAX_TOTAL_TRADE_ROWS)
    parser.add_argument("--max-wall-minutes", type=int, default=DEFAULT_MAX_WALL_MINUTES)
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--timestamp", default=default_timestamp())
    parser.add_argument("--output", default=str(DEFAULT_PLAN_OUTPUT))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    bounds = MeasurementBounds(
        max_events=args.max_events,
        max_markets=args.max_markets,
        max_candidate_wallets_per_market=args.max_candidate_wallets_per_market,
        max_total_trade_rows=args.max_total_trade_rows,
        max_wall_minutes=args.max_wall_minutes,
    )
    if not args.run_live:
        payload = build_measurement_plan(
            event_slug=args.event_slug,
            market_slug=args.market_slug,
            max_events=args.max_events,
            max_markets=args.max_markets,
            max_candidate_wallets_per_market=args.max_candidate_wallets_per_market,
            max_total_trade_rows=args.max_total_trade_rows,
            max_wall_minutes=args.max_wall_minutes,
        )
        write_json(payload, args.output)
        if not args.quiet:
            print(f"gate: {payload['gateDecision']}")
            print(f"output: {args.output}")
        return 0

    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else ROOT / "validation_outputs" / f"event_forensic_performance_measurement_{args.timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    env_status = runtime_env_status(root=ROOT)
    violations = bound_violations(bounds)
    if violations:
        target_selection = build_target_selection_payload(
            target=None,
            rejected_targets=[{"rejectionReason": "scope_bound_violation", "boundViolations": violations}],
            bounds=bounds,
            env_status=env_status,
        )
        write_json(target_selection, output_dir / "target_selection.json")
        summary = build_summary(
            output_dir=output_dir,
            bounds=bounds,
            env_status=env_status,
            target_selection=target_selection,
            live_result=None,
        )
        summary["summary"]["gateDecision"] = "performance_measurement_blocked_scope_risk"
        write_json(summary, output_dir / "summary.json")
        _print_summary(summary, quiet=args.quiet)
        return 2
    target, rejected = select_bounded_target(
        inventory_path=args.inventory,
        bounds=bounds,
        explicit_event_slug=args.event_slug,
        explicit_market_slug=args.market_slug,
    )
    target_selection = build_target_selection_payload(
        target=target,
        rejected_targets=rejected,
        bounds=bounds,
        env_status=env_status,
    )
    write_json(target_selection, output_dir / "target_selection.json")
    if target is None:
        summary = build_summary(
            output_dir=output_dir,
            bounds=bounds,
            env_status=env_status,
            target_selection=target_selection,
            live_result=None,
        )
        summary["summary"]["gateDecision"] = "performance_measurement_blocked_no_target"
        write_json(summary, output_dir / "summary.json")
        _print_summary(summary, quiet=args.quiet)
        return 2
    live_result = run_bounded_measurement(target, output_dir=output_dir, bounds=bounds)
    summary = build_summary(
        output_dir=output_dir,
        bounds=bounds,
        env_status=env_status,
        target_selection=target_selection,
        live_result=live_result,
    )
    write_json(summary, output_dir / "summary.json")
    _print_summary(summary, quiet=args.quiet)
    return 0 if summary["summary"]["gateDecision"] == "performance_measurement_complete" else 2


def _live_worker_entry(target: dict[str, object], output_dir_raw: str, bounds_raw: dict[str, int], queue: Any) -> None:
    try:
        import threading

        from app.event_forensic import EventForensicAnalyzer
        from app.polymarket import PolymarketClient
        from app.storage import Storage

        output_dir = Path(output_dir_raw)
        worker_dir = output_dir / "live_run"
        data_dir = worker_dir / "isolated_app_data"
        config = AppConfig(
            data_dir=data_dir,
            db_path=data_dir / "event_forensic_performance.sqlite3",
            reports_dir=worker_dir / "reports",
            outputs_dir=worker_dir / "event_forensic_outputs",
            default_lookback="event",
            max_trade_pages=40,
            trade_page_size=100,
        )
        config.ensure_dirs()
        storage = Storage(config.db_path)
        storage.init()
        analyzer = EventForensicAnalyzer(PolymarketClient(), storage, config)
        bounds = MeasurementBounds(
            max_events=int(bounds_raw.get("maxEvents") or DEFAULT_MAX_EVENTS),
            max_markets=int(bounds_raw.get("maxMarkets") or DEFAULT_MAX_MARKETS),
            max_candidate_wallets_per_market=int(
                bounds_raw.get("maxCandidateWalletsPerMarket") or DEFAULT_MAX_CANDIDATE_WALLETS_PER_MARKET
            ),
            max_total_trade_rows=int(bounds_raw.get("maxTotalTradeRows") or DEFAULT_MAX_TOTAL_TRADE_ROWS),
            max_wall_minutes=int(bounds_raw.get("maxWallMinutes") or DEFAULT_MAX_WALL_MINUTES),
        )
        input_value = str(target.get("inputValue") or "")
        resolved_target = analyzer.resolve_target(
            input_value,
            analysis_scope="event",
            include_related_markets=False,
        )
        available_markets = resolved_target.get("availableMarkets") if isinstance(resolved_target, Mapping) else []
        live_market_count = len(available_markets) if isinstance(available_markets, list) else 0
        if live_market_count > bounds.max_markets:
            queue.put(
                {
                    **_target_result_base(target),
                    "status": "blocked_scope_exceeded",
                    "gateDecision": "performance_measurement_blocked_scope_risk",
                    "error": "resolved_market_count_exceeds_bound",
                    "resolvedMarketCount": live_market_count,
                    "resolvedTarget": resolved_target,
                }
            )
            return

        stop_event = threading.Event()
        progress_rows: list[dict[str, object]] = []
        measurement_started = time.monotonic()

        def progress_callback(event: object) -> None:
            metadata = getattr(event, "metadata", None)
            row = {
                "percent": getattr(event, "percent", 0),
                "stage": getattr(event, "stage", ""),
                "detail": getattr(event, "detail", ""),
                "metadata": metadata if isinstance(metadata, dict) else {},
                "elapsedSeconds": round(time.monotonic() - measurement_started, 3),
            }
            progress_rows.append(row)
            if len(progress_rows) > 250:
                del progress_rows[:-250]
            meta = row["metadata"]
            raw_rows = _int_or_none(meta.get("rawTradeRowsCollectedSoFar")) if isinstance(meta, Mapping) else None
            if raw_rows is not None and raw_rows > bounds.max_total_trade_rows:
                stop_event.set()
            if time.monotonic() - measurement_started > bounds.max_wall_seconds:
                stop_event.set()

        report = analyzer.analyze(
            input_value,
            config.reports_dir,
            min_notional=_decimal_or_none(target.get("minNotional")) or Decimal("250"),
            include_related_markets=False,
            include_blockchain=False,
            funding_trace_mode=FUNDING_TRACE_MODE_DISABLED,
            analysis_scope="event",
            progress_callback=progress_callback,
            stop_event=stop_event,
        )
        export_files = report.get("export_files") if isinstance(report, Mapping) else {}
        if not isinstance(export_files, Mapping):
            export_files = {}
        summary = report.get("summary") if isinstance(report, Mapping) else {}
        if not isinstance(summary, Mapping):
            summary = {}
        performance = report.get("performance") if isinstance(report, Mapping) else {}
        if not isinstance(performance, Mapping):
            performance = {}
        report_summary = _report_summary_from_report(report)
        runtime_violations = _runtime_bound_violations(report_summary, bounds)
        gate = "performance_measurement_complete" if not runtime_violations and report.get("status") == "completed" else "performance_measurement_blocked_scope_risk"
        queue.put(
            {
                **_target_result_base(target),
                "status": str(report.get("status") or "unknown"),
                "gateDecision": gate,
                "eventAnalysisJsonPath": str(export_files.get("event_analysis_json_path") or ""),
                "reportJsonPath": str(export_files.get("report_json_path") or ""),
                "reportMarkdownPath": str(export_files.get("event_report_md_path") or ""),
                "rawTradeCount": _int_or_none(summary.get("raw_trade_count")),
                "candidateTradeCount": _int_or_none(summary.get("candidate_trade_count")),
                "candidateWalletCount": _int_or_none(performance.get("candidate_wallet_count")),
                "truncatedMarketCount": _int_or_none(summary.get("truncated_market_count")),
                "analysisMarketCount": _int_or_none(summary.get("analysis_market_count")),
                "totalEventMarketCount": _int_or_none(summary.get("total_event_market_count")),
                "timings": _timings(performance),
                "dominantBottleneck": _dominant_bottleneck(_timings(performance)),
                "runtimeBoundViolations": runtime_violations,
                "progressTail": progress_rows[-25:],
                "fundingTraceMode": "disabled",
                "isolatedDataDir": str(data_dir),
                "storageScope": "validation_output_dir_only",
                "resolvedTarget": resolved_target,
            }
        )
    except Exception as exc:
        queue.put({**_target_result_base(target), "status": "failed_runtime_error", "error": f"{type(exc).__name__}: {exc}"})


def _load_inventory_rows(*, root: str | Path, inventory_path: str | Path) -> list[dict[str, object]]:
    path = Path(inventory_path)
    if not path.is_absolute():
        path = Path(root) / path
    rows: list[dict[str, object]] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, Mapping):
        for row in payload.get("slowestReports", []):
            if isinstance(row, Mapping):
                rows.append(dict(row))

    # The committed inventory stores the slowest rows only. Rebuild locally so
    # target selection can find smaller bounded whole-event runs too.
    try:
        from tools.event_forensic_performance_inventory import (
            DEFAULT_MAX_BYTES,
            DEFAULT_MAX_FILES,
            _looks_like_event_forensic_report,
            _report_row,
            discover_report_paths,
        )

        seen = {str(row.get("path") or "") for row in rows}
        for report_path in discover_report_paths(root, max_files=DEFAULT_MAX_FILES):
            if str(report_path) in seen:
                continue
            size = report_path.stat().st_size
            if size > DEFAULT_MAX_BYTES:
                continue
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if _looks_like_event_forensic_report(report):
                rows.append(_report_row(report_path, report, size))
    except Exception:
        pass
    return rows


def _target_candidate(row: Mapping[str, object]) -> dict[str, object]:
    path = str(row.get("path") or "")
    min_notional = "250.00"
    try:
        report = json.loads((ROOT / path).read_text(encoding="utf-8"))
        settings = report.get("analysis_settings") if isinstance(report, Mapping) else {}
        if isinstance(settings, Mapping) and settings.get("min_notional"):
            min_notional = str(settings.get("min_notional"))
    except Exception:
        pass
    event_slug = str(row.get("eventSlug") or "").strip()
    return {
        "label": "bounded_performance_target",
        "eventSlug": event_slug,
        "eventTitle": str(row.get("eventTitle") or ""),
        "inputValue": f"https://polymarket.com/event/{event_slug}" if event_slug else "",
        "analysisScope": str(row.get("analysisScope") or ""),
        "selectedMarketSlug": str(row.get("selectedMarketSlug") or ""),
        "analysisMarketCount": _int_or_none(row.get("analysisMarketCount")) or 0,
        "totalEventMarketCount": _int_or_none(row.get("totalEventMarketCount")) or 0,
        "truncatedMarketCount": _int_or_none(row.get("truncatedMarketCount")) or 0,
        "rawTradeCount": _int_or_none(row.get("rawTradeCount")) or 0,
        "candidateTradeCount": _int_or_none(row.get("candidateTradeCount")) or 0,
        "candidateWalletCount": _int_or_none(row.get("candidateWalletCount")) or 0,
        "walletContextCount": _int_or_none(row.get("walletContextCount")) or 0,
        "totalSeconds": _float_or_none(row.get("totalSeconds")) or 0.0,
        "dominantBottleneck": str(row.get("dominantBottleneck") or "unknown"),
        "sourceReportPath": path,
        "selectionReason": "bounded whole-event local performance report",
        "minNotional": min_notional,
    }


def _target_rejection_reason(candidate: Mapping[str, object], bounds: MeasurementBounds) -> str:
    if candidate.get("analysisScope") != "whole_event":
        return "not_whole_event_scope"
    if not candidate.get("eventSlug") or not candidate.get("inputValue"):
        return "missing_event_slug"
    markets = _int_or_none(candidate.get("analysisMarketCount")) or 0
    if markets <= 0:
        return "missing_analysis_market_count"
    if markets > bounds.max_markets:
        return "analysis_market_count_exceeds_bound"
    raw_rows = _int_or_none(candidate.get("rawTradeCount")) or 0
    if raw_rows > bounds.max_total_trade_rows:
        return "raw_trade_count_exceeds_bound"
    wallets = _int_or_none(candidate.get("candidateWalletCount")) or 0
    if wallets > markets * bounds.max_candidate_wallets_per_market:
        return "candidate_wallet_count_exceeds_per_market_bound"
    return ""


def _target_priority(candidate: Mapping[str, object]) -> tuple[int, float, int, int, int]:
    truncated = 1 if (_int_or_none(candidate.get("truncatedMarketCount")) or 0) > 0 else 0
    return (
        truncated,
        float(candidate.get("totalSeconds") or 0.0),
        _int_or_none(candidate.get("candidateWalletCount")) or 0,
        _int_or_none(candidate.get("rawTradeCount")) or 0,
        _int_or_none(candidate.get("analysisMarketCount")) or 0,
    )


def _target_result_base(target: Mapping[str, object]) -> dict[str, object]:
    return {
        "label": str(target.get("label") or ""),
        "eventSlug": str(target.get("eventSlug") or ""),
        "inputValue": str(target.get("inputValue") or ""),
        "sourceReportPath": str(target.get("sourceReportPath") or ""),
    }


def _report_summary_from_result(result: Mapping[str, object]) -> dict[str, object]:
    path = Path(str(result.get("eventAnalysisJsonPath") or ""))
    if path.is_file():
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report = {}
        if isinstance(report, Mapping):
            return _report_summary_from_report(report)
    raw_timings = result.get("timings")
    timings = raw_timings if isinstance(raw_timings, dict) else {}
    return {
        "eventSlug": str(result.get("eventSlug") or ""),
        "analysisScope": "",
        "analysisMarketCount": _int_or_none(result.get("analysisMarketCount")) or 0,
        "totalEventMarketCount": _int_or_none(result.get("totalEventMarketCount")) or 0,
        "rawTradeCount": _int_or_none(result.get("rawTradeCount")) or 0,
        "candidateTradeCount": _int_or_none(result.get("candidateTradeCount")) or 0,
        "candidateWalletCount": _int_or_none(result.get("candidateWalletCount")) or 0,
        "truncatedMarketCount": _int_or_none(result.get("truncatedMarketCount")) or 0,
        "timings": dict(timings),
        "dominantBottleneck": str(result.get("dominantBottleneck") or _dominant_bottleneck(timings)),
        "totalSeconds": _float_or_none(timings.get("total_seconds")) or 0.0,
    }


def _report_summary_from_report(report: Mapping[str, object]) -> dict[str, object]:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    event = report.get("event") if isinstance(report.get("event"), Mapping) else {}
    performance = report.get("performance") if isinstance(report.get("performance"), Mapping) else {}
    timings = _timings(performance)
    return {
        "eventSlug": str(report.get("eventSlug") or event.get("slug") or ""),
        "analysisScope": str(report.get("analysisScope") or summary.get("analysisScope") or report.get("analysis_scope") or ""),
        "analysisMarketCount": _int_or_none(summary.get("analysis_market_count") or event.get("analysisMarketCount")) or 0,
        "totalEventMarketCount": _int_or_none(summary.get("total_event_market_count") or event.get("marketCount")) or 0,
        "rawTradeCount": _int_or_none(summary.get("raw_trade_count") or performance.get("trade_collection_raw_trade_rows")) or 0,
        "candidateTradeCount": _int_or_none(summary.get("candidate_trade_count") or performance.get("candidate_trade_count_visible")) or 0,
        "candidateWalletCount": _int_or_none(performance.get("candidate_wallet_count")) or 0,
        "truncatedMarketCount": _int_or_none(summary.get("truncated_market_count") or performance.get("trade_collection_truncated_markets")) or 0,
        "timings": timings,
        "dominantBottleneck": _dominant_bottleneck(timings),
        "totalSeconds": _float_or_none(performance.get("total_seconds")) or _float_or_none(performance.get("totalSeconds")) or 0.0,
        "status": str(report.get("status") or ""),
    }


def _summary_gate(
    target_selection: Mapping[str, object],
    result: Mapping[str, object],
    report_summary: Mapping[str, object],
    bounds: MeasurementBounds,
) -> str:
    if not target_selection.get("selectedTargetCount"):
        return "performance_measurement_blocked_no_target"
    if not result:
        return "performance_measurement_inconclusive"
    if result.get("status") == "aborted_timeout" or result.get("gateDecision") == "performance_measurement_blocked_scope_risk":
        return "performance_measurement_blocked_scope_risk"
    if result.get("status") != "completed":
        return "performance_measurement_inconclusive"
    if _runtime_bound_violations(report_summary, bounds):
        return "performance_measurement_blocked_scope_risk"
    return "performance_measurement_complete"


def _runtime_bound_violations(report_summary: Mapping[str, object], bounds: MeasurementBounds) -> list[str]:
    violations: list[str] = []
    markets = _int_or_none(report_summary.get("analysisMarketCount")) or 0
    if markets > bounds.max_markets:
        violations.append("analysis_market_count_exceeds_bound")
    raw_rows = _int_or_none(report_summary.get("rawTradeCount")) or 0
    if raw_rows > bounds.max_total_trade_rows:
        violations.append("raw_trade_count_exceeds_bound")
    wallets = _int_or_none(report_summary.get("candidateWalletCount")) or 0
    if markets and wallets > markets * bounds.max_candidate_wallets_per_market:
        violations.append("candidate_wallet_count_exceeds_per_market_bound")
    total_seconds = _float_or_none(report_summary.get("totalSeconds")) or 0.0
    if total_seconds > bounds.max_wall_seconds:
        violations.append("total_seconds_exceeds_bound")
    return violations


def _timings(performance: Mapping[str, object]) -> dict[str, float]:
    fields = (
        "resolve_input_seconds",
        "collect_event_trades_seconds",
        "trade_collection_elapsed_seconds",
        "prefetch_wallet_context_seconds",
        "prepare_candidate_context_seconds",
        "prefetch_funding_context_seconds",
        "score_candidates_seconds",
        "collect_price_history_seconds",
        "related_market_scan_seconds",
        "assemble_report_rows_seconds",
        "total_seconds",
    )
    result: dict[str, float] = {}
    for field in fields:
        value = _float_or_none(performance.get(field))
        if value is not None:
            result[field] = value
    return result


def _dominant_bottleneck(timings: Mapping[str, object]) -> str:
    fields = (
        "collect_event_trades_seconds",
        "prefetch_wallet_context_seconds",
        "prepare_candidate_context_seconds",
        "prefetch_funding_context_seconds",
        "score_candidates_seconds",
        "collect_price_history_seconds",
        "related_market_scan_seconds",
        "assemble_report_rows_seconds",
    )
    present = {field: _float_or_none(timings.get(field)) for field in fields if _float_or_none(timings.get(field)) is not None}
    if not present:
        return "unknown"
    return max(present.items(), key=lambda item: float(item[1] or 0.0))[0]


def _plan_gate(
    violations: Sequence[str],
    env_status: Mapping[str, object],
    event_slug: str,
    market_slug: str,
) -> str:
    if violations:
        return "performance_measurement_scope_exceeded"
    if not env_status.get("rpcConfigured"):
        return "performance_measurement_blocked_missing_env"
    if not event_slug and not market_slug:
        return "performance_measurement_needs_operator_approval"
    return "performance_measurement_needs_operator_approval"


def _plan_next_action(gate: str) -> str:
    if gate == "performance_measurement_blocked_missing_env":
        return "Provide read-only RPC/API env and exact saved-report target before live measurement."
    if gate == "performance_measurement_scope_exceeded":
        return "Reduce bounds to campaign limits before live measurement."
    return "Run explicit --run-live measurement with selected local target and bounds."


def _forbidden_actions() -> list[str]:
    return [
        "Do not broaden discovery beyond the selected event.",
        "Do not use private keys, CLOB auth, trading credentials, or order placement.",
        "Do not change scoring, thresholds, gates, storage schema, Phase 3, or UI sorting.",
        "Do not write to normal app storage or mutate saved reports.",
    ]


def _int_or_none(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _decimal_or_none(value: object) -> Decimal | None:
    try:
        if value in (None, ""):
            return None
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _print_summary(summary: Mapping[str, object], *, quiet: bool) -> None:
    if quiet:
        return
    aggregate = summary.get("summary") if isinstance(summary.get("summary"), Mapping) else {}
    print(json.dumps({"summaryPath": str(Path(str(summary.get("outputDir") or "")) / "summary.json"), "gate": aggregate.get("gateDecision")}, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
