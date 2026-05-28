"""Optional Polymarket indexer sidecar primitives.

The indexer package is intentionally isolated from scanner/archive/event
forensic runtime paths. Phase 3A only provides storage/model/health skeletons.
"""

from app.indexer.health import CursorHealth, assess_cursor_health, summarize_cursor_health
from app.indexer.adapters import (
    normalize_data_trade,
    normalize_gamma_market,
    normalize_orderbook_snapshot,
    stable_data_trade_id,
    token_condition_mapping_from_gamma_market,
)
from app.indexer.models import (
    IndexedMarket,
    IndexedTrade,
    IndexerCursor,
    OrderbookSnapshot,
    ScoreHistoryEntry,
    WalletIndexSnapshot,
)
from app.indexer.storage import IndexerStorage

__all__ = [
    "CursorHealth",
    "IndexedMarket",
    "IndexedTrade",
    "IndexerCursor",
    "IndexerStorage",
    "OrderbookSnapshot",
    "ScoreHistoryEntry",
    "WalletIndexSnapshot",
    "assess_cursor_health",
    "normalize_data_trade",
    "normalize_gamma_market",
    "normalize_orderbook_snapshot",
    "summarize_cursor_health",
    "stable_data_trade_id",
    "token_condition_mapping_from_gamma_market",
]
