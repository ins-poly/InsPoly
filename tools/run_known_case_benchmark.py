#!/usr/bin/env python3
"""Run the stable Side/Outcome known-case benchmark corpus offline."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.side_outcome import UNKNOWN, normalize_cluster_direction, normalize_side_outcome
from tools.curate_known_case_benchmark import DEFAULT_OUTPUT as DEFAULT_CORPUS
from tools.curate_known_case_benchmark import REQUIRED_CATEGORIES, validate_known_case_corpus


REPORT_TYPE = "post_side_outcome_known_case_benchmark_run"
SCHEMA_VERSION = "known_case_benchmark_run_v1"
DEFAULT_RUN_OUTPUT = Path("validation_outputs/known_case_benchmark_run_20260526.json")


def run_known_case_benchmark(corpus_path: str | Path = DEFAULT_CORPUS) -> dict[str, object]:
    corpus_file = Path(corpus_path)
    corpus = json.loads(corpus_file.read_text(encoding="utf-8"))
    schema_errors = validate_known_case_corpus(corpus)
    cases = corpus.get("cases") if isinstance(corpus, Mapping) else []
    case_results = [evaluate_known_case(case) for case in cases if isinstance(case, Mapping)]
    summary = _summarize(case_results, schema_errors)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "corpusPath": str(corpus_file),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeBehaviorChanged": False,
        "gateDecision": _gate(summary),
        "summary": summary,
        "caseResults": case_results,
    }


def evaluate_known_case(case: Mapping[str, object]) -> dict[str, object]:
    trades = _case_trades(case)
    evaluated_trades = [_evaluate_trade(trade) for trade in trades]
    expected = _mapping(case.get("expected_result"))
    errors: list[str] = []
    if not evaluated_trades:
        errors.append("no_evaluable_trades")
    primary = evaluated_trades[0] if evaluated_trades else {}
    for field, observed_field in (
        ("economic_side", "economic_side"),
        ("model_probability", "model_probability"),
        ("cluster_direction", "cluster_direction"),
    ):
        expected_value = str(expected.get(field) or case.get(field) or UNKNOWN)
        observed_value = str(primary.get(observed_field) or UNKNOWN)
        if expected_value != observed_value:
            errors.append(f"{field}_expected_{expected_value}_observed_{observed_value}")
    expected_phase4 = str(case.get("expected_phase4_effect") or "")
    if expected_phase4.startswith("same_cluster_"):
        expected_cluster = expected_phase4.removeprefix("same_cluster_")
        clusters = {str(row.get("cluster_direction")) for row in evaluated_trades}
        if clusters != {expected_cluster}:
            errors.append(f"cluster_pair_expected_{expected_cluster}_observed_{sorted(clusters)}")
    if "blocked" in str(case.get("phase3_capital_status") or "") and expected.get("phase3_runtime_allowed") is not False:
        errors.append("phase3_blocked_case_allows_runtime")
    if expected.get("direct_gate_mutation_allowed") is not False:
        errors.append("direct_gate_mutation_allowed")
    errors.extend(_sidecar_contract_errors(case, expected))
    status = "pass" if not errors else "fail"
    if any(row.get("model_probability") == UNKNOWN for row in evaluated_trades) and status == "pass":
        status = "unknown_pass"
    return {
        "case_id": case.get("case_id", ""),
        "category": case.get("category", ""),
        "source_type": case.get("source_type", ""),
        "mode": case.get("mode", ""),
        "status": status,
        "errors": errors,
        "observed": {
            "economic_side": primary.get("economic_side", UNKNOWN),
            "model_probability": primary.get("model_probability", UNKNOWN),
            "cluster_direction": primary.get("cluster_direction", UNKNOWN),
            "automatic_action_allowed": False,
            "exact_wallet_detection_allowed": False,
            "false_positive_control": bool(expected.get("false_positive_control", False)),
            "public_case_control": bool(expected.get("public_case_control", False)),
            "phase3_runtime_allowed": False,
            "direct_gate_mutation_allowed": False,
            "safe_to_use_for_scoring_claims": False,
        },
        "tradeResults": evaluated_trades,
    }


def write_json(path: str | Path, payload: Mapping[str, object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--output", default=str(DEFAULT_RUN_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = run_known_case_benchmark(args.corpus)
    write_json(args.output, report)
    if not args.quiet:
        print(f"cases: {report['summary']['caseCount']}")
        print(f"passed: {report['summary']['passCount']}")
        print(f"failed: {report['summary']['failCount']}")
        print(f"gate: {report['gateDecision']}")
    return 0


def _case_trades(case: Mapping[str, object]) -> list[Mapping[str, object]]:
    rows = case.get("case_trades")
    if isinstance(rows, list) and rows:
        return [row for row in rows if isinstance(row, Mapping)]
    return [
        {
            "raw_side": case.get("raw_side"),
            "raw_outcome": case.get("raw_outcome"),
            "raw_token_price": case.get("raw_token_price"),
        }
    ]


def _evaluate_trade(trade: Mapping[str, object]) -> dict[str, object]:
    side = trade.get("raw_side")
    outcome = trade.get("raw_outcome")
    price = trade.get("raw_token_price")
    normalized = normalize_side_outcome(side, outcome, price)
    cluster = normalize_cluster_direction(side, outcome, price)
    return {
        "raw_side": normalized.raw_order_side,
        "raw_outcome": normalized.raw_token_outcome,
        "raw_token_price": str(normalized.raw_token_price) if normalized.raw_token_price is not None else UNKNOWN,
        "economic_side": normalized.economic_side,
        "model_probability": str(normalized.economic_side_probability) if normalized.economic_side_probability is not None else UNKNOWN,
        "cluster_direction": cluster.cluster_direction,
        "normalization_status": normalized.normalization_status,
        "fallback_reason": normalized.fallback_reason,
    }


def _summarize(case_results: Sequence[Mapping[str, object]], schema_errors: Sequence[str]) -> dict[str, object]:
    categories = Counter(str(row.get("category") or "unknown") for row in case_results)
    source_types = Counter(str(row.get("source_type") or "unknown") for row in case_results)
    statuses = Counter(str(row.get("status") or "unknown") for row in case_results)
    missing = sorted(set(REQUIRED_CATEGORIES) - set(categories))
    fail_count = statuses.get("fail", 0) + len(schema_errors)
    return {
        "caseCount": len(case_results),
        "passCount": statuses.get("pass", 0),
        "unknownPassCount": statuses.get("unknown_pass", 0),
        "failCount": fail_count,
        "statusCounts": dict(sorted(statuses.items())),
        "sourceTypeCounts": dict(sorted(source_types.items())),
        "categoryCounts": dict(sorted(categories.items())),
        "missingRequiredCategories": missing,
        "schemaErrors": list(schema_errors),
        "phase3BlockedCaseCount": sum(1 for row in case_results if "phase3" in str(row.get("category") or "")),
        "advisoryOnlyCaseCount": sum(1 for row in case_results if _is_advisory_result(row)),
        "falsePositiveControlCaseCount": sum(1 for row in case_results if _mapping(row.get("observed")).get("false_positive_control") is True),
        "publicCaseControlCaseCount": sum(1 for row in case_results if _mapping(row.get("observed")).get("public_case_control") is True),
        "syntheticCaseCount": source_types.get("synthetic_fixture", 0),
        "realOrDerivedCaseCount": len(case_results) - source_types.get("synthetic_fixture", 0),
    }


def _gate(summary: Mapping[str, object]) -> str:
    if summary.get("failCount", 0):
        return "known_case_corpus_blocked"
    if summary.get("missingRequiredCategories"):
        return "known_case_corpus_needs_more_real_artifacts"
    return "known_case_corpus_ready"


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sidecar_contract_errors(case: Mapping[str, object], expected: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    assertion_type = str(case.get("assertion_type") or "")
    if expected.get("automatic_action_allowed", False) is not False:
        errors.append("automatic_action_allowed")
    if expected.get("safe_to_use_for_scoring_claims", False) is not False:
        errors.append("safe_to_use_for_scoring_claims")
    if assertion_type in {"false_positive_control", "public_case_control", "sidecar_context_control"}:
        if not str(case.get("forbidden_interpretation") or "").strip():
            errors.append("missing_forbidden_interpretation")
        if expected.get("requires_fresh_validation_for_model_use") is not True:
            errors.append("fresh_validation_not_required_for_advisory_control")
        if case.get("requires_fresh_validation") is not True:
            errors.append("top_level_fresh_validation_not_required")
        if expected.get("exact_wallet_detection_allowed") is not False:
            errors.append("exact_wallet_detection_allowed")
    if assertion_type == "false_positive_control":
        if expected.get("false_positive_control") is not True:
            errors.append("false_positive_control_not_marked")
        notes = case.get("false_positive_notes")
        if not isinstance(notes, list) or not notes:
            errors.append("false_positive_notes_missing")
    if assertion_type == "public_case_control":
        if expected.get("public_case_control") is not True:
            errors.append("public_case_control_not_marked")
        if not isinstance(case.get("source_urls"), list) or not case.get("source_urls"):
            errors.append("public_source_urls_missing")
        if str(case.get("assertion_level") or "") == "pattern_level_only" and str(case.get("wallet") or "") != "pattern-level":
            errors.append("pattern_level_wallet_assertion")
    return errors


def _is_advisory_result(row: Mapping[str, object]) -> bool:
    observed = _mapping(row.get("observed"))
    return (
        observed.get("false_positive_control") is True
        or observed.get("public_case_control") is True
        or str(row.get("category") or "")
        in {
            "true_low_probability_later_winner",
            "weak_history_near_certainty_demotion",
            "selected_market_vs_whole_event_scope_boundary",
            "pagination_truncation_warning_control",
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
