from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.event_forensic_performance import (
    build_score_loop_memoization_metadata,
    candidate_performance_cache_key,
    compare_candidate_output_contract,
)
from tools.event_forensic_behavior_snapshot import (
    build_behavior_snapshot,
    extract_candidate_contract_rows,
    main,
)


class EventForensicPerformanceEquivalenceTests(unittest.TestCase):
    def test_snapshot_preserves_candidate_ids_scores_rank_buckets_and_export_count(self) -> None:
        rows = [
            _candidate_row("trade-a", score=42, bucket="primary_event_forensic"),
            _candidate_row("trade-b", score=55, bucket="review_required_secondary"),
        ]

        snapshot = build_behavior_snapshot(rows, source_path="fixture.json", include_rows=True)

        self.assertEqual(snapshot["candidateIds"], ["trade-a", "trade-b"])
        self.assertEqual(snapshot["rankOrderIds"], ["trade-b", "trade-a"])
        self.assertEqual(snapshot["scoreByCandidateId"]["trade-a"], 42)
        self.assertEqual(snapshot["reviewBucketByCandidateId"]["trade-b"], "review_required_secondary")
        self.assertEqual(snapshot["exportRowCount"], 2)
        self.assertTrue(snapshot["contractComparisonAgainstSelf"]["passed"])
        self.assertFalse(snapshot["networkUsed"])

    def test_candidate_output_contract_proves_equivalent_rows(self) -> None:
        rows = extract_candidate_contract_rows(
            [
                _candidate_row("trade-a", score=60, bucket="primary_event_forensic"),
                _candidate_row("trade-b", score=39, bucket="review_required_secondary"),
            ]
        )

        result = compare_candidate_output_contract(rows, [dict(row) for row in rows])

        self.assertTrue(result["passed"])
        self.assertEqual(result["candidateCountBefore"], 2)
        self.assertEqual(result["candidateCountAfter"], 2)

    def test_candidate_output_contract_catches_rank_score_bucket_change(self) -> None:
        before = extract_candidate_contract_rows(
            [
                _candidate_row("trade-a", score=60, bucket="primary_event_forensic"),
                _candidate_row("trade-b", score=30, bucket="review_required_secondary"),
            ]
        )
        after = [dict(row) for row in before]
        after[0]["eventForensicScore"] = 20
        after[1]["reviewBucket"] = "primary_event_forensic"

        result = compare_candidate_output_contract(before, after)

        self.assertFalse(result["passed"])
        self.assertIn("eventForensicScore_changed_at_0", result["violations"])
        self.assertIn("reviewBucket_changed_at_1", result["violations"])
        self.assertIn("rank_order_changed", result["violations"])

    def test_weak_history_review_demotion_metadata_is_preserved(self) -> None:
        row = _candidate_row(
            "weak-history",
            score=82,
            bucket="review_required_weak_history_near_certainty",
            demoted="Yes",
        )

        snapshot = build_behavior_snapshot([row], source_path="fixture.json", include_rows=True)

        candidate = snapshot["candidateRows"][0]
        self.assertEqual(candidate["weakHistoryNearCertaintyReviewDemotion"], "Yes")
        self.assertEqual(candidate["reviewBucket"], "review_required_weak_history_near_certainty")

    def test_score_loop_memoization_metadata_is_additive_and_does_not_hide_rows(self) -> None:
        metadata = build_score_loop_memoization_metadata(
            candidate_rows=1200,
            unique_wallets=300,
            unique_markets=6,
            unique_domains=2,
        )

        self.assertTrue(metadata["enabled"])
        self.assertEqual(metadata["repeatedWalletCandidateOpportunities"], 900)
        self.assertTrue(metadata["candidateOrderPreserved"])
        self.assertTrue(metadata["scoreFormulaPreserved"])
        self.assertFalse(metadata["chunkMetadata"]["rowsHidden"])
        self.assertEqual(metadata["chunkMetadata"]["coveredItemCount"], 1200)

    def test_cache_key_and_missing_data_fallback_are_deterministic(self) -> None:
        first = {"wallet": "0xabc", "conditionId": "0xcond", "timestamp": "2026-05-25T00:00:00Z"}
        second = dict(reversed(list(first.items())))

        self.assertEqual(candidate_performance_cache_key(first), candidate_performance_cache_key(second))

        before = extract_candidate_contract_rows([first])
        after = extract_candidate_contract_rows([dict(second)])
        self.assertTrue(compare_candidate_output_contract(before, after)["passed"])

    def test_snapshot_cli_is_offline_and_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "rows.json"
            output = root / "snapshot.json"
            source.write_text(json.dumps({"rows": [_candidate_row("trade-a", score=44)]}), encoding="utf-8")

            self.assertEqual(main(["--input", str(source), "--output", str(output), "--quiet"]), 0)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(payload["networkUsed"])
        self.assertFalse(payload["runtimeBehaviorChanged"])
        self.assertEqual(payload["candidateCount"], 1)


def _candidate_row(
    trade_id: str,
    *,
    score: int = 40,
    bucket: str = "primary_event_forensic",
    demoted: str = "No",
) -> dict[str, object]:
    return {
        "tradeId": trade_id,
        "wallet": "0xwallet",
        "conditionId": "0xcondition",
        "timestamp": "2026-05-25T00:00:00Z",
        "eventForensicScore": score,
        "existingModelScore": 10,
        "candidateAdmissionStage": "normal_candidate",
        "reviewBucketAfterPolicy": bucket,
        "weakHistoryNearCertaintyReviewDemotion": demoted,
    }


if __name__ == "__main__":
    unittest.main()
