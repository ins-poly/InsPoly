from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FALSE_POSITIVE_DIR = Path("false_positive_library")
DEFAULT_QUALITY_DIR = Path("analyst_quality_outputs")
DEFAULT_OUTPUT_DIR = Path("false_positive_library")


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


def _string(value: Any) -> str:
    return str(value or "").strip()


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    return [value]


def discover_inputs(
    *,
    false_positive_library_path: Path | None = None,
    packet_quality_report_path: Path | None = None,
) -> dict[str, Path | None]:
    library_path = _resolve(false_positive_library_path) if false_positive_library_path else None
    quality_path = _resolve(packet_quality_report_path) if packet_quality_report_path else None
    return {
        "false_positive_library": library_path
        if library_path and library_path.exists()
        else _latest_file(DEFAULT_FALSE_POSITIVE_DIR, "false_positive_pattern_library_*.json"),
        "packet_quality_report": quality_path
        if quality_path and quality_path.exists()
        else _latest_file(DEFAULT_QUALITY_DIR, "packet_quality_report_*.json"),
    }


def _library_patterns(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    patterns = payload.get("patterns")
    if not isinstance(patterns, list):
        return {}
    result = {}
    for pattern in patterns:
        if isinstance(pattern, Mapping) and _string(pattern.get("pattern_key")):
            result[_string(pattern.get("pattern_key"))] = dict(pattern)
    return result


def _packet_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("packetQualityRows")
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def build_explanation_report(
    false_positive_library_payload: Mapping[str, Any],
    packet_quality_report_payload: Mapping[str, Any],
    *,
    input_paths: Mapping[str, Path | None] | None = None,
) -> dict[str, Any]:
    patterns = _library_patterns(false_positive_library_payload)
    packet_rows = _packet_rows(packet_quality_report_payload)
    packet_matches: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    packet_counter: Counter[str] = Counter()
    for row in packet_rows:
        matches = row.get("falsePositiveAdvisoryMatches")
        if not isinstance(matches, list):
            continue
        for match in matches:
            if not isinstance(match, Mapping):
                continue
            key = _string(match.get("pattern"))
            if not key:
                continue
            packet_counter.update([key])
            if len(packet_matches[key]) < 10:
                packet_matches[key].append(
                    {
                        "packetId": _string(row.get("packetId")) or "unknown",
                        "wallet": _string(row.get("wallet")) or "unknown",
                        "marketOrEvent": _string(row.get("marketOrEvent")) or "unknown",
                        "analystPriority": _string(row.get("analystPriority")) or "unknown",
                        "message": _string(match.get("message")),
                        "analystQuestion": _string(match.get("analystQuestion")),
                    }
                )
    library_summary = (
        false_positive_library_payload.get("summary")
        if isinstance(false_positive_library_payload.get("summary"), Mapping)
        else {}
    )
    library_counter = {
        _string(item.get("pattern_key")): int(item.get("observed_count") or 0)
        for item in _listify(library_summary.get("top_patterns"))
        if isinstance(item, Mapping) and _string(item.get("pattern_key"))
    }
    pattern_keys = sorted(set(patterns) | set(packet_counter) | set(library_counter))
    rows = []
    for key in pattern_keys:
        pattern = patterns.get(key, {})
        playbook = pattern.get("analyst_playbook") if isinstance(pattern.get("analyst_playbook"), Mapping) else {}
        rows.append(
            {
                "patternKey": key,
                "label": _string(pattern.get("label")) or key,
                "libraryObservedCount": int(pattern.get("observed_count") or library_counter.get(key, 0) or 0),
                "currentPacketMatchCount": int(packet_counter.get(key, 0)),
                "analystMeaning": _string(pattern.get("analyst_meaning") or playbook.get("packet_note")),
                "inspectNext": _string(playbook.get("inspect_next") or pattern.get("inspect_next")),
                "reviewQuestions": [str(item) for item in _listify(playbook.get("review_questions")) if _string(item)],
                "samplePacketMatches": packet_matches.get(key, []),
                "automaticActionAllowed": False,
                "falsePositiveLibraryUsedForScoring": False,
                "forbiddenUse": _string(pattern.get("forbidden_use"))
                or "Do not suppress, downgrade, reroute, rescore, or change eligibility from this advisory.",
                "safeAnalystUse": "Use as a checklist for manual source review and false-positive triage only.",
            }
        )
    rows.sort(key=lambda item: (-int(item.get("currentPacketMatchCount") or 0), -int(item.get("libraryObservedCount") or 0), str(item.get("patternKey") or "")))
    paths = input_paths or {}
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourceFalsePositiveLibraryPath": str(paths.get("false_positive_library") or ""),
        "sourcePacketQualityReportPath": str(paths.get("packet_quality_report") or ""),
        "summary": {
            "patternCount": len(rows),
            "packetCount": len(packet_rows),
            "packetsWithFalsePositiveAdvisoryMatches": sum(
                1 for row in packet_rows if row.get("falsePositiveAdvisoryMatches")
            ),
            "totalPacketPatternMatches": sum(packet_counter.values()),
            "automaticActionAllowed": False,
            "falsePositiveLibraryUsedForScoring": False,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
        },
        "patternRows": rows,
        "analystUse": [
            "Start with patterns that match many current packets.",
            "Use review questions to decide which packets need source verification before escalation.",
            "Treat high-volume, retrospective-only, and funding-unknown patterns as caution flags, not automatic suppressors.",
        ],
        "forbiddenUse": [
            "Do not automatically suppress or downgrade packets from this report.",
            "Do not change scores, gates, HER routing, funding eligibility, or candidate admission from this report.",
            "Do not treat saved-output-only patterns as fresh precision evidence.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# False-Positive Explanation Report",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Source false-positive library: {payload.get('sourceFalsePositiveLibraryPath', '')}",
        f"- Source packet quality report: {payload.get('sourcePacketQualityReportPath', '')}",
        f"- Patterns: {summary.get('patternCount', 0)}",
        f"- Packets with advisory matches: {summary.get('packetsWithFalsePositiveAdvisoryMatches', 0)}",
        f"- Automatic action allowed: {summary.get('automaticActionAllowed', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Pattern Rows",
    ]
    for row in payload.get("patternRows") or []:
        lines.extend(
            [
                f"- `{row.get('patternKey', '')}`: {row.get('label', '')}",
                f"  - current packet matches: {row.get('currentPacketMatchCount', 0)}",
                f"  - library observed count: {row.get('libraryObservedCount', 0)}",
                f"  - analyst meaning: {row.get('analystMeaning', '')}",
                f"  - inspect next: {row.get('inspectNext', '')}",
                f"  - forbidden use: {row.get('forbiddenUse', '')}",
            ]
        )
        questions = row.get("reviewQuestions") if isinstance(row.get("reviewQuestions"), list) else []
        for question in questions[:2]:
            lines.append(f"  - question: {question}")
    lines.extend(["", "## Analyst Use"])
    for item in payload.get("analystUse") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Forbidden Use"])
    for item in payload.get("forbiddenUse") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"false_positive_explanation_report_{stamp}.json"
    markdown_path = resolved / f"false_positive_explanation_report_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate advisory-only false-positive explanation report.")
    parser.add_argument("--false-positive-library", type=Path)
    parser.add_argument("--packet-quality-report", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    paths = discover_inputs(
        false_positive_library_path=args.false_positive_library,
        packet_quality_report_path=args.packet_quality_report,
    )
    payload = build_explanation_report(
        _load_json(paths["false_positive_library"]),
        _load_json(paths["packet_quality_report"]),
        input_paths=paths,
    )
    outputs = write_outputs(payload, args.output_dir)
    summary = payload.get("summary", {})
    print(f"False-positive explanation report JSON: {outputs['json_path']}")
    print(f"False-positive explanation report markdown: {outputs['markdown_path']}")
    print(f"Patterns: {summary.get('patternCount', 0)}")
    print(f"Packets with advisory matches: {summary.get('packetsWithFalsePositiveAdvisoryMatches', 0)}")
    print(f"Automatic action allowed: {summary.get('automaticActionAllowed', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
