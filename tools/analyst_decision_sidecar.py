from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("analyst_sidecars")
DEFAULT_PACKET_DIR = Path("review_packets")
DEFAULT_QUALITY_DIR = Path("analyst_quality_outputs")

ALLOWED_DECISIONS = (
    "unreviewed",
    "needs_source_check",
    "likely_false_positive",
    "plausible_insider_style_lead",
    "escalate_manual_review",
    "insufficient_evidence",
)


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


def discover_inputs(packet_quality_report: Path | None = None, review_packets: Path | None = None) -> dict[str, Path | None]:
    return {
        "packet_quality_report": _resolve(packet_quality_report)
        if packet_quality_report
        else _latest_file(DEFAULT_QUALITY_DIR, "packet_quality_report_*.json"),
        "review_packets": _resolve(review_packets)
        if review_packets
        else _latest_file(DEFAULT_PACKET_DIR, "unique_review_packets_*.json"),
    }


def _rows_from_quality_report(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("packetQualityRows")
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _rows_from_review_packets(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    packets = payload.get("packets") if isinstance(payload.get("packets"), list) else []
    for packet in packets:
        if not isinstance(packet, Mapping):
            continue
        rows.append(
            {
                "packetId": packet.get("packet_id", ""),
                "wallet": packet.get("wallet", ""),
                "traderName": packet.get("trader_name", ""),
                "marketOrEvent": packet.get("market") or packet.get("target") or "",
                "strongRiskFlag": packet.get("group") in {"strong_risk", "overlap"},
                "hardEvidenceReviewFlag": packet.get("group") in {"hard_evidence_review", "overlap"},
                "overlapFlag": packet.get("group") == "overlap",
                "analystPriority": "unranked",
            }
        )
    return rows


def build_sidecar(
    *,
    quality_report_payload: Mapping[str, Any] | None = None,
    review_packet_payload: Mapping[str, Any] | None = None,
    quality_report_path: Path | None = None,
    review_packet_path: Path | None = None,
) -> dict[str, Any]:
    quality_report_payload = quality_report_payload or {}
    review_packet_payload = review_packet_payload or {}
    rows = _rows_from_quality_report(quality_report_payload) or _rows_from_review_packets(review_packet_payload)
    sidecar_rows = []
    for row in rows:
        sidecar_rows.append(
            {
                "packetId": _string(row.get("packetId")) or "unknown",
                "wallet": _string(row.get("wallet")) or "unknown",
                "traderName": _string(row.get("traderName")) or "unknown",
                "marketOrEvent": _string(row.get("marketOrEvent")) or "unknown",
                "strongRiskFlag": bool(row.get("strongRiskFlag")),
                "hardEvidenceReviewFlag": bool(row.get("hardEvidenceReviewFlag")),
                "overlapFlag": bool(row.get("overlapFlag")),
                "packetQualityPriority": _string(row.get("analystPriority")) or "unranked",
                "analystDecision": "unreviewed",
                "allowedDecisions": list(ALLOWED_DECISIONS),
                "analystNotes": "",
                "reviewer": "",
                "reviewedAt": "",
                "followUpAction": "",
                "productionUseAllowed": False,
                "scoringUseAllowed": False,
                "routingUseAllowed": False,
                "sidecarOnly": True,
            }
        )
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourcePacketQualityReportPath": str(quality_report_path or ""),
        "sourceReviewPacketsPath": str(review_packet_path or ""),
        "summary": {
            "sidecarRowCount": len(sidecar_rows),
            "allowedDecisions": list(ALLOWED_DECISIONS),
            "productionUseAllowed": False,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
        },
        "sidecarRows": sidecar_rows,
        "limitations": [
            "This is a local analyst note sidecar only.",
            "Analyst decisions are not consumed by scanner, archive, event-forensic, scoring, gates, HER routing, funding eligibility, or candidate admission.",
            "Sidecar labels may support future evaluation only after a separate RFC and explicit approval.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Analyst Decision Sidecar",
        "",
        f"- generatedAt: {payload.get('generatedAt', '')}",
        f"- sourcePacketQualityReportPath: {payload.get('sourcePacketQualityReportPath', '')}",
        f"- sourceReviewPacketsPath: {payload.get('sourceReviewPacketsPath', '')}",
        f"- sidecarRowCount: {summary.get('sidecarRowCount', 0)}",
        f"- productionUseAllowed: {summary.get('productionUseAllowed', False)}",
        f"- modelBehaviorChanged: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Allowed Decisions",
    ]
    for decision in summary.get("allowedDecisions") or []:
        lines.append(f"- `{decision}`")
    lines.extend(["", "## Rows"])
    rows = payload.get("sidecarRows") if isinstance(payload.get("sidecarRows"), list) else []
    if not rows:
        lines.append("- none")
    for row in rows[:50]:
        lines.append(
            f"- `{row.get('packetId', '')}` {row.get('wallet', 'unknown')} / "
            f"{row.get('marketOrEvent', 'unknown')}: {row.get('analystDecision', 'unreviewed')}"
        )
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"analyst_decision_sidecar_{stamp}.json"
    md_path = resolved / f"analyst_decision_sidecar_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(md_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a reporting-only analyst decision sidecar template.")
    parser.add_argument("--packet-quality-report", type=Path)
    parser.add_argument("--review-packets", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    inputs = discover_inputs(args.packet_quality_report, args.review_packets)
    quality_path = inputs.get("packet_quality_report")
    packets_path = inputs.get("review_packets")
    payload = build_sidecar(
        quality_report_payload=_load_json(quality_path),
        review_packet_payload=_load_json(packets_path),
        quality_report_path=quality_path,
        review_packet_path=packets_path,
    )
    outputs = write_outputs(payload, args.output_dir)
    print(f"Analyst decision sidecar JSON: {outputs['json_path']}")
    print(f"Analyst decision sidecar markdown: {outputs['markdown_path']}")
    print(f"Rows: {payload.get('summary', {}).get('sidecarRowCount', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
