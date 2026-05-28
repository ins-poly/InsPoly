#!/usr/bin/env python3
"""Aggregate bounded Event Forensic performance measurement summaries."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "event_forensic_performance_measurement_aggregate"
SCHEMA_VERSION = "event_forensic_performance_measurement_aggregate_v1"
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_performance_measurement_aggregate_20260525.json")


def build_measurement_aggregate(summaries: Sequence[Mapping[str, object]]) -> dict[str, object]:
    measurements = [_measurement_row(summary) for summary in summaries]
    completed = [row for row in measurements if row["gateDecision"] == "performance_measurement_complete"]
    total_seconds = [float(row["totalSeconds"]) for row in completed if row["totalSeconds"]]
    bottlenecks = Counter(str(row["dominantBottleneck"] or "unknown") for row in completed)
    truncation_count = sum(1 for row in completed if int(row["truncatedMarketCount"] or 0) > 0)
    max_markets = max((int(row["marketCount"] or 0) for row in completed), default=0)
    patch_gate = _performance_gate(completed, bottlenecks, max_markets)
    pagination_gate = _pagination_gate(completed, truncation_count, max_markets)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": any(bool(row["networkUsed"]) for row in measurements),
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "storageMutated": False,
        "summary": {
            "measurementCount": len(measurements),
            "completedMeasurementCount": len(completed),
            "totalMarkets": sum(int(row["marketCount"] or 0) for row in completed),
            "totalRawRows": sum(int(row["rawTradeRows"] or 0) for row in completed),
            "totalCandidateRows": sum(int(row["candidateRows"] or 0) for row in completed),
            "totalCandidateWallets": sum(int(row["candidateWalletCount"] or 0) for row in completed),
            "slowestRunSeconds": max(total_seconds) if total_seconds else 0.0,
            "medianTotalSeconds": statistics.median(total_seconds) if total_seconds else 0.0,
            "maxMarketCount": max_markets,
            "truncationOccurrenceCount": truncation_count,
            "dominantBottleneckCounts": dict(sorted(bottlenecks.items())),
            "performanceGate": patch_gate,
            "paginationGate": pagination_gate,
            "subsetApprovalNeeded": patch_gate == "performance_needs_subset_measurement",
        },
        "measurements": measurements,
        "recommendation": _recommendation(patch_gate, pagination_gate),
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def load_json_object(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _measurement_row(summary: Mapping[str, object]) -> dict[str, object]:
    nested = summary.get("summary") if isinstance(summary.get("summary"), Mapping) else {}
    report_summary = summary.get("reportSummary") if isinstance(summary.get("reportSummary"), Mapping) else {}
    return {
        "sourceSummaryPath": str(summary.get("sourceSummaryPath") or ""),
        "outputDir": str(summary.get("outputDir") or nested.get("outputDir") or ""),
        "eventSlug": str(nested.get("eventSlug") or report_summary.get("eventSlug") or ""),
        "gateDecision": str(nested.get("gateDecision") or summary.get("measurementGate") or ""),
        "networkUsed": bool(summary.get("networkUsed")),
        "marketCount": _int_or_zero(nested.get("marketCount") or report_summary.get("analysisMarketCount")),
        "totalEventMarketCount": _int_or_zero(nested.get("totalEventMarketCount") or report_summary.get("totalEventMarketCount")),
        "rawTradeRows": _int_or_zero(nested.get("rawTradeRows") or report_summary.get("rawTradeCount")),
        "candidateRows": _int_or_zero(nested.get("candidateRows") or report_summary.get("candidateTradeCount")),
        "candidateWalletCount": _int_or_zero(nested.get("candidateWalletCount") or report_summary.get("candidateWalletCount")),
        "truncatedMarketCount": _int_or_zero(nested.get("truncatedMarketCount") or report_summary.get("truncatedMarketCount")),
        "totalSeconds": _float_or_zero(nested.get("totalSeconds") or report_summary.get("totalSeconds")),
        "dominantBottleneck": str(nested.get("dominantBottleneck") or report_summary.get("dominantBottleneck") or "unknown"),
    }


def _performance_gate(completed: Sequence[Mapping[str, object]], bottlenecks: Counter[str], max_markets: int) -> str:
    if not completed:
        return "performance_measurement_inconclusive"
    if len(completed) >= 3 and max_markets <= 1:
        return "performance_needs_subset_measurement"
    if max_markets > 1 and len(completed) >= 2 and _consistent_non_unknown_bottleneck(bottlenecks):
        return "performance_evidence_sufficient_for_patch_rfc"
    if len(completed) >= 2:
        return "performance_needs_more_safe_targets"
    return "performance_measurement_inconclusive"


def _pagination_gate(completed: Sequence[Mapping[str, object]], truncation_count: int, max_markets: int) -> str:
    if not completed:
        return "pagination_still_needs_operator_plan_for_large_events"
    if truncation_count:
        return "pagination_issue_observed"
    if max_markets <= 1:
        return "pagination_still_needs_operator_plan_for_large_events"
    return "pagination_measurement_clean_for_safe_targets"


def _consistent_non_unknown_bottleneck(bottlenecks: Counter[str]) -> bool:
    if not bottlenecks:
        return False
    dominant, count = bottlenecks.most_common(1)[0]
    return dominant != "unknown" and count >= 2


def _recommendation(performance_gate: str, pagination_gate: str) -> str:
    if performance_gate == "performance_evidence_sufficient_for_patch_rfc":
        return "Draft a behavior-preserving performance patch RFC before runtime optimization."
    if performance_gate == "performance_needs_subset_measurement":
        return "Safe targets remain too small; request explicit subset-only approval for a larger event before patching."
    if performance_gate == "performance_needs_more_safe_targets":
        return "Measure more current <=8-market targets before selecting a patch."
    if pagination_gate == "pagination_issue_observed":
        return "Keep pagination operator-gated; truncation appeared in bounded safe measurements."
    return "Evidence remains inconclusive; preserve current runtime behavior."


def _int_or_zero(value: object) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _float_or_zero(value: object) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summaries", nargs="+")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payloads = []
    for path in args.summaries:
        payload = load_json_object(path)
        payload["sourceSummaryPath"] = path
        payloads.append(payload)
    aggregate = build_measurement_aggregate(payloads)
    write_json(aggregate, args.output)
    if not args.quiet:
        print(json.dumps({"output": args.output, "gate": aggregate["summary"]["performanceGate"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
