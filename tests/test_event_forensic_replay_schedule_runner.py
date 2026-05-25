from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.event_forensic_replay import build_replay_snapshot
from tools.event_forensic_replay_schedule_runner import build_replay_schedule_plan, main


ROOT = Path(__file__).resolve().parents[1]


def _snapshot(scope: str = "event") -> dict[str, object]:
    return build_replay_snapshot(
        {
            "generated_at": "2026-05-25T00:00:00+00:00",
            "analysis_scope": scope,
            "event": {"slug": "event-a", "title": "Event A", "marketCount": 2},
            "selected_market_slug": "market-a" if scope == "market" else "",
            "summary": {"candidate_trade_count": 1},
            "display_trades": [{"tradeId": "trade-a", "wallet": "0xabc"}],
            "performance": {"total_seconds": 1.0},
        },
        generated_at="2026-05-25T00:00:00+00:00",
    )


class EventForensicReplayScheduleRunnerTests(unittest.TestCase):
    def test_schedule_generates_expected_replay_stages(self) -> None:
        plan = build_replay_schedule_plan(_snapshot("event"), generated_at="2026-05-25T00:00:00+00:00")

        self.assertEqual([row["stage"] for row in plan["stages"]], ["initial", "+1h", "+4h", "+24h"])
        self.assertEqual(plan["sourceSnapshot"]["analysisScope"], "whole_event")
        self.assertFalse(plan["backgroundSchedulerStarted"])
        self.assertFalse(plan["networkUsed"])

    def test_selected_market_scope_is_preserved(self) -> None:
        plan = build_replay_schedule_plan(_snapshot("market"), generated_at="2026-05-25T00:00:00+00:00")

        self.assertEqual(plan["sourceSnapshot"]["analysisScope"], "selected_market")
        self.assertEqual(plan["sourceSnapshot"]["selectedMarketSlug"], "market-a")

    def test_cli_reads_snapshot_and_writes_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_path = root / "snapshot.json"
            snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
            output = root / "plan.json"

            self.assertEqual(main(["--snapshot", str(snapshot_path), "--output", str(output), "--quiet"]), 0)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["gateDecision"], "replay_schedule_sidecar_ready")
        self.assertFalse(payload["storageMutated"])

    def test_tool_source_has_no_network_or_scheduler_imports(self) -> None:
        source = (ROOT / "tools/event_forensic_replay_schedule_runner.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("http.client", source)
        self.assertNotIn("import sched", source)


if __name__ == "__main__":
    unittest.main()
