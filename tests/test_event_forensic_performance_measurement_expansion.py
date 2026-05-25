from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_forensic_performance_measurement_expansion import (
    build_expansion_candidates,
    main,
)


class EventForensicPerformanceMeasurementExpansionTests(unittest.TestCase):
    def test_previous_safe_unmeasured_targets_are_prioritized(self) -> None:
        payload = build_expansion_candidates(
            previous_inventory={"candidates": []},
            previous_resolution={
                "resolvedCandidates": [
                    {
                        "eventSlug": "measured",
                        "safeForFullMeasurement": True,
                        "inputValue": "https://polymarket.com/event/measured",
                    },
                    {
                        "eventSlug": "next-safe",
                        "safeForFullMeasurement": True,
                        "inputValue": "https://polymarket.com/event/next-safe",
                        "savedAnalysisMarketCount": 1,
                        "savedRawTradeCount": 1000,
                        "savedCandidateTradeCount": 10,
                    },
                ]
            },
            previous_measurement={
                "measurementGate": "performance_measurement_complete",
                "measurement": {"eventSlug": "measured"},
            },
            max_candidates=3,
            include_local_inventory=False,
        )

        slugs = [row["eventSlug"] for row in payload["candidates"]]
        self.assertIn("next-safe", slugs)
        self.assertNotIn("measured", slugs)
        self.assertIn("previous_safe_target_not_yet_measured", payload["candidates"][0]["expansionSources"])

    def test_inventory_candidates_are_deduped_and_exclude_measured(self) -> None:
        payload = build_expansion_candidates(
            previous_inventory={
                "candidates": [
                    {
                        "eventSlug": "measured",
                        "inputValue": "https://polymarket.com/event/measured",
                        "analysisScope": "whole_event",
                    },
                    {
                        "eventSlug": "candidate-a",
                        "inputValue": "https://polymarket.com/event/candidate-a",
                        "analysisScope": "whole_event",
                        "savedAnalysisMarketCount": 1,
                        "savedRawTradeCount": 2500,
                        "savedCandidateTradeCount": 200,
                        "savedLocalMeasurementSafe": True,
                        "likelyWithinLiveMarketBound": True,
                    },
                ]
            },
            previous_resolution={"resolvedCandidates": []},
            previous_measurement={
                "measurementGate": "performance_measurement_complete",
                "measurement": {"eventSlug": "measured"},
            },
            max_candidates=5,
            include_local_inventory=False,
        )

        slugs = [row["eventSlug"] for row in payload["candidates"]]
        self.assertIn("candidate-a", slugs)
        self.assertNotIn("measured", slugs)
        self.assertFalse(payload["networkUsed"])
        self.assertFalse(payload["runtimeBehaviorChanged"])

    def test_cli_writes_expansion_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inv = root / "inventory.json"
            res = root / "resolution.json"
            meas = root / "measurement.json"
            out = root / "out.json"
            inv.write_text(json.dumps({"candidates": []}), encoding="utf-8")
            res.write_text(
                json.dumps(
                    {
                        "resolvedCandidates": [
                            {
                                "eventSlug": "next-safe",
                                "safeForFullMeasurement": True,
                                "inputValue": "https://polymarket.com/event/next-safe",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            meas.write_text(json.dumps({"measurementGate": "performance_measurement_complete", "measurement": {}}), encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "--previous-inventory",
                        str(inv),
                        "--previous-resolution",
                        str(res),
                        "--previous-measurement",
                        str(meas),
                        "--output",
                        str(out),
                        "--quiet",
                    ]
                ),
                0,
            )
            payload = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(payload["reportType"], "event_forensic_performance_measurement_expansion_candidates")


if __name__ == "__main__":
    unittest.main()
