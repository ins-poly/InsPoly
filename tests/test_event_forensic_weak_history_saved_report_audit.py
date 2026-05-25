from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_forensic_weak_history_saved_report_audit import (
    REPORT_TYPE,
    build_saved_report_inventory,
    build_weak_history_saved_report_audit,
    evaluate_saved_report_row,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "event_forensic_weak_history_saved_reports" / "synthetic_event_analysis.json"


class EventForensicWeakHistorySavedReportAuditTests(unittest.TestCase):
    def test_detector_runs_offline_and_marks_synthetic_fixtures(self) -> None:
        report = build_weak_history_saved_report_audit(ROOT, max_files=12, max_bytes=6_000_000, max_rows_per_file=80)

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertIn(report["gateDecision"], {"weak_history_needs_live_rpc_validation", "weak_history_needs_more_saved_reports"})
        self.assertGreaterEqual(report["summary"]["sourceTypeCounts"].get("synthetic_fixture", 0), 1)

    def test_near_certain_later_win_uses_phase2_economic_probability(self) -> None:
        row = evaluate_saved_report_row(
            {
                "id": "sell-yes-inversion",
                "wallet": "0xweak",
                "side": "YES",
                "orderSide": "SELL",
                "price": "0.04",
                "laterWon": "true",
                "winnerRank": "1",
                "eventForensicFlags": ["weak_wallet_track_record"],
            },
            FIXTURE,
            "synthetic_fixture",
        )

        self.assertEqual(row["economicSide"], "NO")
        self.assertEqual(row["economicSideProbability"], "0.96")
        self.assertTrue(row["nearCertainEconomicEntry"])
        self.assertTrue(row["weakHistoryNearCertainLaterWin"])
        self.assertEqual(row["weakHistoryClassification"], "weak_history")

    def test_missing_fields_produce_unknown_not_zero(self) -> None:
        row = evaluate_saved_report_row(
            {
                "id": "missing-price",
                "side": "YES",
                "orderSide": "SELL",
                "laterWon": "true",
                "eventForensicFlags": ["weak_wallet_track_record"],
            },
            FIXTURE,
            "synthetic_fixture",
        )

        self.assertEqual(row["economicSideProbability"], "unknown")
        self.assertFalse(row["nearCertainEconomicEntry"])
        self.assertIn("missing_or_malformed_side_outcome_price", row["qualityNotes"])

    def test_inventory_and_cli_write_outputs(self) -> None:
        inventory = build_saved_report_inventory(ROOT, max_files=12, max_bytes=6_000_000)
        self.assertGreater(inventory["summary"]["artifactCount"], 0)

        with tempfile.TemporaryDirectory() as tmp:
            inventory_path = Path(tmp) / "inventory.json"
            audit_path = Path(tmp) / "audit.json"
            exit_code = main(
                [
                    "--root",
                    str(ROOT),
                    "--inventory-output",
                    str(inventory_path),
                    "--audit-output",
                    str(audit_path),
                    "--max-files",
                    "12",
                    "--max-rows-per-file",
                    "80",
                    "--quiet",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(inventory_path.exists())
            self.assertTrue(audit_path.exists())
            payload = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertFalse(payload["networkUsed"])

    def test_tool_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("event_forensic_weak_history_saved_report_audit", source)


if __name__ == "__main__":
    unittest.main()
