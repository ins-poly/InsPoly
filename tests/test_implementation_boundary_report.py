from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.implementation_boundary_report import (
    ALLOWED_CATEGORIES,
    build_analyst_crosswalk,
    build_boundary_report,
    write_outputs,
)


class ImplementationBoundaryReportTests(unittest.TestCase):
    def _source_schema(self) -> dict:
        return {
            "field_actions": [
                {
                    "field": "hard_evidence_sources",
                    "priority": "high",
                    "combined_missing_count": 10,
                    "source_missing_count": 4,
                    "schema_missing_count": 6,
                    "safe_repair_type": "accepted-source propagation/display audit",
                    "safe_next_check": "Trace display propagation only.",
                },
                {
                    "field": "gate_branch",
                    "priority": "high",
                    "combined_missing_count": 5,
                    "source_missing_count": 2,
                    "schema_missing_count": 3,
                    "safe_repair_type": "gate branch display audit",
                    "safe_next_check": "Trace gate branch display only.",
                },
            ]
        }

    def test_boundary_uses_allowed_categories_only(self) -> None:
        payload = build_boundary_report(
            source_schema=self._source_schema(),
            candidate_recall={"diagnostic_interpretation": "no_recall_change_indicated_from_saved_outputs"},
            false_positive={
                "patterns": [
                    {
                        "pattern_key": "no_independent_hard_evidence",
                        "label": "No independent hard evidence",
                        "observed_count": 7,
                        "analyst_playbook": {"automatic_action_allowed": False},
                    }
                ]
            },
            readiness={"readinessClassification": "not_ready_corpus_too_cache_only"},
            strategic_next_action={"decision": "stop_human_approval_required"},
        )
        categories = {issue["classification"] for issue in payload["issues"]}
        self.assertTrue(categories.issubset(ALLOWED_CATEGORIES))
        self.assertEqual(payload["summary"]["category_counts"]["safe_schema_propagation_fix"], 1)

    def test_model_changing_and_rpc_issues_are_never_safe(self) -> None:
        payload = build_boundary_report(
            source_schema={},
            candidate_recall={"near_miss_visibility": {"funnel_file_count": 0}},
            readiness={"readinessClassification": "not_ready_corpus_too_cache_only"},
            strategic_next_action={"decision": "stop_human_approval_required"},
        )
        unsafe = [
            issue
            for issue in payload["issues"]
            if issue["classification"] in {"rfc_only_model_behavior_change", "blocked_by_rpc", "reject_or_defer"}
        ]
        self.assertTrue(unsafe)
        self.assertTrue(all(not issue["safeImplementationAllowed"] for issue in unsafe))

    def test_false_positive_library_stays_advisory(self) -> None:
        payload = build_boundary_report(
            false_positive={
                "patterns": [
                    {
                        "pattern_key": "high_volume_public_user",
                        "label": "High-volume public user",
                        "observed_count": 3,
                        "analyst_playbook": {"automatic_action_allowed": False},
                    }
                ]
            }
        )
        fp_issue = next(issue for issue in payload["issues"] if issue["issueId"].startswith("FP-"))
        self.assertEqual(fp_issue["classification"], "safe_analyst_explanation_fix")
        self.assertIn("cannot suppress", fp_issue["whyThisDoesNotOrDoesChangeModelBehavior"].lower())

    def test_crosswalk_generated_from_existing_artifacts(self) -> None:
        payload = build_analyst_crosswalk(
            source_schema=self._source_schema(),
            false_positive={
                "patterns": [
                    {
                        "pattern_key": "no_independent_hard_evidence",
                        "label": "No independent hard evidence",
                        "observed_count": 7,
                        "analyst_playbook": {"automatic_action_allowed": False},
                    },
                    {
                        "pattern_key": "gate_trace_missing",
                        "label": "Gate trace missing",
                        "observed_count": 2,
                        "analyst_playbook": {"automatic_action_allowed": False},
                    },
                ]
            },
            review_packets={"summary": {"unique_packet_count": 2}},
            review_index={"summary": {"latest_by_kind": {"unique_review_packets": "/tmp/packets.json"}}},
        )
        self.assertEqual(payload["summary"]["crosswalk_count"], 2)
        self.assertFalse(payload["summary"]["model_behavior_changed"])
        self.assertEqual(payload["crosswalk"][0]["falsePositivePattern"]["automaticActionAllowed"], False)

    def test_missing_optional_artifacts_do_not_crash_and_outputs_are_written(self) -> None:
        boundary = build_boundary_report()
        crosswalk = build_analyst_crosswalk()
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_outputs(boundary, crosswalk, Path(tmp))
            self.assertTrue(Path(outputs["boundary_json"]).exists())
            self.assertTrue(Path(outputs["crosswalk_markdown"]).exists())


if __name__ == "__main__":
    unittest.main()
