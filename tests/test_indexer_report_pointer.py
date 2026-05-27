from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
import unittest

from app.report_pointer import (
    POINTER_FIELD,
    POINTER_SCHEMA_VERSION,
    ReportPointerValidationError,
    attach_indexer_warehouse_pointer,
    normalize_indexer_warehouse_pointer,
)


ROOT = Path(__file__).resolve().parents[1]


def _minimal_pointer() -> dict[str, object]:
    return {
        "artifactType": "indexer_warehouse_query",
        "artifactPath": "validation_outputs/inspoly_indexer_warehouse_w3_query_run_20260527.json",
        "artifactId": "w3-query-run",
        "sourceReportId": "report.json",
    }


class IndexerReportPointerTests(unittest.TestCase):
    def test_normalizes_metadata_only_pointer(self) -> None:
        normalized = normalize_indexer_warehouse_pointer(
            _minimal_pointer(),
            generated_at=datetime(2026, 5, 27, tzinfo=UTC),
        )

        self.assertEqual(normalized["pointerVersion"], POINTER_SCHEMA_VERSION)
        self.assertTrue(normalized["sidecarOnly"])
        self.assertTrue(normalized["advisoryOnly"])
        self.assertFalse(normalized["metricsCopied"])
        self.assertFalse(normalized["scoringEffect"])
        self.assertFalse(normalized["routingEffect"])
        self.assertFalse(normalized["uiRequired"])
        self.assertFalse(normalized["liveRefresh"])
        self.assertFalse(normalized["rawDbReadRequired"])
        self.assertEqual(normalized["generatedAt"], "2026-05-27T00:00:00+00:00")

    def test_accepts_static_draft_report_ui_flag_and_normalizes_to_ui_required(self) -> None:
        pointer = _minimal_pointer()
        pointer["reportUiRequired"] = False

        normalized = normalize_indexer_warehouse_pointer(pointer)

        self.assertFalse(normalized["uiRequired"])
        self.assertNotIn("reportUiRequired", normalized)

    def test_rejects_copied_metrics(self) -> None:
        pointer = _minimal_pointer()
        pointer["tradeCount"] = 580

        with self.assertRaises(ReportPointerValidationError):
            normalize_indexer_warehouse_pointer(pointer)

    def test_rejects_row_level_context(self) -> None:
        pointer = _minimal_pointer()
        pointer["qualityNotes"] = [{"rowsByTarget": {"market": 60}}]

        with self.assertRaises(ReportPointerValidationError):
            normalize_indexer_warehouse_pointer(pointer)

    def test_rejects_unsafe_flags(self) -> None:
        pointer = _minimal_pointer()
        pointer["metricsCopied"] = True

        with self.assertRaises(ReportPointerValidationError):
            normalize_indexer_warehouse_pointer(pointer)

    def test_attach_returns_report_copy_with_top_level_pointer(self) -> None:
        report = {"generated_at": "2026-05-27T00:00:00+00:00", "cases": []}

        updated = attach_indexer_warehouse_pointer(report, _minimal_pointer())

        self.assertIn(POINTER_FIELD, updated)
        self.assertNotIn(POINTER_FIELD, report)
        self.assertEqual(updated["cases"], [])

    def test_static_fixture_matches_runtime_validator(self) -> None:
        fixture = json.loads((ROOT / "tests/fixtures/indexer_w4_report_pointer_example.json").read_text())

        normalized = normalize_indexer_warehouse_pointer(fixture[POINTER_FIELD])

        self.assertEqual(normalized["pointerVersion"], POINTER_SCHEMA_VERSION)
        self.assertFalse(normalized["metricsCopied"])


if __name__ == "__main__":
    unittest.main()
