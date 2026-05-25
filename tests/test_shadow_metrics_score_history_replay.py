from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.indexer import IndexerStorage
from tools.replay_shadow_metrics_to_score_history import replay_shadow_metrics_fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "shadow_metrics" / "low_probability_large_buy.json"


class ShadowMetricsScoreHistoryReplayTests(unittest.TestCase):
    def test_replay_writes_shadow_metrics_to_append_only_score_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            summary = replay_shadow_metrics_fixture(
                FIXTURE,
                db_path,
                computed_at="2026-05-21T10:00:00+00:00",
            )
            storage = IndexerStorage(db_path)
            rows = storage.list_score_history(subject_type="wallet", subject_id="wallet-low-odds")

        self.assertEqual(summary["rowsInserted"], 8)
        self.assertTrue(summary["appendOnlyReplay"])
        self.assertFalse(summary["networkUsed"])
        self.assertFalse(summary["productionIntegration"])
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(str(row["score_type"]).startswith("shadow_") for row in rows))

    def test_repeated_replay_appends_history_with_same_input_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            first = replay_shadow_metrics_fixture(FIXTURE, db_path, computed_at="2026-05-21T10:00:00+00:00")
            second = replay_shadow_metrics_fixture(FIXTURE, db_path, computed_at="2026-05-21T11:00:00+00:00")
            storage = IndexerStorage(db_path)
            rows = storage.list_score_history(subject_type="wallet", subject_id="wallet-low-odds")

        self.assertEqual(first["inputHash"], second["inputHash"])
        self.assertEqual(len(rows), 16)

    def test_replay_does_not_use_network_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
                with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                    summary = replay_shadow_metrics_fixture(FIXTURE, Path(tmp) / "indexer.sqlite3")

        self.assertFalse(summary["networkUsed"])

    def test_replay_tool_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("replay_shadow_metrics_to_score_history", source)


if __name__ == "__main__":
    unittest.main()
