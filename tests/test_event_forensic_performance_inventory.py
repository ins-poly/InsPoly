from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_forensic_performance_inventory import (
    REPORT_TYPE,
    build_performance_inventory,
    discover_report_paths,
    main as inventory_main,
)


ROOT = Path(__file__).resolve().parents[1]


class EventForensicPerformanceInventoryTests(unittest.TestCase):
    def test_inventory_reads_saved_reports_without_raw_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "event_forensic_outputs/event_forensic_20260525_010203"
            report_dir.mkdir(parents=True)
            raw_dir = report_dir / "raw_event_bundle"
            raw_dir.mkdir()
            (raw_dir / "trades.json").write_text("[]", encoding="utf-8")
            (report_dir / "event_analysis.json").write_text(
                json.dumps(
                    {
                        "analysis_scope": "event",
                        "event": {"slug": "event-a", "title": "Event A", "marketCount": 3},
                        "summary": {
                            "candidate_trade_count": 12,
                            "analysis_market_count": 3,
                            "total_event_market_count": 3,
                            "truncated_market_count": 1,
                        },
                        "performance": {
                            "collect_event_trades_seconds": 4.5,
                            "prefetch_wallet_context_seconds": 2.0,
                            "score_candidates_seconds": 1.0,
                            "total_seconds": 9.0,
                            "wallet_context_count": 5,
                        },
                    }
                ),
                encoding="utf-8",
            )

            paths = discover_report_paths(root)
            report = build_performance_inventory(root)

        self.assertEqual([path.name for path in paths], ["event_analysis.json"])
        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertEqual(report["summary"]["wholeEventRunCount"], 1)
        self.assertEqual(report["summary"]["runsWithTruncatedMarkets"], 1)
        self.assertEqual(report["summary"]["dominantBottleneckCounts"]["collect_event_trades_seconds"], 1)

    def test_inventory_classifies_selected_market_scope_from_legacy_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / ".inspoly/reports"
            reports.mkdir(parents=True)
            (reports / "event_forensic_20260525_010203.json").write_text(
                json.dumps(
                    {
                        "analysis_scope": "market",
                        "selected_market_slug": "market-a",
                        "event": {"slug": "event-a", "title": "Event A", "marketCount": 1},
                        "summary": {"candidate_trade_count": 2, "display_trade_count": 1},
                        "performance": {"prefetch_wallet_context_seconds": 3.0, "total_seconds": 4.0},
                    }
                ),
                encoding="utf-8",
            )

            report = build_performance_inventory(root)

        self.assertEqual(report["summary"]["selectedMarketRunCount"], 1)
        self.assertEqual(report["slowestReports"][0]["analysisScope"], "selected_market")
        self.assertEqual(report["slowestReports"][0]["dominantBottleneck"], "prefetch_wallet_context_seconds")

    def test_inventory_cli_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "event_forensic_outputs/event_forensic_20260525_010203"
            report_dir.mkdir(parents=True)
            (report_dir / "event_analysis.json").write_text(
                json.dumps({"analysis_scope": "event", "event": {}, "summary": {}, "performance": {"total_seconds": 1.0}}),
                encoding="utf-8",
            )
            output = root / "inventory.json"

            self.assertEqual(inventory_main(["--root", str(root), "--output", str(output), "--quiet"]), 0)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["reportType"], REPORT_TYPE)
        self.assertFalse(payload["runtimeBehaviorChanged"])

    def test_inventory_tool_has_no_network_imports(self) -> None:
        source = (ROOT / "tools/event_forensic_performance_inventory.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("http.client", source)
        self.assertNotIn("socket", source)


if __name__ == "__main__":
    unittest.main()
