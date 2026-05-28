from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_forensic_post_patch_performance_analysis import (
    build_post_patch_analysis,
    main,
)


class EventForensicPostPatchPerformanceAnalysisTests(unittest.TestCase):
    def test_partial_gate_when_score_improves_but_scorer_remains_dominant(self) -> None:
        payload = build_post_patch_analysis(
            baseline_payload=_measurement_payload(
                total=663.47,
                score=388.2,
                prefetch=236.57,
                raw=31919,
                candidates=15353,
                wallets=3239,
                dominant="score_candidates_seconds",
            ),
            post_payload=_measurement_payload(
                total=644.47,
                score=353.58,
                prefetch=249.8,
                raw=31929,
                candidates=15354,
                wallets=3241,
                dominant="score_candidates_seconds",
                memoization=True,
            ),
            static_equivalence={"gate": "static_equivalence_passed", "candidateCount": 15353},
            live_output_delta={"candidateCountDelta": 1, "weakHistoryDemotionChangeCountOnCommonIds": 0},
        )

        self.assertEqual(payload["gateDecision"], "patch_partial_needs_next_optimization")
        self.assertGreater(payload["comparison"]["normalizedScoreImprovementPercent"], 5)
        self.assertTrue(payload["memoization"]["enabled"])
        self.assertFalse(payload["wholeEventCompletenessClaim"])

    def test_regression_gate_when_static_equivalence_fails(self) -> None:
        payload = build_post_patch_analysis(
            baseline_payload=_measurement_payload(total=100, score=50, candidates=100),
            post_payload=_measurement_payload(total=90, score=40, candidates=100),
            static_equivalence={"gate": "static_equivalence_failed"},
        )

        self.assertEqual(payload["gateDecision"], "regression_stop")

    def test_measurement_blocked_gate_when_post_measurement_did_not_complete(self) -> None:
        post = _measurement_payload(total=0, score=0, candidates=0)
        post["summary"]["gateDecision"] = "subset_measurement_blocked_scope"

        payload = build_post_patch_analysis(
            baseline_payload=_measurement_payload(total=100, score=50, candidates=100),
            post_payload=post,
            static_equivalence={"gate": "static_equivalence_passed"},
        )

        self.assertEqual(payload["gateDecision"], "measurement_blocked")

    def test_control_measurement_comparison_is_included(self) -> None:
        payload = build_post_patch_analysis(
            baseline_payload=_measurement_payload(total=100, score=50, candidates=100),
            post_payload=_measurement_payload(total=90, score=40, candidates=100, memoization=True),
            static_equivalence={"gate": "static_equivalence_passed"},
            control_measurements=[
                (
                    _measurement_payload(total=20.54, score=1.0, candidates=144, event="control"),
                    _measurement_payload(total=17.22, score=1.0, candidates=144, event="control"),
                )
            ],
        )

        self.assertEqual(payload["controlMeasurements"][0]["eventSlug"], "control")
        self.assertGreater(payload["controlMeasurements"][0]["totalSecondsImprovementPercent"], 0)

    def test_cli_writes_output_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline.json"
            post = root / "post.json"
            static = root / "static.json"
            output = root / "out.json"
            baseline.write_text(json.dumps(_measurement_payload(total=100, score=50, candidates=100)), encoding="utf-8")
            post.write_text(json.dumps(_measurement_payload(total=90, score=40, candidates=100, memoization=True)), encoding="utf-8")
            static.write_text(json.dumps({"gate": "static_equivalence_passed"}), encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "--baseline",
                        str(baseline),
                        "--post",
                        str(post),
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


def _measurement_payload(
    *,
    total: float,
    score: float,
    prefetch: float = 0.0,
    raw: int = 1000,
    candidates: int = 100,
    wallets: int = 50,
    dominant: str = "score_candidates_seconds",
    event: str = "event",
    memoization: bool = False,
) -> dict[str, object]:
    return {
        "networkUsed": True,
        "summary": {
            "gateDecision": "subset_measurement_complete",
            "eventSlug": event,
            "subsetOnly": True,
            "selectedMarketCount": 6,
            "analysisMarketCount": 6,
            "liveResolvedMarketCount": 15,
            "rawTradeRows": raw,
            "candidateRows": candidates,
            "candidateWalletCount": wallets,
            "truncatedMarketCount": 6,
            "dominantBottleneck": dominant,
            "totalSeconds": total,
            "runtimeBoundViolations": [],
        },
        "reportSummary": {
            "timings": {
                "score_candidates_seconds": score,
                "prefetch_wallet_context_seconds": prefetch,
                "total_seconds": total,
            },
            "performance": {
                "score_input_memoization": {
                    "enabled": True,
                    "candidateRows": candidates,
                    "uniqueWallets": wallets,
                    "uniqueMarkets": 6,
                    "uniqueDomains": 1,
                    "repeatedWalletCandidateOpportunities": max(0, candidates - wallets),
                    "cacheScopes": ["wallet_window_trades", "funding_resolver_health"],
                }
            }
            if memoization
            else {},
        },
        "liveResult": {
            "eventAnalysisJsonPath": "",
        },
        "postMemoization": memoization,
    }


if __name__ == "__main__":
    unittest.main()
