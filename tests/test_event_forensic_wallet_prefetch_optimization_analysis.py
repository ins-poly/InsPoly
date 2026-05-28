from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_forensic_wallet_prefetch_optimization_analysis import (
    build_wallet_prefetch_optimization_analysis,
    main,
)


class EventForensicWalletPrefetchOptimizationAnalysisTests(unittest.TestCase):
    def test_partial_gate_when_score_improves_but_prefetch_does_not(self) -> None:
        payload = build_wallet_prefetch_optimization_analysis(
            pre_memoization_payload=_measurement(total=663.47, score=388.2, prefetch=236.57),
            post_scorer_payload=_measurement(total=644.47, score=353.58, prefetch=249.8),
            post_wallet_payload=_measurement(
                total=703.56,
                score=338.0,
                prefetch=316.64,
                wallet_reuse=True,
            ),
            static_equivalence_payload=_static_equivalence(),
        )

        self.assertEqual(payload["gateDecision"], "wallet_prefetch_patch_partial")
        self.assertGreater(payload["comparisonPostScorerToPostWallet"]["normalizedScoreImprovementPercent"], 3)
        self.assertLess(payload["comparisonPostScorerToPostWallet"]["normalizedPrefetchImprovementPercent"], 0)
        self.assertFalse(payload["wholeEventCompletenessClaim"])

    def test_regression_gate_when_static_equivalence_fails(self) -> None:
        static = _static_equivalence()
        static["contractComparisonAgainstSelf"]["passed"] = False

        payload = build_wallet_prefetch_optimization_analysis(
            pre_memoization_payload=_measurement(total=100, score=50, prefetch=40),
            post_scorer_payload=_measurement(total=90, score=40, prefetch=45),
            post_wallet_payload=_measurement(total=80, score=35, prefetch=35),
            static_equivalence_payload=static,
        )

        self.assertEqual(payload["gateDecision"], "regression_stop")

    def test_candidate_delta_counts_live_source_drift_without_claiming_regression(self) -> None:
        payload = build_wallet_prefetch_optimization_analysis(
            pre_memoization_payload=_measurement(total=100, score=50, prefetch=40),
            post_scorer_payload=_measurement(total=90, score=40, prefetch=45),
            post_wallet_payload=_measurement(total=85, score=35, prefetch=44),
            static_equivalence_payload=_static_equivalence(),
            previous_candidate_rows=[
                _candidate("a", score=10, bucket="primary"),
                _candidate("b", score=20, bucket="secondary"),
            ],
            post_candidate_rows=[
                _candidate("a", score=11, bucket="primary"),
                _candidate("c", score=30, bucket="secondary"),
            ],
        )

        delta = payload["liveOutputDelta"]
        self.assertTrue(delta["available"])
        self.assertEqual(delta["commonCandidateCount"], 1)
        self.assertEqual(delta["addedCandidateCount"], 1)
        self.assertEqual(delta["removedCandidateCount"], 1)
        self.assertEqual(delta["scoreChangeCountOnCommonIds"], 1)

    def test_cli_writes_output_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pre = root / "pre.json"
            scorer = root / "scorer.json"
            wallet = root / "wallet.json"
            static = root / "static.json"
            output = root / "out.json"
            pre.write_text(json.dumps(_measurement(total=100, score=50, prefetch=40)), encoding="utf-8")
            scorer.write_text(json.dumps(_measurement(total=90, score=40, prefetch=45)), encoding="utf-8")
            wallet.write_text(json.dumps(_measurement(total=85, score=35, prefetch=44)), encoding="utf-8")
            static.write_text(json.dumps(_static_equivalence()), encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "--pre-memoization",
                        str(pre),
                        "--post-scorer",
                        str(scorer),
                        "--post-wallet",
                        str(wallet),
                        "--static-equivalence",
                        str(static),
                        "--output",
                        str(output),
                        "--quiet",
                    ]
                ),
                0,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(payload["runtimeBehaviorChanged"])
        self.assertFalse(payload["forbiddenScopePreserved"]["phase3Runtime"])


def _measurement(
    *,
    total: float,
    score: float,
    prefetch: float,
    raw: int = 31929,
    candidates: int = 15354,
    wallets: int = 3241,
    wallet_reuse: bool = False,
) -> dict[str, object]:
    performance = {}
    if wallet_reuse:
        performance["wallet_context_reuse"] = {
            "enabled": True,
            "repeatedWalletContextOpportunities": candidates - wallets,
            "walletFetchBoundaryPreserved": True,
        }
    return {
        "networkUsed": True,
        "summary": {
            "gateDecision": "subset_measurement_complete",
            "eventSlug": "event",
            "subsetOnly": True,
            "analysisMarketCount": 6,
            "liveResolvedMarketCount": 15,
            "rawTradeRows": raw,
            "candidateRows": candidates,
            "candidateWalletCount": wallets,
            "truncatedMarketCount": 6,
            "dominantBottleneck": "score_candidates_seconds",
            "totalSeconds": total,
            "runtimeBoundViolations": [],
        },
        "reportSummary": {
            "timings": {
                "score_candidates_seconds": score,
                "prefetch_wallet_context_seconds": prefetch,
                "total_seconds": total,
            }
        },
        "liveResult": {"eventAnalysisJsonPath": ""},
        "performance": performance,
    }


def _static_equivalence() -> dict[str, object]:
    return {
        "candidateCount": 15353,
        "exportRowCount": 15353,
        "candidateRowsSha256": "abc",
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "contractComparisonAgainstSelf": {"passed": True, "violations": []},
    }


def _candidate(candidate_id: str, *, score: int, bucket: str) -> dict[str, object]:
    return {
        "tradeId": candidate_id,
        "eventForensicScore": score,
        "reviewBucketAfterPolicy": bucket,
        "weakHistoryNearCertaintyReviewDemotion": "No",
    }


if __name__ == "__main__":
    unittest.main()
