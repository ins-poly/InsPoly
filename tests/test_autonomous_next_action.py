from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from tools.autonomous_next_action import (
    FORBIDDEN_PROMPT_PHRASES,
    OUTPUT_SECTIONS,
    build_action_pack,
    write_outputs as write_action_outputs,
)
from tools.gate_decision_readiness import write_outputs as write_readiness_outputs


class AutonomousNextActionTests(unittest.TestCase):
    def _write_inputs(
        self,
        root: Path,
        *,
        classification: str = "not_ready_corpus_too_cache_only",
        recommendation: str = "strong_risk_gate_review_not_ready_cache_only",
        consistency: str = "count_reporting_consistent",
        legacy_classification_key: bool = False,
    ) -> dict[str, Path]:
        output_dir = root / "validation_corpus_outputs"
        diagnostic_dir = root / "strong_risk_diagnostic_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        diagnostic_dir.mkdir(parents=True, exist_ok=True)
        corpus_path = output_dir / "post_v2_corpus_20260504_000000.json"
        prewarm_path = output_dir / "funding_cache_prewarm_20260504_000000.json"
        consistency_path = output_dir / "report_consistency_20260504_000000.json"
        diagnostic_path = diagnostic_dir / "strong_risk_gate_diagnostic_20260504_000000.json"
        readiness_path = output_dir / "gate_decision_readiness_20260504_000000.json"
        readiness_md = output_dir / "gate_decision_readiness_20260504_000000.md"
        memory_path = root / "PROJECT_MEMORY.md"

        corpus_payload = {
            "validationPolicy": "cache_only",
            "completed_targets": 32,
            "skipped_targets": 0,
            "aborted_targets": 0,
            "funding_enabled_targets": 0,
            "cache_only_targets": 28,
            "funding_blocked_targets": 0,
            "rawVisibleRows": 3857,
            "uniqueVisibleRows": 1758,
            "rawStrongRiskRows": 799,
            "uniqueStrongRiskRows": 396,
            "rawHardEvidenceReviewRows": 574,
            "uniqueHardEvidenceReviewRows": 217,
            "strongRiskDedupeRatio": 2.0177,
            "hardEvidenceReviewDedupeRatio": 2.6452,
        }
        prewarm_payload = {
            "funding_candidate_targets": 14,
            "wallet_time_windows_found": 4,
            "wallet_time_windows_attempted": 2,
            "cache_hits_observed": 0,
            "cache_misses_observed": 1,
            "cache_writes": 1,
            "rpc_failures": 1,
            "rate_limits": 0,
            "targets_left_unprewarmed": 48,
            "stop_reason": "trace_timeout",
            "prewarm_coverage_by_target_family": {
                "archive_politics_world": {"targets": 22, "windowsFound": 4, "windowsAttempted": 2}
            },
        }
        consistency_payload = {"classification": consistency}
        diagnostic_payload = {
            "rawStrongRiskRows": 799,
            "uniqueStrongRiskRows": 396,
            "strongRiskRowsWithGateTraceAvailable": 602,
            "strongRiskRowsWithoutGateTrace": 197,
            "freshUniqueGateLeakageCandidateRows": 0,
            "potentialGateLeakageCandidateRows": 592,
            "hardInvalidConditionCounts": {},
        }
        readiness_payload = {
            "generated_at": "2026-05-04T15:21:37+00:00",
            "recommendation": recommendation,
            "inputArtifacts": {
                "corpus_output": str(corpus_path),
                "prewarm_report": str(prewarm_path),
                "report_consistency": str(consistency_path),
                "strong_risk_diagnostic": str(diagnostic_path),
            },
            "corpusConfig": {
                "totalTargets": 52,
                "freshRerunnableTargets": 48,
                "archiveTargets": 24,
                "targetFamilyDistribution": {
                    "archive_politics_world": 24,
                    "politics_world_event_forensic": 17,
                    "sports_crypto": 4,
                },
            },
            "run": {
                "completedTargets": 32,
                "skippedTargets": 0,
                "abortedTargets": 0,
                "completedFreshRerunnableTargets": 28,
                "fundingEnabledTargets": 0,
                "cacheOnlyTargets": 28,
                "fundingBlockedTargets": 0,
                "rawVisibleRows": 3857,
                "uniqueVisibleRows": 1758,
                "rawStrongRiskRows": 799,
                "uniqueStrongRiskRows": 396,
                "strongRiskDedupeRatio": 2.0177,
                "rawHardEvidenceReviewRows": 574,
                "uniqueHardEvidenceReviewRows": 217,
                "hardEvidenceReviewDedupeRatio": 2.6452,
            },
            "strongRiskGateTrace": {
                "strongRiskRowsWithGateTrace": 602,
                "strongRiskGateTraceCoverage": 0.7534,
            },
            "funding": {
                "fundingCandidateTargets": 14,
                "tracesRequested": 2,
                "cacheHits": 0,
                "cacheMisses": 1,
                "cacheWrites": 1,
                "rpcFailures": 1,
                "rateLimits": 0,
                "targetsLeftUnprewarmed": 48,
                "stopReason": "trace_timeout",
                "prewarmCoverageByTargetFamily": prewarm_payload["prewarm_coverage_by_target_family"],
            },
            "reportConsistency": {"classification": consistency},
            "herInvalidConditionCounts": {},
            "freshUniqueGateLeakageCandidates": 0,
            "broadSavedFieldGateLeakageCandidates": 592,
        }
        if legacy_classification_key:
            readiness_payload["classification"] = classification
        else:
            readiness_payload["readinessClassification"] = classification

        corpus_path.write_text(json.dumps(corpus_payload), encoding="utf-8")
        prewarm_path.write_text(json.dumps(prewarm_payload), encoding="utf-8")
        consistency_path.write_text(json.dumps(consistency_payload), encoding="utf-8")
        diagnostic_path.write_text(json.dumps(diagnostic_payload), encoding="utf-8")
        readiness_path.write_text(json.dumps(readiness_payload), encoding="utf-8")
        readiness_md.write_text("# Gate Decision Readiness\n", encoding="utf-8")
        memory_path.write_text("# PROJECT_MEMORY\n", encoding="utf-8")
        return {
            "output_dir": output_dir,
            "readiness": readiness_path,
            "readiness_md": readiness_md,
            "corpus": corpus_path,
            "prewarm": prewarm_path,
            "consistency": consistency_path,
            "diagnostic": diagnostic_path,
            "memory": memory_path,
        }

    def _pack_for(self, paths: dict[str, Path]) -> dict:
        return build_action_pack(
            output_dir=paths["output_dir"],
            readiness_json_path=paths["readiness"],
            readiness_md_path=paths["readiness_md"],
            corpus_output_path=paths["corpus"],
            prewarm_path=paths["prewarm"],
            consistency_path=paths["consistency"],
            strong_risk_diagnostic_path=paths["diagnostic"],
            project_memory_path=paths["memory"],
        )

    def test_cache_only_routes_to_rpc_reliability_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(Path(tmp), classification="not_ready_corpus_too_cache_only")
            pack = self._pack_for(paths)
        self.assertEqual(set(pack), set(OUTPUT_SECTIONS))
        self.assertEqual(pack["decision"], "run_rpc_cache_reliability_path")
        self.assertIn("48-target auto-policy", pack["ready_to_copy_codex_prompt"])

    def test_cache_only_after_mixed_endpoint_trace_path_uses_rpc_reliability_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(Path(tmp), classification="not_ready_corpus_too_cache_only")
            trace_path = paths["output_dir"] / "trace_method_diagnostic_20260505_000000.json"
            trace_path.write_text(
                json.dumps(
                    {
                        "classification": "trace_method_path_available_with_endpoint_errors",
                        "recommended_next_step": "run_bounded_12_target_validation_smoke_with_endpoint_quarantine",
                        "endpoint_labels": ["polygon.publicnode.com", "polygon.drpc.org"],
                    }
                ),
                encoding="utf-8",
            )
            pack = self._pack_for(paths)
        prompt = pack["ready_to_copy_codex_prompt"]
        self.assertEqual(pack["decision"], "run_rpc_cache_reliability_path")
        self.assertIn("endpoint-cooldown quarantine", prompt)
        self.assertIn("12-target auto-policy", prompt)

    def test_cache_only_after_prewarm_budget_uses_family_balanced_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(Path(tmp), classification="not_ready_corpus_too_cache_only")
            prewarm_payload = json.loads(paths["prewarm"].read_text(encoding="utf-8"))
            prewarm_payload.update(
                {
                    "wallet_time_windows_found": 30,
                    "wallet_time_windows_attempted": 24,
                    "cache_hits_observed": 5,
                    "cache_misses_observed": 18,
                    "cache_writes": 18,
                    "rpc_failures": 2,
                    "trace_timeouts_observed": 1,
                    "max_trace_timeouts": 3,
                    "targets_left_unprewarmed": 47,
                    "stop_reason": "max_total_traces",
                }
            )
            paths["prewarm"].write_text(json.dumps(prewarm_payload), encoding="utf-8")
            readiness_payload = json.loads(paths["readiness"].read_text(encoding="utf-8"))
            readiness_payload["funding"].update(
                {
                    "tracesRequested": 24,
                    "cacheHits": 5,
                    "cacheMisses": 18,
                    "cacheWrites": 18,
                    "rpcFailures": 2,
                    "traceTimeoutsObserved": 1,
                    "maxTraceTimeouts": 3,
                    "targetsLeftUnprewarmed": 47,
                    "stopReason": "max_total_traces",
                }
            )
            paths["readiness"].write_text(json.dumps(readiness_payload), encoding="utf-8")
            pack = self._pack_for(paths)
        prompt = pack["ready_to_copy_codex_prompt"]
        self.assertEqual(pack["decision"], "run_rpc_cache_reliability_path")
        self.assertIn("family-balanced", pack["recommended_next_task"])
        self.assertIn("--max-total-traces 48", prompt)
        self.assertIn("Do not rerun the expanded 48-target auto-policy validation yet", prompt)
        self.assertIn("trace timeouts 1/3", prompt)

    def test_cache_only_after_family_balanced_high_rpc_failures_requires_operator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(Path(tmp), classification="not_ready_corpus_too_cache_only")
            trace_path = paths["output_dir"] / "trace_method_diagnostic_20260505_000000.json"
            trace_path.write_text(
                json.dumps(
                    {
                        "classification": "public_rpc_trace_chunk_bottleneck",
                        "recommended_next_step": "operator_rpc_configuration_or_capacity_decision",
                        "endpoint_labels": ["polygon.publicnode.com", "polygon.drpc.org"],
                    }
                ),
                encoding="utf-8",
            )
            prewarm_payload = json.loads(paths["prewarm"].read_text(encoding="utf-8"))
            prewarm_payload.update(
                {
                    "wallet_time_windows_found": 56,
                    "wallet_time_windows_attempted": 48,
                    "cache_writes": 36,
                    "rpc_failures": 34,
                    "targets_left_unprewarmed": 43,
                    "trace_timeouts_observed": 2,
                    "max_trace_timeouts": 3,
                    "stop_reason": "max_total_traces",
                }
            )
            paths["prewarm"].write_text(json.dumps(prewarm_payload), encoding="utf-8")
            readiness_payload = json.loads(paths["readiness"].read_text(encoding="utf-8"))
            readiness_payload["funding"].update(
                {
                    "tracesRequested": 48,
                    "cacheWrites": 36,
                    "rpcFailures": 34,
                    "targetsLeftUnprewarmed": 43,
                    "traceTimeoutsObserved": 2,
                    "maxTraceTimeouts": 3,
                    "stopReason": "max_total_traces",
                }
            )
            paths["readiness"].write_text(json.dumps(readiness_payload), encoding="utf-8")
            pack = self._pack_for(paths)
        self.assertEqual(pack["decision"], "stop_human_approval_required")
        self.assertIn("operator-approved RPC endpoint", pack["ready_to_copy_codex_prompt"])

    def test_available_trace_diagnostic_does_not_hide_prewarm_failure_dominance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(Path(tmp), classification="not_ready_corpus_too_cache_only")
            trace_path = paths["output_dir"] / "trace_method_diagnostic_20260505_000000.json"
            trace_path.write_text(
                json.dumps(
                    {
                        "classification": "trace_method_path_available",
                        "recommended_next_step": "run_bounded_12_target_validation_smoke",
                    }
                ),
                encoding="utf-8",
            )
            prewarm_payload = json.loads(paths["prewarm"].read_text(encoding="utf-8"))
            prewarm_payload.update(
                {
                    "wallet_time_windows_attempted": 47,
                    "trace_outcome_status_counts": {"success": 12, "failure": 35},
                    "targets_left_unprewarmed": 43,
                    "stop_reason": "max_total_traces",
                }
            )
            paths["prewarm"].write_text(json.dumps(prewarm_payload), encoding="utf-8")
            pack = self._pack_for(paths)
        self.assertEqual(pack["decision"], "stop_human_approval_required")

    def test_cache_only_after_trace_timeout_requires_operator_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(Path(tmp), classification="not_ready_corpus_too_cache_only")
            trace_path = paths["output_dir"] / "trace_method_diagnostic_20260505_000000.json"
            trace_path.write_text(
                json.dumps(
                    {
                        "classification": "public_rpc_trace_timeout",
                        "recommended_next_step": "operator_rpc_configuration_or_capacity_decision",
                        "endpoint_labels": ["polygon.publicnode.com", "polygon.drpc.org"],
                    }
                ),
                encoding="utf-8",
            )
            pack = self._pack_for(paths)
        prompt = pack["ready_to_copy_codex_prompt"]
        self.assertEqual(pack["decision"], "stop_human_approval_required")
        self.assertIn("operator-approved RPC endpoint", prompt)
        self.assertIn("operator RPC capacity and readiness recovery package", prompt)
        self.assertIn("python3 tools/operator_rpc_recovery_package.py", prompt)
        self.assertIn("Separate three outcomes explicitly", prompt)
        self.assertIn("full ready-to-copy comprehensive Codex prompt", prompt)
        self.assertIn("Do not run the full 48-target validation", "\n".join(pack["stop_conditions"]))

    def test_public_rpc_bottleneck_routes_to_rpc_reliability_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(
                Path(tmp),
                classification="not_ready_public_rpc_bottleneck",
                recommendation="public_rpc_or_private_rpc_needed",
            )
            pack = self._pack_for(paths)
        self.assertEqual(pack["decision"], "run_rpc_cache_reliability_path")
        self.assertIn("better bounded diagnostics", pack["ready_to_copy_codex_prompt"])

    def test_corpus_too_narrow_routes_to_fresh_trace_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(
                Path(tmp),
                classification="not_ready_corpus_too_narrow",
                recommendation="expand_corpus_more",
            )
            pack = self._pack_for(paths)
        self.assertEqual(pack["decision"], "run_fresh_trace_validation_path")
        self.assertIn("local saved metadata", pack["ready_to_copy_codex_prompt"])

    def test_ready_no_gate_issue_prompt_has_no_detector_edit_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(
                Path(tmp),
                classification="ready_no_gate_issue_observed",
                recommendation="continue_validation_no_model_change",
            )
            pack = self._pack_for(paths)
        self.assertEqual(pack["decision"], "produce_unique_review_packets")
        self.assertIn("unique-row review packets", pack["ready_to_copy_codex_prompt"])
        self.assertNotIn("enabled production detector edit", pack["recommended_next_task"].lower())

    def test_gate_review_ready_is_rfc_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(
                Path(tmp),
                classification="ready_for_strong_risk_gate_review",
                recommendation="strong_risk_gate_review_ready",
            )
            pack = self._pack_for(paths)
        prompt = pack["ready_to_copy_codex_prompt"]
        self.assertEqual(pack["decision"], "strong_risk_gate_review_ready_rfc_only")
        self.assertIn("Produce an RFC only", prompt)
        self.assertIn("Do not enable production edits", prompt)

    def test_source_attribution_routes_to_source_propagation_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(
                Path(tmp),
                classification="source_attribution_repair_needed",
                recommendation="source_attribution_repair_needed",
            )
            pack = self._pack_for(paths)
        prompt = pack["ready_to_copy_codex_prompt"]
        self.assertEqual(pack["decision"], "source_attribution_repair_path")
        self.assertIn("schema/source propagation", prompt)
        self.assertIn("Do not alter scoring", prompt)

    def test_her_routing_routes_to_accepted_contract_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(
                Path(tmp),
                classification="hard_evidence_routing_repair_needed",
                recommendation="hard_evidence_routing_repair_needed",
            )
            pack = self._pack_for(paths)
        prompt = pack["ready_to_copy_codex_prompt"]
        self.assertEqual(pack["decision"], "her_routing_repair_path")
        self.assertIn("accepted Hard Evidence Review contract", prompt)
        self.assertIn("Do not broaden HER eligibility", prompt)

    def test_missing_readiness_report_falls_back_without_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "validation_corpus_outputs"
            output_dir.mkdir(parents=True)
            pack = build_action_pack(output_dir=output_dir, project_memory_path=Path(tmp) / "PROJECT_MEMORY.md")
        self.assertEqual(pack["decision"], "run_cache_only_regression_path")
        self.assertIn("gate_decision_readiness_json", pack["evidence_paths"]["missing_inputs"])

    def test_generated_prompt_includes_constraints_stop_conditions_and_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(Path(tmp), classification="not_ready_corpus_too_cache_only")
            pack = self._pack_for(paths)
        prompt = pack["ready_to_copy_codex_prompt"]
        self.assertIn("Do not edit `_score_trade()`", prompt)
        self.assertIn("Stop conditions:", prompt)
        self.assertIn("python3 tools/funding_resolver_healthcheck.py", prompt)

    def test_prompt_omits_forbidden_phrases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(Path(tmp), classification="not_ready_corpus_too_cache_only")
            pack = self._pack_for(paths)
        prompt = pack["ready_to_copy_codex_prompt"].lower()
        for phrase in FORBIDDEN_PROMPT_PHRASES:
            self.assertNotIn(phrase, prompt)

    def test_json_and_markdown_outputs_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(Path(tmp), classification="not_ready_corpus_too_cache_only")
            pack = self._pack_for(paths)
            outputs = write_action_outputs(pack, paths["output_dir"], timestamp="20260504_010101")
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())

    def test_action_outputs_do_not_overwrite_same_second_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(Path(tmp), classification="not_ready_corpus_too_cache_only")
            pack = self._pack_for(paths)
            first = write_action_outputs(pack, paths["output_dir"], timestamp="20260504_010101")
            second = write_action_outputs(pack, paths["output_dir"], timestamp="20260504_010101")
            self.assertNotEqual(first["json_path"], second["json_path"])
            self.assertTrue(Path(first["json_path"]).exists())
            self.assertTrue(Path(second["json_path"]).exists())

    def test_gate_readiness_can_emit_next_action_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(Path(tmp), classification="not_ready_corpus_too_cache_only")
            summary = json.loads(paths["readiness"].read_text(encoding="utf-8"))
            outputs = write_readiness_outputs(summary, paths["output_dir"], emit_next_action=True)
            readiness_md = Path(outputs["markdown_path"]).read_text(encoding="utf-8")
            self.assertTrue(Path(outputs["autonomous_next_action_json_path"]).exists())
            self.assertIn("## Autonomous Next Action", readiness_md)
            self.assertEqual(outputs["autonomous_next_action_decision"], "run_rpc_cache_reliability_path")

    def test_legacy_readiness_classification_key_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(
                Path(tmp),
                classification="not_ready_corpus_too_cache_only",
                legacy_classification_key=True,
            )
            pack = self._pack_for(paths)
        self.assertEqual(pack["decision"], "run_rpc_cache_reliability_path")

    def test_standalone_pack_uses_readiness_input_corpus_over_newer_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(Path(tmp), classification="not_ready_corpus_too_cache_only")
            newer_probe = paths["output_dir"] / "post_v2_corpus_20260505_000000.json"
            newer_probe.write_text(
                json.dumps({"validationPolicy": "network_probe", "completed_targets": 1}),
                encoding="utf-8",
            )
            pack = build_action_pack(
                output_dir=paths["output_dir"],
                readiness_json_path=paths["readiness"],
                readiness_md_path=paths["readiness_md"],
                project_memory_path=paths["memory"],
            )
        self.assertEqual(pack["evidence_paths"]["post_v2_corpus_json"], str(paths["corpus"]))

    def test_standalone_pack_ignores_newer_smoke_readiness_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_inputs(Path(tmp), classification="not_ready_corpus_too_cache_only")
            smoke_corpus = paths["output_dir"] / "post_v2_corpus_20260505_010000.json"
            smoke_readiness = paths["output_dir"] / "gate_decision_readiness_20260505_010000.json"
            smoke_readiness_md = paths["output_dir"] / "gate_decision_readiness_20260505_010000.md"
            smoke_corpus.write_text(
                json.dumps(
                    {
                        "corpus_name": "post_v2_validation_corpus_smoke",
                        "validationPolicy": "cache_only",
                        "completed_targets": 12,
                        "total_targets": 12,
                    }
                ),
                encoding="utf-8",
            )
            smoke_readiness.write_text(
                json.dumps(
                    {
                        "readinessClassification": "not_ready_corpus_too_narrow",
                        "recommendation": "expand_corpus_more",
                        "inputArtifacts": {
                            "corpus_output": str(smoke_corpus),
                            "prewarm_report": str(paths["prewarm"]),
                            "report_consistency": str(paths["consistency"]),
                            "strong_risk_diagnostic": str(paths["diagnostic"]),
                        },
                    }
                ),
                encoding="utf-8",
            )
            smoke_readiness_md.write_text("# Smoke Readiness\n", encoding="utf-8")
            os.utime(paths["readiness"], (100, 100))
            os.utime(paths["corpus"], (100, 100))
            os.utime(smoke_corpus, (200, 200))
            os.utime(smoke_readiness, (200, 200))
            pack = build_action_pack(
                output_dir=paths["output_dir"],
                project_memory_path=paths["memory"],
            )
        self.assertEqual(pack["decision"], "run_rpc_cache_reliability_path")
        self.assertEqual(pack["evidence_paths"]["gate_decision_readiness_json"], str(paths["readiness"]))
        self.assertEqual(pack["evidence_paths"]["post_v2_corpus_json"], str(paths["corpus"]))


if __name__ == "__main__":
    unittest.main()
