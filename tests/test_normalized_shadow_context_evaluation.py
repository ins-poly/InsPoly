from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.shadow_metrics import ADVISORY_CONTEXT, ADVISORY_NONE, STATUS_AVAILABLE
from tools.evaluate_normalized_shadow_context import (
    METRIC_ENTRY_EDGE,
    METRIC_LOW_ODDS,
    METRIC_MICROSTRUCTURE,
    METRIC_NET_PNL,
    METRIC_WIN_RATE,
    STATUS_NOT_COMPUTED,
    evaluate_artifact,
    evaluate_artifacts,
    markdown_report,
    write_evaluation_outputs,
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


def metric(payload: dict[str, object], name: str) -> dict[str, object]:
    for item in payload["metricEvaluations"]:
        if item["metric"] == name:
            return item
    raise AssertionError(f"missing metric: {name}")


class NormalizedShadowContextEvaluationTests(unittest.TestCase):
    def test_recent_scanner_normalization_produces_low_odds_metric_but_limited_value(self) -> None:
        payload = evaluate_artifact(
            "recent_scanner_report_json",
            FIXTURES / "recent_scanner_report.json",
        )

        low_odds = metric(payload, METRIC_LOW_ODDS)
        pnl = metric(payload, METRIC_NET_PNL)

        self.assertEqual(payload["normalizedRecordCount"], 1)
        self.assertEqual(low_odds["coverageBefore"], "covered_with_derivations")
        self.assertEqual(low_odds["evaluatedStatus"], STATUS_AVAILABLE)
        self.assertEqual(low_odds["advisoryLevel"], ADVISORY_NONE)
        self.assertFalse(low_odds["usefulAdvisory"])
        self.assertEqual(pnl["evaluatedStatus"], STATUS_NOT_COMPUTED)
        self.assert_no_forbidden_output(payload)

    def test_archive_evaluation_adds_wallet_history_context_but_keeps_other_metrics_not_computed(self) -> None:
        payload = evaluate_artifact(
            "archive_report_json",
            FIXTURES / "archive_report.json",
        )

        win_rate = metric(payload, METRIC_WIN_RATE)
        entry_edge = metric(payload, METRIC_ENTRY_EDGE)
        micro = metric(payload, METRIC_MICROSTRUCTURE)

        self.assertEqual(payload["normalizedRecordCount"], 2)
        self.assertEqual(win_rate["evaluatedStatus"], STATUS_AVAILABLE)
        self.assertEqual(win_rate["advisoryLevel"], ADVISORY_CONTEXT)
        self.assertTrue(win_rate["usefulAdvisory"])
        self.assertEqual(win_rate["details"]["usefulRecordCount"], 1)
        self.assertEqual(entry_edge["evaluatedStatus"], STATUS_NOT_COMPUTED)
        self.assertEqual(micro["evaluatedStatus"], STATUS_NOT_COMPUTED)
        self.assert_no_forbidden_output(payload)

    def test_event_forensic_evaluation_gets_exposure_context_without_hindsight_fields(self) -> None:
        payload = evaluate_artifact(
            "event_forensic_event_analysis_json",
            FIXTURES / "event_forensic_event_analysis.json",
        )

        low_odds = metric(payload, METRIC_LOW_ODDS)
        pnl = metric(payload, METRIC_NET_PNL)

        self.assertEqual(payload["normalizedRecordCount"], 1)
        self.assertGreater(payload["skippedUnsafeFieldCount"], 0)
        self.assertEqual(low_odds["evaluatedStatus"], STATUS_AVAILABLE)
        self.assertEqual(low_odds["advisoryLevel"], ADVISORY_CONTEXT)
        self.assertTrue(low_odds["usefulAdvisory"])
        self.assertIn("cash_amount_from_position_size_derivable_not_shares", low_odds["qualityNotes"])
        self.assertEqual(pnl["evaluatedStatus"], STATUS_NOT_COMPUTED)
        self.assert_no_forbidden_output(payload)

    def test_reconstruction_evaluation_computes_sidecar_pnl_from_ledger_inputs(self) -> None:
        payload = evaluate_artifact(
            "reconstruction_report_dir",
            FIXTURES / "reconstruction_report",
        )

        pnl = metric(payload, METRIC_NET_PNL)
        low_odds = metric(payload, METRIC_LOW_ODDS)

        self.assertEqual(payload["normalizedRecordCount"], 2)
        self.assertEqual(pnl["coverageBefore"], "covered_with_derivations")
        self.assertEqual(pnl["evaluatedStatus"], STATUS_AVAILABLE)
        self.assertEqual(pnl["advisoryLevel"], ADVISORY_CONTEXT)
        self.assertIsNotNone(pnl["value"])
        self.assertTrue(pnl["usefulAdvisory"])
        self.assertEqual(low_odds["evaluatedStatus"], STATUS_NOT_COMPUTED)
        self.assert_no_forbidden_output(payload)

    def test_combined_report_is_sidecar_only_and_can_write_explicit_outputs(self) -> None:
        report = evaluate_artifacts(
            [
                ("archive_report_json", FIXTURES / "archive_report.json"),
                ("event_forensic_event_analysis_json", FIXTURES / "event_forensic_event_analysis.json"),
                ("reconstruction_report_dir", FIXTURES / "reconstruction_report"),
            ]
        )
        markdown = markdown_report(report)

        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertEqual(report["summary"]["artifactCount"], 3)
        self.assertGreaterEqual(report["summary"]["usefulMetricCount"], 3)
        self.assertIn("Normalized Shadow Context Evaluation", markdown)
        self.assert_no_forbidden_output(report)

        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_evaluation_outputs(report, tmp)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            self.assertIn("normalized_shadow_context_evaluation", json_path.read_text(encoding="utf-8"))

    def test_evaluator_does_not_use_network_calls(self) -> None:
        with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
            with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                payload = evaluate_artifact(
                    "recent_scanner_report_json",
                    FIXTURES / "recent_scanner_report.json",
                )

        self.assertEqual(metric(payload, METRIC_LOW_ODDS)["evaluatedStatus"], STATUS_AVAILABLE)

    def test_evaluator_tool_is_not_imported_by_runtime_paths(self) -> None:
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
            self.assertNotIn("evaluate_normalized_shadow_context", source)

    def assert_no_forbidden_output(self, payload: object) -> None:
        text = json.dumps(payload)
        for forbidden in FORBIDDEN_TEXT:
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
