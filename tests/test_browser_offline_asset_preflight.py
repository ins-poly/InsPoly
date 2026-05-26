from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.browser_offline_asset_preflight import build_browser_offline_asset_preflight


ROOT = Path(__file__).resolve().parents[1]


class BrowserOfflineAssetPreflightTests(unittest.TestCase):
    def test_preflight_detects_runtime_cdn_assets(self) -> None:
        payload = build_browser_offline_asset_preflight(ROOT)

        self.assertFalse(payload["networkUsed"])
        self.assertFalse(payload["uiRuntimeChanged"])
        self.assertEqual(payload["summary"]["runtimeRequiredMissingLocalAssetCount"], 0)
        self.assertIn(payload["gateDecision"], {"browser_offline_assets_blocked_missing_assets", "browser_offline_assets_ready_for_patch"})

    def test_local_asset_candidate_marks_ready_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app/vendor/browser/react/18.3.1").mkdir(parents=True)
            (root / "app/vendor/browser/react-dom/18.3.1").mkdir(parents=True)
            (root / "app/vendor/browser/babel-standalone/7.29.7").mkdir(parents=True)
            (root / "app/vendor/browser/react/18.3.1/react.development.js").write_text("", encoding="utf-8")
            (root / "app/vendor/browser/react-dom/18.3.1/react-dom.development.js").write_text("", encoding="utf-8")
            (root / "app/vendor/browser/babel-standalone/7.29.7/babel.min.js").write_text("", encoding="utf-8")
            html = root / "ui.html"
            html.write_text(
                '<script src="https://unpkg.com/react@18/umd/react.development.js"></script>'
                '<script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>'
                '<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>',
                encoding="utf-8",
            )

            payload = build_browser_offline_asset_preflight(root, html_files=["ui.html"])

        self.assertEqual(payload["gateDecision"], "browser_offline_assets_ready_for_patch")
        self.assertEqual(payload["summary"]["runtimeRequiredMissingLocalAssetCount"], 0)

    def test_tool_source_has_no_network_imports(self) -> None:
        source = (ROOT / "tools/browser_offline_asset_preflight.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("http.client", source)
        self.assertNotIn("socket", source)


if __name__ == "__main__":
    unittest.main()
