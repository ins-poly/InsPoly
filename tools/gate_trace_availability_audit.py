from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKET_DIR = Path("review_packets")
DEFAULT_DIAGNOSTIC_DIR = Path("strong_risk_diagnostic_outputs")
DEFAULT_OUTPUT_DIR = Path("source_schema_repair_outputs")


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


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "confirmed", "available"}


def discover_inputs(
    *,
    review_packets_path: Path | None = None,
    strong_risk_diagnostic_path: Path | None = None,
) -> dict[str, Path | None]:
    packets_path = _resolve(review_packets_path) if review_packets_path else None
    diagnostic_path = _resolve(strong_risk_diagnostic_path) if strong_risk_diagnostic_path else None
    return {
        "review_packets": packets_path
        if packets_path and packets_path.exists()
        else _latest_file(DEFAULT_PACKET_DIR, "unique_review_packets_*.json"),
        "strong_risk_diagnostic": diagnostic_path
        if diagnostic_path and diagnostic_path.exists()
        else _latest_file(DEFAULT_DIAGNOSTIC_DIR, "strong_risk_gate_diagnostic_*.json"),
    }


def _packets(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    packets = payload.get("packets")
    if not isinstance(packets, list):
        return []
    return [dict(packet) for packet in packets if isinstance(packet, Mapping)]


def _packet_is_strong_risk(packet: Mapping[str, Any]) -> bool:
    group = _string(packet.get("group")).lower()
    severity = _string(packet.get("severity")).lower()
    judgment = _string(packet.get("judgment")).lower()
    return group in {"strong_risk", "overlap"} or severity == "strong risk" or "strong risk" in judgment


def _packet_target_family(packet: Mapping[str, Any]) -> str:
    source_navigation = packet.get("source_navigation") if isinstance(packet.get("source_navigation"), Mapping) else {}
    source_path = _string(packet.get("source_path") or source_navigation.get("source_path"))
    target = _string(packet.get("target") or packet.get("target_label")).lower()
    source_lower = source_path.lower()
    if "archive" in source_lower or "archive" in target:
        return "archive"
    if "event_forensic_outputs" in source_lower or "event_forensic" in source_lower:
        return "event_forensic"
    if "sports" in target or "crypto" in target:
        return "sports_crypto"
    if "politics" in target or "world" in target:
        return "politics_world"
    return "unknown"


def _artifact_key(packet: Mapping[str, Any]) -> str:
    source_navigation = packet.get("source_navigation") if isinstance(packet.get("source_navigation"), Mapping) else {}
    source_path = _string(packet.get("source_path") or source_navigation.get("source_path"))
    if not source_path:
        return "missing_source_path"
    return source_path


def _gate_trace_available(packet: Mapping[str, Any]) -> bool:
    for key in ("gate_trace_available", "strong_risk_gate_trace_available", "gateTraceAvailable"):
        if key in packet:
            return _truthy(packet.get(key))
    branch = _string(packet.get("strong_risk_exact_gate_branch") or packet.get("gate_branch"))
    gate_family = _string(packet.get("gate_family") or packet.get("strong_risk_gate_family"))
    source_collections = [item for item in _listify(packet.get("source_collections")) if _string(item)]
    return bool(branch and gate_family and source_collections)


def _increment_bucket(bucket: dict[str, Any], packet: Mapping[str, Any]) -> None:
    strong = _packet_is_strong_risk(packet)
    source_navigation = packet.get("source_navigation") if isinstance(packet.get("source_navigation"), Mapping) else {}
    hard_sources = [item for item in _listify(packet.get("hard_evidence_sources")) if _string(item)]
    branch = _string(packet.get("strong_risk_exact_gate_branch") or packet.get("gate_branch"))
    gate_family = _string(packet.get("gate_family") or packet.get("strong_risk_gate_family"))
    source_collections = [item for item in _listify(packet.get("source_collections") or source_navigation.get("source_collections")) if _string(item)]
    available = _gate_trace_available(packet)
    bucket["packetCount"] += 1
    if strong:
        bucket["strongRiskPacketCount"] += 1
    if available:
        bucket["gateTraceAvailableCount"] += 1
    else:
        bucket["gateTraceMissingCount"] += 1
    if branch:
        bucket["exactGateBranchPresentCount"] += 1
    else:
        bucket["exactGateBranchMissingCount"] += 1
    if gate_family:
        bucket["gateFamilyPresentCount"] += 1
    else:
        bucket["gateFamilyMissingCount"] += 1
    if source_navigation:
        bucket["sourceNavigationPresentCount"] += 1
    else:
        bucket["sourceNavigationMissingCount"] += 1
    if source_collections:
        bucket["sourceCollectionPresentCount"] += 1
    else:
        bucket["sourceCollectionMissingCount"] += 1
    if hard_sources:
        bucket["hardEvidenceSourcesPresentCount"] += 1
    else:
        bucket["hardEvidenceSourcesMissingCount"] += 1


def _bucket(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "packetCount": 0,
        "strongRiskPacketCount": 0,
        "gateTraceAvailableCount": 0,
        "gateTraceMissingCount": 0,
        "exactGateBranchPresentCount": 0,
        "exactGateBranchMissingCount": 0,
        "gateFamilyPresentCount": 0,
        "gateFamilyMissingCount": 0,
        "sourceNavigationPresentCount": 0,
        "sourceNavigationMissingCount": 0,
        "sourceCollectionPresentCount": 0,
        "sourceCollectionMissingCount": 0,
        "hardEvidenceSourcesPresentCount": 0,
        "hardEvidenceSourcesMissingCount": 0,
    }


def _finalize_rows(rows: Mapping[str, dict[str, Any]]) -> list[dict[str, Any]]:
    finalized = []
    for name, row in rows.items():
        packet_count = int(row.get("packetCount") or 0)
        out = dict(row)
        out["name"] = name
        out["gateTraceCoverageRatio"] = round((out["gateTraceAvailableCount"] / packet_count), 4) if packet_count else 0.0
        out["sourceNavigationCoverageRatio"] = (
            round((out["sourceNavigationPresentCount"] / packet_count), 4) if packet_count else 0.0
        )
        out["readOnlyReportingOnly"] = True
        finalized.append(out)
    finalized.sort(key=lambda item: (-int(item.get("gateTraceMissingCount") or 0), str(item.get("name") or "")))
    return finalized


def build_audit(
    review_packets_payload: Mapping[str, Any],
    strong_risk_diagnostic_payload: Mapping[str, Any] | None = None,
    *,
    input_paths: Mapping[str, Path | None] | None = None,
) -> dict[str, Any]:
    packets = _packets(review_packets_payload)
    strong_packets = [packet for packet in packets if _packet_is_strong_risk(packet)]
    artifact_rows: defaultdict[str, dict[str, Any]] = defaultdict(lambda: _bucket(""))
    family_rows: defaultdict[str, dict[str, Any]] = defaultdict(lambda: _bucket(""))
    missing_examples: list[dict[str, Any]] = []
    branch_counter: Counter[str] = Counter()
    for packet in packets:
        artifact_key = _artifact_key(packet)
        family_key = _packet_target_family(packet)
        if not artifact_rows[artifact_key].get("name"):
            artifact_rows[artifact_key]["name"] = artifact_key
        if not family_rows[family_key].get("name"):
            family_rows[family_key]["name"] = family_key
        _increment_bucket(artifact_rows[artifact_key], packet)
        _increment_bucket(family_rows[family_key], packet)
        branch = _string(packet.get("strong_risk_exact_gate_branch") or packet.get("gate_branch"))
        if branch:
            branch_counter.update([branch])
        if _packet_is_strong_risk(packet) and not _gate_trace_available(packet):
            missing_examples.append(
                {
                    "packetId": _string(packet.get("packet_id")) or "unknown",
                    "wallet": _string(packet.get("wallet")) or "unknown",
                    "marketOrEvent": _string(packet.get("market") or packet.get("target")) or "unknown",
                    "sourcePath": artifact_key,
                    "targetFamily": family_key,
                    "exactGateBranch": branch or "missing",
                    "gateFamily": _string(packet.get("gate_family") or packet.get("strong_risk_gate_family")) or "missing",
                    "sourceCollections": [
                        str(item)
                        for item in _listify(
                            packet.get("source_collections")
                            or (
                                packet.get("source_navigation")
                                if isinstance(packet.get("source_navigation"), Mapping)
                                else {}
                            ).get("source_collections")
                        )
                        if _string(item)
                    ],
                }
            )

    diagnostic_payload = strong_risk_diagnostic_payload or {}
    diagnostic_family_counts = diagnostic_payload.get("strongRiskByTargetFamily")
    if not isinstance(diagnostic_family_counts, Mapping):
        diagnostic_family_counts = {}
    diagnostic_summary = {
        "rawStrongRiskRows": diagnostic_payload.get("rawStrongRiskRows", 0),
        "strongRiskRowsWithGateTraceAvailable": diagnostic_payload.get("strongRiskRowsWithGateTraceAvailable", 0),
        "strongRiskRowsWithoutGateTrace": diagnostic_payload.get("strongRiskRowsWithoutGateTrace", 0),
        "strongRiskByTargetFamily": dict(diagnostic_family_counts),
        "recommendation": diagnostic_payload.get("recommendation", ""),
    }
    gate_trace_available = sum(1 for packet in strong_packets if _gate_trace_available(packet))
    gate_trace_missing = len(strong_packets) - gate_trace_available
    paths = input_paths or {}
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourceReviewPacketsPath": str(paths.get("review_packets") or ""),
        "sourceStrongRiskDiagnosticPath": str(paths.get("strong_risk_diagnostic") or ""),
        "summary": {
            "packetCount": len(packets),
            "strongRiskPacketCount": len(strong_packets),
            "strongRiskGateTraceAvailableCount": gate_trace_available,
            "strongRiskGateTraceMissingCount": gate_trace_missing,
            "strongRiskGateTraceCoverageRatio": round(gate_trace_available / len(strong_packets), 4)
            if strong_packets
            else 0.0,
            "artifactRowCount": len(artifact_rows),
            "targetFamilyRowCount": len(family_rows),
            "detectorBehaviorChanged": False,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
        },
        "artifactRows": _finalize_rows(artifact_rows),
        "targetFamilyRows": _finalize_rows(family_rows),
        "gateBranchCounts": dict(sorted(branch_counter.items())),
        "missingGateTraceExamples": missing_examples[:50],
        "strongRiskDiagnosticSummary": diagnostic_summary,
        "recommendedReportingActions": [
            "Use artifact rows to find where saved review packets lose gate trace fields.",
            "Use target-family rows to separate event-forensic/cache-only limitations from reusable schema gaps.",
            "Repair only display/export propagation when the missing field already exists upstream.",
            "Do not infer a detector defect from cache-only or legacy saved fields without fresh trace-enabled validation.",
        ],
        "limitations": [
            "This audit reads saved local artifacts only.",
            "It does not recompute scores, gates, HER routing, funding eligibility, or candidate admission.",
            "Missing gate trace in cache-only artifacts is a review-readiness limitation, not proof of a model defect.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Gate Trace Availability Audit",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Source review packets: {payload.get('sourceReviewPacketsPath', '')}",
        f"- Source Strong Risk diagnostic: {payload.get('sourceStrongRiskDiagnosticPath', '')}",
        f"- Packet count: {summary.get('packetCount', 0)}",
        f"- Strong Risk packet count: {summary.get('strongRiskPacketCount', 0)}",
        f"- Strong Risk gate trace available: {summary.get('strongRiskGateTraceAvailableCount', 0)}",
        f"- Strong Risk gate trace missing: {summary.get('strongRiskGateTraceMissingCount', 0)}",
        f"- Strong Risk gate trace coverage ratio: {summary.get('strongRiskGateTraceCoverageRatio', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Target Family Rows",
    ]
    for row in payload.get("targetFamilyRows") or []:
        lines.append(
            f"- `{row.get('name', '')}`: {row.get('gateTraceAvailableCount', 0)} available / "
            f"{row.get('gateTraceMissingCount', 0)} missing "
            f"(coverage {row.get('gateTraceCoverageRatio', 0)})"
        )
    lines.extend(["", "## Artifact Rows"])
    for row in (payload.get("artifactRows") or [])[:25]:
        lines.append(
            f"- `{row.get('name', '')}`: packets={row.get('packetCount', 0)}, "
            f"trace_missing={row.get('gateTraceMissingCount', 0)}, "
            f"source_nav_coverage={row.get('sourceNavigationCoverageRatio', 0)}"
        )
    lines.extend(["", "## Missing Gate Trace Examples"])
    examples = payload.get("missingGateTraceExamples") if isinstance(payload.get("missingGateTraceExamples"), list) else []
    if not examples:
        lines.append("- none")
    for item in examples[:20]:
        if isinstance(item, Mapping):
            lines.append(
                f"- `{item.get('packetId', '')}` {item.get('wallet', 'unknown')} / "
                f"{item.get('marketOrEvent', 'unknown')} "
                f"(branch={item.get('exactGateBranch', 'missing')}, family={item.get('gateFamily', 'missing')})"
            )
    lines.extend(["", "## Recommended Reporting Actions"])
    for item in payload.get("recommendedReportingActions") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"gate_trace_availability_audit_{stamp}.json"
    markdown_path = resolved / f"gate_trace_availability_audit_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit saved review packet gate-trace availability without changing scoring.")
    parser.add_argument("--review-packets", type=Path)
    parser.add_argument("--strong-risk-diagnostic", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    paths = discover_inputs(
        review_packets_path=args.review_packets,
        strong_risk_diagnostic_path=args.strong_risk_diagnostic,
    )
    payload = build_audit(
        _load_json(paths["review_packets"]),
        _load_json(paths["strong_risk_diagnostic"]),
        input_paths=paths,
    )
    outputs = write_outputs(payload, args.output_dir)
    summary = payload.get("summary", {})
    print(f"Gate trace availability audit JSON: {outputs['json_path']}")
    print(f"Gate trace availability audit markdown: {outputs['markdown_path']}")
    print(f"Strong Risk packets: {summary.get('strongRiskPacketCount', 0)}")
    print(f"Strong Risk gate trace missing: {summary.get('strongRiskGateTraceMissingCount', 0)}")
    print(f"Model behavior changed: {summary.get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
