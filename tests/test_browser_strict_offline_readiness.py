from __future__ import annotations

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
    def test_repo_currently_reports_asset_policy_blocker_or_better(self) -> None:
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
            (root / "app/vendor").mkdir(parents=True)
            for name in ("react.development.js", "react-dom.development.js", "babel.min.js"):
                (root / "app/vendor" / name).write_text("// local asset\n", encoding="utf-8")
            (root / "app/browser_desktop.py").write_text(
                'if parsed.path == "/": pass\nif parsed.path == "/api/bootstrap": pass\n',
                encoding="utf-8",
            )
            html = root / "app/browser_ui.html"
            html.write_text(
                '<script src="vendor/react.development.js"></script>'
                '<script src="vendor/react-dom.development.js"></script>'
                '<script src="vendor/babel.min.js"></script>'
                '<script type="text/babel">ReactDOM.createRoot(root).render(<App />);</script>',
                encoding="utf-8",
            )

            payload = build_strict_offline_readiness(root, html_files=["app/browser_ui.html"])

        self.assertEqual(payload["gateDecision"], "browser_offline_partial_local_assets_ready")
        self.assertFalse(payload["summary"]["strictOfflineBootPossibleNow"])
        self.assertIn("browser_desktop_static_asset_serving_not_implemented", payload["summary"]["strictOfflineBootBlockedBy"])

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
