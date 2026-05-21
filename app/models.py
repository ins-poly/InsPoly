from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal


@dataclass(slots=True)
class Market:
    market_id: str
    condition_id: str
    slug: str
    question: str
    category: str
    end_date: str | None
    liquidity: Decimal
    volume: Decimal
    outcomes: list[str]
    token_ids: list[str]
    tags: list[str]
    site_categories: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "Market":
        outcomes = _parse_jsonish_list(data.get("outcomes"))
        token_ids = _parse_jsonish_list(data.get("clobTokenIds"))
        tags = [str(tag).lower() for tag in _parse_jsonish_list(data.get("tags"))]
        return cls(
            market_id=str(data.get("id", "")),
            condition_id=str(data.get("conditionId", "")),
            slug=str(data.get("slug", "")),
            question=str(data.get("question", "")),
            category=str(data.get("category", "")),
            end_date=data.get("endDate"),
            liquidity=_to_decimal(data.get("liquidity")),
            volume=_to_decimal(data.get("volume")),
            outcomes=[str(item) for item in outcomes],
            token_ids=[str(item) for item in token_ids],
            tags=tags,
        )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["liquidity"] = str(self.liquidity)
        payload["volume"] = str(self.volume)
        return payload


@dataclass(slots=True)
class Trade:
    trade_id: str
    condition_id: str
    asset_id: str
    wallet: str
    side: str
    outcome: str
    price: Decimal
    size: Decimal
    timestamp: datetime
    title: str
    slug: str
    event_slug: str
    trader_name: str = ""
    trader_pseudonym: str = ""

    @classmethod
    def from_api(cls, data: dict) -> "Trade":
        timestamp = datetime.fromtimestamp(int(data.get("timestamp", 0)), tz=UTC)
        return cls(
            trade_id=str(data.get("transactionHash", "")),
            condition_id=str(data.get("conditionId", "")),
            asset_id=str(data.get("asset", "")),
            wallet=str(data.get("proxyWallet", "")).lower(),
            side=str(data.get("side", "")).upper(),
            outcome=str(data.get("outcome", "")),
            price=_to_decimal(data.get("price")),
            size=_to_decimal(data.get("size")),
            timestamp=timestamp,
            title=str(data.get("title", "")),
            slug=str(data.get("slug", "")),
            event_slug=str(data.get("eventSlug", "")),
            trader_name=str(data.get("name", "") or ""),
            trader_pseudonym=str(data.get("pseudonym", "") or ""),
        )

    @property
    def notional(self) -> Decimal:
        return self.price * self.size

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["price"] = str(self.price)
        payload["size"] = str(self.size)
        payload["timestamp"] = self.timestamp.isoformat()
        payload["notional"] = str(self.notional)
        return payload


@dataclass(slots=True)
class WalletInspection:
    address: str
    polygon_nonce: int | None
    traded_market_count: int | None
    recent_trade_count: int
    unique_market_count: int
    focus_market_count: int
    first_trade_at: str | None
    last_trade_at: str | None
    dominant_domain_label: str = "Other"
    domain_concentration_score: float = 0.0
    public_model_specialist_flag: bool = False
    domain_counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class FlaggedCase:
    severity: str
    suspicion_score: int
    confidence_score: int
    review_priority: str
    verdict: str
    trade_count_window: int
    window_start: str
    window_end: str
    trade: Trade
    market: Market
    wallet_inspection: WalletInspection
    subscores: dict[str, int]
    flags: list[str]
    explanation: list[str]
    reasons_against: list[str]
    raw_metrics: dict[str, str]
    case_type: str | None = None
    initial_suspicion_score: int | None = None
    latest_suspicion_score: int | None = None
    initial_severity: str | None = None
    latest_severity: str | None = None
    replay_stage: str = "initial"
    replay_count: int = 0

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "case_type": self.case_type,
            "suspicion_score": self.suspicion_score,
            "confidence_score": self.confidence_score,
            "review_priority": self.review_priority,
            "verdict": self.verdict,
            "trade_count_window": self.trade_count_window,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "trade": self.trade.to_dict(),
            "market": self.market.to_dict(),
            "wallet_inspection": self.wallet_inspection.to_dict(),
            "subscores": dict(self.subscores),
            "flags": list(self.flags),
            "explanation": list(self.explanation),
            "reasons_against": list(self.reasons_against),
            "raw_metrics": dict(self.raw_metrics),
            "initial_suspicion_score": self.initial_suspicion_score if self.initial_suspicion_score is not None else self.suspicion_score,
            "latest_suspicion_score": self.latest_suspicion_score if self.latest_suspicion_score is not None else self.suspicion_score,
            "initial_severity": self.initial_severity or self.severity,
            "latest_severity": self.latest_severity or self.severity,
            "replay_stage": self.replay_stage,
            "replay_count": self.replay_count,
        }


def _to_decimal(value: object) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _parse_jsonish_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            import json

            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return []
            return parsed if isinstance(parsed, list) else []
    return []
