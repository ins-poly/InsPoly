#!/usr/bin/env python3
"""Subset-only Event Forensic performance measurement helper.

The default mode is offline selection/analysis. Live execution requires
``--run-live`` and filters the resolved event to an explicit market slug
allowlist from a local saved report family. The output is validation-only and
must not be interpreted as whole-event complete.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import FUNDING_TRACE_MODE_DISABLED, AppConfig
from tools.event_forensic_bounded_performance_measurement import (
    MeasurementBounds,
    _dominant_bottleneck,
    _float_or_none,
    _forbidden_actions,
    _int_or_none,
    _report_summary_from_result,
    _timings,
    runtime_env_status,
    write_json,
)


REPORT_TYPE = "event_forensic_subset_performance_measurement"
SCHEMA_VERSION = "event_forensic_subset_performance_measurement_v1"
DEFAULT_APPROVAL_PACKAGE = Path("docs/inspoly_event_forensic_subset_measurement_approval_package_20260525.md")
DEFAULT_SAVED_REPORT = Path("event_forensic_outputs/event_forensic_20260430_170713/event_analysis.json")
DEFAULT_SELECTION_OUTPUT = Path("validation_outputs/event_forensic_subset_measurement_selection_20260525.json")
DEFAULT_ANALYSIS_OUTPUT = Path("validation_outputs/event_forensic_subset_measurement_analysis_20260525.json")
DEFAULT_AGGREGATE = Path("validation_outputs/event_forensic_performance_measurement_aggregate_20260525.json")
DEFAULT_EVENT_SLUG = "us-x-iran-permanent-peace-deal-by"
DEFAULT_TIMESTAMP_PREFIX = "event_forensic_subset_measurement"


def build_subset_selection(
    *,
    saved_report_path: str | Path = DEFAULT_SAVED_REPORT,
    event_slug: str = DEFAULT_EVENT_SLUG,
    bounds: MeasurementBounds = MeasurementBounds(),
    approval_package_path: str | Path = DEFAULT_APPROVAL_PACKAGE,
) -> dict[str, object]:
    report_path = _resolve_path(saved_report_path)
    report = _load_json_object(report_path)
    report_markets = _extract_report_markets(report)
    selected = report_markets[: bounds.max_markets]
    missing_reason = ""
    if not selected:
        missing_reason = "saved_report_has_no_market_slug_allowlist"
    elif not event_slug:
        missing_reason = "missing_event_slug"
    elif len(selected) > bounds.max_markets:
        missing_reason = "subset_market_count_exceeds_bound"
    gate = "subset_selection_ready" if not missing_reason else "subset_measurement_blocked_needs_selection"
    selected_slugs = [str(row["marketSlug"]) for row in selected if row.get("marketSlug")]
    return {
        "reportType": f"{REPORT_TYPE}_selection",
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "storageMutated": False,
        "subsetOnly": True,
        "wholeEventCompletenessClaim": False,
        "gateDecision": gate,
        "blockReason": missing_reason,
        "eventSlug": event_slug,
        "inputValue": f"https://polymarket.com/event/{event_slug}" if event_slug else "",
        "sourceReportPath": _relative_or_absolute(report_path),
        "approvalPackagePath": _relative_or_absolute(_resolve_path(approval_package_path)),
        "selectionSource": "explicit_market_slug_allowlist_from_local_saved_report_family",
        "selectedMarketSlugs": selected_slugs,
        "selectedMarkets": selected,
        "selectedMarketCount": len(selected_slugs),
        "whySelected": (
            "Local saved report family contains a 6-market analysis for the larger Iran peace-deal event; "
            "the current live whole-event scope exceeds the 8-market full-measurement cap."
        ),
        "whySubsetIsNotWholeEvent": (
            "The approved subset is not the full event. The current live event resolves beyond the approved "
            "subset, so this run may measure timing and truncation within the explicit market allowlist only "
            "and cannot claim whole-event completeness."
        ),
        "bounds": bounds.to_dict(),
        "forbiddenActions": _forbidden_actions(),
    }


def validate_subset_selection(selection: Mapping[str, object], *, bounds: MeasurementBounds) -> list[str]:
    violations: list[str] = []
    if not selection.get("subsetOnly"):
        violations.append("missing_subset_only_label")
    if selection.get("wholeEventCompletenessClaim"):
        violations.append("whole_event_completeness_claim_not_allowed")
    if not str(selection.get("eventSlug") or "").strip():
        violations.append("missing_event_slug")
    slugs = selection.get("selectedMarketSlugs")
    if not isinstance(slugs, list) or not slugs:
        violations.append("missing_market_slug_allowlist")
    else:
        clean_slugs = [str(slug).strip() for slug in slugs if str(slug).strip()]
        if len(clean_slugs) != len(slugs):
            violations.append("empty_market_slug_in_allowlist")
        if len(clean_slugs) > bounds.max_markets:
            violations.append("subset_market_count_exceeds_bound")
    return violations


def run_subset_measurement(
    selection: Mapping[str, object],
    *,
    output_dir: Path,
    bounds: MeasurementBounds,
) -> dict[str, object]:
    ctx = mp.get_context("spawn")
    queue: mp.Queue = ctx.Queue()
    process = ctx.Process(
        target=_live_subset_worker_entry,
        args=(dict(selection), str(output_dir), bounds.to_dict(), queue),
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
            "status": "aborted_timeout",
            "gateDecision": "subset_measurement_blocked_scope",
            "error": "max_wall_time_elapsed",
            "wallClockSeconds": round(time.monotonic() - started, 3),
            "subsetOnly": True,
            "wholeEventCompletenessClaim": False,
        }
    payload: dict[str, object] | None = None
    while not queue.empty():
        message = queue.get()
        if isinstance(message, Mapping):
            payload = dict(message)
    if payload is None:
        return {
            "status": "failed_runtime_error",
            "gateDecision": "subset_measurement_inconclusive",
            "error": f"worker_exit_{process.exitcode}",
            "wallClockSeconds": round(time.monotonic() - started, 3),
            "subsetOnly": True,
            "wholeEventCompletenessClaim": False,
        }
    payload["wallClockSeconds"] = round(time.monotonic() - started, 3)
    return payload


def build_subset_summary(
    *,
    output_dir: Path,
    bounds: MeasurementBounds,
    env_status: Mapping[str, object],
    selection: Mapping[str, object],
    live_result: Mapping[str, object] | None,
) -> dict[str, object]:
    result = dict(live_result or {})
    report_summary = _report_summary_from_result(result)
    gate = _summary_gate(selection, result, report_summary, bounds)
    selected_count = len(selection.get("selectedMarketSlugs") or [])
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "outputDir": str(output_dir),
        "sidecarOnly": True,
        "subsetOnly": True,
        "wholeEventCompletenessClaim": False,
        "completenessDisclaimer": _subset_disclaimer(),
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
        "selection": dict(selection),
        "liveResult": result,
        "reportSummary": report_summary,
        "summary": {
            "gateDecision": gate,
            "measurementExecuted": bool(live_result),
            "eventSlug": report_summary.get("eventSlug", "") or selection.get("eventSlug", ""),
            "subsetOnly": True,
            "wholeEventCompletenessClaim": False,
            "selectedMarketCount": selected_count,
            "analysisMarketCount": report_summary.get("analysisMarketCount", 0),
            "liveResolvedMarketCount": result.get("liveResolvedMarketCount", 0),
            "rawTradeRows": report_summary.get("rawTradeCount", 0),
            "candidateRows": report_summary.get("candidateTradeCount", 0),
            "candidateWalletCount": report_summary.get("candidateWalletCount", 0),
            "truncatedMarketCount": report_summary.get("truncatedMarketCount", 0),
            "dominantBottleneck": report_summary.get("dominantBottleneck", "unknown"),
            "totalSeconds": report_summary.get("totalSeconds", 0.0),
            "runtimeBoundViolations": list(result.get("runtimeBoundViolations", []))
            if isinstance(result.get("runtimeBoundViolations"), list)
            else [],
        },
        "forbiddenActionsPreserved": _forbidden_actions(),
    }


def build_subset_analysis(
    *,
    subset_summary: Mapping[str, object],
    aggregate_payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    summary = subset_summary.get("summary") if isinstance(subset_summary.get("summary"), Mapping) else {}
    live_result = subset_summary.get("liveResult") if isinstance(subset_summary.get("liveResult"), Mapping) else {}
    aggregate_summary = {}
    if isinstance(aggregate_payload, Mapping):
        aggregate_summary = aggregate_payload.get("summary") if isinstance(aggregate_payload.get("summary"), Mapping) else {}
    gate = _analysis_gate(summary)
    total_seconds = _float_or_none(summary.get("totalSeconds")) or 0.0
    prior_median = _float_or_none(aggregate_summary.get("medianTotalSeconds")) or 0.0
    return {
        "reportType": f"{REPORT_TYPE}_analysis",
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "subsetOnly": True,
        "wholeEventCompletenessClaim": False,
        "networkUsed": bool(subset_summary.get("networkUsed")),
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "storageMutated": False,
        "summary": {
            "gateDecision": gate,
            "eventSlug": summary.get("eventSlug", ""),
            "selectedMarketCount": _int_or_none(summary.get("selectedMarketCount")) or 0,
            "analysisMarketCount": _int_or_none(summary.get("analysisMarketCount")) or 0,
            "liveResolvedMarketCount": _int_or_none(summary.get("liveResolvedMarketCount")) or 0,
            "rawTradeRows": _int_or_none(summary.get("rawTradeRows")) or 0,
            "candidateRows": _int_or_none(summary.get("candidateRows")) or 0,
            "candidateWalletCount": _int_or_none(summary.get("candidateWalletCount")) or 0,
            "truncatedMarketCount": _int_or_none(summary.get("truncatedMarketCount")) or 0,
            "dominantBottleneck": str(summary.get("dominantBottleneck") or "unknown"),
            "totalSeconds": total_seconds,
            "priorSmallTargetMedianSeconds": prior_median,
            "secondsVsPriorMedianDelta": round(total_seconds - prior_median, 2) if prior_median else 0.0,
            "runtimeBoundViolations": list(live_result.get("runtimeBoundViolations", []))
            if isinstance(live_result.get("runtimeBoundViolations"), list)
            else list(summary.get("runtimeBoundViolations", []))
            if isinstance(summary.get("runtimeBoundViolations"), list)
            else [],
        },
        "bottleneckAssessment": _bottleneck_assessment(summary, aggregate_summary),
        "paginationAssessment": _pagination_assessment(summary),
        "claimsNotSupported": [
            "whole_event_completeness",
            "candidate_quality_for_excluded_markets",
            "full_event_pagination_correctness",
            "scorer_or_gate_tuning_decisions",
        ],
        "patchRfcRecommended": gate == "subset_measurement_complete_patch_rfc_ready",
        "liveResultOutputDir": str(subset_summary.get("outputDir") or live_result.get("outputDir") or ""),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saved-report", default=str(DEFAULT_SAVED_REPORT))
    parser.add_argument("--event-slug", default=DEFAULT_EVENT_SLUG)
    parser.add_argument("--selection-output", default=str(DEFAULT_SELECTION_OUTPUT))
    parser.add_argument("--selection", default="")
    parser.add_argument("--aggregate", default=str(DEFAULT_AGGREGATE))
    parser.add_argument("--analysis-output", default=str(DEFAULT_ANALYSIS_OUTPUT))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--timestamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--max-markets", type=int, default=8)
    parser.add_argument("--max-candidate-wallets-per-market", type=int, default=150)
    parser.add_argument("--max-total-trade-rows", type=int, default=50_000)
    parser.add_argument("--max-wall-minutes", type=int, default=30)
    parser.add_argument("--select-only", action="store_true")
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    bounds = MeasurementBounds(
        max_markets=args.max_markets,
        max_candidate_wallets_per_market=args.max_candidate_wallets_per_market,
        max_total_trade_rows=args.max_total_trade_rows,
        max_wall_minutes=args.max_wall_minutes,
    )
    selection_path = Path(args.selection) if args.selection else Path(args.selection_output)
    if args.select_only or (not args.run_live and not args.analyze):
        selection = build_subset_selection(
            saved_report_path=args.saved_report,
            event_slug=args.event_slug,
            bounds=bounds,
        )
        write_json(selection, selection_path)
        _print({"selectionPath": str(selection_path), "gate": selection["gateDecision"]}, quiet=args.quiet)
        return 0 if selection["gateDecision"] == "subset_selection_ready" else 2

    selection = _load_json_object(_resolve_path(selection_path))
    violations = validate_subset_selection(selection, bounds=bounds)
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else ROOT / "validation_outputs" / f"{DEFAULT_TIMESTAMP_PREFIX}_{args.timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(selection, output_dir / "target_selection.json")
    if args.run_live:
        env_status = runtime_env_status(root=ROOT)
        if violations:
            live_result = {
                "status": "blocked_scope",
                "gateDecision": "subset_measurement_blocked_scope",
                "runtimeBoundViolations": violations,
                "subsetOnly": True,
                "wholeEventCompletenessClaim": False,
            }
        else:
            live_result = run_subset_measurement(selection, output_dir=output_dir, bounds=bounds)
        subset_summary = build_subset_summary(
            output_dir=output_dir,
            bounds=bounds,
            env_status=env_status,
            selection=selection,
            live_result=live_result,
        )
        write_json(subset_summary, output_dir / "summary.json")
        aggregate = _try_load_json_object(_resolve_path(args.aggregate))
        analysis = build_subset_analysis(subset_summary=subset_summary, aggregate_payload=aggregate)
        write_json(analysis, args.analysis_output)
        _print(
            {
                "summaryPath": str(output_dir / "summary.json"),
                "analysisPath": args.analysis_output,
                "gate": analysis["summary"]["gateDecision"],
            },
            quiet=args.quiet,
        )
        return 0 if subset_summary["summary"]["gateDecision"] == "subset_measurement_complete" else 2

    summary_path = output_dir / "summary.json"
    subset_summary = _load_json_object(summary_path)
    aggregate = _try_load_json_object(_resolve_path(args.aggregate))
    analysis = build_subset_analysis(subset_summary=subset_summary, aggregate_payload=aggregate)
    write_json(analysis, args.analysis_output)
    _print({"analysisPath": args.analysis_output, "gate": analysis["summary"]["gateDecision"]}, quiet=args.quiet)
    return 0


def _live_subset_worker_entry(selection: dict[str, object], output_dir_raw: str, bounds_raw: dict[str, int], queue: Any) -> None:
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
            db_path=data_dir / "event_forensic_subset_performance.sqlite3",
            reports_dir=worker_dir / "reports",
            outputs_dir=worker_dir / "event_forensic_outputs",
            default_lookback="event",
            max_trade_pages=40,
            trade_page_size=100,
        )
        config.ensure_dirs()
        storage = Storage(config.db_path)
        storage.init()
        bounds = MeasurementBounds(
            max_markets=int(bounds_raw.get("maxMarkets") or 8),
            max_candidate_wallets_per_market=int(bounds_raw.get("maxCandidateWalletsPerMarket") or 150),
            max_total_trade_rows=int(bounds_raw.get("maxTotalTradeRows") or 50_000),
            max_wall_minutes=int(bounds_raw.get("maxWallMinutes") or 30),
        )
        selected_slugs = tuple(str(slug).strip() for slug in selection.get("selectedMarketSlugs", []) if str(slug).strip())
        selected_market_rows = selection.get("selectedMarkets") if isinstance(selection.get("selectedMarkets"), list) else []
        selected_condition_ids = tuple(
            str(row.get("conditionId") or "").strip()
            for row in selected_market_rows
            if isinstance(row, Mapping) and str(row.get("conditionId") or "").strip()
        )
        analyzer = _SubsetEventForensicAnalyzer(
            PolymarketClient(),
            storage,
            config,
            selected_market_slugs=selected_slugs,
            selected_condition_ids=selected_condition_ids,
        )
        input_value = str(selection.get("inputValue") or "")
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
            min_notional=Decimal("250"),
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
        timings = _timings(performance)
        report_summary = _report_summary_from_result(
            {
                "eventAnalysisJsonPath": str(export_files.get("event_analysis_json_path") or ""),
                "timings": timings,
            }
        )
        runtime_violations = _runtime_bound_violations(report_summary, bounds)
        gate = (
            "subset_measurement_complete"
            if not runtime_violations and report.get("status") == "completed"
            else "subset_measurement_blocked_scope"
        )
        queue.put(
            {
                "status": str(report.get("status") or "unknown"),
                "gateDecision": gate,
                "eventSlug": str(selection.get("eventSlug") or ""),
                "inputValue": input_value,
                "subsetOnly": True,
                "wholeEventCompletenessClaim": False,
                "completenessDisclaimer": _subset_disclaimer(),
                "selectedMarketSlugs": list(selected_slugs),
                "selectedMarketCount": len(selected_slugs),
                "liveResolvedMarketCount": analyzer.live_resolved_market_count,
                "eventAnalysisJsonPath": str(export_files.get("event_analysis_json_path") or ""),
                "reportJsonPath": str(export_files.get("report_json_path") or ""),
                "reportMarkdownPath": str(export_files.get("event_report_md_path") or ""),
                "rawTradeCount": _int_or_none(summary.get("raw_trade_count")),
                "candidateTradeCount": _int_or_none(summary.get("candidate_trade_count")),
                "candidateWalletCount": _int_or_none(performance.get("candidate_wallet_count")),
                "truncatedMarketCount": _int_or_none(summary.get("truncated_market_count")),
                "analysisMarketCount": _int_or_none(summary.get("analysis_market_count")),
                "totalEventMarketCount": analyzer.live_resolved_market_count,
                "timings": timings,
                "dominantBottleneck": _dominant_bottleneck(timings),
                "runtimeBoundViolations": runtime_violations,
                "progressTail": progress_rows[-25:],
                "fundingTraceMode": "disabled",
                "isolatedDataDir": str(data_dir),
                "storageScope": "validation_output_dir_only",
                "missingSelectedMarketSlugs": analyzer.missing_selected_market_slugs,
                "missingSelectedConditionIds": analyzer.missing_selected_condition_ids,
                "matchedSelectedMarketSlugs": analyzer.matched_selected_market_slugs,
                "matchedSelectedConditionIds": analyzer.matched_selected_condition_ids,
                "slugDriftObserved": analyzer.slug_drift_observed,
            }
        )
    except Exception as exc:
        queue.put(
            {
                "status": "failed_runtime_error",
                "gateDecision": "subset_measurement_inconclusive",
                "error": f"{type(exc).__name__}: {exc}",
                "subsetOnly": True,
                "wholeEventCompletenessClaim": False,
            }
        )


class _SubsetEventForensicAnalyzer:
    """Delegating wrapper that filters resolved markets for validation only."""

    def __init__(
        self,
        client: object,
        storage: object,
        config: AppConfig,
        *,
        selected_market_slugs: Sequence[str],
        selected_condition_ids: Sequence[str],
    ) -> None:
        from app.event_forensic import EventForensicAnalyzer

        self._delegate = EventForensicAnalyzer(client, storage, config)
        self._selected_market_slugs = tuple(str(slug).strip() for slug in selected_market_slugs if str(slug).strip())
        self._selected_condition_ids = tuple(
            str(condition_id).strip() for condition_id in selected_condition_ids if str(condition_id).strip()
        )
        self.live_resolved_market_count = 0
        self.missing_selected_market_slugs: list[str] = []
        self.missing_selected_condition_ids: list[str] = []
        self.matched_selected_market_slugs: list[str] = []
        self.matched_selected_condition_ids: list[str] = []
        self.slug_drift_observed: list[dict[str, str]] = []

    def analyze(self, *args: object, **kwargs: object) -> dict[str, object]:
        original = self._delegate.resolve_input

        def subset_resolve(input_value: str) -> object:
            resolved = original(input_value)
            self.live_resolved_market_count = len(resolved.markets)
            slug_to_condition = {market.slug: condition_id for condition_id, market in resolved.markets.items()}
            selected_conditions: list[str] = []
            for index, slug in enumerate(self._selected_market_slugs):
                requested_condition_id = self._selected_condition_ids[index] if index < len(self._selected_condition_ids) else ""
                if requested_condition_id and requested_condition_id in resolved.markets:
                    selected_conditions.append(requested_condition_id)
                    live_slug = resolved.markets[requested_condition_id].slug
                    if live_slug != slug:
                        self.slug_drift_observed.append(
                            {
                                "conditionId": requested_condition_id,
                                "approvedSavedSlug": slug,
                                "liveResolvedSlug": live_slug,
                            }
                        )
                    continue
                if slug in slug_to_condition:
                    selected_conditions.append(slug_to_condition[slug])
            self.matched_selected_market_slugs = [
                resolved.markets[condition_id].slug for condition_id in selected_conditions
            ]
            self.matched_selected_condition_ids = list(selected_conditions)
            selected_pairs = [
                (
                    slug,
                    self._selected_condition_ids[index] if index < len(self._selected_condition_ids) else "",
                )
                for index, slug in enumerate(self._selected_market_slugs)
            ]
            self.missing_selected_market_slugs = [
                slug
                for slug, condition_id in selected_pairs
                if slug not in slug_to_condition and condition_id not in resolved.markets
            ]
            self.missing_selected_condition_ids = [
                condition_id
                for slug, condition_id in selected_pairs
                if condition_id and condition_id not in resolved.markets and slug not in slug_to_condition
            ]
            if self.missing_selected_market_slugs:
                raise ValueError(
                    "Selected subset market slug(s)/condition ID(s) were not present in the live resolved event: "
                    + ", ".join(self.missing_selected_market_slugs)
                )
            resolved.markets = {
                condition_id: resolved.markets[condition_id]
                for condition_id in selected_conditions
            }
            resolved.market_payloads = {
                condition_id: resolved.market_payloads[condition_id]
                for condition_id in selected_conditions
                if condition_id in resolved.market_payloads
            }
            if isinstance(resolved.event_payload, dict):
                filtered_payload = dict(resolved.event_payload)
                filtered_payload["markets"] = [
                    resolved.market_payloads[condition_id]
                    for condition_id in selected_conditions
                    if condition_id in resolved.market_payloads
                ]
                resolved.event_payload = filtered_payload
            return resolved

        self._delegate.resolve_input = subset_resolve  # type: ignore[method-assign]
        try:
            return self._delegate.analyze(*args, **kwargs)
        finally:
            self._delegate.resolve_input = original  # type: ignore[method-assign]


def _extract_report_markets(report: Mapping[str, object]) -> list[dict[str, object]]:
    rows = report.get("markets")
    result: list[dict[str, object]] = []
    if isinstance(rows, list):
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            slug = str(item.get("marketSlug") or item.get("slug") or "").strip()
            if not slug:
                continue
            result.append(
                {
                    "marketSlug": slug,
                    "conditionId": str(item.get("conditionId") or ""),
                    "marketTitle": str(item.get("market") or item.get("question") or item.get("title") or ""),
                    "winner": str(item.get("winner") or ""),
                    "source": "saved_event_analysis_markets",
                }
            )
    return result


def _summary_gate(
    selection: Mapping[str, object],
    result: Mapping[str, object],
    report_summary: Mapping[str, object],
    bounds: MeasurementBounds,
) -> str:
    violations = validate_subset_selection(selection, bounds=bounds)
    if violations:
        return "subset_measurement_blocked_scope"
    if not result:
        return "subset_measurement_inconclusive"
    if result.get("gateDecision") == "subset_measurement_blocked_scope":
        return "subset_measurement_blocked_scope"
    if result.get("status") != "completed":
        return "subset_measurement_inconclusive"
    if _runtime_bound_violations(report_summary, bounds):
        return "subset_measurement_blocked_scope"
    return "subset_measurement_complete"


def _analysis_gate(summary: Mapping[str, object]) -> str:
    if summary.get("gateDecision") != "subset_measurement_complete":
        if summary.get("gateDecision") == "subset_measurement_blocked_scope":
            return "subset_measurement_blocked_scope"
        return "subset_measurement_inconclusive"
    markets = _int_or_none(summary.get("analysisMarketCount")) or _int_or_none(summary.get("selectedMarketCount")) or 0
    raw_rows = _int_or_none(summary.get("rawTradeRows")) or 0
    candidate_rows = _int_or_none(summary.get("candidateRows")) or 0
    bottleneck = str(summary.get("dominantBottleneck") or "unknown")
    if markets >= 2 and raw_rows > 0 and candidate_rows > 0 and bottleneck != "unknown":
        return "subset_measurement_complete_patch_rfc_ready"
    if raw_rows > 0:
        return "subset_measurement_complete_more_data_needed"
    return "subset_measurement_inconclusive"


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


def _bottleneck_assessment(summary: Mapping[str, object], aggregate_summary: Mapping[str, object]) -> dict[str, object]:
    dominant = str(summary.get("dominantBottleneck") or "unknown")
    total_seconds = _float_or_none(summary.get("totalSeconds")) or 0.0
    prior_median = _float_or_none(aggregate_summary.get("medianTotalSeconds")) or 0.0
    return {
        "dominantBottleneck": dominant,
        "previousSafeTargetMedianSeconds": prior_median,
        "subsetTotalSeconds": total_seconds,
        "slowerThanPreviousMedian": bool(prior_median and total_seconds > prior_median),
        "interpretation": _bottleneck_interpretation(dominant),
    }


def _pagination_assessment(summary: Mapping[str, object]) -> dict[str, object]:
    truncated = _int_or_none(summary.get("truncatedMarketCount")) or 0
    return {
        "truncationObserved": truncated > 0,
        "truncatedMarketCount": truncated,
        "paginationGate": "pagination_issue_observed" if truncated > 0 else "pagination_subset_clean_not_whole_event_proof",
        "wholeEventCompletenessProven": False,
    }


def _bottleneck_interpretation(bottleneck: str) -> str:
    if bottleneck == "prefetch_wallet_context_seconds":
        return "Wallet-context prefetch dominated the approved subset."
    if bottleneck == "collect_event_trades_seconds":
        return "Trade collection dominated the approved subset."
    if bottleneck == "score_candidates_seconds":
        return "Candidate scoring dominated the approved subset."
    if bottleneck == "unknown":
        return "No dominant stage was identified."
    return f"{bottleneck} dominated the approved subset."


def _subset_disclaimer() -> str:
    return (
        "Subset-only validation run. The selected market allowlist is not the full event, "
        "and results cannot be used as whole-event completeness evidence."
    )


def _load_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _try_load_json_object(path: Path) -> dict[str, object] | None:
    try:
        return _load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _resolve_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def _relative_or_absolute(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _print(payload: Mapping[str, object], *, quiet: bool) -> None:
    if not quiet:
        print(json.dumps(dict(payload), sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
