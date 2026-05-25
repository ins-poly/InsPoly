#!/usr/bin/env python3
"""Phase 3 capital-at-risk unblock impact audit.

Combines the prior Phase 3 audit with the new source inventory and ledger
cross-check evidence. This remains sidecar-only and does not authorize runtime
capital-at-risk normalization.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.phase3_capital_ledger_crosscheck import (  # noqa: E402
    build_ledger_crosscheck,
    discover_ledger_artifact_dirs,
)
from tools.phase3_capital_source_inventory import (  # noqa: E402
    QUALITY_DISPLAY_ONLY,
    QUALITY_SAFE_BUY_CASH,
    QUALITY_SAFE_SELL_MAX_LOSS,
    QUALITY_UNSAFE_OLD_NOTIONAL_ONLY,
    QUALITY_UNKNOWN_MISSING_FIELDS,
    build_source_inventory,
    discover_inventory_records,
)


REPORT_TYPE = "phase3_capital_unblock_impact_audit"
SCHEMA_VERSION = "phase3_capital_unblock_impact_v1"
DEFAULT_OLD_AUDIT = Path("side_outcome_audits/side_outcome_phase3_capital_at_risk_audit_20260522.json")
DEFAULT_BLOCKER_OUTPUT = Path("validation_outputs/phase3_capital_unblock_blocker_reconciliation_20260525.json")
DEFAULT_IMPACT_OUTPUT = Path("validation_outputs/phase3_capital_unblock_impact_audit_20260525.json")


def build_blocker_reconciliation(
    *,
    old_audit: Mapping[str, object] | None,
    source_inventory: Mapping[str, object],
    ledger_crosscheck: Mapping[str, object],
) -> dict[str, object]:
    old_summary = _mapping(old_audit.get("summary") if old_audit else {})
    affected_counts = _mapping(old_summary.get("affectedCounts"))
    source_summary = _mapping(source_inventory.get("summary"))
    ledger_summary = _mapping(ledger_crosscheck.get("summary"))
    blockers = [
        {
            "blocker": "SELL max-loss semantics differ from raw notional",
            "previousEvidence": {
                "sellRowsWithCapitalDelta": affected_counts.get("sellRowsWithCapitalDelta", 0),
                "rowsWithCapitalDelta": affected_counts.get("rowsWithCapitalDelta", 0),
            },
            "newEvidence": {
                "ledgerSafeSellMaxLossRows": ledger_summary.get("safeSellMaxLossRows", 0),
                "sourceInventorySafeSellMaxLossRows": _quality_count(source_inventory, QUALITY_SAFE_SELL_MAX_LOSS),
            },
            "status": "partially_reduced_by_formula_and_ledger_fixtures",
            "remainingRequirement": "prove runtime sources expose direct side/outcome/price/size or explicit max-loss/collateral before changing scoring capital",
        },
        {
            "blocker": "usdcSize is observed cash/proceeds, not automatically SELL max loss",
            "previousEvidence": {
                "sellUsdcSizeRows": _old_note_count(old_summary, "sell_usdc_size_recorded_as_observed_cash_not_max_loss"),
            },
            "newEvidence": {
                "ledgerRowsWhereUsdcSizeIsObservedCashNotMaxLoss": ledger_summary.get(
                    "rowsWhereUsdcSizeIsObservedCashNotMaxLoss",
                    0,
                )
            },
            "status": "confirmed_not_removed",
            "remainingRequirement": "keep observed cash, proceeds, collateral, and max loss as separate fields",
        },
        {
            "blocker": "old/lossy notional-only rows cannot be reinterpreted",
            "previousEvidence": {
                "oldReportNotionalOnlyRows": _old_note_count(old_summary, "old_report_notional_only_not_safe_for_rescoring"),
            },
            "newEvidence": {
                "inventoryOldNotionalOnlyRows": source_summary.get("oldNotionalOnlyRows", 0),
            },
            "status": "still_blocks_runtime_reinterpretation",
            "remainingRequirement": "old reports must remain no-op/unknown for Phase 3 unless full raw trade fields are available",
        },
        {
            "blocker": "sensitive funding/HER/Strong Risk overlap",
            "previousEvidence": {
                "sensitiveOverlapRows": affected_counts.get("sensitiveOverlapRows", 0),
            },
            "newEvidence": {
                "directGateChangesAllowed": False,
            },
            "status": "still_requires_separate_gate_guardrails",
            "remainingRequirement": "any capital-driven gate effects require explicit approval and before/after guard tests",
        },
    ]
    return {
        "reportType": "phase3_capital_unblock_blocker_reconciliation",
        "schemaVersion": "phase3_capital_unblock_blocker_reconciliation_v1",
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeImplementationAllowed": False,
        "currentGateBeforeAudit": "keep_phase3_blocked",
        "blockers": blockers,
    }


def build_unblock_impact_audit(
    *,
    old_audit: Mapping[str, object] | None,
    source_inventory: Mapping[str, object],
    ledger_crosscheck: Mapping[str, object],
) -> dict[str, object]:
    source_summary = _mapping(source_inventory.get("summary"))
    ledger_summary = _mapping(ledger_crosscheck.get("summary"))
    quality_counts = _mapping(source_summary.get("sourceQualityCounts"))
    old_summary = _mapping(old_audit.get("summary") if old_audit else {})
    affected_counts = _mapping(old_summary.get("affectedCounts"))
    total_rows = int(source_summary.get("recordsEvaluated") or 0)
    safe_buy = int(quality_counts.get(QUALITY_SAFE_BUY_CASH) or 0)
    safe_sell = int(quality_counts.get(QUALITY_SAFE_SELL_MAX_LOSS) or 0)
    display_only = int(quality_counts.get(QUALITY_DISPLAY_ONLY) or 0)
    unsafe_old = int(quality_counts.get(QUALITY_UNSAFE_OLD_NOTIONAL_ONLY) or 0)
    unknown = int(quality_counts.get(QUALITY_UNKNOWN_MISSING_FIELDS) or 0)
    still_unsafe = unsafe_old + unknown + display_only
    gate = _gate_decision(
        source_summary=source_summary,
        ledger_summary=ledger_summary,
        affected_counts=affected_counts,
        safe_sell=safe_sell,
        unsafe_old=unsafe_old,
        still_unsafe=still_unsafe,
    )
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeImplementationAllowed": False,
        "gateDecision": gate,
        "summary": {
            "totalRowsEvaluated": total_rows,
            "safeForBuyCashRows": safe_buy,
            "safeForSellMaxLossRows": safe_sell,
            "safeForDisplayOnlyRows": display_only,
            "unsafeOldNotionalOnlyRows": unsafe_old,
            "unknownMissingFieldRows": unknown,
            "stillUnsafeRows": still_unsafe,
            "runtimeSafeCandidateRows": source_summary.get("runtimeSafeCandidateRows", 0),
            "realLocalSafeForSellMaxLossRows": source_summary.get("realLocalSafeForSellMaxLoss", 0),
            "ledgerSafeSellMaxLossRows": ledger_summary.get("safeSellMaxLossRows", 0),
            "ledgerRowsWhereUsdcSizeIsObservedCashNotMaxLoss": ledger_summary.get(
                "rowsWhereUsdcSizeIsObservedCashNotMaxLoss",
                0,
            ),
            "oldAuditRowsWithCapitalDelta": affected_counts.get("rowsWithCapitalDelta", 0),
            "oldAuditSensitiveOverlapRows": affected_counts.get("sensitiveOverlapRows", 0),
            "affectedRowsIfImplementedOnlyForSafeRows": safe_buy + safe_sell,
            "falseConfidenceRisk": "high" if still_unsafe > safe_sell else "medium",
        },
        "sourceQualityCounts": quality_counts,
        "ledgerSummary": ledger_summary,
        "oldAuditAffectedCounts": affected_counts,
        "decisionRationale": _decision_rationale(gate),
        "explicitBlocks": [
            "no scanner/archive/Event Forensic runtime capital migration in this campaign",
            "no _score_trade() or _event_forensic_score() Phase 3 changes",
            "no scoring weights, thresholds, direct gates, storage schema, live/RPC/network, saved-artifact, or UI sorting/filtering changes",
        ],
    }


def write_json(payload: Mapping[str, object], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _gate_decision(
    *,
    source_summary: Mapping[str, object],
    ledger_summary: Mapping[str, object],
    affected_counts: Mapping[str, object],
    safe_sell: int,
    unsafe_old: int,
    still_unsafe: int,
) -> str:
    real_safe_sell = int(source_summary.get("realLocalSafeForSellMaxLoss") or 0)
    sensitive_overlap = int(affected_counts.get("sensitiveOverlapRows") or 0)
    ledger_safe = int(ledger_summary.get("safeSellMaxLossRows") or 0)
    if real_safe_sell > 0 and unsafe_old == 0 and sensitive_overlap == 0:
        return "phase3_ready_for_implementation_rfc"
    if safe_sell > 0 or ledger_safe > 0:
        return "phase3_ready_for_partial_safe_sidecar_only"
    if still_unsafe > 0:
        return "phase3_keep_blocked_needs_source_fields"
    return "phase3_keep_blocked_accounting_ambiguous"


def _decision_rationale(gate: str) -> list[str]:
    if gate == "phase3_ready_for_implementation_rfc":
        return [
            "real/non-synthetic SELL max-loss rows are source-safe",
            "old-report fallback risk is controlled",
            "sensitive overlap does not require gate migration",
        ]
    if gate == "phase3_ready_for_partial_safe_sidecar_only":
        return [
            "ledger/source helpers now prove formula semantics for safe rows",
            "old/lossy report rows and sensitive contexts still block production migration",
            "runtime implementation RFC remains premature",
        ]
    if gate == "phase3_keep_blocked_needs_source_fields":
        return [
            "too many rows still lack side/outcome/price/size or direct source provenance",
            "old notional-only artifacts cannot be reinterpreted",
        ]
    return [
        "SELL observed cash/proceeds/collateral semantics remain ambiguous",
        "no runtime migration should proceed",
    ]


def _old_note_count(summary: Mapping[str, object], note: str) -> int:
    counts = _mapping(summary.get("unsafeOrMissingFieldCounts"))
    return int(counts.get(note) or 0)


def _quality_count(source_inventory: Mapping[str, object], quality: str) -> int:
    summary = _mapping(source_inventory.get("summary"))
    counts = _mapping(summary.get("sourceQualityCounts"))
    return int(counts.get(quality) or 0)


def _load_json(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--old-audit-json", default=str(DEFAULT_OLD_AUDIT))
    parser.add_argument("--blocker-output-json", default=str(DEFAULT_BLOCKER_OUTPUT))
    parser.add_argument("--impact-output-json", default=str(DEFAULT_IMPACT_OUTPUT))
    parser.add_argument("--max-files", type=int, default=250)
    parser.add_argument("--max-rows-per-file", type=int, default=200)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    records = discover_inventory_records(
        args.root,
        max_files=args.max_files,
        max_rows_per_file=args.max_rows_per_file,
    )
    source_inventory = build_source_inventory(records)
    ledger_crosscheck = build_ledger_crosscheck(discover_ledger_artifact_dirs(args.root))
    old_audit = _load_json(Path(args.old_audit_json))
    blocker = build_blocker_reconciliation(
        old_audit=old_audit,
        source_inventory=source_inventory,
        ledger_crosscheck=ledger_crosscheck,
    )
    impact = build_unblock_impact_audit(
        old_audit=old_audit,
        source_inventory=source_inventory,
        ledger_crosscheck=ledger_crosscheck,
    )
    blocker_path = write_json(blocker, args.blocker_output_json)
    impact_path = write_json(impact, args.impact_output_json)
    if not args.quiet:
        print(blocker_path)
        print(impact_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
