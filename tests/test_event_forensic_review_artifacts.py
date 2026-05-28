from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.config import AppConfig
from app.event_forensic_desktop import EventForensicBrowserApp
from app.scanner import ProgressEvent


class EventForensicReviewArtifactsTests(unittest.TestCase):
    def test_review_artifact_index_payload_finds_latest_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packets_dir = root / "review_packets"
            packets_dir.mkdir()
            packet_path = packets_dir / "unique_review_packets_20260505_000000.md"
            packet_path.write_text("# packets\n", encoding="utf-8")
            quality_dir = root / "analyst_quality_outputs"
            quality_dir.mkdir()
            quality_path = quality_dir / "review_packet_quality_check_20260505_000001.md"
            quality_path.write_text("# quality\n", encoding="utf-8")
            queue_path = quality_dir / "wallet_review_queue_20260505_000001.md"
            queue_path.write_text("# queue\n", encoding="utf-8")
            bundle_dir = root / "analyst_review_bundles"
            bundle_dir.mkdir()
            bundle_path = bundle_dir / "analyst_review_bundle_20260505_000001.md"
            bundle_path.write_text("# bundle\n", encoding="utf-8")
            manifest_dir = root / "artifact_manifests"
            manifest_dir.mkdir()
            manifest_path = manifest_dir / "review_artifact_manifest_20260505_000001.md"
            manifest_path.write_text("# manifest\n", encoding="utf-8")
            boundary_dir = root / "implementation_boundaries"
            boundary_dir.mkdir()
            boundary_path = boundary_dir / "implementation_boundary_20260505.md"
            boundary_path.write_text("# boundary\n", encoding="utf-8")
            crosswalk_path = boundary_dir / "analyst_crosswalk_20260505.md"
            crosswalk_path.write_text("# crosswalk\n", encoding="utf-8")
            app = EventForensicBrowserApp.__new__(EventForensicBrowserApp)
            app.config = AppConfig(
                data_dir=root,
                db_path=root / "ignored.sqlite3",
                reports_dir=root / "reports",
                outputs_dir=root / "event_forensic_outputs",
            )
            payload = app._review_artifact_index_payload()
        self.assertIn("review_packets", payload["outputs"])
        self.assertEqual(payload["outputs"]["review_packets"], str(packet_path))
        self.assertEqual(payload["outputs"]["review_packet_quality"], str(quality_path))
        self.assertEqual(payload["outputs"]["wallet_review_queue"], str(queue_path))
        self.assertEqual(payload["outputs"]["analyst_handoff_bundle"], str(bundle_path))
        self.assertEqual(payload["outputs"]["artifact_manifest"], str(manifest_path))
        self.assertEqual(payload["outputs"]["implementation_boundary"], str(boundary_path))
        self.assertEqual(payload["outputs"]["analyst_crosswalk"], str(crosswalk_path))

    def test_open_output_opens_review_artifact_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packets_dir = root / "review_packets"
            packets_dir.mkdir()
            packet_path = packets_dir / "unique_review_packets_20260505_000000.md"
            packet_path.write_text("# packets\n", encoding="utf-8")
            app = EventForensicBrowserApp.__new__(EventForensicBrowserApp)
            app._lock = threading.RLock()
            app.config = AppConfig(
                data_dir=root,
                db_path=root / "ignored.sqlite3",
                reports_dir=root / "reports",
                outputs_dir=root / "event_forensic_outputs",
            )
            app.case_review_status = {"outputs": {}}
            app.current_report = None
            with patch("app.event_forensic_desktop.open_local_path") as open_mock:
                result = app.open_output({"key": "review_packets"})
        self.assertTrue(result["ok"])
        open_mock.assert_called_once_with(packet_path.resolve())

    def test_event_forensic_progress_metadata_is_preserved_in_status(self) -> None:
        app = EventForensicBrowserApp.__new__(EventForensicBrowserApp)
        app._lock = threading.RLock()
        app._append_performance_log = lambda _line: None
        app._on_progress(
            ProgressEvent(
                percent=18,
                stage="Loading trades",
                detail="Fetched market 1/2 for the target event",
                metadata={
                    "analysisMarketTotal": 2,
                    "analysisMarketCompleted": 1,
                    "rawTradeRowsCollectedSoFar": 12,
                    "truncatedMarketCountSoFar": 1,
                    "collectionRiskClass": "truncated_collection_risk",
                },
            )
        )
        self.assertEqual(app.scan_status["progressMetrics"]["analysisMarketCompleted"], 1)
        self.assertEqual(app.scan_status["progressMetrics"]["collectionRiskClass"], "truncated_collection_risk")

    def test_display_report_compatibility_treats_missing_time_window_as_empty(self) -> None:
        app = EventForensicBrowserApp.__new__(EventForensicBrowserApp)
        old_settings = {"analysis_scope": "event", "min_notional": "1000"}
        new_settings = {"analysis_scope": "event", "min_notional": "1000", "start_at": "", "end_at": ""}
        self.assertEqual(
            app._compatible_analysis_settings(old_settings),
            app._compatible_analysis_settings(new_settings),
        )


if __name__ == "__main__":
    unittest.main()
