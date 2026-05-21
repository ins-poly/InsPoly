from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = Path("event_forensic_outputs")
DEFAULT_OUTPUT_DIR = Path("event_forensic_scope_outputs")


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


def _text(value: Any) -> str:
    return str(value or "").strip()


def _scope_risk(payload: Mapping[str, Any], summary: Mapping[str, Any]) -> str:
    selected_condition = bool(_text(payload.get("selected_condition_id")))
    total_event_markets = int(summary.get("total_event_market_count") or 0)
    analysis_markets = int(summary.get("analysis_market_count") or 0)
    truncated = int(summary.get("truncated_market_count") or 0)
    note = _text(payload.get("scope_note") or payload.get("display_note"))
    if selected_condition and total_event_markets > analysis_markets:
        return "single_market_with_sibling_context"
    if truncated > 0:
        return "truncated_event_collection"
    if not note:
        return "missing_scope_note"
    return "scope_semantics_visible"


def build_audit(input_dir: Path = DEFAULT_INPUT_DIR, *, limit: int = 100) -> dict[str, Any]:
    root = _resolve(input_dir) or input_dir
    rows: list[dict[str, Any]] = []
    if root.exists():
        paths = sorted(root.glob("event_forensic_*/event_analysis.json"), key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
        for path in paths[:limit]:
            payload = _load_json(path)
            if not payload:
                continue
            summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
            rows.append(
                {
                    "eventAnalysisPath": str(path),
                    "eventSlug": _text(payload.get("parent_event_slug") or payload.get("selected_market_slug")),
                    "analysisScope": _text(payload.get("analysis_scope")),
                    "selectedConditionIdPresent": bool(_text(payload.get("selected_condition_id"))),
                    "selectedMarketSlug": _text(payload.get("selected_market_slug")),
                    "analysisMarketCount": int(summary.get("analysis_market_count") or 0),
                    "totalEventMarketCount": int(summary.get("total_event_market_count") or 0),
                    "uniqueMarketCount": int(summary.get("unique_market_count") or 0),
                    "truncatedMarketCount": int(summary.get("truncated_market_count") or 0),
                    "scopeNotePresent": bool(_text(payload.get("scope_note") or payload.get("display_note"))),
                    "scopeRiskClass": _scope_risk(payload, summary),
                    "modelBehaviorChanged": False,
                }
            )
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("scopeRiskClass") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "event_forensic_scope_semantics_audit",
        "summary": {
            "runCount": len(rows),
            "singleMarketWithSiblingContextCount": counts.get("single_market_with_sibling_context", 0),
            "truncatedEventCollectionCount": counts.get("truncated_event_collection", 0),
            "missingScopeNoteCount": counts.get("missing_scope_note", 0),
            "scopeRiskClassCounts": counts,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
        },
        "scopeRows": rows,
        "recommendations": [
            "Keep single-market condition_id scope strict.",
            "Use this audit to improve UI/report warnings only; do not broaden event scope automatically.",
            "If a user wants sibling markets primary, run whole-event analysis explicitly.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Event Forensic Scope Semantics Audit",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Runs inspected: {summary.get('runCount', 0)}",
        f"- Single-market with sibling context: {summary.get('singleMarketWithSiblingContextCount', 0)}",
        f"- Truncated event collections: {summary.get('truncatedEventCollectionCount', 0)}",
        f"- Missing scope notes: {summary.get('missingScopeNoteCount', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Scope Rows",
    ]
    for row in (payload.get("scopeRows") or [])[:50]:
        if isinstance(row, Mapping):
            lines.append(
                f"- `{row.get('eventSlug', '')}` risk={row.get('scopeRiskClass', '')} "
                f"analysisMarkets={row.get('analysisMarketCount', 0)}/{row.get('totalEventMarketCount', 0)}"
            )
    lines.extend(["", "## Recommendations"])
    for item in payload.get("recommendations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"event_forensic_scope_semantics_audit_{stamp}.json"
    markdown_path = resolved / f"event_forensic_scope_semantics_audit_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit saved event-forensic scope semantics without changing scope behavior.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    payload = build_audit(args.input_dir)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Event forensic scope audit JSON: {outputs['json_path']}")
    print(f"Event forensic scope audit markdown: {outputs['markdown_path']}")
    print(f"Runs inspected: {payload.get('summary', {}).get('runCount', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
