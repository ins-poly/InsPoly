#!/usr/bin/env python3
"""Audit Event Forensic score-call input reuse from saved candidate exports."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "event_forensic_score_call_input_audit"
SCHEMA_VERSION = "event_forensic_score_call_input_audit_v1"
DEFAULT_INPUT = Path(
    "validation_outputs/event_forensic_subset_measurement_20260525_181811/"
    "live_run/event_forensic_outputs/event_forensic_20260525_151815/candidate_trades.json"
)
DEFAULT_OUTPUT = Path("validation_outputs/event_forensic_score_call_input_audit_20260526.json")


def build_score_call_input_audit(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    row_count = len(rows)
    exact_signatures = Counter(_signature(row, _EXACT_SIGNATURE_FIELDS) for row in rows)
    wallet_market_token = Counter(_signature(row, _WALLET_MARKET_TOKEN_FIELDS) for row in rows)
    probability_context = Counter(_signature(row, _PROBABILITY_CONTEXT_FIELDS) for row in rows)
    gate_context = Counter(_signature(row, _GATE_CONTEXT_FIELDS) for row in rows)
    event_overlay = Counter(_signature(row, _EVENT_OVERLAY_FIELDS) for row in rows)
    exact_duplicate_rows = sum(count for count in exact_signatures.values() if count > 1)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "storageMutated": False,
        "totalRows": row_count,
        "exactInputSignature": _counter_summary(exact_signatures),
        "walletMarketTokenSignature": _counter_summary(wallet_market_token),
        "normalizedProbabilityContext": _counter_summary(probability_context),
        "fundingHerStrongRiskContext": _counter_summary(gate_context),
        "eventOverlayContext": _counter_summary(event_overlay),
        "duplicateEquivalentScoreCallsRare": exact_duplicate_rows <= max(1, int(row_count * 0.01)),
        "safeOptimizationRecommendation": (
            "memoize_context_fragments_only"
            if exact_duplicate_rows <= max(1, int(row_count * 0.01))
            else "exact_score_result_memoization_requires_complete_signature_review"
        ),
        "gateDecision": "score_call_input_reuse_context_fragments_only",
    }


def load_candidate_rows(path: str | Path) -> list[dict[str, object]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping):
        rows = payload.get("rows") or payload.get("candidateTrades") or payload.get("candidates") or []
    else:
        rows = []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payload = build_score_call_input_audit(load_candidate_rows(args.input))
    write_json(payload, args.output)
    if not args.quiet:
        print(json.dumps({"output": args.output, "gateDecision": payload["gateDecision"]}, sort_keys=True))
    return 0


_EXACT_SIGNATURE_FIELDS = (
    "wallet",
    "conditionId",
    "marketSlug",
    "timestamp",
    "rawOrderSide",
    "rawTokenOutcome",
    "rawTokenPrice",
    "notionalUsd",
    "candidateAdmissionStage",
    "analysisScope",
    "selectedConditionId",
)
_WALLET_MARKET_TOKEN_FIELDS = ("wallet", "conditionId", "rawOrderSide", "rawTokenOutcome")
_PROBABILITY_CONTEXT_FIELDS = (
    "rawOrderSide",
    "rawTokenOutcome",
    "economicSide",
    "economicSideProbability",
    "modelEconomicDirection",
    "clusterDirection",
)
_GATE_CONTEXT_FIELDS = (
    "fundingEvidenceGrade",
    "hardEvidenceReviewTier",
    "strongRiskGateType",
    "candidateAdmissionStage",
    "weakHistoryNearCertaintyReviewDemotion",
)
_EVENT_OVERLAY_FIELDS = ("parentEventSlug", "selectedMarketSlug", "analysisScope")


def _signature(row: Mapping[str, object], fields: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(row.get(field) or "") for field in fields)


def _counter_summary(counter: Counter[tuple[str, ...]]) -> dict[str, object]:
    total_rows = sum(counter.values())
    repeated_groups = {key: count for key, count in counter.items() if count > 1}
    return {
        "uniqueSignatures": len(counter),
        "repeatedSignatureGroups": len(repeated_groups),
        "rowsInRepeatedSignatureGroups": sum(repeated_groups.values()),
        "largestGroupSize": max(counter.values(), default=0),
        "reuseRatio": round((sum(repeated_groups.values()) / total_rows), 6) if total_rows else 0.0,
        "topRepeatedGroups": [
            {"signature": list(key), "count": count}
            for key, count in counter.most_common(5)
            if count > 1
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
