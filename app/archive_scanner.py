from __future__ import annotations

import csv
import json
from collections.abc import Callable
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.config import (
    FUNDING_TRACE_MODE_DISABLED,
    AppConfig,
    funding_trace_mode as runtime_funding_trace_mode,
    normalize_funding_trace_mode,
    validation_cache_only_mode,
)
from app.event_context import EventContextResolver
from app.funding_context import FundingContext, FundingResolver, unknown_funding_context
from app.report_pointer import attach_indexer_warehouse_pointer
from app.models import FlaggedCase, Market, Trade
from app.polymarket import PolymarketClient
from app.side_outcome import normalize_cluster_direction, normalize_side_outcome
from app.scanner import (
    ProgressEvent,
    HARD_EVIDENCE_REVIEW_TIER,
    STRONG_RISK_ATTRIBUTION_FIELDS,
    _annotate_hard_evidence_review,
    _annotate_domain_peer_history,
    _annotate_preclassification_linkage,
    _apply_candidate_admission_metadata,
    _build_wallet_inspection,
    _build_candidate_trade_set,
    _build_structural_pre_admission_funnel,
    _build_structural_pre_admission_metadata,
    _case_survives_output_threshold,
    _case_has_hard_evidence_review,
    _capital_at_risk_usdc,
    _classify_execution_state,
    _domain_for_trade,
    _emit_progress,
    _funding_cache_key,
    _funding_availability_report_lines,
    _group_domain_trades,
    _group_market_trades,
    _group_wallet_trades,
    _is_opening_exposure,
    _looks_like_deadline_market,
    _score_trade,
    _should_trace_funding,
    _candidate_admission_near_miss_records,
    _finalize_structural_pre_admission_funnel,
    _structural_pre_admission_prefunding_pool,
    _structural_pre_admission_funnel_markdown,
    _stop_requested,
    _validate_candidate_admissions,
    _wallet_activity_gap_days,
    _wallet_market_conviction_ratio,
)
from app.site_categories import SiteCategory
from app.storage import Storage
from app.wallet_analytics import (
    WalletPerformance,
    compute_wallet_performance,
    compute_wallet_statistical_prior,
    win_rate_relevance_note,
)

ARCHIVE_EVENT_LOOKAHEAD_DAYS = 7


class ArchiveResearchScanner:
    def __init__(self, client: PolymarketClient, storage: Storage, config: AppConfig) -> None:
        self._client = client
        self._storage = storage
        self._config = config
        self._event_context_resolver = EventContextResolver(
            self._config.data_dir,
            AppConfig.load().data_dir,
        )
        self._funding_resolver = FundingResolver()

    def scan(
        self,
        start_at: datetime,
        end_at: datetime,
        reports_dir: Path,
        *,
        selected_categories: tuple[SiteCategory, ...],
        min_notional: Decimal | None = None,
        max_notional: Decimal | None = None,
        include_blockchain: bool = True,
        funding_trace_mode: str | None = None,
        include_related_markets: bool = True,
        indexer_warehouse_pointer: dict[str, object] | None = None,
        progress_callback: callable | None = None,
        stop_event: object | None = None,
    ) -> dict[str, object]:
        if end_at <= start_at:
            raise ValueError("End datetime must be later than start datetime.")

        started_at = datetime.now(UTC)
        effective_funding_trace_mode = normalize_funding_trace_mode(
            funding_trace_mode,
            default=runtime_funding_trace_mode(),
        )
        if not include_blockchain:
            effective_funding_trace_mode = FUNDING_TRACE_MODE_DISABLED
        self._funding_resolver = FundingResolver(trace_mode=effective_funding_trace_mode)
        _emit_progress(progress_callback, 4, "Preparing", "Loading Polymarket site categories")
        focus_markets = self._load_archive_focus_markets(selected_categories, start_at, end_at)
        _emit_progress(
            progress_callback,
            12,
            "Preparing",
            f"Loaded {len(focus_markets)} markets from selected site categories",
        )

        interval_hours = max((end_at - start_at).total_seconds() / 3600, 0.0)
        recent_trades: list[Trade] = []
        focus_market_ids = list(focus_markets)
        total_chunks = max(1, len(focus_market_ids))
        truncated_market_count = 0
        for index, condition_id in enumerate(focus_market_ids, start=1):
            if _stop_requested(stop_event):
                break
            market_trades = self._client.fetch_trades_in_range(
                start_ts=int(start_at.timestamp()),
                end_ts=int(end_at.timestamp()),
                max_pages=self._config.max_trade_pages,
                page_size=self._config.trade_page_size,
                condition_ids=[condition_id],
            )
            if len(market_trades) >= 3000:
                truncated_market_count += 1
            recent_trades.extend(market_trades)
            percent = 12 + int((index / total_chunks) * 28)
            _emit_progress(
                progress_callback,
                percent,
                "Fetching archive trades",
                f"Fetched market {index}/{total_chunks} across {interval_hours:.1f}h",
            )

        scoped_trades = [trade for trade in recent_trades if trade.condition_id in focus_markets]
        base_min = min_notional if min_notional is not None else Decimal("250")
        normal_candidate_trades = _build_candidate_trade_set(
            scoped_trades,
            minimum_notional=base_min,
        )
        wallet_trades = _group_wallet_trades(scoped_trades)
        market_trades = _group_market_trades(scoped_trades)
        domain_trades = _group_domain_trades(scoped_trades, focus_markets)
        wallet_cache: dict[str, tuple[object, list[Trade], WalletPerformance]] = {}
        funding_cache: dict[tuple[str, str], FundingContext] = {}
        normal_candidate_ids = {trade.trade_id for trade in normal_candidate_trades}
        validation_cache_only = validation_cache_only_mode()
        pre_admission_pool = _structural_pre_admission_prefunding_pool(
            scoped_trades,
            minimum_notional=base_min,
            normal_candidate_ids=normal_candidate_ids,
        )
        pre_admission_funding: dict[str, FundingContext] = {}
        pre_admission_wallet_histories: dict[str, list[Trade]] = {}
        pre_trace_attempted_ids: set[str] = set()
        pre_trace_succeeded_ids: set[str] = set()
        pre_trace_skipped_reasons: dict[str, str] = {}
        funding_trace_disabled = effective_funding_trace_mode == FUNDING_TRACE_MODE_DISABLED
        if pre_admission_pool and (validation_cache_only or funding_trace_disabled):
            skip_reason = (
                "validation_cache_only_pre_admission_skipped"
                if validation_cache_only
                else (
                    "funding_trace_disabled_no_rpc_mode"
                    if include_blockchain
                    else "funding_trace_not_requested"
                )
            )
            for trade in pre_admission_pool:
                pre_trace_skipped_reasons[trade.trade_id] = skip_reason
                self._funding_resolver.record_trace_skipped(skip_reason)
            _emit_progress(
                progress_callback,
                41,
                "Skipping blockchain linkage",
                f"Skipping {len(pre_admission_pool)} pre-admission funding checks; funding evidence remains unknown",
            )
        elif pre_admission_pool:
            _emit_progress(
                progress_callback,
                41,
                "Tracing blockchain linkage",
                f"Starting {len(pre_admission_pool)} pre-admission funding checks",
            )

        def hydrate_wallet(trade: Trade) -> tuple[object, list[Trade], WalletPerformance]:
            cached = wallet_cache.get(trade.wallet)
            if cached is not None:
                return cached
            wallet_stats = self._client.fetch_wallet_stats(trade.wallet)
            wallet_inspection = _build_wallet_inspection(
                trade.wallet,
                wallet_stats.trades,
                wallet_stats.traded_market_count,
                wallet_stats.polygon_nonce,
                focus_markets,
            )
            wallet_positions = self._client.fetch_wallet_positions(trade.wallet)
            wallet_performance = compute_wallet_performance(wallet_stats.trades, wallet_positions)
            cached = (wallet_inspection, wallet_stats.trades, wallet_performance)
            wallet_cache[trade.wallet] = cached
            return cached

        pre_admission_total = max(1, len(pre_admission_pool))
        for pre_index, trade in enumerate([] if validation_cache_only or funding_trace_disabled else pre_admission_pool, start=1):
            if _stop_requested(stop_event):
                break
            wallet_inspection, wallet_history_trades, _wallet_performance = hydrate_wallet(trade)
            pre_admission_wallet_histories[trade.wallet] = wallet_history_trades
            trade_domain = _domain_for_trade(trade, focus_markets)
            prior_gap_days, _observed_post_gap_days = _wallet_activity_gap_days(wallet_history_trades, trade)
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
            funding_key = _funding_cache_key(trade)
            funding_context = funding_cache.get(funding_key) or FundingContext(funding_found=False)
            if not funding_context.funding_found and funding_context.error is None and funding_key not in funding_cache:
                should_trace = _should_trace_funding(
                    wallet_inspection,
                    trade=trade,
                    mode="archive",
                    derived_metrics={
                        "trade_domain": trade_domain,
                        "opening_exposure_flag": opening_exposure,
                        "capital_at_risk_usdc": _capital_at_risk_usdc(trade, execution_state),
                        "wallet_market_conviction_ratio": _wallet_market_conviction_ratio(
                            wallet_trades.get(trade.wallet, []),
                            trade,
                        ),
                        "reactivated_after_dormancy_flag": bool(
                            prior_gap_days is not None and prior_gap_days >= 30
                        ),
                    },
                )
                if should_trace:
                    pre_trace_attempted_ids.add(trade.trade_id)
                    _emit_progress(
                        progress_callback,
                        41,
                        "Tracing blockchain linkage",
                        f"Pre-admission funding check {pre_index}/{pre_admission_total}",
                    )
                    funding_context = self._funding_resolver.analyze(trade.wallet, trade.timestamp)
                    funding_cache[funding_key] = funding_context
                    _emit_progress(
                        progress_callback,
                        41,
                        "Tracing blockchain linkage",
                        f"Pre-admission funding check {pre_index}/{pre_admission_total} finished",
                    )
                else:
                    self._funding_resolver.record_trace_skipped("funding_trace_not_requested")
                    funding_context = unknown_funding_context("funding_trace_not_requested")
                    pre_trace_skipped_reasons[trade.trade_id] = "funding_trace_not_requested"
            elif funding_key in funding_cache:
                pre_trace_attempted_ids.add(trade.trade_id)
            if funding_context.error is None:
                pre_trace_succeeded_ids.add(trade.trade_id)
            pre_admission_funding[trade.trade_id] = funding_context

        pre_admission_metadata = _build_structural_pre_admission_metadata(
            pre_admission_pool,
            minimum_notional=base_min,
            funding_context_by_trade_id=pre_admission_funding,
            wallet_history_by_wallet=pre_admission_wallet_histories,
            normal_candidate_ids=normal_candidate_ids,
            enable_structural_pre_admission=True,
        )
        candidate_admission_funnel = _build_structural_pre_admission_funnel(
            scoped_trades,
            minimum_notional=base_min,
            normal_candidate_ids=normal_candidate_ids,
            pre_admission_pool=pre_admission_pool,
            funding_context_by_trade_id=pre_admission_funding,
            wallet_history_by_wallet=pre_admission_wallet_histories,
            admission_metadata=pre_admission_metadata,
            funding_resolver_health=self._funding_resolver.health(),
            pre_admission_funding_trace_enabled=not validation_cache_only and not funding_trace_disabled,
            pre_admission_funding_trace_attempted_ids=pre_trace_attempted_ids,
            pre_admission_funding_trace_succeeded_ids=pre_trace_succeeded_ids,
            pre_admission_funding_trace_skipped_reasons=pre_trace_skipped_reasons,
        )
        candidate_trades = _build_candidate_trade_set(
            scoped_trades,
            minimum_notional=base_min,
            enable_structural_pre_admission=True,
            structural_pre_admission_metadata=pre_admission_metadata,
        )
        if max_notional is not None:
            candidate_trades = [trade for trade in candidate_trades if trade.notional <= max_notional]
            pre_admission_metadata = {
                trade_id: metadata
                for trade_id, metadata in pre_admission_metadata.items()
                if any(trade.trade_id == trade_id for trade in candidate_trades)
            }

        _emit_progress(
            progress_callback,
            45,
            "Filtering",
            (
                f"{len(candidate_trades)} candidate trades remain after archive filters"
                + (
                    f" ({len(pre_admission_metadata)} structurally pre-admitted)"
                    if pre_admission_metadata
                    else ""
                )
            ),
        )

        candidate_cases: list[FlaggedCase] = []
        total_candidates = max(1, len(candidate_trades))
        if candidate_trades:
            _emit_progress(
                progress_callback,
                46,
                "Tracing blockchain linkage",
                f"Starting candidate funding checks for {len(candidate_trades)} archive candidates",
            )
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
            if funding_trace_disabled:
                skip_reason = (
                    "funding_trace_disabled_no_rpc_mode"
                    if include_blockchain
                    else "funding_trace_not_requested"
                )
                self._funding_resolver.record_trace_skipped(skip_reason)
                funding_context = unknown_funding_context(skip_reason)
            elif _should_trace_funding(
                wallet_inspection,
                trade=trade,
                mode="archive",
                derived_metrics={
                    "trade_domain": trade_domain,
                    "opening_exposure_flag": opening_exposure,
                    "capital_at_risk_usdc": capital_at_risk,
                    "wallet_market_conviction_ratio": conviction_ratio,
                    "reactivated_after_dormancy_flag": bool(
                        prior_gap_days is not None and prior_gap_days >= 30
                    ),
                },
            ):
                funding_key = _funding_cache_key(trade)
                funding_context = funding_cache.get(funding_key) or FundingContext(funding_found=False)
                if not funding_context.funding_found and funding_context.error is None and funding_key not in funding_cache:
                    _emit_progress(
                        progress_callback,
                        46 + int((trade_index / total_candidates) * 20),
                        "Tracing blockchain linkage",
                        f"Candidate funding check {trade_index}/{len(candidate_trades)}",
                    )
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
                _apply_candidate_admission_metadata(
                    case,
                    pre_admission_metadata.get(trade.trade_id),
                )
                _annotate_archive_wallet_history(case, wallet_performance)
                candidate_cases.append(case)

            percent = 45 + int((trade_index / total_candidates) * 30)
            _emit_progress(
                progress_callback,
                percent,
                "Scoring",
                f"Scored archive candidate {trade_index}/{total_candidates}",
            )

        _annotate_domain_peer_history(candidate_cases, wallet_cache)
        _annotate_preclassification_linkage(candidate_cases)
        _validate_candidate_admissions(candidate_cases)
        _finalize_structural_pre_admission_funnel(candidate_admission_funnel, candidate_cases)
        _annotate_hard_evidence_review(
            candidate_cases,
            evidence_availability_stage="archive_no_outcome_context",
        )
        strong_risk_candidates = list(candidate_cases)
        flagged_cases: list[FlaggedCase] = []
        excluded_cases: list[FlaggedCase] = []
        for case in candidate_cases:
            visibility_tier = _visibility_tier_for_case(case)
            case.raw_metrics["visibility_tier"] = visibility_tier
            case.raw_metrics["visible_inclusion_status"] = visibility_tier
            if visibility_tier in {"Visible", HARD_EVIDENCE_REVIEW_TIER}:
                flagged_cases.append(case)
            else:
                case.raw_metrics["exclusion_reason"] = "Promoted to secondary review rather than hidden."
                excluded_cases.append(case)
        flagged_cases.sort(key=_archive_case_sort_key, reverse=True)
        excluded_cases.sort(key=lambda item: item.suspicion_score, reverse=True)
        strong_risk_diagnostics = _build_strong_risk_diagnostics(strong_risk_candidates)
        stopped = _stop_requested(stop_event)

        wallet_rollups = _wallet_rollups(scoped_trades, candidate_trades, flagged_cases, wallet_cache)
        market_rollups = _market_rollups(scoped_trades, candidate_trades, flagged_cases, focus_markets)
        report = {
            "generated_at": started_at.isoformat(),
            "range_start": start_at.isoformat(),
            "range_end": end_at.isoformat(),
            "range_hours": round(interval_hours, 2),
            "topic_scope": ",".join(category.label for category in selected_categories),
            "raw_trade_count": len(recent_trades),
            "filtered_trade_count": len(scoped_trades),
            "candidate_trade_count": len(candidate_trades),
            "normal_candidate_trade_count": len(normal_candidate_trades),
            "structural_pre_admission_count": sum(
                1
                for case in candidate_cases
                if case.raw_metrics.get("candidateAdmissionStage") == "pre_admitted_validated"
            ),
            "structural_pre_admission_rejected_count": sum(
                1
                for case in candidate_cases
                if case.raw_metrics.get("candidateAdmissionStage") == "pre_admitted_rejected"
            ),
            "flagged_case_count": len(flagged_cases),
            "excluded_case_count": len(excluded_cases),
            "secondary_review_case_count": len(excluded_cases),
            "unique_wallet_count": len({trade.wallet for trade in scoped_trades}),
            "unique_market_count": len({trade.condition_id for trade in scoped_trades}),
            "truncated_market_count": truncated_market_count,
            "status": "stopped" if stopped else "completed",
            "cases": [case.to_dict() for case in flagged_cases],
            "secondary_review_cases": [case.to_dict() for case in excluded_cases],
            "wallet_rollups_top": wallet_rollups[:25],
            "market_rollups_top": market_rollups[:25],
            "candidate_admission_funnel": candidate_admission_funnel,
            "funding_resolver_health": self._funding_resolver.health().to_dict(),
            "analysis_settings": {
                "include_blockchain": bool(include_blockchain),
                "funding_trace_mode": effective_funding_trace_mode,
                "include_related_markets": bool(include_related_markets),
                "case_family_scope_status": "archive_category_scan_no_single_event_anchor",
                "case_family_scope_note": (
                    "Archive scanner runs are category-wide. Event-target case-family expansion is available "
                    "in Event Forensic; this archive setting is recorded for UI consistency and does not "
                    "broaden candidate admission."
                ),
            },
        }
        export_files = self._write_report_files(
            started_at,
            reports_dir,
            report,
            scoped_trades=scoped_trades,
            candidate_trades=candidate_trades,
            flagged_cases=flagged_cases,
            excluded_cases=excluded_cases,
            strong_risk_diagnostics=strong_risk_diagnostics,
            wallet_rollups=wallet_rollups,
            market_rollups=market_rollups,
            candidate_admission_funnel=candidate_admission_funnel,
            candidate_admission_records=_archive_candidate_admission_records(
                candidate_cases,
                near_miss_records=_candidate_admission_near_miss_records(candidate_admission_funnel),
            ),
            indexer_warehouse_pointer=indexer_warehouse_pointer,
        )
        report["export_files"] = export_files
        report["report_json_path"] = export_files["report_json_path"]
        report["report_md_path"] = export_files["report_md_path"]
        report["report_txt_path"] = export_files["summary_txt_path"]
        _emit_progress(progress_callback, 92, "Saving", "Archive exports written to disk")

        range_label = f"{start_at.isoformat()} -> {end_at.isoformat()}"
        scan_run_id = self._storage.create_scan_run(
            started_at=started_at.isoformat(),
            lookback=range_label,
            topic_scope=",".join(category.label for category in selected_categories),
            raw_trade_count=len(recent_trades),
            filtered_trade_count=len(scoped_trades),
            flagged_case_count=len(flagged_cases),
            report_json_path=export_files["report_json_path"],
            report_md_path=export_files["report_md_path"],
        )
        self._storage.save_flagged_cases(scan_run_id, flagged_cases)

        report["scan_run_id"] = scan_run_id
        if stopped:
            _emit_progress(progress_callback, 100, "Stopped", "Archive run stopped and partial exports saved")
        else:
            _emit_progress(progress_callback, 100, "Done", "Archive export finished")
        return report

    def _write_report_files(
        self,
        started_at: datetime,
        reports_dir: Path,
        report: dict[str, object],
        *,
        scoped_trades: list[Trade],
        candidate_trades: list[Trade],
        flagged_cases: list[FlaggedCase],
        excluded_cases: list[FlaggedCase],
        strong_risk_diagnostics: list[dict[str, object]],
        wallet_rollups: list[dict[str, object]],
        market_rollups: list[dict[str, object]],
        candidate_admission_funnel: dict[str, object] | None = None,
        candidate_admission_records: list[dict[str, object]] | None = None,
        indexer_warehouse_pointer: dict[str, object] | None = None,
    ) -> dict[str, str]:
        suffix = "_stopped" if report.get("status") == "stopped" else ""
        base_name = started_at.strftime("archive_research_%Y%m%d_%H%M%S") + suffix
        json_path = reports_dir / f"{base_name}.json"
        md_path = reports_dir / f"{base_name}.md"
        summary_txt_path = self._config.outputs_dir / f"{base_name}_summary.txt"
        trades_csv_path = self._config.outputs_dir / f"{base_name}_trades.csv"
        candidates_csv_path = self._config.outputs_dir / f"{base_name}_candidates.csv"
        flagged_csv_path = self._config.outputs_dir / f"{base_name}_flagged.csv"
        secondary_review_csv_path = self._config.outputs_dir / f"{base_name}_secondary_review.csv"
        resolution_gap_csv_path = self._config.outputs_dir / f"{base_name}_resolution_gap_cases.csv"
        yield_farm_csv_path = self._config.outputs_dir / f"{base_name}_yield_farm_cases.csv"
        theta_decay_csv_path = self._config.outputs_dir / f"{base_name}_theta_decay_cases.csv"
        off_hours_csv_path = self._config.outputs_dir / f"{base_name}_off_hours_cases.csv"
        zombie_distortion_csv_path = self._config.outputs_dir / f"{base_name}_zombie_distortion_cases.csv"
        bot_like_csv_path = self._config.outputs_dir / f"{base_name}_bot_like_cases.csv"
        domain_specialist_csv_path = self._config.outputs_dir / f"{base_name}_domain_specialist_cases.csv"
        funding_links_csv_path = self._config.outputs_dir / f"{base_name}_funding_links.csv"
        excluded_json_path = self._config.outputs_dir / f"{base_name}_excluded_hidden.json"
        strong_risk_diagnostic_csv_path = self._config.outputs_dir / f"{base_name}_strong_risk_diagnostic.csv"
        strong_risk_diagnostic_md_path = self._config.outputs_dir / f"{base_name}_strong_risk_diagnostic.md"
        wallets_csv_path = self._config.outputs_dir / f"{base_name}_wallets.csv"
        markets_csv_path = self._config.outputs_dir / f"{base_name}_markets.csv"
        admission_funnel_json_path = self._config.outputs_dir / f"{base_name}_candidate_admission_funnel.json"
        admission_funnel_md_path = self._config.outputs_dir / f"{base_name}_candidate_admission_funnel.md"
        admission_records_json_path = self._config.outputs_dir / f"{base_name}_candidate_admission_records.json"

        export_files = {
            "report_json_path": str(json_path),
            "report_md_path": str(md_path),
            "summary_txt_path": str(summary_txt_path),
            "trades_csv_path": str(trades_csv_path),
            "candidates_csv_path": str(candidates_csv_path),
            "flagged_csv_path": str(flagged_csv_path),
            "secondary_review_csv_path": str(secondary_review_csv_path),
            "resolution_gap_cases_csv_path": str(resolution_gap_csv_path),
            "yield_farm_cases_csv_path": str(yield_farm_csv_path),
            "theta_decay_cases_csv_path": str(theta_decay_csv_path),
            "off_hours_cases_csv_path": str(off_hours_csv_path),
            "zombie_distortion_cases_csv_path": str(zombie_distortion_csv_path),
            "bot_like_cases_csv_path": str(bot_like_csv_path),
            "domain_specialist_cases_csv_path": str(domain_specialist_csv_path),
            "funding_links_csv_path": str(funding_links_csv_path),
            "excluded_hidden_json_path": str(excluded_json_path),
            "strong_risk_diagnostic_csv_path": str(strong_risk_diagnostic_csv_path),
            "strong_risk_diagnostic_md_path": str(strong_risk_diagnostic_md_path),
            "wallets_csv_path": str(wallets_csv_path),
            "markets_csv_path": str(markets_csv_path),
            "candidate_admission_funnel_json_path": str(admission_funnel_json_path),
            "candidate_admission_funnel_md_path": str(admission_funnel_md_path),
            "candidate_admission_records_json_path": str(admission_records_json_path),
        }
        report["export_files"] = export_files
        if indexer_warehouse_pointer is not None:
            report_with_pointer = attach_indexer_warehouse_pointer(
                report,
                indexer_warehouse_pointer,
                source_report_id=str(json_path),
                generated_at=started_at,
            )
            report.clear()
            report.update(report_with_pointer)

        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(_to_markdown(report), encoding="utf-8")
        summary_txt_path.write_text(_to_text_report(report), encoding="utf-8")
        _write_trades_csv(trades_csv_path, scoped_trades)
        _write_trades_csv(candidates_csv_path, candidate_trades)
        _write_flagged_csv(flagged_csv_path, flagged_cases)
        _write_flagged_csv(secondary_review_csv_path, excluded_cases)
        _write_case_slice_csv(
            resolution_gap_csv_path,
            flagged_cases,
            lambda case: case.case_type == "Resolution Gap" or case.raw_metrics.get("resolution_gap_flag") == "Yes",
        )
        _write_case_slice_csv(
            yield_farm_csv_path,
            flagged_cases,
            lambda case: "yield_farm_pattern" in case.flags,
        )
        _write_case_slice_csv(
            theta_decay_csv_path,
            flagged_cases,
            lambda case: "theta_decay_pattern" in case.flags,
        )
        _write_case_slice_csv(
            off_hours_csv_path,
            flagged_cases,
            lambda case: case.raw_metrics.get("off_hours_flag") == "Yes",
        )
        _write_case_slice_csv(
            zombie_distortion_csv_path,
            flagged_cases,
            lambda case: case.raw_metrics.get("formal_win_rate_may_be_overstated") == "Yes",
        )
        _write_case_slice_csv(
            bot_like_csv_path,
            flagged_cases,
            lambda case: (
                case.raw_metrics.get("low_analyst_value_flag") == "Yes"
                or float(case.raw_metrics.get("bot_likeness_score", "0") or 0) >= 70.0
            ),
        )
        _write_case_slice_csv(
            domain_specialist_csv_path,
            flagged_cases,
            lambda case: (
                "domain_specialist_profile" in case.flags
                or float(case.raw_metrics.get("domain_concentration_score", "0") or 0) >= 0.75
            ),
        )
        _write_rollup_csv(funding_links_csv_path, _build_funding_link_rows(flagged_cases))
        _write_hidden_excluded_json(excluded_json_path, excluded_cases)
        _write_strong_risk_diagnostic_csv(strong_risk_diagnostic_csv_path, strong_risk_diagnostics)
        strong_risk_diagnostic_md_path.write_text(
            _strong_risk_diagnostic_markdown(strong_risk_diagnostics),
            encoding="utf-8",
        )
        _write_rollup_csv(wallets_csv_path, wallet_rollups)
        _write_rollup_csv(markets_csv_path, market_rollups)
        if isinstance(candidate_admission_funnel, dict):
            admission_funnel_json_path.write_text(
                json.dumps(candidate_admission_funnel, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            admission_funnel_md_path.write_text(
                _structural_pre_admission_funnel_markdown(candidate_admission_funnel),
                encoding="utf-8",
            )
        admission_records_json_path.write_text(
            json.dumps(candidate_admission_records or [], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return export_files

    def _load_archive_focus_markets(
        self,
        selected_categories: tuple[SiteCategory, ...],
        start_at: datetime,
        end_at: datetime,
    ) -> dict[str, Market]:
        # Archive research is meant for trades around event resolution, not all long-dated open markets.
        relevant_markets: dict[str, Market] = {}
        sources = (
            self._client.fetch_focus_markets(
                selected_categories=selected_categories,
                max_pages=3,
                page_size=200,
                active="true",
                closed=None,
            ),
            self._client.fetch_focus_markets(
                selected_categories=selected_categories,
                max_pages=3,
                page_size=200,
                active=None,
                closed="true",
            ),
        )
        resolution_deadline = end_at + timedelta(days=ARCHIVE_EVENT_LOOKAHEAD_DAYS)
        for source in sources:
            for condition_id, market in source.items():
                if not market.end_date:
                    continue
                try:
                    end_dt = datetime.fromisoformat(market.end_date.replace("Z", "+00:00")).astimezone(UTC)
                except ValueError:
                    continue
                if end_dt < start_at:
                    continue
                if end_dt > resolution_deadline:
                    continue
                relevant_markets[condition_id] = market
        return relevant_markets


def _archive_candidate_admission_records(
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
                "suspiciousFundingQuality": raw.get("suspiciousFundingQuality", ""),
                "suspiciousFundingQualityReasons": raw.get("suspiciousFundingQualityReasons", ""),
                "suspiciousFundingHardEvidenceEligible": raw.get("suspiciousFundingHardEvidenceEligible", ""),
                "repricingSourceQuality": raw.get("repricingSourceQuality") or raw.get("repricing_source_quality", ""),
                "rawMetrics": dict(raw),
            }
        )
    return records


def parse_local_datetime(raw: str) -> datetime:
    text = raw.strip()
    if not text:
        raise ValueError("Datetime is required.")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid datetime: {raw}") from exc
    if parsed.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(UTC)


def default_archive_range() -> tuple[str, str]:
    end_local = datetime.now().astimezone().replace(second=0, microsecond=0)
    start_local = end_local - timedelta(days=1)
    return (
        start_local.replace(tzinfo=None).isoformat(timespec="minutes"),
        end_local.replace(tzinfo=None).isoformat(timespec="minutes"),
    )


def _visibility_tier_for_case(case: FlaggedCase) -> str:
    raw = case.raw_metrics
    win_rate_visible = (
        raw.get("economic_win_rate_clears_threshold") == "Yes"
        or raw.get("win_rate_clears_threshold") == "Yes"
        or raw.get("wallet_economic_sample_size", "0") in {"", "0"}
    )
    if _case_has_hard_evidence_review(case):
        return HARD_EVIDENCE_REVIEW_TIER
    if case.severity == "Strong Risk":
        return "Visible"
    if raw.get("shared_funding_source_flag") == "Yes":
        if raw.get("cex_proxy_cluster_flag") != "Yes" and raw.get("funding_graph_key_strict"):
            return "Visible"
    if raw.get("split_wallet_pattern_flag") == "Yes":
        if raw.get("cex_proxy_cluster_flag") != "Yes" and raw.get("funding_graph_key_strict"):
            return "Visible"
    if raw.get("cex_proxy_cluster_flag") == "Yes":
        return "Secondary review"
    if raw.get("event_family_repeat_flag") == "Yes" and raw.get("opening_exposure_flag") == "Yes":
        return "Visible"
    if _case_survives_output_threshold(case) and win_rate_visible:
        return "Visible"
    if _case_survives_output_threshold(case):
        return "Secondary review"
    return "Secondary review"


def _archive_case_sort_key(case: FlaggedCase) -> tuple[int, int, int]:
    if case.severity == "Strong Risk":
        bucket = 3
    elif _case_has_hard_evidence_review(case):
        bucket = 2
    else:
        bucket = 1
    return bucket, case.suspicion_score, case.confidence_score


def _trade_row(trade: Trade) -> dict[str, object]:
    normalized = normalize_side_outcome(trade.side, trade.outcome, trade.price).to_raw_metrics()
    cluster = normalize_cluster_direction(trade.side, trade.outcome, trade.price).to_raw_metrics()
    return {
        "trade_id": trade.trade_id,
        "timestamp": trade.timestamp.isoformat(),
        "wallet": trade.wallet,
        "condition_id": trade.condition_id,
        "asset_id": trade.asset_id,
        "side": trade.side,
        "outcome": trade.outcome,
        "price": str(trade.price),
        "raw_token_outcome": normalized["raw_token_outcome"],
        "raw_order_side": normalized["raw_order_side"],
        "raw_token_price": normalized["raw_token_price"],
        "raw_token_price_label": normalized["raw_token_price_label"],
        "economic_side": normalized["economic_side"],
        "economic_side_probability": normalized["economic_side_probability"],
        "economic_side_probability_label": normalized["economic_side_probability_label"],
        "economic_direction_normalized": normalized["economic_direction_normalized"],
        "model_probability_basis": normalized["model_probability_basis"],
        "model_economic_direction": normalized["model_economic_direction"],
        "side_outcome_normalization_status": normalized["side_outcome_normalization_status"],
        "side_outcome_fallback_reason": normalized["side_outcome_fallback_reason"],
        "cluster_direction": cluster["cluster_direction"],
        "cluster_direction_basis": cluster["cluster_direction_basis"],
        "cluster_normalization_status": cluster["cluster_normalization_status"],
        "cluster_direction_fallback_reason": cluster["cluster_direction_fallback_reason"],
        "size": str(trade.size),
        "notional": str(trade.notional),
        "title": trade.title,
        "slug": trade.slug,
        "event_slug": trade.event_slug,
        "trader_name": trade.trader_name,
        "trader_pseudonym": trade.trader_pseudonym,
    }


def _write_trades_csv(path: Path, trades: list[Trade]) -> None:
    fieldnames = list(_trade_row(trades[0]).keys()) if trades else [
        "trade_id",
        "timestamp",
        "wallet",
        "condition_id",
        "asset_id",
        "side",
        "outcome",
        "price",
        "raw_token_outcome",
        "raw_order_side",
        "raw_token_price",
        "raw_token_price_label",
        "economic_side",
        "economic_side_probability",
        "economic_side_probability_label",
        "economic_direction_normalized",
        "model_probability_basis",
        "model_economic_direction",
        "side_outcome_normalization_status",
        "side_outcome_fallback_reason",
        "cluster_direction",
        "cluster_direction_basis",
        "cluster_normalization_status",
        "cluster_direction_fallback_reason",
        "size",
        "notional",
        "title",
        "slug",
        "event_slug",
        "trader_name",
        "trader_pseudonym",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for trade in trades:
            writer.writerow(_trade_row(trade))


def _write_flagged_csv(path: Path, cases: list[FlaggedCase]) -> None:
    fieldnames = [
        "severity",
        "case_type",
        "suspicion_score",
        "confidence_score",
        "review_priority",
        "visibility_tier",
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
        *[
            field
            for field in STRONG_RISK_ATTRIBUTION_FIELDS
            if field
            not in {
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
        ],
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
        "wallet",
        "timestamp",
        "market_title",
        "side",
        "outcome",
        "raw_token_outcome",
        "raw_order_side",
        "raw_token_price",
        "raw_token_price_label",
        "economic_side",
        "economic_side_probability",
        "economic_side_probability_label",
        "economic_direction_normalized",
        "model_probability",
        "model_probability_basis",
        "model_economic_direction",
        "side_outcome_normalization_status",
        "side_outcome_fallback_reason",
        "cluster_direction",
        "cluster_direction_basis",
        "cluster_normalization_status",
        "cluster_direction_fallback_reason",
        "trade_state",
        "trade_notional_usdc",
        "capital_at_risk_usdc",
        "entry_vs_consensus_15m",
        "favorable_move_15m",
        "favorable_move_1h",
        "favorable_move_4h",
        "repricing_source_quality",
        "repricing_source_quality_reasons",
        "repricing_driver_trade_count",
        "repricing_driver_wallet_count",
        "repricing_window_trade_count",
        "repricing_same_outcome_trade_count",
        "repricing_driven_by_single_wallet",
        "strong_timing_proof_count",
        "supporting_booster_count",
        "liquidity_shock_signal",
        "coordinated_cluster_signal",
        "wallet_specialization_ratio",
        "wallet_market_conviction_ratio",
        "same_side_share_30m",
        "market_size_percentile",
        "wallet_size_multiple_vs_median",
        "wallet_closed_positions",
        "wallet_closed_win_rate",
        "wallet_economic_win_rate",
        "wallet_statistical_prior_label",
        "wallet_statistical_p_value",
        "wallet_statistical_log_score",
        "wallet_resolved_sample_size",
        "wallet_resolved_win_rate",
        "wallet_statistical_prior_note",
        "zombie_loss_count",
        "zombie_loss_notional",
        "redemption_avoidance_ratio",
        "formal_win_rate_may_be_overstated",
        "bot_likeness_score",
        "manual_review_value_score",
        "domain_specialist_label",
        "domain_concentration_score",
        "trade_domain",
        "domain_peer_percentile",
        "domain_adjusted_anomaly_score",
        "wallet_domain_peer_percentile",
        "event_timezone",
        "local_event_time",
        "off_hours_flag",
        "deadline_market_flag",
        "offline_timeline_matched",
        "public_knowledge_at",
        "official_confirmation_at",
        "public_outcome_at",
        "stale_resolution_annotation",
        "reality_oracle_gap_label",
        "timeline_source",
        "timeline_id",
        "funding_source_label",
        "funding_source_category",
        "funding_origin_label",
        "funding_origin_category",
        "funding_amount_usdc",
        "funding_timestamp",
        "minutes_from_funding_to_trade",
        "funding_velocity_label",
        "suspicious_funding_score",
        "suspicious_funding_flag",
        "recent_external_funding_flag",
        "funding_depth",
        "funding_evidence_grade",
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
        "funding_proxy_tight_cohort_flag",
        "funding_proxy_tight_cohort_size",
        "shared_funding_source_flag",
        "shared_funding_source_cluster_size",
        "shared_funding_source_wallet_count",
        "sharedFundingSourceWalletCount",
        "win_rate_clears_threshold",
        "economic_win_rate_clears_threshold",
        "hours_to_resolution",
        "verdict",
        "win_rate_adjustment_note",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    "severity": case.severity,
                    "case_type": case.case_type or "",
                    "suspicion_score": case.suspicion_score,
                    "confidence_score": case.confidence_score,
                    "review_priority": case.review_priority,
                    "visibility_tier": case.raw_metrics.get("visibility_tier", ""),
                    "hardEvidenceSources": case.raw_metrics.get("hardEvidenceSources", ""),
                    "hardEvidenceStrength": case.raw_metrics.get("hardEvidenceStrength", ""),
                    "hardEvidencePrimaryReason": case.raw_metrics.get("hardEvidencePrimaryReason", ""),
                    "hardEvidenceTradeIds": case.raw_metrics.get("hardEvidenceTradeIds", ""),
                    "hardEvidenceWalletIds": case.raw_metrics.get("hardEvidenceWalletIds", ""),
                    "hardEvidenceReviewTier": case.raw_metrics.get("hardEvidenceReviewTier", ""),
                    "evidenceAvailabilityStage": case.raw_metrics.get("evidenceAvailabilityStage", ""),
                    "strongRiskGatePassed": case.raw_metrics.get("strongRiskGatePassed", ""),
                    "strongRiskGateType": case.raw_metrics.get("strongRiskGateType", ""),
                    "strongRiskGateReasons": case.raw_metrics.get("strongRiskGateReasons", ""),
                    "strongRiskGateEvidenceSources": case.raw_metrics.get("strongRiskGateEvidenceSources", ""),
                    "strongRiskTimingProofSources": case.raw_metrics.get("strongRiskTimingProofSources", ""),
                    "strongRiskStructuralSources": case.raw_metrics.get("strongRiskStructuralSources", ""),
                    "strongRiskSupportingBoosters": case.raw_metrics.get("strongRiskSupportingBoosters", ""),
                    "strongRiskStructuralConcernCount": case.raw_metrics.get("strongRiskStructuralConcernCount", ""),
                    "strongRiskTimingProofCount": case.raw_metrics.get("strongRiskTimingProofCount", ""),
                    "strongRiskOpeningExposureConfirmed": case.raw_metrics.get("strongRiskOpeningExposureConfirmed", ""),
                    "strongRiskConfidenceScore": case.raw_metrics.get("strongRiskConfidenceScore", ""),
                    "strongRiskSuspicionScore": case.raw_metrics.get("strongRiskSuspicionScore", ""),
                    "strongRiskSuppressorConflict": case.raw_metrics.get("strongRiskSuppressorConflict", ""),
                    "strongRiskSuppressorConflictReasons": case.raw_metrics.get("strongRiskSuppressorConflictReasons", ""),
                    "strongRiskHasHardEvidenceSources": case.raw_metrics.get("strongRiskHasHardEvidenceSources", ""),
                    "strongRiskNoHardEvidenceExplanation": case.raw_metrics.get("strongRiskNoHardEvidenceExplanation", ""),
                    "strongRiskCompositionClass": case.raw_metrics.get("strongRiskCompositionClass", ""),
                    **{
                        field: case.raw_metrics.get(field, "")
                        for field in STRONG_RISK_ATTRIBUTION_FIELDS
                        if field
                        not in {
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
                    },
                    "candidateAdmissionReason": case.raw_metrics.get("candidateAdmissionReason", ""),
                    "candidateAdmissionStage": case.raw_metrics.get("candidateAdmissionStage", ""),
                    "candidateAdmissionEvidenceSources": case.raw_metrics.get("candidateAdmissionEvidenceSources", ""),
                    "candidateAdmissionFloorNotional": case.raw_metrics.get("candidateAdmissionFloorNotional", ""),
                    "groupedCandidateId": case.raw_metrics.get("groupedCandidateId", ""),
                    "groupedCandidateAggregateNotional": case.raw_metrics.get("groupedCandidateAggregateNotional", ""),
                    "groupedCandidateWalletCount": case.raw_metrics.get("groupedCandidateWalletCount", ""),
                    "groupedCandidateStrictFunding": case.raw_metrics.get("groupedCandidateStrictFunding", ""),
                    "groupedCandidateProxyOnly": case.raw_metrics.get("groupedCandidateProxyOnly", ""),
                    "groupedCandidateFundingGrade": case.raw_metrics.get("groupedCandidateFundingGrade", ""),
                    "groupedCandidateTimeSpanMinutes": case.raw_metrics.get("groupedCandidateTimeSpanMinutes", ""),
                    "groupedCandidatePriceBand": case.raw_metrics.get("groupedCandidatePriceBand", ""),
                    "candidateAdmissionValidatedOpeningExposure": case.raw_metrics.get("candidateAdmissionValidatedOpeningExposure", ""),
                    "candidateAdmissionRejectedReason": case.raw_metrics.get("candidateAdmissionRejectedReason", ""),
                    "wallet": case.trade.wallet,
                    "timestamp": case.trade.timestamp.isoformat(),
                    "market_title": case.trade.title,
                    "side": case.trade.side,
                    "outcome": case.trade.outcome,
                    "raw_token_outcome": case.raw_metrics.get("raw_token_outcome", ""),
                    "raw_order_side": case.raw_metrics.get("raw_order_side", ""),
                    "raw_token_price": case.raw_metrics.get("raw_token_price", ""),
                    "raw_token_price_label": case.raw_metrics.get("raw_token_price_label", ""),
                    "economic_side": case.raw_metrics.get("economic_side", ""),
                    "economic_side_probability": case.raw_metrics.get("economic_side_probability", ""),
                    "economic_side_probability_label": case.raw_metrics.get("economic_side_probability_label", ""),
                    "economic_direction_normalized": case.raw_metrics.get("economic_direction_normalized", ""),
                    "model_probability": case.raw_metrics.get("model_probability", ""),
                    "model_probability_basis": case.raw_metrics.get("model_probability_basis", ""),
                    "model_economic_direction": case.raw_metrics.get("model_economic_direction", ""),
                    "side_outcome_normalization_status": case.raw_metrics.get("side_outcome_normalization_status", ""),
                    "side_outcome_fallback_reason": case.raw_metrics.get("side_outcome_fallback_reason", ""),
                    "cluster_direction": case.raw_metrics.get("cluster_direction", ""),
                    "cluster_direction_basis": case.raw_metrics.get("cluster_direction_basis", ""),
                    "cluster_normalization_status": case.raw_metrics.get("cluster_normalization_status", ""),
                    "cluster_direction_fallback_reason": case.raw_metrics.get("cluster_direction_fallback_reason", ""),
                    "trade_state": case.raw_metrics.get("trade_state", ""),
                    "trade_notional_usdc": case.raw_metrics.get("trade_notional_usdc", ""),
                    "capital_at_risk_usdc": case.raw_metrics.get("capital_at_risk_usdc", ""),
                    "entry_vs_consensus_15m": case.raw_metrics.get("entry_vs_consensus_15m", ""),
                    "favorable_move_15m": case.raw_metrics.get("favorable_move_15m", ""),
                    "favorable_move_1h": case.raw_metrics.get("favorable_move_1h", ""),
                    "favorable_move_4h": case.raw_metrics.get("favorable_move_4h", ""),
                    "repricing_source_quality": case.raw_metrics.get("repricing_source_quality", ""),
                    "repricing_source_quality_reasons": case.raw_metrics.get("repricing_source_quality_reasons", ""),
                    "repricing_driver_trade_count": case.raw_metrics.get("repricing_driver_trade_count", ""),
                    "repricing_driver_wallet_count": case.raw_metrics.get("repricing_driver_wallet_count", ""),
                    "repricing_window_trade_count": case.raw_metrics.get("repricing_window_trade_count", ""),
                    "repricing_same_outcome_trade_count": case.raw_metrics.get("repricing_same_outcome_trade_count", ""),
                    "repricing_driven_by_single_wallet": case.raw_metrics.get("repricing_driven_by_single_wallet", ""),
                    "strong_timing_proof_count": case.raw_metrics.get("strong_timing_proof_count", ""),
                    "supporting_booster_count": case.raw_metrics.get("supporting_booster_count", ""),
                    "liquidity_shock_signal": case.raw_metrics.get("liquidity_shock_signal", ""),
                    "coordinated_cluster_signal": case.raw_metrics.get("coordinated_cluster_signal", ""),
                    "wallet_specialization_ratio": case.raw_metrics.get("wallet_specialization_ratio", ""),
                    "wallet_market_conviction_ratio": case.raw_metrics.get("wallet_market_conviction_ratio", ""),
                    "same_side_share_30m": case.raw_metrics.get("same_side_share_30m", ""),
                    "market_size_percentile": case.raw_metrics.get("market_size_percentile", ""),
                    "wallet_size_multiple_vs_median": case.raw_metrics.get("wallet_size_multiple_vs_median", ""),
                    "wallet_closed_positions": case.raw_metrics.get("wallet_closed_positions", ""),
                    "wallet_closed_win_rate": case.raw_metrics.get("wallet_closed_win_rate", ""),
                    "wallet_economic_win_rate": case.raw_metrics.get("wallet_economic_win_rate", ""),
                    "wallet_statistical_prior_label": case.raw_metrics.get("wallet_statistical_prior_label", ""),
                    "wallet_statistical_p_value": case.raw_metrics.get("wallet_statistical_p_value", ""),
                    "wallet_statistical_log_score": case.raw_metrics.get("wallet_statistical_log_score", ""),
                    "wallet_resolved_sample_size": case.raw_metrics.get("wallet_resolved_sample_size", ""),
                    "wallet_resolved_win_rate": case.raw_metrics.get("wallet_resolved_win_rate", ""),
                    "wallet_statistical_prior_note": case.raw_metrics.get("wallet_statistical_prior_note", ""),
                    "zombie_loss_count": case.raw_metrics.get("zombie_loss_count", ""),
                    "zombie_loss_notional": case.raw_metrics.get("zombie_loss_notional", ""),
                    "redemption_avoidance_ratio": case.raw_metrics.get("redemption_avoidance_ratio", ""),
                    "formal_win_rate_may_be_overstated": case.raw_metrics.get("formal_win_rate_may_be_overstated", ""),
                    "bot_likeness_score": case.raw_metrics.get("bot_likeness_score", ""),
                    "manual_review_value_score": case.raw_metrics.get("manual_review_value_score", ""),
                    "domain_specialist_label": case.raw_metrics.get("domain_specialist_label", ""),
                    "domain_concentration_score": case.raw_metrics.get("domain_concentration_score", ""),
                    "trade_domain": case.raw_metrics.get("trade_domain", ""),
                    "domain_peer_percentile": case.raw_metrics.get("domain_peer_percentile", ""),
                    "domain_adjusted_anomaly_score": case.raw_metrics.get("domain_adjusted_anomaly_score", ""),
                    "wallet_domain_peer_percentile": case.raw_metrics.get("wallet_domain_peer_percentile", ""),
                    "event_timezone": case.raw_metrics.get("event_timezone", ""),
                    "local_event_time": case.raw_metrics.get("local_event_time", ""),
                    "off_hours_flag": case.raw_metrics.get("off_hours_flag", ""),
                    "deadline_market_flag": case.raw_metrics.get("deadline_market_flag", ""),
                    "offline_timeline_matched": case.raw_metrics.get("offline_timeline_matched", ""),
                    "public_knowledge_at": case.raw_metrics.get("public_knowledge_at", ""),
                    "official_confirmation_at": case.raw_metrics.get("official_confirmation_at", ""),
                    "public_outcome_at": case.raw_metrics.get("public_outcome_at", ""),
                    "stale_resolution_annotation": case.raw_metrics.get("stale_resolution_annotation", ""),
                    "reality_oracle_gap_label": case.raw_metrics.get("reality_oracle_gap_label", ""),
                    "timeline_source": case.raw_metrics.get("timeline_source", ""),
                    "timeline_id": case.raw_metrics.get("timeline_id", ""),
                    "funding_source_label": case.raw_metrics.get("funding_source_label", ""),
                    "funding_source_category": case.raw_metrics.get("funding_source_category", ""),
                    "funding_origin_label": case.raw_metrics.get("funding_origin_label", ""),
                    "funding_origin_category": case.raw_metrics.get("funding_origin_category", ""),
                    "funding_amount_usdc": case.raw_metrics.get("funding_amount_usdc", ""),
                    "funding_timestamp": case.raw_metrics.get("funding_timestamp", ""),
                    "minutes_from_funding_to_trade": case.raw_metrics.get("minutes_from_funding_to_trade", ""),
                    "funding_velocity_label": case.raw_metrics.get("funding_velocity_label", ""),
                    "suspicious_funding_score": case.raw_metrics.get("suspicious_funding_score", ""),
                    "suspicious_funding_flag": case.raw_metrics.get("suspicious_funding_flag", ""),
                    "recent_external_funding_flag": case.raw_metrics.get("recent_external_funding_flag", ""),
                    "funding_depth": case.raw_metrics.get("funding_depth", ""),
                    "funding_evidence_grade": case.raw_metrics.get("funding_evidence_grade", ""),
                    "suspiciousFundingQuality": case.raw_metrics.get("suspiciousFundingQuality", ""),
                    "suspiciousFundingQualityReasons": case.raw_metrics.get("suspiciousFundingQualityReasons", ""),
                    "suspiciousFundingHardEvidenceEligible": case.raw_metrics.get("suspiciousFundingHardEvidenceEligible", ""),
                    "suspiciousFundingTraceSucceeded": case.raw_metrics.get("suspiciousFundingTraceSucceeded", ""),
                    "suspiciousFundingTraceDepth": case.raw_metrics.get("suspiciousFundingTraceDepth", ""),
                    "suspiciousFundingSourceCategory": case.raw_metrics.get("suspiciousFundingSourceCategory", ""),
                    "suspiciousFundingOriginCategory": case.raw_metrics.get("suspiciousFundingOriginCategory", ""),
                    "suspiciousFundingMinutesBeforeTrade": case.raw_metrics.get("suspiciousFundingMinutesBeforeTrade", ""),
                    "suspiciousFundingAmountUsd": case.raw_metrics.get("suspiciousFundingAmountUsd", ""),
                    "suspiciousFundingTradeNotionalUsd": case.raw_metrics.get("suspiciousFundingTradeNotionalUsd", ""),
                    "suspiciousFundingAmountToTradeRatio": case.raw_metrics.get("suspiciousFundingAmountToTradeRatio", ""),
                    "suspiciousFundingRecentEnough": case.raw_metrics.get("suspiciousFundingRecentEnough", ""),
                    "suspiciousFundingAmountAligned": case.raw_metrics.get("suspiciousFundingAmountAligned", ""),
                    "suspiciousFundingIndependentSupport": case.raw_metrics.get("suspiciousFundingIndependentSupport", ""),
                    "suspiciousFundingIndependentSupportSources": case.raw_metrics.get("suspiciousFundingIndependentSupportSources", ""),
                    "suspiciousFundingSuppressorConflict": case.raw_metrics.get("suspiciousFundingSuppressorConflict", ""),
                    "suspiciousFundingSuppressorConflictReasons": case.raw_metrics.get("suspiciousFundingSuppressorConflictReasons", ""),
                    "fundingResolverAvailable": case.raw_metrics.get("fundingResolverAvailable", ""),
                    "fundingResolverDisabledReason": case.raw_metrics.get("fundingResolverDisabledReason", ""),
                    "fundingResolverAuthError": case.raw_metrics.get("fundingResolverAuthError", ""),
                    "fundingResolverUnavailableReason": case.raw_metrics.get("fundingResolverUnavailableReason", ""),
                    "fundingResolverFunctionalStatus": case.raw_metrics.get("fundingResolverFunctionalStatus", ""),
                    "fundingResolverEndpointLabel": case.raw_metrics.get("fundingResolverEndpointLabel", ""),
                    "fundingResolverLastError": case.raw_metrics.get("fundingResolverLastError", ""),
                    "fundingTraceAttemptedCount": case.raw_metrics.get("fundingTraceAttemptedCount", ""),
                    "fundingTraceSucceededCount": case.raw_metrics.get("fundingTraceSucceededCount", ""),
                    "fundingTraceFailedCount": case.raw_metrics.get("fundingTraceFailedCount", ""),
                    "fundingTraceSkippedCount": case.raw_metrics.get("fundingTraceSkippedCount", ""),
                    "fundingTraceCoverageRatio": case.raw_metrics.get("fundingTraceCoverageRatio", ""),
                    "fundingTraceEndpointPoolSize": case.raw_metrics.get("fundingTraceEndpointPoolSize", ""),
                    "fundingTraceEndpointAvailableCount": case.raw_metrics.get("fundingTraceEndpointAvailableCount", ""),
                    "fundingTraceEndpointCooldownCount": case.raw_metrics.get("fundingTraceEndpointCooldownCount", ""),
                    "fundingTraceEndpointFailureDistribution": case.raw_metrics.get("fundingTraceEndpointFailureDistribution", ""),
                    "fundingTraceRateLimitedCount": case.raw_metrics.get("fundingTraceRateLimitedCount", ""),
                    "fundingTraceRetryCount": case.raw_metrics.get("fundingTraceRetryCount", ""),
                    "fundingTraceFallbackEndpointCount": case.raw_metrics.get("fundingTraceFallbackEndpointCount", ""),
                    "fundingTraceLogChunksAttempted": case.raw_metrics.get("fundingTraceLogChunksAttempted", ""),
                    "fundingTraceLogChunksSucceeded": case.raw_metrics.get("fundingTraceLogChunksSucceeded", ""),
                    "fundingTraceLogChunksFailed": case.raw_metrics.get("fundingTraceLogChunksFailed", ""),
                    "fundingTraceLogChunksRateLimited": case.raw_metrics.get("fundingTraceLogChunksRateLimited", ""),
                    "fundingTraceCacheHitCount": case.raw_metrics.get("fundingTraceCacheHitCount", ""),
                    "fundingTraceCacheMissCount": case.raw_metrics.get("fundingTraceCacheMissCount", ""),
                    "fundingTracePersistentCacheEnabled": case.raw_metrics.get("fundingTracePersistentCacheEnabled", ""),
                    "fundingTracePersistentCacheHitCount": case.raw_metrics.get("fundingTracePersistentCacheHitCount", ""),
                    "fundingTracePersistentCacheMissCount": case.raw_metrics.get("fundingTracePersistentCacheMissCount", ""),
                    "fundingTracePersistentCacheWriteCount": case.raw_metrics.get("fundingTracePersistentCacheWriteCount", ""),
                    "fundingTracePersistentCacheExpiredCount": case.raw_metrics.get("fundingTracePersistentCacheExpiredCount", ""),
                    "fundingTracePersistentCacheFailureCooldownCount": case.raw_metrics.get("fundingTracePersistentCacheFailureCooldownCount", ""),
                    "fundingTracePersistentCacheSchemaVersion": case.raw_metrics.get("fundingTracePersistentCacheSchemaVersion", ""),
                    "fundingTraceFromPersistentCache": case.raw_metrics.get("fundingTraceFromPersistentCache", ""),
                    "fundingTracePersistentCacheStatus": case.raw_metrics.get("fundingTracePersistentCacheStatus", ""),
                    "funding_proxy_tight_cohort_flag": case.raw_metrics.get("funding_proxy_tight_cohort_flag", ""),
                    "funding_proxy_tight_cohort_size": case.raw_metrics.get("funding_proxy_tight_cohort_size", ""),
                    "shared_funding_source_flag": case.raw_metrics.get("shared_funding_source_flag", ""),
                    "shared_funding_source_cluster_size": case.raw_metrics.get("shared_funding_source_cluster_size", ""),
                    "shared_funding_source_wallet_count": case.raw_metrics.get("shared_funding_source_wallet_count", ""),
                    "sharedFundingSourceWalletCount": case.raw_metrics.get("sharedFundingSourceWalletCount", ""),
                    "win_rate_clears_threshold": case.raw_metrics.get("win_rate_clears_threshold", ""),
                    "economic_win_rate_clears_threshold": case.raw_metrics.get("economic_win_rate_clears_threshold", ""),
                    "hours_to_resolution": case.raw_metrics.get("hours_to_resolution", ""),
                    "verdict": case.verdict,
                    "win_rate_adjustment_note": case.raw_metrics.get("win_rate_adjustment_note", ""),
                }
            )


def _annotate_archive_wallet_history(case: FlaggedCase, wallet_performance: WalletPerformance) -> None:
    closed_summary = wallet_performance.closed_summary
    activity_summary = wallet_performance.activity_summary
    case.raw_metrics["wallet_closed_positions"] = str(closed_summary.total)
    case.raw_metrics["wallet_closed_wins"] = str(closed_summary.wins)
    case.raw_metrics["wallet_closed_losses"] = str(closed_summary.losses)
    case.raw_metrics["wallet_closed_win_rate"] = f"{closed_summary.win_rate_value:.1f}%"
    case.raw_metrics["wallet_win_rate_threshold"] = f"{closed_summary.win_rate_threshold:.1f}%"
    case.raw_metrics["win_rate_clears_threshold"] = "Yes" if closed_summary.win_rate_clears_threshold else "No"
    case.raw_metrics["wallet_economic_win_rate"] = f"{closed_summary.economic_win_rate_value:.1f}%"
    case.raw_metrics["wallet_economic_sample_size"] = str(closed_summary.economic_sample_size)
    case.raw_metrics["economic_win_rate_clears_threshold"] = (
        "Yes" if closed_summary.economic_win_rate_clears_threshold else "No"
    )
    case.raw_metrics["zombie_loss_count"] = str(closed_summary.zombie_loss_count)
    case.raw_metrics["zombie_loss_notional"] = f"{closed_summary.zombie_loss_notional:.2f}"
    case.raw_metrics["redemption_avoidance_ratio"] = f"{closed_summary.redemption_avoidance_ratio * 100:.1f}%"
    case.raw_metrics["formal_win_rate_may_be_overstated"] = (
        "Yes" if closed_summary.formal_win_rate_may_be_overstated else "No"
    )
    case.raw_metrics.update(compute_wallet_statistical_prior(closed_summary).to_raw_metrics())
    case.raw_metrics["bot_likeness_score"] = f"{activity_summary.bot_likeness_score:.1f}"
    case.raw_metrics["manual_review_value_score"] = f"{activity_summary.manual_review_value_score:.1f}"
    case.raw_metrics["low_analyst_value_flag"] = "Yes" if activity_summary.low_analyst_value_flag else "No"

    relevance_note = win_rate_relevance_note(
        closed_summary.total,
        closed_summary.win_rate_clears_threshold,
    )
    if relevance_note:
        case.raw_metrics["win_rate_relevance_note"] = relevance_note


def _build_strong_risk_diagnostics(cases: list[FlaggedCase]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for case in cases:
        snapshot = _strong_risk_snapshot(case)
        if case.severity == "Strong Risk":
            continue
        rows.append(
            {
                "market": case.trade.title,
                "wallet": case.trade.wallet,
                "case_type": case.case_type or "",
                "raw_score_before_suppressors": int(case.raw_metrics.get("pre_suppressor_score", case.suspicion_score)),
                "wallet_passed_credibility_gate": "Yes" if snapshot["wallet_passed_credibility_gate"] else "No",
                "opening_exposure": "Yes" if snapshot["opening_exposure"] else "No",
                "favorable_repricing": "Yes" if snapshot["favorable_repricing"] else "No",
                "beat_local_consensus": "Yes" if snapshot["beat_local_consensus"] else "No",
                "strong_timing_proof_count": snapshot["strong_timing_proof_count"],
                "supporting_booster_count": snapshot["supporting_booster_count"],
                "structural_concern": "Yes" if snapshot["structural_concern"] else "No",
                "final_class_assigned": "Excluded" if snapshot["excluded_by_win_rate"] else case.severity,
                "strong_risk_block_reason": snapshot["block_reason"],
                "_gate_score": snapshot["gate_score"],
                "_final_score": case.suspicion_score,
            }
        )

    rows.sort(
        key=lambda row: (
            int(row["_gate_score"]),
            int(row["raw_score_before_suppressors"]),
            int(row["_final_score"]),
        ),
        reverse=True,
    )
    trimmed = rows[:20]
    for row in trimmed:
        row.pop("_gate_score", None)
        row.pop("_final_score", None)
    return trimmed


def _strong_risk_snapshot(case: FlaggedCase) -> dict[str, object]:
    raw = case.raw_metrics
    flags = set(case.flags)
    wallet_passed = raw.get("credibility_gamed_flag") != "Yes"
    opening_exposure = raw.get("trade_state") == "increase"
    favorable_repricing = raw.get("favorable_repricing_flag") == "Yes"
    beat_local_consensus = raw.get("beat_consensus_flag") == "Yes"
    strong_timing_proof_count = int(raw.get("strong_timing_proof_count", "0") or 0)
    supporting_booster_count = int(raw.get("supporting_booster_count", "0") or 0)
    structural_concern = raw.get("structural_concern_flag") == "Yes"
    materially_uncertain = raw.get("materially_uncertain_flag") == "Yes"
    decisive_timing_edge = raw.get("decisive_timing_edge_flag") == "Yes"
    benign_pattern = raw.get("benign_pattern_flag") == "Yes"
    resolution_gap_flag = (case.case_type == "Resolution Gap") or raw.get("resolution_gap_flag") == "Yes"
    excluded_by_win_rate = raw.get("visible_inclusion_status") == "Excluded"
    timing_gate_passed = (
        strong_timing_proof_count >= 2
        or (strong_timing_proof_count >= 1 and supporting_booster_count >= 1)
    )

    gate_score = sum(
        1
        for value in (
            wallet_passed,
            opening_exposure,
            favorable_repricing,
            beat_local_consensus,
            timing_gate_passed,
            structural_concern,
            decisive_timing_edge,
            not benign_pattern,
            not resolution_gap_flag,
        )
        if value
    )
    return {
        "wallet_passed_credibility_gate": wallet_passed,
        "opening_exposure": opening_exposure,
        "favorable_repricing": favorable_repricing,
        "beat_local_consensus": beat_local_consensus,
        "strong_timing_proof_count": strong_timing_proof_count,
        "supporting_booster_count": supporting_booster_count,
        "structural_concern": structural_concern,
        "excluded_by_win_rate": excluded_by_win_rate,
        "gate_score": gate_score,
        "block_reason": _strong_risk_block_reason(
            case,
            wallet_passed=wallet_passed,
            opening_exposure=opening_exposure,
            favorable_repricing=favorable_repricing,
            beat_local_consensus=beat_local_consensus,
            strong_timing_proof_count=strong_timing_proof_count,
            supporting_booster_count=supporting_booster_count,
            structural_concern=structural_concern,
            materially_uncertain=materially_uncertain,
            decisive_timing_edge=decisive_timing_edge,
            benign_pattern=benign_pattern,
            resolution_gap_flag=resolution_gap_flag,
            flags=flags,
        ),
    }


def _strong_risk_block_reason(
    case: FlaggedCase,
    *,
    wallet_passed: bool,
    opening_exposure: bool,
    favorable_repricing: bool,
    beat_local_consensus: bool,
    strong_timing_proof_count: int,
    supporting_booster_count: int,
    structural_concern: bool,
    materially_uncertain: bool,
    decisive_timing_edge: bool,
    benign_pattern: bool,
    resolution_gap_flag: bool,
    flags: set[str],
) -> str:
    if not wallet_passed:
        return "Blocked because the wallet context looked gameable or too low-value for a strong-risk label."
    if resolution_gap_flag:
        return "Blocked because the trade looked more like public-news lag or stale market pricing than a private-information opening."
    if not opening_exposure:
        return "Blocked because the trade looked like a close or reduction rather than a fresh directional opening."
    if "near_certainty_trade" in flags:
        return "Blocked because the market was already too close to certainty."
    if "yield_farm_pattern" in flags:
        return "Blocked because the trade resembled near-certain capital parking rather than a real informational edge."
    if "theta_decay_pattern" in flags:
        return "Blocked because the trade resembled an ordinary deadline or theta-decay position."
    if benign_pattern:
        return "Blocked because the trade matched a benign pattern strongly enough to undercut a strong-risk interpretation."
    if not favorable_repricing:
        return "Blocked because no meaningful favorable repricing followed the entry."
    if not decisive_timing_edge:
        return "Blocked because the trade did not show a clear timing edge against consensus or later repricing."
    if strong_timing_proof_count <= 0:
        return "Blocked because the trade never showed a strong timing proof such as repricing, beating consensus, or very early entry."
    if supporting_booster_count <= 0 and strong_timing_proof_count < 2:
        return "Blocked because the trade showed one strong timing proof but lacked a supporting booster such as off-hours, liquidity shock, or coordinated cluster."
    if not structural_concern:
        return "Blocked because we did not see enough structural concern from wallet novelty, concentration, or same-side linkage."
    if not materially_uncertain and not beat_local_consensus and case.suspicion_score < 48:
        return "Blocked because the market was already close to certainty and the trade did not beat consensus strongly enough to overcome that."
    if case.suspicion_score < 40:
        return "Blocked because the overall score still fell short of the strong-risk range."
    if case.confidence_score < 50:
        return "Blocked because the loaded data confidence was too weak for a strong-risk label."
    return "Blocked by the remaining strong-risk gate combination even though several positive signals were present."


def _write_hidden_excluded_json(path: Path, cases: list[FlaggedCase]) -> None:
    payload = {
        "excluded_case_count": len(cases),
        "cases": [case.to_dict() for case in cases],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_case_slice_csv(
    path: Path,
    cases: list[FlaggedCase],
    predicate: Callable[[FlaggedCase], bool],
) -> None:
    _write_flagged_csv(path, [case for case in cases if predicate(case)])


def _build_funding_link_rows(cases: list[FlaggedCase]) -> list[dict[str, object]]:
    grouped = defaultdict(list)
    for case in cases:
        key = case.raw_metrics.get("funding_graph_key", "")
        if key:
            grouped[key].append(case)

    rows: list[dict[str, object]] = []
    for key, linked_cases in grouped.items():
        if len(linked_cases) < 2:
            continue
        wallets = sorted({case.trade.wallet for case in linked_cases})
        markets = sorted({case.trade.title for case in linked_cases})
        sample = linked_cases[0]
        rows.append(
            {
                "funding_graph_key": key,
                "cluster_size": len(linked_cases),
                "wallet_count": len(wallets),
                "wallets": ", ".join(wallets),
                "market_count": len(markets),
                "markets": " | ".join(markets[:10]),
                "funding_origin_label": sample.raw_metrics.get("funding_origin_label", ""),
                "funding_origin_category": sample.raw_metrics.get("funding_origin_category", ""),
                "funding_source_label": sample.raw_metrics.get("funding_source_label", ""),
                "funding_source_category": sample.raw_metrics.get("funding_source_category", ""),
            }
        )
    rows.sort(key=lambda item: int(item["cluster_size"]), reverse=True)
    return rows


def _write_strong_risk_diagnostic_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "market",
        "wallet",
        "case_type",
        "raw_score_before_suppressors",
        "wallet_passed_credibility_gate",
        "opening_exposure",
        "favorable_repricing",
        "beat_local_consensus",
        "strong_timing_proof_count",
        "supporting_booster_count",
        "structural_concern",
        "final_class_assigned",
        "strong_risk_block_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _strong_risk_diagnostic_markdown(rows: list[dict[str, object]]) -> str:
    lines = [
        "# Strong Risk Near-Miss Diagnostic",
        "",
        "| Market | Wallet | Case type | Raw score before suppressors | Credibility gate | Opening exposure | Favorable repricing | Beat consensus | Strong timing proofs | Supporting boosters | Structural concern | Final class | Why not Strong Risk |",
        "| --- | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("market", "")).replace("|", "/"),
                    str(row.get("wallet", "")).replace("|", "/"),
                    str(row.get("case_type", "")).replace("|", "/"),
                    str(row.get("raw_score_before_suppressors", "")),
                    str(row.get("wallet_passed_credibility_gate", "")),
                    str(row.get("opening_exposure", "")),
                    str(row.get("favorable_repricing", "")),
                    str(row.get("beat_local_consensus", "")),
                    str(row.get("strong_timing_proof_count", "")),
                    str(row.get("supporting_booster_count", "")),
                    str(row.get("structural_concern", "")),
                    str(row.get("final_class_assigned", "")).replace("|", "/"),
                    str(row.get("strong_risk_block_reason", "")).replace("|", "/"),
                ]
            )
            + " |"
        )
    if len(lines) == 4:
        lines.append("| No near-miss cases were available. | | | | | | | | | | | | |")
    return "\n".join(lines) + "\n"


def _write_rollup_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not fieldnames:
            handle.write("")
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _wallet_rollups(
    scoped_trades: list[Trade],
    candidate_trades: list[Trade],
    flagged_cases: list[FlaggedCase],
    wallet_cache: dict[str, tuple[object, list[Trade], WalletPerformance]],
) -> list[dict[str, object]]:
    candidates_by_wallet = defaultdict(list)
    for trade in candidate_trades:
        candidates_by_wallet[trade.wallet].append(trade)
    flagged_by_wallet = defaultdict(list)
    for case in flagged_cases:
        flagged_by_wallet[case.trade.wallet].append(case)

    grouped = defaultdict(list)
    for trade in scoped_trades:
        grouped[trade.wallet].append(trade)

    rows: list[dict[str, object]] = []
    for wallet, trades in grouped.items():
        ordered = sorted(trades, key=lambda item: item.timestamp)
        buy_notional = sum((trade.notional for trade in trades if trade.side == "BUY"), Decimal("0"))
        sell_notional = sum((trade.notional for trade in trades if trade.side == "SELL"), Decimal("0"))
        wallet_inspection = None
        wallet_performance = None
        cached = wallet_cache.get(wallet)
        if cached is not None:
            wallet_inspection = cached[0]
            wallet_performance = cached[2]
        closed_summary = wallet_performance.closed_summary if wallet_performance is not None else None
        activity_summary = wallet_performance.activity_summary if wallet_performance is not None else None
        statistical_prior = compute_wallet_statistical_prior(closed_summary) if closed_summary is not None else None
        rows.append(
            {
                "wallet": wallet,
                "trade_count": len(trades),
                "candidate_trade_count": len(candidates_by_wallet.get(wallet, [])),
                "flagged_case_count": len(flagged_by_wallet.get(wallet, [])),
                "unique_market_count": len({trade.condition_id for trade in trades}),
                "domain_specialist_label": getattr(wallet_inspection, "dominant_domain_label", "Other"),
                "domain_concentration_score": f"{getattr(wallet_inspection, 'domain_concentration_score', 0.0):.2f}",
                "formal_win_rate": f"{closed_summary.win_rate_value:.1f}%" if closed_summary is not None else "",
                "economic_win_rate": (
                    f"{closed_summary.economic_win_rate_value:.1f}%" if closed_summary is not None else ""
                ),
                "wallet_statistical_prior_label": statistical_prior.label if statistical_prior is not None else "",
                "wallet_statistical_p_value": (
                    statistical_prior.to_raw_metrics()["wallet_statistical_p_value"]
                    if statistical_prior is not None
                    else ""
                ),
                "wallet_statistical_log_score": (
                    f"{statistical_prior.log_score:.2f}" if statistical_prior is not None else ""
                ),
                "wallet_resolved_sample_size": (
                    str(statistical_prior.resolved_sample_size) if statistical_prior is not None else ""
                ),
                "wallet_resolved_win_rate": (
                    f"{statistical_prior.resolved_win_rate_value:.1f}%" if statistical_prior is not None else ""
                ),
                "zombie_loss_count": str(closed_summary.zombie_loss_count) if closed_summary is not None else "",
                "bot_likeness_score": (
                    f"{activity_summary.bot_likeness_score:.1f}" if activity_summary is not None else ""
                ),
                "manual_review_value_score": (
                    f"{activity_summary.manual_review_value_score:.1f}" if activity_summary is not None else ""
                ),
                "buy_notional": str(buy_notional.quantize(Decimal("0.01"))),
                "sell_notional": str(sell_notional.quantize(Decimal("0.01"))),
                "total_notional": str((buy_notional + sell_notional).quantize(Decimal("0.01"))),
                "first_trade_at": ordered[0].timestamp.isoformat(),
                "last_trade_at": ordered[-1].timestamp.isoformat(),
            }
        )
    rows.sort(key=lambda item: Decimal(str(item["total_notional"])), reverse=True)
    return rows


def _market_rollups(
    scoped_trades: list[Trade],
    candidate_trades: list[Trade],
    flagged_cases: list[FlaggedCase],
    focus_markets: dict[str, Market],
) -> list[dict[str, object]]:
    candidates_by_market = defaultdict(list)
    for trade in candidate_trades:
        candidates_by_market[trade.condition_id].append(trade)
    flagged_by_market = defaultdict(list)
    for case in flagged_cases:
        flagged_by_market[case.trade.condition_id].append(case)

    grouped = defaultdict(list)
    for trade in scoped_trades:
        grouped[trade.condition_id].append(trade)

    rows: list[dict[str, object]] = []
    for condition_id, trades in grouped.items():
        ordered = sorted(trades, key=lambda item: item.timestamp)
        market = focus_markets.get(condition_id)
        total_notional = sum((trade.notional for trade in trades), Decimal("0"))
        rows.append(
            {
                "condition_id": condition_id,
                "market_title": ordered[0].title if ordered else "",
                "event_slug": ordered[0].event_slug if ordered else "",
                "trade_count": len(trades),
                "candidate_trade_count": len(candidates_by_market.get(condition_id, [])),
                "flagged_case_count": len(flagged_by_market.get(condition_id, [])),
                "unique_wallet_count": len({trade.wallet for trade in trades}),
                "total_notional": str(total_notional.quantize(Decimal("0.01"))),
                "first_trade_at": ordered[0].timestamp.isoformat(),
                "last_trade_at": ordered[-1].timestamp.isoformat(),
                "site_categories": ", ".join(market.site_categories) if market else "",
                "market_liquidity": str(market.liquidity.quantize(Decimal("0.01"))) if market else "0.00",
                "market_volume": str(market.volume.quantize(Decimal("0.01"))) if market else "0.00",
                "end_date": market.end_date if market else "",
            }
        )
    rows.sort(key=lambda item: Decimal(str(item["total_notional"])), reverse=True)
    return rows


def _to_markdown(report: dict[str, object]) -> str:
    lines = [
        "# InsPoly Archive Research Export",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Range start: {report['range_start']}",
        f"- Range end: {report['range_end']}",
        f"- Range hours: {report['range_hours']}",
        f"- Topic scope: {report['topic_scope']}",
        f"- Raw trades loaded: {report['raw_trade_count']}",
        f"- Focus-category trades after filter: {report['filtered_trade_count']}",
        f"- Candidate trades after size filter: {report['candidate_trade_count']}",
        f"- Unique wallets: {report['unique_wallet_count']}",
        f"- Unique markets: {report['unique_market_count']}",
        f"- Markets that may be truncated by API pagination limits: {report.get('truncated_market_count', 0)}",
        f"- Flagged cases: {report['flagged_case_count']}",
        f"- Secondary review cases: {report.get('secondary_review_case_count', 0)}",
        "",
    ]
    funding_lines = _funding_availability_report_lines(report.get("funding_resolver_health"))
    if funding_lines:
        lines.extend(["## Funding Availability", ""])
        lines.extend(funding_lines)
        lines.append("")
        lines.append("## Export files")
    else:
        lines.append("## Export files")
    for label, value in (report.get("export_files") or {}).items():
        lines.append(f"- {label}: {value}")
    lines.extend(["", "## Top flagged cases"])
    for case in report["cases"][:25]:
        trade = case["trade"]
        lines.extend(
            [
                f"### [{case['severity']}] {trade['wallet']} on {trade['title']}",
                f"- Time: {trade['timestamp']}",
                f"- Position: {trade['side']} {trade['outcome']}",
                f"- Trade size: ${case['raw_metrics'].get('trade_notional_usdc', '0')}",
                f"- Score: {case['suspicion_score']}/100",
            ]
        )
        funding_quality = _suspicious_funding_quality_note(case.get("raw_metrics", {}))
        if funding_quality:
            lines.append(f"- Suspicious funding quality: {funding_quality}")
        for reason in case["explanation"][:4]:
            lines.append(f"  - {reason}")
        lines.append("")
    return "\n".join(lines)


def _suspicious_funding_quality_note(raw_metrics: object) -> str:
    if not isinstance(raw_metrics, dict):
        return ""
    quality = str(raw_metrics.get("suspiciousFundingQuality") or "").strip()
    if not quality or quality in {"none", "unknown"}:
        return ""
    reasons = _text_values(raw_metrics.get("suspiciousFundingQualityReasons"))
    support_sources = _text_values(raw_metrics.get("suspiciousFundingIndependentSupportSources"))
    suppressor_reasons = _text_values(raw_metrics.get("suspiciousFundingSuppressorConflictReasons"))
    parts = [quality]
    if reasons:
        parts.append(reasons[0])
    if support_sources:
        parts.append("support=" + ", ".join(support_sources))
    if suppressor_reasons:
        parts.append("suppressors=" + ", ".join(suppressor_reasons))
    return "; ".join(parts)


def _text_values(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return _text_values(parsed)
    separator = ";" if ";" in text else ","
    if separator in text:
        return [part.strip() for part in text.split(separator) if part.strip()]
    return [text]


def _to_text_report(report: dict[str, object]) -> str:
    lines = [
        "InsPoly Archive Researcher",
        f"Generated at: {report['generated_at']}",
        f"Range start: {report['range_start']}",
        f"Range end: {report['range_end']}",
        f"Range hours: {report['range_hours']}",
        f"Topic scope: {report['topic_scope']}",
        f"Trades loaded: {report['raw_trade_count']}",
        f"Focus-category trades after filter: {report['filtered_trade_count']}",
        f"Candidate trades after size filter: {report['candidate_trade_count']}",
        f"Unique wallets: {report['unique_wallet_count']}",
        f"Unique markets: {report['unique_market_count']}",
        f"Markets that may be truncated by API pagination limits: {report.get('truncated_market_count', 0)}",
        f"Flagged cases: {report['flagged_case_count']}",
        "",
        "Export files:",
    ]
    funding_lines = _funding_availability_report_lines(report.get("funding_resolver_health"))
    if funding_lines:
        lines.extend(["", "Funding availability:"])
        lines.extend(funding_lines)
        lines.append("")
    for label, value in (report.get("export_files") or {}).items():
        lines.append(f"- {label}: {value}")

    top_wallets = report.get("wallet_rollups_top") or []
    if top_wallets:
        lines.extend(["", "Top wallets by archive notional:"])
        for row in top_wallets[:10]:
            lines.append(
                f"- {row['wallet']}: ${row['total_notional']} across {row['trade_count']} trades "
                f"({row['flagged_case_count']} flagged)"
            )

    top_markets = report.get("market_rollups_top") or []
    if top_markets:
        lines.extend(["", "Top markets by archive notional:"])
        for row in top_markets[:10]:
            lines.append(
                f"- {row['market_title']}: ${row['total_notional']} across {row['trade_count']} trades "
                f"from {row['unique_wallet_count']} wallets"
            )

    lines.extend(["", "Top flagged cases:"])
    if report["cases"]:
        for case in report["cases"][:20]:
            trade = case["trade"]
            lines.append(
                f"- [{case['severity']}] {trade['timestamp']} | {trade['wallet']} | "
                f"{trade['side']} {trade['outcome']} | ${case['raw_metrics'].get('trade_notional_usdc', '0')} | "
                f"{trade['title']}"
            )
    else:
        lines.append("- No flagged cases in this archive window.")

    return "\n".join(lines)
