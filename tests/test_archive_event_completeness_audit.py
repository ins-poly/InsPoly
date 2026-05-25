from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.archive_event_completeness_audit import (
    REPORT_TYPE,
    build_completeness_audit,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


class ArchiveEventCompletenessAuditTests(unittest.TestCase):
    def test_detects_explicit_event_truncation_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "event_forensic_outputs/event_forensic_20260525_010203"
            report_dir.mkdir(parents=True)
            (report_dir / "event_analysis.json").write_text(
                json.dumps(
                    {
                        "analysis_scope": "event",
                        "event": {"marketCount": 4},
                        "summary": {"analysis_market_count": 4, "truncated_market_count": 2},
                        "performance": {"trade_collection_raw_trade_rows": 5000},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_completeness_audit(root)

        self.assertEqual(payload["reportType"], REPORT_TYPE)
        self.assertFalse(payload["networkUsed"])
        self.assertEqual(payload["summary"]["truncatedReportedCount"], 1)
        self.assertEqual(payload["artifactRows"][0]["completenessClassification"], "truncated_reported")
        self.assertTrue(payload["artifactRows"][0]["rankingMayBeAffected"])

    def test_handles_old_report_without_marker_as_legacy_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / ".inspoly/reports"
            reports.mkdir(parents=True)
            (reports / "event_forensic_20260525_010203.json").write_text(
                json.dumps({"analysis_scope": "market", "event": {"marketCount": 6}, "summary": {"candidate_trade_count": 3}}),
                encoding="utf-8",
            )

            payload = build_completeness_audit(root)

        self.assertEqual(payload["artifactRows"][0]["scope"], "selected_market")
        self.assertEqual(payload["artifactRows"][0]["completenessClassification"], "unknown_legacy")

    def test_classifies_selected_market_complete_without_treating_siblings_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / ".inspoly/reports"
            reports.mkdir(parents=True)
            (reports / "event_forensic_20260525_010203.json").write_text(
                json.dumps(
                    {
                        "analysis_scope": "market",
                        "event": {"marketCount": 12},
                        "summary": {"analysis_market_count": 1, "total_event_market_count": 12, "truncated_market_count": 0},
                        "performance": {},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_completeness_audit(root)

        self.assertEqual(payload["artifactRows"][0]["scope"], "selected_market")
        self.assertEqual(payload["artifactRows"][0]["completenessClassification"], "complete_local")

    def test_cli_writes_output_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / ".inspoly_archive_researcher/reports"
            report_dir.mkdir(parents=True)
            (report_dir / "archive_research_20260525_010203.json").write_text(
                json.dumps({"topic_scope": "Politics", "raw_trade_count": 10, "truncated_market_count": 0}),
                encoding="utf-8",
            )
            output = root / "audit.json"

            self.assertEqual(main(["--root", str(root), "--output", str(output), "--quiet"]), 0)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(payload["savedArtifactsMutated"])
        self.assertEqual(payload["artifactRows"][0]["artifactFamily"], "archive")

    def test_tool_source_has_no_network_imports(self) -> None:
        source = (ROOT / "tools/archive_event_completeness_audit.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("http.client", source)
        self.assertNotIn("socket", source)


if __name__ == "__main__":
    unittest.main()
