#!/usr/bin/env python3
"""Fixture-only dry run for the optional Polymarket indexer sidecar.

This tool intentionally accepts local JSON fixtures only. It does not fetch
network data, start background jobs, or integrate with scanner/archive/event
forensic runtime paths.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.indexer import (  # noqa: E402
    IndexerStorage,
    normalize_data_trade,
    normalize_gamma_market,
    normalize_orderbook_snapshot,
)


def run_fixture_dry_run(
    fixture_path: str | Path,
    db_path: str | Path,
    *,
    summary_json_path: str | Path | None = None,
) -> dict[str, Any]:
    fixture = _read_fixture(Path(fixture_path))
    storage = IndexerStorage(Path(db_path))
    storage.init()

    for cursor in _sequence(fixture.get("cursors")):
        if not isinstance(cursor, Mapping):
            continue
        storage.upsert_cursor(
            source=_text(cursor.get("source")) or "fixture",
            cursor_key=_text(cursor.get("cursor_key") or cursor.get("cursorKey")) or "default",
            cursor_value=_text(cursor.get("cursor_value") or cursor.get("cursorValue")),
            status=_text(cursor.get("status")) or "ok",
            last_error=_text(cursor.get("last_error") or cursor.get("lastError")),
            updated_at=_text(cursor.get("updated_at") or cursor.get("updatedAt")) or None,
        )

    for row in _sequence(fixture.get("markets")):
        if isinstance(row, Mapping):
            storage.upsert_market(normalize_gamma_market(row))

    for row in _sequence(fixture.get("trades")):
        if isinstance(row, Mapping):
            storage.upsert_trade(normalize_data_trade(row, source=_text(row.get("source")) or "fixture"))

    for row in _sequence(fixture.get("orderbooks")):
        if not isinstance(row, Mapping):
            continue
        storage.insert_orderbook_snapshot(
            normalize_orderbook_snapshot(
                row,
                token_id=_text(row.get("token_id") or row.get("tokenId") or row.get("asset")) or "unknown",
                condition_id=_text(row.get("condition_id") or row.get("conditionId")) or "unknown",
                timestamp=_text(row.get("timestamp") or row.get("timestamp_utc") or row.get("updated_at"))
                or "unknown",
            )
        )

    counts = storage.table_counts()
    health = storage.cursor_health()
    summary = {
        "fixturePath": str(fixture_path),
        "dbPath": str(db_path),
        "tableCounts": counts,
        "cursorHealth": [
            {
                "source": item.source,
                "cursorKey": item.cursor_key,
                "status": item.status,
                "isStale": item.is_stale,
                "lastError": item.last_error,
            }
            for item in health
        ],
        "networkUsed": False,
        "productionIntegration": False,
    }
    if summary_json_path is not None:
        output_path = Path(summary_json_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _read_fixture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Fixture root must be a JSON object")
    return payload


def _sequence(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _text(value: object) -> str:
    return str(value).strip() if value not in (None, "") else ""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load a local indexer fixture into a sidecar SQLite DB.")
    parser.add_argument("--fixture-json", required=True, help="Local JSON fixture with markets/trades/orderbooks/cursors.")
    parser.add_argument("--db-path", required=True, help="Target sidecar SQLite path for this dry run.")
    parser.add_argument("--summary-json", help="Optional local path for writing the dry-run JSON summary.")
    args = parser.parse_args(argv)

    summary = run_fixture_dry_run(args.fixture_json, args.db_path, summary_json_path=args.summary_json)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
