import json
import tempfile
import unittest
from pathlib import Path

from tools.event_forensic_scorer_context_optimization_analysis import (
    build_scorer_context_optimization_analysis,
    write_json,
)


class EventForensicScorerContextOptimizationAnalysisTests(unittest.TestCase):
    def test_gate_is_partial_when_score_improves_but_total_regresses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = _measurement(root, total=645.0, score=340.0, prefetch=266.0, profile=True)
            optimized = _measurement(root, total=679.0, score=318.0, prefetch=303.0, profile=True, prepared=True)
            payload = build_scorer_context_optimization_analysis(
                pre_memoization_payload=_measurement(root, total=663.0, score=388.0, prefetch=236.0),
                post_scorer_payload=_measurement(root, total=644.0, score=354.0, prefetch=250.0),
                post_wallet_payload=_measurement(root, total=704.0, score=338.0, prefetch=317.0),
                post_profile_payload=profile,
                optimized_payload=optimized,
                static_equivalence_payload=_static_equivalence(),
                input_audit_payload=_input_audit(),
            )

        self.assertEqual(payload["gateDecision"], "scorer_context_patch_partial")
        self.assertEqual(payload["preparedContext"]["preparedContextCoverageRatio"], 1.0)
        self.assertFalse(payload["runtimeBehaviorChanged"])
        self.assertTrue(payload["staticEquivalence"]["passed"])

    def test_equivalence_failure_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            measurement = _measurement(root, total=100.0, score=50.0, prefetch=25.0, profile=True)
            payload = build_scorer_context_optimization_analysis(
                pre_memoization_payload=measurement,
                post_scorer_payload=measurement,
                post_wallet_payload=measurement,
                post_profile_payload=measurement,
                optimized_payload=measurement,
                static_equivalence_payload={
                    **_static_equivalence(),
                    "contractComparisonAgainstSelf": {"passed": False, "violations": ["rank drift"]},
                },
                input_audit_payload=_input_audit(),
            )

        self.assertEqual(payload["gateDecision"], "regression_stop")

    def test_write_json_outputs_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "analysis.json"
            write_json({"gateDecision": "scorer_context_patch_partial"}, target)
            payload = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(payload["gateDecision"], "scorer_context_patch_partial")


def _measurement(
    root: Path,
    *,
    total: float,
    score: float,
    prefetch: float,
    profile: bool = False,
    prepared: bool = False,
) -> dict[str, object]:
    performance = {
        "trade_collection_raw_trade_rows": 2000,
        "candidate_trade_count_visible": 1000,
        "candidate_wallet_count": 200,
        "total_seconds": total,
        "score_candidates_seconds": score,
        "prefetch_wallet_context_seconds": prefetch,
        "prepare_candidate_context_seconds": 5.0,
    }
    if profile:
        performance["scorer_context_profile"] = {
            "topBuckets": [
                {
                    "bucket": "score_trade_call",
                    "seconds": score - 7.0,
                    "shareOfScoreLoop": 0.97,
                    "secondsPerCandidate": round((score - 7.0) / 1000, 6),
                }
            ]
        }
    if prepared:
        performance["score_trade_prepared_context"] = {
            "preparedContextRows": 1000,
            "scoreCallCount": 1000,
            "preparedContextCoverageRatio": 1.0,
        }
    path = root / f"event_analysis_{total}.json"
    path.write_text(json.dumps({"performance": performance}), encoding="utf-8")
    return {
        "networkUsed": True,
        "summary": {
            "eventSlug": "example-event",
            "subsetOnly": True,
            "analysisMarketCount": 6,
            "liveResolvedMarketCount": 15,
            "rawTradeRows": 2000,
            "candidateRows": 1000,
            "candidateWalletCount": 200,
            "truncatedMarketCount": 6,
            "totalSeconds": total,
            "dominantBottleneck": "score_candidates_seconds",
            "gateDecision": "subset_measurement_complete",
        },
        "liveResult": {
            "eventAnalysisJsonPath": str(path),
            "timings": {
                "total_seconds": total,
                "score_candidates_seconds": score,
                "prefetch_wallet_context_seconds": prefetch,
                "prepare_candidate_context_seconds": 5.0,
            },
        },
    }


def _static_equivalence() -> dict[str, object]:
    return {
        "candidateCount": 100,
        "exportRowCount": 100,
        "candidateRowsSha256": "abc",
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "contractComparisonAgainstSelf": {"passed": True, "violations": []},
    }


def _input_audit() -> dict[str, object]:
    return {
        "gateDecision": "score_call_input_reuse_context_fragments_only",
        "totalRows": 100,
        "duplicateEquivalentScoreCallsRare": True,
        "safeOptimizationRecommendation": "memoize_context_fragments_only",
    }


if __name__ == "__main__":
    unittest.main()
