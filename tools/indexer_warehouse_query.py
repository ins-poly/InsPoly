#!/usr/bin/env python3
"""Query compact indexer warehouse registry metadata for analyst review."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "indexer_warehouse_query"
SCHEMA_VERSION = "indexer_warehouse_query_v1"

MODE_LIST_RUNS = "list-runs"
MODE_SUMMARIZE_RUN = "summarize-run"
MODE_AGGREGATE = "aggregate"
MODE_TARGET_COVERAGE = "target-coverage"
MODE_HEALTH = "health"
MODE_RETENTION_STATUS = "retention-status"
MODE_BLOCKED_SCOPES = "blocked-scopes"
QUERY_MODES = (
    MODE_LIST_RUNS,
    MODE_SUMMARIZE_RUN,
    MODE_AGGREGATE,
    MODE_TARGET_COVERAGE,
    MODE_HEALTH,
    MODE_RETENTION_STATUS,
    MODE_BLOCKED_SCOPES,
)

GATE_READY = "indexer_warehouse_query_ready"
GATE_EMPTY_REGISTRY = "indexer_warehouse_query_empty_registry"
GATE_BLOCKED_MALFORMED_REGISTRY = "indexer_warehouse_query_blocked_malformed_registry"
GATE_RUN_NOT_FOUND = "indexer_warehouse_query_run_not_found"

QUERY_WARNINGS = (
    "sidecar_only",
    "advisory_only",
    "not_scoring_signal",
    "not_report_integrated",
    "local_paths_may_be_machine_specific",
    "stale_data_possible_no_live_refresh",
)

UNSUPPORTED_QUERY_MODES = (
    "score_ranking",
    "insider_verdicts",
    "funding_conclusions",
    "trading_order_data",
    "private_auth_data",
    "report_embedding",
    "browser_ui_panel",
    "live_refresh",
    "raw_db_mutation",
)


def run_warehouse_query(
    registry_json: str | Path,
    *,
    query_mode: str,
    run_id: str | None = None,
    label: str | None = None,
    output_json: str | Path | None = None,
    output_markdown: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Run a read-only analyst query over compact W2 registry metadata."""

    if query_mode not in QUERY_MODES:
        raise ValueError(f"unsupported query mode: {query_mode}")

    generated_at = (now or datetime.now(tz=UTC)).isoformat()
    registry_path = Path(registry_json)
    report = _base_report(registry_path, query_mode=query_mode, generated_at=generated_at)

    try:
        registry = _read_registry(registry_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report["errors"] = [str(exc)]
        _set_gate(report, GATE_BLOCKED_MALFORMED_REGISTRY, "repair_or_regenerate_w2_registry_before_query")
        return _write_outputs(report, output_json=output_json, output_markdown=output_markdown)

    runs = _registry_runs(registry)
    report["registryProvenance"] = _registry_provenance(registry)
    report["aggregate"] = _aggregate_summary(registry, runs)
    report["targetCoverage"] = _target_coverage(runs)
    report["health"] = _health_summary(runs)
    report["retentionStatus"] = _retention_status(runs)
    report["blockedScopes"] = _blocked_scopes(runs)
    report["runs"] = _run_views(runs) if query_mode == MODE_LIST_RUNS else []

    if not runs:
        _set_gate(report, GATE_EMPTY_REGISTRY, "regenerate_registry_from_w1_summaries_before_analyst_query")
        report["queryResult"] = {}
        return _write_outputs(report, output_json=output_json, output_markdown=output_markdown)

    selected_run = None
    if query_mode == MODE_SUMMARIZE_RUN:
        selected_run = _select_run(runs, run_id=run_id, label=label)
        if selected_run is None:
            _set_gate(report, GATE_RUN_NOT_FOUND, "select_existing_run_id_or_label_from_registry")
            report["queryResult"] = {}
            return _write_outputs(report, output_json=output_json, output_markdown=output_markdown)
        report["selectedRun"] = _run_view(selected_run)

    report["queryResult"] = _query_result(
        query_mode=query_mode,
        runs=runs,
        selected_run=selected_run,
        report=report,
    )
    _set_gate(report, GATE_READY, "use_query_output_as_sidecar_advisory_summary_only")
    return _write_outputs(report, output_json=output_json, output_markdown=output_markdown)


def write_query_output(report: Mapping[str, object], output_json: str | Path) -> Path:
    path = Path(output_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _base_report(registry_path: Path, *, query_mode: str, generated_at: str) -> dict[str, object]:
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at,
        "queryMode": query_mode,
        "sourceRegistry": str(registry_path),
        "sidecarOnly": True,
        "readOnly": True,
        "networkUsed": False,
        "inputRegistryMutated": False,
        "inputDbsMutated": False,
        "savedReportsMutated": False,
        "productionIntegration": False,
        "reportBrowserIntegration": False,
        "scoringSignal": False,
        "runtimeImplementationAllowed": False,
        "warnings": list(QUERY_WARNINGS),
        "unsupportedQueryModes": list(UNSUPPORTED_QUERY_MODES),
        "registryProvenance": {},
        "runs": [],
        "selectedRun": {},
        "aggregate": {},
        "targetCoverage": {},
        "health": {},
        "retentionStatus": {},
        "blockedScopes": [],
        "queryResult": {},
        "errors": [],
        "summary": {
            "gateDecision": "",
            "queryMode": query_mode,
            "runCount": 0,
            "activeReviewCandidates": 0,
            "retainedReferences": 0,
            "cleanupCandidates": 0,
            "blockedNotW0Ready": 0,
            "totalMarkets": 0,
            "totalTrades": 0,
            "totalCursors": 0,
            "malformedRawJsonCount": 0,
            "duplicateIndicatorCount": 0,
            "targetCoverageCount": 0,
            "blockedScopeCount": 0,
            "nextAllowedAction": "",
        },
    }


def _read_registry(path: Path) -> dict[str, object]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("registry root must be an object")
    if loaded.get("reportType") != "indexer_warehouse_registry":
        raise ValueError("registry reportType must be indexer_warehouse_registry")
    runs = loaded.get("runs")
    if not isinstance(runs, Sequence) or isinstance(runs, (str, bytes, bytearray)):
        raise ValueError("registry runs must be a list")
    return loaded


def _registry_runs(registry: Mapping[str, object]) -> list[Mapping[str, object]]:
    runs = registry.get("runs")
    if not isinstance(runs, Sequence) or isinstance(runs, (str, bytes, bytearray)):
        return []
    return [item for item in runs if isinstance(item, Mapping)]


def _registry_provenance(registry: Mapping[str, object]) -> dict[str, object]:
    return {
        "reportType": registry.get("reportType", ""),
        "schemaVersion": registry.get("schemaVersion", ""),
        "generatedAt": registry.get("generatedAt", ""),
        "tool": registry.get("tool", ""),
        "inputSummaryPaths": _text_list(registry.get("inputSummaryPaths")),
        "registryGate": _mapping_value(registry.get("summary"), "gateDecision"),
    }


def _aggregate_summary(registry: Mapping[str, object], runs: Sequence[Mapping[str, object]]) -> dict[str, object]:
    summary = registry.get("summary") if isinstance(registry.get("summary"), Mapping) else {}
    if summary:
        aggregate = {
            "runCount": _int_value(summary.get("runCount")),
            "activeReviewCandidates": _int_value(summary.get("activeReviewCandidates")),
            "retainedReferences": _int_value(summary.get("retainedReferences")),
            "cleanupCandidates": _int_value(summary.get("cleanupCandidates")),
            "blockedNotW0Ready": _int_value(summary.get("blockedNotW0Ready")),
            "totalMarkets": _int_value(summary.get("totalMarkets")),
            "totalTrades": _int_value(summary.get("totalTrades")),
            "totalCursors": _int_value(summary.get("totalCursors")),
            "malformedRawJsonCount": _int_value(summary.get("malformedRawJsonCount")),
            "duplicateIndicatorCount": _int_value(summary.get("duplicateIndicatorCount")),
            "localOnlyRawDbReferences": bool(summary.get("localOnlyRawDbReferences", True)),
        }
    else:
        classifications = [str(run.get("retentionClassification") or "") for run in runs]
        aggregate = {
            "runCount": len(runs),
            "activeReviewCandidates": classifications.count("active_review_candidate"),
            "retainedReferences": classifications.count("retained_reference"),
            "cleanupCandidates": classifications.count("cleanup_candidate"),
            "blockedNotW0Ready": classifications.count("blocked_not_w0_ready"),
            "totalMarkets": sum(_int_value(run.get("marketCount")) for run in runs),
            "totalTrades": sum(_int_value(run.get("tradeCount")) for run in runs),
            "totalCursors": sum(_int_value(run.get("cursorCount")) for run in runs),
            "malformedRawJsonCount": sum(_int_value(run.get("malformedRawJsonCount")) for run in runs),
            "duplicateIndicatorCount": sum(_int_value(run.get("duplicateIndicatorCount")) for run in runs),
            "localOnlyRawDbReferences": all(bool(run.get("sourceDbPathLocalOnly", True)) for run in runs),
        }
    aggregate["advisoryOnly"] = True
    aggregate["scoringSignal"] = False
    return aggregate


def _target_coverage(runs: Sequence[Mapping[str, object]]) -> dict[str, object]:
    targets: dict[str, dict[str, object]] = {}
    missing_metadata_runs: list[str] = []
    for run in runs:
        rows_by_target = _int_mapping(run.get("rowsByTarget"))
        if not rows_by_target:
            missing_metadata_runs.append(str(run.get("label") or run.get("runId") or "unknown"))
            continue
        for slug, rows in rows_by_target.items():
            item = targets.setdefault(
                slug,
                {
                    "targetSlug": slug,
                    "totalRows": 0,
                    "runIds": [],
                    "runLabels": [],
                    "retentionClassifications": [],
                },
            )
            item["totalRows"] = _int_value(item.get("totalRows")) + rows
            item["runIds"].append(str(run.get("runId") or ""))
            item["runLabels"].append(str(run.get("label") or ""))
            item["retentionClassifications"].append(str(run.get("retentionClassification") or ""))
    return {
        "coveredTargetCount": len(targets),
        "targets": sorted(targets.values(), key=lambda item: str(item["targetSlug"])),
        "runsMissingTargetMetadata": missing_metadata_runs,
        "targetMetadataCoverageStatus": "target_metadata_present" if targets else "target_metadata_unavailable",
        "notes": [
            "Target coverage is derived from compact registry rowsByTarget fields.",
            "Runs without rowsByTarget cannot prove target-level distribution from W3 alone.",
        ],
    }


def _health_summary(runs: Sequence[Mapping[str, object]]) -> dict[str, object]:
    w1_gates: dict[str, int] = {}
    collection_statuses: dict[str, int] = {}
    stale_warning_runs: list[str] = []
    for run in runs:
        _bump(w1_gates, str(run.get("w1GateDecision") or "unknown"))
        _bump(collection_statuses, str(run.get("collectionMetadataStatus") or "unknown"))
        if str(run.get("stalenessStatus") or "") == "stale_cursor_warning_only":
            stale_warning_runs.append(str(run.get("label") or run.get("runId") or "unknown"))
    return {
        "w0ReadyRuns": sum(1 for run in runs if bool(run.get("warehouseW0Ready"))),
        "w0NotReadyRuns": sum(1 for run in runs if not bool(run.get("warehouseW0Ready"))),
        "w1GateDistribution": w1_gates,
        "collectionMetadataDistribution": collection_statuses,
        "malformedRawJsonCount": sum(_int_value(run.get("malformedRawJsonCount")) for run in runs),
        "duplicateIndicatorCount": sum(_int_value(run.get("duplicateIndicatorCount")) for run in runs),
        "staleWarningRuns": stale_warning_runs,
        "healthStatus": "ready_with_stale_historical_warning" if stale_warning_runs else "ready",
        "staleDataWarning": "Registry is historical and does not perform live refresh.",
    }


def _retention_status(runs: Sequence[Mapping[str, object]]) -> dict[str, object]:
    distribution: dict[str, int] = {}
    recommendations: list[dict[str, object]] = []
    for run in runs:
        classification = str(run.get("retentionClassification") or "unknown")
        _bump(distribution, classification)
        recommendations.append(
            {
                "runId": run.get("runId", ""),
                "label": run.get("label", ""),
                "classification": classification,
                "recommendation": run.get("retentionRecommendation", ""),
                "sourceDbPath": run.get("sourceDbPath", ""),
                "sourceDbPathLocalOnly": bool(run.get("sourceDbPathLocalOnly", True)),
            }
        )
    return {
        "classificationDistribution": distribution,
        "recommendations": recommendations,
        "manualCleanupOnly": True,
        "artifactDeletionPerformed": False,
    }


def _blocked_scopes(runs: Sequence[Mapping[str, object]]) -> list[str]:
    scopes: set[str] = set()
    for run in runs:
        scopes.update(_text_list(run.get("blockedScopes")))
    return sorted(scopes)


def _run_views(runs: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [_run_view(run) for run in runs]


def _run_view(run: Mapping[str, object]) -> dict[str, object]:
    return {
        "runId": run.get("runId", ""),
        "label": run.get("label", ""),
        "retentionClassification": run.get("retentionClassification", ""),
        "sourceDbPath": run.get("sourceDbPath", ""),
        "sourceDbPathLocalOnly": bool(run.get("sourceDbPathLocalOnly", True)),
        "marketCount": _int_value(run.get("marketCount")),
        "tradeCount": _int_value(run.get("tradeCount")),
        "cursorCount": _int_value(run.get("cursorCount")),
        "warehouseW0Ready": bool(run.get("warehouseW0Ready")),
        "w1GateDecision": run.get("w1GateDecision", ""),
        "malformedRawJsonCount": _int_value(run.get("malformedRawJsonCount")),
        "duplicateIndicatorCount": _int_value(run.get("duplicateIndicatorCount")),
        "collectionMetadataStatus": run.get("collectionMetadataStatus", ""),
        "targetSlugs": _text_list(run.get("targetSlugs")),
        "rowsByTarget": _int_mapping(run.get("rowsByTarget")),
        "retentionRecommendation": run.get("retentionRecommendation", ""),
        "stalenessStatus": run.get("stalenessStatus", ""),
    }


def _select_run(
    runs: Sequence[Mapping[str, object]],
    *,
    run_id: str | None,
    label: str | None,
) -> Mapping[str, object] | None:
    if run_id:
        for run in runs:
            if str(run.get("runId") or "") == run_id:
                return run
    if label:
        for run in runs:
            if str(run.get("label") or "") == label:
                return run
    return None


def _query_result(
    *,
    query_mode: str,
    runs: Sequence[Mapping[str, object]],
    selected_run: Mapping[str, object] | None,
    report: Mapping[str, object],
) -> object:
    if query_mode == MODE_LIST_RUNS:
        return {"runs": _run_views(runs)}
    if query_mode == MODE_SUMMARIZE_RUN:
        return {"run": _run_view(selected_run or {})}
    if query_mode == MODE_AGGREGATE:
        return report.get("aggregate", {})
    if query_mode == MODE_TARGET_COVERAGE:
        return report.get("targetCoverage", {})
    if query_mode == MODE_HEALTH:
        return report.get("health", {})
    if query_mode == MODE_RETENTION_STATUS:
        return report.get("retentionStatus", {})
    if query_mode == MODE_BLOCKED_SCOPES:
        return {"blockedScopes": report.get("blockedScopes", [])}
    return {}


def _write_outputs(
    report: dict[str, object],
    *,
    output_json: str | Path | None,
    output_markdown: str | Path | None,
) -> dict[str, object]:
    _sync_summary(report)
    if output_json:
        write_query_output(report, output_json)
    if output_markdown:
        _write_markdown(report, output_markdown)
    return report


def _write_markdown(report: Mapping[str, object], output_path: str | Path) -> Path:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    aggregate = report.get("aggregate") if isinstance(report.get("aggregate"), Mapping) else {}
    target_coverage = report.get("targetCoverage") if isinstance(report.get("targetCoverage"), Mapping) else {}
    lines = [
        "# Indexer Warehouse Query Summary",
        "",
        f"- Query mode: `{report.get('queryMode', '')}`",
        f"- Gate: `{summary.get('gateDecision', '')}`",
        f"- Source registry: `{report.get('sourceRegistry', '')}`",
        f"- Runs: `{summary.get('runCount', 0)}`",
        f"- Active review candidates: `{summary.get('activeReviewCandidates', 0)}`",
        f"- Retained references: `{summary.get('retainedReferences', 0)}`",
        f"- Markets: `{aggregate.get('totalMarkets', 0)}`",
        f"- Trades: `{aggregate.get('totalTrades', 0)}`",
        f"- Cursors: `{aggregate.get('totalCursors', 0)}`",
        "",
        "## Warnings",
        "",
    ]
    for warning in _text_list(report.get("warnings")):
        lines.append(f"- `{warning}`")
    targets = target_coverage.get("targets") if isinstance(target_coverage, Mapping) else []
    if isinstance(targets, Sequence) and targets:
        lines.extend(["", "## Target Coverage", ""])
        for item in targets:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('targetSlug', '')}`: `{item.get('totalRows', 0)}` rows")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _sync_summary(report: dict[str, object]) -> None:
    summary = report["summary"]
    assert isinstance(summary, dict)
    aggregate = report.get("aggregate") if isinstance(report.get("aggregate"), Mapping) else {}
    target_coverage = report.get("targetCoverage") if isinstance(report.get("targetCoverage"), Mapping) else {}
    blocked_scopes = report.get("blockedScopes") if isinstance(report.get("blockedScopes"), Sequence) else []
    summary.update(
        {
            "runCount": _int_value(aggregate.get("runCount")),
            "activeReviewCandidates": _int_value(aggregate.get("activeReviewCandidates")),
            "retainedReferences": _int_value(aggregate.get("retainedReferences")),
            "cleanupCandidates": _int_value(aggregate.get("cleanupCandidates")),
            "blockedNotW0Ready": _int_value(aggregate.get("blockedNotW0Ready")),
            "totalMarkets": _int_value(aggregate.get("totalMarkets")),
            "totalTrades": _int_value(aggregate.get("totalTrades")),
            "totalCursors": _int_value(aggregate.get("totalCursors")),
            "malformedRawJsonCount": _int_value(aggregate.get("malformedRawJsonCount")),
            "duplicateIndicatorCount": _int_value(aggregate.get("duplicateIndicatorCount")),
            "targetCoverageCount": _int_value(target_coverage.get("coveredTargetCount")) if isinstance(target_coverage, Mapping) else 0,
            "blockedScopeCount": len([item for item in blocked_scopes if str(item)]),
        }
    )


def _set_gate(report: dict[str, object], gate: str, next_action: str) -> None:
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary["gateDecision"] = gate
    summary["nextAllowedAction"] = next_action


def _mapping_value(value: object, key: str) -> object:
    if isinstance(value, Mapping):
        return value.get(key, "")
    return ""


def _int_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        text_key = str(key)
        if text_key:
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


def _bump(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-json", required=True, help="W2 registry JSON to query.")
    parser.add_argument("--query-mode", choices=QUERY_MODES, required=True)
    parser.add_argument("--run-id", help="Run id for summarize-run mode.")
    parser.add_argument("--label", help="Run label for summarize-run mode.")
    parser.add_argument("--output-json", help="Optional compact query JSON output path.")
    parser.add_argument("--output-markdown", help="Optional Markdown query output path.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = run_warehouse_query(
        args.registry_json,
        query_mode=args.query_mode,
        run_id=args.run_id,
        label=args.label,
        output_json=args.output_json,
        output_markdown=args.output_markdown,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
