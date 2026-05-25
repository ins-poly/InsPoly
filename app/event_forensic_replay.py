"""Read-only Event Forensic replay snapshot helpers.

The helpers in this module build stable sidecar payloads from already-collected
Event Forensic report data. They do not fetch data, run analysis, change scores,
or write to application storage.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPLAY_SNAPSHOT_REPORT_TYPE = "event_forensic_replay_snapshot"
REPLAY_SNAPSHOT_SCHEMA_VERSION = "event_forensic_replay_snapshot_v1"
DEFAULT_REPLAY_STAGES = ("initial", "+1h", "+4h", "+24h")
FORBIDDEN_SECRET_KEY_PARTS = (
    "secret",
    "private_key",
    "privatekey",
    "api_key",
    "apikey",
    "auth",
    "auth_token",
    "access_token",
    "refresh_token",
    "bearer_token",
    "password",
    "credential",
    "mnemonic",
)
TIMING_FIELDS = (
    "resolve_input_seconds",
    "collect_event_trades_seconds",
    "trade_collection_elapsed_seconds",
    "prefetch_wallet_context_seconds",
    "prepare_candidate_context_seconds",
    "prefetch_funding_context_seconds",
    "score_candidates_seconds",
    "collect_price_history_seconds",
    "related_market_scan_seconds",
    "assemble_report_rows_seconds",
    "total_seconds",
)


def build_replay_snapshot(
    report: Mapping[str, object],
    *,
    replay_stage: str = "initial",
    candidate_rows: Sequence[Mapping[str, object]] | None = None,
    generated_at: str | None = None,
) -> dict[str, object]:
    """Build a deterministic replay snapshot from saved report-like data."""

    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    event = report.get("event") if isinstance(report.get("event"), Mapping) else {}
    settings = report.get("analysis_settings") if isinstance(report.get("analysis_settings"), Mapping) else {}
    performance = report.get("performance") if isinstance(report.get("performance"), Mapping) else {}
    rows = _candidate_rows(report, candidate_rows)
    candidate_ids = [_candidate_id(row, index) for index, row in enumerate(rows)]
    snapshot = {
        "reportType": REPLAY_SNAPSHOT_REPORT_TYPE,
        "schemaVersion": REPLAY_SNAPSHOT_SCHEMA_VERSION,
        "generatedAt": generated_at or datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "replayStage": replay_stage,
        "event": {
            "eventSlug": _text(report.get("eventSlug") or event.get("slug") or report.get("parent_event_slug")),
            "eventId": _text(event.get("id")),
            "eventTitle": _text(event.get("title")),
            "canonicalUrl": _text(event.get("canonicalUrl")),
            "resolutionStatus": _resolution_status(report, event),
            "outcomeContextAvailable": _boolish(
                event.get("outcomeContextAvailable")
                if "outcomeContextAvailable" in event
                else summary.get("outcome_context_available")
            ),
        },
        "market": {
            "selectedConditionId": _text(report.get("selectedConditionId") or report.get("selected_condition_id") or settings.get("selected_condition_id")),
            "selectedMarketSlug": _text(report.get("selectedMarketSlug") or report.get("selected_market_slug") or settings.get("selected_market_slug")),
            "selectedMarketQuestion": _text(report.get("selectedMarketQuestion") or report.get("selected_market_title")),
            "analysisMarketCount": _int_or_none(summary.get("analysis_market_count") or event.get("analysisMarketCount")),
            "totalEventMarketCount": _int_or_none(summary.get("total_event_market_count") or event.get("marketCount")),
        },
        "scope": {
            "analysisScope": _analysis_scope(report),
            "legacyAnalysisScope": _text(report.get("analysis_scope") or settings.get("analysis_scope")),
            "primaryScoringScope": _text(report.get("primaryScoringScope") or summary.get("primaryScoringScope") or settings.get("primary_scoring_scope")),
            "relatedMarketsContextIncluded": _boolish(report.get("relatedMarketsContextIncluded") or summary.get("relatedMarketsContextIncluded") or settings.get("related_markets_context_included")),
            "siblingMarketsPrimaryScored": _boolish(report.get("siblingMarketsPrimaryScored") or summary.get("siblingMarketsPrimaryScored") or settings.get("sibling_markets_primary_scored")),
        },
        "sourceReport": {
            "generatedAt": _text(report.get("generated_at") or report.get("generatedAt")),
            "analysisVersion": _text(report.get("analysis_version")),
            "status": _text(report.get("status")),
            "reportJsonPath": _text(report.get("report_json_path")),
        },
        "candidateCounts": {
            "rawTradeCount": _int_or_none(summary.get("raw_trade_count")),
            "candidateTradeCount": _int_or_none(summary.get("candidate_trade_count")),
            "normalCandidateTradeCount": _int_or_none(summary.get("normal_candidate_trade_count")),
            "candidateRowsInSnapshot": len(rows),
            "candidateTradeSetIds": candidate_ids,
        },
        "candidates": [_candidate_snapshot(row, candidate_ids[index]) for index, row in enumerate(rows)],
        "winnerResolutionMetadata": _winner_resolution_metadata(report),
        "scoreInputs": {
            "minNotional": _text(settings.get("min_notional")),
            "includeRelatedMarkets": _boolish(settings.get("include_related_markets")),
            "includeBlockchain": _boolish(settings.get("include_blockchain")),
            "fundingTraceMode": _text(settings.get("funding_trace_mode") or report.get("fundingTraceMode")),
            "startAt": _text(settings.get("start_at")),
            "endAt": _text(settings.get("end_at")),
        },
        "timing": {field: performance.get(field) for field in TIMING_FIELDS if performance.get(field) not in (None, "")},
        "versionMetadata": {
            "snapshotSchemaVersion": REPLAY_SNAPSHOT_SCHEMA_VERSION,
            "analysisVersion": _text(report.get("analysis_version")),
            "supportedReplayStages": list(DEFAULT_REPLAY_STAGES),
        },
        "qualityNotes": _quality_notes(report, rows),
    }
    forbidden_paths = find_forbidden_snapshot_key_paths(snapshot)
    snapshot["containsRestrictedFields"] = bool(forbidden_paths)
    snapshot["restrictedFieldPaths"] = forbidden_paths
    return snapshot


def write_replay_snapshot(snapshot: Mapping[str, object], output_path: str | Path) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def find_forbidden_snapshot_key_paths(payload: object, *, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            normalized = key_text.replace("-", "_").lower()
            if any(part in normalized for part in FORBIDDEN_SECRET_KEY_PARTS):
                paths.append(path)
            paths.extend(find_forbidden_snapshot_key_paths(value, prefix=path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            paths.extend(find_forbidden_snapshot_key_paths(value, prefix=f"{prefix}[{index}]"))
    return paths


def _candidate_rows(
    report: Mapping[str, object],
    explicit_rows: Sequence[Mapping[str, object]] | None,
) -> list[Mapping[str, object]]:
    if explicit_rows is not None:
        return [row for row in explicit_rows if isinstance(row, Mapping)]
    candidates: list[Mapping[str, object]] = []
    for key in ("display_trades", "suspicious_trades", "review_required_trades", "display_review_required_trades"):
        rows = report.get(key)
        if isinstance(rows, list):
            candidates.extend(row for row in rows if isinstance(row, Mapping))
    seen: set[str] = set()
    deduped: list[Mapping[str, object]] = []
    for index, row in enumerate(candidates):
        candidate_id = _candidate_id(row, index)
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        deduped.append(row)
    return deduped


def _candidate_snapshot(row: Mapping[str, object], candidate_id: str) -> dict[str, object]:
    return {
        "candidateId": candidate_id,
        "tradeId": _text(row.get("tradeId") or row.get("trade_id")),
        "tradeKey": _text(row.get("tradeKey") or row.get("candidateTradeKey")),
        "wallet": _text(row.get("wallet")),
        "conditionId": _text(row.get("conditionId") or row.get("condition_id")),
        "timestamp": _text(row.get("timestamp")),
        "market": _text(row.get("market")),
        "rawOrderSide": _text(row.get("rawOrderSide") or row.get("orderSide") or row.get("side")),
        "rawTokenOutcome": _text(row.get("rawTokenOutcome") or row.get("outcome")),
        "economicSide": _text(row.get("economicSide")),
        "eventForensicScore": row.get("eventForensicScore"),
        "existingModelScore": row.get("existingModelScore"),
        "reviewBucket": _text(row.get("reviewBucketAfterPolicy") or row.get("finalDisplayTier")),
        "laterWon": row.get("laterWon"),
        "winnerRank": row.get("winnerRank"),
    }


def _candidate_id(row: Mapping[str, object], index: int) -> str:
    for key in ("tradeId", "trade_id", "id", "candidateId"):
        value = _text(row.get(key))
        if value:
            return value
    parts = [
        _text(row.get("wallet")),
        _text(row.get("conditionId") or row.get("condition_id")),
        _text(row.get("timestamp")),
        _text(row.get("rawOrderSide") or row.get("orderSide") or row.get("side")),
        _text(row.get("rawTokenOutcome") or row.get("outcome")),
    ]
    key = "|".join(part for part in parts if part)
    return key or f"candidate-{index + 1}"


def _winner_resolution_metadata(report: Mapping[str, object]) -> dict[str, object]:
    markets = report.get("markets") if isinstance(report.get("markets"), list) else []
    rows = []
    for market in markets:
        if not isinstance(market, Mapping):
            continue
        rows.append(
            {
                "conditionId": _text(market.get("conditionId") or market.get("condition_id")),
                "market": _text(market.get("question") or market.get("market") or market.get("title")),
                "winningOutcome": _text(market.get("winningOutcome") or market.get("winning_outcome")),
                "resolutionStatus": _text(market.get("resolutionStatus") or market.get("status")),
            }
        )
    return {
        "markets": rows,
        "winnerMetadataAvailable": any(row.get("winningOutcome") for row in rows),
    }


def _quality_notes(report: Mapping[str, object], rows: Sequence[Mapping[str, object]]) -> list[str]:
    notes = []
    if not rows:
        notes.append("no_candidate_rows_available_in_source_report")
    if not _text(report.get("analysisScope")):
        notes.append("product_scope_missing_or_inferred_from_legacy_fields")
    performance = report.get("performance") if isinstance(report.get("performance"), Mapping) else {}
    if not any(performance.get(field) not in (None, "") for field in TIMING_FIELDS):
        notes.append("timing_fields_missing")
    return notes or ["complete_snapshot_fields_available"]


def _resolution_status(report: Mapping[str, object], event: Mapping[str, object]) -> str:
    value = event.get("resolutionStatus")
    if value not in (None, ""):
        return _text(value)
    eligibility = report.get("eligibility")
    if isinstance(eligibility, Mapping):
        return _text(eligibility.get("status"))
    return ""


def _analysis_scope(report: Mapping[str, object]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    settings = report.get("analysis_settings") if isinstance(report.get("analysis_settings"), Mapping) else {}
    product = _text(report.get("analysisScope") or summary.get("analysisScope"))
    if product:
        return product
    legacy = _text(report.get("analysis_scope") or settings.get("analysis_scope"))
    if legacy == "market":
        return "selected_market"
    if legacy == "event":
        return "whole_event"
    return "unknown"


def _text(value: object) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None
