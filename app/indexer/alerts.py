from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


ALERT_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist_entries (
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (subject_type, subject_id)
);

CREATE TABLE IF NOT EXISTS advisory_alerts (
    alert_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    advisory_level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_advisory_alerts_subject
ON advisory_alerts(subject_type, subject_id, created_at);
"""


@dataclass(frozen=True, slots=True)
class WatchlistEntry:
    subject_type: str
    subject_id: str
    reason: str
    status: str = "active"
    updated_at: str = ""
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AdvisoryAlert:
    alert_id: str
    subject_type: str
    subject_id: str
    alert_type: str
    advisory_level: str
    message: str
    created_at: str
    status: str = "active"
    source_hash: str = ""
    raw: Mapping[str, object] = field(default_factory=dict)


class AlertSidecarStore:
    """Local analyst-only watchlist/alert storage for sidecar tests."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(ALERT_SCHEMA)

    def upsert_watchlist_entry(self, entry: WatchlistEntry) -> None:
        updated_at = entry.updated_at or _now_iso()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO watchlist_entries (
                    subject_type, subject_id, reason, status, updated_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject_type, subject_id) DO UPDATE SET
                    reason = excluded.reason,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    raw_json = excluded.raw_json
                """,
                (
                    entry.subject_type,
                    entry.subject_id,
                    entry.reason,
                    entry.status,
                    updated_at,
                    _json_dump(entry.raw),
                ),
            )

    def delete_watchlist_entry(self, subject_type: str, subject_id: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "DELETE FROM watchlist_entries WHERE subject_type = ? AND subject_id = ?",
                (subject_type, subject_id),
            )

    def list_watchlist_entries(self) -> tuple[dict[str, Any], ...]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM watchlist_entries ORDER BY subject_type, subject_id"
            ).fetchall()
        return tuple(_row_with_raw(row) for row in rows)

    def upsert_alert(self, alert: AdvisoryAlert) -> bool:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO advisory_alerts (
                    alert_id, subject_type, subject_id, alert_type, advisory_level,
                    message, created_at, status, source_hash, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert.alert_id,
                    alert.subject_type,
                    alert.subject_id,
                    alert.alert_type,
                    alert.advisory_level,
                    alert.message,
                    alert.created_at,
                    alert.status,
                    alert.source_hash,
                    _json_dump(alert.raw),
                ),
            )
            return cursor.rowcount > 0

    def list_alerts(self, *, status: str | None = None) -> tuple[dict[str, Any], ...]:
        query = "SELECT * FROM advisory_alerts"
        params: list[object] = []
        if status is not None:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC, alert_id DESC"
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return tuple(_row_with_raw(row) for row in rows)

    def expire_alerts(self, *, now: datetime, max_age_seconds: int) -> int:
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must be non-negative")
        expired = 0
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT alert_id, created_at FROM advisory_alerts WHERE status = 'active'").fetchall()
            for row in rows:
                created = _parse_datetime(str(row["created_at"]))
                if created is not None and (now - created).total_seconds() > max_age_seconds:
                    conn.execute("UPDATE advisory_alerts SET status = 'expired' WHERE alert_id = ?", (row["alert_id"],))
                    expired += 1
        return expired

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn


def stable_alert_id(subject_type: str, subject_id: str, alert_type: str, source_hash: str) -> str:
    raw = "|".join([subject_type, subject_id, alert_type, source_hash]).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def advisory_alert_from_metric(
    *,
    subject_type: str,
    subject_id: str,
    metric: Mapping[str, object],
    source_hash: str,
    created_at: str,
) -> AdvisoryAlert:
    alert_type = str(metric.get("name") or "shadow_metric")
    advisory_level = str(metric.get("advisoryLevel") or "context")
    alert_id = stable_alert_id(subject_type, subject_id, alert_type, source_hash)
    return AdvisoryAlert(
        alert_id=alert_id,
        subject_type=subject_type,
        subject_id=subject_id,
        alert_type=alert_type,
        advisory_level=f"advisory_{advisory_level}",
        message=f"Repeated advisory context: {alert_type}",
        created_at=created_at,
        source_hash=source_hash,
        raw=dict(metric),
    )


def evaluate_static_advisory_alerts(
    *,
    subject_type: str,
    subject_id: str,
    shadow_metrics: Sequence[Mapping[str, object]],
    score_history: Sequence[Mapping[str, object]],
    source_hash: str,
    created_at: str,
) -> tuple[AdvisoryAlert, ...]:
    previous_context = {
        str(row.get("score_type"))
        for row in score_history
        if str(row.get("label", "")).startswith("shadow_") and row.get("score_type")
    }
    alerts: list[AdvisoryAlert] = []
    for metric in shadow_metrics:
        name = str(metric.get("name") or "")
        status = str(metric.get("status") or "")
        advisory_level = str(metric.get("advisoryLevel") or "none")
        if not name or status == "unknown" or advisory_level == "none":
            continue
        if name not in previous_context:
            continue
        alerts.append(
            advisory_alert_from_metric(
                subject_type=subject_type,
                subject_id=subject_id,
                metric=metric,
                source_hash=source_hash,
                created_at=created_at,
            )
        )
    return tuple(alerts)


def _row_with_raw(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["raw"] = _json_load(payload.pop("raw_json"))
    return payload


def _json_dump(payload: Mapping[str, object]) -> str:
    import json

    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)


def _json_load(payload: str) -> dict[str, Any]:
    import json

    loaded = json.loads(payload)
    return loaded if isinstance(loaded, dict) else {}


def _parse_datetime(value: str) -> datetime | None:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()
