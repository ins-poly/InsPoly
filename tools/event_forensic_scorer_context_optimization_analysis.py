#!/usr/bin/env python3
"""Analyze Event Forensic scorer-context optimization measurements."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "event_forensic_scorer_context_optimization_measurement"
SCHEMA_VERSION = "event_forensic_scorer_context_optimization_measurement_v1"
DEFAULT_PRE_MEMOIZATION = Path("validation_outputs/event_forensic_subset_measurement_20260525_181811/summary.json")
DEFAULT_POST_SCORER = Path("validation_outputs/event_forensic_performance_patch_post_measurement_20260525_190410/summary.json")
DEFAULT_POST_WALLET = Path("validation_outputs/event_forensic_wallet_prefetch_optimization_live_20260525_195106/summary.json")
DEFAULT_POST_PROFILE = Path("validation_outputs/event_forensic_scorer_context_profile_live_20260526_112806/summary.json")
DEFAULT_OPTIMIZED = Path("validation_outputs/event_forensic_scorer_context_optimization_live_20260526_115811/summary.json")
DEFAULT_STATIC_EQUIVALENCE = Path("validation_outputs/event_forensic_scorer_context_optimization_static_equivalence_20260526.json")
DEFAULT_INPUT_AUDIT = Path("validation_outputs/event_forensic_score_call_input_audit_20260526.json")
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_scorer_context_optimization_measurement_20260526.json")


def build_scorer_context_optimization_analysis(
    *,
    pre_memoization_payload: Mapping[str, object],
    post_scorer_payload: Mapping[str, object],
    post_wallet_payload: Mapping[str, object],
    post_profile_payload: Mapping[str, object],
    optimized_payload: Mapping[str, object],
    static_equivalence_payload: Mapping[str, object],
    input_audit_payload: Mapping[str, object],
) -> dict[str, object]:
    pre_memoization = _measurement_from_payload(pre_memoization_payload)
    post_scorer = _measurement_from_payload(post_scorer_payload)
    post_wallet = _measurement_from_payload(post_wallet_payload)
    post_profile = _measurement_from_payload(post_profile_payload)
    optimized = _measurement_from_payload(optimized_payload)
    static_equivalence = _static_equivalence(static_equivalence_payload)
    profile_to_optimized = _comparison(post_profile, optimized)
    scorer_to_optimized = _comparison(post_scorer, optimized)
    pre_to_optimized = _comparison(pre_memoization, optimized)
    gate = _gate_decision(
        static_equivalence=static_equivalence,
        optimized=optimized,
        profile_to_optimized=profile_to_optimized,
    )
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": False,
        "networkUsed": bool(optimized.get("networkUsed")),
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "storageMutated": False,
        "wholeEventCompletenessClaim": False,
        "commitsCompared": {
            "preScorerMemoizationBaseline": "pre-3bf03ce",
            "scorerMemoization": "3bf03ce",
            "postScorerMeasurement": "338b559",
            "walletContextCache": "eae111e",
            "scorerProfile": "5d12334",
            "currentOptimizationRun": "working_tree_prepared_score_context",
        },
        "scope": {
            "eventSlug": optimized.get("eventSlug"),
            "subsetOnly": True,
            "analysisMarketCount": optimized.get("analysisMarketCount"),
            "liveResolvedMarketCount": optimized.get("liveResolvedMarketCount"),
            "wholeEventCompletenessClaim": False,
        },
        "preMemoizationBaseline": pre_memoization,
        "postScorerMemoizationBaseline": post_scorer,
        "postWalletContextCache": post_wallet,
        "postScorerContextProfile": post_profile,
        "postScorerContextOptimization": optimized,
        "comparisonProfileToOptimized": profile_to_optimized,
        "comparisonPostScorerToOptimized": scorer_to_optimized,
        "comparisonPreMemoizationToOptimized": pre_to_optimized,
        "staticEquivalence": static_equivalence,
        "scoreCallInputAudit": {
            "gateDecision": input_audit_payload.get("gateDecision"),
            "totalRows": input_audit_payload.get("totalRows"),
            "duplicateEquivalentScoreCallsRare": input_audit_payload.get("duplicateEquivalentScoreCallsRare"),
            "safeOptimizationRecommendation": input_audit_payload.get("safeOptimizationRecommendation"),
            "exactInputSignature": input_audit_payload.get("exactInputSignature", {}),
            "walletMarketTokenSignature": input_audit_payload.get("walletMarketTokenSignature", {}),
            "normalizedProbabilityContext": input_audit_payload.get("normalizedProbabilityContext", {}),
        },
        "preparedContext": optimized.get("scoreTradePreparedContext") or {},
        "profilerTopBottlenecks": _top_bottlenecks(optimized),
        "gateDecision": gate,
        "nextRecommendedCampaign": _next_campaign(gate, optimized),
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
    parser.add_argument("--pre-memoization", default=str(DEFAULT_PRE_MEMOIZATION))
    parser.add_argument("--post-scorer", default=str(DEFAULT_POST_SCORER))
    parser.add_argument("--post-wallet", default=str(DEFAULT_POST_WALLET))
    parser.add_argument("--post-profile", default=str(DEFAULT_POST_PROFILE))
    parser.add_argument("--optimized", default=str(DEFAULT_OPTIMIZED))
    parser.add_argument("--static-equivalence", default=str(DEFAULT_STATIC_EQUIVALENCE))
    parser.add_argument("--input-audit", default=str(DEFAULT_INPUT_AUDIT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payload = build_scorer_context_optimization_analysis(
        pre_memoization_payload=load_json_object(args.pre_memoization),
        post_scorer_payload=load_json_object(args.post_scorer),
        post_wallet_payload=load_json_object(args.post_wallet),
        post_profile_payload=load_json_object(args.post_profile),
        optimized_payload=load_json_object(args.optimized),
        static_equivalence_payload=load_json_object(args.static_equivalence),
        input_audit_payload=load_json_object(args.input_audit),
    )
    write_json(payload, args.output)
    if not args.quiet:
        print(json.dumps({"output": args.output, "gateDecision": payload["gateDecision"]}, sort_keys=True))
    return 0


def _measurement_from_payload(payload: Mapping[str, object]) -> dict[str, object]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    live_result = payload.get("liveResult") if isinstance(payload.get("liveResult"), Mapping) else {}
    report_summary = payload.get("reportSummary") if isinstance(payload.get("reportSummary"), Mapping) else {}
    timings = report_summary.get("timings") if isinstance(report_summary.get("timings"), Mapping) else {}
    if not timings and isinstance(live_result.get("timings"), Mapping):
        timings = live_result["timings"]
    performance = _load_performance(live_result.get("eventAnalysisJsonPath"))
    raw_rows = _int_value(summary.get("rawTradeRows") or live_result.get("rawTradeCount") or performance.get("trade_collection_raw_trade_rows"))
    candidate_rows = _int_value(summary.get("candidateRows") or live_result.get("candidateTradeCount") or performance.get("candidate_trade_count_visible"))
    candidate_wallets = _int_value(
        summary.get("candidateWalletCount") or live_result.get("candidateWalletCount") or performance.get("candidate_wallet_count")
    )
    total_seconds = _float_value(summary.get("totalSeconds") or live_result.get("wallClockSeconds") or performance.get("total_seconds"))
    measurement = {
        "sourceOutputDir": str(payload.get("outputDir") or ""),
        "eventSlug": str(summary.get("eventSlug") or live_result.get("eventSlug") or ""),
        "subsetOnly": bool(summary.get("subsetOnly", payload.get("subsetOnly", False))),
        "analysisMarketCount": _int_value(summary.get("analysisMarketCount") or live_result.get("analysisMarketCount")),
        "liveResolvedMarketCount": _int_value(summary.get("liveResolvedMarketCount") or live_result.get("liveResolvedMarketCount")),
        "rawTradeRows": raw_rows,
        "candidateRows": candidate_rows,
        "candidateWalletCount": candidate_wallets,
        "truncatedMarketCount": _int_value(summary.get("truncatedMarketCount") or live_result.get("truncatedMarketCount")),
        "totalSeconds": total_seconds,
        "dominantBottleneck": str(summary.get("dominantBottleneck") or live_result.get("dominantBottleneck") or "unknown"),
        "gateDecision": str(summary.get("gateDecision") or live_result.get("gateDecision") or ""),
        "runtimeBoundViolations": list(summary.get("runtimeBoundViolations", []))
        if isinstance(summary.get("runtimeBoundViolations"), list)
        else [],
        "networkUsed": bool(payload.get("networkUsed")),
        "timings": {str(key): _float_value(value) for key, value in dict(timings).items()},
        "scoreInputMemoization": performance.get("score_input_memoization") if isinstance(performance, Mapping) else {},
        "walletContextReuse": performance.get("wallet_context_reuse") if isinstance(performance, Mapping) else {},
        "scorerContextProfile": performance.get("scorer_context_profile") if isinstance(performance, Mapping) else {},
        "scoreTradePreparedContext": performance.get("score_trade_prepared_context") if isinstance(performance, Mapping) else {},
    }
    measurement["normalized"] = _normalized_metrics(measurement)
    return measurement


def _load_performance(path_raw: object) -> dict[str, object]:
    raw = str(path_raw or "").strip()
    if not raw:
        return {}
    path = Path(raw)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, Mapping):
        return {}
    performance = payload.get("performance")
    return dict(performance) if isinstance(performance, Mapping) else {}


def _normalized_metrics(measurement: Mapping[str, object]) -> dict[str, float]:
    timings = measurement.get("timings") if isinstance(measurement.get("timings"), Mapping) else {}
    raw_rows = _int_value(measurement.get("rawTradeRows"))
    candidates = _int_value(measurement.get("candidateRows"))
    wallets = _int_value(measurement.get("candidateWalletCount"))
    total = _float_value(measurement.get("totalSeconds"))
    score = _float_value(timings.get("score_candidates_seconds"))
    prefetch = _float_value(timings.get("prefetch_wallet_context_seconds"))
    prepare = _float_value(timings.get("prepare_candidate_context_seconds"))
    return {
        "totalSecondsPer1000RawRows": _per_1000(total, raw_rows),
        "totalSecondsPer1000Candidates": _per_1000(total, candidates),
        "scoreSecondsPer1000Candidates": _per_1000(score, candidates),
        "prefetchSecondsPer1000Wallets": _per_1000(prefetch, wallets),
        "prepareSecondsPer1000Candidates": _per_1000(prepare, candidates),
        "candidatesPerWallet": round(candidates / wallets, 6) if wallets else 0.0,
    }


def _comparison(before: Mapping[str, object], after: Mapping[str, object]) -> dict[str, object]:
    before_timings = before.get("timings") if isinstance(before.get("timings"), Mapping) else {}
    after_timings = after.get("timings") if isinstance(after.get("timings"), Mapping) else {}
    before_norm = before.get("normalized") if isinstance(before.get("normalized"), Mapping) else {}
    after_norm = after.get("normalized") if isinstance(after.get("normalized"), Mapping) else {}
    return {
        "rawTradeRowsDelta": _int_value(after.get("rawTradeRows")) - _int_value(before.get("rawTradeRows")),
        "candidateRowsDelta": _int_value(after.get("candidateRows")) - _int_value(before.get("candidateRows")),
        "candidateWalletCountDelta": _int_value(after.get("candidateWalletCount")) - _int_value(before.get("candidateWalletCount")),
        "totalSecondsDelta": _round(_float_value(after.get("totalSeconds")) - _float_value(before.get("totalSeconds"))),
        "totalSecondsImprovementPercent": _improvement_percent(
            _float_value(before.get("totalSeconds")),
            _float_value(after.get("totalSeconds")),
        ),
        "scoreCandidatesSecondsDelta": _round(
            _float_value(after_timings.get("score_candidates_seconds"))
            - _float_value(before_timings.get("score_candidates_seconds"))
        ),
        "scoreCandidatesImprovementPercent": _improvement_percent(
            _float_value(before_timings.get("score_candidates_seconds")),
            _float_value(after_timings.get("score_candidates_seconds")),
        ),
        "prefetchWalletContextSecondsDelta": _round(
            _float_value(after_timings.get("prefetch_wallet_context_seconds"))
            - _float_value(before_timings.get("prefetch_wallet_context_seconds"))
        ),
        "prefetchWalletContextImprovementPercent": _improvement_percent(
            _float_value(before_timings.get("prefetch_wallet_context_seconds")),
            _float_value(after_timings.get("prefetch_wallet_context_seconds")),
        ),
        "normalizedTotalImprovementPercent": _improvement_percent(
            _float_value(before_norm.get("totalSecondsPer1000Candidates")),
            _float_value(after_norm.get("totalSecondsPer1000Candidates")),
        ),
        "normalizedScoreImprovementPercent": _improvement_percent(
            _float_value(before_norm.get("scoreSecondsPer1000Candidates")),
            _float_value(after_norm.get("scoreSecondsPer1000Candidates")),
        ),
        "normalizedPrefetchImprovementPercent": _improvement_percent(
            _float_value(before_norm.get("prefetchSecondsPer1000Wallets")),
            _float_value(after_norm.get("prefetchSecondsPer1000Wallets")),
        ),
    }


def _static_equivalence(payload: Mapping[str, object]) -> dict[str, object]:
    comparison = payload.get("contractComparisonAgainstSelf")
    passed = bool(comparison.get("passed")) if isinstance(comparison, Mapping) else False
    return {
        "passed": passed and not bool(payload.get("networkUsed")) and not bool(payload.get("runtimeBehaviorChanged")),
        "candidateCount": _int_value(payload.get("candidateCount")),
        "exportRowCount": _int_value(payload.get("exportRowCount")),
        "candidateRowsSha256": str(payload.get("candidateRowsSha256") or ""),
    }


def _top_bottlenecks(measurement: Mapping[str, object]) -> list[object]:
    profile = measurement.get("scorerContextProfile") if isinstance(measurement.get("scorerContextProfile"), Mapping) else {}
    top = profile.get("topBuckets") if isinstance(profile.get("topBuckets"), list) else []
    return top[:5]


def _gate_decision(
    *,
    static_equivalence: Mapping[str, object],
    optimized: Mapping[str, object],
    profile_to_optimized: Mapping[str, object],
) -> str:
    if not static_equivalence.get("passed"):
        return "regression_stop"
    if str(optimized.get("gateDecision")) not in {"subset_measurement_complete", "performance_measurement_complete"}:
        return "measurement_blocked"
    normalized_score_improvement = _float_value(profile_to_optimized.get("normalizedScoreImprovementPercent"))
    normalized_total_improvement = _float_value(profile_to_optimized.get("normalizedTotalImprovementPercent"))
    if normalized_score_improvement >= 5.0 and normalized_total_improvement >= 3.0:
        return "scorer_context_patch_effective"
    if normalized_score_improvement >= 3.0:
        return "scorer_context_patch_partial"
    return "scorer_context_no_safe_patch"


def _next_campaign(gate: str, optimized: Mapping[str, object]) -> str:
    timings = optimized.get("timings") if isinstance(optimized.get("timings"), Mapping) else {}
    if gate == "scorer_context_patch_effective":
        return "release_readiness_or_small_control_measurement"
    if gate == "scorer_context_patch_partial":
        if _float_value(timings.get("prefetch_wallet_context_seconds")) >= _float_value(timings.get("score_candidates_seconds")) * 0.75:
            return "wallet_api_boundary_batching_rfc_or_pagination_operator_plan"
        return "finer_score_trade_internal_profile"
    if gate == "regression_stop":
        return "revert_or_fix_runtime_patch_before_measurement"
    return "optimization_blocker_review"


def _per_1000(seconds: float, count: int) -> float:
    if not count:
        return 0.0
    return round((seconds / count) * 1000.0, 6)


def _improvement_percent(before: float, after: float) -> float:
    if before == 0:
        return 0.0
    return round(((before - after) / before) * 100.0, 3)


def _round(value: float) -> float:
    return round(value, 3)


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


if __name__ == "__main__":
    raise SystemExit(main())
