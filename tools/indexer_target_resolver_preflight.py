#!/usr/bin/env python3
"""Bounded read-only target resolver preflight for indexer sidecar probes."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.polymarket import PolymarketClient  # noqa: E402


REPORT_TYPE = "indexer_target_resolver_preflight"
SCHEMA_VERSION = "indexer_target_resolver_preflight_v1"

GATE_READY = "indexer_target_resolver_preflight_selected_3_targets"
GATE_BLOCKED_MISSING_APPROVAL = "indexer_target_resolver_preflight_blocked_missing_live_approval"
GATE_BLOCKED_MISSING_VALID_TARGETS = "indexer_target_resolver_preflight_blocked_missing_valid_targets"

VALID_CLASSIFICATIONS = {"preferred_repeat_anchor", "replacement_candidate", "sparse_control", "failed_needs_review"}
REPLACEMENT_CLASSIFICATIONS = {"replacement_candidate", "sparse_control"}


def run_resolver_preflight(
    registry_json: str | Path,
    *,
    output_json: str | Path | None = None,
    max_candidates: int = 10,
    allow_live_network: bool = False,
    client: object | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Resolve registry candidates without trades, SQLite writes, or production integration."""

    generated_at = (now or datetime.now(tz=UTC)).isoformat()
    registry_path = Path(registry_json)
    registry = _read_json_object(registry_path)
    candidates = _candidate_list(registry)
    preferred_anchors = _text_list(registry.get("preferredAnchors"))
    replacement_priority = _text_list(registry.get("replacementPriority"))

    report: dict[str, object] = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at,
        "registryJson": str(registry_path),
        "sidecarOnly": True,
        "readOnly": True,
        "networkUsed": False,
        "tradeIngestion": False,
        "sqliteWritten": False,
        "productionIntegration": False,
        "maxCandidates": int(max_candidates),
        "preferredAnchors": preferred_anchors,
        "replacementPriority": replacement_priority,
        "results": [],
        "summary": {
            "gateDecision": GATE_BLOCKED_MISSING_VALID_TARGETS,
            "candidatesConsidered": 0,
            "candidatesResolved": 0,
            "validTargetCount": 0,
            "selectedCount": 0,
            "selectedMarketSlugs": [],
            "selectedConditionIds": [],
            "anchorsValid": False,
            "replacementSelected": "",
            "blockedReason": "",
            "recommendedNextAction": "do_not_run_live_ingestion_until_three_valid_targets_selected",
        },
    }

    if not allow_live_network:
        summary = report["summary"]
        assert isinstance(summary, dict)
        summary["gateDecision"] = GATE_BLOCKED_MISSING_APPROVAL
        summary["blockedReason"] = "resolver_preflight_requires_explicit_allow_live_network"
        _write_if_requested(report, output_json)
        return report

    report["networkUsed"] = True
    client_instance = client or PolymarketClient()
    checked = 0
    results: list[dict[str, object]] = []
    valid_by_slug: dict[str, dict[str, object]] = {}

    for candidate in sorted(candidates, key=lambda item: int(item.get("priority") or 9999)):
        slug = str(candidate.get("slug") or "").strip()
        classification = str(candidate.get("candidateClassification") or "")
        needs_preflight = bool(candidate.get("liveResolverPreflightNeeded"))
        if not slug:
            continue
        if not needs_preflight or classification not in VALID_CLASSIFICATIONS:
            results.append(_skipped_result(candidate, "skipped_local_policy"))
            continue
        if checked >= max_candidates:
            results.append(_skipped_result(candidate, "skipped_max_candidates_reached"))
            continue
        checked += 1
        resolved = _resolve_candidate(candidate, client_instance)
        results.append(resolved)
        if resolved.get("status") == "valid_single_market":
            valid_by_slug[slug] = resolved

    selected: list[dict[str, object]] = []
    missing_anchors: list[str] = []
    for anchor in preferred_anchors:
        resolved = valid_by_slug.get(anchor)
        if resolved:
            selected.append(resolved)
        else:
            missing_anchors.append(anchor)

    replacement_selected = ""
    if not missing_anchors:
        for slug in replacement_priority:
            resolved = valid_by_slug.get(slug)
            if resolved:
                selected.append(resolved)
                replacement_selected = slug
                break

    selected = selected[:3]
    selected_slugs = [str(item.get("canonicalMarketSlug") or item.get("slug") or "") for item in selected]
    selected_conditions = [str(item.get("conditionId") or "") for item in selected if item.get("conditionId")]
    valid_count = sum(1 for item in results if item.get("status") == "valid_single_market")
    gate = GATE_READY if len(selected_slugs) == 3 and not missing_anchors and replacement_selected else GATE_BLOCKED_MISSING_VALID_TARGETS
    blocked_reason = ""
    if gate != GATE_READY:
        if missing_anchors:
            blocked_reason = "preferred_anchor_failed_preflight"
        elif not replacement_selected:
            blocked_reason = "replacement_target_failed_preflight"
        else:
            blocked_reason = "selected_target_count_not_three"

    report["results"] = results
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary.update(
        {
            "gateDecision": gate,
            "candidatesConsidered": checked,
            "candidatesResolved": checked,
            "validTargetCount": valid_count,
            "selectedCount": len(selected_slugs),
            "selectedMarketSlugs": selected_slugs,
            "selectedConditionIds": selected_conditions,
            "anchorsValid": not missing_anchors and len(preferred_anchors) == 2,
            "replacementSelected": replacement_selected,
            "blockedReason": blocked_reason,
            "recommendedNextAction": (
                "run_one_bounded_multitarget_repeat_probe_no_runtime_integration"
                if gate == GATE_READY
                else "expand_or_repair_target_registry_before_live_ingestion"
            ),
        }
    )
    _write_if_requested(report, output_json)
    return report


def write_preflight_output(report: Mapping[str, object], output_json: str | Path) -> Path:
    target = Path(output_json)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _resolve_candidate(candidate: Mapping[str, object], client: object) -> dict[str, object]:
    slug = str(candidate.get("slug") or "").strip()
    base = {
        "slug": slug,
        "candidateClassification": str(candidate.get("candidateClassification") or ""),
        "priority": int(candidate.get("priority") or 9999),
        "status": "provider_lookup_failed",
        "resolutionSource": "",
        "canonicalMarketSlug": "",
        "conditionId": "",
        "marketCount": 0,
        "aliasOrRedirect": False,
        "rejectReason": "",
        "providerWarnings": [],
    }
    if slug.lower() in {"*", "all", "any"}:
        base["status"] = "rejected"
        base["rejectReason"] = "wildcard_target_forbidden"
        return base

    market_payload = _safe_call(client, "fetch_market_by_slug", slug)
    market = _single_market_from_payload(market_payload, fallback_slug=slug)
    if market is not None:
        return _valid_result(base, market, source="gamma_market")

    event_payload = _safe_call(client, "fetch_event_by_slug", slug)
    event_result = _event_resolution_result(base, event_payload, input_slug=slug, source="gamma_event")
    if event_result is not None:
        return event_result

    pages_payload = _safe_pages_call(client, slug)
    if pages_payload is not None:
        event_from_pages, source_market_payload = pages_payload
        source_market = _single_market_from_payload(source_market_payload, fallback_slug=slug)
        if source_market is not None:
            return _valid_result(base, source_market, source="page_market")
        event_result = _event_resolution_result(base, event_from_pages, input_slug=slug, source="page_event")
        if event_result is not None:
            return event_result

    base["rejectReason"] = "provider_lookup_failed"
    return base


def _event_resolution_result(
    base: Mapping[str, object],
    payload: object,
    *,
    input_slug: str,
    source: str,
) -> dict[str, object] | None:
    if not isinstance(payload, Mapping):
        return None
    markets = payload.get("markets")
    if not isinstance(markets, Sequence) or isinstance(markets, (str, bytes)):
        return None
    market_count = len(markets)
    if market_count != 1:
        result = dict(base)
        result["status"] = "rejected"
        result["resolutionSource"] = source
        result["marketCount"] = market_count
        result["rejectReason"] = "target_exceeds_bounds_or_not_single_market" if market_count else "provider_lookup_failed"
        return result
    market = _single_market_from_payload(markets[0], fallback_slug=input_slug)
    if market is None:
        result = dict(base)
        result["status"] = "rejected"
        result["resolutionSource"] = source
        result["marketCount"] = 1
        result["rejectReason"] = "single_market_payload_missing_condition_id"
        return result
    market.setdefault("eventSlug", str(payload.get("slug") or input_slug))
    return _valid_result(base, market, source=source)


def _valid_result(base: Mapping[str, object], market: Mapping[str, object], *, source: str) -> dict[str, object]:
    slug = str(base.get("slug") or "")
    canonical = str(market.get("slug") or slug)
    result = dict(base)
    result.update(
        {
            "status": "valid_single_market",
            "resolutionSource": source,
            "canonicalMarketSlug": canonical,
            "conditionId": _condition_id(market),
            "marketCount": 1,
            "aliasOrRedirect": bool(canonical and canonical != slug),
            "rejectReason": "",
        }
    )
    return result


def _single_market_from_payload(payload: object, *, fallback_slug: str) -> dict[str, object] | None:
    if not isinstance(payload, Mapping):
        return None
    condition_id = _condition_id(payload)
    if not condition_id:
        return None
    market = dict(payload)
    market.setdefault("slug", fallback_slug)
    return market


def _condition_id(payload: Mapping[str, object]) -> str:
    for key in ("conditionId", "condition_id", "conditionID"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _safe_call(client: object, method_name: str, slug: str) -> object:
    method = getattr(client, method_name)
    try:
        return method(slug)
    except Exception:
        return None


def _safe_pages_call(client: object, slug: str) -> tuple[object, object] | None:
    method = getattr(client, "fetch_event_resolution_from_pages")
    try:
        payload = method(slug)
    except Exception:
        return None
    if isinstance(payload, tuple) and len(payload) == 2:
        return payload
    return None


def _candidate_list(registry: Mapping[str, object]) -> list[dict[str, object]]:
    candidates = registry.get("candidates")
    if not isinstance(candidates, list):
        return []
    return [dict(item) for item in candidates if isinstance(item, Mapping)]


def _skipped_result(candidate: Mapping[str, object], reason: str) -> dict[str, object]:
    return {
        "slug": str(candidate.get("slug") or ""),
        "candidateClassification": str(candidate.get("candidateClassification") or ""),
        "priority": int(candidate.get("priority") or 9999),
        "status": "skipped",
        "resolutionSource": "",
        "canonicalMarketSlug": "",
        "conditionId": "",
        "marketCount": 0,
        "aliasOrRedirect": False,
        "rejectReason": reason,
        "providerWarnings": [],
    }


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_if_requested(report: Mapping[str, object], output_json: str | Path | None) -> None:
    if output_json:
        write_preflight_output(report, output_json)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-json", required=True, help="Target registry JSON to resolve.")
    parser.add_argument("--output-json", required=True, help="Compact resolver preflight JSON output.")
    parser.add_argument("--max-candidates", type=int, default=10, help="Maximum live resolver checks.")
    parser.add_argument("--allow-live-network", action="store_true", help="Required for public read-only resolver calls.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = run_resolver_preflight(
        args.registry_json,
        output_json=args.output_json,
        max_candidates=args.max_candidates,
        allow_live_network=args.allow_live_network,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
