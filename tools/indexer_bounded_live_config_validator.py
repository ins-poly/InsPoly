#!/usr/bin/env python3
"""Validate a proposed bounded live-indexer config without network calls."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


REPORT_TYPE = "indexer_bounded_live_config_validation"
SCHEMA_VERSION = "indexer_bounded_live_config_validation_v1"

GATE_VALID = "indexer_bounded_live_config_valid_for_operator_review"
GATE_BLOCKED = "indexer_bounded_live_config_blocked"

HARD_LIMITS = {
    "maxMarkets": 50,
    "maxPages": 25,
    "maxRows": 50000,
    "timeoutSeconds": 1800,
}
OPTIONAL_LIMITS = {
    "maxPublicTradesPerTarget": 50000,
}

TARGET_KEYS = ("marketSlugs", "conditionIds", "eventSlugs", "tokenIds")
ALLOWED_DATA_TYPES = {
    "markets",
    "public_trades",
    "orderbook_snapshots",
    "cursors",
    "health_rows",
}
DISALLOWED_DATA_TYPES = {
    "private_user_socket_data",
    "auth",
    "orders",
    "private_keys",
    "trading",
}
FORBIDDEN_KEY_PARTS = (
    "api_key",
    "apikey",
    "api_secret",
    "apisecret",
    "auth",
    "clob_secret",
    "credential",
    "mnemonic",
    "order_placement",
    "passphrase",
    "place_order",
    "private_key",
    "secret",
    "signature",
    "trading",
    "user_socket",
)
FORBIDDEN_PATH_PARTS = {
    "app",
    "docs",
    "release_manifests",
    "shadow_review_packets",
    "side_outcome_review_packets",
    "tests",
}
ALLOWED_SIDECAR_PATH_PARTS = {".inspoly_indexer", "indexer_sidecar_outputs"}
SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def validate_bounded_live_config(
    config: Mapping[str, object],
    *,
    config_path: str | Path | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """Return a validation report for an operator-proposed sidecar config."""

    checks: list[dict[str, object]] = []
    normalized: dict[str, object] = {}

    if not isinstance(config, Mapping):
        checks.append(_check("config_root", "error", "Config root must be a JSON object."))
        config = {}

    _check_dry_run(config, checks)
    _check_runtime_boundaries(config, checks)
    _check_forbidden_keys(config, checks)
    _check_data_types(config, checks)
    _check_targets(config, checks, normalized)
    _check_limits(config, checks, normalized)
    _check_output_path(config, checks, normalized)

    errors = [item for item in checks if item["status"] == "error"]
    warnings = [item for item in checks if item["status"] == "warning"]
    gate = GATE_BLOCKED if errors else GATE_VALID

    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": (generated_at or datetime.now(tz=UTC)).isoformat(),
        "configPath": str(config_path) if config_path is not None else "",
        "sidecarOnly": True,
        "networkUsed": False,
        "readOnly": True,
        "productionIntegration": False,
        "liveIngestionStarted": False,
        "summary": {
            "gateDecision": gate,
            "errorCount": len(errors),
            "warningCount": len(warnings),
            "checkCount": len(checks),
            "operatorApprovalStillRequired": True,
        },
        "normalized": normalized,
        "checks": checks,
    }


def validate_bounded_live_config_file(config_path: str | Path) -> dict[str, object]:
    path = Path(config_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return validate_bounded_live_config(payload, config_path=path)


def write_validation_output(report: Mapping[str, object], output_json: str | Path) -> Path:
    target = Path(output_json)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _check_dry_run(config: Mapping[str, object], checks: list[dict[str, object]]) -> None:
    if config.get("dryRun") is True:
        checks.append(_check("dry_run", "ok", "Config explicitly requests dry-run validation."))
    else:
        checks.append(_check("dry_run", "error", "dryRun must be true until an operator approves live ingestion."))


def _check_runtime_boundaries(config: Mapping[str, object], checks: list[dict[str, object]]) -> None:
    bool_checks = {
        "networkExecution": False,
        "productionIntegration": False,
        "autoStart": False,
        "backgroundWorker": False,
        "warehouseMode": False,
        "mutateSavedArtifacts": False,
    }
    for key, expected in bool_checks.items():
        value = config.get(key)
        if value is None:
            checks.append(_check(key, "warning", f"{key} is omitted; approval packet should record it as false."))
        elif value is expected:
            checks.append(_check(key, "ok", f"{key} is explicitly false."))
        else:
            checks.append(_check(key, "error", f"{key} must be false for operator-readiness validation."))
    if config.get("requiresOperatorApproval") is True:
        checks.append(_check("requires_operator_approval", "ok", "Config records the operator approval gate."))
    else:
        checks.append(_check("requires_operator_approval", "error", "requiresOperatorApproval must be true."))


def _check_forbidden_keys(config: Mapping[str, object], checks: list[dict[str, object]]) -> None:
    forbidden = sorted(_find_forbidden_keys(config))
    if forbidden:
        checks.append(
            _check(
                "forbidden_keys",
                "error",
                "Config contains auth, private-key, order-placement, or trading fields.",
                {"keys": forbidden},
            )
        )
    else:
        checks.append(_check("forbidden_keys", "ok", "No auth, private-key, order-placement, or trading fields found."))


def _check_data_types(config: Mapping[str, object], checks: list[dict[str, object]]) -> None:
    data_types = _text_list(config.get("allowedDataTypes"))
    if not data_types:
        checks.append(_check("allowed_data_types", "warning", "allowedDataTypes is omitted; packet should list allowed public sidecar data."))
        return
    unknown = sorted(set(data_types) - ALLOWED_DATA_TYPES - DISALLOWED_DATA_TYPES)
    disallowed = sorted(set(data_types) & DISALLOWED_DATA_TYPES)
    if disallowed:
        checks.append(_check("allowed_data_types", "error", "Disallowed data types are present.", {"dataTypes": disallowed}))
    elif unknown:
        checks.append(_check("allowed_data_types", "error", "Unknown data types are present.", {"dataTypes": unknown}))
    else:
        checks.append(_check("allowed_data_types", "ok", "Data types are public sidecar-only inputs."))


def _check_targets(
    config: Mapping[str, object],
    checks: list[dict[str, object]],
    normalized: dict[str, object],
) -> None:
    targets = config.get("targets")
    if not isinstance(targets, Mapping):
        checks.append(_check("targets", "error", "targets must be an object with explicit market/event identifiers."))
        normalized["targetCount"] = 0
        return
    values: list[str] = []
    for key in TARGET_KEYS:
        values.extend(_text_list(targets.get(key)))
    normalized["targetCount"] = len(values)
    normalized["targetKeys"] = [key for key in TARGET_KEYS if _text_list(targets.get(key))]
    bad_values = [value for value in values if value.lower() in {"*", "all", "any"}]
    if not values:
        checks.append(_check("targets", "error", "At least one explicit target identifier is required."))
    elif bad_values:
        checks.append(_check("targets", "error", "Wildcard or all-market targets are forbidden.", {"targets": bad_values}))
    elif len(values) > HARD_LIMITS["maxMarkets"]:
        checks.append(_check("targets", "error", "Target count exceeds hard maxMarkets cap.", {"targetCount": len(values)}))
    else:
        checks.append(_check("targets", "ok", "Targets are explicit and bounded.", {"targetCount": len(values)}))


def _check_limits(
    config: Mapping[str, object],
    checks: list[dict[str, object]],
    normalized: dict[str, object],
) -> None:
    limits = config.get("limits")
    if not isinstance(limits, Mapping):
        checks.append(_check("limits", "error", "limits must be an object."))
        return
    normalized_limits: dict[str, int] = {}
    for key, hard_cap in HARD_LIMITS.items():
        value = _int_value(limits.get(key))
        if value is None:
            checks.append(_check(f"limits.{key}", "error", f"{key} must be an integer."))
            continue
        normalized_limits[key] = value
        if value <= 0:
            checks.append(_check(f"limits.{key}", "error", f"{key} must be positive."))
        elif value > hard_cap:
            checks.append(_check(f"limits.{key}", "error", f"{key} exceeds hard cap {hard_cap}."))
        else:
            checks.append(_check(f"limits.{key}", "ok", f"{key} is within hard cap {hard_cap}."))
    normalized["limits"] = normalized_limits
    target_count = int(normalized.get("targetCount") or 0)
    max_markets = normalized_limits.get("maxMarkets")
    if max_markets is not None and target_count > max_markets:
        checks.append(_check("limits.maxMarkets", "error", "Target count exceeds configured maxMarkets."))
    _check_optional_public_trade_limits(limits, checks, normalized, normalized_limits)


def _check_optional_public_trade_limits(
    limits: Mapping[str, object],
    checks: list[dict[str, object]],
    normalized: dict[str, object],
    normalized_limits: Mapping[str, int],
) -> None:
    raw_value = limits.get("maxPublicTradesPerTarget")
    normalized["maxPublicTradesPerTarget"] = None
    if raw_value is None:
        return
    value = _int_value(raw_value)
    if value is None:
        checks.append(_check("limits.maxPublicTradesPerTarget", "error", "maxPublicTradesPerTarget must be an integer when present."))
        return
    normalized["maxPublicTradesPerTarget"] = value
    hard_cap = OPTIONAL_LIMITS["maxPublicTradesPerTarget"]
    if value <= 0:
        checks.append(_check("limits.maxPublicTradesPerTarget", "error", "maxPublicTradesPerTarget must be positive when present."))
        return
    if value > hard_cap:
        checks.append(_check("limits.maxPublicTradesPerTarget", "error", f"maxPublicTradesPerTarget exceeds hard cap {hard_cap}."))
        return
    target_count = int(normalized.get("targetCount") or 0)
    max_rows = normalized_limits.get("maxRows")
    if max_rows is not None and target_count > 1:
        market_row_budget = target_count
        trade_budget = max_rows - market_row_budget
        requested_trade_budget = value * target_count
        if requested_trade_budget > trade_budget:
            checks.append(
                _check(
                    "limits.maxPublicTradesPerTarget",
                    "error",
                    "Per-target public-trade budget must fit inside maxRows after one market row per target.",
                    {
                        "targetCount": target_count,
                        "requestedTradeBudget": requested_trade_budget,
                        "availableTradeBudget": trade_budget,
                    },
                )
            )
            return
    checks.append(_check("limits.maxPublicTradesPerTarget", "ok", "Per-target public-trade cap fits inside aggregate safety limits."))


def _check_output_path(
    config: Mapping[str, object],
    checks: list[dict[str, object]],
    normalized: dict[str, object],
) -> None:
    output = config.get("output")
    sqlite_path = ""
    if isinstance(output, Mapping):
        sqlite_path = _text(output.get("sqlitePath") or output.get("dbPath"))
    if not sqlite_path:
        sqlite_path = _text(config.get("sqlitePath") or config.get("dbPath"))
    normalized["sqlitePath"] = sqlite_path
    if not sqlite_path:
        checks.append(_check("output.sqlitePath", "error", "A local SQLite output path is required."))
        return
    lower = sqlite_path.lower()
    if "://" in lower or lower.startswith(("http:", "https:", "postgres:", "redis:", "s3:")):
        checks.append(_check("output.sqlitePath", "error", "Output path must be a local SQLite filesystem path."))
        return
    path = Path(sqlite_path)
    if path.suffix not in SQLITE_SUFFIXES:
        checks.append(_check("output.sqlitePath", "error", "Output path must end in .db, .sqlite, or .sqlite3."))
        return
    parts = set(path.parts)
    forbidden = sorted(parts & FORBIDDEN_PATH_PARTS)
    if forbidden:
        checks.append(_check("output.sqlitePath", "error", "Output path is inside a forbidden repo artifact/runtime area.", {"parts": forbidden}))
        return
    if not (parts & ALLOWED_SIDECAR_PATH_PARTS):
        checks.append(
            _check(
                "output.sqlitePath",
                "warning",
                "Output path should normally live under .inspoly_indexer/ or indexer_sidecar_outputs/.",
            )
        )
    else:
        checks.append(_check("output.sqlitePath", "ok", "Output path is in an approved sidecar directory."))


def _find_forbidden_keys(value: object, *, prefix: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            text_key = str(key)
            normalized = _normalize_key(text_key)
            child_path = f"{prefix}.{text_key}" if prefix else text_key
            if any(part in normalized for part in FORBIDDEN_KEY_PARTS):
                found.add(child_path)
            found.update(_find_forbidden_keys(child, prefix=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.update(_find_forbidden_keys(child, prefix=f"{prefix}[{index}]"))
    return found


def _check(name: str, status: str, message: str, details: Mapping[str, object] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"name": name, "status": status, "message": message}
    if details:
        payload["details"] = dict(details)
    return payload


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _text(value: object) -> str:
    return str(value or "").strip()


def _int_value(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _normalize_key(value: str) -> str:
    return "".join("_" if char in "- ." else char.lower() for char in value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a proposed bounded live-indexer config without network calls.")
    parser.add_argument("--config-json", required=True, help="Local proposed config JSON.")
    parser.add_argument("--output-json", help="Optional path for the validation report.")
    args = parser.parse_args(argv)

    report = validate_bounded_live_config_file(args.config_json)
    if args.output_json:
        write_validation_output(report, args.output_json)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
