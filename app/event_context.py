from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models import Market, Trade

TIMELINE_FILENAMES = (
    "event_timelines.json",
    "event_timelines.csv",
    "offline_event_timelines.json",
    "offline_event_timelines.csv",
)

DOMAIN_DEFAULT_TIMEZONES = {
    "Politics": "America/New_York",
    "Geopolitics": "Europe/London",
    "Ukraine / war": "Europe/Kyiv",
    "Middle East": "Asia/Jerusalem",
    "Macro / rates": "America/New_York",
    "Crypto": "UTC",
    "Sports": "America/New_York",
    "Entertainment": "America/Los_Angeles",
    "Other": "UTC",
}

KEYWORD_TIMEZONES = {
    "ukraine": "Europe/Kyiv",
    "kyiv": "Europe/Kyiv",
    "kiev": "Europe/Kyiv",
    "russia": "Europe/Kyiv",
    "moscow": "Europe/Kyiv",
    "israel": "Asia/Jerusalem",
    "gaza": "Asia/Jerusalem",
    "jerusalem": "Asia/Jerusalem",
    "iran": "Asia/Tehran",
    "tehran": "Asia/Tehran",
    "lebanon": "Asia/Jerusalem",
    "syria": "Asia/Jerusalem",
    "taiwan": "Asia/Taipei",
    "china": "Asia/Shanghai",
    "beijing": "Asia/Shanghai",
    "tokyo": "Asia/Tokyo",
    "japan": "Asia/Tokyo",
    "european union": "Europe/Brussels",
    "eu ": "Europe/Brussels",
    "brussels": "Europe/Brussels",
    "london": "Europe/London",
    "britain": "Europe/London",
    "uk ": "Europe/London",
    "los angeles": "America/Los_Angeles",
    "hollywood": "America/Los_Angeles",
    "new york": "America/New_York",
    "washington": "America/New_York",
    "fed": "America/New_York",
    "fomc": "America/New_York",
    "trump": "America/New_York",
    "senate": "America/New_York",
    "house": "America/New_York",
}


@dataclass(slots=True)
class EventContext:
    trade_domain: str
    event_timezone: str
    local_event_time: str
    local_event_hour: int
    off_hours_flag: bool
    market_deadline_flag: bool
    matched_offline_row: bool
    timeline_id: str | None = None
    timeline_source: str | None = None
    broad_report_at: datetime | None = None
    official_confirmation_at: datetime | None = None
    public_outcome_at: datetime | None = None
    public_knowledge_at: datetime | None = None
    stale_resolution_annotation: bool = False
    reality_oracle_gap_label: str | None = None


class EventContextResolver:
    def __init__(self, *data_dirs: Path) -> None:
        unique_dirs: list[Path] = []
        for directory in data_dirs:
            if directory not in unique_dirs:
                unique_dirs.append(directory)
        self._data_dirs = tuple(unique_dirs)
        self._timeline_rows = self._load_timeline_rows()

    def resolve(
        self,
        *,
        trade: Trade,
        market: Market,
        trade_domain: str,
        market_deadline_flag: bool,
    ) -> EventContext:
        row = self._match_timeline_row(trade, market)
        timezone_name = self._timezone_name_for(trade, market, trade_domain, row)
        timezone = _safe_timezone(timezone_name)
        local_trade_time = trade.timestamp.astimezone(timezone)
        broad_report_at = _parse_datetime(_row_value(row, "broad_report_at", "first_broad_report_at"))
        official_confirmation_at = _parse_datetime(
            _row_value(row, "official_confirmation_at", "official_confirmed_at")
        )
        public_outcome_at = _parse_datetime(_row_value(row, "public_outcome_at", "truth_revealed_at"))
        public_knowledge_at = min(
            (
                value
                for value in (public_outcome_at, official_confirmation_at, broad_report_at)
                if value is not None
            ),
            default=None,
        )
        stale_annotation = _as_bool(
            _row_value(
                row,
                "stale_resolution",
                "stale_resolution_flag",
                "stale_resolution_annotation",
            )
        )
        if public_outcome_at is not None and trade.timestamp >= public_outcome_at:
            stale_annotation = True
        return EventContext(
            trade_domain=trade_domain,
            event_timezone=timezone.key,
            local_event_time=local_trade_time.isoformat(timespec="minutes"),
            local_event_hour=local_trade_time.hour,
            off_hours_flag=local_trade_time.hour >= 22 or local_trade_time.hour < 7,
            market_deadline_flag=market_deadline_flag,
            matched_offline_row=bool(row),
            timeline_id=_row_value(row, "timeline_id", "id"),
            timeline_source=_row_value(row, "timeline_source", "__source_name"),
            broad_report_at=broad_report_at,
            official_confirmation_at=official_confirmation_at,
            public_outcome_at=public_outcome_at,
            public_knowledge_at=public_knowledge_at,
            stale_resolution_annotation=stale_annotation,
            reality_oracle_gap_label=_row_value(
                row,
                "reality_oracle_gap_label",
                "gap_label",
                "oracle_gap_label",
            ),
        )

    def _load_timeline_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for data_dir in self._data_dirs:
            for filename in TIMELINE_FILENAMES:
                path = data_dir / filename
                if not path.exists():
                    continue
                try:
                    rows.extend(_load_rows_from_path(path))
                except (OSError, json.JSONDecodeError, csv.Error):
                    continue
        return rows

    def _match_timeline_row(self, trade: Trade, market: Market) -> dict[str, str]:
        best_score = 0
        best_row: dict[str, str] = {}
        for row in self._timeline_rows:
            score = _timeline_match_score(row, trade, market)
            if score > best_score:
                best_score = score
                best_row = row
        return best_row if best_score >= 45 else {}

    def _timezone_name_for(
        self,
        trade: Trade,
        market: Market,
        trade_domain: str,
        row: dict[str, str],
    ) -> str:
        explicit = _row_value(row, "event_timezone", "timezone", "local_timezone")
        if explicit and _is_valid_timezone(explicit):
            return explicit
        search_text = " ".join(
            item
            for item in (market.question, trade.title, trade.event_slug, market.slug)
            if item
        ).lower()
        for keyword, timezone_name in KEYWORD_TIMEZONES.items():
            if keyword in search_text:
                return timezone_name
        return DOMAIN_DEFAULT_TIMEZONES.get(trade_domain, "UTC")


def _load_rows_from_path(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            if isinstance(raw.get("rows"), list):
                raw_rows = raw["rows"]
            elif isinstance(raw.get("events"), list):
                raw_rows = raw["events"]
            else:
                raw_rows = []
        elif isinstance(raw, list):
            raw_rows = raw
        else:
            raw_rows = []
        return [_normalize_row(row, path) for row in raw_rows if isinstance(row, dict)]

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [_normalize_row(dict(row), path) for row in reader]


def _normalize_row(row: dict[str, object], path: Path) -> dict[str, str]:
    normalized: dict[str, str] = {"__source_name": path.name}
    for key, value in row.items():
        normalized[str(key).strip().lower()] = "" if value is None else str(value).strip()
    return normalized


def _timeline_match_score(row: dict[str, str], trade: Trade, market: Market) -> int:
    score = 0
    identifiers = {
        "condition_id": trade.condition_id,
        "market_id": market.market_id,
        "market_slug": market.slug,
        "slug": trade.slug,
        "event_slug": trade.event_slug,
    }
    for key, expected in identifiers.items():
        if expected and row.get(key, "").lower() == str(expected).lower():
            if key == "condition_id":
                return 100
            score = max(score, 90 if key == "market_id" else 80 if key in {"market_slug", "slug"} else 70)

    market_question = _normalize_text(market.question)
    trade_title = _normalize_text(trade.title)
    row_question = _normalize_text(_row_value(row, "question", "market_question", "title"))
    if row_question:
        if row_question == market_question or row_question == trade_title:
            score = max(score, 65)
        elif len(row_question) >= 12 and row_question in market_question:
            score = max(score, 55)

    contains_text = _normalize_text(_row_value(row, "question_contains", "title_contains", "match"))
    if contains_text and len(contains_text) >= 10:
        haystack = " ".join((market_question, trade_title, _normalize_text(trade.event_slug)))
        if contains_text in haystack:
            score = max(score, 50)
    return score


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = "".join(char.lower() if char.isalnum() else " " for char in value)
    return " ".join(text.split())


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _row_value(row: dict[str, str], *keys: str) -> str | None:
    if not row:
        return None
    for key in keys:
        value = row.get(key.lower())
        if value:
            return value
    return None


def _as_bool(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _safe_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _is_valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return False
    return True
