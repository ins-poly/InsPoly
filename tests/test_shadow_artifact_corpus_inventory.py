from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.shadow_artifact_corpus_inventory import (
    FAMILY_ARCHIVE_CSV,
    FAMILY_ARCHIVE_REPORT_JSON,
    FAMILY_CASE_SPECIFIC_INVESTIGATION,
    FAMILY_EVENT_FORENSIC_BUNDLE,
    FAMILY_EVENT_FORENSIC_REPORT_JSON,
    FAMILY_RECENT_SCANNER_JSON,
    FAMILY_RECONSTRUCTION_REPORT_DIR,
    FAMILY_SIDECAR_OUTPUT,
    METRIC_LOW_ODDS,
    METRIC_NET_PNL,
    STATUS_SUPPORTED,
    discover_corpus_inventory,
    main,
    markdown_report,
    write_inventory_outputs,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shadow_artifact_corpus_inventory"


class ShadowArtifactCorpusInventoryTests(unittest.TestCase):
    def test_inventory_classifies_supported_and_coverage_only_artifact_families(self) -> None:
        report = discover_corpus_inventory(FIXTURES, stale_days=99999).to_dict()
        families = {item["family"] for item in report["artifacts"]}

        self.assertIn(FAMILY_RECENT_SCANNER_JSON, families)
        self.assertIn(FAMILY_ARCHIVE_REPORT_JSON, families)
        self.assertIn(FAMILY_ARCHIVE_CSV, families)
        self.assertIn(FAMILY_EVENT_FORENSIC_REPORT_JSON, families)
        self.assertIn(FAMILY_EVENT_FORENSIC_BUNDLE, families)
        self.assertIn(FAMILY_CASE_SPECIFIC_INVESTIGATION, families)
        self.assertIn(FAMILY_RECONSTRUCTION_REPORT_DIR, families)
        self.assertIn(FAMILY_SIDECAR_OUTPUT, families)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])

        recent = self._first_family(report, FAMILY_RECENT_SCANNER_JSON)
        self.assertEqual(recent["supportStatus"], STATUS_SUPPORTED)
        self.assertEqual(recent["likelySupportedMetrics"], [METRIC_LOW_ODDS])
        self.assertEqual(recent["detectedFiles"], ["scan_20260101_000000.json"])

        reconstruction = self._first_family(report, FAMILY_RECONSTRUCTION_REPORT_DIR)
        self.assertIn(METRIC_NET_PNL, reconstruction["likelySupportedMetrics"])
        self.assertIn("normalized_trades.csv", reconstruction["detectedFiles"])

    def test_inventory_output_is_explicit_and_markdown_summarizes_counts(self) -> None:
        report = discover_corpus_inventory(FIXTURES, max_per_family=1, stale_days=99999).to_dict()
        markdown = markdown_report(report)

        self.assertIn("Shadow Artifact Corpus Inventory", markdown)
        self.assertIn(FAMILY_RECENT_SCANNER_JSON, markdown)
        self.assertIn("normalizer_supported", markdown)
        self.assertGreaterEqual(report["summary"]["artifactCount"], 1)

        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_inventory_outputs(report, tmp)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reportType"], "shadow_artifact_corpus_inventory")

    def test_cli_creates_parent_directories_for_explicit_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_json = Path(tmp) / "nested" / "inventory.json"
            output_md = Path(tmp) / "nested" / "inventory.md"
            exit_code = main(
                [
                    "--root",
                    str(FIXTURES),
                    "--max-per-family",
                    "1",
                    "--stale-days",
                    "99999",
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

    def test_inventory_respects_family_cap_without_mutating_sources(self) -> None:
        source = FIXTURES / ".inspoly" / "reports" / "scan_20260101_000000.json"
        before = source.read_text(encoding="utf-8")

        report = discover_corpus_inventory(FIXTURES, max_per_family=1, stale_days=99999).to_dict()

        self.assertEqual(source.read_text(encoding="utf-8"), before)
        family_counts = report["summary"]["familyCounts"]
        self.assertTrue(all(count <= 1 for count in family_counts.values()))

    def test_inventory_does_not_use_network_calls(self) -> None:
        with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
            with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                report = discover_corpus_inventory(FIXTURES, stale_days=99999).to_dict()

        self.assertGreater(report["summary"]["artifactCount"], 0)

    def test_inventory_tool_is_not_imported_by_runtime_paths(self) -> None:
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
            self.assertNotIn("shadow_artifact_corpus_inventory", source)

    def _first_family(self, report: dict[str, object], family: str) -> dict[str, object]:
        for item in report["artifacts"]:
            if item["family"] == family:
                return item
        raise AssertionError(f"missing family: {family}")


if __name__ == "__main__":
    unittest.main()
