from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from threading import Lock
from time import perf_counter
from urllib.parse import unquote, urlparse

from app.config import (
    FUNDING_TRACE_MODE_CACHE_ONLY,
    FUNDING_TRACE_MODE_DISABLED,
    FUNDING_TRACE_MODE_LIVE_RPC,
    AppConfig,
    funding_trace_mode,
    normalize_funding_trace_mode,
    validation_cache_only_mode,
)
from app.event_context import EventContextResolver
from app.funding_context import (
    PROXY_FUNDING_EVIDENCE_GRADES,
    FundingContext,
    FundingResolver,
    grade_funding_evidence,
    unknown_funding_context,
)
from app.event_forensic_performance import (
    build_score_loop_memoization_metadata,
    build_score_trade_prepared_context_metadata,
    build_scorer_context_profile_metadata,
    build_wallet_api_boundary_trace_metadata,
    build_wallet_context_reuse_metadata,
)
from app.report_pointer import POINTER_FIELD, attach_indexer_warehouse_pointer
from app.models import FlaggedCase, Market, Trade
from app.polymarket import MAX_TRADES_OFFSET, PolymarketClient
from app.side_outcome import UNKNOWN, normalize_cluster_direction, normalize_side_outcome
from app.scanner import (
    ProgressEvent,
    HARD_EVIDENCE_REVIEW_TIER,
    REPRICING_SOURCE_QUALITY_MECHANICAL,
    REPRICING_SOURCE_QUALITY_NONE,
    REPRICING_SOURCE_QUALITY_STRONG,
    REPRICING_SOURCE_QUALITY_WEAK,
    STRONG_RISK_ATTRIBUTION_FIELDS,
    SUSPICIOUS_FUNDING_QUALITY_MODERATE,
    SUSPICIOUS_FUNDING_QUALITY_STRONG,
    _suspicious_funding_hard_evidence_eligible,
    _annotate_domain_peer_history,
    _annotate_hard_evidence_review,
    _annotate_preclassification_linkage,
    _apply_candidate_admission_metadata,
    _build_candidate_trade_set,
    _build_structural_pre_admission_funnel,
    _build_structural_pre_admission_metadata,
    _build_wallet_inspection,
    _capital_at_risk_usdc,
    build_score_trade_prepared_context,
    _case_survives_output_threshold,
    _case_has_hard_evidence_review,
    _classify_execution_state,
    _domain_for_trade,
    _emit_progress,
    _event_family_key,
    _funding_cache_key,
    _group_domain_trades,
    _group_market_trades,
    _group_wallet_trades,
    _is_opening_exposure,
    _looks_like_deadline_market,
    _score_trade,
    _should_trace_funding,
    _candidate_admission_near_miss_records,
    _finalize_structural_pre_admission_funnel,
    _funding_availability_report_lines,
    _structural_pre_admission_prefunding_pool,
    _structural_pre_admission_funnel_markdown,
    _stop_requested,
    _validate_candidate_admissions,
    _wallet_market_conviction_ratio,
)
from app.storage import Storage
from app.wallet_analytics import WalletPerformance, compute_wallet_performance


MIN_RESOLVED_OUTCOME_PRICE = Decimal("0.97")
EVENT_ANALYSIS_VERSION = "v1"
EVENT_FORENSIC_WALLET_PREFETCH_WORKERS = 12
EVENT_FORENSIC_MARKET_FETCH_WORKERS = 6
EVENT_FORENSIC_PRICE_HISTORY_WORKERS = 8
EVENT_FORENSIC_FUNDING_PREFETCH_WORKERS = 8
EVENT_FORENSIC_VISIBLE_TRADE_LIMIT = 200
EVENT_FORENSIC_VISIBLE_WALLET_LIMIT = 120
EVENT_FORENSIC_VISIBLE_CLUSTER_LIMIT = 60
EVENT_FORENSIC_GRAPH_TRADE_LIMIT = 24
EVENT_FORENSIC_GRAPH_WALLET_LIMIT = 18
EVENT_FORENSIC_GRAPH_CLUSTER_LIMIT = 12
EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD = 40
WEAK_HISTORY_NEAR_CERTAINTY_REVIEW_REQUIRED_TIER = "weak_history_near_certainty_review_required"
WEAK_HISTORY_NEAR_CERTAINTY_REVIEW_REASON = (
    "Weak economic history plus a near-certain later-winning entry is review-required context, "
    "not primary Event Forensic placement."
)
EVENT_FORENSIC_CASE_FAMILY_EVENT_LIMIT = 30
EVENT_FORENSIC_HIGH_ASYMMETRY_DOMAINS = {"Politics", "Geopolitics", "Middle East", "Ukraine / war"}
EVENT_FORENSIC_PUBLIC_BETTING_DOMAINS = {"Sports", "Entertainment", "Crypto", "Macro / rates"}
EVENT_FORENSIC_SPORTS_KEYWORDS = (
    "ufc",
    "fight night",
    "mma",
    "boxing",
    "nba",
    "nfl",
    "mlb",
    "nhl",
    "soccer",
    "football",
    "tennis",
    "golf",
    "formula 1",
    "f1",
    "champions league",
    "premier league",
    "world cup",
    "super bowl",
)
POOR_HISTORY_SAMPLE_MIN = 20
POOR_HISTORY_WIN_RATE_MAX = 15.0
PUBLIC_POWER_USER_TOTAL_PREDICTIONS_MIN = 100
PUBLIC_POWER_USER_HISTORY_TRADE_MIN = 100
PUBLIC_POWER_USER_EVENT_TRADE_MIN = 30
PUBLIC_POWER_USER_UNIQUE_MARKET_MIN = 50
HIGH_VOLUME_EVENT_TRADE_MIN = 25
HIGH_VOLUME_NOTABLE_TRADE_MIN = 20
HIGH_VOLUME_WINNING_OPENING_MIN = 15
HIGH_VOLUME_SIBLING_CONTEXT_MIN = 50
EVENT_SATURATION_TRADE_MIN = 30
EVENT_SATURATION_OPENING_MIN = 20
EVENT_SATURATION_WINNING_OPENING_MIN = 15
NEAR_CERTAINTY_PRICE = 0.94
VERY_NEAR_CERTAINTY_PRICE = 0.97
GENERIC_CASE_FAMILY_TAG_SLUGS = {
    "business",
    "crypto",
    "culture",
    "elections",
    "finance",
    "geopolitics",
    "global",
    "news",
    "politics",
    "sports",
    "technology",
    "trump",
    "weather",
    "world",
}
GENERIC_CASE_FAMILY_TOKENS = {
    "after",
    "before",
    "election",
    "leader",
    "market",
    "president",
    "released",
    "single",
}
CASE_FAMILY_ACTION_GROUPS = {
    "removal": {
        "arrest",
        "arrested",
        "capture",
        "captured",
        "coup",
        "custody",
        "detain",
        "detained",
        "exile",
        "exiled",
        "flee",
        "flees",
        "leave",
        "leaves",
        "ousted",
        "out",
        "remove",
        "removed",
        "removal",
        "resign",
        "resigned",
        "resigns",
        "surrender",
    },
    "military_action": {
        "airstrike",
        "attack",
        "attacks",
        "bomb",
        "bombed",
        "bombs",
        "invade",
        "invades",
        "invasion",
        "military",
        "strike",
        "strikes",
        "war",
    },
}
CASE_FAMILY_META_MARKET_TOKENS = {
    "body",
    "cam",
    "camera",
    "check",
    "debate",
    "fact",
    "footage",
    "interview",
    "mention",
    "mentioned",
    "mentions",
    "odds",
    "over",
    "post",
    "said",
    "say",
    "says",
    "speech",
    "statement",
    "staged",
    "tweet",
    "tweets",
    "under",
}

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "before",
    "by",
    "for",
    "if",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "will",
    "with",
}
MONTH_WORDS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}


@dataclass(slots=True)
class ResolvedEvent:
    input_value: str
    canonical_url: str
    event_id: str
    event_slug: str
    event_title: str
    event_description: str
    event_category: str
    event_closed: bool
    event_end_date: str | None
    source_market_slug: str | None
    source_condition_id: str | None
    event_payload: dict[str, object]
    markets: dict[str, Market]
    market_payloads: dict[str, dict[str, object]]
    event_family_id: str
    family_tokens: set[str]


@dataclass(slots=True)
class CandidateReplayContext:
    trade: Trade
    market: Market
    trade_domain: str
    wallet_inspection: object
    wallet_history_trades: list[Trade]
    wallet_performance: WalletPerformance
    market_window_trades: list[Trade]
    domain_window_trades: list[Trade]
    event_context: object
    funding_cache_key: tuple[str, str] | None
    prior_wallet_gap_days: float | None = None
    observed_post_trade_gap_days: float | None = None
    family_key: str = ""
    prior_family_trade_count: int = 0
    prior_family_market_count: int = 0
    event_family_share: float = 0.0
    funding_skip_reason: str = ""
    prepared_score_context: object | None = None


@dataclass(slots=True)
class AnalysisScopeContext:
    analysis_scope: str
    analysis_markets: dict[str, Market]
    selected_market: Market | None
    selected_condition_id: str | None
    selected_market_slug: str | None
    selected_market_title: str | None


def _effective_funding_trace_mode(include_blockchain: bool, requested_mode: str | None = None) -> str:
    if not include_blockchain:
        return FUNDING_TRACE_MODE_DISABLED
    configured = funding_trace_mode()
    return normalize_funding_trace_mode(requested_mode, default=configured)


def _normalize_analysis_window_bound(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(UTC)


def _time_window_filter_trades(
    trades: list[Trade],
    *,
    start_at: datetime | None,
    end_at: datetime | None,
) -> list[Trade]:
    if start_at is None and end_at is None:
        return trades
    filtered: list[Trade] = []
    for trade in trades:
        timestamp = _normalize_analysis_window_bound(trade.timestamp)
        if timestamp is None:
            continue
        if start_at is not None and timestamp < start_at:
            continue
        if end_at is not None and timestamp > end_at:
            continue
        filtered.append(trade)
    return filtered


def _append_wallet_api_trace(
    trace_records: list[dict[str, object]] | None,
    trace_lock: Lock | None,
    record: dict[str, object],
) -> None:
    if trace_records is None:
        return
    if trace_lock is None:
        trace_records.append(record)
        return
    with trace_lock:
        trace_records.append(record)


def _funding_skip_reason_for_mode(mode: str, *, include_blockchain: bool) -> str:
    if not include_blockchain:
        return "blockchain_disabled"
    if mode == FUNDING_TRACE_MODE_DISABLED:
        return "funding_trace_disabled_no_rpc_mode"
    if mode == FUNDING_TRACE_MODE_CACHE_ONLY:
        return "funding_trace_cache_only_miss"
    return "funding_trace_not_requested"


def _funding_progress_stage(mode: str) -> str:
    if mode == FUNDING_TRACE_MODE_DISABLED:
        return "Skipping blockchain funding traces"
    if mode == FUNDING_TRACE_MODE_CACHE_ONLY:
        return "Checking cached blockchain linkage"
    return "Tracing blockchain linkage"


class EventForensicAnalyzer:
    def __init__(self, client: PolymarketClient, storage: Storage, config: AppConfig) -> None:
        self._client = client
        self._storage = storage
        self._config = config
        self._event_context_resolver = EventContextResolver(self._config.data_dir)
        self._funding_resolver = FundingResolver()

    def analyze(
        self,
        input_value: str,
        reports_dir: Path,
        *,
        min_notional: Decimal | None = None,
        include_related_markets: bool = True,
        include_blockchain: bool = True,
        funding_trace_mode: str | None = None,
        analysis_scope: str | None = None,
        selected_condition_id: str | None = None,
        selected_market_slug: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        indexer_warehouse_pointer: dict[str, object] | None = None,
        progress_callback: callable | None = None,
        stop_event: object | None = None,
    ) -> dict[str, object]:
        started_at = datetime.now(UTC)
        analysis_started = perf_counter()
        window_start_at = _normalize_analysis_window_bound(start_at)
        window_end_at = _normalize_analysis_window_bound(end_at)
        if window_start_at is not None and window_end_at is not None and window_end_at <= window_start_at:
            raise ValueError("End datetime must be later than start datetime.")
        threshold = min_notional if min_notional is not None else Decimal("250")
        runtime_validation_cache_only = validation_cache_only_mode()
        effective_funding_trace_mode = _effective_funding_trace_mode(
            include_blockchain,
            funding_trace_mode,
        )
        if runtime_validation_cache_only and effective_funding_trace_mode == FUNDING_TRACE_MODE_LIVE_RPC:
            effective_funding_trace_mode = FUNDING_TRACE_MODE_CACHE_ONLY
        self._funding_resolver = FundingResolver(trace_mode=effective_funding_trace_mode)
        performance: dict[str, object] = {}
        performance["funding_trace_mode"] = effective_funding_trace_mode
        performance["fundingTraceMode"] = effective_funding_trace_mode
        if effective_funding_trace_mode == FUNDING_TRACE_MODE_DISABLED:
            performance["funding_trace_disabled_reason"] = _funding_skip_reason_for_mode(
                effective_funding_trace_mode,
                include_blockchain=include_blockchain,
            )
            performance["fundingTraceDisabledReason"] = performance["funding_trace_disabled_reason"]

        stage_started = perf_counter()
        _emit_progress(progress_callback, 4, "Resolving input", "Parsing the Polymarket URL")
        resolved = self.resolve_input(input_value)
        scope_context = _resolve_analysis_scope_context(
            resolved,
            analysis_scope=analysis_scope,
            selected_condition_id=selected_condition_id,
            selected_market_slug=selected_market_slug,
        )
        case_family_expansion = self._expand_case_family_scope(
            resolved,
            scope_context,
            include_related_markets=include_related_markets,
        )
        if case_family_expansion["added_market_count"]:
            scope_context = _resolve_analysis_scope_context(
                resolved,
                analysis_scope=scope_context.analysis_scope,
                selected_condition_id=scope_context.selected_condition_id,
                selected_market_slug=scope_context.selected_market_slug,
            )
        performance["resolve_input_seconds"] = round(perf_counter() - stage_started, 2)
        performance["case_family_added_market_count"] = case_family_expansion["added_market_count"]
        performance["case_family_added_event_count"] = case_family_expansion["added_event_count"]
        eligibility = self._eligibility_payload(resolved)
        if not eligibility["eligible"]:
            report = self._build_ineligible_report(
                started_at=started_at,
                resolved=resolved,
                scope_context=scope_context,
                threshold=threshold,
                eligibility=eligibility,
                include_related_markets=include_related_markets,
            )
            export_files = self._write_report_bundle(
                started_at,
                reports_dir,
                report,
                suspicious_trades=[],
                suspicious_wallets=[],
                ranked_wallets=[],
                wallet_clusters=[],
                wallet_graph={"nodes": [], "edges": []},
                related_markets=[],
                candidate_audit_rows=[],
                raw_bundle={"analysis_scope_metadata": _analysis_scope_metadata(resolved, scope_context)},
            )
            report["export_files"] = export_files
            report["report_json_path"] = export_files["report_json_path"]
            report["report_md_path"] = export_files["event_report_md_path"]
            report["report_txt_path"] = export_files["event_report_md_path"]
            _emit_progress(progress_callback, 100, "Preview only", eligibility["reason"])
            return report

        wallet_cache: dict[str, tuple[object, list[Trade], WalletPerformance]] = {}
        wallet_api_trace_records: list[dict[str, object]] = []
        wallet_api_trace_lock = Lock()
        wallet_prefetch_executor: ThreadPoolExecutor | None = None
        warm_wallet_futures: dict[str, Future] = {}
        if EVENT_FORENSIC_WALLET_PREFETCH_WORKERS > 1:
            wallet_prefetch_executor = ThreadPoolExecutor(
                max_workers=EVENT_FORENSIC_WALLET_PREFETCH_WORKERS
            )

        def seed_wallet_prefetch(_condition_id: str, market_trades: list[Trade]) -> None:
            if wallet_prefetch_executor is None:
                return
            for trade in market_trades:
                wallet = trade.wallet
                if not wallet or trade.notional < threshold:
                    continue
                if wallet in wallet_cache or wallet in warm_wallet_futures:
                    continue
                warm_wallet_futures[wallet] = wallet_prefetch_executor.submit(
                    self._fetch_wallet_context,
                    wallet,
                    scope_context.analysis_markets,
                    trace_records=wallet_api_trace_records,
                    trace_lock=wallet_api_trace_lock,
                )

        stage_started = perf_counter()
        _emit_progress(
            progress_callback,
            10,
            "Loading event",
            (
                f"Resolved event '{resolved.event_title}' with {len(resolved.markets)} market(s); "
                f"scope is {_analysis_scope_label(scope_context.analysis_scope)}"
            ),
        )

        single_market_sibling_context_count = (
            max(len(resolved.markets) - len(scope_context.analysis_markets), 0)
            if scope_context.selected_condition_id
            else 0
        )
        trade_collection_progress: dict[str, object] = {}
        raw_trades, truncated_market_count = self._collect_event_trades(
            resolved,
            minimum_notional=threshold,
            start_at=window_start_at,
            end_at=window_end_at,
            progress_callback=progress_callback,
            stop_event=stop_event,
            on_market_trades=seed_wallet_prefetch,
            collection_progress=trade_collection_progress,
            single_market_sibling_context_count=single_market_sibling_context_count,
            selected_condition_id_present=bool(scope_context.selected_condition_id),
            total_event_market_count=len(resolved.markets),
        )
        performance["collect_event_trades_seconds"] = round(perf_counter() - stage_started, 2)
        performance["truncated_market_count"] = truncated_market_count
        trade_collection_progress.update(
            {
                "tradeCollectionStage": "completed",
                "collectionElapsedSeconds": performance["collect_event_trades_seconds"],
                "collectionRiskClass": _trade_collection_risk_class(
                    truncated_market_count=truncated_market_count,
                    collection_elapsed_seconds=float(performance["collect_event_trades_seconds"] or 0.0),
                    analysis_market_count=len(scope_context.analysis_markets),
                    total_event_market_count=len(resolved.markets),
                    selected_condition_id_present=bool(scope_context.selected_condition_id),
                ),
                "singleMarketSiblingContextCount": single_market_sibling_context_count,
            }
        )
        performance["trade_collection_progress"] = dict(trade_collection_progress)
        performance["trade_collection_market_total"] = trade_collection_progress.get("analysisMarketTotal", len(resolved.markets))
        performance["trade_collection_market_completed"] = trade_collection_progress.get("analysisMarketCompleted", len(resolved.markets))
        performance["trade_collection_raw_trade_rows"] = trade_collection_progress.get("rawTradeRowsCollectedSoFar", len(raw_trades))
        performance["trade_collection_truncated_markets"] = truncated_market_count
        performance["trade_collection_elapsed_seconds"] = performance["collect_event_trades_seconds"]
        performance["trade_collection_risk_class"] = trade_collection_progress.get("collectionRiskClass", "")
        performance["single_market_sibling_context_count"] = single_market_sibling_context_count
        scoped_trades = sorted(
            _dedupe_trades(
                _time_window_filter_trades(
                    _scope_filter_trades(
                        raw_trades,
                        selected_condition_id=scope_context.selected_condition_id,
                    ),
                    start_at=window_start_at,
                    end_at=window_end_at,
                )
            ),
            key=lambda item: (item.timestamp, item.trade_id),
        )
        performance["analysis_time_window_start"] = window_start_at.isoformat() if window_start_at else ""
        performance["analysis_time_window_end"] = window_end_at.isoformat() if window_end_at else ""
        performance["analysis_time_window_enabled"] = bool(window_start_at or window_end_at)
        if _stop_requested(stop_event):
            if wallet_prefetch_executor is not None:
                wallet_prefetch_executor.shutdown(wait=False, cancel_futures=True)
            return self._build_stopped_report(
                started_at,
                reports_dir,
                resolved,
                scope_context,
                threshold,
                scoped_trades,
                truncated_market_count,
                include_related_markets,
                include_blockchain,
                start_at=window_start_at,
                end_at=window_end_at,
            )
        prethreshold_candidate_trades = _build_candidate_trade_set(
            scoped_trades,
            minimum_notional=threshold,
        )
        prethreshold_candidate_count = len(prethreshold_candidate_trades)
        normal_candidate_trades = [
            trade for trade in prethreshold_candidate_trades if trade.notional >= threshold
        ]
        normal_candidate_ids = {trade.trade_id for trade in normal_candidate_trades}
        validation_cache_only = runtime_validation_cache_only or effective_funding_trace_mode in {
            FUNDING_TRACE_MODE_CACHE_ONLY,
            FUNDING_TRACE_MODE_DISABLED,
        }
        pre_admission_pool = _structural_pre_admission_prefunding_pool(
            scoped_trades,
            minimum_notional=threshold,
            normal_candidate_ids=normal_candidate_ids,
        )
        pre_admission_context_pool = [] if validation_cache_only else pre_admission_pool
        if validation_cache_only and pre_admission_pool:
            skip_reason = (
                "validation_cache_only_pre_admission_skipped"
                if runtime_validation_cache_only and effective_funding_trace_mode == FUNDING_TRACE_MODE_CACHE_ONLY
                else _funding_skip_reason_for_mode(
                    effective_funding_trace_mode,
                    include_blockchain=include_blockchain,
                )
            )
            _emit_progress(
                progress_callback,
                24,
                _funding_progress_stage(effective_funding_trace_mode),
                (
                    f"Skipping {len(pre_admission_pool)} structural pre-admission funding checks; "
                    "funding remains unknown, not none"
                ),
            )
            for trade in pre_admission_pool:
                self._funding_resolver.record_trace_skipped(skip_reason)
        context_pool_trades = _dedupe_trades([*normal_candidate_trades, *pre_admission_context_pool])
        below_threshold_candidate_count = prethreshold_candidate_count - len(normal_candidate_trades)
        context_pool_wallet_references = [trade.wallet for trade in context_pool_trades if trade.wallet]
        context_pool_wallet_count = len({trade.wallet for trade in context_pool_trades})
        candidate_wallet_count = len({trade.wallet for trade in normal_candidate_trades})
        performance["market_fetch_workers"] = min(
            EVENT_FORENSIC_MARKET_FETCH_WORKERS,
            max(1, len(resolved.markets)),
        )
        performance["wallet_prefetch_workers"] = min(
            EVENT_FORENSIC_WALLET_PREFETCH_WORKERS,
            max(1, context_pool_wallet_count),
        )
        performance["price_history_workers"] = min(
            EVENT_FORENSIC_PRICE_HISTORY_WORKERS,
            max(1, len(scope_context.analysis_markets)),
        )
        performance["wallet_prefetch_seeded_count"] = len(warm_wallet_futures)
        performance["candidate_trade_count_prethreshold"] = prethreshold_candidate_count
        performance["candidate_trade_count_visible"] = len(normal_candidate_trades)
        performance["structural_pre_admission_prefunding_pool_count"] = len(pre_admission_pool)
        performance["candidate_wallet_count"] = candidate_wallet_count
        wallet_trades = _group_wallet_trades(scoped_trades)
        market_trades = _group_market_trades(scoped_trades)
        domain_trades = _group_domain_trades(scoped_trades, scope_context.analysis_markets)
        market_notional_samples = {
            condition_id: sorted(float(item.notional) for item in trades)
            for condition_id, trades in market_trades.items()
        }
        domain_notional_samples = {
            domain: sorted(float(item.notional) for item in trades)
            for domain, trades in domain_trades.items()
            if len(trades) >= 8
        }

        _emit_progress(
            progress_callback,
            25,
            "Collecting evidence",
            (
                f"Loaded {len(scoped_trades)} scope-filtered trade(s); {len(normal_candidate_trades)} met the visible "
                f"${threshold:,.0f} minimum"
                + (
                    f" ({below_threshold_candidate_count} smaller aggregate entries skipped for speed and clarity)"
                    if below_threshold_candidate_count
                    else ""
                )
            ),
        )
        funding_cache: dict[tuple[str, str], FundingContext] = {}
        all_cases: list[FlaggedCase] = []
        price_history_future = None
        price_history_executor: ThreadPoolExecutor | None = None
        related_market_future = None
        related_market_executor: ThreadPoolExecutor | None = None
        if scoped_trades:
            price_history_executor = ThreadPoolExecutor(max_workers=1)
            price_history_future = price_history_executor.submit(
                self._collect_price_history_timed,
                resolved,
                scope_context.analysis_markets,
                scoped_trades,
                stop_event,
            )
        stage_started = perf_counter()
        self._prefetch_wallet_contexts(
            context_pool_trades,
            wallet_cache,
            scope_context.analysis_markets,
            progress_callback=progress_callback,
            stop_event=stop_event,
            prestarted_futures=warm_wallet_futures,
            executor=wallet_prefetch_executor,
            trace_records=wallet_api_trace_records,
            trace_lock=wallet_api_trace_lock,
        )
        performance["prefetch_wallet_context_seconds"] = round(perf_counter() - stage_started, 2)
        performance["wallet_context_count"] = len(wallet_cache)
        if wallet_prefetch_executor is not None:
            wallet_prefetch_executor.shutdown(wait=False)
        if wallet_cache:
            related_market_executor = ThreadPoolExecutor(max_workers=1)
            related_market_future = related_market_executor.submit(
                self._discover_related_markets_timed,
                resolved,
                wallet_cache,
                include_related_markets,
            )
        if _stop_requested(stop_event):
            if wallet_prefetch_executor is not None:
                wallet_prefetch_executor.shutdown(wait=False, cancel_futures=True)
            if price_history_executor is not None:
                price_history_executor.shutdown(wait=False, cancel_futures=True)
            if related_market_executor is not None:
                related_market_executor.shutdown(wait=False, cancel_futures=True)
            return self._build_stopped_report(
                started_at,
                reports_dir,
                resolved,
                scope_context,
                threshold,
                scoped_trades,
                truncated_market_count,
                include_related_markets,
                include_blockchain,
                start_at=window_start_at,
                end_at=window_end_at,
            )

        stage_started = perf_counter()
        context_pool_contexts, funding_requests, wallet_context_profile = self._prepare_candidate_contexts(
            context_pool_trades,
            resolved=resolved,
            scope_context=scope_context,
            wallet_cache=wallet_cache,
            wallet_trades=wallet_trades,
            market_trades=market_trades,
            domain_trades=domain_trades,
            include_blockchain=include_blockchain,
            funding_trace_mode=effective_funding_trace_mode,
            progress_callback=progress_callback,
            stop_event=stop_event,
            wallet_api_trace_records=wallet_api_trace_records,
            wallet_api_trace_lock=wallet_api_trace_lock,
        )
        performance["prepare_candidate_context_seconds"] = round(perf_counter() - stage_started, 2)
        performance["wallet_api_boundary_trace"] = build_wallet_api_boundary_trace_metadata(
            trace_records=wallet_api_trace_records,
            requested_wallet_references=len(context_pool_wallet_references),
            unique_requested_wallets=context_pool_wallet_count,
            wallet_context_count=len(wallet_cache),
            prestarted_future_count=len(warm_wallet_futures),
            prefetch_seconds=float(performance["prefetch_wallet_context_seconds"] or 0.0),
            truncated_market_count=truncated_market_count,
            analysis_market_count=len(scope_context.analysis_markets),
            live_resolved_market_count=len(resolved.markets),
        )
        performance["funding_request_count"] = len(funding_requests)
        performance["funding_prefetch_workers"] = (
            0
            if not funding_requests
            else min(EVENT_FORENSIC_FUNDING_PREFETCH_WORKERS, len(funding_requests))
        )
        if _stop_requested(stop_event):
            if wallet_prefetch_executor is not None:
                wallet_prefetch_executor.shutdown(wait=False, cancel_futures=True)
            if price_history_executor is not None:
                price_history_executor.shutdown(wait=False, cancel_futures=True)
            if related_market_executor is not None:
                related_market_executor.shutdown(wait=False, cancel_futures=True)
            return self._build_stopped_report(
                started_at,
                reports_dir,
                resolved,
                scope_context,
                threshold,
                scoped_trades,
                truncated_market_count,
                include_related_markets,
                include_blockchain,
                start_at=window_start_at,
                end_at=window_end_at,
            )

        stage_started = perf_counter()
        if effective_funding_trace_mode == FUNDING_TRACE_MODE_DISABLED:
            _emit_progress(
                progress_callback,
                37,
                "Skipping blockchain funding traces",
                "Skipping blockchain funding traces: no-RPC mode; funding evidence is unknown, not none",
            )
        elif funding_requests:
            progress_stage = _funding_progress_stage(effective_funding_trace_mode)
            detail = (
                f"Checking {len(funding_requests)} cached funding context(s); cache misses become unknown"
                if effective_funding_trace_mode == FUNDING_TRACE_MODE_CACHE_ONLY
                else f"Starting {len(funding_requests)} funding context traces"
            )
            _emit_progress(
                progress_callback,
                37,
                progress_stage,
                detail,
            )
        self._prefetch_funding_contexts(
            funding_requests,
            funding_cache,
            funding_trace_mode=effective_funding_trace_mode,
            progress_callback=progress_callback,
            stop_event=stop_event,
        )
        performance["prefetch_funding_context_seconds"] = round(perf_counter() - stage_started, 2)
        funding_health_snapshot = self._funding_resolver.health().to_dict()
        performance["funding_resolver_health"] = funding_health_snapshot
        performance["funding_resolver_available"] = funding_health_snapshot["fundingResolverAvailable"]
        performance["funding_resolver_auth_error"] = funding_health_snapshot["fundingResolverAuthError"]
        performance["funding_resolver_unavailable_reason"] = funding_health_snapshot.get(
            "fundingResolverUnavailableReason",
            "",
        )
        performance["funding_resolver_functional_status"] = funding_health_snapshot.get(
            "fundingResolverFunctionalStatus",
            "",
        )
        performance["funding_resolver_endpoint_label"] = funding_health_snapshot["fundingResolverEndpointLabel"]
        performance["funding_trace_mode"] = funding_health_snapshot.get("fundingTraceMode", effective_funding_trace_mode)
        performance["fundingTraceMode"] = performance["funding_trace_mode"]
        performance["funding_trace_disabled_reason"] = funding_health_snapshot.get("fundingTraceDisabledReason", "")
        performance["fundingTraceDisabledReason"] = performance["funding_trace_disabled_reason"]
        performance["funding_trace_skipped_reason_distribution"] = funding_health_snapshot.get(
            "fundingTraceSkippedReasonDistribution",
            {},
        )
        performance["fundingTraceSkippedReasonDistribution"] = performance[
            "funding_trace_skipped_reason_distribution"
        ]
        performance["funding_trace_attempted_count"] = funding_health_snapshot.get("fundingTraceAttemptedCount", 0)
        performance["fundingTraceAttemptedCount"] = performance["funding_trace_attempted_count"]
        performance["funding_trace_succeeded_count"] = funding_health_snapshot.get("fundingTraceSucceededCount", 0)
        performance["fundingTraceSucceededCount"] = performance["funding_trace_succeeded_count"]
        performance["funding_trace_failed_count"] = funding_health_snapshot.get("fundingTraceFailedCount", 0)
        performance["fundingTraceFailedCount"] = performance["funding_trace_failed_count"]
        performance["funding_evidence_interpretation"] = funding_health_snapshot.get(
            "fundingEvidenceInterpretation",
            "",
        )
        performance["fundingEvidenceInterpretation"] = performance["funding_evidence_interpretation"]
        performance["funding_trace_coverage_ratio"] = funding_health_snapshot["fundingTraceCoverageRatio"]
        performance["funding_trace_endpoint_pool_size"] = funding_health_snapshot.get("fundingTraceEndpointPoolSize", 0)
        performance["funding_trace_endpoint_available_count"] = funding_health_snapshot.get("fundingTraceEndpointAvailableCount", 0)
        performance["funding_trace_endpoint_cooldown_count"] = funding_health_snapshot.get("fundingTraceEndpointCooldownCount", 0)
        performance["funding_trace_rate_limited_count"] = funding_health_snapshot.get("fundingTraceRateLimitedCount", 0)
        performance["funding_trace_retry_count"] = funding_health_snapshot.get("fundingTraceRetryCount", 0)
        performance["funding_trace_fallback_endpoint_count"] = funding_health_snapshot.get("fundingTraceFallbackEndpointCount", 0)
        performance["funding_trace_log_chunks_attempted"] = funding_health_snapshot.get("fundingTraceLogChunksAttempted", 0)
        performance["funding_trace_log_chunks_succeeded"] = funding_health_snapshot.get("fundingTraceLogChunksSucceeded", 0)
        performance["funding_trace_log_chunks_failed"] = funding_health_snapshot.get("fundingTraceLogChunksFailed", 0)
        performance["funding_trace_cache_hit_count"] = funding_health_snapshot.get("fundingTraceCacheHitCount", 0)
        performance["funding_trace_cache_miss_count"] = funding_health_snapshot.get("fundingTraceCacheMissCount", 0)
        performance["funding_trace_persistent_cache_enabled"] = funding_health_snapshot.get("fundingTracePersistentCacheEnabled", False)
        performance["funding_trace_persistent_cache_hit_count"] = funding_health_snapshot.get("fundingTracePersistentCacheHitCount", 0)
        performance["funding_trace_persistent_cache_miss_count"] = funding_health_snapshot.get("fundingTracePersistentCacheMissCount", 0)
        performance["funding_trace_persistent_cache_write_count"] = funding_health_snapshot.get("fundingTracePersistentCacheWriteCount", 0)
        performance["funding_trace_persistent_cache_expired_count"] = funding_health_snapshot.get("fundingTracePersistentCacheExpiredCount", 0)
        performance["funding_trace_persistent_cache_failure_cooldown_count"] = funding_health_snapshot.get("fundingTracePersistentCacheFailureCooldownCount", 0)
        performance["funding_trace_persistent_cache_schema_version"] = funding_health_snapshot.get("fundingTracePersistentCacheSchemaVersion", 0)
        if (
            self._funding_resolver.rpc_disabled_reason is not None
            and effective_funding_trace_mode != FUNDING_TRACE_MODE_DISABLED
        ):
            performance["funding_rpc_disabled_reason"] = self._funding_resolver.rpc_disabled_reason
        if self._client.polygon_nonce_disabled_reason is not None:
            performance["polygon_nonce_disabled_reason"] = self._client.polygon_nonce_disabled_reason
        if _stop_requested(stop_event):
            if wallet_prefetch_executor is not None:
                wallet_prefetch_executor.shutdown(wait=False, cancel_futures=True)
            if price_history_executor is not None:
                price_history_executor.shutdown(wait=False, cancel_futures=True)
            if related_market_executor is not None:
                related_market_executor.shutdown(wait=False, cancel_futures=True)
            return self._build_stopped_report(
                started_at,
                reports_dir,
                resolved,
                scope_context,
                threshold,
                scoped_trades,
                truncated_market_count,
                include_related_markets,
                include_blockchain,
                start_at=window_start_at,
                end_at=window_end_at,
            )

        funding_by_trade_id: dict[str, FundingContext] = {}
        wallet_history_by_wallet: dict[str, list[Trade]] = {}
        for context in context_pool_contexts:
            wallet_history_by_wallet[context.trade.wallet] = context.wallet_history_trades
            funding_by_trade_id[context.trade.trade_id] = (
                funding_cache.get(context.funding_cache_key)
                if context.funding_cache_key is not None
                else None
            ) or unknown_funding_context(
                context.funding_skip_reason
                or _funding_skip_reason_for_mode(
                    effective_funding_trace_mode,
                    include_blockchain=include_blockchain,
                )
            )
        pre_admission_metadata = _build_structural_pre_admission_metadata(
            pre_admission_pool,
            minimum_notional=threshold,
            funding_context_by_trade_id=funding_by_trade_id,
            wallet_history_by_wallet=wallet_history_by_wallet,
            normal_candidate_ids=normal_candidate_ids,
            enable_structural_pre_admission=True,
        )
        pre_pool_ids = {trade.trade_id for trade in pre_admission_pool}
        pre_trace_attempted_ids = {
            context.trade.trade_id
            for context in context_pool_contexts
            if context.trade.trade_id in pre_pool_ids and context.funding_cache_key is not None
        }
        pre_trace_succeeded_ids = {
            context.trade.trade_id
            for context in context_pool_contexts
            if context.trade.trade_id in pre_pool_ids
            and context.funding_cache_key is not None
            and (funding_cache.get(context.funding_cache_key) is not None)
            and (funding_cache.get(context.funding_cache_key) or FundingContext(funding_found=False)).error is None
        }
        pre_trace_skipped_reasons: dict[str, str] = {}
        for context in context_pool_contexts:
            if context.trade.trade_id not in pre_pool_ids or context.trade.trade_id in pre_trace_attempted_ids:
                continue
            skip_reason = context.funding_skip_reason or _funding_skip_reason_for_mode(
                effective_funding_trace_mode,
                include_blockchain=include_blockchain,
            )
            self._funding_resolver.record_trace_skipped(skip_reason)
            pre_trace_skipped_reasons[context.trade.trade_id] = skip_reason
        if validation_cache_only:
            skip_reason = (
                "validation_cache_only_pre_admission_skipped"
                if runtime_validation_cache_only and effective_funding_trace_mode == FUNDING_TRACE_MODE_CACHE_ONLY
                else _funding_skip_reason_for_mode(
                    effective_funding_trace_mode,
                    include_blockchain=include_blockchain,
                )
            )
            for trade in pre_admission_pool:
                if trade.trade_id in pre_trace_attempted_ids:
                    continue
                pre_trace_skipped_reasons.setdefault(trade.trade_id, skip_reason)
        candidate_admission_funnel = _build_structural_pre_admission_funnel(
            scoped_trades,
            minimum_notional=threshold,
            normal_candidate_ids=normal_candidate_ids,
            pre_admission_pool=pre_admission_pool,
            funding_context_by_trade_id=funding_by_trade_id,
            wallet_history_by_wallet=wallet_history_by_wallet,
            admission_metadata=pre_admission_metadata,
            funding_resolver_health=self._funding_resolver.health(),
            pre_admission_funding_trace_enabled=include_blockchain and not validation_cache_only,
            pre_admission_funding_trace_attempted_ids=pre_trace_attempted_ids,
            pre_admission_funding_trace_succeeded_ids=pre_trace_succeeded_ids,
            pre_admission_funding_trace_skipped_reasons=pre_trace_skipped_reasons,
        )
        admitted_trade_ids = set(pre_admission_metadata)
        candidate_contexts = [
            context
            for context in context_pool_contexts
            if context.trade.trade_id in normal_candidate_ids
            or context.trade.trade_id in admitted_trade_ids
        ]
        candidate_trades = [context.trade for context in candidate_contexts]
        candidate_wallet_count = len({trade.wallet for trade in candidate_trades})
        structural_pre_admission_count = len(admitted_trade_ids)
        performance["candidate_trade_count_visible"] = len(candidate_trades)
        performance["candidate_wallet_count"] = candidate_wallet_count
        performance["structural_pre_admission_count"] = structural_pre_admission_count
        performance["normal_candidate_trade_count"] = len(normal_candidate_trades)
        total_candidates = max(1, len(candidate_contexts))
        scoring_wallet_windows = {
            wallet: wallet_trades.get(wallet, [])
            for wallet in {context.trade.wallet for context in candidate_contexts}
        }
        scoring_market_notional_samples = {
            condition_id: market_notional_samples.get(condition_id)
            for condition_id in {context.trade.condition_id for context in candidate_contexts}
        }
        scoring_domain_notional_samples = {
            domain: domain_notional_samples.get(domain)
            for domain in {context.trade_domain for context in candidate_contexts}
        }
        scoring_funding_health = self._funding_resolver.health().to_dict()
        score_loop_memoization = build_score_loop_memoization_metadata(
            candidate_rows=len(candidate_contexts),
            unique_wallets=len(scoring_wallet_windows),
            unique_markets=len(scoring_market_notional_samples),
            unique_domains=len(scoring_domain_notional_samples),
        )
        performance["score_input_memoization"] = score_loop_memoization
        prepared_context_count = sum(
            1 for context in candidate_contexts if context.prepared_score_context is not None
        )
        performance["score_trade_prepared_context"] = build_score_trade_prepared_context_metadata(
            candidate_rows=len(candidate_contexts),
            prepared_context_rows=prepared_context_count,
            score_call_count=len(candidate_contexts),
            fallback_context_rows=len(candidate_contexts) - prepared_context_count,
        )

        stage_started = perf_counter()
        wallet_domain_counts_cache: dict[str, dict[str, int]] = {}
        wallet_domain_profile = {
            "cache_hits": 0,
            "cache_misses": 0,
        }
        scorer_profile_seconds = {
            "funding_context_lookup": 0.0,
            "score_input_lookup": 0.0,
            "score_trade_call": 0.0,
            "candidate_admission_metadata": 0.0,
            "wallet_domain_profile_annotation": 0.0,
            "append_case": 0.0,
            "progress_emit": 0.0,
        }
        scored_case_count = 0
        skipped_case_count = 0
        for trade_index, context in enumerate(candidate_contexts, start=1):
            if _stop_requested(stop_event):
                break
            profile_started = perf_counter()
            funding_context = (
                funding_cache.get(context.funding_cache_key)
                if context.funding_cache_key is not None
                else None
            ) or unknown_funding_context(
                "blockchain_disabled" if not include_blockchain else "funding_trace_not_requested"
            )
            scorer_profile_seconds["funding_context_lookup"] += perf_counter() - profile_started

            profile_started = perf_counter()
            wallet_window_trades = scoring_wallet_windows.get(context.trade.wallet, [])
            market_notional_sample = scoring_market_notional_samples.get(context.trade.condition_id)
            domain_notional_sample = scoring_domain_notional_samples.get(context.trade_domain)
            scorer_profile_seconds["score_input_lookup"] += perf_counter() - profile_started

            profile_started = perf_counter()
            case = _score_trade(
                trade=context.trade,
                market=context.market,
                trade_domain=context.trade_domain,
                wallet_inspection=context.wallet_inspection,
                wallet_performance=context.wallet_performance,
                wallet_window_trades=wallet_window_trades,
                wallet_history_trades=context.wallet_history_trades,
                market_window_trades=context.market_window_trades,
                domain_window_trades=context.domain_window_trades,
                event_context=context.event_context,
                funding_context=funding_context,
                funding_health=scoring_funding_health,
                include_below_threshold=True,
                market_notional_samples=market_notional_sample,
                domain_notional_samples=domain_notional_sample,
                prior_wallet_gap_days=context.prior_wallet_gap_days,
                observed_post_trade_gap_days=context.observed_post_trade_gap_days,
                family_key=context.family_key,
                prior_family_trade_count=context.prior_family_trade_count,
                prior_family_market_count=context.prior_family_market_count,
                event_family_share=context.event_family_share,
                prepared_context=context.prepared_score_context,
            )
            scorer_profile_seconds["score_trade_call"] += perf_counter() - profile_started
            if case is not None:
                scored_case_count += 1
                profile_started = perf_counter()
                _apply_candidate_admission_metadata(
                    case,
                    pre_admission_metadata.get(context.trade.trade_id),
                )
                scorer_profile_seconds["candidate_admission_metadata"] += perf_counter() - profile_started
                profile_started = perf_counter()
                _annotate_wallet_domain_diversity(
                    case,
                    wallet_history_trades=context.wallet_history_trades,
                    focus_markets=scope_context.analysis_markets,
                    domain_counts_cache=wallet_domain_counts_cache,
                    profile=wallet_domain_profile,
                )
                scorer_profile_seconds["wallet_domain_profile_annotation"] += perf_counter() - profile_started
                profile_started = perf_counter()
                all_cases.append(case)
                scorer_profile_seconds["append_case"] += perf_counter() - profile_started
            else:
                skipped_case_count += 1

            percent = 25 + int((trade_index / total_candidates) * 35)
            profile_started = perf_counter()
            _emit_progress(
                progress_callback,
                percent,
                "Replaying model",
                f"Scored trade {trade_index}/{total_candidates} with the current InsPoly logic",
            )
            scorer_profile_seconds["progress_emit"] += perf_counter() - profile_started
        score_candidates_elapsed = perf_counter() - stage_started
        performance["score_candidates_seconds"] = round(score_candidates_elapsed, 2)
        performance["score_candidates_per_second"] = round(
            (len(candidate_contexts) / score_candidates_elapsed) if score_candidates_elapsed > 0 else 0.0,
            3,
        )
        wallet_context_reuse = build_wallet_context_reuse_metadata(
            context_pool_trade_rows=len(context_pool_trades),
            candidate_rows=len(candidate_contexts),
            requested_wallet_references=len(context_pool_wallet_references),
            unique_requested_wallets=context_pool_wallet_count,
            wallet_context_count=len(wallet_cache),
            prestarted_future_count=len(warm_wallet_futures),
            wallet_context_cache_hits=int(wallet_context_profile.get("wallet_context_cache_hits", 0)),
            wallet_context_cache_misses=int(wallet_context_profile.get("wallet_context_cache_misses", 0)),
            scoped_history_cache_hits=int(wallet_context_profile.get("scoped_history_cache_hits", 0)),
            scoped_history_cache_misses=int(wallet_context_profile.get("scoped_history_cache_misses", 0)),
            wallet_history_metrics_cache_hits=int(wallet_context_profile.get("wallet_history_metrics_cache_hits", 0)),
            wallet_history_metrics_cache_misses=int(wallet_context_profile.get("wallet_history_metrics_cache_misses", 0)),
            domain_profile_cache_hits=int(wallet_domain_profile.get("cache_hits", 0)),
            domain_profile_cache_misses=int(wallet_domain_profile.get("cache_misses", 0)),
            prefetch_seconds=float(performance["prefetch_wallet_context_seconds"] or 0.0),
            prepare_seconds=float(performance["prepare_candidate_context_seconds"] or 0.0),
            score_seconds=float(performance["score_candidates_seconds"] or 0.0),
        )
        performance["wallet_context_reuse"] = wallet_context_reuse
        performance["scorer_context_profile"] = build_scorer_context_profile_metadata(
            candidate_rows=len(candidate_contexts),
            scored_case_count=scored_case_count,
            skipped_case_count=skipped_case_count,
            bucket_seconds=scorer_profile_seconds,
            score_loop_seconds=score_candidates_elapsed,
            wallet_context_reuse=wallet_context_reuse,
        )

        _annotate_domain_peer_history(all_cases, wallet_cache)
        _annotate_preclassification_linkage(all_cases)
        _validate_candidate_admissions(all_cases)
        _finalize_structural_pre_admission_funnel(candidate_admission_funnel, all_cases)
        performance["structural_pre_admission_validated_count"] = sum(
            1
            for case in all_cases
            if case.raw_metrics.get("candidateAdmissionStage") == "pre_admitted_validated"
        )
        performance["structural_pre_admission_rejected_count"] = sum(
            1
            for case in all_cases
            if case.raw_metrics.get("candidateAdmissionStage") == "pre_admitted_rejected"
        )

        winners_by_condition = {
            condition_id: _winning_outcome_from_payload(payload)
            for condition_id, payload in resolved.market_payloads.items()
            if condition_id in scope_context.analysis_markets
        }
        winning_entry_ranks = _winning_entry_ranks(all_cases, winners_by_condition)
        _annotate_hard_evidence_review(
            all_cases,
            winner_ranks_by_trade_id=winning_entry_ranks,
            evidence_availability_stage=(
                "event_forensic_outcome_context_available"
                if any(winners_by_condition.values())
                else "event_forensic_no_outcome_context"
            ),
        )
        flagged_existing_cases = [case for case in all_cases if _case_survives_output_threshold(case)]
        if price_history_future is not None:
            price_history, price_history_seconds = price_history_future.result()
            performance["collect_price_history_seconds"] = price_history_seconds
            if price_history_executor is not None:
                price_history_executor.shutdown(wait=False)
        else:
            price_history = {}
            performance["collect_price_history_seconds"] = 0.0
        if related_market_future is not None:
            related_market_rows, related_market_seconds = related_market_future.result()
            performance["related_market_scan_seconds"] = related_market_seconds
            if related_market_executor is not None:
                related_market_executor.shutdown(wait=False)
        else:
            related_market_rows = []
            performance["related_market_scan_seconds"] = 0.0

        stage_started = perf_counter()
        sibling_market_activity = _sibling_market_activity_lookup(
            wallet_cache,
            all_event_condition_ids=set(resolved.markets),
            selected_condition_id=scope_context.selected_condition_id,
        )
        trade_payloads = self._build_trade_payloads(
            resolved=resolved,
            cases=all_cases,
            wallet_cache=wallet_cache,
            winners_by_condition=winners_by_condition,
            related_market_rows=related_market_rows,
            analysis_scope=scope_context.analysis_scope,
            sibling_market_activity=sibling_market_activity,
            scope_context=scope_context,
        )
        visible_trade_payloads = _visible_trade_payloads(
            trade_payloads,
            minimum_notional=threshold,
        )
        _annotate_weak_history_near_certainty_review_policy(visible_trade_payloads)
        ranked_trades = self._ranked_trade_rows(visible_trade_payloads)
        prepolicy_threshold_suspicious_trade_count = sum(
            1 for item in ranked_trades if item["eventForensicScore"] >= EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD
        )
        prepolicy_hard_evidence_review_trade_count = sum(
            1 for item in ranked_trades if item.get("hardEvidenceReviewTier") == HARD_EVIDENCE_REVIEW_TIER
        )
        threshold_suspicious_trades = [
            item for item in ranked_trades if item["eventForensicScore"] >= EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD
            and not _is_weak_history_near_certainty_review_demoted(item)
        ]
        hard_evidence_review_trades = [
            item for item in ranked_trades if item.get("hardEvidenceReviewTier") == HARD_EVIDENCE_REVIEW_TIER
            and not _is_weak_history_near_certainty_review_demoted(item)
        ]
        suspicious_trades = _dedupe_trade_payloads(
            [*threshold_suspicious_trades, *hard_evidence_review_trades]
        )
        suspicious_trades.sort(key=_event_trade_sort_key, reverse=True)
        review_required_trades = [
            item for item in ranked_trades if _is_weak_history_near_certainty_review_demoted(item)
        ]
        review_required_trades.sort(key=_event_trade_sort_key, reverse=True)
        fallback_display_trades = [
            item for item in ranked_trades if not _is_weak_history_near_certainty_review_demoted(item)
        ][:25]
        display_trades = suspicious_trades[:EVENT_FORENSIC_VISIBLE_TRADE_LIMIT] or fallback_display_trades
        display_review_required_trades = review_required_trades[:EVENT_FORENSIC_VISIBLE_TRADE_LIMIT]

        ranked_wallets = self._build_wallet_rankings(
            visible_trade_payloads,
            related_market_rows,
            analysis_scope=scope_context.analysis_scope,
            sibling_market_activity=sibling_market_activity,
        )
        suspicious_wallets = _primary_suspicious_wallet_rows(ranked_wallets)
        display_wallets = suspicious_wallets[:EVENT_FORENSIC_VISIBLE_WALLET_LIMIT] or ranked_wallets[:25]
        wallet_clusters = self._build_wallet_clusters(
            visible_trade_payloads,
            suspicious_wallets,
            analysis_scope=scope_context.analysis_scope,
            sibling_market_activity=sibling_market_activity,
            scope_context=scope_context,
        )
        display_clusters = wallet_clusters[:EVENT_FORENSIC_VISIBLE_CLUSTER_LIMIT]
        wallet_graph = self._build_wallet_graph(
            resolved,
            display_trades,
            display_wallets,
            display_clusters,
            scope_context=scope_context,
        )
        model_gap = self._build_model_gap_analysis(
            visible_trade_payloads,
            suspicious_wallets,
            wallet_clusters,
            analysis_scope=scope_context.analysis_scope,
            selected_market_title=scope_context.selected_market_title,
            outcome_context_available=_eligibility_has_outcome_context(eligibility),
        )
        candidate_audit_rows = _candidate_audit_rows(
            visible_trade_payloads,
            suspicious_trades=suspicious_trades,
            ranked_wallets=ranked_wallets,
            funding_trace_mode=effective_funding_trace_mode,
        )
        timeline_points = self._timeline_points(resolved, display_trades, price_history)
        evidence_warnings = _evidence_warnings(
            performance,
            include_blockchain=include_blockchain,
        )
        performance["assemble_report_rows_seconds"] = round(perf_counter() - stage_started, 2)
        empty_state_note = _empty_state_note(
            analysis_scope=scope_context.analysis_scope,
            selected_market_title=scope_context.selected_market_title,
            candidate_trade_count=len(candidate_trades),
        )
        scope_product_metadata = _scope_product_metadata(
            resolved,
            scope_context,
            include_related_markets=include_related_markets,
        )
        scope_summary_metadata = _scope_summary_metadata(
            resolved,
            scope_context,
            include_related_markets=include_related_markets,
        )

        raw_bundle = {
            "analysis_scope_metadata": _analysis_scope_metadata(resolved, scope_context),
            "scope_product_metadata": scope_product_metadata,
            "analysis_time_window": {
                "start_at": window_start_at.isoformat() if window_start_at else "",
                "end_at": window_end_at.isoformat() if window_end_at else "",
            },
            "resolved_event": resolved.event_payload,
            "event_markets": list(resolved.market_payloads.values()),
            "case_family_expansion": case_family_expansion,
            "analysis_markets": [
                resolved.market_payloads[condition_id]
                for condition_id in scope_context.analysis_markets
                if condition_id in resolved.market_payloads
            ],
            "trades": [trade.to_dict() for trade in scoped_trades],
            "candidate_trade_count": len(candidate_trades),
            "normal_candidate_trade_count": len(normal_candidate_trades),
            "structural_pre_admission_count": performance.get("structural_pre_admission_validated_count", 0),
            "structural_pre_admission_rejected_count": performance.get("structural_pre_admission_rejected_count", 0),
            "prethreshold_candidate_trade_count": prethreshold_candidate_count,
            "below_threshold_candidate_trade_count": below_threshold_candidate_count,
            "candidate_wallet_count": candidate_wallet_count,
            "price_history": price_history,
            "wallet_histories": {
                wallet: [trade.to_dict() for trade in history]
                for wallet, (_inspection, history, _performance) in wallet_cache.items()
            },
            "funding_contexts": {
                f"{wallet}:{hour}": _funding_context_to_dict(context)
                for (wallet, hour), context in funding_cache.items()
            },
            "candidate_admission_records": _candidate_admission_records(
                all_cases,
                near_miss_records=_candidate_admission_near_miss_records(candidate_admission_funnel),
            ),
            "ranked_wallets": ranked_wallets,
            "source_trades": _source_trade_payloads_for_wallet_details(visible_trade_payloads, ranked_wallets),
        }

        report = {
            "analysis_version": EVENT_ANALYSIS_VERSION,
            "generated_at": started_at.isoformat(),
            "status": "stopped" if _stop_requested(stop_event) else "completed",
            "input_url": input_value,
            **_analysis_scope_metadata(resolved, scope_context),
            **scope_product_metadata,
            "target_resolution": self._resolved_target_payload(resolved, scope_context),
            "event": {
                "id": resolved.event_id,
                "slug": resolved.event_slug,
                "title": resolved.event_title,
                "description": resolved.event_description,
                "canonicalUrl": resolved.canonical_url,
                "category": resolved.event_category or "Unknown",
                "completed": _event_closed_for_report(resolved),
                "resolutionStatus": eligibility.get("status", "eligible"),
                "outcomeContextAvailable": _eligibility_has_outcome_context(eligibility),
                "familyId": resolved.event_family_id,
                "marketCount": len(resolved.markets),
                "analysisMarketCount": len(scope_context.analysis_markets),
                "sourceMarketSlug": resolved.source_market_slug,
                "sourceConditionId": resolved.source_condition_id,
            },
            "eligibility": eligibility,
            "analysis_settings": {
                "min_notional": f"{threshold:.2f}",
                "include_related_markets": include_related_markets,
                "include_blockchain": include_blockchain,
                "funding_trace_mode": effective_funding_trace_mode,
                "analysis_scope": scope_context.analysis_scope,
                "primary_scoring_scope": scope_product_metadata["primaryScoringScope"],
                "related_markets_context_included": scope_product_metadata["relatedMarketsContextIncluded"],
                "sibling_markets_primary_scored": scope_product_metadata["siblingMarketsPrimaryScored"],
                "selected_condition_id": scope_context.selected_condition_id,
                "selected_market_slug": scope_context.selected_market_slug,
                "start_at": window_start_at.isoformat() if window_start_at else "",
                "end_at": window_end_at.isoformat() if window_end_at else "",
            },
            "summary": {
                **scope_summary_metadata,
                "raw_trade_count": len(scoped_trades),
                "candidate_trade_count": len(candidate_trades),
                "normal_candidate_trade_count": len(normal_candidate_trades),
                "structural_pre_admission_count": performance.get("structural_pre_admission_validated_count", 0),
                "structural_pre_admission_rejected_count": performance.get("structural_pre_admission_rejected_count", 0),
                "existing_flagged_count": len(flagged_existing_cases),
                "forensic_suspicious_trade_count": len(threshold_suspicious_trades),
                "primary_review_trade_count": len(suspicious_trades),
                "hard_evidence_review_trade_count": len(hard_evidence_review_trades),
                "prepolicy_forensic_suspicious_trade_count": prepolicy_threshold_suspicious_trade_count,
                "prepolicy_hard_evidence_review_trade_count": prepolicy_hard_evidence_review_trade_count,
                "weak_history_near_certainty_review_demotion_count": len(review_required_trades),
                "review_required_trade_count": len(review_required_trades),
                "suspicious_wallet_count": len(suspicious_wallets),
                "wallet_context_count": len(ranked_wallets),
                "wallet_cluster_count": len(wallet_clusters),
                "display_trade_count": len(display_trades),
                "display_review_required_trade_count": len(display_review_required_trades),
                "display_wallet_count": len(display_wallets),
                "display_cluster_count": len(display_clusters),
                "below_threshold_candidate_count": below_threshold_candidate_count,
                "unique_wallet_count": len({trade.wallet for trade in scoped_trades}),
                "unique_market_count": len({trade.condition_id for trade in scoped_trades}),
                "analysis_market_count": len(scope_context.analysis_markets),
                "total_event_market_count": len(resolved.markets),
                "truncated_market_count": truncated_market_count,
                "case_family_added_market_count": case_family_expansion["added_market_count"],
                "case_family_added_event_count": case_family_expansion["added_event_count"],
                "resolved_market_count": eligibility.get("resolved_market_count", 0),
                "unresolved_market_count": eligibility.get("unresolved_market_count", 0),
                "outcome_context_available": _eligibility_has_outcome_context(eligibility),
            },
            "markets": self._market_summaries(
                resolved,
                scoped_trades,
                candidate_trades,
                winners_by_condition,
                price_history,
                analysis_markets=scope_context.analysis_markets,
            ),
            "timeline_points": timeline_points,
            "evidence_warnings": evidence_warnings,
            "scope_note": _scope_note(scope_context),
            "display_note": _display_note(
                suspicious_trade_count=len(suspicious_trades),
                display_trade_count=len(display_trades),
                suspicious_wallet_count=len(suspicious_wallets),
                display_wallet_count=len(display_wallets),
                wallet_cluster_count=len(wallet_clusters),
                display_cluster_count=len(display_clusters),
            ),
            "empty_state_note": empty_state_note,
            "performance": performance,
            "fundingTraceMode": performance.get("fundingTraceMode", effective_funding_trace_mode),
            "fundingTraceDisabledReason": performance.get("fundingTraceDisabledReason", ""),
            "fundingEvidenceInterpretation": performance.get("fundingEvidenceInterpretation", ""),
            "funding_resolver_health": self._funding_resolver.health().to_dict(),
            "candidate_admission_funnel": candidate_admission_funnel,
            "suspicious_trades": display_trades,
            "review_required_trades": review_required_trades,
            "suspicious_wallets": display_wallets,
            "wallet_clusters": display_clusters,
            "display_trades": display_trades,
            "display_review_required_trades": display_review_required_trades,
            "display_wallets": display_wallets,
            "display_clusters": display_clusters,
            "wallet_graph": wallet_graph,
            "related_markets": related_market_rows,
            "model_gap": model_gap,
        }
        report["candidate_audit"] = _candidate_audit_summary(report, candidate_audit_rows)
        performance["total_seconds"] = round(perf_counter() - analysis_started, 2)
        report["event_report_markdown"] = self._event_report_markdown(report)
        report["model_gap_markdown"] = self._model_gap_markdown(report)

        export_files = self._write_report_bundle(
            started_at,
            reports_dir,
            report,
            suspicious_trades=suspicious_trades,
            suspicious_wallets=suspicious_wallets,
            ranked_wallets=ranked_wallets,
            wallet_clusters=wallet_clusters,
            wallet_graph=wallet_graph,
            related_markets=related_market_rows,
            candidate_audit_rows=candidate_audit_rows,
            raw_bundle=raw_bundle,
            indexer_warehouse_pointer=indexer_warehouse_pointer,
        )
        report["export_files"] = export_files
        report["report_json_path"] = export_files["report_json_path"]
        report["report_md_path"] = export_files["event_report_md_path"]
        report["report_txt_path"] = export_files["event_report_md_path"]

        scan_run_id = self._storage.create_scan_run(
            started_at=started_at.isoformat(),
            lookback=input_value,
            topic_scope=resolved.event_title,
            raw_trade_count=len(scoped_trades),
            filtered_trade_count=len(candidate_trades),
            flagged_case_count=len(suspicious_trades),
            report_json_path=export_files["report_json_path"],
            report_md_path=export_files["event_report_md_path"],
        )
        self._storage.save_flagged_cases(scan_run_id, flagged_existing_cases[:250])
        report["scan_run_id"] = scan_run_id

        _emit_progress(progress_callback, 100, "Done", "Event forensic analysis finished")
        return report

    def resolve_target(
        self,
        input_value: str,
        *,
        analysis_scope: str | None = None,
        selected_condition_id: str | None = None,
        selected_market_slug: str | None = None,
        include_related_markets: bool = False,
    ) -> dict[str, object]:
        resolved = self.resolve_input(input_value)
        scope_context = _resolve_analysis_scope_context(
            resolved,
            analysis_scope=analysis_scope,
            selected_condition_id=selected_condition_id,
            selected_market_slug=selected_market_slug,
            require_selection=False,
        )
        expansion = self._expand_case_family_scope(
            resolved,
            scope_context,
            include_related_markets=include_related_markets,
        )
        if expansion["added_market_count"]:
            scope_context = _resolve_analysis_scope_context(
                resolved,
                analysis_scope=scope_context.analysis_scope,
                selected_condition_id=scope_context.selected_condition_id,
                selected_market_slug=scope_context.selected_market_slug,
                require_selection=False,
            )
        return self._resolved_target_payload(resolved, scope_context)

    def resolve_input(self, input_value: str) -> ResolvedEvent:
        slug = _extract_polymarket_slug(input_value)
        if not slug:
            raise ValueError("Could not extract a Polymarket event or market slug from the input.")

        resource_kind = _extract_polymarket_resource_kind(input_value)
        event_payload = self._client.fetch_event_by_slug(slug)
        source_market_payload: dict[str, object] | None = None
        if event_payload is None:
            source_market_payload = self._client.fetch_market_by_slug(slug)
            if source_market_payload is not None:
                events = source_market_payload.get("events") or []
                event_stub = next((item for item in events if isinstance(item, dict)), None)
                if event_stub is None:
                    raise ValueError("The market was found, but no parent event metadata was available.")
                event_slug = str(event_stub.get("slug") or "")
                event_payload = self._client.fetch_event_by_slug(event_slug) or dict(event_stub)
            if event_payload is None:
                event_payload, source_market_payload = self._client.fetch_event_resolution_from_pages(
                    slug,
                    page_hint=resource_kind,
                )
            if event_payload is None:
                raise ValueError("The provided Polymarket URL could not be resolved.")

        if not isinstance(event_payload, dict):
            raise ValueError("The Polymarket event payload was malformed.")

        market_payloads: dict[str, dict[str, object]] = {}
        raw_markets = event_payload.get("markets") or []
        for item in raw_markets:
            if not isinstance(item, dict):
                continue
            condition_id = str(item.get("conditionId") or "")
            if not condition_id:
                continue
            market_payloads[condition_id] = item

        if source_market_payload is not None:
            source_condition_id = str(source_market_payload.get("conditionId") or "")
            if source_condition_id and source_condition_id not in market_payloads:
                market_payloads[source_condition_id] = source_market_payload
        else:
            source_condition_id = None

        if not market_payloads:
            raise ValueError("No event markets were available for forensic analysis.")

        markets: dict[str, Market] = {}
        for condition_id, payload in market_payloads.items():
            market = Market.from_api(payload)
            market.site_categories = _market_categories(event_payload, payload)
            markets[condition_id] = market

        event_title = str(
            event_payload.get("title")
            or ((source_market_payload or {}).get("question") if source_market_payload else "")
            or next(iter(markets.values())).question
        )
        family_tokens = _meaningful_tokens(
            " ".join([event_title] + [market.question for market in markets.values()])
        )
        return ResolvedEvent(
            input_value=input_value,
            canonical_url=f"https://polymarket.com/event/{event_payload.get('slug', slug)}",
            event_id=str(event_payload.get("id") or ""),
            event_slug=str(event_payload.get("slug") or slug),
            event_title=event_title,
            event_description=str(event_payload.get("description") or ""),
            event_category=str(event_payload.get("category") or next(iter(markets.values())).site_categories[0]),
            event_closed=bool(event_payload.get("closed", False)),
            event_end_date=event_payload.get("endDate"),
            source_market_slug=str(source_market_payload.get("slug") or "") if source_market_payload else None,
            source_condition_id=source_condition_id,
            event_payload=event_payload,
            markets=markets,
            market_payloads=market_payloads,
            event_family_id=_family_id_from_tokens(family_tokens) or _slug_family_id(str(event_payload.get("slug") or slug)),
            family_tokens=family_tokens,
        )

    def _resolved_target_payload(
        self,
        resolved: ResolvedEvent,
        scope_context: AnalysisScopeContext,
    ) -> dict[str, object]:
        available_markets = []
        for condition_id, market in resolved.markets.items():
            payload = resolved.market_payloads.get(condition_id, {})
            winner = _winning_outcome_from_payload(payload)
            status_parts: list[str] = []
            if winner:
                status_parts.append(f"Resolved {winner}")
            elif bool(payload.get("closed", False)):
                status_parts.append("Closed")
            else:
                status_parts.append("Open")
            available_markets.append(
                {
                    "conditionId": condition_id,
                    "marketSlug": market.slug,
                    "marketTitle": market.question,
                    "statusLabel": " · ".join(status_parts),
                    "winner": winner,
                    "closed": bool(payload.get("closed", False)),
                    "selected": condition_id == scope_context.selected_condition_id,
                }
            )
        return {
            "inputUrl": resolved.input_value,
            "analysisScope": scope_context.analysis_scope,
            "analysisScopeLabel": _analysis_scope_label(scope_context.analysis_scope),
            "selectedConditionId": scope_context.selected_condition_id,
            "selectedMarketSlug": scope_context.selected_market_slug,
            "selectedMarketTitle": scope_context.selected_market_title,
            "parentEventSlug": resolved.event_slug,
            "directMarketInputDetected": bool(resolved.source_condition_id),
            "event": {
                "id": resolved.event_id,
                "slug": resolved.event_slug,
                "title": resolved.event_title,
                "canonicalUrl": resolved.canonical_url,
                "marketCount": len(resolved.markets),
            },
            "availableMarkets": available_markets,
        }

    def _expand_case_family_scope(
        self,
        resolved: ResolvedEvent,
        scope_context: AnalysisScopeContext,
        *,
        include_related_markets: bool,
    ) -> dict[str, object]:
        if not include_related_markets or scope_context.analysis_scope != "event":
            return {"added_market_count": 0, "added_event_count": 0, "events": []}
        tag_ids = _case_family_tag_ids(resolved.event_payload)
        if not tag_ids:
            return {"added_market_count": 0, "added_event_count": 0, "events": []}
        anchor_tokens = _case_family_anchor_tokens(resolved)
        if not anchor_tokens:
            return {"added_market_count": 0, "added_event_count": 0, "events": []}

        added_events: list[dict[str, object]] = []
        added_market_count = 0
        seen_event_slugs = {resolved.event_slug}
        seen_condition_ids = set(resolved.markets)

        for tag_id in tag_ids:
            if len(added_events) >= EVENT_FORENSIC_CASE_FAMILY_EVENT_LIMIT:
                break
            events = self._client.fetch_events_by_tag(
                tag_id,
                max_pages=2,
                page_size=100,
                closed="true",
            )
            for event_payload in events:
                if len(added_events) >= EVENT_FORENSIC_CASE_FAMILY_EVENT_LIMIT:
                    break
                event_slug = str(event_payload.get("slug") or "")
                if not event_slug or event_slug in seen_event_slugs:
                    continue
                event_tokens = _case_family_event_tokens(event_payload)
                match_tokens = _case_family_match_tokens(anchor_tokens, event_tokens)
                if not match_tokens:
                    continue
                markets_payload = [
                    item for item in (event_payload.get("markets") or []) if isinstance(item, dict)
                ]
                added_for_event = 0
                for market_payload in markets_payload:
                    condition_id = str(market_payload.get("conditionId") or "")
                    if not condition_id or condition_id in seen_condition_ids:
                        continue
                    market = Market.from_api(market_payload)
                    market.site_categories = _market_categories(event_payload, market_payload)
                    resolved.markets[condition_id] = market
                    resolved.market_payloads[condition_id] = market_payload
                    seen_condition_ids.add(condition_id)
                    added_for_event += 1
                if not added_for_event:
                    continue
                seen_event_slugs.add(event_slug)
                added_market_count += added_for_event
                resolved.family_tokens.update(event_tokens)
                added_events.append(
                    {
                        "eventSlug": event_slug,
                        "eventTitle": str(event_payload.get("title") or ""),
                        "addedMarketCount": added_for_event,
                        "matchedTokens": match_tokens,
                    }
                )

        return {
            "added_market_count": added_market_count,
            "added_event_count": len(added_events),
            "events": added_events,
        }

    def _prefetch_wallet_contexts(
        self,
        candidate_trades: list[Trade],
        wallet_cache: dict[str, tuple[object, list[Trade], WalletPerformance]],
        focus_markets: dict[str, Market],
        *,
        progress_callback: callable | None,
        stop_event: object | None,
        prestarted_futures: dict[str, Future] | None = None,
        executor: ThreadPoolExecutor | None = None,
        trace_records: list[dict[str, object]] | None = None,
        trace_lock: Lock | None = None,
    ) -> None:
        wallets = sorted({trade.wallet for trade in candidate_trades if trade.wallet and trade.wallet not in wallet_cache})
        if not wallets:
            return

        warm_futures = {
            wallet: future
            for wallet, future in (prestarted_futures or {}).items()
            if wallet in wallets and wallet not in wallet_cache
        }
        remaining_wallets = [wallet for wallet in wallets if wallet not in warm_futures]
        total_wallets = len(warm_futures) + len(remaining_wallets)
        max_workers = min(EVENT_FORENSIC_WALLET_PREFETCH_WORKERS, total_wallets)
        progress_step = max(1, total_wallets // 6)

        if max_workers <= 1 and not warm_futures:
            for index, wallet in enumerate(remaining_wallets, start=1):
                if _stop_requested(stop_event):
                    return
                if trace_records is None and trace_lock is None:
                    wallet_cache[wallet] = self._fetch_wallet_context(wallet, focus_markets)
                else:
                    wallet_cache[wallet] = self._fetch_wallet_context(
                        wallet,
                        focus_markets,
                        trace_records=trace_records,
                        trace_lock=trace_lock,
                    )
                if index == 1 or index == total_wallets or index % progress_step == 0:
                    percent = 26 + int((index / total_wallets) * 6)
                    _emit_progress(
                        progress_callback,
                        percent,
                        "Loading wallet context",
                        f"Loaded {index}/{total_wallets} wallet histories for replay",
                    )
            return

        owns_executor = False
        active_executor = executor
        if active_executor is None and remaining_wallets:
            active_executor = ThreadPoolExecutor(max_workers=max_workers)
            owns_executor = True

        futures = {future: wallet for wallet, future in warm_futures.items()}
        if active_executor is not None:
            for wallet in remaining_wallets:
                if trace_records is None and trace_lock is None:
                    futures[active_executor.submit(self._fetch_wallet_context, wallet, focus_markets)] = wallet
                else:
                    futures[
                        active_executor.submit(
                            self._fetch_wallet_context,
                            wallet,
                            focus_markets,
                            trace_records=trace_records,
                            trace_lock=trace_lock,
                        )
                    ] = wallet

        if not futures:
            return

        try:
            completed = 0
            for future in as_completed(futures):
                if _stop_requested(stop_event):
                    if owns_executor and active_executor is not None:
                        active_executor.shutdown(wait=False, cancel_futures=True)
                    return
                wallet = futures[future]
                wallet_cache[wallet] = future.result()
                completed += 1
                if completed == 1 or completed == total_wallets or completed % progress_step == 0:
                    percent = 26 + int((completed / total_wallets) * 6)
                    _emit_progress(
                        progress_callback,
                        percent,
                        "Loading wallet context",
                        f"Loaded {completed}/{total_wallets} wallet histories for replay",
                    )
        finally:
            if owns_executor and active_executor is not None:
                active_executor.shutdown(wait=False)

    def _wallet_enrichment(
        self,
        wallet: str,
        wallet_cache: dict[str, tuple[object, list[Trade], WalletPerformance]],
        focus_markets: dict[str, Market],
        *,
        trace_records: list[dict[str, object]] | None = None,
        trace_lock: Lock | None = None,
    ) -> tuple[object, list[Trade], WalletPerformance]:
        cached = wallet_cache.get(wallet)
        if cached is not None:
            return cached
        if trace_records is None and trace_lock is None:
            cached = self._fetch_wallet_context(wallet, focus_markets)
        else:
            cached = self._fetch_wallet_context(
                wallet,
                focus_markets,
                trace_records=trace_records,
                trace_lock=trace_lock,
            )
        wallet_cache[wallet] = cached
        return cached

    def _fetch_wallet_context(
        self,
        wallet: str,
        focus_markets: dict[str, Market],
        *,
        trace_records: list[dict[str, object]] | None = None,
        trace_lock: Lock | None = None,
    ) -> tuple[object, list[Trade], WalletPerformance]:
        started = perf_counter()
        stats_started = perf_counter()
        wallet_stats = self._client.fetch_wallet_stats(wallet, trade_limit=500)
        wallet_stats_seconds = perf_counter() - stats_started
        wallet_inspection = _build_wallet_inspection(
            wallet,
            wallet_stats.trades,
            wallet_stats.traded_market_count,
            wallet_stats.polygon_nonce,
            focus_markets,
        )
        positions_started = perf_counter()
        wallet_positions = self._client.fetch_wallet_positions(wallet)
        wallet_positions_seconds = perf_counter() - positions_started
        performance_started = perf_counter()
        wallet_performance = compute_wallet_performance(wallet_stats.trades, wallet_positions)
        wallet_performance_seconds = perf_counter() - performance_started
        _append_wallet_api_trace(
            trace_records,
            trace_lock,
            {
                "wallet": wallet,
                "totalSeconds": round(perf_counter() - started, 6),
                "walletStatsSeconds": round(wallet_stats_seconds, 6),
                "walletPositionsSeconds": round(wallet_positions_seconds, 6),
                "walletPerformanceSeconds": round(wallet_performance_seconds, 6),
                "walletStatsTradeRows": len(wallet_stats.trades),
                "walletPositionsRows": len(wallet_positions),
                "tradedMarketCountAvailable": wallet_stats.traded_market_count is not None,
                "polygonNonceAvailable": wallet_stats.polygon_nonce is not None,
            },
        )
        return wallet_inspection, wallet_stats.trades, wallet_performance

    def _prepare_candidate_contexts(
        self,
        candidate_trades: list[Trade],
        *,
        resolved: ResolvedEvent,
        scope_context: AnalysisScopeContext,
        wallet_cache: dict[str, tuple[object, list[Trade], WalletPerformance]],
        wallet_trades: dict[str, list[Trade]],
        market_trades: dict[str, list[Trade]],
        domain_trades: dict[str, list[Trade]],
        include_blockchain: bool,
        funding_trace_mode: str,
        progress_callback: callable | None,
        stop_event: object | None,
        wallet_api_trace_records: list[dict[str, object]] | None = None,
        wallet_api_trace_lock: Lock | None = None,
    ) -> tuple[
        list[CandidateReplayContext],
        dict[tuple[str, str], tuple[str, datetime]],
        dict[str, int],
    ]:
        contexts: list[CandidateReplayContext] = []
        funding_requests: dict[tuple[str, str], tuple[str, datetime]] = {}
        total_candidates = max(1, len(candidate_trades))
        progress_step = max(1, total_candidates // 6)
        all_event_condition_ids = set(resolved.markets)
        scoped_wallet_history_cache: dict[str, list[Trade]] = {}
        wallet_history_metrics_cache: dict[str, dict[str, dict[str, object]]] = {}
        profile = {
            "wallet_context_cache_hits": 0,
            "wallet_context_cache_misses": 0,
            "scoped_history_cache_hits": 0,
            "scoped_history_cache_misses": 0,
            "wallet_history_metrics_cache_hits": 0,
            "wallet_history_metrics_cache_misses": 0,
        }
        for index, trade in enumerate(candidate_trades, start=1):
            if _stop_requested(stop_event):
                break
            market = resolved.markets[trade.condition_id]
            trade_domain = _domain_for_trade(trade, scope_context.analysis_markets)
            if trade.wallet in wallet_cache:
                profile["wallet_context_cache_hits"] += 1
            else:
                profile["wallet_context_cache_misses"] += 1
            wallet_inspection, wallet_history_trades, wallet_performance = self._wallet_enrichment(
                trade.wallet,
                wallet_cache,
                scope_context.analysis_markets,
                trace_records=wallet_api_trace_records,
                trace_lock=wallet_api_trace_lock,
            )
            scoped_wallet_history_trades = scoped_wallet_history_cache.get(trade.wallet)
            if scoped_wallet_history_trades is None:
                scoped_wallet_history_trades = _scope_filter_wallet_history_trades(
                    wallet_history_trades,
                    all_event_condition_ids=all_event_condition_ids,
                    selected_condition_id=scope_context.selected_condition_id,
                )
                scoped_wallet_history_cache[trade.wallet] = scoped_wallet_history_trades
                profile["scoped_history_cache_misses"] += 1
            else:
                profile["scoped_history_cache_hits"] += 1
            wallet_trade_metrics = wallet_history_metrics_cache.get(trade.wallet)
            if wallet_trade_metrics is None:
                wallet_trade_metrics = _wallet_trade_replay_metrics(scoped_wallet_history_trades)
                wallet_history_metrics_cache[trade.wallet] = wallet_trade_metrics
                profile["wallet_history_metrics_cache_misses"] += 1
            else:
                profile["wallet_history_metrics_cache_hits"] += 1
            wallet_window_trades = wallet_trades.get(trade.wallet, [])
            market_window_trades = market_trades.get(trade.condition_id, [])
            prepared_score_context = build_score_trade_prepared_context(
                trade=trade,
                wallet_window_trades=wallet_window_trades,
                wallet_history_trades=scoped_wallet_history_trades,
                market_window_trades=market_window_trades,
            )
            execution_state = _classify_execution_state(
                trade,
                prepared_score_context.prior_same_asset_trades,
                prepared_score_context.prior_same_market_trades,
            )
            opening_exposure = _is_opening_exposure(execution_state)
            capital_at_risk = _capital_at_risk_usdc(trade, execution_state)
            conviction_ratio = prepared_score_context.wallet_market_conviction_ratio
            trade_metrics = wallet_trade_metrics.get(trade.trade_id, {})
            prior_gap_days = trade_metrics.get("prior_wallet_gap_days")
            funding_cache_key: tuple[str, str] | None = None
            funding_skip_reason = ""
            trace_wanted = include_blockchain and _should_trace_funding(
                wallet_inspection,
                trade=trade,
                mode="event_forensic",
                derived_metrics={
                    "trade_domain": trade_domain,
                    "opening_exposure_flag": opening_exposure,
                    "capital_at_risk_usdc": capital_at_risk,
                    "wallet_market_conviction_ratio": conviction_ratio,
                    "reactivated_after_dormancy_flag": bool(
                        prior_gap_days is not None and prior_gap_days >= 30
                    ),
                },
            )
            if trace_wanted:
                if funding_trace_mode == FUNDING_TRACE_MODE_DISABLED:
                    funding_skip_reason = "funding_trace_disabled_no_rpc_mode"
                    self._funding_resolver.record_trace_skipped(funding_skip_reason)
                else:
                    funding_cache_key = _funding_cache_key(trade)
                    funding_requests.setdefault(funding_cache_key, (trade.wallet, trade.timestamp))

            contexts.append(
                CandidateReplayContext(
                    trade=trade,
                    market=market,
                    trade_domain=trade_domain,
                    wallet_inspection=wallet_inspection,
                    wallet_history_trades=scoped_wallet_history_trades,
                    wallet_performance=wallet_performance,
                    market_window_trades=market_window_trades,
                    domain_window_trades=domain_trades.get(trade_domain, []),
                    event_context=self._event_context_resolver.resolve(
                        trade=trade,
                        market=market,
                        trade_domain=trade_domain,
                        market_deadline_flag=_looks_like_deadline_market(market.question),
                    ),
                    funding_cache_key=funding_cache_key,
                    prior_wallet_gap_days=trade_metrics.get("prior_wallet_gap_days"),
                    observed_post_trade_gap_days=trade_metrics.get("observed_post_trade_gap_days"),
                    family_key=str(trade_metrics.get("family_key") or ""),
                    prior_family_trade_count=int(trade_metrics.get("prior_family_trade_count") or 0),
                    prior_family_market_count=int(trade_metrics.get("prior_family_market_count") or 0),
                    event_family_share=float(trade_metrics.get("event_family_share") or 0.0),
                    funding_skip_reason=funding_skip_reason,
                    prepared_score_context=prepared_score_context,
                )
            )
            if index == 1 or index == total_candidates or index % progress_step == 0:
                percent = 31 + int((index / total_candidates) * 5)
                _emit_progress(
                    progress_callback,
                    percent,
                    "Preparing replay",
                    f"Prepared {index}/{total_candidates} candidate trade contexts",
                )
        return contexts, funding_requests, profile

    def _prefetch_funding_contexts(
        self,
        funding_requests: dict[tuple[str, str], tuple[str, datetime]],
        funding_cache: dict[tuple[str, str], FundingContext],
        *,
        funding_trace_mode: str,
        progress_callback: callable | None,
        stop_event: object | None,
    ) -> None:
        if funding_trace_mode == FUNDING_TRACE_MODE_DISABLED or not funding_requests:
            return

        items = list(funding_requests.items())
        total = len(items)
        max_workers = (
            1
            if funding_trace_mode == FUNDING_TRACE_MODE_CACHE_ONLY
            else min(EVENT_FORENSIC_FUNDING_PREFETCH_WORKERS, total)
        )
        progress_step = max(1, total // 6)
        progress_stage = _funding_progress_stage(funding_trace_mode)

        if max_workers <= 1:
            for index, (cache_key, (wallet, trade_time)) in enumerate(items, start=1):
                if _stop_requested(stop_event):
                    return
                funding_cache[cache_key] = self._funding_resolver.analyze(wallet, trade_time)
                if index == 1 or index == total or index % progress_step == 0:
                    percent = 37 + int((index / total) * 8)
                    _emit_progress(
                        progress_callback,
                        percent,
                        progress_stage,
                        f"Resolved {index}/{total} funding contexts",
                    )
            return

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._funding_resolver.analyze, wallet, trade_time): cache_key
                for cache_key, (wallet, trade_time) in items
            }
            completed = 0
            pending = set(futures)
            while pending:
                if _stop_requested(stop_event):
                    executor.shutdown(wait=False, cancel_futures=True)
                    return
                done, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
                if not done:
                    _emit_progress(
                        progress_callback,
                        37 + int((completed / total) * 8),
                        progress_stage,
                        f"Resolved {completed}/{total} funding contexts; waiting for active traces",
                    )
                    continue
                for future in done:
                    funding_cache[futures[future]] = future.result()
                    completed += 1
                    if completed == 1 or completed == total or completed % progress_step == 0:
                        percent = 37 + int((completed / total) * 8)
                        _emit_progress(
                            progress_callback,
                            percent,
                            progress_stage,
                            f"Resolved {completed}/{total} funding contexts",
                        )

    def _collect_price_history_timed(
        self,
        resolved: ResolvedEvent,
        analysis_markets: dict[str, Market],
        trades: list[Trade],
        stop_event: object | None,
    ) -> tuple[dict[str, dict[str, object]], float]:
        started = perf_counter()
        history = self._collect_price_history(
            resolved,
            analysis_markets,
            trades,
            progress_callback=None,
            stop_event=stop_event,
        )
        return history, round(perf_counter() - started, 2)

    def _discover_related_markets_timed(
        self,
        resolved: ResolvedEvent,
        wallet_cache: dict[str, tuple[object, list[Trade], WalletPerformance]],
        include_related_markets: bool,
    ) -> tuple[list[dict[str, object]], float]:
        started = perf_counter()
        rows = self._discover_related_markets(
            resolved,
            wallet_cache,
            include_related_markets=include_related_markets,
        )
        return rows, round(perf_counter() - started, 2)

    def _fetch_market_trade_slice(
        self,
        condition_id: str,
        *,
        start_ts: int,
        end_ts: int,
        minimum_notional: Decimal | None = None,
    ) -> tuple[str, list[Trade], bool]:
        market_trades = self._client.fetch_trades_in_range(
            start_ts=start_ts,
            end_ts=end_ts,
            max_pages=self._config.max_trade_pages,
            page_size=self._config.trade_page_size,
            condition_ids=[condition_id],
        )
        filtered_trades: list[Trade] = []
        if minimum_notional is not None and minimum_notional > 0:
            filtered_trades = self._client.fetch_trades_in_range(
                start_ts=start_ts,
                end_ts=end_ts,
                max_pages=self._config.max_trade_pages,
                page_size=self._config.trade_page_size,
                condition_ids=[condition_id],
                filter_cash_amount=minimum_notional,
            )
            market_trades = _dedupe_trades([*market_trades, *filtered_trades])
        max_retrievable = min(
            self._config.max_trade_pages * self._config.trade_page_size,
            MAX_TRADES_OFFSET + self._config.trade_page_size,
        )
        truncated = len(market_trades) >= max_retrievable or len(filtered_trades) >= max_retrievable
        return condition_id, market_trades, truncated

    def _fetch_market_price_payload(
        self,
        market: Market,
        winner: str | None,
        start_ts: int,
        end_ts: int,
    ) -> tuple[str, dict[str, object]]:
        token_ids = list(market.token_ids)
        asset_id = None
        if winner and winner in market.outcomes:
            try:
                asset_id = token_ids[market.outcomes.index(winner)]
            except (IndexError, ValueError):
                asset_id = token_ids[0] if token_ids else None
        else:
            asset_id = token_ids[0] if token_ids else None
        if not asset_id:
            return market.condition_id, {"asset_id": "", "winner_outcome": winner, "points": []}
        try:
            series = self._client.fetch_price_history(asset_id, start_ts, end_ts)
        except Exception:
            series = []
        return market.condition_id, {
            "asset_id": asset_id,
            "winner_outcome": winner,
            "points": series,
        }

    def _collect_event_trades(
        self,
        resolved: ResolvedEvent,
        *,
        minimum_notional: Decimal | None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        progress_callback: callable | None = None,
        stop_event: object | None = None,
        on_market_trades: callable | None = None,
        collection_progress: dict[str, object] | None = None,
        single_market_sibling_context_count: int = 0,
        selected_condition_id_present: bool = False,
        total_event_market_count: int | None = None,
    ) -> tuple[list[Trade], int]:
        event_start, event_end = _analysis_time_bounds(resolved)
        now = datetime.now(UTC)
        event_closed = _event_closed_for_report(resolved)
        if not event_closed:
            event_end = now
        if not event_closed and event_start is not None and event_end is not None and event_start >= event_end:
            event_start = None
        if event_start is None and event_end is not None and event_closed:
            event_start = event_end - timedelta(days=14)
        if event_start is None:
            event_start = now - timedelta(days=365)
        if event_end is None:
            event_end = now
        end_padding = timedelta(days=7) if event_closed else timedelta()
        end_ts = int((event_end + end_padding).timestamp())
        start_ts = max(0, int((event_start - timedelta(days=1)).timestamp()))
        if start_at is not None:
            start_ts = max(0, int(start_at.timestamp()))
        if end_at is not None:
            end_ts = int(end_at.timestamp())
        if end_ts <= start_ts:
            return [], 0

        all_trades: list[Trade] = []
        truncated_market_count = 0
        condition_ids = list(resolved.markets)
        total_markets = max(1, len(condition_ids))
        max_workers = min(EVENT_FORENSIC_MARKET_FETCH_WORKERS, total_markets)
        collection_started = perf_counter()

        def market_slug(condition_id: str) -> str:
            market = resolved.markets.get(condition_id)
            if market is not None:
                return market.slug or condition_id
            payload = resolved.market_payloads.get(condition_id) or {}
            return str(payload.get("slug") or condition_id)

        def progress_metadata(
            *,
            completed: int,
            condition_id: str,
        ) -> dict[str, object]:
            elapsed = round(perf_counter() - collection_started, 2)
            metrics: dict[str, object] = {
                "tradeCollectionStage": "collecting_trades",
                "analysisMarketTotal": total_markets,
                "analysisMarketCompleted": completed,
                "truncatedMarketCountSoFar": truncated_market_count,
                "rawTradeRowsCollectedSoFar": len(all_trades),
                "lastCollectedMarketSlug": market_slug(condition_id),
                "collectionElapsedSeconds": elapsed,
                "collectionRiskClass": _trade_collection_risk_class(
                    truncated_market_count=truncated_market_count,
                    collection_elapsed_seconds=elapsed,
                    analysis_market_count=total_markets,
                    total_event_market_count=int(total_event_market_count or total_markets),
                    selected_condition_id_present=selected_condition_id_present,
                ),
                "singleMarketSiblingContextCount": single_market_sibling_context_count,
            }
            if collection_progress is not None:
                collection_progress.update(metrics)
            return metrics

        if collection_progress is not None:
            collection_progress.update(
                {
                    "tradeCollectionStage": "collecting_trades",
                    "analysisMarketTotal": total_markets,
                    "analysisMarketCompleted": 0,
                    "truncatedMarketCountSoFar": 0,
                    "rawTradeRowsCollectedSoFar": 0,
                    "lastCollectedMarketSlug": "",
                    "collectionElapsedSeconds": 0.0,
                    "collectionRiskClass": "collection_profile_normal",
                    "singleMarketSiblingContextCount": single_market_sibling_context_count,
                }
            )

        if max_workers <= 1:
            for index, condition_id in enumerate(condition_ids, start=1):
                if _stop_requested(stop_event):
                    break
                _condition_id, market_trades, truncated = self._fetch_market_trade_slice(
                    condition_id,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    minimum_notional=minimum_notional,
                )
                if truncated:
                    truncated_market_count += 1
                all_trades.extend(market_trades)
                if on_market_trades is not None and market_trades:
                    on_market_trades(_condition_id, market_trades)
                percent = 10 + int((index / total_markets) * 12)
                _emit_progress(
                    progress_callback,
                    percent,
                    "Loading trades",
                    f"Fetched market {index}/{total_markets} for the target event",
                    metadata=progress_metadata(completed=index, condition_id=_condition_id),
                )
            return all_trades, truncated_market_count

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._fetch_market_trade_slice,
                    condition_id,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    minimum_notional=minimum_notional,
                ): condition_id
                for condition_id in condition_ids
            }
            completed = 0
            for future in as_completed(futures):
                if _stop_requested(stop_event):
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                _condition_id, market_trades, truncated = future.result()
                if truncated:
                    truncated_market_count += 1
                all_trades.extend(market_trades)
                if on_market_trades is not None and market_trades:
                    on_market_trades(_condition_id, market_trades)
                completed += 1
                percent = 10 + int((completed / total_markets) * 12)
                _emit_progress(
                    progress_callback,
                    percent,
                    "Loading trades",
                    f"Fetched market {completed}/{total_markets} for the target event",
                    metadata=progress_metadata(completed=completed, condition_id=_condition_id),
                )
        return all_trades, truncated_market_count

    def _collect_price_history(
        self,
        resolved: ResolvedEvent,
        analysis_markets: dict[str, Market],
        trades: list[Trade],
        progress_callback: callable | None,
        stop_event: object | None,
    ) -> dict[str, dict[str, object]]:
        if not trades:
            return {}
        start_ts = int(min(trade.timestamp for trade in trades).timestamp()) - 3600
        end_ts = int(max(trade.timestamp for trade in trades).timestamp()) + 24 * 3600
        history: dict[str, dict[str, object]] = {}
        markets = list(analysis_markets.values())
        total_markets = max(1, len(markets))
        max_workers = min(EVENT_FORENSIC_PRICE_HISTORY_WORKERS, total_markets)

        if max_workers <= 1:
            for index, market in enumerate(markets, start=1):
                if _stop_requested(stop_event):
                    break
                winner = _winning_outcome_from_payload(resolved.market_payloads.get(market.condition_id, {}))
                condition_id, payload = self._fetch_market_price_payload(market, winner, start_ts, end_ts)
                history[condition_id] = payload
                _emit_progress(
                    progress_callback,
                    60 + int((index / total_markets) * 8),
                    "Loading prices",
                    f"Fetched price history {index}/{total_markets}",
                )
            return history

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._fetch_market_price_payload,
                    market,
                    _winning_outcome_from_payload(resolved.market_payloads.get(market.condition_id, {})),
                    start_ts,
                    end_ts,
                ): market.condition_id
                for market in markets
            }
            completed = 0
            for future in as_completed(futures):
                if _stop_requested(stop_event):
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                condition_id, payload = future.result()
                history[condition_id] = payload
                completed += 1
                _emit_progress(
                    progress_callback,
                    60 + int((completed / total_markets) * 8),
                    "Loading prices",
                    f"Fetched price history {completed}/{total_markets}",
                )
        return history

    def _eligibility_payload(self, resolved: ResolvedEvent) -> dict[str, object]:
        closed_markets = [bool(payload.get("closed", False)) for payload in resolved.market_payloads.values()]
        winner_known = [
            _winning_outcome_from_payload(payload) is not None
            for payload in resolved.market_payloads.values()
        ]
        all_closed = bool(closed_markets) and all(closed_markets)
        fully_resolved = all_closed and all(winner_known)
        resolved_market_count = sum(1 for item in winner_known if item)
        unresolved_market_count = len(winner_known) - resolved_market_count
        base = {
            "eligible": True,
            "resolved_market_count": resolved_market_count,
            "unresolved_market_count": unresolved_market_count,
            "outcome_context_available": resolved_market_count > 0,
        }
        if fully_resolved:
            return {**base, "reason": "", "status": "eligible"}
        if resolved_market_count > 0:
            return {
                **base,
                "reason": (
                    f"Partial event analysis: {resolved_market_count} market(s) have final outcomes and "
                    f"{unresolved_market_count} still do not."
                ),
                "status": "partial",
            }
        if not resolved.event_closed and not all_closed:
            return {
                **base,
                "reason": (
                    "Live event analysis: no market has a final resolved outcome yet, so later-correctness "
                    "and winner ranking are disabled. Rankings still use current scanner, timing, wallet, "
                    "funding, repricing, and linkage evidence."
                ),
                "status": "live",
            }
        return {
            **base,
            "reason": (
                "The event is closed but does not expose a final resolved outcome yet, so later-correctness "
                "and winner ranking are disabled. Rankings still use current scanner, timing, wallet, "
                "funding, repricing, and linkage evidence."
            ),
            "status": "unresolved",
        }

    def _build_ineligible_report(
        self,
        *,
        started_at: datetime,
        resolved: ResolvedEvent,
        scope_context: AnalysisScopeContext,
        threshold: Decimal,
        eligibility: dict[str, object],
        include_related_markets: bool,
    ) -> dict[str, object]:
        scope_product_metadata = _scope_product_metadata(
            resolved,
            scope_context,
            include_related_markets=include_related_markets,
        )
        scope_summary_metadata = _scope_summary_metadata(
            resolved,
            scope_context,
            include_related_markets=include_related_markets,
        )
        report = {
            "analysis_version": EVENT_ANALYSIS_VERSION,
            "generated_at": started_at.isoformat(),
            "status": "preview_only",
            "input_url": resolved.input_value,
            **_analysis_scope_metadata(resolved, scope_context),
            **scope_product_metadata,
            "target_resolution": self._resolved_target_payload(resolved, scope_context),
            "event": {
                "id": resolved.event_id,
                "slug": resolved.event_slug,
                "title": resolved.event_title,
                "canonicalUrl": resolved.canonical_url,
                "completed": False,
                "resolutionStatus": eligibility.get("status", "preview_only"),
                "outcomeContextAvailable": _eligibility_has_outcome_context(eligibility),
                "marketCount": len(resolved.markets),
                "analysisMarketCount": len(scope_context.analysis_markets),
                "familyId": resolved.event_family_id,
            },
            "eligibility": eligibility,
            "analysis_settings": {
                "min_notional": f"{threshold:.2f}",
                "include_related_markets": include_related_markets,
                "include_blockchain": True,
                "analysis_scope": scope_context.analysis_scope,
                "primary_scoring_scope": scope_product_metadata["primaryScoringScope"],
                "related_markets_context_included": scope_product_metadata["relatedMarketsContextIncluded"],
                "sibling_markets_primary_scored": scope_product_metadata["siblingMarketsPrimaryScored"],
                "selected_condition_id": scope_context.selected_condition_id,
                "selected_market_slug": scope_context.selected_market_slug,
            },
            "summary": {
                **scope_summary_metadata,
                "raw_trade_count": 0,
                "candidate_trade_count": 0,
                "existing_flagged_count": 0,
                "forensic_suspicious_trade_count": 0,
                "suspicious_wallet_count": 0,
                "wallet_cluster_count": 0,
                "unique_wallet_count": 0,
                "unique_market_count": len(scope_context.analysis_markets),
                "analysis_market_count": len(scope_context.analysis_markets),
                "total_event_market_count": len(resolved.markets),
                "truncated_market_count": 0,
            },
            "markets": self._market_summaries(
                resolved,
                [],
                [],
                {},
                {},
                analysis_markets=scope_context.analysis_markets,
            ),
            "timeline_points": [],
            "scope_note": _scope_note(scope_context),
            "empty_state_note": "",
            "suspicious_trades": [],
            "suspicious_wallets": [],
            "wallet_clusters": [],
            "display_trades": [],
            "display_wallets": [],
            "display_clusters": [],
            "wallet_graph": {"nodes": [], "edges": []},
            "related_markets": [],
            "model_gap": {
                "caught_by_existing": [],
                "missed_by_existing": [],
                "overflagged_by_existing": [],
                "recommended_heuristics": [],
                "summary": eligibility["reason"],
            },
        }
        report["event_report_markdown"] = self._event_report_markdown(report)
        report["model_gap_markdown"] = self._model_gap_markdown(report)
        return report

    def _build_stopped_report(
        self,
        started_at: datetime,
        reports_dir: Path,
        resolved: ResolvedEvent,
        scope_context: AnalysisScopeContext,
        threshold: Decimal,
        raw_trades: list[Trade],
        truncated_market_count: int,
        include_related_markets: bool,
        include_blockchain: bool,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> dict[str, object]:
        eligibility = self._eligibility_payload(resolved)
        scope_product_metadata = _scope_product_metadata(
            resolved,
            scope_context,
            include_related_markets=include_related_markets,
        )
        scope_summary_metadata = _scope_summary_metadata(
            resolved,
            scope_context,
            include_related_markets=include_related_markets,
        )
        report = {
            "analysis_version": EVENT_ANALYSIS_VERSION,
            "generated_at": started_at.isoformat(),
            "status": "stopped",
            "input_url": resolved.input_value,
            **_analysis_scope_metadata(resolved, scope_context),
            **scope_product_metadata,
            "target_resolution": self._resolved_target_payload(resolved, scope_context),
            "event": {
                "id": resolved.event_id,
                "slug": resolved.event_slug,
                "title": resolved.event_title,
                "canonicalUrl": resolved.canonical_url,
                "completed": _event_closed_for_report(resolved),
                "resolutionStatus": eligibility.get("status", "eligible"),
                "outcomeContextAvailable": _eligibility_has_outcome_context(eligibility),
                "marketCount": len(resolved.markets),
                "analysisMarketCount": len(scope_context.analysis_markets),
                "familyId": resolved.event_family_id,
            },
            "eligibility": eligibility,
            "analysis_settings": {
                "min_notional": f"{threshold:.2f}",
                "include_related_markets": include_related_markets,
                "include_blockchain": include_blockchain,
                "analysis_scope": scope_context.analysis_scope,
                "primary_scoring_scope": scope_product_metadata["primaryScoringScope"],
                "related_markets_context_included": scope_product_metadata["relatedMarketsContextIncluded"],
                "sibling_markets_primary_scored": scope_product_metadata["siblingMarketsPrimaryScored"],
                "selected_condition_id": scope_context.selected_condition_id,
                "selected_market_slug": scope_context.selected_market_slug,
                "start_at": start_at.isoformat() if start_at else "",
                "end_at": end_at.isoformat() if end_at else "",
            },
            "summary": {
                **scope_summary_metadata,
                "raw_trade_count": len(raw_trades),
                "candidate_trade_count": 0,
                "existing_flagged_count": 0,
                "forensic_suspicious_trade_count": 0,
                "suspicious_wallet_count": 0,
                "wallet_cluster_count": 0,
                "unique_wallet_count": len({trade.wallet for trade in raw_trades}),
                "unique_market_count": len({trade.condition_id for trade in raw_trades}),
                "analysis_market_count": len(scope_context.analysis_markets),
                "total_event_market_count": len(resolved.markets),
                "truncated_market_count": truncated_market_count,
            },
            "markets": self._market_summaries(
                resolved,
                raw_trades,
                [],
                {},
                {},
                analysis_markets=scope_context.analysis_markets,
            ),
            "timeline_points": [],
            "scope_note": _scope_note(scope_context),
            "empty_state_note": "",
            "suspicious_trades": [],
            "suspicious_wallets": [],
            "wallet_clusters": [],
            "display_trades": [],
            "display_wallets": [],
            "display_clusters": [],
            "wallet_graph": {"nodes": [], "edges": []},
            "related_markets": [],
            "model_gap": {
                "caught_by_existing": [],
                "missed_by_existing": [],
                "overflagged_by_existing": [],
                "recommended_heuristics": [],
                "summary": "The run was stopped before the event-forensic ranking finished.",
            },
        }
        report["event_report_markdown"] = self._event_report_markdown(report)
        report["model_gap_markdown"] = self._model_gap_markdown(report)
        export_files = self._write_report_bundle(
            started_at,
            reports_dir,
            report,
            suspicious_trades=[],
            suspicious_wallets=[],
            ranked_wallets=[],
            wallet_clusters=[],
            wallet_graph={"nodes": [], "edges": []},
            related_markets=[],
            candidate_audit_rows=[],
            raw_bundle={
                "analysis_scope_metadata": _analysis_scope_metadata(resolved, scope_context),
                "trades": [trade.to_dict() for trade in raw_trades],
            },
        )
        report["export_files"] = export_files
        report["report_json_path"] = export_files["report_json_path"]
        report["report_md_path"] = export_files["event_report_md_path"]
        report["report_txt_path"] = export_files["event_report_md_path"]
        return report

    def _build_trade_payloads(
        self,
        *,
        resolved: ResolvedEvent,
        cases: list[FlaggedCase],
        wallet_cache: dict[str, tuple[object, list[Trade], WalletPerformance]],
        winners_by_condition: dict[str, str | None],
        related_market_rows: list[dict[str, object]],
        analysis_scope: str,
        sibling_market_activity: dict[str, dict[str, int]],
        scope_context: AnalysisScopeContext,
    ) -> list[dict[str, object]]:
        related_by_wallet = Counter(row["wallet"] for row in related_market_rows)
        wallet_case_groups: dict[str, list[FlaggedCase]] = defaultdict(list)
        for case in cases:
            wallet_case_groups[case.trade.wallet].append(case)

        winning_entry_ranks = _winning_entry_ranks(cases, winners_by_condition)
        payloads: list[dict[str, object]] = []
        for case in cases:
            trade = case.trade
            raw = case.raw_metrics
            wallet = trade.wallet
            market = case.market
            wallet_context = wallet_cache.get(wallet)
            wallet_inspection = wallet_context[0] if wallet_context is not None else None
            wallet_total_predictions = getattr(wallet_inspection, "traded_market_count", None)
            wallet_loaded_history_trade_count = int(getattr(wallet_inspection, "recent_trade_count", 0) or 0)
            wallet_loaded_unique_market_count = int(getattr(wallet_inspection, "unique_market_count", 0) or 0)
            wallet_joined_at = str(getattr(wallet_inspection, "first_trade_at", "") or "")
            winner = winners_by_condition.get(trade.condition_id)
            outcome_known = bool(winner)
            later_won = bool(raw.get("trade_state") == "increase" and _case_economic_side_won(case, winner))
            related_count = related_by_wallet.get(wallet, 0)
            scored_related_count = 0 if analysis_scope == "market" else related_count
            sibling_activity = sibling_market_activity.get(
                wallet,
                {"otherEventMarketTrades": 0, "siblingMarketActivityCount": 0},
            )
            wallet_cases = wallet_case_groups[wallet]
            wallet_winning_entries = sum(
                1
                for item in wallet_cases
                if item.raw_metrics.get("trade_state") == "increase"
                and _case_economic_side_won(item, winners_by_condition.get(item.trade.condition_id))
            )
            wallet_opening_entries = sum(
                1 for item in wallet_cases if item.raw_metrics.get("trade_state") == "increase"
            )
            score, flags, notes, reducers = _event_forensic_score(
                case=case,
                later_won=later_won,
                winner_rank=winning_entry_ranks.get(trade.trade_id),
                related_market_count=scored_related_count,
                wallet_winning_entries=wallet_winning_entries,
                wallet_opening_entries=wallet_opening_entries,
            )
            caught_by_existing = _case_survives_output_threshold(case)
            hard_evidence_sources = _text_values(raw.get("hardEvidenceSources"))
            hard_evidence_trade_ids = _text_values(raw.get("hardEvidenceTradeIds"))
            hard_evidence_wallet_ids = _text_values(raw.get("hardEvidenceWalletIds"))
            final_event_judgment = _event_judgment(
                score,
                later_won=later_won,
                opening_exposure=raw.get("opening_exposure_flag") == "Yes" or raw.get("trade_state") == "increase",
            )
            side_outcome_context = normalize_side_outcome(trade.side, trade.outcome, trade.price).to_payload()
            cluster_context = normalize_cluster_direction(trade.side, trade.outcome, trade.price).to_payload()
            model_probability = side_outcome_context.get("economicSideProbability")
            if not isinstance(model_probability, (int, float)):
                model_probability = float(trade.price)
            strong_risk_attribution = {
                field: raw.get(field, "")
                for field in STRONG_RISK_ATTRIBUTION_FIELDS
            }
            if final_event_judgment.startswith("Strong Risk"):
                existing_sources = _text_values(strong_risk_attribution.get("strongRiskGateEvidenceSources"))
                retrospective_sources = ["event_forensic_retrospective_correctness"]
                if later_won:
                    retrospective_sources.append("later_correctness")
                if winning_entry_ranks.get(trade.trade_id):
                    retrospective_sources.append("winner_rank")
                opening_exposure_status = (
                    "confirmed"
                    if raw.get("opening_exposure_flag") == "Yes" or raw.get("trade_state") == "increase"
                    else "not_confirmed"
                )
                retrospective_gate_inputs = {
                    "retrospective_event_forensic": True,
                    "later_correctness": later_won,
                    "winner_rank": winning_entry_ranks.get(trade.trade_id) or "",
                    "low_probability_winner": bool(model_probability <= 0.35),
                    "dormant_after_win": "dormant_after_win" in flags,
                    "resolved_event_only": True,
                    "live_detectable": False,
                }
                exact_gate_inputs = {
                    "retrospective_event_forensic_gate": True,
                    "timing_led_gate": False,
                    "structure_led_gate": False,
                    "score": score,
                }
                independent_evidence_sources = _dedupe_labels(
                    [source for source in hard_evidence_sources if source != "suspicious_recent_funding"]
                )
                gate_trace = {
                    "gateName": "retrospective_event_forensic_gate",
                    "gateFamily": "retrospective_correctness",
                    "gateType": "retrospective_event_forensic",
                    "composition": "retrospective_correctness",
                    "exactGateBranch": "retrospective_event_forensic_gate",
                    "strongRisk": True,
                    "score": score,
                    "confidenceScore": case.confidence_score,
                    "timingSources": _text_values(strong_risk_attribution.get("strongRiskTimingProofSources")),
                    "structuralSources": _text_values(strong_risk_attribution.get("strongRiskStructuralSources")),
                    "boosterSources": _text_values(strong_risk_attribution.get("strongRiskSupportingBoosters")),
                    "hardEvidenceSources": hard_evidence_sources,
                    "independentEvidenceSources": independent_evidence_sources,
                    "hasIndependentHardEvidence": bool(independent_evidence_sources),
                    "suppressorConflictReasons": _text_values(strong_risk_attribution.get("strongRiskSuppressorConflictReasons")),
                    "openingExposureStatus": opening_exposure_status,
                    "timingRepricingOnly": False,
                    "retrospectiveOnly": True,
                    "scoreOnly": False,
                    "savedFieldsSufficient": True,
                    "diagnosticOnly": True,
                }
                strong_risk_attribution.update(
                    {
                        "strongRiskGateTrace": json.dumps(gate_trace, sort_keys=True),
                        "strongRiskGateName": "retrospective_event_forensic_gate",
                        "strongRiskGateFamily": "retrospective_correctness",
                        "strongRiskGateInputs": json.dumps(
                            {
                                "exact": json.dumps(exact_gate_inputs, sort_keys=True),
                                "retrospective": json.dumps(retrospective_gate_inputs, sort_keys=True),
                                "structure": "",
                                "timing": "",
                            },
                            sort_keys=True,
                        ),
                        "strongRiskGatePassed": "Yes",
                        "strongRiskGateType": "retrospective_event_forensic",
                        "strongRiskGateReasons": "event_forensic_retrospective_correctness",
                        "strongRiskGateEvidenceSources": "; ".join(
                            _dedupe_labels(retrospective_sources + existing_sources)
                        ),
                        "strongRiskOpeningExposureConfirmed": (
                            "Yes"
                            if raw.get("opening_exposure_flag") == "Yes" or raw.get("trade_state") == "increase"
                            else "No"
                        ),
                        "strongRiskSuspicionScore": str(score),
                        "strongRiskHasIndependentHardEvidence": "Yes" if independent_evidence_sources else "No",
                        "strongRiskIndependentEvidenceSources": "; ".join(independent_evidence_sources),
                        "strongRiskHasHardEvidenceSources": "Yes" if hard_evidence_sources else "No",
                        "strongRiskNoHardEvidenceExplanation": (
                            ""
                            if hard_evidence_sources
                            else "Retrospective event-forensic correctness/rank, not structural hard evidence."
                        ),
                        "strongRiskCompositionClass": "retrospective_correctness",
                        "strongRiskExactGateBranch": "retrospective_event_forensic_gate",
                        "strongRiskExactGatePassed": "Yes",
                        "strongRiskExactGateFailedReasons": "",
                        "strongRiskExactGateInputs": json.dumps(exact_gate_inputs, sort_keys=True),
                        "strongRiskRetrospectiveGateInputs": json.dumps(retrospective_gate_inputs, sort_keys=True),
                        "strongRiskGateSourceWasInferred": "No",
                        "strongRiskGateSourceInferenceReason": "",
                        "strongRiskScoreOnlyResolution": "not_applicable",
                        "strongRiskGateLeakageCandidate": "No",
                        "strongRiskGateLeakageReason": "",
                        "strongRiskLiveDetectable": "No",
                        "strongRiskRetrospectiveOnly": "Yes",
                        "strongRiskRetrospectiveSources": "; ".join(_dedupe_labels(retrospective_sources)),
                        "strongRiskOpeningExposureStatus": opening_exposure_status,
                        "strongRiskTimingRepricingOnly": "No",
                        "strongRiskScoreOnly": "No",
                        "strongRiskSavedFieldsSufficient": "Yes",
                        "strongRiskDiagnosticOnly": "Yes",
                    }
                )
            payloads.append(
                {
                    "id": trade.trade_id,
                    "analysisScope": analysis_scope,
                    "selectedConditionId": scope_context.selected_condition_id,
                    "selectedMarketSlug": scope_context.selected_market_slug,
                    "selectedMarketTitle": scope_context.selected_market_title,
                    "parentEventSlug": resolved.event_slug,
                    "conditionId": trade.condition_id,
                    "wallet": wallet,
                    "walletShort": _short_wallet(wallet),
                    "username": _trade_username(trade),
                    "market": trade.title,
                    "marketSlug": market.slug,
                    "marketUrl": f"https://polymarket.com/event/{trade.event_slug or market.slug}",
                    "profileUrl": f"https://polymarket.com/profile/{wallet}",
                    "walletTotalPredictions": wallet_total_predictions if wallet_total_predictions is not None else "",
                    "walletProfileViews": "",
                    "walletJoinedAt": wallet_joined_at,
                    "walletProfileAgeDays": _profile_age_days(wallet_joined_at, trade.timestamp),
                    "walletLoadedHistoryTradeCount": wallet_loaded_history_trade_count,
                    "walletLoadedUniqueMarketCount": wallet_loaded_unique_market_count,
                    "timestamp": trade.timestamp.isoformat(),
                    "displayTime": _display_time(trade.timestamp.isoformat()),
                    "side": trade.outcome,
                    "orderSide": trade.side,
                    "price": float(trade.price),
                    **side_outcome_context,
                    **cluster_context,
                    "positionSize": float(trade.notional),
                    "liquidityShare": raw.get("liquidity_ratio", "Unavailable"),
                    "openingExposure": raw.get("trade_state") == "increase",
                    "laterWon": later_won,
                    "winningOutcome": winner or "Unknown",
                    "outcomeKnown": outcome_known,
                    "outcomeStatus": "resolved" if outcome_known else "unknown",
                    "winnerRank": winning_entry_ranks.get(trade.trade_id),
                    "existingModelScore": case.suspicion_score,
                    "existingModelClass": case.severity,
                    "existingModelVerdict": case.verdict,
                    "existingModelFlags": list(case.flags),
                    "existingModelCaught": caught_by_existing,
                    "existingWhy": list(case.explanation),
                    "reducesConcern": list(case.reasons_against),
                    "eventForensicScore": score,
                    "eventForensicFlags": flags,
                    "eventForensicNotes": notes,
                    "eventForensicReducers": reducers,
                    "hardEvidenceSources": hard_evidence_sources,
                    "hardEvidenceStrength": raw.get("hardEvidenceStrength", "None"),
                    "hardEvidencePrimaryReason": raw.get("hardEvidencePrimaryReason", ""),
                    "hardEvidenceTradeIds": hard_evidence_trade_ids,
                    "hardEvidenceWalletIds": hard_evidence_wallet_ids,
                    "hardEvidenceReviewTier": raw.get("hardEvidenceReviewTier", ""),
                    "evidenceAvailabilityStage": raw.get("evidenceAvailabilityStage", ""),
                    "candidateAdmissionReason": raw.get("candidateAdmissionReason", ""),
                    "candidateAdmissionStage": raw.get("candidateAdmissionStage", ""),
                    "candidateAdmissionEvidenceSources": raw.get("candidateAdmissionEvidenceSources", ""),
                    "candidateAdmissionFloorNotional": raw.get("candidateAdmissionFloorNotional", ""),
                    "groupedCandidateId": raw.get("groupedCandidateId", ""),
                    "groupedCandidateAggregateNotional": raw.get("groupedCandidateAggregateNotional", ""),
                    "groupedCandidateWalletCount": raw.get("groupedCandidateWalletCount", ""),
                    "groupedCandidateStrictFunding": raw.get("groupedCandidateStrictFunding", ""),
                    "groupedCandidateProxyOnly": raw.get("groupedCandidateProxyOnly", ""),
                    "groupedCandidateFundingGrade": raw.get("groupedCandidateFundingGrade", ""),
                    "groupedCandidateTimeSpanMinutes": raw.get("groupedCandidateTimeSpanMinutes", ""),
                    "groupedCandidatePriceBand": raw.get("groupedCandidatePriceBand", ""),
                    "candidateAdmissionValidatedOpeningExposure": raw.get("candidateAdmissionValidatedOpeningExposure", ""),
                    "candidateAdmissionRejectedReason": raw.get("candidateAdmissionRejectedReason", ""),
                    "finalEventJudgment": final_event_judgment,
                    **strong_risk_attribution,
                    "relatedMarketTrades": related_count,
                    "otherEventMarketTrades": sibling_activity["otherEventMarketTrades"],
                    "siblingMarketActivityCount": sibling_activity["siblingMarketActivityCount"],
                    "fundingKey": raw.get("funding_graph_key", ""),
                    "fundingEvidenceGrade": raw.get("funding_evidence_grade") or raw.get("fundingEvidenceGrade", ""),
                    "suspiciousFundingQuality": raw.get("suspiciousFundingQuality", ""),
                    "suspiciousFundingQualityReasons": raw.get("suspiciousFundingQualityReasons", ""),
                    "suspiciousFundingHardEvidenceEligible": raw.get("suspiciousFundingHardEvidenceEligible", ""),
                    "suspiciousFundingTraceSucceeded": raw.get("suspiciousFundingTraceSucceeded", ""),
                    "suspiciousFundingTraceDepth": raw.get("suspiciousFundingTraceDepth", ""),
                    "suspiciousFundingSourceCategory": raw.get("suspiciousFundingSourceCategory", ""),
                    "suspiciousFundingOriginCategory": raw.get("suspiciousFundingOriginCategory", ""),
                    "suspiciousFundingMinutesBeforeTrade": raw.get("suspiciousFundingMinutesBeforeTrade", ""),
                    "suspiciousFundingAmountUsd": raw.get("suspiciousFundingAmountUsd", ""),
                    "suspiciousFundingTradeNotionalUsd": raw.get("suspiciousFundingTradeNotionalUsd", ""),
                    "suspiciousFundingAmountToTradeRatio": raw.get("suspiciousFundingAmountToTradeRatio", ""),
                    "suspiciousFundingRecentEnough": raw.get("suspiciousFundingRecentEnough", ""),
                    "suspiciousFundingAmountAligned": raw.get("suspiciousFundingAmountAligned", ""),
                    "suspiciousFundingIndependentSupport": raw.get("suspiciousFundingIndependentSupport", ""),
                    "suspiciousFundingIndependentSupportSources": raw.get("suspiciousFundingIndependentSupportSources", ""),
                    "suspiciousFundingSuppressorConflict": raw.get("suspiciousFundingSuppressorConflict", ""),
                    "suspiciousFundingSuppressorConflictReasons": raw.get("suspiciousFundingSuppressorConflictReasons", ""),
                    "fundingResolverAvailable": raw.get("fundingResolverAvailable", ""),
                    "fundingResolverDisabledReason": raw.get("fundingResolverDisabledReason", ""),
                    "fundingResolverAuthError": raw.get("fundingResolverAuthError", ""),
                    "fundingResolverUnavailableReason": raw.get("fundingResolverUnavailableReason", ""),
                    "fundingResolverFunctionalStatus": raw.get("fundingResolverFunctionalStatus", ""),
                    "fundingResolverEndpointLabel": raw.get("fundingResolverEndpointLabel", ""),
                    "fundingResolverLastError": raw.get("fundingResolverLastError", ""),
                    "fundingTraceAttemptedCount": raw.get("fundingTraceAttemptedCount", ""),
                    "fundingTraceSucceededCount": raw.get("fundingTraceSucceededCount", ""),
                    "fundingTraceFailedCount": raw.get("fundingTraceFailedCount", ""),
                    "fundingTraceSkippedCount": raw.get("fundingTraceSkippedCount", ""),
                    "fundingTraceCoverageRatio": raw.get("fundingTraceCoverageRatio", ""),
                    "fundingTraceEndpointPoolSize": raw.get("fundingTraceEndpointPoolSize", ""),
                    "fundingTraceEndpointAvailableCount": raw.get("fundingTraceEndpointAvailableCount", ""),
                    "fundingTraceEndpointCooldownCount": raw.get("fundingTraceEndpointCooldownCount", ""),
                    "fundingTraceEndpointFailureDistribution": raw.get("fundingTraceEndpointFailureDistribution", ""),
                    "fundingTraceRateLimitedCount": raw.get("fundingTraceRateLimitedCount", ""),
                    "fundingTraceRetryCount": raw.get("fundingTraceRetryCount", ""),
                    "fundingTraceFallbackEndpointCount": raw.get("fundingTraceFallbackEndpointCount", ""),
                    "fundingTraceLogChunksAttempted": raw.get("fundingTraceLogChunksAttempted", ""),
                    "fundingTraceLogChunksSucceeded": raw.get("fundingTraceLogChunksSucceeded", ""),
                    "fundingTraceLogChunksFailed": raw.get("fundingTraceLogChunksFailed", ""),
                    "fundingTraceLogChunksRateLimited": raw.get("fundingTraceLogChunksRateLimited", ""),
                    "fundingTraceCacheHitCount": raw.get("fundingTraceCacheHitCount", ""),
                    "fundingTraceCacheMissCount": raw.get("fundingTraceCacheMissCount", ""),
                    "fundingTracePersistentCacheEnabled": raw.get("fundingTracePersistentCacheEnabled", ""),
                    "fundingTracePersistentCacheHitCount": raw.get("fundingTracePersistentCacheHitCount", ""),
                    "fundingTracePersistentCacheMissCount": raw.get("fundingTracePersistentCacheMissCount", ""),
                    "fundingTracePersistentCacheWriteCount": raw.get("fundingTracePersistentCacheWriteCount", ""),
                    "fundingTracePersistentCacheExpiredCount": raw.get("fundingTracePersistentCacheExpiredCount", ""),
                    "fundingTracePersistentCacheFailureCooldownCount": raw.get("fundingTracePersistentCacheFailureCooldownCount", ""),
                    "fundingTracePersistentCacheSchemaVersion": raw.get("fundingTracePersistentCacheSchemaVersion", ""),
                    "fundingTraceFromPersistentCache": raw.get("fundingTraceFromPersistentCache", ""),
                    "fundingTracePersistentCacheStatus": raw.get("fundingTracePersistentCacheStatus", ""),
                    "fundingProxyTightCohort": raw.get("funding_proxy_tight_cohort_flag", ""),
                    "sharedFundingSourceWalletCount": raw.get("shared_funding_source_wallet_count", ""),
                    "repricingSourceQuality": raw.get("repricing_source_quality") or raw.get("repricingSourceQuality", ""),
                    "repricingSourceQualityReasons": raw.get("repricing_source_quality_reasons") or raw.get("repricingSourceQualityReasons", ""),
                    "tradeState": raw.get("trade_state", "Unavailable"),
                    "tradeDomain": raw.get("trade_domain", "Other"),
                    "walletReviewDomainProfile": raw.get("wallet_review_domain_profile", ""),
                    "walletReviewDomainCount": raw.get("wallet_review_domain_count", ""),
                    "walletSportsHistoryTradeCount": raw.get("wallet_sports_history_trade_count", ""),
                    "walletCrossDomainPublicBettorFlag": raw.get("wallet_cross_domain_public_bettor_flag", ""),
                    "walletCrossDomainPublicBettorReason": raw.get("wallet_cross_domain_public_bettor_reason", ""),
                    "caseType": case.case_type,
                    "summary": _trade_summary(case, later_won, flags, reducers),
                    "rawMetrics": dict(raw),
                }
            )
        return payloads

    def _ranked_trade_rows(self, trade_payloads: list[dict[str, object]]) -> list[dict[str, object]]:
        ranked = list(trade_payloads)
        ranked.sort(key=_event_trade_sort_key, reverse=True)
        return ranked

    def _build_wallet_rankings(
        self,
        trade_payloads: list[dict[str, object]],
        related_market_rows: list[dict[str, object]],
        *,
        analysis_scope: str,
        sibling_market_activity: dict[str, dict[str, int]],
    ) -> list[dict[str, object]]:
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for item in trade_payloads:
            grouped[item["wallet"]].append(item)

        related_by_wallet: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in related_market_rows:
            related_by_wallet[row["wallet"]].append(row)

        rows: list[dict[str, object]] = []
        for wallet, items in grouped.items():
            sorted_items = sorted(items, key=lambda item: item["eventForensicScore"], reverse=True)
            top_scores = [item["eventForensicScore"] for item in sorted_items[:3]]
            average_top = sum(top_scores) / max(1, len(top_scores))
            suspicious_count = sum(1 for item in items if item["eventForensicScore"] >= 40)
            later_wins = sum(1 for item in items if item["laterWon"])
            opening_entries = sum(1 for item in items if item["openingExposure"])
            resolved_opening_entries = sum(1 for item in items if item["openingExposure"] and item.get("outcomeKnown"))
            unique_event_markets = len(
                {
                    str(item.get("conditionId") or item.get("selectedConditionId") or item.get("marketSlug") or "")
                    for item in items
                    if item.get("conditionId") or item.get("selectedConditionId") or item.get("marketSlug")
                }
            )
            event_trade_density = len(items) / max(1, unique_event_markets)
            wallet_total_predictions = _max_payload_int(
                items,
                "walletTotalPredictions",
                "wallet_total_predictions",
                "wallet_public_stats_trades",
            )
            wallet_loaded_history_trade_count = _max_payload_int(
                items,
                "walletLoadedHistoryTradeCount",
                "wallet_loaded_history_trade_count",
                "wallet_recent_trade_count",
                "recent_trade_count",
            )
            wallet_loaded_unique_market_count = _max_payload_int(
                items,
                "walletLoadedUniqueMarketCount",
                "wallet_unique_market_count",
                "unique_market_count",
                "market_breadth",
            )
            wallet_profile_views = _first_payload_value(items, "walletProfileViews", "wallet_profile_views")
            wallet_joined_at = str(_first_payload_value(items, "walletJoinedAt", "wallet_joined_at") or "")
            wallet_profile_age_days = _max_payload_int(items, "walletProfileAgeDays", "wallet_profile_age_days")
            related_rows = related_by_wallet.get(wallet, [])
            sibling_activity = sibling_market_activity.get(
                wallet,
                {"otherEventMarketTrades": 0, "siblingMarketActivityCount": 0},
            )
            sibling_context_trades = int(sibling_activity.get("otherEventMarketTrades") or 0)
            public_power_user = _wallet_public_power_user_flag(
                wallet_total_predictions=wallet_total_predictions,
                wallet_loaded_history_trade_count=wallet_loaded_history_trade_count,
                event_trade_count=len(items),
                wallet_loaded_unique_market_count=wallet_loaded_unique_market_count,
                sibling_context_trades=sibling_context_trades,
            )
            high_volume_event_user = _wallet_high_volume_event_user_flag(
                event_trade_count=len(items),
                suspicious_trade_count=suspicious_count,
                winning_opening_entries=later_wins,
                sibling_context_trades=sibling_context_trades,
            )
            event_saturation = _wallet_event_saturation_flag(
                event_trade_count=len(items),
                opening_entries=opening_entries,
                winning_opening_entries=later_wins,
            )
            shared_funder = any(item["rawMetrics"].get("shared_funding_source_flag") == "Yes" for item in items)
            specialist = any(item["rawMetrics"].get("specialist_explained_flag") == "Yes" for item in items)
            bot_like = any(item["rawMetrics"].get("low_analyst_value_flag") == "Yes" for item in items)
            zombie = any(item["rawMetrics"].get("formal_win_rate_may_be_overstated") == "Yes" for item in items)
            cross_domain_public_bettor = any(
                item["rawMetrics"].get("wallet_cross_domain_public_bettor_flag") == "Yes" for item in items
            )
            cross_domain_public_bettor_reason = _first_text(
                item["rawMetrics"].get("wallet_cross_domain_public_bettor_reason")
                for item in items
            )
            wallet_review_domain_profile = _first_text(
                item["rawMetrics"].get("wallet_review_domain_profile") for item in items
            )
            dormant_reactivation = any(
                item["rawMetrics"].get("reactivated_after_dormancy_flag") == "Yes" for item in items
            )
            dormant_after_win = any(
                item["laterWon"] and item["rawMetrics"].get("post_trade_dormancy_flag") == "Yes" for item in items
            )
            event_family_repeat = any(
                item["rawMetrics"].get("event_family_repeat_flag") == "Yes" for item in items
            )
            split_wallet = any(
                item["rawMetrics"].get("split_wallet_pattern_flag") == "Yes" for item in items
            )
            poor_history = any(_poor_wallet_history(item["rawMetrics"]) for item in items)
            independent_proof = any(
                _has_independent_forensic_proof(
                    item["rawMetrics"],
                    price=float(item.get("price") or 0.0),
                    winner_rank=item.get("winnerRank"),
                )
                for item in items
            )
            independent_hard_evidence = any(
                _has_independent_hard_evidence(
                    item["rawMetrics"],
                    price=float(item.get("price") or 0.0),
                    winner_rank=item.get("winnerRank"),
                )
                for item in items
            )
            hard_evidence_sources, evidence_source_flags, hard_evidence_source_details = (
                _wallet_hard_evidence_attribution(items)
            )
            hard_evidence_trade_ids = _dedupe_labels(
                [
                    trade_id
                    for item in items
                    for trade_id in _text_values(item.get("hardEvidenceTradeIds"))
                ]
            )
            hard_evidence_wallet_ids = _dedupe_labels(
                [
                    wallet_id
                    for item in items
                    for wallet_id in _text_values(item.get("hardEvidenceWalletIds"))
                ]
            )
            hard_evidence_strength = _wallet_hard_evidence_strength(hard_evidence_sources, items)
            hard_evidence_review_tier = HARD_EVIDENCE_REVIEW_TIER if hard_evidence_sources else ""
            hard_evidence_primary_reason = _first_text(
                item.get("hardEvidencePrimaryReason")
                for item in items
                if item.get("hardEvidenceReviewTier") == HARD_EVIDENCE_REVIEW_TIER
            )
            candidate_admission_reasons = _dedupe_labels(
                [str(item.get("candidateAdmissionReason") or "") for item in items]
            )
            candidate_admission_stages = _dedupe_labels(
                [str(item.get("candidateAdmissionStage") or "") for item in items]
            )
            candidate_admission_sources = _dedupe_labels(
                [
                    source
                    for item in items
                    for source in _text_values(item.get("candidateAdmissionEvidenceSources"))
                ]
            )
            grouped_candidate_ids = _dedupe_labels(
                [str(item.get("groupedCandidateId") or "") for item in items]
            )
            grouped_candidate_grades = _dedupe_labels(
                [str(item.get("groupedCandidateFundingGrade") or "") for item in items]
            )
            grouped_candidate_proxy_only = any(item.get("groupedCandidateProxyOnly") == "Yes" for item in items)
            grouped_candidate_strict_funding = any(item.get("groupedCandidateStrictFunding") == "Yes" for item in items)
            repricing_source_quality, repricing_source_quality_reasons = _wallet_repricing_source_quality(items)
            suspicious_funding_quality, suspicious_funding_quality_reasons, suspicious_funding_eligible = (
                _wallet_suspicious_funding_quality(items)
            )
            strong_risk_gate_passed = any(item.get("strongRiskGatePassed") == "Yes" for item in items)
            strong_risk_gate_types = _dedupe_labels(
                [
                    str(item.get("strongRiskGateType") or "")
                    for item in items
                    if str(item.get("strongRiskGateType") or "") not in {"", "not_strong_risk"}
                ]
            )
            strong_risk_gate_sources = _dedupe_labels(
                [
                    source
                    for item in items
                    for source in _text_values(item.get("strongRiskGateEvidenceSources"))
                ]
            )
            strong_risk_timing_sources = _dedupe_labels(
                [
                    source
                    for item in items
                    for source in _text_values(item.get("strongRiskTimingProofSources"))
                ]
            )
            strong_risk_structural_sources = _dedupe_labels(
                [
                    source
                    for item in items
                    for source in _text_values(item.get("strongRiskStructuralSources"))
                ]
            )
            strong_risk_suppressor_conflicts = _dedupe_labels(
                [
                    reason
                    for item in items
                    for reason in _text_values(item.get("strongRiskSuppressorConflictReasons"))
                ]
            )
            strong_risk_composition_classes = _dedupe_labels(
                [
                    str(item.get("strongRiskCompositionClass") or "")
                    for item in items
                    if str(item.get("strongRiskCompositionClass") or "") not in {"", "not_strong_risk"}
                ]
            )
            high_volume_context_gate = _wallet_high_volume_context_gate(
                public_power_user=public_power_user,
                high_volume_event_user=high_volume_event_user,
                event_saturation=event_saturation,
                wallet_total_predictions=wallet_total_predictions,
                wallet_loaded_history_trade_count=wallet_loaded_history_trade_count,
                event_trade_count=len(items),
                suspicious_trade_count=suspicious_count,
                winning_opening_entries=later_wins,
                sibling_context_trades=sibling_context_trades,
            )
            score = average_top
            score += min(suspicious_count * 5, 15)
            if analysis_scope != "market":
                score += min(len(related_rows) * 3, 12)
            if shared_funder:
                score += 8
            if split_wallet:
                score += 8
            if event_family_repeat:
                score += 6
            if dormant_reactivation:
                score += 4
            if dormant_after_win:
                score += 5
            if later_wins >= 2:
                score += 6
            if specialist:
                score -= 10
            if bot_like:
                score -= 12
            if zombie:
                score -= 4
            if cross_domain_public_bettor and not independent_hard_evidence:
                score -= 12
            if poor_history and not independent_proof:
                score -= 25
            elif poor_history:
                score -= 8
            public_power_user_reducer_applied = False
            public_power_user_note = ""
            if high_volume_context_gate and independent_hard_evidence:
                public_power_user_note = (
                    "High-volume public-user pattern present, but independent hard evidence keeps it eligible for primary review."
                )
            elif high_volume_context_gate:
                score_cap = 100
                reducer_parts: list[str] = []
                if public_power_user:
                    score -= 25
                    score_cap = min(score_cap, 55)
                    public_power_user_reducer_applied = True
                    reducer_parts.append("public power-user profile")
                if high_volume_event_user:
                    score -= 20
                    score_cap = min(score_cap, 50)
                    public_power_user_reducer_applied = True
                    reducer_parts.append("high event-trade volume")
                if event_saturation:
                    score_cap = min(score_cap, 40)
                    reducer_parts.append("event-saturation pattern")
                if suspicious_count >= HIGH_VOLUME_NOTABLE_TRADE_MIN:
                    score_cap = min(score_cap, 40)
                    reducer_parts.append("many notable event trades")
                if later_wins >= HIGH_VOLUME_WINNING_OPENING_MIN:
                    score_cap = min(score_cap, 40)
                    reducer_parts.append("many winning opening entries")
                if sibling_context_trades >= HIGH_VOLUME_SIBLING_CONTEXT_MIN:
                    score_cap = min(score_cap, 40)
                    reducer_parts.append("heavy sibling-market context activity")
                if public_power_user and event_saturation:
                    score_cap = min(score_cap, 35)
                score_cap = min(score_cap, 40)
                score = min(score, score_cap)
                public_power_user_note = (
                    "High-volume public participant reducer applied for "
                    f"{', '.join(reducer_parts)}. Many trades or many winning entries are treated as context "
                    "unless independent hard evidence is present."
                )
            score = max(0, min(100, round(score)))
            top_item = sorted_items[0]
            if resolved_opening_entries == opening_entries:
                event_result = f"{later_wins} winning opening entries out of {opening_entries}"
            elif resolved_opening_entries:
                event_result = (
                    f"{later_wins} winning opening entries out of {resolved_opening_entries} resolved opening entries; "
                    f"{opening_entries - resolved_opening_entries} still unresolved"
                )
            else:
                event_result = f"{opening_entries} opening entries; final outcomes not known"
            wallet_quality_gate = "secondary_only" if poor_history and not independent_proof else "primary_allowed"
            wallet_quality_note = (
                "Very weak economic history; kept out of primary wallet ranking unless independent evidence exists."
                if wallet_quality_gate == "secondary_only"
                else "Weak economic history tempers this wallet score."
                if poor_history
                else "No weak-history gate triggered."
            )
            wallet_primary_review_status = _wallet_primary_review_status(
                public_power_user=public_power_user,
                high_volume_event_user=high_volume_event_user,
                event_saturation=event_saturation,
                high_volume_context_gate=high_volume_context_gate,
                independent_hard_evidence=independent_hard_evidence,
                cross_domain_public_bettor=cross_domain_public_bettor,
            )
            interpretation_class = _wallet_interpretation_class(
                public_power_user=public_power_user,
                high_volume_event_user=high_volume_event_user,
                event_saturation=event_saturation,
                high_volume_context_gate=high_volume_context_gate,
                independent_hard_evidence=independent_hard_evidence,
                cross_domain_public_bettor=cross_domain_public_bettor,
                shared_funder=shared_funder,
                split_wallet=split_wallet,
                bot_like=bot_like,
                specialist=specialist,
                poor_history=poor_history,
            )
            statistical_prior_label = str(
                top_item["rawMetrics"].get("wallet_statistical_prior_label") or "insufficient_sample"
            )
            statistical_prior_note = str(top_item["rawMetrics"].get("wallet_statistical_prior_note") or "")
            rows.append(
                {
                    "wallet": wallet,
                    "walletShort": _short_wallet(wallet),
                    "profileUrl": top_item["profileUrl"],
                    "username": next((item["username"] for item in sorted_items if item["username"] != "Not available"), "Not available"),
                    "walletScore": score,
                    "insiderStyleWalletScore": _insider_style_wallet_score(
                        score,
                        public_power_user=public_power_user,
                        high_volume_event_user=high_volume_event_user,
                        event_saturation=event_saturation,
                        high_volume_context_gate=high_volume_context_gate,
                        independent_hard_evidence=independent_hard_evidence,
                        cross_domain_public_bettor=cross_domain_public_bettor,
                    ),
                    "analysisScope": analysis_scope,
                    "selectedConditionId": top_item.get("selectedConditionId"),
                    "selectedMarketSlug": top_item.get("selectedMarketSlug"),
                    "selectedMarketTitle": top_item.get("selectedMarketTitle"),
                    "parentEventSlug": top_item.get("parentEventSlug"),
                    "suspiciousTradeCount": suspicious_count,
                    "eventTradeCount": len(items),
                    "walletTotalPredictions": wallet_total_predictions or "",
                    "walletProfileViews": wallet_profile_views or "",
                    "walletJoinedAt": wallet_joined_at,
                    "walletProfileAgeDays": wallet_profile_age_days or "",
                    "walletLoadedEventTradeCount": len(items),
                    "walletNotableTradeCount": suspicious_count,
                    "walletOpeningEntryCount": opening_entries,
                    "walletWinningOpeningEntryCount": later_wins,
                    "walletEventTradeDensity": f"{event_trade_density:.2f}",
                    "walletUniqueEventMarketsTraded": unique_event_markets,
                    "walletLoadedHistoryTradeCount": wallet_loaded_history_trade_count or "",
                    "walletLoadedUniqueMarketCount": wallet_loaded_unique_market_count or "",
                    "walletPublicPowerUserFlag": public_power_user,
                    "walletHighVolumeEventUserFlag": high_volume_event_user,
                    "walletEventSaturationFlag": event_saturation,
                    "independentHardEvidenceFlag": independent_hard_evidence,
                    "walletHardEvidenceSources": hard_evidence_sources,
                    "walletEvidenceSourceFlags": evidence_source_flags,
                    "walletHardEvidenceSourceDetails": hard_evidence_source_details,
                    "hardEvidenceSources": hard_evidence_sources,
                    "hardEvidenceStrength": hard_evidence_strength,
                    "hardEvidencePrimaryReason": hard_evidence_primary_reason,
                    "hardEvidenceTradeIds": hard_evidence_trade_ids,
                    "hardEvidenceWalletIds": hard_evidence_wallet_ids,
                    "hardEvidenceReviewTier": hard_evidence_review_tier,
                    "evidenceAvailabilityStage": _first_text(
                        item.get("evidenceAvailabilityStage") for item in items
                    ),
                    "strongRiskGatePassed": "Yes" if strong_risk_gate_passed else "No",
                    "strongRiskGateType": strong_risk_gate_types,
                    "strongRiskGateReasons": _dedupe_labels(
                        [
                            reason
                            for item in items
                            for reason in _text_values(item.get("strongRiskGateReasons"))
                        ]
                    ),
                    "strongRiskGateEvidenceSources": strong_risk_gate_sources,
                    "strongRiskTimingProofSources": strong_risk_timing_sources,
                    "strongRiskStructuralSources": strong_risk_structural_sources,
                    "strongRiskSupportingBoosters": _dedupe_labels(
                        [
                            source
                            for item in items
                            for source in _text_values(item.get("strongRiskSupportingBoosters"))
                        ]
                    ),
                    "strongRiskStructuralConcernCount": _first_text(
                        item.get("strongRiskStructuralConcernCount") for item in items
                    ),
                    "strongRiskTimingProofCount": _first_text(
                        item.get("strongRiskTimingProofCount") for item in items
                    ),
                    "strongRiskOpeningExposureConfirmed": _first_text(
                        item.get("strongRiskOpeningExposureConfirmed") for item in items
                    ),
                    "strongRiskConfidenceScore": _first_text(
                        item.get("strongRiskConfidenceScore") for item in items
                    ),
                    "strongRiskSuspicionScore": _first_text(
                        item.get("strongRiskSuspicionScore") for item in items
                    ),
                    "strongRiskSuppressorConflict": "Yes" if strong_risk_suppressor_conflicts else "No",
                    "strongRiskSuppressorConflictReasons": strong_risk_suppressor_conflicts,
                    "strongRiskHasHardEvidenceSources": "Yes" if hard_evidence_sources else "No",
                    "strongRiskNoHardEvidenceExplanation": _first_text(
                        item.get("strongRiskNoHardEvidenceExplanation") for item in items
                    ),
                    "strongRiskCompositionClass": strong_risk_composition_classes,
                    **_wallet_strong_risk_extra_values(items),
                    "candidateAdmissionReason": candidate_admission_reasons,
                    "candidateAdmissionStage": candidate_admission_stages,
                    "candidateAdmissionEvidenceSources": candidate_admission_sources,
                    "candidateAdmissionFloorNotional": _first_text(
                        item.get("candidateAdmissionFloorNotional") for item in items
                    ),
                    "groupedCandidateId": grouped_candidate_ids,
                    "groupedCandidateAggregateNotional": _first_text(
                        item.get("groupedCandidateAggregateNotional") for item in items
                    ),
                    "groupedCandidateWalletCount": _first_text(
                        item.get("groupedCandidateWalletCount") for item in items
                    ),
                    "groupedCandidateStrictFunding": "Yes" if grouped_candidate_strict_funding else "No",
                    "groupedCandidateProxyOnly": "Yes" if grouped_candidate_proxy_only else "No",
                    "groupedCandidateFundingGrade": grouped_candidate_grades,
                    "groupedCandidateTimeSpanMinutes": _first_text(
                        item.get("groupedCandidateTimeSpanMinutes") for item in items
                    ),
                    "groupedCandidatePriceBand": _first_text(
                        item.get("groupedCandidatePriceBand") for item in items
                    ),
                    "candidateAdmissionValidatedOpeningExposure": _first_text(
                        item.get("candidateAdmissionValidatedOpeningExposure") for item in items
                    ),
                    "candidateAdmissionRejectedReason": _first_text(
                        item.get("candidateAdmissionRejectedReason") for item in items
                    ),
                    "repricingSourceQuality": repricing_source_quality,
                    "repricingSourceQualityReasons": repricing_source_quality_reasons,
                    "fundingEvidenceGrade": _first_payload_value(items, "fundingEvidenceGrade", "funding_evidence_grade"),
                    "suspiciousFundingQuality": suspicious_funding_quality,
                    "suspiciousFundingQualityReasons": suspicious_funding_quality_reasons,
                    "suspiciousFundingHardEvidenceEligible": suspicious_funding_eligible,
                    "suspiciousFundingTraceSucceeded": _first_payload_value(
                        items,
                        "suspiciousFundingTraceSucceeded",
                        "suspiciousFundingTraceSucceeded",
                    ),
                    "suspiciousFundingTraceDepth": _first_payload_value(
                        items,
                        "suspiciousFundingTraceDepth",
                        "suspiciousFundingTraceDepth",
                    ),
                    "suspiciousFundingSourceCategory": _first_payload_value(
                        items,
                        "suspiciousFundingSourceCategory",
                        "suspiciousFundingSourceCategory",
                    ),
                    "suspiciousFundingOriginCategory": _first_payload_value(
                        items,
                        "suspiciousFundingOriginCategory",
                        "suspiciousFundingOriginCategory",
                    ),
                    "suspiciousFundingMinutesBeforeTrade": _first_payload_value(
                        items,
                        "suspiciousFundingMinutesBeforeTrade",
                        "suspiciousFundingMinutesBeforeTrade",
                    ),
                    "suspiciousFundingAmountUsd": _first_payload_value(
                        items,
                        "suspiciousFundingAmountUsd",
                        "suspiciousFundingAmountUsd",
                    ),
                    "suspiciousFundingTradeNotionalUsd": _first_payload_value(
                        items,
                        "suspiciousFundingTradeNotionalUsd",
                        "suspiciousFundingTradeNotionalUsd",
                    ),
                    "suspiciousFundingAmountToTradeRatio": _first_payload_value(
                        items,
                        "suspiciousFundingAmountToTradeRatio",
                        "suspiciousFundingAmountToTradeRatio",
                    ),
                    "suspiciousFundingRecentEnough": _first_payload_value(
                        items,
                        "suspiciousFundingRecentEnough",
                        "suspiciousFundingRecentEnough",
                    ),
                    "suspiciousFundingAmountAligned": _first_payload_value(
                        items,
                        "suspiciousFundingAmountAligned",
                        "suspiciousFundingAmountAligned",
                    ),
                    "suspiciousFundingIndependentSupport": _first_payload_value(
                        items,
                        "suspiciousFundingIndependentSupport",
                        "suspiciousFundingIndependentSupport",
                    ),
                    "suspiciousFundingIndependentSupportSources": _first_payload_value(
                        items,
                        "suspiciousFundingIndependentSupportSources",
                        "suspiciousFundingIndependentSupportSources",
                    ),
                    "suspiciousFundingSuppressorConflict": _first_payload_value(
                        items,
                        "suspiciousFundingSuppressorConflict",
                        "suspiciousFundingSuppressorConflict",
                    ),
                    "suspiciousFundingSuppressorConflictReasons": _first_payload_value(
                        items,
                        "suspiciousFundingSuppressorConflictReasons",
                        "suspiciousFundingSuppressorConflictReasons",
                    ),
                    "walletPublicWhaleOrPowerUserLabel": _wallet_public_power_user_label(
                        public_power_user=public_power_user,
                        high_volume_event_user=high_volume_event_user,
                        event_saturation=event_saturation,
                    ),
                    "walletPublicPowerUserReducerApplied": public_power_user_reducer_applied,
                    "walletPublicPowerUserStatus": _public_power_user_status(
                        public_power_user=public_power_user,
                        independent_hard_evidence=independent_hard_evidence,
                        reducer_applied=public_power_user_reducer_applied,
                    ),
                    "walletHighVolumeEventStatus": _high_volume_event_status(
                        high_volume_event_user=high_volume_event_user,
                        independent_hard_evidence=independent_hard_evidence,
                        reducer_applied=public_power_user_reducer_applied,
                    ),
                    "walletEventSaturationStatus": _event_saturation_status(
                        event_saturation=event_saturation,
                        independent_hard_evidence=independent_hard_evidence,
                    ),
                    "walletPrimaryReviewStatus": wallet_primary_review_status,
                    "walletPublicPowerUserNote": public_power_user_note,
                    "walletCrossDomainPublicBettorFlag": cross_domain_public_bettor,
                    "walletCrossDomainPublicBettorStatus": _cross_domain_public_bettor_status(
                        cross_domain_public_bettor=cross_domain_public_bettor,
                        independent_hard_evidence=independent_hard_evidence,
                    ),
                    "walletCrossDomainPublicBettorReason": cross_domain_public_bettor_reason,
                    "walletReviewDomainProfile": wallet_review_domain_profile,
                    "caseInterpretationClass": interpretation_class,
                    "topTradeScores": top_scores,
                    "relatedMarketTradeCount": len(related_rows),
                    "otherEventMarketTrades": sibling_activity["otherEventMarketTrades"],
                    "siblingMarketActivityCount": sibling_activity["siblingMarketActivityCount"],
                    "eventResult": event_result,
                    "resolvedOpeningEntryCount": resolved_opening_entries,
                    "openingEntryCount": opening_entries,
                    "outcomeContextAvailable": bool(resolved_opening_entries),
                    "fundingFlags": "Shared funder" if shared_funder else "No shared-funder signal",
                    "specialistStatus": "Specialist-like" if specialist else "Not clearly specialist",
                    "botStatus": "Bot-like" if bot_like else "Not clearly bot-like",
                    "zombieStatus": "Zombie distortion risk" if zombie else "No zombie distortion signal",
                    "walletQualityGate": wallet_quality_gate,
                    "walletQualityStatus": "Weak economic history" if poor_history else "No weak-history gate",
                    "walletQualityNote": wallet_quality_note,
                    "walletStatisticalPriorLabel": statistical_prior_label,
                    "walletStatisticalPValue": top_item["rawMetrics"].get("wallet_statistical_p_value", ""),
                    "walletStatisticalLogScore": top_item["rawMetrics"].get("wallet_statistical_log_score", ""),
                    "walletResolvedSampleSize": top_item["rawMetrics"].get("wallet_resolved_sample_size", ""),
                    "walletResolvedWinRate": top_item["rawMetrics"].get("wallet_resolved_win_rate", ""),
                    "walletStatisticalPriorNote": statistical_prior_note,
                    "primaryEvidenceStatus": "Independent evidence" if independent_proof else "Timing-only or weak evidence",
                    "summary": _wallet_summary(
                        analysis_scope=analysis_scope,
                        wallet_score=score,
                        suspicious_trade_count=suspicious_count,
                        related_market_trade_count=len(related_rows),
                        other_event_market_trades=sibling_activity["otherEventMarketTrades"],
                        sibling_market_activity_count=sibling_activity["siblingMarketActivityCount"],
                        later_wins=later_wins,
                        shared_funder=shared_funder,
                        split_wallet=split_wallet,
                        event_family_repeat=event_family_repeat,
                        dormant_reactivation=dormant_reactivation,
                        dormant_after_win=dormant_after_win,
                        specialist=specialist,
                        bot_like=bot_like,
                        opening_entries=opening_entries,
                        resolved_opening_entries=resolved_opening_entries,
                        wallet_quality_note=wallet_quality_note if poor_history else "",
                        public_power_user_note=public_power_user_note,
                        cross_domain_public_bettor_reason=(
                            cross_domain_public_bettor_reason
                            if cross_domain_public_bettor and not independent_hard_evidence
                            else ""
                        ),
                        wallet_statistical_prior_label=statistical_prior_label,
                        wallet_statistical_prior_note=statistical_prior_note,
                    ),
                    "tradeIds": [item["id"] for item in sorted_items],
                }
            )
        rows.sort(
            key=lambda item: (
                1 if item.get("hardEvidenceReviewTier") == HARD_EVIDENCE_REVIEW_TIER else 0,
                item["insiderStyleWalletScore"],
                item["walletScore"],
                item["suspiciousTradeCount"],
            ),
            reverse=True,
        )
        return rows

    def _build_wallet_clusters(
        self,
        trade_payloads: list[dict[str, object]],
        suspicious_wallets: list[dict[str, object]],
        *,
        analysis_scope: str,
        sibling_market_activity: dict[str, dict[str, int]],
        scope_context: AnalysisScopeContext,
    ) -> list[dict[str, object]]:
        suspicious_wallet_lookup = {
            row["wallet"]
            for row in suspicious_wallets
            if row["walletScore"] >= 40 or row.get("hardEvidenceReviewTier") == HARD_EVIDENCE_REVIEW_TIER
        }
        funding_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
        for item in trade_payloads:
            funding_key = str(item.get("fundingKey") or "")
            if (
                funding_key
                and item["wallet"] in suspicious_wallet_lookup
                and (
                    item["eventForensicScore"] >= 40
                    or item.get("hardEvidenceReviewTier") == HARD_EVIDENCE_REVIEW_TIER
                )
            ):
                funding_groups[funding_key].append(item)

        rows: list[dict[str, object]] = []
        for index, items in enumerate(funding_groups.values(), start=1):
            wallets = sorted({item["wallet"] for item in items})
            if len(wallets) < 2:
                continue
            sibling_trade_total = sum(
                sibling_market_activity.get(wallet, {}).get("otherEventMarketTrades", 0)
                for wallet in wallets
            )
            sibling_wallet_count = sum(
                1
                for wallet in wallets
                if sibling_market_activity.get(wallet, {}).get("otherEventMarketTrades", 0) > 0
            )
            score = min(100, 45 + len(wallets) * 8 + sum(item["eventForensicScore"] >= 55 for item in items) * 3)
            cluster_hard_sources = _dedupe_labels(
                [source for item in items for source in _text_values(item.get("hardEvidenceSources"))]
            )
            rows.append(
                {
                    "id": f"funding-{index}",
                    "analysisScope": analysis_scope,
                    "selectedConditionId": scope_context.selected_condition_id,
                    "selectedMarketSlug": scope_context.selected_market_slug,
                    "selectedMarketTitle": scope_context.selected_market_title,
                    "parentEventSlug": items[0].get("parentEventSlug"),
                    "connectionType": "Shared direct funder",
                    "wallets": wallets,
                    "walletCount": len(wallets),
                    "sameFunder": True,
                    "sameSideTimingPattern": any(
                        item["rawMetrics"].get("coordinated_cluster_signal") == "Yes" for item in items
                    ),
                    "relatedMarketOverlap": sum(item["relatedMarketTrades"] for item in items),
                    "otherEventMarketTrades": sibling_trade_total,
                    "siblingMarketWalletCount": sibling_wallet_count,
                    "clusterScore": score,
                    "hardEvidenceSources": cluster_hard_sources,
                    "hardEvidenceStrength": "Strong" if cluster_hard_sources else "None",
                    "hardEvidencePrimaryReason": _first_text(
                        item.get("hardEvidencePrimaryReason") for item in items
                    ),
                    "hardEvidenceTradeIds": _dedupe_labels(
                        [trade_id for item in items for trade_id in _text_values(item.get("hardEvidenceTradeIds"))]
                    ),
                    "hardEvidenceWalletIds": _dedupe_labels(
                        [wallet_id for item in items for wallet_id in _text_values(item.get("hardEvidenceWalletIds"))]
                    ),
                    "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER if cluster_hard_sources else "",
                    "evidenceAvailabilityStage": _first_text(
                        item.get("evidenceAvailabilityStage") for item in items
                    ),
                    "summary": _cluster_summary(
                        analysis_scope=analysis_scope,
                        base_summary=(
                        "Shared upstream funding before event entries makes this a linked-funding lead."
                        ),
                        sibling_wallet_count=sibling_wallet_count,
                    ),
                    "tradeIds": [item["id"] for item in items],
                }
            )

        timing_groups = _timing_clusters(trade_payloads, suspicious_wallet_lookup)
        for index, group in enumerate(timing_groups, start=1):
            wallets = sorted({item["wallet"] for item in group})
            sibling_trade_total = sum(
                sibling_market_activity.get(wallet, {}).get("otherEventMarketTrades", 0)
                for wallet in wallets
            )
            sibling_wallet_count = sum(
                1
                for wallet in wallets
                if sibling_market_activity.get(wallet, {}).get("otherEventMarketTrades", 0) > 0
            )
            score = min(100, 35 + len(wallets) * 7 + sum(item["eventForensicScore"] >= 55 for item in group) * 4)
            cluster_hard_sources = _dedupe_labels(
                [source for item in group for source in _text_values(item.get("hardEvidenceSources"))]
            )
            rows.append(
                {
                    "id": f"timing-{index}",
                    "analysisScope": analysis_scope,
                    "selectedConditionId": scope_context.selected_condition_id,
                    "selectedMarketSlug": scope_context.selected_market_slug,
                    "selectedMarketTitle": scope_context.selected_market_title,
                    "parentEventSlug": group[0].get("parentEventSlug"),
                    "connectionType": "Synchronized same-side entry",
                    "wallets": wallets,
                    "walletCount": len(wallets),
                    "sameFunder": any(item["rawMetrics"].get("shared_funding_source_flag") == "Yes" for item in group),
                    "sameSideTimingPattern": True,
                    "relatedMarketOverlap": sum(item["relatedMarketTrades"] for item in group),
                    "otherEventMarketTrades": sibling_trade_total,
                    "siblingMarketWalletCount": sibling_wallet_count,
                    "clusterScore": score,
                    "hardEvidenceSources": cluster_hard_sources,
                    "hardEvidenceStrength": "Strong" if cluster_hard_sources else "None",
                    "hardEvidencePrimaryReason": _first_text(
                        item.get("hardEvidencePrimaryReason") for item in group
                    ),
                    "hardEvidenceTradeIds": _dedupe_labels(
                        [trade_id for item in group for trade_id in _text_values(item.get("hardEvidenceTradeIds"))]
                    ),
                    "hardEvidenceWalletIds": _dedupe_labels(
                        [wallet_id for item in group for wallet_id in _text_values(item.get("hardEvidenceWalletIds"))]
                    ),
                    "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER if cluster_hard_sources else "",
                    "evidenceAvailabilityStage": _first_text(
                        item.get("evidenceAvailabilityStage") for item in group
                    ),
                    "summary": _cluster_summary(
                        analysis_scope=analysis_scope,
                        base_summary=(
                        "A tight same-side entry window makes this a coordination lead to compare against funding and trade timing."
                        ),
                        sibling_wallet_count=sibling_wallet_count,
                    ),
                    "tradeIds": [item["id"] for item in group],
                }
            )
        rows.sort(
            key=lambda item: (
                1 if item.get("hardEvidenceReviewTier") == HARD_EVIDENCE_REVIEW_TIER else 0,
                item["clusterScore"],
            ),
            reverse=True,
        )
        return rows

    def _build_wallet_graph(
        self,
        resolved: ResolvedEvent,
        suspicious_trades: list[dict[str, object]],
        suspicious_wallets: list[dict[str, object]],
        wallet_clusters: list[dict[str, object]],
        *,
        scope_context: AnalysisScopeContext,
    ) -> dict[str, object]:
        nodes: dict[str, dict[str, object]] = {}
        edges: list[dict[str, object]] = []
        selected_wallets = list(suspicious_wallets[:EVENT_FORENSIC_GRAPH_WALLET_LIMIT])
        if not selected_wallets:
            selected_wallets = _fallback_wallet_rows(suspicious_trades, limit=EVENT_FORENSIC_GRAPH_WALLET_LIMIT)
        selected_wallet_lookup = {item["wallet"] for item in selected_wallets}
        selected_trades = _graph_trade_slice(
            suspicious_trades,
            selected_wallet_lookup,
            limit=EVENT_FORENSIC_GRAPH_TRADE_LIMIT,
        )

        for item in selected_wallets:
            nodes[item["wallet"]] = {
                "id": item["wallet"],
                "label": item["walletShort"],
                "type": "wallet",
                "score": item["walletScore"],
            }

        seen_market_edges: set[tuple[str, str]] = set()
        seen_funder_edges: set[tuple[str, str]] = set()
        for trade in selected_trades:
            market_node_id = f"market:{trade['marketSlug']}"
            nodes.setdefault(
                market_node_id,
                {
                    "id": market_node_id,
                    "label": trade["market"],
                    "type": "market",
                    "score": trade["eventForensicScore"],
                },
            )
            market_edge_key = (trade["wallet"], market_node_id)
            if trade["wallet"] in nodes and market_edge_key not in seen_market_edges:
                seen_market_edges.add(market_edge_key)
                edges.append(
                    {
                        "source": trade["wallet"],
                        "target": market_node_id,
                        "type": "wallet_to_market",
                        "label": f"{trade['orderSide']} {trade['side']}",
                        "score": trade["eventForensicScore"],
                    }
                )
            funding_origin = trade["rawMetrics"].get("funding_origin_address", "")
            if funding_origin:
                funder_id = f"funder:{funding_origin}"
                nodes.setdefault(
                    funder_id,
                    {
                        "id": funder_id,
                        "label": trade["rawMetrics"].get("funding_origin_label", _short_wallet(funding_origin)),
                        "type": "funder",
                        "score": 0,
                    },
                )
                funder_edge_key = (funder_id, trade["wallet"])
                if funder_edge_key not in seen_funder_edges:
                    seen_funder_edges.add(funder_edge_key)
                    edges.append(
                        {
                            "source": funder_id,
                            "target": trade["wallet"],
                            "type": "funder_to_wallet",
                            "label": trade["rawMetrics"].get("funding_velocity_label", "funded"),
                            "score": trade["eventForensicScore"],
                        }
                    )

        seen_wallet_links: set[tuple[str, str, str]] = set()
        for cluster in wallet_clusters[:EVENT_FORENSIC_GRAPH_CLUSTER_LIMIT]:
            if len(cluster["wallets"]) < 2:
                continue
            anchor = cluster["wallets"][0]
            if anchor not in selected_wallet_lookup:
                continue
            for wallet in cluster["wallets"][1:]:
                if wallet not in selected_wallet_lookup:
                    continue
                edge_key = tuple(sorted((anchor, wallet))) + (cluster["connectionType"],)
                if edge_key in seen_wallet_links:
                    continue
                seen_wallet_links.add(edge_key)
                edges.append(
                    {
                        "source": anchor,
                        "target": wallet,
                        "type": "wallet_to_wallet",
                        "label": cluster["connectionType"],
                        "score": cluster["clusterScore"],
                    }
                )
        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "eventSlug": resolved.event_slug,
            "analysisScope": scope_context.analysis_scope,
            "selectedConditionId": scope_context.selected_condition_id,
            "selectedMarketSlug": scope_context.selected_market_slug,
            "selectedMarketTitle": scope_context.selected_market_title,
            "simplified": True,
            "selectedWalletCount": len(selected_wallet_lookup),
            "selectedTradeCount": len(selected_trades),
        }

    def _discover_related_markets(
        self,
        resolved: ResolvedEvent,
        wallet_cache: dict[str, tuple[object, list[Trade], WalletPerformance]],
        *,
        include_related_markets: bool,
    ) -> list[dict[str, object]]:
        if not include_related_markets:
            return []
        rows: list[dict[str, object]] = []
        event_condition_ids = set(resolved.markets)
        for wallet, (_inspection, history, _performance) in wallet_cache.items():
            for trade in history:
                if trade.condition_id in event_condition_ids:
                    continue
                overlap = _token_overlap(resolved.family_tokens, _meaningful_tokens(f"{trade.title} {trade.event_slug}"))
                if overlap < 0.35:
                    continue
                rows.append(
                    {
                        "wallet": wallet,
                        "walletShort": _short_wallet(wallet),
                        "market": trade.title,
                        "marketUrl": f"https://polymarket.com/event/{trade.event_slug or trade.slug}",
                        "eventSlug": trade.event_slug,
                        "marketSlug": trade.slug,
                        "timestamp": trade.timestamp.isoformat(),
                        "displayTime": _display_time(trade.timestamp.isoformat()),
                        "side": trade.outcome,
                        "orderSide": trade.side,
                        "notional": float(trade.notional),
                        "familyOverlap": round(overlap, 2),
                        "summary": (
                            "The same wallet also traded a title-similar market outside the exact event, "
                            "which strengthens the event-family pattern."
                        ),
                    }
                )
        rows.sort(key=lambda item: (item["familyOverlap"], item["notional"]), reverse=True)
        seen: set[tuple[str, str]] = set()
        deduped: list[dict[str, object]] = []
        for row in rows:
            key = (row["wallet"], row["marketSlug"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        return deduped[:120]

    def _build_model_gap_analysis(
        self,
        trade_payloads: list[dict[str, object]],
        suspicious_wallets: list[dict[str, object]],
        wallet_clusters: list[dict[str, object]],
        *,
        analysis_scope: str = "event",
        selected_market_title: str | None = None,
        outcome_context_available: bool = True,
    ) -> dict[str, object]:
        high_forensic = [item for item in trade_payloads if item["eventForensicScore"] >= 55]
        caught = [item for item in high_forensic if item["existingModelCaught"]]
        missed = [item for item in high_forensic if not item["existingModelCaught"]]
        overflagged = [
            item
            for item in trade_payloads
            if item["existingModelCaught"] and item["eventForensicScore"] <= 30
        ]
        heuristics = _suggest_model_improvements(missed, overflagged, suspicious_wallets, wallet_clusters)
        payload = {
            "high_forensic_count": len(high_forensic),
            "caught_count": len(caught),
            "missed_count": len(missed),
            "overflagged_count": len(overflagged),
            "caught_by_existing": caught[:12],
            "missed_by_existing": missed[:12],
            "overflagged_by_existing": overflagged[:12],
            "caught_groups": _group_model_gap_items(caught),
            "missed_groups": _group_model_gap_items(missed),
            "overflagged_groups": _group_model_gap_items(overflagged),
            "recommended_heuristics": heuristics,
            "analysis_scope": analysis_scope,
            "selected_market_title": selected_market_title,
            "outcome_context_available": outcome_context_available,
        }
        payload["summary"] = _model_gap_summary_text(payload)
        return payload

    def _market_summaries(
        self,
        resolved: ResolvedEvent,
        scoped_trades: list[Trade],
        candidate_trades: list[Trade],
        winners_by_condition: dict[str, str | None],
        price_history: dict[str, dict[str, object]],
        *,
        analysis_markets: dict[str, Market] | None = None,
    ) -> list[dict[str, object]]:
        scoped_by_market = _group_market_trades(scoped_trades)
        candidate_by_market = _group_market_trades(candidate_trades)
        rows: list[dict[str, object]] = []
        for condition_id, market in (analysis_markets or resolved.markets).items():
            series = (price_history.get(condition_id) or {}).get("points") or []
            price_move = _price_move_summary(series)
            rows.append(
                {
                    "conditionId": condition_id,
                    "market": market.question,
                    "marketSlug": market.slug,
                    "marketUrl": f"https://polymarket.com/event/{resolved.event_slug}",
                    "winner": winners_by_condition.get(condition_id) or "Unknown",
                    "tradeCount": len(scoped_by_market.get(condition_id, [])),
                    "candidateTradeCount": len(candidate_by_market.get(condition_id, [])),
                    "volume": float(market.volume),
                    "liquidity": float(market.liquidity),
                    "timelineSummary": price_move,
                }
            )
        return rows

    def _timeline_points(
        self,
        resolved: ResolvedEvent,
        suspicious_trades: list[dict[str, object]],
        price_history: dict[str, dict[str, object]],
    ) -> list[dict[str, object]]:
        points: list[dict[str, object]] = []
        for trade in suspicious_trades[:12]:
            price_context = _side_outcome_label_for_trade(trade)
            note = (
                f"{trade['walletShort']} {trade['orderSide']} {trade['side']} for "
                f"${trade['positionSize']:,.0f}. {price_context}. {trade['summary']}"
            )
            points.append(
                {
                    "timestamp": trade["timestamp"],
                    "label": trade["market"],
                    "note": note,
                    "type": "trade",
                }
            )
        for condition_id, series_payload in price_history.items():
            summary = _price_jump_point(series_payload.get("points") or [])
            if summary is None:
                continue
            market = resolved.markets.get(condition_id)
            if market is None:
                continue
            points.append(
                {
                    "timestamp": summary["timestamp"],
                    "label": market.question,
                    "note": (
                        f"The tracked market side moved from {summary['startPrice']:.2f} to "
                        f"{summary['endPrice']:.2f} over the sharpest observed hourly move."
                    ),
                    "type": "price_move",
                }
            )
        points.sort(key=lambda item: item["timestamp"])
        return points[:20]

    def _event_report_markdown(self, report: dict[str, object]) -> str:
        event = report["event"]
        summary = report["summary"]
        markets = report.get("markets", [])
        analysis_scope = _report_analysis_scope(report)
        selected_market_title = _report_selected_market_title(report)
        selected_condition_id = _report_selected_condition_id(report)
        selected_market_slug = str(
            report.get("selected_market_slug")
            or (report.get("target_resolution") or {}).get("selectedMarketSlug")
            or ""
        )
        parent_event_slug = str(
            report.get("parent_event_slug")
            or event.get("slug")
            or (report.get("target_resolution") or {}).get("parentEventSlug")
            or ""
        )
        scope_product_metadata = _report_scope_product_metadata(report)
        lines = [
            "# InsPoly Event Forensic Report",
            "",
            f"## {event['title']}",
            "",
            f"- Event link: {event['canonicalUrl']}",
            f"- Outcome status: {_report_resolution_status_label(report)}",
            f"- Analysis scope: {_analysis_scope_label(analysis_scope)}",
            f"- Markets analyzed: {summary.get('analysis_market_count', event.get('analysisMarketCount', event.get('marketCount', 0)))}",
            f"- Total event markets: {event.get('marketCount', 0)}",
            f"- Trades above threshold: {summary.get('candidate_trade_count', 0)}",
            f"- Unique wallets in loaded {'selected-market' if analysis_scope == 'market' else 'event'} sample: {summary.get('unique_wallet_count', 0)}",
            f"- Parent event slug: {parent_event_slug or 'Unknown'}",
            f"- Scope: {report.get('scope_note', 'Event-wide review across all wallets active in the loaded event.')}",
            f"- Product scope: {scope_product_metadata['analysisScope']}",
            f"- Primary scoring scope: {scope_product_metadata['primaryScoringScope']}",
            f"- Related markets context included: {'yes' if scope_product_metadata['relatedMarketsContextIncluded'] else 'no'}",
            f"- Sibling markets primary-scored: {'yes' if scope_product_metadata['siblingMarketsPrimaryScored'] else 'no'}",
            f"- Scope explanation: {scope_product_metadata['scopeExplanation']}",
            "",
        ]
        if analysis_scope == "market":
            lines.extend(
                [
                    f"- Selected market: {selected_market_title or 'Unknown child market'}",
                    f"- Condition ID: {selected_condition_id or 'Unknown'}",
                    f"- Market slug: {selected_market_slug or 'Unknown'}",
                    "",
                ]
            )
        eligibility = report.get("eligibility", {})
        if not eligibility.get("eligible", False):
            lines.extend(
                [
                    "## Eligibility",
                    "",
                    str(eligibility.get("reason", "This event is not eligible for full forensic mode.")),
                    "",
                ]
            )
            return "\n".join(lines)
        if eligibility.get("status") == "partial" and eligibility.get("reason"):
            lines.extend(
                [
                    "## Partial Resolution Note",
                    "",
                    str(eligibility.get("reason")),
                    "",
                ]
            )
        if eligibility.get("status") == "live" and eligibility.get("reason"):
            lines.extend(
                [
                    "## Live Event Note",
                    "",
                    str(eligibility.get("reason")),
                    "",
                ]
            )
        if eligibility.get("status") == "unresolved" and eligibility.get("reason"):
            lines.extend(
                [
                    "## Outcome Availability",
                    "",
                    str(eligibility.get("reason")),
                    "",
                ]
            )
        funding_lines = _funding_availability_report_lines(report.get("funding_resolver_health"))
        if funding_lines:
            lines.extend(["## Funding Availability", ""])
            lines.extend(funding_lines)
            lines.append("")
        evidence_warnings = [str(item) for item in report.get("evidence_warnings", []) if str(item).strip()]
        if evidence_warnings:
            lines.extend(["## Evidence Availability", ""])
            for warning in evidence_warnings:
                lines.append(f"- {warning}")
            lines.append("")

        top_trades = (report.get("display_trades") or report.get("suspicious_trades", []))[:8]
        review_required_trades = (
            report.get("display_review_required_trades")
            or report.get("review_required_trades")
            or []
        )[:8]
        top_wallets = (report.get("display_wallets") or report.get("suspicious_wallets", []))[:8]
        clusters = (report.get("display_clusters") or report.get("wallet_clusters", []))[:5]
        primary_story = _primary_story_lines(report, top_trades, top_wallets, clusters)
        primary_wallets = _primary_story_wallets(primary_story)
        lines.extend(["## Primary Story", ""])
        lines.extend(primary_story.get("lines") or [])

        other_candidates = _other_candidate_lines(top_wallets, top_trades, primary_wallets)
        lines.extend(["", "## Other Candidates Worth a Look", ""])
        if other_candidates:
            lines.extend(other_candidates)
        else:
            lines.append("- No secondary wallet or trade lead cleared the on-screen review threshold.")

        if review_required_trades:
            lines.extend(["", "## Review-Required Context", ""])
            lines.append(
                "- These rows remain exported but are kept out of the primary trade list by the weak-history near-certainty policy."
            )
            for trade in review_required_trades:
                lines.append(
                    f"- `{trade.get('walletShort') or _short_wallet(str(trade.get('wallet') or ''))}` "
                    f"{trade.get('orderSide') or ''} {trade.get('side') or ''} in **{trade.get('market') or 'Unknown market'}**: "
                    f"{trade.get('weakHistoryNearCertaintyReviewReason') or WEAK_HISTORY_NEAR_CERTAINTY_REVIEW_REASON}"
                )

        lines.extend(["", "## What To Inspect Next", ""])
        lines.extend(_next_action_lines(report, primary_story, clusters))

        lines.extend(["", "## Scope and Sample Notes", ""])
        lines.append(f"- Analysis scope: {_analysis_scope_label(analysis_scope)}.")
        lines.append(
            f"- Markets analyzed: {summary.get('analysis_market_count', event.get('analysisMarketCount', event.get('marketCount', 0)))} "
            f"of {event.get('marketCount', 0)} event market(s)."
        )
        lines.append(f"- Trades above the configured size threshold: {summary.get('candidate_trade_count', 0)}.")
        lines.append(
            f"- Unique wallets in the loaded {'selected-market' if analysis_scope == 'market' else 'event'} sample: "
            f"{summary.get('unique_wallet_count', 0)}."
        )
        display_note = _human_display_note(str(report.get("display_note") or ""))
        if display_note:
            lines.append(f"- {display_note}")

        lines.extend(["", "## Outcome Context", ""])
        if markets:
            outcome_counts = Counter(str(market.get("winner") or "Unknown") for market in markets)
            yes_markets = sorted(
                [market for market in markets if str(market.get("winner") or "") == "Yes"],
                key=lambda item: str(item.get("market") or ""),
            )
            unknown_markets = sorted(
                [
                    market
                    for market in markets
                    if str(market.get("winner") or "Unknown") not in {"Yes", "No"}
                ],
                key=lambda item: str(item.get("market") or ""),
            )
            lines.append(
                f"- {len(markets)} child markets were reviewed: "
                f"{outcome_counts.get('Yes', 0)} resolved **Yes**, "
                f"{outcome_counts.get('No', 0)} resolved **No**, "
                f"and {outcome_counts.get('Unknown', 0)} remain **Unknown**."
            )
            if yes_markets:
                yes_labels = _market_label_list(yes_markets, limit=6)
                lines.append(f"- The markets that resolved **Yes** were: {yes_labels}.")
            if unknown_markets:
                unknown_labels = _market_label_list(unknown_markets, limit=4)
                lines.append(f"- Still unresolved or unknown: {unknown_labels}.")
            if summary.get("truncated_market_count", 0):
                lines.append(
                    f"- {summary.get('truncated_market_count', 0)} market(s) hit the trade pagination cap, "
                    "so the loaded sample for those markets is partial."
                )
        else:
            lines.append("- No child-market outcome rows were saved in this report.")

        lines.extend(["", "## Linked Wallet Leads", ""])
        if clusters:
            for index, cluster in enumerate(clusters, start=1):
                lines.append(_cluster_report_line(cluster, index=index))
        else:
            lines.append("- No strong linked-wallet cluster cleared the primary threshold in the loaded data.")

        lines.extend(["", "## Related-Market Behavior", ""])
        related = report.get("related_markets", [])[:5]
        if related:
            if analysis_scope == "market":
                lines.append("- These rows are enrichment only; they do not affect the primary single-market ranking.")
            for item in related:
                lines.append(
                    f"- {item['walletShort']} also traded **{item['market']}** outside the exact event, which reinforces the same event-family thesis."
                )
        else:
            lines.append("- No meaningful same-family spillover was found in the loaded wallet histories.")

        lines.extend(["", "## Analyst Appendix", ""])
        lines.append("- Model QA details are kept in the separate model-gap export so the default report stays focused on review leads.")
        performance = report.get("performance") or {}
        if performance:
            lines.append(
                "- Runtime details are written to the runtime profile export; they are not part of the analyst narrative."
            )
        lines.extend(["", "## Bottom Line", ""])
        if top_trades:
            if not _report_has_outcome_context(report):
                lines.append(
                    "The loaded event is being reviewed before final outcomes are available. "
                    "The strongest cases are therefore based on opening exposure, timing, repricing, wallet behavior, "
                    "funding context, and linkage evidence, not later correctness."
                )
            elif analysis_scope == "market":
                lines.append(
                    "The selected child market showed a mix of current-model signals and selected-market context. "
                    "The strongest cases were the ones that combined opening exposure, later correctness, fast repricing, "
                    "and structural wallet linkage or repeated same-family behavior."
                )
            else:
                lines.append(
                    "This event showed a mix of current-model signals and event-specific context. "
                    "The strongest cases were the ones that combined opening exposure, later correctness, fast repricing, "
                    "and structural wallet linkage or repeated same-family behavior."
                )
        else:
            lines.append(
                (
                    "The selected child market did not produce a strong forensic case. The available evidence leans closer to ordinary trading than to a clear information edge."
                    if analysis_scope == "market"
                    else "The loaded event did not produce a strong forensic case. The available evidence leans closer to ordinary trading than to a clear information edge."
                )
            )
        return "\n".join(lines)

    def _model_gap_markdown(self, report: dict[str, object]) -> str:
        model_gap = report.get("model_gap", {})
        analysis_scope = _report_analysis_scope(report)
        selected_market_title = _report_selected_market_title(report)
        lines = [
            "# Event Model Gap Report",
            "",
            _model_gap_summary_text(model_gap),
        ]
        lines.extend(
            [
                "",
                "## Scope",
                "",
                (
                    f"- This compares only the selected child market ({selected_market_title or 'Unknown child market'})."
                    if analysis_scope == "market"
                    else "- This is an event-wide comparison, not a single-wallet report."
                ),
            ]
        )
        missed = model_gap.get("missed_groups", [])
        if missed:
            lines.extend(["", "## What The Current Model Missed", ""])
            for item in missed:
                lines.append(f"- {item['summary']}")
        overflagged = model_gap.get("overflagged_groups", [])
        if overflagged:
            lines.extend(["", "## Trades That Looked Weaker After Event Context", ""])
            for item in overflagged:
                lines.append(f"- {item['summary']}")
        heuristics = model_gap.get("recommended_heuristics", [])
        if heuristics:
            lines.extend(["", "## Possible Improvements", ""])
            for heuristic in heuristics:
                lines.append(f"- {heuristic}")
        if not missed and not overflagged and not heuristics:
            lines.extend(
                [
                    "",
                    "## Bottom Line",
                    "",
                    (
                        f"- The selected child market ({selected_market_title or 'Unknown child market'}) did not reveal a useful model-gap lesson on its own."
                        if analysis_scope == "market"
                        else "- This event did not reveal a useful model-gap lesson on its own."
                    ),
                ]
            )
            return "\n".join(lines)
        if not heuristics:
            lines.extend(
                [
                    "",
                    "## Possible Improvements",
                    "",
                    (
                        "- No new heuristic stood out strongly enough in the selected child market alone."
                        if analysis_scope == "market"
                        else "- No new heuristic stood out strongly enough in this event alone."
                    ),
                ]
            )
        return "\n".join(lines)

    def _write_report_bundle(
        self,
        started_at: datetime,
        reports_dir: Path,
        report: dict[str, object],
        *,
        suspicious_trades: list[dict[str, object]],
        suspicious_wallets: list[dict[str, object]],
        ranked_wallets: list[dict[str, object]],
        wallet_clusters: list[dict[str, object]],
        wallet_graph: dict[str, object],
        related_markets: list[dict[str, object]],
        candidate_audit_rows: list[dict[str, object]],
        raw_bundle: dict[str, object],
        indexer_warehouse_pointer: dict[str, object] | None = None,
    ) -> dict[str, str]:
        suffix = "_stopped" if report.get("status") == "stopped" else ""
        base_name = started_at.strftime("event_forensic_%Y%m%d_%H%M%S") + suffix
        bundle_dir = self._config.outputs_dir / base_name
        raw_dir = bundle_dir / "raw_event_bundle"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)

        report_json_path = reports_dir / f"{base_name}.json"
        event_analysis_json_path = bundle_dir / "event_analysis.json"
        event_report_md_path = bundle_dir / "event_report.md"
        suspicious_trades_csv_path = bundle_dir / "suspicious_trades.csv"
        suspicious_wallets_csv_path = bundle_dir / "suspicious_wallets.csv"
        wallet_context_csv_path = bundle_dir / "wallet_context.csv"
        wallet_clusters_csv_path = bundle_dir / "wallet_clusters.csv"
        wallet_graph_json_path = bundle_dir / "wallet_graph.json"
        related_markets_json_path = bundle_dir / "related_markets.json"
        model_gap_md_path = bundle_dir / "model_gap_report.md"
        runtime_profile_path = bundle_dir / "runtime_profile.log"
        admission_funnel_json_path = bundle_dir / "candidate_admission_funnel.json"
        admission_funnel_md_path = bundle_dir / "candidate_admission_funnel.md"
        candidate_trades_csv_path = bundle_dir / "candidate_trades.csv"
        candidate_trades_json_path = bundle_dir / "candidate_trades.json"
        candidate_audit_md_path = bundle_dir / "candidate_audit.md"
        admission_funnel = report.get("candidate_admission_funnel")

        export_files = {
            "report_json_path": str(report_json_path),
            "event_analysis_json_path": str(event_analysis_json_path),
            "event_report_md_path": str(event_report_md_path),
            "suspicious_trades_csv_path": str(suspicious_trades_csv_path),
            "suspicious_wallets_csv_path": str(suspicious_wallets_csv_path),
            "wallet_context_csv_path": str(wallet_context_csv_path),
            "wallet_clusters_csv_path": str(wallet_clusters_csv_path),
            "wallet_graph_json_path": str(wallet_graph_json_path),
            "related_markets_json_path": str(related_markets_json_path),
            "model_gap_report_md_path": str(model_gap_md_path),
            "runtime_profile_path": str(runtime_profile_path),
            "raw_event_bundle_dir": str(raw_dir),
            "candidate_trades_csv_path": str(candidate_trades_csv_path),
            "candidate_trades_json_path": str(candidate_trades_json_path),
            "candidate_audit_md_path": str(candidate_audit_md_path),
        }
        if isinstance(admission_funnel, dict):
            export_files["candidate_admission_funnel_json_path"] = str(admission_funnel_json_path)
            export_files["candidate_admission_funnel_md_path"] = str(admission_funnel_md_path)
        persisted_report = dict(report)
        persisted_report["export_files"] = export_files
        persisted_report["report_json_path"] = str(report_json_path)
        persisted_report["report_md_path"] = str(event_report_md_path)
        persisted_report["report_txt_path"] = str(event_report_md_path)
        if indexer_warehouse_pointer is not None:
            persisted_report = attach_indexer_warehouse_pointer(
                persisted_report,
                indexer_warehouse_pointer,
                source_report_id=str(report_json_path),
                generated_at=started_at,
            )
            report[POINTER_FIELD] = persisted_report[POINTER_FIELD]

        report_json = json.dumps(persisted_report, ensure_ascii=False, indent=2)
        report_json_path.write_text(report_json, encoding="utf-8")
        event_analysis_json_path.write_text(report_json, encoding="utf-8")
        event_report_md_path.write_text(str(report.get("event_report_markdown", "")), encoding="utf-8")
        model_gap_md_path.write_text(str(report.get("model_gap_markdown", "")), encoding="utf-8")
        runtime_profile_path.write_text(_runtime_profile_text(persisted_report), encoding="utf-8")
        wallet_graph_json_path.write_text(json.dumps(wallet_graph, ensure_ascii=False, indent=2), encoding="utf-8")
        related_markets_json_path.write_text(json.dumps(related_markets, ensure_ascii=False, indent=2), encoding="utf-8")
        candidate_trades_json_path.write_text(
            json.dumps(
                _candidate_audit_json_payload(persisted_report, candidate_audit_rows),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        candidate_audit_md_path.write_text(
            _candidate_audit_markdown(persisted_report, candidate_audit_rows),
            encoding="utf-8",
        )
        if isinstance(admission_funnel, dict):
            admission_funnel_json_path.write_text(
                json.dumps(admission_funnel, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            admission_funnel_md_path.write_text(
                _structural_pre_admission_funnel_markdown(admission_funnel),
                encoding="utf-8",
            )

        _write_csv(
            candidate_trades_csv_path,
            candidate_audit_rows,
            _candidate_audit_fieldnames(),
        )
        _write_csv(
            suspicious_trades_csv_path,
            suspicious_trades,
            [
                "analysisScope",
                "selectedConditionId",
                "selectedMarketSlug",
                "selectedMarketTitle",
                "parentEventSlug",
                "conditionId",
                "wallet",
                "username",
                "timestamp",
                "market",
                "side",
                "orderSide",
                "rawTokenOutcome",
                "rawOrderSide",
                "rawTokenPrice",
                "rawTokenPriceLabel",
                "economicSide",
                "economicSideProbability",
                "economicSideProbabilityLabel",
                "economicDirectionNormalized",
                "modelProbabilityBasis",
                "modelEconomicDirection",
                "sideOutcomeNormalizationStatus",
                "sideOutcomeFallbackReason",
                "clusterDirection",
                "clusterDirectionBasis",
                "clusterNormalizationStatus",
                "clusterDirectionFallbackReason",
                "positionSize",
                "liquidityShare",
                "laterWon",
                "outcomeStatus",
                "winningOutcome",
                "openingExposure",
                "existingModelScore",
                "existingModelClass",
                "eventForensicScore",
                "weakHistoryNearCertaintyReviewDemotion",
                "weakHistoryNearCertaintyReviewReason",
                "reviewBucketBeforePolicy",
                "reviewBucketAfterPolicy",
                "hardEvidenceSources",
                "hardEvidenceStrength",
                "hardEvidencePrimaryReason",
                "hardEvidenceTradeIds",
                "hardEvidenceWalletIds",
                "hardEvidenceReviewTier",
                "evidenceAvailabilityStage",
                "strongRiskGatePassed",
                "strongRiskGateType",
                "strongRiskGateReasons",
                "strongRiskGateEvidenceSources",
                "strongRiskTimingProofSources",
                "strongRiskStructuralSources",
                "strongRiskSupportingBoosters",
                "strongRiskStructuralConcernCount",
                "strongRiskTimingProofCount",
                "strongRiskOpeningExposureConfirmed",
                "strongRiskConfidenceScore",
                "strongRiskSuspicionScore",
                "strongRiskSuppressorConflict",
                "strongRiskSuppressorConflictReasons",
                "strongRiskHasHardEvidenceSources",
                "strongRiskNoHardEvidenceExplanation",
                "strongRiskCompositionClass",
                *_strong_risk_extra_fieldnames(),
                "candidateAdmissionReason",
                "candidateAdmissionStage",
                "candidateAdmissionEvidenceSources",
                "candidateAdmissionFloorNotional",
                "groupedCandidateId",
                "groupedCandidateAggregateNotional",
                "groupedCandidateWalletCount",
                "groupedCandidateStrictFunding",
                "groupedCandidateProxyOnly",
                "groupedCandidateFundingGrade",
                "groupedCandidateTimeSpanMinutes",
                "groupedCandidatePriceBand",
                "candidateAdmissionValidatedOpeningExposure",
                "candidateAdmissionRejectedReason",
                "fundingEvidenceGrade",
                "suspiciousFundingQuality",
                "suspiciousFundingQualityReasons",
                "suspiciousFundingHardEvidenceEligible",
                "suspiciousFundingTraceSucceeded",
                "suspiciousFundingTraceDepth",
                "suspiciousFundingSourceCategory",
                "suspiciousFundingOriginCategory",
                "suspiciousFundingMinutesBeforeTrade",
                "suspiciousFundingAmountUsd",
                "suspiciousFundingTradeNotionalUsd",
                "suspiciousFundingAmountToTradeRatio",
                "suspiciousFundingRecentEnough",
                "suspiciousFundingAmountAligned",
                "suspiciousFundingIndependentSupport",
                "suspiciousFundingIndependentSupportSources",
                "suspiciousFundingSuppressorConflict",
                "suspiciousFundingSuppressorConflictReasons",
                "fundingResolverAvailable",
                "fundingResolverDisabledReason",
                "fundingResolverAuthError",
                "fundingResolverUnavailableReason",
                "fundingResolverFunctionalStatus",
                "fundingResolverEndpointLabel",
                "fundingResolverLastError",
                "fundingTraceAttemptedCount",
                "fundingTraceSucceededCount",
                "fundingTraceFailedCount",
                "fundingTraceSkippedCount",
                "fundingTraceCoverageRatio",
                "fundingTraceEndpointPoolSize",
                "fundingTraceEndpointAvailableCount",
                "fundingTraceEndpointCooldownCount",
                "fundingTraceEndpointFailureDistribution",
                "fundingTraceRateLimitedCount",
                "fundingTraceRetryCount",
                "fundingTraceFallbackEndpointCount",
                "fundingTraceLogChunksAttempted",
                "fundingTraceLogChunksSucceeded",
                "fundingTraceLogChunksFailed",
                "fundingTraceLogChunksRateLimited",
                "fundingTraceCacheHitCount",
                "fundingTraceCacheMissCount",
                "fundingTracePersistentCacheEnabled",
                "fundingTracePersistentCacheHitCount",
                "fundingTracePersistentCacheMissCount",
                "fundingTracePersistentCacheWriteCount",
                "fundingTracePersistentCacheExpiredCount",
                "fundingTracePersistentCacheFailureCooldownCount",
                "fundingTracePersistentCacheSchemaVersion",
                "fundingTraceFromPersistentCache",
                "fundingTracePersistentCacheStatus",
                "fundingProxyTightCohort",
                "sharedFundingSourceWalletCount",
                "repricingSourceQuality",
                "repricingSourceQualityReasons",
                "walletReviewDomainProfile",
                "walletReviewDomainCount",
                "walletSportsHistoryTradeCount",
                "walletCrossDomainPublicBettorFlag",
                "walletCrossDomainPublicBettorReason",
                "finalEventJudgment",
                "summary",
            ],
        )
        _write_csv(
            suspicious_wallets_csv_path,
            suspicious_wallets,
            _wallet_csv_fieldnames(),
        )
        _write_csv(
            wallet_context_csv_path,
            ranked_wallets if ranked_wallets is not None else suspicious_wallets,
            _wallet_csv_fieldnames(),
        )
        _write_csv(
            wallet_clusters_csv_path,
            wallet_clusters,
            [
                "analysisScope",
                "selectedConditionId",
                "selectedMarketSlug",
                "selectedMarketTitle",
                "parentEventSlug",
                "id",
                "connectionType",
                "walletCount",
                "sameFunder",
                "sameSideTimingPattern",
                "relatedMarketOverlap",
                "otherEventMarketTrades",
                "siblingMarketWalletCount",
                "clusterScore",
                "hardEvidenceSources",
                "hardEvidenceStrength",
                "hardEvidencePrimaryReason",
                "hardEvidenceTradeIds",
                "hardEvidenceWalletIds",
                "hardEvidenceReviewTier",
                "evidenceAvailabilityStage",
                "summary",
            ],
        )

        for name, payload in raw_bundle.items():
            path = raw_dir / f"{name}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return export_files


def _wallet_csv_fieldnames() -> list[str]:
    return [
        "analysisScope",
        "selectedConditionId",
        "selectedMarketSlug",
        "selectedMarketTitle",
        "parentEventSlug",
        "wallet",
        "username",
        "walletScore",
        "insiderStyleWalletScore",
        "suspiciousTradeCount",
        "eventTradeCount",
        "walletTotalPredictions",
        "walletProfileViews",
        "walletJoinedAt",
        "walletProfileAgeDays",
        "walletLoadedEventTradeCount",
        "walletNotableTradeCount",
        "walletOpeningEntryCount",
        "walletWinningOpeningEntryCount",
        "walletEventTradeDensity",
        "walletUniqueEventMarketsTraded",
        "walletLoadedHistoryTradeCount",
        "walletLoadedUniqueMarketCount",
        "walletPublicPowerUserFlag",
        "walletHighVolumeEventUserFlag",
        "walletEventSaturationFlag",
        "independentHardEvidenceFlag",
        "walletHardEvidenceSources",
        "walletEvidenceSourceFlags",
        "walletHardEvidenceSourceDetails",
        "hardEvidenceSources",
        "hardEvidenceStrength",
        "hardEvidencePrimaryReason",
        "hardEvidenceTradeIds",
        "hardEvidenceWalletIds",
        "hardEvidenceReviewTier",
        "evidenceAvailabilityStage",
        "strongRiskGatePassed",
        "strongRiskGateType",
        "strongRiskGateReasons",
        "strongRiskGateEvidenceSources",
        "strongRiskTimingProofSources",
        "strongRiskStructuralSources",
        "strongRiskSupportingBoosters",
        "strongRiskStructuralConcernCount",
        "strongRiskTimingProofCount",
        "strongRiskOpeningExposureConfirmed",
        "strongRiskConfidenceScore",
        "strongRiskSuspicionScore",
        "strongRiskSuppressorConflict",
        "strongRiskSuppressorConflictReasons",
        "strongRiskHasHardEvidenceSources",
        "strongRiskNoHardEvidenceExplanation",
        "strongRiskCompositionClass",
        *_strong_risk_extra_fieldnames(),
        "candidateAdmissionReason",
        "candidateAdmissionStage",
        "candidateAdmissionEvidenceSources",
        "candidateAdmissionFloorNotional",
        "groupedCandidateId",
        "groupedCandidateAggregateNotional",
        "groupedCandidateWalletCount",
        "groupedCandidateStrictFunding",
        "groupedCandidateProxyOnly",
        "groupedCandidateFundingGrade",
        "groupedCandidateTimeSpanMinutes",
        "groupedCandidatePriceBand",
        "candidateAdmissionValidatedOpeningExposure",
        "candidateAdmissionRejectedReason",
        "repricingSourceQuality",
        "repricingSourceQualityReasons",
        "fundingEvidenceGrade",
        "suspiciousFundingQuality",
        "suspiciousFundingQualityReasons",
        "suspiciousFundingHardEvidenceEligible",
        "suspiciousFundingTraceSucceeded",
        "suspiciousFundingTraceDepth",
        "suspiciousFundingSourceCategory",
        "suspiciousFundingOriginCategory",
        "suspiciousFundingMinutesBeforeTrade",
        "suspiciousFundingAmountUsd",
        "suspiciousFundingTradeNotionalUsd",
        "suspiciousFundingAmountToTradeRatio",
        "suspiciousFundingRecentEnough",
        "suspiciousFundingAmountAligned",
        "suspiciousFundingIndependentSupport",
        "suspiciousFundingIndependentSupportSources",
        "suspiciousFundingSuppressorConflict",
        "suspiciousFundingSuppressorConflictReasons",
        "walletPublicWhaleOrPowerUserLabel",
        "walletPublicPowerUserReducerApplied",
        "walletPublicPowerUserStatus",
        "walletHighVolumeEventStatus",
        "walletEventSaturationStatus",
        "walletCrossDomainPublicBettorFlag",
        "walletCrossDomainPublicBettorStatus",
        "walletCrossDomainPublicBettorReason",
        "walletReviewDomainProfile",
        "walletPrimaryReviewStatus",
        "walletPublicPowerUserNote",
        "caseInterpretationClass",
        "relatedMarketTradeCount",
        "otherEventMarketTrades",
        "siblingMarketActivityCount",
        "eventResult",
        "fundingFlags",
        "specialistStatus",
        "botStatus",
        "zombieStatus",
        "walletQualityStatus",
        "walletQualityNote",
        "walletStatisticalPriorLabel",
        "walletStatisticalPValue",
        "walletStatisticalLogScore",
        "walletResolvedSampleSize",
        "walletResolvedWinRate",
        "walletStatisticalPriorNote",
        "primaryEvidenceStatus",
        "summary",
    ]


_STRONG_RISK_BASE_ATTRIBUTION_FIELDNAMES = {
    "strongRiskGatePassed",
    "strongRiskGateType",
    "strongRiskGateReasons",
    "strongRiskGateEvidenceSources",
    "strongRiskTimingProofSources",
    "strongRiskStructuralSources",
    "strongRiskSupportingBoosters",
    "strongRiskStructuralConcernCount",
    "strongRiskTimingProofCount",
    "strongRiskOpeningExposureConfirmed",
    "strongRiskConfidenceScore",
    "strongRiskSuspicionScore",
    "strongRiskSuppressorConflict",
    "strongRiskSuppressorConflictReasons",
    "strongRiskHasHardEvidenceSources",
    "strongRiskNoHardEvidenceExplanation",
    "strongRiskCompositionClass",
}


def _strong_risk_extra_fieldnames() -> list[str]:
    return [
        field
        for field in STRONG_RISK_ATTRIBUTION_FIELDS
        if field not in _STRONG_RISK_BASE_ATTRIBUTION_FIELDNAMES
    ]


_WALLET_STRONG_RISK_DEDUPE_FIELDS = {
    "strongRiskIndependentEvidenceSources",
    "strongRiskExactGateBranch",
    "strongRiskExactGateFailedReasons",
    "strongRiskStructuralSourcesResolved",
    "strongRiskHardEvidenceEligibleSources",
    "strongRiskNonHardStructuralSources",
    "strongRiskSourceAttributionIssue",
    "strongRiskNoHardEvidenceSourcesReason",
    "strongRiskScoreOnlyResolution",
    "strongRiskGateLeakageReason",
    "strongRiskRetrospectiveSources",
}


_WALLET_STRONG_RISK_YES_NO_FIELDS = {
    "strongRiskHasIndependentHardEvidence",
    "strongRiskTimingRepricingOnly",
    "strongRiskScoreOnly",
    "strongRiskSavedFieldsSufficient",
    "strongRiskDiagnosticOnly",
    "strongRiskExactGatePassed",
    "strongRiskGateSourceWasInferred",
    "strongRiskMissingSourceAttribution",
    "strongRiskGateLeakageCandidate",
    "strongRiskLiveDetectable",
    "strongRiskRetrospectiveOnly",
}


def _wallet_strong_risk_extra_values(items: list[dict[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for field in _strong_risk_extra_fieldnames():
        if field in _WALLET_STRONG_RISK_YES_NO_FIELDS:
            field_values = [str(item.get(field) or "").strip() for item in items]
            if any(value == "Yes" for value in field_values):
                values[field] = "Yes"
            elif any(value == "No" for value in field_values):
                values[field] = "No"
            else:
                values[field] = ""
        elif field in _WALLET_STRONG_RISK_DEDUPE_FIELDS:
            values[field] = _dedupe_labels(
                [
                    text
                    for item in items
                    for text in _text_values(item.get(field))
                ]
            )
        else:
            values[field] = _first_text(item.get(field) for item in items)
    return values


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = {}
            for field in fieldnames:
                value = row.get(field, "")
                if isinstance(value, list):
                    payload[field] = "; ".join(str(item) for item in value)
                else:
                    payload[field] = value
            writer.writerow(payload)


def _candidate_audit_fieldnames() -> list[str]:
    return [
        "source",
        "tradeId",
        "wallet",
        "username",
        "marketSlug",
        "conditionId",
        "timestamp",
        "side",
        "outcome",
        "orderSide",
        "rawTokenOutcome",
        "rawOrderSide",
        "rawTokenPrice",
        "rawTokenPriceLabel",
        "economicSide",
        "economicSideProbability",
        "economicSideProbabilityLabel",
        "economicDirectionNormalized",
        "modelProbabilityBasis",
        "modelEconomicDirection",
        "sideOutcomeNormalizationStatus",
        "sideOutcomeFallbackReason",
        "clusterDirection",
        "clusterDirectionBasis",
        "clusterNormalizationStatus",
        "clusterDirectionFallbackReason",
        "notionalUsd",
        "currentModelScore",
        "currentModelSeverity",
        "currentModelVerdict",
        "strongRiskGateStatus",
        "strongRiskGateType",
        "strongRiskGateBranch",
        "strongRiskGateReasons",
        "hardEvidenceReviewFlag",
        "hardEvidenceReviewTier",
        "hardEvidenceSources",
        "eventForensicScore",
        "weakHistoryNearCertaintyReviewDemotion",
        "weakHistoryNearCertaintyReviewReason",
        "reviewBucketBeforePolicy",
        "reviewBucketAfterPolicy",
        "eventForensicFlags",
        "eventForensicBoosters",
        "eventForensicReducers",
        "fundingEvidenceGrade",
        "fundingTraceMode",
        "fundingTraceStatus",
        "highVolumePublicUserStatus",
        "crossDomainPublicBettorStatus",
        "repricingSourceQuality",
        "nearCertaintyOrStaleStatus",
        "botOrLowAnalystValueStatus",
        "finalDisplayTier",
        "finalTierReason",
        "primaryUiExplanation",
        "analysisScope",
        "selectedConditionId",
        "selectedMarketSlug",
        "parentEventSlug",
        "candidateAdmissionStage",
        "candidateAdmissionReason",
        "candidateAdmissionRejectedReason",
        "openingExposure",
        "siblingContextOnly",
        "rawCurrentModelFlags",
        "rawExistingWhy",
    ]


def _candidate_audit_rows(
    visible_trade_payloads: list[dict[str, object]],
    *,
    suspicious_trades: list[dict[str, object]],
    ranked_wallets: list[dict[str, object]],
    funding_trace_mode: str,
) -> list[dict[str, object]]:
    primary_trade_ids = {
        str(item.get("id") or item.get("tradeId") or "").strip()
        for item in suspicious_trades
        if str(item.get("id") or item.get("tradeId") or "").strip()
    }
    primary_trade_keys = {
        _candidate_trade_key(item)
        for item in suspicious_trades
        if _candidate_trade_key(item)
    }
    wallet_status = {
        str(item.get("wallet") or "").lower(): item
        for item in ranked_wallets
        if str(item.get("wallet") or "").strip()
    }

    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in sorted(visible_trade_payloads, key=_event_trade_sort_key, reverse=True):
        trade_id = str(item.get("id") or item.get("tradeId") or "").strip()
        key = trade_id or _candidate_trade_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        wallet_row = wallet_status.get(str(item.get("wallet") or "").lower(), {})
        is_primary = bool(trade_id and trade_id in primary_trade_ids) or _candidate_trade_key(item) in primary_trade_keys
        rows.append(
            _candidate_audit_row_from_trade_payload(
                item,
                wallet_row=wallet_row,
                is_primary=is_primary,
                funding_trace_mode=funding_trace_mode,
            )
        )
    return rows


def _candidate_audit_row_from_trade_payload(
    item: dict[str, object],
    *,
    wallet_row: dict[str, object],
    is_primary: bool,
    funding_trace_mode: str,
) -> dict[str, object]:
    raw = item.get("rawMetrics")
    raw_metrics = raw if isinstance(raw, dict) else {}
    tier, reason, explanation = _candidate_audit_display_tier(item, wallet_row=wallet_row, is_primary=is_primary)
    hard_evidence_sources = _text_values(item.get("hardEvidenceSources") or raw_metrics.get("hardEvidenceSources"))
    hard_evidence_tier = str(item.get("hardEvidenceReviewTier") or raw_metrics.get("hardEvidenceReviewTier") or "")
    event_flags = _text_values(item.get("eventForensicFlags"))
    event_reducers = _text_values(item.get("eventForensicReducers"))
    suppressor_reasons = _text_values(
        item.get("strongRiskSuppressorConflictReasons")
        or raw_metrics.get("strongRiskSuppressorConflictReasons")
    )
    high_volume_status = str(wallet_row.get("walletPrimaryReviewStatus") or wallet_row.get("walletPublicPowerUserStatus") or "")
    if not high_volume_status and any("high_volume_public_user" in reason for reason in suppressor_reasons):
        high_volume_status = "high_volume_public_user_context"
    cross_domain_status = str(wallet_row.get("walletCrossDomainPublicBettorStatus") or "")
    if not cross_domain_status and str(item.get("walletCrossDomainPublicBettorFlag") or raw_metrics.get("wallet_cross_domain_public_bettor_flag") or "") == "Yes":
        cross_domain_status = "cross_domain_public_bettor"
    funding_grade = str(item.get("fundingEvidenceGrade") or raw_metrics.get("fundingEvidenceGrade") or raw_metrics.get("funding_evidence_grade") or "").strip()
    if not funding_grade:
        funding_grade = "unknown"
    funding_status = str(
        item.get("fundingResolverFunctionalStatus")
        or raw_metrics.get("fundingResolverFunctionalStatus")
        or item.get("fundingResolverDisabledReason")
        or raw_metrics.get("fundingResolverDisabledReason")
        or ""
    )
    if not funding_status and funding_trace_mode == "disabled":
        funding_status = "disabled_no_rpc_mode"
    return {
        "source": "new_run_visible_candidate",
        "tradeId": item.get("id") or item.get("tradeId") or "",
        "wallet": item.get("wallet", ""),
        "username": item.get("username", ""),
        "marketSlug": item.get("marketSlug", ""),
        "conditionId": item.get("conditionId", ""),
        "timestamp": item.get("timestamp", ""),
        "side": item.get("side", ""),
        "outcome": item.get("side", ""),
        "orderSide": item.get("orderSide", ""),
        "rawTokenOutcome": item.get("rawTokenOutcome", ""),
        "rawOrderSide": item.get("rawOrderSide", ""),
        "rawTokenPrice": item.get("rawTokenPrice", ""),
        "rawTokenPriceLabel": item.get("rawTokenPriceLabel", ""),
        "economicSide": item.get("economicSide", ""),
        "economicSideProbability": item.get("economicSideProbability", ""),
        "economicSideProbabilityLabel": item.get("economicSideProbabilityLabel", ""),
        "economicDirectionNormalized": item.get("economicDirectionNormalized", ""),
        "modelProbabilityBasis": item.get("modelProbabilityBasis", ""),
        "modelEconomicDirection": item.get("modelEconomicDirection", ""),
        "sideOutcomeNormalizationStatus": item.get("sideOutcomeNormalizationStatus", ""),
        "sideOutcomeFallbackReason": item.get("sideOutcomeFallbackReason", ""),
        "clusterDirection": item.get("clusterDirection", ""),
        "clusterDirectionBasis": item.get("clusterDirectionBasis", ""),
        "clusterNormalizationStatus": item.get("clusterNormalizationStatus", ""),
        "clusterDirectionFallbackReason": item.get("clusterDirectionFallbackReason", ""),
        "notionalUsd": item.get("positionSize", ""),
        "currentModelScore": item.get("existingModelScore", ""),
        "currentModelSeverity": item.get("existingModelClass", ""),
        "currentModelVerdict": item.get("existingModelVerdict", ""),
        "strongRiskGateStatus": item.get("strongRiskGatePassed") or raw_metrics.get("strongRiskGatePassed") or "",
        "strongRiskGateType": item.get("strongRiskGateType") or raw_metrics.get("strongRiskGateType") or "",
        "strongRiskGateBranch": item.get("strongRiskExactGateBranch") or raw_metrics.get("strongRiskExactGateBranch") or item.get("strongRiskGateName") or raw_metrics.get("strongRiskGateName") or "",
        "strongRiskGateReasons": item.get("strongRiskGateReasons") or raw_metrics.get("strongRiskGateReasons") or "",
        "hardEvidenceReviewFlag": "Yes" if hard_evidence_tier == HARD_EVIDENCE_REVIEW_TIER else "No",
        "hardEvidenceReviewTier": hard_evidence_tier,
        "hardEvidenceSources": hard_evidence_sources,
        "eventForensicScore": item.get("eventForensicScore", ""),
        "weakHistoryNearCertaintyReviewDemotion": item.get("weakHistoryNearCertaintyReviewDemotion", ""),
        "weakHistoryNearCertaintyReviewReason": item.get("weakHistoryNearCertaintyReviewReason", ""),
        "reviewBucketBeforePolicy": item.get("reviewBucketBeforePolicy", ""),
        "reviewBucketAfterPolicy": item.get("reviewBucketAfterPolicy", ""),
        "eventForensicFlags": event_flags,
        "eventForensicBoosters": event_flags,
        "eventForensicReducers": event_reducers,
        "fundingEvidenceGrade": funding_grade,
        "fundingTraceMode": funding_trace_mode,
        "fundingTraceStatus": funding_status,
        "highVolumePublicUserStatus": high_volume_status,
        "crossDomainPublicBettorStatus": cross_domain_status,
        "repricingSourceQuality": item.get("repricingSourceQuality") or raw_metrics.get("repricingSourceQuality") or raw_metrics.get("repricing_source_quality") or "",
        "nearCertaintyOrStaleStatus": _candidate_near_certainty_or_stale_status(item, raw_metrics),
        "botOrLowAnalystValueStatus": _candidate_bot_or_low_value_status(item, raw_metrics, wallet_row),
        "finalDisplayTier": tier,
        "finalTierReason": reason,
        "primaryUiExplanation": explanation,
        "analysisScope": item.get("analysisScope", ""),
        "selectedConditionId": item.get("selectedConditionId", ""),
        "selectedMarketSlug": item.get("selectedMarketSlug", ""),
        "parentEventSlug": item.get("parentEventSlug", ""),
        "candidateAdmissionStage": item.get("candidateAdmissionStage") or raw_metrics.get("candidateAdmissionStage") or "",
        "candidateAdmissionReason": item.get("candidateAdmissionReason") or raw_metrics.get("candidateAdmissionReason") or "",
        "candidateAdmissionRejectedReason": item.get("candidateAdmissionRejectedReason") or raw_metrics.get("candidateAdmissionRejectedReason") or "",
        "openingExposure": item.get("openingExposure", ""),
        "siblingContextOnly": (
            "Yes"
            if item.get("analysisScope") == "market"
            and item.get("selectedConditionId")
            and item.get("conditionId")
            and item.get("conditionId") != item.get("selectedConditionId")
            else "No"
        ),
        "rawCurrentModelFlags": item.get("existingModelFlags", []),
        "rawExistingWhy": item.get("existingWhy", []),
    }


def _candidate_audit_display_tier(
    item: dict[str, object],
    *,
    wallet_row: dict[str, object],
    is_primary: bool,
) -> tuple[str, str, str]:
    score = _metric_int(item.get("eventForensicScore"))
    current_severity = str(item.get("existingModelClass") or "")
    hard_evidence_tier = str(item.get("hardEvidenceReviewTier") or "")
    reducers = _text_values(item.get("eventForensicReducers"))
    suppressors = _text_values(item.get("strongRiskSuppressorConflictReasons"))
    stage = str(item.get("candidateAdmissionStage") or "")
    if is_primary:
        if hard_evidence_tier == HARD_EVIDENCE_REVIEW_TIER:
            reason = "Hard Evidence Review row is always included in primary review."
        else:
            reason = f"Event Forensic score {score} met the primary threshold {EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD}."
        return "primary_event_forensic", reason, "Shown in the primary UI review list."
    if _is_weak_history_near_certainty_review_demoted(item):
        reason = str(item.get("weakHistoryNearCertaintyReviewReason") or WEAK_HISTORY_NEAR_CERTAINTY_REVIEW_REASON)
        before_bucket = str(item.get("reviewBucketBeforePolicy") or "primary_review")
        return (
            WEAK_HISTORY_NEAR_CERTAINTY_REVIEW_REQUIRED_TIER,
            reason,
            f"Kept in exports and candidate audit, but moved from `{before_bucket}` to secondary review-required context.",
        )
    demotion_bits = _dedupe_labels([*reducers, *suppressors])
    demotion_text = "; ".join(demotion_bits[:4]) if demotion_bits else f"Event Forensic score {score} stayed below primary threshold {EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD}."
    if current_severity == "Strong Risk":
        return (
            "current_model_strong_risk_demoted",
            demotion_text,
            "Not shown as a primary Event Forensic row because contextual reducers or missing independent evidence kept it below the primary tier.",
        )
    if current_severity == "Worth a Look":
        return (
            "current_model_worth_a_look_demoted",
            demotion_text,
            "Not shown as a primary Event Forensic row because the current model row stayed below the Event Forensic primary tier.",
        )
    if "near_miss" in stage or "pre_admitted_rejected" in stage:
        return (
            "structural_near_miss",
            demotion_text,
            "Kept as structural/candidate-admission context rather than a primary row.",
        )
    if str(wallet_row.get("walletPrimaryReviewStatus") or "").startswith("context_only"):
        return (
            "context_only",
            str(wallet_row.get("walletPrimaryReviewStatus") or demotion_text),
            "Kept in wallet context, not primary trade review.",
        )
    if score > 0:
        return (
            "secondary_candidate",
            demotion_text,
            "Candidate was scored and exported for audit but did not clear primary UI thresholds.",
        )
    return (
        "not_flagged_candidate",
        "Candidate did not survive current-model or Event Forensic primary review thresholds.",
        "Exported for audit completeness only.",
    )


def _candidate_near_certainty_or_stale_status(item: dict[str, object], raw_metrics: dict[str, object]) -> str:
    flags = _text_values(item.get("existingModelFlags"))
    values = []
    if "near_certainty_trade" in flags:
        values.append("near_certainty_trade")
    for key in (
        "stale_resolution_annotation",
        "soft_resolution_gap_flag",
        "resolution_gap_flag",
        "hard_resolution_gap_flag",
        "possible_public_lag_flag",
    ):
        if str(raw_metrics.get(key) or "") == "Yes":
            values.append(key)
    suppressors = _text_values(item.get("strongRiskSuppressorConflictReasons") or raw_metrics.get("strongRiskSuppressorConflictReasons"))
    values.extend([value for value in suppressors if value in {"near_certainty", "stale_or_resolution_gap"}])
    return "; ".join(_dedupe_labels(values)) or "none_detected"


def _candidate_bot_or_low_value_status(
    item: dict[str, object],
    raw_metrics: dict[str, object],
    wallet_row: dict[str, object],
) -> str:
    values = []
    if str(raw_metrics.get("low_analyst_value_flag") or "") == "Yes":
        values.append("low_analyst_value")
    if str(raw_metrics.get("bot_like_flag") or "") == "Yes":
        values.append("bot_like")
    bot_status = str(wallet_row.get("botStatus") or "")
    if bot_status and bot_status != "not_bot_like":
        values.append(bot_status)
    suppressors = _text_values(item.get("strongRiskSuppressorConflictReasons") or raw_metrics.get("strongRiskSuppressorConflictReasons"))
    values.extend([value for value in suppressors if value in {"bot_like_execution", "low_analyst_value_wallet"}])
    return "; ".join(_dedupe_labels(values)) or "none_detected"


def _candidate_trade_key(item: dict[str, object]) -> str:
    parts = [
        str(item.get("wallet") or ""),
        str(item.get("conditionId") or ""),
        str(item.get("timestamp") or ""),
        str(item.get("side") or ""),
        str(item.get("orderSide") or ""),
        str(item.get("positionSize") or ""),
    ]
    key = "|".join(parts).strip("|")
    return key


def _candidate_audit_summary(report: dict[str, object], rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "countHierarchy": _candidate_audit_count_hierarchy(report, rows),
        "finalDisplayTierCounts": _candidate_audit_tier_counts(rows),
        "topDemotionReasons": _candidate_audit_top_demotion_reasons(rows),
        "rowCount": len(rows),
    }


def _candidate_audit_json_payload(report: dict[str, object], rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "generatedAt": str(report.get("generated_at") or ""),
        "analysisScope": report.get("analysis_scope") or (report.get("analysis_settings") or {}).get("analysis_scope"),
        "selectedConditionId": report.get("selected_condition_id") or (report.get("analysis_settings") or {}).get("selected_condition_id"),
        "selectedMarketSlug": report.get("selected_market_slug") or (report.get("analysis_settings") or {}).get("selected_market_slug"),
        "countHierarchy": _candidate_audit_count_hierarchy(report, rows),
        "finalDisplayTierCounts": _candidate_audit_tier_counts(rows),
        "topDemotionReasons": _candidate_audit_top_demotion_reasons(rows),
        "rows": rows,
        "notes": [
            "Candidate audit is reporting-only and does not change scoring.",
            "Funding unavailable remains unknown, not none.",
            "Single-market primary scope remains condition_id-strict; sibling/event rows are context only.",
        ],
    }


def _candidate_audit_count_hierarchy(report: dict[str, object], rows: list[dict[str, object]]) -> dict[str, object]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    performance = report.get("performance") if isinstance(report.get("performance"), dict) else {}
    return {
        "allEventRowsCollected": performance.get("trade_collection_raw_trade_rows", ""),
        "selectedMarketRowsConsidered": summary.get("raw_trade_count", ""),
        "candidatesAboveMinSize": summary.get("normal_candidate_trade_count") or summary.get("candidate_trade_count") or len(rows),
        "currentModelFlagged": summary.get("existing_flagged_count", ""),
        "currentModelStrongRisk": sum(1 for row in rows if row.get("currentModelSeverity") == "Strong Risk"),
        "eventForensicPrimaryRows": summary.get("forensic_suspicious_trade_count", ""),
        "contextWallets": summary.get("wallet_context_count", ""),
        "truncatedMarkets": summary.get("truncated_market_count", ""),
    }


def _candidate_audit_tier_counts(rows: list[dict[str, object]]) -> dict[str, int]:
    return dict(Counter(str(row.get("finalDisplayTier") or "unknown") for row in rows))


def _candidate_audit_top_demotion_reasons(rows: list[dict[str, object]], *, limit: int = 12) -> list[dict[str, object]]:
    counter: Counter[str] = Counter()
    for row in rows:
        if row.get("finalDisplayTier") == "primary_event_forensic":
            continue
        for value in _text_values(row.get("eventForensicReducers")):
            counter[value] += 1
        for value in _text_values(row.get("finalTierReason")):
            if value and value not in {"none_detected"}:
                counter[value] += 1
    return [{"reason": reason, "count": count} for reason, count in counter.most_common(limit)]


def _candidate_audit_markdown(report: dict[str, object], rows: list[dict[str, object]]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    settings = report.get("analysis_settings") if isinstance(report.get("analysis_settings"), dict) else {}
    count_hierarchy = _candidate_audit_count_hierarchy(report, rows)
    tier_counts = _candidate_audit_tier_counts(rows)
    demotion_reasons = _candidate_audit_top_demotion_reasons(rows)
    lines = [
        "# Event Forensic Candidate Audit",
        "",
        "This export is reporting-only. It exposes candidate visibility and demotion reasons without changing detector/scoring/gate/HER/funding/candidate-admission behavior.",
        "",
        "## Count Hierarchy",
        "",
    ]
    for key, value in count_hierarchy.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Scope",
            "",
            f"- Analysis scope: `{settings.get('analysis_scope') or report.get('analysis_scope') or ''}`",
            f"- Selected condition ID: `{settings.get('selected_condition_id') or report.get('selected_condition_id') or ''}`",
            f"- Selected market slug: `{settings.get('selected_market_slug') or report.get('selected_market_slug') or ''}`",
            "- Single-market primary ranking remains condition_id-scoped. Sibling/event rows are context only.",
            "",
            "## Funding",
            "",
            f"- Funding trace mode: `{settings.get('funding_trace_mode') or report.get('fundingTraceMode') or ''}`",
            f"- Funding evidence interpretation: {report.get('fundingEvidenceInterpretation') or 'Funding unavailable is unknown, not none.'}",
            "",
            "## Final Display Tiers",
            "",
        ]
    )
    for tier, count in tier_counts.items():
        lines.append(f"- `{tier}`: {count}")
    lines.extend(["", "## Top Demotion Reasons", ""])
    if demotion_reasons:
        for item in demotion_reasons:
            lines.append(f"- {item['count']}x: {item['reason']}")
    else:
        lines.append("- No demotion reasons recorded.")
    lines.extend(["", "## Candidate Rows", ""])
    for row in rows[:60]:
        lines.append(
            "- "
            f"`{row.get('finalDisplayTier')}` "
            f"score={row.get('eventForensicScore')} "
            f"current={row.get('currentModelScore')} {row.get('currentModelSeverity')} "
            f"wallet=`{row.get('wallet')}` "
            f"notional={row.get('notionalUsd')} "
            f"reason={row.get('finalTierReason')}"
        )
    if len(rows) > 60:
        lines.append(f"- ... {len(rows) - 60} additional rows in candidate_trades.csv/json")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `primary_event_forensic` rows are the rows shown in the primary Event Forensic trade list.",
            f"- `{WEAK_HISTORY_NEAR_CERTAINTY_REVIEW_REQUIRED_TIER}` rows matched the approved weak-history near-certainty later-win placement policy and remain in exports/candidate audit.",
            "- `current_model_*_demoted` rows were visible to the current/base model but did not survive Event Forensic primary review.",
            "- `not_flagged_candidate` rows are exported so analysts can see the full selected-market candidate stack.",
            "- Funding disabled/cache-miss rows must be interpreted as funding `unknown`, not clean funding.",
        ]
    )
    return "\n".join(lines) + "\n"


def _runtime_profile_text(report: dict[str, object]) -> str:
    event = report.get("event") or {}
    summary = report.get("summary") or {}
    settings = report.get("analysis_settings") or {}
    performance = report.get("performance") or {}
    lines = [
        "InsPoly Event Forensic Runtime Profile",
        f"Generated at: {report.get('generated_at', '')}",
        f"Status: {report.get('status', 'unknown')}",
        f"Event: {event.get('title', 'Unknown event')}",
        f"Analysis scope: {_analysis_scope_label(str(report.get('analysis_scope') or settings.get('analysis_scope') or 'event'))}",
        f"Selected condition: {report.get('selected_condition_id') or settings.get('selected_condition_id') or ''}",
        f"Visible threshold: ${settings.get('min_notional', '0.00')}",
        f"Candidate trades: {summary.get('candidate_trade_count', 0)}",
        f"Candidate wallets: {performance.get('candidate_wallet_count', 0)}",
        f"Funding trace mode: {performance.get('fundingTraceMode', performance.get('funding_trace_mode', 'live_rpc'))}",
        f"Funding requests: {performance.get('funding_request_count', 0)}",
        f"Wallet contexts loaded: {performance.get('wallet_context_count', 0)}",
        "",
        "Stage timings:",
        f"- resolve_input_seconds: {float(performance.get('resolve_input_seconds') or 0.0):.2f}s",
        f"- collect_event_trades_seconds: {float(performance.get('collect_event_trades_seconds') or 0.0):.2f}s",
        f"- prefetch_wallet_context_seconds: {float(performance.get('prefetch_wallet_context_seconds') or 0.0):.2f}s",
        f"- prepare_candidate_context_seconds: {float(performance.get('prepare_candidate_context_seconds') or 0.0):.2f}s",
        f"- prefetch_funding_context_seconds: {float(performance.get('prefetch_funding_context_seconds') or 0.0):.2f}s",
        f"- score_candidates_seconds: {float(performance.get('score_candidates_seconds') or 0.0):.2f}s",
        f"- collect_price_history_seconds: {float(performance.get('collect_price_history_seconds') or 0.0):.2f}s",
        f"- related_market_scan_seconds: {float(performance.get('related_market_scan_seconds') or 0.0):.2f}s",
        f"- assemble_report_rows_seconds: {float(performance.get('assemble_report_rows_seconds') or 0.0):.2f}s",
        f"- total_seconds: {float(performance.get('total_seconds') or 0.0):.2f}s",
        "",
        "Trade collection reporting:",
        f"- trade_collection_market_total: {performance.get('trade_collection_market_total', 0)}",
        f"- trade_collection_market_completed: {performance.get('trade_collection_market_completed', 0)}",
        f"- trade_collection_raw_trade_rows: {performance.get('trade_collection_raw_trade_rows', 0)}",
        f"- trade_collection_truncated_markets: {performance.get('trade_collection_truncated_markets', performance.get('truncated_market_count', 0))}",
        f"- trade_collection_risk_class: {performance.get('trade_collection_risk_class', '')}",
        f"- single_market_sibling_context_count: {performance.get('single_market_sibling_context_count', 0)}",
        "",
        "Concurrency:",
        f"- market_fetch_workers: {performance.get('market_fetch_workers', 0)}",
        f"- wallet_prefetch_workers: {performance.get('wallet_prefetch_workers', 0)}",
        f"- funding_prefetch_workers: {performance.get('funding_prefetch_workers', 0)}",
        f"- price_history_workers: {performance.get('price_history_workers', 0)}",
    ]
    funding_interpretation = str(
        performance.get("fundingEvidenceInterpretation")
        or performance.get("funding_evidence_interpretation")
        or ""
    ).strip()
    if funding_interpretation:
        lines.append(f"- funding_evidence_interpretation: {funding_interpretation}")
    funding_disabled_reason = str(
        performance.get("fundingTraceDisabledReason")
        or performance.get("funding_trace_disabled_reason")
        or ""
    ).strip()
    if funding_disabled_reason:
        lines.append(f"- funding_trace_disabled_reason: {funding_disabled_reason}")
    funding_reason = str(performance.get("funding_rpc_disabled_reason") or "").strip()
    if funding_reason:
        lines.append(f"- funding_rpc_disabled_reason: {funding_reason}")
    nonce_reason = str(performance.get("polygon_nonce_disabled_reason") or "").strip()
    if nonce_reason:
        lines.append(f"- polygon_nonce_disabled_reason: {nonce_reason}")
    return "\n".join(lines) + "\n"


def _normalize_analysis_scope(scope: str | None, *, resolved: ResolvedEvent | None = None) -> str:
    text = str(scope or "").strip().lower()
    if not text:
        return "market" if resolved is not None and resolved.source_condition_id else "event"
    if text not in {"event", "market"}:
        raise ValueError("Analysis scope must be 'event' or 'market'.")
    return text


def _analysis_scope_label(scope: str) -> str:
    return "Single market" if scope == "market" else "Whole event"


def _analysis_scope_subject(scope: str, selected_market_title: str | None = None) -> str:
    if scope == "market":
        market_title = str(selected_market_title or "").strip()
        if market_title:
            return f"the selected child market ({market_title})"
        return "the selected child market"
    return "this event"


def _analysis_scope_context_phrase(scope: str) -> str:
    return "selected-market context" if scope == "market" else "event context"


def _resolve_selected_child_market(
    event_markets: dict[str, Market],
    selected_condition_id: str | None = None,
    selected_market_slug: str | None = None,
) -> Market | None:
    condition_id = str(selected_condition_id or "").strip()
    market_slug = str(selected_market_slug or "").strip()
    if condition_id:
        return event_markets.get(condition_id)
    if market_slug:
        for market in event_markets.values():
            if market.slug == market_slug:
                return market
    return None


def _resolve_analysis_scope_context(
    resolved: ResolvedEvent,
    *,
    analysis_scope: str | None,
    selected_condition_id: str | None,
    selected_market_slug: str | None,
    require_selection: bool = True,
) -> AnalysisScopeContext:
    normalized_scope = _normalize_analysis_scope(analysis_scope, resolved=resolved)
    resolved_condition_id = str(selected_condition_id or "").strip() or None
    resolved_market_slug = str(selected_market_slug or "").strip() or None
    selected_market: Market | None = None
    analysis_markets = dict(resolved.markets)

    if normalized_scope == "market":
        if not resolved_condition_id and not resolved_market_slug:
            resolved_condition_id = resolved.source_condition_id or None
            resolved_market_slug = resolved.source_market_slug or None
        if not resolved_condition_id and not resolved_market_slug:
            if require_selection:
                raise ValueError("Single-market analysis requires an exact child-market condition ID or slug.")
        else:
            selected_market = _resolve_selected_child_market(
                resolved.markets,
                selected_condition_id=resolved_condition_id,
                selected_market_slug=resolved_market_slug,
            )
            if selected_market is None:
                raise ValueError("Selected child market does not belong to resolved event")
            resolved_condition_id = selected_market.condition_id
            resolved_market_slug = selected_market.slug or resolved_market_slug
            analysis_markets = {selected_market.condition_id: selected_market}
    else:
        resolved_condition_id = None
        resolved_market_slug = None

    return AnalysisScopeContext(
        analysis_scope=normalized_scope,
        analysis_markets=analysis_markets,
        selected_market=selected_market,
        selected_condition_id=resolved_condition_id,
        selected_market_slug=resolved_market_slug,
        selected_market_title=selected_market.question if selected_market is not None else None,
    )


def _analysis_scope_metadata(
    resolved: ResolvedEvent,
    scope_context: AnalysisScopeContext,
) -> dict[str, object]:
    return {
        "analysis_scope": scope_context.analysis_scope,
        "selected_condition_id": scope_context.selected_condition_id,
        "selected_market_slug": scope_context.selected_market_slug,
        "selected_market_title": scope_context.selected_market_title,
        "parent_event_slug": resolved.event_slug,
    }


def _scope_product_metadata(
    resolved: ResolvedEvent,
    scope_context: AnalysisScopeContext,
    *,
    include_related_markets: bool,
) -> dict[str, object]:
    selected_scope = scope_context.analysis_scope == "market"
    product_scope = "selected_market" if selected_scope else "whole_event"
    selected_market_question = scope_context.selected_market_title or ""
    if selected_scope:
        scope_explanation = (
            "Selected-market report: primary scoring and ranking use only the selected market. "
            "Related or sibling markets are context-only unless whole-event scope is explicitly selected."
        )
    else:
        scope_explanation = (
            "Whole-event report: primary scoring and ranking use the explicitly loaded event markets. "
            "Related case-family markets can contribute only because whole-event scope is active."
        )
    return {
        "analysisScope": product_scope,
        "primaryScoringScope": product_scope,
        "selectedMarketSlug": scope_context.selected_market_slug or "",
        "selectedMarketQuestion": selected_market_question,
        "eventSlug": resolved.event_slug,
        "relatedMarketsContextIncluded": bool(include_related_markets),
        "siblingMarketsPrimaryScored": bool(not selected_scope and include_related_markets),
        "scopeExplanation": scope_explanation,
    }


def _scope_summary_metadata(
    resolved: ResolvedEvent,
    scope_context: AnalysisScopeContext,
    *,
    include_related_markets: bool,
) -> dict[str, object]:
    return dict(
        _scope_product_metadata(
            resolved,
            scope_context,
            include_related_markets=include_related_markets,
        )
    )


def _scope_note(scope_context: AnalysisScopeContext) -> str:
    if scope_context.analysis_scope == "market":
        market_title = scope_context.selected_market_title or "the selected child market"
        condition_id = scope_context.selected_condition_id or "Unknown"
        return (
            f"This is a single-market report for {market_title} ({condition_id}). "
            "Primary rankings only use the selected child market; sibling event markets and external related markets "
            "are shown as enrichment only when available."
        )
    return (
        "This is an event-wide report. Trades, wallets, and linked-wallet groups from the resolved event "
        "are ranked together; when related markets are enabled, closely matched sibling events can also be "
        "added to the primary case-family search."
    )


def _empty_state_note(
    *,
    analysis_scope: str,
    selected_market_title: str | None,
    candidate_trade_count: int,
) -> str:
    if candidate_trade_count > 0:
        return ""
    if analysis_scope == "market":
        market_label = selected_market_title or "selected market"
        return f"No candidate trades found for {market_label} under the current minimum trade size."
    return "No candidate trades found under the current minimum trade size."


def _scope_filter_trades(
    trades: list[Trade],
    *,
    selected_condition_id: str | None = None,
) -> list[Trade]:
    condition_id = str(selected_condition_id or "").strip()
    if not condition_id:
        return list(trades)
    return [trade for trade in trades if trade.condition_id == condition_id]


def _scope_filter_cases(
    cases: list[FlaggedCase],
    *,
    selected_condition_id: str | None = None,
) -> list[FlaggedCase]:
    condition_id = str(selected_condition_id or "").strip()
    if not condition_id:
        return list(cases)
    return [case for case in cases if case.trade.condition_id == condition_id]


def _scope_filter_wallet_history_trades(
    trades: list[Trade],
    *,
    all_event_condition_ids: set[str],
    selected_condition_id: str | None = None,
) -> list[Trade]:
    condition_id = str(selected_condition_id or "").strip()
    if not condition_id:
        return list(trades)
    return [
        trade
        for trade in trades
        if trade.condition_id == condition_id or trade.condition_id not in all_event_condition_ids
    ]


def _scope_filter_wallet_clusters(
    clusters: list[dict[str, object]],
    *,
    selected_condition_id: str | None = None,
) -> list[dict[str, object]]:
    condition_id = str(selected_condition_id or "").strip()
    if not condition_id:
        return list(clusters)
    return [
        cluster
        for cluster in clusters
        if str(cluster.get("selectedConditionId") or "") == condition_id
    ]


def _sibling_market_activity_lookup(
    wallet_cache: dict[str, tuple[object, list[Trade], WalletPerformance]],
    *,
    all_event_condition_ids: set[str],
    selected_condition_id: str | None = None,
) -> dict[str, dict[str, int]]:
    condition_id = str(selected_condition_id or "").strip()
    if not condition_id:
        return {}
    rows: dict[str, dict[str, int]] = {}
    for wallet, (_inspection, history, _performance) in wallet_cache.items():
        sibling_trades = [
            trade
            for trade in history
            if trade.condition_id in all_event_condition_ids and trade.condition_id != condition_id
        ]
        if not sibling_trades:
            continue
        rows[wallet] = {
            "otherEventMarketTrades": len(sibling_trades),
            "siblingMarketActivityCount": len({trade.condition_id for trade in sibling_trades}),
        }
    return rows


def _cluster_summary(
    *,
    analysis_scope: str,
    base_summary: str,
    sibling_wallet_count: int,
) -> str:
    if analysis_scope == "market" and sibling_wallet_count > 0:
        return (
            f"{base_summary} {sibling_wallet_count} linked wallet(s) also traded sibling child markets. "
            "Sibling-market activity is context only and does not change the single-market score."
        )
    return base_summary


def _report_analysis_scope(report: dict[str, object]) -> str:
    return str(
        report.get("analysis_scope")
        or (report.get("analysis_settings") or {}).get("analysis_scope")
        or "event"
    )


def _report_selected_condition_id(report: dict[str, object]) -> str | None:
    value = report.get("selected_condition_id")
    if value:
        return str(value)
    settings = report.get("analysis_settings") or {}
    fallback = settings.get("selected_condition_id")
    return str(fallback) if fallback else None


def _report_selected_market_slug(report: dict[str, object]) -> str | None:
    value = report.get("selected_market_slug")
    if value:
        return str(value)
    settings = report.get("analysis_settings") or {}
    fallback = settings.get("selected_market_slug")
    return str(fallback) if fallback else None


def _report_selected_market_title(report: dict[str, object]) -> str | None:
    value = report.get("selected_market_title")
    return str(value) if value else None


def _report_scope_product_metadata(report: dict[str, object]) -> dict[str, object]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    settings = report.get("analysis_settings") if isinstance(report.get("analysis_settings"), dict) else {}
    event = report.get("event") if isinstance(report.get("event"), dict) else {}
    legacy_scope = _report_analysis_scope(report)
    product_scope = str(
        report.get("analysisScope")
        or summary.get("analysisScope")
        or ("selected_market" if legacy_scope == "market" else "whole_event")
    )
    primary_scope = str(
        report.get("primaryScoringScope")
        or summary.get("primaryScoringScope")
        or settings.get("primary_scoring_scope")
        or product_scope
    )
    related_context = report.get("relatedMarketsContextIncluded", summary.get("relatedMarketsContextIncluded"))
    if related_context is None:
        related_context = bool(report.get("related_markets") or [])
    sibling_primary = report.get("siblingMarketsPrimaryScored", summary.get("siblingMarketsPrimaryScored"))
    if sibling_primary is None:
        sibling_primary = bool(legacy_scope == "event" and settings.get("include_related_markets", False))
    explanation = str(report.get("scopeExplanation") or summary.get("scopeExplanation") or report.get("scope_note") or "")
    if not explanation:
        explanation = (
            "Selected-market report: primary scoring and ranking use only the selected market; related or sibling markets are context-only."
            if legacy_scope == "market"
            else "Whole-event report: primary scoring and ranking use the explicitly loaded event markets."
        )
    selected_market_title = _report_selected_market_title(report) or ""
    return {
        "analysisScope": product_scope,
        "primaryScoringScope": primary_scope,
        "selectedMarketSlug": str(
            report.get("selectedMarketSlug")
            or summary.get("selectedMarketSlug")
            or _report_selected_market_slug(report)
            or ""
        ),
        "selectedMarketQuestion": str(
            report.get("selectedMarketQuestion")
            or summary.get("selectedMarketQuestion")
            or selected_market_title
        ),
        "eventSlug": str(
            report.get("eventSlug")
            or summary.get("eventSlug")
            or event.get("slug")
            or report.get("parent_event_slug")
            or ""
        ),
        "relatedMarketsContextIncluded": bool(related_context),
        "siblingMarketsPrimaryScored": bool(sibling_primary),
        "scopeExplanation": explanation,
    }


def _report_resolution_status(report: dict[str, object]) -> str:
    eligibility = report.get("eligibility") or {}
    event = report.get("event") or {}
    return str(
        eligibility.get("status")
        or event.get("resolutionStatus")
        or ("eligible" if event.get("completed") else "preview_only")
    )


def _report_has_outcome_context(report: dict[str, object]) -> bool:
    eligibility = report.get("eligibility") or {}
    event = report.get("event") or {}
    summary = report.get("summary") or {}
    if "outcome_context_available" in summary:
        return bool(summary.get("outcome_context_available"))
    if "outcomeContextAvailable" in event:
        return bool(event.get("outcomeContextAvailable"))
    if "outcome_context_available" in eligibility:
        return bool(eligibility.get("outcome_context_available"))
    return _report_resolution_status(report) in {"eligible", "partial"}


def _report_resolution_status_label(report: dict[str, object]) -> str:
    status = _report_resolution_status(report)
    if status == "eligible":
        return "Fully resolved"
    if status == "partial":
        return "Partially resolved"
    if status == "live":
        return "Live event"
    if status == "unresolved":
        return "Outcome pending"
    if status == "preview_only":
        return "Preview only"
    return status.replace("_", " ").title()


def _extract_polymarket_slug(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if "://" not in text:
        return text.strip("/").split("/")[-1]
    parsed = urlparse(text)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return ""
    if parts[0] in {"event", "market"} and len(parts) >= 2:
        return unquote(parts[1])
    return unquote(parts[-1])


def _extract_polymarket_resource_kind(value: str) -> str | None:
    text = value.strip()
    if not text or "://" not in text:
        return None
    parsed = urlparse(text)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None
    if parts[0] in {"event", "market"}:
        return parts[0]
    if len(parts) >= 2 and parts[1] in {"event", "market"}:
        return parts[1]
    return None


def _wallet_trade_replay_metrics(wallet_history_trades: list[Trade]) -> dict[str, dict[str, object]]:
    ordered = sorted(wallet_history_trades, key=lambda item: (item.timestamp, item.trade_id))
    if not ordered:
        return {}

    visible_history_count = len(ordered)
    family_keys = {trade.trade_id: _event_family_key(trade) for trade in ordered}
    family_total_counts: dict[str, int] = {}
    for family_key in family_keys.values():
        family_total_counts[family_key] = family_total_counts.get(family_key, 0) + 1

    prior_family_counts: dict[str, int] = {}
    prior_family_markets: dict[str, set[str]] = {}
    result: dict[str, dict[str, object]] = {}
    for index, trade in enumerate(ordered):
        family_key = family_keys[trade.trade_id]
        prior_trade = ordered[index - 1] if index > 0 else None
        next_trade = ordered[index + 1] if index + 1 < len(ordered) else None

        prior_gap_days = None
        if prior_trade is not None:
            prior_gap_days = max((trade.timestamp - prior_trade.timestamp).total_seconds() / 86400.0, 0.0)

        observed_until = next_trade.timestamp if next_trade is not None else datetime.now(UTC)
        observed_post_gap_days = None
        if observed_until > trade.timestamp:
            observed_post_gap_days = max((observed_until - trade.timestamp).total_seconds() / 86400.0, 0.0)

        prior_market_set = prior_family_markets.get(family_key, set())
        result[trade.trade_id] = {
            "prior_wallet_gap_days": prior_gap_days,
            "observed_post_trade_gap_days": observed_post_gap_days,
            "family_key": family_key,
            "prior_family_trade_count": prior_family_counts.get(family_key, 0),
            "prior_family_market_count": len(prior_market_set),
            "event_family_share": family_total_counts.get(family_key, 0) / max(1, visible_history_count),
        }
        prior_family_counts[family_key] = prior_family_counts.get(family_key, 0) + 1
        prior_family_markets.setdefault(family_key, set()).add(trade.condition_id)
    return result


def _review_domain_for_trade(trade: Trade, focus_markets: dict[str, Market]) -> str:
    domain = _domain_for_trade(trade, focus_markets)
    if domain != "Other":
        return domain
    text = f"{trade.title} {trade.slug} {trade.event_slug}".lower()
    if any(keyword in text for keyword in EVENT_FORENSIC_SPORTS_KEYWORDS):
        return "Sports"
    if any(keyword in text for keyword in ("movie", "oscars", "grammy", "song", "album", "celebrity")):
        return "Entertainment"
    if any(keyword in text for keyword in ("bitcoin", "ethereum", "crypto", "solana", "xrp", "token")):
        return "Crypto"
    return domain


def _wallet_review_domain_counts(
    wallet_history_trades: list[Trade],
    focus_markets: dict[str, Market],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for trade in wallet_history_trades:
        counts[_review_domain_for_trade(trade, focus_markets)] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _annotate_wallet_domain_diversity(
    case: FlaggedCase,
    *,
    wallet_history_trades: list[Trade],
    focus_markets: dict[str, Market],
    domain_counts_cache: dict[str, dict[str, int]] | None = None,
    profile: dict[str, int] | None = None,
) -> None:
    raw = case.raw_metrics
    cache_key = case.trade.wallet if domain_counts_cache is not None else ""
    if cache_key and cache_key in domain_counts_cache:
        domain_counts = domain_counts_cache[cache_key]
        if profile is not None:
            profile["cache_hits"] = int(profile.get("cache_hits", 0)) + 1
    else:
        domain_counts = _wallet_review_domain_counts(wallet_history_trades, focus_markets)
        if cache_key:
            domain_counts_cache[cache_key] = domain_counts
        if profile is not None:
            profile["cache_misses"] = int(profile.get("cache_misses", 0)) + 1
    nonzero_domains = {domain: count for domain, count in domain_counts.items() if count > 0}
    trade_domain = str(raw.get("trade_domain") or "Other")
    sports_count = int(nonzero_domains.get("Sports", 0))
    public_domain_count = sum(
        count
        for domain, count in nonzero_domains.items()
        if domain in EVENT_FORENSIC_PUBLIC_BETTING_DOMAINS
    )
    sensitive_count = sum(
        count
        for domain, count in nonzero_domains.items()
        if domain in EVENT_FORENSIC_HIGH_ASYMMETRY_DOMAINS
    )
    domain_count = len(nonzero_domains)
    raw["wallet_review_domain_profile"] = "; ".join(
        f"{domain}={count}" for domain, count in nonzero_domains.items()
    )
    raw["wallet_review_domain_count"] = str(domain_count)
    raw["wallet_sports_history_trade_count"] = str(sports_count)
    raw["wallet_public_betting_domain_trade_count"] = str(public_domain_count)
    raw["wallet_sensitive_domain_trade_count"] = str(sensitive_count)

    cross_domain_public_bettor = (
        trade_domain in EVENT_FORENSIC_HIGH_ASYMMETRY_DOMAINS
        and sports_count >= 1
        and sensitive_count >= 1
        and domain_count >= 2
    )
    raw["wallet_cross_domain_public_bettor_flag"] = "Yes" if cross_domain_public_bettor else "No"
    if cross_domain_public_bettor:
        raw["wallet_cross_domain_public_bettor_reason"] = (
            "Wallet history includes unrelated sports/public-betting activity as well as the current "
            f"{trade_domain} market family; this weakens a one-off insider-style interpretation unless "
            "independent hard evidence is present."
        )
    else:
        raw["wallet_cross_domain_public_bettor_reason"] = ""


def _parse_dt(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _analysis_time_bounds(resolved: ResolvedEvent) -> tuple[datetime | None, datetime | None]:
    start_candidates = [
        _parse_dt(resolved.event_payload.get("startDate")),
        _parse_dt(resolved.event_payload.get("creationDate")),
        _parse_dt(resolved.event_payload.get("createdAt")),
        _parse_dt(resolved.event_end_date),
    ]
    end_candidates = [
        _parse_dt(resolved.event_end_date),
        _parse_dt(resolved.event_payload.get("endDate")),
        _parse_dt(resolved.event_payload.get("closedTime")),
    ]
    for payload in resolved.market_payloads.values():
        start_candidates.extend(
            [
                _parse_dt(payload.get("startDate")),
                _parse_dt(payload.get("startDateIso")),
                _parse_dt(payload.get("creationDate")),
                _parse_dt(payload.get("createdAt")),
            ]
        )
        end_candidates.extend(
            [
                _parse_dt(payload.get("endDate")),
                _parse_dt(payload.get("endDateIso")),
                _parse_dt(payload.get("closedTime")),
            ]
        )
    starts = [item for item in start_candidates if item is not None]
    ends = [item for item in end_candidates if item is not None]
    return (min(starts) if starts else None, max(ends) if ends else None)


def _event_closed_for_report(resolved: ResolvedEvent) -> bool:
    closed_markets = [bool(payload.get("closed", False)) for payload in resolved.market_payloads.values()]
    return bool(resolved.event_closed or (closed_markets and all(closed_markets)))


def _eligibility_has_outcome_context(eligibility: dict[str, object]) -> bool:
    if "outcome_context_available" in eligibility:
        return bool(eligibility.get("outcome_context_available"))
    return str(eligibility.get("status") or "") in {"eligible", "partial"}


def _metric_float(value: object) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text or text == "First visible trade":
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _metric_int(value: object) -> int:
    parsed = _metric_float(value)
    return int(parsed) if parsed is not None else 0


def _funding_evidence_grade_from_raw(raw: dict[str, object]) -> str:
    return str(raw.get("funding_evidence_grade") or raw.get("fundingEvidenceGrade") or "").strip()


def _has_proxy_funding_grade(raw: dict[str, object]) -> bool:
    grade = _funding_evidence_grade_from_raw(raw)
    if grade in PROXY_FUNDING_EVIDENCE_GRADES:
        return True
    return bool(raw.get("cex_proxy_cluster_flag") == "Yes" and not str(raw.get("funding_graph_key_strict") or "").strip())


def _repricing_source_quality_from_raw(raw: dict[str, object]) -> str:
    return str(raw.get("repricing_source_quality") or raw.get("repricingSourceQuality") or "").strip()


def _wallet_repricing_source_quality(items: list[dict[str, object]]) -> tuple[str, str]:
    qualities: list[str] = []
    reasons: list[str] = []
    for item in items:
        raw = item.get("rawMetrics") if isinstance(item.get("rawMetrics"), dict) else {}
        quality = ""
        if isinstance(raw, dict):
            quality = _repricing_source_quality_from_raw(raw)
            reasons.extend(
                _text_values(
                    raw.get("repricing_source_quality_reasons")
                    or raw.get("repricingSourceQualityReasons")
                )
            )
        if not quality:
            quality = str(
                item.get("repricingSourceQuality")
                or item.get("repricing_source_quality")
                or ""
            ).strip()
        if quality:
            qualities.append(quality)
        reasons.extend(
            _text_values(
                item.get("repricingSourceQualityReasons")
                or item.get("repricing_source_quality_reasons")
            )
        )

    normalized = [
        quality.lower().replace(" ", "_").replace("-", "_")
        for quality in qualities
        if str(quality or "").strip()
    ]
    if not normalized:
        return "", "; ".join(_dedupe_labels(reasons))
    for candidate in (
        REPRICING_SOURCE_QUALITY_MECHANICAL,
        REPRICING_SOURCE_QUALITY_WEAK,
        REPRICING_SOURCE_QUALITY_STRONG,
        REPRICING_SOURCE_QUALITY_NONE,
    ):
        if candidate in normalized:
            return candidate, "; ".join(_dedupe_labels(reasons))
    return normalized[0], "; ".join(_dedupe_labels(reasons))


def _suspicious_funding_quality_from_raw(raw: dict[str, object]) -> str:
    return str(raw.get("suspiciousFundingQuality") or raw.get("suspicious_funding_quality") or "").strip()


def _suspicious_funding_quality_eligible(raw: dict[str, object]) -> bool:
    return str(raw.get("suspiciousFundingHardEvidenceEligible") or "").strip() == "Yes"


def _wallet_suspicious_funding_quality(items: list[dict[str, object]]) -> tuple[str, str, str]:
    quality_rank = {
        SUSPICIOUS_FUNDING_QUALITY_STRONG: 4,
        SUSPICIOUS_FUNDING_QUALITY_MODERATE: 3,
        "weak": 2,
        "none": 1,
        "unknown": 0,
    }
    best_quality = ""
    reasons: list[str] = []
    eligible = False
    for item in items:
        raw = item.get("rawMetrics") if isinstance(item.get("rawMetrics"), dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        quality = (
            str(item.get("suspiciousFundingQuality") or "").strip()
            or _suspicious_funding_quality_from_raw(raw)
        )
        if quality and quality_rank.get(quality, -1) > quality_rank.get(best_quality, -1):
            best_quality = quality
        if _suspicious_funding_quality_eligible(raw) or str(item.get("suspiciousFundingHardEvidenceEligible") or "").strip() == "Yes":
            eligible = True
        reasons.extend(
            _text_values(
                item.get("suspiciousFundingQualityReasons")
                or raw.get("suspiciousFundingQualityReasons")
                or raw.get("suspicious_funding_quality_reasons")
            )
        )
    return best_quality, "; ".join(_dedupe_labels(reasons)), "Yes" if eligible else "No"


def _first_payload_value(items: list[dict[str, object]], key: str, raw_key: str) -> object:
    for item in items:
        value = item.get(key)
        if value not in (None, ""):
            return value
        raw = item.get("rawMetrics") if isinstance(item.get("rawMetrics"), dict) else {}
        value = raw.get(raw_key) if isinstance(raw, dict) else None
        if value not in (None, ""):
            return value
    return ""


def _max_payload_int(items: list[dict[str, object]], *keys: str) -> int:
    values: list[int] = []
    for item in items:
        raw = item.get("rawMetrics") if isinstance(item.get("rawMetrics"), dict) else {}
        for key in keys:
            value = item.get(key)
            if value in (None, "") and isinstance(raw, dict):
                value = raw.get(key)
            parsed = _metric_int(value)
            if parsed > 0:
                values.append(parsed)
    return max(values) if values else 0


def _profile_age_days(joined_at: str, as_of: datetime) -> int | str:
    if not joined_at:
        return ""
    try:
        joined = datetime.fromisoformat(joined_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if joined.tzinfo is None:
        joined = joined.replace(tzinfo=UTC)
    return max(0, int((as_of - joined).total_seconds() // 86400))


def _poor_wallet_history(raw: dict[str, object]) -> bool:
    sample_size = _metric_int(raw.get("wallet_economic_sample_size"))
    win_rate = _metric_float(raw.get("wallet_economic_win_rate"))
    if sample_size < POOR_HISTORY_SAMPLE_MIN or win_rate is None:
        return False
    return win_rate <= POOR_HISTORY_WIN_RATE_MAX


def _has_independent_forensic_proof(
    raw: dict[str, object],
    *,
    price: float,
    winner_rank: object,
) -> bool:
    if _strict_shared_funding_has_distinct_wallet_support(raw):
        return True
    if raw.get("split_wallet_pattern_flag") == "Yes":
        return True
    if _suspicious_funding_quality_eligible(raw) and not _has_proxy_funding_grade(raw):
        return True
    if raw.get("beat_consensus_flag") == "Yes" or raw.get("favorable_repricing_flag") == "Yes":
        weak_repricing_only = (
            raw.get("beat_consensus_flag") != "Yes"
            and raw.get("favorable_repricing_flag") == "Yes"
            and _high_impact_timing_or_repricing(raw)
            and _repricing_source_quality_from_raw(raw)
            in {REPRICING_SOURCE_QUALITY_WEAK, REPRICING_SOURCE_QUALITY_MECHANICAL}
        )
        if not weak_repricing_only:
            return True
    try:
        rank_value = int(winner_rank) if winner_rank is not None else None
    except (TypeError, ValueError):
        rank_value = None
    return bool(price <= 0.35 and rank_value is not None and rank_value <= 6)


def _has_independent_hard_evidence(
    raw: dict[str, object],
    *,
    price: float,
    winner_rank: object,
) -> bool:
    if raw.get("hardEvidenceReviewTier") == HARD_EVIDENCE_REVIEW_TIER:
        return True
    strict_shared_funding = _strict_shared_funding_has_distinct_wallet_support(raw)
    if raw.get("split_wallet_pattern_flag") == "Yes" and strict_shared_funding:
        return True
    if strict_shared_funding:
        return True
    if _suspicious_funding_quality_eligible(raw) and not _has_proxy_funding_grade(raw):
        return True
    try:
        rank_value = int(winner_rank) if winner_rank is not None else None
    except (TypeError, ValueError):
        rank_value = None
    if price <= 0.35 and rank_value is not None and rank_value <= 6:
        return True
    if raw.get("reactivated_after_dormancy_flag") == "Yes" and raw.get("opening_exposure_flag") == "Yes":
        return True
    return False


def _trade_public_power_user_flag(raw: dict[str, object]) -> bool:
    return (
        _metric_int(raw.get("wallet_traded_market_count") or raw.get("walletTotalPredictions"))
        > PUBLIC_POWER_USER_TOTAL_PREDICTIONS_MIN
        or _metric_int(raw.get("wallet_recent_trade_count") or raw.get("walletLoadedHistoryTradeCount"))
        > PUBLIC_POWER_USER_HISTORY_TRADE_MIN
        or _metric_int(raw.get("wallet_unique_market_count") or raw.get("walletLoadedUniqueMarketCount"))
        >= PUBLIC_POWER_USER_UNIQUE_MARKET_MIN
    )


def _has_concrete_public_user_escape_evidence(raw: dict[str, object]) -> bool:
    if raw.get("hardEvidenceReviewTier") == HARD_EVIDENCE_REVIEW_TIER:
        return True
    if _strict_shared_funding_has_distinct_wallet_support(raw):
        return True
    if raw.get("split_wallet_pattern_flag") == "Yes":
        return True
    if _suspicious_funding_quality_eligible(raw) and not _has_proxy_funding_grade(raw):
        return True
    return False


def _should_downgrade_high_impact_repricing_only(
    raw: dict[str, object],
    *,
    price: float,
    winner_rank: object,
) -> bool:
    quality = _repricing_source_quality_from_raw(raw)
    if quality not in {REPRICING_SOURCE_QUALITY_WEAK, REPRICING_SOURCE_QUALITY_MECHANICAL}:
        return False
    if raw.get("favorable_repricing_flag") != "Yes":
        return False
    if raw.get("beat_consensus_flag") == "Yes":
        return False
    if not _high_impact_timing_or_repricing(raw):
        return False
    return not _has_independent_hard_evidence(raw, price=price, winner_rank=winner_rank)


def _strict_shared_funding_has_distinct_wallet_support(raw: dict[str, object]) -> bool:
    if raw.get("shared_funding_source_flag") != "Yes":
        return False
    if raw.get("cex_proxy_cluster_flag") == "Yes":
        return False
    if not str(raw.get("funding_graph_key_strict") or "").strip():
        return False
    wallet_count = _metric_int(
        raw.get("shared_funding_source_wallet_count")
        or raw.get("sharedFundingSourceWalletCount")
        or raw.get("groupedCandidateWalletCount")
    )
    return wallet_count >= 2


def _wallet_hard_evidence_attribution(
    items: list[dict[str, object]],
) -> tuple[list[str], list[str], list[str]]:
    hard_sources: list[str] = []
    source_flags: list[str] = []
    source_details: list[str] = []

    for item in items:
        raw = item.get("rawMetrics") if isinstance(item.get("rawMetrics"), dict) else {}
        flags = _payload_flag_set(item.get("eventForensicFlags"))
        price = _payload_model_probability(item, raw)
        winner_rank_value = _metric_int(item.get("winnerRank"))
        later_won = bool(item.get("laterWon"))
        saved_hard_sources = _text_values(item.get("hardEvidenceSources")) or _text_values(
            raw.get("hardEvidenceSources")
        )
        saved_hard_details = _text_values(raw.get("hardEvidencePrimaryReason"))
        if saved_hard_sources:
            hard_sources.extend(saved_hard_sources)
            source_flags.extend(saved_hard_sources)
            source_details.extend(saved_hard_details)
            continue

        def add_hard(label: str) -> None:
            hard_sources.append(label)
            source_flags.append(label)

        strict_shared_funding = _strict_shared_funding_has_distinct_wallet_support(raw)

        if (raw.get("split_wallet_pattern_flag") == "Yes" or "split_wallet_pattern" in flags) and strict_shared_funding:
            add_hard("split_wallet_pattern")

        shared_cluster_size = _metric_int(raw.get("shared_funding_source_cluster_size"))
        if raw.get("shared_funding_source_flag") == "Yes" or "shared_funder_cluster" in flags:
            source_flags.append("shared_funding_source")
            if shared_cluster_size:
                source_flags.append("shared_funding_cluster_size")
                source_details.append(f"shared_funding_cluster_size={shared_cluster_size}")
            if strict_shared_funding:
                hard_sources.append("strict_shared_funding_source")

        if _suspicious_funding_quality_eligible(raw) and not _has_proxy_funding_grade(raw):
            add_hard("suspicious_recent_funding")
            source_label = str(raw.get("funding_source_label") or "").strip()
            if source_label:
                source_details.append(f"suspicious_recent_funding={source_label}")
        if raw.get("recent_external_funding_flag") == "Yes" or "recent_opaque_funding" in flags:
            source_flags.append("recent_external_funding")

        if "low_probability_winner" in flags or (price <= 0.35 and winner_rank_value and winner_rank_value <= 6):
            source_flags.append("low_probability_winner")
            if price <= 0.35 and winner_rank_value and winner_rank_value <= 6:
                hard_sources.append("low_probability_early_winner")

        dormant_gap = _metric_float(raw.get("days_since_prior_wallet_trade"))
        if raw.get("reactivated_after_dormancy_flag") == "Yes" or "dormant_reactivation" in flags:
            source_flags.append("dormant_reactivation")
            if dormant_gap is not None:
                source_details.append(f"dormant_reactivation_gap_days={round(dormant_gap)}")
            if raw.get("opening_exposure_flag") == "Yes":
                hard_sources.append("dormant_wallet_reactivation")

        if (later_won and raw.get("post_trade_dormancy_flag") == "Yes") or "dormant_after_win" in flags:
            source_flags.append("dormant_after_win")

        if "early_winning_entry" in flags or (winner_rank_value and winner_rank_value <= 3):
            source_flags.append("early_winning_entry")

        beat_consensus = raw.get("beat_consensus_flag") == "Yes" or "beat_consensus" in flags
        post_entry_repricing = raw.get("favorable_repricing_flag") == "Yes" or "post_entry_repricing" in flags
        if beat_consensus:
            source_flags.append("beat_consensus")
        if post_entry_repricing:
            source_flags.append("post_entry_repricing")
        if _high_impact_timing_or_repricing(raw) and (beat_consensus or post_entry_repricing):
            source_flags.append("high_impact_timing_or_repricing")
            source_details.append(
                _high_impact_timing_or_repricing_detail(
                    item,
                    raw,
                    beat_consensus=beat_consensus,
                    post_entry_repricing=post_entry_repricing,
                )
            )

        same_side_cluster = raw.get("coordinated_cluster_signal") == "Yes" or "same_side_cluster" in flags
        if same_side_cluster:
            source_flags.append("same_side_cluster")

    return _dedupe_labels(hard_sources), _dedupe_labels(source_flags), _dedupe_labels(source_details)


def _payload_flag_set(value: object) -> set[str]:
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    text = str(value or "").strip()
    if not text:
        return set()
    return {part.strip() for part in re.split(r"[;,]", text) if part.strip()}


def _high_impact_timing_or_repricing(raw: dict[str, object]) -> bool:
    liquidity = _metric_float(raw.get("market_liquidity_usdc"))
    liquidity_ratio = _metric_float(raw.get("liquidity_ratio"))
    return bool(
        (liquidity is not None and 0 < liquidity <= 100000)
        or (liquidity_ratio is not None and liquidity_ratio >= 5.0)
    )


def _high_impact_timing_or_repricing_detail(
    item: dict[str, object],
    raw: dict[str, object],
    *,
    beat_consensus: bool,
    post_entry_repricing: bool,
) -> str:
    liquidity = _metric_float(raw.get("market_liquidity_usdc"))
    liquidity_ratio = _metric_float(raw.get("liquidity_ratio"))
    reasons: list[str] = []
    if liquidity is not None and 0 < liquidity <= 100000:
        reasons.append("low_liquidity")
    if liquidity_ratio is not None and liquidity_ratio >= 5.0:
        reasons.append("large_liquidity_share")

    triggers: list[str] = []
    if beat_consensus:
        triggers.append("beat_consensus")
    if post_entry_repricing:
        triggers.append("post_entry_repricing")

    parts = ["high_impact_timing_or_repricing"]
    if reasons:
        parts.append(f"reason={'+'.join(reasons)}")
    if triggers:
        parts.append(f"trigger={'+'.join(triggers)}")

    detail_keys = (
        ("trade_id", item.get("id")),
        ("condition_id", item.get("conditionId") or item.get("selectedConditionId")),
        ("price", item.get("price")),
        ("timestamp", item.get("timestamp")),
        ("market_liquidity_usdc", raw.get("market_liquidity_usdc")),
        ("liquidity_ratio", raw.get("liquidity_ratio")),
        ("entry_vs_consensus_15m", raw.get("entry_vs_consensus_15m")),
        ("favorable_move_15m", raw.get("favorable_move_15m")),
        ("favorable_move_1h", raw.get("favorable_move_1h")),
        ("favorable_move_4h", raw.get("favorable_move_4h")),
        ("favorable_move_24h", raw.get("favorable_move_24h")),
        ("liquidity_shock_signal", raw.get("liquidity_shock_signal")),
        ("repricing_source_quality", raw.get("repricing_source_quality") or raw.get("repricingSourceQuality")),
        (
            "repricing_source_quality_reasons",
            raw.get("repricing_source_quality_reasons") or raw.get("repricingSourceQualityReasons"),
        ),
        ("repricing_driver_trade_count", raw.get("repricing_driver_trade_count")),
        ("repricing_driver_wallet_count", raw.get("repricing_driver_wallet_count")),
        ("repricing_window_trade_count", raw.get("repricing_window_trade_count")),
        ("repricing_same_outcome_trade_count", raw.get("repricing_same_outcome_trade_count")),
        ("repricing_driven_by_single_wallet", raw.get("repricing_driven_by_single_wallet")),
        ("public_information_state", raw.get("public_information_state")),
        ("offline_timeline_matched", raw.get("offline_timeline_matched")),
        ("public_knowledge_at", raw.get("public_knowledge_at")),
    )
    for key, value in detail_keys:
        text = str(value or "").strip()
        if not text or text == "Unavailable":
            continue
        parts.append(f"{key}={text}")
    return ", ".join(parts)


def _source_trade_payloads_for_wallet_details(
    trade_payloads: list[dict[str, object]],
    wallet_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    payloads_by_id = {
        trade_id: item
        for item in trade_payloads
        if (trade_id := _payload_trade_id(item))
    }
    source_ids: list[str] = []
    seen_source_ids: set[str] = set()
    for wallet in wallet_rows:
        for detail in _text_values(wallet.get("walletHardEvidenceSourceDetails")):
            if "high_impact_timing_or_repricing" not in detail.lower():
                continue
            trade_id = _source_detail_value(detail, "trade_id")
            if not trade_id or trade_id in seen_source_ids:
                continue
            seen_source_ids.add(trade_id)
            source_ids.append(trade_id)
    return [payloads_by_id[trade_id] for trade_id in source_ids if trade_id in payloads_by_id]


def _payload_trade_id(row: dict[str, object]) -> str:
    return str(row.get("id") or row.get("tradeId") or row.get("trade_id") or "").strip()


def _text_values(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parsed = _jsonish_list(value)
        if parsed:
            return [str(item).strip() for item in parsed if str(item).strip()]
        text = value.strip()
        return [text] if text else []
    return []


def _source_detail_value(detail: str, key: str) -> str:
    wanted = key.strip().lower()
    for part in detail.split(","):
        name, separator, value = part.partition("=")
        if separator and name.strip().lower() == wanted:
            return value.strip()
    return ""


def _dedupe_labels(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _first_text(values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _wallet_hard_evidence_strength(sources: list[str], items: list[dict[str, object]]) -> str:
    saved: list[str] = []
    for item in items:
        raw = item.get("rawMetrics") if isinstance(item.get("rawMetrics"), dict) else {}
        value = str(item.get("hardEvidenceStrength") or raw.get("hardEvidenceStrength") or "").strip()
        if value:
            saved.append(value)
    if "Strong" in saved:
        return "Strong"
    if sources and len(sources) >= 2:
        return "Strong"
    if sources and sources[0] == "suspicious_recent_funding":
        for item in items:
            raw = item.get("rawMetrics") if isinstance(item.get("rawMetrics"), dict) else {}
            if _suspicious_funding_quality_from_raw(raw) == SUSPICIOUS_FUNDING_QUALITY_STRONG:
                return "Strong"
        return "Moderate"
    if sources and sources[0] in {"split_wallet_pattern", "low_probability_early_winner"}:
        return "Strong"
    if sources:
        return "Moderate"
    return "None"


def _wallet_public_power_user_label(
    *,
    public_power_user: bool,
    high_volume_event_user: bool,
    event_saturation: bool,
) -> str:
    if event_saturation:
        return "Event-saturated public power-user context"
    if public_power_user:
        return "Public power-user context"
    if high_volume_event_user:
        return "High-volume event participant context"
    return "No high-volume public-user pattern"


def _public_power_user_status(
    *,
    public_power_user: bool,
    independent_hard_evidence: bool,
    reducer_applied: bool,
) -> str:
    if not public_power_user:
        return "not_public_power_user"
    if independent_hard_evidence:
        return "public_power_user_with_hard_evidence"
    if reducer_applied:
        return "public_power_user_demoted"
    return "public_power_user_context"


def _high_volume_event_status(
    *,
    high_volume_event_user: bool,
    independent_hard_evidence: bool,
    reducer_applied: bool,
) -> str:
    if not high_volume_event_user:
        return "not_high_volume_event_user"
    if independent_hard_evidence:
        return "high_volume_event_user_with_hard_evidence"
    if reducer_applied:
        return "high_volume_event_user_demoted"
    return "high_volume_event_user_context"


def _event_saturation_status(*, event_saturation: bool, independent_hard_evidence: bool) -> str:
    if not event_saturation:
        return "not_event_saturated"
    if independent_hard_evidence:
        return "event_saturation_with_hard_evidence"
    return "event_saturation_context_only"


def _cross_domain_public_bettor_status(
    *,
    cross_domain_public_bettor: bool,
    independent_hard_evidence: bool,
) -> str:
    if not cross_domain_public_bettor:
        return "not_cross_domain_public_bettor"
    if independent_hard_evidence:
        return "cross_domain_public_bettor_with_hard_evidence"
    return "cross_domain_public_bettor_context_only"


def _wallet_primary_review_status(
    *,
    public_power_user: bool,
    high_volume_event_user: bool,
    event_saturation: bool,
    high_volume_context_gate: bool,
    independent_hard_evidence: bool,
    cross_domain_public_bettor: bool = False,
) -> str:
    if independent_hard_evidence:
        return "primary_allowed"
    if cross_domain_public_bettor:
        return "context_only_cross_domain_public_bettor"
    if high_volume_context_gate or event_saturation or public_power_user or high_volume_event_user:
        return "context_only_high_volume_public_user"
    return "primary_allowed"


def _wallet_interpretation_class(
    *,
    public_power_user: bool,
    high_volume_event_user: bool,
    event_saturation: bool,
    high_volume_context_gate: bool,
    independent_hard_evidence: bool,
    cross_domain_public_bettor: bool,
    shared_funder: bool,
    split_wallet: bool,
    bot_like: bool,
    specialist: bool,
    poor_history: bool,
) -> str:
    if (high_volume_context_gate or public_power_user or high_volume_event_user or event_saturation) and not independent_hard_evidence:
        return "high_volume_public_power_user"
    if cross_domain_public_bettor and not independent_hard_evidence:
        return "cross_domain_public_bettor"
    if split_wallet or shared_funder:
        return "cluster_or_linkage_case"
    if bot_like or specialist:
        return "bot_or_low_analyst_value"
    if independent_hard_evidence:
        return "insider_style_candidate"
    if poor_history:
        return "ambiguous_needs_review"
    return "ambiguous_needs_review"


def _insider_style_wallet_score(
    wallet_score: int,
    *,
    public_power_user: bool,
    high_volume_event_user: bool,
    event_saturation: bool,
    high_volume_context_gate: bool,
    independent_hard_evidence: bool,
    cross_domain_public_bettor: bool = False,
) -> int:
    if independent_hard_evidence:
        return wallet_score
    if cross_domain_public_bettor:
        return min(wallet_score, 45)
    if high_volume_context_gate:
        return min(wallet_score, 40)
    penalty = 0
    if public_power_user:
        penalty += 25
    if high_volume_event_user:
        penalty += 15
    if event_saturation:
        penalty += 20
    return max(0, wallet_score - penalty)


def _wallet_public_power_user_flag(
    *,
    wallet_total_predictions: int,
    wallet_loaded_history_trade_count: int,
    event_trade_count: int,
    wallet_loaded_unique_market_count: int,
    sibling_context_trades: int,
) -> bool:
    return (
        wallet_total_predictions > PUBLIC_POWER_USER_TOTAL_PREDICTIONS_MIN
        or wallet_loaded_history_trade_count > PUBLIC_POWER_USER_HISTORY_TRADE_MIN
        or event_trade_count >= PUBLIC_POWER_USER_EVENT_TRADE_MIN
        or wallet_loaded_unique_market_count >= PUBLIC_POWER_USER_UNIQUE_MARKET_MIN
        or sibling_context_trades >= HIGH_VOLUME_SIBLING_CONTEXT_MIN
    )


def _wallet_high_volume_event_user_flag(
    *,
    event_trade_count: int,
    suspicious_trade_count: int,
    winning_opening_entries: int,
    sibling_context_trades: int,
) -> bool:
    return (
        event_trade_count >= HIGH_VOLUME_EVENT_TRADE_MIN
        or suspicious_trade_count >= HIGH_VOLUME_NOTABLE_TRADE_MIN
        or winning_opening_entries >= HIGH_VOLUME_WINNING_OPENING_MIN
        or sibling_context_trades >= HIGH_VOLUME_SIBLING_CONTEXT_MIN
    )


def _wallet_event_saturation_flag(
    *,
    event_trade_count: int,
    opening_entries: int,
    winning_opening_entries: int,
) -> bool:
    return (
        event_trade_count >= EVENT_SATURATION_TRADE_MIN
        and opening_entries >= EVENT_SATURATION_OPENING_MIN
        and winning_opening_entries >= EVENT_SATURATION_WINNING_OPENING_MIN
    )


def _wallet_high_volume_context_gate(
    *,
    public_power_user: bool,
    high_volume_event_user: bool,
    event_saturation: bool,
    wallet_total_predictions: int,
    wallet_loaded_history_trade_count: int,
    event_trade_count: int,
    suspicious_trade_count: int,
    winning_opening_entries: int,
    sibling_context_trades: int,
) -> bool:
    return (
        public_power_user
        or high_volume_event_user
        or event_saturation
        or wallet_total_predictions > PUBLIC_POWER_USER_TOTAL_PREDICTIONS_MIN
        or wallet_loaded_history_trade_count > PUBLIC_POWER_USER_HISTORY_TRADE_MIN
        or event_trade_count >= HIGH_VOLUME_EVENT_TRADE_MIN
        or suspicious_trade_count >= HIGH_VOLUME_NOTABLE_TRADE_MIN
        or winning_opening_entries >= HIGH_VOLUME_WINNING_OPENING_MIN
        or sibling_context_trades >= HIGH_VOLUME_SIBLING_CONTEXT_MIN
    )


def _trade_collection_risk_class(
    *,
    truncated_market_count: int,
    collection_elapsed_seconds: float,
    analysis_market_count: int,
    total_event_market_count: int,
    selected_condition_id_present: bool,
) -> str:
    if truncated_market_count > 0 and collection_elapsed_seconds >= 30:
        return "truncated_collection_high_cost"
    if truncated_market_count > 0:
        return "truncated_collection_risk"
    if analysis_market_count > 0 and collection_elapsed_seconds / max(analysis_market_count, 1) >= 15:
        return "slow_per_market_collection"
    if selected_condition_id_present and total_event_market_count > analysis_market_count:
        return "single_market_sibling_context_reporting_risk"
    return "collection_profile_normal"


def _primary_suspicious_wallet_rows(ranked_wallets: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in ranked_wallets:
        independent_hard_evidence = bool(row.get("independentHardEvidenceFlag"))
        if row.get("walletQualityGate") == "secondary_only" and not independent_hard_evidence:
            continue
        if row.get("walletPrimaryReviewStatus") == "context_only_high_volume_public_user" and not independent_hard_evidence:
            continue
        if row.get("caseInterpretationClass") == "high_volume_public_power_user" and not independent_hard_evidence:
            continue
        if row.get("walletHighVolumeEventUserFlag") and not independent_hard_evidence:
            continue
        if row.get("walletEventSaturationFlag") and not independent_hard_evidence:
            continue
        if row.get("walletPublicPowerUserFlag") and not independent_hard_evidence:
            continue
        suspicious_count = int(row.get("suspiciousTradeCount") or 0)
        wallet_score = int(row.get("walletScore") or 0)
        if independent_hard_evidence:
            rows.append(row)
        elif suspicious_count >= 1:
            rows.append(row)
        elif wallet_score >= 45 and row.get("primaryEvidenceStatus") == "Independent evidence":
            rows.append(row)
    return rows


def _evidence_warnings(
    performance: dict[str, object],
    *,
    include_blockchain: bool,
) -> list[str]:
    warnings: list[str] = []
    trace_mode = str(performance.get("fundingTraceMode") or performance.get("funding_trace_mode") or "").strip()
    if trace_mode == FUNDING_TRACE_MODE_DISABLED:
        warnings.append("Blockchain funding trace was disabled; funding evidence is unknown, not none.")
    elif trace_mode == FUNDING_TRACE_MODE_CACHE_ONLY:
        warnings.append("Blockchain funding trace ran in cache-only mode; cache misses are unknown, not none.")
    if include_blockchain:
        health = performance.get("funding_resolver_health")
        health = health if isinstance(health, dict) else {}
        if health and not bool(health.get("fundingResolverAvailable")):
            functional_status = str(health.get("fundingResolverFunctionalStatus") or "")
            if bool(health.get("fundingResolverAuthError")):
                warnings.append(
                    "Funding evidence: not assessed because resolver unavailable (auth_error)."
                )
            elif functional_status in {"available_lightweight_only", "rate_limited_for_funding_trace"}:
                warnings.append(
                    "Funding evidence: lightweight RPC available, funding trace blocked by rate limits."
                )
            else:
                warnings.append(
                    "Funding evidence: not assessed because resolver unavailable."
                )
        funding_reason = str(performance.get("funding_rpc_disabled_reason") or "").strip()
        nonce_reason = str(performance.get("polygon_nonce_disabled_reason") or "").strip()
        if funding_reason or nonce_reason:
            detail = funding_reason or nonce_reason
            warnings.append(
                f"Blockchain linkage was requested but Polygon RPC failed ({detail}); shared-funder evidence is incomplete."
            )
    truncated_count = int(performance.get("truncated_market_count") or 0)
    if truncated_count:
        warnings.append(
            f"{truncated_count} market(s) hit the public trade pagination cap; large-trade backfill was attempted, but the market sample is still partial."
        )
    return warnings


def _market_categories(event_payload: dict[str, object], market_payload: dict[str, object]) -> list[str]:
    labels: list[str] = []
    for candidate in (event_payload.get("category"), market_payload.get("category")):
        text = str(candidate or "").strip()
        if text and text not in labels:
            labels.append(text)
    for tag in event_payload.get("tags") or []:
        if not isinstance(tag, dict):
            continue
        label = str(tag.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
    return labels or ["Uncategorized"]


def _case_family_tag_ids(event_payload: dict[str, object]) -> list[str]:
    tag_ids: list[str] = []
    for tag in event_payload.get("tags") or []:
        if not isinstance(tag, dict):
            continue
        slug = str(tag.get("slug") or "").strip().lower()
        label = str(tag.get("label") or "").strip().lower()
        if not slug or slug in GENERIC_CASE_FAMILY_TAG_SLUGS:
            continue
        if label in GENERIC_CASE_FAMILY_TAG_SLUGS:
            continue
        tag_id = str(tag.get("id") or "").strip()
        if tag_id and tag_id not in tag_ids:
            tag_ids.append(tag_id)
    return tag_ids


def _case_family_anchor_tokens(resolved: ResolvedEvent) -> set[str]:
    text = " ".join(
        [
            resolved.event_slug,
            resolved.event_title,
            *[market.question for market in resolved.markets.values()],
        ]
    )
    tokens = _meaningful_tokens(text)
    return {
        token
        for token in tokens
        if token not in GENERIC_CASE_FAMILY_TOKENS and token not in MONTH_WORDS
    }


def _case_family_event_tokens(event_payload: dict[str, object]) -> set[str]:
    parts = [
        str(event_payload.get("slug") or ""),
        str(event_payload.get("title") or ""),
    ]
    for market_payload in event_payload.get("markets") or []:
        if isinstance(market_payload, dict):
            parts.append(str(market_payload.get("slug") or ""))
            parts.append(str(market_payload.get("question") or ""))
    return _meaningful_tokens(" ".join(parts))


def _case_family_action_groups(tokens: set[str]) -> set[str]:
    return {
        group_name
        for group_name, group_tokens in CASE_FAMILY_ACTION_GROUPS.items()
        if tokens & group_tokens
    }


def _case_family_action_tokens(tokens: set[str]) -> set[str]:
    result: set[str] = set()
    for group_tokens in CASE_FAMILY_ACTION_GROUPS.values():
        result.update(tokens & group_tokens)
    return result


def _case_family_match_tokens(anchor_tokens: set[str], event_tokens: set[str]) -> list[str]:
    shared_subject_tokens = (anchor_tokens - _case_family_action_tokens(anchor_tokens)) & (
        event_tokens - _case_family_action_tokens(event_tokens)
    )
    if not shared_subject_tokens:
        return []

    anchor_groups = _case_family_action_groups(anchor_tokens)
    event_groups = _case_family_action_groups(event_tokens)
    if anchor_groups:
        shared_groups = anchor_groups & event_groups
        if not shared_groups:
            return []
        if event_tokens & CASE_FAMILY_META_MARKET_TOKENS:
            return []
        matched_actions = set()
        for group_name in shared_groups:
            matched_actions.update(event_tokens & CASE_FAMILY_ACTION_GROUPS[group_name])
        return sorted(shared_subject_tokens | matched_actions)

    shared_tokens = anchor_tokens & event_tokens
    if len(shared_tokens) < 2:
        return []
    if event_tokens & CASE_FAMILY_META_MARKET_TOKENS:
        return []
    return sorted(shared_tokens)


def _winning_outcome_from_payload(payload: dict[str, object]) -> str | None:
    if not payload or not bool(payload.get("closed", False)):
        return None
    outcomes = _jsonish_list(payload.get("outcomes"))
    prices = _jsonish_list(payload.get("outcomePrices"))
    if not outcomes or len(outcomes) != len(prices):
        return None
    resolved_pairs: list[tuple[str, Decimal]] = []
    for outcome, price in zip(outcomes, prices, strict=False):
        try:
            price_value = Decimal(str(price))
        except (InvalidOperation, TypeError, ValueError):
            continue
        resolved_pairs.append((str(outcome), price_value))
    if not resolved_pairs:
        return None
    winner, best_price = max(resolved_pairs, key=lambda item: item[1])
    return winner if best_price >= MIN_RESOLVED_OUTCOME_PRICE else None


def _jsonish_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return []
            return parsed if isinstance(parsed, list) else []
    return []


def _meaningful_tokens(text: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower())
    tokens = set()
    for token in normalized.split():
        if len(token) < 3 or token in STOPWORDS or token in MONTH_WORDS or token.isdigit():
            continue
        tokens.add(token)
    return tokens


def _family_id_from_tokens(tokens: set[str]) -> str:
    ordered = sorted(tokens)
    return "-".join(ordered[:8])


def _slug_family_id(slug: str) -> str:
    return "-".join(sorted(_meaningful_tokens(slug))[:8]) or slug


def _token_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), len(right))


def _short_wallet(value: str) -> str:
    if len(value) < 12:
        return value
    return f"{value[:6]}...{value[-4:]}"


def _trade_username(trade: Trade) -> str:
    if trade.trader_name and trade.trader_pseudonym and trade.trader_name != trade.trader_pseudonym:
        return f"{trade.trader_name} ({trade.trader_pseudonym})"
    if trade.trader_name:
        return trade.trader_name
    if trade.trader_pseudonym:
        return trade.trader_pseudonym
    return "Not available"


def _display_time(value: str) -> str:
    parsed = _parse_dt(value)
    if parsed is None:
        return value
    return parsed.astimezone().strftime("%b %d, %H:%M")


def _market_label_list(markets: list[dict[str, object]], *, limit: int) -> str:
    labels = [str(market.get("market") or "Unknown market") for market in markets[:limit]]
    remaining = len(markets) - len(labels)
    if remaining > 0:
        labels.append(f"+ {remaining} more")
    return "; ".join(labels)


def _money_label(value: object) -> str:
    try:
        amount = float(value or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"${amount:,.0f}"


def _friendly_connection_type(value: object) -> str:
    text = str(value or "").strip()
    if text == "Shared direct funder":
        return "shared funding"
    if text == "Synchronized same-side entry":
        return "tight same-side timing"
    return text.lower() or "linked behavior"


def _wallet_sample(wallets: object, *, limit: int = 4) -> str:
    wallet_list = [str(wallet) for wallet in wallets or []]
    visible = [_short_wallet(wallet) for wallet in wallet_list[:limit]]
    remaining = len(wallet_list) - len(visible)
    if remaining > 0:
        visible.append(f"+ {remaining} more")
    return ", ".join(visible) if visible else "No wallet sample available"


def _cluster_meaning_sentence(cluster: dict[str, object]) -> str:
    parts: list[str] = []
    if cluster.get("sameFunder"):
        parts.append("shared funding")
    if cluster.get("sameSideTimingPattern"):
        parts.append("same-side timing")
    if int(cluster.get("relatedMarketOverlap") or 0) > 0:
        parts.append("related-market overlap")
    if not parts:
        return "Review these wallets together because their event behavior overlaps."
    return f"Review these wallets together because the group combines {', '.join(parts)}."


def _cluster_report_line(cluster: dict[str, object], *, index: int) -> str:
    wallet_count = int(cluster.get("walletCount") or len(cluster.get("wallets") or []))
    score = int(cluster.get("clusterScore") or 0)
    sibling_count = int(cluster.get("siblingMarketWalletCount") or 0)
    sibling_note = (
        f" {sibling_count} member wallet(s) also traded sibling markets kept as context."
        if sibling_count > 0
        else ""
    )
    return (
        f"- Group {index}: {wallet_count} wallet(s) linked by "
        f"{_friendly_connection_type(cluster.get('connectionType'))}; sample: "
        f"{_wallet_sample(cluster.get('wallets'))}. Link strength {score}/100. "
        f"{_cluster_meaning_sentence(cluster)}{sibling_note}"
    )


def _human_display_note(note: str) -> str:
    text = str(note or "").strip()
    if not text:
        return ""
    text = re.sub(
        r"The app is showing the top (\d+) of (\d+) visible trade rows",
        r"Trade review list is capped at \1 of \2 threshold-cleared trade rows",
        text,
    )
    text = re.sub(
        r"the top (\d+) of (\d+) wallet rows",
        r"wallet review list is capped at \1 of \2 wallet rows",
        text,
    )
    text = re.sub(
        r"and the top (\d+) of (\d+) linked-wallet groups",
        r"linked-wallet review list is capped at \1 of \2 groups",
        text,
    )
    text = text.replace(
        "Full exports remain in the CSV files on disk.",
        "Use Open exports for the complete row set.",
    )
    text = text.replace(
        "The visible panel already includes every row that cleared the configured event-forensic threshold.",
        "The on-screen review lists include every row that cleared the configured event-forensic threshold.",
    )
    return text


def _human_wallet_summary(wallet: dict[str, object]) -> str:
    text = str(wallet.get("summary") or "").strip()
    score = int(wallet.get("walletScore") or 0)
    if text.startswith("Wallet score"):
        text = re.sub(r"^Wallet score \d+/100 with ", "", text)
        if text:
            text = text[0].upper() + text[1:]
        text = text.replace("It recorded", "It recorded")
        text = text.replace("winning opening entry/entries", "winning opening entries")
        if score and "Wallet concern score" not in text:
            text = f"{text} Wallet concern score: {score}/100."
    text = re.sub(r"sibling-event trade\(s\)", "sibling-market context trade(s)", text)
    text = text.replace(
        "but those trades are excluded from the primary wallet score.",
        "Sibling-market activity is context only and does not change the single-market score.",
    )
    return text or "This wallet is the strongest review lead in the loaded data."


def _primary_story_lines(
    report: dict[str, object],
    top_trades: list[dict[str, object]],
    top_wallets: list[dict[str, object]],
    clusters: list[dict[str, object]],
) -> dict[str, object]:
    top_wallet = top_wallets[0] if top_wallets else None
    top_cluster = clusters[0] if clusters else None
    primary_cluster = None
    if top_cluster and (top_cluster.get("sameFunder") or not top_wallet):
        primary_cluster = top_cluster

    if primary_cluster:
        wallets = [str(wallet) for wallet in primary_cluster.get("wallets") or []]
        lines = [
            (
                f"- Primary group: **{int(primary_cluster.get('walletCount') or len(wallets))} wallets** "
                f"linked by {_friendly_connection_type(primary_cluster.get('connectionType'))}."
            ),
            f"- Wallet sample: {_wallet_sample(wallets, limit=5)}.",
            f"- Why it matters: {_cluster_meaning_sentence(primary_cluster)}",
            "- Treat this as a linkage lead, not proof of common ownership, until the member wallets and funding trail are reviewed.",
        ]
        return {"type": "cluster", "wallets": set(wallets), "lines": lines}

    if top_wallet:
        wallet_short = str(top_wallet.get("walletShort") or _short_wallet(str(top_wallet.get("wallet") or "")))
        username = str(top_wallet.get("username") or "Not available")
        event_result = str(top_wallet.get("eventResult") or "").strip()
        event_trade_count = int(top_wallet.get("eventTradeCount") or 0)
        suspicious_count = int(top_wallet.get("suspiciousTradeCount") or 0)
        related_count = int(top_wallet.get("relatedMarketTradeCount") or 0)
        sibling_count = int(top_wallet.get("otherEventMarketTrades") or 0)
        evidence_bits: list[str] = []
        if str(top_wallet.get("fundingFlags") or "").startswith("Shared"):
            evidence_bits.append("shared-funding evidence")
        funding_quality_note = _suspicious_funding_quality_note(top_wallet)
        if funding_quality_note:
            evidence_bits.append(funding_quality_note)
        if related_count:
            evidence_bits.append(f"{related_count} related-market trade(s)")
        if sibling_count:
            evidence_bits.append(f"{sibling_count} sibling-market trade(s) kept as context")
        if str(top_wallet.get("walletQualityStatus") or "").startswith("Weak"):
            evidence_bits.append("weak-history caveat")
        evidence_text = "; ".join(evidence_bits) if evidence_bits else "timing, outcome, and wallet-history evidence"
        lines = [
            f"- Primary subject: **{wallet_short}** ({username}).",
            (
                f"- What happened: {suspicious_count} notable trade(s) in this scope across "
                f"{event_trade_count} loaded event trade(s)"
                + (f"; {event_result}." if event_result else ".")
            ),
            f"- Why it matters: {_human_wallet_summary(top_wallet)}",
            f"- Evidence to check: {evidence_text}.",
        ]
        return {"type": "wallet", "wallets": {str(top_wallet.get("wallet") or "")}, "lines": lines}

    if top_trades:
        trade = top_trades[0]
        wallet = str(trade.get("wallet") or "")
        price_context = _side_outcome_label_for_trade(trade)
        lines = [
            f"- Primary trade: **{trade.get('walletShort') or _short_wallet(wallet)}** on **{trade.get('market') or 'Unknown market'}**.",
            (
                f"- What happened: {trade.get('orderSide') or 'TRADE'} {trade.get('side') or ''} "
                f"for {_money_label(trade.get('positionSize'))} at {trade.get('displayTime') or 'an unknown time'}. "
                f"{price_context}."
            ),
            f"- Why it matters: {str(trade.get('summary') or 'This is the strongest trade lead in the loaded data.')}",
        ]
        funding_quality_note = _suspicious_funding_quality_note(trade)
        if funding_quality_note:
            lines.append(f"- Suspicious funding quality: {funding_quality_note}.")
        return {"type": "trade", "wallets": {wallet}, "lines": lines}

    empty_note = str(
        report.get("empty_state_note")
        or "No trade crossed the event-forensic threshold in the loaded sample."
    )
    return {"type": "empty", "wallets": set(), "lines": [f"- {empty_note}"]}


def _primary_story_wallets(primary_story: dict[str, object]) -> set[str]:
    wallets = primary_story.get("wallets")
    if isinstance(wallets, set):
        return {wallet for wallet in wallets if wallet}
    return {str(wallet) for wallet in wallets or [] if str(wallet)}


def _other_candidate_lines(
    top_wallets: list[dict[str, object]],
    top_trades: list[dict[str, object]],
    primary_wallets: set[str],
    *,
    limit: int = 4,
) -> list[str]:
    lines: list[str] = []
    seen_wallets = set(primary_wallets)
    for wallet in top_wallets:
        wallet_address = str(wallet.get("wallet") or "")
        if wallet_address in seen_wallets:
            continue
        seen_wallets.add(wallet_address)
        wallet_short = str(wallet.get("walletShort") or _short_wallet(wallet_address))
        username = str(wallet.get("username") or "Not available")
        event_result = str(wallet.get("eventResult") or "").strip()
        lines.append(
            f"- **{wallet_short}** ({username}): {int(wallet.get('suspiciousTradeCount') or 0)} notable trade(s)"
            + (f"; {event_result}." if event_result else ".")
        )
        if len(lines) >= limit:
            return lines

    for trade in top_trades:
        wallet_address = str(trade.get("wallet") or "")
        if wallet_address in seen_wallets:
            continue
        seen_wallets.add(wallet_address)
        lines.append(
            f"- **{trade.get('walletShort') or _short_wallet(wallet_address)}** on **{trade.get('market') or 'Unknown market'}**: "
            f"{trade.get('orderSide') or 'TRADE'} {trade.get('side') or ''} for {_money_label(trade.get('positionSize'))} "
            f"at {trade.get('displayTime') or 'an unknown time'}. {_side_outcome_label_for_trade(trade)}."
        )
        if len(lines) >= limit:
            break
    return lines


def _side_outcome_label_for_trade(trade: dict[str, object]) -> str:
    raw_label = str(trade.get("rawTokenPriceLabel") or "").strip()
    economic_label = str(trade.get("economicSideProbabilityLabel") or "").strip()
    if raw_label and economic_label:
        return f"{raw_label}; {economic_label}"
    price = trade.get("price")
    if price not in (None, ""):
        normalized = normalize_side_outcome(trade.get("orderSide"), trade.get("side"), price)
        return f"{normalized.raw_token_price_label}; {normalized.economic_side_probability_label}"
    return "Token price unavailable; economic probability unavailable"


def _suspicious_funding_quality_note(row: dict[str, object]) -> str:
    quality = str(row.get("suspiciousFundingQuality") or "").strip()
    if not quality or quality in {"none", "unknown"}:
        return ""
    reasons = _text_values(row.get("suspiciousFundingQualityReasons"))
    support_sources = _text_values(row.get("suspiciousFundingIndependentSupportSources"))
    suppressor_reasons = _text_values(row.get("suspiciousFundingSuppressorConflictReasons"))
    parts = [f"suspicious funding quality {quality}"]
    if reasons:
        parts.append(reasons[0])
    if support_sources:
        parts.append("support=" + ", ".join(support_sources))
    if suppressor_reasons:
        parts.append("suppressors=" + ", ".join(suppressor_reasons))
    return "; ".join(parts)


def _next_action_lines(
    report: dict[str, object],
    primary_story: dict[str, object],
    clusters: list[dict[str, object]],
) -> list[str]:
    analysis_scope = _report_analysis_scope(report)
    selected_market_title = _report_selected_market_title(report)
    lines: list[str] = []
    story_type = str(primary_story.get("type") or "")
    if story_type == "cluster":
        lines.append("- Open the Linked wallets tab first and compare the member wallets' entry times, sides, and position sizes.")
        lines.append("- Then select the highest-scoring member wallet and inspect its trade sequence.")
    elif story_type == "wallet":
        lines.append("- Open the Wallets tab first and select the primary wallet, then compare its strongest trade rows in the Trades tab.")
        if clusters:
            lines.append("- Check whether the wallet appears in a linked-wallet group before drawing conclusions about coordination.")
    elif story_type == "trade":
        lines.append("- Open the Trades tab first and inspect the primary trade, then review the wallet's other event trades.")
    else:
        lines.append("- Use the ranked evidence tabs to confirm whether any weaker rows still deserve manual review.")
    if analysis_scope == "market":
        lines.append(
            f"- Keep the scope fixed to the selected market ({selected_market_title or 'Unknown child market'}); sibling-market activity is context only."
        )
    else:
        lines.append("- Keep whole-event scope in mind: separate wallet, trade, and linkage leads may be independent unless a connection row ties them together.")
    return lines


def _visible_trade_payloads(
    trade_payloads: list[dict[str, object]],
    *,
    minimum_notional: Decimal,
) -> list[dict[str, object]]:
    threshold = float(minimum_notional)
    visible: list[dict[str, object]] = []
    for item in trade_payloads:
        if float(item.get("positionSize") or 0.0) >= threshold:
            visible.append(item)
            continue
        raw = item.get("rawMetrics")
        raw_metrics = raw if isinstance(raw, dict) else {}
        if (
            item.get("candidateAdmissionStage") == "pre_admitted_validated"
            or raw_metrics.get("candidateAdmissionStage") == "pre_admitted_validated"
        ):
            visible.append(item)
    return visible


def _candidate_admission_records(
    cases: list[FlaggedCase],
    *,
    near_miss_records: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = [dict(record) for record in near_miss_records or []]
    for case in cases:
        raw = case.raw_metrics
        reason = str(raw.get("candidateAdmissionReason") or "").strip()
        stage = str(raw.get("candidateAdmissionStage") or "").strip()
        if not reason and stage != "pre_admitted_rejected":
            continue
        records.append(
            {
                "id": case.trade.trade_id,
                "trade_id": case.trade.trade_id,
                "wallet": case.trade.wallet,
                "conditionId": case.trade.condition_id,
                "severity": case.severity,
                "candidateAdmissionReason": reason,
                "candidateAdmissionStage": stage,
                "candidateAdmissionEvidenceSources": raw.get("candidateAdmissionEvidenceSources", ""),
                "candidateAdmissionFloorNotional": raw.get("candidateAdmissionFloorNotional", ""),
                "groupedCandidateId": raw.get("groupedCandidateId", ""),
                "groupedCandidateAggregateNotional": raw.get("groupedCandidateAggregateNotional", ""),
                "groupedCandidateWalletCount": raw.get("groupedCandidateWalletCount", ""),
                "groupedCandidateStrictFunding": raw.get("groupedCandidateStrictFunding", ""),
                "groupedCandidateProxyOnly": raw.get("groupedCandidateProxyOnly", ""),
                "groupedCandidateFundingGrade": raw.get("groupedCandidateFundingGrade", ""),
                "groupedCandidateTimeSpanMinutes": raw.get("groupedCandidateTimeSpanMinutes", ""),
                "groupedCandidatePriceBand": raw.get("groupedCandidatePriceBand", ""),
                "candidateAdmissionValidatedOpeningExposure": raw.get("candidateAdmissionValidatedOpeningExposure", ""),
                "candidateAdmissionRejectedReason": raw.get("candidateAdmissionRejectedReason", ""),
                "hardEvidenceSources": raw.get("hardEvidenceSources", ""),
                "hardEvidenceReviewTier": raw.get("hardEvidenceReviewTier", ""),
                "fundingEvidenceGrade": raw.get("fundingEvidenceGrade") or raw.get("funding_evidence_grade", ""),
                "repricingSourceQuality": raw.get("repricingSourceQuality") or raw.get("repricing_source_quality", ""),
                "rawMetrics": dict(raw),
            }
        )
    return records


def _display_note(
    *,
    suspicious_trade_count: int,
    display_trade_count: int,
    suspicious_wallet_count: int,
    display_wallet_count: int,
    wallet_cluster_count: int,
    display_cluster_count: int,
) -> str:
    parts: list[str] = []
    if suspicious_trade_count > display_trade_count:
        parts.append(
            f"Trade review list is capped at {display_trade_count} of {suspicious_trade_count} threshold-cleared trade rows"
        )
    if suspicious_wallet_count > display_wallet_count:
        parts.append(
            f"wallet review list is capped at {display_wallet_count} of {suspicious_wallet_count} wallet rows"
        )
    if wallet_cluster_count > display_cluster_count:
        parts.append(
            f"linked-wallet review list is capped at {display_cluster_count} of {wallet_cluster_count} groups"
        )
    if not parts:
        return "The on-screen review lists include every row that cleared the configured event-forensic threshold."
    return "; ".join(parts) + ". Use Open exports for the complete row set."


def _fallback_wallet_rows(
    trade_rows: list[dict[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for trade in trade_rows:
        wallet = str(trade.get("wallet") or "")
        if not wallet or wallet in seen:
            continue
        seen.add(wallet)
        rows.append(
            {
                "wallet": wallet,
                "walletShort": str(trade.get("walletShort") or _short_wallet(wallet)),
                "walletScore": int(trade.get("eventForensicScore") or 0),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _graph_trade_slice(
    trade_rows: list[dict[str, object]],
    wallet_lookup: set[str],
    *,
    limit: int,
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    selected_keys: set[tuple[str, str]] = set()
    market_edges_per_wallet: Counter[str] = Counter()
    for trade in trade_rows:
        wallet = str(trade.get("wallet") or "")
        market_slug = str(trade.get("marketSlug") or "")
        if wallet not in wallet_lookup or not market_slug:
            continue
        edge_key = (wallet, market_slug)
        if edge_key in selected_keys or market_edges_per_wallet[wallet] >= 2:
            continue
        selected_keys.add(edge_key)
        market_edges_per_wallet[wallet] += 1
        selected.append(trade)
        if len(selected) >= limit:
            break
    return selected


def _score_range(items: list[dict[str, object]], key: str) -> str:
    if not items:
        return "0"
    values = sorted(int(item.get(key) or 0) for item in items)
    if values[0] == values[-1]:
        return str(values[0])
    return f"{values[0]}-{values[-1]}"


def _group_model_gap_items(items: list[dict[str, object]], *, limit: int = 5) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in items:
        grouped[str(item.get("market") or "Unknown market")].append(item)

    rows: list[dict[str, object]] = []
    for market, market_items in grouped.items():
        ordered = sorted(
            market_items,
            key=lambda item: (
                int(item.get("eventForensicScore") or 0),
                int(item.get("existingModelScore") or 0),
            ),
            reverse=True,
        )
        wallets: list[str] = []
        seen_wallets: set[str] = set()
        for item in ordered:
            wallet_short = str(item.get("walletShort") or "")
            if wallet_short and wallet_short not in seen_wallets:
                seen_wallets.add(wallet_short)
                wallets.append(wallet_short)
        wallet_phrase = ", ".join(wallets[:4])
        if len(wallets) > 4:
            wallet_phrase = f"{wallet_phrase} + {len(wallets) - 4} more"
        trade_count = len(ordered)
        wallet_count = len({str(item.get('wallet') or '') for item in ordered if item.get('wallet')})
        rows.append(
            {
                "market": market,
                "tradeCount": trade_count,
                "walletCount": wallet_count,
                "wallets": wallets[:4],
                "forensicScoreRange": _score_range(ordered, "eventForensicScore"),
                "currentScoreRange": _score_range(ordered, "existingModelScore"),
                "summary": (
                    f"**{market}** concentrated {trade_count} trade(s) across {wallet_count} wallet(s). "
                    f"Forensic scores ranged { _score_range(ordered, 'eventForensicScore') }, while current-model "
                    f"scores ranged { _score_range(ordered, 'existingModelScore') }. "
                    f"Representative wallets: {wallet_phrase or 'n/a'}."
                ),
                "topForensicScore": int(ordered[0].get("eventForensicScore") or 0),
            }
        )
    rows.sort(
        key=lambda item: (
            int(item.get("tradeCount") or 0),
            int(item.get("topForensicScore") or 0),
        ),
        reverse=True,
    )
    return rows[:limit]


def _model_gap_summary_text(model_gap: dict[str, object]) -> str:
    counts = _model_gap_counts(model_gap)
    analysis_scope = str(model_gap.get("analysis_scope") or "event")
    selected_market_title = str(model_gap.get("selected_market_title") or "").strip() or None
    high_forensic_count = counts["high_forensic_count"]
    caught_count = counts["caught_count"]
    missed_count = counts["missed_count"]
    overflagged_count = counts["overflagged_count"]
    overflagged_phrase = _count_noun(overflagged_count, "trade")
    high_forensic_phrase = _count_noun(high_forensic_count, "high-concern trade")
    scope_subject = _analysis_scope_subject(analysis_scope, selected_market_title)
    scope_context_phrase = _analysis_scope_context_phrase(analysis_scope)
    outcome_context_available = bool(model_gap.get("outcome_context_available", True))
    weaker_context_phrase = (
        f"after the final outcome and {scope_context_phrase} were known"
        if outcome_context_available
        else f"after the currently loaded {scope_context_phrase} was reviewed"
    )
    if high_forensic_count == 0 and overflagged_count == 0:
        if analysis_scope == "market":
            return (
                f"The forensic review did not reveal a meaningful disagreement between the current model "
                f"and the forensic review in {scope_subject}."
            )
        return "This event did not reveal a meaningful disagreement between the current model and the forensic review."
    if high_forensic_count == 0:
        return (
            "The forensic review did not uncover any high-concern trades that the current model missed. "
            f"The main lesson was the opposite: {overflagged_phrase} looked weaker {weaker_context_phrase}."
        )
    if missed_count == 0:
        return (
            f"The current model kept up with the strongest forensic cases in {scope_subject}: "
            f"it already surfaced all {high_forensic_phrase}. "
            f"A separate {overflagged_phrase} looked weaker {weaker_context_phrase}."
        )
    return (
        f"The current model already surfaced {caught_count} of the {high_forensic_phrase} and "
        f"missed {missed_count}. Another {overflagged_phrase} looked weaker {weaker_context_phrase}."
    )


def _model_gap_counts(model_gap: dict[str, object]) -> dict[str, int]:
    high_forensic_count = int(model_gap.get("high_forensic_count") or 0)
    caught_count = int(model_gap.get("caught_count") or 0)
    missed_count = int(model_gap.get("missed_count") or 0)
    overflagged_count = int(model_gap.get("overflagged_count") or 0)
    if high_forensic_count or caught_count or missed_count or overflagged_count:
        return {
            "high_forensic_count": high_forensic_count,
            "caught_count": caught_count,
            "missed_count": missed_count,
            "overflagged_count": overflagged_count,
        }
    legacy_summary = str(model_gap.get("summary") or "")
    legacy_match = re.search(
        r"caught\s+(?P<caught>\d+)\s+of\s+the\s+(?P<high>\d+)\s+strongest.*?missed\s+(?P<missed>\d+).*?too generous on\s+(?P<over>\d+)",
        legacy_summary,
        flags=re.IGNORECASE,
    )
    if legacy_match:
        return {
            "high_forensic_count": int(legacy_match.group("high")),
            "caught_count": int(legacy_match.group("caught")),
            "missed_count": int(legacy_match.group("missed")),
            "overflagged_count": int(legacy_match.group("over")),
        }
    return {
        "high_forensic_count": len(model_gap.get("caught_by_existing") or []) + len(model_gap.get("missed_by_existing") or []),
        "caught_count": len(model_gap.get("caught_by_existing") or []),
        "missed_count": len(model_gap.get("missed_by_existing") or []),
        "overflagged_count": len(model_gap.get("overflagged_by_existing") or []),
    }


def _count_noun(value: int, noun: str) -> str:
    suffix = "" if value == 1 else "s"
    return f"{value} {noun}{suffix}"


def _dedupe_trades(trades: list[Trade]) -> list[Trade]:
    unique: dict[tuple[str, str, str], Trade] = {}
    for trade in trades:
        key = (trade.trade_id, trade.wallet, trade.condition_id)
        unique[key] = trade
    return list(unique.values())


def _winning_entry_ranks(cases: list[FlaggedCase], winners_by_condition: dict[str, str | None]) -> dict[str, int]:
    grouped: dict[str, list[FlaggedCase]] = defaultdict(list)
    for case in cases:
        winner = winners_by_condition.get(case.trade.condition_id)
        if (
            winner
            and _case_economic_side_won(case, winner)
            and case.raw_metrics.get("trade_state") == "increase"
        ):
            grouped[case.trade.condition_id].append(case)
    result: dict[str, int] = {}
    for market_cases in grouped.values():
        ordered = sorted(market_cases, key=lambda item: (item.trade.timestamp, item.trade.trade_id))
        for index, case in enumerate(ordered, start=1):
            result[case.trade.trade_id] = index
    return result


def _normalize_winner_outcome(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"YES", "Y"}:
        return "YES"
    if text in {"NO", "N"}:
        return "NO"
    return UNKNOWN


def _case_side_outcome_model(case: FlaggedCase):
    return normalize_side_outcome(case.trade.side, case.trade.outcome, case.trade.price)


def _case_economic_side_won(case: FlaggedCase, winner: object) -> bool:
    winner_outcome = _normalize_winner_outcome(winner)
    normalized = _case_side_outcome_model(case)
    return bool(winner_outcome != UNKNOWN and normalized.economic_side == winner_outcome)


def _payload_model_probability(item: dict[str, object], raw: dict[str, object]) -> float:
    for value in (
        item.get("economicSideProbability"),
        raw.get("economic_side_probability"),
        raw.get("model_probability"),
        item.get("price"),
    ):
        probability = _metric_float(value)
        if probability is not None:
            return probability / 100.0 if probability > 1 else probability
    return 0.0


def _event_forensic_score(
    *,
    case: FlaggedCase,
    later_won: bool,
    winner_rank: int | None,
    related_market_count: int,
    wallet_winning_entries: int,
    wallet_opening_entries: int,
) -> tuple[int, list[str], list[str], list[str]]:
    raw = case.raw_metrics
    score = round(case.suspicion_score * 0.55)
    flags: list[str] = []
    notes: list[str] = []
    reducers: list[str] = []
    dormant_gap_days = _metric_float(raw.get("days_since_prior_wallet_trade"))
    post_trade_gap_days = _metric_float(raw.get("days_to_next_wallet_trade"))
    try:
        raw_entry_price = float(case.trade.price)
    except (TypeError, ValueError):
        raw_entry_price = 0.0
    normalized_side_outcome = _case_side_outcome_model(case)
    if normalized_side_outcome.economic_side_probability is None:
        entry_price = raw_entry_price
        entry_probability_basis = "raw_token_price_fallback"
    else:
        entry_price = float(normalized_side_outcome.economic_side_probability)
        entry_probability_basis = normalized_side_outcome.model_probability_basis
    near_certainty_entry = entry_price >= NEAR_CERTAINTY_PRICE
    poor_history = _poor_wallet_history(raw)
    independent_proof = _has_independent_forensic_proof(
        raw,
        price=entry_price,
        winner_rank=winner_rank,
    )
    public_power_user = _trade_public_power_user_flag(raw)
    concrete_public_user_escape = _has_concrete_public_user_escape_evidence(raw)

    if raw.get("trade_state") == "increase":
        score += 7
        flags.append("opening_exposure")
    else:
        score -= 12
        reducers.append("This looks weaker in event context because it does not resemble a clean opening trade.")

    if raw.get("event_family_repeat_flag") == "Yes":
        score += 6
        flags.append("event_family_repeat")
        notes.append("The wallet had already returned to closely related markets in the same event family.")
    if raw.get("reactivated_after_dormancy_flag") == "Yes":
        score += 7 if dormant_gap_days is not None and dormant_gap_days >= 90 else 4
        flags.append("dormant_reactivation")
        if dormant_gap_days is not None:
            notes.append(f"The wallet reappeared after roughly {round(dormant_gap_days)} dormant day(s).")
        else:
            notes.append("The wallet reappeared after a long dormant stretch.")
    if raw.get("split_wallet_pattern_flag") == "Yes":
        score += 8
        flags.append("split_wallet_pattern")
        notes.append("Linked wallets entered the same side in a narrow price and time band.")

    if later_won:
        flags.append("later_correct")
        if entry_price >= VERY_NEAR_CERTAINTY_PRICE:
            score += 3
            flags.append("near_certainty_winner")
            reducers.append("Later correctness is weak evidence because the entry was already priced near certainty.")
        elif near_certainty_entry:
            score += 5
            flags.append("near_certainty_winner")
            reducers.append("Later correctness is weaker here because the market was already close to certainty.")
        elif entry_price >= 0.80:
            score += 10
            notes.append("The trade later won, but it entered after the market already leaned strongly that way.")
        else:
            score += 18
            notes.append("The trade eventually landed on the winning outcome.")
        if entry_price <= 0.35:
            score += 8
            flags.append("low_probability_winner")
            notes.append("It committed real capital while the market still implied a low probability.")
        if raw.get("post_trade_dormancy_flag") == "Yes":
            flags.append("dormant_after_win")
            if near_certainty_entry:
                reducers.append("The post-win quiet period is less meaningful because the entry was near certainty.")
            else:
                score += 6
                if post_trade_gap_days is not None:
                    notes.append(f"After this trade, the wallet stayed quiet for about {round(post_trade_gap_days)} day(s).")
                else:
                    notes.append("After this trade, the wallet went quiet for an unusually long period.")
    if winner_rank is not None:
        if winner_rank <= 3:
            score += 10
            flags.append("early_winning_entry")
            notes.append("It was one of the earliest winning entries in this market.")
        elif winner_rank <= 6:
            score += 5
    if raw.get("beat_consensus_flag") == "Yes":
        score += 6
        flags.append("beat_consensus")
    if raw.get("favorable_repricing_flag") == "Yes":
        score += 8
        flags.append("post_entry_repricing")
    if raw.get("suspicious_funding_flag") == "Yes" and not _has_proxy_funding_grade(raw):
        score += 7
        flags.append("recent_opaque_funding")
    if raw.get("shared_funding_source_flag") == "Yes":
        score += 10
        flags.append("shared_funder_cluster")
    if raw.get("coordinated_cluster_signal") == "Yes":
        score += 5
        flags.append("same_side_cluster")
    if related_market_count >= 2:
        score += 7
        flags.append("related_market_repeat")
        notes.append("The wallet also expressed the same thesis in related markets.")
    elif related_market_count == 1:
        score += 3
    if wallet_winning_entries >= 2 and (not near_certainty_entry or independent_proof):
        score += 6
        flags.append("repeat_correct_timing")
    if wallet_opening_entries >= 3 and wallet_winning_entries >= 2 and (not near_certainty_entry or independent_proof):
        score += 4

    if raw.get("wallet_cross_domain_public_bettor_flag") == "Yes":
        flags.append("cross_domain_public_bettor")
        reason = str(raw.get("wallet_cross_domain_public_bettor_reason") or "").strip()
        if independent_proof:
            score -= 4
            reducers.append(
                reason
                or "The wallet spans unrelated public-betting domains, but independent evidence keeps the case reviewable."
            )
        else:
            score -= 14
            reducers.append(
                reason
                or "The wallet spans unrelated public-betting domains, which weakens a one-off insider-style interpretation."
            )

    if public_power_user:
        flags.append("public_power_user")
        if concrete_public_user_escape:
            score -= 4
            reducers.append(
                "The wallet has more than 100 public predictions, but concrete linkage/funding evidence keeps it reviewable."
            )
        else:
            score -= 18
            score = min(score, EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD - 1)
            reducers.append(
                "The wallet has more than 100 public predictions or broad market history; without concrete linkage/funding evidence, this is context only."
            )

    if poor_history:
        flags.append("weak_wallet_track_record")
        if independent_proof:
            score -= 8
            reducers.append("The wallet's weak economic history tempers the case despite independent supporting evidence.")
        else:
            score -= 20
            reducers.append("The wallet's broader losing record blocks a primary insider-style interpretation without independent evidence.")
            if near_certainty_entry:
                score = min(score, EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD - 1)

    if case.case_type == "Resolution Gap":
        score -= 24
        reducers.append("This looks more like public information that the market absorbed slowly than like a private-information trade.")
    if raw.get("specialist_explained_flag") == "Yes":
        score -= 6
        reducers.append("The wallet also looks like a repeat specialist, which weakens the one-off insider interpretation.")
    if raw.get("low_analyst_value_flag") == "Yes":
        score -= 6
        reducers.append("The wallet looks heavily automated and low-value for manual forensic review.")
    if raw.get("formal_win_rate_may_be_overstated") == "Yes":
        score -= 2
    if "yield_farm_pattern" in case.flags:
        score -= 12
        reducers.append("The entry resembles near-certain capital parking more than a directional information edge.")
    if "theta_decay_pattern" in case.flags:
        score -= 10
        reducers.append("The entry also fits a standard deadline-decay pattern.")
    if "near_certainty_trade" in case.flags:
        score -= 15
        reducers.append("The market price was already near certainty at entry.")
    if _should_downgrade_high_impact_repricing_only(raw, price=entry_price, winner_rank=winner_rank):
        repricing_quality = _repricing_source_quality_from_raw(raw)
        if repricing_quality == REPRICING_SOURCE_QUALITY_MECHANICAL:
            score = min(score, EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD - 1)
            reducers.append(
                "High-impact repricing looks mechanical in the loaded Polymarket tape and is not enough by itself for primary review."
            )
        elif repricing_quality == REPRICING_SOURCE_QUALITY_WEAK:
            score = min(score, 54)
            reducers.append(
                "High-impact repricing source quality is weak without non-repricing hard evidence."
            )

    raw["event_forensic_model_probability"] = f"{entry_price:.6f}".rstrip("0").rstrip(".")
    raw["event_forensic_model_probability_basis"] = entry_probability_basis
    score = max(0, min(100, score))
    if not notes:
        notes.extend(case.explanation[:2])
    return score, flags, notes[:4], reducers[:4]


def _dedupe_trade_payloads(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    result: list[dict[str, object]] = []
    for row in rows:
        trade_id = str(row.get("id") or "").strip()
        key = trade_id or f"{row.get('wallet')}|{row.get('timestamp')}|{row.get('conditionId')}"
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _annotate_weak_history_near_certainty_review_policy(rows: list[dict[str, object]]) -> None:
    for item in rows:
        before_bucket = _review_bucket_before_weak_history_policy(item)
        demote, reason = _weak_history_near_certainty_review_demotion(item)
        item["reviewBucketBeforePolicy"] = before_bucket
        item["weakHistoryNearCertaintyReviewDemotion"] = "Yes" if demote else "No"
        item["weakHistoryNearCertaintyReviewReason"] = reason
        item["reviewBucketAfterPolicy"] = (
            WEAK_HISTORY_NEAR_CERTAINTY_REVIEW_REQUIRED_TIER if demote else before_bucket
        )


def _is_weak_history_near_certainty_review_demoted(item: dict[str, object]) -> bool:
    return str(item.get("weakHistoryNearCertaintyReviewDemotion") or "") == "Yes"


def _review_bucket_before_weak_history_policy(item: dict[str, object]) -> str:
    current_strong = str(item.get("existingModelClass") or "") == "Strong Risk"
    retrospective_strong = str(item.get("finalEventJudgment") or "").startswith("Strong Risk")
    if current_strong or retrospective_strong:
        return "current_or_retrospective_strong_risk"
    if item.get("hardEvidenceReviewTier") == HARD_EVIDENCE_REVIEW_TIER:
        return "hard_evidence_review"
    if _metric_int(item.get("eventForensicScore")) >= EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD:
        return "event_forensic_primary_threshold"
    return "secondary_context"


def _weak_history_near_certainty_review_demotion(item: dict[str, object]) -> tuple[bool, str]:
    raw = item.get("rawMetrics")
    raw_metrics = raw if isinstance(raw, dict) else {}
    before_bucket = _review_bucket_before_weak_history_policy(item)
    if before_bucket == "secondary_context":
        return False, "already_secondary_review_context"
    if not _payload_later_won_true(item):
        return False, "later_correctness_unknown_or_false"
    probability = _weak_history_policy_probability(item, raw_metrics)
    if probability is None:
        return False, "economic_side_probability_unavailable"
    if probability < NEAR_CERTAINTY_PRICE:
        return False, "economic_side_probability_not_near_certainty"
    if not _payload_has_weak_history_signal(item, raw_metrics):
        return False, "weak_history_signal_absent_or_unknown"
    return True, WEAK_HISTORY_NEAR_CERTAINTY_REVIEW_REASON


def _payload_later_won_true(item: dict[str, object]) -> bool:
    value = item.get("laterWon")
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"true", "yes", "1"}


def _weak_history_policy_probability(item: dict[str, object], raw_metrics: dict[str, object]) -> float | None:
    status = str(
        item.get("sideOutcomeNormalizationStatus")
        or raw_metrics.get("sideOutcomeNormalizationStatus")
        or raw_metrics.get("side_outcome_normalization_status")
        or ""
    ).strip()
    if status and status != "normalized":
        return None
    for value in (
        item.get("economicSideProbability"),
        raw_metrics.get("event_forensic_model_probability"),
        raw_metrics.get("economic_side_probability"),
        raw_metrics.get("model_probability"),
    ):
        probability = _metric_float(value)
        if probability is not None:
            return probability / 100.0 if probability > 1 else probability
    return None


def _payload_has_weak_history_signal(item: dict[str, object], raw_metrics: dict[str, object]) -> bool:
    flags = _text_values(item.get("eventForensicFlags"))
    if "weak_wallet_track_record" in flags:
        return True
    text_parts = [
        *_text_values(item.get("eventForensicFlags")),
        *_text_values(item.get("eventForensicReducers")),
        *_text_values(item.get("reducesConcern")),
        str(item.get("summary") or ""),
        str(raw_metrics.get("wallet_economic_history_note") or ""),
        str(raw_metrics.get("economic_history_note") or ""),
        str(raw_metrics.get("weak_wallet_track_record") or ""),
    ]
    text = " ".join(part.lower() for part in text_parts if str(part).strip())
    if "strong track record" in text or "history is not weak" in text:
        return False
    return (
        "weak_wallet_track_record" in text
        or "weak economic history" in text
        or "weak economic track" in text
        or "broader losing record" in text
    )


def _event_trade_sort_key(item: dict[str, object]) -> tuple[int, int, int, int, float]:
    strong_existing = str(item.get("existingModelClass") or "") == "Strong Risk"
    retrospective_strong = str(item.get("finalEventJudgment") or "").startswith("Strong Risk")
    hard_evidence_review = item.get("hardEvidenceReviewTier") == HARD_EVIDENCE_REVIEW_TIER
    threshold_review = int(item.get("eventForensicScore") or 0) >= EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD
    if strong_existing or retrospective_strong:
        bucket = 4
    elif hard_evidence_review:
        bucket = 3
    elif threshold_review:
        bucket = 2
    else:
        bucket = 1
    return (
        bucket,
        _metric_int(item.get("eventForensicScore")),
        int(bool(item.get("laterWon"))),
        _metric_int(item.get("existingModelScore")),
        _metric_float(item.get("positionSize")) or 0.0,
    )


def _event_judgment(score: int, *, later_won: bool = False, opening_exposure: bool = False) -> str:
    if score >= 70 and later_won and opening_exposure:
        return "Strong Risk: Retrospective"
    if score >= 70:
        return "High event-forensic concern"
    if score >= 55:
        return "Meaningful event-forensic concern"
    if score >= 40:
        return "Mixed but notable"
    return "Likely contextual or benign"


def _trade_summary(case: FlaggedCase, later_won: bool, flags: list[str], reducers: list[str]) -> str:
    funding_quality = str(case.raw_metrics.get("suspiciousFundingQuality") or "").strip()
    if "public_power_user" in flags and "weak_wallet_track_record" in flags:
        return "The wallet has broad public prediction history and weak economics, so this is context unless concrete linkage evidence appears."
    if "public_power_user" in flags:
        return "The wallet has broad public prediction history, so this is context unless concrete linkage evidence appears."
    if "weak_wallet_track_record" in flags and "near_certainty_winner" in flags:
        return "The trade later won, but the wallet history is very weak and the entry was already near certainty."
    if "weak_wallet_track_record" in flags:
        return "The wallet's weak economic history keeps this out of the strongest insider-style bucket."
    if later_won and "related_market_repeat" in flags:
        return "This trade looks stronger because it later won and the same wallet repeated the thesis in related markets."
    if later_won and "shared_funder_cluster" in flags:
        return "This trade later won and the wallet also sits inside a same-funder cluster."
    if funding_quality == "strong":
        return "This trade has a strong suspicious-funding lead with opening exposure and amount/time alignment."
    if funding_quality == "moderate":
        return "This trade has a moderate suspicious-funding lead that needs another structural cue for primary hard-evidence review."
    if funding_quality == "weak":
        return "This trade has weak suspicious-funding context, not enough by itself for hard-evidence review."
    if funding_quality == "unknown":
        return "Funding quality is unknown because the trace was unavailable, skipped, failed, or legacy-only."
    if later_won:
        return "This trade stands out because it later won after looking unusually well timed at entry."
    if reducers:
        return reducers[0]
    return "This trade is notable in the event context, but the evidence is mixed."


def _wallet_summary(
    *,
    analysis_scope: str,
    wallet_score: int,
    suspicious_trade_count: int,
    related_market_trade_count: int,
    other_event_market_trades: int,
    sibling_market_activity_count: int,
    later_wins: int,
    opening_entries: int,
    resolved_opening_entries: int,
    shared_funder: bool,
    split_wallet: bool,
    event_family_repeat: bool,
    dormant_reactivation: bool,
    dormant_after_win: bool,
    specialist: bool,
    bot_like: bool,
    wallet_quality_note: str = "",
    public_power_user_note: str = "",
    cross_domain_public_bettor_reason: str = "",
    wallet_statistical_prior_label: str = "",
    wallet_statistical_prior_note: str = "",
) -> str:
    parts = [
        f"{suspicious_trade_count} notable event trade(s) cleared review thresholds.",
    ]
    if opening_entries <= 0:
        parts.append("No clean opening entries were saved for outcome review.")
    elif resolved_opening_entries <= 0:
        parts.append("Final outcomes are not available for this wallet's opening entries yet.")
    elif resolved_opening_entries == opening_entries:
        parts.append(f"{later_wins} opening entries later resolved on the traded side.")
    else:
        parts.append(
            f"{later_wins} of {resolved_opening_entries} resolved opening entries later landed on the traded side; "
            f"{opening_entries - resolved_opening_entries} opening entries remain unresolved."
        )
    if related_market_trade_count and analysis_scope != "market":
        parts.append(f"It also appeared in {related_market_trade_count} related-market trade(s).")
    elif related_market_trade_count and analysis_scope == "market":
        parts.append(
            f"It also appeared in {related_market_trade_count} external related-market trade(s), "
            "but that enrichment is excluded from the primary wallet score."
        )
    if other_event_market_trades and analysis_scope == "market":
        parts.append(
            f"It also traded {other_event_market_trades} sibling-market context trade(s) across "
            f"{sibling_market_activity_count} other child market(s). "
            "Sibling-market activity is context only and does not change the single-market score."
        )
    if shared_funder:
        parts.append("It shares an upstream funding route with another suspicious wallet.")
    if split_wallet:
        parts.append("At least one trade matched a split-wallet entry shape across linked wallets.")
    if event_family_repeat:
        parts.append("It kept returning to closely related markets in the same event family.")
    if dormant_reactivation:
        parts.append("It reactivated after a long quiet period before trading this event family.")
    if dormant_after_win:
        parts.append("It also went quiet again after a winning event trade.")
    if specialist:
        parts.append("Specialist-like behavior reduces how strongly this looks like a burner-wallet pattern.")
    if bot_like:
        parts.append("Bot-like behavior reduces manual-review value.")
    if public_power_user_note:
        parts.append(public_power_user_note)
    if cross_domain_public_bettor_reason:
        parts.append(cross_domain_public_bettor_reason)
    if wallet_statistical_prior_label in {
        "weak_statistical_prior",
        "meaningful_statistical_prior",
        "strong_statistical_prior",
    }:
        parts.append(
            wallet_statistical_prior_note
            or "Unusual resolved win history, context only; not event-specific proof."
        )
    if wallet_quality_note:
        parts.append(wallet_quality_note)
    parts.append(f"Wallet concern score: {wallet_score}/100.")
    return " ".join(parts)


def _timing_clusters(
    trade_payloads: list[dict[str, object]],
    suspicious_wallet_lookup: set[str],
) -> list[list[dict[str, object]]]:
    grouped: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
    for item in trade_payloads:
        if item["wallet"] not in suspicious_wallet_lookup:
            continue
        if item["eventForensicScore"] < 45 and item.get("hardEvidenceReviewTier") != HARD_EVIDENCE_REVIEW_TIER:
            continue
        key = _timing_cluster_key(item)
        grouped[key].append(item)

    clusters: list[list[dict[str, object]]] = []
    for items in grouped.values():
        ordered = sorted(items, key=lambda item: item["timestamp"])
        current: list[dict[str, object]] = []
        last_time: datetime | None = None
        for item in ordered:
            timestamp = _parse_dt(item["timestamp"])
            if timestamp is None:
                continue
            if last_time is None or (timestamp - last_time).total_seconds() <= 30 * 60:
                current.append(item)
            else:
                if len({trade["wallet"] for trade in current}) >= 2:
                    clusters.append(current[:])
                current = [item]
            last_time = timestamp
        if len({trade["wallet"] for trade in current}) >= 2:
            clusters.append(current[:])
    return clusters


def _timing_cluster_key(item: dict[str, object]) -> tuple[str, ...]:
    cluster_direction = str(item.get("clusterDirection") or "").strip()
    if cluster_direction in {"long_yes", "long_no"} and item.get("clusterNormalizationStatus") == "normalized":
        return (str(item.get("marketSlug") or ""), cluster_direction)
    return (
        str(item.get("marketSlug") or ""),
        str(item.get("orderSide") or ""),
        str(item.get("side") or ""),
    )


def _suggest_model_improvements(
    missed: list[dict[str, object]],
    overflagged: list[dict[str, object]],
    suspicious_wallets: list[dict[str, object]],
    wallet_clusters: list[dict[str, object]],
) -> list[str]:
    suggestions: list[str] = []
    if any(item.get("laterWon") and item.get("winnerRank") and item["winnerRank"] <= 3 for item in missed):
        suggestions.append(
            "Add a stronger event-level boost for early winning entries that were placed before a visible repricing wave."
        )
    if any(item.get("relatedMarketTrades", 0) >= 1 for item in missed):
        suggestions.append(
            "Add an event-family repeat signal when the same wallet trades sibling or title-similar markets around the same thesis."
        )
    if any(item.get("rawMetrics", {}).get("shared_funding_source_flag") == "Yes" for item in missed):
        suggestions.append(
            "Promote same-funder clustering into the main model when multiple event wallets share an opaque recent funding source."
        )
    if any(item.get("rawMetrics", {}).get("low_analyst_value_flag") == "Yes" for item in overflagged):
        suggestions.append(
            "Increase the low-analyst-value bot penalty so automated capital rotation does not absorb manual review time."
        )
    if any(item.get("rawMetrics", {}).get("specialist_explained_flag") == "Yes" for item in overflagged):
        suggestions.append(
            "Stronger specialist discounts would reduce false positives in repeat domain-specialist wallets."
        )
    if any(cluster.get("sameFunder") for cluster in wallet_clusters):
        suggestions.append(
            "Store cluster-level features separately from single-trade scores so structurally linked wallets stand out at the event level."
        )
    if not suggestions:
        suggestions.append("This event did not reveal a single dominant new heuristic beyond the current model.")
    return suggestions


def _price_move_summary(series: list[dict[str, object]]) -> str:
    if len(series) < 2:
        return "Price history was too thin to summarize."
    first_price = _point_price(series[0])
    last_price = _point_price(series[-1])
    if first_price is None or last_price is None:
        return "Price history was too thin to summarize."
    direction = "higher" if last_price > first_price else "lower" if last_price < first_price else "flat"
    return f"The tracked market side finished {direction}, moving from {first_price:.2f} to {last_price:.2f} in the loaded hourly history."


def _price_jump_point(series: list[dict[str, object]]) -> dict[str, object] | None:
    if len(series) < 2:
        return None
    best: dict[str, object] | None = None
    best_move = Decimal("0")
    for left, right in zip(series, series[1:], strict=False):
        left_price = _point_price(left)
        right_price = _point_price(right)
        if left_price is None or right_price is None:
            continue
        move = abs(Decimal(str(right_price)) - Decimal(str(left_price)))
        if move > best_move:
            best_move = move
            best = {
                "timestamp": _point_timestamp(right),
                "startPrice": left_price,
                "endPrice": right_price,
            }
    return best


def _point_price(point: dict[str, object]) -> float | None:
    raw = point.get("p")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _point_timestamp(point: dict[str, object]) -> str:
    raw = point.get("t")
    if raw is None:
        return ""
    try:
        parsed = datetime.fromtimestamp(int(raw), tz=UTC)
    except (TypeError, ValueError, OSError):
        return ""
    return parsed.isoformat()


def _funding_context_to_dict(context: FundingContext) -> dict[str, object]:
    evidence_grade = grade_funding_evidence(context)
    return {
        "funding_found": context.funding_found,
        "source_address": context.source_address,
        "source_label": context.source_label,
        "source_type": context.source_type,
        "source_category": context.source_category,
        "origin_address": context.origin_address,
        "origin_label": context.origin_label,
        "origin_type": context.origin_type,
        "origin_category": context.origin_category,
        "funding_tx_hash": context.funding_tx_hash,
        "funding_timestamp": context.funding_timestamp.isoformat() if context.funding_timestamp else "",
        "funding_amount_usdc": context.funding_amount_usdc,
        "minutes_from_funding_to_trade": context.minutes_from_funding_to_trade,
        "funding_velocity_label": context.funding_velocity_label,
        "suspicious_funding_score": context.suspicious_funding_score,
        "suspicious_funding_flag": context.suspicious_funding_flag,
        "recent_external_funding_flag": context.recent_external_funding_flag,
        "funding_depth": context.funding_depth,
        "funding_evidence_grade": evidence_grade,
        "fundingEvidenceGrade": evidence_grade,
        "funding_graph_key": context.funding_graph_key,
        "funding_graph_key_strict": context.funding_graph_key_strict,
        "funding_graph_key_proxy": context.funding_graph_key_proxy,
        "funding_fingerprint": context.funding_fingerprint,
        "cex_proxy_cluster_flag": context.cex_proxy_cluster_flag,
        "cex_proxy_cluster_size": context.cex_proxy_cluster_size,
        "fundingTraceFromPersistentCache": context.funding_trace_from_persistent_cache,
        "fundingTracePersistentCacheStatus": context.funding_trace_cache_status,
        "error": context.error,
    }
