from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tools.indexer_fixture_dry_run import run_fixture_dry_run


ROOT = Path(__file__).resolve().parents[1]


class IndexerFixtureDryRunTests(unittest.TestCase):
    def test_fixture_dry_run_loads_static_rows_into_sidecar_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = Path(tmp) / "fixture.json"
            db_path = Path(tmp) / "indexer.sqlite3"
            fixture_path.write_text(
                json.dumps(
                    {
                        "cursors": [
                            {
                                "source": "fixture",
                                "cursor_key": "markets",
                                "cursor_value": "done",
                                "updated_at": "2026-05-21T10:00:00+00:00",
                            }
                        ],
                        "markets": [
                            {
                                "conditionId": "cond-a",
                                "slug": "market-a",
                                "eventSlug": "event-a",
                                "question": "Fixture?",
                                "active": True,
                                "closed": False,
                            }
                        ],
                        "trades": [
                            {
                                "source": "activity",
                                "transactionHash": "0xtx",
                                "conditionId": "cond-a",
                                "asset": "yes-token",
                                "proxyWallet": "0xabc",
                                "side": "BUY",
                                "outcome": "Yes",
                                "size": "10",
                                "price": "0.5",
                                "usdcSize": "5.2",
                                "timestamp": "1770000000",
                            }
                        ],
                        "orderbooks": [
                            {
                                "token_id": "yes-token",
                                "condition_id": "cond-a",
                                "timestamp": "2026-05-21T10:00:00+00:00",
                                "bids": [["0.49", "10"]],
                                "asks": [["0.51", "12"]],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            summary = run_fixture_dry_run(fixture_path, db_path)

            with closing(sqlite3.connect(db_path)) as conn:
                trade_source = conn.execute("SELECT source FROM indexed_trades").fetchone()[0]

        self.assertFalse(summary["networkUsed"])
        self.assertFalse(summary["productionIntegration"])
        self.assertEqual(summary["tableCounts"]["indexer_cursors"], 1)
        self.assertEqual(summary["tableCounts"]["indexed_markets"], 1)
        self.assertEqual(summary["tableCounts"]["indexed_trades"], 1)
        self.assertEqual(summary["tableCounts"]["orderbook_snapshots"], 1)
        self.assertEqual(trade_source, "activity")

    def test_fixture_dry_run_can_replay_twice_without_duplicate_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = Path(tmp) / "fixture.json"
            db_path = Path(tmp) / "indexer.sqlite3"
            summary_path = Path(tmp) / "summary.json"
            fixture_path.write_text(
                json.dumps(
                    {
                        "cursors": [
                            {
                                "source": "fixture",
                                "cursor_key": "markets",
                                "cursor_value": "done",
                                "updated_at": "2026-05-21T10:00:00+00:00",
                            }
                        ],
                        "markets": [
                            {
                                "conditionId": "cond-a",
                                "slug": "market-a",
                                "eventSlug": "event-a",
                                "question": "Fixture?",
                                "active": True,
                                "closed": False,
                                "unexpected": {"marketRaw": True},
                            }
                        ],
                        "trades": [
                            {
                                "source": "activity",
                                "transactionHash": "0xtx",
                                "conditionId": "cond-a",
                                "asset": "yes-token",
                                "proxyWallet": "0xabc",
                                "side": "BUY",
                                "outcome": "Yes",
                                "size": "10",
                                "price": "0.5",
                                "usdcSize": "5.2",
                                "timestamp": "1770000000",
                                "unexpected": {"tradeRaw": True},
                            }
                        ],
                        "orderbooks": [
                            {
                                "token_id": "yes-token",
                                "condition_id": "cond-a",
                                "timestamp": "2026-05-21T10:00:00+00:00",
                                "bids": [["0.49", "10"]],
                                "asks": [["0.51", "12"]],
                                "unexpected": {"bookRaw": True},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            run_fixture_dry_run(fixture_path, db_path)
            summary = run_fixture_dry_run(fixture_path, db_path, summary_json_path=summary_path)

            with closing(sqlite3.connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                market_raw = json.loads(
                    conn.execute("SELECT raw_json FROM indexed_markets WHERE condition_id = ?", ("cond-a",)).fetchone()[
                        "raw_json"
                    ]
                )
                trade_raw = json.loads(conn.execute("SELECT raw_json FROM indexed_trades").fetchone()["raw_json"])
                book_raw = json.loads(conn.execute("SELECT raw_json FROM orderbook_snapshots").fetchone()["raw_json"])
                cursor = conn.execute(
                    "SELECT cursor_value, status FROM indexer_cursors WHERE source = ? AND cursor_key = ?",
                    ("fixture", "markets"),
                ).fetchone()
            written_summary = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertEqual(summary["tableCounts"]["indexer_cursors"], 1)
        self.assertEqual(summary["tableCounts"]["indexed_markets"], 1)
        self.assertEqual(summary["tableCounts"]["indexed_trades"], 1)
        self.assertEqual(summary["tableCounts"]["orderbook_snapshots"], 1)
        self.assertEqual(summary["cursorHealth"][0]["status"], "ok")
        self.assertEqual(cursor["cursor_value"], "done")
        self.assertEqual(cursor["status"], "ok")
        self.assertEqual(market_raw["unexpected"], {"marketRaw": True})
        self.assertEqual(trade_raw["unexpected"], {"tradeRaw": True})
        self.assertEqual(book_raw["unexpected"], {"bookRaw": True})
        self.assertEqual(written_summary["tableCounts"], summary["tableCounts"])

    def test_fixture_dry_run_does_not_use_network_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = Path(tmp) / "fixture.json"
            db_path = Path(tmp) / "indexer.sqlite3"
            fixture_path.write_text(
                json.dumps(
                    {
                        "markets": [{"conditionId": "cond-a", "slug": "market-a"}],
                        "trades": [{"transactionHash": "0xtx", "size": "1"}],
                    }
                ),
                encoding="utf-8",
            )

            with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
                with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                    summary = run_fixture_dry_run(fixture_path, db_path)

        self.assertFalse(summary["networkUsed"])
        self.assertFalse(summary["productionIntegration"])

    def test_fixture_dry_run_rejects_non_object_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = Path(tmp) / "fixture.json"
            fixture_path.write_text("[]", encoding="utf-8")

            with self.assertRaises(ValueError):
                run_fixture_dry_run(fixture_path, Path(tmp) / "indexer.sqlite3")


class IndexerFixtureDryRunIsolationTests(unittest.TestCase):
    def test_dry_run_tool_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
            "app/browser_desktop.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("indexer_fixture_dry_run", source)


if __name__ == "__main__":
    unittest.main()
