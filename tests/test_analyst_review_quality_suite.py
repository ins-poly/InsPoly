from __future__ import annotations

from pathlib import Path
import copy
import json
import tempfile
import unittest

from tools.analyst_review_quality_suite import (
    build_artifact_manifest,
    build_diagnostic_context,
    build_handoff_bundle,
    build_manifest_preview,
    build_packet_group_drilldown,
    build_packet_quality_report,
    build_quality_check,
    build_wallet_queue,
    _write_pair,
    render_packet_quality_report_markdown,
    render_group_drilldown_markdown,
    render_quality_markdown,
    render_bundle_markdown,
)


class AnalystReviewQualitySuiteTests(unittest.TestCase):
    def _packet_payload(self) -> dict:
        return {
            "summary": {"unique_packet_count": 2, "wallet_group_count": 1, "market_group_count": 1},
            "wallet_groups": [
                {
                    "wallet": "0x1111111111111111111111111111111111111111",
                    "packet_count": 2,
                    "market_count": 1,
                    "strong_risk_packet_count": 2,
                    "hard_evidence_review_packet_count": 1,
                    "max_score": 88,
                    "wallet_link": "https://polygonscan.com/address/0x1111111111111111111111111111111111111111",
                    "suppressor_themes": [{"name": "high_volume_public_user", "count": 2}],
                    "packet_ids": ["packet_0001", "packet_0002"],
                }
            ],
            "packets": [
                {
                    "packet_id": "packet_0001",
                    "wallet": "0x1111111111111111111111111111111111111111",
                    "trader_name": "alice",
                    "market": "Market A",
                    "condition_id": "0xabc",
                    "trade_id": "0xtrade1",
                    "source_path": "/tmp/source.csv",
                    "links": {
                        "polygonscan_wallet": "https://polygonscan.com/address/0x111",
                        "polymarket_market": "https://polymarket.com/event/example",
                    },
                    "why_this_matters": ["reason"],
                    "why_this_may_be_false_positive": ["caution"],
                    "what_to_inspect_next": ["step"],
                    "funding_evidence_grade": "unknown",
                    "gate_family": "structural",
                    "group": "strong_risk",
                    "strong_risk_exact_gate_branch": "structural_branch",
                    "dedupe_group_size": 6,
                    "false_positive_advisory": [
                        {
                            "pattern": "funding_unknown",
                            "issue_id": "FP-006",
                            "message": "Funding unknown.",
                            "automatic_action_allowed": "false",
                        }
                    ],
                },
                {
                    "packet_id": "packet_0002",
                    "wallet": "",
                    "market": "",
                    "why_this_matters": [],
                    "why_this_may_be_false_positive": [],
                    "what_to_inspect_next": [],
                    "group": "overlap",
                    "retrospective_only": True,
                },
            ],
        }

    def test_quality_check_reports_field_coverage(self) -> None:
        payload = build_quality_check(self._packet_payload())
        self.assertEqual(payload["summary"]["packet_count"], 2)
        self.assertEqual(payload["field_coverage"]["wallet"]["present"], 1)
        self.assertEqual(payload["summary"]["packets_with_any_missing_quality_field"], 1)
        self.assertFalse(payload["summary"]["model_behavior_changed"])

    def test_wallet_queue_is_advisory_and_uses_packet_groups(self) -> None:
        payload = build_wallet_queue(self._packet_payload())
        self.assertEqual(payload["summary"]["wallet_count"], 1)
        self.assertTrue(payload["summary"]["advisory_only"])
        self.assertIn("Hard Evidence Review", payload["wallet_queue"][0]["advisory_review_reason"])
        self.assertIn("High-volume", payload["wallet_queue"][0]["advisory_caution"])

    def test_handoff_bundle_collects_artifacts_without_model_changes(self) -> None:
        quality = build_quality_check(self._packet_payload())
        queue = build_wallet_queue(self._packet_payload())
        bundle = build_handoff_bundle(
            {"unique_review_packets": "/tmp/packets.json", "implementation_boundary": "/tmp/boundary.json"},
            self._packet_payload(),
            quality,
            queue,
        )
        self.assertEqual(bundle["summary"]["packet_count"], 2)
        self.assertFalse(bundle["summary"]["model_behavior_changed"])
        self.assertEqual(bundle["artifact_paths"]["unique_review_packets"], "/tmp/packets.json")
        self.assertEqual(bundle["artifact_paths"]["implementation_boundary"], "/tmp/boundary.json")

    def test_handoff_bundle_includes_diagnostic_context_without_model_changes(self) -> None:
        quality = build_quality_check(self._packet_payload())
        queue = build_wallet_queue(self._packet_payload())
        context = {
            "implementation_boundary": {
                "issue_count": 3,
                "model_behavior_changed": False,
            }
        }
        bundle = build_handoff_bundle(
            {"unique_review_packets": "/tmp/packets.json"},
            self._packet_payload(),
            quality,
            queue,
            context,
        )
        self.assertEqual(bundle["summary"]["diagnostic_context_count"], 1)
        self.assertFalse(bundle["summary"]["model_behavior_changed"])
        self.assertFalse(bundle["diagnostic_context"]["implementation_boundary"]["model_behavior_changed"])
        self.assertIn("Diagnostic Context", render_bundle_markdown(bundle))

    def test_handoff_bundle_includes_manifest_summary_without_model_changes(self) -> None:
        quality = build_quality_check(self._packet_payload())
        queue = build_wallet_queue(self._packet_payload())
        manifest_summary = {
            "artifact_count": 3,
            "missing_artifact_count": 1,
            "hash_covered_artifact_count": 2,
            "old_outputs_mutated": False,
        }
        bundle = build_handoff_bundle(
            {"unique_review_packets": "/tmp/packets.json"},
            self._packet_payload(),
            quality,
            queue,
            manifest_summary=manifest_summary,
        )
        self.assertEqual(bundle["summary"]["manifest_artifact_count"], 3)
        self.assertEqual(bundle["manifest_summary"]["hash_covered_artifact_count"], 2)
        self.assertFalse(bundle["summary"]["model_behavior_changed"])
        self.assertIn("Manifest Summary", render_bundle_markdown(bundle))

    def test_diagnostic_context_handles_missing_optional_artifacts(self) -> None:
        context = build_diagnostic_context({"implementation_boundary": "/tmp/missing-boundary.json"})
        self.assertEqual(context, {})

    def test_manifest_hashes_existing_files_and_marks_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            path.write_text("hello", encoding="utf-8")
            payload = build_artifact_manifest(
                {
                    "packet_quality_report": str(path),
                    "unique_review_packets": str(path),
                    "analyst_handoff_bundle": str(path),
                    "review_output_index": str(path),
                    "false_positive_library": str(path),
                    "source_schema_repair_plan": str(path),
                    "candidate_recall_diagnostic": str(path),
                    "missing": str(Path(tmp) / "missing.json"),
                }
            )
        entries = {item["name"]: item for item in payload["artifacts"]}
        self.assertTrue(entries["packet_quality_report"]["exists"])
        self.assertEqual(len(entries["packet_quality_report"]["sha256"]), 64)
        self.assertFalse(entries["missing"]["exists"])
        self.assertEqual(payload["summary"]["missing_artifact_count"], 1)
        self.assertEqual(payload["summary"]["hash_covered_artifact_count"], 7)
        self.assertEqual(payload["summary"]["missing_required_artifacts"], [])
        self.assertFalse(payload["summary"]["old_outputs_mutated"])

    def test_manifest_preview_reports_required_artifact_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            path.write_text("hello", encoding="utf-8")
            preview = build_manifest_preview({"packet_quality_report": str(path), "unique_review_packets": ""})
        self.assertTrue(preview["required_artifact_status"]["packet_quality_report"])
        self.assertFalse(preview["required_artifact_status"]["unique_review_packets"])
        self.assertEqual(preview["hash_covered_artifact_count"], 1)
        self.assertIn("unique_review_packets", preview["missing_required_artifacts"])

    def test_outputs_are_written(self) -> None:
        payload = build_quality_check(self._packet_payload())
        with tempfile.TemporaryDirectory() as tmp:
            outputs = _write_pair(payload, Path(tmp), "review_packet_quality_check", render_quality_markdown)
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())

    def test_packet_quality_report_is_generated_from_review_packets(self) -> None:
        payload = build_packet_quality_report(self._packet_payload())
        self.assertEqual(payload["packetCount"], 2)
        self.assertEqual(len(payload["packetQualityRows"]), 2)
        self.assertIn("priorityReviewQueue", payload)
        self.assertFalse(payload["safety"]["modelBehaviorChanged"])
        self.assertFalse(payload["safety"]["fundingEligibilityChanged"])

    def test_packet_quality_report_handles_missing_optional_fields(self) -> None:
        payload = build_packet_quality_report({"packets": [{"packet_id": "packet_legacy"}]})
        row = payload["packetQualityRows"][0]
        self.assertEqual(row["wallet"], "unknown")
        self.assertIn("wallet", row["missingCriticalFields"])
        self.assertIn("market_or_event", row["missingCriticalFields"])

    def test_packet_quality_report_marks_cache_and_retrospective_warnings(self) -> None:
        payload = build_packet_quality_report(self._packet_payload())
        rows = {row["packetId"]: row for row in payload["packetQualityRows"]}
        self.assertTrue(rows["packet_0001"]["cacheOnlyWarning"])
        self.assertTrue(rows["packet_0002"]["retrospectiveOnlyWarning"])
        self.assertGreaterEqual(payload["qualitySummary"]["packetsWithCacheOnlyEvidence"], 1)
        self.assertGreaterEqual(payload["qualitySummary"]["packetsWithRetrospectiveOnlyEvidence"], 1)

    def test_false_positive_matches_remain_advisory_only(self) -> None:
        payload = build_packet_quality_report(self._packet_payload())
        row = payload["packetQualityRows"][0]
        self.assertEqual(row["falsePositiveAdvisoryMatches"][0]["pattern"], "funding_unknown")
        self.assertFalse(row["falsePositiveAdvisoryMatches"][0]["automaticActionAllowed"])
        self.assertFalse(payload["warningsSummary"]["automaticActionAllowed"])
        self.assertFalse(payload["warningsSummary"]["falsePositiveLibraryUsedForScoring"])

    def test_packet_quality_report_does_not_modify_input_scoring_fields(self) -> None:
        packet_payload = self._packet_payload()
        before = copy.deepcopy(packet_payload)
        payload = build_packet_quality_report(packet_payload)
        self.assertEqual(packet_payload, before)
        self.assertFalse(payload["safety"]["scoringChanged"])
        self.assertFalse(payload["safety"]["gatesChanged"])
        self.assertFalse(payload["safety"]["herRoutingChanged"])

    def test_packet_quality_report_json_is_valid(self) -> None:
        payload = build_packet_quality_report(self._packet_payload())
        with tempfile.TemporaryDirectory() as tmp:
            outputs = _write_pair(payload, Path(tmp), "packet_quality_report", render_packet_quality_report_markdown)
            json.loads(Path(outputs["json_path"]).read_text(encoding="utf-8"))
            self.assertIn("Packet Quality Report", Path(outputs["markdown_path"]).read_text(encoding="utf-8"))

    def test_packet_group_drilldown_is_reporting_only(self) -> None:
        payload = build_packet_group_drilldown(self._packet_payload())
        self.assertEqual(payload["summary"]["walletGroupCount"], 1)
        self.assertEqual(payload["summary"]["marketGroupCount"], 0)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])
        self.assertFalse(payload["summary"]["productionPriorityChanged"])
        self.assertEqual(payload["walletGroups"][0]["analystPriority"], "high")
        self.assertTrue(payload["walletGroups"][0]["readOnlyReportingOnly"])
        self.assertIn("Packet Group Drilldown", render_group_drilldown_markdown(payload))


if __name__ == "__main__":
    unittest.main()
