from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.archive_event_pagination_measurement_analysis import (
    build_pagination_measurement_analysis,
    main,
)


class ArchiveEventPaginationMeasurementAnalysisTests(unittest.TestCase):
    def test_scope_risk_measurement_requires_operator_plan(self) -> None:
        analysis = build_pagination_measurement_analysis(
            {
                "networkUsed": True,
                "summary": {"gateDecision": "performance_measurement_blocked_scope_risk"},
                "targetSelection": {"selectedTarget": {"eventSlug": "event-a", "analysisMarketCount": 6}},
                "liveResult": {
                    "status": "blocked_scope_exceeded",
                    "error": "resolved_market_count_exceeds_bound",
                    "resolvedMarketCount": 15,
                },
                "reportSummary": {},
            },
            {
                "summary": {
                    "reportsEvaluated": 10,
                    "truncatedReportedCount": 2,
                    "unknownLegacyCount": 1,
                }
            },
        )

        self.assertEqual(analysis["gateDecision"], "pagination_needs_operator_plan")
        self.assertTrue(any("scope drifted" in item for item in analysis["findings"]))
        self.assertFalse(analysis["runtimeBehaviorChanged"])
        self.assertFalse(analysis["savedArtifactsMutated"])

    def test_complete_untruncated_measurement_is_clean(self) -> None:
        analysis = build_pagination_measurement_analysis(
            {
                "networkUsed": True,
                "summary": {"gateDecision": "performance_measurement_complete"},
                "liveResult": {"status": "completed"},
                "reportSummary": {"truncatedMarketCount": 0},
            },
            {"summary": {"reportsEvaluated": 1, "truncatedReportedCount": 0, "unknownLegacyCount": 0}},
        )

        self.assertEqual(analysis["gateDecision"], "pagination_live_measurement_clean")

    def test_completed_measurement_with_truncation_requires_operator_plan(self) -> None:
        analysis = build_pagination_measurement_analysis(
            {
                "networkUsed": True,
                "summary": {"gateDecision": "performance_measurement_complete"},
                "liveResult": {"status": "completed"},
                "reportSummary": {"truncatedMarketCount": 3},
            },
            {"summary": {"reportsEvaluated": 1, "truncatedReportedCount": 0, "unknownLegacyCount": 0}},
        )

        self.assertEqual(analysis["gateDecision"], "pagination_needs_operator_plan")

    def test_resolved_market_count_uses_completed_live_result_metadata(self) -> None:
        analysis = build_pagination_measurement_analysis(
            {
                "networkUsed": True,
                "summary": {"gateDecision": "performance_measurement_complete"},
                "liveResult": {"status": "completed", "totalEventMarketCount": 1},
                "reportSummary": {"truncatedMarketCount": 0},
            },
            {"summary": {"reportsEvaluated": 1, "truncatedReportedCount": 0, "unknownLegacyCount": 0}},
        )

        self.assertEqual(analysis["measurement"]["resolvedMarketCount"], 1)

    def test_cli_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            measurement = root / "measurement.json"
            completeness = root / "completeness.json"
            output = root / "analysis.json"
            markdown = root / "analysis.md"
            measurement.write_text(
                json.dumps(
                    {
                        "summary": {"gateDecision": "performance_measurement_blocked_scope_risk"},
                        "targetSelection": {"selectedTarget": {"eventSlug": "event-a", "analysisMarketCount": 6}},
                        "liveResult": {"status": "blocked_scope_exceeded", "resolvedMarketCount": 15},
                        "reportSummary": {},
                    }
                ),
                encoding="utf-8",
            )
            completeness.write_text(json.dumps({"summary": {"reportsEvaluated": 1}}), encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "--measurement-summary",
                        str(measurement),
                        "--completeness-audit",
                        str(completeness),
                        "--output",
                        str(output),
                        "--markdown",
                        str(markdown),
                        "--quiet",
                    ]
                ),
                0,
            )
            self.assertTrue(output.exists())
            self.assertTrue(markdown.exists())

    def test_tool_source_has_no_network_imports(self) -> None:
        source = Path("tools/archive_event_pagination_measurement_analysis.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("http.client", source)


if __name__ == "__main__":
    unittest.main()
