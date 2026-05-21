from __future__ import annotations

import json
import csv
import tempfile
import os
import sqlite3
import subprocess
import threading
import unittest
from concurrent.futures import Future
from io import BytesIO
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from app.config import AppConfig, load_runtime_env
from app.event_context import EventContext
from app.event_forensic_desktop import EventForensicBrowserApp
from app.event_forensic import (
    EventForensicAnalyzer,
    ResolvedEvent,
    _annotate_wallet_domain_diversity,
    _candidate_audit_json_payload,
    _candidate_audit_markdown,
    _candidate_audit_rows,
    _extract_polymarket_resource_kind,
    _event_forensic_score,
    _event_judgment,
    _evidence_warnings,
    _group_model_gap_items,
    _model_gap_summary_text,
    _primary_suspicious_wallet_rows,
    _resolve_analysis_scope_context,
    _resolve_selected_child_market,
    _scope_filter_trades,
    _scope_filter_wallet_history_trades,
    _source_trade_payloads_for_wallet_details,
    _trade_summary,
    _visible_trade_payloads,
    _wallet_review_domain_counts,
    _wallet_trade_replay_metrics,
)
from app.funding_context import (
    FUNDING_EVIDENCE_UNKNOWN,
    TRANSFER_EVENT_TOPIC,
    FundingContext,
    FundingResolver,
    FundingTransfer,
    FundingTracePersistentCache,
    grade_funding_evidence,
    unknown_funding_context,
)
from app.models import FlaggedCase, Market, Trade, WalletInspection
from app.archive_scanner import _visibility_tier_for_case, _write_flagged_csv
from app.archive_scanner import _to_markdown as _archive_to_markdown
from app.polymarket import PolymarketClient, polygon_rpc_urls
from app.scanner import (
    HARD_EVIDENCE_REVIEW_TIER,
    SUSPICIOUS_FUNDING_QUALITY_MODERATE,
    SUSPICIOUS_FUNDING_QUALITY_STRONG,
    SUSPICIOUS_FUNDING_QUALITY_UNKNOWN,
    SUSPICIOUS_FUNDING_QUALITY_WEAK,
    STRUCTURAL_PRE_ADMISSION_MAX_FLOOR_USD,
    STRUCTURAL_PRE_ADMISSION_FLOOR_USD,
    _annotate_hard_evidence_review,
    _annotate_shared_funding_links,
    _apply_candidate_admission_metadata,
    _build_candidate_trade_set,
    _build_structural_pre_admission_funnel,
    _build_structural_pre_admission_metadata,
    _capital_at_risk_usdc,
    _classify_execution_state,
    _event_family_key,
    _is_opening_exposure,
    _score_trade,
    _severity_from_score,
    _should_trace_funding,
    _finalize_structural_pre_admission_funnel,
    _funding_availability_report_lines,
    _structural_pre_admission_floor,
    _structural_pre_admission_funnel_markdown,
    _structural_pre_admission_prefunding_pool,
    _suspicious_funding_quality_metrics,
    _validate_candidate_admissions,
)
from app.wallet_analytics import (
    ActivitySummary,
    ClosedPositionSummary,
    OpenPositionSummary,
    WalletPerformance,
)
from tools.ai_case_reviewer import (
    ReviewInputError,
    _trade_reducers,
    build_case_packets,
    discover_latest_event_forensic_run,
    review_case_packet,
    review_event_outputs,
    review_latest_outputs,
)
from tools.model_behavior_audit import (
    audit_records,
    collect_funnels,
    normalize_record,
    write_audit_outputs,
)
from tools.funding_resolver_healthcheck import (
    classify_rpc_health,
    mask_rpc_url,
    render_markdown,
    run_healthcheck,
)
from tools.replay_suspicious_funding_quality import replay_records


def _trade(
    *,
    trade_id: str,
    wallet: str,
    condition_id: str,
    asset_id: str,
    timestamp: datetime,
    price: str,
    size: str,
    title: str,
    slug: str,
    event_slug: str,
    side: str = "BUY",
    outcome: str = "YES",
) -> Trade:
    return Trade(
        trade_id=trade_id,
        condition_id=condition_id,
        asset_id=asset_id,
        wallet=wallet,
        side=side,
        outcome=outcome,
        price=Decimal(price),
        size=Decimal(size),
        timestamp=timestamp,
        title=title,
        slug=slug,
        event_slug=event_slug,
    )


def _market(*, condition_id: str, slug: str, question: str, liquidity: str = "20000") -> Market:
    return Market(
        market_id=f"market-{condition_id}",
        condition_id=condition_id,
        slug=slug,
        question=question,
        category="Politics",
        end_date=datetime(2026, 4, 8, tzinfo=UTC).isoformat(),
        liquidity=Decimal(liquidity),
        volume=Decimal("60000"),
        outcomes=["YES", "NO"],
        token_ids=["yes", "no"],
        tags=[],
        site_categories=["Middle East"],
    )


def _wallet_inspection(trade_count: int) -> WalletInspection:
    return WalletInspection(
        address="0xwallet",
        polygon_nonce=12,
        traded_market_count=trade_count,
        recent_trade_count=trade_count,
        unique_market_count=trade_count,
        focus_market_count=trade_count,
        first_trade_at=datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        last_trade_at=datetime(2026, 4, 7, tzinfo=UTC).isoformat(),
        dominant_domain_label="Middle East",
        domain_concentration_score=0.95,
        public_model_specialist_flag=False,
        domain_counts={"Middle East": trade_count},
        notes=[],
    )


def _wallet_performance() -> WalletPerformance:
    return WalletPerformance(
        closed_positions=[],
        closed_summary=ClosedPositionSummary(
            total=0,
            wins=0,
            losses=0,
            win_rate_value=0.0,
            win_rate_threshold=50.0,
            win_rate_clears_threshold=False,
            total_realized_pnl=0.0,
            average_return=0.0,
            economic_sample_size=0,
            economic_win_rate_value=0.0,
            economic_win_rate_threshold=50.0,
            economic_win_rate_clears_threshold=False,
            zombie_loss_count=0,
            zombie_loss_notional=0.0,
            redemption_avoidance_ratio=0.0,
            de_facto_loss_count=0,
            formal_win_rate_may_be_overstated=False,
        ),
        open_summary=OpenPositionSummary(
            count=0,
            notional=0.0,
            unrealized_pnl=0.0,
            unrealized_pct=0.0,
            zombie_positions=0,
            zombie_notional=0.0,
        ),
        activity_summary=ActivitySummary(
            bot_likeness_score=5.0,
            microtrade_ratio=0.0,
            median_trade_size=2500.0,
            trade_burst_rate=0.0,
            median_intertrade_interval_minutes=1440.0,
            market_breadth=4,
            manual_review_value_score=85.0,
            low_analyst_value_flag=False,
        ),
    )


def _event_context() -> EventContext:
    return EventContext(
        trade_domain="Middle East",
        event_timezone="Asia/Tehran",
        local_event_time="2026-04-07T19:00+03:30",
        local_event_hour=19,
        off_hours_flag=False,
        market_deadline_flag=True,
        matched_offline_row=False,
    )


def _flagged_case(*, trade: Trade, market: Market, raw_metrics: dict[str, str], flags: list[str]) -> FlaggedCase:
    return FlaggedCase(
        severity="Worth a Look",
        case_type=None,
        suspicion_score=42,
        confidence_score=80,
        review_priority="Medium",
        verdict="Needs manual review.",
        trade_count_window=1,
        window_start=trade.timestamp.isoformat(),
        window_end=trade.timestamp.isoformat(),
        trade=trade,
        market=market,
        wallet_inspection=_wallet_inspection(4),
        subscores={"trade_state": 5, "timing": 6, "size": 5, "wallet_behavior": 4, "benign_discount": 0},
        flags=flags,
        explanation=[],
        reasons_against=[],
        raw_metrics=raw_metrics,
    )


def _suspicious_funding_raw(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "suspicious_funding_flag": "Yes",
        "fundingEvidenceGrade": "suspicious_direct",
        "funding_evidence_grade": "suspicious_direct",
        "fundingResolverAvailable": "Yes",
        "fundingTraceSucceededCount": "1",
        "fundingTraceFailedCount": "0",
        "funding_tx_hash": "0xfunding",
        "funding_timestamp": "2026-04-07T11:00:00+00:00",
        "funding_amount_usdc": "2000.00",
        "funding_depth": "1",
        "funding_source_category": "unknown",
        "funding_origin_category": "unknown",
        "minutes_from_funding_to_trade": "60.0",
        "trade_notional_usdc": "1000.00",
        "opening_exposure_flag": "Yes",
        "trade_state": "increase",
        "price_implied_probability": "45.0",
        "stale_resolution_annotation": "No",
        "resolution_gap_flag": "No",
        "hard_public_information_flag": "No",
        "low_analyst_value_flag": "No",
        "bot_likeness_score": "10.0",
        "public_model_specialist_flag": "No",
        "wallet_recent_trade_count": "5",
        "wallet_focus_market_count": "1",
        "wallet_unique_market_count": "5",
        "wallet_closed_positions": "2",
        "shared_funding_source_flag": "No",
        "split_wallet_pattern_flag": "No",
        "cex_proxy_cluster_flag": "No",
        "reactivated_after_dormancy_flag": "No",
        "event_family_repeat_flag": "No",
        "coordinated_sizing_cluster_flag": "No",
    }
    raw.update(overrides)
    return raw


def _next_data_html(*, query_slug: list[str], event_payload: dict[str, object]) -> str:
    payload = {
        "props": {
            "pageProps": {
                "dehydratedState": {
                    "queries": [
                        {
                            "queryKey": ["/api/event/slug", event_payload["slug"]],
                            "state": {"data": event_payload},
                        }
                    ]
                }
            }
        },
        "query": {"slug": query_slug},
        "page": "/event/[...slug]",
    }
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script></body></html>"
    )


class ScannerPatternTests(unittest.TestCase):
    def _event_analyzer(self) -> EventForensicAnalyzer:
        return EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )

    def _benchmark_lite_records(self) -> list[dict[str, object]]:
        return [
            {
                "id": "strict-split-wallet",
                "severity": "Low Risk",
                "existingModelClass": "Low Risk",
                "visibility_tier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceSources": "split_wallet_pattern; strict_shared_funding_source",
                "hardEvidenceStrength": "Strong",
                "fundingEvidenceGrade": "direct_strict",
                "shared_funding_source_flag": "Yes",
                "funding_graph_key_strict": "0xstrict-funder",
                "cex_proxy_cluster_flag": "No",
                "condition_id": "cond-strict",
                "economic_direction": "long_yes",
                "opening_exposure_flag": "Yes",
                "repricingSourceQuality": "none",
            },
            {
                "id": "cex-proxy-only",
                "severity": "Low Risk",
                "existingModelClass": "Low Risk",
                "visibility_tier": "Secondary review",
                "hardEvidenceReviewTier": "",
                "hardEvidenceSources": "",
                "fundingEvidenceGrade": "cex_proxy",
                "cex_proxy_cluster_flag": "Yes",
                "funding_graph_key_proxy": "binance|day|2500-5000",
                "shared_funding_source_flag": "Yes",
                "opening_exposure_flag": "Yes",
                "repricingSourceQuality": "none",
            },
            {
                "id": "cex-plus-dormant",
                "severity": "Low Risk",
                "existingModelClass": "Low Risk",
                "visibility_tier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceSources": "dormant_wallet_reactivation",
                "hardEvidenceStrength": "Moderate",
                "fundingEvidenceGrade": "cex_proxy",
                "cex_proxy_cluster_flag": "Yes",
                "reactivated_after_dormancy_flag": "Yes",
                "opening_exposure_flag": "Yes",
                "repricingSourceQuality": "none",
            },
            {
                "id": "high-impact-repricing-only",
                "severity": "Low Risk",
                "existingModelClass": "Low Risk",
                "hardEvidenceReviewTier": "",
                "hardEvidenceSources": "",
                "fundingEvidenceGrade": "none",
                "favorable_repricing_flag": "Yes",
                "eventForensicFlags": "post_entry_repricing; high_impact_timing_or_repricing",
                "repricingSourceQuality": "strong",
                "eventForensicScore": 48,
            },
            {
                "id": "mechanical-repricing",
                "severity": "Low Risk",
                "existingModelClass": "Low Risk",
                "hardEvidenceReviewTier": "",
                "hardEvidenceSources": "",
                "fundingEvidenceGrade": "none",
                "favorable_repricing_flag": "Yes",
                "eventForensicFlags": "post_entry_repricing; high_impact_timing_or_repricing",
                "repricingSourceQuality": "mechanical",
                "repricing_driver_trade_count": 1,
                "repricing_driver_wallet_count": 1,
                "repricing_driven_by_single_wallet": "Yes",
            },
            {
                "id": "weak-repricing",
                "severity": "Low Risk",
                "existingModelClass": "Low Risk",
                "hardEvidenceReviewTier": "",
                "hardEvidenceSources": "",
                "fundingEvidenceGrade": "none",
                "favorable_repricing_flag": "Yes",
                "eventForensicFlags": "post_entry_repricing; high_impact_timing_or_repricing",
                "repricingSourceQuality": "weak",
                "eventForensicScore": 39,
                "eventForensicReducers": "repricing source quality weak; high-impact-only cap",
            },
            {
                "id": "strong-repricing-quality",
                "severity": "Low Risk",
                "existingModelClass": "Low Risk",
                "hardEvidenceReviewTier": "",
                "hardEvidenceSources": "",
                "fundingEvidenceGrade": "none",
                "favorable_repricing_flag": "Yes",
                "eventForensicFlags": "post_entry_repricing; high_impact_timing_or_repricing",
                "repricingSourceQuality": "strong",
                "eventForensicScore": 48,
                "repricing_driver_trade_count": 4,
                "repricing_driver_wallet_count": 4,
            },
            {
                "id": "near-certainty-split",
                "severity": "Low Risk",
                "existingModelClass": "Low Risk",
                "visibility_tier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceSources": "split_wallet_pattern",
                "hardEvidenceStrength": "Strong",
                "fundingEvidenceGrade": "direct_strict",
                "funding_graph_key_strict": "0xstrict-near",
                "cex_proxy_cluster_flag": "No",
                "eventForensicFlags": "near_certainty_trade",
                "opening_exposure_flag": "Yes",
                "repricingSourceQuality": "none",
            },
            {
                "id": "high-volume-public-no-hard",
                "severity": "Low Risk",
                "existingModelClass": "Low Risk",
                "walletPrimaryReviewStatus": "context_only_high_volume_public_user",
                "hardEvidenceReviewTier": "",
                "hardEvidenceSources": "",
                "fundingEvidenceGrade": "none",
                "caseInterpretationClass": "high_volume_public_power_user",
                "eventForensicReducers": "high_volume_public_user context-only demotion",
                "repricingSourceQuality": "none",
            },
            {
                "id": "high-volume-public-strict",
                "severity": "Low Risk",
                "existingModelClass": "Low Risk",
                "visibility_tier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceSources": "strict_shared_funding_source",
                "hardEvidenceStrength": "Moderate",
                "fundingEvidenceGrade": "direct_strict",
                "shared_funding_source_flag": "Yes",
                "funding_graph_key_strict": "0xstrict-power",
                "cex_proxy_cluster_flag": "No",
                "caseInterpretationClass": "high_volume_public_power_user",
                "eventForensicReducers": "high_volume_public_user ambiguity remains",
                "repricingSourceQuality": "none",
            },
        ]

    def _power_user_payloads(
        self,
        *,
        wallet: str = "0xpower",
        count: int = 30,
        winning_count: int = 15,
        score: int = 82,
        total_predictions: int = 320,
        shared_funding_cluster_size: int = 0,
        split_wallet: bool = False,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for index in range(count):
            rows.append(
                {
                    "id": f"{wallet}-{index}",
                    "wallet": wallet,
                    "walletShort": f"{wallet[:6]}...{wallet[-4:]}",
                    "profileUrl": f"https://polymarket.com/profile/{wallet}",
                    "username": "Not available",
                    "eventForensicScore": score,
                    "laterWon": index < winning_count,
                    "openingExposure": True,
                    "relatedMarketTrades": 0,
                    "price": 0.62,
                    "winnerRank": 12,
                    "conditionId": f"cond-{index % 4}",
                    "selectedConditionId": "cond-selected",
                    "selectedMarketSlug": "february-28",
                    "selectedMarketTitle": "February 28",
                    "parentEventSlug": "us-strikes-iran",
                    "rawMetrics": {
                        "wallet_total_predictions": str(total_predictions),
                        "wallet_recent_trade_count": str(total_predictions),
                        "wallet_unique_market_count": "80",
                        "shared_funding_source_flag": "Yes" if shared_funding_cluster_size else "No",
                        "shared_funding_source_cluster_size": str(shared_funding_cluster_size),
                        "shared_funding_source_wallet_count": str(shared_funding_cluster_size),
                        "funding_graph_key_strict": "0xstrict-funder" if shared_funding_cluster_size else "",
                        "cex_proxy_cluster_flag": "No",
                        "specialist_explained_flag": "No",
                        "low_analyst_value_flag": "No",
                        "formal_win_rate_may_be_overstated": "No",
                        "reactivated_after_dormancy_flag": "No",
                        "post_trade_dormancy_flag": "No",
                        "event_family_repeat_flag": "No",
                        "split_wallet_pattern_flag": "Yes" if split_wallet else "No",
                        "suspicious_funding_flag": "No",
                        "beat_consensus_flag": "No",
                        "favorable_repricing_flag": "No",
                    },
                }
            )
        return rows

    def _write_case_reviewer_fixture(
        self,
        root: Path,
        *,
        wallet: str = "0xpower",
        username: str = "operationcastle",
        trade_count: int = 30,
        winning_count: int = 15,
        wallet_event_trade_count: str = "30",
        wallet_notable_trade_count: str = "30",
        wallet_opening_count: str = "20",
        wallet_winning_count: str = "15",
        total_predictions: str = "320",
        wallet_score: str | None = None,
        insider_style_wallet_score: str | None = None,
        hard_evidence: bool = False,
        summary_counts: dict[str, int] | None = None,
    ) -> Path:
        event_analysis_path = root / "event_analysis.json"
        trades_path = root / "suspicious_trades.csv"
        wallets_path = root / "wallet_context.csv"
        clusters_path = root / "wallet_clusters.csv"
        graph_path = root / "wallet_graph.json"
        model_gap_path = root / "model_gap_report.md"
        raw_dir = root / "raw_event_bundle"
        raw_dir.mkdir(exist_ok=True)

        summary = summary_counts or {
            "raw_trade_count": trade_count,
            "candidate_trade_count": trade_count,
            "forensic_suspicious_trade_count": trade_count,
        }
        event_analysis_path.write_text(
            json.dumps(
                {
                    "event": {"title": "Reviewer fixture event", "slug": "reviewer-fixture"},
                    "analysis_scope": "event",
                    "summary": summary,
                    "export_files": {
                        "suspicious_trades_csv_path": str(trades_path),
                        "wallet_context_csv_path": str(wallets_path),
                        "wallet_clusters_csv_path": str(clusters_path),
                        "wallet_graph_json_path": str(graph_path),
                        "model_gap_report_md_path": str(model_gap_path),
                        "raw_event_bundle_dir": str(raw_dir),
                    },
                }
            ),
            encoding="utf-8",
        )

        trade_fields = [
            "id",
            "wallet",
            "username",
            "market",
            "timestamp",
            "eventForensicScore",
            "openingExposure",
            "laterWon",
            "eventForensicFlags",
            "eventForensicReducers",
            "summary",
        ]
        with trades_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=trade_fields)
            writer.writeheader()
            for index in range(trade_count):
                writer.writerow(
                    {
                        "id": f"trade-{index}",
                        "wallet": wallet,
                        "username": username,
                        "market": f"Market {index % 4}",
                        "timestamp": f"2026-04-30T12:{index % 60:02d}:00+00:00",
                        "eventForensicScore": "82",
                        "openingExposure": "True",
                        "laterWon": "True" if index < winning_count else "False",
                        "eventForensicFlags": "split_wallet;shared_funder" if hard_evidence else "",
                        "eventForensicReducers": "",
                        "summary": "High-volume winning entry",
                    }
                )

        wallet_fields = [
            "wallet",
            "username",
            "walletScore",
            "insiderStyleWalletScore",
            "eventTradeCount",
            "suspiciousTradeCount",
            "walletTotalPredictions",
            "walletOpeningEntryCount",
            "walletWinningOpeningEntryCount",
            "walletPublicPowerUserFlag",
            "walletHighVolumeEventUserFlag",
            "walletEventSaturationFlag",
            "independentHardEvidenceFlag",
            "walletQualityStatus",
            "botStatus",
            "specialistStatus",
            "fundingFlags",
            "summary",
        ]
        with wallets_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=wallet_fields)
            writer.writeheader()
            writer.writerow(
                {
                    "wallet": wallet,
                    "username": username,
                    "walletScore": wallet_score if wallet_score is not None else ("35" if not hard_evidence else "78"),
                    "insiderStyleWalletScore": (
                        insider_style_wallet_score
                        if insider_style_wallet_score is not None
                        else ("0" if not hard_evidence else "74")
                    ),
                    "eventTradeCount": wallet_event_trade_count,
                    "suspiciousTradeCount": wallet_notable_trade_count,
                    "walletTotalPredictions": total_predictions,
                    "walletOpeningEntryCount": wallet_opening_count,
                    "walletWinningOpeningEntryCount": wallet_winning_count,
                    "walletPublicPowerUserFlag": "True",
                    "walletHighVolumeEventUserFlag": "True",
                    "walletEventSaturationFlag": "True",
                    "independentHardEvidenceFlag": "True" if hard_evidence else "False",
                    "walletQualityStatus": "No weak-history gate",
                    "botStatus": "Not clearly bot-like",
                    "specialistStatus": "Not clearly specialist",
                    "fundingFlags": "Shared direct funder" if hard_evidence else "No shared-funder signal",
                    "summary": "High-volume public participant with split-wallet evidence." if hard_evidence else "High-volume public participant reducer applied.",
                }
            )
        clusters_path.write_text("id,walletCount,clusterScore\n", encoding="utf-8")
        graph_path.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
        model_gap_path.write_text("# Model gap\n", encoding="utf-8")
        return event_analysis_path

    def test_resolve_selected_child_market_prefers_exact_condition_id(self) -> None:
        first = _market(
            condition_id="cond-a",
            slug="february-27",
            question="February 27",
        )
        second = _market(
            condition_id="cond-b",
            slug="february-28",
            question="February 28",
        )

        selected = _resolve_selected_child_market(
            {"cond-a": first, "cond-b": second},
            selected_condition_id="cond-b",
            selected_market_slug="february-27",
        )

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.condition_id, "cond-b")
        self.assertEqual(selected.slug, "february-28")

    def test_scope_filter_trades_uses_exact_condition_id(self) -> None:
        base_time = datetime(2026, 2, 27, 12, 0, tzinfo=UTC)
        trades = [
            _trade(
                trade_id="trade-a",
                wallet="0x1",
                condition_id="cond-a",
                asset_id="asset-a",
                timestamp=base_time,
                price="0.12",
                size="1000",
                title="February 27",
                slug="february-27",
                event_slug="us-strikes-iran",
            ),
            _trade(
                trade_id="trade-b",
                wallet="0x2",
                condition_id="cond-b",
                asset_id="asset-b",
                timestamp=base_time + timedelta(minutes=5),
                price="0.14",
                size="2000",
                title="February 28",
                slug="february-28",
                event_slug="us-strikes-iran",
            ),
        ]

        scoped = _scope_filter_trades(trades, selected_condition_id="cond-b")

        self.assertEqual([trade.trade_id for trade in scoped], ["trade-b"])

    def test_scope_filter_wallet_history_removes_sibling_event_trades_only(self) -> None:
        base_time = datetime(2026, 2, 27, 12, 0, tzinfo=UTC)
        selected_trade = _trade(
            trade_id="selected",
            wallet="0xwallet",
            condition_id="cond-selected",
            asset_id="asset-selected",
            timestamp=base_time,
            price="0.20",
            size="3000",
            title="February 28",
            slug="february-28",
            event_slug="us-strikes-iran",
        )
        sibling_trade = _trade(
            trade_id="sibling",
            wallet="0xwallet",
            condition_id="cond-sibling",
            asset_id="asset-sibling",
            timestamp=base_time - timedelta(hours=1),
            price="0.22",
            size="2500",
            title="February 27",
            slug="february-27",
            event_slug="us-strikes-iran",
        )
        external_trade = _trade(
            trade_id="external",
            wallet="0xwallet",
            condition_id="cond-external",
            asset_id="asset-external",
            timestamp=base_time - timedelta(days=2),
            price="0.18",
            size="1500",
            title="External thesis",
            slug="external-thesis",
            event_slug="another-event",
        )

        scoped_history = _scope_filter_wallet_history_trades(
            [selected_trade, sibling_trade, external_trade],
            all_event_condition_ids={"cond-selected", "cond-sibling"},
            selected_condition_id="cond-selected",
        )

        self.assertEqual([trade.trade_id for trade in scoped_history], ["selected", "external"])

    def test_market_scope_wallet_ranking_excludes_related_market_boost(self) -> None:
        analyzer = EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )
        trade_payloads = [
            {
                "id": "trade-1",
                "wallet": "0xwallet",
                "walletShort": "0xwall...let",
                "profileUrl": "https://polymarket.com/profile/0xwallet",
                "username": "Not available",
                "eventForensicScore": 50,
                "laterWon": False,
                "openingExposure": True,
                "relatedMarketTrades": 2,
                "selectedConditionId": "cond-selected",
                "selectedMarketSlug": "february-28",
                "selectedMarketTitle": "February 28",
                "parentEventSlug": "us-strikes-iran",
                "rawMetrics": {
                    "shared_funding_source_flag": "No",
                    "specialist_explained_flag": "No",
                    "low_analyst_value_flag": "No",
                    "formal_win_rate_may_be_overstated": "No",
                    "reactivated_after_dormancy_flag": "No",
                    "post_trade_dormancy_flag": "No",
                    "event_family_repeat_flag": "No",
                    "split_wallet_pattern_flag": "No",
                },
            }
        ]
        related_rows = [
            {"wallet": "0xwallet", "market": "Outside event A"},
            {"wallet": "0xwallet", "market": "Outside event B"},
        ]

        event_rows = analyzer._build_wallet_rankings(
            trade_payloads,
            related_rows,
            analysis_scope="event",
            sibling_market_activity={},
        )
        market_rows = analyzer._build_wallet_rankings(
            trade_payloads,
            related_rows,
            analysis_scope="market",
            sibling_market_activity={"0xwallet": {"otherEventMarketTrades": 4, "siblingMarketActivityCount": 2}},
        )

        self.assertGreater(event_rows[0]["walletScore"], market_rows[0]["walletScore"])
        self.assertEqual(market_rows[0]["otherEventMarketTrades"], 4)
        self.assertIn("excluded from the primary wallet score", market_rows[0]["summary"])

    def test_wallet_ranking_surfaces_statistical_prior_without_score_boost(self) -> None:
        analyzer = EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )
        trade_payloads = [
            {
                "id": "trade-1",
                "wallet": "0xwallet",
                "walletShort": "0xwall...let",
                "profileUrl": "https://polymarket.com/profile/0xwallet",
                "username": "Not available",
                "eventForensicScore": 50,
                "laterWon": False,
                "openingExposure": True,
                "relatedMarketTrades": 0,
                "selectedConditionId": "cond-selected",
                "selectedMarketSlug": "february-28",
                "selectedMarketTitle": "February 28",
                "parentEventSlug": "us-strikes-iran",
                "rawMetrics": {
                    "shared_funding_source_flag": "No",
                    "specialist_explained_flag": "No",
                    "low_analyst_value_flag": "No",
                    "formal_win_rate_may_be_overstated": "No",
                    "reactivated_after_dormancy_flag": "No",
                    "post_trade_dormancy_flag": "No",
                    "event_family_repeat_flag": "No",
                    "split_wallet_pattern_flag": "No",
                    "wallet_statistical_prior_label": "meaningful_statistical_prior",
                    "wallet_statistical_p_value": "0.000977",
                    "wallet_statistical_log_score": "3.01",
                    "wallet_resolved_sample_size": "10",
                    "wallet_resolved_win_rate": "100.0%",
                    "wallet_statistical_prior_note": (
                        "Unusual resolved win history, context only: not event-specific proof."
                    ),
                },
            }
        ]

        rows = analyzer._build_wallet_rankings(
            trade_payloads,
            [],
            analysis_scope="event",
            sibling_market_activity={},
        )

        self.assertEqual(rows[0]["walletScore"], 55)
        self.assertEqual(rows[0]["walletStatisticalPriorLabel"], "meaningful_statistical_prior")
        self.assertEqual(rows[0]["walletResolvedSampleSize"], "10")
        self.assertIn("context only", rows[0]["summary"])
        self.assertIn("not event-specific proof", rows[0]["summary"])

    def test_high_volume_winning_wallet_without_hard_evidence_is_capped_and_context_only(self) -> None:
        rows = self._event_analyzer()._build_wallet_rankings(
            self._power_user_payloads(),
            [],
            analysis_scope="event",
            sibling_market_activity={},
        )

        power_row = rows[0]
        self.assertTrue(power_row["walletPublicPowerUserFlag"])
        self.assertTrue(power_row["walletHighVolumeEventUserFlag"])
        self.assertTrue(power_row["walletEventSaturationFlag"])
        self.assertFalse(power_row["independentHardEvidenceFlag"])
        self.assertLessEqual(power_row["walletScore"], 35)
        self.assertEqual(power_row["walletPublicPowerUserStatus"], "public_power_user_demoted")
        self.assertEqual(power_row["walletPrimaryReviewStatus"], "context_only_high_volume_public_user")
        self.assertEqual(power_row["caseInterpretationClass"], "high_volume_public_power_user")
        self.assertNotIn(power_row["wallet"], [row["wallet"] for row in _primary_suspicious_wallet_rows(rows)])

    def test_acceptance_25_trade_public_power_user_is_not_top_high_concern_without_hard_evidence(self) -> None:
        rows = self._event_analyzer()._build_wallet_rankings(
            self._power_user_payloads(count=25, winning_count=15, score=95, total_predictions=320),
            [],
            analysis_scope="event",
            sibling_market_activity={},
        )

        power_row = rows[0]
        self.assertTrue(power_row["walletPublicPowerUserFlag"])
        self.assertTrue(power_row["walletHighVolumeEventUserFlag"])
        self.assertFalse(power_row["walletEventSaturationFlag"])
        self.assertFalse(power_row["independentHardEvidenceFlag"])
        self.assertLessEqual(power_row["walletScore"], 40)
        self.assertLessEqual(power_row["insiderStyleWalletScore"], 40)
        self.assertEqual(power_row["walletPrimaryReviewStatus"], "context_only_high_volume_public_user")
        self.assertNotIn(power_row["wallet"], [row["wallet"] for row in _primary_suspicious_wallet_rows(rows)])

    def test_high_volume_wallet_with_hard_linkage_is_not_capped_too_aggressively(self) -> None:
        rows = self._event_analyzer()._build_wallet_rankings(
            self._power_user_payloads(shared_funding_cluster_size=3, split_wallet=True),
            [],
            analysis_scope="event",
            sibling_market_activity={},
        )

        power_row = rows[0]
        self.assertTrue(power_row["walletPublicPowerUserFlag"])
        self.assertTrue(power_row["walletEventSaturationFlag"])
        self.assertTrue(power_row["independentHardEvidenceFlag"])
        self.assertEqual(power_row["walletHardEvidenceSources"], ["split_wallet_pattern", "strict_shared_funding_source"])
        self.assertEqual(power_row["hardEvidenceReviewTier"], HARD_EVIDENCE_REVIEW_TIER)
        self.assertNotEqual(power_row.get("hardEvidenceReviewTier"), "Strong Risk")
        self.assertIn("shared_funding_cluster_size", power_row["walletEvidenceSourceFlags"])
        self.assertIn("shared_funding_cluster_size=3", power_row["walletHardEvidenceSourceDetails"])
        self.assertGreaterEqual(power_row["walletScore"], 70)
        self.assertFalse(power_row["walletPublicPowerUserReducerApplied"])
        self.assertEqual(power_row["walletPrimaryReviewStatus"], "primary_allowed")
        self.assertIn(power_row["wallet"], [row["wallet"] for row in _primary_suspicious_wallet_rows(rows)])

    def test_event_saturation_wallet_does_not_outrank_primary_insider_style_wallet(self) -> None:
        saturated = self._power_user_payloads(wallet="0xsaturated", score=92, total_predictions=350)
        focused = self._power_user_payloads(
            wallet="0xfocused",
            count=2,
            winning_count=1,
            score=74,
            total_predictions=12,
            shared_funding_cluster_size=3,
        )

        rows = self._event_analyzer()._build_wallet_rankings(
            saturated + focused,
            [],
            analysis_scope="event",
            sibling_market_activity={},
        )
        primary = _primary_suspicious_wallet_rows(rows)

        self.assertEqual(primary[0]["wallet"], "0xfocused")
        self.assertNotIn("0xsaturated", [row["wallet"] for row in primary])
        self.assertLessEqual(next(row for row in rows if row["wallet"] == "0xsaturated")["walletScore"], 35)

    def test_public_prediction_count_over_100_sets_power_user_flag(self) -> None:
        rows = self._event_analyzer()._build_wallet_rankings(
            self._power_user_payloads(count=1, winning_count=0, score=44, total_predictions=101),
            [],
            analysis_scope="event",
            sibling_market_activity={},
        )

        self.assertTrue(rows[0]["walletPublicPowerUserFlag"])
        self.assertEqual(rows[0]["walletPublicPowerUserStatus"], "public_power_user_demoted")

    def test_mistky_style_public_power_user_is_context_only_without_hard_evidence(self) -> None:
        rows = self._event_analyzer()._build_wallet_rankings(
            self._power_user_payloads(
                wallet="0xmistky",
                count=38,
                winning_count=23,
                score=96,
                total_predictions=436,
            ),
            [{"wallet": "0xmistky", "market": "Related A"} for _ in range(3)],
            analysis_scope="market",
            sibling_market_activity={"0xmistky": {"otherEventMarketTrades": 107, "siblingMarketActivityCount": 3}},
        )

        row = rows[0]
        self.assertTrue(row["walletPublicPowerUserFlag"])
        self.assertTrue(row["walletHighVolumeEventUserFlag"])
        self.assertTrue(row["walletEventSaturationFlag"])
        self.assertFalse(row["independentHardEvidenceFlag"])
        self.assertEqual(row["caseInterpretationClass"], "high_volume_public_power_user")
        self.assertEqual(row["walletPrimaryReviewStatus"], "context_only_high_volume_public_user")
        self.assertLessEqual(row["walletScore"], 40)
        self.assertLessEqual(row["insiderStyleWalletScore"], 40)
        self.assertEqual(row["walletTotalPredictions"], 436)
        self.assertEqual(row["walletLoadedEventTradeCount"], 38)
        self.assertEqual(row["walletWinningOpeningEntryCount"], 23)
        self.assertEqual(row["otherEventMarketTrades"], 107)
        self.assertNotIn("0xmistky", [item["wallet"] for item in _primary_suspicious_wallet_rows(rows)])

    def test_high_volume_repricing_with_unavailable_liquidity_is_not_hard_evidence(self) -> None:
        payloads = self._power_user_payloads(
            wallet="0xmistky",
            count=38,
            winning_count=23,
            score=96,
            total_predictions=436,
        )
        for payload in payloads:
            payload["rawMetrics"]["favorable_repricing_flag"] = "Yes"
            payload["rawMetrics"]["market_liquidity_usdc"] = "0.00"
            payload["rawMetrics"]["liquidity_ratio"] = "Unavailable"

        rows = self._event_analyzer()._build_wallet_rankings(
            payloads,
            [],
            analysis_scope="event",
            sibling_market_activity={"0xmistky": {"otherEventMarketTrades": 107, "siblingMarketActivityCount": 3}},
        )

        row = rows[0]
        self.assertFalse(row["independentHardEvidenceFlag"])
        self.assertEqual(row["walletPrimaryReviewStatus"], "context_only_high_volume_public_user")
        self.assertEqual(row["caseInterpretationClass"], "high_volume_public_power_user")
        self.assertNotIn("0xmistky", [item["wallet"] for item in _primary_suspicious_wallet_rows(rows)])

    def test_high_impact_repricing_wallet_details_explain_trigger(self) -> None:
        payloads = self._power_user_payloads(
            wallet="0xedge",
            count=1,
            winning_count=0,
            score=46,
            total_predictions=1,
        )
        payloads[0]["rawMetrics"].update(
            {
                "favorable_repricing_flag": "Yes",
                "market_liquidity_usdc": "221944.52",
                "liquidity_ratio": "20.74%",
                "favorable_move_1h": "0.10",
                "favorable_move_24h": "0.16",
                "liquidity_shock_signal": "Yes",
                "public_information_state": "No Public Lag Concern",
                "repricing_source_quality": "weak",
                "repricing_source_quality_reasons": "limited supporting market activity",
            }
        )

        row = self._event_analyzer()._build_wallet_rankings(
            payloads,
            [],
            analysis_scope="event",
            sibling_market_activity={},
        )[0]

        self.assertFalse(row["independentHardEvidenceFlag"])
        self.assertEqual(row["walletHardEvidenceSources"], [])
        self.assertEqual(row["hardEvidenceReviewTier"], "")
        self.assertIn("high_impact_timing_or_repricing", row["walletEvidenceSourceFlags"])
        detail = " ".join(row["walletHardEvidenceSourceDetails"])
        self.assertIn("reason=large_liquidity_share", detail)
        self.assertIn("trigger=post_entry_repricing", detail)
        self.assertIn("trade_id=0xedge-0", detail)
        self.assertIn("condition_id=cond-0", detail)
        self.assertIn("liquidity_ratio=20.74%", detail)
        self.assertIn("market_liquidity_usdc=221944.52", detail)
        self.assertIn("favorable_move_1h=0.10", detail)
        self.assertIn("favorable_move_24h=0.16", detail)
        self.assertEqual(row["repricingSourceQuality"], "weak")
        self.assertIn("limited supporting market activity", row["repricingSourceQualityReasons"])

    def test_event_trade_ranking_prefers_hard_evidence_over_high_impact_only(self) -> None:
        analyzer = self._event_analyzer()
        hard = {
            "id": "hard",
            "wallet": "0xhard",
            "eventForensicScore": 28,
            "existingModelScore": 16,
            "laterWon": False,
            "positionSize": 1200.0,
            "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
            "finalEventJudgment": "Likely contextual or benign",
        }
        high_impact_only = {
            "id": "high-impact",
            "wallet": "0ximpact",
            "eventForensicScore": 72,
            "existingModelScore": 38,
            "laterWon": False,
            "positionSize": 8000.0,
            "hardEvidenceReviewTier": "",
            "finalEventJudgment": "High event-forensic concern",
        }

        ranked = analyzer._ranked_trade_rows([high_impact_only, hard])

        self.assertEqual([item["id"] for item in ranked], ["hard", "high-impact"])

    def test_wallet_context_export_includes_power_user_fields(self) -> None:
        analyzer = self._event_analyzer()
        wallet_row = analyzer._build_wallet_rankings(
            self._power_user_payloads(shared_funding_cluster_size=3, split_wallet=True),
            [],
            analysis_scope="event",
            sibling_market_activity={},
        )[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports_dir = root / "reports"
            reports_dir.mkdir()
            analyzer._config = AppConfig(
                data_dir=root,
                db_path=root / "ignored.sqlite3",
                reports_dir=reports_dir,
                outputs_dir=root / "outputs",
            )
            exports = analyzer._write_report_bundle(
                datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
                reports_dir,
                {
                    "status": "completed",
                    "event_report_markdown": "",
                    "model_gap_markdown": "",
                    "performance": {},
                    "summary": {},
                    "analysis_settings": {},
                    "event": {},
                },
                suspicious_trades=[],
                suspicious_wallets=[],
                ranked_wallets=[wallet_row],
                wallet_clusters=[],
                wallet_graph={"nodes": [], "edges": []},
                related_markets=[],
                candidate_audit_rows=[],
                raw_bundle={},
            )

            self.assertIn("wallet_context_csv_path", exports)
            with Path(exports["wallet_context_csv_path"]).open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertIn("walletPublicPowerUserFlag", reader.fieldnames or [])
                self.assertIn("walletEventSaturationFlag", reader.fieldnames or [])
                self.assertIn("walletHardEvidenceSources", reader.fieldnames or [])
                self.assertIn("walletEvidenceSourceFlags", reader.fieldnames or [])
                self.assertIn("walletHardEvidenceSourceDetails", reader.fieldnames or [])
                self.assertIn("hardEvidenceSources", reader.fieldnames or [])
                self.assertIn("hardEvidenceReviewTier", reader.fieldnames or [])
                self.assertIn("repricingSourceQuality", reader.fieldnames or [])
                self.assertIn("repricingSourceQualityReasons", reader.fieldnames or [])
                rows = list(reader)
            self.assertEqual(rows[0]["wallet"], "0xpower")
            self.assertEqual(rows[0]["walletPublicPowerUserFlag"], "True")
            self.assertIn("split_wallet_pattern", rows[0]["walletHardEvidenceSources"])
            self.assertIn("strict_shared_funding_source", rows[0]["walletHardEvidenceSources"])
            self.assertIn("shared_funding_cluster_size=3", rows[0]["walletHardEvidenceSourceDetails"])

    def test_ai_case_reviewer_writes_outputs_without_auto_code_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_analysis_path = root / "event_analysis.json"
            trades_path = root / "suspicious_trades.csv"
            wallets_path = root / "suspicious_wallets.csv"
            clusters_path = root / "wallet_clusters.csv"
            graph_path = root / "wallet_graph.json"
            model_gap_path = root / "model_gap_report.md"
            output_dir = root / "ai_review_outputs"

            event_analysis_path.write_text(
                json.dumps(
                    {
                        "event": {"title": "Test event"},
                        "analysis_scope": "event",
                        "export_files": {
                            "suspicious_trades_csv_path": str(trades_path),
                            "suspicious_wallets_csv_path": str(wallets_path),
                            "wallet_clusters_csv_path": str(clusters_path),
                            "wallet_graph_json_path": str(graph_path),
                            "model_gap_report_md_path": str(model_gap_path),
                            "raw_event_bundle_dir": str(root / "raw_event_bundle"),
                        },
                    }
                ),
                encoding="utf-8",
            )
            trades_path.write_text(
                "wallet,eventForensicScore,eventForensicFlags,eventForensicReducers,summary\n"
                "0xpower,82,,,High-volume winning entry\n",
                encoding="utf-8",
            )
            wallets_path.write_text(
                "wallet,username,walletScore,insiderStyleWalletScore,eventTradeCount,suspiciousTradeCount,"
                "walletTotalPredictions,walletOpeningEntryCount,walletWinningOpeningEntryCount,"
                "walletPublicPowerUserFlag,walletHighVolumeEventUserFlag,walletEventSaturationFlag,"
                "independentHardEvidenceFlag,walletQualityStatus,botStatus,specialistStatus,fundingFlags,summary\n"
                "0xpower,operationcastle,35,0,30,30,320,20,15,True,True,True,False,"
                "No weak-history gate,Not clearly bot-like,Not clearly specialist,No shared-funder signal,"
                "High-volume public participant reducer applied.\n",
                encoding="utf-8",
            )
            clusters_path.write_text("id,walletCount,clusterScore\n", encoding="utf-8")
            graph_path.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
            model_gap_path.write_text("# Model gap\n", encoding="utf-8")

            outputs = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=output_dir,
                top_n=5,
            )

            cases_payload = json.loads(Path(outputs["cases_json_path"]).read_text(encoding="utf-8"))
            self.assertFalse(cases_payload["safety"]["production_code_modified"])
            self.assertFalse(cases_payload["safety"]["automatic_scoring_changes_applied"])
            self.assertEqual(cases_payload["reviews"][0]["review_verdict"], "likely_false_positive")
            self.assertFalse(cases_payload["reviews"][0]["automatic_code_change_allowed"])
            model_notes = Path(outputs["model_changes_md_path"]).read_text(encoding="utf-8")
            self.assertIn("does not edit production code", model_notes)
            self.assertIn("operationcastle", model_notes)
            self.assertIn("event_trade_count: 30", model_notes)
            self.assertIn("Proposed deterministic fix", model_notes)

    def test_ai_case_reviewer_marks_bot_specialist_without_hard_evidence_as_advisory(self) -> None:
        packet = {
            "case_id": "wallet-1-0xbot",
            "case_type": "wallet",
            "supporting_evidence": {"independent_hard_evidence": False},
            "reducers": {
                "bot_like": True,
                "specialist": True,
                "high_volume_public_user": False,
                "event_saturation": False,
            },
            "event_activity": {"event_trade_count": 4},
            "relevant_trades": [{"eventForensicScore": 42}],
        }

        review = review_case_packet(packet)

        self.assertEqual(review["review_verdict"], "ambiguous")
        self.assertEqual(review["interpretation_class"], "bot_or_low_analyst_value")
        self.assertFalse(review["automatic_code_change_allowed"])
        self.assertIn("advisory/ambiguous", review["recommended_test_fixture"][0])

        high_volume_packet = {
            **packet,
            "reducers": {
                **packet["reducers"],
                "high_volume_public_user": True,
                "event_saturation": True,
            },
            "event_activity": {"event_trade_count": 30},
        }
        high_volume_review = review_case_packet(high_volume_packet)
        self.assertEqual(high_volume_review["review_verdict"], "likely_false_positive")
        self.assertEqual(high_volume_review["interpretation_class"], "high_volume_public_power_user")

    def test_ai_case_reviewer_displays_suspicious_funding_quality_without_production_verdict_change(self) -> None:
        weak_packet = {
            "case_id": "wallet-weak-funding",
            "case_type": "wallet",
            "supporting_evidence": {
                "independent_hard_evidence": False,
                "suspicious_funding": True,
                "suspicious_funding_quality": "weak",
                "suspicious_funding_quality_reasons": [
                    "weak multi-hop funding without trade alignment",
                ],
                "suspicious_funding_hard_evidence_eligible": False,
                "suspicious_funding_suppressor_conflict": True,
                "suspicious_funding_suppressor_conflict_reasons": ["high_volume_public_user"],
            },
            "reducers": {"high_volume_public_user": True, "event_saturation": True},
            "event_activity": {"event_trade_count": 30},
            "relevant_trades": [{"eventForensicScore": 42}],
        }
        strong_packet = {
            **weak_packet,
            "case_id": "wallet-strong-funding",
            "supporting_evidence": {
                "independent_hard_evidence": True,
                "suspicious_funding": True,
                "suspicious_funding_quality": "strong",
                "suspicious_funding_quality_reasons": [
                    "recent direct suspicious funding with amount alignment and opening exposure",
                ],
                "suspicious_funding_hard_evidence_eligible": True,
                "hard_evidence_sources": ["suspicious_recent_funding"],
            },
            "reducers": {"high_volume_public_user": False, "event_saturation": False},
            "event_activity": {"event_trade_count": 1},
        }

        weak_review = review_case_packet(weak_packet)
        strong_review = review_case_packet(strong_packet)

        self.assertEqual(weak_review["review_verdict"], "likely_false_positive")
        self.assertIn("Suspicious funding quality is `weak`", " ".join(weak_review["evidence_that_weakens_concern"]))
        self.assertIn("Suppressor conflict", " ".join(weak_review["evidence_that_weakens_concern"]))
        self.assertEqual(strong_review["review_verdict"], "plausible_insider_style")
        self.assertIn("Suspicious funding quality is `strong`", " ".join(strong_review["evidence_that_supports_concern"]))
        self.assertFalse(strong_review["automatic_code_change_allowed"])

    def test_ai_case_reviewer_marks_stale_deadline_reducers_without_hard_evidence_as_advisory(self) -> None:
        reducers = _trade_reducers(
            {
                "eventForensicReducers": [
                    "The entry also fits a standard deadline-decay pattern.",
                    "This looks more like public information that the market absorbed slowly than like a private-information trade.",
                    "The entry resembles near-certain capital parking more than a directional information edge.",
                ]
            }
        )
        self.assertTrue(reducers["theta_decay"])
        self.assertTrue(reducers["yield_farm"])
        self.assertTrue(reducers["resolution_gap"])

        packet = {
            "case_id": "trade-1-0xtheta",
            "case_type": "trade",
            "supporting_evidence": {
                "independent_hard_evidence": False,
                "beat_consensus": True,
                "favorable_repricing": True,
            },
            "reducers": reducers,
            "event_activity": {"event_trade_count": 1},
            "relevant_trades": [{"eventForensicScore": 40}],
        }

        review = review_case_packet(packet)

        self.assertEqual(review["review_verdict"], "ambiguous")
        self.assertEqual(review["interpretation_class"], "stale_or_resolution_gap")
        self.assertFalse(review["automatic_code_change_allowed"])
        self.assertIn("advisory/ambiguous", review["recommended_test_fixture"][0])

        hard_evidence_packet = {
            **packet,
            "supporting_evidence": {
                "independent_hard_evidence": True,
                "low_probability_winner": True,
                "hard_evidence_sources": ["low-probability winning entry"],
            },
        }
        hard_evidence_review = review_case_packet(hard_evidence_packet)
        self.assertEqual(hard_evidence_review["review_verdict"], "plausible_insider_style")
        self.assertEqual(hard_evidence_review["interpretation_class"], "insider_style_candidate")

    def test_ai_case_reviewer_latest_discovery_ignores_incomplete_newer_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs_dir = Path(tmp) / "event_forensic_outputs"
            valid = outputs_dir / "event_forensic_20260430_120000"
            incomplete = outputs_dir / "event_forensic_20260430_130000"
            valid.mkdir(parents=True)
            incomplete.mkdir(parents=True)
            (valid / "event_analysis.json").write_text(
                json.dumps({"summary": {"raw_trade_count": 0, "candidate_trade_count": 0}}),
                encoding="utf-8",
            )
            os.utime(valid, (1000, 1000))
            os.utime(incomplete, (2000, 2000))

            self.assertEqual(discover_latest_event_forensic_run(outputs_dir), valid)

        with tempfile.TemporaryDirectory() as tmp:
            outputs_dir = Path(tmp) / "event_forensic_outputs"
            (outputs_dir / "event_forensic_20260430_130000").mkdir(parents=True)
            with self.assertRaises(ReviewInputError):
                discover_latest_event_forensic_run(outputs_dir)

    def test_ai_case_reviewer_rejects_bad_event_analysis_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ReviewInputError, "placeholder"):
                review_event_outputs(event_analysis_json_path=Path("path/to/event_analysis.json"))
            with self.assertRaisesRegex(ReviewInputError, "does not exist"):
                review_event_outputs(event_analysis_json_path=root / "missing_event_analysis.json")
            invalid = root / "event_analysis.json"
            invalid.write_text("{not-json", encoding="utf-8")
            with self.assertRaisesRegex(ReviewInputError, "Invalid JSON"):
                review_event_outputs(event_analysis_json_path=invalid)

    def test_ai_case_reviewer_latest_runs_newest_valid_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs_dir = root / "event_forensic_outputs"
            old = outputs_dir / "event_forensic_20260430_120000"
            new = outputs_dir / "event_forensic_20260430_130000"
            old.mkdir(parents=True)
            new.mkdir(parents=True)
            self._write_case_reviewer_fixture(old, username="old-user")
            self._write_case_reviewer_fixture(new, username="new-user")
            os.utime(old, (1000, 1000))
            os.utime(new, (2000, 2000))

            outputs = review_latest_outputs(
                event_forensic_outputs_dir=outputs_dir,
                output_dir=root / "ai_review_outputs",
                top_n=3,
            )

            self.assertEqual(outputs["detected_input_dir"], str(new))
            self.assertTrue(Path(outputs["review_report_md_path"]).exists())

    def test_ai_case_reviewer_keeps_back_to_back_outputs_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "tools.ai_case_reviewer._review_timestamp",
            return_value="20260430_120000",
        ):
            root = Path(tmp)
            event_analysis_path = self._write_case_reviewer_fixture(root)
            output_dir = root / "ai_review_outputs"

            first = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=output_dir,
                top_n=3,
            )
            second = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=output_dir,
                top_n=3,
            )

            self.assertNotEqual(first["cases_json_path"], second["cases_json_path"])
            self.assertNotEqual(first["review_report_md_path"], second["review_report_md_path"])
            self.assertTrue(Path(first["cases_json_path"]).exists())
            self.assertTrue(Path(second["cases_json_path"]).exists())
            self.assertTrue(Path(second["cases_json_path"]).name.endswith("_2.json"))

    def test_ai_case_reviewer_derives_activity_counts_from_relevant_trades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_analysis_path = self._write_case_reviewer_fixture(
                root,
                username="ciro2",
                trade_count=27,
                winning_count=25,
                wallet_event_trade_count="",
                wallet_notable_trade_count="",
                wallet_opening_count="",
                wallet_winning_count="",
            )

            outputs = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=root / "ai_review_outputs",
                top_n=3,
            )
            payload = json.loads(Path(outputs["cases_json_path"]).read_text(encoding="utf-8"))
            wallet_packet = next(item for item in payload["case_packets"] if item["case_type"] == "wallet")

            self.assertEqual(wallet_packet["username"], "ciro2")
            self.assertEqual(wallet_packet["event_activity"]["event_trade_count"], 27)
            self.assertEqual(wallet_packet["event_activity"]["notable_trade_count"], 27)
            self.assertEqual(wallet_packet["event_activity"]["opening_entry_count"], 27)
            self.assertEqual(wallet_packet["event_activity"]["winning_opening_entry_count"], 25)
            self.assertEqual(payload["reviews"][0]["review_verdict"], "likely_false_positive")

    def test_ai_case_reviewer_flags_high_score_zero_insider_power_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_analysis_path = self._write_case_reviewer_fixture(
                root,
                username="ciro2",
                trade_count=27,
                winning_count=27,
                wallet_event_trade_count="27",
                wallet_notable_trade_count="25",
                wallet_opening_count="27",
                wallet_winning_count="27",
                wallet_score="100",
                insider_style_wallet_score="0",
                hard_evidence=False,
            )

            outputs = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=root / "ai_review_outputs",
                top_n=3,
            )
            payload = json.loads(Path(outputs["cases_json_path"]).read_text(encoding="utf-8"))
            wallet_review = next(item for item in payload["reviews"] if str(item["case_id"]).startswith("wallet-"))
            report_text = Path(outputs["review_report_md_path"]).read_text(encoding="utf-8")

            self.assertEqual(wallet_review["review_verdict"], "likely_false_positive")
            self.assertEqual(wallet_review["interpretation_class"], "high_volume_public_power_user")
            self.assertGreaterEqual(wallet_review["confidence"], 0.75)
            self.assertIn("high generic wallet score but zero insider-style score", report_text)
            self.assertIn("High volume and repeated wins appear without independent hard evidence", report_text)

    def test_ai_case_reviewer_merges_suspicious_wallet_and_context_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_analysis_path = self._write_case_reviewer_fixture(
                root,
                trade_count=3,
                winning_count=2,
                wallet_event_trade_count="0",
                wallet_notable_trade_count="0",
                wallet_opening_count="0",
                wallet_winning_count="0",
            )
            event_analysis = json.loads(event_analysis_path.read_text(encoding="utf-8"))
            suspicious_wallets = root / "suspicious_wallets.csv"
            event_analysis["export_files"]["suspicious_wallets_csv_path"] = str(suspicious_wallets)
            event_analysis_path.write_text(json.dumps(event_analysis), encoding="utf-8")
            suspicious_wallets.write_text(
                "wallet,username,walletScore,insiderStyleWalletScore,eventTradeCount,suspiciousTradeCount,"
                "walletOpeningEntryCount,walletWinningOpeningEntryCount,walletUniqueEventMarketsTraded,"
                "walletPublicPowerUserFlag,walletHighVolumeEventUserFlag,walletEventSaturationFlag,"
                "independentHardEvidenceFlag,summary\n"
                "0xpower,operationcastle,100,0,25,25,25,25,4,True,True,True,False,"
                "Suspicious wallet export has non-zero activity counts.\n",
                encoding="utf-8",
            )

            outputs = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=root / "ai_review_outputs",
                top_n=3,
            )
            payload = json.loads(Path(outputs["cases_json_path"]).read_text(encoding="utf-8"))
            wallet_packet = next(item for item in payload["case_packets"] if item["case_type"] == "wallet")

            self.assertEqual(wallet_packet["event_activity"]["event_trade_count"], 25)
            self.assertEqual(wallet_packet["event_activity"]["notable_trade_count"], 25)
            self.assertEqual(wallet_packet["event_activity"]["opening_entry_count"], 25)
            self.assertEqual(wallet_packet["event_activity"]["winning_opening_entry_count"], 25)
            self.assertEqual(wallet_packet["event_activity"]["unique_event_markets_traded"], 4)

    def test_ai_case_reviewer_merges_rich_embedded_trade_evidence_without_raw_dump(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_analysis_path = self._write_case_reviewer_fixture(
                root,
                wallet_event_trade_count="",
                wallet_notable_trade_count="",
                wallet_opening_count="",
                wallet_winning_count="",
            )
            event_analysis = json.loads(event_analysis_path.read_text(encoding="utf-8"))
            event_analysis["display_trades"] = [
                {
                    "id": "trade-0",
                    "wallet": "0xpower",
                    "username": "operationcastle",
                    "market": "Market 0",
                    "timestamp": "2026-04-30T12:00:00+00:00",
                    "eventForensicScore": 82,
                    "openingExposure": True,
                    "laterWon": True,
                    "eventForensicFlags": ["opening_exposure", "post_entry_repricing"],
                    "rawMetrics": {
                        "favorable_repricing_flag": "Yes",
                        "market_liquidity_usdc": "50000",
                        "liquidity_ratio": "6.0",
                    },
                    "summary": "Embedded report row carries richer forensic evidence than the CSV export.",
                }
            ]
            event_analysis_path.write_text(json.dumps(event_analysis), encoding="utf-8")

            outputs = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=root / "ai_review_outputs",
                top_n=3,
            )
            payload = json.loads(Path(outputs["cases_json_path"]).read_text(encoding="utf-8"))
            wallet_packet = next(item for item in payload["case_packets"] if item["case_type"] == "wallet")
            first_trade = wallet_packet["relevant_trades"][0]

            self.assertIn("post_entry_repricing", first_trade["eventForensicFlags"])
            self.assertIn("high-impact timing/repricing edge", first_trade["hardEvidenceSources"])
            self.assertNotIn("rawMetrics", first_trade)
            self.assertTrue(wallet_packet["supporting_evidence"]["favorable_repricing"])
            self.assertIn("high-impact timing/repricing edge", wallet_packet["supporting_evidence"]["hard_evidence_sources"])

    def test_ai_case_reviewer_preserves_hard_evidence_escape_hatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_analysis_path = self._write_case_reviewer_fixture(
                root,
                username="linked-power-user",
                hard_evidence=True,
            )

            outputs = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=root / "ai_review_outputs",
                top_n=3,
            )
            payload = json.loads(Path(outputs["cases_json_path"]).read_text(encoding="utf-8"))
            wallet_review = next(item for item in payload["reviews"] if str(item["case_id"]).startswith("wallet-"))

            self.assertEqual(wallet_review["review_verdict"], "plausible_insider_style")
            self.assertIn(wallet_review["interpretation_class"], {"cluster_or_linkage_case", "insider_style_candidate"})

    def test_ai_case_reviewer_adds_under_ranked_hard_evidence_wallets_beyond_top_slice(self) -> None:
        packets = build_case_packets(
            event_analysis={"event": {"title": "Hard evidence event", "slug": "hard-evidence-event"}},
            trade_rows=[
                {
                    "id": "hard-trade",
                    "wallet": "0xhard",
                    "username": "quiet-wallet",
                    "market": "Low probability market",
                    "eventForensicScore": 28,
                    "openingExposure": True,
                    "laterWon": True,
                    "price": 0.22,
                    "winnerRank": 3,
                    "eventForensicFlags": ["dormant_reactivation", "low_probability_winner"],
                    "summary": "Dormant wallet reactivated for a low-probability winning entry.",
                }
            ],
            wallet_rows=[
                {
                    "wallet": "0xtop",
                    "username": "top-wallet",
                    "walletScore": 90,
                    "insiderStyleWalletScore": 90,
                    "eventTradeCount": 3,
                    "suspiciousTradeCount": 3,
                    "independentHardEvidenceFlag": False,
                    "summary": "Top ranked wallet.",
                },
                {
                    "wallet": "0xhard",
                    "username": "quiet-wallet",
                    "walletScore": 32,
                    "insiderStyleWalletScore": 32,
                    "eventTradeCount": 1,
                    "suspiciousTradeCount": 0,
                    "independentHardEvidenceFlag": True,
                    "walletPrimaryReviewStatus": "primary_allowed",
                    "summary": "Saved hard evidence but no primary trade cleared the threshold.",
                },
            ],
            cluster_rows=[],
            top_n=1,
        )

        wallet_packets = [packet for packet in packets if packet["case_type"] == "wallet"]
        hard_packet = next(packet for packet in wallet_packets if packet["wallet"] == "0xhard")
        hard_review = review_case_packet(hard_packet)

        self.assertEqual([packet["wallet"] for packet in wallet_packets], ["0xtop", "0xhard"])
        self.assertEqual(hard_packet["review_focus"], "under_ranked_hard_evidence_wallet")
        self.assertIn("low-probability winning entry", hard_packet["supporting_evidence"]["hard_evidence_sources"])
        self.assertEqual(hard_review["review_verdict"], "plausible_insider_style")
        self.assertIn("low rank", " ".join(hard_review["evidence_that_supports_concern"]))

    def test_ai_case_reviewer_uses_wallet_level_hard_evidence_sources_without_relevant_trades(self) -> None:
        packets = build_case_packets(
            event_analysis={"event": {"title": "Hard evidence event", "slug": "hard-evidence-event"}},
            trade_rows=[],
            wallet_rows=[
                {
                    "wallet": "0xtop",
                    "username": "top-wallet",
                    "walletScore": 90,
                    "insiderStyleWalletScore": 90,
                    "eventTradeCount": 3,
                    "suspiciousTradeCount": 3,
                    "independentHardEvidenceFlag": False,
                    "summary": "Top ranked wallet.",
                },
                {
                    "wallet": "0xquiet",
                    "username": "quiet-wallet",
                    "walletScore": 31,
                    "insiderStyleWalletScore": 31,
                    "eventTradeCount": 1,
                    "suspiciousTradeCount": 0,
                    "independentHardEvidenceFlag": True,
                    "walletPrimaryReviewStatus": "primary_allowed",
                    "walletHardEvidenceSources": ["split_wallet_pattern", "dormant_reactivation"],
                    "walletEvidenceSourceFlags": [
                        "split_wallet_pattern",
                        "dormant_reactivation",
                        "dormant_after_win",
                    ],
                    "walletHardEvidenceSourceDetails": ["dormant_reactivation_gap_days=132"],
                    "summary": "Saved hard evidence but no primary trade cleared the threshold.",
                },
            ],
            cluster_rows=[],
            top_n=1,
        )

        hard_packet = next(packet for packet in packets if packet.get("wallet") == "0xquiet")
        supporting = hard_packet["supporting_evidence"]
        hard_review = review_case_packet(hard_packet)

        self.assertEqual(hard_packet["review_focus"], "under_ranked_hard_evidence_wallet")
        self.assertEqual(supporting["hard_evidence_sources"], ["split_wallet_pattern", "dormant_reactivation"])
        self.assertNotIn("saved wallet hard-evidence flag", supporting["hard_evidence_sources"])
        self.assertIn("dormant_after_win", supporting["evidence_source_flags"])
        self.assertIn("dormant_reactivation_gap_days=132", supporting["hard_evidence_source_details"])
        self.assertIn("Concrete wallet evidence source flags", " ".join(hard_review["evidence_that_supports_concern"]))

    def test_ai_case_reviewer_preserves_high_impact_source_details_without_relevant_trades(self) -> None:
        detail = (
            "high_impact_timing_or_repricing, reason=large_liquidity_share, "
            "trigger=post_entry_repricing, trade_id=trade-1, condition_id=cond-1, "
            "liquidity_ratio=20.74%, market_liquidity_usdc=221944.52"
        )
        packets = build_case_packets(
            event_analysis={"event": {"title": "High impact event", "slug": "high-impact-event"}},
            trade_rows=[],
            wallet_rows=[
                {
                    "wallet": "0xtop",
                    "username": "top-wallet",
                    "walletScore": 90,
                    "insiderStyleWalletScore": 90,
                    "eventTradeCount": 3,
                    "suspiciousTradeCount": 3,
                    "independentHardEvidenceFlag": False,
                    "summary": "Top ranked wallet.",
                },
                {
                    "wallet": "0xhighimpact",
                    "username": "high-impact-wallet",
                    "walletScore": 31,
                    "insiderStyleWalletScore": 31,
                    "eventTradeCount": 1,
                    "suspiciousTradeCount": 0,
                    "independentHardEvidenceFlag": True,
                    "walletPrimaryReviewStatus": "primary_allowed",
                    "walletHardEvidenceSources": ["high_impact_timing_or_repricing"],
                    "walletEvidenceSourceFlags": [
                        "post_entry_repricing",
                        "high_impact_timing_or_repricing",
                    ],
                    "walletHardEvidenceSourceDetails": [detail],
                    "summary": "Saved hard evidence but no primary trade cleared the threshold.",
                },
            ],
            cluster_rows=[],
            top_n=1,
        )

        hard_packet = next(packet for packet in packets if packet.get("wallet") == "0xhighimpact")
        supporting = hard_packet["supporting_evidence"]
        hard_review = review_case_packet(hard_packet)

        self.assertEqual(hard_packet["review_focus"], "under_ranked_hard_evidence_wallet")
        self.assertEqual(supporting["hard_evidence_sources"], ["high_impact_timing_or_repricing"])
        self.assertNotIn("saved wallet hard-evidence flag", supporting["hard_evidence_sources"])
        self.assertTrue(supporting["favorable_repricing"])
        self.assertIn(detail, supporting["hard_evidence_source_details"])
        self.assertEqual(supporting["high_impact_source_quality"], "weak")
        self.assertEqual(hard_review["review_verdict"], "ambiguous")
        self.assertIn("source quality", " ".join(hard_review["evidence_that_weakens_concern"]))

    def test_event_forensic_selects_enriched_high_impact_source_trade_payloads(self) -> None:
        source_detail = (
            "high_impact_timing_or_repricing, reason=large_liquidity_share, "
            "trigger=post_entry_repricing, trade_id=source-trade-1, condition_id=cond-1"
        )
        source_trade = {
            "id": "source-trade-1",
            "wallet": "0xhighimpact",
            "conditionId": "cond-1",
            "eventForensicScore": 34,
            "openingExposure": True,
            "eventForensicFlags": ["opening_exposure", "post_entry_repricing"],
            "eventForensicReducers": ["near_certainty_entry"],
            "rawMetrics": {
                "favorable_repricing_flag": "Yes",
                "liquidity_ratio": "20.74%",
            },
        }
        unrelated_trade = {
            "id": "unrelated-trade",
            "wallet": "0xother",
            "conditionId": "cond-2",
            "eventForensicScore": 70,
            "openingExposure": True,
            "rawMetrics": {"favorable_repricing_flag": "Yes"},
        }

        source_rows = _source_trade_payloads_for_wallet_details(
            [unrelated_trade, source_trade],
            [
                {
                    "wallet": "0xhighimpact",
                    "walletHardEvidenceSourceDetails": [source_detail],
                }
            ],
        )

        self.assertEqual(source_rows, [source_trade])
        self.assertEqual(source_rows[0]["eventForensicFlags"], ["opening_exposure", "post_entry_repricing"])
        self.assertEqual(source_rows[0]["eventForensicReducers"], ["near_certainty_entry"])
        self.assertEqual(source_rows[0]["rawMetrics"]["liquidity_ratio"], "20.74%")

    def test_ai_case_reviewer_attaches_raw_bundle_high_impact_source_trade_rows(self) -> None:
        detail = (
            "high_impact_timing_or_repricing, reason=large_liquidity_share, "
            "trigger=post_entry_repricing, trade_id=source-trade-1, condition_id=cond-1, "
            "liquidity_ratio=20.74%, market_liquidity_usdc=94663.44, "
            "public_information_state=No Public Lag Concern, offline_timeline_matched=No"
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_bundle = root / "raw_event_bundle"
            raw_bundle.mkdir()
            (raw_bundle / "trades.json").write_text(
                json.dumps(
                    [
                        {
                            "trade_id": "source-trade-1",
                            "wallet": "0xhighimpact",
                            "condition_id": "cond-1",
                            "timestamp": "2026-05-01T10:00:00+00:00",
                            "title": "Thin repricing market",
                            "side": "BUY",
                            "outcome": "No",
                            "price": "0.46",
                            "size": "9000",
                            "trader_name": "source-user",
                            "trader_pseudonym": "Source-Pseudonym",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            event_analysis_path = root / "event_analysis.json"
            event_analysis_path.write_text(
                json.dumps(
                    {
                        "event": {"title": "High impact event", "slug": "high-impact-event"},
                        "summary": {
                            "raw_trade_count": 2,
                            "candidate_trade_count": 1,
                            "forensic_suspicious_trade_count": 1,
                        },
                        "display_trades": [
                            {
                                "id": "visible-trade",
                                "wallet": "0xtop",
                                "market": "Visible market",
                                "eventForensicScore": 70,
                            }
                        ],
                        "display_wallets": [
                            {
                                "wallet": "0xtop",
                                "username": "top-wallet",
                                "walletScore": 90,
                                "insiderStyleWalletScore": 90,
                                "eventTradeCount": 1,
                                "suspiciousTradeCount": 1,
                                "independentHardEvidenceFlag": False,
                                "summary": "Top ranked wallet.",
                            },
                            {
                                "wallet": "0xhighimpact",
                                "username": "high-impact-wallet",
                                "walletScore": 31,
                                "insiderStyleWalletScore": 31,
                                "eventTradeCount": 1,
                                "suspiciousTradeCount": 0,
                                "independentHardEvidenceFlag": True,
                                "walletPrimaryReviewStatus": "primary_allowed",
                                "walletHardEvidenceSources": ["high_impact_timing_or_repricing"],
                                "walletEvidenceSourceFlags": [
                                    "post_entry_repricing",
                                    "high_impact_timing_or_repricing",
                                ],
                                "walletHardEvidenceSourceDetails": [detail],
                                "summary": "Saved high-impact evidence but source trade is only in the raw bundle.",
                            },
                        ],
                        "export_files": {"raw_event_bundle_dir": str(raw_bundle)},
                    }
                ),
                encoding="utf-8",
            )

            outputs = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=root / "ai_review_outputs",
                top_n=1,
            )
            payload = json.loads(Path(outputs["cases_json_path"]).read_text(encoding="utf-8"))
            hard_packet = next(packet for packet in payload["case_packets"] if packet.get("wallet") == "0xhighimpact")
            supporting = hard_packet["supporting_evidence"]

            self.assertEqual(hard_packet["review_focus"], "under_ranked_hard_evidence_wallet")
            self.assertEqual(hard_packet["relevant_trades"], [])
            self.assertEqual(hard_packet["source_trades"][0]["id"], "source-trade-1")
            self.assertEqual(hard_packet["source_trades"][0]["source"], "raw_event_bundle")
            self.assertEqual(hard_packet["source_trades"][0]["conditionId"], "cond-1")
            self.assertEqual(hard_packet["source_trades"][0]["username"], "source-user (Source-Pseudonym)")
            self.assertEqual(supporting["high_impact_source_trade_rows_available"], 1)
            self.assertEqual(supporting["high_impact_source_trade_rows_missing"], [])
            self.assertEqual(supporting["high_impact_source_quality"], "weak")
            self.assertIn(
                "raw event bundle but lacks reviewer opening-exposure context",
                " ".join(supporting["high_impact_source_quality_reasons"]),
            )

    def test_ai_case_reviewer_prefers_enriched_source_trade_rows(self) -> None:
        detail = (
            "high_impact_timing_or_repricing, reason=large_liquidity_share, "
            "trigger=post_entry_repricing, trade_id=source-trade-1, condition_id=cond-1, "
            "liquidity_ratio=20.74%, market_liquidity_usdc=94663.44, "
            "liquidity_shock_signal=Yes, public_information_state=No Public Lag Concern, "
            "offline_timeline_matched=No"
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_bundle = root / "raw_event_bundle"
            raw_bundle.mkdir()
            (raw_bundle / "trades.json").write_text(
                json.dumps(
                    [
                        {
                            "trade_id": "source-trade-1",
                            "wallet": "0xhighimpact",
                            "condition_id": "cond-1",
                            "timestamp": "2026-05-01T10:00:00+00:00",
                            "title": "Thin repricing market",
                            "side": "BUY",
                            "outcome": "No",
                            "price": "0.46",
                            "size": "9000",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (raw_bundle / "source_trades.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "source-trade-1",
                            "wallet": "0xhighimpact",
                            "username": "high-impact-wallet",
                            "conditionId": "cond-1",
                            "timestamp": "2026-05-01T10:00:00+00:00",
                            "market": "Thin repricing market",
                            "side": "No",
                            "orderSide": "BUY",
                            "price": 0.46,
                            "positionSize": 9000,
                            "openingExposure": True,
                            "eventForensicScore": 34,
                            "eventForensicFlags": ["opening_exposure", "post_entry_repricing"],
                            "eventForensicReducers": ["near_certainty_entry"],
                            "rawMetrics": {
                                "favorable_repricing_flag": "Yes",
                                "market_liquidity_usdc": "94663.44",
                                "liquidity_ratio": "20.74%",
                            },
                            "summary": "Enriched source trade exported from Event Forensic.",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            event_analysis_path = root / "event_analysis.json"
            event_analysis_path.write_text(
                json.dumps(
                    {
                        "event": {"title": "High impact event", "slug": "high-impact-event"},
                        "summary": {"raw_trade_count": 1, "candidate_trade_count": 1},
                        "display_trades": [
                            {
                                "id": "visible-trade",
                                "wallet": "0xtop",
                                "market": "Visible market",
                                "eventForensicScore": 70,
                            }
                        ],
                        "display_wallets": [
                            {
                                "wallet": "0xtop",
                                "username": "top-wallet",
                                "walletScore": 90,
                                "insiderStyleWalletScore": 90,
                                "eventTradeCount": 1,
                                "suspiciousTradeCount": 1,
                                "independentHardEvidenceFlag": False,
                                "summary": "Top ranked wallet.",
                            },
                            {
                                "wallet": "0xhighimpact",
                                "username": "high-impact-wallet",
                                "walletScore": 31,
                                "insiderStyleWalletScore": 31,
                                "eventTradeCount": 1,
                                "suspiciousTradeCount": 0,
                                "independentHardEvidenceFlag": True,
                                "walletPrimaryReviewStatus": "primary_allowed",
                                "walletHardEvidenceSources": ["high_impact_timing_or_repricing"],
                                "walletEvidenceSourceFlags": [
                                    "post_entry_repricing",
                                    "high_impact_timing_or_repricing",
                                ],
                                "walletHardEvidenceSourceDetails": [detail],
                                "summary": "Saved high-impact evidence with enriched source context.",
                            },
                        ],
                        "export_files": {"raw_event_bundle_dir": str(raw_bundle)},
                    }
                ),
                encoding="utf-8",
            )

            outputs = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=root / "ai_review_outputs",
                top_n=1,
            )
            payload = json.loads(Path(outputs["cases_json_path"]).read_text(encoding="utf-8"))
            hard_packet = next(packet for packet in payload["case_packets"] if packet.get("wallet") == "0xhighimpact")
            source_trade = hard_packet["source_trades"][0]
            supporting = hard_packet["supporting_evidence"]

            self.assertEqual(source_trade["source"], "raw_event_bundle")
            self.assertTrue(source_trade["openingExposure"])
            self.assertEqual(source_trade["eventForensicScore"], 34)
            self.assertEqual(source_trade["eventForensicFlags"], ["opening_exposure", "post_entry_repricing"])
            self.assertEqual(source_trade["eventForensicReducers"], ["near_certainty_entry"])
            self.assertEqual(source_trade["rawMetrics"]["market_liquidity_usdc"], "94663.44")
            self.assertEqual(supporting["high_impact_source_trade_rows_available"], 1)
            self.assertEqual(supporting["high_impact_source_trade_rows_missing"], [])
            self.assertEqual(supporting["high_impact_source_quality"], "mechanical")
            self.assertNotIn(
                "lacks reviewer opening-exposure context",
                " ".join(supporting["high_impact_source_quality_reasons"]),
            )

    def test_ai_case_reviewer_merges_enriched_source_row_when_trade_is_also_relevant(self) -> None:
        detail = (
            "high_impact_timing_or_repricing, reason=large_liquidity_share, "
            "trigger=post_entry_repricing, trade_id=source-trade-1, condition_id=cond-1, "
            "liquidity_ratio=20.74%, market_liquidity_usdc=94663.44, "
            "liquidity_shock_signal=Yes, public_information_state=No Public Lag Concern, "
            "offline_timeline_matched=No"
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_bundle = root / "raw_event_bundle"
            raw_bundle.mkdir()
            (raw_bundle / "source_trades.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "source-trade-1",
                            "wallet": "0xhighimpact",
                            "username": "high-impact-wallet",
                            "conditionId": "cond-1",
                            "timestamp": "2026-05-01T10:00:00+00:00",
                            "market": "Thin repricing market",
                            "side": "No",
                            "orderSide": "BUY",
                            "price": 0.46,
                            "positionSize": 9000,
                            "openingExposure": True,
                            "eventForensicScore": 0,
                            "eventForensicFlags": ["opening_exposure", "post_entry_repricing"],
                            "eventForensicReducers": ["near_certainty_entry"],
                            "rawMetrics": {
                                "favorable_repricing_flag": "Yes",
                                "market_liquidity_usdc": "94663.44",
                                "liquidity_ratio": "20.74%",
                            },
                            "summary": "Enriched source trade exported from Event Forensic.",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            event_analysis_path = root / "event_analysis.json"
            event_analysis_path.write_text(
                json.dumps(
                    {
                        "event": {"title": "High impact event", "slug": "high-impact-event"},
                        "summary": {"raw_trade_count": 1, "candidate_trade_count": 1},
                        "display_trades": [
                            {
                                "id": "source-trade-1",
                                "wallet": "0xhighimpact",
                                "username": "high-impact-wallet",
                                "conditionId": "cond-1",
                                "timestamp": "2026-05-01T10:00:00+00:00",
                                "market": "Thin repricing market",
                                "openingExposure": True,
                                "eventForensicScore": 0,
                                "eventForensicFlags": ["opening_exposure", "post_entry_repricing"],
                                "eventForensicReducers": ["near_certainty_entry"],
                                "summary": "Relevant row lacks rawMetrics.",
                            }
                        ],
                        "display_wallets": [
                            {
                                "wallet": "0xtop",
                                "username": "top-wallet",
                                "walletScore": 90,
                                "insiderStyleWalletScore": 90,
                                "eventTradeCount": 1,
                                "suspiciousTradeCount": 1,
                                "independentHardEvidenceFlag": False,
                                "summary": "Top ranked wallet.",
                            },
                            {
                                "wallet": "0xhighimpact",
                                "username": "high-impact-wallet",
                                "walletScore": 31,
                                "insiderStyleWalletScore": 31,
                                "eventTradeCount": 1,
                                "suspiciousTradeCount": 0,
                                "independentHardEvidenceFlag": True,
                                "walletPrimaryReviewStatus": "primary_allowed",
                                "walletHardEvidenceSources": ["high_impact_timing_or_repricing"],
                                "walletEvidenceSourceFlags": [
                                    "post_entry_repricing",
                                    "high_impact_timing_or_repricing",
                                ],
                                "walletHardEvidenceSourceDetails": [detail],
                                "summary": "Saved high-impact evidence with source trade also in relevant trades.",
                            },
                        ],
                        "export_files": {"raw_event_bundle_dir": str(raw_bundle)},
                    }
                ),
                encoding="utf-8",
            )

            outputs = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=root / "ai_review_outputs",
                top_n=1,
            )
            payload = json.loads(Path(outputs["cases_json_path"]).read_text(encoding="utf-8"))
            hard_packet = next(packet for packet in payload["case_packets"] if packet.get("wallet") == "0xhighimpact")
            source_trade = hard_packet["source_trades"][0]

            self.assertNotIn("rawMetrics", hard_packet["relevant_trades"][0])
            self.assertEqual(source_trade["source"], "reviewer_relevant_trades")
            self.assertEqual(source_trade["enrichedSource"], "raw_event_bundle")
            self.assertEqual(source_trade["eventForensicScore"], 0)
            self.assertEqual(source_trade["rawMetrics"]["market_liquidity_usdc"], "94663.44")

    def test_ai_case_reviewer_labels_public_news_thin_market_high_impact_as_advisory(self) -> None:
        detail = (
            "high_impact_timing_or_repricing, reason=large_liquidity_share, "
            "trigger=post_entry_repricing, trade_id=trade-1, condition_id=cond-1, "
            "liquidity_ratio=22.18%, market_liquidity_usdc=94663.44, "
            "liquidity_shock_signal=Yes, public_information_state=No Public Lag Concern, "
            "offline_timeline_matched=No"
        )
        packets = build_case_packets(
            event_analysis={"event": {"title": "High impact event", "slug": "high-impact-event"}},
            trade_rows=[
                {
                    "id": "trade-1",
                    "wallet": "0xhighimpact",
                    "username": "high-impact-wallet",
                    "conditionId": "cond-1",
                    "market": "Thin repricing market",
                    "eventForensicScore": 34,
                    "openingExposure": True,
                    "laterWon": True,
                    "price": 0.45,
                    "eventForensicFlags": ["post_entry_repricing"],
                    "summary": "Opening entry repriced in a thin market.",
                }
            ],
            wallet_rows=[
                {
                    "wallet": "0xtop",
                    "username": "top-wallet",
                    "walletScore": 90,
                    "insiderStyleWalletScore": 90,
                    "eventTradeCount": 3,
                    "suspiciousTradeCount": 3,
                    "independentHardEvidenceFlag": False,
                    "summary": "Top ranked wallet.",
                },
                {
                    "wallet": "0xhighimpact",
                    "username": "high-impact-wallet",
                    "walletScore": 31,
                    "insiderStyleWalletScore": 31,
                    "eventTradeCount": 1,
                    "suspiciousTradeCount": 0,
                    "independentHardEvidenceFlag": True,
                    "walletPrimaryReviewStatus": "primary_allowed",
                    "walletHardEvidenceSources": ["high_impact_timing_or_repricing"],
                    "walletEvidenceSourceFlags": [
                        "post_entry_repricing",
                        "high_impact_timing_or_repricing",
                    ],
                    "walletHardEvidenceSourceDetails": [detail],
                    "summary": "Saved high-impact hard evidence with no other source.",
                },
            ],
            cluster_rows=[],
            top_n=1,
        )

        hard_packet = next(packet for packet in packets if packet.get("wallet") == "0xhighimpact")
        supporting = hard_packet["supporting_evidence"]
        hard_review = review_case_packet(hard_packet)

        self.assertEqual(supporting["high_impact_source_quality"], "mechanical")
        self.assertIn("liquidity shock signal is present", supporting["high_impact_source_quality_reasons"])
        self.assertEqual(hard_review["review_verdict"], "ambiguous")
        self.assertIn("High-impact timing/repricing evidence is present", " ".join(hard_review["evidence_that_supports_concern"]))
        self.assertNotIn("Independent hard evidence in saved outputs", " ".join(hard_review["evidence_that_supports_concern"]))

    def test_ai_case_reviewer_labels_non_opening_high_impact_as_context_only(self) -> None:
        detail = (
            "high_impact_timing_or_repricing, reason=large_liquidity_share, "
            "trigger=post_entry_repricing, trade_id=trade-1, condition_id=cond-1, "
            "liquidity_ratio=22.18%, market_liquidity_usdc=94663.44"
        )
        packets = build_case_packets(
            event_analysis={"event": {"title": "High impact event", "slug": "high-impact-event"}},
            trade_rows=[
                {
                    "id": "trade-1",
                    "wallet": "0xhighimpact",
                    "username": "high-impact-wallet",
                    "conditionId": "cond-1",
                    "market": "Thin repricing market",
                    "eventForensicScore": 34,
                    "openingExposure": False,
                    "laterWon": True,
                    "price": 0.45,
                    "eventForensicFlags": ["post_entry_repricing"],
                    "summary": "Later reduction repriced after public movement.",
                }
            ],
            wallet_rows=[
                {
                    "wallet": "0xtop",
                    "username": "top-wallet",
                    "walletScore": 90,
                    "insiderStyleWalletScore": 90,
                    "eventTradeCount": 3,
                    "suspiciousTradeCount": 3,
                    "independentHardEvidenceFlag": False,
                    "summary": "Top ranked wallet.",
                },
                {
                    "wallet": "0xhighimpact",
                    "username": "high-impact-wallet",
                    "walletScore": 31,
                    "insiderStyleWalletScore": 31,
                    "eventTradeCount": 1,
                    "suspiciousTradeCount": 0,
                    "independentHardEvidenceFlag": True,
                    "walletPrimaryReviewStatus": "primary_allowed",
                    "walletHardEvidenceSources": ["high_impact_timing_or_repricing"],
                    "walletEvidenceSourceFlags": ["high_impact_timing_or_repricing"],
                    "walletHardEvidenceSourceDetails": [detail],
                    "summary": "Saved high-impact evidence from a non-opening source trade.",
                },
            ],
            cluster_rows=[],
            top_n=1,
        )

        hard_packet = next(packet for packet in packets if packet.get("wallet") == "0xhighimpact")
        supporting = hard_packet["supporting_evidence"]
        hard_review = review_case_packet(hard_packet)

        self.assertEqual(supporting["high_impact_source_quality"], "weak")
        self.assertIn(
            "source trade is not a clean opening exposure",
            " ".join(supporting["high_impact_source_quality_reasons"]),
        )
        self.assertEqual(hard_review["review_verdict"], "ambiguous")

    def test_ai_case_reviewer_keeps_corroborated_high_impact_as_plausible(self) -> None:
        detail = (
            "high_impact_timing_or_repricing, reason=large_liquidity_share, "
            "trigger=post_entry_repricing, trade_id=trade-1, condition_id=cond-1, "
            "liquidity_ratio=22.18%, market_liquidity_usdc=94663.44"
        )
        packets = build_case_packets(
            event_analysis={"event": {"title": "High impact event", "slug": "high-impact-event"}},
            trade_rows=[],
            wallet_rows=[
                {
                    "wallet": "0xtop",
                    "username": "top-wallet",
                    "walletScore": 90,
                    "insiderStyleWalletScore": 90,
                    "eventTradeCount": 3,
                    "suspiciousTradeCount": 3,
                    "independentHardEvidenceFlag": False,
                    "summary": "Top ranked wallet.",
                },
                {
                    "wallet": "0xhighimpact",
                    "username": "high-impact-wallet",
                    "walletScore": 31,
                    "insiderStyleWalletScore": 31,
                    "eventTradeCount": 1,
                    "suspiciousTradeCount": 0,
                    "independentHardEvidenceFlag": True,
                    "walletPrimaryReviewStatus": "primary_allowed",
                    "walletHardEvidenceSources": [
                        "high_impact_timing_or_repricing",
                        "shared_funding_source",
                    ],
                    "walletEvidenceSourceFlags": [
                        "post_entry_repricing",
                        "high_impact_timing_or_repricing",
                        "shared_funding_source",
                    ],
                    "walletHardEvidenceSourceDetails": [detail, "shared_funding_cluster_size=3"],
                    "summary": "Saved high-impact evidence with shared funding corroboration.",
                },
            ],
            cluster_rows=[],
            top_n=1,
        )

        hard_packet = next(packet for packet in packets if packet.get("wallet") == "0xhighimpact")
        supporting = hard_packet["supporting_evidence"]
        hard_review = review_case_packet(hard_packet)

        self.assertEqual(supporting["high_impact_source_quality"], "strong")
        self.assertEqual(hard_review["review_verdict"], "plausible_insider_style")
        self.assertIn("Independent hard evidence in saved outputs", " ".join(hard_review["evidence_that_supports_concern"]))

    def test_ai_case_reviewer_counts_mistky_style_wallet_as_likely_false_positive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_analysis_path = self._write_case_reviewer_fixture(
                root,
                username="MisTKy",
                trade_count=38,
                winning_count=23,
                wallet_event_trade_count="38",
                wallet_notable_trade_count="16",
                wallet_opening_count="31",
                wallet_winning_count="23",
                total_predictions="436",
                hard_evidence=False,
            )

            outputs = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=root / "ai_review_outputs",
                top_n=3,
            )
            payload = json.loads(Path(outputs["cases_json_path"]).read_text(encoding="utf-8"))
            wallet_review = next(item for item in payload["reviews"] if str(item["case_id"]).startswith("wallet-"))

            self.assertEqual(outputs["likely_false_positive_count"], 1)
            self.assertEqual(wallet_review["review_verdict"], "likely_false_positive")
            self.assertEqual(wallet_review["interpretation_class"], "high_volume_public_power_user")

    def test_ai_case_reviewer_llm_skips_without_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            event_analysis_path = self._write_case_reviewer_fixture(root)

            outputs = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=root / "ai_review_outputs",
                top_n=3,
                use_llm=True,
            )

            self.assertEqual(outputs["llm"]["status"], "skipped")
            self.assertIn("no provider/API key configured", outputs["llm"]["reason"])
            self.assertTrue(Path(outputs["llm_raw_jsonl_path"]).exists())

    def test_ai_case_reviewer_llm_invalid_json_is_saved_but_not_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"INSPOLY_LLM_PROVIDER": "openai", "INSPOLY_LLM_MODEL": "test-model", "OPENAI_API_KEY": "test-key"},
            clear=True,
        ), mock.patch("tools.ai_case_reviewer._call_openai_llm", return_value="not-json"):
            root = Path(tmp)
            event_analysis_path = self._write_case_reviewer_fixture(root)

            outputs = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=root / "ai_review_outputs",
                top_n=3,
                use_llm=True,
            )

            self.assertEqual(outputs["llm"]["status"], "invalid")
            raw_text = Path(outputs["llm_raw_jsonl_path"]).read_text(encoding="utf-8")
            self.assertIn("not-json", raw_text)
            payload = json.loads(Path(outputs["llm_cases_json_path"]).read_text(encoding="utf-8"))
            self.assertFalse(payload["safety"]["automatic_scoring_changes_applied"])

    def test_ai_case_reviewer_llm_valid_json_writes_advisory_report(self) -> None:
        llm_payload = {
            "case_reviews": [
                {
                    "case_id": "wallet-1-0xpower",
                    "llm_review_verdict": "likely_false_positive",
                    "interpretation_class": "high_volume_public_power_user",
                    "confidence": 0.91,
                    "main_reason": "Volume and wins dominate without hard evidence.",
                    "evidence_that_supports_concern": [],
                    "evidence_that_weakens_concern": ["Public high-volume behavior"],
                    "missing_data_needed": [],
                    "recommended_model_change": ["Keep high-volume cap."],
                    "recommended_test_fixture": ["High-volume cap fixture"],
                    "should_codex_implement_change": False,
                    "implementation_risk": "low",
                }
            ],
            "model_recommendations": {
                "recommended_changes": [
                    {
                        "change_id": "keep-high-volume-cap",
                        "target_area": "tests",
                        "problem": "Need regression coverage.",
                        "proposed_change": "Keep fixture coverage.",
                        "expected_effect": "Prevents recurrence.",
                        "risk": "low",
                        "requires_scoring_change": False,
                        "requires_ui_change": False,
                        "test_plan": ["Run reviewer tests"],
                    }
                ]
            },
        }
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"INSPOLY_LLM_PROVIDER": "openai", "INSPOLY_LLM_MODEL": "test-model", "OPENAI_API_KEY": "test-key"},
            clear=True,
        ), mock.patch("tools.ai_case_reviewer._call_openai_llm", return_value=json.dumps(llm_payload)):
            root = Path(tmp)
            event_analysis_path = self._write_case_reviewer_fixture(root)

            outputs = review_event_outputs(
                event_analysis_json_path=event_analysis_path,
                output_dir=root / "ai_review_outputs",
                top_n=3,
                use_llm=True,
            )

            self.assertEqual(outputs["llm"]["status"], "completed")
            report_text = Path(outputs["llm_review_report_md_path"]).read_text(encoding="utf-8")
            self.assertIn("LLM review is advisory", report_text)
            model_text = Path(outputs["llm_model_changes_md_path"]).read_text(encoding="utf-8")
            self.assertIn("keep-high-volume-cap", model_text)

    def test_event_forensic_backend_case_reviewer_action_returns_report_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_analysis_path = self._write_case_reviewer_fixture(root)
            app = EventForensicBrowserApp.__new__(EventForensicBrowserApp)
            app._lock = threading.RLock()
            app.config = AppConfig(
                data_dir=root,
                db_path=root / "ignored.sqlite3",
                reports_dir=root / "reports",
                outputs_dir=root / "event_forensic_outputs",
            )
            app.case_review_status = {
                "running": False,
                "stage": "Idle",
                "detail": "",
                "error": None,
                "summary": {},
                "outputs": {},
                "llm": {},
            }
            app.current_report = {
                "export_files": {
                    "event_analysis_json_path": str(event_analysis_path),
                }
            }
            app._log_error = lambda context, exc: None

            result = app.run_case_reviewer({"useLlm": False})

            self.assertTrue(result["ok"])
            review = result["caseReview"]
            self.assertEqual(review["stage"], "Completed")
            self.assertIn("No production scoring rules were changed", review["detail"])
            self.assertIn("review_report_md_path", review["outputs"])
            self.assertGreater(review["summary"]["casesReviewed"], 0)

    def test_resolve_analysis_scope_context_auto_selects_direct_market_input(self) -> None:
        market = _market(
            condition_id="cond-selected",
            slug="february-28",
            question="February 28",
        )
        resolved_event = ResolvedEvent(
            input_value="https://polymarket.com/event/february-28",
            canonical_url="https://polymarket.com/event/us-strikes-iran",
            event_id="event-1",
            event_slug="us-strikes-iran",
            event_title="US strikes Iran by...?",
            event_description="",
            event_category="Politics",
            event_closed=True,
            event_end_date=datetime(2026, 3, 1, tzinfo=UTC).isoformat(),
            source_market_slug="february-28",
            source_condition_id="cond-selected",
            event_payload={},
            markets={"cond-selected": market},
            market_payloads={"cond-selected": {}},
            event_family_id="us-strikes-iran",
            family_tokens={"us", "iran"},
        )

        scope_context = _resolve_analysis_scope_context(
            resolved_event,
            analysis_scope=None,
            selected_condition_id=None,
            selected_market_slug=None,
        )

        self.assertEqual(scope_context.analysis_scope, "market")
        self.assertEqual(scope_context.selected_condition_id, "cond-selected")
        self.assertEqual(scope_context.selected_market_slug, "february-28")

    def test_event_scope_context_ignores_stale_child_market_selection(self) -> None:
        iran_market = _market(
            condition_id="cond-iran",
            slug="us-strikes-iran-by-february-28",
            question="US strikes Iran by February 28?",
        )
        maduro_market = _market(
            condition_id="cond-maduro",
            slug="maduro-in-us-custody-by-january-31",
            question="Maduro in U.S. custody by January 31?",
        )
        resolved_event = ResolvedEvent(
            input_value="https://polymarket.com/event/maduro-in-us-custody-by-january-31",
            canonical_url="https://polymarket.com/event/maduro-in-us-custody-by-january-31",
            event_id="event-maduro",
            event_slug="maduro-in-us-custody-by-january-31",
            event_title="Maduro in U.S. custody by January 31?",
            event_description="",
            event_category="Politics",
            event_closed=True,
            event_end_date=datetime(2026, 1, 31, tzinfo=UTC).isoformat(),
            source_market_slug=None,
            source_condition_id=None,
            event_payload={},
            markets={"cond-maduro": maduro_market},
            market_payloads={"cond-maduro": {}},
            event_family_id="custody-maduro",
            family_tokens={"maduro", "custody"},
        )

        scope_context = _resolve_analysis_scope_context(
            resolved_event,
            analysis_scope="event",
            selected_condition_id=iran_market.condition_id,
            selected_market_slug=iran_market.slug,
        )

        self.assertEqual(scope_context.analysis_scope, "event")
        self.assertEqual(scope_context.analysis_markets, {"cond-maduro": maduro_market})
        self.assertIsNone(scope_context.selected_market)
        self.assertIsNone(scope_context.selected_condition_id)
        self.assertIsNone(scope_context.selected_market_slug)

    def test_visible_trade_payloads_respect_minimum_notional(self) -> None:
        payloads = [
            {"id": "small", "positionSize": 250.0},
            {"id": "large", "positionSize": 1250.0},
        ]

        visible = _visible_trade_payloads(payloads, minimum_notional=Decimal("1000"))

        self.assertEqual([item["id"] for item in visible], ["large"])

    def test_group_model_gap_items_collapses_repetitive_trade_spam(self) -> None:
        groups = _group_model_gap_items(
            [
                {
                    "market": "US strikes Iran by March 2, 2026?",
                    "wallet": "0x1",
                    "walletShort": "0x1...0001",
                    "eventForensicScore": 83,
                    "existingModelScore": 23,
                },
                {
                    "market": "US strikes Iran by March 2, 2026?",
                    "wallet": "0x2",
                    "walletShort": "0x2...0002",
                    "eventForensicScore": 79,
                    "existingModelScore": 17,
                },
                {
                    "market": "US strikes Iran by March 4, 2026?",
                    "wallet": "0x3",
                    "walletShort": "0x3...0003",
                    "eventForensicScore": 70,
                    "existingModelScore": 31,
                },
            ]
        )

        self.assertEqual(groups[0]["market"], "US strikes Iran by March 2, 2026?")
        self.assertEqual(groups[0]["tradeCount"], 2)
        self.assertEqual(groups[0]["walletCount"], 2)
        self.assertEqual(groups[0]["forensicScoreRange"], "79-83")
        self.assertEqual(groups[0]["currentScoreRange"], "17-23")

    def test_model_gap_summary_text_mentions_selected_market_in_market_scope(self) -> None:
        summary = _model_gap_summary_text(
            {
                "analysis_scope": "market",
                "selected_market_title": "February 28",
                "high_forensic_count": 2,
                "caught_count": 2,
                "missed_count": 0,
                "overflagged_count": 1,
            }
        )

        self.assertIn("selected child market (February 28)", summary)
        self.assertIn("selected-market context", summary)
        self.assertNotIn("event finished", summary)

    def test_event_report_markdown_includes_single_market_metadata(self) -> None:
        analyzer = EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )
        report = {
            "event": {
                "title": "US strikes Iran by...?",
                "canonicalUrl": "https://polymarket.com/event/us-strikes-iran",
                "completed": True,
                "marketCount": 4,
                "analysisMarketCount": 1,
                "slug": "us-strikes-iran",
            },
            "summary": {
                "analysis_market_count": 1,
                "candidate_trade_count": 0,
                "unique_wallet_count": 0,
            },
            "analysis_scope": "market",
            "selected_market_title": "February 28",
            "selected_condition_id": "cond-selected",
            "selected_market_slug": "february-28",
            "parent_event_slug": "us-strikes-iran",
            "scope_note": "Single-market scope note.",
            "eligibility": {"eligible": True},
            "markets": [],
            "display_trades": [],
            "suspicious_trades": [],
            "display_wallets": [],
            "wallet_clusters": [],
            "related_markets": [],
            "model_gap": {
                "analysis_scope": "market",
                "selected_market_title": "February 28",
                "high_forensic_count": 0,
                "caught_count": 0,
                "missed_count": 0,
                "overflagged_count": 0,
            },
            "funding_resolver_health": {
                "fundingResolverAvailable": False,
                "fundingResolverAuthError": True,
                "fundingResolverDisabledReason": "HTTPError: HTTP Error 401: Unauthorized",
            },
            "performance": {},
        }

        markdown = analyzer._event_report_markdown(report)

        self.assertIn("- Analysis scope: Single market", markdown)
        self.assertIn("- Selected market: February 28", markdown)
        self.assertIn("- Condition ID: cond-selected", markdown)
        self.assertIn("- Market slug: february-28", markdown)
        self.assertIn("- Parent event slug: us-strikes-iran", markdown)
        self.assertIn("selected child market", markdown)
        self.assertIn("## Primary Story", markdown)
        self.assertIn("Funding resolver: unavailable - auth_error", markdown)
        self.assertIn("Funding evidence: not assessed because resolver unavailable", markdown)
        self.assertIn("## What To Inspect Next", markdown)
        self.assertIn("## Analyst Appendix", markdown)
        self.assertNotIn("## Current Model vs Forensic View", markdown)
        self.assertNotIn("## Model Improvement Ideas", markdown)
        self.assertNotIn("## Runtime", markdown)

    def test_event_forensic_eligibility_allows_live_events_without_outcomes(self) -> None:
        analyzer = EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )
        market = _market(
            condition_id="cond-live",
            slug="live-event-market",
            question="Will the live event happen?",
        )
        resolved_event = ResolvedEvent(
            input_value="https://polymarket.com/event/live-event",
            canonical_url="https://polymarket.com/event/live-event",
            event_id="event-live",
            event_slug="live-event",
            event_title="Live event",
            event_description="",
            event_category="Politics",
            event_closed=False,
            event_end_date=datetime(2026, 5, 1, tzinfo=UTC).isoformat(),
            source_market_slug=None,
            source_condition_id=None,
            event_payload={"slug": "live-event", "closed": False},
            markets={"cond-live": market},
            market_payloads={
                "cond-live": {
                    "conditionId": "cond-live",
                    "closed": False,
                    "outcomes": '["Yes","No"]',
                    "outcomePrices": '["0.54","0.46"]',
                }
            },
            event_family_id="live-event",
            family_tokens={"live", "event"},
        )

        eligibility = analyzer._eligibility_payload(resolved_event)

        self.assertTrue(eligibility["eligible"])
        self.assertEqual(eligibility["status"], "live")
        self.assertFalse(eligibility["outcome_context_available"])
        self.assertIn("later-correctness", eligibility["reason"])

    def test_event_report_markdown_labels_live_events_without_preview_block(self) -> None:
        analyzer = EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )
        report = {
            "event": {
                "title": "Live event",
                "canonicalUrl": "https://polymarket.com/event/live-event",
                "completed": False,
                "resolutionStatus": "live",
                "outcomeContextAvailable": False,
                "marketCount": 1,
                "analysisMarketCount": 1,
                "slug": "live-event",
            },
            "summary": {
                "analysis_market_count": 1,
                "candidate_trade_count": 1,
                "unique_wallet_count": 1,
                "outcome_context_available": False,
            },
            "analysis_scope": "event",
            "parent_event_slug": "live-event",
            "scope_note": "Live event-wide scope note.",
            "eligibility": {
                "eligible": True,
                "status": "live",
                "reason": "Live event analysis: no market has a final resolved outcome yet.",
                "outcome_context_available": False,
            },
            "markets": [{"winner": "Unknown", "market": "Will the live event happen?"}],
            "display_trades": [
                {
                    "wallet": "0xwallet",
                    "walletShort": "0xwall...let",
                    "market": "Will the live event happen?",
                    "orderSide": "BUY",
                    "side": "YES",
                    "positionSize": 1500.0,
                    "displayTime": "2026-04-27 12:00 UTC",
                    "summary": "This trade is notable in the event context, but the evidence is mixed.",
                }
            ],
            "suspicious_trades": [],
            "display_wallets": [],
            "wallet_clusters": [],
            "related_markets": [],
            "model_gap": {
                "analysis_scope": "event",
                "outcome_context_available": False,
                "high_forensic_count": 0,
                "caught_count": 0,
                "missed_count": 0,
                "overflagged_count": 0,
            },
            "performance": {},
        }

        markdown = analyzer._event_report_markdown(report)

        self.assertIn("- Outcome status: Live event", markdown)
        self.assertIn("## Live Event Note", markdown)
        self.assertIn("before final outcomes are available", markdown)
        self.assertNotIn("## Eligibility", markdown)
        self.assertNotIn("Preview only", markdown)

    def test_trade_payload_marks_unknown_outcomes_as_pending_not_lost(self) -> None:
        analyzer = EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )
        trade = _trade(
            trade_id="live-trade",
            wallet="0xwallet",
            condition_id="cond-live",
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 27, 12, 0, tzinfo=UTC),
            price="0.42",
            size="2000",
            title="Will the live event happen?",
            slug="live-event-market",
            event_slug="live-event",
        )
        market = _market(
            condition_id="cond-live",
            slug="live-event-market",
            question="Will the live event happen?",
        )
        resolved_event = ResolvedEvent(
            input_value="https://polymarket.com/event/live-event",
            canonical_url="https://polymarket.com/event/live-event",
            event_id="event-live",
            event_slug="live-event",
            event_title="Live event",
            event_description="",
            event_category="Politics",
            event_closed=False,
            event_end_date=datetime(2026, 5, 1, tzinfo=UTC).isoformat(),
            source_market_slug=None,
            source_condition_id=None,
            event_payload={},
            markets={"cond-live": market},
            market_payloads={"cond-live": {"closed": False}},
            event_family_id="live-event",
            family_tokens={"live", "event"},
        )
        case = _flagged_case(
            trade=trade,
            market=market,
            raw_metrics={"trade_state": "increase", "opening_exposure_flag": "Yes"},
            flags=[],
        )

        payloads = analyzer._build_trade_payloads(
            resolved=resolved_event,
            cases=[case],
            wallet_cache={},
            winners_by_condition={"cond-live": None},
            related_market_rows=[],
            analysis_scope="event",
            sibling_market_activity={},
            scope_context=_resolve_analysis_scope_context(
                resolved_event,
                analysis_scope="event",
                selected_condition_id=None,
                selected_market_slug=None,
            ),
        )

        self.assertEqual(payloads[0]["outcomeStatus"], "unknown")
        self.assertFalse(payloads[0]["outcomeKnown"])
        self.assertFalse(payloads[0]["laterWon"])
        self.assertEqual(payloads[0]["winningOutcome"], "Unknown")

    def test_event_forensic_ui_has_selection_aware_structured_stories(self) -> None:
        html = Path("app/browser_event_forensic_ui.html").read_text(encoding="utf-8")

        self.assertIn("function AnalystNarrative", html)
        self.assertIn("function WalletStory", html)
        self.assertIn("function TradeStory", html)
        self.assertIn("function GroupStory", html)
        self.assertIn("function MarketStory", html)
        self.assertIn("function EntityLink", html)
        self.assertIn("Market-level report", html)
        self.assertIn("Wallet story:", html)
        self.assertIn("Trade story:", html)
        self.assertIn("Linked-wallet group story:", html)
        self.assertIn("Technical details", html)
        self.assertIn("Highest insider-style concern", html)
        self.assertIn("The account appears to be a public high-volume bettor/power user", html)
        self.assertIn("Sibling-market activity is context only and does not change the single-market score", html)
        self.assertIn("Case Reviewer: second-pass logic audit", html)
        self.assertIn("Run Case Reviewer", html)
        self.assertNotIn("Saved review drilldown", html)
        self.assertNotIn("Review Packets", html)
        self.assertNotIn("False Positive Library", html)
        self.assertIn("Use LLM reasoning if configured", html)
        self.assertIn("Run reviewer automatically after analysis", html)
        self.assertIn("Cases reviewed", html)
        self.assertIn("Likely false positives", html)
        self.assertIn("Plausible insider-style cases", html)
        self.assertIn("Ambiguous cases", html)
        self.assertIn("Top suggested fixes", html)
        self.assertIn("function isContextOnlyHighVolumeWallet", html)
        self.assertIn("Context only: high-volume public user", html)
        self.assertIn("not a primary insider-style lead", html)
        self.assertIn("more than 100 predictions / high-volume public activity", html)
        self.assertIn("Hard Evidence Review", html)
        self.assertIn("Open candidate audit", html)
        self.assertIn("function numericValue", html)
        self.assertIn("function firstNumericValue", html)
        self.assertIn("firstNumericValue(right.insiderStyleWalletScore, right.walletScore)", html)
        self.assertIn('if (mode === "forensic-desc") return compareTradeConcern(left, right);', html)
        concern_sort = html[html.index("const compareTradeConcern") : html.index("const compareTradeConcern") + 500]
        self.assertLess(concern_sort.index("eventForensicScore"), concern_sort.index("hardEvidenceRank"))

    def test_candidate_audit_rows_preserve_tiers_and_unknown_funding(self) -> None:
        base_payload = {
            "analysisScope": "market",
            "selectedConditionId": "cond-1",
            "selectedMarketSlug": "market-one",
            "parentEventSlug": "event-one",
            "conditionId": "cond-1",
            "marketSlug": "market-one",
            "timestamp": "2026-05-05T20:20:38+00:00",
            "side": "No",
            "orderSide": "BUY",
            "positionSize": 10000.0,
            "openingExposure": True,
            "fundingEvidenceGrade": "unknown",
            "fundingResolverFunctionalStatus": "disabled_no_rpc_mode",
            "strongRiskGatePassed": "Yes",
            "strongRiskGateType": "structure_led",
            "strongRiskExactGateBranch": "structure_led_gate",
            "strongRiskGateReasons": "existing_structure_led_gate",
            "hardEvidenceReviewTier": "",
            "hardEvidenceSources": [],
            "eventForensicFlags": ["opening_exposure"],
            "eventForensicReducers": [],
            "existingModelVerdict": "Multiple high-signal markers align.",
            "rawMetrics": {"fundingEvidenceGrade": "unknown"},
        }
        primary = {
            **base_payload,
            "id": "primary-trade",
            "wallet": "0xprimary",
            "username": "Primary",
            "existingModelScore": 50,
            "existingModelClass": "Strong Risk",
            "eventForensicScore": 42,
        }
        strong_demoted = {
            **base_payload,
            "id": "strong-demoted",
            "wallet": "0xstrong",
            "username": "Strong Demoted",
            "existingModelScore": 48,
            "existingModelClass": "Strong Risk",
            "eventForensicScore": 32,
            "eventForensicReducers": ["High-volume public-user context weakens the case."],
            "strongRiskSuppressorConflictReasons": "high_volume_public_user",
        }
        worth_demoted = {
            **base_payload,
            "id": "worth-demoted",
            "wallet": "0xworth",
            "username": "Worth Demoted",
            "existingModelScore": 31,
            "existingModelClass": "Worth a Look",
            "eventForensicScore": 20,
        }
        not_flagged = {
            **base_payload,
            "id": "not-flagged",
            "wallet": "0xplain",
            "username": "Plain Candidate",
            "existingModelScore": 8,
            "existingModelClass": "Low Risk",
            "eventForensicScore": 0,
        }
        wallet_rows = [
            {
                "wallet": "0xstrong",
                "walletPrimaryReviewStatus": "context_only_high_volume_public_user",
                "walletPublicPowerUserStatus": "public_power_user_demoted",
            }
        ]

        rows = _candidate_audit_rows(
            [primary, strong_demoted, worth_demoted, not_flagged],
            suspicious_trades=[primary],
            ranked_wallets=wallet_rows,
            funding_trace_mode="disabled",
        )
        tiers = {row["tradeId"]: row["finalDisplayTier"] for row in rows}

        self.assertEqual(tiers["primary-trade"], "primary_event_forensic")
        self.assertEqual(tiers["strong-demoted"], "current_model_strong_risk_demoted")
        self.assertEqual(tiers["worth-demoted"], "current_model_worth_a_look_demoted")
        self.assertEqual(tiers["not-flagged"], "not_flagged_candidate")
        self.assertTrue(all(row["fundingEvidenceGrade"] == "unknown" for row in rows))
        self.assertTrue(all(row["fundingTraceMode"] == "disabled" for row in rows))
        self.assertIn("not shown", rows[1]["primaryUiExplanation"].lower())

        report = {
            "generated_at": "2026-05-07T13:00:00+00:00",
            "analysis_scope": "market",
            "selected_condition_id": "cond-1",
            "selected_market_slug": "market-one",
            "summary": {
                "raw_trade_count": 4,
                "normal_candidate_trade_count": 4,
                "existing_flagged_count": 3,
                "forensic_suspicious_trade_count": 1,
                "wallet_context_count": 1,
                "truncated_market_count": 0,
            },
            "performance": {"trade_collection_raw_trade_rows": 4},
            "analysis_settings": {"funding_trace_mode": "disabled", "analysis_scope": "market"},
            "fundingEvidenceInterpretation": "Funding evidence is unknown, not none.",
        }
        payload = _candidate_audit_json_payload(report, rows)
        markdown = _candidate_audit_markdown(report, rows)
        self.assertEqual(payload["finalDisplayTierCounts"]["current_model_strong_risk_demoted"], 1)
        self.assertIn("Funding evidence is unknown", markdown)
        self.assertIn("current_model_strong_risk_demoted", markdown)

    def test_write_report_bundle_exports_candidate_audit_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = AppConfig(
                data_dir=root / ".event",
                db_path=root / ".event" / "event.sqlite3",
                reports_dir=root / ".event" / "reports",
                outputs_dir=root / "event_outputs",
            )
            config.reports_dir.mkdir(parents=True, exist_ok=True)
            analyzer = EventForensicAnalyzer(mock.Mock(), mock.Mock(), config)
            report = {
                "generated_at": "2026-05-07T13:00:00+00:00",
                "status": "completed",
                "event": {"title": "Candidate Audit Event"},
                "analysis_scope": "market",
                "selected_condition_id": "cond-1",
                "selected_market_slug": "market-one",
                "summary": {
                    "raw_trade_count": 1,
                    "normal_candidate_trade_count": 1,
                    "candidate_trade_count": 1,
                    "existing_flagged_count": 1,
                    "forensic_suspicious_trade_count": 1,
                    "wallet_context_count": 1,
                    "truncated_market_count": 0,
                },
                "performance": {"trade_collection_raw_trade_rows": 1},
                "analysis_settings": {"funding_trace_mode": "disabled", "analysis_scope": "market"},
                "fundingEvidenceInterpretation": "Funding evidence is unknown, not none.",
                "event_report_markdown": "# Report\n",
                "model_gap_markdown": "# Model Gap\n",
                "candidate_admission_funnel": {},
            }
            candidate_rows = [
                {
                    "tradeId": "trade-1",
                    "wallet": "0xabc",
                    "conditionId": "cond-1",
                    "notionalUsd": 1000,
                    "currentModelSeverity": "Strong Risk",
                    "eventForensicScore": 41,
                    "finalDisplayTier": "primary_event_forensic",
                    "finalTierReason": "Event Forensic score 41 met the primary threshold 40.",
                    "fundingEvidenceGrade": "unknown",
                    "fundingTraceMode": "disabled",
                    "primaryUiExplanation": "Shown in the primary UI review list.",
                }
            ]

            export_files = analyzer._write_report_bundle(
                datetime(2026, 5, 7, 13, 0, 0, tzinfo=UTC),
                config.reports_dir,
                report,
                suspicious_trades=[],
                suspicious_wallets=[],
                ranked_wallets=[],
                wallet_clusters=[],
                wallet_graph={"nodes": [], "edges": []},
                related_markets=[],
                candidate_audit_rows=candidate_rows,
                raw_bundle={},
            )

            csv_path = Path(export_files["candidate_trades_csv_path"])
            json_path = Path(export_files["candidate_trades_json_path"])
            md_path = Path(export_files["candidate_audit_md_path"])
            self.assertTrue(csv_path.exists())
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            self.assertIn("finalDisplayTier", csv_path.read_text(encoding="utf-8"))
            candidate_payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(candidate_payload["rows"][0]["finalDisplayTier"], "primary_event_forensic")
            self.assertIn("Funding evidence is unknown", md_path.read_text(encoding="utf-8"))

    def test_candidate_audit_backfill_tool_writes_sidecar_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "event_forensic_old_run"
            reports_dir = root / "reports"
            run_dir.mkdir()
            reports_dir.mkdir()
            report_json_path = reports_dir / "event_forensic_test.json"
            event_analysis = {
                "generated_at": "2026-05-07T13:00:00+00:00",
                "report_json_path": str(report_json_path),
                "analysis_scope": "market",
                "selected_condition_id": "cond-1",
                "selected_market_slug": "market-one",
                "analysis_settings": {
                    "analysis_scope": "market",
                    "selected_condition_id": "cond-1",
                    "selected_market_slug": "market-one",
                    "funding_trace_mode": "disabled",
                },
                "summary": {
                    "raw_trade_count": 2,
                    "normal_candidate_trade_count": 2,
                    "candidate_trade_count": 2,
                    "existing_flagged_count": 2,
                    "forensic_suspicious_trade_count": 1,
                    "wallet_context_count": 1,
                    "truncated_market_count": 0,
                },
                "performance": {"trade_collection_raw_trade_rows": 2},
                "fundingEvidenceInterpretation": "Funding evidence is unknown, not none.",
                "suspicious_trades": [
                    {
                        "id": "primary-trade",
                        "wallet": "0xprimary",
                        "username": "Primary",
                        "marketSlug": "market-one",
                        "conditionId": "cond-1",
                        "timestamp": "2026-05-07T10:00:00+00:00",
                        "side": "No",
                        "orderSide": "BUY",
                        "positionSize": 10000,
                        "existingModelScore": 50,
                        "existingModelClass": "Strong Risk",
                        "eventForensicScore": 42,
                        "fundingEvidenceGrade": "unknown",
                        "fundingResolverFunctionalStatus": "disabled_no_rpc_mode",
                    }
                ],
            }
            event_analysis_path = run_dir / "event_analysis.json"
            event_analysis_text = json.dumps(event_analysis)
            event_analysis_path.write_text(event_analysis_text, encoding="utf-8")
            suspicious_csv = run_dir / "suspicious_trades.csv"
            suspicious_csv_text = "tradeId,wallet\nprimary-trade,0xprimary\n"
            suspicious_csv.write_text(suspicious_csv_text, encoding="utf-8")
            sqlite_path = root / "event.sqlite3"
            conn = sqlite3.connect(sqlite_path)
            try:
                conn.executescript(
                    """
                    create table scan_runs (
                        id integer primary key,
                        started_at text not null,
                        lookback text not null,
                        topic_scope text not null,
                        raw_trade_count integer not null,
                        filtered_trade_count integer not null,
                        flagged_case_count integer not null,
                        report_json_path text not null,
                        report_md_path text not null
                    );
                    create table flagged_cases (
                        id integer primary key,
                        scan_run_id integer not null,
                        trade_id text not null,
                        market_slug text not null,
                        market_title text not null,
                        wallet_address text not null,
                        side text not null,
                        outcome text not null,
                        timestamp text not null,
                        trade_notional text not null,
                        score integer not null,
                        level text not null,
                        verdict text not null,
                        reasons_json text not null,
                        metrics_json text not null,
                        wallet_summary_json text not null
                    );
                    """
                )
                conn.execute(
                    "insert into scan_runs values (1, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "2026-05-07T13:00:00+00:00",
                        "url",
                        "Event",
                        2,
                        2,
                        2,
                        str(report_json_path),
                        "report.md",
                    ),
                )
                conn.execute(
                    "insert into flagged_cases values (1, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "primary-trade",
                        "market-one",
                        "Market One",
                        "0xprimary",
                        "BUY",
                        "No",
                        "2026-05-07T10:00:00+00:00",
                        "10000",
                        50,
                        "Strong Risk",
                        "Multiple high-signal markers align.",
                        json.dumps(["large opening trade"]),
                        json.dumps({"fundingEvidenceGrade": "unknown", "fundingResolverFunctionalStatus": "disabled_no_rpc_mode"}),
                        "{}",
                    ),
                )
                conn.execute(
                    "insert into flagged_cases values (2, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "demoted-trade",
                        "market-one",
                        "Market One",
                        "0xdemoted",
                        "BUY",
                        "No",
                        "2026-05-07T11:00:00+00:00",
                        "9000",
                        45,
                        "Strong Risk",
                        "Multiple high-signal markers align.",
                        json.dumps(["large opening trade"]),
                        json.dumps(
                            {
                                "fundingEvidenceGrade": "unknown",
                                "fundingResolverFunctionalStatus": "disabled_no_rpc_mode",
                                "strongRiskSuppressorConflictReasons": "high_volume_public_user",
                            }
                        ),
                        "{}",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            result = subprocess.run(
                [
                    "python3",
                    "tools/event_forensic_candidate_audit_export.py",
                    "--run-dir",
                    str(run_dir),
                    "--sqlite-path",
                    str(sqlite_path),
                ],
                cwd=Path.cwd(),
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("rows=2", result.stdout)
            self.assertEqual(event_analysis_path.read_text(encoding="utf-8"), event_analysis_text)
            self.assertEqual(suspicious_csv.read_text(encoding="utf-8"), suspicious_csv_text)
            sidecar_json = sorted(run_dir.glob("event_forensic_candidate_audit_*.json"))
            self.assertEqual(len(sidecar_json), 1)
            payload = json.loads(sidecar_json[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["finalDisplayTierCounts"]["current_model_strong_risk_demoted"], 1)
            self.assertTrue(payload["recoverabilityNote"].startswith("Old saved bundles"))

    def test_scanner_ui_explains_filter_hidden_cards(self) -> None:
        html = Path("app/browser_ui.html").read_text(encoding="utf-8")

        self.assertIn("function activeCardFilterLabels", html)
        self.assertIn("The selected run has", html)
        self.assertIn("current filters hide", html)
        self.assertIn("showAllQualityScreenedLabel", html)
        self.assertIn("quality-screened cards", html)
        self.assertIn("Min size:", html)

    def test_execution_state_supports_opening_short_exposure(self) -> None:
        trade = _trade(
            trade_id="short-open",
            wallet="0xshort",
            condition_id="cond-short",
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 11, 0, tzinfo=UTC),
            price="0.42",
            size="10000",
            title="Will event happen?",
            slug="will-event-happen",
            event_slug="will-event-happen",
            side="SELL",
            outcome="YES",
        )

        execution_state = _classify_execution_state(trade, [], [])

        self.assertEqual(execution_state, "increase_short")
        self.assertTrue(_is_opening_exposure(execution_state))
        self.assertEqual(_capital_at_risk_usdc(trade, execution_state), trade.notional)

    def test_should_trace_funding_for_high_conviction_and_forensic_modes(self) -> None:
        inspection = WalletInspection(
            address="0xseasoned",
            polygon_nonce=180,
            traded_market_count=140,
            recent_trade_count=140,
            unique_market_count=70,
            focus_market_count=12,
            first_trade_at=datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
            last_trade_at=datetime(2026, 4, 7, tzinfo=UTC).isoformat(),
            dominant_domain_label="Middle East",
            domain_concentration_score=0.45,
            public_model_specialist_flag=False,
            domain_counts={"Middle East": 12},
            notes=[],
        )

        self.assertTrue(
            _should_trace_funding(
                inspection,
                mode="recent",
                derived_metrics={
                    "trade_domain": "Middle East",
                    "opening_exposure_flag": True,
                    "capital_at_risk_usdc": Decimal("3200"),
                    "wallet_market_conviction_ratio": 0.9,
                },
            )
        )
        self.assertTrue(_should_trace_funding(inspection, mode="event_forensic"))

    def test_event_family_key_collapses_deadline_variants(self) -> None:
        first = _trade(
            trade_id="a",
            wallet="0x1",
            condition_id="c1",
            asset_id="yes",
            timestamp=datetime(2026, 4, 7, tzinfo=UTC),
            price="0.10",
            size="10000",
            title="US x Iran ceasefire by April 7, 2026?",
            slug="us-x-iran-ceasefire-by-april-7-2026",
            event_slug="us-x-iran-ceasefire-by-april-7-2026",
        )
        second = _trade(
            trade_id="b",
            wallet="0x1",
            condition_id="c2",
            asset_id="yes",
            timestamp=datetime(2026, 4, 8, tzinfo=UTC),
            price="0.10",
            size="10000",
            title="US x Iran ceasefire by March 31, 2026?",
            slug="us-x-iran-ceasefire-by-march-31-2026",
            event_slug="us-x-iran-ceasefire-by-march-31-2026",
        )

        self.assertEqual(_event_family_key(first), "us-x-iran-ceasefire-by")
        self.assertEqual(_event_family_key(first), _event_family_key(second))

    def test_score_trade_adds_dormancy_and_event_family_repeat(self) -> None:
        current_trade = _trade(
            trade_id="current",
            wallet="0xwallet",
            condition_id="cond-current",
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 15, 0, tzinfo=UTC),
            price="0.10",
            size="50000",
            title="US x Iran ceasefire by April 7, 2026?",
            slug="us-x-iran-ceasefire-by-april-7-2026",
            event_slug="us-x-iran-ceasefire-by-april-7-2026",
        )
        wallet_history = [
            _trade(
                trade_id="old-1",
                wallet="0xwallet",
                condition_id="cond-old-1",
                asset_id="asset-old-1",
                timestamp=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                price="0.18",
                size="6000",
                title="US x Iran ceasefire by March 31, 2026?",
                slug="us-x-iran-ceasefire-by-march-31-2026",
                event_slug="us-x-iran-ceasefire-by-march-31-2026",
            ),
            _trade(
                trade_id="old-2",
                wallet="0xwallet",
                condition_id="cond-old-2",
                asset_id="asset-old-2",
                timestamp=datetime(2026, 1, 2, 10, 0, tzinfo=UTC),
                price="0.16",
                size="7000",
                title="US x Iran ceasefire by January 31, 2026?",
                slug="us-x-iran-ceasefire-by-january-31-2026",
                event_slug="us-x-iran-ceasefire-by-january-31-2026",
            ),
            _trade(
                trade_id="old-3",
                wallet="0xwallet",
                condition_id="cond-old-2",
                asset_id="asset-old-2",
                timestamp=datetime(2026, 1, 3, 10, 0, tzinfo=UTC),
                price="0.14",
                size="8000",
                title="US x Iran ceasefire by January 31, 2026?",
                slug="us-x-iran-ceasefire-by-january-31-2026",
                event_slug="us-x-iran-ceasefire-by-january-31-2026",
            ),
            current_trade,
        ]
        market = _market(
            condition_id="cond-current",
            slug="us-x-iran-ceasefire-by-april-7-2026",
            question="US x Iran ceasefire by April 7, 2026?",
        )
        market_window_trades = [
            _trade(
                trade_id="peer-1",
                wallet="0xpeer1",
                condition_id="cond-current",
                asset_id="asset-yes",
                timestamp=current_trade.timestamp - timedelta(minutes=12),
                price="0.18",
                size="4000",
                title=current_trade.title,
                slug=current_trade.slug,
                event_slug=current_trade.event_slug,
            ),
            _trade(
                trade_id="peer-2",
                wallet="0xpeer2",
                condition_id="cond-current",
                asset_id="asset-yes",
                timestamp=current_trade.timestamp - timedelta(minutes=5),
                price="0.19",
                size="4500",
                title=current_trade.title,
                slug=current_trade.slug,
                event_slug=current_trade.event_slug,
            ),
            current_trade,
            _trade(
                trade_id="peer-3",
                wallet="0xpeer3",
                condition_id="cond-current",
                asset_id="asset-yes",
                timestamp=current_trade.timestamp + timedelta(minutes=10),
                price="0.27",
                size="5000",
                title=current_trade.title,
                slug=current_trade.slug,
                event_slug=current_trade.event_slug,
            ),
            _trade(
                trade_id="peer-4",
                wallet="0xpeer4",
                condition_id="cond-current",
                asset_id="asset-yes",
                timestamp=current_trade.timestamp + timedelta(minutes=20),
                price="0.32",
                size="5500",
                title=current_trade.title,
                slug=current_trade.slug,
                event_slug=current_trade.event_slug,
            ),
        ]

        case = _score_trade(
            trade=current_trade,
            market=market,
            trade_domain="Middle East",
            wallet_inspection=_wallet_inspection(len(wallet_history)),
            wallet_performance=_wallet_performance(),
            wallet_window_trades=[current_trade],
            wallet_history_trades=wallet_history,
            market_window_trades=market_window_trades,
            domain_window_trades=market_window_trades,
            event_context=_event_context(),
            funding_context=FundingContext(funding_found=False),
            include_below_threshold=True,
        )

        self.assertIsNotNone(case)
        assert case is not None
        self.assertIn("dormant_wallet_reactivation", case.flags)
        self.assertIn("event_family_repeat", case.flags)
        self.assertEqual(case.raw_metrics["reactivated_after_dormancy_flag"], "Yes")
        self.assertEqual(case.raw_metrics["event_family_repeat_flag"], "Yes")

    def test_shared_funder_annotation_marks_split_wallet_pattern(self) -> None:
        market = _market(
            condition_id="cond-shared",
            slug="israel-strikes-iran-by-february-28-2026",
            question="Israel strikes Iran by February 28, 2026?",
        )
        trade_one = _trade(
            trade_id="split-1",
            wallet="0xwallet-1",
            condition_id="cond-shared",
            asset_id="asset-yes",
            timestamp=datetime(2026, 2, 27, 20, 0, tzinfo=UTC),
            price="0.11",
            size="25000",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
        )
        trade_two = _trade(
            trade_id="split-2",
            wallet="0xwallet-2",
            condition_id="cond-shared",
            asset_id="asset-yes",
            timestamp=datetime(2026, 2, 27, 20, 8, tzinfo=UTC),
            price="0.13",
            size="24000",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
        )
        raw_metrics = {
            "trade_state": "increase",
            "opening_exposure_flag": "Yes",
            "economic_direction": "long_yes",
            "funding_graph_key": "shared-route",
            "resolution_gap_flag": "No",
            "structural_concern_flag": "No",
            "materially_uncertain_flag": "Yes",
            "decisive_timing_edge_flag": "Yes",
            "strong_timing_proof_count": "1",
            "supporting_booster_count": "1",
            "benign_pattern_flag": "No",
            "credibility_gamed_flag": "No",
            "hard_resolution_gap_flag": "No",
            "soft_resolution_gap_flag": "No",
            "reactivated_after_dormancy_flag": "No",
            "split_wallet_pattern_flag": "No",
        }

        first = _flagged_case(
            trade=trade_one,
            market=market,
            raw_metrics=dict(raw_metrics),
            flags=[],
        )
        second = _flagged_case(
            trade=trade_two,
            market=market,
            raw_metrics=dict(raw_metrics),
            flags=[],
        )

        _annotate_shared_funding_links([first, second])

        self.assertEqual(first.raw_metrics["shared_funding_source_flag"], "Yes")
        self.assertEqual(second.raw_metrics["shared_funding_source_flag"], "Yes")
        self.assertEqual(first.raw_metrics["shared_funding_source_wallet_count"], "2")
        self.assertEqual(first.raw_metrics["split_wallet_pattern_flag"], "Yes")
        self.assertEqual(second.raw_metrics["split_wallet_pattern_flag"], "Yes")
        self.assertIn("split_wallet_pattern", first.flags)
        self.assertIn("split_wallet_pattern", second.flags)

    def test_shared_funding_distinguishes_trade_count_from_wallet_count(self) -> None:
        market = _market(
            condition_id="cond-same-wallet-funding",
            slug="same-wallet-funding",
            question="Same wallet repeats funding route?",
        )
        raw_metrics = {
            "trade_state": "increase",
            "opening_exposure_flag": "Yes",
            "economic_direction": "long_yes",
            "funding_graph_key": "strict:repeat",
            "funding_graph_key_strict": "strict:repeat",
            "funding_graph_key_proxy": "",
            "funding_evidence_grade": "direct_strict",
            "shared_funding_source_flag": "No",
            "shared_funding_source_cluster_size": "0",
            "split_wallet_pattern_flag": "No",
            "cex_proxy_cluster_flag": "No",
            "resolution_gap_flag": "No",
            "materially_uncertain_flag": "Yes",
            "decisive_timing_edge_flag": "No",
            "strong_timing_proof_count": "0",
            "supporting_booster_count": "0",
            "structural_concern_count": "0",
            "hardEvidenceSources": "",
        }
        first = _flagged_case(
            trade=_trade(
                trade_id="same-wallet-funding-1",
                wallet="0xsamewallet",
                condition_id=market.condition_id,
                asset_id="asset-yes",
                timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
                price="0.42",
                size="2500",
                title=market.question,
                slug=market.slug,
                event_slug=market.slug,
            ),
            market=market,
            raw_metrics=dict(raw_metrics),
            flags=[],
        )
        second = _flagged_case(
            trade=_trade(
                trade_id="same-wallet-funding-2",
                wallet="0xsamewallet",
                condition_id=market.condition_id,
                asset_id="asset-yes",
                timestamp=datetime(2026, 4, 7, 12, 4, tzinfo=UTC),
                price="0.43",
                size="2600",
                title=market.question,
                slug=market.slug,
                event_slug=market.slug,
            ),
            market=market,
            raw_metrics=dict(raw_metrics),
            flags=[],
        )

        _annotate_shared_funding_links([first, second])
        _annotate_hard_evidence_review([first, second], evidence_availability_stage="archive_no_outcome_context")

        self.assertEqual(first.raw_metrics["shared_funding_source_cluster_size"], "2")
        self.assertEqual(first.raw_metrics["shared_funding_source_wallet_count"], "1")
        self.assertEqual(first.raw_metrics["hardEvidenceSources"], "")
        self.assertNotIn("strict_shared_funding_source", first.raw_metrics["strongRiskStructuralSources"])

    def test_funding_evidence_grade_values(self) -> None:
        cases = {
            "none": FundingContext(funding_found=False),
            "unknown": unknown_funding_context("HTTPError: HTTP Error 401: Unauthorized"),
            "cex_proxy": FundingContext(
                funding_found=True,
                source_category="cex",
                origin_category="cex",
                funding_depth=1,
            ),
            "bridge_proxy": FundingContext(
                funding_found=True,
                source_category="bridge",
                origin_category="bridge",
                funding_depth=1,
            ),
            "multi_hop_unknown": FundingContext(
                funding_found=True,
                source_category="unknown",
                origin_category="unknown",
                funding_depth=2,
                funding_graph_key_strict="0xorigin",
                suspicious_funding_flag=True,
            ),
            "suspicious_direct": FundingContext(
                funding_found=True,
                source_category="dex",
                origin_category="dex",
                funding_depth=1,
                funding_graph_key_strict="0xdex",
                suspicious_funding_flag=True,
            ),
            "direct_strict": FundingContext(
                funding_found=True,
                source_category="unknown",
                origin_category="unknown",
                funding_depth=1,
                funding_graph_key_strict="0xorigin",
            ),
        }

        for expected, context in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(grade_funding_evidence(context), expected)

    def test_funding_healthcheck_classifies_auth_and_masks_urls(self) -> None:
        auth_error = HTTPError(
            "https://user:secret@example.invalid/private-key",
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(b""),
        )
        with mock.patch("tools.funding_resolver_healthcheck._post_json", side_effect=auth_error):
            result = classify_rpc_health("https://user:secret@example.invalid/private-key?token=abc")

        self.assertEqual(result["status"], "auth_error")
        self.assertEqual(result["endpoint_label"], "example.invalid")
        rendered = render_markdown({"overall_status": "auth_error", "auth_error": True, "endpoints": [result]})
        self.assertNotIn("secret", rendered)
        self.assertNotIn("token=abc", rendered)
        self.assertEqual(mask_rpc_url("https://user:secret@example.invalid/private-key?token=abc"), "example.invalid")

    def test_runtime_env_file_loads_when_os_env_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".inspoly_runtime.env").write_text(
                "\n"
                "# local runtime config\n"
                "INSPOLY_POLYGON_RPC_URLS=https://one.example,https://two.example\n"
                "\n"
                "IGNORED_LINE_WITHOUT_EQUALS\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                loaded = load_runtime_env(root)

                self.assertEqual(
                    loaded["INSPOLY_POLYGON_RPC_URLS"],
                    "https://one.example,https://two.example",
                )
                self.assertEqual(
                    polygon_rpc_urls(),
                    ["https://one.example", "https://two.example"],
                )
                self.assertNotIn("IGNORED_LINE_WITHOUT_EQUALS", os.environ)

    def test_runtime_env_does_not_override_shell_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".inspoly_runtime.env").write_text(
                "INSPOLY_POLYGON_RPC_URLS=https://runtime.example\n",
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {"INSPOLY_POLYGON_RPC_URLS": "https://shell.example"},
                clear=True,
            ):
                loaded = load_runtime_env(root)

                self.assertEqual(loaded, {})
                self.assertEqual(polygon_rpc_urls(), ["https://shell.example"])

    def test_healthcheck_and_resolver_use_same_loaded_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".inspoly_runtime.env").write_text(
                "INSPOLY_POLYGON_RPC_URLS=https://one.example,https://two.example\n",
                encoding="utf-8",
            )

            def fake_classify(url: str) -> dict[str, object]:
                return {
                    "endpoint_label": mask_rpc_url(url),
                    "status": "available" if url == "https://one.example" else "network_error",
                    "detail": "",
                }

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("tools.funding_resolver_healthcheck.classify_rpc_health", side_effect=fake_classify):
                    report = run_healthcheck(runtime_env_root=root)
                resolver = FundingResolver()

                self.assertEqual(report["overall_status"], "available_for_funding_trace")
                self.assertEqual(report["selected_endpoint_label"], "one.example")
                self.assertEqual(resolver._rpc_urls, ["https://one.example", "https://two.example"])

    def test_healthcheck_selects_first_available_endpoint(self) -> None:
        def fake_classify(url: str) -> dict[str, object]:
            return {"endpoint_label": mask_rpc_url(url), "status": "available", "detail": ""}

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("tools.funding_resolver_healthcheck.classify_rpc_health", side_effect=fake_classify):
                report = run_healthcheck(
                    urls=["https://first.example", "https://second.example"],
                    runtime_env_root=Path(temp_dir),
                )

        self.assertEqual(report["overall_status"], "available_for_funding_trace")
        self.assertEqual(report["selected_endpoint_label"], "first.example")
        rendered = render_markdown(report)
        self.assertIn("Selected endpoint: first.example", rendered)
        self.assertNotIn("https://first.example", rendered)

    def test_healthcheck_recovers_when_first_endpoint_fails(self) -> None:
        def fake_classify(url: str) -> dict[str, object]:
            status = "network_error" if url == "https://bad.example" else "available"
            return {"endpoint_label": mask_rpc_url(url), "status": status, "detail": ""}

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("tools.funding_resolver_healthcheck.classify_rpc_health", side_effect=fake_classify):
                report = run_healthcheck(
                    urls=["https://bad.example", "https://good.example"],
                    runtime_env_root=Path(temp_dir),
                )

        self.assertEqual(report["overall_status"], "available_for_funding_trace")
        self.assertEqual(report["selected_endpoint_label"], "good.example")

    def test_healthcheck_all_endpoints_fail_specific_reason(self) -> None:
        def fake_classify(url: str) -> dict[str, object]:
            return {"endpoint_label": mask_rpc_url(url), "status": "rate_limited", "detail": "HTTP 429"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("tools.funding_resolver_healthcheck.classify_rpc_health", side_effect=fake_classify):
                report = run_healthcheck(
                    urls=["https://first.example", "https://second.example"],
                    runtime_env_root=Path(temp_dir),
                )

        self.assertEqual(report["overall_status"], "rate_limited")
        self.assertEqual(report["selected_endpoint_label"], "")

    def test_functional_healthcheck_distinguishes_getlogs_rate_limit(self) -> None:
        def fake_post(url: str, payload: dict[str, object], timeout: int = 10) -> dict[str, object]:
            if payload["method"] == "eth_blockNumber":
                return {"jsonrpc": "2.0", "id": 1, "result": "0x64"}
            raise HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=BytesIO(b""))

        with mock.patch("tools.funding_resolver_healthcheck._post_json", side_effect=fake_post):
            result = classify_rpc_health("https://limited.example")

        self.assertEqual(result["status"], "rate_limited")
        self.assertEqual(result["lightweight_status"], "lightweight_available")
        self.assertEqual(result["funding_trace_status"], "rate_limited")

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("tools.funding_resolver_healthcheck._post_json", side_effect=fake_post):
                report = run_healthcheck(
                    urls=["https://limited.example"],
                    runtime_env_root=Path(temp_dir),
                )
        self.assertEqual(report["overall_status"], "rate_limited_for_funding_trace")
        self.assertTrue(report["lightweight_available"])
        self.assertFalse(report["funding_trace_available"])

    def test_funding_resolver_retries_next_endpoint_after_429(self) -> None:
        calls: list[str] = []

        def fake_post(url: str, payload: dict[str, object], timeout: int = 10) -> dict[str, object]:
            calls.append(url)
            if "bad.example" in url:
                raise HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=BytesIO(b""))
            return {"jsonrpc": "2.0", "id": 1, "result": "0x2a"}

        with mock.patch.dict(
            os.environ,
            {
                "INSPOLY_POLYGON_RPC_MAX_RETRIES": "1",
                "INSPOLY_POLYGON_RPC_MIN_INTERVAL_SECONDS": "0",
                "INSPOLY_POLYGON_RPC_429_COOLDOWN_SECONDS": "60",
            },
        ):
            resolver = FundingResolver(rpc_url="https://bad.example,https://good.example")
            with mock.patch("app.funding_context._post_json", side_effect=fake_post):
                result = resolver._rpc("eth_blockNumber", [])

        health = resolver.health()
        self.assertEqual(result, "0x2a")
        self.assertEqual(calls, ["https://bad.example", "https://good.example"])
        self.assertEqual(health.fundingTraceRateLimitedCount, 1)
        self.assertEqual(health.fundingTraceRetryCount, 1)
        self.assertEqual(health.fundingTraceFallbackEndpointCount, 1)
        self.assertEqual(health.fundingTraceEndpointPoolSize, 2)
        self.assertEqual(health.fundingTraceEndpointCooldownCount, 1)

    def test_validation_rpc_can_use_single_attempt_post(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "INSPOLY_VALIDATION_MODE": "1",
                "INSPOLY_POLYGON_RPC_DISABLE_HTTP_RETRIES": "1",
                "INSPOLY_POLYGON_RPC_MIN_INTERVAL_SECONDS": "0",
            },
        ):
            resolver = FundingResolver(rpc_url="https://one.example")
            with mock.patch(
                "app.funding_context._post_json",
                side_effect=AssertionError("retrying transport should not be used"),
            ) as retrying_post:
                with mock.patch(
                    "app.funding_context._post_json_once",
                    return_value={"result": "0x2a"},
                ) as single_post:
                    result = resolver._rpc("eth_blockNumber", [])

        self.assertEqual(result, "0x2a")
        retrying_post.assert_not_called()
        single_post.assert_called_once()

    def test_validation_getlogs_network_error_cools_endpoint_and_falls_back(self) -> None:
        calls: list[str] = []

        def fake_single_post(url: str, payload: dict[str, object], timeout: int = 10) -> dict[str, object]:
            calls.append(url)
            if "bad.example" in url:
                raise HTTPError(url, 400, "Bad Request", hdrs=None, fp=BytesIO(b""))
            return {"result": []}

        with mock.patch.dict(
            os.environ,
            {
                "INSPOLY_VALIDATION_MODE": "1",
                "INSPOLY_POLYGON_RPC_DISABLE_HTTP_RETRIES": "1",
                "INSPOLY_POLYGON_RPC_MIN_INTERVAL_SECONDS": "0",
                "INSPOLY_POLYGON_RPC_MAX_RETRIES": "1",
                "INSPOLY_POLYGON_RPC_ERROR_COOLDOWN_SECONDS": "60",
                "INSPOLY_VALIDATION_COOLDOWN_GETLOGS_NETWORK_ERRORS": "1",
            },
        ):
            resolver = FundingResolver(rpc_url="https://bad.example,https://good.example")
            with mock.patch("app.funding_context._post_json_once", side_effect=fake_single_post):
                result = resolver._rpc("eth_getLogs", [{"fromBlock": "0x1", "toBlock": "0x2"}])

        self.assertEqual(result, [])
        self.assertEqual(calls, ["https://bad.example", "https://good.example"])
        health = resolver.health()
        self.assertEqual(health.fundingTraceRetryCount, 1)
        self.assertEqual(health.fundingTraceFallbackEndpointCount, 1)
        self.assertEqual(health.fundingTraceEndpointCooldownCount, 1)
        endpoint_summary = {
            str(item.get("endpointLabel")): item
            for item in health.fundingTraceEndpointSummary
        }
        self.assertTrue(endpoint_summary["bad.example"]["cooldownActive"])
        self.assertEqual(
            endpoint_summary["bad.example"]["fundingTraceHealthStatus"],
            "cooldown_after_error",
        )

    def test_funding_resolver_all_endpoints_rate_limited_reason(self) -> None:
        rate_limit = HTTPError("https://limited.example", 429, "Too Many Requests", hdrs=None, fp=BytesIO(b""))

        with mock.patch.dict(
            os.environ,
            {
                "INSPOLY_POLYGON_RPC_MAX_RETRIES": "1",
                "INSPOLY_POLYGON_RPC_MIN_INTERVAL_SECONDS": "0",
                "INSPOLY_POLYGON_RPC_429_COOLDOWN_SECONDS": "60",
            },
        ):
            resolver = FundingResolver(rpc_url="https://one.example,https://two.example")
            with mock.patch("app.funding_context._post_json", side_effect=rate_limit):
                with self.assertRaises(HTTPError):
                    resolver._rpc("eth_blockNumber", [])

        health = resolver.health()
        self.assertFalse(health.fundingResolverAvailable)
        self.assertEqual(health.fundingResolverUnavailableReason, "rate_limited")
        self.assertEqual(health.fundingTraceRateLimitedCount, 2)

    def test_getlogs_block_range_is_chunked(self) -> None:
        ranges: list[tuple[int, int]] = []

        def fake_rpc(method: str, params: list[object]) -> list[dict[str, object]]:
            self.assertEqual(method, "eth_getLogs")
            query = params[0]
            ranges.append((int(str(query["fromBlock"]), 16), int(str(query["toBlock"]), 16)))
            return []

        with mock.patch.dict(os.environ, {"INSPOLY_POLYGON_RPC_GETLOGS_BLOCK_CHUNK": "10"}):
            resolver = FundingResolver(rpc_url="https://example.invalid")
        with mock.patch("app.funding_context.SEARCH_WINDOW_BLOCKS", 25):
            with mock.patch("app.funding_context.MAX_SEARCH_BLOCKS", 25):
                with mock.patch.object(resolver, "_rpc", side_effect=fake_rpc):
                    resolver._latest_usdc_transfer_to("0x" + "1" * 40, 25)

        self.assertIn((16, 25), ranges)
        self.assertIn((6, 15), ranges)
        self.assertIn((1, 5), ranges)
        self.assertTrue(all(end - start + 1 <= 10 for start, end in ranges))

    def test_chunking_preserves_latest_transfer_semantics(self) -> None:
        to_address = "0x" + "1" * 40
        from_address = "0x" + "2" * 40
        to_topic = "0x" + to_address.replace("0x", "").zfill(64)
        from_topic = "0x" + from_address.replace("0x", "").zfill(64)
        log = {
            "topics": [TRANSFER_EVENT_TOPIC, from_topic, to_topic],
            "data": hex(5_000_000),
            "blockNumber": "0x14",
            "logIndex": "0x0",
            "transactionHash": "0xlatest",
        }

        def fake_rpc(method: str, params: list[object]) -> list[dict[str, object]]:
            query = params[0]
            start = int(str(query["fromBlock"]), 16)
            end = int(str(query["toBlock"]), 16)
            if start <= 20 <= end:
                return [log]
            return []

        with mock.patch.dict(os.environ, {"INSPOLY_POLYGON_RPC_GETLOGS_BLOCK_CHUNK": "10"}):
            resolver = FundingResolver(rpc_url="https://example.invalid")
        with mock.patch.object(resolver, "_rpc", side_effect=fake_rpc):
            with mock.patch.object(resolver, "_block_timestamp", return_value=int(datetime(2026, 4, 7, tzinfo=UTC).timestamp())):
                transfer = resolver._latest_usdc_transfer_to(to_address, 25)

        self.assertIsNotNone(transfer)
        self.assertEqual(transfer.tx_hash, "0xlatest")
        self.assertEqual(transfer.amount_usdc, 5.0)

    def test_funding_trace_cache_prevents_duplicate_wallet_hour_trace(self) -> None:
        resolver = FundingResolver(rpc_url="https://example.invalid", persistent_cache_enabled=False)
        as_of = datetime(2026, 4, 7, 12, 10, tzinfo=UTC)

        with mock.patch.object(resolver, "_block_before_timestamp", return_value=100):
            with mock.patch.object(resolver, "_latest_usdc_transfer_to", return_value=None) as mocked_latest:
                first = resolver.analyze("0xABC", as_of)
                second = resolver.analyze("0xabc", as_of + timedelta(minutes=20))

        self.assertFalse(first.funding_found)
        self.assertFalse(second.funding_found)
        self.assertEqual(mocked_latest.call_count, 1)
        health = resolver.health()
        self.assertEqual(health.fundingTraceCacheHitCount, 1)
        self.assertGreaterEqual(health.fundingTraceCacheMissCount, 1)

    def test_persistent_funding_cache_returns_success_without_rpc_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "funding.sqlite"
            as_of = datetime(2026, 4, 7, 12, 10, tzinfo=UTC)
            transfer = FundingTransfer(
                from_address="0x" + "2" * 40,
                to_address="0x" + "1" * 40,
                amount_usdc=3000.0,
                tx_hash="0xfunded",
                block_number=100,
                timestamp=as_of - timedelta(minutes=30),
            )
            resolver = FundingResolver(
                rpc_url="https://example.invalid",
                persistent_cache_path=cache_path,
                persistent_cache_enabled=True,
            )
            with mock.patch.object(resolver, "_block_before_timestamp", return_value=100):
                with mock.patch.object(resolver, "_latest_usdc_transfer_to", return_value=transfer):
                    first = resolver.analyze("0x" + "1" * 40, as_of)

            cached_resolver = FundingResolver(
                rpc_url="https://example.invalid",
                persistent_cache_path=cache_path,
                persistent_cache_enabled=True,
            )
            with mock.patch.object(cached_resolver, "_block_before_timestamp") as mocked_block:
                second = cached_resolver.analyze("0x" + "1" * 40, as_of + timedelta(minutes=20))

            self.assertTrue(first.funding_found)
            self.assertTrue(second.funding_found)
            self.assertTrue(second.funding_trace_from_persistent_cache)
            mocked_block.assert_not_called()
            health = cached_resolver.health()
            self.assertEqual(health.fundingTracePersistentCacheHitCount, 1)
            self.assertEqual(health.fundingTracePersistentCacheMissCount, 0)
            self.assertEqual(health.fundingTraceSucceededCount, 1)

    def test_persistent_cache_returns_none_only_for_successful_none_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "funding.sqlite"
            as_of = datetime(2026, 4, 7, 12, 10, tzinfo=UTC)
            resolver = FundingResolver(
                rpc_url="https://example.invalid",
                persistent_cache_path=cache_path,
                persistent_cache_enabled=True,
            )
            with mock.patch.object(resolver, "_block_before_timestamp", return_value=100):
                with mock.patch.object(resolver, "_latest_usdc_transfer_to", return_value=None):
                    first = resolver.analyze("0xnone", as_of)

            cached_resolver = FundingResolver(
                rpc_url="https://example.invalid",
                persistent_cache_path=cache_path,
                persistent_cache_enabled=True,
            )
            with mock.patch.object(cached_resolver, "_block_before_timestamp") as mocked_block:
                second = cached_resolver.analyze("0xnone", as_of)

            self.assertFalse(first.funding_found)
            self.assertEqual(grade_funding_evidence(first), "none")
            self.assertFalse(second.funding_found)
            self.assertEqual(grade_funding_evidence(second), "none")
            self.assertTrue(second.funding_trace_from_persistent_cache)
            mocked_block.assert_not_called()

    def test_persistent_cache_does_not_convert_rpc_failure_to_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "funding.sqlite"
            as_of = datetime(2026, 4, 7, 12, 10, tzinfo=UTC)
            resolver = FundingResolver(
                rpc_url="https://example.invalid",
                persistent_cache_path=cache_path,
                persistent_cache_enabled=True,
            )
            with mock.patch.object(resolver, "_block_before_timestamp", side_effect=HTTPError("https://x", 429, "Too Many Requests", None, BytesIO(b""))):
                first = resolver.analyze("0xfail", as_of)

            cached_resolver = FundingResolver(
                rpc_url="https://example.invalid",
                persistent_cache_path=cache_path,
                persistent_cache_enabled=True,
            )
            with mock.patch.object(cached_resolver, "_block_before_timestamp") as mocked_block:
                second = cached_resolver.analyze("0xfail", as_of)

            self.assertEqual(grade_funding_evidence(first), FUNDING_EVIDENCE_UNKNOWN)
            self.assertEqual(grade_funding_evidence(second), FUNDING_EVIDENCE_UNKNOWN)
            self.assertTrue(second.funding_trace_from_persistent_cache)
            self.assertEqual(second.funding_trace_cache_status, "failure")
            mocked_block.assert_not_called()
            self.assertEqual(cached_resolver.health().fundingTracePersistentCacheFailureCooldownCount, 1)

    def test_persistent_cache_expired_entries_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "funding.sqlite"
            as_of = datetime(2026, 4, 7, 12, 10, tzinfo=UTC)
            resolver = FundingResolver(
                rpc_url="https://example.invalid",
                persistent_cache_path=cache_path,
                persistent_cache_enabled=True,
            )
            with mock.patch.object(resolver, "_block_before_timestamp", return_value=100):
                with mock.patch.object(resolver, "_latest_usdc_transfer_to", return_value=None):
                    resolver.analyze("0xexpired", as_of)
            with sqlite3.connect(cache_path) as connection:
                connection.execute("UPDATE funding_trace_cache SET expires_at = 0")

            second_resolver = FundingResolver(
                rpc_url="https://example.invalid",
                persistent_cache_path=cache_path,
                persistent_cache_enabled=True,
            )
            with mock.patch.object(second_resolver, "_block_before_timestamp", return_value=100):
                with mock.patch.object(second_resolver, "_latest_usdc_transfer_to", return_value=None) as mocked_latest:
                    second_resolver.analyze("0xexpired", as_of)

            self.assertEqual(mocked_latest.call_count, 1)
            self.assertGreaterEqual(second_resolver.health().fundingTracePersistentCacheExpiredCount, 1)

    def test_persistent_cache_schema_mismatch_is_handled_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "funding.sqlite"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(cache_path) as connection:
                connection.execute(
                    "CREATE TABLE funding_trace_cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO funding_trace_cache_meta (key, value) VALUES ('schema_version', '999')"
                )
            cache = FundingTracePersistentCache(cache_path, enabled=True)

            self.assertTrue(cache.enabled)
            self.assertTrue(cache.schema_mismatch_handled)

    def test_model_behavior_audit_summarizes_persistent_cache_accounting(self) -> None:
        summary = audit_records(
            [
                {
                    "wallet": "0xcached",
                    "candidateAdmissionStage": "normal_candidate",
                    "fundingEvidenceGrade": "none",
                    "fundingTracePersistentCacheEnabled": "Yes",
                    "fundingTracePersistentCacheHitCount": "2",
                    "fundingTracePersistentCacheMissCount": "3",
                    "fundingTracePersistentCacheWriteCount": "1",
                    "fundingTraceFromPersistentCache": "Yes",
                    "fundingTracePersistentCacheStatus": "none",
                }
            ]
        )

        self.assertEqual(summary["funding_trace_persistent_cache_hit_rows"], 1)
        self.assertEqual(summary["funding_trace_persistent_cache_hit_count"], 2)
        self.assertEqual(summary["funding_trace_persistent_cache_miss_count"], 3)
        self.assertEqual(summary["funding_trace_persistent_cache_write_count"], 1)

    def test_model_behavior_audit_does_not_require_endpoint_fallback_when_cache_satisfies_trace(self) -> None:
        summary = audit_records(
            [],
            funnels=[
                {
                    "enabled": True,
                    "fundingResolverAvailable": True,
                    "fundingResolverFunctionalStatus": "available_for_funding_trace",
                    "fundingTraceAttemptedCount": 2,
                    "fundingTraceSucceededCount": 2,
                    "fundingTraceEndpointPoolSize": 4,
                    "fundingTraceEndpointSummary": [
                        {"request_count": 0},
                        {"request_count": 0},
                        {"request_count": 0},
                        {"request_count": 0},
                    ],
                    "fundingTraceLogChunksAttempted": 0,
                    "fundingTraceRateLimitedCount": 0,
                    "fundingTracePersistentCacheHitCount": 2,
                }
            ],
        )

        warning_codes = {warning["code"] for warning in summary["warnings"]}
        self.assertNotIn("single_endpoint_used_with_multiple_configured", warning_codes)

    def test_funding_report_lines_include_persistent_cache_accounting(self) -> None:
        lines = _funding_availability_report_lines(
            {
                "fundingResolverAvailable": True,
                "fundingResolverFunctionalStatus": "available_for_funding_trace",
                "fundingTraceAttemptedCount": 1,
                "fundingTraceSucceededCount": 1,
                "fundingTracePersistentCacheEnabled": True,
                "fundingTracePersistentCacheHitCount": 1,
                "fundingTracePersistentCacheMissCount": 0,
                "fundingTracePersistentCacheWriteCount": 1,
            }
        )

        self.assertIn("Funding trace persistent cache enabled/hits/misses/writes", "\n".join(lines))

    def test_event_forensic_wallet_rows_preserve_suspicious_funding_grade_fields(self) -> None:
        rows = self._event_analyzer()._build_wallet_rankings(
            [
                {
                    "id": "trade-1",
                    "wallet": "0xwallet",
                    "walletShort": "0xwall...let",
                    "profileUrl": "https://polymarket.com/profile/0xwallet",
                    "username": "Not available",
                    "eventForensicScore": 50,
                    "laterWon": False,
                    "openingExposure": True,
                    "relatedMarketTrades": 0,
                    "selectedConditionId": "cond-selected",
                    "selectedMarketSlug": "market-slug",
                    "selectedMarketTitle": "Market title",
                    "parentEventSlug": "event-slug",
                    "fundingEvidenceGrade": "multi_hop_unknown",
                    "suspiciousFundingQuality": "strong",
                    "suspiciousFundingQualityReasons": "recent aligned funding",
                    "suspiciousFundingHardEvidenceEligible": "Yes",
                    "suspiciousFundingTraceSucceeded": "Yes",
                    "suspiciousFundingTraceDepth": "2",
                    "suspiciousFundingAmountUsd": "2500.0",
                    "rawMetrics": {
                        "shared_funding_source_flag": "No",
                        "specialist_explained_flag": "No",
                        "low_analyst_value_flag": "No",
                        "formal_win_rate_may_be_overstated": "No",
                        "reactivated_after_dormancy_flag": "No",
                        "post_trade_dormancy_flag": "No",
                        "event_family_repeat_flag": "No",
                        "split_wallet_pattern_flag": "No",
                        "fundingEvidenceGrade": "multi_hop_unknown",
                        "suspiciousFundingQuality": "strong",
                        "suspiciousFundingHardEvidenceEligible": "Yes",
                    },
                }
            ],
            [],
            analysis_scope="market",
            sibling_market_activity={},
        )

        self.assertEqual(rows[0]["fundingEvidenceGrade"], "multi_hop_unknown")
        self.assertEqual(rows[0]["suspiciousFundingQuality"], "strong")
        self.assertEqual(rows[0]["suspiciousFundingTraceSucceeded"], "Yes")
        self.assertEqual(rows[0]["suspiciousFundingTraceDepth"], "2")

    def test_model_behavior_audit_flags_lightweight_available_trace_failed(self) -> None:
        summary = audit_records(
            [],
            funnels=[
                {
                    "enabled": True,
                    "counts": {
                        "subThresholdAboveStructuralFloorTrades": 2,
                        "groupedConditionDirectionGroups": 1,
                    },
                    "fundingResolverAvailable": False,
                    "fundingResolverFunctionalStatus": "rate_limited_for_funding_trace",
                    "fundingResolverUnavailableReason": "rate_limited",
                    "fundingResolverDisabledReason": "HTTP 429",
                    "fundingTraceAttemptedCount": 2,
                    "fundingTraceSucceededCount": 0,
                    "fundingTraceFailedCount": 2,
                    "fundingTraceRateLimitedCount": 2,
                    "fundingTraceEndpointPoolSize": 2,
                    "fundingTraceFallbackEndpointCount": 0,
                    "preAdmissionFundingTraceAttemptedCount": 1,
                    "preAdmissionFundingTraceSucceededCount": 0,
                    "preAdmissionFundingAssessmentStatus": "funding_unavailable_not_assessed",
                }
            ],
        )

        warning_codes = {warning["code"] for warning in summary["warnings"]}
        self.assertIn("lightweight_available_but_funding_trace_failed", warning_codes)
        self.assertIn("all_funding_traces_failed_rate_limited", warning_codes)
        self.assertIn("no_endpoint_fallback_after_429", warning_codes)

    def test_funding_report_wording_for_lightweight_only_rate_limit(self) -> None:
        lines = _funding_availability_report_lines(
            {
                "fundingResolverAvailable": False,
                "fundingResolverFunctionalStatus": "rate_limited_for_funding_trace",
                "fundingTraceAttemptedCount": 2,
                "fundingTraceSucceededCount": 0,
                "fundingTraceFailedCount": 2,
                "fundingTraceSkippedCount": 0,
                "fundingTraceRateLimitedCount": 2,
                "fundingTraceEndpointPoolSize": 4,
                "fundingTraceEndpointAvailableCount": 3,
                "fundingTraceEndpointCooldownCount": 1,
            }
        )

        self.assertIn(
            "- Funding resolver: lightweight RPC available, funding trace blocked by rate limits",
            lines,
        )
        self.assertTrue(any("Funding trace endpoint pool: size=4" in line for line in lines))

    def test_funding_report_wording_for_no_trace_attempts(self) -> None:
        lines = _funding_availability_report_lines(
            {
                "fundingResolverAvailable": False,
                "fundingResolverFunctionalStatus": "not_assessed",
                "fundingTraceAttemptedCount": 0,
                "fundingTraceSucceededCount": 0,
                "fundingTraceEndpointPoolSize": 4,
                "fundingTraceEndpointAvailableCount": 4,
                "fundingTraceEndpointCooldownCount": 0,
            }
        )

        rendered = "\n".join(lines)
        self.assertIn("Funding resolver: not assessed; no funding trace candidates", rendered)
        self.assertNotIn("unavailable - not_configured", rendered)

    def test_model_behavior_audit_does_not_flag_not_assessed_no_trace_attempts(self) -> None:
        summary = audit_records(
            [],
            funnels=[
                {
                    "enabled": True,
                    "counts": {},
                    "fundingResolverAvailable": False,
                    "fundingResolverFunctionalStatus": "not_assessed",
                    "fundingTraceAttemptedCount": 0,
                    "fundingTraceSucceededCount": 0,
                    "fundingTraceEndpointPoolSize": 4,
                }
            ],
        )

        warning_codes = {warning["code"] for warning in summary["warnings"]}
        self.assertNotIn("missing_resolver_disabled_reason", warning_codes)
        self.assertNotIn("resolver_unavailable_structural_pre_admission", warning_codes)
        self.assertEqual(summary["pre_admission_funnel"]["funding_resolver_availability"], {"not_assessed": 1})

    def test_model_behavior_audit_uses_wallet_opening_count_for_funding_quality_support(self) -> None:
        summary = audit_records(
            [
                {
                    "wallet": "0xwallet",
                    "walletOpeningEntryCount": 1,
                    "hardEvidenceSources": ["suspicious_recent_funding"],
                    "hardEvidenceStrength": "Strong",
                    "hardEvidenceReviewTier": "Hard Evidence Review",
                    "fundingEvidenceGrade": "multi_hop_unknown",
                    "suspiciousFundingQuality": "strong",
                    "suspiciousFundingRecentEnough": "Yes",
                    "suspiciousFundingAmountAligned": "Yes",
                    "suspiciousFundingHardEvidenceEligible": "Yes",
                    "suspiciousFundingIndependentSupport": "Yes",
                    "suspiciousFundingIndependentSupportSources": "split_wallet_pattern",
                }
            ]
        )

        warning_codes = {warning["code"] for warning in summary["warnings"]}
        self.assertNotIn("multi_hop_unknown_mapped_strong_without_quality_support", warning_codes)

    def test_funding_resolver_classifies_all_auth_failures(self) -> None:
        resolver = FundingResolver(
            rpc_url="https://bad-one.example,https://bad-two.example",
            persistent_cache_enabled=False,
        )
        auth_error = HTTPError(
            "https://bad-one.example",
            403,
            "Forbidden",
            hdrs=None,
            fp=BytesIO(b""),
        )

        with mock.patch("app.funding_context._post_json", side_effect=auth_error):
            context = resolver.analyze("0xabc", datetime(2026, 4, 7, tzinfo=UTC))

        health = resolver.health()
        self.assertFalse(context.funding_found)
        self.assertFalse(health.fundingResolverAvailable)
        self.assertTrue(health.fundingResolverAuthError)
        self.assertEqual(health.fundingResolverUnavailableReason, "auth_error")

    def test_score_trade_records_funding_evidence_grade(self) -> None:
        trade = _trade(
            trade_id="funding-grade-trade",
            wallet="0xfunded",
            condition_id="cond-funding-grade",
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.42",
            size="2500",
            title="Funding grade case?",
            slug="funding-grade-case",
            event_slug="funding-grade-case",
        )
        market = _market(
            condition_id=trade.condition_id,
            slug=trade.slug,
            question=trade.title,
        )
        case = _score_trade(
            trade=trade,
            market=market,
            trade_domain="Middle East",
            wallet_inspection=_wallet_inspection(2),
            wallet_performance=_wallet_performance(),
            wallet_window_trades=[trade],
            wallet_history_trades=[trade],
            market_window_trades=[trade],
            domain_window_trades=[trade],
            event_context=_event_context(),
            funding_context=FundingContext(
                funding_found=True,
                source_category="cex",
                origin_category="cex",
                source_label="Binance",
                funding_depth=1,
                funding_graph_key_proxy="binance|2026-04-07T12|2500",
                funding_fingerprint="binance|2500|2026-04-07T12|depth:1",
            ),
            include_below_threshold=True,
        )

        self.assertIsNotNone(case)
        assert case is not None
        self.assertEqual(case.raw_metrics["funding_evidence_grade"], "cex_proxy")
        self.assertEqual(case.raw_metrics["fundingEvidenceGrade"], "cex_proxy")

    def test_cex_proxy_annotation_alone_stays_weak_context(self) -> None:
        first_market = _market(
            condition_id="cond-cex-one",
            slug="cex-proxy-one",
            question="CEX proxy one?",
        )
        second_market = _market(
            condition_id="cond-cex-two",
            slug="cex-proxy-two",
            question="CEX proxy two?",
        )
        base_raw = {
            "trade_state": "increase",
            "opening_exposure_flag": "Yes",
            "economic_direction": "long_yes",
            "funding_graph_key": "binance|2026-04-07T12|2500",
            "funding_graph_key_strict": "",
            "funding_graph_key_proxy": "binance|2026-04-07T12|2500",
            "funding_fingerprint": "binance|2500|2026-04-07T12|depth:1",
            "funding_evidence_grade": "cex_proxy",
            "shared_funding_source_flag": "No",
            "shared_funding_source_cluster_size": "0",
            "split_wallet_pattern_flag": "No",
            "cex_proxy_cluster_flag": "No",
            "funding_proxy_tight_cohort_flag": "No",
            "funding_proxy_tight_cohort_size": "0",
            "resolution_gap_flag": "No",
            "structural_concern_flag": "No",
            "materially_uncertain_flag": "Yes",
            "decisive_timing_edge_flag": "No",
            "strong_timing_proof_count": "0",
            "supporting_booster_count": "0",
            "benign_pattern_flag": "No",
            "credibility_gamed_flag": "No",
            "hard_resolution_gap_flag": "No",
            "soft_resolution_gap_flag": "No",
            "reactivated_after_dormancy_flag": "No",
            "event_family_repeat_flag": "No",
            "suspicious_funding_flag": "No",
            "coordinated_sizing_cluster_flag": "No",
            "hard_public_information_flag": "No",
            "economic_win_rate_clears_threshold": "No",
            "win_rate_clears_threshold": "No",
            "wallet_economic_sample_size": "8",
        }
        first = _flagged_case(
            trade=_trade(
                trade_id="cex-weak-1",
                wallet="0xcexweak1",
                condition_id=first_market.condition_id,
                asset_id="asset-yes",
                timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
                price="0.42",
                size="2500",
                title=first_market.question,
                slug=first_market.slug,
                event_slug=first_market.slug,
            ),
            market=first_market,
            raw_metrics=dict(base_raw),
            flags=[],
        )
        second = _flagged_case(
            trade=_trade(
                trade_id="cex-weak-2",
                wallet="0xcexweak2",
                condition_id=second_market.condition_id,
                asset_id="asset-yes",
                timestamp=datetime(2026, 4, 7, 12, 8, tzinfo=UTC),
                price="0.42",
                size="2500",
                title=second_market.question,
                slug=second_market.slug,
                event_slug=second_market.slug,
            ),
            market=second_market,
            raw_metrics=dict(base_raw),
            flags=[],
        )

        _annotate_shared_funding_links([first, second])
        _annotate_hard_evidence_review([first, second], evidence_availability_stage="archive_no_outcome_context")

        self.assertEqual(first.raw_metrics["cex_proxy_cluster_flag"], "Yes")
        self.assertEqual(first.raw_metrics["shared_funding_source_flag"], "No")
        self.assertEqual(first.raw_metrics["funding_proxy_tight_cohort_flag"], "No")
        self.assertEqual(first.raw_metrics["split_wallet_pattern_flag"], "No")
        self.assertEqual(first.raw_metrics["hardEvidenceReviewTier"], "")

    def test_cex_proxy_tight_cohort_is_context_not_hard_evidence(self) -> None:
        market = _market(
            condition_id="cond-cex-tight",
            slug="cex-proxy-tight",
            question="CEX proxy tight cohort?",
        )
        base_raw = {
            "trade_state": "increase",
            "opening_exposure_flag": "Yes",
            "economic_direction": "long_yes",
            "funding_graph_key": "binance|2026-04-07T12|2500",
            "funding_graph_key_strict": "",
            "funding_graph_key_proxy": "binance|2026-04-07T12|2500",
            "funding_fingerprint": "binance|2500|2026-04-07T12|depth:1",
            "funding_evidence_grade": "cex_proxy",
            "shared_funding_source_flag": "No",
            "shared_funding_source_cluster_size": "0",
            "split_wallet_pattern_flag": "No",
            "cex_proxy_cluster_flag": "No",
            "funding_proxy_tight_cohort_flag": "No",
            "funding_proxy_tight_cohort_size": "0",
            "resolution_gap_flag": "No",
            "structural_concern_flag": "No",
            "materially_uncertain_flag": "Yes",
            "decisive_timing_edge_flag": "Yes",
            "strong_timing_proof_count": "1",
            "supporting_booster_count": "1",
            "benign_pattern_flag": "No",
            "credibility_gamed_flag": "No",
            "hard_resolution_gap_flag": "No",
            "soft_resolution_gap_flag": "No",
            "reactivated_after_dormancy_flag": "No",
            "event_family_repeat_flag": "No",
            "suspicious_funding_flag": "No",
            "coordinated_sizing_cluster_flag": "No",
            "hard_public_information_flag": "No",
            "economic_win_rate_clears_threshold": "No",
            "win_rate_clears_threshold": "No",
            "wallet_economic_sample_size": "8",
        }
        cases = []
        for index in range(2):
            trade = _trade(
                trade_id=f"cex-tight-{index}",
                wallet=f"0xcextight{index}",
                condition_id=market.condition_id,
                asset_id="asset-yes",
                timestamp=datetime(2026, 4, 7, 12, index * 8, tzinfo=UTC),
                price="0.42",
                size="2500",
                title=market.question,
                slug=market.slug,
                event_slug=market.slug,
            )
            case = _flagged_case(trade=trade, market=market, raw_metrics=dict(base_raw), flags=[])
            case.severity = "Low Risk"
            case.suspicion_score = 12
            cases.append(case)

        _annotate_shared_funding_links(cases)
        _annotate_hard_evidence_review(cases, evidence_availability_stage="archive_no_outcome_context")

        self.assertEqual(cases[0].raw_metrics["shared_funding_source_flag"], "Yes")
        self.assertEqual(cases[0].raw_metrics["funding_proxy_tight_cohort_flag"], "Yes")
        self.assertEqual(cases[0].raw_metrics["split_wallet_pattern_flag"], "Yes")
        self.assertEqual(cases[0].raw_metrics["hardEvidenceSources"], "")
        self.assertEqual(cases[0].raw_metrics["hardEvidenceReviewTier"], "")
        self.assertNotEqual(cases[0].severity, "Strong Risk")

    def test_structural_pre_admission_floor_and_normal_candidates_unchanged(self) -> None:
        self.assertEqual(_structural_pre_admission_floor(Decimal("1000")), Decimal("200.00"))
        self.assertEqual(_structural_pre_admission_floor(Decimal("100")), STRUCTURAL_PRE_ADMISSION_FLOOR_USD)
        self.assertEqual(_structural_pre_admission_floor(Decimal("10000")), STRUCTURAL_PRE_ADMISSION_MAX_FLOOR_USD)
        trade = _trade(
            trade_id="normal-threshold",
            wallet="0xnormal",
            condition_id="cond-normal",
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.50",
            size="2500",
            title="Normal admission?",
            slug="normal-admission",
            event_slug="normal-admission",
        )
        baseline = _build_candidate_trade_set([trade], minimum_notional=Decimal("1000"))
        enabled = _build_candidate_trade_set(
            [trade],
            minimum_notional=Decimal("1000"),
            enable_structural_pre_admission=True,
            structural_pre_admission_metadata={},
        )
        self.assertEqual([item.trade_id for item in baseline], [trade.trade_id])
        self.assertEqual([item.trade_id for item in enabled], [trade.trade_id])

    def test_structural_pre_admission_strict_shared_funding_group(self) -> None:
        now = datetime(2026, 4, 7, 12, 0, tzinfo=UTC)
        trades = [
            _trade(
                trade_id="pre-strict-1",
                wallet="0xpre1",
                condition_id="cond-pre-strict",
                asset_id="asset-yes",
                timestamp=now,
                price="0.50",
                size="1200",
                title="Strict pre admission?",
                slug="strict-pre",
                event_slug="strict-pre",
            ),
            _trade(
                trade_id="pre-strict-2",
                wallet="0xpre2",
                condition_id="cond-pre-strict",
                asset_id="asset-yes",
                timestamp=now + timedelta(minutes=10),
                price="0.53",
                size="1000",
                title="Strict pre admission?",
                slug="strict-pre",
                event_slug="strict-pre",
            ),
        ]
        metadata = _build_structural_pre_admission_metadata(
            trades,
            minimum_notional=Decimal("1000"),
            funding_context_by_trade_id={
                trade.trade_id: FundingContext(
                    funding_found=True,
                    source_category="unknown",
                    origin_category="unknown",
                    funding_depth=1,
                    funding_graph_key_strict="0xstrict-pre",
                )
                for trade in trades
            },
            wallet_history_by_wallet={trade.wallet: [trade] for trade in trades},
            enable_structural_pre_admission=True,
        )
        candidate_trades = _build_candidate_trade_set(
            trades,
            minimum_notional=Decimal("1000"),
            enable_structural_pre_admission=True,
            structural_pre_admission_metadata=metadata,
        )

        self.assertEqual({trade.trade_id for trade in candidate_trades}, {"pre-strict-1", "pre-strict-2"})
        self.assertEqual(metadata["pre-strict-1"]["candidateAdmissionReason"], "strict_shared_funding_group")
        self.assertEqual(metadata["pre-strict-1"]["groupedCandidateStrictFunding"], "Yes")
        self.assertEqual(metadata["pre-strict-1"]["groupedCandidateProxyOnly"], "No")

    def test_structural_pre_admission_rejects_proxy_and_timing_only_groups(self) -> None:
        now = datetime(2026, 4, 7, 12, 0, tzinfo=UTC)
        trades = [
            _trade(
                trade_id=f"proxy-{index}",
                wallet=f"0xproxy{index}",
                condition_id="cond-proxy",
                asset_id="asset-yes",
                timestamp=now + timedelta(minutes=index * 5),
                price="0.50",
                size="1200",
                title="Proxy pre admission?",
                slug="proxy-pre",
                event_slug="proxy-pre",
            )
            for index in range(2)
        ]
        for grade, context in {
            "cex": FundingContext(
                funding_found=True,
                source_category="cex",
                origin_category="cex",
                funding_depth=1,
                funding_graph_key_proxy="binance|bucket",
                funding_fingerprint="binance|bucket",
            ),
            "bridge": FundingContext(
                funding_found=True,
                source_category="bridge",
                origin_category="bridge",
                funding_depth=1,
                funding_graph_key_proxy="bridge|bucket",
                funding_fingerprint="bridge|bucket",
            ),
            "none": FundingContext(funding_found=False),
        }.items():
            with self.subTest(grade=grade):
                metadata = _build_structural_pre_admission_metadata(
                    trades,
                    minimum_notional=Decimal("1000"),
                    funding_context_by_trade_id={trade.trade_id: context for trade in trades},
                    wallet_history_by_wallet={trade.wallet: [trade] for trade in trades},
                    enable_structural_pre_admission=True,
                )
                self.assertEqual(metadata, {})

    def test_structural_pre_admission_does_not_admit_unknown_funding_when_resolver_unavailable(self) -> None:
        trades = [
            _trade(
                trade_id=f"unavailable-{index}",
                wallet=f"0xunavailable{index}",
                condition_id="cond-unavailable",
                asset_id="asset-yes",
                timestamp=datetime(2026, 4, 7, 12, index * 5, tzinfo=UTC),
                price="0.50",
                size="1200",
                title="Unavailable funding?",
                slug="unavailable-funding",
                event_slug="unavailable-funding",
            )
            for index in range(2)
        ]
        funding = {
            trade.trade_id: unknown_funding_context("HTTPError: HTTP Error 401: Unauthorized")
            for trade in trades
        }
        metadata = _build_structural_pre_admission_metadata(
            trades,
            minimum_notional=Decimal("1000"),
            funding_context_by_trade_id=funding,
            wallet_history_by_wallet={trade.wallet: [trade] for trade in trades},
            enable_structural_pre_admission=True,
        )
        funnel = _build_structural_pre_admission_funnel(
            trades,
            minimum_notional=Decimal("1000"),
            pre_admission_pool=trades,
            funding_context_by_trade_id=funding,
            admission_metadata=metadata,
            funding_resolver_available=False,
            funding_resolver_disabled_reason="HTTPError: HTTP Error 401: Unauthorized",
            funding_resolver_auth_error=True,
            pre_admission_funding_trace_attempted_ids={trade.trade_id for trade in trades},
        )

        self.assertEqual(metadata, {})
        self.assertEqual(funnel["preAdmissionFundingAssessmentStatus"], "funding_unavailable_not_assessed")
        self.assertGreater(funnel["preAdmissionFundingUnknownCount"], 0)
        self.assertEqual(
            funnel["topRejectedGroups"][0]["candidateAdmissionRejectedReason"],
            "funding_resolver_unavailable",
        )

    def test_structural_pre_admission_single_exceptions_validate_after_scoring(self) -> None:
        market = _market(
            condition_id="cond-pre-single",
            slug="pre-single",
            question="Single pre-admission?",
            liquidity="500000",
        )
        trade = _trade(
            trade_id="pre-suspicious",
            wallet="0xprefunded",
            condition_id=market.condition_id,
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.42",
            size="800",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
        )
        funding = FundingContext(
            funding_found=True,
            source_category="dex",
            origin_category="dex",
            funding_depth=1,
            funding_graph_key_strict="0xdex-pre",
            suspicious_funding_flag=True,
        )
        metadata = _build_structural_pre_admission_metadata(
            [trade],
            minimum_notional=Decimal("1000"),
            funding_context_by_trade_id={trade.trade_id: funding},
            wallet_history_by_wallet={trade.wallet: [trade]},
            enable_structural_pre_admission=True,
        )
        case = _score_trade(
            trade=trade,
            market=market,
            trade_domain="Middle East",
            wallet_inspection=_wallet_inspection(2),
            wallet_performance=_wallet_performance(),
            wallet_window_trades=[trade],
            wallet_history_trades=[trade],
            market_window_trades=[trade],
            domain_window_trades=[trade],
            event_context=_event_context(),
            funding_context=funding,
            include_below_threshold=True,
        )
        self.assertIsNotNone(case)
        assert case is not None
        _apply_candidate_admission_metadata(case, metadata[trade.trade_id])
        _validate_candidate_admissions([case])
        self.assertEqual(case.raw_metrics["candidateAdmissionStage"], "pre_admitted_validated")
        self.assertEqual(case.raw_metrics["candidateAdmissionValidatedOpeningExposure"], "Yes")

        near_trade = _trade(
            trade_id="pre-suspicious-near",
            wallet="0xprefunded2",
            condition_id=market.condition_id,
            asset_id="asset-yes",
            timestamp=trade.timestamp,
            price="0.96",
            size="500",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
        )
        near_case = _score_trade(
            trade=near_trade,
            market=market,
            trade_domain="Middle East",
            wallet_inspection=_wallet_inspection(2),
            wallet_performance=_wallet_performance(),
            wallet_window_trades=[near_trade],
            wallet_history_trades=[near_trade],
            market_window_trades=[near_trade],
            domain_window_trades=[near_trade],
            event_context=_event_context(),
            funding_context=funding,
            include_below_threshold=True,
        )
        self.assertIsNotNone(near_case)
        assert near_case is not None
        _apply_candidate_admission_metadata(
            near_case,
            {
                **metadata[trade.trade_id],
                "candidateAdmissionReason": "suspicious_recent_funding",
            },
        )
        self.assertEqual(near_case.raw_metrics["candidateAdmissionStage"], "pre_admitted_rejected")
        self.assertEqual(near_case.raw_metrics["candidateAdmissionRejectedReason"], "near_certainty_suppressed")

    def test_structural_pre_admission_dormant_reactivation_and_floor(self) -> None:
        trade = _trade(
            trade_id="pre-dormant",
            wallet="0xdormantpre",
            condition_id="cond-dormant-pre",
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.50",
            size="900",
            title="Dormant pre admission?",
            slug="dormant-pre",
            event_slug="dormant-pre",
        )
        prior = _trade(
            trade_id="pre-dormant-prior",
            wallet=trade.wallet,
            condition_id="older-cond",
            asset_id="older-asset",
            timestamp=trade.timestamp - timedelta(days=100),
            price="0.50",
            size="100",
            title="Older trade",
            slug="older",
            event_slug="older",
        )
        below_floor = _trade(
            trade_id="below-floor",
            wallet="0xbelow",
            condition_id=trade.condition_id,
            asset_id="asset-yes",
            timestamp=trade.timestamp,
            price="0.50",
            size="100",
            title=trade.title,
            slug=trade.slug,
            event_slug=trade.event_slug,
        )
        metadata = _build_structural_pre_admission_metadata(
            [trade, below_floor],
            minimum_notional=Decimal("1000"),
            funding_context_by_trade_id={},
            wallet_history_by_wallet={trade.wallet: [prior, trade], below_floor.wallet: [below_floor]},
            enable_structural_pre_admission=True,
        )

        self.assertEqual(metadata["pre-dormant"]["candidateAdmissionReason"], "dormant_reactivation")
        self.assertNotIn("below-floor", metadata)

    def test_structural_pre_admission_does_not_open_disallowed_context_only_gates(self) -> None:
        now = datetime(2026, 4, 7, 12, 0, tzinfo=UTC)
        disallowed = [
            _trade(
                trade_id="event-family-only",
                wallet="0xfamily",
                condition_id="cond-disallowed",
                asset_id="asset-yes",
                timestamp=now,
                price="0.40",
                size="1500",
                title="Event family only?",
                slug="event-family-only",
                event_slug="event-family-only",
            ),
            _trade(
                trade_id="low-prob-winner-only",
                wallet="0xwinner",
                condition_id="cond-disallowed",
                asset_id="asset-yes",
                timestamp=now + timedelta(minutes=1),
                price="0.20",
                size="3000",
                title="Low probability winner only?",
                slug="winner-only",
                event_slug="winner-only",
            ),
            _trade(
                trade_id="high-impact-repricing-only",
                wallet="0xrepricing",
                condition_id="cond-disallowed",
                asset_id="asset-yes",
                timestamp=now + timedelta(minutes=2),
                price="0.45",
                size="1500",
                title="High impact repricing only?",
                slug="repricing-only",
                event_slug="repricing-only",
            ),
        ]
        metadata = _build_structural_pre_admission_metadata(
            disallowed,
            minimum_notional=Decimal("1000"),
            funding_context_by_trade_id={trade.trade_id: FundingContext(funding_found=False) for trade in disallowed},
            wallet_history_by_wallet={trade.wallet: [trade] for trade in disallowed},
            enable_structural_pre_admission=True,
        )

        self.assertEqual(metadata, {})

    def test_pre_admitted_strict_group_is_scored_not_automatic_strong_and_hard_review_visible(self) -> None:
        market = _market(
            condition_id="cond-pre-hard",
            slug="pre-hard",
            question="Pre-admitted strict hard review?",
            liquidity="500000",
        )
        trades = [
            _trade(
                trade_id=f"pre-hard-{index}",
                wallet=f"0xprehard{index}",
                condition_id=market.condition_id,
                asset_id="asset-yes",
                timestamp=datetime(2026, 4, 7, 12, index * 8, tzinfo=UTC),
                price="0.50",
                size="1100",
                title=market.question,
                slug=market.slug,
                event_slug=market.slug,
            )
            for index in range(2)
        ]
        funding_contexts = {
            trade.trade_id: FundingContext(
                funding_found=True,
                source_category="unknown",
                origin_category="unknown",
                funding_depth=1,
                funding_graph_key_strict="0xpre-hard",
            )
            for trade in trades
        }
        metadata = _build_structural_pre_admission_metadata(
            trades,
            minimum_notional=Decimal("1000"),
            funding_context_by_trade_id=funding_contexts,
            wallet_history_by_wallet={trade.wallet: [trade] for trade in trades},
            enable_structural_pre_admission=True,
        )
        cases = []
        for trade in trades:
            case = _score_trade(
                trade=trade,
                market=market,
                trade_domain="Middle East",
                wallet_inspection=_wallet_inspection(2),
                wallet_performance=_wallet_performance(),
                wallet_window_trades=[trade],
                wallet_history_trades=[trade],
                market_window_trades=trades,
                domain_window_trades=trades,
                event_context=_event_context(),
                funding_context=funding_contexts[trade.trade_id],
                include_below_threshold=True,
            )
            self.assertIsNotNone(case)
            assert case is not None
            _apply_candidate_admission_metadata(case, metadata[trade.trade_id])
            case.confidence_score = 40
            cases.append(case)

        _annotate_shared_funding_links(cases)
        _validate_candidate_admissions(cases)
        _annotate_hard_evidence_review(cases, evidence_availability_stage="archive_no_outcome_context")

        self.assertTrue(all(case.raw_metrics["candidateAdmissionStage"] == "pre_admitted_validated" for case in cases))
        self.assertNotEqual(cases[0].severity, "Strong Risk")
        self.assertEqual(cases[0].raw_metrics["hardEvidenceReviewTier"], HARD_EVIDENCE_REVIEW_TIER)
        self.assertEqual(_visibility_tier_for_case(cases[0]), HARD_EVIDENCE_REVIEW_TIER)

    def test_pre_admitted_strict_group_keeps_suppressors_visible(self) -> None:
        market = _market(
            condition_id="cond-pre-near",
            slug="pre-near",
            question="Pre-admitted near certainty strict group?",
            liquidity="500000",
        )
        trades = [
            _trade(
                trade_id=f"pre-near-{index}",
                wallet=f"0xprenear{index}",
                condition_id=market.condition_id,
                asset_id="asset-yes",
                timestamp=datetime(2026, 4, 7, 12, index * 5, tzinfo=UTC),
                price="0.96",
                size="600",
                title=market.question,
                slug=market.slug,
                event_slug=market.slug,
            )
            for index in range(2)
        ]
        funding_contexts = {
            trade.trade_id: FundingContext(
                funding_found=True,
                source_category="unknown",
                origin_category="unknown",
                funding_depth=1,
                funding_graph_key_strict="0xpre-near",
            )
            for trade in trades
        }
        metadata = _build_structural_pre_admission_metadata(
            trades,
            minimum_notional=Decimal("1000"),
            funding_context_by_trade_id=funding_contexts,
            wallet_history_by_wallet={trade.wallet: [trade] for trade in trades},
            enable_structural_pre_admission=True,
        )
        cases = []
        for trade in trades:
            case = _score_trade(
                trade=trade,
                market=market,
                trade_domain="Middle East",
                wallet_inspection=_wallet_inspection(2),
                wallet_performance=_wallet_performance(),
                wallet_window_trades=[trade],
                wallet_history_trades=[trade],
                market_window_trades=trades,
                domain_window_trades=trades,
                event_context=_event_context(),
                funding_context=funding_contexts[trade.trade_id],
                include_below_threshold=True,
            )
            self.assertIsNotNone(case)
            assert case is not None
            _apply_candidate_admission_metadata(case, metadata[trade.trade_id])
            cases.append(case)

        _annotate_shared_funding_links(cases)
        _validate_candidate_admissions(cases)
        _annotate_hard_evidence_review(cases, evidence_availability_stage="archive_no_outcome_context")

        self.assertEqual(cases[0].raw_metrics["candidateAdmissionStage"], "pre_admitted_validated")
        self.assertIn("near_certainty_trade", cases[0].flags)
        self.assertTrue(cases[0].reasons_against)
        self.assertEqual(cases[0].raw_metrics["hardEvidenceReviewTier"], HARD_EVIDENCE_REVIEW_TIER)

    def test_event_forensic_visibility_includes_valid_pre_admitted_below_threshold_market_scope_only(self) -> None:
        visible = _visible_trade_payloads(
            [
                {
                    "id": "below-valid",
                    "conditionId": "selected-cond",
                    "positionSize": 600.0,
                    "candidateAdmissionStage": "pre_admitted_validated",
                    "rawMetrics": {"candidateAdmissionStage": "pre_admitted_validated"},
                },
                {
                    "id": "below-normal",
                    "conditionId": "selected-cond",
                    "positionSize": 600.0,
                    "candidateAdmissionStage": "normal_candidate",
                    "rawMetrics": {"candidateAdmissionStage": "normal_candidate"},
                },
            ],
            minimum_notional=Decimal("1000"),
        )
        self.assertEqual([item["id"] for item in visible], ["below-valid"])
        scoped = _scope_filter_trades(
            [
                _trade(
                    trade_id="selected",
                    wallet="0xscope",
                    condition_id="selected-cond",
                    asset_id="asset-yes",
                    timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
                    price="0.50",
                    size="1200",
                    title="Selected",
                    slug="selected",
                    event_slug="scope",
                ),
                _trade(
                    trade_id="sibling",
                    wallet="0xscope2",
                    condition_id="sibling-cond",
                    asset_id="asset-yes",
                    timestamp=datetime(2026, 4, 7, 12, 1, tzinfo=UTC),
                    price="0.50",
                    size="1200",
                    title="Sibling",
                    slug="sibling",
                    event_slug="scope",
                ),
            ],
            selected_condition_id="selected-cond",
        )
        pool = _structural_pre_admission_prefunding_pool(
            scoped,
            minimum_notional=Decimal("1000"),
            normal_candidate_ids=set(),
        )
        self.assertEqual([trade.trade_id for trade in pool], ["selected"])

    def test_archive_and_event_outputs_expose_candidate_admission_fields(self) -> None:
        market = _market(
            condition_id="cond-output-fields",
            slug="output-fields",
            question="Output fields?",
        )
        trade = _trade(
            trade_id="output-fields",
            wallet="0xoutput",
            condition_id=market.condition_id,
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.50",
            size="1200",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
        )
        case = _flagged_case(
            trade=trade,
            market=market,
            raw_metrics={
                "candidateAdmissionReason": "strict_shared_funding_group",
                "candidateAdmissionStage": "pre_admitted_validated",
                "candidateAdmissionEvidenceSources": "strict_shared_funding_source",
                "candidateAdmissionFloorNotional": "200.00",
                "groupedCandidateId": "group-1",
                "groupedCandidateAggregateNotional": "1200.00",
                "groupedCandidateWalletCount": "2",
                "groupedCandidateStrictFunding": "Yes",
                "groupedCandidateProxyOnly": "No",
                "groupedCandidateFundingGrade": "direct_strict",
                "groupedCandidateTimeSpanMinutes": "5.0",
                "groupedCandidatePriceBand": "0.01",
                "candidateAdmissionValidatedOpeningExposure": "Yes",
                "candidateAdmissionRejectedReason": "",
            },
            flags=[],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "flagged.csv"
            _write_flagged_csv(path, [case])
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                row = next(reader)
            self.assertEqual(row["candidateAdmissionReason"], "strict_shared_funding_group")
            self.assertEqual(row["groupedCandidateFundingGrade"], "direct_strict")

    def test_candidate_admission_funnel_files_roundtrip_and_absent_when_disabled(self) -> None:
        trade = _trade(
            trade_id="funnel-1",
            wallet="0xfunnel",
            condition_id="cond-funnel",
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.50",
            size="800",
            title="Funnel?",
            slug="funnel",
            event_slug="funnel",
        )
        funnel = _build_structural_pre_admission_funnel(
            [trade],
            minimum_notional=Decimal("1000"),
            normal_candidate_ids=set(),
            pre_admission_pool=[trade],
            funding_context_by_trade_id={trade.trade_id: FundingContext(funding_found=False)},
            pre_admission_funding_trace_attempted_ids={trade.trade_id},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.assertEqual(collect_funnels([root]), [])
            (root / "candidate_admission_funnel.json").write_text(json.dumps(funnel), encoding="utf-8")
            (root / "candidate_admission_funnel.md").write_text(
                _structural_pre_admission_funnel_markdown(funnel),
                encoding="utf-8",
            )
            loaded = collect_funnels([root])
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["counts"]["subThresholdAboveStructuralFloorTrades"], 1)

    def test_candidate_admission_funnel_strict_group_reaches_validated_stage(self) -> None:
        market = _market(condition_id="cond-funnel-strict", slug="funnel-strict", question="Funnel strict?")
        trades = [
            _trade(
                trade_id=f"funnel-strict-{index}",
                wallet=f"0xfunnelstrict{index}",
                condition_id=market.condition_id,
                asset_id="asset-yes",
                timestamp=datetime(2026, 4, 7, 12, index * 5, tzinfo=UTC),
                price="0.50",
                size="1200",
                title=market.question,
                slug=market.slug,
                event_slug=market.slug,
            )
            for index in range(2)
        ]
        funding = {
            trade.trade_id: FundingContext(
                funding_found=True,
                source_category="unknown",
                origin_category="unknown",
                funding_depth=1,
                funding_graph_key_strict="0xfunnel-strict",
            )
            for trade in trades
        }
        metadata = _build_structural_pre_admission_metadata(
            trades,
            minimum_notional=Decimal("1000"),
            funding_context_by_trade_id=funding,
            wallet_history_by_wallet={trade.wallet: [trade] for trade in trades},
            enable_structural_pre_admission=True,
        )
        funnel = _build_structural_pre_admission_funnel(
            trades,
            minimum_notional=Decimal("1000"),
            normal_candidate_ids=set(),
            pre_admission_pool=trades,
            funding_context_by_trade_id=funding,
            wallet_history_by_wallet={trade.wallet: [trade] for trade in trades},
            admission_metadata=metadata,
            pre_admission_funding_trace_attempted_ids={trade.trade_id for trade in trades},
            pre_admission_funding_trace_succeeded_ids={trade.trade_id for trade in trades},
        )
        cases = []
        for trade in trades:
            case = _score_trade(
                trade=trade,
                market=market,
                trade_domain="Middle East",
                wallet_inspection=_wallet_inspection(2),
                wallet_performance=_wallet_performance(),
                wallet_window_trades=[trade],
                wallet_history_trades=[trade],
                market_window_trades=trades,
                domain_window_trades=trades,
                event_context=_event_context(),
                funding_context=funding[trade.trade_id],
                include_below_threshold=True,
            )
            self.assertIsNotNone(case)
            assert case is not None
            _apply_candidate_admission_metadata(case, metadata[trade.trade_id])
            cases.append(case)
        _annotate_shared_funding_links(cases)
        _validate_candidate_admissions(cases)
        _finalize_structural_pre_admission_funnel(funnel, cases)

        counts = funnel["counts"]
        self.assertGreater(counts["groupedConditionDirectionGroups"], 0)
        self.assertGreater(funnel["preAdmissionStrictFundingGroupsFound"], 0)
        self.assertGreater(counts["groupsAdmittedPendingScoring"], 0)
        self.assertGreater(funnel["validatedPreAdmissionCount"], 0)

    def test_candidate_admission_funnel_proxy_and_timing_rejections(self) -> None:
        now = datetime(2026, 4, 7, 12, 0, tzinfo=UTC)
        trades = [
            _trade(
                trade_id=f"funnel-proxy-{index}",
                wallet=f"0xfunnelproxy{index}",
                condition_id="cond-funnel-proxy",
                asset_id="asset-yes",
                timestamp=now + timedelta(minutes=index * 5),
                price="0.50",
                size="1200",
                title="Funnel proxy?",
                slug="funnel-proxy",
                event_slug="funnel-proxy",
            )
            for index in range(2)
        ]
        proxy_funding = {
            trade.trade_id: FundingContext(
                funding_found=True,
                source_category="cex",
                origin_category="cex",
                funding_depth=1,
                funding_graph_key_proxy="binance|bucket",
                funding_fingerprint="binance|bucket",
            )
            for trade in trades
        }
        proxy_funnel = _build_structural_pre_admission_funnel(
            trades,
            minimum_notional=Decimal("1000"),
            pre_admission_pool=trades,
            funding_context_by_trade_id=proxy_funding,
            pre_admission_funding_trace_attempted_ids={trade.trade_id for trade in trades},
            pre_admission_funding_trace_succeeded_ids={trade.trade_id for trade in trades},
        )
        self.assertGreater(proxy_funnel["preAdmissionProxyOnlyGroupsFound"], 0)
        self.assertGreater(proxy_funnel["counts"]["groupsRejectedProxyOnly"], 0)
        self.assertEqual(proxy_funnel.get("validatedPreAdmissionCount", 0), 0)

        timing_funnel = _build_structural_pre_admission_funnel(
            trades,
            minimum_notional=Decimal("1000"),
            pre_admission_pool=trades,
            funding_context_by_trade_id={trade.trade_id: FundingContext(funding_found=False) for trade in trades},
            pre_admission_funding_trace_attempted_ids={trade.trade_id for trade in trades},
        )
        self.assertGreater(timing_funnel["counts"]["groupedConditionDirectionGroups"], 0)
        self.assertGreater(timing_funnel["counts"]["groupsTimingOnlyNoStructuralEvidence"], 0)
        self.assertEqual(timing_funnel.get("validatedPreAdmissionCount", 0), 0)

    def test_candidate_admission_funnel_dormant_non_opening_rejection_and_disabled_funding(self) -> None:
        market = _market(condition_id="cond-funnel-dormant", slug="funnel-dormant", question="Funnel dormant?")
        prior = _trade(
            trade_id="dormant-prior-open",
            wallet="0xfunneldormant",
            condition_id=market.condition_id,
            asset_id="asset-yes",
            timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            price="0.50",
            size="1200",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
        )
        trade = _trade(
            trade_id="dormant-close",
            wallet=prior.wallet,
            condition_id=market.condition_id,
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.50",
            size="800",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
            side="SELL",
        )
        metadata = _build_structural_pre_admission_metadata(
            [trade],
            minimum_notional=Decimal("1000"),
            funding_context_by_trade_id={},
            wallet_history_by_wallet={trade.wallet: [prior, trade]},
            enable_structural_pre_admission=True,
        )
        case = _score_trade(
            trade=trade,
            market=market,
            trade_domain="Middle East",
            wallet_inspection=_wallet_inspection(2),
            wallet_performance=_wallet_performance(),
            wallet_window_trades=[prior, trade],
            wallet_history_trades=[prior, trade],
            market_window_trades=[prior, trade],
            domain_window_trades=[prior, trade],
            event_context=_event_context(),
            funding_context=FundingContext(funding_found=False),
            include_below_threshold=True,
        )
        self.assertIsNotNone(case)
        assert case is not None
        _apply_candidate_admission_metadata(case, metadata[trade.trade_id])
        _validate_candidate_admissions([case])
        funnel = _build_structural_pre_admission_funnel(
            [trade],
            minimum_notional=Decimal("1000"),
            pre_admission_pool=[trade],
            funding_context_by_trade_id={trade.trade_id: FundingContext(funding_found=False)},
            wallet_history_by_wallet={trade.wallet: [prior, trade]},
            admission_metadata=metadata,
            pre_admission_funding_trace_attempted_ids={trade.trade_id},
        )
        _finalize_structural_pre_admission_funnel(funnel, [case])
        self.assertGreater(funnel["counts"]["dormantReactivationAttempts"], 0)
        self.assertEqual(funnel["preAdmissionRejectedReasonDistribution"]["opening_exposure_not_confirmed"], 1)

        disabled_funnel = _build_structural_pre_admission_funnel(
            [
                _trade(
                    trade_id=f"disabled-{index}",
                    wallet=f"0xdisabled{index}",
                    condition_id="cond-disabled",
                    asset_id="asset-yes",
                    timestamp=datetime(2026, 4, 7, 13, index, tzinfo=UTC),
                    price="0.50",
                    size="1200",
                    title="Disabled funding?",
                    slug="disabled",
                    event_slug="disabled",
                )
                for index in range(2)
            ],
            minimum_notional=Decimal("1000"),
            funding_resolver_available=False,
            funding_resolver_disabled_reason="rpc disabled",
            pre_admission_funding_trace_enabled=True,
        )
        self.assertFalse(disabled_funnel["fundingResolverAvailable"])
        self.assertEqual(disabled_funnel["fundingResolverDisabledReason"], "rpc disabled")
        self.assertEqual(disabled_funnel["preAdmissionStrictFundingGroupsFound"], 0)
        self.assertGreater(disabled_funnel["counts"]["groupsSkippedFundingResolverDisabled"], 0)
        self.assertEqual(
            disabled_funnel["topRejectedGroups"][0]["candidateAdmissionRejectedReason"],
            "funding_resolver_unavailable",
        )
        disabled_markdown = _structural_pre_admission_funnel_markdown(disabled_funnel)
        self.assertIn("Funding evidence: not assessed because resolver unavailable", disabled_markdown)
        self.assertNotIn("no strict non-proxy shared funding group was found", disabled_markdown.lower())

    def test_model_behavior_audit_reads_funnel_and_flags_discovery_warnings(self) -> None:
        funnel = {
            "enabled": True,
            "counts": {
                "subThresholdAboveStructuralFloorTrades": 2,
                "groupedConditionDirectionGroups": 1,
                "groupsAdmittedPendingScoring": 0,
            },
            "preAdmissionFundingTraceAttemptedCount": 0,
            "fundingResolverAvailable": True,
            "preAdmissionStrictFundingGroupsFound": 0,
            "preAdmissionProxyOnlyGroupsFound": 0,
            "preAdmissionFundingUnknownCount": 2,
            "nearMissGroups": 1,
        }
        summary = audit_records([], funnels=[funnel])
        warning_codes = {warning["code"] for warning in summary["warnings"]}
        self.assertIn("pre_admission_funding_trace_zero_with_grouped_subthreshold", warning_codes)
        self.assertEqual(summary["pre_admission_funnel"]["total_near_miss_groups"], 1)

        invalid = audit_records(
            [
                {
                    "candidateAdmissionReason": "strict_shared_funding_group",
                    "candidateAdmissionStage": "pre_admitted_validated",
                    "groupedCandidateId": "bad-proxy",
                    "groupedCandidateProxyOnly": "Yes",
                    "groupedCandidateFundingGrade": "cex_proxy",
                    "fundingEvidenceGrade": "cex_proxy",
                    "repricingSourceQuality": "none",
                }
            ]
        )
        self.assertIn(
            "proxy_only_group_claims_strict_funding",
            {warning["code"] for warning in invalid["warnings"]},
        )
        unavailable = audit_records(
            [],
            funnels=[
                {
                    "enabled": True,
                    "fundingResolverAvailable": False,
                    "fundingResolverAuthError": True,
                    "fundingResolverDisabledReason": "HTTPError: HTTP Error 401: Unauthorized",
                    "counts": {
                        "subThresholdAboveStructuralFloorTrades": 2,
                        "groupedConditionDirectionGroups": 1,
                    },
                    "nearMissGroups": 1,
                    "topRejectedGroups": [
                        {"candidateAdmissionRejectedReason": "funding_resolver_unavailable"}
                    ],
                }
            ],
        )
        unavailable_codes = {warning["code"] for warning in unavailable["warnings"]}
        self.assertIn("resolver_unavailable_structural_pre_admission", unavailable_codes)
        self.assertNotIn("pre_admission_funding_trace_zero_with_grouped_subthreshold", unavailable_codes)
        self.assertEqual(
            unavailable["pre_admission_funnel"]["near_miss_groups_funding_not_assessable"],
            1,
        )
        self.assertEqual(audit_records([{"severity": "Low Risk"}])["pre_admission_funnel"]["funnel_file_count"], 0)

    def test_score_trade_classifies_repricing_source_quality(self) -> None:
        def scored_case(
            *,
            quality_slug: str,
            liquidity: str,
            volume: str,
            price: str,
            prior_count: int,
            future_prices: list[str],
            future_wallets: list[str],
        ) -> FlaggedCase:
            market = _market(
                condition_id=f"cond-{quality_slug}",
                slug=f"{quality_slug}-repricing",
                question=f"{quality_slug} repricing quality?",
                liquidity=liquidity,
            )
            market.volume = Decimal(volume)
            trade = _trade(
                trade_id=f"{quality_slug}-entry",
                wallet=f"0x{quality_slug}",
                condition_id=market.condition_id,
                asset_id="asset-yes",
                timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
                price=price,
                size="2500",
                title=market.question,
                slug=market.slug,
                event_slug=market.slug,
            )
            market_trades = [
                _trade(
                    trade_id=f"{quality_slug}-prior-{index}",
                    wallet=f"0xprior{index}",
                    condition_id=market.condition_id,
                    asset_id="asset-yes",
                    timestamp=trade.timestamp - timedelta(minutes=10 + index),
                    price=price,
                    size="100",
                    title=market.question,
                    slug=market.slug,
                    event_slug=market.slug,
                )
                for index in range(prior_count)
            ]
            market_trades.append(trade)
            for index, future_price in enumerate(future_prices):
                market_trades.append(
                    _trade(
                        trade_id=f"{quality_slug}-future-{index}",
                        wallet=future_wallets[index],
                        condition_id=market.condition_id,
                        asset_id="asset-yes",
                        timestamp=trade.timestamp + timedelta(minutes=5 + index * 4),
                        price=future_price,
                        size="100",
                        title=market.question,
                        slug=market.slug,
                        event_slug=market.slug,
                    )
                )
            market_trades.append(
                _trade(
                    trade_id=f"{quality_slug}-late-observed",
                    wallet="0xlate",
                    condition_id=market.condition_id,
                    asset_id="asset-yes",
                    timestamp=trade.timestamp + timedelta(hours=25),
                    price=price,
                    size="100",
                    title=market.question,
                    slug=market.slug,
                    event_slug=market.slug,
                )
            )
            case = _score_trade(
                trade=trade,
                market=market,
                trade_domain="Middle East",
                wallet_inspection=_wallet_inspection(2),
                wallet_performance=_wallet_performance(),
                wallet_window_trades=[trade],
                wallet_history_trades=[trade],
                market_window_trades=market_trades,
                domain_window_trades=market_trades,
                event_context=_event_context(),
                funding_context=FundingContext(funding_found=False),
                include_below_threshold=True,
            )
            self.assertIsNotNone(case)
            assert case is not None
            return case

        strong = scored_case(
            quality_slug="strong",
            liquidity="500000",
            volume="2000000",
            price="0.45",
            prior_count=4,
            future_prices=["0.50", "0.52", "0.53"],
            future_wallets=["0xdriver1", "0xdriver2", "0xdriver3"],
        )
        weak = scored_case(
            quality_slug="weak",
            liquidity="80000",
            volume="2000000",
            price="0.45",
            prior_count=4,
            future_prices=["0.50", "0.52", "0.53"],
            future_wallets=["0xdriver1", "0xdriver2", "0xdriver3"],
        )
        mechanical = scored_case(
            quality_slug="mechanical",
            liquidity="50000",
            volume="100000",
            price="0.96",
            prior_count=0,
            future_prices=["0.99"],
            future_wallets=["0xonedriver"],
        )

        self.assertEqual(strong.raw_metrics["repricing_source_quality"], "strong")
        self.assertEqual(weak.raw_metrics["repricing_source_quality"], "weak")
        self.assertEqual(mechanical.raw_metrics["repricing_source_quality"], "mechanical")
        self.assertEqual(mechanical.raw_metrics["repricing_driven_by_single_wallet"], "Yes")
        self.assertIn("one trade or wallet", mechanical.raw_metrics["repricing_source_quality_reasons"])

    def test_score_trade_does_not_penalize_missing_repricing(self) -> None:
        current_trade = _trade(
            trade_id="recent-no-repricing",
            wallet="0xwallet",
            condition_id="cond-repricing",
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 15, 0, tzinfo=UTC),
            price="0.22",
            size="15000",
            title="Ceasefire by Friday?",
            slug="ceasefire-by-friday",
            event_slug="ceasefire-by-friday",
        )
        market = _market(
            condition_id="cond-repricing",
            slug="ceasefire-by-friday",
            question="Ceasefire by Friday?",
        )
        market_window_trades = [
            _trade(
                trade_id="peer-1",
                wallet="0xpeer1",
                condition_id="cond-repricing",
                asset_id="asset-yes",
                timestamp=current_trade.timestamp - timedelta(minutes=10),
                price="0.28",
                size="4000",
                title=current_trade.title,
                slug=current_trade.slug,
                event_slug=current_trade.event_slug,
            ),
            _trade(
                trade_id="peer-2",
                wallet="0xpeer2",
                condition_id="cond-repricing",
                asset_id="asset-yes",
                timestamp=current_trade.timestamp - timedelta(minutes=4),
                price="0.27",
                size="4200",
                title=current_trade.title,
                slug=current_trade.slug,
                event_slug=current_trade.event_slug,
            ),
            current_trade,
        ]

        case = _score_trade(
            trade=current_trade,
            market=market,
            trade_domain="Middle East",
            wallet_inspection=_wallet_inspection(12),
            wallet_performance=_wallet_performance(),
            wallet_window_trades=[current_trade],
            wallet_history_trades=[current_trade],
            market_window_trades=market_window_trades,
            domain_window_trades=market_window_trades,
            event_context=_event_context(),
            funding_context=FundingContext(funding_found=False),
            include_below_threshold=True,
        )

        self.assertIsNotNone(case)
        assert case is not None
        self.assertEqual(case.raw_metrics["favorable_move_1h"], "Unavailable")
        self.assertNotIn(
            "We did not see a strong favorable repricing after the trade in the loaded sample.",
            case.reasons_against,
        )

    def test_precomputed_notional_samples_match_default_scoring(self) -> None:
        current_trade = _trade(
            trade_id="trade-percentiles",
            wallet="0xwallet",
            condition_id="cond-percentiles",
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 15, 0, tzinfo=UTC),
            price="0.21",
            size="8000",
            title="Iran by Friday?",
            slug="iran-by-friday",
            event_slug="iran-by-friday",
        )
        market = _market(
            condition_id="cond-percentiles",
            slug="iran-by-friday",
            question="Iran by Friday?",
        )
        market_window_trades = [
            _trade(
                trade_id=f"peer-{index}",
                wallet=f"0xpeer{index}",
                condition_id="cond-percentiles",
                asset_id="asset-yes",
                timestamp=current_trade.timestamp - timedelta(minutes=20 - index),
                price="0.22",
                size=str(2000 + index * 350),
                title=current_trade.title,
                slug=current_trade.slug,
                event_slug=current_trade.event_slug,
            )
            for index in range(1, 10)
        ] + [current_trade]

        default_case = _score_trade(
            trade=current_trade,
            market=market,
            trade_domain="Middle East",
            wallet_inspection=_wallet_inspection(12),
            wallet_performance=_wallet_performance(),
            wallet_window_trades=[current_trade],
            wallet_history_trades=[current_trade],
            market_window_trades=market_window_trades,
            domain_window_trades=market_window_trades,
            event_context=_event_context(),
            funding_context=FundingContext(funding_found=False),
            include_below_threshold=True,
        )
        cached_case = _score_trade(
            trade=current_trade,
            market=market,
            trade_domain="Middle East",
            wallet_inspection=_wallet_inspection(12),
            wallet_performance=_wallet_performance(),
            wallet_window_trades=[current_trade],
            wallet_history_trades=[current_trade],
            market_window_trades=market_window_trades,
            domain_window_trades=market_window_trades,
            event_context=_event_context(),
            funding_context=FundingContext(funding_found=False),
            include_below_threshold=True,
            market_notional_samples=sorted(float(item.notional) for item in market_window_trades),
            domain_notional_samples=sorted(float(item.notional) for item in market_window_trades),
        )

        self.assertIsNotNone(default_case)
        self.assertIsNotNone(cached_case)
        assert default_case is not None and cached_case is not None
        self.assertEqual(cached_case.suspicion_score, default_case.suspicion_score)
        self.assertEqual(cached_case.severity, default_case.severity)
        self.assertEqual(
            cached_case.raw_metrics["market_size_percentile"],
            default_case.raw_metrics["market_size_percentile"],
        )
        self.assertEqual(
            cached_case.raw_metrics["domain_peer_percentile"],
            default_case.raw_metrics["domain_peer_percentile"],
        )

    def test_soft_public_lag_no_longer_forces_low_risk(self) -> None:
        severity = _severity_from_score(
            42,
            80,
            opening_exposure_flag=True,
            materially_uncertain=False,
            decisive_timing_edge=True,
            strong_timing_proof_count=1,
            supporting_booster_count=1,
            structural_concern_count=2,
            benign_pattern=False,
            credibility_gamed=True,
            hard_resolution_gap_flag=False,
            soft_resolution_gap_flag=True,
        )

        self.assertEqual(severity, "Strong Risk")

    def test_archive_visibility_promotes_structural_cases(self) -> None:
        market = _market(
            condition_id="cond-archive",
            slug="archive-case",
            question="Archive case?",
        )
        trade = _trade(
            trade_id="archive-1",
            wallet="0xarchive",
            condition_id="cond-archive",
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.20",
            size="20000",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
        )
        case = _flagged_case(
            trade=trade,
            market=market,
            raw_metrics={
                "shared_funding_source_flag": "Yes",
                "funding_graph_key_strict": "0xstrict-funder",
                "split_wallet_pattern_flag": "No",
                "cex_proxy_cluster_flag": "No",
                "event_family_repeat_flag": "No",
                "opening_exposure_flag": "Yes",
                "economic_win_rate_clears_threshold": "No",
                "win_rate_clears_threshold": "No",
                "wallet_economic_sample_size": "6",
                "structural_concern_count": "2",
                "hard_public_information_flag": "No",
            },
            flags=[],
        )
        case.severity = "Worth a Look"
        case.suspicion_score = 22

        self.assertEqual(_visibility_tier_for_case(case), "Visible")

    def test_split_wallet_low_base_score_is_hard_evidence_review(self) -> None:
        market = _market(
            condition_id="cond-split-low",
            slug="split-low",
            question="Split-wallet low base case?",
        )
        first_trade = _trade(
            trade_id="split-low-1",
            wallet="0xsplit1",
            condition_id=market.condition_id,
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.44",
            size="2500",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
        )
        second_trade = _trade(
            trade_id="split-low-2",
            wallet="0xsplit2",
            condition_id=market.condition_id,
            asset_id="asset-yes",
            timestamp=first_trade.timestamp + timedelta(minutes=8),
            price="0.45",
            size="2400",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
        )
        raw = {
            "shared_funding_source_flag": "Yes",
            "funding_graph_key_strict": "0xstrict-funder",
            "split_wallet_pattern_flag": "Yes",
            "cex_proxy_cluster_flag": "No",
            "economic_direction": "long_yes",
            "opening_exposure_flag": "Yes",
            "event_family_repeat_flag": "No",
            "reactivated_after_dormancy_flag": "No",
            "suspicious_funding_flag": "No",
            "coordinated_sizing_cluster_flag": "No",
            "hard_public_information_flag": "No",
            "economic_win_rate_clears_threshold": "No",
            "win_rate_clears_threshold": "No",
            "wallet_economic_sample_size": "8",
            "structural_concern_count": "1",
        }
        cases = [
            _flagged_case(trade=first_trade, market=market, raw_metrics=dict(raw), flags=[]),
            _flagged_case(trade=second_trade, market=market, raw_metrics=dict(raw), flags=[]),
        ]
        for case in cases:
            case.severity = "Low Risk"
            case.suspicion_score = 12

        _annotate_hard_evidence_review(cases, evidence_availability_stage="archive_no_outcome_context")

        self.assertEqual(cases[0].raw_metrics["hardEvidenceReviewTier"], HARD_EVIDENCE_REVIEW_TIER)
        self.assertIn("split_wallet_pattern", cases[0].raw_metrics["hardEvidenceSources"])
        self.assertEqual(_visibility_tier_for_case(cases[0]), HARD_EVIDENCE_REVIEW_TIER)

    def test_suspicious_direct_recent_aligned_opening_is_strong_quality(self) -> None:
        metrics = _suspicious_funding_quality_metrics(_suspicious_funding_raw(), flags=[])

        self.assertEqual(metrics["suspiciousFundingQuality"], SUSPICIOUS_FUNDING_QUALITY_STRONG)
        self.assertEqual(metrics["suspiciousFundingHardEvidenceEligible"], "Yes")
        self.assertEqual(metrics["suspiciousFundingRecentEnough"], "Yes")
        self.assertEqual(metrics["suspiciousFundingAmountAligned"], "Yes")
        self.assertEqual(metrics["suspiciousFundingSuppressorConflict"], "No")

    def test_multi_hop_recent_aligned_without_support_is_moderate_not_eligible(self) -> None:
        metrics = _suspicious_funding_quality_metrics(
            _suspicious_funding_raw(
                fundingEvidenceGrade="multi_hop_unknown",
                funding_evidence_grade="multi_hop_unknown",
                funding_depth="2",
            ),
            flags=[],
        )

        self.assertEqual(metrics["suspiciousFundingQuality"], SUSPICIOUS_FUNDING_QUALITY_MODERATE)
        self.assertEqual(metrics["suspiciousFundingHardEvidenceEligible"], "No")
        self.assertEqual(metrics["suspiciousFundingIndependentSupport"], "No")

    def test_multi_hop_recent_aligned_with_split_wallet_support_is_eligible(self) -> None:
        metrics = _suspicious_funding_quality_metrics(
            _suspicious_funding_raw(
                fundingEvidenceGrade="multi_hop_unknown",
                funding_evidence_grade="multi_hop_unknown",
                funding_depth="2",
                shared_funding_source_flag="Yes",
                split_wallet_pattern_flag="Yes",
                funding_graph_key_strict="0xstrict",
            ),
            flags=[],
        )

        self.assertEqual(metrics["suspiciousFundingQuality"], SUSPICIOUS_FUNDING_QUALITY_STRONG)
        self.assertEqual(metrics["suspiciousFundingHardEvidenceEligible"], "Yes")
        self.assertEqual(metrics["suspiciousFundingIndependentSupport"], "Yes")
        self.assertIn("split_wallet_pattern", metrics["suspiciousFundingIndependentSupportSources"])

    def test_multi_hop_old_or_poor_amount_alignment_is_weak(self) -> None:
        old_metrics = _suspicious_funding_quality_metrics(
            _suspicious_funding_raw(
                fundingEvidenceGrade="multi_hop_unknown",
                funding_evidence_grade="multi_hop_unknown",
                minutes_from_funding_to_trade=str(48 * 60),
            ),
            flags=[],
        )
        poor_amount_metrics = _suspicious_funding_quality_metrics(
            _suspicious_funding_raw(
                fundingEvidenceGrade="multi_hop_unknown",
                funding_evidence_grade="multi_hop_unknown",
                funding_amount_usdc="100000.00",
                trade_notional_usdc="1000.00",
            ),
            flags=[],
        )

        self.assertEqual(old_metrics["suspiciousFundingQuality"], SUSPICIOUS_FUNDING_QUALITY_WEAK)
        self.assertEqual(poor_amount_metrics["suspiciousFundingQuality"], SUSPICIOUS_FUNDING_QUALITY_WEAK)
        self.assertEqual(old_metrics["suspiciousFundingHardEvidenceEligible"], "No")
        self.assertEqual(poor_amount_metrics["suspiciousFundingHardEvidenceEligible"], "No")

    def test_suspicious_funding_suppressors_block_funding_only_hard_evidence(self) -> None:
        near_metrics = _suspicious_funding_quality_metrics(
            _suspicious_funding_raw(price_implied_probability="98.0"),
            flags=["near_certainty_trade"],
        )
        stale_metrics = _suspicious_funding_quality_metrics(
            _suspicious_funding_raw(stale_resolution_annotation="Yes"),
            flags=[],
        )
        high_volume_metrics = _suspicious_funding_quality_metrics(
            _suspicious_funding_raw(wallet_recent_trade_count="150", wallet_unique_market_count="75"),
            flags=[],
        )

        self.assertEqual(near_metrics["suspiciousFundingHardEvidenceEligible"], "No")
        self.assertEqual(stale_metrics["suspiciousFundingHardEvidenceEligible"], "No")
        self.assertEqual(high_volume_metrics["suspiciousFundingHardEvidenceEligible"], "No")
        self.assertEqual(high_volume_metrics["suspiciousFundingQuality"], SUSPICIOUS_FUNDING_QUALITY_WEAK)
        self.assertIn("high_volume_public_user", high_volume_metrics["suspiciousFundingSuppressorConflictReasons"])

    def test_high_volume_suspicious_direct_with_split_wallet_support_is_eligible(self) -> None:
        metrics = _suspicious_funding_quality_metrics(
            _suspicious_funding_raw(
                wallet_recent_trade_count="150",
                wallet_unique_market_count="75",
                shared_funding_source_flag="Yes",
                split_wallet_pattern_flag="Yes",
                funding_graph_key_strict="0xstrict",
            ),
            flags=[],
        )

        self.assertEqual(metrics["suspiciousFundingHardEvidenceEligible"], "Yes")
        self.assertEqual(metrics["suspiciousFundingQuality"], SUSPICIOUS_FUNDING_QUALITY_MODERATE)
        self.assertIn("split_wallet_pattern", metrics["suspiciousFundingIndependentSupportSources"])
        self.assertEqual(metrics["suspiciousFundingSuppressorConflict"], "Yes")
        self.assertIn("high_volume_public_user", metrics["suspiciousFundingSuppressorConflictReasons"])

    def test_multi_hop_suppressor_conflicts_without_support_are_weak_not_eligible(self) -> None:
        fixtures = [
            _suspicious_funding_raw(
                fundingEvidenceGrade="multi_hop_unknown",
                funding_evidence_grade="multi_hop_unknown",
                low_analyst_value_flag="Yes",
            ),
            _suspicious_funding_raw(
                fundingEvidenceGrade="multi_hop_unknown",
                funding_evidence_grade="multi_hop_unknown",
                stale_resolution_annotation="Yes",
            ),
            _suspicious_funding_raw(
                fundingEvidenceGrade="multi_hop_unknown",
                funding_evidence_grade="multi_hop_unknown",
                wallet_recent_trade_count="150",
                wallet_unique_market_count="75",
            ),
            _suspicious_funding_raw(
                fundingEvidenceGrade="multi_hop_unknown",
                funding_evidence_grade="multi_hop_unknown",
                specialist_explained_flag="Yes",
            ),
        ]

        for raw in fixtures:
            metrics = _suspicious_funding_quality_metrics(raw, flags=[])
            self.assertEqual(metrics["suspiciousFundingQuality"], SUSPICIOUS_FUNDING_QUALITY_WEAK)
            self.assertEqual(metrics["suspiciousFundingHardEvidenceEligible"], "No")
            self.assertEqual(metrics["suspiciousFundingSuppressorConflict"], "Yes")

    def test_cex_bridge_unknown_and_trace_failed_are_not_suspicious_funding_eligible(self) -> None:
        cex = _suspicious_funding_quality_metrics(
            _suspicious_funding_raw(
                fundingEvidenceGrade="cex_proxy",
                funding_evidence_grade="cex_proxy",
                funding_graph_key_strict="",
                funding_graph_key_proxy="binance|day|500-1000",
                cex_proxy_cluster_flag="Yes",
            ),
            flags=[],
        )
        bridge = _suspicious_funding_quality_metrics(
            _suspicious_funding_raw(
                fundingEvidenceGrade="bridge_proxy",
                funding_evidence_grade="bridge_proxy",
            ),
            flags=[],
        )
        unknown = _suspicious_funding_quality_metrics(
            _suspicious_funding_raw(
                fundingEvidenceGrade=FUNDING_EVIDENCE_UNKNOWN,
                funding_evidence_grade=FUNDING_EVIDENCE_UNKNOWN,
                fundingResolverAvailable="No",
            ),
            flags=[],
        )
        failed = _suspicious_funding_quality_metrics(
            _suspicious_funding_raw(
                fundingTraceSucceededCount="0",
                fundingTraceFailedCount="1",
            ),
            flags=[],
        )

        self.assertEqual(cex["suspiciousFundingHardEvidenceEligible"], "No")
        self.assertEqual(bridge["suspiciousFundingHardEvidenceEligible"], "No")
        self.assertEqual(unknown["suspiciousFundingQuality"], SUSPICIOUS_FUNDING_QUALITY_UNKNOWN)
        self.assertEqual(failed["suspiciousFundingQuality"], SUSPICIOUS_FUNDING_QUALITY_UNKNOWN)

    def test_offline_replay_classifies_saved_strong_suspicious_funding_without_rpc(self) -> None:
        record = {
            "wallet": "0xreplay",
            "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
            "hardEvidenceSources": "suspicious_recent_funding",
            "hardEvidenceStrength": "Strong",
            "fundingEvidenceGrade": "suspicious_direct",
            "suspicious_funding_flag": "Yes",
            "funding_amount_usdc": "2500",
            "trade_notional_usdc": "2000",
            "minutes_from_funding_to_trade": "30",
            "opening_exposure_flag": "Yes",
            "funding_tx_hash": "0xfund",
        }

        with mock.patch("app.funding_context._post_json") as mocked_rpc:
            summary = replay_records([record])

        mocked_rpc.assert_not_called()
        self.assertEqual(summary["suspiciousFundingQuality"]["strong"], 1)
        self.assertEqual(summary["suspiciousFundingHardEvidenceEligibleCount"], 1)
        self.assertEqual(summary["replayed_suspicious_funding_hard_evidence_review_count"], 1)

    def test_offline_replay_downgrades_weak_multi_hop_unknown(self) -> None:
        summary = replay_records(
            [
                {
                    "wallet": "0xweakmulti",
                    "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                    "hardEvidenceSources": "suspicious_recent_funding",
                    "hardEvidenceStrength": "Strong",
                    "fundingEvidenceGrade": "multi_hop_unknown",
                    "suspicious_funding_flag": "Yes",
                    "funding_amount_usdc": "100000",
                    "trade_notional_usdc": "1000",
                    "minutes_from_funding_to_trade": str(48 * 60),
                    "opening_exposure_flag": "Yes",
                    "funding_tx_hash": "0xfund",
                    "funding_depth": "2",
                }
            ]
        )

        self.assertEqual(summary["suspiciousFundingQuality"]["weak"], 1)
        self.assertEqual(summary["prior_suspicious_funding_hard_evidence_review_count"], 1)
        self.assertEqual(summary["rows_downgraded_from_suspicious_funding_hard_evidence_to_contextual"], 1)
        self.assertEqual(summary["replayed_suspicious_funding_hard_evidence_review_count"], 0)

    def test_offline_replay_missing_fields_are_insufficient_not_strong(self) -> None:
        summary = replay_records(
            [
                {
                    "wallet": "0xmissing",
                    "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                    "hardEvidenceSources": "suspicious_recent_funding",
                    "fundingEvidenceGrade": "multi_hop_unknown",
                    "suspicious_funding_flag": "Yes",
                }
            ]
        )

        self.assertEqual(summary["rows_missing_required_saved_fields"], 1)
        self.assertNotIn("strong", summary["suspiciousFundingQuality"])

    def test_offline_replay_warns_if_weak_would_remain_hard_evidence(self) -> None:
        with mock.patch(
            "tools.replay_suspicious_funding_quality._suspicious_funding_quality_metrics",
            return_value={
                "suspiciousFundingQuality": "weak",
                "suspiciousFundingHardEvidenceEligible": "Yes",
                "suspiciousFundingQualityReasons": "forced weak replay fixture",
                "suspiciousFundingRecentEnough": "Yes",
                "suspiciousFundingAmountAligned": "No",
                "suspiciousFundingIndependentSupport": "No",
            },
        ):
            summary = replay_records(
                [
                    {
                        "wallet": "0ximpossible",
                        "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                        "hardEvidenceSources": "suspicious_recent_funding",
                        "fundingEvidenceGrade": "multi_hop_unknown",
                        "suspicious_funding_flag": "Yes",
                        "funding_amount_usdc": "100000",
                        "trade_notional_usdc": "1000",
                        "minutes_from_funding_to_trade": "30",
                        "opening_exposure_flag": "Yes",
                        "funding_tx_hash": "0xfund",
                    }
                ]
            )

        warning_codes = {item["code"] for item in summary["warnings"]}
        self.assertIn("weak_funding_would_remain_hard_evidence", warning_codes)

    def test_hard_evidence_review_uses_suspicious_funding_quality_gate(self) -> None:
        market = _market(condition_id="cond-funding-quality", slug="funding-quality", question="Funding quality?")
        trade = _trade(
            trade_id="weak-funding",
            wallet="0xweakfunding",
            condition_id=market.condition_id,
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.44",
            size="2500",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
        )
        case = _flagged_case(
            trade=trade,
            market=market,
            raw_metrics=_suspicious_funding_raw(
                fundingEvidenceGrade="multi_hop_unknown",
                funding_evidence_grade="multi_hop_unknown",
                funding_amount_usdc="100000.00",
                trade_notional_usdc="1000.00",
            ),
            flags=[],
        )

        _annotate_hard_evidence_review([case], evidence_availability_stage="archive_no_outcome_context")

        self.assertEqual(case.raw_metrics["suspiciousFundingQuality"], SUSPICIOUS_FUNDING_QUALITY_WEAK)
        self.assertEqual(case.raw_metrics["hardEvidenceReviewTier"], "")
        self.assertNotIn("suspicious_recent_funding", case.raw_metrics["hardEvidenceSources"])

    def test_dormant_and_split_wallet_hard_evidence_survive_weak_or_moderate_funding_quality(self) -> None:
        market = _market(condition_id="cond-other-hard", slug="other-hard", question="Other hard evidence?")
        dormant_trade = _trade(
            trade_id="dormant-weak-funding",
            wallet="0xdormantweak",
            condition_id=market.condition_id,
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.44",
            size="2500",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
        )
        dormant_case = _flagged_case(
            trade=dormant_trade,
            market=market,
            raw_metrics=_suspicious_funding_raw(
                fundingEvidenceGrade="multi_hop_unknown",
                funding_evidence_grade="multi_hop_unknown",
                funding_amount_usdc="100000.00",
                trade_notional_usdc="1000.00",
                reactivated_after_dormancy_flag="Yes",
            ),
            flags=[],
        )
        split_raw = _suspicious_funding_raw(
            fundingEvidenceGrade="multi_hop_unknown",
            funding_evidence_grade="multi_hop_unknown",
            shared_funding_source_flag="Yes",
            split_wallet_pattern_flag="Yes",
            funding_graph_key_strict="0xstrict-moderate",
            economic_direction="long_yes",
        )
        split_cases = []
        for index in range(2):
            trade = _trade(
                trade_id=f"split-moderate-{index}",
                wallet=f"0xsplitmoderate{index}",
                condition_id=market.condition_id,
                asset_id="asset-yes",
                timestamp=datetime(2026, 4, 7, 12, index + 1, tzinfo=UTC),
                price="0.45",
                size="2500",
                title=market.question,
                slug=market.slug,
                event_slug=market.slug,
            )
            split_cases.append(_flagged_case(trade=trade, market=market, raw_metrics=dict(split_raw), flags=[]))
        cases = [dormant_case, *split_cases]

        _annotate_hard_evidence_review(cases, evidence_availability_stage="archive_no_outcome_context")

        self.assertEqual(dormant_case.raw_metrics["hardEvidenceReviewTier"], HARD_EVIDENCE_REVIEW_TIER)
        self.assertIn("dormant_wallet_reactivation", dormant_case.raw_metrics["hardEvidenceSources"])
        self.assertEqual(split_cases[0].raw_metrics["hardEvidenceReviewTier"], HARD_EVIDENCE_REVIEW_TIER)
        self.assertIn("split_wallet_pattern", split_cases[0].raw_metrics["hardEvidenceSources"])

    def test_cex_proxy_only_group_is_not_hard_evidence_review(self) -> None:
        market = _market(
            condition_id="cond-cex",
            slug="cex-proxy",
            question="CEX proxy case?",
        )
        raw = {
            "shared_funding_source_flag": "Yes",
            "shared_funding_source_cluster_size": "2",
            "funding_graph_key_strict": "",
            "funding_graph_key_proxy": "binance|day|2500-5000",
            "split_wallet_pattern_flag": "Yes",
            "cex_proxy_cluster_flag": "Yes",
            "economic_direction": "long_yes",
            "opening_exposure_flag": "Yes",
            "event_family_repeat_flag": "No",
            "reactivated_after_dormancy_flag": "No",
            "suspicious_funding_flag": "No",
            "coordinated_sizing_cluster_flag": "No",
            "hard_public_information_flag": "No",
            "economic_win_rate_clears_threshold": "No",
            "win_rate_clears_threshold": "No",
            "wallet_economic_sample_size": "8",
            "structural_concern_count": "1",
        }
        cases = []
        for index in range(2):
            trade = _trade(
                trade_id=f"cex-{index}",
                wallet=f"0xcex{index}",
                condition_id=market.condition_id,
                asset_id="asset-yes",
                timestamp=datetime(2026, 4, 7, 12, index, tzinfo=UTC),
                price="0.42",
                size="2500",
                title=market.question,
                slug=market.slug,
                event_slug=market.slug,
            )
            case = _flagged_case(trade=trade, market=market, raw_metrics=dict(raw), flags=["cex_proxy_cluster"])
            case.severity = "Low Risk"
            case.suspicion_score = 12
            cases.append(case)

        _annotate_hard_evidence_review(cases, evidence_availability_stage="archive_no_outcome_context")

        self.assertEqual(cases[0].raw_metrics["hardEvidenceSources"], "")
        self.assertEqual(cases[0].raw_metrics["hardEvidenceReviewTier"], "")
        self.assertEqual(_visibility_tier_for_case(cases[0]), "Secondary review")

    def test_near_certainty_split_wallet_is_visible_but_severity_stays_suppressed(self) -> None:
        market = _market(
            condition_id="cond-near-split",
            slug="near-split",
            question="Near certainty split case?",
        )
        raw = {
            "shared_funding_source_flag": "Yes",
            "funding_graph_key_strict": "0xstrict-near",
            "split_wallet_pattern_flag": "Yes",
            "cex_proxy_cluster_flag": "No",
            "economic_direction": "long_yes",
            "opening_exposure_flag": "Yes",
            "event_family_repeat_flag": "No",
            "reactivated_after_dormancy_flag": "No",
            "suspicious_funding_flag": "No",
            "coordinated_sizing_cluster_flag": "No",
            "hard_public_information_flag": "No",
            "economic_win_rate_clears_threshold": "No",
            "win_rate_clears_threshold": "No",
            "wallet_economic_sample_size": "8",
            "structural_concern_count": "1",
        }
        cases = []
        for index in range(2):
            trade = _trade(
                trade_id=f"near-split-{index}",
                wallet=f"0xnear{index}",
                condition_id=market.condition_id,
                asset_id="asset-yes",
                timestamp=datetime(2026, 4, 7, 12, index, tzinfo=UTC),
                price="0.99",
                size="2500",
                title=market.question,
                slug=market.slug,
                event_slug=market.slug,
            )
            case = _flagged_case(trade=trade, market=market, raw_metrics=dict(raw), flags=["near_certainty_trade"])
            case.severity = "Low Risk"
            case.suspicion_score = 16
            cases.append(case)

        _annotate_hard_evidence_review(cases, evidence_availability_stage="archive_no_outcome_context")

        self.assertEqual(cases[0].raw_metrics["hardEvidenceReviewTier"], HARD_EVIDENCE_REVIEW_TIER)
        self.assertEqual(_visibility_tier_for_case(cases[0]), HARD_EVIDENCE_REVIEW_TIER)
        self.assertEqual(cases[0].severity, "Low Risk")

    def test_model_behavior_benchmark_lite_fixture_expectations(self) -> None:
        records = self._benchmark_lite_records()
        summary = audit_records(records)
        normalized = {normalize_record(record)["row_id"]: normalize_record(record) for record in records}

        self.assertEqual(summary["total_rows_inspected"], 10)
        self.assertEqual(summary["hard_evidence_review_rows"], 4)
        self.assertEqual(summary["strong_risk_rows"], 0)
        self.assertEqual(summary["warnings"], [])

        self.assertTrue(normalized["strict-split-wallet"]["hard_evidence_review"])
        self.assertFalse(normalized["strict-split-wallet"]["strong_risk"])
        self.assertFalse(normalized["cex-proxy-only"]["hard_evidence_review"])
        self.assertTrue(normalized["cex-plus-dormant"]["hard_evidence_review"])
        self.assertIn(
            "dormant_wallet_reactivation",
            normalized["cex-plus-dormant"]["independent_hard_sources"],
        )
        self.assertFalse(normalized["high-impact-repricing-only"]["hard_evidence_review"])
        self.assertFalse(normalized["mechanical-repricing"]["hard_evidence_review"])
        self.assertEqual(normalized["mechanical-repricing"]["repricing_source_quality"], "mechanical")
        self.assertEqual(normalized["weak-repricing"]["repricing_source_quality"], "weak")
        self.assertEqual(normalized["strong-repricing-quality"]["repricing_source_quality"], "strong")
        self.assertLess(records[5]["eventForensicScore"], 40)
        self.assertFalse(normalized["strong-repricing-quality"]["strong_risk"])
        self.assertTrue(normalized["near-certainty-split"]["hard_evidence_review"])
        self.assertIn("near_certainty", normalized["near-certainty-split"]["suppressors"])
        self.assertFalse(normalized["high-volume-public-no-hard"]["hard_evidence_review"])
        self.assertFalse(normalized["high-volume-public-no-hard"]["visible"])
        self.assertTrue(normalized["high-volume-public-strict"]["hard_evidence_review"])
        self.assertIn("high_volume_public_user", normalized["high-volume-public-strict"]["suppressors"])

        distributions = summary["distributions"]
        self.assertEqual(distributions["repricingSourceQuality"]["mechanical"], 1)
        self.assertEqual(distributions["repricingSourceQuality"]["weak"], 1)
        self.assertEqual(distributions["repricingSourceQuality"]["strong"], 2)
        self.assertEqual(distributions["fundingEvidenceGrade"]["cex_proxy"], 2)
        self.assertEqual(summary["hard_evidence_review_with_suppressors"]["near_certainty"], 1)
        self.assertEqual(summary["hard_evidence_review_with_suppressors"]["high_volume_public_user"], 1)

    def test_model_behavior_audit_flags_invalid_synthetic_records(self) -> None:
        invalid_records = [
            {
                "id": "bad-cex-hard",
                "severity": "Low Risk",
                "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceSources": "",
                "fundingEvidenceGrade": "cex_proxy",
                "cex_proxy_cluster_flag": "Yes",
            },
            {
                "id": "bad-high-impact-hard",
                "severity": "Low Risk",
                "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceSources": "high_impact_timing_or_repricing",
                "fundingEvidenceGrade": "none",
                "favorable_repricing_flag": "Yes",
                "repricingSourceQuality": "weak",
                "eventForensicFlags": "post_entry_repricing",
            },
            {
                "id": "bad-mechanical-hard",
                "severity": "Low Risk",
                "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceSources": "high_impact_timing_or_repricing",
                "fundingEvidenceGrade": "none",
                "favorable_repricing_flag": "Yes",
                "repricingSourceQuality": "mechanical",
                "eventForensicFlags": "post_entry_repricing",
            },
            {
                "id": "bad-strong-gate",
                "severity": "Strong Risk",
                "existingModelClass": "Low Risk",
                "strong_timing_proof_count": "0",
                "supporting_booster_count": "0",
                "structural_concern_count": "0",
                "opening_exposure_flag": "No",
                "hardEvidenceReviewTier": "",
                "fundingEvidenceGrade": "none",
                "repricingSourceQuality": "none",
            },
            {
                "id": "missing-funding-grade",
                "severity": "Low Risk",
                "hardEvidenceReviewTier": "",
                "hardEvidenceSources": "",
                "funding_source_label": "Opaque funder",
            },
            {
                "id": "missing-repricing-quality",
                "severity": "Low Risk",
                "hardEvidenceReviewTier": "",
                "hardEvidenceSources": "",
                "fundingEvidenceGrade": "none",
                "favorable_repricing_flag": "Yes",
            },
            {
                "id": "bad-proxy-pre-hard",
                "severity": "Low Risk",
                "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceSources": "strict_shared_funding_source",
                "fundingEvidenceGrade": "cex_proxy",
                "candidateAdmissionReason": "strict_shared_funding_group",
                "candidateAdmissionStage": "pre_admitted_validated",
                "candidateAdmissionEvidenceSources": "strict_shared_funding_source",
                "groupedCandidateId": "proxy-group",
                "groupedCandidateProxyOnly": "Yes",
                "groupedCandidateFundingGrade": "cex_proxy",
                "repricingSourceQuality": "none",
            },
            {
                "id": "bad-missing-reason",
                "severity": "Low Risk",
                "candidateAdmissionStage": "pre_admitted_validated",
                "groupedCandidateId": "group-missing-reason",
                "fundingEvidenceGrade": "direct_strict",
                "repricingSourceQuality": "none",
            },
            {
                "id": "bad-missing-group-id",
                "severity": "Low Risk",
                "candidateAdmissionReason": "strict_shared_funding_group",
                "candidateAdmissionStage": "pre_admitted_validated",
                "fundingEvidenceGrade": "direct_strict",
                "repricingSourceQuality": "none",
            },
            {
                "id": "bad-mechanical-pre",
                "severity": "Low Risk",
                "candidateAdmissionReason": "dormant_reactivation",
                "candidateAdmissionStage": "pre_admitted_validated",
                "candidateAdmissionEvidenceSources": "dormant_wallet_reactivation",
                "fundingEvidenceGrade": "none",
                "repricingSourceQuality": "mechanical",
            },
            {
                "id": "bad-high-impact-pre",
                "severity": "Low Risk",
                "candidateAdmissionReason": "high_impact_repricing",
                "candidateAdmissionStage": "pre_admitted_validated",
                "candidateAdmissionEvidenceSources": "high_impact_timing_or_repricing",
                "fundingEvidenceGrade": "none",
                "favorable_repricing_flag": "Yes",
                "eventForensicFlags": "post_entry_repricing",
                "repricingSourceQuality": "weak",
            },
            {
                "id": "bad-none-unavailable",
                "severity": "Low Risk",
                "fundingEvidenceGrade": "none",
                "fundingResolverAvailable": "No",
                "fundingResolverDisabledReason": "HTTPError: HTTP Error 401: Unauthorized",
                "fundingResolverAuthError": "Yes",
                "repricingSourceQuality": "none",
            },
            {
                "id": "bad-strict-unavailable",
                "severity": "Low Risk",
                "candidateAdmissionReason": "strict_shared_funding_group",
                "candidateAdmissionStage": "pre_admitted_validated",
                "candidateAdmissionEvidenceSources": "strict_shared_funding_source",
                "groupedCandidateId": "strict-unavailable",
                "groupedCandidateFundingGrade": "unknown",
                "fundingEvidenceGrade": "unknown",
                "fundingResolverAvailable": "No",
                "fundingResolverDisabledReason": "HTTPError: HTTP Error 401: Unauthorized",
                "repricingSourceQuality": "none",
            },
            {
                "id": "bad-weak-suspicious-funding-hard",
                "severity": "Low Risk",
                "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceSources": "suspicious_recent_funding",
                "hardEvidenceStrength": "Moderate",
                "fundingEvidenceGrade": "multi_hop_unknown",
                "suspiciousFundingQuality": "weak",
                "suspiciousFundingHardEvidenceEligible": "No",
                "suspiciousFundingIndependentSupport": "No",
                "suspiciousFundingSuppressorConflict": "Yes",
                "repricingSourceQuality": "none",
            },
            {
                "id": "bad-unknown-suspicious-funding-hard",
                "severity": "Low Risk",
                "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceSources": "suspicious_recent_funding",
                "fundingEvidenceGrade": "unknown",
                "suspiciousFundingQuality": "unknown",
                "repricingSourceQuality": "none",
            },
            {
                "id": "bad-multi-hop-strong",
                "severity": "Low Risk",
                "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceSources": "suspicious_recent_funding",
                "hardEvidenceStrength": "Strong",
                "fundingEvidenceGrade": "multi_hop_unknown",
                "suspiciousFundingQuality": "moderate",
                "suspiciousFundingRecentEnough": "Yes",
                "suspiciousFundingAmountAligned": "No",
                "opening_exposure_flag": "Yes",
                "repricingSourceQuality": "none",
            },
            {
                "id": "bad-multi-hop-strong-no-support",
                "severity": "Low Risk",
                "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceSources": "suspicious_recent_funding",
                "hardEvidenceStrength": "Strong",
                "fundingEvidenceGrade": "multi_hop_unknown",
                "suspiciousFundingQuality": "strong",
                "suspiciousFundingHardEvidenceEligible": "Yes",
                "suspiciousFundingIndependentSupport": "No",
                "suspiciousFundingSuppressorConflict": "No",
                "suspiciousFundingRecentEnough": "Yes",
                "suspiciousFundingAmountAligned": "Yes",
                "opening_exposure_flag": "Yes",
                "repricingSourceQuality": "none",
            },
            {
                "id": "bad-suppressor-conflict-missing",
                "severity": "Low Risk",
                "fundingEvidenceGrade": "multi_hop_unknown",
                "suspiciousFundingQuality": "strong",
                "suspiciousFundingSuppressorConflict": "No",
                "eventForensicReducers": "high_volume_public_user",
                "repricingSourceQuality": "none",
            },
            {
                "id": "bad-support-missing-sources",
                "severity": "Low Risk",
                "fundingEvidenceGrade": "multi_hop_unknown",
                "suspiciousFundingQuality": "strong",
                "suspiciousFundingIndependentSupport": "Yes",
                "suspiciousFundingIndependentSupportSources": "",
                "repricingSourceQuality": "none",
            },
            {
                "id": "bad-unknown-grade-quality",
                "severity": "Low Risk",
                "fundingEvidenceGrade": "unknown",
                "suspiciousFundingQuality": "weak",
                "repricingSourceQuality": "none",
            },
        ]

        summary = audit_records(invalid_records)
        warning_codes = {warning["code"] for warning in summary["warnings"]}

        self.assertIn("cex_proxy_only_hard_evidence_review", warning_codes)
        self.assertIn("high_impact_repricing_only_hard_evidence_review", warning_codes)
        self.assertIn("mechanical_repricing_marked_hard_evidence", warning_codes)
        self.assertIn("strong_risk_without_existing_gate", warning_codes)
        self.assertIn("missing_hard_evidence_sources", warning_codes)
        self.assertIn("missing_funding_evidence_grade", warning_codes)
        self.assertIn("missing_repricing_source_quality", warning_codes)
        self.assertIn("proxy_only_grouped_admission_hard_evidence_review", warning_codes)
        self.assertIn("proxy_only_group_claims_strict_funding", warning_codes)
        self.assertIn("missing_candidate_admission_reason", warning_codes)
        self.assertIn("missing_grouped_candidate_id", warning_codes)
        self.assertIn("mechanical_repricing_pre_admission", warning_codes)
        self.assertIn("high_impact_repricing_only_pre_admission", warning_codes)
        self.assertIn("funding_none_with_resolver_unavailable", warning_codes)
        self.assertIn("strict_funding_admission_with_resolver_unavailable", warning_codes)
        self.assertIn("weak_suspicious_funding_only_hard_evidence_review", warning_codes)
        self.assertIn("unknown_suspicious_funding_hard_evidence_review", warning_codes)
        self.assertIn("multi_hop_unknown_mapped_strong_without_quality_support", warning_codes)
        self.assertIn("multi_hop_unknown_strong_without_independent_support", warning_codes)
        self.assertIn("multi_hop_unknown_hard_evidence_without_independent_support", warning_codes)
        self.assertIn("suspicious_funding_suppressor_conflict_missing", warning_codes)
        self.assertIn("suspicious_funding_independent_support_missing_sources", warning_codes)
        self.assertIn("suspicious_funding_only_suppressor_conflict", warning_codes)
        self.assertIn("funding_unknown_quality_not_unknown", warning_codes)

    def test_model_behavior_audit_reports_candidate_admission_distributions(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "valid-pre",
                    "severity": "Low Risk",
                    "candidateAdmissionReason": "strict_shared_funding_group",
                    "candidateAdmissionStage": "pre_admitted_validated",
                    "candidateAdmissionEvidenceSources": "strict_shared_funding_source; split_wallet_pattern",
                    "groupedCandidateId": "strict-group",
                    "groupedCandidateProxyOnly": "No",
                    "groupedCandidateFundingGrade": "direct_strict",
                    "candidateAdmissionValidatedOpeningExposure": "Yes",
                    "fundingEvidenceGrade": "direct_strict",
                    "repricingSourceQuality": "none",
                },
                {
                    "id": "normal",
                    "severity": "Low Risk",
                    "candidateAdmissionStage": "normal_candidate",
                    "fundingEvidenceGrade": "none",
                    "repricingSourceQuality": "none",
                },
            ]
        )

        self.assertEqual(summary["pre_admitted_candidate_rows"], 1)
        self.assertEqual(summary["normal_candidate_rows"], 1)
        self.assertEqual(summary["proxy_only_grouped_admissions"], 0)
        self.assertEqual(summary["warnings"], [])
        self.assertEqual(
            summary["distributions"]["candidateAdmissionReason"]["strict_shared_funding_group"],
            1,
        )
        self.assertEqual(
            summary["distributions"]["groupedCandidateFundingGrade"]["direct_strict"],
            1,
        )

    def test_model_behavior_audit_does_not_flag_legacy_rows_without_resolver_fields(self) -> None:
        summary = audit_records([{"id": "legacy", "severity": "Low Risk"}])
        warning_codes = {warning["code"] for warning in summary["warnings"]}
        self.assertNotIn("funding_none_with_resolver_unavailable", warning_codes)
        self.assertNotIn("missing_resolver_disabled_reason", warning_codes)

    def test_model_behavior_audit_accepts_valid_hard_evidence_record(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "valid-hard",
                    "severity": "Low Risk",
                    "existingModelClass": "Low Risk",
                    "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                    "hardEvidenceSources": "split_wallet_pattern; strict_shared_funding_source",
                    "hardEvidenceStrength": "Strong",
                    "fundingEvidenceGrade": "direct_strict",
                    "funding_graph_key_strict": "0xstrict",
                    "cex_proxy_cluster_flag": "No",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        self.assertEqual(summary["hard_evidence_review_rows"], 1)
        self.assertEqual(summary["warnings"], [])

    def test_model_behavior_audit_accepts_strong_suspicious_funding_quality(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "valid-strong-funding",
                    "severity": "Low Risk",
                    "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                    "hardEvidenceSources": "suspicious_recent_funding",
                    "hardEvidenceStrength": "Strong",
                    "fundingEvidenceGrade": "suspicious_direct",
                    "suspiciousFundingQuality": "strong",
                    "suspiciousFundingHardEvidenceEligible": "Yes",
                    "suspiciousFundingRecentEnough": "Yes",
                    "suspiciousFundingAmountAligned": "Yes",
                    "opening_exposure_flag": "Yes",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        self.assertEqual(summary["hard_evidence_review_rows"], 1)
        self.assertEqual(summary["suspicious_funding_hard_evidence_eligible_rows"], 1)
        self.assertEqual(summary["warnings"], [])

    def test_model_behavior_audit_handles_legacy_records_gracefully(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "legacy-row",
                    "severity": "Worth a Look",
                    "wallet": "0xlegacy",
                }
            ]
        )

        self.assertEqual(summary["total_rows_inspected"], 1)
        self.assertEqual(summary["legacy_or_unknown_schema_rows"], 1)
        self.assertEqual(summary["warnings"], [])

    def test_model_behavior_audit_normalizes_snake_and_camel_case(self) -> None:
        camel = normalize_record(
            {
                "id": "camel",
                "severity": "Low Risk",
                "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                "hardEvidenceSources": ["split_wallet_pattern"],
                "fundingEvidenceGrade": "direct_strict",
                "repricingSourceQuality": "strong",
            }
        )
        snake = normalize_record(
            {
                "id": "snake",
                "severity": "Low Risk",
                "hard_evidence_review_tier": HARD_EVIDENCE_REVIEW_TIER,
                "hard_evidence_sources": ["split_wallet_pattern"],
                "funding_evidence_grade": "direct_strict",
                "repricing_source_quality": "strong",
            }
        )

        self.assertEqual(camel["hard_evidence_review"], snake["hard_evidence_review"])
        self.assertEqual(camel["hard_evidence_sources"], snake["hard_evidence_sources"])
        self.assertEqual(camel["funding_evidence_grade"], snake["funding_evidence_grade"])
        self.assertEqual(camel["repricing_source_quality"], snake["repricing_source_quality"])

    def test_model_behavior_audit_writes_markdown_and_json_outputs(self) -> None:
        summary = audit_records(self._benchmark_lite_records())

        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = write_audit_outputs(
                summary,
                Path(tmpdir),
                timestamp="20260501_000000",
            )
            markdown_path = Path(outputs["markdown_path"])
            json_path = Path(outputs["json_path"])

            self.assertTrue(markdown_path.exists())
            self.assertTrue(json_path.exists())
            self.assertIn("## Next Action", markdown_path.read_text(encoding="utf-8"))
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["total_rows_inspected"], 10)

    def test_model_behavior_audit_reports_hard_evidence_pathway_distribution(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "split-hard",
                    "severity": "Low Risk",
                    "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
                    "hardEvidenceSources": "split_wallet_pattern",
                    "fundingEvidenceGrade": "direct_strict",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        pathway = summary["hard_evidence_pathway_counts"]
        self.assertEqual(pathway["split_wallet_hard_evidence_review_rows"], 1)
        self.assertEqual(summary["distributions"]["hardEvidenceSources"]["split_wallet_pattern"], 1)

    def test_model_behavior_audit_reports_strong_risk_rows_without_hard_sources(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "strong-no-hard",
                    "severity": "Strong Risk",
                    "strongRiskGate": "Yes",
                    "eventForensicScore": "78",
                    "hardEvidenceSources": "",
                    "fundingEvidenceGrade": "none",
                    "repricingSourceQuality": "none",
                    "opening_exposure_flag": "Yes",
                }
            ]
        )

        composition = summary["strong_risk_composition"]
        self.assertEqual(composition["strong_risk_rows_with_no_hard_evidence_sources"], 1)
        self.assertEqual(composition["strong_risk_rows_by_evidence_source"]["none"], 1)

    def test_model_behavior_audit_does_not_count_benign_model_gap_as_current_strong_risk(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "model-gap-benign",
                    "existingModelClass": "Strong Risk",
                    "finalEventJudgment": "Likely contextual or benign",
                    "eventForensicScore": "25",
                    "fundingEvidenceGrade": "multi_hop_unknown",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        self.assertEqual(summary["strong_risk_rows"], 0)
        self.assertEqual(summary["strong_risk_composition"]["strong_risk_rows_with_no_hard_evidence_sources"], 0)

    def test_model_behavior_audit_reports_strong_risk_timing_repricing_only(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "strong-repricing-only",
                    "severity": "Strong Risk",
                    "strongRiskGate": "Yes",
                    "eventForensicScore": "74",
                    "hardEvidenceSources": "",
                    "fundingEvidenceGrade": "none",
                    "favorable_repricing_flag": "Yes",
                    "eventForensicFlags": "post_entry_repricing high-impact timing/repricing",
                    "repricingSourceQuality": "weak",
                    "opening_exposure_flag": "Yes",
                }
            ]
        )

        self.assertEqual(
            summary["strong_risk_composition"]["strong_risk_rows_driven_by_timing_repricing_only"],
            1,
        )

    def test_model_behavior_audit_starvation_detects_independent_support_not_routed(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "split-not-routed",
                    "severity": "Low Risk",
                    "candidateAdmissionStage": "normal_candidate",
                    "hardEvidenceReviewTier": "",
                    "hardEvidenceSources": "",
                    "splitWalletPatternFlag": "Yes",
                    "fundingEvidenceGrade": "direct_strict",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        warning_codes = {warning["code"] for warning in summary["warnings"]}
        starvation = summary["hard_evidence_starvation"]
        self.assertIn("independent_evidence_not_routed_hard_evidence_review", warning_codes)
        self.assertEqual(starvation["independent_sources_observed"]["split_wallet_pattern"], 1)
        self.assertEqual(starvation["independent_sources_not_routed_to_hard_evidence_review_rows"], 1)
        self.assertEqual(summary["large_sample_classification"], "hard-evidence starvation suspected")

    def test_model_behavior_audit_starvation_does_not_flag_clean_rows(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "clean",
                    "severity": "Low Risk",
                    "candidateAdmissionStage": "normal_candidate",
                    "hardEvidenceReviewTier": "",
                    "hardEvidenceSources": "",
                    "fundingEvidenceGrade": "none",
                    "repricingSourceQuality": "none",
                }
            ]
        )

        warning_codes = {warning["code"] for warning in summary["warnings"]}
        starvation = summary["hard_evidence_starvation"]
        self.assertNotIn("independent_evidence_not_routed_hard_evidence_review", warning_codes)
        self.assertFalse(starvation["independent_hard_evidence_sources_appeared"])
        self.assertEqual(starvation["independent_sources_not_routed_to_hard_evidence_review_rows"], 0)

    def test_model_behavior_audit_starvation_legacy_independent_support_is_expected_gap(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "legacy-dormant",
                    "finalEventJudgment": "Meaningful event-forensic concern",
                    "eventForensicFlags": ["opening_exposure", "dormant_reactivation"],
                    "openingExposure": True,
                    "rawMetrics": {
                        "reactivated_after_dormancy_flag": "Yes",
                        "opening_exposure_flag": "Yes",
                        "days_since_prior_wallet_trade": "120.0",
                    },
                }
            ]
        )

        warning_codes = {warning["code"] for warning in summary["warnings"]}
        starvation = summary["hard_evidence_starvation"]
        self.assertNotIn("independent_evidence_not_routed_hard_evidence_review", warning_codes)
        self.assertEqual(starvation["legacy_or_unknown_independent_support_rows"], 1)
        self.assertEqual(starvation["new_format_independent_support_rows"], 0)
        self.assertEqual(starvation["independent_sources_not_routed_to_hard_evidence_review_rows"], 0)

    def test_model_behavior_audit_starvation_short_dormancy_is_not_hard_evidence(self) -> None:
        summary = audit_records(
            [
                {
                    "id": "short-dormant",
                    "severity": "Low Risk",
                    "candidateAdmissionStage": "normal_candidate",
                    "hardEvidenceReviewTier": "",
                    "hardEvidenceSources": "",
                    "fundingEvidenceGrade": "unknown",
                    "repricingSourceQuality": "none",
                    "openingExposure": True,
                    "rawMetrics": {
                        "reactivated_after_dormancy_flag": "Yes",
                        "opening_exposure_flag": "Yes",
                        "days_since_prior_wallet_trade": "35.0",
                    },
                }
            ]
        )

        starvation = summary["hard_evidence_starvation"]
        self.assertFalse(starvation["independent_hard_evidence_sources_appeared"])
        self.assertEqual(starvation["independent_sources_not_routed_to_hard_evidence_review_rows"], 0)

    def test_model_behavior_audit_large_sample_prefix(self) -> None:
        summary = audit_records([])

        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = write_audit_outputs(
                summary,
                Path(tmpdir),
                timestamp="20260501_000000",
                filename_prefix="large_sample_post_v2",
            )

            self.assertTrue(outputs["markdown_path"].endswith("large_sample_post_v2_20260501_000000.md"))
            self.assertTrue(outputs["json_path"].endswith("large_sample_post_v2_20260501_000000.json"))

    def test_event_forensic_score_rewards_new_patterns(self) -> None:
        market = _market(
            condition_id="cond-forensic",
            slug="maduro-out-by-january-31-2026",
            question="Maduro out by January 31, 2026?",
        )
        trade = _trade(
            trade_id="forensic",
            wallet="0xwallet",
            condition_id="cond-forensic",
            asset_id="asset-yes",
            timestamp=datetime(2026, 1, 20, 12, 0, tzinfo=UTC),
            price="0.12",
            size="35000",
            title=market.question,
            slug=market.slug,
            event_slug="maduro-out-in-2025",
        )
        case = _flagged_case(
            trade=trade,
            market=market,
            raw_metrics={
                "trade_state": "increase",
                "beat_consensus_flag": "Yes",
                "favorable_repricing_flag": "Yes",
                "suspicious_funding_flag": "Yes",
                "shared_funding_source_flag": "Yes",
                "coordinated_cluster_signal": "No",
                "specialist_explained_flag": "No",
                "low_analyst_value_flag": "No",
                "formal_win_rate_may_be_overstated": "No",
                "event_family_repeat_flag": "Yes",
                "reactivated_after_dormancy_flag": "Yes",
                "post_trade_dormancy_flag": "Yes",
                "split_wallet_pattern_flag": "Yes",
                "days_since_prior_wallet_trade": "120.0",
                "days_to_next_wallet_trade": "180.0",
            },
            flags=[],
        )

        score, flags, notes, reducers = _event_forensic_score(
            case=case,
            later_won=True,
            winner_rank=1,
            related_market_count=2,
            wallet_winning_entries=2,
            wallet_opening_entries=3,
        )

        self.assertGreaterEqual(score, 80)
        self.assertIn("event_family_repeat", flags)
        self.assertIn("dormant_reactivation", flags)
        self.assertIn("dormant_after_win", flags)
        self.assertIn("split_wallet_pattern", flags)
        self.assertTrue(notes)
        self.assertEqual(reducers, [])

    def test_event_forensic_score_downgrades_mechanical_repricing_only(self) -> None:
        market = _market(
            condition_id="cond-mechanical-repricing",
            slug="mechanical-repricing",
            question="Mechanical repricing?",
        )
        trade = _trade(
            trade_id="mechanical-repricing",
            wallet="0xmechanical",
            condition_id=market.condition_id,
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.45",
            size="5000",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
        )
        raw = {
            "trade_state": "increase",
            "beat_consensus_flag": "No",
            "favorable_repricing_flag": "Yes",
            "market_liquidity_usdc": "50000",
            "liquidity_ratio": "20.0%",
            "repricing_source_quality": "mechanical",
            "suspicious_funding_flag": "No",
            "shared_funding_source_flag": "No",
            "split_wallet_pattern_flag": "No",
            "reactivated_after_dormancy_flag": "No",
            "opening_exposure_flag": "Yes",
            "hardEvidenceReviewTier": "",
        }
        case = _flagged_case(trade=trade, market=market, raw_metrics=dict(raw), flags=[])
        case.suspicion_score = 60

        score, flags, _notes, reducers = _event_forensic_score(
            case=case,
            later_won=False,
            winner_rank=None,
            related_market_count=0,
            wallet_winning_entries=0,
            wallet_opening_entries=1,
        )

        self.assertLess(score, 40)
        self.assertIn("post_entry_repricing", flags)
        self.assertIn("mechanical", " ".join(reducers))

    def test_event_forensic_score_does_not_downgrade_strong_repricing_quality(self) -> None:
        market = _market(
            condition_id="cond-strong-repricing",
            slug="strong-repricing",
            question="Strong repricing?",
        )
        trade = _trade(
            trade_id="strong-repricing",
            wallet="0xstrong",
            condition_id=market.condition_id,
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.45",
            size="5000",
            title=market.question,
            slug=market.slug,
            event_slug=market.slug,
        )
        raw = {
            "trade_state": "increase",
            "beat_consensus_flag": "No",
            "favorable_repricing_flag": "Yes",
            "market_liquidity_usdc": "500000",
            "liquidity_ratio": "1.0%",
            "repricing_source_quality": "strong",
            "suspicious_funding_flag": "No",
            "shared_funding_source_flag": "No",
            "split_wallet_pattern_flag": "No",
            "reactivated_after_dormancy_flag": "No",
            "opening_exposure_flag": "Yes",
            "hardEvidenceReviewTier": "",
        }
        case = _flagged_case(trade=trade, market=market, raw_metrics=dict(raw), flags=[])
        case.suspicion_score = 60

        score, flags, _notes, reducers = _event_forensic_score(
            case=case,
            later_won=False,
            winner_rank=None,
            related_market_count=0,
            wallet_winning_entries=0,
            wallet_opening_entries=1,
        )

        self.assertGreaterEqual(score, 48)
        self.assertIn("post_entry_repricing", flags)
        self.assertNotIn("repricing source quality", " ".join(reducers).lower())

    def test_event_forensic_score_suppresses_poor_history_near_certainty_winner(self) -> None:
        market = _market(
            condition_id="cond-near-certain",
            slug="us-strikes-iran-by-february-28-2026",
            question="US strikes Iran by February 28, 2026?",
        )
        trade = _trade(
            trade_id="near-certain",
            wallet="0xweak",
            condition_id="cond-near-certain",
            asset_id="asset-yes",
            timestamp=datetime(2026, 2, 28, 7, 26, tzinfo=UTC),
            price="0.99",
            size="5000",
            title=market.question,
            slug=market.slug,
            event_slug="us-strikes-iran-by",
        )
        case = _flagged_case(
            trade=trade,
            market=market,
            raw_metrics={
                "trade_state": "increase",
                "beat_consensus_flag": "No",
                "favorable_repricing_flag": "No",
                "suspicious_funding_flag": "No",
                "shared_funding_source_flag": "No",
                "coordinated_cluster_signal": "Yes",
                "specialist_explained_flag": "No",
                "low_analyst_value_flag": "No",
                "formal_win_rate_may_be_overstated": "No",
                "event_family_repeat_flag": "No",
                "reactivated_after_dormancy_flag": "No",
                "post_trade_dormancy_flag": "Yes",
                "split_wallet_pattern_flag": "No",
                "days_since_prior_wallet_trade": "First visible trade",
                "days_to_next_wallet_trade": "46.0",
                "wallet_economic_sample_size": "181",
                "wallet_economic_win_rate": "0.6%",
            },
            flags=["near_certainty_trade"],
        )
        case.suspicion_score = 20

        score, flags, _notes, reducers = _event_forensic_score(
            case=case,
            later_won=True,
            winner_rank=24,
            related_market_count=0,
            wallet_winning_entries=4,
            wallet_opening_entries=4,
        )

        self.assertLess(score, 40)
        self.assertIn("weak_wallet_track_record", flags)
        self.assertIn("near_certainty_winner", flags)
        self.assertTrue(any("losing record" in reducer or "near certainty" in reducer for reducer in reducers))

    def test_event_forensic_score_caps_public_power_user_without_concrete_linkage(self) -> None:
        market = _market(
            condition_id="cond-public-power",
            slug="hormuz-transit",
            question="Will ships transit the Strait of Hormuz?",
        )
        trade = _trade(
            trade_id="public-power",
            wallet="0xpower",
            condition_id=market.condition_id,
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 21, 16, 0, tzinfo=UTC),
            price="0.22",
            size="6860",
            title=market.question,
            slug=market.slug,
            event_slug="hormuz",
        )
        case = _flagged_case(
            trade=trade,
            market=market,
            raw_metrics={
                "trade_state": "increase",
                "favorable_repricing_flag": "Yes",
                "repricing_source_quality": "weak",
                "beat_consensus_flag": "No",
                "suspicious_funding_flag": "No",
                "shared_funding_source_flag": "No",
                "split_wallet_pattern_flag": "No",
                "reactivated_after_dormancy_flag": "No",
                "post_trade_dormancy_flag": "No",
                "wallet_traded_market_count": "765",
                "wallet_recent_trade_count": "500",
                "wallet_unique_market_count": "342",
                "wallet_economic_sample_size": "330",
                "wallet_economic_win_rate": "7.6%",
            },
            flags=[],
        )
        case.suspicion_score = 52

        score, flags, _notes, reducers = _event_forensic_score(
            case=case,
            later_won=True,
            winner_rank=1,
            related_market_count=0,
            wallet_winning_entries=1,
            wallet_opening_entries=1,
        )

        self.assertLess(score, 40)
        self.assertIn("public_power_user", flags)
        self.assertIn("weak_wallet_track_record", flags)
        self.assertIn("more than 100 public predictions", " ".join(reducers))
        self.assertIn("broad public prediction history", _trade_summary(case, True, flags, reducers))

    def test_event_forensic_score_allows_public_power_user_with_concrete_linkage(self) -> None:
        market = _market(
            condition_id="cond-linked-power",
            slug="linked-power-user",
            question="Linked power user?",
        )
        trade = _trade(
            trade_id="linked-power",
            wallet="0xlinkedpower",
            condition_id=market.condition_id,
            asset_id="asset-yes",
            timestamp=datetime(2026, 4, 21, 16, 0, tzinfo=UTC),
            price="0.22",
            size="6860",
            title=market.question,
            slug=market.slug,
            event_slug="linked-power-user",
        )
        case = _flagged_case(
            trade=trade,
            market=market,
            raw_metrics={
                "trade_state": "increase",
                "beat_consensus_flag": "No",
                "favorable_repricing_flag": "No",
                "suspicious_funding_flag": "No",
                "shared_funding_source_flag": "Yes",
                "funding_graph_key_strict": "funder|hour|side",
                "shared_funding_source_wallet_count": "2",
                "cex_proxy_cluster_flag": "No",
                "split_wallet_pattern_flag": "No",
                "reactivated_after_dormancy_flag": "No",
                "post_trade_dormancy_flag": "No",
                "wallet_traded_market_count": "765",
                "wallet_recent_trade_count": "500",
                "wallet_unique_market_count": "342",
            },
            flags=[],
        )
        case.suspicion_score = 52

        score, flags, _notes, reducers = _event_forensic_score(
            case=case,
            later_won=True,
            winner_rank=1,
            related_market_count=0,
            wallet_winning_entries=1,
            wallet_opening_entries=1,
        )

        self.assertGreaterEqual(score, 40)
        self.assertIn("public_power_user", flags)
        self.assertIn("shared_funder_cluster", flags)
        self.assertIn("keeps it reviewable", " ".join(reducers))

    def test_wallet_review_domain_counts_detects_sports_history_from_titles(self) -> None:
        iran_market = _market(
            condition_id="cond-iran",
            slug="iran-meeting",
            question="US x Iran diplomatic meeting by April 27, 2026?",
        )
        history = [
            _trade(
                trade_id="iran",
                wallet="0xdiverse",
                condition_id=iran_market.condition_id,
                asset_id="iran-no",
                timestamp=datetime(2026, 4, 20, tzinfo=UTC),
                price="0.70",
                size="1000",
                title=iran_market.question,
                slug=iran_market.slug,
                event_slug="iran-diplomatic-meeting",
            ),
            _trade(
                trade_id="ufc",
                wallet="0xdiverse",
                condition_id="cond-ufc",
                asset_id="ufc-yes",
                timestamp=datetime(2026, 4, 21, tzinfo=UTC),
                price="0.43",
                size="1000",
                title="UFC Fight Night: Yousri Belgaroui vs. Mansur Abdul-Malik",
                slug="ufc-fight-night-yousri-belgaroui-vs-mansur-abdul-malik",
                event_slug="ufc-fight-night",
            ),
        ]

        counts = _wallet_review_domain_counts(history, {iran_market.condition_id: iran_market})

        self.assertEqual(counts["Middle East"], 1)
        self.assertEqual(counts["Sports"], 1)

    def test_event_forensic_score_downgrades_cross_domain_public_bettor_without_hard_evidence(self) -> None:
        market = _market(
            condition_id="cond-iran-cross-domain",
            slug="us-iran-ceasefire",
            question="US x Iran ceasefire extended by April 22, 2026?",
        )
        trade = _trade(
            trade_id="iran-cross-domain",
            wallet="0xdiverse",
            condition_id=market.condition_id,
            asset_id="asset-no",
            timestamp=datetime(2026, 4, 20, 12, 0, tzinfo=UTC),
            price="0.70",
            size="10000",
            title=market.question,
            slug=market.slug,
            event_slug="us-iran-ceasefire",
            outcome="NO",
        )
        sports_trade = _trade(
            trade_id="ufc-cross-domain",
            wallet="0xdiverse",
            condition_id="cond-ufc-cross-domain",
            asset_id="ufc-yes",
            timestamp=datetime(2026, 4, 19, 12, 0, tzinfo=UTC),
            price="0.43",
            size="10000",
            title="UFC Fight Night: Yousri Belgaroui vs. Mansur Abdul-Malik",
            slug="ufc-fight-night-yousri-belgaroui-vs-mansur-abdul-malik",
            event_slug="ufc-fight-night",
        )
        case = _flagged_case(
            trade=trade,
            market=market,
            raw_metrics={
                "trade_state": "increase",
                "trade_domain": "Middle East",
                "beat_consensus_flag": "No",
                "favorable_repricing_flag": "No",
                "suspicious_funding_flag": "No",
                "shared_funding_source_flag": "No",
                "coordinated_cluster_signal": "No",
                "specialist_explained_flag": "No",
                "low_analyst_value_flag": "No",
                "formal_win_rate_may_be_overstated": "No",
                "event_family_repeat_flag": "No",
                "reactivated_after_dormancy_flag": "No",
                "post_trade_dormancy_flag": "No",
                "split_wallet_pattern_flag": "No",
            },
            flags=[],
        )
        case.suspicion_score = 75
        _annotate_wallet_domain_diversity(
            case,
            wallet_history_trades=[sports_trade, trade],
            focus_markets={market.condition_id: market},
        )

        score, flags, _notes, reducers = _event_forensic_score(
            case=case,
            later_won=False,
            winner_rank=None,
            related_market_count=0,
            wallet_winning_entries=0,
            wallet_opening_entries=1,
        )

        self.assertEqual(case.raw_metrics["wallet_cross_domain_public_bettor_flag"], "Yes")
        self.assertIn("cross_domain_public_bettor", flags)
        self.assertLess(score, 40)
        self.assertTrue(any("sports/public-betting" in reducer for reducer in reducers))

    def test_primary_suspicious_wallet_rows_excludes_secondary_only_weak_history(self) -> None:
        rows = [
            {
                "wallet": "0xweak",
                "walletScore": 67,
                "suspiciousTradeCount": 3,
                "walletQualityGate": "secondary_only",
                "primaryEvidenceStatus": "Timing-only or weak evidence",
            },
            {
                "wallet": "0xstrong",
                "walletScore": 48,
                "suspiciousTradeCount": 1,
                "walletQualityGate": "primary_allowed",
                "primaryEvidenceStatus": "Independent evidence",
            },
        ]

        visible = _primary_suspicious_wallet_rows(rows)

        self.assertEqual([row["wallet"] for row in visible], ["0xstrong"])

    def test_evidence_warnings_show_blockchain_disabled_when_requested(self) -> None:
        warnings = _evidence_warnings(
            {"funding_rpc_disabled_reason": "HTTPError: HTTP Error 401: Unauthorized"},
            include_blockchain=True,
        )

        self.assertEqual(len(warnings), 1)
        self.assertIn("Blockchain linkage was requested", warnings[0])
        self.assertEqual(_evidence_warnings({}, include_blockchain=False), [])

        cap_warnings = _evidence_warnings(
            {"truncated_market_count": 2},
            include_blockchain=False,
        )
        self.assertEqual(len(cap_warnings), 1)
        self.assertIn("pagination cap", cap_warnings[0])

    def test_archive_report_markdown_includes_funding_availability_note(self) -> None:
        report = {
            "generated_at": "2026-05-02T00:00:00+00:00",
            "range_start": "2026-05-01T00:00:00+00:00",
            "range_end": "2026-05-02T00:00:00+00:00",
            "range_hours": 24,
            "topic_scope": "World",
            "raw_trade_count": 0,
            "filtered_trade_count": 0,
            "candidate_trade_count": 0,
            "unique_wallet_count": 0,
            "unique_market_count": 0,
            "truncated_market_count": 0,
            "flagged_case_count": 0,
            "secondary_review_case_count": 0,
            "export_files": {},
            "cases": [],
            "funding_resolver_health": {
                "fundingResolverAvailable": False,
                "fundingResolverAuthError": True,
                "fundingResolverDisabledReason": "HTTPError: HTTP Error 401: Unauthorized",
            },
        }

        markdown = _archive_to_markdown(report)

        self.assertIn("Funding resolver: unavailable - auth_error", markdown)
        self.assertIn("Funding evidence: not assessed because resolver unavailable", markdown)

    def test_event_forensic_judgment_can_emit_retrospective_strong_risk(self) -> None:
        self.assertEqual(
            _event_judgment(78, later_won=True, opening_exposure=True),
            "Strong Risk: Retrospective",
        )

    def test_extract_polymarket_resource_kind_handles_locale_prefix(self) -> None:
        self.assertEqual(
            _extract_polymarket_resource_kind("https://polymarket.com/uk/event/us-strikes-iran-by"),
            "event",
        )
        self.assertEqual(
            _extract_polymarket_resource_kind("https://polymarket.com/market/us-strikes-iran-by-january-14-2026-913"),
            "market",
        )
        self.assertIsNone(_extract_polymarket_resource_kind("us-strikes-iran-by"))

    def test_event_page_fallback_recovers_event_payload(self) -> None:
        client = PolymarketClient()
        event_payload = {
            "id": "114242",
            "slug": "us-strikes-iran-by",
            "title": "US strikes Iran by...?",
            "markets": [
                {
                    "id": "1175504",
                    "slug": "us-strikes-iran-by-january-14-2026-913",
                    "conditionId": "0xcond",
                    "question": "US strikes Iran by January 14, 2026?",
                }
            ],
        }
        html = _next_data_html(query_slug=["us-strikes-iran-by"], event_payload=event_payload)

        with mock.patch("app.polymarket._get_text", return_value=html):
            resolved_event, source_market = client.fetch_event_resolution_from_pages(
                "us-strikes-iran-by",
                page_hint="event",
            )

        self.assertEqual(resolved_event, event_payload)
        self.assertIsNone(source_market)

    def test_market_page_fallback_recovers_parent_event_and_source_market(self) -> None:
        client = PolymarketClient()
        event_payload = {
            "id": "114242",
            "slug": "us-strikes-iran-by",
            "title": "US strikes Iran by...?",
            "markets": [
                {
                    "id": "1175504",
                    "slug": "us-strikes-iran-by-january-14-2026-913",
                    "conditionId": "0xcond",
                    "question": "US strikes Iran by January 14, 2026?",
                },
                {
                    "id": "1175524",
                    "slug": "us-strikes-iran-by-january-15-2026-652-612",
                    "conditionId": "0xother",
                    "question": "US strikes Iran by January 15, 2026?",
                },
            ],
        }
        html = _next_data_html(
            query_slug=["us-strikes-iran-by", "us-strikes-iran-by-january-14-2026-913"],
            event_payload=event_payload,
        )

        with mock.patch("app.polymarket._get_text", return_value=html):
            resolved_event, source_market = client.fetch_event_resolution_from_pages(
                "us-strikes-iran-by-january-14-2026-913",
                page_hint="market",
            )

        self.assertEqual(resolved_event, event_payload)
        assert source_market is not None
        self.assertEqual(source_market["slug"], "us-strikes-iran-by-january-14-2026-913")
        self.assertEqual(source_market["conditionId"], "0xcond")
        self.assertEqual(source_market["events"], [{"slug": "us-strikes-iran-by"}])

    def test_resolve_target_expands_whole_event_to_case_family_markets(self) -> None:
        custody_event = {
            "id": "event-custody",
            "slug": "maduro-in-us-custody-by-january-31",
            "title": "Maduro in U.S. custody by January 31?",
            "closed": True,
            "endDate": datetime(2026, 1, 31, tzinfo=UTC).isoformat(),
            "tags": [{"id": "246", "label": "Venezuela", "slug": "venezuela"}],
            "markets": [
                {
                    "id": "market-custody",
                    "slug": "maduro-in-us-custody-by-january-31",
                    "conditionId": "cond-custody",
                    "question": "Maduro in U.S. custody by January 31?",
                    "closed": True,
                    "endDate": datetime(2026, 1, 31, tzinfo=UTC).isoformat(),
                }
            ],
        }
        out_event = {
            "id": "event-out",
            "slug": "maduro-out-in-2025",
            "title": "Maduro out by...?",
            "closed": True,
            "endDate": datetime(2026, 1, 31, tzinfo=UTC).isoformat(),
            "tags": [{"id": "246", "label": "Venezuela", "slug": "venezuela"}],
            "markets": [
                {
                    "id": "market-out",
                    "slug": "maduro-out-by-january-31-2026-318",
                    "conditionId": "cond-out",
                    "question": "Maduro out by January 31, 2026?",
                    "closed": True,
                    "endDate": datetime(2026, 1, 31, tzinfo=UTC).isoformat(),
                }
            ],
        }
        speech_event = {
            "id": "event-speech",
            "slug": "will-trump-say-maduro-before-january-31",
            "title": "Will Trump say Maduro before January 31?",
            "closed": True,
            "endDate": datetime(2026, 1, 31, tzinfo=UTC).isoformat(),
            "tags": [{"id": "246", "label": "Venezuela", "slug": "venezuela"}],
            "markets": [
                {
                    "id": "market-speech",
                    "slug": "will-trump-say-maduro-before-january-31",
                    "conditionId": "cond-speech",
                    "question": "Will Trump say Maduro before January 31?",
                    "closed": True,
                    "endDate": datetime(2026, 1, 31, tzinfo=UTC).isoformat(),
                }
            ],
        }

        class FakeClient:
            def fetch_event_by_slug(self, slug):
                return custody_event if slug == custody_event["slug"] else None

            def fetch_market_by_slug(self, slug):
                return None

            def fetch_event_resolution_from_pages(self, slug, *, page_hint=None):
                return None, None

            def fetch_events_by_tag(self, tag_id, **kwargs):
                return [out_event, speech_event]

        analyzer = EventForensicAnalyzer(
            client=FakeClient(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )

        target = analyzer.resolve_target(
            "https://polymarket.com/event/maduro-in-us-custody-by-january-31",
            analysis_scope="event",
            include_related_markets=True,
        )

        slugs = {item["marketSlug"] for item in target["availableMarkets"]}
        self.assertIn("maduro-in-us-custody-by-january-31", slugs)
        self.assertIn("maduro-out-by-january-31-2026-318", slugs)
        self.assertNotIn("will-trump-say-maduro-before-january-31", slugs)

    def test_prefetch_wallet_contexts_reuses_seeded_future(self) -> None:
        analyzer = EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )
        focus_markets = {"cond-seeded": _market(condition_id="cond-seeded", slug="seeded", question="Seeded?")}
        seeded_trade = _trade(
            trade_id="seeded-trade",
            wallet="0xseeded",
            condition_id="cond-seeded",
            asset_id="asset-seeded",
            timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            price="0.50",
            size="4000",
            title="Seeded?",
            slug="seeded",
            event_slug="seeded-event",
        )
        fresh_trade = _trade(
            trade_id="fresh-trade",
            wallet="0xfresh",
            condition_id="cond-seeded",
            asset_id="asset-seeded",
            timestamp=datetime(2026, 4, 7, 12, 10, tzinfo=UTC),
            price="0.45",
            size="5000",
            title="Seeded?",
            slug="seeded",
            event_slug="seeded-event",
        )
        seeded_result = (_wallet_inspection(2), [seeded_trade], _wallet_performance())
        fresh_result = (_wallet_inspection(3), [fresh_trade], _wallet_performance())
        seeded_future: Future = Future()
        seeded_future.set_result(seeded_result)
        wallet_cache: dict[str, tuple[object, list[Trade], WalletPerformance]] = {}

        with mock.patch.object(analyzer, "_fetch_wallet_context", return_value=fresh_result) as mocked_fetch:
            analyzer._prefetch_wallet_contexts(
                [seeded_trade, fresh_trade],
                wallet_cache,
                focus_markets,
                progress_callback=None,
                stop_event=None,
                prestarted_futures={"0xseeded": seeded_future},
            )

        self.assertEqual(wallet_cache["0xseeded"], seeded_result)
        self.assertEqual(wallet_cache["0xfresh"], fresh_result)
        mocked_fetch.assert_called_once_with("0xfresh", focus_markets)

    def test_event_forensic_disabled_funding_prefetch_does_not_call_resolver(self) -> None:
        analyzer = EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )
        analyzer._funding_resolver = mock.Mock()
        funding_cache: dict[tuple[str, str], FundingContext] = {}

        analyzer._prefetch_funding_contexts(
            {("0xabc", "2026040712"): ("0xabc", datetime(2026, 4, 7, 12, 0, tzinfo=UTC))},
            funding_cache,
            funding_trace_mode="disabled",
            progress_callback=None,
            stop_event=None,
        )

        analyzer._funding_resolver.analyze.assert_not_called()
        self.assertEqual(funding_cache, {})

    def test_event_forensic_warnings_disclose_disabled_funding_unknown_not_none(self) -> None:
        warnings = _evidence_warnings(
            {
                "fundingTraceMode": "disabled",
                "funding_resolver_health": {
                    "fundingResolverAvailable": False,
                    "fundingResolverFunctionalStatus": "disabled_no_rpc_mode",
                    "fundingTraceAttemptedCount": 0,
                    "fundingTraceSucceededCount": 0,
                },
            },
            include_blockchain=True,
        )

        self.assertTrue(any("funding evidence is unknown, not none" in item for item in warnings))

    def test_event_forensic_ui_exposes_funding_trace_mode_control(self) -> None:
        html = Path("app/browser_event_forensic_ui.html").read_text(encoding="utf-8")
        self.assertIn("fundingTraceMode", html)
        self.assertIn('value="live_rpc"', html)
        self.assertIn('value="cache_only"', html)
        self.assertIn('value="disabled"', html)
        self.assertIn('fundingTraceMode: ""', html)
        self.assertIn('value={filters.fundingTraceMode || "disabled"}', html)

    def test_event_forensic_ui_child_market_picker_does_not_require_scope_toggle(self) -> None:
        html = Path("app/browser_event_forensic_ui.html").read_text(encoding="utf-8")
        self.assertIn('const showChildMarketPicker = analysisScope === "market" || availableMarkets.length > 0', html)
        self.assertIn("Selecting a child market switches scope to Single market", html)
        self.assertIn('analysisScope: nextConditionId ? "market" : "event"', html)
        self.assertIn('Whole event / no child market selected', html)
        self.assertIn('analysisScope: "event"', html)
        self.assertIn('selectedConditionId: ""', html)

    def test_event_forensic_ui_minimum_trade_size_is_easy_to_replace(self) -> None:
        html = Path("app/browser_event_forensic_ui.html").read_text(encoding="utf-8")
        self.assertIn('onFocus={event => event.target.select()}', html)
        self.assertIn('inputMode="decimal"', html)
        self.assertIn('aria-label="Minimum trade size"', html)

    def test_event_forensic_ui_exposes_entry_probability_and_time_window_controls(self) -> None:
        html = Path("app/browser_event_forensic_ui.html").read_text(encoding="utf-8")
        self.assertIn('maxEntryProbability: ""', html)
        self.assertIn('aria-label="Maximum entry probability percent"', html)
        self.assertIn("filterRowsForTab(activeTab, baseRows, filters)", html)
        self.assertIn("Show all trade rows", html)
        self.assertIn('startDateTime: ""', html)
        self.assertIn('endDateTime: ""', html)
        self.assertIn("updateDateTimeFilter", html)
        self.assertIn('type="date"', html)
        self.assertIn('type="time"', html)
        self.assertIn('aria-label="Analysis start date"', html)
        self.assertIn('aria-label="Analysis start time"', html)
        self.assertIn('aria-label="Analysis end date"', html)
        self.assertIn('aria-label="Analysis end time"', html)
        self.assertIn("tradeEntryProbabilitySortValue", html)
        self.assertIn('value: "forensic-desc", label: "Event forensic priority (recommended)"', html)
        self.assertIn('value: "entryProbability-asc", label: "Lowest entry price / implied probability"', html)
        self.assertIn('value: "existingModelScore-desc", label: "Base scanner score (diagnostic)"', html)
        self.assertIn('if (mode === "forensic-desc") return compareTradeConcern(left, right);', html)
        self.assertIn("numericValue(right.eventForensicScore) - numericValue(left.eventForensicScore)", html)
        self.assertIn("hardEvidenceRank(right) - hardEvidenceRank(left)", html)
        self.assertIn("numericValue(right.existingModelScore) - numericValue(left.existingModelScore)", html)
        self.assertIn("numericValue(right.positionSize) - numericValue(left.positionSize)", html)
        self.assertIn(
            'if (mode === "existingModelScore-desc") return numericValue(right.existingModelScore) - numericValue(left.existingModelScore) || compareTradeConcern(left, right);',
            html,
        )
        self.assertIn('mode === "entryProbability-asc"', html)
        self.assertIn(
            'if (mode === "entryProbability-asc") return tradeEntryProbabilitySortValue(left) - tradeEntryProbabilitySortValue(right) || compareTradeConcern(left, right);',
            html,
        )
        self.assertIn("return percent === null ? Number.POSITIVE_INFINITY : percent;", html)
        self.assertIn("const rows = filterRowsForTab(activeTab, baseRows, filters);", html)
        self.assertIn("const sortedRows = useMemo(() => sortRowsForTab(activeTab, rows, sortMode)", html)
        self.assertIn("Event concern ${item.eventForensicScore}/100", html)
        self.assertIn("Base scanner: ${numericValue(item.existingModelScore)}/100", html)
        self.assertIn("numericValueAvailable(item.existingModelScore)", html)
        self.assertIn("Event forensic priority = Event Forensic overlay (eventForensicScore)", html)
        self.assertIn("Base scanner score = shared _score_trade() score (existingModelScore)", html)
        self.assertIn("Sorting changes only loaded visible rows", html)
        trade_sort_options = html[html.index("function sortOptionsForTab") : html.index("function sortRowsForTab")]
        self.assertNotIn('label: "Highest forensic concern"', trade_sort_options)
        self.assertNotIn('label: "Highest current-model score"', trade_sort_options)
        self.assertNotIn('label: "Lowest entry probability"', trade_sort_options)

    def test_collect_event_trades_invokes_market_callback(self) -> None:
        analyzer = EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )
        market_one = _market(condition_id="cond-1", slug="market-one", question="Market one?")
        market_two = _market(condition_id="cond-2", slug="market-two", question="Market two?")
        resolved = ResolvedEvent(
            input_value="https://polymarket.com/event/test-event",
            canonical_url="https://polymarket.com/event/test-event",
            event_id="event-1",
            event_slug="test-event",
            event_title="Test event",
            event_description="",
            event_category="Politics",
            event_closed=True,
            event_end_date=datetime(2026, 4, 8, tzinfo=UTC).isoformat(),
            source_market_slug=None,
            source_condition_id=None,
            event_payload={
                "slug": "test-event",
                "startDate": datetime(2026, 4, 1, tzinfo=UTC).isoformat(),
                "endDate": datetime(2026, 4, 8, tzinfo=UTC).isoformat(),
            },
            markets={"cond-1": market_one, "cond-2": market_two},
            market_payloads={},
            event_family_id="test-event",
            family_tokens={"test", "event"},
        )
        first_market_trades = [
            _trade(
                trade_id="trade-1",
                wallet="0xwallet1",
                condition_id="cond-1",
                asset_id="asset-1",
                timestamp=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
                price="0.40",
                size="3000",
                title=market_one.question,
                slug=market_one.slug,
                event_slug=resolved.event_slug,
            )
        ]
        second_market_trades = [
            _trade(
                trade_id="trade-2",
                wallet="0xwallet2",
                condition_id="cond-2",
                asset_id="asset-2",
                timestamp=datetime(2026, 4, 7, 13, 0, tzinfo=UTC),
                price="0.35",
                size="3500",
                title=market_two.question,
                slug=market_two.slug,
                event_slug=resolved.event_slug,
            )
        ]
        seen: list[tuple[str, list[str]]] = []
        progress_events: list[object] = []
        collection_progress: dict[str, object] = {}

        with mock.patch("app.event_forensic.EVENT_FORENSIC_MARKET_FETCH_WORKERS", 1), mock.patch.object(
            analyzer,
            "_fetch_market_trade_slice",
            side_effect=[
                ("cond-1", first_market_trades, False),
                ("cond-2", second_market_trades, False),
            ],
        ):
            trades, truncated_market_count = analyzer._collect_event_trades(
                resolved,
                minimum_notional=Decimal("1000"),
                progress_callback=progress_events.append,
                stop_event=None,
                on_market_trades=lambda condition_id, rows: seen.append(
                    (condition_id, [trade.trade_id for trade in rows])
                ),
                collection_progress=collection_progress,
            )

        self.assertEqual(truncated_market_count, 0)
        self.assertEqual({trade.trade_id for trade in trades}, {"trade-1", "trade-2"})
        self.assertEqual(seen, [("cond-1", ["trade-1"]), ("cond-2", ["trade-2"])])
        self.assertEqual(collection_progress["analysisMarketTotal"], 2)
        self.assertEqual(collection_progress["analysisMarketCompleted"], 2)
        self.assertEqual(collection_progress["rawTradeRowsCollectedSoFar"], 2)
        self.assertEqual(collection_progress["lastCollectedMarketSlug"], "market-two")
        self.assertEqual(collection_progress["collectionRiskClass"], "collection_profile_normal")
        self.assertEqual(collection_progress["singleMarketSiblingContextCount"], 0)
        self.assertTrue(progress_events)
        self.assertEqual(getattr(progress_events[-1], "metadata", {})["analysisMarketCompleted"], 2)

    def test_collect_live_event_without_start_date_uses_current_window(self) -> None:
        analyzer = EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )
        market = _market(condition_id="cond-live", slug="live-market", question="Live market?")
        future_end = datetime.now(UTC) + timedelta(days=30)
        resolved = ResolvedEvent(
            input_value="https://polymarket.com/event/live-event",
            canonical_url="https://polymarket.com/event/live-event",
            event_id="event-live",
            event_slug="live-event",
            event_title="Live event",
            event_description="",
            event_category="Politics",
            event_closed=False,
            event_end_date=future_end.isoformat(),
            source_market_slug=None,
            source_condition_id=None,
            event_payload={"slug": "live-event", "endDate": future_end.isoformat()},
            markets={"cond-live": market},
            market_payloads={"cond-live": {"conditionId": "cond-live", "closed": False}},
            event_family_id="live-event",
            family_tokens={"live", "event"},
        )
        calls: list[tuple[int, int]] = []

        def fake_fetch(condition_id: str, *, start_ts: int, end_ts: int, minimum_notional: Decimal | None = None):
            calls.append((start_ts, end_ts))
            return condition_id, [], False

        before = int((datetime.now(UTC) - timedelta(days=367)).timestamp())
        after = int((datetime.now(UTC) + timedelta(days=1)).timestamp())
        with mock.patch("app.event_forensic.EVENT_FORENSIC_MARKET_FETCH_WORKERS", 1), mock.patch.object(
            analyzer,
            "_fetch_market_trade_slice",
            side_effect=fake_fetch,
        ):
            analyzer._collect_event_trades(
                resolved,
                minimum_notional=Decimal("1000"),
                progress_callback=None,
                stop_event=None,
            )

        self.assertEqual(len(calls), 1)
        start_ts, end_ts = calls[0]
        self.assertGreaterEqual(start_ts, before)
        self.assertLessEqual(end_ts, after)
        self.assertLess(end_ts, int(future_end.timestamp()))

    def test_collect_event_trades_respects_explicit_time_window(self) -> None:
        analyzer = EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )
        market = _market(condition_id="cond-window", slug="window-market", question="Window market?")
        resolved = ResolvedEvent(
            input_value="https://polymarket.com/event/window-event",
            canonical_url="https://polymarket.com/event/window-event",
            event_id="event-window",
            event_slug="window-event",
            event_title="Window event",
            event_description="",
            event_category="Politics",
            event_closed=True,
            event_end_date="2026-06-30T00:00:00+00:00",
            source_market_slug=None,
            source_condition_id=None,
            event_payload={
                "slug": "window-event",
                "startDate": "2026-01-01T00:00:00+00:00",
                "endDate": "2026-06-30T00:00:00+00:00",
            },
            markets={"cond-window": market},
            market_payloads={
                "cond-window": {
                    "conditionId": "cond-window",
                    "startDate": "2026-01-01T00:00:00+00:00",
                    "endDate": "2026-06-30T00:00:00+00:00",
                    "closed": True,
                }
            },
            event_family_id="window-event",
            family_tokens={"window", "event"},
        )
        start_at = datetime(2026, 5, 1, 9, 30, tzinfo=UTC)
        end_at = datetime(2026, 5, 11, 15, 45, tzinfo=UTC)
        calls: list[tuple[int, int]] = []

        def fake_fetch(condition_id: str, *, start_ts: int, end_ts: int, minimum_notional: Decimal | None = None):
            calls.append((start_ts, end_ts))
            return condition_id, [], False

        with mock.patch("app.event_forensic.EVENT_FORENSIC_MARKET_FETCH_WORKERS", 1), mock.patch.object(
            analyzer,
            "_fetch_market_trade_slice",
            side_effect=fake_fetch,
        ):
            analyzer._collect_event_trades(
                resolved,
                minimum_notional=Decimal("1000"),
                start_at=start_at,
                end_at=end_at,
                progress_callback=None,
                stop_event=None,
            )

        self.assertEqual(calls, [(int(start_at.timestamp()), int(end_at.timestamp()))])

    def test_fetch_market_trade_slice_backfills_large_filtered_trades(self) -> None:
        recent_trade = _trade(
            trade_id="recent-small",
            wallet="0xrecent",
            condition_id="cond-1",
            asset_id="asset-1",
            timestamp=datetime(2026, 1, 3, 7, 40, tzinfo=UTC),
            price="0.57",
            size="5",
            title="Maduro out by January 31?",
            slug="maduro-out-by-january-31",
            event_slug="maduro-out-in-2025",
        )
        older_large_trade = _trade(
            trade_id="older-large",
            wallet="0x31a56e9e690c621ed21de08cb559e9524cdb8ed9",
            condition_id="cond-1",
            asset_id="asset-1",
            timestamp=datetime(2026, 1, 3, 2, 58, tzinfo=UTC),
            price="0.08",
            size="88186.77",
            title="Maduro out by January 31?",
            slug="maduro-out-by-january-31",
            event_slug="maduro-out-in-2025",
        )

        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[Decimal | None] = []

            def fetch_trades_in_range(self, **kwargs):
                self.calls.append(kwargs.get("filter_cash_amount"))
                if kwargs.get("filter_cash_amount") is not None:
                    return [older_large_trade]
                return [recent_trade]

        fake_client = FakeClient()
        analyzer = EventForensicAnalyzer(
            client=fake_client,
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )

        _condition_id, trades, truncated = analyzer._fetch_market_trade_slice(
            "cond-1",
            start_ts=0,
            end_ts=2_000_000_000,
            minimum_notional=Decimal("1000"),
        )

        self.assertFalse(truncated)
        self.assertEqual({trade.trade_id for trade in trades}, {"recent-small", "older-large"})
        self.assertEqual(fake_client.calls, [None, Decimal("1000")])

    def test_wallet_trade_replay_metrics_preserve_gap_and_family_semantics(self) -> None:
        trade_one = _trade(
            trade_id="family-1",
            wallet="0xwallet",
            condition_id="cond-a",
            asset_id="asset-a",
            timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            price="0.20",
            size="1000",
            title="US strikes Iran by January 10, 2026?",
            slug="us-strikes-iran-by-january-10-2026",
            event_slug="us-strikes-iran-by-january-10-2026",
        )
        trade_two = _trade(
            trade_id="family-2",
            wallet="0xwallet",
            condition_id="cond-b",
            asset_id="asset-b",
            timestamp=datetime(2026, 2, 15, 12, 0, tzinfo=UTC),
            price="0.25",
            size="1200",
            title="US strikes Iran by February 20, 2026?",
            slug="us-strikes-iran-by-february-20-2026",
            event_slug="us-strikes-iran-by-february-20-2026",
        )
        trade_three = _trade(
            trade_id="other-1",
            wallet="0xwallet",
            condition_id="cond-c",
            asset_id="asset-c",
            timestamp=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
            price="0.30",
            size="900",
            title="Ceasefire by Friday?",
            slug="ceasefire-by-friday",
            event_slug="ceasefire-by-friday",
        )

        metrics = _wallet_trade_replay_metrics([trade_three, trade_one, trade_two])

        self.assertIsNone(metrics["family-1"]["prior_wallet_gap_days"])
        self.assertEqual(metrics["family-1"]["prior_family_trade_count"], 0)
        self.assertEqual(metrics["family-1"]["prior_family_market_count"], 0)
        self.assertEqual(metrics["family-1"]["family_key"], "us-strikes-iran-by")
        self.assertAlmostEqual(metrics["family-1"]["event_family_share"], 2 / 3)
        self.assertGreater(metrics["family-2"]["prior_wallet_gap_days"], 30.0)
        self.assertEqual(metrics["family-2"]["prior_family_trade_count"], 1)
        self.assertEqual(metrics["family-2"]["prior_family_market_count"], 1)
        self.assertEqual(metrics["other-1"]["family_key"], "ceasefire-by-friday")
        self.assertAlmostEqual(metrics["other-1"]["event_family_share"], 1 / 3)

    def test_funding_resolver_disables_rpc_after_auth_error(self) -> None:
        resolver = FundingResolver(rpc_url="https://example.invalid", persistent_cache_enabled=False)
        auth_error = HTTPError(
            resolver._rpc_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(b""),
        )

        with mock.patch("app.funding_context._post_json", side_effect=auth_error) as mocked_post:
            first = resolver.analyze("0xabc", datetime(2026, 4, 7, tzinfo=UTC))

        self.assertEqual(mocked_post.call_count, 1)
        self.assertFalse(first.funding_found)
        self.assertIn("401", first.error or "")
        self.assertEqual(grade_funding_evidence(first), FUNDING_EVIDENCE_UNKNOWN)
        self.assertIn("401", resolver.rpc_disabled_reason or "")
        self.assertTrue(resolver.health().fundingResolverAuthError)

        with mock.patch("app.funding_context._post_json", side_effect=AssertionError("RPC should be skipped")) as mocked_post:
            second = resolver.analyze("0xabc", datetime(2026, 4, 7, tzinfo=UTC))

        mocked_post.assert_not_called()
        self.assertFalse(second.funding_found)
        self.assertEqual(second.error, resolver.rpc_disabled_reason)
        self.assertEqual(grade_funding_evidence(second), FUNDING_EVIDENCE_UNKNOWN)
        self.assertGreaterEqual(resolver.health().fundingTraceSkippedCount, 1)

    def test_funding_resolver_disabled_mode_skips_rpc_and_marks_unknown(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"INSPOLY_FUNDING_TRACE_MODE": "disabled", "INSPOLY_VALIDATION_MODE": "0"},
        ):
            resolver = FundingResolver(
                rpc_url="https://example.invalid",
                trace_mode="disabled",
                persistent_cache_enabled=False,
            )
            with mock.patch("app.funding_context._post_json", side_effect=AssertionError("RPC should be skipped")) as mocked_post:
                context = resolver.analyze("0xabc", datetime(2026, 4, 7, tzinfo=UTC))

        mocked_post.assert_not_called()
        self.assertFalse(context.funding_found)
        self.assertEqual(context.error, "funding_trace_disabled_no_rpc_mode")
        self.assertEqual(grade_funding_evidence(context), FUNDING_EVIDENCE_UNKNOWN)
        health = resolver.health().to_dict()
        self.assertEqual(health["fundingTraceMode"], "disabled")
        self.assertEqual(health["fundingTraceAttemptedCount"], 0)
        self.assertEqual(health["fundingTraceSucceededCount"], 0)
        self.assertEqual(
            health["fundingTraceSkippedReasonDistribution"],
            {"funding_trace_disabled_no_rpc_mode": 1},
        )
        self.assertIn("unknown, not none", health["fundingEvidenceInterpretation"])

    def test_funding_resolver_cache_only_miss_skips_rpc_and_marks_unknown(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"INSPOLY_FUNDING_TRACE_MODE": "cache_only", "INSPOLY_VALIDATION_MODE": "0"},
        ):
            resolver = FundingResolver(
                rpc_url="https://example.invalid",
                trace_mode="cache_only",
                persistent_cache_enabled=False,
            )
            with mock.patch("app.funding_context._post_json", side_effect=AssertionError("RPC should be skipped")) as mocked_post:
                context = resolver.analyze("0xabc", datetime(2026, 4, 7, tzinfo=UTC))

        mocked_post.assert_not_called()
        self.assertFalse(context.funding_found)
        self.assertEqual(context.error, "funding_trace_cache_only_miss")
        self.assertEqual(grade_funding_evidence(context), FUNDING_EVIDENCE_UNKNOWN)
        health = resolver.health().to_dict()
        self.assertEqual(health["fundingTraceMode"], "cache_only")
        self.assertEqual(health["fundingTraceAttemptedCount"], 0)
        self.assertEqual(health["fundingTraceSucceededCount"], 0)
        self.assertEqual(
            health["fundingTraceSkippedReasonDistribution"],
            {"funding_trace_cache_only_miss": 1},
        )

    def test_funding_resolver_falls_back_to_second_rpc_endpoint(self) -> None:
        resolver = FundingResolver(rpc_url="https://bad.example,https://good.example")
        auth_error = HTTPError(
            "https://bad.example",
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(b""),
        )

        def fake_post(url, payload, timeout):
            if url == "https://bad.example":
                raise auth_error
            return {"result": "0x2a"}

        with mock.patch("app.funding_context._post_json", side_effect=fake_post) as mocked_post:
            result = resolver._rpc("eth_blockNumber", [])

        self.assertEqual(result, "0x2a")
        self.assertIsNone(resolver.rpc_disabled_reason)
        self.assertEqual(mocked_post.call_count, 2)

    def test_polygon_nonce_lookup_disables_after_auth_error(self) -> None:
        client = PolymarketClient(polygon_rpc_url="https://polygon-rpc.com")
        auth_error = HTTPError(
            "https://polygon-rpc.com",
            403,
            "Forbidden",
            hdrs=None,
            fp=BytesIO(b""),
        )

        with mock.patch("app.polymarket._post_json", side_effect=auth_error) as mocked_post:
            first = client.fetch_polygon_nonce("0xabc")

        self.assertEqual(mocked_post.call_count, 1)
        self.assertIsNone(first)
        self.assertIn("403", client.polygon_nonce_disabled_reason or "")

        with mock.patch("app.polymarket._post_json", side_effect=AssertionError("nonce RPC should be skipped")) as mocked_post:
            second = client.fetch_polygon_nonce("0xabc")

        mocked_post.assert_not_called()
        self.assertIsNone(second)

    def test_polygon_nonce_lookup_falls_back_to_second_rpc_endpoint(self) -> None:
        client = PolymarketClient(
            polygon_rpc_url="https://bad.example,https://good.example"
        )
        auth_error = HTTPError(
            "https://bad.example",
            403,
            "Forbidden",
            hdrs=None,
            fp=BytesIO(b""),
        )

        def fake_post(url, payload, timeout):
            if url == "https://bad.example":
                raise auth_error
            return {"result": "0x10"}

        with mock.patch("app.polymarket._post_json", side_effect=fake_post) as mocked_post:
            nonce = client.fetch_polygon_nonce("0xabc")

        self.assertEqual(nonce, 16)
        self.assertIsNone(client.polygon_nonce_disabled_reason)
        self.assertEqual(mocked_post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
