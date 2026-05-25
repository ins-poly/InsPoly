from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tools.event_forensic_weak_history_live_rpc_validation import (
    ValidationBounds,
    analyze_report_result,
    build_summary,
    runtime_env_status,
    select_targets,
    write_json,
)


class EventForensicWeakHistoryLiveRpcValidationTests(unittest.TestCase):
    def test_runtime_env_status_never_exposes_secret_values(self) -> None:
        old_value = os.environ.get("POLYGON_RPC_URL")
        os.environ["POLYGON_RPC_URL"] = "https://secret.example/rpc"
        try:
            status = runtime_env_status(Path.cwd())
        finally:
            if old_value is None:
                os.environ.pop("POLYGON_RPC_URL", None)
            else:
                os.environ["POLYGON_RPC_URL"] = old_value

        rendered = str(status)
        self.assertTrue(status["configuredEnvKeys"]["POLYGON_RPC_URL"])
        self.assertTrue(status["rpcConfigured"])
        self.assertTrue(status["secretValuesPrinted"] is False)
        self.assertNotIn("secret.example", rendered)

    def test_select_targets_enforces_candidate_wallet_bound(self) -> None:
        candidates = [
            {
                "artifactPath": "event_forensic_outputs/example/event_analysis.json",
                "eventSlug": "event-a",
                "conditionId": "condition-a",
                "marketUrl": "https://polymarket.com/event/event-a",
                "market": "Example",
                "sourceRawTradeCount": 20,
                "sourceCandidateTradeCount": 151,
                "tradeKey": "t1",
                "wallet": "0x1",
            }
        ]

        selected, excluded = select_targets(
            candidates,
            bounds=ValidationBounds(max_candidate_wallets_per_market=150),
        )

        self.assertEqual(selected, [])
        self.assertEqual(excluded[0]["reason"], "max_candidate_wallets_per_market_bound")

    def test_analyze_report_result_detects_high_rank_weak_near_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "event_analysis.json"
            write_json(
                report_path,
                {
                    "summary": {"raw_trade_count": 10, "candidate_trade_count": 2},
                    "display_trades": [
                        {
                            "id": "trade-1",
                            "wallet": "0xweak",
                            "orderSide": "BUY",
                            "side": "No",
                            "price": 0.96,
                            "laterWon": True,
                            "winnerRank": 4,
                            "eventForensicFlags": ["weak_wallet_track_record", "near_certainty_winner"],
                            "eventForensicReducers": [
                                "The wallet's broader losing record blocks a primary interpretation.",
                                "The market price was already near certainty at entry.",
                            ],
                            "economicSideProbability": 0.96,
                            "clusterDirection": "long_no",
                        }
                    ],
                    "suspicious_trades": [],
                },
            )

            summary = analyze_report_result(
                {"status": "completed", "label": "target", "eventAnalysisJsonPath": str(report_path)},
                bounds=ValidationBounds(),
            )

        self.assertEqual(summary["weakHistoryNearCertainLaterWinCases"][0]["displayRank"], 1)
        self.assertEqual(summary["phase2EconomicProbabilityMismatches"], 0)
        self.assertEqual(summary["phase4ClusterDirectionMismatches"], 0)

    def test_build_summary_selects_model_rfc_gate_for_high_rank_reducer_present_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "event_analysis.json"
            write_json(
                report_path,
                {
                    "summary": {"raw_trade_count": 10, "candidate_trade_count": 2},
                    "display_trades": [
                        {
                            "id": "trade-1",
                            "wallet": "0xweak",
                            "orderSide": "BUY",
                            "side": "No",
                            "price": 0.96,
                            "laterWon": True,
                            "winnerRank": 4,
                            "eventForensicFlags": ["weak_wallet_track_record", "near_certainty_winner"],
                            "eventForensicReducers": ["near certainty", "weak economic history"],
                            "economicSideProbability": 0.96,
                            "clusterDirection": "long_no",
                        }
                    ],
                },
            )
            summary = build_summary(
                output_dir=Path(tmp),
                bounds=ValidationBounds(),
                env_status={"secretValuesPrinted": False},
                selected_targets=[{"eventSlug": "event-a", "marketKey": "condition-a"}],
                excluded_targets=[],
                live_results=[
                    {
                        "status": "completed",
                        "label": "target",
                        "eventAnalysisJsonPath": str(report_path),
                    }
                ],
            )

        self.assertEqual(summary["summary"]["gateDecision"], "weak_history_live_validation_needs_model_rfc")


if __name__ == "__main__":
    unittest.main()
