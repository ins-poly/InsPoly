from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.operator_rpc_recovery_package import build_recovery_package, write_outputs


class OperatorRpcRecoveryPackageTests(unittest.TestCase):
    def _write_inputs(self, root: Path) -> dict[str, Path]:
        output_dir = root / "validation_corpus_outputs"
        health_dir = root / "funding_health_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        health_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "output_dir": output_dir,
            "healthcheck": health_dir / "funding_resolver_healthcheck_20260505_000000.json",
            "trace": output_dir / "trace_method_diagnostic_20260505_000000.json",
            "prewarm": output_dir / "funding_cache_prewarm_20260505_000000.json",
            "smoke": output_dir / "post_v2_corpus_20260505_000000.json",
            "terminal": output_dir / "validation_corpus_terminal_failure_20260505_000000.json",
            "readiness": output_dir / "gate_decision_readiness_20260505_000000.json",
            "action": output_dir / "autonomous_next_action_20260505_000000.json",
        }
        paths["healthcheck"].write_text(json.dumps({"overall_status": "available_for_funding_trace"}), encoding="utf-8")
        paths["trace"].write_text(
            json.dumps(
                {
                    "classification": "trace_method_path_available_with_endpoint_errors",
                    "recommended_next_step": "run_bounded_12_target_validation_smoke_with_endpoint_quarantine",
                    "configured_getlogs_block_chunk": 750,
                    "method_summary": {"eth_getLogs": {"available": 3, "timeout": 1}},
                }
            ),
            encoding="utf-8",
        )
        paths["prewarm"].write_text(
            json.dumps(
                {
                    "wallet_time_windows_found": 52,
                    "wallet_time_windows_attempted": 48,
                    "cache_hits_observed": 14,
                    "cache_misses_observed": 33,
                    "cache_writes": 33,
                    "trace_outcome_status_counts": {"success": 12, "failure": 35},
                    "rpc_failures": 35,
                    "trace_timeouts_observed": 1,
                    "targets_left_unprewarmed": 43,
                    "stop_reason": "max_total_traces",
                    "prewarm_coverage_by_target_family": {
                        "politics_world_event_forensic": {
                            "windowsFound": 12,
                            "windowsAttempted": 9,
                            "traceOutcome_failure": 8,
                            "traceTimeouts": 1,
                            "targetsLeftUnprewarmed": 17,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        paths["smoke"].write_text(
            json.dumps(
                {
                    "networkProbeStatus": "network_probe_stalled",
                    "cacheOnlyFallbackUsed": True,
                    "funding_enabled_targets": 0,
                    "cache_only_targets": 6,
                    "funding_trace_attempted": 0,
                }
            ),
            encoding="utf-8",
        )
        paths["terminal"].write_text(json.dumps({"terminalReason": "signal_15"}), encoding="utf-8")
        paths["readiness"].write_text(
            json.dumps(
                {
                    "readinessClassification": "not_ready_corpus_too_cache_only",
                    "recommendation": "strong_risk_gate_review_not_ready_cache_only",
                }
            ),
            encoding="utf-8",
        )
        paths["action"].write_text(
            json.dumps(
                {
                    "decision": "stop_human_approval_required",
                    "ready_to_copy_codex_prompt": "prompt",
                }
            ),
            encoding="utf-8",
        )
        return paths

    def test_recovery_package_masks_endpoint_secrets_and_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            paths = self._write_inputs(Path(tmp))
            package = build_recovery_package(
                output_dir=paths["output_dir"],
                healthcheck=paths["healthcheck"],
                trace_diagnostic=paths["trace"],
                prewarm=paths["prewarm"],
                smoke_corpus=paths["smoke"],
                terminal_failure=paths["terminal"],
                readiness=paths["readiness"],
                action=paths["action"],
                repo_root=Path(tmp),
                endpoint_urls=["https://user:secret@polygon.example.test/private-token"],
            )
            text = json.dumps(package)
            outputs = write_outputs(package, paths["output_dir"], timestamp="20260505_010101")
            markdown = Path(outputs["markdown_path"]).read_text(encoding="utf-8")
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())

        self.assertEqual(package["active_endpoint_labels"], ["polygon.example.test"])
        self.assertEqual(package["configuration_status"], "existing_env_config_rechecked_no_new_operator_approved_rpc_configuration_detected")
        self.assertTrue(package["operator_decision_required"])
        self.assertNotIn("user:secret", text)
        self.assertNotIn("private-token", text)
        self.assertIn("polygon.example.test", markdown)

    def test_operator_approved_flag_records_present_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            paths = self._write_inputs(Path(tmp))
            package = build_recovery_package(
                output_dir=paths["output_dir"],
                healthcheck=paths["healthcheck"],
                trace_diagnostic=paths["trace"],
                prewarm=paths["prewarm"],
                smoke_corpus=paths["smoke"],
                terminal_failure=paths["terminal"],
                readiness=paths["readiness"],
                action=paths["action"],
                operator_approved_config_present=True,
                repo_root=Path(tmp),
                endpoint_urls=["https://polygon.example.test"],
            )

        self.assertEqual(package["configuration_status"], "operator_approved_rpc_configuration_present")
        self.assertFalse(package["operator_decision_required"])


if __name__ == "__main__":
    unittest.main()
