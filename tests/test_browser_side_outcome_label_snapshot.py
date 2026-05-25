from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.browser_side_outcome_label_snapshot import (
    REPORT_TYPE,
    build_browser_label_snapshot,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


class BrowserSideOutcomeLabelSnapshotTests(unittest.TestCase):
    def test_snapshot_labels_token_price_and_economic_probability(self) -> None:
        report = build_browser_label_snapshot(ROOT)

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["uiSortingFilteringChanged"])
        self.assertTrue(report["summary"]["tokenPriceLabelPresent"])
        self.assertTrue(report["summary"]["economicProbabilityLabelPresent"])
        self.assertTrue(report["summary"]["entryChanceMisleadingLabelAbsent"])

    def test_cli_writes_output_and_does_not_touch_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "labels.json"
            self.assertEqual(main(["--root", str(ROOT), "--output", str(output), "--quiet"]), 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn(payload["gateDecision"], {"browser_label_contract_ok", "browser_label_contract_needs_copy_fix"})

        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("browser_side_outcome_label_snapshot", source)


if __name__ == "__main__":
    unittest.main()
