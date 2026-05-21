from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.false_positive_guardrail_audit import build_guardrail_audit, render_markdown, write_outputs


class FalsePositiveGuardrailAuditTests(unittest.TestCase):
    def test_guardrails_pass_when_all_artifacts_are_advisory_only(self) -> None:
        payload = build_guardrail_audit(
            {
                "false_positive_library": {
                    "patterns": [
                        {
                            "pattern_key": "funding_unknown",
                            "analyst_playbook": {"automatic_action_allowed": False},
                        }
                    ]
                },
                "false_positive_explanation_report": {
                    "summary": {
                        "automaticActionAllowed": False,
                        "falsePositiveLibraryUsedForScoring": False,
                    }
                },
                "packet_quality_report": {
                    "warningsSummary": {
                        "automaticActionAllowed": False,
                        "falsePositiveLibraryUsedForScoring": False,
                    }
                },
                "candidate_recall_diagnostic": {"summary": {"automatic_routing_allowed": False}},
                "analyst_decision_sidecar": {"summary": {"productionUseAllowed": False, "scoringChanged": False}},
            }
        )
        self.assertTrue(payload["summary"]["guardrailsPassed"])
        self.assertEqual(payload["summary"]["violationCount"], 0)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertFalse(payload["summary"]["falsePositiveLibraryUsedForScoring"])

    def test_guardrail_violation_is_reported_without_changing_behavior(self) -> None:
        payload = build_guardrail_audit(
            {
                "false_positive_library": {
                    "patterns": [
                        {
                            "pattern_key": "bad",
                            "analyst_playbook": {"automatic_action_allowed": True},
                        }
                    ]
                }
            }
        )
        self.assertFalse(payload["summary"]["guardrailsPassed"])
        self.assertGreaterEqual(payload["summary"]["violationCount"], 1)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertIn("automatic_action_allowed_not_false", payload["violations"][0]["violation"])

    def test_missing_optional_artifacts_do_not_crash(self) -> None:
        payload = build_guardrail_audit({})
        self.assertFalse(payload["summary"]["guardrailsPassed"] is None)
        self.assertEqual(payload["summary"]["artifactCount"], 5)

    def test_outputs_are_valid_json(self) -> None:
        payload = build_guardrail_audit({})
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_outputs(payload, Path(tmp))
            loaded = json.loads(Path(outputs["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(loaded["summary"]["artifactCount"], 5)
            self.assertIn("False-Positive Guardrail Audit", Path(outputs["markdown_path"]).read_text(encoding="utf-8"))
            self.assertIn("Guardrails", render_markdown(payload))


if __name__ == "__main__":
    unittest.main()
