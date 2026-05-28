from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.generate_shadow_review_packets import (
    INDEX_TYPE,
    build_shadow_review_packets,
    main,
    packet_markdown,
    write_shadow_review_packets,
)


ROOT = Path(__file__).resolve().parents[1]


def sample_batch_eval() -> dict[str, object]:
    return {
        "artifacts": [
            {
                "artifactPath": "archive.json",
                "inventoryFamily": "archive_report_json",
                "normalizationQualityNotes": ["note-a"],
                "metricEvaluations": [
                    {
                        "metric": "shadow_win_rate_confidence",
                        "evaluatedStatus": "available",
                        "advisoryLevel": "context",
                        "value": "0.2",
                        "usefulAdvisory": True,
                        "details": {},
                        "qualityNotes": [],
                    }
                ],
            }
        ]
    }


class ShadowReviewPacketsTests(unittest.TestCase):
    def test_packets_are_sidecar_only_and_include_advisory_metrics(self) -> None:
        packets = build_shadow_review_packets(batch_evaluation=sample_batch_eval())

        self.assertEqual(len(packets), 1)
        packet = packets[0]
        self.assertTrue(packet["sidecarOnly"])
        self.assertFalse(packet["productionIntegration"])
        self.assertEqual(packet["sourceArtifactPath"], "archive.json")
        self.assertEqual(packet["advisoryMetrics"][0]["name"], "shadow_win_rate_confidence")
        self.assertFalse(packet["guardrails"]["affectsScoring"])

    def test_packet_outputs_are_explicit_json_and_markdown(self) -> None:
        packets = build_shadow_review_packets(batch_evaluation=sample_batch_eval())
        markdown = packet_markdown(packets[0])

        self.assertIn("Shadow Review Packet", markdown)
        self.assertIn("sidecar_only", markdown)

        with tempfile.TemporaryDirectory() as tmp:
            index = write_shadow_review_packets(packets, tmp)
            self.assertEqual(index["indexType"], INDEX_TYPE)
            self.assertEqual(index["packetCount"], 1)
            packet_json = Path(index["packetPaths"][0]["json"])
            self.assertTrue(packet_json.exists())
            self.assertTrue((Path(tmp) / "shadow_review_packet_index_latest.json").exists())

    def test_cli_generates_packet_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch_json = Path(tmp) / "batch.json"
            batch_json.write_text(json.dumps(sample_batch_eval()), encoding="utf-8")
            output_dir = Path(tmp) / "packets"
            exit_code = main(
                [
                    "--batch-evaluation-json",
                    str(batch_json),
                    "--output-dir",
                    str(output_dir),
                    "--quiet",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(list(output_dir.glob("shadow_review_packet_index_*.json")))

    def test_packet_tool_is_not_imported_by_runtime_paths(self) -> None:
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
            self.assertNotIn("generate_shadow_review_packets", source)


if __name__ == "__main__":
    unittest.main()
