from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.indexer_bounded_live_config_validator import (
    GATE_BLOCKED,
    GATE_VALID,
    main,
    validate_bounded_live_config,
)


ROOT = Path(__file__).resolve().parents[1]


class IndexerBoundedLiveConfigValidatorTests(unittest.TestCase):
    def test_valid_sidecar_config_is_operator_review_ready(self) -> None:
        report = validate_bounded_live_config(_valid_config())

        self.assertEqual(report["summary"]["gateDecision"], GATE_VALID)
        self.assertEqual(report["summary"]["errorCount"], 0)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertFalse(report["liveIngestionStarted"])
        self.assertEqual(report["normalized"]["targetCount"], 2)

    def test_dry_run_is_required_until_operator_approval(self) -> None:
        config = _valid_config()
        config["dryRun"] = False

        report = validate_bounded_live_config(config)

        self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED)
        self.assertIn("dry_run", _error_names(report))

    def test_hard_caps_block_unbounded_configs(self) -> None:
        config = _valid_config()
        config["limits"]["maxRows"] = 50001

        report = validate_bounded_live_config(config)

        self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED)
        self.assertIn("limits.maxRows", _error_names(report))

    def test_per_target_public_trade_cap_must_fit_aggregate_budget(self) -> None:
        config = _valid_config()
        config["targets"] = {"marketSlugs": ["market-a", "market-b", "market-c"]}
        config["limits"] = {
            "maxMarkets": 3,
            "maxPages": 2,
            "maxRows": 100,
            "timeoutSeconds": 120,
            "maxPublicTradesPerTarget": 40,
        }

        report = validate_bounded_live_config(config)

        self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED)
        self.assertIn("limits.maxPublicTradesPerTarget", _error_names(report))

    def test_valid_per_target_public_trade_cap_is_recorded(self) -> None:
        config = _valid_config()
        config["targets"] = {"marketSlugs": ["market-a", "market-b", "market-c"]}
        config["limits"] = {
            "maxMarkets": 3,
            "maxPages": 2,
            "maxRows": 183,
            "timeoutSeconds": 120,
            "maxPublicTradesPerTarget": 60,
        }

        report = validate_bounded_live_config(config)

        self.assertEqual(report["summary"]["gateDecision"], GATE_VALID)
        self.assertEqual(report["normalized"]["maxPublicTradesPerTarget"], 60)

    def test_old_single_target_config_remains_valid_without_per_target_cap(self) -> None:
        config = _valid_config()
        config["targets"] = {"marketSlugs": ["market-a"]}
        config["limits"] = {
            "maxMarkets": 1,
            "maxPages": 1,
            "maxRows": 20,
            "timeoutSeconds": 120,
        }

        report = validate_bounded_live_config(config)

        self.assertEqual(report["summary"]["gateDecision"], GATE_VALID)
        self.assertIsNone(report["normalized"]["maxPublicTradesPerTarget"])

    def test_auth_or_trading_fields_are_forbidden_even_when_nested(self) -> None:
        config = _valid_config()
        config["clob"] = {"apiKey": "secret", "placeOrder": False}

        report = validate_bounded_live_config(config)

        self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED)
        self.assertIn("forbidden_keys", _error_names(report))

    def test_output_path_must_be_local_sqlite_sidecar_path(self) -> None:
        config = _valid_config()
        config["output"] = {"sqlitePath": "postgres://localhost/indexer"}

        report = validate_bounded_live_config(config)

        self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED)
        self.assertIn("output.sqlitePath", _error_names(report))

    def test_wildcard_targets_are_forbidden(self) -> None:
        config = _valid_config()
        config["targets"] = {"eventSlugs": ["all"]}

        report = validate_bounded_live_config(config)

        self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED)
        self.assertIn("targets", _error_names(report))

    def test_cli_writes_validation_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            output_path = Path(tmp) / "validation.json"
            config_path.write_text(json.dumps(_valid_config()), encoding="utf-8")

            with redirect_stdout(StringIO()):
                exit_code = main(["--config-json", str(config_path), "--output-json", str(output_path)])

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["reportType"], "indexer_bounded_live_config_validation")
        self.assertEqual(payload["summary"]["gateDecision"], GATE_VALID)

    def test_validator_does_not_use_network_calls(self) -> None:
        with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
            with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                report = validate_bounded_live_config(_valid_config())

        self.assertFalse(report["networkUsed"])

    def test_validator_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
            "app/browser_desktop.py",
            "app/browser_event_forensic_ui.html",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("indexer_bounded_live_config_validator", source)


def _valid_config() -> dict[str, object]:
    return {
        "dryRun": True,
        "requiresOperatorApproval": True,
        "networkExecution": False,
        "productionIntegration": False,
        "autoStart": False,
        "backgroundWorker": False,
        "warehouseMode": False,
        "mutateSavedArtifacts": False,
        "allowedDataTypes": ["markets", "public_trades", "orderbook_snapshots", "cursors", "health_rows"],
        "targets": {"marketSlugs": ["market-a", "market-b"]},
        "limits": {
            "maxMarkets": 2,
            "maxPages": 5,
            "maxRows": 1000,
            "timeoutSeconds": 120,
        },
        "output": {"sqlitePath": ".inspoly_indexer/operator_review/indexer.sqlite3"},
    }


def _error_names(report: dict[str, object]) -> set[str]:
    return {
        str(check["name"])
        for check in report.get("checks", [])
        if isinstance(check, dict) and check.get("status") == "error"
    }


if __name__ == "__main__":
    unittest.main()
