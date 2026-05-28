#!/usr/bin/env python3
"""Bounded live validation for weak-history near-certain Event Forensic cases.

This tool is validation-only. It selects targets from existing local Event
Forensic artifacts, runs the existing analyzer against a bounded target set,
and writes all fresh outputs under one timestamped validation directory.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import FUNDING_TRACE_MODE_DISABLED, AppConfig, load_runtime_env
from app.side_outcome import UNKNOWN, normalize_cluster_direction, normalize_side_outcome
from tools.event_forensic_weak_history_saved_report_audit import (
    _discover_artifacts,
    _load_artifact_rows,
    evaluate_saved_report_row,
)


REPORT_TYPE = "event_forensic_weak_history_live_rpc_validation"
SCHEMA_VERSION = "event_forensic_weak_history_live_rpc_validation_v1"
DEFAULT_SOURCE_MAX_FILES = 260
DEFAULT_SOURCE_MAX_BYTES = 6_000_000
DEFAULT_SOURCE_MAX_ROWS_PER_FILE = 2_000
NEAR_CERTAINTY_THRESHOLD = Decimal("0.95")
DEFAULT_BOUNDS = {
    "max_events": 3,
    "max_markets_per_event": 8,
    "max_candidate_wallets_per_market": 150,
    "max_total_trade_rows": 50_000,
    "max_wall_time_seconds": 30 * 60,
}
SECRET_ENV_KEYS = {
    "OPENAI_API_KEY",
    "POLYGON_RPC_URL",
    "POLYGON_RPC_URLS",
    "INSPOLY_POLYGON_RPC_URLS",
    "INSPOLY_POLYGON_RPC_URL",
    "CLOB_API_KEY",
    "CLOB_SECRET",
    "CLOB_PASSPHRASE",
    "PRIVATE_KEY",
}
SAFE_ENV_KEYS = (
    "INSPOLY_FUNDING_TRACE_MODE",
    "INSPOLY_DISABLE_LIVE_FUNDING_TRACES",
    "INSPOLY_VALIDATION_MODE",
    "INSPOLY_VALIDATION_ALLOW_NETWORK_FUNDING",
)


@dataclass(frozen=True, slots=True)
class ValidationBounds:
    max_events: int = DEFAULT_BOUNDS["max_events"]
    max_markets_per_event: int = DEFAULT_BOUNDS["max_markets_per_event"]
    max_candidate_wallets_per_market: int = DEFAULT_BOUNDS["max_candidate_wallets_per_market"]
    max_total_trade_rows: int = DEFAULT_BOUNDS["max_total_trade_rows"]
    max_wall_time_seconds: int = DEFAULT_BOUNDS["max_wall_time_seconds"]

    def to_dict(self) -> dict[str, int]:
        return {
            "maxEvents": self.max_events,
            "maxMarketsPerEvent": self.max_markets_per_event,
            "maxCandidateWalletsPerMarket": self.max_candidate_wallets_per_market,
            "maxTotalTradeRows": self.max_total_trade_rows,
            "maxWallTimeSeconds": self.max_wall_time_seconds,
        }


def default_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def runtime_env_status(root: Path = ROOT) -> dict[str, Any]:
    loaded = load_runtime_env(root)
    keys = sorted(set(SAFE_ENV_KEYS).union(SECRET_ENV_KEYS).union(loaded.keys()))
    configured = {key: bool(os.environ.get(key)) for key in keys}
    return {
        "runtimeEnvFilePresent": (root / ".inspoly_runtime.env").exists(),
        "loadedRuntimeEnvKeys": sorted(loaded.keys()),
        "configuredEnvKeys": configured,
        "secretValuesPrinted": False,
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
    }


def collect_candidate_rows(
    root: Path = ROOT,
    *,
    max_files: int = DEFAULT_SOURCE_MAX_FILES,
    max_bytes: int = DEFAULT_SOURCE_MAX_BYTES,
    max_rows_per_file: int = DEFAULT_SOURCE_MAX_ROWS_PER_FILE,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for artifact in _discover_artifacts(root)[:max_files]:
        try:
            size = artifact.stat().st_size
        except OSError:
            continue
        source_type = "synthetic_fixture" if "tests/fixtures" in str(artifact) else "real_local_saved_report"
        if source_type != "real_local_saved_report" or size > max_bytes:
            continue
        loaded = _load_artifact_rows(artifact, max_rows_per_file=max_rows_per_file)
        report = _load_json_object(artifact)
        for row in loaded.get("rows", []):
            if not isinstance(row, Mapping):
                continue
            evaluated = evaluate_saved_report_row(row, artifact, source_type)
            if not evaluated.get("weakHistoryNearCertainLaterWin"):
                continue
            enriched = _enrich_candidate_from_report(row, evaluated, report, artifact)
            candidates.append(enriched)
    return _dedupe_candidates(candidates)


def select_targets(
    candidates: Sequence[Mapping[str, Any]],
    *,
    bounds: ValidationBounds,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        event_slug = str(candidate.get("eventSlug") or candidate.get("event") or UNKNOWN)
        market_key = str(
            candidate.get("conditionId")
            or candidate.get("marketSlug")
            or candidate.get("marketUrl")
            or candidate.get("market")
            or UNKNOWN
        )
        grouped[(event_slug, market_key)].append(candidate)

    event_counts: Counter[str] = Counter()
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for (event_slug, market_key), rows in sorted(
        grouped.items(),
        key=lambda item: (-len(item[1]), item[0][0], item[0][1]),
    ):
        sample = rows[0]
        raw_count = _int_or_none(sample.get("sourceRawTradeCount")) or 0
        candidate_count = _int_or_none(sample.get("sourceCandidateTradeCount")) or len(rows)
        reason = _target_exclusion_reason(
            event_slug,
            event_counts,
            raw_count=raw_count,
            candidate_count=candidate_count,
            bounds=bounds,
        )
        if reason:
            excluded.append(
                {
                    "eventSlug": event_slug,
                    "marketKey": market_key,
                    "sourceArtifactPath": sample.get("artifactPath", ""),
                    "reason": reason,
                    "expectedWeakNearCertainLaterWinRows": len(rows),
                    "sourceRawTradeCount": raw_count,
                    "sourceCandidateTradeCount": candidate_count,
                }
            )
            continue
        input_value = str(sample.get("marketUrl") or sample.get("sourceInputUrl") or "").strip()
        if not input_value:
            excluded.append(
                {
                    "eventSlug": event_slug,
                    "marketKey": market_key,
                    "sourceArtifactPath": sample.get("artifactPath", ""),
                    "reason": "missing_input_url",
                    "expectedWeakNearCertainLaterWinRows": len(rows),
                }
            )
            continue
        event_counts[event_slug] += 1
        selected.append(
            {
                "label": f"weak_history_near_certainty_{len(selected) + 1}",
                "mode": "event_forensic",
                "inputType": "polymarket_url",
                "inputValue": input_value,
                "sourceArtifactPath": sample.get("artifactPath", ""),
                "eventSlug": event_slug,
                "marketKey": market_key,
                "marketTitle": sample.get("market", ""),
                "marketUrl": sample.get("marketUrl", ""),
                "conditionId": sample.get("conditionId", ""),
                "analysisScope": sample.get("analysisScope") or "event",
                "minNotional": sample.get("sourceMinNotional") or "10000.00",
                "scopeSettings": {
                    "includeRelatedMarkets": False,
                    "includeBlockchain": False,
                    "fundingTraceMode": FUNDING_TRACE_MODE_DISABLED,
                    "analysisScope": sample.get("analysisScope") or "event",
                    "selectedConditionId": sample.get("selectedConditionId") or "",
                    "selectedMarketSlug": sample.get("selectedMarketSlug") or "",
                },
                "expectedSignals": {
                    "weakHistoryNearCertainLaterWinRows": len(rows),
                    "candidateTradeKeys": sorted({str(row.get("tradeKey") or "") for row in rows if row.get("tradeKey")}),
                    "wallets": sorted({str(row.get("wallet") or "") for row in rows if row.get("wallet")}),
                    "winnerRanks": sorted({_int_or_none(row.get("winnerRank")) or 0 for row in rows}),
                    "sourceRawTradeCount": raw_count,
                    "sourceCandidateTradeCount": candidate_count,
                },
                "boundsApplied": bounds.to_dict(),
                "reasonForSelection": (
                    "Existing saved Event Forensic artifact contains real weak-history near-certain later-winning rows."
                ),
            }
        )
    return selected, excluded


def run_live_targets(
    targets: Sequence[Mapping[str, Any]],
    *,
    output_dir: Path,
    bounds: ValidationBounds,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    for index, target in enumerate(targets, start=1):
        remaining = bounds.max_wall_time_seconds - int(time.monotonic() - started)
        if remaining <= 0:
            results.append(_aborted_result(target, "live_rpc_validation_blocked_scope_exceeded", "max_wall_time_elapsed"))
            break
        timeout_seconds = min(remaining, bounds.max_wall_time_seconds)
        results.append(_run_one_target_in_process(dict(target), output_dir=output_dir, timeout_seconds=timeout_seconds, index=index))
    return results


def build_summary(
    *,
    output_dir: Path,
    bounds: ValidationBounds,
    env_status: Mapping[str, Any],
    selected_targets: Sequence[Mapping[str, Any]],
    excluded_targets: Sequence[Mapping[str, Any]],
    live_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    report_summaries = [analyze_report_result(result, bounds=bounds) for result in live_results]
    status_counts = Counter(str(result.get("status") or "unknown") for result in live_results)
    total_raw_rows = sum(_int_or_none(item.get("rawTradeCount")) or 0 for item in report_summaries)
    weak_cases = [case for item in report_summaries for case in item.get("weakHistoryNearCertainLaterWinCases", [])]
    high_rank_cases = [case for case in weak_cases if (_int_or_none(case.get("displayRank")) or 9999) <= 10]
    missing_reducer_cases = [
        case
        for case in weak_cases
        if not case.get("weakHistoryReducerPresent") or not case.get("nearCertaintyReducerPresent")
    ]
    if total_raw_rows > bounds.max_total_trade_rows:
        gate = "live_rpc_validation_blocked_scope_exceeded"
    elif status_counts.get("aborted_timeout") or status_counts.get("aborted_scope_exceeded"):
        gate = "live_rpc_validation_blocked_scope_exceeded"
    elif any(str(result.get("status") or "").startswith("blocked_rate_limited") for result in live_results):
        gate = "live_rpc_validation_blocked_rate_limited"
    elif not selected_targets:
        gate = "weak_history_live_validation_inconclusive"
    elif not any(result.get("status") == "completed" for result in live_results):
        gate = "weak_history_live_validation_inconclusive"
    elif missing_reducer_cases:
        gate = "weak_history_live_validation_bug_found"
    elif high_rank_cases:
        gate = "weak_history_live_validation_needs_model_rfc"
    elif weak_cases:
        gate = "weak_history_live_validation_clean"
    else:
        gate = "weak_history_live_validation_inconclusive"
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "outputDir": str(output_dir),
        "networkUsed": bool(live_results),
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "appStorageMutated": False,
        "productionIntegration": False,
        "bounds": bounds.to_dict(),
        "envConfigStatus": dict(env_status),
        "targetSelection": {
            "selectedTargetCount": len(selected_targets),
            "excludedTargetCount": len(excluded_targets),
            "selectedEvents": sorted({str(item.get("eventSlug") or UNKNOWN) for item in selected_targets}),
            "selectedMarkets": sorted({str(item.get("marketKey") or UNKNOWN) for item in selected_targets}),
            "targets": [dict(item) for item in selected_targets],
            "excludedTargets": [dict(item) for item in excluded_targets],
        },
        "liveResults": [dict(item) for item in live_results],
        "reportSummaries": report_summaries,
        "summary": {
            "gateDecision": gate,
            "selectedEventCount": len({str(item.get("eventSlug") or UNKNOWN) for item in selected_targets}),
            "selectedMarketCount": len({str(item.get("marketKey") or UNKNOWN) for item in selected_targets}),
            "completedTargetCount": status_counts.get("completed", 0),
            "targetStatusCounts": dict(sorted(status_counts.items())),
            "totalRawTradeRows": total_raw_rows,
            "totalCandidateRows": sum(_int_or_none(item.get("candidateTradeCount")) or 0 for item in report_summaries),
            "weakHistoryRows": sum(_int_or_none(item.get("weakHistoryRows")) or 0 for item in report_summaries),
            "nearCertainEconomicRows": sum(_int_or_none(item.get("nearCertainEconomicRows")) or 0 for item in report_summaries),
            "weakHistoryNearCertainLaterWinRows": len(weak_cases),
            "highRankWeakHistoryNearCertainLaterWinRows": len(high_rank_cases),
            "missingExpectedReducerRows": len(missing_reducer_cases),
            "phase2EconomicProbabilityMismatches": sum(
                _int_or_none(item.get("phase2EconomicProbabilityMismatches")) or 0 for item in report_summaries
            ),
            "phase4ClusterDirectionMismatches": sum(
                _int_or_none(item.get("phase4ClusterDirectionMismatches")) or 0 for item in report_summaries
            ),
        },
        "interpretation": _summary_interpretation(gate, weak_cases, high_rank_cases),
    }


def analyze_report_result(result: Mapping[str, Any], *, bounds: ValidationBounds) -> dict[str, Any]:
    path = Path(str(result.get("eventAnalysisJsonPath") or ""))
    if result.get("status") != "completed" or not path.exists():
        return {
            "targetLabel": result.get("label", ""),
            "status": result.get("status", "unknown"),
            "rawTradeCount": 0,
            "candidateTradeCount": 0,
            "weakHistoryNearCertainLaterWinCases": [],
            "analysisNotes": ["target_not_completed_or_report_missing"],
        }
    report = _load_json_object(path)
    summary = report.get("summary") if isinstance(report, Mapping) else {}
    if not isinstance(summary, Mapping):
        summary = {}
    display_rows = _rows_from_report(report, "display_trades")
    suspicious_rows = _rows_from_report(report, "suspicious_trades")
    rows_by_id: dict[str, tuple[int | None, Mapping[str, Any]]] = {}
    for rank, row in enumerate(display_rows, start=1):
        rows_by_id[_row_key(row, rank)] = (rank, row)
    for row in suspicious_rows:
        key = _row_key(row, None)
        rows_by_id.setdefault(key, (None, row))
    evaluated = [_evaluate_live_row(row, display_rank=rank) for rank, row in rows_by_id.values()]
    weak_cases = [row for row in evaluated if row.get("weakHistoryNearCertainLaterWin")]
    phase2_mismatch = sum(1 for row in evaluated if row.get("phase2EconomicProbabilityStatus") == "mismatch")
    phase4_mismatch = sum(1 for row in evaluated if row.get("phase4ClusterDirectionStatus") == "mismatch")
    raw_trade_count = _int_or_none(summary.get("raw_trade_count") or summary.get("rawTradeCount")) or 0
    notes: list[str] = []
    if raw_trade_count > bounds.max_total_trade_rows:
        notes.append("raw_trade_count_exceeds_bound")
    if not weak_cases:
        notes.append("weak_history_near_certainty_later_win_not_reproduced")
    return {
        "targetLabel": result.get("label", ""),
        "status": result.get("status", "unknown"),
        "eventAnalysisJsonPath": str(path),
        "rawTradeCount": raw_trade_count,
        "candidateTradeCount": _int_or_none(summary.get("candidate_trade_count") or summary.get("candidateTradeCount")) or 0,
        "displayTradeCount": len(display_rows),
        "suspiciousTradeCount": len(suspicious_rows),
        "weakHistoryRows": sum(1 for row in evaluated if row.get("weakHistoryClassification") == "weak_history"),
        "nearCertainEconomicRows": sum(1 for row in evaluated if row.get("nearCertainEconomicEntry")),
        "weakHistoryNearCertainLaterWinCases": weak_cases,
        "phase2EconomicProbabilityMismatches": phase2_mismatch,
        "phase4ClusterDirectionMismatches": phase4_mismatch,
        "analysisNotes": notes,
    }


def write_markdown_report(path: Path, summary: Mapping[str, Any]) -> None:
    data = dict(summary)
    aggregate = data.get("summary", {}) if isinstance(data.get("summary"), Mapping) else {}
    target_selection = data.get("targetSelection", {}) if isinstance(data.get("targetSelection"), Mapping) else {}
    report_summaries = data.get("reportSummaries", []) if isinstance(data.get("reportSummaries"), list) else []
    lines = [
        "# Event Forensic Weak-History Live/RPC Validation",
        "",
        "This is a bounded measurement-only validation. It does not approve scorer tuning, runtime migration, Phase 3 capital-at-risk work, or gate changes.",
        "",
        "## Gate Decision",
        "",
        f"- Gate: `{aggregate.get('gateDecision', 'unknown')}`",
        f"- Output directory: `{data.get('outputDir', '')}`",
        f"- Network used: {data.get('networkUsed', False)}",
        f"- Runtime behavior changed: {data.get('runtimeBehaviorChanged', False)}",
        f"- Saved artifacts mutated: {data.get('savedArtifactsMutated', False)}",
        f"- App storage mutated: {data.get('appStorageMutated', False)}",
        "",
        "## Bounds Used",
        "",
    ]
    for key, value in (data.get("bounds") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Env/Config Status",
            "",
            "- Secret values were not printed.",
            f"- Runtime env file present: {data.get('envConfigStatus', {}).get('runtimeEnvFilePresent', False)}",
            f"- RPC configured: {data.get('envConfigStatus', {}).get('rpcConfigured', False)}",
            f"- CLOB/private auth configured but unused: {data.get('envConfigStatus', {}).get('clobAuthConfiguredButUnused', False)}",
            "",
            "## Targets",
            "",
            f"- Selected events: {aggregate.get('selectedEventCount', 0)}",
            f"- Selected markets: {aggregate.get('selectedMarketCount', 0)}",
            f"- Selected target count: {target_selection.get('selectedTargetCount', 0)}",
            f"- Excluded target count: {target_selection.get('excludedTargetCount', 0)}",
            "",
        ]
    )
    for target in target_selection.get("targets", []):
        lines.extend(
            [
                f"### {target.get('label', 'target')}",
                "",
                f"- Event: `{target.get('eventSlug', '')}`",
                f"- Market: {target.get('marketTitle', '')}",
                f"- Input: {target.get('inputValue', '')}",
                f"- Source artifact: `{target.get('sourceArtifactPath', '')}`",
                f"- Reason: {target.get('reasonForSelection', '')}",
                "",
            ]
        )
    lines.extend(
        [
            "## Row Counts",
            "",
            f"- Completed targets: {aggregate.get('completedTargetCount', 0)}",
            f"- Raw trade rows loaded: {aggregate.get('totalRawTradeRows', 0)}",
            f"- Candidate rows: {aggregate.get('totalCandidateRows', 0)}",
            f"- Weak-history rows: {aggregate.get('weakHistoryRows', 0)}",
            f"- Near-certain economic rows: {aggregate.get('nearCertainEconomicRows', 0)}",
            f"- Weak-history near-certain later-win rows: {aggregate.get('weakHistoryNearCertainLaterWinRows', 0)}",
            f"- High-rank weak-history near-certain later-win rows: {aggregate.get('highRankWeakHistoryNearCertainLaterWinRows', 0)}",
            "",
            "## Findings",
            "",
            f"- {data.get('interpretation', '')}",
            f"- Phase 2 economic probability mismatches: {aggregate.get('phase2EconomicProbabilityMismatches', 0)}",
            f"- Phase 4 cluster direction mismatches: {aggregate.get('phase4ClusterDirectionMismatches', 0)}",
            "",
            "## Report Summaries",
            "",
            "```json",
            json.dumps(report_summaries, indent=2, sort_keys=True),
            "```",
            "",
            "## Remaining Scope Blocks",
            "",
            "- No scorer tuning was performed.",
            "- Phase 3 capital-at-risk remains blocked.",
            "- Strong Risk, HER, funding, candidate admission, storage, and UI sorting were not changed.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--timestamp", default=default_timestamp())
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--select-only", action="store_true")
    parser.add_argument("--max-events", type=int, default=DEFAULT_BOUNDS["max_events"])
    parser.add_argument("--max-markets-per-event", type=int, default=DEFAULT_BOUNDS["max_markets_per_event"])
    parser.add_argument(
        "--max-candidate-wallets-per-market",
        type=int,
        default=DEFAULT_BOUNDS["max_candidate_wallets_per_market"],
    )
    parser.add_argument("--max-total-trade-rows", type=int, default=DEFAULT_BOUNDS["max_total_trade_rows"])
    parser.add_argument("--max-wall-time-seconds", type=int, default=DEFAULT_BOUNDS["max_wall_time_seconds"])
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else root / "validation_outputs" / f"event_forensic_weak_history_live_rpc_{args.timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    bounds = ValidationBounds(
        max_events=args.max_events,
        max_markets_per_event=args.max_markets_per_event,
        max_candidate_wallets_per_market=args.max_candidate_wallets_per_market,
        max_total_trade_rows=args.max_total_trade_rows,
        max_wall_time_seconds=args.max_wall_time_seconds,
    )
    env_status = runtime_env_status(root)
    candidates = collect_candidate_rows(root)
    selected_targets, excluded_targets = select_targets(candidates, bounds=bounds)
    target_selection = {
        "reportType": f"{REPORT_TYPE}_target_selection",
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "bounds": bounds.to_dict(),
        "envConfigStatus": env_status,
        "candidateRowsFound": len(candidates),
        "selectedTargets": selected_targets,
        "excludedTargets": excluded_targets,
        "networkUsed": False,
        "savedArtifactsMutated": False,
    }
    write_json(output_dir / "target_selection.json", target_selection)
    write_json(
        root / "validation_outputs" / f"event_forensic_weak_history_live_rpc_TARGET_SELECTION_{args.timestamp}.json",
        target_selection,
    )
    live_results: list[dict[str, Any]] = []
    if not args.select_only:
        live_results = run_live_targets(selected_targets, output_dir=output_dir, bounds=bounds)
    summary = build_summary(
        output_dir=output_dir,
        bounds=bounds,
        env_status=env_status,
        selected_targets=selected_targets,
        excluded_targets=excluded_targets,
        live_results=live_results,
    )
    write_json(output_dir / "summary.json", summary)
    report_path = root / "docs" / f"inspoly_event_forensic_weak_history_live_rpc_validation_{args.timestamp[:8]}.md"
    write_markdown_report(report_path, summary)
    print(json.dumps({"summaryPath": str(output_dir / "summary.json"), "reportPath": str(report_path), "gate": summary["summary"]["gateDecision"]}, sort_keys=True))
    return 0


def _run_one_target_in_process(
    target: dict[str, Any],
    *,
    output_dir: Path,
    timeout_seconds: int,
    index: int,
) -> dict[str, Any]:
    ctx = mp.get_context("spawn")
    queue: mp.Queue = ctx.Queue()
    process = ctx.Process(
        target=_live_worker_entry,
        args=(target, str(output_dir), index, queue),
        daemon=True,
    )
    started = time.monotonic()
    process.start()
    process.join(timeout=max(1, timeout_seconds))
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        return _aborted_result(target, "aborted_timeout", "max_wall_time_elapsed")
    payload: dict[str, Any] | None = None
    while not queue.empty():
        message = queue.get()
        if isinstance(message, Mapping):
            payload = dict(message)
    if payload is None:
        return {
            **_target_result_base(target),
            "status": "failed_runtime_error",
            "error": f"worker_exit_{process.exitcode}",
            "wallClockSeconds": round(time.monotonic() - started, 3),
        }
    payload["wallClockSeconds"] = round(time.monotonic() - started, 3)
    return payload


def _live_worker_entry(target: dict[str, Any], output_dir_raw: str, index: int, queue: Any) -> None:
    try:
        output_dir = Path(output_dir_raw)
        worker_dir = output_dir / "live_runs" / f"target_{index:02d}"
        data_dir = worker_dir / "isolated_app_data"
        config = AppConfig(
            data_dir=data_dir,
            db_path=data_dir / "event_forensic_validation.sqlite3",
            reports_dir=worker_dir / "reports",
            outputs_dir=worker_dir / "event_forensic_outputs",
            default_lookback="event",
            max_trade_pages=40,
            trade_page_size=100,
        )
        config.ensure_dirs()
        from app.event_forensic import EventForensicAnalyzer
        from app.polymarket import PolymarketClient
        from app.storage import Storage

        storage = Storage(config.db_path)
        storage.init()
        analyzer = EventForensicAnalyzer(PolymarketClient(), storage, config)
        scope = target.get("scopeSettings") if isinstance(target.get("scopeSettings"), Mapping) else {}
        report = analyzer.analyze(
            str(target.get("inputValue") or ""),
            config.reports_dir,
            min_notional=_decimal_or_none(target.get("minNotional")),
            include_related_markets=False,
            include_blockchain=False,
            funding_trace_mode=FUNDING_TRACE_MODE_DISABLED,
            analysis_scope=_optional_str(scope.get("analysisScope")),
            selected_condition_id=_optional_str(scope.get("selectedConditionId")),
            selected_market_slug=_optional_str(scope.get("selectedMarketSlug")),
        )
        export_files = report.get("export_files") if isinstance(report, Mapping) else {}
        if not isinstance(export_files, Mapping):
            export_files = {}
        summary = report.get("summary") if isinstance(report, Mapping) else {}
        if not isinstance(summary, Mapping):
            summary = {}
        queue.put(
            {
                **_target_result_base(target),
                "status": "completed",
                "eventAnalysisJsonPath": str(export_files.get("event_analysis_json_path") or ""),
                "reportJsonPath": str(export_files.get("report_json_path") or ""),
                "reportMarkdownPath": str(export_files.get("event_report_md_path") or ""),
                "rawTradeCount": _int_or_none(summary.get("raw_trade_count") or summary.get("rawTradeCount")) or 0,
                "candidateTradeCount": _int_or_none(summary.get("candidate_trade_count") or summary.get("candidateTradeCount")) or 0,
                "fundingTraceMode": "disabled",
                "isolatedDataDir": str(data_dir),
                "storageScope": "validation_output_dir_only",
            }
        )
    except Exception as exc:
        queue.put({**_target_result_base(target), "status": "failed_runtime_error", "error": f"{type(exc).__name__}: {exc}"})


def _evaluate_live_row(row: Mapping[str, Any], *, display_rank: int | None) -> dict[str, Any]:
    order_side = _first(row, "rawOrderSide", "raw_order_side", "orderSide", "order_side")
    token_outcome = _first(row, "rawTokenOutcome", "raw_token_outcome", "side", "outcome")
    raw_price = _first(row, "rawTokenPrice", "raw_token_price", "price", "entryPrice", "entry_probability")
    normalized = normalize_side_outcome(order_side, token_outcome, raw_price)
    cluster = normalize_cluster_direction(order_side, token_outcome, raw_price)
    later_won = _boolish(_first(row, "laterWon", "later_won", "laterCorrect", "later_correct"))
    winner_rank = _int_or_none(_first(row, "winnerRank", "winner_rank", "winningRank", "winning_rank"))
    weak_history = _weak_history_classification(row)
    near_certain = normalized.economic_side_probability is not None and normalized.economic_side_probability >= NEAR_CERTAINTY_THRESHOLD
    saved_probability = _decimal_or_none(_first(row, "economicSideProbability", "economic_side_probability", "modelProbability"))
    saved_cluster = str(_first(row, "clusterDirection", "cluster_direction", "modelEconomicDirection", "model_economic_direction") or "")
    phase2_status = _comparison_status(saved_probability, normalized.economic_side_probability)
    phase4_status = _cluster_comparison_status(saved_cluster, cluster.cluster_direction)
    weak_reducer_present = weak_history == "weak_history"
    text = _row_search_text(row)
    near_reducer_present = "near_certainty" in text or "near certainty" in text
    return {
        "tradeKey": str(_first(row, "id", "tradeId", "trade_id", "transactionHash", "uniqueTradeKey") or ""),
        "wallet": str(_first(row, "wallet", "proxyWallet", "address") or ""),
        "market": str(_first(row, "market", "marketTitle", "selectedMarketTitle") or ""),
        "eventSlug": str(_first(row, "parentEventSlug", "eventSlug", "event") or ""),
        "rawOrderSide": normalized.raw_order_side,
        "rawTokenOutcome": normalized.raw_token_outcome,
        "rawTokenPrice": _decimal_text(normalized.raw_token_price),
        "economicSide": normalized.economic_side,
        "economicSideProbability": _decimal_text(normalized.economic_side_probability),
        "clusterDirection": cluster.cluster_direction,
        "displayRank": display_rank if display_rank is not None else "not_in_display_rows",
        "eventForensicScore": _int_or_none(_first(row, "eventForensicScore", "event_forensic_score")) or 0,
        "existingModelClass": str(_first(row, "existingModelClass", "severity") or ""),
        "strongRiskGatePassed": str(_first(row, "strongRiskGatePassed") or ""),
        "laterWon": later_won if later_won is not None else UNKNOWN,
        "winnerRank": winner_rank if winner_rank is not None else UNKNOWN,
        "weakHistoryClassification": weak_history,
        "nearCertainEconomicEntry": near_certain,
        "weakHistoryNearCertainLaterWin": bool(weak_history == "weak_history" and near_certain and later_won is True),
        "weakHistoryReducerPresent": weak_reducer_present,
        "nearCertaintyReducerPresent": near_reducer_present,
        "phase2EconomicProbabilityStatus": phase2_status,
        "phase4ClusterDirectionStatus": phase4_status,
        "summary": str(row.get("summary") or "")[:500],
    }


def _enrich_candidate_from_report(
    row: Mapping[str, Any],
    evaluated: Mapping[str, Any],
    report: Mapping[str, Any],
    artifact: Path,
) -> dict[str, Any]:
    analysis_settings = report.get("analysis_settings") if isinstance(report.get("analysis_settings"), Mapping) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    event = report.get("event") if isinstance(report.get("event"), Mapping) else {}
    condition_id = _first(row, "conditionId", "selectedConditionId") or _first_market(report, "conditionId")
    return {
        **dict(evaluated),
        "artifactPath": _relative(ROOT, artifact),
        "sourceInputUrl": str(report.get("input_url") or report.get("inputUrl") or ""),
        "eventSlug": str(_first(row, "parentEventSlug", "eventSlug", "event") or event.get("slug") or ""),
        "marketSlug": str(_first(row, "marketSlug", "selectedMarketSlug") or _first_market(report, "slug") or ""),
        "marketUrl": str(_first(row, "marketUrl") or _first_market(report, "marketUrl") or _first_market(report, "url") or report.get("input_url") or ""),
        "conditionId": str(condition_id or ""),
        "selectedConditionId": str(_first(row, "selectedConditionId") or ""),
        "selectedMarketSlug": str(_first(row, "selectedMarketSlug") or ""),
        "sourceMinNotional": str(analysis_settings.get("min_notional") or "10000.00"),
        "sourceRawTradeCount": _int_or_none(summary.get("raw_trade_count")) or 0,
        "sourceCandidateTradeCount": _int_or_none(summary.get("candidate_trade_count")) or 0,
        "sourceAnalysisMarketCount": _int_or_none(summary.get("analysis_market_count")) or 0,
        "sourceTotalEventMarketCount": _int_or_none(summary.get("total_event_market_count")) or 0,
    }


def _target_exclusion_reason(
    event_slug: str,
    event_counts: Counter[str],
    *,
    raw_count: int,
    candidate_count: int,
    bounds: ValidationBounds,
) -> str:
    if len(event_counts) >= bounds.max_events and event_slug not in event_counts:
        return "max_events_bound"
    if event_counts[event_slug] >= bounds.max_markets_per_event:
        return "max_markets_per_event_bound"
    if raw_count > bounds.max_total_trade_rows:
        return "max_total_trade_rows_bound"
    if candidate_count > bounds.max_candidate_wallets_per_market:
        return "max_candidate_wallets_per_market_bound"
    return ""


def _dedupe_candidates(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        key = (
            str(candidate.get("artifactPath") or ""),
            str(candidate.get("tradeKey") or ""),
            str(candidate.get("wallet") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(candidate))
    return result


def _rows_from_report(report: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = report.get(key)
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _row_key(row: Mapping[str, Any], rank: int | None) -> str:
    return str(_first(row, "id", "tradeId", "trade_id", "transactionHash", "uniqueTradeKey") or f"rank:{rank}")


def _weak_history_classification(row: Mapping[str, Any]) -> str:
    text = _row_search_text(row)
    if "weak_wallet_track_record" in text or "weak economic history" in text or "weak economic track" in text:
        return "weak_history"
    if "history is not weak" in text or "strong track record" in text:
        return "not_weak_history"
    return UNKNOWN


def _row_search_text(row: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "eventForensicFlags",
        "event_forensic_flags",
        "eventForensicReducers",
        "reducesConcern",
        "summary",
        "strongRiskSuppressorConflictReasons",
    ):
        value = row.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value not in (None, ""):
            parts.append(str(value))
    raw = row.get("rawMetrics")
    if isinstance(raw, Mapping):
        parts.extend(str(raw.get(key) or "") for key in ("wallet_economic_history_note", "economic_history_note", "weak_wallet_track_record"))
    return " ".join(parts).lower()


def _comparison_status(saved: Decimal | None, computed: Decimal | None) -> str:
    if saved is None and computed is None:
        return "unknown"
    if saved is None or computed is None:
        return "not_comparable"
    return "match" if abs(saved - computed) <= Decimal("0.000001") else "mismatch"


def _cluster_comparison_status(saved: str, computed: str) -> str:
    if not saved or saved == UNKNOWN or computed == UNKNOWN:
        return "unknown"
    return "match" if saved == computed else "mismatch"


def _summary_interpretation(gate: str, weak_cases: Sequence[Mapping[str, Any]], high_rank_cases: Sequence[Mapping[str, Any]]) -> str:
    if gate == "weak_history_live_validation_clean":
        return "Fresh bounded output reproduced weak-history near-certain later-win rows without high-rank or missing-reducer evidence."
    if gate == "weak_history_live_validation_needs_model_rfc":
        return (
            "Fresh bounded output includes weak-history near-certain later-win rows in high review ranks. "
            "Reducers appear present, so this is a model-policy question rather than a narrow runtime bug."
        )
    if gate == "weak_history_live_validation_bug_found":
        return "Fresh bounded output found weak-history near-certain later-win rows missing expected reducer evidence."
    if gate == "live_rpc_validation_blocked_scope_exceeded":
        return "The bounded validation exceeded or approached configured safety bounds and should be rerun with a narrower target."
    if weak_cases or high_rank_cases:
        return "Fresh bounded output produced relevant rows, but the evidence was insufficient for a clean gate."
    return "Fresh bounded output did not reproduce enough weak-history near-certain later-win evidence to close the blocker."


def _target_result_base(target: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "label": target.get("label", ""),
        "inputValue": target.get("inputValue", ""),
        "eventSlug": target.get("eventSlug", ""),
        "marketKey": target.get("marketKey", ""),
        "sourceArtifactPath": target.get("sourceArtifactPath", ""),
    }


def _aborted_result(target: Mapping[str, Any], status: str, reason: str) -> dict[str, Any]:
    return {**_target_result_base(target), "status": status, "error": reason}


def _load_json_object(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _first_market(report: Mapping[str, Any], key: str) -> Any:
    markets = report.get("markets")
    if not isinstance(markets, list):
        return None
    for item in markets:
        if isinstance(item, Mapping) and item.get(key) not in (None, ""):
            return item.get(key)
    return None


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace("%", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _decimal_text(value: Decimal | None) -> str:
    return str(value) if value is not None else UNKNOWN


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _relative(base: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
