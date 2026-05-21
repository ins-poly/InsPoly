from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.source_attribution_completeness import build_completeness_matrix, write_outputs


class SourceAttributionCompletenessTests(unittest.TestCase):
    def test_counts_missing_required_fields_by_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packets.json"
            path.write_text(
                json.dumps(
                    {
                        "packets": [
                            {
                                "packet_id": "packet_0001",
                                "group": "strong_risk",
                                "wallet": "0xabc",
                                "strong_risk_gate_type": "structure_led",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            payload = build_completeness_matrix({"review_packets": [path], "case_reviewer": [], "diagnostics": []})
        self.assertEqual(payload["summary"]["rows_inspected"], 1)
        self.assertEqual(payload["summary"]["rows_with_missing_fields"], 1)
        self.assertIn("hard_evidence_sources", payload["summary"]["missing_field_counts"])
        self.assertIn("packets.json", payload["by_artifact"])

    def test_complete_row_has_no_missing_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packets.json"
            path.write_text(
                json.dumps(
                    {
                        "packets": [
                            {
                                "packet_id": "packet_0001",
                                "group": "strong_risk",
                                "strong_risk_gate_type": "structure_led",
                                "strong_risk_exact_gate_branch": "structure_led_gate",
                                "strong_risk_composition_class": "structural",
                                "hard_evidence_sources": ["dormant_wallet_reactivation"],
                                "suppressors": ["domain_specialist"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            payload = build_completeness_matrix({"review_packets": [path], "case_reviewer": [], "diagnostics": []})
        self.assertEqual(payload["summary"]["complete_rows"], 1)
        self.assertEqual(payload["summary"]["rows_with_missing_fields"], 0)

    def test_legacy_case_reviewer_packet_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.json"
            path.write_text(
                json.dumps(
                    {
                        "case_packets": [
                            {
                                "case_id": "wallet-1",
                                "wallet": "0xabc",
                                "supporting_evidence": {"hard_evidence_sources": ["low_probability_early_winner"]},
                            }
                        ],
                        "reviews": [{"case_id": "wallet-1", "evidence_that_weakens_concern": ["No independent funding."]}],
                    }
                ),
                encoding="utf-8",
            )
            payload = build_completeness_matrix({"review_packets": [], "case_reviewer": [path], "diagnostics": []})
        self.assertEqual(payload["summary"]["rows_inspected"], 1)
        self.assertIsInstance(payload["examples"], list)

    def test_outputs_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_completeness_matrix({"review_packets": [], "case_reviewer": [], "diagnostics": []})
            outputs = write_outputs(payload, Path(tmp))
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())


if __name__ == "__main__":
    unittest.main()
