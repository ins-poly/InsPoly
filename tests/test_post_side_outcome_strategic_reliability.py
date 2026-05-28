from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.post_side_outcome_strategic_reliability import (
    PROGRAM_JSON_PATHS,
    build_program_reports,
    inspect_forbidden_scope,
    main,
    write_program_reports,
)


ROOT = Path(__file__).resolve().parents[1]


class PostSideOutcomeStrategicReliabilityTests(unittest.TestCase):
    def test_program_reports_have_expected_gates_and_no_runtime_flags(self) -> None:
        reports = build_program_reports(ROOT)

        self.assertEqual(reports["event_forensic_reliability"]["gateDecision"], "event_forensic_needs_live_rpc_validation")
        self.assertEqual(reports["benchmark_productization"]["gateDecision"], "benchmark_system_local_regression_ready")
        self.assertEqual(reports["event_level_semantics"]["gateDecision"], "event_level_semantics_rfc_ready_no_runtime")
        self.assertEqual(reports["phase3_capital_source_quality"]["gateDecision"], "keep_phase3_blocked")
        self.assertEqual(reports["sensitive_gate_integrity"]["gateDecision"], "sensitive_gate_integrity_preserved_local_only")
        self.assertEqual(reports["archive_completeness_visibility"]["gateDecision"], "archive_visibility_monitoring_local_only")
        for report in reports.values():
            self.assertFalse(report["networkUsed"])
            self.assertFalse(report["productionIntegration"])
            self.assertFalse(report["runtimeBehaviorChanged"])

    def test_summary_reports_all_program_gates(self) -> None:
        reports = build_program_reports(ROOT)
        gates = reports["summary"]["programGates"]

        for key in PROGRAM_JSON_PATHS:
            if key != "summary":
                self.assertIn(key, gates)
        self.assertIn("Phase 3 capital-at-risk runtime implementation", reports["summary"]["blocked"])

    def test_forbidden_scope_scan_is_clean(self) -> None:
        scan = inspect_forbidden_scope(ROOT)

        self.assertFalse(scan["strategicToolNetworkTokens"])
        self.assertFalse(scan["runtimeImportsStrategicTool"])
        self.assertFalse(scan["phase3CapitalHelperUsesSideOutcome"])
        self.assertFalse(scan["storageSchemaStrategicMarkers"])
        self.assertFalse(scan["browserSortingFilteringStrategicMarkers"])
        self.assertFalse(scan["polymarketLiveStrategicMarkers"])

    def test_write_program_outputs_and_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reports = build_program_reports(ROOT)
            written = write_program_reports(reports, root=ROOT, output_dir=tmp)

            self.assertEqual(set(written), set(PROGRAM_JSON_PATHS))
            for path in written.values():
                payload = json.loads(Path(path).read_text(encoding="utf-8"))
                self.assertIn("gateDecision", payload)

            self.assertEqual(main(["--root", str(ROOT), "--output-dir", tmp, "--quiet"]), 0)


if __name__ == "__main__":
    unittest.main()
