#!/usr/bin/env python3
"""Audit local Event Forensic reports for selected-market vs whole-event scope."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "event_level_semantics_evidence_audit"
SCHEMA_VERSION = "event_level_semantics_evidence_audit_v1"
DEFAULT_OUTPUT = Path("validation_outputs/event_level_semantics_evidence_audit_20260522.json")
MAX_DEFAULT_BYTES = 6_000_000
MAX_DEFAULT_FILES = 160


def build_event_level_semantics_audit(
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
        "limitations": [
            "This audit reads scope metadata and local report rows only.",
            "It does not change selected-market or whole-event runtime semantics.",
            "Skipped large reports require a bounded operator replay if exact scope distribution is needed.",
        ],
    }


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

    report = build_event_level_semantics_audit(args.root, max_files=args.max_files, max_bytes=args.max_bytes)
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
            "relatedMarketReferenceCount": 0,
            "siblingContextTradeCount": 0,
            "scopeCopyClear": False,
            "selectedMarketPrimaryRows": 0,
            "possibleScopeAmbiguity": True,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, Mapping):
        payload = {}
    analysis_scope = str(payload.get("analysis_scope") or payload.get("analysisScope") or "unknown").lower()
    selected_condition = str(payload.get("selected_condition_id") or payload.get("selectedConditionId") or "")
    selected_slug = str(payload.get("selected_market_slug") or payload.get("selectedMarketSlug") or "")
    related = payload.get("related_markets")
    markets = payload.get("markets")
    suspicious = payload.get("suspicious_trades")
    display = payload.get("display_trades")
    rows = [row for row in (suspicious if isinstance(suspicious, list) else display if isinstance(display, list) else []) if isinstance(row, Mapping)]
    non_selected_rows = [
        row
        for row in rows
        if selected_condition
        and str(row.get("conditionId") or row.get("condition_id") or "") not in {"", selected_condition}
    ]
    scope_text = " ".join(
        str(payload.get(key) or "")
        for key in ("scope_note", "display_note", "event_report_markdown", "model_gap_markdown")
    ).lower()
    scope_copy_clear = (
        ("selected market" in scope_text or "whole-event" in scope_text or "whole event" in scope_text)
        and ("context" in scope_text or "primary" in scope_text or analysis_scope in {"market", "event"})
    )
    related_count = len(related) if isinstance(related, list) else 0
    market_count = len(markets) if isinstance(markets, list) else int(_mapping(payload.get("summary")).get("analysis_market_count") or 0)
    primary_scope = "selected_market" if analysis_scope == "market" else "whole_event" if analysis_scope == "event" else "unknown"
    ambiguous = bool(analysis_scope == "market" and (related_count or non_selected_rows) and not scope_copy_clear)
    return {
        "path": relative,
        "sourceType": source_type,
        "loadStatus": "loaded",
        "sizeBytes": size,
        "analysisScope": analysis_scope or "unknown",
        "primaryScoringScope": primary_scope,
        "selectedConditionIdPresent": bool(selected_condition),
        "selectedMarketSlugPresent": bool(selected_slug),
        "relatedMarketReferenceCount": related_count,
        "analysisMarketCount": market_count,
        "siblingContextTradeCount": len(non_selected_rows),
        "rowCount": len(rows),
        "scopeCopyClear": scope_copy_clear,
        "selectedMarketPrimaryRows": len(rows) - len(non_selected_rows),
        "possibleScopeAmbiguity": ambiguous,
    }


def _summarize(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    statuses = Counter(str(row.get("loadStatus") or "unknown") for row in rows)
    scopes = Counter(str(row.get("primaryScoringScope") or "unknown") for row in rows)
    source_types = Counter(str(row.get("sourceType") or "unknown") for row in rows)
    ambiguity = [row for row in rows if row.get("possibleScopeAmbiguity")]
    return {
        "artifactCount": len(rows),
        "loadedReportCount": statuses.get("loaded", 0),
        "skippedTooLargeCount": statuses.get("skipped_too_large", 0),
        "sourceTypeCounts": dict(sorted(source_types.items())),
        "primaryScopeCounts": dict(sorted(scopes.items())),
        "marketScopeReportCount": scopes.get("selected_market", 0),
        "wholeEventReportCount": scopes.get("whole_event", 0),
        "reportsWithRelatedMarketReferences": sum(1 for row in rows if int(row.get("relatedMarketReferenceCount") or 0) > 0),
        "reportsWithSiblingContextRows": sum(1 for row in rows if int(row.get("siblingContextTradeCount") or 0) > 0),
        "reportsWithClearScopeCopy": sum(1 for row in rows if row.get("scopeCopyClear")),
        "possibleScopeAmbiguityCount": len(ambiguity),
        "runtimeScopeChanged": False,
    }


def _gate(summary: Mapping[str, object]) -> str:
    if summary.get("possibleScopeAmbiguityCount", 0):
        return "event_level_semantics_needs_product_decision"
    return "event_level_semantics_evidence_hardened"


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _relative(base: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
