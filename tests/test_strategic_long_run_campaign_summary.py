from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.strategic_long_run_campaign_summary import (
    build_final_summary,
    build_phase3_unblock_requirements,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


class StrategicLongRunCampaignSummaryTests(unittest.TestCase):
    def test_phase3_unblock_requirements_keep_runtime_blocked(self) -> None:
        payload = build_phase3_unblock_requirements(ROOT)

        self.assertEqual(payload["gateDecision"], "phase3_unblock_requirements_documented_keep_blocked")
        self.assertFalse(payload["runtimeBehaviorChanged"])
        self.assertIn("sellMaxLossExposure", payload["requiredSourceFields"])

    def test_final_summary_has_live_rpc_blocker_and_no_runtime_change(self) -> None:
        payload = build_final_summary(ROOT)

        self.assertIn(payload["gateDecision"], {"long_run_campaign_complete_with_live_rpc_blocker", "long_run_campaign_needs_fix"})
        self.assertFalse(payload["networkUsed"])
        self.assertFalse(payload["runtimeBehaviorChanged"])
        self.assertIn("Phase 3 capital-at-risk runtime implementation", payload["blocked"])

    def test_cli_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            phase3 = Path(tmp) / "phase3.json"
            summary = Path(tmp) / "summary.json"
            self.assertEqual(
                main(
                    [
                        "--root",
                        str(ROOT),
                        "--phase3-output",
                        str(phase3),
                        "--summary-output",
                        str(summary),
                        "--quiet",
                    ]
                ),
                0,
            )
            self.assertTrue(phase3.exists())
            payload = json.loads(summary.read_text(encoding="utf-8"))
            self.assertFalse(payload["stagingCommitPushPerformed"])


if __name__ == "__main__":
    unittest.main()
