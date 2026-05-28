from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.archive_visibility_doc_drift_audit import build_audit as build_doc_drift_audit
from tools.autonomous_branch_decision_report import build_report as build_branch_decision_report
from tools.autonomous_progress_chain import build_chain
from tools.benchmark_label_readiness_gate import build_readiness, write_outputs as write_label_readiness_outputs
from tools.benchmark_label_priority_queue import build_queue as build_label_priority_queue
from tools.benchmark_label_priority_template import build_template as build_label_priority_template
from tools.benchmark_label_handoff_pack import build_handoff as build_label_handoff_pack
from tools.benchmark_label_worksheet import build_worksheet as build_label_worksheet
from tools.benchmark_label_action_pack import build_action_pack as build_label_action_pack
from tools.benchmark_label_cycle import build_cycle as build_label_cycle
from tools.benchmark_label_csv_preflight import build_preflight as build_label_csv_preflight
from tools.benchmark_label_expectation_report import build_expectation_report as build_label_expectation_report
from tools.benchmark_label_completion_status import build_status as build_label_completion_status
from tools.benchmark_case_level_template import build_case_level_artifacts
from tools.direct_script_import_audit import build_audit as build_direct_script_import_audit
from tools.direct_script_cli_smoke_audit import build_audit as build_direct_script_cli_smoke_audit
from tools.test_coverage_inventory_audit import build_audit as build_test_coverage_inventory_audit
from tools.benchmark_labeling_workbench import build_workbench, write_outputs as write_workbench_outputs
from tools.event_forensic_performance_audit import build_audit as build_performance_audit
from tools.event_forensic_performance_rfc import build_rfc as build_performance_rfc
from tools.event_forensic_scope_semantics_audit import build_audit as build_scope_audit
from tools.event_forensic_perf001_progress_spec import build_spec as build_perf001_progress_spec
from tools.event_forensic_trade_collection_profile import build_profile as build_trade_collection_profile
from tools.local_known_case_benchmark import build_benchmark, write_outputs as write_benchmark_outputs
from tools.offline_timeline_coverage_audit import build_audit as build_offline_timeline_audit
from tools.offline_timeline_csv_validator import validate_csv as validate_offline_timeline_csv
from tools.offline_timeline_template_pack import build_template_pack as build_offline_timeline_template_pack
from tools.ui_offline_readiness_plan import build_plan as build_ui_offline_plan
from tools.ui_offline_asset_manifest import build_manifest as build_ui_offline_asset_manifest
from tools.ui_offline_implementation_preflight import build_preflight as build_ui_offline_preflight
from tools.ui_runtime_dependency_audit import build_audit as build_ui_audit


class AutonomousSafeDiagnosticsTests(unittest.TestCase):
    def test_known_case_benchmark_uses_saved_packets_without_model_changes(self) -> None:
        payload = build_benchmark(
            packet_payload={
                "packets": [
                    {
                        "packetId": "p1",
                        "wallet": "0xabc",
                        "market": "Will example happen?",
                        "conditionId": "cond-1",
                        "strongRisk": True,
                        "hardEvidenceReview": False,
                    }
                ]
            },
            event_forensic_root=Path("/does/not/exist"),
        )
        self.assertEqual(payload["summary"]["rowCount"], 1)
        self.assertEqual(payload["benchmarkRows"][0]["benchmarkStatus"], "candidate_needs_human_label")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertIn("Do not", payload["benchmarkRows"][0]["forbiddenUse"])

    def test_known_case_benchmark_outputs_valid_json(self) -> None:
        payload = build_benchmark(packet_payload={"packets": []}, event_forensic_root=Path("/does/not/exist"))
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_benchmark_outputs(payload, Path(tmp))
            loaded = json.loads(Path(outputs["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(loaded["artifactType"], "local_known_case_benchmark_scaffold")
            self.assertTrue(Path(outputs["markdown_path"]).exists())

    def test_event_forensic_performance_audit_classifies_funding_bottleneck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "event_forensic_20260505_000000"
            run_dir.mkdir()
            (run_dir / "event_analysis.json").write_text(
                json.dumps(
                    {
                        "parent_event_slug": "example-event",
                        "summary": {"raw_trade_count": 10, "candidate_trade_count": 2, "truncated_market_count": 1},
                        "performance": {
                            "total_seconds": 150,
                            "prefetch_funding_context_seconds": 100,
                            "validationFundingStatus": "rpc_failure_limit_hit",
                        },
                    }
                ),
                encoding="utf-8",
            )
            payload = build_performance_audit(Path(tmp))
        self.assertEqual(payload["summary"]["runCount"], 1)
        self.assertEqual(payload["summary"]["fundingRpcBlockedRunCount"], 1)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_archive_visibility_doc_drift_audit_is_read_only(self) -> None:
        payload = build_doc_drift_audit()
        self.assertIn("summary", payload)
        self.assertGreaterEqual(payload["summary"]["checkCount"], 6)
        self.assertGreaterEqual(payload["summary"]["contractCheckCount"], 4)
        self.assertEqual(payload["summary"]["staleArchiveHardHidePhraseCount"], 0)
        self.assertFalse(payload["summary"]["docsRequireVisibilityReconciliation"])
        self.assertFalse(payload["summary"]["archiveVisibilityChanged"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_archive_visibility_doc_drift_audit_detects_stale_hard_hide_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "risk_level_scoring.md"
            code = root / "archive_scanner.py"
            doc.write_text(
                "\n".join(
                    [
                        "archive mode annotate-not-hide",
                        "excluded_cases compatibility",
                        "якщо ні, вона йде в `Excluded`, навіть якщо score високий",
                    ]
                ),
                encoding="utf-8",
            )
            code.write_text(
                "\n".join(
                    [
                        "visibility_tier = 'Secondary review'",
                        "visible_inclusion_status = visibility_tier",
                        "excluded_cases = []",
                        "exclusion_reason = \"Promoted to secondary review rather than hidden.\"",
                        "def _visibility_tier_for_case(case): pass",
                    ]
                ),
                encoding="utf-8",
            )

            payload = build_doc_drift_audit(doc, code)

        self.assertGreater(payload["summary"]["staleArchiveHardHidePhraseCount"], 0)
        self.assertTrue(payload["summary"]["docsRequireVisibilityReconciliation"])
        stale_rows = [row for row in payload["driftRows"] if row["checkId"] == "ARCHIVE-NO-HARD-HIDE-001"]
        self.assertEqual(len(stale_rows), 1)
        self.assertTrue(stale_rows[0]["driftObserved"])
        self.assertFalse(payload["summary"]["archiveVisibilityChanged"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_offline_timeline_coverage_audit_reports_missing_timeline_files_without_behavior_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_offline_timeline_audit([Path(tmp) / ".inspoly"], [])

        self.assertEqual(payload["summary"]["coverageStatus"], "no_local_timeline_files")
        self.assertEqual(payload["summary"]["existingTimelineFileCount"], 0)
        self.assertFalse(payload["summary"]["timelineDataChanged"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_offline_timeline_coverage_audit_counts_local_rows_and_saved_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / ".inspoly"
            data_dir.mkdir()
            (data_dir / "event_timelines.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "condition_id": "cond-1",
                                "timeline_id": "tl-1",
                                "public_knowledge_at": "2026-01-01T00:00:00Z",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            review_dir = root / "review_packets"
            review_dir.mkdir()
            (review_dir / "unique_review_packets_20260506_000000.json").write_text(
                json.dumps(
                    {
                        "packets": [
                            {
                                "packetId": "p1",
                                "raw_metrics": {
                                    "offline_timeline_matched": "Yes",
                                    "timeline_id": "tl-1",
                                    "public_knowledge_at": "2026-01-01T00:00:00+00:00",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            payload = build_offline_timeline_audit(
                [data_dir],
                [(review_dir, "unique_review_packets_*.json")],
            )

        self.assertEqual(payload["summary"]["coverageStatus"], "timeline_coverage_observed")
        self.assertEqual(payload["summary"]["existingTimelineFileCount"], 1)
        self.assertEqual(payload["summary"]["timelineRowCount"], 1)
        self.assertEqual(payload["summary"]["offlineTimelineMatchedYesCount"], 1)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_offline_timeline_template_pack_is_header_only_and_human_curated(self) -> None:
        payload = build_offline_timeline_template_pack(
            {"summary": {"coverageStatus": "no_local_timeline_files"}}
        )

        self.assertEqual(payload["summary"]["sourceCoverageStatus"], "no_local_timeline_files")
        self.assertGreaterEqual(payload["summary"]["templateFieldCount"], 10)
        self.assertEqual(payload["summary"]["templateRowsPreFilled"], 0)
        self.assertTrue(payload["summary"]["humanCurationRequired"])
        self.assertFalse(payload["summary"]["externalFeedsAdded"])
        self.assertFalse(payload["summary"]["timelineDataChanged"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_offline_timeline_csv_validator_accepts_header_only_template_without_runtime_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "offline_event_timelines_template.csv"
            path.write_text(
                ",".join(
                    [
                        "timeline_id",
                        "condition_id",
                        "market_id",
                        "market_slug",
                        "slug",
                        "event_slug",
                        "question",
                        "question_contains",
                        "event_timezone",
                        "broad_report_at",
                        "official_confirmation_at",
                        "public_outcome_at",
                        "stale_resolution",
                        "reality_oracle_gap_label",
                        "timeline_source",
                        "source_note",
                        "curator",
                        "review_status",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = validate_offline_timeline_csv(path)

        self.assertEqual(payload["summary"]["validationStatus"], "template_only_no_rows")
        self.assertEqual(payload["summary"]["rowCount"], 0)
        self.assertFalse(payload["summary"]["runtimeDataChanged"])
        self.assertFalse(payload["summary"]["externalFeedsAdded"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_offline_timeline_csv_validator_flags_invalid_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "offline_event_timelines_bad.csv"
            path.write_text(
                "\n".join(
                    [
                        "timeline_id,condition_id,market_id,market_slug,slug,event_slug,question,question_contains,event_timezone,broad_report_at,official_confirmation_at,public_outcome_at,stale_resolution,reality_oracle_gap_label,timeline_source,source_note,curator,review_status",
                        "tl-1,,,,,,,,Not/AZone,not-a-time,,,maybe,,,curator,unknown",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = validate_offline_timeline_csv(path)

        self.assertEqual(payload["summary"]["validationStatus"], "invalid_rows_present")
        self.assertEqual(payload["summary"]["invalidRowCount"], 1)
        self.assertIn("missing_match_identifier", payload["rowResults"][0]["errors"])
        self.assertFalse(payload["summary"]["timelineDataChanged"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_direct_script_import_audit_detects_missing_repo_root_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools_dir = Path(tmp) / "tools"
            tools_dir.mkdir()
            (tools_dir / "bad_tool.py").write_text(
                "from app.scanner import _score_trade\n\nif __name__ == \"__main__\":\n    pass\n",
                encoding="utf-8",
            )
            (tools_dir / "good_tool.py").write_text(
                "\n".join(
                    [
                        "from pathlib import Path",
                        "import sys",
                        "REPO_ROOT = Path(__file__).resolve().parents[1]",
                        "if str(REPO_ROOT) not in sys.path:",
                        "    sys.path.insert(0, str(REPO_ROOT))",
                        "from tools.model_behavior_audit import collect_records",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = build_direct_script_import_audit(tools_dir)

        self.assertEqual(payload["summary"]["repoRootImportToolCount"], 2)
        self.assertEqual(payload["summary"]["missingGuardToolCount"], 1)
        self.assertEqual(payload["summary"]["directRunRiskStatus"], "missing_repo_root_path_guards")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertFalse(payload["summary"]["gatesChanged"])

    def test_direct_script_import_audit_passes_guarded_repo_root_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools_dir = Path(tmp) / "tools"
            tools_dir.mkdir()
            (tools_dir / "guarded_tool.py").write_text(
                "\n".join(
                    [
                        "from pathlib import Path",
                        "import sys",
                        "REPO_ROOT = Path(__file__).resolve().parents[1]",
                        "if str(REPO_ROOT) not in sys.path:",
                        "    sys.path.insert(0, str(REPO_ROOT))",
                        "from app.config import load_runtime_env",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = build_direct_script_import_audit(tools_dir)

        self.assertEqual(payload["summary"]["missingGuardToolCount"], 0)
        self.assertEqual(payload["summary"]["directRunRiskStatus"], "repo_root_import_guards_ok")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_direct_script_cli_smoke_audit_runs_argparse_help_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools_dir = root / "tools"
            tools_dir.mkdir()
            (tools_dir / "ok_tool.py").write_text(
                "\n".join(
                    [
                        "import argparse",
                        "def main():",
                        "    parser = argparse.ArgumentParser(description='ok')",
                        "    parser.parse_args()",
                        "    return 0",
                        "if __name__ == \"__main__\":",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = build_direct_script_cli_smoke_audit(
                tools_dir,
                repo_root=root,
                per_tool_timeout_seconds=2,
            )

        self.assertEqual(payload["summary"]["argparseCliCandidateCount"], 1)
        self.assertEqual(payload["summary"]["helpOkCount"], 1)
        self.assertEqual(payload["summary"]["directCliRiskStatus"], "direct_cli_help_ok")
        self.assertFalse(payload["summary"]["networkCallsIntended"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_direct_script_cli_smoke_audit_reports_help_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools_dir = root / "tools"
            tools_dir.mkdir()
            (tools_dir / "broken_tool.py").write_text(
                "\n".join(
                    [
                        "import argparse",
                        "import sys",
                        "def main():",
                        "    parser = argparse.ArgumentParser(description='broken')",
                        "    if '--help' in sys.argv:",
                        "        return 2",
                        "    parser.parse_args()",
                        "    return 0",
                        "if __name__ == \"__main__\":",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = build_direct_script_cli_smoke_audit(
                tools_dir,
                repo_root=root,
                per_tool_timeout_seconds=2,
            )

        self.assertEqual(payload["summary"]["helpFailureCount"], 1)
        self.assertEqual(payload["summary"]["directCliRiskStatus"], "direct_cli_help_issues")
        self.assertEqual(len(payload["issueRows"]), 1)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_test_coverage_inventory_audit_counts_direct_test_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app").mkdir()
            (root / "tools").mkdir()
            (root / "tests").mkdir()
            (root / "app" / "scanner.py").write_text("", encoding="utf-8")
            (root / "app" / "event_forensic.py").write_text("", encoding="utf-8")
            (root / "tools" / "review_output_index.py").write_text("", encoding="utf-8")
            (root / "tests" / "test_sample.py").write_text(
                "from app.scanner import _score_trade\nfrom tools.review_output_index import build_review_output_index\n",
                encoding="utf-8",
            )

            payload = build_test_coverage_inventory_audit(root)

        self.assertEqual(payload["summary"]["appModuleCount"], 2)
        self.assertEqual(payload["summary"]["appModuleWithDirectTestReferenceCount"], 1)
        self.assertEqual(payload["summary"]["toolModuleWithDirectTestReferenceCount"], 1)
        self.assertEqual(payload["summary"]["highPriorityAppModuleWithoutDirectTestReferenceCount"], 1)
        self.assertEqual(payload["summary"]["coverageInventoryStatus"], "high_priority_app_modules_unreferenced")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_ui_runtime_dependency_audit_reports_current_boot_risk(self) -> None:
        payload = build_ui_audit([Path("app/browser_ui.html"), Path("app/browser_event_forensic_ui.html")])
        self.assertEqual(payload["summary"]["runtimeRequiredDependencyCount"], 0)
        self.assertEqual(payload["summary"]["cdnRuntimeDependencyCount"], 0)
        self.assertIn(payload["summary"]["offlineRisk"], {"low", "high"})
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_summarizes_without_behavior_change(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "unlabeled_template_only", "usableLabeledRows": 0}},
                "benchmark_label_priority_queue": {"summary": {"queueRowCount": 10}},
                "benchmark_label_priority_template": {"summary": {"templateRowCount": 10}},
                "benchmark_label_handoff_pack": {"summary": {"queueRowCount": 10}},
                "benchmark_label_worksheet": {"summary": {"worksheetRowCount": 10}},
                "benchmark_label_action_pack": {"summary": {"humanActionRequired": True}},
                "benchmark_label_csv_preflight": {"summary": {"preflightStatus": "structure_ok_unlabeled"}},
                "benchmark_label_completion_status": {
                    "summary": {"candidateCsvCount": 1, "selectedCompletionStatus": "blank_or_unlabeled_template", "selectedUsableLabelRows": 0}
                },
                "benchmark_label_expectation_report": {"summary": {"expectationStatus": "no_human_labels_available", "usableLabeledRows": 0}},
                "benchmark_label_cycle": {"summary": {"cycleStatus": "waiting_for_human_labels", "usableLabeledRows": 0}},
                "event_forensic_performance_audit": {"summary": {"runCount": 2, "slowRunCountOver120s": 1}},
                "event_forensic_performance_rfc": {"summary": {"proposalCount": 3}},
                "event_forensic_trade_collection_profile": {"summary": {"runCount": 2, "truncatedRunCount": 1}},
                "event_forensic_perf001_progress_spec": {"summary": {"proposedFieldCount": 9}},
                "event_forensic_perf001_implementation_report": {"summary": {"persistedPerformanceFieldsAdded": True}},
                "archive_visibility_doc_drift_audit": {"summary": {"checkCount": 3, "driftObservedCount": 0}},
                "offline_timeline_coverage_audit": {"summary": {"coverageStatus": "no_local_timeline_files"}},
                "offline_timeline_template_pack": {"summary": {"templateFieldCount": 18, "templateRowsPreFilled": 0}},
                "offline_timeline_csv_validation": {"summary": {"validationStatus": "template_only_no_rows"}},
                "ui_runtime_dependency_audit": {"summary": {"offlineRisk": "high"}},
                "direct_script_import_audit": {
                    "summary": {
                        "directRunRiskStatus": "repo_root_import_guards_ok",
                        "missingGuardToolCount": 0,
                        "repoRootImportToolCount": 9,
                    }
                },
                "direct_script_cli_smoke_audit": {
                    "summary": {
                        "directCliRiskStatus": "direct_cli_help_ok",
                        "helpFailureCount": 0,
                        "helpTimeoutCount": 0,
                    }
                },
                "test_coverage_inventory_audit": {
                    "summary": {
                        "coverageInventoryStatus": "high_priority_app_modules_unreferenced",
                        "highPriorityAppModuleWithoutDirectTestReferenceCount": 2,
                    }
                },
                "autonomous_branch_decision_report": {"summary": {"selectedBranch": "human_benchmark_labeling"}},
                "analyst_readiness_cycle_summary": {"summary": {"readinessClassification": "not_ready_corpus_too_cache_only"}},
                "operator_rpc_recovery_package": {"configuration_status": "no_new_operator_rpc_config_detected"},
            }
        )
        self.assertEqual(payload["summary"]["benchmarkRows"], 3)
        self.assertEqual(payload["summary"]["benchmarkLabelReadinessStatus"], "unlabeled_template_only")
        self.assertEqual(payload["summary"]["benchmarkLabelPriorityQueueRows"], 10)
        self.assertEqual(payload["summary"]["benchmarkLabelPriorityTemplateRows"], 10)
        self.assertEqual(payload["summary"]["benchmarkLabelHandoffRows"], 10)
        self.assertEqual(payload["summary"]["benchmarkLabelWorksheetRows"], 10)
        self.assertTrue(payload["summary"]["benchmarkLabelActionPackPresent"])
        self.assertEqual(payload["summary"]["benchmarkLabelCsvPreflightStatus"], "structure_ok_unlabeled")
        self.assertEqual(payload["summary"]["benchmarkLabelCompletionStatus"], "blank_or_unlabeled_template")
        self.assertEqual(payload["summary"]["benchmarkLabelExpectationStatus"], "no_human_labels_available")
        self.assertEqual(payload["summary"]["benchmarkLabelCycleStatus"], "waiting_for_human_labels")
        self.assertEqual(payload["summary"]["autonomousBranchSelectedBranch"], "human_benchmark_labeling")
        self.assertEqual(payload["summary"]["tradeCollectionProfileRuns"], 2)
        self.assertEqual(payload["summary"]["perf001ProgressSpecProposedFields"], 9)
        self.assertTrue(payload["summary"]["perf001ImplementationReportPresent"])
        self.assertEqual(payload["summary"]["directScriptImportAuditStatus"], "repo_root_import_guards_ok")
        self.assertEqual(payload["summary"]["directScriptImportRepoRootImportTools"], 9)
        self.assertEqual(payload["summary"]["directScriptCliSmokeAuditStatus"], "direct_cli_help_ok")
        self.assertEqual(payload["summary"]["testCoverageInventoryStatus"], "high_priority_app_modules_unreferenced")
        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-004")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertIn("Stop before changing detector scoring", payload["stopConditions"][0])
        self.assertTrue(any(item["promptId"] == "NEXT-005" for item in payload["nextPromptOptions"]))
        self.assertTrue(any(item["promptId"] == "NEXT-006" for item in payload["nextPromptOptions"]))
        self.assertTrue(any(item["promptId"] == "NEXT-020" for item in payload["nextPromptOptions"]))
        self.assertTrue(any(item["promptId"] == "NEXT-021" for item in payload["nextPromptOptions"]))
        self.assertTrue(any(item["promptId"] == "NEXT-022" for item in payload["nextPromptOptions"]))
        self.assertTrue(any(item["promptId"] == "NEXT-023" for item in payload["nextPromptOptions"]))

    def test_autonomous_progress_chain_recommends_label_readiness_when_missing(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "event_forensic_performance_audit": {"summary": {"runCount": 2, "slowRunCountOver120s": 1}},
            }
        )
        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-006")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_label_priority_queue_when_labels_missing(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "unlabeled_template_only", "usableLabeledRows": 0}},
            }
        )
        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-010")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_label_handoff_when_queue_exists(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "unlabeled_template_only", "usableLabeledRows": 0}},
                "benchmark_label_priority_queue": {"summary": {"queueRowCount": 10}},
            }
        )
        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-011")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_label_handoff_when_template_exists(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "unlabeled_template_only", "usableLabeledRows": 0}},
                "benchmark_label_priority_queue": {"summary": {"queueRowCount": 10}},
                "benchmark_label_priority_template": {"summary": {"templateRowCount": 10}},
            }
        )
        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-012")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_label_worksheet_when_handoff_exists(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "unlabeled_template_only", "usableLabeledRows": 0}},
                "benchmark_label_priority_queue": {"summary": {"queueRowCount": 10}},
                "benchmark_label_priority_template": {"summary": {"templateRowCount": 10}},
                "benchmark_label_handoff_pack": {"summary": {"queueRowCount": 10}},
            }
        )
        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-014")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_trade_profile_when_rfc_exists(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "unlabeled_template_only", "usableLabeledRows": 0}},
                "benchmark_label_priority_queue": {"summary": {"queueRowCount": 10}},
                "benchmark_label_priority_template": {"summary": {"templateRowCount": 10}},
                "benchmark_label_handoff_pack": {"summary": {"queueRowCount": 10}},
                "benchmark_label_worksheet": {"summary": {"worksheetRowCount": 10}},
                "benchmark_label_completion_status": {"summary": {"candidateCsvCount": 1}},
                "event_forensic_performance_audit": {"summary": {"runCount": 2, "slowRunCountOver120s": 1}},
                "event_forensic_performance_rfc": {"summary": {"proposalCount": 3}},
            }
        )
        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-003")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_perf001_spec_when_profile_exists(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "unlabeled_template_only", "usableLabeledRows": 0}},
                "benchmark_label_priority_queue": {"summary": {"queueRowCount": 10}},
                "benchmark_label_priority_template": {"summary": {"templateRowCount": 10}},
                "benchmark_label_handoff_pack": {"summary": {"queueRowCount": 10}},
                "benchmark_label_worksheet": {"summary": {"worksheetRowCount": 10}},
                "benchmark_label_completion_status": {"summary": {"candidateCsvCount": 1}},
                "event_forensic_performance_audit": {"summary": {"runCount": 2, "slowRunCountOver120s": 1}},
                "event_forensic_performance_rfc": {"summary": {"proposalCount": 3}},
                "event_forensic_trade_collection_profile": {"summary": {"runCount": 2, "truncatedRunCount": 1}},
            }
        )
        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-007")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_direct_import_audit_after_ui_preflight(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "unlabeled_template_only", "usableLabeledRows": 0}},
                "benchmark_label_priority_queue": {"summary": {"queueRowCount": 10}},
                "benchmark_label_priority_template": {"summary": {"templateRowCount": 10}},
                "benchmark_label_handoff_pack": {"summary": {"queueRowCount": 10}},
                "benchmark_label_worksheet": {"summary": {"worksheetRowCount": 10}},
                "benchmark_label_completion_status": {"summary": {"candidateCsvCount": 1}},
                "event_forensic_performance_audit": {"summary": {"runCount": 2, "slowRunCountOver120s": 1}},
                "event_forensic_performance_rfc": {"summary": {"proposalCount": 3}},
                "event_forensic_trade_collection_profile": {"summary": {"runCount": 2, "truncatedRunCount": 1}},
                "event_forensic_perf001_progress_spec": {"summary": {"proposedFieldCount": 9}},
                "event_forensic_perf001_implementation_report": {"summary": {"persistedPerformanceFieldsAdded": True}},
                "archive_visibility_doc_drift_audit": {"summary": {"checkCount": 3}},
                "offline_timeline_coverage_audit": {"summary": {"coverageStatus": "no_local_timeline_files"}},
                "offline_timeline_template_pack": {"summary": {"templateFieldCount": 18}},
                "offline_timeline_csv_validation": {"summary": {"validationStatus": "template_only_no_rows"}},
                "ui_runtime_dependency_audit": {"summary": {"offlineRisk": "high"}},
                "ui_offline_readiness_plan": {"summary": {"planStepCount": 3}},
                "ui_offline_asset_manifest": {"summary": {"uniqueRuntimeAssetCount": 4}},
                "ui_offline_implementation_preflight": {"summary": {"preflightStatus": "blocked_missing_runtime_assets"}},
            }
        )
        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-020")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_cli_smoke_after_direct_import_audit(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "unlabeled_template_only", "usableLabeledRows": 0}},
                "benchmark_label_priority_queue": {"summary": {"queueRowCount": 10}},
                "benchmark_label_priority_template": {"summary": {"templateRowCount": 10}},
                "benchmark_label_handoff_pack": {"summary": {"queueRowCount": 10}},
                "benchmark_label_worksheet": {"summary": {"worksheetRowCount": 10}},
                "benchmark_label_completion_status": {"summary": {"candidateCsvCount": 1}},
                "event_forensic_performance_audit": {"summary": {"runCount": 2, "slowRunCountOver120s": 1}},
                "event_forensic_performance_rfc": {"summary": {"proposalCount": 3}},
                "event_forensic_trade_collection_profile": {"summary": {"runCount": 2, "truncatedRunCount": 1}},
                "event_forensic_perf001_progress_spec": {"summary": {"proposedFieldCount": 9}},
                "event_forensic_perf001_implementation_report": {"summary": {"persistedPerformanceFieldsAdded": True}},
                "archive_visibility_doc_drift_audit": {"summary": {"checkCount": 3}},
                "offline_timeline_coverage_audit": {"summary": {"coverageStatus": "no_local_timeline_files"}},
                "offline_timeline_template_pack": {"summary": {"templateFieldCount": 18}},
                "offline_timeline_csv_validation": {"summary": {"validationStatus": "template_only_no_rows"}},
                "ui_runtime_dependency_audit": {"summary": {"offlineRisk": "high"}},
                "ui_offline_readiness_plan": {"summary": {"planStepCount": 3}},
                "ui_offline_asset_manifest": {"summary": {"uniqueRuntimeAssetCount": 4}},
                "ui_offline_implementation_preflight": {"summary": {"preflightStatus": "blocked_missing_runtime_assets"}},
                "direct_script_import_audit": {"summary": {"directRunRiskStatus": "repo_root_import_guards_ok"}},
            }
        )
        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-021")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_test_coverage_inventory_after_cli_smoke(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "unlabeled_template_only", "usableLabeledRows": 0}},
                "benchmark_label_priority_queue": {"summary": {"queueRowCount": 10}},
                "benchmark_label_priority_template": {"summary": {"templateRowCount": 10}},
                "benchmark_label_handoff_pack": {"summary": {"queueRowCount": 10}},
                "benchmark_label_worksheet": {"summary": {"worksheetRowCount": 10}},
                "benchmark_label_completion_status": {"summary": {"candidateCsvCount": 1}},
                "event_forensic_performance_audit": {"summary": {"runCount": 2, "slowRunCountOver120s": 1}},
                "event_forensic_performance_rfc": {"summary": {"proposalCount": 3}},
                "event_forensic_trade_collection_profile": {"summary": {"runCount": 2, "truncatedRunCount": 1}},
                "event_forensic_perf001_progress_spec": {"summary": {"proposedFieldCount": 9}},
                "event_forensic_perf001_implementation_report": {"summary": {"persistedPerformanceFieldsAdded": True}},
                "archive_visibility_doc_drift_audit": {"summary": {"checkCount": 3}},
                "offline_timeline_coverage_audit": {"summary": {"coverageStatus": "no_local_timeline_files"}},
                "offline_timeline_template_pack": {"summary": {"templateFieldCount": 18}},
                "offline_timeline_csv_validation": {"summary": {"validationStatus": "template_only_no_rows"}},
                "ui_runtime_dependency_audit": {"summary": {"offlineRisk": "high"}},
                "ui_offline_readiness_plan": {"summary": {"planStepCount": 3}},
                "ui_offline_asset_manifest": {"summary": {"uniqueRuntimeAssetCount": 4}},
                "ui_offline_implementation_preflight": {"summary": {"preflightStatus": "blocked_missing_runtime_assets"}},
                "direct_script_import_audit": {"summary": {"directRunRiskStatus": "repo_root_import_guards_ok"}},
                "direct_script_cli_smoke_audit": {"summary": {"directCliRiskStatus": "direct_cli_help_ok"}},
            }
        )
        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-022")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_benchmark_labeling_workbench_creates_human_template_only(self) -> None:
        payload = build_workbench(
            {
                "benchmarkRows": [
                    {
                        "localCaseId": "LOCAL-PACKET-0001",
                        "sourceType": "unique_review_packet",
                        "eventSlug": "example",
                        "wallet": "0xabc",
                    }
                ]
            }
        )
        self.assertEqual(payload["summary"]["labelTemplateRowCount"], 1)
        row = payload["labelRows"][0]
        self.assertEqual(row["benchmarkStatus"], "awaiting_human_label")
        self.assertIn("expectedAnalystDisposition", row["labelFields"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_benchmark_labeling_workbench_writes_csv_json_md(self) -> None:
        payload = build_workbench({"benchmarkRows": [{"localCaseId": "LOCAL-1"}]})
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_workbench_outputs(payload, Path(tmp))
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())
            self.assertTrue(Path(outputs["csv_path"]).exists())

    def test_benchmark_label_readiness_gate_rejects_unlabeled_template(self) -> None:
        payload = build_readiness(
            {
                "labelRows": [
                    {
                        "localCaseId": "LOCAL-1",
                        "labelFields": {"expectedAnalystDisposition": "", "humanLabelConfidence": ""},
                    }
                ]
            }
        )
        self.assertEqual(payload["summary"]["readinessStatus"], "unlabeled_template_only")
        self.assertEqual(payload["summary"]["usableLabeledRows"], 0)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertIn("Stop before treating unlabeled", payload["stopConditions"][0])

    def test_benchmark_label_readiness_gate_accepts_reporting_only_labels(self) -> None:
        payload = build_readiness(
            {
                "labelRows": [
                    {
                        "localCaseId": "LOCAL-1",
                        "labelFields": {
                            "expectedAnalystDisposition": "plausible_insider_style",
                            "humanLabelConfidence": "high",
                            "freshValidationRequired": "yes",
                        },
                    }
                ]
            },
            min_usable_labels=1,
        )
        self.assertEqual(payload["summary"]["readinessStatus"], "ready_for_reporting_regression_only")
        self.assertEqual(payload["summary"]["usableLabeledRows"], 1)
        self.assertFalse(payload["summary"]["candidateAdmissionChanged"])
        self.assertIn("reporting_regression_expectation_only", payload["readinessRows"][0]["allowedUse"])

    def test_benchmark_label_readiness_outputs_valid_json(self) -> None:
        payload = build_readiness({"labelRows": []})
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_label_readiness_outputs(payload, Path(tmp))
            loaded = json.loads(Path(outputs["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(loaded["artifactType"], "benchmark_label_readiness_gate")
            self.assertTrue(Path(outputs["markdown_path"]).exists())

    def test_benchmark_label_priority_queue_does_not_assign_labels(self) -> None:
        payload = build_label_priority_queue(
            {
                "labelRows": [
                    {
                        "localCaseId": "LOCAL-1",
                        "sourceType": "unique_review_packet",
                        "market": "Example market",
                        "wallet": "0xabc",
                        "observedLabels": {"strongRisk": True, "hardEvidenceReview": True, "overlap": True},
                        "labelFields": {"expectedAnalystDisposition": "", "humanLabelConfidence": ""},
                    },
                    {
                        "localCaseId": "LOCAL-2",
                        "sourceType": "event_forensic_run",
                        "eventSlug": "example-event",
                        "observedLabels": {"forensicSuspiciousTradeCount": 5, "truncatedMarketCount": 1},
                        "labelFields": {"expectedAnalystDisposition": "", "humanLabelConfidence": ""},
                    },
                ]
            },
            limit=2,
        )
        self.assertEqual(payload["summary"]["queueRowCount"], 2)
        self.assertEqual(payload["priorityRows"][0]["priorityClass"], "high")
        self.assertEqual(payload["priorityRows"][0]["allowedUse"], "manual_label_queue_only")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertIn("Do not use this priority queue as scoring", payload["priorityRows"][0]["forbiddenUse"])
        self.assertNotIn("event_scope_count_expectation", payload["priorityRows"][0]["recommendedHumanQuestion"])
        self.assertNotIn("insufficient_context", payload["priorityRows"][0]["recommendedHumanQuestion"])
        self.assertIn("ignore_not_benchmark", payload["priorityRows"][0]["recommendedHumanQuestion"])

    def test_benchmark_label_priority_template_is_readiness_gate_compatible(self) -> None:
        payload = build_label_priority_template(
            {
                "priorityRows": [
                    {
                        "queueRank": 1,
                        "localCaseId": "LOCAL-1",
                        "sourceType": "unique_review_packet",
                        "market": "Example",
                        "wallet": "0xabc",
                        "priorityClass": "high",
                        "labelPriorityScore": 90,
                        "priorityReasons": ["Strong Risk packet is high-value."],
                    }
                ]
            }
        )
        self.assertEqual(payload["summary"]["templateRowCount"], 1)
        self.assertEqual(payload["summary"]["humanLabelsAssignedByThisTool"], 0)
        self.assertTrue(payload["summary"]["readyForBenchmarkReadinessGate"])
        row = payload["templateRows"][0]
        self.assertIn("expectedAnalystDisposition", row)
        self.assertEqual(row["freshValidationRequired"], "yes")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_branch_decision_report_selects_human_labeling_without_rpc_config(self) -> None:
        payload = build_branch_decision_report(
            {
                "autonomous_progress_chain": {
                    "summary": {
                        "readinessClassification": "not_ready_corpus_too_cache_only",
                        "operatorRpcStatus": "existing_env_config_rechecked_no_new_operator_approved_rpc_configuration_detected",
                        "operatorDecisionRequired": True,
                    }
                },
                "operator_rpc_recovery_package": {
                    "configuration_status": "existing_env_config_rechecked_no_new_operator_approved_rpc_configuration_detected",
                    "operator_decision_required": True,
                },
                "gate_decision_readiness": {
                    "readinessClassification": "not_ready_corpus_too_cache_only",
                    "recommendation": "strong_risk_gate_review_not_ready_cache_only",
                },
                "benchmark_label_priority_queue": {"summary": {"queueRowCount": 30}},
                "benchmark_label_priority_template": {"summary": {"templateRowCount": 30}},
                "benchmark_label_readiness": {"summary": {"usableLabeledRows": 0}},
                "ui_offline_asset_manifest": {"summary": {"missingRuntimeAssetCount": 4, "uiRuntimeChanged": False}},
                "ui_offline_implementation_preflight": {
                    "summary": {"preflightStatus": "blocked_missing_runtime_assets", "missingRuntimeAssetCount": 4}
                },
            }
        )
        self.assertEqual(payload["summary"]["selectedBranch"], "human_benchmark_labeling")
        self.assertEqual(payload["summary"]["benchmarkPriorityQueueRows"], 30)
        self.assertEqual(payload["summary"]["benchmarkPriorityTemplateRows"], 30)
        self.assertEqual(payload["summary"]["uiOfflineImplementationPreflightStatus"], "blocked_missing_runtime_assets")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertIn("benchmark_label_priority_template", payload["selectedNextPrompt"])

    def test_branch_decision_report_uses_ui_preflight_when_ui_branch_is_next(self) -> None:
        payload = build_branch_decision_report(
            {
                "gate_decision_readiness": {"readinessClassification": "not_ready_corpus_too_cache_only"},
                "operator_rpc_recovery_package": {
                    "configuration_status": "existing_env_config_rechecked_no_new_operator_approved_rpc_configuration_detected",
                    "operator_decision_required": True,
                },
                "benchmark_label_priority_queue": {"summary": {"queueRowCount": 0}},
                "benchmark_label_readiness": {"summary": {"usableLabeledRows": 0}},
                "ui_offline_asset_manifest": {"summary": {"missingRuntimeAssetCount": 4, "uiRuntimeChanged": False}},
                "ui_offline_implementation_preflight": {
                    "summary": {"preflightStatus": "blocked_missing_runtime_assets", "missingRuntimeAssetCount": 4}
                },
            }
        )

        self.assertEqual(payload["summary"]["selectedBranch"], "ui_offline_implementation_requires_approval")
        self.assertEqual(payload["summary"]["uiOfflineImplementationPreflightStatus"], "blocked_missing_runtime_assets")
        self.assertIn("ui_offline_implementation_preflight", payload["selectedNextPrompt"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_branch_decision_report_prefers_rpc_when_config_present(self) -> None:
        payload = build_branch_decision_report(
            {
                "gate_decision_readiness": {"readinessClassification": "not_ready_corpus_too_cache_only"},
                "operator_rpc_recovery_package": {
                    "configuration_status": "operator_rpc_config_detected_needs_probe",
                    "operator_decision_required": False,
                },
                "benchmark_label_priority_queue": {"summary": {"queueRowCount": 30}},
                "benchmark_label_readiness": {"summary": {"usableLabeledRows": 0}},
            }
        )
        self.assertEqual(payload["summary"]["selectedBranch"], "operator_rpc_recovery")
        self.assertIn("bounded recovery", payload["selectedNextPrompt"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_benchmark_label_handoff_pack_assigns_no_labels(self) -> None:
        payload = build_label_handoff_pack(
            {
                "priorityRows": [
                    {
                        "queueRank": 1,
                        "localCaseId": "LOCAL-1",
                        "priorityClass": "high",
                        "labelPriorityScore": 90,
                        "sourceType": "unique_review_packet",
                        "market": "Example",
                        "wallet": "0xabc",
                        "priorityReasons": ["Strong Risk packet is high-value."],
                    }
                ]
            },
            template_path=Path("known_case_benchmarks/benchmark_label_priority_template_test.json"),
        )
        self.assertEqual(payload["summary"]["queueRowCount"], 1)
        self.assertEqual(payload["summary"]["humanLabelsAssignedByThisTool"], 0)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertIn("likely_false_positive", payload["labelingInstructions"]["allowedValues"]["expectedAnalystDisposition"])
        self.assertNotIn("event_scope_count_expectation", payload["labelingInstructions"]["allowedValues"]["expectedAnalystDisposition"])
        self.assertNotIn("insufficient_context", payload["labelingInstructions"]["allowedValues"]["expectedAnalystDisposition"])
        self.assertIn("ignore_not_benchmark", payload["labelingInstructions"]["allowedValues"]["expectedAnalystDisposition"])
        self.assertIn("Do not infer labels automatically.", payload["stopConditions"][0])

    def test_benchmark_label_worksheet_adds_human_context_without_labels(self) -> None:
        payload = build_label_worksheet(
            {
                "allowedValues": {
                    "expectedAnalystDisposition": [
                        "likely_false_positive",
                        "plausible_insider_style",
                        "needs_fresh_validation",
                        "inconclusive",
                        "reporting_only_control",
                        "ignore_not_benchmark",
                    ],
                    "humanLabelConfidence": ["low", "medium", "high"],
                },
                "templateRows": [
                    {
                        "queueRank": 1,
                        "localCaseId": "LOCAL-1",
                        "sourceType": "unique_review_packet",
                        "market": "Example",
                        "wallet": "0xabc",
                        "priorityClass": "high",
                        "labelPriorityScore": 90,
                        "priorityReasons": "Strong Risk packet is high-value. | HER packet helps validate routing.",
                    }
                ],
            },
            completion_payload={"summary": {"selectedCompletionStatus": "blank_or_unlabeled_template", "selectedUsableLabelRows": 0}},
        )
        self.assertEqual(payload["summary"]["worksheetRowCount"], 1)
        self.assertEqual(payload["summary"]["labelsAssignedByThisTool"], 0)
        self.assertEqual(payload["summary"]["completionStatusAtGeneration"], "blank_or_unlabeled_template")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        row = payload["worksheetRows"][0]
        self.assertEqual(row["blankLabelFields"]["expectedAnalystDisposition"], "")
        self.assertIn("likely_false_positive", row["allowedAnalystDispositions"])
        self.assertTrue(any("Strong Risk" in item for item in row["evidenceFocus"]))
        self.assertIn("Do not infer labels automatically.", payload["stopConditions"][0])

    def test_benchmark_label_action_pack_collects_manual_files_without_labels(self) -> None:
        payload = build_label_action_pack(
            {
                "priorityTemplateJson": {
                    "allowedValues": {
                        "expectedAnalystDisposition": ["likely_false_positive", "plausible_insider_style"],
                        "humanLabelConfidence": ["low", "medium", "high"],
                    },
                    "summary": {"templateRowCount": 30},
                },
                "worksheetJson": {"summary": {"worksheetRowCount": 30}},
                "handoffJson": {"summary": {"queueRowCount": 30}},
                "completionStatusJson": {
                    "summary": {
                        "selectedCompletionStatus": "blank_or_unlabeled_template",
                        "selectedUsableLabelRows": 0,
                        "invalidLabelRows": 0,
                        "selectedLabelsCsvPath": "/tmp/template.csv",
                    }
                },
                "readinessJson": {"summary": {"readinessStatus": "unlabeled_template_only", "usableLabeledRows": 0}},
            }
        )
        self.assertEqual(payload["summary"]["templateRowCount"], 30)
        self.assertEqual(payload["summary"]["worksheetRowCount"], 30)
        self.assertTrue(payload["summary"]["humanActionRequired"])
        self.assertEqual(payload["summary"]["labelsAssignedByThisTool"], 0)
        self.assertIn("templateCsvToEdit", payload["filesToOpen"])
        self.assertIn("benchmark_label_csv_preflight.py", payload["commandsAfterFilling"][0])
        self.assertIn("benchmark_label_completion_status.py", payload["commandsAfterFilling"][1])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertIn("Do not infer labels automatically.", payload["stopConditions"][0])

    def test_benchmark_label_csv_preflight_catches_structure_and_value_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.csv"
            labels = root / "labels.csv"
            template.write_text(
                "localCaseId,sourceType,eventSlug,market,conditionId,wallet,expectedAnalystDisposition,humanLabelConfidence,freshValidationRequired\n"
                "LOCAL-1,unique_review_packet,event,Market,cond,0xabc,,,yes\n",
                encoding="utf-8",
            )
            labels.write_text(
                "localCaseId,sourceType,eventSlug,market,conditionId,wallet,expectedAnalystDisposition,humanLabelConfidence,freshValidationRequired\n"
                "LOCAL-1,unique_review_packet,event,Changed,cond,0xabc,event_scope_count_expectation,high,maybe\n",
                encoding="utf-8",
            )
            payload = build_label_csv_preflight(template_csv_path=template, labels_csv_path=labels)
        self.assertEqual(payload["summary"]["preflightStatus"], "structure_or_values_need_fix")
        self.assertEqual(payload["summary"]["invalidLabelRows"], 1)
        self.assertEqual(payload["summary"]["immutableFieldMismatchCount"], 1)
        self.assertFalse(payload["summary"]["readinessGateRecommended"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertEqual(payload["summary"]["labelsAssignedByThisTool"], 0)

    def test_benchmark_label_csv_preflight_allows_ready_labeled_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.csv"
            labels = root / "labels.csv"
            rows = [
                f"LOCAL-{idx},unique_review_packet,event,Market {idx},cond-{idx},0xabc,likely_false_positive,high,yes"
                for idx in range(12)
            ]
            template_rows = [
                f"LOCAL-{idx},unique_review_packet,event,Market {idx},cond-{idx},0xabc,,,yes"
                for idx in range(12)
            ]
            header = "localCaseId,sourceType,eventSlug,market,conditionId,wallet,expectedAnalystDisposition,humanLabelConfidence,freshValidationRequired\n"
            template.write_text(header + "\n".join(template_rows) + "\n", encoding="utf-8")
            labels.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
            payload = build_label_csv_preflight(template_csv_path=template, labels_csv_path=labels)
        self.assertEqual(payload["summary"]["preflightStatus"], "ready_for_readiness_gate")
        self.assertEqual(payload["summary"]["usableLabelRows"], 12)
        self.assertTrue(payload["summary"]["readinessGateRecommended"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_benchmark_label_expectation_report_summarizes_human_labels_without_behavior_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            labels = Path(tmp) / "labels.csv"
            labels.write_text(
                "localCaseId,expectedAnalystDisposition,expectedDetectorDisposition,humanLabelConfidence,humanFalsePositiveReason,humanInsiderStyleReason,freshValidationRequired,notes\n"
                "LOCAL-1,likely_false_positive,reporting_only_note,high,High volume public user,,yes,review note\n"
                "LOCAL-2,plausible_insider_style,rfc_only_review_candidate,medium,,Early winning entry,no,review note\n",
                encoding="utf-8",
            )
            payload = build_label_expectation_report(
                {
                    "labelRows": [
                        {
                            "localCaseId": "LOCAL-1",
                            "sourceType": "unique_review_packet",
                            "market": "Example",
                            "wallet": "0xabc",
                            "observedLabels": {"strongRisk": True, "hardEvidenceReview": False, "overlap": False},
                            "labelFields": {},
                        },
                        {
                            "localCaseId": "LOCAL-2",
                            "sourceType": "unique_review_packet",
                            "market": "Example",
                            "wallet": "0xdef",
                            "observedLabels": {"strongRisk": False, "hardEvidenceReview": False, "overlap": False},
                            "labelFields": {},
                        },
                    ]
                },
                labels_csv_path=labels,
                preflight_payload={"summary": {"preflightStatus": "partially_labeled_structure_ok"}},
                readiness_payload={"summary": {"readinessStatus": "partially_labeled_needs_more_rows"}},
            )
        self.assertEqual(payload["summary"]["expectationStatus"], "partial_reporting_expectations")
        self.assertEqual(payload["summary"]["usableLabeledRows"], 2)
        self.assertEqual(payload["summary"]["dispositionCounts"]["likely_false_positive"], 1)
        self.assertEqual(payload["summary"]["dispositionCounts"]["plausible_insider_style"], 1)
        self.assertIn("human_likely_false_positive_on_observed_high_risk_row", payload["summary"]["reviewFlagCounts"])
        self.assertIn("human_plausible_insider_without_observed_strong_or_her", payload["summary"]["reviewFlagCounts"])
        self.assertEqual(payload["summary"]["labelsAssignedByThisTool"], 0)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertIn("reporting_regression_expectation_only", payload["expectationRows"][0]["allowedUse"])

    def test_benchmark_label_completion_status_distinguishes_blank_and_filled_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "benchmark_label_priority_template_20260506_000000.csv").write_text(
                "localCaseId,expectedAnalystDisposition,humanLabelConfidence\n"
                "LOCAL-1,,\n"
                "LOCAL-2,,\n",
                encoding="utf-8",
            )
            (root / "human_benchmark_labels_20260506_000001.csv").write_text(
                "localCaseId,expectedAnalystDisposition,humanLabelConfidence\n"
                "LOCAL-1,likely_false_positive,high\n"
                "LOCAL-2,plausible_insider_style,medium\n",
                encoding="utf-8",
            )
            payload = build_label_completion_status(input_dir=root)
        self.assertEqual(payload["summary"]["candidateCsvCount"], 2)
        self.assertEqual(payload["summary"]["candidateFilledCsvCount"], 1)
        self.assertEqual(payload["summary"]["selectedCompletionStatus"], "partially_labeled_needs_more_rows")
        self.assertEqual(payload["summary"]["selectedUsableLabelRows"], 2)
        self.assertTrue(payload["summary"]["readinessGateRecommended"])
        selected = next(row for row in payload["csvRows"] if row["appearsHumanFilled"])
        self.assertTrue(selected["hasRequiredColumns"])
        self.assertIn("benchmark_label_readiness_gate.py", selected["recommendedReadinessCommand"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_benchmark_label_completion_status_rejects_incompatible_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "human_benchmark_labels_20260506_000001.csv").write_text(
                "localCaseId,expectedAnalystDisposition,humanLabelConfidence\n"
                "LOCAL-1,event_scope_count_expectation,high\n",
                encoding="utf-8",
            )
            payload = build_label_completion_status(input_dir=root)
        self.assertEqual(payload["summary"]["selectedCompletionStatus"], "invalid_labels_need_fix")
        self.assertEqual(payload["summary"]["invalidLabelRows"], 1)
        self.assertFalse(payload["summary"]["readinessGateRecommended"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_benchmark_label_cycle_runs_full_blank_workflow_without_assigning_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "benchmark_labeling_workbench_20260506_000000.json").write_text(
                json.dumps(
                    {
                        "summary": {"labelTemplateRowCount": 2},
                        "labelRows": [
                            {"localCaseId": "LOCAL-1", "labelFields": {}},
                            {"localCaseId": "LOCAL-2", "labelFields": {}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (root / "benchmark_label_priority_template_20260506_000000.csv").write_text(
                "localCaseId,sourceType,eventSlug,market,conditionId,wallet,expectedAnalystDisposition,humanLabelConfidence\n"
                "LOCAL-1,packet,event,Market,cond,0xabc,,\n"
                "LOCAL-2,packet,event,Market,cond,0xdef,,\n",
                encoding="utf-8",
            )

            payload = build_label_cycle(input_dir=root, output_dir=root, min_usable_labels=2)

        self.assertEqual(payload["summary"]["cycleStatus"], "waiting_for_human_labels")
        self.assertEqual(payload["summary"]["usableLabeledRows"], 0)
        self.assertTrue(payload["summary"]["humanActionRequired"])
        self.assertEqual(payload["summary"]["labelsAssignedByThisTool"], 0)
        self.assertIn("completionStatus", payload["componentArtifacts"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_benchmark_label_cycle_accepts_ready_human_csv_as_reporting_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "benchmark_labeling_workbench_20260506_000000.json").write_text(
                json.dumps(
                    {
                        "summary": {"labelTemplateRowCount": 2},
                        "labelRows": [
                            {"localCaseId": "LOCAL-1", "labelFields": {}},
                            {"localCaseId": "LOCAL-2", "labelFields": {}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            template = root / "benchmark_label_priority_template_20260506_000000.csv"
            template.write_text(
                "localCaseId,sourceType,eventSlug,market,conditionId,wallet,expectedAnalystDisposition,humanLabelConfidence\n"
                "LOCAL-1,packet,event,Market,cond,0xabc,,\n"
                "LOCAL-2,packet,event,Market,cond,0xdef,,\n",
                encoding="utf-8",
            )
            labels = root / "human_benchmark_labels_20260506_000001.csv"
            labels.write_text(
                "localCaseId,sourceType,eventSlug,market,conditionId,wallet,expectedAnalystDisposition,humanLabelConfidence\n"
                "LOCAL-1,packet,event,Market,cond,0xabc,likely_false_positive,high\n"
                "LOCAL-2,packet,event,Market,cond,0xdef,plausible_insider_style,medium\n",
                encoding="utf-8",
            )

            payload = build_label_cycle(
                input_dir=root,
                output_dir=root,
                template_csv_path=template,
                labels_csv_path=labels,
                min_usable_labels=2,
            )

        self.assertEqual(payload["summary"]["cycleStatus"], "ready_for_reporting_regression_only")
        self.assertEqual(payload["summary"]["readinessStatus"], "ready_for_reporting_regression_only")
        self.assertEqual(payload["summary"]["usableLabeledRows"], 2)
        self.assertEqual(payload["summary"]["labelsAssignedByThisTool"], 0)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_event_forensic_performance_rfc_is_rfc_only(self) -> None:
        payload = build_performance_rfc(
            {
                "summary": {
                    "runCount": 10,
                    "slowRunCountOver120s": 2,
                    "fundingRpcBlockedRunCount": 1,
                    "bottleneckClassCounts": {"event_trade_collection_dominant": 4},
                }
            }
        )
        self.assertEqual(payload["summary"]["proposalCount"], 3)
        self.assertFalse(payload["summary"]["implementationApproved"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertIn("Do not change Strong Risk gates", payload["forbiddenImplementation"][1])

    def test_event_forensic_trade_collection_profile_reports_truncation_without_behavior_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "event_forensic_20260506_000000"
            bundle = run_dir / "raw_event_bundle"
            bundle.mkdir(parents=True)
            (run_dir / "event_analysis.json").write_text(
                json.dumps(
                    {
                        "parent_event_slug": "example-event",
                        "analysis_scope": "market",
                        "selected_condition_id": "cond-1",
                        "summary": {
                            "raw_trade_count": 2,
                            "candidate_trade_count": 1,
                            "analysis_market_count": 1,
                            "total_event_market_count": 3,
                            "truncated_market_count": 1,
                        },
                        "performance": {"collect_event_trades_seconds": 40, "market_fetch_workers": 6},
                    }
                ),
                encoding="utf-8",
            )
            (bundle / "trades.json").write_text(
                json.dumps(
                    [
                        {"condition_id": "cond-1", "slug": "m1"},
                        {"condition_id": "cond-1", "slug": "m1"},
                    ]
                ),
                encoding="utf-8",
            )
            (bundle / "analysis_markets.json").write_text(
                json.dumps([{"conditionId": "cond-1", "slug": "m1", "question": "Market 1"}]),
                encoding="utf-8",
            )
            (bundle / "event_markets.json").write_text(
                json.dumps([{"conditionId": "cond-1", "slug": "m1", "question": "Market 1"}]),
                encoding="utf-8",
            )
            payload = build_trade_collection_profile(Path(tmp))
        self.assertEqual(payload["summary"]["runCount"], 1)
        self.assertEqual(payload["summary"]["truncatedRunCount"], 1)
        self.assertEqual(payload["profileRows"][0]["collectionRiskClass"], "truncated_collection_high_cost")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_event_forensic_perf001_progress_spec_is_reporting_only(self) -> None:
        payload = build_perf001_progress_spec(
            {"summary": {"runCount": 100, "truncatedRunCount": 91, "slowCollectionRunCountOver30s": 16}}
        )
        self.assertEqual(payload["summary"]["implementationPriority"], "high")
        self.assertGreaterEqual(payload["summary"]["proposedFieldCount"], 8)
        self.assertFalse(payload["summary"]["implementationApproved"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertIn("Do not skip markets", payload["forbiddenImplementation"][0])

    def test_ui_offline_readiness_plan_is_plan_only(self) -> None:
        payload = build_ui_offline_plan(
            {
                "summary": {"offlineRisk": "high", "runtimeRequiredDependencyCount": 4},
                "dependencyRows": [{"runtimeRequiredForUiBoot": True, "url": "https://unpkg.com/react"}],
            }
        )
        self.assertEqual(payload["summary"]["planStepCount"], 3)
        self.assertFalse(payload["summary"]["implementationApproved"])
        self.assertFalse(payload["summary"]["uiRuntimeChanged"])
        self.assertIn("Do not rewrite", payload["forbiddenWithoutApproval"][0])

    def test_ui_offline_asset_manifest_is_manifest_only(self) -> None:
        payload = build_ui_offline_asset_manifest(
            {
                "summary": {"offlineRisk": "high", "runtimeRequiredDependencyCount": 2},
                "dependencyRows": [
                    {
                        "file": "/tmp/browser_ui.html",
                        "runtimeRequiredForUiBoot": True,
                        "analystNavigationOnly": False,
                        "dependencyKind": "react_cdn",
                        "url": "https://unpkg.com/react@18/umd/react.development.js",
                    },
                    {
                        "file": "/tmp/browser_ui.html",
                        "runtimeRequiredForUiBoot": False,
                        "analystNavigationOnly": True,
                        "dependencyKind": "analyst_external_link",
                        "url": "https://polymarket.com/profile/0xabc",
                    },
                ],
            },
            {"summary": {"planStepCount": 3}},
        )
        self.assertEqual(payload["summary"]["uniqueRuntimeAssetCount"], 1)
        self.assertEqual(payload["summary"]["analystNavigationLinkCount"], 1)
        self.assertFalse(payload["summary"]["implementationApproved"])
        self.assertFalse(payload["summary"]["uiRuntimeChanged"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertIn("Downloading or vendoring", payload["loaderBoundary"]["requiresSeparateApproval"][0])

    def test_ui_offline_implementation_preflight_blocks_missing_assets_without_runtime_change(self) -> None:
        payload = build_ui_offline_preflight(
            {"summary": {"offlineRisk": "high", "runtimeRequiredDependencyCount": 1}},
            {"summary": {"implementationApproved": False}},
            {
                "summary": {
                    "offlineRisk": "high",
                    "runtimeRequiredDependencyCount": 1,
                    "uniqueRuntimeAssetCount": 1,
                    "missingRuntimeAssetCount": 1,
                    "implementationApproved": False,
                },
                "assetRows": [
                    {
                        "assetId": "UI-ASSET-001",
                        "dependencyKind": "react_cdn",
                        "suggestedLocalPath": "app/vendor/react/react.development.js",
                        "targetExistsNow": False,
                        "requiredForOfflineBoot": True,
                        "approvalRequiredBeforeRuntimeChange": True,
                        "sourceFiles": ["app/browser_ui.html"],
                    }
                ],
            },
        )

        self.assertEqual(payload["summary"]["preflightStatus"], "blocked_missing_runtime_assets")
        self.assertEqual(payload["summary"]["missingRuntimeAssetCount"], 1)
        self.assertTrue(payload["summary"]["approvalRequiredBeforeRuntimeChange"])
        self.assertFalse(payload["summary"]["uiRuntimeChanged"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_ui_offline_implementation_preflight_handles_missing_optional_artifacts(self) -> None:
        payload = build_ui_offline_preflight({}, {}, {})

        self.assertEqual(payload["summary"]["preflightStatus"], "no_runtime_dependencies_detected")
        self.assertFalse(payload["summary"]["uiRuntimeChanged"])
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_ui_manifest_when_plan_exists(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "unlabeled_template_only", "usableLabeledRows": 0}},
                "benchmark_label_priority_queue": {"summary": {"queueRowCount": 10}},
                "benchmark_label_priority_template": {"summary": {"templateRowCount": 10}},
                "benchmark_label_handoff_pack": {"summary": {"queueRowCount": 10}},
                "benchmark_label_worksheet": {"summary": {"worksheetRowCount": 10}},
                "benchmark_label_completion_status": {"summary": {"candidateCsvCount": 1}},
                "event_forensic_performance_audit": {"summary": {"runCount": 2, "slowRunCountOver120s": 1}},
                "event_forensic_performance_rfc": {"summary": {"proposalCount": 3}},
                "event_forensic_trade_collection_profile": {"summary": {"runCount": 2, "truncatedRunCount": 1}},
                "event_forensic_perf001_progress_spec": {"summary": {"proposedFieldCount": 9}},
                "event_forensic_perf001_implementation_report": {"summary": {"persistedPerformanceFieldsAdded": True}},
                "archive_visibility_doc_drift_audit": {"summary": {"checkCount": 3, "driftObservedCount": 0}},
                "offline_timeline_coverage_audit": {"summary": {"coverageStatus": "no_local_timeline_files"}},
                "offline_timeline_template_pack": {"summary": {"templateFieldCount": 18, "templateRowsPreFilled": 0}},
                "offline_timeline_csv_validation": {"summary": {"validationStatus": "template_only_no_rows"}},
                "ui_runtime_dependency_audit": {"summary": {"offlineRisk": "high"}},
                "ui_offline_readiness_plan": {"summary": {"planStepCount": 3}},
            }
        )
        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-009")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_timeline_audit_when_missing(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "complete", "usableLabeledRows": 3}},
                "event_forensic_performance_audit": {"summary": {"runCount": 2, "slowRunCountOver120s": 0}},
                "event_forensic_performance_rfc": {"summary": {"proposalCount": 3}},
                "event_forensic_trade_collection_profile": {"summary": {"runCount": 2}},
                "event_forensic_perf001_progress_spec": {"summary": {"proposedFieldCount": 9}},
                "event_forensic_perf001_implementation_report": {"summary": {"persistedPerformanceFieldsAdded": True}},
                "archive_visibility_doc_drift_audit": {"summary": {"checkCount": 6, "driftObservedCount": 0}},
                "ui_runtime_dependency_audit": {"summary": {"offlineRisk": "high"}},
            }
        )

        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-017")
        self.assertEqual(payload["summary"]["offlineTimelineCoverageStatus"], "missing")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_timeline_template_when_no_local_timelines(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "complete", "usableLabeledRows": 3}},
                "event_forensic_performance_audit": {"summary": {"runCount": 2, "slowRunCountOver120s": 0}},
                "event_forensic_performance_rfc": {"summary": {"proposalCount": 3}},
                "event_forensic_trade_collection_profile": {"summary": {"runCount": 2}},
                "event_forensic_perf001_progress_spec": {"summary": {"proposedFieldCount": 9}},
                "event_forensic_perf001_implementation_report": {"summary": {"persistedPerformanceFieldsAdded": True}},
                "archive_visibility_doc_drift_audit": {"summary": {"checkCount": 6, "driftObservedCount": 0}},
                "offline_timeline_coverage_audit": {"summary": {"coverageStatus": "no_local_timeline_files"}},
                "ui_runtime_dependency_audit": {"summary": {"offlineRisk": "high"}},
            }
        )

        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-018")
        self.assertEqual(payload["summary"]["offlineTimelineCoverageStatus"], "no_local_timeline_files")
        self.assertEqual(payload["summary"]["offlineTimelineTemplateFieldCount"], 0)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_timeline_csv_validation_when_template_exists(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "complete", "usableLabeledRows": 3}},
                "event_forensic_performance_audit": {"summary": {"runCount": 2, "slowRunCountOver120s": 0}},
                "event_forensic_performance_rfc": {"summary": {"proposalCount": 3}},
                "event_forensic_trade_collection_profile": {"summary": {"runCount": 2}},
                "event_forensic_perf001_progress_spec": {"summary": {"proposedFieldCount": 9}},
                "event_forensic_perf001_implementation_report": {"summary": {"persistedPerformanceFieldsAdded": True}},
                "archive_visibility_doc_drift_audit": {"summary": {"checkCount": 6, "driftObservedCount": 0}},
                "offline_timeline_coverage_audit": {"summary": {"coverageStatus": "no_local_timeline_files"}},
                "offline_timeline_template_pack": {"summary": {"templateFieldCount": 18, "templateRowsPreFilled": 0}},
                "ui_runtime_dependency_audit": {"summary": {"offlineRisk": "high"}},
            }
        )

        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-019")
        self.assertEqual(payload["summary"]["offlineTimelineCsvValidationStatus"], "missing")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_autonomous_progress_chain_recommends_ui_preflight_when_manifest_exists(self) -> None:
        payload = build_chain(
            {
                "local_known_case_benchmark": {"summary": {"rowCount": 3}},
                "benchmark_labeling_workbench": {"summary": {"labelTemplateRowCount": 3}},
                "benchmark_label_readiness": {"summary": {"readinessStatus": "complete", "usableLabeledRows": 3}},
                "event_forensic_performance_audit": {"summary": {"runCount": 2, "slowRunCountOver120s": 0}},
                "event_forensic_performance_rfc": {"summary": {"proposalCount": 3}},
                "event_forensic_trade_collection_profile": {"summary": {"runCount": 2}},
                "event_forensic_perf001_progress_spec": {"summary": {"proposedFieldCount": 9}},
                "event_forensic_perf001_implementation_report": {"summary": {"persistedPerformanceFieldsAdded": True}},
                "archive_visibility_doc_drift_audit": {"summary": {"checkCount": 6, "driftObservedCount": 0}},
                "offline_timeline_coverage_audit": {"summary": {"coverageStatus": "no_local_timeline_files"}},
                "offline_timeline_template_pack": {"summary": {"templateFieldCount": 18, "templateRowsPreFilled": 0}},
                "offline_timeline_csv_validation": {"summary": {"validationStatus": "template_only_no_rows"}},
                "ui_runtime_dependency_audit": {"summary": {"offlineRisk": "high"}},
                "ui_offline_readiness_plan": {"summary": {"planStepCount": 3}},
                "ui_offline_asset_manifest": {"summary": {"uniqueRuntimeAssetCount": 4, "missingRuntimeAssetCount": 4}},
            }
        )

        self.assertEqual(payload["recommendedNextPromptId"], "NEXT-016")
        self.assertEqual(payload["summary"]["uiOfflineImplementationPreflightStatus"], "missing")
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_event_forensic_scope_semantics_audit_preserves_strict_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "event_forensic_20260505_000000"
            run_dir.mkdir()
            (run_dir / "event_analysis.json").write_text(
                json.dumps(
                    {
                        "selected_condition_id": "cond-1",
                        "parent_event_slug": "example-event",
                        "summary": {"analysis_market_count": 1, "total_event_market_count": 4},
                        "scope_note": "single market",
                    }
                ),
                encoding="utf-8",
            )
            payload = build_scope_audit(Path(tmp))
        self.assertEqual(payload["summary"]["singleMarketWithSiblingContextCount"], 1)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertIn("Keep single-market condition_id scope strict.", payload["recommendations"][0])

    def test_benchmark_case_level_template_uses_case_rows_without_human_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_path = root / "event_analysis.json"
            event_path.write_text(
                json.dumps(
                    {
                        "suspicious_trades": [
                            {
                                "id": "0x" + "1" * 64,
                                "wallet": "0xabc",
                                "username": "AnalystCandidate (Public-Handle)",
                                "parentEventSlug": "example-event",
                                "marketSlug": "example-market",
                                "conditionId": "cond-1",
                                "market": "Will example happen?",
                                "side": "Yes",
                                "winningOutcome": "Yes",
                                "price": 0.12,
                                "positionSize": 100,
                                "timestamp": "2026-01-01T00:00:00+00:00",
                                "finalEventJudgment": "Strong Risk: Retrospective",
                                "strongRiskGatePassed": "Yes",
                                "strongRiskExactGateBranch": "retrospective_event_forensic_gate",
                                "hardEvidenceReviewTier": "Hard Evidence Review",
                                "hardEvidenceSources": ["low_probability_early_winner"],
                                "fundingEvidenceGrade": "unknown",
                                "fundingTraceSkippedCount": 5,
                                "eventForensicScore": 91,
                                "eventForensicNotes": ["Saved event-forensic concern."],
                                "strongRiskSuppressorConflictReasons": ["high_volume_public_user"],
                                "outcomeKnown": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            selected_csv = root / "selected.csv"
            selected_csv.write_text(
                "\n".join(
                    [
                        "queueRank,localCaseId,sourceType,eventSlug,market,conditionId,wallet,sourceArtifact",
                        f"1,LOCAL-EVENT-0001,event_forensic_run,example-event,Will example happen?,cond-1,,{event_path}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            case_payload, reclass_payload = build_case_level_artifacts(
                selected_csv_path=selected_csv,
                review_packets_payload={
                    "packets": [
                        {
                            "packet_id": "packet_0001",
                            "group": "strong_risk",
                            "wallet": "0xdef",
                            "trade_id": "0x" + "2" * 64,
                            "condition_id": "cond-2",
                            "market": "Will packet happen?",
                            "judgment": "Strong Risk: Retrospective",
                            "funding_evidence_grade": "unknown",
                            "critical_field_warnings": [{"field": "hard_evidence_sources"}],
                            "false_positive_advisory": [{"pattern": "funding_unknown"}],
                        }
                    ]
                },
                max_rows=10,
            )

        self.assertGreaterEqual(case_payload["summary"]["caseLevelRowCount"], 2)
        self.assertEqual(
            case_payload["summary"]["caseLevelRowCount"],
            case_payload["summary"]["rowsWithWalletOrTradeIdentifiers"],
        )
        self.assertTrue(case_payload["summary"]["humanLabelFieldsRemainBlank"])
        self.assertEqual(case_payload["summary"]["labelsAssignedByThisTool"], 0)
        for row in case_payload["caseRows"]:
            self.assertTrue(row["wallet"] or row["tradeId"] or row["txHash"])
            self.assertEqual(row["expectedAnalystDisposition"], "")
            self.assertEqual(row["humanLabelConfidence"], "")
            self.assertEqual(row["expectedDetectorDisposition"], "")
            self.assertEqual(row["freshValidationRequired"], "")
        self.assertEqual(reclass_payload["summary"]["originalRowCount"], 1)
        self.assertTrue(reclass_payload["summary"]["eventRunRowsNotTreatedAsCaseLevelLabels"])
        self.assertEqual(
            reclass_payload["reclassificationRows"][0]["classification"],
            "convert_to_case_level_children",
        )
        self.assertFalse(case_payload["summary"]["modelBehaviorChanged"])

    def test_benchmark_case_level_template_handles_missing_event_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selected_csv = root / "selected.csv"
            selected_csv.write_text(
                "\n".join(
                    [
                        "queueRank,localCaseId,sourceType,eventSlug,market,conditionId,wallet,sourceArtifact",
                        f"1,LOCAL-EVENT-0001,event_forensic_run,example-event,Will example happen?,cond-1,,{root / 'missing.json'}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            case_payload, reclass_payload = build_case_level_artifacts(
                selected_csv_path=selected_csv,
                review_packets_payload={"packets": []},
                max_rows=10,
            )

        self.assertEqual(case_payload["summary"]["caseLevelRowCount"], 0)
        self.assertTrue(case_payload["summary"]["humanLabelFieldsRemainBlank"])
        self.assertEqual(case_payload["summary"]["labelsAssignedByThisTool"], 0)
        self.assertEqual(reclass_payload["summary"]["originalRowCount"], 1)
        self.assertEqual(
            reclass_payload["reclassificationRows"][0]["classification"],
            "needs_human_review",
        )
        self.assertTrue(reclass_payload["summary"]["eventRunRowsNotTreatedAsCaseLevelLabels"])
        self.assertFalse(case_payload["summary"]["modelBehaviorChanged"])


if __name__ == "__main__":
    unittest.main()
