from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.side_outcome_archive_evidence_audit import (
    REPORT_TYPE,
    build_archive_evidence_audit,
    discover_archive_artifacts,
    load_archive_records,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "side_outcome_phase2_archive"


class SideOutcomeArchiveEvidenceAuditTests(unittest.TestCase):
    def _synthetic_records(self):
        artifacts = [
            {
                "path": str(FIXTURES / "archive_report.json"),
                "relativePath": "tests/fixtures/side_outcome_phase2_archive/archive_report.json",
                "artifactFamily": "archive_report_json",
                "artifactEvidenceType": "synthetic_fixture",
            },
            {
                "path": str(FIXTURES / "archive_trades.csv"),
                "relativePath": "tests/fixtures/side_outcome_phase2_archive/archive_trades.csv",
                "artifactFamily": "archive_trades_csv",
                "artifactEvidenceType": "synthetic_fixture",
            },
            {
                "path": str(FIXTURES / "archive_flagged.csv"),
                "relativePath": "tests/fixtures/side_outcome_phase2_archive/archive_flagged.csv",
                "artifactFamily": "archive_flagged_csv",
                "artifactEvidenceType": "synthetic_fixture",
            },
        ]
        records, skipped = load_archive_records(artifacts, max_rows_per_file=50)
        self.assertEqual(skipped, [])
        return records

    def test_archive_json_fixture_parses_cases(self) -> None:
        records = self._synthetic_records()
        json_rows = [row for row in records if row["artifactFamily"] == "archive_report_json"]

        self.assertGreaterEqual(len(json_rows), 11)
        self.assertTrue(all(row["artifactEvidenceType"] == "synthetic_fixture" for row in json_rows))
        self.assertIn("archive-sell-yes-low", {row.get("id") for row in json_rows})

    def test_archive_csv_fixture_parses_trade_and_flagged_rows(self) -> None:
        records = self._synthetic_records()
        families = {row["artifactFamily"] for row in records}

        self.assertIn("archive_trades_csv", families)
        self.assertIn("archive_flagged_csv", families)
        self.assertTrue(any(row.get("raw_token_price") == "0.20" for row in records))

    def test_sell_yes_and_sell_no_inversions_are_counted(self) -> None:
        report = build_archive_evidence_audit(self._synthetic_records())
        affected = report["summary"]["affectedRows"]
        examples = report["affectedExamples"]

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertGreaterEqual(affected["lowProbability30Changed"], 4)
        self.assertGreaterEqual(affected["directionChanged"], 4)
        self.assertTrue(any(item["rowId"] == "archive-sell-yes-low" for item in examples))
        self.assertTrue(any(item["rowId"] == "archive-sell-no-low" for item in examples))

    def test_old_fields_only_row_uses_old_probability_without_phase1_fields(self) -> None:
        report = build_archive_evidence_audit(self._synthetic_records())
        field_counts = report["summary"]["fieldCoverageCounts"]
        examples = report["affectedExamples"]

        self.assertGreaterEqual(field_counts["old_fields_only_rows"], 1)
        self.assertTrue(any(item["rowId"] == "archive-old-fields-only" for item in examples))

    def test_malformed_rows_do_not_crash_and_stay_unknown(self) -> None:
        report = build_archive_evidence_audit(self._synthetic_records())
        missing = report["summary"]["missingFieldTaxonomy"]

        self.assertGreaterEqual(missing["missing_or_unknown_token_price"], 2)
        self.assertGreaterEqual(report["summary"]["fieldCoverageCounts"]["lossy_csv_without_price"], 1)

    def test_synthetic_fixtures_are_classified_separately_from_existing_fixtures(self) -> None:
        artifacts = discover_archive_artifacts(ROOT)
        synthetic = [item for item in artifacts if item["artifactEvidenceType"] == "synthetic_fixture"]
        existing = [item for item in artifacts if item["artifactEvidenceType"] == "existing_test_fixture"]

        self.assertGreaterEqual(len(synthetic), 3)
        self.assertTrue(existing)
        self.assertTrue(all("side_outcome_phase2_archive" in item["relativePath"] for item in synthetic))

    def test_cli_writes_outputs_and_runtime_paths_do_not_import_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_md = Path(tmp) / "archive_gap.md"
            output_json = Path(tmp) / "archive_gap.json"
            exit_code = main(
                [
                    "--root",
                    str(ROOT),
                    "--output-md",
                    str(output_md),
                    "--output-json",
                    str(output_json),
                    "--max-files",
                    "30",
                    "--max-rows-per-file",
                    "25",
                    "--quiet",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_md.exists())
            self.assertTrue(output_json.exists())
            self.assertIn("Archive Evidence Gap", output_md.read_text(encoding="utf-8"))
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertGreater(payload["summary"]["artifactsDiscovered"], payload["summary"]["artifactsSelected"])
            self.assertGreaterEqual(payload["summary"]["evidenceTypeCounts"]["synthetic_fixture"]["artifacts"], 3)

        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/browser_ui.html",
            "app/browser_event_forensic_ui.html",
            "app/storage.py",
            "app/polymarket.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("side_outcome_archive_evidence_audit", source)


if __name__ == "__main__":
    unittest.main()
