#!/usr/bin/env python3
"""Manual bounded live indexer sidecar runner.

This tool is intentionally CLI-only and sidecar-only. It validates an
operator-reviewed config before any network path is reachable, never starts a
daemon, and writes only to the configured local SQLite sidecar DB.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.indexer import (  # noqa: E402
    IndexerStorage,
    normalize_data_trade,
    normalize_gamma_market,
    token_condition_mapping_from_gamma_market,
)
from app.polymarket import DATA_BASE, PolymarketClient, _get_json  # noqa: E402
from tools.indexer_bounded_live_config_validator import (  # noqa: E402
    GATE_VALID,
    validate_bounded_live_config_file,
)
from tools.indexer_sidecar_readiness_audit import audit_indexer_sidecar_readiness  # noqa: E402


REPORT_TYPE = "bounded_live_indexer_sidecar_run"
SCHEMA_VERSION = "bounded_live_indexer_sidecar_run_v1"

GATE_BLOCKED_MISSING_TARGET = "bounded_live_indexer_blocked_missing_operator_target"
GATE_BLOCKED_PROVIDER = "bounded_live_indexer_blocked_by_provider_or_env"
GATE_BLOCKED_NO_SAFE_PATH = "bounded_live_indexer_no_safe_next_step"
GATE_SUCCESS_HARDENING = "bounded_live_indexer_success_needs_operator_hardening"
GATE_LOW_VALUE = "bounded_live_indexer_low_value_keep_fixture_only"

SOURCE_NAME = "bounded_live_sidecar"
NARROW_LIMITS = {
    "maxMarkets": 3,
    "maxPages": 2,
    "maxRows": 500,
    "timeoutSeconds": 120,
}

TradeFetcher = Callable[[Mapping[str, object]], object]


def run_bounded_live_sidecar(
    config_json: str | Path,
    *,
    summary_json: str | Path | None = None,
    db_audit_json: str | Path | None = None,
    allow_live_network: bool = False,
    client: object | None = None,
    trade_fetcher: TradeFetcher | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Execute one bounded sidecar run or return a blocked preflight report."""

    started = time.monotonic()
    generated_at = now or datetime.now(tz=UTC)
    config_path = Path(config_json)
    config = _read_json_object(config_path)
    validation = validate_bounded_live_config_file(config_path)
    report = _base_report(
        config_path=config_path,
        config=config,
        validation=validation,
        generated_at=generated_at,
    )

    if validation.get("summary", {}).get("gateDecision") != GATE_VALID:
        gate = _blocked_gate_from_validation(validation)
        _finish_report(report, gate=gate, started=started)
        return _write_report(report, summary_json)

    target = _single_exact_target(config)
    if target is None:
        report["failures"].append("Config must contain exactly one marketSlugs or eventSlugs value.")
        _finish_report(report, gate=GATE_BLOCKED_MISSING_TARGET, started=started)
        return _write_report(report, summary_json)

    limit_error = _narrow_limit_error(config)
    if limit_error:
        report["failures"].append(limit_error)
        _finish_report(report, gate=GATE_BLOCKED_NO_SAFE_PATH, started=started)
        return _write_report(report, summary_json)

    if not allow_live_network:
        report["failures"].append("Live network execution requires the explicit --allow-live-network command flag.")
        _finish_report(report, gate=GATE_BLOCKED_NO_SAFE_PATH, started=started)
        return _write_report(report, summary_json)

    db_path = _sqlite_path(config)
    storage = IndexerStorage(db_path)
    market_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    malformed = {
        "marketsNonMapping": 0,
        "tradesNonMapping": 0,
        "orderbooksNonMapping": 0,
    }
    limits = _limits(config)
    target_key, slug = target
    report["networkUsed"] = True
    report["liveIngestionStarted"] = True
    report["target"] = {"type": target_key, "slug": slug}

    try:
        market_rows, market_warnings, market_failures, malformed_markets = _fetch_market_rows(
            target_key=target_key,
            slug=slug,
            max_markets=limits["maxMarkets"],
            client=client or PolymarketClient(),
        )
        malformed["marketsNonMapping"] = malformed_markets
        report["warnings"].extend(market_warnings)
        report["failures"].extend(market_failures)
        if market_failures and not market_rows:
            report["summary"]["malformedPayloadCounts"] = malformed
            _finish_report(report, gate=GATE_BLOCKED_PROVIDER, started=started)
            return _write_report(report, summary_json)

        storage.init()
        condition_ids: list[str] = []
        token_ids: dict[str, str] = {}
        timestamp = generated_at.replace(microsecond=0).isoformat()
        for row in market_rows[: limits["maxMarkets"]]:
            market = normalize_gamma_market(row, updated_at=timestamp)
            storage.upsert_market(market)
            if market.condition_id != "unknown":
                condition_ids.append(market.condition_id)
            token_mapping = token_condition_mapping_from_gamma_market(row)
            for token_id, mapping in token_mapping.items():
                condition_id = str(getattr(mapping, "condition_id", "") or "")
                if condition_id:
                    token_ids[str(token_id)] = condition_id

        storage.upsert_cursor(
            source=SOURCE_NAME,
            cursor_key="markets",
            cursor_value=f"{target_key}:{slug}:{len(market_rows)}",
            status="ok" if market_rows else "warn",
            last_error="" if market_rows else "no_market_rows",
            updated_at=timestamp,
        )

        trade_rows, trade_warnings, malformed_trades = _fetch_public_trade_rows(
            condition_ids=condition_ids,
            max_pages=limits["maxPages"],
            max_rows=limits["maxRows"] - len(market_rows),
            trade_fetcher=trade_fetcher or _default_trade_fetcher,
        )
        malformed["tradesNonMapping"] = malformed_trades
        report["warnings"].extend(trade_warnings)

        stored_trades = 0
        remaining_rows = max(0, limits["maxRows"] - len(market_rows))
        for row in trade_rows[:remaining_rows]:
            storage.upsert_trade(normalize_data_trade(row, source=SOURCE_NAME))
            stored_trades += 1

        storage.upsert_cursor(
            source=SOURCE_NAME,
            cursor_key="public_trades",
            cursor_value=f"conditions:{len(condition_ids)}:rows:{stored_trades}",
            status="ok",
            updated_at=timestamp,
        )
        if token_ids:
            report["warnings"].append(
                "Orderbook snapshots were skipped: no approved public orderbook endpoint contract is wired into this manual runner."
            )

        table_counts = storage.table_counts()
        audit = audit_indexer_sidecar_readiness(db_path, now=generated_at)
        if db_audit_json:
            _write_json(audit, db_audit_json)

        report["output"]["dbCreated"] = db_path.exists()
        report["output"]["dbAuditJson"] = str(db_audit_json or "")
        report["summary"]["marketsAttempted"] = 1
        report["summary"]["marketsCompleted"] = int(table_counts.get("indexed_markets", 0))
        report["summary"]["storedRows"] = sum(int(value) for value in table_counts.values())
        report["summary"]["tableCounts"] = table_counts
        report["summary"]["cursorStates"] = _cursor_states(storage)
        report["summary"]["malformedPayloadCounts"] = malformed
        report["summary"]["readinessGate"] = audit.get("summary", {}).get("readinessGate", "")
        gate = GATE_SUCCESS_HARDENING if table_counts.get("indexed_markets", 0) or stored_trades else GATE_LOW_VALUE
    except Exception as exc:
        report["failures"].append(f"{type(exc).__name__}: {exc}")
        try:
            storage.upsert_cursor(
                source=SOURCE_NAME,
                cursor_key="run",
                cursor_value=f"{target_key}:{slug}",
                status="error",
                last_error=str(exc),
            )
        except Exception:
            pass
        gate = GATE_BLOCKED_PROVIDER

    _finish_report(report, gate=gate, started=started)
    return _write_report(report, summary_json)


def _read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Config JSON root must be an object.")
    return payload


def _base_report(
    *,
    config_path: Path,
    config: Mapping[str, object],
    validation: Mapping[str, object],
    generated_at: datetime,
) -> dict[str, object]:
    db_path = _sqlite_path(config)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at.isoformat(),
        "configPath": str(config_path),
        "sidecarOnly": True,
        "readOnlyExternalServices": True,
        "networkUsed": False,
        "liveIngestionStarted": False,
        "productionIntegration": False,
        "backgroundWorker": False,
        "daemonMode": False,
        "externalWrites": False,
        "authUsed": False,
        "tradingUsed": False,
        "savedArtifactsMutated": False,
        "target": {"type": "", "slug": ""},
        "bounds": _limits(config),
        "output": {
            "sqlitePath": str(db_path),
            "dbCreated": False,
            "summaryJson": "",
            "dbAuditJson": "",
        },
        "summary": {
            "gateDecision": "",
            "elapsedSeconds": 0.0,
            "marketsAttempted": 0,
            "marketsCompleted": 0,
            "storedRows": 0,
            "tableCounts": {},
            "cursorStates": [],
            "malformedPayloadCounts": {
                "marketsNonMapping": 0,
                "tradesNonMapping": 0,
                "orderbooksNonMapping": 0,
            },
            "validationGate": validation.get("summary", {}).get("gateDecision", ""),
        },
        "warnings": [],
        "failures": [],
        "validation": validation,
    }


def _finish_report(report: dict[str, object], *, gate: str, started: float) -> None:
    summary = report["summary"]
    if isinstance(summary, dict):
        summary["gateDecision"] = gate
        summary["elapsedSeconds"] = round(time.monotonic() - started, 3)


def _write_report(report: dict[str, object], summary_json: str | Path | None) -> dict[str, object]:
    if summary_json:
        report["output"]["summaryJson"] = str(summary_json)  # type: ignore[index]
        _write_json(report, summary_json)
    return report


def _write_json(payload: Mapping[str, object], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _blocked_gate_from_validation(validation: Mapping[str, object]) -> str:
    checks = validation.get("checks")
    if isinstance(checks, Sequence):
        for check in checks:
            if isinstance(check, Mapping) and check.get("status") == "error" and check.get("name") == "targets":
                return GATE_BLOCKED_MISSING_TARGET
    return GATE_BLOCKED_NO_SAFE_PATH


def _single_exact_target(config: Mapping[str, object]) -> tuple[str, str] | None:
    targets = config.get("targets")
    if not isinstance(targets, Mapping):
        return None
    pairs: list[tuple[str, str]] = []
    for key in ("marketSlugs", "eventSlugs"):
        value = targets.get(key)
        if isinstance(value, list):
            pairs.extend((key, str(item).strip()) for item in value if str(item or "").strip())
    if len(pairs) != 1:
        return None
    key, slug = pairs[0]
    if slug.lower() in {"*", "all", "any"}:
        return None
    return key, slug


def _narrow_limit_error(config: Mapping[str, object]) -> str:
    limits = _limits(config)
    for key, cap in NARROW_LIMITS.items():
        if limits[key] > cap:
            return f"{key}={limits[key]} exceeds campaign cap {cap}."
    return ""


def _limits(config: Mapping[str, object]) -> dict[str, int]:
    limits = config.get("limits")
    if not isinstance(limits, Mapping):
        return dict(NARROW_LIMITS)
    return {
        "maxMarkets": _int(limits.get("maxMarkets"), NARROW_LIMITS["maxMarkets"]),
        "maxPages": _int(limits.get("maxPages"), NARROW_LIMITS["maxPages"]),
        "maxRows": _int(limits.get("maxRows"), NARROW_LIMITS["maxRows"]),
        "timeoutSeconds": _int(limits.get("timeoutSeconds"), NARROW_LIMITS["timeoutSeconds"]),
    }


def _sqlite_path(config: Mapping[str, object]) -> Path:
    output = config.get("output")
    value = ""
    if isinstance(output, Mapping):
        value = str(output.get("sqlitePath") or output.get("dbPath") or "").strip()
    if not value:
        value = str(config.get("sqlitePath") or config.get("dbPath") or "").strip()
    return Path(value) if value else Path(".inspoly_indexer/bounded_live_20260527/indexer.sqlite3")


def _fetch_market_rows(
    *,
    target_key: str,
    slug: str,
    max_markets: int,
    client: object,
) -> tuple[list[dict[str, object]], list[str], list[str], int]:
    warnings: list[str] = []
    failures: list[str] = []
    malformed = 0
    rows: list[dict[str, object]] = []

    if target_key == "marketSlugs":
        payload = client.fetch_market_by_slug(slug)  # type: ignore[attr-defined]
        if isinstance(payload, Mapping):
            rows.append(dict(payload))
        elif payload is None:
            failures.append(f"Market slug not found or provider failed: {slug}")
        else:
            malformed += 1
        return rows, warnings, failures, malformed

    payload = client.fetch_event_by_slug(slug)  # type: ignore[attr-defined]
    if not isinstance(payload, Mapping):
        failures.append(f"Event slug not found or provider failed: {slug}")
        return rows, warnings, failures, malformed
    markets = payload.get("markets")
    if not isinstance(markets, Sequence) or isinstance(markets, (str, bytes)):
        warnings.append("Event payload did not include a markets list.")
        return rows, warnings, failures, malformed
    for item in markets[:max_markets]:
        if isinstance(item, Mapping):
            market = dict(item)
            market.setdefault("eventSlug", slug)
            rows.append(market)
        else:
            malformed += 1
    if len(markets) > max_markets:
        warnings.append(f"Event market expansion capped at {max_markets} markets.")
    return rows, warnings, failures, malformed


def _fetch_public_trade_rows(
    *,
    condition_ids: Sequence[str],
    max_pages: int,
    max_rows: int,
    trade_fetcher: TradeFetcher,
) -> tuple[list[dict[str, object]], list[str], int]:
    if max_rows <= 0:
        return [], ["Public trade fetch skipped because the row cap was reached by market rows."], 0
    if not condition_ids:
        return [], ["Public trade fetch skipped because no condition IDs were resolved."], 0
    market_filter = ",".join(condition_ids)
    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    malformed = 0
    page_size = min(100, max_rows)
    for page in range(max_pages):
        if len(rows) >= max_rows:
            break
        limit = min(page_size, max_rows - len(rows))
        payload = trade_fetcher({"limit": limit, "offset": page * page_size, "market": market_filter})
        if not isinstance(payload, list):
            warnings.append("Public trades payload was not a list; stopping pagination.")
            break
        if not payload:
            break
        for item in payload:
            if len(rows) >= max_rows:
                break
            if isinstance(item, Mapping):
                rows.append(dict(item))
            else:
                malformed += 1
        if len(payload) < limit:
            break
    if len(rows) >= max_rows:
        warnings.append(f"Public trade rows capped at {max_rows}.")
    return rows, warnings, malformed


def _default_trade_fetcher(params: Mapping[str, object]) -> object:
    return _get_json(f"{DATA_BASE}/trades", dict(params), timeout=12)


def _cursor_states(storage: IndexerStorage) -> list[dict[str, str]]:
    states: list[dict[str, str]] = []
    for cursor in storage.list_cursors():
        states.append(
            {
                "source": cursor.source,
                "cursorKey": cursor.cursor_key,
                "cursorValue": cursor.cursor_value,
                "status": cursor.status,
                "lastError": cursor.last_error,
            }
        )
    return states


def _int(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one bounded live indexer sidecar pass from an approved config.")
    parser.add_argument("--config-json", required=True, help="Operator-reviewed bounded live config JSON.")
    parser.add_argument("--summary-json", help="Optional compact run summary JSON.")
    parser.add_argument("--db-audit-json", help="Optional readiness audit JSON for the produced DB.")
    parser.add_argument(
        "--allow-live-network",
        action="store_true",
        help="Required to perform live public GET requests after config validation passes.",
    )
    args = parser.parse_args(argv)

    report = run_bounded_live_sidecar(
        args.config_json,
        summary_json=args.summary_json,
        db_audit_json=args.db_audit_json,
        allow_live_network=args.allow_live_network,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
