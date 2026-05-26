import json
import tempfile
import unittest
from pathlib import Path

from tools.event_forensic_scorer_context_profile_analysis import (
    build_scorer_context_profile_analysis,
    write_json,
)


class EventForensicScorerContextProfileAnalysisTests(unittest.TestCase):
    def test_profile_analysis_keeps_wallet_cache_when_profile_recovers_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile_payload = _measurement_payload(
                tmp_path,
                total=645.0,
                score=340.0,
                prefetch=266.0,
                candidates=15354,
                wallets=3287,
                profile=True,
            )
            analysis = build_scorer_context_profile_analysis(
                pre_memoization_payload=_measurement_payload(tmp_path, total=663.0, score=388.0, prefetch=236.0),
                post_scorer_payload=_measurement_payload(tmp_path, total=644.0, score=354.0, prefetch=250.0),
                post_wallet_payload=_measurement_payload(tmp_path, total=704.0, score=338.0, prefetch=317.0),
                post_profile_payload=profile_payload,
                static_equivalence_payload=_static_equivalence_payload(),
            )

        self.assertEqual(analysis["gateDecision"], "wallet_cache_keep_confirmed")
        self.assertEqual(analysis["walletCacheRetentionDecision"], "keep_as_is_pending_next_scorer_context_work")
        self.assertFalse(analysis["runtimeBehaviorChanged"])
        self.assertTrue(analysis["staticEquivalence"]["passed"])
        self.assertEqual(analysis["profilerTopBottlenecks"][0]["bucket"], "score_trade_call")

    def test_static_equivalence_failure_stops_before_retention_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _measurement_payload(tmp_path, total=100.0, score=50.0, prefetch=25.0, profile=True)
            analysis = build_scorer_context_profile_analysis(
                pre_memoization_payload=payload,
                post_scorer_payload=payload,
                post_wallet_payload=payload,
                post_profile_payload=payload,
                static_equivalence_payload={
                    **_static_equivalence_payload(),
                    "contractComparisonAgainstSelf": {"passed": False, "violations": ["score drift"]},
                },
            )

        self.assertEqual(analysis["gateDecision"], "regression_stop")

    def test_write_json_outputs_stable_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "analysis.json"
            write_json({"gateDecision": "wallet_cache_keep_confirmed"}, target)
            payload = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(payload["gateDecision"], "wallet_cache_keep_confirmed")


def _measurement_payload(
    tmp_path: Path,
    *,
    total: float,
    score: float,
    prefetch: float,
    candidates: int = 1000,
    wallets: int = 200,
    profile: bool = False,
) -> dict[str, object]:
    performance = {
        "trade_collection_raw_trade_rows": candidates * 2,
        "candidate_trade_count_visible": candidates,
        "candidate_wallet_count": wallets,
        "total_seconds": total,
        "score_candidates_seconds": score,
        "prefetch_wallet_context_seconds": prefetch,
        "prepare_candidate_context_seconds": 5.0,
    }
    if profile:
        performance["scorer_context_profile"] = {
            "enabled": True,
            "topBuckets": [
                {
                    "bucket": "score_trade_call",
                    "seconds": score - 5.0,
                    "shareOfScoreLoop": 0.95,
                    "secondsPerCandidate": round((score - 5.0) / candidates, 6),
                }
            ],
            "candidateAdmissionPreserved": True,
            "scoreFormulaPreserved": True,
            "reviewRoutingPreserved": True,
            "exportsPreserved": True,
        }
    analysis_path = tmp_path / f"event_analysis_{total}.json"
    analysis_path.write_text(json.dumps({"performance": performance}), encoding="utf-8")
    return {
        "networkUsed": True,
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "summary": {
            "eventSlug": "example-event",
            "subsetOnly": True,
            "analysisMarketCount": 6,
            "liveResolvedMarketCount": 15,
            "rawTradeRows": candidates * 2,
            "candidateRows": candidates,
            "candidateWalletCount": wallets,
            "truncatedMarketCount": 6,
            "totalSeconds": total,
            "dominantBottleneck": "score_candidates_seconds",
            "gateDecision": "subset_measurement_complete",
        },
        "liveResult": {
            "eventAnalysisJsonPath": str(analysis_path),
            "timings": {
                "total_seconds": total,
                "score_candidates_seconds": score,
                "prefetch_wallet_context_seconds": prefetch,
                "prepare_candidate_context_seconds": 5.0,
            },
        },
    }


def _static_equivalence_payload() -> dict[str, object]:
    return {
        "candidateCount": 100,
        "exportRowCount": 100,
        "candidateRowsSha256": "abc",
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "contractComparisonAgainstSelf": {"passed": True, "violations": []},
    }


if __name__ == "__main__":
    unittest.main()
