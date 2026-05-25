#!/usr/bin/env python3
"""Compare Event Forensic pre/post performance patch measurements."""

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


REPORT_TYPE = "event_forensic_performance_patch_post_measurement"
SCHEMA_VERSION = "event_forensic_performance_patch_post_measurement_v1"
DEFAULT_BASELINE = Path("validation_outputs/event_forensic_subset_measurement_20260525_181811/summary.json")
DEFAULT_STATIC_EQUIVALENCE = Path("validation_outputs/event_forensic_performance_patch_post_static_equivalence_20260525.json")
DEFAULT_LIVE_DELTA = Path("validation_outputs/event_forensic_performance_patch_live_output_delta_20260525.json")
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_performance_patch_post_measurement_20260525.json")


def build_post_patch_analysis(
    *,
    baseline_payload: Mapping[str, object],
    post_payload: Mapping[str, object],
    static_equivalence: Mapping[str, object] | None = None,
    live_output_delta: Mapping[str, object] | None = None,
    control_measurements: Sequence[tuple[Mapping[str, object], Mapping[str, object]]] | None = None,
) -> dict[str, object]:
    baseline = _measurement_from_payload(baseline_payload)
    post = _measurement_from_payload(post_payload)
    baseline_norm = _normalized_metrics(baseline)
    post_norm = _normalized_metrics(post)
    comparison = _comparison(baseline, post, baseline_norm, post_norm)
    behavior = _behavior_equivalence(static_equivalence or {}, live_output_delta or {})
    controls = [
        _control_comparison(before_payload, after_payload)
        for before_payload, after_payload in (control_measurements or [])
    ]
    gate = _gate_decision(comparison, behavior, post)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": bool(post.get("networkUsed")),
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "storageMutated": False,
        "wholeEventCompletenessClaim": False,
        "baseline": baseline,
        "postPatch": post,
        "normalizedBaseline": baseline_norm,
        "normalizedPostPatch": post_norm,
        "comparison": comparison,
        "behaviorEquivalence": behavior,
        "controlMeasurements": controls,
        "memoization": _memoization_summary(post),
        "gateDecision": gate,
        "nextRecommendedCampaign": _next_campaign(gate, post),
        "forbiddenScopePreserved": {
            "phase3Runtime": False,
            "scoringWeightsChanged": False,
            "thresholdsChanged": False,
            "directGateChanges": False,
            "storageSchemaChanged": False,
            "uiSortingChanged": False,
            "tradingOrPrivateKeyUsed": False,
        },
    }


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
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--post", required=True)
    parser.add_argument("--static-equivalence", default=str(DEFAULT_STATIC_EQUIVALENCE))
    parser.add_argument("--live-delta", default=str(DEFAULT_LIVE_DELTA))
    parser.add_argument("--control", action="append", default=[], help="before.json::after.json")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    controls: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
    for raw in args.control:
        before_raw, after_raw = raw.split("::", 1)
        controls.append((load_json_object(before_raw), load_json_object(after_raw)))
    payload = build_post_patch_analysis(
        baseline_payload=load_json_object(args.baseline),
        post_payload=load_json_object(args.post),
        static_equivalence=load_json_object(args.static_equivalence) if Path(args.static_equivalence).exists() else None,
        live_output_delta=load_json_object(args.live_delta) if Path(args.live_delta).exists() else None,
        control_measurements=controls,
    )
    write_json(payload, args.output)
    if not args.quiet:
        print(json.dumps({"output": args.output, "gateDecision": payload["gateDecision"]}, sort_keys=True))
    return 0


def _measurement_from_payload(payload: Mapping[str, object]) -> dict[str, object]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    report_summary = payload.get("reportSummary") if isinstance(payload.get("reportSummary"), Mapping) else {}
    live_result = payload.get("liveResult") if isinstance(payload.get("liveResult"), Mapping) else {}
    timings = report_summary.get("timings") if isinstance(report_summary.get("timings"), Mapping) else {}
    if not timings and isinstance(live_result.get("timings"), Mapping):
        timings = live_result["timings"]
    event_analysis = _try_load_event_analysis(live_result.get("eventAnalysisJsonPath"))
    performance = event_analysis.get("performance") if isinstance(event_analysis.get("performance"), Mapping) else {}
    if not performance and isinstance(report_summary.get("performance"), Mapping):
        performance = report_summary["performance"]
    if not timings and performance:
        timings = {
            key: performance.get(key)
            for key in (
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
        }
    return {
        "sourceOutputDir": str(payload.get("outputDir") or live_result.get("outputDir") or ""),
        "eventSlug": str(summary.get("eventSlug") or live_result.get("eventSlug") or ""),
        "subsetOnly": bool(summary.get("subsetOnly", payload.get("subsetOnly", False))),
        "selectedMarketCount": _int_value(summary.get("selectedMarketCount")),
        "analysisMarketCount": _int_value(summary.get("analysisMarketCount") or summary.get("marketCount")),
        "liveResolvedMarketCount": _int_value(summary.get("liveResolvedMarketCount") or summary.get("totalEventMarketCount")),
        "rawTradeRows": _int_value(summary.get("rawTradeRows")),
        "candidateRows": _int_value(summary.get("candidateRows")),
        "candidateWalletCount": _int_value(summary.get("candidateWalletCount")),
        "truncatedMarketCount": _int_value(summary.get("truncatedMarketCount")),
        "totalSeconds": _float_value(summary.get("totalSeconds")),
        "dominantBottleneck": str(summary.get("dominantBottleneck") or "unknown"),
        "gateDecision": str(summary.get("gateDecision") or ""),
        "runtimeBoundViolations": list(summary.get("runtimeBoundViolations", []))
        if isinstance(summary.get("runtimeBoundViolations"), list)
        else [],
        "networkUsed": bool(payload.get("networkUsed")),
        "timings": {str(key): _float_value(value) for key, value in dict(timings).items()},
        "memoization": performance.get("score_input_memoization") if isinstance(performance, Mapping) else None,
    }


def _normalized_metrics(row: Mapping[str, object]) -> dict[str, float]:
    raw_rows = _int_value(row.get("rawTradeRows"))
    candidates = _int_value(row.get("candidateRows"))
    wallets = _int_value(row.get("candidateWalletCount"))
    timings = row.get("timings") if isinstance(row.get("timings"), Mapping) else {}
    score_seconds = _float_value(timings.get("score_candidates_seconds"))
    prefetch_seconds = _float_value(timings.get("prefetch_wallet_context_seconds"))
    total_seconds = _float_value(row.get("totalSeconds"))
    return {
        "totalSecondsPer1000RawRows": _per_1000(total_seconds, raw_rows),
        "totalSecondsPer1000Candidates": _per_1000(total_seconds, candidates),
        "scoreSecondsPer1000Candidates": _per_1000(score_seconds, candidates),
        "prefetchSecondsPer1000Wallets": _per_1000(prefetch_seconds, wallets),
        "rawRowsPerCandidate": round(raw_rows / candidates, 6) if candidates else 0.0,
        "candidatesPerWallet": round(candidates / wallets, 6) if wallets else 0.0,
    }


def _comparison(
    baseline: Mapping[str, object],
    post: Mapping[str, object],
    baseline_norm: Mapping[str, object],
    post_norm: Mapping[str, object],
) -> dict[str, object]:
    timings_before = baseline.get("timings") if isinstance(baseline.get("timings"), Mapping) else {}
    timings_after = post.get("timings") if isinstance(post.get("timings"), Mapping) else {}
    return {
        "rawTradeRowsDelta": _int_value(post.get("rawTradeRows")) - _int_value(baseline.get("rawTradeRows")),
        "candidateRowsDelta": _int_value(post.get("candidateRows")) - _int_value(baseline.get("candidateRows")),
        "candidateWalletCountDelta": _int_value(post.get("candidateWalletCount")) - _int_value(baseline.get("candidateWalletCount")),
        "totalSecondsDelta": _round(_float_value(post.get("totalSeconds")) - _float_value(baseline.get("totalSeconds"))),
        "totalSecondsImprovementPercent": _improvement_percent(
            _float_value(baseline.get("totalSeconds")),
            _float_value(post.get("totalSeconds")),
        ),
        "scoreCandidatesSecondsDelta": _round(
            _float_value(timings_after.get("score_candidates_seconds"))
            - _float_value(timings_before.get("score_candidates_seconds"))
        ),
        "scoreCandidatesImprovementPercent": _improvement_percent(
            _float_value(timings_before.get("score_candidates_seconds")),
            _float_value(timings_after.get("score_candidates_seconds")),
        ),
        "prefetchWalletContextSecondsDelta": _round(
            _float_value(timings_after.get("prefetch_wallet_context_seconds"))
            - _float_value(timings_before.get("prefetch_wallet_context_seconds"))
        ),
        "prefetchWalletContextImprovementPercent": _improvement_percent(
            _float_value(timings_before.get("prefetch_wallet_context_seconds")),
            _float_value(timings_after.get("prefetch_wallet_context_seconds")),
        ),
        "normalizedScoreImprovementPercent": _improvement_percent(
            _float_value(baseline_norm.get("scoreSecondsPer1000Candidates")),
            _float_value(post_norm.get("scoreSecondsPer1000Candidates")),
        ),
        "normalizedTotalImprovementPercent": _improvement_percent(
            _float_value(baseline_norm.get("totalSecondsPer1000Candidates")),
            _float_value(post_norm.get("totalSecondsPer1000Candidates")),
        ),
        "normalizedPrefetchImprovementPercent": _improvement_percent(
            _float_value(baseline_norm.get("prefetchSecondsPer1000Wallets")),
            _float_value(post_norm.get("prefetchSecondsPer1000Wallets")),
        ),
    }


def _behavior_equivalence(
    static_equivalence: Mapping[str, object],
    live_output_delta: Mapping[str, object],
) -> dict[str, object]:
    static_gate = str(static_equivalence.get("gate") or static_equivalence.get("equivalenceGate") or "")
    post_patch_snapshot = (
        static_equivalence.get("postPatchSnapshot")
        if isinstance(static_equivalence.get("postPatchSnapshot"), Mapping)
        else {}
    )
    return {
        "staticEquivalenceGate": static_gate,
        "staticEquivalencePassed": static_gate in {
            "static_equivalence_passed",
            "event_forensic_performance_patch_equivalence_static_snapshot_passed",
        },
        "staticCandidateCount": _int_value(
            static_equivalence.get("candidateCount") or post_patch_snapshot.get("candidateCount")
        ),
        "liveCandidateCountDelta": _int_value(live_output_delta.get("candidateCountDelta")),
        "liveAddedCandidateCount": _int_value(live_output_delta.get("addedCandidateCount")),
        "liveRemovedCandidateCount": _int_value(live_output_delta.get("removedCandidateCount")),
        "liveScoreChangeCountOnCommonIds": _int_value(live_output_delta.get("scoreChangeCountOnCommonIds")),
        "liveReviewBucketChangeCountOnCommonIds": _int_value(live_output_delta.get("reviewBucketChangeCountOnCommonIds")),
        "liveWeakHistoryDemotionChangeCountOnCommonIds": _int_value(live_output_delta.get("weakHistoryDemotionChangeCountOnCommonIds")),
        "liveStrictEquivalencePassed": bool(live_output_delta.get("strictContractComparison", {}).get("passed"))
        if isinstance(live_output_delta.get("strictContractComparison"), Mapping)
        else False,
        "liveEquivalenceInterpretation": (
            "live_data_drift_observed; use static equivalence and common-id drift counters as behavior guard"
            if live_output_delta
            else "not_evaluated"
        ),
    }


def _control_comparison(before_payload: Mapping[str, object], after_payload: Mapping[str, object]) -> dict[str, object]:
    before = _measurement_from_payload(before_payload)
    after = _measurement_from_payload(after_payload)
    return {
        "eventSlug": after.get("eventSlug") or before.get("eventSlug"),
        "baselineTotalSeconds": before.get("totalSeconds"),
        "postPatchTotalSeconds": after.get("totalSeconds"),
        "totalSecondsImprovementPercent": _improvement_percent(
            _float_value(before.get("totalSeconds")),
            _float_value(after.get("totalSeconds")),
        ),
        "baselineCandidateRows": before.get("candidateRows"),
        "postPatchCandidateRows": after.get("candidateRows"),
        "candidateRowsDelta": _int_value(after.get("candidateRows")) - _int_value(before.get("candidateRows")),
        "gateDecision": after.get("gateDecision"),
    }


def _memoization_summary(post: Mapping[str, object]) -> dict[str, object]:
    memo = post.get("memoization") if isinstance(post.get("memoization"), Mapping) else {}
    candidates = _int_value(memo.get("candidateRows"))
    unique_wallets = _int_value(memo.get("uniqueWallets"))
    repeated = _int_value(memo.get("repeatedWalletCandidateOpportunities"))
    return {
        "enabled": bool(memo.get("enabled")),
        "candidateRows": candidates,
        "uniqueWallets": unique_wallets,
        "uniqueMarkets": _int_value(memo.get("uniqueMarkets")),
        "uniqueDomains": _int_value(memo.get("uniqueDomains")),
        "cacheableLookupCount": candidates,
        "cacheHitsEstimate": repeated,
        "cacheMissesEstimate": unique_wallets,
        "repeatedWalletCandidateOpportunities": repeated,
        "effectiveReuseRatio": round(repeated / candidates, 6) if candidates else 0.0,
        "cacheScopes": list(memo.get("cacheScopes", [])) if isinstance(memo.get("cacheScopes"), list) else [],
    }


def _gate_decision(
    comparison: Mapping[str, object],
    behavior: Mapping[str, object],
    post: Mapping[str, object],
) -> str:
    if not bool(behavior.get("staticEquivalencePassed")):
        return "regression_stop"
    if str(post.get("gateDecision")) not in {"subset_measurement_complete", "performance_measurement_complete"}:
        return "measurement_blocked"
    normalized_score_improvement = _float_value(comparison.get("normalizedScoreImprovementPercent"))
    normalized_total_improvement = _float_value(comparison.get("normalizedTotalImprovementPercent"))
    if normalized_score_improvement >= 5.0 and normalized_total_improvement >= 2.0:
        if str(post.get("dominantBottleneck")) == "score_candidates_seconds":
            return "patch_partial_needs_next_optimization"
        return "patch_effective"
    if normalized_score_improvement >= 5.0:
        return "patch_partial_needs_next_optimization"
    return "patch_not_effective_needs_redesign"


def _next_campaign(gate: str, post: Mapping[str, object]) -> str:
    if gate == "patch_partial_needs_next_optimization":
        if str(post.get("dominantBottleneck")) == "score_candidates_seconds":
            return "deeper_scorer_context_profiling_plus_wallet_prefetch_rfc"
        return "wallet_prefetch_optimization_rfc"
    if gate == "patch_effective":
        return "release_readiness_addendum"
    if gate == "measurement_blocked":
        return "measurement_blocker_triage"
    return "performance_redesign_or_rollback_decision"


def _try_load_event_analysis(path_value: object) -> dict[str, object]:
    path = Path(str(path_value or ""))
    if not path.is_file():
        return {}
    try:
        return load_json_object(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _per_1000(seconds: float, count: int) -> float:
    if count <= 0:
        return 0.0
    return round((float(seconds) / count) * 1000, 6)


def _improvement_percent(before: float, after: float) -> float:
    if before <= 0:
        return 0.0
    return round(((before - after) / before) * 100.0, 3)


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


def _round(value: float) -> float:
    return round(float(value), 3)


if __name__ == "__main__":
    raise SystemExit(main())
