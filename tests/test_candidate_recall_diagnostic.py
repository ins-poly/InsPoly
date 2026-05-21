from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from tools.candidate_recall_diagnostic import build_candidate_recall_diagnostic, build_stratified_saved_output_slices, write_outputs


class CandidateRecallDiagnosticTests(unittest.TestCase):
    def test_missing_inputs_do_not_crash(self) -> None:
        payload = build_candidate_recall_diagnostic(corpus_path=Path("/tmp/does-not-exist.json"))
        self.assertIn("diagnostic_interpretation", payload)
        self.assertIn("audit", payload)

    def test_no_recall_change_interpretation_for_empty_saved_inputs(self) -> None:
        payload = build_candidate_recall_diagnostic(corpus_path=Path("/tmp/does-not-exist.json"))
        self.assertEqual(payload["diagnostic_interpretation"], "no_recall_change_indicated_from_saved_outputs")
        self.assertIn("near_miss_visibility", payload)
        self.assertIn("stratified_saved_output_recall", payload)
        self.assertIn("fresh_validation_requirements_before_recall_change", payload)
        self.assertEqual(payload["near_miss_visibility"]["diagnostic_quality"], "limited_no_candidate_funnel_files")
        self.assertFalse(payload["summary"]["model_behavior_changed"])
        self.assertFalse(payload["summary"]["candidate_admission_changed"])
        self.assertFalse(payload["summary"]["automatic_routing_allowed"])

    def test_outputs_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_candidate_recall_diagnostic(corpus_path=Path("/tmp/does-not-exist.json"))
            outputs = write_outputs(payload, Path(tmp))
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())
            json.loads(Path(outputs["json_path"]).read_text(encoding="utf-8"))

    def test_stratified_saved_output_slices_separate_limitations(self) -> None:
        payload = build_stratified_saved_output_slices(
            packet_quality_payload={
                "packetQualityRows": [
                    {
                        "packetId": "packet_0001",
                        "wallet": "0x111",
                        "marketOrEvent": "Market A",
                        "strongRiskFlag": True,
                        "hardEvidenceReviewFlag": False,
                        "overlapFlag": False,
                        "cacheOnlyWarning": "Funding unknown.",
                        "retrospectiveOnlyWarning": "",
                        "sourceAttributionWarning": "Gate trace missing.",
                        "falsePositiveAdvisoryMatches": [{"pattern": "funding_unknown"}],
                        "dedupeGroupSize": 6,
                    },
                    {
                        "packetId": "packet_0002",
                        "wallet": "0x222",
                        "marketOrEvent": "Market B",
                        "strongRiskFlag": False,
                        "hardEvidenceReviewFlag": True,
                        "overlapFlag": False,
                        "cacheOnlyWarning": "",
                        "retrospectiveOnlyWarning": "Retrospective-only.",
                        "sourceAttributionWarning": "",
                        "falsePositiveAdvisoryMatches": [],
                        "dedupeGroupSize": 1,
                    },
                ]
            },
            review_packet_payload={},
            audit={"funnel_file_count": 0, "near_miss_groups": 0},
            gate_trace_payload={"summary": {"strongRiskGateTraceMissingCount": 1}},
            false_positive_explanation_payload={"summary": {"patternCount": 1, "totalPacketPatternMatches": 1}},
        )
        rows = {row["sliceId"]: row for row in payload["slices"]}
        self.assertEqual(rows["strong_risk_saved_packets"]["packetCount"], 1)
        self.assertEqual(rows["hard_evidence_review_saved_packets"]["packetCount"], 1)
        self.assertEqual(rows["cache_only_or_funding_unknown"]["packetCount"], 1)
        self.assertEqual(rows["retrospective_only"]["packetCount"], 1)
        self.assertEqual(rows["gate_trace_or_source_weak"]["packetCount"], 1)
        self.assertEqual(rows["false_positive_advisory"]["packetCount"], 1)
        self.assertEqual(rows["large_dedupe_groups"]["packetCount"], 1)
        self.assertFalse(rows["false_positive_advisory"]["automaticRoutingAllowed"])
        self.assertFalse(payload["summary"]["model_behavior_changed"])

    def test_stratified_slices_report_candidate_funnel_near_misses_without_routing_changes(self) -> None:
        payload = build_stratified_saved_output_slices(
            packet_quality_payload={},
            review_packet_payload={"packets": []},
            audit={"funnel_file_count": 2, "near_miss_groups": 4, "near_miss_groups_funding_not_assessable": 3},
            gate_trace_payload={},
            false_positive_explanation_payload={},
        )
        near_miss = next(row for row in payload["slices"] if row["sliceId"] == "candidate_funnel_near_misses")
        self.assertEqual(near_miss["packetCount"], 4)
        self.assertEqual(near_miss["cacheOnlyOrFundingUnknownCount"], 3)
        self.assertFalse(near_miss["automaticRoutingAllowed"])


if __name__ == "__main__":
    unittest.main()
