#!/usr/bin/env python3
"""Inventory Event Forensic pagination/truncation impact from local reports.

This sidecar reads local JSON reports and compact validation summaries only.
It does not fetch network data, mutate saved artifacts, or change runtime
pagination behavior.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "event_forensic_pagination_truncation_inventory"
SCHEMA_VERSION = "event_forensic_pagination_truncation_inventory_v1"
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_pagination_truncation_inventory_20260526.json")
DEFAULT_MAX_BYTES = 6_000_000
DEFAULT_MAX_FILES = 120
DEFAULT_PAGE_CAP_ROWS = 3100


def discover_report_paths(root: str | Path = ".", *, max_files: int = DEFAULT_MAX_FILES) -> list[Path]:
    base = Path(root)
    patterns = (
        ".inspoly_event_forensic_analyzer/reports/event_forensic_*.json",
        ".inspoly/reports/event_forensic_*.json",
        "event_forensic_outputs/event_forensic_*/event_analysis.json",
        "validation_outputs/event_forensic_*/*/event_forensic_outputs/*/event_analysis.json",
        "validation_outputs/event_forensic_*/*/reports/event_forensic_*.json",
        "validation_outputs/event_forensic_*/*/summary.json",
        "validation_outputs/event_forensic_*summary*.json",
        "tests/fixtures/**/event_analysis.json",
        "tests/fixtures/**/*event_forensic*.json",
    )
    paths: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(base.glob(pattern)):
            if not path.is_file() or path.suffix.lower() != ".json":
                continue
            if ".git" in path.parts or "__pycache__" in path.parts or "raw_event_bundle" in path.parts:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(path)
    return paths[:max_files]


def build_truncation_inventory(
    root: str | Path = ".",
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    page_cap_rows: int = DEFAULT_PAGE_CAP_ROWS,
) -> dict[str, object]:
    artifact_rows: list[dict[str, object]] = []
    market_rows: list[dict[str, object]] = []
    skipped_large: list[dict[str, object]] = []
    skipped_invalid = 0
    for path in discover_report_paths(root, max_files=max_files):
        try:
            size = path.stat().st_size
        except OSError:
            skipped_invalid += 1
            continue
        if size > max_bytes:
            skipped_large.append({"path": str(path), "sizeBytes": size})
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            skipped_invalid += 1
            continue
        if not isinstance(payload, Mapping):
            skipped_invalid += 1
            continue
        artifact = _artifact_row(path, payload, size, page_cap_rows=page_cap_rows)
        if artifact["artifactFamily"] == "event_forensic":
            artifact_rows.append(artifact)
            market_rows.extend(_market_rows(path, payload, artifact, page_cap_rows=page_cap_rows))
    summary = _summary(artifact_rows, market_rows, skipped_large, skipped_invalid)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "productionPaginationChanged": False,
        "root": str(Path(root)),
        "maxFiles": max_files,
        "maxBytes": max_bytes,
        "pageCapRows": page_cap_rows,
        "gateDecision": _inventory_gate(summary),
        "summary": summary,
        "artifactRows": artifact_rows[:120],
        "marketRows": market_rows[:240],
        "largestSkippedFiles": sorted(skipped_large, key=lambda item: int(item["sizeBytes"]), reverse=True)[:25],
        "limitations": [
            "Local report scan only; it cannot prove deeper pagination behavior.",
            "Per-market truncation is inferred when reports expose only aggregate truncation markers.",
            "High-review and sensitive overlap counts use saved top-slice report rows, not a full rerun.",
        ],
    }


def build_impact_assessment(
    *,
    inventory_payload: Mapping[str, object],
    collection_payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    inventory_summary = _as_mapping(inventory_payload.get("summary"))
    collection_summary = _as_mapping((collection_payload or {}).get("summary"))
    raw_delta = _int(collection_summary.get("rawRowsDelta"))
    candidate_delta = _int(collection_summary.get("candidateFloorRowsDelta"))
    collection_gate = str(collection_summary.get("gateDecision") or "")
    material = raw_delta > 0 or candidate_delta > 0
    bounds_hit = bool(collection_summary.get("boundsHit")) or collection_gate == "bounded_collection_blocked"
    if material:
        gate = "pagination_material_impact_found_needs_rfc"
    elif bounds_hit:
        gate = "pagination_blocked_by_bounds"
    elif collection_payload:
        gate = "pagination_low_impact_monitor_only"
    else:
        gate = "pagination_operator_plan_ready_no_live"
    return {
        "reportType": "event_forensic_pagination_impact_assessment",
        "schemaVersion": "event_forensic_pagination_impact_assessment_v1",
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": bool(collection_payload and collection_payload.get("networkUsed")),
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "productionPaginationChanged": False,
        "gateDecision": gate,
        "summary": {
            "gateDecision": gate,
            "inventoryReportsEvaluated": _int(inventory_summary.get("reportsEvaluated")),
            "inventoryTruncatedReports": _int(inventory_summary.get("truncatedReportCount")),
            "inventoryTruncatedMarkets": _int(inventory_summary.get("truncatedMarketRows")),
            "inventoryHighReviewRowsAffected": _int(inventory_summary.get("highReviewRowsAffectedByTruncation")),
            "inventoryWeakHistoryRowsAffected": _int(inventory_summary.get("weakHistoryDemotionRowsAffectedByTruncation")),
            "inventorySensitiveRowsAffected": _int(inventory_summary.get("sensitiveRowsAffectedByTruncation")),
            "collectionExecuted": bool(collection_payload),
            "collectionGate": collection_gate,
            "rawRowsDelta": raw_delta,
            "candidateFloorRowsDelta": candidate_delta,
            "baselineTruncatedMarkets": _int(collection_summary.get("baselineTruncatedMarkets")),
            "deeperStillTruncatedMarkets": _int(collection_summary.get("deeperStillTruncatedMarkets")),
            "collectionWallClockSeconds": collection_summary.get("wallClockSeconds", 0),
            "boundsHit": bounds_hit,
            "materialImpactObserved": material,
        },
        "inventorySummary": dict(inventory_summary),
        "collectionSummary": dict(collection_summary),
        "recommendation": _impact_recommendation(gate),
        "claimsNotSupported": [
            "whole_event_completeness",
            "production_pagination_migration_ready",
            "score_or_gate_tuning_decision",
            "rank_change_claim_without_sidecar_replay",
        ],
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _artifact_row(path: Path, payload: Mapping[str, object], size: int, *, page_cap_rows: int) -> dict[str, object]:
    summary = _as_mapping(payload.get("summary"))
    performance = _as_mapping(payload.get("performance"))
    live = _as_mapping(payload.get("liveResult"))
    report_summary = _as_mapping(payload.get("reportSummary"))
    effective_summary = summary or report_summary or _as_mapping(live.get("reportSummary"))
    effective_performance = performance
    event = _as_mapping(payload.get("event"))
    truncated = _first_int(
        effective_summary.get("truncated_market_count"),
        effective_summary.get("truncatedMarketCount"),
        effective_performance.get("truncated_market_count"),
        effective_performance.get("trade_collection_truncated_markets"),
        live.get("truncatedMarketCount"),
    )
    markets = _market_payloads(payload)
    warnings = _warning_rows(payload)
    scope = _scope(payload)
    return {
        "path": str(path),
        "sizeBytes": size,
        "artifactFamily": "event_forensic" if _looks_event_forensic(path, payload) else "unknown",
        "eventSlug": str(
            payload.get("eventSlug")
            or effective_summary.get("eventSlug")
            or event.get("slug")
            or live.get("eventSlug")
            or ""
        ),
        "scope": scope,
        "analysisMarketCount": _first_int(
            effective_summary.get("analysis_market_count"),
            effective_summary.get("analysisMarketCount"),
            effective_performance.get("trade_collection_market_total"),
            live.get("analysisMarketCount"),
            len(markets) if markets else None,
        ),
        "totalEventMarketCount": _first_int(
            effective_summary.get("total_event_market_count"),
            effective_summary.get("totalEventMarketCount"),
            event.get("marketCount"),
            live.get("liveResolvedMarketCount"),
        ),
        "rawTradeRows": _first_int(
            effective_summary.get("raw_trade_count"),
            effective_summary.get("rawTradeRows"),
            effective_performance.get("trade_collection_raw_trade_rows"),
            live.get("rawTradeCount"),
        ),
        "candidateRows": _first_int(
            effective_summary.get("candidate_trade_count"),
            effective_summary.get("candidateRows"),
            effective_summary.get("normal_candidate_trade_count"),
            live.get("candidateTradeCount"),
        ),
        "truncatedMarketCount": truncated,
        "truncationReported": bool(truncated and truncated > 0),
        "analystVisiblePaginationWarning": any("pagination cap" in warning.lower() for warning in warnings),
        "collectionRiskClass": str(effective_performance.get("trade_collection_risk_class") or ""),
        "marketRowsVisible": len(markets),
        "pageCapRows": page_cap_rows,
    }


def _market_rows(
    path: Path,
    payload: Mapping[str, object],
    artifact: Mapping[str, object],
    *,
    page_cap_rows: int,
) -> list[dict[str, object]]:
    markets = _market_payloads(payload)
    if not markets:
        return []
    row_counts = _display_row_counts_by_market(payload)
    truncated_count = _int(artifact.get("truncatedMarketCount"))
    inferred_all = truncated_count >= len(markets) and len(markets) > 0
    rows: list[dict[str, object]] = []
    for market in markets:
        condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
        market_slug = str(market.get("marketSlug") or market.get("slug") or "")
        trade_count = _first_int(market.get("tradeCount"), market.get("trade_count"))
        candidate_count = _first_int(market.get("candidateTradeCount"), market.get("candidate_trade_count"))
        stats = row_counts.get(condition_id) or row_counts.get(market_slug) or {}
        inferred_truncated = bool(
            inferred_all
            or (trade_count is not None and trade_count >= page_cap_rows)
            or (candidate_count is not None and candidate_count >= page_cap_rows)
        )
        rows.append(
            {
                "path": str(path),
                "eventSlug": artifact.get("eventSlug", ""),
                "scope": artifact.get("scope", ""),
                "conditionId": condition_id,
                "marketSlug": market_slug,
                "marketTitle": str(market.get("market") or market.get("question") or market.get("title") or ""),
                "tradeCount": trade_count,
                "candidateTradeCount": candidate_count,
                "truncationStatus": "truncated_or_aggregate_inferred" if inferred_truncated else "not_truncated_or_unknown",
                "candidateRowsFromTruncatedMarket": _int(stats.get("candidateRows")) if inferred_truncated else 0,
                "highReviewRowsAffected": _int(stats.get("highReviewRows")) if inferred_truncated else 0,
                "weakHistoryDemotionRowsAffected": _int(stats.get("weakHistoryRows")) if inferred_truncated else 0,
                "sensitiveRowsAffected": _int(stats.get("sensitiveRows")) if inferred_truncated else 0,
            }
        )
    return rows


def _display_row_counts_by_market(payload: Mapping[str, object]) -> dict[str, dict[str, int]]:
    result: dict[str, Counter[str]] = defaultdict(Counter)
    for row in _candidate_like_rows(payload):
        if not isinstance(row, Mapping):
            continue
        condition_id = str(row.get("conditionId") or row.get("condition_id") or "")
        market_slug = str(row.get("marketSlug") or row.get("slug") or "")
        keys = [key for key in (condition_id, market_slug) if key]
        for key in keys:
            result[key]["candidateRows"] += 1
            if _is_high_review_row(row):
                result[key]["highReviewRows"] += 1
            if _is_weak_history_demotion_row(row):
                result[key]["weakHistoryRows"] += 1
            if _is_sensitive_row(row):
                result[key]["sensitiveRows"] += 1
    return {key: dict(counter) for key, counter in result.items()}


def _summary(
    artifact_rows: Sequence[Mapping[str, object]],
    market_rows: Sequence[Mapping[str, object]],
    skipped_large: Sequence[Mapping[str, object]],
    skipped_invalid: int,
) -> dict[str, object]:
    scopes = Counter(str(row.get("scope") or "unknown") for row in artifact_rows)
    truncated_reports = [row for row in artifact_rows if row.get("truncationReported")]
    truncated_market_rows = [
        row for row in market_rows if row.get("truncationStatus") == "truncated_or_aggregate_inferred"
    ]
    return {
        "reportsEvaluated": len(artifact_rows),
        "marketsEvaluated": len(market_rows),
        "skippedLargeReportCount": len(skipped_large),
        "skippedInvalidReportCount": skipped_invalid,
        "scopeCounts": dict(sorted(scopes.items())),
        "truncatedReportCount": len(truncated_reports),
        "truncatedMarketRows": len(truncated_market_rows),
        "candidateRowsAffectedByTruncation": sum(_int(row.get("candidateRowsFromTruncatedMarket")) for row in truncated_market_rows),
        "highReviewRowsAffectedByTruncation": sum(_int(row.get("highReviewRowsAffected")) for row in truncated_market_rows),
        "weakHistoryDemotionRowsAffectedByTruncation": sum(
            _int(row.get("weakHistoryDemotionRowsAffected")) for row in truncated_market_rows
        ),
        "sensitiveRowsAffectedByTruncation": sum(_int(row.get("sensitiveRowsAffected")) for row in truncated_market_rows),
        "analystWarningReportCount": sum(1 for row in artifact_rows if row.get("analystVisiblePaginationWarning")),
        "rankingRiskReportCount": sum(1 for row in artifact_rows if row.get("truncationReported")),
    }


def _candidate_like_rows(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    for key in (
        "suspicious_trades",
        "review_required_trades",
        "display_trades",
        "display_review_required_trades",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, Mapping))
    return rows


def _market_payloads(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    rows = payload.get("markets")
    return [item for item in rows if isinstance(item, Mapping)] if isinstance(rows, list) else []


def _warning_rows(payload: Mapping[str, object]) -> list[str]:
    value = payload.get("evidence_warnings")
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _scope(payload: Mapping[str, object]) -> str:
    summary = _as_mapping(payload.get("summary"))
    settings = _as_mapping(payload.get("analysis_settings"))
    for value in (
        payload.get("analysisScope"),
        summary.get("analysisScope"),
        payload.get("analysis_scope"),
        settings.get("analysis_scope"),
    ):
        text = str(value or "").strip()
        if text:
            if text == "market":
                return "selected_market"
            if text == "event":
                return "event"
            return text
    if bool(payload.get("subsetOnly")):
        return "subset_only"
    return "unknown"


def _looks_event_forensic(path: Path, payload: Mapping[str, object]) -> bool:
    text = str(path).lower()
    return "event_forensic" in text or "analysis_scope" in payload or "analysisScope" in payload or "event" in payload


def _is_high_review_row(row: Mapping[str, object]) -> bool:
    score = _int(row.get("eventForensicScore") or row.get("event_forensic_score"))
    if score >= 70:
        return True
    if str(row.get("hardEvidenceReviewTier") or "").strip():
        return True
    if str(row.get("reviewBucketAfterPolicy") or "").lower() in {"primary", "high", "high_review"}:
        return True
    return False


def _is_weak_history_demotion_row(row: Mapping[str, object]) -> bool:
    if bool(row.get("weakHistoryNearCertaintyReviewDemotion")):
        return True
    text = " ".join(str(row.get(key) or "") for key in ("weakHistoryNearCertaintyReviewReason", "eventForensicReducers", "eventForensicNotes"))
    return "weak" in text.lower() and "near" in text.lower()


def _is_sensitive_row(row: Mapping[str, object]) -> bool:
    if str(row.get("strongRiskGatePassed") or "").lower() in {"true", "yes", "1"}:
        return True
    text = " ".join(
        str(row.get(key) or "")
        for key in (
            "hardEvidenceSources",
            "hardEvidenceReviewTier",
            "fundingEvidenceGrade",
            "suspiciousFundingQuality",
            "strongRiskGateReasons",
        )
    ).lower()
    return any(marker in text for marker in ("funding", "strong risk", "hard evidence", "her"))


def _inventory_gate(summary: Mapping[str, object]) -> str:
    if _int(summary.get("truncatedReportCount")) > 0:
        return "pagination_sidecar_inventory_ready_operator_plan_required"
    return "pagination_sidecar_inventory_ready_no_truncation_found"


def _impact_recommendation(gate: str) -> str:
    if gate == "pagination_material_impact_found_needs_rfc":
        return "Create an RFC before any production pagination expansion; deeper rows changed the bounded evidence surface."
    if gate == "pagination_blocked_by_bounds":
        return "Keep the operator plan; tighter or separately approved bounds are needed before drawing impact conclusions."
    if gate == "pagination_low_impact_monitor_only":
        return "Keep current production pagination and monitor; no material bounded delta was observed."
    return "Operator plan is ready; no live deeper collection evidence was attached to this assessment."


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _first_int(*values: object) -> int | None:
    for value in values:
        if value in (None, ""):
            continue
        parsed = _int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _int(value: object) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _load_json_object(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--collection-summary", default="")
    parser.add_argument("--impact-output", default="validation_outputs/event_forensic_pagination_impact_assessment_20260526.json")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    inventory = build_truncation_inventory(args.root, max_files=args.max_files, max_bytes=args.max_bytes)
    write_json(inventory, args.output)
    if args.collection_summary:
        collection = _load_json_object(args.collection_summary)
        assessment = build_impact_assessment(inventory_payload=inventory, collection_payload=collection)
        write_json(assessment, args.impact_output)
    if not args.quiet:
        print(f"gate: {inventory['gateDecision']}")
        print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
