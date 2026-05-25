from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.audit_shadow_metrics_against_artifacts import (
    STATUS_OK,
    STATUS_WARNING,
    audit_shadow_metrics_artifact_dir,
    write_shadow_artifact_audit,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "shadow_metrics_artifacts"


class ShadowMetricsArtifactAuditTests(unittest.TestCase):
    def test_reads_event_like_fixture_and_emits_advisory_metrics_only(self) -> None:
        audit = audit_shadow_metrics_artifact_dir(FIXTURES / "event_like")

        self.assertEqual(audit.status, STATUS_OK)
        self.assertEqual(audit.rows_loaded, 1)
        metric_names = {metric["name"] for metric in audit.metrics}
        self.assertIn("shadow_low_odds_position_size", metric_names)
        self.assertIn("shadow_microstructure_context", metric_names)
        self.assertFalse(audit.network_used)
        self.assertFalse(audit.production_integration)
        self.assertNotIn("risk_level", json.dumps(audit.to_dict()))
        self.assertNotIn("Hard Evidence Review", json.dumps(audit.to_dict()))

    def test_missing_fields_stay_unknown_and_do_not_become_zero(self) -> None:
        audit = audit_shadow_metrics_artifact_dir(FIXTURES / "missing_data")

        self.assertEqual(audit.status, STATUS_WARNING)
        low_odds = self._metric(audit, "shadow_low_odds_position_size")
        pnl = self._metric(audit, "shadow_net_position_pnl")
        self.assertEqual(low_odds["status"], "unknown")
        self.assertIsNone(low_odds["value"])
        self.assertEqual(pnl["status"], "unknown")

    def test_optional_output_writes_json_and_markdown(self) -> None:
        audit = audit_shadow_metrics_artifact_dir(FIXTURES / "event_like")
        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_shadow_artifact_audit(audit, tmp)

            written = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")

        self.assertEqual(written["rowsLoaded"], 1)
        self.assertIn("Shadow Metrics Artifact Audit", markdown)
        self.assertIn("shadow_low_odds_position_size", markdown)

    def test_audit_does_not_use_network_calls(self) -> None:
        with patch("socket.create_connection", side_effect=AssertionError("network call blocked")):
            with patch("urllib.request.urlopen", side_effect=AssertionError("network call blocked")):
                audit = audit_shadow_metrics_artifact_dir(FIXTURES / "event_like")

        self.assertEqual(audit.status, STATUS_OK)

    def test_audit_tool_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("audit_shadow_metrics_against_artifacts", source)

    def _metric(self, audit, name: str):
        for metric in audit.metrics:
            if metric["name"] == name:
                return metric
        raise AssertionError(f"Missing metric: {name}")


if __name__ == "__main__":
    unittest.main()
