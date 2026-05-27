#!/usr/bin/env python3
"""Build a local-only W2 registry from compact warehouse review summaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "indexer_warehouse_registry"
SCHEMA_VERSION = "indexer_warehouse_registry_v1"

GATE_READY = "indexer_warehouse_registry_ready"
GATE_BLOCKED_MALFORMED_INPUT = "indexer_warehouse_registry_blocked_malformed_input"
GATE_NO_INPUTS = "indexer_warehouse_registry_blocked_no_inputs"

CLASS_ACTIVE = "active_review_candidate"
CLASS_RETAINED = "retained_reference"
CLASS_STALE = "stale_candidate"
CLASS_CLEANUP = "cleanup_candidate"
CLASS_BLOCKED = "blocked_not_w0_ready"

READY_W1_GATE = "ready_for_local_warehouse_review"

BLOCKED_RUNTIME_SCOPES = (
    "live_ingestion",
    "warehouse_writer_copy_pipeline",
    "scheduler_background_daemon",
    "production_runtime_imports",
    "report_browser_integration",
    "production_storage_schema_migration",
    "saved_report_mutation",
    "scoring_gate_funding_phase3_changes",
    "clob_auth_private_keys_trading_order_placement_external_writes",
)

DEFAULT_MAX_ACTIVE_RUNS = 3
DEFAULT_MAX_RETAINED_RUNS = 10
DEFAULT_RAW_DB_BYTE_WARNING = 2_000_000_000


def build_warehouse_registry(
    summary_paths: Sequence[str | Path],
    *,
    dry_run: bool = False,
    max_active_runs: int = DEFAULT_MAX_ACTIVE_RUNS,
    max_retained_runs: int = DEFAULT_MAX_RETAINED_RUNS,
    raw_db_byte_warning: int = DEFAULT_RAW_DB_BYTE_WARNING,
    now: datetime | None = None,
) -> dict[str, object]:
    """Build a compact registry from W1 aggregate or per-DB summary JSON files."""

    generated_at = (now or datetime.now(tz=UTC)).isoformat()
    paths = [Path(path) for path in summary_paths]
    report: dict[str, object] = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at,
        "tool": "tools/indexer_warehouse_registry.py",
        "sidecarOnly": True,
        "readOnly": True,
        "networkUsed": False,
        "inputDbsMutated": False,
        "savedReportsMutated": False,
        "productionIntegration": False,
        "artifactDeletionPerformed": False,
        "artifactMovePerformed": False,
        "schemaMigrationPerformed": False,
        "dryRun": dry_run,
        "inputSummaryPaths": [str(path) for path in paths],
        "registryPolicy": {
            "manifestLocationPolicy": "commit_compact_registry_json_docs_under_validation_outputs_and_docs",
            "rawDbPolicy": "local_only_do_not_commit",
            "rawDbPathReferencesAllowed": True,
            "rawDbPathReferencesLocalOnly": True,
            "maxActiveRuns": max_active_runs,
            "maxRetainedRuns": max_retained_runs,
            "rawDbByteWarning": raw_db_byte_warning,
            "cleanupMode": "manual_only_no_deletion_performed",
        },
        "allowedMetadataFields": [
            "runId",
            "label",
            "sourceDbPath",
            "rawSummaryPath",
            "sourceSummaryPath",
            "createdOrObservedAt",
            "targetSlugs",
            "targetSetIdentity",
            "marketCount",
            "tradeCount",
            "cursorCount",
            "warehouseW0Ready",
            "w1GateDecision",
            "malformedRawJsonCount",
            "duplicateIndicatorCount",
            "collectionMetadataStatus",
            "rowsByTarget",
            "retentionClassification",
            "retentionRecommendation",
            "blockedScopes",
        ],
        "forbiddenMetadataFields": [
            "privateKeys",
            "apiSecrets",
            "authTokens",
            "orderPlacementPayloads",
            "tradingInstructions",
            "walletPrivateData",
            "copiedReportMetrics",
        ],
        "runs": [],
        "errors": [],
        "summary": {
            "gateDecision": "",
            "inputSummaryCount": len(paths),
            "runCount": 0,
            "activeReviewCandidates": 0,
            "retainedReferences": 0,
            "staleCandidates": 0,
            "cleanupCandidates": 0,
            "blockedNotW0Ready": 0,
            "totalMarkets": 0,
            "totalTrades": 0,
            "totalCursors": 0,
            "malformedRawJsonCount": 0,
            "duplicateIndicatorCount": 0,
            "rawDbPathsReferenced": 0,
            "localOnlyRawDbReferences": True,
            "nextAllowedAction": "",
        },
    }

    if not paths:
        _set_gate(report, GATE_NO_INPUTS, "provide_w1_summary_json_before_w2_registry_review")
        return report

    entries: list[dict[str, object]] = []
    errors: list[str] = []
    for path in paths:
        try:
            payload = _read_json_object(path)
            entries.extend(_entries_from_payload(payload, source_summary_path=path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{path}:{exc}")

    if errors:
        report["errors"] = errors
        _set_gate(report, GATE_BLOCKED_MALFORMED_INPUT, "repair_malformed_w1_summary_before_registry_update")
        return report

    entries.sort(key=lambda item: (str(item.get("retentionClassification", "")), str(item.get("label", ""))))
    report["runs"] = entries
    _update_summary(report)
    _set_gate(report, GATE_READY, "use_registry_for_local_retention_review_only_w3_requires_approval")
    return report


def write_registry_output(report: Mapping[str, object], output_json: str | Path) -> Path:
    target = Path(output_json)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _entries_from_payload(payload: Mapping[str, object], *, source_summary_path: Path) -> list[dict[str, object]]:
    generated_at = str(payload.get("generatedAt") or "")
    runs = payload.get("runs")
    if isinstance(runs, Sequence) and not isinstance(runs, (str, bytes, bytearray)):
        entries: list[dict[str, object]] = []
        for index, item in enumerate(runs):
            if not isinstance(item, Mapping):
                raise ValueError(f"runs[{index}] must be an object")
            entries.append(_entry_from_run(item, source_summary_path=source_summary_path, parent_generated_at=generated_at))
        return entries

    if str(payload.get("reportType") or "") == "indexer_warehouse_manual_command":
        return [_entry_from_manual_command(payload, source_summary_path=source_summary_path)]

    raise ValueError("summary must contain a runs array or an indexer_warehouse_manual_command report")


def _entry_from_manual_command(payload: Mapping[str, object], *, source_summary_path: Path) -> dict[str, object]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    collection = payload.get("collectionMetadata") if isinstance(payload.get("collectionMetadata"), Mapping) else {}
    rows_by_target = collection.get("rowsByTarget") if isinstance(collection.get("rowsByTarget"), Mapping) else {}
    run = {
        "label": _derive_label(str(payload.get("inputDbPath") or source_summary_path)),
        "dbPath": payload.get("inputDbPath", ""),
        "rawSummaryPath": payload.get("runSummaryPath", ""),
        "gateDecision": summary.get("gateDecision", ""),
        "marketCount": summary.get("marketCount", 0),
        "tradeCount": summary.get("tradeCount", 0),
        "cursorCount": summary.get("cursorCount", 0),
        "malformedRawJsonCount": summary.get("malformedRawJsonCount", 0),
        "duplicateIndicatorCount": summary.get("duplicateIndicatorCount", 0),
        "warehouseW0Ready": summary.get("warehouseW0Ready", False),
        "collectionMetadataStatus": summary.get("collectionMetadataStatus", ""),
        "rowsByTarget": rows_by_target,
        "warnings": _text_list(payload.get("findings")),
    }
    return _entry_from_run(run, source_summary_path=source_summary_path, parent_generated_at=str(payload.get("generatedAt") or ""))


def _entry_from_run(
    run: Mapping[str, object],
    *,
    source_summary_path: Path,
    parent_generated_at: str,
) -> dict[str, object]:
    label = str(run.get("label") or _derive_label(str(run.get("dbPath") or source_summary_path)))
    db_path = str(run.get("dbPath") or run.get("inputDbPath") or "")
    rows_by_target = _int_mapping(run.get("rowsByTarget"))
    target_slugs = _target_slugs(run, rows_by_target)
    market_count = _int_value(run.get("marketCount"))
    trade_count = _int_value(run.get("tradeCount"))
    cursor_count = _int_value(run.get("cursorCount"))
    malformed_count = _int_value(run.get("malformedRawJsonCount"))
    duplicate_count = _int_value(run.get("duplicateIndicatorCount"))
    w0_ready = bool(run.get("warehouseW0Ready"))
    w1_gate = str(run.get("gateDecision") or "")
    collection_status = str(run.get("collectionMetadataStatus") or "")
    warnings = _text_list(run.get("warnings"))
    classification = _retention_classification(
        w1_gate=w1_gate,
        w0_ready=w0_ready,
        market_count=market_count,
        trade_count=trade_count,
        malformed_count=malformed_count,
        duplicate_count=duplicate_count,
        collection_status=collection_status,
        warnings=warnings,
    )
    return {
        "runId": _run_id(label, db_path, source_summary_path),
        "label": label,
        "sourceDbPath": db_path,
        "sourceDbPathLocalOnly": _is_local_reference(db_path),
        "rawDbCommitDefault": False,
        "rawSummaryPath": str(run.get("rawSummaryPath") or run.get("runSummaryPath") or ""),
        "sourceSummaryPath": str(source_summary_path),
        "createdOrObservedAt": str(run.get("createdAt") or run.get("observedAt") or parent_generated_at),
        "targetSlugs": target_slugs,
        "targetSetIdentity": _target_set_identity(target_slugs, db_path),
        "marketCount": market_count,
        "tradeCount": trade_count,
        "cursorCount": cursor_count,
        "w1GateDecision": w1_gate,
        "warehouseW0Ready": w0_ready,
        "malformedRawJsonCount": malformed_count,
        "duplicateIndicatorCount": duplicate_count,
        "collectionMetadataStatus": collection_status,
        "rowsByTarget": rows_by_target,
        "warnings": warnings,
        "stalenessStatus": _staleness_status(warnings),
        "retentionClassification": classification,
        "retentionRecommendation": _retention_recommendation(classification),
        "blockedScopes": list(BLOCKED_RUNTIME_SCOPES),
    }


def _retention_classification(
    *,
    w1_gate: str,
    w0_ready: bool,
    market_count: int,
    trade_count: int,
    malformed_count: int,
    duplicate_count: int,
    collection_status: str,
    warnings: Sequence[str],
) -> str:
    if w1_gate != READY_W1_GATE or not w0_ready or malformed_count or duplicate_count:
        return CLASS_BLOCKED
    if market_count <= 0 or trade_count <= 0:
        return CLASS_CLEANUP
    if collection_status == "per_target_metadata_ready":
        return CLASS_ACTIVE
    if _staleness_status(warnings) == "stale_cursor_warning_only" and collection_status not in {"external_summary_required", ""}:
        return CLASS_STALE
    return CLASS_RETAINED


def _retention_recommendation(classification: str) -> str:
    recommendations = {
        CLASS_ACTIVE: "preserve_raw_db_locally_as_current_review_candidate_until_w3_or_newer_per_target_run",
        CLASS_RETAINED: "retain_compact_summary_and_keep_raw_db_local_only_as_reference_until_superseded",
        CLASS_STALE: "refresh_or_retire_manually_after_preserving_compact_summary",
        CLASS_CLEANUP: "manual_cleanup_candidate_after_confirming_no_current_gate_depends_on_raw_db",
        CLASS_BLOCKED: "do_not_use_for_w2_review_until_w0_or_summary_blockers_are_resolved",
    }
    return recommendations[classification]


def _update_summary(report: dict[str, object]) -> None:
    runs = report.get("runs") if isinstance(report.get("runs"), Sequence) else []
    entries = [item for item in runs if isinstance(item, Mapping)]
    classes = [str(item.get("retentionClassification") or "") for item in entries]
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary.update(
        {
            "runCount": len(entries),
            "activeReviewCandidates": classes.count(CLASS_ACTIVE),
            "retainedReferences": classes.count(CLASS_RETAINED),
            "staleCandidates": classes.count(CLASS_STALE),
            "cleanupCandidates": classes.count(CLASS_CLEANUP),
            "blockedNotW0Ready": classes.count(CLASS_BLOCKED),
            "totalMarkets": sum(_int_value(item.get("marketCount")) for item in entries),
            "totalTrades": sum(_int_value(item.get("tradeCount")) for item in entries),
            "totalCursors": sum(_int_value(item.get("cursorCount")) for item in entries),
            "malformedRawJsonCount": sum(_int_value(item.get("malformedRawJsonCount")) for item in entries),
            "duplicateIndicatorCount": sum(_int_value(item.get("duplicateIndicatorCount")) for item in entries),
            "rawDbPathsReferenced": sum(1 for item in entries if str(item.get("sourceDbPath") or "")),
            "localOnlyRawDbReferences": all(bool(item.get("sourceDbPathLocalOnly")) for item in entries),
        }
    )


def _read_json_object(path: Path) -> dict[str, object]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("JSON root must be an object")
    return loaded


def _derive_label(path_text: str) -> str:
    name = Path(path_text).parent.name or Path(path_text).stem or "warehouse_run"
    return name.replace(" ", "_")


def _run_id(label: str, db_path: str, source_summary_path: Path) -> str:
    digest = hashlib.sha256(f"{label}\0{db_path}\0{source_summary_path}".encode("utf-8")).hexdigest()[:12]
    safe_label = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in label).strip("_")
    return f"{safe_label or 'warehouse_run'}-{digest}"


def _target_set_identity(target_slugs: Sequence[str], db_path: str) -> str:
    seed = "\0".join(sorted(target_slugs)) if target_slugs else db_path
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"target_set_{digest}"


def _target_slugs(run: Mapping[str, object], rows_by_target: Mapping[str, int]) -> list[str]:
    explicit = _text_list(run.get("targetSlugs"))
    if explicit:
        return sorted(explicit)
    return sorted(str(key) for key in rows_by_target)


def _staleness_status(warnings: Sequence[str]) -> str:
    return "stale_cursor_warning_only" if any(str(item).startswith("stale_cursor_count:") for item in warnings) else "not_marked_stale"


def _is_local_reference(path_text: str) -> bool:
    lower = str(path_text).lower().strip()
    return bool(lower) and "://" not in lower and not lower.startswith(("http:", "https:", "postgres:", "redis:", "s3:"))


def _int_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        text_key = str(key)
        if not text_key:
            continue
        result[text_key] = _int_value(item)
    return result


def _text_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value if str(item)]


def _int_value(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _set_gate(report: dict[str, object], gate: str, next_action: str) -> None:
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary["gateDecision"] = gate
    summary["nextAllowedAction"] = next_action


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--w1-summary-json", action="append", required=True, help="W1 aggregate or per-DB summary JSON.")
    parser.add_argument("--output-json", help="Optional registry JSON output path.")
    parser.add_argument("--dry-run", action="store_true", help="Mark the registry as a dry-run review artifact.")
    parser.add_argument("--max-active-runs", type=int, default=DEFAULT_MAX_ACTIVE_RUNS)
    parser.add_argument("--max-retained-runs", type=int, default=DEFAULT_MAX_RETAINED_RUNS)
    parser.add_argument("--raw-db-byte-warning", type=int, default=DEFAULT_RAW_DB_BYTE_WARNING)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = build_warehouse_registry(
        args.w1_summary_json,
        dry_run=args.dry_run,
        max_active_runs=args.max_active_runs,
        max_retained_runs=args.max_retained_runs,
        raw_db_byte_warning=args.raw_db_byte_warning,
    )
    if args.output_json:
        write_registry_output(report, args.output_json)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
