from __future__ import annotations

import argparse
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


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _nested_health(performance: Mapping[str, Any]) -> Mapping[str, Any]:
    value = performance.get("funding_resolver_health")
    return value if isinstance(value, Mapping) else {}


def _perf_text(performance: Mapping[str, Any], *keys: str) -> str:
    health = _nested_health(performance)
    for key in keys:
        value = performance.get(key)
        if value:
            return _text(value)
        value = health.get(key)
        if value:
            return _text(value)
    return ""


def _classify_bottleneck(performance: Mapping[str, Any], summary: Mapping[str, Any]) -> str:
    funding = _number(performance.get("prefetch_funding_context_seconds"))
    collect = _number(performance.get("collect_event_trades_seconds"))
    wallet = _number(performance.get("prefetch_wallet_context_seconds"))
    resolve = _number(performance.get("resolve_input_seconds"))
    score = _number(performance.get("score_candidates_seconds"))
    funding_status = _perf_text(performance, "validationFundingStatus", "validation_funding_status")
    bundle_status = _perf_text(performance, "validationBundleStatus", "validation_bundle_status")
    abort_reason = _perf_text(performance, "validationAbortReason", "validation_abort_reason")
    if (
        funding_status in {"rpc_failure_limit_hit", "trace_timeout"}
        or bundle_status == "completed_funding_blocked"
        or "rpc_failure" in abort_reason
    ):
        return "funding_rpc_blocked"
    if funding >= max(collect, wallet, resolve, score, 1.0):
        return "funding_prefetch_dominant"
    if collect >= max(wallet, resolve, score, 1.0):
        return "event_trade_collection_dominant"
    if wallet >= max(resolve, score, 1.0):
        return "wallet_prefetch_dominant"
    if _number(summary.get("truncated_market_count")) > 0:
        return "truncated_market_collection_risk"
    return "no_single_large_bottleneck_observed"


def _audit_row(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    performance = payload.get("performance") if isinstance(payload.get("performance"), Mapping) else {}
    total = _number(performance.get("total_seconds"))
    funding = _number(performance.get("prefetch_funding_context_seconds"))
    collect = _number(performance.get("collect_event_trades_seconds"))
    wallet = _number(performance.get("prefetch_wallet_context_seconds"))
    score = _number(performance.get("score_candidates_seconds"))
    return {
        "runPath": str(path.parent),
        "eventAnalysisPath": str(path),
        "generatedAt": payload.get("generated_at", ""),
        "status": payload.get("status", ""),
        "eventSlug": _text(payload.get("parent_event_slug") or payload.get("selected_market_slug")),
        "analysisScope": payload.get("analysis_scope", ""),
        "rawTradeCount": int(summary.get("raw_trade_count") or 0),
        "candidateTradeCount": int(summary.get("candidate_trade_count") or 0),
        "displayTradeCount": int(summary.get("display_trade_count") or 0),
        "truncatedMarketCount": int(summary.get("truncated_market_count") or 0),
        "totalSeconds": total,
        "collectEventTradesSeconds": collect,
        "prefetchWalletContextSeconds": wallet,
        "prefetchFundingContextSeconds": funding,
        "scoreCandidatesSeconds": score,
        "fundingTraceCoverageRatio": _number(performance.get("funding_trace_coverage_ratio")),
        "validationBundleStatus": _perf_text(performance, "validationBundleStatus", "validation_bundle_status"),
        "validationFundingStatus": _perf_text(performance, "validationFundingStatus", "validation_funding_status"),
        "validationAbortReason": _perf_text(performance, "validationAbortReason", "validation_abort_reason"),
        "bottleneckClass": _classify_bottleneck(performance, summary),
        "modelBehaviorChanged": False,
    }


def build_audit(input_dir: Path = DEFAULT_INPUT_DIR, *, limit: int = 80) -> dict[str, Any]:
    root = _resolve(input_dir) or input_dir
    rows: list[dict[str, Any]] = []
    if root.exists():
        paths = sorted(root.glob("event_forensic_*/event_analysis.json"), key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
        for path in paths[:limit]:
            payload = _load_json(path)
            if payload:
                rows.append(_audit_row(path, payload))
    slow_rows = sorted(rows, key=lambda row: row.get("totalSeconds", 0), reverse=True)[:10]
    bottlenecks: dict[str, int] = {}
    for row in rows:
        key = str(row.get("bottleneckClass") or "unknown")
        bottlenecks[key] = bottlenecks.get(key, 0) + 1
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "event_forensic_performance_audit",
        "summary": {
            "runCount": len(rows),
            "slowRunCountOver120s": sum(1 for row in rows if _number(row.get("totalSeconds")) >= 120),
            "fundingRpcBlockedRunCount": sum(1 for row in rows if row.get("bottleneckClass") == "funding_rpc_blocked"),
            "truncatedRunCount": sum(1 for row in rows if int(row.get("truncatedMarketCount") or 0) > 0),
            "maxTotalSeconds": max((_number(row.get("totalSeconds")) for row in rows), default=0.0),
            "bottleneckClassCounts": bottlenecks,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
        },
        "slowestRuns": slow_rows,
        "runRows": rows,
        "recommendations": [
            "Keep performance work read-only until a specific bottleneck fix is approved.",
            "Separate RPC/funding stalls from trade-collection and wallet-context bottlenecks.",
            "Do not change scoring or candidate gates to make runs faster.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Event Forensic Performance Audit",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Runs inspected: {summary.get('runCount', 0)}",
        f"- Slow runs over 120s: {summary.get('slowRunCountOver120s', 0)}",
        f"- Funding/RPC blocked runs: {summary.get('fundingRpcBlockedRunCount', 0)}",
        f"- Truncated runs: {summary.get('truncatedRunCount', 0)}",
        f"- Max total seconds: {summary.get('maxTotalSeconds', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Slowest Runs",
    ]
    for row in payload.get("slowestRuns") or []:
        if isinstance(row, Mapping):
            lines.append(
                f"- `{row.get('eventSlug', '')}` total={row.get('totalSeconds', 0)}s "
                f"bottleneck={row.get('bottleneckClass', '')} path={row.get('eventAnalysisPath', '')}"
            )
    lines.extend(["", "## Recommendations"])
    for item in payload.get("recommendations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"event_forensic_performance_audit_{stamp}.json"
    markdown_path = resolved / f"event_forensic_performance_audit_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit saved event-forensic performance without changing detector behavior.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    payload = build_audit(args.input_dir)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Event forensic performance audit JSON: {outputs['json_path']}")
    print(f"Event forensic performance audit markdown: {outputs['markdown_path']}")
    print(f"Runs inspected: {payload.get('summary', {}).get('runCount', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
