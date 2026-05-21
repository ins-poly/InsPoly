from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import unittest

from tools.ceasefire_event_leak_investigation import (
    TRUTH_SOCIAL_STATUS_ID,
    decode_truth_social_status_time,
    price_at,
    risk_tier_for_score,
)


class CeasefireEventLeakInvestigationTests(unittest.TestCase):
    def test_truth_social_status_id_decodes_to_working_timestamp(self) -> None:
        decoded = decode_truth_social_status_time(TRUTH_SOCIAL_STATUS_ID)
        self.assertEqual(decoded.replace(microsecond=0), datetime(2026, 5, 8, 18, 0, 31, tzinfo=UTC))

    def test_risk_tier_uses_score_and_large_exposure(self) -> None:
        self.assertEqual(risk_tier_for_score(72, Decimal("1000")), "high_review_candidate")
        self.assertEqual(risk_tier_for_score(20, Decimal("25000")), "high_review_candidate")
        self.assertEqual(risk_tier_for_score(20, Decimal("100000")), "critical_review_candidate")

    def test_price_at_uses_latest_prior_point(self) -> None:
        history = [
            {"time": datetime(2026, 5, 8, 17, 55, tzinfo=UTC), "p": Decimal("0.31")},
            {"time": datetime(2026, 5, 8, 18, 5, tzinfo=UTC), "p": Decimal("0.75")},
        ]
        self.assertEqual(price_at(history, datetime(2026, 5, 8, 18, 0, tzinfo=UTC)), Decimal("0.31"))


if __name__ == "__main__":
    unittest.main()
