from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.side_outcome_phase4_post_migration_drift_audit import (
    REPORT_TYPE,
    build_phase4_post_migration_drift_audit_from_records,
    inspect_phase4_runtime_scope,
    main,
    write_outputs,
)


ROOT = Path(__file__).resolve().parents[1]


def _clean_runtime_scan() -> dict[str, object]:
    return {
        "centralClusterHelperExists": True,
        "centralClusterHelperDelegatesToSideOutcome": True,
        "scannerClusterUsesCentralHelper": True,
        "scannerSameSideWindowUsesNormalizedDirection": True,
        "scannerStructuralGroupsUseClusterHelper": True,
        "archiveExportsClusterFields": True,
        "eventForensicTimingUsesClusterDirection": True,
        "eventForensicPayloadExportsClusterFields": True,
        "rawDisplayFieldsPreserved": True,
        "malformedFallbackConservative": True,
        "phase3CapitalAtRiskImplemented": False,
        "directGateLogicUsesClusterNormalization": False,
        "storageClusterSchemaChanged": False,
        "browserClusterSortingFilteringChanged": False,
        "liveRpcNetworkChangesDetected": False,
        "productionImportsThisAuditTool": {},
        "phase3BlockStillDocumented": True,
        "runtimeVerificationOutputPresent": True,
    }


def _records() -> list[dict[str, object]]:
    return [
        {
            "id": "buy-yes-sensitive",
            "artifactFamily": "scanner_report_json",
            "artifactEvidenceType": "synthetic_fixture",
            "wallet": "0xphase4a",
            "condition_id": "cond-phase4-yes",
            "marketSlug": "phase4-yes-market",
            "eventSlug": "phase4-event",
            "side": "BUY",
            "outcome": "YES",
            "price": "0.20",
            "economic_direction": "long_yes",
            "hardEvidenceReviewTier": "Hard Evidence Review",
        },
        {
            "id": "sell-no-sensitive",
            "artifactFamily": "scanner_report_json",
            "artifactEvidenceType": "synthetic_fixture",
            "wallet": "0xphase4b",
            "condition_id": "cond-phase4-yes",
            "marketSlug": "phase4-yes-market",
            "eventSlug": "phase4-event",
            "side": "SELL",
            "outcome": "NO",
            "price": "0.20",
            "economic_direction": "short_no",
            "fundingEvidenceGrade": "suspicious_direct",
        },
        {
            "id": "buy-no",
            "artifactFamily": "event_forensic_json",
            "artifactEvidenceType": "synthetic_fixture",
            "wallet": "0xphase4c",
            "condition_id": "cond-phase4-no",
            "marketSlug": "phase4-no-market",
            "eventSlug": "phase4-event",
            "side": "BUY",
            "outcome": "NO",
            "price": "0.30",
            "economic_direction": "long_no",
        },
        {
            "id": "sell-yes",
            "artifactFamily": "event_forensic_json",
            "artifactEvidenceType": "synthetic_fixture",
            "wallet": "0xphase4d",
            "condition_id": "cond-phase4-no",
            "marketSlug": "phase4-no-market",
            "eventSlug": "phase4-event",
            "side": "SELL",
            "outcome": "YES",
            "price": "0.30",
            "economic_direction": "short_yes",
            "candidateAdmissionStage": "candidate",
        },
        {
            "id": "old-direction-only",
            "artifactFamily": "archive_report_json",
            "artifactEvidenceType": "existing_test_fixture",
            "condition_id": "cond-old",
            "economic_direction": "short_yes",
        },
        {
            "id": "malformed",
            "artifactFamily": "archive_report_json",
            "artifactEvidenceType": "synthetic_fixture",
            "condition_id": "cond-bad",
            "side": "SELL",
            "outcome": "MAYBE",
            "price": "0.20",
            "economic_direction": "short_yes",
        },
    ]


class SideOutcomePhase4PostMigrationDriftAuditTests(unittest.TestCase):
    def test_builds_stable_report_with_expected_phase4_drift_only(self) -> None:
        report = build_phase4_post_migration_drift_audit_from_records(
            _records(),
            root=ROOT,
            runtime_scan=_clean_runtime_scan(),
        )

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertEqual(report["gateDecision"], "phase4_stable")
        self.assertFalse(report["unexpectedDriftFindings"])
        self.assertGreater(report["driftSummary"]["affectedCounts"]["rowsWithDirectionChange"], 0)
        self.assertGreater(report["driftSummary"]["affectedCounts"]["rowsInPreviouslySplitMergeGroups"], 0)
        self.assertGreater(report["sensitiveMergeGroupSummary"]["sensitiveMergeGroupCount"], 0)
        self.assertGreater(report["compatibilitySweep"]["oldLegacyDirectionOnlyRows"], 0)
        self.assertGreater(report["compatibilitySweep"]["unknownOrMalformedRows"], 0)
        self.assertFalse(report["implementationReview"]["phase3CapitalAtRiskImplemented"])

    def test_review_packet_contains_group_keys_and_risk_sizing_confirmation(self) -> None:
        report = build_phase4_post_migration_drift_audit_from_records(
            _records(),
            root=ROOT,
            runtime_scan=_clean_runtime_scan(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            paths = write_outputs(
                report,
                json_path=output / "phase4.json",
                markdown_path=output / "phase4.md",
                review_dir=output / "review_packet",
            )
            self.assertTrue(Path(paths["jsonPath"]).exists())
            self.assertTrue(Path(paths["markdownPath"]).exists())
            groups = json.loads((output / "review_packet" / "sensitive_merge_groups.json").read_text(encoding="utf-8"))

        self.assertTrue(groups)
        first = groups[0]
        self.assertIn("normalizedGroupKey", first)
        self.assertIn("oldDirections", first)
        self.assertIn("rows", first)
        self.assertFalse(first["riskSizingChanged"])
        self.assertTrue(first["expectedByRfc"])
        self.assertIn("newNormalizedClusterDirection", first["rows"][0])

    def test_actual_runtime_scan_confirms_scope_boundaries(self) -> None:
        runtime = inspect_phase4_runtime_scope(ROOT)

        self.assertTrue(runtime["centralClusterHelperExists"])
        self.assertTrue(runtime["centralClusterHelperDelegatesToSideOutcome"])
        self.assertTrue(runtime["scannerSameSideWindowUsesNormalizedDirection"])
        self.assertTrue(runtime["scannerStructuralGroupsUseClusterHelper"])
        self.assertTrue(runtime["archiveExportsClusterFields"])
        self.assertTrue(runtime["eventForensicTimingUsesClusterDirection"])
        self.assertFalse(runtime["phase3CapitalAtRiskImplemented"])
        self.assertFalse(runtime["directGateLogicUsesClusterNormalization"])
        self.assertFalse(runtime["storageClusterSchemaChanged"])
        self.assertFalse(runtime["browserClusterSortingFilteringChanged"])
        self.assertTrue(all(not imported for imported in runtime["productionImportsThisAuditTool"].values()))

    def test_cli_writes_outputs_without_runtime_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            exit_code = main(
                [
                    "--root",
                    str(ROOT),
                    "--output-json",
                    str(output / "phase4.json"),
                    "--output-md",
                    str(output / "phase4.md"),
                    "--review-dir",
                    str(output / "review_packet"),
                    "--max-files",
                    "30",
                    "--max-rows-per-file",
                    "25",
                    "--quiet",
                ]
            )
            payload = json.loads((output / "phase4.json").read_text(encoding="utf-8"))
            review_summary_exists = (output / "review_packet" / "summary.json").exists()

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["gateDecision"], "phase4_stable")
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
            self.assertNotIn("side_outcome_phase4_post_migration_drift_audit", source)


if __name__ == "__main__":
    unittest.main()
