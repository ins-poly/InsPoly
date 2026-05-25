#!/usr/bin/env python3
"""Replay local shadow metric fixtures into sidecar score history.

The replay is append-only by design: repeating the same fixture records another
historical observation with the same input hash. It does not call network APIs,
mutate production reports, or import scanner/archive/event-forensic runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.indexer import IndexerStorage, ScoreHistoryEntry  # noqa: E402
from app.shadow_metrics import compute_shadow_metrics_from_payload  # noqa: E402


def replay_shadow_metrics_fixture(
    fixture_path: str | Path,
    db_path: str | Path,
    *,
    computed_at: str | None = None,
) -> dict[str, Any]:
    payload = _read_fixture(Path(fixture_path))
    storage = IndexerStorage(Path(db_path))
    storage.init()
    report = compute_shadow_metrics_from_payload(payload)
    input_hash = _input_hash(payload)
    subject_type = _text(payload.get("subject_type") or payload.get("subjectType")) or "wallet"
    subject_id = _text(payload.get("subject_id") or payload.get("subjectId")) or _infer_subject_id(payload)
    timestamp = computed_at or datetime.now(tz=UTC).replace(microsecond=0).isoformat()
    inserted_ids: list[int] = []
    for metric in report.metrics:
        inserted_ids.append(
            storage.append_score_history(
                ScoreHistoryEntry(
                    subject_type=subject_type,
                    subject_id=subject_id,
                    score_type=metric.name,
                    score=metric.value or "unknown",
                    label=f"shadow_{metric.advisory_level}",
                    computed_at=timestamp,
                    input_hash=input_hash,
                    raw_metrics=metric.to_dict(),
                )
            )
        )
    return {
        "fixturePath": str(fixture_path),
        "dbPath": str(db_path),
        "subjectType": subject_type,
        "subjectId": subject_id,
        "inputHash": input_hash,
        "rowsInserted": len(inserted_ids),
        "insertedIds": inserted_ids,
        "appendOnlyReplay": True,
        "networkUsed": False,
        "productionIntegration": False,
    }


def _read_fixture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Shadow metric replay fixture root must be a JSON object")
    return payload


def _input_hash(payload: Mapping[str, object]) -> str:
    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _infer_subject_id(payload: Mapping[str, object]) -> str:
    trades = payload.get("trades")
    if isinstance(trades, list):
        for row in trades:
            if isinstance(row, Mapping):
                wallet = _text(row.get("wallet") or row.get("proxyWallet") or row.get("user"))
                if wallet:
                    return wallet
    return "unknown"


def _text(value: object) -> str:
    return str(value).strip() if value not in (None, "") else ""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay local shadow metric fixture into sidecar score history.")
    parser.add_argument("--fixture-json", required=True, help="Local shadow metric fixture JSON.")
    parser.add_argument("--db-path", required=True, help="Target sidecar SQLite DB path.")
    parser.add_argument("--computed-at", help="Optional deterministic timestamp for score history rows.")
    args = parser.parse_args(argv)
    summary = replay_shadow_metrics_fixture(args.fixture_json, args.db_path, computed_at=args.computed_at)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
