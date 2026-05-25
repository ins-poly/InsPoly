from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_forensic_bounded_performance_measurement import build_measurement_plan, main


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

    def test_tool_source_has_no_network_imports(self) -> None:
        source = (ROOT / "tools/event_forensic_bounded_performance_measurement.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("http.client", source)
        self.assertNotIn("socket", source)


if __name__ == "__main__":
    unittest.main()
