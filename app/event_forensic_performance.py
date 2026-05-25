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
