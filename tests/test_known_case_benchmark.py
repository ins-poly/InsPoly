from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.curate_known_case_benchmark import (
    REQUIRED_CATEGORIES,
    curate_known_case_benchmark,
    main as curate_main,
    validate_known_case_corpus,
)
from tools.run_known_case_benchmark import main as run_main
from tools.run_known_case_benchmark import run_known_case_benchmark


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "known_case_benchmark" / "post_side_outcome_known_cases.json"


class KnownCaseBenchmarkTests(unittest.TestCase):
    def test_curated_corpus_schema_and_required_categories(self) -> None:
        payload = json.loads(CORPUS.read_text(encoding="utf-8"))
        errors = validate_known_case_corpus(payload)

        self.assertEqual(errors, [])
        categories = {case["category"] for case in payload["cases"]}
        self.assertEqual(set(REQUIRED_CATEGORIES) - categories, set())
        self.assertEqual(payload["schemaVersion"], "known_case_benchmark_v2")

    def test_curation_tool_runs_offline_and_marks_synthetic_cases(self) -> None:
        corpus = curate_known_case_benchmark(ROOT)

        self.assertFalse(corpus["networkUsed"])
        self.assertFalse(corpus["productionIntegration"])
        synthetic = [case for case in corpus["cases"] if case["source_type"] == "synthetic_fixture"]
        self.assertGreater(len(synthetic), 0)
        for case in synthetic:
            self.assertIn("synthetic", case["provenance_quality"])

    def test_curated_case_ids_and_categories_match_committed_fixture(self) -> None:
        committed = json.loads(CORPUS.read_text(encoding="utf-8"))
        curated = curate_known_case_benchmark(ROOT)

        committed_cases = [(case["case_id"], case["category"]) for case in committed["cases"]]
        curated_cases = [(case["case_id"], case["category"]) for case in curated["cases"]]
        self.assertEqual(curated_cases, committed_cases)

    def test_curation_cli_writes_output_and_supports_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "known_cases.json"
            self.assertEqual(
                curate_main(["--root", str(ROOT), "--output", str(output), "--quiet"]),
                0,
            )
            self.assertTrue(output.exists())
            dry_run_output = Path(tmp) / "dry_run.json"
            self.assertEqual(
                curate_main(["--root", str(ROOT), "--output", str(dry_run_output), "--dry-run", "--quiet"]),
                0,
            )
            self.assertFalse(dry_run_output.exists())

    def test_benchmark_runner_passes_curated_corpus(self) -> None:
        report = run_known_case_benchmark(CORPUS)

        self.assertEqual(report["gateDecision"], "known_case_corpus_ready")
        self.assertEqual(report["summary"]["failCount"], 0)
        self.assertEqual(report["summary"]["caseCount"], len(REQUIRED_CATEGORIES))
        self.assertEqual(report["summary"]["falsePositiveControlCaseCount"], 4)
        self.assertEqual(report["summary"]["advisoryOnlyCaseCount"], 8)

    def test_buy_sell_economic_probability_expectations(self) -> None:
        report = run_known_case_benchmark(CORPUS)
        results = {row["category"]: row for row in report["caseResults"]}

        self.assertEqual(
            results["sell_yes_low_price_economic_no_high_probability"]["observed"]["model_probability"],
            "0.80",
        )
        self.assertEqual(
            results["sell_no_low_price_economic_yes_high_probability"]["observed"]["model_probability"],
            "0.80",
        )

    def test_cluster_direction_expectations(self) -> None:
        report = run_known_case_benchmark(CORPUS)
        results = {row["category"]: row for row in report["caseResults"]}

        long_yes = results["buy_yes_sell_no_same_cluster_long_yes"]["tradeResults"]
        long_no = results["buy_no_sell_yes_same_cluster_long_no"]["tradeResults"]
        self.assertEqual({row["cluster_direction"] for row in long_yes}, {"long_yes"})
        self.assertEqual({row["cluster_direction"] for row in long_no}, {"long_no"})

    def test_malformed_old_report_and_phase3_blocked_cases(self) -> None:
        report = run_known_case_benchmark(CORPUS)
        results = {row["category"]: row for row in report["caseResults"]}

        malformed = results["malformed_missing_fallback"]
        self.assertEqual(malformed["observed"]["model_probability"], "unknown")
        self.assertEqual(malformed["status"], "unknown_pass")
        old_report = results["old_report_without_phase2_phase4_fields"]
        self.assertEqual(old_report["observed"]["model_probability"], "0.8")
        phase3 = results["phase3_capital_at_risk_blocked_overlap"]
        self.assertFalse(phase3["observed"]["phase3_runtime_allowed"])

    def test_false_positive_controls_are_advisory_only(self) -> None:
        payload = json.loads(CORPUS.read_text(encoding="utf-8"))
        controls = [
            case
            for case in payload["cases"]
            if case.get("assertion_type") == "false_positive_control"
        ]

        self.assertEqual(
            {case["category"] for case in controls},
            {
                "false_positive_near_certainty_control",
                "high_volume_public_user_false_positive_control",
                "funding_unknown_control",
                "no_independent_hard_evidence_control",
            },
        )
        for case in controls:
            expected = case["expected_result"]
            self.assertFalse(expected["automatic_action_allowed"])
            self.assertFalse(expected["safe_to_use_for_scoring_claims"])
            self.assertFalse(expected["direct_gate_mutation_allowed"])
            self.assertTrue(expected["false_positive_control"])
            self.assertTrue(expected["requires_fresh_validation_for_model_use"])
            self.assertTrue(case["forbidden_interpretation"])
            self.assertGreater(len(case["false_positive_notes"]), 0)

    def test_sidecar_context_controls_do_not_authorize_runtime_changes(self) -> None:
        payload = json.loads(CORPUS.read_text(encoding="utf-8"))
        controls = [
            case
            for case in payload["cases"]
            if case.get("assertion_type") == "sidecar_context_control"
        ]

        self.assertEqual(
            {case["category"] for case in controls},
            {
                "true_low_probability_later_winner",
                "weak_history_near_certainty_demotion",
                "selected_market_vs_whole_event_scope_boundary",
                "pagination_truncation_warning_control",
            },
        )
        for case in controls:
            expected = case["expected_result"]
            self.assertFalse(expected["automatic_action_allowed"])
            self.assertFalse(expected["safe_to_use_for_scoring_claims"])
            self.assertTrue(expected["requires_fresh_validation_for_model_use"])
            self.assertIn("Do not", case["forbidden_interpretation"])

    def test_no_duplicate_case_ids_and_fixture_remains_compact(self) -> None:
        payload = json.loads(CORPUS.read_text(encoding="utf-8"))
        case_ids = [case["case_id"] for case in payload["cases"]]

        self.assertEqual(len(case_ids), len(set(case_ids)))
        self.assertLess(CORPUS.stat().st_size, 80_000)

    def test_run_cli_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run.json"
            self.assertEqual(
                run_main(["--corpus", str(CORPUS), "--output", str(output), "--quiet"]),
                0,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["gateDecision"], "known_case_corpus_ready")
        self.assertFalse(payload["networkUsed"])

    def test_tools_are_not_imported_by_runtime_paths(self) -> None:
        forbidden = ("curate_known_case_benchmark", "run_known_case_benchmark")
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
