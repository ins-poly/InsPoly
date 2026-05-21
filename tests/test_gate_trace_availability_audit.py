from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.gate_trace_availability_audit import build_audit, render_markdown, write_outputs


class GateTraceAvailabilityAuditTests(unittest.TestCase):
    def _packet_payload(self) -> dict:
        return {
            "packets": [
                {
                    "packet_id": "packet_0001",
                    "wallet": "0x111",
                    "market": "Market A",
                    "group": "strong_risk",
                    "source_path": "/tmp/event_forensic_outputs/run/event_analysis.json",
                    "source_collections": ["diagnostic:topManualInspectionRows"],
                    "gate_family": "structural",
                    "strong_risk_exact_gate_branch": "structural_branch",
                    "gate_trace_available": True,
                    "hard_evidence_sources": ["same_funder_cluster"],
                },
                {
                    "packet_id": "packet_0002",
                    "wallet": "0x222",
                    "market": "Market B",
                    "group": "strong_risk",
                    "source_path": "/tmp/archive_outputs/run/suspicious.csv",
                    "strong_risk_exact_gate_branch": "",
                    "gate_family": "",
                    "gate_trace_available": False,
                    "hard_evidence_sources": [],
                },
            ]
        }

    def test_audit_counts_gate_trace_coverage_without_model_changes(self) -> None:
        payload = build_audit(
            self._packet_payload(),
            {
                "rawStrongRiskRows": 2,
                "strongRiskRowsWithGateTraceAvailable": 1,
                "strongRiskRowsWithoutGateTrace": 1,
                "strongRiskByTargetFamily": {"event_forensic": 1, "archive": 1},
            },
        )
        summary = payload["summary"]
        self.assertEqual(summary["strongRiskPacketCount"], 2)
        self.assertEqual(summary["strongRiskGateTraceAvailableCount"], 1)
        self.assertEqual(summary["strongRiskGateTraceMissingCount"], 1)
        self.assertFalse(summary["modelBehaviorChanged"])
        self.assertFalse(summary["gatesChanged"])
        self.assertFalse(summary["herRoutingChanged"])
        self.assertFalse(summary["fundingEligibilityChanged"])

    def test_audit_separates_artifacts_and_target_families(self) -> None:
        payload = build_audit(self._packet_payload())
        artifact_names = {row["name"] for row in payload["artifactRows"]}
        family_names = {row["name"] for row in payload["targetFamilyRows"]}
        self.assertIn("/tmp/event_forensic_outputs/run/event_analysis.json", artifact_names)
        self.assertIn("/tmp/archive_outputs/run/suspicious.csv", artifact_names)
        self.assertIn("event_forensic", family_names)
        self.assertIn("archive", family_names)

    def test_missing_gate_trace_examples_are_reported(self) -> None:
        payload = build_audit(self._packet_payload())
        self.assertEqual(payload["missingGateTraceExamples"][0]["packetId"], "packet_0002")
        self.assertEqual(payload["missingGateTraceExamples"][0]["exactGateBranch"], "missing")
        self.assertIn("Gate Trace Availability Audit", render_markdown(payload))

    def test_outputs_are_valid_json(self) -> None:
        payload = build_audit(self._packet_payload())
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_outputs(payload, Path(tmp))
            loaded = json.loads(Path(outputs["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(loaded["summary"]["strongRiskPacketCount"], 2)
            self.assertIn("Gate Trace Availability Audit", Path(outputs["markdown_path"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
