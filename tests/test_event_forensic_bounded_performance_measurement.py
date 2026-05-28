from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_forensic_bounded_performance_measurement import (
    MeasurementBounds,
    build_measurement_plan,
    build_summary,
    build_target_selection_payload,
    main,
    select_bounded_target,
)


ROOT = Path(__file__).resolve().parents[1]


class EventForensicBoundedPerformanceMeasurementTests(unittest.TestCase):
    def test_missing_env_blocks_live_measurement_without_network(self) -> None:
        payload = build_measurement_plan(env={})

        self.assertEqual(payload["gateDecision"], "performance_measurement_blocked_missing_env")
        self.assertFalse(payload["networkUsed"])
        self.assertFalse(payload["measurementExecuted"])
        self.assertFalse(payload["envStatus"]["secretsPrinted"])

    def test_scope_bounds_are_enforced(self) -> None:
        payload = build_measurement_plan(max_events=2, max_markets=9, env={"POLYGON_RPC_URL": "https://example.invalid"})

        self.assertEqual(payload["gateDecision"], "performance_measurement_scope_exceeded")
        self.assertIn("max_events_exceeds_campaign_bound", payload["boundViolations"])
        self.assertIn("max_markets_exceeds_campaign_bound", payload["boundViolations"])

    def test_cli_writes_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "plan.json"
            self.assertEqual(main(["--output", str(output), "--quiet"]), 0)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(payload["runtimeBehaviorChanged"])
        self.assertFalse(payload["networkUsed"])

    def test_selects_bounded_whole_event_target_from_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "reports"
            report_dir.mkdir()
            source_report = report_dir / "event_analysis.json"
            source_report.write_text(
                json.dumps({"analysis_settings": {"min_notional": "250.00"}}),
                encoding="utf-8",
            )
            inventory = root / "inventory.json"
            inventory.write_text(
                json.dumps(
                    {
                        "slowestReports": [
                            {
                                "analysisScope": "whole_event",
                                "eventSlug": "too-large",
                                "analysisMarketCount": 12,
                                "rawTradeCount": 1000,
                                "candidateWalletCount": 20,
                                "path": str(source_report),
                            },
                            {
                                "analysisScope": "whole_event",
                                "eventSlug": "bounded-event",
                                "eventTitle": "Bounded Event",
                                "analysisMarketCount": 6,
                                "totalEventMarketCount": 6,
                                "rawTradeCount": 10000,
                                "candidateWalletCount": 300,
                                "truncatedMarketCount": 2,
                                "totalSeconds": 120.0,
                                "path": str(source_report),
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            target, rejected = select_bounded_target(root=root, inventory_path=inventory, bounds=MeasurementBounds())

        self.assertIsNotNone(target)
        self.assertEqual(target["eventSlug"], "bounded-event")
        self.assertEqual(target["minNotional"], "250.00")
        self.assertIn("analysis_market_count_exceeds_bound", {row["rejectionReason"] for row in rejected})

    def test_summary_blocks_when_no_target_is_available(self) -> None:
        selection = build_target_selection_payload(
            target=None,
            rejected_targets=[],
            bounds=MeasurementBounds(),
            env_status={"rpcConfigured": True, "secretValuesPrinted": False},
        )

        summary = build_summary(
            output_dir=Path("/tmp/perf-measurement"),
            bounds=MeasurementBounds(),
            env_status={"rpcConfigured": True, "secretValuesPrinted": False},
            target_selection=selection,
            live_result=None,
        )

        self.assertEqual(summary["summary"]["gateDecision"], "performance_measurement_blocked_no_target")
        self.assertFalse(summary["runtimeBehaviorChanged"])
        self.assertFalse(summary["appStorageMutated"])

    def test_summary_accepts_completed_bounded_result(self) -> None:
        selection = build_target_selection_payload(
            target={"eventSlug": "bounded-event"},
            rejected_targets=[],
            bounds=MeasurementBounds(),
            env_status={"rpcConfigured": True, "secretValuesPrinted": False},
        )

        summary = build_summary(
            output_dir=Path("/tmp/perf-measurement"),
            bounds=MeasurementBounds(),
            env_status={"rpcConfigured": True, "secretValuesPrinted": False},
            target_selection=selection,
            live_result={
                "status": "completed",
                "eventSlug": "bounded-event",
                "analysisMarketCount": 6,
                "rawTradeCount": 10000,
                "candidateTradeCount": 100,
                "candidateWalletCount": 300,
                "truncatedMarketCount": 2,
                "timings": {"collect_event_trades_seconds": 3.0, "total_seconds": 5.0},
            },
        )

        self.assertEqual(summary["summary"]["gateDecision"], "performance_measurement_complete")
        self.assertEqual(summary["summary"]["dominantBottleneck"], "collect_event_trades_seconds")

    def test_tool_source_has_no_network_imports(self) -> None:
        source = (ROOT / "tools/event_forensic_bounded_performance_measurement.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("http.client", source)
        self.assertNotIn("socket", source)


if __name__ == "__main__":
    unittest.main()
