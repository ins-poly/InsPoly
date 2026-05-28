from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_forensic_measurement_target_inventory import build_target_inventory, main as inventory_main
from tools.event_forensic_measurement_target_resolution import (
    build_target_resolution,
    main as resolution_main,
    subset_policy_gate,
)


class EventForensicMeasurementTargetSelectionTests(unittest.TestCase):
    def test_inventory_proposes_bounded_whole_event_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = root / "inventory.json"
            inventory.write_text(
                json.dumps(
                    {
                        "slowestReports": [
                            {
                                "analysisScope": "selected_market",
                                "eventSlug": "selected-event",
                                "analysisMarketCount": 1,
                                "path": "selected.json",
                            },
                            {
                                "analysisScope": "whole_event",
                                "eventSlug": "bounded-event",
                                "eventTitle": "Bounded Event",
                                "analysisMarketCount": 4,
                                "totalEventMarketCount": 4,
                                "rawTradeCount": 5000,
                                "candidateTradeCount": 100,
                                "candidateWalletCount": 200,
                                "truncatedMarketCount": 1,
                                "totalSeconds": 80.0,
                                "dominantBottleneck": "prefetch_wallet_context_seconds",
                                "path": "bounded.json",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            payload = build_target_inventory(root=root, inventory_path=inventory)

        self.assertEqual(payload["summary"]["candidateCount"], 1)
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["eventSlug"], "bounded-event")
        self.assertTrue(candidate["likelyWithinLiveMarketBound"])
        self.assertTrue(candidate["savedLocalMeasurementSafe"])
        self.assertIn("saved candidate rows", candidate["whyUseful"])

    def test_inventory_cli_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = root / "inventory.json"
            output = root / "targets.json"
            inventory.write_text(json.dumps({"slowestReports": []}), encoding="utf-8")

            self.assertEqual(
                inventory_main(["--root", str(root), "--inventory", str(inventory), "--output", str(output), "--quiet"]),
                0,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["reportType"], "event_forensic_measurement_target_inventory")
        self.assertFalse(payload["networkUsed"])

    def test_resolution_finds_safe_target_with_fake_resolver(self) -> None:
        candidates = [
            {
                "eventSlug": "safe-event",
                "inputValue": "https://polymarket.com/event/safe-event",
                "savedAnalysisMarketCount": 4,
                "savedRawTradeCount": 5000,
                "savedCandidateWalletCount": 200,
                "savedLocalMeasurementSafe": True,
            }
        ]

        payload = build_target_resolution(candidates, resolver=lambda _url: _resolved_target(4))

        self.assertEqual(payload["gateDecision"], "safe_target_found")
        self.assertEqual(payload["subsetPolicyGate"], "subset_policy_not_needed")
        self.assertTrue(payload["selectedSafeTarget"]["safeForFullMeasurement"])
        self.assertFalse(payload["runtimeBehaviorChanged"])

    def test_resolution_marks_larger_event_for_subset_policy(self) -> None:
        candidates = [
            {
                "eventSlug": "large-event",
                "inputValue": "https://polymarket.com/event/large-event",
                "savedAnalysisMarketCount": 6,
                "savedRawTradeCount": 5000,
                "savedCandidateWalletCount": 200,
                "savedLocalMeasurementSafe": True,
            }
        ]

        payload = build_target_resolution(candidates, resolver=lambda _url: _resolved_target(15))

        self.assertEqual(payload["gateDecision"], "no_safe_target_found")
        self.assertEqual(payload["subsetPolicyGate"], "subset_policy_ready_for_user_approval")
        self.assertIn("live_market_count_exceeds_bound", payload["resolvedCandidates"][0]["blockReasons"])

    def test_subset_policy_gate_contract(self) -> None:
        self.assertEqual(subset_policy_gate("safe_target_found"), "subset_policy_not_needed")
        self.assertEqual(subset_policy_gate("no_safe_target_found"), "subset_policy_ready_for_user_approval")

    def test_resolution_cli_writes_output_with_empty_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = root / "targets.json"
            output = root / "resolution.json"
            inventory.write_text(json.dumps({"candidates": []}), encoding="utf-8")

            self.assertEqual(
                resolution_main(["--input", str(inventory), "--output", str(output), "--quiet"]),
                0,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["gateDecision"], "target_resolution_scope_risk")
        self.assertFalse(payload["storageMutated"])

    def test_tools_do_not_import_network_clients_at_module_import(self) -> None:
        resolution_source = Path("tools/event_forensic_measurement_target_resolution.py").read_text(encoding="utf-8")
        inventory_source = Path("tools/event_forensic_measurement_target_inventory.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", resolution_source)
        self.assertNotIn("urlopen", resolution_source)
        self.assertNotIn("http.client", inventory_source)


def _resolved_target(market_count: int) -> dict[str, object]:
    return {
        "analysisScope": "event",
        "event": {"slug": "event-a", "title": "Event A"},
        "availableMarkets": [
            {"marketSlug": f"market-{index}", "marketTitle": f"Market {index}", "selected": False}
            for index in range(market_count)
        ],
    }


if __name__ == "__main__":
    unittest.main()
