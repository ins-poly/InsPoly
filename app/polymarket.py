from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError
from urllib.error import URLError
from dataclasses import dataclass
from decimal import Decimal

from app.config import load_runtime_env
from app.models import Market, Trade
from app.site_categories import SITE_CATEGORY_CANDIDATES, SiteCategory


GAMMA_BASE = "https://gamma-api.polymarket.com"
DATA_BASE = "https://data-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
POLYGON_RPC = "https://polygon-rpc.com"
MAX_TRADES_OFFSET = 3000
RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}
HOST_CONCURRENCY_LIMITS = {
    "gamma-api.polymarket.com": 4,
    "data-api.polymarket.com": 12,
    "clob.polymarket.com": 4,
    "polygon-rpc.com": 2,
}
HOST_REQUEST_SPACING_SECONDS = {
    "gamma-api.polymarket.com": 0.04,
    "data-api.polymarket.com": 0.01,
    "clob.polymarket.com": 0.05,
    "polygon-rpc.com": 0.15,
}
DEFAULT_HOST_CONCURRENCY = 3
_HOST_LIMITER_LOCK = threading.Lock()
_HOST_SEMAPHORES: dict[str, threading.Semaphore] = {}
_HOST_NEXT_REQUEST_TS: dict[str, float] = {}


def _get_json(url: str, params: dict[str, object] | None = None, timeout: int = 30) -> object:
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; InsPoly/0.1; +https://polymarket.com)",
        },
    )
    return _load_json_request(request, timeout=timeout)


def _post_json(url: str, payload: dict[str, object], timeout: int = 30) -> object:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; InsPoly/0.1; +https://polymarket.com)",
        },
        method="POST",
    )
    return _load_json_request(request, timeout=timeout)


def _get_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (compatible; InsPoly/0.1; +https://polymarket.com)",
        },
    )
    return _load_text_request(request, timeout=timeout)


def _load_json_request(request: urllib.request.Request, *, timeout: int) -> object:
    delays = [0.8, 1.6, 3.2, 6.4]
    url = request.full_url
    for attempt in range(len(delays) + 1):
        try:
            _wait_for_host_slot(url)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in RETRYABLE_HTTP_CODES and attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            raise
        except (TimeoutError, socket.timeout, URLError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as exc:
            reason = getattr(exc, "reason", exc)
            if attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            raise reason if isinstance(reason, Exception) else exc
        finally:
            _release_host_slot(url)


def _load_text_request(request: urllib.request.Request, *, timeout: int) -> str:
    delays = [0.8, 1.6, 3.2, 6.4]
    url = request.full_url
    for attempt in range(len(delays) + 1):
        try:
            _wait_for_host_slot(url)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", "ignore")
        except HTTPError as exc:
            if exc.code in RETRYABLE_HTTP_CODES and attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            raise
        except (TimeoutError, socket.timeout, URLError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as exc:
            reason = getattr(exc, "reason", exc)
            if attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            raise reason if isinstance(reason, Exception) else exc
        finally:
            _release_host_slot(url)


def _wait_for_host_slot(url: str) -> None:
    host = _request_host(url)
    semaphore = _host_semaphore(host)
    semaphore.acquire()
    spacing = HOST_REQUEST_SPACING_SECONDS.get(host, 0.0)
    if spacing <= 0:
        return
    while True:
        with _HOST_LIMITER_LOCK:
            now = time.monotonic()
            next_allowed = _HOST_NEXT_REQUEST_TS.get(host, 0.0)
            if now >= next_allowed:
                _HOST_NEXT_REQUEST_TS[host] = now + spacing
                return
            wait_for = next_allowed - now
        if wait_for > 0:
            time.sleep(min(wait_for, spacing))


def _release_host_slot(url: str) -> None:
    host = _request_host(url)
    _host_semaphore(host).release()


def _is_auth_http_error(exc: Exception) -> bool:
    return isinstance(exc, HTTPError) and exc.code in {401, 403}


def _host_semaphore(host: str) -> threading.Semaphore:
    with _HOST_LIMITER_LOCK:
        semaphore = _HOST_SEMAPHORES.get(host)
        if semaphore is None:
            limit = HOST_CONCURRENCY_LIMITS.get(host, DEFAULT_HOST_CONCURRENCY)
            semaphore = threading.Semaphore(limit)
            _HOST_SEMAPHORES[host] = semaphore
        return semaphore


def _request_host(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower()


def polygon_rpc_urls(explicit: str | None = None) -> list[str]:
    load_runtime_env()
    raw = (
        explicit
        or os.environ.get("INSPOLY_POLYGON_RPC_URLS")
        or os.environ.get("POLYGON_RPC_URLS")
        or os.environ.get("POLYGON_RPC_URL")
        or POLYGON_RPC
    )
    urls: list[str] = []
    for candidate in re.split(r"[\s,]+", raw):
        url = candidate.strip()
        if url and url not in urls:
            urls.append(url)
    return urls or [POLYGON_RPC]


@dataclass(slots=True)
class WalletPublicStats:
    traded_market_count: int | None
    trades: list[Trade]
    polygon_nonce: int | None


@dataclass(slots=True)
class WalletPosition:
    asset_id: str
    condition_id: str
    size: Decimal
    current_value: Decimal
    redeemable: bool
    title: str
    outcome: str


@dataclass(slots=True)
class MarketStatus:
    condition_id: str
    title: str
    closed: bool
    accepting_orders: bool
    end_date: str | None


class PolymarketClient:
    def __init__(self, polygon_rpc_url: str | None = None) -> None:
        self._polygon_rpc_urls = polygon_rpc_urls(polygon_rpc_url)
        self._disabled_polygon_rpc_urls: dict[str, str] = {}
        self._polygon_nonce_disabled_reason: str | None = None

    def fetch_event_by_slug(self, slug: str) -> dict[str, object] | None:
        try:
            payload = _get_json(f"{GAMMA_BASE}/events/slug/{slug}", timeout=12)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def fetch_market_by_slug(self, slug: str) -> dict[str, object] | None:
        try:
            payload = _get_json(f"{GAMMA_BASE}/markets/slug/{slug}", timeout=12)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def fetch_event_resolution_from_pages(
        self,
        slug: str,
        *,
        page_hint: str | None = None,
    ) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        if page_hint == "market":
            event_payload, source_market_payload = self._fetch_event_resolution_from_market_page(slug)
            if event_payload is not None:
                return event_payload, source_market_payload
            return self._fetch_event_resolution_from_event_page(slug), None
        if page_hint == "event":
            event_payload = self._fetch_event_resolution_from_event_page(slug)
            if event_payload is not None:
                return event_payload, None
            return self._fetch_event_resolution_from_market_page(slug)

        event_payload = self._fetch_event_resolution_from_event_page(slug)
        if event_payload is not None:
            return event_payload, None
        return self._fetch_event_resolution_from_market_page(slug)

    def _fetch_event_resolution_from_event_page(self, slug: str) -> dict[str, object] | None:
        next_data = self._fetch_next_data(f"https://polymarket.com/event/{slug}")
        if next_data is None:
            return None
        payload = _next_data_query_payload(next_data, "/api/event/slug", slug)
        return payload if isinstance(payload, dict) else None

    def _fetch_event_resolution_from_market_page(
        self,
        slug: str,
    ) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        next_data = self._fetch_next_data(f"https://polymarket.com/market/{slug}")
        if next_data is None:
            return None, None
        query_slug = _next_data_market_query_slug(next_data)
        event_slug = query_slug[0] if query_slug else None
        market_slug = query_slug[-1] if query_slug else slug
        if not event_slug:
            return None, None
        event_payload = _next_data_query_payload(next_data, "/api/event/slug", event_slug)
        if not isinstance(event_payload, dict):
            return None, None
        source_market_payload = _market_payload_from_event(event_payload, market_slug)
        if source_market_payload is None:
            source_market_payload = _market_payload_from_event(event_payload, slug)
        if source_market_payload is not None:
            source_market_payload = dict(source_market_payload)
            source_market_payload.setdefault("events", [{"slug": event_slug}])
        return event_payload, source_market_payload

    def _fetch_next_data(self, url: str) -> dict[str, object] | None:
        try:
            html = _get_text(url, timeout=15)
        except Exception:
            return None
        return _extract_next_data_payload(html)

    def fetch_site_categories(self) -> list[SiteCategory]:
        categories: list[SiteCategory] = []
        for expected_label, slug in SITE_CATEGORY_CANDIDATES:
            try:
                item = _get_json(f"{GAMMA_BASE}/tags/slug/{slug}", timeout=10)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            categories.append(
                SiteCategory(
                    label=str(item.get("label") or expected_label),
                    slug=str(item.get("slug") or slug),
                    tag_id=str(item.get("id")),
                )
            )
        return categories

    def fetch_focus_markets(
        self,
        *,
        selected_categories: tuple[SiteCategory, ...],
        max_pages: int = 2,
        page_size: int = 200,
        active: str | None = "true",
        closed: str | None = None,
    ) -> dict[str, Market]:
        markets: dict[str, Market] = {}
        for category in selected_categories:
            for page in range(max_pages):
                params: dict[str, object] = {
                    "limit": page_size,
                    "offset": page * page_size,
                    "tag_id": category.tag_id,
                }
                if active is not None:
                    params["active"] = active
                if closed is not None:
                    params["closed"] = closed
                try:
                    batch = _get_json(f"{GAMMA_BASE}/markets", params)
                except HTTPError as exc:
                    # Gamma sometimes returns 422 on higher offsets instead of an empty page.
                    # Treat that as the end of pagination for this category slice instead of failing the full scan.
                    if exc.code == 422:
                        break
                    raise
                if not isinstance(batch, list) or not batch:
                    break
                for item in batch:
                    market = Market.from_api(item)
                    existing = markets.get(market.condition_id)
                    if existing is None:
                        market.site_categories = [category.label]
                        markets[market.condition_id] = market
                    elif category.label not in existing.site_categories:
                        existing.site_categories.append(category.label)
                if len(batch) < page_size:
                    break
        return markets

    def fetch_events_by_tag(
        self,
        tag_id: str,
        *,
        max_pages: int = 2,
        page_size: int = 100,
        closed: str | None = "true",
    ) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        for page in range(max_pages):
            params: dict[str, object] = {
                "limit": page_size,
                "offset": page * page_size,
                "tag_id": tag_id,
            }
            if closed is not None:
                params["closed"] = closed
            try:
                batch = _get_json(f"{GAMMA_BASE}/events", params, timeout=12)
            except HTTPError as exc:
                if exc.code == 422:
                    break
                raise
            except Exception:
                break
            if not isinstance(batch, list) or not batch:
                break
            events.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < page_size:
                break
        return events

    def fetch_recent_trades(
        self,
        *,
        cutoff_ts: int,
        max_pages: int,
        page_size: int,
        condition_ids: list[str] | None = None,
    ) -> list[Trade]:
        trades: list[Trade] = []
        market_filter = ",".join(condition_ids) if condition_ids else None
        for page in range(max_pages):
            params: dict[str, object] = {"limit": page_size, "offset": page * page_size}
            if market_filter:
                params["market"] = market_filter
            batch = _get_json(f"{DATA_BASE}/trades", params)
            if not isinstance(batch, list) or not batch:
                break
            stop = False
            for item in batch:
                trade = Trade.from_api(item)
                if int(trade.timestamp.timestamp()) < cutoff_ts:
                    stop = True
                    break
                trades.append(trade)
            if stop or len(batch) < page_size:
                break
            time.sleep(0.15)
        return trades

    def fetch_trades_in_range(
        self,
        *,
        start_ts: int,
        end_ts: int,
        max_pages: int,
        page_size: int,
        condition_ids: list[str] | None = None,
        filter_cash_amount: Decimal | None = None,
    ) -> list[Trade]:
        trades: list[Trade] = []
        market_filter = ",".join(condition_ids) if condition_ids else None
        # Data API pacing already flows through the shared host limiter in `_wait_for_host_slot()`.
        # Avoid an extra per-page sleep here because event-forensic replays fan out this path across
        # many markets and the duplicate delay dominates large completed-event runs.
        for page in range(max_pages):
            offset = page * page_size
            if offset > MAX_TRADES_OFFSET:
                break
            params: dict[str, object] = {"limit": page_size, "offset": offset}
            if market_filter:
                params["market"] = market_filter
            if filter_cash_amount is not None and filter_cash_amount > 0:
                params["filterType"] = "CASH"
                params["filterAmount"] = str(filter_cash_amount)
            try:
                batch = _get_json(f"{DATA_BASE}/trades", params)
            except HTTPError as exc:
                if exc.code == 400 and offset >= MAX_TRADES_OFFSET:
                    break
                raise
            if not isinstance(batch, list) or not batch:
                break
            stop = False
            for item in batch:
                trade = Trade.from_api(item)
                trade_ts = int(trade.timestamp.timestamp())
                if trade_ts > end_ts:
                    continue
                if trade_ts < start_ts:
                    stop = True
                    break
                trades.append(trade)
            if stop or len(batch) < page_size:
                break
        return trades

    def fetch_wallet_stats(self, address: str, trade_limit: int = 200) -> WalletPublicStats:
        traded_market_count: int | None = None
        try:
            traded_payload = _get_json(f"{DATA_BASE}/traded", {"user": address})
            if isinstance(traded_payload, dict):
                raw_value = traded_payload.get("traded")
                traded_market_count = int(raw_value) if raw_value is not None else None
        except Exception:
            traded_market_count = None

        try:
            trades_payload = _get_json(
                f"{DATA_BASE}/trades",
                {"user": address, "limit": trade_limit, "offset": 0},
            )
            trades = [Trade.from_api(item) for item in trades_payload] if isinstance(trades_payload, list) else []
        except Exception:
            trades = []

        return WalletPublicStats(
            traded_market_count=traded_market_count,
            trades=trades,
            polygon_nonce=self.fetch_polygon_nonce(address),
        )

    def fetch_wallet_positions(self, address: str) -> list[WalletPosition]:
        try:
            payload = _get_json(f"{DATA_BASE}/positions", {"user": address}, timeout=12)
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        positions: list[WalletPosition] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            positions.append(
                WalletPosition(
                    asset_id=str(item.get("asset", "")),
                    condition_id=str(item.get("conditionId", "")),
                    size=Decimal(str(item.get("size", 0) or 0)),
                    current_value=Decimal(str(item.get("currentValue", 0) or 0)),
                    redeemable=bool(item.get("redeemable", False)),
                    title=str(item.get("title", "")),
                    outcome=str(item.get("outcome", "")),
                )
            )
        return positions

    def fetch_market_status_by_slug(self, slug: str) -> MarketStatus | None:
        try:
            payload = _get_json(f"{GAMMA_BASE}/markets/slug/{slug}", timeout=12)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        return MarketStatus(
            condition_id=str(payload.get("conditionId", "")),
            title=str(payload.get("question", "")),
            closed=bool(payload.get("closed", False)),
            accepting_orders=bool(payload.get("acceptingOrders", False)),
            end_date=payload.get("endDate"),
        )

    def fetch_polygon_nonce(self, address: str) -> int | None:
        if self._polygon_nonce_disabled_reason is not None:
            return None
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_getTransactionCount",
            "params": [address, "latest"],
            "id": 1,
        }
        last_error: str | None = None
        for rpc_url in self._polygon_rpc_urls:
            if rpc_url in self._disabled_polygon_rpc_urls:
                continue
            try:
                response = _post_json(rpc_url, payload, timeout=5)
                if isinstance(response, dict):
                    result = response.get("result")
                    if isinstance(result, str):
                        return int(result, 16)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if _is_auth_http_error(exc):
                    self._disabled_polygon_rpc_urls[rpc_url] = last_error
                    continue
                continue
        if len(self._disabled_polygon_rpc_urls) >= len(self._polygon_rpc_urls):
            self._polygon_nonce_disabled_reason = "; ".join(self._disabled_polygon_rpc_urls.values())
        return None

    @property
    def polygon_nonce_disabled_reason(self) -> str | None:
        return self._polygon_nonce_disabled_reason

    def fetch_price_history(self, asset_id: str, start_ts: int, end_ts: int) -> list[dict[str, object]]:
        payload = _get_json(
            f"{CLOB_BASE}/prices-history",
            {
                "market": asset_id,
                "startTs": start_ts,
                "endTs": end_ts,
                "interval": "1h",
                "fidelity": 1,
            },
            timeout=8,
        )
        if not isinstance(payload, dict):
            return []
        history = payload.get("history", [])
        return history if isinstance(history, list) else []

    @staticmethod
    def compute_max_favorable_move(side: str, entry_price: Decimal, history: list[dict[str, object]]) -> Decimal:
        best_move = Decimal("0")
        for point in history:
            raw_price = point.get("p")
            if raw_price is None:
                continue
            price = Decimal(str(raw_price))
            move = price - entry_price if side == "BUY" else entry_price - price
            if move > best_move:
                best_move = move
        return best_move


def _extract_next_data_payload(html: str) -> dict[str, object] | None:
    match = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.S,
    )
    if match is None:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _next_data_query_payload(
    next_data: dict[str, object],
    api_key: str,
    slug: str,
) -> dict[str, object] | None:
    queries = (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("dehydratedState", {})
        .get("queries", [])
    )
    if not isinstance(queries, list):
        return None
    for query in queries:
        if not isinstance(query, dict):
            continue
        query_key = query.get("queryKey")
        if not isinstance(query_key, list) or len(query_key) < 2:
            continue
        if str(query_key[0]) != api_key or str(query_key[1]) != slug:
            continue
        payload = (query.get("state") or {}).get("data")
        return payload if isinstance(payload, dict) else None
    return None


def _next_data_market_query_slug(next_data: dict[str, object]) -> list[str]:
    query = next_data.get("query")
    if not isinstance(query, dict):
        return []
    slug_value = query.get("slug")
    if isinstance(slug_value, list):
        return [str(item) for item in slug_value if str(item)]
    if isinstance(slug_value, str) and slug_value:
        return [slug_value]
    return []


def _market_payload_from_event(event_payload: dict[str, object], market_slug: str) -> dict[str, object] | None:
    for item in event_payload.get("markets") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("slug") or "") == market_slug:
            return item
    return None
