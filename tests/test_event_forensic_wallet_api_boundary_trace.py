from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_forensic_wallet_api_boundary_trace_analysis import (
    build_wallet_api_boundary_trace_analysis,
    main,
)


class EventForensicWalletApiBoundaryTraceTests(unittest.TestCase):
    def test_no_safe_patch_gate_when_wallet_requests_already_deduped(self) -> None:
        payload = build_wallet_api_boundary_trace_analysis(
            current_payload=_measurement(duplicate_requests=0, truncated=6),
            profile_payload=_measurement(total=645.17, score=339.83, prefetch=266.2),
            prepared_payload=_measurement(total=678.99, score=318.0, prefetch=303.42),
            static_equivalence_payload=_static_equivalence(),
        )

        self.assertEqual(payload["gateDecision"], "api_boundary_no_safe_patch")
        self.assertEqual(payload["paginationGateDecision"], "pagination_operator_plan_required")
        self.assertFalse(payload["optimizationDecision"]["runtimePatchImplemented"])
        self.assertTrue(payload["optimizationDecision"]["batchingRequiresSeparateApproval"])
        self.assertFalse(payload["wholeEventCompletenessClaim"])

    def test_regression_gate_if_static_equivalence_fails(self) -> None:
        static = _static_equivalence()
        static["contractComparisonAgainstSelf"]["passed"] = False

        payload = build_wallet_api_boundary_trace_analysis(
            current_payload=_measurement(duplicate_requests=0, truncated=0),
            static_equivalence_payload=static,
        )

        self.assertEqual(payload["gateDecision"], "regression_stop")

    def test_patch_partial_gate_when_exact_duplicates_exist(self) -> None:
        payload = build_wallet_api_boundary_trace_analysis(
            current_payload=_measurement(duplicate_requests=3, truncated=0),
            static_equivalence_payload=_static_equivalence(),
        )

        self.assertEqual(payload["gateDecision"], "api_boundary_patch_partial")
        self.assertTrue(payload["duplicateOpportunitySummary"]["safeExactDedupeOpportunity"])
        self.assertEqual(payload["paginationGateDecision"], "pagination_live_measurement_clean")

    def test_cli_writes_stable_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "current.json"
            static = root / "static.json"
            output = root / "out.json"
            current.write_text(json.dumps(_measurement(duplicate_requests=0, truncated=2)), encoding="utf-8")
            static.write_text(json.dumps(_static_equivalence()), encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "--current",
                        str(current),
                        "--profile",
                        str(root / "missing-profile.json"),
                        "--prepared",
                        str(root / "missing-prepared.json"),
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

        self.assertEqual(payload["reportType"], "event_forensic_wallet_api_boundary_trace")
        self.assertEqual(payload["gateDecision"], "api_boundary_no_safe_patch")
        self.assertFalse(payload["forbiddenScopePreserved"]["paginationSemanticsChanged"])


def _measurement(
    *,
    duplicate_requests: int = 0,
    truncated: int = 0,
    total: float = 700.0,
    score: float = 320.0,
    prefetch: float = 300.0,
) -> dict[str, object]:
    return {
        "networkUsed": True,
        "summary": {
            "gateDecision": "subset_measurement_complete",
            "eventSlug": "event",
            "subsetOnly": True,
            "analysisMarketCount": 6,
            "liveResolvedMarketCount": 15,
            "rawTradeRows": 32000,
            "candidateRows": 15354,
            "candidateWalletCount": 3292,
            "truncatedMarketCount": truncated,
            "dominantBottleneck": "score_candidates_seconds",
            "totalSeconds": total,
        },
        "reportSummary": {
            "timings": {
                "score_candidates_seconds": score,
                "prefetch_wallet_context_seconds": prefetch,
                "total_seconds": total,
            }
        },
        "performance": {
            "wallet_api_boundary_trace": {
                "enabled": True,
                "duplicateExactWalletContextRequests": duplicate_requests,
                "repeatedWalletReferencesAlreadyDeduped": 12000,
                "safeExactDedupeOpportunity": duplicate_requests > 0,
                "safePatchRecommendation": "fixture",
                "batchingImplemented": False,
                "batchingApproved": False,
            }
        },
    }


def _static_equivalence() -> dict[str, object]:
    return {
        "candidateCount": 15353,
        "exportRowCount": 15353,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "contractComparisonAgainstSelf": {"passed": True, "violations": []},
    }


if __name__ == "__main__":
    unittest.main()
