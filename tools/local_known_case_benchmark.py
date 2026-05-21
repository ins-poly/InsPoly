from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("known_case_benchmarks")
REVIEW_PACKET_DIR = Path("review_packets")
EVENT_FORENSIC_DIR = Path("event_forensic_outputs")


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


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _event_rows_from_packets(packet_path: Path | None, payload: Mapping[str, Any], *, limit: int = 80) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    packets = _as_list(payload.get("packets"))
    for index, packet in enumerate(packets[:limit], start=1):
        if not isinstance(packet, Mapping):
            continue
        source_navigation = packet.get("source_navigation") if isinstance(packet.get("source_navigation"), Mapping) else {}
        flags = packet.get("flags") if isinstance(packet.get("flags"), Mapping) else {}
        raw = packet.get("rawMetrics") or packet.get("raw_metrics")
        raw_metrics = raw if isinstance(raw, Mapping) else {}
        event_slug = _first_text(
            packet.get("eventSlug"),
            packet.get("event_slug"),
            source_navigation.get("event_slug"),
            raw_metrics.get("event_slug"),
            raw_metrics.get("parent_event_slug"),
        )
        market = _first_text(packet.get("market"), packet.get("marketTitle"), packet.get("title"), raw_metrics.get("market_title"))
        wallet = _first_text(packet.get("wallet"), packet.get("trader"), packet.get("proxyWallet"), raw_metrics.get("wallet"))
        condition_id = _first_text(
            packet.get("conditionId"), packet.get("condition_id"), source_navigation.get("condition_id"), raw_metrics.get("condition_id")
        )
        if not any([event_slug, market, wallet, condition_id]):
            continue
        strong = bool(packet.get("strongRisk") or packet.get("strong_risk") or packet.get("isStrongRisk"))
        her = bool(packet.get("hardEvidenceReview") or packet.get("hard_evidence_review") or packet.get("isHardEvidenceReview"))
        rows.append(
            {
                "localCaseId": f"LOCAL-PACKET-{index:04d}",
                "sourceArtifact": str(packet_path or ""),
                "sourceType": "unique_review_packet",
                "benchmarkStatus": "candidate_needs_human_label",
                "eventSlug": event_slug,
                "market": market,
                "conditionId": condition_id,
                "wallet": wallet,
                "observedLabels": {
                    "strongRisk": strong,
                    "hardEvidenceReview": her,
                    "overlap": strong and her,
                    "severity": _first_text(packet.get("severity"), packet.get("riskLevel"), packet.get("risk_level")),
                },
                "evidenceClass": "saved_output_only",
                "whyUseful": "Local saved packet can become a benchmark row after a human assigns expected behavior.",
                "forbiddenUse": "Do not train, tune, suppress, rescore, or change gates from this scaffold without human labels and fresh validation.",
                "modelBehaviorChanged": False,
            }
        )
    return rows


def _event_rows_from_forensic_outputs(root: Path, *, limit: int = 60) -> list[dict[str, Any]]:
    resolved = _resolve(root) or root
    rows: list[dict[str, Any]] = []
    if not resolved.exists():
        return rows
    directories = sorted(resolved.glob("event_forensic_*"), key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
    for directory in directories[:limit]:
        path = directory / "event_analysis.json"
        payload = _load_json(path)
        if not payload:
            continue
        event = payload.get("event") if isinstance(payload.get("event"), Mapping) else {}
        summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
        performance = payload.get("performance") if isinstance(payload.get("performance"), Mapping) else {}
        row_id = f"LOCAL-EVENT-{len(rows) + 1:04d}"
        rows.append(
            {
                "localCaseId": row_id,
                "sourceArtifact": str(path),
                "sourceType": "event_forensic_run",
                "benchmarkStatus": "run_needs_human_expected_outcome_label",
                "eventSlug": _first_text(payload.get("parent_event_slug"), event.get("slug"), payload.get("selected_market_slug")),
                "market": _first_text(payload.get("selected_market_title"), event.get("title"), payload.get("selected_market_slug")),
                "conditionId": _first_text(payload.get("selected_condition_id")),
                "wallet": "",
                "observedLabels": {
                    "forensicSuspiciousTradeCount": int(summary.get("forensic_suspicious_trade_count") or 0),
                    "primaryReviewTradeCount": int(summary.get("primary_review_trade_count") or 0),
                    "hardEvidenceReviewTradeCount": int(summary.get("hard_evidence_review_trade_count") or 0),
                    "truncatedMarketCount": int(summary.get("truncated_market_count") or 0),
                    "validationBundleStatus": _first_text(performance.get("validationBundleStatus"), performance.get("validation_bundle_status")),
                },
                "evidenceClass": "saved_output_only",
                "whyUseful": "Local forensic run can anchor regression expectations for analyst-visible counts and scope behavior.",
                "forbiddenUse": "Do not treat this scaffold as labeled precision/recall or change production behavior from it.",
                "modelBehaviorChanged": False,
            }
        )
    return rows


def build_benchmark(
    *,
    review_packet_path: Path | None = None,
    event_forensic_root: Path = EVENT_FORENSIC_DIR,
    packet_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    packet_path = review_packet_path or _latest_file(REVIEW_PACKET_DIR, "unique_review_packets_*.json")
    packets = dict(packet_payload) if packet_payload is not None else _load_json(packet_path)
    packet_rows = _event_rows_from_packets(packet_path, packets)
    event_rows = _event_rows_from_forensic_outputs(event_forensic_root)
    rows = packet_rows + event_rows
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "local_known_case_benchmark_scaffold",
        "sourceReviewPacketsPath": str(packet_path or ""),
        "summary": {
            "rowCount": len(rows),
            "packetCandidateRows": len(packet_rows),
            "eventRunRows": len(event_rows),
            "humanLabeledRows": 0,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "fundingEligibilityChanged": False,
            "herRoutingChanged": False,
            "oldOutputsMutated": False,
        },
        "benchmarkRows": rows,
        "limitations": [
            "Rows are recovered only from local saved artifacts.",
            "Rows are benchmark scaffolds, not labeled truth.",
            "No external news, intelligence, RPC, or API calls are used.",
            "Production detector behavior must not be changed from this scaffold alone.",
        ],
        "readyToCopyNextPrompt": "Add human labels to selected benchmark scaffold rows, then run reporting-only consistency checks. Do not change scoring or gates.",
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Local Known-Case Benchmark Scaffold",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Rows: {summary.get('rowCount', 0)}",
        f"- Packet candidate rows: {summary.get('packetCandidateRows', 0)}",
        f"- Event run rows: {summary.get('eventRunRows', 0)}",
        f"- Human-labeled rows: {summary.get('humanLabeledRows', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Rows",
    ]
    for row in payload.get("benchmarkRows") or []:
        if isinstance(row, Mapping):
            lines.append(
                f"- `{row.get('localCaseId', '')}` {row.get('sourceType', '')}: "
                f"{row.get('eventSlug') or row.get('market') or 'unknown'} / {row.get('wallet') or 'event-run'}"
            )
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"local_known_case_benchmark_{stamp}.json"
    markdown_path = resolved / f"local_known_case_benchmark_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a local-only known-case benchmark scaffold from saved artifacts.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    payload = build_benchmark()
    outputs = write_outputs(payload, args.output_dir)
    print(f"Known-case benchmark JSON: {outputs['json_path']}")
    print(f"Known-case benchmark markdown: {outputs['markdown_path']}")
    print(f"Rows: {payload.get('summary', {}).get('rowCount', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
