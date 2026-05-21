from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.strategic_backlog_dashboard import build_dashboard, write_outputs


class StrategicBacklogDashboardTests(unittest.TestCase):
    def test_dashboard_groups_status_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backlog_path = root / "backlog.json"
            validation_dir = root / "validation_corpus_outputs"
            validation_dir.mkdir()
            backlog_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "DONE",
                                "title": "Done task",
                                "workstream": "Analyst-facing case quality",
                                "priority": "P0",
                                "blockedByRpc": False,
                                "requiresHumanApproval": False,
                                "modelBehaviorChange": False,
                                "riskLevel": "low",
                            },
                            {
                                "id": "RPC",
                                "title": "RPC task",
                                "workstream": "Validation/RPC readiness",
                                "priority": "P1",
                                "blockedByRpc": True,
                                "requiresHumanApproval": False,
                                "modelBehaviorChange": False,
                                "riskLevel": "medium",
                            },
                            {
                                "id": "APPROVAL",
                                "title": "Approval task",
                                "workstream": "Validation/RPC readiness",
                                "priority": "P2",
                                "blockedByRpc": False,
                                "requiresHumanApproval": True,
                                "modelBehaviorChange": True,
                                "riskLevel": "high",
                            },
                            {
                                "id": "OPEN",
                                "title": "Open task",
                                "workstream": "Report readability and executive summaries",
                                "priority": "P1",
                                "blockedByRpc": False,
                                "requiresHumanApproval": False,
                                "modelBehaviorChange": False,
                                "riskLevel": "low",
                                "commandsToRun": ["python3 tools/example.py"],
                                "testsToRun": ["python3 -m unittest"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (validation_dir / "gate_decision_readiness_20260505_000000.json").write_text(
                json.dumps({"readinessClassification": "not_ready_corpus_too_cache_only"}),
                encoding="utf-8",
            )
            (validation_dir / "operator_rpc_capacity_recovery_package_20260505_000000.json").write_text(
                json.dumps({"configuration_status": "no_new_operator_rpc_config_detected"}),
                encoding="utf-8",
            )
            payload = build_dashboard(
                backlog_path=backlog_path,
                validation_output_dir=validation_dir,
                completed_ids=["DONE"],
            )
        self.assertEqual(payload["status_counts"]["completed"], 1)
        self.assertEqual(payload["status_counts"]["blocked_by_rpc"], 1)
        self.assertEqual(payload["status_counts"]["human_approval_required"], 1)
        self.assertEqual(payload["status_counts"]["available"], 1)
        self.assertFalse(payload["read_only_safety"]["validation_runs_triggered"])

    def test_outputs_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backlog_path = root / "backlog.json"
            validation_dir = root / "validation_corpus_outputs"
            validation_dir.mkdir()
            backlog_path.write_text(json.dumps({"items": []}), encoding="utf-8")
            payload = build_dashboard(backlog_path=backlog_path, validation_output_dir=validation_dir, completed_ids=[])
            outputs = write_outputs(payload, root)
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())


if __name__ == "__main__":
    unittest.main()
