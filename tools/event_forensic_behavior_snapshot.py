#!/usr/bin/env python3
"""Build an offline Event Forensic behavior snapshot from saved output rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.event_forensic_performance import (
    CANDIDATE_ID_FIELDS,
    compare_candidate_output_contract,
    candidate_performance_cache_key,
)


REPORT_TYPE = "event_forensic_behavior_snapshot"
SCHEMA_VERSION = "event_forensic_behavior_snapshot_v1"
DEFAULT_INPUT = Path(
    "validation_outputs/event_forensic_subset_measurement_20260525_181811/"
    "live_run/event_forensic_outputs/event_forensic_20260525_151815/candidate_trades.json"
)
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_behavior_baseline_snapshot_20260525.json")
ROW_COLLECTION_FIELDS = (
    "rows",
    "candidate_trades",
    "suspicious_trades",
    "review_required_trades",
    "display_trades",
    "display_review_required_trades",
)


def build_behavior_snapshot(
    rows: Sequence[Mapping[str, object]],
    *,
    source_path: str = "",
    include_rows: bool = False,
) -> dict[str, object]:
    contract_rows = extract_candidate_contract_rows(rows)
    rank_order_ids = [
        row["candidateId"]
        for row in sorted(
            contract_rows,
            key=lambda item: (-_float_value(item.get("eventForensicScore")), int(item.get("sourceIndex") or 0)),
        )
    ]
    candidate_rows_json = json.dumps(contract_rows, sort_keys=True, separators=(",", ":"))
    snapshot = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sourcePath": source_path,
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "storageMutated": False,
        "savedArtifactsMutated": False,
        "candidateCount": len(contract_rows),
        "candidateIds": [str(row["candidateId"]) for row in contract_rows],
        "rankOrderIds": rank_order_ids,
        "scoreByCandidateId": {
            str(row["candidateId"]): row.get("eventForensicScore") for row in contract_rows
        },
        "reviewBucketByCandidateId": {
            str(row["candidateId"]): row.get("reviewBucket") for row in contract_rows
        },
        "exportRowKeys": [str(row["exportRowKey"]) for row in contract_rows],
        "exportRowCount": len(contract_rows),
        "candidateRowsIncluded": include_rows,
        "candidateRowsSha256": hashlib.sha256(candidate_rows_json.encode("utf-8")).hexdigest(),
        "candidateRowsSample": contract_rows[:5],
        "contractComparisonAgainstSelf": compare_candidate_output_contract(contract_rows, contract_rows),
    }
    if include_rows:
        snapshot["candidateRows"] = contract_rows
    return snapshot


def extract_candidate_contract_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        candidate_id = _candidate_id(row, index)
        result.append(
            {
                "sourceIndex": index,
                "candidateId": candidate_id,
                "tradeId": _first_text(row, CANDIDATE_ID_FIELDS),
                "tradeKey": str(row.get("tradeKey") or row.get("candidateTradeKey") or ""),
                "wallet": str(row.get("wallet") or ""),
                "conditionId": str(row.get("conditionId") or row.get("condition_id") or ""),
                "timestamp": str(row.get("timestamp") or ""),
                "eventForensicScore": _score_value(row.get("eventForensicScore")),
                "existingModelScore": _score_value(row.get("existingModelScore") or row.get("currentModelScore")),
                "rank": row.get("rank") or index + 1,
                "reviewBucket": _review_bucket(row),
                "candidateAdmissionStage": str(row.get("candidateAdmissionStage") or ""),
                "weakHistoryNearCertaintyReviewDemotion": str(
                    row.get("weakHistoryNearCertaintyReviewDemotion") or ""
                ),
                "exportRowKey": _export_row_key(row, candidate_id),
            }
        )
    return result


def load_rows(path: str | Path) -> list[dict[str, object]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object or list")
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for field in ROW_COLLECTION_FIELDS:
        value = payload.get(field)
        if not isinstance(value, list):
            continue
        for index, row in enumerate(value):
            if not isinstance(row, Mapping):
                continue
            candidate_id = _candidate_id(row, len(rows) + index)
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            rows.append(dict(row))
    return rows


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--include-rows", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    rows = load_rows(args.input)
    snapshot = build_behavior_snapshot(rows, source_path=args.input, include_rows=args.include_rows)
    write_json(snapshot, args.output)
    if not args.quiet:
        print(json.dumps({"output": args.output, "candidateCount": snapshot["candidateCount"]}, sort_keys=True))
    return 0


def _candidate_id(row: Mapping[str, object], index: int) -> str:
    candidate_id = _first_text(row, CANDIDATE_ID_FIELDS)
    if candidate_id:
        return candidate_id
    cache_key = candidate_performance_cache_key(row)
    return cache_key or f"candidate-{index + 1}"


def _first_text(row: Mapping[str, object], fields: Sequence[str]) -> str:
    for field in fields:
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def _review_bucket(row: Mapping[str, object]) -> str:
    for field in ("reviewBucketAfterPolicy", "finalDisplayTier", "reviewBucket", "candidateAdmissionStage"):
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return "unknown"


def _export_row_key(row: Mapping[str, object], candidate_id: str) -> str:
    parts = [
        candidate_id,
        str(row.get("wallet") or ""),
        str(row.get("conditionId") or row.get("condition_id") or ""),
        str(row.get("timestamp") or ""),
    ]
    return "|".join(parts)


def _score_value(value: object) -> int | float | str:
    if value in (None, ""):
        return ""
    try:
        numeric = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return str(value)
    if numeric.is_integer():
        return int(numeric)
    return numeric


def _float_value(value: object) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
