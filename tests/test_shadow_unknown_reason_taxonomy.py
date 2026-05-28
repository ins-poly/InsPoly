from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.batch_evaluate_normalized_shadow_context import batch_evaluate_from_root
from tools.batch_normalize_shadow_inputs import batch_normalize_from_root
from tools.shadow_unknown_reason_taxonomy import (
    CATEGORY_LOSSY_CSV,
    CATEGORY_MISSING_CURRENT_PRICE,
    CATEGORY_MISSING_TOKEN_ID,
    CATEGORY_MISSING_MICROSTRUCTURE,
    CATEGORY_MISSING_REFERENCE_PRICE,
    CATEGORY_QUALITY_DERIVATION,
    CATEGORY_UNSAFE_HINDSIGHT,
    REPORT_TYPE,
    build_taxonomy_report,
    classify_reason,
    main,
    markdown_report,
    write_taxonomy_outputs,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shadow_artifact_corpus_inventory"


class ShadowUnknownReasonTaxonomyTests(unittest.TestCase):
    def test_reason_classifier_covers_required_categories(self) -> None:
        self.assertEqual(classify_reason("current price is missing"), CATEGORY_MISSING_CURRENT_PRICE)
        self.assertEqual(classify_reason("reference price is unavailable"), CATEGORY_MISSING_REFERENCE_PRICE)
        self.assertEqual(classify_reason("token/current-price/share semantics are incomplete"), CATEGORY_MISSING_TOKEN_ID)
        self.assertEqual(classify_reason("no local orderbook snapshot is present"), CATEGORY_MISSING_MICROSTRUCTURE)
        self.assertEqual(classify_reason("outcome fields are unsafe and reference price is unavailable"), CATEGORY_UNSAFE_HINDSIGHT)
        self.assertEqual(classify_reason("Archive flagged CSV is lossy"), CATEGORY_LOSSY_CSV)
        self.assertEqual(classify_reason("quality_note:cash_amount_from_report_notional_derivable"), CATEGORY_QUALITY_DERIVATION)

    def test_taxonomy_builds_priority_queue_from_batch_outputs(self) -> None:
        normalization = batch_normalize_from_root(FIXTURES, max_artifacts_per_family=2, max_records_per_artifact=10)
        evaluation = batch_evaluate_from_root(FIXTURES, max_artifacts_per_family=2)
        report = build_taxonomy_report(normalization, batch_evaluation=evaluation)

        categories = {item["category"] for item in report["categorySummary"]}

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertIn(CATEGORY_MISSING_CURRENT_PRICE, categories)
        self.assertIn(CATEGORY_MISSING_REFERENCE_PRICE, categories)
        self.assertGreater(report["summary"]["totalObservations"], 0)
        self.assertTrue(report["categorySummary"])

    def test_taxonomy_output_is_explicit_markdown_and_json(self) -> None:
        normalization = batch_normalize_from_root(FIXTURES, max_artifacts_per_family=1, max_records_per_artifact=10)
        report = build_taxonomy_report(normalization)
        markdown = markdown_report(report)

        self.assertIn("Shadow Unknown Reason Taxonomy", markdown)
        self.assertIn("Priority Queue", markdown)

        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_taxonomy_outputs(report, tmp)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reportType"], REPORT_TYPE)

    def test_cli_creates_explicit_outputs(self) -> None:
        normalization = batch_normalize_from_root(FIXTURES, max_artifacts_per_family=1, max_records_per_artifact=10)
        with tempfile.TemporaryDirectory() as tmp:
            input_json = Path(tmp) / "normalization.json"
            input_json.write_text(json.dumps(normalization), encoding="utf-8")
            output_json = Path(tmp) / "nested" / "taxonomy.json"
            output_md = Path(tmp) / "nested" / "taxonomy.md"
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

    def test_taxonomy_tool_is_not_imported_by_runtime_paths(self) -> None:
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
            self.assertNotIn("shadow_unknown_reason_taxonomy", source)


if __name__ == "__main__":
    unittest.main()
