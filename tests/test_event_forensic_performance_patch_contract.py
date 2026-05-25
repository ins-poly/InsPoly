from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.event_forensic_performance import (
    build_chunk_metadata,
    candidate_performance_cache_key,
    compare_candidate_output_contract,
    summarize_timing_costs,
)
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


if __name__ == "__main__":
    unittest.main()
