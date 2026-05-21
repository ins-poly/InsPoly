from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.review_packet_case_reviewer_compare import compare_packets_to_case_reviewer, write_outputs


class ReviewPacketCaseReviewerCompareTests(unittest.TestCase):
    def test_matches_wallets_and_counts_false_positive_verdicts(self) -> None:
        packet_payload = {
            "packets": [
                {
                    "packet_id": "packet_0001",
                    "wallet": "0x1111111111111111111111111111111111111111",
                    "group": "strong_risk",
                    "market": "Market A",
                },
                {
                    "packet_id": "packet_0002",
                    "wallet": "0x2222222222222222222222222222222222222222",
                    "group": "hard_evidence_review",
                    "market": "Market B",
                },
            ]
        }
        case_payload = {
            "case_packets": [
                {
                    "case_id": "wallet-1",
                    "case_type": "wallet",
                    "wallet": "0x1111111111111111111111111111111111111111",
                    "event": "Event A",
                    "username": "alpha",
                }
            ],
            "reviews": [
                {
                    "case_id": "wallet-1",
                    "review_verdict": "likely_false_positive",
                    "interpretation_class": "high_volume_public_power_user",
                    "confidence": 0.8,
                    "main_reason": "High volume without independent evidence.",
                }
            ],
        }
        payload = compare_packets_to_case_reviewer(packet_payload, case_payload)
        self.assertEqual(payload["summary"]["match_count"], 1)
        self.assertEqual(payload["summary"]["packets_matching_case_reviewer_false_positive"], 1)
        self.assertEqual(payload["summary"]["packets_without_case_reviewer_match"], 1)
        self.assertEqual(payload["matches"][0]["review_verdict"], "likely_false_positive")

    def test_plausible_cases_are_counted_separately(self) -> None:
        packet_payload = {
            "packets": [
                {
                    "packet_id": "packet_0001",
                    "wallet": "0x3333333333333333333333333333333333333333",
                    "group": "overlap",
                }
            ]
        }
        case_payload = {
            "case_packets": [
                {"case_id": "wallet-1", "wallet": "0x3333333333333333333333333333333333333333"}
            ],
            "reviews": [
                {
                    "case_id": "wallet-1",
                    "review_verdict": "plausible_insider_style",
                    "interpretation_class": "insider_style_candidate",
                }
            ],
        }
        payload = compare_packets_to_case_reviewer(packet_payload, case_payload)
        self.assertEqual(payload["summary"]["packets_matching_case_reviewer_plausible"], 1)
        self.assertEqual(payload["summary"]["packets_matching_case_reviewer_false_positive"], 0)

    def test_missing_inputs_do_not_crash(self) -> None:
        payload = compare_packets_to_case_reviewer({}, {})
        self.assertIn("review_packets", payload["summary"]["missing_inputs"])
        self.assertIn("case_reviewer_cases", payload["summary"]["missing_inputs"])
        self.assertEqual(payload["summary"]["packet_count"], 0)

    def test_outputs_are_written(self) -> None:
        payload = compare_packets_to_case_reviewer({"packets": []}, {"case_packets": [], "reviews": []})
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_outputs(payload, Path(tmp))
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())


if __name__ == "__main__":
    unittest.main()
