from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.side_outcome_phase2_post_migration_drift_audit import (
    REPORT_TYPE,
    build_post_migration_drift_audit_from_records,
    inspect_runtime_scope,
    main,
    write_outputs,
)


ROOT = Path(__file__).resolve().parents[1]


def _clean_runtime_scan() -> dict[str, object]:
    return {
        "centralHelperUsedByScoreTrade": True,
        "centralHelperUsedByEventForensicScore": True,
        "archiveUsesHelperOnlyForAdditiveRows": True,
        "rawDisplayFieldsPreserved": True,
        "modelFieldsHaveProvenance": True,
        "oldReportLoadingAbsentSafe": True,
        "browserEntryProbabilitySortStillRaw": True,
        "phase3CapitalAtRiskImplemented": False,
        "phase4ClusterDirectionImplemented": False,
        "storageSchemaMentionsPhase2Fields": False,
        "liveRpcNetworkChangesDetected": False,
        "productionImportsThisAuditTool": {},
        "phase3ExpectedBlockPresent": True,
        "phase4ExpectedFailurePresent": True,
    }


def _impact_records() -> list[dict[str, object]]:
    return [
        {
            "artifactFamily": "event_forensic_json",
            "artifactPath": "fixture/event_analysis.json",
            "id": "event-sensitive-sell-yes",
            "wallet": "0xsensitive",
            "conditionId": "cond-sensitive",
            "orderSide": "SELL",
            "side": "YES",
            "price": "0.20",
            "openingExposure": True,
            "winningOutcome": "No",
            "laterWon": False,
            "existingModelClass": "Strong Risk",
            "hardEvidenceReviewTier": "Hard Evidence Review",
        },
        {
            "artifactFamily": "scanner_report_json",
            "artifactPath": "fixture/old_scan.json",
            "trade_id": "old-row-no-model-field",
            "wallet": "0xold",
            "condition_id": "cond-old",
            "side": "SELL",
            "outcome": "YES",
            "price": "0.20",
            "price_implied_probability": "20.0%",
            "trade_state": "increase",
        },
        {
            "artifactFamily": "scanner_report_json",
            "artifactPath": "fixture/malformed_scan.json",
            "trade_id": "malformed-no-price",
            "wallet": "0xmalformed",
            "condition_id": "cond-malformed",
            "side": "SELL",
            "outcome": "YES",
            "price_implied_probability": "",
            "trade_state": "increase",
        },
    ]


def _archive_records() -> list[dict[str, object]]:
    return [
        {
            "artifactFamily": "archive_trades_csv",
            "artifactEvidenceType": "synthetic_fixture",
            "artifactPath": "fixture/archive_trades.csv",
            "sourceShape": "archive_csv_row",
            "trade_id": "archive-sell-no",
            "wallet": "0xarchive",
            "condition_id": "cond-archive",
            "side": "SELL",
            "outcome": "NO",
            "price": "0.80",
            "severity": "Worth a Look",
        }
    ]


class SideOutcomePhase2PostMigrationDriftAuditTests(unittest.TestCase):
    def test_builds_post_migration_report_with_expected_drift_only(self) -> None:
        report = build_post_migration_drift_audit_from_records(
            impact_records=_impact_records(),
            archive_records=_archive_records(),
            root=ROOT,
            runtime_scan=_clean_runtime_scan(),
        )

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertEqual(report["gateDecision"], "phase2_stable")
        self.assertFalse(report["unexpectedDriftFindings"])
        self.assertGreater(report["driftSummary"]["rowsBySurface"]["anyModelRelevantChange"], 0)
        self.assertGreater(report["sensitiveCaseSummary"]["affectedSensitiveContextRows"], 0)
        self.assertGreater(report["compatibilitySweep"]["oldRowsWithoutModelProbability"], 0)
        self.assertGreater(report["compatibilitySweep"]["unknownEconomicProbabilityRows"], 0)
        self.assertFalse(report["phase3CapitalAtRiskImplemented"])
        self.assertFalse(report["phase4ClusterDirectionImplemented"])

    def test_sensitive_review_packet_contains_required_interpretation_fields(self) -> None:
        report = build_post_migration_drift_audit_from_records(
            impact_records=_impact_records(),
            archive_records=_archive_records(),
            root=ROOT,
            runtime_scan=_clean_runtime_scan(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            paths = write_outputs(
                report,
                json_path=output / "drift.json",
                markdown_path=output / "stabilization.md",
                review_dir=output / "review_packet",
            )
            cases = json.loads((output / "review_packet" / "sensitive_cases.json").read_text(encoding="utf-8"))

        self.assertTrue(Path(paths["jsonPath"]).name.endswith(".json"))
        self.assertTrue(Path(paths["markdownPath"]).name.endswith(".md"))
        self.assertTrue(Path(paths["reviewPacketDir"]).name.endswith("review_packet"))
        self.assertTrue(cases)
        first = cases[0]
        self.assertIn("tradeKey", first)
        self.assertIn("rawOrderSide", first)
        self.assertIn("economicSideProbability", first)
        self.assertIn("oldInterpretation", first)
        self.assertIn("newInterpretation", first)
        self.assertIn("affectedScannerArchiveEventForensicOutput", first)
        self.assertTrue(first["expectedByRfc"])

    def test_actual_runtime_scope_scan_keeps_phase3_phase4_and_storage_blocked(self) -> None:
        runtime = inspect_runtime_scope(ROOT)

        self.assertTrue(runtime["centralHelperUsedByScoreTrade"])
        self.assertTrue(runtime["centralHelperUsedByEventForensicScore"])
        self.assertFalse(runtime["phase3CapitalAtRiskImplemented"])
        self.assertFalse(runtime["phase4ClusterDirectionImplemented"])
        self.assertFalse(runtime["storageSchemaMentionsPhase2Fields"])
        self.assertTrue(runtime["browserEntryProbabilitySortStillRaw"])
        self.assertTrue(all(not imported for imported in runtime["productionImportsThisAuditTool"].values()))

    def test_cli_writes_sidecar_outputs_without_runtime_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            exit_code = main(
                [
                    "--root",
                    str(ROOT),
                    "--output-json",
                    str(output / "drift.json"),
                    "--output-md",
                    str(output / "stabilization.md"),
                    "--review-dir",
                    str(output / "review_packet"),
                    "--max-files",
                    "3",
                    "--max-rows-per-file",
                    "20",
                    "--archive-max-files",
                    "10",
                    "--archive-max-rows-per-file",
                    "20",
                    "--quiet",
                ]
            )
            payload = json.loads((output / "drift.json").read_text(encoding="utf-8"))
            review_summary_exists = (output / "review_packet" / "summary.json").exists()

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["gateDecision"], "phase2_stable")
        self.assertTrue(review_summary_exists)
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/browser_ui.html",
            "app/browser_event_forensic_ui.html",
            "app/storage.py",
            "app/polymarket.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("side_outcome_phase2_post_migration_drift_audit", source)


if __name__ == "__main__":
    unittest.main()
