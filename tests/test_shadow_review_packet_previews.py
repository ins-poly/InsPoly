from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.render_shadow_review_packet_previews import (
    PREVIEW_TYPE,
    main,
    render_shadow_review_packet_previews,
)


ROOT = Path(__file__).resolve().parents[1]


def sample_packet() -> dict[str, object]:
    return {
        "packetType": "shadow_review_packet",
        "schemaVersion": "shadow_review_packet_v1",
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "sourceArtifactPath": "artifact.json",
        "sourceFamily": "archive_report_json",
        "advisoryMetrics": [
            {
                "name": "shadow_win_rate_confidence",
                "status": "available",
                "advisoryLevel": "context",
                "value": "0.25",
            }
        ],
        "qualityNotes": ["duplicates_existing_archive_fields"],
        "guardrails": {
            "affectsScoring": False,
            "affectsLabels": False,
            "affectsRouting": False,
            "affectsReports": False,
            "affectsUi": False,
        },
    }


def write_index(tmp: str) -> Path:
    root = Path(tmp)
    packet_path = root / "packet.json"
    packet_path.write_text(json.dumps(sample_packet()), encoding="utf-8")
    index_path = root / "index.json"
    index_path.write_text(
        json.dumps({"packetPaths": [{"json": str(packet_path), "markdown": str(root / "packet.md")}]}),
        encoding="utf-8",
    )
    return index_path


class ShadowReviewPacketPreviewTests(unittest.TestCase):
    def test_preview_writes_sidecar_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index_path = write_index(tmp)
            output_dir = Path(tmp) / "previews"
            preview = render_shadow_review_packet_previews(packet_index_json=index_path, output_dir=output_dir)
            latest_json = output_dir / "shadow_review_packet_previews_latest.json"
            latest_md = output_dir / "shadow_review_packet_previews_latest.md"
            written = json.loads(latest_json.read_text(encoding="utf-8"))
            markdown = latest_md.read_text(encoding="utf-8")

        self.assertEqual(preview["previewType"], PREVIEW_TYPE)
        self.assertEqual(written["packetCount"], 1)
        self.assertTrue(written["sidecarOnly"])
        self.assertFalse(written["productionIntegration"])
        self.assertFalse(written["networkUsed"])
        self.assertIn("shadow_win_rate_confidence", markdown)
        self.assertNotIn("risk_level", json.dumps(written))
        self.assertNotIn("Strong Risk", markdown)

    def test_cli_generates_preview_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index_path = write_index(tmp)
            output_dir = Path(tmp) / "previews"
            exit_code = main(
                [
                    "--packet-index-json",
                    str(index_path),
                    "--output-dir",
                    str(output_dir),
                    "--quiet",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "shadow_review_packet_previews_latest.json").exists())

    def test_forbidden_production_text_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = sample_packet()
            packet["risk_level"] = "HIGH"
            packet_path = root / "packet.json"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            index_path = root / "index.json"
            index_path.write_text(json.dumps({"packetPaths": [{"json": str(packet_path)}]}), encoding="utf-8")

            with self.assertRaises(ValueError):
                render_shadow_review_packet_previews(packet_index_json=index_path, output_dir=root / "previews")

    def test_preview_tool_is_not_imported_by_runtime_paths(self) -> None:
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
            self.assertNotIn("render_shadow_review_packet_previews", source)


if __name__ == "__main__":
    unittest.main()
