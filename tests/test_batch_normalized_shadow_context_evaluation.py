from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.batch_evaluate_normalized_shadow_context import (
    REPORT_TYPE,
    STATUS_EVALUATED,
    STATUS_SKIPPED,
    batch_evaluate_from_root,
    main,
    markdown_report,
    write_batch_evaluation_outputs,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shadow_artifact_corpus_inventory"


class BatchNormalizedShadowContextEvaluationTests(unittest.TestCase):
    def test_batch_evaluator_computes_useful_and_skipped_artifacts(self) -> None:
        report = batch_evaluate_from_root(FIXTURES, max_artifacts_per_family=2)
        statuses = {item["status"] for item in report["artifacts"]}

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertIn(STATUS_EVALUATED, statuses)
        self.assertIn(STATUS_SKIPPED, statuses)
        self.assertGreater(report["summary"]["evaluatedArtifactCount"], 0)
        self.assertGreater(report["summary"]["usefulMetricCount"], 0)
        self.assertIn("valueByFamily", report["summary"])

    def test_batch_evaluator_reports_metric_status_counts_and_examples(self) -> None:
        report = batch_evaluate_from_root(FIXTURES, max_artifacts_per_family=2)
        summary = report["summary"]

        self.assertIn("metricStatusCounts", summary)
        self.assertIn("available", summary["metricStatusCounts"])
        self.assertTrue(summary["usefulExamples"])
        self.assertTrue(summary["clutterExamples"])
        self.assertIn(summary["decisionHint"], {
            "keep_sidecar_only_useful_but_duplication_or_confusion_risk_high",
            "sidecar_evidence_improved_but_requires_later_gate_review",
        })

    def test_batch_evaluation_output_is_explicit_and_markdown_has_decision_context(self) -> None:
        report = batch_evaluate_from_root(FIXTURES, max_artifacts_per_family=1)
        markdown = markdown_report(report)

        self.assertIn("Batch Normalized Shadow Context Evaluation", markdown)
        self.assertIn("Duplicate/confusion risk", markdown)

        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_batch_evaluation_outputs(report, tmp)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reportType"], REPORT_TYPE)

    def test_cli_creates_explicit_outputs_without_stdout_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_json = Path(tmp) / "nested" / "evaluation.json"
            output_md = Path(tmp) / "nested" / "evaluation.md"
            exit_code = main(
                [
                    "--root",
                    str(FIXTURES),
                    "--max-artifacts-per-family",
                    "1",
                    "--output-json",
                    str(output_json),
                    "--output-md",
                    str(output_md),
                    "--quiet",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())

    def test_batch_evaluator_does_not_use_network_calls(self) -> None:
        with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
            with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                report = batch_evaluate_from_root(FIXTURES, max_artifacts_per_family=1)

        self.assertGreater(report["summary"]["artifactCount"], 0)

    def test_batch_evaluator_tool_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/browser_event_forensic_ui.html",
            "app/storage.py",
            "app/polymarket.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("batch_evaluate_normalized_shadow_context", source)


if __name__ == "__main__":
    unittest.main()
