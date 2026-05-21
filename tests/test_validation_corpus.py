from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import queue
import tempfile
from typing import Any, Mapping
import unittest
from unittest import mock

from app.archive_scanner import ArchiveResearchScanner
from app.config import AppConfig
from app.funding_context import FUNDING_EVIDENCE_UNKNOWN, FundingResolver
from app.models import Market, Trade
from app.site_categories import SiteCategory
from tools.run_validation_corpus import (
    ValidationSettings,
    ValidationRunInterrupted,
    _monitor_worker_process,
    _terminate_process_tree,
    _validation_env_overrides,
    build_corpus_summary,
    classify_network_probe,
    classify_corpus_result,
    ensure_validation_runtime_defaults,
    load_corpus_config,
    normalize_target_tags,
    render_corpus_markdown,
    run_corpus,
    run_auto_policy,
    main as run_validation_main,
    run_selected_audit,
    run_target,
    select_network_probe_corpus,
    select_smoke_corpus,
)
from tools.candidate_recall_audit import summarize_candidate_recall
from tools.discover_validation_targets import discover_validation_targets
from tools.network_funding_diagnostics import summarize_network_funding_diagnostics
from tools.prewarm_funding_cache import _family_balanced_targets, discover_funding_windows, run_prewarm
from tools.validate_report_consistency import summarize_report_consistency
from tools.gate_decision_readiness import _latest_corpus_output, build_readiness


class _FakeProcess:
    def __init__(self, *, alive_calls: int = 10) -> None:
        self.alive_calls = alive_calls
        self.terminated = False
        self.joined = False
        self.exitcode = None

    def is_alive(self) -> bool:
        if self.terminated:
            return False
        self.alive_calls -= 1
        return self.alive_calls >= 0

    def terminate(self) -> None:
        self.terminated = True
        self.exitcode = -15

    def join(self, timeout: float | None = None) -> None:
        self.joined = True


class _FakeQueue:
    def __init__(self, events: list[dict] | None = None) -> None:
        self.events = list(events or [])

    def get(self, timeout: float | None = None) -> dict:
        if not self.events:
            raise queue.Empty
        return self.events.pop(0)

    def get_nowait(self) -> dict:
        if not self.events:
            raise queue.Empty
        return self.events.pop(0)


class _FakeArchiveClient:
    def __init__(self, trades: list[Trade]) -> None:
        self.trades = trades
        self.wallet_stats_calls = 0
        self.wallet_positions_calls = 0

    def fetch_trades_in_range(self, **_kwargs: object) -> list[Trade]:
        return list(self.trades)

    def fetch_wallet_stats(self, _wallet: str) -> object:
        self.wallet_stats_calls += 1
        raise AssertionError("validation cache-only pre-admission should not hydrate wallet stats")

    def fetch_wallet_positions(self, _wallet: str) -> list[object]:
        self.wallet_positions_calls += 1
        raise AssertionError("validation cache-only pre-admission should not hydrate wallet positions")


class _FakeStorage:
    def create_scan_run(self, **_kwargs: object) -> int:
        return 1

    def save_flagged_cases(self, _scan_run_id: int, _cases: list[object]) -> None:
        return None


def _settings(**overrides: object) -> ValidationSettings:
    values = {
        "timeout_seconds": 900,
        "funding_timeout_seconds": 300,
        "max_funding_traces_per_bundle": 50,
        "max_funding_trace_failures_per_bundle": 10,
        "max_consecutive_rpc_failures": 5,
        "abort_on_funding_stall_seconds": 120,
        "stall_heartbeat_seconds": 30,
        "max_rpc_stall_targets": 3,
        "auto_cache_fallback": True,
        "network_probe_targets": 3,
        "cache_first": True,
        "allow_network_funding": True,
        "output_dir": Path("validation_corpus_outputs"),
    }
    values.update(overrides)
    return ValidationSettings(**values)


class ValidationCorpusRunnerTests(unittest.TestCase):
    def test_corpus_config_loads_valid_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corpus.json"
            path.write_text(
                json.dumps(
                    {
                        "corpusName": "test",
                        "targets": [
                            {
                                "label": "saved",
                                "mode": "event_forensic",
                                "inputType": "saved_output_replay",
                                "inputValue": "event_forensic_outputs/example",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            corpus = load_corpus_config(path)
        self.assertEqual(corpus["targets"][0]["label"], "saved")

    def test_missing_target_input_is_skipped(self) -> None:
        result = run_target(
            {
                "label": "missing",
                "mode": "event_forensic",
                "inputType": "saved_output_replay",
                "inputValue": "does/not/exist",
            },
            index=1,
            skip_rerun=False,
            audit_only=False,
            settings=_settings(),
        )
        self.assertEqual(result["status"], "skipped_missing_input")

    def test_bundle_timeout_marks_target_aborted_timeout(self) -> None:
        process = _FakeProcess(alive_calls=3)
        times = iter([0.0, 901.0])
        result = _monitor_worker_process(
            process,
            _FakeQueue(),
            {"label": "slow"},
            _settings(timeout_seconds=900),
            now_func=lambda: next(times),
        )
        self.assertEqual(result["status"], "aborted_timeout")
        self.assertTrue(result["validationTimedOut"])
        self.assertTrue(process.terminated)
        self.assertTrue(result["validationKilledProcess"])

    def test_funding_stall_marks_target_aborted_rpc_stall(self) -> None:
        process = _FakeProcess(alive_calls=4)
        times = iter([0.0, 1.0, 123.0])
        result = _monitor_worker_process(
            process,
            _FakeQueue(
                [
                    {
                        "type": "progress",
                        "stage": "Tracing blockchain linkage",
                        "detail": "Resolved 1/10 funding contexts",
                    }
                ]
            ),
            {"label": "stalled"},
            _settings(abort_on_funding_stall_seconds=120),
            now_func=lambda: next(times),
        )
        self.assertEqual(result["status"], "aborted_rpc_stall")
        self.assertEqual(result["validationFundingStatus"], "funding_blocked")
        self.assertTrue(result["validationFundingTimedOut"])

    def test_funding_progress_heartbeat_prevents_stall_abort(self) -> None:
        process = _FakeProcess(alive_calls=3)
        times = iter([0.0, 1.0, 50.0, 99.0, 100.0])
        result = _monitor_worker_process(
            process,
            _FakeQueue(
                [
                    {
                        "type": "progress",
                        "stage": "Tracing blockchain linkage",
                        "detail": "Funding trace 1/3",
                    },
                    {
                        "type": "progress",
                        "stage": "Tracing blockchain linkage",
                        "detail": "Funding trace 2/3",
                    },
                    {
                        "type": "result",
                        "payload": {
                            "status": "completed_funding_enabled",
                            "validationBundleStatus": "completed_funding_enabled",
                            "validationFundingStatus": "funding_enabled",
                        },
                    },
                ]
            ),
            {"label": "heartbeat"},
            _settings(abort_on_funding_stall_seconds=60),
            now_func=lambda: next(times),
        )
        self.assertEqual(result["status"], "completed_funding_enabled")
        self.assertFalse(result.get("validationFundingTimedOut", False))
        self.assertEqual(result["validationLastProgressMessage"], "Tracing blockchain linkage Funding trace 2/3")

    def test_funding_phase_timeout_marks_target_stalled(self) -> None:
        process = _FakeProcess(alive_calls=4)
        times = iter([0.0, 1.0, 302.0])
        result = _monitor_worker_process(
            process,
            _FakeQueue(
                [
                    {
                        "type": "progress",
                        "stage": "Tracing blockchain linkage",
                        "detail": "Funding trace started",
                    }
                ]
            ),
            {"label": "funding_timeout"},
            _settings(funding_timeout_seconds=300, abort_on_funding_stall_seconds=999),
            now_func=lambda: next(times),
        )
        self.assertEqual(result["status"], "aborted_rpc_stall")
        self.assertEqual(result["validationAbortReason"], "validation_funding_phase_timeout")

    def test_process_group_is_killed_on_timeout(self) -> None:
        class GroupProcess(_FakeProcess):
            pid = 12345

            def is_alive(self) -> bool:
                return not self.terminated

        process = GroupProcess()
        with mock.patch("tools.run_validation_corpus.os.getpgid", return_value=54321), mock.patch(
            "tools.run_validation_corpus.os.getpgrp", return_value=11111
        ), mock.patch("tools.run_validation_corpus.os.killpg") as killpg:
            killed = _terminate_process_tree(process)
        self.assertTrue(killed)
        killpg.assert_called()

    def test_cache_only_mode_blocks_network_funding_env(self) -> None:
        env = _validation_env_overrides(_settings(allow_network_funding=False))
        self.assertEqual(env["INSPOLY_VALIDATION_MODE"], "1")
        self.assertEqual(env["INSPOLY_VALIDATION_ALLOW_NETWORK_FUNDING"], "0")
        self.assertEqual(env["INSPOLY_FUNDING_TRACE_MODE"], "cache_only")

    def test_runner_invokes_audit_only_on_selected_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "rows.json"
            source.write_text('[{"id":"row-1","severity":"Low Risk"}]\n', encoding="utf-8")
            summary, outputs = run_selected_audit([str(source)], root)
            self.assertEqual(summary["total_rows_inspected"], 1)
            self.assertTrue(Path(outputs["json_path"]).exists())

    def test_corpus_report_includes_statuses_and_sections(self) -> None:
        summary = build_corpus_summary(
            corpus={"corpusName": "test"},
            target_results=[
                {"status": "completed_cache_only", "tags": ["live_or_unresolved"]},
                {"status": "skipped_missing_input", "tags": []},
            ],
            selected_output_paths=[],
            audit_summary={
                "total_rows_inspected": 1,
                "event_forensic_rows_inspected": 1,
                "archive_rows_inspected": 0,
                "visible_rows": 0,
                "strong_risk_rows": 0,
                "hard_evidence_review_rows": 0,
                "normal_candidate_rows": 0,
                "pre_admitted_candidate_rows": 0,
                "warnings": [],
                "pre_admission_funnel": {},
                "hard_evidence_pathway_counts": {"split_wallet_hard_evidence_review_rows": 0},
                "strong_risk_composition": {"strong_risk_rows_with_no_hard_evidence_sources": 0},
                "hard_evidence_starvation": {},
            },
            audit_output_paths={},
        )
        markdown = render_corpus_markdown(summary)
        self.assertIn("Target Statuses", markdown)
        self.assertIn("Hard-Evidence Pathways", markdown)
        self.assertIn("Strong Risk Composition", markdown)

    def test_classification_corpus_too_narrow(self) -> None:
        classification = classify_corpus_result(
            target_results=[{"status": "completed_cache_only", "tags": ["live_or_unresolved"]}],
            audit_summary={"archive_rows_inspected": 0, "warnings": []},
            completed_tags={"live_or_unresolved": 1},
        )
        self.assertEqual(classification, "corpus still too narrow")

    def test_target_tags_normalize_mode_and_saved_output(self) -> None:
        tags = normalize_target_tags(
            {
                "mode": "archive",
                "inputType": "saved_output_replay",
                "tags": ["politics_world"],
            }
        )
        self.assertIn("archive", tags)
        self.assertIn("audit_only_saved_output", tags)
        self.assertIn("cached_only", tags)

    def test_classification_funding_infrastructure_bottleneck(self) -> None:
        classification = classify_corpus_result(
            target_results=[
                {"status": "aborted_rpc_stall", "tags": ["politics_world"]},
                {"status": "completed_funding_blocked", "tags": ["politics_world"]},
            ],
            audit_summary={"warnings": []},
            completed_tags={},
        )
        self.assertEqual(classification, "funding infrastructure bottleneck")

    def test_classification_hard_evidence_starvation(self) -> None:
        classification = classify_corpus_result(
            target_results=[{"status": "completed_cache_only", "tags": ["live_or_unresolved"]}] * 6,
            audit_summary={
                "warnings": [],
                "hard_evidence_starvation": {
                    "independent_sources_not_routed_to_hard_evidence_review_rows": 1
                },
            },
            completed_tags={"live_or_unresolved": 6, "politics_world": 6},
        )
        self.assertEqual(classification, "hard-evidence starvation suspected")

    def test_classification_suspicious_funding_overbroad(self) -> None:
        classification = classify_corpus_result(
            target_results=[{"status": "completed_cache_only", "tags": ["live_or_unresolved"]}] * 6,
            audit_summary={
                "warnings": [{"code": "multi_hop_unknown_hard_evidence_without_independent_support"}],
                "hard_evidence_pathway_counts": {},
            },
            completed_tags={"live_or_unresolved": 6, "politics_world": 6},
        )
        self.assertEqual(classification, "suspicious funding still overbroad")

    def test_classification_unknown_funding_with_independent_support_not_overbroad_by_itself(self) -> None:
        classification = classify_corpus_result(
            target_results=[
                {
                    "status": "completed_cache_only",
                    "tags": ["fresh_rerunnable", "event_forensic", "live_or_unresolved", "politics_world", "non_gta"],
                }
            ]
            * 8
            + [
                {
                    "status": "completed_cache_only",
                    "tags": ["fresh_rerunnable", "archive", "resolved_or_partial", "sports_crypto", "non_gta"],
                }
            ]
            * 4,
            audit_summary={
                "warnings": [],
                "archive_rows_inspected": 20,
                "hard_evidence_pathway_counts": {
                    "unknown_suspicious_funding_hard_evidence_review_rows": 5
                },
                "strong_risk_rows": 0,
                "pre_admission_funnel": {"total_near_miss_groups": 0, "funding_trace_attempted_count": 4},
            },
            completed_tags={
                "fresh_rerunnable": 12,
                "event_forensic": 8,
                "archive": 4,
                "live_or_unresolved": 8,
                "resolved_or_partial": 4,
                "politics_world": 8,
                "sports_crypto": 4,
                "non_gta": 12,
            },
        )
        self.assertEqual(classification, "post-v2 behavior acceptable")

    def test_classification_post_v2_behavior_acceptable(self) -> None:
        classification = classify_corpus_result(
            target_results=[
                {
                    "status": "completed_funding_enabled",
                    "tags": ["fresh_rerunnable", "event_forensic", "live_or_unresolved", "politics_world", "non_gta"],
                }
            ]
            * 8
            + [
                {
                    "status": "completed_cache_only",
                    "tags": ["fresh_rerunnable", "archive", "resolved_or_partial", "sports_crypto", "non_gta"],
                }
            ]
            * 4,
            audit_summary={
                "warnings": [],
                "archive_rows_inspected": 20,
                "pre_admission_funnel": {"total_near_miss_groups": 0, "funding_trace_attempted_count": 4},
            },
            completed_tags={
                "fresh_rerunnable": 12,
                "event_forensic": 8,
                "archive": 4,
                "live_or_unresolved": 8,
                "resolved_or_partial": 4,
                "politics_world": 8,
                "sports_crypto": 4,
                "non_gta": 12,
            },
        )
        self.assertEqual(classification, "post-v2 behavior acceptable")

    def test_classification_candidate_recall_concern(self) -> None:
        classification = classify_corpus_result(
            target_results=[
                {
                    "status": "completed_funding_enabled",
                    "tags": ["fresh_rerunnable", "event_forensic", "live_or_unresolved", "politics_world", "non_gta"],
                }
            ]
            * 8
            + [
                {
                    "status": "completed_cache_only",
                    "tags": ["fresh_rerunnable", "archive", "resolved_or_partial", "sports_crypto", "non_gta"],
                }
            ]
            * 4,
            audit_summary={
                "warnings": [],
                "archive_rows_inspected": 20,
                "pre_admission_funnel": {"total_near_miss_groups": 2, "funding_trace_attempted_count": 0},
            },
            completed_tags={
                "fresh_rerunnable": 12,
                "event_forensic": 8,
                "archive": 4,
                "live_or_unresolved": 8,
                "resolved_or_partial": 4,
                "politics_world": 8,
                "sports_crypto": 4,
                "non_gta": 12,
            },
        )
        self.assertEqual(classification, "candidate recall concern")

    def test_classification_weak_repricing_concern_requires_dominance(self) -> None:
        target_results = [
            {
                "status": "completed_cache_only",
                "tags": ["fresh_rerunnable", "event_forensic", "live_or_unresolved", "politics_world", "non_gta"],
            }
        ] * 8 + [
            {
                "status": "completed_cache_only",
                "tags": ["fresh_rerunnable", "archive", "resolved_or_partial", "sports_crypto", "non_gta"],
            }
        ] * 4
        completed_tags = {
            "fresh_rerunnable": 12,
            "event_forensic": 8,
            "archive": 4,
            "live_or_unresolved": 8,
            "resolved_or_partial": 4,
            "politics_world": 8,
            "sports_crypto": 4,
            "non_gta": 12,
        }
        classification = classify_corpus_result(
            target_results=target_results,
            audit_summary={
                "warnings": [],
                "archive_rows_inspected": 20,
                "pre_admission_funnel": {"total_near_miss_groups": 0, "funding_trace_attempted_count": 4},
                "strong_risk_rows": 100,
                "strong_risk_exact_provenance_by_target_status": {
                    "fresh_generated": {
                        "strong_risk_rows": 100,
                        "weak_mechanical_unknown_repricing_without_structural_support_rows": 4,
                        "timing_led_without_structural_support_rows": 4,
                    }
                },
            },
            completed_tags=completed_tags,
        )
        self.assertEqual(classification, "post-v2 behavior acceptable")

        classification = classify_corpus_result(
            target_results=target_results,
            audit_summary={
                "warnings": [],
                "archive_rows_inspected": 20,
                "pre_admission_funnel": {"total_near_miss_groups": 0, "funding_trace_attempted_count": 4},
                "strong_risk_rows": 100,
                "strong_risk_exact_provenance_by_target_status": {
                    "fresh_generated": {
                        "strong_risk_rows": 100,
                        "weak_mechanical_unknown_repricing_without_structural_support_rows": 61,
                        "timing_led_without_structural_support_rows": 61,
                    }
                },
            },
            completed_tags=completed_tags,
        )
        self.assertEqual(classification, "strong-risk composition concern")

    def test_legacy_output_loads_through_selected_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "legacy.json"
            source.write_text('{"cases":[{"id":"legacy","severity":"Low Risk"}]}\n', encoding="utf-8")
            summary, _outputs = run_selected_audit([str(source)], root)
        self.assertEqual(summary["total_rows_inspected"], 1)
        self.assertEqual(summary["legacy_or_unknown_schema_rows"], 1)

    def test_cache_only_saved_output_target_is_audit_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saved = Path(tmp) / "saved.json"
            saved.write_text("[]\n", encoding="utf-8")
            result = run_target(
                {
                    "label": "saved",
                    "mode": "archive",
                    "inputType": "saved_output_replay",
                    "inputValue": str(saved),
                    "tags": ["cached_only"],
                },
                index=1,
                skip_rerun=False,
                audit_only=False,
                settings=_settings(),
            )
        self.assertEqual(result["status"], "audit_only_saved_output")
        self.assertEqual(result["validationFundingStatus"], "not_assessed")

    def test_corpus_summary_preserves_selected_output_paths(self) -> None:
        summary = build_corpus_summary(
            corpus={"corpusName": "test"},
            target_results=[{"status": "audit_only_saved_output", "tags": ["cached_only"]}],
            selected_output_paths=["saved.json"],
            audit_summary={"total_rows_inspected": 0, "warnings": []},
            audit_output_paths={"json_path": "audit.json"},
        )
        self.assertEqual(summary["selected_output_paths"], ["saved.json"])
        self.assertEqual(summary["audit_output_paths"]["json_path"], "audit.json")

    def test_validation_runtime_defaults_are_appended_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".inspoly_runtime.env"
            path.write_text("# local\nINSPOLY_VALIDATION_CACHE_FIRST=0\n", encoding="utf-8")
            first = ensure_validation_runtime_defaults(path)
            second = ensure_validation_runtime_defaults(path)
            self.assertIn("INSPOLY_VALIDATION_BUNDLE_TIMEOUT_SECONDS", first)
            self.assertIn("INSPOLY_VALIDATION_TARGET_TIMEOUT_SECONDS", first)
            self.assertIn("INSPOLY_VALIDATION_AUTO_CACHE_FALLBACK", first)
            self.assertNotIn("INSPOLY_VALIDATION_CACHE_FIRST", first)
            self.assertEqual(second, [])

    def test_network_probe_classifies_passed(self) -> None:
        summary = {
            "target_results": [
                {"status": "completed_funding_enabled"},
                {"status": "completed_cache_only"},
            ]
        }
        self.assertEqual(classify_network_probe(summary), "network_probe_passed")

    def test_network_probe_classifies_stalled(self) -> None:
        summary = {"target_results": [{"status": "aborted_rpc_stall"}]}
        self.assertEqual(classify_network_probe(summary), "network_probe_stalled")

    def test_network_probe_classifies_funding_blocked(self) -> None:
        summary = {"target_results": [{"status": "completed_funding_blocked"}]}
        self.assertEqual(classify_network_probe(summary), "network_probe_funding_blocked")

    def test_auto_policy_probe_failure_runs_cache_fallback(self) -> None:
        with mock.patch("tools.run_validation_corpus.run_healthcheck") as healthcheck, mock.patch(
            "tools.run_validation_corpus.write_health_outputs"
        ) as health_outputs, mock.patch("tools.run_validation_corpus.run_network_probe") as probe, mock.patch(
            "tools.run_validation_corpus.run_corpus"
        ) as run_corpus_mock, mock.patch("tools.run_validation_corpus.write_corpus_outputs") as write_outputs:
            healthcheck.return_value = {"overall_status": "available_for_funding_trace"}
            health_outputs.return_value = {"json_path": "health.json", "markdown_path": "health.md"}
            probe.return_value = ({"networkProbeStatus": "network_probe_stalled"}, {"json_path": "probe.json", "markdown_path": "probe.md"}, "network_probe_stalled")
            run_corpus_mock.return_value = {
                "target_results": [],
                "final_classification": "post-v2 behavior acceptable on cache-only corpus",
                "cacheOnlyFallbackUsed": True,
            }
            write_outputs.return_value = {"json_path": "corpus.json", "markdown_path": "corpus.md"}
            summary, _outputs, paths = run_auto_policy(
                {"corpusName": "test", "targets": []},
                max_targets=3,
                skip_rerun=False,
                audit_only=False,
                settings=_settings(allow_network_funding=True),
            )
        self.assertTrue(run_corpus_mock.call_args.kwargs["settings"].allow_network_funding is False)
        self.assertTrue(summary["cacheOnlyFallbackUsed"])
        self.assertEqual(paths["network_probe_json_path"], "probe.json")

    def test_auto_policy_probe_pass_runs_network_corpus(self) -> None:
        with mock.patch("tools.run_validation_corpus.run_healthcheck") as healthcheck, mock.patch(
            "tools.run_validation_corpus.write_health_outputs"
        ) as health_outputs, mock.patch("tools.run_validation_corpus.run_network_probe") as probe, mock.patch(
            "tools.run_validation_corpus.run_corpus"
        ) as run_corpus_mock, mock.patch("tools.run_validation_corpus.write_corpus_outputs") as write_outputs:
            healthcheck.return_value = {"overall_status": "available_for_funding_trace"}
            health_outputs.return_value = {"json_path": "health.json", "markdown_path": "health.md"}
            probe.return_value = ({"networkProbeStatus": "network_probe_passed"}, {"json_path": "probe.json", "markdown_path": "probe.md"}, "network_probe_passed")
            run_corpus_mock.return_value = {
                "target_results": [{"status": "completed_funding_enabled"}],
                "final_classification": "network validation stable",
                "fullNetworkAttempted": True,
            }
            write_outputs.return_value = {"json_path": "corpus.json", "markdown_path": "corpus.md"}
            summary, _outputs, _paths = run_auto_policy(
                {"corpusName": "test", "targets": []},
                max_targets=3,
                skip_rerun=False,
                audit_only=False,
                settings=_settings(allow_network_funding=True),
            )
        self.assertTrue(run_corpus_mock.call_args.kwargs["settings"].allow_network_funding)
        self.assertTrue(summary["fullNetworkAttempted"])

    def test_auto_policy_cache_fallback_records_network_source_summary(self) -> None:
        with mock.patch("tools.run_validation_corpus.run_healthcheck") as healthcheck, mock.patch(
            "tools.run_validation_corpus.write_health_outputs"
        ) as health_outputs, mock.patch("tools.run_validation_corpus.run_network_probe") as probe, mock.patch(
            "tools.run_validation_corpus.run_corpus"
        ) as run_corpus_mock, mock.patch("tools.run_validation_corpus.write_corpus_outputs") as write_outputs:
            healthcheck.return_value = {"overall_status": "available_for_funding_trace"}
            health_outputs.return_value = {"json_path": "health.json", "markdown_path": "health.md"}
            probe.return_value = (
                {"networkProbeStatus": "network_probe_passed"},
                {"json_path": "probe.json", "markdown_path": "probe.md"},
                "network_probe_passed",
            )
            network_summary = {
                "validationPolicy": "auto_policy",
                "target_results": [{"label": "slow", "status": "aborted_rpc_stall", "validationAbortReason": "rpc_stall"}],
                "stoppedEarlyReason": "max_rpc_stall_targets_hit",
                "completed_targets": 0,
                "aborted_targets": 1,
                "funding_enabled_targets": 0,
                "funding_blocked_targets": 0,
                "timeout_targets": 0,
                "rpc_stall_targets": 1,
                "final_classification": "funding infrastructure bottleneck",
            }
            fallback_summary = {
                "target_results": [],
                "final_classification": "post-v2 behavior acceptable on cache-only corpus",
                "cacheOnlyFallbackUsed": True,
            }
            run_corpus_mock.side_effect = [network_summary, fallback_summary]
            write_outputs.return_value = {"json_path": "corpus.json", "markdown_path": "corpus.md"}
            run_auto_policy(
                {"corpusName": "test", "targets": []},
                max_targets=3,
                skip_rerun=False,
                audit_only=False,
                settings=_settings(allow_network_funding=True),
            )
        fallback_kwargs = run_corpus_mock.call_args_list[1].kwargs
        self.assertEqual(fallback_kwargs["fallback_reason"], "full_network_stalled_or_blocked")
        self.assertEqual(fallback_kwargs["fallback_source_summary"]["stoppedEarlyReason"], "max_rpc_stall_targets_hit")
        self.assertEqual(fallback_kwargs["fallback_source_summary"]["targetStatusCounts"], {"aborted_rpc_stall": 1})

    def test_policy_adjusts_cache_only_acceptable_classification(self) -> None:
        summary = build_corpus_summary(
            corpus={"corpusName": "test"},
            target_results=[
                {
                    "status": "completed_cache_only",
                    "tags": ["fresh_rerunnable", "event_forensic", "live_or_unresolved", "politics_world", "non_gta"],
                }
            ]
            * 8
            + [
                {
                    "status": "completed_cache_only",
                    "tags": ["fresh_rerunnable", "archive", "resolved_or_partial", "sports_crypto", "non_gta"],
                }
            ]
            * 4,
            selected_output_paths=[],
            audit_summary={
                "warnings": [],
                "archive_rows_inspected": 20,
                "pre_admission_funnel": {"total_near_miss_groups": 0, "funding_trace_attempted_count": 4},
            },
            audit_output_paths={},
            validation_policy="auto_policy",
            cache_only_fallback_used=True,
            fallback_reason="network_probe_stalled",
        )
        self.assertEqual(summary["final_classification"], "post-v2 behavior acceptable on cache-only corpus")

    def test_network_run_stops_after_rpc_stall_limit(self) -> None:
        targets = [
            {"label": "a", "mode": "event_forensic", "inputType": "market_url", "inputValue": "url-a"},
            {"label": "b", "mode": "event_forensic", "inputType": "market_url", "inputValue": "url-b"},
            {"label": "c", "mode": "event_forensic", "inputType": "market_url", "inputValue": "url-c"},
        ]
        results = [
            {"label": "a", "status": "aborted_rpc_stall", "tags": ["fresh_rerunnable"]},
            {"label": "b", "status": "aborted_rpc_stall", "tags": ["fresh_rerunnable"]},
            {"label": "c", "status": "completed_funding_enabled", "tags": ["fresh_rerunnable"]},
        ]
        with mock.patch("tools.run_validation_corpus.run_target", side_effect=results) as run_target_mock, mock.patch(
            "tools.run_validation_corpus.run_selected_audit", return_value=({"warnings": []}, {})
        ):
            summary = run_corpus(
                {"corpusName": "test", "targets": targets},
                max_targets=3,
                skip_rerun=False,
                audit_only=False,
                settings=_settings(allow_network_funding=True, max_rpc_stall_targets=2),
            )
        self.assertEqual(run_target_mock.call_count, 2)
        self.assertEqual(summary["stoppedEarlyReason"], "max_rpc_stall_targets_hit")

    def test_auto_policy_uses_lightweight_corpus_for_cache_fallback(self) -> None:
        network_corpus = {
            "corpusName": "network",
            "targets": [
                {"label": "heavy_event", "mode": "event_forensic", "inputType": "market_url", "inputValue": "url-a"}
            ],
        }
        fallback_corpus = {
            "corpusName": "fallback",
            "targets": [
                {"label": "short_archive", "mode": "archive", "inputType": "archive_window", "inputValue": "a/b"}
            ],
        }
        calls: list[str] = []

        def fake_run_corpus(selected_corpus: Mapping[str, Any], **kwargs: object) -> dict[str, Any]:
            calls.append(str(selected_corpus.get("corpusName") or ""))
            if kwargs.get("cache_only_fallback_used"):
                return {
                    "target_results": [{"label": "short_archive", "status": "completed_cache_only"}],
                    "final_classification": "corpus still too narrow",
                    "cacheOnlyFallbackUsed": True,
                }
            return {
                "target_results": [
                    {"label": "heavy_event", "status": "completed_funding_blocked"},
                    {"label": "heavy_event_2", "status": "completed_funding_blocked"},
                    {"label": "heavy_event_3", "status": "completed_funding_blocked"},
                ],
                "stoppedEarlyReason": "",
            }

        with mock.patch(
            "tools.run_validation_corpus.run_healthcheck",
            return_value={"overall_status": "available_for_funding_trace"},
        ), mock.patch(
            "tools.run_validation_corpus.write_health_outputs",
            return_value={"json_path": "health.json", "markdown_path": "health.md"},
        ), mock.patch(
            "tools.run_validation_corpus.run_network_probe",
            return_value=({"target_results": []}, {"json_path": "probe.json", "markdown_path": "probe.md"}, "network_probe_passed"),
        ), mock.patch(
            "tools.run_validation_corpus.run_corpus",
            side_effect=fake_run_corpus,
        ), mock.patch(
            "tools.run_validation_corpus.write_corpus_outputs",
            return_value={"json_path": "out.json", "markdown_path": "out.md"},
        ):
            summary, _outputs, _policy = run_auto_policy(
                network_corpus,
                max_targets=1,
                skip_rerun=False,
                audit_only=False,
                settings=_settings(max_rpc_stall_targets=3),
                fallback_corpus=fallback_corpus,
            )
        self.assertEqual(calls, ["network", "fallback"])
        self.assertTrue(summary["cacheOnlyFallbackUsed"])

    def test_run_corpus_writes_terminal_failure_artifact_on_interrupt(self) -> None:
        targets = [
            {"label": "a", "mode": "event_forensic", "inputType": "market_url", "inputValue": "url-a"},
            {"label": "b", "mode": "event_forensic", "inputType": "market_url", "inputValue": "url-b"},
        ]
        results = [
            {"label": "a", "status": "completed_cache_only", "tags": ["fresh_rerunnable"], "audit_paths": ["a.json"]},
            KeyboardInterrupt("manual stop"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("tools.run_validation_corpus.run_target", side_effect=results):
                with self.assertRaises(KeyboardInterrupt):
                    run_corpus(
                        {"corpusName": "test", "targets": targets},
                        max_targets=2,
                        skip_rerun=False,
                        audit_only=False,
                        settings=_settings(output_dir=root),
                        validation_policy="auto_policy",
                        cache_only_fallback_used=True,
                        fallback_reason="network_probe_stalled",
                        terminal_artifact_label="test_terminal",
                        terminal_artifact_timestamp="20260504_010101",
                    )
            artifact = root / "validation_corpus_terminal_failure_20260504_010101.json"
            payload = json.loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(payload["terminalState"], "terminal_failure")
        self.assertEqual(payload["terminalArtifactLabel"], "test_terminal")
        self.assertEqual(payload["target_status_counts"], {"completed_cache_only": 1})
        self.assertEqual(payload["currentTarget"]["label"], "b")
        self.assertEqual(payload["lastCompletedTargetIndex"], 1)
        self.assertEqual(payload["lastCompletedTarget"]["label"], "a")
        self.assertEqual(payload["partialTargetResultsCount"], 1)
        self.assertIsNotNone(payload["currentTargetRuntimeSeconds"])
        self.assertTrue(payload["checkpointJsonPath"].endswith("validation_corpus_checkpoint_20260504_010101.json"))
        self.assertTrue(payload["orphanWorkerCleanup"]["cleanupReported"])

    def test_run_corpus_signal_interrupt_exits_cleanly_after_terminal_artifact(self) -> None:
        targets = [
            {"label": "a", "mode": "event_forensic", "inputType": "market_url", "inputValue": "url-a"},
            {"label": "b", "mode": "event_forensic", "inputType": "market_url", "inputValue": "url-b"},
        ]
        results = [
            {"label": "a", "status": "completed_cache_only", "tags": ["fresh_rerunnable"], "audit_paths": ["a.json"]},
            ValidationRunInterrupted(15),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("tools.run_validation_corpus.run_target", side_effect=results):
                with self.assertRaises(SystemExit) as raised:
                    run_corpus(
                        {"corpusName": "test", "targets": targets},
                        max_targets=2,
                        skip_rerun=False,
                        audit_only=False,
                        settings=_settings(output_dir=root),
                        validation_policy="auto_policy",
                        cache_only_fallback_used=True,
                        fallback_reason="network_probe_stalled",
                        terminal_artifact_label="test_signal_terminal",
                        terminal_artifact_timestamp="20260504_030303",
                    )
            artifact = root / "validation_corpus_terminal_failure_20260504_030303.json"
            payload = json.loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(raised.exception.code, 130)
        self.assertEqual(payload["terminalReason"], "signal_15")
        self.assertEqual(payload["terminalArtifactKind"], "explicit_terminal_failure")
        self.assertEqual(payload["lastCompletedTargetIndex"], 1)
        self.assertEqual(payload["currentTarget"]["label"], "b")

    def test_run_corpus_writes_progress_checkpoint_after_targets(self) -> None:
        targets = [
            {"label": "a", "mode": "event_forensic", "inputType": "market_url", "inputValue": "url-a"},
            {"label": "b", "mode": "event_forensic", "inputType": "market_url", "inputValue": "url-b"},
        ]
        results = [
            {
                "label": "a",
                "status": "completed_cache_only",
                "tags": ["fresh_rerunnable"],
                "audit_paths": ["a.json"],
                "validationWallClockSeconds": 11.0,
                "validationPhase": "Done",
            },
            {
                "label": "b",
                "status": "aborted_rpc_stall",
                "tags": ["fresh_rerunnable"],
                "audit_paths": ["b.json"],
                "validationWallClockSeconds": 122.0,
                "validationPhase": "Tracing blockchain linkage",
                "validationAbortReason": "validation_funding_stall_timeout",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("tools.run_validation_corpus.run_target", side_effect=results), mock.patch(
                "tools.run_validation_corpus.run_selected_audit",
                return_value=({"warnings": []}, {}),
            ):
                summary = run_corpus(
                    {"corpusName": "test", "targets": targets},
                    max_targets=2,
                    skip_rerun=False,
                    audit_only=False,
                    settings=_settings(output_dir=root),
                    validation_policy="cache_only",
                    terminal_artifact_label="test_checkpoint",
                    terminal_artifact_timestamp="20260504_020202",
                )
            checkpoint = root / "validation_corpus_checkpoint_20260504_020202.json"
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        self.assertEqual(summary["target_status_counts"], {"aborted_rpc_stall": 1, "completed_cache_only": 1})
        self.assertEqual(payload["terminalState"], "running_checkpoint")
        self.assertEqual(payload["terminalArtifactKind"], "progress_checkpoint")
        self.assertEqual(payload["checkpointReason"], "after_target_completed")
        self.assertEqual(payload["lastCompletedTargetIndex"], 2)
        self.assertEqual(payload["lastCompletedTarget"]["label"], "b")
        self.assertEqual(payload["partialTargetResultsCount"], 2)
        self.assertEqual(payload["slowestCompletedTargets"][0]["label"], "b")

    def test_archive_validation_cache_only_skips_preadmission_hydration(self) -> None:
        trade = Trade(
            trade_id="subthreshold-1",
            condition_id="cond-1",
            asset_id="asset-1",
            wallet="0x1111111111111111111111111111111111111111",
            side="BUY",
            outcome="YES",
            price=Decimal("0.50"),
            size=Decimal("400"),
            timestamp=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
            title="Archive cache-only test",
            slug="archive-cache-only-test",
            event_slug="archive-cache-only",
        )
        market = Market(
            market_id="m1",
            condition_id="cond-1",
            slug="archive-cache-only-test",
            question="Archive cache-only test?",
            category="World",
            end_date=None,
            liquidity=Decimal("10000"),
            volume=Decimal("50000"),
            outcomes=["YES", "NO"],
            token_ids=["asset-1", "asset-2"],
            tags=["world"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = AppConfig(
                data_dir=root / ".archive",
                db_path=root / ".archive" / "archive.sqlite3",
                reports_dir=root / ".archive" / "reports",
                outputs_dir=root / "archive_outputs",
                max_trade_pages=1,
                trade_page_size=10,
            )
            config.ensure_dirs()
            client = _FakeArchiveClient([trade])
            progress_events: list[object] = []
            with mock.patch.dict(
                os.environ,
                {
                    "INSPOLY_VALIDATION_MODE": "1",
                    "INSPOLY_VALIDATION_ALLOW_NETWORK_FUNDING": "0",
                },
            ):
                scanner = ArchiveResearchScanner(client, _FakeStorage(), config)
                with mock.patch.object(scanner, "_load_archive_focus_markets", return_value={"cond-1": market}):
                    report = scanner.scan(
                        datetime(2026, 4, 30, 11, 0, tzinfo=UTC),
                        datetime(2026, 4, 30, 13, 0, tzinfo=UTC),
                        config.reports_dir,
                        selected_categories=(SiteCategory("World", "world", "1"),),
                        min_notional=Decimal("1000"),
                        progress_callback=progress_events.append,
                    )
        self.assertEqual(client.wallet_stats_calls, 0)
        self.assertEqual(client.wallet_positions_calls, 0)
        self.assertEqual(report["candidate_trade_count"], 0)
        self.assertEqual(report["funding_resolver_health"]["validationBundleStatus"], "completed_cache_only")
        funnel = report["candidate_admission_funnel"]
        self.assertFalse(funnel["preAdmissionFundingTraceEnabled"])
        self.assertEqual(
            funnel["fundingTraceSkippedReasonDistribution"],
            {"validation_cache_only_pre_admission_skipped": 1},
        )
        self.assertNotIn("Tracing blockchain linkage", {getattr(event, "stage", "") for event in progress_events})

    def test_latest_readiness_corpus_ignores_tiny_smoke_when_broader_run_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            broad = root / "post_v2_corpus_20260504_010000.json"
            smoke = root / "post_v2_corpus_20260504_020000.json"
            broad.write_text(
                json.dumps(
                    {
                        "validationPolicy": "cache_only",
                        "total_targets": 32,
                        "completed_targets": 32,
                        "interpretableModelEvidenceTargets": 28,
                    }
                ),
                encoding="utf-8",
            )
            smoke.write_text(
                json.dumps(
                    {
                        "corpus_name": "post_v2_validation_corpus_smoke",
                        "validationPolicy": "cache_only",
                        "total_targets": 12,
                        "completed_targets": 12,
                        "interpretableModelEvidenceTargets": 8,
                        "target_status_counts": {"completed_cache_only": 8, "audit_only_saved_output": 4},
                    }
                ),
                encoding="utf-8",
            )
            os.utime(broad, (100, 100))
            os.utime(smoke, (200, 200))
            with mock.patch("tools.gate_decision_readiness.DEFAULT_OUTPUT_DIR", root):
                latest = _latest_corpus_output()
        self.assertEqual(latest, broad)

    def test_default_readiness_uses_reports_matching_selected_non_smoke_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            diagnostic_root = root / "strong_risk_diagnostic_outputs"
            diagnostic_root.mkdir()
            config = root / "post_v2_validation_corpus.json"
            broad = root / "post_v2_corpus_20260504_010000.json"
            smoke = root / "post_v2_corpus_20260504_020000.json"
            broad_drilldown = root / "corpus_provenance_drilldown_20260504_010000.json"
            smoke_drilldown = root / "corpus_provenance_drilldown_20260504_020000.json"
            broad_consistency = root / "report_consistency_20260504_010000.json"
            smoke_consistency = root / "report_consistency_20260504_020000.json"
            broad_diagnostic = diagnostic_root / "strong_risk_gate_diagnostic_20260504_010000.json"
            smoke_diagnostic = diagnostic_root / "strong_risk_gate_diagnostic_20260504_020000.json"
            prewarm = root / "funding_cache_prewarm_20260504_020000.json"
            config.write_text(json.dumps({"targets": []}), encoding="utf-8")
            broad_payload = {
                "corpus_name": "post_v2_validation_corpus",
                "validationPolicy": "cache_only",
                "completed_targets": 32,
                "interpretableModelEvidenceTargets": 28,
                "rawVisibleRows": 3857,
                "uniqueVisibleRows": 1758,
                "rawStrongRiskRows": 799,
                "uniqueStrongRiskRows": 396,
                "rawHardEvidenceReviewRows": 574,
                "uniqueHardEvidenceReviewRows": 217,
            }
            smoke_payload = {
                "corpus_name": "post_v2_validation_corpus_smoke",
                "validationPolicy": "cache_only",
                "completed_targets": 12,
                "interpretableModelEvidenceTargets": 8,
                "rawVisibleRows": 1894,
                "uniqueVisibleRows": 931,
                "rawStrongRiskRows": 197,
                "uniqueStrongRiskRows": 125,
                "rawHardEvidenceReviewRows": 0,
                "uniqueHardEvidenceReviewRows": 0,
            }
            broad.write_text(json.dumps(broad_payload), encoding="utf-8")
            smoke.write_text(json.dumps(smoke_payload), encoding="utf-8")
            broad_drilldown.write_text(json.dumps({"input_artifacts": {"corpus": str(broad)}, **broad_payload}), encoding="utf-8")
            smoke_drilldown.write_text(json.dumps({"input_artifacts": {"corpus": str(smoke)}, **smoke_payload}), encoding="utf-8")
            broad_consistency.write_text(
                json.dumps({"classification": "count_reporting_consistent", "sources": [{"kind": "corpus", "json_path": str(broad)}]}),
                encoding="utf-8",
            )
            smoke_consistency.write_text(
                json.dumps({"classification": "count_reporting_consistent", "sources": [{"kind": "corpus", "json_path": str(smoke)}]}),
                encoding="utf-8",
            )
            broad_diagnostic.write_text(json.dumps({"inputArtifacts": {"corpus": str(broad)}, **broad_payload}), encoding="utf-8")
            smoke_diagnostic.write_text(json.dumps({"inputArtifacts": {"corpus": str(smoke)}, **smoke_payload}), encoding="utf-8")
            prewarm.write_text(json.dumps({}), encoding="utf-8")
            for path, stamp in [
                (broad, 100),
                (broad_drilldown, 100),
                (broad_consistency, 100),
                (broad_diagnostic, 100),
                (smoke, 200),
                (smoke_drilldown, 200),
                (smoke_consistency, 200),
                (smoke_diagnostic, 200),
            ]:
                os.utime(path, (stamp, stamp))
            with mock.patch("tools.gate_decision_readiness.DEFAULT_OUTPUT_DIR", root), mock.patch(
                "tools.gate_decision_readiness.STRONG_RISK_DIAGNOSTIC_DIR", diagnostic_root
            ):
                summary = build_readiness(corpus_config_path=config)
        artifacts = summary["inputArtifacts"]
        self.assertEqual(Path(artifacts["corpus_output"]), broad)
        self.assertEqual(Path(artifacts["corpus_provenance_drilldown"]), broad_drilldown)
        self.assertEqual(Path(artifacts["report_consistency"]), broad_consistency)
        self.assertEqual(Path(artifacts["strong_risk_diagnostic"]), broad_diagnostic)

    def test_smoke_corpus_prefers_short_archive_windows(self) -> None:
        corpus = {
            "corpusName": "test",
            "targets": [
                {
                    "label": "long_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-02-01T00:00:00+00:00/2026-04-22T00:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable", "high_volume"],
                },
                {
                    "label": "event",
                    "mode": "event_forensic",
                    "inputType": "market_url",
                    "inputValue": "https://example.invalid/market",
                    "freshRerunnable": True,
                    "tags": ["event_forensic", "fresh_rerunnable"],
                },
                {
                    "label": "short_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T01:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable"],
                },
                {
                    "label": "six_hour_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T06:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable"],
                },
            ],
        }
        smoke = select_smoke_corpus(corpus, 2)
        self.assertEqual([target["label"] for target in smoke["targets"]], ["short_archive", "six_hour_archive"])
        self.assertEqual(smoke["corpusName"], "test_smoke")

    def test_smoke_corpus_can_prefer_prewarmed_successful_targets(self) -> None:
        corpus = {
            "corpusName": "test",
            "targets": [
                {
                    "label": "short_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T01:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable"],
                },
                {
                    "label": "event_with_cache",
                    "mode": "event_forensic",
                    "inputType": "market_url",
                    "inputValue": "https://example.invalid/market",
                    "freshRerunnable": True,
                    "tags": ["event_forensic", "fresh_rerunnable", "funding_candidate"],
                },
            ],
        }
        smoke = select_smoke_corpus(
            corpus,
            1,
            prewarm_summary={
                "target_results": [
                    {
                        "label": "event_with_cache",
                        "status": "completed",
                        "traceSucceededDelta": 1,
                        "cacheHitsObserved": 1,
                        "failuresObserved": 0,
                        "windowsAttempted": 1,
                    }
                ]
            },
        )
        self.assertEqual([target["label"] for target in smoke["targets"]], ["event_with_cache"])

    def test_smoke_corpus_does_not_promote_long_prewarmed_archive_over_event(self) -> None:
        corpus = {
            "corpusName": "test",
            "targets": [
                {
                    "label": "long_archive_with_cache",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T12:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable", "funding_candidate"],
                },
                {
                    "label": "event_with_cache",
                    "mode": "event_forensic",
                    "inputType": "market_url",
                    "inputValue": "https://example.invalid/market",
                    "freshRerunnable": True,
                    "tags": ["event_forensic", "fresh_rerunnable", "funding_candidate"],
                },
            ],
        }
        prewarm_summary = {
            "target_results": [
                {
                    "label": "long_archive_with_cache",
                    "status": "completed",
                    "traceSucceededDelta": 1,
                    "cacheHitsObserved": 1,
                    "failuresObserved": 0,
                    "windowsAttempted": 1,
                },
                {
                    "label": "event_with_cache",
                    "status": "completed",
                    "traceSucceededDelta": 1,
                    "cacheHitsObserved": 1,
                    "failuresObserved": 0,
                    "windowsAttempted": 1,
                },
            ]
        }
        smoke = select_smoke_corpus(corpus, 1, prewarm_summary=prewarm_summary)
        self.assertEqual([target["label"] for target in smoke["targets"]], ["event_with_cache"])

    def test_network_probe_corpus_uses_smoke_selection_for_network_allowed_targets(self) -> None:
        corpus = {
            "corpusName": "test",
            "targets": [
                {
                    "label": "long_network_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-02-01T00:00:00+00:00/2026-04-22T00:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable", "network_allowed", "high_volume"],
                },
                {
                    "label": "short_network_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T01:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable", "network_allowed"],
                },
                {
                    "label": "medium_network_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T06:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable", "network_allowed"],
                },
            ],
        }
        probe = select_network_probe_corpus(corpus, 2)
        self.assertEqual(
            [target["label"] for target in probe["targets"]],
            ["short_network_archive", "medium_network_archive"],
        )
        self.assertEqual(probe["corpusName"], "test_network_probe")

    def test_network_probe_can_preserve_prewarmed_smoke_order(self) -> None:
        corpus = {
            "corpusName": "test_smoke",
            "targets": [
                {
                    "label": "event_first",
                    "mode": "event_forensic",
                    "inputType": "market_url",
                    "inputValue": "https://example.invalid/market-a",
                    "tags": ["event_forensic", "network_allowed"],
                },
                {
                    "label": "short_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T01:00:00+00:00",
                    "tags": ["archive", "network_allowed"],
                },
            ],
        }
        probe = select_network_probe_corpus(corpus, 1, preserve_order=True)
        self.assertEqual([target["label"] for target in probe["targets"]], ["event_first"])
        self.assertEqual(probe["corpusName"], "test_smoke_network_probe")

    def test_auto_policy_small_max_targets_uses_smoke_selection(self) -> None:
        corpus = {
            "corpusName": "test",
            "targets": [
                {
                    "label": "long_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-02-01T00:00:00+00:00/2026-04-30T00:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable", "high_volume"],
                },
                {
                    "label": "short_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T01:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable"],
                },
                {
                    "label": "six_hour_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T06:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable"],
                },
            ],
        }
        captured: dict[str, list[str]] = {}

        def fake_run_auto_policy(selected_corpus: Mapping[str, Any], **_kwargs: object):
            captured["labels"] = [str(target.get("label")) for target in selected_corpus.get("targets", [])]
            return ({"final_classification": "corpus still too narrow"}, {"json_path": "x.json", "markdown_path": "x.md"}, {})

        with mock.patch("tools.run_validation_corpus.ensure_validation_runtime_defaults"), mock.patch(
            "tools.run_validation_corpus.load_runtime_env"
        ), mock.patch(
            "tools.run_validation_corpus.validation_settings_from_env", return_value=_settings()
        ), mock.patch(
            "tools.run_validation_corpus.load_corpus_config", return_value=corpus
        ), mock.patch(
            "tools.run_validation_corpus.run_auto_policy", side_effect=fake_run_auto_policy
        ), mock.patch(
            "tools.run_validation_corpus._print_summary"
        ):
            exit_code = run_validation_main(["--auto-policy", "--max-targets", "2"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(captured["labels"], ["short_archive", "six_hour_archive"])

    def test_cache_only_small_max_targets_uses_smoke_selection(self) -> None:
        corpus = {
            "corpusName": "test",
            "targets": [
                {
                    "label": "long_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-02-01T00:00:00+00:00/2026-04-30T00:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable", "high_volume"],
                },
                {
                    "label": "short_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T01:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable"],
                },
                {
                    "label": "six_hour_archive",
                    "mode": "archive",
                    "inputType": "archive_window",
                    "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T06:00:00+00:00",
                    "freshRerunnable": True,
                    "tags": ["archive", "fresh_rerunnable"],
                },
            ],
        }
        captured: dict[str, list[str]] = {}

        def fake_run_corpus(selected_corpus: Mapping[str, Any], **_kwargs: object):
            captured["labels"] = [str(target.get("label")) for target in selected_corpus.get("targets", [])]
            return {"final_classification": "corpus still too narrow"}

        with mock.patch("tools.run_validation_corpus.ensure_validation_runtime_defaults"), mock.patch(
            "tools.run_validation_corpus.load_runtime_env"
        ), mock.patch(
            "tools.run_validation_corpus.validation_settings_from_env", return_value=_settings(allow_network_funding=False)
        ), mock.patch(
            "tools.run_validation_corpus.load_corpus_config", return_value=corpus
        ), mock.patch(
            "tools.run_validation_corpus.run_corpus", side_effect=fake_run_corpus
        ), mock.patch(
            "tools.run_validation_corpus.write_corpus_outputs", return_value={"json_path": "x.json", "markdown_path": "x.md"}
        ), mock.patch(
            "tools.run_validation_corpus._print_summary"
        ):
            exit_code = run_validation_main(["--cache-only", "--max-targets", "2"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(captured["labels"], ["short_archive", "six_hour_archive"])

    def test_prewarm_discovers_windows_from_saved_style_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "candidates.csv"
            csv_path.write_text(
                "wallet,timestamp,notional\n"
                "0x1111111111111111111111111111111111111111,2026-04-30T01:00:00+00:00,1200\n",
                encoding="utf-8",
            )
            windows = discover_funding_windows(
                {"priorOutputPaths": [str(csv_path)], "tags": []},
                repo_root=root,
            )
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].wallet, "0x1111111111111111111111111111111111111111")

    def test_prewarm_handles_missing_metadata(self) -> None:
        class FakeResolver:
            def analyze(self, wallet: str, as_of: datetime):  # pragma: no cover - should not be called
                raise AssertionError("analyze should not run")

            def health(self) -> dict:
                return {}

        summary = run_prewarm(
            {"corpusName": "test", "targets": [{"label": "missing", "mode": "archive", "inputType": "archive_window", "inputValue": "x/y"}]},
            max_targets=1,
            max_traces_per_target=2,
            max_total_traces=2,
            timeout_seconds=30,
            resolver_factory=FakeResolver,
        )
        self.assertEqual(summary["skipped_targets"], 1)
        self.assertEqual(summary["wallet_time_windows_attempted"], 0)

    def test_prewarm_uses_cache_first_and_respects_caps(self) -> None:
        class Context:
            funding_trace_from_persistent_cache = True
            error = None

        class FakeResolver:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def analyze(self, wallet: str, as_of: datetime) -> Context:
                self.calls.append(wallet)
                return Context()

            def health(self) -> dict:
                return {
                    "fundingTraceAttemptedCount": len(self.calls),
                    "fundingTraceSucceededCount": len(self.calls),
                    "fundingTraceFailedCount": 0,
                    "fundingTraceSkippedCount": 0,
                    "fundingTracePersistentCacheHitCount": len(self.calls),
                    "fundingTracePersistentCacheMissCount": 0,
                    "fundingTracePersistentCacheWriteCount": 0,
                    "fundingTracePersistentCacheEnabled": True,
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "candidates.csv"
            csv_path.write_text(
                "wallet,timestamp,notional\n"
                "0x1111111111111111111111111111111111111111,2026-04-30T01:00:00+00:00,1200\n"
                "0x2222222222222222222222222222222222222222,2026-04-30T02:00:00+00:00,1100\n",
                encoding="utf-8",
            )
            summary = run_prewarm(
                {
                    "corpusName": "test",
                    "targets": [
                        {
                            "label": "target",
                            "mode": "archive",
                            "inputType": "saved_output_replay",
                            "inputValue": str(csv_path),
                        }
                    ],
                },
                max_targets=1,
                max_traces_per_target=2,
                max_total_traces=1,
                timeout_seconds=30,
                resolver_factory=FakeResolver,
                repo_root=root,
            )
        self.assertEqual(summary["wallet_time_windows_attempted"], 1)
        self.assertEqual(summary["cache_hits_observed"], 1)
        self.assertEqual(summary["stop_reason"], "max_total_traces")
        family = summary["prewarm_coverage_by_target_family"]["archive"]
        self.assertEqual(family["targetsLeftUnprewarmed"], 1)
        self.assertEqual(family["windowCoverageRatio"], 0.5)
        self.assertEqual(family["cacheHitRate"], 1.0)

    def test_prewarm_continues_after_single_trace_timeout_within_limit(self) -> None:
        class Context:
            funding_trace_from_persistent_cache = True
            error = None

        class FakeResolver:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def analyze(self, wallet: str, as_of: datetime) -> Context:
                self.calls.append(wallet)
                if len(self.calls) == 1:
                    raise TimeoutError("funding_trace_timeout")
                return Context()

            def health(self) -> dict:
                successful = max(0, len(self.calls) - 1)
                return {
                    "fundingTraceAttemptedCount": successful,
                    "fundingTraceSucceededCount": successful,
                    "fundingTraceFailedCount": 0,
                    "fundingTraceSkippedCount": 0,
                    "fundingTracePersistentCacheHitCount": successful,
                    "fundingTracePersistentCacheMissCount": 0,
                    "fundingTracePersistentCacheWriteCount": 0,
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_csv = root / "first.csv"
            second_csv = root / "second.csv"
            first_csv.write_text(
                "wallet,timestamp,notional\n"
                "0x1111111111111111111111111111111111111111,2026-04-30T01:00:00+00:00,1200\n",
                encoding="utf-8",
            )
            second_csv.write_text(
                "wallet,timestamp,notional\n"
                "0x2222222222222222222222222222222222222222,2026-04-30T02:00:00+00:00,1100\n",
                encoding="utf-8",
            )
            summary = run_prewarm(
                {
                    "corpusName": "test",
                    "targets": [
                        {"label": "first", "mode": "archive", "inputType": "saved_output_replay", "inputValue": str(first_csv)},
                        {"label": "second", "mode": "archive", "inputType": "saved_output_replay", "inputValue": str(second_csv)},
                    ],
                },
                max_targets=2,
                max_traces_per_target=1,
                max_total_traces=2,
                timeout_seconds=30,
                max_trace_timeouts=2,
                resolver_factory=FakeResolver,
                repo_root=root,
            )
        self.assertEqual(summary["stop_reason"], "")
        self.assertEqual(summary["trace_timeouts_observed"], 1)
        self.assertEqual(summary["wallet_time_windows_attempted"], 2)
        self.assertEqual(summary["funding_blocked_targets"], 1)
        self.assertEqual(summary["completed_targets"], 1)
        self.assertEqual(summary["target_results"][0]["targetStopReason"], "trace_timeout")
        self.assertEqual(summary["target_results"][1]["status"], "completed")

    def test_prewarm_stops_after_trace_timeout_limit(self) -> None:
        class FakeResolver:
            def analyze(self, wallet: str, as_of: datetime):
                raise TimeoutError("funding_trace_timeout")

            def health(self) -> dict:
                return {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_csv = root / "first.csv"
            second_csv = root / "second.csv"
            first_csv.write_text(
                "wallet,timestamp,notional\n"
                "0x1111111111111111111111111111111111111111,2026-04-30T01:00:00+00:00,1200\n",
                encoding="utf-8",
            )
            second_csv.write_text(
                "wallet,timestamp,notional\n"
                "0x2222222222222222222222222222222222222222,2026-04-30T02:00:00+00:00,1100\n",
                encoding="utf-8",
            )
            summary = run_prewarm(
                {
                    "corpusName": "test",
                    "targets": [
                        {"label": "first", "mode": "archive", "inputType": "saved_output_replay", "inputValue": str(first_csv)},
                        {"label": "second", "mode": "archive", "inputType": "saved_output_replay", "inputValue": str(second_csv)},
                    ],
                },
                max_targets=2,
                max_traces_per_target=1,
                max_total_traces=2,
                timeout_seconds=30,
                max_trace_timeouts=1,
                resolver_factory=FakeResolver,
                repo_root=root,
            )
        self.assertEqual(summary["stop_reason"], "trace_timeout")
        self.assertEqual(summary["trace_timeouts_observed"], 1)
        self.assertEqual(summary["max_trace_timeouts"], 1)
        self.assertEqual(summary["wallet_time_windows_attempted"], 1)
        self.assertEqual(summary["funding_blocked_targets"], 1)
        self.assertEqual(summary["skipped_targets"], 1)
        self.assertEqual(summary["target_results"][1]["status"], "skipped_global_limit")

    def test_prewarm_prioritizes_short_funding_candidate_targets_before_max_targets(self) -> None:
        class Context:
            funding_trace_from_persistent_cache = True
            error = None

        class FakeResolver:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def analyze(self, wallet: str, as_of: datetime) -> Context:
                self.calls.append(wallet)
                return Context()

            def health(self) -> dict:
                return {
                    "fundingTraceAttemptedCount": len(self.calls),
                    "fundingTraceSucceededCount": len(self.calls),
                    "fundingTraceFailedCount": 0,
                    "fundingTraceSkippedCount": 0,
                    "fundingTracePersistentCacheHitCount": len(self.calls),
                    "fundingTracePersistentCacheMissCount": 0,
                    "fundingTracePersistentCacheWriteCount": 0,
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            long_csv = root / "long.csv"
            short_csv = root / "short.csv"
            long_csv.write_text(
                "wallet,timestamp,notional\n"
                "0x1111111111111111111111111111111111111111,2026-04-30T01:00:00+00:00,1200\n",
                encoding="utf-8",
            )
            short_csv.write_text(
                "wallet,timestamp,notional\n"
                "0x2222222222222222222222222222222222222222,2026-04-30T02:00:00+00:00,1100\n",
                encoding="utf-8",
            )
            summary = run_prewarm(
                {
                    "corpusName": "test",
                    "targets": [
                        {
                            "label": "long",
                            "mode": "archive",
                            "inputType": "archive_window",
                            "inputValue": "2026-02-01T00:00:00+00:00/2026-04-30T00:00:00+00:00",
                            "priorOutputPaths": [str(long_csv)],
                            "tags": ["archive", "funding_candidate"],
                        },
                        {
                            "label": "short",
                            "mode": "archive",
                            "inputType": "archive_window",
                            "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T01:00:00+00:00",
                            "priorOutputPaths": [str(short_csv)],
                            "tags": ["archive", "funding_candidate"],
                        },
                    ],
                },
                max_targets=1,
                max_traces_per_target=1,
                max_total_traces=1,
                timeout_seconds=30,
                resolver_factory=FakeResolver,
                repo_root=root,
            )
        self.assertEqual(summary["target_results"][0]["label"], "short")
        self.assertEqual(summary["wallet_time_windows_attempted"], 1)

    def test_prewarm_target_order_is_family_balanced(self) -> None:
        targets = [
            {
                "label": "archive_short",
                "mode": "archive",
                "inputType": "archive_window",
                "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T01:00:00+00:00",
                "tags": ["archive", "politics_world", "funding_candidate"],
            },
            {
                "label": "archive_second",
                "mode": "archive",
                "inputType": "archive_window",
                "inputValue": "2026-04-30T00:00:00+00:00/2026-04-30T02:00:00+00:00",
                "tags": ["archive", "politics_world", "funding_candidate"],
            },
            {
                "label": "sports_event",
                "mode": "event_forensic",
                "inputType": "market_url",
                "inputValue": "https://example.invalid/sports",
                "tags": ["sports_crypto", "funding_candidate"],
            },
            {
                "label": "gta_event",
                "mode": "event_forensic",
                "inputType": "market_url",
                "inputValue": "https://example.invalid/gta",
                "tags": ["gta_or_known_cluster", "funding_candidate"],
            },
        ]
        ordered = _family_balanced_targets([dict(target) for target in targets])
        self.assertEqual(
            [target["label"] for target in ordered[:3]],
            ["archive_short", "gta_event", "sports_event"],
        )
        self.assertEqual(ordered[3]["label"], "archive_second")

    def _write_readiness_fixture(
        self,
        root: Path,
        *,
        statuses: list[str],
        families: list[str],
        unique_visible: int = 100,
        raw_strong: int = 30,
        unique_strong: int = 30,
        traced: int = 30,
        her_invalid: dict[str, int] | None = None,
        fresh_unique_gate_leakage: int = 0,
        consistency: str = "count_reporting_consistent",
        prewarm: dict | None = None,
        source_repair_rows: int = 0,
    ) -> dict[str, Path]:
        root.mkdir(parents=True, exist_ok=True)
        targets = []
        target_results = []
        for index, status in enumerate(statuses):
            family = families[index % len(families)]
            tags = ["fresh_rerunnable", "event_forensic", "non_gta"]
            if family.startswith("archive"):
                tags = ["fresh_rerunnable", "archive", "resolved_or_partial", "non_gta"]
            elif family == "sports_crypto":
                tags.append("sports_crypto")
            elif family == "gta_or_known_cluster":
                tags.append("gta_or_known_cluster")
            else:
                tags.append("politics_world")
            mode = "archive" if "archive" in tags else "event_forensic"
            targets.append(
                {
                    "label": f"target-{index}",
                    "mode": mode,
                    "inputType": "archive_window" if mode == "archive" else "market_url",
                    "inputValue": f"value-{index}",
                    "freshRerunnable": True,
                    "auditOnly": False,
                    "cacheOnlyOk": True,
                    "networkAllowed": True,
                    "targetFamily": family,
                    "tags": tags,
                }
            )
            target_results.append(
                {
                    "label": f"target-{index}",
                    "mode": mode,
                    "status": status,
                    "targetFamily": family,
                    "tags": tags,
                }
            )
        config = root / "corpus_config.json"
        corpus = root / "corpus_output.json"
        diag = root / "strong_diag.json"
        consistency_path = root / "consistency.json"
        prewarm_path = root / "prewarm.json"
        config.write_text(json.dumps({"targets": targets}), encoding="utf-8")
        status_counts = Counter(statuses)
        audit_summary = {
            "total_rows_inspected": unique_visible + 10,
            "rawVisibleRows": unique_visible,
            "uniqueVisibleRows": unique_visible,
            "rawStrongRiskRows": raw_strong,
            "uniqueStrongRiskRows": unique_strong,
            "rawHardEvidenceReviewRows": 5,
            "uniqueHardEvidenceReviewRows": 5,
            "strongRiskDedupeRatio": 1.0,
            "hardEvidenceReviewDedupeRatio": 1.0,
            "strong_risk_exact_provenance_by_target_status": {
                "fresh_generated": {
                    "strong_risk_rows": raw_strong,
                    "source_attribution_issue_distribution": {
                        "schema_propagation_gap": source_repair_rows,
                    },
                }
            },
        }
        corpus.write_text(
            json.dumps(
                {
                    "target_results": target_results,
                    "completed_targets": len(statuses),
                    "skipped_targets": 0,
                    "aborted_targets": 0,
                    "funding_enabled_targets": status_counts["completed_funding_enabled"],
                    "cache_only_targets": status_counts["completed_cache_only"],
                    "funding_blocked_targets": status_counts["completed_funding_blocked"],
                    "audit_summary": audit_summary,
                    "rawVisibleRows": unique_visible,
                    "uniqueVisibleRows": unique_visible,
                    "rawStrongRiskRows": raw_strong,
                    "uniqueStrongRiskRows": unique_strong,
                    "rawHardEvidenceReviewRows": 5,
                    "uniqueHardEvidenceReviewRows": 5,
                    "strongRiskDedupeRatio": 1.0,
                    "hardEvidenceReviewDedupeRatio": 1.0,
                }
            ),
            encoding="utf-8",
        )
        diag.write_text(
            json.dumps(
                {
                    "rawStrongRiskRows": raw_strong,
                    "uniqueStrongRiskRows": unique_strong,
                    "strongRiskRowsWithGateTraceAvailable": traced,
                    "strongRiskRowsWithoutGateTrace": max(0, raw_strong - traced),
                    "hardInvalidConditionCounts": her_invalid or {},
                    "freshUniqueGateLeakageCandidateRows": fresh_unique_gate_leakage,
                    "potentialGateLeakageCandidateRows": fresh_unique_gate_leakage,
                }
            ),
            encoding="utf-8",
        )
        consistency_path.write_text(json.dumps({"classification": consistency}), encoding="utf-8")
        prewarm_payload = prewarm or {
            "funding_candidate_targets": 3,
            "wallet_time_windows_found": 8,
            "wallet_time_windows_attempted": 8,
            "cache_hits_observed": 8,
            "cache_misses_observed": 0,
            "cache_writes": 0,
            "rpc_failures": 0,
            "rate_limits": 0,
            "targets_left_unprewarmed": 0,
            "prewarm_coverage_by_target_family": {"politics_world_event_forensic": {"targets": 3}},
        }
        prewarm_path.write_text(json.dumps(prewarm_payload), encoding="utf-8")
        return {
            "config": config,
            "corpus": corpus,
            "diag": diag,
            "consistency": consistency_path,
            "prewarm": prewarm_path,
        }

    def _build_readiness_from_fixture(self, paths: dict[str, Path]) -> dict:
        return build_readiness(
            corpus_config_path=paths["config"],
            corpus_output_path=paths["corpus"],
            strong_risk_diagnostic_path=paths["diag"],
            prewarm_path=paths["prewarm"],
            consistency_path=paths["consistency"],
        )

    def test_readiness_returns_cache_only_for_cache_only_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._write_readiness_fixture(
                root,
                statuses=["completed_cache_only"] * 8,
                families=["politics_world_event_forensic", "sports_crypto", "archive_politics_world"],
                traced=30,
            )
            summary = self._build_readiness_from_fixture(paths)
        self.assertEqual(summary["readinessClassification"], "not_ready_corpus_too_cache_only")
        self.assertEqual(summary["recommendation"], "strong_risk_gate_review_not_ready_cache_only")

    def test_readiness_returns_corpus_too_narrow_for_insufficient_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._write_readiness_fixture(
                root,
                statuses=["completed_funding_enabled"] * 6,
                families=["politics_world_event_forensic"],
            )
            summary = self._build_readiness_from_fixture(paths)
        self.assertEqual(summary["readinessClassification"], "not_ready_corpus_too_narrow")

    def test_readiness_returns_ready_no_gate_issue_when_thresholds_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._write_readiness_fixture(
                root,
                statuses=["completed_funding_enabled"] * 9,
                families=["politics_world_event_forensic", "sports_crypto", "archive_politics_world"],
            )
            summary = self._build_readiness_from_fixture(paths)
        self.assertEqual(summary["readinessClassification"], "ready_no_gate_issue_observed")
        self.assertEqual(summary["recommendation"], "continue_validation_no_model_change")

    def test_readiness_returns_gate_review_only_for_fresh_unique_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._write_readiness_fixture(
                root,
                statuses=["completed_funding_enabled"] * 9,
                families=["politics_world_event_forensic", "sports_crypto", "archive_politics_world"],
                fresh_unique_gate_leakage=2,
            )
            summary = self._build_readiness_from_fixture(paths)
        self.assertEqual(summary["readinessClassification"], "ready_for_strong_risk_gate_review")
        self.assertEqual(summary["recommendation"], "strong_risk_gate_review_ready")

    def test_readiness_consumes_prewarm_report_and_missing_optional_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._write_readiness_fixture(
                root,
                statuses=["completed_funding_enabled"] * 9,
                families=["politics_world_event_forensic", "sports_crypto", "archive_politics_world"],
                prewarm={
                    "funding_candidate_targets": 5,
                    "wallet_time_windows_found": 10,
                    "wallet_time_windows_attempted": 8,
                    "cache_hits_observed": 6,
                    "cache_misses_observed": 2,
                    "cache_writes": 1,
                    "rpc_failures": 0,
                    "rate_limits": 0,
                    "targets_left_unprewarmed": 2,
                    "trace_timeouts_observed": 1,
                    "max_trace_timeouts": 3,
                    "stop_reason": "max_total_traces",
                    "prewarm_coverage_by_target_family": {"sports_crypto": {"targets": 2}},
                },
            )
            summary = build_readiness(
                corpus_config_path=paths["config"],
                corpus_output_path=paths["corpus"],
                strong_risk_diagnostic_path=paths["diag"],
                prewarm_path=paths["prewarm"],
                consistency_path=paths["consistency"],
            )
        self.assertEqual(summary["funding"]["fundingCandidateTargets"], 5)
        self.assertEqual(summary["funding"]["cacheWrites"], 1)
        self.assertEqual(summary["funding"]["traceTimeoutsObserved"], 1)
        self.assertEqual(summary["funding"]["maxTraceTimeouts"], 3)
        self.assertEqual(summary["funding"]["stopReason"], "max_total_traces")
        self.assertIn("sports_crypto", summary["funding"]["prewarmCoverageByTargetFamily"])

    def test_readiness_requires_raw_unique_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._write_readiness_fixture(
                root,
                statuses=["completed_funding_enabled"] * 9,
                families=["politics_world_event_forensic", "sports_crypto", "archive_politics_world"],
                consistency="reporting consistency repair needed",
            )
            summary = self._build_readiness_from_fixture(paths)
        self.assertFalse(summary["readinessThresholds"]["reportConsistencyPasses"])
        self.assertNotEqual(summary["readinessClassification"], "ready_no_gate_issue_observed")

    def test_readiness_routes_source_and_her_repairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_paths = self._write_readiness_fixture(
                root / "source",
                statuses=["completed_funding_enabled"] * 9,
                families=["politics_world_event_forensic", "sports_crypto", "archive_politics_world"],
                source_repair_rows=1,
            )
            her_paths = self._write_readiness_fixture(
                root / "her",
                statuses=["completed_funding_enabled"] * 9,
                families=["politics_world_event_forensic", "sports_crypto", "archive_politics_world"],
                her_invalid={"proxy_only": 1},
            )
            source_summary = self._build_readiness_from_fixture(source_paths)
            her_summary = self._build_readiness_from_fixture(her_paths)
        self.assertEqual(source_summary["readinessClassification"], "source_attribution_repair_needed")
        self.assertEqual(her_summary["readinessClassification"], "hard_evidence_routing_repair_needed")

    def test_candidate_recall_audit_reads_corpus_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "corpus.json"
            corpus.write_text(
                json.dumps(
                    {
                        "selected_output_paths": [],
                        "audit_summary": {
                            "pre_admission_funnel": {
                                "total_near_miss_groups": 0,
                                "subthreshold_above_floor_trades": 0,
                                "grouped_subthreshold_groups": 0,
                                "strict_funding_groups_found": 0,
                                "total_validated": 0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            summary = summarize_candidate_recall([corpus])
        self.assertEqual(summary["classification"], "no recall opportunity observed")

    def test_candidate_recall_audit_classifies_rules_too_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "corpus.json"
            corpus.write_text(
                json.dumps(
                    {
                        "selected_output_paths": [],
                        "audit_summary": {
                            "pre_admission_funnel": {
                                "total_near_miss_groups": 77,
                                "total_validated": 0,
                                "top_rejection_reasons": {"time_band_exceeded": 70},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            summary = summarize_candidate_recall([corpus])
        self.assertEqual(summary["classification"], "rules too strict but requires human approval")
        self.assertEqual(summary["top_non_admission_reasons"]["time_band_exceeded"], 70)

    def test_report_consistency_matching_report_set_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "post_v2_corpus_20260503_000000.json"
            audit = root / "post_v2_corpus_audit_20260503_000000.json"
            acceptance = root / "post_v2_acceptance_report_20260503_000000.json"
            deep = root / "strong_risk_deep_dive_20260503_000000.json"
            recall = root / "candidate_recall_audit_20260503_000000.json"
            corpus.write_text(
                json.dumps(
                    {
                        "total_targets": 2,
                        "completed_targets": 2,
                        "cache_only_targets": 1,
                        "funding_enabled_targets": 1,
                        "funding_blocked_targets": 0,
                        "target_status_counts": {"audit_only_saved_output": 0},
                        "completed_target_tag_counts": {"fresh_rerunnable": 2},
                        "audit_summary": {
                            "total_rows_inspected": 10,
                            "event_forensic_rows_inspected": 6,
                            "archive_rows_inspected": 4,
                            "visible_rows": 3,
                            "rawVisibleRows": 3,
                            "uniqueVisibleRows": 3,
                            "visibleDedupeRatio": 1.0,
                            "normal_candidate_rows": 2,
                            "pre_admitted_candidate_rows": 1,
                            "strong_risk_rows": 1,
                            "rawStrongRiskRows": 1,
                            "uniqueStrongRiskRows": 1,
                            "strongRiskDedupeRatio": 1.0,
                            "hard_evidence_review_rows": 1,
                            "rawHardEvidenceReviewRows": 1,
                            "uniqueHardEvidenceReviewRows": 1,
                            "hardEvidenceReviewDedupeRatio": 1.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            audit.write_text(
                json.dumps(
                    {
                        "total_rows_inspected": 10,
                        "event_forensic_rows_inspected": 6,
                        "archive_rows_inspected": 4,
                        "visible_rows": 3,
                        "rawVisibleRows": 3,
                        "uniqueVisibleRows": 3,
                        "visibleDedupeRatio": 1.0,
                        "normal_candidate_rows": 2,
                        "pre_admitted_candidate_rows": 1,
                        "strong_risk_rows": 1,
                        "rawStrongRiskRows": 1,
                        "uniqueStrongRiskRows": 1,
                        "strongRiskDedupeRatio": 1.0,
                        "hard_evidence_review_rows": 1,
                        "rawHardEvidenceReviewRows": 1,
                        "uniqueHardEvidenceReviewRows": 1,
                        "hardEvidenceReviewDedupeRatio": 1.0,
                    }
                ),
                encoding="utf-8",
            )
            acceptance.write_text(
                json.dumps(
                    {
                        "rows_inspected": 10,
                        "visible_rows": 3,
                        "rawVisibleRows": 3,
                        "uniqueVisibleRows": 3,
                        "visibleDedupeRatio": 1.0,
                        "strong_risk_rows": 1,
                        "rawStrongRiskRows": 1,
                        "uniqueStrongRiskRows": 1,
                        "strongRiskDedupeRatio": 1.0,
                        "hard_evidence_review_rows": 1,
                        "rawHardEvidenceReviewRows": 1,
                        "uniqueHardEvidenceReviewRows": 1,
                        "hardEvidenceReviewDedupeRatio": 1.0,
                        "total_targets": 2,
                        "completed_targets": 2,
                        "cache_only_targets": 1,
                        "funding_enabled_targets": 1,
                        "funding_blocked_targets": 0,
                        "target_status_counts": {"audit_only_saved_output": 0},
                        "completed_target_tag_counts": {"fresh_rerunnable": 2},
                    }
                ),
                encoding="utf-8",
            )
            deep.write_text(json.dumps({"strong_risk_rows": 1}), encoding="utf-8")
            recall.write_text(json.dumps({"classification": "no recall opportunity observed"}), encoding="utf-8")
            summary = summarize_report_consistency(
                corpus_json=corpus,
                audit_json=audit,
                deep_dive_json=deep,
                acceptance_json=acceptance,
                recall_json=recall,
                project_memory_path=root / "PROJECT_MEMORY.md",
            )
        self.assertEqual(summary["classification"], "count_reporting_consistent")
        self.assertEqual(summary["metrics"]["corpus"]["rowsInspected"], 10)

    def test_report_consistency_flags_mismatched_rows_inspected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "post_v2_corpus_20260503_000000.json"
            audit = root / "post_v2_corpus_audit_20260503_000000.json"
            acceptance = root / "post_v2_acceptance_report_20260503_000000.json"
            deep = root / "strong_risk_deep_dive_20260503_000000.json"
            recall = root / "candidate_recall_audit_20260503_000000.json"
            corpus.write_text(
                json.dumps(
                    {
                        "total_targets": 1,
                        "completed_targets": 1,
                        "audit_summary": {
                            "total_rows_inspected": 10,
                            "visible_rows": 1,
                            "strong_risk_rows": 0,
                            "hard_evidence_review_rows": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            audit.write_text(json.dumps({"total_rows_inspected": 11}), encoding="utf-8")
            acceptance.write_text(
                json.dumps(
                    {
                        "rows_inspected": 10,
                        "visible_rows": 1,
                        "strong_risk_rows": 0,
                        "hard_evidence_review_rows": 0,
                        "total_targets": 1,
                        "completed_targets": 1,
                    }
                ),
                encoding="utf-8",
            )
            deep.write_text(json.dumps({"strong_risk_rows": 0}), encoding="utf-8")
            recall.write_text(json.dumps({}), encoding="utf-8")
            summary = summarize_report_consistency(
                corpus_json=corpus,
                audit_json=audit,
                deep_dive_json=deep,
                acceptance_json=acceptance,
                recall_json=recall,
                project_memory_path=root / "PROJECT_MEMORY.md",
            )
        self.assertEqual(summary["classification"], "reporting consistency repair needed")
        self.assertTrue(any(warning.get("metric") == "rowsInspected" for warning in summary["warnings"]))

    def test_report_consistency_ignores_unlinked_acceptance_for_selected_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "post_v2_corpus_20260503_000000.json"
            audit = root / "post_v2_corpus_audit_20260503_000000.json"
            deep = root / "strong_risk_deep_dive_20260503_000000.json"
            old_acceptance = root / "post_v2_acceptance_report_20260502_000000.json"
            recall = root / "candidate_recall_audit_20260503_000000.json"
            audit_payload = {
                "total_rows_inspected": 10,
                "visible_rows": 3,
                "rawVisibleRows": 3,
                "uniqueVisibleRows": 3,
                "visibleDedupeRatio": 1.0,
                "strong_risk_rows": 1,
                "rawStrongRiskRows": 1,
                "uniqueStrongRiskRows": 1,
                "strongRiskDedupeRatio": 1.0,
                "hard_evidence_review_rows": 1,
                "rawHardEvidenceReviewRows": 1,
                "uniqueHardEvidenceReviewRows": 1,
                "hardEvidenceReviewDedupeRatio": 1.0,
            }
            corpus.write_text(
                json.dumps(
                    {
                        "total_targets": 1,
                        "completed_targets": 1,
                        "target_status_counts": {"audit_only_saved_output": 0},
                        "audit_summary": audit_payload,
                    }
                ),
                encoding="utf-8",
            )
            audit.write_text(json.dumps(audit_payload), encoding="utf-8")
            deep.write_text(json.dumps({"strong_risk_rows": 1}), encoding="utf-8")
            old_acceptance.write_text(
                json.dumps(
                    {
                        "source_corpus_json": str(root / "post_v2_corpus_20260502_000000.json"),
                        "rows_inspected": 999,
                        "visible_rows": 999,
                        "strong_risk_rows": 999,
                    }
                ),
                encoding="utf-8",
            )
            recall.write_text(json.dumps({}), encoding="utf-8")
            summary = summarize_report_consistency(
                corpus_json=corpus,
                audit_json=audit,
                deep_dive_json=deep,
                recall_json=recall,
                project_memory_path=root / "PROJECT_MEMORY.md",
            )
        self.assertEqual(summary["classification"], "count_reporting_consistent")
        self.assertNotIn("acceptance", summary["metrics"])

    def test_report_consistency_flags_raw_only_headline_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "post_v2_corpus_20260503_000000.json"
            audit = root / "post_v2_corpus_audit_20260503_000000.json"
            acceptance = root / "post_v2_acceptance_report_20260503_000000.json"
            deep = root / "strong_risk_deep_dive_20260503_000000.json"
            recall = root / "candidate_recall_audit_20260503_000000.json"
            audit_payload = {
                "total_rows_inspected": 1,
                "visible_rows": 1,
                "rawVisibleRows": 1,
                "uniqueVisibleRows": 1,
                "visibleDedupeRatio": 1.0,
                "strong_risk_rows": 1,
                "rawStrongRiskRows": 1,
                "uniqueStrongRiskRows": 1,
                "strongRiskDedupeRatio": 1.0,
                "hard_evidence_review_rows": 0,
                "rawHardEvidenceReviewRows": 0,
                "uniqueHardEvidenceReviewRows": 0,
                "hardEvidenceReviewDedupeRatio": 0.0,
            }
            corpus.write_text(
                json.dumps(
                    {
                        "total_targets": 1,
                        "completed_targets": 1,
                        "target_status_counts": {"audit_only_saved_output": 0},
                        "audit_summary": audit_payload,
                    }
                ),
                encoding="utf-8",
            )
            corpus.with_suffix(".md").write_text("- Strong Risk rows: 1\n", encoding="utf-8")
            audit.write_text(json.dumps(audit_payload), encoding="utf-8")
            acceptance.write_text(
                json.dumps({"rows_inspected": 1, "total_targets": 1, "completed_targets": 1, **audit_payload}),
                encoding="utf-8",
            )
            deep.write_text(json.dumps({"strong_risk_rows": 1}), encoding="utf-8")
            recall.write_text(json.dumps({}), encoding="utf-8")
            summary = summarize_report_consistency(
                corpus_json=corpus,
                audit_json=audit,
                deep_dive_json=deep,
                acceptance_json=acceptance,
                recall_json=recall,
                project_memory_path=root / "PROJECT_MEMORY.md",
            )
        self.assertIn("headline_counts_raw_only", {warning["code"] for warning in summary["warnings"]})

    def test_report_consistency_keeps_raw_rows_separate_from_inspected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "post_v2_corpus_20260503_000000.json"
            audit = root / "post_v2_corpus_audit_20260503_000000.json"
            acceptance = root / "post_v2_acceptance_report_20260503_000000.json"
            deep = root / "strong_risk_deep_dive_20260503_000000.json"
            recall = root / "candidate_recall_audit_20260503_000000.json"
            corpus.write_text(
                json.dumps(
                    {
                        "total_targets": 1,
                        "completed_targets": 1,
                        "audit_summary": {
                            "total_rows_inspected": 5,
                            "visible_rows": 1,
                            "strong_risk_rows": 0,
                            "hard_evidence_review_rows": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            audit.write_text(json.dumps({"total_rows_inspected": 5}), encoding="utf-8")
            acceptance.write_text(
                json.dumps(
                    {
                        "rows_inspected": 5,
                        "rawRowsScanned": 100,
                        "visible_rows": 1,
                        "strong_risk_rows": 0,
                        "hard_evidence_review_rows": 0,
                        "total_targets": 1,
                        "completed_targets": 1,
                    }
                ),
                encoding="utf-8",
            )
            deep.write_text(json.dumps({"strong_risk_rows": 0}), encoding="utf-8")
            recall.write_text(json.dumps({}), encoding="utf-8")
            summary = summarize_report_consistency(
                corpus_json=corpus,
                audit_json=audit,
                deep_dive_json=deep,
                acceptance_json=acceptance,
                recall_json=recall,
                project_memory_path=root / "PROJECT_MEMORY.md",
            )
        self.assertFalse(
            any(warning.get("code") == "raw_rows_scanned_reported_as_rows_inspected" for warning in summary["warnings"])
        )

    def test_report_consistency_missing_field_is_unknown_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "post_v2_corpus_20260503_000000.json"
            audit = root / "post_v2_corpus_audit_20260503_000000.json"
            acceptance = root / "post_v2_acceptance_report_20260503_000000.json"
            deep = root / "strong_risk_deep_dive_20260503_000000.json"
            recall = root / "candidate_recall_audit_20260503_000000.json"
            corpus.write_text(json.dumps({"audit_summary": {}, "total_targets": 1}), encoding="utf-8")
            audit.write_text(json.dumps({}), encoding="utf-8")
            acceptance.write_text(json.dumps({}), encoding="utf-8")
            deep.write_text(json.dumps({}), encoding="utf-8")
            recall.write_text(json.dumps({}), encoding="utf-8")
            summary = summarize_report_consistency(
                corpus_json=corpus,
                audit_json=audit,
                deep_dive_json=deep,
                acceptance_json=acceptance,
                recall_json=recall,
                project_memory_path=root / "PROJECT_MEMORY.md",
            )
        self.assertEqual(summary["metrics"]["corpus"]["rowsInspected"], "unknown")

    def test_report_consistency_handles_legacy_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "post_v2_corpus_20260503_000000.json"
            audit = root / "post_v2_corpus_audit_20260503_000000.json"
            acceptance = root / "post_v2_acceptance_report_20260503_000000.json"
            deep = root / "strong_risk_deep_dive_20260503_000000.json"
            recall = root / "candidate_recall_audit_20260503_000000.json"
            for path in (corpus, audit, acceptance, deep, recall):
                path.write_text(json.dumps({"legacy": True}), encoding="utf-8")
            summary = summarize_report_consistency(
                corpus_json=corpus,
                audit_json=audit,
                deep_dive_json=deep,
                acceptance_json=acceptance,
                recall_json=recall,
                project_memory_path=root / "PROJECT_MEMORY.md",
            )
        self.assertEqual(summary["metrics"]["corpus"]["visibleRows"], "unknown")

    def test_report_consistency_does_not_select_probe_when_corpus_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "post_v2_corpus_20260503_000000.json"
            audit = root / "post_v2_corpus_audit_20260503_000000.json"
            acceptance = root / "post_v2_acceptance_report_20260503_000000.json"
            deep = root / "strong_risk_deep_dive_20260503_000000.json"
            recall = root / "candidate_recall_audit_20260503_000000.json"
            corpus.write_text(
                json.dumps(
                    {
                        "validationPolicy": "network_probe",
                        "total_targets": 1,
                        "completed_targets": 1,
                        "audit_summary": {"total_rows_inspected": 1},
                    }
                ),
                encoding="utf-8",
            )
            audit.write_text(json.dumps({"total_rows_inspected": 1}), encoding="utf-8")
            acceptance.write_text(json.dumps({"rows_inspected": 1}), encoding="utf-8")
            deep.write_text(json.dumps({}), encoding="utf-8")
            recall.write_text(json.dumps({}), encoding="utf-8")
            summary = summarize_report_consistency(
                corpus_json=corpus,
                audit_json=audit,
                deep_dive_json=deep,
                acceptance_json=acceptance,
                recall_json=recall,
                project_memory_path=root / "PROJECT_MEMORY.md",
            )
        self.assertEqual(summary["metrics"]["corpus"]["rowsInspected"], 1)

    def test_report_consistency_selects_diagnostics_matching_selected_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "validation_corpus_outputs"
            diagnostic_dir = root / "strong_risk_diagnostic_outputs"
            output_dir.mkdir()
            diagnostic_dir.mkdir()
            corpus = output_dir / "post_v2_corpus_20260503_010000.json"
            audit = output_dir / "post_v2_corpus_audit_20260503_010000.json"
            smoke_corpus = output_dir / "post_v2_corpus_20260503_020000.json"
            broad_drilldown = output_dir / "corpus_provenance_drilldown_20260503_010000.json"
            smoke_drilldown = output_dir / "corpus_provenance_drilldown_20260503_020000.json"
            broad_diagnostic = diagnostic_dir / "strong_risk_gate_diagnostic_20260503_010000.json"
            smoke_diagnostic = diagnostic_dir / "strong_risk_gate_diagnostic_20260503_020000.json"
            audit_metrics = {
                "total_rows_inspected": 10,
                "visible_rows": 4,
                "rawVisibleRows": 4,
                "uniqueVisibleRows": 2,
                "visibleDedupeRatio": 2.0,
                "strong_risk_rows": 3,
                "rawStrongRiskRows": 3,
                "uniqueStrongRiskRows": 2,
                "strongRiskDedupeRatio": 1.5,
                "hard_evidence_review_rows": 1,
                "rawHardEvidenceReviewRows": 1,
                "uniqueHardEvidenceReviewRows": 1,
                "hardEvidenceReviewDedupeRatio": 1.0,
            }
            corpus.write_text(
                json.dumps(
                    {
                        "validationPolicy": "cache_only",
                        "total_targets": 8,
                        "completed_targets": 8,
                        "cache_only_targets": 8,
                        "funding_enabled_targets": 0,
                        "funding_blocked_targets": 0,
                        "target_status_counts": {"audit_only_saved_output": 0},
                        "completed_target_tag_counts": {"fresh_rerunnable": 8},
                        "audit_summary": audit_metrics,
                        "audit_output_paths": {"json_path": str(audit)},
                    }
                ),
                encoding="utf-8",
            )
            audit.write_text(json.dumps(audit_metrics), encoding="utf-8")
            smoke_corpus.write_text(
                json.dumps(
                    {
                        "corpus_name": "post_v2_validation_corpus_smoke",
                        "validationPolicy": "cache_only",
                        "audit_summary": {"rawVisibleRows": 40, "uniqueVisibleRows": 20},
                    }
                ),
                encoding="utf-8",
            )
            broad_metrics = {
                "input_artifacts": {"corpus": str(corpus)},
                "rawVisibleRows": 4,
                "uniqueVisibleRows": 2,
                "visibleDedupeRatio": 2.0,
                "rawStrongRiskRows": 3,
                "uniqueStrongRiskRows": 2,
                "strongRiskDedupeRatio": 1.5,
                "rawHardEvidenceReviewRows": 1,
                "uniqueHardEvidenceReviewRows": 1,
                "hardEvidenceReviewDedupeRatio": 1.0,
            }
            smoke_metrics = {
                "input_artifacts": {"corpus": str(smoke_corpus)},
                "rawVisibleRows": 40,
                "uniqueVisibleRows": 20,
                "visibleDedupeRatio": 2.0,
                "rawStrongRiskRows": 30,
                "uniqueStrongRiskRows": 20,
                "strongRiskDedupeRatio": 1.5,
                "rawHardEvidenceReviewRows": 0,
                "uniqueHardEvidenceReviewRows": 0,
                "hardEvidenceReviewDedupeRatio": 0.0,
            }
            broad_drilldown.write_text(json.dumps(broad_metrics), encoding="utf-8")
            smoke_drilldown.write_text(json.dumps(smoke_metrics), encoding="utf-8")
            broad_diagnostic.write_text(json.dumps({"inputArtifacts": {"corpus": str(corpus)}, **broad_metrics}), encoding="utf-8")
            smoke_diagnostic.write_text(json.dumps({"inputArtifacts": {"corpus": str(smoke_corpus)}, **smoke_metrics}), encoding="utf-8")
            os.utime(broad_drilldown, (100, 100))
            os.utime(broad_diagnostic, (100, 100))
            os.utime(smoke_drilldown, (200, 200))
            os.utime(smoke_diagnostic, (200, 200))
            with mock.patch("tools.validate_report_consistency.REPO_ROOT", root), mock.patch(
                "tools.validate_report_consistency.DEFAULT_OUTPUT_DIR", Path("validation_corpus_outputs")
            ):
                summary = summarize_report_consistency(
                    corpus_json=corpus,
                    project_memory_path=root / "PROJECT_MEMORY.md",
                )
        self.assertEqual(summary["classification"], "count_reporting_consistent")
        self.assertEqual(summary["sources"][3]["json_path"], str(broad_drilldown))
        self.assertEqual(summary["sources"][4]["json_path"], str(broad_diagnostic))

    def test_network_diagnostics_identify_stalled_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "post_v2_corpus_20260503_000000.json"
            corpus.write_text(
                json.dumps(
                    {
                        "validationPolicy": "network_funding",
                        "fullNetworkAttempted": True,
                        "target_results": [
                            {
                                "label": "stalled",
                                "status": "aborted_rpc_stall",
                                "validationPhase": "Tracing blockchain linkage",
                                "validationAbortReason": "validation_funding_stall_timeout",
                                "validationKilledProcess": True,
                            }
                        ],
                        "audit_summary": {"pre_admission_funnel": {}},
                    }
                ),
                encoding="utf-8",
            )
            summary = summarize_network_funding_diagnostics([corpus])
        self.assertEqual(summary["network_targets_stalled"], 1)
        self.assertEqual(summary["stalled_targets"][0]["phase"], "Tracing blockchain linkage")

    def test_discover_validation_targets_from_local_event_and_archive_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_dir = root / "event_forensic_outputs" / "event_forensic_20260503_000000"
            event_dir.mkdir(parents=True)
            event_report = event_dir / "event_analysis.json"
            event_report.write_text(
                json.dumps(
                    {
                        "input_url": "https://polymarket.com/market/will-bitcoin-hit-150k-in-2025",
                        "selected_market_slug": "will-bitcoin-hit-150k-in-2025",
                        "analysis_scope": "market",
                        "summary": {"candidate_trade_count": 25, "unresolved_market_count": 1},
                    }
                ),
                encoding="utf-8",
            )
            archive_dir = root / ".inspoly_archive_researcher" / "reports"
            archive_dir.mkdir(parents=True)
            archive_report = archive_dir / "archive_research_20260503_000000.json"
            archive_report.write_text(
                json.dumps(
                    {
                        "range_start": "2026-05-01T00:00:00+00:00",
                        "range_end": "2026-05-01T01:00:00+00:00",
                        "topic_scope": "Sports,Crypto",
                        "candidate_trade_count": 5,
                    }
                ),
                encoding="utf-8",
            )
            corpus = root / "validation_corpus" / "post_v2_validation_corpus.json"
            corpus.parent.mkdir(parents=True)
            corpus.write_text(json.dumps({"targets": []}), encoding="utf-8")
            summary = discover_validation_targets(repo_root=root, corpus_path=corpus)
        self.assertGreaterEqual(summary["total_candidates"], 2)
        tags = summary["tag_counts"]
        self.assertGreaterEqual(tags.get("event_forensic", 0), 1)
        self.assertGreaterEqual(tags.get("archive", 0), 1)
        self.assertGreaterEqual(tags.get("sports_crypto", 0), 2)

    def test_discover_validation_targets_marks_saved_output_medium_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_dir = root / "event_forensic_outputs" / "event_forensic_20260503_000000"
            event_dir.mkdir(parents=True)
            (event_dir / "event_analysis.json").write_text(
                json.dumps({"summary": {"candidate_trade_count": 1}}),
                encoding="utf-8",
            )
            corpus = root / "validation_corpus" / "post_v2_validation_corpus.json"
            corpus.parent.mkdir(parents=True)
            corpus.write_text(json.dumps({"targets": []}), encoding="utf-8")
            summary = discover_validation_targets(repo_root=root, corpus_path=corpus)
        target = summary["targets"][0]
        self.assertEqual(target["confidence"], "medium")
        self.assertEqual(target["inputType"], "saved_output_replay")
        self.assertIn("audit_only_saved_output", target["tags"])
        self.assertFalse(target["freshRerunnable"])
        self.assertTrue(target["auditOnly"])
        self.assertIn("targetFamily", target)

    def test_discover_event_url_without_child_market_uses_event_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_dir = root / "event_forensic_outputs" / "event_forensic_20260503_000000"
            event_dir.mkdir(parents=True)
            (event_dir / "event_analysis.json").write_text(
                json.dumps(
                    {
                        "input_url": "https://polymarket.com/event/example-event",
                        "analysis_scope": "market",
                        "summary": {"candidate_trade_count": 1},
                    }
                ),
                encoding="utf-8",
            )
            corpus = root / "validation_corpus" / "post_v2_validation_corpus.json"
            corpus.parent.mkdir(parents=True)
            corpus.write_text(json.dumps({"targets": []}), encoding="utf-8")
            summary = discover_validation_targets(repo_root=root, corpus_path=corpus)
        target = summary["targets"][0]
        self.assertEqual(target["inputType"], "event_url")
        self.assertEqual(target["scopeSettings"]["analysisScope"], "event")
        self.assertTrue(target["freshRerunnable"])
        self.assertTrue(target["networkAllowed"])


class ValidationFundingCircuitBreakerTests(unittest.TestCase):
    def _validation_env(self, **overrides: str):
        base = {
            "INSPOLY_VALIDATION_MODE": "1",
            "INSPOLY_VALIDATION_ALLOW_NETWORK_FUNDING": "1",
            "INSPOLY_VALIDATION_MAX_FUNDING_TRACES_PER_BUNDLE": "50",
            "INSPOLY_VALIDATION_MAX_FUNDING_TRACE_FAILURES_PER_BUNDLE": "10",
            "INSPOLY_VALIDATION_MAX_CONSECUTIVE_RPC_FAILURES": "5",
            "INSPOLY_FUNDING_TRACE_CACHE_ENABLED": "0",
        }
        base.update(overrides)
        return mock.patch.dict(os.environ, base, clear=False)

    def test_cache_only_mode_returns_unknown_without_rpc(self) -> None:
        with self._validation_env(INSPOLY_VALIDATION_ALLOW_NETWORK_FUNDING="0"):
            resolver = FundingResolver(rpc_url="https://example.invalid", persistent_cache_enabled=False)
            with mock.patch.object(resolver, "_block_before_timestamp", side_effect=AssertionError("rpc called")):
                context = resolver.analyze("0x1111111111111111111111111111111111111111", datetime.now(UTC))
        self.assertEqual(context.funding_evidence_grade, FUNDING_EVIDENCE_UNKNOWN)
        self.assertIn("validation_cache_only", context.error or "")
        self.assertEqual(resolver.health().fundingTraceSkippedCount, 1)

    def test_network_funding_mode_respects_max_traces_per_bundle(self) -> None:
        with self._validation_env(INSPOLY_VALIDATION_MAX_FUNDING_TRACES_PER_BUNDLE="1"):
            resolver = FundingResolver(rpc_url="https://example.invalid", persistent_cache_enabled=False)
            with mock.patch.object(resolver, "_block_before_timestamp", return_value=None) as block_lookup:
                first = resolver.analyze("0x1111111111111111111111111111111111111111", datetime.now(UTC))
                second = resolver.analyze("0x2222222222222222222222222222222222222222", datetime.now(UTC))
        self.assertEqual(first.funding_evidence_grade, FUNDING_EVIDENCE_UNKNOWN)
        self.assertEqual(second.funding_evidence_grade, FUNDING_EVIDENCE_UNKNOWN)
        self.assertIn("validation_funding_trace_limit_hit", second.error or "")
        self.assertEqual(block_lookup.call_count, 1)
        self.assertTrue(resolver.health().validationFundingTraceLimitHit)

    def test_consecutive_rpc_failure_limit_stops_bundle_funding(self) -> None:
        with self._validation_env(INSPOLY_VALIDATION_MAX_CONSECUTIVE_RPC_FAILURES="1"):
            resolver = FundingResolver(rpc_url="https://example.invalid", persistent_cache_enabled=False)
            with mock.patch.object(resolver, "_block_before_timestamp", return_value=None) as block_lookup:
                resolver.analyze("0x1111111111111111111111111111111111111111", datetime.now(UTC))
                second = resolver.analyze("0x2222222222222222222222222222222222222222", datetime.now(UTC))
        self.assertIn("validation_consecutive_rpc_failure_limit_hit", second.error or "")
        self.assertEqual(second.funding_evidence_grade, FUNDING_EVIDENCE_UNKNOWN)
        self.assertEqual(block_lookup.call_count, 1)
        self.assertTrue(resolver.health().validationRpcFailureLimitHit)

    def test_validation_log_chunk_budget_returns_unknown_not_none(self) -> None:
        with self._validation_env(INSPOLY_VALIDATION_MAX_LOG_CHUNKS_PER_TRACE="1"):
            resolver = FundingResolver(rpc_url="https://example.invalid", persistent_cache_enabled=False)
            with mock.patch.object(resolver, "_block_before_timestamp", return_value=100):
                with mock.patch.object(resolver, "_get_usdc_logs_chunk", return_value=[]) as log_lookup:
                    context = resolver.analyze(
                        "0x1111111111111111111111111111111111111111",
                        datetime.now(UTC),
                    )
        self.assertEqual(context.funding_evidence_grade, FUNDING_EVIDENCE_UNKNOWN)
        self.assertIn("validation_funding_trace_log_chunk_limit_hit", context.error or "")
        self.assertEqual(log_lookup.call_count, 1)
        self.assertEqual(resolver.health().fundingTraceFailedCount, 1)

    def test_validation_block_lookup_uses_bounded_estimate(self) -> None:
        with self._validation_env(
            INSPOLY_VALIDATION_APPROXIMATE_BLOCK_LOOKUP="1",
            INSPOLY_POLYGON_AVERAGE_BLOCK_SECONDS="2",
        ):
            resolver = FundingResolver(rpc_url="https://example.invalid", persistent_cache_enabled=False)
            resolver._latest_block_number = 1000
            with mock.patch.object(resolver, "_block_timestamp", return_value=10_000) as timestamp_lookup:
                block = resolver._block_before_timestamp(
                    datetime.fromtimestamp(9_900, UTC)
                )
        self.assertEqual(block, 950)
        timestamp_lookup.assert_called_once_with(1000)


if __name__ == "__main__":
    unittest.main()
