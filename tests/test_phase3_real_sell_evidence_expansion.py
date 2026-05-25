from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.phase3_real_sell_evidence_discovery import (
    PROVENANCE_EXISTING_FIXTURE,
    PROVENANCE_REAL_PROFILE,
    PROVENANCE_REAL_RECONSTRUCTION,
    PROVENANCE_SYNTHETIC_FIXTURE,
    build_real_sell_evidence_discovery,
    classify_artifact_provenance,
    evaluate_sell_evidence_row,
)
from tools.phase3_sensitive_capital_review_packets import build_review_packets, write_review_packets


ROOT = Path(__file__).resolve().parents[1]


class Phase3RealSellEvidenceExpansionTests(unittest.TestCase):
    def test_artifact_provenance_distinguishes_real_and_fixture_sources(self) -> None:
        self.assertEqual(
            classify_artifact_provenance("polymarket_profile_0xabc_report/normalized_trades.csv"),
            PROVENANCE_REAL_PROFILE,
        )
        self.assertEqual(
            classify_artifact_provenance("polymarket_wallet_0xabc_report/normalized_trades.csv"),
            PROVENANCE_REAL_RECONSTRUCTION,
        )
        self.assertEqual(
            classify_artifact_provenance("tests/fixtures/polymarket_ledger_artifacts/profile_like_good/normalized_trades.csv"),
            PROVENANCE_EXISTING_FIXTURE,
        )
        self.assertEqual(
            classify_artifact_provenance("tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json"),
            PROVENANCE_SYNTHETIC_FIXTURE,
        )

    def test_sell_max_loss_is_safe_only_with_direct_price_and_size_fields(self) -> None:
        row = evaluate_sell_evidence_row(
            {
                "side": "SELL",
                "outcome": "YES",
                "price": "0.20",
                "size": "100",
                "usdcSize": "20",
                "artifactPath": "polymarket_wallet_0xabc_report/normalized_trades.csv",
                "artifactFamily": "normalized_trades_csv",
                "artifactEvidenceType": "real_local",
                "source_type": "normalized_trade",
            }
        )

        self.assertTrue(row["safeForSellMaxLoss"])
        self.assertEqual(row["sourceProvenance"], PROVENANCE_REAL_RECONSTRUCTION)
        self.assertEqual(row["hypotheticalSellMaxLoss"], "80.00")
        self.assertEqual(row["observedCash"], "20")
        self.assertEqual(row["recommendation"], "safe_sidecar_only")

    def test_old_notional_only_row_remains_unsafe(self) -> None:
        row = evaluate_sell_evidence_row(
            {
                "side": "SELL",
                "outcome": "YES",
                "trade_notional_usdc": "20",
                "capital_at_risk_usdc": "20",
                "artifactFamily": "scanner_report_json",
                "artifactEvidenceType": "real_local",
                "source_type": "scanner_report_json",
            }
        )

        self.assertFalse(row["safeForSellMaxLoss"])
        self.assertEqual(row["recommendation"], "unsafe_old_notional")
        self.assertIn("notional_only_cannot_be_reinterpreted", row["qualityNotes"])

    def test_discovery_summary_counts_real_and_synthetic_sell_rows_separately(self) -> None:
        report = build_real_sell_evidence_discovery(
            [
                {
                    "side": "SELL",
                    "outcome": "NO",
                    "price": "0.30",
                    "size": "10",
                    "artifactPath": "polymarket_profile_0xabc_report/normalized_trades.csv",
                    "artifactFamily": "normalized_trades_csv",
                    "artifactEvidenceType": "real_local",
                    "source_type": "normalized_trade",
                },
                {
                    "side": "SELL",
                    "outcome": "YES",
                    "price": "0.20",
                    "size": "1",
                    "artifactPath": "tests/fixtures/side_outcome_phase3_capital_at_risk/cases.json",
                    "artifactFamily": "known_case_benchmark",
                    "artifactEvidenceType": "synthetic_fixture",
                    "source_type": "known_case_benchmark",
                },
            ]
        )

        summary = report["summary"]
        self.assertEqual(summary["sellRows"], 2)
        self.assertEqual(summary["realSellRows"], 1)
        self.assertEqual(summary["syntheticSellRows"], 1)
        self.assertEqual(summary["safeRealSellMaxLossRows"], 1)

    def test_sensitive_packet_generation_is_schema_stable_and_does_not_mutate_inputs(self) -> None:
        discovery = {
            "reportType": "phase3_real_sell_evidence_discovery",
            "summary": {"sensitiveOverlapRows": 1},
            "reviewCandidates": [
                {
                    "rowId": "row-1",
                    "sourceProvenance": "synthetic_fixture",
                    "sourceType": "known_case_benchmark",
                    "artifactFamily": "known_case_benchmark",
                    "artifactPath": "tests/fixtures/example.json",
                    "wallet": "wallet-a",
                    "market": "market-a",
                    "event": "event-a",
                    "rawOrderSide": "SELL",
                    "rawTokenOutcome": "YES",
                    "rawTokenPrice": "0.20",
                    "size": "1",
                    "usdcSize": "unknown",
                    "economicSide": "NO",
                    "economicSideProbability": "0.80",
                    "currentRawNotional": "0.20",
                    "hypotheticalSellMaxLoss": "0.80",
                    "observedCash": "unknown",
                    "sourceQuality": "safe_for_display_only",
                    "safeForSellMaxLoss": False,
                    "sensitiveOverlap": True,
                    "recommendation": "needs_source_fields",
                    "qualityNotes": ["missing_source_fields"],
                }
            ],
        }
        source_inventory = {"reportType": "phase3_capital_source_inventory"}
        impact = {
            "reportType": "phase3_capital_unblock_impact_audit",
            "gateDecision": "phase3_ready_for_partial_safe_sidecar_only",
            "summary": {"oldAuditSensitiveOverlapRows": 2177},
        }
        before = copy.deepcopy(discovery)

        report = build_review_packets(discovery=discovery, source_inventory=source_inventory, impact_audit=impact)

        self.assertEqual(discovery, before)
        self.assertEqual(report["summary"]["packets"], 1)
        self.assertEqual(report["summary"]["needsSourceFields"], 1)
        self.assertFalse(report["productionIntegration"])
        self.assertFalse(report["networkUsed"])

        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_review_packets(report, tmp)
            output_dir = Path(outputs["outputDir"])
            index_payload = json.loads((output_dir / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index_payload["summary"]["packets"], 1)
            self.assertTrue((output_dir / "phase3-sensitive-capital-001.json").exists())
            self.assertTrue((output_dir / "phase3-sensitive-capital-001.md").exists())

    def test_new_tools_do_not_use_network_modules(self) -> None:
        for relative_path in (
            "tools/phase3_real_sell_evidence_discovery.py",
            "tools/phase3_sensitive_capital_review_packets.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("requests", source)
            self.assertNotIn("urlopen", source)
            self.assertNotIn("http.client", source)
            self.assertNotIn("socket", source)

    def test_new_tools_are_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/browser_ui.html",
            "app/browser_event_forensic_ui.html",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("phase3_real_sell_evidence_discovery", source)
            self.assertNotIn("phase3_sensitive_capital_review_packets", source)


if __name__ == "__main__":
    unittest.main()
