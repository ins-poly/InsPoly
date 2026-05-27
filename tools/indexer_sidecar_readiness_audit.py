#!/usr/bin/env python3
"""Read-only readiness audit for an existing indexer sidecar SQLite DB."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.indexer.warehouse_contract import evaluate_warehouse_w0_contract


REPORT_TYPE = "indexer_sidecar_readiness_audit"
SCHEMA_VERSION = "indexer_sidecar_readiness_audit_v1"

EXPECTED_TABLES = (
    "indexer_cursors",
    "indexed_markets",
    "indexed_trades",
    "orderbook_snapshots",
    "wallet_index_snapshots",
    "score_history",
)

RAW_JSON_COLUMNS = (
    ("indexed_markets", "raw_json"),
    ("indexed_trades", "raw_json"),
    ("orderbook_snapshots", "raw_json"),
    ("wallet_index_snapshots", "raw_profile_json"),
    ("score_history", "raw_metrics_json"),
)


def audit_indexer_sidecar_readiness(
    db_path: str | Path,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 3600,
) -> dict[str, object]:
    """Inspect an existing sidecar DB without initializing or mutating it."""

    path = Path(db_path)
    generated_at = (now or datetime.now(tz=UTC)).isoformat()
    base: dict[str, object] = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at,
        "dbPath": str(path),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "readOnly": True,
        "runtimeImplementationAllowed": False,
    }
    if not path.exists():
        return _with_warehouse_w0({
            **base,
            "schema": _empty_schema("missing_db"),
            "summary": {
                "dbExists": False,
                "schemaStatus": "missing_db",
                "expectedTablesPresent": 0,
                "expectedTablesMissing": len(EXPECTED_TABLES),
                "tableCounts": {},
                "cursorCount": 0,
                "staleCursorCount": 0,
                "cursorErrorCount": 0,
                "malformedRawJsonCount": 0,
                "duplicateIndicatorCount": 0,
                "readinessGate": "indexer_sidecar_db_missing",
                "recommendedNextAction": "create_or_select_existing_sidecar_db_before_live_indexer_review",
            },
            "cursorHealth": [],
            "duplicateIndicators": {},
            "malformedRawJson": {},
        })

    now = now or datetime.now(tz=UTC)
    try:
        with closing(_connect_read_only(path)) as conn:
            tables = _existing_tables(conn)
            missing = [table for table in EXPECTED_TABLES if table not in tables]
            present = [table for table in EXPECTED_TABLES if table in tables]
            table_counts = {table: _table_count(conn, table) for table in present}
            cursor_health = _cursor_health(conn, now=now, stale_after_seconds=stale_after_seconds) if "indexer_cursors" in tables else []
            malformed = _malformed_raw_json_counts(conn, tables)
            duplicates = _duplicate_indicators(conn, tables)
    except sqlite3.Error as exc:
        return _with_warehouse_w0({
            **base,
            "schema": _empty_schema("sqlite_open_error"),
            "summary": {
                "dbExists": True,
                "schemaStatus": "sqlite_open_error",
                "sqliteError": str(exc),
                "expectedTablesPresent": 0,
                "expectedTablesMissing": len(EXPECTED_TABLES),
                "tableCounts": {},
                "cursorCount": 0,
                "staleCursorCount": 0,
                "cursorErrorCount": 0,
                "malformedRawJsonCount": 0,
                "duplicateIndicatorCount": 0,
                "readinessGate": "indexer_sidecar_db_unreadable",
                "recommendedNextAction": "repair_or_replace_sidecar_db_before_live_indexer_review",
            },
            "cursorHealth": [],
            "duplicateIndicators": {},
            "malformedRawJson": {},
        })

    stale_count = sum(1 for item in cursor_health if item["isStale"])
    error_count = sum(1 for item in cursor_health if item["status"] not in {"ok", "idle"} or item["lastError"])
    malformed_count = sum(int(value) for value in malformed.values())
    duplicate_count = sum(int(value) for value in duplicates.values())
    schema_status = "complete" if not missing else "missing_tables"
    gate, action = _readiness_gate(
        missing=missing,
        table_counts=table_counts,
        stale_cursor_count=stale_count,
        cursor_error_count=error_count,
        malformed_raw_json_count=malformed_count,
        duplicate_indicator_count=duplicate_count,
    )
    return _with_warehouse_w0({
        **base,
        "schema": {
            "status": schema_status,
            "expectedTables": list(EXPECTED_TABLES),
            "presentTables": present,
            "missingTables": missing,
        },
        "summary": {
            "dbExists": True,
            "schemaStatus": schema_status,
            "expectedTablesPresent": len(present),
            "expectedTablesMissing": len(missing),
            "tableCounts": table_counts,
            "cursorCount": len(cursor_health),
            "staleCursorCount": stale_count,
            "cursorErrorCount": error_count,
            "malformedRawJsonCount": malformed_count,
            "duplicateIndicatorCount": duplicate_count,
            "readinessGate": gate,
            "recommendedNextAction": action,
        },
        "cursorHealth": cursor_health,
        "duplicateIndicators": duplicates,
        "malformedRawJson": malformed,
    })


def write_audit_output(report: Mapping[str, object], output_json: str | Path) -> Path:
    target = Path(output_json)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _with_warehouse_w0(report: dict[str, object]) -> dict[str, object]:
    warehouse_w0 = evaluate_warehouse_w0_contract(report)
    report["warehouseW0"] = warehouse_w0
    summary = report.get("summary")
    if isinstance(summary, dict):
        summary["warehouseW0Ready"] = warehouse_w0["warehouseW0Ready"]
        summary["warehouseW0BlockingReasons"] = warehouse_w0["warehouseW0BlockingReasons"]
        summary["tableContractStatus"] = warehouse_w0["tableContractStatus"]["status"]
        summary["cursorContractStatus"] = warehouse_w0["cursorContractStatus"]["status"]
        summary["collectionMetadataStatus"] = warehouse_w0["collectionMetadataStatus"]["status"]
        summary["retentionPolicyStatus"] = warehouse_w0["retentionPolicyStatus"]["status"]
    return report


def _connect_read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row["name"]) for row in rows}


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"]) if row is not None else 0


def _cursor_health(
    conn: sqlite3.Connection,
    *,
    now: datetime,
    stale_after_seconds: int,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT source, cursor_key, cursor_value, updated_at, status, last_error
        FROM indexer_cursors
        ORDER BY source, cursor_key
        """
    ).fetchall()
    health: list[dict[str, object]] = []
    for row in rows:
        updated_at = str(row["updated_at"] or "")
        parsed = _parse_datetime(updated_at)
        age_seconds = (now - parsed).total_seconds() if parsed is not None else None
        status = str(row["status"] or "")
        last_error = str(row["last_error"] or "")
        is_stale = (
            parsed is None
            or (age_seconds is not None and age_seconds > stale_after_seconds)
            or status not in {"ok", "idle"}
        )
        health.append(
            {
                "source": str(row["source"]),
                "cursorKey": str(row["cursor_key"]),
                "cursorValue": str(row["cursor_value"]),
                "updatedAt": updated_at,
                "status": status,
                "lastError": last_error,
                "ageSeconds": age_seconds,
                "isStale": is_stale,
            }
        )
    return health


def _malformed_raw_json_counts(conn: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, column in RAW_JSON_COLUMNS:
        key = f"{table}.{column}"
        if table not in tables:
            counts[key] = 0
            continue
        bad = 0
        for row in conn.execute(f"SELECT {column} FROM {table}").fetchall():
            try:
                loaded = json.loads(str(row[column]))
            except json.JSONDecodeError:
                bad += 1
                continue
            if not isinstance(loaded, dict):
                bad += 1
        counts[key] = bad
    return counts


def _duplicate_indicators(conn: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    indicators = {
        "duplicateMarketSlugs": 0,
        "duplicateTradeTransactionOrderKeys": 0,
        "duplicateOrderbookTokenConditionTimestamps": 0,
        "duplicateScoreHistoryInputHashes": 0,
    }
    if "indexed_markets" in tables:
        indicators["duplicateMarketSlugs"] = _duplicate_group_count(
            conn,
            """
            SELECT slug, COUNT(*) AS count
            FROM indexed_markets
            WHERE slug != ''
            GROUP BY slug
            HAVING COUNT(*) > 1
            """,
        )
    if "indexed_trades" in tables:
        indicators["duplicateTradeTransactionOrderKeys"] = _duplicate_group_count(
            conn,
            """
            SELECT transaction_hash, order_hash, condition_id, token_id, wallet, side, outcome, timestamp, COUNT(*) AS count
            FROM indexed_trades
            WHERE transaction_hash != '' OR order_hash != ''
            GROUP BY transaction_hash, order_hash, condition_id, token_id, wallet, side, outcome, timestamp
            HAVING COUNT(*) > 1
            """,
        )
    if "orderbook_snapshots" in tables:
        indicators["duplicateOrderbookTokenConditionTimestamps"] = _duplicate_group_count(
            conn,
            """
            SELECT token_id, condition_id, timestamp, COUNT(*) AS count
            FROM orderbook_snapshots
            GROUP BY token_id, condition_id, timestamp
            HAVING COUNT(*) > 1
            """,
        )
    if "score_history" in tables:
        indicators["duplicateScoreHistoryInputHashes"] = _duplicate_group_count(
            conn,
            """
            SELECT subject_type, subject_id, score_type, computed_at, input_hash, COUNT(*) AS count
            FROM score_history
            GROUP BY subject_type, subject_id, score_type, computed_at, input_hash
            HAVING COUNT(*) > 1
            """,
        )
    return indicators


def _duplicate_group_count(conn: sqlite3.Connection, query: str) -> int:
    rows = conn.execute(query).fetchall()
    return sum(int(row["count"]) - 1 for row in rows)


def _readiness_gate(
    *,
    missing: Sequence[str],
    table_counts: Mapping[str, int],
    stale_cursor_count: int,
    cursor_error_count: int,
    malformed_raw_json_count: int,
    duplicate_indicator_count: int,
) -> tuple[str, str]:
    if missing:
        return "indexer_sidecar_readiness_blocked_missing_schema", "restore_or_initialize_sidecar_schema_before_live_indexer_review"
    if malformed_raw_json_count:
        return "indexer_sidecar_readiness_blocked_malformed_json", "repair_sidecar_raw_json_before_warehouse_or_live_indexer_review"
    if cursor_error_count:
        return "indexer_sidecar_readiness_blocked_cursor_errors", "resolve_cursor_errors_before_live_indexer_review"
    if stale_cursor_count:
        return "indexer_sidecar_readiness_warn_stale_cursors", "refresh_or_accept_stale_cursor_state_before_live_indexer_review"
    if sum(table_counts.values()) == 0:
        return "indexer_sidecar_readiness_empty_db", "load_fixture_or_static_sidecar_data_before_live_indexer_review"
    if duplicate_indicator_count:
        return "indexer_sidecar_readiness_warn_duplicate_indicators", "inspect_duplicate_indicators_before_warehouse_review"
    return "indexer_sidecar_readiness_ready_no_runtime", "use_as_operator_review_input_only_live_indexer_still_requires_approval"


def _empty_schema(status: str) -> dict[str, object]:
    return {
        "status": status,
        "expectedTables": list(EXPECTED_TABLES),
        "presentTables": [],
        "missingTables": list(EXPECTED_TABLES),
    }


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit an existing indexer sidecar SQLite DB without mutating it.")
    parser.add_argument("--db-path", required=True, help="Existing indexer sidecar SQLite database.")
    parser.add_argument("--output-json", help="Optional compact JSON output path.")
    parser.add_argument("--stale-after-seconds", type=int, default=3600)
    args = parser.parse_args(argv)

    report = audit_indexer_sidecar_readiness(
        args.db_path,
        stale_after_seconds=args.stale_after_seconds,
    )
    if args.output_json:
        write_audit_output(report, args.output_json)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
