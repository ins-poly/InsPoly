#!/usr/bin/env python3
"""Render sidecar-only previews from shadow review packet outputs."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


PREVIEW_TYPE = "shadow_review_packet_preview_batch"
SCHEMA_VERSION = "shadow_review_packet_preview_v1"

FORBIDDEN_PREVIEW_TEXT = (
    "risk_level",
    "riskLevel",
    "Strong Risk",
    "strongRisk",
    "Hard Evidence Review",
    "hardEvidenceReview",
    "candidateAdmission",
    "candidate_admission",
    "fundingEligibility",
    "funding_eligibility",
    "eventForensicScore",
    "existingModelScore",
    "sortKey",
)


def render_shadow_review_packet_previews(
    *, packet_index_json: str | Path, output_dir: str | Path, max_packets: int | None = None
) -> dict[str, object]:
    index_payload = _read_json(packet_index_json)
    previews = []
    for item in _packet_index_items(index_payload, max_packets=max_packets):
        packet = _read_json(item["json"])
        _assert_preview_safe(packet)
        previews.append(_preview_from_packet(packet))
    preview_payload = {
        "previewType": PREVIEW_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "sourceIndexPath": str(packet_index_json),
        "packetCount": len(previews),
        "previews": previews,
    }
    _assert_preview_safe(preview_payload)
    return write_shadow_review_packet_previews(preview_payload, output_dir)


def write_shadow_review_packet_previews(preview_payload: Mapping[str, object], output_dir: str | Path) -> dict[str, object]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"shadow_review_packet_previews_{stamp}.json"
    md_path = target / f"shadow_review_packet_previews_{stamp}.md"
    latest_json = target / "shadow_review_packet_previews_latest.json"
    latest_md = target / "shadow_review_packet_previews_latest.md"
    payload = dict(preview_payload)
    payload["generatedAt"] = datetime.now(tz=UTC).isoformat()
    json_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    markdown = preview_markdown(payload)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")
    latest_md.write_text(markdown, encoding="utf-8")
    return {**payload, "outputPaths": [str(json_path), str(md_path)], "latestPaths": [str(latest_json), str(latest_md)]}


def preview_markdown(preview_payload: Mapping[str, object]) -> str:
    lines = [
        "# Shadow Review Packet Previews",
        "",
        "- Scope: sidecar_only",
        f"- Packet count: {preview_payload.get('packetCount', 0)}",
        "- Production integration: false",
        "",
        "| Source artifact | Family | Metrics | Quality notes |",
        "| --- | --- | --- | --- |",
    ]
    for preview in preview_payload.get("previews", []):
        if not isinstance(preview, Mapping):
            continue
        metrics = ", ".join(
            str(metric.get("name")) for metric in preview.get("advisoryMetrics", []) if isinstance(metric, Mapping)
        )
        notes = ", ".join(str(note) for note in preview.get("qualityNotes", []))
        lines.append(
            f"| `{preview.get('sourceArtifactPath')}` | `{preview.get('sourceFamily')}` | {metrics or 'unknown'} | {notes or 'none'} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _preview_from_packet(packet: Mapping[str, object]) -> dict[str, object]:
    guardrails = packet.get("guardrails") if isinstance(packet.get("guardrails"), Mapping) else {}
    return {
        "packetType": packet.get("packetType"),
        "schemaVersion": packet.get("schemaVersion"),
        "sidecarOnly": bool(packet.get("sidecarOnly")),
        "networkUsed": bool(packet.get("networkUsed")),
        "productionIntegration": bool(packet.get("productionIntegration")),
        "sourceArtifactPath": packet.get("sourceArtifactPath"),
        "sourceFamily": packet.get("sourceFamily"),
        "advisoryMetrics": [_metric_preview(metric) for metric in packet.get("advisoryMetrics", []) if isinstance(metric, Mapping)],
        "qualityNotes": list(packet.get("qualityNotes", [])) if isinstance(packet.get("qualityNotes"), list) else [],
        "guardrails": {
            "affectsScoring": bool(guardrails.get("affectsScoring")),
            "affectsLabels": bool(guardrails.get("affectsLabels")),
            "affectsRouting": bool(guardrails.get("affectsRouting")),
            "affectsReports": bool(guardrails.get("affectsReports")),
            "affectsUi": bool(guardrails.get("affectsUi")),
        },
    }


def _metric_preview(metric: Mapping[str, object]) -> dict[str, object]:
    return {
        "name": metric.get("name"),
        "status": metric.get("status"),
        "advisoryLevel": metric.get("advisoryLevel"),
        "value": metric.get("value") if metric.get("value") not in ("", None) else "unknown",
    }


def _packet_index_items(index_payload: Mapping[str, object], *, max_packets: int | None) -> list[Mapping[str, str]]:
    raw_items = index_payload.get("packetPaths") if isinstance(index_payload.get("packetPaths"), list) else []
    items: list[Mapping[str, str]] = []
    for item in raw_items:
        if not isinstance(item, Mapping) or not item.get("json"):
            continue
        items.append({"json": str(item.get("json"))})
        if max_packets is not None and len(items) >= max_packets:
            break
    return items


def _read_json(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _assert_preview_safe(preview_payload: Mapping[str, object]) -> None:
    text = json.dumps(preview_payload)
    found = [item for item in FORBIDDEN_PREVIEW_TEXT if item in text]
    if found:
        raise ValueError(f"Shadow packet preview contains forbidden production text: {', '.join(sorted(found))}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render sidecar-only previews from shadow review packet outputs.")
    parser.add_argument("--packet-index-json", required=True, help="Local shadow review packet index JSON.")
    parser.add_argument("--output-dir", required=True, help="Explicit output directory for preview artifacts.")
    parser.add_argument("--max-packets", type=int, default=None, help="Optional max packets to render.")
    parser.add_argument("--quiet", action="store_true", help="Suppress JSON output.")
    args = parser.parse_args(argv)

    preview = render_shadow_review_packet_previews(
        packet_index_json=args.packet_index_json,
        output_dir=args.output_dir,
        max_packets=args.max_packets,
    )
    if not args.quiet:
        print(json.dumps(preview, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
