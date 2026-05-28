from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest

from app.indexer.alerts import (
    AdvisoryAlert,
    AlertSidecarStore,
    WatchlistEntry,
    advisory_alert_from_metric,
    evaluate_static_advisory_alerts,
    stable_alert_id,
)


ROOT = Path(__file__).resolve().parents[1]


class AlertSidecarStoreTests(unittest.TestCase):
    def test_stable_alert_identity_and_duplicate_suppression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AlertSidecarStore(Path(tmp) / "alerts.sqlite3")
            store.init()
            alert = AdvisoryAlert(
                alert_id=stable_alert_id("wallet", "wallet-a", "shadow_low_odds", "hash-a"),
                subject_type="wallet",
                subject_id="wallet-a",
                alert_type="shadow_low_odds",
                advisory_level="advisory_context",
                message="Repeated advisory context",
                created_at="2026-05-21T10:00:00+00:00",
                source_hash="hash-a",
                raw={"advisoryOnly": True},
            )

            first = store.upsert_alert(alert)
            second = store.upsert_alert(alert)
            alerts = store.list_alerts()

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["advisory_level"], "advisory_context")
        self.assertEqual(alerts[0]["raw"], {"advisoryOnly": True})

    def test_watchlist_entry_create_update_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AlertSidecarStore(Path(tmp) / "alerts.sqlite3")
            store.init()
            store.upsert_watchlist_entry(
                WatchlistEntry(
                    subject_type="wallet",
                    subject_id="wallet-a",
                    reason="manual analyst context",
                    updated_at="2026-05-21T10:00:00+00:00",
                )
            )
            store.upsert_watchlist_entry(
                WatchlistEntry(
                    subject_type="wallet",
                    subject_id="wallet-a",
                    reason="updated context",
                    updated_at="2026-05-21T11:00:00+00:00",
                )
            )
            before_delete = store.list_watchlist_entries()
            store.delete_watchlist_entry("wallet", "wallet-a")
            after_delete = store.list_watchlist_entries()

        self.assertEqual(len(before_delete), 1)
        self.assertEqual(before_delete[0]["reason"], "updated context")
        self.assertEqual(after_delete, ())

    def test_stale_alert_expiration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AlertSidecarStore(Path(tmp) / "alerts.sqlite3")
            store.init()
            store.upsert_alert(
                AdvisoryAlert(
                    alert_id="alert-old",
                    subject_type="wallet",
                    subject_id="wallet-a",
                    alert_type="shadow_low_odds",
                    advisory_level="advisory_context",
                    message="Old alert",
                    created_at="2026-05-21T10:00:00+00:00",
                    source_hash="hash-a",
                )
            )

            expired = store.expire_alerts(
                now=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
                max_age_seconds=3600,
            )
            alerts = store.list_alerts()

        self.assertEqual(expired, 1)
        self.assertEqual(alerts[0]["status"], "expired")

    def test_static_alert_evaluator_requires_repeated_advisory_context(self) -> None:
        metric = {
            "name": "shadow_low_odds_position_size",
            "status": "available",
            "advisoryLevel": "context",
            "value": "1200",
        }
        one_off = evaluate_static_advisory_alerts(
            subject_type="wallet",
            subject_id="wallet-a",
            shadow_metrics=[metric],
            score_history=[],
            source_hash="hash-a",
            created_at="2026-05-21T10:00:00+00:00",
        )
        repeated = evaluate_static_advisory_alerts(
            subject_type="wallet",
            subject_id="wallet-a",
            shadow_metrics=[metric],
            score_history=[{"score_type": "shadow_low_odds_position_size", "label": "shadow_context"}],
            source_hash="hash-a",
            created_at="2026-05-21T10:00:00+00:00",
        )

        self.assertEqual(one_off, ())
        self.assertEqual(len(repeated), 1)
        self.assertEqual(repeated[0].advisory_level, "advisory_context")

    def test_static_alert_evaluator_skips_unknown_quality_metrics(self) -> None:
        alerts = evaluate_static_advisory_alerts(
            subject_type="wallet",
            subject_id="wallet-a",
            shadow_metrics=[
                {
                    "name": "shadow_net_position_pnl",
                    "status": "unknown",
                    "advisoryLevel": "context",
                }
            ],
            score_history=[{"score_type": "shadow_net_position_pnl", "label": "shadow_context"}],
            source_hash="hash-a",
            created_at="2026-05-21T10:00:00+00:00",
        )

        self.assertEqual(alerts, ())

    def test_advisory_alert_from_metric_is_not_production_label(self) -> None:
        alert = advisory_alert_from_metric(
            subject_type="wallet",
            subject_id="wallet-a",
            metric={
                "name": "shadow_low_odds_position_size",
                "status": "available",
                "advisoryLevel": "context",
            },
            source_hash="hash-a",
            created_at="2026-05-21T10:00:00+00:00",
        )

        self.assertTrue(alert.advisory_level.startswith("advisory_"))
        self.assertNotIn("Strong Risk", alert.message)
        self.assertNotIn("Hard Evidence Review", alert.message)

    def test_alert_sidecar_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
            "app/browser_desktop.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("app.indexer.alerts", source)


if __name__ == "__main__":
    unittest.main()
