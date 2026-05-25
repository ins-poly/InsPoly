#!/usr/bin/env python3
"""Offline monitor for Polymarket __NEXT_DATA__ fallback payload shape."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.polymarket import _extract_next_data_payload, _market_payload_from_event, _next_data_market_query_slug, _next_data_query_payload


REPORT_TYPE = "gamma_fallback_drift_monitor"
SCHEMA_VERSION = "gamma_fallback_drift_monitor_v1"
DEFAULT_OUTPUT = Path("validation_outputs/gamma_fallback_drift_monitor_20260525.json")


def build_gamma_fallback_drift_monitor(
    root: str | Path = ".",
    *,
    fixture_paths: Sequence[str | Path] | None = None,
) -> dict[str, object]:
    base = Path(root)
    paths = [Path(item) for item in fixture_paths] if fixture_paths is not None else _discover_fixtures(base)
    rows = [_evaluate_fixture(path if path.is_absolute() else base / path, base) for path in paths]
    summary = _summary(rows)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "resolverBehaviorChanged": False,
        "gateDecision": _gate(summary),
        "summary": summary,
        "fixtureRows": rows,
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _discover_fixtures(base: Path) -> list[Path]:
    patterns = (
        "tests/fixtures/gamma_fallback/*",
        "tests/fixtures/**/*next_data*.html",
        "tests/fixtures/**/*next_data*.json",
    )
    paths: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(base.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def _evaluate_fixture(path: Path, base: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return _row(path, base, "load_error", [])
    payload: dict[str, object] | None
    if path.suffix.lower() == ".json":
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            loaded = None
        payload = loaded if isinstance(loaded, dict) else None
    else:
        payload = _extract_next_data_payload(text)
    if payload is None:
        return _row(path, base, "missing_next_data_payload", ["missing_next_data_script_or_json_object"])
    query_slug = _next_data_market_query_slug(payload)
    event_slug = query_slug[0] if query_slug else ""
    market_slug = query_slug[-1] if query_slug else ""
    event_payload = _next_data_query_payload(payload, "/api/event/slug", event_slug) if event_slug else None
    notes: list[str] = []
    if not query_slug:
        notes.append("missing_query_slug")
    if not event_payload:
        notes.append("missing_event_query_payload")
    source_market = _market_payload_from_event(event_payload, market_slug) if event_payload and market_slug else None
    if event_payload and market_slug and not source_market:
        notes.append("source_market_not_found_in_event_payload")
    status = "shape_ok" if not notes else "shape_changed_or_incomplete"
    row = _row(path, base, status, notes)
    row.update(
        {
            "querySlug": query_slug,
            "eventPayloadPresent": bool(event_payload),
            "sourceMarketPresent": bool(source_market),
        }
    )
    return row


def _row(path: Path, base: Path, status: str, notes: Sequence[str]) -> dict[str, object]:
    try:
        relative = str(path.relative_to(base))
    except ValueError:
        relative = str(path)
    return {
        "path": relative,
        "status": status,
        "qualityNotes": list(notes),
    }


def _summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    ok = sum(1 for row in rows if row.get("status") == "shape_ok")
    changed = sum(1 for row in rows if row.get("status") == "shape_changed_or_incomplete")
    return {
        "fixtureCount": len(rows),
        "shapeOkCount": ok,
        "shapeChangedOrIncompleteCount": changed,
        "missingFixtureCount": 1 if not rows else 0,
        "liveFetchPerformed": False,
    }


def _gate(summary: Mapping[str, object]) -> str:
    if int(summary.get("shapeChangedOrIncompleteCount") or 0) > 0:
        return "gamma_fallback_bug_found"
    if int(summary.get("missingFixtureCount") or 0) > 0:
        return "gamma_fallback_needs_live_check"
    return "gamma_fallback_monitor_ready"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--fixture", action="append", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payload = build_gamma_fallback_drift_monitor(args.root, fixture_paths=args.fixture)
    write_json(payload, args.output)
    if not args.quiet:
        print(f"gate: {payload['gateDecision']}")
        print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
