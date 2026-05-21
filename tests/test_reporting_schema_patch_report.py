from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.reporting_schema_patch_report import build_patch_report, write_outputs


class ReportingSchemaPatchReportTests(unittest.TestCase):
    def _boundary(self) -> dict:
        return {
            "summary": {"issue_count": 5, "model_behavior_changed": False},
            "issues": [
                {
                    "issueId": "SCHEMA-001",
                    "classification": "safe_schema_propagation_fix",
                    "issueSummary": "hard evidence sources missing",
                    "safeImplementationAllowed": True,
                },
                {
                    "issueId": "SCHEMA-002",
                    "classification": "safe_reporting_fix",
                    "issueSummary": "composition missing",
                    "safeImplementationAllowed": True,
                },
                {
                    "issueId": "SCHEMA-003",
                    "classification": "safe_reporting_fix",
                    "issueSummary": "gate branch missing",
                    "safeImplementationAllowed": True,
                },
                {
                    "issueId": "FP-001",
                    "classification": "safe_analyst_explanation_fix",
                    "issueSummary": "false-positive caution",
                    "safeImplementationAllowed": True,
                },
                {
                    "issueId": "SCHEMA-004",
                    "classification": "safe_reporting_fix",
                    "issueSummary": "gate type missing",
                    "safeImplementationAllowed": True,
                },
                {
                    "issueId": "SCHEMA-005",
                    "classification": "safe_analyst_explanation_fix",
                    "issueSummary": "suppressors missing",
                    "safeImplementationAllowed": True,
                },
                {
                    "issueId": "SCHEMA-006",
                    "classification": "safe_navigation_or_index_fix",
                    "issueSummary": "condition id missing",
                    "safeImplementationAllowed": True,
                },
                {
                    "issueId": "SCHEMA-007",
                    "classification": "safe_navigation_or_index_fix",
                    "issueSummary": "trade id missing",
                    "safeImplementationAllowed": True,
                },
                {
                    "issueId": "SCHEMA-008",
                    "classification": "safe_navigation_or_index_fix",
                    "issueSummary": "market missing",
                    "safeImplementationAllowed": True,
                },
                {
                    "issueId": "SCHEMA-009",
                    "classification": "safe_navigation_or_index_fix",
                    "issueSummary": "wallet missing",
                    "safeImplementationAllowed": True,
                },
                {
                    "issueId": "RFC-001",
                    "classification": "rfc_only_model_behavior_change",
                    "issueSummary": "gate review",
                    "safeImplementationAllowed": False,
                },
                {
                    "issueId": "RPC-001",
                    "classification": "blocked_by_rpc",
                    "issueSummary": "fresh funding blocked",
                    "safeImplementationAllowed": False,
                },
            ],
        }

    def test_patch_report_selects_only_approved_safe_issues(self) -> None:
        payload = build_patch_report(boundary=self._boundary())
        self.assertEqual(payload["summary"]["selected_issue_ids"], ["SCHEMA-001", "SCHEMA-002", "SCHEMA-003"])
        self.assertEqual(payload["summary"]["selected_issue_count"], 3)
        self.assertFalse(payload["summary"]["model_behavior_changed"])
        self.assertFalse(payload["summary"]["false_positive_library_used_for_scoring"])

    def test_patch_report_can_select_round_two_safe_issues(self) -> None:
        payload = build_patch_report(
            boundary=self._boundary(),
            selected_issue_ids=("SCHEMA-004", "SCHEMA-005", "SCHEMA-006"),
            previously_implemented_issue_ids=("SCHEMA-001", "SCHEMA-002", "SCHEMA-003"),
        )
        self.assertEqual(payload["summary"]["selected_issue_ids"], ["SCHEMA-004", "SCHEMA-005", "SCHEMA-006"])
        self.assertEqual(payload["summary"]["previously_implemented_issue_ids"], ["SCHEMA-001", "SCHEMA-002", "SCHEMA-003"])
        self.assertEqual(payload["summary"]["selected_issue_count"], 3)
        self.assertEqual(payload["summary"]["remaining_safe_fix_count"], 4)
        behavior_ids = {item["issueId"] for item in payload["exact_behavior_added"]}
        self.assertEqual(behavior_ids, {"SCHEMA-004", "SCHEMA-005", "SCHEMA-006"})
        self.assertFalse(payload["summary"]["model_behavior_changed"])

    def test_patch_report_can_select_round_three_safe_issues(self) -> None:
        payload = build_patch_report(
            boundary=self._boundary(),
            selected_issue_ids=("SCHEMA-007", "SCHEMA-008", "SCHEMA-009"),
            previously_implemented_issue_ids=("SCHEMA-001", "SCHEMA-002", "SCHEMA-003", "SCHEMA-004", "SCHEMA-005", "SCHEMA-006"),
        )
        self.assertEqual(payload["summary"]["selected_issue_ids"], ["SCHEMA-007", "SCHEMA-008", "SCHEMA-009"])
        self.assertEqual(payload["summary"]["selected_issue_count"], 3)
        behavior_ids = {item["issueId"] for item in payload["exact_behavior_added"]}
        self.assertEqual(behavior_ids, {"SCHEMA-007", "SCHEMA-008", "SCHEMA-009"})
        self.assertFalse(payload["summary"]["model_behavior_changed"])

    def test_patch_report_can_select_false_positive_advisory_issues(self) -> None:
        payload = build_patch_report(
            boundary=self._boundary(),
            selected_issue_ids=("FP-001", "FP-002", "FP-003"),
            previously_implemented_issue_ids=(
                "SCHEMA-001",
                "SCHEMA-002",
                "SCHEMA-003",
                "SCHEMA-004",
                "SCHEMA-005",
                "SCHEMA-006",
                "SCHEMA-007",
                "SCHEMA-008",
                "SCHEMA-009",
            ),
        )
        self.assertEqual(payload["summary"]["selected_issue_ids"], ["FP-001", "FP-002", "FP-003"])
        self.assertFalse(payload["summary"]["false_positive_library_used_for_scoring"])
        self.assertTrue(all("reporting-only" in item["whyNoModelBehaviorChange"] for item in payload["exact_behavior_added"]))

    def test_patch_report_can_select_round_five_false_positive_issues(self) -> None:
        payload = build_patch_report(
            boundary=self._boundary(),
            selected_issue_ids=("FP-004", "FP-005", "FP-006"),
            previously_implemented_issue_ids=(
                "SCHEMA-001",
                "SCHEMA-002",
                "SCHEMA-003",
                "SCHEMA-004",
                "SCHEMA-005",
                "SCHEMA-006",
                "SCHEMA-007",
                "SCHEMA-008",
                "SCHEMA-009",
                "FP-001",
                "FP-002",
                "FP-003",
            ),
        )
        self.assertEqual(payload["summary"]["selected_issue_ids"], ["FP-004", "FP-005", "FP-006"])
        self.assertFalse(payload["summary"]["model_behavior_changed"])

    def test_patch_report_can_select_final_false_positive_issues(self) -> None:
        payload = build_patch_report(
            boundary=self._boundary(),
            selected_issue_ids=("FP-007", "FP-008"),
            previously_implemented_issue_ids=(
                "SCHEMA-001",
                "SCHEMA-002",
                "SCHEMA-003",
                "SCHEMA-004",
                "SCHEMA-005",
                "SCHEMA-006",
                "SCHEMA-007",
                "SCHEMA-008",
                "SCHEMA-009",
                "FP-001",
                "FP-002",
                "FP-003",
                "FP-004",
                "FP-005",
                "FP-006",
            ),
        )
        self.assertEqual(payload["summary"]["selected_issue_ids"], ["FP-007", "FP-008"])
        self.assertFalse(payload["summary"]["model_behavior_changed"])

    def test_model_and_rpc_issues_remain_untouched(self) -> None:
        payload = build_patch_report(boundary=self._boundary())
        self.assertEqual(payload["summary"]["rfc_only_issues_left_untouched"], 1)
        self.assertEqual(payload["summary"]["rpc_blocked_issues_left_untouched"], 1)
        self.assertEqual(payload["rfc_only_issues_left_untouched"][0]["issueId"], "RFC-001")
        self.assertEqual(payload["rpc_blocked_issues_left_untouched"][0]["issueId"], "RPC-001")

    def test_missing_optional_artifacts_do_not_crash_and_outputs_are_written(self) -> None:
        payload = build_patch_report(boundary={})
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_outputs(payload, Path(tmp), output_stem="reporting_schema_patch_report_20260505_round2")
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())
            self.assertTrue(outputs["json_path"].endswith("_round2.json"))


if __name__ == "__main__":
    unittest.main()
