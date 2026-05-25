#!/usr/bin/env python3
"""Preflight and bounded plan helper for Event Forensic performance measurement.

The default mode is plan-only and offline. A future approved live run can reuse
the same bound validation, but this tool does not perform network calls.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "event_forensic_bounded_performance_measurement_plan"
SCHEMA_VERSION = "event_forensic_bounded_performance_measurement_plan_v1"
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_performance_measurement_plan_20260525.json")
DEFAULT_MAX_EVENTS = 1
DEFAULT_MAX_MARKETS = 8
DEFAULT_MAX_WALL_MINUTES = 30
ENV_KEYS = ("INSPOLY_POLYGON_RPC_URLS", "POLYGON_RPC_URL", "INSPOLY_POLYGON_RPC_URL")


def build_measurement_plan(
    *,
    event_slug: str = "",
    market_slug: str = "",
    max_events: int = DEFAULT_MAX_EVENTS,
    max_markets: int = DEFAULT_MAX_MARKETS,
    max_wall_minutes: int = DEFAULT_MAX_WALL_MINUTES,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    env = os.environ if env is None else env
    bounds = {
        "maxEvents": max_events,
        "maxMarkets": max_markets,
        "maxWallMinutes": max_wall_minutes,
    }
    violations = _bound_violations(bounds)
    env_status = _env_status(env)
    gate = _gate(violations, env_status, event_slug, market_slug)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "measurementExecuted": False,
        "gateDecision": gate,
        "summary": {
            "measurementExecuted": False,
            "rpcConfigured": bool(env_status.get("rpcConfigured")),
            "boundViolationCount": len(violations),
            "maxEvents": max_events,
            "maxMarkets": max_markets,
            "maxWallMinutes": max_wall_minutes,
        },
        "target": {
            "eventSlug": event_slug,
            "marketSlug": market_slug,
            "selectionSource": "operator_supplied_or_existing_saved_report",
        },
        "bounds": bounds,
        "boundViolations": violations,
        "envStatus": env_status,
        "nextAction": (
            "Run a separate approved live measurement with this target and bounds."
            if gate == "performance_measurement_needs_operator_approval"
            else "Provide read-only RPC/API env and exact saved-report target before live measurement."
        ),
        "forbiddenActions": [
            "Do not broaden discovery beyond the selected event.",
            "Do not change scoring, thresholds, gates, storage schema, or UI sorting.",
            "Do not write to app storage or mutate saved reports.",
        ],
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _env_status(env: Mapping[str, str]) -> dict[str, object]:
    present = [key for key in ENV_KEYS if str(env.get(key) or "").strip()]
    return {
        "rpcConfigured": bool(present),
        "configuredKeyCount": len(present),
        "configuredKeys": present,
        "secretsPrinted": False,
    }


def _bound_violations(bounds: Mapping[str, int]) -> list[str]:
    violations: list[str] = []
    if int(bounds.get("maxEvents") or 0) > DEFAULT_MAX_EVENTS:
        violations.append("max_events_exceeds_campaign_bound")
    if int(bounds.get("maxMarkets") or 0) > DEFAULT_MAX_MARKETS:
        violations.append("max_markets_exceeds_campaign_bound")
    if int(bounds.get("maxWallMinutes") or 0) > DEFAULT_MAX_WALL_MINUTES:
        violations.append("max_wall_time_exceeds_campaign_bound")
    return violations


def _gate(violations: Sequence[str], env_status: Mapping[str, object], event_slug: str, market_slug: str) -> str:
    if violations:
        return "performance_measurement_scope_exceeded"
    if not env_status.get("rpcConfigured"):
        return "performance_measurement_blocked_missing_env"
    if not event_slug and not market_slug:
        return "performance_measurement_needs_operator_approval"
    return "performance_measurement_needs_operator_approval"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-slug", default="")
    parser.add_argument("--market-slug", default="")
    parser.add_argument("--max-events", type=int, default=DEFAULT_MAX_EVENTS)
    parser.add_argument("--max-markets", type=int, default=DEFAULT_MAX_MARKETS)
    parser.add_argument("--max-wall-minutes", type=int, default=DEFAULT_MAX_WALL_MINUTES)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payload = build_measurement_plan(
        event_slug=args.event_slug,
        market_slug=args.market_slug,
        max_events=args.max_events,
        max_markets=args.max_markets,
        max_wall_minutes=args.max_wall_minutes,
    )
    write_json(payload, args.output)
    if not args.quiet:
        print(f"gate: {payload['gateDecision']}")
        print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
