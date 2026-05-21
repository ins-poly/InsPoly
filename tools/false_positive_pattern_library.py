from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW_PACKET_DIR = Path("review_packets")
DEFAULT_AI_REVIEW_DIR = Path("ai_review_outputs")
DEFAULT_OUTPUT_DIR = Path("false_positive_library")

PATTERN_DEFINITIONS: dict[str, dict[str, str]] = {
    "high_volume_public_user": {
        "label": "High-volume public user",
        "analyst_meaning": "Repeated activity or repeated wins can look insider-style even when the wallet behaves like a public power user.",
        "inspect_next": "Check whether independent hard evidence exists beyond volume, repeated wins, or event saturation.",
    },
    "event_saturation": {
        "label": "Event saturation",
        "analyst_meaning": "A wallet trading many markets in the same event may naturally create many later-correct entries.",
        "inspect_next": "Compare unique event markets traded, opening entries, and independent evidence sources.",
    },
    "near_certainty": {
        "label": "Near-certainty entry",
        "analyst_meaning": "Trades entered at very high probabilities can appear correct without carrying insider-style information.",
        "inspect_next": "Review price at entry and whether the market was already effectively resolved.",
    },
    "stale_or_resolution_gap": {
        "label": "Stale or resolution-gap trade",
        "analyst_meaning": "Public information or delayed resolution can make a trade look stronger after the fact.",
        "inspect_next": "Check timestamp, outcome timing, and whether the edge was live-detectable before resolution.",
    },
    "domain_specialist": {
        "label": "Domain specialist",
        "analyst_meaning": "A skilled public specialist can produce sharp-looking trades without private information.",
        "inspect_next": "Review wallet history across related public domains and compare against source attribution.",
    },
    "weak_economic_history": {
        "label": "Weak economic history",
        "analyst_meaning": "A wallet with weak broader performance may be a noisy winner rather than a strong lead.",
        "inspect_next": "Check historical prediction count, win/loss profile, and whether current evidence is independently strong.",
    },
    "bot_like": {
        "label": "Bot-like execution",
        "analyst_meaning": "Mechanical execution can inflate case counts without indicating human insider-style selection.",
        "inspect_next": "Look for repeated tiny trades, systematic timing, or automation-like order behavior.",
    },
    "yield_farm": {
        "label": "Yield-farm behavior",
        "analyst_meaning": "Some trades may be liquidity, rewards, or yield behavior rather than informational bets.",
        "inspect_next": "Check whether the trade economics look like incentive harvesting rather than directional conviction.",
    },
    "theta_decay": {
        "label": "Deadline/theta decay",
        "analyst_meaning": "Deadline markets can drift predictably as time passes, weakening insider-style interpretation.",
        "inspect_next": "Inspect time-to-deadline and whether the price move was mechanical.",
    },
    "resolution_gap": {
        "label": "Resolution gap",
        "analyst_meaning": "The trade may benefit from known or nearly known outcomes before platform resolution catches up.",
        "inspect_next": "Compare public outcome availability against trade timestamp.",
    },
    "funding_unknown": {
        "label": "Funding unknown",
        "analyst_meaning": "Funding cannot support or refute the case when trace evidence is unavailable.",
        "inspect_next": "Treat funding as unknown until fresh trace-enabled validation is available.",
    },
    "no_independent_hard_evidence": {
        "label": "No independent hard evidence",
        "analyst_meaning": "A case based only on volume, score, timing, or repeated correctness should not be escalated as hard evidence.",
        "inspect_next": "Look for dormant reactivation, low-probability winner, split/shared funding, or other accepted independent sources.",
    },
    "retrospective_only": {
        "label": "Retrospective-only evidence",
        "analyst_meaning": "Later correctness is useful for audit but can overstate what was knowable live.",
        "inspect_next": "Separate after-the-fact correctness from live-detectable timing or structure.",
    },
    "gate_trace_missing": {
        "label": "Gate trace missing",
        "analyst_meaning": "Older saved rows may not explain the exact Strong Risk gate branch.",
        "inspect_next": "Use these rows as review examples, not as gate-change evidence.",
    },
}

PATTERN_REVIEW_QUESTIONS: dict[str, list[str]] = {
    "high_volume_public_user": [
        "Does the concern survive after removing volume and repeated-win evidence?",
        "Is there independent hard evidence such as low-probability timing, dormancy, or linked funding?",
    ],
    "event_saturation": [
        "Did the wallet trade many markets in the same event, creating repeated correctness mechanically?",
        "Are the notable wins concentrated in public/near-resolved markets?",
    ],
    "near_certainty": [
        "Was entry price already near certainty before the saved trade?",
        "Would a live analyst have seen the trade as informational or simply late public consensus?",
    ],
    "stale_or_resolution_gap": [
        "Was the relevant outcome already public or effectively settled before platform resolution?",
        "Can the packet separate public-lag exploitation from private-information behavior?",
    ],
    "funding_unknown": [
        "Is the funding field unknown because RPC was unavailable rather than because no funding link exists?",
        "Should this packet wait for fresh trace-enabled validation before funding interpretation?",
    ],
    "no_independent_hard_evidence": [
        "Which accepted hard-evidence sources are actually present?",
        "Is the case driven only by score, volume, timing, or retrospective correctness?",
    ],
    "retrospective_only": [
        "Can the case be justified using only live-detectable evidence?",
        "Is later correctness being treated as audit context rather than live proof?",
    ],
    "gate_trace_missing": [
        "Is the exact Strong Risk gate branch unavailable because the row is legacy or cache-only?",
        "Should this be used as a review example instead of a gate-change example?",
    ],
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
    candidates = sorted(root.glob(pattern), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return candidates[0] if candidates else None


def _latest_files(directory: Path, pattern: str, limit: int) -> list[Path]:
    root = _resolve(directory) or directory
    if not root.exists():
        return []
    return sorted(root.glob(pattern), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)[:limit]


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


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


def _text_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _get(mapping: Mapping[str, Any], key: str, default: Any = None) -> Any:
    if key in mapping:
        return mapping.get(key, default)
    lower_map = {str(item).lower(): item for item in mapping}
    actual = lower_map.get(key.lower())
    return mapping.get(actual, default) if actual is not None else default


def _nested(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = _get(mapping, key, {})
    return value if isinstance(value, Mapping) else {}


def _string(mapping: Mapping[str, Any], key: str) -> str:
    value = _get(mapping, key, "")
    return value.strip() if isinstance(value, str) else str(value).strip() if value is not None else ""


def _pattern_keys_from_packet(packet: Mapping[str, Any]) -> set[str]:
    keys = {item for item in _listify(_get(packet, "suppressors")) if item in PATTERN_DEFINITIONS}
    if str(_get(packet, "funding_evidence_grade", "")).lower() in {"", "unknown", "none"}:
        keys.add("funding_unknown")
    if not _truthy(_get(packet, "has_independent_hard_evidence")) and not _listify(_get(packet, "hard_evidence_sources")):
        keys.add("no_independent_hard_evidence")
    if _truthy(_get(packet, "retrospective_only")):
        keys.add("retrospective_only")
    if _get(packet, "gate_trace_available") is False:
        keys.add("gate_trace_missing")
    for caution in _text_list(_get(packet, "why_this_may_be_false_positive")):
        lower = caution.lower()
        if "high-volume" in lower or "public-user" in lower:
            keys.add("high_volume_public_user")
        if "funding evidence is unknown" in lower:
            keys.add("funding_unknown")
        if "retrospective-only" in lower:
            keys.add("retrospective_only")
    return keys


def _pattern_keys_from_case(packet: Mapping[str, Any], review: Mapping[str, Any]) -> set[str]:
    reducers = _nested(packet, "reducers")
    keys = {key for key, enabled in reducers.items() if _truthy(enabled) and key in PATTERN_DEFINITIONS}
    export_context = _nested(packet, "wallet_export_context")
    if _truthy(export_context.get("walletPublicPowerUserFlag")):
        keys.add("high_volume_public_user")
    if _truthy(export_context.get("walletHighVolumeEventUserFlag")):
        keys.add("high_volume_public_user")
    if _truthy(export_context.get("walletEventSaturationFlag")):
        keys.add("event_saturation")
    support = _nested(packet, "supporting_evidence")
    if not _truthy(support.get("independent_hard_evidence")) and not _listify(support.get("hard_evidence_sources")):
        keys.add("no_independent_hard_evidence")
    if str(support.get("suspicious_funding_quality") or "").lower() == "unknown":
        keys.add("funding_unknown")
    interpretation = _string(review, "interpretation_class")
    if interpretation == "high_volume_public_power_user":
        keys.add("high_volume_public_user")
    if interpretation == "stale_or_resolution_gap":
        keys.add("stale_or_resolution_gap")
    for text in _text_list(_get(review, "evidence_that_weakens_concern")):
        lower = text.lower()
        if "near-certainty" in lower:
            keys.add("near_certainty")
        if "high-volume" in lower or "repeated wins" in lower:
            keys.add("high_volume_public_user")
        if "no independent" in lower:
            keys.add("no_independent_hard_evidence")
        if "funding" in lower and "unknown" in lower:
            keys.add("funding_unknown")
    return keys


def _packet_example(packet: Mapping[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_type": "unique_review_packet",
        "source_path": source_path,
        "packet_id": _string(packet, "packet_id"),
        "group": _string(packet, "group"),
        "wallet": _string(packet, "wallet"),
        "market": _string(packet, "market"),
        "score": _get(packet, "score"),
        "suppressors": _listify(_get(packet, "suppressors")),
        "funding_evidence_grade": _string(packet, "funding_evidence_grade"),
        "why_false_positive": _text_list(_get(packet, "why_this_may_be_false_positive"))[:3],
    }


def _case_example(packet: Mapping[str, Any], review: Mapping[str, Any], source_path: str) -> dict[str, Any]:
    activity = _nested(packet, "event_activity")
    scores = _nested(packet, "scores")
    return {
        "source_type": "case_reviewer",
        "source_path": source_path,
        "case_id": _string(packet, "case_id") or _string(review, "case_id"),
        "review_verdict": _string(review, "review_verdict"),
        "interpretation_class": _string(review, "interpretation_class"),
        "wallet": _string(packet, "wallet"),
        "username": _string(packet, "username"),
        "event": _string(packet, "event"),
        "wallet_score": scores.get("wallet_score"),
        "insider_style_wallet_score": scores.get("insider_style_wallet_score"),
        "event_trade_count": activity.get("event_trade_count"),
        "notable_trade_count": activity.get("notable_trade_count"),
        "winning_opening_entry_count": activity.get("winning_opening_entry_count"),
        "weakening_evidence": _text_list(_get(review, "evidence_that_weakens_concern"))[:4],
        "recommended_model_change": _text_list(_get(review, "recommended_model_change"))[:3],
    }


def _add_example(pattern_examples: dict[str, list[dict[str, Any]]], pattern_key: str, example: dict[str, Any], limit: int) -> None:
    examples = pattern_examples[pattern_key]
    identity = json.dumps(example, sort_keys=True, default=str)
    if any(json.dumps(existing, sort_keys=True, default=str) == identity for existing in examples):
        return
    if len(examples) < limit:
        examples.append(example)


def _analyst_playbook(pattern_key: str, definition: Mapping[str, str]) -> dict[str, Any]:
    return {
        "review_questions": PATTERN_REVIEW_QUESTIONS.get(
            pattern_key,
            [
                "Does the pattern explain the saved concern without private-information behavior?",
                "What independent evidence would be needed before escalation?",
            ],
        ),
        "packet_note": definition.get("analyst_meaning", ""),
        "inspect_next": definition.get("inspect_next", ""),
        "automatic_action_allowed": False,
        "fresh_validation_needed_for_model_use": True,
        "do_not_do": [
            "Do not automatically suppress rows from this pattern.",
            "Do not change scores, gates, HER routing, or funding eligibility from this library.",
            "Do not treat cache-only or retrospective-only examples as fresh precision evidence.",
        ],
    }


def _case_reviews_by_id(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for review in reviews:
        if not isinstance(review, Mapping):
            continue
        case_id = _string(review, "case_id")
        if case_id:
            result[case_id] = review
    return result


def discover_input_paths(
    *,
    review_packet_path: Path | None = None,
    ai_review_dir: Path = DEFAULT_AI_REVIEW_DIR,
    max_case_reviewer_files: int = 20,
) -> dict[str, list[Path]]:
    packet = _resolve(review_packet_path) or _latest_file(DEFAULT_REVIEW_PACKET_DIR, "unique_review_packets_*.json")
    cases = _latest_files(ai_review_dir, "AI_CASE_REVIEW_CASES_*.json", max_case_reviewer_files)
    return {
        "review_packets": [packet] if packet and packet.exists() else [],
        "case_reviewer_cases": cases,
    }


def build_false_positive_library(
    *,
    review_packet_paths: Sequence[Path] = (),
    case_reviewer_paths: Sequence[Path] = (),
    example_limit_per_pattern: int = 10,
) -> dict[str, Any]:
    pattern_counts: Counter[str] = Counter()
    pattern_sources: dict[str, Counter[str]] = defaultdict(Counter)
    pattern_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    case_reviewer_false_positives: list[dict[str, Any]] = []
    inputs: list[str] = []
    review_packet_count = 0
    case_review_count = 0

    for path in review_packet_paths:
        payload = _load_json(path)
        if not payload:
            continue
        inputs.append(str(path))
        packets = payload.get("packets")
        if not isinstance(packets, list):
            continue
        for packet in packets:
            if not isinstance(packet, Mapping):
                continue
            review_packet_count += 1
            example = _packet_example(packet, str(path))
            for key in _pattern_keys_from_packet(packet):
                pattern_counts[key] += 1
                pattern_sources[key]["unique_review_packet"] += 1
                _add_example(pattern_examples, key, example, example_limit_per_pattern)

    seen_false_positive_cases: set[str] = set()
    for path in case_reviewer_paths:
        payload = _load_json(path)
        if not payload:
            continue
        inputs.append(str(path))
        reviews = _case_reviews_by_id(payload)
        packets = payload.get("case_packets")
        if not isinstance(packets, list):
            continue
        for packet in packets:
            if not isinstance(packet, Mapping):
                continue
            case_id = _string(packet, "case_id")
            review = reviews.get(case_id) or _nested(packet, "deterministic_review")
            if not review:
                continue
            case_review_count += 1
            example = _case_example(packet, review, str(path))
            for key in _pattern_keys_from_case(packet, review):
                pattern_counts[key] += 1
                pattern_sources[key]["case_reviewer"] += 1
                _add_example(pattern_examples, key, example, example_limit_per_pattern)
            if _string(review, "review_verdict") == "likely_false_positive":
                false_positive_id = f"{example.get('wallet')}|{example.get('event')}|{example.get('interpretation_class')}"
                if false_positive_id not in seen_false_positive_cases:
                    seen_false_positive_cases.add(false_positive_id)
                    case_reviewer_false_positives.append(example)

    patterns = []
    for key, count in sorted(pattern_counts.items(), key=lambda item: (-item[1], item[0])):
        definition = PATTERN_DEFINITIONS.get(key, {})
        patterns.append(
            {
                "pattern_key": key,
                "label": definition.get("label", key),
                "observed_count": count,
                "source_counts": dict(pattern_sources[key]),
                "analyst_meaning": definition.get("analyst_meaning", ""),
                "inspect_next": definition.get("inspect_next", ""),
                "safe_use": "Use as analyst caution and packet triage context only.",
                "forbidden_use": "Do not automatically suppress rows, change labels, tune weights, or alter gates from this library.",
                "analyst_playbook": _analyst_playbook(key, definition),
                "examples": pattern_examples.get(key, []),
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "input_paths": inputs,
            "review_packets_read": review_packet_count,
            "case_reviewer_cases_read": case_review_count,
            "pattern_count": len(patterns),
            "case_reviewer_likely_false_positive_examples": len(case_reviewer_false_positives),
            "top_patterns": [
                {"pattern_key": pattern["pattern_key"], "observed_count": pattern["observed_count"]}
                for pattern in patterns[:8]
            ],
        },
        "limitations": [
            "This library is generated from saved local artifacts only.",
            "It is diagnostic and analyst-facing; it does not change model behavior.",
            "Cache-only, stale, duplicate-inflated, or retrospective-only evidence must not be overclaimed.",
            "Repeated false-positive patterns should inform review and RFCs, not enabled production edits.",
        ],
        "patterns": patterns,
        "case_reviewer_false_positive_examples": case_reviewer_false_positives[:50],
        "invariants_preserved": [
            "_score_trade() unchanged",
            "Strong Risk gates unchanged",
            "scoring weights unchanged",
            "production severity labels unchanged",
            "Hard Evidence Review routing unchanged",
            "suspicious funding v2 unchanged",
            "old saved outputs not mutated",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    patterns = payload.get("patterns") if isinstance(payload.get("patterns"), list) else []
    false_positives = (
        payload.get("case_reviewer_false_positive_examples")
        if isinstance(payload.get("case_reviewer_false_positive_examples"), list)
        else []
    )
    lines = [
        "# False-Positive Pattern Library",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Review packets read: {summary.get('review_packets_read', 0)}",
        f"- Case Reviewer cases read: {summary.get('case_reviewer_cases_read', 0)}",
        f"- Pattern count: {summary.get('pattern_count', 0)}",
        f"- Case Reviewer likely false-positive examples: {summary.get('case_reviewer_likely_false_positive_examples', 0)}",
        "",
        "## Safe Use",
        "",
        "- Use this as analyst caution and packet triage context.",
        "- Do not automatically suppress rows from this library.",
        "- Do not change scoring, gates, labels, HER routing, or funding eligibility from this report.",
        "",
        "## Limitations",
    ]
    for limitation in payload.get("limitations") or []:
        lines.append(f"- {limitation}")
    lines.extend(["", "## Top Patterns"])
    if not patterns:
        lines.append("- none")
    for pattern in patterns:
        lines.extend(
            [
                "",
                f"### {pattern.get('label', pattern.get('pattern_key', 'unknown'))}",
                "",
                f"- Key: `{pattern.get('pattern_key', '')}`",
                f"- Observed count: {pattern.get('observed_count', 0)}",
                f"- Source counts: {pattern.get('source_counts', {})}",
                f"- Analyst meaning: {pattern.get('analyst_meaning', '')}",
                f"- Inspect next: {pattern.get('inspect_next', '')}",
                f"- Forbidden use: {pattern.get('forbidden_use', '')}",
                f"- Automatic action allowed: {pattern.get('analyst_playbook', {}).get('automatic_action_allowed', False)}",
                "- Review questions:",
            ]
        )
        playbook = pattern.get("analyst_playbook") if isinstance(pattern.get("analyst_playbook"), Mapping) else {}
        for question in playbook.get("review_questions") or []:
            lines.append(f"  - {question}")
        lines.extend(
            [
                "- Examples:",
            ]
        )
        examples = pattern.get("examples") if isinstance(pattern.get("examples"), list) else []
        if not examples:
            lines.append("  - none")
        for example in examples[:5]:
            wallet = example.get("wallet") or "unknown wallet"
            market_or_event = example.get("market") or example.get("event") or "unknown market/event"
            verdict = example.get("review_verdict") or example.get("group") or ""
            lines.append(f"  - {wallet} | {market_or_event} | {verdict}")
    lines.extend(["", "## Case Reviewer Likely False Positives"])
    if not false_positives:
        lines.append("- none observed in selected inputs")
    for example in false_positives[:25]:
        lines.extend(
            [
                f"- {example.get('username') or example.get('wallet') or 'unknown'}",
                f"  - Wallet: {example.get('wallet', '')}",
                f"  - Event: {example.get('event', '')}",
                f"  - Interpretation: `{example.get('interpretation_class', '')}`",
                f"  - Scores: wallet={example.get('wallet_score', '')}, insider_style={example.get('insider_style_wallet_score', '')}",
                f"  - Counts: event_trades={example.get('event_trade_count', '')}, notable={example.get('notable_trade_count', '')}, winning_opening={example.get('winning_opening_entry_count', '')}",
                f"  - Weakening evidence: {'; '.join(example.get('weakening_evidence') or [])}",
            ]
        )
    lines.extend(["", "## Input Paths"])
    for path in summary.get("input_paths") or []:
        lines.append(f"- {path}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved_output_dir = _resolve(output_dir) or output_dir
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved_output_dir / f"false_positive_pattern_library_{stamp}.json"
    markdown_path = resolved_output_dir / f"false_positive_pattern_library_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a read-only false-positive pattern library from saved outputs.")
    parser.add_argument("--review-packets", type=Path, help="Specific unique review packets JSON to read.")
    parser.add_argument("--ai-review-dir", type=Path, default=DEFAULT_AI_REVIEW_DIR)
    parser.add_argument("--max-case-reviewer-files", type=int, default=20)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    paths = discover_input_paths(
        review_packet_path=args.review_packets,
        ai_review_dir=args.ai_review_dir,
        max_case_reviewer_files=args.max_case_reviewer_files,
    )
    payload = build_false_positive_library(
        review_packet_paths=paths["review_packets"],
        case_reviewer_paths=paths["case_reviewer_cases"],
    )
    outputs = write_outputs(payload, args.output_dir)
    summary = payload.get("summary", {})
    print(f"False-positive pattern library JSON: {outputs['json_path']}")
    print(f"False-positive pattern library markdown: {outputs['markdown_path']}")
    print(f"Pattern count: {summary.get('pattern_count', 0)}")
    print(f"Likely false-positive examples: {summary.get('case_reviewer_likely_false_positive_examples', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
