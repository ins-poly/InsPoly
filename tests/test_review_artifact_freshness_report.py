from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.review_artifact_freshness_report import build_freshness_report, render_markdown, write_outputs


class ReviewArtifactFreshnessReportTests(unittest.TestCase):
    def test_freshness_report_counts_index_navigation_without_model_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "artifact.json"
            artifact.write_text("{}", encoding="utf-8")
            payload = build_freshness_report(
                {
                    "review_output_index": {
                        "summary": {
                            "latest_by_kind": {"packet_quality_report": str(artifact)},
                            "related_reference_count": 3,
                        },
                        "entries": [{"kind": "packet_quality_report"}],
                    },
                    "artifact_manifest": {
                        "summary": {
                            "artifact_count": 1,
                            "missing_artifact_count": 0,
                            "hash_covered_artifact_count": 1,
                        }
                    },
                    "analyst_handoff_bundle": {"summary": {"packet_count": 2}},
                }
            )
        summary = payload["summary"]
        self.assertEqual(summary["indexedKindCount"], 1)
        self.assertEqual(summary["missingLatestArtifactCount"], 0)
        self.assertEqual(summary["relatedReferenceCount"], 3)
        self.assertFalse(summary["modelBehaviorChanged"])
        self.assertFalse(summary["oldOutputsMutated"])
        self.assertTrue(payload["navigationHealth"]["readyForAnalystHandoff"])

    def test_missing_latest_artifact_is_reported(self) -> None:
        payload = build_freshness_report(
            {
                "review_output_index": {
                    "summary": {"latest_by_kind": {"missing": "/tmp/not-present-in-inspoly-tests.json"}},
                    "entries": [],
                }
            }
        )
        self.assertEqual(payload["summary"]["missingLatestArtifactCount"], 1)
        self.assertFalse(payload["navigationHealth"]["readyForAnalystHandoff"])

    def test_missing_optional_inputs_do_not_crash(self) -> None:
        payload = build_freshness_report({})
        self.assertEqual(payload["summary"]["indexedKindCount"], 0)
        self.assertFalse(payload["summary"]["modelBehaviorChanged"])

    def test_outputs_are_valid_json(self) -> None:
        payload = build_freshness_report({})
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_outputs(payload, Path(tmp))
            loaded = json.loads(Path(outputs["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(loaded["summary"]["indexedKindCount"], 0)
            self.assertIn("Review Artifact Freshness Report", Path(outputs["markdown_path"]).read_text(encoding="utf-8"))
            self.assertIn("Latest Artifact Rows", render_markdown(payload))


if __name__ == "__main__":
    unittest.main()
