#!/usr/bin/env python3
"""Generate Phase 3 sensitive-overlap capital review packets.

Packets are small, sidecar-only review artifacts. They summarize representative
rows from the real SELL evidence discovery output and never mutate source
artifacts.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


DEFAULT_DISCOVERY = Path("validation_outputs/phase3_real_sell_evidence_discovery_20260525.json")
DEFAULT_SOURCE_INVENTORY = Path("validation_outputs/phase3_capital_source_inventory_20260525.json")
DEFAULT_IMPACT = Path("validation_outputs/phase3_capital_unblock_impact_audit_20260525.json")
DEFAULT_OUTPUT_DIR = Path("phase3_capital_review_packets/phase3_sensitive_overlap_20260525")


def packet_payload(row: Mapping[str, object], *, index: int) -> dict[str, object]:
    recommendation = str(row.get("recommendation") or "needs_source_fields")
    return {
        "packetId": f"phase3-sensitive-capital-{index:03d}",
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeImplementationAllowed": False,
        "source": {
            "artifactPath": row.get("artifactPath", ""),
            "sourceProvenance": row.get("sourceProvenance", "unknown"),
            "sourceType": row.get("sourceType", "unknown"),
            "artifactFamily": row.get("artifactFamily", "unknown"),
            "rowId": row.get("rowId", ""),
        },
        "identity": {
            "wallet": row.get("wallet", ""),
            "market": row.get("market", ""),
            "event": row.get("event", ""),
        },
        "trade": {
            "rawOrderSide": row.get("rawOrderSide", "unknown"),
            "rawTokenOutcome": row.get("rawTokenOutcome", "unknown"),
            "rawTokenPrice": row.get("rawTokenPrice", "unknown"),
            "size": row.get("size", "unknown"),
            "usdcSize": row.get("usdcSize", "unknown"),
            "economicSide": row.get("economicSide", "unknown"),
            "economicSideProbability": row.get("economicSideProbability", "unknown"),
        },
        "capital": {
            "currentRawNotional": row.get("currentRawNotional", "unknown"),
            "hypotheticalSellMaxLoss": row.get("hypotheticalSellMaxLoss", "unknown"),
            "observedCash": row.get("observedCash", "unknown"),
            "sourceQuality": row.get("sourceQuality", "unknown"),
            "safeForSellMaxLoss": bool(row.get("safeForSellMaxLoss")),
            "qualityNotes": list(row.get("qualityNotes", [])) if isinstance(row.get("qualityNotes"), list) else [],
        },
        "sensitiveOverlap": bool(row.get("sensitiveOverlap")),
        "recommendation": recommendation,
        "recommendationReason": _recommendation_reason(recommendation),
    }


def build_review_packets(
    *,
    discovery: Mapping[str, object],
    source_inventory: Mapping[str, object],
    impact_audit: Mapping[str, object],
    limit: int = 12,
) -> dict[str, object]:
    candidates = discovery.get("reviewCandidates", [])
    rows = candidates if isinstance(candidates, list) else []
    packets = [packet_payload(row, index=index + 1) for index, row in enumerate(rows[:limit]) if isinstance(row, Mapping)]
    return {
        "reportType": "phase3_sensitive_capital_review_packets",
        "schemaVersion": "phase3_sensitive_capital_review_packets_v1",
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeImplementationAllowed": False,
        "sourceInputs": {
            "discoveryReportType": discovery.get("reportType"),
            "sourceInventoryReportType": source_inventory.get("reportType"),
            "impactAuditReportType": impact_audit.get("reportType"),
            "impactGateDecision": impact_audit.get("gateDecision"),
        },
        "summary": {
            "packets": len(packets),
            "safeSidecarOnly": sum(1 for packet in packets if packet["recommendation"] == "safe_sidecar_only"),
            "unsafeOldNotional": sum(1 for packet in packets if packet["recommendation"] == "unsafe_old_notional"),
            "needsSourceFields": sum(1 for packet in packets if packet["recommendation"] == "needs_source_fields"),
            "discoverySensitiveOverlapRows": _nested(discovery, "summary", "sensitiveOverlapRows"),
            "oldAuditSensitiveOverlapRows": _nested(impact_audit, "summary", "oldAuditSensitiveOverlapRows"),
        },
        "packets": packets,
    }


def write_review_packets(report: Mapping[str, object], output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    packets = report.get("packets", [])
    index_rows: list[dict[str, str]] = []
    for packet in packets if isinstance(packets, list) else []:
        if not isinstance(packet, Mapping):
            continue
        packet_id = str(packet.get("packetId") or "packet")
        stem = _slug(packet_id)
        json_path = root / f"{stem}.json"
        md_path = root / f"{stem}.md"
        json_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        md_path.write_text(packet_markdown(packet), encoding="utf-8")
        index_rows.append(
            {
                "packetId": packet_id,
                "json": json_path.name,
                "markdown": md_path.name,
                "recommendation": str(packet.get("recommendation") or ""),
            }
        )
    index_payload = {
        "reportType": report.get("reportType"),
        "schemaVersion": report.get("schemaVersion"),
        "generatedAt": report.get("generatedAt"),
        "summary": report.get("summary"),
        "packets": index_rows,
    }
    (root / "index.json").write_text(json.dumps(index_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "index.md").write_text(index_markdown(report, index_rows), encoding="utf-8")
    return {"outputDir": str(root), "indexJson": str(root / "index.json"), "indexMarkdown": str(root / "index.md")}


def packet_markdown(packet: Mapping[str, object]) -> str:
    source = packet.get("source", {}) if isinstance(packet.get("source"), Mapping) else {}
    identity = packet.get("identity", {}) if isinstance(packet.get("identity"), Mapping) else {}
    trade = packet.get("trade", {}) if isinstance(packet.get("trade"), Mapping) else {}
    capital = packet.get("capital", {}) if isinstance(packet.get("capital"), Mapping) else {}
    notes = capital.get("qualityNotes", [])
    lines = [
        f"# {packet.get('packetId')}",
        "",
        f"- Recommendation: `{packet.get('recommendation')}`",
        f"- Sensitive overlap: `{packet.get('sensitiveOverlap')}`",
        f"- Source provenance: `{source.get('sourceProvenance', 'unknown')}`",
        f"- Artifact: `{source.get('artifactPath', '')}`",
        "",
        "## Identity",
        "",
        f"- Wallet: `{identity.get('wallet', '')}`",
        f"- Market: `{identity.get('market', '')}`",
        f"- Event: `{identity.get('event', '')}`",
        "",
        "## Trade And Capital",
        "",
        f"- Raw side/outcome: `{trade.get('rawOrderSide')}` / `{trade.get('rawTokenOutcome')}`",
        f"- Raw token price: `{trade.get('rawTokenPrice')}`",
        f"- Size: `{trade.get('size')}`",
        f"- `usdcSize`: `{trade.get('usdcSize')}`",
        f"- Economic side/probability: `{trade.get('economicSide')}` / `{trade.get('economicSideProbability')}`",
        f"- Current raw notional: `{capital.get('currentRawNotional')}`",
        f"- Hypothetical SELL max loss: `{capital.get('hypotheticalSellMaxLoss')}`",
        f"- Observed cash: `{capital.get('observedCash')}`",
        f"- Source quality: `{capital.get('sourceQuality')}`",
        f"- Safe for SELL max loss: `{capital.get('safeForSellMaxLoss')}`",
        "",
        "## Quality Notes",
        "",
    ]
    if isinstance(notes, list) and notes:
        lines.extend(f"- `{note}`" for note in notes)
    else:
        lines.append("- `none`")
    lines.extend(["", "## Reason", "", str(packet.get("recommendationReason") or "")])
    return "\n".join(lines).rstrip() + "\n"


def index_markdown(report: Mapping[str, object], rows: Sequence[Mapping[str, str]]) -> str:
    summary = report.get("summary", {}) if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# Phase 3 Sensitive Capital Review Packets",
        "",
        f"- Packets: `{summary.get('packets', 0)}`",
        f"- Safe sidecar-only: `{summary.get('safeSidecarOnly', 0)}`",
        f"- Unsafe old-notional: `{summary.get('unsafeOldNotional', 0)}`",
        f"- Needs source fields: `{summary.get('needsSourceFields', 0)}`",
        "",
        "| Packet | Recommendation | JSON | Markdown |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(f"| `{row['packetId']}` | `{row['recommendation']}` | `{row['json']}` | `{row['markdown']}` |")
    return "\n".join(lines).rstrip() + "\n"


def _recommendation_reason(recommendation: str) -> str:
    if recommendation == "safe_sidecar_only":
        return "The row has enough direct side/outcome/price/size evidence for sidecar max-loss review, but this does not authorize production capital migration."
    if recommendation == "unsafe_old_notional":
        return "The row is notional-only or lossy; it must not be reinterpreted as economic max loss."
    return "The row needs stronger source fields before Phase 3 capital semantics can be trusted."


def _nested(payload: Mapping[str, object], *keys: str) -> object:
    current: object = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return 0
        current = current.get(key, 0)
    return current


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-") or "packet"


def _load_json(path: str | Path) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery-json", default=str(DEFAULT_DISCOVERY))
    parser.add_argument("--source-inventory-json", default=str(DEFAULT_SOURCE_INVENTORY))
    parser.add_argument("--impact-json", default=str(DEFAULT_IMPACT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_review_packets(
        discovery=_load_json(args.discovery_json),
        source_inventory=_load_json(args.source_inventory_json),
        impact_audit=_load_json(args.impact_json),
        limit=args.limit,
    )
    outputs = write_review_packets(report, args.output_dir)
    if not args.quiet:
        print(outputs["outputDir"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
