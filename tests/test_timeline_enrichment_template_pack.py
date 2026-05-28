from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from tools.timeline_enrichment_template_pack import FIELDS, build_template_pack, main


ROOT = Path(__file__).resolve().parents[1]


class TimelineEnrichmentTemplatePackTests(unittest.TestCase):
    def test_template_requires_source_timestamp_and_catalyst(self) -> None:
        payload = build_template_pack(
            [
                {
                    "timeline_id": "case-1",
                    "source_url": "https://example.invalid/source",
                    "source_timestamp_utc": "2026-05-25T00:00:00+00:00",
                    "catalyst": "public report",
                }
            ]
        )

        self.assertEqual(payload["gateDecision"], "timeline_template_pack_ready")
        self.assertFalse(payload["networkUsed"])
        self.assertFalse(payload["summary"]["timestampsInferred"])
        self.assertEqual(payload["summary"]["invalidSampleRowCount"], 0)

    def test_invalid_sample_row_is_reported_not_inferred(self) -> None:
        payload = build_template_pack([{"timeline_id": "case-2", "source_url": "not-a-url"}])

        self.assertEqual(payload["summary"]["invalidSampleRowCount"], 1)
        self.assertIn("missing_required:source_timestamp_utc", payload["validationRows"][0]["errors"])
        self.assertIn("missing_required:catalyst", payload["validationRows"][0]["errors"])
        self.assertFalse(payload["validationRows"][0]["runtimeUseAllowed"])

    def test_cli_writes_header_only_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "timeline.json"
            template = Path(tmp) / "timeline.csv"
            self.assertEqual(main(["--output", str(output), "--template", str(template), "--quiet"]), 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            with template.open(newline="", encoding="utf-8") as handle:
                headers = next(csv.reader(handle))

        self.assertEqual(headers, list(FIELDS))
        self.assertEqual(payload["summary"]["sampleRowCount"], 0)

    def test_tool_source_has_no_network_imports(self) -> None:
        source = (ROOT / "tools/timeline_enrichment_template_pack.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("http.client", source)
        self.assertNotIn("socket", source)


if __name__ == "__main__":
    unittest.main()
