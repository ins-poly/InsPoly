from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUALITY_OUTPUT_DIR = Path("analyst_quality_outputs")
DEFAULT_BUNDLE_OUTPUT_DIR = Path("analyst_review_bundles")
DEFAULT_MANIFEST_OUTPUT_DIR = Path("artifact_manifests")

ARTIFACT_PATTERNS = {
    "unique_review_packets": ("review_packets", "unique_review_packets_*.json"),
    "unique_review_packets_md": ("review_packets", "unique_review_packets_*.md"),
    "review_packet_quality": ("analyst_quality_outputs", "review_packet_quality_check_*.json"),
    "packet_quality_report": ("analyst_quality_outputs", "packet_quality_report_*.json"),
    "packet_group_drilldown": ("analyst_quality_outputs", "packet_group_drilldown_*.json"),
    "analyst_evidence_limitation_digest": ("analyst_quality_outputs", "analyst_evidence_limitation_digest_*.json"),
    "analyst_readiness_cycle_summary": ("analyst_quality_outputs", "analyst_readiness_cycle_summary_*.json"),
    "wallet_review_queue": ("analyst_quality_outputs", "wallet_review_queue_*.json"),
    "analyst_decision_sidecar": ("analyst_sidecars", "analyst_decision_sidecar_*.json"),
    "analyst_handoff_bundle": ("analyst_review_bundles", "analyst_review_bundle_*.json"),
    "artifact_manifest": ("artifact_manifests", "review_artifact_manifest_*.json"),
    "review_artifact_freshness_report": ("artifact_manifests", "review_artifact_freshness_report_*.json"),
    "review_output_index": ("review_index_outputs", "review_output_index_*.json"),
    "false_positive_library": ("false_positive_library", "false_positive_pattern_library_*.json"),
    "false_positive_explanation_report": ("false_positive_library", "false_positive_explanation_report_*.json"),
    "false_positive_guardrail_audit": ("false_positive_library", "false_positive_guardrail_audit_*.json"),
    "source_attribution_completeness": ("source_attribution_outputs", "source_attribution_completeness_*.json"),
    "source_schema_repair_plan": ("source_schema_repair_outputs", "source_schema_repair_plan_*.json"),
    "gate_trace_availability_audit": ("source_schema_repair_outputs", "gate_trace_availability_audit_*.json"),
    "schema_normalization_check": ("schema_normalization_outputs", "review_schema_normalization_check_*.json"),
    "candidate_recall_diagnostic": ("candidate_recall_outputs", "candidate_recall_diagnostic_*.json"),
    "implementation_boundary": ("implementation_boundaries", "implementation_boundary_*.json"),
    "analyst_crosswalk": ("implementation_boundaries", "analyst_crosswalk_*.json"),
    "reporting_schema_patch_report": ("implementation_boundaries", "reporting_schema_patch_report_*.json"),
    "review_packet_case_reviewer_compare": ("review_packet_compare_outputs", "review_packet_case_reviewer_compare_*.json"),
    "strategic_backlog_dashboard": ("strategic_backlog_outputs", "strategic_backlog_dashboard_*.json"),
    "strategic_next_action": ("strategic_backlog_outputs", "strategic_next_action_*.json"),
    "gate_decision_readiness": ("validation_corpus_outputs", "gate_decision_readiness_*.json"),
    "operator_rpc_recovery_package": ("validation_corpus_outputs", "operator_rpc_capacity_recovery_package_*.json"),
}

REQUIRED_MANIFEST_ARTIFACTS = (
    "packet_quality_report",
    "unique_review_packets",
    "analyst_handoff_bundle",
    "review_output_index",
    "false_positive_library",
    "source_schema_repair_plan",
    "candidate_recall_diagnostic",
)


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _latest_file(directory: str | Path, pattern: str) -> Path | None:
    root = _resolve(directory) or Path(directory)
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
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "confirmed"}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return not bool(value)
    return str(value).strip().lower() in {"", "unknown", "missing", "none", "null", "n/a"}


def _first_string(mapping: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _string(mapping.get(key))
        if value:
            return value
    return ""


def discover_latest_artifacts() -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for name, (directory, pattern) in ARTIFACT_PATTERNS.items():
        path = _latest_file(directory, pattern)
        artifacts[name] = str(path) if path else ""
    return artifacts


def build_diagnostic_context(artifacts: Mapping[str, str]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for name in (
        "implementation_boundary",
        "analyst_crosswalk",
        "source_schema_repair_plan",
        "candidate_recall_diagnostic",
        "false_positive_library",
        "reporting_schema_patch_report",
    ):
        path = _resolve(artifacts.get(name)) if artifacts.get(name) else None
        payload = _load_json(path)
        summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
        if not payload and not summary:
            continue
        if name == "source_schema_repair_plan":
            context[name] = {
                "path": str(path) if path else "",
                "field_count": summary.get("field_count", 0),
                "high_priority_field_count": summary.get("high_priority_field_count", 0),
                "total_combined_missing_fields": summary.get("total_combined_missing_fields", 0),
                "top_fields": [
                    {
                        "field": action.get("field", ""),
                        "priority": action.get("priority", ""),
                        "combined_missing_count": action.get("combined_missing_count", 0),
                    }
                    for action in (payload.get("field_actions") or [])[:5]
                    if isinstance(action, Mapping)
                ],
            }
        elif name == "candidate_recall_diagnostic":
            context[name] = {
                "path": str(path) if path else "",
                "diagnostic_interpretation": payload.get("diagnostic_interpretation", ""),
                "fresh_validation_required": summary.get("fresh_validation_required", False),
                "model_behavior_changed": summary.get("model_behavior_changed", False),
            }
        elif name == "false_positive_library":
            context[name] = {
                "path": str(path) if path else "",
                "pattern_count": summary.get("pattern_count", 0),
                "likely_false_positive_examples": summary.get("case_reviewer_likely_false_positive_examples", 0),
                "top_patterns": summary.get("top_patterns", [])[:5],
                "advisory_only": True,
            }
        elif name == "implementation_boundary":
            context[name] = {
                "path": str(path) if path else "",
                "issue_count": summary.get("issue_count", 0),
                "safe_fix_count": summary.get("safe_fix_count", 0),
                "category_counts": summary.get("category_counts", {}),
                "model_behavior_changed": summary.get("model_behavior_changed", False),
            }
        elif name == "analyst_crosswalk":
            context[name] = {
                "path": str(path) if path else "",
                "crosswalk_count": summary.get("crosswalk_count", 0),
                "model_behavior_changed": summary.get("model_behavior_changed", False),
            }
        elif name == "reporting_schema_patch_report":
            context[name] = {
                "path": str(path) if path else "",
                "selected_issue_count": summary.get("selected_issue_count", 0),
                "safe_fixes_implemented": summary.get("safe_fixes_implemented", 0),
                "model_behavior_changed": summary.get("model_behavior_changed", False),
            }
    return context


def _packets(packet_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    packets = packet_payload.get("packets")
    if not isinstance(packets, list):
        return []
    return [dict(packet) for packet in packets if isinstance(packet, Mapping)]


def build_quality_check(packet_payload: Mapping[str, Any], *, source_path: Path | None = None) -> dict[str, Any]:
    packets = _packets(packet_payload)
    field_checks = {
        "wallet": lambda packet: bool(_string(packet.get("wallet"))),
        "market_or_condition": lambda packet: bool(_string(packet.get("market")) or _string(packet.get("condition_id"))),
        "source_path": lambda packet: bool(_string(packet.get("source_path"))),
        "links": lambda packet: bool(packet.get("links")) if isinstance(packet.get("links"), Mapping) else False,
        "why_this_matters": lambda packet: bool(packet.get("why_this_matters")),
        "why_this_may_be_false_positive": lambda packet: bool(packet.get("why_this_may_be_false_positive")),
        "what_to_inspect_next": lambda packet: bool(packet.get("what_to_inspect_next")),
        "funding_evidence_grade": lambda packet: bool(_string(packet.get("funding_evidence_grade"))),
        "gate_or_hard_evidence": lambda packet: bool(
            _string(packet.get("gate_family"))
            or _string(packet.get("strong_risk_gate_type"))
            or packet.get("hard_evidence_sources")
        ),
    }
    coverage = {}
    packet_count = len(packets)
    for name, checker in field_checks.items():
        present = sum(1 for packet in packets if checker(packet))
        coverage[name] = {
            "present": present,
            "missing": packet_count - present,
            "coverage_ratio": round(present / packet_count, 4) if packet_count else 0.0,
        }
    missing_samples = []
    for packet in packets:
        missing = [name for name, checker in field_checks.items() if not checker(packet)]
        if missing:
            missing_samples.append(
                {
                    "packet_id": packet.get("packet_id", ""),
                    "wallet": packet.get("wallet", ""),
                    "missing_fields": missing,
                }
            )
    return {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(),
            "source_path": str(source_path) if source_path else "",
            "packet_count": packet_count,
            "packets_with_any_missing_quality_field": len(missing_samples),
            "read_only": True,
            "model_behavior_changed": False,
        },
        "field_coverage": coverage,
        "missing_samples": missing_samples[:50],
        "limitations": [
            "This checks saved packet completeness only.",
            "Missing fields are review-quality issues, not production label changes.",
            "No scoring, gate, HER routing, or funding eligibility behavior is changed.",
        ],
    }


def _packet_links(packet: Mapping[str, Any]) -> dict[str, str]:
    links = packet.get("links")
    if not isinstance(links, Mapping):
        return {}
    return {str(key): str(value) for key, value in links.items() if str(value or "").strip()}


def _source_artifact_links(packet: Mapping[str, Any]) -> dict[str, Any]:
    links: dict[str, Any] = {}
    packet_links = _packet_links(packet)
    if packet_links:
        links["external"] = packet_links
    source_path = _first_string(packet, "source_path", "sourcePath")
    if source_path:
        links["source_path"] = source_path
    source_row = _first_string(packet, "source_row", "sourceRow")
    if source_row:
        links["source_row"] = source_row
    source_navigation = packet.get("source_navigation")
    if isinstance(source_navigation, Mapping):
        for key in ("source_path", "source_row", "source_collections", "trade_id", "wallet", "market", "condition_id"):
            value = source_navigation.get(key)
            if value:
                links[f"source_navigation.{key}"] = value
    source_collections = packet.get("source_collections")
    if source_collections:
        links["source_collections"] = source_collections
    return links


def _false_positive_matches(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for item in _listify(packet.get("false_positive_advisory")):
        if not isinstance(item, Mapping):
            continue
        pattern = _string(item.get("pattern"))
        if not pattern:
            continue
        matches.append(
            {
                "pattern": pattern,
                "issueId": _string(item.get("issue_id")),
                "message": _string(item.get("message")),
                "analystQuestion": _string(item.get("analyst_question")),
                "automaticActionAllowed": False,
                "forbiddenUse": _string(item.get("forbidden_use"))
                or "Do not suppress, downgrade, rescore, reroute, or change eligibility from this advisory.",
            }
        )
    return matches


def _packet_flags(packet: Mapping[str, Any]) -> dict[str, bool]:
    group = _string(packet.get("group")).lower()
    judgment = _string(packet.get("judgment")).lower()
    severity = _string(packet.get("severity")).lower()
    hard_sources = [item for item in _listify(packet.get("hard_evidence_sources")) if _string(item)]
    strong_risk = group in {"strong_risk", "overlap"} or "strong risk" in judgment or severity == "strong risk"
    her = group in {"hard_evidence_review", "overlap"} or bool(hard_sources)
    overlap = group == "overlap" or (strong_risk and her)
    return {"strongRisk": strong_risk, "hardEvidenceReview": her, "overlap": overlap}


def _missing_critical_fields(packet: Mapping[str, Any], flags: Mapping[str, bool]) -> list[str]:
    links = _packet_links(packet)
    source_links = _source_artifact_links(packet)
    hard_sources = [item for item in _listify(packet.get("hard_evidence_sources")) if _string(item)]
    missing = []
    if _is_missing(packet.get("packet_id")):
        missing.append("packet_id")
    if _is_missing(packet.get("wallet")):
        missing.append("wallet")
    if _is_missing(packet.get("trader_name")):
        missing.append("trader_name")
    if _is_missing(packet.get("market")) and _is_missing(packet.get("target")):
        missing.append("market_or_event")
    if _is_missing(packet.get("condition_id")):
        missing.append("condition_id")
    if _is_missing(packet.get("trade_id")):
        missing.append("trade_id")
    if not links.get("polygonscan_wallet"):
        missing.append("wallet_link")
    if not any("polymarket" in key.lower() or "market" in key.lower() for key in links):
        missing.append("market_link")
    if not source_links:
        missing.append("source_artifact_link")
    if flags.get("strongRisk") and _is_missing(packet.get("strong_risk_exact_gate_branch")):
        missing.append("exact_gate_branch")
    if (flags.get("strongRisk") or flags.get("hardEvidenceReview")) and not hard_sources:
        missing.append("hard_evidence_sources")
    if _is_missing(packet.get("why_this_matters")):
        missing.append("why_suspicious")
    if _is_missing(packet.get("why_this_may_be_false_positive")):
        missing.append("why_maybe_false_positive")
    if _is_missing(packet.get("what_to_inspect_next")):
        missing.append("what_to_inspect_next")
    return missing


def _cache_only_warning(packet: Mapping[str, Any], false_positive_matches: Sequence[Mapping[str, Any]]) -> str:
    funding_grade = _string(packet.get("funding_evidence_grade")).lower()
    suspicious_funding = _string(packet.get("suspicious_funding_quality") or packet.get("suspiciousFundingQuality")).lower()
    patterns = {str(item.get("pattern") or "") for item in false_positive_matches}
    if funding_grade in {"", "unknown", "none", "missing", "null"} or suspicious_funding in {"unknown", "missing"}:
        return "Funding/source context is unavailable or unknown in saved packets; treat as cache-only limitation, not clean funding evidence."
    if "funding_unknown" in patterns:
        return "False-positive advisory marks funding as unknown; fresh trace-enabled validation is required before funding conclusions."
    return ""


def _source_attribution_warning(packet: Mapping[str, Any], flags: Mapping[str, bool]) -> str:
    hard_sources = [item for item in _listify(packet.get("hard_evidence_sources")) if _string(item)]
    gate_trace_available = packet.get("gate_trace_available")
    source_links = _source_artifact_links(packet)
    critical_warnings = packet.get("critical_field_warnings")
    warning_ids = {
        _string(item.get("issue_id"))
        for item in _listify(critical_warnings)
        if isinstance(item, Mapping) and _string(item.get("issue_id"))
    }
    if flags.get("strongRisk") and not hard_sources:
        return "Strong Risk packet has no accepted hard-evidence sources saved; verify source artifacts before escalation."
    if flags.get("hardEvidenceReview") and not hard_sources:
        return "HER packet has no accepted hard-evidence sources saved in this packet view; verify source propagation."
    if gate_trace_available is False or gate_trace_available is None or "SCHEMA-001" in warning_ids:
        return "Gate/source attribution is incomplete in saved packet fields."
    if not source_links:
        return "No source artifact navigation is saved for this packet."
    return ""


def _analyst_priority(
    packet: Mapping[str, Any],
    flags: Mapping[str, bool],
    *,
    missing_critical_fields: Sequence[str],
    false_positive_matches: Sequence[Mapping[str, Any]],
    cache_only_warning: str,
    retrospective_only_warning: str,
    source_attribution_warning: str,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    dedupe_group_size = _safe_int(packet.get("dedupe_group_size"), 1)
    score = _safe_float(packet.get("score"))
    if flags.get("overlap"):
        reasons.append("Strong Risk/HER overlap should be reviewed early.")
    if flags.get("hardEvidenceReview"):
        reasons.append("Hard Evidence Review material is present.")
    if flags.get("strongRisk"):
        reasons.append("Strong Risk packet is analyst-relevant.")
    if dedupe_group_size >= 5:
        reasons.append(f"Large dedupe group size ({dedupe_group_size}) can indicate repeated saved evidence.")
    if score is not None and score >= 90:
        reasons.append(f"High saved score ({score:g}) merits source verification.")
    if source_attribution_warning:
        reasons.append("Source attribution weakness needs analyst verification.")
    if missing_critical_fields:
        reasons.append("High-value packet fields are missing.")
    if cache_only_warning:
        reasons.append("Funding/source evidence is cache-only or unknown.")
    if retrospective_only_warning:
        reasons.append("Retrospective-only evidence must be separated from live-detectable lead quality.")
    if false_positive_matches:
        reasons.append("False-positive advisory patterns require caution before escalation.")

    if flags.get("overlap") or flags.get("hardEvidenceReview") or (
        flags.get("strongRisk") and (dedupe_group_size >= 5 or source_attribution_warning)
    ):
        priority = "high"
    elif flags.get("strongRisk") or false_positive_matches or cache_only_warning or retrospective_only_warning:
        priority = "medium"
    else:
        priority = "standard"
    return priority, reasons


def build_packet_quality_report(packet_payload: Mapping[str, Any], *, source_path: Path | None = None) -> dict[str, Any]:
    packets = _packets(packet_payload)
    rows: list[dict[str, Any]] = []
    warning_counter: Counter[str] = Counter()
    advisory_counter: Counter[str] = Counter()
    priority_counter: Counter[str] = Counter()
    for packet in packets:
        flags = _packet_flags(packet)
        false_positive_matches = _false_positive_matches(packet)
        for match in false_positive_matches:
            advisory_counter.update([str(match.get("pattern") or "unknown")])
        missing_critical_fields = _missing_critical_fields(packet, flags)
        cache_only_warning = _cache_only_warning(packet, false_positive_matches)
        retrospective_only_warning = (
            "Packet is marked retrospective-only; do not treat outcome correctness as live-detectable proof."
            if _truthy(packet.get("retrospective_only"))
            else ""
        )
        source_attribution_warning = _source_attribution_warning(packet, flags)
        links = _packet_links(packet)
        missing_wallet_link = not bool(links.get("polygonscan_wallet"))
        missing_market_link = not any("polymarket" in key.lower() or "market" in key.lower() for key in links)
        dedupe_group_size = _safe_int(packet.get("dedupe_group_size"), 1)
        large_dedupe_group = dedupe_group_size >= 5
        priority, priority_reasons = _analyst_priority(
            packet,
            flags,
            missing_critical_fields=missing_critical_fields,
            false_positive_matches=false_positive_matches,
            cache_only_warning=cache_only_warning,
            retrospective_only_warning=retrospective_only_warning,
            source_attribution_warning=source_attribution_warning,
        )
        priority_counter.update([priority])
        if missing_critical_fields:
            warning_counter.update(["missing_high_value_fields"])
        if cache_only_warning:
            warning_counter.update(["cache_only_or_funding_unknown"])
        if retrospective_only_warning:
            warning_counter.update(["retrospective_only"])
        if source_attribution_warning:
            warning_counter.update(["missing_or_weak_source_attribution"])
        if missing_wallet_link:
            warning_counter.update(["missing_wallet_link"])
        if missing_market_link:
            warning_counter.update(["missing_market_link"])
        if false_positive_matches:
            warning_counter.update(["false_positive_advisory"])
        if flags["overlap"]:
            warning_counter.update(["strong_risk_her_overlap"])
        if large_dedupe_group:
            warning_counter.update(["large_dedupe_group"])

        row = {
            "packetId": _first_string(packet, "packet_id") or "unknown",
            "wallet": _first_string(packet, "wallet") or "unknown",
            "traderName": _first_string(packet, "trader_name", "traderName") or "unknown",
            "marketOrEvent": _first_string(packet, "market", "target") or "unknown",
            "strongRiskFlag": flags["strongRisk"],
            "hardEvidenceReviewFlag": flags["hardEvidenceReview"],
            "overlapFlag": flags["overlap"],
            "exactGateBranch": _first_string(packet, "strong_risk_exact_gate_branch", "gate_branch") or "missing",
            "hardEvidenceSources": [str(item) for item in _listify(packet.get("hard_evidence_sources")) if _string(item)],
            "fundingQuality": _first_string(packet, "funding_evidence_grade", "fundingEvidenceGrade") or "unknown",
            "suspiciousFundingQuality": _first_string(packet, "suspicious_funding_quality", "suspiciousFundingQuality") or "unknown",
            "suppressorConflicts": {
                "suppressorConflict": bool(packet.get("suppressor_conflict")),
                "suppressors": [str(item) for item in _listify(packet.get("suppressors")) if _string(item)],
            },
            "falsePositiveAdvisoryMatches": false_positive_matches,
            "missingCriticalFields": missing_critical_fields,
            "cacheOnlyWarning": cache_only_warning,
            "retrospectiveOnlyWarning": retrospective_only_warning,
            "sourceAttributionWarning": source_attribution_warning,
            "missingWalletLink": missing_wallet_link,
            "missingMarketLink": missing_market_link,
            "dedupeGroupSize": dedupe_group_size,
            "largeDedupeGroup": large_dedupe_group,
            "analystPriority": priority,
            "analystPriorityReasons": priority_reasons,
            "whySuspicious": [str(item) for item in _listify(packet.get("why_this_matters")) if _string(item)],
            "whyMaybeFalsePositive": [
                str(item) for item in _listify(packet.get("why_this_may_be_false_positive")) if _string(item)
            ],
            "whatToInspectNext": [str(item) for item in _listify(packet.get("what_to_inspect_next")) if _string(item)],
            "availableArtifactLinks": _source_artifact_links(packet),
            "readOnlyReportingOnly": True,
        }
        rows.append(row)

    priority_queue = [
        row
        for row in sorted(
            rows,
            key=lambda item: (
                {"high": 0, "medium": 1, "standard": 2}.get(str(item.get("analystPriority")), 3),
                -_safe_int(item.get("dedupeGroupSize"), 1),
                str(item.get("packetId") or ""),
            ),
        )
        if row.get("analystPriority") in {"high", "medium"}
    ]
    quality_summary = {
        "packetCount": len(rows),
        "strongRiskPackets": sum(1 for row in rows if row["strongRiskFlag"]),
        "hardEvidenceReviewPackets": sum(1 for row in rows if row["hardEvidenceReviewFlag"]),
        "overlapPackets": sum(1 for row in rows if row["overlapFlag"]),
        "packetsWithMissingHighValueFields": warning_counter.get("missing_high_value_fields", 0),
        "packetsWithCacheOnlyEvidence": warning_counter.get("cache_only_or_funding_unknown", 0),
        "packetsWithRetrospectiveOnlyEvidence": warning_counter.get("retrospective_only", 0),
        "packetsWithMissingOrWeakSourceAttribution": warning_counter.get("missing_or_weak_source_attribution", 0),
        "packetsWithMissingWalletLinks": warning_counter.get("missing_wallet_link", 0),
        "packetsWithMissingMarketLinks": warning_counter.get("missing_market_link", 0),
        "packetsWithFalsePositiveAdvisoryMatches": warning_counter.get("false_positive_advisory", 0),
        "packetsWithLargeDedupeGroup": warning_counter.get("large_dedupe_group", 0),
        "priorityReviewQueueCount": len(priority_queue),
        "analystPriorityCounts": dict(sorted(priority_counter.items())),
        "readOnly": True,
        "modelBehaviorChanged": False,
    }
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourceReviewPacketsPath": str(source_path) if source_path else "",
        "packetCount": len(rows),
        "qualitySummary": quality_summary,
        "warningsSummary": {
            "warningCounts": dict(sorted(warning_counter.items())),
            "falsePositiveAdvisoryPatternCounts": dict(sorted(advisory_counter.items())),
            "automaticActionAllowed": False,
            "falsePositiveLibraryUsedForScoring": False,
        },
        "priorityReviewQueue": priority_queue[:50],
        "packetQualityRows": rows,
        "limitations": [
            "This report classifies saved review-packet quality only.",
            "It does not change scores, gates, labels, HER routing, funding eligibility, candidate admission, or production severity.",
            "False-positive advisory matches are analyst cautions only and cannot suppress, downgrade, reroute, rescore, or change eligibility.",
            "Cache-only and retrospective-only evidence must not be overclaimed as fresh trace-enabled proof.",
        ],
        "safety": {
            "readOnlyReportingOnly": True,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "falsePositiveLibraryUsedForScoring": False,
        },
    }


def _group_suppressor_names(group: Mapping[str, Any]) -> list[str]:
    return [
        _string(item.get("name"))
        for item in _listify(group.get("suppressor_themes"))
        if isinstance(item, Mapping) and _string(item.get("name"))
    ]


def _group_priority(group: Mapping[str, Any], *, group_type: str) -> tuple[str, list[str]]:
    reasons = []
    packet_count = _safe_int(group.get("packet_count"))
    wallet_count = _safe_int(group.get("wallet_count"))
    market_count = _safe_int(group.get("market_count"))
    strong = _safe_int(group.get("strong_risk_packet_count"))
    her = _safe_int(group.get("hard_evidence_review_packet_count"))
    overlap = _safe_int(group.get("overlap_packet_count"))
    dedupe_total = _safe_int(group.get("dedupe_group_size_total"))
    if her:
        reasons.append(f"{her} Hard Evidence Review packet(s) in this group.")
    if overlap:
        reasons.append(f"{overlap} Strong Risk/HER overlap packet(s) in this group.")
    if strong:
        reasons.append(f"{strong} Strong Risk packet(s) in this group.")
    if packet_count >= 5:
        reasons.append(f"{packet_count} packet(s) create a repeated-review cluster.")
    if group_type == "wallet" and market_count >= 3:
        reasons.append(f"Wallet appears across {market_count} market(s).")
    if group_type == "market" and wallet_count >= 5:
        reasons.append(f"Market has {wallet_count} distinct wallet(s) in saved packets.")
    if dedupe_total >= 10:
        reasons.append(f"Dedupe group total is {dedupe_total}.")
    suppressors = _group_suppressor_names(group)
    if suppressors:
        reasons.append("False-positive advisory themes: " + ", ".join(suppressors[:5]) + ".")
    if her or overlap or packet_count >= 5 or market_count >= 3 or wallet_count >= 5:
        return "high", reasons
    if strong or packet_count >= 2:
        return "medium", reasons or ["Saved group has repeated review relevance."]
    return "standard", reasons or ["Single saved group; inspect only if packet context warrants it."]


def build_packet_group_drilldown(packet_payload: Mapping[str, Any], *, source_path: Path | None = None) -> dict[str, Any]:
    wallet_rows = []
    for group in packet_payload.get("wallet_groups") or []:
        if not isinstance(group, Mapping):
            continue
        priority, reasons = _group_priority(group, group_type="wallet")
        wallet_rows.append(
            {
                "groupType": "wallet",
                "wallet": _string(group.get("wallet")) or "unknown",
                "walletLink": _string(group.get("wallet_link")),
                "packetCount": _safe_int(group.get("packet_count")),
                "marketCount": _safe_int(group.get("market_count")),
                "markets": [str(item) for item in _listify(group.get("markets")) if _string(item)],
                "strongRiskPacketCount": _safe_int(group.get("strong_risk_packet_count")),
                "hardEvidenceReviewPacketCount": _safe_int(group.get("hard_evidence_review_packet_count")),
                "overlapPacketCount": _safe_int(group.get("overlap_packet_count")),
                "dedupeGroupSizeTotal": _safe_int(group.get("dedupe_group_size_total")),
                "maxScore": group.get("max_score"),
                "packetIds": [str(item) for item in _listify(group.get("packet_ids")) if _string(item)],
                "falsePositiveAdvisoryThemes": _group_suppressor_names(group),
                "analystPriority": priority,
                "analystPriorityReasons": reasons,
                "readOnlyReportingOnly": True,
            }
        )
    market_rows = []
    for group in packet_payload.get("market_groups") or []:
        if not isinstance(group, Mapping):
            continue
        priority, reasons = _group_priority(group, group_type="market")
        market_rows.append(
            {
                "groupType": "market",
                "market": _string(group.get("market")) or "unknown",
                "marketKey": _string(group.get("market_key")) or "unknown",
                "polymarketLink": _string(group.get("polymarket_link")),
                "packetCount": _safe_int(group.get("packet_count")),
                "walletCount": _safe_int(group.get("wallet_count")),
                "wallets": [str(item) for item in _listify(group.get("wallets")) if _string(item)],
                "strongRiskPacketCount": _safe_int(group.get("strong_risk_packet_count")),
                "hardEvidenceReviewPacketCount": _safe_int(group.get("hard_evidence_review_packet_count")),
                "overlapPacketCount": _safe_int(group.get("overlap_packet_count")),
                "maxScore": group.get("max_score"),
                "packetIds": [str(item) for item in _listify(group.get("packet_ids")) if _string(item)],
                "falsePositiveAdvisoryThemes": _group_suppressor_names(group),
                "analystPriority": priority,
                "analystPriorityReasons": reasons,
                "readOnlyReportingOnly": True,
            }
        )
    wallet_rows.sort(key=lambda row: ({"high": 0, "medium": 1, "standard": 2}.get(row["analystPriority"], 3), -row["packetCount"], -row["marketCount"], row["wallet"]))
    market_rows.sort(key=lambda row: ({"high": 0, "medium": 1, "standard": 2}.get(row["analystPriority"], 3), -row["packetCount"], -row["walletCount"], row["market"]))
    priority_counts = Counter(row["analystPriority"] for row in wallet_rows + market_rows)
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourceReviewPacketsPath": str(source_path) if source_path else "",
        "summary": {
            "walletGroupCount": len(wallet_rows),
            "marketGroupCount": len(market_rows),
            "highPriorityGroupCount": priority_counts.get("high", 0),
            "mediumPriorityGroupCount": priority_counts.get("medium", 0),
            "readOnly": True,
            "modelBehaviorChanged": False,
            "productionPriorityChanged": False,
        },
        "walletGroups": wallet_rows,
        "marketGroups": market_rows,
        "limitations": [
            "Group priority is an analyst navigation aid only.",
            "Grouping never drops production rows and never changes severity, scoring, gates, HER routing, funding eligibility, or candidate admission.",
            "False-positive advisory themes are review questions only, not suppressor logic.",
        ],
    }
def build_wallet_queue(packet_payload: Mapping[str, Any], *, source_path: Path | None = None) -> dict[str, Any]:
    wallet_groups = packet_payload.get("wallet_groups")
    if not isinstance(wallet_groups, list):
        wallet_groups = []
    queue = []
    for group in wallet_groups:
        if not isinstance(group, Mapping):
            continue
        suppressors = [
            _string(item.get("name"))
            for item in group.get("suppressor_themes", [])
            if isinstance(item, Mapping) and _string(item.get("name"))
        ]
        queue.append(
            {
                "wallet": group.get("wallet", ""),
                "packet_count": int(group.get("packet_count") or 0),
                "market_count": int(group.get("market_count") or 0),
                "strong_risk_packet_count": int(group.get("strong_risk_packet_count") or 0),
                "hard_evidence_review_packet_count": int(group.get("hard_evidence_review_packet_count") or 0),
                "max_score": group.get("max_score"),
                "wallet_link": group.get("wallet_link", ""),
                "suppressor_themes": group.get("suppressor_themes", []),
                "packet_ids": group.get("packet_ids", []),
                "advisory_review_reason": _wallet_queue_reason(group, suppressors),
                "advisory_caution": _wallet_queue_caution(suppressors),
            }
        )
    queue.sort(
        key=lambda item: (
            -int(item["hard_evidence_review_packet_count"]),
            -int(item["packet_count"]),
            -int(item["market_count"]),
            -(float(item["max_score"]) if item.get("max_score") is not None else -1),
            str(item["wallet"]),
        )
    )
    for index, item in enumerate(queue, start=1):
        item["queue_rank"] = index
    return {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(),
            "source_path": str(source_path) if source_path else "",
            "wallet_count": len(queue),
            "advisory_only": True,
            "production_priority_changed": False,
        },
        "wallet_queue": queue,
        "limitations": [
            "Queue rank is derived from saved review-packet grouping only.",
            "It is an analyst workflow aid, not a production severity label.",
            "Funding unknown remains unknown until fresh trace-enabled validation is available.",
        ],
    }


def _wallet_queue_reason(group: Mapping[str, Any], suppressors: Sequence[str]) -> str:
    if int(group.get("hard_evidence_review_packet_count") or 0) > 0:
        return "Review early because saved packets include Hard Evidence Review material."
    if int(group.get("packet_count") or 0) > 1:
        return "Review as a repeated saved-packet wallet across one or more markets."
    if "high_volume_public_user" in suppressors:
        return "Review mainly to confirm whether high-volume public behavior explains the packet."
    return "Review as a single saved local packet with standard verification steps."


def _wallet_queue_caution(suppressors: Sequence[str]) -> str:
    if "high_volume_public_user" in suppressors:
        return "High-volume public-user suppressor is present; do not overclaim insider style without independent evidence."
    if "near_certainty" in suppressors or "stale_or_resolution_gap" in suppressors:
        return "Near-certainty or stale-resolution context may explain the saved concern."
    return "Confirm source fields, funding status, and hard-evidence sources before escalation."


def build_handoff_bundle(
    artifacts: Mapping[str, str],
    packet_payload: Mapping[str, Any],
    quality_payload: Mapping[str, Any],
    queue_payload: Mapping[str, Any],
    diagnostic_context: Mapping[str, Any] | None = None,
    manifest_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    packet_summary = packet_payload.get("summary") if isinstance(packet_payload.get("summary"), Mapping) else {}
    quality_summary = quality_payload.get("summary") if isinstance(quality_payload.get("summary"), Mapping) else {}
    queue_summary = queue_payload.get("summary") if isinstance(queue_payload.get("summary"), Mapping) else {}
    return {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(),
            "packet_count": packet_summary.get("unique_packet_count", 0),
            "wallet_group_count": packet_summary.get("wallet_group_count", 0),
            "market_group_count": packet_summary.get("market_group_count", 0),
            "quality_missing_packet_count": quality_summary.get("packets_with_any_missing_quality_field", 0),
            "wallet_queue_count": queue_summary.get("wallet_count", 0),
            "diagnostic_context_count": len(diagnostic_context or {}),
            "manifest_artifact_count": (manifest_summary or {}).get("artifact_count", 0),
            "manifest_missing_artifact_count": (manifest_summary or {}).get("missing_artifact_count", 0),
            "manifest_hash_covered_artifact_count": (manifest_summary or {}).get("hash_covered_artifact_count", 0),
            "read_only": True,
            "model_behavior_changed": False,
            "current_blocker": "RPC/funding validation remains blocked unless latest readiness says otherwise.",
        },
        "artifact_paths": dict(artifacts),
        "manifest_summary": dict(manifest_summary or {}),
        "diagnostic_context": dict(diagnostic_context or {}),
        "top_wallet_queue": (queue_payload.get("wallet_queue") or [])[:10],
        "limitations": [
            "This bundle packages local saved review artifacts only.",
            "It is suitable for analyst handoff, not for changing detector behavior.",
            "Cache-only evidence must not be described as fresh funding-enabled proof.",
        ],
    }


def _manifest_summary_from_entries(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    required_status = {}
    for name in REQUIRED_MANIFEST_ARTIFACTS:
        match = next((item for item in entries if item.get("name") == name), None)
        required_status[name] = bool(match and match.get("exists"))
    missing_required = [name for name, exists in required_status.items() if not exists]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "artifact_count": len(entries),
        "existing_artifact_count": sum(1 for item in entries if item.get("exists")),
        "missing_artifact_count": sum(1 for item in entries if not item.get("exists")),
        "hash_covered_artifact_count": sum(1 for item in entries if item.get("exists") and item.get("sha256")),
        "required_artifact_status": required_status,
        "missing_required_artifacts": missing_required,
        "read_only": True,
        "old_outputs_mutated": False,
    }


def build_manifest_preview(artifacts: Mapping[str, str]) -> dict[str, Any]:
    entries = []
    for name, path_text in sorted(artifacts.items()):
        path = _resolve(path_text) if path_text else None
        exists = bool(path and path.exists() and path.is_file())
        entries.append(
            {
                "name": name,
                "path": path_text,
                "exists": exists,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if exists and path else "",
            }
        )
    return _manifest_summary_from_entries(entries)


def build_artifact_manifest(artifacts: Mapping[str, str]) -> dict[str, Any]:
    entries = []
    for name, path_text in sorted(artifacts.items()):
        path = _resolve(path_text) if path_text else None
        if not path or not path.exists() or not path.is_file():
            entries.append({"name": name, "path": path_text, "exists": False, "sha256": ""})
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        stat = path.stat()
        entries.append(
            {
                "name": name,
                "path": str(path),
                "exists": True,
                "size_bytes": stat.st_size,
                "modified_time": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                "sha256": digest,
            }
        )
    summary = _manifest_summary_from_entries(entries)
    return {
        "summary": summary,
        "artifacts": entries,
        "limitations": [
            "Hashes document artifact identity at generation time.",
            "This manifest does not lock files or rewrite historical outputs.",
            "Manifest metadata is for analyst provenance only and is never used for scoring, routing, suppression, or eligibility.",
        ],
    }


def _render_key_values(title: str, summary: Mapping[str, Any]) -> list[str]:
    lines = [f"# {title}", ""]
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")
    return lines


def render_quality_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = _render_key_values("Review Packet Quality Check", summary)
    lines.extend(["", "## Field Coverage"])
    for field, values in (payload.get("field_coverage") or {}).items():
        lines.append(
            f"- {field}: {values.get('present', 0)} present / {values.get('missing', 0)} missing "
            f"({values.get('coverage_ratio', 0)})"
        )
    lines.extend(["", "## Missing Samples"])
    samples = payload.get("missing_samples") if isinstance(payload.get("missing_samples"), list) else []
    if not samples:
        lines.append("- none")
    for sample in samples[:25]:
        lines.append(f"- `{sample.get('packet_id')}` missing: {', '.join(sample.get('missing_fields') or [])}")
    return "\n".join(lines).rstrip() + "\n"


def render_packet_quality_report_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("qualitySummary") if isinstance(payload.get("qualitySummary"), Mapping) else {}
    warnings = payload.get("warningsSummary") if isinstance(payload.get("warningsSummary"), Mapping) else {}
    lines = [
        "# Packet Quality Report",
        "",
        f"- generatedAt: {payload.get('generatedAt', '')}",
        f"- sourceReviewPacketsPath: {payload.get('sourceReviewPacketsPath', '')}",
        f"- packetCount: {payload.get('packetCount', 0)}",
        f"- readOnly: {summary.get('readOnly', True)}",
        f"- modelBehaviorChanged: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Quality Summary",
    ]
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Warnings Summary"])
    for key, value in warnings.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Priority Review Queue"])
    queue = payload.get("priorityReviewQueue") if isinstance(payload.get("priorityReviewQueue"), list) else []
    if not queue:
        lines.append("- none")
    for row in queue[:25]:
        reasons = "; ".join(str(item) for item in row.get("analystPriorityReasons", [])[:3])
        lines.append(
            f"- `{row.get('packetId', '')}` {row.get('analystPriority', '')}: "
            f"{row.get('wallet', 'unknown')} / {row.get('marketOrEvent', 'unknown')} "
            f"(dedupe {row.get('dedupeGroupSize', 0)}). {reasons}"
        )
    lines.extend(["", "## Packet Rows"])
    rows = payload.get("packetQualityRows") if isinstance(payload.get("packetQualityRows"), list) else []
    if not rows:
        lines.append("- none")
    for row in rows[:50]:
        warnings_for_row = []
        if row.get("missingCriticalFields"):
            warnings_for_row.append("missing fields: " + ", ".join(row.get("missingCriticalFields") or []))
        if row.get("cacheOnlyWarning"):
            warnings_for_row.append("cache-only")
        if row.get("retrospectiveOnlyWarning"):
            warnings_for_row.append("retrospective-only")
        if row.get("sourceAttributionWarning"):
            warnings_for_row.append("source warning")
        if row.get("falsePositiveAdvisoryMatches"):
            warnings_for_row.append(
                "FP advisory: "
                + ", ".join(str(item.get("pattern")) for item in row.get("falsePositiveAdvisoryMatches") or [])
            )
        lines.append(
            f"- `{row.get('packetId', '')}` priority={row.get('analystPriority', '')} "
            f"strongRisk={row.get('strongRiskFlag')} HER={row.get('hardEvidenceReviewFlag')} "
            f"overlap={row.get('overlapFlag')} warnings={'; '.join(warnings_for_row) or 'none'}"
        )
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def render_group_drilldown_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Packet Group Drilldown",
        "",
        f"- generatedAt: {payload.get('generatedAt', '')}",
        f"- sourceReviewPacketsPath: {payload.get('sourceReviewPacketsPath', '')}",
        f"- walletGroupCount: {summary.get('walletGroupCount', 0)}",
        f"- marketGroupCount: {summary.get('marketGroupCount', 0)}",
        f"- highPriorityGroupCount: {summary.get('highPriorityGroupCount', 0)}",
        f"- modelBehaviorChanged: {summary.get('modelBehaviorChanged', False)}",
        f"- productionPriorityChanged: {summary.get('productionPriorityChanged', False)}",
        "",
        "## Wallet Groups",
    ]
    wallet_groups = payload.get("walletGroups") if isinstance(payload.get("walletGroups"), list) else []
    if not wallet_groups:
        lines.append("- none")
    for row in wallet_groups[:40]:
        reasons = "; ".join(str(item) for item in row.get("analystPriorityReasons", [])[:3])
        lines.append(
            f"- `{row.get('wallet', '')}` priority={row.get('analystPriority')} "
            f"packets={row.get('packetCount')} markets={row.get('marketCount')} "
            f"dedupeTotal={row.get('dedupeGroupSizeTotal')}. {reasons}"
        )
    lines.extend(["", "## Market Groups"])
    market_groups = payload.get("marketGroups") if isinstance(payload.get("marketGroups"), list) else []
    if not market_groups:
        lines.append("- none")
    for row in market_groups[:40]:
        reasons = "; ".join(str(item) for item in row.get("analystPriorityReasons", [])[:3])
        lines.append(
            f"- `{row.get('market', '')}` priority={row.get('analystPriority')} "
            f"packets={row.get('packetCount')} wallets={row.get('walletCount')}. {reasons}"
        )
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def render_wallet_queue_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = _render_key_values("Wallet Review Queue", summary)
    lines.extend(["", "## Queue"])
    queue = payload.get("wallet_queue") if isinstance(payload.get("wallet_queue"), list) else []
    if not queue:
        lines.append("- none")
    for item in queue[:50]:
        lines.append(
            f"- #{item.get('queue_rank')} `{item.get('wallet')}`: {item.get('packet_count')} packets, "
            f"{item.get('market_count')} markets. {item.get('advisory_review_reason')} "
            f"Caution: {item.get('advisory_caution')}"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_bundle_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = _render_key_values("Analyst Review Handoff Bundle", summary)
    lines.extend(["", "## Artifact Paths"])
    for name, path in (payload.get("artifact_paths") or {}).items():
        lines.append(f"- {name}: {path or 'missing'}")
    manifest_summary = payload.get("manifest_summary") if isinstance(payload.get("manifest_summary"), Mapping) else {}
    lines.extend(["", "## Manifest Summary"])
    if not manifest_summary:
        lines.append("- none")
    for key, value in manifest_summary.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Top Wallet Queue"])
    queue = payload.get("top_wallet_queue") if isinstance(payload.get("top_wallet_queue"), list) else []
    if not queue:
        lines.append("- none")
    for item in queue[:10]:
        lines.append(f"- #{item.get('queue_rank')} `{item.get('wallet')}`: {item.get('advisory_review_reason')}")
    context = payload.get("diagnostic_context") if isinstance(payload.get("diagnostic_context"), Mapping) else {}
    lines.extend(["", "## Diagnostic Context"])
    if not context:
        lines.append("- none")
    for name, values in context.items():
        lines.append(f"- {name}: {values}")
    return "\n".join(lines).rstrip() + "\n"


def render_manifest_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = _render_key_values("Review Artifact Manifest", summary)
    lines.extend(["", "## Artifacts"])
    for item in payload.get("artifacts") or []:
        exists = "exists" if item.get("exists") else "missing"
        digest = str(item.get("sha256") or "")[:16]
        lines.append(f"- {item.get('name')}: {exists} {item.get('path') or ''} {digest}")
    return "\n".join(lines).rstrip() + "\n"


def _write_pair(
    payload: Mapping[str, Any],
    output_dir: Path,
    stem: str,
    renderer,
    *,
    stamp: str | None = None,
) -> dict[str, str]:
    resolved_output_dir = _resolve(output_dir) or output_dir
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved_output_dir / f"{stem}_{stamp}.json"
    markdown_path = resolved_output_dir / f"{stem}_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(renderer(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def run_suite(*, only: str = "all") -> dict[str, dict[str, str]]:
    artifacts = discover_latest_artifacts()
    packet_path = _resolve(artifacts.get("unique_review_packets")) if artifacts.get("unique_review_packets") else None
    packet_payload = _load_json(packet_path)
    quality_payload = build_quality_check(packet_payload, source_path=packet_path)
    packet_quality_report_payload = build_packet_quality_report(packet_payload, source_path=packet_path)
    group_drilldown_payload = build_packet_group_drilldown(packet_payload, source_path=packet_path)
    queue_payload = build_wallet_queue(packet_payload, source_path=packet_path)
    diagnostic_context = build_diagnostic_context(artifacts)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    outputs: dict[str, dict[str, str]] = {}
    if only in {"all", "quality"}:
        outputs["quality"] = _write_pair(
            quality_payload, DEFAULT_QUALITY_OUTPUT_DIR, "review_packet_quality_check", render_quality_markdown, stamp=stamp
        )
        artifacts = dict(artifacts)
        artifacts["review_packet_quality"] = outputs["quality"]["json_path"]
    if only in {"all", "packet-quality-report"}:
        outputs["packet_quality_report"] = _write_pair(
            packet_quality_report_payload,
            DEFAULT_QUALITY_OUTPUT_DIR,
            "packet_quality_report",
            render_packet_quality_report_markdown,
            stamp=stamp,
        )
        artifacts = dict(artifacts)
        artifacts["packet_quality_report"] = outputs["packet_quality_report"]["json_path"]
    if only in {"all", "group-drilldown"}:
        outputs["group_drilldown"] = _write_pair(
            group_drilldown_payload,
            DEFAULT_QUALITY_OUTPUT_DIR,
            "packet_group_drilldown",
            render_group_drilldown_markdown,
            stamp=stamp,
        )
        artifacts = dict(artifacts)
        artifacts["packet_group_drilldown"] = outputs["group_drilldown"]["json_path"]
    if only in {"all", "wallet-queue"}:
        outputs["wallet_queue"] = _write_pair(
            queue_payload, DEFAULT_QUALITY_OUTPUT_DIR, "wallet_review_queue", render_wallet_queue_markdown, stamp=stamp
        )
        artifacts = dict(artifacts)
        artifacts["wallet_review_queue"] = outputs["wallet_queue"]["json_path"]
    manifest_preview = build_manifest_preview(artifacts)
    bundle_payload = build_handoff_bundle(
        artifacts,
        packet_payload,
        quality_payload,
        queue_payload,
        diagnostic_context,
        manifest_summary=manifest_preview,
    )
    if only in {"all", "bundle"}:
        outputs["bundle"] = _write_pair(
            bundle_payload, DEFAULT_BUNDLE_OUTPUT_DIR, "analyst_review_bundle", render_bundle_markdown, stamp=stamp
        )
        artifacts = dict(artifacts)
        artifacts["analyst_handoff_bundle"] = outputs["bundle"]["json_path"]
    manifest_payload = build_artifact_manifest(artifacts)
    if only in {"all", "manifest"}:
        outputs["manifest"] = _write_pair(
            manifest_payload, DEFAULT_MANIFEST_OUTPUT_DIR, "review_artifact_manifest", render_manifest_markdown, stamp=stamp
        )
    return outputs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate safe analyst review quality artifacts from local saved outputs.")
    parser.add_argument(
        "--only",
        choices=("all", "quality", "packet-quality-report", "group-drilldown", "bundle", "wallet-queue", "manifest"),
        default="all",
    )
    args = parser.parse_args(argv)
    outputs = run_suite(only=args.only)
    for name, paths in outputs.items():
        print(f"{name} JSON: {paths['json_path']}")
        print(f"{name} markdown: {paths['markdown_path']}")
    if not outputs:
        print("No outputs written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
