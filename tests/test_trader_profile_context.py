from __future__ import annotations

from pathlib import Path
import unittest

from app.trader_profile_context import build_trader_profile_context


ROOT = Path(__file__).resolve().parents[1]


class TraderProfileContextTests(unittest.TestCase):
    def test_profile_summarizes_positions_pnl_and_advisory_metrics(self) -> None:
        profile = build_trader_profile_context(
            wallet="wallet-a",
            positions=[
                {"remaining_shares": "75", "total_pnl": "12.5"},
                {"remaining_shares": "0", "total_pnl": "3"},
            ],
            shadow_metrics=[
                {
                    "name": "shadow_low_odds_position_size",
                    "status": "available",
                    "advisoryLevel": "context",
                }
            ],
            trade_count=4,
        )

        self.assertEqual(profile.wallet, "wallet-a")
        self.assertEqual(profile.position_count, 2)
        self.assertEqual(profile.open_position_count, 1)
        self.assertEqual(profile.total_remaining_shares, "75")
        self.assertEqual(profile.total_pnl, "15.5")
        self.assertEqual(profile.pnl_status, "known")
        self.assertEqual(profile.advisory_metrics, ("shadow_low_odds_position_size",))
        self.assertFalse(profile.production_integration)

    def test_missing_current_price_keeps_pnl_unknown(self) -> None:
        profile = build_trader_profile_context(
            wallet="wallet-a",
            positions=[{"remaining_shares": "100", "total_pnl": None}],
        )

        self.assertEqual(profile.pnl_status, "unknown")
        self.assertIsNone(profile.total_pnl)
        self.assertIn("pnl_unknown_when_any_position_missing_total_pnl", profile.caution_notes)

    def test_high_volume_public_user_caution_is_context_only(self) -> None:
        profile = build_trader_profile_context(
            wallet="wallet-a",
            positions=[],
            high_volume_public_user=True,
        )

        self.assertIn("high_volume_public_user_context", profile.caution_notes)
        self.assertNotIn("risk", profile.to_dict())

    def test_trader_profile_helper_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("trader_profile_context", source)


if __name__ == "__main__":
    unittest.main()
