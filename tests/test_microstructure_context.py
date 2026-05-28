from __future__ import annotations

from pathlib import Path
import unittest

from app.microstructure_context import (
    STATUS_AVAILABLE,
    STATUS_NOT_TRIGGERED,
    STATUS_UNKNOWN,
    summarize_microstructure_snapshots,
)


ROOT = Path(__file__).resolve().parents[1]


class MicrostructureContextTests(unittest.TestCase):
    def test_spread_and_depth_shock_are_context_only(self) -> None:
        context = summarize_microstructure_snapshots(
            [
                {
                    "timestamp": "2026-05-21T10:00:00+00:00",
                    "spread_bps": "100",
                    "bid_depth": "1000",
                    "ask_depth": "1000",
                    "liquidity_imbalance": "0",
                },
                {
                    "timestamp": "2026-05-21T10:01:00+00:00",
                    "spread_bps": "500",
                    "bid_depth": "200",
                    "ask_depth": "200",
                    "liquidity_imbalance": "0.55",
                },
            ]
        )

        self.assertEqual(context.status, STATUS_AVAILABLE)
        self.assertTrue(context.liquidity_shock)
        self.assertEqual(context.spread_change_bps, "400")
        self.assertEqual(context.depth_change, "-1600")
        self.assertFalse(context.production_integration)

    def test_stable_snapshots_are_not_triggered(self) -> None:
        context = summarize_microstructure_snapshots(
            [
                {"timestamp": "1", "spread_bps": "100", "bid_depth": "1000", "ask_depth": "1000"},
                {"timestamp": "2", "spread_bps": "120", "bid_depth": "950", "ask_depth": "990"},
            ]
        )

        self.assertEqual(context.status, STATUS_NOT_TRIGGERED)
        self.assertFalse(context.liquidity_shock)

    def test_malformed_snapshots_are_unknown_with_quality_note(self) -> None:
        context = summarize_microstructure_snapshots([{"timestamp": "1", "spread_bps": "bad"}])

        self.assertEqual(context.status, STATUS_UNKNOWN)
        self.assertIn("malformed_snapshot_ignored", context.quality_notes)

    def test_microstructure_helper_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("microstructure_context", source)


if __name__ == "__main__":
    unittest.main()
