from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.indexer import IndexerStorage, OrderbookSnapshot
from tools.audit_microstructure_context import audit_microstructure_db


ROOT = Path(__file__).resolve().parents[1]


class MicrostructureArtifactAuditTests(unittest.TestCase):
    def test_audit_reads_sidecar_db_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            storage = IndexerStorage(db_path)
            storage.init()
            storage.insert_orderbook_snapshot(
                OrderbookSnapshot(
                    token_id="yes-a",
                    condition_id="cond-a",
                    timestamp="2026-05-21T10:00:00+00:00",
                    spread_bps="100",
                    bid_depth="1000",
                    ask_depth="1000",
                    liquidity_imbalance="0",
                )
            )
            storage.insert_orderbook_snapshot(
                OrderbookSnapshot(
                    token_id="yes-a",
                    condition_id="cond-a",
                    timestamp="2026-05-21T10:01:00+00:00",
                    spread_bps="500",
                    bid_depth="200",
                    ask_depth="200",
                    liquidity_imbalance="0.55",
                )
            )

            summary = audit_microstructure_db(db_path, token_id="yes-a")

        self.assertEqual(summary["snapshotCount"], 2)
        self.assertEqual(summary["context"]["status"], "available")
        self.assertFalse(summary["networkUsed"])
        self.assertFalse(summary["productionIntegration"])

    def test_audit_writes_optional_output_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            out = Path(tmp) / "out"
            storage = IndexerStorage(db_path)
            storage.init()
            storage.insert_orderbook_snapshot(
                OrderbookSnapshot(
                    token_id="yes-a",
                    condition_id="cond-a",
                    timestamp="2026-05-21T10:00:00+00:00",
                    spread_bps="100",
                    bid_depth="1000",
                    ask_depth="1000",
                )
            )

            summary = audit_microstructure_db(db_path, output_dir=out)
            written = json.loads(Path(summary["outputPath"]).read_text(encoding="utf-8"))

        self.assertEqual(written["snapshotCount"], 1)

    def test_audit_does_not_use_network_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "indexer.sqlite3"
            IndexerStorage(db_path).init()
            with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
                with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                    summary = audit_microstructure_db(db_path)

        self.assertFalse(summary["networkUsed"])

    def test_audit_tool_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("audit_microstructure_context", source)


if __name__ == "__main__":
    unittest.main()
