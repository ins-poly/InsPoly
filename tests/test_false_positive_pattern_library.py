from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.false_positive_pattern_library import build_false_positive_library, write_outputs


class FalsePositivePatternLibraryTests(unittest.TestCase):
    def test_suppressor_patterns_are_grouped_from_review_packets(self) -> None:
        payload = build_false_positive_library(
            review_packet_paths=[],
            case_reviewer_paths=[],
        )
        self.assertEqual(payload["summary"]["pattern_count"], 0)

        with tempfile.TemporaryDirectory() as tmp:
            review_path = Path(tmp) / "packets.json"
            review_path.write_text(
                json.dumps(
                    {
                        "packets": [
                            {
                                "packet_id": "packet_0001",
                                "wallet": "0x1234567890abcdef1234567890abcdef12345678",
                                "market": "Example market",
                                "group": "strong_risk",
                                "suppressors": ["high_volume_public_user", "near_certainty"],
                                "funding_evidence_grade": "unknown",
                                "has_independent_hard_evidence": False,
                                "hard_evidence_sources": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            payload = build_false_positive_library(review_packet_paths=[review_path])
        keys = {pattern["pattern_key"] for pattern in payload["patterns"]}
        self.assertIn("high_volume_public_user", keys)
        self.assertIn("near_certainty", keys)
        self.assertIn("funding_unknown", keys)
        self.assertIn("no_independent_hard_evidence", keys)
        pattern = next(item for item in payload["patterns"] if item["pattern_key"] == "high_volume_public_user")
        self.assertFalse(pattern["analyst_playbook"]["automatic_action_allowed"])
        self.assertTrue(pattern["analyst_playbook"]["review_questions"])

    def test_case_reviewer_likely_false_positive_is_summarized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cases_path = Path(tmp) / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "case_packets": [
                            {
                                "case_id": "wallet-1",
                                "wallet": "0x1234567890abcdef1234567890abcdef12345678",
                                "username": "public user",
                                "event": "Event",
                                "scores": {"wallet_score": 100, "insider_style_wallet_score": 0},
                                "event_activity": {
                                    "event_trade_count": 30,
                                    "notable_trade_count": 25,
                                    "winning_opening_entry_count": 20,
                                },
                                "wallet_export_context": {"walletPublicPowerUserFlag": True},
                                "supporting_evidence": {"independent_hard_evidence": False, "hard_evidence_sources": []},
                            }
                        ],
                        "reviews": [
                            {
                                "case_id": "wallet-1",
                                "review_verdict": "likely_false_positive",
                                "interpretation_class": "high_volume_public_power_user",
                                "evidence_that_weakens_concern": [
                                    "High-volume repeated wins without independent hard evidence."
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            payload = build_false_positive_library(case_reviewer_paths=[cases_path])
        self.assertEqual(payload["summary"]["case_reviewer_likely_false_positive_examples"], 1)
        self.assertEqual(payload["case_reviewer_false_positive_examples"][0]["wallet_score"], 100)
        keys = {pattern["pattern_key"] for pattern in payload["patterns"]}
        self.assertIn("high_volume_public_user", keys)

    def test_missing_optional_fields_do_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.json"
            path.write_text(json.dumps({"case_packets": [{"case_id": "x"}], "reviews": [{"case_id": "x"}]}), encoding="utf-8")
            payload = build_false_positive_library(case_reviewer_paths=[path])
        self.assertIsInstance(payload["patterns"], list)

    def test_inputs_are_not_modified(self) -> None:
        packet_payload = {
            "packets": [
                {
                    "packet_id": "packet_0001",
                    "suppressors": ["domain_specialist"],
                    "funding_evidence_grade": "unknown",
                }
            ]
        }
        before = copy.deepcopy(packet_payload)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packets.json"
            path.write_text(json.dumps(packet_payload), encoding="utf-8")
            build_false_positive_library(review_packet_paths=[path])
            after = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(after, before)

    def test_outputs_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_false_positive_library()
            outputs = write_outputs(payload, Path(tmp))
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())

    def test_forbidden_use_blocks_automatic_suppression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packets.json"
            path.write_text(
                json.dumps({"packets": [{"packet_id": "x", "suppressors": ["bot_like"], "funding_evidence_grade": "unknown"}]}),
                encoding="utf-8",
            )
            payload = build_false_positive_library(review_packet_paths=[path])
        pattern = next(item for item in payload["patterns"] if item["pattern_key"] == "bot_like")
        self.assertIn("Do not automatically suppress", pattern["forbidden_use"])
        self.assertIn("Do not automatically suppress", pattern["analyst_playbook"]["do_not_do"][0])

    def test_evidence_sentences_with_commas_are_not_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cases_path = Path(tmp) / "cases.json"
            sentence = "No independent funding, split-wallet, low-probability, or dormancy evidence is present."
            cases_path.write_text(
                json.dumps(
                    {
                        "case_packets": [{"case_id": "wallet-1", "wallet": "0x123"}],
                        "reviews": [
                            {
                                "case_id": "wallet-1",
                                "review_verdict": "likely_false_positive",
                                "interpretation_class": "high_volume_public_power_user",
                                "evidence_that_weakens_concern": [sentence],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            payload = build_false_positive_library(case_reviewer_paths=[cases_path])
        self.assertEqual(payload["case_reviewer_false_positive_examples"][0]["weakening_evidence"], [sentence])


if __name__ == "__main__":
    unittest.main()
