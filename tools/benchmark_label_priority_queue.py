from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = Path("known_case_benchmarks")
DEFAULT_OUTPUT_DIR = Path("known_case_benchmarks")


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


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _observed(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("observedLabels")
    return value if isinstance(value, Mapping) else {}


def _priority(row: Mapping[str, Any]) -> tuple[int, list[str]]:
    observed = _observed(row)
    reasons: list[str] = []
    score = 0
    if bool(observed.get("overlap")):
        score += 45
        reasons.append("Strong Risk and HER overlap needs early human interpretation.")
    if bool(observed.get("strongRisk")):
        score += 35
        reasons.append("Strong Risk packet is high-value for detector expectation labeling.")
    if bool(observed.get("hardEvidenceReview")):
        score += 30
        reasons.append("HER packet helps validate evidence-routing expectations.")
    suspicious_count = _int(observed.get("forensicSuspiciousTradeCount"))
    primary_count = _int(observed.get("primaryReviewTradeCount"))
    her_count = _int(observed.get("hardEvidenceReviewTradeCount"))
    truncated = _int(observed.get("truncatedMarketCount"))
    if suspicious_count:
        score += min(35, 15 + suspicious_count)
        reasons.append(f"Saved event run has {suspicious_count} suspicious trades.")
    if primary_count:
        score += min(25, 10 + primary_count)
        reasons.append(f"Saved event run has {primary_count} primary-review trades.")
    if her_count:
        score += min(25, 10 + her_count)
        reasons.append(f"Saved event run has {her_count} HER trades.")
    if truncated:
        score += 10
        reasons.append("Truncated collection should be labeled with evidence limitations in mind.")
    source_type = str(row.get("sourceType") or "")
    if source_type == "unique_review_packet":
        score += 8
        reasons.append("Packet row is closer to analyst case review than event-level count rows.")
    elif source_type == "event_forensic_run":
        score += 5
        reasons.append("Event-run row helps validate run-level scope/count expectations.")
    if not str(row.get("wallet") or ""):
        score -= 3
        reasons.append("No wallet on row; label as event/run expectation rather than wallet disposition.")
    if not reasons:
        reasons.append("Baseline saved-output row; label only after higher-signal rows.")
    return score, reasons


def _priority_class(score: int) -> str:
    if score >= 55:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def build_queue(payload: Mapping[str, Any], *, source_path: Path | None = None, limit: int = 30) -> dict[str, Any]:
    raw_rows = payload.get("labelRows") if isinstance(payload.get("labelRows"), list) else []
    scored: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, Mapping):
            continue
        labels = row.get("labelFields") if isinstance(row.get("labelFields"), Mapping) else {}
        if any(str(labels.get(field) or "").strip() for field in ("expectedAnalystDisposition", "humanLabelConfidence")):
            continue
        score, reasons = _priority(row)
        scored.append(
            {
                "localCaseId": row.get("localCaseId", ""),
                "sourceType": row.get("sourceType", ""),
                "sourceArtifact": row.get("sourceArtifact", ""),
                "eventSlug": row.get("eventSlug", ""),
                "market": row.get("market", ""),
                "conditionId": row.get("conditionId", ""),
                "wallet": row.get("wallet", ""),
                "observedLabels": dict(_observed(row)),
                "labelPriorityScore": score,
                "priorityClass": _priority_class(score),
                "priorityReasons": reasons,
                "recommendedHumanQuestion": (
                    "Should this saved-output row be labeled likely_false_positive, plausible_insider_style, "
                    "needs_fresh_validation, inconclusive, reporting_only_control, or ignore_not_benchmark?"
                ),
                "allowedUse": "manual_label_queue_only",
                "forbiddenUse": "Do not use this priority queue as scoring, suppression, gate, HER, funding, or candidate-admission logic.",
                "modelBehaviorChanged": False,
            }
        )
    scored.sort(
        key=lambda item: (
            -int(item.get("labelPriorityScore") or 0),
            str(item.get("sourceType") or ""),
            str(item.get("localCaseId") or ""),
        )
    )
    def append_candidates(target: list[dict[str, Any]], candidates: Sequence[dict[str, Any]], desired_count: int) -> None:
        seen_ids = {str(existing.get("localCaseId") or "") for existing in target}
        seen_keys: dict[str, int] = {}
        for existing in target:
            key = f"{existing.get('wallet') or 'event-run'}::{existing.get('conditionId') or existing.get('market') or existing.get('eventSlug')}"
            seen_keys[key] = seen_keys.get(key, 0) + 1
        for candidate in candidates:
            if len(target) >= desired_count:
                break
            case_id = str(candidate.get("localCaseId") or "")
            if case_id in seen_ids:
                continue
            key = (
                f"{candidate.get('wallet') or 'event-run'}::"
                f"{candidate.get('conditionId') or candidate.get('market') or candidate.get('eventSlug')}"
            )
            count = seen_keys.get(key, 0)
            if count >= 3 and len(target) >= max(10, limit // 2):
                continue
            seen_ids.add(case_id)
            seen_keys[key] = count + 1
            target.append(dict(candidate))

    packet_candidates = [row for row in scored if row.get("sourceType") == "unique_review_packet"]
    event_candidates = [row for row in scored if row.get("sourceType") == "event_forensic_run"]
    queue: list[dict[str, Any]] = []
    if packet_candidates and event_candidates and limit >= 10:
        append_candidates(queue, packet_candidates, min(len(packet_candidates), max(5, limit // 3)))
        append_candidates(queue, event_candidates, len(queue) + min(len(event_candidates), max(5, limit // 3)))
    append_candidates(queue, scored, limit)
    ranked_queue = []
    for item in sorted(
        queue,
        key=lambda row: (
            -int(row.get("labelPriorityScore") or 0),
            str(row.get("sourceType") or ""),
            str(row.get("localCaseId") or ""),
        ),
    )[:limit]:
        key = f"{item.get('wallet') or 'event-run'}::{item.get('conditionId') or item.get('market') or item.get('eventSlug')}"
        item = dict(item)
        item["dedupeLabelKey"] = key
        item["queueRank"] = len(ranked_queue) + 1
        ranked_queue.append(item)
    queue = ranked_queue
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_label_priority_queue",
        "sourceWorkbenchPath": str(source_path or ""),
        "summary": {
            "sourceRowCount": len(raw_rows),
            "queueRowCount": len(queue),
            "highPriorityRowCount": sum(1 for row in queue if row.get("priorityClass") == "high"),
            "mediumPriorityRowCount": sum(1 for row in queue if row.get("priorityClass") == "medium"),
            "eventRunRowCount": sum(1 for row in queue if row.get("sourceType") == "event_forensic_run"),
            "packetRowCount": sum(1 for row in queue if row.get("sourceType") == "unique_review_packet"),
            "uniqueWalletCount": len({str(row.get("wallet") or "") for row in queue if row.get("wallet")}),
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "priorityRows": queue,
        "limitations": [
            "This queue prioritizes human labeling effort only.",
            "It does not assign labels.",
            "It does not change production detector behavior.",
            "Rows remain saved-output/cache-only evidence until separately validated.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Benchmark Label Priority Queue",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Source rows: {summary.get('sourceRowCount', 0)}",
        f"- Queue rows: {summary.get('queueRowCount', 0)}",
        f"- High priority rows: {summary.get('highPriorityRowCount', 0)}",
        f"- Packet rows: {summary.get('packetRowCount', 0)}",
        f"- Event-run rows: {summary.get('eventRunRowCount', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Queue",
    ]
    for row in payload.get("priorityRows") or []:
        if isinstance(row, Mapping):
            label = row.get("eventSlug") or row.get("market") or "unknown"
            lines.append(
                f"- #{row.get('queueRank', '')} `{row.get('localCaseId', '')}` "
                f"{row.get('priorityClass', '')} score={row.get('labelPriorityScore', 0)}: "
                f"{label} / {row.get('wallet') or 'event-run'}"
            )
            reasons = row.get("priorityReasons") if isinstance(row.get("priorityReasons"), list) else []
            if reasons:
                lines.append(f"  - why: {reasons[0]}")
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def _write_csv(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    fieldnames = [
        "queueRank",
        "localCaseId",
        "priorityClass",
        "labelPriorityScore",
        "sourceType",
        "eventSlug",
        "market",
        "conditionId",
        "wallet",
        "priorityReasons",
        "recommendedHumanQuestion",
        "sourceArtifact",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"benchmark_label_priority_queue_{stamp}.json"
    markdown_path = resolved / f"benchmark_label_priority_queue_{stamp}.md"
    csv_path = resolved / f"benchmark_label_priority_queue_{stamp}.csv"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    _write_csv([row for row in payload.get("priorityRows", []) if isinstance(row, Mapping)], csv_path)
    return {"json_path": str(json_path), "markdown_path": str(markdown_path), "csv_path": str(csv_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a reporting-only priority queue for human benchmark labeling.")
    parser.add_argument("--workbench", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args(argv)
    source = args.workbench or _latest_file(DEFAULT_INPUT_DIR, "benchmark_labeling_workbench_*.json")
    payload = build_queue(_load_json(source), source_path=source, limit=args.limit)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Benchmark label priority queue JSON: {outputs['json_path']}")
    print(f"Benchmark label priority queue markdown: {outputs['markdown_path']}")
    print(f"Benchmark label priority queue CSV: {outputs['csv_path']}")
    print(f"Queue rows: {payload.get('summary', {}).get('queueRowCount', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
