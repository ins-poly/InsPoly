import json
import tempfile
import unittest
from pathlib import Path

from tools.event_forensic_score_call_input_audit import (
    build_score_call_input_audit,
    load_candidate_rows,
    main,
)


class EventForensicScoreCallInputAuditTests(unittest.TestCase):
    def test_exact_duplicates_rare_recommends_context_fragments(self) -> None:
        rows = [
            _row("a", wallet="0x1", market="m1", timestamp="2026-05-26T00:00:00Z", price=0.2),
            _row("b", wallet="0x1", market="m1", timestamp="2026-05-26T00:01:00Z", price=0.2),
            _row("c", wallet="0x2", market="m1", timestamp="2026-05-26T00:02:00Z", price=0.4),
        ]

        payload = build_score_call_input_audit(rows)

        self.assertEqual(payload["gateDecision"], "score_call_input_reuse_context_fragments_only")
        self.assertTrue(payload["duplicateEquivalentScoreCallsRare"])
        self.assertEqual(payload["exactInputSignature"]["uniqueSignatures"], 3)
        self.assertGreater(payload["walletMarketTokenSignature"]["rowsInRepeatedSignatureGroups"], 0)
        self.assertFalse(payload["networkUsed"])
        self.assertFalse(payload["runtimeBehaviorChanged"])

    def test_loader_accepts_candidate_trades_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.json"
            path.write_text(json.dumps({"candidateTrades": [_row("a")]}), encoding="utf-8")

            rows = load_candidate_rows(path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tradeId"], "a")

    def test_cli_writes_stable_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "rows.json"
            output_path = root / "out.json"
            input_path.write_text(
                json.dumps({"rows": [_row("a"), _row("b", timestamp="2026-05-26T00:01:00Z")]}),
                encoding="utf-8",
            )

            self.assertEqual(main(["--input", str(input_path), "--output", str(output_path), "--quiet"]), 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["totalRows"], 2)
        self.assertEqual(payload["safeOptimizationRecommendation"], "memoize_context_fragments_only")


def _row(
    trade_id: str,
    *,
    wallet: str = "0xwallet",
    market: str = "market-a",
    timestamp: str = "2026-05-26T00:00:00Z",
    price: float = 0.2,
) -> dict[str, object]:
    return {
        "tradeId": trade_id,
        "wallet": wallet,
        "conditionId": market,
        "marketSlug": market,
        "timestamp": timestamp,
        "rawOrderSide": "BUY",
        "rawTokenOutcome": "YES",
        "rawTokenPrice": price,
        "notionalUsd": 100,
        "candidateAdmissionStage": "normal_candidate",
        "analysisScope": "event",
        "selectedConditionId": market,
        "economicSide": "YES",
        "economicSideProbability": price,
        "modelEconomicDirection": "long_yes",
        "clusterDirection": "long_yes",
        "fundingEvidenceGrade": "none",
        "hardEvidenceReviewTier": "",
        "strongRiskGateType": "",
        "weakHistoryNearCertaintyReviewDemotion": "No",
        "parentEventSlug": "event-a",
        "selectedMarketSlug": market,
    }


if __name__ == "__main__":
    unittest.main()
