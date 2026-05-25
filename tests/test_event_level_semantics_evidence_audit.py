from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_level_semantics_evidence_audit import (
    REPORT_TYPE,
    build_event_level_semantics_audit,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


class EventLevelSemanticsEvidenceAuditTests(unittest.TestCase):
    def test_selected_market_and_whole_event_fixtures_are_distinct(self) -> None:
        report = build_event_level_semantics_audit(ROOT, max_files=12, max_bytes=6_000_000)

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertGreaterEqual(report["summary"]["marketScopeReportCount"], 1)
        self.assertGreaterEqual(report["summary"]["wholeEventReportCount"], 1)

    def test_related_markets_do_not_imply_primary_scoring_when_copy_is_clear(self) -> None:
        report = build_event_level_semantics_audit(ROOT, max_files=12, max_bytes=6_000_000)
        fixture = next(
            row
            for row in report["reports"]
            if str(row["path"]).endswith("market_scope_with_sibling_context.json")
        )

        self.assertEqual(fixture["primaryScoringScope"], "selected_market")
        self.assertEqual(fixture["siblingContextTradeCount"], 1)
        self.assertTrue(fixture["scopeCopyClear"])
        self.assertFalse(fixture["possibleScopeAmbiguity"])

    def test_cli_writes_output_and_runtime_paths_do_not_import_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "event_level.json"
            self.assertEqual(
                main(["--root", str(ROOT), "--output", str(output), "--max-files", "12", "--quiet"]),
                0,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(payload["networkUsed"])

        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("event_level_semantics_evidence_audit", source)


if __name__ == "__main__":
    unittest.main()
