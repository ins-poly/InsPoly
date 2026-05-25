from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.event_forensic_replay import (
    REPLAY_SNAPSHOT_REPORT_TYPE,
    build_replay_snapshot,
    find_forbidden_snapshot_key_paths,
    write_replay_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]


def _base_report(*, analysis_scope: str = "event") -> dict[str, object]:
    return {
        "analysis_version": "fixture-v1",
        "generated_at": "2026-05-25T00:00:00+00:00",
        "status": "completed",
        "analysis_scope": analysis_scope,
        "analysis_settings": {
            "analysis_scope": analysis_scope,
            "min_notional": "250.00",
            "include_related_markets": True,
            "include_blockchain": False,
            "funding_trace_mode": "disabled",
            "start_at": "",
            "end_at": "",
        },
        "event": {
            "id": "event-id",
            "slug": "event-slug",
            "title": "Event title",
            "canonicalUrl": "https://polymarket.com/event/event-slug",
            "marketCount": 2,
            "analysisMarketCount": 2,
            "resolutionStatus": "resolved",
            "outcomeContextAvailable": True,
        },
        "summary": {
            "raw_trade_count": 10,
            "candidate_trade_count": 2,
            "normal_candidate_trade_count": 2,
            "analysis_market_count": 2,
            "total_event_market_count": 2,
        },
        "performance": {
            "collect_event_trades_seconds": 1.25,
            "prefetch_wallet_context_seconds": 2.5,
            "score_candidates_seconds": 0.75,
            "total_seconds": 5.0,
        },
        "markets": [
            {
                "conditionId": "cond-1",
                "question": "Market 1?",
                "winningOutcome": "YES",
                "resolutionStatus": "resolved",
            }
        ],
        "display_trades": [
            {
                "tradeId": "trade-1",
                "wallet": "0xabc",
                "conditionId": "cond-1",
                "timestamp": "2026-05-01T00:00:00+00:00",
                "market": "Market 1?",
                "rawOrderSide": "BUY",
                "rawTokenOutcome": "YES",
                "economicSide": "YES",
                "eventForensicScore": 42,
                "existingModelScore": 17,
                "laterWon": True,
                "winnerRank": 1,
            }
        ],
    }


class EventForensicReplaySnapshotTests(unittest.TestCase):
    def test_snapshot_schema_preserves_whole_event_scope_and_candidate_ids(self) -> None:
        snapshot = build_replay_snapshot(
            _base_report(analysis_scope="event"),
            replay_stage="+1h",
            generated_at="2026-05-25T00:00:00+00:00",
        )

        self.assertEqual(snapshot["reportType"], REPLAY_SNAPSHOT_REPORT_TYPE)
        self.assertEqual(snapshot["replayStage"], "+1h")
        self.assertEqual(snapshot["scope"]["analysisScope"], "whole_event")
        self.assertEqual(snapshot["candidateCounts"]["candidateTradeSetIds"], ["trade-1"])
        self.assertEqual(snapshot["timing"]["score_candidates_seconds"], 0.75)
        self.assertTrue(snapshot["winnerResolutionMetadata"]["winnerMetadataAvailable"])
        self.assertFalse(snapshot["networkUsed"])
        self.assertFalse(snapshot["runtimeBehaviorChanged"])
        self.assertFalse(snapshot["containsRestrictedFields"])

    def test_snapshot_preserves_selected_market_scope_from_legacy_report(self) -> None:
        report = _base_report(analysis_scope="market")
        report["selected_condition_id"] = "cond-1"
        report["selected_market_slug"] = "market-1"
        report["selected_market_title"] = "Market 1?"

        snapshot = build_replay_snapshot(report, generated_at="2026-05-25T00:00:00+00:00")

        self.assertEqual(snapshot["scope"]["analysisScope"], "selected_market")
        self.assertEqual(snapshot["market"]["selectedConditionId"], "cond-1")
        self.assertEqual(snapshot["market"]["selectedMarketSlug"], "market-1")
        self.assertIn("product_scope_missing_or_inferred_from_legacy_fields", snapshot["qualityNotes"])

    def test_old_report_without_candidates_falls_back_safely(self) -> None:
        report = {
            "analysis_scope": "event",
            "event": {"slug": "old-event", "title": "Old event"},
            "summary": {},
            "performance": {},
        }

        snapshot = build_replay_snapshot(report, generated_at="2026-05-25T00:00:00+00:00")

        self.assertEqual(snapshot["candidateCounts"]["candidateRowsInSnapshot"], 0)
        self.assertIn("no_candidate_rows_available_in_source_report", snapshot["qualityNotes"])
        self.assertIn("timing_fields_missing", snapshot["qualityNotes"])

    def test_explicit_candidate_rows_override_display_rows(self) -> None:
        report = _base_report()
        snapshot = build_replay_snapshot(
            report,
            candidate_rows=[
                {"tradeId": "audit-1", "wallet": "0x1", "conditionId": "cond-1"},
                {"tradeId": "audit-2", "wallet": "0x2", "conditionId": "cond-2"},
            ],
            generated_at="2026-05-25T00:00:00+00:00",
        )

        self.assertEqual(snapshot["candidateCounts"]["candidateTradeSetIds"], ["audit-1", "audit-2"])

    def test_forbidden_secret_key_detector_does_not_flag_market_token_fields(self) -> None:
        snapshot = build_replay_snapshot(_base_report(), generated_at="2026-05-25T00:00:00+00:00")
        self.assertEqual(find_forbidden_snapshot_key_paths(snapshot), [])
        self.assertEqual(find_forbidden_snapshot_key_paths({"api_key": "secret"}), ["api_key"])

    def test_snapshot_write_round_trip(self) -> None:
        snapshot = build_replay_snapshot(_base_report(), generated_at="2026-05-25T00:00:00+00:00")
        with tempfile.TemporaryDirectory() as tmp:
            output = write_replay_snapshot(snapshot, Path(tmp) / "snapshot.json")
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["reportType"], REPLAY_SNAPSHOT_REPORT_TYPE)
        self.assertEqual(payload["candidateCounts"]["candidateRowsInSnapshot"], 1)

    def test_replay_helper_has_no_network_imports(self) -> None:
        source = (ROOT / "app/event_forensic_replay.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("http.client", source)
        self.assertNotIn("socket", source)


if __name__ == "__main__":
    unittest.main()
