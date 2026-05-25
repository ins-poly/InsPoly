from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.shadow_field_coverage_mapping import (
    CLASS_AMBIGUOUS,
    CLASS_AVAILABLE,
    CLASS_DERIVABLE,
    CLASS_MISSING,
    CLASS_UNSAFE,
    METRIC_COVERED,
    METRIC_COVERED_WITH_DERIVATIONS,
    METRIC_MISSING,
    artifact_families,
    coverage_for_artifact,
    coverage_report,
    markdown_report,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shadow_field_coverage"


def metric(coverage, name: str):
    for item in coverage.metrics:
        if item.metric == name:
            return item
    raise AssertionError(f"Missing metric: {name}")


def slot(metric_coverage, name: str):
    for item in metric_coverage.slots:
        if item.slot == name:
            return item
    raise AssertionError(f"Missing slot: {name}")


class ShadowFieldCoverageMappingTests(unittest.TestCase):
    def test_recent_scanner_report_has_low_odds_inputs_but_missing_reference_and_current_price(self) -> None:
        coverage = coverage_for_artifact(
            "recent_scanner_report_json",
            FIXTURES / "recent_scanner_report.json",
        )

        low_odds = metric(coverage, "shadow_low_odds_position_size")
        entry_edge = metric(coverage, "shadow_entry_price_edge")
        pnl = metric(coverage, "shadow_net_position_pnl")

        self.assertEqual(low_odds.status, METRIC_COVERED_WITH_DERIVATIONS)
        self.assertEqual(slot(low_odds, "entry_price").classification, CLASS_AVAILABLE)
        self.assertEqual(slot(low_odds, "cash_amount").classification, CLASS_DERIVABLE)
        self.assertEqual(slot(entry_edge, "reference_price").classification, CLASS_AMBIGUOUS)
        self.assertEqual(slot(pnl, "current_price").classification, CLASS_MISSING)

    def test_archive_report_json_has_wallet_history_but_no_current_price(self) -> None:
        coverage = coverage_for_artifact(
            "archive_report_json",
            FIXTURES / "archive_report.json",
        )

        low_odds = metric(coverage, "shadow_low_odds_position_size")
        win_rate = metric(coverage, "shadow_win_rate_confidence")
        pnl = metric(coverage, "shadow_net_position_pnl")
        microstructure = metric(coverage, "shadow_microstructure_context")

        self.assertEqual(low_odds.status, METRIC_COVERED_WITH_DERIVATIONS)
        self.assertEqual(win_rate.status, METRIC_COVERED_WITH_DERIVATIONS)
        self.assertEqual(slot(pnl, "current_price").classification, CLASS_MISSING)
        self.assertIn(
            slot(microstructure, "microstructure_snapshot").classification,
            {"incompatible", "unsafe"},
        )

    def test_archive_flagged_csv_is_too_lossy_for_trade_level_shadow_metrics(self) -> None:
        coverage = coverage_for_artifact(
            "archive_flagged_csv",
            FIXTURES / "archive_flagged.csv",
        )

        low_odds = metric(coverage, "shadow_low_odds_position_size")
        pnl = metric(coverage, "shadow_net_position_pnl")
        microstructure = metric(coverage, "shadow_microstructure_context")

        self.assertEqual(low_odds.status, METRIC_MISSING)
        self.assertEqual(slot(low_odds, "entry_price").classification, CLASS_MISSING)
        self.assertEqual(slot(pnl, "condition_id").classification, CLASS_MISSING)
        self.assertEqual(slot(pnl, "token_id").classification, CLASS_MISSING)
        self.assertEqual(slot(microstructure, "microstructure_snapshot").classification, CLASS_UNSAFE)

    def test_event_forensic_json_covers_low_odds_with_derivations_but_not_pnl(self) -> None:
        coverage = coverage_for_artifact(
            "event_forensic_event_analysis_json",
            FIXTURES / "event_forensic_event_analysis.json",
        )

        low_odds = metric(coverage, "shadow_low_odds_position_size")
        pnl = metric(coverage, "shadow_net_position_pnl")
        win_rate = metric(coverage, "shadow_win_rate_confidence")

        self.assertEqual(low_odds.status, METRIC_COVERED_WITH_DERIVATIONS)
        self.assertEqual(slot(low_odds, "cash_amount").field, "display_trades[].positionSize")
        self.assertEqual(slot(pnl, "token_id").classification, CLASS_MISSING)
        self.assertEqual(slot(pnl, "share_size").classification, CLASS_AMBIGUOUS)
        self.assertEqual(slot(win_rate, "win_count").classification, CLASS_AMBIGUOUS)

    def test_old_event_forensic_csv_lacks_price_and_token_fields(self) -> None:
        coverage = coverage_for_artifact(
            "event_forensic_suspicious_trades_csv",
            FIXTURES / "event_forensic_suspicious_trades.csv",
        )

        low_odds = metric(coverage, "shadow_low_odds_position_size")
        pnl = metric(coverage, "shadow_net_position_pnl")

        self.assertEqual(low_odds.status, METRIC_MISSING)
        self.assertEqual(slot(low_odds, "entry_price").classification, CLASS_MISSING)
        self.assertEqual(slot(pnl, "token_id").classification, CLASS_MISSING)
        self.assertEqual(slot(pnl, "share_size").classification, CLASS_AMBIGUOUS)

    def test_wallet_context_only_covers_win_rate_partially_and_duplicates_production_context(self) -> None:
        coverage = coverage_for_artifact(
            "event_forensic_wallet_context_csv",
            FIXTURES / "event_forensic_wallet_context.csv",
        )

        win_rate = metric(coverage, "shadow_win_rate_confidence")
        low_odds = metric(coverage, "shadow_low_odds_position_size")

        self.assertEqual(slot(win_rate, "resolved_count").classification, CLASS_DERIVABLE)
        self.assertEqual(slot(win_rate, "win_count").classification, CLASS_AMBIGUOUS)
        self.assertIn("wallet statistical prior", win_rate.duplicate_production_semantics[0])
        self.assertEqual(low_odds.status, METRIC_MISSING)

    def test_case_specific_ceasefire_shape_has_trade_inputs_but_ambiguous_reference_price(self) -> None:
        coverage = coverage_for_artifact(
            "case_specific_ceasefire_suspicious_trades_csv",
            FIXTURES / "case_specific_ceasefire_suspicious_trades.csv",
        )

        low_odds = metric(coverage, "shadow_low_odds_position_size")
        edge = metric(coverage, "shadow_entry_price_edge")

        self.assertEqual(low_odds.status, METRIC_COVERED_WITH_DERIVATIONS)
        self.assertEqual(slot(low_odds, "entry_price").classification, CLASS_AVAILABLE)
        self.assertEqual(slot(edge, "reference_price").classification, CLASS_AMBIGUOUS)

    def test_reconstruction_report_dir_covers_ledger_inputs_with_derivations(self) -> None:
        coverage = coverage_for_artifact(
            "reconstruction_report_dir",
            FIXTURES / "reconstruction_report",
        )

        pnl = metric(coverage, "shadow_net_position_pnl")
        edge = metric(coverage, "shadow_entry_price_edge")

        self.assertEqual(pnl.status, METRIC_COVERED_WITH_DERIVATIONS)
        self.assertEqual(slot(pnl, "current_price").classification, CLASS_AVAILABLE)
        self.assertEqual(slot(pnl, "wallet").classification, CLASS_DERIVABLE)
        self.assertEqual(edge.status, METRIC_MISSING)

    def test_production_score_like_fields_are_marked_unsafe_when_used_as_candidates(self) -> None:
        coverage = coverage_for_artifact(
            "event_forensic_event_analysis_json",
            FIXTURES / "event_forensic_event_analysis.json",
        )

        edge = metric(coverage, "shadow_entry_price_edge")
        self.assertEqual(slot(edge, "reference_price").classification, CLASS_UNSAFE)

    def test_report_output_is_sidecar_only_and_lists_families(self) -> None:
        self.assertIn("recent_scanner_report_json", artifact_families())
        report = coverage_report(
            [
                ("recent_scanner_report_json", FIXTURES / "recent_scanner_report.json"),
                ("reconstruction_report_dir", FIXTURES / "reconstruction_report"),
            ]
        )
        markdown = markdown_report(report)

        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertIn("shadow_low_odds_position_size", markdown)

    def test_optional_output_files_can_be_written_by_cli_helpers_without_runtime_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = coverage_report(
                [("recent_scanner_report_json", FIXTURES / "recent_scanner_report.json")]
            )
            target = Path(tmp) / "coverage.md"
            target.write_text(markdown_report(report), encoding="utf-8")

            self.assertIn("Shadow Field Coverage Mapping", target.read_text(encoding="utf-8"))

    def test_mapping_tool_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/browser_event_forensic_ui.html",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("shadow_field_coverage_mapping", source)


if __name__ == "__main__":
    unittest.main()
