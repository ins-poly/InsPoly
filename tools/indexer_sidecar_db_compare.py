#!/usr/bin/env python3
"""Read-only comparison for two indexer sidecar SQLite DBs."""

from __future__ import annotations

import argparse
import hashlib
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

from tools.indexer_sidecar_readiness_audit import (  # noqa: E402
    EXPECTED_TABLES,
    audit_indexer_sidecar_readiness,
)


REPORT_TYPE = "indexer_sidecar_db_compare"
SCHEMA_VERSION = "indexer_sidecar_db_compare_v1"

MODE_SELF_COMPARE = "self_compare"
MODE_IDEMPOTENT_REPLAY = "idempotent_replay"
MODE_FRESH_LIVE = "fresh_live"
COMPARISON_MODES = (MODE_SELF_COMPARE, MODE_IDEMPOTENT_REPLAY, MODE_FRESH_LIVE)

GATE_READY = "indexer_sidecar_compare_ready_for_repeat_run"
GATE_PROVIDER_DRIFT = "indexer_sidecar_compare_warn_provider_drift"
GATE_STORAGE_RISK = "indexer_sidecar_compare_blocked_storage_risk"
GATE_MISSING_INPUT = "indexer_sidecar_compare_missing_input"

SAMPLE_LIMIT = 20


def compare_indexer_sidecar_dbs(
    base_db: str | Path,
    candidate_db: str | Path,
    *,
    comparison_mode: str,
    trade_row_drift_tolerance_pct: float = 10.0,
    trade_row_drift_tolerance_abs: int = 25,
    scope_market_slugs: Sequence[str] | None = None,
    scope_condition_ids: Sequence[str] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Compare two sidecar DBs without initializing or mutating either file."""

    if comparison_mode not in COMPARISON_MODES:
        raise ValueError(f"unsupported comparison mode: {comparison_mode}")

    generated_at = (now or datetime.now(tz=UTC)).isoformat()
    base_path = Path(base_db)
    candidate_path = Path(candidate_db)
    base_readiness = audit_indexer_sidecar_readiness(base_path, now=now)
    candidate_readiness = audit_indexer_sidecar_readiness(candidate_path, now=now)
    scoped_market_slugs = tuple(str(item).strip() for item in (scope_market_slugs or ()) if str(item).strip())
    scoped_condition_ids = tuple(str(item).strip() for item in (scope_condition_ids or ()) if str(item).strip())
    scope_enabled = bool(scoped_market_slugs or scoped_condition_ids)

    report: dict[str, object] = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at,
        "baseDbPath": str(base_path),
        "candidateDbPath": str(candidate_path),
        "comparisonMode": comparison_mode,
        "sidecarOnly": True,
        "readOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeImplementationAllowed": False,
        "tolerances": {
            "tradeRowDriftTolerancePct": trade_row_drift_tolerance_pct,
            "tradeRowDriftToleranceAbs": trade_row_drift_tolerance_abs,
        },
        "readiness": {
            "base": _readiness_summary(base_readiness),
            "candidate": _readiness_summary(candidate_readiness),
        },
        "scope": _empty_scope_report(
            enabled=scope_enabled,
            market_slugs=scoped_market_slugs,
            condition_ids=scoped_condition_ids,
        ),
        "tableCounts": {},
        "cursorComparison": _empty_entity_comparison(),
        "marketComparison": _empty_entity_comparison(),
        "tradeComparison": {
            "baseCount": 0,
            "candidateCount": 0,
            "rowDelta": 0,
            "allowedRowDrift": 0,
            "missingTradeIdCount": 0,
            "addedTradeIdCount": 0,
            "commonRawHashChangedCount": 0,
            "missingTradeIdSamples": [],
            "addedTradeIdSamples": [],
            "commonRawHashChangedSamples": [],
            "status": "not_compared",
        },
        "rawHashComparison": {
            "marketRawHashChangedCount": 0,
            "tradeRawHashChangedCount": 0,
        },
        "findings": [],
        "summary": {
            "gateDecision": GATE_READY,
            "baseDbExists": base_path.exists(),
            "candidateDbExists": candidate_path.exists(),
            "baseReadinessGate": _gate_from_readiness(base_readiness),
            "candidateReadinessGate": _gate_from_readiness(candidate_readiness),
            "tableCountDriftCount": 0,
            "cursorDriftCount": 0,
            "marketIdentityDriftCount": 0,
            "tradeIdentityDriftCount": 0,
            "rawHashDriftCount": 0,
            "providerDriftCount": 0,
            "storageRiskCount": 0,
            "recommendedNextAction": "compare_completed_no_runtime_integration",
        },
    }

    blocking_readiness = _blocking_readiness_findings(base_readiness, candidate_readiness)
    report["findings"] = list(blocking_readiness)
    if not base_path.exists() or not candidate_path.exists():
        _set_gate(
            report,
            GATE_MISSING_INPUT,
            "select_existing_sidecar_dbs_before_repeat_run_review",
            storage_risk_count=len(blocking_readiness) or 1,
        )
        return report
    if blocking_readiness:
        _set_gate(
            report,
            GATE_STORAGE_RISK,
            "repair_or_replace_sidecar_db_before_repeat_run_review",
            storage_risk_count=len(blocking_readiness),
        )
        return report

    try:
        with closing(_connect_read_only(base_path)) as base_conn:
            with closing(_connect_read_only(candidate_path)) as candidate_conn:
                base_market_rows_all = _market_rows(base_conn)
                candidate_market_rows_all = _market_rows(candidate_conn)
                base_trade_rows_all = _trade_rows(base_conn)
                candidate_trade_rows_all = _trade_rows(candidate_conn)
                scope_report = _resolve_scope(
                    base_market_rows_all,
                    candidate_market_rows_all,
                    market_slugs=scoped_market_slugs,
                    condition_ids=scoped_condition_ids,
                )
                if scope_enabled:
                    condition_scope = set(scope_report["resolvedConditionIds"])
                    base_counts = _scoped_table_counts(base_conn, condition_scope)
                    candidate_counts = _scoped_table_counts(candidate_conn, condition_scope)
                    base_market_rows = _filter_markets_by_condition(base_market_rows_all, condition_scope)
                    candidate_market_rows = _filter_markets_by_condition(candidate_market_rows_all, condition_scope)
                    base_trade_rows = _filter_trades_by_condition(base_trade_rows_all, condition_scope)
                    candidate_trade_rows = _filter_trades_by_condition(candidate_trade_rows_all, condition_scope)
                    report["scope"] = scope_report
                else:
                    base_counts = _table_counts(base_conn)
                    candidate_counts = _table_counts(candidate_conn)
                    base_market_rows = base_market_rows_all
                    candidate_market_rows = candidate_market_rows_all
                    base_trade_rows = base_trade_rows_all
                    candidate_trade_rows = candidate_trade_rows_all
                table_comparison = _compare_table_counts(
                    base_counts,
                    candidate_counts,
                    comparison_mode=comparison_mode,
                )
                cursors = _compare_cursors(
                    _cursor_rows(base_conn),
                    _cursor_rows(candidate_conn),
                    comparison_mode=comparison_mode,
                    scoped=scope_enabled,
                )
                markets = _compare_keyed(
                    base_market_rows,
                    candidate_market_rows,
                    exact_values=comparison_mode in {MODE_SELF_COMPARE, MODE_IDEMPOTENT_REPLAY},
                    identity_fields=("conditionId", "slug", "eventSlug"),
                )
                trades = _compare_trades(
                    base_trade_rows,
                    candidate_trade_rows,
                    comparison_mode=comparison_mode,
                    tolerance_pct=trade_row_drift_tolerance_pct,
                    tolerance_abs=trade_row_drift_tolerance_abs,
                )
    except sqlite3.Error as exc:
        report["findings"].append(f"sqlite_compare_error:{exc}")
        _set_gate(
            report,
            GATE_STORAGE_RISK,
            "repair_or_replace_sidecar_db_before_repeat_run_review",
            storage_risk_count=1,
        )
        return report

    report["tableCounts"] = table_comparison
    report["cursorComparison"] = cursors
    report["marketComparison"] = markets
    report["tradeComparison"] = trades
    report["rawHashComparison"] = {
        "marketRawHashChangedCount": markets["rawHashChangedCount"],
        "tradeRawHashChangedCount": trades["commonRawHashChangedCount"],
    }

    storage_risks: list[str] = []
    provider_drifts: list[str] = []
    scope_detail = report.get("scope", {})
    if isinstance(scope_detail, Mapping) and scope_detail.get("enabled"):
        if scope_detail.get("missingMarketSlugs") or scope_detail.get("missingConditionIds"):
            storage_risks.append("scoped_targets_missing")
        if scope_detail.get("unsupportedCompareReason"):
            storage_risks.append("scoped_compare_unsupported")

    drifted_tables = _drifted_tables(table_comparison)
    if table_comparison["driftCount"]:
        if comparison_mode == MODE_FRESH_LIVE and drifted_tables <= {"indexed_trades"}:
            provider_drifts.append("table_count_drift_allowed_for_fresh_live_review")
        else:
            storage_risks.append("table_count_drift_not_allowed_for_exact_replay")

    if cursors["missingKeyCount"] or cursors["addedKeyCount"]:
        storage_risks.append("cursor_key_set_mismatch")
    if cursors.get("statusErrorChangedCount"):
        storage_risks.append("cursor_status_or_error_mismatch")
    if cursors["valueChangedCount"]:
        if comparison_mode == MODE_FRESH_LIVE or scope_enabled:
            provider_drifts.append("cursor_value_drift_requires_operator_review")
        else:
            storage_risks.append("cursor_value_drift_not_allowed_for_exact_replay")

    if markets["missingKeyCount"] or markets["addedKeyCount"] or markets["identityChangedCount"]:
        storage_risks.append("market_identity_mismatch")
    if markets["rawHashChangedCount"]:
        if comparison_mode == MODE_FRESH_LIVE:
            provider_drifts.append("market_payload_drift_requires_operator_review")
        else:
            storage_risks.append("market_raw_hash_drift_not_allowed_for_exact_replay")

    if trades["status"] == "drift_blocked":
        if scope_enabled and comparison_mode == MODE_FRESH_LIVE:
            provider_drifts.append("scoped_trade_identity_or_row_drift_outside_fresh_live_tolerance")
        else:
            storage_risks.append("trade_identity_or_row_drift_outside_policy")
    elif trades["status"] == "provider_drift_within_tolerance":
        provider_drifts.append("trade_identity_or_row_drift_within_fresh_live_tolerance")
    elif trades["status"] == "exact_drift_blocked":
        storage_risks.append("trade_identity_or_raw_hash_drift_not_allowed_for_exact_replay")

    report["findings"].extend(storage_risks)
    report["findings"].extend(provider_drifts)
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary["tableCountDriftCount"] = table_comparison["driftCount"]
    summary["cursorDriftCount"] = (
        cursors["missingKeyCount"]
        + cursors["addedKeyCount"]
        + cursors["valueChangedCount"]
        + int(cursors.get("statusErrorChangedCount") or 0)
    )
    summary["marketIdentityDriftCount"] = (
        markets["missingKeyCount"] + markets["addedKeyCount"] + markets["identityChangedCount"]
    )
    summary["tradeIdentityDriftCount"] = trades["missingTradeIdCount"] + trades["addedTradeIdCount"]
    summary["rawHashDriftCount"] = markets["rawHashChangedCount"] + trades["commonRawHashChangedCount"]
    summary["providerDriftCount"] = len(provider_drifts)
    summary["storageRiskCount"] = len(storage_risks)

    if storage_risks:
        _set_gate(
            report,
            GATE_STORAGE_RISK,
            "resolve_storage_risk_before_repeat_run_or_warehouse_review",
            storage_risk_count=len(storage_risks),
        )
    elif provider_drifts:
        _set_gate(
            report,
            GATE_PROVIDER_DRIFT,
            "operator_review_provider_drift_before_repeat_run_expansion",
            provider_drift_count=len(provider_drifts),
        )
    else:
        _set_gate(
            report,
            GATE_READY,
            "use_compare_result_as_repeat_run_approval_input_only_no_runtime_integration",
        )

    return report


def write_compare_output(report: Mapping[str, object], output_json: str | Path) -> Path:
    target = Path(output_json)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _connect_read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in EXPECTED_TABLES:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        counts[table] = int(row["count"]) if row is not None else 0
    return counts


def _scoped_table_counts(conn: sqlite3.Connection, condition_ids: set[str]) -> dict[str, int]:
    counts = {table: 0 for table in EXPECTED_TABLES}
    counts["indexer_cursors"] = int(conn.execute("SELECT COUNT(*) AS count FROM indexer_cursors").fetchone()["count"])
    counts["indexed_markets"] = _count_condition_rows(conn, "indexed_markets", condition_ids)
    counts["indexed_trades"] = _count_condition_rows(conn, "indexed_trades", condition_ids)
    counts["orderbook_snapshots"] = _count_condition_rows(conn, "orderbook_snapshots", condition_ids)
    if "wallet_index_snapshots" in EXPECTED_TABLES:
        counts["wallet_index_snapshots"] = int(conn.execute("SELECT COUNT(*) AS count FROM wallet_index_snapshots").fetchone()["count"])
    if "score_history" in EXPECTED_TABLES:
        counts["score_history"] = int(conn.execute("SELECT COUNT(*) AS count FROM score_history").fetchone()["count"])
    return counts


def _count_condition_rows(conn: sqlite3.Connection, table: str, condition_ids: set[str]) -> int:
    if not condition_ids:
        return 0
    placeholders = ",".join("?" for _ in condition_ids)
    row = conn.execute(
        f"SELECT COUNT(*) AS count FROM {table} WHERE condition_id IN ({placeholders})",
        sorted(condition_ids),
    ).fetchone()
    return int(row["count"]) if row is not None else 0


def _compare_table_counts(
    base_counts: Mapping[str, int],
    candidate_counts: Mapping[str, int],
    *,
    comparison_mode: str,
) -> dict[str, object]:
    tables: dict[str, object] = {}
    drift_count = 0
    for table in EXPECTED_TABLES:
        base = int(base_counts.get(table, 0))
        candidate = int(candidate_counts.get(table, 0))
        delta = candidate - base
        status = "match" if delta == 0 else "drift"
        if status == "drift":
            drift_count += 1
        tables[table] = {
            "base": base,
            "candidate": candidate,
            "delta": delta,
            "status": status,
        }
    return {
        "comparisonMode": comparison_mode,
        "driftCount": drift_count,
        "tables": tables,
    }


def _cursor_rows(conn: sqlite3.Connection) -> dict[str, dict[str, object]]:
    rows = conn.execute(
        """
        SELECT source, cursor_key, cursor_value, updated_at, status, last_error
        FROM indexer_cursors
        ORDER BY source, cursor_key
        """
    ).fetchall()
    return {
        f"{row['source']}::{row['cursor_key']}": {
            "source": str(row["source"]),
            "cursorKey": str(row["cursor_key"]),
            "cursorValue": str(row["cursor_value"]),
            "status": str(row["status"]),
            "lastError": str(row["last_error"]),
            "updatedAt": str(row["updated_at"]),
            "identityHash": _hash_payload({"source": row["source"], "cursorKey": row["cursor_key"]}),
            "valueHash": _hash_payload(
                {
                    "cursorValue": row["cursor_value"],
                    "status": row["status"],
                    "lastError": row["last_error"],
                }
            ),
            "rawHash": _hash_payload(dict(row)),
        }
        for row in rows
    }


def _compare_cursors(
    base_rows: Mapping[str, Mapping[str, object]],
    candidate_rows: Mapping[str, Mapping[str, object]],
    *,
    comparison_mode: str,
    scoped: bool,
) -> dict[str, object]:
    base_keys = set(base_rows)
    candidate_keys = set(candidate_rows)
    missing = sorted(base_keys - candidate_keys)
    added = sorted(candidate_keys - base_keys)
    common = sorted(base_keys & candidate_keys)
    cursor_value_changed: list[str] = []
    status_error_changed: list[str] = []
    raw_changed: list[str] = []
    for key in common:
        base = base_rows[key]
        candidate = candidate_rows[key]
        if base.get("cursorValue") != candidate.get("cursorValue"):
            cursor_value_changed.append(key)
        if base.get("status") != candidate.get("status") or base.get("lastError") != candidate.get("lastError"):
            status_error_changed.append(key)
        if base.get("rawHash") != candidate.get("rawHash"):
            raw_changed.append(key)
    exact_values = comparison_mode in {MODE_SELF_COMPARE, MODE_IDEMPOTENT_REPLAY} and not scoped
    return {
        "baseCount": len(base_keys),
        "candidateCount": len(candidate_keys),
        "missingKeyCount": len(missing),
        "addedKeyCount": len(added),
        "identityChangedCount": 0,
        "valueChangedCount": len(cursor_value_changed),
        "statusErrorChangedCount": len(status_error_changed),
        "rawHashChangedCount": len(raw_changed) if exact_values else 0,
        "missingKeySamples": _sample(missing),
        "addedKeySamples": _sample(added),
        "identityChangedSamples": [],
        "valueChangedSamples": _sample(cursor_value_changed),
        "statusErrorChangedSamples": _sample(status_error_changed),
        "rawHashChangedSamples": _sample(raw_changed) if exact_values else [],
    }


def _market_rows(conn: sqlite3.Connection) -> dict[str, dict[str, object]]:
    rows = conn.execute(
        """
        SELECT condition_id, slug, event_slug, question, active, closed, end_date, raw_json, updated_at
        FROM indexed_markets
        ORDER BY condition_id
        """
    ).fetchall()
    markets: dict[str, dict[str, object]] = {}
    for row in rows:
        markets[str(row["condition_id"])] = {
            "conditionId": str(row["condition_id"]),
            "slug": str(row["slug"]),
            "eventSlug": str(row["event_slug"]),
            "question": str(row["question"]),
            "active": int(row["active"]),
            "closed": int(row["closed"]),
            "endDate": str(row["end_date"]),
            "updatedAt": str(row["updated_at"]),
            "identityHash": _hash_payload(
                {
                    "conditionId": row["condition_id"],
                    "slug": row["slug"],
                    "eventSlug": row["event_slug"],
                }
            ),
            "valueHash": _hash_payload(
                {
                    "question": row["question"],
                    "active": row["active"],
                    "closed": row["closed"],
                    "endDate": row["end_date"],
                }
            ),
            "rawHash": _hash_text(str(row["raw_json"])),
        }
    return markets


def _resolve_scope(
    base_markets: Mapping[str, Mapping[str, object]],
    candidate_markets: Mapping[str, Mapping[str, object]],
    *,
    market_slugs: Sequence[str],
    condition_ids: Sequence[str],
) -> dict[str, object]:
    condition_scope = set(condition_ids)
    missing_market_slugs: list[dict[str, object]] = []
    missing_condition_ids: list[dict[str, object]] = []
    for slug in market_slugs:
        base_matches = _conditions_for_slug(base_markets, slug)
        candidate_matches = _conditions_for_slug(candidate_markets, slug)
        condition_scope.update(base_matches)
        condition_scope.update(candidate_matches)
        if not base_matches or not candidate_matches:
            missing_market_slugs.append(
                {
                    "slug": slug,
                    "basePresent": bool(base_matches),
                    "candidatePresent": bool(candidate_matches),
                }
            )
    for condition_id in condition_ids:
        base_present = condition_id in base_markets
        candidate_present = condition_id in candidate_markets
        if not base_present or not candidate_present:
            missing_condition_ids.append(
                {
                    "conditionId": condition_id,
                    "basePresent": base_present,
                    "candidatePresent": candidate_present,
                }
            )
    unsupported_reason = ""
    if (market_slugs or condition_ids) and not condition_scope:
        unsupported_reason = "scope_resolved_no_condition_ids"
    return {
        "enabled": bool(market_slugs or condition_ids),
        "requestedMarketSlugs": list(market_slugs),
        "requestedConditionIds": list(condition_ids),
        "resolvedConditionIds": sorted(condition_scope),
        "missingMarketSlugs": missing_market_slugs,
        "missingConditionIds": missing_condition_ids,
        "unsupportedCompareReason": unsupported_reason,
    }


def _conditions_for_slug(markets: Mapping[str, Mapping[str, object]], slug: str) -> set[str]:
    return {
        str(condition_id)
        for condition_id, row in markets.items()
        if str(row.get("slug") or "") == slug or str(row.get("eventSlug") or "") == slug
    }


def _filter_markets_by_condition(
    markets: Mapping[str, Mapping[str, object]],
    condition_ids: set[str],
) -> dict[str, Mapping[str, object]]:
    return {key: row for key, row in markets.items() if key in condition_ids}


def _trade_rows(conn: sqlite3.Connection) -> dict[str, dict[str, object]]:
    rows = conn.execute(
        """
        SELECT stable_trade_id, transaction_hash, order_hash, condition_id, token_id,
               wallet, side, outcome, size, price, usdc_size, timestamp, source, raw_json
        FROM indexed_trades
        ORDER BY stable_trade_id
        """
    ).fetchall()
    trades: dict[str, dict[str, object]] = {}
    for row in rows:
        trades[str(row["stable_trade_id"])] = {
            "stableTradeId": str(row["stable_trade_id"]),
            "conditionId": str(row["condition_id"]),
            "tokenId": str(row["token_id"]),
            "wallet": str(row["wallet"]),
            "side": str(row["side"]),
            "outcome": str(row["outcome"]),
            "timestamp": str(row["timestamp"]),
            "identityHash": _hash_payload(
                {
                    "stableTradeId": row["stable_trade_id"],
                    "conditionId": row["condition_id"],
                    "tokenId": row["token_id"],
                }
            ),
            "valueHash": _hash_payload(
                {
                    "transactionHash": row["transaction_hash"],
                    "orderHash": row["order_hash"],
                    "wallet": row["wallet"],
                    "side": row["side"],
                    "outcome": row["outcome"],
                    "size": row["size"],
                    "price": row["price"],
                    "usdcSize": row["usdc_size"],
                    "timestamp": row["timestamp"],
                    "source": row["source"],
                }
            ),
            "rawHash": _hash_text(str(row["raw_json"])),
        }
    return trades


def _filter_trades_by_condition(
    trades: Mapping[str, Mapping[str, object]],
    condition_ids: set[str],
) -> dict[str, Mapping[str, object]]:
    return {key: row for key, row in trades.items() if str(row.get("conditionId") or "") in condition_ids}


def _compare_keyed(
    base_rows: Mapping[str, Mapping[str, object]],
    candidate_rows: Mapping[str, Mapping[str, object]],
    *,
    exact_values: bool,
    identity_fields: Sequence[str] | None = None,
) -> dict[str, object]:
    base_keys = set(base_rows)
    candidate_keys = set(candidate_rows)
    missing = sorted(base_keys - candidate_keys)
    added = sorted(candidate_keys - base_keys)
    common = sorted(base_keys & candidate_keys)

    identity_changed: list[str] = []
    value_changed: list[str] = []
    raw_changed: list[str] = []
    for key in common:
        base = base_rows[key]
        candidate = candidate_rows[key]
        if identity_fields is None:
            identity_changed_current = base.get("identityHash") != candidate.get("identityHash")
        else:
            identity_changed_current = any(base.get(field) != candidate.get(field) for field in identity_fields)
        if identity_changed_current:
            identity_changed.append(key)
        if exact_values and base.get("valueHash") != candidate.get("valueHash"):
            value_changed.append(key)
        if exact_values and base.get("rawHash") != candidate.get("rawHash"):
            raw_changed.append(key)
        elif not exact_values and base.get("rawHash") != candidate.get("rawHash"):
            raw_changed.append(key)

    return {
        "baseCount": len(base_keys),
        "candidateCount": len(candidate_keys),
        "missingKeyCount": len(missing),
        "addedKeyCount": len(added),
        "identityChangedCount": len(identity_changed),
        "valueChangedCount": len(value_changed),
        "rawHashChangedCount": len(raw_changed),
        "missingKeySamples": _sample(missing),
        "addedKeySamples": _sample(added),
        "identityChangedSamples": _sample(identity_changed),
        "valueChangedSamples": _sample(value_changed),
        "rawHashChangedSamples": _sample(raw_changed),
    }


def _compare_trades(
    base_trades: Mapping[str, Mapping[str, object]],
    candidate_trades: Mapping[str, Mapping[str, object]],
    *,
    comparison_mode: str,
    tolerance_pct: float,
    tolerance_abs: int,
) -> dict[str, object]:
    base_ids = set(base_trades)
    candidate_ids = set(candidate_trades)
    missing = sorted(base_ids - candidate_ids)
    added = sorted(candidate_ids - base_ids)
    common = sorted(base_ids & candidate_ids)
    raw_changed = [key for key in common if base_trades[key].get("rawHash") != candidate_trades[key].get("rawHash")]
    value_changed = [key for key in common if base_trades[key].get("valueHash") != candidate_trades[key].get("valueHash")]
    base_count = len(base_ids)
    candidate_count = len(candidate_ids)
    row_delta = candidate_count - base_count
    allowed = max(int(tolerance_abs), int(round(base_count * (float(tolerance_pct) / 100.0))))

    exact_has_drift = bool(missing or added or raw_changed or value_changed or row_delta)
    if comparison_mode in {MODE_SELF_COMPARE, MODE_IDEMPOTENT_REPLAY}:
        status = "exact_drift_blocked" if exact_has_drift else "match"
    else:
        drift_magnitude = max(abs(row_delta), len(missing), len(added), len(raw_changed), len(value_changed))
        if drift_magnitude == 0:
            status = "match"
        elif drift_magnitude <= allowed:
            status = "provider_drift_within_tolerance"
        else:
            status = "drift_blocked"

    return {
        "baseCount": base_count,
        "candidateCount": candidate_count,
        "rowDelta": row_delta,
        "allowedRowDrift": allowed,
        "missingTradeIdCount": len(missing),
        "addedTradeIdCount": len(added),
        "commonRawHashChangedCount": len(raw_changed),
        "commonValueChangedCount": len(value_changed),
        "missingTradeIdSamples": _sample(missing),
        "addedTradeIdSamples": _sample(added),
        "commonRawHashChangedSamples": _sample(raw_changed),
        "commonValueChangedSamples": _sample(value_changed),
        "status": status,
    }


def _readiness_summary(report: Mapping[str, object]) -> dict[str, object]:
    summary = report.get("summary", {})
    if not isinstance(summary, Mapping):
        return {}
    keys = (
        "dbExists",
        "schemaStatus",
        "expectedTablesPresent",
        "expectedTablesMissing",
        "tableCounts",
        "cursorCount",
        "staleCursorCount",
        "cursorErrorCount",
        "malformedRawJsonCount",
        "duplicateIndicatorCount",
        "readinessGate",
        "recommendedNextAction",
    )
    return {key: summary.get(key) for key in keys if key in summary}


def _drifted_tables(table_comparison: Mapping[str, object]) -> set[str]:
    tables = table_comparison.get("tables", {})
    if not isinstance(tables, Mapping):
        return set()
    drifted: set[str] = set()
    for table, detail in tables.items():
        if isinstance(detail, Mapping) and detail.get("status") == "drift":
            drifted.add(str(table))
    return drifted


def _gate_from_readiness(report: Mapping[str, object]) -> str:
    summary = report.get("summary", {})
    if isinstance(summary, Mapping):
        return str(summary.get("readinessGate", ""))
    return ""


def _blocking_readiness_findings(
    base_readiness: Mapping[str, object],
    candidate_readiness: Mapping[str, object],
) -> list[str]:
    findings: list[str] = []
    for label, report in (("base", base_readiness), ("candidate", candidate_readiness)):
        summary = report.get("summary", {})
        if not isinstance(summary, Mapping):
            findings.append(f"{label}:missing_readiness_summary")
            continue
        if not summary.get("dbExists"):
            findings.append(f"{label}:db_missing")
        if summary.get("schemaStatus") != "complete":
            findings.append(f"{label}:schema_not_complete")
        if int(summary.get("expectedTablesMissing") or 0):
            findings.append(f"{label}:expected_tables_missing")
        if int(summary.get("malformedRawJsonCount") or 0):
            findings.append(f"{label}:malformed_raw_json")
        if int(summary.get("duplicateIndicatorCount") or 0):
            findings.append(f"{label}:duplicate_indicators")
        if int(summary.get("cursorErrorCount") or 0):
            findings.append(f"{label}:cursor_errors")
    return findings


def _set_gate(
    report: dict[str, object],
    gate: str,
    action: str,
    *,
    storage_risk_count: int | None = None,
    provider_drift_count: int | None = None,
) -> None:
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary["gateDecision"] = gate
    summary["recommendedNextAction"] = action
    if storage_risk_count is not None:
        summary["storageRiskCount"] = storage_risk_count
    if provider_drift_count is not None:
        summary["providerDriftCount"] = provider_drift_count


def _empty_entity_comparison() -> dict[str, object]:
    return {
        "baseCount": 0,
        "candidateCount": 0,
        "missingKeyCount": 0,
        "addedKeyCount": 0,
        "identityChangedCount": 0,
        "valueChangedCount": 0,
        "statusErrorChangedCount": 0,
        "rawHashChangedCount": 0,
        "missingKeySamples": [],
        "addedKeySamples": [],
        "identityChangedSamples": [],
        "valueChangedSamples": [],
        "statusErrorChangedSamples": [],
        "rawHashChangedSamples": [],
    }


def _empty_scope_report(*, enabled: bool, market_slugs: Sequence[str], condition_ids: Sequence[str]) -> dict[str, object]:
    return {
        "enabled": enabled,
        "requestedMarketSlugs": list(market_slugs),
        "requestedConditionIds": list(condition_ids),
        "resolvedConditionIds": [],
        "missingMarketSlugs": [],
        "missingConditionIds": [],
        "unsupportedCompareReason": "",
    }


def _hash_payload(payload: Mapping[str, object]) -> str:
    return _hash_text(json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str))


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sample(values: Sequence[str]) -> list[str]:
    return list(values[:SAMPLE_LIMIT])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-db", required=True, help="Existing sidecar DB used as the baseline.")
    parser.add_argument("--candidate-db", required=True, help="Candidate sidecar DB to compare.")
    parser.add_argument("--comparison-mode", required=True, choices=COMPARISON_MODES)
    parser.add_argument("--output-json", help="Optional path for the compact compare report.")
    parser.add_argument("--trade-row-drift-tolerance-pct", type=float, default=10.0)
    parser.add_argument("--trade-row-drift-tolerance-abs", type=int, default=25)
    parser.add_argument("--scope-market-slug", action="append", default=[], help="Limit comparison to this market slug. Repeatable.")
    parser.add_argument("--scope-condition-id", action="append", default=[], help="Limit comparison to this condition ID. Repeatable.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = compare_indexer_sidecar_dbs(
        args.base_db,
        args.candidate_db,
        comparison_mode=args.comparison_mode,
        trade_row_drift_tolerance_pct=args.trade_row_drift_tolerance_pct,
        trade_row_drift_tolerance_abs=args.trade_row_drift_tolerance_abs,
        scope_market_slugs=args.scope_market_slug,
        scope_condition_ids=args.scope_condition_id,
    )
    if args.output_json:
        write_compare_output(report, args.output_json)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
