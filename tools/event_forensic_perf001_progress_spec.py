from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = Path("event_forensic_performance_outputs")
DEFAULT_OUTPUT_DIR = Path("event_forensic_performance_outputs")


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


def _summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("summary")
    return value if isinstance(value, Mapping) else {}


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def build_spec(profile_payload: Mapping[str, Any], *, source_path: Path | None = None) -> dict[str, Any]:
    summary = _summary(profile_payload)
    truncated_runs = _int(summary.get("truncatedRunCount"))
    slow_runs = _int(summary.get("slowCollectionRunCountOver30s"))
    run_count = _int(summary.get("runCount"))
    priority = "high" if truncated_runs >= max(1, run_count // 2) or slow_runs > 0 else "medium"
    progress_fields = [
        {
            "field": "tradeCollectionStage",
            "type": "string",
            "source": "event_forensic collection loop",
            "purpose": "Separate resolve, trade collection, wallet prefetch, funding prefetch, scoring, and report assembly in the UI.",
        },
        {
            "field": "analysisMarketTotal",
            "type": "integer",
            "source": "resolved analysis market list",
            "purpose": "Show how many primary markets are in scope without broadening the scope.",
        },
        {
            "field": "analysisMarketCompleted",
            "type": "integer",
            "source": "trade collection completion counter",
            "purpose": "Give the analyst a real progress denominator during collection.",
        },
        {
            "field": "truncatedMarketCountSoFar",
            "type": "integer",
            "source": "existing pagination cap detection",
            "purpose": "Surface truncation as it happens instead of only after the report is saved.",
        },
        {
            "field": "rawTradeRowsCollectedSoFar",
            "type": "integer",
            "source": "in-memory collected trade list length",
            "purpose": "Show whether the run is collecting evidence or stalled.",
        },
        {
            "field": "lastCollectedMarketSlug",
            "type": "string",
            "source": "current market payload",
            "purpose": "Help diagnose which market family is slow without exposing secrets.",
        },
        {
            "field": "collectionElapsedSeconds",
            "type": "number",
            "source": "perf_counter at collection start",
            "purpose": "Make slow collection visible before the global timeout.",
        },
        {
            "field": "collectionRiskClass",
            "type": "enum",
            "source": "reporting-only classification from saved counters",
            "purpose": "Flag truncation/high-cost risk without changing detector behavior.",
        },
        {
            "field": "singleMarketSiblingContextCount",
            "type": "integer",
            "source": "event and analysis market counts",
            "purpose": "Clarify when a strict single-market run has sibling context available but not primary-scored.",
        },
    ]
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "event_forensic_perf001_progress_spec",
        "sourceTradeCollectionProfilePath": str(source_path or ""),
        "summary": {
            "sourceRunCount": run_count,
            "sourceTruncatedRunCount": truncated_runs,
            "sourceSlowCollectionRunCountOver30s": slow_runs,
            "implementationPriority": priority,
            "proposedFieldCount": len(progress_fields),
            "implementationApproved": False,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
        },
        "proposedProgressFields": progress_fields,
        "likelyFilesIfApproved": [
            "app/event_forensic.py",
            "app/browser_event_forensic_ui.html",
            "app/event_forensic_desktop.py",
            "tests/test_scanner_patterns.py or a focused reporting test file",
        ],
        "acceptanceCriteria": [
            "Progress/status payloads expose market collection counters and truncation count without changing analysis scope.",
            "Saved performance/report fields remain additive and legacy reports still load.",
            "No scoring, gate, HER, funding eligibility, or candidate-admission fields are changed.",
            "Runtime profile text includes the new reporting counters when available and tolerates missing legacy fields.",
        ],
        "forbiddenImplementation": [
            "Do not skip markets or reduce collection scope to improve the progress percentage.",
            "Do not lower thresholds, alter Strong Risk gates, or change HER/funding eligibility.",
            "Do not treat truncation as absence of suspicious behavior.",
        ],
        "readyToCopyPrompt": (
            "Implement PERF-001 progress/reporting instrumentation only: add additive trade-collection progress counters "
            "and saved report fields from rfcs/event_forensic_perf001_progress_spec outputs. Preserve scoring, gates, "
            "strict condition_id scope, HER routing, funding eligibility, candidate admission, and legacy output loading."
        ),
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = _summary(payload)
    lines = [
        "# Event Forensic PERF-001 Progress Spec",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Source runs: {summary.get('sourceRunCount', 0)}",
        f"- Source truncated runs: {summary.get('sourceTruncatedRunCount', 0)}",
        f"- Source slow collection runs over 30s: {summary.get('sourceSlowCollectionRunCountOver30s', 0)}",
        f"- Implementation priority: {summary.get('implementationPriority', '')}",
        f"- Implementation approved: {summary.get('implementationApproved', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Proposed Progress Fields",
    ]
    for item in payload.get("proposedProgressFields") or []:
        if isinstance(item, Mapping):
            lines.append(f"- `{item.get('field', '')}` ({item.get('type', '')}): {item.get('purpose', '')}")
    lines.extend(["", "## Acceptance Criteria"])
    for item in payload.get("acceptanceCriteria") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Forbidden Implementation"])
    for item in payload.get("forbiddenImplementation") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"event_forensic_perf001_progress_spec_{stamp}.json"
    markdown_path = resolved / f"event_forensic_perf001_progress_spec_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a reporting-only PERF-001 progress instrumentation spec from trade collection profiles.")
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    source = args.profile or _latest_file(DEFAULT_INPUT_DIR, "event_forensic_trade_collection_profile_*.json")
    payload = build_spec(_load_json(source), source_path=source)
    outputs = write_outputs(payload, args.output_dir)
    print(f"PERF-001 progress spec JSON: {outputs['json_path']}")
    print(f"PERF-001 progress spec markdown: {outputs['markdown_path']}")
    print(f"Proposed fields: {payload.get('summary', {}).get('proposedFieldCount', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
