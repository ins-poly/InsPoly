from __future__ import annotations

import unittest

from app.event_forensic import (
    EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD,
    HARD_EVIDENCE_REVIEW_TIER,
    WEAK_HISTORY_NEAR_CERTAINTY_REVIEW_REQUIRED_TIER,
    _annotate_weak_history_near_certainty_review_policy,
    _candidate_audit_fieldnames,
    _candidate_audit_rows,
    _is_weak_history_near_certainty_review_demoted,
)


class EventForensicWeakHistoryReviewDemotionTests(unittest.TestCase):
    def test_matching_weak_history_near_certainty_later_win_is_demoted_from_primary(self) -> None:
        row = _weak_history_near_certainty_row()

        _annotate_weak_history_near_certainty_review_policy([row])
        primary_rows = _primary_after_policy([row])
        audit_rows = _candidate_audit_rows(
            [row],
            suspicious_trades=primary_rows,
            ranked_wallets=[],
            funding_trace_mode="disabled",
        )

        self.assertEqual(row["weakHistoryNearCertaintyReviewDemotion"], "Yes")
        self.assertEqual(row["reviewBucketAfterPolicy"], WEAK_HISTORY_NEAR_CERTAINTY_REVIEW_REQUIRED_TIER)
        self.assertEqual(primary_rows, [])
        self.assertEqual(audit_rows[0]["finalDisplayTier"], WEAK_HISTORY_NEAR_CERTAINTY_REVIEW_REQUIRED_TIER)
        self.assertIn("candidate audit", audit_rows[0]["primaryUiExplanation"])

    def test_high_score_matching_row_keeps_score_but_moves_to_review_required(self) -> None:
        row = _weak_history_near_certainty_row(event_forensic_score=82)

        _annotate_weak_history_near_certainty_review_policy([row])

        self.assertEqual(row["eventForensicScore"], 82)
        self.assertEqual(_primary_after_policy([row]), [])
        self.assertEqual(row["reviewBucketBeforePolicy"], "current_or_retrospective_strong_risk")
        self.assertEqual(row["reviewBucketAfterPolicy"], WEAK_HISTORY_NEAR_CERTAINTY_REVIEW_REQUIRED_TIER)

    def test_strong_history_near_certainty_later_win_is_not_demoted(self) -> None:
        row = _weak_history_near_certainty_row(
            event_forensic_flags=["near_certainty_winner"],
            event_forensic_reducers=["Later correctness is weaker here because the market was already close to certainty."],
            summary="The wallet has a strong track record across prior economic positions.",
        )

        _annotate_weak_history_near_certainty_review_policy([row])

        self.assertEqual(row["weakHistoryNearCertaintyReviewDemotion"], "No")
        self.assertEqual(row["weakHistoryNearCertaintyReviewReason"], "weak_history_signal_absent_or_unknown")
        self.assertNotEqual(row["reviewBucketAfterPolicy"], WEAK_HISTORY_NEAR_CERTAINTY_REVIEW_REQUIRED_TIER)

    def test_low_probability_informed_call_is_not_demoted(self) -> None:
        row = _weak_history_near_certainty_row(economic_side_probability=0.22)

        _annotate_weak_history_near_certainty_review_policy([row])

        self.assertEqual(row["weakHistoryNearCertaintyReviewDemotion"], "No")
        self.assertEqual(row["weakHistoryNearCertaintyReviewReason"], "economic_side_probability_not_near_certainty")

    def test_missing_required_fields_do_not_demote(self) -> None:
        missing_later = _weak_history_near_certainty_row(later_won="")
        missing_probability = _weak_history_near_certainty_row(economic_side_probability="")

        _annotate_weak_history_near_certainty_review_policy([missing_later, missing_probability])

        self.assertEqual(missing_later["weakHistoryNearCertaintyReviewDemotion"], "No")
        self.assertEqual(missing_later["weakHistoryNearCertaintyReviewReason"], "later_correctness_unknown_or_false")
        self.assertEqual(missing_probability["weakHistoryNearCertaintyReviewDemotion"], "No")
        self.assertEqual(missing_probability["weakHistoryNearCertaintyReviewReason"], "economic_side_probability_unavailable")

    def test_old_report_like_row_without_new_fields_stays_absent_safe(self) -> None:
        row = {
            "id": "old-row",
            "wallet": "0xold",
            "conditionId": "cond-old",
            "timestamp": "2026-05-24T00:00:00+00:00",
            "side": "YES",
            "orderSide": "BUY",
            "positionSize": 1000,
            "existingModelClass": "Strong Risk",
            "eventForensicScore": 41,
            "hardEvidenceReviewTier": "",
            "fundingEvidenceGrade": "unknown",
        }

        _annotate_weak_history_near_certainty_review_policy([row])
        audit_rows = _candidate_audit_rows(
            [row],
            suspicious_trades=[row],
            ranked_wallets=[],
            funding_trace_mode="disabled",
        )

        self.assertEqual(row["weakHistoryNearCertaintyReviewDemotion"], "No")
        self.assertEqual(audit_rows[0]["finalDisplayTier"], "primary_event_forensic")
        self.assertEqual(audit_rows[0]["weakHistoryNearCertaintyReviewDemotion"], "No")

    def test_export_fieldnames_include_additive_review_policy_fields(self) -> None:
        fieldnames = _candidate_audit_fieldnames()

        self.assertIn("weakHistoryNearCertaintyReviewDemotion", fieldnames)
        self.assertIn("weakHistoryNearCertaintyReviewReason", fieldnames)
        self.assertIn("reviewBucketBeforePolicy", fieldnames)
        self.assertIn("reviewBucketAfterPolicy", fieldnames)

    def test_scoring_threshold_constants_are_unchanged(self) -> None:
        self.assertEqual(EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD, 40)


def _weak_history_near_certainty_row(
    *,
    event_forensic_score: int = 6,
    economic_side_probability: object = 0.96,
    later_won: object = True,
    event_forensic_flags: list[str] | None = None,
    event_forensic_reducers: list[str] | None = None,
    summary: str = "The trade later won, but the wallet history is very weak and the entry was already near certainty.",
) -> dict[str, object]:
    return {
        "id": "weak-history-near-certainty",
        "wallet": "0xweak",
        "walletShort": "0xweak",
        "username": "Weak History",
        "market": "Example market",
        "marketSlug": "example-market",
        "conditionId": "cond-example",
        "timestamp": "2026-05-24T00:00:00+00:00",
        "side": "NO",
        "orderSide": "BUY",
        "rawTokenOutcome": "NO",
        "rawOrderSide": "BUY",
        "rawTokenPrice": 0.96,
        "economicSide": "NO",
        "economicSideProbability": economic_side_probability,
        "sideOutcomeNormalizationStatus": "normalized",
        "positionSize": 1000.0,
        "existingModelScore": 88,
        "existingModelClass": "Strong Risk",
        "existingModelVerdict": "Strong current-model context.",
        "eventForensicScore": event_forensic_score,
        "hardEvidenceReviewTier": HARD_EVIDENCE_REVIEW_TIER,
        "hardEvidenceSources": ["dormant_wallet_reactivation"],
        "laterWon": later_won,
        "winnerRank": 38,
        "eventForensicFlags": event_forensic_flags
        if event_forensic_flags is not None
        else ["later_correct", "near_certainty_winner", "weak_wallet_track_record"],
        "eventForensicReducers": event_forensic_reducers
        if event_forensic_reducers is not None
        else [
            "Later correctness is weaker here because the market was already close to certainty.",
            "The wallet's broader losing record blocks a primary insider-style interpretation without independent evidence.",
        ],
        "summary": summary,
        "fundingEvidenceGrade": "unknown",
    }


def _primary_after_policy(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if not _is_weak_history_near_certainty_review_demoted(row)
        and (
            int(row.get("eventForensicScore") or 0) >= EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD
            or row.get("hardEvidenceReviewTier") == HARD_EVIDENCE_REVIEW_TIER
        )
    ]


if __name__ == "__main__":
    unittest.main()
