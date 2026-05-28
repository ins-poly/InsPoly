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
SCHEMA_VERSION = "known_case_benchmark_v3"
DEFAULT_OUTPUT = Path("tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json")

ALLOWED_SOURCE_TYPES = {
    "false_positive_library",
    "generated_audit_evidence",
    "public_enforcement_source",
    "public_source_metadata",
    "review_packet",
    "real_local_artifact",
    "sidecar_measurement",
    "synthetic_fixture",
}

ALLOWED_ASSERTION_LEVELS = {
    "exact_wallet_supported",
    "defer_needs_human_label",
    "insufficient_source_evidence",
    "local_artifact_supported",
    "market_level_only",
    "named_user_local_wallet_candidate",
    "named_user_only",
    "pattern_level_only",
    "sidecar_context_only",
    "synthetic_control",
}

PUBLIC_EXACT_WALLET_DEFERRED_REASON = (
    "Public sources and local artifacts do not link this public case to a "
    "fixture-grade exact wallet/user/market identity. Keep the case non-exact "
    "until a source or human review label proves the identity bridge."
)

PUBLIC_LOCAL_ARTIFACT_REFS: dict[str, list[dict[str, object]]] = {
    "public_maduro_enforcement_named_user_control": [
        {
            "path": "validation_outputs/event_forensic_performance_expansion_candidates_20260525.json",
            "match": "eventSlug=maduro-in-us-custody-by-january-31; eventSlug=maduro-out-in-2025",
            "confidence": "market_family_only",
            "proves_wallet_identity": False,
        },
        {
            "path": "validation_outputs/event_forensic_performance_expansion_resolution_20260525.json",
            "match": "bounded target resolution found Maduro event scopes, not named-user wallet identity",
            "confidence": "market_family_only",
            "proves_wallet_identity": False,
        },
    ],
    "public_maduro_pre_charge_market_timing_control": [
        {
            "path": "validation_outputs/event_forensic_performance_expansion_candidates_20260525.json",
            "match": "local candidate pool contains Maduro event families",
            "confidence": "market_family_only",
            "proves_wallet_identity": False,
        },
    ],
    "public_iran_military_cluster_pattern_control": [
        {
            "path": "validation_outputs/event_forensic_performance_expansion_candidates_20260525.json",
            "match": "eventSlug=us-x-iran-permanent-peace-deal-by; eventSlug=us-strikes-iran-by",
            "confidence": "event_family_only",
            "proves_wallet_identity": False,
        },
        {
            "path": "validation_outputs/event_forensic_granular_pagination_probe_20260526.json",
            "match": "conditionId=0xceb6dfaa2cf5abc9d47ebc867b984a7715104944249274e8a483a2e17473e5f5",
            "confidence": "market_condition_only",
            "proves_wallet_identity": False,
        },
    ],
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
    "public_maduro_enforcement_named_user_control",
    "public_maduro_pre_charge_market_timing_control",
    "public_iran_military_cluster_pattern_control",
    "public_zachxbt_axiom_pattern_control",
    "public_google_year_in_search_retrospective_control",
    "public_trump_whale_high_volume_control",
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
    "assertion_level",
    "evidence_quality",
    "expected_behavior",
    "forbidden_interpretation",
    "false_positive_notes",
    "source_urls",
    "source_titles",
    "source_dates",
    "public_knowledge_timing",
    "catalyst_timing",
    "requires_fresh_validation",
    "source_note",
    "local_artifact_refs",
    "identity_confidence",
    "deferred_reason",
    "human_review_needed",
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
            "publicCaseCount": sum(1 for case in cases if case.get("assertion_type") == "public_case_control"),
            "exactWalletPublicCaseCount": sum(1 for case in cases if case.get("assertion_level") == "exact_wallet_supported"),
            "namedUserLocalWalletCandidatePublicCaseCount": sum(
                1 for case in cases if case.get("assertion_level") == "named_user_local_wallet_candidate"
            ),
            "namedUserPublicCaseCount": sum(1 for case in cases if case.get("assertion_level") == "named_user_only"),
            "patternLevelPublicCaseCount": sum(1 for case in cases if case.get("assertion_level") == "pattern_level_only"),
            "marketLevelPublicCaseCount": sum(1 for case in cases if case.get("assertion_level") == "market_level_only"),
            "insufficientSourcePublicCaseCount": sum(1 for case in cases if case.get("assertion_level") == "insufficient_source_evidence"),
            "deferNeedsHumanLabelPublicCaseCount": sum(1 for case in cases if case.get("assertion_level") == "defer_needs_human_label"),
            "publicSourceUrlCount": len(
                {
                    str(url)
                    for case in cases
                    if case.get("assertion_type") == "public_case_control"
                    for url in _as_list(case.get("source_urls"))
                }
            ),
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
        assertion_level = str(case.get("assertion_level") or "")
        if assertion_level not in ALLOWED_ASSERTION_LEVELS:
            errors.append(f"{case.get('case_id', index)} unsupported assertion_level: {assertion_level}")
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
            if case.get("requires_fresh_validation") is not True:
                errors.append(f"{case.get('case_id', index)} advisory control must require fresh validation")
            if isinstance(expected, Mapping):
                if expected.get("automatic_action_allowed") is not False:
                    errors.append(f"{case.get('case_id', index)} advisory control must forbid automatic action")
                if expected.get("safe_to_use_for_scoring_claims") is not False:
                    errors.append(f"{case.get('case_id', index)} advisory control must not be scoring evidence")
                if expected.get("requires_fresh_validation_for_model_use") is not True:
                    errors.append(f"{case.get('case_id', index)} advisory control must require fresh validation for model use")
        if case.get("assertion_type") == "public_case_control":
            for field in ("source_urls", "source_titles", "source_dates"):
                values = case.get(field)
                if not isinstance(values, list) or not values:
                    errors.append(f"{case.get('case_id', index)} public case must include {field}")
            if not str(case.get("source_note") or "").strip():
                errors.append(f"{case.get('case_id', index)} public case must include source_note")
            if not str(case.get("identity_confidence") or "").strip():
                errors.append(f"{case.get('case_id', index)} public case must include identity_confidence")
            local_refs = case.get("local_artifact_refs")
            if not isinstance(local_refs, list):
                errors.append(f"{case.get('case_id', index)} public case local_artifact_refs must be a list")
                local_refs = []
            for ref_index, ref in enumerate(local_refs):
                if not isinstance(ref, Mapping):
                    errors.append(f"{case.get('case_id', index)} local_artifact_refs[{ref_index}] must be an object")
                    continue
                ref_path = str(ref.get("path") or "")
                if not ref_path or ref_path.startswith("/") or len(ref_path) > 180:
                    errors.append(f"{case.get('case_id', index)} local_artifact_refs[{ref_index}] must be a compact relative path")
                if not str(ref.get("match") or "").strip():
                    errors.append(f"{case.get('case_id', index)} local_artifact_refs[{ref_index}] must describe the matched field")
            if assertion_level == "exact_wallet_supported":
                if str(case.get("wallet") or "") in {"", "unknown", "pattern-level"}:
                    errors.append(f"{case.get('case_id', index)} exact-wallet case requires explicit wallet")
                if str(case.get("market") or "") in {"", "unknown", "pattern-level"}:
                    errors.append(f"{case.get('case_id', index)} exact-wallet case requires explicit market")
            elif case.get("assertion_type") == "public_case_control":
                if not str(case.get("deferred_reason") or "").strip():
                    errors.append(f"{case.get('case_id', index)} non-exact public case must include deferred_reason")
            if assertion_level == "pattern_level_only":
                if str(case.get("wallet") or "") != "pattern-level":
                    errors.append(f"{case.get('case_id', index)} pattern-level public case must not assert a wallet")
                if isinstance(expected, Mapping) and expected.get("exact_wallet_detection_allowed") is not False:
                    errors.append(f"{case.get('case_id', index)} pattern-level public case must forbid exact-wallet detection")
            if assertion_level == "named_user_local_wallet_candidate":
                if case.get("human_review_needed") is not True:
                    errors.append(f"{case.get('case_id', index)} named-user local wallet candidate must require human review")
                if not local_refs:
                    errors.append(f"{case.get('case_id', index)} named-user local wallet candidate must include local artifact refs")
                if isinstance(expected, Mapping) and expected.get("exact_wallet_detection_allowed") is not False:
                    errors.append(f"{case.get('case_id', index)} local wallet candidate must forbid exact-wallet detection")
            if assertion_level in {"insufficient_source_evidence", "defer_needs_human_label"}:
                if case.get("human_review_needed") is not True:
                    errors.append(f"{case.get('case_id', index)} deferred/insufficient public case must require human review")
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
        _public_case_control(
            category="public_maduro_enforcement_named_user_control",
            assertion_level="named_user_only",
            mode="event_forensic",
            wallet="named-user-only",
            market="maduro-out-by-january-31-2026",
            event="maduro-and-venezuela-related-contracts",
            raw_side="BUY",
            raw_outcome="YES",
            raw_price="0.33",
            source_urls=[
                "https://www.justice.gov/usao-sdny/media/1437781/dl",
                "https://www.cftc.gov/media/13761/EnfGannonKenVanDykeComplaint042326/download",
            ],
            source_titles=[
                "United States v. Gannon Ken Van Dyke complaint",
                "CFTC complaint: Gannon Ken Van Dyke",
            ],
            source_dates=["2026-04-23", "2026-04-23"],
            expected_behavior="Official enforcement sources support a named-user public case, but not an exact wallet benchmark assertion.",
            forbidden_interpretation="Do not infer the exact Polymarket wallet from this source metadata or change runtime gates from a named-user enforcement case.",
            source_note="Official complaint/filing alleges named-user Maduro-related Polymarket trading and profits; wallet identity remains unavailable in this compact benchmark.",
            public_knowledge_timing={
                "status": "source_provided",
                "timestamp": "2026-01-03T04:21:00-05:00",
                "note": "DOJ complaint states the President publicly announced Maduro capture at approximately 4:21 AM EST.",
            },
            catalyst_timing={
                "status": "source_provided",
                "timestamp": "2026-01-03T04:21:00-05:00",
                "note": "Public announcement/resolution catalyst for Maduro/Venezuela markets.",
            },
            false_positive_notes=[
                "Named-user enforcement source is strong for public-case context but not exact-wallet fixture truth.",
                "Treat as a fresh-validation priority, not scorer-tuning data.",
            ],
            evidence_quality="official_named_user_source_no_wallet",
        ),
        _public_case_control(
            category="public_maduro_pre_charge_market_timing_control",
            assertion_level="market_level_only",
            mode="event_forensic",
            wallet="unknown",
            market="maduro-related-contracts",
            event="maduro-capture-public-market-timing",
            raw_side="BUY",
            raw_outcome="YES",
            raw_price="0.20",
            source_urls=[
                "https://www.axios.com/2026/01/05/venezuela-polymarket-prediction-insider-trading",
                "https://www.theatlantic.com/technology/2026/01/venezuela-maduro-polymarket-prediction-markets/685526/",
            ],
            source_titles=[
                "A congressman wants to criminalize insider trading on prediction markets",
                "The Polymarket Bets on Maduro Are a Warning",
            ],
            source_dates=["2026-01-05", "2026-01-06"],
            expected_behavior="Early public coverage supports market-level timing concern before identity attribution was available.",
            forbidden_interpretation="Do not turn pre-charge public reporting into exact-wallet truth, legal conclusion, or automatic detector behavior.",
            source_note="Public articles described suspiciously timed Maduro-related bets before later enforcement documents named an alleged trader.",
            public_knowledge_timing={
                "status": "article_publication",
                "timestamp": "2026-01-05",
                "note": "Axios public article date for post-event policy response.",
            },
            catalyst_timing={
                "status": "source_described",
                "timestamp": "2026-01-03",
                "note": "Maduro capture/announcement timing is described as the public catalyst.",
            },
            false_positive_notes=[
                "Before official attribution, public reporting supports timing concern only.",
                "Use as a source-quality guard against overclaiming from anonymous trades.",
            ],
            evidence_quality="public_market_timing_source_no_identity",
        ),
        _public_case_control(
            category="public_iran_military_cluster_pattern_control",
            assertion_level="pattern_level_only",
            mode="event_forensic",
            wallet="pattern-level",
            market="iran-military-operation-contracts",
            event="iran-war-polymarket-cluster",
            raw_side="BUY",
            raw_outcome="YES",
            raw_price="0.04",
            source_urls=[
                "https://www.cbsnews.com/news/betting-on-iran-war-insider-trading-concerns-prediction-markets-60-minutes/",
                "https://cointelegraph.com/news/bubblemaps-polymarket-cluster-win-military-bets",
            ],
            source_titles=[
                "Suspected insider accounts net $2.4 million on Polymarket Iran war bets with 98% win rate, firm finds",
                "Wallet cluster earned $2.4M with 98% win rate on Polymarket military bets: Bubblemaps",
            ],
            source_dates=["2026-05-17", "2026-05-19"],
            expected_behavior="Public reporting supports a pattern-level cluster/timing benchmark, not exact wallet detection.",
            forbidden_interpretation="Do not assert that InsPoly should identify any specific wallet from this public-source pattern alone.",
            source_note="CBS/Cointelegraph summarize Bubblemaps-reported connected accounts and military-event timing; exact wallet fixture labels are not imported.",
            public_knowledge_timing={
                "status": "article_publication",
                "timestamp": "2026-05-17",
                "note": "CBS/60 Minutes public publication date.",
            },
            catalyst_timing={
                "status": "multiple_source_described",
                "timestamp": "2026-02-28/2026-05",
                "note": "Sources describe multiple U.S. military/Iran developments rather than one fixture-grade timestamp.",
            },
            false_positive_notes=[
                "High win rate and connected-account reporting are pattern evidence only.",
                "Exact wallet labels require separate source proof or local artifact reconciliation.",
            ],
            evidence_quality="public_pattern_source_no_exact_wallet_import",
        ),
        _public_case_control(
            category="public_zachxbt_axiom_pattern_control",
            assertion_level="pattern_level_only",
            mode="event_forensic",
            wallet="pattern-level",
            market="zachxbt-axiom-investigation-market",
            event="zachxbt-company-named-investigation",
            raw_side="BUY",
            raw_outcome="YES",
            raw_price="0.14",
            source_urls=[
                "https://www.coindesk.com/markets/2026/02/27/polymarket-bettors-appear-to-have-insider-traded-on-a-market-designed-to-catch-insider-traders",
                "https://cointelegraph.com/news/suspected-insider-1-2m-zachxbt-axiom-expose",
            ],
            source_titles=[
                "Polymarket bettors appear to have insider-traded on a market designed to catch insider traders",
                "Suspected insider wallets rack up $1.2M betting on ZachXBT's Axiom expose",
            ],
            source_dates=["2026-02-27", "2026-02-27"],
            expected_behavior="Public reporting supports an advance-publication pattern case for source timing and overclaiming controls.",
            forbidden_interpretation="Do not treat partial wallet snippets, handles, or article summaries as exact-wallet benchmark truth.",
            source_note="Sources describe concentrated Axiom bets before ZachXBT publication and attribution uncertainty due Polymarket identity limits.",
            public_knowledge_timing={
                "status": "source_described",
                "timestamp": "2026-02-26",
                "note": "Sources describe ZachXBT publication as the public reveal; exact timestamp is not fixture-grade here.",
            },
            catalyst_timing={
                "status": "source_described",
                "timestamp": "2026-02-26",
                "note": "Axiom was publicly named by ZachXBT after the relevant betting window.",
            },
            false_positive_notes=[
                "Use for pattern-level source timing, not exact-wallet assertion.",
                "Attribution remains unclear without exchange cooperation.",
            ],
            evidence_quality="public_pattern_source_partial_wallet_snippets",
        ),
        _public_case_control(
            category="public_google_year_in_search_retrospective_control",
            assertion_level="market_level_only",
            mode="event_forensic",
            wallet="unknown",
            market="google-year-in-search-related-contracts",
            event="google-year-in-search-2025",
            raw_side="BUY",
            raw_outcome="YES",
            raw_price="0.18",
            source_urls=[
                "https://www.theatlantic.com/technology/2026/01/venezuela-maduro-polymarket-prediction-markets/685526/",
            ],
            source_titles=[
                "The Polymarket Bets on Maduro Are a Warning",
            ],
            source_dates=["2026-01-06"],
            expected_behavior="Public article mention supports a retrospective-only caution, not a benchmarkable wallet identity.",
            forbidden_interpretation="Do not use a secondary article mention as exact case evidence, automatic suspicion, or runtime tuning approval.",
            source_note="Atlantic article mentions Google Year in Search bets as another public example, but the fixture has no primary source or wallet identity.",
            public_knowledge_timing={
                "status": "secondary_article_publication",
                "timestamp": "2026-01-06",
                "note": "Only secondary article publication date is recorded.",
            },
            catalyst_timing={
                "status": "source_described_no_exact_timestamp",
                "timestamp": "2025-12",
                "note": "Article describes bets before Google's Year in Search report release but does not provide fixture-grade timing.",
            },
            false_positive_notes=[
                "Secondary-source-only item; keep as retrospective caution.",
                "Requires primary source and wallet/market reconciliation before executable exact assertions.",
            ],
            evidence_quality="secondary_public_source_retrospective_only",
        ),
        _public_case_control(
            category="public_trump_whale_high_volume_control",
            assertion_level="named_user_only",
            mode="scanner",
            wallet="named-user-only",
            market="presidential-election-winner-2024",
            event="2024-us-presidential-election",
            raw_side="BUY",
            raw_outcome="YES",
            raw_price="0.62",
            source_urls=[
                "https://www.investing.com/news/world-news/polymarket-says-mystery-trump-bettor-is-french-national-3680928",
            ],
            source_titles=[
                "Polymarket says mystery Trump bettor is French national",
            ],
            source_dates=["2024-10-24"],
            expected_behavior="High-volume public trader/source review should be a false-positive caution unless independent hard evidence exists.",
            forbidden_interpretation="Do not infer manipulation, insider status, or exact wallet identity solely from high volume and named account handles.",
            source_note="Reuters-republished source says Polymarket investigated a French high-volume Trump bettor and did not identify manipulation evidence at that time.",
            public_knowledge_timing={
                "status": "article_publication",
                "timestamp": "2024-10-24",
                "note": "Reuters publication date via Investing.com mirror.",
            },
            catalyst_timing={
                "status": "public_election_context",
                "timestamp": "2024-11-05/2024-11-06",
                "note": "Election result context is public and high-volume; this fixture is a false-positive control, not a suspicion label.",
            },
            false_positive_notes=[
                "High-volume public trader behavior can move or lead market odds without proving insider access.",
                "Use as a public-knowledge false-positive control.",
            ],
            evidence_quality="public_named_account_high_volume_false_positive_control",
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
            "exact_wallet_detection_allowed": False,
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
            "exact_wallet_detection_allowed": False,
            "false_positive_control": True,
            "requires_fresh_validation_for_model_use": True,
            "safe_to_use_for_scoring_claims": False,
        }
    )
    return case


def _public_case_control(
    *,
    category: str,
    assertion_level: str,
    mode: str,
    wallet: str,
    market: str,
    event: str,
    raw_side: str,
    raw_outcome: str,
    raw_price: str,
    source_urls: Sequence[str],
    source_titles: Sequence[str],
    source_dates: Sequence[str],
    expected_behavior: str,
    forbidden_interpretation: str,
    source_note: str,
    public_knowledge_timing: Mapping[str, object],
    catalyst_timing: Mapping[str, object],
    false_positive_notes: Sequence[str],
    evidence_quality: str,
    local_artifact_refs: Sequence[Mapping[str, object]] | None = None,
    identity_confidence: str | None = None,
    deferred_reason: str = PUBLIC_EXACT_WALLET_DEFERRED_REASON,
    human_review_needed: bool = True,
) -> dict[str, object]:
    case = _make_case(
        case_id=f"known-{category}",
        category=category,
        source_type="public_enforcement_source" if "enforcement" in category else "public_source_metadata",
        source_path="docs/inspoly_public_case_benchmark_labeling_20260526.md",
        mode=mode,
        wallet=wallet,
        market=market,
        event=event,
        trade_key=f"public|{category}|{raw_side}|{raw_outcome}|{raw_price}",
        raw_side=raw_side,
        raw_outcome=raw_outcome,
        raw_price=raw_price,
        expected_phase2_effect=f"{category}_public_metadata_only",
        expected_phase4_effect="unchanged_long_yes",
        phase3_status="not_applicable",
        sensitive_context=category in {
            "public_maduro_enforcement_named_user_control",
            "public_maduro_pre_charge_market_timing_control",
            "public_iran_military_cluster_pattern_control",
            "public_zachxbt_axiom_pattern_control",
        },
        notes=expected_behavior,
        provenance_quality=f"{evidence_quality}_compact_metadata",
        assertion_type="public_case_control",
        assertion_level=assertion_level,
        expected_behavior=expected_behavior,
        forbidden_interpretation=forbidden_interpretation,
        false_positive_notes=false_positive_notes,
        source_note=source_note,
        source_urls=source_urls,
        source_titles=source_titles,
        source_dates=source_dates,
        evidence_quality=evidence_quality,
        public_knowledge_timing=public_knowledge_timing,
        catalyst_timing=catalyst_timing,
        requires_fresh_validation=True,
        local_artifact_refs=local_artifact_refs or PUBLIC_LOCAL_ARTIFACT_REFS.get(category, []),
        identity_confidence=identity_confidence or assertion_level,
        deferred_reason=deferred_reason if assertion_level != "exact_wallet_supported" else "",
        human_review_needed=human_review_needed,
    )
    case["expected_result"].update(
        {
            "automatic_action_allowed": False,
            "exact_wallet_detection_allowed": False,
            "false_positive_control": category == "public_trump_whale_high_volume_control",
            "public_case_control": True,
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
    assertion_level: str | None = None,
    evidence_quality: str | None = None,
    expected_behavior: str = "Preserve current side/outcome normalization and keep this fixture sidecar-only.",
    forbidden_interpretation: str = "Do not use this benchmark case to change scoring, gates, labels, routing, or production runtime behavior.",
    false_positive_notes: Sequence[str] | None = None,
    source_urls: Sequence[str] | None = None,
    source_titles: Sequence[str] | None = None,
    source_dates: Sequence[str] | None = None,
    public_knowledge_timing: Mapping[str, object] | None = None,
    catalyst_timing: Mapping[str, object] | None = None,
    requires_fresh_validation: bool | None = None,
    source_note: str = "",
    local_artifact_refs: Sequence[Mapping[str, object]] | None = None,
    identity_confidence: str | None = None,
    deferred_reason: str = "",
    human_review_needed: bool = False,
) -> dict[str, object]:
    normalized = normalize_side_outcome(raw_side, raw_outcome, raw_price)
    cluster = normalize_cluster_direction(raw_side, raw_outcome, raw_price)
    resolved_assertion_level = assertion_level or _default_assertion_level(source_type, assertion_type)
    resolved_requires_fresh_validation = bool(requires_fresh_validation) if requires_fresh_validation is not None else _is_advisory_type(assertion_type)
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
        "assertion_level": resolved_assertion_level,
        "evidence_quality": evidence_quality or provenance_quality,
        "expected_behavior": expected_behavior,
        "forbidden_interpretation": forbidden_interpretation,
        "false_positive_notes": list(false_positive_notes or []),
        "source_urls": list(source_urls or []),
        "source_titles": list(source_titles or []),
        "source_dates": list(source_dates or []),
        "public_knowledge_timing": dict(public_knowledge_timing or {"status": "not_applicable"}),
        "catalyst_timing": dict(catalyst_timing or {"status": "not_applicable"}),
        "requires_fresh_validation": resolved_requires_fresh_validation,
        "source_note": source_note,
        "local_artifact_refs": [dict(ref) for ref in (local_artifact_refs or [])],
        "identity_confidence": identity_confidence or resolved_assertion_level,
        "deferred_reason": deferred_reason,
        "human_review_needed": bool(human_review_needed),
        "notes": notes,
        "quality_notes": list(quality_notes or []),
        "provenance_quality": provenance_quality,
    }


def _ensure_case(case: Mapping[str, object]) -> dict[str, object]:
    ensured = dict(case)
    for field in REQUIRED_CASE_FIELDS:
        if field == "sensitive_context":
            ensured.setdefault(field, False)
        elif field in {"false_positive_notes", "local_artifact_refs"}:
            ensured.setdefault(field, [])
        elif field in {"source_urls", "source_titles", "source_dates"}:
            ensured.setdefault(field, [])
        elif field in {"public_knowledge_timing", "catalyst_timing"}:
            ensured.setdefault(field, {"status": "not_applicable"})
        elif field == "requires_fresh_validation":
            ensured.setdefault(field, _is_advisory_type(str(ensured.get("assertion_type") or "")))
        elif field == "assertion_level":
            ensured.setdefault(
                field,
                _default_assertion_level(
                    str(ensured.get("source_type") or ""),
                    str(ensured.get("assertion_type") or ""),
                ),
            )
        elif field == "evidence_quality":
            ensured.setdefault(field, ensured.get("provenance_quality", "unknown"))
        elif field == "identity_confidence":
            ensured.setdefault(field, ensured.get("assertion_level", "unknown"))
        elif field == "human_review_needed":
            ensured.setdefault(field, False)
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
    return _is_advisory_type(assertion_type)


def _is_advisory_type(assertion_type: str) -> bool:
    return assertion_type in {"false_positive_control", "public_case_control", "sidecar_context_control"}


def _default_assertion_level(source_type: str, assertion_type: str) -> str:
    if assertion_type == "public_case_control":
        return "pattern_level_only"
    if assertion_type == "sidecar_context_control":
        return "sidecar_context_only"
    if source_type == "synthetic_fixture":
        return "synthetic_control"
    if source_type in {"generated_audit_evidence", "real_local_artifact", "review_packet"}:
        return "local_artifact_supported"
    if source_type == "false_positive_library":
        return "local_artifact_supported"
    return "pattern_level_only"


def _decimal_or_unknown(value: object) -> str:
    return str(value) if value not in (None, "") else UNKNOWN


if __name__ == "__main__":
    raise SystemExit(main())
