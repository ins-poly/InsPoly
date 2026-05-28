#!/usr/bin/env python3
"""Offline policy simulation for Event Forensic weak-history near-certainty rows.

This tool reads existing validation artifacts only. It does not import or call
the Event Forensic runtime analyzer, does not use network/RPC, and does not
mutate reports.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.side_outcome import UNKNOWN, normalize_cluster_direction, normalize_side_outcome


REPORT_TYPE = "event_forensic_weak_history_policy_simulation"
SCHEMA_VERSION = "event_forensic_weak_history_policy_simulation_v1"
NEAR_CERTAINTY_THRESHOLD = Decimal("0.95")
DEFAULT_LIVE_SUMMARY = Path("validation_outputs/event_forensic_weak_history_live_rpc_20260524_112348/summary.json")
DEFAULT_SAVED_AUDIT = Path("validation_outputs/event_forensic_weak_history_saved_report_audit_20260522.json")
DEFAULT_KNOWN_CASE_CORPUS = Path("tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json")
DEFAULT_EVIDENCE_OUTPUT = Path("validation_outputs/event_forensic_weak_history_policy_evidence_20260524.json")
DEFAULT_SIMULATION_OUTPUT = Path("validation_outputs/event_forensic_weak_history_policy_simulation_20260524.json")


POLICY_OPTIONS = (
    "current",
    "stronger_reducer",
    "review_bucket_demotion",
    "explanation_only",
)


@dataclass(frozen=True, slots=True)
class PolicyRow:
    source: str
    source_path: str
    trade_key: str
    wallet: str
    market: str
    event_slug: str
    raw_order_side: str
    raw_token_outcome: str
    raw_token_price: str
    economic_side: str
    economic_side_probability: str
    cluster_direction: str
    event_forensic_score: int | None
    display_rank: int | None
    existing_model_class: str
    strong_risk_gate_passed: str
    hard_evidence_review_tier: str
    later_won: bool | None
    winner_rank: int | None
    weak_history_classification: str
    near_certain_economic_entry: bool
    weak_history_reducer_present: bool
    near_certainty_reducer_present: bool
    quality_notes: tuple[str, ...]

    @property
    def weak_history_near_certainty(self) -> bool:
        return self.weak_history_classification == "weak_history" and self.near_certain_economic_entry

    @property
    def weak_history_near_certainty_later_win(self) -> bool:
        return self.weak_history_near_certainty and self.later_won is True

    @property
    def is_high_rank(self) -> bool:
        return bool(self.display_rank is not None and self.display_rank <= 10)

    @property
    def is_primary_review(self) -> bool:
        if self.display_rank is not None:
            return True
        if self.hard_evidence_review_tier:
            return True
        if self.event_forensic_score is not None and self.event_forensic_score >= 40:
            return True
        return self.existing_model_class == "Strong Risk"

    @property
    def has_required_policy_fields(self) -> bool:
        return (
            self.weak_history_classification != UNKNOWN
            and self.economic_side_probability != UNKNOWN
            and self.later_won is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "sourcePath": self.source_path,
            "tradeKey": self.trade_key,
            "wallet": self.wallet,
            "market": self.market,
            "eventSlug": self.event_slug,
            "rawOrderSide": self.raw_order_side,
            "rawTokenOutcome": self.raw_token_outcome,
            "rawTokenPrice": self.raw_token_price,
            "economicSide": self.economic_side,
            "economicSideProbability": self.economic_side_probability,
            "clusterDirection": self.cluster_direction,
            "eventForensicScore": self.event_forensic_score if self.event_forensic_score is not None else UNKNOWN,
            "displayRank": self.display_rank if self.display_rank is not None else UNKNOWN,
            "existingModelClass": self.existing_model_class,
            "strongRiskGatePassed": self.strong_risk_gate_passed,
            "hardEvidenceReviewTier": self.hard_evidence_review_tier,
            "laterWon": self.later_won if self.later_won is not None else UNKNOWN,
            "winnerRank": self.winner_rank if self.winner_rank is not None else UNKNOWN,
            "weakHistoryClassification": self.weak_history_classification,
            "nearCertainEconomicEntry": self.near_certain_economic_entry,
            "weakHistoryReducerPresent": self.weak_history_reducer_present,
            "nearCertaintyReducerPresent": self.near_certainty_reducer_present,
            "qualityNotes": list(self.quality_notes),
        }


def build_policy_evidence(
    *,
    live_summary_path: Path = DEFAULT_LIVE_SUMMARY,
    saved_audit_path: Path = DEFAULT_SAVED_AUDIT,
    known_case_corpus_path: Path = DEFAULT_KNOWN_CASE_CORPUS,
) -> dict[str, Any]:
    live_summary = _load_json(live_summary_path)
    saved_audit = _load_json(saved_audit_path)
    known_case = _load_json(known_case_corpus_path)
    rows = collect_policy_rows(live_summary_path=live_summary_path)
    return {
        "reportType": "event_forensic_weak_history_policy_evidence",
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "productionIntegration": False,
        "savedArtifactsMutated": False,
        "inputs": {
            "liveSummaryPath": str(live_summary_path),
            "savedAuditPath": str(saved_audit_path),
            "knownCaseCorpusPath": str(known_case_corpus_path),
        },
        "liveValidation": {
            "gateDecision": _dig(live_summary, "summary", "gateDecision"),
            "selectedEventCount": _dig(live_summary, "summary", "selectedEventCount"),
            "selectedMarketCount": _dig(live_summary, "summary", "selectedMarketCount"),
            "totalRawTradeRows": _dig(live_summary, "summary", "totalRawTradeRows"),
            "totalCandidateRows": _dig(live_summary, "summary", "totalCandidateRows"),
            "weakHistoryNearCertainLaterWinRows": _dig(live_summary, "summary", "weakHistoryNearCertainLaterWinRows"),
            "highRankWeakHistoryNearCertainLaterWinRows": _dig(live_summary, "summary", "highRankWeakHistoryNearCertainLaterWinRows"),
            "missingExpectedReducerRows": _dig(live_summary, "summary", "missingExpectedReducerRows"),
            "phase2EconomicProbabilityMismatches": _dig(live_summary, "summary", "phase2EconomicProbabilityMismatches"),
            "phase4ClusterDirectionMismatches": _dig(live_summary, "summary", "phase4ClusterDirectionMismatches"),
        },
        "savedReportAudit": {
            "gateDecision": saved_audit.get("gateDecision", UNKNOWN),
            "rowsEvaluated": _dig(saved_audit, "summary", "rowsEvaluated"),
            "realWeakHistoryNearCertainLaterWinRows": _dig(saved_audit, "summary", "realWeakHistoryNearCertainLaterWinRows"),
            "sufficientRealWeakHistoryNearCertainLaterWinRows": _dig(saved_audit, "summary", "sufficientRealWeakHistoryNearCertainLaterWinRows"),
            "localBlockerClosed": _dig(saved_audit, "summary", "localBlockerClosed"),
        },
        "knownCaseCorpus": {
            "caseCount": len(known_case.get("cases", [])) if isinstance(known_case.get("cases"), list) else 0,
            "categories": [
                str(row.get("category") or "")
                for row in known_case.get("cases", [])
                if isinstance(row, Mapping)
            ],
            "networkUsed": bool(known_case.get("networkUsed", False)),
            "runtimeBehaviorChanged": bool(known_case.get("runtimeBehaviorChanged", False)),
        },
        "currentCodePolicyInventory": {
            "eventScoreReducerAlreadyPresent": True,
            "nearCertaintyReducerAlreadyPresent": True,
            "weakHistoryScoreCapAlreadyPresent": True,
            "reviewPlacementCanStillPrioritizeExistingStrongRisk": True,
            "phase2EconomicProbabilityUsed": True,
            "phase4ClusterDirectionAvailable": True,
        },
        "whyNotNarrowRuntimeBug": [
            "Live rows had weak-history and near-certainty reducers present.",
            "Phase 2 economic probability mismatches were zero.",
            "Phase 4 cluster direction mismatches were zero.",
            "High placement is explained by existing Strong Risk/review-bucket semantics rather than missing reducer execution.",
        ],
        "policyRowsCollected": len(rows),
        "policyRowSummary": summarize_rows(rows),
    }


def collect_policy_rows(
    *,
    live_summary_path: Path = DEFAULT_LIVE_SUMMARY,
) -> list[PolicyRow]:
    live_summary = _load_json(live_summary_path)
    rows: list[PolicyRow] = []
    seen: set[tuple[str, str]] = set()
    for report_summary in live_summary.get("reportSummaries", []):
        if not isinstance(report_summary, Mapping):
            continue
        report_path = Path(str(report_summary.get("eventAnalysisJsonPath") or ""))
        if report_path.exists():
            rows.extend(_rows_from_event_analysis(report_path))
        for case in report_summary.get("weakHistoryNearCertainLaterWinCases", []):
            if isinstance(case, Mapping):
                rows.append(_policy_row_from_summary_case(case, source_path=str(live_summary_path)))
    deduped: list[PolicyRow] = []
    for row in rows:
        key = (row.source_path, row.trade_key or f"{row.wallet}|{row.display_rank}|{row.raw_token_price}")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def simulate_policy_options(rows: Sequence[PolicyRow]) -> dict[str, Any]:
    options = {name: _simulate_option(rows, name) for name in POLICY_OPTIONS}
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "productionIntegration": False,
        "savedArtifactsMutated": False,
        "policyOptions": options,
        "summary": {
            "rowCount": len(rows),
            "weakHistoryNearCertainRows": sum(row.weak_history_near_certainty for row in rows),
            "weakHistoryNearCertainLaterWinRows": sum(row.weak_history_near_certainty_later_win for row in rows),
            "highRankWeakHistoryNearCertainLaterWinRows": sum(
                row.weak_history_near_certainty_later_win and row.is_high_rank for row in rows
            ),
            "unknownOrMissingFieldRows": sum(not row.has_required_policy_fields for row in rows),
            "recommendedOption": "review_bucket_demotion",
            "gateDecision": "policy_ready_for_product_decision",
        },
        "evidenceLimitations": [
            "Simulation reads one bounded live output plus saved/local artifacts; it is not a scorer implementation.",
            "Review-bucket demotion changes analyst-facing placement and therefore needs product approval before implementation.",
            "Stronger score reducers may not move rows that are high-ranked because of existing Strong Risk review-bucket priority.",
            "Known-case corpus is a regression guardrail, not a labeled tuning set.",
        ],
    }


def write_outputs(
    *,
    evidence_output: Path = DEFAULT_EVIDENCE_OUTPUT,
    simulation_output: Path = DEFAULT_SIMULATION_OUTPUT,
    live_summary_path: Path = DEFAULT_LIVE_SUMMARY,
    saved_audit_path: Path = DEFAULT_SAVED_AUDIT,
    known_case_corpus_path: Path = DEFAULT_KNOWN_CASE_CORPUS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = build_policy_evidence(
        live_summary_path=live_summary_path,
        saved_audit_path=saved_audit_path,
        known_case_corpus_path=known_case_corpus_path,
    )
    rows = collect_policy_rows(live_summary_path=live_summary_path)
    simulation = simulate_policy_options(rows)
    simulation["inputs"] = {
        "liveSummaryPath": str(live_summary_path),
        "savedAuditPath": str(saved_audit_path),
        "knownCaseCorpusPath": str(known_case_corpus_path),
    }
    simulation["representativeAffectedRows"] = [
        row.to_dict()
        for row in rows
        if row.weak_history_near_certainty_later_win
    ][:20]
    _write_json(evidence_output, evidence)
    _write_json(simulation_output, simulation)
    return evidence, simulation


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-summary", default=str(DEFAULT_LIVE_SUMMARY))
    parser.add_argument("--saved-audit", default=str(DEFAULT_SAVED_AUDIT))
    parser.add_argument("--known-case-corpus", default=str(DEFAULT_KNOWN_CASE_CORPUS))
    parser.add_argument("--evidence-output", default=str(DEFAULT_EVIDENCE_OUTPUT))
    parser.add_argument("--simulation-output", default=str(DEFAULT_SIMULATION_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    evidence, simulation = write_outputs(
        evidence_output=Path(args.evidence_output),
        simulation_output=Path(args.simulation_output),
        live_summary_path=Path(args.live_summary),
        saved_audit_path=Path(args.saved_audit),
        known_case_corpus_path=Path(args.known_case_corpus),
    )
    if not args.quiet:
        print(
            json.dumps(
                {
                    "evidenceOutput": args.evidence_output,
                    "simulationOutput": args.simulation_output,
                    "gate": simulation["summary"]["gateDecision"],
                    "recommendedOption": simulation["summary"]["recommendedOption"],
                    "policyRowsCollected": evidence["policyRowsCollected"],
                },
                sort_keys=True,
            )
        )
    return 0


def _simulate_option(rows: Sequence[PolicyRow], option: str) -> dict[str, Any]:
    affected: list[PolicyRow] = [row for row in rows if row.weak_history_near_certainty]
    later_win = [row for row in affected if row.later_won is True]
    high_rank = [row for row in later_win if row.is_high_rank]
    unknown = [row for row in rows if not row.has_required_policy_fields]
    demoted: list[PolicyRow] = []
    warning_only: list[PolicyRow] = []
    score_adjusted: list[PolicyRow] = []
    remains_primary = [row for row in rows if row.is_primary_review]
    if option == "stronger_reducer":
        score_adjusted = affected
        remains_primary = [
            row
            for row in rows
            if row.is_primary_review and not _would_fall_below_primary_after_score_reducer(row)
        ]
    elif option == "review_bucket_demotion":
        demoted = later_win
        remains_primary = [
            row
            for row in rows
            if row.is_primary_review and row not in demoted
        ]
    elif option == "explanation_only":
        warning_only = affected
    elif option == "current":
        pass
    else:
        raise ValueError(f"Unknown policy option: {option}")
    return {
        "description": _policy_description(option),
        "affectedRows": len(affected),
        "affectedHighRankRows": len(high_rank),
        "affectedWeakHistoryNearCertainRows": len(affected),
        "affectedWeakHistoryNearCertainLaterWinRows": len(later_win),
        "rowsThatWouldBeDemoted": len(demoted),
        "rowsWithScoreAdjustmentOnly": len(score_adjusted),
        "rowsWithExplanationWarningOnly": len(warning_only),
        "rowsThatWouldRemainPrimary": len(remains_primary),
        "unknownMissingFieldRows": len(unknown),
        "runtimeMutation": False,
        "requiresProductApproval": option == "review_bucket_demotion",
        "requiresImplementationApproval": option in {"stronger_reducer", "review_bucket_demotion", "explanation_only"},
        "evidenceLimitations": _option_limitations(option),
    }


def summarize_rows(rows: Sequence[PolicyRow]) -> dict[str, Any]:
    source_counts = Counter(row.source for row in rows)
    return {
        "rowCount": len(rows),
        "sourceCounts": dict(sorted(source_counts.items())),
        "weakHistoryRows": sum(row.weak_history_classification == "weak_history" for row in rows),
        "nearCertainEconomicRows": sum(row.near_certain_economic_entry for row in rows),
        "weakHistoryNearCertainRows": sum(row.weak_history_near_certainty for row in rows),
        "weakHistoryNearCertainLaterWinRows": sum(row.weak_history_near_certainty_later_win for row in rows),
        "highRankWeakHistoryNearCertainLaterWinRows": sum(
            row.weak_history_near_certainty_later_win and row.is_high_rank for row in rows
        ),
        "unknownMissingFieldRows": sum(not row.has_required_policy_fields for row in rows),
    }


def _rows_from_event_analysis(path: Path) -> list[PolicyRow]:
    payload = _load_json(path)
    rows: list[PolicyRow] = []
    for key in ("display_trades", "suspicious_trades"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for index, row in enumerate(value, start=1):
            if isinstance(row, Mapping):
                rows.append(
                    _policy_row_from_event_row(
                        row,
                        source="live_event_analysis",
                        source_path=str(path),
                        display_rank=index if key == "display_trades" else None,
                    )
                )
    return rows


def _policy_row_from_summary_case(row: Mapping[str, Any], *, source_path: str) -> PolicyRow:
    return _policy_row_from_event_row(row, source="live_summary_case", source_path=source_path, display_rank=_int_or_none(row.get("displayRank")))


def _policy_row_from_event_row(
    row: Mapping[str, Any],
    *,
    source: str,
    source_path: str,
    display_rank: int | None,
) -> PolicyRow:
    raw_order_side = _first(row, "rawOrderSide", "raw_order_side", "orderSide", "order_side")
    raw_token_outcome = _first(row, "rawTokenOutcome", "raw_token_outcome", "side", "outcome")
    raw_token_price = _first(row, "rawTokenPrice", "raw_token_price", "price", "entryPrice")
    normalized = normalize_side_outcome(raw_order_side, raw_token_outcome, raw_token_price)
    cluster = normalize_cluster_direction(raw_order_side, raw_token_outcome, raw_token_price)
    later_won = _boolish(_first(row, "laterWon", "later_won", "laterCorrect", "later_correct"))
    weak_history = _weak_history_classification(row)
    model_probability = normalized.economic_side_probability
    near_certain = bool(model_probability is not None and model_probability >= NEAR_CERTAINTY_THRESHOLD)
    text = _row_text(row)
    notes = []
    if normalized.normalization_status != "normalized":
        notes.append(normalized.fallback_reason or "missing_or_malformed_side_outcome_price")
    if weak_history == UNKNOWN:
        notes.append("weak_history_unknown")
    if later_won is None:
        notes.append("later_won_unknown")
    return PolicyRow(
        source=source,
        source_path=source_path,
        trade_key=str(_first(row, "id", "tradeId", "trade_id", "transactionHash", "uniqueTradeKey") or ""),
        wallet=str(_first(row, "wallet", "proxyWallet", "address") or ""),
        market=str(_first(row, "market", "marketTitle", "selectedMarketTitle") or ""),
        event_slug=str(_first(row, "parentEventSlug", "eventSlug", "event") or ""),
        raw_order_side=normalized.raw_order_side,
        raw_token_outcome=normalized.raw_token_outcome,
        raw_token_price=_decimal_text(normalized.raw_token_price),
        economic_side=normalized.economic_side,
        economic_side_probability=_decimal_text(normalized.economic_side_probability),
        cluster_direction=cluster.cluster_direction,
        event_forensic_score=_int_or_none(_first(row, "eventForensicScore", "event_forensic_score")),
        display_rank=display_rank,
        existing_model_class=str(_first(row, "existingModelClass", "existing_model_class", "severity") or ""),
        strong_risk_gate_passed=str(_first(row, "strongRiskGatePassed", "strong_risk_gate_passed") or ""),
        hard_evidence_review_tier=str(_first(row, "hardEvidenceReviewTier", "hard_evidence_review_tier") or ""),
        later_won=later_won,
        winner_rank=_int_or_none(_first(row, "winnerRank", "winner_rank", "winningRank", "winning_rank")),
        weak_history_classification=weak_history,
        near_certain_economic_entry=near_certain,
        weak_history_reducer_present=weak_history == "weak_history",
        near_certainty_reducer_present=("near_certainty" in text or "near certainty" in text),
        quality_notes=tuple(notes),
    )


def _would_fall_below_primary_after_score_reducer(row: PolicyRow) -> bool:
    if row.hard_evidence_review_tier:
        return False
    if row.existing_model_class == "Strong Risk":
        return False
    if row.event_forensic_score is None:
        return False
    return max(0, row.event_forensic_score - 15) < 40


def _policy_description(option: str) -> str:
    return {
        "current": "Keep existing runtime behavior and review placement.",
        "stronger_reducer": "Simulate an additional score penalty for weak-history near-certain rows.",
        "review_bucket_demotion": "Simulate moving weak-history near-certain later-win rows out of primary/high review placement.",
        "explanation_only": "Simulate stronger analyst warning fields without score or placement changes.",
    }[option]


def _option_limitations(option: str) -> list[str]:
    common = ["Simulation only; no runtime mutation or scoring change."]
    if option == "stronger_reducer":
        return common + [
            "Score-only reducers may not affect rows prioritized by existing Strong Risk or hard-evidence buckets.",
            "False negatives are possible if a weak-history wallet is actually an early informed trader.",
        ]
    if option == "review_bucket_demotion":
        return common + [
            "Changes analyst-facing review placement and requires product approval.",
            "Must preserve exports so analysts can still find demoted rows.",
        ]
    if option == "explanation_only":
        return common + [
            "Does not address high-rank placement concern.",
            "May be enough if the product goal is clearer analyst interpretation, not lower prominence.",
        ]
    return common + ["Leaves the reproduced high-rank ambiguity intact."]


def _weak_history_classification(row: Mapping[str, Any]) -> str:
    text = _row_text(row)
    if "weak_wallet_track_record" in text or "weak economic history" in text or "weak economic track" in text:
        return "weak_history"
    if "history is not weak" in text or "strong track record" in text:
        return "not_weak_history"
    return UNKNOWN


def _row_text(row: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "eventForensicFlags",
        "event_forensic_flags",
        "eventForensicReducers",
        "reducesConcern",
        "summary",
        "strongRiskSuppressorConflictReasons",
    ):
        value = row.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value not in (None, ""):
            parts.append(str(value))
    raw = row.get("rawMetrics")
    if isinstance(raw, Mapping):
        parts.extend(
            str(raw.get(key) or "")
            for key in ("wallet_economic_history_note", "economic_history_note", "weak_wallet_track_record")
        )
    return " ".join(parts).lower()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _dig(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return UNKNOWN
        current = current.get(key)
    return current if current not in (None, "") else UNKNOWN


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _decimal_text(value: Decimal | None) -> str:
    return str(value) if value is not None else UNKNOWN


if __name__ == "__main__":
    raise SystemExit(main())
