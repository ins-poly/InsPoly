from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlparse
import http.client

import app.__main__ as app_main
import app.case_reviewer as case_reviewer
import app.cli as app_cli
import app.browser_desktop as browser_desktop
import app.desktop as desktop
import app.macos_launcher as macos_launcher
from app.archive_scanner import ArchiveResearchScanner
from app.config import AppConfig
from app.config import FUNDING_TRACE_MODE_DISABLED, FUNDING_TRACE_MODE_LIVE_RPC, funding_trace_mode
from app.cli import build_parser
from app.local_server import MAX_JSON_BODY_BYTES, open_local_path, safe_child_path
from app.macos_power import MacSleepAssertion
from app.report_pointer import POINTER_FIELD
from app.models import Market
from app.scanner import Scanner
from app.site_categories import SiteCategory
from app.storage import Storage
from app.topic_rules import available_topics, match_focus_topic


class AppWorkflowContractTests(unittest.TestCase):
    def test_topic_rules_match_selected_world_event_labels(self) -> None:
        match = match_focus_topic(
            "Iran missile strike raises NATO and Ukraine questions",
            selected_topics=("Iran", "War/Ceasefire", "Ukraine"),
        )

        self.assertTrue(match.matched)
        self.assertEqual(match.labels, ("Iran", "War/Ceasefire", "Ukraine"))
        self.assertIn("Politics", available_topics())

    def test_topic_rules_respect_selected_topic_subset(self) -> None:
        match = match_focus_topic(
            "President and senate election market",
            selected_topics=("Iran",),
        )

        self.assertFalse(match.matched)
        self.assertEqual(match.labels, ())

    def test_storage_creates_scan_run_schema_without_flagged_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "inspoly.sqlite"
            storage = Storage(db_path)
            storage.init()
            run_id = storage.create_scan_run(
                started_at="2026-05-06T10:00:00+00:00",
                lookback="4h",
                topic_scope="Politics",
                raw_trade_count=10,
                filtered_trade_count=4,
                flagged_case_count=0,
                report_json_path="/tmp/report.json",
                report_md_path="/tmp/report.md",
            )

            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT lookback, topic_scope, raw_trade_count, flagged_case_count FROM scan_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()

        self.assertEqual(row, ("4h", "Politics", 10, 0))

    def test_cli_parser_keeps_expected_subcommands(self) -> None:
        parser = build_parser()

        self.assertEqual(parser.parse_args(["scan", "--lookback", "12h"]).command, "scan")
        self.assertEqual(parser.parse_args(["inspect-wallet", "--address", "0xabc"]).command, "inspect-wallet")
        self.assertEqual(parser.parse_args(["desktop"]).command, "desktop")
        self.assertEqual(parser.parse_args(["archive-desktop"]).command, "archive-desktop")
        self.assertEqual(parser.parse_args(["event-desktop"]).command, "event-desktop")
        self.assertEqual(parser.parse_args(["macos-app"]).command, "macos-app")

    def test_module_entrypoint_reuses_cli_main_without_launching(self) -> None:
        self.assertIs(app_main.main, app_cli.main)

    def test_pyproject_exposes_inspoly_console_script(self) -> None:
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("[project.scripts]", pyproject)
        self.assertIn('inspoly = "app.cli:main"', pyproject)
        self.assertIn("[tool.setuptools.package-data]", pyproject)
        self.assertIn('"*.html"', pyproject)
        self.assertIn('"vendor/browser/**/*"', pyproject)

    def test_macos_packaging_scripts_cover_local_dmg_and_optional_notarization(self) -> None:
        spec = Path("packaging/InsPoly.spec").read_text(encoding="utf-8")
        entitlements = Path("packaging/entitlements.plist").read_text(encoding="utf-8")
        local_build = Path("tools/build_macos_app.sh").read_text(encoding="utf-8")
        release_build = Path("tools/build_macos_release.sh").read_text(encoding="utf-8")
        validation = Path("tools/validate_macos_release.sh").read_text(encoding="utf-8")
        performance_probe = Path("tools/run_event_forensic_performance_probe.sh").read_text(encoding="utf-8")

        self.assertIn("InsPoly.icns", spec)
        self.assertIn("tools/create_macos_icon.sh", local_build)
        self.assertIn("INSPOLY_MACOS_SIGN_IDENTITY", release_build)
        self.assertIn("--notarize", release_build)
        self.assertIn("no Apple login or password", release_build)
        self.assertNotIn("INSPOLY_NOTARYTOOL_PASSWORD", release_build)
        self.assertNotIn("INSPOLY_NOTARYTOOL_APPLE_ID", release_build)
        self.assertIn("--norsrc --noextattr", release_build)
        self.assertIn("--options runtime", release_build)
        self.assertIn("notarytool submit", release_build)
        self.assertIn("stapler staple", release_build)
        self.assertIn("shasum -a 256", release_build)
        self.assertIn("com.apple.security.cs.disable-library-validation", entitlements)
        self.assertIn("python3 -m unittest discover", validation)
        self.assertIn("tools/public_repo_checks.py --all", validation)
        self.assertIn("hdiutil imageinfo", validation)
        self.assertIn("screen-off long run", validation)
        self.assertIn("acceptable for local builds", validation)
        self.assertIn("event_forensic_performance_inventory.py", performance_probe)
        self.assertIn("does not change scoring", performance_probe)

    def test_case_reviewer_runtime_import_is_packaged(self) -> None:
        source = Path("app/event_forensic_desktop.py").read_text(encoding="utf-8")

        self.assertIsNotNone(case_reviewer.review_event_outputs)
        self.assertIn("from app.case_reviewer import", source)
        self.assertNotIn("from tools.ai_case_reviewer import", source)

    def test_funding_trace_defaults_disabled_until_explicit_opt_in(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(funding_trace_mode(), FUNDING_TRACE_MODE_DISABLED)
        with patch.dict(os.environ, {"INSPOLY_FUNDING_TRACE_MODE": "live_rpc"}, clear=True):
            self.assertEqual(funding_trace_mode(), FUNDING_TRACE_MODE_LIVE_RPC)

    def test_browser_launch_functions_delegate_without_opening_browser(self) -> None:
        with patch.object(browser_desktop, "BrowserDesktopApp") as browser_cls:
            browser_desktop.launch_browser_desktop_app()
        browser_cls.assert_called_once_with()
        browser_cls.return_value.launch.assert_called_once_with()

        with patch.object(browser_desktop, "ArchiveResearchBrowserApp") as archive_cls:
            browser_desktop.launch_archive_research_browser_app()
        archive_cls.assert_called_once_with()
        archive_cls.return_value.launch.assert_called_once_with()

    def test_browser_launch_uses_reusable_server_handle(self) -> None:
        app = browser_desktop.BrowserDesktopApp.__new__(browser_desktop.BrowserDesktopApp)
        handle = Mock()
        handle.url = "http://127.0.0.1:1234"
        handle.label = "InsPoly test UI"

        with (
            patch.object(app, "create_server", return_value=handle),
            patch("app.browser_desktop.webbrowser.open") as open_mock,
            patch("builtins.print"),
        ):
            app.launch()

        open_mock.assert_called_once_with("http://127.0.0.1:1234")
        handle.serve_forever.assert_called_once_with()
        handle.close.assert_called_once_with()

    def test_browser_server_uses_tokenized_url(self) -> None:
        app = browser_desktop.BrowserDesktopApp.__new__(browser_desktop.BrowserDesktopApp)
        app.asset_name = "browser_ui.html"
        app.app_meta = {"launchLabel": "InsPoly test UI"}
        app.session_token = "old-token"

        handle = app.create_server()
        try:
            parsed = urlparse(handle.url)
            self.assertEqual(parsed.hostname, "127.0.0.1")
            self.assertIn("token=", parsed.query)
            self.assertNotEqual(app.session_token, "old-token")
        finally:
            handle.close()

    def test_browser_api_rejects_missing_token(self) -> None:
        app = browser_desktop.BrowserDesktopApp.__new__(browser_desktop.BrowserDesktopApp)
        app.asset_name = "browser_ui.html"
        app.app_meta = {"launchLabel": "InsPoly test UI"}
        app.session_token = "test-token"
        app.load_run = lambda _name: {"ok": True}  # type: ignore[method-assign]
        handle = app.create_server()
        handle.start_background(thread_name="test browser server")
        try:
            parsed = urlparse(handle.url)
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
            conn.request("GET", "/api/run?name=example.json")
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 403)
        finally:
            handle.close()

    def test_browser_api_accepts_session_cookie_and_checks_json_content_type(self) -> None:
        app = browser_desktop.BrowserDesktopApp.__new__(browser_desktop.BrowserDesktopApp)
        app.asset_name = "browser_ui.html"
        app.app_meta = {"launchLabel": "InsPoly test UI"}
        app.session_token = "test-token"
        app.open_exports_dir = lambda: {"ok": True}  # type: ignore[method-assign]
        handle = app.create_server()
        handle.start_background(thread_name="test browser server")
        try:
            parsed = urlparse(handle.url)
            headers = {"Cookie": f"inspoly_session={app.session_token}", "Content-Type": "text/plain"}
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
            conn.request("POST", "/api/open-exports-dir", body="{}", headers=headers)
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 415)

            headers["Content-Type"] = "application/json"
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
            conn.request("POST", "/api/open-exports-dir", body="{}", headers=headers)
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 200)
        finally:
            handle.close()

    def test_browser_api_rejects_forbidden_host_and_origin(self) -> None:
        app = browser_desktop.BrowserDesktopApp.__new__(browser_desktop.BrowserDesktopApp)
        app.asset_name = "browser_ui.html"
        app.app_meta = {"launchLabel": "InsPoly test UI"}
        handle = app.create_server()
        handle.start_background(thread_name="test browser server")
        try:
            parsed = urlparse(handle.url)
            cookie = f"inspoly_session={app.session_token}"
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
            conn.request("GET", "/api/bootstrap", headers={"Cookie": cookie, "Host": "evil.example"})
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 403)

            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
            conn.request(
                "GET",
                "/api/bootstrap",
                headers={"Cookie": cookie, "Origin": "https://evil.example"},
            )
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 403)
        finally:
            handle.close()

    def test_browser_api_rejects_oversized_json_body(self) -> None:
        app = browser_desktop.BrowserDesktopApp.__new__(browser_desktop.BrowserDesktopApp)
        app.asset_name = "browser_ui.html"
        app.app_meta = {"launchLabel": "InsPoly test UI"}
        app.open_exports_dir = lambda: {"ok": True}  # type: ignore[method-assign]
        handle = app.create_server()
        handle.start_background(thread_name="test browser server")
        try:
            parsed = urlparse(handle.url)
            body = json.dumps({"payload": "x" * MAX_JSON_BODY_BYTES})
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
            conn.request(
                "POST",
                "/api/open-exports-dir",
                body=body,
                headers={
                    "Cookie": f"inspoly_session={app.session_token}",
                    "Content-Type": "application/json",
                },
            )
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 413)
        finally:
            handle.close()

    def test_safe_child_path_rejects_report_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "reports"
            root.mkdir()

            with self.assertRaises(ValueError):
                safe_child_path(root, "../outside.json", suffix=".json")

    def test_open_local_path_uses_platform_specific_opener(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.txt"
            path.write_text("ok", encoding="utf-8")

            with patch("app.local_server.subprocess.run") as run_mock:
                open_local_path(path, platform_name="darwin")
            self.assertEqual(run_mock.call_args.args[0][0], "open")

            with patch("app.local_server.subprocess.run") as run_mock:
                open_local_path(path, platform_name="linux")
            self.assertEqual(run_mock.call_args.args[0][0], "xdg-open")

            with patch("app.local_server.os.startfile", create=True) as startfile_mock:
                open_local_path(path, platform_name="win32")
            startfile_mock.assert_called_once_with(str(path.resolve()))

    def test_native_launcher_loads_existing_mode_server_url_inside_shell(self) -> None:
        class FakeApp:
            scan_status = {"running": False}

            def __init__(self, handle: Mock) -> None:
                self._handle = handle

            def create_server(self) -> Mock:
                return self._handle

        handle = Mock()
        handle.url = "http://127.0.0.1:4567"
        factory = Mock(return_value=FakeApp(handle))
        api = macos_launcher.NativeLauncherApi(
            sleep_assertion=MacSleepAssertion(enabled=False),
            poll_interval=0.01,
        )
        api.window = Mock()
        try:
            with patch.dict(macos_launcher.MODE_FACTORIES, {"recent": factory}):
                result = api.launch_mode("recent", keep_awake=True)
        finally:
            api.shutdown()

        self.assertTrue(result["ok"])
        factory.assert_called_once_with()
        handle.start_background.assert_called_once_with(thread_name="InsPoly recent server")
        api.window.evaluate_js.assert_called_once()
        self.assertIn("window.loadWorkspace", api.window.evaluate_js.call_args.args[0])
        self.assertIn("http://127.0.0.1:4567", api.window.evaluate_js.call_args.args[0])
        api.window.load_url.assert_not_called()
        handle.close.assert_called_once_with()

    def test_native_launcher_switch_mode_stops_and_closes_previous_server(self) -> None:
        class FakeApp:
            scan_status = {"running": True}

            def __init__(self, handle: Mock) -> None:
                self._handle = handle
                self.stop_scan = Mock(return_value={"ok": True})

            def create_server(self) -> Mock:
                return self._handle

        first_handle = Mock()
        first_handle.url = "http://127.0.0.1:1111"
        second_handle = Mock()
        second_handle.url = "http://127.0.0.1:2222"
        first_app = FakeApp(first_handle)
        second_app = FakeApp(second_handle)
        api = macos_launcher.NativeLauncherApi(
            sleep_assertion=MacSleepAssertion(enabled=False),
            poll_interval=0.01,
        )
        api.window = Mock()
        try:
            with patch.dict(
                macos_launcher.MODE_FACTORIES,
                {
                    "recent": Mock(return_value=first_app),
                    "archive": Mock(return_value=second_app),
                },
            ):
                self.assertTrue(api.launch_mode("recent", keep_awake=True)["ok"])
                self.assertTrue(api.launch_mode("archive", keep_awake=False)["ok"])
        finally:
            api.shutdown()

        first_app.stop_scan.assert_called_once_with()
        first_handle.close.assert_called_once_with()
        second_handle.close.assert_called_once_with()
        self.assertFalse(api.keep_awake)

    def test_native_launcher_closes_new_server_when_window_load_fails(self) -> None:
        class FakeApp:
            scan_status = {"running": False}

            def __init__(self, handle: Mock) -> None:
                self._handle = handle

            def create_server(self) -> Mock:
                return self._handle

        handle = Mock()
        handle.url = "http://127.0.0.1:4567"
        api = macos_launcher.NativeLauncherApi(sleep_assertion=MacSleepAssertion(enabled=False))
        api.window = Mock()
        api.window.evaluate_js.side_effect = RuntimeError("webview unavailable")
        try:
            with patch.dict(macos_launcher.MODE_FACTORIES, {"recent": Mock(return_value=FakeApp(handle))}):
                result = api.launch_mode("recent", keep_awake=True)
        finally:
            api.shutdown()

        self.assertFalse(result["ok"])
        self.assertIn("native window", str(result["error"]))
        handle.close.assert_called_once_with()

    def test_native_launcher_returns_startup_error_when_server_cannot_start(self) -> None:
        class FakeApp:
            def create_server(self) -> Mock:
                raise OSError("address already in use")

        api = macos_launcher.NativeLauncherApi(sleep_assertion=MacSleepAssertion(enabled=False))
        try:
            with patch.dict(macos_launcher.MODE_FACTORIES, {"recent": Mock(return_value=FakeApp())}):
                result = api.launch_mode("recent", keep_awake=True)
        finally:
            api.shutdown()

        self.assertFalse(result["ok"])
        self.assertIn("could not start", str(result["error"]))
        self.assertIn("OSError", str(result["detail"]))

    def test_native_launcher_controls_stop_outputs_log_and_funding_mode(self) -> None:
        class FakeApp:
            scan_status = {"running": True}

            def __init__(self) -> None:
                self.stop_analysis = Mock(return_value={"ok": True})
                self.open_exports_dir = Mock(return_value={"ok": True})
                self.performance_log_path = Path("event_forensic_outputs") / "performance.log"

        api = macos_launcher.NativeLauncherApi(
            runtime_root=Path.cwd(),
            sleep_assertion=MacSleepAssertion(enabled=False),
        )
        fake_app = FakeApp()
        with api._lock:
            api.current_app = fake_app
            api.current_mode = "event"

        with patch.dict(os.environ, {}, clear=False), patch("app.macos_launcher.open_local_path") as open_mock:
            funding_status = api.set_funding_trace_mode("cache-only")
            stop_result = api.stop_current_analysis()
            outputs_result = api.open_current_outputs()
            log_result = api.open_current_log()

        self.assertEqual(funding_status["fundingTraceMode"], "cache_only")
        self.assertTrue(stop_result["ok"])
        fake_app.stop_analysis.assert_called_once_with()
        self.assertTrue(outputs_result["ok"])
        fake_app.open_exports_dir.assert_called_once_with()
        self.assertTrue(log_result["ok"])
        open_mock.assert_called_once_with(Path.cwd())
        api.shutdown()

    def test_native_launcher_sleep_assertion_tracks_running_status(self) -> None:
        class FakeSleepAssertion:
            def __init__(self) -> None:
                self.active = False
                self.acquire_count = 0
                self.release_count = 0

            def acquire(self) -> bool:
                self.active = True
                self.acquire_count += 1
                return True

            def release(self) -> None:
                self.active = False
                self.release_count += 1

            def status(self) -> dict[str, object]:
                return {"supported": True, "active": self.active, "lastError": None}

        class FakeApp:
            scan_status = {"running": True}

            def __init__(self, handle: Mock) -> None:
                self._handle = handle
                self.stop_scan = Mock(return_value={"ok": True})

            def create_server(self) -> Mock:
                return self._handle

        handle = Mock()
        handle.url = "http://127.0.0.1:4567"
        sleep = FakeSleepAssertion()
        app = FakeApp(handle)
        api = macos_launcher.NativeLauncherApi(sleep_assertion=sleep, poll_interval=0.01)
        try:
            with patch.dict(macos_launcher.MODE_FACTORIES, {"recent": Mock(return_value=app)}):
                self.assertTrue(api.launch_mode("recent", keep_awake=True)["ok"])
                time.sleep(0.04)
                self.assertGreaterEqual(sleep.acquire_count, 1)
                app.scan_status = {"running": False}
                time.sleep(0.04)
                self.assertFalse(sleep.active)
        finally:
            api.shutdown()

    def test_native_launcher_rejects_unknown_mode(self) -> None:
        api = macos_launcher.NativeLauncherApi(sleep_assertion=MacSleepAssertion(enabled=False))

        result = api.launch_mode("missing")
        api.shutdown()

        self.assertFalse(result["ok"])
        self.assertIn("not available", str(result["error"]))

    def test_native_runtime_root_can_be_prepared_explicitly(self) -> None:
        previous_cwd = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                runtime_root = Path(tmp) / "InsPolyRuntime"
                prepared = macos_launcher.prepare_native_runtime_root(runtime_root)

                self.assertEqual(prepared, runtime_root.resolve())
                self.assertEqual(Path.cwd(), runtime_root.resolve())
                self.assertTrue(runtime_root.is_dir())
        finally:
            os.chdir(previous_cwd)

    def test_cli_desktop_command_stays_on_browser_launch_path(self) -> None:
        source = Path(app_cli.__file__).read_text(encoding="utf-8")

        self.assertIn("from app.browser_desktop import launch_browser_desktop_app", source)
        self.assertIn("launch_browser_desktop_app()", source)
        self.assertNotIn("from app.desktop import launch_desktop_app", source)
        self.assertNotIn("launch_desktop_app()", source)

    def test_legacy_tk_launch_function_delegates_without_opening_window(self) -> None:
        with patch.object(desktop, "DesktopApp") as desktop_cls:
            desktop.launch_desktop_app()
        desktop_cls.assert_called_once_with()
        desktop_cls.return_value.run.assert_called_once_with()

    def test_browser_scanner_exposes_entry_probability_for_cards_and_filters(self) -> None:
        app = browser_desktop.BrowserDesktopApp.__new__(browser_desktop.BrowserDesktopApp)
        case = {
            "trade": {
                "trade_id": "trade-1",
                "title": "Will the event happen?",
                "wallet": "0xabcdef1234567890",
                "trader_name": "",
                "trader_pseudonym": "analyst",
                "outcome": "YES",
                "side": "BUY",
                "price": "0.91",
                "timestamp": "2026-05-07T10:00:00+00:00",
                "event_slug": "will-the-event-happen",
            },
            "market": {"site_categories": ["Politics"]},
            "raw_metrics": {
                "trade_notional_usdc": "12500",
                "liquidity_ratio": "3.0%",
                "hours_to_resolution": "12",
                "trade_state": "increase",
                "wallet_traded_market_count": "88",
            },
            "flags": [],
            "severity": "Worth a Look",
            "case_type": None,
            "suspicion_score": 61,
            "explanation": ["Entry was notable."],
            "reasons_against": [],
        }

        payload = app._case_card_payload(case)
        context_lines = [value for _label, value in app._key_context_items(case)]

        self.assertEqual(payload["entryProbability"], 91.0)
        self.assertEqual(payload["entryProbabilityLabel"], "91.0%")
        self.assertEqual(payload["rawTokenPriceLabel"], "Raw token: Yes @ 91.0%")
        self.assertEqual(payload["economicSideProbabilityLabel"], "Economic side: Yes @ 91.0%")
        self.assertEqual(payload["walletPredictions"], 88)
        self.assertEqual(payload["walletPredictionsLabel"], "88")
        self.assertTrue(any("Token price at trade: Raw token: Yes @ 91.0%." in line for line in context_lines))
        self.assertTrue(any("Economic-side probability at trade: Economic side: Yes @ 91.0%." in line for line in context_lines))
        self.assertTrue(any("Wallet public prediction count: 88." in line for line in context_lines))

    def test_browser_scanner_hides_wallets_over_prediction_cap_from_visible_review(self) -> None:
        app = browser_desktop.BrowserDesktopApp.__new__(browser_desktop.BrowserDesktopApp)
        case = {
            "severity": "Strong Risk",
            "trade": {"wallet": "0xwallet"},
            "raw_metrics": {"wallet_traded_market_count": "287"},
            "wallet_inspection": {"traded_market_count": 287},
        }

        self.assertFalse(app._case_passes_wallet_quality(case))

    def test_old_scanner_report_without_side_outcome_fields_still_loads_and_derives_safely(self) -> None:
        app = browser_desktop.BrowserDesktopApp.__new__(browser_desktop.BrowserDesktopApp)
        report = {
            "cases": [
                {
                    "severity": "Worth a Look",
                    "case_type": None,
                    "suspicion_score": 55,
                    "confidence_score": 90,
                    "review_priority": "Medium",
                    "verdict": "Needs review",
                    "trade_count_window": 1,
                    "window_start": "2026-05-07T10:00:00+00:00",
                    "window_end": "2026-05-07T10:00:00+00:00",
                    "trade": {
                        "trade_id": "old-sell-yes",
                        "title": "Old report market",
                        "wallet": "0xabcdef1234567890",
                        "trader_name": "",
                        "trader_pseudonym": "",
                        "outcome": "YES",
                        "side": "SELL",
                        "price": "0.20",
                        "timestamp": "2026-05-07T10:00:00+00:00",
                        "event_slug": "old-report-market",
                    },
                    "market": {"site_categories": []},
                    "wallet_inspection": {},
                    "subscores": {},
                    "flags": [],
                    "explanation": ["Old report row."],
                    "reasons_against": [],
                    "raw_metrics": {
                        "trade_notional_usdc": "1000",
                        "price_implied_probability": "20.0%",
                        "liquidity_ratio": "Unavailable",
                        "trade_state": "increase",
                    },
                }
            ]
        }

        normalized = app._normalize_report(report)
        payload = app._case_card_payload(normalized["cases"][0])

        self.assertNotIn("raw_token_price_label", normalized["cases"][0]["raw_metrics"])
        self.assertEqual(payload["entryProbability"], 20.0)
        self.assertEqual(payload["rawTokenPriceLabel"], "Raw token: Yes @ 20.0%")
        self.assertEqual(payload["economicSideProbabilityLabel"], "Economic side: No @ 80.0%")

    def test_scanner_report_writer_keeps_pointer_absent_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports_dir = root / "reports"
            outputs_dir = root / "outputs"
            reports_dir.mkdir()
            outputs_dir.mkdir()
            scanner = Scanner(
                client=object(),
                storage=object(),
                config=AppConfig(
                    data_dir=root,
                    db_path=root / "db.sqlite3",
                    reports_dir=reports_dir,
                    outputs_dir=outputs_dir,
                ),
            )
            report = {
                "generated_at": "2026-05-27T00:00:00+00:00",
                "lookback": "48h",
                "topic_scope": "Politics",
                "raw_trade_count": 0,
                "filtered_trade_count": 0,
                "candidate_trade_count": 0,
                "flagged_case_count": 0,
                "status": "completed",
                "funding_resolver_health": {},
                "cases": [],
            }

            json_path, _md_path, _txt_path = scanner._write_report_files(
                datetime(2026, 5, 27, 10, 0, 0, tzinfo=UTC),
                reports_dir,
                report,
            )
            payload = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertNotIn(POINTER_FIELD, payload)

    def test_scanner_report_writer_persists_explicit_pointer_only(self) -> None:
        pointer = {
            "artifactType": "indexer_warehouse_query",
            "artifactPath": "validation_outputs/inspoly_indexer_warehouse_w3_query_run_20260527.json",
            "artifactId": "w3-query-run",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports_dir = root / "reports"
            outputs_dir = root / "outputs"
            reports_dir.mkdir()
            outputs_dir.mkdir()
            scanner = Scanner(
                client=object(),
                storage=object(),
                config=AppConfig(
                    data_dir=root,
                    db_path=root / "db.sqlite3",
                    reports_dir=reports_dir,
                    outputs_dir=outputs_dir,
                ),
            )
            report = {
                "generated_at": "2026-05-27T00:00:00+00:00",
                "lookback": "48h",
                "topic_scope": "Politics",
                "raw_trade_count": 0,
                "filtered_trade_count": 0,
                "candidate_trade_count": 0,
                "flagged_case_count": 0,
                "status": "completed",
                "funding_resolver_health": {},
                "cases": [],
            }

            json_path, _md_path, _txt_path = scanner._write_report_files(
                datetime(2026, 5, 27, 10, 0, 1, tzinfo=UTC),
                reports_dir,
                report,
                indexer_warehouse_pointer=pointer,
            )
            payload = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertIn(POINTER_FIELD, payload)
        self.assertIn(POINTER_FIELD, report)
        self.assertFalse(payload[POINTER_FIELD]["metricsCopied"])
        self.assertFalse(payload[POINTER_FIELD]["scoringEffect"])
        self.assertFalse(payload[POINTER_FIELD]["routingEffect"])
        self.assertFalse(payload[POINTER_FIELD]["uiRequired"])

    def test_archive_report_writer_persists_explicit_pointer_only(self) -> None:
        pointer = {
            "artifactType": "indexer_warehouse_query",
            "artifactPath": "validation_outputs/inspoly_indexer_warehouse_w3_query_run_20260527.json",
            "artifactId": "w3-query-run",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports_dir = root / "reports"
            outputs_dir = root / "outputs"
            reports_dir.mkdir()
            outputs_dir.mkdir()
            scanner = ArchiveResearchScanner(
                client=object(),
                storage=object(),
                config=AppConfig(
                    data_dir=root,
                    db_path=root / "db.sqlite3",
                    reports_dir=reports_dir,
                    outputs_dir=outputs_dir,
                ),
            )
            report = {
                "generated_at": "2026-05-27T00:00:00+00:00",
                "range_start": "2026-05-26T00:00:00+00:00",
                "range_end": "2026-05-27T00:00:00+00:00",
                "range_hours": 24,
                "topic_scope": "Politics",
                "raw_trade_count": 0,
                "filtered_trade_count": 0,
                "candidate_trade_count": 0,
                "unique_wallet_count": 0,
                "unique_market_count": 0,
                "flagged_case_count": 0,
                "secondary_review_case_count": 0,
                "status": "completed",
                "funding_resolver_health": {},
                "cases": [],
            }

            export_files = scanner._write_report_files(
                datetime(2026, 5, 27, 10, 0, 2, tzinfo=UTC),
                reports_dir,
                report,
                scoped_trades=[],
                candidate_trades=[],
                flagged_cases=[],
                excluded_cases=[],
                strong_risk_diagnostics=[],
                wallet_rollups=[],
                market_rollups=[],
                indexer_warehouse_pointer=pointer,
            )
            payload = json.loads(Path(export_files["report_json_path"]).read_text(encoding="utf-8"))

        self.assertIn(POINTER_FIELD, payload)
        self.assertIn(POINTER_FIELD, report)
        self.assertFalse(payload[POINTER_FIELD]["metricsCopied"])

    def test_browser_payload_ignores_indexer_pointer_metadata(self) -> None:
        app = browser_desktop.BrowserDesktopApp.__new__(browser_desktop.BrowserDesktopApp)
        app.current_output_path = None
        app.config = AppConfig(
            data_dir=Path("."),
            db_path=Path("./ignored.sqlite3"),
            reports_dir=Path("."),
            outputs_dir=Path("."),
        )
        report = {
            "lookback": "48h",
            "topic_scope": "Politics",
            "raw_trade_count": 20,
            "candidate_trade_count": 3,
            "flagged_case_count": 1,
            "generated_at": "2026-05-27T12:00:00+00:00",
            POINTER_FIELD: {
                "artifactType": "indexer_warehouse_query",
                "artifactPath": "validation_outputs/inspoly_indexer_warehouse_w3_query_run_20260527.json",
                "artifactId": "w3-query-run",
                "metricsCopied": False,
                "scoringEffect": False,
                "routingEffect": False,
            },
            "cases": [
                {"severity": "Worth a Look", "case_type": None, "trade": {"slug": "market-one", "title": "Market one?"}}
            ],
        }

        normalized = app._normalize_report(report)
        payload = app._report_payload(normalized, visible_cases=normalized["cases"])

        self.assertIn(POINTER_FIELD, normalized)
        self.assertNotIn(POINTER_FIELD, payload)
        self.assertEqual(payload["visibleFlaggedCaseCount"], 1)

    def test_old_report_without_safe_side_outcome_inputs_stays_unknown_not_zero(self) -> None:
        app = browser_desktop.BrowserDesktopApp.__new__(browser_desktop.BrowserDesktopApp)
        case = {
            "trade": {
                "trade_id": "unknown-side",
                "title": "Unknown side market",
                "wallet": "0xabcdef1234567890",
                "trader_name": "",
                "trader_pseudonym": "",
                "outcome": "",
                "side": "",
                "timestamp": "2026-05-07T10:00:00+00:00",
                "event_slug": "unknown-side",
            },
            "market": {"site_categories": []},
            "raw_metrics": {
                "trade_notional_usdc": "1000",
                "price_implied_probability": "",
                "liquidity_ratio": "Unavailable",
            },
            "flags": [],
            "severity": "Low Risk",
            "case_type": None,
            "suspicion_score": 10,
            "explanation": [],
            "reasons_against": [],
        }

        payload = app._case_card_payload(case)

        self.assertIsNone(payload["entryProbability"])
        self.assertEqual(payload["rawTokenPriceLabel"], "Raw token: unknown")
        self.assertEqual(payload["economicSideProbabilityLabel"], "Economic side: unknown")

    def test_browser_scanner_default_filters_include_system_scope_controls(self) -> None:
        app = browser_desktop.BrowserDesktopApp.__new__(browser_desktop.BrowserDesktopApp)
        app.site_categories = []

        filters = app._default_case_filters()

        self.assertTrue(filters["includeRelatedMarkets"])
        self.assertFalse(filters["includeBlockchain"])
        self.assertEqual(filters["fundingTraceMode"], FUNDING_TRACE_MODE_DISABLED)

    def test_browser_report_payload_distinguishes_saved_and_visible_cases(self) -> None:
        app = browser_desktop.BrowserDesktopApp.__new__(browser_desktop.BrowserDesktopApp)
        app.current_output_path = None
        app.config = AppConfig(
            data_dir=Path("."),
            db_path=Path("./ignored.sqlite3"),
            reports_dir=Path("."),
            outputs_dir=Path("."),
        )
        saved_cases = [
            {"severity": "Worth a Look", "case_type": None, "trade": {"slug": "market-one", "title": "Market one?"}},
            {"severity": "Low Risk", "case_type": None, "trade": {"slug": "market-two", "title": "Market two?"}},
        ]

        payload = app._report_payload(
            {
                "lookback": "48h",
                "topic_scope": "Politics",
                "raw_trade_count": 20,
                "candidate_trade_count": 3,
                "flagged_case_count": 2,
                "generated_at": "2026-05-07T12:00:00+00:00",
                "cases": saved_cases,
            },
            visible_cases=saved_cases[:1],
        )

        self.assertEqual(payload["savedFlaggedCaseCount"], 2)
        self.assertEqual(payload["visibleFlaggedCaseCount"], 1)
        self.assertEqual(payload["serverHiddenCaseCount"], 1)
        self.assertEqual(payload["savedMarketCount"], 2)
        self.assertEqual(payload["visibleMarketCount"], 1)

    def test_browser_scanner_ui_has_entry_probability_filter_contract(self) -> None:
        html = Path("app/browser_ui.html").read_text(encoding="utf-8")

        self.assertIn("maxEntryProbability", html)
        self.assertIn("Max token price %", html)
        self.assertIn("Maximum raw token price percent", html)
        self.assertIn("parseProbabilityFilter", html)
        self.assertIn("Token price", html)
        self.assertNotIn("Entry chance", html)

    def test_browser_scanner_ui_exposes_system_funding_and_case_family_controls(self) -> None:
        html = Path("app/browser_ui.html").read_text(encoding="utf-8")

        self.assertIn("includeRelatedMarkets", html)
        self.assertIn("Include related case-family markets", html)
        self.assertIn("includeBlockchain", html)
        self.assertIn("Include blockchain linkage", html)
        self.assertIn("fundingTraceMode", html)
        self.assertIn("Funding trace mode", html)
        self.assertIn('includeBlockchain: false', html)
        self.assertIn('fundingTraceMode: "disabled"', html)
        self.assertIn('value="live_rpc"', html)
        self.assertIn('value="cache_only"', html)
        self.assertIn('value="disabled"', html)
        self.assertIn("Case-family scope", html)
        self.assertIn("quality-screened visible", html)
        self.assertIn("saved flagged total", html)
        self.assertIn("Base scanner score is the shared InsPoly suspicion score from _score_trade().", html)
        self.assertIn("Trade size", html)
        self.assertIn("pred {card.walletPredictionsLabel", html)

    def test_browser_scanner_ui_exposes_custom_lookback_and_show_all_cards_button(self) -> None:
        html = Path("app/browser_ui.html").read_text(encoding="utf-8")

        self.assertIn("LOOKBACK_PRESETS", html)
        self.assertIn("Custom hours", html)
        self.assertIn('aria-label="Custom lookback hours"', html)
        self.assertIn("lookbackFromHoursInput", html)
        self.assertIn("showAllQualityScreenedLabel", html)
        self.assertIn("quality-screened cards", html)

    def test_recent_scanner_fetches_each_focus_market_separately(self) -> None:
        market_one = Market(
            market_id="market-one",
            condition_id="cond-one",
            slug="market-one",
            question="Market one?",
            category="Politics",
            end_date=None,
            liquidity=Decimal("10000"),
            volume=Decimal("50000"),
            outcomes=["YES", "NO"],
            token_ids=["yes", "no"],
            tags=[],
            site_categories=["Politics"],
        )
        market_two = Market(
            market_id="market-two",
            condition_id="cond-two",
            slug="market-two",
            question="Market two?",
            category="Politics",
            end_date=None,
            liquidity=Decimal("10000"),
            volume=Decimal("50000"),
            outcomes=["YES", "NO"],
            token_ids=["yes", "no"],
            tags=[],
            site_categories=["Politics"],
        )

        class FakeClient:
            def __init__(self) -> None:
                self.recent_trade_condition_calls: list[tuple[str, ...]] = []

            def fetch_focus_markets(self, *, selected_categories):
                return {market_one.condition_id: market_one, market_two.condition_id: market_two}

            def fetch_recent_trades(self, *, cutoff_ts, max_pages, page_size, condition_ids=None):
                self.recent_trade_condition_calls.append(tuple(condition_ids or ()))
                return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = AppConfig(
                data_dir=root,
                db_path=root / "inspoly.sqlite3",
                reports_dir=root / "reports",
                outputs_dir=root / "outputs",
                max_trade_pages=2,
                trade_page_size=5,
            )
            config.ensure_dirs()
            storage = Storage(config.db_path)
            storage.init()
            client = FakeClient()
            report = Scanner(client, storage, config).scan(
                "7d",
                config.reports_dir,
                selected_categories=(SiteCategory(label="Politics", slug="politics", tag_id="1"),),
                include_blockchain=False,
            )

        self.assertEqual(client.recent_trade_condition_calls, [("cond-one",), ("cond-two",)])
        diagnostics = report["trade_collection_diagnostics"]
        self.assertEqual(diagnostics["marketFetchMode"], "per_market_single_condition")
        self.assertEqual(diagnostics["focusMarketCount"], 2)
        self.assertEqual(diagnostics["rawTradeCountMeaning"], "api_loaded_recent_trade_rows_not_total_polymarket_volume")

    def test_recent_scanner_records_failed_market_fetch_without_failing_run(self) -> None:
        market_one = Market(
            market_id="market-one",
            condition_id="cond-one",
            slug="market-one",
            question="Market one?",
            category="Politics",
            end_date=None,
            liquidity=Decimal("10000"),
            volume=Decimal("50000"),
            outcomes=["YES", "NO"],
            token_ids=["yes", "no"],
            tags=[],
            site_categories=["Politics"],
        )
        market_two = Market(
            market_id="market-two",
            condition_id="cond-two",
            slug="market-two",
            question="Market two?",
            category="Politics",
            end_date=None,
            liquidity=Decimal("10000"),
            volume=Decimal("50000"),
            outcomes=["YES", "NO"],
            token_ids=["yes", "no"],
            tags=[],
            site_categories=["Politics"],
        )

        class FakeClient:
            def fetch_focus_markets(self, *, selected_categories):
                return {market_one.condition_id: market_one, market_two.condition_id: market_two}

            def fetch_recent_trades(self, *, cutoff_ts, max_pages, page_size, condition_ids=None):
                if condition_ids == ["cond-one"]:
                    raise ConnectionResetError(54, "Connection reset by peer")
                return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = AppConfig(
                data_dir=root,
                db_path=root / "inspoly.sqlite3",
                reports_dir=root / "reports",
                outputs_dir=root / "outputs",
            )
            config.ensure_dirs()
            storage = Storage(config.db_path)
            storage.init()
            report = Scanner(FakeClient(), storage, config).scan(
                "7d",
                config.reports_dir,
                selected_categories=(SiteCategory(label="Politics", slug="politics", tag_id="1"),),
                include_blockchain=False,
            )

        self.assertEqual(report["status"], "completed")
        diagnostics = report["trade_collection_diagnostics"]
        self.assertEqual(diagnostics["failedMarketFetchCount"], 1)
        self.assertIn("ConnectionResetError", diagnostics["failedMarketFetches"][0]["reason"])
        self.assertIn("partial", diagnostics["partialCollectionWarning"].lower())


if __name__ == "__main__":
    unittest.main()
