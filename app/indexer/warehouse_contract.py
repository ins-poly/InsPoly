from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


WAREHOUSE_W0_SCHEMA_VERSION = "indexer_warehouse_w0_contract_v1"

EXPECTED_WAREHOUSE_TABLES = (
    "indexer_cursors",
    "indexed_markets",
    "indexed_trades",
    "orderbook_snapshots",
    "wallet_index_snapshots",
    "score_history",
)

RAW_JSON_POLICY_COLUMNS = (
    "indexed_markets.raw_json",
    "indexed_trades.raw_json",
    "orderbook_snapshots.raw_json",
    "wallet_index_snapshots.raw_profile_json",
    "score_history.raw_metrics_json",
)

LOCAL_SIDECAR_ROOTS = (".inspoly_indexer", "indexer_sidecar_outputs")
FORBIDDEN_WAREHOUSE_PATH_PARTS = (
    "app",
    "docs",
    "release_manifests",
    "shadow_review_packets",
    "side_outcome_review_packets",
    "tests",
)


@dataclass(frozen=True, slots=True)
class WarehouseW0Status:
    status: str
    ready: bool
    blocking_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "ready": self.ready,
            "blockingReasons": list(self.blocking_reasons),
            "warnings": list(self.warnings),
        }


def table_contract_status(schema: Mapping[str, object]) -> dict[str, object]:
    expected = tuple(str(item) for item in schema.get("expectedTables", EXPECTED_WAREHOUSE_TABLES))
    present = tuple(str(item) for item in schema.get("presentTables", ()))
    missing = tuple(str(item) for item in schema.get("missingTables", ()))
    if not schema or schema.get("status") in {"missing_db", "sqlite_open_error"}:
        status = WarehouseW0Status(
            "unreadable_or_missing_schema",
            False,
            ("warehouse_schema_unreadable_or_missing",),
        )
    elif missing:
        status = WarehouseW0Status(
            "missing_expected_tables",
            False,
            tuple(f"missing_table:{table}" for table in missing),
        )
    else:
        status = WarehouseW0Status("complete", True)
    payload = status.as_dict()
    payload.update(
        {
            "expectedTables": list(expected),
            "presentTables": list(present),
            "missingTables": list(missing),
        }
    )
    return payload


def cursor_contract_status(cursor_health: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if not cursor_health:
        return WarehouseW0Status(
            "missing_cursors",
            False,
            ("missing_indexer_cursors",),
        ).as_dict()
    key_set = tuple(
        f"{item.get('source', '')}:{item.get('cursorKey', '')}"
        for item in cursor_health
    )
    error_items = [
        item for item in cursor_health
        if str(item.get("status") or "") not in {"ok", "idle"} or str(item.get("lastError") or "")
    ]
    stale_items = [item for item in cursor_health if bool(item.get("isStale"))]
    warnings: list[str] = []
    if stale_items:
        warnings.append(f"stale_cursor_count:{len(stale_items)}")
    if any(str(item.get("cursorKey") or "") == "public_trades" for item in cursor_health):
        warnings.append("aggregate_public_trade_cursor_only")
    if error_items:
        status = WarehouseW0Status(
            "cursor_errors",
            False,
            tuple(
                f"cursor_error:{item.get('source', '')}:{item.get('cursorKey', '')}"
                for item in error_items
            ),
            tuple(warnings),
        )
    else:
        status = WarehouseW0Status("ready_with_warnings" if warnings else "ready", True, (), tuple(warnings))
    payload = status.as_dict()
    payload.update(
        {
            "cursorCount": len(cursor_health),
            "cursorKeys": list(key_set),
            "staleCursorCount": len(stale_items),
            "cursorErrorCount": len(error_items),
        }
    )
    return payload


def raw_json_policy_status(summary: Mapping[str, object]) -> dict[str, object]:
    malformed_count = int(summary.get("malformedRawJsonCount") or 0)
    if malformed_count:
        status = WarehouseW0Status(
            "blocked_malformed_raw_json",
            False,
            (f"malformed_raw_json_count:{malformed_count}",),
        )
    else:
        status = WarehouseW0Status("ready", True)
    payload = status.as_dict()
    payload.update(
        {
            "malformedRawJsonCount": malformed_count,
            "policyColumns": list(RAW_JSON_POLICY_COLUMNS),
        }
    )
    return payload


def duplicate_policy_status(summary: Mapping[str, object]) -> dict[str, object]:
    duplicate_count = int(summary.get("duplicateIndicatorCount") or 0)
    if duplicate_count:
        status = WarehouseW0Status(
            "blocked_duplicate_indicators",
            False,
            (f"duplicate_indicator_count:{duplicate_count}",),
        )
    else:
        status = WarehouseW0Status("ready", True)
    payload = status.as_dict()
    payload["duplicateIndicatorCount"] = duplicate_count
    return payload


def collection_metadata_status(run_summary: Mapping[str, object] | None) -> dict[str, object]:
    collection = _public_trade_collection(run_summary)
    if not collection:
        return WarehouseW0Status(
            "external_summary_required",
            True,
            (),
            ("collection_metadata_not_stored_in_sidecar_db",),
        ).as_dict()
    policy = str(collection.get("collectionPolicy") or collection.get("mode") or "")
    rows_by_target = collection.get("rowsByTarget")
    starvation = tuple(str(item) for item in collection.get("targetStarvationWarnings", ()) if str(item))
    if policy == "per_target_public_trade_cap" and isinstance(rows_by_target, Mapping) and rows_by_target:
        status = WarehouseW0Status("per_target_metadata_ready", True, (), tuple(starvation))
    elif bool(collection.get("mayUnderrepresentTargets")):
        status = WarehouseW0Status(
            "aggregate_collection_warning",
            True,
            (),
            tuple(starvation) or ("aggregate_collection_may_underrepresent_targets",),
        )
    else:
        status = WarehouseW0Status(
            "metadata_present_but_not_per_target",
            True,
            (),
            ("per_target_collection_metadata_not_confirmed",),
        )
    payload = status.as_dict()
    payload.update(
        {
            "collectionPolicy": policy,
            "rowsByTarget": dict(rows_by_target) if isinstance(rows_by_target, Mapping) else {},
            "perTargetPublicTradeLimit": collection.get("perTargetPublicTradeLimit"),
            "aggregatePublicTradeLimit": collection.get("aggregatePublicTradeLimit"),
        }
    )
    return payload


def retention_policy_status(db_path: str | Path) -> dict[str, object]:
    path_text = str(db_path or "").strip()
    if not path_text:
        return WarehouseW0Status(
            "missing_local_path",
            False,
            ("missing_local_sidecar_db_path",),
        ).as_dict()
    lower = path_text.lower()
    if "://" in lower or lower.startswith(("http:", "https:", "postgres:", "redis:", "s3:")):
        return WarehouseW0Status(
            "blocked_external_or_service_path",
            False,
            ("warehouse_path_must_be_local_sqlite",),
        ).as_dict()
    path = Path(path_text)
    parts = set(path.parts)
    forbidden = tuple(sorted(parts & set(FORBIDDEN_WAREHOUSE_PATH_PARTS)))
    if forbidden:
        status = WarehouseW0Status(
            "blocked_forbidden_repo_area",
            False,
            tuple(f"forbidden_path_part:{part}" for part in forbidden),
        )
    elif parts & set(LOCAL_SIDECAR_ROOTS):
        status = WarehouseW0Status("local_sidecar_path_ready", True)
    else:
        status = WarehouseW0Status(
            "local_path_requires_operator_retention_policy",
            True,
            (),
            ("path_not_under_default_sidecar_root",),
        )
    payload = status.as_dict()
    payload.update(
        {
            "dbPath": path_text,
            "localOnlyDefault": True,
            "rawDbCommitDefault": False,
            "recommendedRoots": list(LOCAL_SIDECAR_ROOTS),
        }
    )
    return payload


def evaluate_warehouse_w0_contract(
    readiness_report: Mapping[str, object],
    *,
    run_summary: Mapping[str, object] | None = None,
) -> dict[str, object]:
    schema = readiness_report.get("schema") if isinstance(readiness_report.get("schema"), Mapping) else {}
    summary = readiness_report.get("summary") if isinstance(readiness_report.get("summary"), Mapping) else {}
    cursor_health = readiness_report.get("cursorHealth")
    cursor_rows = tuple(item for item in cursor_health if isinstance(item, Mapping)) if isinstance(cursor_health, Sequence) else ()
    table_status = table_contract_status(schema)  # type: ignore[arg-type]
    cursor_status = cursor_contract_status(cursor_rows)
    raw_status = raw_json_policy_status(summary)  # type: ignore[arg-type]
    duplicate_status = duplicate_policy_status(summary)  # type: ignore[arg-type]
    collection_status = collection_metadata_status(run_summary)
    retention_status = retention_policy_status(str(readiness_report.get("dbPath") or ""))

    components = (
        table_status,
        cursor_status,
        raw_status,
        duplicate_status,
        retention_status,
    )
    blocking: list[str] = []
    warnings: list[str] = []
    for component in components + (collection_status,):
        blocking.extend(str(item) for item in component.get("blockingReasons", ()) if str(item))
        warnings.extend(str(item) for item in component.get("warnings", ()) if str(item))

    ready = all(bool(component.get("ready")) for component in components)
    old_db_status = _old_db_compatibility_status(
        ready=ready,
        collection_status=str(collection_status.get("status") or ""),
        cursor_status=str(cursor_status.get("status") or ""),
        warnings=warnings,
    )
    return {
        "schemaVersion": WAREHOUSE_W0_SCHEMA_VERSION,
        "warehouseW0Ready": ready,
        "warehouseW0BlockingReasons": blocking,
        "warehouseW0Warnings": warnings,
        "tableContractStatus": table_status,
        "cursorContractStatus": cursor_status,
        "rawJsonPolicyStatus": raw_status,
        "duplicatePolicyStatus": duplicate_status,
        "collectionMetadataStatus": collection_status,
        "retentionPolicyStatus": retention_status,
        "oldDbCompatibility": old_db_status,
        "runtimeBoundaries": {
            "sidecarOnly": True,
            "networkUsed": False,
            "productionIntegration": False,
            "liveIngestionAllowed": False,
            "warehouseWriterImplemented": False,
            "reportBrowserIntegration": False,
        },
    }


def _public_trade_collection(run_summary: Mapping[str, object] | None) -> Mapping[str, object]:
    if not isinstance(run_summary, Mapping):
        return {}
    summary = run_summary.get("summary")
    if isinstance(summary, Mapping):
        collection = summary.get("publicTradeCollection")
        if isinstance(collection, Mapping):
            return collection
    collection = run_summary.get("publicTradeCollection")
    return collection if isinstance(collection, Mapping) else {}


def _old_db_compatibility_status(
    *,
    ready: bool,
    collection_status: str,
    cursor_status: str,
    warnings: Sequence[str],
) -> dict[str, object]:
    if not ready:
        status = "sidecar_readable_not_w0_ready"
    elif collection_status == "external_summary_required" or "aggregate_public_trade_cursor_only" in warnings:
        status = "sidecar_readable_w0_limited"
    else:
        status = "sidecar_readable_w0_ready"
    return {
        "status": status,
        "oldSidecarDbsRemainReadable": True,
        "requiresMigration": False,
        "cursorStatus": cursor_status,
        "collectionMetadataStatus": collection_status,
        "notes": [
            "W0 does not require old sidecar DB migration.",
            "Per-target collection metadata may live in run summaries instead of the DB schema.",
        ],
    }
