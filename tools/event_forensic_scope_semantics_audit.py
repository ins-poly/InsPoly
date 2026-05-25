#!/usr/bin/env python3
"""Audit local Event Forensic reports for explicit scope semantics metadata."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "event_forensic_scope_semantics_audit"
SCHEMA_VERSION = "event_forensic_scope_semantics_audit_v1"
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_scope_semantics_audit_20260525.json")
MAX_DEFAULT_BYTES = 6_000_000
MAX_DEFAULT_FILES = 180
REQUIRED_SUMMARY_FIELDS = (
    "analysisScope",
    "primaryScoringScope",
    "selectedMarketSlug",
    "selectedMarketQuestion",
    "eventSlug",
    "relatedMarketsContextIncluded",
    "siblingMarketsPrimaryScored",
    "scopeExplanation",
)


def build_scope_semantics_audit(
    root: str | Path = ".",
    *,
    max_files: int | None = MAX_DEFAULT_FILES,
    max_bytes: int | None = MAX_DEFAULT_BYTES,
) -> dict[str, object]:
    base = Path(root)
    artifacts = _discover_reports(base)
    if max_files is not None:
        artifacts = artifacts[:max_files]
    rows = [_evaluate_report(base, path, max_bytes=max_bytes) for path in artifacts]
    summary = _summarize(rows)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "root": str(base.resolve()),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "gateDecision": _gate(summary),
        "summary": summary,
        "reports": rows,
        "requiredSummaryFields": list(REQUIRED_SUMMARY_FIELDS),
        "limitations": [
            "This audit reads local report artifacts only.",
            "Old reports may lack explicit product-scope fields; fallback classification is absent-safe.",
            "The audit does not rescore, mutate saved reports, or broaden selected-market primary scope.",
        ],
    }


def build_audit(root: str | Path = ".") -> dict[str, object]:
    payload = build_scope_semantics_audit(root, max_files=None, max_bytes=MAX_DEFAULT_BYTES)
    reports = [row for row in payload["reports"] if isinstance(row, Mapping)]
    summary = dict(payload["summary"])
    summary["singleMarketWithSiblingContextCount"] = sum(
        1
        for row in reports
        if row.get("primaryScoringScope") == "selected_market"
        and int(row.get("totalEventMarketCount") or 0) > int(row.get("analysisMarketCount") or 0)
    )
    summary["modelBehaviorChanged"] = False
    payload["summary"] = summary
    payload["recommendations"] = [
        "Keep single-market condition_id scope strict.",
        "Use additive report copy/metadata before considering any scope behavior changes.",
    ]
    return payload


def write_json(path: str | Path, payload: Mapping[str, object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-files", type=int, default=MAX_DEFAULT_FILES)
    parser.add_argument("--max-bytes", type=int, default=MAX_DEFAULT_BYTES)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_scope_semantics_audit(args.root, max_files=args.max_files, max_bytes=args.max_bytes)
    write_json(args.output, report)
    if not args.quiet:
        print(f"gate: {report['gateDecision']}")
        print(f"output: {args.output}")
    return 0


def _discover_reports(base: Path) -> list[Path]:
    patterns = (
        "tests/fixtures/event_level_semantics/*.json",
        ".inspoly/reports/event_forensic_*.json",
        "event_forensic_outputs/**/event_analysis.json",
        "event_forensic_*/event_analysis.json",
    )
    paths: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(base.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def _evaluate_report(base: Path, path: Path, *, max_bytes: int | None) -> dict[str, object]:
    relative = _relative(base, path)
    source_type = "synthetic_fixture" if "tests/fixtures" in relative else "real_local_saved_report"
    size = path.stat().st_size
    if max_bytes is not None and size > max_bytes:
        return {
            "path": relative,
            "sourceType": source_type,
            "loadStatus": "skipped_too_large",
            "sizeBytes": size,
            "analysisScope": "unknown",
            "primaryScoringScope": "unknown",
            "explicitSummaryScopeFieldsPresent": False,
            "missingSummaryScopeFields": list(REQUIRED_SUMMARY_FIELDS),
            "relatedMarketReferenceCount": 0,
            "siblingContextTradeCount": 0,
            "selectedMarketRowsOnly": False,
            "scopeCopyClear": False,
            "possibleScopeAmbiguity": True,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, Mapping):
        payload = {}
    return _evaluate_payload(relative, source_type=source_type, size=size, payload=payload)


def _evaluate_payload(
    relative: str,
    *,
    source_type: str,
    size: int,
    payload: Mapping[str, object],
) -> dict[str, object]:
    summary = _mapping(payload.get("summary"))
    settings = _mapping(payload.get("analysis_settings"))
    event = _mapping(payload.get("event"))
    analysis_scope = _product_scope(payload, summary, settings)
    primary_scope = _primary_scope(payload, summary, settings, analysis_scope)
    selected_condition = str(
        payload.get("selected_condition_id")
        or payload.get("selectedConditionId")
        or settings.get("selected_condition_id")
        or ""
    )
    selected_slug = str(
        payload.get("selected_market_slug")
        or payload.get("selectedMarketSlug")
        or summary.get("selectedMarketSlug")
        or settings.get("selected_market_slug")
        or ""
    )
    related = payload.get("related_markets")
    markets = payload.get("markets")
    rows = _report_rows(payload)
    non_selected_rows = [
        row
        for row in rows
        if selected_condition
        and str(row.get("conditionId") or row.get("condition_id") or "") not in {"", selected_condition}
    ]
    missing_summary_fields = [field for field in REQUIRED_SUMMARY_FIELDS if field not in summary]
    scope_text = " ".join(
        str(value or "")
        for value in (
            payload.get("scopeExplanation"),
            summary.get("scopeExplanation"),
            payload.get("scope_note"),
            payload.get("event_report_markdown"),
            payload.get("model_gap_markdown"),
        )
    ).lower()
    scope_copy_clear = (
        (
            "selected-market" in scope_text
            or "selected market" in scope_text
            or "whole-event" in scope_text
            or "whole event" in scope_text
        )
        and ("primary" in scope_text or "context" in scope_text)
    )
    related_count = len(related) if isinstance(related, list) else 0
    market_count = len(markets) if isinstance(markets, list) else int(summary.get("analysis_market_count") or 0)
    total_event_market_count = int(summary.get("total_event_market_count") or event.get("marketCount") or market_count)
    selected_market_scope = analysis_scope == "selected_market"
    selected_rows_only = not selected_market_scope or not non_selected_rows
    ambiguous = bool(
        selected_market_scope
        and (related_count or non_selected_rows)
        and (missing_summary_fields or not scope_copy_clear)
    )
    return {
        "path": relative,
        "sourceType": source_type,
        "loadStatus": "loaded",
        "sizeBytes": size,
        "analysisScope": analysis_scope,
        "primaryScoringScope": primary_scope,
        "selectedConditionIdPresent": bool(selected_condition),
        "selectedMarketSlug": selected_slug,
        "explicitSummaryScopeFieldsPresent": not missing_summary_fields,
        "missingSummaryScopeFields": missing_summary_fields,
        "relatedMarketReferenceCount": related_count,
        "analysisMarketCount": market_count,
        "totalEventMarketCount": total_event_market_count,
        "siblingContextTradeCount": len(non_selected_rows),
        "rowCount": len(rows),
        "selectedMarketRowsOnly": selected_rows_only,
        "scopeCopyClear": scope_copy_clear,
        "possibleScopeAmbiguity": ambiguous,
        "relatedMarketsContextIncluded": bool(
            payload.get("relatedMarketsContextIncluded", summary.get("relatedMarketsContextIncluded", related_count > 0))
        ),
        "siblingMarketsPrimaryScored": bool(
            payload.get("siblingMarketsPrimaryScored", summary.get("siblingMarketsPrimaryScored", False))
        ),
    }


def _summarize(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    statuses = Counter(str(row.get("loadStatus") or "unknown") for row in rows)
    scopes = Counter(str(row.get("primaryScoringScope") or "unknown") for row in rows)
    source_types = Counter(str(row.get("sourceType") or "unknown") for row in rows)
    return {
        "artifactCount": len(rows),
        "loadedReportCount": statuses.get("loaded", 0),
        "skippedTooLargeCount": statuses.get("skipped_too_large", 0),
        "sourceTypeCounts": dict(sorted(source_types.items())),
        "primaryScopeCounts": dict(sorted(scopes.items())),
        "explicitSummaryScopeFieldReportCount": sum(1 for row in rows if row.get("explicitSummaryScopeFieldsPresent")),
        "missingSummaryScopeFieldReportCount": sum(1 for row in rows if row.get("missingSummaryScopeFields")),
        "selectedMarketReportCount": scopes.get("selected_market", 0),
        "wholeEventReportCount": scopes.get("whole_event", 0),
        "reportsWithRelatedMarketReferences": sum(1 for row in rows if int(row.get("relatedMarketReferenceCount") or 0) > 0),
        "reportsWithSiblingContextRows": sum(1 for row in rows if int(row.get("siblingContextTradeCount") or 0) > 0),
        "selectedMarketReportsWithOnlySelectedRows": sum(
            1
            for row in rows
            if row.get("primaryScoringScope") == "selected_market" and row.get("selectedMarketRowsOnly")
        ),
        "possibleScopeAmbiguityCount": sum(1 for row in rows if row.get("possibleScopeAmbiguity")),
        "runtimeScopeChanged": False,
    }


def _gate(summary: Mapping[str, object]) -> str:
    if int(summary.get("possibleScopeAmbiguityCount") or 0) > 0:
        return "scope_semantics_needs_new_report_metadata"
    return "scope_semantics_contract_explicit"


def _report_rows(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    display = payload.get("display_trades")
    suspicious = payload.get("suspicious_trades")
    rows = display if isinstance(display, list) else suspicious if isinstance(suspicious, list) else []
    return [row for row in rows if isinstance(row, Mapping)]


def _product_scope(
    payload: Mapping[str, object],
    summary: Mapping[str, object],
    settings: Mapping[str, object],
) -> str:
    explicit = str(payload.get("analysisScope") or summary.get("analysisScope") or "").strip()
    if explicit in {"selected_market", "whole_event"}:
        return explicit
    legacy = str(
        payload.get("analysis_scope")
        or settings.get("analysis_scope")
        or explicit
        or "unknown"
    ).strip().lower()
    if legacy == "market":
        return "selected_market"
    if legacy == "event":
        return "whole_event"
    if payload.get("selected_condition_id") or payload.get("selectedConditionId") or settings.get("selected_condition_id"):
        return "selected_market"
    return "unknown"


def _primary_scope(
    payload: Mapping[str, object],
    summary: Mapping[str, object],
    settings: Mapping[str, object],
    fallback: str,
) -> str:
    explicit = str(
        payload.get("primaryScoringScope")
        or summary.get("primaryScoringScope")
        or settings.get("primary_scoring_scope")
        or ""
    ).strip()
    return explicit if explicit else fallback


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _relative(base: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
