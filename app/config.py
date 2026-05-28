from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

RUNTIME_ENV_FILENAME = ".inspoly_runtime.env"
FUNDING_TRACE_MODE_LIVE_RPC = "live_rpc"
FUNDING_TRACE_MODE_CACHE_ONLY = "cache_only"
FUNDING_TRACE_MODE_DISABLED = "disabled"
FUNDING_TRACE_MODES = {
    FUNDING_TRACE_MODE_LIVE_RPC,
    FUNDING_TRACE_MODE_CACHE_ONLY,
    FUNDING_TRACE_MODE_DISABLED,
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_runtime_env(
    root: Path | None = None,
    *,
    filename: str = RUNTIME_ENV_FILENAME,
) -> dict[str, str]:
    env_path = (root or repository_root()) / filename
    loaded: dict[str, str] = {}
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return loaded
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip()
        loaded[key] = os.environ[key]
    return loaded


def runtime_env_value(key: str, default: str = "") -> str:
    load_runtime_env()
    return os.environ.get(key, default)


def runtime_env_int(key: str, default: int, *, minimum: int | None = None) -> int:
    raw = runtime_env_value(key, str(default))
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


def runtime_env_float(key: str, default: float, *, minimum: float | None = None) -> float:
    raw = runtime_env_value(key, str(default))
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


def validation_cache_only_mode() -> bool:
    return bool(runtime_env_int("INSPOLY_VALIDATION_MODE", 0, minimum=0)) and not bool(
        runtime_env_int("INSPOLY_VALIDATION_ALLOW_NETWORK_FUNDING", 1, minimum=0)
    )


def normalize_funding_trace_mode(value: str | None, *, default: str = FUNDING_TRACE_MODE_DISABLED) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"", "default"}:
        normalized = default
    if normalized in {"live", "live_rpc", "rpc", "network", "network_funding"}:
        return FUNDING_TRACE_MODE_LIVE_RPC
    if normalized in {"cache", "cached", "cache_only", "cacheonly"}:
        return FUNDING_TRACE_MODE_CACHE_ONLY
    if normalized in {"disabled", "disable", "off", "none", "no_rpc", "norpc"}:
        return FUNDING_TRACE_MODE_DISABLED
    return default if default in FUNDING_TRACE_MODES else FUNDING_TRACE_MODE_DISABLED


def funding_trace_mode(default: str = FUNDING_TRACE_MODE_DISABLED) -> str:
    load_runtime_env()
    raw = os.environ.get("INSPOLY_FUNDING_TRACE_MODE")
    if raw is not None:
        return normalize_funding_trace_mode(raw, default=default)
    if runtime_env_int("INSPOLY_DISABLE_LIVE_FUNDING_TRACES", 0, minimum=0):
        return FUNDING_TRACE_MODE_DISABLED
    return normalize_funding_trace_mode(default, default=FUNDING_TRACE_MODE_DISABLED)


@dataclass(slots=True)
class AppConfig:
    data_dir: Path
    db_path: Path
    reports_dir: Path
    outputs_dir: Path
    default_lookback: str = "4h"
    max_trade_pages: int = 3
    trade_page_size: int = 100

    @classmethod
    def load(
        cls,
        *,
        app_slug: str = "inspoly",
        outputs_dir_name: str = "outputs",
        default_lookback: str = "4h",
        max_trade_pages: int = 3,
        trade_page_size: int = 100,
    ) -> "AppConfig":
        root = Path.cwd()
        data_dir = root / f".{app_slug}"
        reports_dir = data_dir / "reports"
        outputs_dir = root / outputs_dir_name
        return cls(
            data_dir=data_dir,
            db_path=data_dir / f"{app_slug}.sqlite3",
            reports_dir=reports_dir,
            outputs_dir=outputs_dir,
            default_lookback=default_lookback,
            max_trade_pages=max_trade_pages,
            trade_page_size=trade_page_size,
        )

    @classmethod
    def load_archive_researcher(cls) -> "AppConfig":
        return cls.load(
            app_slug="inspoly_archive_researcher",
            outputs_dir_name="archive_outputs",
            default_lookback="24h",
            max_trade_pages=40,
            trade_page_size=200,
        )

    @classmethod
    def load_event_forensic_analyzer(cls) -> "AppConfig":
        return cls.load(
            app_slug="inspoly_event_forensic_analyzer",
            outputs_dir_name="event_forensic_outputs",
            default_lookback="event",
            max_trade_pages=40,
            trade_page_size=100,
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
