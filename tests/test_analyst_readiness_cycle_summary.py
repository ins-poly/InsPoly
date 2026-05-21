from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.analyst_readiness_cycle_summary import build_cycle_summary, render_markdown, write_outputs


class AnalystReadinessCycleSummaryTests(unittest.TestCase):
    def test_cycle_summary_collects_latest_reporting_state(self) -> None:
        payload = build_cycle_summary(
            {
                "candidate_recall_diagnostic": {
                    "summary": {"diagnostic_interpretation": "no_recall_change_indicated_from_saved_outputs"}
                },
                "false_positive_guardrail_audit": {"summary": {"guardrailsPassed": True}},
                "analyst_evidence_limitation_digest": {"summary": {"activeLimitationCount": 5}},
                "review_artifact_freshness_report": {"summary": {"missingLatestArtifactCount": 0}},
                "review_output_index": {"summary": {"entry_count": 77}},
                "artifact_manifest": {"summary": {"artifact_count": 25, "missing_artifact_count": 0}},
                "gate_decision_readiness": {"final_readiness_classification": "not_ready_corpus_too_cache_only"},
            }
        )
        summary = payload["summary"]
        self.assertEqual(summary["cycleCount"], 5)
        self.assertEqual(summary["readinessClassification"], "not_ready_corpus_too_cache_only")
        self.assertEqual(summary["reviewIndexEntryCount"], 77)
        self.assertTrue(summary["guardrailsPassed"])
        self.assertFalse(summary["modelBehaviorChanged"])
        self.assertIn("readyToCopyNextPrompt", payload)

    def test_missing_optional_artifacts_do_not_crash(self) -> None:
        payload = build_cycle_summary({})
        self.assertEqual(payload["summary"]["cycleCount"], 5)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_next_prompt_preserves_hard_constraints(self) -> None:
        payload = build_cycle_summary({})
        prompt = payload["readyToCopyNextPrompt"]
        self.assertIn("Do not edit _score_trade()", prompt)
        self.assertIn("Do not use false-positive library", prompt)
        self.assertNotIn("change weights", prompt.lower())
        self.assertNotIn("lower thresholds", prompt.lower())

    def test_outputs_are_valid_json(self) -> None:
        payload = build_cycle_summary({})
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_outputs(payload, Path(tmp))
            loaded = json.loads(Path(outputs["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(loaded["summary"]["cycleCount"], 5)
            self.assertIn("Analyst Readiness Cycle Summary", Path(outputs["markdown_path"]).read_text(encoding="utf-8"))
            self.assertIn("Ready-To-Copy Next Prompt", render_markdown(payload))


if __name__ == "__main__":
    unittest.main()
