#!/usr/bin/env python3
"""Generate analyst-only shadow review packets from sidecar outputs."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


INDEX_TYPE = "shadow_review_packet_index"
PACKET_TYPE = "shadow_review_packet"
SCHEMA_VERSION = "shadow_review_packet_v1"

FORBIDDEN_PACKET_TEXT = (
    "risk_level",
    "riskLevel",
    "Strong Risk",
    "strongRisk",
    "Hard Evidence Review",
    "hardEvidenceReview",
    "HER",
    "candidateAdmission",
    "candidate_admission",
    "fundingEligibility",
    "funding_eligibility",
    "eventForensicScore",
    "existingModelScore",
    "sortKey",
)


def build_shadow_review_packets(
    *,
    batch_evaluation: Mapping[str, object],
    reconstruction_pnl: Mapping[str, object] | None = None,
    archive_overlap: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    packets: list[dict[str, object]] = []
    packets.extend(_packets_from_batch_evaluation(batch_evaluation))
    if reconstruction_pnl:
        packets.extend(_packets_from_reconstruction(reconstruction_pnl))
    if archive_overlap:
        packets.extend(_packets_from_archive_overlap(archive_overlap))
    deduped = _dedupe_packets(packets)
    for packet in deduped:
        _assert_packet_safe(packet)
    return deduped


def write_shadow_review_packets(packets: Sequence[Mapping[str, object]], output_dir: str | Path) -> dict[str, object]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    packet_paths = []
    for index, packet in enumerate(packets, start=1):
        base = f"shadow_review_packet_{stamp}_{index:03d}"
        json_path = target / f"{base}.json"
        md_path = target / f"{base}.md"
        json_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        md_path.write_text(packet_markdown(packet), encoding="utf-8")
        packet_paths.append({"json": str(json_path), "markdown": str(md_path), "sourceArtifactPath": packet.get("sourceArtifactPath")})
    index_payload = {
        "indexType": INDEX_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "packetCount": len(packet_paths),
        "packetPaths": packet_paths,
    }
    index_json = target / f"shadow_review_packet_index_{stamp}.json"
    index_md = target / f"shadow_review_packet_index_{stamp}.md"
    index_json.write_text(json.dumps(index_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    index_md.write_text(index_markdown(index_payload), encoding="utf-8")
    latest_json = target / "shadow_review_packet_index_latest.json"
    latest_md = target / "shadow_review_packet_index_latest.md"
    latest_json.write_text(json.dumps(index_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest_md.write_text(index_markdown(index_payload), encoding="utf-8")
    return {**index_payload, "indexJsonPath": str(index_json), "indexMarkdownPath": str(index_md)}


def packet_markdown(packet: Mapping[str, object]) -> str:
    lines = [
        "# Shadow Review Packet",
        "",
        "- Scope: sidecar_only",
        f"- Source artifact: `{packet.get('sourceArtifactPath')}`",
        f"- Source family: `{packet.get('sourceFamily')}`",
        "",
        "## Advisory Metrics",
    ]
    for metric in packet.get("advisoryMetrics", []):
        if isinstance(metric, Mapping):
            lines.append(
                f"- `{metric.get('name')}`: `{metric.get('status')}` / `{metric.get('advisoryLevel')}` / "
                f"{metric.get('value') or 'unknown'}"
            )
    notes = packet.get("qualityNotes") if isinstance(packet.get("qualityNotes"), list) else []
    if notes:
        lines.extend(["", "## Quality Notes"])
        lines.extend(f"- {note}" for note in notes)
    return "\n".join(lines).rstrip() + "\n"


def index_markdown(index_payload: Mapping[str, object]) -> str:
    lines = [
        "# Shadow Review Packet Index",
        "",
        "- Scope: sidecar_only",
        f"- Packet count: {index_payload.get('packetCount', 0)}",
        "",
        "| Source artifact | JSON | Markdown |",
        "| --- | --- | --- |",
    ]
    for item in index_payload.get("packetPaths", []):
        if isinstance(item, Mapping):
            lines.append(f"| `{item.get('sourceArtifactPath')}` | `{item.get('json')}` | `{item.get('markdown')}` |")
    return "\n".join(lines).rstrip() + "\n"


def _packets_from_batch_evaluation(batch_evaluation: Mapping[str, object]) -> list[dict[str, object]]:
    packets = []
    artifacts = batch_evaluation.get("artifacts") if isinstance(batch_evaluation.get("artifacts"), list) else []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        metrics = [
            _metric_packet(metric)
            for metric in artifact.get("metricEvaluations", [])
            if isinstance(metric, Mapping) and metric.get("usefulAdvisory")
        ]
        if not metrics:
            continue
        packets.append(
            _packet(
                source_artifact_path=str(artifact.get("artifactPath")),
                source_family=str(artifact.get("inventoryFamily") or artifact.get("family") or "unknown"),
                metrics=metrics,
                quality_notes=list(artifact.get("normalizationQualityNotes", [])),
            )
        )
    return packets


def _packets_from_reconstruction(reconstruction_pnl: Mapping[str, object]) -> list[dict[str, object]]:
    packets = []
    artifacts = reconstruction_pnl.get("artifacts") if isinstance(reconstruction_pnl.get("artifacts"), list) else []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping) or artifact.get("status") != "available":
            continue
        packets.append(
            _packet(
                source_artifact_path=str(artifact.get("artifactPath")),
                source_family="reconstruction_report_dir",
                metrics=[
                    {
                        "name": "shadow_net_position_pnl",
                        "status": artifact.get("status"),
                        "advisoryLevel": artifact.get("advisoryLevel"),
                        "value": artifact.get("pnlValue"),
                        "details": artifact.get("metricDetails", {}),
                    }
                ],
                quality_notes=list(artifact.get("qualityNotes", [])),
            )
        )
    return packets


def _packets_from_archive_overlap(archive_overlap: Mapping[str, object]) -> list[dict[str, object]]:
    packets = []
    artifacts = archive_overlap.get("artifacts") if isinstance(archive_overlap.get("artifacts"), list) else []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        useful_rows = [
            row for row in artifact.get("walletHistoryRows", []) if isinstance(row, Mapping) and row.get("shadowUseful")
        ]
        if not useful_rows:
            continue
        packets.append(
            _packet(
                source_artifact_path=str(artifact.get("artifactPath")),
                source_family="archive_report_json",
                metrics=[
                    {
                        "name": "shadow_win_rate_confidence",
                        "status": "available",
                        "advisoryLevel": "context",
                        "value": str(len(useful_rows)),
                        "details": {"usefulWalletHistoryRows": len(useful_rows), "duplicateProductionSemantics": True},
                    }
                ],
                quality_notes=["archive_wallet_history_shadow_confidence_duplicates_existing_fields"],
            )
        )
    return packets


def _packet(
    *,
    source_artifact_path: str,
    source_family: str,
    metrics: Sequence[Mapping[str, object]],
    quality_notes: Sequence[str],
) -> dict[str, object]:
    return {
        "packetType": PACKET_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "sourceArtifactPath": source_artifact_path,
        "sourceFamily": source_family,
        "advisoryMetrics": list(metrics),
        "qualityNotes": list(quality_notes),
        "guardrails": {
            "affectsScoring": False,
            "affectsLabels": False,
            "affectsRouting": False,
            "affectsReports": False,
            "affectsUi": False,
        },
    }


def _metric_packet(metric: Mapping[str, object]) -> dict[str, object]:
    return {
        "name": metric.get("metric"),
        "status": metric.get("evaluatedStatus"),
        "advisoryLevel": metric.get("advisoryLevel"),
        "value": metric.get("value"),
        "details": metric.get("details", {}),
        "qualityNotes": metric.get("qualityNotes", []),
    }


def _dedupe_packets(packets: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    deduped = []
    seen: set[tuple[str, str]] = set()
    for packet in packets:
        metric_names = ",".join(sorted(str(metric.get("name")) for metric in packet.get("advisoryMetrics", [])))
        key = (str(packet.get("sourceArtifactPath")), metric_names)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(packet)
    return deduped


def _assert_packet_safe(packet: Mapping[str, object]) -> None:
    text = json.dumps(packet)
    found = [item for item in FORBIDDEN_PACKET_TEXT if item in text]
    if found:
        raise ValueError(f"Shadow packet contains forbidden production text: {', '.join(sorted(found))}")


def _read_json(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Input JSON root must be an object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate analyst-only shadow review packets.")
    parser.add_argument("--batch-evaluation-json", required=True)
    parser.add_argument("--reconstruction-pnl-json")
    parser.add_argument("--archive-overlap-json")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    packets = build_shadow_review_packets(
        batch_evaluation=_read_json(args.batch_evaluation_json),
        reconstruction_pnl=_read_json(args.reconstruction_pnl_json) if args.reconstruction_pnl_json else None,
        archive_overlap=_read_json(args.archive_overlap_json) if args.archive_overlap_json else None,
    )
    index_payload = write_shadow_review_packets(packets, args.output_dir)
    if not args.quiet:
        print(json.dumps(index_payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
