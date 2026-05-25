from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from app.indexer.models import IndexerCursor


@dataclass(frozen=True, slots=True)
class CursorHealth:
    source: str
    cursor_key: str
    status: str
    updated_at: str
    age_seconds: float | None
    stale_after_seconds: int
    is_stale: bool
    last_error: str = ""


def assess_cursor_health(
    cursor: IndexerCursor,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 3600,
) -> CursorHealth:
    checked_at = now or datetime.now(tz=UTC)
    updated_at = _parse_datetime(cursor.updated_at)
    if updated_at is None:
        age_seconds = None
        is_stale = True
    else:
        age_seconds = max(0.0, (checked_at - updated_at).total_seconds())
        is_stale = age_seconds > stale_after_seconds
    return CursorHealth(
        source=cursor.source,
        cursor_key=cursor.cursor_key,
        status=cursor.status,
        updated_at=cursor.updated_at,
        age_seconds=age_seconds,
        stale_after_seconds=stale_after_seconds,
        is_stale=is_stale or cursor.status not in {"ok", "idle"},
        last_error=cursor.last_error,
    )


def summarize_cursor_health(
    cursors: Iterable[IndexerCursor],
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 3600,
) -> tuple[CursorHealth, ...]:
    return tuple(
        assess_cursor_health(cursor, now=now, stale_after_seconds=stale_after_seconds)
        for cursor in cursors
    )


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
