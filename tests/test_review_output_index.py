from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.review_output_index import RELATED_KIND_MAP, SEARCH_DIRS, _summary_for_json, build_review_output_index, write_outputs


class ReviewOutputIndexTests(unittest.TestCase):
    def test_index_handles_missing_dirs(self) -> None:
        payload = build_review_output_index(limit_per_kind=1)
        self.assertIn("summary", payload)
        self.assertIn("entries", payload)

    def test_outputs_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"generated_at": "now", "summary": {"entry_count": 0, "latest_by_kind": {}}, "entries": []}
            outputs = write_outputs(payload, Path(tmp))
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())

    def test_latest_review_packets_summary_is_indexed(self) -> None:
        payload = build_review_output_index(limit_per_kind=1)
        packet_entries = [entry for entry in payload["entries"] if entry["kind"] == "unique_review_packets"]
        if packet_entries:
            self.assertIn("unique_packet_count", packet_entries[0]["summary"])

    def test_archive_visibility_audit_summary_includes_contract_drift_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archive_visibility_doc_drift_audit.json"
            path.write_text(
                json.dumps(
                    {
                        "summary": {
                            "checkCount": 6,
                            "contractCheckCount": 4,
                            "driftObservedCount": 1,
                            "staleArchiveHardHidePhraseCount": 2,
                            "docsRequireVisibilityReconciliation": True,
                            "archiveVisibilityChanged": False,
                            "modelBehaviorChanged": False,
                        }
                    }
                ),
                encoding="utf-8",
            )

            summary = _summary_for_json(path, "archive_visibility_doc_drift_audit")

        self.assertEqual(summary["check_count"], 6)
        self.assertEqual(summary["contract_check_count"], 4)
        self.assertEqual(summary["stale_archive_hard_hide_phrase_count"], 2)
        self.assertTrue(summary["docs_require_visibility_reconciliation"])
        self.assertFalse(summary["archive_visibility_changed"])

    def test_ui_offline_preflight_summary_is_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ui_offline_implementation_preflight.json"
            path.write_text(
                json.dumps(
                    {
                        "summary": {
                            "preflightStatus": "blocked_missing_runtime_assets",
                            "offlineRisk": "high",
                            "runtimeRequiredDependencyCount": 4,
                            "uniqueRuntimeAssetCount": 4,
                            "missingRuntimeAssetCount": 4,
                            "approvalRequiredBeforeRuntimeChange": True,
                            "implementationApproved": False,
                            "uiRuntimeChanged": False,
                            "modelBehaviorChanged": False,
                        }
                    }
                ),
                encoding="utf-8",
            )

            summary = _summary_for_json(path, "ui_offline_implementation_preflight")

        self.assertEqual(summary["preflight_status"], "blocked_missing_runtime_assets")
        self.assertEqual(summary["missing_runtime_asset_count"], 4)
        self.assertTrue(summary["approval_required_before_runtime_change"])
        self.assertFalse(summary["ui_runtime_changed"])

    def test_offline_timeline_coverage_summary_is_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "offline_timeline_coverage_audit.json"
            path.write_text(
                json.dumps(
                    {
                        "summary": {
                            "coverageStatus": "no_local_timeline_files",
                            "existingTimelineFileCount": 0,
                            "timelineRowCount": 0,
                            "reviewArtifactCount": 2,
                            "reviewRowsInspected": 12,
                            "offlineTimelineMatchedYesCount": 0,
                            "publicKnowledgeAtPresentCount": 0,
                            "timelineDataChanged": False,
                            "modelBehaviorChanged": False,
                        }
                    }
                ),
                encoding="utf-8",
            )

            summary = _summary_for_json(path, "offline_timeline_coverage_audit")

        self.assertEqual(summary["coverage_status"], "no_local_timeline_files")
        self.assertEqual(summary["existing_timeline_file_count"], 0)
        self.assertEqual(summary["review_rows_inspected"], 12)
        self.assertFalse(summary["timeline_data_changed"])
        self.assertFalse(summary["model_behavior_changed"])

    def test_offline_timeline_template_pack_summary_is_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "offline_timeline_template_pack.json"
            path.write_text(
                json.dumps(
                    {
                        "summary": {
                            "sourceCoverageStatus": "no_local_timeline_files",
                            "templateFieldCount": 18,
                            "templateRowsPreFilled": 0,
                            "humanCurationRequired": True,
                            "timelineDataChanged": False,
                            "externalFeedsAdded": False,
                            "modelBehaviorChanged": False,
                        }
                    }
                ),
                encoding="utf-8",
            )

            summary = _summary_for_json(path, "offline_timeline_template_pack")

        self.assertEqual(summary["source_coverage_status"], "no_local_timeline_files")
        self.assertEqual(summary["template_field_count"], 18)
        self.assertEqual(summary["template_rows_pre_filled"], 0)
        self.assertTrue(summary["human_curation_required"])
        self.assertFalse(summary["external_feeds_added"])
        self.assertFalse(summary["model_behavior_changed"])

    def test_offline_timeline_csv_validation_summary_is_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "offline_timeline_csv_validation.json"
            path.write_text(
                json.dumps(
                    {
                        "summary": {
                            "validationStatus": "template_only_no_rows",
                            "rowCount": 0,
                            "validApprovedRowCount": 0,
                            "invalidRowCount": 0,
                            "missingRequiredColumnCount": 0,
                            "runtimeDataChanged": False,
                            "timelineDataChanged": False,
                            "externalFeedsAdded": False,
                            "modelBehaviorChanged": False,
                        }
                    }
                ),
                encoding="utf-8",
            )

            summary = _summary_for_json(path, "offline_timeline_csv_validation")

        self.assertEqual(summary["validation_status"], "template_only_no_rows")
        self.assertEqual(summary["row_count"], 0)
        self.assertFalse(summary["runtime_data_changed"])
        self.assertFalse(summary["external_feeds_added"])
        self.assertFalse(summary["model_behavior_changed"])

    def test_direct_script_import_audit_summary_is_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "direct_script_import_audit.json"
            path.write_text(
                json.dumps(
                    {
                        "summary": {
                            "toolFileCount": 12,
                            "repoRootImportToolCount": 5,
                            "guardedRepoRootImportToolCount": 4,
                            "missingGuardToolCount": 1,
                            "directRunRiskStatus": "missing_repo_root_path_guards",
                            "modelBehaviorChanged": False,
                        }
                    }
                ),
                encoding="utf-8",
            )

            summary = _summary_for_json(path, "direct_script_import_audit")

        self.assertEqual(summary["tool_file_count"], 12)
        self.assertEqual(summary["repo_root_import_tool_count"], 5)
        self.assertEqual(summary["missing_guard_tool_count"], 1)
        self.assertEqual(summary["direct_run_risk_status"], "missing_repo_root_path_guards")
        self.assertFalse(summary["model_behavior_changed"])

    def test_direct_script_cli_smoke_audit_summary_is_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "direct_script_cli_smoke_audit.json"
            path.write_text(
                json.dumps(
                    {
                        "summary": {
                            "argparseCliCandidateCount": 14,
                            "helpOkCount": 13,
                            "helpFailureCount": 1,
                            "helpTimeoutCount": 0,
                            "directCliRiskStatus": "direct_cli_help_issues",
                            "networkCallsIntended": False,
                            "modelBehaviorChanged": False,
                        }
                    }
                ),
                encoding="utf-8",
            )

            summary = _summary_for_json(path, "direct_script_cli_smoke_audit")

        self.assertEqual(summary["argparse_cli_candidate_count"], 14)
        self.assertEqual(summary["help_ok_count"], 13)
        self.assertEqual(summary["help_failure_count"], 1)
        self.assertEqual(summary["direct_cli_risk_status"], "direct_cli_help_issues")
        self.assertFalse(summary["network_calls_intended"])
        self.assertFalse(summary["model_behavior_changed"])

    def test_benchmark_label_cycle_summary_is_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "benchmark_label_cycle.json"
            path.write_text(
                json.dumps(
                    {
                        "summary": {
                            "cycleStatus": "waiting_for_human_labels",
                            "completionStatus": "blank_or_unlabeled_template",
                            "preflightStatus": "structure_ok_unlabeled",
                            "readinessStatus": "unlabeled_template_only",
                            "expectationStatus": "no_human_labels_available",
                            "usableLabeledRows": 0,
                            "invalidLabelRows": 0,
                            "humanActionRequired": True,
                            "labelsAssignedByThisTool": 0,
                            "modelBehaviorChanged": False,
                        }
                    }
                ),
                encoding="utf-8",
            )

            summary = _summary_for_json(path, "benchmark_label_cycle")

        self.assertEqual(summary["cycle_status"], "waiting_for_human_labels")
        self.assertEqual(summary["preflight_status"], "structure_ok_unlabeled")
        self.assertEqual(summary["readiness_status"], "unlabeled_template_only")
        self.assertTrue(summary["human_action_required"])
        self.assertEqual(summary["labels_assigned_by_this_tool"], 0)
        self.assertFalse(summary["model_behavior_changed"])

    def test_test_coverage_inventory_audit_summary_is_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test_coverage_inventory_audit.json"
            path.write_text(
                json.dumps(
                    {
                        "summary": {
                            "testFileCount": 10,
                            "appModuleCount": 7,
                            "appModuleWithDirectTestReferenceCount": 4,
                            "appModuleWithoutDirectTestReferenceCount": 3,
                            "highPriorityAppModuleWithoutDirectTestReferenceCount": 2,
                            "toolModuleCount": 20,
                            "toolModuleWithDirectTestReferenceCount": 15,
                            "coverageInventoryStatus": "high_priority_app_modules_unreferenced",
                            "modelBehaviorChanged": False,
                        }
                    }
                ),
                encoding="utf-8",
            )

            summary = _summary_for_json(path, "test_coverage_inventory_audit")

        self.assertEqual(summary["test_file_count"], 10)
        self.assertEqual(summary["app_module_count"], 7)
        self.assertEqual(summary["high_priority_app_module_without_direct_test_reference_count"], 2)
        self.assertEqual(summary["coverage_inventory_status"], "high_priority_app_modules_unreferenced")
        self.assertFalse(summary["model_behavior_changed"])

    def test_latest_analyst_quality_artifacts_are_indexed(self) -> None:
        payload = build_review_output_index(limit_per_kind=1)
        by_kind = {entry["kind"]: entry for entry in payload["entries"]}
        if "review_packet_quality" in by_kind:
            self.assertIn("packets_with_any_missing_quality_field", by_kind["review_packet_quality"]["summary"])
        if "packet_quality_report" in by_kind:
            self.assertIn("priority_review_queue_count", by_kind["packet_quality_report"]["summary"])
            self.assertIn("model_behavior_changed", by_kind["packet_quality_report"]["summary"])
        if "packet_group_drilldown" in by_kind:
            self.assertIn("wallet_group_count", by_kind["packet_group_drilldown"]["summary"])
            self.assertIn("production_priority_changed", by_kind["packet_group_drilldown"]["summary"])
        if "analyst_evidence_limitation_digest" in by_kind:
            self.assertIn("active_limitation_count", by_kind["analyst_evidence_limitation_digest"]["summary"])
            self.assertFalse(by_kind["analyst_evidence_limitation_digest"]["summary"]["automatic_action_allowed"])
            self.assertFalse(by_kind["analyst_evidence_limitation_digest"]["summary"]["model_behavior_changed"])
        if "analyst_readiness_cycle_summary" in by_kind:
            self.assertIn("cycle_count", by_kind["analyst_readiness_cycle_summary"]["summary"])
            self.assertFalse(by_kind["analyst_readiness_cycle_summary"]["summary"]["model_behavior_changed"])
            self.assertFalse(by_kind["analyst_readiness_cycle_summary"]["summary"]["old_outputs_mutated"])
        if "analyst_decision_sidecar" in by_kind:
            self.assertIn("sidecar_row_count", by_kind["analyst_decision_sidecar"]["summary"])
            self.assertFalse(by_kind["analyst_decision_sidecar"]["summary"]["production_use_allowed"])
            self.assertFalse(by_kind["analyst_decision_sidecar"]["summary"]["scoring_changed"])
        if "wallet_review_queue" in by_kind:
            self.assertIn("wallet_count", by_kind["wallet_review_queue"]["summary"])
        if "analyst_handoff_bundle" in by_kind:
            self.assertIn("model_behavior_changed", by_kind["analyst_handoff_bundle"]["summary"])
        if "artifact_manifest" in by_kind:
            self.assertIn("old_outputs_mutated", by_kind["artifact_manifest"]["summary"])
            self.assertIn("missing_artifact_count", by_kind["artifact_manifest"]["summary"])
            self.assertIn("hash_covered_artifact_count", by_kind["artifact_manifest"]["summary"])
        if "review_artifact_freshness_report" in by_kind:
            self.assertIn("missing_latest_artifact_count", by_kind["review_artifact_freshness_report"]["summary"])
            self.assertFalse(by_kind["review_artifact_freshness_report"]["summary"]["model_behavior_changed"])
            self.assertFalse(by_kind["review_artifact_freshness_report"]["summary"]["old_outputs_mutated"])
        if "source_schema_repair_plan" in by_kind:
            self.assertIn("detector_behavior_changed", by_kind["source_schema_repair_plan"]["summary"])
        if "gate_trace_availability_audit" in by_kind:
            self.assertIn("strong_risk_gate_trace_missing_count", by_kind["gate_trace_availability_audit"]["summary"])
            self.assertFalse(by_kind["gate_trace_availability_audit"]["summary"]["model_behavior_changed"])
            self.assertFalse(by_kind["gate_trace_availability_audit"]["summary"]["gates_changed"])
        if "implementation_boundary" in by_kind:
            self.assertIn("model_behavior_changed", by_kind["implementation_boundary"]["summary"])
        if "analyst_crosswalk" in by_kind:
            self.assertIn("crosswalk_count", by_kind["analyst_crosswalk"]["summary"])
        if "candidate_recall_diagnostic" in by_kind:
            self.assertIn("diagnostic_interpretation", by_kind["candidate_recall_diagnostic"]["summary"])
        if "reporting_schema_patch_report" in by_kind:
            self.assertIn("model_behavior_changed", by_kind["reporting_schema_patch_report"]["summary"])
        if "false_positive_explanation_report" in by_kind:
            self.assertIn(
                "packets_with_false_positive_advisory_matches",
                by_kind["false_positive_explanation_report"]["summary"],
            )
            self.assertFalse(by_kind["false_positive_explanation_report"]["summary"]["automatic_action_allowed"])
            self.assertFalse(by_kind["false_positive_explanation_report"]["summary"]["model_behavior_changed"])
        if "false_positive_guardrail_audit" in by_kind:
            self.assertIn("guardrails_passed", by_kind["false_positive_guardrail_audit"]["summary"])
            self.assertFalse(by_kind["false_positive_guardrail_audit"]["summary"]["automatic_action_allowed"])
            self.assertFalse(by_kind["false_positive_guardrail_audit"]["summary"]["model_behavior_changed"])
        if "ui_offline_asset_manifest" in by_kind:
            self.assertIn("unique_runtime_asset_count", by_kind["ui_offline_asset_manifest"]["summary"])
            self.assertFalse(by_kind["ui_offline_asset_manifest"]["summary"]["implementation_approved"])
            self.assertFalse(by_kind["ui_offline_asset_manifest"]["summary"]["ui_runtime_changed"])
        if "ui_offline_implementation_preflight" in by_kind:
            self.assertIn("preflight_status", by_kind["ui_offline_implementation_preflight"]["summary"])
            self.assertFalse(by_kind["ui_offline_implementation_preflight"]["summary"]["implementation_approved"])
            self.assertFalse(by_kind["ui_offline_implementation_preflight"]["summary"]["ui_runtime_changed"])
        if "offline_timeline_coverage_audit" in by_kind:
            self.assertIn("coverage_status", by_kind["offline_timeline_coverage_audit"]["summary"])
            self.assertFalse(by_kind["offline_timeline_coverage_audit"]["summary"]["timeline_data_changed"])
            self.assertFalse(by_kind["offline_timeline_coverage_audit"]["summary"]["model_behavior_changed"])
        if "offline_timeline_template_pack" in by_kind:
            self.assertIn("template_field_count", by_kind["offline_timeline_template_pack"]["summary"])
            self.assertEqual(by_kind["offline_timeline_template_pack"]["summary"]["template_rows_pre_filled"], 0)
            self.assertFalse(by_kind["offline_timeline_template_pack"]["summary"]["external_feeds_added"])
        if "offline_timeline_csv_validation" in by_kind:
            self.assertIn("validation_status", by_kind["offline_timeline_csv_validation"]["summary"])
            self.assertFalse(by_kind["offline_timeline_csv_validation"]["summary"]["runtime_data_changed"])
            self.assertFalse(by_kind["offline_timeline_csv_validation"]["summary"]["external_feeds_added"])
        if "benchmark_label_priority_queue" in by_kind:
            self.assertIn("queue_row_count", by_kind["benchmark_label_priority_queue"]["summary"])
            self.assertFalse(by_kind["benchmark_label_priority_queue"]["summary"]["model_behavior_changed"])
        if "benchmark_label_priority_template" in by_kind:
            self.assertIn("template_row_count", by_kind["benchmark_label_priority_template"]["summary"])
            self.assertEqual(by_kind["benchmark_label_priority_template"]["summary"]["human_labels_assigned_by_this_tool"], 0)
            self.assertFalse(by_kind["benchmark_label_priority_template"]["summary"]["model_behavior_changed"])
        if "benchmark_label_handoff_pack" in by_kind:
            self.assertIn("queue_row_count", by_kind["benchmark_label_handoff_pack"]["summary"])
            self.assertEqual(by_kind["benchmark_label_handoff_pack"]["summary"]["human_labels_assigned_by_this_tool"], 0)
            self.assertIn("readiness_compatible_template_present", by_kind["benchmark_label_handoff_pack"]["summary"])
            self.assertFalse(by_kind["benchmark_label_handoff_pack"]["summary"]["model_behavior_changed"])
        if "benchmark_label_worksheet" in by_kind:
            self.assertIn("worksheet_row_count", by_kind["benchmark_label_worksheet"]["summary"])
            self.assertEqual(by_kind["benchmark_label_worksheet"]["summary"]["labels_assigned_by_this_tool"], 0)
            self.assertIn("readiness_gate_compatible", by_kind["benchmark_label_worksheet"]["summary"])
            self.assertFalse(by_kind["benchmark_label_worksheet"]["summary"]["model_behavior_changed"])
        if "benchmark_label_action_pack" in by_kind:
            self.assertIn("human_action_required", by_kind["benchmark_label_action_pack"]["summary"])
            self.assertEqual(by_kind["benchmark_label_action_pack"]["summary"]["labels_assigned_by_this_tool"], 0)
            self.assertIn("readiness_status", by_kind["benchmark_label_action_pack"]["summary"])
            self.assertFalse(by_kind["benchmark_label_action_pack"]["summary"]["model_behavior_changed"])
        if "benchmark_label_csv_preflight" in by_kind:
            self.assertIn("preflight_status", by_kind["benchmark_label_csv_preflight"]["summary"])
            self.assertEqual(by_kind["benchmark_label_csv_preflight"]["summary"]["labels_assigned_by_this_tool"], 0)
            self.assertIn("readiness_gate_recommended", by_kind["benchmark_label_csv_preflight"]["summary"])
            self.assertFalse(by_kind["benchmark_label_csv_preflight"]["summary"]["model_behavior_changed"])
        if "benchmark_label_expectation_report" in by_kind:
            self.assertIn("expectation_status", by_kind["benchmark_label_expectation_report"]["summary"])
            self.assertEqual(by_kind["benchmark_label_expectation_report"]["summary"]["labels_assigned_by_this_tool"], 0)
            self.assertIn("disposition_counts", by_kind["benchmark_label_expectation_report"]["summary"])
            self.assertFalse(by_kind["benchmark_label_expectation_report"]["summary"]["model_behavior_changed"])
        if "benchmark_label_completion_status" in by_kind:
            self.assertIn("candidate_csv_count", by_kind["benchmark_label_completion_status"]["summary"])
            self.assertIn("candidate_filled_csv_count", by_kind["benchmark_label_completion_status"]["summary"])
            self.assertIn("readiness_gate_recommended", by_kind["benchmark_label_completion_status"]["summary"])
            self.assertFalse(by_kind["benchmark_label_completion_status"]["summary"]["model_behavior_changed"])
        if "benchmark_label_cycle" in by_kind:
            self.assertIn("cycle_status", by_kind["benchmark_label_cycle"]["summary"])
            self.assertEqual(by_kind["benchmark_label_cycle"]["summary"]["labels_assigned_by_this_tool"], 0)
            self.assertFalse(by_kind["benchmark_label_cycle"]["summary"]["model_behavior_changed"])
        if "autonomous_branch_decision_report" in by_kind:
            self.assertIn("selected_branch", by_kind["autonomous_branch_decision_report"]["summary"])
            self.assertFalse(by_kind["autonomous_branch_decision_report"]["summary"]["model_behavior_changed"])
        if "direct_script_import_audit" in by_kind:
            self.assertIn("direct_run_risk_status", by_kind["direct_script_import_audit"]["summary"])
            self.assertFalse(by_kind["direct_script_import_audit"]["summary"]["model_behavior_changed"])
        if "direct_script_cli_smoke_audit" in by_kind:
            self.assertIn("direct_cli_risk_status", by_kind["direct_script_cli_smoke_audit"]["summary"])
            self.assertFalse(by_kind["direct_script_cli_smoke_audit"]["summary"]["network_calls_intended"])
            self.assertFalse(by_kind["direct_script_cli_smoke_audit"]["summary"]["model_behavior_changed"])
        if "test_coverage_inventory_audit" in by_kind:
            self.assertIn("coverage_inventory_status", by_kind["test_coverage_inventory_audit"]["summary"])
            self.assertFalse(by_kind["test_coverage_inventory_audit"]["summary"]["model_behavior_changed"])

    def test_related_diagnostic_links_are_attached_when_artifacts_exist(self) -> None:
        payload = build_review_output_index(limit_per_kind=1)
        entries = {entry["kind"]: entry for entry in payload["entries"]}
        if "unique_review_packets" in entries and "implementation_boundary" in entries:
            related_kinds = {item["kind"] for item in entries["unique_review_packets"].get("related_diagnostics", [])}
            self.assertIn("implementation_boundary", related_kinds)
        self.assertIn("related_reference_count", payload["summary"])

    def test_packet_quality_report_is_first_class_index_kind(self) -> None:
        self.assertIn("packet_quality_report", SEARCH_DIRS)
        related = set(RELATED_KIND_MAP["packet_quality_report"])
        self.assertIn("unique_review_packets", related)
        self.assertIn("false_positive_library", related)
        self.assertIn("source_schema_repair_plan", related)
        self.assertIn("candidate_recall_diagnostic", related)
        self.assertIn("analyst_handoff_bundle", related)
        self.assertIn("packet_group_drilldown", RELATED_KIND_MAP)

    def test_artifact_manifest_links_to_key_review_artifacts(self) -> None:
        self.assertIn("artifact_manifest", RELATED_KIND_MAP)
        related = set(RELATED_KIND_MAP["artifact_manifest"])
        self.assertIn("packet_quality_report", related)
        self.assertIn("unique_review_packets", related)
        self.assertIn("analyst_handoff_bundle", related)
        self.assertIn("candidate_recall_diagnostic", related)

    def test_analyst_decision_sidecar_is_first_class_index_kind(self) -> None:
        self.assertIn("analyst_decision_sidecar", SEARCH_DIRS)
        related = set(RELATED_KIND_MAP["analyst_decision_sidecar"])
        self.assertIn("packet_quality_report", related)
        self.assertIn("unique_review_packets", related)
        self.assertIn("packet_group_drilldown", related)
        self.assertIn("analyst_handoff_bundle", related)

    def test_gate_trace_audit_is_first_class_index_kind(self) -> None:
        self.assertIn("gate_trace_availability_audit", SEARCH_DIRS)
        related = set(RELATED_KIND_MAP["gate_trace_availability_audit"])
        self.assertIn("source_schema_repair_plan", related)
        self.assertIn("unique_review_packets", related)
        self.assertIn("packet_quality_report", related)
        self.assertIn("analyst_handoff_bundle", related)

    def test_false_positive_explanation_report_is_first_class_index_kind(self) -> None:
        self.assertIn("false_positive_explanation_report", SEARCH_DIRS)
        related = set(RELATED_KIND_MAP["false_positive_explanation_report"])
        self.assertIn("false_positive_library", related)
        self.assertIn("packet_quality_report", related)
        self.assertIn("unique_review_packets", related)
        self.assertIn("analyst_handoff_bundle", related)

    def test_false_positive_guardrail_audit_is_first_class_index_kind(self) -> None:
        self.assertIn("false_positive_guardrail_audit", SEARCH_DIRS)
        related = set(RELATED_KIND_MAP["false_positive_guardrail_audit"])
        self.assertIn("false_positive_library", related)
        self.assertIn("false_positive_explanation_report", related)
        self.assertIn("candidate_recall_diagnostic", related)
        self.assertIn("analyst_decision_sidecar", related)

    def test_evidence_limitation_digest_is_first_class_index_kind(self) -> None:
        self.assertIn("analyst_evidence_limitation_digest", SEARCH_DIRS)
        related = set(RELATED_KIND_MAP["analyst_evidence_limitation_digest"])
        self.assertIn("packet_quality_report", related)
        self.assertIn("candidate_recall_diagnostic", related)
        self.assertIn("gate_trace_availability_audit", related)
        self.assertIn("false_positive_guardrail_audit", related)

    def test_review_artifact_freshness_report_is_first_class_index_kind(self) -> None:
        self.assertIn("review_artifact_freshness_report", SEARCH_DIRS)
        related = set(RELATED_KIND_MAP["review_artifact_freshness_report"])
        self.assertIn("artifact_manifest", related)
        self.assertIn("analyst_handoff_bundle", related)
        self.assertIn("packet_quality_report", related)
        self.assertIn("ui_offline_implementation_preflight", related)

    def test_analyst_readiness_cycle_summary_is_first_class_index_kind(self) -> None:
        self.assertIn("analyst_readiness_cycle_summary", SEARCH_DIRS)
        related = set(RELATED_KIND_MAP["analyst_readiness_cycle_summary"])
        self.assertIn("analyst_evidence_limitation_digest", related)
        self.assertIn("candidate_recall_diagnostic", related)
        self.assertIn("false_positive_guardrail_audit", related)
        self.assertIn("review_artifact_freshness_report", related)

    def test_new_autonomous_safe_diagnostics_are_first_class_index_kinds(self) -> None:
        for kind in (
            "local_known_case_benchmark",
            "benchmark_labeling_workbench",
            "benchmark_label_readiness",
            "benchmark_label_priority_queue",
            "benchmark_label_priority_template",
            "benchmark_label_handoff_pack",
            "benchmark_label_worksheet",
            "benchmark_label_action_pack",
            "benchmark_label_csv_preflight",
            "benchmark_label_expectation_report",
            "benchmark_label_completion_status",
            "benchmark_label_cycle",
            "autonomous_branch_decision_report",
            "event_forensic_performance_audit",
            "event_forensic_performance_rfc",
            "event_forensic_trade_collection_profile",
            "event_forensic_perf001_progress_spec",
            "event_forensic_perf001_implementation_report",
            "event_forensic_scope_semantics_audit",
            "archive_visibility_doc_drift_audit",
            "offline_timeline_coverage_audit",
            "offline_timeline_template_pack",
            "offline_timeline_csv_validation",
            "ui_runtime_dependency_audit",
            "ui_offline_readiness_plan",
            "ui_offline_asset_manifest",
            "ui_offline_implementation_preflight",
            "direct_script_import_audit",
            "direct_script_cli_smoke_audit",
            "test_coverage_inventory_audit",
            "autonomous_progress_chain",
            "autonomous_change_log",
        ):
            self.assertIn(kind, SEARCH_DIRS)
            self.assertIn(kind, RELATED_KIND_MAP)
        chain_related = set(RELATED_KIND_MAP["autonomous_progress_chain"])
        self.assertIn("local_known_case_benchmark", chain_related)
        self.assertIn("benchmark_labeling_workbench", chain_related)
        self.assertIn("benchmark_label_readiness", chain_related)
        self.assertIn("benchmark_label_priority_queue", chain_related)
        self.assertIn("benchmark_label_priority_template", chain_related)
        self.assertIn("benchmark_label_handoff_pack", chain_related)
        self.assertIn("autonomous_branch_decision_report", chain_related)
        self.assertIn("event_forensic_performance_audit", chain_related)
        self.assertIn("event_forensic_performance_rfc", chain_related)
        self.assertIn("event_forensic_trade_collection_profile", chain_related)
        self.assertIn("event_forensic_perf001_progress_spec", chain_related)
        self.assertIn("event_forensic_perf001_implementation_report", chain_related)
        self.assertIn("event_forensic_scope_semantics_audit", chain_related)
        self.assertIn("ui_runtime_dependency_audit", chain_related)
        self.assertIn("ui_offline_readiness_plan", chain_related)
        self.assertIn("ui_offline_asset_manifest", chain_related)
        self.assertIn("ui_offline_implementation_preflight", chain_related)
        self.assertIn("autonomous_change_log", chain_related)
        self.assertIn("benchmark_labeling_workbench", RELATED_KIND_MAP["local_known_case_benchmark"])
        self.assertIn("benchmark_label_readiness", RELATED_KIND_MAP["benchmark_labeling_workbench"])
        self.assertIn("benchmark_label_priority_queue", RELATED_KIND_MAP["benchmark_labeling_workbench"])
        self.assertIn("benchmark_label_priority_queue", RELATED_KIND_MAP["benchmark_label_readiness"])
        self.assertIn("benchmark_label_priority_template", SEARCH_DIRS)
        self.assertIn("benchmark_label_priority_template", RELATED_KIND_MAP["benchmark_label_priority_queue"])
        self.assertIn("benchmark_label_handoff_pack", SEARCH_DIRS)
        self.assertIn("benchmark_label_handoff_pack", RELATED_KIND_MAP["benchmark_label_priority_queue"])
        self.assertIn("benchmark_label_worksheet", SEARCH_DIRS)
        self.assertIn("benchmark_label_worksheet", RELATED_KIND_MAP["benchmark_label_priority_template"])
        self.assertIn("benchmark_label_worksheet", RELATED_KIND_MAP["benchmark_label_handoff_pack"])
        self.assertIn("benchmark_label_action_pack", SEARCH_DIRS)
        self.assertIn("benchmark_label_action_pack", RELATED_KIND_MAP["benchmark_label_worksheet"])
        self.assertIn("benchmark_label_action_pack", RELATED_KIND_MAP["benchmark_label_completion_status"])
        self.assertIn("benchmark_label_csv_preflight", SEARCH_DIRS)
        self.assertIn("benchmark_label_csv_preflight", RELATED_KIND_MAP["benchmark_label_action_pack"])
        self.assertIn("benchmark_label_csv_preflight", RELATED_KIND_MAP["benchmark_label_completion_status"])
        self.assertIn("benchmark_label_expectation_report", SEARCH_DIRS)
        self.assertIn("benchmark_label_expectation_report", RELATED_KIND_MAP["benchmark_label_readiness"])
        self.assertIn("benchmark_label_expectation_report", RELATED_KIND_MAP["benchmark_label_completion_status"])
        self.assertIn("benchmark_label_completion_status", SEARCH_DIRS)
        self.assertIn("benchmark_label_completion_status", RELATED_KIND_MAP["benchmark_label_priority_template"])
        self.assertIn("benchmark_label_completion_status", RELATED_KIND_MAP["benchmark_label_handoff_pack"])
        self.assertIn("benchmark_label_cycle", SEARCH_DIRS)
        self.assertIn("benchmark_label_cycle", RELATED_KIND_MAP["benchmark_label_expectation_report"])
        self.assertIn("benchmark_label_cycle", RELATED_KIND_MAP["autonomous_progress_chain"])
        self.assertIn("autonomous_branch_decision_report", SEARCH_DIRS)
        self.assertIn("benchmark_label_priority_queue", RELATED_KIND_MAP["autonomous_branch_decision_report"])
        self.assertIn("ui_offline_asset_manifest", RELATED_KIND_MAP["ui_runtime_dependency_audit"])
        self.assertIn("ui_offline_asset_manifest", RELATED_KIND_MAP["ui_offline_readiness_plan"])
        self.assertIn("ui_offline_implementation_preflight", RELATED_KIND_MAP["ui_runtime_dependency_audit"])
        self.assertIn("ui_offline_implementation_preflight", RELATED_KIND_MAP["ui_offline_asset_manifest"])
        self.assertIn("offline_timeline_coverage_audit", RELATED_KIND_MAP["analyst_readiness_cycle_summary"])
        self.assertIn("offline_timeline_coverage_audit", RELATED_KIND_MAP["autonomous_progress_chain"])
        self.assertIn("offline_timeline_template_pack", RELATED_KIND_MAP["offline_timeline_coverage_audit"])
        self.assertIn("offline_timeline_template_pack", RELATED_KIND_MAP["autonomous_progress_chain"])
        self.assertIn("offline_timeline_csv_validation", RELATED_KIND_MAP["offline_timeline_template_pack"])
        self.assertIn("offline_timeline_csv_validation", RELATED_KIND_MAP["autonomous_progress_chain"])
        self.assertIn("direct_script_import_audit", RELATED_KIND_MAP["autonomous_progress_chain"])
        self.assertIn("autonomous_progress_chain", RELATED_KIND_MAP["direct_script_import_audit"])
        self.assertIn("direct_script_cli_smoke_audit", RELATED_KIND_MAP["direct_script_import_audit"])
        self.assertIn("direct_script_cli_smoke_audit", RELATED_KIND_MAP["autonomous_progress_chain"])
        self.assertIn("direct_script_import_audit", RELATED_KIND_MAP["direct_script_cli_smoke_audit"])
        self.assertIn("test_coverage_inventory_audit", RELATED_KIND_MAP["direct_script_cli_smoke_audit"])
        self.assertIn("test_coverage_inventory_audit", RELATED_KIND_MAP["autonomous_progress_chain"])


if __name__ == "__main__":
    unittest.main()
