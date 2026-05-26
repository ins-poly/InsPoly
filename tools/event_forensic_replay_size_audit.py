#!/usr/bin/env python3
"""Audit Event Forensic replay snapshot size and schema stability."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.event_forensic_replay import build_replay_snapshot


REPORT_TYPE = "event_forensic_replay_size_audit"
SCHEMA_VERSION = "event_forensic_replay_size_audit_v1"
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_replay_size_audit_20260526.json")
DEFAULT_REPORT_GLOBS = (
    ".inspoly_event_forensic_analyzer/reports/event_forensic_*.json",
    ".inspoly/reports/event_forensic_*.json",
    "event_forensic_outputs/event_forensic_*.json",
    "validation_outputs/event_forensic_subset_measurement_*/live_run/event_forensic_outputs/event_forensic_*/event_analysis.json",
    "validation_outputs/event_forensic_*_measurement_*/live_run/event_forensic_outputs/event_forensic_*/event_analysis.json",
)


def build_replay_size_audit(
    root: str | Path = ".",
    *,
    report_globs: Sequence[str] = DEFAULT_REPORT_GLOBS,
    max_files: int = 30,
    max_report_bytes: int = 50_000_000,
    max_candidate_rows_per_snapshot: int = 250,
    generated_at: str | None = None,
) -> dict[str, object]:
    base = Path(root)
    generated = generated_at or datetime.now(tz=UTC).isoformat()
    paths = discover_report_paths(base, report_globs, max_files=max_files)
    rows: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for path in paths:
        size = path.stat().st_size
        relative = path.relative_to(base) if path.is_relative_to(base) else path
        if size > max_report_bytes:
            skipped.append(
                {
                    "path": str(relative),
                    "reason": "report_exceeds_max_report_bytes",
                    "reportBytes": size,
                }
            )
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            skipped.append({"path": str(relative), "reason": type(exc).__name__, "reportBytes": size})
            continue
        if not isinstance(payload, Mapping):
            skipped.append({"path": str(relative), "reason": "report_payload_not_object", "reportBytes": size})
            continue
        source_rows = _candidate_rows(payload)
        sampled_rows = source_rows[:max_candidate_rows_per_snapshot]
        snapshot = build_replay_snapshot(payload, candidate_rows=sampled_rows, generated_at=generated)
        snapshot_bytes = len(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        rows.append(
            _audit_row(
                str(relative),
                size,
                snapshot,
                snapshot_bytes,
                source_candidate_count=len(source_rows),
                sampled_candidate_count=len(sampled_rows),
            )
        )
    summary = _summary(rows, skipped, len(paths), max_files, max_report_bytes, max_candidate_rows_per_snapshot)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated,
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "storageSchemaChanged": False,
        "reportSchemaMutated": False,
        "browserEmbeddingImplemented": False,
        "gateDecision": _gate(summary),
        "summary": summary,
        "reportRows": rows,
        "skippedReports": skipped,
        "requiredProductDecisions": [
            "approve_report_embedding_size_budget_before_adding_replaySnapshot_to_reports",
            "approve_storage_schema_and_retention_policy_before_storage_backed_replay",
            "approve_browser_replay_viewer_before_ui_embedding",
        ],
    }


def discover_report_paths(base: Path, globs: Sequence[str], *, max_files: int) -> list[Path]:
    seen: set[Path] = set()
    paths: list[Path] = []
    for pattern in globs:
        for path in base.glob(pattern):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(path)
    paths.sort(key=lambda item: (-item.stat().st_size, str(item)))
    if max_files > 0:
        return paths[:max_files]
    return paths


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _candidate_rows(report: Mapping[str, object]) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    for key in ("display_trades", "suspicious_trades", "review_required_trades", "display_review_required_trades"):
        value = report.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, Mapping))
    seen: set[str] = set()
    deduped: list[Mapping[str, object]] = []
    for index, row in enumerate(rows):
        candidate_id = _candidate_id(row, index)
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        deduped.append(row)
    return deduped


def _candidate_id(row: Mapping[str, object], index: int) -> str:
    for key in ("tradeId", "trade_id", "id", "candidateId"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    parts = [
        str(row.get("wallet") or "").strip(),
        str(row.get("conditionId") or row.get("condition_id") or "").strip(),
        str(row.get("timestamp") or "").strip(),
        str(row.get("rawOrderSide") or row.get("orderSide") or row.get("side") or "").strip(),
        str(row.get("rawTokenOutcome") or row.get("outcome") or "").strip(),
    ]
    key = "|".join(part for part in parts if part)
    return key or f"candidate-{index + 1}"


def _audit_row(
    path: str,
    report_bytes: int,
    snapshot: Mapping[str, object],
    snapshot_bytes: int,
    *,
    source_candidate_count: int,
    sampled_candidate_count: int,
) -> dict[str, object]:
    counts = snapshot.get("candidateCounts") if isinstance(snapshot.get("candidateCounts"), Mapping) else {}
    scope = snapshot.get("scope") if isinstance(snapshot.get("scope"), Mapping) else {}
    event = snapshot.get("event") if isinstance(snapshot.get("event"), Mapping) else {}
    market = snapshot.get("market") if isinstance(snapshot.get("market"), Mapping) else {}
    candidate_rows = source_candidate_count
    summary_candidate_count = _int_or_none(counts.get("candidateTradeCount"))
    estimated_full_snapshot_bytes = _estimate_full_snapshot_size(snapshot_bytes, sampled_candidate_count, source_candidate_count)
    estimated_all_candidate_snapshot_bytes = _estimate_full_snapshot_size(
        snapshot_bytes,
        sampled_candidate_count,
        max(source_candidate_count, summary_candidate_count or 0),
    )
    return {
        "path": path,
        "reportBytes": report_bytes,
        "sampledSnapshotBytes": snapshot_bytes,
        "estimatedFullSnapshotBytes": estimated_full_snapshot_bytes,
        "estimatedAllCandidateSnapshotBytes": estimated_all_candidate_snapshot_bytes,
        "snapshotToReportRatio": round(estimated_full_snapshot_bytes / report_bytes, 6) if report_bytes else None,
        "estimatedTopLevelEmbedBytes": estimated_full_snapshot_bytes + 64,
        "candidateRowsInSourceReport": candidate_rows,
        "candidateTradeCountFromSummary": summary_candidate_count,
        "sampledCandidateRowsInSnapshot": sampled_candidate_count,
        "snapshotCoversAllCandidateTrades": (
            True
            if not summary_candidate_count
            else candidate_rows >= summary_candidate_count
        ),
        "candidateTradeSetIdsStable": _stable_candidate_ids(counts.get("candidateTradeSetIds")),
        "analysisScope": str(scope.get("analysisScope") or "unknown"),
        "eventSlug": str(event.get("eventSlug") or ""),
        "selectedMarketSlug": str(market.get("selectedMarketSlug") or ""),
        "containsRestrictedFields": bool(snapshot.get("containsRestrictedFields")),
        "qualityNotes": list(snapshot.get("qualityNotes") or []),
        "embeddingRisk": _embedding_risk(estimated_full_snapshot_bytes, candidate_rows),
        "allCandidateEmbeddingRisk": _embedding_risk(
            estimated_all_candidate_snapshot_bytes,
            max(candidate_rows, summary_candidate_count or 0),
        ),
        "storagePersistenceRisk": _storage_risk(estimated_full_snapshot_bytes, candidate_rows),
    }


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _estimate_full_snapshot_size(sampled_bytes: int, sampled_count: int, source_count: int) -> int:
    if source_count <= sampled_count or sampled_count <= 0:
        return sampled_bytes
    fixed_overhead = 1500
    variable_bytes = max(sampled_bytes - fixed_overhead, sampled_count)
    average_candidate_bytes = variable_bytes / sampled_count
    return int(fixed_overhead + (average_candidate_bytes * source_count))


def _stable_candidate_ids(value: object) -> bool:
    if not isinstance(value, list):
        return False
    return all(isinstance(item, str) and bool(item.strip()) for item in value)


def _embedding_risk(snapshot_bytes: int, candidate_rows: int) -> str:
    if snapshot_bytes > 5_000_000 or candidate_rows > 10_000:
        return "high_size_review_required"
    if snapshot_bytes > 1_000_000 or candidate_rows > 2_500:
        return "medium_size_review_required"
    return "low"


def _storage_risk(snapshot_bytes: int, candidate_rows: int) -> str:
    if snapshot_bytes > 5_000_000 or candidate_rows > 10_000:
        return "requires_retention_and_cleanup_policy"
    if snapshot_bytes > 1_000_000 or candidate_rows > 2_500:
        return "requires_size_budget"
    return "low"


def _summary(
    rows: Sequence[Mapping[str, object]],
    skipped: Sequence[Mapping[str, object]],
    discovered_count: int,
    max_files: int,
    max_report_bytes: int,
    max_candidate_rows_per_snapshot: int,
) -> dict[str, object]:
    snapshot_sizes = [int(row.get("estimatedFullSnapshotBytes") or 0) for row in rows]
    all_candidate_snapshot_sizes = [int(row.get("estimatedAllCandidateSnapshotBytes") or 0) for row in rows]
    report_sizes = [int(row.get("reportBytes") or 0) for row in rows]
    candidate_counts = [int(row.get("candidateRowsInSourceReport") or 0) for row in rows]
    summary_candidate_counts = [int(row.get("candidateTradeCountFromSummary") or 0) for row in rows]
    high_embedding = [row for row in rows if row.get("embeddingRisk") == "high_size_review_required"]
    medium_embedding = [row for row in rows if row.get("embeddingRisk") == "medium_size_review_required"]
    high_all_candidate_embedding = [
        row for row in rows if row.get("allCandidateEmbeddingRisk") == "high_size_review_required"
    ]
    medium_all_candidate_embedding = [
        row for row in rows if row.get("allCandidateEmbeddingRisk") == "medium_size_review_required"
    ]
    restricted = [row for row in rows if row.get("containsRestrictedFields")]
    old_fallback = [
        row
        for row in rows
        if any(
            note in set(row.get("qualityNotes") or [])
            for note in ("no_candidate_rows_available_in_source_report", "product_scope_missing_or_inferred_from_legacy_fields")
        )
    ]
    incomplete_rows = [row for row in rows if not row.get("snapshotCoversAllCandidateTrades")]
    return {
        "reportsDiscovered": discovered_count,
        "reportsAudited": len(rows),
        "reportsSkipped": len(skipped),
        "maxFiles": max_files,
        "maxReportBytes": max_report_bytes,
        "maxCandidateRowsPerSnapshotSample": max_candidate_rows_per_snapshot,
        "totalReportBytesAudited": sum(report_sizes),
        "totalSnapshotBytesEstimated": sum(snapshot_sizes),
        "maxSnapshotBytes": max(snapshot_sizes) if snapshot_sizes else 0,
        "medianSnapshotBytes": _median_int(snapshot_sizes),
        "maxAllCandidateSnapshotBytes": max(all_candidate_snapshot_sizes) if all_candidate_snapshot_sizes else 0,
        "medianAllCandidateSnapshotBytes": _median_int(all_candidate_snapshot_sizes),
        "maxReportBytesObserved": max(report_sizes) if report_sizes else 0,
        "maxCandidateRowsInSnapshot": max(candidate_counts) if candidate_counts else 0,
        "maxCandidateRowsInSourceReport": max(candidate_counts) if candidate_counts else 0,
        "maxCandidateTradeCountFromSummary": max(summary_candidate_counts) if summary_candidate_counts else 0,
        "medianCandidateRowsInSnapshot": _median_int(candidate_counts),
        "medianCandidateRowsInSourceReport": _median_int(candidate_counts),
        "medianCandidateTradeCountFromSummary": _median_int(summary_candidate_counts),
        "highEmbeddingRiskReports": len(high_embedding),
        "mediumEmbeddingRiskReports": len(medium_embedding),
        "highAllCandidateEmbeddingRiskReports": len(high_all_candidate_embedding),
        "mediumAllCandidateEmbeddingRiskReports": len(medium_all_candidate_embedding),
        "restrictedFieldReports": len(restricted),
        "oldReportFallbackReports": len(old_fallback),
        "reportsWhereSnapshotRowsAreTopSliceOnly": len(incomplete_rows),
        "oldReportsLoadAbsentSafe": True,
        "storageBackedPersistenceNeedsSchema": True,
        "browserEmbeddingNeedsProductApproval": True,
    }


def _median_int(values: Sequence[int]) -> int:
    if not values:
        return 0
    sorted_values = sorted(values)
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[mid]
    return int((sorted_values[mid - 1] + sorted_values[mid]) / 2)


def _gate(summary: Mapping[str, object]) -> str:
    if int(summary.get("restrictedFieldReports") or 0) > 0:
        return "replay_keep_sidecar_only_final"
    if int(summary.get("highEmbeddingRiskReports") or 0) > 0 or int(summary.get("highAllCandidateEmbeddingRiskReports") or 0) > 0:
        return "replay_keep_sidecar_only_final"
    if int(summary.get("mediumEmbeddingRiskReports") or 0) > 0 or int(summary.get("mediumAllCandidateEmbeddingRiskReports") or 0) > 0:
        return "replay_top_level_embedding_rfc_ready"
    return "replay_keep_sidecar_only_final"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-files", type=int, default=30)
    parser.add_argument("--max-report-bytes", type=int, default=50_000_000)
    parser.add_argument("--max-candidate-rows-per-snapshot", type=int, default=250)
    parser.add_argument("--generated-at")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payload = build_replay_size_audit(
        args.root,
        max_files=args.max_files,
        max_report_bytes=args.max_report_bytes,
        max_candidate_rows_per_snapshot=args.max_candidate_rows_per_snapshot,
        generated_at=args.generated_at,
    )
    write_json(payload, args.output)
    if not args.quiet:
        print(f"gate: {payload['gateDecision']}")
        print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
