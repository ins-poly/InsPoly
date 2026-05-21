from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = Path("event_forensic_performance_outputs")
DEFAULT_OUTPUT_DIR = Path("rfcs")


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _latest_file(directory: Path, pattern: str) -> Path | None:
    root = _resolve(directory) or directory
    if not root.exists():
        return None
    candidates = sorted(root.glob(pattern), key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
    return candidates[0] if candidates else None


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def build_rfc(audit_payload: Mapping[str, Any], *, source_path: Path | None = None) -> dict[str, Any]:
    summary = audit_payload.get("summary") if isinstance(audit_payload.get("summary"), Mapping) else {}
    bottlenecks = summary.get("bottleneckClassCounts") if isinstance(summary.get("bottleneckClassCounts"), Mapping) else {}
    proposals = [
        {
            "proposalId": "PERF-001",
            "title": "Separate event trade collection from scoring in progress reports",
            "bottleneckClass": "event_trade_collection_dominant",
            "observedRunCount": int(bottlenecks.get("event_trade_collection_dominant") or 0),
            "allowedImplementation": "reporting_or_instrumentation_only",
            "wouldChangeDetectorBehavior": False,
            "risk": "low",
            "acceptanceCriteria": "Saved reports expose trade-collection timing and truncation warnings without changing candidate inclusion.",
        },
        {
            "proposalId": "PERF-002",
            "title": "Bound funding prefetch diagnostics before validation expansion",
            "bottleneckClass": "funding_rpc_blocked",
            "observedRunCount": int(summary.get("fundingRpcBlockedRunCount") or 0),
            "allowedImplementation": "diagnostic_only_until_rpc_capacity_is_approved",
            "wouldChangeDetectorBehavior": False,
            "risk": "medium",
            "acceptanceCriteria": "Funding/RPC stalls are reported as validation blockers, not as absence of suspicious funding.",
        },
        {
            "proposalId": "PERF-003",
            "title": "Wallet-context latency instrumentation",
            "bottleneckClass": "wallet_prefetch_dominant",
            "observedRunCount": int(bottlenecks.get("wallet_prefetch_dominant") or 0),
            "allowedImplementation": "instrumentation_only",
            "wouldChangeDetectorBehavior": False,
            "risk": "low",
            "acceptanceCriteria": "Wallet prefetch timing is visible by run and does not alter wallet scoring or suppressors.",
        },
    ]
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "event_forensic_performance_rfc",
        "sourcePerformanceAuditPath": str(source_path or ""),
        "summary": {
            "proposalCount": len(proposals),
            "sourceRunCount": summary.get("runCount", 0),
            "slowRunCountOver120s": summary.get("slowRunCountOver120s", 0),
            "fundingRpcBlockedRunCount": summary.get("fundingRpcBlockedRunCount", 0),
            "truncatedRunCount": summary.get("truncatedRunCount", 0),
            "implementationApproved": False,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
        },
        "proposals": proposals,
        "forbiddenImplementation": [
            "Do not reduce candidate scope to improve runtime.",
            "Do not change Strong Risk gates, scoring weights, HER routing, funding eligibility, or structural thresholds.",
            "Do not treat RPC failures as no suspicious funding.",
        ],
        "readyToCopyNextPrompt": "Implement only PERF-001 reporting/instrumentation if approved. Do not change detector behavior.",
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Event Forensic Performance RFC",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Source runs: {summary.get('sourceRunCount', 0)}",
        f"- Slow runs over 120s: {summary.get('slowRunCountOver120s', 0)}",
        f"- Funding/RPC blocked runs: {summary.get('fundingRpcBlockedRunCount', 0)}",
        f"- Implementation approved: {summary.get('implementationApproved', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Proposals",
    ]
    for proposal in payload.get("proposals") or []:
        if isinstance(proposal, Mapping):
            lines.append(
                f"- `{proposal.get('proposalId', '')}` {proposal.get('title', '')}: "
                f"{proposal.get('allowedImplementation', '')}; observed={proposal.get('observedRunCount', 0)}"
            )
    lines.extend(["", "## Forbidden Implementation"])
    for item in payload.get("forbiddenImplementation") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"EVENT_FORENSIC_PERFORMANCE_RFC_{stamp}.json"
    markdown_path = resolved / f"EVENT_FORENSIC_PERFORMANCE_RFC_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draft an RFC-only event forensic performance proposal from saved audit outputs.")
    parser.add_argument("--audit", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    source = args.audit or _latest_file(DEFAULT_INPUT_DIR, "event_forensic_performance_audit_*.json")
    payload = build_rfc(_load_json(source), source_path=source)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Performance RFC JSON: {outputs['json_path']}")
    print(f"Performance RFC markdown: {outputs['markdown_path']}")
    print(f"Proposals: {payload.get('summary', {}).get('proposalCount', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
