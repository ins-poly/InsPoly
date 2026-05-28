from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.event_forensic_bounded_performance_measurement import MeasurementBounds
from tools.event_forensic_subset_performance_measurement import (
    build_subset_analysis,
    build_subset_selection,
    build_subset_summary,
    main,
    validate_subset_selection,
)


ROOT = Path(__file__).resolve().parents[1]


def _saved_report(path: Path, market_count: int = 2) -> None:
    path.write_text(
        json.dumps(
            {
                "markets": [
                    {
                        "marketSlug": f"event-by-date-{index}",
                        "conditionId": f"0x{index}",
                        "market": f"Event by date {index}?",
                        "winner": "Unknown",
                    }
                    for index in range(market_count)
                ]
            }
        ),
        encoding="utf-8",
    )


class EventForensicSubsetMeasurementTests(unittest.TestCase):
    def test_selection_requires_subset_label_and_no_whole_event_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "event_analysis.json"
            _saved_report(report, market_count=2)

            selection = build_subset_selection(saved_report_path=report, event_slug="large-event")

        self.assertEqual(selection["gateDecision"], "subset_selection_ready")
        self.assertTrue(selection["subsetOnly"])
        self.assertFalse(selection["wholeEventCompletenessClaim"])
        self.assertEqual(selection["selectedMarketSlugs"], ["event-by-date-0", "event-by-date-1"])
        self.assertIn("not the full event", selection["whySubsetIsNotWholeEvent"])

    def test_selection_bounds_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "event_analysis.json"
            _saved_report(report, market_count=3)
            selection = build_subset_selection(
                saved_report_path=report,
                event_slug="large-event",
                bounds=MeasurementBounds(max_markets=2),
            )

        self.assertEqual(selection["selectedMarketCount"], 2)
        self.assertEqual(validate_subset_selection(selection, bounds=MeasurementBounds(max_markets=2)), [])
        selection["selectedMarketSlugs"].append("too-many")
        self.assertIn(
            "subset_market_count_exceeds_bound",
            validate_subset_selection(selection, bounds=MeasurementBounds(max_markets=2)),
        )

    def test_summary_blocks_whole_event_completeness_claims(self) -> None:
        selection = {
            "subsetOnly": True,
            "wholeEventCompletenessClaim": False,
            "eventSlug": "large-event",
            "selectedMarketSlugs": ["a", "b"],
        }
        summary = build_subset_summary(
            output_dir=Path("/tmp/subset"),
            bounds=MeasurementBounds(),
            env_status={"rpcConfigured": True, "secretsPrinted": False},
            selection=selection,
            live_result={
                "status": "completed",
                "eventSlug": "large-event",
                "analysisMarketCount": 2,
                "liveResolvedMarketCount": 15,
                "rawTradeCount": 1000,
                "candidateTradeCount": 100,
                "candidateWalletCount": 120,
                "truncatedMarketCount": 1,
                "timings": {"prefetch_wallet_context_seconds": 4.0, "total_seconds": 10.0},
            },
        )

        self.assertEqual(summary["summary"]["gateDecision"], "subset_measurement_complete")
        self.assertTrue(summary["subsetOnly"])
        self.assertFalse(summary["wholeEventCompletenessClaim"])
        self.assertEqual(summary["summary"]["liveResolvedMarketCount"], 15)

    def test_analysis_recommends_patch_rfc_for_multimarket_subset_with_bottleneck(self) -> None:
        subset_summary = {
            "networkUsed": True,
            "outputDir": "validation_outputs/subset",
            "summary": {
                "gateDecision": "subset_measurement_complete",
                "eventSlug": "large-event",
                "selectedMarketCount": 6,
                "analysisMarketCount": 6,
                "liveResolvedMarketCount": 15,
                "rawTradeRows": 12000,
                "candidateRows": 900,
                "candidateWalletCount": 300,
                "truncatedMarketCount": 2,
                "dominantBottleneck": "prefetch_wallet_context_seconds",
                "totalSeconds": 120.0,
            },
        }

        analysis = build_subset_analysis(
            subset_summary=subset_summary,
            aggregate_payload={"summary": {"medianTotalSeconds": 20.54}},
        )

        self.assertEqual(analysis["summary"]["gateDecision"], "subset_measurement_complete_patch_rfc_ready")
        self.assertTrue(analysis["patchRfcRecommended"])
        self.assertFalse(analysis["paginationAssessment"]["wholeEventCompletenessProven"])

    def test_malformed_selection_blocks_scope(self) -> None:
        violations = validate_subset_selection(
            {"wholeEventCompletenessClaim": True, "eventSlug": "", "selectedMarketSlugs": []},
            bounds=MeasurementBounds(),
        )

        self.assertIn("missing_subset_only_label", violations)
        self.assertIn("whole_event_completeness_claim_not_allowed", violations)
        self.assertIn("missing_event_slug", violations)
        self.assertIn("missing_market_slug_allowlist", violations)

    def test_cli_writes_selection_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "event_analysis.json"
            output = Path(tmp) / "selection.json"
            _saved_report(report, market_count=1)

            self.assertEqual(
                main(
                    [
                        "--select-only",
                        "--saved-report",
                        str(report),
                        "--event-slug",
                        "large-event",
                        "--selection-output",
                        str(output),
                        "--quiet",
                    ]
                ),
                0,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(payload["networkUsed"])
        self.assertTrue(payload["subsetOnly"])

    def test_tool_source_has_no_private_or_trading_markers(self) -> None:
        source = (ROOT / "tools/event_forensic_subset_performance_measurement.py").read_text(encoding="utf-8")

        forbidden = (
            "place" + "_order",
            "create" + "_order",
            "PRIVATE" + "_KEY =",
            "CLOB" + "_SECRET =",
            "CLOB" + "_API_KEY =",
        )
        for marker in forbidden:
            self.assertNotIn(marker, source)


if __name__ == "__main__":
    unittest.main()
