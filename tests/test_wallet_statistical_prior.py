from __future__ import annotations

import unittest

from app.wallet_analytics import ClosedPositionSummary, compute_wallet_statistical_prior


def _summary(
    *,
    total: int,
    wins: int,
    losses: int,
    economic_sample_size: int | None = None,
    economic_win_rate_value: float | None = None,
    zombie_loss_count: int = 0,
    formal_overstated: bool = False,
) -> ClosedPositionSummary:
    sample = economic_sample_size if economic_sample_size is not None else total
    economic_rate = (
        economic_win_rate_value
        if economic_win_rate_value is not None
        else (wins / sample * 100.0 if sample else 0.0)
    )
    return ClosedPositionSummary(
        total=total,
        wins=wins,
        losses=losses,
        win_rate_value=(wins / total * 100.0 if total else 0.0),
        win_rate_threshold=50.0,
        win_rate_clears_threshold=False,
        total_realized_pnl=0.0,
        average_return=0.0,
        economic_sample_size=sample,
        economic_win_rate_value=economic_rate,
        economic_win_rate_threshold=50.0,
        economic_win_rate_clears_threshold=False,
        zombie_loss_count=zombie_loss_count,
        zombie_loss_notional=0.0,
        redemption_avoidance_ratio=0.0,
        de_facto_loss_count=zombie_loss_count,
        formal_win_rate_may_be_overstated=formal_overstated,
    )


class WalletStatisticalPriorTests(unittest.TestCase):
    def test_small_sample_is_not_a_statistical_prior(self) -> None:
        prior = compute_wallet_statistical_prior(_summary(total=4, wins=4, losses=0))

        self.assertEqual(prior.label, "insufficient_sample")
        self.assertNotIn(prior.label, {"meaningful_statistical_prior", "strong_statistical_prior"})
        self.assertEqual(prior.resolved_sample_size, 4)
        self.assertEqual(prior.log_score, 0.0)

    def test_high_win_rate_with_meaningful_sample_gets_prior_label(self) -> None:
        prior = compute_wallet_statistical_prior(_summary(total=10, wins=10, losses=0))

        self.assertEqual(prior.label, "meaningful_statistical_prior")
        self.assertLess(prior.p_value, 0.001)
        self.assertGreater(prior.log_score, 3.0)

    def test_extreme_resolved_record_gets_strong_prior_label(self) -> None:
        prior = compute_wallet_statistical_prior(_summary(total=14, wins=14, losses=0))

        self.assertEqual(prior.label, "strong_statistical_prior")
        self.assertLess(prior.p_value, 0.0001)

    def test_zombie_distortion_uses_economic_sample_size(self) -> None:
        prior = compute_wallet_statistical_prior(
            _summary(
                total=8,
                wins=8,
                losses=0,
                economic_sample_size=12,
                economic_win_rate_value=66.7,
                zombie_loss_count=4,
                formal_overstated=True,
            )
        )

        self.assertEqual(prior.resolved_sample_size, 12)
        self.assertEqual(prior.label, "no_statistical_prior")
        self.assertGreater(prior.p_value, 0.01)

    def test_zombie_heavy_formal_wins_do_not_create_prior_label(self) -> None:
        prior = compute_wallet_statistical_prior(
            _summary(
                total=20,
                wins=20,
                losses=0,
                economic_sample_size=40,
                economic_win_rate_value=50.0,
                zombie_loss_count=20,
                formal_overstated=True,
            )
        )

        self.assertEqual(prior.resolved_sample_size, 40)
        self.assertEqual(prior.resolved_win_rate_value, 50.0)
        self.assertEqual(prior.label, "no_statistical_prior")
        self.assertNotIn(prior.label, {"meaningful_statistical_prior", "strong_statistical_prior"})

    def test_raw_metric_payload_uses_expected_keys(self) -> None:
        metrics = compute_wallet_statistical_prior(_summary(total=10, wins=10, losses=0)).to_raw_metrics()

        self.assertEqual(metrics["wallet_resolved_sample_size"], "10")
        self.assertEqual(metrics["wallet_resolved_win_rate"], "100.0%")
        self.assertEqual(metrics["wallet_statistical_prior_label"], "meaningful_statistical_prior")
        self.assertIn("wallet_statistical_prior_note", metrics)


if __name__ == "__main__":
    unittest.main()
