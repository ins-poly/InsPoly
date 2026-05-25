from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.gamma_fallback_drift_monitor import build_gamma_fallback_drift_monitor, main


ROOT = Path(__file__).resolve().parents[1]


def _next_data_html() -> str:
    payload = {
        "props": {
            "pageProps": {
                "dehydratedState": {
                    "queries": [
                        {
                            "queryKey": ["/api/event/slug", "event-a"],
                            "state": {
                                "data": {
                                    "slug": "event-a",
                                    "markets": [
                                        {
                                            "slug": "market-a",
                                            "conditionId": "0xcond",
                                            "question": "Market A?",
                                        }
                                    ],
                                }
                            },
                        }
                    ]
                }
            }
        },
        "query": {"slug": ["event-a", "market-a"]},
    }
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(payload) + "</script>"


class GammaFallbackDriftMonitorTests(unittest.TestCase):
    def test_monitor_validates_saved_next_data_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "next_data.html"
            fixture.write_text(_next_data_html(), encoding="utf-8")

            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                payload = build_gamma_fallback_drift_monitor(root, fixture_paths=[fixture])

        self.assertEqual(payload["gateDecision"], "gamma_fallback_monitor_ready")
        self.assertFalse(payload["networkUsed"])
        self.assertEqual(payload["summary"]["shapeOkCount"], 1)
        self.assertTrue(payload["fixtureRows"][0]["sourceMarketPresent"])

    def test_missing_fixtures_request_live_check_without_fetching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_gamma_fallback_drift_monitor(tmp, fixture_paths=[])

        self.assertEqual(payload["gateDecision"], "gamma_fallback_needs_live_check")
        self.assertEqual(payload["summary"]["missingFixtureCount"], 1)

    def test_cli_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "next_data.html"
            fixture.write_text(_next_data_html(), encoding="utf-8")
            output = root / "gamma.json"

            self.assertEqual(main(["--root", str(root), "--fixture", str(fixture), "--output", str(output), "--quiet"]), 0)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["reportType"], "gamma_fallback_drift_monitor")
        self.assertFalse(payload["resolverBehaviorChanged"])

    def test_tool_does_not_call_network_fetch_helpers(self) -> None:
        source = (ROOT / "tools/gamma_fallback_drift_monitor.py").read_text(encoding="utf-8")
        self.assertNotIn("_get_text(", source)
        self.assertNotIn("urlopen(", source)


if __name__ == "__main__":
    unittest.main()
