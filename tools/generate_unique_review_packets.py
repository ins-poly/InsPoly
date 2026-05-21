from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALIDATION_OUTPUT_DIR = Path("validation_corpus_outputs")
DEFAULT_STRONG_RISK_DIR = Path("strong_risk_diagnostic_outputs")
DEFAULT_OUTPUT_DIR = Path("review_packets")

WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
TX_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")


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


def _value(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row.get(key)
    lower_map = {str(key).lower(): key for key in row}
    for key in keys:
        actual = lower_map.get(key.lower())
        if actual is not None:
            return row.get(actual)
    return None


def _string(row: Mapping[str, Any], *keys: str) -> str:
    value = _value(row, *keys)
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _listify(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_listify(item))
        return result
    if isinstance(value, tuple | set):
        result = []
        for item in value:
            result.extend(_listify(item))
        return result
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped.replace("'", '"'))
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return _listify(parsed)
        return [part.strip() for part in stripped.split(",") if part.strip()]
    return [str(value).strip()]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _valid_wallet(value: str) -> bool:
    return bool(WALLET_RE.match(value or ""))


def _valid_tx(value: str) -> bool:
    return bool(TX_RE.match(value or ""))


def _http_url(value: str) -> bool:
    lowered = (value or "").strip().lower()
    return lowered.startswith("https://") or lowered.startswith("http://")


def _row_hash(row: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(row), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def dedupe_key_for_row(row: Mapping[str, Any]) -> str:
    explicit = _string(row, "dedupeKey", "dedupe_key")
    if explicit and explicit.lower() not in {"unknown", "none", "null"}:
        return explicit
    trade_id = _string(row, "tradeId", "trade_id", "row_id", "txHash", "transactionHash")
    wallet = _string(row, "wallet", "walletAddress", "wallet_address")
    condition = _string(row, "conditionId", "condition_id", "market")
    timestamp = _string(row, "timestamp", "createdAt", "created_at")
    notional = _string(row, "notional", "capitalAtRisk", "capital_at_risk")
    if trade_id and trade_id.lower() not in {"unknown", "none", "null"}:
        return f"trade:{trade_id}|wallet:{wallet}|condition:{condition}"
    if wallet or condition or timestamp or notional:
        return f"wallet:{wallet}|condition:{condition}|timestamp:{timestamp}|notional:{notional}"
    source_path = _string(row, "sourcePath", "source_path")
    source_row = _string(row, "sourceRow", "source_row")
    if source_path or source_row:
        return f"source:{source_path}|row:{source_row}"
    return f"hash:{_row_hash(row)}"


def _is_strong_risk(row: Mapping[str, Any]) -> bool:
    judgment = _string(row, "judgment", "severity")
    if "strong risk" in judgment.lower():
        return True
    non_strong = {"", "unknown", "not_strong_risk", "none", "null"}
    diagnostic_gate_family = _string(row, "gateFamily")
    diagnostic_gate_name = _string(row, "gateName")
    if any(value.strip().lower() not in non_strong for value in (diagnostic_gate_family, diagnostic_gate_name)):
        return True
    gate_type = _string(row, "strongRiskGateType", "strong_risk_gate_type", "gateType", "gate_type")
    composition = _string(row, "strongRiskCompositionClass", "strong_risk_composition_class", "composition")
    if any(value.strip().lower() not in non_strong for value in (gate_type, composition)):
        return True
    gate_branch = _string(row, "strongRiskExactGateBranch", "strong_risk_exact_gate_branch")
    if not gate_type and not composition and gate_branch.strip().lower() not in non_strong:
        return True
    return False


def _is_hard_evidence_review(row: Mapping[str, Any]) -> bool:
    hard_sources = _listify(_value(row, "hardEvidenceSources", "hard_evidence_sources"))
    hard_strength = _string(row, "hardEvidenceStrength", "hard_evidence_strength")
    judgment = _string(row, "judgment", "severity")
    if hard_sources:
        return True
    return "hard evidence" in judgment.lower() or hard_strength.lower() in {"medium", "strong", "very strong"}


def _links_for_packet(row: Mapping[str, Any]) -> dict[str, str]:
    links: dict[str, str] = {}
    wallet = _string(row, "wallet", "walletAddress", "wallet_address")
    tx_hash = _string(row, "txHash", "transactionHash", "transaction_hash", "tradeId", "trade_id")
    if _valid_wallet(wallet):
        links["polygonscan_wallet"] = f"https://polygonscan.com/address/{wallet}"
    if _valid_tx(tx_hash):
        links["polygonscan_transaction"] = f"https://polygonscan.com/tx/{tx_hash}"
    for key in ("marketUrl", "market_url", "eventUrl", "event_url", "polymarketUrl", "polymarket_url", "url"):
        url = _string(row, key)
        if _http_url(url):
            links["polymarket"] = url
            break
    return links


def _wallet_from_row(row: Mapping[str, Any]) -> str:
    wallet = _string(
        row,
        "wallet",
        "walletAddress",
        "wallet_address",
        "proxyWallet",
        "proxy_wallet",
        "traderWallet",
        "trader_wallet",
    )
    if wallet:
        return wallet
    trader = _string(row, "trader", "maker", "userAddress", "user_address")
    return trader if _valid_wallet(trader) else ""


def _why_this_matters(packet: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if packet.get("group") in {"strong_risk", "overlap"}:
        gate = packet.get("gate_family") or packet.get("gate_name") or packet.get("strong_risk_gate_type")
        reasons.append(f"Saved row is in the Strong Risk review surface via `{gate or 'unknown gate'}`.")
    if packet.get("group") in {"hard_evidence_review", "overlap"}:
        sources = packet.get("hard_evidence_sources") or []
        reasons.append(f"Saved row carries hard-evidence review sources: {', '.join(sources) if sources else 'unspecified'}.")
    if packet.get("opening_exposure_status") in {"confirmed", "Yes", "yes", True}:
        reasons.append("Opening exposure is saved as confirmed, which is more relevant than a close or inventory reduction.")
    if str(packet.get("repricing_source_quality") or "").lower() in {"strong", "mechanical"}:
        reasons.append(f"Repricing source quality is `{packet.get('repricing_source_quality')}`.")
    if str(packet.get("funding_evidence_grade") or "").lower() not in {"", "unknown", "none"}:
        reasons.append(f"Funding evidence grade is `{packet.get('funding_evidence_grade')}`.")
    if _truthy(packet.get("retrospective_only")):
        reasons.append("The row is retrospective-only, useful for review but not proof that the case was live-detectable.")
    return reasons or ["The row was selected because saved local diagnostics classified it for analyst review."]


def _why_may_be_false_positive(packet: Mapping[str, Any]) -> list[str]:
    cautions: list[str] = []
    suppressors = [str(item) for item in packet.get("suppressors") or []]
    if suppressors:
        cautions.append(f"Saved suppressors are present: {', '.join(suppressors)}.")
    if "high_volume_public_user" in suppressors:
        cautions.append("High-volume public-user behavior can create repeated wins without independent insider-style evidence.")
    if "domain_specialist" in suppressors:
        cautions.append("Domain-specialist behavior can look sharp without implying private information.")
    if "near_certainty" in suppressors or "stale_or_resolution_gap" in suppressors:
        cautions.append("Near-certainty or stale/resolution-gap trades may be retrospectively obvious.")
    if str(packet.get("funding_evidence_grade") or "").lower() == "unknown":
        cautions.append("Funding evidence is unknown in saved fields, so funding-based confidence should not be overclaimed.")
    if packet.get("gate_trace_available") is False:
        cautions.append("Gate trace is missing for this saved row, so exact gate provenance is limited.")
    if _truthy(packet.get("retrospective_only")):
        cautions.append("Retrospective-only evidence can inflate apparent precision after outcomes are known.")
    return cautions or ["No explicit suppressor was saved; still verify wallet history, market context, and source attribution before escalation."]


SUPPRESSOR_ADVISORY = {
    "no_independent_hard_evidence": "Check whether accepted hard-evidence sources exist beyond score, volume, timing, or repeated correctness.",
    "high_volume_public_user": "Check whether repeat wins are explained by public high-volume behavior rather than private information.",
    "domain_specialist": "Check whether the wallet is a domain specialist whose public edge explains the trade.",
    "near_certainty": "Check whether the entry was already near certainty when opened.",
    "stale_or_resolution_gap": "Check whether public resolution lag or stale settlement explains the apparent edge.",
    "weak_economic_history": "Check whether weak wallet history makes the apparent signal too thin for escalation.",
    "funding_unknown": "Treat funding as unknown until a fresh trace-enabled run confirms it.",
}

FALSE_POSITIVE_ISSUE_IDS = {
    "no_independent_hard_evidence": "FP-001",
    "high_volume_public_user": "FP-002",
    "near_certainty": "FP-003",
    "stale_or_resolution_gap": "FP-004",
    "weak_economic_history": "FP-005",
    "funding_unknown": "FP-006",
    "gate_trace_missing": "FP-007",
    "retrospective_only": "FP-008",
}

FALSE_POSITIVE_QUESTIONS = {
    "no_independent_hard_evidence": "Which accepted hard-evidence sources are actually present?",
    "high_volume_public_user": "Does the concern survive after removing volume and repeated-win evidence?",
    "near_certainty": "Was the market already close to certain when the position opened?",
    "stale_or_resolution_gap": "Was the relevant outcome already public or effectively settled before platform resolution?",
    "weak_economic_history": "Is the saved wallet history strong enough to distinguish skill from noise?",
    "funding_unknown": "Is funding still unknown because fresh trace-enabled validation is unavailable?",
    "gate_trace_missing": "Can the exact gate trace be verified in source artifacts?",
    "retrospective_only": "Could this have been detected live, or only after the outcome was known?",
}


def _advisory_entry(pattern: str) -> dict[str, str]:
    return {
        "issue_id": FALSE_POSITIVE_ISSUE_IDS.get(pattern, ""),
        "pattern": pattern,
        "message": SUPPRESSOR_ADVISORY.get(pattern, "Review this saved pattern as analyst caution only."),
        "analyst_question": FALSE_POSITIVE_QUESTIONS.get(pattern, "Does the concern survive after considering this context?"),
        "automatic_action_allowed": "false",
        "forbidden_use": "Do not suppress, downgrade, rescore, reroute, or change eligibility from this advisory.",
        "fresh_validation_needed_for_model_use": "true",
    }


def _false_positive_advisory(packet: Mapping[str, Any]) -> list[dict[str, str]]:
    suppressors = [str(item).strip() for item in packet.get("suppressors") or [] if str(item or "").strip()]
    patterns: list[str] = []
    if _missing_packet_field(packet.get("hard_evidence_sources")) and not _truthy(packet.get("has_independent_hard_evidence")):
        patterns.append("no_independent_hard_evidence")
    patterns.extend(suppressors)
    if str(packet.get("funding_evidence_grade") or "").strip().lower() in {"", "unknown", "none", "null"}:
        patterns.append("funding_unknown")
    if packet.get("gate_trace_available") is False or packet.get("gate_trace_available") is None:
        patterns.append("gate_trace_missing")
    if _truthy(packet.get("retrospective_only")):
        patterns.append("retrospective_only")
    advisory: list[dict[str, str]] = []
    seen: set[str] = set()
    for pattern in patterns:
        if pattern in seen:
            continue
        seen.add(pattern)
        advisory.append(_advisory_entry(pattern))
    if not suppressors:
        advisory.append(
            {
                "issue_id": "SCHEMA-005",
                "pattern": "suppressors_missing",
                "message": "No suppressor or false-positive conflict reason is saved on this packet.",
                "analyst_question": "Does source context show high-volume, near-certainty, stale, specialist, or other benign explanation?",
                "automatic_action_allowed": "false",
                "forbidden_use": "Do not treat missing suppressors as proof for or against the case.",
                "fresh_validation_needed_for_model_use": "true",
            }
        )
    return advisory


def _what_to_inspect_next(packet: Mapping[str, Any]) -> list[str]:
    steps = [
        "Open the saved source artifact and confirm the row-level context.",
        "Compare hardEvidenceSources, suppressors, gate branch, and retrospective-only status.",
    ]
    links = packet.get("links") if isinstance(packet.get("links"), Mapping) else {}
    if links.get("polygonscan_wallet"):
        steps.append("Inspect the wallet address on Polygonscan for funding and counterparties.")
    if links.get("polygonscan_transaction"):
        steps.append("Inspect the transaction hash and timing around the market move.")
    if links.get("polymarket"):
        steps.append("Open the Polymarket market/event page and review liquidity, timing, and outcome context.")
    if str(packet.get("funding_evidence_grade") or "").lower() == "unknown":
        steps.append("Treat funding as unknown until fresh trace-enabled validation is available.")
    return steps


def _score_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _first_present(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text.lower() not in {"unknown", "none", "null"}:
            return text
    return "unknown"


def _missing_packet_field(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, list | tuple | set | dict):
        return len(value) == 0
    text = str(value).strip()
    return not text or text.lower() in {"unknown", "none", "null", "[]"}


def _critical_field_warnings(packet: Mapping[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    group = str(packet.get("group") or "")
    strong_surface = group in {"strong_risk", "overlap"}
    if _missing_packet_field(packet.get("hard_evidence_sources")):
        warnings.append(
            {
                "issue_id": "SCHEMA-001",
                "field": "hard_evidence_sources",
                "severity": "high",
                "message": (
                    "No accepted hard-evidence source is saved on this packet. Treat the packet as an analyst "
                    "lead until the source artifact confirms accepted independent evidence."
                ),
                "safe_use": "Review context only; this warning does not suppress, downgrade, or rescore the case.",
            }
        )
    if strong_surface and _missing_packet_field(packet.get("strong_risk_composition_class")):
        warnings.append(
            {
                "issue_id": "SCHEMA-002",
                "field": "strong_risk_composition_class",
                "severity": "high",
                "message": (
                    "Strong Risk composition is missing from saved packet fields. Inspect the source artifact "
                    "before interpreting which evidence family drove the saved Strong Risk surface."
                ),
                "safe_use": "Review context only; this warning does not change Strong Risk gates.",
            }
        )
    if strong_surface and _missing_packet_field(packet.get("strong_risk_exact_gate_branch")):
        warnings.append(
            {
                "issue_id": "SCHEMA-003",
                "field": "strong_risk_exact_gate_branch",
                "severity": "high",
                "message": (
                    "Exact Strong Risk gate branch is missing from saved packet fields. Use the source artifact "
                    "for branch-level interpretation instead of inferring the branch from score alone."
                ),
                "safe_use": "Review context only; this warning does not alter gate behavior.",
            }
        )
    if strong_surface and _missing_packet_field(packet.get("strong_risk_gate_type")):
        warnings.append(
            {
                "issue_id": "SCHEMA-004",
                "field": "strong_risk_gate_type",
                "severity": "high",
                "message": (
                    "Strong Risk gate type is missing from saved packet fields. Treat gate-family interpretation "
                    "as incomplete until the source artifact is inspected."
                ),
                "safe_use": "Review context only; this warning does not change Strong Risk gates.",
            }
        )
    if _missing_packet_field(packet.get("suppressors")):
        warnings.append(
            {
                "issue_id": "SCHEMA-005",
                "field": "suppressors",
                "severity": "medium",
                "message": (
                    "No suppressor or false-positive conflict reason is saved on this packet. Manually verify "
                    "high-volume, near-certainty, stale, or specialist context before escalation."
                ),
                "safe_use": "Advisory review context only; missing suppressors never upgrades or downgrades a case.",
            }
        )
    if _missing_packet_field(packet.get("condition_id")):
        warnings.append(
            {
                "issue_id": "SCHEMA-006",
                "field": "condition_id",
                "severity": "medium",
                "message": (
                    "Condition ID is missing from saved packet fields. Market navigation should use the market text, "
                    "target label, and source artifact path instead."
                ),
                "safe_use": "Navigation context only; this warning does not broaden market scope.",
            }
        )
    if _missing_packet_field(packet.get("trade_id")):
        warnings.append(
            {
                "issue_id": "SCHEMA-007",
                "field": "trade_id",
                "severity": "medium",
                "message": (
                    "Trade ID or transaction hash is missing from saved packet fields. Use timestamp, wallet, "
                    "market, and source artifact row for navigation."
                ),
                "safe_use": "Navigation context only; this warning does not infer transaction evidence.",
            }
        )
    if _missing_packet_field(packet.get("market")):
        warnings.append(
            {
                "issue_id": "SCHEMA-008",
                "field": "market",
                "severity": "medium",
                "message": (
                    "Market display text is missing from saved packet fields. Use condition ID, target label, "
                    "and source artifact path for review."
                ),
                "safe_use": "Navigation context only; this warning does not broaden event or market scope.",
            }
        )
    if _missing_packet_field(packet.get("wallet")):
        warnings.append(
            {
                "issue_id": "SCHEMA-009",
                "field": "wallet",
                "severity": "medium",
                "message": (
                    "Wallet address is missing from saved packet fields. Use trader name, source row, and market context "
                    "for review; do not infer wallet linkage."
                ),
                "safe_use": "Navigation context only; this warning does not create wallet linkage.",
            }
        )
    return warnings


def packet_from_row(row: Mapping[str, Any], *, group_size: int = 1, sources: Sequence[str] | None = None) -> dict[str, Any] | None:
    strong = _is_strong_risk(row)
    hard = _is_hard_evidence_review(row)
    if not strong and not hard:
        return None
    group = "overlap" if strong and hard else "strong_risk" if strong else "hard_evidence_review"
    packet: dict[str, Any] = {
        "packet_id": "",
        "group": group,
        "dedupe_key": dedupe_key_for_row(row),
        "dedupe_group_size": group_size,
        "wallet": _wallet_from_row(row),
        "trader_name": _string(row, "traderName", "trader_name", "username", "name"),
        "market": _string(
            row,
            "market",
            "marketTitle",
            "market_title",
            "marketQuestion",
            "market_question",
            "event",
            "eventTitle",
            "event_title",
            "question",
        ),
        "condition_id": _string(row, "conditionId", "condition_id", "marketConditionId", "market_condition_id", "condition"),
        "trade_id": _string(row, "tradeId", "trade_id", "row_id", "txHash", "transactionHash", "transaction_hash"),
        "timestamp": _string(row, "timestamp", "createdAt", "created_at"),
        "notional": _string(row, "notional", "capitalAtRisk", "capital_at_risk"),
        "score": _value(row, "score", "walletScore", "eventForensicScore", "suspicion_score"),
        "severity": _string(row, "severity"),
        "judgment": _string(row, "judgment"),
        "strong_risk_gate_type": _string(row, "strongRiskGateType", "strong_risk_gate_type", "gateType", "gate_type", "gateFamily"),
        "strong_risk_exact_gate_branch": _string(
            row, "strongRiskExactGateBranch", "strong_risk_exact_gate_branch", "gateBranch", "gate_branch", "gateName"
        ),
        "strong_risk_composition_class": _string(
            row, "strongRiskCompositionClass", "strong_risk_composition_class", "composition", "gateFamily"
        ),
        "gate_family": _string(row, "gateFamily"),
        "gate_name": _string(row, "gateName"),
        "funding_evidence_grade": _string(row, "fundingEvidenceGrade", "funding_evidence_grade"),
        "hard_evidence_sources": _listify(_value(row, "hardEvidenceSources", "hard_evidence_sources")),
        "independent_evidence_sources": _listify(_value(row, "independentEvidenceSources", "independent_evidence_sources")),
        "has_independent_hard_evidence": _truthy(_value(row, "hasIndependentHardEvidence", "strongRiskHasIndependentHardEvidence")),
        "suppressors": _listify(
            _value(
                row,
                "suppressors",
                "strongRiskSuppressorConflictReasons",
                "strong_risk_suppressor_conflict_reasons",
                "suppressorConflictReasons",
                "suppressor_conflict_reasons",
            )
        ),
        "suppressor_conflict": _truthy(_value(row, "suppressorConflict", "strongRiskSuppressorConflict")),
        "opening_exposure_status": _string(row, "openingExposureStatus", "strongRiskOpeningExposureStatus", "opening_exposure_status"),
        "repricing_source_quality": _string(row, "repricingSourceQuality", "repricing_source_quality"),
        "retrospective_only": _truthy(_value(row, "retrospectiveOnly", "strongRiskRetrospectiveOnly")),
        "live_detectable": _value(row, "liveDetectable", "strongRiskLiveDetectable"),
        "timing_repricing_only": _truthy(_value(row, "timingRepricingOnly", "strongRiskTimingRepricingOnly")),
        "score_only": _truthy(_value(row, "scoreOnly", "strongRiskScoreOnly")),
        "gate_trace_available": _value(row, "gateTraceAvailable", "strong_risk_gate_trace_available"),
        "source_path": _string(row, "sourcePath", "source_path"),
        "source_row": _string(row, "sourceRow", "source_row"),
        "target": _string(row, "target", "bundle", "validationTargetLabel"),
        "source_collections": sorted(set(sources or [])),
        "links": _links_for_packet(row),
    }
    packet["source_navigation"] = {
        "source_path": packet["source_path"],
        "source_row": packet["source_row"],
        "source_collections": packet["source_collections"],
        "wallet": packet["wallet"],
        "market": packet["market"],
        "condition_id": packet["condition_id"],
        "trade_id": packet["trade_id"],
    }
    packet["why_this_matters"] = _why_this_matters(packet)
    packet["why_this_may_be_false_positive"] = _why_may_be_false_positive(packet)
    packet["what_to_inspect_next"] = _what_to_inspect_next(packet)
    packet["false_positive_advisory"] = _false_positive_advisory(packet)
    packet["critical_field_warnings"] = _critical_field_warnings(packet)
    return packet


def build_packets_from_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    source_collections: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = dedupe_key_for_row(row)
        grouped[key].append(row)
        collection = _string(row, "_source_collection")
        if collection:
            source_collections[key].append(collection)

    packets: list[dict[str, Any]] = []
    for key, group_rows in sorted(grouped.items(), key=lambda item: item[0]):
        packet = packet_from_row(
            group_rows[0],
            group_size=len(group_rows),
            sources=source_collections.get(key) or [],
        )
        if packet is None:
            continue
        packet["dedupe_key"] = key
        packets.append(packet)

    group_rank = {"overlap": 0, "strong_risk": 1, "hard_evidence_review": 2}
    packets.sort(
        key=lambda item: (
            group_rank.get(str(item.get("group")), 9),
            -float(item.get("score") or 0) if isinstance(item.get("score"), (int, float)) else 0,
            str(item.get("wallet") or ""),
            str(item.get("dedupe_key") or ""),
        )
    )
    for index, packet in enumerate(packets, start=1):
        packet["packet_id"] = f"packet_{index:04d}"
    return packets


def build_wallet_groups(packets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for packet in packets:
        grouped[_first_present(packet.get("wallet"), packet.get("trader_name"))].append(packet)

    groups: list[dict[str, Any]] = []
    for wallet, wallet_packets in grouped.items():
        suppressors = Counter(
            str(suppressor)
            for packet in wallet_packets
            for suppressor in (packet.get("suppressors") or [])
            if str(suppressor or "").strip()
        )
        markets = sorted(
            {
                _first_present(packet.get("condition_id"), packet.get("market"))
                for packet in wallet_packets
                if _first_present(packet.get("condition_id"), packet.get("market")) != "unknown"
            }
        )
        scores = [_score_number(packet.get("score")) for packet in wallet_packets]
        links = [
            packet.get("links", {}).get("polygonscan_wallet")
            for packet in wallet_packets
            if isinstance(packet.get("links"), Mapping) and packet.get("links", {}).get("polygonscan_wallet")
        ]
        groups.append(
            {
                "wallet": wallet,
                "packet_count": len(wallet_packets),
                "strong_risk_packet_count": sum(1 for packet in wallet_packets if packet.get("group") in {"strong_risk", "overlap"}),
                "hard_evidence_review_packet_count": sum(
                    1 for packet in wallet_packets if packet.get("group") in {"hard_evidence_review", "overlap"}
                ),
                "overlap_packet_count": sum(1 for packet in wallet_packets if packet.get("group") == "overlap"),
                "dedupe_group_size_total": sum(int(packet.get("dedupe_group_size") or 1) for packet in wallet_packets),
                "market_count": len(markets),
                "markets": markets[:12],
                "suppressor_themes": [
                    {"name": name, "count": count} for name, count in suppressors.most_common(8)
                ],
                "max_score": max((score for score in scores if score is not None), default=None),
                "packet_ids": [str(packet.get("packet_id") or "") for packet in wallet_packets],
                "wallet_link": links[0] if links else "",
            }
        )
    groups.sort(
        key=lambda item: (
            -int(item.get("packet_count") or 0),
            -int(item.get("dedupe_group_size_total") or 0),
            -(float(item.get("max_score")) if item.get("max_score") is not None else -1),
            str(item.get("wallet") or ""),
        )
    )
    return groups


def build_market_groups(packets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for packet in packets:
        key = _first_present(packet.get("condition_id"), packet.get("market"), packet.get("target"))
        grouped[key].append(packet)

    groups: list[dict[str, Any]] = []
    for key, market_packets in grouped.items():
        wallets = sorted(
            {
                _first_present(packet.get("wallet"), packet.get("trader_name"))
                for packet in market_packets
                if _first_present(packet.get("wallet"), packet.get("trader_name")) != "unknown"
            }
        )
        suppressors = Counter(
            str(suppressor)
            for packet in market_packets
            for suppressor in (packet.get("suppressors") or [])
            if str(suppressor or "").strip()
        )
        scores = [_score_number(packet.get("score")) for packet in market_packets]
        market_names = [
            str(packet.get("market") or "").strip()
            for packet in market_packets
            if str(packet.get("market") or "").strip()
        ]
        polymarket_links = [
            packet.get("links", {}).get("polymarket")
            for packet in market_packets
            if isinstance(packet.get("links"), Mapping) and packet.get("links", {}).get("polymarket")
        ]
        groups.append(
            {
                "market_key": key,
                "market": market_names[0] if market_names else key,
                "packet_count": len(market_packets),
                "wallet_count": len(wallets),
                "wallets": wallets[:12],
                "strong_risk_packet_count": sum(1 for packet in market_packets if packet.get("group") in {"strong_risk", "overlap"}),
                "hard_evidence_review_packet_count": sum(
                    1 for packet in market_packets if packet.get("group") in {"hard_evidence_review", "overlap"}
                ),
                "overlap_packet_count": sum(1 for packet in market_packets if packet.get("group") == "overlap"),
                "suppressor_themes": [
                    {"name": name, "count": count} for name, count in suppressors.most_common(8)
                ],
                "max_score": max((score for score in scores if score is not None), default=None),
                "packet_ids": [str(packet.get("packet_id") or "") for packet in market_packets],
                "polymarket_link": polymarket_links[0] if polymarket_links else "",
            }
        )
    groups.sort(
        key=lambda item: (
            -int(item.get("packet_count") or 0),
            -int(item.get("wallet_count") or 0),
            -(float(item.get("max_score")) if item.get("max_score") is not None else -1),
            str(item.get("market_key") or ""),
        )
    )
    return groups


def build_retrospective_summary(packets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    retrospective = [packet for packet in packets if _truthy(packet.get("retrospective_only"))]
    gate_trace_missing = [packet for packet in packets if packet.get("gate_trace_available") is False or packet.get("gate_trace_available") is None]
    funding_unknown = [
        packet
        for packet in packets
        if str(packet.get("funding_evidence_grade") or "").strip().lower() in {"", "unknown", "none", "null"}
    ]
    live_unknown = [
        packet
        for packet in packets
        if str(packet.get("live_detectable") or "").strip().lower() in {"", "unknown", "none", "null"}
    ]
    return {
        "retrospective_only_packets": len(retrospective),
        "gate_trace_missing_packets": len(gate_trace_missing),
        "funding_unknown_packets": len(funding_unknown),
        "live_detectable_unknown_packets": len(live_unknown),
        "warning": (
            "Saved packets may include cache-only, retrospective-only, or gate-trace-limited evidence. "
            "Use these as analyst review leads, not as fresh trace-enabled gate-decision proof."
        ),
        "packet_ids": [str(packet.get("packet_id") or "") for packet in retrospective[:50]],
    }


def _collect_rows_from_payload(payload: Mapping[str, Any], source_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("topManualInspectionRows", "topPotentialGateLeakageCandidates"):
        value = payload.get(key)
        if isinstance(value, list):
            for row in value:
                if isinstance(row, Mapping):
                    copied = dict(row)
                    copied["_source_collection"] = f"{source_name}:{key}"
                    rows.append(copied)
    stratified = payload.get("stratifiedExamples")
    if isinstance(stratified, Mapping):
        for key, value in stratified.items():
            if not isinstance(value, list):
                continue
            for row in value:
                if isinstance(row, Mapping):
                    copied = dict(row)
                    copied["_source_collection"] = f"{source_name}:stratifiedExamples.{key}"
                    rows.append(copied)
    for key in ("warnings", "examples", "casePackets"):
        value = payload.get(key)
        if isinstance(value, list):
            for row in value:
                if isinstance(row, Mapping):
                    copied = dict(row)
                    copied["_source_collection"] = f"{source_name}:{key}"
                    rows.append(copied)
    return rows


def _input_paths_from_readiness(readiness: Mapping[str, Any]) -> list[Path]:
    artifacts = readiness.get("inputArtifacts")
    if not isinstance(artifacts, Mapping):
        return []
    keys = ("corpus_provenance_drilldown", "strong_risk_diagnostic", "model_behavior_audit", "corpus_output")
    paths = []
    for key in keys:
        resolved = _resolve(str(artifacts.get(key) or "").strip() or None)
        if resolved and resolved.exists():
            paths.append(resolved)
    return paths


def discover_input_paths(
    *,
    validation_output_dir: Path = DEFAULT_VALIDATION_OUTPUT_DIR,
    strong_risk_dir: Path = DEFAULT_STRONG_RISK_DIR,
    explicit_inputs: Sequence[Path] | None = None,
) -> list[Path]:
    if explicit_inputs:
        return [path for path in (_resolve(item) for item in explicit_inputs) if path and path.exists()]
    readiness_path = _latest_file(validation_output_dir, "gate_decision_readiness_*.json")
    readiness = _load_json(readiness_path)
    paths = _input_paths_from_readiness(readiness)
    fallback_candidates = [
        _latest_file(strong_risk_dir, "strong_risk_gate_diagnostic_*.json"),
        _latest_file(validation_output_dir, "corpus_provenance_drilldown_*.json"),
        _latest_file(validation_output_dir, "post_v2_corpus_audit_*.json"),
        _latest_file(validation_output_dir, "post_v2_corpus_*.json"),
    ]
    for path in fallback_candidates:
        if path and path.exists() and path not in paths:
            paths.append(path)
    return paths


def build_review_packet_payload(input_paths: Sequence[Path]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    loaded_paths: list[str] = []
    for path in input_paths:
        payload = _load_json(path)
        if not payload:
            continue
        loaded_paths.append(str(path))
        rows.extend(_collect_rows_from_payload(payload, path.name))
    packets = build_packets_from_rows(rows)
    wallet_groups = build_wallet_groups(packets)
    market_groups = build_market_groups(packets)
    retrospective_summary = build_retrospective_summary(packets)
    group_counts = Counter(str(packet.get("group")) for packet in packets)
    critical_warning_counts = Counter(
        str(warning.get("issue_id") or "unknown")
        for packet in packets
        for warning in (packet.get("critical_field_warnings") or [])
        if isinstance(warning, Mapping)
    )
    overlap_count = group_counts.get("overlap", 0)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "input_paths": loaded_paths,
        "source_rows_collected": len(rows),
        "unique_packet_count": len(packets),
        "strong_risk_packets": group_counts.get("strong_risk", 0) + overlap_count,
        "hard_evidence_review_packets": group_counts.get("hard_evidence_review", 0) + overlap_count,
        "overlap_packets": overlap_count,
        "packets_with_wallet_links": sum(1 for packet in packets if packet.get("links", {}).get("polygonscan_wallet")),
        "packets_with_transaction_links": sum(1 for packet in packets if packet.get("links", {}).get("polygonscan_transaction")),
        "packets_with_polymarket_links": sum(1 for packet in packets if packet.get("links", {}).get("polymarket")),
        "wallet_group_count": len(wallet_groups),
        "market_group_count": len(market_groups),
        "source_navigation_packets": sum(1 for packet in packets if packet.get("source_path")),
        "retrospective_only_packets": retrospective_summary["retrospective_only_packets"],
        "gate_trace_missing_packets": retrospective_summary["gate_trace_missing_packets"],
        "funding_unknown_packets": retrospective_summary["funding_unknown_packets"],
        "packets_with_critical_field_warnings": sum(1 for packet in packets if packet.get("critical_field_warnings")),
        "packets_with_false_positive_advisory": sum(1 for packet in packets if packet.get("false_positive_advisory")),
        "critical_field_warning_counts": dict(sorted(critical_warning_counts.items())),
        "limitations": [
            "This is generated from saved local artifacts only.",
            "It does not change scoring, gates, labels, HER routing, or funding eligibility.",
            "Cache-only and retrospective-only evidence must not be overclaimed as fresh trace-enabled proof.",
        ],
    }
    return {
        "summary": summary,
        "wallet_groups": wallet_groups,
        "market_groups": market_groups,
        "retrospective_summary": retrospective_summary,
        "packets": packets,
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    packets = payload.get("packets") if isinstance(payload.get("packets"), list) else []
    lines = [
        "# Unique Review Packets",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Source rows collected: {summary.get('source_rows_collected', 0)}",
        f"- Unique packets: {summary.get('unique_packet_count', 0)}",
        f"- Strong Risk packets: {summary.get('strong_risk_packets', 0)}",
        f"- Hard Evidence Review packets: {summary.get('hard_evidence_review_packets', 0)}",
        f"- Overlap packets: {summary.get('overlap_packets', 0)}",
        f"- Wallet links: {summary.get('packets_with_wallet_links', 0)}",
        f"- Transaction links: {summary.get('packets_with_transaction_links', 0)}",
        f"- Polymarket links: {summary.get('packets_with_polymarket_links', 0)}",
        f"- Wallet groups: {summary.get('wallet_group_count', 0)}",
        f"- Market groups: {summary.get('market_group_count', 0)}",
        f"- Source-navigation packets: {summary.get('source_navigation_packets', 0)}",
        f"- Retrospective-only packets: {summary.get('retrospective_only_packets', 0)}",
        f"- Gate-trace-missing packets: {summary.get('gate_trace_missing_packets', 0)}",
        f"- Funding-unknown packets: {summary.get('funding_unknown_packets', 0)}",
        f"- Packets with critical field warnings: {summary.get('packets_with_critical_field_warnings', 0)}",
        f"- Packets with false-positive advisory: {summary.get('packets_with_false_positive_advisory', 0)}",
        "",
        "## Limitations",
    ]
    for item in summary.get("limitations") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Input Paths"])
    for path in summary.get("input_paths") or []:
        lines.append(f"- {path}")
    if not packets:
        lines.extend(["", "## Packets", "", "- No Strong Risk or Hard Evidence Review packets were built from the selected artifacts."])
        return "\n".join(lines).rstrip() + "\n"

    retrospective_summary = payload.get("retrospective_summary") if isinstance(payload.get("retrospective_summary"), Mapping) else {}
    lines.extend(
        [
            "",
            "## Evidence Freshness Warnings",
            "",
            f"- Retrospective-only packets: {retrospective_summary.get('retrospective_only_packets', 0)}",
            f"- Gate-trace-missing packets: {retrospective_summary.get('gate_trace_missing_packets', 0)}",
            f"- Funding-unknown packets: {retrospective_summary.get('funding_unknown_packets', 0)}",
            f"- Warning: {retrospective_summary.get('warning', '')}",
            "",
            "## Wallet Groups",
            "",
        ]
    )
    for group in (payload.get("wallet_groups") or [])[:25]:
        themes = ", ".join(f"{item.get('name')} ({item.get('count')})" for item in group.get("suppressor_themes") or []) or "none"
        lines.append(
            f"- `{group.get('wallet')}`: {group.get('packet_count')} packets, "
            f"{group.get('market_count')} markets, suppressors: {themes}"
        )
    if not payload.get("wallet_groups"):
        lines.append("- none")
    lines.extend(["", "## Market Groups", ""])
    for group in (payload.get("market_groups") or [])[:25]:
        themes = ", ".join(f"{item.get('name')} ({item.get('count')})" for item in group.get("suppressor_themes") or []) or "none"
        lines.append(
            f"- `{group.get('market_key')}`: {group.get('packet_count')} packets, "
            f"{group.get('wallet_count')} wallets, suppressors: {themes}"
        )
    if not payload.get("market_groups"):
        lines.append("- none")

    for group, heading in (
        ("overlap", "Overlap: Strong Risk And HER"),
        ("strong_risk", "Strong Risk"),
        ("hard_evidence_review", "Hard Evidence Review"),
    ):
        group_packets = [packet for packet in packets if packet.get("group") == group]
        lines.extend(["", f"## {heading}", ""])
        if not group_packets:
            lines.append("- none")
            continue
        for packet in group_packets[:50]:
            wallet = packet.get("wallet") or "unknown wallet"
            market = packet.get("market") or "unknown market"
            score = packet.get("score")
            lines.append(f"### {packet.get('packet_id')} - {wallet}")
            lines.append("")
            lines.append(f"- Market: {market}")
            lines.append(f"- Score: {score if score is not None else 'unknown'}")
            lines.append(f"- Dedupe group size: {packet.get('dedupe_group_size', 1)}")
            lines.append(f"- Gate: {packet.get('gate_family') or packet.get('strong_risk_composition_class') or 'unknown'} / {packet.get('gate_name') or packet.get('strong_risk_exact_gate_branch') or 'unknown'}")
            lines.append(f"- Hard evidence sources: {', '.join(packet.get('hard_evidence_sources') or []) or 'none'}")
            warnings = packet.get("critical_field_warnings") if isinstance(packet.get("critical_field_warnings"), list) else []
            if warnings:
                lines.append("- Critical field warnings:")
                for warning in warnings:
                    if not isinstance(warning, Mapping):
                        continue
                    lines.append(
                        f"  - {warning.get('issue_id', 'unknown')} `{warning.get('field', 'unknown')}`: "
                        f"{warning.get('message', '')}"
                    )
            links = packet.get("links") if isinstance(packet.get("links"), Mapping) else {}
            if links:
                lines.append("- Links:")
                for label, url in links.items():
                    lines.append(f"  - {label}: {url}")
            lines.append("- Why this matters:")
            for reason in packet.get("why_this_matters") or []:
                lines.append(f"  - {reason}")
            lines.append("- Why this may be false positive:")
            for caution in packet.get("why_this_may_be_false_positive") or []:
                lines.append(f"  - {caution}")
            advisory = packet.get("false_positive_advisory") if isinstance(packet.get("false_positive_advisory"), list) else []
            if advisory:
                lines.append("- False-positive advisory:")
                for item in advisory:
                    if isinstance(item, Mapping):
                        lines.append(f"  - {item.get('pattern', 'unknown')}: {item.get('message', '')}")
            lines.append("- What to inspect next:")
            for step in packet.get("what_to_inspect_next") or []:
                lines.append(f"  - {step}")
            if packet.get("source_path"):
                lines.append(f"- Source: {packet.get('source_path')} row {packet.get('source_row') or 'unknown'}")
            source_navigation = packet.get("source_navigation") if isinstance(packet.get("source_navigation"), Mapping) else {}
            collections = source_navigation.get("source_collections") if isinstance(source_navigation.get("source_collections"), list) else []
            if collections:
                lines.append("- Source collections:")
                for collection in collections[:8]:
                    lines.append(f"  - {collection}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved_output_dir = _resolve(output_dir) or output_dir
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved_output_dir / f"unique_review_packets_{stamp}.json"
    markdown_path = resolved_output_dir / f"unique_review_packets_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate deduped analyst review packets from saved local artifacts.")
    parser.add_argument("inputs", nargs="*", type=Path, help="Optional JSON artifacts to inspect.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--validation-output-dir", type=Path, default=DEFAULT_VALIDATION_OUTPUT_DIR)
    parser.add_argument("--strong-risk-dir", type=Path, default=DEFAULT_STRONG_RISK_DIR)
    args = parser.parse_args(argv)

    input_paths = discover_input_paths(
        validation_output_dir=args.validation_output_dir,
        strong_risk_dir=args.strong_risk_dir,
        explicit_inputs=args.inputs,
    )
    payload = build_review_packet_payload(input_paths)
    outputs = write_outputs(payload, args.output_dir)
    summary = payload.get("summary", {})
    print(f"Unique review packets JSON: {outputs['json_path']}")
    print(f"Unique review packets markdown: {outputs['markdown_path']}")
    print(f"Unique packets: {summary.get('unique_packet_count', 0)}")
    print(f"Strong Risk packets: {summary.get('strong_risk_packets', 0)}")
    print(f"Hard Evidence Review packets: {summary.get('hard_evidence_review_packets', 0)}")
    print(f"Overlap packets: {summary.get('overlap_packets', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
