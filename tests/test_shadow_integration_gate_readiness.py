from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.shadow_integration_gate_readiness import (
    REPORT_TYPE,
    build_shadow_integration_gate_readiness,
    main,
    write_shadow_integration_gate_readiness,
)


ROOT = Path(__file__).resolve().parents[1]


def blocked_inputs() -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    dashboard = {
        "summary": {
            "decision": "keep_sidecar_only",
            "overallDuplicateConfusionRisk": "high",
            "batchNormalizedRecords": 433,
            "batchUsefulMetrics": 3,
            "batchMetricStatusCounts": {"unknown": 10, "not_computed": 162},
        }
    }
    taxonomy = {
        "categorySummary": [
            {"category": "missing_token_id", "productionReportChangeRequired": True},
        ]
    }
    archive_overlap = {
        "summary": {
            "duplicateRatio": "0.57",
            "usefulShadowRows": 48,
            "duplicateProductionSemanticRows": 498,
        }
    }
    previews = {"packetCount": 13}
    return dashboard, taxonomy, archive_overlap, previews


def candidate_inputs() -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    dashboard = {
        "summary": {
            "decision": "rfc_only_candidate",
            "overallDuplicateConfusionRisk": "low",
            "batchNormalizedRecords": 100,
            "batchUsefulMetrics": 20,
            "batchMetricStatusCounts": {"unknown": 1, "not_computed": 2},
        }
    }
    taxonomy = {"categorySummary": []}
    archive_overlap = {
        "summary": {
            "duplicateRatio": "0.10",
            "usefulShadowRows": 80,
            "duplicateProductionSemanticRows": 5,
        }
    }
    previews = {"packetCount": 25}
    return dashboard, taxonomy, archive_overlap, previews


class ShadowIntegrationGateReadinessTests(unittest.TestCase):
    def test_blocks_report_copying_when_evidence_remains_weak(self) -> None:
        dashboard, taxonomy, archive_overlap, previews = blocked_inputs()
        report = build_shadow_integration_gate_readiness(
            dashboard=dashboard,
            taxonomy=taxonomy,
            archive_overlap=archive_overlap,
            packet_previews=previews,
        )

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertEqual(report["decision"], "keep_sidecar_only")
        self.assertFalse(report["reportCopyingRfcAllowed"])
        self.assertFalse(report["implementationAllowed"])
        self.assertTrue(report["blockingReasons"])

    def test_can_identify_rfc_only_candidate_when_no_blockers_remain(self) -> None:
        dashboard, taxonomy, archive_overlap, previews = candidate_inputs()
        report = build_shadow_integration_gate_readiness(
            dashboard=dashboard,
            taxonomy=taxonomy,
            archive_overlap=archive_overlap,
            packet_previews=previews,
        )

        self.assertEqual(report["decision"], "rfc_only_candidate")
        self.assertTrue(report["reportCopyingRfcAllowed"])
        self.assertFalse(report["implementationAllowed"])

    def test_writes_json_and_markdown_outputs(self) -> None:
        dashboard, taxonomy, archive_overlap, previews = blocked_inputs()
        report = build_shadow_integration_gate_readiness(
            dashboard=dashboard,
            taxonomy=taxonomy,
            archive_overlap=archive_overlap,
            packet_previews=previews,
        )
        with tempfile.TemporaryDirectory() as tmp:
            written = write_shadow_integration_gate_readiness(report, tmp)
            latest_json = Path(tmp) / "shadow_integration_gate_readiness_latest.json"
            latest_md = Path(tmp) / "shadow_integration_gate_readiness_latest.md"
            self.assertTrue(latest_json.exists())
            self.assertTrue(latest_md.exists())
            self.assertIn("keep_sidecar_only", latest_md.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(latest_json.read_text(encoding="utf-8"))["decision"], "keep_sidecar_only")
            self.assertIn("outputPaths", written)

    def test_cli_generates_latest_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dashboard, taxonomy, archive_overlap, previews = blocked_inputs()
            paths = {}
            for name, payload in (
                ("dashboard", dashboard),
                ("taxonomy", taxonomy),
                ("archive_overlap", archive_overlap),
                ("previews", previews),
            ):
                path = Path(tmp) / f"{name}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                paths[name] = path
            output_dir = Path(tmp) / "out"
            exit_code = main(
                [
                    "--dashboard-json",
                    str(paths["dashboard"]),
                    "--taxonomy-json",
                    str(paths["taxonomy"]),
                    "--archive-overlap-json",
                    str(paths["archive_overlap"]),
                    "--packet-preview-json",
                    str(paths["previews"]),
                    "--output-dir",
                    str(output_dir),
                    "--quiet",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "shadow_integration_gate_readiness_latest.json").exists())

    def test_gate_tool_is_not_imported_by_runtime_paths(self) -> None:
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
            self.assertNotIn("shadow_integration_gate_readiness", source)


if __name__ == "__main__":
    unittest.main()
