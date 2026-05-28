from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.evaluate_reconstruction_shadow_pnl import (
    REPORT_TYPE,
    evaluate_reconstruction_dir,
    evaluate_reconstruction_dirs,
    main,
    markdown_report,
    write_reconstruction_pnl_outputs,
)


ROOT = Path(__file__).resolve().parents[1]
GOOD = ROOT / "tests" / "fixtures" / "shadow_input_normalization" / "reconstruction_report"
MISSING_CURRENT = ROOT / "tests" / "fixtures" / "reconstruction_shadow_pnl" / "missing_current"


class ReconstructionShadowPnlEvaluationTests(unittest.TestCase):
    def test_reconstruction_pnl_available_when_current_price_exists(self) -> None:
        artifact = evaluate_reconstruction_dir(GOOD)

        self.assertEqual(artifact["status"], "available")
        self.assertTrue(artifact["pnlIsContextOnly"])
        self.assertGreater(artifact["ledgerRecordCount"], 0)
        self.assertGreater(artifact["currentPriceRecordCount"], 0)
        self.assertIsNotNone(artifact["pnlValue"])

    def test_missing_current_price_remains_unknown(self) -> None:
        artifact = evaluate_reconstruction_dir(MISSING_CURRENT)

        self.assertEqual(artifact["status"], "unknown")
        self.assertFalse(artifact["currentPriceAvailable"])
        self.assertIsNone(artifact["pnlValue"])
        self.assertIn("current_prices_missing_not_computed", artifact["qualityNotes"])

    def test_combined_report_is_sidecar_only_and_explicit(self) -> None:
        report = evaluate_reconstruction_dirs([GOOD, MISSING_CURRENT])
        markdown = markdown_report(report)

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertTrue(report["summary"]["pnlContextOnly"])
        self.assertEqual(report["summary"]["artifactCount"], 2)
        self.assertIn("Reconstruction Shadow PnL Evaluation", markdown)

        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_reconstruction_pnl_outputs(report, tmp)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reportType"], REPORT_TYPE)

    def test_cli_creates_explicit_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_json = Path(tmp) / "nested" / "pnl.json"
            output_md = Path(tmp) / "nested" / "pnl.md"
            exit_code = main(
                [
                    "--artifact-dir",
                    str(GOOD),
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

    def test_reconstruction_pnl_tool_is_not_imported_by_runtime_paths(self) -> None:
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
            self.assertNotIn("evaluate_reconstruction_shadow_pnl", source)


if __name__ == "__main__":
    unittest.main()
