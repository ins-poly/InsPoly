from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.normalize_shadow_inputs_from_artifacts import (
    METRIC_ENTRY_EDGE,
    METRIC_LOW_ODDS,
    METRIC_MICROSTRUCTURE,
    METRIC_NET_PNL,
    METRIC_WIN_RATE,
    RECORD_CURRENT_PRICE,
    RECORD_LEDGER_TRADE,
    RECORD_TRADE_EXPOSURE,
    RECORD_WALLET_HISTORY,
    STATUS_AVAILABLE,
    STATUS_NOT_COMPUTED,
    STATUS_UNKNOWN,
    markdown_report,
    normalize_artifact,
    normalize_artifacts,
    supported_families,
    write_normalization_outputs,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shadow_input_normalization"
FORBIDDEN_TEXT = (
    "risk_level",
    "Strong Risk",
    "Hard Evidence Review",
    "HER",
    "candidateAdmission",
    "fundingEligibility",
    "eventForensicScore",
    "existingModelScore",
    "laterWon",
    "winnerRank",
    "sortKey",
)


def readiness(artifact, metric: str) -> dict[str, object]:
    payload = artifact.to_dict()
    for item in payload["metricReadiness"]:
        if item["metric"] == metric:
            return item
    raise AssertionError(f"missing metric readiness: {metric}")


class ShadowInputNormalizationTests(unittest.TestCase):
    def test_recent_scanner_normalizes_low_odds_only_with_derivation_notes(self) -> None:
        artifact = normalize_artifact(
            "recent_scanner_report_json",
            FIXTURES / "recent_scanner_report.json",
        )
        payload = artifact.to_dict()

        self.assertEqual(payload["recordCount"], 1)
        record = payload["normalizedRecords"][0]
        self.assertEqual(record["recordType"], RECORD_TRADE_EXPOSURE)
        self.assertEqual(record["targetMetrics"], [METRIC_LOW_ODDS])
        self.assertEqual(record["fields"]["cash_amount"], "120")
        self.assertIn("cash_amount_from_report_notional_derivable", record["qualityNotes"])
        self.assertEqual(readiness(artifact, METRIC_LOW_ODDS)["status"], STATUS_AVAILABLE)
        self.assertEqual(readiness(artifact, METRIC_NET_PNL)["status"], STATUS_NOT_COMPUTED)
        self.assert_no_forbidden_output(payload)

    def test_archive_json_normalizes_low_odds_and_wallet_history_records(self) -> None:
        artifact = normalize_artifact(
            "archive_report_json",
            FIXTURES / "archive_report.json",
        )
        payload = artifact.to_dict()
        record_types = {record["recordType"] for record in payload["normalizedRecords"]}

        self.assertIn(RECORD_TRADE_EXPOSURE, record_types)
        self.assertIn(RECORD_WALLET_HISTORY, record_types)
        wallet_record = next(record for record in payload["normalizedRecords"] if record["recordType"] == RECORD_WALLET_HISTORY)
        self.assertEqual(wallet_record["fields"]["resolved_trades"], 40)
        self.assertEqual(wallet_record["fields"]["winning_trades"], 26)
        self.assertEqual(readiness(artifact, METRIC_LOW_ODDS)["status"], STATUS_AVAILABLE)
        self.assertEqual(readiness(artifact, METRIC_WIN_RATE)["status"], STATUS_AVAILABLE)
        self.assertEqual(readiness(artifact, METRIC_MICROSTRUCTURE)["status"], STATUS_NOT_COMPUTED)
        self.assert_no_forbidden_output(payload)

    def test_event_forensic_json_skips_unsafe_fields_and_normalizes_exposure_only(self) -> None:
        artifact = normalize_artifact(
            "event_forensic_event_analysis_json",
            FIXTURES / "event_forensic_event_analysis.json",
        )
        payload = artifact.to_dict()

        self.assertEqual(payload["recordCount"], 1)
        self.assertGreater(payload["skippedUnsafeFieldCount"], 0)
        record = payload["normalizedRecords"][0]
        self.assertEqual(record["fields"]["cash_amount"], 1200)
        self.assertIn("cash_amount_from_position_size_derivable_not_shares", record["qualityNotes"])
        self.assertEqual(readiness(artifact, METRIC_LOW_ODDS)["status"], STATUS_AVAILABLE)
        self.assertEqual(readiness(artifact, METRIC_ENTRY_EDGE)["status"], STATUS_NOT_COMPUTED)
        self.assertEqual(readiness(artifact, METRIC_NET_PNL)["status"], STATUS_NOT_COMPUTED)
        self.assert_no_forbidden_output(payload)

    def test_event_forensic_json_can_use_price_present_suspicious_trades_fallback(self) -> None:
        artifact = normalize_artifact(
            "event_forensic_event_analysis_json",
            FIXTURES / "event_forensic_suspicious_trades_fallback.json",
        )
        payload = artifact.to_dict()

        self.assertEqual(payload["recordCount"], 1)
        record = payload["normalizedRecords"][0]
        self.assertEqual(record["fields"]["wallet"], "wallet-fallback")
        self.assertEqual(record["fields"]["price"], 0.1)
        self.assertIn("event_forensic_suspicious_trades_fallback_price_required", record["qualityNotes"])
        self.assertIn("event_forensic_suspicious_trades_fallback_used", payload["qualityNotes"])
        self.assertEqual(readiness(artifact, METRIC_LOW_ODDS)["status"], STATUS_AVAILABLE)
        self.assert_no_forbidden_output(payload)

    def test_event_forensic_json_without_safe_rows_marks_low_odds_unknown(self) -> None:
        artifact = normalize_artifact(
            "event_forensic_event_analysis_json",
            FIXTURES / "event_forensic_empty_event_analysis.json",
        )

        self.assertEqual(artifact.to_dict()["recordCount"], 0)
        self.assertEqual(readiness(artifact, METRIC_LOW_ODDS)["status"], STATUS_UNKNOWN)

    def test_reconstruction_report_dir_normalizes_ledger_records_and_current_prices(self) -> None:
        artifact = normalize_artifact(
            "reconstruction_report_dir",
            FIXTURES / "reconstruction_report",
        )
        payload = artifact.to_dict()
        record_types = {record["recordType"] for record in payload["normalizedRecords"]}

        self.assertIn(RECORD_LEDGER_TRADE, record_types)
        self.assertIn(RECORD_CURRENT_PRICE, record_types)
        ledger = next(record for record in payload["normalizedRecords"] if record["recordType"] == RECORD_LEDGER_TRADE)
        self.assertEqual(ledger["fields"]["wallet"], "wallet-a")
        self.assertEqual(ledger["fields"]["usdcSize"], "99.21")
        self.assertIn("wallet_from_raw_positions_base_params_derivable", ledger["qualityNotes"])
        self.assertEqual(payload["currentPrices"]["wallet-a|cond-1|token-yes-1|YES"], 0.195)
        self.assertEqual(readiness(artifact, METRIC_NET_PNL)["status"], STATUS_AVAILABLE)
        self.assertEqual(readiness(artifact, METRIC_LOW_ODDS)["status"], STATUS_NOT_COMPUTED)
        self.assert_no_forbidden_output(payload)

    def test_report_output_stays_sidecar_only_and_cli_helpers_can_write_outputs(self) -> None:
        self.assertIn("recent_scanner_report_json", supported_families())
        report = normalize_artifacts(
            [
                ("recent_scanner_report_json", FIXTURES / "recent_scanner_report.json"),
                ("reconstruction_report_dir", FIXTURES / "reconstruction_report"),
            ]
        )
        markdown = markdown_report(report)

        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertIn("Shadow Input Normalization", markdown)
        self.assertIn(METRIC_NET_PNL, markdown)
        self.assert_no_forbidden_output(report)

        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_normalization_outputs(report, tmp)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            self.assertIn("shadow_input_normalization", json_path.read_text(encoding="utf-8"))

    def test_unsupported_families_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_artifact("archive_flagged_csv", FIXTURES / "archive_report.json")

    def test_normalizer_does_not_use_network_calls(self) -> None:
        with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
            with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                artifact = normalize_artifact(
                    "recent_scanner_report_json",
                    FIXTURES / "recent_scanner_report.json",
                )

        self.assertEqual(readiness(artifact, METRIC_LOW_ODDS)["status"], STATUS_AVAILABLE)

    def test_normalizer_tool_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/browser_event_forensic_ui.html",
            "app/storage.py",
            "app/polymarket.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("normalize_shadow_inputs_from_artifacts", source)

    def assert_no_forbidden_output(self, payload: object) -> None:
        text = json.dumps(payload)
        for forbidden in FORBIDDEN_TEXT:
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
