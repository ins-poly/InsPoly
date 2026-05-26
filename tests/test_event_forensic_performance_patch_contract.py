from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from datetime import UTC, datetime
from decimal import Decimal

from app.event_forensic import _annotate_wallet_domain_diversity
from app.event_forensic_performance import (
    build_chunk_metadata,
    candidate_performance_cache_key,
    compare_candidate_output_contract,
    build_score_trade_prepared_context_metadata,
    build_scorer_context_profile_metadata,
    build_wallet_context_reuse_metadata,
    summarize_timing_costs,
)
from app.models import FlaggedCase, Market, Trade, WalletInspection
from tools.event_forensic_subset_bottleneck_decomposition import (
    build_bottleneck_decomposition,
    main,
)


class EventForensicPerformancePatchContractTests(unittest.TestCase):
    def test_cache_key_is_deterministic_for_same_candidate_identity(self) -> None:
        first = {
            "wallet": "0xabc",
            "conditionId": "0xcond",
            "tradeId": "trade-1",
            "timestamp": "2026-05-25T00:00:00Z",
            "rawOrderSide": "SELL",
            "rawTokenOutcome": "Yes",
            "economicSide": "No",
        }
        second = dict(reversed(list(first.items())))

        self.assertEqual(candidate_performance_cache_key(first), candidate_performance_cache_key(second))

    def test_chunk_metadata_covers_all_rows_without_hiding(self) -> None:
        metadata = build_chunk_metadata(1201, chunk_size=500)

        self.assertEqual(metadata["chunkCount"], 3)
        self.assertEqual(metadata["coveredItemCount"], 1201)
        self.assertFalse(metadata["rowsHidden"])
        self.assertEqual(metadata["chunks"][-1]["itemCount"], 201)

    def test_candidate_output_contract_passes_when_outputs_match(self) -> None:
        before = [
            {
                "tradeId": "a",
                "eventForensicScore": 60,
                "existingModelScore": 20,
                "candidateAdmissionStage": "normal",
                "reviewBucketAfterPolicy": "primary",
            },
            {
                "tradeId": "b",
                "eventForensicScore": 45,
                "existingModelScore": 10,
                "candidateAdmissionStage": "normal",
                "reviewBucketAfterPolicy": "secondary",
            },
        ]

        result = compare_candidate_output_contract(before, [dict(row) for row in before])

        self.assertTrue(result["passed"])
        self.assertEqual(result["violations"], [])

    def test_candidate_output_contract_detects_score_rank_and_admission_changes(self) -> None:
        before = [
            {"tradeId": "a", "eventForensicScore": 60, "candidateAdmissionStage": "normal"},
            {"tradeId": "b", "eventForensicScore": 45, "candidateAdmissionStage": "normal"},
        ]
        after = [
            {"tradeId": "a", "eventForensicScore": 40, "candidateAdmissionStage": "normal"},
            {"tradeId": "b", "eventForensicScore": 90, "candidateAdmissionStage": "pre_admitted"},
        ]

        result = compare_candidate_output_contract(before, after)

        self.assertFalse(result["passed"])
        self.assertIn("eventForensicScore_changed_at_0", result["violations"])
        self.assertIn("candidateAdmissionStage_changed_at_1", result["violations"])
        self.assertIn("rank_order_changed", result["violations"])

    def test_timing_summary_calculates_per_row_and_per_wallet_costs(self) -> None:
        payload = summarize_timing_costs(
            {"score_candidates_seconds": 50, "prefetch_wallet_context_seconds": 25, "total_seconds": 100},
            candidate_rows=1000,
            candidate_wallets=250,
            market_count=5,
        )

        self.assertEqual(payload["dominantStage"], "score_candidates_seconds")
        self.assertEqual(payload["scoreSecondsPerCandidateRow"], 0.05)
        self.assertEqual(payload["prefetchSecondsPerCandidateWallet"], 0.1)
        self.assertEqual(payload["candidateRowsPerWallet"], 4.0)

    def test_wallet_context_reuse_metadata_is_additive_and_run_local(self) -> None:
        metadata = build_wallet_context_reuse_metadata(
            context_pool_trade_rows=120,
            candidate_rows=100,
            requested_wallet_references=120,
            unique_requested_wallets=30,
            wallet_context_count=30,
            prestarted_future_count=10,
            wallet_context_cache_hits=120,
            scoped_history_cache_hits=90,
            scoped_history_cache_misses=30,
            wallet_history_metrics_cache_hits=90,
            wallet_history_metrics_cache_misses=30,
            domain_profile_cache_hits=70,
            domain_profile_cache_misses=30,
            prefetch_seconds=15,
            prepare_seconds=3,
            score_seconds=20,
        )

        self.assertTrue(metadata["enabled"])
        self.assertTrue(metadata["runLocalOnly"])
        self.assertFalse(metadata["persistentCacheEnabled"])
        self.assertTrue(metadata["walletFetchBoundaryPreserved"])
        self.assertEqual(metadata["repeatedWalletContextOpportunities"], 90)
        self.assertEqual(metadata["effectiveScopedHistoryReuseRatio"], 0.75)
        self.assertEqual(metadata["prefetchSecondsPerWalletContext"], 0.5)
        self.assertTrue(metadata["scoreFormulaPreserved"])

    def test_scorer_context_profile_metadata_ranks_buckets_without_behavior_change(self) -> None:
        metadata = build_scorer_context_profile_metadata(
            candidate_rows=100,
            scored_case_count=98,
            skipped_case_count=2,
            bucket_seconds={
                "score_trade_call": 20.0,
                "wallet_domain_profile_annotation": 2.5,
                "funding_context_lookup": 0.5,
            },
            score_loop_seconds=25.0,
            wallet_context_reuse={
                "repeatedWalletContextOpportunities": 70,
                "effectiveScopedHistoryReuseRatio": 0.7,
                "effectiveDomainProfileReuseRatio": 0.65,
                "walletFetchBoundaryPreserved": True,
            },
        )

        self.assertTrue(metadata["enabled"])
        self.assertTrue(metadata["additiveMetadataOnly"])
        self.assertEqual(metadata["topBuckets"][0]["bucket"], "score_trade_call")
        self.assertEqual(metadata["topBuckets"][0]["shareOfScoreLoop"], 0.8)
        self.assertEqual(metadata["topBuckets"][0]["secondsPerCandidate"], 0.2)
        self.assertTrue(metadata["candidateAdmissionPreserved"])
        self.assertTrue(metadata["scoreFormulaPreserved"])
        self.assertTrue(metadata["walletContextReuseSummary"]["walletFetchBoundaryPreserved"])

    def test_score_trade_prepared_context_metadata_preserves_score_call_contract(self) -> None:
        metadata = build_score_trade_prepared_context_metadata(
            candidate_rows=100,
            prepared_context_rows=100,
            score_call_count=100,
            fallback_context_rows=0,
        )

        self.assertTrue(metadata["enabled"])
        self.assertEqual(metadata["preparedContextCoverageRatio"], 1.0)
        self.assertEqual(metadata["avoidedRepeatedContextBuilds"], 100)
        self.assertTrue(metadata["scoreCallCountUnchanged"])
        self.assertIn("same_outcome_market_trades", metadata["cacheScopes"])
        self.assertTrue(metadata["candidateAdmissionPreserved"])
        self.assertTrue(metadata["scoreFormulaPreserved"])

    def test_wallet_domain_profile_cache_preserves_raw_metrics(self) -> None:
        market = _market("cond-politics", question="Will policy pass?")
        case_a = _flagged_case(
            _trade(
                trade_id="candidate-a",
                condition_id="cond-politics",
                title="Will policy pass?",
                event_slug="policy-event",
            ),
            market,
        )
        case_b = _flagged_case(
            _trade(
                trade_id="candidate-b",
                condition_id="cond-politics",
                title="Will policy pass?",
                event_slug="policy-event",
            ),
            market,
        )
        history = [
            case_a.trade,
            _trade(
                trade_id="sports-history",
                condition_id="cond-sports",
                title="NBA Finals winner",
                event_slug="nba-finals",
            ),
        ]
        baseline = _flagged_case(case_a.trade, market)
        _annotate_wallet_domain_diversity(
            baseline,
            wallet_history_trades=history,
            focus_markets={market.condition_id: market},
        )

        cache: dict[str, dict[str, int]] = {}
        profile = {"cache_hits": 0, "cache_misses": 0}
        _annotate_wallet_domain_diversity(
            case_a,
            wallet_history_trades=history,
            focus_markets={market.condition_id: market},
            domain_counts_cache=cache,
            profile=profile,
        )
        _annotate_wallet_domain_diversity(
            case_b,
            wallet_history_trades=history,
            focus_markets={market.condition_id: market},
            domain_counts_cache=cache,
            profile=profile,
        )

        self.assertEqual(case_a.raw_metrics, baseline.raw_metrics)
        self.assertEqual(case_b.raw_metrics, baseline.raw_metrics)
        self.assertEqual(profile["cache_misses"], 1)
        self.assertEqual(profile["cache_hits"], 1)

    def test_bottleneck_decomposition_accepts_high_density_rfc_evidence(self) -> None:
        subset_summary = {
            "summary": {
                "gateDecision": "subset_measurement_blocked_scope",
                "eventSlug": "large-event",
                "analysisMarketCount": 6,
                "liveResolvedMarketCount": 15,
                "candidateRows": 15353,
                "candidateWalletCount": 3239,
                "rawTradeRows": 31919,
                "truncatedMarketCount": 6,
                "totalSeconds": 663.47,
                "runtimeBoundViolations": ["candidate_wallet_count_exceeds_per_market_bound"],
            },
            "reportSummary": {
                "timings": {
                    "score_candidates_seconds": 388.2,
                    "prefetch_wallet_context_seconds": 236.57,
                    "total_seconds": 663.47,
                }
            },
        }
        report = {
            "markets": [
                {"marketSlug": "a", "conditionId": "0xa", "tradeCount": 100, "candidateTradeCount": 80},
                {"marketSlug": "b", "conditionId": "0xb", "tradeCount": 50, "candidateTradeCount": 20},
            ]
        }

        payload = build_bottleneck_decomposition(
            subset_summary=subset_summary,
            aggregate_payload={"summary": {"medianTotalSeconds": 20.54}},
            report_payload=report,
        )

        self.assertEqual(payload["evidenceGate"], "high_density_subset_evidence_accepted_for_rfc")
        self.assertFalse(payload["wholeEventCompletenessClaim"])
        self.assertTrue(payload["classification"]["scoringLoopDominant"])
        self.assertTrue(payload["patchSignals"]["scorerInputContextMemoization"])

    def test_decomposition_cli_is_offline_and_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = root / "summary.json"
            aggregate = root / "aggregate.json"
            output = root / "out.json"
            summary.write_text(
                json.dumps(
                    {
                        "summary": {
                            "gateDecision": "subset_measurement_blocked_scope",
                            "eventSlug": "large-event",
                            "analysisMarketCount": 2,
                            "candidateRows": 100,
                            "candidateWalletCount": 40,
                            "rawTradeRows": 500,
                            "totalSeconds": 20,
                        },
                        "reportSummary": {
                            "timings": {
                                "score_candidates_seconds": 10,
                                "prefetch_wallet_context_seconds": 5,
                                "total_seconds": 20,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            aggregate.write_text(json.dumps({"summary": {"medianTotalSeconds": 10}}), encoding="utf-8")

            self.assertEqual(
                main(["--summary", str(summary), "--aggregate", str(aggregate), "--output", str(output), "--quiet"]),
                0,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(payload["networkUsed"])
        self.assertFalse(payload["runtimeBehaviorChanged"])
        self.assertEqual(payload["evidenceGate"], "high_density_subset_evidence_accepted_for_rfc")


def _market(condition_id: str, *, question: str) -> Market:
    return Market(
        market_id=condition_id,
        condition_id=condition_id,
        slug=f"{condition_id}-slug",
        question=question,
        category="Politics",
        end_date=None,
        liquidity=Decimal("0"),
        volume=Decimal("0"),
        outcomes=["Yes", "No"],
        token_ids=["yes", "no"],
        tags=[],
    )


def _trade(
    *,
    trade_id: str,
    condition_id: str,
    title: str,
    event_slug: str,
) -> Trade:
    return Trade(
        trade_id=trade_id,
        condition_id=condition_id,
        asset_id=f"{condition_id}-asset",
        wallet="0xwallet",
        side="BUY",
        outcome="Yes",
        price=Decimal("0.50"),
        size=Decimal("10"),
        timestamp=datetime(2026, 5, 25, tzinfo=UTC),
        title=title,
        slug=f"{trade_id}-slug",
        event_slug=event_slug,
    )


def _flagged_case(trade: Trade, market: Market) -> FlaggedCase:
    return FlaggedCase(
        severity="Medium",
        suspicion_score=50,
        confidence_score=50,
        review_priority="normal",
        verdict="review",
        trade_count_window=1,
        window_start="",
        window_end="",
        trade=trade,
        market=market,
        wallet_inspection=WalletInspection(
            address=trade.wallet,
            polygon_nonce=None,
            traded_market_count=None,
            recent_trade_count=2,
            unique_market_count=2,
            focus_market_count=1,
            first_trade_at=None,
            last_trade_at=None,
        ),
        subscores={},
        flags=[],
        explanation=[],
        reasons_against=[],
        raw_metrics={"trade_domain": "Politics"},
    )


if __name__ == "__main__":
    unittest.main()
