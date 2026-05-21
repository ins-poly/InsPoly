from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("analyst_quality_outputs")
INPUT_PATTERNS = {
    "packet_quality_report": (Path("analyst_quality_outputs"), "packet_quality_report_*.json"),
    "candidate_recall_diagnostic": (Path("candidate_recall_outputs"), "candidate_recall_diagnostic_*.json"),
    "gate_trace_availability_audit": (Path("source_schema_repair_outputs"), "gate_trace_availability_audit_*.json"),
    "false_positive_explanation_report": (Path("false_positive_library"), "false_positive_explanation_report_*.json"),
    "false_positive_guardrail_audit": (Path("false_positive_library"), "false_positive_guardrail_audit_*.json"),
    "gate_decision_readiness": (Path("validation_corpus_outputs"), "gate_decision_readiness_*.json"),
}


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


def discover_inputs() -> dict[str, Path | None]:
    return {name: _latest_file(directory, pattern) for name, (directory, pattern) in INPUT_PATTERNS.items()}


def build_digest(payloads: Mapping[str, Mapping[str, Any]], *, input_paths: Mapping[str, Path | None] | None = None) -> dict[str, Any]:
    packet_quality = payloads.get("packet_quality_report", {})
    quality_summary = packet_quality.get("qualitySummary") if isinstance(packet_quality.get("qualitySummary"), Mapping) else {}
    recall_summary = _summary(payloads.get("candidate_recall_diagnostic", {}))
    gate_summary = _summary(payloads.get("gate_trace_availability_audit", {}))
    fp_summary = _summary(payloads.get("false_positive_explanation_report", {}))
    guardrail_summary = _summary(payloads.get("false_positive_guardrail_audit", {}))
    readiness = payloads.get("gate_decision_readiness", {})
    readiness_classification = (
        readiness.get("final_readiness_classification")
        or readiness.get("readiness_classification")
        or readiness.get("classification")
        or readiness.get("finalReadinessClassification")
        or readiness.get("readinessClassification")
        or "unknown"
    )
    limitation_rows = [
        {
            "limitationId": "cache_only_or_funding_unknown",
            "count": quality_summary.get(
                "packetsWithCacheOnlyEvidence", recall_summary.get("cache_only_or_funding_unknown_packets", 0)
            ),
            "analystMeaning": "Funding/source context is unavailable or unknown in saved packets.",
            "doNotConclude": "Do not treat unknown funding as clean, suspicious, or absent funding.",
            "safeNextInspection": "Wait for operator-approved RPC capacity or inspect non-funding evidence only.",
        },
        {
            "limitationId": "retrospective_only",
            "count": quality_summary.get("packetsWithRetrospectiveOnlyEvidence", recall_summary.get("retrospective_only_packets", 0)),
            "analystMeaning": "Some packets rely on outcome-known context rather than live-detectable evidence.",
            "doNotConclude": "Do not use later correctness alone as live insider-style proof.",
            "safeNextInspection": "Separate pre-outcome timing/structure from after-the-fact correctness.",
        },
        {
            "limitationId": "gate_trace_or_source_weak",
            "count": gate_summary.get(
                "strongRiskGateTraceMissingCount",
                quality_summary.get("packetsWithMissingOrWeakSourceAttribution", 0),
            ),
            "analystMeaning": "Saved packet fields do not always expose exact gate/source trace.",
            "doNotConclude": "Do not treat missing display trace as a detector gate defect.",
            "safeNextInspection": "Use source paths and gate-trace audit rows before escalating.",
        },
        {
            "limitationId": "false_positive_advisory",
            "count": fp_summary.get(
                "packetsWithFalsePositiveAdvisoryMatches",
                quality_summary.get("packetsWithFalsePositiveAdvisoryMatches", 0),
            ),
            "analystMeaning": "Advisory patterns flag possible public-user/noise explanations.",
            "doNotConclude": "Do not automatically suppress, downgrade, reroute, rescore, admit, or reject packets.",
            "safeNextInspection": "Answer pattern-specific analyst questions and check independent hard evidence.",
        },
        {
            "limitationId": "large_dedupe_groups",
            "count": quality_summary.get("packetsWithLargeDedupeGroup", 0),
            "analystMeaning": "Duplicate-inflated saved rows can make evidence look broader than unique evidence.",
            "doNotConclude": "Do not drop production rows; dedupe remains reporting-only.",
            "safeNextInspection": "Prioritize unique wallet/market packets for human review.",
        },
    ]
    high_count = sum(1 for row in limitation_rows if int(row.get("count") or 0) > 0)
    paths = input_paths or {}
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "inputPaths": {key: str(value) if value else "" for key, value in paths.items()},
        "summary": {
            "limitationRowCount": len(limitation_rows),
            "activeLimitationCount": high_count,
            "packetCount": quality_summary.get("packetCount", packet_quality.get("packetCount", 0)),
            "readinessClassification": readiness_classification,
            "guardrailsPassed": guardrail_summary.get("guardrailsPassed", False),
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "automaticActionAllowed": False,
        },
        "limitationRows": limitation_rows,
        "analystBottomLine": (
            "Saved outputs are useful for review triage, but cache-only/funding-unknown, retrospective-only, "
            "gate-trace gaps, and advisory false-positive patterns mean they cannot justify production recall/gate changes."
        ),
        "safeUse": [
            "Use this digest to decide what to inspect manually before escalating a packet.",
            "Use it as a warning layer in handoff, not as scoring or routing input.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Analyst Evidence Limitation Digest",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Packet count: {summary.get('packetCount', 0)}",
        f"- Active limitations: {summary.get('activeLimitationCount', 0)}/{summary.get('limitationRowCount', 0)}",
        f"- Readiness classification: {summary.get('readinessClassification', 'unknown')}",
        f"- Guardrails passed: {summary.get('guardrailsPassed', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Limitation Rows",
    ]
    for row in payload.get("limitationRows") or []:
        if isinstance(row, Mapping):
            lines.extend(
                [
                    f"- `{row.get('limitationId', '')}`: {row.get('count', 0)}",
                    f"  - analyst meaning: {row.get('analystMeaning', '')}",
                    f"  - do not conclude: {row.get('doNotConclude', '')}",
                    f"  - safe next inspection: {row.get('safeNextInspection', '')}",
                ]
            )
    lines.extend(["", "## Bottom Line", str(payload.get("analystBottomLine", "")), "", "## Safe Use"])
    for item in payload.get("safeUse") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"analyst_evidence_limitation_digest_{stamp}.json"
    markdown_path = resolved / f"analyst_evidence_limitation_digest_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a read-only analyst evidence limitation digest.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    paths = discover_inputs()
    payload = build_digest({name: _load_json(path) for name, path in paths.items()}, input_paths=paths)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Evidence limitation digest JSON: {outputs['json_path']}")
    print(f"Evidence limitation digest markdown: {outputs['markdown_path']}")
    print(f"Active limitations: {payload.get('summary', {}).get('activeLimitationCount', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
