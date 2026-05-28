#!/usr/bin/env python3
"""Audit saved Event Forensic reports for weak-history near-certain later wins.

This is an offline sidecar. It reads existing local JSON/CSV artifacts and
synthetic test fixtures only. It does not call live/RPC services and does not
modify saved reports.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.side_outcome import UNKNOWN, normalize_side_outcome


REPORT_TYPE = "event_forensic_weak_history_saved_report_audit"
SCHEMA_VERSION = "event_forensic_weak_history_saved_report_audit_v1"
DEFAULT_INVENTORY_OUTPUT = Path("validation_outputs/event_forensic_saved_report_inventory_20260522.json")
DEFAULT_AUDIT_OUTPUT = Path("validation_outputs/event_forensic_weak_history_saved_report_audit_20260522.json")
NEAR_CERTAINTY_THRESHOLD = Decimal("0.95")
MAX_DEFAULT_BYTES = 6_000_000
MAX_DEFAULT_FILES = 180
MAX_DEFAULT_ROWS_PER_FILE = 260


def build_saved_report_inventory(
    root: str | Path = ".",
    *,
    max_files: int | None = MAX_DEFAULT_FILES,
    max_bytes: int | None = MAX_DEFAULT_BYTES,
) -> dict[str, object]:
    base = Path(root)
    paths = _discover_artifacts(base)
    if max_files is not None:
        paths = paths[:max_files]
    items = [_inventory_item(base, path, max_bytes=max_bytes) for path in paths]
    counts = Counter(str(item["sourceType"]) for item in items)
    skipped = sum(1 for item in items if item["loadStatus"].startswith("skipped"))
    return {
        "reportType": "event_forensic_saved_report_inventory",
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "root": str(base.resolve()),
        "sidecarOnly": True,
        "networkUsed": False,
        "savedArtifactsMutated": False,
        "summary": {
            "artifactCount": len(items),
            "realLocalSavedReportCount": counts.get("real_local_saved_report", 0),
            "syntheticFixtureCount": counts.get("synthetic_fixture", 0),
            "skippedTooLargeCount": skipped,
        },
        "items": items,
    }


def build_weak_history_saved_report_audit(
    root: str | Path = ".",
    *,
    max_files: int | None = MAX_DEFAULT_FILES,
    max_bytes: int | None = MAX_DEFAULT_BYTES,
    max_rows_per_file: int | None = MAX_DEFAULT_ROWS_PER_FILE,
) -> dict[str, object]:
    base = Path(root)
    inventory = build_saved_report_inventory(base, max_files=max_files, max_bytes=max_bytes)
    rows: list[dict[str, object]] = []
    skipped_rows = 0
    for item in inventory["items"]:
        if not isinstance(item, Mapping) or item.get("loadStatus") != "loadable":
            continue
        artifact_path = base / str(item["path"])
        loaded = _load_artifact_rows(artifact_path, max_rows_per_file=max_rows_per_file)
        skipped_rows += int(loaded.get("skippedRows") or 0)
        source_type = str(item["sourceType"])
        for row in loaded["rows"]:
            if isinstance(row, Mapping):
                rows.append(evaluate_saved_report_row(row, artifact_path, source_type))
    summary = _summarize(rows, inventory, skipped_rows)
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
        "representativeCases": _representative_cases(rows),
        "limitations": [
            "Saved-report replay can prove field compatibility and local examples, but not current live ranking distribution.",
            "Synthetic fixtures are contract checks only and are excluded from production-evidence counts.",
            "Large local event_analysis.json files may be skipped by byte bound and remain candidates for a future bounded operator run.",
        ],
    }


def evaluate_saved_report_row(row: Mapping[str, object], artifact_path: str | Path, source_type: str) -> dict[str, object]:
    artifact = Path(artifact_path)
    order_side = _first(row, "rawOrderSide", "raw_order_side", "orderSide", "order_side")
    token_outcome = _first(row, "rawTokenOutcome", "raw_token_outcome", "side", "outcome")
    raw_price = _first(row, "rawTokenPrice", "raw_token_price", "price", "entryPrice", "entry_probability")
    normalized = normalize_side_outcome(order_side, token_outcome, raw_price)
    model_probability = normalized.economic_side_probability
    later_won = _boolish(_first(row, "laterWon", "later_won", "laterCorrect", "later_correct"))
    winner_rank = _intish(_first(row, "winnerRank", "winner_rank", "winningRank", "winning_rank"))
    weak_history = _weak_history_classification(row)
    near_certain = bool(model_probability is not None and model_probability >= NEAR_CERTAINTY_THRESHOLD)
    sufficient = (
        source_type == "real_local_saved_report"
        and normalized.normalization_status == "normalized"
        and later_won is not None
        and weak_history != UNKNOWN
        and winner_rank is not None
    )
    quality_notes = _quality_notes(row, normalized.normalization_status, later_won, winner_rank, weak_history)
    return {
        "artifactPath": _relative(ROOT, artifact),
        "sourceType": source_type,
        "tradeKey": str(_first(row, "id", "tradeId", "trade_id", "transactionHash", "uniqueTradeKey") or ""),
        "wallet": str(_first(row, "wallet", "proxyWallet", "address") or ""),
        "market": str(_first(row, "market", "marketTitle", "selectedMarketTitle") or ""),
        "event": str(_first(row, "parentEventSlug", "eventSlug", "event") or ""),
        "analysisScope": str(_first(row, "analysisScope", "analysis_scope") or UNKNOWN),
        "rawOrderSide": normalized.raw_order_side,
        "rawTokenOutcome": normalized.raw_token_outcome,
        "rawTokenPrice": _decimal_text(normalized.raw_token_price),
        "economicSide": normalized.economic_side,
        "economicSideProbability": _decimal_text(model_probability),
        "modelProbabilityBasis": normalized.model_probability_basis,
        "nearCertainEconomicEntry": near_certain,
        "laterWon": later_won if later_won is not None else UNKNOWN,
        "winnerRank": winner_rank if winner_rank is not None else UNKNOWN,
        "weakHistoryClassification": weak_history,
        "weakHistoryNearCertainLaterWin": bool(near_certain and later_won is True and weak_history == "weak_history"),
        "sufficientForLocalBlockerClosure": sufficient,
        "qualityNotes": quality_notes,
    }


def write_json(path: str | Path, payload: Mapping[str, object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--inventory-output", default=str(DEFAULT_INVENTORY_OUTPUT))
    parser.add_argument("--audit-output", default=str(DEFAULT_AUDIT_OUTPUT))
    parser.add_argument("--max-files", type=int, default=MAX_DEFAULT_FILES)
    parser.add_argument("--max-bytes", type=int, default=MAX_DEFAULT_BYTES)
    parser.add_argument("--max-rows-per-file", type=int, default=MAX_DEFAULT_ROWS_PER_FILE)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    inventory = build_saved_report_inventory(args.root, max_files=args.max_files, max_bytes=args.max_bytes)
    audit = build_weak_history_saved_report_audit(
        args.root,
        max_files=args.max_files,
        max_bytes=args.max_bytes,
        max_rows_per_file=args.max_rows_per_file,
    )
    write_json(args.inventory_output, inventory)
    write_json(args.audit_output, audit)
    if not args.quiet:
        print(f"inventory: {args.inventory_output}")
        print(f"audit: {args.audit_output}")
        print(f"gate: {audit['gateDecision']}")
    return 0


def _discover_artifacts(base: Path) -> list[Path]:
    patterns = (
        "tests/fixtures/event_forensic_weak_history_saved_reports/*.json",
        ".inspoly/reports/event_forensic_*.json",
        "event_forensic_outputs/**/event_analysis.json",
        "event_forensic_outputs/event_forensic_*.json",
        "event_forensic_outputs/**/suspicious_trades.csv",
    )
    paths: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(base.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def _inventory_item(base: Path, path: Path, *, max_bytes: int | None) -> dict[str, object]:
    relative = _relative(base, path)
    size = path.stat().st_size
    source_type = "synthetic_fixture" if "tests/fixtures" in relative else "real_local_saved_report"
    load_status = "loadable"
    if max_bytes is not None and size > max_bytes:
        load_status = "skipped_too_large"
    return {
        "path": relative,
        "sourceType": source_type,
        "sizeBytes": size,
        "format": path.suffix.lstrip("."),
        "loadStatus": load_status,
    }


def _load_artifact_rows(path: Path, *, max_rows_per_file: int | None) -> dict[str, object]:
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
    for key in ("suspicious_trades", "display_trades", "trades", "cases"):
        value = payload.get(key)
        if isinstance(value, list):
            for row in value:
                if isinstance(row, Mapping):
                    yield row


def _summarize(rows: Sequence[Mapping[str, object]], inventory: Mapping[str, object], skipped_rows: int) -> dict[str, object]:
    source_counts = Counter(str(row.get("sourceType") or UNKNOWN) for row in rows)
    weak_near_later = [row for row in rows if row.get("weakHistoryNearCertainLaterWin")]
    real_weak_near_later = [row for row in weak_near_later if row.get("sourceType") == "real_local_saved_report"]
    sufficient = [row for row in real_weak_near_later if row.get("sufficientForLocalBlockerClosure")]
    return {
        "artifactInventory": inventory.get("summary", {}),
        "rowsEvaluated": len(rows),
        "rowsSkippedByBound": skipped_rows,
        "sourceTypeCounts": dict(sorted(source_counts.items())),
        "nearCertainEconomicRows": sum(1 for row in rows if row.get("nearCertainEconomicEntry")),
        "laterWinRows": sum(1 for row in rows if row.get("laterWon") is True),
        "weakHistoryRows": sum(1 for row in rows if row.get("weakHistoryClassification") == "weak_history"),
        "weakHistoryNearCertainLaterWinRows": len(weak_near_later),
        "realWeakHistoryNearCertainLaterWinRows": len(real_weak_near_later),
        "sufficientRealWeakHistoryNearCertainLaterWinRows": len(sufficient),
        "unknownEconomicProbabilityRows": sum(1 for row in rows if row.get("economicSideProbability") == UNKNOWN),
        "unknownWeakHistoryRows": sum(1 for row in rows if row.get("weakHistoryClassification") == UNKNOWN),
        "unknownLaterWinRows": sum(1 for row in rows if row.get("laterWon") == UNKNOWN),
        "unknownWinnerRankRows": sum(1 for row in rows if row.get("winnerRank") == UNKNOWN),
        "localBlockerClosed": len(sufficient) >= 10,
    }


def _gate(summary: Mapping[str, object]) -> str:
    if summary.get("localBlockerClosed"):
        return "weak_history_blocker_closed_locally"
    if summary.get("realWeakHistoryNearCertainLaterWinRows", 0):
        return "weak_history_needs_live_rpc_validation"
    if summary.get("rowsEvaluated", 0):
        return "weak_history_needs_more_saved_reports"
    return "weak_history_needs_more_saved_reports"


def _representative_cases(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    interesting = [
        row
        for row in rows
        if row.get("weakHistoryNearCertainLaterWin")
        or row.get("nearCertainEconomicEntry")
        or row.get("sourceType") == "synthetic_fixture"
    ]
    return [dict(row) for row in interesting[:20]]


def _weak_history_classification(row: Mapping[str, object]) -> str:
    text_parts: list[str] = []
    for key in (
        "eventForensicFlags",
        "event_forensic_flags",
        "eventForensicReducers",
        "reducesConcern",
        "summary",
        "strongRiskSuppressorConflictReasons",
    ):
        value = row.get(key)
        if isinstance(value, list):
            text_parts.extend(str(item) for item in value)
        elif value not in (None, ""):
            text_parts.append(str(value))
    raw_metrics = row.get("rawMetrics")
    if isinstance(raw_metrics, Mapping):
        text_parts.extend(str(raw_metrics.get(key) or "") for key in ("wallet_economic_history_note", "weak_wallet_track_record"))
    text = " ".join(text_parts).lower()
    if "weak_wallet_track_record" in text or "weak economic history" in text or "weak economic track" in text:
        return "weak_history"
    if "history is not weak" in text or "strong track record" in text:
        return "not_weak_history"
    return UNKNOWN


def _quality_notes(
    row: Mapping[str, object],
    normalization_status: str,
    later_won: bool | None,
    winner_rank: int | None,
    weak_history: str,
) -> list[str]:
    notes: list[str] = []
    if normalization_status != "normalized":
        notes.append("missing_or_malformed_side_outcome_price")
    if later_won is None:
        notes.append("later_won_unknown")
    if winner_rank is None:
        notes.append("winner_rank_unknown")
    if weak_history == UNKNOWN:
        notes.append("weak_history_unknown")
    if row.get("source_type") == "synthetic_fixture" or row.get("sourceType") == "synthetic_fixture":
        notes.append("synthetic_fixture_not_production_evidence")
    return notes


def _first(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _boolish(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def _intish(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return UNKNOWN
    return str(value)


def _relative(base: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
