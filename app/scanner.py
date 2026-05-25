from __future__ import annotations

import json
import re
from collections import Counter
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median

from app.config import (
    FUNDING_TRACE_MODE_DISABLED,
    AppConfig,
    funding_trace_mode as runtime_funding_trace_mode,
    normalize_funding_trace_mode,
)
from app.event_context import EventContext, EventContextResolver
from app.funding_context import (
    FUNDING_EVIDENCE_BRIDGE_PROXY,
    FUNDING_EVIDENCE_CEX_PROXY,
    FUNDING_EVIDENCE_DIRECT_STRICT,
    FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN,
    FUNDING_EVIDENCE_NONE,
    FUNDING_EVIDENCE_SUSPICIOUS_DIRECT,
    FUNDING_EVIDENCE_UNKNOWN,
    PROXY_FUNDING_EVIDENCE_GRADES,
    FundingContext,
    FundingResolver,
    FundingResolverHealth,
    grade_funding_evidence,
    unknown_funding_context,
)
from app.models import FlaggedCase, Market, Trade, WalletInspection
from app.polymarket import PolymarketClient
from app.side_outcome import normalize_cluster_direction, normalize_side_outcome
from app.site_categories import SiteCategory, category_sensitivity
from app.storage import Storage
from app.topic_rules import match_focus_topic
from app.wallet_analytics import (
    WalletPerformance,
    bot_activity_note,
    compute_wallet_performance,
    compute_wallet_statistical_prior,
    economic_history_relevance_note,
)


def parse_lookback(raw: str) -> timedelta:
    units = {"h": "hours", "d": "days", "m": "minutes"}
    if len(raw) < 2 or raw[-1] not in units:
        raise ValueError("Lookback must be in the form 4h, 12h, 1d, or 30m.")
    value = int(raw[:-1])
    unit = raw[-1]
    return timedelta(**{units[unit]: value})


@dataclass(slots=True)
class ProgressEvent:
    percent: int
    stage: str
    detail: str
    metadata: dict[str, object] | None = None


class ScanStopped(Exception):
    pass


DOMAIN_BY_CATEGORY = {
    "Politics": "Politics",
    "Elections": "Politics",
    "Trump": "Politics",
    "World": "Geopolitics",
    "Geopolitics": "Geopolitics",
    "Middle East": "Middle East",
    "Iran": "Middle East",
    "Ukraine": "Ukraine / war",
    "Business": "Macro / rates",
    "Economy": "Macro / rates",
    "Finance": "Macro / rates",
    "Tech": "Technology",
    "Technology": "Technology",
    "Weather": "Weather",
    "Crypto": "Crypto",
    "Sports": "Sports",
    "Esports": "Sports",
    "Culture": "Entertainment",
    "Entertainment": "Entertainment",
    "Gaming": "Entertainment",
    "Mentions": "Entertainment",
}
PUBLIC_MODEL_DOMAINS = {"Sports", "Crypto", "Macro / rates"}
KEYWORD_DOMAIN_OVERRIDES = {
    "Ukraine": "Ukraine / war",
    "Russia": "Ukraine / war",
    "Iran": "Middle East",
    "Israel": "Middle East",
    "War/Ceasefire": "Geopolitics",
    "Sanctions/NATO/EU": "Geopolitics",
    "China/Taiwan": "Geopolitics",
    "Diplomacy/Intel": "Geopolitics",
}
EVENT_FAMILY_MONTH_WORDS = (
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
)
EVENT_FAMILY_DATE_SUFFIX_RE = re.compile(
    rf"-(?:{'|'.join(EVENT_FAMILY_MONTH_WORDS)})(?:-\d{{1,2}}(?:-\d{{2,4}})?)?$"
)
EVENT_FAMILY_YEAR_SUFFIX_RE = re.compile(r"-\d{4}$")
DORMANT_REACTIVATION_DAYS = 30.0
STRONG_DORMANT_REACTIVATION_DAYS = 90.0
POST_TRADE_DORMANCY_DAYS = 45.0
SPLIT_WALLET_WINDOW_MINUTES = 30.0
SPLIT_WALLET_PRICE_BAND = Decimal("0.06")
HARD_EVIDENCE_REVIEW_TIER = "Hard Evidence Review"
NO_HARD_EVIDENCE_REVIEW_TIER = ""
STRUCTURAL_PRE_ADMISSION_FLOOR_USD = Decimal("100")
STRUCTURAL_PRE_ADMISSION_FLOOR_RATIO = Decimal("0.20")
STRUCTURAL_PRE_ADMISSION_MAX_FLOOR_USD = Decimal("500")
STRUCTURAL_PRE_ADMISSION_MAX_PREFUNDING_TRADES_PER_CONDITION = 250
STRUCTURAL_PRE_ADMISSION_MAX_ADDED_PER_CONDITION = 75
STRUCTURAL_PRE_ADMISSION_ELIGIBLE_FUNDING_GRADES = {
    FUNDING_EVIDENCE_DIRECT_STRICT,
    FUNDING_EVIDENCE_SUSPICIOUS_DIRECT,
    FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN,
}
STRUCTURAL_PRE_ADMISSION_GROUP_REASONS = {
    "strict_shared_funding_group",
    "split_wallet_group",
}
STRUCTURAL_PRE_ADMISSION_SINGLE_REASONS = {
    "suspicious_recent_funding",
    "dormant_reactivation",
}
STRUCTURAL_PRE_ADMISSION_FIELDS = (
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
)
REPRICING_SOURCE_QUALITY_NONE = "none"
REPRICING_SOURCE_QUALITY_STRONG = "strong"
REPRICING_SOURCE_QUALITY_WEAK = "weak"
REPRICING_SOURCE_QUALITY_MECHANICAL = "mechanical"
SUSPICIOUS_FUNDING_QUALITY_STRONG = "strong"
SUSPICIOUS_FUNDING_QUALITY_MODERATE = "moderate"
SUSPICIOUS_FUNDING_QUALITY_WEAK = "weak"
SUSPICIOUS_FUNDING_QUALITY_NONE = "none"
SUSPICIOUS_FUNDING_QUALITY_UNKNOWN = "unknown"
SUSPICIOUS_FUNDING_RECENT_MINUTES = 24 * 60
SUSPICIOUS_FUNDING_MIN_AMOUNT_USD = Decimal("500")
SUSPICIOUS_FUNDING_AMOUNT_RATIO_MIN = Decimal("0.25")
SUSPICIOUS_FUNDING_AMOUNT_RATIO_MAX = Decimal("5.0")
SUSPICIOUS_FUNDING_QUALITY_FIELDS = (
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
)
HARD_EVIDENCE_FIELDS = (
    "hardEvidenceSources",
    "hardEvidenceStrength",
    "hardEvidencePrimaryReason",
    "hardEvidenceTradeIds",
    "hardEvidenceWalletIds",
    "hardEvidenceReviewTier",
    "evidenceAvailabilityStage",
)
STRONG_RISK_ATTRIBUTION_FIELDS = (
    "strongRiskGateTrace",
    "strongRiskGateName",
    "strongRiskGateFamily",
    "strongRiskGateInputs",
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
    "strongRiskHasIndependentHardEvidence",
    "strongRiskIndependentEvidenceSources",
    "strongRiskSuppressorConflict",
    "strongRiskSuppressorConflictReasons",
    "strongRiskHasHardEvidenceSources",
    "strongRiskNoHardEvidenceExplanation",
    "strongRiskCompositionClass",
    "strongRiskExactGateBranch",
    "strongRiskExactGatePassed",
    "strongRiskExactGateFailedReasons",
    "strongRiskExactGateInputs",
    "strongRiskTimingGateInputs",
    "strongRiskStructureGateInputs",
    "strongRiskRetrospectiveGateInputs",
    "strongRiskGateSourceWasInferred",
    "strongRiskGateSourceInferenceReason",
    "strongRiskStructuralSourcesResolved",
    "strongRiskHardEvidenceEligibleSources",
    "strongRiskNonHardStructuralSources",
    "strongRiskMissingSourceAttribution",
    "strongRiskSourceAttributionIssue",
    "strongRiskNoHardEvidenceSourcesReason",
    "strongRiskStructuralButNotHardEvidence",
    "strongRiskStructuralButNotHardEvidenceSources",
    "strongRiskWhyNoHardEvidence",
    "strongRiskScoreOnlyResolution",
    "strongRiskGateLeakageCandidate",
    "strongRiskGateLeakageReason",
    "strongRiskLiveDetectable",
    "strongRiskRetrospectiveOnly",
    "strongRiskRetrospectiveSources",
    "strongRiskOpeningExposureStatus",
    "strongRiskTimingRepricingOnly",
    "strongRiskScoreOnly",
    "strongRiskSavedFieldsSufficient",
    "strongRiskDiagnosticOnly",
)
STRONG_RISK_HARD_EVIDENCE_ELIGIBLE_SOURCES = {
    "split_wallet_pattern",
    "strict_shared_funding_source",
    "strict_shared_funding",
    "non_proxy_shared_funding",
    "dormant_wallet_reactivation",
    "low_probability_early_winner",
    "event_family_repeat_narrow_context",
    "same_market_same_direction_strict_structural_cluster",
    "coordinated_sizing_with_hard_evidence",
}
HARD_EVIDENCE_REASON_BY_SOURCE = {
    "split_wallet_pattern": "Linked wallets entered the same side from a strict shared funding route in a narrow time/price band.",
    "strict_shared_funding_source": "Multiple candidate wallets share a strict upstream funding source, not only a weak exchange proxy.",
    "suspicious_recent_funding": "The wallet has a high-quality suspicious-funding lead with trade-specific time/amount alignment.",
    "dormant_wallet_reactivation": "A dormant wallet reactivated to open exposure in this market.",
    "low_probability_early_winner": "The trade later resolved as a low-probability winner and was an early winning entry.",
    "event_family_repeat_narrow_context": "The wallet repeated an event-family thesis while opening exposure in a narrow timing/context window.",
    "coordinated_sizing_with_hard_evidence": "Coordinated sizing appears alongside another hard-evidence source.",
}


def _emit_progress(
    callback: callable | None,
    percent: int,
    stage: str,
    detail: str,
    metadata: dict[str, object] | None = None,
) -> None:
    if callback is None:
        return
    callback(ProgressEvent(percent=percent, stage=stage, detail=detail, metadata=metadata))


class Scanner:
    def __init__(self, client: PolymarketClient, storage: Storage, config: AppConfig) -> None:
        self._client = client
        self._storage = storage
        self._config = config
        self._event_context_resolver = EventContextResolver(self._config.data_dir)
        self._funding_resolver = FundingResolver()

    def scan(
        self,
        lookback: str,
        reports_dir: Path,
        *,
        selected_categories: tuple[SiteCategory, ...],
        min_notional: Decimal | None = None,
        max_notional: Decimal | None = None,
        include_blockchain: bool = True,
        funding_trace_mode: str | None = None,
        include_related_markets: bool = True,
        progress_callback: callable | None = None,
        stop_event: object | None = None,
    ) -> dict[str, object]:
        started_at = datetime.now(UTC)
        effective_funding_trace_mode = normalize_funding_trace_mode(
            funding_trace_mode,
            default=runtime_funding_trace_mode(),
        )
        if not include_blockchain:
            effective_funding_trace_mode = FUNDING_TRACE_MODE_DISABLED
        self._funding_resolver = FundingResolver(trace_mode=effective_funding_trace_mode)
        cutoff = started_at - parse_lookback(lookback)

        _emit_progress(progress_callback, 5, "Preparing", "Loading Polymarket site categories")
        focus_markets = self._client.fetch_focus_markets(selected_categories=selected_categories)
        _emit_progress(
            progress_callback,
            15,
            "Preparing",
            f"Loaded {len(focus_markets)} markets from selected site categories",
        )

        recent_trades: list[Trade] = []
        focus_market_ids = list(focus_markets)
        per_market_row_cap = self._config.max_trade_pages * self._config.trade_page_size
        possible_truncated_market_ids: list[str] = []
        market_trade_counts: dict[str, int] = {}
        failed_market_fetches: list[dict[str, str]] = []
        total_markets = max(1, len(focus_market_ids))
        for market_index, condition_id in enumerate(focus_market_ids, start=1):
            if _stop_requested(stop_event):
                break
            try:
                market_trades = self._client.fetch_recent_trades(
                    cutoff_ts=int(cutoff.timestamp()),
                    max_pages=self._config.max_trade_pages,
                    page_size=self._config.trade_page_size,
                    condition_ids=[condition_id],
                )
            except Exception as exc:
                market = focus_markets.get(condition_id)
                failed_market_fetches.append(
                    {
                        "conditionId": condition_id,
                        "marketSlug": market.slug if market else "",
                        "reason": f"{type(exc).__name__}: {exc}",
                    }
                )
                market_trade_counts[condition_id] = 0
                _emit_progress(
                    progress_callback,
                    15 + int((market_index / total_markets) * 30),
                    "Fetching trades",
                    f"Skipped market {market_index}/{len(focus_market_ids)} after trade fetch error",
                )
                continue
            recent_trades.extend(market_trades)
            market_trade_counts[condition_id] = len(market_trades)
            if per_market_row_cap and len(market_trades) >= per_market_row_cap:
                possible_truncated_market_ids.append(condition_id)
            percent = 15 + int((market_index / total_markets) * 30)
            _emit_progress(
                progress_callback,
                percent,
                "Fetching trades",
                f"Fetched market trades {market_index}/{len(focus_market_ids)}",
            )

        scoped_trades = [trade for trade in recent_trades if trade.condition_id in focus_markets]
        base_min = min_notional if min_notional is not None else Decimal("750")
        candidate_trades = _build_candidate_trade_set(
            scoped_trades,
            minimum_notional=base_min,
        )
        if max_notional is not None:
            candidate_trades = [trade for trade in candidate_trades if trade.notional <= max_notional]
        wallet_trades = _group_wallet_trades(scoped_trades)
        market_trades = _group_market_trades(scoped_trades)
        domain_trades = _group_domain_trades(scoped_trades, focus_markets)
        wallet_cache: dict[str, tuple[WalletInspection, list[Trade], WalletPerformance]] = {}
        funding_cache: dict[tuple[str, str], FundingContext] = {}

        _emit_progress(
            progress_callback,
            50,
            "Filtering",
            f"{len(candidate_trades)} candidate trades remain after category and size filters",
        )

        candidate_cases: list[FlaggedCase] = []
        total_candidates = max(1, len(candidate_trades))
        for trade_index, trade in enumerate(candidate_trades, start=1):
            if _stop_requested(stop_event):
                break
            market = focus_markets[trade.condition_id]
            trade_domain = _domain_for_trade(trade, focus_markets)
            cached_wallet = wallet_cache.get(trade.wallet)
            if cached_wallet is None:
                wallet_stats = self._client.fetch_wallet_stats(trade.wallet)
                wallet_inspection = _build_wallet_inspection(
                    trade.wallet,
                    wallet_stats.trades,
                    wallet_stats.traded_market_count,
                    wallet_stats.polygon_nonce,
                    focus_markets,
                )
                wallet_history_trades = wallet_stats.trades
                wallet_positions = self._client.fetch_wallet_positions(trade.wallet)
                wallet_performance = compute_wallet_performance(wallet_stats.trades, wallet_positions)
                wallet_cache[trade.wallet] = (wallet_inspection, wallet_history_trades, wallet_performance)
            else:
                wallet_inspection, wallet_history_trades, wallet_performance = cached_wallet
            funding_context = unknown_funding_context("funding_trace_not_requested")
            same_market_wallet_trades = wallet_trades.get(trade.wallet, [])
            prior_same_market_trades = [
                item
                for item in wallet_history_trades
                if item.condition_id == trade.condition_id
                and item.trade_id != trade.trade_id
                and item.timestamp <= trade.timestamp
            ]
            prior_same_asset_trades = [
                item
                for item in wallet_history_trades
                if item.asset_id == trade.asset_id
                and item.trade_id != trade.trade_id
                and item.timestamp <= trade.timestamp
            ]
            execution_state = _classify_execution_state(
                trade,
                prior_same_asset_trades,
                prior_same_market_trades,
            )
            opening_exposure = _is_opening_exposure(execution_state)
            capital_at_risk = _capital_at_risk_usdc(trade, execution_state)
            conviction_ratio = _wallet_market_conviction_ratio(wallet_trades.get(trade.wallet, []), trade)
            prior_gap_days, _observed_post_gap_days = _wallet_activity_gap_days(wallet_history_trades, trade)
            should_trace_funding = _should_trace_funding(
                wallet_inspection,
                trade=trade,
                mode="recent",
                derived_metrics={
                    "trade_domain": trade_domain,
                    "opening_exposure_flag": opening_exposure,
                    "capital_at_risk_usdc": capital_at_risk,
                    "wallet_market_conviction_ratio": conviction_ratio,
                    "reactivated_after_dormancy_flag": bool(
                        prior_gap_days is not None and prior_gap_days >= DORMANT_REACTIVATION_DAYS
                    ),
                },
            )
            if effective_funding_trace_mode == FUNDING_TRACE_MODE_DISABLED:
                skip_reason = (
                    "funding_trace_disabled_no_rpc_mode"
                    if include_blockchain
                    else "funding_trace_not_requested"
                )
                self._funding_resolver.record_trace_skipped(skip_reason)
                funding_context = unknown_funding_context(skip_reason)
            elif should_trace_funding:
                funding_key = _funding_cache_key(trade)
                funding_context = funding_cache.get(funding_key) or FundingContext(funding_found=False)
                if not funding_context.funding_found and funding_context.error is None and funding_key not in funding_cache:
                    funding_context = self._funding_resolver.analyze(trade.wallet, trade.timestamp)
                    funding_cache[funding_key] = funding_context
            else:
                self._funding_resolver.record_trace_skipped("funding_trace_not_requested")

            case = _score_trade(
                trade=trade,
                market=market,
                trade_domain=trade_domain,
                wallet_inspection=wallet_inspection,
                wallet_performance=wallet_performance,
                wallet_window_trades=wallet_trades.get(trade.wallet, []),
                wallet_history_trades=wallet_history_trades,
                market_window_trades=market_trades.get(trade.condition_id, []),
                domain_window_trades=domain_trades.get(trade_domain, []),
                event_context=self._event_context_resolver.resolve(
                    trade=trade,
                    market=market,
                    trade_domain=trade_domain,
                    market_deadline_flag=_looks_like_deadline_market(market.question),
                ),
                funding_context=funding_context,
                funding_health=self._funding_resolver.health(),
                include_below_threshold=True,
            )
            if case is not None:
                candidate_cases.append(case)

            percent = 50 + int((trade_index / total_candidates) * 35)
            _emit_progress(
                progress_callback,
                percent,
                "Scoring",
                f"Scored candidate {trade_index}/{total_candidates}",
            )

        _annotate_domain_peer_history(candidate_cases, wallet_cache)
        _annotate_preclassification_linkage(candidate_cases)
        flagged_cases = [case for case in candidate_cases if _case_survives_output_threshold(case)]
        _annotate_side_outcome_raw_metrics(flagged_cases)
        flagged_cases.sort(key=lambda item: item.suspicion_score, reverse=True)
        stopped = _stop_requested(stop_event)
        trade_collection_diagnostics = {
            "rawTradeCountMeaning": "api_loaded_recent_trade_rows_not_total_polymarket_volume",
            "focusMarketScope": "active_selected_site_category_markets",
            "marketFetchMode": "per_market_single_condition",
            "marketFilterSemantics": (
                "Data API market filtering is treated as single-condition only; scanner avoids "
                "multi-market batches because they can silently under-sample markets."
            ),
            "selectedCategoryCount": len(selected_categories),
            "selectedCategories": [category.label for category in selected_categories],
            "focusMarketCount": len(focus_markets),
            "perMarketPageLimit": self._config.max_trade_pages,
            "perMarketPageSize": self._config.trade_page_size,
            "perMarketRowCap": per_market_row_cap,
            "possibleTruncatedMarketCount": len(possible_truncated_market_ids),
            "possibleTruncatedMarketConditionIds": possible_truncated_market_ids[:50],
            "failedMarketFetchCount": len(failed_market_fetches),
            "failedMarketFetches": failed_market_fetches[:25],
            "activeMarketScopeOnly": True,
            "coverageWarning": (
                "Recent scanner counts are API-loaded rows from active selected-category markets "
                "within page limits, not a complete Polymarket-wide weekly trade count."
            ),
            "partialCollectionWarning": (
                "Some focus markets failed during trade collection; counts are partial for those markets."
                if failed_market_fetches
                else ""
            ),
            "nonEmptyMarketCount": sum(1 for count in market_trade_counts.values() if count > 0),
        }
        report = {
            "generated_at": started_at.isoformat(),
            "lookback": lookback,
            "topic_scope": ",".join(category.label for category in selected_categories),
            "raw_trade_count": len(recent_trades),
            "filtered_trade_count": len(scoped_trades),
            "candidate_trade_count": len(candidate_trades),
            "flagged_case_count": len(flagged_cases),
            "status": "stopped" if stopped else "completed",
            "trade_collection_diagnostics": trade_collection_diagnostics,
            "analysis_settings": {
                "include_blockchain": bool(include_blockchain),
                "funding_trace_mode": effective_funding_trace_mode,
                "include_related_markets": bool(include_related_markets),
                "case_family_scope_status": "category_scan_no_single_event_anchor",
                "case_family_scope_note": (
                    "Recent scanner runs are category-wide. Event-target case-family expansion is available "
                    "in Event Forensic; this scanner setting is recorded for UI consistency and does not "
                    "broaden candidate admission."
                ),
            },
            "funding_resolver_health": self._funding_resolver.health().to_dict(),
            "cases": [case.to_dict() for case in flagged_cases],
        }
        json_path, md_path, txt_path = self._write_report_files(started_at, reports_dir, report)
        _emit_progress(progress_callback, 92, "Saving", "Reports written to disk")

        scan_run_id = self._storage.create_scan_run(
            started_at=started_at.isoformat(),
            lookback=lookback,
            topic_scope=",".join(category.label for category in selected_categories),
            raw_trade_count=len(recent_trades),
            filtered_trade_count=len(scoped_trades),
            flagged_case_count=len(flagged_cases),
            report_json_path=str(json_path),
            report_md_path=str(md_path),
        )
        self._storage.save_flagged_cases(scan_run_id, flagged_cases)

        report["scan_run_id"] = scan_run_id
        report["report_json_path"] = str(json_path)
        report["report_md_path"] = str(md_path)
        report["report_txt_path"] = str(txt_path)
        if stopped:
            _emit_progress(progress_callback, 100, "Stopped", "Scan stopped and partial results saved")
        else:
            _emit_progress(progress_callback, 100, "Done", "Scan finished")
        return report

    def _write_report_files(
        self,
        started_at: datetime,
        reports_dir: Path,
        report: dict[str, object],
    ) -> tuple[Path, Path, Path]:
        suffix = "_stopped" if report.get("status") == "stopped" else ""
        base_name = started_at.strftime("scan_%Y%m%d_%H%M%S") + suffix
        json_path = reports_dir / f"{base_name}.json"
        md_path = reports_dir / f"{base_name}.md"
        txt_path = self._config.outputs_dir / f"{base_name}.txt"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(_to_markdown(report), encoding="utf-8")
        txt_path.write_text(_to_text_report(report), encoding="utf-8")
        return json_path, md_path, txt_path


def _stop_requested(stop_event: object | None) -> bool:
    return bool(stop_event is not None and getattr(stop_event, "is_set")())


def inspect_wallet(
    client: PolymarketClient,
    address: str,
    focus_markets: dict[str, Market],
) -> WalletInspection:
    wallet_stats = client.fetch_wallet_stats(address)
    return _build_wallet_inspection(
        address,
        wallet_stats.trades,
        wallet_stats.traded_market_count,
        wallet_stats.polygon_nonce,
        focus_markets,
    )


def _build_wallet_inspection(
    address: str,
    trades: list[Trade],
    traded_market_count: int | None,
    polygon_nonce: int | None,
    focus_markets: dict[str, Market],
) -> WalletInspection:
    timestamps = sorted(trade.timestamp for trade in trades)
    focus_count = sum(1 for trade in trades if trade.condition_id in focus_markets)
    domain_counts = _wallet_domain_counts(trades, focus_markets)
    if domain_counts:
        dominant_domain = max(domain_counts, key=domain_counts.get)
        domain_concentration = domain_counts[dominant_domain] / max(1, sum(domain_counts.values()))
    else:
        dominant_domain = "Other"
        domain_concentration = 0.0
    notes: list[str] = []
    if polygon_nonce is not None and polygon_nonce <= 5:
        notes.append("Low on-chain nonce suggests a lightly used wallet.")
    if traded_market_count is not None and traded_market_count <= 3:
        notes.append("Very few prior Polymarket markets are visible in loaded history.")
    if domain_concentration >= 0.7 and sum(domain_counts.values()) >= 4:
        notes.append(f"The wallet looks concentrated in {dominant_domain.lower()} markets.")
    if not notes:
        notes.append("No obvious low-history wallet signal was found in the basic review.")

    return WalletInspection(
        address=address.lower(),
        polygon_nonce=polygon_nonce,
        traded_market_count=traded_market_count,
        recent_trade_count=len(trades),
        unique_market_count=len({trade.condition_id for trade in trades}),
        focus_market_count=focus_count,
        first_trade_at=timestamps[0].isoformat() if timestamps else None,
        last_trade_at=timestamps[-1].isoformat() if timestamps else None,
        dominant_domain_label=dominant_domain,
        domain_concentration_score=domain_concentration,
        public_model_specialist_flag=dominant_domain in PUBLIC_MODEL_DOMAINS,
        domain_counts=domain_counts,
        notes=notes,
    )


def _group_wallet_trades(trades: list[Trade]) -> dict[str, list[Trade]]:
    grouped: dict[str, list[Trade]] = {}
    for trade in trades:
        grouped.setdefault(trade.wallet, []).append(trade)
    return grouped


def _group_market_trades(trades: list[Trade]) -> dict[str, list[Trade]]:
    grouped: dict[str, list[Trade]] = {}
    for trade in trades:
        grouped.setdefault(trade.condition_id, []).append(trade)
    return grouped


def _group_domain_trades(
    trades: list[Trade],
    focus_markets: dict[str, Market],
) -> dict[str, list[Trade]]:
    grouped: dict[str, list[Trade]] = {}
    for trade in trades:
        grouped.setdefault(_domain_for_trade(trade, focus_markets), []).append(trade)
    return grouped


def _funding_cache_key(trade: Trade) -> tuple[str, str]:
    return trade.wallet, trade.timestamp.strftime("%Y%m%d%H")


def _should_trace_funding(
    wallet_inspection: WalletInspection,
    *,
    trade: Trade | None = None,
    mode: str | None = None,
    derived_metrics: dict[str, object] | None = None,
) -> bool:
    if mode in {"archive", "event_forensic"}:
        return True
    if wallet_inspection.polygon_nonce is not None and wallet_inspection.polygon_nonce <= 50:
        return True
    if wallet_inspection.traded_market_count is not None and wallet_inspection.traded_market_count <= 30:
        return True
    if wallet_inspection.recent_trade_count <= 100:
        return True
    metrics = derived_metrics or {}
    trade_domain = str(metrics.get("trade_domain") or "")
    if trade_domain in {"Politics", "Geopolitics", "Ukraine / war", "Middle East"}:
        return True
    if bool(metrics.get("reactivated_after_dormancy_flag")):
        return True
    capital_at_risk = metrics.get("capital_at_risk_usdc")
    if bool(metrics.get("opening_exposure_flag")) and capital_at_risk is not None:
        try:
            if Decimal(str(capital_at_risk)) >= Decimal("2500"):
                return True
        except Exception:
            pass
    conviction_ratio = metrics.get("wallet_market_conviction_ratio")
    if conviction_ratio is not None:
        try:
            if float(conviction_ratio) >= 0.85:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _build_candidate_trade_set(
    trades: list[Trade],
    *,
    minimum_notional: Decimal,
    aggregate_window: timedelta = timedelta(hours=6),
    aggregate_threshold: Decimal = Decimal("1000"),
    enable_structural_pre_admission: bool = False,
    structural_pre_admission_metadata: dict[str, dict[str, str]] | None = None,
) -> list[Trade]:
    selected: dict[str, Trade] = {
        trade.trade_id: trade for trade in trades if trade.notional >= minimum_notional
    }
    grouped: dict[tuple[str, str, str, str], list[Trade]] = {}
    for trade in trades:
        key = (trade.wallet, trade.condition_id, trade.side, trade.outcome.upper())
        grouped.setdefault(key, []).append(trade)

    for grouped_trades in grouped.values():
        ordered = sorted(grouped_trades, key=_trade_sort_key)
        left = 0
        running_total = Decimal("0")
        for right, trade in enumerate(ordered):
            running_total += trade.notional
            while (
                left < right
                and ordered[right].timestamp - ordered[left].timestamp > aggregate_window
            ):
                running_total -= ordered[left].notional
                left += 1
            if right - left + 1 >= 2 and running_total >= aggregate_threshold:
                for item in ordered[left : right + 1]:
                    selected.setdefault(item.trade_id, item)

    if enable_structural_pre_admission and structural_pre_admission_metadata:
        floor = _structural_pre_admission_floor(minimum_notional)
        for trade in trades:
            if trade.trade_id in selected:
                continue
            if trade.trade_id not in structural_pre_admission_metadata:
                continue
            if trade.notional < floor:
                continue
            selected[trade.trade_id] = trade
    return sorted(selected.values(), key=_trade_sort_key)


def _structural_pre_admission_floor(minimum_notional: Decimal) -> Decimal:
    return max(
        STRUCTURAL_PRE_ADMISSION_FLOOR_USD,
        min(
            STRUCTURAL_PRE_ADMISSION_MAX_FLOOR_USD,
            minimum_notional * STRUCTURAL_PRE_ADMISSION_FLOOR_RATIO,
        ),
    )


def _structural_pre_admission_prefunding_pool(
    trades: list[Trade],
    *,
    minimum_notional: Decimal,
    normal_candidate_ids: set[str] | None = None,
) -> list[Trade]:
    floor = _structural_pre_admission_floor(minimum_notional)
    normal_candidate_ids = normal_candidate_ids or set()
    grouped: dict[str, list[Trade]] = {}
    for trade in trades:
        if trade.trade_id in normal_candidate_ids:
            continue
        if trade.notional < floor or trade.notional >= minimum_notional:
            continue
        grouped.setdefault(trade.condition_id, []).append(trade)

    pool: list[Trade] = []
    for condition_id in sorted(grouped):
        ordered = sorted(
            grouped[condition_id],
            key=lambda item: (item.notional, item.timestamp, item.trade_id),
            reverse=True,
        )
        pool.extend(ordered[:STRUCTURAL_PRE_ADMISSION_MAX_PREFUNDING_TRADES_PER_CONDITION])
    return sorted(pool, key=_trade_sort_key)


def _build_structural_pre_admission_metadata(
    trades: list[Trade],
    *,
    minimum_notional: Decimal,
    funding_context_by_trade_id: dict[str, FundingContext] | None = None,
    wallet_history_by_wallet: dict[str, list[Trade]] | None = None,
    normal_candidate_ids: set[str] | None = None,
    enable_structural_pre_admission: bool = False,
) -> dict[str, dict[str, str]]:
    if not enable_structural_pre_admission:
        return {}

    funding_context_by_trade_id = funding_context_by_trade_id or {}
    wallet_history_by_wallet = wallet_history_by_wallet or {}
    normal_candidate_ids = normal_candidate_ids or set()
    floor = _structural_pre_admission_floor(minimum_notional)
    eligible = [
        trade
        for trade in trades
        if trade.trade_id not in normal_candidate_ids
        and floor <= trade.notional < minimum_notional
    ]
    metadata: dict[str, dict[str, str]] = {}
    added_by_condition: Counter[str] = Counter()

    def remaining_capacity(condition_id: str) -> int:
        return max(
            STRUCTURAL_PRE_ADMISSION_MAX_ADDED_PER_CONDITION - added_by_condition[condition_id],
            0,
        )

    strict_groups: dict[tuple[str, str, str], list[Trade]] = {}
    for trade in eligible:
        context = funding_context_by_trade_id.get(trade.trade_id) or FundingContext(funding_found=False)
        grade = grade_funding_evidence(context)
        strict_key = str(context.funding_graph_key_strict or "").strip()
        if grade not in STRUCTURAL_PRE_ADMISSION_ELIGIBLE_FUNDING_GRADES:
            continue
        if not strict_key or grade in PROXY_FUNDING_EVIDENCE_GRADES:
            continue
        direction = _pre_admission_direction_hint(trade)
        if not direction:
            continue
        strict_groups.setdefault((trade.condition_id, direction, strict_key), []).append(trade)

    group_items: list[tuple[Decimal, tuple[str, str, str], list[Trade]]] = []
    for key, group in strict_groups.items():
        wallets = {trade.wallet for trade in group if trade.wallet}
        if len(wallets) < 2:
            continue
        ordered = sorted(group, key=_trade_sort_key)
        aggregate = sum((trade.notional for trade in ordered), Decimal("0"))
        if aggregate < minimum_notional:
            continue
        time_span = _trade_group_time_span_minutes(ordered)
        price_band = _trade_group_price_band(ordered)
        if time_span > 60.0 or price_band > SPLIT_WALLET_PRICE_BAND:
            continue
        group_items.append((aggregate, key, ordered))

    for aggregate, key, ordered in sorted(group_items, key=lambda item: (item[0], item[1]), reverse=True):
        condition_id, direction, strict_key = key
        capacity = remaining_capacity(condition_id)
        if capacity <= 0:
            continue
        selected_group = ordered[:capacity]
        if len({trade.wallet for trade in selected_group if trade.wallet}) < 2:
            continue
        added_by_condition[condition_id] += len(selected_group)
        grade_text = _common_funding_grade(selected_group, funding_context_by_trade_id)
        group_id = f"structural:{condition_id}:{direction}:{strict_key}"
        time_span = _trade_group_time_span_minutes(selected_group)
        price_band = _trade_group_price_band(selected_group)
        for trade in selected_group:
            metadata[trade.trade_id] = {
                "candidateAdmissionReason": "strict_shared_funding_group",
                "candidateAdmissionStage": "pre_admitted_pending_linkage_validation",
                "candidateAdmissionEvidenceSources": "strict_shared_funding_source; split_wallet_pattern",
                "candidateAdmissionFloorNotional": _fmt_decimal(floor),
                "groupedCandidateId": group_id,
                "groupedCandidateAggregateNotional": _fmt_decimal(aggregate),
                "groupedCandidateWalletCount": str(len({item.wallet for item in ordered if item.wallet})),
                "groupedCandidateStrictFunding": "Yes",
                "groupedCandidateProxyOnly": "No",
                "groupedCandidateFundingGrade": grade_text,
                "groupedCandidateTimeSpanMinutes": f"{time_span:.1f}",
                "groupedCandidatePriceBand": _fmt_decimal(price_band),
                "candidateAdmissionValidatedOpeningExposure": "Pending",
                "candidateAdmissionRejectedReason": "",
            }

    for trade in sorted(eligible, key=lambda item: (item.condition_id, item.notional), reverse=True):
        if trade.trade_id in metadata or remaining_capacity(trade.condition_id) <= 0:
            continue
        context = funding_context_by_trade_id.get(trade.trade_id) or FundingContext(funding_found=False)
        grade = grade_funding_evidence(context)
        if (
            context.suspicious_funding_flag
            and grade in {FUNDING_EVIDENCE_SUSPICIOUS_DIRECT, FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN}
            and grade not in PROXY_FUNDING_EVIDENCE_GRADES
        ):
            metadata[trade.trade_id] = {
                "candidateAdmissionReason": "suspicious_recent_funding",
                "candidateAdmissionStage": "pre_admitted_pending_opening_validation",
                "candidateAdmissionEvidenceSources": "suspicious_recent_funding",
                "candidateAdmissionFloorNotional": _fmt_decimal(floor),
                "groupedCandidateId": "",
                "groupedCandidateAggregateNotional": "",
                "groupedCandidateWalletCount": "1",
                "groupedCandidateStrictFunding": "No",
                "groupedCandidateProxyOnly": "No",
                "groupedCandidateFundingGrade": grade,
                "groupedCandidateTimeSpanMinutes": "",
                "groupedCandidatePriceBand": "",
                "candidateAdmissionValidatedOpeningExposure": "Pending",
                "candidateAdmissionRejectedReason": "",
            }
            added_by_condition[trade.condition_id] += 1

    for trade in sorted(eligible, key=lambda item: (item.condition_id, item.notional), reverse=True):
        if trade.trade_id in metadata or remaining_capacity(trade.condition_id) <= 0:
            continue
        prior_gap_days, _observed_gap_days = _wallet_activity_gap_days(
            wallet_history_by_wallet.get(trade.wallet, []),
            trade,
        )
        if prior_gap_days is None or prior_gap_days < STRONG_DORMANT_REACTIVATION_DAYS:
            continue
        metadata[trade.trade_id] = {
            "candidateAdmissionReason": "dormant_reactivation",
            "candidateAdmissionStage": "pre_admitted_pending_opening_validation",
            "candidateAdmissionEvidenceSources": "dormant_wallet_reactivation",
            "candidateAdmissionFloorNotional": _fmt_decimal(floor),
            "groupedCandidateId": "",
            "groupedCandidateAggregateNotional": "",
            "groupedCandidateWalletCount": "1",
            "groupedCandidateStrictFunding": "No",
            "groupedCandidateProxyOnly": "No",
            "groupedCandidateFundingGrade": "",
            "groupedCandidateTimeSpanMinutes": "",
            "groupedCandidatePriceBand": "",
            "candidateAdmissionValidatedOpeningExposure": "Pending",
            "candidateAdmissionRejectedReason": "",
        }
        added_by_condition[trade.condition_id] += 1

    return metadata


def _build_structural_pre_admission_funnel(
    trades: list[Trade],
    *,
    minimum_notional: Decimal,
    normal_candidate_ids: set[str] | None = None,
    pre_admission_pool: list[Trade] | None = None,
    funding_context_by_trade_id: dict[str, FundingContext] | None = None,
    wallet_history_by_wallet: dict[str, list[Trade]] | None = None,
    admission_metadata: dict[str, dict[str, str]] | None = None,
    funding_resolver_available: bool = True,
    funding_resolver_disabled_reason: str = "",
    funding_resolver_auth_error: bool = False,
    funding_resolver_unavailable_reason: str = "",
    funding_resolver_endpoint_label: str = "",
    funding_resolver_last_error: str = "",
    funding_resolver_health: FundingResolverHealth | dict[str, object] | None = None,
    pre_admission_funding_trace_enabled: bool = True,
    pre_admission_funding_trace_attempted_ids: set[str] | None = None,
    pre_admission_funding_trace_succeeded_ids: set[str] | None = None,
    pre_admission_funding_trace_skipped_reasons: dict[str, str] | None = None,
) -> dict[str, object]:
    normal_candidate_ids = normal_candidate_ids or set()
    pre_admission_pool = pre_admission_pool or []
    pre_pool_ids = {trade.trade_id for trade in pre_admission_pool}
    funding_context_by_trade_id = funding_context_by_trade_id or {}
    wallet_history_by_wallet = wallet_history_by_wallet or {}
    admission_metadata = admission_metadata or {}
    attempted_ids = pre_admission_funding_trace_attempted_ids or set()
    succeeded_ids = pre_admission_funding_trace_succeeded_ids or set()
    skipped_reasons = pre_admission_funding_trace_skipped_reasons or {}
    health = _funding_health_to_dict(funding_resolver_health)
    if health:
        funding_resolver_available = bool(health.get("fundingResolverAvailable"))
        funding_resolver_disabled_reason = str(health.get("fundingResolverDisabledReason") or funding_resolver_disabled_reason)
        funding_resolver_auth_error = bool(health.get("fundingResolverAuthError"))
        funding_resolver_unavailable_reason = str(
            health.get("fundingResolverUnavailableReason") or funding_resolver_unavailable_reason
        )
        funding_resolver_endpoint_label = str(health.get("fundingResolverEndpointLabel") or funding_resolver_endpoint_label)
        funding_resolver_last_error = str(health.get("fundingResolverLastError") or funding_resolver_last_error)
    floor = _structural_pre_admission_floor(minimum_notional)
    counts: Counter[str] = Counter()

    below_normal = [
        trade
        for trade in trades
        if trade.trade_id not in normal_candidate_ids and trade.notional < minimum_notional
    ]
    above_floor = [trade for trade in below_normal if trade.notional >= floor]
    below_floor = [trade for trade in below_normal if trade.notional < floor]
    usable_condition = [trade for trade in above_floor if str(trade.condition_id or "").strip()]
    with_direction = [trade for trade in usable_condition if _pre_admission_direction_hint(trade)]

    counts["totalRawTradesConsidered"] = len(trades)
    counts["normalCandidateTrades"] = len(normal_candidate_ids)
    counts["belowNormalThresholdTrades"] = len(below_normal)
    counts["subThresholdAboveStructuralFloorTrades"] = len(above_floor)
    counts["belowStructuralFloorTrades"] = len(below_floor)
    counts["subThresholdUsableConditionIdTrades"] = len(usable_condition)
    counts["subThresholdNormalizedDirectionTrades"] = len(with_direction)
    counts["rejectedDuplicateNormalCandidate"] = sum(
        1 for trade in trades if trade.trade_id in normal_candidate_ids
    )

    by_condition: dict[str, list[Trade]] = {}
    groups: dict[tuple[str, str], list[Trade]] = {}
    for trade in with_direction:
        by_condition.setdefault(trade.condition_id, []).append(trade)
        groups.setdefault((trade.condition_id, _pre_admission_direction_hint(trade)), []).append(trade)
    counts["groupedConditionDirectionGroups"] = len(groups)
    counts["rejectedCapHit"] = sum(
        max(0, len(group) - STRUCTURAL_PRE_ADMISSION_MAX_PREFUNDING_TRADES_PER_CONDITION)
        for group in by_condition.values()
    )

    strict_group_keys: set[tuple[str, str, str]] = set()
    proxy_group_keys: set[tuple[str, str, str]] = set()
    rejected_groups: list[dict[str, object]] = []
    near_miss_records: list[dict[str, object]] = []

    for (condition_id, direction), group in sorted(groups.items()):
        ordered = sorted(group, key=_trade_sort_key)
        wallets = {trade.wallet for trade in ordered if trade.wallet}
        aggregate = sum((trade.notional for trade in ordered), Decimal("0"))
        time_span = _trade_group_time_span_minutes(ordered)
        price_band = _trade_group_price_band(ordered)
        grades = _group_funding_grades(ordered, funding_context_by_trade_id)
        group_grade = _common_diagnostic_grade(grades)
        proxy_only = _diagnostic_group_proxy_only(ordered, funding_context_by_trade_id)
        strict_keys = _diagnostic_strict_keys(ordered, funding_context_by_trade_id)
        proxy_keys = _diagnostic_proxy_keys(ordered, funding_context_by_trade_id)

        for grade in set(grades):
            counts[f"groupsFundingGrade{_funding_grade_counter_suffix(grade)}"] += 1
        if not grades:
            counts["groupsFundingGradeUnknown"] += 1
        if "unknown" in grades or any(trade.trade_id not in funding_context_by_trade_id for trade in ordered):
            counts["preAdmissionFundingUnknownCount"] += 1

        reject_reason = ""
        if len(wallets) < 2:
            reject_reason = "wallet_count_below_2"
        else:
            counts["groupsAtLeastTwoWallets"] += 1
        if not reject_reason:
            if aggregate < minimum_notional:
                reject_reason = "aggregate_below_minimum"
            else:
                counts["groupsAggregateAboveMinimum"] += 1
        if not reject_reason:
            if time_span > 60.0:
                reject_reason = "time_band_exceeded"
            else:
                counts["groupsWithinTimeBand"] += 1
        if not reject_reason:
            if price_band > SPLIT_WALLET_PRICE_BAND:
                reject_reason = "price_band_exceeded"
            else:
                counts["groupsWithinPriceBand"] += 1

        if not reject_reason:
            if not funding_resolver_available:
                counts["groupsSkippedFundingResolverDisabled"] += 1
                reject_reason = "funding_resolver_unavailable"
            elif not pre_admission_funding_trace_enabled or any(
                trade.trade_id not in funding_context_by_trade_id for trade in ordered if trade.trade_id in pre_pool_ids
            ):
                counts["groupsSkippedFundingNotTraced"] += 1
                reject_reason = "funding_not_traced"
            elif strict_keys:
                counts["groupsStrictNonProxySharedFundingKey"] += len(strict_keys)
                for strict_key in strict_keys:
                    strict_group_keys.add((condition_id, direction, strict_key))
            elif proxy_only or proxy_keys:
                counts["groupsRejectedProxyOnly"] += 1
                reject_reason = "proxy_only_group"
                for proxy_key in proxy_keys:
                    proxy_group_keys.add((condition_id, direction, proxy_key))
            else:
                counts["groupsTimingOnlyNoStructuralEvidence"] += 1
                reject_reason = "timing_only_no_structural_evidence"

        if reject_reason:
            rejected = _diagnostic_group_record(
                stage="pre_admission_near_miss_group_rejected",
                reason="strict_shared_funding_group" if strict_keys else "timing_or_funding_group",
                rejected_reason=reject_reason,
                condition_id=condition_id,
                direction=direction,
                wallets=len(wallets),
                aggregate=aggregate,
                time_span=time_span,
                price_band=price_band,
                funding_grade=group_grade,
                strict_funding=bool(strict_keys),
                proxy_only=proxy_only or bool(proxy_keys),
                normal_duplicate=False,
                below_floor=False,
                cap_hit=any(trade.trade_id not in pre_pool_ids for trade in ordered),
            )
            rejected_groups.append(rejected)
            near_miss_records.append(rejected)

    grouped_metadata_ids = {
        str(metadata.get("groupedCandidateId") or "")
        for metadata in admission_metadata.values()
        if str(metadata.get("candidateAdmissionReason") or "") in STRUCTURAL_PRE_ADMISSION_GROUP_REASONS
        and str(metadata.get("groupedCandidateId") or "")
    }
    counts["groupsAdmittedPendingScoring"] = len(grouped_metadata_ids)
    counts["suspiciousFundingAttempts"] = sum(
        1
        for metadata in admission_metadata.values()
        if metadata.get("candidateAdmissionReason") == "suspicious_recent_funding"
    )
    counts["dormantReactivationAttempts"] = sum(
        1
        for metadata in admission_metadata.values()
        if metadata.get("candidateAdmissionReason") == "dormant_reactivation"
    )

    top_by_count = []
    top_by_near_miss = []
    for condition_id, condition_trades in sorted(by_condition.items()):
        aggregate = sum((trade.notional for trade in condition_trades), Decimal("0"))
        item = {
            "conditionId": condition_id,
            "subThresholdAboveFloorCount": len(condition_trades),
            "aggregateNotional": _fmt_decimal(aggregate),
        }
        top_by_count.append(item)
        top_by_near_miss.append(item)
    top_by_count.sort(key=lambda item: (int(item["subThresholdAboveFloorCount"]), item["conditionId"]), reverse=True)
    top_by_near_miss.sort(key=lambda item: (Decimal(str(item["aggregateNotional"])), item["conditionId"]), reverse=True)

    skipped_counter = Counter(skipped_reasons.values())
    missing_trace_count = sum(1 for trade in pre_admission_pool if trade.trade_id not in funding_context_by_trade_id)
    if missing_trace_count:
        skipped_counter["funding_context_missing"] += missing_trace_count
    if not pre_admission_funding_trace_enabled and pre_admission_pool:
        skipped_counter["blockchain_disabled"] += len(pre_admission_pool)
    funding_unknown_rate = (
        counts["preAdmissionFundingUnknownCount"] / counts["subThresholdAboveStructuralFloorTrades"]
        if counts["subThresholdAboveStructuralFloorTrades"]
        else 0.0
    )
    assessment_status = _funding_assessment_status(
        resolver_available=funding_resolver_available,
        grouped_count=counts["groupedConditionDirectionGroups"],
        trace_attempted_count=len(attempted_ids),
        strict_group_count=len(strict_group_keys),
        funding_unknown_count=counts["preAdmissionFundingUnknownCount"],
    )
    health_attempted = int(health.get("fundingTraceAttemptedCount", len(attempted_ids)) if health else len(attempted_ids))
    health_succeeded = int(health.get("fundingTraceSucceededCount", len(succeeded_ids)) if health else len(succeeded_ids))
    health_failed = int(health.get("fundingTraceFailedCount", 0) if health else 0)
    health_skipped = int(health.get("fundingTraceSkippedCount", sum(skipped_counter.values())) if health else sum(skipped_counter.values()))
    health_skipped_reasons = (
        health.get("fundingTraceSkippedReasonDistribution", _counter_to_plain_dict(skipped_counter))
        if health
        else _counter_to_plain_dict(skipped_counter)
    )
    endpoint_failure_distribution = dict(
        health.get("fundingTraceEndpointFailureDistribution") or {}
    ) if health else {}
    endpoint_summary = list(health.get("fundingTraceEndpointSummary") or []) if health else []

    return {
        "enabled": True,
        "minimum_notional": _fmt_decimal(minimum_notional),
        "candidate_floor_notional": _fmt_decimal(floor),
        "minimumNotional": _fmt_decimal(minimum_notional),
        "candidateFloorNotional": _fmt_decimal(floor),
        "prefundingPoolCap": STRUCTURAL_PRE_ADMISSION_MAX_PREFUNDING_TRADES_PER_CONDITION,
        "addedPerConditionCap": STRUCTURAL_PRE_ADMISSION_MAX_ADDED_PER_CONDITION,
        "conditionIdsProcessed": len(by_condition),
        "counts": _counter_to_plain_dict(counts),
        "fundingResolverAvailable": bool(funding_resolver_available),
        "fundingResolverDisabledReason": funding_resolver_disabled_reason,
        "fundingResolverAuthError": bool(funding_resolver_auth_error),
        "fundingResolverUnavailableReason": funding_resolver_unavailable_reason,
        "fundingResolverFunctionalStatus": str(health.get("fundingResolverFunctionalStatus") or "") if health else "",
        "fundingResolverEndpointLabel": funding_resolver_endpoint_label,
        "fundingResolverLastError": funding_resolver_last_error,
        "fundingTraceAttemptedCount": health_attempted,
        "fundingTraceSucceededCount": health_succeeded,
        "fundingTraceFailedCount": health_failed,
        "fundingTraceSkippedCount": health_skipped,
        "fundingTraceSkippedReasonDistribution": dict(health_skipped_reasons or {}),
        "fundingTraceCoverageRatio": round((health_succeeded / health_attempted) if health_attempted else 0.0, 4),
        "fundingTraceEndpointPoolSize": int(health.get("fundingTraceEndpointPoolSize") or 0) if health else 0,
        "fundingTraceEndpointAvailableCount": int(health.get("fundingTraceEndpointAvailableCount") or 0) if health else 0,
        "fundingTraceEndpointCooldownCount": int(health.get("fundingTraceEndpointCooldownCount") or 0) if health else 0,
        "fundingTraceEndpointFailureDistribution": endpoint_failure_distribution,
        "fundingTraceEndpointSummary": endpoint_summary,
        "fundingTraceRateLimitedCount": int(health.get("fundingTraceRateLimitedCount") or 0) if health else 0,
        "fundingTraceRetryCount": int(health.get("fundingTraceRetryCount") or 0) if health else 0,
        "fundingTraceFallbackEndpointCount": int(health.get("fundingTraceFallbackEndpointCount") or 0) if health else 0,
        "fundingTraceLogChunksAttempted": int(health.get("fundingTraceLogChunksAttempted") or 0) if health else 0,
        "fundingTraceLogChunksSucceeded": int(health.get("fundingTraceLogChunksSucceeded") or 0) if health else 0,
        "fundingTraceLogChunksFailed": int(health.get("fundingTraceLogChunksFailed") or 0) if health else 0,
        "fundingTraceLogChunksRateLimited": int(health.get("fundingTraceLogChunksRateLimited") or 0) if health else 0,
        "fundingTraceCacheHitCount": int(health.get("fundingTraceCacheHitCount") or 0) if health else 0,
        "fundingTraceCacheMissCount": int(health.get("fundingTraceCacheMissCount") or 0) if health else 0,
        "fundingTracePersistentCacheEnabled": bool(health.get("fundingTracePersistentCacheEnabled")) if health else False,
        "fundingTracePersistentCacheHitCount": int(health.get("fundingTracePersistentCacheHitCount") or 0) if health else 0,
        "fundingTracePersistentCacheMissCount": int(health.get("fundingTracePersistentCacheMissCount") or 0) if health else 0,
        "fundingTracePersistentCacheWriteCount": int(health.get("fundingTracePersistentCacheWriteCount") or 0) if health else 0,
        "fundingTracePersistentCacheExpiredCount": int(health.get("fundingTracePersistentCacheExpiredCount") or 0) if health else 0,
        "fundingTracePersistentCacheFailureCooldownCount": int(health.get("fundingTracePersistentCacheFailureCooldownCount") or 0) if health else 0,
        "fundingTracePersistentCacheSchemaVersion": int(health.get("fundingTracePersistentCacheSchemaVersion") or 0) if health else 0,
        "preAdmissionFundingTraceEnabled": bool(pre_admission_funding_trace_enabled),
        "preAdmissionFundingTraceAttemptedCount": len(attempted_ids),
        "preAdmissionFundingTraceSucceededCount": len(succeeded_ids),
        "preAdmissionFundingTraceFailedCount": max(0, len(attempted_ids) - len(succeeded_ids)),
        "preAdmissionFundingTraceSkippedCount": sum(skipped_counter.values()),
        "preAdmissionFundingTraceSkippedReasonDistribution": _counter_to_plain_dict(skipped_counter),
        "preAdmissionStrictFundingGroupsFound": len(strict_group_keys),
        "preAdmissionProxyOnlyGroupsFound": len(proxy_group_keys),
        "preAdmissionFundingUnknownCount": counts["preAdmissionFundingUnknownCount"],
        "preAdmissionFundingUnknownRate": round(funding_unknown_rate, 4),
        "preAdmissionFundingAssessmentStatus": assessment_status,
        "nearMissGroups": len(rejected_groups),
        "topConditionIdsBySubThresholdAboveFloorCount": top_by_count[:20],
        "topConditionIdsByNearMissAggregateNotional": top_by_near_miss[:20],
        "topRejectedGroups": sorted(
            rejected_groups,
            key=lambda item: (Decimal(str(item.get("aggregateNotional") or "0")), str(item.get("conditionId") or "")),
            reverse=True,
        )[:20],
        "candidateAdmissionNearMissRecords": near_miss_records[:250],
    }


def _finalize_structural_pre_admission_funnel(
    funnel: dict[str, object] | None,
    cases: list[FlaggedCase],
) -> dict[str, object] | None:
    if not funnel:
        return funnel
    counts = funnel.setdefault("counts", {})
    if not isinstance(counts, dict):
        counts = {}
        funnel["counts"] = counts
    rejected_reason_counts: Counter[str] = Counter()
    grouped_rejected_opening: set[str] = set()
    grouped_validated: set[str] = set()
    for case in cases:
        raw = case.raw_metrics
        reason = str(raw.get("candidateAdmissionReason") or "").strip()
        if not reason:
            continue
        stage = str(raw.get("candidateAdmissionStage") or "").strip()
        rejected_reason = str(raw.get("candidateAdmissionRejectedReason") or "").strip()
        group_id = str(raw.get("groupedCandidateId") or "").strip()
        if rejected_reason:
            rejected_reason_counts[rejected_reason] += 1
        if reason in STRUCTURAL_PRE_ADMISSION_GROUP_REASONS:
            key = group_id or case.trade.trade_id
            if stage == "pre_admitted_validated":
                grouped_validated.add(key)
            elif rejected_reason == "opening_exposure_not_confirmed":
                grouped_rejected_opening.add(key)
        elif reason == "suspicious_recent_funding" and stage == "pre_admitted_validated":
            counts["suspiciousFundingValidated"] = int(counts.get("suspiciousFundingValidated", 0)) + 1
        elif reason == "dormant_reactivation" and stage == "pre_admitted_validated":
            counts["dormantReactivationValidated"] = int(counts.get("dormantReactivationValidated", 0)) + 1

        if rejected_reason == "near_certainty_suppressed":
            counts["rejectedNearCertainty"] = int(counts.get("rejectedNearCertainty", 0)) + 1
        elif rejected_reason in {"yield_farm_suppressed", "theta_decay_suppressed", "stale_or_resolution_gap"}:
            counts["rejectedYieldThetaStale"] = int(counts.get("rejectedYieldThetaStale", 0)) + 1
        elif rejected_reason == "high_impact_repricing_only":
            counts["rejectedHighImpactRepricingOnly"] = int(counts.get("rejectedHighImpactRepricingOnly", 0)) + 1
        elif rejected_reason == "mechanical_repricing":
            counts["rejectedMechanicalRepricing"] = int(counts.get("rejectedMechanicalRepricing", 0)) + 1

    counts["groupsRejectedAfterScoringOpeningExposure"] = len(grouped_rejected_opening)
    counts["groupsValidatedAfterScoring"] = len(grouped_validated)
    funnel["preAdmissionRejectedReasonDistribution"] = _counter_to_plain_dict(rejected_reason_counts)
    funnel["validatedPreAdmissionCount"] = sum(
        1
        for case in cases
        if case.raw_metrics.get("candidateAdmissionStage") == "pre_admitted_validated"
    )
    funnel["rejectedAfterScoringCount"] = sum(
        1
        for case in cases
        if case.raw_metrics.get("candidateAdmissionStage") == "pre_admitted_rejected"
    )
    return funnel


def _structural_pre_admission_funnel_markdown(funnel: dict[str, object] | None) -> str:
    if not funnel:
        return "# Candidate Admission Funnel\n\n- Structural pre-admission diagnostic: unavailable\n"
    counts = funnel.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    lines = [
        "# Candidate Admission Funnel",
        "",
        f"- Enabled: {funnel.get('enabled', False)}",
        f"- Minimum notional: {funnel.get('minimumNotional') or funnel.get('minimum_notional', '')}",
        f"- Candidate floor notional: {funnel.get('candidateFloorNotional') or funnel.get('candidate_floor_notional', '')}",
        f"- Prefunding pool cap: {funnel.get('prefundingPoolCap', '')}",
        f"- Added-per-condition cap: {funnel.get('addedPerConditionCap', '')}",
        f"- Condition IDs processed: {funnel.get('conditionIdsProcessed', 0)}",
        f"- Funding resolver available: {funnel.get('fundingResolverAvailable', False)}",
        f"- Funding resolver functional status: {funnel.get('fundingResolverFunctionalStatus', '') or 'unknown'}",
        f"- Funding resolver auth error: {funnel.get('fundingResolverAuthError', False)}",
        f"- Funding resolver unavailable reason: {funnel.get('fundingResolverUnavailableReason', '') or 'none'}",
        f"- Funding resolver disabled reason: {funnel.get('fundingResolverDisabledReason', '') or 'none'}",
        f"- Funding resolver endpoint: {funnel.get('fundingResolverEndpointLabel', '') or 'unknown'}",
        f"- Pre-admission funding trace enabled: {funnel.get('preAdmissionFundingTraceEnabled', False)}",
        f"- Funding assessment status: {funnel.get('preAdmissionFundingAssessmentStatus', 'unknown')}",
        "",
        "## Stage Counts",
    ]
    for key in (
        "totalRawTradesConsidered",
        "normalCandidateTrades",
        "belowNormalThresholdTrades",
        "subThresholdAboveStructuralFloorTrades",
        "belowStructuralFloorTrades",
        "subThresholdUsableConditionIdTrades",
        "subThresholdNormalizedDirectionTrades",
        "groupedConditionDirectionGroups",
        "groupsAtLeastTwoWallets",
        "groupsAggregateAboveMinimum",
        "groupsWithinTimeBand",
        "groupsWithinPriceBand",
        "groupsTimingOnlyNoStructuralEvidence",
        "groupsStrictNonProxySharedFundingKey",
        "groupsFundingGradeDirectStrict",
        "groupsFundingGradeSuspiciousDirect",
        "groupsFundingGradeMultiHopUnknown",
        "groupsFundingGradeCexProxy",
        "groupsFundingGradeBridgeProxy",
        "groupsFundingGradeNone",
        "groupsFundingGradeUnknown",
        "groupsSkippedFundingResolverDisabled",
        "groupsSkippedFundingNotTraced",
        "groupsRejectedProxyOnly",
        "groupsAdmittedPendingScoring",
        "groupsRejectedAfterScoringOpeningExposure",
        "groupsValidatedAfterScoring",
        "suspiciousFundingAttempts",
        "suspiciousFundingValidated",
        "dormantReactivationAttempts",
        "dormantReactivationValidated",
        "rejectedNearCertainty",
        "rejectedYieldThetaStale",
        "rejectedHighImpactRepricingOnly",
        "rejectedMechanicalRepricing",
        "rejectedDuplicateNormalCandidate",
        "rejectedCapHit",
    ):
        lines.append(f"- {key}: {counts.get(key, 0)}")
    lines.extend(
        [
            "",
            "## Funding Trace",
            f"- attempted: {funnel.get('preAdmissionFundingTraceAttemptedCount', 0)}",
            f"- succeeded: {funnel.get('preAdmissionFundingTraceSucceededCount', 0)}",
            f"- failed: {funnel.get('preAdmissionFundingTraceFailedCount', 0)}",
            f"- skipped: {funnel.get('preAdmissionFundingTraceSkippedCount', 0)}",
            f"- strict funding groups found: {funnel.get('preAdmissionStrictFundingGroupsFound', 0)}",
            f"- proxy-only groups found: {funnel.get('preAdmissionProxyOnlyGroupsFound', 0)}",
            f"- funding unknown count: {funnel.get('preAdmissionFundingUnknownCount', 0)}",
            f"- funding unknown rate: {funnel.get('preAdmissionFundingUnknownRate', 0)}",
            f"- endpoint pool size: {funnel.get('fundingTraceEndpointPoolSize', 0)}",
            f"- endpoint available count: {funnel.get('fundingTraceEndpointAvailableCount', 0)}",
            f"- endpoint cooldown count: {funnel.get('fundingTraceEndpointCooldownCount', 0)}",
            f"- endpoint failures: {funnel.get('fundingTraceEndpointFailureDistribution', {})}",
            f"- rate-limited trace count: {funnel.get('fundingTraceRateLimitedCount', 0)}",
            f"- retry count: {funnel.get('fundingTraceRetryCount', 0)}",
            f"- fallback endpoint count: {funnel.get('fundingTraceFallbackEndpointCount', 0)}",
            f"- log chunks attempted: {funnel.get('fundingTraceLogChunksAttempted', 0)}",
            f"- log chunks succeeded: {funnel.get('fundingTraceLogChunksSucceeded', 0)}",
            f"- log chunks failed: {funnel.get('fundingTraceLogChunksFailed', 0)}",
            f"- cache hits: {funnel.get('fundingTraceCacheHitCount', 0)}",
            f"- cache misses: {funnel.get('fundingTraceCacheMissCount', 0)}",
            "",
            "## Interpretation",
            _funding_funnel_interpretation(funnel, counts),
            "",
            "## Top Rejected Groups",
        ]
    )
    rejected = funnel.get("topRejectedGroups", [])
    if isinstance(rejected, list) and rejected:
        for item in rejected[:20]:
            if not isinstance(item, dict):
                continue
            lines.append(
                "- "
                f"{item.get('conditionId', '')} {item.get('economicDirection', '')}: "
                f"wallets={item.get('walletCount', 0)}, "
                f"aggregate={item.get('aggregateNotional', '')}, "
                f"time={item.get('timeSpanMinutes', '')}, "
                f"priceBand={item.get('priceBand', '')}, "
                f"grade={item.get('fundingEvidenceGrade', '')}, "
                f"proxyOnly={item.get('proxyOnly', '')}, "
                f"reason={item.get('candidateAdmissionRejectedReason', '')}"
            )
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _candidate_admission_near_miss_records(funnel: dict[str, object] | None) -> list[dict[str, object]]:
    if not funnel:
        return []
    records = funnel.get("candidateAdmissionNearMissRecords", [])
    if not isinstance(records, list):
        return []
    return [dict(record) for record in records if isinstance(record, dict)]


def _group_funding_grades(
    trades: list[Trade],
    funding_context_by_trade_id: dict[str, FundingContext],
) -> list[str]:
    grades: list[str] = []
    for trade in trades:
        context = funding_context_by_trade_id.get(trade.trade_id)
        if context is None:
            grades.append(FUNDING_EVIDENCE_UNKNOWN)
            continue
        if context.error:
            grades.append(FUNDING_EVIDENCE_UNKNOWN)
            continue
        grades.append(grade_funding_evidence(context) or FUNDING_EVIDENCE_NONE)
    return grades


def _common_diagnostic_grade(grades: list[str]) -> str:
    values = {str(grade or FUNDING_EVIDENCE_UNKNOWN) for grade in grades}
    values.discard("")
    if not values:
        return "unknown"
    if len(values) == 1:
        return next(iter(values))
    return "; ".join(sorted(values))


def _funding_grade_counter_suffix(grade: str) -> str:
    return {
        FUNDING_EVIDENCE_DIRECT_STRICT: "DirectStrict",
        FUNDING_EVIDENCE_SUSPICIOUS_DIRECT: "SuspiciousDirect",
        FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN: "MultiHopUnknown",
        FUNDING_EVIDENCE_CEX_PROXY: "CexProxy",
        FUNDING_EVIDENCE_BRIDGE_PROXY: "BridgeProxy",
        FUNDING_EVIDENCE_NONE: "None",
        FUNDING_EVIDENCE_UNKNOWN: "Unknown",
    }.get(str(grade or FUNDING_EVIDENCE_UNKNOWN), "Unknown")


def _diagnostic_strict_keys(
    trades: list[Trade],
    funding_context_by_trade_id: dict[str, FundingContext],
) -> set[str]:
    grouped: dict[str, set[str]] = {}
    for trade in trades:
        context = funding_context_by_trade_id.get(trade.trade_id)
        if context is None:
            continue
        grade = grade_funding_evidence(context)
        strict_key = str(context.funding_graph_key_strict or "").strip()
        if strict_key and grade in STRUCTURAL_PRE_ADMISSION_ELIGIBLE_FUNDING_GRADES and grade not in PROXY_FUNDING_EVIDENCE_GRADES:
            grouped.setdefault(strict_key, set()).add(trade.wallet)
    return {key for key, wallets in grouped.items() if len({wallet for wallet in wallets if wallet}) >= 2}


def _diagnostic_proxy_keys(
    trades: list[Trade],
    funding_context_by_trade_id: dict[str, FundingContext],
) -> set[str]:
    grouped: dict[str, set[str]] = {}
    for trade in trades:
        context = funding_context_by_trade_id.get(trade.trade_id)
        if context is None:
            continue
        proxy_key = str(context.funding_graph_key_proxy or context.funding_fingerprint or "").strip()
        if proxy_key and grade_funding_evidence(context) in PROXY_FUNDING_EVIDENCE_GRADES:
            grouped.setdefault(proxy_key, set()).add(trade.wallet)
    return {key for key, wallets in grouped.items() if len({wallet for wallet in wallets if wallet}) >= 2}


def _diagnostic_group_proxy_only(
    trades: list[Trade],
    funding_context_by_trade_id: dict[str, FundingContext],
) -> bool:
    strict_keys = _diagnostic_strict_keys(trades, funding_context_by_trade_id)
    proxy_keys = _diagnostic_proxy_keys(trades, funding_context_by_trade_id)
    return bool(proxy_keys and not strict_keys)


def _diagnostic_group_record(
    *,
    stage: str,
    reason: str,
    rejected_reason: str,
    condition_id: str,
    direction: str,
    wallets: int,
    aggregate: Decimal,
    time_span: float,
    price_band: Decimal,
    funding_grade: str,
    strict_funding: bool,
    proxy_only: bool,
    normal_duplicate: bool,
    below_floor: bool,
    cap_hit: bool,
) -> dict[str, object]:
    return {
        "candidateAdmissionStage": stage,
        "candidateAdmissionReason": reason,
        "candidateAdmissionRejectedReason": rejected_reason,
        "conditionId": condition_id,
        "economicDirection": direction,
        "walletCount": wallets,
        "aggregateNotional": _fmt_decimal(aggregate),
        "timeSpanMinutes": f"{time_span:.1f}",
        "priceBand": _fmt_decimal(price_band),
        "fundingEvidenceGrade": funding_grade,
        "strictFunding": "Yes" if strict_funding else "No",
        "proxyOnly": "Yes" if proxy_only else "No",
        "openingExposureValidated": "No",
        "normalCandidateDuplicate": "Yes" if normal_duplicate else "No",
        "belowFloor": "Yes" if below_floor else "No",
        "capHit": "Yes" if cap_hit else "No",
    }


def _counter_to_plain_dict(counter: Counter[str] | dict[str, int]) -> dict[str, int]:
    return {str(key): int(value) for key, value in sorted(counter.items())}


def _funding_health_to_dict(
    health: FundingResolverHealth | dict[str, object] | None,
) -> dict[str, object]:
    if health is None:
        return {}
    if isinstance(health, FundingResolverHealth):
        return health.to_dict()
    return dict(health)


def _funding_health_for_raw_metrics(
    funding_context: FundingContext,
    health: FundingResolverHealth | dict[str, object] | None,
) -> dict[str, str]:
    health_dict = _funding_health_to_dict(health)
    reason = str(
        health_dict.get("fundingResolverDisabledReason")
        or health_dict.get("fundingResolverLastError")
        or funding_context.error
        or ""
    )
    resolver_available = health_dict.get("fundingResolverAvailable")
    if resolver_available is None:
        resolver_available = not bool(funding_context.error)
    auth_error = bool(health_dict.get("fundingResolverAuthError")) or _funding_auth_error_text(reason)
    return {
        "fundingResolverAvailable": "Yes" if bool(resolver_available) else "No",
        "fundingResolverDisabledReason": str(health_dict.get("fundingResolverDisabledReason") or ""),
        "fundingResolverAuthError": "Yes" if auth_error else "No",
        "fundingResolverUnavailableReason": str(health_dict.get("fundingResolverUnavailableReason") or ""),
        "fundingResolverFunctionalStatus": str(health_dict.get("fundingResolverFunctionalStatus") or ""),
        "fundingResolverEndpointLabel": str(health_dict.get("fundingResolverEndpointLabel") or ""),
        "fundingResolverLastError": str(health_dict.get("fundingResolverLastError") or funding_context.error or ""),
        "fundingTraceAttemptedCount": str(int(health_dict.get("fundingTraceAttemptedCount") or 0)),
        "fundingTraceSucceededCount": str(int(health_dict.get("fundingTraceSucceededCount") or 0)),
        "fundingTraceFailedCount": str(int(health_dict.get("fundingTraceFailedCount") or 0)),
        "fundingTraceSkippedCount": str(int(health_dict.get("fundingTraceSkippedCount") or 0)),
        "fundingTraceSkippedReasonDistribution": json.dumps(
            health_dict.get("fundingTraceSkippedReasonDistribution") or {},
            sort_keys=True,
        ),
        "fundingTraceCoverageRatio": str(health_dict.get("fundingTraceCoverageRatio") or "0.0"),
        "fundingTraceEndpointPoolSize": str(int(health_dict.get("fundingTraceEndpointPoolSize") or 0)),
        "fundingTraceEndpointAvailableCount": str(int(health_dict.get("fundingTraceEndpointAvailableCount") or 0)),
        "fundingTraceEndpointCooldownCount": str(int(health_dict.get("fundingTraceEndpointCooldownCount") or 0)),
        "fundingTraceEndpointFailureDistribution": json.dumps(
            health_dict.get("fundingTraceEndpointFailureDistribution") or {},
            sort_keys=True,
        ),
        "fundingTraceEndpointSummary": json.dumps(
            health_dict.get("fundingTraceEndpointSummary") or [],
            sort_keys=True,
        ),
        "fundingTraceRateLimitedCount": str(int(health_dict.get("fundingTraceRateLimitedCount") or 0)),
        "fundingTraceRetryCount": str(int(health_dict.get("fundingTraceRetryCount") or 0)),
        "fundingTraceFallbackEndpointCount": str(int(health_dict.get("fundingTraceFallbackEndpointCount") or 0)),
        "fundingTraceLogChunksAttempted": str(int(health_dict.get("fundingTraceLogChunksAttempted") or 0)),
        "fundingTraceLogChunksSucceeded": str(int(health_dict.get("fundingTraceLogChunksSucceeded") or 0)),
        "fundingTraceLogChunksFailed": str(int(health_dict.get("fundingTraceLogChunksFailed") or 0)),
        "fundingTraceLogChunksRateLimited": str(int(health_dict.get("fundingTraceLogChunksRateLimited") or 0)),
        "fundingTraceCacheHitCount": str(int(health_dict.get("fundingTraceCacheHitCount") or 0)),
        "fundingTraceCacheMissCount": str(int(health_dict.get("fundingTraceCacheMissCount") or 0)),
        "fundingTracePersistentCacheEnabled": "Yes" if bool(health_dict.get("fundingTracePersistentCacheEnabled")) else "No",
        "fundingTracePersistentCacheHitCount": str(int(health_dict.get("fundingTracePersistentCacheHitCount") or 0)),
        "fundingTracePersistentCacheMissCount": str(int(health_dict.get("fundingTracePersistentCacheMissCount") or 0)),
        "fundingTracePersistentCacheWriteCount": str(int(health_dict.get("fundingTracePersistentCacheWriteCount") or 0)),
        "fundingTracePersistentCacheExpiredCount": str(int(health_dict.get("fundingTracePersistentCacheExpiredCount") or 0)),
        "fundingTracePersistentCacheFailureCooldownCount": str(int(health_dict.get("fundingTracePersistentCacheFailureCooldownCount") or 0)),
        "fundingTracePersistentCacheSchemaVersion": str(int(health_dict.get("fundingTracePersistentCacheSchemaVersion") or 0)),
    }


def _funding_auth_error_text(value: str) -> bool:
    text = (value or "").lower()
    return any(token in text for token in ("401", "403", "unauthorized", "forbidden", "auth"))


def _funding_assessment_status(
    *,
    resolver_available: bool,
    grouped_count: int,
    trace_attempted_count: int,
    strict_group_count: int,
    funding_unknown_count: int = 0,
) -> str:
    if not resolver_available:
        return "funding_unavailable_not_assessed"
    if grouped_count <= 0:
        return "no_grouped_subthreshold_candidates"
    if trace_attempted_count <= 0:
        return "grouped_candidates_not_traced"
    if funding_unknown_count > 0 and strict_group_count <= 0:
        return "funding_partially_unknown"
    if strict_group_count <= 0:
        return "assessed_no_strict_funding_groups"
    return "strict_funding_groups_found"


def _funding_funnel_interpretation(funnel: dict[str, object], counts: dict[str, object]) -> str:
    status = str(funnel.get("preAdmissionFundingAssessmentStatus") or "")
    if status == "funding_unavailable_not_assessed":
        reason = str(funnel.get("fundingResolverDisabledReason") or funnel.get("fundingResolverLastError") or "").strip()
        detail = f" ({reason})" if reason else ""
        return f"- Funding evidence: not assessed because resolver unavailable{detail}."
    if status == "no_grouped_subthreshold_candidates":
        return "- Grouped structural pre-admission did not run because no grouped above-floor sub-threshold candidates existed."
    if status == "grouped_candidates_not_traced":
        return "- Grouped candidates existed, but funding traces were not attempted for the pre-candidate pool."
    if status == "assessed_no_strict_funding_groups":
        return "- Funding traces were attempted; no strict non-proxy shared funding group was found in the assessed pool."
    if status == "funding_partially_unknown":
        return "- Funding traces were attempted, but some grouped funding evidence was unavailable or incomplete; absence of strict funding is not fully proven."
    if status == "strict_funding_groups_found":
        return "- Strict non-proxy shared funding groups were found and passed to admission validation."
    if int(counts.get("groupsAggregateAboveMinimum") or 0) == 0:
        return "- Grouped candidates existed but failed wallet-count or aggregate-notional criteria before funding evidence could matter."
    if int(counts.get("groupsWithinTimeBand") or 0) == 0:
        return "- Grouped candidates existed but failed the tight time-band criterion before funding evidence could matter."
    return "- Funding assessment status could not be classified from saved funnel fields."


def _funding_availability_report_lines(health: dict[str, object] | None) -> list[str]:
    if not isinstance(health, dict) or not health:
        return []
    available = bool(health.get("fundingResolverAvailable"))
    auth_error = bool(health.get("fundingResolverAuthError"))
    functional_status = str(health.get("fundingResolverFunctionalStatus") or "").strip()
    trace_mode = str(health.get("fundingTraceMode") or "live_rpc").strip()
    evidence_interpretation = str(health.get("fundingEvidenceInterpretation") or "").strip()
    trace_succeeded = int(float(str(health.get("fundingTraceSucceededCount") or "0") or 0))
    trace_attempted = int(float(str(health.get("fundingTraceAttemptedCount") or "0") or 0))
    rate_limited_count = int(float(str(health.get("fundingTraceRateLimitedCount") or "0") or 0))
    last_error = str(health.get("fundingResolverLastError") or health.get("fundingResolverDisabledReason") or "").strip()
    detail_lines = [
        "- Funding trace endpoint pool: "
        f"size={health.get('fundingTraceEndpointPoolSize', 0)}, "
        f"available={health.get('fundingTraceEndpointAvailableCount', 0)}, "
        f"cooldown={health.get('fundingTraceEndpointCooldownCount', 0)}",
        "- Funding trace attempts/succeeded/failed/skipped: "
        f"{trace_attempted}/"
        f"{health.get('fundingTraceSucceededCount', 0)}/"
        f"{health.get('fundingTraceFailedCount', 0)}/"
        f"{health.get('fundingTraceSkippedCount', 0)}",
        "- Funding trace retries/fallbacks/rate-limits: "
        f"{health.get('fundingTraceRetryCount', 0)}/"
        f"{health.get('fundingTraceFallbackEndpointCount', 0)}/"
        f"{rate_limited_count}",
        "- Funding trace log chunks attempted/succeeded/failed: "
        f"{health.get('fundingTraceLogChunksAttempted', 0)}/"
        f"{health.get('fundingTraceLogChunksSucceeded', 0)}/"
        f"{health.get('fundingTraceLogChunksFailed', 0)}",
        "- Funding trace cache hits/misses: "
        f"{health.get('fundingTraceCacheHitCount', 0)}/"
        f"{health.get('fundingTraceCacheMissCount', 0)}",
        "- Funding trace persistent cache enabled/hits/misses/writes: "
        f"{health.get('fundingTracePersistentCacheEnabled', False)}/"
        f"{health.get('fundingTracePersistentCacheHitCount', 0)}/"
        f"{health.get('fundingTracePersistentCacheMissCount', 0)}/"
        f"{health.get('fundingTracePersistentCacheWriteCount', 0)}",
    ]
    if trace_mode:
        detail_lines.insert(0, f"- Funding trace mode: {trace_mode}")
    if evidence_interpretation:
        detail_lines.insert(1, f"- Funding evidence interpretation: {evidence_interpretation}")
    if functional_status == "disabled_no_rpc_mode":
        return [
            "- Funding resolver: disabled - no_rpc_mode",
            "- Funding evidence: blockchain funding trace was disabled; funding evidence is unknown, not none.",
            *detail_lines,
        ]
    if functional_status == "cache_only":
        return [
            "- Funding resolver: cache-only mode; live RPC was not used",
            "- Funding evidence: cache misses are unknown, not none.",
            *detail_lines,
        ]
    if available or functional_status == "available_for_funding_trace" or trace_succeeded > 0:
        return ["- Funding resolver: available for funding trace", *detail_lines]
    if functional_status == "not_assessed" and trace_attempted == 0:
        return [
            "- Funding resolver: not assessed; no funding trace candidates",
            "- Funding evidence: not assessed because no funding trace was requested",
            *detail_lines,
        ]
    if functional_status in {"available_lightweight_only", "rate_limited_for_funding_trace"} or (
        trace_attempted > 0 and trace_succeeded <= 0 and rate_limited_count > 0
    ):
        return [
            "- Funding resolver: lightweight RPC available, funding trace blocked by rate limits",
            "- Funding evidence: not assessed because resolver unavailable",
            *detail_lines,
        ]
    if auth_error:
        return [
            "- Funding resolver: unavailable - auth_error",
            "- Funding evidence: not assessed because resolver unavailable",
            *detail_lines,
        ]
    classified_reason = str(health.get("fundingResolverUnavailableReason") or "").strip()
    if classified_reason:
        return [
            f"- Funding resolver: unavailable - {classified_reason}",
            "- Funding evidence: not assessed because resolver unavailable",
            *detail_lines,
        ]
    lowered = last_error.lower()
    if "429" in lowered or "rate" in lowered:
        reason = "rate_limited"
    elif last_error:
        reason = "network_or_rpc_error"
    else:
        reason = "not_configured"
    return [
        f"- Funding resolver: unavailable - {reason}",
        "- Funding evidence: not assessed because resolver unavailable",
        *detail_lines,
    ]


def _pre_admission_direction_hint(trade: Trade) -> str:
    normalized = normalize_cluster_direction(trade.side, trade.outcome, trade.price)
    if normalized.cluster_normalization_status == "normalized":
        return normalized.cluster_direction
    return ""


def _trade_group_time_span_minutes(trades: list[Trade]) -> float:
    if len(trades) <= 1:
        return 0.0
    ordered = sorted(trades, key=_trade_sort_key)
    return max((ordered[-1].timestamp - ordered[0].timestamp).total_seconds() / 60.0, 0.0)


def _trade_group_price_band(trades: list[Trade]) -> Decimal:
    prices = [trade.price for trade in trades]
    return max(prices) - min(prices) if prices else Decimal("0")


def _common_funding_grade(
    trades: list[Trade],
    funding_context_by_trade_id: dict[str, FundingContext],
) -> str:
    grades = {
        grade_funding_evidence(
            funding_context_by_trade_id.get(trade.trade_id)
            or unknown_funding_context("funding_context_missing")
        )
        for trade in trades
    }
    grades.discard("")
    if len(grades) == 1:
        return next(iter(grades))
    ordered = [
        grade
        for grade in (
            FUNDING_EVIDENCE_SUSPICIOUS_DIRECT,
            FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN,
            FUNDING_EVIDENCE_DIRECT_STRICT,
        )
        if grade in grades
    ]
    return "; ".join(ordered)


def _annotate_preclassification_linkage(cases: list[FlaggedCase]) -> None:
    _annotate_shared_funding_links(cases)
    _annotate_coordinated_sizing_clusters(cases)


def _annotate_side_outcome_raw_metrics(cases: list[FlaggedCase]) -> None:
    for case in cases:
        metrics = normalize_side_outcome(case.trade.side, case.trade.outcome, case.trade.price).to_raw_metrics()
        if metrics.get("model_probability_basis") == "unknown" and case.raw_metrics.get("model_probability_basis"):
            metrics["model_probability_basis"] = case.raw_metrics["model_probability_basis"]
        metrics.update(normalize_cluster_direction(case.trade.side, case.trade.outcome, case.trade.price).to_raw_metrics())
        case.raw_metrics.update(metrics)


def _cluster_direction_for_trade(trade: Trade) -> str:
    normalized = normalize_cluster_direction(trade.side, trade.outcome, trade.price)
    if normalized.cluster_normalization_status == "normalized":
        return normalized.cluster_direction
    return ""


def _cluster_direction_for_case(case: FlaggedCase) -> str:
    raw = case.raw_metrics
    direction = str(raw.get("cluster_direction") or "").strip()
    if direction in {"long_yes", "long_no"} and raw.get("cluster_normalization_status") == "normalized":
        return direction
    model_direction = str(raw.get("model_economic_direction") or "").strip()
    if model_direction in {"long_yes", "long_no"} and raw.get("side_outcome_normalization_status") == "normalized":
        return model_direction
    return _cluster_direction_for_trade(case.trade)


def _annotate_hard_evidence_review(
    cases: list[FlaggedCase],
    *,
    winner_ranks_by_trade_id: dict[str, int] | None = None,
    evidence_availability_stage: str,
) -> None:
    strict_funding_groups = _hard_evidence_groups(cases, _strict_funding_group_key)
    split_wallet_groups = _hard_evidence_groups(cases, _split_wallet_group_key)
    coordinated_sizing_groups = _hard_evidence_groups(cases, _coordinated_sizing_group_key)
    winner_ranks_by_trade_id = winner_ranks_by_trade_id or {}

    for case in cases:
        _update_suspicious_funding_quality(case.raw_metrics, case.flags)
        evidence = _hard_evidence_for_case(
            case,
            strict_funding_groups=strict_funding_groups,
            split_wallet_groups=split_wallet_groups,
            coordinated_sizing_groups=coordinated_sizing_groups,
            winner_ranks_by_trade_id=winner_ranks_by_trade_id,
            evidence_availability_stage=evidence_availability_stage,
        )
        _write_hard_evidence_fields(case.raw_metrics, evidence)
        _refresh_strong_risk_attribution(case)


def _case_has_hard_evidence_review(case: FlaggedCase | dict[str, object]) -> bool:
    raw = case.raw_metrics if isinstance(case, FlaggedCase) else case
    return str(raw.get("hardEvidenceReviewTier") or "") == HARD_EVIDENCE_REVIEW_TIER


def _case_survives_output_threshold(case: FlaggedCase) -> bool:
    raw = case.raw_metrics
    structural_count = int(raw.get("structural_concern_count", "0") or 0)
    opening_exposure = raw.get("opening_exposure_flag") == "Yes"
    if _case_has_hard_evidence_review(case):
        return True
    if raw.get("hard_public_information_flag") == "Yes":
        return True
    if case.suspicion_score >= 18:
        return True
    if case.severity == "Strong Risk":
        return True
    return opening_exposure and structural_count >= 2 and case.suspicion_score >= 14


def _hard_evidence_groups(
    cases: list[FlaggedCase],
    key_func: callable,
) -> dict[str, list[FlaggedCase]]:
    grouped: dict[str, list[FlaggedCase]] = {}
    for case in cases:
        key = key_func(case)
        if key:
            grouped.setdefault(key, []).append(case)
    return grouped


def _strict_funding_group_key(case: FlaggedCase) -> str:
    raw = case.raw_metrics
    if _candidate_admission_rejected(raw):
        return ""
    if raw.get("shared_funding_source_flag") != "Yes":
        return ""
    if raw.get("cex_proxy_cluster_flag") == "Yes":
        return ""
    return str(raw.get("funding_graph_key_strict") or "").strip()


def _split_wallet_group_key(case: FlaggedCase) -> str:
    raw = case.raw_metrics
    if raw.get("split_wallet_pattern_flag") != "Yes":
        return ""
    strict_key = _strict_funding_group_key(case)
    if not strict_key:
        return ""
    condition_id = case.trade.condition_id
    direction = _cluster_direction_for_case(case)
    if not direction:
        return ""
    return f"{strict_key}|{condition_id}|{direction}"


def _coordinated_sizing_group_key(case: FlaggedCase) -> str:
    raw = case.raw_metrics
    if raw.get("coordinated_sizing_cluster_flag") != "Yes":
        return ""
    condition_id = case.trade.condition_id
    direction = _cluster_direction_for_case(case)
    if not direction:
        return ""
    return f"{condition_id}|{direction}"


def _hard_evidence_for_case(
    case: FlaggedCase,
    *,
    strict_funding_groups: dict[str, list[FlaggedCase]],
    split_wallet_groups: dict[str, list[FlaggedCase]],
    coordinated_sizing_groups: dict[str, list[FlaggedCase]],
    winner_ranks_by_trade_id: dict[str, int],
    evidence_availability_stage: str,
) -> dict[str, object]:
    raw = case.raw_metrics
    sources: list[str] = []
    source_cases: list[FlaggedCase] = []

    def add_source(source: str, members: list[FlaggedCase] | None = None) -> None:
        if source not in sources:
            sources.append(source)
        source_cases.extend(members or [case])

    split_group = split_wallet_groups.get(_split_wallet_group_key(case), [])
    if len({item.trade.wallet for item in split_group}) >= 2:
        add_source("split_wallet_pattern", split_group)

    strict_group = strict_funding_groups.get(_strict_funding_group_key(case), [])
    if len({item.trade.wallet for item in strict_group}) >= 2:
        add_source("strict_shared_funding_source", strict_group)

    if _suspicious_funding_hard_evidence_eligible(raw):
        add_source("suspicious_recent_funding")

    if raw.get("reactivated_after_dormancy_flag") == "Yes" and raw.get("opening_exposure_flag") == "Yes":
        add_source("dormant_wallet_reactivation")

    winner_rank = winner_ranks_by_trade_id.get(case.trade.trade_id)
    if (
        winner_rank is not None
        and winner_rank <= 6
        and raw.get("opening_exposure_flag") == "Yes"
        and case.trade.price <= Decimal("0.35")
    ):
        add_source("low_probability_early_winner")

    if _event_family_hard_evidence_context(raw):
        add_source("event_family_repeat_narrow_context")

    coordinated_group = coordinated_sizing_groups.get(_coordinated_sizing_group_key(case), [])
    if sources and len({item.trade.wallet for item in coordinated_group}) >= 3:
        add_source("coordinated_sizing_with_hard_evidence", coordinated_group)

    trade_ids = sorted({item.trade.trade_id for item in source_cases if item.trade.trade_id})
    wallet_ids = sorted({item.trade.wallet for item in source_cases if item.trade.wallet})
    strength = _hard_evidence_strength(sources, raw)
    primary_source = sources[0] if sources else ""
    tier = HARD_EVIDENCE_REVIEW_TIER if sources else NO_HARD_EVIDENCE_REVIEW_TIER
    return {
        "sources": sources,
        "strength": strength,
        "primary_reason": HARD_EVIDENCE_REASON_BY_SOURCE.get(primary_source, ""),
        "trade_ids": trade_ids,
        "wallet_ids": wallet_ids,
        "review_tier": tier,
        "availability_stage": evidence_availability_stage,
    }


def _event_family_hard_evidence_context(raw: dict[str, object]) -> bool:
    if raw.get("event_family_repeat_flag") != "Yes" or raw.get("opening_exposure_flag") != "Yes":
        return False
    if _metric_int_like(raw.get("related_markets_30m")) >= 2:
        return True
    if raw.get("off_hours_flag") == "Yes":
        return True
    if raw.get("liquidity_shock_signal") == "Yes":
        return True
    if _metric_int_like(raw.get("strong_timing_proof_count")) >= 1:
        return True
    hours_to_resolution = _metric_float_like(raw.get("hours_to_resolution"))
    return bool(hours_to_resolution is not None and hours_to_resolution <= 24.0)


def _funding_evidence_grade_from_raw(raw: dict[str, object]) -> str:
    return str(raw.get("funding_evidence_grade") or raw.get("fundingEvidenceGrade") or "").strip()


def _has_proxy_funding_grade(raw: dict[str, object]) -> bool:
    grade = _funding_evidence_grade_from_raw(raw)
    if grade in PROXY_FUNDING_EVIDENCE_GRADES:
        return True
    return bool(raw.get("cex_proxy_cluster_flag") == "Yes" and not str(raw.get("funding_graph_key_strict") or "").strip())


def _suspicious_funding_hard_evidence_eligible(raw: dict[str, object]) -> bool:
    if str(raw.get("suspiciousFundingHardEvidenceEligible") or "").strip() != "Yes":
        return False
    grade = _funding_evidence_grade_from_raw(raw)
    if grade in PROXY_FUNDING_EVIDENCE_GRADES:
        return False
    quality = str(raw.get("suspiciousFundingQuality") or "").strip()
    if quality != SUSPICIOUS_FUNDING_QUALITY_STRONG:
        return False
    independent_support, support_sources = _saved_suspicious_funding_independent_support(raw)
    suppressor_conflict = str(raw.get("suspiciousFundingSuppressorConflict") or "").strip() == "Yes"
    if grade == FUNDING_EVIDENCE_SUSPICIOUS_DIRECT:
        if quality == SUSPICIOUS_FUNDING_QUALITY_STRONG and not suppressor_conflict:
            return True
        return bool(
            independent_support
            and quality in {SUSPICIOUS_FUNDING_QUALITY_STRONG, SUSPICIOUS_FUNDING_QUALITY_MODERATE}
        )
    if grade == FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN:
        return independent_support and bool(support_sources)
    return False


def _update_suspicious_funding_quality(
    raw: dict[str, object],
    flags: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, str]:
    metrics = _suspicious_funding_quality_metrics(raw, flags=flags)
    raw.update(metrics)
    return metrics


def _suspicious_funding_quality_metrics(
    raw: dict[str, object],
    *,
    flags: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, str]:
    flags_set = {str(flag or "") for flag in (flags or [])}
    grade = _funding_evidence_grade_from_raw(raw) or FUNDING_EVIDENCE_UNKNOWN
    trace_succeeded = _suspicious_funding_trace_succeeded(raw, grade)
    funding_flag = str(raw.get("suspicious_funding_flag") or "").strip() == "Yes"
    proxy_only = grade in PROXY_FUNDING_EVIDENCE_GRADES or _has_proxy_funding_grade(raw)
    amount = _decimal_metric(raw.get("funding_amount_usdc"))
    trade_notional = _decimal_metric(raw.get("trade_notional_usdc"))
    minutes_before_trade = _metric_float_like(raw.get("minutes_from_funding_to_trade"))
    trace_depth = _metric_int_like(raw.get("funding_depth"))
    ratio = None
    if amount is not None and trade_notional is not None and trade_notional > 0:
        ratio = amount / trade_notional

    recent_enough = bool(minutes_before_trade is not None and 0 <= minutes_before_trade <= SUSPICIOUS_FUNDING_RECENT_MINUTES)
    amount_meaningful = bool(amount is not None and amount >= SUSPICIOUS_FUNDING_MIN_AMOUNT_USD)
    amount_aligned = bool(
        amount_meaningful
        and ratio is not None
        and SUSPICIOUS_FUNDING_AMOUNT_RATIO_MIN <= ratio <= SUSPICIOUS_FUNDING_AMOUNT_RATIO_MAX
    )
    opening_exposure = str(raw.get("opening_exposure_flag") or "").strip() == "Yes" or str(raw.get("trade_state") or "").strip() == "increase"
    independent_support, support_reasons = _suspicious_funding_independent_support(raw, flags_set)
    suppressor_conflicts = _suspicious_funding_suppressor_conflicts(raw, flags_set)
    if independent_support:
        suppressor_conflicts = [code for code in suppressor_conflicts if code != "domain_specialist"]
    suppressor_conflict = bool(suppressor_conflicts)
    reasons: list[str] = []

    if trace_succeeded == "Unknown":
        quality = SUSPICIOUS_FUNDING_QUALITY_UNKNOWN
        reasons.append("funding trace unavailable or incomplete")
    elif not funding_flag or grade not in {FUNDING_EVIDENCE_SUSPICIOUS_DIRECT, FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN}:
        quality = SUSPICIOUS_FUNDING_QUALITY_NONE
        if proxy_only:
            reasons.append(f"{grade} is proxy context, not suspicious funding hard evidence")
        else:
            reasons.append("no qualifying suspicious funding evidence after a successful trace")
    elif proxy_only:
        quality = SUSPICIOUS_FUNDING_QUALITY_NONE
        reasons.append(f"{grade} is proxy context, not suspicious funding hard evidence")
    elif not opening_exposure:
        quality = SUSPICIOUS_FUNDING_QUALITY_WEAK
        reasons.append("funding was not tied to confirmed opening exposure")
    elif not recent_enough:
        quality = SUSPICIOUS_FUNDING_QUALITY_WEAK
        reasons.append("funding was outside the 24h trade-specific window")
    elif not amount_meaningful:
        quality = SUSPICIOUS_FUNDING_QUALITY_WEAK
        reasons.append("funding amount was below the meaningful-amount floor")
    elif not amount_aligned:
        quality = SUSPICIOUS_FUNDING_QUALITY_WEAK
        reasons.append("funding amount was poorly aligned with trade notional")
    elif suppressor_conflict and not independent_support:
        quality = SUSPICIOUS_FUNDING_QUALITY_WEAK
        reasons.append("suppressors conflict with funding-only hard evidence")
    elif suppressor_conflict and grade == FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN:
        quality = SUSPICIOUS_FUNDING_QUALITY_MODERATE
        reasons.append("multi-hop unknown funding has structural support but suppressor conflicts")
    elif suppressor_conflict and grade == FUNDING_EVIDENCE_SUSPICIOUS_DIRECT:
        quality = SUSPICIOUS_FUNDING_QUALITY_MODERATE
        reasons.append("direct suspicious funding has structural support but suppressor conflicts")
    elif (
        grade == FUNDING_EVIDENCE_SUSPICIOUS_DIRECT
        and recent_enough
        and amount_aligned
        and not suppressor_conflict
    ):
        quality = SUSPICIOUS_FUNDING_QUALITY_STRONG
        reasons.append("recent direct suspicious funding with amount alignment and opening exposure")
    elif (
        grade == FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN
        and recent_enough
        and amount_aligned
        and independent_support
        and not suppressor_conflict
    ):
        quality = SUSPICIOUS_FUNDING_QUALITY_STRONG
        reasons.append("multi-hop unknown funding is amount/time aligned and supported by independent structure")
    elif (
        grade == FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN
        and recent_enough
        and amount_aligned
        and opening_exposure
    ):
        quality = SUSPICIOUS_FUNDING_QUALITY_MODERATE
        reasons.append("multi-hop unknown funding is amount/time aligned but lacks independent structural support")
    elif (
        grade in {FUNDING_EVIDENCE_SUSPICIOUS_DIRECT, FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN}
        and opening_exposure
        and (recent_enough or amount_aligned)
    ):
        quality = SUSPICIOUS_FUNDING_QUALITY_MODERATE
        if grade == FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN:
            reasons.append("multi-hop unknown funding has partial trade alignment")
        else:
            reasons.append("suspicious direct funding has partial trade alignment")
    else:
        quality = SUSPICIOUS_FUNDING_QUALITY_WEAK
        reasons.append("suspicious funding signal lacked trade-specific alignment")

    if quality in {SUSPICIOUS_FUNDING_QUALITY_STRONG, SUSPICIOUS_FUNDING_QUALITY_MODERATE}:
        if support_reasons:
            reasons.append("independent support: " + ", ".join(support_reasons))
        if suppressor_conflicts:
            reasons.append("suppressor conflicts: " + ", ".join(suppressor_conflicts))

    direct_eligible = bool(
        grade == FUNDING_EVIDENCE_SUSPICIOUS_DIRECT
        and quality == SUSPICIOUS_FUNDING_QUALITY_STRONG
        and not suppressor_conflict
    )
    direct_supported_eligible = bool(
        grade == FUNDING_EVIDENCE_SUSPICIOUS_DIRECT
        and independent_support
        and quality in {SUSPICIOUS_FUNDING_QUALITY_STRONG, SUSPICIOUS_FUNDING_QUALITY_MODERATE}
    )
    multi_hop_eligible = bool(
        grade == FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN
        and quality == SUSPICIOUS_FUNDING_QUALITY_STRONG
        and independent_support
        and support_reasons
    )
    eligible = bool(not proxy_only and (direct_eligible or direct_supported_eligible or multi_hop_eligible))
    return {
        "suspiciousFundingQuality": quality,
        "suspiciousFundingQualityReasons": "; ".join(_dedupe_text(reasons)),
        "suspiciousFundingHardEvidenceEligible": "Yes" if eligible else "No",
        "suspiciousFundingTraceSucceeded": trace_succeeded,
        "suspiciousFundingTraceDepth": str(trace_depth) if trace_depth else "",
        "suspiciousFundingSourceCategory": str(raw.get("funding_source_category") or "").strip(),
        "suspiciousFundingOriginCategory": str(raw.get("funding_origin_category") or "").strip(),
        "suspiciousFundingMinutesBeforeTrade": f"{minutes_before_trade:.1f}" if minutes_before_trade is not None else "",
        "suspiciousFundingAmountUsd": _fmt_decimal(amount) if amount is not None else "",
        "suspiciousFundingTradeNotionalUsd": _fmt_decimal(trade_notional) if trade_notional is not None else "",
        "suspiciousFundingAmountToTradeRatio": f"{float(ratio):.4f}" if ratio is not None else "",
        "suspiciousFundingRecentEnough": _yes_no_unknown(recent_enough, minutes_before_trade is not None),
        "suspiciousFundingAmountAligned": _yes_no_unknown(amount_aligned, ratio is not None and amount is not None),
        "suspiciousFundingIndependentSupport": "Yes" if independent_support else "No",
        "suspiciousFundingIndependentSupportSources": "; ".join(_dedupe_text(support_reasons)),
        "suspiciousFundingSuppressorConflict": "Yes" if suppressor_conflicts else "No",
        "suspiciousFundingSuppressorConflictReasons": "; ".join(_dedupe_text(suppressor_conflicts)),
    }


def _suspicious_funding_trace_succeeded(raw: dict[str, object], grade: str) -> str:
    resolver_available = str(raw.get("fundingResolverAvailable") or "").strip()
    if resolver_available == "No" or grade == FUNDING_EVIDENCE_UNKNOWN:
        return "Unknown"
    if _metric_int_like(raw.get("fundingTraceFailedCount")) > 0 and _metric_int_like(raw.get("fundingTraceSucceededCount")) <= 0:
        return "Unknown"
    if raw.get("funding_tx_hash") or raw.get("funding_timestamp") or raw.get("funding_amount_usdc"):
        return "Yes"
    if grade == FUNDING_EVIDENCE_NONE:
        return "Yes"
    if grade in {
        FUNDING_EVIDENCE_SUSPICIOUS_DIRECT,
        FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN,
        FUNDING_EVIDENCE_DIRECT_STRICT,
        FUNDING_EVIDENCE_CEX_PROXY,
        FUNDING_EVIDENCE_BRIDGE_PROXY,
    }:
        return "Yes"
    if resolver_available == "":
        return "Unknown"
    return "No"


def _suspicious_funding_independent_support(
    raw: dict[str, object],
    flags: set[str],
) -> tuple[bool, list[str]]:
    support: list[str] = []
    opening_exposure = str(raw.get("opening_exposure_flag") or "").strip() == "Yes" or str(raw.get("trade_state") or "").strip() == "increase"
    strict_shared_funding = _strict_shared_funding_has_distinct_wallet_support(raw)
    if raw.get("split_wallet_pattern_flag") == "Yes" and not _has_proxy_funding_grade(raw):
        support.append("split_wallet_pattern")
    if strict_shared_funding:
        support.append("strict_shared_funding_source")
    dormancy_gap_days = _metric_float_like(raw.get("days_since_prior_wallet_trade"))
    if (
        raw.get("reactivated_after_dormancy_flag") == "Yes"
        and opening_exposure
        and dormancy_gap_days is not None
        and dormancy_gap_days >= 90.0
    ):
        support.append("dormant_wallet_reactivation")
    if (
        opening_exposure
        and (
            raw.get("event_family_repeat_hard_evidence_flag") == "Yes"
            or (
                "event_family_repeat_narrow_context" in _text_values(raw.get("hardEvidenceSources"))
                and raw.get("event_family_repeat_flag") == "Yes"
            )
        )
    ):
        support.append("event_family_repeat_narrow_context")
    outcome_available = raw.get("outcomeKnown") in {True, "True", "Yes"} or raw.get("outcome_status") in {"known", "resolved"}
    winner_rank = _metric_int_like(raw.get("winnerRank") or raw.get("winner_rank"))
    probability = _metric_float_like(raw.get("price_implied_probability"))
    if (
        opening_exposure
        and outcome_available
        and winner_rank
        and winner_rank <= 6
        and probability is not None
        and probability <= 35.0
    ):
        support.append("low_probability_early_winner")
    if raw.get("coordinated_sizing_cluster_flag") == "Yes" and strict_shared_funding:
        support.append("same_market_same_direction_strict_structural_cluster")
    return bool(support), _dedupe_text(support)


def _suspicious_funding_suppressor_conflicts(raw: dict[str, object], flags: set[str]) -> list[str]:
    conflicts: list[str] = []
    probability = _metric_float_like(raw.get("price_implied_probability"))
    if "near_certainty_trade" in flags or (probability is not None and probability >= 94.0):
        conflicts.append("near_certainty")
    if "yield_farm_pattern" in flags:
        conflicts.append("yield_farm")
    if "theta_decay_pattern" in flags:
        conflicts.append("theta_decay")
    if (
        raw.get("stale_resolution_annotation") == "Yes"
        or raw.get("resolution_gap_flag") == "Yes"
    ):
        conflicts.append("stale_or_resolution_gap")
    if raw.get("hard_public_information_flag") == "Yes" or raw.get("hard_resolution_gap_flag") == "Yes":
        conflicts.append("hard_resolution_gap")
    if "bot_like_execution" in flags or (_metric_float_like(raw.get("bot_likeness_score")) or 0.0) >= 70.0:
        conflicts.append("bot_like_execution")
    if raw.get("low_analyst_value_flag") == "Yes":
        conflicts.append("low_analyst_value_wallet")
    if "domain_specialist_profile" in flags or raw.get("specialist_explained_flag") == "Yes":
        conflicts.append("domain_specialist")
    recent_trade_count = _metric_int_like(raw.get("wallet_recent_trade_count"))
    focus_market_count = _metric_int_like(raw.get("wallet_focus_market_count"))
    unique_market_count = _metric_int_like(raw.get("wallet_unique_market_count"))
    if (
        raw.get("public_model_specialist_flag") == "Yes"
        or raw.get("walletPublicPowerUserFlag") in {True, "True", "Yes"}
        or recent_trade_count >= 100
        or unique_market_count >= 50
        or (recent_trade_count >= 50 and focus_market_count >= 5)
    ):
        conflicts.append("high_volume_public_user")
    return _dedupe_text(conflicts)


def _saved_suspicious_funding_independent_support(raw: dict[str, object]) -> tuple[bool, list[str]]:
    saved_support = str(raw.get("suspiciousFundingIndependentSupport") or "").strip() == "Yes"
    support_sources = _text_values(raw.get("suspiciousFundingIndependentSupportSources"))
    if support_sources:
        return True, support_sources
    return saved_support, []


def _decimal_metric(value: object) -> Decimal | None:
    text = str(value or "").strip().replace(",", "").replace("$", "")
    if not text or text in {"Unavailable", "First visible trade"}:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _yes_no_unknown(value: bool, known: bool) -> str:
    if not known:
        return "Unknown"
    return "Yes" if value else "No"


def _dedupe_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _hard_evidence_strength(sources: list[str], raw: dict[str, object] | None = None) -> str:
    if not sources:
        return "None"
    if len(sources) >= 2:
        return "Strong"
    if sources[0] == "suspicious_recent_funding":
        quality = str((raw or {}).get("suspiciousFundingQuality") or "").strip()
        grade = _funding_evidence_grade_from_raw(raw or {})
        suppressor_conflict = str((raw or {}).get("suspiciousFundingSuppressorConflict") or "").strip() == "Yes"
        independent_support, support_sources = _saved_suspicious_funding_independent_support(raw or {})
        if (
            quality == SUSPICIOUS_FUNDING_QUALITY_STRONG
            and grade == FUNDING_EVIDENCE_SUSPICIOUS_DIRECT
            and not suppressor_conflict
        ):
            return "Strong"
        if (
            quality == SUSPICIOUS_FUNDING_QUALITY_STRONG
            and grade == FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN
            and independent_support
            and support_sources
        ):
            return "Strong"
        return "Moderate"
    if sources[0] in {"split_wallet_pattern", "suspicious_recent_funding", "low_probability_early_winner"}:
        return "Strong"
    return "Moderate"


def _write_hard_evidence_fields(raw: dict[str, object], evidence: dict[str, object]) -> None:
    sources = [str(item) for item in evidence.get("sources", []) if str(item or "").strip()]
    trade_ids = [str(item) for item in evidence.get("trade_ids", []) if str(item or "").strip()]
    wallet_ids = [str(item) for item in evidence.get("wallet_ids", []) if str(item or "").strip()]
    raw["hardEvidenceSources"] = "; ".join(sources)
    raw["hardEvidenceStrength"] = str(evidence.get("strength") or "None")
    raw["hardEvidencePrimaryReason"] = str(evidence.get("primary_reason") or "")
    raw["hardEvidenceTradeIds"] = "; ".join(trade_ids)
    raw["hardEvidenceWalletIds"] = "; ".join(wallet_ids)
    raw["hardEvidenceReviewTier"] = str(evidence.get("review_tier") or NO_HARD_EVIDENCE_REVIEW_TIER)
    raw["evidenceAvailabilityStage"] = str(evidence.get("availability_stage") or "")


def _apply_candidate_admission_metadata(
    case: FlaggedCase,
    metadata: dict[str, str] | None,
) -> None:
    if not metadata:
        case.raw_metrics.setdefault("candidateAdmissionStage", "normal_candidate")
        return
    for key in STRUCTURAL_PRE_ADMISSION_FIELDS:
        case.raw_metrics[key] = str(metadata.get(key, ""))
    rejection = _candidate_admission_rejection_reason(case, require_linkage=False)
    if rejection:
        case.raw_metrics["candidateAdmissionStage"] = "pre_admitted_rejected"
        case.raw_metrics["candidateAdmissionValidatedOpeningExposure"] = (
            "Yes" if case.raw_metrics.get("opening_exposure_flag") == "Yes" else "No"
        )
        case.raw_metrics["candidateAdmissionRejectedReason"] = rejection


def _validate_candidate_admissions(cases: list[FlaggedCase]) -> None:
    for case in cases:
        raw = case.raw_metrics
        if not str(raw.get("candidateAdmissionReason") or "").strip():
            continue
        if _candidate_admission_rejected(raw):
            continue
        rejection = _candidate_admission_rejection_reason(case, require_linkage=True)
        if rejection:
            raw["candidateAdmissionStage"] = "pre_admitted_rejected"
            raw["candidateAdmissionValidatedOpeningExposure"] = (
                "Yes" if raw.get("opening_exposure_flag") == "Yes" else "No"
            )
            raw["candidateAdmissionRejectedReason"] = rejection
            continue
        raw["candidateAdmissionStage"] = "pre_admitted_validated"
        raw["candidateAdmissionValidatedOpeningExposure"] = "Yes"
        raw["candidateAdmissionRejectedReason"] = ""


def _candidate_admission_rejected(raw: dict[str, object]) -> bool:
    return bool(
        str(raw.get("candidateAdmissionRejectedReason") or "").strip()
        or str(raw.get("candidateAdmissionStage") or "").strip() == "pre_admitted_rejected"
    )


def _candidate_admission_rejection_reason(
    case: FlaggedCase,
    *,
    require_linkage: bool,
) -> str:
    raw = case.raw_metrics
    reason = str(raw.get("candidateAdmissionReason") or "").strip()
    if not reason:
        return ""
    if raw.get("opening_exposure_flag") != "Yes":
        return "opening_exposure_not_confirmed"
    if raw.get("repricing_source_quality") == REPRICING_SOURCE_QUALITY_MECHANICAL or raw.get("repricingSourceQuality") == REPRICING_SOURCE_QUALITY_MECHANICAL:
        return "mechanical_repricing"
    if raw.get("hard_public_information_flag") == "Yes" or raw.get("resolution_gap_type") == "hard":
        return "stale_or_resolution_gap"

    if reason in STRUCTURAL_PRE_ADMISSION_GROUP_REASONS:
        if raw.get("groupedCandidateProxyOnly") == "Yes":
            return "proxy_only_group"
        grouped_grade = str(raw.get("groupedCandidateFundingGrade") or "").strip()
        if raw.get("fundingResolverAvailable") == "No" or grouped_grade == FUNDING_EVIDENCE_UNKNOWN:
            return "funding_resolver_unavailable"
        if grouped_grade == FUNDING_EVIDENCE_NONE:
            return "strict_funding_not_confirmed"
        if raw.get("groupedCandidateStrictFunding") != "Yes":
            return "strict_funding_not_confirmed"
        if require_linkage:
            if raw.get("shared_funding_source_flag") != "Yes":
                return "shared_funding_link_not_confirmed"
            if raw.get("cex_proxy_cluster_flag") == "Yes":
                return "proxy_only_group"
            sources = _text_values(raw.get("candidateAdmissionEvidenceSources"))
            if "split_wallet_pattern" in sources and raw.get("split_wallet_pattern_flag") != "Yes":
                return "split_wallet_pattern_not_confirmed"
        return ""

    if reason in STRUCTURAL_PRE_ADMISSION_SINGLE_REASONS:
        if "near_certainty_trade" in case.flags:
            return "near_certainty_suppressed"
        if "yield_farm_pattern" in case.flags:
            return "yield_farm_suppressed"
        if "theta_decay_pattern" in case.flags:
            return "theta_decay_suppressed"
        if raw.get("stale_resolution_annotation") == "Yes" or raw.get("resolution_gap_flag") == "Yes":
            return "stale_or_resolution_gap"
        if reason == "suspicious_recent_funding":
            grade = _funding_evidence_grade_from_raw(raw)
            if raw.get("suspicious_funding_flag") != "Yes":
                return "suspicious_funding_not_confirmed"
            if grade not in {FUNDING_EVIDENCE_SUSPICIOUS_DIRECT, FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN}:
                return "suspicious_funding_grade_not_eligible"
        if reason == "dormant_reactivation":
            gap = _metric_float_like(raw.get("days_since_prior_wallet_trade"))
            if raw.get("reactivated_after_dormancy_flag") != "Yes":
                return "dormant_reactivation_not_confirmed"
            if gap is None or gap < STRONG_DORMANT_REACTIVATION_DAYS:
                return "dormancy_below_90_days"
    return ""


def _text_values(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            result.extend(_text_values(item))
        return result
    text = str(value or "").strip()
    if not text:
        return []
    separator = ";" if ";" in text else ","
    if separator in text:
        return [part.strip() for part in text.split(separator) if part.strip()]
    return [text]


def _metric_int_like(value: object) -> int:
    try:
        return int(float(str(value or "0").replace("%", "")))
    except (TypeError, ValueError):
        return 0


def _metric_float_like(value: object) -> float | None:
    text = str(value or "").strip().replace("%", "")
    if not text or text == "Unavailable" or text == "First visible trade":
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _wallet_domain_counts(trades: list[Trade], focus_markets: dict[str, Market]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trade in trades:
        domain = _domain_for_trade(trade, focus_markets)
        counts[domain] = counts.get(domain, 0) + 1
    return counts


def _domain_for_trade(trade: Trade, focus_markets: dict[str, Market]) -> str:
    market = focus_markets.get(trade.condition_id)
    if market is not None:
        for category in market.site_categories:
            if category in DOMAIN_BY_CATEGORY:
                return DOMAIN_BY_CATEGORY[category]
    topic_match = match_focus_topic(f"{trade.title} {trade.event_slug}")
    for label in topic_match.labels:
        if label in KEYWORD_DOMAIN_OVERRIDES:
            return KEYWORD_DOMAIN_OVERRIDES[label]
    return "Other"


def _score_trade(
    *,
    trade: Trade,
    market: Market,
    trade_domain: str,
    wallet_inspection: WalletInspection,
    wallet_performance: WalletPerformance,
    wallet_window_trades: list[Trade],
    wallet_history_trades: list[Trade],
    market_window_trades: list[Trade],
    domain_window_trades: list[Trade],
    event_context: EventContext,
    funding_context: FundingContext,
    funding_health: FundingResolverHealth | dict[str, object] | None = None,
    include_below_threshold: bool = False,
    market_notional_samples: list[float] | None = None,
    domain_notional_samples: list[float] | None = None,
    prior_wallet_gap_days: float | None = None,
    observed_post_trade_gap_days: float | None = None,
    family_key: str | None = None,
    prior_family_trade_count: int | None = None,
    prior_family_market_count: int | None = None,
    event_family_share: float | None = None,
) -> FlaggedCase | None:
    subscores = {
        "trade_state": 0,
        "timing": 0,
        "size": 0,
        "market_state": 0,
        "wallet_novelty": 0,
        "wallet_behavior": 0,
        "market_sensitivity": 0,
        "cluster": 0,
        "post_trade": 0,
        "benign_discount": 0,
    }
    flags: list[str] = []
    explanation: list[str] = []
    reasons_against: list[str] = []
    funding_evidence_grade = grade_funding_evidence(funding_context)
    funding_health_dict = _funding_health_for_raw_metrics(funding_context, funding_health)
    raw_metrics: dict[str, str] = {
        "trade_notional_usdc": _fmt_decimal(trade.notional),
        "market_liquidity_usdc": _fmt_decimal(market.liquidity),
        "market_volume_usdc": _fmt_decimal(market.volume),
        "case_type": "",
        "event_family_key": "",
        "wallet_prior_event_family_trades": "0",
        "wallet_prior_event_family_markets": "0",
        "wallet_event_family_share": "0.00",
        "event_family_repeat_flag": "No",
        "days_since_prior_wallet_trade": "",
        "days_to_next_wallet_trade": "",
        "reactivated_after_dormancy_flag": "No",
        "post_trade_dormancy_flag": "No",
        "trade_domain": trade_domain,
        "domain_specialist_label": wallet_inspection.dominant_domain_label,
        "domain_concentration_score": f"{wallet_inspection.domain_concentration_score:.2f}",
        "public_model_specialist_flag": "Yes" if wallet_inspection.public_model_specialist_flag else "No",
        "wallet_traded_market_count": str(wallet_inspection.traded_market_count or ""),
        "wallet_recent_trade_count": str(wallet_inspection.recent_trade_count),
        "wallet_unique_market_count": str(wallet_inspection.unique_market_count),
        "wallet_focus_market_count": str(wallet_inspection.focus_market_count),
        "event_timezone": event_context.event_timezone,
        "local_event_time": event_context.local_event_time,
        "local_event_hour": str(event_context.local_event_hour),
        "off_hours_flag": "Yes" if event_context.off_hours_flag else "No",
        "deadline_market_flag": "Yes" if event_context.market_deadline_flag else "No",
        "offline_timeline_matched": "Yes" if event_context.matched_offline_row else "No",
        "timeline_id": event_context.timeline_id or "",
        "timeline_source": event_context.timeline_source or "",
        "stale_resolution_annotation": "Yes" if event_context.stale_resolution_annotation else "No",
        "reality_oracle_gap_label": event_context.reality_oracle_gap_label or "",
        "funding_source_label": funding_context.source_label,
        "funding_source_category": funding_context.source_category,
        "funding_source_address": funding_context.source_address,
        "funding_origin_label": funding_context.origin_label,
        "funding_origin_category": funding_context.origin_category,
        "funding_origin_address": funding_context.origin_address,
        "funding_tx_hash": funding_context.funding_tx_hash,
        "funding_amount_usdc": _fmt_decimal(funding_context.funding_amount_usdc),
        "funding_velocity_label": funding_context.funding_velocity_label,
        "funding_depth": str(funding_context.funding_depth),
        "funding_evidence_grade": funding_evidence_grade,
        "fundingEvidenceGrade": funding_evidence_grade,
        "fundingResolverAvailable": funding_health_dict["fundingResolverAvailable"],
        "fundingResolverDisabledReason": funding_health_dict["fundingResolverDisabledReason"],
        "fundingResolverAuthError": funding_health_dict["fundingResolverAuthError"],
        "fundingResolverUnavailableReason": funding_health_dict["fundingResolverUnavailableReason"],
        "fundingResolverFunctionalStatus": funding_health_dict["fundingResolverFunctionalStatus"],
        "fundingResolverEndpointLabel": funding_health_dict["fundingResolverEndpointLabel"],
        "fundingResolverLastError": funding_health_dict["fundingResolverLastError"],
        "fundingTraceAttemptedCount": funding_health_dict["fundingTraceAttemptedCount"],
        "fundingTraceSucceededCount": funding_health_dict["fundingTraceSucceededCount"],
        "fundingTraceFailedCount": funding_health_dict["fundingTraceFailedCount"],
        "fundingTraceSkippedCount": funding_health_dict["fundingTraceSkippedCount"],
        "fundingTraceSkippedReasonDistribution": funding_health_dict["fundingTraceSkippedReasonDistribution"],
        "fundingTraceCoverageRatio": funding_health_dict["fundingTraceCoverageRatio"],
        "fundingTraceEndpointPoolSize": funding_health_dict["fundingTraceEndpointPoolSize"],
        "fundingTraceEndpointAvailableCount": funding_health_dict["fundingTraceEndpointAvailableCount"],
        "fundingTraceEndpointCooldownCount": funding_health_dict["fundingTraceEndpointCooldownCount"],
        "fundingTraceEndpointFailureDistribution": funding_health_dict["fundingTraceEndpointFailureDistribution"],
        "fundingTraceEndpointSummary": funding_health_dict["fundingTraceEndpointSummary"],
        "fundingTraceRateLimitedCount": funding_health_dict["fundingTraceRateLimitedCount"],
        "fundingTraceRetryCount": funding_health_dict["fundingTraceRetryCount"],
        "fundingTraceFallbackEndpointCount": funding_health_dict["fundingTraceFallbackEndpointCount"],
        "fundingTraceLogChunksAttempted": funding_health_dict["fundingTraceLogChunksAttempted"],
        "fundingTraceLogChunksSucceeded": funding_health_dict["fundingTraceLogChunksSucceeded"],
        "fundingTraceLogChunksFailed": funding_health_dict["fundingTraceLogChunksFailed"],
        "fundingTraceLogChunksRateLimited": funding_health_dict["fundingTraceLogChunksRateLimited"],
        "fundingTraceCacheHitCount": funding_health_dict["fundingTraceCacheHitCount"],
        "fundingTraceCacheMissCount": funding_health_dict["fundingTraceCacheMissCount"],
        "fundingTracePersistentCacheEnabled": funding_health_dict["fundingTracePersistentCacheEnabled"],
        "fundingTracePersistentCacheHitCount": funding_health_dict["fundingTracePersistentCacheHitCount"],
        "fundingTracePersistentCacheMissCount": funding_health_dict["fundingTracePersistentCacheMissCount"],
        "fundingTracePersistentCacheWriteCount": funding_health_dict["fundingTracePersistentCacheWriteCount"],
        "fundingTracePersistentCacheExpiredCount": funding_health_dict["fundingTracePersistentCacheExpiredCount"],
        "fundingTracePersistentCacheFailureCooldownCount": funding_health_dict["fundingTracePersistentCacheFailureCooldownCount"],
        "fundingTracePersistentCacheSchemaVersion": funding_health_dict["fundingTracePersistentCacheSchemaVersion"],
        "fundingTraceFromPersistentCache": "Yes" if funding_context.funding_trace_from_persistent_cache else "No",
        "fundingTracePersistentCacheStatus": funding_context.funding_trace_cache_status,
        "suspicious_funding_score": f"{funding_context.suspicious_funding_score:.2f}",
        "suspicious_funding_flag": "Yes" if funding_context.suspicious_funding_flag else "No",
        "recent_external_funding_flag": "Yes" if funding_context.recent_external_funding_flag else "No",
        "funding_graph_key": funding_context.funding_graph_key,
        "candidateAdmissionReason": "",
        "candidateAdmissionStage": "normal_candidate",
        "candidateAdmissionEvidenceSources": "",
        "candidateAdmissionFloorNotional": "",
        "groupedCandidateId": "",
        "groupedCandidateAggregateNotional": "",
        "groupedCandidateWalletCount": "",
        "groupedCandidateStrictFunding": "No",
        "groupedCandidateProxyOnly": "No",
        "groupedCandidateFundingGrade": "",
        "groupedCandidateTimeSpanMinutes": "",
        "groupedCandidatePriceBand": "",
        "candidateAdmissionValidatedOpeningExposure": "",
        "candidateAdmissionRejectedReason": "",
        "shared_funding_source_flag": "No",
        "shared_funding_source_cluster_size": "0",
        "split_wallet_pattern_flag": "No",
        "split_wallet_pattern_cluster_size": "0",
        "funding_proxy_cluster_flag": "No",
        "funding_proxy_cluster_size": "0",
        "funding_proxy_tight_cohort_flag": "No",
        "funding_proxy_tight_cohort_size": "0",
        "cex_proxy_cluster_flag": "No",
        "cex_proxy_cluster_size": "0",
        "coordinated_sizing_cluster_flag": "No",
        "coordinated_sizing_cluster_size": "0",
        "event_family_funder_cohort_flag": "No",
        "event_family_funder_cohort_size": "0",
        "funding_graph_key_strict": funding_context.funding_graph_key_strict,
        "funding_graph_key_proxy": funding_context.funding_graph_key_proxy,
        "funding_fingerprint": funding_context.funding_fingerprint,
    }
    for key, value in (
        ("broad_report_at", event_context.broad_report_at),
        ("official_confirmation_at", event_context.official_confirmation_at),
        ("public_outcome_at", event_context.public_outcome_at),
        ("public_knowledge_at", event_context.public_knowledge_at),
        ("funding_timestamp", funding_context.funding_timestamp),
    ):
        raw_metrics[key] = value.isoformat() if value is not None else ""
    raw_metrics["minutes_from_funding_to_trade"] = (
        f"{funding_context.minutes_from_funding_to_trade:.1f}"
        if funding_context.minutes_from_funding_to_trade is not None
        else ""
    )
    closed_summary = wallet_performance.closed_summary
    activity_summary = wallet_performance.activity_summary
    raw_metrics["wallet_closed_positions"] = str(closed_summary.total)
    raw_metrics["wallet_closed_wins"] = str(closed_summary.wins)
    raw_metrics["wallet_closed_losses"] = str(closed_summary.losses)
    raw_metrics["wallet_closed_win_rate"] = f"{closed_summary.win_rate_value:.1f}%"
    raw_metrics["wallet_win_rate_threshold"] = f"{closed_summary.win_rate_threshold:.1f}%"
    raw_metrics["win_rate_clears_threshold"] = "Yes" if closed_summary.win_rate_clears_threshold else "No"
    raw_metrics["wallet_economic_sample_size"] = str(closed_summary.economic_sample_size)
    raw_metrics["wallet_economic_win_rate"] = f"{closed_summary.economic_win_rate_value:.1f}%"
    raw_metrics["wallet_economic_threshold"] = f"{closed_summary.economic_win_rate_threshold:.1f}%"
    raw_metrics["economic_win_rate_clears_threshold"] = (
        "Yes" if closed_summary.economic_win_rate_clears_threshold else "No"
    )
    raw_metrics["zombie_loss_count"] = str(closed_summary.zombie_loss_count)
    raw_metrics["zombie_loss_notional"] = _fmt_decimal(closed_summary.zombie_loss_notional)
    raw_metrics["redemption_avoidance_ratio"] = f"{closed_summary.redemption_avoidance_ratio * 100:.1f}%"
    raw_metrics["formal_win_rate_may_be_overstated"] = (
        "Yes" if closed_summary.formal_win_rate_may_be_overstated else "No"
    )
    raw_metrics.update(compute_wallet_statistical_prior(closed_summary).to_raw_metrics())
    raw_metrics["bot_likeness_score"] = f"{activity_summary.bot_likeness_score:.1f}"
    raw_metrics["microtrade_ratio"] = f"{activity_summary.microtrade_ratio * 100:.1f}%"
    raw_metrics["median_trade_size"] = _fmt_decimal(activity_summary.median_trade_size)
    raw_metrics["trade_burst_rate"] = f"{activity_summary.trade_burst_rate:.1f}"
    raw_metrics["median_intertrade_interval_minutes"] = f"{activity_summary.median_intertrade_interval_minutes:.1f}"
    raw_metrics["market_breadth"] = str(activity_summary.market_breadth)
    raw_metrics["manual_review_value_score"] = f"{activity_summary.manual_review_value_score:.1f}"
    raw_metrics["low_analyst_value_flag"] = "Yes" if activity_summary.low_analyst_value_flag else "No"
    same_outcome_market_trades = sorted(
        [item for item in market_window_trades if item.asset_id == trade.asset_id],
        key=lambda item: (item.timestamp, item.trade_id),
    )
    same_market_wallet_trades = [item for item in wallet_window_trades if item.condition_id == trade.condition_id]
    prior_same_market_trades = [
        item
        for item in wallet_history_trades
        if item.condition_id == trade.condition_id
        and item.trade_id != trade.trade_id
        and item.timestamp <= trade.timestamp
    ]
    prior_same_asset_trades = [
        item
        for item in wallet_history_trades
        if item.asset_id == trade.asset_id
        and item.trade_id != trade.trade_id
        and item.timestamp <= trade.timestamp
    ]
    if prior_wallet_gap_days is None and observed_post_trade_gap_days is None:
        prior_wallet_gap_days, observed_post_trade_gap_days = _wallet_activity_gap_days(wallet_history_trades, trade)
    if family_key is None:
        family_key = _event_family_key(trade, market)
    if (
        prior_family_trade_count is None
        or prior_family_market_count is None
        or event_family_share is None
    ):
        (
            prior_family_trade_count,
            prior_family_market_count,
            event_family_share,
        ) = _event_family_stats(
            wallet_history_trades,
            trade,
            family_key,
        )
    raw_metrics["event_family_key"] = family_key
    raw_metrics["wallet_prior_event_family_trades"] = str(prior_family_trade_count)
    raw_metrics["wallet_prior_event_family_markets"] = str(prior_family_market_count)
    raw_metrics["wallet_event_family_share"] = f"{event_family_share:.2f}"
    if prior_wallet_gap_days is None:
        raw_metrics["days_since_prior_wallet_trade"] = "First visible trade"
    else:
        raw_metrics["days_since_prior_wallet_trade"] = f"{prior_wallet_gap_days:.1f}"
    if observed_post_trade_gap_days is not None:
        raw_metrics["days_to_next_wallet_trade"] = f"{observed_post_trade_gap_days:.1f}"

    execution_state = _classify_execution_state(trade, prior_same_asset_trades, prior_same_market_trades)
    opening_exposure_flag = _is_opening_exposure(execution_state)
    economic_direction = _economic_direction(trade, execution_state)
    trade_state = "increase" if opening_exposure_flag else _legacy_trade_state(execution_state)
    raw_metrics["execution_state"] = execution_state
    raw_metrics["opening_exposure_flag"] = "Yes" if opening_exposure_flag else "No"
    raw_metrics["economic_direction"] = economic_direction
    raw_metrics["trade_state"] = trade_state
    side_outcome_model = normalize_side_outcome(trade.side, trade.outcome, trade.price)
    raw_metrics.update(side_outcome_model.to_raw_metrics())
    raw_metrics.update(normalize_cluster_direction(trade.side, trade.outcome, trade.price).to_raw_metrics())
    model_probability = side_outcome_model.economic_side_probability
    model_probability_basis = side_outcome_model.model_probability_basis
    if model_probability is None:
        model_probability = trade.price
        model_probability_basis = "raw_token_price_fallback"
    raw_metrics["model_probability"] = str(model_probability)
    raw_metrics["model_probability_basis"] = model_probability_basis

    capital_at_risk = _capital_at_risk_usdc(trade, execution_state)
    raw_metrics["capital_at_risk_usdc"] = _fmt_decimal(capital_at_risk)
    raw_metrics["price_implied_probability"] = f"{(trade.price * Decimal('100')):.1f}%"
    uncertainty = _uncertainty_level(model_probability)
    raw_metrics["uncertainty_level"] = f"{uncertainty:.2f}"

    opening_increase = opening_exposure_flag and capital_at_risk > 0
    if opening_increase:
        subscores["trade_state"] += 5
        explanation.append("The trade appears to add fresh directional exposure rather than simply closing inventory.")
    else:
        flags.append("non_opening_trade")
        if execution_state == "reduce":
            reasons_against.append("The trade looks more like a reduction of an existing position than a fresh conviction entry.")
            subscores["benign_discount"] -= 10
        elif execution_state == "close":
            reasons_against.append("The trade looks more like a position close than a new directional bet.")
            subscores["benign_discount"] -= 12
        elif execution_state == "roll":
            reasons_against.append("The trade looks closer to a position roll than to a fresh directional opening.")
            subscores["benign_discount"] -= 9
        else:
            reasons_against.append("The trade purpose is ambiguous, so it should not be treated like a clean opening exposure.")
            subscores["benign_discount"] -= 8

    size_basis = capital_at_risk if opening_increase else trade.notional * Decimal("0.30")
    if size_basis >= Decimal("5000"):
        subscores["size"] += 8
        flags.append("large_trade_absolute")
        explanation.append("The position size is large in absolute dollar terms.")
    elif size_basis >= Decimal("2500"):
        subscores["size"] += 5
        explanation.append("The position size is notable even before market context is applied.")
    elif size_basis >= Decimal("1000"):
        subscores["size"] += 3

    liquidity_ratio: Decimal | None = None
    if market.liquidity > 0:
        liquidity_ratio = capital_at_risk / market.liquidity if opening_increase else trade.notional / market.liquidity
        raw_metrics["liquidity_ratio"] = f"{(liquidity_ratio * 100):.2f}%"
        if liquidity_ratio >= Decimal("0.30"):
            subscores["size"] += 8
            flags.append("liquidity_drain_extreme")
            explanation.append("The trade consumed an unusually large share of visible liquidity.")
        elif liquidity_ratio >= Decimal("0.15"):
            subscores["size"] += 6
            flags.append("large_trade_relative_to_market")
            explanation.append("The trade consumed a meaningfully large share of visible market liquidity.")
        elif liquidity_ratio >= Decimal("0.05"):
            subscores["size"] += 3
            explanation.append("The trade took enough visible liquidity to stand out in this market.")
    else:
        raw_metrics["liquidity_ratio"] = "Unavailable"

    market_notionals = (
        market_notional_samples
        if market_notional_samples is not None
        else _sorted_trade_notionals(market_window_trades)
    )
    if market_notionals:
        market_percentile = _percentile_rank_sorted(float(trade.notional), market_notionals)
        raw_metrics["market_size_percentile"] = f"{market_percentile:.1f}"
        if market_percentile >= 99:
            subscores["size"] += 6
            explanation.append("The trade sits at the extreme upper end of size within this market window.")
        elif market_percentile >= 95:
            subscores["size"] += 5
        elif market_percentile >= 90:
            subscores["size"] += 3
    else:
        market_percentile = None

    domain_peer_percentile: float | None = None
    if len(domain_window_trades) >= 8:
        domain_notionals = (
            domain_notional_samples
            if domain_notional_samples is not None
            else _sorted_trade_notionals(domain_window_trades)
        )
        domain_peer_percentile = _percentile_rank_sorted(float(trade.notional), domain_notionals)
        raw_metrics["domain_peer_percentile"] = f"{domain_peer_percentile:.1f}"
    else:
        raw_metrics["domain_peer_percentile"] = "Unavailable"

    size_multiple: float | None = None
    wallet_baseline = [
        float(item.notional)
        for item in wallet_history_trades
        if item.trade_id != trade.trade_id and item.notional > 0
    ]
    if len(wallet_baseline) >= 5:
        wallet_median = median(wallet_baseline)
        if wallet_median > 0:
            size_multiple = float(size_basis) / wallet_median
            raw_metrics["wallet_size_multiple_vs_median"] = f"{size_multiple:.2f}"
            if size_multiple >= 10:
                subscores["size"] += 7
                flags.append("wallet_size_anomaly")
                explanation.append("This trade is many times larger than the wallet's usual trade size.")
            elif size_multiple >= 5:
                subscores["size"] += 5
            elif size_multiple >= 3:
                subscores["size"] += 3
    else:
        raw_metrics["wallet_size_multiple_vs_median"] = "Unavailable"

    domain_adjusted_anomaly = 0.0
    if domain_peer_percentile is not None:
        if domain_peer_percentile >= 99:
            domain_adjusted_anomaly += 8
        elif domain_peer_percentile >= 95:
            domain_adjusted_anomaly += 6
        elif domain_peer_percentile >= 90:
            domain_adjusted_anomaly += 4
        elif domain_peer_percentile <= 70 and wallet_inspection.domain_concentration_score >= 0.75:
            domain_adjusted_anomaly -= 3
    if liquidity_ratio is not None:
        if liquidity_ratio >= Decimal("0.15"):
            domain_adjusted_anomaly += 3
        elif liquidity_ratio >= Decimal("0.05"):
            domain_adjusted_anomaly += 1
    if size_multiple is not None:
        if size_multiple >= 10:
            domain_adjusted_anomaly += 4
        elif size_multiple >= 5:
            domain_adjusted_anomaly += 2
    raw_metrics["domain_adjusted_anomaly_score"] = f"{max(domain_adjusted_anomaly, 0.0):.1f}"
    if opening_increase and domain_adjusted_anomaly >= 9:
        flags.append("domain_peer_outlier")
        subscores["wallet_behavior"] += 4
        explanation.append("The trade still looks unusually large even versus peer activity in the same market domain.")
    elif opening_increase and domain_adjusted_anomaly >= 6:
        subscores["wallet_behavior"] += 2
    elif wallet_inspection.domain_concentration_score >= 0.75 and domain_adjusted_anomaly <= 1:
        reasons_against.append("Relative to peer traders in this domain, the trade does not look especially unusual.")
        subscores["benign_discount"] -= 2

    if (wallet_inspection.polygon_nonce is not None and wallet_inspection.polygon_nonce <= 5) or (
        wallet_inspection.traded_market_count is not None and wallet_inspection.traded_market_count <= 3
    ):
        subscores["wallet_novelty"] += 6
        flags.append("wallet_recently_activated")
        explanation.append("The wallet looks low-history relative to what we loaded.")

    if wallet_inspection.recent_trade_count < 20:
        subscores["wallet_novelty"] += 3
    elif wallet_inspection.recent_trade_count < 50:
        subscores["wallet_novelty"] += 1

    specialization_ratio = (
        wallet_inspection.focus_market_count / wallet_inspection.unique_market_count
        if wallet_inspection.unique_market_count
        else 0.0
    )
    raw_metrics["wallet_specialization_ratio"] = f"{specialization_ratio:.2f}"
    if specialization_ratio >= 0.80 and wallet_inspection.recent_trade_count <= 20:
        subscores["wallet_behavior"] += 5
        flags.append("event_sniper_profile")
        explanation.append("The wallet is unusually concentrated in this event family despite having little overall history.")
    elif specialization_ratio >= 0.65 and wallet_inspection.recent_trade_count >= 50:
        subscores["benign_discount"] -= 4
        reasons_against.append("The wallet looks more like a specialist in this market family than a burner account.")

    if wallet_inspection.domain_concentration_score >= 0.75 and wallet_inspection.recent_trade_count >= 20:
        flags.append("domain_specialist_profile")
        if wallet_inspection.public_model_specialist_flag:
            subscores["benign_discount"] -= 6
            reasons_against.append(
                f"The wallet looks more like a repeat {wallet_inspection.dominant_domain_label.lower()} specialist than a one-off event sniper."
            )
        else:
            subscores["benign_discount"] -= 3

    reactivated_after_dormancy = bool(
        prior_wallet_gap_days is not None and prior_wallet_gap_days >= DORMANT_REACTIVATION_DAYS
    )
    raw_metrics["reactivated_after_dormancy_flag"] = "Yes" if reactivated_after_dormancy else "No"
    if opening_increase and reactivated_after_dormancy and not wallet_inspection.public_model_specialist_flag:
        dormancy_bonus = 0
        if prior_wallet_gap_days >= STRONG_DORMANT_REACTIVATION_DAYS:
            dormancy_bonus = 5
        elif (
            model_probability <= Decimal("0.35")
            or size_basis >= Decimal("2500")
            or prior_family_market_count >= 2
        ):
            dormancy_bonus = 3
        if dormancy_bonus:
            subscores["wallet_behavior"] += dormancy_bonus
            flags.append("dormant_wallet_reactivation")
            if prior_wallet_gap_days >= STRONG_DORMANT_REACTIVATION_DAYS:
                explanation.append("The wallet had been inactive for months before resurfacing for this trade.")
            else:
                explanation.append("The wallet reactivated after a long quiet period and then entered this trade.")

    post_trade_dormancy = bool(
        observed_post_trade_gap_days is not None and observed_post_trade_gap_days >= POST_TRADE_DORMANCY_DAYS
    )
    raw_metrics["post_trade_dormancy_flag"] = "Yes" if post_trade_dormancy else "No"

    event_family_repeat = bool(
        prior_family_market_count >= 2
        and prior_family_trade_count >= 3
        and event_family_share >= 0.35
    )
    raw_metrics["event_family_repeat_flag"] = "Yes" if event_family_repeat else "No"
    if opening_increase and event_family_repeat and trade_domain not in PUBLIC_MODEL_DOMAINS:
        subscores["wallet_behavior"] += 4 if wallet_inspection.recent_trade_count <= 40 else 2
        flags.append("event_family_repeat")
        explanation.append("The wallet has repeatedly returned to closely related markets in this same event family.")

    related_window_trades = [
        item
        for item in wallet_window_trades
        if abs((item.timestamp - trade.timestamp).total_seconds()) <= 30 * 60
    ]
    related_markets = {item.condition_id for item in related_window_trades}
    raw_metrics["related_markets_30m"] = str(len(related_markets))
    if len(related_markets) >= 3:
        subscores["wallet_behavior"] += 4
        explanation.append("The wallet entered several related markets in a short time window.")
    elif len(related_markets) == 2:
        subscores["wallet_behavior"] += 2

    conviction_ratio = _wallet_market_conviction_ratio(wallet_window_trades, trade)
    raw_metrics["wallet_market_conviction_ratio"] = f"{conviction_ratio:.2f}"
    if opening_increase and conviction_ratio >= 0.85:
        subscores["wallet_behavior"] += 3
        explanation.append("The wallet committed an unusually concentrated share of its visible activity to this one market.")

    if funding_context.suspicious_funding_flag:
        flags.append("suspicious_funding_source")
        subscores["wallet_behavior"] += 6
        explanation.append(
            "The wallet appears to have been funded shortly before the trade from an unattributed or opaque source."
        )
    elif (
        opening_increase
        and funding_context.recent_external_funding_flag
        and wallet_inspection.recent_trade_count <= 20
    ):
        flags.append("recent_wallet_funding")
        subscores["wallet_behavior"] += 2
        explanation.append("The wallet appears to have been freshly funded not long before this trade.")

    consensus_edge = _consensus_edge(same_outcome_market_trades, trade)
    if consensus_edge is None:
        raw_metrics["entry_vs_consensus_15m"] = "Unavailable"
    else:
        raw_metrics["entry_vs_consensus_15m"] = f"{consensus_edge:+.3f}"
        if opening_increase:
            if consensus_edge >= Decimal("0.08"):
                subscores["timing"] += 10
                flags.append("beat_local_consensus")
                explanation.append("The entry beat the local market consensus by a wide margin.")
            elif consensus_edge >= Decimal("0.04"):
                subscores["timing"] += 6
                explanation.append("The entry price was materially better than the market had just been offering.")
            elif consensus_edge >= Decimal("0.02"):
                subscores["timing"] += 3
            elif consensus_edge <= Decimal("-0.04"):
                subscores["benign_discount"] -= 4
                reasons_against.append("The trade looks more like it chased an already-moving market than beat local consensus.")

    favorable_moves = _favorable_moves_after_entry(same_outcome_market_trades, trade)
    raw_metrics["favorable_move_15m"] = _fmt_decimal(favorable_moves["15m"]) if favorable_moves["15m"] is not None else "Unavailable"
    raw_metrics["favorable_move_1h"] = _fmt_decimal(favorable_moves["1h"]) if favorable_moves["1h"] is not None else "Unavailable"
    raw_metrics["favorable_move_4h"] = _fmt_decimal(favorable_moves["4h"]) if favorable_moves["4h"] is not None else "Unavailable"
    raw_metrics["favorable_move_24h"] = _fmt_decimal(favorable_moves["24h"]) if favorable_moves["24h"] is not None else "Unavailable"
    if opening_increase:
        if _move_is_at_least(favorable_moves["15m"], Decimal("0.10")) or _move_is_at_least(favorable_moves["1h"], Decimal("0.18")):
            subscores["post_trade"] += 12
            flags.append("rapid_favorable_repricing")
            explanation.append("The market repriced sharply in the trade's favor soon after entry.")
        elif _move_is_at_least(favorable_moves["15m"], Decimal("0.05")) or _move_is_at_least(favorable_moves["1h"], Decimal("0.10")):
            subscores["post_trade"] += 8
            explanation.append("The market moved clearly in the trade's favor after entry.")
        elif _move_is_at_least(favorable_moves["4h"], Decimal("0.08")) or _move_is_at_least(favorable_moves["24h"], Decimal("0.12")):
            subscores["post_trade"] += 5
        elif any(move is not None for move in favorable_moves.values()):
            subscores["benign_discount"] -= 5
            reasons_against.append("We did not see a strong favorable repricing after the trade in the loaded sample.")

    entry_rank, entry_percentile = _market_entry_rank(same_outcome_market_trades, trade)
    raw_metrics["market_entry_rank"] = str(entry_rank) if entry_rank is not None else "Unavailable"
    raw_metrics["market_entry_percentile"] = f"{entry_percentile:.2f}" if entry_percentile is not None else "Unavailable"
    entry_rank_signal = False
    if (
        opening_increase
        and entry_rank is not None
        and entry_rank <= 3
        and len(same_outcome_market_trades) >= 8
        and _move_is_at_least(favorable_moves["1h"], Decimal("0.05"))
    ):
        entry_rank_signal = True
        flags.append("early_meaningful_entry")
        subscores["timing"] += 4
        explanation.append("The wallet appears to have been among the earliest meaningful entrants before the market repriced.")

    hours_to_resolution: float | None = None
    if market.end_date:
        try:
            end_dt = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
            if end_dt > trade.timestamp:
                hours_to_resolution = max((end_dt - trade.timestamp).total_seconds() / 3600, 0.0)
                raw_metrics["hours_to_resolution"] = f"{hours_to_resolution:.2f}"
                if opening_increase and model_probability < Decimal("0.95"):
                    if hours_to_resolution <= 1:
                        subscores["timing"] += 9
                        explanation.append("The trade was placed very close to a truth-revealing market moment while uncertainty still remained.")
                    elif hours_to_resolution <= 6:
                        subscores["timing"] += 5
            else:
                raw_metrics["hours_to_resolution"] = "Unavailable"
        except ValueError:
            raw_metrics["hours_to_resolution"] = "Unavailable"
    else:
        raw_metrics["hours_to_resolution"] = "Unavailable"

    off_hours_edge = False
    if (
        opening_increase
        and event_context.off_hours_flag
        and (
            size_basis >= Decimal("2500")
            or (liquidity_ratio is not None and liquidity_ratio >= Decimal("0.10"))
        )
    ):
        off_hours_edge = True
        flags.append("off_hours_local_entry")
        if liquidity_ratio is not None and liquidity_ratio >= Decimal("0.15"):
            subscores["timing"] += 5
        else:
            subscores["timing"] += 3
        explanation.append(
            "The trade landed during the event's local off-hours window, when large directional entries can be more informative."
        )

    if model_probability >= Decimal("0.98"):
        flags.append("near_certainty_trade")
        subscores["benign_discount"] -= 10
        reasons_against.append("The entry price already implied an almost certain outcome, which strongly weakens an insider-style interpretation.")
    elif model_probability >= Decimal("0.95"):
        flags.append("near_certainty_trade")
        subscores["benign_discount"] -= 6
        reasons_against.append("The entry price already implied a near-certain outcome, which strongly weakens an insider-style interpretation.")
    elif model_probability <= Decimal("0.30") and opening_increase:
        subscores["market_state"] += 4
        flags.append("low_probability_conviction")
        explanation.append("The trade committed real capital at a low implied probability, which makes the conviction more noteworthy.")

    if (
        opening_increase
        and event_context.market_deadline_flag
        and trade.side == "BUY"
        and trade.outcome.upper() == "NO"
        and hours_to_resolution is not None
        and hours_to_resolution <= 24
        and trade.price >= Decimal("0.70")
        and _move_is_at_most(favorable_moves["1h"], Decimal("0.03"))
    ):
        flags.append("theta_decay_pattern")
        subscores["benign_discount"] -= 10
        reasons_against.append("This looks more like an ordinary late deadline trade than a hidden-information entry.")

    if (
        opening_increase
        and model_probability >= Decimal("0.97")
        and capital_at_risk >= Decimal("5000")
        and _move_is_at_most(favorable_moves["1h"], Decimal("0.02"))
    ):
        flags.append("yield_farm_pattern")
        subscores["benign_discount"] -= 10
        reasons_against.append("The trade looks closer to near-certain capital parking than to a genuine information edge.")

    sensitivity_points = 0
    sensitivity_reason = "This category has moderate information-asymmetry sensitivity."
    for category in market.site_categories or ["Uncategorized"]:
        points, reason = category_sensitivity(category)
        if points > sensitivity_points:
            sensitivity_points = points
            sensitivity_reason = reason
    subscores["market_sensitivity"] += sensitivity_points
    explanation.append(sensitivity_reason)
    raw_metrics["site_categories"] = ", ".join(market.site_categories or ["Uncategorized"])

    if market.liquidity and market.liquidity <= Decimal("100000"):
        subscores["market_sensitivity"] += 2
        explanation.append("This market is thin enough that individual entries stand out more.")
    if market.volume and market.volume <= Decimal("300000"):
        subscores["market_sensitivity"] += 2

    cluster_direction = str(raw_metrics.get("cluster_direction") or "").strip()
    cluster_trades = []
    if cluster_direction:
        cluster_trades = [
            item
            for item in market_window_trades
            if _cluster_direction_for_trade(item) == cluster_direction
            and item.wallet != trade.wallet
            and abs((item.timestamp - trade.timestamp).total_seconds()) <= 30 * 60
        ]
    cluster_wallets = {item.wallet for item in cluster_trades}
    raw_metrics["cluster_wallets_30m_same_side"] = str(len(cluster_wallets))
    same_side_dollar_volume = trade.notional + sum((item.notional for item in cluster_trades), Decimal("0"))
    total_window_volume = sum(
        (
            item.notional
            for item in market_window_trades
            if abs((item.timestamp - trade.timestamp).total_seconds()) <= 30 * 60
        ),
        Decimal("0"),
    )
    same_side_share = (same_side_dollar_volume / total_window_volume) if total_window_volume > 0 else Decimal("0")
    raw_metrics["same_side_dollar_volume_30m"] = _fmt_decimal(same_side_dollar_volume)
    raw_metrics["same_side_share_30m"] = f"{(same_side_share * 100):.2f}%"
    if len(cluster_wallets) >= 4 and same_side_share >= Decimal("0.55") and market.liquidity <= Decimal("100000"):
        subscores["cluster"] += 4
        flags.append("coordinated_new_wallet_cluster")
        explanation.append("Several wallets hit the same side in a thin market quickly enough to look stronger than ordinary crowding.")
    elif len(cluster_wallets) >= 4 and same_side_share >= Decimal("0.45"):
        subscores["cluster"] += 2
        flags.append("crowded_same_side_entry")
        explanation.append("Several wallets entered the same side in a short time window, but this still looks closer to crowding than proven coordination.")
    elif len(cluster_wallets) >= 2 and same_side_share >= Decimal("0.30"):
        subscores["cluster"] += 1

    if wallet_inspection.recent_trade_count >= 50 and wallet_inspection.focus_market_count >= 5:
        subscores["benign_discount"] -= 6
        reasons_against.append("The wallet already has an established history in similar markets.")

    if len(same_market_wallet_trades) >= 2:
        first_entry = min(item.timestamp for item in same_market_wallet_trades)
        last_entry = max(item.timestamp for item in same_market_wallet_trades)
        if (last_entry - first_entry).total_seconds() >= 3600:
            subscores["benign_discount"] -= 4
            reasons_against.append("The position appears to have been built gradually rather than in one sharp entry.")

    if closed_summary.formal_win_rate_may_be_overstated:
        flags.append("zombie_position_distortion")
        subscores["benign_discount"] -= 3
        reasons_against.append("The wallet’s formal win rate may be overstated because several economically dead positions were never redeemed.")
    elif not closed_summary.economic_win_rate_clears_threshold and closed_summary.economic_sample_size >= 3:
        subscores["benign_discount"] -= 2
        reasons_against.append("The wallet’s economic track record is not strong enough to materially strengthen this case.")

    if activity_summary.low_analyst_value_flag:
        flags.append("low_analyst_value_wallet")
        flags.append("bot_like_execution")
        subscores["benign_discount"] -= 4
        reasons_against.append("The trading pattern looks highly automated and low-value for manual insider-style review.")
    elif activity_summary.bot_likeness_score >= 70:
        flags.append("bot_like_execution")
        subscores["benign_discount"] -= 3
        reasons_against.append("The trading pattern looks mechanically repetitive, which weakens the analyst value of this case.")

    history_note = economic_history_relevance_note(closed_summary)
    if history_note:
        raw_metrics["economic_history_note"] = history_note
    activity_note = bot_activity_note(activity_summary)
    if activity_note:
        raw_metrics["bot_activity_note"] = activity_note

    pre_suppressor_score = sum(value for key, value in subscores.items() if key != "benign_discount")
    raw_metrics["pre_suppressor_score"] = str(pre_suppressor_score)
    suspicion_score = max(
        0,
        min(
            100,
            pre_suppressor_score + subscores["benign_discount"],
        ),
    )
    confidence_score = _confidence_score(wallet_inspection, market)
    resolution_gap_type = _resolution_gap_type(
        trade=trade,
        market=market,
        opening_exposure_flag=opening_increase,
        hours_to_resolution=hours_to_resolution,
        consensus_edge=consensus_edge,
        favorable_moves=favorable_moves,
        flags=flags,
        event_context=event_context,
        model_probability=model_probability,
    )
    hard_resolution_gap_flag = resolution_gap_type == "hard"
    soft_resolution_gap_flag = resolution_gap_type == "possible"
    resolution_gap_flag = resolution_gap_type is not None
    case_type = "Resolution Gap" if hard_resolution_gap_flag else None
    raw_metrics["public_information_state"] = (
        "Hard Public Information" if hard_resolution_gap_flag else "Possible Public Lag" if soft_resolution_gap_flag else "No Public Lag Concern"
    )
    if resolution_gap_flag:
        raw_metrics["case_type"] = case_type or ""
        if hard_resolution_gap_flag:
            flags.append("offline_timeline_resolution_gap")
            explanation.append(
                "Offline timeline evidence suggests the event was already publicly knowable before this trade, making it look more like public-lag behavior."
            )
        else:
            explanation.append(
                "The setup may reflect slow market absorption of public information, but it does not fully negate the structural or timing signal."
            )
        if hard_resolution_gap_flag:
            reasons_against.append(
                "This looks closer to public-news lag or stale market pricing than to a private-information entry."
            )

    materially_uncertain = model_probability <= Decimal("0.94")
    beat_consensus = consensus_edge is not None and consensus_edge >= Decimal("0.03")
    favorable_repricing = (
        _move_is_at_least(favorable_moves["15m"], Decimal("0.02"))
        or _move_is_at_least(favorable_moves["1h"], Decimal("0.04"))
        or _move_is_at_least(favorable_moves["4h"], Decimal("0.06"))
        or _move_is_at_least(favorable_moves["24h"], Decimal("0.10"))
    )
    decisive_timing_edge = bool(
        (consensus_edge is not None and consensus_edge >= Decimal("0.02"))
        or _move_is_at_least(favorable_moves["15m"], Decimal("0.02"))
        or _move_is_at_least(favorable_moves["1h"], Decimal("0.04"))
        or _move_is_at_least(favorable_moves["4h"], Decimal("0.06"))
    )
    specialist_explained_pattern = bool(
        "domain_specialist_profile" in flags
        and wallet_inspection.domain_concentration_score >= 0.75
        and (wallet_inspection.public_model_specialist_flag or wallet_inspection.recent_trade_count >= 50)
        and domain_peer_percentile is not None
        and domain_peer_percentile < 90
        and not beat_consensus
        and _move_is_at_most(favorable_moves["1h"], Decimal("0.08"))
    )
    credibility_gamed = bool(
        closed_summary.formal_win_rate_may_be_overstated or activity_summary.low_analyst_value_flag
    )
    benign_pattern = any(
        flag in flags
        for flag in ("yield_farm_pattern", "theta_decay_pattern", "near_certainty_trade")
    ) or specialist_explained_pattern
    liquidity_shock_signal = bool(
        (liquidity_ratio is not None and liquidity_ratio >= Decimal("0.15"))
        or "liquidity_drain_extreme" in flags
        or "large_trade_relative_to_market" in flags
    )
    coordinated_cluster_signal = "coordinated_new_wallet_cluster" in flags
    strong_timing_proof_count = sum(
        1
        for value in (beat_consensus, favorable_repricing, entry_rank_signal)
        if value
    )
    supporting_booster_count = sum(
        1
        for value in (off_hours_edge, liquidity_shock_signal, coordinated_cluster_signal)
        if value
    )
    timing_evidence_count = sum(
        1
        for value in (
            beat_consensus,
            favorable_repricing,
            entry_rank_signal,
            off_hours_edge,
            liquidity_shock_signal,
            coordinated_cluster_signal,
        )
        if value
    )
    raw_metrics["materially_uncertain_flag"] = "Yes" if materially_uncertain else "No"
    raw_metrics["beat_consensus_flag"] = "Yes" if beat_consensus else "No"
    raw_metrics["favorable_repricing_flag"] = "Yes" if favorable_repricing else "No"
    raw_metrics["decisive_timing_edge_flag"] = "Yes" if decisive_timing_edge else "No"
    raw_metrics["timing_evidence_count"] = str(timing_evidence_count)
    raw_metrics["strong_timing_proof_count"] = str(strong_timing_proof_count)
    raw_metrics["supporting_booster_count"] = str(supporting_booster_count)
    raw_metrics["prospective_timing_evidence_count"] = str(
        sum(1 for value in (beat_consensus, entry_rank_signal, off_hours_edge, liquidity_shock_signal, coordinated_cluster_signal) if value)
    )
    raw_metrics["retrospective_timing_evidence_count"] = str(int(favorable_repricing))
    raw_metrics["liquidity_shock_signal"] = "Yes" if liquidity_shock_signal else "No"
    raw_metrics["coordinated_cluster_signal"] = "Yes" if coordinated_cluster_signal else "No"
    raw_metrics["benign_pattern_flag"] = "Yes" if benign_pattern else "No"
    raw_metrics["resolution_gap_flag"] = "Yes" if resolution_gap_flag else "No"
    raw_metrics["resolution_gap_type"] = resolution_gap_type or ""
    raw_metrics["hard_resolution_gap_flag"] = "Yes" if hard_resolution_gap_flag else "No"
    raw_metrics["soft_resolution_gap_flag"] = "Yes" if soft_resolution_gap_flag else "No"
    raw_metrics["possible_public_lag_flag"] = "Yes" if soft_resolution_gap_flag else "No"
    raw_metrics["hard_public_information_flag"] = "Yes" if hard_resolution_gap_flag else "No"
    raw_metrics["specialist_explained_flag"] = "Yes" if specialist_explained_pattern else "No"
    raw_metrics["credibility_gamed_flag"] = "Yes" if credibility_gamed else "No"
    raw_metrics.update(
        _repricing_source_quality_metrics(
            trade=trade,
            market=market,
            market_outcome_trades=same_outcome_market_trades,
            favorable_moves=favorable_moves,
            favorable_repricing=favorable_repricing,
            liquidity_ratio=liquidity_ratio,
            flags=flags,
            raw_metrics=raw_metrics,
            model_probability=model_probability,
        )
    )
    _update_suspicious_funding_quality(raw_metrics, flags)
    structural_concern_count, structural_concern_tier = _structural_concern_snapshot(
        flags=flags,
        raw_metrics=raw_metrics,
    )
    raw_metrics["structural_concern_count"] = str(structural_concern_count)
    raw_metrics["structural_concern_tier"] = structural_concern_tier
    raw_metrics["structural_concern_flag"] = "Yes" if structural_concern_count >= 1 else "No"

    if suspicion_score < 18 and not resolution_gap_flag and not include_below_threshold:
        return None

    severity = _severity_from_score(
        suspicion_score,
        confidence_score,
        opening_exposure_flag=opening_increase,
        materially_uncertain=materially_uncertain,
        decisive_timing_edge=decisive_timing_edge,
        strong_timing_proof_count=strong_timing_proof_count,
        supporting_booster_count=supporting_booster_count,
        structural_concern_count=structural_concern_count,
        benign_pattern=benign_pattern,
        credibility_gamed=credibility_gamed,
        hard_resolution_gap_flag=hard_resolution_gap_flag,
        soft_resolution_gap_flag=soft_resolution_gap_flag,
    )
    raw_metrics.update(
        _strong_risk_attribution_metrics(
            severity=severity,
            score=suspicion_score,
            confidence_score=confidence_score,
            raw_metrics=raw_metrics,
            flags=flags,
        )
    )
    review_priority = _review_priority_for_case(severity, case_type, suspicion_score)
    verdict = _verdict_for_case(severity, case_type)

    return FlaggedCase(
        severity=severity,
        case_type=case_type,
        suspicion_score=suspicion_score,
        confidence_score=confidence_score,
        review_priority=review_priority,
        verdict=verdict,
        trade_count_window=len(same_market_wallet_trades),
        window_start=min(item.timestamp for item in same_market_wallet_trades).isoformat(),
        window_end=max(item.timestamp for item in same_market_wallet_trades).isoformat(),
        trade=trade,
        market=market,
        wallet_inspection=wallet_inspection,
        subscores=subscores,
        flags=flags,
        explanation=explanation[:5],
        reasons_against=reasons_against[:3],
        raw_metrics=raw_metrics,
        initial_suspicion_score=suspicion_score,
        latest_suspicion_score=suspicion_score,
        initial_severity=severity,
        latest_severity=severity,
    )


def _percentile_rank(value: float, values: list[float]) -> float:
    if not values:
        return 0.0
    less_or_equal = sum(1 for item in values if item <= value)
    return (less_or_equal / len(values)) * 100.0


def _percentile_rank_sorted(value: float, values: list[float]) -> float:
    if not values:
        return 0.0
    return (bisect_right(values, value) / len(values)) * 100.0


def _sorted_trade_notionals(trades: list[Trade]) -> list[float]:
    return sorted(float(item.notional) for item in trades)


def _classify_execution_state(
    trade: Trade,
    prior_same_asset_trades: list[Trade],
    prior_same_market_trades: list[Trade],
) -> str:
    prior_position = Decimal("0")
    for item in sorted(prior_same_asset_trades, key=lambda row: (row.timestamp, row.trade_id)):
        if item.side == "BUY":
            prior_position += item.size
        elif item.side == "SELL":
            prior_position -= item.size
    if trade.side == "BUY":
        return "increase_long"
    if prior_position <= Decimal("0.01"):
        if any(item.side == "BUY" and item.asset_id != trade.asset_id for item in prior_same_market_trades[-6:]):
            return "roll"
        return "increase_short"
    if prior_position <= trade.size * Decimal("1.05"):
        return "close"
    return "reduce"


def _classify_trade_state(
    trade: Trade,
    prior_same_asset_trades: list[Trade],
    prior_same_market_trades: list[Trade],
) -> str:
    return _legacy_trade_state(
        _classify_execution_state(trade, prior_same_asset_trades, prior_same_market_trades)
    )


def _legacy_trade_state(execution_state: str) -> str:
    if execution_state in {"increase_long", "increase_short"}:
        return "increase"
    return execution_state


def _is_opening_exposure(execution_state: str) -> bool:
    return execution_state in {"increase_long", "increase_short"}


def _economic_direction(trade: Trade, execution_state: str) -> str:
    if execution_state == "increase_short":
        return f"short_{trade.outcome.lower()}"
    return f"long_{trade.outcome.lower()}"


def _capital_at_risk_usdc(trade: Trade, execution_state: str) -> Decimal:
    if _is_opening_exposure(execution_state):
        return trade.notional
    return Decimal("0")


def _capital_at_risk(trade: Trade, trade_state: str) -> Decimal:
    if trade_state == "increase" and trade.side == "BUY":
        return trade.notional
    return Decimal("0")


def _uncertainty_level(price: Decimal) -> Decimal:
    return max(Decimal("0"), Decimal("1") - abs(price - Decimal("0.5")) * Decimal("2"))


def _consensus_edge(market_outcome_trades: list[Trade], trade: Trade) -> Decimal | None:
    prior_prices = [
        item.price
        for item in market_outcome_trades
        if item.trade_id != trade.trade_id
        and item.timestamp < trade.timestamp
        and (trade.timestamp - item.timestamp).total_seconds() <= 15 * 60
    ]
    if len(prior_prices) < 2:
        return None
    consensus = Decimal(str(median(float(price) for price in prior_prices)))
    if trade.side == "BUY":
        return consensus - trade.price
    return trade.price - consensus


def _favorable_moves_after_entry(market_outcome_trades: list[Trade], trade: Trade) -> dict[str, Decimal | None]:
    windows = {
        "15m": trade.timestamp + timedelta(minutes=15),
        "1h": trade.timestamp + timedelta(hours=1),
        "4h": trade.timestamp + timedelta(hours=4),
        "24h": trade.timestamp + timedelta(hours=24),
    }
    future_prices = {label: [] for label in windows}
    latest_observed = trade.timestamp
    for item in market_outcome_trades:
        if item.timestamp <= trade.timestamp:
            continue
        if item.timestamp > latest_observed:
            latest_observed = item.timestamp
        for label, cutoff in windows.items():
            if item.timestamp <= cutoff:
                future_prices[label].append(item.price)
    moves: dict[str, Decimal | None] = {}
    for label, prices in future_prices.items():
        if latest_observed < windows[label]:
            moves[label] = None
            continue
        if not prices:
            moves[label] = Decimal("0")
            continue
        max_price = max(prices)
        min_price = min(prices)
        if trade.side == "BUY":
            moves[label] = max(Decimal("0"), max_price - trade.price)
        else:
            moves[label] = max(Decimal("0"), trade.price - min_price)
    return moves


def _repricing_source_quality_metrics(
    *,
    trade: Trade,
    market: Market,
    market_outcome_trades: list[Trade],
    favorable_moves: dict[str, Decimal | None],
    favorable_repricing: bool,
    liquidity_ratio: Decimal | None,
    flags: list[str],
    raw_metrics: dict[str, str],
    model_probability: Decimal,
) -> dict[str, str]:
    window_label = _repricing_quality_window(favorable_moves)
    driver_stats = _repricing_driver_stats(
        trade=trade,
        market_outcome_trades=market_outcome_trades,
        window_label=window_label,
    )
    same_outcome_trade_count = len(market_outcome_trades)
    metrics = {
        "repricing_source_quality": REPRICING_SOURCE_QUALITY_NONE,
        "repricingSourceQuality": REPRICING_SOURCE_QUALITY_NONE,
        "repricing_source_quality_reasons": "",
        "repricingSourceQualityReasons": "",
        "repricing_quality_window": window_label,
        "repricing_driver_trade_count": str(driver_stats["driver_trade_count"]),
        "repricing_driver_wallet_count": str(driver_stats["driver_wallet_count"]),
        "repricing_window_trade_count": str(driver_stats["window_trade_count"]),
        "repricing_same_outcome_trade_count": str(same_outcome_trade_count),
        "repricing_driven_by_single_wallet": "Yes" if driver_stats["single_driver"] else "No",
    }
    if not favorable_repricing:
        return metrics

    thin_market = market.liquidity > 0 and market.liquidity <= Decimal("100000")
    very_thin_market = market.liquidity > 0 and market.liquidity <= Decimal("50000")
    low_volume = market.volume > 0 and market.volume <= Decimal("300000")
    low_trade_count = same_outcome_trade_count < 8 or driver_stats["window_trade_count"] < 3
    high_price = model_probability >= Decimal("0.85")
    near_certainty_or_decay = any(
        flag in flags
        for flag in ("near_certainty_trade", "yield_farm_pattern", "theta_decay_pattern")
    )
    stale_or_public_lag = (
        raw_metrics.get("stale_resolution_annotation") == "Yes"
        or raw_metrics.get("hard_public_information_flag") == "Yes"
        or raw_metrics.get("resolution_gap_type") == "hard"
    )
    large_liquidity_share = liquidity_ratio is not None and liquidity_ratio >= Decimal("0.15")
    reasons: list[str] = []

    def add_reason(condition: bool, text: str) -> None:
        if condition:
            reasons.append(text)

    add_reason(near_certainty_or_decay, "near-certainty/yield/theta suppressor is present")
    add_reason(stale_or_public_lag, "stale or public-lag flag is present")
    add_reason(driver_stats["single_driver"], "repricing is driven by one trade or wallet in the loaded tape")
    add_reason(very_thin_market, "market liquidity is very thin")
    add_reason(thin_market and not very_thin_market, "market liquidity is thin")
    add_reason(low_volume, "market volume is low")
    add_reason(low_trade_count, "loaded same-outcome trade count is low")
    add_reason(high_price, "entry price was already high")
    add_reason(large_liquidity_share, "entry consumed a large liquidity share")

    mechanical = bool(
        near_certainty_or_decay
        or stale_or_public_lag
        or (
            driver_stats["single_driver"]
            and (very_thin_market or low_trade_count or large_liquidity_share or high_price)
        )
    )
    weak = bool(
        thin_market
        or low_volume
        or low_trade_count
        or driver_stats["single_driver"]
        or high_price
        or large_liquidity_share
    )
    if mechanical:
        quality = REPRICING_SOURCE_QUALITY_MECHANICAL
    elif weak:
        quality = REPRICING_SOURCE_QUALITY_WEAK
    else:
        quality = REPRICING_SOURCE_QUALITY_STRONG
        reasons.append("repricing has multi-trade confirmation in a non-thin market without stale/near-certainty suppressors")

    reason_text = "; ".join(reasons)
    metrics["repricing_source_quality"] = quality
    metrics["repricingSourceQuality"] = quality
    metrics["repricing_source_quality_reasons"] = reason_text
    metrics["repricingSourceQualityReasons"] = reason_text
    return metrics


def _repricing_quality_window(favorable_moves: dict[str, Decimal | None]) -> str:
    for label, threshold in (
        ("15m", Decimal("0.02")),
        ("1h", Decimal("0.04")),
        ("4h", Decimal("0.06")),
        ("24h", Decimal("0.10")),
    ):
        if _move_is_at_least(favorable_moves.get(label), threshold):
            return label
    for label in ("15m", "1h", "4h", "24h"):
        if favorable_moves.get(label) is not None:
            return label
    return ""


def _repricing_driver_stats(
    *,
    trade: Trade,
    market_outcome_trades: list[Trade],
    window_label: str,
) -> dict[str, int | bool]:
    if not window_label:
        return {
            "driver_trade_count": 0,
            "driver_wallet_count": 0,
            "window_trade_count": 0,
            "single_driver": False,
        }
    cutoffs = {
        "15m": trade.timestamp + timedelta(minutes=15),
        "1h": trade.timestamp + timedelta(hours=1),
        "4h": trade.timestamp + timedelta(hours=4),
        "24h": trade.timestamp + timedelta(hours=24),
    }
    cutoff = cutoffs.get(window_label)
    if cutoff is None:
        return {
            "driver_trade_count": 0,
            "driver_wallet_count": 0,
            "window_trade_count": 0,
            "single_driver": False,
        }
    window_trades = [
        item
        for item in market_outcome_trades
        if item.timestamp > trade.timestamp and item.timestamp <= cutoff
    ]
    if trade.side == "BUY":
        driver_trades = [item for item in window_trades if item.price > trade.price]
    else:
        driver_trades = [item for item in window_trades if item.price < trade.price]
    driver_wallets = {item.wallet for item in driver_trades if item.wallet}
    single_driver = bool(driver_trades and (len(driver_trades) <= 1 or len(driver_wallets) <= 1))
    return {
        "driver_trade_count": len(driver_trades),
        "driver_wallet_count": len(driver_wallets),
        "window_trade_count": len(window_trades),
        "single_driver": single_driver,
    }


def _market_entry_rank(market_outcome_trades: list[Trade], trade: Trade) -> tuple[int | None, float | None]:
    ordered = sorted(market_outcome_trades, key=lambda item: (item.timestamp, item.trade_id))
    for index, item in enumerate(ordered, start=1):
        if item.trade_id == trade.trade_id:
            return index, index / len(ordered) if ordered else None
    return None, None


def _wallet_market_conviction_ratio(wallet_window_trades: list[Trade], trade: Trade) -> float:
    total_notional = sum((item.notional for item in wallet_window_trades), Decimal("0"))
    if total_notional <= 0:
        return 0.0
    market_notional = sum(
        (item.notional for item in wallet_window_trades if item.condition_id == trade.condition_id),
        Decimal("0"),
    )
    return float(market_notional / total_notional)


def _looks_like_deadline_market(question: str) -> bool:
    text = question.lower()
    return any(marker in text for marker in (" by ", "before ", "by april", "by may", "by june", "by july", "by august", "by september", "by october", "by november", "by december"))


def _move_is_at_least(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value >= threshold


def _move_is_at_most(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value <= threshold


def _resolution_gap_type(
    *,
    trade: Trade,
    market: Market,
    opening_exposure_flag: bool,
    hours_to_resolution: float | None,
    consensus_edge: Decimal | None,
    favorable_moves: dict[str, Decimal | None],
    flags: list[str],
    event_context: EventContext,
    model_probability: Decimal,
) -> str | None:
    if not opening_exposure_flag:
        return None

    if event_context.public_outcome_at is not None and trade.timestamp >= event_context.public_outcome_at:
        return "hard"
    if event_context.stale_resolution_annotation and event_context.public_knowledge_at is not None:
        if trade.timestamp >= event_context.public_knowledge_at:
            return "hard"
    if event_context.official_confirmation_at is not None and trade.timestamp >= event_context.official_confirmation_at:
        if model_probability >= Decimal("0.90"):
            return "hard"
    if event_context.broad_report_at is not None and trade.timestamp >= event_context.broad_report_at:
        if model_probability >= Decimal("0.95") and _move_is_at_most(favorable_moves["1h"], Decimal("0.02")):
            return "possible"

    near_certainty = model_probability >= Decimal("0.94")
    very_low_uncertainty = _uncertainty_level(model_probability) <= Decimal("0.12")
    weak_repricing = (
        (
            favorable_moves["15m"] is None
            or favorable_moves["15m"] <= Decimal("0.02")
        )
        and (
            favorable_moves["1h"] is None
            or favorable_moves["1h"] <= Decimal("0.03")
        )
        and (
            favorable_moves["4h"] is None
            or favorable_moves["4h"] <= Decimal("0.05")
        )
    )
    weak_consensus_edge = consensus_edge is None or consensus_edge < Decimal("0.02")
    stale_window = (
        hours_to_resolution is None
        or hours_to_resolution <= 120
        or _looks_like_deadline_market(market.question)
    )
    late_entry_pattern = any(flag in flags for flag in ("near_certainty_trade", "yield_farm_pattern"))

    if (
        near_certainty
        and very_low_uncertainty
        and weak_repricing
        and weak_consensus_edge
        and stale_window
        and (late_entry_pattern or model_probability >= Decimal("0.97") or favorable_moves["1h"] is None or favorable_moves["1h"] <= Decimal("0.01"))
    ):
        return "possible"
    return None


def _confidence_score(wallet_inspection: WalletInspection, market: Market) -> int:
    score = 40
    if wallet_inspection.traded_market_count is not None:
        score += 20
    if wallet_inspection.first_trade_at:
        score += 15
    if market.liquidity > 0:
        score += 15
    if market.volume > 0:
        score += 10
    return min(score, 100)


def _severity_from_score(
    score: int,
    confidence_score: int,
    *,
    opening_exposure_flag: bool,
    materially_uncertain: bool,
    decisive_timing_edge: bool,
    strong_timing_proof_count: int,
    supporting_booster_count: int,
    structural_concern_count: int,
    benign_pattern: bool,
    credibility_gamed: bool,
    hard_resolution_gap_flag: bool,
    soft_resolution_gap_flag: bool,
) -> str:
    if hard_resolution_gap_flag:
        return "Low Risk"
    timing_led_strong = (
        opening_exposure_flag
        and decisive_timing_edge
        and strong_timing_proof_count >= 1
        and (supporting_booster_count >= 1 or structural_concern_count >= 1)
        and confidence_score >= 50
        and score >= 40
    )
    structure_led_strong = (
        opening_exposure_flag
        and structural_concern_count >= 2
        and confidence_score >= 50
        and score >= 36
    )
    if timing_led_strong or structure_led_strong:
        return "Strong Risk"
    if opening_exposure_flag and structural_concern_count >= 2 and score >= 24:
        return "Worth a Look"
    if score >= 28:
        return "Worth a Look"
    return "Low Risk"


def _strong_risk_attribution_metrics(
    *,
    severity: str,
    score: int,
    confidence_score: int,
    raw_metrics: dict[str, object],
    flags: list[str] | tuple[str, ...] | set[str] | None,
    retrospective_event_forensic: bool = False,
) -> dict[str, str]:
    """Explain the existing Strong Risk gate without changing score or severity."""

    flags_set = {str(flag or "") for flag in (flags or [])}
    opening_exposure = (
        str(raw_metrics.get("opening_exposure_flag") or "").strip() == "Yes"
        or str(raw_metrics.get("trade_state") or "").strip() == "increase"
    )
    decisive_timing_edge = str(raw_metrics.get("decisive_timing_edge_flag") or "").strip() == "Yes"
    strong_timing_count = _metric_int_like(raw_metrics.get("strong_timing_proof_count"))
    supporting_booster_count = _metric_int_like(raw_metrics.get("supporting_booster_count"))
    structural_count = _metric_int_like(raw_metrics.get("structural_concern_count"))
    timing_gate = bool(
        opening_exposure
        and decisive_timing_edge
        and strong_timing_count >= 1
        and (supporting_booster_count >= 1 or structural_count >= 1)
        and confidence_score >= 50
        and score >= 40
    )
    structure_gate = bool(
        opening_exposure
        and structural_count >= 2
        and confidence_score >= 50
        and score >= 36
    )
    strong_risk = str(severity or "").startswith("Strong Risk") or retrospective_event_forensic

    timing_sources = _strong_risk_timing_sources(raw_metrics, flags_set)
    structural_sources = _strong_risk_structural_sources(raw_metrics, flags_set)
    boosters = _strong_risk_supporting_boosters(raw_metrics, flags_set)
    suppressor_conflicts = _strong_risk_suppressor_conflicts(
        raw_metrics,
        flags_set,
        timing_sources=timing_sources,
        structural_sources=structural_sources,
    )
    hard_sources = _text_values(raw_metrics.get("hardEvidenceSources"))
    has_hard_sources = bool(hard_sources)
    exact_gate_metrics = _strong_risk_exact_gate_metrics(
        severity=severity,
        score=score,
        confidence_score=confidence_score,
        opening_exposure=opening_exposure,
        decisive_timing_edge=decisive_timing_edge,
        strong_timing_count=strong_timing_count,
        supporting_booster_count=supporting_booster_count,
        structural_count=structural_count,
        timing_sources=timing_sources,
        booster_sources=boosters,
        structural_sources=structural_sources,
        hard_resolution_gap_flag=(
            str(raw_metrics.get("hard_public_information_flag") or "").strip() == "Yes"
            or str(raw_metrics.get("hard_resolution_gap_flag") or "").strip() == "Yes"
        ),
        retrospective_event_forensic=retrospective_event_forensic,
    )

    if not strong_risk:
        gate_type = "not_strong_risk"
        composition = "not_strong_risk"
        gate_reasons: list[str] = []
    elif retrospective_event_forensic:
        gate_type = "retrospective_event_forensic"
        composition = "retrospective_correctness"
        gate_reasons = ["event_forensic_retrospective_correctness"]
    elif timing_gate and structure_gate:
        gate_type = "mixed_timing_structure"
        composition = "structural" if structural_sources else "timing_with_support"
        gate_reasons = ["existing_timing_led_gate", "existing_structure_led_gate"]
    elif structure_gate:
        gate_type = "structure_led"
        composition = "structural"
        gate_reasons = ["existing_structure_led_gate"]
    elif timing_gate:
        gate_type = "timing_led"
        composition = "timing_with_support" if (structural_sources or boosters) else "timing_only"
        gate_reasons = ["existing_timing_led_gate"]
    else:
        gate_type = "timing_led" if timing_sources else "structure_led" if structural_sources else "legacy_unknown"
        composition = "contextual_or_ambiguous" if suppressor_conflicts else "score_only"
        gate_reasons = ["strong_risk_saved_without_reconstructable_gate"]

    gate_sources = _dedupe_text(timing_sources + structural_sources + boosters)
    if retrospective_event_forensic:
        gate_sources = _dedupe_text(["event_forensic_retrospective_correctness", *gate_sources])
    if strong_risk and not gate_sources and composition == "score_only":
        gate_type = "legacy_unknown" if not any(
            str(raw_metrics.get(key) or "").strip()
            for key in (
                "strong_timing_proof_count",
                "supporting_booster_count",
                "structural_concern_count",
                "opening_exposure_flag",
                "decisive_timing_edge_flag",
            )
        ) else gate_type

    no_hard_explanation = ""
    if strong_risk and not has_hard_sources:
        if gate_type == "retrospective_event_forensic":
            no_hard_explanation = "Retrospective event-forensic correctness/rank, not structural hard evidence."
        elif gate_type == "timing_led":
            no_hard_explanation = "Strong Risk is timing-led; hardEvidenceSources are reserved for structural hard-evidence review sources."
        elif gate_type == "legacy_unknown":
            no_hard_explanation = "Saved row lacks enough gate-source fields to attribute Strong Risk."
        elif composition == "score_only":
            no_hard_explanation = "No timing, structural, or retrospective gate source is identifiable from saved fields."
        else:
            no_hard_explanation = "No structural hardEvidenceSources were saved for this Strong Risk row."
    source_attribution = _strong_risk_source_attribution_metrics(
        strong_risk=strong_risk,
        gate_type=gate_type,
        structural_sources=structural_sources,
        hard_sources=hard_sources,
        structural_count=structural_count,
        no_hard_explanation=no_hard_explanation,
    )
    score_only_resolution = "not_applicable"
    leakage_candidate = "No"
    leakage_reason = ""
    if strong_risk and composition == "score_only":
        score_only_resolution = "actual_score_only_gate_leakage_candidate"
        leakage_candidate = "Yes"
        leakage_reason = "No exact timing, structural, or retrospective gate branch was identified."

    return {
        "strongRiskGatePassed": "Yes" if strong_risk else "No",
        "strongRiskGateType": gate_type,
        "strongRiskGateReasons": "; ".join(_dedupe_text(gate_reasons)),
        "strongRiskGateEvidenceSources": "; ".join(gate_sources),
        "strongRiskTimingProofSources": "; ".join(_dedupe_text(timing_sources)),
        "strongRiskStructuralSources": "; ".join(_dedupe_text(structural_sources)),
        "strongRiskSupportingBoosters": "; ".join(_dedupe_text(boosters)),
        "strongRiskStructuralConcernCount": str(structural_count),
        "strongRiskTimingProofCount": str(strong_timing_count),
        "strongRiskOpeningExposureConfirmed": "Yes" if opening_exposure else "No",
        "strongRiskConfidenceScore": str(confidence_score),
        "strongRiskSuspicionScore": str(score),
        "strongRiskSuppressorConflict": "Yes" if suppressor_conflicts else "No",
        "strongRiskSuppressorConflictReasons": "; ".join(_dedupe_text(suppressor_conflicts)),
        "strongRiskHasHardEvidenceSources": "Yes" if has_hard_sources else "No",
        "strongRiskNoHardEvidenceExplanation": no_hard_explanation,
        "strongRiskCompositionClass": composition,
        "strongRiskGateSourceWasInferred": "No",
        "strongRiskGateSourceInferenceReason": "",
        "strongRiskScoreOnlyResolution": score_only_resolution,
        "strongRiskGateLeakageCandidate": leakage_candidate,
        "strongRiskGateLeakageReason": leakage_reason,
        "strongRiskLiveDetectable": "No" if retrospective_event_forensic else "Yes" if strong_risk else "No",
        "strongRiskRetrospectiveOnly": "Yes" if retrospective_event_forensic else "No",
        "strongRiskRetrospectiveSources": "event_forensic_retrospective_correctness" if retrospective_event_forensic else "",
        **_strong_risk_gate_trace_metrics(
            strong_risk=strong_risk,
            gate_type=gate_type,
            composition=composition,
            score=score,
            confidence_score=confidence_score,
            exact_gate_metrics=exact_gate_metrics,
            timing_sources=timing_sources,
            structural_sources=structural_sources,
            booster_sources=boosters,
            hard_sources=hard_sources,
            hard_eligible_sources=_text_values(source_attribution.get("strongRiskHardEvidenceEligibleSources")),
            suppressor_conflicts=suppressor_conflicts,
            opening_exposure=opening_exposure,
            retrospective_event_forensic=retrospective_event_forensic,
        ),
        **exact_gate_metrics,
        **source_attribution,
    }


def _strong_risk_gate_trace_metrics(
    *,
    strong_risk: bool,
    gate_type: str,
    composition: str,
    score: int,
    confidence_score: int,
    exact_gate_metrics: dict[str, str],
    timing_sources: list[str],
    structural_sources: list[str],
    booster_sources: list[str],
    hard_sources: list[str],
    hard_eligible_sources: list[str],
    suppressor_conflicts: list[str],
    opening_exposure: bool,
    retrospective_event_forensic: bool,
) -> dict[str, str]:
    """Expose the saved Strong Risk gate path without changing the gate itself."""

    exact_branch = str(exact_gate_metrics.get("strongRiskExactGateBranch") or "").strip()
    if not strong_risk:
        gate_name = "not_strong_risk"
        gate_family = "unknown"
    elif retrospective_event_forensic or gate_type == "retrospective_event_forensic":
        gate_name = exact_branch or "retrospective_event_forensic_gate"
        gate_family = "retrospective_correctness"
    elif gate_type in {"structure_led", "mixed_timing_structure"}:
        gate_name = exact_branch or "structure_led_gate"
        gate_family = "structural"
    elif gate_type == "timing_led":
        gate_name = exact_branch or "timing_led_gate"
        gate_family = "timing_repricing"
    elif composition == "score_only":
        gate_name = "score_threshold_unclear"
        gate_family = "score_threshold"
    elif any("funding" in source for source in hard_sources + hard_eligible_sources + structural_sources):
        gate_name = gate_type or "funding_context_gate"
        gate_family = "funding"
    elif any(source in {"domain_peer_outlier", "wallet_size_anomaly"} for source in structural_sources):
        gate_name = gate_type or "wallet_behavior_gate"
        gate_family = "wallet_behavior"
    else:
        gate_name = gate_type or exact_branch or "unknown"
        gate_family = "unknown"

    independent_sources = _dedupe_text(
        [
            source
            for source in [*hard_sources, *hard_eligible_sources]
            if source and source != "suspicious_recent_funding"
        ]
    )
    has_independent = bool(independent_sources)
    timing_repricing_only = bool(
        strong_risk
        and gate_family == "timing_repricing"
        and not has_independent
        and not structural_sources
    )
    score_only = bool(strong_risk and (composition == "score_only" or gate_family == "score_threshold"))
    saved_fields_sufficient = bool(
        not strong_risk
        or (
            exact_branch
            and exact_branch not in {"legacy_unknown", "not_strong_risk"}
            and gate_family != "unknown"
        )
    )
    opening_status = "confirmed" if opening_exposure else "not_confirmed"
    gate_inputs = {
        "exact": exact_gate_metrics.get("strongRiskExactGateInputs") or "",
        "timing": exact_gate_metrics.get("strongRiskTimingGateInputs") or "",
        "structure": exact_gate_metrics.get("strongRiskStructureGateInputs") or "",
        "retrospective": exact_gate_metrics.get("strongRiskRetrospectiveGateInputs") or "",
    }
    trace = {
        "gateName": gate_name,
        "gateFamily": gate_family,
        "gateType": gate_type,
        "composition": composition,
        "exactGateBranch": exact_branch,
        "strongRisk": strong_risk,
        "score": score,
        "confidenceScore": confidence_score,
        "timingSources": timing_sources,
        "structuralSources": structural_sources,
        "boosterSources": booster_sources,
        "hardEvidenceSources": hard_sources,
        "independentEvidenceSources": independent_sources,
        "hasIndependentHardEvidence": has_independent,
        "suppressorConflictReasons": suppressor_conflicts,
        "openingExposureStatus": opening_status,
        "timingRepricingOnly": timing_repricing_only,
        "retrospectiveOnly": bool(retrospective_event_forensic),
        "scoreOnly": score_only,
        "savedFieldsSufficient": saved_fields_sufficient,
        "diagnosticOnly": True,
    }
    return {
        "strongRiskGateTrace": json.dumps(trace, sort_keys=True),
        "strongRiskGateName": gate_name,
        "strongRiskGateFamily": gate_family,
        "strongRiskGateInputs": json.dumps(gate_inputs, sort_keys=True),
        "strongRiskHasIndependentHardEvidence": "Yes" if has_independent else "No",
        "strongRiskIndependentEvidenceSources": "; ".join(independent_sources),
        "strongRiskOpeningExposureStatus": opening_status,
        "strongRiskTimingRepricingOnly": "Yes" if timing_repricing_only else "No",
        "strongRiskScoreOnly": "Yes" if score_only else "No",
        "strongRiskSavedFieldsSufficient": "Yes" if saved_fields_sufficient else "No",
        "strongRiskDiagnosticOnly": "Yes",
    }


def _strong_risk_exact_gate_metrics(
    *,
    severity: str,
    score: int,
    confidence_score: int,
    opening_exposure: bool,
    decisive_timing_edge: bool,
    strong_timing_count: int,
    supporting_booster_count: int,
    structural_count: int,
    timing_sources: list[str],
    booster_sources: list[str],
    structural_sources: list[str],
    hard_resolution_gap_flag: bool,
    retrospective_event_forensic: bool = False,
) -> dict[str, str]:
    strong_risk = str(severity or "").startswith("Strong Risk") or retrospective_event_forensic
    timing_inputs = {
        "opening_exposure_confirmed": opening_exposure,
        "decisive_timing_edge": decisive_timing_edge,
        "strong_timing_proof_exists": strong_timing_count >= 1,
        "timing_proof_count": strong_timing_count,
        "timing_proof_sources": timing_sources,
        "supporting_booster_exists": supporting_booster_count >= 1,
        "supporting_booster_sources": booster_sources,
        "structural_concern_count": structural_count,
        "confidence_threshold_passed": confidence_score >= 50,
        "score_threshold_passed": score >= 40,
        "hard_public_resolution_gap_block_absent": not hard_resolution_gap_flag,
    }
    structure_inputs = {
        "opening_exposure_confirmed": opening_exposure,
        "structural_concern_count": structural_count,
        "structural_concern_sources": structural_sources,
        "structural_threshold_passed": structural_count >= 2,
        "confidence_threshold_passed": confidence_score >= 50,
        "score_threshold_passed": score >= 36,
        "hard_public_resolution_gap_block_absent": not hard_resolution_gap_flag,
    }
    timing_gate = bool(
        not hard_resolution_gap_flag
        and opening_exposure
        and decisive_timing_edge
        and strong_timing_count >= 1
        and (supporting_booster_count >= 1 or structural_count >= 1)
        and confidence_score >= 50
        and score >= 40
    )
    structure_gate = bool(
        not hard_resolution_gap_flag
        and opening_exposure
        and structural_count >= 2
        and confidence_score >= 50
        and score >= 36
    )
    retrospective_inputs = {
        "retrospective_event_forensic": retrospective_event_forensic,
        "later_correctness": retrospective_event_forensic,
        "winner_rank": "",
        "low_probability_winner": "",
        "dormant_after_win": "",
        "resolved_event_only": retrospective_event_forensic,
        "live_detectable": not retrospective_event_forensic,
    }
    failed_reasons: list[str] = []
    if hard_resolution_gap_flag:
        failed_reasons.append("hard_public_resolution_gap_block")
    if not opening_exposure:
        failed_reasons.append("opening_exposure_not_confirmed")
    if not timing_gate:
        if not decisive_timing_edge:
            failed_reasons.append("timing_gate_missing_decisive_timing_edge")
        if strong_timing_count < 1:
            failed_reasons.append("timing_gate_missing_strong_timing_proof")
        if supporting_booster_count < 1 and structural_count < 1:
            failed_reasons.append("timing_gate_missing_booster_or_structure")
        if confidence_score < 50:
            failed_reasons.append("timing_gate_confidence_below_50")
        if score < 40:
            failed_reasons.append("timing_gate_score_below_40")
    if not structure_gate:
        if structural_count < 2:
            failed_reasons.append("structure_gate_structural_count_below_2")
        if confidence_score < 50:
            failed_reasons.append("structure_gate_confidence_below_50")
        if score < 36:
            failed_reasons.append("structure_gate_score_below_36")

    if retrospective_event_forensic:
        branch = "retrospective_event_forensic_gate"
    elif timing_gate and strong_risk:
        branch = "timing_led_gate"
    elif structure_gate and strong_risk:
        branch = "structure_led_gate"
    elif strong_risk:
        branch = "legacy_unknown"
    else:
        branch = "not_strong_risk"
    exact_inputs = {
        "timing_led_gate": timing_gate,
        "structure_led_gate": structure_gate,
        "retrospective_event_forensic_gate": retrospective_event_forensic,
        "severity": severity,
        "score": score,
        "confidence_score": confidence_score,
    }
    return {
        "strongRiskExactGateBranch": branch,
        "strongRiskExactGatePassed": "Yes" if branch not in {"not_strong_risk", "legacy_unknown"} else "No",
        "strongRiskExactGateFailedReasons": "" if branch not in {"not_strong_risk", "legacy_unknown"} else "; ".join(_dedupe_text(failed_reasons)),
        "strongRiskExactGateInputs": json.dumps(exact_inputs, sort_keys=True),
        "strongRiskTimingGateInputs": json.dumps(timing_inputs, sort_keys=True),
        "strongRiskStructureGateInputs": json.dumps(structure_inputs, sort_keys=True),
        "strongRiskRetrospectiveGateInputs": json.dumps(retrospective_inputs, sort_keys=True),
    }


def _strong_risk_source_attribution_metrics(
    *,
    strong_risk: bool,
    gate_type: str,
    structural_sources: list[str],
    hard_sources: list[str],
    structural_count: int,
    no_hard_explanation: str,
) -> dict[str, str]:
    resolved_sources = _dedupe_text(structural_sources)
    hard_eligible = [
        source for source in resolved_sources if _strong_risk_hard_evidence_source_key(source)
    ]
    non_hard = [source for source in resolved_sources if source not in hard_eligible]
    if not strong_risk:
        issue = "none"
    elif gate_type == "legacy_unknown":
        issue = "legacy_unknown"
    elif gate_type in {"structure_led", "mixed_timing_structure"} and structural_count > 0 and not resolved_sources:
        issue = "inference_insufficient"
    elif not hard_sources and hard_eligible:
        issue = "hard_evidence_source_missing"
    elif not hard_sources and resolved_sources and not hard_eligible:
        issue = "structural_but_not_hard_evidence"
    else:
        issue = "none"
    missing = bool(issue in {"schema_propagation_gap", "hard_evidence_source_missing", "inference_insufficient"})
    structural_but_not_hard = bool(issue == "structural_but_not_hard_evidence")
    reason = no_hard_explanation
    if strong_risk and not hard_sources:
        if issue == "structural_but_not_hard_evidence":
            reason = "Strong Risk structural concerns are not Hard Evidence Review-eligible structural sources."
        elif not reason and issue == "hard_evidence_source_missing":
            reason = "A hard-evidence-eligible Strong Risk structural source was resolved but hardEvidenceSources is empty."
        elif not reason and issue == "legacy_unknown":
            reason = "Saved row lacks exact source fields."
    return {
        "strongRiskStructuralSourcesResolved": "; ".join(resolved_sources),
        "strongRiskHardEvidenceEligibleSources": "; ".join(_dedupe_text(hard_eligible)),
        "strongRiskNonHardStructuralSources": "; ".join(_dedupe_text(non_hard)),
        "strongRiskMissingSourceAttribution": "Yes" if missing else "No",
        "strongRiskSourceAttributionIssue": issue,
        "strongRiskNoHardEvidenceSourcesReason": reason,
        "strongRiskStructuralButNotHardEvidence": "Yes" if structural_but_not_hard else "No",
        "strongRiskStructuralButNotHardEvidenceSources": "; ".join(_dedupe_text(non_hard)),
        "strongRiskWhyNoHardEvidence": reason,
    }


def _strong_risk_hard_evidence_source_key(source: str) -> str:
    normalized = str(source or "").strip()
    if normalized in STRONG_RISK_HARD_EVIDENCE_ELIGIBLE_SOURCES:
        if normalized == "strict_shared_funding":
            return "strict_shared_funding_source"
        if normalized == "non_proxy_shared_funding":
            return "strict_shared_funding_source"
        return normalized
    return ""


def _strong_risk_timing_sources(raw: dict[str, object], flags: set[str]) -> list[str]:
    sources: list[str] = []
    if str(raw.get("beat_consensus_flag") or "").strip() == "Yes":
        sources.append("beat_local_consensus")
    if str(raw.get("favorable_repricing_flag") or "").strip() == "Yes":
        sources.append("rapid_favorable_repricing")
    entry_rank = _metric_int_like(raw.get("market_entry_rank"))
    if entry_rank and entry_rank <= 3:
        sources.append("early_meaningful_entry")
    if str(raw.get("off_hours_flag") or "").strip() == "Yes":
        sources.append("off_hours_local_entry")
    hours_to_resolution = _metric_float_like(raw.get("hours_to_resolution"))
    if hours_to_resolution is not None and hours_to_resolution <= 24.0:
        sources.append("hours_to_resolution_timing")
    if str(raw.get("decisive_timing_edge_flag") or "").strip() == "Yes" and not sources:
        sources.append("decisive_timing_edge")
    if "post_entry_repricing" in flags:
        sources.append("rapid_favorable_repricing")
    return _dedupe_text(sources)


def _strong_risk_supporting_boosters(raw: dict[str, object], flags: set[str]) -> list[str]:
    boosters: list[str] = []
    if str(raw.get("off_hours_flag") or "").strip() == "Yes":
        boosters.append("off_hours_local_entry")
    if str(raw.get("liquidity_shock_signal") or "").strip() == "Yes":
        boosters.append("liquidity_shock")
    if str(raw.get("coordinated_cluster_signal") or "").strip() == "Yes" or "coordinated_new_wallet_cluster" in flags:
        boosters.append("coordinated_cluster")
    return _dedupe_text(boosters)


def _strong_risk_structural_sources(raw: dict[str, object], flags: set[str]) -> list[str]:
    sources: list[str] = []
    hard_sources = _text_values(raw.get("hardEvidenceSources"))
    for source in hard_sources:
        if source and source != "suspicious_recent_funding":
            sources.append(source)
    if str(raw.get("split_wallet_pattern_flag") or "").strip() == "Yes":
        sources.append("split_wallet_pattern")
    if _strict_shared_funding_has_distinct_wallet_support(raw):
        sources.append("strict_shared_funding_source")
    if str(raw.get("reactivated_after_dormancy_flag") or "").strip() == "Yes":
        sources.append("dormant_wallet_reactivation")
    if str(raw.get("event_family_repeat_flag") or "").strip() == "Yes":
        sources.append("event_family_repeat")
    if str(raw.get("coordinated_sizing_cluster_flag") or "").strip() == "Yes":
        sources.append("coordinated_sizing")
    if _strict_shared_funding_has_distinct_wallet_support(raw):
        sources.append("non_proxy_shared_funding")
    if "domain_peer_outlier" in flags:
        sources.append("domain_peer_outlier")
    if "wallet_size_anomaly" in flags:
        sources.append("wallet_size_anomaly")
    return _dedupe_text(sources)


def _strict_shared_funding_has_distinct_wallet_support(raw: dict[str, object]) -> bool:
    if str(raw.get("shared_funding_source_flag") or "").strip() != "Yes":
        return False
    if str(raw.get("cex_proxy_cluster_flag") or "").strip() == "Yes":
        return False
    if not str(raw.get("funding_graph_key_strict") or "").strip():
        return False
    wallet_count = _metric_int_like(
        raw.get("shared_funding_source_wallet_count")
        or raw.get("sharedFundingSourceWalletCount")
        or raw.get("groupedCandidateWalletCount")
    )
    return wallet_count >= 2


def _strong_risk_suppressor_conflicts(
    raw: dict[str, object],
    flags: set[str],
    *,
    timing_sources: list[str],
    structural_sources: list[str],
) -> list[str]:
    conflicts = _suspicious_funding_suppressor_conflicts(raw, flags)
    repricing_quality = str(raw.get("repricingSourceQuality") or raw.get("repricing_source_quality") or "").strip()
    if (
        "rapid_favorable_repricing" in timing_sources
        and repricing_quality in {REPRICING_SOURCE_QUALITY_WEAK, REPRICING_SOURCE_QUALITY_MECHANICAL, "unknown"}
    ):
        conflicts.append(f"repricing_source_quality_{repricing_quality or 'unknown'}")
    funding_grade = _funding_evidence_grade_from_raw(raw)
    funding_sources = _text_values(raw.get("hardEvidenceSources")) + _text_values(raw.get("strongRiskStructuralSources"))
    if (
        "suspicious_recent_funding" in funding_sources
        and funding_grade == FUNDING_EVIDENCE_UNKNOWN
    ):
        conflicts.append("funding_unknown")
    if "domain_specialist" in conflicts and structural_sources:
        conflicts = [item for item in conflicts if item != "domain_specialist"]
    return _dedupe_text(conflicts)


def _refresh_strong_risk_attribution(case: FlaggedCase, *, retrospective_event_forensic: bool = False) -> None:
    case.raw_metrics.update(
        _strong_risk_attribution_metrics(
            severity=case.severity,
            score=case.suspicion_score,
            confidence_score=case.confidence_score,
            raw_metrics=case.raw_metrics,
            flags=case.flags,
            retrospective_event_forensic=retrospective_event_forensic,
        )
    )


def _review_priority_for_case(severity: str, case_type: str | None, score: int) -> str:
    if case_type == "Resolution Gap":
        return "Low"
    if severity == "Strong Risk":
        return "High"
    if severity == "Worth a Look":
        return "Medium" if score >= 45 else "Low"
    return "Low"


def _verdict_for_case(severity: str, case_type: str | None) -> str:
    if case_type == "Resolution Gap":
        return "Looks more like public-news lag or stale market pricing than private-information trading."
    if severity == "Strong Risk":
        return "Multiple high-signal markers align."
    if severity == "Worth a Look":
        return "Needs manual review."
    return "Likely benign or weakly suspicious."


def _annotate_shared_funding_links(cases: list[FlaggedCase]) -> None:
    grouped: dict[str, list[FlaggedCase]] = {}
    for case in cases:
        if _candidate_admission_rejected(case.raw_metrics):
            continue
        key = (
            case.raw_metrics.get("funding_graph_key_strict", "")
            or case.raw_metrics.get("funding_graph_key_proxy", "")
            or case.raw_metrics.get("funding_graph_key", "")
        )
        if key:
            grouped.setdefault(key, []).append(case)

    for key, linked_cases in grouped.items():
        if len(linked_cases) < 2:
            continue
        proxy_cluster = all(_is_proxy_funding_case(case) for case in linked_cases)
        if proxy_cluster:
            _mark_proxy_funding_cluster(linked_cases)
            for tight_group in _proxy_tight_cohort_groups(linked_cases):
                _apply_shared_funding_group(tight_group, proxy_cluster=True)
                _annotate_split_wallet_patterns(tight_group)
            continue

        _apply_shared_funding_group(linked_cases, proxy_cluster=False)
        _annotate_split_wallet_patterns(linked_cases)


def _is_proxy_funding_case(case: FlaggedCase) -> bool:
    raw = case.raw_metrics
    if str(raw.get("funding_graph_key_strict") or "").strip():
        return False
    return bool(str(raw.get("funding_graph_key_proxy") or "").strip() or _has_proxy_funding_grade(raw))


def _mark_proxy_funding_cluster(linked_cases: list[FlaggedCase]) -> None:
    cluster_size = len(linked_cases)
    for case in linked_cases:
        raw = case.raw_metrics
        raw["funding_proxy_cluster_flag"] = "Yes"
        raw["funding_proxy_cluster_size"] = str(max(_metric_int_like(raw.get("funding_proxy_cluster_size")), cluster_size))
        raw["cex_proxy_cluster_flag"] = "Yes"
        raw["cex_proxy_cluster_size"] = str(max(_metric_int_like(raw.get("cex_proxy_cluster_size")), cluster_size))
        if "cex_proxy_cluster" not in case.flags:
            case.flags.append("cex_proxy_cluster")


def _proxy_tight_cohort_groups(linked_cases: list[FlaggedCase]) -> list[list[FlaggedCase]]:
    grouped: dict[tuple[str, str, str], list[FlaggedCase]] = {}
    for case in linked_cases:
        raw = case.raw_metrics
        if raw.get("opening_exposure_flag") != "Yes":
            continue
        direction = _cluster_direction_for_case(case)
        fingerprint = str(raw.get("funding_fingerprint") or raw.get("funding_graph_key_proxy") or "").strip()
        if not direction or not fingerprint:
            continue
        grouped.setdefault((case.trade.condition_id, direction, fingerprint), []).append(case)

    result: list[list[FlaggedCase]] = []
    for group in grouped.values():
        if len({case.trade.wallet for case in group}) < 2:
            continue
        ordered = sorted(group, key=lambda item: _trade_sort_key(item.trade))
        time_span_minutes = (
            (ordered[-1].trade.timestamp - ordered[0].trade.timestamp).total_seconds() / 60.0
            if len(ordered) > 1
            else 0.0
        )
        if time_span_minutes <= SPLIT_WALLET_WINDOW_MINUTES:
            result.append(ordered)
    return result


def _apply_shared_funding_group(linked_cases: list[FlaggedCase], *, proxy_cluster: bool) -> None:
    cluster_size = len(linked_cases)
    wallet_count = len({case.trade.wallet for case in linked_cases})
    bonus = 4 if cluster_size >= 3 else 2
    for case in linked_cases:
        raw = case.raw_metrics
        raw["shared_funding_source_flag"] = "Yes"
        raw["shared_funding_source_cluster_size"] = str(
            max(_metric_int_like(raw.get("shared_funding_source_cluster_size")), cluster_size)
        )
        raw["shared_funding_source_wallet_count"] = str(
            max(_metric_int_like(raw.get("shared_funding_source_wallet_count")), wallet_count)
        )
        raw["sharedFundingSourceWalletCount"] = raw["shared_funding_source_wallet_count"]
        if proxy_cluster:
            raw["funding_proxy_tight_cohort_flag"] = "Yes"
            raw["funding_proxy_tight_cohort_size"] = str(
                max(_metric_int_like(raw.get("funding_proxy_tight_cohort_size")), cluster_size)
            )
        if "shared_funding_source" not in case.flags:
            case.flags.append("shared_funding_source")
        message = (
            f"{cluster_size} candidate wallets appear to share the same upstream funding route or intermediary."
        )
        if proxy_cluster:
            message = (
                f"{cluster_size} candidate wallets share an exchange/bridge funding fingerprint while entering "
                "the same market side in a tight time band."
            )
        if message not in case.explanation:
            case.explanation.append(message)
        if case.case_type == "Resolution Gap" or raw.get("hard_public_information_flag") == "Yes":
            continue
        case.suspicion_score = min(100, case.suspicion_score + bonus)
        case.raw_metrics["funding_link_bonus_applied"] = str(bonus)
        _refresh_case_classification(case)


def _annotate_domain_peer_history(
    cases: list[FlaggedCase],
    wallet_cache: dict[str, tuple[WalletInspection, list[Trade], WalletPerformance]],
) -> None:
    peers_by_domain: dict[str, list[tuple[str, float]]] = {}
    for wallet, cached in wallet_cache.items():
        inspection, _wallet_trades, performance = cached
        closed_summary = performance.closed_summary
        if closed_summary.economic_sample_size <= 0:
            continue
        peers_by_domain.setdefault(inspection.dominant_domain_label, []).append(
            (wallet, closed_summary.economic_win_rate_value)
        )

    for case in cases:
        domain = case.raw_metrics.get("domain_specialist_label", "Other")
        peers = peers_by_domain.get(domain, [])
        if len(peers) < 2:
            case.raw_metrics.setdefault("wallet_domain_peer_percentile", "Unavailable")
            continue
        wallet = case.trade.wallet
        own_value = next((value for peer_wallet, value in peers if peer_wallet == wallet), None)
        if own_value is None:
            case.raw_metrics["wallet_domain_peer_percentile"] = "Unavailable"
            continue
        percentile = _percentile_rank(own_value, sorted(value for _peer_wallet, value in peers))
        case.raw_metrics["wallet_domain_peer_percentile"] = f"{percentile:.1f}"


def _structural_concern_snapshot(*, flags: list[str], raw_metrics: dict[str, str]) -> tuple[int, str]:
    count = 0
    if raw_metrics.get("suspicious_funding_flag") == "Yes":
        count += 1
    if raw_metrics.get("shared_funding_source_flag") == "Yes":
        count += 1
    if raw_metrics.get("split_wallet_pattern_flag") == "Yes":
        count += 1
    if raw_metrics.get("cex_proxy_cluster_flag") == "Yes" and raw_metrics.get("funding_proxy_tight_cohort_flag") == "Yes":
        count += 1
    if raw_metrics.get("coordinated_sizing_cluster_flag") == "Yes" or raw_metrics.get("coordinated_cluster_signal") == "Yes":
        count += 1
    if "domain_peer_outlier" in flags:
        count += 1
    if raw_metrics.get("event_family_repeat_flag") == "Yes":
        count += 1
    if raw_metrics.get("reactivated_after_dormancy_flag") == "Yes":
        count += 1
    if "wallet_size_anomaly" in flags:
        count += 1
    try:
        if float(raw_metrics.get("wallet_market_conviction_ratio", "0") or 0) >= 0.85:
            count += 1
    except (TypeError, ValueError):
        pass

    if count >= 4:
        return count, "High"
    if count >= 2:
        return count, "Elevated"
    if count >= 1:
        return count, "Present"
    return 0, "None"


def _refresh_case_classification(case: FlaggedCase) -> None:
    raw = case.raw_metrics
    case.case_type = raw.get("case_type") or ("Resolution Gap" if raw.get("hard_public_information_flag") == "Yes" else None)
    structural_count, structural_tier = _structural_concern_snapshot(flags=case.flags, raw_metrics=raw)
    raw["structural_concern_count"] = str(structural_count)
    raw["structural_concern_tier"] = structural_tier
    raw["structural_concern_flag"] = "Yes" if structural_count >= 1 else "No"
    case.severity = _severity_from_score(
        case.suspicion_score,
        case.confidence_score,
        opening_exposure_flag=raw.get("opening_exposure_flag") == "Yes" or raw.get("trade_state") == "increase",
        materially_uncertain=raw.get("materially_uncertain_flag") == "Yes",
        decisive_timing_edge=raw.get("decisive_timing_edge_flag") == "Yes",
        strong_timing_proof_count=int(raw.get("strong_timing_proof_count", "0") or 0),
        supporting_booster_count=int(raw.get("supporting_booster_count", "0") or 0),
        structural_concern_count=structural_count,
        benign_pattern=raw.get("benign_pattern_flag") == "Yes",
        credibility_gamed=raw.get("credibility_gamed_flag") == "Yes",
        hard_resolution_gap_flag=raw.get("hard_public_information_flag") == "Yes" or raw.get("hard_resolution_gap_flag") == "Yes",
        soft_resolution_gap_flag=raw.get("soft_resolution_gap_flag") == "Yes",
    )
    case.review_priority = _review_priority_for_case(case.severity, case.case_type, case.suspicion_score)
    case.verdict = _verdict_for_case(case.severity, case.case_type)
    case.latest_suspicion_score = case.suspicion_score
    case.latest_severity = case.severity
    _refresh_strong_risk_attribution(case)


def _trade_sort_key(trade: Trade) -> tuple[datetime, str]:
    return trade.timestamp, trade.trade_id


def _wallet_activity_gap_days(wallet_history_trades: list[Trade], trade: Trade) -> tuple[float | None, float | None]:
    prior_trade: Trade | None = None
    next_trade: Trade | None = None
    trade_key = _trade_sort_key(trade)
    for item in sorted(wallet_history_trades, key=_trade_sort_key):
        if item.trade_id == trade.trade_id:
            continue
        item_key = _trade_sort_key(item)
        if item_key < trade_key:
            prior_trade = item
            continue
        if item_key > trade_key:
            next_trade = item
            break

    prior_gap_days = None
    if prior_trade is not None:
        prior_gap_days = max((trade.timestamp - prior_trade.timestamp).total_seconds() / 86400.0, 0.0)

    observed_post_gap_days = None
    observed_until = next_trade.timestamp if next_trade is not None else datetime.now(UTC)
    if observed_until > trade.timestamp:
        observed_post_gap_days = max((observed_until - trade.timestamp).total_seconds() / 86400.0, 0.0)

    return prior_gap_days, observed_post_gap_days


def _event_family_key(trade: Trade, market: Market | None = None) -> str:
    candidates = [trade.event_slug, trade.slug, market.slug if market is not None else "", trade.title]
    for candidate in candidates:
        text = str(candidate or "").strip().lower()
        if not text:
            continue
        normalized = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        normalized = re.sub(r"-\d+$", "", normalized)
        while True:
            updated = EVENT_FAMILY_DATE_SUFFIX_RE.sub("", normalized)
            updated = EVENT_FAMILY_YEAR_SUFFIX_RE.sub("", updated).strip("-")
            if updated == normalized:
                break
            normalized = updated
        if normalized:
            return normalized
    return ""


def _event_family_stats(
    wallet_history_trades: list[Trade],
    trade: Trade,
    family_key: str,
) -> tuple[int, int, float]:
    if not family_key:
        return 0, 0, 0.0

    trade_key = _trade_sort_key(trade)
    prior_family_trades = 0
    prior_family_markets: set[str] = set()
    family_trade_count = 1
    visible_history_count = 1

    for item in wallet_history_trades:
        if item.trade_id == trade.trade_id:
            continue
        visible_history_count += 1
        if _event_family_key(item) != family_key:
            continue
        family_trade_count += 1
        if _trade_sort_key(item) < trade_key:
            prior_family_trades += 1
            prior_family_markets.add(item.condition_id)

    family_share = family_trade_count / max(1, visible_history_count)
    return prior_family_trades, len(prior_family_markets), family_share


def _annotate_split_wallet_patterns(linked_cases: list[FlaggedCase]) -> None:
    for group in _shared_funding_split_groups(linked_cases):
        bonus = 5 if len(group) >= 3 else 3
        for case in group:
            case.raw_metrics["split_wallet_pattern_flag"] = "Yes"
            case.raw_metrics["split_wallet_pattern_cluster_size"] = str(len(group))
            if "split_wallet_pattern" not in case.flags:
                case.flags.append("split_wallet_pattern")
            message = (
                f"{len(group)} linked wallets entered the same side of this market from the same funding route "
                "in a narrow price and time band."
            )
            if message not in case.explanation:
                case.explanation.append(message)
            if case.case_type == "Resolution Gap" or case.raw_metrics.get("hard_public_information_flag") == "Yes":
                continue
            case.suspicion_score = min(100, case.suspicion_score + bonus)
            case.raw_metrics["split_wallet_bonus_applied"] = str(bonus)
            _refresh_case_classification(case)


def _shared_funding_split_groups(linked_cases: list[FlaggedCase]) -> list[list[FlaggedCase]]:
    grouped: dict[tuple[str, str], list[FlaggedCase]] = {}
    for case in linked_cases:
        if case.raw_metrics.get("opening_exposure_flag") != "Yes":
            continue
        direction = _cluster_direction_for_case(case)
        if not direction:
            continue
        key = (case.trade.condition_id, direction)
        grouped.setdefault(key, []).append(case)

    result: list[list[FlaggedCase]] = []
    for cases in grouped.values():
        wallets = {case.trade.wallet for case in cases}
        if len(wallets) < 2:
            continue
        ordered = sorted(cases, key=lambda item: _trade_sort_key(item.trade))
        time_span_minutes = (
            (ordered[-1].trade.timestamp - ordered[0].trade.timestamp).total_seconds() / 60.0
            if len(ordered) > 1
            else 0.0
        )
        prices = [case.trade.price for case in ordered]
        price_band = max(prices) - min(prices) if prices else Decimal("0")
        if (
            time_span_minutes <= 60.0
            and price_band <= SPLIT_WALLET_PRICE_BAND
        ):
            result.append(ordered)
    return result


def _annotate_coordinated_sizing_clusters(cases: list[FlaggedCase]) -> None:
    grouped: dict[tuple[str, str], list[FlaggedCase]] = {}
    for case in cases:
        if case.raw_metrics.get("opening_exposure_flag") != "Yes":
            continue
        direction = _cluster_direction_for_case(case)
        if not direction:
            continue
        key = (case.trade.condition_id, direction)
        grouped.setdefault(key, []).append(case)

    for grouped_cases in grouped.values():
        ordered = sorted(grouped_cases, key=lambda item: _trade_sort_key(item.trade))
        left = 0
        for right, case in enumerate(ordered):
            while left < right and (case.trade.timestamp - ordered[left].trade.timestamp).total_seconds() > 30 * 60:
                left += 1
            window = ordered[left : right + 1]
            wallets = {item.trade.wallet for item in window}
            if len(wallets) < 3:
                continue
            sizes = [float(item.trade.notional) for item in window if item.trade.notional > 0]
            if len(sizes) < 3:
                continue
            avg_size = sum(sizes) / len(sizes)
            if avg_size <= 0:
                continue
            size_variance = max(abs(size - avg_size) / avg_size for size in sizes)
            if size_variance > 0.30:
                continue
            same_side_share = Decimal("0")
            for item in window:
                try:
                    share_value = Decimal(str(item.raw_metrics.get("same_side_share_30m", "0")).replace("%", "") or "0")
                except Exception:
                    share_value = Decimal("0")
                if share_value > same_side_share:
                    same_side_share = share_value
            if same_side_share < Decimal("40"):
                continue
            cluster_size = len(wallets)
            bonus = 4 if cluster_size >= 3 else 2
            for item in window:
                item.raw_metrics["coordinated_sizing_cluster_flag"] = "Yes"
                item.raw_metrics["coordinated_sizing_cluster_size"] = str(cluster_size)
                if "coordinated_sizing_cluster" not in item.flags:
                    item.flags.append("coordinated_sizing_cluster")
                if item.case_type == "Resolution Gap" or item.raw_metrics.get("hard_public_information_flag") == "Yes":
                    continue
                item.suspicion_score = min(100, item.suspicion_score + bonus)
                _refresh_case_classification(item)


def _fmt_decimal(value: Decimal | int | float) -> str:
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return f"{value.quantize(Decimal('0.01'))}"


def _to_markdown(report: dict[str, object]) -> str:
    diagnostics = report.get("trade_collection_diagnostics") or {}
    lines = [
        "# InsPoly Scan Report",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Lookback: {report['lookback']}",
        f"- API-loaded recent trade rows: {report['raw_trade_count']}",
        f"- Focus-category trades after filter: {report['filtered_trade_count']}",
        f"- Candidate trades after size pre-filter: {report['candidate_trade_count']}",
        f"- Flagged cases: {report['flagged_case_count']}",
        "",
    ]
    if diagnostics:
        lines.extend(
            [
                "## Trade collection coverage",
                "",
                f"- Count meaning: {diagnostics.get('rawTradeCountMeaning', 'Unknown')}",
                f"- Focus market scope: {diagnostics.get('focusMarketScope', 'Unknown')}",
                f"- Market fetch mode: {diagnostics.get('marketFetchMode', 'Unknown')}",
                f"- Focus markets: {diagnostics.get('focusMarketCount', 'Unknown')}",
                f"- Non-empty markets loaded: {diagnostics.get('nonEmptyMarketCount', 'Unknown')}",
                f"- Per-market row cap: {diagnostics.get('perMarketRowCap', 'Unknown')}",
                f"- Possible truncated markets: {diagnostics.get('possibleTruncatedMarketCount', 0)}",
                f"- Failed market fetches: {diagnostics.get('failedMarketFetchCount', 0)}",
                f"- Coverage warning: {diagnostics.get('coverageWarning', '')}",
                f"- Partial collection warning: {diagnostics.get('partialCollectionWarning', '')}",
                "",
            ]
        )
    settings = report.get("analysis_settings") or {}
    if settings:
        lines.extend(
            [
                "## Runtime settings",
                "",
                f"- Include blockchain linkage: {settings.get('include_blockchain', 'Unknown')}",
                f"- Funding trace mode: {settings.get('funding_trace_mode', 'Unknown')}",
                f"- Include related case-family markets: {settings.get('include_related_markets', 'Unknown')}",
                f"- Case-family scope status: {settings.get('case_family_scope_status', 'Unknown')}",
                f"- Case-family note: {settings.get('case_family_scope_note', '')}",
                "",
            ]
        )
    funding_lines = _funding_availability_report_lines(report.get("funding_resolver_health"))
    if funding_lines:
        lines.extend(["## Funding availability", ""])
        lines.extend(funding_lines)
        lines.append("")
    for case in report["cases"]:
        trade = case["trade"]
        data_coverage = case["confidence_score"]
        lines.extend(
            [
                f"## [{case['severity']}] {trade['wallet']} on {trade['title']}",
                "",
                f"- Market: {trade['title']}",
                f"- Wallet: {trade['wallet']}",
                f"- Time: {trade['timestamp']}",
                f"- Position: {trade['side']} {trade['outcome']}",
                f"- Token price: {case['raw_metrics'].get('raw_token_price_label', case['raw_metrics'].get('price_implied_probability', 'Unavailable'))}",
                f"- Economic probability: {case['raw_metrics'].get('economic_side_probability_label', 'Unavailable')}",
                f"- Trade size: ${case['raw_metrics']['trade_notional_usdc']}",
                f"- Trade state: {case['raw_metrics'].get('trade_state', 'Unavailable')}",
                f"- Capital at risk: ${case['raw_metrics'].get('capital_at_risk_usdc', '0')}",
                f"- Overall assessment: {case['severity']}",
                f"- Case type: {case.get('case_type') or 'Standard risk case'}",
                "- What stands out:",
            ]
        )
        for reason in case["explanation"]:
            lines.append(f"  - {reason}")
        if case["reasons_against"]:
            lines.append("- What reduces concern:")
            for reason in case["reasons_against"]:
                lines.append(f"  - {reason}")
        if data_coverage < 95:
            lines.append(f"- Data coverage: {data_coverage}/100")
        lines.append("")
    return "\n".join(lines)


def _to_text_report(report: dict[str, object]) -> str:
    diagnostics = report.get("trade_collection_diagnostics") or {}
    lines = [
        "InsPoly quick analysis",
        f"Generated at: {report['generated_at']}",
        f"Lookback: {report['lookback']}",
        f"Category scope: {report['topic_scope']}",
        f"API-loaded recent trade rows: {report['raw_trade_count']}",
        f"Focus-category trades after filter: {report['filtered_trade_count']}",
        f"Candidate trades after size pre-filter: {report['candidate_trade_count']}",
        f"Flagged cases: {report['flagged_case_count']}",
        "",
    ]
    if diagnostics:
        lines.extend(
            [
                "Trade collection coverage:",
                f"- Count meaning: {diagnostics.get('rawTradeCountMeaning', 'Unknown')}",
                f"- Focus market scope: {diagnostics.get('focusMarketScope', 'Unknown')}",
                f"- Market fetch mode: {diagnostics.get('marketFetchMode', 'Unknown')}",
                f"- Focus markets: {diagnostics.get('focusMarketCount', 'Unknown')}",
                f"- Non-empty markets loaded: {diagnostics.get('nonEmptyMarketCount', 'Unknown')}",
                f"- Per-market row cap: {diagnostics.get('perMarketRowCap', 'Unknown')}",
                f"- Possible truncated markets: {diagnostics.get('possibleTruncatedMarketCount', 0)}",
                f"- Failed market fetches: {diagnostics.get('failedMarketFetchCount', 0)}",
                f"- Coverage warning: {diagnostics.get('coverageWarning', '')}",
                f"- Partial collection warning: {diagnostics.get('partialCollectionWarning', '')}",
                "",
            ]
        )
    settings = report.get("analysis_settings") or {}
    if settings:
        lines.extend(
            [
                "Runtime settings:",
                f"- Include blockchain linkage: {settings.get('include_blockchain', 'Unknown')}",
                f"- Funding trace mode: {settings.get('funding_trace_mode', 'Unknown')}",
                f"- Include related case-family markets: {settings.get('include_related_markets', 'Unknown')}",
                f"- Case-family scope status: {settings.get('case_family_scope_status', 'Unknown')}",
                f"- Case-family note: {settings.get('case_family_scope_note', '')}",
                "",
            ]
        )
    funding_lines = _funding_availability_report_lines(report.get("funding_resolver_health"))
    if funding_lines:
        lines.extend(["Funding availability:"])
        lines.extend(funding_lines)
        lines.append("")
    for case in report["cases"]:
        trade = case["trade"]
        wallet = case["wallet_inspection"]
        username = _report_username(trade)
        lines.extend(
            [
                f"Market: {trade['title']}",
                f"Wallet: {trade['wallet']}",
                f"Username: {username}",
                "Key context:",
                f"- Trade time: {trade['timestamp']}",
                f"- Position: {trade['side']} {trade['outcome']}",
                f"- Token price: {case['raw_metrics'].get('raw_token_price_label', case['raw_metrics'].get('price_implied_probability', 'Unavailable'))}",
                f"- Economic probability: {case['raw_metrics'].get('economic_side_probability_label', 'Unavailable')}",
                f"- Trade size: ${case['raw_metrics']['trade_notional_usdc']}",
                f"- Trade state: {case['raw_metrics'].get('trade_state', 'Unavailable')}",
                f"- Capital at risk: ${case['raw_metrics'].get('capital_at_risk_usdc', '0')}",
                f"- Categories: {case['raw_metrics'].get('site_categories', 'Uncategorized')}",
                f"- Market size percentile: {case['raw_metrics'].get('market_size_percentile', 'n/a')}",
                f"- Wallet size multiple vs median: {_wallet_size_text(case)}",
                f"- Trade domain: {case['raw_metrics'].get('trade_domain', 'Other')}",
                f"- Domain peer percentile: {case['raw_metrics'].get('domain_peer_percentile', 'Unavailable')}",
                f"- Wallet domain peer percentile: {case['raw_metrics'].get('wallet_domain_peer_percentile', 'Unavailable')}",
                f"- Entry vs local consensus: {case['raw_metrics'].get('entry_vs_consensus_15m', 'Unavailable')}",
                f"- Favorable move after entry (1h): {case['raw_metrics'].get('favorable_move_1h', '0')}",
                f"- Local event time: {case['raw_metrics'].get('local_event_time', 'Unavailable')}",
                f"- Off-hours flag: {case['raw_metrics'].get('off_hours_flag', 'No')}",
                f"- Funding source: {case['raw_metrics'].get('funding_source_label', 'Unknown')}",
                f"- Funding velocity: {case['raw_metrics'].get('funding_velocity_label', 'Unavailable')}",
                f"- Dominant wallet domain: {case['raw_metrics'].get('domain_specialist_label', 'Other')}",
                f"- Economic win rate: {case['raw_metrics'].get('wallet_economic_win_rate', 'Unavailable')}",
                f"- Zombie or de facto losses: {case['raw_metrics'].get('zombie_loss_count', '0')}",
                f"- Bot-likeness score: {case['raw_metrics'].get('bot_likeness_score', '0')}",
                "",
                f"Overall assessment: {case['severity']}",
                f"Case type: {case.get('case_type') or 'Standard risk case'}",
                "What stands out:",
            ]
        )
        for reason in case["explanation"]:
            lines.append(f"- {reason}")
        if case["reasons_against"]:
            lines.append("What reduces concern:")
            for reason in case["reasons_against"]:
                lines.append(f"- {reason}")
        else:
            lines.append("What reduces concern:")
            lines.append("- No strong benign pattern was visible in the loaded data.")
        lines.extend(
            [
                "Bottom line:",
                _bottom_line_text(case["severity"], case.get("case_type")),
                "How system interpreted this case:",
                _system_interpretation_text(case),
                "Wallet snapshot:",
                f"- Visible loaded Polymarket trade count: {wallet.get('recent_trade_count', 'n/a')}",
                f"- Visible loaded unique markets: {wallet.get('unique_market_count', 'n/a')}",
                f"- Focus-category market count: {wallet.get('focus_market_count', 'n/a')}",
                f"- Dominant domain: {wallet.get('dominant_domain_label', 'Other')}",
                f"- Domain concentration: {wallet.get('domain_concentration_score', 0):.2f}",
                f"- First visible trade: {wallet.get('first_trade_at') or 'Not available'}",
                f"- Last visible trade: {wallet.get('last_trade_at') or 'Not available'}",
                "Recent closed positions:",
                f"- Formal closed win rate: {case['raw_metrics'].get('wallet_closed_win_rate', 'Unavailable')}",
                f"- Economic win rate: {case['raw_metrics'].get('wallet_economic_win_rate', 'Unavailable')}",
                f"- Zombie losses in loaded sample: {case['raw_metrics'].get('zombie_loss_count', '0')}",
                "Lifetime position statistics:",
                f"- Polygon nonce: {wallet.get('polygon_nonce', 'Not available')}",
                f"- Traded market count: {wallet.get('traded_market_count', 'Not available')}",
            ]
        )
        if case["confidence_score"] < 95:
            lines.append(f"Data coverage: {case['confidence_score']}/100")
        lines.append("")
    if not report["cases"]:
        lines.append("No flagged cases in this run.")
    return "\n".join(lines)


def _bottom_line_text(severity: str, case_type: str | None = None) -> str:
    if case_type == "Resolution Gap":
        return "This looks more like public information that the market priced slowly than like insider-style information."
    if severity == "Strong Risk":
        return "Several important signals point in the same direction, so this case deserves close manual review."
    if severity == "Worth a Look":
        return "The trade is unusual enough to justify a closer look, but the current evidence is mixed."
    return "Some elements stand out, but the loaded evidence leans closer to ordinary trading than to a strong risk signal."


def _report_username(trade: dict[str, object]) -> str:
    trader_name = str(trade.get("trader_name", "") or "").strip()
    pseudonym = str(trade.get("trader_pseudonym", "") or "").strip()
    if trader_name and pseudonym and trader_name != pseudonym:
        return f"{trader_name} ({pseudonym})"
    if trader_name:
        return trader_name
    if pseudonym:
        return pseudonym
    return "Not available"


def _wallet_size_text(case: dict[str, object]) -> str:
    value = case["raw_metrics"].get("wallet_size_multiple_vs_median", "Unavailable")
    if value == "Unavailable":
        return "Unavailable because the wallet comparison sample was too small"
    return f"{value}x"


def _system_interpretation_text(case: dict[str, object]) -> str:
    subscores = case["subscores"]
    raw_metrics = case["raw_metrics"]
    parts: list[str] = []
    trade_state = raw_metrics.get("trade_state", "Unavailable")
    if trade_state == "increase":
        parts.append("The system treated this as a fresh exposure increase rather than a clean close.")
    elif trade_state in {"reduce", "close", "roll"}:
        parts.append("The system treated this more like inventory reduction than a fresh opening bet.")
    else:
        parts.append("The system could not cleanly confirm that this trade opened fresh exposure.")
    timing_points = int(subscores.get("timing", 0) or 0)
    post_trade_points = int(subscores.get("post_trade", 0) or 0)
    if timing_points > 0:
        parts.append("Timing mattered because the trade arrived relatively close to resolution.")
    elif post_trade_points > 0:
        parts.append("The entry was not especially close to formal resolution, but later repricing still supports a timing edge.")
    else:
        parts.append("Timing did not materially raise concern.")
    if subscores.get("size", 0):
        parts.append("Size mattered because the trade stood out against this market, this wallet, or both.")
    if subscores.get("market_state", 0):
        parts.append("Market-state logic raised concern because the trade entered while uncertainty still remained or because the entry price implied strong asymmetry.")
    if subscores.get("wallet_novelty", 0):
        parts.append("Wallet history added concern because the wallet looks limited in the loaded dataset.")
    if raw_metrics.get("off_hours_flag") == "Yes":
        parts.append("The trade also landed during the event's local off-hours window.")
    if raw_metrics.get("suspicious_funding_flag") == "Yes":
        quality = str(raw_metrics.get("suspiciousFundingQuality") or "").strip()
        if quality:
            parts.append(f"Suspicious funding quality was classified as {quality}.")
        else:
            parts.append("Fresh funding from an opaque source added structural concern.")
    if raw_metrics.get("shared_funding_source_flag") == "Yes":
        parts.append("Multiple flagged wallets in the run appear to share the same upstream funding source or intermediary.")
    if subscores.get("cluster", 0):
        parts.append("Nearby same-side activity from other wallets was visible, but this remains a crowding clue unless stronger linkage is confirmed.")
    if post_trade_points > 0:
        parts.append("Post-trade repricing strengthened the case because the market moved in the trade's favor after entry.")
    if subscores.get("benign_discount", 0) < 0:
        parts.append("Established-wallet or gradual-build signals reduced the final concern level.")
    if raw_metrics.get("domain_peer_percentile") not in {"", "Unavailable"}:
        parts.append(
            f"Relative to same-domain peers, this trade ranked around the {raw_metrics.get('domain_peer_percentile')}th percentile for size."
        )
    if raw_metrics.get("specialist_explained_flag") == "Yes":
        parts.append("The pattern may be explained by repeat specialist behavior in this market type.")
    if raw_metrics.get("public_knowledge_at"):
        parts.append("Offline timeline data suggests the event may already have been publicly knowable by this point.")
    if raw_metrics.get("formal_win_rate_may_be_overstated") == "Yes":
        parts.append("The wallet’s formal win rate may be overstated because several economically dead positions were never redeemed.")
    if raw_metrics.get("low_analyst_value_flag") == "Yes":
        parts.append("The wallet looks highly automated and low-value for manual insider-style review.")
    if raw_metrics.get("win_rate_adjustment_note"):
        parts.append(str(raw_metrics["win_rate_adjustment_note"]))
    elif raw_metrics.get("win_rate_relevance_note"):
        parts.append(str(raw_metrics["win_rate_relevance_note"]))
    if raw_metrics.get("economic_history_note"):
        parts.append(str(raw_metrics["economic_history_note"]))
    if raw_metrics.get("bot_activity_note"):
        parts.append(str(raw_metrics["bot_activity_note"]))
    return " ".join(parts)
