from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.browser_strict_offline_readiness import (
    REPORT_TYPE,
    build_strict_offline_readiness,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


class BrowserStrictOfflineReadinessTests(unittest.TestCase):
    def test_repo_reports_strict_offline_ready_or_known_blocker(self) -> None:
        payload = build_strict_offline_readiness(ROOT)

        self.assertEqual(payload["reportType"], REPORT_TYPE)
        self.assertFalse(payload["networkUsed"])
        self.assertFalse(payload["uiRuntimeChanged"])
        self.assertIn(
            payload["gateDecision"],
            {
                "browser_strict_offline_ready",
                "browser_offline_partial_local_assets_ready",
                "browser_offline_blocked_requires_asset_policy",
                "browser_offline_no_safe_change",
            },
        )
        self.assertGreaterEqual(payload["summary"]["htmlFileCount"], 2)

    def test_missing_remote_boot_assets_are_hard_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app").mkdir()
            (root / "app/browser_desktop.py").write_text(
                'if parsed.path == "/": pass\nif parsed.path == "/api/bootstrap": pass\n',
                encoding="utf-8",
            )
            html = root / "app/browser_ui.html"
            html.write_text(
                '<script src="https://unpkg.com/react@18/umd/react.development.js"></script>'
                '<script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>'
                '<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>'
                '<script type="text/babel">ReactDOM.createRoot(root).render(<App />);</script>',
                encoding="utf-8",
            )

            payload = build_strict_offline_readiness(root, html_files=["app/browser_ui.html"])

        self.assertEqual(payload["gateDecision"], "browser_offline_blocked_requires_asset_policy")
        self.assertIn("remote_react_reactdom_babel_boot_assets", payload["summary"]["strictOfflineBootBlockedBy"])
        self.assertIn("inline_text_babel_requires_babel_runtime_or_build_pipeline", payload["summary"]["strictOfflineBootBlockedBy"])

    def test_local_assets_without_remote_scripts_are_partial_when_server_lacks_static_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app/vendor/browser/react/18.3.1").mkdir(parents=True)
            (root / "app/vendor/browser/react-dom/18.3.1").mkdir(parents=True)
            (root / "app/vendor/browser/babel-standalone/7.29.7").mkdir(parents=True)
            (root / "app/vendor/browser/react/18.3.1/react.development.js").write_text("// react\n", encoding="utf-8")
            (root / "app/vendor/browser/react-dom/18.3.1/react-dom.development.js").write_text("// react-dom\n", encoding="utf-8")
            (root / "app/vendor/browser/babel-standalone/7.29.7/babel.min.js").write_text("// babel\n", encoding="utf-8")
            (root / "app/browser_desktop.py").write_text(
                'if parsed.path == "/": pass\nif parsed.path == "/api/bootstrap": pass\n',
                encoding="utf-8",
            )
            html = root / "app/browser_ui.html"
            html.write_text(
                '<script src="/vendor/browser/react/18.3.1/react.development.js"></script>'
                '<script src="/vendor/browser/react-dom/18.3.1/react-dom.development.js"></script>'
                '<script src="/vendor/browser/babel-standalone/7.29.7/babel.min.js"></script>'
                '<script type="text/babel">ReactDOM.createRoot(root).render(<App />);</script>',
                encoding="utf-8",
            )

            payload = build_strict_offline_readiness(root, html_files=["app/browser_ui.html"])

        self.assertEqual(payload["gateDecision"], "browser_offline_no_safe_change")
        self.assertFalse(payload["summary"]["strictOfflineBootPossibleNow"])
        self.assertIn("browser_desktop_static_asset_serving_not_implemented", payload["summary"]["strictOfflineBootBlockedBy"])
        self.assertIn("local_vendor_asset_provenance_missing_or_mismatch", payload["summary"]["strictOfflineBootBlockedBy"])

    def test_local_assets_manifest_and_server_enable_strict_offline_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = {
                "app/vendor/browser/react/18.3.1/react.development.js": "// react\n",
                "app/vendor/browser/react-dom/18.3.1/react-dom.development.js": "// react-dom\n",
                "app/vendor/browser/babel-standalone/7.29.7/babel.min.js": "// babel\n",
            }
            for relative, source in assets.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")
            provenance = {
                "schemaVersion": "browser_vendor_provenance_v1",
                "assets": [
                    {
                        "localPath": relative,
                        "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                        "sizeBytes": len(source.encode("utf-8")),
                    }
                    for relative, source in assets.items()
                ],
            }
            (root / "app/vendor/browser/PROVENANCE.json").write_text(json.dumps(provenance), encoding="utf-8")
            server_source = (
                'if parsed.path == "/": pass\n'
                'if parsed.path == "/api/bootstrap": pass\n'
                "load_browser_vendor_asset(parsed.path)\n"
                "is_browser_vendor_asset_path(parsed.path)\n"
            )
            (root / "app/browser_desktop.py").write_text(server_source, encoding="utf-8")
            html = root / "app/browser_ui.html"
            html.write_text(
                '<script src="/vendor/browser/react/18.3.1/react.development.js"></script>'
                '<script src="/vendor/browser/react-dom/18.3.1/react-dom.development.js"></script>'
                '<script src="/vendor/browser/babel-standalone/7.29.7/babel.min.js"></script>'
                '<script type="text/babel">ReactDOM.createRoot(root).render(<App />);</script>',
                encoding="utf-8",
            )

            payload = build_strict_offline_readiness(root, html_files=["app/browser_ui.html"])

        self.assertEqual(payload["gateDecision"], "browser_strict_offline_ready")
        self.assertTrue(payload["summary"]["strictOfflineBootPossibleNow"])
        self.assertEqual(payload["summary"]["strictOfflineBootBlockedBy"], [])

    def test_cli_writes_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "readiness.json"
            self.assertEqual(main(["--root", str(ROOT), "--output", str(output), "--quiet"]), 0)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["reportType"], REPORT_TYPE)
        self.assertFalse(payload["runtimeBehaviorChanged"])

    def test_tool_source_has_no_network_imports(self) -> None:
        source = (ROOT / "tools/browser_strict_offline_readiness.py").read_text(encoding="utf-8")
        self.assertNotIn("requests", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("http.client", source)
        self.assertNotIn("socket", source)


if __name__ == "__main__":
    unittest.main()
