"""Pure Event Forensic performance contract helpers.

These helpers are sidecar-safe: they do not run Event Forensic analysis, fetch
network data, change scores, or mutate storage. They exist to make future
behavior-preserving optimization RFCs executable and testable.
"""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence


TIMING_STAGE_FIELDS = (
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

CANDIDATE_ID_FIELDS = ("candidateId", "tradeId", "trade_id", "id", "tradeKey", "candidateTradeKey")
SCORE_FIELDS = ("eventForensicScore", "existingModelScore")
ADMISSION_FIELDS = ("candidateAdmissionStage", "finalDisplayTier", "reviewBucketAfterPolicy", "reviewBucket")


def candidate_performance_cache_key(candidate: Mapping[str, object]) -> str:
    """Return a deterministic key for future pure candidate-context caching."""

    identity = {
        "trade_id": _first_text(candidate, CANDIDATE_ID_FIELDS),
        "wallet": _text(candidate.get("wallet")),
        "condition_id": _text(candidate.get("conditionId") or candidate.get("condition_id")),
        "timestamp": _text(candidate.get("timestamp")),
        "raw_order_side": _text(candidate.get("rawOrderSide") or candidate.get("orderSide") or candidate.get("side")),
        "raw_token_outcome": _text(candidate.get("rawTokenOutcome") or candidate.get("outcome")),
        "economic_side": _text(candidate.get("economicSide")),
    }
    stable = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def build_chunk_metadata(total_items: int, *, chunk_size: int = 500) -> dict[str, object]:
    """Build deterministic progress chunks without changing or hiding rows."""

    total = max(0, int(total_items))
    size = max(1, int(chunk_size))
    chunks = []
    for start in range(0, total, size):
        end = min(start + size, total)
        chunks.append(
            {
                "chunkIndex": len(chunks) + 1,
                "startIndexInclusive": start,
                "endIndexExclusive": end,
                "itemCount": end - start,
            }
        )
    return {
        "totalItems": total,
        "chunkSize": size,
        "chunkCount": len(chunks),
        "coveredItemCount": sum(int(chunk["itemCount"]) for chunk in chunks),
        "rowsHidden": False,
        "chunks": chunks,
    }


def build_score_loop_memoization_metadata(
    *,
    candidate_rows: int,
    unique_wallets: int,
    unique_markets: int,
    unique_domains: int,
    chunk_size: int = 500,
) -> dict[str, object]:
    """Describe score-loop memoization coverage without changing rows."""

    candidate_count = max(0, int(candidate_rows or 0))
    wallet_count = max(0, int(unique_wallets or 0))
    market_count = max(0, int(unique_markets or 0))
    domain_count = max(0, int(unique_domains or 0))
    return {
        "enabled": True,
        "candidateRows": candidate_count,
        "uniqueWallets": wallet_count,
        "uniqueMarkets": market_count,
        "uniqueDomains": domain_count,
        "repeatedWalletCandidateOpportunities": max(0, candidate_count - wallet_count),
        "cacheScopes": [
            "wallet_window_trades",
            "market_notional_samples",
            "domain_notional_samples",
            "funding_resolver_health",
        ],
        "candidateOrderPreserved": True,
        "candidateAdmissionPreserved": True,
        "scoreFormulaPreserved": True,
        "reviewRoutingPreserved": True,
        "exportsPreserved": True,
        "chunkMetadata": build_chunk_metadata(candidate_count, chunk_size=chunk_size),
    }


def build_wallet_context_reuse_metadata(
    *,
    context_pool_trade_rows: int,
    candidate_rows: int,
    requested_wallet_references: int,
    unique_requested_wallets: int,
    wallet_context_count: int,
    prestarted_future_count: int = 0,
    wallet_context_cache_hits: int = 0,
    wallet_context_cache_misses: int = 0,
    scoped_history_cache_hits: int = 0,
    scoped_history_cache_misses: int = 0,
    wallet_history_metrics_cache_hits: int = 0,
    wallet_history_metrics_cache_misses: int = 0,
    domain_profile_cache_hits: int = 0,
    domain_profile_cache_misses: int = 0,
    prefetch_seconds: float = 0.0,
    prepare_seconds: float = 0.0,
    score_seconds: float = 0.0,
) -> dict[str, object]:
    """Describe run-local wallet/context reuse without changing analysis rows."""

    context_rows = max(0, int(context_pool_trade_rows or 0))
    visible_rows = max(0, int(candidate_rows or 0))
    wallet_refs = max(0, int(requested_wallet_references or 0))
    unique_wallets = max(0, int(unique_requested_wallets or 0))
    context_count = max(0, int(wallet_context_count or 0))
    return {
        "enabled": True,
        "runLocalOnly": True,
        "persistentCacheEnabled": False,
        "walletFetchBoundaryPreserved": True,
        "candidateOrderPreserved": True,
        "candidateAdmissionPreserved": True,
        "scoreFormulaPreserved": True,
        "reviewRoutingPreserved": True,
        "exportsPreserved": True,
        "contextPoolTradeRows": context_rows,
        "candidateRows": visible_rows,
        "requestedWalletReferences": wallet_refs,
        "uniqueRequestedWallets": unique_wallets,
        "walletContextCount": context_count,
        "prestartedFutureCount": max(0, int(prestarted_future_count or 0)),
        "repeatedWalletContextOpportunities": max(0, wallet_refs - unique_wallets),
        "walletContextCacheHitsDuringPrepare": max(0, int(wallet_context_cache_hits or 0)),
        "walletContextCacheMissesDuringPrepare": max(0, int(wallet_context_cache_misses or 0)),
        "scopedHistoryCacheHits": max(0, int(scoped_history_cache_hits or 0)),
        "scopedHistoryCacheMisses": max(0, int(scoped_history_cache_misses or 0)),
        "walletHistoryMetricsCacheHits": max(0, int(wallet_history_metrics_cache_hits or 0)),
        "walletHistoryMetricsCacheMisses": max(0, int(wallet_history_metrics_cache_misses or 0)),
        "domainProfileCacheHits": max(0, int(domain_profile_cache_hits or 0)),
        "domainProfileCacheMisses": max(0, int(domain_profile_cache_misses or 0)),
        "effectiveScopedHistoryReuseRatio": _ratio(scoped_history_cache_hits, max(1, context_rows)),
        "effectiveDomainProfileReuseRatio": _ratio(domain_profile_cache_hits, max(1, visible_rows)),
        "prefetchSecondsPerWalletContext": _ratio(prefetch_seconds, context_count),
        "prepareSecondsPerContextRow": _ratio(prepare_seconds, context_rows),
        "scoreSecondsPerCandidateRow": _ratio(score_seconds, visible_rows),
        "cacheScopes": [
            "wallet_context_lookup",
            "scoped_wallet_history",
            "wallet_history_replay_metrics",
            "wallet_domain_profile",
        ],
    }


def build_scorer_context_profile_metadata(
    *,
    candidate_rows: int,
    scored_case_count: int,
    skipped_case_count: int,
    bucket_seconds: Mapping[str, float | int],
    score_loop_seconds: float,
    wallet_context_reuse: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Summarize additive scorer-context profiling buckets."""

    candidate_count = max(0, int(candidate_rows or 0))
    scored_count = max(0, int(scored_case_count or 0))
    skipped_count = max(0, int(skipped_case_count or 0))
    total = max(0.0, float(score_loop_seconds or 0.0))
    normalized = {
        str(key): round(max(0.0, float(value or 0.0)), 6)
        for key, value in bucket_seconds.items()
    }
    top_buckets = [
        {
            "bucket": key,
            "seconds": value,
            "shareOfScoreLoop": _ratio(value, total),
            "secondsPerCandidate": _ratio(value, candidate_count),
        }
        for key, value in sorted(normalized.items(), key=lambda item: item[1], reverse=True)
        if value > 0
    ]
    wallet_reuse = dict(wallet_context_reuse or {})
    return {
        "enabled": True,
        "runLocalOnly": True,
        "additiveMetadataOnly": True,
        "candidateRows": candidate_count,
        "scoredCaseCount": scored_count,
        "skippedCaseCount": skipped_count,
        "scoreLoopSeconds": round(total, 6),
        "bucketSeconds": normalized,
        "topBuckets": top_buckets[:10],
        "candidateOrderPreserved": True,
        "candidateAdmissionPreserved": True,
        "scoreFormulaPreserved": True,
        "reviewRoutingPreserved": True,
        "exportsPreserved": True,
        "scoreTradeCallCovers": [
            "low_probability_checks",
            "near_certainty_checks",
            "cluster_timing_context",
            "weak_history_score_reducers",
            "market_domain_percentile_context",
        ],
        "externalToScoreTradeBuckets": [
            "funding_context_lookup",
            "score_input_lookup",
            "candidate_admission_metadata",
            "wallet_domain_profile_annotation",
            "progress_emit",
        ],
        "walletContextReuseSummary": {
            "repeatedWalletContextOpportunities": int(wallet_reuse.get("repeatedWalletContextOpportunities") or 0),
            "effectiveScopedHistoryReuseRatio": _float_or_zero(wallet_reuse.get("effectiveScopedHistoryReuseRatio")),
            "effectiveDomainProfileReuseRatio": _float_or_zero(wallet_reuse.get("effectiveDomainProfileReuseRatio")),
            "walletFetchBoundaryPreserved": bool(wallet_reuse.get("walletFetchBoundaryPreserved", True)),
        },
        "profilingOverheadNote": (
            "Buckets are coarse run-local timings around existing calls. They do not instrument inside "
            "_score_trade() and should be interpreted as profiler evidence, not scorer semantics."
        ),
    }


def build_score_trade_prepared_context_metadata(
    *,
    candidate_rows: int,
    prepared_context_rows: int,
    score_call_count: int,
    fallback_context_rows: int = 0,
) -> dict[str, object]:
    """Describe prepared scorer-context reuse without changing scoring rows."""

    candidate_count = max(0, int(candidate_rows or 0))
    prepared_count = max(0, int(prepared_context_rows or 0))
    score_calls = max(0, int(score_call_count or 0))
    fallback_count = max(0, int(fallback_context_rows or 0))
    return {
        "enabled": True,
        "runLocalOnly": True,
        "additiveMetadataOnly": True,
        "candidateRows": candidate_count,
        "scoreCallCount": score_calls,
        "preparedContextRows": prepared_count,
        "fallbackContextRows": fallback_count,
        "preparedContextCoverageRatio": _ratio(prepared_count, candidate_count),
        "scoreCallCountUnchanged": score_calls == candidate_count,
        "avoidedRepeatedContextBuilds": prepared_count,
        "cacheScopes": [
            "same_outcome_market_trades",
            "same_market_wallet_trades",
            "prior_same_market_trades",
            "prior_same_asset_trades",
            "related_window_trades",
            "wallet_baseline_notionals",
            "wallet_market_conviction_ratio",
        ],
        "candidateOrderPreserved": True,
        "candidateAdmissionPreserved": True,
        "scoreFormulaPreserved": True,
        "reviewRoutingPreserved": True,
        "exportsPreserved": True,
    }


def build_wallet_api_boundary_trace_metadata(
    *,
    trace_records: Sequence[Mapping[str, object]],
    requested_wallet_references: int,
    unique_requested_wallets: int,
    wallet_context_count: int,
    prestarted_future_count: int = 0,
    prefetch_seconds: float = 0.0,
    truncated_market_count: int = 0,
    analysis_market_count: int = 0,
    live_resolved_market_count: int = 0,
) -> dict[str, object]:
    """Aggregate wallet API-boundary timings without exposing per-wallet rows."""

    records = [dict(record) for record in trace_records if isinstance(record, Mapping)]
    context_count = max(0, int(wallet_context_count or 0))
    wallet_refs = max(0, int(requested_wallet_references or 0))
    unique_wallets = max(0, int(unique_requested_wallets or 0))
    fetched_wallets = len(records)
    unique_fetched_wallets = len({str(record.get("wallet") or "") for record in records if record.get("wallet")})
    duplicate_wallet_requests = max(0, fetched_wallets - unique_fetched_wallets)
    total_seconds = sum(_float_or_zero(record.get("totalSeconds")) for record in records)
    stats_seconds = sum(_float_or_zero(record.get("walletStatsSeconds")) for record in records)
    positions_seconds = sum(_float_or_zero(record.get("walletPositionsSeconds")) for record in records)
    performance_seconds = sum(_float_or_zero(record.get("walletPerformanceSeconds")) for record in records)
    trade_rows = sum(max(0, int(record.get("walletStatsTradeRows") or 0)) for record in records)
    position_rows = sum(max(0, int(record.get("walletPositionsRows") or 0)) for record in records)
    inferred_request_count = fetched_wallets * 4
    return {
        "enabled": True,
        "runLocalOnly": True,
        "additiveMetadataOnly": True,
        "walletFetchBoundaryPreserved": True,
        "paginationSemanticsPreserved": True,
        "candidateOrderPreserved": True,
        "candidateAdmissionPreserved": True,
        "scoreFormulaPreserved": True,
        "reviewRoutingPreserved": True,
        "exportsPreserved": True,
        "requestedWalletReferences": wallet_refs,
        "uniqueRequestedWallets": unique_wallets,
        "walletContextCount": context_count,
        "walletContextFetchRecords": fetched_wallets,
        "uniqueFetchedWallets": unique_fetched_wallets,
        "duplicateExactWalletContextRequests": duplicate_wallet_requests,
        "safeExactDedupeOpportunity": duplicate_wallet_requests > 0,
        "prestartedFutureCount": max(0, int(prestarted_future_count or 0)),
        "repeatedWalletReferencesAlreadyDeduped": max(0, wallet_refs - unique_wallets),
        "prefetchSeconds": round(max(0.0, float(prefetch_seconds or 0.0)), 6),
        "observedWalletBoundarySeconds": round(total_seconds, 6),
        "walletStatsSeconds": round(stats_seconds, 6),
        "walletPositionsSeconds": round(positions_seconds, 6),
        "walletPerformanceSeconds": round(performance_seconds, 6),
        "secondsPerWalletContext": _ratio(prefetch_seconds, context_count),
        "observedBoundarySecondsPerWallet": _ratio(total_seconds, fetched_wallets),
        "walletStatsSecondsPerWallet": _ratio(stats_seconds, fetched_wallets),
        "walletPositionsSecondsPerWallet": _ratio(positions_seconds, fetched_wallets),
        "inferredRequestCount": inferred_request_count,
        "inferredRequestsPerWalletContext": _ratio(inferred_request_count, context_count),
        "requestClassCounts": {
            "data_api_traded_inferred": fetched_wallets,
            "data_api_wallet_trades_inferred": fetched_wallets,
            "polygon_rpc_nonce_inferred": fetched_wallets,
            "data_api_positions_inferred": fetched_wallets,
        },
        "requestClassSeconds": {
            "wallet_stats_bundle": round(stats_seconds, 6),
            "wallet_positions": round(positions_seconds, 6),
            "wallet_performance_local": round(performance_seconds, 6),
        },
        "rowsReturned": {
            "walletStatsTradeRows": trade_rows,
            "walletPositionRows": position_rows,
            "walletStatsTradeRowsPerWallet": _ratio(trade_rows, fetched_wallets),
            "walletPositionRowsPerWallet": _ratio(position_rows, fetched_wallets),
        },
        "paginationContext": {
            "truncatedMarketCount": max(0, int(truncated_market_count or 0)),
            "analysisMarketCount": max(0, int(analysis_market_count or 0)),
            "liveResolvedMarketCount": max(0, int(live_resolved_market_count or 0)),
            "subsetOnlyLikely": bool(live_resolved_market_count and analysis_market_count < live_resolved_market_count),
        },
        "retryFallbackVisibility": "not_instrumented_at_low_level",
        "batchingImplemented": False,
        "batchingApproved": False,
        "safePatchRecommendation": (
            "exact_duplicate_wallet_request_dedupe_possible"
            if duplicate_wallet_requests > 0
            else "no_safe_runtime_patch_from_trace_without_api_equivalence_rfc"
        ),
    }


def summarize_timing_costs(
    timings: Mapping[str, object],
    *,
    candidate_rows: int = 0,
    candidate_wallets: int = 0,
    market_count: int = 0,
) -> dict[str, object]:
    """Summarize timing fields into per-row/per-wallet cost metadata."""

    normalized = {
        field: _float_or_zero(timings.get(field))
        for field in TIMING_STAGE_FIELDS
        if timings.get(field) not in (None, "")
    }
    total = normalized.get("total_seconds", 0.0)
    candidate_count = max(0, int(candidate_rows or 0))
    wallet_count = max(0, int(candidate_wallets or 0))
    markets = max(0, int(market_count or 0))
    score_seconds = normalized.get("score_candidates_seconds", 0.0)
    prefetch_seconds = normalized.get("prefetch_wallet_context_seconds", 0.0)
    return {
        "timings": normalized,
        "dominantStage": _dominant_stage(normalized),
        "scoreSecondsPerCandidateRow": _ratio(score_seconds, candidate_count),
        "prefetchSecondsPerCandidateWallet": _ratio(prefetch_seconds, wallet_count),
        "candidateRowsPerWallet": _ratio(candidate_count, wallet_count),
        "candidateRowsPerMarket": _ratio(candidate_count, markets),
        "candidateWalletsPerMarket": _ratio(wallet_count, markets),
        "scoreShareOfTotal": _ratio(score_seconds, total),
        "prefetchShareOfTotal": _ratio(prefetch_seconds, total),
    }


def compare_candidate_output_contract(
    before_rows: Sequence[Mapping[str, object]],
    after_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Compare output invariants future performance patches must preserve."""

    violations: list[str] = []
    before_ids = [_candidate_id(row, index) for index, row in enumerate(before_rows)]
    after_ids = [_candidate_id(row, index) for index, row in enumerate(after_rows)]
    if before_ids != after_ids:
        violations.append("candidate_ids_or_order_changed")
    if len(before_rows) != len(after_rows):
        violations.append("candidate_count_changed")

    for index, before in enumerate(before_rows[: min(len(before_rows), len(after_rows))]):
        after = after_rows[index]
        for field in SCORE_FIELDS:
            if _text(before.get(field)) != _text(after.get(field)):
                violations.append(f"{field}_changed_at_{index}")
        for field in ADMISSION_FIELDS:
            if _text(before.get(field)) != _text(after.get(field)):
                violations.append(f"{field}_changed_at_{index}")

    before_rank = _rank_key(before_rows)
    after_rank = _rank_key(after_rows)
    if before_rank != after_rank:
        violations.append("rank_order_changed")
    return {
        "passed": not violations,
        "violations": violations,
        "candidateCountBefore": len(before_rows),
        "candidateCountAfter": len(after_rows),
    }


def _candidate_id(row: Mapping[str, object], index: int) -> str:
    value = _first_text(row, CANDIDATE_ID_FIELDS)
    if value:
        return value
    return candidate_performance_cache_key(row) or f"candidate-{index + 1}"


def _first_text(row: Mapping[str, object], fields: Sequence[str]) -> str:
    for field in fields:
        value = _text(row.get(field))
        if value:
            return value
    return ""


def _rank_key(rows: Sequence[Mapping[str, object]]) -> list[str]:
    ranked = sorted(
        enumerate(rows),
        key=lambda item: (
            -_float_or_zero(item[1].get("eventForensicScore")),
            item[0],
        ),
    )
    return [_candidate_id(row, index) for index, row in ranked]


def _dominant_stage(timings: Mapping[str, float]) -> str:
    candidates = {
        key: float(value)
        for key, value in timings.items()
        if key != "total_seconds" and key.endswith("_seconds")
    }
    if not candidates:
        return "unknown"
    return max(candidates.items(), key=lambda item: item[1])[0]


def _ratio(numerator: float | int, denominator: float | int) -> float:
    try:
        denominator_value = float(denominator)
        if denominator_value == 0:
            return 0.0
        return round(float(numerator) / denominator_value, 6)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _float_or_zero(value: object) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
