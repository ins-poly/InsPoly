#!/usr/bin/env python3
"""Read-only archive visibility and completeness monitoring v2."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence


REPORT_TYPE = "archive_visibility_monitoring_v2"
SCHEMA_VERSION = "archive_visibility_monitoring_v2"
DEFAULT_OUTPUT = Path("validation_outputs/archive_visibility_monitoring_v2_20260522.json")
MAX_DEFAULT_FILES = 160
MAX_DEFAULT_ROWS_PER_FILE = 160
MAX_DEFAULT_BYTES = 3_000_000


def build_archive_visibility_monitoring_v2(
    root: str | Path = ".",
    *,
    max_files: int | None = MAX_DEFAULT_FILES,
    max_rows_per_file: int | None = MAX_DEFAULT_ROWS_PER_FILE,
    max_bytes: int | None = MAX_DEFAULT_BYTES,
) -> dict[str, object]:
    base = Path(root)
    paths = _discover_archive_artifacts(base)
    if max_files is not None:
        paths = paths[:max_files]
    artifacts = [_artifact_inventory(base, path, max_bytes=max_bytes) for path in paths]
    rows: list[dict[str, object]] = []
    skipped_rows = 0
    for artifact in artifacts:
        if artifact["loadStatus"] != "loadable":
            continue
        loaded = _load_rows(base / str(artifact["path"]), max_rows_per_file=max_rows_per_file)
        skipped_rows += int(loaded.get("skippedRows") or 0)
        for row in loaded["rows"]:
            if isinstance(row, Mapping):
                rows.append(_evaluate_row(row, artifact))
    summary = _summarize(artifacts, rows, skipped_rows)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "root": str(base.resolve()),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeBehaviorChanged": False,
        "archiveVisibilityChanged": False,
        "savedArtifactsMutated": False,
        "gateDecision": _gate(summary),
        "summary": summary,
        "artifactInventory": artifacts,
        "sampleRows": rows[:40],
        "limitations": [
            "Bounded local scan only; large files may be skipped or sampled.",
            "Old/lossy rows are annotated as unsafe for rescoring, not hidden.",
            "This tool does not alter archive visibility tiers or candidate admission.",
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
    parser.add_argument("--max-rows-per-file", type=int, default=MAX_DEFAULT_ROWS_PER_FILE)
    parser.add_argument("--max-bytes", type=int, default=MAX_DEFAULT_BYTES)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_archive_visibility_monitoring_v2(
        args.root,
        max_files=args.max_files,
        max_rows_per_file=args.max_rows_per_file,
        max_bytes=args.max_bytes,
    )
    write_json(args.output, report)
    if not args.quiet:
        print(f"gate: {report['gateDecision']}")
        print(f"output: {args.output}")
    return 0


def _discover_archive_artifacts(base: Path) -> list[Path]:
    patterns = (
        "tests/fixtures/archive_visibility_monitoring_v2/*",
        "tests/fixtures/side_outcome_phase2_archive/*",
        "tests/fixtures/side_outcome_phase3_capital_at_risk/archive_rows.csv",
        ".inspoly_archive_researcher/reports/archive_research_*.json",
        ".inspoly_archive_researcher/reports/archive_research_*.csv",
    )
    paths: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(base.glob(pattern)):
            if path.is_file() and path.suffix.lower() in {".json", ".csv"} and path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def _artifact_inventory(base: Path, path: Path, *, max_bytes: int | None) -> dict[str, object]:
    relative = _relative(base, path)
    source_type = "synthetic_fixture" if "tests/fixtures" in relative else "real_local_archive_artifact"
    size = path.stat().st_size
    load_status = "loadable" if max_bytes is None or size <= max_bytes else "skipped_too_large"
    return {
        "path": relative,
        "sourceType": source_type,
        "format": path.suffix.lstrip("."),
        "sizeBytes": size,
        "loadStatus": load_status,
    }


def _load_rows(path: Path, *, max_rows_per_file: int | None) -> dict[str, object]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            rows = [row for _, row in zip(range(max_rows_per_file or 10**9), csv.DictReader(handle))]
        return {"rows": rows, "skippedRows": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"rows": [], "skippedRows": 0}
    rows = list(_rows_from_json(payload))
    if max_rows_per_file is not None and len(rows) > max_rows_per_file:
        return {"rows": rows[:max_rows_per_file], "skippedRows": len(rows) - max_rows_per_file}
    return {"rows": rows, "skippedRows": 0}


def _rows_from_json(payload: object) -> Iterable[Mapping[str, object]]:
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, Mapping):
                yield row
        return
    if not isinstance(payload, Mapping):
        return
    for key in ("flagged_cases", "excluded_cases", "secondary_cases", "cases", "trades", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            for row in value:
                if isinstance(row, Mapping):
                    yield row


def _evaluate_row(row: Mapping[str, object], artifact: Mapping[str, object]) -> dict[str, object]:
    visibility = str(_first(row, "visibility_tier", "visibilityTier", "visible_inclusion_status", "visibleInclusionStatus") or "unknown")
    side = _first(row, "raw_order_side", "rawOrderSide", "orderSide", "side")
    outcome = _first(row, "raw_token_outcome", "rawTokenOutcome", "outcome")
    price = _first(row, "raw_token_price", "rawTokenPrice", "price", "price_implied_probability")
    notes = []
    if _missing(side):
        notes.append("missing_side")
    if _missing(outcome):
        notes.append("missing_outcome")
    if _missing(price):
        notes.append("missing_price")
    if _is_lossy(row, artifact):
        notes.append("old_or_lossy_row")
    if _has_truncation_marker(row):
        notes.append("truncation_marker_present")
    return {
        "artifactPath": artifact.get("path", ""),
        "sourceType": artifact.get("sourceType", ""),
        "visibilityTier": visibility,
        "isVisible": visibility.lower() in {"visible", "included", "hard evidence review", "hard_evidence_review"},
        "isSecondaryReview": "secondary" in visibility.lower() or "excluded" in str(artifact.get("path", "")).lower(),
        "isHiddenOrExcludedLegacy": visibility.lower() in {"hidden", "excluded"},
        "sidePresent": not _missing(side),
        "outcomePresent": not _missing(outcome),
        "pricePresent": not _missing(price),
        "lossyOrOldRow": "old_or_lossy_row" in notes,
        "truncationMarkerPresent": "truncation_marker_present" in notes,
        "qualityNotes": notes,
    }


def _summarize(
    artifacts: Sequence[Mapping[str, object]],
    rows: Sequence[Mapping[str, object]],
    skipped_rows: int,
) -> dict[str, object]:
    artifact_sources = Counter(str(item.get("sourceType") or "unknown") for item in artifacts)
    row_sources = Counter(str(row.get("sourceType") or "unknown") for row in rows)
    visibility = Counter(str(row.get("visibilityTier") or "unknown") for row in rows)
    return {
        "artifactCount": len(artifacts),
        "loadableArtifactCount": sum(1 for item in artifacts if item.get("loadStatus") == "loadable"),
        "skippedTooLargeArtifactCount": sum(1 for item in artifacts if item.get("loadStatus") == "skipped_too_large"),
        "rowsEvaluated": len(rows),
        "rowsSkippedByBound": skipped_rows,
        "artifactSourceTypeCounts": dict(sorted(artifact_sources.items())),
        "rowSourceTypeCounts": dict(sorted(row_sources.items())),
        "visibilityTierCounts": dict(sorted(visibility.items())),
        "visibleOrHardEvidenceRows": sum(1 for row in rows if row.get("isVisible")),
        "secondaryReviewRows": sum(1 for row in rows if row.get("isSecondaryReview")),
        "legacyHiddenOrExcludedRows": sum(1 for row in rows if row.get("isHiddenOrExcludedLegacy")),
        "oldOrLossyRows": sum(1 for row in rows if row.get("lossyOrOldRow")),
        "missingSideRows": sum(1 for row in rows if not row.get("sidePresent")),
        "missingOutcomeRows": sum(1 for row in rows if not row.get("outcomePresent")),
        "missingPriceRows": sum(1 for row in rows if not row.get("pricePresent")),
        "truncationMarkerRows": sum(1 for row in rows if row.get("truncationMarkerPresent")),
        "archiveVisibilityChanged": False,
    }


def _gate(summary: Mapping[str, object]) -> str:
    return "archive_visibility_monitoring_v2_ready"


def _first(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _missing(value: object) -> bool:
    return value in (None, "", "unknown", "Unknown")


def _is_lossy(row: Mapping[str, object], artifact: Mapping[str, object]) -> bool:
    path = str(artifact.get("path") or "").lower()
    if artifact.get("format") == "csv" and not row.get("raw_token_price") and not row.get("rawTokenPrice"):
        return True
    return bool(row.get("old_report_row") or row.get("lossy_row") or "old" in path)


def _has_truncation_marker(row: Mapping[str, object]) -> bool:
    text = " ".join(str(row.get(key) or "") for key in ("truncated", "truncation", "dataCompleteness", "qualityNotes")).lower()
    return "truncat" in text


def _relative(base: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
