from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app.__main__ as app_main
import app.cli as app_cli
import app.browser_desktop as browser_desktop
import app.desktop as desktop
from app.archive_scanner import ArchiveResearchScanner
from app.config import AppConfig
from app.cli import build_parser
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

    def test_module_entrypoint_reuses_cli_main_without_launching(self) -> None:
        self.assertIs(app_main.main, app_cli.main)

    def test_browser_launch_functions_delegate_without_opening_browser(self) -> None:
        with patch.object(browser_desktop, "BrowserDesktopApp") as browser_cls:
            browser_desktop.launch_browser_desktop_app()
        browser_cls.assert_called_once_with()
        browser_cls.return_value.launch.assert_called_once_with()

        with patch.object(browser_desktop, "ArchiveResearchBrowserApp") as archive_cls:
            browser_desktop.launch_archive_research_browser_app()
        archive_cls.assert_called_once_with()
        archive_cls.return_value.launch.assert_called_once_with()

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
        self.assertTrue(filters["includeBlockchain"])
        self.assertIn(filters["fundingTraceMode"], {"live_rpc", "cache_only", "disabled"})

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
