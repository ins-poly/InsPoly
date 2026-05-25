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
    measurement_summary: Mapping[str, object] | None = None,
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
        "performanceBudget": _performance_budget(measurement_summary),
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


def load_optional_json(path: str | Path | None) -> dict[str, object] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Optional JSON input must be a JSON object")
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


def _performance_budget(measurement_summary: Mapping[str, object] | None) -> dict[str, object]:
    if not measurement_summary:
        return {
            "source": "none",
            "budgetStatus": "not_computed",
            "notes": ["no_measurement_summary_supplied"],
        }
    summary = measurement_summary.get("summary") if isinstance(measurement_summary.get("summary"), Mapping) else {}
    timings = summary.get("timings") if isinstance(summary.get("timings"), Mapping) else {}
    if not timings:
        report_summary = measurement_summary.get("reportSummary")
        if isinstance(report_summary, Mapping):
            timings = report_summary.get("timings") if isinstance(report_summary.get("timings"), Mapping) else {}
    total_seconds = _float_or_none(summary.get("totalSeconds"))
    if total_seconds is None:
        report_summary = measurement_summary.get("reportSummary")
        if isinstance(report_summary, Mapping):
            total_seconds = _float_or_none(report_summary.get("totalSeconds"))
    max_wall_seconds = _nested_number(measurement_summary, "bounds", "maxWallSeconds")
    budget_status = "unknown"
    notes: list[str] = []
    if total_seconds is None:
        notes.append("measurement_total_seconds_missing")
    elif max_wall_seconds is None:
        notes.append("measurement_wall_budget_missing")
    elif total_seconds <= max_wall_seconds:
        budget_status = "within_observed_wall_budget"
    else:
        budget_status = "exceeds_observed_wall_budget"
        notes.append("observed_measurement_exceeds_wall_budget")
    dominant_bottleneck = str(summary.get("dominantBottleneck") or "")
    if not dominant_bottleneck and timings:
        dominant_bottleneck = _dominant_timing(timings)
    return {
        "source": "bounded_measurement_summary",
        "budgetStatus": budget_status,
        "observedTotalSeconds": total_seconds,
        "observedMaxWallSeconds": max_wall_seconds,
        "observedMarketCount": summary.get("marketCount"),
        "observedRawTradeRows": summary.get("rawTradeRows"),
        "observedCandidateRows": summary.get("candidateRows"),
        "observedDominantBottleneck": dominant_bottleneck,
        "networkAllowedByDefault": False,
        "backgroundSchedulerStarted": False,
        "notes": notes or ["bounded_measurement_budget_recorded"],
    }


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nested_number(payload: Mapping[str, object], first: str, second: str) -> float | None:
    value = payload.get(first)
    if not isinstance(value, Mapping):
        return None
    return _float_or_none(value.get(second))


def _dominant_timing(timings: Mapping[str, object]) -> str:
    best_key = ""
    best_value = -1.0
    for key, value in timings.items():
        if key == "total_seconds":
            continue
        numeric = _float_or_none(value)
        if numeric is not None and numeric > best_value:
            best_key = str(key)
            best_value = numeric
    return best_key


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
    parser.add_argument("--measurement-summary")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    plan = build_replay_schedule_plan(
        load_snapshot(args.snapshot),
        measurement_summary=load_optional_json(args.measurement_summary),
    )
    write_json(plan, args.output)
    if not args.quiet:
        print(f"gate: {plan['gateDecision']}")
        print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
