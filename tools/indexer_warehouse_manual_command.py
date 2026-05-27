#!/usr/bin/env python3
"""Manual read-only warehouse review command for existing indexer sidecar DBs."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.indexer.warehouse_contract import evaluate_warehouse_w0_contract, retention_policy_status  # noqa: E402
from tools.indexer_sidecar_readiness_audit import audit_indexer_sidecar_readiness  # noqa: E402


REPORT_TYPE = "indexer_warehouse_manual_command"
SCHEMA_VERSION = "indexer_warehouse_manual_command_v1"

GATE_READY = "ready_for_local_warehouse_review"
GATE_MISSING_DB = "blocked_missing_db"
GATE_W0_NOT_READY = "blocked_w0_not_ready"
GATE_SCHEMA_OR_CURSOR_RISK = "blocked_schema_or_cursor_risk"
GATE_EMPTY_OR_LOW_VALUE = "blocked_empty_or_low_value_db"

BLOCKED_RUNTIME_SCOPES = (
    "live_ingestion",
    "scheduler_background_daemon",
    "production_runtime_imports",
    "report_browser_integration",
    "production_storage_schema_migration",
    "saved_report_mutation",
    "scoring_gate_funding_phase3_changes",
    "clob_auth_private_keys_trading_order_placement_external_writes",
)


def run_warehouse_manual_command(
    db_path: str | Path,
    *,
    output_json: str | Path | None = None,
    output_markdown: str | Path | None = None,
    run_summary_json: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Summarize an existing local sidecar DB without mutating it."""

    path = Path(db_path)
    generated_at = (now or datetime.now(tz=UTC)).isoformat()
    run_summary = _read_json_object(run_summary_json) if run_summary_json else None
    report: dict[str, object] = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at,
        "inputDbPath": str(path),
        "runSummaryPath": str(run_summary_json or ""),
        "sidecarOnly": True,
        "readOnly": True,
        "networkUsed": False,
        "inputDbMutated": False,
        "savedReportsMutated": False,
        "productionIntegration": False,
        "backgroundWorker": False,
        "daemonMode": False,
        "externalWrites": False,
        "runtimeImplementationAllowed": False,
        "blockedRuntimeScopes": list(BLOCKED_RUNTIME_SCOPES),
        "readiness": {},
        "warehouseW0": {},
        "contentSummary": _empty_content_summary(),
        "collectionMetadata": {},
        "retention": retention_policy_status(path),
        "findings": [],
        "summary": {
            "gateDecision": "",
            "dbExists": path.exists(),
            "tableCounts": {},
            "marketCount": 0,
            "tradeCount": 0,
            "cursorCount": 0,
            "malformedRawJsonCount": 0,
            "duplicateIndicatorCount": 0,
            "warehouseW0Ready": False,
            "collectionMetadataStatus": "",
            "retentionRecommendation": "keep_raw_db_local_only_delete_output_dir_to_rollback",
            "nextAllowedAction": "",
        },
    }

    if not path.exists():
        _set_gate(report, GATE_MISSING_DB, "select_existing_local_sidecar_db_before_w1_review")
        return _write_outputs(report, output_json=output_json, output_markdown=output_markdown)

    before_mtime = path.stat().st_mtime_ns
    readiness = audit_indexer_sidecar_readiness(path, now=now)
    warehouse_w0 = evaluate_warehouse_w0_contract(readiness, run_summary=run_summary)
    report["readiness"] = readiness
    report["warehouseW0"] = warehouse_w0
    report["collectionMetadata"] = warehouse_w0["collectionMetadataStatus"]
    try:
        content_summary = _read_content_summary(path)
    except sqlite3.Error as exc:
        report["findings"].append(f"sqlite_content_summary_error:{exc}")
        content_summary = _empty_content_summary()
    report["contentSummary"] = content_summary

    after_mtime = path.stat().st_mtime_ns
    report["inputDbMutated"] = before_mtime != after_mtime
    if report["inputDbMutated"]:
        report["findings"].append("input_db_mtime_changed_during_read_only_review")

    readiness_summary = readiness.get("summary") if isinstance(readiness.get("summary"), Mapping) else {}
    table_counts = readiness_summary.get("tableCounts") if isinstance(readiness_summary.get("tableCounts"), Mapping) else {}
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary.update(
        {
            "tableCounts": dict(table_counts),
            "marketCount": int(table_counts.get("indexed_markets") or 0),
            "tradeCount": int(table_counts.get("indexed_trades") or 0),
            "cursorCount": int(readiness_summary.get("cursorCount") or 0),
            "malformedRawJsonCount": int(readiness_summary.get("malformedRawJsonCount") or 0),
            "duplicateIndicatorCount": int(readiness_summary.get("duplicateIndicatorCount") or 0),
            "warehouseW0Ready": bool(warehouse_w0.get("warehouseW0Ready")),
            "collectionMetadataStatus": str(warehouse_w0.get("collectionMetadataStatus", {}).get("status", "")),
        }
    )

    gate = _gate_for_report(
        readiness=readiness,
        warehouse_w0=warehouse_w0,
        content_summary=content_summary,
        input_db_mutated=bool(report["inputDbMutated"]),
    )
    next_action = {
        GATE_READY: "use_summary_for_local_warehouse_review_only_w2_registry_retention_requires_approval",
        GATE_MISSING_DB: "select_existing_local_sidecar_db_before_w1_review",
        GATE_W0_NOT_READY: "resolve_w0_blocking_reasons_before_w1_review",
        GATE_SCHEMA_OR_CURSOR_RISK: "repair_schema_cursor_or_raw_payload_risk_before_w1_review",
        GATE_EMPTY_OR_LOW_VALUE: "use_richer_sidecar_db_or_fixture_before_w1_review",
    }[gate]
    _set_gate(report, gate, next_action)
    return _write_outputs(report, output_json=output_json, output_markdown=output_markdown)


def _gate_for_report(
    *,
    readiness: Mapping[str, object],
    warehouse_w0: Mapping[str, object],
    content_summary: Mapping[str, object],
    input_db_mutated: bool,
) -> str:
    if input_db_mutated:
        return GATE_SCHEMA_OR_CURSOR_RISK
    if not bool(warehouse_w0.get("warehouseW0Ready")):
        blockers = warehouse_w0.get("warehouseW0BlockingReasons")
        blocker_text = " ".join(str(item) for item in blockers) if isinstance(blockers, Sequence) else ""
        if "cursor" in blocker_text or "schema" in blocker_text or "raw_json" in blocker_text:
            return GATE_SCHEMA_OR_CURSOR_RISK
        return GATE_W0_NOT_READY
    readiness_summary = readiness.get("summary") if isinstance(readiness.get("summary"), Mapping) else {}
    if int(readiness_summary.get("malformedRawJsonCount") or 0):
        return GATE_SCHEMA_OR_CURSOR_RISK
    if int(readiness_summary.get("duplicateIndicatorCount") or 0):
        return GATE_SCHEMA_OR_CURSOR_RISK
    market_count = int(content_summary.get("marketCount") or 0)
    trade_count = int(content_summary.get("tradeCount") or 0)
    if market_count <= 0 or trade_count <= 0:
        return GATE_EMPTY_OR_LOW_VALUE
    return GATE_READY


def _read_content_summary(path: Path) -> dict[str, object]:
    with closing(_connect_read_only(path)) as conn:
        market_rows = conn.execute(
            """
            SELECT condition_id, slug, event_slug, active, closed, updated_at
            FROM indexed_markets
            ORDER BY slug, condition_id
            """
        ).fetchall()
        trade_rows_by_condition = conn.execute(
            """
            SELECT condition_id, COUNT(*) AS count
            FROM indexed_trades
            GROUP BY condition_id
            ORDER BY condition_id
            """
        ).fetchall()
        cursor_rows = conn.execute(
            """
            SELECT source, cursor_key, cursor_value, status, last_error
            FROM indexer_cursors
            ORDER BY source, cursor_key
            """
        ).fetchall()
        orderbook_count = _table_count(conn, "orderbook_snapshots")
        wallet_snapshot_count = _table_count(conn, "wallet_index_snapshots")
        score_history_count = _table_count(conn, "score_history")
    trades_by_condition = {str(row["condition_id"]): int(row["count"]) for row in trade_rows_by_condition}
    markets = [
        {
            "conditionId": str(row["condition_id"]),
            "slug": str(row["slug"]),
            "eventSlug": str(row["event_slug"]),
            "active": bool(row["active"]),
            "closed": bool(row["closed"]),
            "updatedAt": str(row["updated_at"]),
            "tradeRows": trades_by_condition.get(str(row["condition_id"]), 0),
        }
        for row in market_rows
    ]
    return {
        "marketCount": len(markets),
        "tradeCount": sum(trades_by_condition.values()),
        "cursorCount": len(cursor_rows),
        "orderbookSnapshotCount": orderbook_count,
        "walletSnapshotCount": wallet_snapshot_count,
        "scoreHistoryCount": score_history_count,
        "markets": markets[:20],
        "tradesByCondition": trades_by_condition,
        "cursorStates": [
            {
                "source": str(row["source"]),
                "cursorKey": str(row["cursor_key"]),
                "cursorValue": str(row["cursor_value"]),
                "status": str(row["status"]),
                "lastError": str(row["last_error"]),
            }
            for row in cursor_rows
        ],
    }


def _empty_content_summary() -> dict[str, object]:
    return {
        "marketCount": 0,
        "tradeCount": 0,
        "cursorCount": 0,
        "orderbookSnapshotCount": 0,
        "walletSnapshotCount": 0,
        "scoreHistoryCount": 0,
        "markets": [],
        "tradesByCondition": {},
        "cursorStates": [],
    }


def _connect_read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"]) if row is not None else 0


def _read_json_object(path: str | Path | None) -> dict[str, object]:
    if path is None:
        return {}
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("JSON summary root must be an object.")
    return loaded


def _set_gate(report: dict[str, object], gate: str, next_action: str) -> None:
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary["gateDecision"] = gate
    summary["nextAllowedAction"] = next_action


def _write_outputs(
    report: dict[str, object],
    *,
    output_json: str | Path | None,
    output_markdown: str | Path | None,
) -> dict[str, object]:
    if output_json:
        _write_json(report, output_json)
    if output_markdown:
        _write_markdown(report, output_markdown)
    return report


def _write_json(payload: Mapping[str, object], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_markdown(report: Mapping[str, object], output_path: str | Path) -> Path:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    content = report.get("contentSummary") if isinstance(report.get("contentSummary"), Mapping) else {}
    lines = [
        "# Indexer Warehouse Manual Command Summary",
        "",
        f"- Gate: `{summary.get('gateDecision', '')}`",
        f"- DB: `{report.get('inputDbPath', '')}`",
        f"- Markets: `{summary.get('marketCount', 0)}`",
        f"- Trades: `{summary.get('tradeCount', 0)}`",
        f"- Cursors: `{summary.get('cursorCount', 0)}`",
        f"- W0 ready: `{summary.get('warehouseW0Ready', False)}`",
        f"- Collection metadata: `{summary.get('collectionMetadataStatus', '')}`",
        f"- Next action: `{summary.get('nextAllowedAction', '')}`",
        "",
        "## Runtime Boundary",
        "",
        "- Network used: `False`",
        "- Production integration: `False`",
        "- Saved reports mutated: `False`",
        "- Input DB mutated: `False`",
        "",
        "## Market Rows",
        "",
    ]
    markets = content.get("markets") if isinstance(content, Mapping) else []
    if isinstance(markets, Sequence) and markets:
        for item in markets:
            if isinstance(item, Mapping):
                lines.append(
                    f"- `{item.get('slug', '')}` / `{item.get('conditionId', '')}`: "
                    f"`{item.get('tradeRows', 0)}` trade rows"
                )
    else:
        lines.append("- No market rows summarized.")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize an existing indexer sidecar DB for W1 warehouse review.")
    parser.add_argument("--db-path", required=True, help="Existing local indexer sidecar SQLite database.")
    parser.add_argument("--run-summary-json", help="Optional bounded runner summary JSON for collection metadata.")
    parser.add_argument("--output-json", help="Optional compact JSON output path.")
    parser.add_argument("--output-markdown", help="Optional Markdown summary output path.")
    args = parser.parse_args(argv)

    report = run_warehouse_manual_command(
        args.db_path,
        run_summary_json=args.run_summary_json,
        output_json=args.output_json,
        output_markdown=args.output_markdown,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
