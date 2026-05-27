from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from tools.indexer_target_resolver_preflight import (
    GATE_BLOCKED_MISSING_APPROVAL,
    GATE_BLOCKED_MISSING_VALID_TARGETS,
    GATE_READY,
    main,
    run_resolver_preflight,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-05-27T09:10:00+00:00")


class IndexerTargetResolverPreflightTests(unittest.TestCase):
    def test_missing_live_approval_blocks_before_client_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = _write_registry(Path(tmp) / "registry.json")
            client = _FakeClient(markets={"anchor-a": _market("anchor-a", "cond-a")})

            report = run_resolver_preflight(registry, allow_live_network=False, client=client, now=NOW)

            self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED_MISSING_APPROVAL)
            self.assertEqual(client.calls, [])
            self.assertFalse(report["networkUsed"])

    def test_selects_two_anchors_and_first_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = _write_registry(Path(tmp) / "registry.json")
            client = _FakeClient(
                markets={
                    "anchor-a": _market("anchor-a", "cond-a"),
                    "anchor-b": _market("anchor-b", "cond-b"),
                    "replacement-a": _market("replacement-a", "cond-c"),
                    "sparse-fallback": _market("sparse-fallback", "cond-d"),
                }
            )

            report = run_resolver_preflight(registry, allow_live_network=True, client=client, now=NOW)

            self.assertEqual(report["summary"]["gateDecision"], GATE_READY)
            self.assertEqual(report["summary"]["selectedMarketSlugs"], ["anchor-a", "anchor-b", "replacement-a"])
            self.assertEqual(report["summary"]["selectedConditionIds"], ["cond-a", "cond-b", "cond-c"])
            self.assertEqual(report["summary"]["replacementSelected"], "replacement-a")
            self.assertFalse(report["tradeIngestion"])
            self.assertFalse(report["sqliteWritten"])

    def test_rejects_multi_market_event_and_still_selects_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = _write_registry(Path(tmp) / "registry.json")
            client = _FakeClient(
                markets={
                    "anchor-a": _market("anchor-a", "cond-a"),
                    "anchor-b": _market("anchor-b", "cond-b"),
                    "replacement-a": _market("replacement-a", "cond-c"),
                },
                events={"failed-event": {"slug": "failed-event", "markets": [_market("x", "x"), _market("y", "y")]}}
            )

            report = run_resolver_preflight(registry, allow_live_network=True, client=client, now=NOW)

            failed = _result_by_slug(report, "failed-event")
            self.assertEqual(failed["status"], "rejected")
            self.assertEqual(failed["rejectReason"], "target_exceeds_bounds_or_not_single_market")
            self.assertEqual(report["summary"]["gateDecision"], GATE_READY)
            self.assertEqual(report["summary"]["selectedMarketSlugs"], ["anchor-a", "anchor-b", "replacement-a"])

    def test_falls_back_to_sparse_control_when_first_replacement_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = _write_registry(Path(tmp) / "registry.json")
            client = _FakeClient(
                markets={
                    "anchor-a": _market("anchor-a", "cond-a"),
                    "anchor-b": _market("anchor-b", "cond-b"),
                    "sparse-fallback": _market("sparse-fallback", "cond-d"),
                }
            )

            report = run_resolver_preflight(registry, allow_live_network=True, client=client, now=NOW)

            self.assertEqual(report["summary"]["gateDecision"], GATE_READY)
            self.assertEqual(report["summary"]["selectedMarketSlugs"], ["anchor-a", "anchor-b", "sparse-fallback"])
            self.assertEqual(report["summary"]["replacementSelected"], "sparse-fallback")

    def test_blocks_when_three_valid_targets_are_not_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = _write_registry(Path(tmp) / "registry.json")
            client = _FakeClient(markets={"anchor-a": _market("anchor-a", "cond-a")})

            report = run_resolver_preflight(registry, allow_live_network=True, client=client, now=NOW)

            self.assertEqual(report["summary"]["gateDecision"], GATE_BLOCKED_MISSING_VALID_TARGETS)
            self.assertEqual(report["summary"]["blockedReason"], "preferred_anchor_failed_preflight")

    def test_cli_writes_output_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = _write_registry(Path(tmp) / "registry.json")
            output_path = Path(tmp) / "preflight.json"

            with redirect_stdout(StringIO()):
                exit_code = main(
                    [
                        "--registry-json",
                        str(registry),
                        "--output-json",
                        str(output_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reportType"], "indexer_target_resolver_preflight")
            self.assertEqual(payload["summary"]["gateDecision"], GATE_BLOCKED_MISSING_APPROVAL)

    def test_preflight_tool_is_not_imported_by_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
            "app/polymarket.py",
            "app/storage.py",
            "app/browser_desktop.py",
            "app/browser_ui.html",
            "app/browser_event_forensic_ui.html",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("indexer_target_resolver_preflight", source)


class _FakeClient:
    def __init__(
        self,
        *,
        markets: dict[str, dict[str, object]] | None = None,
        events: dict[str, dict[str, object]] | None = None,
        pages: dict[str, tuple[dict[str, object] | None, dict[str, object] | None]] | None = None,
    ) -> None:
        self.markets = markets or {}
        self.events = events or {}
        self.pages = pages or {}
        self.calls: list[tuple[str, str]] = []

    def fetch_market_by_slug(self, slug: str) -> dict[str, object] | None:
        self.calls.append(("market", slug))
        return self.markets.get(slug)

    def fetch_event_by_slug(self, slug: str) -> dict[str, object] | None:
        self.calls.append(("event", slug))
        return self.events.get(slug)

    def fetch_event_resolution_from_pages(self, slug: str) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        self.calls.append(("pages", slug))
        return self.pages.get(slug, (None, None))


def _write_registry(path: Path) -> Path:
    payload = {
        "reportType": "indexer_probe_target_registry",
        "preferredAnchors": ["anchor-a", "anchor-b"],
        "replacementPriority": ["replacement-a", "sparse-fallback"],
        "candidates": [
            {
                "slug": "anchor-a",
                "candidateClassification": "preferred_repeat_anchor",
                "priority": 10,
                "liveResolverPreflightNeeded": True,
            },
            {
                "slug": "anchor-b",
                "candidateClassification": "preferred_repeat_anchor",
                "priority": 20,
                "liveResolverPreflightNeeded": True,
            },
            {
                "slug": "failed-event",
                "candidateClassification": "failed_needs_review",
                "priority": 30,
                "liveResolverPreflightNeeded": True,
            },
            {
                "slug": "replacement-a",
                "candidateClassification": "replacement_candidate",
                "priority": 40,
                "liveResolverPreflightNeeded": True,
            },
            {
                "slug": "sparse-fallback",
                "candidateClassification": "sparse_control",
                "priority": 50,
                "liveResolverPreflightNeeded": True,
            },
            {
                "slug": "large-event",
                "candidateClassification": "do_not_use",
                "priority": 90,
                "liveResolverPreflightNeeded": False,
            },
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _market(slug: str, condition_id: str) -> dict[str, object]:
    return {"slug": slug, "conditionId": condition_id, "question": "Fixture?"}


def _result_by_slug(report: dict[str, object], slug: str) -> dict[str, object]:
    for item in report["results"]:
        if isinstance(item, dict) and item.get("slug") == slug:
            return item
    raise AssertionError(f"Missing result for {slug}")


if __name__ == "__main__":
    unittest.main()
