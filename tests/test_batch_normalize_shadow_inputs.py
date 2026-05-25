from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.batch_normalize_shadow_inputs import (
    REPORT_TYPE,
    STATUS_NORMALIZED,
    STATUS_SKIPPED,
    batch_normalize_from_root,
    main,
    markdown_report,
    write_batch_outputs,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shadow_artifact_corpus_inventory"


class BatchNormalizeShadowInputsTests(unittest.TestCase):
    def test_batch_runner_normalizes_supported_families_and_skips_unsupported(self) -> None:
        report = batch_normalize_from_root(
            FIXTURES,
            max_artifacts_per_family=2,
            max_records_per_artifact=5,
        )
        statuses = {item["status"] for item in report["artifacts"]}

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertIn(STATUS_NORMALIZED, statuses)
        self.assertIn(STATUS_SKIPPED, statuses)
        self.assertGreater(report["summary"]["normalizedRecordCount"], 0)
        self.assertGreater(report["summary"]["skippedArtifactCount"], 0)

        normalized = [item for item in report["artifacts"] if item["status"] == STATUS_NORMALIZED]
        self.assertTrue(any(item["normalizerFamily"] == "recent_scanner_report_json" for item in normalized))
        self.assertTrue(any(item["normalizerFamily"] == "event_forensic_event_analysis_json" for item in normalized))
        self.assertTrue(any(item["normalizerFamily"] == "reconstruction_report_dir" for item in normalized))

    def test_batch_runner_reports_unknown_reasons_and_family_coverage(self) -> None:
        report = batch_normalize_from_root(
            FIXTURES,
            max_artifacts_per_family=2,
            max_records_per_artifact=5,
        )
        summary = report["summary"]

        self.assertIn("coverageByFamily", summary)
        self.assertIn("unknownReasonCounts", summary)
        self.assertGreater(summary["availableMetricCount"], 0)
        self.assertTrue(any("current price" in reason for reason in summary["unknownReasonCounts"]))
        self.assertIn("recent_scanner_report_json", summary["coverageByFamily"])

    def test_batch_output_is_explicit_and_markdown_lists_skips(self) -> None:
        report = batch_normalize_from_root(
            FIXTURES,
            max_artifacts_per_family=1,
            max_records_per_artifact=1,
        )
        markdown = markdown_report(report)

        self.assertIn("Batch Shadow Input Normalization", markdown)
        self.assertIn("Skipped artifacts", markdown)

        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_batch_outputs(report, tmp)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reportType"], REPORT_TYPE)

    def test_cli_creates_explicit_outputs_without_stdout_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_json = Path(tmp) / "nested" / "batch.json"
            output_md = Path(tmp) / "nested" / "batch.md"
            exit_code = main(
                [
                    "--root",
                    str(FIXTURES),
                    "--max-artifacts-per-family",
                    "1",
                    "--max-records-per-artifact",
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

    def test_batch_runner_does_not_use_network_calls(self) -> None:
        with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
            with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                report = batch_normalize_from_root(
                    FIXTURES,
                    max_artifacts_per_family=1,
                    max_records_per_artifact=1,
                )

        self.assertGreater(report["summary"]["artifactCount"], 0)

    def test_batch_tool_is_not_imported_by_runtime_paths(self) -> None:
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
            self.assertNotIn("batch_normalize_shadow_inputs", source)


if __name__ == "__main__":
    unittest.main()
