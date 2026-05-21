from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.strategic_backlog_next_action import (
    FORBIDDEN_PROMPT_PHRASES,
    build_action_pack,
    write_outputs,
)


def _sample_backlog_path(root: Path) -> Path:
    workstreams = (
        ["Analyst-facing case quality"] * 5
        + ["Unique-row review packets"] * 4
        + ["Report readability and executive summaries"] * 3
        + ["UI drilldown and clickable wallet/market links"] * 3
        + ["False-positive and false-negative control"] * 3
        + ["Validation/RPC readiness"] * 3
    )
    items = []
    for index, workstream in enumerate(workstreams, start=1):
        rpc_blocked = workstream == "Validation/RPC readiness"
        items.append(
            {
                "id": f"SAMPLE-{index:03d}",
                "title": f"{workstream} task {index}",
                "workstream": workstream,
                "priority": "P1",
                "blockedByRpc": rpc_blocked,
                "requiresHumanApproval": False,
                "modelBehaviorChange": False,
                "riskLevel": "low",
                "commandsToRun": ["python3 tools/generate_unique_review_packets.py"],
                "testsToRun": ["python3 -m unittest discover -s tests -p 'test_*.py'"],
            }
        )
    path = root / "sample_backlog.json"
    path.write_text(json.dumps({"items": items}), encoding="utf-8")
    return path


class StrategicBacklogNextActionTests(unittest.TestCase):
    def test_backlog_has_required_safe_non_rpc_depth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backlog_path = _sample_backlog_path(Path(tmp))
            payload = json.loads(backlog_path.read_text(encoding="utf-8"))
        items = payload.get("items", [])
        self.assertGreaterEqual(len(items), 20)
        safe_non_rpc = [
            item
            for item in items
            if not item.get("blockedByRpc")
            and not item.get("requiresHumanApproval")
            and not item.get("modelBehaviorChange")
        ]
        analyst_items = [
            item
            for item in items
            if item.get("workstream")
            in {
                "Analyst-facing case quality",
                "Unique-row review packets",
                "Report readability and executive summaries",
                "UI drilldown and clickable wallet/market links",
            }
        ]
        fp_fn_items = [
            item
            for item in items
            if "False-positive" in str(item.get("workstream")) or "false-negative" in str(item.get("workstream"))
        ]
        navigation_items = [
            item
            for item in items
            if "UI" in str(item.get("workstream")) or "clickable" in str(item.get("workstream")) or "navigation" in item.get("title", "").lower()
        ]
        validation_items = [item for item in items if "Validation/RPC readiness" == item.get("workstream")]
        self.assertGreaterEqual(len(safe_non_rpc), 10)
        self.assertGreaterEqual(len(analyst_items), 5)
        self.assertGreaterEqual(len(fp_fn_items), 3)
        self.assertGreaterEqual(len(navigation_items), 3)
        self.assertGreaterEqual(len(validation_items), 3)

    def test_selector_avoids_rpc_blocked_tasks_when_cache_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backlog = {
                "items": [
                    {
                        "id": "P0-RPC",
                        "title": "RPC task",
                        "workstream": "Validation/RPC readiness",
                        "priority": "P0",
                        "blockedByRpc": True,
                        "requiresHumanApproval": False,
                        "modelBehaviorChange": False,
                        "riskLevel": "low",
                    },
                    {
                        "id": "P1-SAFE",
                        "title": "Safe packet task",
                        "workstream": "Unique-row review packets",
                        "priority": "P1",
                        "blockedByRpc": False,
                        "requiresHumanApproval": False,
                        "modelBehaviorChange": False,
                        "riskLevel": "low",
                        "commandsToRun": ["python3 tools/generate_unique_review_packets.py"],
                        "testsToRun": ["python3 -m unittest tests.test_unique_review_packets"],
                        "acceptanceCriteria": ["writes packets"],
                        "stopConditions": ["stop safely"],
                    },
                ]
            }
            backlog_path = root / "backlog.json"
            readiness_path = root / "gate_decision_readiness_20260505_000000.json"
            operator_path = root / "operator_rpc_capacity_recovery_package_20260505_000000.json"
            backlog_path.write_text(json.dumps(backlog), encoding="utf-8")
            readiness_path.write_text(json.dumps({"readinessClassification": "not_ready_corpus_too_cache_only"}), encoding="utf-8")
            operator_path.write_text(json.dumps({"configuration_status": "no_new_operator_rpc_config_detected"}), encoding="utf-8")
            pack = build_action_pack(
                backlog_path=backlog_path,
                output_dir=root,
                validation_output_dir=root,
                readiness_path=readiness_path,
                operator_package_path=operator_path,
            )
        self.assertEqual(pack["selected_item"]["id"], "P1-SAFE")
        self.assertEqual(pack["decision"], "generate_review_packets")

    def test_selector_avoids_model_behavior_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backlog = {
                "items": [
                    {
                        "id": "P0-RFC",
                        "title": "RFC task",
                        "workstream": "Validation/RPC readiness",
                        "priority": "P0",
                        "blockedByRpc": False,
                        "requiresHumanApproval": True,
                        "modelBehaviorChange": True,
                        "riskLevel": "low",
                    },
                    {
                        "id": "P1-SAFE",
                        "title": "Safe readability task",
                        "workstream": "Report readability and executive summaries",
                        "priority": "P1",
                        "blockedByRpc": False,
                        "requiresHumanApproval": False,
                        "modelBehaviorChange": False,
                        "riskLevel": "low",
                        "commandsToRun": ["python3 tools/generate_unique_review_packets.py"],
                        "testsToRun": ["python3 -m unittest tests.test_unique_review_packets"],
                    },
                ]
            }
            backlog_path = root / "backlog.json"
            readiness_path = root / "gate_decision_readiness_20260505_000000.json"
            backlog_path.write_text(json.dumps(backlog), encoding="utf-8")
            readiness_path.write_text(json.dumps({"readinessClassification": "ready_no_gate_issue_observed"}), encoding="utf-8")
            pack = build_action_pack(
                backlog_path=backlog_path,
                output_dir=root,
                validation_output_dir=root,
                readiness_path=readiness_path,
            )
        self.assertEqual(pack["selected_item"]["id"], "P1-SAFE")
        self.assertFalse(pack["selected_item"]["modelBehaviorChange"])

    def test_prompt_is_self_contained_and_avoids_forbidden_phrases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = build_action_pack(backlog_path=_sample_backlog_path(Path(tmp)))
        prompt = pack["ready_to_copy_codex_prompt"]
        for required in ("Role:", "Current status:", "Hard constraints:", "Files/tools to inspect", "Commands to run:", "Tests to run:", "Stop conditions:"):
            self.assertIn(required, prompt)
        lower = prompt.lower()
        for phrase in FORBIDDEN_PROMPT_PHRASES:
            self.assertNotIn(phrase, lower)

    def test_selector_prefers_safe_implementation_boundary_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backlog = {
                "items": [
                    {
                        "id": "BOUNDARY-OPEN",
                        "title": "Build implementation boundary crosswalk",
                        "workstream": "Implementation boundary and analyst workflow",
                        "priority": "P1",
                        "blockedByRpc": False,
                        "requiresHumanApproval": False,
                        "modelBehaviorChange": False,
                        "riskLevel": "low",
                        "commandsToRun": ["python3 tools/implementation_boundary_report.py"],
                        "testsToRun": ["python3 -m unittest tests.test_implementation_boundary_report"],
                        "acceptanceCriteria": ["writes boundary"],
                        "stopConditions": ["stop safely"],
                    },
                    {
                        "id": "RPC-OPEN",
                        "title": "Run RPC task",
                        "workstream": "Validation/RPC readiness",
                        "priority": "P0",
                        "blockedByRpc": True,
                        "requiresHumanApproval": False,
                        "modelBehaviorChange": False,
                        "riskLevel": "low",
                    },
                ]
            }
            backlog_path = root / "backlog.json"
            readiness_path = root / "gate_decision_readiness_20260505_000000.json"
            backlog_path.write_text(json.dumps(backlog), encoding="utf-8")
            readiness_path.write_text(json.dumps({"readinessClassification": "not_ready_corpus_too_cache_only"}), encoding="utf-8")
            pack = build_action_pack(
                backlog_path=backlog_path,
                output_dir=root,
                validation_output_dir=root,
                readiness_path=readiness_path,
            )
        self.assertEqual(pack["selected_item"]["id"], "BOUNDARY-OPEN")
        self.assertEqual(pack["decision"], "improve_analyst_report_readability")

    def test_outputs_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = build_action_pack(backlog_path=_sample_backlog_path(root), output_dir=root)
            outputs = write_outputs(pack, root)
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())


if __name__ == "__main__":
    unittest.main()
