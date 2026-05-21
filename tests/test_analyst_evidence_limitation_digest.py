from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.analyst_evidence_limitation_digest import build_digest, render_markdown, write_outputs


class AnalystEvidenceLimitationDigestTests(unittest.TestCase):
    def test_digest_combines_latest_limitation_counts_without_model_changes(self) -> None:
        payload = build_digest(
            {
                "packet_quality_report": {
                    "qualitySummary": {
                        "packetCount": 10,
                        "packetsWithCacheOnlyEvidence": 7,
                        "packetsWithRetrospectiveOnlyEvidence": 3,
                        "packetsWithMissingOrWeakSourceAttribution": 8,
                        "packetsWithFalsePositiveAdvisoryMatches": 6,
                        "packetsWithLargeDedupeGroup": 2,
                    }
                },
                "gate_trace_availability_audit": {"summary": {"strongRiskGateTraceMissingCount": 5}},
                "false_positive_guardrail_audit": {"summary": {"guardrailsPassed": True}},
                "gate_decision_readiness": {"final_readiness_classification": "not_ready_corpus_too_cache_only"},
            }
        )
        summary = payload["summary"]
        self.assertEqual(summary["packetCount"], 10)
        self.assertEqual(summary["activeLimitationCount"], 5)
        self.assertEqual(summary["readinessClassification"], "not_ready_corpus_too_cache_only")
        self.assertTrue(summary["guardrailsPassed"])
        self.assertFalse(summary["modelBehaviorChanged"])
        self.assertFalse(summary["automaticActionAllowed"])

    def test_digest_missing_optional_artifacts_do_not_crash(self) -> None:
        payload = build_digest({})
        self.assertEqual(payload["summary"]["limitationRowCount"], 5)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_digest_forbidden_conclusions_are_explicit(self) -> None:
        payload = build_digest({})
        conclusions = " ".join(row["doNotConclude"] for row in payload["limitationRows"])
        self.assertIn("Do not", conclusions)
        self.assertIn("scoring or routing input", " ".join(payload["safeUse"]))

    def test_outputs_are_valid_json(self) -> None:
        payload = build_digest({})
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_outputs(payload, Path(tmp))
            loaded = json.loads(Path(outputs["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(loaded["summary"]["limitationRowCount"], 5)
            self.assertIn("Analyst Evidence Limitation Digest", Path(outputs["markdown_path"]).read_text(encoding="utf-8"))
            self.assertIn("Bottom Line", render_markdown(payload))


if __name__ == "__main__":
    unittest.main()
