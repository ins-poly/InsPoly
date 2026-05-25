#!/usr/bin/env python3
"""Read-only audit over sidecar orderbook snapshots."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.microstructure_context import summarize_microstructure_snapshots  # noqa: E402


def audit_microstructure_db(
    db_path: str | Path,
    *,
    token_id: str | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    rows = _read_snapshots(Path(db_path), token_id=token_id)
    context = summarize_microstructure_snapshots(rows)
    summary = {
        "dbPath": str(db_path),
        "tokenId": token_id,
        "snapshotCount": len(rows),
        "context": context.to_dict(),
        "networkUsed": False,
        "productionIntegration": False,
    }
    if output_dir is not None:
        target = Path(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        output_path = target / f"microstructure_context_audit_{stamp}.json"
        output_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        summary["outputPath"] = str(output_path)
    return summary


def _read_snapshots(db_path: Path, *, token_id: str | None) -> list[dict[str, object]]:
    query = "SELECT * FROM orderbook_snapshots"
    params: list[object] = []
    if token_id:
        query += " WHERE token_id = ?"
        params.append(token_id)
    query += " ORDER BY timestamp ASC, id ASC"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit microstructure context from a local sidecar DB.")
    parser.add_argument("--db-path", required=True, help="Sidecar SQLite DB path.")
    parser.add_argument("--token-id", help="Optional token id filter.")
    parser.add_argument("--output-dir", help="Optional explicit output directory.")
    args = parser.parse_args(argv)
    summary = audit_microstructure_db(args.db_path, token_id=args.token_id, output_dir=args.output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
