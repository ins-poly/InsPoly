from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.indexer.health import CursorHealth, summarize_cursor_health
from app.indexer.models import (
    IndexedMarket,
    IndexedTrade,
    IndexerCursor,
    OrderbookSnapshot,
    ScoreHistoryEntry,
    WalletIndexSnapshot,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS indexer_cursors (
    source TEXT NOT NULL,
    cursor_key TEXT NOT NULL,
    cursor_value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    last_error TEXT NOT NULL,
    PRIMARY KEY (source, cursor_key)
);

CREATE TABLE IF NOT EXISTS indexed_markets (
    condition_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    event_slug TEXT NOT NULL,
    question TEXT NOT NULL,
    active INTEGER NOT NULL,
    closed INTEGER NOT NULL,
    end_date TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS indexed_trades (
    stable_trade_id TEXT PRIMARY KEY,
    transaction_hash TEXT NOT NULL,
    order_hash TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    wallet TEXT NOT NULL,
    side TEXT NOT NULL,
    outcome TEXT NOT NULL,
    size TEXT NOT NULL,
    price TEXT NOT NULL,
    usdc_size TEXT,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_indexed_trades_wallet ON indexed_trades(wallet);
CREATE INDEX IF NOT EXISTS idx_indexed_trades_condition ON indexed_trades(condition_id);
CREATE INDEX IF NOT EXISTS idx_indexed_trades_token ON indexed_trades(token_id);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    best_bid TEXT,
    best_ask TEXT,
    spread_bps TEXT,
    bid_depth TEXT,
    ask_depth TEXT,
    liquidity_imbalance TEXT,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_token_time
ON orderbook_snapshots(token_id, timestamp);

CREATE TABLE IF NOT EXISTS wallet_index_snapshots (
    wallet TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    trade_count INTEGER NOT NULL,
    total_volume TEXT NOT NULL,
    raw_profile_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS score_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    score_type TEXT NOT NULL,
    score TEXT NOT NULL,
    label TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    raw_metrics_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_score_history_subject
ON score_history(subject_type, subject_id, computed_at);
"""


class IndexerStorage:
    """Isolated SQLite storage for the optional Phase 3 indexer sidecar."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)

    def upsert_cursor(
        self,
        *,
        source: str,
        cursor_key: str,
        cursor_value: str,
        status: str = "ok",
        last_error: str = "",
        updated_at: str | None = None,
    ) -> None:
        updated_at = updated_at or _now_iso()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO indexer_cursors (
                    source, cursor_key, cursor_value, updated_at, status, last_error
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, cursor_key) DO UPDATE SET
                    cursor_value = excluded.cursor_value,
                    updated_at = excluded.updated_at,
                    status = excluded.status,
                    last_error = excluded.last_error
                """,
                (source, cursor_key, cursor_value, updated_at, status, last_error),
            )

    def get_cursor(self, source: str, cursor_key: str) -> IndexerCursor | None:
        row = self._fetch_one(
            """
            SELECT source, cursor_key, cursor_value, updated_at, status, last_error
            FROM indexer_cursors
            WHERE source = ? AND cursor_key = ?
            """,
            (source, cursor_key),
        )
        return _cursor_from_row(row) if row is not None else None

    def list_cursors(self) -> tuple[IndexerCursor, ...]:
        rows = self._fetch_all(
            """
            SELECT source, cursor_key, cursor_value, updated_at, status, last_error
            FROM indexer_cursors
            ORDER BY source, cursor_key
            """
        )
        return tuple(_cursor_from_row(row) for row in rows)

    def cursor_health(
        self,
        *,
        now: datetime | None = None,
        stale_after_seconds: int = 3600,
    ) -> tuple[CursorHealth, ...]:
        return summarize_cursor_health(
            self.list_cursors(),
            now=now,
            stale_after_seconds=stale_after_seconds,
        )

    def upsert_market(self, market: IndexedMarket) -> None:
        updated_at = market.updated_at or _now_iso()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO indexed_markets (
                    condition_id, slug, event_slug, question, active, closed,
                    end_date, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(condition_id) DO UPDATE SET
                    slug = excluded.slug,
                    event_slug = excluded.event_slug,
                    question = excluded.question,
                    active = excluded.active,
                    closed = excluded.closed,
                    end_date = excluded.end_date,
                    raw_json = excluded.raw_json,
                    updated_at = excluded.updated_at
                """,
                (
                    market.condition_id,
                    market.slug,
                    market.event_slug,
                    market.question,
                    int(market.active),
                    int(market.closed),
                    market.end_date,
                    _json_dump(market.raw),
                    updated_at,
                ),
            )

    def get_market(self, condition_id: str) -> dict[str, Any] | None:
        row = self._fetch_one("SELECT * FROM indexed_markets WHERE condition_id = ?", (condition_id,))
        if row is None:
            return None
        payload = dict(row)
        payload["active"] = bool(payload["active"])
        payload["closed"] = bool(payload["closed"])
        payload["raw"] = _json_load(payload.pop("raw_json"))
        return payload

    def upsert_trade(self, trade: IndexedTrade) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO indexed_trades (
                    stable_trade_id, transaction_hash, order_hash, condition_id,
                    token_id, wallet, side, outcome, size, price, usdc_size,
                    timestamp, source, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stable_trade_id) DO UPDATE SET
                    transaction_hash = excluded.transaction_hash,
                    order_hash = excluded.order_hash,
                    condition_id = excluded.condition_id,
                    token_id = excluded.token_id,
                    wallet = excluded.wallet,
                    side = excluded.side,
                    outcome = excluded.outcome,
                    size = excluded.size,
                    price = excluded.price,
                    usdc_size = excluded.usdc_size,
                    timestamp = excluded.timestamp,
                    source = excluded.source,
                    raw_json = excluded.raw_json
                """,
                (
                    trade.stable_trade_id,
                    trade.transaction_hash,
                    trade.order_hash,
                    trade.condition_id,
                    trade.token_id,
                    trade.wallet,
                    trade.side,
                    trade.outcome,
                    trade.size,
                    trade.price,
                    trade.usdc_size,
                    trade.timestamp,
                    trade.source,
                    _json_dump(trade.raw),
                ),
            )

    def get_trade(self, stable_trade_id: str) -> dict[str, Any] | None:
        row = self._fetch_one("SELECT * FROM indexed_trades WHERE stable_trade_id = ?", (stable_trade_id,))
        if row is None:
            return None
        payload = dict(row)
        payload["raw"] = _json_load(payload.pop("raw_json"))
        return payload

    def insert_orderbook_snapshot(self, snapshot: OrderbookSnapshot) -> int:
        with closing(self._connect()) as conn:
            existing = conn.execute(
                """
                SELECT id FROM orderbook_snapshots
                WHERE token_id = ? AND condition_id = ? AND timestamp = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (snapshot.token_id, snapshot.condition_id, snapshot.timestamp),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    """
                    UPDATE orderbook_snapshots SET
                        best_bid = ?,
                        best_ask = ?,
                        spread_bps = ?,
                        bid_depth = ?,
                        ask_depth = ?,
                        liquidity_imbalance = ?,
                        raw_json = ?
                    WHERE id = ?
                    """,
                    (
                        snapshot.best_bid,
                        snapshot.best_ask,
                        snapshot.spread_bps,
                        snapshot.bid_depth,
                        snapshot.ask_depth,
                        snapshot.liquidity_imbalance,
                        _json_dump(snapshot.raw),
                        existing["id"],
                    ),
                )
                return int(existing["id"])
            cursor = conn.execute(
                """
                INSERT INTO orderbook_snapshots (
                    token_id, condition_id, timestamp, best_bid, best_ask,
                    spread_bps, bid_depth, ask_depth, liquidity_imbalance, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.token_id,
                    snapshot.condition_id,
                    snapshot.timestamp,
                    snapshot.best_bid,
                    snapshot.best_ask,
                    snapshot.spread_bps,
                    snapshot.bid_depth,
                    snapshot.ask_depth,
                    snapshot.liquidity_imbalance,
                    _json_dump(snapshot.raw),
                ),
            )
            return int(cursor.lastrowid)

    def latest_orderbook_snapshot(self, token_id: str) -> dict[str, Any] | None:
        row = self._fetch_one(
            """
            SELECT * FROM orderbook_snapshots
            WHERE token_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (token_id,),
        )
        if row is None:
            return None
        payload = dict(row)
        payload["raw"] = _json_load(payload.pop("raw_json"))
        return payload

    def upsert_wallet_snapshot(self, snapshot: WalletIndexSnapshot) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO wallet_index_snapshots (
                    wallet, first_seen_at, last_seen_at, trade_count, total_volume,
                    raw_profile_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(wallet) DO UPDATE SET
                    first_seen_at = excluded.first_seen_at,
                    last_seen_at = excluded.last_seen_at,
                    trade_count = excluded.trade_count,
                    total_volume = excluded.total_volume,
                    raw_profile_json = excluded.raw_profile_json
                """,
                (
                    snapshot.wallet,
                    snapshot.first_seen_at,
                    snapshot.last_seen_at,
                    snapshot.trade_count,
                    snapshot.total_volume,
                    _json_dump(snapshot.raw_profile),
                ),
            )

    def append_score_history(self, entry: ScoreHistoryEntry) -> int:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO score_history (
                    subject_type, subject_id, score_type, score, label,
                    computed_at, input_hash, raw_metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.subject_type,
                    entry.subject_id,
                    entry.score_type,
                    entry.score,
                    entry.label,
                    entry.computed_at,
                    entry.input_hash,
                    _json_dump(entry.raw_metrics),
                ),
            )
            return int(cursor.lastrowid)

    def list_score_history(
        self,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        score_type: str | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        where: list[str] = []
        params: list[object] = []
        if subject_type is not None:
            where.append("subject_type = ?")
            params.append(subject_type)
        if subject_id is not None:
            where.append("subject_id = ?")
            params.append(subject_id)
        if score_type is not None:
            where.append("score_type = ?")
            params.append(score_type)
        query = "SELECT * FROM score_history"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY computed_at DESC, id DESC"
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be positive")
            query += " LIMIT ?"
            params.append(limit)
        return tuple(_score_history_from_row(row) for row in self._fetch_all(query, params))

    def latest_score_history(
        self,
        *,
        subject_type: str,
        subject_id: str,
        score_type: str,
    ) -> dict[str, Any] | None:
        rows = self.list_score_history(
            subject_type=subject_type,
            subject_id=subject_id,
            score_type=score_type,
            limit=1,
        )
        return rows[0] if rows else None

    def table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table in (
            "indexer_cursors",
            "indexed_markets",
            "indexed_trades",
            "orderbook_snapshots",
            "wallet_index_snapshots",
            "score_history",
        ):
            row = self._fetch_one(f"SELECT COUNT(*) AS count FROM {table}")
            counts[table] = int(row["count"]) if row is not None else 0
        return counts

    def _fetch_one(self, query: str, params: Iterable[object] = ()) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(query, tuple(params)).fetchone()

    def _fetch_all(self, query: str, params: Iterable[object] = ()) -> list[sqlite3.Row]:
        with closing(self._connect()) as conn:
            return list(conn.execute(query, tuple(params)).fetchall())

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn


def _cursor_from_row(row: sqlite3.Row) -> IndexerCursor:
    return IndexerCursor(
        source=str(row["source"]),
        cursor_key=str(row["cursor_key"]),
        cursor_value=str(row["cursor_value"]),
        updated_at=str(row["updated_at"]),
        status=str(row["status"]),
        last_error=str(row["last_error"]),
    )


def _score_history_from_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["raw_metrics"] = _json_load(payload.pop("raw_metrics_json"))
    return payload


def _json_dump(payload: Mapping[str, object]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)


def _json_load(payload: str) -> dict[str, Any]:
    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("Stored raw_json is malformed JSON") from exc
    if not isinstance(loaded, dict):
        raise ValueError("Stored raw_json must be a JSON object")
    return loaded


def _now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()
