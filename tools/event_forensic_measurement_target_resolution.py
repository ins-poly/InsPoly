#!/usr/bin/env python3
"""Resolve bounded Event Forensic measurement target candidates."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import AppConfig
from tools.event_forensic_bounded_performance_measurement import MeasurementBounds, runtime_env_status


REPORT_TYPE = "event_forensic_measurement_target_resolution"
SCHEMA_VERSION = "event_forensic_measurement_target_resolution_v1"
DEFAULT_INPUT = Path("validation_outputs/event_forensic_measurement_target_inventory_20260525.json")
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_measurement_target_resolution_20260525.json")
DEFAULT_MAX_CANDIDATES = 8
DEFAULT_MAX_RESOLUTION_MINUTES = 15


def build_target_resolution(
    candidates: Sequence[Mapping[str, object]],
    *,
    bounds: MeasurementBounds = MeasurementBounds(),
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_resolution_minutes: int = DEFAULT_MAX_RESOLUTION_MINUTES,
    resolver: Any | None = None,
) -> dict[str, object]:
    started = time.monotonic()
    env_status = runtime_env_status(root=ROOT)
    resolved_rows: list[dict[str, object]] = []
    for index, candidate in enumerate(list(candidates)[:max_candidates], start=1):
        if time.monotonic() - started > max_resolution_minutes * 60:
            resolved_rows.append(
                {
                    "eventSlug": str(candidate.get("eventSlug") or ""),
                    "status": "blocked_resolution_time_bound",
                    "safeForFullMeasurement": False,
                    "blockReason": "target_resolution_time_bound_exceeded",
                }
            )
            break
        resolved_rows.append(
            _resolve_candidate(
                candidate,
                index=index,
                bounds=bounds,
                resolver=resolver,
            )
        )
    safe_rows = [row for row in resolved_rows if row.get("safeForFullMeasurement")]
    gate = _resolution_gate(resolved_rows, safe_rows)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": resolver is None and bool(resolved_rows),
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "storageMutated": False,
        "broadCrawlingUsed": False,
        "privateKeyUsed": False,
        "clobAuthUsed": False,
        "ordersPlaced": False,
        "bounds": {
            **bounds.to_dict(),
            "maxCandidateTargetEventsToResolve": max_candidates,
            "maxResolutionMinutes": max_resolution_minutes,
        },
        "envStatus": env_status,
        "gateDecision": gate,
        "summary": {
            "candidateCount": len(list(candidates)[:max_candidates]),
            "resolvedCount": len([row for row in resolved_rows if row.get("status") == "resolved"]),
            "safeTargetCount": len(safe_rows),
            "unsafeTargetCount": len([row for row in resolved_rows if not row.get("safeForFullMeasurement")]),
            "selectedSafeTargetEventSlug": str(safe_rows[0].get("eventSlug") or "") if safe_rows else "",
        },
        "resolvedCandidates": resolved_rows,
        "selectedSafeTarget": safe_rows[0] if safe_rows else {},
        "subsetPolicyGate": subset_policy_gate(gate),
    }


def subset_policy_gate(resolution_gate: str) -> str:
    if resolution_gate == "safe_target_found":
        return "subset_policy_not_needed"
    return "subset_policy_ready_for_user_approval"


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def load_inventory_candidates(path: str | Path) -> list[dict[str, object]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Target inventory must be a JSON object")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return []
    return [dict(item) for item in candidates if isinstance(item, Mapping)]


def _resolve_candidate(
    candidate: Mapping[str, object],
    *,
    index: int,
    bounds: MeasurementBounds,
    resolver: Any | None,
) -> dict[str, object]:
    input_value = str(candidate.get("inputValue") or "").strip()
    base = {
        "index": index,
        "eventSlug": str(candidate.get("eventSlug") or ""),
        "inputValue": input_value,
        "sourceReportPath": str(candidate.get("sourceReportPath") or ""),
        "savedAnalysisMarketCount": _int_or_zero(candidate.get("savedAnalysisMarketCount")),
        "savedRawTradeCount": _int_or_zero(candidate.get("savedRawTradeCount")),
        "savedCandidateTradeCount": _int_or_zero(candidate.get("savedCandidateTradeCount")),
        "savedCandidateWalletCount": _int_or_zero(candidate.get("savedCandidateWalletCount")),
        "savedTruncatedMarketCount": _int_or_zero(candidate.get("savedTruncatedMarketCount")),
        "savedLocalMeasurementSafe": bool(candidate.get("savedLocalMeasurementSafe")),
    }
    if not input_value:
        return {**base, "status": "missing_input", "safeForFullMeasurement": False, "blockReason": "missing_input_value"}
    started = time.monotonic()
    try:
        resolved = resolver(input_value) if resolver is not None else _resolve_live_target(input_value)
    except Exception as exc:
        return {
            **base,
            "status": "resolution_failed",
            "safeForFullMeasurement": False,
            "blockReason": f"{type(exc).__name__}: {exc}",
            "resolutionSeconds": round(time.monotonic() - started, 3),
        }
    live_market_count = _live_market_count(resolved)
    block_reasons = _safe_target_block_reasons(base, live_market_count, bounds)
    return {
        **base,
        "status": "resolved",
        "resolutionSeconds": round(time.monotonic() - started, 3),
        "liveMarketCount": live_market_count,
        "liveSelectedMarketCount": _selected_market_count(resolved),
        "liveEventTitle": _nested_text(resolved, "event", "title"),
        "safeForFullMeasurement": not block_reasons,
        "blockReasons": block_reasons,
        "resolvedTarget": _compact_resolved_target(resolved),
    }


def _resolve_live_target(input_value: str) -> dict[str, object]:
    from app.event_forensic import EventForensicAnalyzer
    from app.polymarket import PolymarketClient
    from app.storage import Storage

    with tempfile.TemporaryDirectory(prefix="inspoly_target_resolution_") as tmp:
        data_dir = Path(tmp) / "app_data"
        config = AppConfig(
            data_dir=data_dir,
            db_path=data_dir / "target_resolution.sqlite3",
            reports_dir=data_dir / "reports",
            outputs_dir=data_dir / "outputs",
            default_lookback="event",
            max_trade_pages=1,
            trade_page_size=1,
        )
        config.ensure_dirs()
        storage = Storage(config.db_path)
        storage.init()
        analyzer = EventForensicAnalyzer(PolymarketClient(), storage, config)
        return analyzer.resolve_target(input_value, analysis_scope="event", include_related_markets=False)


def _safe_target_block_reasons(base: Mapping[str, object], live_market_count: int, bounds: MeasurementBounds) -> list[str]:
    reasons: list[str] = []
    if live_market_count <= 0:
        reasons.append("live_market_count_missing")
    elif live_market_count > bounds.max_markets:
        reasons.append("live_market_count_exceeds_bound")
    raw_rows = _int_or_zero(base.get("savedRawTradeCount"))
    if raw_rows > bounds.max_total_trade_rows:
        reasons.append("saved_raw_rows_exceed_bound")
    wallets = _int_or_zero(base.get("savedCandidateWalletCount"))
    market_denominator = live_market_count or _int_or_zero(base.get("savedAnalysisMarketCount"))
    if market_denominator and wallets > market_denominator * bounds.max_candidate_wallets_per_market:
        reasons.append("saved_candidate_wallets_exceed_per_market_bound")
    if not bool(base.get("savedLocalMeasurementSafe")):
        reasons.append("saved_local_evidence_not_measurement_safe")
    return reasons


def _resolution_gate(resolved_rows: Sequence[Mapping[str, object]], safe_rows: Sequence[Mapping[str, object]]) -> str:
    if safe_rows:
        return "safe_target_found"
    if any(row.get("status") == "blocked_resolution_time_bound" for row in resolved_rows):
        return "target_resolution_scope_risk"
    if any(row.get("status") == "resolved" for row in resolved_rows):
        return "no_safe_target_found"
    return "target_resolution_scope_risk"


def _compact_resolved_target(resolved: Mapping[str, object]) -> dict[str, object]:
    markets = resolved.get("availableMarkets") if isinstance(resolved.get("availableMarkets"), list) else []
    return {
        "analysisScope": str(resolved.get("analysisScope") or ""),
        "eventSlug": _nested_text(resolved, "event", "slug"),
        "eventTitle": _nested_text(resolved, "event", "title"),
        "marketCount": len(markets),
        "availableMarkets": [
            {
                "marketSlug": str(item.get("marketSlug") or ""),
                "marketTitle": str(item.get("marketTitle") or ""),
                "closed": bool(item.get("closed")),
                "winner": item.get("winner"),
            }
            for item in markets[:12]
            if isinstance(item, Mapping)
        ],
    }


def _live_market_count(resolved: Mapping[str, object]) -> int:
    markets = resolved.get("availableMarkets") if isinstance(resolved.get("availableMarkets"), list) else []
    return len(markets)


def _selected_market_count(resolved: Mapping[str, object]) -> int:
    markets = resolved.get("availableMarkets") if isinstance(resolved.get("availableMarkets"), list) else []
    return sum(1 for item in markets if isinstance(item, Mapping) and item.get("selected"))


def _nested_text(payload: Mapping[str, object], first: str, second: str) -> str:
    value = payload.get(first)
    if not isinstance(value, Mapping):
        return ""
    return str(value.get(second) or "").strip()


def _int_or_zero(value: object) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument("--max-resolution-minutes", type=int, default=DEFAULT_MAX_RESOLUTION_MINUTES)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payload = build_target_resolution(
        load_inventory_candidates(args.input),
        max_candidates=args.max_candidates,
        max_resolution_minutes=args.max_resolution_minutes,
    )
    write_json(payload, args.output)
    if not args.quiet:
        print(json.dumps({"gate": payload["gateDecision"], "output": args.output}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
