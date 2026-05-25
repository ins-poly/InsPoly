from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app.config import AppConfig
from app.event_forensic import (
    EventForensicAnalyzer,
    ResolvedEvent,
    _resolve_analysis_scope_context,
    _scope_product_metadata,
)
from app.event_forensic_desktop import EventForensicBrowserApp
from app.models import Market
from tools.event_forensic_scope_semantics_audit import (
    REPORT_TYPE,
    build_scope_semantics_audit,
    main as audit_main,
)


ROOT = Path(__file__).resolve().parents[1]


def _market(condition_id: str, slug: str, question: str) -> Market:
    return Market(
        market_id=f"market-{condition_id}",
        condition_id=condition_id,
        slug=slug,
        question=question,
        category="Politics",
        end_date=datetime(2026, 4, 8, tzinfo=UTC).isoformat(),
        liquidity=Decimal("20000"),
        volume=Decimal("60000"),
        outcomes=["YES", "NO"],
        token_ids=["yes", "no"],
        tags=[],
    )


def _resolved_event() -> ResolvedEvent:
    selected = _market("cond-selected", "selected-market", "Selected child market?")
    sibling = _market("cond-sibling", "sibling-market", "Sibling child market?")
    return ResolvedEvent(
        input_value="https://polymarket.com/event/example",
        canonical_url="https://polymarket.com/event/example",
        event_id="event-1",
        event_slug="example-event",
        event_title="Example event",
        event_description="",
        event_category="Politics",
        event_closed=True,
        event_end_date=datetime(2026, 4, 8, tzinfo=UTC).isoformat(),
        source_market_slug=selected.slug,
        source_condition_id=selected.condition_id,
        event_payload={},
        markets={selected.condition_id: selected, sibling.condition_id: sibling},
        market_payloads={selected.condition_id: {}, sibling.condition_id: {}},
        event_family_id="example-event",
        family_tokens={"example"},
    )


class EventForensicScopeSemanticsTests(unittest.TestCase):
    def test_selected_market_scope_metadata_is_context_only(self) -> None:
        resolved = _resolved_event()
        scope_context = _resolve_analysis_scope_context(
            resolved,
            analysis_scope="market",
            selected_condition_id="cond-selected",
            selected_market_slug=None,
        )

        metadata = _scope_product_metadata(resolved, scope_context, include_related_markets=True)

        self.assertEqual(metadata["analysisScope"], "selected_market")
        self.assertEqual(metadata["primaryScoringScope"], "selected_market")
        self.assertEqual(metadata["selectedMarketSlug"], "selected-market")
        self.assertEqual(metadata["selectedMarketQuestion"], "Selected child market?")
        self.assertEqual(metadata["eventSlug"], "example-event")
        self.assertTrue(metadata["relatedMarketsContextIncluded"])
        self.assertFalse(metadata["siblingMarketsPrimaryScored"])
        self.assertIn("context-only", metadata["scopeExplanation"])

    def test_whole_event_scope_metadata_is_explicit(self) -> None:
        resolved = _resolved_event()
        scope_context = _resolve_analysis_scope_context(
            resolved,
            analysis_scope="event",
            selected_condition_id="cond-selected",
            selected_market_slug="selected-market",
        )

        metadata = _scope_product_metadata(resolved, scope_context, include_related_markets=True)

        self.assertEqual(metadata["analysisScope"], "whole_event")
        self.assertEqual(metadata["primaryScoringScope"], "whole_event")
        self.assertEqual(metadata["selectedMarketSlug"], "")
        self.assertTrue(metadata["siblingMarketsPrimaryScored"])
        self.assertIn("Whole-event report", metadata["scopeExplanation"])

    def test_report_summary_gets_additive_scope_fields(self) -> None:
        resolved = _resolved_event()
        scope_context = _resolve_analysis_scope_context(
            resolved,
            analysis_scope="market",
            selected_condition_id="cond-selected",
            selected_market_slug=None,
        )
        analyzer = EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )

        report = analyzer._build_ineligible_report(
            started_at=datetime(2026, 5, 25, tzinfo=UTC),
            resolved=resolved,
            scope_context=scope_context,
            threshold=Decimal("250"),
            eligibility={"eligible": False, "reason": "fixture"},
            include_related_markets=True,
        )

        self.assertEqual(report["analysisScope"], "selected_market")
        self.assertEqual(report["summary"]["analysisScope"], "selected_market")
        self.assertEqual(report["summary"]["primaryScoringScope"], "selected_market")
        self.assertFalse(report["summary"]["siblingMarketsPrimaryScored"])
        self.assertIn("Primary scoring scope: selected_market", report["event_report_markdown"])

    def test_old_report_without_scope_product_fields_loads_safely(self) -> None:
        app = EventForensicBrowserApp.__new__(EventForensicBrowserApp)
        app.analyzer = EventForensicAnalyzer(
            client=object(),
            storage=object(),
            config=AppConfig(
                data_dir=Path("."),
                db_path=Path("./ignored.sqlite3"),
                reports_dir=Path("."),
                outputs_dir=Path("."),
            ),
        )
        app.config = app.analyzer._config
        old_report = {
            "generated_at": "2026-05-25T00:00:00+00:00",
            "status": "completed",
            "event": {
                "title": "Old report",
                "canonicalUrl": "https://polymarket.com/event/old",
                "slug": "old-event",
                "marketCount": 2,
                "analysisMarketCount": 1,
                "completed": True,
            },
            "analysis_scope": "market",
            "selected_market_title": "Old selected market",
            "selected_condition_id": "cond-old",
            "selected_market_slug": "old-market",
            "summary": {"candidate_trade_count": 0, "analysis_market_count": 1, "unique_wallet_count": 0},
            "scope_note": "Old selected-market scope note.",
            "eligibility": {"eligible": True},
            "markets": [],
            "display_trades": [],
            "suspicious_trades": [],
            "display_wallets": [],
            "wallet_clusters": [],
            "related_markets": [],
            "model_gap": {},
            "funding_resolver_health": {},
            "performance": {},
        }

        prepared = app._prepare_report(old_report)

        self.assertIn("event_report_markdown", prepared)
        self.assertIn("Primary scoring scope: selected_market", prepared["event_report_markdown"])
        self.assertNotIn("analysisScope", old_report)

    def test_scope_semantics_audit_reads_local_artifacts_offline(self) -> None:
        report = build_scope_semantics_audit(ROOT, max_files=12, max_bytes=6_000_000)

        self.assertEqual(report["reportType"], REPORT_TYPE)
        self.assertFalse(report["networkUsed"])
        self.assertGreaterEqual(report["summary"]["selectedMarketReportCount"], 1)
        self.assertGreaterEqual(report["summary"]["wholeEventReportCount"], 1)

    def test_scope_semantics_audit_cli_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "scope.json"
            self.assertEqual(
                audit_main(["--root", str(ROOT), "--output", str(output), "--max-files", "12", "--quiet"]),
                0,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["reportType"], REPORT_TYPE)
        self.assertFalse(payload["runtimeBehaviorChanged"])

    def test_browser_copy_contains_explicit_scope_semantics(self) -> None:
        html = (ROOT / "app/browser_event_forensic_ui.html").read_text(encoding="utf-8")

        self.assertIn("function reportScopeSemantics(report)", html)
        self.assertIn("Primary scoring scope:", html)
        self.assertIn("Sibling markets primary-scored:", html)
        self.assertIn("context-only", html)

    def test_scope_semantics_audit_tool_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/browser_desktop.py",
            "app/browser_event_forensic_ui.html",
            "app/storage.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("event_forensic_scope_semantics_audit", source)


if __name__ == "__main__":
    unittest.main()
