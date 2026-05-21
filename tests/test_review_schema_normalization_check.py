from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.review_schema_normalization_check import build_schema_normalization_check, write_outputs


class ReviewSchemaNormalizationCheckTests(unittest.TestCase):
    def test_alias_usage_counts_legacy_and_new_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packets.json"
            path.write_text(
                json.dumps(
                    {
                        "packets": [
                            {
                                "walletAddress": "0xabc",
                                "event": "Example event",
                                "condition_id": "0xcond",
                                "tradeId": "0xtrade",
                                "hardEvidenceSources": ["dormant_wallet_reactivation"],
                                "strong_risk_gate_type": "structure_led",
                                "strongRiskExactGateBranch": "structure_led_gate",
                                "strongRiskCompositionClass": "structural",
                                "suppressors": ["domain_specialist"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            payload = build_schema_normalization_check([(path, "unique_review_packets")])
        self.assertEqual(payload["summary"]["rows_inspected"], 1)
        self.assertIn("walletAddress", payload["alias_usage"]["wallet"])
        self.assertEqual(payload["summary"]["missing_by_field"], {})

    def test_missing_fields_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packets.json"
            path.write_text(json.dumps({"packets": [{"wallet": "0xabc"}]}), encoding="utf-8")
            payload = build_schema_normalization_check([(path, "unique_review_packets")])
        self.assertIn("hard_evidence_sources", payload["summary"]["missing_by_field"])
        self.assertTrue(payload["examples"])

    def test_outputs_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_schema_normalization_check([])
            outputs = write_outputs(payload, Path(tmp))
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())


if __name__ == "__main__":
    unittest.main()
