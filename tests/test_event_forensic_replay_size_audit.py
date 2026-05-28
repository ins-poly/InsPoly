from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_forensic_replay_size_audit import (
    REPORT_TYPE,
    build_replay_size_audit,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_report(path: Path, *, candidate_count: int = 2, analysis_scope: str = "event") -> None:
    rows = [
        {
            "tradeId": f"trade-{index}",
            "wallet": f"0x{index:02x}",
            "conditionId": "cond-1",
            "timestamp": f"2026-05-26T00:00:{index:02d}+00:00",
            "rawOrderSide": "BUY",
            "rawTokenOutcome": "YES",
            "economicSide": "YES",
            "eventForensicScore": 10 + index,
            "finalDisplayTier": "review_required",
        }
        for index in range(candidate_count)
    ]
    payload = {
        "analysis_version": "fixture",
        "analysis_scope": analysis_scope,
        "event": {"slug": "event-slug", "title": "Event"},
        "summary": {"raw_trade_count": 10, "candidate_trade_count": candidate_count},
        "performance": {"total_seconds": 1.0},
        "display_trades": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class EventForensicReplaySizeAuditTests(unittest.TestCase):
    def test_size_audit_builds_snapshot_size_rows_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_report(root / ".inspoly_event_forensic_analyzer/reports/event_forensic_1.json", candidate_count=3)

            audit = build_replay_size_audit(root, generated_at="2026-05-26T00:00:00+00:00")

        self.assertEqual(audit["reportType"], REPORT_TYPE)
        self.assertFalse(audit["networkUsed"])
        self.assertFalse(audit["runtimeBehaviorChanged"])
        self.assertEqual(audit["summary"]["reportsAudited"], 1)
        self.assertEqual(audit["summary"]["maxCandidateRowsInSnapshot"], 3)
        self.assertGreater(audit["summary"]["maxSnapshotBytes"], 0)
        self.assertTrue(audit["reportRows"][0]["candidateTradeSetIdsStable"])
        self.assertEqual(audit["reportRows"][0]["candidateRowsInSourceReport"], 3)

    def test_old_report_without_candidate_rows_loads_absent_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / ".inspoly_event_forensic_analyzer/reports/event_forensic_old.json"
            report.parent.mkdir(parents=True)
            report.write_text(
                json.dumps({"analysis_scope": "event", "event": {"slug": "old-event"}, "summary": {}}),
                encoding="utf-8",
            )

            audit = build_replay_size_audit(root, generated_at="2026-05-26T00:00:00+00:00")

        self.assertEqual(audit["summary"]["oldReportFallbackReports"], 1)
        self.assertTrue(audit["summary"]["oldReportsLoadAbsentSafe"])
        self.assertIn("no_candidate_rows_available_in_source_report", audit["reportRows"][0]["qualityNotes"])

    def test_cli_writes_policy_audit_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            _write_report(root / ".inspoly_event_forensic_analyzer/reports/event_forensic_1.json")
            output = Path(tmp) / "audit.json"

            self.assertEqual(
                main(
                    [
                        "--root",
                        str(root),
                        "--output",
                        str(output),
                        "--generated-at",
                        "2026-05-26T00:00:00+00:00",
                        "--quiet",
                    ]
                ),
                0,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["reportType"], REPORT_TYPE)
        self.assertFalse(payload["storageSchemaChanged"])

    def test_tool_source_has_no_network_or_storage_imports(self) -> None:
        source = (ROOT / "tools/event_forensic_replay_size_audit.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("http.client", source)
        self.assertNotIn("socket", source)
        self.assertNotIn("Storage(", source)


if __name__ == "__main__":
    unittest.main()
