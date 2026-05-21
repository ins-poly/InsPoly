from __future__ import annotations

import unittest

from tools.model_behavior_audit import audit_records
from tools.report_dedupe import build_count_hygiene_summary, count_hygiene_warnings, dedupe_key


class ReportDedupeTests(unittest.TestCase):
    def test_shared_dedupe_helper_collapses_duplicate_trade_rows(self) -> None:
        rows = [
            {"trade_id": "t1", "wallet": "0xabc", "condition_id": "cond"},
            {"trade_id": "t1", "wallet": "0xabc", "condition_id": "cond"},
        ]
        summary = build_count_hygiene_summary([dict(row, strong_risk=True, hard_evidence_review=True, visible=True) for row in rows])
        self.assertEqual(summary["uniqueStrongRiskRows"], 1)
        self.assertEqual(summary["rawStrongRiskRows"], 2)

    def test_shared_dedupe_helper_keeps_distinct_trades(self) -> None:
        rows = [
            {"trade_id": "t1", "wallet": "0xabc", "condition_id": "cond", "strong_risk": True},
            {"trade_id": "t2", "wallet": "0xabc", "condition_id": "cond", "strong_risk": True},
        ]
        summary = build_count_hygiene_summary(rows)
        self.assertEqual(summary["uniqueStrongRiskRows"], 2)

    def test_fallback_dedupe_key_is_low_confidence(self) -> None:
        key, source = dedupe_key({"wallet": "0xabc", "condition_id": "cond", "notional": "123"})
        self.assertIn("wallet:0xabc", key)
        self.assertEqual(source, "wallet_condition_timebucket_notional")
        summary = build_count_hygiene_summary(
            [{"wallet": "0xabc", "condition_id": "cond", "notional": "123", "strong_risk": True} for _ in range(10)]
        )
        self.assertTrue(any(warning["code"] == "dedupe_key_low_confidence" for warning in count_hygiene_warnings(summary)))

    def test_dedupe_inflation_warning_and_concern_thresholds(self) -> None:
        warning_summary = build_count_hygiene_summary(
            [
                {"trade_id": "t1", "wallet": "w", "condition_id": "c", "strong_risk": True},
                {"trade_id": "t1", "wallet": "w", "condition_id": "c", "strong_risk": True},
                {"trade_id": "t2", "wallet": "w", "condition_id": "c", "strong_risk": True},
            ]
        )
        self.assertTrue(
            any(warning["code"] == "strong_risk_dedupe_inflation_warning" for warning in count_hygiene_warnings(warning_summary))
        )
        concern_summary = build_count_hygiene_summary(
            [{"trade_id": "t1", "wallet": "w", "condition_id": "c", "strong_risk": True} for _ in range(2)]
        )
        self.assertTrue(
            any(warning["code"] == "strong_risk_dedupe_inflation_concern" for warning in count_hygiene_warnings(concern_summary))
        )

    def test_model_behavior_audit_reports_raw_and_unique_counts(self) -> None:
        summary = audit_records(
            [
                {
                    "tradeId": "t1",
                    "wallet": "0xabc",
                    "conditionId": "cond",
                    "severity": "Strong Risk",
                    "hardEvidenceReviewTier": "Hard Evidence Review",
                },
                {
                    "tradeId": "t1",
                    "wallet": "0xabc",
                    "conditionId": "cond",
                    "severity": "Strong Risk",
                    "hardEvidenceReviewTier": "Hard Evidence Review",
                },
            ]
        )
        self.assertEqual(summary["rawStrongRiskRows"], 2)
        self.assertEqual(summary["uniqueStrongRiskRows"], 1)
        self.assertEqual(summary["rawHardEvidenceReviewRows"], 2)
        self.assertEqual(summary["uniqueHardEvidenceReviewRows"], 1)


if __name__ == "__main__":
    unittest.main()
