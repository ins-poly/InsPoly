#!/usr/bin/env python3
"""Decompose an existing subset-only Event Forensic performance measurement.

This tool is offline-only. It reads saved validation output and optional local
report artifacts, then writes a compact RFC evidence payload. It does not make
network calls, run Event Forensic analysis, mutate storage, or change scoring.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.event_forensic_performance import summarize_timing_costs


REPORT_TYPE = "event_forensic_subset_bottleneck_decomposition"
SCHEMA_VERSION = "event_forensic_subset_bottleneck_decomposition_v1"
DEFAULT_SUMMARY = Path("validation_outputs/event_forensic_subset_measurement_20260525_181811/summary.json")
DEFAULT_AGGREGATE = Path("validation_outputs/event_forensic_performance_measurement_aggregate_20260525.json")
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_subset_bottleneck_decomposition_20260525.json")


def build_bottleneck_decomposition(
    *,
    subset_summary: Mapping[str, object],
    aggregate_payload: Mapping[str, object] | None = None,
    report_payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    summary = subset_summary.get("summary") if isinstance(subset_summary.get("summary"), Mapping) else {}
    live_result = subset_summary.get("liveResult") if isinstance(subset_summary.get("liveResult"), Mapping) else {}
    report_summary = subset_summary.get("reportSummary") if isinstance(subset_summary.get("reportSummary"), Mapping) else {}
    aggregate_summary = (
        aggregate_payload.get("summary")
        if isinstance(aggregate_payload, Mapping) and isinstance(aggregate_payload.get("summary"), Mapping)
        else {}
    )
    timings = _timings_from(summary, live_result, report_summary, report_payload)
    candidate_rows = _int_value(summary.get("candidateRows") or report_summary.get("candidateTradeCount"))
    candidate_wallets = _int_value(summary.get("candidateWalletCount") or report_summary.get("candidateWalletCount"))
    market_count = _int_value(summary.get("analysisMarketCount") or report_summary.get("analysisMarketCount"))
    raw_rows = _int_value(summary.get("rawTradeRows") or report_summary.get("rawTradeCount"))
    timing_costs = summarize_timing_costs(
        timings,
        candidate_rows=candidate_rows,
        candidate_wallets=candidate_wallets,
        market_count=market_count,
    )
    market_contributions = _market_contributions(report_payload)
    repeated_wallet_opportunities = max(0, candidate_rows - candidate_wallets)
    previous_median = _float_value(aggregate_summary.get("medianTotalSeconds"))
    total_seconds = _float_value(summary.get("totalSeconds") or report_summary.get("totalSeconds"))
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "storageMutated": False,
        "wholeEventCompletenessClaim": False,
        "evidenceGate": "high_density_subset_evidence_accepted_for_rfc",
        "sourceGate": str(summary.get("gateDecision") or ""),
        "runtimeBoundViolations": list(summary.get("runtimeBoundViolations", []))
        if isinstance(summary.get("runtimeBoundViolations"), list)
        else list(live_result.get("runtimeBoundViolations", []))
        if isinstance(live_result.get("runtimeBoundViolations"), list)
        else [],
        "event": {
            "eventSlug": str(summary.get("eventSlug") or live_result.get("eventSlug") or ""),
            "subsetOnly": True,
            "selectedMarketCount": market_count,
            "liveResolvedMarketCount": _int_value(summary.get("liveResolvedMarketCount") or live_result.get("liveResolvedMarketCount")),
        },
        "counts": {
            "rawTradeRows": raw_rows,
            "candidateRows": candidate_rows,
            "candidateWallets": candidate_wallets,
            "truncatedMarketCount": _int_value(summary.get("truncatedMarketCount") or report_summary.get("truncatedMarketCount")),
            "candidateRowsPerWallet": timing_costs["candidateRowsPerWallet"],
            "candidateRowsPerMarket": timing_costs["candidateRowsPerMarket"],
            "candidateWalletsPerMarket": timing_costs["candidateWalletsPerMarket"],
            "repeatedWalletCandidateOpportunities": repeated_wallet_opportunities,
        },
        "timings": {
            "totalSeconds": total_seconds,
            "previousSafeTargetMedianSeconds": previous_median,
            "subsetVsPreviousMedianMultiple": round(total_seconds / previous_median, 3) if previous_median else 0.0,
            **timing_costs,
        },
        "marketContributions": market_contributions,
        "classification": _classification(timing_costs, candidate_rows, candidate_wallets, market_count),
        "patchSignals": _patch_signals(timing_costs, repeated_wallet_opportunities, market_contributions),
        "claimsAllowed": [
            "performance_bottleneck_evidence_for_this_subset",
            "candidate_density_evidence_for_future_rfc",
            "pagination_truncation_observed_within_subset",
        ],
        "claimsNotAllowed": [
            "whole_event_completeness",
            "production_tuning_approval",
            "candidate_quality_for_excluded_markets",
            "scorer_weight_or_threshold_change",
            "candidate_admission_or_gate_change",
        ],
    }


def load_summary_with_report(summary_path: str | Path) -> tuple[dict[str, object], dict[str, object] | None]:
    summary = load_json_object(summary_path)
    live_result = summary.get("liveResult") if isinstance(summary.get("liveResult"), Mapping) else {}
    report_path = Path(str(live_result.get("eventAnalysisJsonPath") or ""))
    report = load_json_object(report_path) if report_path.is_file() else None
    return summary, report


def load_json_object(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--aggregate", default=str(DEFAULT_AGGREGATE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    summary, report = load_summary_with_report(args.summary)
    aggregate = load_json_object(args.aggregate) if Path(args.aggregate).exists() else None
    payload = build_bottleneck_decomposition(
        subset_summary=summary,
        aggregate_payload=aggregate,
        report_payload=report,
    )
    write_json(payload, args.output)
    if not args.quiet:
        print(json.dumps({"output": args.output, "gate": payload["evidenceGate"]}, sort_keys=True))
    return 0


def _timings_from(
    summary: Mapping[str, object],
    live_result: Mapping[str, object],
    report_summary: Mapping[str, object],
    report_payload: Mapping[str, object] | None,
) -> dict[str, object]:
    if isinstance(report_payload, Mapping) and isinstance(report_payload.get("performance"), Mapping):
        return dict(report_payload["performance"])
    if isinstance(report_summary.get("timings"), Mapping):
        return dict(report_summary["timings"])
    if isinstance(live_result.get("timings"), Mapping):
        return dict(live_result["timings"])
    return {k: summary.get(k) for k in ("totalSeconds", "score_candidates_seconds", "prefetch_wallet_context_seconds")}


def _market_contributions(report_payload: Mapping[str, object] | None) -> list[dict[str, object]]:
    if not isinstance(report_payload, Mapping) or not isinstance(report_payload.get("markets"), list):
        return []
    markets = [row for row in report_payload["markets"] if isinstance(row, Mapping)]
    total_candidates = sum(_int_value(row.get("candidateTradeCount")) for row in markets)
    total_trades = sum(_int_value(row.get("tradeCount")) for row in markets)
    result = []
    for row in markets:
        candidate_count = _int_value(row.get("candidateTradeCount"))
        trade_count = _int_value(row.get("tradeCount"))
        result.append(
            {
                "marketSlug": str(row.get("marketSlug") or row.get("slug") or ""),
                "conditionId": str(row.get("conditionId") or ""),
                "market": str(row.get("market") or row.get("question") or ""),
                "tradeCount": trade_count,
                "candidateTradeCount": candidate_count,
                "candidateShare": _ratio(candidate_count, total_candidates),
                "tradeShare": _ratio(trade_count, total_trades),
                "truncatedLikely": True,
            }
        )
    return sorted(result, key=lambda item: int(item["candidateTradeCount"]), reverse=True)


def _classification(
    timing_costs: Mapping[str, object],
    candidate_rows: int,
    candidate_wallets: int,
    market_count: int,
) -> dict[str, object]:
    dominant = str(timing_costs.get("dominantStage") or "unknown")
    return {
        "dominantBottleneck": dominant,
        "scoringLoopDominant": dominant == "score_candidates_seconds",
        "walletPrefetchSecondary": _float_value(timing_costs.get("prefetchShareOfTotal")) >= 0.2,
        "dataDensityHigh": candidate_rows >= 10_000 or _ratio(candidate_wallets, market_count) > 150,
        "repeatedWalletOpportunityHigh": _ratio(candidate_rows, candidate_wallets) >= 2.0,
    }


def _patch_signals(
    timing_costs: Mapping[str, object],
    repeated_wallet_opportunities: int,
    market_contributions: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    score_share = _float_value(timing_costs.get("scoreShareOfTotal"))
    prefetch_share = _float_value(timing_costs.get("prefetchShareOfTotal"))
    return {
        "scorerInputContextMemoization": score_share >= 0.4,
        "walletContextPrefetchDedupReuse": prefetch_share >= 0.2,
        "candidateChunkingForOperatorFeedback": repeated_wallet_opportunities > 0,
        "timingInstrumentation": True,
        "replaySnapshotReuse": True,
        "marketSkewObserved": bool(market_contributions)
        and max(float(row.get("candidateShare") or 0.0) for row in market_contributions) >= 0.2,
    }


def _int_value(value: object) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _float_value(value: object) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _ratio(numerator: int | float, denominator: int | float) -> float:
    try:
        denominator_value = float(denominator)
        if denominator_value == 0:
            return 0.0
        return round(float(numerator) / denominator_value, 6)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
