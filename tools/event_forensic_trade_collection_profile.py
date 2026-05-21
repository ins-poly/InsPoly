from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = Path("event_forensic_outputs")
DEFAULT_OUTPUT_DIR = Path("event_forensic_performance_outputs")


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _load_json(path: Path | None) -> Any:
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _latest_paths(input_dir: Path, limit: int) -> list[Path]:
    root = _resolve(input_dir) or input_dir
    if not root.exists():
        return []
    paths = sorted(root.glob("event_forensic_*/event_analysis.json"), key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
    return paths[:limit]


def _condition_id_from_trade(trade: Mapping[str, Any]) -> str:
    return _text(trade.get("condition_id") or trade.get("conditionId") or trade.get("market") or trade.get("market_id"))


def _condition_id_from_market(market: Mapping[str, Any]) -> str:
    return _text(market.get("conditionId") or market.get("condition_id") or market.get("id"))


def _market_label(market: Mapping[str, Any]) -> str:
    return _text(market.get("question") or market.get("title") or market.get("slug") or market.get("conditionId"))


def _top_market_rows(bundle_dir: Path, limit: int = 8) -> tuple[list[dict[str, Any]], dict[str, int]]:
    trades_payload = _load_json(bundle_dir / "trades.json")
    event_markets_payload = _load_json(bundle_dir / "event_markets.json")
    analysis_markets_payload = _load_json(bundle_dir / "analysis_markets.json")
    trades = [_mapping(row) for row in _list(trades_payload)]
    event_markets = [_mapping(row) for row in _list(event_markets_payload)]
    analysis_markets = [_mapping(row) for row in _list(analysis_markets_payload)]
    market_by_condition = {
        condition: market
        for market in [*event_markets, *analysis_markets]
        if (condition := _condition_id_from_market(market))
    }
    counts = Counter(_condition_id_from_trade(trade) for trade in trades if _condition_id_from_trade(trade))
    top_rows: list[dict[str, Any]] = []
    for condition_id, trade_count in counts.most_common(limit):
        market = market_by_condition.get(condition_id, {})
        top_rows.append(
            {
                "conditionId": condition_id,
                "marketSlug": _text(market.get("slug")),
                "marketTitle": _market_label(market),
                "tradeCount": trade_count,
                "volumeNum": _number(market.get("volumeNum") or market.get("volume")),
                "closed": bool(market.get("closed")),
                "umaResolutionStatus": _text(market.get("umaResolutionStatus")),
            }
        )
    return top_rows, {
        "rawBundleTradeRows": len(trades),
        "rawBundleEventMarketRows": len(event_markets),
        "rawBundleAnalysisMarketRows": len(analysis_markets),
        "uniqueConditionIdsInRawTrades": len(counts),
    }


def _risk_class(row: Mapping[str, Any]) -> str:
    if not row.get("rawBundlePresent"):
        return "raw_bundle_missing"
    if _int(row.get("truncatedMarketCount")) > 0 and _number(row.get("collectEventTradesSeconds")) >= 30:
        return "truncated_collection_high_cost"
    if _int(row.get("truncatedMarketCount")) > 0:
        return "truncated_collection_risk"
    if _number(row.get("secondsPerAnalysisMarket")) >= 15:
        return "slow_per_market_collection"
    if _int(row.get("singleMarketSiblingContextCount")) > 0:
        return "single_market_sibling_context_reporting_risk"
    return "collection_profile_normal"


def _profile_row(path: Path) -> dict[str, Any]:
    payload = _mapping(_load_json(path))
    summary = _mapping(payload.get("summary"))
    performance = _mapping(payload.get("performance"))
    bundle_dir = path.parent / "raw_event_bundle"
    top_rows, raw_counts = _top_market_rows(bundle_dir)
    analysis_market_count = _int(summary.get("analysis_market_count") or len(payload.get("markets") or []))
    total_event_market_count = _int(summary.get("total_event_market_count"))
    raw_trade_count = _int(summary.get("raw_trade_count"))
    collect_seconds = _number(performance.get("collect_event_trades_seconds"))
    selected_condition = _text(payload.get("selected_condition_id"))
    row = {
        "runPath": str(path.parent),
        "eventAnalysisPath": str(path),
        "rawBundlePath": str(bundle_dir) if bundle_dir.exists() else "",
        "rawBundlePresent": bundle_dir.exists(),
        "generatedAt": payload.get("generated_at", ""),
        "status": payload.get("status", ""),
        "eventSlug": _text(payload.get("parent_event_slug") or payload.get("selected_market_slug")),
        "eventTitle": _text(_mapping(payload.get("event")).get("title") or payload.get("selected_market_title")),
        "analysisScope": _text(payload.get("analysis_scope")),
        "selectedConditionIdPresent": bool(selected_condition),
        "analysisMarketCount": analysis_market_count,
        "totalEventMarketCount": total_event_market_count,
        "singleMarketSiblingContextCount": max(total_event_market_count - analysis_market_count, 0) if selected_condition else 0,
        "truncatedMarketCount": _int(summary.get("truncated_market_count") or performance.get("truncated_market_count")),
        "rawTradeCount": raw_trade_count,
        "candidateTradeCount": _int(summary.get("candidate_trade_count")),
        "belowThresholdCandidateCount": _int(summary.get("below_threshold_candidate_count")),
        "collectEventTradesSeconds": collect_seconds,
        "marketFetchWorkers": _int(performance.get("market_fetch_workers")),
        "secondsPerAnalysisMarket": round(collect_seconds / max(analysis_market_count, 1), 4),
        "rawTradesPerSecond": round(raw_trade_count / collect_seconds, 4) if collect_seconds > 0 else 0,
        **raw_counts,
        "topMarketsByRawTradeCount": top_rows,
        "modelBehaviorChanged": False,
    }
    row["collectionRiskClass"] = _risk_class(row)
    return row


def build_profile(input_dir: Path = DEFAULT_INPUT_DIR, *, limit: int = 100) -> dict[str, Any]:
    rows = [_profile_row(path) for path in _latest_paths(input_dir, limit)]
    risk_counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("collectionRiskClass") or "unknown")
        risk_counts[key] = risk_counts.get(key, 0) + 1
    highest_cost = sorted(rows, key=lambda row: _number(row.get("collectEventTradesSeconds")), reverse=True)[:12]
    truncation_rows = [row for row in rows if _int(row.get("truncatedMarketCount")) > 0]
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "event_forensic_trade_collection_profile",
        "summary": {
            "runCount": len(rows),
            "rawBundlePresentRunCount": sum(1 for row in rows if row.get("rawBundlePresent")),
            "truncatedRunCount": len(truncation_rows),
            "slowCollectionRunCountOver30s": sum(1 for row in rows if _number(row.get("collectEventTradesSeconds")) >= 30),
            "singleMarketSiblingContextRunCount": sum(1 for row in rows if _int(row.get("singleMarketSiblingContextCount")) > 0),
            "maxCollectEventTradesSeconds": max((_number(row.get("collectEventTradesSeconds")) for row in rows), default=0.0),
            "riskClassCounts": risk_counts,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
        },
        "highestCostRuns": highest_cost,
        "truncationRows": truncation_rows[:30],
        "profileRows": rows,
        "recommendations": [
            "Use this profile to prioritize reporting/instrumentation work only.",
            "Do not reduce market scope, candidate scope, or thresholds to improve runtime.",
            "If collection remains expensive, add progress visibility before changing fetch behavior.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = _mapping(payload.get("summary"))
    lines = [
        "# Event Forensic Trade Collection Profile",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Runs inspected: {summary.get('runCount', 0)}",
        f"- Raw bundle present runs: {summary.get('rawBundlePresentRunCount', 0)}",
        f"- Truncated runs: {summary.get('truncatedRunCount', 0)}",
        f"- Slow collection runs over 30s: {summary.get('slowCollectionRunCountOver30s', 0)}",
        f"- Single-market sibling-context runs: {summary.get('singleMarketSiblingContextRunCount', 0)}",
        f"- Max collect-event-trades seconds: {summary.get('maxCollectEventTradesSeconds', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Highest Collection Cost Runs",
    ]
    for row in _list(payload.get("highestCostRuns")):
        if isinstance(row, Mapping):
            lines.append(
                f"- `{row.get('eventSlug', '')}` scope={row.get('analysisScope', '')} "
                f"collect={row.get('collectEventTradesSeconds', 0)}s "
                f"truncated={row.get('truncatedMarketCount', 0)} "
                f"risk={row.get('collectionRiskClass', '')} path={row.get('eventAnalysisPath', '')}"
            )
    lines.extend(["", "## Recommendations"])
    for item in _list(payload.get("recommendations")):
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"event_forensic_trade_collection_profile_{stamp}.json"
    markdown_path = resolved / f"event_forensic_trade_collection_profile_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a reporting-only profile of saved event-forensic trade collection cost and truncation risk.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    payload = build_profile(args.input_dir, limit=args.limit)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Event forensic trade collection profile JSON: {outputs['json_path']}")
    print(f"Event forensic trade collection profile markdown: {outputs['markdown_path']}")
    print(f"Runs inspected: {payload.get('summary', {}).get('runCount', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
