#!/usr/bin/env python3
"""Analyze Event Forensic wallet API-boundary trace output."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "event_forensic_wallet_api_boundary_trace"
SCHEMA_VERSION = "event_forensic_wallet_api_boundary_trace_v1"
DEFAULT_CURRENT = Path("validation_outputs/event_forensic_wallet_api_boundary_trace_live_20260526/summary.json")
DEFAULT_PROFILE = Path("validation_outputs/event_forensic_scorer_context_profile_live_20260526_112806/summary.json")
DEFAULT_PREPARED = Path("validation_outputs/event_forensic_scorer_context_optimization_live_20260526_115811/summary.json")
DEFAULT_STATIC_EQUIVALENCE = Path("validation_outputs/event_forensic_wallet_api_boundary_static_equivalence_20260526.json")
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_wallet_api_boundary_trace_20260526.json")


def build_wallet_api_boundary_trace_analysis(
    *,
    current_payload: Mapping[str, object],
    profile_payload: Mapping[str, object] | None = None,
    prepared_payload: Mapping[str, object] | None = None,
    static_equivalence_payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    current = _measurement_from_payload(current_payload)
    profile = _measurement_from_payload(profile_payload or {})
    prepared = _measurement_from_payload(prepared_payload or {})
    static_equivalence = _static_equivalence(static_equivalence_payload or {})
    trace = current.get("walletApiBoundaryTrace") if isinstance(current.get("walletApiBoundaryTrace"), Mapping) else {}
    pagination_gate = _pagination_gate(current)
    api_gate = _api_gate(trace, static_equivalence)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": False,
        "networkUsed": bool(current.get("networkUsed")),
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "storageMutated": False,
        "wholeEventCompletenessClaim": False,
        "scope": {
            "eventSlug": current.get("eventSlug", ""),
            "subsetOnly": bool(current.get("subsetOnly")),
            "analysisMarketCount": current.get("analysisMarketCount", 0),
            "liveResolvedMarketCount": current.get("liveResolvedMarketCount", 0),
            "wholeEventCompletenessClaim": False,
        },
        "currentMeasurement": current,
        "profileBaseline": profile,
        "preparedScorerContextBaseline": prepared,
        "comparisonProfileToCurrent": _comparison(profile, current),
        "comparisonPreparedToCurrent": _comparison(prepared, current),
        "staticEquivalence": static_equivalence,
        "apiBoundaryTrace": dict(trace),
        "duplicateOpportunitySummary": {
            "duplicateExactWalletContextRequests": int(trace.get("duplicateExactWalletContextRequests") or 0),
            "repeatedWalletReferencesAlreadyDeduped": int(trace.get("repeatedWalletReferencesAlreadyDeduped") or 0),
            "safeExactDedupeOpportunity": bool(trace.get("safeExactDedupeOpportunity")),
            "safePatchRecommendation": str(trace.get("safePatchRecommendation") or ""),
            "batchingImplemented": bool(trace.get("batchingImplemented")),
            "batchingApproved": bool(trace.get("batchingApproved")),
        },
        "paginationAssessment": {
            "gateDecision": pagination_gate,
            "truncatedMarketCount": current.get("truncatedMarketCount", 0),
            "analysisMarketCount": current.get("analysisMarketCount", 0),
            "liveResolvedMarketCount": current.get("liveResolvedMarketCount", 0),
            "scopeClaim": "subset_only_not_whole_event_complete" if current.get("subsetOnly") else "full_scope_or_unknown",
            "operatorPlanRequired": pagination_gate == "pagination_operator_plan_required",
        },
        "gateDecision": api_gate,
        "paginationGateDecision": pagination_gate,
        "optimizationDecision": _optimization_decision(trace),
        "forbiddenScopePreserved": {
            "phase3Runtime": False,
            "scoringWeightsChanged": False,
            "thresholdsChanged": False,
            "directGateChanges": False,
            "storageSchemaChanged": False,
            "uiSortingChanged": False,
            "tradingOrPrivateKeyUsed": False,
            "paginationSemanticsChanged": False,
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
    parser.add_argument("--current", default=str(DEFAULT_CURRENT))
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--prepared", default=str(DEFAULT_PREPARED))
    parser.add_argument("--static-equivalence", default=str(DEFAULT_STATIC_EQUIVALENCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payload = build_wallet_api_boundary_trace_analysis(
        current_payload=load_json_object(args.current),
        profile_payload=_load_optional_json(args.profile),
        prepared_payload=_load_optional_json(args.prepared),
        static_equivalence_payload=_load_optional_json(args.static_equivalence),
    )
    write_json(payload, args.output)
    if not args.quiet:
        print(
            json.dumps(
                {
                    "output": args.output,
                    "gateDecision": payload["gateDecision"],
                    "paginationGateDecision": payload["paginationGateDecision"],
                },
                sort_keys=True,
            )
        )
    return 0


def _load_optional_json(path_raw: str | Path) -> dict[str, object]:
    path = Path(path_raw)
    if not path.exists():
        return {}
    return load_json_object(path)


def _measurement_from_payload(payload: Mapping[str, object]) -> dict[str, object]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    live_result = payload.get("liveResult") if isinstance(payload.get("liveResult"), Mapping) else {}
    report_summary = payload.get("reportSummary") if isinstance(payload.get("reportSummary"), Mapping) else {}
    timings = report_summary.get("timings") if isinstance(report_summary.get("timings"), Mapping) else {}
    if not timings and isinstance(live_result.get("timings"), Mapping):
        timings = live_result["timings"]
    performance = _load_performance(live_result.get("eventAnalysisJsonPath"))
    if not performance and isinstance(payload.get("performance"), Mapping):
        performance = dict(payload["performance"])
    return {
        "sourceOutputDir": str(payload.get("outputDir") or live_result.get("outputDir") or ""),
        "eventSlug": str(summary.get("eventSlug") or live_result.get("eventSlug") or ""),
        "subsetOnly": bool(summary.get("subsetOnly", payload.get("subsetOnly", False))),
        "analysisMarketCount": _int_value(summary.get("analysisMarketCount") or live_result.get("analysisMarketCount")),
        "liveResolvedMarketCount": _int_value(summary.get("liveResolvedMarketCount") or live_result.get("liveResolvedMarketCount")),
        "rawTradeRows": _int_value(summary.get("rawTradeRows") or live_result.get("rawTradeCount") or performance.get("trade_collection_raw_trade_rows")),
        "candidateRows": _int_value(summary.get("candidateRows") or live_result.get("candidateTradeCount") or performance.get("candidate_trade_count_visible")),
        "candidateWalletCount": _int_value(summary.get("candidateWalletCount") or live_result.get("candidateWalletCount") or performance.get("candidate_wallet_count")),
        "truncatedMarketCount": _int_value(summary.get("truncatedMarketCount") or live_result.get("truncatedMarketCount") or performance.get("truncated_market_count")),
        "totalSeconds": _float_value(summary.get("totalSeconds") or live_result.get("wallClockSeconds") or performance.get("total_seconds")),
        "dominantBottleneck": str(summary.get("dominantBottleneck") or live_result.get("dominantBottleneck") or "unknown"),
        "gateDecision": str(summary.get("gateDecision") or live_result.get("gateDecision") or ""),
        "networkUsed": bool(payload.get("networkUsed")),
        "timings": {str(key): _float_value(value) for key, value in dict(timings).items()},
        "walletApiBoundaryTrace": performance.get("wallet_api_boundary_trace") if isinstance(performance, Mapping) else {},
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


def _static_equivalence(payload: Mapping[str, object]) -> dict[str, object]:
    comparison = payload.get("contractComparisonAgainstSelf")
    passed = bool(comparison.get("passed")) if isinstance(comparison, Mapping) else bool(payload.get("passed", True))
    return {
        "available": bool(payload),
        "passed": passed,
        "candidateCount": _int_value(payload.get("candidateCount")),
        "exportRowCount": _int_value(payload.get("exportRowCount")),
        "networkUsed": bool(payload.get("networkUsed")),
        "runtimeBehaviorChanged": bool(payload.get("runtimeBehaviorChanged")),
    }


def _comparison(before: Mapping[str, object], after: Mapping[str, object]) -> dict[str, object]:
    before_candidates = _int_value(before.get("candidateRows"))
    after_candidates = _int_value(after.get("candidateRows"))
    before_wallets = _int_value(before.get("candidateWalletCount"))
    after_wallets = _int_value(after.get("candidateWalletCount"))
    before_timings = before.get("timings") if isinstance(before.get("timings"), Mapping) else {}
    after_timings = after.get("timings") if isinstance(after.get("timings"), Mapping) else {}
    return {
        "candidateRowsDelta": after_candidates - before_candidates,
        "candidateWalletCountDelta": after_wallets - before_wallets,
        "totalSecondsDelta": round(_float_value(after.get("totalSeconds")) - _float_value(before.get("totalSeconds")), 3),
        "scoreCandidatesSecondsDelta": round(
            _float_value(after_timings.get("score_candidates_seconds"))
            - _float_value(before_timings.get("score_candidates_seconds")),
            3,
        ),
        "prefetchWalletContextSecondsDelta": round(
            _float_value(after_timings.get("prefetch_wallet_context_seconds"))
            - _float_value(before_timings.get("prefetch_wallet_context_seconds")),
            3,
        ),
        "scoreSecondsPer1000CandidatesBefore": _per_1000(
            _float_value(before_timings.get("score_candidates_seconds")),
            before_candidates,
        ),
        "scoreSecondsPer1000CandidatesAfter": _per_1000(
            _float_value(after_timings.get("score_candidates_seconds")),
            after_candidates,
        ),
        "prefetchSecondsPer1000WalletsBefore": _per_1000(
            _float_value(before_timings.get("prefetch_wallet_context_seconds")),
            before_wallets,
        ),
        "prefetchSecondsPer1000WalletsAfter": _per_1000(
            _float_value(after_timings.get("prefetch_wallet_context_seconds")),
            after_wallets,
        ),
    }


def _api_gate(trace: Mapping[str, object], static_equivalence: Mapping[str, object]) -> str:
    if static_equivalence and not bool(static_equivalence.get("passed")):
        return "regression_stop"
    if not trace:
        return "measurement_blocked"
    if int(trace.get("duplicateExactWalletContextRequests") or 0) <= 0:
        return "api_boundary_no_safe_patch"
    return "api_boundary_patch_partial"


def _pagination_gate(measurement: Mapping[str, object]) -> str:
    truncated = _int_value(measurement.get("truncatedMarketCount"))
    if truncated > 0:
        return "pagination_operator_plan_required"
    return "pagination_live_measurement_clean"


def _optimization_decision(trace: Mapping[str, object]) -> dict[str, object]:
    duplicate_requests = int(trace.get("duplicateExactWalletContextRequests") or 0)
    return {
        "runtimePatchImplemented": False,
        "safeExactDedupeOpportunity": duplicate_requests > 0,
        "duplicateExactWalletContextRequests": duplicate_requests,
        "batchingRequiresSeparateApproval": True,
        "reason": (
            "Trace found exact duplicate wallet-context calls that could be deduped."
            if duplicate_requests > 0
            else "Event Forensic already dedupes wallet-context requests by wallet before the API boundary; "
            "batching would need an API-equivalence proof and separate implementation approval."
        ),
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


def _per_1000(seconds: float, count: int) -> float:
    if count <= 0:
        return 0.0
    return round((seconds / count) * 1000, 6)


if __name__ == "__main__":
    raise SystemExit(main())
