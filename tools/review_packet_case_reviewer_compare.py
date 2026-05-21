from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW_PACKET_DIR = Path("review_packets")
DEFAULT_CASE_REVIEWER_DIR = Path("ai_review_outputs")
DEFAULT_OUTPUT_DIR = Path("review_packet_compare_outputs")


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


def _lower_wallet(value: Any) -> str:
    text = _string(value).lower()
    return text if text.startswith("0x") else ""


def _case_reviewer_cases(case_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    packets = case_payload.get("case_packets")
    reviews = case_payload.get("reviews")
    if not isinstance(packets, list):
        packets = []
    if not isinstance(reviews, list):
        reviews = []
    review_by_case_id = {
        _string(review.get("case_id")): dict(review)
        for review in reviews
        if isinstance(review, Mapping) and _string(review.get("case_id"))
    }
    cases: list[dict[str, Any]] = []
    for packet in packets:
        if not isinstance(packet, Mapping):
            continue
        case_id = _string(packet.get("case_id"))
        review = review_by_case_id.get(case_id, {})
        cases.append(
            {
                "case_id": case_id,
                "case_type": _string(packet.get("case_type")),
                "wallet": _lower_wallet(packet.get("wallet")),
                "username": _string(packet.get("username")),
                "event": _string(packet.get("event")),
                "review_verdict": _string(review.get("review_verdict")),
                "interpretation_class": _string(review.get("interpretation_class")),
                "confidence": review.get("confidence"),
                "main_reason": _string(review.get("main_reason")),
            }
        )
    return cases


def _is_false_positive_case(case: Mapping[str, Any]) -> bool:
    verdict = _string(case.get("review_verdict")).lower()
    interpretation = _string(case.get("interpretation_class")).lower()
    return verdict == "likely_false_positive" or interpretation == "high_volume_public_power_user"


def _is_plausible_case(case: Mapping[str, Any]) -> bool:
    verdict = _string(case.get("review_verdict")).lower()
    interpretation = _string(case.get("interpretation_class")).lower()
    return verdict == "plausible_insider_style" or interpretation == "insider_style_candidate"


def compare_packets_to_case_reviewer(
    review_packet_payload: Mapping[str, Any],
    case_reviewer_payload: Mapping[str, Any],
    *,
    review_packet_path: Path | None = None,
    case_reviewer_path: Path | None = None,
) -> dict[str, Any]:
    packets = review_packet_payload.get("packets")
    if not isinstance(packets, list):
        packets = []
    cases = _case_reviewer_cases(case_reviewer_payload)
    cases_by_wallet: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        wallet = _lower_wallet(case.get("wallet"))
        if wallet:
            cases_by_wallet.setdefault(wallet, []).append(case)

    matches: list[dict[str, Any]] = []
    unmatched_packets: list[dict[str, Any]] = []
    fp_packet_ids: set[str] = set()
    plausible_packet_ids: set[str] = set()
    for packet in packets:
        if not isinstance(packet, Mapping):
            continue
        wallet = _lower_wallet(packet.get("wallet"))
        packet_id = _string(packet.get("packet_id"))
        matching_cases = cases_by_wallet.get(wallet, [])
        if not matching_cases:
            unmatched_packets.append(
                {
                    "packet_id": packet_id,
                    "wallet": wallet,
                    "group": _string(packet.get("group")),
                    "market": _string(packet.get("market")),
                    "reason": "No wallet match in latest Case Reviewer cases.",
                }
            )
            continue
        for case in matching_cases:
            if _is_false_positive_case(case):
                fp_packet_ids.add(packet_id)
            if _is_plausible_case(case):
                plausible_packet_ids.add(packet_id)
            matches.append(
                {
                    "packet_id": packet_id,
                    "wallet": wallet,
                    "packet_group": _string(packet.get("group")),
                    "packet_market": _string(packet.get("market")),
                    "case_id": case.get("case_id"),
                    "case_type": case.get("case_type"),
                    "case_event": case.get("event"),
                    "username": case.get("username"),
                    "review_verdict": case.get("review_verdict"),
                    "interpretation_class": case.get("interpretation_class"),
                    "confidence": case.get("confidence"),
                    "main_reason": case.get("main_reason"),
                }
            )

    false_positive_cases = [case for case in cases if _is_false_positive_case(case)]
    plausible_cases = [case for case in cases if _is_plausible_case(case)]
    missing_inputs = []
    if not review_packet_payload:
        missing_inputs.append("review_packets")
    if not case_reviewer_payload:
        missing_inputs.append("case_reviewer_cases")

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "review_packet_path": str(review_packet_path) if review_packet_path else "",
        "case_reviewer_path": str(case_reviewer_path) if case_reviewer_path else "",
        "packet_count": len([packet for packet in packets if isinstance(packet, Mapping)]),
        "case_reviewer_case_count": len(cases),
        "case_reviewer_false_positive_count": len(false_positive_cases),
        "case_reviewer_plausible_count": len(plausible_cases),
        "matched_wallet_count": len({match["wallet"] for match in matches if match.get("wallet")}),
        "match_count": len(matches),
        "packets_matching_case_reviewer_false_positive": len(fp_packet_ids),
        "packets_matching_case_reviewer_plausible": len(plausible_packet_ids),
        "packets_without_case_reviewer_match": len(unmatched_packets),
        "missing_inputs": missing_inputs,
        "limitations": [
            "Comparison is wallet-based and uses saved local outputs only.",
            "A missing match does not prove a packet is better or worse; the latest Case Reviewer may cover a different event.",
            "This report does not change scoring, gates, labels, HER routing, or funding eligibility.",
        ],
    }
    return {
        "summary": summary,
        "matches": matches,
        "unmatched_packets_sample": unmatched_packets[:50],
        "case_reviewer_false_positive_examples": false_positive_cases[:50],
        "case_reviewer_plausible_examples": plausible_cases[:50],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Review Packet vs Case Reviewer Comparison",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Review packet path: {summary.get('review_packet_path', '') or 'missing'}",
        f"- Case Reviewer path: {summary.get('case_reviewer_path', '') or 'missing'}",
        f"- Review packets: {summary.get('packet_count', 0)}",
        f"- Case Reviewer cases: {summary.get('case_reviewer_case_count', 0)}",
        f"- Case Reviewer likely false positives: {summary.get('case_reviewer_false_positive_count', 0)}",
        f"- Case Reviewer plausible insider-style cases: {summary.get('case_reviewer_plausible_count', 0)}",
        f"- Wallet matches: {summary.get('matched_wallet_count', 0)}",
        f"- Packets matching Case Reviewer false positives: {summary.get('packets_matching_case_reviewer_false_positive', 0)}",
        f"- Packets matching Case Reviewer plausible cases: {summary.get('packets_matching_case_reviewer_plausible', 0)}",
        f"- Packets without Case Reviewer wallet match: {summary.get('packets_without_case_reviewer_match', 0)}",
        "",
        "## Limitations",
    ]
    for item in summary.get("limitations") or []:
        lines.append(f"- {item}")
    if summary.get("missing_inputs"):
        lines.extend(["", "## Missing Inputs"])
        for item in summary.get("missing_inputs") or []:
            lines.append(f"- {item}")
    lines.extend(["", "## Matches"])
    matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
    if not matches:
        lines.append("- none")
    for match in matches[:50]:
        lines.append(
            f"- `{match.get('packet_id')}` wallet `{match.get('wallet')}` -> "
            f"`{match.get('review_verdict') or 'unknown'}` / `{match.get('interpretation_class') or 'unknown'}` "
            f"({match.get('case_event') or 'unknown event'})"
        )
    lines.extend(["", "## Case Reviewer False-Positive Examples"])
    examples = payload.get("case_reviewer_false_positive_examples") if isinstance(payload.get("case_reviewer_false_positive_examples"), list) else []
    if not examples:
        lines.append("- none")
    for case in examples[:25]:
        lines.append(
            f"- `{case.get('wallet')}` {case.get('username') or ''}: "
            f"{case.get('review_verdict') or 'unknown'} / {case.get('interpretation_class') or 'unknown'}"
        )
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved_output_dir = _resolve(output_dir) or output_dir
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved_output_dir / f"review_packet_case_reviewer_compare_{stamp}.json"
    markdown_path = resolved_output_dir / f"review_packet_case_reviewer_compare_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare unique review packets against deterministic Case Reviewer verdicts.")
    parser.add_argument("--review-packets", type=Path)
    parser.add_argument("--case-reviewer-cases", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    review_packet_path = _resolve(args.review_packets) if args.review_packets else _latest_file(DEFAULT_REVIEW_PACKET_DIR, "unique_review_packets_*.json")
    case_reviewer_path = (
        _resolve(args.case_reviewer_cases)
        if args.case_reviewer_cases
        else _latest_file(DEFAULT_CASE_REVIEWER_DIR, "AI_CASE_REVIEW_CASES_*.json")
    )
    payload = compare_packets_to_case_reviewer(
        _load_json(review_packet_path),
        _load_json(case_reviewer_path),
        review_packet_path=review_packet_path,
        case_reviewer_path=case_reviewer_path,
    )
    outputs = write_outputs(payload, args.output_dir)
    summary = payload.get("summary", {})
    print(f"Review packet comparison JSON: {outputs['json_path']}")
    print(f"Review packet comparison markdown: {outputs['markdown_path']}")
    print(f"Review packets: {summary.get('packet_count', 0)}")
    print(f"Case Reviewer cases: {summary.get('case_reviewer_case_count', 0)}")
    print(f"Wallet matches: {summary.get('matched_wallet_count', 0)}")
    print(f"Packets matching Case Reviewer false positives: {summary.get('packets_matching_case_reviewer_false_positive', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
