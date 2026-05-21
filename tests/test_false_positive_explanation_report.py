from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.false_positive_explanation_report import build_explanation_report, render_markdown, write_outputs


class FalsePositiveExplanationReportTests(unittest.TestCase):
    def _library_payload(self) -> dict:
        return {
            "summary": {"top_patterns": [{"pattern_key": "high_volume_public_user", "observed_count": 12}]},
            "patterns": [
                {
                    "pattern_key": "high_volume_public_user",
                    "label": "High-volume public user",
                    "observed_count": 12,
                    "analyst_meaning": "Repeated public activity can look insider-style.",
                    "analyst_playbook": {
                        "inspect_next": "Look for independent hard evidence.",
                        "review_questions": ["Does the concern survive without volume?"],
                    },
                    "forbidden_use": "Do not automatically suppress rows from this pattern.",
                }
            ],
        }

    def _quality_payload(self) -> dict:
        return {
            "packetQualityRows": [
                {
                    "packetId": "packet_0001",
                    "wallet": "0x111",
                    "marketOrEvent": "Market A",
                    "analystPriority": "high",
                    "falsePositiveAdvisoryMatches": [
                        {
                            "pattern": "high_volume_public_user",
                            "message": "High-volume caution.",
                            "analystQuestion": "Is there independent hard evidence?",
                        }
                    ],
                }
            ]
        }

    def test_report_explains_current_false_positive_matches(self) -> None:
        payload = build_explanation_report(self._library_payload(), self._quality_payload())
        self.assertEqual(payload["summary"]["patternCount"], 1)
        self.assertEqual(payload["summary"]["packetsWithFalsePositiveAdvisoryMatches"], 1)
        row = payload["patternRows"][0]
        self.assertEqual(row["patternKey"], "high_volume_public_user")
        self.assertEqual(row["currentPacketMatchCount"], 1)
        self.assertEqual(row["libraryObservedCount"], 12)
        self.assertFalse(row["automaticActionAllowed"])
        self.assertFalse(row["falsePositiveLibraryUsedForScoring"])

    def test_report_is_advisory_only_and_preserves_detector_behavior(self) -> None:
        payload = build_explanation_report(self._library_payload(), self._quality_payload())
        summary = payload["summary"]
        self.assertFalse(summary["automaticActionAllowed"])
        self.assertFalse(summary["falsePositiveLibraryUsedForScoring"])
        self.assertFalse(summary["modelBehaviorChanged"])
        self.assertFalse(summary["scoringChanged"])
        self.assertFalse(summary["gatesChanged"])
        self.assertFalse(summary["herRoutingChanged"])
        self.assertFalse(summary["fundingEligibilityChanged"])
        self.assertFalse(summary["candidateAdmissionChanged"])

    def test_missing_optional_artifacts_do_not_crash(self) -> None:
        payload = build_explanation_report({}, {})
        self.assertEqual(payload["summary"]["patternCount"], 0)
        self.assertEqual(payload["patternRows"], [])

    def test_outputs_are_valid_json_and_markdown(self) -> None:
        payload = build_explanation_report(self._library_payload(), self._quality_payload())
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_outputs(payload, Path(tmp))
            loaded = json.loads(Path(outputs["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(loaded["summary"]["patternCount"], 1)
            self.assertIn("False-Positive Explanation Report", Path(outputs["markdown_path"]).read_text(encoding="utf-8"))
            self.assertIn("forbidden use", render_markdown(payload).lower())


if __name__ == "__main__":
    unittest.main()
