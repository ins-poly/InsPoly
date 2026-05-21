from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.report_dedupe import build_count_hygiene_summary, count_hygiene_warnings


DEFAULT_INPUT_DIRS = (
    Path("event_forensic_outputs"),
    Path("archive_outputs"),
    Path("ai_review_outputs"),
)
DEFAULT_OUTPUT_DIR = Path("model_behavior_audit_outputs")
FUNNEL_FILE_SUFFIX = "candidate_admission_funnel.json"

HARD_EVIDENCE_REVIEW_TIER = "Hard Evidence Review"
PROXY_FUNDING_GRADES = {"cex_proxy", "bridge_proxy"}
REPRICING_SOURCE_QUALITY_MECHANICAL = "mechanical"
SUSPICIOUS_FUNDING_QUALITIES = {"strong", "moderate", "weak", "none", "unknown"}

INDEPENDENT_HARD_EVIDENCE_SOURCES = {
    "split_wallet_pattern",
    "strict_shared_funding_source",
    "strict_shared_funding",
    "non_proxy_shared_funding",
    "suspicious_recent_funding",
    "dormant_wallet_reactivation",
    "low_probability_early_winner",
    "event_family_repeat_narrow_context",
    "coordinated_sizing_with_hard_evidence",
    "same_market_same_direction_strict_structural_cluster",
}
STRUCTURAL_HARD_EVIDENCE_SOURCES = INDEPENDENT_HARD_EVIDENCE_SOURCES - {"suspicious_recent_funding"}
HIGH_IMPACT_SOURCE_TOKENS = {
    "high_impact_timing_or_repricing",
    "high-impact timing/repricing",
    "high impact timing/repricing",
}

FUNDING_SIGNAL_KEYS = (
    "funding_source_label",
    "fundingSourceLabel",
    "funding_source_category",
    "fundingSourceCategory",
    "funding_origin_label",
    "fundingOriginLabel",
    "funding_origin_category",
    "fundingOriginCategory",
    "funding_amount_usdc",
    "fundingAmountUsdc",
    "funding_timestamp",
    "fundingTimestamp",
    "funding_graph_key_strict",
    "fundingGraphKeyStrict",
    "funding_graph_key_proxy",
    "fundingGraphKeyProxy",
    "funding_key",
    "fundingKey",
    "shared_funding_source_flag",
    "sharedFundingSourceFlag",
    "suspicious_funding_flag",
    "suspiciousFundingFlag",
    "recent_external_funding_flag",
    "recentExternalFundingFlag",
    "cex_proxy_cluster_flag",
    "cexProxyClusterFlag",
    "funding_proxy_cluster_flag",
    "fundingProxyClusterFlag",
    "funding_proxy_tight_cohort_flag",
    "fundingProxyTightCohortFlag",
    "fundingResolverAvailable",
    "funding_resolver_available",
    "fundingResolverDisabledReason",
    "funding_resolver_disabled_reason",
    "fundingResolverAuthError",
    "funding_resolver_auth_error",
    "fundingResolverUnavailableReason",
    "funding_resolver_unavailable_reason",
    "fundingResolverFunctionalStatus",
    "funding_resolver_functional_status",
    "fundingResolverEndpointLabel",
    "funding_resolver_endpoint_label",
    "fundingResolverLastError",
    "funding_resolver_last_error",
    "fundingTraceAttemptedCount",
    "funding_trace_attempted_count",
    "fundingTraceSucceededCount",
    "funding_trace_succeeded_count",
    "fundingTraceFailedCount",
    "funding_trace_failed_count",
    "fundingTraceSkippedCount",
    "funding_trace_skipped_count",
    "fundingTraceCoverageRatio",
    "funding_trace_coverage_ratio",
    "fundingTraceEndpointPoolSize",
    "funding_trace_endpoint_pool_size",
    "fundingTraceRateLimitedCount",
    "funding_trace_rate_limited_count",
    "fundingTraceRetryCount",
    "funding_trace_retry_count",
    "fundingTraceFallbackEndpointCount",
    "funding_trace_fallback_endpoint_count",
    "fundingTraceLogChunksAttempted",
    "funding_trace_log_chunks_attempted",
    "fundingTraceLogChunksSucceeded",
    "funding_trace_log_chunks_succeeded",
    "fundingTraceLogChunksFailed",
    "funding_trace_log_chunks_failed",
    "fundingTraceCacheHitCount",
    "funding_trace_cache_hit_count",
    "fundingTraceCacheMissCount",
    "funding_trace_cache_miss_count",
    "fundingTracePersistentCacheEnabled",
    "funding_trace_persistent_cache_enabled",
    "fundingTracePersistentCacheHitCount",
    "funding_trace_persistent_cache_hit_count",
    "fundingTracePersistentCacheMissCount",
    "funding_trace_persistent_cache_miss_count",
    "fundingTracePersistentCacheWriteCount",
    "funding_trace_persistent_cache_write_count",
    "fundingTracePersistentCacheExpiredCount",
    "funding_trace_persistent_cache_expired_count",
    "fundingTracePersistentCacheFailureCooldownCount",
    "funding_trace_persistent_cache_failure_cooldown_count",
    "fundingTracePersistentCacheSchemaVersion",
    "funding_trace_persistent_cache_schema_version",
    "fundingTraceFromPersistentCache",
    "funding_trace_from_persistent_cache",
    "fundingTracePersistentCacheStatus",
    "funding_trace_persistent_cache_status",
)
REPRICING_SIGNAL_KEYS = (
    "favorable_repricing_flag",
    "favorableRepricingFlag",
    "favorable_move_15m",
    "favorableMove15m",
    "favorable_move_1h",
    "favorableMove1h",
    "favorable_move_4h",
    "favorableMove4h",
    "favorable_move_24h",
    "favorableMove24h",
    "repricing_driver_trade_count",
    "repricingDriverTradeCount",
    "repricing_driver_wallet_count",
    "repricingDriverWalletCount",
    "repricing_window_trade_count",
    "repricingWindowTradeCount",
    "repricing_same_outcome_trade_count",
    "repricingSameOutcomeTradeCount",
    "repricing_driven_by_single_wallet",
    "repricingDrivenBySingleWallet",
    "repricing_source_quality",
    "repricingSourceQuality",
    "repricing_source_quality_reasons",
    "repricingSourceQualityReasons",
)
SUSPICIOUS_FUNDING_QUALITY_KEYS = (
    "suspiciousFundingQuality",
    "suspicious_funding_quality",
    "suspiciousFundingQualityReasons",
    "suspicious_funding_quality_reasons",
    "suspiciousFundingHardEvidenceEligible",
    "suspicious_funding_hard_evidence_eligible",
    "suspiciousFundingTraceSucceeded",
    "suspicious_funding_trace_succeeded",
    "suspiciousFundingTraceDepth",
    "suspicious_funding_trace_depth",
    "suspiciousFundingSourceCategory",
    "suspicious_funding_source_category",
    "suspiciousFundingOriginCategory",
    "suspicious_funding_origin_category",
    "suspiciousFundingMinutesBeforeTrade",
    "suspicious_funding_minutes_before_trade",
    "suspiciousFundingAmountUsd",
    "suspicious_funding_amount_usd",
    "suspiciousFundingTradeNotionalUsd",
    "suspicious_funding_trade_notional_usd",
    "suspiciousFundingAmountToTradeRatio",
    "suspicious_funding_amount_to_trade_ratio",
    "suspiciousFundingRecentEnough",
    "suspicious_funding_recent_enough",
    "suspiciousFundingAmountAligned",
    "suspicious_funding_amount_aligned",
    "suspiciousFundingIndependentSupport",
    "suspicious_funding_independent_support",
    "suspiciousFundingIndependentSupportSources",
    "suspicious_funding_independent_support_sources",
    "suspiciousFundingSuppressorConflict",
    "suspicious_funding_suppressor_conflict",
    "suspiciousFundingSuppressorConflictReasons",
    "suspicious_funding_suppressor_conflict_reasons",
)
STRONG_RISK_ATTRIBUTION_KEYS = (
    "strongRiskGateTrace",
    "strong_risk_gate_trace",
    "strongRiskGateName",
    "strong_risk_gate_name",
    "strongRiskGateFamily",
    "strong_risk_gate_family",
    "strongRiskGateInputs",
    "strong_risk_gate_inputs",
    "strongRiskGatePassed",
    "strong_risk_gate_passed",
    "strongRiskGateType",
    "strong_risk_gate_type",
    "strongRiskGateReasons",
    "strong_risk_gate_reasons",
    "strongRiskGateEvidenceSources",
    "strong_risk_gate_evidence_sources",
    "strongRiskTimingProofSources",
    "strong_risk_timing_proof_sources",
    "strongRiskStructuralSources",
    "strong_risk_structural_sources",
    "strongRiskSupportingBoosters",
    "strong_risk_supporting_boosters",
    "strongRiskStructuralConcernCount",
    "strong_risk_structural_concern_count",
    "strongRiskTimingProofCount",
    "strong_risk_timing_proof_count",
    "strongRiskOpeningExposureConfirmed",
    "strong_risk_opening_exposure_confirmed",
    "strongRiskConfidenceScore",
    "strong_risk_confidence_score",
    "strongRiskSuspicionScore",
    "strong_risk_suspicion_score",
    "strongRiskHasIndependentHardEvidence",
    "strong_risk_has_independent_hard_evidence",
    "strongRiskIndependentEvidenceSources",
    "strong_risk_independent_evidence_sources",
    "strongRiskSuppressorConflict",
    "strong_risk_suppressor_conflict",
    "strongRiskSuppressorConflictReasons",
    "strong_risk_suppressor_conflict_reasons",
    "strongRiskHasHardEvidenceSources",
    "strong_risk_has_hard_evidence_sources",
    "strongRiskNoHardEvidenceExplanation",
    "strong_risk_no_hard_evidence_explanation",
    "strongRiskCompositionClass",
    "strong_risk_composition_class",
    "strongRiskExactGateBranch",
    "strong_risk_exact_gate_branch",
    "strongRiskExactGatePassed",
    "strong_risk_exact_gate_passed",
    "strongRiskExactGateFailedReasons",
    "strong_risk_exact_gate_failed_reasons",
    "strongRiskExactGateInputs",
    "strong_risk_exact_gate_inputs",
    "strongRiskTimingGateInputs",
    "strong_risk_timing_gate_inputs",
    "strongRiskStructureGateInputs",
    "strong_risk_structure_gate_inputs",
    "strongRiskRetrospectiveGateInputs",
    "strong_risk_retrospective_gate_inputs",
    "strongRiskGateSourceWasInferred",
    "strong_risk_gate_source_was_inferred",
    "strongRiskGateSourceInferenceReason",
    "strong_risk_gate_source_inference_reason",
    "strongRiskStructuralSourcesResolved",
    "strong_risk_structural_sources_resolved",
    "strongRiskHardEvidenceEligibleSources",
    "strong_risk_hard_evidence_eligible_sources",
    "strongRiskNonHardStructuralSources",
    "strong_risk_non_hard_structural_sources",
    "strongRiskMissingSourceAttribution",
    "strong_risk_missing_source_attribution",
    "strongRiskSourceAttributionIssue",
    "strong_risk_source_attribution_issue",
    "strongRiskNoHardEvidenceSourcesReason",
    "strong_risk_no_hard_evidence_sources_reason",
    "strongRiskStructuralButNotHardEvidence",
    "strong_risk_structural_but_not_hard_evidence",
    "strongRiskStructuralButNotHardEvidenceSources",
    "strong_risk_structural_but_not_hard_evidence_sources",
    "strongRiskWhyNoHardEvidence",
    "strong_risk_why_no_hard_evidence",
    "strongRiskScoreOnlyResolution",
    "strong_risk_score_only_resolution",
    "strongRiskGateLeakageCandidate",
    "strong_risk_gate_leakage_candidate",
    "strongRiskGateLeakageReason",
    "strong_risk_gate_leakage_reason",
    "strongRiskLiveDetectable",
    "strong_risk_live_detectable",
    "strongRiskRetrospectiveOnly",
    "strong_risk_retrospective_only",
    "strongRiskRetrospectiveSources",
    "strong_risk_retrospective_sources",
    "strongRiskOpeningExposureStatus",
    "strong_risk_opening_exposure_status",
    "strongRiskTimingRepricingOnly",
    "strong_risk_timing_repricing_only",
    "strongRiskScoreOnly",
    "strong_risk_score_only",
    "strongRiskSavedFieldsSufficient",
    "strong_risk_saved_fields_sufficient",
    "strongRiskDiagnosticOnly",
    "strong_risk_diagnostic_only",
)
ADMISSION_SIGNAL_KEYS = (
    "candidateAdmissionReason",
    "candidate_admission_reason",
    "candidateAdmissionStage",
    "candidate_admission_stage",
    "candidateAdmissionEvidenceSources",
    "candidate_admission_evidence_sources",
    "candidateAdmissionFloorNotional",
    "candidate_admission_floor_notional",
    "groupedCandidateId",
    "grouped_candidate_id",
    "groupedCandidateAggregateNotional",
    "grouped_candidate_aggregate_notional",
    "groupedCandidateWalletCount",
    "grouped_candidate_wallet_count",
    "groupedCandidateStrictFunding",
    "grouped_candidate_strict_funding",
    "groupedCandidateProxyOnly",
    "grouped_candidate_proxy_only",
    "groupedCandidateFundingGrade",
    "grouped_candidate_funding_grade",
    "groupedCandidateTimeSpanMinutes",
    "grouped_candidate_time_span_minutes",
    "groupedCandidatePriceBand",
    "grouped_candidate_price_band",
    "candidateAdmissionValidatedOpeningExposure",
    "candidate_admission_validated_opening_exposure",
    "candidateAdmissionRejectedReason",
    "candidate_admission_rejected_reason",
)
NEW_SCHEMA_KEYS = (
    "hardEvidenceSources",
    "hard_evidence_sources",
    "hardEvidenceReviewTier",
    "hard_evidence_review_tier",
    "fundingEvidenceGrade",
    "funding_evidence_grade",
    "repricingSourceQuality",
    "repricing_source_quality",
) + ADMISSION_SIGNAL_KEYS + SUSPICIOUS_FUNDING_QUALITY_KEYS + STRONG_RISK_ATTRIBUTION_KEYS

ROW_LIKE_KEYS = (
    "severity",
    "case_type",
    "caseType",
    "wallet",
    "trade_id",
    "tradeId",
    "condition_id",
    "conditionId",
    "eventForensicScore",
    "event_forensic_score",
    "walletScore",
    "clusterScore",
    "existingModelClass",
    "finalEventJudgment",
) + NEW_SCHEMA_KEYS + FUNDING_SIGNAL_KEYS + REPRICING_SIGNAL_KEYS + ADMISSION_SIGNAL_KEYS + SUSPICIOUS_FUNDING_QUALITY_KEYS + STRONG_RISK_ATTRIBUTION_KEYS

CONTAINER_KEYS = {
    "display_trades",
    "display_wallets",
    "display_clusters",
    "ranked_trades",
    "ranked_wallets",
    "wallet_clusters",
    "suspicious_trades",
    "suspicious_wallets",
    "flagged_cases",
    "cases",
    "case_packets",
    "trades",
    "wallets",
    "clusters",
    "rows",
    "records",
}

SUPPRESSOR_CODES = (
    "near_certainty",
    "yield_farm",
    "theta_decay",
    "stale_or_resolution_gap",
    "hard_resolution_gap",
    "bot_like_execution",
    "low_analyst_value_wallet",
    "domain_specialist",
    "high_volume_public_user",
)


def normalize_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize saved output rows without changing the production scoring model."""

    severity = _string_value(row, "severity", "riskLevel", "risk_level", "level")
    existing_model_class = _string_value(row, "existingModelClass", "existing_model_class")
    judgment = _string_value(
        row,
        "finalEventJudgment",
        "final_event_judgment",
        "judgment",
        "caseJudgment",
        "case_judgment",
    )
    visibility_tier = _string_value(
        row,
        "visibility_tier",
        "visibilityTier",
        "walletPrimaryReviewStatus",
        "wallet_primary_review_status",
        "primaryReviewStatus",
        "primary_review_status",
        "reviewTier",
        "review_tier",
    )

    hard_tier = _string_value(row, "hardEvidenceReviewTier", "hard_evidence_review_tier")
    hard_review_bool = _lookup(row, "hardEvidenceReview", "hard_evidence_review")
    hard_evidence_review = (
        hard_tier == HARD_EVIDENCE_REVIEW_TIER
        or _truthy(hard_review_bool)
        or visibility_tier == HARD_EVIDENCE_REVIEW_TIER
    )
    hard_sources = _listish(
        _lookup(
            row,
            "hardEvidenceSources",
            "hard_evidence_sources",
            "walletHardEvidenceSources",
            "wallet_hard_evidence_sources",
        )
    )
    hard_sources = _dedupe([_normalize_source(source) for source in hard_sources if source])
    hard_strength = _string_value(row, "hardEvidenceStrength", "hard_evidence_strength")

    funding_grade = _normalize_label(
        _string_value(row, "fundingEvidenceGrade", "funding_evidence_grade")
    )
    funding_grade_field_present = _has_key(row, "fundingEvidenceGrade") or _has_key(row, "funding_evidence_grade")
    suspicious_funding_quality = _normalize_label(
        _string_value(row, "suspiciousFundingQuality", "suspicious_funding_quality")
    )
    if suspicious_funding_quality not in SUSPICIOUS_FUNDING_QUALITIES:
        suspicious_funding_quality = "unknown" if suspicious_funding_quality else "unknown"
    suspicious_funding_hard_eligible = _truthy(
        _lookup(row, "suspiciousFundingHardEvidenceEligible", "suspicious_funding_hard_evidence_eligible")
    )
    suspicious_funding_independent_support = _truthy(
        _lookup(row, "suspiciousFundingIndependentSupport", "suspicious_funding_independent_support")
    )
    suspicious_funding_independent_support_sources = _dedupe(
        _normalize_label(value)
        for value in _listish(
            _lookup(
                row,
                "suspiciousFundingIndependentSupportSources",
                "suspicious_funding_independent_support_sources",
            )
        )
        if _normalize_label(value)
    )
    suspicious_funding_suppressor_conflict = _truthy(
        _lookup(row, "suspiciousFundingSuppressorConflict", "suspicious_funding_suppressor_conflict")
    )
    suspicious_funding_suppressor_conflict_reasons = _dedupe(
        _normalize_label(value)
        for value in _listish(
            _lookup(
                row,
                "suspiciousFundingSuppressorConflictReasons",
                "suspicious_funding_suppressor_conflict_reasons",
            )
        )
        if _normalize_label(value)
    )
    suspicious_funding_recent_enough = _truthy(
        _lookup(row, "suspiciousFundingRecentEnough", "suspicious_funding_recent_enough")
    )
    suspicious_funding_amount_aligned = _truthy(
        _lookup(row, "suspiciousFundingAmountAligned", "suspicious_funding_amount_aligned")
    )
    suspicious_funding_trace_succeeded = _normalize_label(
        _string_value(row, "suspiciousFundingTraceSucceeded", "suspicious_funding_trace_succeeded")
    )
    repricing_quality = _normalize_label(
        _string_value(row, "repricingSourceQuality", "repricing_source_quality")
    )
    candidate_admission_reasons = [
        _normalize_label(value)
        for value in _listish(_lookup(row, "candidateAdmissionReason", "candidate_admission_reason"))
        if _normalize_label(value)
    ]
    candidate_admission_reason = next(
        (value for value in candidate_admission_reasons if value != "none"),
        candidate_admission_reasons[0] if candidate_admission_reasons else "",
    )
    candidate_admission_stages = [
        _normalize_label(value)
        for value in _listish(_lookup(row, "candidateAdmissionStage", "candidate_admission_stage"))
        if _normalize_label(value)
    ]
    candidate_admission_stage = next(
        (value for value in candidate_admission_stages if value.startswith("pre_admitted")),
        candidate_admission_stages[0] if candidate_admission_stages else "",
    )
    candidate_admission_sources = _dedupe(
        [
            _normalize_source(source)
            for source in _listish(
                _lookup(
                    row,
                    "candidateAdmissionEvidenceSources",
                    "candidate_admission_evidence_sources",
                )
            )
            if source
        ]
    )
    candidate_independent_sources = [
        source for source in candidate_admission_sources if _is_independent_hard_source(source)
    ]
    grouped_candidate_id = _string_value(row, "groupedCandidateId", "grouped_candidate_id")
    grouped_candidate_grades = [
        _normalize_label(value)
        for value in _listish(_lookup(row, "groupedCandidateFundingGrade", "grouped_candidate_funding_grade"))
        if _normalize_label(value)
    ]
    grouped_candidate_funding_grade = next(
        (value for value in grouped_candidate_grades if value != "unknown"),
        grouped_candidate_grades[0] if grouped_candidate_grades else "",
    )
    grouped_candidate_proxy_only = _truthy(
        _lookup(row, "groupedCandidateProxyOnly", "grouped_candidate_proxy_only")
    )
    near_miss_candidate = candidate_admission_stage.startswith("pre_admission_near_miss")
    pre_admitted = bool(
        not near_miss_candidate
        and (
            candidate_admission_reason
            or candidate_admission_stage.startswith("pre_admitted")
        )
    )
    grouped_pre_admitted = bool(
        pre_admitted
        and (
            grouped_candidate_id
            or candidate_admission_reason in {"strict_shared_funding_group", "split_wallet_group"}
        )
    )

    source_flags = _listish(
        _lookup(
            row,
            "eventForensicFlags",
            "event_forensic_flags",
            "walletEvidenceSourceFlags",
            "wallet_evidence_source_flags",
            "sourceFlags",
            "source_flags",
            "flags",
        )
    )
    source_details = _listish(
        _lookup(
            row,
            "walletHardEvidenceSourceDetails",
            "wallet_hard_evidence_source_details",
            "walletEvidenceSourceDetails",
            "wallet_evidence_source_details",
            "sourceDetails",
            "source_details",
        )
    )

    suppressors = _detect_suppressors(row)
    funding_fields_present = _has_meaningful_signal(row, FUNDING_SIGNAL_KEYS)
    repricing_fields_present = _has_meaningful_signal(row, REPRICING_SIGNAL_KEYS) or _has_repricing_flag(
        source_flags + source_details
    )
    resolver_available = _boolish_or_none(
        _lookup(row, "fundingResolverAvailable", "funding_resolver_available")
    )
    resolver_auth_error = _truthy(_lookup(row, "fundingResolverAuthError", "funding_resolver_auth_error"))
    resolver_disabled_reason = _string_value(
        row,
        "fundingResolverDisabledReason",
        "funding_resolver_disabled_reason",
    )
    resolver_unavailable_reason = _string_value(
        row,
        "fundingResolverUnavailableReason",
        "funding_resolver_unavailable_reason",
    )
    resolver_functional_status = _string_value(
        row,
        "fundingResolverFunctionalStatus",
        "funding_resolver_functional_status",
    )
    resolver_last_error = _string_value(row, "fundingResolverLastError", "funding_resolver_last_error")
    trace_attempted = int(_number(_lookup(row, "fundingTraceAttemptedCount", "funding_trace_attempted_count")) or 0)
    trace_succeeded = int(_number(_lookup(row, "fundingTraceSucceededCount", "funding_trace_succeeded_count")) or 0)
    trace_coverage = _number(_lookup(row, "fundingTraceCoverageRatio", "funding_trace_coverage_ratio"))
    persistent_cache_enabled_present = _has_key(row, "fundingTracePersistentCacheEnabled") or _has_key(
        row,
        "funding_trace_persistent_cache_enabled",
    )
    persistent_cache_enabled = _truthy(
        _lookup(row, "fundingTracePersistentCacheEnabled", "funding_trace_persistent_cache_enabled")
    )
    persistent_cache_hit_count = int(
        _number(_lookup(row, "fundingTracePersistentCacheHitCount", "funding_trace_persistent_cache_hit_count")) or 0
    )
    persistent_cache_miss_count = int(
        _number(_lookup(row, "fundingTracePersistentCacheMissCount", "funding_trace_persistent_cache_miss_count")) or 0
    )
    persistent_cache_write_count = int(
        _number(_lookup(row, "fundingTracePersistentCacheWriteCount", "funding_trace_persistent_cache_write_count")) or 0
    )
    persistent_cache_expired_count = int(
        _number(_lookup(row, "fundingTracePersistentCacheExpiredCount", "funding_trace_persistent_cache_expired_count")) or 0
    )
    persistent_cache_failure_cooldown_count = int(
        _number(
            _lookup(
                row,
                "fundingTracePersistentCacheFailureCooldownCount",
                "funding_trace_persistent_cache_failure_cooldown_count",
            )
        )
        or 0
    )
    persistent_cache_schema_version = int(
        _number(_lookup(row, "fundingTracePersistentCacheSchemaVersion", "funding_trace_persistent_cache_schema_version")) or 0
    )
    funding_from_persistent_cache = _truthy(
        _lookup(row, "fundingTraceFromPersistentCache", "funding_trace_from_persistent_cache")
    )
    persistent_cache_status = _normalize_label(
        _string_value(row, "fundingTracePersistentCacheStatus", "funding_trace_persistent_cache_status")
    )

    opening_exposure_confirmed = _truthy(
        _lookup(row, "opening_exposure_flag", "openingExposureFlag", "openingExposure")
    )
    if not opening_exposure_confirmed:
        opening_entry_count = _number(_lookup(row, "walletOpeningEntryCount", "openingEntryCount"))
        opening_exposure_confirmed = bool(opening_entry_count is not None and opening_entry_count > 0)
    score = _score_value(row)

    strong_risk = _is_strong_risk(severity, existing_model_class, judgment)
    gate_fields_present = _strong_gate_fields_present(row, existing_model_class, judgment)
    strong_gate_apparent = _strong_gate_apparent(row, existing_model_class, judgment)

    schema_has_new_fields = any(_has_key(row, key) for key in NEW_SCHEMA_KEYS)
    independent_hard_sources = [
        source for source in hard_sources if _is_independent_hard_source(source)
    ]
    non_funding_independent_hard_sources = [
        source for source in independent_hard_sources if source != "suspicious_recent_funding"
    ]
    suspicious_funding_only_hard_review = bool(
        hard_evidence_review
        and hard_sources
        and set(hard_sources) == {"suspicious_recent_funding"}
    )
    high_impact_present = _has_high_impact_source(
        hard_sources + source_flags + source_details + candidate_admission_sources + [candidate_admission_reason]
    )
    proxy_funding_present = _proxy_funding_present(row, funding_grade)
    strict_funding_present = _strict_funding_present(row, funding_grade)
    raw_independent_support_sources = _raw_independent_support_sources(
        row,
        hard_sources=hard_sources,
        source_flags=source_flags,
        source_details=source_details,
        suspicious_support_sources=suspicious_funding_independent_support_sources,
        proxy_funding_present=proxy_funding_present,
        opening_exposure_confirmed=opening_exposure_confirmed,
    )
    strong_attribution = _strong_risk_attribution_from_row(
        row,
        strong_risk=strong_risk,
        gate_fields_present=gate_fields_present,
        schema_has_new_fields=schema_has_new_fields,
        hard_sources=hard_sources,
        suppressors=suppressors,
        raw_independent_support_sources=raw_independent_support_sources,
        high_impact_present=high_impact_present,
        opening_exposure_confirmed=opening_exposure_confirmed,
        repricing_quality=repricing_quality or "unknown",
        funding_grade=funding_grade or "unknown",
        score=score,
        existing_model_class=existing_model_class,
        judgment=judgment,
    )
    visible = _visible_row(
        hard_evidence_review=hard_evidence_review,
        strong_risk=strong_risk,
        severity=severity,
        visibility_tier=visibility_tier,
        row=row,
    )

    return {
        "source_path": _string_value(row, "_audit_source_path"),
        "source_row": _string_value(row, "_audit_source_row"),
        "row_id": _row_id(row),
        "wallet": _string_value(row, "wallet", "walletAddress", "wallet_address", "username"),
        "condition_id": _string_value(row, "conditionId", "condition_id"),
        "market_title": _string_value(row, "market", "market_title", "marketTitle", "title"),
        "reasons_against": _listish(_lookup(row, "reducesConcern", "reasonsAgainst", "reasons_against")),
        "severity": severity or "unknown",
        "judgment": judgment or "unknown",
        "score": score,
        "score_bucket": _score_bucket(score),
        "visible": visible,
        "strong_risk": strong_risk,
        "gate_fields_present": gate_fields_present,
        "strong_gate_apparent": strong_gate_apparent,
        "hard_evidence_review": hard_evidence_review,
        "hard_evidence_review_tier": hard_tier,
        "hard_evidence_sources": hard_sources,
        "hard_evidence_strength": hard_strength or "unknown",
        "funding_evidence_grade": funding_grade or "unknown",
        "funding_grade_field_present": funding_grade_field_present,
        "suspicious_funding_quality": suspicious_funding_quality,
        "suspicious_funding_hard_eligible": suspicious_funding_hard_eligible,
        "suspicious_funding_independent_support": suspicious_funding_independent_support,
        "suspicious_funding_independent_support_sources": suspicious_funding_independent_support_sources,
        "suspicious_funding_suppressor_conflict": suspicious_funding_suppressor_conflict,
        "suspicious_funding_suppressor_conflict_reasons": suspicious_funding_suppressor_conflict_reasons,
        "suspicious_funding_recent_enough": suspicious_funding_recent_enough,
        "suspicious_funding_amount_aligned": suspicious_funding_amount_aligned,
        "suspicious_funding_trace_succeeded": suspicious_funding_trace_succeeded or "unknown",
        "repricing_source_quality": repricing_quality or "unknown",
        "candidate_admission_reason": candidate_admission_reason or "none",
        "candidate_admission_stage": candidate_admission_stage or "unknown",
        "candidate_admission_sources": candidate_admission_sources,
        "candidate_independent_sources": candidate_independent_sources,
        "candidate_admission_opening_validated": _truthy(
            _lookup(row, "candidateAdmissionValidatedOpeningExposure", "candidate_admission_validated_opening_exposure")
        ),
        "opening_exposure_confirmed": opening_exposure_confirmed,
        "pre_admitted": pre_admitted,
        "near_miss_candidate": near_miss_candidate,
        "grouped_pre_admitted": grouped_pre_admitted,
        "grouped_candidate_id": grouped_candidate_id,
        "grouped_candidate_funding_grade": grouped_candidate_funding_grade or "unknown",
        "grouped_candidate_proxy_only": grouped_candidate_proxy_only,
        "suppressors": suppressors,
        "funding_fields_present": funding_fields_present,
        "funding_resolver_available": resolver_available,
        "funding_resolver_unavailable": resolver_available is False and resolver_functional_status != "not_assessed",
        "funding_resolver_auth_error": resolver_auth_error,
        "funding_resolver_unavailable_reason": resolver_unavailable_reason,
        "funding_resolver_functional_status": resolver_functional_status,
        "funding_resolver_disabled_reason": resolver_disabled_reason,
        "funding_resolver_last_error": resolver_last_error,
        "funding_trace_attempted_count": trace_attempted,
        "funding_trace_succeeded_count": trace_succeeded,
        "funding_trace_coverage_ratio": trace_coverage if trace_coverage is not None else 0.0,
        "funding_trace_persistent_cache_enabled": persistent_cache_enabled,
        "funding_trace_persistent_cache_enabled_present": persistent_cache_enabled_present,
        "funding_trace_persistent_cache_hit_count": persistent_cache_hit_count,
        "funding_trace_persistent_cache_miss_count": persistent_cache_miss_count,
        "funding_trace_persistent_cache_write_count": persistent_cache_write_count,
        "funding_trace_persistent_cache_expired_count": persistent_cache_expired_count,
        "funding_trace_persistent_cache_failure_cooldown_count": persistent_cache_failure_cooldown_count,
        "funding_trace_persistent_cache_schema_version": persistent_cache_schema_version,
        "funding_trace_from_persistent_cache": funding_from_persistent_cache,
        "funding_trace_persistent_cache_status": persistent_cache_status,
        "repricing_fields_present": repricing_fields_present,
        "schema_has_new_fields": schema_has_new_fields,
        "independent_hard_sources": independent_hard_sources,
        "non_funding_independent_hard_sources": non_funding_independent_hard_sources,
        "suspicious_funding_only_hard_review": suspicious_funding_only_hard_review,
        "high_impact_repricing_present": high_impact_present,
        "proxy_funding_present": proxy_funding_present,
        "strict_funding_present": strict_funding_present,
        "raw_independent_support_sources": raw_independent_support_sources,
        **strong_attribution,
    }


def audit_records(
    records: Iterable[Mapping[str, Any]],
    *,
    funnels: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized = [normalize_record(record) for record in records]
    warnings: dict[str, dict[str, Any]] = {}

    for record in normalized:
        if record["hard_evidence_review"] and not record["hard_evidence_sources"]:
            _add_warning(
                warnings,
                "missing_hard_evidence_sources",
                "Hard Evidence Review row has no hardEvidenceSources.",
                record,
            )

        if (
            record["hard_evidence_review"]
            and record["proxy_funding_present"]
            and not record["strict_funding_present"]
            and not record["independent_hard_sources"]
        ):
            _add_warning(
                warnings,
                "cex_proxy_only_hard_evidence_review",
                "CEX/bridge proxy-only row is marked Hard Evidence Review.",
                record,
            )
        if (
            record["hard_evidence_review"]
            and record["proxy_funding_present"]
            and not record["strict_funding_present"]
            and set(record["hard_evidence_sources"]).issubset({"suspicious_recent_funding"})
        ):
            _add_warning(
                warnings,
                "cex_bridge_proxy_suspicious_funding_hard_evidence_review",
                "CEX/bridge proxy-only funding is marked Hard Evidence Review via suspicious funding.",
                record,
            )

        if (
            record["suspicious_funding_only_hard_review"]
            and record["suspicious_funding_quality"] == "weak"
            and not record["suspicious_funding_independent_support"]
        ):
            _add_warning(
                warnings,
                "weak_suspicious_funding_only_hard_evidence_review",
                "Weak suspicious funding is the only Hard Evidence Review source without independent support.",
                record,
            )

        if (
            record["hard_evidence_review"]
            and "suspicious_recent_funding" in record["hard_evidence_sources"]
            and record["suspicious_funding_quality"] == "unknown"
        ):
            _add_warning(
                warnings,
                "unknown_suspicious_funding_hard_evidence_review",
                "Unknown suspicious funding quality is marked Hard Evidence Review.",
                record,
            )

        if (
            record["funding_evidence_grade"] == "multi_hop_unknown"
            and record["hard_evidence_strength"] == "Strong"
            and "suspicious_recent_funding" in record["hard_evidence_sources"]
            and (
                record["suspicious_funding_quality"] != "strong"
                or not record["suspicious_funding_recent_enough"]
                or not record["suspicious_funding_amount_aligned"]
                or not record["opening_exposure_confirmed"]
                or not record["suspicious_funding_independent_support"]
            )
        ):
            _add_warning(
                warnings,
                "multi_hop_unknown_mapped_strong_without_quality_support",
                "multi_hop_unknown appears mapped to Strong without amount/time/opening/independent support.",
                record,
            )

        if (
            record["funding_evidence_grade"] == "multi_hop_unknown"
            and record["suspicious_funding_quality"] == "strong"
            and not record["suspicious_funding_independent_support"]
        ):
            _add_warning(
                warnings,
                "multi_hop_unknown_strong_without_independent_support",
                "multi_hop_unknown is classified strong without independent structural support.",
                record,
            )

        if (
            record["hard_evidence_review"]
            and record["funding_evidence_grade"] == "multi_hop_unknown"
            and "suspicious_recent_funding" in record["hard_evidence_sources"]
            and not record["suspicious_funding_independent_support"]
        ):
            _add_warning(
                warnings,
                "multi_hop_unknown_hard_evidence_without_independent_support",
                "multi_hop_unknown suspicious funding is marked Hard Evidence Review without independent support.",
                record,
            )

        if (
            record["suspicious_funding_only_hard_review"]
            and (
                record["suspicious_funding_suppressor_conflict"]
                or record["suspicious_funding_suppressor_conflict_reasons"]
                or record["suppressors"]
            )
            and not record["suspicious_funding_independent_support"]
        ):
            _add_warning(
                warnings,
                "suspicious_funding_only_suppressor_conflict",
                "Suspicious-funding-only Hard Evidence Review has suppressor conflicts and no independent support.",
                record,
            )

        expected_suspicious_funding_suppressors = {
            code
            for code in record["suppressors"]
            if code
            in {
                "near_certainty",
                "yield_farm",
                "theta_decay",
                "stale_or_resolution_gap",
                "hard_resolution_gap",
                "bot_like_execution",
                "low_analyst_value_wallet",
                "high_volume_public_user",
            }
        }
        if "domain_specialist" in record["suppressors"] and not record["suspicious_funding_independent_support"]:
            expected_suspicious_funding_suppressors.add("domain_specialist")
        if (
            record["funding_evidence_grade"] in {"suspicious_direct", "multi_hop_unknown"}
            and expected_suspicious_funding_suppressors
            and record["suspicious_funding_quality"] in {"strong", "moderate", "weak"}
            and not record["suspicious_funding_suppressor_conflict"]
        ):
            _add_warning(
                warnings,
                "suspicious_funding_suppressor_conflict_missing",
                "suspiciousFundingSuppressorConflict is false while suppressor flags are present.",
                record,
            )

        if (
            record["suspicious_funding_independent_support"]
            and not record["suspicious_funding_independent_support_sources"]
        ):
            _add_warning(
                warnings,
                "suspicious_funding_independent_support_missing_sources",
                "suspiciousFundingIndependentSupport is true but no support source is listed.",
                record,
            )

        if (
            record["funding_evidence_grade"] == "unknown"
            and record["suspicious_funding_quality"] != "unknown"
        ):
            _add_warning(
                warnings,
                "funding_unknown_quality_not_unknown",
                "fundingEvidenceGrade is unknown but suspiciousFundingQuality is not unknown.",
                record,
            )

        if (
            record["hard_evidence_review"]
            and record["high_impact_repricing_present"]
            and not record["independent_hard_sources"]
        ):
            _add_warning(
                warnings,
                "high_impact_repricing_only_hard_evidence_review",
                "High-impact repricing-only row is marked Hard Evidence Review.",
                record,
            )

        if (
            record["hard_evidence_review"]
            and record["repricing_source_quality"] == REPRICING_SOURCE_QUALITY_MECHANICAL
            and (
                record["high_impact_repricing_present"]
                or not record["independent_hard_sources"]
            )
        ):
            _add_warning(
                warnings,
                "mechanical_repricing_marked_hard_evidence",
                "Mechanical repricing appears to be treated as hard evidence.",
                record,
            )

        if (
            record["strong_risk"]
            and record["gate_fields_present"]
            and not record["strong_gate_apparent"]
        ):
            _add_warning(
                warnings,
                "strong_risk_without_existing_gate",
                "Strong Risk row lacks saved fields indicating an existing Strong Risk gate.",
                record,
            )

        if record["strong_risk"] and not record["strong_risk_gate_evidence_sources"]:
            _add_warning(
                warnings,
                "strong_risk_no_gate_evidence_sources",
                "Strong Risk row has no gate evidence sources.",
                record,
            )

        if (
            record["strong_risk"]
            and record["schema_has_new_fields"]
            and not record["strong_risk_exact_gate_branch_present"]
        ):
            _add_warning(
                warnings,
                "new_format_strong_risk_missing_exact_gate_branch",
                "New-format Strong Risk row lacks strongRiskExactGateBranch.",
                record,
            )

        if (
            record["strong_risk"]
            and record["strong_risk_exact_gate_branch"] == "structure_led_gate"
            and not record["strong_risk_structural_sources_resolved"]
        ):
            _add_warning(
                warnings,
                "exact_structure_gate_missing_structural_sources",
                "Exact structure-led Strong Risk gate has no resolved structural sources.",
                record,
            )

        if (
            record["strong_risk"]
            and record["strong_risk_source_attribution_issue"] == "hard_evidence_source_missing"
        ):
            _add_warning(
                warnings,
                "structure_led_hard_evidence_source_missing",
                "Structure-led/mixed Strong Risk row has a hard-evidence-eligible source but empty hardEvidenceSources.",
                record,
            )

        if record["strong_risk"] and record["strong_risk_composition_class"] == "score_only":
            _add_warning(
                warnings,
                "strong_risk_score_only",
                "Strong Risk row has no identifiable timing, structural, or retrospective gate source.",
                record,
            )

        if record["strong_risk"] and record["strong_risk_gate_leakage_candidate"]:
            _add_warning(
                warnings,
                "strong_risk_gate_leakage_candidate",
                "Strong Risk row remains a gate leakage candidate after exact provenance.",
                record,
            )

        if (
            record["strong_risk"]
            and record["strong_risk_retrospective_only"]
            and record["strong_risk_live_detectable"]
        ):
            _add_warning(
                warnings,
                "retrospective_strong_risk_marked_live_detectable",
                "Retrospective-only Strong Risk row is marked live-detectable.",
                record,
            )

        if record["strong_risk"] and not record["strong_risk_opening_exposure_confirmed"]:
            _add_warning(
                warnings,
                "strong_risk_opening_exposure_not_confirmed",
                "Strong Risk row does not have confirmed opening exposure.",
                record,
            )

        if (
            record["strong_risk"]
            and record["repricing_source_quality"] in {"weak", "mechanical", "unknown"}
            and "rapid_favorable_repricing" in record["strong_risk_timing_proof_sources"]
            and not record["strong_risk_structural_sources_resolved"]
        ):
            _add_warning(
                warnings,
                "strong_risk_weak_repricing_without_structure",
                "Strong Risk row relies on weak/mechanical/unknown repricing without structural support.",
                record,
            )

        if (
            record["strong_risk"]
            and record["strong_risk_suppressor_conflict"]
            and not record["strong_risk_structural_sources_resolved"]
        ):
            _add_warning(
                warnings,
                "strong_risk_suppressor_conflict_without_structure",
                "Strong Risk row has suppressor conflicts without structural support.",
                record,
            )

        if (
            record["strong_risk"]
            and record["suspicious_funding_only_hard_review"]
        ):
            _add_warning(
                warnings,
                "strong_risk_suspicious_funding_only_after_v2",
                "Strong Risk row appears to use suspicious funding only after v2 routing.",
                record,
            )

        if (
            record["strong_risk"]
            and record["strong_risk_gate_type"] == "retrospective_event_forensic"
            and str(record.get("judgment") or "").startswith("Strong Risk")
            and _normalize_label(record.get("judgment")) not in {"strong_risk_retrospective"}
            and record["source_path"]
            and "event_forensic_outputs" in record["source_path"]
            and _normalize_label(record.get("judgment")) in {"strong_risk_live", "strong_risk_unresolved"}
        ):
            _add_warning(
                warnings,
                "retrospective_strong_risk_in_live_context",
                "Retrospective-only Strong Risk appears in a live/unresolved context.",
                record,
            )

        if (
            record["strong_risk"]
            and not record["hard_evidence_sources"]
            and record["strong_risk_gate_type"] == "structure_led"
        ):
            _add_warning(
                warnings,
                "structure_led_strong_risk_missing_hard_sources",
                "Structure-led Strong Risk row has no hardEvidenceSources.",
                record,
            )

        if record["strong_risk"] and record["strong_risk_exact_inferred_gate_disagree"]:
            _add_warning(
                warnings,
                "strong_risk_exact_inferred_gate_disagree",
                "Exact Strong Risk gate branch disagrees with inferred gate type.",
                record,
            )

        if (
            record["strong_risk"]
            and record["schema_has_new_fields"]
            and record["strong_risk_gate_type"] == "legacy_unknown"
        ):
            _add_warning(
                warnings,
                "new_format_strong_risk_legacy_unknown_gate",
                "New-format Strong Risk row has legacy_unknown gate attribution.",
                record,
            )

        if (
            record["funding_fields_present"]
            and record["funding_evidence_grade"] == "unknown"
            and not record["funding_grade_field_present"]
        ):
            _add_warning(
                warnings,
                "missing_funding_evidence_grade",
                "Funding fields are present but fundingEvidenceGrade is missing.",
                record,
            )

        if record["funding_resolver_unavailable"] and record["funding_evidence_grade"] == "none":
            _add_warning(
                warnings,
                "funding_none_with_resolver_unavailable",
                "fundingEvidenceGrade is none while funding resolver is unavailable.",
                record,
            )

        if record["funding_trace_attempted_count"] > 0 and record["funding_trace_coverage_ratio"] == 0 and record["funding_evidence_grade"] == "none":
            _add_warning(
                warnings,
                "funding_none_with_zero_trace_coverage",
                "fundingEvidenceGrade is none while funding trace coverage is zero.",
                record,
            )

        if (
            record["funding_trace_from_persistent_cache"]
            and record["funding_trace_persistent_cache_status"] == "failure"
            and record["funding_evidence_grade"] != "unknown"
        ):
            _add_warning(
                warnings,
                "cached_failure_used_as_funding_evidence",
                "Cached failure/cooldown metadata is being used as funding evidence.",
                record,
            )

        if (
            record["funding_trace_from_persistent_cache"]
            and record["funding_trace_persistent_cache_status"] == "failure"
            and record["funding_evidence_grade"] == "none"
        ):
            _add_warning(
                warnings,
                "cached_unknown_used_as_none",
                "Cached unknown/failure funding state is represented as none.",
                record,
            )

        if (
            record["schema_has_new_fields"]
            and record["funding_trace_persistent_cache_enabled_present"]
            and not record["funding_trace_persistent_cache_enabled"]
            and record["funding_trace_attempted_count"] > 0
        ):
            _add_warning(
                warnings,
                "persistent_cache_disabled_fresh_validation",
                "Persistent funding trace cache is disabled while funding traces are attempted.",
                record,
            )

        if record["funding_resolver_unavailable"] and not record["funding_resolver_disabled_reason"]:
            _add_warning(
                warnings,
                "missing_resolver_disabled_reason",
                "Funding resolver is unavailable but no disabled reason is saved.",
                record,
            )

        if record["repricing_fields_present"] and record["repricing_source_quality"] == "unknown":
            _add_warning(
                warnings,
                "missing_repricing_source_quality",
                "Repricing fields are present but repricingSourceQuality is missing.",
                record,
            )

        if record["pre_admitted"] and record["candidate_admission_reason"] == "none":
            _add_warning(
                warnings,
                "missing_candidate_admission_reason",
                "Pre-admitted row is missing candidateAdmissionReason.",
                record,
            )

        if record["grouped_pre_admitted"] and not record["grouped_candidate_id"]:
            _add_warning(
                warnings,
                "missing_grouped_candidate_id",
                "Grouped pre-admitted row is missing groupedCandidateId.",
                record,
            )

        if (
            record["grouped_candidate_proxy_only"]
            and record["hard_evidence_review"]
        ):
            _add_warning(
                warnings,
                "proxy_only_grouped_admission_hard_evidence_review",
                "Proxy-only grouped admission is surfaced as Hard Evidence Review.",
                record,
            )

        if (
            record["grouped_candidate_proxy_only"]
            and record["candidate_admission_reason"] == "strict_shared_funding_group"
        ):
            _add_warning(
                warnings,
                "proxy_only_group_claims_strict_funding",
                "Proxy-only grouped admission claims strict shared funding.",
                record,
            )

        if (
            record["pre_admitted"]
            and record["high_impact_repricing_present"]
            and not record["candidate_independent_sources"]
            and not record["independent_hard_sources"]
        ):
            _add_warning(
                warnings,
                "high_impact_repricing_only_pre_admission",
                "High-impact repricing-only row was pre-admitted.",
                record,
            )

        if record["pre_admitted"] and record["repricing_source_quality"] == REPRICING_SOURCE_QUALITY_MECHANICAL:
            _add_warning(
                warnings,
                "mechanical_repricing_pre_admission",
                "Mechanical repricing row was pre-admitted.",
                record,
            )

        if (
            record["pre_admitted"]
            and any(code in record["suppressors"] for code in ("near_certainty", "yield_farm", "theta_decay", "stale_or_resolution_gap"))
            and not record["candidate_independent_sources"]
            and not record["independent_hard_sources"]
        ):
            _add_warning(
                warnings,
                "suppressed_context_only_pre_admission",
                "Near-certainty/yield/theta/stale-only row was pre-admitted without structural admission evidence.",
                record,
            )

        if (
            record["pre_admitted"]
            and record["candidate_admission_reason"] in {"strict_shared_funding_group", "split_wallet_group"}
            and record["grouped_candidate_funding_grade"] == "unknown"
        ):
            _add_warning(
                warnings,
                "unknown_funding_grade_grouped_admission",
                "Grouped pre-admission has unknown fundingEvidenceGrade.",
                record,
            )

        if (
            record["pre_admitted"]
            and record["candidate_admission_reason"] in {"strict_shared_funding_group", "split_wallet_group"}
            and record["funding_resolver_unavailable"]
        ):
            _add_warning(
                warnings,
                "strict_funding_admission_with_resolver_unavailable",
                "Strict funding admission is present while funding resolver is unavailable.",
                record,
            )

        if (
            record["pre_admitted"]
            and record["candidate_admission_reason"] in {"strict_shared_funding_group", "split_wallet_group"}
            and record["funding_trace_attempted_count"] > 0
            and record["funding_trace_coverage_ratio"] == 0
        ):
            _add_warning(
                warnings,
                "strict_funding_admission_zero_trace_coverage",
                "Strict funding admission is present while funding trace coverage is zero.",
                record,
            )

        if (
            record["hard_evidence_review"]
            and "strict_shared_funding_source" in record["independent_hard_sources"]
            and record["funding_resolver_unavailable"]
        ):
            _add_warning(
                warnings,
                "funding_hard_evidence_with_resolver_unavailable",
                "Hard Evidence Review uses funding evidence while funding resolver is unavailable.",
                record,
            )

        if (
            record["pre_admitted"]
            and record["candidate_admission_stage"] == "pre_admitted_validated"
            and not (record["candidate_admission_opening_validated"] or record["opening_exposure_confirmed"])
        ):
            _add_warning(
                warnings,
                "validated_admission_missing_opening_exposure_confirmation",
                "Validated pre-admission is missing opening-exposure confirmation.",
                record,
            )

        if record["pre_admitted"]:
            reason = record["candidate_admission_reason"]
            sources = set(record["candidate_admission_sources"])
            if reason == "event_family_repeat" or sources == {"event_family_repeat_narrow_context"}:
                _add_warning(
                    warnings,
                    "event_family_only_pre_admission",
                    "Event-family-only row was pre-admitted.",
                    record,
                )
            if reason == "low_probability_early_winner" or sources == {"low_probability_early_winner"}:
                _add_warning(
                    warnings,
                    "low_probability_winner_only_pre_admission",
                    "Low-probability-winner-only row was pre-admitted.",
                    record,
                )

        if (
            record["schema_has_new_fields"]
            and record["raw_independent_support_sources"]
            and not record["hard_evidence_review"]
            and not record["near_miss_candidate"]
        ):
            _add_warning(
                warnings,
                "independent_evidence_not_routed_hard_evidence_review",
                "Saved fields indicate independent hard evidence, but the row is not routed to Hard Evidence Review.",
                record,
            )

    hard_source_counter: Counter[str] = Counter()
    for record in normalized:
        if record["hard_evidence_sources"]:
            hard_source_counter.update(record["hard_evidence_sources"])
        else:
            hard_source_counter["none"] += 1

    hard_by_severity: Counter[str] = Counter()
    for record in normalized:
        if record["hard_evidence_review"]:
            hard_by_severity[f"{record['severity']} | {record['judgment']}"] += 1

    suppressor_counts = Counter()
    for record in normalized:
        if record["hard_evidence_review"]:
            suppressor_counts.update(record["suppressors"])
    for code in SUPPRESSOR_CODES:
        suppressor_counts.setdefault(code, 0)

    legacy_or_unknown_rows = sum(1 for record in normalized if not record["schema_has_new_fields"])
    strong_gate_unknown_rows = sum(
        1
        for record in normalized
        if record["strong_risk"] and not record["gate_fields_present"]
    )
    pre_admitted_rows = [record for record in normalized if record["pre_admitted"]]
    new_schema_rows = [record for record in normalized if record["schema_has_new_fields"]]
    proxy_only_grouped_admissions = sum(
        1 for record in pre_admitted_rows if record["grouped_candidate_proxy_only"]
    )
    proxy_only_grouped_admissions_hard = sum(
        1
        for record in pre_admitted_rows
        if record["grouped_candidate_proxy_only"] and record["hard_evidence_review"]
    )
    high_impact_pre_admissions = sum(
        1
        for record in pre_admitted_rows
        if record["high_impact_repricing_present"]
        and not record["candidate_independent_sources"]
        and not record["independent_hard_sources"]
    )
    mechanical_pre_admissions = sum(
        1
        for record in pre_admitted_rows
        if record["repricing_source_quality"] == REPRICING_SOURCE_QUALITY_MECHANICAL
    )
    suppressed_context_only_pre_admissions = sum(
        1
        for record in pre_admitted_rows
        if any(code in record["suppressors"] for code in ("near_certainty", "yield_farm", "theta_decay", "stale_or_resolution_gap"))
        and not record["candidate_independent_sources"]
        and not record["independent_hard_sources"]
    )
    suspicious_funding_hard_eligible_count = sum(
        1 for record in normalized if record["suspicious_funding_hard_eligible"]
    )
    suspicious_funding_only_hard_rows = [
        record for record in normalized if record["suspicious_funding_only_hard_review"]
    ]
    suspicious_funding_only_suppressor_rows = [
        record
        for record in suspicious_funding_only_hard_rows
        if record["suspicious_funding_suppressor_conflict"] or record["suppressors"]
    ]
    multi_hop_hard_review_rows = [
        record
        for record in normalized
        if record["funding_evidence_grade"] == "multi_hop_unknown"
        and record["hard_evidence_review"]
        and "suspicious_recent_funding" in record["hard_evidence_sources"]
    ]
    multi_hop_hard_without_support_rows = [
        record
        for record in multi_hop_hard_review_rows
        if not record["suspicious_funding_independent_support"]
    ]
    multi_hop_strong_without_support_rows = [
        record
        for record in normalized
        if record["funding_evidence_grade"] == "multi_hop_unknown"
        and record["suspicious_funding_quality"] == "strong"
        and not record["suspicious_funding_independent_support"]
    ]
    hard_by_suspicious_quality = Counter(
        record["suspicious_funding_quality"]
        for record in normalized
        if record["hard_evidence_review"]
        and "suspicious_recent_funding" in record["hard_evidence_sources"]
    )
    funding_quality_by_grade = Counter(
        f"{record['funding_evidence_grade']} | {record['suspicious_funding_quality']}"
        for record in normalized
    )
    funding_quality_by_judgment = Counter(
        f"{record['severity']} | {record['judgment']} | {record['suspicious_funding_quality']}"
        for record in normalized
    )
    multi_hop_quality = Counter(
        record["suspicious_funding_quality"]
        for record in normalized
        if record["funding_evidence_grade"] == "multi_hop_unknown"
    )
    suppressor_conflict_distribution = Counter(
        "true" if record["suspicious_funding_suppressor_conflict"] else "false"
        for record in normalized
    )
    independent_support_distribution = Counter(
        "true" if record["suspicious_funding_independent_support"] else "false"
        for record in normalized
    )
    hard_by_funding_grade_support = Counter(
        f"{record['funding_evidence_grade']} | independent_support={record['suspicious_funding_independent_support']}"
        for record in normalized
        if record["hard_evidence_review"]
    )
    hard_by_suppressor_conflict = Counter(
        f"suppressor_conflict={record['suspicious_funding_suppressor_conflict']}"
        for record in normalized
        if record["hard_evidence_review"]
    )
    unknown_quality_hard_rows = sum(
        1
        for record in normalized
        if record["suspicious_funding_quality"] == "unknown" and record["hard_evidence_review"]
    )
    hard_review_rows = [record for record in normalized if record["hard_evidence_review"]]
    strong_rows = [record for record in normalized if record["strong_risk"]]
    hard_evidence_pathway_counts = {
        "suspicious_funding_only_hard_evidence_review_rows": len(suspicious_funding_only_hard_rows),
        "suspicious_funding_only_hard_evidence_review_with_suppressors": len(suspicious_funding_only_suppressor_rows),
        "multi_hop_unknown_hard_evidence_review_rows": len(multi_hop_hard_review_rows),
        "multi_hop_unknown_hard_evidence_review_without_independent_support": len(multi_hop_hard_without_support_rows),
        "direct_suspicious_funding_hard_evidence_review_rows": sum(
            1
            for record in hard_review_rows
            if record["funding_evidence_grade"] == "suspicious_direct"
            and "suspicious_recent_funding" in record["hard_evidence_sources"]
        ),
        "split_wallet_hard_evidence_review_rows": _hard_review_source_count(hard_review_rows, "split_wallet_pattern"),
        "strict_shared_funding_hard_evidence_review_rows": _hard_review_source_count(
            hard_review_rows,
            "strict_shared_funding_source",
        ),
        "dormant_reactivation_hard_evidence_review_rows": _hard_review_source_count(
            hard_review_rows,
            "dormant_wallet_reactivation",
        ),
        "low_probability_early_winner_hard_evidence_review_rows": _hard_review_source_count(
            hard_review_rows,
            "low_probability_early_winner",
        ),
        "event_family_repeat_narrow_context_hard_evidence_review_rows": _hard_review_source_count(
            hard_review_rows,
            "event_family_repeat_narrow_context",
        ),
        "high_impact_repricing_only_hard_evidence_review_rows": sum(
            1
            for record in hard_review_rows
            if record["high_impact_repricing_present"] and not record["raw_independent_support_sources"]
        ),
        "cex_bridge_proxy_only_hard_evidence_review_rows": sum(
            1
            for record in hard_review_rows
            if record["proxy_funding_present"]
            and not record["strict_funding_present"]
            and not record["raw_independent_support_sources"]
        ),
        "weak_suspicious_funding_hard_evidence_review_rows": sum(
            1
            for record in hard_review_rows
            if record["suspicious_funding_quality"] == "weak"
            and "suspicious_recent_funding" in record["hard_evidence_sources"]
        ),
        "unknown_suspicious_funding_hard_evidence_review_rows": unknown_quality_hard_rows,
    }

    strong_by_evidence_source: Counter[str] = Counter()
    for record in strong_rows:
        if record["hard_evidence_sources"]:
            strong_by_evidence_source.update(record["hard_evidence_sources"])
        else:
            strong_by_evidence_source["none"] += 1
    strong_suppressors = Counter()
    for record in strong_rows:
        strong_suppressors.update(record["suppressors"])
    for code in SUPPRESSOR_CODES:
        strong_suppressors.setdefault(code, 0)
    strong_rows_driven_by_structure = sum(
        1 for record in strong_rows if record["raw_independent_support_sources"]
    )
    strong_rows_timing_repricing_only = sum(
        1
        for record in strong_rows
        if record["high_impact_repricing_present"]
        and not record["raw_independent_support_sources"]
        and not record["suspicious_funding_hard_eligible"]
    )
    strong_rows_suspicious_funding_only = sum(
        1
        for record in strong_rows
        if (
            set(record["hard_evidence_sources"]) == {"suspicious_recent_funding"}
            or (
                record["suspicious_funding_hard_eligible"]
                and not record["raw_independent_support_sources"]
                and not record["high_impact_repricing_present"]
            )
        )
    )
    strong_gate_type_distribution = Counter(record["strong_risk_gate_type"] for record in strong_rows)
    strong_composition_distribution = Counter(record["strong_risk_composition_class"] for record in strong_rows)
    strong_exact_branch_distribution = Counter(
        record["strong_risk_exact_gate_branch"] for record in strong_rows
    )
    strong_exact_inferred_disagree_rows = [
        record for record in strong_rows if record["strong_risk_exact_inferred_gate_disagree"]
    ]
    strong_exact_missing_rows = [
        record
        for record in strong_rows
        if record["schema_has_new_fields"] and not record["strong_risk_exact_gate_branch_present"]
    ]
    strong_live_detectable_rows = [
        record for record in strong_rows if record["strong_risk_live_detectable"]
    ]
    strong_retrospective_only_rows = [
        record for record in strong_rows if record["strong_risk_retrospective_only"]
    ]
    strong_gate_leakage_rows = [
        record for record in strong_rows if record["strong_risk_gate_leakage_candidate"]
    ]
    strong_structural_empty_hard_rows = [
        record
        for record in strong_rows
        if record["strong_risk_gate_type"] in {"structure_led", "mixed_timing_structure"}
        and not record["hard_evidence_sources"]
    ]
    strong_structural_non_hard_only_rows = [
        record
        for record in strong_structural_empty_hard_rows
        if record["strong_risk_source_attribution_issue"] == "structural_but_not_hard_evidence"
    ]
    strong_structural_missing_hard_source_rows = [
        record
        for record in strong_structural_empty_hard_rows
        if record["strong_risk_source_attribution_issue"] == "hard_evidence_source_missing"
    ]
    strong_rows_no_gate_sources = sum(
        1 for record in strong_rows if not record["strong_risk_gate_evidence_sources"]
    )
    strong_rows_score_only = sum(
        1 for record in strong_rows if record["strong_risk_composition_class"] == "score_only"
    )
    strong_rows_timing_only = sum(
        1
        for record in strong_rows
        if record["strong_risk_gate_type"] == "timing_led"
        and not record["strong_risk_structural_sources_resolved"]
    )
    strong_rows_structure_led = sum(
        1 for record in strong_rows if record["strong_risk_gate_type"] == "structure_led"
    )
    strong_rows_mixed = sum(
        1 for record in strong_rows if record["strong_risk_gate_type"] == "mixed_timing_structure"
    )
    strong_rows_retrospective = sum(
        1 for record in strong_rows if record["strong_risk_gate_type"] == "retrospective_event_forensic"
    )
    strong_rows_suppressor_conflict = sum(
        1 for record in strong_rows if record["strong_risk_suppressor_conflict"]
    )
    strong_rows_suppressor_conflict_no_structure = sum(
        1
        for record in strong_rows
        if record["strong_risk_suppressor_conflict"]
        and not record["strong_risk_structural_sources_resolved"]
    )
    strong_rows_weak_repricing = sum(
        1
        for record in strong_rows
        if record["repricing_source_quality"] in {"weak", "mechanical", "unknown"}
        and "rapid_favorable_repricing" in record["strong_risk_timing_proof_sources"]
        and not record["strong_risk_structural_sources_resolved"]
    )
    strong_top_rows = _strong_risk_top_rows(strong_rows, limit=50)
    strong_risk_composition = {
        "strong_risk_rows_by_gate_type": _counter_dict(strong_gate_type_distribution),
        "strong_risk_rows_by_composition_class": _counter_dict(strong_composition_distribution),
        "strong_risk_rows_by_exact_gate_branch": _counter_dict(strong_exact_branch_distribution),
        "strong_risk_rows_by_source_attribution_issue": _counter_dict(
            Counter(record["strong_risk_source_attribution_issue"] for record in strong_rows)
        ),
        "strong_risk_structural_but_not_hard_evidence_rows": sum(
            1 for record in strong_rows if record["strong_risk_structural_but_not_hard_evidence"]
        ),
        "strong_risk_structural_but_not_hard_evidence_sources": _counter_dict(
            Counter(
                source
                for record in strong_rows
                for source in record["strong_risk_structural_but_not_hard_evidence_sources"]
            )
        ),
        "strong_risk_rows_by_score_only_resolution": _counter_dict(
            Counter(record["strong_risk_score_only_resolution"] for record in strong_rows)
        ),
        "strong_risk_rows_by_evidence_source": _counter_dict(strong_by_evidence_source),
        "strong_risk_rows_by_score_judgment_severity": _counter_dict(
            Counter(
                f"{record['score_bucket']} | {record['severity']} | {record['judgment']}"
                for record in strong_rows
            )
        ),
        "strong_risk_rows_with_no_hard_evidence_sources": sum(
            1 for record in strong_rows if not record["hard_evidence_sources"]
        ),
        "strong_risk_rows_with_no_gate_evidence_sources": strong_rows_no_gate_sources,
        "strong_risk_score_only_rows": strong_rows_score_only,
        "strong_risk_score_only_after_exact_provenance_rows": sum(
            1
            for record in strong_rows
            if record["strong_risk_score_only_resolution"] == "actual_score_only_gate_leakage_candidate"
        ),
        "strong_risk_gate_leakage_candidate_rows": len(strong_gate_leakage_rows),
        "strong_risk_new_format_missing_exact_gate_branch_rows": len(strong_exact_missing_rows),
        "strong_risk_exact_inferred_gate_disagree_rows": len(strong_exact_inferred_disagree_rows),
        "strong_risk_live_detectable_rows": len(strong_live_detectable_rows),
        "strong_risk_retrospective_only_rows_exact": len(strong_retrospective_only_rows),
        "strong_risk_timing_only_rows": strong_rows_timing_only,
        "strong_risk_structure_led_rows": strong_rows_structure_led,
        "strong_risk_mixed_timing_structure_rows": strong_rows_mixed,
        "strong_risk_retrospective_only_rows": strong_rows_retrospective,
        "strong_risk_suppressor_conflict_rows": strong_rows_suppressor_conflict,
        "strong_risk_suppressor_conflict_without_structure_rows": strong_rows_suppressor_conflict_no_structure,
        "strong_risk_weak_mechanical_unknown_repricing_rows": strong_rows_weak_repricing,
        "strong_risk_rows_with_suppressors": _counter_dict(strong_suppressors),
        "strong_risk_rows_driven_by_timing_repricing_only": strong_rows_timing_repricing_only,
        "strong_risk_rows_driven_by_suspicious_funding_only": strong_rows_suspicious_funding_only,
        "strong_risk_rows_driven_by_structure": strong_rows_driven_by_structure,
        "strong_risk_rows_opening_exposure_not_confirmed": sum(
            1 for record in strong_rows if not record["opening_exposure_confirmed"]
        ),
        "strong_risk_rows_funding_unknown": sum(
            1 for record in strong_rows if record["funding_evidence_grade"] == "unknown"
        ),
        "strong_risk_rows_repricing_unknown": sum(
            1 for record in strong_rows if record["repricing_source_quality"] == "unknown"
        ),
        "top_strong_risk_rows": strong_top_rows,
    }
    strong_no_hard_rows = [record for record in strong_rows if not record["hard_evidence_sources"]]
    strong_risk_deep_dive = {
        "no_hard_evidence_rows_by_gate_type": _counter_dict(
            Counter(record["strong_risk_gate_type"] for record in strong_no_hard_rows)
        ),
        "no_hard_evidence_rows_by_composition_class": _counter_dict(
            Counter(record["strong_risk_composition_class"] for record in strong_no_hard_rows)
        ),
        "confirmed_opening_exposure_rows": sum(
            1 for record in strong_rows if record["strong_risk_opening_exposure_confirmed"]
        ),
        "strong_timing_proof_rows": sum(
            1 for record in strong_rows if record["strong_risk_timing_proof_count"] > 0
        ),
        "repricing_dependent_rows": sum(
            1
            for record in strong_rows
            if "rapid_favorable_repricing" in record["strong_risk_timing_proof_sources"]
        ),
        "weak_mechanical_unknown_repricing_rows": strong_rows_weak_repricing,
        "suppressor_conflict_rows": strong_rows_suppressor_conflict,
        "high_volume_bot_stale_specialist_without_structure_rows": sum(
            1
            for record in strong_rows
            if not record["strong_risk_structural_sources"]
            and any(
                code in record["strong_risk_suppressor_conflict_reasons"]
                for code in {
                    "bot_like_execution",
                    "high_volume_public_user",
                    "stale_or_resolution_gap",
                    "domain_specialist",
                }
            )
        ),
        "credible_if_timing_repricing_advisory_only_rows": sum(
            1
            for record in strong_rows
            if record["strong_risk_structural_sources"]
            or record["strong_risk_gate_type"] == "retrospective_event_forensic"
        ),
        "hard_sources_missing_because_schema_propagation_rows": sum(
            1
            for record in strong_no_hard_rows
            if record["strong_risk_structural_sources"]
        ),
        "hard_sources_missing_because_no_structural_evidence_rows": sum(
            1
            for record in strong_no_hard_rows
            if not record["strong_risk_structural_sources"]
        ),
        "possible_strong_risk_gate_leakage_rows": (
            len(strong_gate_leakage_rows)
            + sum(1 for record in strong_rows if not record["strong_risk_opening_exposure_confirmed"])
        ),
        "live_detectable_strong_risk_rows": len(strong_live_detectable_rows),
        "retrospective_only_strong_risk_rows": len(strong_retrospective_only_rows),
        "exact_gate_branch_distribution": _counter_dict(strong_exact_branch_distribution),
        "inferred_gate_type_distribution": _counter_dict(strong_gate_type_distribution),
        "exact_inferred_gate_disagree_rows": len(strong_exact_inferred_disagree_rows),
        "exact_gate_branch_missing_rows": len(strong_exact_missing_rows),
        "score_only_after_exact_provenance_rows": strong_risk_composition.get(
            "strong_risk_score_only_after_exact_provenance_rows",
            0,
        ),
        "gate_leakage_candidate_rows": len(strong_gate_leakage_rows),
        "structural_mixed_empty_hard_sources_by_issue": _counter_dict(
            Counter(record["strong_risk_source_attribution_issue"] for record in strong_structural_empty_hard_rows)
        ),
        "structural_rows_with_non_hard_structural_sources_only": len(strong_structural_non_hard_only_rows),
        "structural_rows_with_missing_independent_hard_evidence_source": len(
            strong_structural_missing_hard_source_rows
        ),
        "retrospective_rows_incorrectly_live_detectable": sum(
            1 for record in strong_rows if record["strong_risk_retrospective_only"] and record["strong_risk_live_detectable"]
        ),
        "suppressor_conflict_without_structural_support_rows": strong_rows_suppressor_conflict_no_structure,
        "timing_led_weak_repricing_without_structural_support_rows": strong_rows_weak_repricing,
        "structural_mixed_empty_hard_sources_rows": _example_records(strong_structural_empty_hard_rows, limit=50),
        "gate_leakage_candidate_examples": _example_records(strong_gate_leakage_rows, limit=50),
        "top_strong_risk_rows": strong_top_rows,
    }

    raw_independent_source_counter = Counter()
    for record in normalized:
        raw_independent_source_counter.update(record["raw_independent_support_sources"])
    new_format_independent_rows = [
        record
        for record in normalized
        if record["schema_has_new_fields"] and record["raw_independent_support_sources"]
    ]
    legacy_independent_rows = [
        record
        for record in normalized
        if not record["schema_has_new_fields"] and record["raw_independent_support_sources"]
    ]
    independent_not_routed_rows = [
        record
        for record in normalized
        if record["schema_has_new_fields"]
        and record["raw_independent_support_sources"]
        and not record["hard_evidence_review"]
        and not record["near_miss_candidate"]
    ]
    normal_candidate_independent_not_hard_rows = [
        record
        for record in independent_not_routed_rows
        if record["candidate_admission_stage"] == "normal_candidate"
    ]
    hard_sources_none_raw_support_rows = [
        record
        for record in normalized
        if record["schema_has_new_fields"]
        and not record["hard_evidence_sources"]
        and record["raw_independent_support_sources"]
    ]
    suspicious_funding_rows = [
        record
        for record in normalized
        if record["funding_evidence_grade"] in {"suspicious_direct", "multi_hop_unknown"}
    ]
    suspicious_funding_removed_reasons = {
        "no_direct_suspicious_funding_rows": 1
        if suspicious_funding_rows
        and not any(record["funding_evidence_grade"] == "suspicious_direct" for record in suspicious_funding_rows)
        else 0,
        "multi_hop_unknown_without_independent_support_rows": sum(
            1
            for record in suspicious_funding_rows
            if record["funding_evidence_grade"] == "multi_hop_unknown"
            and not record["suspicious_funding_independent_support"]
        ),
        "suppressor_conflict_rows": sum(
            1 for record in suspicious_funding_rows if record["suspicious_funding_suppressor_conflict"]
        ),
        "opening_exposure_not_confirmed_rows": sum(
            1 for record in suspicious_funding_rows if not record["opening_exposure_confirmed"]
        ),
        "amount_or_time_alignment_failed_rows": sum(
            1
            for record in suspicious_funding_rows
            if not (record["suspicious_funding_recent_enough"] and record["suspicious_funding_amount_aligned"])
        ),
        "missing_or_unknown_quality_rows": sum(
            1 for record in suspicious_funding_rows if record["suspicious_funding_quality"] == "unknown"
        ),
    }
    hard_evidence_starvation = {
        "independent_hard_evidence_sources_appeared": bool(raw_independent_source_counter),
        "independent_sources_observed": _counter_dict(raw_independent_source_counter),
        "new_format_independent_support_rows": len(new_format_independent_rows),
        "legacy_or_unknown_independent_support_rows": len(legacy_independent_rows),
        "independent_sources_not_routed_to_hard_evidence_review_rows": len(independent_not_routed_rows),
        "normal_candidates_with_independent_support_not_hard_evidence_review": len(
            normal_candidate_independent_not_hard_rows
        ),
        "hard_evidence_sources_none_but_raw_independent_support_rows": len(hard_sources_none_raw_support_rows),
        "v2_suspicious_funding_removal_reasons": suspicious_funding_removed_reasons,
        "suspicious_funding_rows": len(suspicious_funding_rows),
        "suspicious_funding_direct_rows": sum(
            1 for record in suspicious_funding_rows if record["funding_evidence_grade"] == "suspicious_direct"
        ),
        "suspicious_funding_multi_hop_unknown_rows": sum(
            1 for record in suspicious_funding_rows if record["funding_evidence_grade"] == "multi_hop_unknown"
        ),
        "examples_independent_support_not_routed": _example_records(independent_not_routed_rows),
        "examples_hard_sources_none_but_raw_support": _example_records(hard_sources_none_raw_support_rows),
        "examples_legacy_or_unknown_independent_support": _example_records(legacy_independent_rows),
    }
    persistent_cache_hit_rows = sum(1 for record in normalized if record["funding_trace_from_persistent_cache"])
    persistent_cache_hit_count = max(
        (record["funding_trace_persistent_cache_hit_count"] for record in normalized),
        default=0,
    )
    persistent_cache_miss_count = max(
        (record["funding_trace_persistent_cache_miss_count"] for record in normalized),
        default=0,
    )
    persistent_cache_write_count = max(
        (record["funding_trace_persistent_cache_write_count"] for record in normalized),
        default=0,
    )
    persistent_cache_expired_count = max(
        (record["funding_trace_persistent_cache_expired_count"] for record in normalized),
        default=0,
    )
    persistent_cache_failure_cooldown_count = max(
        (record["funding_trace_persistent_cache_failure_cooldown_count"] for record in normalized),
        default=0,
    )
    persistent_cache_denominator = persistent_cache_hit_count + persistent_cache_miss_count
    persistent_cache_hit_rate = (
        persistent_cache_hit_count / persistent_cache_denominator
        if persistent_cache_denominator
        else 0.0
    )
    unknown_after_cache_miss_rows = sum(
        1
        for record in normalized
        if record["funding_evidence_grade"] == "unknown"
        and record["funding_trace_persistent_cache_miss_count"] > 0
        and not record["funding_trace_from_persistent_cache"]
    )
    funnel_summary = _audit_funnels(funnels or [], warnings)

    visible_rows = sum(1 for record in normalized if record["visible"])
    hard_review_count = sum(1 for record in normalized if record["hard_evidence_review"])
    count_hygiene = build_count_hygiene_summary(normalized)
    for warning in count_hygiene_warnings(count_hygiene):
        code = str(warning.get("code") or "")
        item = warnings.setdefault(
            code,
            {
                "code": code,
                "message": "Report count interpretation warning; raw rows should be read with adjacent unique counts.",
                "count": 0,
                "examples": [],
            },
        )
        item["count"] += 1
        if len(item["examples"]) < 5:
            item["examples"].append(dict(warning))
    warning_list = sorted(warnings.values(), key=lambda item: item["code"])
    next_actions = _next_actions(warning_list, legacy_or_unknown_rows)
    large_sample_classification = _classify_large_sample(
        warning_codes={warning["code"] for warning in warning_list},
        funnel_summary=funnel_summary,
        hard_evidence_pathway_counts=hard_evidence_pathway_counts,
        strong_risk_composition=strong_risk_composition,
        hard_evidence_starvation=hard_evidence_starvation,
        strong_risk_rows=len(strong_rows),
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_rows_inspected": len(normalized),
        "event_forensic_rows_inspected": sum(
            1 for record in normalized if "event_forensic_outputs" in record["source_path"]
        ),
        "archive_rows_inspected": sum(
            1 for record in normalized if "archive_outputs" in record["source_path"]
        ),
        "ai_review_rows_inspected": sum(
            1 for record in normalized if "ai_review_outputs" in record["source_path"]
        ),
        "visible_rows": visible_rows,
        "rawVisibleRows": count_hygiene["rawVisibleRows"],
        "uniqueVisibleRows": count_hygiene["uniqueVisibleRows"],
        "visibleDedupeRatio": count_hygiene["visibleDedupeRatio"],
        "strong_risk_rows": sum(1 for record in normalized if record["strong_risk"]),
        "rawStrongRiskRows": count_hygiene["rawStrongRiskRows"],
        "uniqueStrongRiskRows": count_hygiene["uniqueStrongRiskRows"],
        "strongRiskDedupeRatio": count_hygiene["strongRiskDedupeRatio"],
        "hard_evidence_review_rows": hard_review_count,
        "rawHardEvidenceReviewRows": count_hygiene["rawHardEvidenceReviewRows"],
        "uniqueHardEvidenceReviewRows": count_hygiene["uniqueHardEvidenceReviewRows"],
        "hardEvidenceReviewDedupeRatio": count_hygiene["hardEvidenceReviewDedupeRatio"],
        "topDuplicateStrongRiskKeys": count_hygiene["topDuplicateStrongRiskKeys"],
        "topDuplicateHardEvidenceReviewKeys": count_hygiene["topDuplicateHardEvidenceReviewKeys"],
        "topDuplicateTargets": count_hygiene["topDuplicateTargets"],
        "count_hygiene": count_hygiene,
        "hard_evidence_review_share_of_visible_rows": round(
            hard_review_count / visible_rows if visible_rows else 0.0,
            4,
        ),
        "pre_admitted_candidate_rows": len(pre_admitted_rows),
        "normal_candidate_rows": sum(
            1 for record in normalized if record["candidate_admission_stage"] == "normal_candidate"
        ),
        "proxy_only_grouped_admissions": proxy_only_grouped_admissions,
        "proxy_only_grouped_admissions_hard_evidence_review": proxy_only_grouped_admissions_hard,
        "high_impact_repricing_only_pre_admissions": high_impact_pre_admissions,
        "mechanical_repricing_pre_admissions": mechanical_pre_admissions,
        "near_certainty_yield_theta_stale_only_pre_admissions": suppressed_context_only_pre_admissions,
        "suspicious_funding_hard_evidence_eligible_rows": suspicious_funding_hard_eligible_count,
        "suspicious_funding_only_hard_evidence_review_rows": len(suspicious_funding_only_hard_rows),
        "suspicious_funding_only_hard_evidence_review_with_suppressors": len(suspicious_funding_only_suppressor_rows),
        "multi_hop_unknown_hard_evidence_review_rows": len(multi_hop_hard_review_rows),
        "multi_hop_unknown_hard_evidence_review_without_independent_support": len(multi_hop_hard_without_support_rows),
        "multi_hop_unknown_strong_without_independent_support_rows": len(multi_hop_strong_without_support_rows),
        "unknown_suspicious_funding_quality_hard_evidence_review_rows": unknown_quality_hard_rows,
        "funding_trace_persistent_cache_hit_rows": persistent_cache_hit_rows,
        "funding_trace_persistent_cache_hit_count": persistent_cache_hit_count,
        "funding_trace_persistent_cache_miss_count": persistent_cache_miss_count,
        "funding_trace_persistent_cache_write_count": persistent_cache_write_count,
        "funding_trace_persistent_cache_expired_count": persistent_cache_expired_count,
        "funding_trace_persistent_cache_failure_cooldown_count": persistent_cache_failure_cooldown_count,
        "funding_trace_persistent_cache_hit_rate": round(persistent_cache_hit_rate, 4),
        "funding_trace_unknown_after_persistent_cache_miss_rows": unknown_after_cache_miss_rows,
        "pre_admission_funnel": funnel_summary,
        "hard_evidence_pathway_counts": hard_evidence_pathway_counts,
        "strong_risk_composition": strong_risk_composition,
        "strong_risk_deep_dive": strong_risk_deep_dive,
        "hard_evidence_starvation": hard_evidence_starvation,
        "large_sample_classification": large_sample_classification,
        "legacy_or_unknown_schema_rows": legacy_or_unknown_rows,
        "strong_gate_unknown_rows": strong_gate_unknown_rows,
        "distributions": {
            "hardEvidenceSources": _counter_dict(hard_source_counter),
            "hardEvidenceStrength": _counter_dict(
                Counter(record["hard_evidence_strength"] for record in normalized)
            ),
            "fundingEvidenceGrade": _counter_dict(
                Counter(record["funding_evidence_grade"] for record in normalized)
            ),
            "fundingEvidenceGradeIncludingLegacy": _counter_dict(
                Counter(record["funding_evidence_grade"] for record in normalized)
            ),
            "fundingEvidenceGradeExcludingLegacy": _counter_dict(
                Counter(record["funding_evidence_grade"] for record in new_schema_rows)
            ),
            "suspiciousFundingQuality": _counter_dict(
                Counter(record["suspicious_funding_quality"] for record in normalized)
            ),
            "hardEvidenceReviewBySuspiciousFundingQuality": _counter_dict(hard_by_suspicious_quality),
            "fundingQualityByFundingEvidenceGrade": _counter_dict(funding_quality_by_grade),
            "fundingQualityByJudgmentSeverity": _counter_dict(funding_quality_by_judgment),
            "multiHopUnknownBySuspiciousFundingQuality": _counter_dict(multi_hop_quality),
            "suspiciousFundingSuppressorConflict": _counter_dict(suppressor_conflict_distribution),
            "suspiciousFundingIndependentSupport": _counter_dict(independent_support_distribution),
            "hardEvidenceReviewByFundingGradeAndIndependentSupport": _counter_dict(hard_by_funding_grade_support),
            "hardEvidenceReviewBySuppressorConflict": _counter_dict(hard_by_suppressor_conflict),
            "fundingResolverAvailabilityRows": _counter_dict(
                Counter(
                    "unavailable" if record["funding_resolver_available"] is False
                    else "available" if record["funding_resolver_available"] is True
                    else "unknown"
                    for record in normalized
                )
            ),
            "repricingSourceQuality": _counter_dict(
                Counter(record["repricing_source_quality"] for record in normalized)
            ),
            "strongRiskGateType": _counter_dict(
                Counter(record["strong_risk_gate_type"] for record in normalized if record["strong_risk"])
            ),
            "strongRiskCompositionClass": _counter_dict(
                Counter(record["strong_risk_composition_class"] for record in normalized if record["strong_risk"])
            ),
            "strongRiskExactGateBranch": _counter_dict(
                Counter(record["strong_risk_exact_gate_branch"] for record in normalized if record["strong_risk"])
            ),
            "strongRiskSourceAttributionIssue": _counter_dict(
                Counter(record["strong_risk_source_attribution_issue"] for record in normalized if record["strong_risk"])
            ),
            "strongRiskScoreOnlyResolution": _counter_dict(
                Counter(record["strong_risk_score_only_resolution"] for record in normalized if record["strong_risk"])
            ),
            "fundingTracePersistentCacheStatus": _counter_dict(
                Counter(record["funding_trace_persistent_cache_status"] or "none" for record in normalized)
            ),
            "candidateAdmissionReason": _counter_dict(
                Counter(record["candidate_admission_reason"] for record in normalized)
            ),
            "candidateAdmissionStage": _counter_dict(
                Counter(record["candidate_admission_stage"] for record in normalized)
            ),
            "groupedCandidateFundingGrade": _counter_dict(
                Counter(record["grouped_candidate_funding_grade"] for record in normalized)
            ),
        },
        "cross_tabs": {
            "hardEvidenceReview_by_severity_judgment": _counter_dict(hard_by_severity),
        },
        "hard_evidence_review_with_suppressors": _counter_dict(suppressor_counts),
        "invalid_condition_counts": {
            warning["code"]: warning["count"] for warning in warning_list
        },
        "warnings": warning_list,
        "next_actions": next_actions,
    }


def _audit_funnels(
    funnels: list[Mapping[str, Any]],
    warnings: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rejection_reasons: Counter[str] = Counter()
    resolver_availability: Counter[str] = Counter()
    resolver_unavailable_reasons: Counter[str] = Counter()
    resolver_functional_statuses: Counter[str] = Counter()
    total_above_floor = 0
    total_grouped = 0
    total_attempts = 0
    total_validated = 0
    total_rejected_after_scoring = 0
    total_near_miss_groups = 0
    total_unknown = 0
    total_strict_groups = 0
    total_proxy_groups = 0
    total_trace_attempts = 0
    total_trace_succeeded = 0
    total_trace_failed = 0
    total_trace_skipped = 0
    total_pre_trace_attempts = 0
    total_pre_trace_succeeded = 0
    total_pre_trace_failed = 0
    total_pre_trace_skipped = 0
    total_rate_limited = 0
    total_retry_count = 0
    total_fallback_endpoint_count = 0
    total_log_chunks_attempted = 0
    total_log_chunks_succeeded = 0
    total_log_chunks_failed = 0
    total_log_chunks_rate_limited = 0
    total_cache_hit_count = 0
    total_cache_miss_count = 0
    total_persistent_cache_hit_count = 0
    total_persistent_cache_miss_count = 0
    total_persistent_cache_write_count = 0
    total_persistent_cache_expired_count = 0
    total_persistent_cache_failure_cooldown_count = 0
    persistent_cache_enabled_bundle_count = 0
    endpoint_pool_sizes: list[int] = []
    lightweight_available_bundle_count = 0
    funding_trace_available_bundle_count = 0
    rate_limited_bundle_count = 0
    lightweight_available_trace_failed_count = 0
    production_trace_succeeded_bundle_count = 0
    trace_coverage_values: list[float] = []
    auth_error_bundle_count = 0
    resolver_unavailable_runs = 0
    near_miss_funding_not_assessable = 0
    inactive_assessments: Counter[str] = Counter()

    for funnel in funnels:
        counts = funnel.get("counts", {})
        counts = counts if isinstance(counts, Mapping) else {}
        source_record = {
            "source_path": str(funnel.get("_audit_source_path") or ""),
            "source_row": "",
            "row_id": "candidate_admission_funnel",
            "wallet": "",
            "severity": "",
            "judgment": "",
            "hard_evidence_sources": [],
            "funding_evidence_grade": "",
            "repricing_source_quality": "",
            "candidate_admission_reason": "",
            "candidate_admission_stage": "",
            "grouped_candidate_id": "",
        }
        above_floor = _funnel_count(counts, "subThresholdAboveStructuralFloorTrades")
        grouped = _funnel_count(counts, "groupedConditionDirectionGroups")
        attempts = (
            _funnel_count(counts, "groupsAdmittedPendingScoring")
            + _funnel_count(counts, "suspiciousFundingAttempts")
            + _funnel_count(counts, "dormantReactivationAttempts")
        )
        validated = int(_number(funnel.get("validatedPreAdmissionCount")) or 0)
        rejected_after_scoring = int(_number(funnel.get("rejectedAfterScoringCount")) or 0)
        near_misses = int(_number(funnel.get("nearMissGroups")) or 0)
        pre_trace_attempts = int(_number(funnel.get("preAdmissionFundingTraceAttemptedCount")) or 0)
        pre_trace_succeeded = int(_number(funnel.get("preAdmissionFundingTraceSucceededCount")) or 0)
        parsed_pre_trace_failed = _number(funnel.get("preAdmissionFundingTraceFailedCount"))
        pre_trace_failed = (
            int(parsed_pre_trace_failed)
            if parsed_pre_trace_failed is not None
            else max(0, pre_trace_attempts - pre_trace_succeeded)
        )
        pre_trace_skipped = int(_number(funnel.get("preAdmissionFundingTraceSkippedCount")) or 0)
        trace_attempts = int(_number(funnel.get("fundingTraceAttemptedCount")) or pre_trace_attempts)
        trace_succeeded = int(_number(funnel.get("fundingTraceSucceededCount")) or pre_trace_succeeded)
        trace_failed = int(_number(funnel.get("fundingTraceFailedCount")) or pre_trace_failed)
        trace_skipped = int(_number(funnel.get("fundingTraceSkippedCount")) or pre_trace_skipped)
        trace_coverage = _number(funnel.get("fundingTraceCoverageRatio"))
        strict_groups = int(_number(funnel.get("preAdmissionStrictFundingGroupsFound")) or 0)
        proxy_groups = int(_number(funnel.get("preAdmissionProxyOnlyGroupsFound")) or 0)
        unknown_count = int(_number(funnel.get("preAdmissionFundingUnknownCount")) or 0)
        resolver_available = _truthy(funnel.get("fundingResolverAvailable"))
        resolver_auth_error = _truthy(funnel.get("fundingResolverAuthError"))
        resolver_reason = str(funnel.get("fundingResolverDisabledReason") or "").strip()
        resolver_unavailable_reason = str(funnel.get("fundingResolverUnavailableReason") or "").strip()
        functional_status = str(funnel.get("fundingResolverFunctionalStatus") or "").strip() or "unknown"
        endpoint_pool_size = int(_number(funnel.get("fundingTraceEndpointPoolSize")) or 0)
        rate_limited_count = int(_number(funnel.get("fundingTraceRateLimitedCount")) or 0)
        retry_count = int(_number(funnel.get("fundingTraceRetryCount")) or 0)
        fallback_endpoint_count = int(_number(funnel.get("fundingTraceFallbackEndpointCount")) or 0)
        log_chunks_attempted = int(_number(funnel.get("fundingTraceLogChunksAttempted")) or 0)
        log_chunks_succeeded = int(_number(funnel.get("fundingTraceLogChunksSucceeded")) or 0)
        log_chunks_failed = int(_number(funnel.get("fundingTraceLogChunksFailed")) or 0)
        log_chunks_rate_limited = int(_number(funnel.get("fundingTraceLogChunksRateLimited")) or 0)
        cache_hit_count = int(_number(funnel.get("fundingTraceCacheHitCount")) or 0)
        cache_miss_count = int(_number(funnel.get("fundingTraceCacheMissCount")) or 0)
        persistent_cache_enabled = _truthy(funnel.get("fundingTracePersistentCacheEnabled"))
        persistent_cache_hit_count = int(_number(funnel.get("fundingTracePersistentCacheHitCount")) or 0)
        persistent_cache_miss_count = int(_number(funnel.get("fundingTracePersistentCacheMissCount")) or 0)
        persistent_cache_write_count = int(_number(funnel.get("fundingTracePersistentCacheWriteCount")) or 0)
        persistent_cache_expired_count = int(_number(funnel.get("fundingTracePersistentCacheExpiredCount")) or 0)
        persistent_cache_failure_cooldown_count = int(
            _number(funnel.get("fundingTracePersistentCacheFailureCooldownCount")) or 0
        )
        endpoint_summary = funnel.get("fundingTraceEndpointSummary") or []

        total_above_floor += above_floor
        total_grouped += grouped
        total_attempts += attempts
        total_validated += validated
        total_rejected_after_scoring += rejected_after_scoring
        total_near_miss_groups += near_misses
        total_unknown += unknown_count
        total_strict_groups += strict_groups
        total_proxy_groups += proxy_groups
        total_trace_attempts += trace_attempts
        total_trace_succeeded += trace_succeeded
        total_trace_failed += trace_failed
        total_trace_skipped += trace_skipped
        total_pre_trace_attempts += pre_trace_attempts
        total_pre_trace_succeeded += pre_trace_succeeded
        total_pre_trace_failed += pre_trace_failed
        total_pre_trace_skipped += pre_trace_skipped
        total_rate_limited += rate_limited_count
        total_retry_count += retry_count
        total_fallback_endpoint_count += fallback_endpoint_count
        total_log_chunks_attempted += log_chunks_attempted
        total_log_chunks_succeeded += log_chunks_succeeded
        total_log_chunks_failed += log_chunks_failed
        total_log_chunks_rate_limited += log_chunks_rate_limited
        total_cache_hit_count += cache_hit_count
        total_cache_miss_count += cache_miss_count
        total_persistent_cache_hit_count += persistent_cache_hit_count
        total_persistent_cache_miss_count += persistent_cache_miss_count
        total_persistent_cache_write_count += persistent_cache_write_count
        total_persistent_cache_expired_count += persistent_cache_expired_count
        total_persistent_cache_failure_cooldown_count += persistent_cache_failure_cooldown_count
        if persistent_cache_enabled:
            persistent_cache_enabled_bundle_count += 1
        endpoint_pool_sizes.append(endpoint_pool_size)
        if trace_coverage is not None:
            trace_coverage_values.append(trace_coverage)
        resolver_functional_statuses[functional_status] += 1
        resolver_not_assessed = functional_status == "not_assessed" and trace_attempts == 0
        if resolver_available:
            resolver_availability["available"] += 1
        elif resolver_not_assessed:
            resolver_availability["not_assessed"] += 1
        else:
            resolver_availability["unavailable"] += 1
        if functional_status in {"available_lightweight_only", "rate_limited_for_funding_trace", "available_for_funding_trace"}:
            lightweight_available_bundle_count += 1
        if functional_status == "available_for_funding_trace" or trace_succeeded > 0:
            funding_trace_available_bundle_count += 1
        if functional_status == "rate_limited_for_funding_trace" or resolver_unavailable_reason == "rate_limited" or rate_limited_count > 0:
            rate_limited_bundle_count += 1
        if functional_status in {"available_lightweight_only", "rate_limited_for_funding_trace"} and trace_attempts > 0 and trace_succeeded == 0:
            lightweight_available_trace_failed_count += 1
        if trace_succeeded > 0:
            production_trace_succeeded_bundle_count += 1
        if resolver_auth_error:
            auth_error_bundle_count += 1
        if not resolver_available and not resolver_not_assessed:
            resolver_unavailable_runs += 1
            resolver_unavailable_reasons[resolver_unavailable_reason or "unknown"] += 1

        for reason, count in (funnel.get("preAdmissionRejectedReasonDistribution") or {}).items():
            rejection_reasons[str(reason)] += int(count or 0)
        for group in funnel.get("topRejectedGroups") or []:
            if isinstance(group, Mapping):
                reason = str(group.get("candidateAdmissionRejectedReason") or "unknown")
                rejection_reasons[reason] += 1
                if reason in {"funding_resolver_unavailable", "funding_not_traced"}:
                    near_miss_funding_not_assessable += 1

        if bool(funnel.get("enabled")) and not resolver_available and not resolver_not_assessed:
            _add_warning(
                warnings,
                "resolver_unavailable_structural_pre_admission",
                "Funding resolver is unavailable in a structural pre-admission run.",
                source_record,
            )
        if not resolver_available and not resolver_reason and not resolver_not_assessed:
            _add_warning(
                warnings,
                "missing_resolver_disabled_reason",
                "Funding resolver is unavailable but no disabled reason is saved.",
                source_record,
            )
        if grouped > 0 and pre_trace_attempts == 0 and resolver_available:
            _add_warning(
                warnings,
                "pre_admission_funding_trace_zero_with_grouped_subthreshold",
                "Pre-admission funding trace attempted count is zero while grouped above-floor sub-threshold trades exist and resolver is available.",
                source_record,
            )
        if functional_status in {"available_lightweight_only", "rate_limited_for_funding_trace"} and trace_attempts > 0 and trace_succeeded == 0:
            _add_warning(
                warnings,
                "lightweight_available_but_funding_trace_failed",
                "Lightweight RPC is available but production funding trace succeeded count is zero.",
                source_record,
            )
        if trace_attempts > 0 and trace_succeeded == 0 and rate_limited_count > 0:
            _add_warning(
                warnings,
                "all_funding_traces_failed_rate_limited",
                "Funding traces were attempted and all available saved evidence points to rate limits.",
                source_record,
            )
        if (
            trace_attempts > 0
            and "fundingTracePersistentCacheEnabled" in funnel
            and not persistent_cache_enabled
        ):
            _add_warning(
                warnings,
                "persistent_cache_disabled_fresh_validation",
                "Persistent funding trace cache is disabled while funding traces are attempted.",
                source_record,
            )
        if rate_limited_count > 0 and endpoint_pool_size > 1 and fallback_endpoint_count == 0:
            _add_warning(
                warnings,
                "no_endpoint_fallback_after_429",
                "A 429/rate-limit was recorded but no endpoint fallback was attempted.",
                source_record,
            )
        cache_satisfied_trace = (
            persistent_cache_hit_count > 0
            and log_chunks_attempted == 0
            and rate_limited_count == 0
        )
        if (
            endpoint_pool_size > 1
            and trace_attempts > 0
            and _endpoint_summary_used_count(endpoint_summary) <= 1
            and not cache_satisfied_trace
        ):
            _add_warning(
                warnings,
                "single_endpoint_used_with_multiple_configured",
                "Multiple RPC endpoints are configured but saved accounting shows trace traffic on at most one endpoint.",
                source_record,
            )
        if (
            str(funnel.get("preAdmissionFundingAssessmentStatus") or "") == "assessed_no_strict_funding_groups"
            and functional_status != "available_for_funding_trace"
        ):
            _add_warning(
                warnings,
                "report_implies_no_strict_funding_without_trace_available",
                "Funnel says no strict funding groups were found while resolver functional status is not funding-trace available.",
                source_record,
            )
        if strict_groups > 0 and attempts == 0:
            _add_warning(
                warnings,
                "strict_funding_groups_found_without_admission_attempts",
                "Strict funding groups were found but no pre-admission attempts were recorded.",
                source_record,
            )

        if validated > 0:
            inactive_assessments["active_validated"] += 1
        elif attempts > 0:
            inactive_assessments["attempts_rejected_after_scoring"] += 1
        elif grouped == 0:
            inactive_assessments["no_grouped_subthreshold_opportunities"] += 1
        elif not resolver_available and not resolver_not_assessed:
            inactive_assessments["funding_resolver_unavailable"] += 1
        elif pre_trace_attempts == 0:
            inactive_assessments["funding_trace_inactive"] += 1
        elif strict_groups == 0:
            inactive_assessments["no_strict_structural_groups_observed"] += 1
        else:
            inactive_assessments["requires_manual_review"] += 1

    funding_unknown_rate = (total_unknown / total_above_floor) if total_above_floor else 0.0
    avg_trace_coverage = (
        sum(trace_coverage_values) / len(trace_coverage_values)
        if trace_coverage_values
        else ((total_trace_succeeded / total_trace_attempts) if total_trace_attempts else 0.0)
    )
    return {
        "funnel_file_count": len(funnels),
        "total_structural_pre_admission_attempts": total_attempts,
        "total_validated": total_validated,
        "total_rejected_after_scoring": total_rejected_after_scoring,
        "total_near_miss_groups": total_near_miss_groups,
        "top_rejection_reasons": _counter_dict(rejection_reasons),
        "funding_resolver_availability": _counter_dict(resolver_availability),
        "funding_resolver_functional_statuses": _counter_dict(resolver_functional_statuses),
        "funding_resolver_unavailable_reasons": _counter_dict(resolver_unavailable_reasons),
        "auth_error_bundle_count": auth_error_bundle_count,
        "lightweight_health_available_bundle_count": lightweight_available_bundle_count,
        "funding_trace_health_available_bundle_count": funding_trace_available_bundle_count,
        "rate_limited_bundle_count": rate_limited_bundle_count,
        "lightweight_available_but_trace_failed_bundle_count": lightweight_available_trace_failed_count,
        "production_trace_succeeded_bundle_count": production_trace_succeeded_bundle_count,
        "funding_trace_endpoint_pool_size_max": max(endpoint_pool_sizes) if endpoint_pool_sizes else 0,
        "funding_trace_endpoint_pool_size_average": round(
            (sum(endpoint_pool_sizes) / len(endpoint_pool_sizes)) if endpoint_pool_sizes else 0.0,
            2,
        ),
        "funding_trace_retry_count": total_retry_count,
        "funding_trace_fallback_endpoint_count": total_fallback_endpoint_count,
        "funding_trace_rate_limited_count": total_rate_limited,
        "funding_trace_log_chunks_attempted": total_log_chunks_attempted,
        "funding_trace_log_chunks_succeeded": total_log_chunks_succeeded,
        "funding_trace_log_chunks_failed": total_log_chunks_failed,
        "funding_trace_log_chunks_rate_limited": total_log_chunks_rate_limited,
        "funding_trace_cache_hit_count": total_cache_hit_count,
        "funding_trace_cache_miss_count": total_cache_miss_count,
        "funding_trace_persistent_cache_enabled_bundle_count": persistent_cache_enabled_bundle_count,
        "funding_trace_persistent_cache_hit_count": total_persistent_cache_hit_count,
        "funding_trace_persistent_cache_miss_count": total_persistent_cache_miss_count,
        "funding_trace_persistent_cache_write_count": total_persistent_cache_write_count,
        "funding_trace_persistent_cache_expired_count": total_persistent_cache_expired_count,
        "funding_trace_persistent_cache_failure_cooldown_count": total_persistent_cache_failure_cooldown_count,
        "funding_trace_persistent_cache_hit_rate": round(
            total_persistent_cache_hit_count
            / (total_persistent_cache_hit_count + total_persistent_cache_miss_count)
            if (total_persistent_cache_hit_count + total_persistent_cache_miss_count)
            else 0.0,
            4,
        ),
        "funding_trace_coverage_ratio": round(avg_trace_coverage, 4),
        "pre_admission_runs_with_resolver_unavailable": resolver_unavailable_runs,
        "near_miss_groups_funding_not_assessable": near_miss_funding_not_assessable,
        "funding_unknown_count": total_unknown,
        "funding_unknown_rate": round(funding_unknown_rate, 4),
        "strict_funding_groups_found": total_strict_groups,
        "proxy_only_groups_found": total_proxy_groups,
        "funding_trace_attempted_count": total_trace_attempts,
        "funding_trace_succeeded_count": total_trace_succeeded,
        "funding_trace_failed_count": total_trace_failed,
        "funding_trace_skipped_count": total_trace_skipped,
        "pre_admission_funding_trace_attempted_count": total_pre_trace_attempts,
        "pre_admission_funding_trace_succeeded_count": total_pre_trace_succeeded,
        "pre_admission_funding_trace_failed_count": total_pre_trace_failed,
        "pre_admission_funding_trace_skipped_count": total_pre_trace_skipped,
        "grouped_subthreshold_groups": total_grouped,
        "subthreshold_above_floor_trades": total_above_floor,
        "inactivity_assessment": _counter_dict(inactive_assessments),
    }


def collect_records(paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for input_path in paths:
        if not input_path.exists():
            continue
        file_paths = [input_path] if input_path.is_file() else sorted(input_path.rglob("*"))
        for path in file_paths:
            if not path.is_file():
                continue
            if path.name.endswith(FUNNEL_FILE_SUFFIX):
                continue
            suffix = path.suffix.lower()
            try:
                if suffix == ".json":
                    records.extend(_records_from_json_file(path))
                elif suffix == ".csv":
                    records.extend(_records_from_csv_file(path))
            except (OSError, csv.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
                records.append(
                    {
                        "_audit_source_path": str(path),
                        "_audit_parse_error": f"{type(exc).__name__}: {exc}",
                    }
                )
    return records


def collect_funnels(paths: Iterable[Path]) -> list[dict[str, Any]]:
    funnels: list[dict[str, Any]] = []
    for input_path in paths:
        if not input_path.exists():
            continue
        file_paths = [input_path] if input_path.is_file() else sorted(input_path.rglob(f"*{FUNNEL_FILE_SUFFIX}"))
        for path in file_paths:
            if not path.is_file() or not path.name.endswith(FUNNEL_FILE_SUFFIX):
                continue
            try:
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(payload, Mapping):
                item = dict(payload)
                item["_audit_source_path"] = str(path)
                funnels.append(item)
    return funnels


def write_audit_outputs(
    summary: Mapping[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    timestamp: str | None = None,
    filename_prefix: str = "model_behavior_audit",
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"{filename_prefix}_{stamp}.json"
    markdown_path = output_dir / f"{filename_prefix}_{stamp}.md"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")

    with markdown_path.open("w", encoding="utf-8") as handle:
        handle.write(_render_markdown(summary))

    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def write_strong_risk_deep_dive_outputs(
    summary: Mapping[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    timestamp: str | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    payload = {
        "generated_at": summary.get("generated_at", ""),
        "input_paths": summary.get("input_paths", []),
        "strong_risk_rows": summary.get("strong_risk_rows", 0),
        "strong_risk_composition": summary.get("strong_risk_composition", {}),
        "strong_risk_deep_dive": summary.get("strong_risk_deep_dive", {}),
        "warnings": [
            warning
            for warning in summary.get("warnings", [])
            if isinstance(warning, Mapping) and str(warning.get("code") or "").startswith("strong_risk")
        ],
    }
    json_path = output_dir / f"strong_risk_deep_dive_{stamp}.json"
    markdown_path = output_dir / f"strong_risk_deep_dive_{stamp}.md"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    markdown_path.write_text(_render_strong_risk_deep_dive_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def _records_from_json_file(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = list(_iter_json_records(payload))
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        copy = dict(row)
        copy["_audit_source_path"] = str(path)
        copy["_audit_source_row"] = str(index)
        records.append(copy)
    return records


def _records_from_csv_file(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            copy = dict(row)
            copy["_audit_source_path"] = str(path)
            copy["_audit_source_row"] = str(index)
            records.append(copy)
    return records


def _iter_json_records(
    payload: Any,
    *,
    parent_key: str = "",
    include_current: bool = True,
) -> Iterable[Mapping[str, Any]]:
    if parent_key in {"performance", "funding_resolver_health", "candidate_admission_funnel"}:
        return
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, Mapping) and (
                parent_key in CONTAINER_KEYS or _looks_like_record(item)
            ):
                yield item
            if isinstance(item, (Mapping, list)):
                yield from _iter_json_records(
                    item,
                    parent_key=parent_key,
                    include_current=False,
                )
        return

    if not isinstance(payload, Mapping):
        return

    if include_current and _looks_like_record(payload):
        yield payload

    for key, value in payload.items():
        if key in {"rawMetrics", "raw_metrics", "supportingEvidence", "supporting_evidence"}:
            continue
        if key in CONTAINER_KEYS or isinstance(value, (Mapping, list)):
            yield from _iter_json_records(value, parent_key=str(key))


def _looks_like_record(row: Mapping[str, Any]) -> bool:
    if any(key in row for key in ROW_LIKE_KEYS):
        return True
    raw = row.get("rawMetrics") or row.get("raw_metrics")
    return isinstance(raw, Mapping) and any(key in raw for key in ROW_LIKE_KEYS)


def _lookup(row: Mapping[str, Any], *keys: str) -> Any:
    for source in _lookup_sources(row):
        for key in keys:
            if key in source and not _blank(source.get(key)):
                return source.get(key)
    return ""


def _lookup_sources(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = [row]
    for key in (
        "rawMetrics",
        "raw_metrics",
        "supportingEvidence",
        "supporting_evidence",
        "evidence",
    ):
        value = row.get(key)
        if isinstance(value, Mapping):
            sources.append(value)
    return sources


def _has_key(row: Mapping[str, Any], key: str) -> bool:
    return any(key in source for source in _lookup_sources(row))


def _string_value(row: Mapping[str, Any], *keys: str) -> str:
    return str(_lookup(row, *keys) or "").strip()


def _listish(value: Any) -> list[str]:
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_listish(item))
        return result
    if isinstance(value, tuple):
        return _listish(list(value))
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return _listish(parsed)
    separator = ";" if ";" in text else ","
    if separator in text:
        return [part.strip() for part in text.split(separator) if part.strip()]
    return [text]


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _normalize_label(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _normalize_source(value: str) -> str:
    text = str(value or "").strip()
    lowered = text.lower()
    if "high-impact timing/repricing" in lowered or "high impact timing/repricing" in lowered:
        return "high_impact_timing_or_repricing"
    return text


def _is_independent_hard_source(source: str) -> bool:
    normalized = _normalize_label(_normalize_source(source))
    return normalized in INDEPENDENT_HARD_EVIDENCE_SOURCES


def _is_structural_hard_evidence_source(source: str) -> bool:
    normalized = _normalize_label(_normalize_source(source))
    return normalized in STRUCTURAL_HARD_EVIDENCE_SOURCES


def _gate_type_from_exact_branch(branch: str) -> str:
    normalized = _normalize_label(branch)
    if normalized == "timing_led_gate":
        return "timing_led"
    if normalized == "structure_led_gate":
        return "structure_led"
    if normalized == "retrospective_event_forensic_gate":
        return "retrospective_event_forensic"
    if normalized == "not_strong_risk":
        return "not_strong_risk"
    return "legacy_unknown"


def _has_high_impact_source(values: Iterable[Any]) -> bool:
    text = " ".join(str(value or "").lower() for value in values)
    return any(token in text for token in HIGH_IMPACT_SOURCE_TOKENS)


def _has_repricing_flag(values: Iterable[Any]) -> bool:
    text = " ".join(str(value or "").lower() for value in values)
    return "post_entry_repricing" in text or "favorable_repricing" in text


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _meaningful(value: Any) -> bool:
    if _blank(value):
        return False
    text = str(value).strip().lower()
    if text in {"no", "false", "0", "0.0", "none", "unknown", "unavailable", "n/a", "na"}:
        return False
    return True


def _has_meaningful_signal(row: Mapping[str, Any], keys: Iterable[str]) -> bool:
    for key in keys:
        value = _lookup(row, key)
        if _meaningful(value):
            return True
    return False


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _boolish_or_none(value: Any) -> bool | None:
    if value is None or _blank(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _number(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1]
    if not text or text.lower() in {"unavailable", "none", "unknown"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _score_value(row: Mapping[str, Any]) -> float | None:
    return _number(
        _lookup(
            row,
            "eventForensicScore",
            "event_forensic_score",
            "suspicion_score",
            "suspicionScore",
            "walletScore",
            "wallet_score",
            "clusterScore",
            "cluster_score",
            "score",
        )
    )


def _score_bucket(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 80:
        return "80+"
    if score >= 70:
        return "70-79"
    if score >= 60:
        return "60-69"
    if score >= 50:
        return "50-59"
    if score >= 40:
        return "40-49"
    if score >= 20:
        return "20-39"
    return "0-19"


def _endpoint_summary_used_count(value: Any) -> int:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return 0
    if not isinstance(value, list):
        return 0
    used = 0
    for item in value:
        if not isinstance(item, Mapping):
            continue
        request_count = _number(item.get("requestCount") or item.get("request_count"))
        if request_count and request_count > 0:
            used += 1
    return used


def _int_value(row: Mapping[str, Any], *keys: str) -> int:
    parsed = _number(_lookup(row, *keys))
    return int(parsed) if parsed is not None else 0


def _funnel_count(counts: Mapping[str, Any], key: str) -> int:
    value = _number(counts.get(key))
    return int(value) if value is not None else 0


def _is_strong_risk(severity: str, existing_model_class: str, judgment: str) -> bool:
    if str(severity or "").strip().startswith("Strong Risk"):
        return True
    if str(judgment or "").strip().startswith("Strong Risk"):
        return True
    if str(existing_model_class or "").strip().startswith("Strong Risk"):
        return not _is_benign_final_judgment(judgment)
    return False


def _is_benign_final_judgment(judgment: str) -> bool:
    text = str(judgment or "").strip().lower()
    return bool(
        text
        and (
            "contextual or benign" in text
            or "likely contextual" in text
            or "benign" == text
        )
    )


def _strong_gate_fields_present(
    row: Mapping[str, Any],
    existing_model_class: str,
    judgment: str,
) -> bool:
    if existing_model_class or judgment:
        return True
    return any(
        _has_key(row, key)
        for key in (
            "strongRiskGate",
            "strong_risk_gate",
            "strongRiskGatePassed",
            "strong_risk_gate_passed",
            "strongRiskGateType",
            "strong_risk_gate_type",
            "strongRiskGateEvidenceSources",
            "strong_risk_gate_evidence_sources",
            "strong_timing_proof_count",
            "strongTimingProofCount",
            "supporting_booster_count",
            "supportingBoosterCount",
            "structural_concern_count",
            "structuralConcernCount",
            "opening_exposure_flag",
            "openingExposureFlag",
            "openingExposure",
            "laterWon",
            "later_won",
            "eventForensicScore",
            "event_forensic_score",
        )
    )


def _strong_gate_apparent(
    row: Mapping[str, Any],
    existing_model_class: str,
    judgment: str,
) -> bool:
    if str(existing_model_class or "").strip() == "Strong Risk":
        return True
    if _truthy(_lookup(row, "strongRiskGate", "strong_risk_gate", "strongRiskGatePassed", "strong_risk_gate_passed")):
        return True
    gate_type = _normalize_label(_string_value(row, "strongRiskGateType", "strong_risk_gate_type"))
    if gate_type and gate_type not in {"not_strong_risk", "legacy_unknown"}:
        return True

    opening = _truthy(_lookup(row, "opening_exposure_flag", "openingExposureFlag", "openingExposure"))
    strong_timing = _int_value(row, "strong_timing_proof_count", "strongTimingProofCount")
    structural = _int_value(row, "structural_concern_count", "structuralConcernCount")
    boosters = _int_value(row, "supporting_booster_count", "supportingBoosterCount")
    score = _number(_lookup(row, "eventForensicScore", "event_forensic_score"))
    later_won = _truthy(_lookup(row, "laterWon", "later_won"))

    if opening and strong_timing >= 1 and (structural >= 1 or boosters >= 1):
        return True
    if opening and structural >= 2 and (strong_timing >= 1 or boosters >= 1):
        return True
    if str(judgment or "").startswith("Strong Risk") and score is not None and score >= 70 and later_won:
        return True
    return False


def _strong_risk_attribution_from_row(
    row: Mapping[str, Any],
    *,
    strong_risk: bool,
    gate_fields_present: bool,
    schema_has_new_fields: bool,
    hard_sources: list[str],
    suppressors: list[str],
    raw_independent_support_sources: list[str],
    high_impact_present: bool,
    opening_exposure_confirmed: bool,
    repricing_quality: str,
    funding_grade: str,
    score: float | None,
    existing_model_class: str,
    judgment: str,
) -> dict[str, Any]:
    explicit_gate_type = _normalize_label(
        _string_value(row, "strongRiskGateType", "strong_risk_gate_type")
    )
    explicit_composition = _normalize_label(
        _string_value(row, "strongRiskCompositionClass", "strong_risk_composition_class")
    )
    trace_payload = _string_value(row, "strongRiskGateTrace", "strong_risk_gate_trace")
    trace_available = any(
        _has_key(row, key)
        for key in (
            "strongRiskGateTrace",
            "strong_risk_gate_trace",
            "strongRiskGateName",
            "strong_risk_gate_name",
            "strongRiskGateFamily",
            "strong_risk_gate_family",
        )
    )
    explicit_gate_name = _normalize_label(
        _string_value(row, "strongRiskGateName", "strong_risk_gate_name")
    )
    explicit_gate_family = _normalize_label(
        _string_value(row, "strongRiskGateFamily", "strong_risk_gate_family")
    )
    explicit_gate_inputs = _string_value(row, "strongRiskGateInputs", "strong_risk_gate_inputs")
    exact_branch = _normalize_label(
        _string_value(row, "strongRiskExactGateBranch", "strong_risk_exact_gate_branch")
    )
    exact_branch_present = any(
        _has_key(row, key)
        for key in ("strongRiskExactGateBranch", "strong_risk_exact_gate_branch")
    )
    exact_gate_passed = _truthy(
        _lookup(row, "strongRiskExactGatePassed", "strong_risk_exact_gate_passed")
    )
    exact_failed_reasons = _dedupe(
        _normalize_label(value)
        for value in _listish(
            _lookup(
                row,
                "strongRiskExactGateFailedReasons",
                "strong_risk_exact_gate_failed_reasons",
            )
        )
        if _normalize_label(value)
    )
    exact_gate_inputs = _string_value(row, "strongRiskExactGateInputs", "strong_risk_exact_gate_inputs")
    timing_gate_inputs = _string_value(row, "strongRiskTimingGateInputs", "strong_risk_timing_gate_inputs")
    structure_gate_inputs = _string_value(row, "strongRiskStructureGateInputs", "strong_risk_structure_gate_inputs")
    retrospective_gate_inputs = _string_value(
        row,
        "strongRiskRetrospectiveGateInputs",
        "strong_risk_retrospective_gate_inputs",
    )
    gate_source_was_inferred = _truthy(
        _lookup(row, "strongRiskGateSourceWasInferred", "strong_risk_gate_source_was_inferred")
    )
    gate_source_inference_reason = _normalize_label(
        _string_value(
            row,
            "strongRiskGateSourceInferenceReason",
            "strong_risk_gate_source_inference_reason",
        )
    )
    gate_sources = _dedupe(
        _normalize_source(value)
        for value in _listish(
            _lookup(row, "strongRiskGateEvidenceSources", "strong_risk_gate_evidence_sources")
        )
        if _normalize_source(value)
    )
    timing_sources = _dedupe(
        _normalize_source(value)
        for value in _listish(
            _lookup(row, "strongRiskTimingProofSources", "strong_risk_timing_proof_sources")
        )
        if _normalize_source(value)
    )
    structural_sources = _dedupe(
        _normalize_source(value)
        for value in _listish(
            _lookup(row, "strongRiskStructuralSources", "strong_risk_structural_sources")
        )
        if _normalize_source(value)
    )
    boosters = _dedupe(
        _normalize_source(value)
        for value in _listish(
            _lookup(row, "strongRiskSupportingBoosters", "strong_risk_supporting_boosters")
        )
        if _normalize_source(value)
    )
    gate_reasons = _dedupe(
        _normalize_label(value)
        for value in _listish(_lookup(row, "strongRiskGateReasons", "strong_risk_gate_reasons"))
        if _normalize_label(value)
    )
    resolved_structural_sources = _dedupe(
        _normalize_source(value)
        for value in _listish(
            _lookup(
                row,
                "strongRiskStructuralSourcesResolved",
                "strong_risk_structural_sources_resolved",
            )
        )
        if _normalize_source(value)
    )
    hard_eligible_sources = _dedupe(
        _normalize_source(value)
        for value in _listish(
            _lookup(
                row,
                "strongRiskHardEvidenceEligibleSources",
                "strong_risk_hard_evidence_eligible_sources",
            )
        )
        if _normalize_source(value)
    )
    non_hard_structural_sources = _dedupe(
        _normalize_source(value)
        for value in _listish(
            _lookup(
                row,
                "strongRiskNonHardStructuralSources",
                "strong_risk_non_hard_structural_sources",
            )
        )
        if _normalize_source(value)
    )
    if not timing_sources:
        timing_sources = _infer_strong_risk_timing_sources(row, high_impact_present=high_impact_present)
    if not structural_sources:
        structural_sources = _dedupe(
            source for source in raw_independent_support_sources if source != "suspicious_recent_funding"
        )
    if not resolved_structural_sources:
        resolved_structural_sources = list(structural_sources)
    if not hard_eligible_sources:
        hard_eligible_sources = _dedupe(
            source for source in resolved_structural_sources if _is_structural_hard_evidence_source(source)
        )
    if not non_hard_structural_sources:
        non_hard_structural_sources = _dedupe(
            source for source in resolved_structural_sources if source not in hard_eligible_sources
        )
    if not boosters:
        boosters = _infer_strong_risk_boosters(row)
    if not gate_sources:
        gate_sources = _dedupe([*timing_sources, *structural_sources, *boosters])
    strong_timing_count = int(
        _number(
            _lookup(
                row,
                "strongRiskTimingProofCount",
                "strong_risk_timing_proof_count",
                "strong_timing_proof_count",
                "strongTimingProofCount",
            )
        )
        or len(timing_sources)
    )
    structural_count = int(
        _number(
            _lookup(
                row,
                "strongRiskStructuralConcernCount",
                "strong_risk_structural_concern_count",
                "structural_concern_count",
                "structuralConcernCount",
            )
        )
        or len(structural_sources)
    )
    supporting_booster_count = int(
        _number(_lookup(row, "supporting_booster_count", "supportingBoosterCount")) or len(boosters)
    )
    suspicion_score = _number(
        _lookup(
            row,
            "strongRiskSuspicionScore",
            "strong_risk_suspicion_score",
            "suspicion_score",
            "suspicionScore",
            "existingModelScore",
            "existing_model_score",
        )
    )
    if suspicion_score is None:
        suspicion_score = score
    confidence_score = _number(
        _lookup(
            row,
            "strongRiskConfidenceScore",
            "strong_risk_confidence_score",
            "confidence_score",
            "confidenceScore",
        )
    )
    decisive_timing_edge = _truthy(_lookup(row, "decisive_timing_edge_flag", "decisiveTimingEdgeFlag"))
    if not decisive_timing_edge and timing_sources:
        decisive_timing_edge = True
    timing_gate = bool(
        opening_exposure_confirmed
        and decisive_timing_edge
        and strong_timing_count >= 1
        and (supporting_booster_count >= 1 or structural_count >= 1)
        and (confidence_score is None or confidence_score >= 50)
        and (suspicion_score is None or suspicion_score >= 40)
    )
    structure_gate = bool(
        opening_exposure_confirmed
        and structural_count >= 2
        and (confidence_score is None or confidence_score >= 50)
        and (suspicion_score is None or suspicion_score >= 36)
    )
    retrospective = _retrospective_strong_risk(row, judgment)

    if not strong_risk:
        gate_type = "not_strong_risk"
        composition = "not_strong_risk"
    elif explicit_gate_type:
        gate_type = explicit_gate_type
        composition = explicit_composition or _composition_for_gate(
            gate_type,
            timing_sources=timing_sources,
            structural_sources=structural_sources,
            suppressor_conflict=False,
        )
    elif exact_branch in {"timing_led_gate", "structure_led_gate", "retrospective_event_forensic_gate"}:
        gate_type = _gate_type_from_exact_branch(exact_branch)
        composition = _composition_for_gate(
            gate_type,
            timing_sources=timing_sources,
            structural_sources=resolved_structural_sources or structural_sources,
            suppressor_conflict=False,
        )
    elif retrospective:
        gate_type = "retrospective_event_forensic"
        composition = "retrospective_correctness"
        if "event_forensic_retrospective_correctness" not in gate_sources:
            gate_sources.insert(0, "event_forensic_retrospective_correctness")
    elif timing_gate and structure_gate:
        gate_type = "mixed_timing_structure"
        composition = "structural" if structural_sources else "timing_with_support"
    elif structure_gate:
        gate_type = "structure_led"
        composition = "structural"
    elif timing_gate:
        gate_type = "timing_led"
        composition = "timing_with_support" if (structural_sources or boosters) else "timing_only"
    elif gate_fields_present:
        gate_type = "legacy_unknown"
        composition = "score_only" if not gate_sources else "contextual_or_ambiguous"
    else:
        gate_type = "legacy_unknown"
        composition = "legacy_unknown"

    suppressor_reasons = _dedupe(
        _normalize_label(value)
        for value in _listish(
            _lookup(row, "strongRiskSuppressorConflictReasons", "strong_risk_suppressor_conflict_reasons")
        )
        if _normalize_label(value)
    )
    if not suppressor_reasons:
        suppressor_reasons = list(suppressors)
        if (
            "rapid_favorable_repricing" in timing_sources
            and repricing_quality in {"weak", "mechanical", "unknown"}
            and not structural_sources
        ):
            suppressor_reasons.append(f"repricing_source_quality_{repricing_quality}")
        if funding_grade == "unknown" and any("funding" in source for source in gate_sources):
            suppressor_reasons.append("funding_unknown")
        suppressor_reasons = _dedupe(suppressor_reasons)
    suppressor_conflict = _truthy(
        _lookup(row, "strongRiskSuppressorConflict", "strong_risk_suppressor_conflict")
    ) or bool(suppressor_reasons)
    if strong_risk and not hard_sources:
        explanation = _string_value(
            row,
            "strongRiskNoHardEvidenceExplanation",
            "strong_risk_no_hard_evidence_explanation",
        )
        if not explanation:
            if gate_type == "timing_led":
                explanation = "Strong Risk is timing-led; no structural hardEvidenceSources were saved."
            elif gate_type == "retrospective_event_forensic":
                explanation = "Retrospective event-forensic correctness/rank, not structural hard evidence."
            elif composition == "score_only":
                explanation = "No timing, structural, or retrospective gate source is identifiable from saved fields."
            else:
                explanation = "Saved row has Strong Risk without structural hardEvidenceSources."
    else:
        explanation = _string_value(
            row,
            "strongRiskNoHardEvidenceExplanation",
            "strong_risk_no_hard_evidence_explanation",
        )

    retrospective_sources = _dedupe(
        _normalize_source(value)
        for value in _listish(
            _lookup(row, "strongRiskRetrospectiveSources", "strong_risk_retrospective_sources")
        )
        if _normalize_source(value)
    )
    if retrospective and not retrospective_sources:
        retrospective_sources = ["event_forensic_retrospective_correctness"]
    retrospective_only_value = _boolish_or_none(
        _lookup(row, "strongRiskRetrospectiveOnly", "strong_risk_retrospective_only")
    )
    retrospective_only = bool(
        retrospective_only_value
        if retrospective_only_value is not None
        else gate_type == "retrospective_event_forensic" or exact_branch == "retrospective_event_forensic_gate"
    )
    live_detectable_value = _boolish_or_none(
        _lookup(row, "strongRiskLiveDetectable", "strong_risk_live_detectable")
    )
    live_detectable = bool(
        live_detectable_value
        if live_detectable_value is not None
        else (strong_risk and not retrospective_only)
    )
    if exact_branch_present and not gate_source_inference_reason:
        gate_source_inference_reason = ""
    elif not exact_branch_present and strong_risk and schema_has_new_fields:
        gate_source_was_inferred = True
        gate_source_inference_reason = "missing_exact_gate_fields"
    elif not exact_branch_present and strong_risk:
        gate_source_was_inferred = True
        gate_source_inference_reason = "legacy_saved_output"

    source_issue = _normalize_label(
        _string_value(row, "strongRiskSourceAttributionIssue", "strong_risk_source_attribution_issue")
    )
    source_issue = _resolve_strong_risk_source_issue(
        explicit_issue=source_issue,
        strong_risk=strong_risk,
        gate_type=gate_type,
        composition=composition,
        schema_has_new_fields=schema_has_new_fields,
        structural_count=structural_count,
        resolved_structural_sources=resolved_structural_sources,
        hard_eligible_sources=hard_eligible_sources,
        hard_sources=hard_sources,
        raw_independent_support_sources=raw_independent_support_sources,
        exact_branch_present=exact_branch_present,
    )
    missing_source_attribution = _truthy(
        _lookup(
            row,
            "strongRiskMissingSourceAttribution",
            "strong_risk_missing_source_attribution",
        )
    ) or source_issue in {
        "schema_propagation_gap",
        "hard_evidence_source_missing",
        "inference_insufficient",
    }
    no_hard_sources_reason = _string_value(
        row,
        "strongRiskNoHardEvidenceSourcesReason",
        "strong_risk_no_hard_evidence_sources_reason",
    ) or explanation
    structural_but_not_hard_sources = _dedupe(
        _normalize_source(value)
        for value in _listish(
            _lookup(
                row,
                "strongRiskStructuralButNotHardEvidenceSources",
                "strong_risk_structural_but_not_hard_evidence_sources",
            )
        )
        if _normalize_source(value)
    )
    if not structural_but_not_hard_sources and source_issue == "structural_but_not_hard_evidence":
        structural_but_not_hard_sources = list(non_hard_structural_sources)
    structural_but_not_hard = _truthy(
        _lookup(
            row,
            "strongRiskStructuralButNotHardEvidence",
            "strong_risk_structural_but_not_hard_evidence",
        )
    ) or source_issue == "structural_but_not_hard_evidence"
    why_no_hard = _string_value(
        row,
        "strongRiskWhyNoHardEvidence",
        "strong_risk_why_no_hard_evidence",
    ) or no_hard_sources_reason
    score_only_resolution = _normalize_label(
        _string_value(row, "strongRiskScoreOnlyResolution", "strong_risk_score_only_resolution")
    )
    score_only_resolution = _resolve_strong_risk_score_only_resolution(
        explicit_resolution=score_only_resolution,
        strong_risk=strong_risk,
        composition=composition,
        exact_branch=exact_branch,
        exact_branch_present=exact_branch_present,
        gate_sources=gate_sources,
        timing_sources=timing_sources,
        structural_sources=resolved_structural_sources or structural_sources,
        retrospective=retrospective or retrospective_only,
        schema_has_new_fields=schema_has_new_fields,
    )
    gate_leakage_candidate = _truthy(
        _lookup(row, "strongRiskGateLeakageCandidate", "strong_risk_gate_leakage_candidate")
    ) or score_only_resolution == "actual_score_only_gate_leakage_candidate"
    gate_leakage_reason = _string_value(
        row,
        "strongRiskGateLeakageReason",
        "strong_risk_gate_leakage_reason",
    )
    if gate_leakage_candidate and not gate_leakage_reason:
        gate_leakage_reason = "No timing proof, structural source, or retrospective source is identifiable after exact provenance."
    exact_inferred_disagree = bool(
        strong_risk
        and exact_branch in {"timing_led_gate", "structure_led_gate", "retrospective_event_forensic_gate"}
        and _gate_type_from_exact_branch(exact_branch) != gate_type
        and not (
            exact_branch == "timing_led_gate"
            and gate_type == "mixed_timing_structure"
        )
    )
    independent_trace_sources = _dedupe(
        _normalize_source(value)
        for value in _listish(
            _lookup(
                row,
                "strongRiskIndependentEvidenceSources",
                "strong_risk_independent_evidence_sources",
            )
        )
        if _normalize_source(value)
    )
    if not independent_trace_sources:
        independent_trace_sources = _dedupe(
            source
            for source in [*hard_sources, *hard_eligible_sources, *raw_independent_support_sources]
            if source and source != "suspicious_recent_funding"
        )
    has_independent_trace = _boolish_or_none(
        _lookup(
            row,
            "strongRiskHasIndependentHardEvidence",
            "strong_risk_has_independent_hard_evidence",
        )
    )
    has_independent_hard = bool(
        has_independent_trace if has_independent_trace is not None else independent_trace_sources
    )
    gate_family = explicit_gate_family
    if not gate_family:
        if gate_type == "retrospective_event_forensic":
            gate_family = "retrospective_correctness"
        elif gate_type in {"structure_led", "mixed_timing_structure"}:
            gate_family = "structural"
        elif gate_type == "timing_led":
            gate_family = "timing_repricing"
        elif composition == "score_only":
            gate_family = "score_threshold"
        elif any("funding" in str(source) for source in [*gate_sources, *resolved_structural_sources]):
            gate_family = "funding"
        else:
            gate_family = "unknown"
    gate_name = explicit_gate_name or exact_branch or gate_type or "unknown"
    opening_status = _normalize_label(
        _string_value(row, "strongRiskOpeningExposureStatus", "strong_risk_opening_exposure_status")
    )
    if not opening_status:
        opening_status = "confirmed" if opening_exposure_confirmed else "not_confirmed" if schema_has_new_fields else "unknown"
    timing_repricing_only = _boolish_or_none(
        _lookup(row, "strongRiskTimingRepricingOnly", "strong_risk_timing_repricing_only")
    )
    if timing_repricing_only is None:
        timing_repricing_only = bool(
            strong_risk
            and gate_family == "timing_repricing"
            and not has_independent_hard
            and not resolved_structural_sources
        )
    score_only_trace = _boolish_or_none(_lookup(row, "strongRiskScoreOnly", "strong_risk_score_only"))
    if score_only_trace is None:
        score_only_trace = bool(strong_risk and composition == "score_only")
    saved_fields_sufficient = _boolish_or_none(
        _lookup(row, "strongRiskSavedFieldsSufficient", "strong_risk_saved_fields_sufficient")
    )
    if saved_fields_sufficient is None:
        saved_fields_sufficient = bool(
            not strong_risk
            or (
                exact_branch_present
                and exact_branch not in {"legacy_unknown", "not_strong_risk"}
                and gate_family != "unknown"
            )
        )
    diagnostic_only = _boolish_or_none(_lookup(row, "strongRiskDiagnosticOnly", "strong_risk_diagnostic_only"))

    return {
        "strong_risk_gate_passed": _truthy(
            _lookup(row, "strongRiskGatePassed", "strong_risk_gate_passed")
        ) or strong_risk,
        "strong_risk_gate_type": gate_type,
        "strong_risk_gate_trace_available": trace_available,
        "strong_risk_gate_trace": trace_payload,
        "strong_risk_gate_name": gate_name,
        "strong_risk_gate_family": gate_family,
        "strong_risk_gate_inputs": explicit_gate_inputs,
        "strong_risk_gate_reasons": gate_reasons,
        "strong_risk_gate_evidence_sources": gate_sources,
        "strong_risk_timing_proof_sources": timing_sources,
        "strong_risk_structural_sources": structural_sources,
        "strong_risk_supporting_boosters": boosters,
        "strong_risk_structural_concern_count": structural_count,
        "strong_risk_timing_proof_count": strong_timing_count,
        "strong_risk_opening_exposure_confirmed": _truthy(
            _lookup(
                row,
                "strongRiskOpeningExposureConfirmed",
                "strong_risk_opening_exposure_confirmed",
            )
        ) or opening_exposure_confirmed,
        "strong_risk_confidence_score": confidence_score,
        "strong_risk_suspicion_score": suspicion_score,
        "strong_risk_has_independent_hard_evidence": has_independent_hard,
        "strong_risk_independent_evidence_sources": independent_trace_sources,
        "strong_risk_suppressor_conflict": suppressor_conflict,
        "strong_risk_suppressor_conflict_reasons": suppressor_reasons,
        "strong_risk_has_hard_evidence_sources": _truthy(
            _lookup(row, "strongRiskHasHardEvidenceSources", "strong_risk_has_hard_evidence_sources")
        ) or bool(hard_sources),
        "strong_risk_no_hard_evidence_explanation": explanation,
        "strong_risk_composition_class": composition,
        "strong_risk_attribution_fields_present": any(_has_key(row, key) for key in STRONG_RISK_ATTRIBUTION_KEYS),
        "strong_risk_new_schema": schema_has_new_fields,
        "strong_risk_exact_gate_branch": exact_branch or ("not_strong_risk" if not strong_risk else "legacy_unknown"),
        "strong_risk_exact_gate_passed": exact_gate_passed,
        "strong_risk_exact_gate_failed_reasons": exact_failed_reasons,
        "strong_risk_exact_gate_inputs": exact_gate_inputs,
        "strong_risk_timing_gate_inputs": timing_gate_inputs,
        "strong_risk_structure_gate_inputs": structure_gate_inputs,
        "strong_risk_retrospective_gate_inputs": retrospective_gate_inputs,
        "strong_risk_exact_gate_branch_present": exact_branch_present,
        "strong_risk_gate_source_was_inferred": gate_source_was_inferred,
        "strong_risk_gate_source_inference_reason": gate_source_inference_reason,
        "strong_risk_exact_inferred_gate_disagree": exact_inferred_disagree,
        "strong_risk_structural_sources_resolved": resolved_structural_sources,
        "strong_risk_hard_evidence_eligible_sources": hard_eligible_sources,
        "strong_risk_non_hard_structural_sources": non_hard_structural_sources,
        "strong_risk_missing_source_attribution": missing_source_attribution,
        "strong_risk_source_attribution_issue": source_issue,
        "strong_risk_no_hard_evidence_sources_reason": no_hard_sources_reason,
        "strong_risk_structural_but_not_hard_evidence": structural_but_not_hard,
        "strong_risk_structural_but_not_hard_evidence_sources": structural_but_not_hard_sources,
        "strong_risk_why_no_hard_evidence": why_no_hard,
        "strong_risk_score_only_resolution": score_only_resolution,
        "strong_risk_gate_leakage_candidate": gate_leakage_candidate,
        "strong_risk_gate_leakage_reason": gate_leakage_reason,
        "strong_risk_live_detectable": live_detectable,
        "strong_risk_retrospective_only": retrospective_only,
        "strong_risk_retrospective_sources": retrospective_sources,
        "strong_risk_opening_exposure_status": opening_status,
        "strong_risk_timing_repricing_only": bool(timing_repricing_only),
        "strong_risk_score_only": bool(score_only_trace),
        "strong_risk_saved_fields_sufficient": bool(saved_fields_sufficient),
        "strong_risk_diagnostic_only": bool(diagnostic_only) if diagnostic_only is not None else trace_available,
    }


def _infer_strong_risk_timing_sources(row: Mapping[str, Any], *, high_impact_present: bool) -> list[str]:
    sources: list[str] = []
    if _truthy(_lookup(row, "beat_consensus_flag", "beatConsensusFlag")):
        sources.append("beat_local_consensus")
    if _truthy(_lookup(row, "favorable_repricing_flag", "favorableRepricingFlag")):
        sources.append("rapid_favorable_repricing")
    entry_rank = _number(_lookup(row, "market_entry_rank", "marketEntryRank", "winnerRank", "winner_rank"))
    if entry_rank is not None and entry_rank <= 3:
        sources.append("early_meaningful_entry")
    if _truthy(_lookup(row, "off_hours_flag", "offHoursFlag")):
        sources.append("off_hours_local_entry")
    hours_to_resolution = _number(_lookup(row, "hours_to_resolution", "hoursToResolution"))
    if hours_to_resolution is not None and hours_to_resolution <= 24:
        sources.append("hours_to_resolution_timing")
    if high_impact_present:
        sources.append("rapid_favorable_repricing")
    source_text = " ".join(str(item).lower() for item in _listish(_lookup(row, "eventForensicFlags", "flags")))
    if "post_entry_repricing" in source_text or "repricing" in source_text:
        sources.append("rapid_favorable_repricing")
    if "early" in source_text or "winner_rank" in source_text:
        sources.append("early_meaningful_entry")
    return _dedupe(sources)


def _infer_strong_risk_boosters(row: Mapping[str, Any]) -> list[str]:
    boosters: list[str] = []
    if _truthy(_lookup(row, "off_hours_flag", "offHoursFlag")):
        boosters.append("off_hours_local_entry")
    if _truthy(_lookup(row, "liquidity_shock_signal", "liquidityShockSignal")):
        boosters.append("liquidity_shock")
    if _truthy(_lookup(row, "coordinated_cluster_signal", "coordinatedClusterSignal")):
        boosters.append("coordinated_cluster")
    return _dedupe(boosters)


def _retrospective_strong_risk(row: Mapping[str, Any], judgment: str) -> bool:
    if str(judgment or "").startswith("Strong Risk") and "retrospective" in str(judgment or "").lower():
        return True
    score = _number(_lookup(row, "eventForensicScore", "event_forensic_score"))
    return bool(
        str(judgment or "").startswith("Strong Risk")
        and score is not None
        and score >= 70
        and _truthy(_lookup(row, "laterWon", "later_won"))
    )


def _composition_for_gate(
    gate_type: str,
    *,
    timing_sources: list[str],
    structural_sources: list[str],
    suppressor_conflict: bool,
) -> str:
    if gate_type == "not_strong_risk":
        return "not_strong_risk"
    if gate_type == "retrospective_event_forensic":
        return "retrospective_correctness"
    if gate_type in {"structure_led", "mixed_timing_structure"} and structural_sources:
        return "structural"
    if gate_type == "timing_led":
        if suppressor_conflict and not structural_sources:
            return "contextual_or_ambiguous"
        return "timing_with_support" if timing_sources else "timing_only"
    if gate_type == "legacy_unknown":
        return "legacy_unknown"
    return "contextual_or_ambiguous"


def _resolve_strong_risk_source_issue(
    *,
    explicit_issue: str,
    strong_risk: bool,
    gate_type: str,
    composition: str,
    schema_has_new_fields: bool,
    structural_count: int,
    resolved_structural_sources: list[str],
    hard_eligible_sources: list[str],
    hard_sources: list[str],
    raw_independent_support_sources: list[str],
    exact_branch_present: bool,
) -> str:
    allowed = {
        "none",
        "schema_propagation_gap",
        "structural_but_not_hard_evidence",
        "hard_evidence_source_missing",
        "legacy_unknown",
        "inference_insufficient",
    }
    if explicit_issue in allowed and explicit_issue not in {"none", ""}:
        return explicit_issue
    if not strong_risk:
        return "none"
    if not schema_has_new_fields and not exact_branch_present:
        return "legacy_unknown"
    structural_gate = gate_type in {"structure_led", "mixed_timing_structure"} or composition == "structural"
    if structural_gate and structural_count > 0 and not resolved_structural_sources:
        return "inference_insufficient"
    if structural_gate and hard_eligible_sources and not hard_sources:
        return "hard_evidence_source_missing"
    if structural_gate and raw_independent_support_sources and not hard_sources and not hard_eligible_sources:
        return "schema_propagation_gap"
    if structural_gate and resolved_structural_sources and not hard_eligible_sources and not hard_sources:
        return "structural_but_not_hard_evidence"
    return "none"


def _resolve_strong_risk_score_only_resolution(
    *,
    explicit_resolution: str,
    strong_risk: bool,
    composition: str,
    exact_branch: str,
    exact_branch_present: bool,
    gate_sources: list[str],
    timing_sources: list[str],
    structural_sources: list[str],
    retrospective: bool,
    schema_has_new_fields: bool,
) -> str:
    allowed = {
        "not_applicable",
        "attribution_parser_miss",
        "missing_exact_gate_fields",
        "actual_score_only_gate_leakage_candidate",
        "retrospective_or_legacy_misclassified",
    }
    if explicit_resolution in allowed and explicit_resolution not in {"", "not_applicable"}:
        return explicit_resolution
    if not strong_risk or composition != "score_only":
        return "not_applicable"
    if retrospective or exact_branch == "retrospective_event_forensic_gate":
        return "retrospective_or_legacy_misclassified"
    if gate_sources or timing_sources or structural_sources:
        return "attribution_parser_miss"
    if not exact_branch_present:
        return "missing_exact_gate_fields" if schema_has_new_fields else "retrospective_or_legacy_misclassified"
    return "actual_score_only_gate_leakage_candidate"


def _proxy_funding_present(row: Mapping[str, Any], funding_grade: str) -> bool:
    if funding_grade in PROXY_FUNDING_GRADES:
        return True
    if _truthy(_lookup(row, "cex_proxy_cluster_flag", "cexProxyClusterFlag")):
        return True
    if _truthy(_lookup(row, "funding_proxy_cluster_flag", "fundingProxyClusterFlag")):
        return True
    category_text = " ".join(
        _string_value(row, key)
        for key in (
            "funding_source_category",
            "fundingSourceCategory",
            "funding_origin_category",
            "fundingOriginCategory",
            "funding_source_label",
            "fundingSourceLabel",
        )
    ).lower()
    return any(token in category_text for token in ("cex", "centralized", "exchange", "bridge"))


def _strict_funding_present(row: Mapping[str, Any], funding_grade: str) -> bool:
    if funding_grade == "direct_strict":
        return True
    strict_key = _string_value(row, "funding_graph_key_strict", "fundingGraphKeyStrict")
    if strict_key:
        return True
    return bool(
        _truthy(_lookup(row, "shared_funding_source_flag", "sharedFundingSourceFlag"))
        and not _truthy(_lookup(row, "cex_proxy_cluster_flag", "cexProxyClusterFlag"))
    )


def _strict_shared_funding_has_distinct_wallet_support(row: Mapping[str, Any]) -> bool:
    if _truthy(_lookup(row, "cex_proxy_cluster_flag", "cexProxyClusterFlag")):
        return False
    if not (
        _truthy(_lookup(row, "shared_funding_source_flag", "sharedFundingSourceFlag"))
        or _truthy(_lookup(row, "strictSharedFundingSourceFlag", "strict_shared_funding_source_flag"))
        or _truthy(_lookup(row, "groupedCandidateStrictFunding", "grouped_candidate_strict_funding"))
    ):
        return False
    if not (
        _string_value(row, "funding_graph_key_strict", "fundingGraphKeyStrict")
        or _truthy(_lookup(row, "groupedCandidateStrictFunding", "grouped_candidate_strict_funding"))
    ):
        return False
    wallet_count = _number(
        _lookup(
            row,
            "sharedFundingSourceWalletCount",
            "shared_funding_source_wallet_count",
            "groupedCandidateWalletCount",
            "grouped_candidate_wallet_count",
        )
    )
    return bool(wallet_count is not None and wallet_count >= 2)


def _raw_independent_support_sources(
    row: Mapping[str, Any],
    *,
    hard_sources: Iterable[str],
    source_flags: Iterable[str],
    source_details: Iterable[str],
    suspicious_support_sources: Iterable[str],
    proxy_funding_present: bool,
    opening_exposure_confirmed: bool,
) -> list[str]:
    """Infer saved-field structural evidence for starvation diagnostics only."""

    observed: set[str] = set()
    for source in hard_sources:
        normalized = _normalize_label(_normalize_source(source))
        if normalized in STRUCTURAL_HARD_EVIDENCE_SOURCES:
            observed.add(normalized)
    for source in suspicious_support_sources:
        normalized = _normalize_label(_normalize_source(source))
        if normalized in {"strict_shared_funding_source", "strict_shared_funding", "non_proxy_shared_funding"}:
            if not _strict_shared_funding_has_distinct_wallet_support(row):
                continue
            normalized = "strict_shared_funding_source"
        if normalized in STRUCTURAL_HARD_EVIDENCE_SOURCES:
            observed.add(normalized)

    combined_text = " ".join(str(value or "") for value in list(source_flags) + list(source_details)).lower()

    if (
        "split_wallet_pattern" in combined_text
        or _truthy(_lookup(row, "splitWalletPatternFlag", "split_wallet_pattern_flag"))
    ):
        observed.add("split_wallet_pattern")

    if (
        not proxy_funding_present
        and _strict_shared_funding_has_distinct_wallet_support(row)
        and (
            "strict_shared_funding_source" in combined_text
            or _truthy(_lookup(row, "strictSharedFundingSourceFlag", "strict_shared_funding_source_flag"))
            or _truthy(_lookup(row, "shared_funding_source_flag", "sharedFundingSourceFlag"))
            or _truthy(_lookup(row, "groupedCandidateStrictFunding", "grouped_candidate_strict_funding"))
        )
    ):
        observed.add("strict_shared_funding_source")

    dormancy_days = _number(
        _lookup(
            row,
            "walletInactivityDays",
            "wallet_inactivity_days",
            "daysSincePriorWalletTrade",
            "days_since_prior_wallet_trade",
            "walletDormantDays",
            "wallet_dormant_days",
        )
    )
    if opening_exposure_confirmed and (
        "dormant_wallet_reactivation" in combined_text
        or (
            _truthy(
                _lookup(
                    row,
                    "dormantWalletReactivationFlag",
                    "dormant_wallet_reactivation_flag",
                    "reactivatedAfterDormancyFlag",
                    "reactivated_after_dormancy_flag",
                )
            )
            and dormancy_days is not None
            and dormancy_days >= 90
        )
        or (dormancy_days is not None and dormancy_days >= 90)
    ):
        observed.add("dormant_wallet_reactivation")

    price = _number(_lookup(row, "price", "tradePrice", "trade_price", "outcomePrice", "outcome_price"))
    winner_rank = _number(_lookup(row, "winnerEntryRank", "winner_entry_rank", "earlyWinnerRank", "early_winner_rank"))
    later_won = _truthy(_lookup(row, "laterWon", "later_won", "resolvedWinner", "resolved_winner"))
    outcomes_available = _truthy(_lookup(row, "outcomesAvailable", "outcomes_available")) or later_won
    if (
        "low_probability_early_winner" in combined_text
        or (
            opening_exposure_confirmed
            and outcomes_available
            and later_won
            and price is not None
            and price <= 0.35
            and winner_rank is not None
            and winner_rank <= 6
        )
    ):
        observed.add("low_probability_early_winner")

    event_family_narrow = any(
        token in combined_text
        for token in (
            "event_family_repeat_narrow_context",
            "event-family repeat narrow",
            "event family repeat narrow",
        )
    ) or (
        opening_exposure_confirmed
        and _truthy(_lookup(row, "eventFamilyRepeatFlag", "event_family_repeat_flag"))
        and _truthy(
            _lookup(
                row,
                "eventFamilyRepeatNarrowContext",
                "event_family_repeat_narrow_context",
                "eventFamilyNarrowContextFlag",
                "event_family_narrow_context_flag",
            )
        )
    )
    if event_family_narrow:
        observed.add("event_family_repeat_narrow_context")

    if "coordinated_sizing_with_hard_evidence" in combined_text and observed:
        observed.add("coordinated_sizing_with_hard_evidence")

    return sorted(observed)


def _visible_row(
    *,
    hard_evidence_review: bool,
    strong_risk: bool,
    severity: str,
    visibility_tier: str,
    row: Mapping[str, Any],
) -> bool:
    if hard_evidence_review or strong_risk:
        return True
    visibility = visibility_tier.strip().lower()
    if visibility in {
        "visible",
        "primary",
        "primary_allowed",
        "hard evidence review",
        "worth a look",
    }:
        return True
    if visibility in {"secondary review", "context_only", "hidden", "excluded"}:
        return False
    if severity in {"Worth a Look", "High concern"}:
        return True
    for key in ("eventForensicScore", "event_forensic_score", "walletScore", "clusterScore"):
        score = _number(_lookup(row, key))
        if score is not None and score >= 40:
            return True
    return False


def _detect_suppressors(row: Mapping[str, Any]) -> list[str]:
    text = _row_search_text(row)
    suppressors: list[str] = []
    if any(token in text for token in ("near_certainty", "near certainty", "near-certain")):
        suppressors.append("near_certainty")
    if any(token in text for token in ("yield_farm", "yield farm", "yield/theta", "yield like")):
        suppressors.append("yield_farm")
    if any(token in text for token in ("theta_decay", "theta decay", "theta")):
        suppressors.append("theta_decay")
    no_stale_gap = any(
        token in text
        for token in (
            "no resolution gap",
            "no_resolution_gap",
            "no public lag concern",
            "no_public_lag_concern",
        )
    )
    if not no_stale_gap and any(
        token in text
        for token in (
            "stale_or_resolution_gap",
            "resolution gap",
            "resolution_gap",
            "stale_resolution",
            "public lag",
            "hard_public_information",
        )
    ):
        suppressors.append("stale_or_resolution_gap")
    if any(token in text for token in ("hard_resolution_gap", "hard public information", "hard_public_information")):
        suppressors.append("hard_resolution_gap")
    not_bot_context = any(
        token in text
        for token in ("not clearly bot-like", "not clearly bot like", "not_bot_like", "not bot-like")
    )
    if not not_bot_context and any(token in text for token in ("bot_like", "bot-like", "bot like", "low_analyst_value")):
        suppressors.append("bot_like_execution")
    if "low_analyst_value" in text:
        suppressors.append("low_analyst_value_wallet")
    if any(token in text for token in ("domain_specialist", "domain specialist", "specialist_explained")):
        suppressors.append("domain_specialist")
    not_high_volume_context = any(
        token in text
        for token in (
            "not_public_power_user",
            "not public power user",
            "not_public_high_volume",
        )
    )
    if not not_high_volume_context and any(
        token in text
        for token in (
            "high_volume_public_user",
            "high-volume public",
            "public power user",
            "context_only_high_volume",
        )
    ):
        suppressors.append("high_volume_public_user")
    return _dedupe(suppressors)


def _row_search_text(row: Mapping[str, Any]) -> str:
    values: list[str] = []
    for source in _lookup_sources(row):
        for key, value in source.items():
            if key.startswith("_audit"):
                continue
            if isinstance(value, (str, int, float, bool)):
                values.append(str(value))
            elif isinstance(value, list):
                values.extend(str(item) for item in value)
    return " ".join(values).lower()


def _row_id(row: Mapping[str, Any]) -> str:
    return _string_value(
        row,
        "id",
        "trade_id",
        "tradeId",
        "wallet",
        "condition_id",
        "conditionId",
    ) or "unknown"


def _add_warning(
    warnings: dict[str, dict[str, Any]],
    code: str,
    message: str,
    record: Mapping[str, Any],
) -> None:
    item = warnings.setdefault(code, {"code": code, "message": message, "count": 0, "examples": []})
    item["count"] += 1
    if len(item["examples"]) < 5:
        item["examples"].append(
            {
                "source_path": record.get("source_path", ""),
                "source_row": record.get("source_row", ""),
                "row_id": record.get("row_id", ""),
                "wallet": record.get("wallet", ""),
                "severity": record.get("severity", ""),
                "judgment": record.get("judgment", ""),
                "hardEvidenceSources": record.get("hard_evidence_sources", []),
                "fundingEvidenceGrade": record.get("funding_evidence_grade", ""),
                "suspiciousFundingQuality": record.get("suspicious_funding_quality", ""),
                "suspiciousFundingHardEvidenceEligible": record.get("suspicious_funding_hard_eligible", ""),
                "suspiciousFundingIndependentSupport": record.get("suspicious_funding_independent_support", ""),
                "suspiciousFundingIndependentSupportSources": record.get("suspicious_funding_independent_support_sources", []),
                "suspiciousFundingSuppressorConflict": record.get("suspicious_funding_suppressor_conflict", ""),
                "suspiciousFundingSuppressorConflictReasons": record.get("suspicious_funding_suppressor_conflict_reasons", []),
                "fundingResolverAvailable": record.get("funding_resolver_available", ""),
                "fundingResolverAuthError": record.get("funding_resolver_auth_error", ""),
                "repricingSourceQuality": record.get("repricing_source_quality", ""),
                "candidateAdmissionReason": record.get("candidate_admission_reason", ""),
                "candidateAdmissionStage": record.get("candidate_admission_stage", ""),
                "groupedCandidateId": record.get("grouped_candidate_id", ""),
                "rawIndependentSupportSources": record.get("raw_independent_support_sources", []),
                "strongRiskGateType": record.get("strong_risk_gate_type", ""),
                "strongRiskExactGateBranch": record.get("strong_risk_exact_gate_branch", ""),
                "strongRiskCompositionClass": record.get("strong_risk_composition_class", ""),
                "strongRiskGateEvidenceSources": record.get("strong_risk_gate_evidence_sources", []),
                "strongRiskTimingProofSources": record.get("strong_risk_timing_proof_sources", []),
                "strongRiskStructuralSources": record.get("strong_risk_structural_sources", []),
                "strongRiskStructuralSourcesResolved": record.get("strong_risk_structural_sources_resolved", []),
                "strongRiskSourceAttributionIssue": record.get("strong_risk_source_attribution_issue", ""),
                "strongRiskStructuralButNotHardEvidence": record.get("strong_risk_structural_but_not_hard_evidence", False),
                "strongRiskStructuralButNotHardEvidenceSources": record.get("strong_risk_structural_but_not_hard_evidence_sources", []),
                "strongRiskScoreOnlyResolution": record.get("strong_risk_score_only_resolution", ""),
                "strongRiskGateLeakageCandidate": record.get("strong_risk_gate_leakage_candidate", False),
                "strongRiskSuppressorConflictReasons": record.get("strong_risk_suppressor_conflict_reasons", []),
            }
        )


def _hard_review_source_count(records: Iterable[Mapping[str, Any]], source: str) -> int:
    return sum(1 for record in records if source in record.get("hard_evidence_sources", []))


def _example_records(records: Iterable[Mapping[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for record in records:
        if len(examples) >= limit:
            break
        examples.append(
            {
                "source_path": record.get("source_path", ""),
                "source_row": record.get("source_row", ""),
                "row_id": record.get("row_id", ""),
                "wallet": record.get("wallet", ""),
                "severity": record.get("severity", ""),
                "judgment": record.get("judgment", ""),
                "hardEvidenceSources": record.get("hard_evidence_sources", []),
                "rawIndependentSupportSources": record.get("raw_independent_support_sources", []),
                "strongRiskGateType": record.get("strong_risk_gate_type", ""),
                "strongRiskExactGateBranch": record.get("strong_risk_exact_gate_branch", ""),
                "strongRiskCompositionClass": record.get("strong_risk_composition_class", ""),
                "strongRiskGateEvidenceSources": record.get("strong_risk_gate_evidence_sources", []),
                "strongRiskStructuralSourcesResolved": record.get("strong_risk_structural_sources_resolved", []),
                "strongRiskSourceAttributionIssue": record.get("strong_risk_source_attribution_issue", ""),
                "strongRiskStructuralButNotHardEvidence": record.get("strong_risk_structural_but_not_hard_evidence", False),
                "strongRiskStructuralButNotHardEvidenceSources": record.get("strong_risk_structural_but_not_hard_evidence_sources", []),
            }
        )
    return examples


def _strong_risk_top_rows(records: Iterable[Mapping[str, Any]], *, limit: int = 50) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordered = sorted(
        records,
        key=lambda record: (
            float(record.get("score") or 0.0),
            len(record.get("strong_risk_gate_evidence_sources") or []),
        ),
        reverse=True,
    )
    for record in ordered[:limit]:
        rows.append(
            {
                "trade_id": record.get("row_id", ""),
                "wallet": record.get("wallet", ""),
                "condition_id": record.get("condition_id", ""),
                "market_title": record.get("market_title", ""),
                "score": record.get("score"),
                "gate_type": record.get("strong_risk_gate_type", ""),
                "exactGateBranch": record.get("strong_risk_exact_gate_branch", ""),
                "composition_class": record.get("strong_risk_composition_class", ""),
                "scoreOnlyResolution": record.get("strong_risk_score_only_resolution", ""),
                "gateLeakageCandidate": record.get("strong_risk_gate_leakage_candidate", False),
                "hardEvidenceSources": record.get("hard_evidence_sources", []),
                "timingProofSources": record.get("strong_risk_timing_proof_sources", []),
                "structuralSources": record.get("strong_risk_structural_sources", []),
                "structuralSourcesResolved": record.get("strong_risk_structural_sources_resolved", []),
                "hardEvidenceEligibleSources": record.get("strong_risk_hard_evidence_eligible_sources", []),
                "structuralButNotHardEvidence": record.get("strong_risk_structural_but_not_hard_evidence", False),
                "structuralButNotHardEvidenceSources": record.get("strong_risk_structural_but_not_hard_evidence_sources", []),
                "whyNoHardEvidence": record.get("strong_risk_why_no_hard_evidence", ""),
                "sourceAttributionIssue": record.get("strong_risk_source_attribution_issue", ""),
                "suppressorConflicts": record.get("strong_risk_suppressor_conflict_reasons", []),
                "openingExposureConfirmed": record.get("strong_risk_opening_exposure_confirmed", False),
                "liveDetectable": record.get("strong_risk_live_detectable", False),
                "retrospectiveOnly": record.get("strong_risk_retrospective_only", False),
                "repricingSourceQuality": record.get("repricing_source_quality", ""),
                "fundingEvidenceGrade": record.get("funding_evidence_grade", ""),
                "suspiciousFundingQuality": record.get("suspicious_funding_quality", ""),
                "reasonsAgainst": record.get("reasons_against", []),
                "source_path": record.get("source_path", ""),
                "source_row": record.get("source_row", ""),
            }
        )
    return rows


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _next_actions(warnings: list[Mapping[str, Any]], legacy_or_unknown_rows: int) -> dict[str, str]:
    warning_codes = {str(item.get("code") or "") for item in warnings}
    schema_codes = {
        "missing_hard_evidence_sources",
        "missing_funding_evidence_grade",
        "missing_repricing_source_quality",
        "missing_candidate_admission_reason",
        "missing_grouped_candidate_id",
        "pre_admission_funding_trace_zero_with_grouped_subthreshold",
        "funding_none_with_resolver_unavailable",
        "funding_none_with_zero_trace_coverage",
        "cached_failure_used_as_funding_evidence",
        "cached_unknown_used_as_none",
        "persistent_cache_disabled_fresh_validation",
        "missing_resolver_disabled_reason",
        "report_implies_no_strict_funding_without_trace_available",
        "suspicious_funding_suppressor_conflict_missing",
        "suspicious_funding_independent_support_missing_sources",
    }
    starvation_codes = {
        "independent_evidence_not_routed_hard_evidence_review",
    }
    overbroad_codes = {
        "cex_proxy_only_hard_evidence_review",
        "high_impact_repricing_only_hard_evidence_review",
        "mechanical_repricing_marked_hard_evidence",
        "proxy_only_grouped_admission_hard_evidence_review",
        "proxy_only_group_claims_strict_funding",
        "high_impact_repricing_only_pre_admission",
        "mechanical_repricing_pre_admission",
        "suppressed_context_only_pre_admission",
        "unknown_funding_grade_grouped_admission",
        "validated_admission_missing_opening_exposure_confirmation",
        "event_family_only_pre_admission",
        "low_probability_winner_only_pre_admission",
        "strict_funding_groups_found_without_admission_attempts",
        "strict_funding_admission_with_resolver_unavailable",
        "strict_funding_admission_zero_trace_coverage",
        "funding_hard_evidence_with_resolver_unavailable",
        "resolver_unavailable_structural_pre_admission",
        "suspicious_funding_only_suppressor_conflict",
        "multi_hop_unknown_strong_without_independent_support",
        "multi_hop_unknown_hard_evidence_without_independent_support",
        "weak_suspicious_funding_only_hard_evidence_review",
        "unknown_suspicious_funding_hard_evidence_review",
    }
    return {
        "safe": "yes" if not warnings else "no",
        "needs_manual_review": "yes" if "strong_risk_without_existing_gate" in warning_codes else "no",
        "schema_issue": "yes" if warning_codes & schema_codes or legacy_or_unknown_rows else "no",
        "possible_overbroad_hard_evidence_review": "yes" if warning_codes & overbroad_codes else "no",
        "possible_hidden_false_positives": "yes" if warning_codes & overbroad_codes else "no",
        "possible_hidden_false_negatives": "yes" if warning_codes & starvation_codes else "no",
    }


def _classify_large_sample(
    *,
    warning_codes: set[str],
    funnel_summary: Mapping[str, Any],
    hard_evidence_pathway_counts: Mapping[str, int],
    strong_risk_composition: Mapping[str, Any],
    hard_evidence_starvation: Mapping[str, Any],
    strong_risk_rows: int,
) -> str:
    trace_attempts = int(funnel_summary.get("funding_trace_attempted_count") or 0)
    trace_coverage = float(funnel_summary.get("funding_trace_coverage_ratio") or 0.0)
    resolver_unavailable = int(funnel_summary.get("pre_admission_runs_with_resolver_unavailable") or 0)
    production_trace_bundles = int(funnel_summary.get("production_trace_succeeded_bundle_count") or 0)
    if trace_attempts > 0 and (trace_coverage < 0.5 or production_trace_bundles == 0 or resolver_unavailable > 0):
        return "funding-blocked sample"

    overbroad_warning_codes = {
        "cex_proxy_only_hard_evidence_review",
        "cex_bridge_proxy_suspicious_funding_hard_evidence_review",
        "high_impact_repricing_only_hard_evidence_review",
        "mechanical_repricing_marked_hard_evidence",
        "weak_suspicious_funding_only_hard_evidence_review",
        "unknown_suspicious_funding_hard_evidence_review",
        "suspicious_funding_only_suppressor_conflict",
        "multi_hop_unknown_hard_evidence_without_independent_support",
        "multi_hop_unknown_strong_without_independent_support",
    }
    overbroad_counts = (
        int(hard_evidence_pathway_counts.get("suspicious_funding_only_hard_evidence_review_with_suppressors") or 0)
        + int(hard_evidence_pathway_counts.get("multi_hop_unknown_hard_evidence_review_without_independent_support") or 0)
        + int(hard_evidence_pathway_counts.get("weak_suspicious_funding_hard_evidence_review_rows") or 0)
        + int(hard_evidence_pathway_counts.get("unknown_suspicious_funding_hard_evidence_review_rows") or 0)
        + int(hard_evidence_pathway_counts.get("cex_bridge_proxy_only_hard_evidence_review_rows") or 0)
        + int(hard_evidence_pathway_counts.get("high_impact_repricing_only_hard_evidence_review_rows") or 0)
    )
    if overbroad_counts or warning_codes & overbroad_warning_codes:
        return "suspicious funding still overbroad"

    if int(hard_evidence_starvation.get("independent_sources_not_routed_to_hard_evidence_review_rows") or 0) > 0:
        return "hard-evidence starvation suspected"

    if strong_risk_rows:
        leakage = int(strong_risk_composition.get("strong_risk_gate_leakage_candidate_rows") or 0)
        missing_exact = int(strong_risk_composition.get("strong_risk_new_format_missing_exact_gate_branch_rows") or 0)
        issue_dist = strong_risk_composition.get("strong_risk_rows_by_source_attribution_issue")
        propagation_or_export = 0
        if isinstance(issue_dist, Mapping):
            propagation_or_export = int(issue_dist.get("schema_propagation_gap") or 0) + int(
                issue_dist.get("hard_evidence_source_missing") or 0
            )
            problematic = propagation_or_export + int(issue_dist.get("inference_insufficient") or 0)
            if propagation_or_export and propagation_or_export >= max(1, problematic // 2):
                return "source-attribution repair needed"
        suppressor_no_structure = int(
            strong_risk_composition.get("strong_risk_suppressor_conflict_without_structure_rows") or 0
        )
        timing_only_attributed = int(strong_risk_composition.get("strong_risk_timing_only_rows") or 0)
        weak_repricing = int(
            strong_risk_composition.get("strong_risk_weak_mechanical_unknown_repricing_rows") or 0
        )
        if (
            leakage
            or missing_exact
            or (suppressor_no_structure / strong_risk_rows) > 0.2
            or (timing_only_attributed / strong_risk_rows > 0.5 and weak_repricing)
        ):
            return "strong-risk composition concern"
        no_sources = int(strong_risk_composition.get("strong_risk_rows_with_no_hard_evidence_sources") or 0)
        timing_only = int(strong_risk_composition.get("strong_risk_rows_driven_by_timing_repricing_only") or 0)
        structured = int(strong_risk_composition.get("strong_risk_rows_driven_by_structure") or 0)
        if structured == 0 and (no_sources + timing_only) / strong_risk_rows >= 0.5:
            return "strong-risk composition concern"

    return "post-v2 behavior acceptable"


def _render_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Model Behavior Audit",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Large-sample classification: {summary.get('large_sample_classification', 'not_classified')}",
        f"- Total rows inspected: {summary.get('total_rows_inspected', 0)}",
        f"- Event Forensic rows inspected: {summary.get('event_forensic_rows_inspected', 0)}",
        f"- Archive rows inspected: {summary.get('archive_rows_inspected', 0)}",
        f"- AI Review rows inspected: {summary.get('ai_review_rows_inspected', 0)}",
        f"- Visible rows: {summary.get('rawVisibleRows', summary.get('visible_rows', 0))} raw / {summary.get('uniqueVisibleRows', 'unknown')} unique (dedupe ratio {summary.get('visibleDedupeRatio', 'unknown')})",
        f"- Strong Risk rows: {summary.get('rawStrongRiskRows', summary.get('strong_risk_rows', 0))} raw / {summary.get('uniqueStrongRiskRows', 'unknown')} unique (dedupe ratio {summary.get('strongRiskDedupeRatio', 'unknown')})",
        f"- Hard Evidence Review rows: {summary.get('rawHardEvidenceReviewRows', summary.get('hard_evidence_review_rows', 0))} raw / {summary.get('uniqueHardEvidenceReviewRows', 'unknown')} unique (dedupe ratio {summary.get('hardEvidenceReviewDedupeRatio', 'unknown')})",
        f"- Hard Evidence Review share of visible rows: {summary.get('hard_evidence_review_share_of_visible_rows', 0)}",
        f"- Normal candidate rows: {summary.get('normal_candidate_rows', 0)}",
        f"- Pre-admitted candidate rows: {summary.get('pre_admitted_candidate_rows', 0)}",
        f"- Proxy-only grouped admissions: {summary.get('proxy_only_grouped_admissions', 0)}",
        f"- Proxy-only grouped admissions surfaced as Hard Evidence Review: {summary.get('proxy_only_grouped_admissions_hard_evidence_review', 0)}",
        f"- High-impact-repricing-only pre-admissions: {summary.get('high_impact_repricing_only_pre_admissions', 0)}",
        f"- Mechanical-repricing pre-admissions: {summary.get('mechanical_repricing_pre_admissions', 0)}",
        f"- Near-certainty/yield/theta/stale-only pre-admissions: {summary.get('near_certainty_yield_theta_stale_only_pre_admissions', 0)}",
        f"- Suspicious funding hard-evidence eligible rows: {summary.get('suspicious_funding_hard_evidence_eligible_rows', 0)}",
        f"- Suspicious funding-only Hard Evidence Review rows: {summary.get('suspicious_funding_only_hard_evidence_review_rows', 0)}",
        f"- Suspicious funding-only Hard Evidence Review rows with suppressors: {summary.get('suspicious_funding_only_hard_evidence_review_with_suppressors', 0)}",
        f"- Multi-hop unknown Hard Evidence Review rows: {summary.get('multi_hop_unknown_hard_evidence_review_rows', 0)}",
        f"- Multi-hop unknown Hard Evidence Review rows without independent support: {summary.get('multi_hop_unknown_hard_evidence_review_without_independent_support', 0)}",
        f"- Multi-hop unknown strong rows without independent support: {summary.get('multi_hop_unknown_strong_without_independent_support_rows', 0)}",
        f"- Persistent funding cache hit rows: {summary.get('funding_trace_persistent_cache_hit_rows', 0)}",
        f"- Persistent funding cache hit/miss/write counts: {summary.get('funding_trace_persistent_cache_hit_count', 0)}/{summary.get('funding_trace_persistent_cache_miss_count', 0)}/{summary.get('funding_trace_persistent_cache_write_count', 0)}",
        f"- Persistent funding cache hit rate: {summary.get('funding_trace_persistent_cache_hit_rate', 0)}",
        f"- Legacy/unknown schema rows: {summary.get('legacy_or_unknown_schema_rows', 0)}",
        f"- Strong Risk rows with unknown gate fields: {summary.get('strong_gate_unknown_rows', 0)}",
        "",
        "## Pre-Admission Funnel",
    ]
    funnel = summary.get("pre_admission_funnel", {})
    if isinstance(funnel, Mapping):
        lines.extend(
            [
                f"- Funnel files inspected: {funnel.get('funnel_file_count', 0)}",
                f"- Structural pre-admission attempts: {funnel.get('total_structural_pre_admission_attempts', 0)}",
                f"- Validated pre-admissions: {funnel.get('total_validated', 0)}",
                f"- Rejected after scoring: {funnel.get('total_rejected_after_scoring', 0)}",
                f"- Near-miss groups: {funnel.get('total_near_miss_groups', 0)}",
                f"- Sub-threshold above-floor trades: {funnel.get('subthreshold_above_floor_trades', 0)}",
                f"- Grouped sub-threshold groups: {funnel.get('grouped_subthreshold_groups', 0)}",
                f"- Strict funding groups found: {funnel.get('strict_funding_groups_found', 0)}",
                f"- Proxy-only groups found: {funnel.get('proxy_only_groups_found', 0)}",
                f"- Funding unknown count: {funnel.get('funding_unknown_count', 0)}",
                f"- Funding unknown rate: {funnel.get('funding_unknown_rate', 0)}",
                f"- Funding resolver availability by bundle: {funnel.get('funding_resolver_availability', {})}",
                f"- Funding resolver functional statuses: {funnel.get('funding_resolver_functional_statuses', {})}",
                f"- Funding resolver unavailable reasons: {funnel.get('funding_resolver_unavailable_reasons', {})}",
                f"- Auth-error bundle count: {funnel.get('auth_error_bundle_count', 0)}",
                f"- Lightweight-health available bundles: {funnel.get('lightweight_health_available_bundle_count', 0)}",
                f"- Funding-trace-health available bundles: {funnel.get('funding_trace_health_available_bundle_count', 0)}",
                f"- Rate-limited bundles: {funnel.get('rate_limited_bundle_count', 0)}",
                f"- Lightweight available but trace failed bundles: {funnel.get('lightweight_available_but_trace_failed_bundle_count', 0)}",
                f"- Production trace succeeded bundles: {funnel.get('production_trace_succeeded_bundle_count', 0)}",
                f"- Endpoint pool size max/avg: {funnel.get('funding_trace_endpoint_pool_size_max', 0)}/{funnel.get('funding_trace_endpoint_pool_size_average', 0)}",
                f"- Funding trace attempted/succeeded/failed/skipped: {funnel.get('funding_trace_attempted_count', 0)}/{funnel.get('funding_trace_succeeded_count', 0)}/{funnel.get('funding_trace_failed_count', 0)}/{funnel.get('funding_trace_skipped_count', 0)}",
                f"- Pre-admission trace attempted/succeeded/failed/skipped: {funnel.get('pre_admission_funding_trace_attempted_count', 0)}/{funnel.get('pre_admission_funding_trace_succeeded_count', 0)}/{funnel.get('pre_admission_funding_trace_failed_count', 0)}/{funnel.get('pre_admission_funding_trace_skipped_count', 0)}",
                f"- Funding trace retries/fallbacks/rate-limits: {funnel.get('funding_trace_retry_count', 0)}/{funnel.get('funding_trace_fallback_endpoint_count', 0)}/{funnel.get('funding_trace_rate_limited_count', 0)}",
                f"- Funding trace log chunks attempted/succeeded/failed/rate-limited: {funnel.get('funding_trace_log_chunks_attempted', 0)}/{funnel.get('funding_trace_log_chunks_succeeded', 0)}/{funnel.get('funding_trace_log_chunks_failed', 0)}/{funnel.get('funding_trace_log_chunks_rate_limited', 0)}",
                f"- Funding trace cache hits/misses: {funnel.get('funding_trace_cache_hit_count', 0)}/{funnel.get('funding_trace_cache_miss_count', 0)}",
                f"- Persistent cache enabled bundles: {funnel.get('funding_trace_persistent_cache_enabled_bundle_count', 0)}",
                f"- Persistent cache hits/misses/writes/expired/failure-cooldowns: {funnel.get('funding_trace_persistent_cache_hit_count', 0)}/{funnel.get('funding_trace_persistent_cache_miss_count', 0)}/{funnel.get('funding_trace_persistent_cache_write_count', 0)}/{funnel.get('funding_trace_persistent_cache_expired_count', 0)}/{funnel.get('funding_trace_persistent_cache_failure_cooldown_count', 0)}",
                f"- Persistent cache hit rate: {funnel.get('funding_trace_persistent_cache_hit_rate', 0)}",
                f"- Funding trace coverage ratio: {funnel.get('funding_trace_coverage_ratio', 0)}",
                f"- Resolver-unavailable pre-admission runs: {funnel.get('pre_admission_runs_with_resolver_unavailable', 0)}",
                f"- Near-miss groups with funding not assessable: {funnel.get('near_miss_groups_funding_not_assessable', 0)}",
            ]
        )
        reasons = funnel.get("top_rejection_reasons", {})
        lines.append("### Funnel Rejection Reasons")
        if isinstance(reasons, Mapping) and reasons:
            for key, count in reasons.items():
                lines.append(f"- {key}: {count}")
        else:
            lines.append("- none")
    lines.extend(["", "## Hard Evidence Pathway Counts"])
    pathway_counts = summary.get("hard_evidence_pathway_counts", {})
    if isinstance(pathway_counts, Mapping) and pathway_counts:
        for key, count in pathway_counts.items():
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- none")

    lines.extend(["", "## Strong Risk Composition"])
    strong_composition = summary.get("strong_risk_composition", {})
    if isinstance(strong_composition, Mapping) and strong_composition:
        for key, value in strong_composition.items():
            if isinstance(value, Mapping):
                lines.append(f"### {key}")
                if value:
                    for subkey, count in value.items():
                        lines.append(f"- {subkey}: {count}")
                else:
                    lines.append("- none")
            else:
                lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")

    lines.extend(["", "## Hard Evidence Starvation"])
    starvation = summary.get("hard_evidence_starvation", {})
    if isinstance(starvation, Mapping) and starvation:
        for key, value in starvation.items():
            if key.startswith("examples_"):
                continue
            if isinstance(value, Mapping):
                lines.append(f"### {key}")
                if value:
                    for subkey, count in value.items():
                        lines.append(f"- {subkey}: {count}")
                else:
                    lines.append("- none")
            else:
                lines.append(f"- {key}: {value}")
        examples = starvation.get("examples_independent_support_not_routed")
        if isinstance(examples, list) and examples:
            lines.append("### Examples independent support not routed")
            for example in examples[:5]:
                if isinstance(example, Mapping):
                    lines.append(
                        f"- {example.get('source_path', '')}:{example.get('source_row', '')} "
                        f"id={example.get('row_id', '')} raw={example.get('rawIndependentSupportSources', [])}"
                    )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
        "## Distributions",
        ]
    )
    distributions = summary.get("distributions", {})
    if isinstance(distributions, Mapping):
        for name, values in distributions.items():
            lines.append(f"### {name}")
            if isinstance(values, Mapping) and values:
                for key, count in values.items():
                    lines.append(f"- {key}: {count}")
            else:
                lines.append("- none")
    lines.extend(["", "## Hard Evidence Review by Severity/Judgment"])
    cross_tabs = summary.get("cross_tabs", {})
    hard_tab = cross_tabs.get("hardEvidenceReview_by_severity_judgment", {}) if isinstance(cross_tabs, Mapping) else {}
    if isinstance(hard_tab, Mapping) and hard_tab:
        for key, count in hard_tab.items():
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- none")

    lines.extend(["", "## Suppressors on Hard Evidence Review Rows"])
    suppressors = summary.get("hard_evidence_review_with_suppressors", {})
    if isinstance(suppressors, Mapping):
        for key in SUPPRESSOR_CODES:
            lines.append(f"- {key}: {suppressors.get(key, 0)}")

    lines.extend(["", "## Warnings"])
    warnings = summary.get("warnings", [])
    if warnings:
        for warning in warnings:
            if not isinstance(warning, Mapping):
                continue
            lines.append(f"- {warning.get('code')}: {warning.get('count', 0)} - {warning.get('message', '')}")
            examples = warning.get("examples", [])
            if isinstance(examples, list):
                for example in examples[:3]:
                    if isinstance(example, Mapping):
                        source = example.get("source_path") or "synthetic"
                        row = example.get("source_row") or ""
                        row_label = f":{row}" if row else ""
                        lines.append(
                            f"  - {source}{row_label} id={example.get('row_id', '')} "
                            f"sources={example.get('hardEvidenceSources', [])}"
                        )
    else:
        lines.append("- none")

    lines.extend(["", "## Next Action"])
    next_actions = summary.get("next_actions", {})
    if isinstance(next_actions, Mapping):
        for key in (
            "safe",
            "needs_manual_review",
            "schema_issue",
            "possible_overbroad_hard_evidence_review",
            "possible_hidden_false_positives",
            "possible_hidden_false_negatives",
        ):
            lines.append(f"- {key.replace('_', ' ')}: {next_actions.get(key, 'no')}")
    lines.append("")
    return "\n".join(lines)


def _render_strong_risk_deep_dive_markdown(payload: Mapping[str, Any]) -> str:
    composition = payload.get("strong_risk_composition", {})
    if not isinstance(composition, Mapping):
        composition = {}
    deep = payload.get("strong_risk_deep_dive", {})
    if not isinstance(deep, Mapping):
        deep = {}
    lines = [
        "# Strong Risk Deep Dive",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Strong Risk rows total: {payload.get('rawStrongRiskRows', payload.get('strong_risk_rows', 0))} raw / {payload.get('uniqueStrongRiskRows', 'unknown')} unique (dedupe ratio {payload.get('strongRiskDedupeRatio', 'unknown')})",
        f"- Live-detectable Strong Risk rows: {composition.get('strong_risk_live_detectable_rows', 0)}",
        f"- Retrospective-only Strong Risk rows: {composition.get('strong_risk_retrospective_only_rows_exact', composition.get('strong_risk_retrospective_only_rows', 0))}",
        f"- Strong Risk rows with no hardEvidenceSources: {composition.get('strong_risk_rows_with_no_hard_evidence_sources', 0)}",
        f"- Strong Risk rows with no gate evidence sources: {composition.get('strong_risk_rows_with_no_gate_evidence_sources', 0)}",
        f"- Score-only Strong Risk rows: {composition.get('strong_risk_score_only_rows', 0)}",
        f"- Score-only after exact provenance: {composition.get('strong_risk_score_only_after_exact_provenance_rows', 0)}",
        f"- Gate leakage candidate rows: {composition.get('strong_risk_gate_leakage_candidate_rows', 0)}",
        f"- Exact gate branch missing rows: {composition.get('strong_risk_new_format_missing_exact_gate_branch_rows', 0)}",
        f"- Exact/inferred gate disagreements: {composition.get('strong_risk_exact_inferred_gate_disagree_rows', 0)}",
        f"- Timing-only Strong Risk rows: {composition.get('strong_risk_timing_only_rows', 0)}",
        f"- Structure-led Strong Risk rows: {composition.get('strong_risk_structure_led_rows', 0)}",
        f"- Mixed timing/structure Strong Risk rows: {composition.get('strong_risk_mixed_timing_structure_rows', 0)}",
        f"- Retrospective-only Strong Risk rows: {composition.get('strong_risk_retrospective_only_rows', 0)}",
        f"- Suppressor-conflict Strong Risk rows: {composition.get('strong_risk_suppressor_conflict_rows', 0)}",
        f"- Opening exposure not confirmed: {composition.get('strong_risk_rows_opening_exposure_not_confirmed', 0)}",
        f"- Weak/mechanical/unknown repricing rows: {composition.get('strong_risk_weak_mechanical_unknown_repricing_rows', 0)}",
        f"- Structural-but-not-Hard-Evidence rows: {composition.get('strong_risk_structural_but_not_hard_evidence_rows', 0)}",
        "",
        "## Gate Type Distribution",
    ]
    gate_dist = composition.get("strong_risk_rows_by_gate_type", {})
    if isinstance(gate_dist, Mapping) and gate_dist:
        for key, count in gate_dist.items():
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- none")
    lines.append("## Composition Class Distribution")
    class_dist = composition.get("strong_risk_rows_by_composition_class", {})
    if isinstance(class_dist, Mapping) and class_dist:
        for key, count in class_dist.items():
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- none")
    lines.append("## Exact Gate Branch Distribution")
    exact_dist = composition.get("strong_risk_rows_by_exact_gate_branch", {})
    if isinstance(exact_dist, Mapping) and exact_dist:
        for key, count in exact_dist.items():
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- none")
    lines.append("## Source Attribution Issue Distribution")
    issue_dist = composition.get("strong_risk_rows_by_source_attribution_issue", {})
    if isinstance(issue_dist, Mapping) and issue_dist:
        for key, count in issue_dist.items():
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- none")
    lines.append("## Structural But Not Hard Evidence")
    lines.append(
        "- Strong Risk can be structure-led without being Hard Evidence Review when the structure is non-hard, "
        "for example wallet_size_anomaly or domain_peer_outlier. This section is explanatory only and does not change severity."
    )
    non_hard_sources = composition.get("strong_risk_structural_but_not_hard_evidence_sources", {})
    if isinstance(non_hard_sources, Mapping) and non_hard_sources:
        for key, count in non_hard_sources.items():
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- none")
    lines.append("## Diagnostic Answers")
    diagnostic_keys = [
        "no_hard_evidence_rows_by_gate_type",
        "confirmed_opening_exposure_rows",
        "strong_timing_proof_rows",
        "repricing_dependent_rows",
        "weak_mechanical_unknown_repricing_rows",
        "suppressor_conflict_rows",
        "high_volume_bot_stale_specialist_without_structure_rows",
        "credible_if_timing_repricing_advisory_only_rows",
        "hard_sources_missing_because_schema_propagation_rows",
        "hard_sources_missing_because_no_structural_evidence_rows",
        "possible_strong_risk_gate_leakage_rows",
    ]
    for key in diagnostic_keys:
        value = deep.get(key)
        if isinstance(value, Mapping):
            lines.append(f"### {key}")
            if value:
                for subkey, count in value.items():
                    lines.append(f"- {subkey}: {count}")
            else:
                lines.append("- none")
        else:
            lines.append(f"- {key}: {value if value is not None else 0}")
    rows = deep.get("top_strong_risk_rows", [])
    lines.extend(["", "## Top Strong Risk Rows"])
    if isinstance(rows, list) and rows:
        for row in rows[:50]:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "- "
                f"id={row.get('trade_id', '')} wallet={row.get('wallet', '')} "
                f"score={row.get('score', '')} gate={row.get('gate_type', '')} "
                f"exact={row.get('exactGateBranch', '')} class={row.get('composition_class', '')} "
                f"leak={row.get('gateLeakageCandidate', False)} issue={row.get('sourceAttributionIssue', '')} "
                f"timing={row.get('timingProofSources', [])} "
                f"structure={row.get('structuralSourcesResolved', row.get('structuralSources', []))} "
                f"suppressors={row.get('suppressorConflicts', [])}"
            )
    else:
        lines.append("- none")
    warnings = payload.get("warnings", [])
    lines.extend(["", "## Strong Risk Warnings"])
    if isinstance(warnings, list) and warnings:
        for warning in warnings:
            if isinstance(warning, Mapping):
                lines.append(f"- {warning.get('code')}: {warning.get('count', 0)}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _print_cli_summary(summary: Mapping[str, Any], outputs: Mapping[str, str]) -> None:
    print(f"Rows inspected: {summary.get('total_rows_inspected', 0)}")
    print(f"Event Forensic rows: {summary.get('event_forensic_rows_inspected', 0)}")
    print(f"Archive rows: {summary.get('archive_rows_inspected', 0)}")
    print(
        "Visible rows: "
        f"{summary.get('rawVisibleRows', summary.get('visible_rows', 0))} raw / "
        f"{summary.get('uniqueVisibleRows', 'unknown')} unique "
        f"(dedupe ratio {summary.get('visibleDedupeRatio', 'unknown')})"
    )
    print(
        "Strong Risk rows: "
        f"{summary.get('rawStrongRiskRows', summary.get('strong_risk_rows', 0))} raw / "
        f"{summary.get('uniqueStrongRiskRows', 'unknown')} unique "
        f"(dedupe ratio {summary.get('strongRiskDedupeRatio', 'unknown')})"
    )
    print(
        "Hard Evidence Review rows: "
        f"{summary.get('rawHardEvidenceReviewRows', summary.get('hard_evidence_review_rows', 0))} raw / "
        f"{summary.get('uniqueHardEvidenceReviewRows', 'unknown')} unique "
        f"(dedupe ratio {summary.get('hardEvidenceReviewDedupeRatio', 'unknown')})"
    )
    print(f"Large-sample classification: {summary.get('large_sample_classification', 'not_classified')}")
    funnel = summary.get("pre_admission_funnel", {})
    if isinstance(funnel, Mapping) and funnel.get("funnel_file_count", 0):
        print(f"Pre-admission attempts: {funnel.get('total_structural_pre_admission_attempts', 0)}")
        print(f"Validated pre-admissions: {funnel.get('total_validated', 0)}")
        print(f"Near-miss groups: {funnel.get('total_near_miss_groups', 0)}")
        print(f"Funding resolver availability: {funnel.get('funding_resolver_availability', {})}")
        print(f"Funding resolver functional statuses: {funnel.get('funding_resolver_functional_statuses', {})}")
        print(f"Rate-limited bundles: {funnel.get('rate_limited_bundle_count', 0)}")
        print(f"Funding trace attempted/succeeded/failed/skipped: {funnel.get('funding_trace_attempted_count', 0)}/{funnel.get('funding_trace_succeeded_count', 0)}/{funnel.get('funding_trace_failed_count', 0)}/{funnel.get('funding_trace_skipped_count', 0)}")
        print(f"Pre-admission trace attempted/succeeded/failed/skipped: {funnel.get('pre_admission_funding_trace_attempted_count', 0)}/{funnel.get('pre_admission_funding_trace_succeeded_count', 0)}/{funnel.get('pre_admission_funding_trace_failed_count', 0)}/{funnel.get('pre_admission_funding_trace_skipped_count', 0)}")
        print(f"Funding trace retries/fallbacks/rate-limits: {funnel.get('funding_trace_retry_count', 0)}/{funnel.get('funding_trace_fallback_endpoint_count', 0)}/{funnel.get('funding_trace_rate_limited_count', 0)}")
        print(f"Funding trace log chunks attempted/succeeded/failed: {funnel.get('funding_trace_log_chunks_attempted', 0)}/{funnel.get('funding_trace_log_chunks_succeeded', 0)}/{funnel.get('funding_trace_log_chunks_failed', 0)}")
        print(f"Persistent cache hits/misses/writes: {funnel.get('funding_trace_persistent_cache_hit_count', 0)}/{funnel.get('funding_trace_persistent_cache_miss_count', 0)}/{funnel.get('funding_trace_persistent_cache_write_count', 0)}")
    warnings = summary.get("warnings", [])
    if warnings:
        print("Warnings:")
        for warning in warnings:
            if isinstance(warning, Mapping):
                print(f"- {warning.get('code')}: {warning.get('count', 0)}")
    else:
        print("Warnings: none")
    print(f"Markdown: {outputs.get('markdown_path', '')}")
    print(f"JSON: {outputs.get('json_path', '')}")
    if outputs.get("strong_risk_deep_dive_markdown_path"):
        print(f"Strong Risk deep dive markdown: {outputs.get('strong_risk_deep_dive_markdown_path', '')}")
        print(f"Strong Risk deep dive JSON: {outputs.get('strong_risk_deep_dive_json_path', '')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit saved InsPoly output fields without rescoring or external APIs."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Saved output files or directories. Defaults to event_forensic_outputs, archive_outputs, and ai_review_outputs when present.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--large-sample-post-v2",
        action="store_true",
        help="Write large_sample_post_v2_<timestamp> outputs for post-v2 validation runs.",
    )
    parser.add_argument(
        "--output-prefix",
        default="",
        help="Optional output filename prefix. Overrides --large-sample-post-v2 when provided.",
    )
    args = parser.parse_args()

    input_paths = args.paths or [path for path in DEFAULT_INPUT_DIRS if path.exists()]
    if not input_paths:
        print("No input paths found. Pass one or more saved output files/directories.", file=sys.stderr)
        raise SystemExit(2)

    records = collect_records(input_paths)
    funnels = collect_funnels(input_paths)
    summary = audit_records(records, funnels=funnels)
    summary["input_paths"] = [str(path) for path in input_paths]
    output_prefix = args.output_prefix or (
        "large_sample_post_v2" if args.large_sample_post_v2 else "model_behavior_audit"
    )
    outputs = write_audit_outputs(summary, args.output_dir, filename_prefix=output_prefix)
    deep_dive_outputs = write_strong_risk_deep_dive_outputs(summary, args.output_dir)
    outputs = {**outputs, "strong_risk_deep_dive_markdown_path": deep_dive_outputs["markdown_path"], "strong_risk_deep_dive_json_path": deep_dive_outputs["json_path"]}
    _print_cli_summary(summary, outputs)


if __name__ == "__main__":
    main()
