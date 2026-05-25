from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


RawPayload = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class IndexerCursor:
    source: str
    cursor_key: str
    cursor_value: str
    updated_at: str
    status: str = "ok"
    last_error: str = ""


@dataclass(frozen=True, slots=True)
class IndexedMarket:
    condition_id: str
    slug: str
    event_slug: str
    question: str
    active: bool
    closed: bool
    end_date: str = ""
    raw: RawPayload = field(default_factory=dict)
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class IndexedTrade:
    stable_trade_id: str
    transaction_hash: str
    order_hash: str
    condition_id: str
    token_id: str
    wallet: str
    side: str
    outcome: str
    size: str
    price: str
    usdc_size: str | None
    timestamp: str
    source: str
    raw: RawPayload = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OrderbookSnapshot:
    token_id: str
    condition_id: str
    timestamp: str
    best_bid: str | None = None
    best_ask: str | None = None
    spread_bps: str | None = None
    bid_depth: str | None = None
    ask_depth: str | None = None
    liquidity_imbalance: str | None = None
    raw: RawPayload = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WalletIndexSnapshot:
    wallet: str
    first_seen_at: str
    last_seen_at: str
    trade_count: int
    total_volume: str
    raw_profile: RawPayload = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScoreHistoryEntry:
    subject_type: str
    subject_id: str
    score_type: str
    score: str
    label: str
    computed_at: str
    input_hash: str
    raw_metrics: RawPayload = field(default_factory=dict)
