from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.analyze_archive_wallet_history_shadow_overlap import (
    REPORT_TYPE,
    analyze_archive_report,
    analyze_archive_reports,
    main,
    markdown_report,
    write_overlap_outputs,
)


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_FIXTURE = ROOT / "tests" / "fixtures" / "shadow_input_normalization" / "archive_report.json"


class ArchiveWalletHistoryShadowOverlapTests(unittest.TestCase):
    def test_archive_overlap_marks_shadow_confidence_as_duplicate_context(self) -> None:
        artifact = analyze_archive_report(ARCHIVE_FIXTURE)
        row = artifact["walletHistoryRows"][0]

        self.assertTrue(row["duplicateProductionSemantics"])
        self.assertTrue(row["shadowUseful"])
        self.assertEqual(row["reason"], "shadow confidence is computed entirely from existing archive wallet-history fields")

    def test_combined_report_recommends_sidecar_or_benchmark_only_for_duplicate_rows(self) -> None:
        report = analyze_archive_reports([ARCHIVE_FIXTURE])
        markdown = markdown_report(report)

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertEqual(report["summary"]["recommendation"], "keep_sidecar_only_or_benchmark_only")
        self.assertIn("Archive Wallet-History Shadow Overlap", markdown)

    def test_overlap_output_is_explicit_json_and_markdown(self) -> None:
        report = analyze_archive_reports([ARCHIVE_FIXTURE])
        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_overlap_outputs(report, tmp)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reportType"], REPORT_TYPE)

    def test_cli_creates_explicit_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_json = Path(tmp) / "nested" / "overlap.json"
            output_md = Path(tmp) / "nested" / "overlap.md"
            exit_code = main(
                [
                    "--artifact-json",
                    str(ARCHIVE_FIXTURE),
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

    def test_overlap_tool_is_not_imported_by_runtime_paths(self) -> None:
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
            self.assertNotIn("analyze_archive_wallet_history_shadow_overlap", source)


if __name__ == "__main__":
    unittest.main()
