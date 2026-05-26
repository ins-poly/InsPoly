#!/usr/bin/env python3
"""Curate a small stable Side/Outcome known-case benchmark corpus.

The corpus is sidecar-only. It reads local audit/replay outputs and falls back
to explicitly synthetic fixtures when a stable local artifact is not available.
It never reads live APIs or mutates source artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.side_outcome import UNKNOWN, normalize_cluster_direction, normalize_side_outcome


REPORT_TYPE = "post_side_outcome_known_case_benchmark_corpus"
SCHEMA_VERSION = "known_case_benchmark_v2"
DEFAULT_OUTPUT = Path("tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json")

ALLOWED_SOURCE_TYPES = {
    "false_positive_library",
    "generated_audit_evidence",
    "review_packet",
    "real_local_artifact",
    "sidecar_measurement",
    "synthetic_fixture",
}

REQUIRED_CATEGORIES = (
    "buy_yes_unaffected",
    "buy_no_unaffected",
    "sell_yes_low_price_economic_no_high_probability",
    "sell_no_low_price_economic_yes_high_probability",
    "sell_yes_near_certainty_inversion",
    "sell_no_near_certainty_inversion",
    "buy_yes_sell_no_same_cluster_long_yes",
    "buy_no_sell_yes_same_cluster_long_no",
    "malformed_missing_fallback",
    "old_report_without_phase2_phase4_fields",
    "sensitive_gate_overlap_no_direct_mutation",
    "phase3_capital_at_risk_blocked_overlap",
    "event_forensic_later_correctness_affected",
    "archive_affected_case",
    "scanner_affected_case",
    "stable_unaffected_control",
    "true_low_probability_later_winner",
    "weak_history_near_certainty_demotion",
    "selected_market_vs_whole_event_scope_boundary",
    "pagination_truncation_warning_control",
    "false_positive_near_certainty_control",
    "high_volume_public_user_false_positive_control",
    "funding_unknown_control",
    "no_independent_hard_evidence_control",
)

REQUIRED_CASE_FIELDS = (
    "case_id",
    "source_type",
    "source_path",
    "mode",
    "wallet",
    "market",
    "event",
    "trade_key",
    "raw_side",
    "raw_outcome",
    "raw_token_price",
    "economic_side",
    "model_probability",
    "cluster_direction",
    "expected_phase2_effect",
    "expected_phase4_effect",
    "phase3_capital_status",
    "sensitive_context",
    "expected_result",
    "assertion_type",
    "expected_behavior",
    "forbidden_interpretation",
    "false_positive_notes",
    "source_note",
    "notes",
    "provenance_quality",
)


def curate_known_case_benchmark(root: str | Path = ".") -> dict[str, object]:
    base = Path(root)
    sources = _load_sources(base)
    cases = _build_cases(sources)
    counts = Counter(str(case["source_type"]) for case in cases)
    category_counts = Counter(str(case["category"]) for case in cases)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeBehaviorChanged": False,
        "sourceInventory": _source_inventory(sources),
        "summary": {
            "caseCount": len(cases),
            "requiredCategoryCount": len(REQUIRED_CATEGORIES),
            "coveredRequiredCategories": sorted(category_counts),
            "missingRequiredCategories": sorted(set(REQUIRED_CATEGORIES) - set(category_counts)),
            "sourceTypeCounts": dict(sorted(counts.items())),
            "syntheticCaseCount": counts.get("synthetic_fixture", 0),
            "realLocalCaseCount": counts.get("real_local_artifact", 0),
            "generatedAuditEvidenceCaseCount": counts.get("generated_audit_evidence", 0),
            "reviewPacketCaseCount": counts.get("review_packet", 0),
        },
        "cases": cases,
    }


def validate_known_case_corpus(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return ["corpus cases must be a list"]
    categories: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            errors.append(f"case {index} must be an object")
            continue
        missing = [field for field in REQUIRED_CASE_FIELDS if field not in case]
        if missing:
            errors.append(f"{case.get('case_id', index)} missing fields: {', '.join(missing)}")
        source_type = str(case.get("source_type") or "")
        if source_type not in ALLOWED_SOURCE_TYPES:
            errors.append(f"{case.get('case_id', index)} unsupported source_type: {source_type}")
        category = str(case.get("category") or "")
        if category:
            categories.add(category)
        if case.get("source_type") == "synthetic_fixture" and "synthetic" not in str(case.get("provenance_quality", "")):
            errors.append(f"{case.get('case_id', index)} synthetic case must be explicitly marked synthetic")
        expected = case.get("expected_result")
        if not isinstance(expected, Mapping):
            errors.append(f"{case.get('case_id', index)} expected_result must be an object")
        if _is_advisory_control(case):
            if not str(case.get("forbidden_interpretation") or "").strip():
                errors.append(f"{case.get('case_id', index)} advisory control must include forbidden_interpretation")
            if not isinstance(case.get("false_positive_notes"), list):
                errors.append(f"{case.get('case_id', index)} advisory control false_positive_notes must be a list")
            if isinstance(expected, Mapping):
                if expected.get("automatic_action_allowed") is not False:
                    errors.append(f"{case.get('case_id', index)} advisory control must forbid automatic action")
                if expected.get("safe_to_use_for_scoring_claims") is not False:
                    errors.append(f"{case.get('case_id', index)} advisory control must not be scoring evidence")
    missing_categories = sorted(set(REQUIRED_CATEGORIES) - categories)
    if missing_categories:
        errors.append("missing required categories: " + ", ".join(missing_categories))
    case_ids = [str(case.get("case_id") or "") for case in cases if isinstance(case, Mapping)]
    duplicate_ids = sorted(case_id for case_id, count in Counter(case_ids).items() if count > 1)
    if duplicate_ids:
        errors.append("duplicate case ids: " + ", ".join(duplicate_ids))
    return errors


def write_json(path: str | Path, payload: Mapping[str, object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    corpus = curate_known_case_benchmark(args.root)
    errors = validate_known_case_corpus(corpus)
    if errors:
        for error in errors:
            print(f"schema error: {error}", file=sys.stderr)
        return 1
    if not args.dry_run:
        write_json(args.output, corpus)
    if not args.quiet:
        summary = corpus["summary"]
        print(f"cases: {summary['caseCount']}")
        print(f"synthetic: {summary['syntheticCaseCount']}")
        print(f"output: {'dry-run' if args.dry_run else args.output}")
    return 0


def _load_sources(base: Path) -> dict[str, object]:
    return {
        "replay": _read_json(base / "validation_outputs/post_side_outcome_benchmark_replay_20260522.json"),
        "phase2_sensitive": _read_json(base / "side_outcome_review_packets/phase2_post_migration_sensitive_cases_20260522/sensitive_cases.json"),
        "phase4_sensitive_merge": _read_json(base / "side_outcome_review_packets/phase4_post_migration_sensitive_merge_groups_20260522/sensitive_merge_groups.json"),
        "archive_evidence": _read_json(base / "side_outcome_audits/side_outcome_phase2_archive_evidence_gap_20260522.json"),
        "phase2_readiness": _read_json(base / "side_outcome_audits/side_outcome_phase2_readiness_impact_audit_20260522.json"),
        "phase3_audit": _read_json(base / "side_outcome_audits/side_outcome_phase3_capital_at_risk_audit_20260522.json"),
        "false_positive_patterns": _read_json(base / "false_positive_library/false_positive_pattern_library_20260505_151140.json"),
        "latest_review_packets": _read_json(base / "review_packets/unique_review_packets_20260505_163257.json"),
        "weak_history_policy": _read_json(base / "validation_outputs/event_forensic_weak_history_policy_evidence_20260524.json"),
        "scope_semantics": _read_json(base / "validation_outputs/event_forensic_scope_semantics_audit_20260525.json"),
        "pagination_impact": _read_json(base / "validation_outputs/event_forensic_pagination_impact_assessment_20260526.json"),
        "phase3_final": _read_json(base / "validation_outputs/phase3_capital_final_evidence_review_20260526.json"),
    }


def _build_cases(sources: Mapping[str, object]) -> list[dict[str, object]]:
    phase2_sensitive = _as_list(sources.get("phase2_sensitive"))
    phase4_groups = _as_list(sources.get("phase4_sensitive_merge"))
    archive_evidence = _as_mapping(sources.get("archive_evidence"))
    phase2_readiness = _as_mapping(sources.get("phase2_readiness"))
    phase3_audit = _as_mapping(sources.get("phase3_audit"))
    false_positive_patterns = _as_mapping(sources.get("false_positive_patterns"))
    weak_history_policy = _as_mapping(sources.get("weak_history_policy"))
    scope_semantics = _as_mapping(sources.get("scope_semantics"))
    pagination_impact = _as_mapping(sources.get("pagination_impact"))
    replay_rows = _as_list(_as_mapping(sources.get("replay")).get("representativeRows"))

    cases = [
        _synthetic_case("buy_yes_unaffected", "scanner", "BUY", "YES", "0.20", "unaffected", "unchanged_long_yes", "Stable BUY YES control."),
        _synthetic_case("buy_no_unaffected", "scanner", "BUY", "NO", "0.20", "unaffected", "unchanged_long_no", "Stable BUY NO control."),
        _synthetic_case(
            "sell_yes_low_price_economic_no_high_probability",
            "scanner",
            "SELL",
            "YES",
            "0.20",
            "low_probability_inverted_to_high_probability",
            "direction_changed_to_long_no",
            "SELL YES low raw token price becomes economic NO high probability.",
        ),
        _synthetic_case(
            "sell_no_low_price_economic_yes_high_probability",
            "scanner",
            "SELL",
            "NO",
            "0.20",
            "low_probability_inverted_to_high_probability",
            "direction_changed_to_long_yes",
            "SELL NO low raw token price becomes economic YES high probability.",
        ),
        _case_from_record(
            "sell_yes_near_certainty_inversion",
            _first(
                replay_rows,
                lambda row: row.get("rawOrderSide") == "SELL"
                and row.get("rawTokenOutcome") == "YES"
                and Decimal(str(row.get("rawTokenPrice", "0"))) >= Decimal("0.95"),
            )
            or _first(_as_list(phase2_readiness.get("affectedExamples")), lambda row: row.get("rawOrderSide") == "SELL" and row.get("rawTokenOutcome") == "YES")
            or {},
            source_type="real_local_artifact",
            source_path="validation_outputs/post_side_outcome_benchmark_replay_20260522.json",
            mode="scanner",
            expected_phase2_effect="near_certainty_inverted",
            expected_phase4_effect="direction_changed_to_long_no",
            phase3_status="blocked_overlap",
            notes="Representative real local SELL YES near-certainty inversion if present; synthetic fallback is avoided unless no record exists.",
        ),
        _case_from_record(
            "sell_no_near_certainty_inversion",
            _first(
                replay_rows,
                lambda row: row.get("rawOrderSide") == "SELL"
                and row.get("rawTokenOutcome") == "NO"
                and Decimal(str(row.get("rawTokenPrice", "0"))) >= Decimal("0.95"),
            )
            or _first(_as_list(phase2_readiness.get("affectedExamples")), lambda row: row.get("rawOrderSide") == "SELL" and row.get("rawTokenOutcome") == "NO")
            or {},
            source_type="real_local_artifact",
            source_path="validation_outputs/post_side_outcome_benchmark_replay_20260522.json",
            mode="scanner",
            expected_phase2_effect="near_certainty_inverted",
            expected_phase4_effect="direction_changed_to_long_yes",
            phase3_status="blocked_overlap",
            notes="Representative real local SELL NO near-certainty inversion.",
        ),
        _cluster_pair_case(
            "buy_yes_sell_no_same_cluster_long_yes",
            "BUY",
            "YES",
            "SELL",
            "NO",
            "long_yes",
            _first(phase4_groups, lambda group: "BUY YES" in _as_list(group.get("rawActions")) and "SELL NO" in _as_list(group.get("rawActions"))),
        ),
        _cluster_pair_case(
            "buy_no_sell_yes_same_cluster_long_no",
            "BUY",
            "NO",
            "SELL",
            "YES",
            "long_no",
            _first(phase4_groups, lambda group: "BUY NO" in _as_list(group.get("rawActions")) and "SELL YES" in _as_list(group.get("rawActions"))),
        ),
        _malformed_case(),
        _old_report_case(),
        _case_from_record(
            "sensitive_gate_overlap_no_direct_mutation",
            _first(phase2_sensitive, lambda row: row.get("expectedByRfc") is True) or {},
            source_type="review_packet",
            source_path="side_outcome_review_packets/phase2_post_migration_sensitive_cases_20260522/sensitive_cases.json",
            mode="event_forensic",
            expected_phase2_effect="expected_indirect_sensitive_overlap",
            expected_phase4_effect="unchanged_or_context_only",
            phase3_status="blocked_if_sell_opening_overlap",
            sensitive_context=True,
            notes="Sensitive overlap is evidence for review only; direct gate mutation remains forbidden.",
        ),
        _case_from_record(
            "phase3_capital_at_risk_blocked_overlap",
            _first(_as_list(phase3_audit.get("affectedExamples")), lambda row: row.get("capitalDelta") not in (None, "", "0", "0.00")) or {},
            source_type="generated_audit_evidence",
            source_path="side_outcome_audits/side_outcome_phase3_capital_at_risk_audit_20260522.json",
            mode="scanner",
            expected_phase2_effect="phase2_context_available",
            expected_phase4_effect="phase4_context_available",
            phase3_status="blocked_overlap",
            notes="Capital-at-risk delta is evidence only; runtime Phase 3 remains blocked.",
        ),
        _case_from_record(
            "event_forensic_later_correctness_affected",
            _first(phase2_sensitive, lambda row: "laterCorrectnessChanged" in _as_list(row.get("affectedSurfaces"))) or {},
            source_type="review_packet",
            source_path="side_outcome_review_packets/phase2_post_migration_sensitive_cases_20260522/sensitive_cases.json",
            mode="event_forensic",
            expected_phase2_effect="later_correctness_inverted",
            expected_phase4_effect="direction_changed_if_sell",
            phase3_status="blocked_if_sell_opening_overlap",
            notes="Event Forensic later-correctness affected row from local review packet.",
        ),
        _case_from_record(
            "archive_affected_case",
            _first(_as_list(archive_evidence.get("affectedExamples")), lambda row: row.get("artifactEvidenceType") == "real_local") or {},
            source_type="generated_audit_evidence",
            source_path="side_outcome_audits/side_outcome_phase2_archive_evidence_gap_20260522.json",
            mode="archive",
            expected_phase2_effect="archive_probability_direction_changed",
            expected_phase4_effect="direction_changed_if_sell",
            phase3_status="blocked_if_sell_opening_overlap",
            notes="Archive evidence-gap audit row derived from a real local archive artifact.",
        ),
        _case_from_record(
            "scanner_affected_case",
            _first(_as_list(phase2_readiness.get("affectedExamples")), lambda row: row.get("artifactFamily") == "scanner_report_json") or {},
            source_type="generated_audit_evidence",
            source_path="side_outcome_audits/side_outcome_phase2_readiness_impact_audit_20260522.json",
            mode="scanner",
            expected_phase2_effect="scanner_probability_direction_changed",
            expected_phase4_effect="direction_changed_if_sell",
            phase3_status="blocked_if_sell_opening_overlap",
            notes="Scanner affected row from the Phase 2 readiness audit.",
        ),
        _synthetic_case(
            "stable_unaffected_control",
            "event_forensic",
            "BUY",
            "YES",
            "0.62",
            "unaffected",
            "unchanged_long_yes",
            "Stable medium-probability control; no low/near threshold inversion expected.",
        ),
        _sidecar_pattern_case(
            "true_low_probability_later_winner",
            source_type="sidecar_measurement",
            source_path="validation_outputs/event_forensic_weak_history_policy_evidence_20260524.json",
            source_payload=weak_history_policy,
            mode="event_forensic",
            raw_side="BUY",
            raw_outcome="YES",
            raw_price="0.04",
            expected_phase2_effect="low_probability_later_winner_context_only",
            expected_phase4_effect="unchanged_long_yes",
            expected_behavior="Pattern-level low-probability later-winner evidence remains benchmark context only.",
            forbidden_interpretation="Do not treat this sidecar measurement as exact-wallet proof, scoring-tuning approval, or automatic Strong Risk evidence.",
            notes="Saved weak-history evidence records low-probability/later-winner policy rows, but this compact case is pattern-level only.",
        ),
        _sidecar_pattern_case(
            "weak_history_near_certainty_demotion",
            source_type="sidecar_measurement",
            source_path="validation_outputs/event_forensic_weak_history_policy_evidence_20260524.json",
            source_payload=weak_history_policy,
            mode="event_forensic",
            raw_side="BUY",
            raw_outcome="YES",
            raw_price="0.99",
            expected_phase2_effect="near_certainty_context_only",
            expected_phase4_effect="unchanged_long_yes",
            expected_behavior="Weak-history near-certainty later-win rows remain exported but should be demotion-aware review context.",
            forbidden_interpretation="Do not promote weak-history near-certainty rows to primary review solely because they later won.",
            notes="Regression control for the weak-history near-certainty demotion workstream.",
        ),
        _sidecar_pattern_case(
            "selected_market_vs_whole_event_scope_boundary",
            source_type="generated_audit_evidence",
            source_path="validation_outputs/event_forensic_scope_semantics_audit_20260525.json",
            source_payload=scope_semantics,
            mode="event_forensic",
            raw_side="BUY",
            raw_outcome="YES",
            raw_price="0.55",
            expected_phase2_effect="scope_metadata_context_only",
            expected_phase4_effect="unchanged_long_yes",
            expected_behavior="Selected-market reports must not silently broaden primary scoring to sibling markets.",
            forbidden_interpretation="Do not use context-only sibling markets as primary selected-market candidates without whole-event mode.",
            notes="Scope audit found selected-market and whole-event semantics must remain explicit.",
        ),
        _sidecar_pattern_case(
            "pagination_truncation_warning_control",
            source_type="generated_audit_evidence",
            source_path="validation_outputs/event_forensic_pagination_impact_assessment_20260526.json",
            source_payload=pagination_impact,
            mode="event_forensic",
            raw_side="BUY",
            raw_outcome="YES",
            raw_price="0.50",
            expected_phase2_effect="pagination_warning_context_only",
            expected_phase4_effect="unchanged_long_yes",
            expected_behavior="Truncation markers stay analyst warnings and do not justify production pagination expansion.",
            forbidden_interpretation="Do not infer completeness, rescore, or broaden pagination from this control case.",
            notes="Pagination impact assessment found low impact for the bounded subset but continued monitor-only truncation markers.",
        ),
        _false_positive_control_case(
            "false_positive_near_certainty_control",
            pattern_key="near_certainty",
            raw_price="0.99",
            patterns_payload=false_positive_patterns,
        ),
        _false_positive_control_case(
            "high_volume_public_user_false_positive_control",
            pattern_key="high_volume_public_user",
            raw_price="0.72",
            patterns_payload=false_positive_patterns,
        ),
        _false_positive_control_case(
            "funding_unknown_control",
            pattern_key="funding_unknown",
            raw_price="0.55",
            patterns_payload=false_positive_patterns,
        ),
        _false_positive_control_case(
            "no_independent_hard_evidence_control",
            pattern_key="no_independent_hard_evidence",
            raw_price="0.64",
            patterns_payload=false_positive_patterns,
        ),
    ]
    return [_ensure_case(case) for case in cases]


def _synthetic_case(
    category: str,
    mode: str,
    raw_side: str,
    raw_outcome: str,
    raw_price: str,
    expected_phase2_effect: str,
    expected_phase4_effect: str,
    notes: str,
) -> dict[str, object]:
    return _make_case(
        case_id=f"known-{category}",
        category=category,
        source_type="synthetic_fixture",
        source_path="tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json",
        mode=mode,
        wallet=f"0x{category[:20].replace('_', '')}",
        market=f"synthetic-{category}",
        event="synthetic-known-case-event",
        trade_key=f"synthetic|{category}|{raw_side}|{raw_outcome}|{raw_price}",
        raw_side=raw_side,
        raw_outcome=raw_outcome,
        raw_price=raw_price,
        expected_phase2_effect=expected_phase2_effect,
        expected_phase4_effect=expected_phase4_effect,
        phase3_status="not_applicable",
        sensitive_context=False,
        notes=notes,
        provenance_quality="synthetic_contract_fixture",
    )


def _cluster_pair_case(
    category: str,
    side_a: str,
    outcome_a: str,
    side_b: str,
    outcome_b: str,
    expected_cluster: str,
    source_group: object,
) -> dict[str, object]:
    group = _as_mapping(source_group)
    rows = _as_list(group.get("rows"))
    source_type = "review_packet" if rows else "synthetic_fixture"
    source_path = "side_outcome_review_packets/phase4_post_migration_sensitive_merge_groups_20260522/sensitive_merge_groups.json" if rows else "tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json"
    case = _make_case(
        case_id=f"known-{category}",
        category=category,
        source_type=source_type,
        source_path=source_path,
        mode="scanner",
        wallet=str(_first_text(group.get("wallet"), "0xcluster")),
        market=str(_first_text(group.get("marketSlug"), f"synthetic-{category}")),
        event=str(_first_text(group.get("eventSlug"), "synthetic-known-case-event")),
        trade_key=str(_first_text(group.get("normalizedGroupKey"), f"synthetic|{category}")),
        raw_side=side_a,
        raw_outcome=outcome_a,
        raw_price="0.20",
        expected_phase2_effect="cluster_pair_context",
        expected_phase4_effect=f"same_cluster_{expected_cluster}",
        phase3_status="not_applicable",
        sensitive_context=bool(group.get("expectedByRfc")) if group else False,
        notes=f"{side_a} {outcome_a} and {side_b} {outcome_b} should share normalized cluster {expected_cluster}.",
        provenance_quality="review_packet_derived_from_real_local_artifacts" if rows else "synthetic_contract_fixture",
    )
    case["case_trades"] = [
        {"raw_side": side_a, "raw_outcome": outcome_a, "raw_token_price": "0.20", "expected_cluster_direction": expected_cluster},
        {"raw_side": side_b, "raw_outcome": outcome_b, "raw_token_price": "0.20", "expected_cluster_direction": expected_cluster},
    ]
    return case


def _malformed_case() -> dict[str, object]:
    return _make_case(
        case_id="known-malformed_missing_fallback",
        category="malformed_missing_fallback",
        source_type="synthetic_fixture",
        source_path="tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json",
        mode="scanner",
        wallet="0xmalformed",
        market="synthetic-malformed",
        event="synthetic-known-case-event",
        trade_key="synthetic|malformed",
        raw_side="",
        raw_outcome="MAYBE",
        raw_price="bad",
        expected_phase2_effect="unknown_not_guessed",
        expected_phase4_effect="unknown_not_grouped",
        phase3_status="not_applicable",
        sensitive_context=False,
        notes="Malformed row must stay unknown, not zero or clean.",
        provenance_quality="synthetic_contract_fixture",
    )


def _old_report_case() -> dict[str, object]:
    case = _make_case(
        case_id="known-old_report_without_phase2_phase4_fields",
        category="old_report_without_phase2_phase4_fields",
        source_type="synthetic_fixture",
        source_path="tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json",
        mode="scanner",
        wallet="0xoldreport",
        market="synthetic-old-report",
        event="synthetic-known-case-event",
        trade_key="synthetic|old-report|SELL|YES|20pct",
        raw_side="SELL",
        raw_outcome="YES",
        raw_price="20.0%",
        expected_phase2_effect="derivable_from_old_raw_fields",
        expected_phase4_effect="derivable_from_old_raw_fields",
        phase3_status="not_applicable",
        sensitive_context=False,
        notes="Old report shape has no Phase 2/4 additive fields; safe derivation uses raw side/outcome/price only.",
        provenance_quality="synthetic_old_report_contract_fixture",
    )
    case["legacy_fields_present"] = {"price_implied_probability": "20.0%", "economic_direction": "short_yes"}
    return case


def _sidecar_pattern_case(
    category: str,
    *,
    source_type: str,
    source_path: str,
    source_payload: Mapping[str, object],
    mode: str,
    raw_side: str,
    raw_outcome: str,
    raw_price: str,
    expected_phase2_effect: str,
    expected_phase4_effect: str,
    expected_behavior: str,
    forbidden_interpretation: str,
    notes: str,
) -> dict[str, object]:
    summary = _as_mapping(source_payload.get("summary"))
    gate = _first_text(source_payload.get("gateDecision"), summary.get("gateDecision"), "available")
    source_note = f"sidecar source gate={gate}; summary_keys={','.join(sorted(str(key) for key in summary.keys())[:6])}"
    case = _make_case(
        case_id=f"known-{category}",
        category=category,
        source_type=source_type,
        source_path=source_path,
        mode=mode,
        wallet="pattern-level",
        market=str(_first_text(summary.get("targetMarket"), summary.get("selectedMarket"), "pattern-level")),
        event=str(_first_text(summary.get("targetEvent"), summary.get("selectedEvent"), "pattern-level")),
        trade_key=f"pattern|{category}|{raw_side}|{raw_outcome}|{raw_price}",
        raw_side=raw_side,
        raw_outcome=raw_outcome,
        raw_price=raw_price,
        expected_phase2_effect=expected_phase2_effect,
        expected_phase4_effect=expected_phase4_effect,
        phase3_status="not_applicable",
        sensitive_context=category in {"true_low_probability_later_winner", "weak_history_near_certainty_demotion"},
        notes=notes,
        provenance_quality=f"{source_type}_compact_pattern_control",
        assertion_type="sidecar_context_control",
        expected_behavior=expected_behavior,
        forbidden_interpretation=forbidden_interpretation,
        false_positive_notes=[],
        source_note=source_note,
    )
    case["expected_result"].update(
        {
            "automatic_action_allowed": False,
            "safe_to_use_for_scoring_claims": False,
            "requires_fresh_validation_for_model_use": True,
        }
    )
    return case


def _false_positive_control_case(
    category: str,
    *,
    pattern_key: str,
    raw_price: str,
    patterns_payload: Mapping[str, object],
) -> dict[str, object]:
    pattern = _pattern_by_key(patterns_payload, pattern_key)
    example = _first_example(pattern)
    label = _first_text(pattern.get("label"), pattern_key.replace("_", " ").title())
    forbidden = _first_text(
        pattern.get("forbidden_use"),
        "Do not automatically suppress, downgrade, rescore, reroute, or change gates from this advisory control.",
    )
    false_positive_notes = [
        _first_text(pattern.get("analyst_meaning"), ""),
        _first_text(pattern.get("safe_use"), ""),
        *_as_text_list(example.get("why_false_positive")),
    ]
    source_note = (
        f"false_positive_pattern={pattern_key}; "
        f"observed_count={_first_text(pattern.get('observed_count'), 'unknown')}; "
        f"source_count_keys={','.join(sorted(str(key) for key in _as_mapping(pattern.get('source_counts')).keys()))}"
    )
    case = _make_case(
        case_id=f"known-{category}",
        category=category,
        source_type="false_positive_library",
        source_path="false_positive_library/false_positive_pattern_library_20260505_151140.json",
        mode="event_forensic",
        wallet=_first_text(example.get("wallet"), "pattern-level"),
        market=_first_text(example.get("market"), pattern_key),
        event=_first_text(example.get("event"), "pattern-level"),
        trade_key=_first_text(example.get("packet_id"), example.get("case_id"), f"pattern|{pattern_key}"),
        raw_side="BUY",
        raw_outcome="YES",
        raw_price=raw_price,
        expected_phase2_effect=f"{pattern_key}_advisory_only",
        expected_phase4_effect="unchanged_long_yes",
        phase3_status="not_applicable",
        sensitive_context=pattern_key in {"funding_unknown", "no_independent_hard_evidence"},
        notes=f"{label}: advisory false-positive control derived from local false-positive library.",
        provenance_quality="false_positive_library_advisory_control_from_local_artifacts",
        assertion_type="false_positive_control",
        expected_behavior="Use only as analyst caution and benchmark guardrail; never as automatic model behavior.",
        forbidden_interpretation=forbidden,
        false_positive_notes=[note for note in false_positive_notes if note],
        source_note=source_note,
    )
    case["expected_result"].update(
        {
            "automatic_action_allowed": False,
            "false_positive_control": True,
            "requires_fresh_validation_for_model_use": True,
            "safe_to_use_for_scoring_claims": False,
        }
    )
    return case


def _case_from_record(
    case_slug: str,
    record: Mapping[str, object],
    *,
    source_type: str,
    source_path: str,
    mode: str,
    expected_phase2_effect: str,
    expected_phase4_effect: str,
    phase3_status: str,
    notes: str,
    sensitive_context: bool | None = None,
) -> dict[str, object]:
    if not record:
        return _synthetic_case(case_slug, mode, "SELL", "YES", "0.98", expected_phase2_effect, expected_phase4_effect, notes)
    raw_side = _first_text(record.get("rawOrderSide"), record.get("raw_side"), record.get("side"))
    raw_outcome = _first_text(record.get("rawTokenOutcome"), record.get("raw_outcome"), record.get("outcome"))
    raw_price = _first_text(record.get("rawTokenPrice"), record.get("raw_token_price"), record.get("price"))
    if not raw_price and record.get("rawTokenPrice") == UNKNOWN:
        raw_price = UNKNOWN
    return _make_case(
        case_id=f"known-{case_slug}",
        category=case_slug,
        source_type=source_type,
        source_path=source_path,
        mode=mode,
        wallet=_first_text(record.get("wallet"), "unknown"),
        market=_first_text(record.get("market"), record.get("marketSlug"), record.get("artifactFamily"), "unknown"),
        event=_first_text(record.get("event"), record.get("eventSlug"), "unknown"),
        trade_key=_first_text(record.get("tradeKey"), record.get("uniqueTradeKey"), record.get("rowId"), "unknown"),
        raw_side=raw_side,
        raw_outcome=raw_outcome,
        raw_price=raw_price,
        expected_phase2_effect=expected_phase2_effect,
        expected_phase4_effect=expected_phase4_effect,
        phase3_status=phase3_status,
        sensitive_context=bool(record.get("sensitiveGateContext", sensitive_context if sensitive_context is not None else False)),
        notes=notes,
        provenance_quality=_provenance_quality(source_type, record),
        derived_from_artifact=_first_text(record.get("artifactPath"), ""),
        quality_notes=_as_list(record.get("qualityNotes")),
        source_note="derived from bounded local audit/review output",
    )


def _make_case(
    *,
    case_id: str,
    category: str,
    source_type: str,
    source_path: str,
    mode: str,
    wallet: str,
    market: str,
    event: str,
    trade_key: str,
    raw_side: str,
    raw_outcome: str,
    raw_price: str,
    expected_phase2_effect: str,
    expected_phase4_effect: str,
    phase3_status: str,
    sensitive_context: bool,
    notes: str,
    provenance_quality: str,
    derived_from_artifact: str = "",
    quality_notes: Sequence[str] | None = None,
    assertion_type: str = "side_outcome_contract",
    expected_behavior: str = "Preserve current side/outcome normalization and keep this fixture sidecar-only.",
    forbidden_interpretation: str = "Do not use this benchmark case to change scoring, gates, labels, routing, or production runtime behavior.",
    false_positive_notes: Sequence[str] | None = None,
    source_note: str = "",
) -> dict[str, object]:
    normalized = normalize_side_outcome(raw_side, raw_outcome, raw_price)
    cluster = normalize_cluster_direction(raw_side, raw_outcome, raw_price)
    return {
        "case_id": case_id,
        "category": category,
        "source_type": source_type,
        "source_path": source_path,
        "derived_from_artifact": derived_from_artifact,
        "mode": mode,
        "wallet": wallet,
        "market": market,
        "event": event,
        "trade_key": trade_key,
        "raw_side": raw_side or UNKNOWN,
        "raw_outcome": raw_outcome or UNKNOWN,
        "raw_token_price": raw_price or UNKNOWN,
        "economic_side": normalized.economic_side,
        "model_probability": _decimal_or_unknown(normalized.economic_side_probability),
        "cluster_direction": cluster.cluster_direction,
        "expected_phase2_effect": expected_phase2_effect,
        "expected_phase4_effect": expected_phase4_effect,
        "phase3_capital_status": phase3_status,
        "sensitive_context": bool(sensitive_context),
        "expected_result": {
            "economic_side": normalized.economic_side,
            "model_probability": _decimal_or_unknown(normalized.economic_side_probability),
            "cluster_direction": cluster.cluster_direction,
            "phase3_runtime_allowed": False,
            "direct_gate_mutation_allowed": False,
        },
        "assertion_type": assertion_type,
        "expected_behavior": expected_behavior,
        "forbidden_interpretation": forbidden_interpretation,
        "false_positive_notes": list(false_positive_notes or []),
        "source_note": source_note,
        "notes": notes,
        "quality_notes": list(quality_notes or []),
        "provenance_quality": provenance_quality,
    }


def _ensure_case(case: Mapping[str, object]) -> dict[str, object]:
    ensured = dict(case)
    for field in REQUIRED_CASE_FIELDS:
        if field == "sensitive_context":
            ensured.setdefault(field, False)
        elif field == "false_positive_notes":
            ensured.setdefault(field, [])
        else:
            ensured.setdefault(field, "")
    return ensured


def _source_inventory(sources: Mapping[str, object]) -> dict[str, object]:
    inventory: dict[str, object] = {}
    for name, payload in sources.items():
        if isinstance(payload, list):
            inventory[name] = {"available": True, "kind": "list", "count": len(payload)}
        elif isinstance(payload, Mapping):
            inventory[name] = {"available": True, "kind": "object", "keys": sorted(str(key) for key in payload.keys())[:12]}
        else:
            inventory[name] = {"available": False, "kind": "missing"}
    return inventory


def _pattern_by_key(payload: Mapping[str, object], pattern_key: str) -> Mapping[str, object]:
    for pattern in _as_list(payload.get("patterns")):
        if isinstance(pattern, Mapping) and pattern.get("pattern_key") == pattern_key:
            return pattern
    return {
        "pattern_key": pattern_key,
        "label": pattern_key.replace("_", " ").title(),
        "forbidden_use": "Do not automatically suppress, downgrade, rescore, reroute, or change gates from this advisory control.",
        "safe_use": "Use as analyst caution and packet triage context only.",
        "examples": [],
    }


def _first_example(pattern: Mapping[str, object]) -> Mapping[str, object]:
    examples = _as_list(pattern.get("examples"))
    for example in examples:
        if isinstance(example, Mapping):
            return example
    return {}


def _provenance_quality(source_type: str, record: Mapping[str, object]) -> str:
    evidence = _first_text(record.get("artifactEvidenceType"), "")
    if source_type == "synthetic_fixture":
        return "synthetic_contract_fixture"
    if source_type == "review_packet":
        return "review_packet_derived_from_real_local_artifact" if evidence in {"", "real_local"} else f"review_packet_{evidence}"
    if source_type == "generated_audit_evidence":
        return "generated_audit_evidence_derived_from_real_local_artifact" if evidence == "real_local" else "generated_audit_evidence"
    return "real_local_artifact_bounded_sample"


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _first(rows: Sequence[object], predicate) -> Mapping[str, object] | None:
    for row in rows:
        if isinstance(row, Mapping):
            try:
                if predicate(row):
                    return row
            except Exception:
                continue
    return None


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _as_text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if value not in (None, ""):
        return [str(value)]
    return []


def _first_text(*values: object) -> str:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""


def _is_advisory_control(case: Mapping[str, object]) -> bool:
    assertion_type = str(case.get("assertion_type") or "")
    return assertion_type in {"false_positive_control", "sidecar_context_control"}


def _decimal_or_unknown(value: object) -> str:
    return str(value) if value not in (None, "") else UNKNOWN


if __name__ == "__main__":
    raise SystemExit(main())
