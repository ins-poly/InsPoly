from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.archive_visibility_monitoring_v2 import (
    REPORT_TYPE,
    build_archive_visibility_monitoring_v2,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


class ArchiveVisibilityMonitoringV2Tests(unittest.TestCase):
    def test_monitoring_counts_visibility_tiers_and_lossy_rows(self) -> None:
        report = build_archive_visibility_monitoring_v2(ROOT, max_files=16, max_rows_per_file=120, max_bytes=3_000_000)

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["archiveVisibilityChanged"])
        self.assertGreaterEqual(report["summary"]["visibleOrHardEvidenceRows"], 1)
        self.assertGreaterEqual(report["summary"]["oldOrLossyRows"], 1)
        self.assertGreaterEqual(report["summary"]["missingPriceRows"], 1)

    def test_cli_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "archive_visibility.json"
            self.assertEqual(
                main(["--root", str(ROOT), "--output", str(output), "--max-files", "16", "--quiet"]),
                0,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["gateDecision"], "archive_visibility_monitoring_v2_ready")
            self.assertFalse(payload["runtimeBehaviorChanged"])

    def test_tool_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("archive_visibility_monitoring_v2", source)


if __name__ == "__main__":
    unittest.main()
