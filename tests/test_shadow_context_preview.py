from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.render_shadow_context_preview import render_shadow_context_preview


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "shadow_context_preview" / "input.json"


class ShadowContextPreviewTests(unittest.TestCase):
    def test_preview_writes_advisory_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preview = render_shadow_context_preview(FIXTURE, tmp)
            json_path = Path(preview["outputPaths"][0])
            md_path = Path(preview["outputPaths"][1])

            written = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")

        self.assertEqual(written["previewType"], "shadow_context_advisory")
        self.assertFalse(written["productionIntegration"])
        self.assertFalse(written["networkUsed"])
        self.assertIn("Shadow Context Preview", markdown)
        self.assertNotIn("risk_level", json.dumps(written))
        self.assertNotIn("Strong Risk", markdown)

    def test_preview_tool_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
            "app/browser_desktop.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("render_shadow_context_preview", source)


if __name__ == "__main__":
    unittest.main()
