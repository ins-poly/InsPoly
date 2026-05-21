from __future__ import annotations

from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
import copy
import json
from pathlib import Path
import sqlite3
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlparse
import urllib.request
from app.config import (
    FUNDING_TRACE_MODE_CACHE_ONLY,
    FUNDING_TRACE_MODE_DISABLED,
    FUNDING_TRACE_MODE_LIVE_RPC,
    funding_trace_mode,
    normalize_funding_trace_mode,
    repository_root,
    runtime_env_float,
    runtime_env_int,
)
from app.polymarket import _post_json, polygon_rpc_urls

TRANSFER_EVENT_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
USDC_ADDRESSES = (
    "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",
    "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
)
SEARCH_WINDOW_BLOCKS = 100_000
MAX_SEARCH_BLOCKS = 1_000_000
DEFAULT_RPC_MAX_CONCURRENCY = 1
DEFAULT_RPC_MIN_INTERVAL_SECONDS = 1.0
DEFAULT_RPC_MAX_RETRIES = 3
DEFAULT_RPC_429_COOLDOWN_SECONDS = 60.0
DEFAULT_RPC_GETLOGS_BLOCK_CHUNK = 1500
DEFAULT_RPC_REQUEST_TIMEOUT_SECONDS = 10.0
DEFAULT_VALIDATION_RPC_REQUEST_TIMEOUT_SECONDS = 5.0
DEFAULT_POLYGON_AVERAGE_BLOCK_SECONDS = 2.1
FUNDING_TRACE_CACHE_SCHEMA_VERSION = 1
FUNDING_TRACE_CACHE_FILENAME = "funding_trace_cache.sqlite"
FUNDING_TRACE_SETTINGS_VERSION = (
    f"polygon_usdc_v1:{SEARCH_WINDOW_BLOCKS}:{MAX_SEARCH_BLOCKS}:"
    + ",".join(address.lower() for address in USDC_ADDRESSES)
)
DEFAULT_FUNDING_TRACE_CACHE_ENABLED = 1
DEFAULT_FUNDING_TRACE_CACHE_TTL_HOURS = 168
DEFAULT_FUNDING_TRACE_NONE_TTL_HOURS = 24
DEFAULT_FUNDING_TRACE_FAILURE_TTL_MINUTES = 5
DEFAULT_VALIDATION_MAX_FUNDING_TRACES_PER_BUNDLE = 50
DEFAULT_VALIDATION_MAX_FUNDING_TRACE_FAILURES_PER_BUNDLE = 10
DEFAULT_VALIDATION_MAX_CONSECUTIVE_RPC_FAILURES = 5
DEFAULT_VALIDATION_ALLOW_NETWORK_FUNDING = 1
DEFAULT_VALIDATION_MAX_LOG_CHUNKS_PER_TRACE = 4

KNOWN_ENTITIES: dict[str, tuple[str, str, str]] = {
    "0x28c6c06298d514db089934071355e5743bf21d60": ("Binance", "cex_binance", "cex"),
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": ("Binance", "cex_binance", "cex"),
    "0xf89d7b9c864f589bbf53a82105107622b35eaa40": ("Binance", "cex_binance", "cex"),
    "0xdfd5293d8e347dfe59e90efd55b2956a1343963d": ("Binance", "cex_binance", "cex"),
    "0x503828976d22510aad0339f595f37cc4e4645c80": ("Coinbase", "cex_coinbase", "cex"),
    "0x71660c4005ba85c37ccec55d0c4493e66fe775d3": ("Coinbase", "cex_coinbase", "cex"),
    "0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43": ("Coinbase", "cex_coinbase", "cex"),
    "0x2910543af39aba0cd09dbb2d50200b3e800a63d2": ("Kraken", "cex_kraken", "cex"),
    "0x0a869d79a7052c7f1b55a8ebabbea3420f0d1e13": ("Kraken", "cex_kraken", "cex"),
    "0x5041ed759dd4afc3a72b8192c143f72f4724081a": ("OKX", "cex_okx", "cex"),
    "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": ("OKX", "cex_okx", "cex"),
    "0xf16e9b0d03470827a95cdfd0cb8a8a3b46969b91": ("KuCoin", "cex_kucoin", "cex"),
    "0xd6216fc19db775df9774a6e33526131da7d19a2c": ("KuCoin", "cex_kucoin", "cex"),
    "0xf89e6d82be28f5cc97a9e6a94a16a17e5be73e78": ("Bybit", "cex_bybit", "cex"),
    "0x6262998ced04146fa42253a5c0af90ca02dfd2a3": ("Crypto.com", "cex_crypto_com", "cex"),
    "0x46340b20830761efd32832a74d7169b29feb9758": ("Crypto.com", "cex_crypto_com", "cex"),
    "0xa0c68c638235ee32657e8f720a23cec1bfc77c77": ("Polygon Bridge", "bridge_polygon", "bridge"),
    "0x401f6c983ea34274ec46f84d70b31c151321188b": ("Polygon Bridge", "bridge_polygon", "bridge"),
    "0x4f3aff3a747fcade12598081e80c6605a8be192f": ("Multichain Bridge", "bridge_multichain", "bridge"),
    "0x45a01e4e04f14f7a4a6880d0cbaf2c3c1acfbed4": ("Stargate", "bridge_stargate", "bridge"),
    "0x76b22b8c1079a44f1211b0e72c5d26c5e3b3c3c9": ("Hop Bridge", "bridge_hop", "bridge"),
    "0xe592427a0aece92de3edee1f18e0157c05861564": ("Uniswap", "dex_uniswap", "dex"),
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": ("Uniswap", "dex_uniswap", "dex"),
    "0x1b02da8cb0d097eb8d57a175b88c7d8b47997506": ("SushiSwap", "dex_sushiswap", "dex"),
    "0xa5e0829caced8ffdd4de3c43696c57f7d7a678ff": ("QuickSwap", "dex_quickswap", "dex"),
    "0x1111111254eeb25477b68fb85ed929f73a960582": ("1inch", "dex_1inch", "dex"),
    "0x794a61358d6845594f94dc1db02a252b5b4814ad": ("Aave", "defi_aave", "defi"),
    "0x8145edddf43f50276641b55bd3ad95944510021e": ("Aave", "defi_aave", "defi"),
}

FUNDING_EVIDENCE_DIRECT_STRICT = "direct_strict"
FUNDING_EVIDENCE_SUSPICIOUS_DIRECT = "suspicious_direct"
FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN = "multi_hop_unknown"
FUNDING_EVIDENCE_BRIDGE_PROXY = "bridge_proxy"
FUNDING_EVIDENCE_CEX_PROXY = "cex_proxy"
FUNDING_EVIDENCE_NONE = "none"
FUNDING_EVIDENCE_UNKNOWN = "unknown"
PROXY_FUNDING_EVIDENCE_GRADES = {
    FUNDING_EVIDENCE_BRIDGE_PROXY,
    FUNDING_EVIDENCE_CEX_PROXY,
}


@dataclass(slots=True)
class FundingTransfer:
    from_address: str
    to_address: str
    amount_usdc: float
    tx_hash: str
    block_number: int
    timestamp: datetime


class FundingTraceBudgetExceeded(RuntimeError):
    pass


@dataclass(slots=True)
class FundingContext:
    funding_found: bool
    source_address: str = ""
    source_label: str = "Unknown"
    source_type: str = "unknown"
    source_category: str = "unknown"
    origin_address: str = ""
    origin_label: str = "Unknown"
    origin_type: str = "unknown"
    origin_category: str = "unknown"
    funding_tx_hash: str = ""
    funding_timestamp: datetime | None = None
    funding_amount_usdc: float = 0.0
    minutes_from_funding_to_trade: float | None = None
    funding_velocity_label: str = "Unavailable"
    suspicious_funding_score: float = 0.0
    suspicious_funding_flag: bool = False
    recent_external_funding_flag: bool = False
    funding_depth: int = 0
    funding_graph_key: str = ""
    funding_graph_key_strict: str = ""
    funding_graph_key_proxy: str = ""
    funding_fingerprint: str = ""
    funding_evidence_grade: str = FUNDING_EVIDENCE_NONE
    cex_proxy_cluster_flag: bool = False
    cex_proxy_cluster_size: int = 0
    funding_trace_from_persistent_cache: bool = False
    funding_trace_cache_status: str = ""
    error: str | None = None


@dataclass(slots=True)
class FundingResolverHealth:
    fundingResolverAvailable: bool
    fundingResolverDisabledReason: str = ""
    fundingResolverAuthError: bool = False
    fundingResolverUnavailableReason: str = ""
    fundingResolverFunctionalStatus: str = ""
    fundingResolverEndpointLabel: str = ""
    fundingResolverLastError: str = ""
    fundingTraceMode: str = FUNDING_TRACE_MODE_LIVE_RPC
    fundingTraceDisabledReason: str = ""
    fundingEvidenceInterpretation: str = ""
    fundingTraceAttemptedCount: int = 0
    fundingTraceSucceededCount: int = 0
    fundingTraceFailedCount: int = 0
    fundingTraceSkippedCount: int = 0
    fundingTraceSkippedReasonDistribution: dict[str, int] = field(default_factory=dict)
    fundingTraceCoverageRatio: float = 0.0
    fundingTraceEndpointPoolSize: int = 0
    fundingTraceEndpointAvailableCount: int = 0
    fundingTraceEndpointCooldownCount: int = 0
    fundingTraceEndpointFailureDistribution: dict[str, int] = field(default_factory=dict)
    fundingTraceEndpointSummary: list[dict[str, object]] = field(default_factory=list)
    fundingTraceRateLimitedCount: int = 0
    fundingTraceRetryCount: int = 0
    fundingTraceFallbackEndpointCount: int = 0
    fundingTraceLogChunksAttempted: int = 0
    fundingTraceLogChunksSucceeded: int = 0
    fundingTraceLogChunksFailed: int = 0
    fundingTraceLogChunksRateLimited: int = 0
    fundingTraceCacheHitCount: int = 0
    fundingTraceCacheMissCount: int = 0
    fundingTracePersistentCacheEnabled: bool = False
    fundingTracePersistentCacheHitCount: int = 0
    fundingTracePersistentCacheMissCount: int = 0
    fundingTracePersistentCacheWriteCount: int = 0
    fundingTracePersistentCacheExpiredCount: int = 0
    fundingTracePersistentCacheFailureCooldownCount: int = 0
    fundingTracePersistentCacheSchemaVersion: int = FUNDING_TRACE_CACHE_SCHEMA_VERSION
    validationBundleStatus: str = ""
    validationFundingStatus: str = ""
    validationAbortReason: str = ""
    validationTimedOut: bool = False
    validationFundingTimedOut: bool = False
    validationRpcFailureLimitHit: bool = False
    validationFundingTraceLimitHit: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "fundingResolverAvailable": self.fundingResolverAvailable,
            "fundingResolverDisabledReason": self.fundingResolverDisabledReason,
            "fundingResolverAuthError": self.fundingResolverAuthError,
            "fundingResolverUnavailableReason": self.fundingResolverUnavailableReason,
            "fundingResolverFunctionalStatus": self.fundingResolverFunctionalStatus,
            "fundingResolverEndpointLabel": self.fundingResolverEndpointLabel,
            "fundingResolverLastError": self.fundingResolverLastError,
            "fundingTraceMode": self.fundingTraceMode,
            "fundingTraceDisabledReason": self.fundingTraceDisabledReason,
            "fundingEvidenceInterpretation": self.fundingEvidenceInterpretation,
            "fundingTraceAttemptedCount": self.fundingTraceAttemptedCount,
            "fundingTraceSucceededCount": self.fundingTraceSucceededCount,
            "fundingTraceFailedCount": self.fundingTraceFailedCount,
            "fundingTraceSkippedCount": self.fundingTraceSkippedCount,
            "fundingTraceSkippedReasonDistribution": dict(self.fundingTraceSkippedReasonDistribution),
            "fundingTraceCoverageRatio": self.fundingTraceCoverageRatio,
            "fundingTraceEndpointPoolSize": self.fundingTraceEndpointPoolSize,
            "fundingTraceEndpointAvailableCount": self.fundingTraceEndpointAvailableCount,
            "fundingTraceEndpointCooldownCount": self.fundingTraceEndpointCooldownCount,
            "fundingTraceEndpointFailureDistribution": dict(self.fundingTraceEndpointFailureDistribution),
            "fundingTraceEndpointSummary": [dict(item) for item in self.fundingTraceEndpointSummary],
            "fundingTraceRateLimitedCount": self.fundingTraceRateLimitedCount,
            "fundingTraceRetryCount": self.fundingTraceRetryCount,
            "fundingTraceFallbackEndpointCount": self.fundingTraceFallbackEndpointCount,
            "fundingTraceLogChunksAttempted": self.fundingTraceLogChunksAttempted,
            "fundingTraceLogChunksSucceeded": self.fundingTraceLogChunksSucceeded,
            "fundingTraceLogChunksFailed": self.fundingTraceLogChunksFailed,
            "fundingTraceLogChunksRateLimited": self.fundingTraceLogChunksRateLimited,
            "fundingTraceCacheHitCount": self.fundingTraceCacheHitCount,
            "fundingTraceCacheMissCount": self.fundingTraceCacheMissCount,
            "fundingTracePersistentCacheEnabled": self.fundingTracePersistentCacheEnabled,
            "fundingTracePersistentCacheHitCount": self.fundingTracePersistentCacheHitCount,
            "fundingTracePersistentCacheMissCount": self.fundingTracePersistentCacheMissCount,
            "fundingTracePersistentCacheWriteCount": self.fundingTracePersistentCacheWriteCount,
            "fundingTracePersistentCacheExpiredCount": self.fundingTracePersistentCacheExpiredCount,
            "fundingTracePersistentCacheFailureCooldownCount": self.fundingTracePersistentCacheFailureCooldownCount,
            "fundingTracePersistentCacheSchemaVersion": self.fundingTracePersistentCacheSchemaVersion,
            "validationBundleStatus": self.validationBundleStatus,
            "validationFundingStatus": self.validationFundingStatus,
            "validationAbortReason": self.validationAbortReason,
            "validationTimedOut": self.validationTimedOut,
            "validationFundingTimedOut": self.validationFundingTimedOut,
            "validationRpcFailureLimitHit": self.validationRpcFailureLimitHit,
            "validationFundingTraceLimitHit": self.validationFundingTraceLimitHit,
        }


@dataclass(slots=True)
class RpcEndpointState:
    url: str
    label: str
    request_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    rate_limited_count: int = 0
    cooldown_until: float = 0.0
    last_error: str = ""
    lightweight_health_status: str = "unknown"
    funding_trace_health_status: str = "unknown"
    disabled: bool = False

    def in_cooldown(self, now: float | None = None) -> bool:
        return self.cooldown_until > (now if now is not None else time.monotonic())

    def to_dict(self) -> dict[str, object]:
        return {
            "endpointLabel": self.label,
            "requestCount": self.request_count,
            "successCount": self.success_count,
            "failureCount": self.failure_count,
            "rateLimitedCount": self.rate_limited_count,
            "cooldownActive": self.in_cooldown(),
            "lastError": self.last_error,
            "lightweightHealthStatus": self.lightweight_health_status,
            "fundingTraceHealthStatus": self.funding_trace_health_status,
        }


class FundingTracePersistentCache:
    def __init__(
        self,
        path: Path | None = None,
        *,
        enabled: bool = True,
        ttl_hours: int = DEFAULT_FUNDING_TRACE_CACHE_TTL_HOURS,
        none_ttl_hours: int = DEFAULT_FUNDING_TRACE_NONE_TTL_HOURS,
        failure_ttl_minutes: int = DEFAULT_FUNDING_TRACE_FAILURE_TTL_MINUTES,
        schema_version: int = FUNDING_TRACE_CACHE_SCHEMA_VERSION,
    ) -> None:
        self.path = path or repository_root() / ".inspoly" / FUNDING_TRACE_CACHE_FILENAME
        self.enabled = bool(enabled)
        self.ttl_seconds = max(0, int(ttl_hours)) * 3600
        self.none_ttl_seconds = max(0, int(none_ttl_hours)) * 3600
        self.failure_ttl_seconds = max(0, int(failure_ttl_minutes)) * 60
        self.schema_version = schema_version
        self.disabled_reason = ""
        self.schema_mismatch_handled = False
        self.expired_count = 0
        if self.enabled:
            self._ensure_schema()

    def get(self, cache_key: str, *, now: float | None = None) -> tuple[str, FundingContext] | None:
        if not self.enabled:
            return None
        current = now if now is not None else time.time()
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT status, context_json, expires_at, schema_version
                    FROM funding_trace_cache
                    WHERE cache_key = ?
                    """,
                    (cache_key,),
                ).fetchone()
        except sqlite3.DatabaseError as exc:
            self._disable(f"sqlite_error:{type(exc).__name__}: {exc}")
            return None
        if row is None:
            return None
        status, context_json, expires_at, schema_version = row
        if int(schema_version or 0) != self.schema_version:
            self._handle_schema_mismatch()
            return None
        if float(expires_at or 0) <= current:
            self.expired_count += 1
            self.delete(cache_key)
            return None
        try:
            payload = json.loads(context_json or "{}")
            context = _funding_context_from_cache_payload(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            self.delete(cache_key)
            return None
        context.funding_trace_from_persistent_cache = True
        context.funding_trace_cache_status = str(status or "")
        return str(status or ""), context

    def put(self, cache_key: str, wallet: str, as_of_bucket: str, context: FundingContext) -> bool:
        if not self.enabled:
            return False
        status, ttl_seconds = self._status_and_ttl(context)
        if ttl_seconds <= 0:
            return False
        now = time.time()
        payload = _funding_context_to_cache_payload(context)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO funding_trace_cache (
                        cache_key, schema_version, wallet, as_of_bucket, chain,
                        contract_set, lookback_settings, trace_settings_version,
                        status, context_json, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cache_key,
                        self.schema_version,
                        wallet.lower(),
                        as_of_bucket,
                        "polygon",
                        ",".join(address.lower() for address in USDC_ADDRESSES),
                        f"{SEARCH_WINDOW_BLOCKS}:{MAX_SEARCH_BLOCKS}",
                        FUNDING_TRACE_SETTINGS_VERSION,
                        status,
                        json.dumps(payload, sort_keys=True),
                        now,
                        now + ttl_seconds,
                    ),
                )
            return True
        except sqlite3.DatabaseError as exc:
            self._disable(f"sqlite_error:{type(exc).__name__}: {exc}")
            return False

    def delete(self, cache_key: str) -> None:
        if not self.enabled:
            return
        try:
            with closing(self._connect()) as connection:
                connection.execute("DELETE FROM funding_trace_cache WHERE cache_key = ?", (cache_key,))
        except sqlite3.DatabaseError:
            return

    def _status_and_ttl(self, context: FundingContext) -> tuple[str, int]:
        if context.error:
            return "failure", self.failure_ttl_seconds
        if context.funding_evidence_grade == FUNDING_EVIDENCE_UNKNOWN:
            return "failure", self.failure_ttl_seconds
        if not context.funding_found:
            return "none", self.none_ttl_seconds
        return "success", self.ttl_seconds

    def _ensure_schema(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS funding_trace_cache_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                row = connection.execute(
                    "SELECT value FROM funding_trace_cache_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is not None and str(row[0]) != str(self.schema_version):
                    connection.execute("DROP TABLE IF EXISTS funding_trace_cache")
                    connection.execute("DELETE FROM funding_trace_cache_meta")
                    self.schema_mismatch_handled = True
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS funding_trace_cache (
                        cache_key TEXT PRIMARY KEY,
                        schema_version INTEGER NOT NULL,
                        wallet TEXT NOT NULL,
                        as_of_bucket TEXT NOT NULL,
                        chain TEXT NOT NULL,
                        contract_set TEXT NOT NULL,
                        lookback_settings TEXT NOT NULL,
                        trace_settings_version TEXT NOT NULL,
                        status TEXT NOT NULL,
                        context_json TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        expires_at REAL NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT OR REPLACE INTO funding_trace_cache_meta (key, value)
                    VALUES ('schema_version', ?)
                    """,
                    (str(self.schema_version),),
                )
        except sqlite3.DatabaseError as exc:
            self._disable(f"sqlite_error:{type(exc).__name__}: {exc}")

    def _handle_schema_mismatch(self) -> None:
        self.schema_mismatch_handled = True
        try:
            with closing(self._connect()) as connection:
                connection.execute("DROP TABLE IF EXISTS funding_trace_cache")
                connection.execute("DELETE FROM funding_trace_cache_meta")
        except sqlite3.DatabaseError:
            return
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, isolation_level=None)

    def _disable(self, reason: str) -> None:
        self.enabled = False
        self.disabled_reason = reason


class FundingResolver:
    def __init__(
        self,
        rpc_url: str | None = None,
        *,
        trace_mode: str | None = None,
        persistent_cache: FundingTracePersistentCache | None = None,
        persistent_cache_path: Path | None = None,
        persistent_cache_enabled: bool | None = None,
    ) -> None:
        self._rpc_urls = polygon_rpc_urls(rpc_url)
        self._rpc_url = self._rpc_urls[0]
        self._endpoint_states = [
            RpcEndpointState(url=url, label=endpoint_label(url))
            for url in self._rpc_urls
        ]
        self._endpoint_by_url = {endpoint.url: endpoint for endpoint in self._endpoint_states}
        self._endpoint_cursor = 0
        self._disabled_rpc_urls: dict[str, str] = {}
        self._block_timestamp_cache: dict[int, int] = {}
        self._log_chunk_cache: dict[tuple[str, int, int, str], list[dict[str, object]]] = {}
        self._analysis_cache: dict[tuple[str, str], FundingContext] = {}
        self._latest_block_number: int | None = None
        self._rpc_disabled_reason: str | None = None
        self._rpc_auth_error = False
        self._last_error = ""
        self._trace_attempted_count = 0
        self._trace_succeeded_count = 0
        self._trace_failed_count = 0
        self._trace_skipped_count = 0
        self._trace_skipped_reasons: Counter[str] = Counter()
        self._endpoint_failure_distribution: Counter[str] = Counter()
        self._rate_limited_count = 0
        self._retry_count = 0
        self._fallback_endpoint_count = 0
        self._log_chunks_attempted = 0
        self._log_chunks_succeeded = 0
        self._log_chunks_failed = 0
        self._log_chunks_rate_limited = 0
        self._cache_hit_count = 0
        self._cache_miss_count = 0
        self._persistent_cache_hit_count = 0
        self._persistent_cache_miss_count = 0
        self._persistent_cache_write_count = 0
        self._persistent_cache_expired_count = 0
        self._persistent_cache_failure_cooldown_count = 0
        self._validation_mode_enabled = bool(
            runtime_env_int("INSPOLY_VALIDATION_MODE", 0, minimum=0)
        )
        self._validation_allow_network_funding = bool(
            runtime_env_int(
                "INSPOLY_VALIDATION_ALLOW_NETWORK_FUNDING",
                DEFAULT_VALIDATION_ALLOW_NETWORK_FUNDING,
                minimum=0,
            )
        )
        default_trace_mode = FUNDING_TRACE_MODE_LIVE_RPC if rpc_url is not None and trace_mode is None else funding_trace_mode()
        self._funding_trace_mode = normalize_funding_trace_mode(
            trace_mode,
            default=default_trace_mode,
        )
        if (
            self._funding_trace_mode == FUNDING_TRACE_MODE_LIVE_RPC
            and self._validation_mode_enabled
            and not self._validation_allow_network_funding
        ):
            self._funding_trace_mode = FUNDING_TRACE_MODE_CACHE_ONLY
        if self._funding_trace_mode == FUNDING_TRACE_MODE_DISABLED:
            self._rpc_disabled_reason = "funding_trace_disabled_no_rpc_mode"
        self._validation_max_funding_traces = runtime_env_int(
            "INSPOLY_VALIDATION_MAX_FUNDING_TRACES_PER_BUNDLE",
            DEFAULT_VALIDATION_MAX_FUNDING_TRACES_PER_BUNDLE,
            minimum=0,
        )
        self._validation_max_trace_failures = runtime_env_int(
            "INSPOLY_VALIDATION_MAX_FUNDING_TRACE_FAILURES_PER_BUNDLE",
            DEFAULT_VALIDATION_MAX_FUNDING_TRACE_FAILURES_PER_BUNDLE,
            minimum=0,
        )
        self._validation_max_consecutive_rpc_failures = runtime_env_int(
            "INSPOLY_VALIDATION_MAX_CONSECUTIVE_RPC_FAILURES",
            DEFAULT_VALIDATION_MAX_CONSECUTIVE_RPC_FAILURES,
            minimum=0,
        )
        self._validation_network_trace_count = 0
        self._validation_network_failure_count = 0
        self._validation_consecutive_rpc_failures = 0
        self._validation_rpc_failure_limit_hit = False
        self._validation_funding_trace_limit_hit = False
        self._validation_abort_reason = ""
        self._max_concurrency = runtime_env_int(
            "INSPOLY_POLYGON_RPC_MAX_CONCURRENCY",
            DEFAULT_RPC_MAX_CONCURRENCY,
            minimum=1,
        )
        self._min_interval_seconds = runtime_env_float(
            "INSPOLY_POLYGON_RPC_MIN_INTERVAL_SECONDS",
            DEFAULT_RPC_MIN_INTERVAL_SECONDS,
            minimum=0.0,
        )
        self._max_retries = runtime_env_int(
            "INSPOLY_POLYGON_RPC_MAX_RETRIES",
            DEFAULT_RPC_MAX_RETRIES,
            minimum=1,
        )
        self._cooldown_seconds = runtime_env_float(
            "INSPOLY_POLYGON_RPC_429_COOLDOWN_SECONDS",
            DEFAULT_RPC_429_COOLDOWN_SECONDS,
            minimum=0.0,
        )
        self._getlogs_block_chunk = runtime_env_int(
            "INSPOLY_POLYGON_RPC_GETLOGS_BLOCK_CHUNK",
            DEFAULT_RPC_GETLOGS_BLOCK_CHUNK,
            minimum=1,
        )
        self._request_timeout_seconds = runtime_env_float(
            "INSPOLY_POLYGON_RPC_REQUEST_TIMEOUT_SECONDS",
            DEFAULT_VALIDATION_RPC_REQUEST_TIMEOUT_SECONDS
            if self._validation_mode_enabled
            else DEFAULT_RPC_REQUEST_TIMEOUT_SECONDS,
            minimum=1.0,
        )
        self._disable_http_retries = bool(
            runtime_env_int(
                "INSPOLY_POLYGON_RPC_DISABLE_HTTP_RETRIES",
                1 if self._validation_mode_enabled else 0,
                minimum=0,
            )
        )
        self._error_cooldown_seconds = runtime_env_float(
            "INSPOLY_POLYGON_RPC_ERROR_COOLDOWN_SECONDS",
            self._cooldown_seconds if self._validation_mode_enabled else 0.0,
            minimum=0.0,
        )
        self._cooldown_getlogs_network_errors = bool(
            runtime_env_int(
                "INSPOLY_VALIDATION_COOLDOWN_GETLOGS_NETWORK_ERRORS",
                1 if self._validation_mode_enabled else 0,
                minimum=0,
            )
        )
        self._validation_max_log_chunks_per_trace = runtime_env_int(
            "INSPOLY_VALIDATION_MAX_LOG_CHUNKS_PER_TRACE",
            DEFAULT_VALIDATION_MAX_LOG_CHUNKS_PER_TRACE
            if self._validation_mode_enabled
            else 0,
            minimum=0,
        )
        self._validation_approximate_block_lookup = bool(
            runtime_env_int(
                "INSPOLY_VALIDATION_APPROXIMATE_BLOCK_LOOKUP",
                1 if self._validation_mode_enabled else 0,
                minimum=0,
            )
        )
        self._average_block_seconds = runtime_env_float(
            "INSPOLY_POLYGON_AVERAGE_BLOCK_SECONDS",
            DEFAULT_POLYGON_AVERAGE_BLOCK_SECONDS,
            minimum=0.1,
        )
        self._rpc_semaphore = threading.BoundedSemaphore(self._max_concurrency)
        self._endpoint_lock = threading.Lock()
        self._next_request_at_by_url = {url: 0.0 for url in self._rpc_urls}
        if persistent_cache is not None:
            self._persistent_cache = persistent_cache
        else:
            enabled = (
                bool(persistent_cache_enabled)
                if persistent_cache_enabled is not None
                else bool(
                    runtime_env_int(
                        "INSPOLY_FUNDING_TRACE_CACHE_ENABLED",
                        DEFAULT_FUNDING_TRACE_CACHE_ENABLED,
                        minimum=0,
                    )
                )
            )
            self._persistent_cache = FundingTracePersistentCache(
                persistent_cache_path,
                enabled=enabled,
                ttl_hours=runtime_env_int(
                    "INSPOLY_FUNDING_TRACE_CACHE_TTL_HOURS",
                    DEFAULT_FUNDING_TRACE_CACHE_TTL_HOURS,
                    minimum=0,
                ),
                none_ttl_hours=runtime_env_int(
                    "INSPOLY_FUNDING_TRACE_NONE_TTL_HOURS",
                    DEFAULT_FUNDING_TRACE_NONE_TTL_HOURS,
                    minimum=0,
                ),
                failure_ttl_minutes=runtime_env_int(
                    "INSPOLY_FUNDING_TRACE_FAILURE_TTL_MINUTES",
                    DEFAULT_FUNDING_TRACE_FAILURE_TTL_MINUTES,
                    minimum=0,
                ),
            )

    def analyze(self, wallet: str, as_of: datetime) -> FundingContext:
        if self._funding_trace_mode == FUNDING_TRACE_MODE_DISABLED:
            reason = "funding_trace_disabled_no_rpc_mode"
            self._rpc_disabled_reason = reason
            self._last_error = reason
            self.record_trace_skipped(reason)
            return unknown_funding_context(reason)

        normalized_wallet = wallet.lower()
        as_of_bucket = as_of.astimezone(UTC).strftime("%Y%m%d%H")
        cache_key = (normalized_wallet, as_of_bucket)
        cached = self._analysis_cache.get(cache_key)
        if cached is not None:
            self._cache_hit_count += 1
            if self._rpc_disabled_reason is not None and cached.error:
                self.record_trace_skipped("funding_resolver_unavailable")
            return copy.deepcopy(cached)
        self._cache_miss_count += 1
        persistent_key = _persistent_cache_key(normalized_wallet, as_of_bucket)
        persistent_lookup = self._persistent_cache.get(persistent_key)
        if persistent_lookup is not None:
            status, context = persistent_lookup
            self._persistent_cache_hit_count += 1
            self._trace_attempted_count += 1
            if status in {"success", "none"} and context.error is None:
                self._trace_succeeded_count += 1
            else:
                self._persistent_cache_failure_cooldown_count += 1
                self._trace_failed_count += 1
                self._last_error = context.error or "funding_trace_cached_failure"
            self._analysis_cache[cache_key] = copy.deepcopy(context)
            return context
        self._persistent_cache_miss_count += 1
        if self._funding_trace_mode == FUNDING_TRACE_MODE_CACHE_ONLY:
            reason = (
                "validation_cache_only_network_disabled"
                if self._validation_mode_enabled and not self._validation_allow_network_funding
                else "funding_trace_cache_only_miss"
            )
            if reason == "validation_cache_only_network_disabled":
                self._validation_abort_reason = reason
            self.record_trace_skipped(reason)
            return unknown_funding_context(reason)
        if self._rpc_disabled_reason is not None:
            current_disabled_reason = self._resolver_disabled_reason(None)
            if current_disabled_reason is not None:
                self.record_trace_skipped("funding_resolver_unavailable")
                self._rpc_disabled_reason = current_disabled_reason
                return unknown_funding_context(current_disabled_reason)
            self._rpc_disabled_reason = None
        validation_block_reason = self._validation_network_block_reason()
        if validation_block_reason is not None:
            self.record_trace_skipped(validation_block_reason)
            return unknown_funding_context(validation_block_reason)
        self._trace_attempted_count += 1
        self._validation_network_trace_count += 1
        try:
            trade_block = self._block_before_timestamp(as_of)
            if trade_block is None:
                context = self._failed_context("funding_trace_incomplete:block_lookup_failed")
                self._record_validation_trace_failure(context.error or "block_lookup_failed")
                self._analysis_cache[cache_key] = copy.deepcopy(context)
                self._write_persistent_cache(persistent_key, normalized_wallet, as_of_bucket, context)
                return context
            first_hop = self._latest_usdc_transfer_to(normalized_wallet, trade_block)
            if first_hop is None:
                self._trace_succeeded_count += 1
                self._record_validation_trace_success()
                context = FundingContext(funding_found=False)
                self._analysis_cache[cache_key] = copy.deepcopy(context)
                self._write_persistent_cache(persistent_key, normalized_wallet, as_of_bucket, context)
                return context

            source_label, source_type, source_category = _classify_address(first_hop.from_address)
            origin_address = first_hop.from_address
            origin_label = source_label
            origin_type = source_type
            origin_category = source_category
            funding_depth = 1

            if source_category == "unknown":
                second_hop = self._latest_usdc_transfer_to(first_hop.from_address, first_hop.block_number - 1)
                if second_hop is not None:
                    funding_depth = 2
                    origin_address = second_hop.from_address
                    origin_label, origin_type, origin_category = _classify_address(origin_address)

            minutes_from_funding = max((as_of - first_hop.timestamp).total_seconds() / 60, 0.0)
            suspicious_score = _suspiciousness_score(
                origin_category=origin_category,
                funding_depth=funding_depth,
                funding_found=True,
            )
            recent_funding_flag = minutes_from_funding <= 24 * 60 and first_hop.amount_usdc >= 2500.0
            suspicious_funding_flag = recent_funding_flag and suspicious_score >= 0.6
            amount_band = _bucketed_amount_band(first_hop.amount_usdc)
            time_band = _bucketed_time_band(first_hop.timestamp)
            strict_key = _strict_funding_graph_key(origin_address, origin_category)
            proxy_key = _proxy_funding_graph_key(
                source_label=source_label,
                source_address=first_hop.from_address,
                source_category=source_category,
                timestamp=first_hop.timestamp,
                amount_usdc=first_hop.amount_usdc,
            )
            funding_fingerprint = _funding_fingerprint(
                source_label=source_label,
                source_address=first_hop.from_address,
                timestamp=first_hop.timestamp,
                amount_usdc=first_hop.amount_usdc,
                funding_depth=funding_depth,
            )
            evidence_grade = _funding_evidence_grade(
                funding_found=True,
                source_category=source_category,
                origin_category=origin_category,
                funding_depth=funding_depth,
                suspicious_funding_flag=suspicious_funding_flag,
                funding_graph_key_strict=strict_key,
            )

            self._trace_succeeded_count += 1
            self._record_validation_trace_success()
            context = FundingContext(
                funding_found=True,
                source_address=first_hop.from_address,
                source_label=source_label,
                source_type=source_type,
                source_category=source_category,
                origin_address=origin_address,
                origin_label=origin_label,
                origin_type=origin_type,
                origin_category=origin_category,
                funding_tx_hash=first_hop.tx_hash,
                funding_timestamp=first_hop.timestamp,
                funding_amount_usdc=first_hop.amount_usdc,
                minutes_from_funding_to_trade=minutes_from_funding,
                funding_velocity_label=_velocity_label(minutes_from_funding),
                suspicious_funding_score=suspicious_score,
                suspicious_funding_flag=suspicious_funding_flag,
                recent_external_funding_flag=recent_funding_flag,
                funding_depth=funding_depth,
                funding_graph_key=strict_key or proxy_key,
                funding_graph_key_strict=strict_key,
                funding_graph_key_proxy=proxy_key,
                funding_fingerprint=funding_fingerprint,
                funding_evidence_grade=evidence_grade,
            )
            self._analysis_cache[cache_key] = copy.deepcopy(context)
            self._write_persistent_cache(persistent_key, normalized_wallet, as_of_bucket, context)
            return context
        except Exception as exc:
            context = self._failed_context(f"{type(exc).__name__}: {exc}")
            self._record_validation_trace_failure(context.error or f"{type(exc).__name__}: {exc}")
            self._analysis_cache[cache_key] = copy.deepcopy(context)
            self._write_persistent_cache(persistent_key, normalized_wallet, as_of_bucket, context)
            return context

    def _validation_network_block_reason(self) -> str | None:
        if not self._validation_mode_enabled:
            return None
        if not self._validation_allow_network_funding:
            self._validation_abort_reason = "validation_cache_only_network_disabled"
            return self._validation_abort_reason
        if (
            self._validation_max_funding_traces >= 0
            and self._validation_network_trace_count >= self._validation_max_funding_traces
        ):
            self._validation_funding_trace_limit_hit = True
            self._validation_abort_reason = "validation_funding_trace_limit_hit"
            return self._validation_abort_reason
        if (
            self._validation_max_trace_failures >= 0
            and self._validation_network_failure_count >= self._validation_max_trace_failures
        ):
            self._validation_rpc_failure_limit_hit = True
            self._validation_abort_reason = "validation_rpc_failure_limit_hit"
            return self._validation_abort_reason
        if (
            self._validation_max_consecutive_rpc_failures >= 0
            and self._validation_consecutive_rpc_failures >= self._validation_max_consecutive_rpc_failures
        ):
            self._validation_rpc_failure_limit_hit = True
            self._validation_abort_reason = "validation_consecutive_rpc_failure_limit_hit"
            return self._validation_abort_reason
        return None

    def _record_validation_trace_success(self) -> None:
        if self._validation_mode_enabled:
            self._validation_consecutive_rpc_failures = 0

    def _record_validation_trace_failure(self, reason: str) -> None:
        if not self._validation_mode_enabled:
            return
        self._validation_network_failure_count += 1
        self._validation_consecutive_rpc_failures += 1
        if (
            self._validation_max_trace_failures >= 0
            and self._validation_network_failure_count >= self._validation_max_trace_failures
        ):
            self._validation_rpc_failure_limit_hit = True
            self._validation_abort_reason = "validation_rpc_failure_limit_hit"
        if (
            self._validation_max_consecutive_rpc_failures >= 0
            and self._validation_consecutive_rpc_failures >= self._validation_max_consecutive_rpc_failures
        ):
            self._validation_rpc_failure_limit_hit = True
            self._validation_abort_reason = "validation_consecutive_rpc_failure_limit_hit"

    def _write_persistent_cache(
        self,
        cache_key: str,
        wallet: str,
        as_of_bucket: str,
        context: FundingContext,
    ) -> None:
        if self._persistent_cache.put(cache_key, wallet, as_of_bucket, context):
            self._persistent_cache_write_count += 1

    def _block_before_timestamp(self, value: datetime) -> int | None:
        target_ts = int(value.astimezone(UTC).timestamp())
        latest_block = self._latest_block_number_value()
        if latest_block is None:
            return None
        latest_ts = self._block_timestamp(latest_block)
        if latest_ts is None:
            return None
        if target_ts >= latest_ts:
            return latest_block
        if self._validation_mode_enabled and self._validation_approximate_block_lookup:
            delta_seconds = max(latest_ts - target_ts, 0)
            estimated_delta_blocks = int(delta_seconds / max(self._average_block_seconds, 0.1))
            return max(1, min(latest_block, latest_block - estimated_delta_blocks))

        low = 1
        high = latest_block
        best = None
        while low <= high:
            mid = (low + high) // 2
            block_ts = self._block_timestamp(mid)
            if block_ts is None:
                return best
            if block_ts <= target_ts:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        return best

    def _latest_usdc_transfer_to(self, to_address: str, to_block: int) -> FundingTransfer | None:
        end_block = to_block
        searched = 0
        log_chunks_checked = 0
        padded_to = _topic_address(to_address)
        while end_block > 0 and searched < MAX_SEARCH_BLOCKS:
            start_block = max(0, end_block - SEARCH_WINDOW_BLOCKS + 1)
            chunk_end = end_block
            while chunk_end >= start_block:
                chunk_start = max(start_block, chunk_end - self._getlogs_block_chunk + 1)
                logs: list[dict[str, object]] = []
                for token in USDC_ADDRESSES:
                    if (
                        self._validation_mode_enabled
                        and self._validation_max_log_chunks_per_trace > 0
                        and log_chunks_checked >= self._validation_max_log_chunks_per_trace
                    ):
                        raise FundingTraceBudgetExceeded(
                            "validation_funding_trace_log_chunk_limit_hit"
                        )
                    logs.extend(self._get_usdc_logs_chunk(token, chunk_start, chunk_end, padded_to))
                    log_chunks_checked += 1
                if logs:
                    selected = max(logs, key=_log_sort_key)
                    return self._parse_transfer_log(selected)
                chunk_end = chunk_start - 1
            searched += end_block - start_block + 1
            end_block = start_block - 1
        return None

    def _get_usdc_logs_chunk(
        self,
        token: str,
        start_block: int,
        end_block: int,
        padded_to: str,
    ) -> list[dict[str, object]]:
        cache_key = (token.lower(), start_block, end_block, padded_to)
        cached = self._log_chunk_cache.get(cache_key)
        if cached is not None:
            self._cache_hit_count += 1
            return [dict(item) for item in cached]
        self._cache_miss_count += 1
        self._log_chunks_attempted += 1
        try:
            response = self._rpc(
                "eth_getLogs",
                [
                    {
                        "fromBlock": hex(start_block),
                        "toBlock": hex(end_block),
                        "address": token,
                        "topics": [TRANSFER_EVENT_TOPIC, None, padded_to],
                    }
                ],
            )
        except Exception as exc:
            self._log_chunks_failed += 1
            if _is_rate_limit_error_text(str(exc)):
                self._log_chunks_rate_limited += 1
            raise
        if isinstance(response, list):
            logs = [item for item in response if isinstance(item, dict)]
            self._log_chunk_cache[cache_key] = [dict(item) for item in logs]
            self._log_chunks_succeeded += 1
            return logs
        self._log_chunks_failed += 1
        raise ValueError("Malformed eth_getLogs response")

    def _parse_transfer_log(self, log: dict[str, object]) -> FundingTransfer:
        topics = log.get("topics") or []
        if not isinstance(topics, list) or len(topics) < 3:
            raise ValueError("Malformed transfer log")
        from_address = "0x" + str(topics[1])[-40:].lower()
        to_address = "0x" + str(topics[2])[-40:].lower()
        amount_hex = str(log.get("data") or "0x0")
        block_number = int(str(log.get("blockNumber") or "0x0"), 16)
        timestamp_raw = self._block_timestamp(block_number)
        timestamp = datetime.fromtimestamp(timestamp_raw or 0, tz=UTC)
        return FundingTransfer(
            from_address=from_address,
            to_address=to_address,
            amount_usdc=int(amount_hex, 16) / 1_000_000,
            tx_hash=str(log.get("transactionHash") or ""),
            block_number=block_number,
            timestamp=timestamp,
        )

    def _latest_block_number_value(self) -> int | None:
        if self._latest_block_number is not None:
            return self._latest_block_number
        raw = self._rpc("eth_blockNumber", [])
        if not isinstance(raw, str):
            return None
        self._latest_block_number = int(raw, 16)
        return self._latest_block_number

    def _block_timestamp(self, block_number: int) -> int | None:
        cached = self._block_timestamp_cache.get(block_number)
        if cached is not None:
            return cached
        raw = self._rpc("eth_getBlockByNumber", [hex(block_number), False])
        if not isinstance(raw, dict):
            return None
        timestamp_hex = raw.get("timestamp")
        if not isinstance(timestamp_hex, str):
            return None
        value = int(timestamp_hex, 16)
        self._block_timestamp_cache[block_number] = value
        return value

    def _rpc(self, method: str, params: list[object]) -> object:
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        last_error: Exception | None = None
        endpoint_attempts = 0
        max_attempts = max(1, self._max_retries) * max(1, len(self._endpoint_states))
        while endpoint_attempts < max_attempts:
            endpoint = self._next_endpoint()
            if endpoint is None:
                break
            if endpoint_attempts > 0:
                self._retry_count += 1
                self._fallback_endpoint_count += 1
            endpoint_attempts += 1
            self._rpc_url = endpoint.url
            try:
                response = self._post_endpoint(endpoint, payload)
            except Exception as exc:
                last_error = exc
                self._record_endpoint_failure(endpoint, exc)
                if _is_auth_http_error(exc):
                    self._rpc_auth_error = True
                    endpoint.disabled = True
                    self._disabled_rpc_urls[endpoint.url] = f"{type(exc).__name__}: {exc}"
                    self._last_error = self._disabled_rpc_urls[endpoint.url]
                    continue
                if _is_rate_limit_error_text(str(exc)):
                    self._cooldown_endpoint(endpoint, f"{type(exc).__name__}: {exc}")
                    continue
                if self._should_cooldown_endpoint_after_error(method, exc):
                    self._cooldown_endpoint(
                        endpoint,
                        f"{type(exc).__name__}: {exc}",
                        status="cooldown_after_error",
                        seconds=self._error_cooldown_seconds,
                    )
                    continue
                continue
            if not isinstance(response, dict):
                last_error = ValueError(f"Invalid RPC response for {method}")
                self._record_endpoint_failure(endpoint, last_error)
                continue
            if response.get("error"):
                last_error = ValueError(str(response["error"]))
                if _is_auth_error_text(str(response["error"])):
                    self._rpc_auth_error = True
                    endpoint.disabled = True
                    self._disabled_rpc_urls[endpoint.url] = f"RPCError: {response['error']}"
                    self._last_error = self._disabled_rpc_urls[endpoint.url]
                    self._record_endpoint_failure(endpoint, last_error)
                    continue
                if _is_rate_limit_error_text(str(response["error"])):
                    self._record_endpoint_failure(endpoint, last_error)
                    self._cooldown_endpoint(endpoint, f"RPCError: {response['error']}")
                    continue
                self._record_endpoint_failure(endpoint, last_error)
                if self._should_cooldown_endpoint_after_error(method, last_error):
                    self._cooldown_endpoint(
                        endpoint,
                        f"RPCError: {response['error']}",
                        status="cooldown_after_error",
                        seconds=self._error_cooldown_seconds,
                    )
                    continue
                continue
            endpoint.success_count += 1
            endpoint.last_error = ""
            self._rpc_disabled_reason = None
            if method == "eth_blockNumber":
                endpoint.lightweight_health_status = "lightweight_available"
            elif method == "eth_getLogs":
                endpoint.funding_trace_health_status = "funding_trace_available"
            return response.get("result")
        self._rpc_disabled_reason = self._resolver_disabled_reason(last_error)
        if last_error is not None:
            self._last_error = f"{type(last_error).__name__}: {last_error}"
            raise last_error
        raise ValueError(f"No Polygon RPC endpoint available for {method}")

    def _post_endpoint(self, endpoint: RpcEndpointState, payload: dict[str, object]) -> object:
        self._respect_endpoint_min_interval(endpoint)
        with self._rpc_semaphore:
            endpoint.request_count += 1
            timeout = max(1, int(round(self._request_timeout_seconds)))
            if self._disable_http_retries:
                return _post_json_once(endpoint.url, payload, timeout=timeout)
            return _post_json(endpoint.url, payload, timeout=timeout)

    def _respect_endpoint_min_interval(self, endpoint: RpcEndpointState) -> None:
        if self._min_interval_seconds <= 0:
            return
        while True:
            with self._endpoint_lock:
                now = time.monotonic()
                next_allowed = self._next_request_at_by_url.get(endpoint.url, 0.0)
                if now >= next_allowed:
                    self._next_request_at_by_url[endpoint.url] = now + self._min_interval_seconds
                    return
                wait_for = next_allowed - now
            if wait_for > 0:
                time.sleep(min(wait_for, self._min_interval_seconds))

    def _next_endpoint(self) -> RpcEndpointState | None:
        now = time.monotonic()
        preferred = [
            endpoint
            for endpoint in self._endpoint_states
            if endpoint.funding_trace_health_status == "funding_trace_available"
        ]
        base_order = preferred + [endpoint for endpoint in self._endpoint_states if endpoint not in preferred]
        if base_order:
            cursor = self._endpoint_cursor % len(base_order)
            ordered = base_order[cursor:] + base_order[:cursor]
        else:
            ordered = []
        for endpoint in ordered:
            if endpoint.disabled:
                continue
            if endpoint.in_cooldown(now):
                continue
            self._endpoint_cursor = (base_order.index(endpoint) + 1) % max(1, len(base_order))
            return endpoint
        return None

    def _record_endpoint_failure(self, endpoint: RpcEndpointState, exc: Exception) -> None:
        error_text = f"{type(exc).__name__}: {exc}"
        endpoint.failure_count += 1
        endpoint.last_error = error_text
        reason = _funding_resolver_unavailable_reason(
            error_text,
            auth_error=_is_auth_error_text(error_text),
            endpoint_label=endpoint.label,
        )
        self._endpoint_failure_distribution[reason] += 1
        if reason == "rate_limited":
            endpoint.rate_limited_count += 1
            self._rate_limited_count += 1

    def _cooldown_endpoint(
        self,
        endpoint: RpcEndpointState,
        reason: str,
        *,
        status: str = "rate_limited",
        seconds: float | None = None,
    ) -> None:
        endpoint.cooldown_until = time.monotonic() + (self._cooldown_seconds if seconds is None else seconds)
        endpoint.last_error = reason
        endpoint.funding_trace_health_status = status

    def _should_cooldown_endpoint_after_error(self, method: str, exc: Exception) -> bool:
        if not self._validation_mode_enabled:
            return False
        if self._error_cooldown_seconds <= 0:
            return False
        if method != "eth_getLogs" or not self._cooldown_getlogs_network_errors:
            return False
        text = f"{type(exc).__name__}: {exc}".lower()
        if _is_auth_error_text(text) or _is_rate_limit_error_text(text):
            return False
        return any(
            token in text
            for token in (
                "timed out",
                "timeout",
                "network",
                "http error",
                "http 400",
                "http 408",
                "http 500",
                "http 502",
                "http 503",
                "http 504",
            )
        )

    def _resolver_disabled_reason(self, last_error: Exception | None) -> str | None:
        active = [endpoint for endpoint in self._endpoint_states if not endpoint.disabled]
        if not active:
            if self._disabled_rpc_urls:
                return "; ".join(self._disabled_rpc_urls.values())
            return "No configured Polygon RPC endpoints are available."
        if all(endpoint.in_cooldown() for endpoint in active):
            reasons = [
                endpoint.last_error or "endpoint cooling down"
                for endpoint in active
            ]
            return "; ".join(reasons)
        if last_error is not None and not any(endpoint.success_count for endpoint in self._endpoint_states):
            return f"{type(last_error).__name__}: {last_error}"
        return None

    @property
    def rpc_disabled_reason(self) -> str | None:
        return self._rpc_disabled_reason

    @property
    def rpc_auth_error(self) -> bool:
        return self._rpc_auth_error

    def record_trace_skipped(self, reason: str) -> None:
        normalized = (reason or "unknown").strip() or "unknown"
        self._trace_skipped_count += 1
        self._trace_skipped_reasons[normalized] += 1

    def health(self) -> FundingResolverHealth:
        attempted = self._trace_attempted_count
        coverage = (self._trace_succeeded_count / attempted) if attempted else 0.0
        disabled_reason = self._rpc_disabled_reason or (
            self._last_error if self._trace_failed_count and not self._trace_succeeded_count else ""
        )
        functional_status = self._functional_status(disabled_reason)
        endpoint_available_count = sum(
            1
            for endpoint in self._endpoint_states
            if not endpoint.disabled and not endpoint.in_cooldown()
        )
        endpoint_cooldown_count = sum(
            1 for endpoint in self._endpoint_states if endpoint.in_cooldown()
        )
        validation_bundle_status, validation_funding_status = self._validation_statuses()
        trace_disabled_reason = ""
        if self._funding_trace_mode == FUNDING_TRACE_MODE_DISABLED:
            trace_disabled_reason = "funding_trace_disabled_no_rpc_mode"
        elif self._funding_trace_mode == FUNDING_TRACE_MODE_CACHE_ONLY:
            trace_disabled_reason = "funding_trace_cache_only_mode"
        return FundingResolverHealth(
            fundingResolverAvailable=functional_status == "available_for_funding_trace",
            fundingResolverDisabledReason=disabled_reason,
            fundingResolverAuthError=self._rpc_auth_error,
            fundingResolverUnavailableReason=(
                "" if not disabled_reason else _funding_resolver_unavailable_reason(
                    disabled_reason,
                    auth_error=self._rpc_auth_error,
                    endpoint_label=endpoint_label(self._rpc_url),
                )
            ),
            fundingResolverFunctionalStatus=functional_status,
            fundingResolverEndpointLabel=endpoint_label(self._rpc_url),
            fundingResolverLastError=self._last_error or disabled_reason,
            fundingTraceMode=self._funding_trace_mode,
            fundingTraceDisabledReason=trace_disabled_reason,
            fundingEvidenceInterpretation=_funding_evidence_interpretation(self._funding_trace_mode),
            fundingTraceAttemptedCount=attempted,
            fundingTraceSucceededCount=self._trace_succeeded_count,
            fundingTraceFailedCount=self._trace_failed_count,
            fundingTraceSkippedCount=self._trace_skipped_count,
            fundingTraceSkippedReasonDistribution=dict(sorted(self._trace_skipped_reasons.items())),
            fundingTraceCoverageRatio=round(coverage, 4),
            fundingTraceEndpointPoolSize=len(self._endpoint_states),
            fundingTraceEndpointAvailableCount=endpoint_available_count,
            fundingTraceEndpointCooldownCount=endpoint_cooldown_count,
            fundingTraceEndpointFailureDistribution=dict(sorted(self._endpoint_failure_distribution.items())),
            fundingTraceEndpointSummary=[endpoint.to_dict() for endpoint in self._endpoint_states],
            fundingTraceRateLimitedCount=self._rate_limited_count,
            fundingTraceRetryCount=self._retry_count,
            fundingTraceFallbackEndpointCount=self._fallback_endpoint_count,
            fundingTraceLogChunksAttempted=self._log_chunks_attempted,
            fundingTraceLogChunksSucceeded=self._log_chunks_succeeded,
            fundingTraceLogChunksFailed=self._log_chunks_failed,
            fundingTraceLogChunksRateLimited=self._log_chunks_rate_limited,
            fundingTraceCacheHitCount=self._cache_hit_count,
            fundingTraceCacheMissCount=self._cache_miss_count,
            fundingTracePersistentCacheEnabled=bool(self._persistent_cache.enabled),
            fundingTracePersistentCacheHitCount=self._persistent_cache_hit_count,
            fundingTracePersistentCacheMissCount=self._persistent_cache_miss_count,
            fundingTracePersistentCacheWriteCount=self._persistent_cache_write_count,
            fundingTracePersistentCacheExpiredCount=(
                self._persistent_cache_expired_count + self._persistent_cache.expired_count
            ),
            fundingTracePersistentCacheFailureCooldownCount=self._persistent_cache_failure_cooldown_count,
            fundingTracePersistentCacheSchemaVersion=FUNDING_TRACE_CACHE_SCHEMA_VERSION,
            validationBundleStatus=validation_bundle_status,
            validationFundingStatus=validation_funding_status,
            validationAbortReason=self._validation_abort_reason,
            validationTimedOut=False,
            validationFundingTimedOut=False,
            validationRpcFailureLimitHit=self._validation_rpc_failure_limit_hit,
            validationFundingTraceLimitHit=self._validation_funding_trace_limit_hit,
        )

    def _validation_statuses(self) -> tuple[str, str]:
        if not self._validation_mode_enabled:
            return "", ""
        if self._funding_trace_mode == FUNDING_TRACE_MODE_DISABLED:
            return "completed_cache_only", "disabled_no_rpc"
        if self._validation_funding_trace_limit_hit:
            return "completed_funding_blocked", "trace_limit_hit"
        if self._validation_rpc_failure_limit_hit:
            return "completed_funding_blocked", "rpc_failure_limit_hit"
        if not self._validation_allow_network_funding:
            return "completed_cache_only", "cache_only"
        if self._trace_attempted_count == 0:
            return "completed_no_funding_candidates", "not_assessed"
        if self._trace_succeeded_count > 0:
            return "completed_funding_enabled", "funding_enabled"
        if self._trace_failed_count > 0 or self._trace_skipped_count > 0:
            return "completed_funding_blocked", "funding_blocked"
        return "completed_no_funding_candidates", "not_assessed"

    def _functional_status(self, disabled_reason: str) -> str:
        if self._funding_trace_mode == FUNDING_TRACE_MODE_DISABLED:
            return "disabled_no_rpc_mode"
        if self._funding_trace_mode == FUNDING_TRACE_MODE_CACHE_ONLY:
            return "cache_only"
        if self._trace_succeeded_count > 0:
            return "available_for_funding_trace"
        if not self._endpoint_states:
            return "not_configured"
        if self._rpc_auth_error and all(endpoint.disabled for endpoint in self._endpoint_states):
            return "auth_error"
        if self._rate_limited_count and self._trace_failed_count and not self._trace_succeeded_count:
            return "rate_limited_for_funding_trace"
        if disabled_reason:
            return _funding_resolver_unavailable_reason(
                disabled_reason,
                auth_error=self._rpc_auth_error,
                endpoint_label=endpoint_label(self._rpc_url),
            )
        if self._trace_attempted_count == 0 and self._endpoint_states:
            return "not_assessed"
        if any(endpoint.lightweight_health_status == "lightweight_available" for endpoint in self._endpoint_states):
            return "available_lightweight_only"
        return "unknown"

    def _failed_context(self, reason: str) -> FundingContext:
        self._trace_failed_count += 1
        self._last_error = reason
        if _is_auth_error_text(reason):
            self._rpc_auth_error = True
        return unknown_funding_context(reason)


def _topic_address(address: str) -> str:
    return "0x" + address.lower().replace("0x", "").zfill(64)


def _post_json_once(url: str, payload: dict[str, object], *, timeout: int) -> object:
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
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _is_auth_http_error(exc: Exception) -> bool:
    return isinstance(exc, HTTPError) and exc.code in {401, 403}


def _is_auth_error_text(value: str) -> bool:
    text = (value or "").lower()
    return any(token in text for token in ("401", "403", "unauthorized", "forbidden", "auth"))


def _is_rate_limit_error_text(value: str) -> bool:
    text = (value or "").lower()
    return any(token in text for token in ("429", "rate limit", "rate_limited", "too many requests"))


def _funding_resolver_unavailable_reason(
    value: str,
    *,
    auth_error: bool = False,
    endpoint_label: str = "",
) -> str:
    text = (value or "").lower()
    if "funding_trace_disabled_no_rpc_mode" in text:
        return "disabled_no_rpc_mode"
    if "funding_trace_cache_only" in text or "validation_cache_only" in text:
        return "cache_only"
    if not endpoint_label or endpoint_label == "not_configured":
        return "not_configured"
    if auth_error or _is_auth_error_text(value):
        return "auth_error"
    if "429" in text or "rate" in text:
        return "rate_limited"
    if "malformed" in text or "invalid rpc response" in text or "json" in text:
        return "malformed_response"
    return "network_error"


def _funding_evidence_interpretation(mode: str) -> str:
    if mode == FUNDING_TRACE_MODE_DISABLED:
        return "Blockchain funding trace was disabled; funding evidence is unknown, not none."
    if mode == FUNDING_TRACE_MODE_CACHE_ONLY:
        return "Cache-only funding trace mode; cache misses are unknown, not none."
    return "Live RPC funding trace mode; unavailable funding remains unknown, not none."


def endpoint_label(url: str) -> str:
    parsed = urlparse(url or "")
    host = parsed.netloc or parsed.path or "not_configured"
    if "@" in host:
        host = host.split("@", 1)[-1]
    return host or "not_configured"


def unknown_funding_context(reason: str = "") -> FundingContext:
    return FundingContext(
        funding_found=False,
        funding_evidence_grade=FUNDING_EVIDENCE_UNKNOWN,
        error=reason or "funding_evidence_unknown",
    )


def _persistent_cache_key(wallet: str, as_of_bucket: str) -> str:
    return "|".join(
        (
            str(FUNDING_TRACE_CACHE_SCHEMA_VERSION),
            "polygon",
            wallet.lower(),
            as_of_bucket,
            str(SEARCH_WINDOW_BLOCKS),
            str(MAX_SEARCH_BLOCKS),
            ",".join(address.lower() for address in USDC_ADDRESSES),
            FUNDING_TRACE_SETTINGS_VERSION,
        )
    )


def _funding_context_to_cache_payload(context: FundingContext) -> dict[str, object]:
    return {
        "funding_found": context.funding_found,
        "source_address": context.source_address,
        "source_label": context.source_label,
        "source_type": context.source_type,
        "source_category": context.source_category,
        "origin_address": context.origin_address,
        "origin_label": context.origin_label,
        "origin_type": context.origin_type,
        "origin_category": context.origin_category,
        "funding_tx_hash": context.funding_tx_hash,
        "funding_timestamp": context.funding_timestamp.isoformat() if context.funding_timestamp else "",
        "funding_amount_usdc": context.funding_amount_usdc,
        "minutes_from_funding_to_trade": context.minutes_from_funding_to_trade,
        "funding_velocity_label": context.funding_velocity_label,
        "suspicious_funding_score": context.suspicious_funding_score,
        "suspicious_funding_flag": context.suspicious_funding_flag,
        "recent_external_funding_flag": context.recent_external_funding_flag,
        "funding_depth": context.funding_depth,
        "funding_graph_key": context.funding_graph_key,
        "funding_graph_key_strict": context.funding_graph_key_strict,
        "funding_graph_key_proxy": context.funding_graph_key_proxy,
        "funding_fingerprint": context.funding_fingerprint,
        "funding_evidence_grade": context.funding_evidence_grade,
        "cex_proxy_cluster_flag": context.cex_proxy_cluster_flag,
        "cex_proxy_cluster_size": context.cex_proxy_cluster_size,
        "error": context.error,
    }


def _funding_context_from_cache_payload(payload: dict[str, object]) -> FundingContext:
    timestamp_raw = str(payload.get("funding_timestamp") or "")
    timestamp: datetime | None = None
    if timestamp_raw:
        timestamp = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        else:
            timestamp = timestamp.astimezone(UTC)
    return FundingContext(
        funding_found=bool(payload.get("funding_found")),
        source_address=str(payload.get("source_address") or ""),
        source_label=str(payload.get("source_label") or "Unknown"),
        source_type=str(payload.get("source_type") or "unknown"),
        source_category=str(payload.get("source_category") or "unknown"),
        origin_address=str(payload.get("origin_address") or ""),
        origin_label=str(payload.get("origin_label") or "Unknown"),
        origin_type=str(payload.get("origin_type") or "unknown"),
        origin_category=str(payload.get("origin_category") or "unknown"),
        funding_tx_hash=str(payload.get("funding_tx_hash") or ""),
        funding_timestamp=timestamp,
        funding_amount_usdc=float(payload.get("funding_amount_usdc") or 0.0),
        minutes_from_funding_to_trade=(
            None
            if payload.get("minutes_from_funding_to_trade") in {"", None}
            else float(payload.get("minutes_from_funding_to_trade") or 0.0)
        ),
        funding_velocity_label=str(payload.get("funding_velocity_label") or "Unavailable"),
        suspicious_funding_score=float(payload.get("suspicious_funding_score") or 0.0),
        suspicious_funding_flag=bool(payload.get("suspicious_funding_flag")),
        recent_external_funding_flag=bool(payload.get("recent_external_funding_flag")),
        funding_depth=int(payload.get("funding_depth") or 0),
        funding_graph_key=str(payload.get("funding_graph_key") or ""),
        funding_graph_key_strict=str(payload.get("funding_graph_key_strict") or ""),
        funding_graph_key_proxy=str(payload.get("funding_graph_key_proxy") or ""),
        funding_fingerprint=str(payload.get("funding_fingerprint") or ""),
        funding_evidence_grade=str(payload.get("funding_evidence_grade") or FUNDING_EVIDENCE_UNKNOWN),
        cex_proxy_cluster_flag=bool(payload.get("cex_proxy_cluster_flag")),
        cex_proxy_cluster_size=int(payload.get("cex_proxy_cluster_size") or 0),
        error=str(payload.get("error") or "") or None,
    )


def _log_sort_key(log: dict[str, object]) -> tuple[int, int]:
    block = int(str(log.get("blockNumber") or "0x0"), 16)
    log_index = int(str(log.get("logIndex") or "0x0"), 16)
    return block, log_index


def _classify_address(address: str) -> tuple[str, str, str]:
    normalized = address.lower()
    entity = KNOWN_ENTITIES.get(normalized)
    if entity is not None:
        return entity
    return _short_address(normalized), "unknown", "unknown"


def _short_address(address: str) -> str:
    if len(address) < 12:
        return address
    return f"{address[:6]}...{address[-4:]}"


def _velocity_label(minutes_from_funding: float | None) -> str:
    if minutes_from_funding is None:
        return "Unavailable"
    if minutes_from_funding <= 60:
        return "within 1 hour"
    if minutes_from_funding <= 6 * 60:
        return "within 6 hours"
    if minutes_from_funding <= 24 * 60:
        return "within 24 hours"
    if minutes_from_funding <= 7 * 24 * 60:
        return "within 7 days"
    return "older funding"


def _suspiciousness_score(
    *,
    origin_category: str,
    funding_depth: int,
    funding_found: bool,
) -> float:
    if not funding_found:
        return 1.0
    if origin_category == "cex":
        return 0.1
    if origin_category == "bridge":
        return 0.3
    if origin_category in {"dex", "defi"}:
        return 0.6
    if funding_depth >= 2:
        return 0.7
    return 0.8


def grade_funding_evidence(context: FundingContext) -> str:
    if context.error or context.funding_evidence_grade == FUNDING_EVIDENCE_UNKNOWN:
        return FUNDING_EVIDENCE_UNKNOWN
    return _funding_evidence_grade(
        funding_found=context.funding_found,
        source_category=context.source_category,
        origin_category=context.origin_category,
        funding_depth=context.funding_depth,
        suspicious_funding_flag=context.suspicious_funding_flag,
        funding_graph_key_strict=context.funding_graph_key_strict,
    )


def _funding_evidence_grade(
    *,
    funding_found: bool,
    source_category: str,
    origin_category: str,
    funding_depth: int,
    suspicious_funding_flag: bool,
    funding_graph_key_strict: str,
) -> str:
    if not funding_found:
        return FUNDING_EVIDENCE_NONE
    source = (source_category or "unknown").lower()
    origin = (origin_category or "unknown").lower()
    categories = {source, origin}
    if "cex" in categories:
        return FUNDING_EVIDENCE_CEX_PROXY
    if "bridge" in categories:
        return FUNDING_EVIDENCE_BRIDGE_PROXY
    if funding_depth >= 2 and origin == "unknown":
        return FUNDING_EVIDENCE_MULTI_HOP_UNKNOWN
    if suspicious_funding_flag:
        return FUNDING_EVIDENCE_SUSPICIOUS_DIRECT
    if funding_graph_key_strict:
        return FUNDING_EVIDENCE_DIRECT_STRICT
    return FUNDING_EVIDENCE_NONE


def _funding_graph_key(origin_address: str, origin_category: str) -> str:
    return _strict_funding_graph_key(origin_address, origin_category)


def _strict_funding_graph_key(origin_address: str, origin_category: str) -> str:
    if not origin_address:
        return ""
    if origin_category in {"cex", "bridge"}:
        return ""
    return origin_address.lower()


def _proxy_funding_graph_key(
    *,
    source_label: str,
    source_address: str,
    source_category: str,
    timestamp: datetime | None,
    amount_usdc: float,
) -> str:
    if source_category not in {"cex", "bridge"}:
        return ""
    label = (source_label or _short_address(source_address.lower())).strip().lower().replace(" ", "-")
    if not label:
        return ""
    return f"{label}|{_bucketed_time_band(timestamp)}|{_bucketed_amount_band(amount_usdc)}"


def _funding_fingerprint(
    *,
    source_label: str,
    source_address: str,
    timestamp: datetime | None,
    amount_usdc: float,
    funding_depth: int,
) -> str:
    label = (source_label or _short_address(source_address.lower())).strip().lower().replace(" ", "-")
    return f"{label}|{_bucketed_amount_band(amount_usdc)}|{_bucketed_time_band(timestamp)}|depth:{funding_depth}"


def _bucketed_amount_band(amount_usdc: float) -> str:
    amount = max(float(amount_usdc), 0.0)
    if amount <= 0:
        return "0"
    step = max(100.0, amount * 0.10)
    bucket = round(amount / step) * step
    return f"{bucket:.0f}"


def _bucketed_time_band(timestamp: datetime | None) -> str:
    if timestamp is None:
        return "unknown-time"
    normalized = timestamp.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return normalized.isoformat(timespec="hours")
