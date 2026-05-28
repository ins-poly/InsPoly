from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.shadow_low_odds_sensitivity import (
    REPORT_TYPE,
    evaluate_low_odds_sensitivity,
    main,
    markdown_report,
    write_sensitivity_outputs,
)


ROOT = Path(__file__).resolve().parents[1]


def sample_batch() -> dict[str, object]:
    def record(price: float, cash: float, *, stale: bool = False) -> dict[str, object]:
        fields = {"side": "BUY", "price": price, "cash_amount": cash}
        if stale:
            fields["stale_resolution"] = True
        return {"recordType": "trade_exposure", "fields": fields}

    return {
        "artifacts": [
            {
                "artifactPath": "artifact-a.json",
                "normalizedRecords": [
                    record(0.1, 1200),
                    record(0.25, 2000),
                    record(0.9, 5000),
                    record(0.05, 2000, stale=True),
                ],
            }
        ]
    }


class ShadowLowOddsSensitivityTests(unittest.TestCase):
    def test_sensitivity_keeps_default_thresholds_unchanged_and_counts_controls(self) -> None:
        report = evaluate_low_odds_sensitivity(sample_batch())

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertTrue(report["defaultThresholdsUnchanged"])
        self.assertEqual(report["summary"]["nearCertaintyControlCount"], 1)
        self.assertEqual(report["summary"]["staleResolutionControlCount"], 1)

        default = next(item for item in report["variants"] if item["priceCeiling"] == "0.15")
        wider = next(item for item in report["variants"] if item["priceCeiling"] == "0.3")
        self.assertEqual(default["triggeredCount"], 1)
        self.assertEqual(wider["triggeredCount"], 2)

    def test_sensitivity_output_is_explicit_json_and_markdown(self) -> None:
        report = evaluate_low_odds_sensitivity(sample_batch())
        markdown = markdown_report(report)

        self.assertIn("Shadow Low-Odds Sensitivity", markdown)
        self.assertIn("Default thresholds unchanged", markdown)

        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_sensitivity_outputs(report, tmp)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reportType"], REPORT_TYPE)

    def test_cli_creates_explicit_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_json = Path(tmp) / "batch.json"
            input_json.write_text(json.dumps(sample_batch()), encoding="utf-8")
            output_json = Path(tmp) / "nested" / "sensitivity.json"
            output_md = Path(tmp) / "nested" / "sensitivity.md"
            exit_code = main(
                [
                    "--batch-normalization-json",
                    str(input_json),
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

    def test_sensitivity_tool_is_not_imported_by_runtime_paths(self) -> None:
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
            self.assertNotIn("shadow_low_odds_sensitivity", source)


if __name__ == "__main__":
    unittest.main()
