from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("known_case_benchmarks")
DEFAULT_SELECTED_CSV = Path("known_case_benchmarks/benchmark_label_priority_template_20260506_084236.csv")
DEFAULT_FIRST12_WORKSHEET = Path("known_case_benchmarks/benchmark_first_12_labeling_worksheet_20260506.json")
HUMAN_LABEL_FIELDS = (
    "expectedAnalystDisposition",
    "humanLabelConfidence",
    "humanInsiderStyleReason",
    "humanFalsePositiveReason",
    "expectedDetectorDisposition",
    "freshValidationRequired",
    "notes",
)
CASE_LEVEL_CSV_FIELDS = (
    "benchmarkCaseId",
    "parentEventRunId",
    "sourceArtifact",
    "queueRank",
    "eventSlug",
    "marketSlug",
    "conditionId",
    "marketQuestion",
    "wallet",
    "traderName",
    "traderPseudonym",
    "tradeId",
    "txHash",
    "side",
    "outcome",
    "price",
    "size",
    "notionalUsd",
    "timestamp",
    "strongRiskFlag",
    "strongRiskGateBranch",
    "hardEvidenceReviewFlag",
    "hardEvidenceSources",
    "fundingEvidenceGrade",
    "suspiciousFundingQuality",
    "suppressorConflicts",
    "falsePositiveAdvisoryMatches",
    "cacheOnlyWarning",
    "retrospectiveOnlyWarning",
    "missingCriticalFields",
    "whySuspiciousSummary",
    "whyMaybeFalsePositiveSummary",
    "whatToInspectNext",
    *HUMAN_LABEL_FIELDS,
)
EVENT_RUN_RECLASSIFICATIONS = {
    "event_run_control_keep_for_reporting_only",
    "convert_to_case_level_children",
    "defer_until_fresh_validation",
    "discard_from_benchmark_candidate",
    "needs_human_review",
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


def _load_json(path: str | Path | None) -> dict[str, Any]:
    resolved = _resolve(path)
    if not resolved or not resolved.exists():
        return {}
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _read_csv_rows(path: str | Path | None) -> list[dict[str, str]]:
    resolved = _resolve(path)
    if not resolved or not resolved.exists():
        return []
    try:
        with resolved.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return [{key: str(value or "").strip() for key, value in row.items()} for row in reader]
    except OSError:
        return []


def _list_text(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_list_text(item))
        return result
    if isinstance(value, tuple):
        result = []
        for item in value:
            result.extend(_list_text(item))
        return result
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[|;,]", value) if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _join(value: Any) -> str:
    return " | ".join(_list_text(value))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _bool_text(value: Any) -> str:
    if value in (True, "true", "True", "yes", "Yes", "YES", "1", 1):
        return "yes"
    if value in (False, "false", "False", "no", "No", "NO", "0", 0):
        return "no"
    return ""


def _is_tx_hash(value: Any) -> bool:
    text = _text(value)
    return bool(re.fullmatch(r"0x[a-fA-F0-9]{64}", text))


def _tx_hash_from_packet(packet: Mapping[str, Any]) -> str:
    trade_id = _text(packet.get("trade_id") or packet.get("tradeId"))
    if _is_tx_hash(trade_id):
        return trade_id
    links = packet.get("links") if isinstance(packet.get("links"), Mapping) else {}
    tx_link = _text(links.get("polygonscan_transaction"))
    match = re.search(r"/tx/(0x[a-fA-F0-9]{64})", tx_link)
    return match.group(1) if match else ""


def _warning_from_funding(funding_grade: str, trace_skipped: Any = "", skip_reason: Any = "") -> str:
    parts: list[str] = []
    if funding_grade == "unknown":
        parts.append("fundingEvidenceGrade=unknown")
    skipped = _text(trace_skipped)
    if skipped and skipped not in {"0", "0.0"}:
        parts.append(f"funding trace skipped count={skipped}")
    reasons = _join(skip_reason)
    if reasons:
        parts.append(f"skip reasons={reasons}")
    if not parts:
        return ""
    parts.append("treat unavailable funding as unknown, not none")
    return "; ".join(parts)


def _retrospective_warning(*, retrospective: Any, final_judgment: str = "", outcome_known: Any = "", live_detectable: Any = "") -> str:
    parts: list[str] = []
    if retrospective in (True, "true", "True", "yes", "Yes"):
        parts.append("retrospective_only=true")
    if "retrospective" in final_judgment.lower():
        parts.append("saved judgment is retrospective")
    if outcome_known in (True, "true", "True", "yes", "Yes"):
        parts.append("outcome context was available in saved artifact")
    if live_detectable in (None, "", "unknown"):
        parts.append("live detectability not proven from saved fields")
    return "; ".join(dict.fromkeys(parts))


def _name_parts(username: Any) -> tuple[str, str]:
    text = _text(username)
    if not text:
        return "", ""
    match = re.match(r"^(.*?)\s*\((.*?)\)\s*$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return text, ""


def _market_family(row: Mapping[str, Any]) -> str:
    return _text(row.get("eventSlug")) or _text(row.get("marketSlug")) or _text(row.get("marketQuestion"))


def _case_key(row: Mapping[str, Any]) -> str:
    wallet = _text(row.get("wallet"))
    condition = _text(row.get("conditionId"))
    trade = _text(row.get("tradeId"))
    if wallet and condition and trade:
        return f"{wallet}|{condition}|{trade}"
    return _text(row.get("benchmarkCaseId"))


def _packet_fp_patterns(packet: Mapping[str, Any]) -> list[str]:
    patterns: list[str] = []
    for item in packet.get("false_positive_advisory") or packet.get("falsePositiveAdvisory") or []:
        if isinstance(item, Mapping) and item.get("pattern"):
            patterns.append(str(item.get("pattern")))
    return sorted(dict.fromkeys(patterns))


def _packet_missing_fields(packet: Mapping[str, Any]) -> list[str]:
    fields: list[str] = []
    for item in packet.get("critical_field_warnings") or packet.get("criticalFieldWarnings") or []:
        if isinstance(item, Mapping) and item.get("field"):
            fields.append(str(item.get("field")))
    return sorted(dict.fromkeys(fields))


def _event_fp_patterns(trade: Mapping[str, Any]) -> list[str]:
    patterns = []
    patterns.extend(_list_text(trade.get("strongRiskSuppressorConflictReasons")))
    if _text(trade.get("fundingEvidenceGrade")) == "unknown":
        patterns.append("funding_unknown")
    if trade.get("walletPublicPowerUserFlag") is True:
        patterns.append("high_volume_public_user")
    if trade.get("walletHighVolumeEventUserFlag") is True:
        patterns.append("high_volume_event_user")
    if trade.get("strongRiskRetrospectiveOnly") in (True, "true", "True", "Yes", "yes"):
        patterns.append("retrospective_only")
    if _text(trade.get("strongRiskSourceAttributionIssue")):
        patterns.append("source_attribution_issue")
    return sorted(dict.fromkeys(patterns))


def _event_missing_fields(trade: Mapping[str, Any]) -> list[str]:
    fields: list[str] = []
    if not _list_text(trade.get("hardEvidenceSources")):
        fields.append("hardEvidenceSources")
    if not _text(trade.get("strongRiskExactGateBranch")):
        fields.append("strongRiskExactGateBranch")
    if _text(trade.get("fundingEvidenceGrade")) == "unknown":
        fields.append("fundingEvidenceGrade")
    if _text(trade.get("strongRiskMissingSourceAttribution")) in {"Yes", "true", "True"}:
        fields.append("sourceAttribution")
    return fields


def _compact_sentence(parts: Sequence[Any], *, fallback: str = "") -> str:
    text_parts = [_text(part) for part in parts if _text(part)]
    return " ".join(text_parts) if text_parts else fallback


def _packet_to_candidate(packet: Mapping[str, Any], index: int) -> dict[str, Any] | None:
    wallet = _text(packet.get("wallet"))
    trade_id = _text(packet.get("trade_id") or packet.get("tradeId"))
    if not wallet and not trade_id:
        return None
    group = _text(packet.get("group"))
    judgment = _text(packet.get("judgment"))
    strong = group == "strong_risk" or "strong risk" in judgment.lower()
    her = group == "hard_evidence_review"
    fp_patterns = _packet_fp_patterns(packet)
    missing = _packet_missing_fields(packet)
    funding_grade = _text(packet.get("funding_evidence_grade") or packet.get("fundingEvidenceGrade"))
    source_artifact = _text(packet.get("source_path") or packet.get("sourcePath"))
    return {
        "benchmarkCaseId": f"CASE-PACKET-{index:04d}",
        "parentEventRunId": "",
        "sourceArtifact": source_artifact,
        "queueRank": index,
        "eventSlug": "",
        "marketSlug": "",
        "conditionId": _text(packet.get("condition_id") or packet.get("conditionId")),
        "marketQuestion": _text(packet.get("market")),
        "wallet": wallet,
        "traderName": _text(packet.get("trader_name") or packet.get("traderName")),
        "traderPseudonym": "",
        "tradeId": trade_id,
        "txHash": _tx_hash_from_packet(packet),
        "side": "",
        "outcome": "",
        "price": "",
        "size": "",
        "notionalUsd": _text(packet.get("notional")),
        "timestamp": _text(packet.get("timestamp")),
        "strongRiskFlag": "yes" if strong else "no",
        "strongRiskGateBranch": _text(packet.get("strong_risk_exact_gate_branch") or packet.get("strongRiskExactGateBranch")),
        "hardEvidenceReviewFlag": "yes" if her else "no",
        "hardEvidenceSources": _join(packet.get("hard_evidence_sources") or packet.get("hardEvidenceSources")),
        "fundingEvidenceGrade": funding_grade,
        "suspiciousFundingQuality": "",
        "suppressorConflicts": _join(packet.get("suppressors") or packet.get("suppressor_conflict")),
        "falsePositiveAdvisoryMatches": _join(fp_patterns),
        "cacheOnlyWarning": _warning_from_funding(funding_grade),
        "retrospectiveOnlyWarning": _retrospective_warning(
            retrospective=packet.get("retrospective_only"),
            final_judgment=judgment,
            live_detectable=packet.get("live_detectable"),
        ),
        "missingCriticalFields": _join(missing),
        "whySuspiciousSummary": _compact_sentence(
            [
                f"Saved packet group={group} judgment={judgment} score={packet.get('score')}.",
                packet.get("why_this_matters"),
            ]
        ),
        "whyMaybeFalsePositiveSummary": _compact_sentence(
            [
                packet.get("why_this_may_be_false_positive"),
                f"Advisory patterns: {_join(fp_patterns)}." if fp_patterns else "",
                f"Missing critical fields: {_join(missing)}." if missing else "",
            ],
            fallback="Review source attribution, funding, and false-positive advisory fields before labeling.",
        ),
        "whatToInspectNext": _join(
            packet.get("what_to_inspect_next")
            or [
                "Open source artifact",
                "verify wallet/trade identity",
                "verify hard evidence sources",
                "check funding evidence grade",
            ]
        ),
        "caseSource": "unique_review_packet",
        "relatedParentEventRunIds": [],
        "selectionSignals": {
            "strongRisk": strong,
            "hardEvidenceReview": her,
            "overlap": strong and her,
            "falsePositiveAdvisory": bool(fp_patterns),
            "sourceSchemaMissingness": bool(missing),
        },
    }


def _event_trade_to_candidate(event_row: Mapping[str, str], trade: Mapping[str, Any], ordinal: int) -> dict[str, Any] | None:
    wallet = _text(trade.get("wallet"))
    trade_id = _text(trade.get("id") or trade.get("tradeId"))
    if not wallet and not trade_id:
        return None
    trader_name, trader_pseudonym = _name_parts(trade.get("username"))
    final_judgment = _text(trade.get("finalEventJudgment"))
    strong = _text(trade.get("strongRiskGatePassed")) == "Yes" or "strong risk" in final_judgment.lower()
    her = _text(trade.get("hardEvidenceReviewTier")) == "Hard Evidence Review"
    fp_patterns = _event_fp_patterns(trade)
    missing = _event_missing_fields(trade)
    funding_grade = _text(trade.get("fundingEvidenceGrade"))
    skip_reasons = trade.get("fundingTraceSkippedReasonDistribution")
    cache_warning = _warning_from_funding(
        funding_grade,
        trade.get("fundingTraceSkippedCount"),
        skip_reasons,
    )
    if not cache_warning and _text(trade.get("fundingTraceFromPersistentCache")):
        cache_warning = "saved funding context may be cache-derived; verify fresh trace before funding conclusions"
    return {
        "benchmarkCaseId": f"CASE-EVENT-{ordinal:04d}",
        "parentEventRunId": _text(event_row.get("localCaseId")),
        "sourceArtifact": _text(event_row.get("sourceArtifact")),
        "queueRank": _text(event_row.get("queueRank")),
        "eventSlug": _text(event_row.get("eventSlug") or trade.get("parentEventSlug")),
        "marketSlug": _text(trade.get("marketSlug") or event_row.get("eventSlug")),
        "conditionId": _text(trade.get("conditionId") or event_row.get("conditionId")),
        "marketQuestion": _text(trade.get("market") or event_row.get("market")),
        "wallet": wallet,
        "traderName": trader_name,
        "traderPseudonym": trader_pseudonym,
        "tradeId": trade_id,
        "txHash": trade_id if _is_tx_hash(trade_id) else "",
        "side": _text(trade.get("side") or trade.get("orderSide")),
        "outcome": _text(trade.get("winningOutcome") or trade.get("outcomeStatus")),
        "price": _text(trade.get("price")),
        "size": _text(trade.get("positionSize")),
        "notionalUsd": _text(trade.get("suspiciousFundingTradeNotionalUsd")),
        "timestamp": _text(trade.get("timestamp")),
        "strongRiskFlag": "yes" if strong else "no",
        "strongRiskGateBranch": _text(trade.get("strongRiskExactGateBranch")),
        "hardEvidenceReviewFlag": "yes" if her else "no",
        "hardEvidenceSources": _join(trade.get("hardEvidenceSources")),
        "fundingEvidenceGrade": funding_grade,
        "suspiciousFundingQuality": _text(trade.get("suspiciousFundingQuality")),
        "suppressorConflicts": _join(trade.get("strongRiskSuppressorConflictReasons")),
        "falsePositiveAdvisoryMatches": _join(fp_patterns),
        "cacheOnlyWarning": cache_warning,
        "retrospectiveOnlyWarning": _retrospective_warning(
            retrospective=trade.get("strongRiskRetrospectiveOnly"),
            final_judgment=final_judgment,
            outcome_known=trade.get("outcomeKnown"),
            live_detectable=trade.get("strongRiskLiveDetectable"),
        ),
        "missingCriticalFields": _join(missing),
        "whySuspiciousSummary": _compact_sentence(
            [
                f"Saved finalEventJudgment={final_judgment} eventForensicScore={trade.get('eventForensicScore')}.",
                _join(trade.get("eventForensicNotes")),
                _text(trade.get("hardEvidencePrimaryReason")),
            ]
        ),
        "whyMaybeFalsePositiveSummary": _compact_sentence(
            [
                _join(trade.get("reducesConcern")),
                f"Suppressor/advisory patterns: {_join(fp_patterns)}." if fp_patterns else "",
                "Funding is unknown or cache-limited." if funding_grade == "unknown" else "",
            ],
            fallback="Check suppressors, public-user behavior, stale-resolution context, and source attribution before labeling.",
        ),
        "whatToInspectNext": _join(
            [
                "Inspect event_analysis suspicious_trades row",
                "verify wallet and trade id",
                "verify hardEvidenceSources and hardEvidenceReviewTier",
                "check fundingEvidenceGrade and suspiciousFundingQuality",
                "review strongRiskGateTrace and suppressor conflicts",
            ]
        ),
        "caseSource": "event_forensic_child_trade",
        "relatedParentEventRunIds": [_text(event_row.get("localCaseId"))],
        "selectionSignals": {
            "strongRisk": strong,
            "hardEvidenceReview": her,
            "overlap": strong and her,
            "falsePositiveAdvisory": bool(fp_patterns),
            "sourceSchemaMissingness": bool(missing),
        },
    }


def _load_event_candidates(selected_rows: Sequence[Mapping[str, str]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    candidates: list[dict[str, Any]] = []
    unavailable: Counter[str] = Counter()
    ordinal = 1
    for row in selected_rows:
        if _text(row.get("sourceType")) != "event_forensic_run":
            continue
        source_path = _resolve(row.get("sourceArtifact"))
        if not source_path or not source_path.exists():
            unavailable["missing_source_artifact"] += 1
            continue
        payload = _load_json(source_path)
        trades = payload.get("suspicious_trades") if isinstance(payload.get("suspicious_trades"), list) else []
        if not trades:
            unavailable["no_suspicious_trades"] += 1
            continue
        for trade in trades:
            if not isinstance(trade, Mapping):
                continue
            candidate = _event_trade_to_candidate(row, trade, ordinal)
            if candidate:
                candidates.append(candidate)
                ordinal += 1
    return candidates, dict(unavailable)


def _dedupe_candidates(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        row = dict(candidate)
        key = _case_key(row)
        if key not in deduped:
            deduped[key] = row
            continue
        existing = deduped[key]
        parents = set(_list_text(existing.get("relatedParentEventRunIds")))
        parents.update(_list_text(row.get("relatedParentEventRunIds")))
        existing["relatedParentEventRunIds"] = sorted(parents)
        source_artifacts = set(_list_text(existing.get("relatedSourceArtifacts")))
        source_artifacts.add(_text(existing.get("sourceArtifact")))
        source_artifacts.add(_text(row.get("sourceArtifact")))
        existing["relatedSourceArtifacts"] = sorted(item for item in source_artifacts if item)
        existing_signals = existing.get("selectionSignals") if isinstance(existing.get("selectionSignals"), Mapping) else {}
        new_signals = row.get("selectionSignals") if isinstance(row.get("selectionSignals"), Mapping) else {}
        merged = {key: bool(existing_signals.get(key) or new_signals.get(key)) for key in set(existing_signals) | set(new_signals)}
        existing["selectionSignals"] = merged
    return list(deduped.values())


def _candidate_score(row: Mapping[str, Any]) -> tuple[int, str]:
    signals = row.get("selectionSignals") if isinstance(row.get("selectionSignals"), Mapping) else {}
    score = 0
    if signals.get("overlap"):
        score += 50
    if signals.get("hardEvidenceReview"):
        score += 35
    if signals.get("strongRisk"):
        score += 30
    if signals.get("falsePositiveAdvisory"):
        score += 15
    if signals.get("sourceSchemaMissingness"):
        score += 10
    if _text(row.get("caseSource")) == "unique_review_packet":
        score += 5
    return -score, _market_family(row)


def _select_case_rows(candidates: Sequence[Mapping[str, Any]], max_rows: int) -> list[dict[str, Any]]:
    pool = sorted((dict(row) for row in candidates), key=_candidate_score)
    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()

    def add_matching(signal: str, target_count: int) -> None:
        if len(selected) >= max_rows:
            return
        current = sum(
            1
            for row in selected
            if isinstance(row.get("selectionSignals"), Mapping) and row["selectionSignals"].get(signal)
        )
        for row in pool:
            if current >= target_count or len(selected) >= max_rows:
                break
            signals = row.get("selectionSignals") if isinstance(row.get("selectionSignals"), Mapping) else {}
            key = _case_key(row)
            if key in selected_keys or not signals.get(signal):
                continue
            selected.append(row)
            selected_keys.add(key)
            current += 1

    def add_source(source: str, target_count: int) -> None:
        if len(selected) >= max_rows:
            return
        current = sum(1 for row in selected if _text(row.get("caseSource")) == source)
        for row in pool:
            if current >= target_count or len(selected) >= max_rows:
                break
            key = _case_key(row)
            if key in selected_keys or _text(row.get("caseSource")) != source:
                continue
            selected.append(row)
            selected_keys.add(key)
            current += 1

    availability = Counter()
    source_availability = Counter()
    for row in pool:
        source_availability[_text(row.get("caseSource"))] += 1
        signals = row.get("selectionSignals") if isinstance(row.get("selectionSignals"), Mapping) else {}
        for signal, value in signals.items():
            if value:
                availability[signal] += 1

    add_matching("overlap", min(5, availability["overlap"]))
    add_matching("hardEvidenceReview", min(10, availability["hardEvidenceReview"]))
    add_matching("strongRisk", min(10, availability["strongRisk"]))
    add_matching("falsePositiveAdvisory", min(5, availability["falsePositiveAdvisory"]))
    add_matching("sourceSchemaMissingness", min(5, availability["sourceSchemaMissingness"]))
    add_source("unique_review_packet", min(5, source_availability["unique_review_packet"]))

    family_counts: Counter[str] = Counter(_market_family(row) for row in selected)
    for row in pool:
        if len(selected) >= max_rows:
            break
        key = _case_key(row)
        if key in selected_keys:
            continue
        family = _market_family(row)
        if family_counts[family] >= 5 and len(family_counts) > 1:
            continue
        selected.append(row)
        selected_keys.add(key)
        family_counts[family] += 1
    for row in pool:
        if len(selected) >= max_rows:
            break
        key = _case_key(row)
        if key in selected_keys:
            continue
        selected.append(row)
        selected_keys.add(key)

    for index, row in enumerate(selected, start=1):
        row["benchmarkCaseId"] = f"BENCH-CASE-20260506-{index:04d}"
    return selected


def _blank_human_fields(row: dict[str, Any]) -> dict[str, Any]:
    for field in HUMAN_LABEL_FIELDS:
        row[field] = ""
    return row


def _case_rows_for_csv(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    csv_rows: list[dict[str, str]] = []
    for row in rows:
        csv_rows.append({field: _join(row.get(field)) if isinstance(row.get(field), (list, tuple)) else _text(row.get(field)) for field in CASE_LEVEL_CSV_FIELDS})
    return csv_rows


def _reclassify_event_rows(
    selected_rows: Sequence[Mapping[str, str]],
    case_rows: Sequence[Mapping[str, Any]],
    event_candidate_unavailable: Mapping[str, int],
) -> dict[str, Any]:
    cases_by_parent: dict[str, list[str]] = {}
    for row in case_rows:
        parent_ids = _list_text(row.get("relatedParentEventRunIds")) or [_text(row.get("parentEventRunId"))]
        for parent_id in parent_ids:
            if parent_id:
                cases_by_parent.setdefault(parent_id, []).append(_text(row.get("benchmarkCaseId")))

    re_rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row in selected_rows:
        local_id = _text(row.get("localCaseId"))
        source_type = _text(row.get("sourceType"))
        source_path = _resolve(row.get("sourceArtifact"))
        proposed = cases_by_parent.get(local_id, [])[:8]
        if source_type != "event_forensic_run":
            classification = "needs_human_review"
            reason = "Original row is not an event-run row; review source type before reclassification."
            keep_control = False
        elif proposed:
            classification = "convert_to_case_level_children"
            reason = (
                "Original row is event/run scoped and lacks a row-level wallet/trader; use concrete child wallet/trade rows "
                "for benchmark labeling and retain the event-run row only as a reporting/count control."
            )
            keep_control = True
        elif source_path and source_path.exists():
            classification = "defer_until_fresh_validation"
            reason = (
                "Saved event-run artifact exists, but no selected case-level child survived de-duplication or row cap; "
                "do not ask for a case-level label on the event-run row."
            )
            keep_control = True
        else:
            classification = "needs_human_review"
            reason = "Source artifact is unavailable; cannot convert to child case rows from saved local evidence."
            keep_control = False
        counts[classification] += 1
        re_rows.append(
            {
                "queueRank": _text(row.get("queueRank")),
                "localCaseId": local_id,
                "sourceType": source_type,
                "eventSlug": _text(row.get("eventSlug")),
                "market": _text(row.get("market")),
                "conditionId": _text(row.get("conditionId")),
                "sourceArtifact": _text(row.get("sourceArtifact")),
                "classification": classification,
                "whySuitableOrNot": reason,
                "proposedChildCaseRows": proposed,
                "candidateChildCaseCountInTemplate": len(proposed),
                "remainReportingOnlyControl": keep_control,
                "humanLabelGuidance": (
                    "Do not label this event-run row as a case-level truth row. Label the proposed child rows instead."
                    if proposed
                    else "Do not use this event-run row as a case-level benchmark label without more review."
                ),
            }
        )

    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_event_run_rows_reclassification",
        "selectedCsvPath": str(_resolve(DEFAULT_SELECTED_CSV) or DEFAULT_SELECTED_CSV),
        "summary": {
            "originalRowCount": len(selected_rows),
            "originalEventRunRowCount": sum(1 for row in selected_rows if _text(row.get("sourceType")) == "event_forensic_run"),
            "originalPacketRowCount": sum(1 for row in selected_rows if _text(row.get("sourceType")) == "unique_review_packet"),
            "classificationCounts": dict(counts),
            "eventRunRowsNotTreatedAsCaseLevelLabels": True,
            "selectedCaseLevelRowCount": len(case_rows),
            "eventCandidateUnavailableCounts": dict(event_candidate_unavailable),
            "labelsAssignedByThisTool": 0,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "allowedClassifications": sorted(EVENT_RUN_RECLASSIFICATIONS),
        "reclassificationRows": re_rows,
        "stopConditions": [
            "Do not ask a human to label event-run rows as if they were wallet/trade cases.",
            "Do not infer case-level labels from event-run counts.",
            "Do not drop production rows because of this reporting-only reclassification.",
        ],
    }


def _summary_for_case_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    signals = Counter()
    for row in rows:
        row_signals = row.get("selectionSignals") if isinstance(row.get("selectionSignals"), Mapping) else {}
        for key, value in row_signals.items():
            if value:
                signals[key] += 1
    wallet_or_trade = sum(1 for row in rows if _text(row.get("wallet")) or _text(row.get("tradeId")) or _text(row.get("txHash")))
    label_fields_blank = all(not _text(row.get(field)) for row in rows for field in HUMAN_LABEL_FIELDS)
    families = Counter(_market_family(row) for row in rows)
    return {
        "caseLevelRowCount": len(rows),
        "rowsWithWalletOrTradeIdentifiers": wallet_or_trade,
        "humanLabelFieldsRemainBlank": label_fields_blank,
        "labelsAssignedByThisTool": 0,
        "sourceSignalCounts": dict(signals),
        "eventFamilyCount": len([family for family in families if family]),
        "eventFamilyDistribution": dict(families),
        "modelBehaviorChanged": False,
        "scoringChanged": False,
        "gatesChanged": False,
        "herRoutingChanged": False,
        "fundingEligibilityChanged": False,
        "candidateAdmissionChanged": False,
        "oldOutputsMutated": False,
        "externalSourcesUsed": False,
    }


def build_case_level_artifacts(
    *,
    selected_csv_path: Path = DEFAULT_SELECTED_CSV,
    first12_worksheet_payload: Mapping[str, Any] | None = None,
    review_packets_payload: Mapping[str, Any] | None = None,
    packet_quality_payload: Mapping[str, Any] | None = None,
    false_positive_payload: Mapping[str, Any] | None = None,
    source_schema_payload: Mapping[str, Any] | None = None,
    candidate_recall_payload: Mapping[str, Any] | None = None,
    max_rows: int = 40,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected_rows = _read_csv_rows(selected_csv_path)
    review_packets_payload = review_packets_payload or {}
    packet_candidates = [
        candidate
        for index, packet in enumerate(review_packets_payload.get("packets", []) or [], start=1)
        if isinstance(packet, Mapping)
        for candidate in [_packet_to_candidate(packet, index)]
        if candidate is not None
    ]
    event_candidates, event_unavailable = _load_event_candidates(selected_rows)
    deduped = _dedupe_candidates([*packet_candidates, *event_candidates])
    selected = [_blank_human_fields(dict(row)) for row in _select_case_rows(deduped, max_rows)]
    selected_csv = _resolve(selected_csv_path) or selected_csv_path
    first12_summary = (
        first12_worksheet_payload.get("suggestedDispositionDistribution")
        if isinstance(first12_worksheet_payload, Mapping) and isinstance(first12_worksheet_payload.get("suggestedDispositionDistribution"), Mapping)
        else {}
    )
    case_payload = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_case_level_template",
        "selectedEventRunCsvPath": str(selected_csv),
        "sourceArtifacts": {
            "first12Worksheet": str(_resolve(DEFAULT_FIRST12_WORKSHEET) or DEFAULT_FIRST12_WORKSHEET),
            "reviewPackets": "review_packets/unique_review_packets_20260505_163257.json",
            "packetQualityReport": "analyst_quality_outputs/packet_quality_report_20260505_184251.json",
            "falsePositiveLibrary": "false_positive_library/false_positive_pattern_library_20260505_151140.json",
            "sourceSchemaRepairPlan": "source_schema_repair_outputs/source_schema_repair_plan_20260505_151140.json",
            "candidateRecallDiagnostic": "candidate_recall_outputs/candidate_recall_diagnostic_20260505_183346.json",
        },
        "strategicInterpretation": {
            "first12WorksheetSuggestedDispositionDistribution": dict(first12_summary),
            "eventRunGranularityIssueObserved": True,
            "manualLabelingShouldTargetCaseLevelRows": True,
        },
        "summary": _summary_for_case_rows(selected),
        "caseLevelColumns": list(CASE_LEVEL_CSV_FIELDS),
        "humanLabelFields": list(HUMAN_LABEL_FIELDS),
        "selectionNotes": [
            "Rows are selected from saved local unique review packets and saved event-forensic child trades.",
            "Event-run rows without wallet/trade identifiers are not primary benchmark rows.",
            "Human label fields are intentionally blank.",
            "False-positive advisory and source/schema missingness are reporting-only review cues.",
        ],
        "supportArtifactSummaries": {
            "packetQuality": packet_quality_payload.get("qualitySummary", {}) if isinstance(packet_quality_payload, Mapping) else {},
            "falsePositiveLibrary": false_positive_payload.get("summary", {}) if isinstance(false_positive_payload, Mapping) else {},
            "sourceSchemaRepairPlan": source_schema_payload.get("summary", {}) if isinstance(source_schema_payload, Mapping) else {},
            "candidateRecallDiagnostic": candidate_recall_payload.get("summary", {}) if isinstance(candidate_recall_payload, Mapping) else {},
        },
        "invariantsPreserved": [
            "_score_trade() unchanged",
            "Strong Risk gates unchanged",
            "scoring weights unchanged",
            "production severity labels unchanged",
            "HER routing unchanged",
            "funding eligibility unchanged",
            "candidate admission unchanged",
            "old saved outputs not mutated",
            "human label fields left blank",
            "no final labels inferred",
            "no external sources used",
            "raw RPC URLs and credentials not written",
        ],
        "caseRows": selected,
    }
    reclass_payload = _reclassify_event_rows(selected_rows, selected, event_unavailable)
    return case_payload, reclass_payload


def render_case_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Case-Level Benchmark Template",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Case-level rows: {summary.get('caseLevelRowCount', 0)}",
        f"- Rows with wallet/trade identifiers: {summary.get('rowsWithWalletOrTradeIdentifiers', 0)}",
        f"- Human label fields remain blank: {summary.get('humanLabelFieldsRemainBlank', False)}",
        f"- Labels assigned by this tool: {summary.get('labelsAssignedByThisTool', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Why This Exists",
        "",
        "The prior selected CSV is event-run scoped. These case rows are concrete saved wallet/trade review leads intended for human labeling and later reporting-only calibration.",
        "",
        "## Selection Counts",
    ]
    for key, value in (summary.get("sourceSignalCounts") or {}).items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Human Label Fields"])
    for field in payload.get("humanLabelFields") or []:
        lines.append(f"- `{field}` must remain blank until a human annotator fills it.")
    lines.extend(["", "## First Rows"])
    for row in payload.get("caseRows") or []:
        if not isinstance(row, Mapping):
            continue
        lines.append(
            f"- `{row.get('benchmarkCaseId', '')}` {row.get('caseSource', '')}: "
            f"wallet `{row.get('wallet', '')}` trade `{row.get('tradeId', '')}` / {row.get('marketQuestion', '')}"
        )
        lines.append(
            f"  - signals: Strong Risk={row.get('strongRiskFlag', '')}, HER={row.get('hardEvidenceReviewFlag', '')}, "
            f"FP advisory={row.get('falsePositiveAdvisoryMatches', '') or 'none'}, missing={row.get('missingCriticalFields', '') or 'none'}"
        )
    lines.extend(["", "## Invariants Preserved"])
    for item in payload.get("invariantsPreserved") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def render_reclassification_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Event-Run Row Reclassification",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Original rows: {summary.get('originalRowCount', 0)}",
        f"- Selected case-level rows: {summary.get('selectedCaseLevelRowCount', 0)}",
        f"- Event-run rows treated as case-level labels: {not summary.get('eventRunRowsNotTreatedAsCaseLevelLabels', True)}",
        f"- Labels assigned by this tool: {summary.get('labelsAssignedByThisTool', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Classification Counts",
    ]
    for key, value in (summary.get("classificationCounts") or {}).items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Rows"])
    for row in payload.get("reclassificationRows") or []:
        if not isinstance(row, Mapping):
            continue
        children = ", ".join(row.get("proposedChildCaseRows") or []) or "none selected"
        lines.append(
            f"- #{row.get('queueRank', '')} `{row.get('localCaseId', '')}` `{row.get('classification', '')}`: "
            f"{row.get('whySuitableOrNot', '')}"
        )
        lines.append(f"  - proposed child case rows: {children}")
        lines.append(f"  - remain reporting-only control: {row.get('remainReportingOnlyControl', False)}")
    lines.extend(["", "## Stop Conditions"])
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(
    case_payload: Mapping[str, Any],
    reclassification_payload: Mapping[str, Any],
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    date_tag: str = "20260506",
) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    case_json_path = resolved / f"benchmark_case_level_template_{date_tag}.json"
    case_md_path = resolved / f"benchmark_case_level_template_{date_tag}.md"
    case_csv_path = resolved / f"benchmark_case_level_template_{date_tag}.csv"
    reclass_json_path = resolved / f"benchmark_event_run_rows_reclassification_{date_tag}.json"
    reclass_md_path = resolved / f"benchmark_event_run_rows_reclassification_{date_tag}.md"
    case_json_path.write_text(json.dumps(dict(case_payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    case_md_path.write_text(render_case_markdown(case_payload), encoding="utf-8")
    with case_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CASE_LEVEL_CSV_FIELDS))
        writer.writeheader()
        writer.writerows(_case_rows_for_csv(case_payload.get("caseRows", []) or []))
    reclass_json_path.write_text(json.dumps(dict(reclassification_payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    reclass_md_path.write_text(render_reclassification_markdown(reclassification_payload), encoding="utf-8")
    return {
        "case_json_path": str(case_json_path),
        "case_markdown_path": str(case_md_path),
        "case_csv_path": str(case_csv_path),
        "reclassification_json_path": str(reclass_json_path),
        "reclassification_markdown_path": str(reclass_md_path),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a case-level benchmark template from saved local artifacts.")
    parser.add_argument("--selected-csv", type=Path, default=DEFAULT_SELECTED_CSV)
    parser.add_argument("--first12-worksheet", type=Path, default=DEFAULT_FIRST12_WORKSHEET)
    parser.add_argument("--review-packets", type=Path, default=None)
    parser.add_argument("--packet-quality-report", type=Path, default=None)
    parser.add_argument("--false-positive-library", type=Path, default=None)
    parser.add_argument("--source-schema-repair-plan", type=Path, default=None)
    parser.add_argument("--candidate-recall-diagnostic", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--date-tag", default="20260506")
    parser.add_argument("--max-rows", type=int, default=40)
    args = parser.parse_args(argv)

    review_packets = args.review_packets or _latest_file(Path("review_packets"), "unique_review_packets_*.json")
    packet_quality = args.packet_quality_report or _latest_file(Path("analyst_quality_outputs"), "packet_quality_report_*.json")
    false_positive = args.false_positive_library or _latest_file(Path("false_positive_library"), "false_positive_pattern_library_*.json")
    source_schema = args.source_schema_repair_plan or _latest_file(Path("source_schema_repair_outputs"), "source_schema_repair_plan_*.json")
    candidate_recall = args.candidate_recall_diagnostic or _latest_file(Path("candidate_recall_outputs"), "candidate_recall_diagnostic_*.json")

    case_payload, reclass_payload = build_case_level_artifacts(
        selected_csv_path=args.selected_csv,
        first12_worksheet_payload=_load_json(args.first12_worksheet),
        review_packets_payload=_load_json(review_packets),
        packet_quality_payload=_load_json(packet_quality),
        false_positive_payload=_load_json(false_positive),
        source_schema_payload=_load_json(source_schema),
        candidate_recall_payload=_load_json(candidate_recall),
        max_rows=args.max_rows,
    )
    outputs = write_outputs(case_payload, reclass_payload, output_dir=args.output_dir, date_tag=args.date_tag)
    summary = case_payload.get("summary", {})
    re_summary = reclass_payload.get("summary", {})
    print(f"Case-level benchmark CSV: {outputs['case_csv_path']}")
    print(f"Case-level benchmark JSON: {outputs['case_json_path']}")
    print(f"Case-level benchmark markdown: {outputs['case_markdown_path']}")
    print(f"Event-run reclassification JSON: {outputs['reclassification_json_path']}")
    print(f"Event-run reclassification markdown: {outputs['reclassification_markdown_path']}")
    print(f"Case-level rows: {summary.get('caseLevelRowCount', 0)}")
    print(f"Rows with wallet/trade identifiers: {summary.get('rowsWithWalletOrTradeIdentifiers', 0)}")
    print(f"Human label fields remain blank: {summary.get('humanLabelFieldsRemainBlank', False)}")
    print(f"Original selected rows reclassified: {re_summary.get('originalRowCount', 0)}")
    print(f"Original event-run rows reclassified: {re_summary.get('originalEventRunRowCount', 0)}")
    print(f"Model behavior changed: {summary.get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
