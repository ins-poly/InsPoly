from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.browser_static_assets import (
    is_browser_vendor_asset_path,
    load_browser_vendor_asset,
)


class BrowserStaticAssetTests(unittest.TestCase):
    def test_loads_only_vendor_browser_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "browser"
            asset = root / "react/18.3.1/react.development.js"
            asset.parent.mkdir(parents=True)
            asset.write_text("// react\n", encoding="utf-8")

            payload = load_browser_vendor_asset(
                "/vendor/browser/react/18.3.1/react.development.js",
                vendor_root=root,
            )

        self.assertIsNotNone(payload)
        data, content_type = payload or (b"", "")
        self.assertEqual(data, b"// react\n")
        self.assertEqual(content_type, "text/javascript; charset=utf-8")

    def test_rejects_non_vendor_paths_and_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "browser"
            root.mkdir(parents=True)
            outside = Path(tmp) / "secret.js"
            outside.write_text("// secret\n", encoding="utf-8")

            self.assertFalse(is_browser_vendor_asset_path("/api/bootstrap"))
            self.assertTrue(is_browser_vendor_asset_path("/vendor/browser/react.js"))
            self.assertIsNone(load_browser_vendor_asset("/api/bootstrap", vendor_root=root))
            self.assertIsNone(load_browser_vendor_asset("/vendor/browser/../secret.js", vendor_root=root))
            self.assertIsNone(load_browser_vendor_asset("/vendor/browser/%2e%2e/secret.js", vendor_root=root))
            self.assertIsNone(load_browser_vendor_asset("/vendor/browser/", vendor_root=root))

    def test_json_manifest_content_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "browser"
            manifest = root / "PROVENANCE.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}", encoding="utf-8")

            payload = load_browser_vendor_asset("/vendor/browser/PROVENANCE.json", vendor_root=root)

        self.assertIsNotNone(payload)
        _data, content_type = payload or (b"", "")
        self.assertEqual(content_type, "application/json; charset=utf-8")


if __name__ == "__main__":
    unittest.main()
