#!/usr/bin/env python3
"""Read-only candidate audit sidecar exporter for saved Event Forensic runs."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.event_forensic import (
    EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD,
    _candidate_audit_fieldnames,
    _candidate_audit_json_payload,
    _candidate_audit_markdown,
    _text_values,
    _write_csv,
)
from app.scanner import HARD_EVIDENCE_REVIEW_TIER


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Event Forensic output bundle directory.")
    parser.add_argument(
        "--sqlite-path",
        default=".inspoly_event_forensic_analyzer/inspoly_event_forensic_analyzer.sqlite3",
        help="Event Forensic SQLite database path. Default: local Event Forensic analyzer DB.",
    )
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    if not run_dir.exists() or not run_dir.is_dir():
        raise SystemExit(f"Run directory not found: {run_dir}")
    report_path = run_dir / "event_analysis.json"
    if not report_path.exists():
        raise SystemExit(f"Missing event_analysis.json in: {run_dir}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    sqlite_path = Path(args.sqlite_path)
    sqlite_rows = _load_sqlite_flagged_rows(sqlite_path, report, run_dir) if sqlite_path.exists() else []
    rows = _backfill_candidate_audit_rows(report, sqlite_rows)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = run_dir / f"event_forensic_candidate_audit_{timestamp}.csv"
    json_path = run_dir / f"event_forensic_candidate_audit_{timestamp}.json"
    md_path = run_dir / f"event_forensic_candidate_audit_{timestamp}.md"
    payload = _candidate_audit_json_payload(report, rows)
    payload.update(
        {
            "backfillMode": "read_only_saved_output_sidecar",
            "sourceRunDir": str(run_dir),
            "sourceEventAnalysisPath": str(report_path),
            "sourceSqlitePath": str(sqlite_path) if sqlite_path.exists() else "",
            "recoverabilityNote": (
                "Old saved bundles may not contain every selected-market candidate row. "
                "This sidecar includes primary Event Forensic rows plus current-model flagged rows recoverable from SQLite."
            ),
        }
    )

    _write_csv(csv_path, rows, _candidate_audit_fieldnames())
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_text = _candidate_audit_markdown(report, rows)
    md_text += (
        "\n## Backfill Recoverability Note\n\n"
        "- This is a read-only sidecar for an old run.\n"
        "- Existing `event_analysis.json`, `suspicious_trades.csv`, and SQLite rows were not modified.\n"
        "- Old bundles may not contain every selected-market candidate row; this sidecar includes primary rows plus SQLite current-model flagged rows.\n"
    )
    md_path.write_text(md_text, encoding="utf-8")

    tier_counts = Counter(str(row.get("finalDisplayTier") or "unknown") for row in rows)
    print(f"candidate_audit_csv={csv_path}")
    print(f"candidate_audit_json={json_path}")
    print(f"candidate_audit_md={md_path}")
    print(f"rows={len(rows)}")
    print(f"tier_counts={dict(tier_counts)}")
    return 0


def _load_sqlite_flagged_rows(
    sqlite_path: Path,
    report: dict[str, Any],
    run_dir: Path,
) -> list[sqlite3.Row]:
    report_json_path = str(report.get("report_json_path") or "")
    report_name = Path(report_json_path).name if report_json_path else ""
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        if report_json_path:
            rows = conn.execute(
                """
                select fc.*
                from flagged_cases fc
                join scan_runs sr on sr.id = fc.scan_run_id
                where sr.report_json_path = ?
                   or sr.report_json_path like ?
                order by fc.score desc, cast(fc.trade_notional as real) desc
                """,
                (report_json_path, f"%{report_name}"),
            ).fetchall()
        else:
            rows = []
        if rows:
            return list(rows)
        generated_at = str(report.get("generated_at") or "")
        if generated_at:
            return list(
                conn.execute(
                    """
                    select fc.*
                    from flagged_cases fc
                    join scan_runs sr on sr.id = fc.scan_run_id
                    where substr(sr.started_at, 1, 19) = substr(?, 1, 19)
                    order by fc.score desc, cast(fc.trade_notional as real) desc
                    """,
                    (generated_at,),
                ).fetchall()
            )
        return []
    finally:
        conn.close()


def _backfill_candidate_audit_rows(
    report: dict[str, Any],
    sqlite_rows: list[sqlite3.Row],
) -> list[dict[str, Any]]:
    primary_rows = report.get("suspicious_trades") or report.get("display_trades") or []
    if not isinstance(primary_rows, list):
        primary_rows = []
    primary_ids = {
        str(item.get("id") or item.get("tradeId") or "").strip()
        for item in primary_rows
        if isinstance(item, dict) and str(item.get("id") or item.get("tradeId") or "").strip()
    }
    rows_by_trade_id: dict[str, dict[str, Any]] = {}
    for item in primary_rows:
        if not isinstance(item, dict):
            continue
        row = _row_from_primary_payload(item)
        trade_id = str(row.get("tradeId") or "")
        if trade_id:
            rows_by_trade_id[trade_id] = row
    for sqlite_row in sqlite_rows:
        row = _row_from_sqlite_flagged_case(sqlite_row, is_primary=str(sqlite_row["trade_id"]) in primary_ids)
        trade_id = str(row.get("tradeId") or "")
        if trade_id in rows_by_trade_id:
            rows_by_trade_id[trade_id].update(
                {
                    "currentModelVerdict": row.get("currentModelVerdict", ""),
                    "rawExistingWhy": row.get("rawExistingWhy", ""),
                }
            )
            continue
        rows_by_trade_id[trade_id] = row
    return sorted(
        rows_by_trade_id.values(),
        key=lambda item: (
            1 if item.get("finalDisplayTier") == "primary_event_forensic" else 0,
            int(float(item.get("eventForensicScore") or item.get("currentModelScore") or 0)),
            float(item.get("notionalUsd") or 0),
        ),
        reverse=True,
    )


def _row_from_primary_payload(item: dict[str, Any]) -> dict[str, Any]:
    reducers = _text_values(item.get("eventForensicReducers"))
    flags = _text_values(item.get("eventForensicFlags"))
    tier_reason = (
        f"Event Forensic score {int(float(item.get('eventForensicScore') or 0))} met the primary threshold "
        f"{EVENT_FORENSIC_PRIMARY_TRADE_THRESHOLD}."
    )
    if str(item.get("hardEvidenceReviewTier") or "") == HARD_EVIDENCE_REVIEW_TIER:
        tier_reason = "Hard Evidence Review row is included in primary review."
    return {
        "source": "old_run_primary_event_forensic",
        "tradeId": item.get("id") or item.get("tradeId") or "",
        "wallet": item.get("wallet", ""),
        "username": item.get("username", ""),
        "marketSlug": item.get("marketSlug", ""),
        "conditionId": item.get("conditionId", ""),
        "timestamp": item.get("timestamp", ""),
        "side": item.get("side", ""),
        "outcome": item.get("side", ""),
        "orderSide": item.get("orderSide", ""),
        "notionalUsd": item.get("positionSize", ""),
        "currentModelScore": item.get("existingModelScore", ""),
        "currentModelSeverity": item.get("existingModelClass", ""),
        "currentModelVerdict": item.get("existingModelVerdict", ""),
        "strongRiskGateStatus": item.get("strongRiskGatePassed", ""),
        "strongRiskGateType": item.get("strongRiskGateType", ""),
        "strongRiskGateBranch": item.get("strongRiskExactGateBranch") or item.get("strongRiskGateName") or "",
        "strongRiskGateReasons": item.get("strongRiskGateReasons", ""),
        "hardEvidenceReviewFlag": "Yes" if str(item.get("hardEvidenceReviewTier") or "") == HARD_EVIDENCE_REVIEW_TIER else "No",
        "hardEvidenceReviewTier": item.get("hardEvidenceReviewTier", ""),
        "hardEvidenceSources": _text_values(item.get("hardEvidenceSources")),
        "eventForensicScore": item.get("eventForensicScore", ""),
        "eventForensicFlags": flags,
        "eventForensicBoosters": flags,
        "eventForensicReducers": reducers,
        "fundingEvidenceGrade": item.get("fundingEvidenceGrade") or "unknown",
        "fundingTraceMode": "disabled" if item.get("fundingResolverDisabledReason") else "",
        "fundingTraceStatus": item.get("fundingResolverFunctionalStatus") or item.get("fundingResolverDisabledReason") or "",
        "highVolumePublicUserStatus": "high_volume_public_user_context" if "high_volume_public_user" in str(item.get("strongRiskSuppressorConflictReasons") or "") else "",
        "crossDomainPublicBettorStatus": "cross_domain_public_bettor" if item.get("walletCrossDomainPublicBettorFlag") == "Yes" else "",
        "repricingSourceQuality": item.get("repricingSourceQuality", ""),
        "nearCertaintyOrStaleStatus": _status_from_suppressors(item, {"near_certainty", "stale_or_resolution_gap"}),
        "botOrLowAnalystValueStatus": _status_from_suppressors(item, {"bot_like_execution", "low_analyst_value_wallet"}),
        "finalDisplayTier": "primary_event_forensic",
        "finalTierReason": tier_reason,
        "primaryUiExplanation": "Shown in the primary UI review list.",
        "analysisScope": item.get("analysisScope", ""),
        "selectedConditionId": item.get("selectedConditionId", ""),
        "selectedMarketSlug": item.get("selectedMarketSlug", ""),
        "parentEventSlug": item.get("parentEventSlug", ""),
        "candidateAdmissionStage": item.get("candidateAdmissionStage", ""),
        "candidateAdmissionReason": item.get("candidateAdmissionReason", ""),
        "candidateAdmissionRejectedReason": item.get("candidateAdmissionRejectedReason", ""),
        "openingExposure": item.get("openingExposure", ""),
        "siblingContextOnly": "No",
        "rawCurrentModelFlags": item.get("existingModelFlags", []),
        "rawExistingWhy": item.get("existingWhy", []),
    }


def _row_from_sqlite_flagged_case(row: sqlite3.Row, *, is_primary: bool) -> dict[str, Any]:
    metrics = json.loads(row["metrics_json"])
    reasons = json.loads(row["reasons_json"])
    final_tier = "primary_event_forensic"
    ui_explanation = "Shown in the primary UI review list."
    final_reason = f"Recovered primary current-model row from SQLite score {row['score']}."
    if not is_primary:
        if row["level"] == "Strong Risk":
            final_tier = "current_model_strong_risk_demoted"
        elif row["level"] == "Worth a Look":
            final_tier = "current_model_worth_a_look_demoted"
        else:
            final_tier = "secondary_candidate"
        final_reason = (
            str(metrics.get("strongRiskSuppressorConflictReasons") or "")
            or str(metrics.get("repricingSourceQualityReasons") or "")
            or "Current-model row was not present in primary Event Forensic saved rows."
        )
        ui_explanation = "Not shown as a primary Event Forensic row in the saved output; recovered from SQLite current-model flagged cases."
    funding_grade = str(metrics.get("fundingEvidenceGrade") or metrics.get("funding_evidence_grade") or "unknown")
    return {
        "source": "old_run_sqlite_current_model_flagged",
        "tradeId": row["trade_id"],
        "wallet": row["wallet_address"],
        "username": "",
        "marketSlug": row["market_slug"],
        "conditionId": metrics.get("conditionId") or metrics.get("condition_id") or "",
        "timestamp": row["timestamp"],
        "side": row["side"],
        "outcome": row["outcome"],
        "orderSide": row["side"],
        "notionalUsd": row["trade_notional"],
        "currentModelScore": row["score"],
        "currentModelSeverity": row["level"],
        "currentModelVerdict": row["verdict"],
        "strongRiskGateStatus": metrics.get("strongRiskGatePassed", ""),
        "strongRiskGateType": metrics.get("strongRiskGateType", ""),
        "strongRiskGateBranch": metrics.get("strongRiskExactGateBranch") or metrics.get("strongRiskGateName") or "",
        "strongRiskGateReasons": metrics.get("strongRiskGateReasons", ""),
        "hardEvidenceReviewFlag": "Yes" if str(metrics.get("hardEvidenceReviewTier") or "") == HARD_EVIDENCE_REVIEW_TIER else "No",
        "hardEvidenceReviewTier": metrics.get("hardEvidenceReviewTier", ""),
        "hardEvidenceSources": _text_values(metrics.get("hardEvidenceSources")),
        "eventForensicScore": "",
        "eventForensicFlags": [],
        "eventForensicBoosters": [],
        "eventForensicReducers": [],
        "fundingEvidenceGrade": funding_grade or "unknown",
        "fundingTraceMode": "disabled" if metrics.get("fundingResolverDisabledReason") == "funding_trace_disabled_no_rpc_mode" else "",
        "fundingTraceStatus": metrics.get("fundingResolverFunctionalStatus") or metrics.get("fundingResolverDisabledReason") or "",
        "highVolumePublicUserStatus": "high_volume_public_user_context" if "high_volume_public_user" in str(metrics.get("strongRiskSuppressorConflictReasons") or "") else "",
        "crossDomainPublicBettorStatus": "cross_domain_public_bettor" if metrics.get("wallet_cross_domain_public_bettor_flag") == "Yes" else "",
        "repricingSourceQuality": metrics.get("repricingSourceQuality") or metrics.get("repricing_source_quality") or "",
        "nearCertaintyOrStaleStatus": _status_from_suppressors(metrics, {"near_certainty", "stale_or_resolution_gap"}),
        "botOrLowAnalystValueStatus": _status_from_suppressors(metrics, {"bot_like_execution", "low_analyst_value_wallet"}),
        "finalDisplayTier": final_tier,
        "finalTierReason": final_reason,
        "primaryUiExplanation": ui_explanation,
        "analysisScope": metrics.get("analysisScope", ""),
        "selectedConditionId": metrics.get("selectedConditionId", ""),
        "selectedMarketSlug": metrics.get("selectedMarketSlug", ""),
        "parentEventSlug": metrics.get("parentEventSlug", ""),
        "candidateAdmissionStage": metrics.get("candidateAdmissionStage", ""),
        "candidateAdmissionReason": metrics.get("candidateAdmissionReason", ""),
        "candidateAdmissionRejectedReason": metrics.get("candidateAdmissionRejectedReason", ""),
        "openingExposure": metrics.get("opening_exposure_flag", ""),
        "siblingContextOnly": "No",
        "rawCurrentModelFlags": [],
        "rawExistingWhy": reasons,
    }


def _status_from_suppressors(item: dict[str, Any], labels: set[str]) -> str:
    values = [
        value
        for value in _text_values(item.get("strongRiskSuppressorConflictReasons"))
        if value in labels
    ]
    return "; ".join(values) if values else "none_detected"


if __name__ == "__main__":
    raise SystemExit(main())
