from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.source_schema_repair_plan import build_repair_plan, write_outputs


class SourceSchemaRepairPlanTests(unittest.TestCase):
    def test_high_priority_fields_are_ranked_first(self) -> None:
        payload = build_repair_plan(
            {"summary": {"rows_inspected": 10, "rows_with_missing_fields": 8, "missing_field_counts": {"suppressors": 8}}},
            {"summary": {"rows_inspected": 12, "missing_by_field": {"hard_evidence_sources": 3}}},
        )
        self.assertEqual(payload["summary"]["high_priority_field_count"], 1)
        self.assertEqual(payload["field_actions"][0]["field"], "hard_evidence_sources")
        self.assertFalse(payload["summary"]["detector_behavior_changed"])

    def test_missing_optional_inputs_do_not_crash(self) -> None:
        payload = build_repair_plan({}, {})
        self.assertEqual(payload["summary"]["field_count"], 0)
        self.assertEqual(payload["field_actions"], [])

    def test_outputs_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_outputs(build_repair_plan({}, {}), Path(tmp))
            self.assertTrue(Path(outputs["json_path"]).exists())
            self.assertTrue(Path(outputs["markdown_path"]).exists())


if __name__ == "__main__":
    unittest.main()
