from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.batch_evaluate_normalized_shadow_context import batch_evaluate_from_root
from tools.batch_normalize_shadow_inputs import batch_normalize_from_root
from tools.shadow_artifact_corpus_inventory import discover_corpus_inventory
from tools.shadow_sidecar_value_dashboard import (
    DECISION_KEEP_SIDECAR_ONLY,
    REPORT_TYPE,
    build_dashboard,
    main,
    markdown_report,
    write_dashboard_outputs,
)
from tools.shadow_unknown_reason_taxonomy import build_taxonomy_report


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shadow_artifact_corpus_inventory"


def fixture_inputs() -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    inventory = discover_corpus_inventory(FIXTURES, max_per_family=2, stale_days=99999).to_dict()
    normalization = batch_normalize_from_root(FIXTURES, max_artifacts_per_family=2, max_records_per_artifact=10)
    evaluation = batch_evaluate_from_root(FIXTURES, max_artifacts_per_family=2)
    taxonomy = build_taxonomy_report(normalization, batch_evaluation=evaluation)
    return inventory, normalization, evaluation, taxonomy


class ShadowSidecarValueDashboardTests(unittest.TestCase):
    def test_dashboard_summarizes_phase_outputs_and_keeps_sidecar_decision(self) -> None:
        inventory, normalization, evaluation, taxonomy = fixture_inputs()
        report = build_dashboard(
            inventory=inventory,
            normalization=normalization,
            evaluation=evaluation,
            taxonomy=taxonomy,
        )

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertFalse(report["productionIntegration"])
        self.assertEqual(report["summary"]["decision"], DECISION_KEEP_SIDECAR_ONLY)
        self.assertGreater(report["summary"]["artifactInventoryCount"], 0)
        self.assertTrue(report["phaseHighlights"])

    def test_dashboard_output_is_explicit_json_and_markdown(self) -> None:
        report = build_dashboard(**_dashboard_kwargs())
        markdown = markdown_report(report)

        self.assertIn("Shadow Sidecar Value Dashboard", markdown)
        self.assertIn("Decision Outputs", markdown)

        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_dashboard_outputs(report, tmp)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reportType"], REPORT_TYPE)

    def test_cli_creates_explicit_outputs(self) -> None:
        inventory, normalization, evaluation, taxonomy = fixture_inputs()
        with tempfile.TemporaryDirectory() as tmp:
            inventory_path = Path(tmp) / "inventory.json"
            normalization_path = Path(tmp) / "normalization.json"
            evaluation_path = Path(tmp) / "evaluation.json"
            taxonomy_path = Path(tmp) / "taxonomy.json"
            inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
            normalization_path.write_text(json.dumps(normalization), encoding="utf-8")
            evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
            taxonomy_path.write_text(json.dumps(taxonomy), encoding="utf-8")
            output_json = Path(tmp) / "nested" / "dashboard.json"
            output_md = Path(tmp) / "nested" / "dashboard.md"

            exit_code = main(
                [
                    "--inventory-json",
                    str(inventory_path),
                    "--normalization-json",
                    str(normalization_path),
                    "--evaluation-json",
                    str(evaluation_path),
                    "--taxonomy-json",
                    str(taxonomy_path),
                    "--output-json",
                    str(output_json),
                    "--output-md",
                    str(output_md),
                    "--quiet",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())

    def test_dashboard_tool_is_not_imported_by_runtime_paths(self) -> None:
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
            self.assertNotIn("shadow_sidecar_value_dashboard", source)


def _dashboard_kwargs() -> dict[str, object]:
    inventory, normalization, evaluation, taxonomy = fixture_inputs()
    return {
        "inventory": inventory,
        "normalization": normalization,
        "evaluation": evaluation,
        "taxonomy": taxonomy,
    }


if __name__ == "__main__":
    unittest.main()
