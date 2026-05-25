#!/usr/bin/env python3
"""Analyze Event Forensic wallet/context optimization measurements."""

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

from tools.event_forensic_behavior_snapshot import (
    extract_candidate_contract_rows,
    load_rows,
)


REPORT_TYPE = "event_forensic_wallet_prefetch_optimization_measurement"
SCHEMA_VERSION = "event_forensic_wallet_prefetch_optimization_measurement_v1"
DEFAULT_PRE_MEMOIZATION = Path("validation_outputs/event_forensic_subset_measurement_20260525_181811/summary.json")
DEFAULT_POST_SCORER = Path("validation_outputs/event_forensic_performance_patch_post_measurement_20260525_190410/summary.json")
DEFAULT_POST_WALLET = Path("validation_outputs/event_forensic_wallet_prefetch_optimization_live_20260525_195106/summary.json")
DEFAULT_STATIC_EQUIVALENCE = Path("validation_outputs/event_forensic_wallet_prefetch_optimization_static_equivalence_20260525.json")
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_wallet_prefetch_optimization_measurement_20260525.json")


def build_wallet_prefetch_optimization_analysis(
    *,
    pre_memoization_payload: Mapping[str, object],
    post_scorer_payload: Mapping[str, object],
    post_wallet_payload: Mapping[str, object],
    static_equivalence_payload: Mapping[str, object],
    previous_candidate_rows: Sequence[Mapping[str, object]] | None = None,
    post_candidate_rows: Sequence[Mapping[str, object]] | None = None,
    control_measurements: Sequence[tuple[Mapping[str, object], Mapping[str, object]]] | None = None,
) -> dict[str, object]:
    pre_memoization = _measurement_from_payload(pre_memoization_payload)
    post_scorer = _measurement_from_payload(post_scorer_payload)
    post_wallet = _measurement_from_payload(post_wallet_payload)
    static_equivalence = _static_equivalence(static_equivalence_payload)
    live_delta = _candidate_delta(previous_candidate_rows or [], post_candidate_rows or [])
    scorer_to_wallet = _comparison(post_scorer, post_wallet)
    pre_to_wallet = _comparison(pre_memoization, post_wallet)
    controls = [
        _control_comparison(before_payload, after_payload)
        for before_payload, after_payload in (control_measurements or [])
    ]
    gate = _gate_decision(
        static_equivalence=static_equivalence,
        post_wallet=post_wallet,
        scorer_to_wallet=scorer_to_wallet,
    )
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": bool(post_wallet.get("networkUsed")),
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "storageMutated": False,
        "wholeEventCompletenessClaim": False,
        "preMemoizationBaseline": pre_memoization,
        "postScorerMemoizationBaseline": post_scorer,
        "postWalletContextOptimization": post_wallet,
        "comparisonPostScorerToPostWallet": scorer_to_wallet,
        "comparisonPreMemoizationToPostWallet": pre_to_wallet,
        "staticEquivalence": static_equivalence,
        "liveOutputDelta": live_delta,
        "controlMeasurements": controls,
        "walletContextReuse": post_wallet.get("walletContextReuse") or {},
        "gateDecision": gate,
        "nextRecommendedCampaign": _next_campaign(gate, post_wallet),
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
    parser.add_argument("--static-equivalence", default=str(DEFAULT_STATIC_EQUIVALENCE))
    parser.add_argument("--previous-candidates", default="")
    parser.add_argument("--post-candidates", default="")
    parser.add_argument("--control", action="append", default=[], help="before.json::after.json")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    controls: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
    for raw in args.control:
        before_raw, after_raw = raw.split("::", 1)
        controls.append((load_json_object(before_raw), load_json_object(after_raw)))

    previous_rows = load_rows(args.previous_candidates) if args.previous_candidates else []
    post_rows = load_rows(args.post_candidates) if args.post_candidates else []
    payload = build_wallet_prefetch_optimization_analysis(
        pre_memoization_payload=load_json_object(args.pre_memoization),
        post_scorer_payload=load_json_object(args.post_scorer),
        post_wallet_payload=load_json_object(args.post_wallet),
        static_equivalence_payload=load_json_object(args.static_equivalence),
        previous_candidate_rows=previous_rows,
        post_candidate_rows=post_rows,
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
    performance = _load_performance(live_result.get("eventAnalysisJsonPath"))
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
        "normalized": _normalized_metrics(summary, timings),
        "scoreInputMemoization": performance.get("score_input_memoization") if isinstance(performance, Mapping) else {},
        "walletContextReuse": performance.get("wallet_context_reuse") if isinstance(performance, Mapping) else {},
    }


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


def _normalized_metrics(summary: Mapping[str, object], timings: Mapping[str, object]) -> dict[str, float]:
    raw_rows = _int_value(summary.get("rawTradeRows"))
    candidates = _int_value(summary.get("candidateRows"))
    wallets = _int_value(summary.get("candidateWalletCount"))
    total = _float_value(summary.get("totalSeconds"))
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
        "prepareCandidateContextSecondsDelta": _round(
            _float_value(after_timings.get("prepare_candidate_context_seconds"))
            - _float_value(before_timings.get("prepare_candidate_context_seconds"))
        ),
        "prepareCandidateContextImprovementPercent": _improvement_percent(
            _float_value(before_timings.get("prepare_candidate_context_seconds")),
            _float_value(after_timings.get("prepare_candidate_context_seconds")),
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
        "normalizedPrepareImprovementPercent": _improvement_percent(
            _float_value(before_norm.get("prepareSecondsPer1000Candidates")),
            _float_value(after_norm.get("prepareSecondsPer1000Candidates")),
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


def _candidate_delta(
    previous_rows: Sequence[Mapping[str, object]],
    post_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if not previous_rows or not post_rows:
        return {"available": False}
    before = extract_candidate_contract_rows(previous_rows)
    after = extract_candidate_contract_rows(post_rows)
    before_by_id = {str(row["candidateId"]): row for row in before}
    after_by_id = {str(row["candidateId"]): row for row in after}
    before_ids = set(before_by_id)
    after_ids = set(after_by_id)
    common = before_ids & after_ids
    return {
        "available": True,
        "candidateCountBefore": len(before),
        "candidateCountAfter": len(after),
        "candidateCountDelta": len(after) - len(before),
        "commonCandidateCount": len(common),
        "addedCandidateCount": len(after_ids - before_ids),
        "removedCandidateCount": len(before_ids - after_ids),
        "scoreChangeCountOnCommonIds": sum(
            1 for candidate_id in common if before_by_id[candidate_id].get("eventForensicScore") != after_by_id[candidate_id].get("eventForensicScore")
        ),
        "reviewBucketChangeCountOnCommonIds": sum(
            1 for candidate_id in common if before_by_id[candidate_id].get("reviewBucket") != after_by_id[candidate_id].get("reviewBucket")
        ),
        "weakHistoryDemotionChangeCountOnCommonIds": sum(
            1
            for candidate_id in common
            if before_by_id[candidate_id].get("weakHistoryNearCertaintyReviewDemotion")
            != after_by_id[candidate_id].get("weakHistoryNearCertaintyReviewDemotion")
        ),
        "interpretation": "live_data_drift_observed; use static equivalence and common-id drift counters as behavior guard",
    }


def _control_comparison(before_payload: Mapping[str, object], after_payload: Mapping[str, object]) -> dict[str, object]:
    before = _measurement_from_payload(before_payload)
    after = _measurement_from_payload(after_payload)
    return {
        "eventSlug": after.get("eventSlug") or before.get("eventSlug"),
        "baselineTotalSeconds": before.get("totalSeconds"),
        "postWalletTotalSeconds": after.get("totalSeconds"),
        "candidateRowsDelta": _int_value(after.get("candidateRows")) - _int_value(before.get("candidateRows")),
        "totalSecondsImprovementPercent": _comparison(before, after)["totalSecondsImprovementPercent"],
    }


def _gate_decision(
    *,
    static_equivalence: Mapping[str, object],
    post_wallet: Mapping[str, object],
    scorer_to_wallet: Mapping[str, object],
) -> str:
    if not static_equivalence.get("passed"):
        return "regression_stop"
    if str(post_wallet.get("gateDecision")) not in {"subset_measurement_complete", "performance_measurement_complete"}:
        return "measurement_blocked"
    score_improved = _float_value(scorer_to_wallet.get("normalizedScoreImprovementPercent")) >= 3.0
    prefetch_improved = _float_value(scorer_to_wallet.get("normalizedPrefetchImprovementPercent")) >= 5.0
    total_improved = _float_value(scorer_to_wallet.get("normalizedTotalImprovementPercent")) >= 3.0
    if prefetch_improved and total_improved:
        return "wallet_prefetch_patch_effective"
    if score_improved:
        return "wallet_prefetch_patch_partial"
    return "wallet_prefetch_patch_not_worth_it"


def _next_campaign(gate: str, post_wallet: Mapping[str, object]) -> str:
    if gate == "wallet_prefetch_patch_partial":
        timings = post_wallet.get("timings") if isinstance(post_wallet.get("timings"), Mapping) else {}
        if _float_value(timings.get("prefetch_wallet_context_seconds")) >= _float_value(timings.get("score_candidates_seconds")) * 0.75:
            return "wallet_prefetch_batching_or_api_boundary_rfc"
        return "scorer_context_profiling_rfc"
    if gate == "wallet_prefetch_patch_effective":
        return "release_readiness_addendum"
    if gate == "wallet_prefetch_patch_not_worth_it":
        return "optimization_redesign_or_rollback_decision"
    return "measurement_or_regression_followup"


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
