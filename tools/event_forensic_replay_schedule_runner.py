#!/usr/bin/env python3
"""Build local Event Forensic replay schedule plans from replay snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.event_forensic_replay import DEFAULT_REPLAY_STAGES, REPLAY_SNAPSHOT_REPORT_TYPE


REPORT_TYPE = "event_forensic_replay_schedule_plan"
SCHEMA_VERSION = "event_forensic_replay_schedule_plan_v1"
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_replay_schedule_plan_20260525.json")
STAGE_OFFSETS = {
    "initial": timedelta(),
    "+1h": timedelta(hours=1),
    "+4h": timedelta(hours=4),
    "+24h": timedelta(hours=24),
}


def build_replay_schedule_plan(
    snapshot: Mapping[str, object],
    *,
    generated_at: str | None = None,
) -> dict[str, object]:
    now = _parse_datetime(generated_at) or datetime.now(tz=UTC)
    source_generated_at = _parse_datetime(str(snapshot.get("generatedAt") or "")) or now
    scope = snapshot.get("scope") if isinstance(snapshot.get("scope"), Mapping) else {}
    candidate_counts = snapshot.get("candidateCounts") if isinstance(snapshot.get("candidateCounts"), Mapping) else {}
    stages = []
    for stage in DEFAULT_REPLAY_STAGES:
        offset = STAGE_OFFSETS.get(stage, timedelta())
        stages.append(
            {
                "stage": stage,
                "scheduledFor": (source_generated_at + offset).isoformat(),
                "status": "planned_only",
                "networkAllowedByDefault": False,
                "backgroundSchedulerStarted": False,
            }
        )
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": now.isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "storageMutated": False,
        "backgroundSchedulerStarted": False,
        "sourceSnapshot": {
            "reportType": str(snapshot.get("reportType") or ""),
            "schemaVersion": str(snapshot.get("schemaVersion") or ""),
            "eventSlug": _nested_text(snapshot, "event", "eventSlug"),
            "selectedMarketSlug": _nested_text(snapshot, "market", "selectedMarketSlug"),
            "analysisScope": str(scope.get("analysisScope") or "unknown"),
            "candidateRowsInSnapshot": candidate_counts.get("candidateRowsInSnapshot", 0),
        },
        "stages": stages,
        "gateDecision": "replay_schedule_sidecar_ready",
        "qualityNotes": _quality_notes(snapshot),
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def load_snapshot(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Replay snapshot must be a JSON object")
    return payload


def _quality_notes(snapshot: Mapping[str, object]) -> list[str]:
    notes: list[str] = []
    if snapshot.get("reportType") != REPLAY_SNAPSHOT_REPORT_TYPE:
        notes.append("source_payload_not_tagged_as_replay_snapshot")
    if snapshot.get("containsRestrictedFields"):
        notes.append("source_snapshot_contains_restricted_fields")
    if not _nested_text(snapshot, "scope", "analysisScope"):
        notes.append("analysis_scope_missing")
    return notes or ["schedule_plan_ready"]


def _nested_text(payload: Mapping[str, object], first: str, second: str) -> str:
    value = payload.get(first)
    if not isinstance(value, Mapping):
        return ""
    return str(value.get(second) or "").strip()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    plan = build_replay_schedule_plan(load_snapshot(args.snapshot))
    write_json(plan, args.output)
    if not args.quiet:
        print(f"gate: {plan['gateDecision']}")
        print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
