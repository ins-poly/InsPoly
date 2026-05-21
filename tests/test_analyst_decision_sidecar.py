from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.analyst_decision_sidecar import (
    ALLOWED_DECISIONS,
    build_sidecar,
    render_markdown,
    write_outputs,
)


class AnalystDecisionSidecarTests(unittest.TestCase):
    def _quality_report_payload(self) -> dict:
        return {
            "packetQualityRows": [
                {
                    "packetId": "packet_0001",
                    "wallet": "0x1111111111111111111111111111111111111111",
                    "traderName": "alice",
                    "marketOrEvent": "Market A",
                    "strongRiskFlag": True,
                    "hardEvidenceReviewFlag": False,
                    "overlapFlag": False,
                    "analystPriority": "high",
                }
            ]
        }

    def test_sidecar_is_generated_from_packet_quality_rows(self) -> None:
        payload = build_sidecar(quality_report_payload=self._quality_report_payload())
        self.assertEqual(payload["summary"]["sidecarRowCount"], 1)
        row = payload["sidecarRows"][0]
        self.assertEqual(row["packetId"], "packet_0001")
        self.assertEqual(row["packetQualityPriority"], "high")
        self.assertEqual(row["analystDecision"], "unreviewed")
        self.assertEqual(row["allowedDecisions"], list(ALLOWED_DECISIONS))

    def test_sidecar_falls_back_to_review_packets_and_handles_missing_optional_fields(self) -> None:
        payload = build_sidecar(
            review_packet_payload={
                "packets": [
                    {
                        "packet_id": "packet_legacy",
                        "group": "overlap",
                    }
                ]
            }
        )
        row = payload["sidecarRows"][0]
        self.assertEqual(row["packetId"], "packet_legacy")
        self.assertEqual(row["wallet"], "unknown")
        self.assertTrue(row["strongRiskFlag"])
        self.assertTrue(row["hardEvidenceReviewFlag"])
        self.assertTrue(row["overlapFlag"])

    def test_sidecar_is_reporting_only_and_not_consumable_by_scoring(self) -> None:
        payload = build_sidecar(quality_report_payload=self._quality_report_payload())
        summary = payload["summary"]
        self.assertFalse(summary["productionUseAllowed"])
        self.assertFalse(summary["modelBehaviorChanged"])
        self.assertFalse(summary["scoringChanged"])
        self.assertFalse(summary["gatesChanged"])
        self.assertFalse(summary["herRoutingChanged"])
        self.assertFalse(summary["fundingEligibilityChanged"])
        self.assertFalse(summary["candidateAdmissionChanged"])
        row = payload["sidecarRows"][0]
        self.assertFalse(row["productionUseAllowed"])
        self.assertFalse(row["scoringUseAllowed"])
        self.assertFalse(row["routingUseAllowed"])
        self.assertTrue(row["sidecarOnly"])

    def test_outputs_are_written_as_valid_json_and_markdown(self) -> None:
        payload = build_sidecar(quality_report_payload=self._quality_report_payload())
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_outputs(payload, Path(tmp))
            loaded = json.loads(Path(outputs["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(loaded["summary"]["sidecarRowCount"], 1)
            markdown = Path(outputs["markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("Analyst Decision Sidecar", markdown)
            self.assertIn("productionUseAllowed: False", render_markdown(payload))


if __name__ == "__main__":
    unittest.main()
