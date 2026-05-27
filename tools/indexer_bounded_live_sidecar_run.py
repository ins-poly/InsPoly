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

    targets, target_error = _bounded_targets(config)
    if target_error:
        report["failures"].append(target_error)
        _finish_report(report, gate=GATE_BLOCKED_MISSING_TARGET, started=started)
        return _write_report(report, summary_json)

    limit_error = _narrow_limit_error(config)
    if limit_error:
        report["failures"].append(limit_error)
        _finish_report(report, gate=GATE_BLOCKED_NO_SAFE_PATH, started=started)
        return _write_report(report, summary_json)

    limits = _limits(config)
    if len(targets) > limits["maxMarkets"]:
        report["failures"].append(f"Target count {len(targets)} exceeds configured maxMarkets {limits['maxMarkets']}.")
        _finish_report(report, gate=GATE_BLOCKED_NO_SAFE_PATH, started=started)
        return _write_report(report, summary_json)

    if not allow_live_network:
        report["failures"].append("Live network execution requires the explicit --allow-live-network command flag.")
        _finish_report(report, gate=GATE_BLOCKED_NO_SAFE_PATH, started=started)
        return _write_report(report, summary_json)

    db_path = _sqlite_path(config)
    storage = IndexerStorage(db_path)
    trade_rows: list[dict[str, object]] = []
    malformed = {
        "marketsNonMapping": 0,
        "tradesNonMapping": 0,
        "orderbooksNonMapping": 0,
    }
    report["networkUsed"] = True
    report["liveIngestionStarted"] = True
    report["target"] = {"type": targets[0][0], "slug": ",".join(slug for _, slug in targets), "count": len(targets)}
    target_results: list[dict[str, object]] = [
        {
            "targetType": target_key,
            "slug": slug,
            "status": "pending",
            "marketRows": 0,
            "conditionIds": [],
            "tradeRows": 0,
            "warnings": [],
            "failures": [],
        }
        for target_key, slug in targets
    ]
    report["targetResults"] = target_results

    try:
        market_entries: list[tuple[dict[str, object], int]] = []
        client_instance = client or PolymarketClient()
        for target_index, (target_key, slug) in enumerate(targets):
            if len(market_entries) >= limits["maxMarkets"]:
                warning = "Skipped because configured maxMarkets was already reached."
                target_results[target_index]["status"] = "skipped"
                target_results[target_index]["warnings"].append(warning)
                report["warnings"].append(f"{slug}: {warning}")
                continue
            remaining_markets = limits["maxMarkets"] - len(market_entries)
            market_rows, market_warnings, market_failures, malformed_markets = _fetch_market_rows(
                target_key=target_key,
                slug=slug,
                max_markets=remaining_markets,
                client=client_instance,
            )
            malformed["marketsNonMapping"] += malformed_markets
            target_results[target_index]["warnings"].extend(market_warnings)
            target_results[target_index]["failures"].extend(market_failures)
            report["warnings"].extend(f"{slug}: {warning}" for warning in market_warnings)
            report["failures"].extend(f"{slug}: {failure}" for failure in market_failures)
            if market_rows:
                target_results[target_index]["status"] = "completed"
                target_results[target_index]["marketRows"] = len(market_rows)
                market_entries.extend((row, target_index) for row in market_rows)
            else:
                target_results[target_index]["status"] = "failed"
        if report["failures"] and not market_entries:
            report["summary"]["malformedPayloadCounts"] = malformed
            _finish_report(report, gate=GATE_BLOCKED_PROVIDER, started=started)
            return _write_report(report, summary_json)
        if not market_entries:
            report["summary"]["malformedPayloadCounts"] = malformed
            _finish_report(report, gate=GATE_LOW_VALUE, started=started)
            return _write_report(report, summary_json)

        storage.init()
        condition_ids: list[str] = []
        condition_to_target: dict[str, int] = {}
        token_ids: dict[str, str] = {}
        timestamp = generated_at.replace(microsecond=0).isoformat()
        for row, target_index in market_entries[: limits["maxMarkets"]]:
            market = normalize_gamma_market(row, updated_at=timestamp)
            storage.upsert_market(market)
            if market.condition_id != "unknown":
                condition_ids.append(market.condition_id)
                condition_to_target[market.condition_id] = target_index
                target_results[target_index]["conditionIds"].append(market.condition_id)
            token_mapping = token_condition_mapping_from_gamma_market(row)
            for token_id, mapping in token_mapping.items():
                condition_id = str(getattr(mapping, "condition_id", "") or "")
                if condition_id:
                    token_ids[str(token_id)] = condition_id

        storage.upsert_cursor(
            source=SOURCE_NAME,
            cursor_key="markets",
            cursor_value=_market_cursor_value(targets, len(market_entries)),
            status="ok" if market_entries else "warn",
            last_error="" if market_entries else "no_market_rows",
            updated_at=timestamp,
        )

        per_target_trade_limit = int(limits.get("maxPublicTradesPerTarget", 0))
        aggregate_trade_budget = limits["maxRows"] - len(market_entries)
        fetch_details: list[dict[str, object]] = []
        collection_policy = "aggregate_condition_filter"
        if len(condition_ids) > 1 and per_target_trade_limit > 0:
            collection_policy = "per_target_public_trade_cap"
            trade_rows, trade_warnings, malformed_trades, fetch_details = _fetch_public_trade_rows_per_target(
                condition_ids=condition_ids,
                condition_to_target=condition_to_target,
                target_results=target_results,
                max_pages=limits["maxPages"],
                max_rows=aggregate_trade_budget,
                per_target_limit=per_target_trade_limit,
                trade_fetcher=trade_fetcher or _default_trade_fetcher,
            )
        else:
            trade_rows, trade_warnings, malformed_trades = _fetch_public_trade_rows(
                condition_ids=condition_ids,
                max_pages=limits["maxPages"],
                max_rows=aggregate_trade_budget,
                trade_fetcher=trade_fetcher or _default_trade_fetcher,
            )
        malformed["tradesNonMapping"] = malformed_trades
        report["warnings"].extend(trade_warnings)

        stored_trades = 0
        remaining_rows = max(0, limits["maxRows"] - len(market_entries))
        trade_counts_by_condition: dict[str, int] = {}
        for row in trade_rows[:remaining_rows]:
            trade = normalize_data_trade(row, source=SOURCE_NAME)
            storage.upsert_trade(trade)
            stored_trades += 1
            trade_counts_by_condition[trade.condition_id] = trade_counts_by_condition.get(trade.condition_id, 0) + 1
        for condition_id, target_index in condition_to_target.items():
            target_results[target_index]["tradeRows"] = int(target_results[target_index]["tradeRows"]) + trade_counts_by_condition.get(condition_id, 0)
        public_trade_collection = _public_trade_collection_summary(
            condition_ids=condition_ids,
            condition_to_target=condition_to_target,
            target_results=target_results,
            limits=limits,
            market_row_count=len(market_entries),
            stored_trades=stored_trades,
            trade_counts_by_condition=trade_counts_by_condition,
            collection_policy=collection_policy,
            per_target_trade_limit=per_target_trade_limit,
            fetch_details=fetch_details,
        )
        if public_trade_collection["mayUnderrepresentTargets"]:
            report["warnings"].append(
                "Public trades were collected with one aggregate condition filter and a global page/row cap; "
                "some targets may be underrepresented."
            )

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
        report["summary"]["marketsAttempted"] = len(targets)
        report["summary"]["marketsCompleted"] = int(table_counts.get("indexed_markets", 0))
        report["summary"]["targetsAttempted"] = len(targets)
        report["summary"]["targetsCompleted"] = sum(1 for result in target_results if result.get("status") == "completed")
        report["summary"]["targetsFailed"] = sum(1 for result in target_results if result.get("status") == "failed")
        report["summary"]["targetsSkipped"] = sum(1 for result in target_results if result.get("status") == "skipped")
        report["summary"]["storedRows"] = sum(int(value) for value in table_counts.values())
        report["summary"]["tableCounts"] = table_counts
        report["summary"]["cursorStates"] = _cursor_states(storage)
        report["summary"]["malformedPayloadCounts"] = malformed
        report["summary"]["publicTradeCollection"] = public_trade_collection
        report["summary"]["readinessGate"] = audit.get("summary", {}).get("readinessGate", "")
        report["summary"]["targetResults"] = target_results
        gate = GATE_SUCCESS_HARDENING if table_counts.get("indexed_markets", 0) or stored_trades else GATE_LOW_VALUE
    except Exception as exc:
        report["failures"].append(f"{type(exc).__name__}: {exc}")
        try:
            storage.upsert_cursor(
                source=SOURCE_NAME,
                cursor_key="run",
                cursor_value=",".join(slug for _, slug in targets),
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
        "target": {"type": "", "slug": "", "count": 0},
        "targetResults": [],
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
            "targetsAttempted": 0,
            "targetsCompleted": 0,
            "targetsFailed": 0,
            "targetsSkipped": 0,
            "storedRows": 0,
            "tableCounts": {},
            "cursorStates": [],
            "targetResults": [],
            "malformedPayloadCounts": {
                "marketsNonMapping": 0,
                "tradesNonMapping": 0,
                "orderbooksNonMapping": 0,
            },
            "publicTradeCollection": {},
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


def _bounded_targets(config: Mapping[str, object]) -> tuple[list[tuple[str, str]], str]:
    targets = config.get("targets")
    if not isinstance(targets, Mapping):
        return [], "Config must contain one to three explicit marketSlugs or one explicit eventSlugs value."
    unsupported = [
        key
        for key in ("conditionIds", "tokenIds")
        if isinstance(targets.get(key), list) and any(str(item or "").strip() for item in targets.get(key, []))
    ]
    if unsupported:
        return [], f"Runner supports only explicit marketSlugs or eventSlugs, not {', '.join(unsupported)}."
    market_slugs = _target_values(targets.get("marketSlugs"))
    event_slugs = _target_values(targets.get("eventSlugs"))
    if market_slugs and event_slugs:
        return [], "Runner does not support mixed marketSlugs and eventSlugs in one invocation."
    values = market_slugs or event_slugs
    if not values:
        return [], "Config must contain one to three explicit marketSlugs or one explicit eventSlugs value."
    if any(value.lower() in {"*", "all", "any"} for value in values):
        return [], "Runner rejects wildcard target values before network access."
    if market_slugs:
        if len(market_slugs) > NARROW_LIMITS["maxMarkets"]:
            return [], "Runner supports at most three explicit marketSlugs in one bounded invocation."
        return [("marketSlugs", slug) for slug in market_slugs], ""
    if len(event_slugs) != 1:
        return [], "Runner preserves one explicit eventSlugs target per invocation."
    return [("eventSlugs", event_slugs[0])], ""


def _target_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _market_cursor_value(targets: Sequence[tuple[str, str]], stored_markets: int) -> str:
    if len(targets) == 1:
        target_key, slug = targets[0]
        return f"{target_key}:{slug}:{stored_markets}"
    joined_slugs = ",".join(slug for _, slug in targets)
    return f"marketSlugs:{joined_slugs}:{stored_markets}"


def _narrow_limit_error(config: Mapping[str, object]) -> str:
    limits = _limits(config)
    for key, cap in NARROW_LIMITS.items():
        if limits[key] > cap:
            return f"{key}={limits[key]} exceeds campaign cap {cap}."
    per_target_trade_limit = limits.get("maxPublicTradesPerTarget", 0)
    if per_target_trade_limit < 0:
        return "maxPublicTradesPerTarget must not be negative."
    if per_target_trade_limit > NARROW_LIMITS["maxRows"]:
        return f"maxPublicTradesPerTarget={per_target_trade_limit} exceeds campaign maxRows cap {NARROW_LIMITS['maxRows']}."
    return ""


def _limits(config: Mapping[str, object]) -> dict[str, int]:
    limits = config.get("limits")
    if not isinstance(limits, Mapping):
        payload = dict(NARROW_LIMITS)
        payload["maxPublicTradesPerTarget"] = 0
        return payload
    return {
        "maxMarkets": _int(limits.get("maxMarkets"), NARROW_LIMITS["maxMarkets"]),
        "maxPages": _int(limits.get("maxPages"), NARROW_LIMITS["maxPages"]),
        "maxRows": _int(limits.get("maxRows"), NARROW_LIMITS["maxRows"]),
        "timeoutSeconds": _int(limits.get("timeoutSeconds"), NARROW_LIMITS["timeoutSeconds"]),
        "maxPublicTradesPerTarget": _int(limits.get("maxPublicTradesPerTarget"), 0),
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


def _fetch_public_trade_rows_per_target(
    *,
    condition_ids: Sequence[str],
    condition_to_target: Mapping[str, int],
    target_results: Sequence[Mapping[str, object]],
    max_pages: int,
    max_rows: int,
    per_target_limit: int,
    trade_fetcher: TradeFetcher,
) -> tuple[list[dict[str, object]], list[str], int, list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    malformed = 0
    fetch_details: list[dict[str, object]] = []
    remaining = max(0, max_rows)
    for condition_id in condition_ids:
        target_index = condition_to_target.get(condition_id)
        target_slug = _target_slug(target_results, target_index)
        if remaining <= 0:
            warnings.append(f"Aggregate public-trade cap exhausted before fetching target {target_slug or condition_id}.")
            fetch_details.append(
                {
                    "conditionId": condition_id,
                    "targetSlug": target_slug,
                    "requestedLimit": 0,
                    "fetchedRows": 0,
                    "acceptedRows": 0,
                    "filterMismatchRows": 0,
                    "missingConditionRows": 0,
                    "aggregateRowsRemainingAfter": 0,
                    "skippedReason": "aggregate_cap_exhausted",
                }
            )
            continue
        target_limit = min(per_target_limit, remaining)
        fetched_rows, target_warnings, target_malformed = _fetch_public_trade_rows(
            condition_ids=[condition_id],
            max_pages=max_pages,
            max_rows=target_limit,
            trade_fetcher=trade_fetcher,
        )
        malformed += target_malformed
        warnings.extend(f"{target_slug or condition_id}: {warning}" for warning in target_warnings)
        accepted_rows: list[dict[str, object]] = []
        filter_mismatches = 0
        missing_condition = 0
        for row in fetched_rows:
            row_condition = _payload_condition_id(row)
            if not row_condition:
                missing_condition += 1
                continue
            if row_condition != condition_id:
                filter_mismatches += 1
                continue
            accepted_rows.append(row)
        if missing_condition:
            warnings.append(f"{target_slug or condition_id}: {missing_condition} public trade rows lacked condition identity and were not stored.")
        if filter_mismatches:
            warnings.append(
                f"{target_slug or condition_id}: {filter_mismatches} public trade rows did not match the requested condition and were not stored."
            )
        rows.extend(accepted_rows)
        remaining -= len(accepted_rows)
        fetch_details.append(
            {
                "conditionId": condition_id,
                "targetSlug": target_slug,
                "requestedLimit": target_limit,
                "fetchedRows": len(fetched_rows),
                "acceptedRows": len(accepted_rows),
                "filterMismatchRows": filter_mismatches,
                "missingConditionRows": missing_condition,
                "aggregateRowsRemainingAfter": remaining,
                "skippedReason": "",
            }
        )
    return rows, warnings, malformed, fetch_details


def _public_trade_collection_summary(
    *,
    condition_ids: Sequence[str],
    condition_to_target: Mapping[str, int],
    target_results: Sequence[Mapping[str, object]],
    limits: Mapping[str, int],
    market_row_count: int,
    stored_trades: int,
    trade_counts_by_condition: Mapping[str, int],
    collection_policy: str = "aggregate_condition_filter",
    per_target_trade_limit: int = 0,
    fetch_details: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    max_rows_after_markets = max(0, int(limits["maxRows"]) - market_row_count)
    aggregate_mode = collection_policy == "aggregate_condition_filter"
    if aggregate_mode:
        page_size = min(100, max_rows_after_markets) if max_rows_after_markets else 0
        effective_fetch_cap = min(max_rows_after_markets, page_size * int(limits["maxPages"])) if page_size else 0
        condition_filter_mode = "comma_separated_condition_ids"
    else:
        page_size = min(100, per_target_trade_limit) if per_target_trade_limit else 0
        effective_fetch_cap = min(max_rows_after_markets, per_target_trade_limit * len(condition_ids))
        condition_filter_mode = "single_condition_per_request"
    per_condition: list[dict[str, object]] = []
    rows_by_target: dict[str, int] = {}
    targets_without_trades: list[str] = []
    uncovered_conditions: list[str] = []
    for condition_id in condition_ids:
        target_index = condition_to_target.get(condition_id)
        target_slug = ""
        if target_index is not None and 0 <= target_index < len(target_results):
            target_slug = str(target_results[target_index].get("slug") or "")
        rows = int(trade_counts_by_condition.get(condition_id, 0))
        if rows == 0:
            uncovered_conditions.append(condition_id)
            if target_slug:
                targets_without_trades.append(target_slug)
        if target_slug:
            rows_by_target[target_slug] = rows
        per_condition.append(
            {
                "conditionId": condition_id,
                "targetSlug": target_slug,
                "storedTradeRows": rows,
            }
        )
    cap_reached = bool(effective_fetch_cap and stored_trades >= effective_fetch_cap)
    may_underrepresent = bool(aggregate_mode and len(condition_ids) > 1 and (uncovered_conditions or cap_reached))
    target_starvation_warnings = _target_starvation_warnings(
        collection_policy=collection_policy,
        targets_without_trades=targets_without_trades,
        fetch_details=fetch_details,
        cap_reached=cap_reached,
    )
    cap_exhaustion_warnings = _cap_exhaustion_warnings(
        collection_policy=collection_policy,
        fetch_details=fetch_details,
        cap_reached=cap_reached,
        per_target_trade_limit=per_target_trade_limit,
        stored_trades=stored_trades,
        effective_fetch_cap=effective_fetch_cap,
    )
    return {
        "mode": collection_policy,
        "collectionPolicy": collection_policy,
        "marketFilter": condition_filter_mode,
        "conditionFilterMode": condition_filter_mode,
        "cursorIdentity": "aggregate_public_trades",
        "perTargetCursorRows": False,
        "perTargetTradeCapConfigured": per_target_trade_limit > 0,
        "perTargetPublicTradeLimit": per_target_trade_limit or None,
        "aggregatePublicTradeLimit": max_rows_after_markets,
        "conditionCount": len(condition_ids),
        "maxRowsAfterMarketRows": max_rows_after_markets,
        "maxPages": int(limits["maxPages"]),
        "pageSize": page_size,
        "effectiveFetchCap": effective_fetch_cap,
        "storedTradeRows": stored_trades,
        "rowsByTarget": rows_by_target,
        "capReached": cap_reached,
        "capExhaustionWarnings": cap_exhaustion_warnings,
        "perConditionStoredRows": per_condition,
        "perTargetFetches": [dict(item) for item in fetch_details],
        "uncoveredConditionIds": uncovered_conditions,
        "targetsWithoutTrades": targets_without_trades,
        "targetStarvationWarnings": target_starvation_warnings,
        "mayUnderrepresentTargets": may_underrepresent,
        "recommendedHardening": (
            "add_per_target_or_per_condition_trade_collection_before_warehouse_rfc"
            if may_underrepresent
            else "current_collection_sufficient_for_bounded_probe"
        ),
    }


def _target_starvation_warnings(
    *,
    collection_policy: str,
    targets_without_trades: Sequence[str],
    fetch_details: Sequence[Mapping[str, object]],
    cap_reached: bool,
) -> list[str]:
    if collection_policy == "aggregate_condition_filter" and targets_without_trades and cap_reached:
        return [f"aggregate_cap_may_have_starved:{slug}" for slug in targets_without_trades]
    warnings: list[str] = []
    for item in fetch_details:
        if str(item.get("skippedReason") or "") == "aggregate_cap_exhausted":
            target_slug = str(item.get("targetSlug") or item.get("conditionId") or "")
            if target_slug:
                warnings.append(f"aggregate_cap_exhausted_before_target:{target_slug}")
    return warnings


def _cap_exhaustion_warnings(
    *,
    collection_policy: str,
    fetch_details: Sequence[Mapping[str, object]],
    cap_reached: bool,
    per_target_trade_limit: int,
    stored_trades: int,
    effective_fetch_cap: int,
) -> list[str]:
    warnings: list[str] = []
    if cap_reached:
        warnings.append(f"{collection_policy}:effective_fetch_cap_reached:{effective_fetch_cap}")
    if collection_policy == "per_target_public_trade_cap":
        for item in fetch_details:
            accepted = int(item.get("acceptedRows") or 0)
            requested = int(item.get("requestedLimit") or 0)
            target_slug = str(item.get("targetSlug") or item.get("conditionId") or "")
            if per_target_trade_limit and requested == per_target_trade_limit and accepted >= per_target_trade_limit:
                warnings.append(f"per_target_cap_reached:{target_slug}:{per_target_trade_limit}")
        if effective_fetch_cap and stored_trades >= effective_fetch_cap:
            warnings.append("aggregate_safety_budget_exhausted")
    return warnings


def _target_slug(target_results: Sequence[Mapping[str, object]], target_index: int | None) -> str:
    if target_index is None or target_index < 0 or target_index >= len(target_results):
        return ""
    return str(target_results[target_index].get("slug") or "")


def _payload_condition_id(row: Mapping[str, object]) -> str:
    for key in ("conditionId", "condition_id", "market"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


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
