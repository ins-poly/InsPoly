from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tools.indexer_bounded_live_sidecar_run import (
    GATE_BLOCKED_MISSING_TARGET,
    GATE_BLOCKED_NO_SAFE_PATH,
    GATE_BLOCKED_PROVIDER,
    GATE_SUCCESS_HARDENING,
    run_bounded_live_sidecar,
)


ROOT = Path(__file__).resolve().parents[1]


class IndexerBoundedLiveSidecarRunTests(unittest.TestCase):
    def test_missing_target_stops_before_network_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp, targets={"marketSlugs": []})
            client = Mock()

            report = run_bounded_live_sidecar(config_path, allow_live_network=True, client=client)

        self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED_MISSING_TARGET)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["liveIngestionStarted"])
        client.fetch_market_by_slug.assert_not_called()
        client.fetch_event_by_slug.assert_not_called()

    def test_live_network_flag_is_required_after_valid_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp)
            client = Mock()

            report = run_bounded_live_sidecar(config_path, allow_live_network=False, client=client)

        self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED_NO_SAFE_PATH)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["liveIngestionStarted"])
        client.fetch_market_by_slug.assert_not_called()

    def test_mocked_market_run_writes_expected_sidecar_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp)
            audit_path = Path(tmp) / "audit.json"
            client = Mock()
            client.fetch_market_by_slug.return_value = _market_payload()

            report = run_bounded_live_sidecar(
                config_path,
                db_audit_json=audit_path,
                allow_live_network=True,
                client=client,
                trade_fetcher=lambda _params: [_trade_payload()],
            )

            self.assertEqual(report["summary"]["gateDecision"], GATE_SUCCESS_HARDENING)
            self.assertTrue(report["networkUsed"])
            self.assertTrue(report["liveIngestionStarted"])
            self.assertTrue(report["output"]["dbCreated"])
            self.assertEqual(report["summary"]["tableCounts"]["indexed_markets"], 1)
            self.assertEqual(report["summary"]["tableCounts"]["indexed_trades"], 1)
            self.assertEqual(report["summary"]["tableCounts"]["indexer_cursors"], 2)
            self.assertEqual(report["summary"]["readinessGate"], "indexer_sidecar_readiness_ready_no_runtime")
            self.assertTrue(audit_path.exists())

    def test_row_cap_stops_trade_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp, limits={"maxMarkets": 1, "maxPages": 2, "maxRows": 2, "timeoutSeconds": 120})
            client = Mock()
            client.fetch_market_by_slug.return_value = _market_payload()

            report = run_bounded_live_sidecar(
                config_path,
                allow_live_network=True,
                client=client,
                trade_fetcher=lambda _params: [_trade_payload("0xtx1"), _trade_payload("0xtx2")],
            )

        self.assertEqual(report["summary"]["tableCounts"]["indexed_markets"], 1)
        self.assertEqual(report["summary"]["tableCounts"]["indexed_trades"], 1)
        self.assertIn("Public trade rows capped at 1.", report["warnings"])

    def test_provider_failure_is_captured_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp)
            client = Mock()
            client.fetch_market_by_slug.side_effect = RuntimeError("provider down")

            report = run_bounded_live_sidecar(config_path, allow_live_network=True, client=client)

        self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED_PROVIDER)
        self.assertTrue(report["networkUsed"])
        self.assertTrue(report["failures"])

    def test_slug_not_found_blocks_without_creating_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(tmp)
            client = Mock()
            client.fetch_market_by_slug.return_value = None

            report = run_bounded_live_sidecar(config_path, allow_live_network=True, client=client)

        self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED_PROVIDER)
        self.assertFalse(report["output"]["dbCreated"])
        self.assertTrue(report["failures"])

    def test_multiple_market_targets_write_expected_sidecar_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(
                tmp,
                targets={"marketSlugs": ["market-a", "market-b", "market-c"]},
                limits={"maxMarkets": 3, "maxPages": 1, "maxRows": 20, "timeoutSeconds": 120},
            )
            client = Mock()
            client.fetch_market_by_slug.side_effect = [
                _market_payload("cond-a", "market-a"),
                _market_payload("cond-b", "market-b"),
                _market_payload("cond-c", "market-c"),
            ]

            report = run_bounded_live_sidecar(
                config_path,
                allow_live_network=True,
                client=client,
                trade_fetcher=lambda _params: [
                    _trade_payload("0xtx-a", "cond-a"),
                    _trade_payload("0xtx-b", "cond-b"),
                    _trade_payload("0xtx-c", "cond-c"),
                ],
            )

        self.assertEqual(report["summary"]["gateDecision"], GATE_SUCCESS_HARDENING)
        self.assertEqual(client.fetch_market_by_slug.call_count, 3)
        self.assertEqual(report["summary"]["tableCounts"]["indexed_markets"], 3)
        self.assertEqual(report["summary"]["tableCounts"]["indexed_trades"], 3)
        self.assertEqual(report["summary"]["targetsAttempted"], 3)
        self.assertEqual(report["summary"]["targetsCompleted"], 3)
        self.assertEqual(report["summary"]["targetsFailed"], 0)
        self.assertEqual([item["tradeRows"] for item in report["summary"]["targetResults"]], [1, 1, 1])

    def test_target_count_above_max_markets_stops_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(
                tmp,
                targets={"marketSlugs": ["market-a", "market-b", "market-c"]},
                limits={"maxMarkets": 2, "maxPages": 1, "maxRows": 20, "timeoutSeconds": 120},
            )
            client = Mock()

            report = run_bounded_live_sidecar(config_path, allow_live_network=True, client=client)

        self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED_NO_SAFE_PATH)
        self.assertFalse(report["networkUsed"])
        client.fetch_market_by_slug.assert_not_called()

    def test_partial_target_provider_failure_is_captured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_config(
                tmp,
                targets={"marketSlugs": ["market-a", "market-b", "market-c"]},
                limits={"maxMarkets": 3, "maxPages": 1, "maxRows": 20, "timeoutSeconds": 120},
            )
            client = Mock()
            client.fetch_market_by_slug.side_effect = [
                _market_payload("cond-a", "market-a"),
                None,
                _market_payload("cond-c", "market-c"),
            ]

            report = run_bounded_live_sidecar(
                config_path,
                allow_live_network=True,
                client=client,
                trade_fetcher=lambda _params: [
                    _trade_payload("0xtx-a", "cond-a"),
                    _trade_payload("0xtx-c", "cond-c"),
                ],
            )

        self.assertEqual(report["summary"]["gateDecision"], GATE_SUCCESS_HARDENING)
        self.assertEqual(report["summary"]["tableCounts"]["indexed_markets"], 2)
        self.assertEqual(report["summary"]["tableCounts"]["indexed_trades"], 2)
        self.assertEqual(report["summary"]["targetsCompleted"], 2)
        self.assertEqual(report["summary"]["targetsFailed"], 1)
        self.assertEqual([item["status"] for item in report["summary"]["targetResults"]], ["completed", "failed", "completed"])
        self.assertTrue(report["failures"])

    def test_runner_is_not_imported_by_production_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
            "app/browser_desktop.py",
            "app/browser_ui.html",
            "app/browser_event_forensic_ui.html",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("indexer_bounded_live_sidecar_run", source)


def _write_config(
    tmp: str,
    *,
    targets: dict[str, list[str]] | None = None,
    limits: dict[str, int] | None = None,
) -> Path:
    config = {
        "dryRun": True,
        "requiresOperatorApproval": True,
        "networkExecution": False,
        "productionIntegration": False,
        "autoStart": False,
        "backgroundWorker": False,
        "warehouseMode": False,
        "mutateSavedArtifacts": False,
        "allowedDataTypes": ["markets", "public_trades", "orderbook_snapshots", "cursors", "health_rows"],
        "targets": targets if targets is not None else {"marketSlugs": ["market-a"]},
        "limits": limits if limits is not None else {"maxMarkets": 1, "maxPages": 1, "maxRows": 20, "timeoutSeconds": 120},
        "output": {"sqlitePath": str(Path(tmp) / ".inspoly_indexer" / "indexer.sqlite3")},
    }
    config_path = Path(tmp) / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def _market_payload(condition_id: str = "cond-a", slug: str = "market-a") -> dict[str, object]:
    return {
        "conditionId": condition_id,
        "slug": slug,
        "eventSlug": "event-a",
        "question": "Fixture?",
        "active": True,
        "closed": False,
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["yes-token", "no-token"]',
    }


def _trade_payload(transaction_hash: str = "0xtx", condition_id: str = "cond-a") -> dict[str, object]:
    return {
        "transactionHash": transaction_hash,
        "conditionId": condition_id,
        "asset": "yes-token",
        "proxyWallet": "0xABCDEF",
        "side": "BUY",
        "outcome": "Yes",
        "size": "10",
        "price": "0.5",
        "timestamp": "1770000000",
    }


if __name__ == "__main__":
    unittest.main()
