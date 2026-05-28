from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("ai_review_outputs")
DEFAULT_EVENT_FORENSIC_OUTPUTS_DIR = Path("event_forensic_outputs")
PLACEHOLDER_PATH_PARTS = ("path/to/", "<", ">", "YOUR_", "REPLACE_ME")
UNDER_RANKED_HARD_EVIDENCE_WALLET_LIMIT = 8
HIGH_IMPACT_SOURCE_QUALITY_STRONG = "strong"
HIGH_IMPACT_SOURCE_QUALITY_WEAK = "weak"
HIGH_IMPACT_SOURCE_QUALITY_MECHANICAL = "mechanical"
HIGH_IMPACT_SOURCE_QUALITY_ADVISORY = {
    HIGH_IMPACT_SOURCE_QUALITY_WEAK,
    HIGH_IMPACT_SOURCE_QUALITY_MECHANICAL,
}
PROXY_FUNDING_EVIDENCE_GRADES = {"bridge_proxy", "cex_proxy"}
SUSPICIOUS_FUNDING_QUALITY_STRONG = "strong"
SUSPICIOUS_FUNDING_QUALITY_MODERATE = "moderate"
SUSPICIOUS_FUNDING_QUALITY_WEAK = "weak"
SUSPICIOUS_FUNDING_QUALITY_UNKNOWN = "unknown"
WALLET_COUNT_MERGE_KEYS = {
    "eventTradeCount",
    "suspiciousTradeCount",
    "walletLoadedEventTradeCount",
    "walletNotableTradeCount",
    "walletOpeningEntryCount",
    "walletWinningOpeningEntryCount",
    "walletUniqueEventMarketsTraded",
    "walletLoadedHistoryTradeCount",
    "walletLoadedUniqueMarketCount",
}


class ReviewInputError(ValueError):
    pass


def review_latest_outputs(
    *,
    event_forensic_outputs_dir: Path = DEFAULT_EVENT_FORENSIC_OUTPUTS_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    top_n: int = 12,
    use_llm: bool = False,
) -> dict[str, Any]:
    run_dir = discover_latest_event_forensic_run(event_forensic_outputs_dir)
    paths = detect_run_paths(run_dir)
    return review_event_outputs(
        event_analysis_json_path=paths["event_analysis_json_path"],
        suspicious_trades_csv_path=paths.get("suspicious_trades_csv_path"),
        suspicious_wallets_csv_path=paths.get("suspicious_wallets_csv_path"),
        wallet_context_csv_path=paths.get("wallet_context_csv_path"),
        wallet_clusters_csv_path=paths.get("wallet_clusters_csv_path"),
        wallet_graph_json_path=paths.get("wallet_graph_json_path"),
        model_gap_report_md_path=paths.get("model_gap_report_md_path"),
        raw_event_bundle_dir=paths.get("raw_event_bundle_dir"),
        output_dir=output_dir,
        top_n=top_n,
        use_llm=use_llm,
        detected_input_dir=run_dir,
    )


def discover_latest_event_forensic_run(outputs_dir: Path = DEFAULT_EVENT_FORENSIC_OUTPUTS_DIR) -> Path:
    if not outputs_dir.exists():
        raise ReviewInputError(f"No event forensic output directory found: {outputs_dir}")
    candidates = sorted(
        [path for path in outputs_dir.glob("event_forensic_*") if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        if (path / "event_analysis.json").exists():
            return path
    raise ReviewInputError(f"No valid event forensic run with event_analysis.json found under {outputs_dir}")


def detect_run_paths(run_dir: Path) -> dict[str, Path]:
    event_analysis = run_dir / "event_analysis.json"
    _validate_existing_file(event_analysis, label="event_analysis_json_path")
    paths: dict[str, Path] = {"event_analysis_json_path": event_analysis}
    optional_files = {
        "suspicious_trades_csv_path": "suspicious_trades.csv",
        "suspicious_wallets_csv_path": "suspicious_wallets.csv",
        "wallet_context_csv_path": "wallet_context.csv",
        "wallet_clusters_csv_path": "wallet_clusters.csv",
        "wallet_graph_json_path": "wallet_graph.json",
        "model_gap_report_md_path": "model_gap_report.md",
    }
    for key, filename in optional_files.items():
        path = run_dir / filename
        if path.exists():
            paths[key] = path
    raw_dir = run_dir / "raw_event_bundle"
    if raw_dir.exists():
        paths["raw_event_bundle_dir"] = raw_dir
    return paths


def review_event_outputs(
    *,
    event_analysis_json_path: Path,
    suspicious_trades_csv_path: Path | None = None,
    suspicious_wallets_csv_path: Path | None = None,
    wallet_context_csv_path: Path | None = None,
    wallet_clusters_csv_path: Path | None = None,
    wallet_graph_json_path: Path | None = None,
    model_gap_report_md_path: Path | None = None,
    raw_event_bundle_dir: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    top_n: int = 12,
    use_llm: bool = False,
    detected_input_dir: Path | None = None,
) -> dict[str, Any]:
    event_analysis_json_path = _validate_existing_file(
        event_analysis_json_path,
        label="event_analysis_json_path",
    )
    event_analysis = _read_json_strict(event_analysis_json_path)
    export_files = event_analysis.get("export_files") if isinstance(event_analysis.get("export_files"), dict) else {}

    suspicious_trades_csv_path = _optional_path(
        suspicious_trades_csv_path or _path_from_export(export_files, "suspicious_trades_csv_path")
    )
    suspicious_wallets_csv_path = _optional_path(
        suspicious_wallets_csv_path or _path_from_export(export_files, "suspicious_wallets_csv_path")
    )
    wallet_context_csv_path = _optional_path(
        wallet_context_csv_path or _path_from_export(export_files, "wallet_context_csv_path")
    )
    wallet_clusters_csv_path = _optional_path(
        wallet_clusters_csv_path or _path_from_export(export_files, "wallet_clusters_csv_path")
    )
    wallet_graph_json_path = _optional_path(
        wallet_graph_json_path or _path_from_export(export_files, "wallet_graph_json_path")
    )
    model_gap_report_md_path = _optional_path(
        model_gap_report_md_path or _path_from_export(export_files, "model_gap_report_md_path")
    )
    raw_event_bundle_dir = _optional_path(
        raw_event_bundle_dir or _path_from_export(export_files, "raw_event_bundle_dir"),
        must_be_file=False,
    )

    trade_rows = _read_csv_rows(suspicious_trades_csv_path)
    context_wallet_rows = _read_csv_rows(wallet_context_csv_path)
    suspicious_wallet_rows = _read_csv_rows(suspicious_wallets_csv_path)
    cluster_rows = _read_csv_rows(wallet_clusters_csv_path)
    raw_trade_rows = _read_raw_trade_rows(raw_event_bundle_dir)
    wallet_graph = _read_json_strict(wallet_graph_json_path) if wallet_graph_json_path else {}
    model_gap_text = (
        model_gap_report_md_path.read_text(encoding="utf-8")
        if model_gap_report_md_path and model_gap_report_md_path.exists()
        else ""
    )

    embedded_wallet_rows = list(event_analysis.get("display_wallets") or event_analysis.get("suspicious_wallets") or [])
    embedded_trade_rows = list(event_analysis.get("display_trades") or event_analysis.get("suspicious_trades") or [])
    embedded_cluster_rows = list(event_analysis.get("display_clusters") or event_analysis.get("wallet_clusters") or [])
    wallet_rows = _merge_wallet_rows(
        suspicious_wallet_rows=suspicious_wallet_rows,
        wallet_context_rows=context_wallet_rows,
        embedded_wallet_rows=embedded_wallet_rows,
    )
    if trade_rows:
        trade_rows = _merge_rich_rows(trade_rows, embedded_trade_rows, key_fn=_trade_merge_key)
    else:
        trade_rows = embedded_trade_rows
    if cluster_rows:
        cluster_rows = _merge_rich_rows(cluster_rows, embedded_cluster_rows, key_fn=lambda row: str(row.get("id") or ""))
    else:
        cluster_rows = embedded_cluster_rows

    _validate_case_sources(
        event_analysis=event_analysis,
        trade_rows=trade_rows,
        wallet_rows=wallet_rows,
        cluster_rows=cluster_rows,
        suspicious_trades_csv_path=suspicious_trades_csv_path,
        suspicious_wallets_csv_path=suspicious_wallets_csv_path,
        wallet_context_csv_path=wallet_context_csv_path,
    )

    packets = build_case_packets(
        event_analysis=event_analysis,
        trade_rows=trade_rows,
        wallet_rows=wallet_rows,
        cluster_rows=cluster_rows,
        top_n=top_n,
        source_trade_rows=raw_trade_rows,
    )
    reviews = [review_case_packet(packet) for packet in packets]
    deterministic_by_case = {str(review["case_id"]): review for review in reviews}
    for packet in packets:
        review = deterministic_by_case.get(str(packet["case_id"]), {})
        packet["deterministic_review"] = {
            "review_verdict": review.get("review_verdict", ""),
            "interpretation_class": review.get("interpretation_class", ""),
            "main_reason": review.get("main_reason", ""),
            "weakening_evidence": review.get("evidence_that_weakens_concern", []),
            "supporting_evidence": review.get("evidence_that_supports_concern", []),
        }
        packet["question_for_llm"] = (
            "Does this case look like a plausible insider-style case, a high-volume public-user false positive, "
            "or something else?"
        )

    if not packets and not _input_is_genuinely_empty(event_analysis):
        raise ReviewInputError("No useful case packets could be built from the saved outputs.")

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _review_timestamp()
    timestamp, cases_path, report_path, model_changes_path = _reserve_review_output_paths(output_dir, timestamp)

    deterministic_summary = _review_summary(reviews)
    deterministic_summary["top_suggested_fixes"] = _top_suggested_fixes(reviews)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_event_analysis_json_path": str(event_analysis_json_path),
        "detected_input_dir": str(detected_input_dir or event_analysis_json_path.parent),
        "event": _event_identity(event_analysis),
        "source_paths": {
            "suspicious_trades_csv_path": str(suspicious_trades_csv_path or ""),
            "suspicious_wallets_csv_path": str(suspicious_wallets_csv_path or ""),
            "wallet_context_csv_path": str(wallet_context_csv_path or ""),
            "wallet_clusters_csv_path": str(wallet_clusters_csv_path or ""),
            "wallet_graph_json_path": str(wallet_graph_json_path or ""),
            "model_gap_report_md_path": str(model_gap_report_md_path or ""),
            "raw_event_bundle_dir": str(raw_event_bundle_dir or ""),
        },
        "safety": {
            "production_code_modified": False,
            "automatic_scoring_changes_applied": False,
            "reviewer_type": "deterministic_local",
        },
        "summary": deterministic_summary,
        "wallet_graph_summary": _wallet_graph_summary(wallet_graph),
        "model_gap_excerpt": model_gap_text[:2000],
        "case_packets": packets,
        "reviews": reviews,
    }
    cases_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_render_review_report(payload), encoding="utf-8")
    model_changes_path.write_text(_render_model_changes_report(payload), encoding="utf-8")

    outputs: dict[str, Any] = {
        "ok": True,
        "detected_input_dir": str(detected_input_dir or event_analysis_json_path.parent),
        "event_title": payload["event"]["title"],
        "event_slug": payload["event"]["slug"],
        "cases_reviewed": deterministic_summary["cases_reviewed"],
        "wallet_cases_reviewed": deterministic_summary["wallet_cases_reviewed"],
        "trade_cases_reviewed": deterministic_summary["trade_cases_reviewed"],
        "cluster_cases_reviewed": deterministic_summary["cluster_cases_reviewed"],
        "likely_false_positive_count": deterministic_summary["likely_false_positive_count"],
        "plausible_insider_style_count": deterministic_summary["plausible_insider_style_count"],
        "ambiguous_count": deterministic_summary["ambiguous_count"],
        "top_suggested_fixes": deterministic_summary["top_suggested_fixes"],
        "cases_json_path": str(cases_path),
        "review_report_md_path": str(report_path),
        "model_changes_md_path": str(model_changes_path),
        "llm": {"enabled": use_llm, "status": "not_requested"},
    }

    if use_llm:
        llm_result = run_llm_review(
            packets=packets,
            deterministic_reviews=reviews,
            output_dir=output_dir,
            timestamp=timestamp,
        )
        outputs["llm"] = llm_result["summary"]
        outputs.update(llm_result["paths"])

    return outputs


def build_case_packets(
    *,
    event_analysis: dict[str, Any],
    trade_rows: list[dict[str, Any]],
    wallet_rows: list[dict[str, Any]],
    cluster_rows: list[dict[str, Any]],
    top_n: int,
    source_trade_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    event = _event_identity(event_analysis)
    analysis_scope = str(event_analysis.get("analysis_scope") or event_analysis.get("analysisScope") or "event")
    packets: list[dict[str, Any]] = []
    source_trades_by_id = _source_trade_rows_by_id(source_trade_rows or [])

    review_wallets = _wallet_rows_for_review(wallet_rows, top_n=top_n)
    for index, wallet in enumerate(review_wallets, start=1):
        wallet_address = str(wallet.get("wallet") or "")
        full_relevant_trades = [
            _compact_trade(trade)
            for trade in trade_rows
            if str(trade.get("wallet") or "") == wallet_address
        ]
        source_trades = _source_trades_for_wallet(
            wallet,
            relevant_trades=full_relevant_trades,
            source_trades_by_id=source_trades_by_id,
        )
        relevant_trades = full_relevant_trades[:8]
        event_activity = _wallet_event_activity(wallet, full_relevant_trades)
        supporting = _supporting_evidence(wallet, full_relevant_trades, source_trades=source_trades)
        supporting["independent_hard_evidence"] = _boolish(wallet.get("independentHardEvidenceFlag")) or any(
            supporting.get(key)
            for key in (
                "low_probability_winner",
                "dormant_reactivation",
                "split_wallet",
                "shared_funding",
                "suspicious_funding",
            )
        )
        review_focus = (
            "under_ranked_hard_evidence_wallet"
            if _is_under_ranked_hard_evidence_wallet(wallet)
            else "top_ranked_wallet"
        )
        packets.append(
            {
                "case_id": f"wallet-{index}-{_short_id(wallet_address)}",
                "case_type": "wallet",
                "review_focus": review_focus,
                "event": event["title"],
                "analysis_scope": analysis_scope,
                "wallet": wallet_address,
                "username": str(wallet.get("username") or "Not available"),
                "profile_summary": {
                    "total_predictions": _nullable_int(wallet.get("walletTotalPredictions")),
                    "profile_views": _nullable_int(wallet.get("walletProfileViews")),
                    "joined_at": wallet.get("walletJoinedAt") or None,
                    "profile_age_days": _nullable_int(wallet.get("walletProfileAgeDays")),
                    "positions_value": None,
                    "biggest_win": None,
                },
                "wallet_export_context": {
                    "walletLoadedEventTradeCount": _nullable_int(wallet.get("walletLoadedEventTradeCount")),
                    "walletNotableTradeCount": _nullable_int(wallet.get("walletNotableTradeCount")),
                    "walletOpeningEntryCount": _nullable_int(wallet.get("walletOpeningEntryCount")),
                    "walletWinningOpeningEntryCount": _nullable_int(wallet.get("walletWinningOpeningEntryCount")),
                    "walletEventTradeDensity": _nullable_number(wallet.get("walletEventTradeDensity")),
                    "walletUniqueEventMarketsTraded": _nullable_int(wallet.get("walletUniqueEventMarketsTraded")),
                    "walletLoadedHistoryTradeCount": _nullable_int(wallet.get("walletLoadedHistoryTradeCount")),
                    "walletLoadedUniqueMarketCount": _nullable_int(wallet.get("walletLoadedUniqueMarketCount")),
                    "walletPublicPowerUserFlag": _boolish(wallet.get("walletPublicPowerUserFlag")),
                    "walletHighVolumeEventUserFlag": _boolish(wallet.get("walletHighVolumeEventUserFlag")),
                    "walletEventSaturationFlag": _boolish(wallet.get("walletEventSaturationFlag")),
                    "independentHardEvidenceFlag": _boolish(wallet.get("independentHardEvidenceFlag")),
                    "walletPrimaryReviewStatus": str(wallet.get("walletPrimaryReviewStatus") or ""),
                    "caseInterpretationClass": str(wallet.get("caseInterpretationClass") or ""),
                    "walletPublicPowerUserStatus": str(wallet.get("walletPublicPowerUserStatus") or ""),
                    "walletHighVolumeEventStatus": str(wallet.get("walletHighVolumeEventStatus") or ""),
                    "walletEventSaturationStatus": str(wallet.get("walletEventSaturationStatus") or ""),
                    "walletPublicPowerUserNote": str(wallet.get("walletPublicPowerUserNote") or ""),
                },
                "event_activity": event_activity,
                "scores": {
                    "wallet_score": _int(wallet.get("walletScore")),
                    "insider_style_wallet_score": _int(wallet.get("insiderStyleWalletScore")),
                    "top_trade_scores": [_int(trade.get("eventForensicScore")) for trade in full_relevant_trades[:3]],
                    "statistical_prior_label": str(wallet.get("walletStatisticalPriorLabel") or ""),
                    "statistical_p_value": wallet.get("walletStatisticalPValue") or None,
                },
                "supporting_evidence": supporting,
                "reducers": _reducers(wallet, full_relevant_trades),
                "relevant_trades": relevant_trades,
                "source_trades": source_trades[:8],
                "system_summary": str(wallet.get("summary") or ""),
                "question_for_reviewer": (
                    "This wallet had saved hard evidence but did not rank in the normal top wallet slice. "
                    "Is it an under-ranked insider-style case?"
                    if review_focus == "under_ranked_hard_evidence_wallet"
                    else "Is this a plausible insider-style case or a high-volume public user false positive?"
                ),
            }
        )

    sorted_trades = sorted(trade_rows, key=lambda row: _number(row.get("eventForensicScore")), reverse=True)
    for index, trade in enumerate(sorted_trades[:top_n], start=1):
        compact = _compact_trade(trade)
        wallet_address = str(compact.get("wallet") or "")
        packets.append(
            {
                "case_id": f"trade-{index}-{_short_id(str(compact.get('id') or wallet_address))}",
                "case_type": "trade",
                "event": event["title"],
                "analysis_scope": analysis_scope,
                "wallet": wallet_address,
                "username": str(compact.get("username") or "Not available"),
                "profile_summary": {},
                "event_activity": {
                    "event_trade_count": 1,
                    "notable_trade_count": 1 if _int(compact.get("eventForensicScore")) >= 40 else 0,
                    "opening_entry_count": 1 if _boolish(compact.get("openingExposure")) else 0,
                    "winning_opening_entry_count": 1
                    if _boolish(compact.get("openingExposure")) and _boolish(compact.get("laterWon"))
                    else 0,
                    "unique_event_markets_traded": 1 if compact.get("market") else 0,
                    "related_market_trade_count": _int(compact.get("relatedMarketTrades")),
                },
                "scores": {
                    "wallet_score": 0,
                    "insider_style_wallet_score": 0,
                    "top_trade_scores": [_int(compact.get("eventForensicScore"))],
                    "statistical_prior_label": "",
                    "statistical_p_value": None,
                },
                "supporting_evidence": _trade_supporting_evidence(compact),
                "reducers": _trade_reducers(compact),
                "relevant_trades": [compact],
                "system_summary": str(compact.get("summary") or ""),
                "question_for_reviewer": "Does this trade show independent insider-style evidence or only event context?",
            }
        )

    for index, cluster in enumerate(cluster_rows[:top_n], start=1):
        packets.append(
            {
                "case_id": f"cluster-{index}-{cluster.get('id') or index}",
                "case_type": "cluster",
                "event": event["title"],
                "analysis_scope": analysis_scope,
                "wallet": "",
                "username": "",
                "profile_summary": {},
                "event_activity": {
                    "event_trade_count": 0,
                    "notable_trade_count": 0,
                    "opening_entry_count": 0,
                    "winning_opening_entry_count": 0,
                    "unique_event_markets_traded": 0,
                    "related_market_trade_count": _int(cluster.get("relatedMarketOverlap")),
                    "wallet_count": _int(cluster.get("walletCount")),
                },
                "scores": {"cluster_score": _int(cluster.get("clusterScore"))},
                "supporting_evidence": {
                    "beat_consensus": False,
                    "favorable_repricing": False,
                    "low_probability_winner": False,
                    "dormant_reactivation": False,
                    "split_wallet": False,
                    "shared_funding": _boolish(cluster.get("sameFunder")),
                    "suspicious_funding": False,
                    "same_side_cluster": _boolish(cluster.get("sameSideTimingPattern")),
                    "independent_hard_evidence": _boolish(cluster.get("sameFunder")),
                },
                "reducers": {},
                "relevant_trades": [],
                "system_summary": str(cluster.get("summary") or ""),
                "question_for_reviewer": "Does this linked-wallet group show hard linkage or only broad same-side activity?",
            }
        )
    return packets


def review_case_packet(packet: dict[str, Any]) -> dict[str, Any]:
    evidence = packet.get("supporting_evidence") if isinstance(packet.get("supporting_evidence"), dict) else {}
    reducers = packet.get("reducers") if isinstance(packet.get("reducers"), dict) else {}
    activity = packet.get("event_activity") if isinstance(packet.get("event_activity"), dict) else {}
    suspicious_funding_quality = str(evidence.get("suspicious_funding_quality") or "").strip()
    suspicious_funding_hard_eligible = _boolish(evidence.get("suspicious_funding_hard_evidence_eligible"))
    hard_evidence = bool(evidence.get("independent_hard_evidence")) or any(
        bool(evidence.get(key))
        for key in (
            "split_wallet",
            "shared_funding",
            "low_probability_winner",
            "dormant_reactivation",
        )
    ) or (
        bool(evidence.get("suspicious_funding"))
        and suspicious_funding_hard_eligible
    )
    high_volume = bool(reducers.get("high_volume_public_user")) or _int(activity.get("event_trade_count")) >= 25
    high_volume = high_volume or _int(activity.get("notable_trade_count")) >= 20
    high_volume = high_volume or _int(activity.get("winning_opening_entry_count")) >= 15
    event_saturation = bool(reducers.get("event_saturation")) or (
        _int(activity.get("winning_opening_entry_count")) >= 15
    )

    supports: list[str] = []
    weakens: list[str] = []
    hard_sources = [
        str(source)
        for source in evidence.get("hard_evidence_sources", [])
        if str(source or "").strip()
    ] if isinstance(evidence.get("hard_evidence_sources"), list) else []
    source_flags = [
        str(source)
        for source in evidence.get("evidence_source_flags", [])
        if str(source or "").strip()
    ] if isinstance(evidence.get("evidence_source_flags"), list) else []
    high_impact_quality = str(evidence.get("high_impact_source_quality") or "").strip()
    high_impact_quality_reasons = [
        str(reason)
        for reason in evidence.get("high_impact_source_quality_reasons", [])
        if str(reason or "").strip()
    ] if isinstance(evidence.get("high_impact_source_quality_reasons"), list) else []
    high_impact_present = _has_high_impact_source(
        hard_sources
        + source_flags
        + (
            evidence.get("hard_evidence_source_details", [])
            if isinstance(evidence.get("hard_evidence_source_details"), list)
            else []
        )
    )
    corroborating_hard_evidence = any(
        bool(evidence.get(key))
        for key in (
            "split_wallet",
            "shared_funding",
            "low_probability_winner",
            "dormant_reactivation",
        )
    ) or (
        bool(evidence.get("suspicious_funding"))
        and suspicious_funding_hard_eligible
    ) or any(_is_corroborating_hard_evidence_source(source) for source in hard_sources)
    high_impact_only_advisory = (
        high_impact_present
        and hard_evidence
        and not corroborating_hard_evidence
        and high_impact_quality in HIGH_IMPACT_SOURCE_QUALITY_ADVISORY
    )
    if not suspicious_funding_hard_eligible and hard_sources:
        funding_source_only = all(
            "suspicious" in str(source or "").lower() or "opaque funding" in str(source or "").lower()
            for source in hard_sources
        )
        if funding_source_only:
            corroborating_hard_evidence = False
            hard_evidence = bool(
                evidence.get("split_wallet")
                or evidence.get("shared_funding")
                or evidence.get("low_probability_winner")
                or evidence.get("dormant_reactivation")
            )
    effective_hard_evidence = hard_evidence and not high_impact_only_advisory

    if hard_evidence:
        if hard_sources:
            if high_impact_only_advisory:
                supports.append(
                    "High-impact timing/repricing evidence is present in saved outputs, "
                    f"but reviewer source quality is `{high_impact_quality}`."
                )
            else:
                supports.append("Independent hard evidence in saved outputs: " + "; ".join(hard_sources) + ".")
        else:
            supports.append("Independent hard evidence is present in the saved InsPoly outputs.")
        if source_flags:
            supports.append("Concrete wallet evidence source flags: " + "; ".join(source_flags) + ".")
        if high_impact_quality:
            quality_text = f"High-impact timing/repricing source quality is `{high_impact_quality}`"
            if high_impact_quality_reasons:
                quality_text += ": " + "; ".join(high_impact_quality_reasons)
            quality_text += "."
            if high_impact_quality in HIGH_IMPACT_SOURCE_QUALITY_ADVISORY:
                weakens.append(quality_text)
            else:
                supports.append(quality_text)
    if evidence.get("suspicious_funding"):
        funding_text = f"Suspicious funding quality is `{suspicious_funding_quality or 'unknown'}`"
        funding_reasons = [
            str(reason)
            for reason in evidence.get("suspicious_funding_quality_reasons", [])
            if str(reason or "").strip()
        ] if isinstance(evidence.get("suspicious_funding_quality_reasons"), list) else []
        if funding_reasons:
            funding_text += ": " + "; ".join(funding_reasons)
        support_sources = [
            str(source)
            for source in evidence.get("suspicious_funding_independent_support_sources", [])
            if str(source or "").strip()
        ] if isinstance(evidence.get("suspicious_funding_independent_support_sources"), list) else []
        suppressor_reasons = [
            str(reason)
            for reason in evidence.get("suspicious_funding_suppressor_conflict_reasons", [])
            if str(reason or "").strip()
        ] if isinstance(evidence.get("suspicious_funding_suppressor_conflict_reasons"), list) else []
        if support_sources:
            funding_text += " Independent support: " + "; ".join(support_sources)
        if _boolish(evidence.get("suspicious_funding_suppressor_conflict")):
            funding_text += " Suppressor conflict"
            if suppressor_reasons:
                funding_text += ": " + "; ".join(suppressor_reasons)
        funding_text += "."
        if (
            suspicious_funding_quality == SUSPICIOUS_FUNDING_QUALITY_STRONG
            and suspicious_funding_hard_eligible
        ):
            supports.append(funding_text)
        elif suspicious_funding_quality == SUSPICIOUS_FUNDING_QUALITY_MODERATE and suspicious_funding_hard_eligible:
            supports.append(funding_text)
        else:
            weakens.append(funding_text)
    if packet.get("review_focus") == "under_ranked_hard_evidence_wallet":
        supports.append("Reviewer included this wallet because saved hard evidence was present despite low rank or no primary trade.")
    if evidence.get("beat_consensus") or evidence.get("favorable_repricing"):
        supports.append("The packet contains timing or repricing evidence.")
    if high_volume:
        weakens.append("High event/account volume can explain repeated winning entries without insider-style access.")
    if reducers.get("bot_like"):
        weakens.append("Bot-like or low-manual-value behavior was recorded.")
    if reducers.get("weak_economic_history"):
        weakens.append("Weak wallet economic history tempers the case.")
    if reducers.get("near_certainty"):
        weakens.append("Near-certainty entry weakens later-correctness evidence.")
    if reducers.get("yield_farm"):
        weakens.append("Yield-farm or capital-parking behavior weakens the insider-style interpretation.")
    if reducers.get("theta_decay"):
        weakens.append("Deadline or theta-decay behavior weakens the insider-style interpretation.")
    if reducers.get("resolution_gap"):
        weakens.append("Stale-resolution or public-information lag weakens the insider-style interpretation.")
    if not effective_hard_evidence:
        weakens.append("No independent funding, split-wallet, low-probability, or dormancy evidence is present.")
    if high_volume and not effective_hard_evidence:
        weakens.append(
            "High volume and repeated wins appear without independent hard evidence, so the saved ranking should be treated as likely public power-user activity."
        )

    scores = packet.get("scores") if isinstance(packet.get("scores"), dict) else {}
    if (
        _int(scores.get("wallet_score")) > 80
        and _int(scores.get("insider_style_wallet_score")) == 0
        and not effective_hard_evidence
    ):
        weakens.append(
            "This wallet has a high generic wallet score but zero insider-style score and no independent hard evidence. It should not be treated as a top insider-style candidate."
        )

    if high_volume and not effective_hard_evidence:
        verdict = "likely_false_positive"
        interpretation = "high_volume_public_power_user"
        confidence = 0.86 if event_saturation else 0.78
        reason = "High-volume activity dominates the concern signal without independent hard evidence."
    elif (reducers.get("bot_like") or reducers.get("specialist")) and not effective_hard_evidence:
        verdict = "ambiguous"
        interpretation = "bot_or_low_analyst_value"
        confidence = 0.62
        reason = "Bot-like or specialist behavior weakens the one-off insider-style interpretation without hard evidence."
    elif (
        reducers.get("near_certainty")
        or reducers.get("yield_farm")
        or reducers.get("theta_decay")
        or reducers.get("resolution_gap")
    ) and not effective_hard_evidence:
        verdict = "ambiguous"
        interpretation = "stale_or_resolution_gap"
        confidence = 0.66 if reducers.get("resolution_gap") else 0.6
        reason = "Near-certainty, yield-farm, deadline-decay, or stale-resolution signals weaken the case without hard evidence."
    elif effective_hard_evidence:
        verdict = "plausible_insider_style"
        source_text = " ".join(hard_sources).lower()
        interpretation = (
            "cluster_or_linkage_case"
            if evidence.get("split_wallet")
            or evidence.get("shared_funding")
            or "cluster" in source_text
            or "split-wallet" in source_text
            or "shared funding" in source_text
            else "insider_style_candidate"
        )
        confidence = 0.7
        reason = "The case has independent evidence beyond repeated correctness or volume."
    elif high_impact_only_advisory:
        verdict = "ambiguous"
        interpretation = "ambiguous_needs_review"
        confidence = 0.61
        reason = (
            "High-impact timing/repricing is present, but its source quality needs manual interpretation "
            "before treating it as independent hard evidence."
        )
    elif packet.get("case_type") == "cluster" and evidence.get("same_side_cluster"):
        verdict = "ambiguous"
        interpretation = "cluster_or_linkage_case"
        confidence = 0.58
        reason = "Same-side clustering is review-worthy but needs funding or repeated behavior before escalation."
    else:
        verdict = "ambiguous"
        interpretation = "ambiguous_needs_review"
        confidence = 0.55
        reason = "The saved packet is not clearly high-volume noise, but it lacks hard corroborating evidence."

    return {
        "case_id": packet.get("case_id", ""),
        "review_verdict": verdict,
        "interpretation_class": interpretation,
        "confidence": confidence,
        "main_reason": reason,
        "evidence_that_supports_concern": supports,
        "evidence_that_weakens_concern": weakens,
        "missing_data_needed": _missing_data(packet),
        "recommended_model_change": _recommended_model_changes(verdict, interpretation),
        "recommended_test_fixture": _recommended_tests(verdict, interpretation),
        "automatic_code_change_allowed": False,
    }


def _wallet_rows_for_review(wallet_rows: list[dict[str, Any]], *, top_n: int) -> list[dict[str, Any]]:
    sorted_wallets = sorted(wallet_rows, key=lambda row: _number(row.get("walletScore")), reverse=True)
    selected = list(sorted_wallets[:top_n])
    selected_wallets = {str(row.get("wallet") or "") for row in selected}
    supplemental: list[dict[str, Any]] = []
    for wallet in sorted_wallets[top_n:]:
        wallet_address = str(wallet.get("wallet") or "")
        if not wallet_address or wallet_address in selected_wallets:
            continue
        if not _is_under_ranked_hard_evidence_wallet(wallet):
            continue
        supplemental.append(wallet)
        selected_wallets.add(wallet_address)
        if len(supplemental) >= UNDER_RANKED_HARD_EVIDENCE_WALLET_LIMIT:
            break
    return selected + supplemental


def _is_under_ranked_hard_evidence_wallet(wallet: dict[str, Any]) -> bool:
    if not _boolish(wallet.get("independentHardEvidenceFlag")):
        return False
    wallet_score = _int(wallet.get("walletScore"))
    notable_count = _int(wallet.get("suspiciousTradeCount") or wallet.get("walletNotableTradeCount"))
    primary_status = str(wallet.get("walletPrimaryReviewStatus") or "")
    return notable_count <= 0 or wallet_score < 45 or primary_status not in {"", "primary_allowed"}


def run_llm_review(
    *,
    packets: list[dict[str, Any]],
    deterministic_reviews: list[dict[str, Any]],
    output_dir: Path,
    timestamp: str,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    provider = (provider or os.environ.get("INSPOLY_LLM_PROVIDER") or "").strip().lower()
    model = (model or os.environ.get("INSPOLY_LLM_MODEL") or "").strip()
    api_key = api_key or os.environ.get("OPENAI_API_KEY")

    cases_path = output_dir / f"AI_CASE_REVIEW_LLM_CASES_{timestamp}.json"
    report_path = output_dir / f"AI_CASE_REVIEW_LLM_REPORT_{timestamp}.md"
    model_changes_path = output_dir / f"AI_CASE_REVIEW_LLM_MODEL_CHANGES_{timestamp}.md"
    raw_path = output_dir / f"AI_CASE_REVIEW_LLM_RAW_{timestamp}.jsonl"
    paths = {
        "llm_cases_json_path": str(cases_path),
        "llm_review_report_md_path": str(report_path),
        "llm_model_changes_md_path": str(model_changes_path),
        "llm_raw_jsonl_path": str(raw_path),
    }

    if provider != "openai" or not api_key or not model:
        reason = "LLM reviewer skipped: no provider/API key configured."
        payload = _llm_payload(
            status="skipped",
            reason=reason,
            packets=packets,
            deterministic_reviews=deterministic_reviews,
            llm_response={},
        )
        _write_llm_outputs(payload, cases_path, report_path, model_changes_path, raw_path)
        return {"summary": {"enabled": True, "status": "skipped", "reason": reason}, "paths": paths}

    try:
        response_text = _call_openai_llm(packet_payload=packets, model=model, api_key=api_key)
    except Exception as exc:  # noqa: BLE001 - reviewer must not break deterministic output
        reason = f"LLM reviewer failed: {type(exc).__name__}: {exc}"
        payload = _llm_payload(
            status="failed",
            reason=reason,
            packets=packets,
            deterministic_reviews=deterministic_reviews,
            llm_response={},
        )
        raw_path.write_text(json.dumps({"error": reason}, ensure_ascii=False) + "\n", encoding="utf-8")
        cases_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        report_path.write_text(_render_llm_report(payload), encoding="utf-8")
        model_changes_path.write_text(_render_llm_model_changes(payload), encoding="utf-8")
        return {"summary": {"enabled": True, "status": "failed", "reason": reason}, "paths": paths}

    raw_path.write_text(json.dumps({"raw_output": response_text}, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        parsed = json.loads(response_text)
        _validate_llm_output(parsed)
        status = "completed"
        reason = "LLM review completed."
    except (json.JSONDecodeError, ReviewInputError) as exc:
        parsed = {}
        status = "invalid"
        reason = f"LLM review invalid: {exc}"

    payload = _llm_payload(
        status=status,
        reason=reason,
        packets=packets,
        deterministic_reviews=deterministic_reviews,
        llm_response=parsed,
    )
    cases_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_render_llm_report(payload), encoding="utf-8")
    model_changes_path.write_text(_render_llm_model_changes(payload), encoding="utf-8")
    return {"summary": {"enabled": True, "status": status, "reason": reason}, "paths": paths}


def _call_openai_llm(*, packet_payload: list[dict[str, Any]], model: str, api_key: str) -> str:
    prompt = {
        "instructions": _llm_system_instructions(),
        "case_packets": packet_payload,
    }
    request_payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": "You are an advisory case reviewer. Return strict JSON only.",
            },
            {
                "role": "user",
                "content": json.dumps(prompt, ensure_ascii=False),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "inspoly_case_review",
                "strict": True,
                "schema": _llm_output_schema(),
            }
        },
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail}") from exc
    return _extract_openai_text(response_payload)


def _extract_openai_text(response_payload: dict[str, Any]) -> str:
    if isinstance(response_payload.get("output_text"), str):
        return str(response_payload["output_text"])
    parts: list[str] = []
    for output in response_payload.get("output") or []:
        for content in output.get("content") or []:
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                parts.append(content["text"])
    if not parts:
        raise RuntimeError("OpenAI response did not include output text.")
    return "".join(parts)


def _llm_system_instructions() -> str:
    return (
        "Use only the provided case packet. Do not browse, use news, or invent external facts. "
        "Do not call a case insider-like unless there is independent insider-style evidence. "
        "High volume, many predictions, many wins, and public profile visibility are not enough. "
        "Repeated correctness in hundreds of trades is often power-user behavior, not insider evidence. "
        "Later correctness alone is not enough. Stronger evidence includes new/dormant wallets, low-probability "
        "winning entries, opaque recent funding, shared funding, split-wallet behavior, same-side clusters of "
        "new or reactivated wallets, strong timing before repricing, unusual size, and post-win dormancy. "
        "Recommend deterministic rules and tests, not vague AI scoring."
    )


def _llm_output_schema() -> dict[str, Any]:
    review_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "case_id": {"type": "string"},
            "llm_review_verdict": {
                "type": "string",
                "enum": ["likely_false_positive", "plausible_insider_style", "ambiguous", "needs_data"],
            },
            "interpretation_class": {
                "type": "string",
                "enum": [
                    "high_volume_public_power_user",
                    "insider_style_candidate",
                    "cluster_or_linkage_case",
                    "stale_or_resolution_gap",
                    "bot_or_low_value",
                    "bot_or_low_analyst_value",
                    "ambiguous_needs_review",
                ],
            },
            "confidence": {"type": "number"},
            "main_reason": {"type": "string"},
            "evidence_that_supports_concern": {"type": "array", "items": {"type": "string"}},
            "evidence_that_weakens_concern": {"type": "array", "items": {"type": "string"}},
            "missing_data_needed": {"type": "array", "items": {"type": "string"}},
            "recommended_model_change": {"type": "array", "items": {"type": "string"}},
            "recommended_test_fixture": {"type": "array", "items": {"type": "string"}},
            "should_codex_implement_change": {"type": "boolean"},
            "implementation_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": [
            "case_id",
            "llm_review_verdict",
            "interpretation_class",
            "confidence",
            "main_reason",
            "evidence_that_supports_concern",
            "evidence_that_weakens_concern",
            "missing_data_needed",
            "recommended_model_change",
            "recommended_test_fixture",
            "should_codex_implement_change",
            "implementation_risk",
        ],
    }
    recommendation_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "change_id": {"type": "string"},
            "target_area": {
                "type": "string",
                "enum": ["wallet_ranking", "trade_scoring", "case_reviewer", "ui", "exports", "tests"],
            },
            "problem": {"type": "string"},
            "proposed_change": {"type": "string"},
            "expected_effect": {"type": "string"},
            "risk": {"type": "string", "enum": ["low", "medium", "high"]},
            "requires_scoring_change": {"type": "boolean"},
            "requires_ui_change": {"type": "boolean"},
            "test_plan": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "change_id",
            "target_area",
            "problem",
            "proposed_change",
            "expected_effect",
            "risk",
            "requires_scoring_change",
            "requires_ui_change",
            "test_plan",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "case_reviews": {"type": "array", "items": review_item},
            "model_recommendations": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "recommended_changes": {"type": "array", "items": recommendation_item},
                },
                "required": ["recommended_changes"],
            },
        },
        "required": ["case_reviews", "model_recommendations"],
    }


def _validate_llm_output(payload: dict[str, Any]) -> None:
    if not isinstance(payload.get("case_reviews"), list):
        raise ReviewInputError("LLM output missing case_reviews array.")
    recommendations = payload.get("model_recommendations")
    if not isinstance(recommendations, dict) or not isinstance(recommendations.get("recommended_changes"), list):
        raise ReviewInputError("LLM output missing model_recommendations.recommended_changes array.")


def _llm_payload(
    *,
    status: str,
    reason: str,
    packets: list[dict[str, Any]],
    deterministic_reviews: list[dict[str, Any]],
    llm_response: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "reason": reason,
        "safety": {
            "production_code_modified": False,
            "automatic_scoring_changes_applied": False,
            "llm_output_is_advisory": True,
        },
        "case_packets": packets,
        "deterministic_reviews": deterministic_reviews,
        "llm_response": llm_response,
    }


def _write_llm_outputs(
    payload: dict[str, Any],
    cases_path: Path,
    report_path: Path,
    model_changes_path: Path,
    raw_path: Path,
) -> None:
    cases_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_render_llm_report(payload), encoding="utf-8")
    model_changes_path.write_text(_render_llm_model_changes(payload), encoding="utf-8")
    raw_path.write_text(json.dumps({"status": payload["status"], "reason": payload["reason"]}, ensure_ascii=False) + "\n", encoding="utf-8")


def _render_llm_report(payload: dict[str, Any]) -> str:
    response = payload.get("llm_response") if isinstance(payload.get("llm_response"), dict) else {}
    reviews = response.get("case_reviews") if isinstance(response.get("case_reviews"), list) else []
    lines = [
        "# InsPoly LLM Case Review",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Reason: {payload.get('reason')}",
        "- Safety: LLM review is advisory. It does not modify scoring rules.",
        "",
    ]
    if not reviews:
        lines.append("No valid LLM case reviews were available.")
        return "\n".join(lines)
    lines.extend(["## LLM Findings", ""])
    for review in reviews:
        lines.extend(
            [
                f"### {review.get('case_id', '')}",
                "",
                f"- Verdict: `{review.get('llm_review_verdict', '')}`",
                f"- Interpretation: `{review.get('interpretation_class', '')}`",
                f"- Confidence: {review.get('confidence', '')}",
                f"- Main reason: {review.get('main_reason', '')}",
                f"- Implementation risk: {review.get('implementation_risk', '')}",
                f"- Codex should implement directly: {review.get('should_codex_implement_change', False)}",
                "",
            ]
        )
    return "\n".join(lines)


def _render_llm_model_changes(payload: dict[str, Any]) -> str:
    response = payload.get("llm_response") if isinstance(payload.get("llm_response"), dict) else {}
    recommendations = response.get("model_recommendations") if isinstance(response.get("model_recommendations"), dict) else {}
    changes = recommendations.get("recommended_changes") if isinstance(recommendations.get("recommended_changes"), list) else []
    lines = [
        "# InsPoly LLM Model Recommendations",
        "",
        "These recommendations are advisory. The reviewer did not edit production code or scoring rules.",
        "",
    ]
    if not changes:
        lines.append("No valid LLM model recommendations were available.")
        return "\n".join(lines)
    for item in changes:
        lines.extend(
            [
                f"## {item.get('change_id', 'change')}",
                "",
                f"- Target area: `{item.get('target_area', '')}`",
                f"- Problem: {item.get('problem', '')}",
                f"- Proposed change: {item.get('proposed_change', '')}",
                f"- Expected effect: {item.get('expected_effect', '')}",
                f"- Risk: {item.get('risk', '')}",
                f"- Requires scoring change: {item.get('requires_scoring_change', False)}",
                f"- Requires UI change: {item.get('requires_ui_change', False)}",
                f"- Test plan: {'; '.join(item.get('test_plan') or [])}",
                "",
            ]
        )
    return "\n".join(lines)


def _supporting_evidence(
    wallet: dict[str, Any],
    trades: list[dict[str, Any]],
    *,
    source_trades: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    summary = " ".join([str(wallet.get("summary") or ""), *(str(trade.get("summary") or "") for trade in trades)])
    flags = " ".join(
        " ".join(str(flag) for flag in trade.get("eventForensicFlags", []))
        if isinstance(trade.get("eventForensicFlags"), list)
        else str(trade.get("eventForensicFlags") or "")
        for trade in trades
    ).lower()
    funding_flags = str(wallet.get("fundingFlags") or "")
    wallet_hard_sources = _listish(wallet.get("hardEvidenceSources")) or _listish(wallet.get("walletHardEvidenceSources"))
    wallet_source_flags = _listish(wallet.get("walletEvidenceSourceFlags"))
    wallet_source_details = _listish(wallet.get("walletHardEvidenceSourceDetails"))
    stable_source_details = [
        value
        for value in (
            wallet.get("hardEvidencePrimaryReason"),
            "; ".join(_listish(wallet.get("hardEvidenceTradeIds"))),
            "; ".join(_listish(wallet.get("hardEvidenceWalletIds"))),
        )
        if str(value or "").strip()
    ]
    hard_sources = _dedupe(
        wallet_hard_sources
        + [
            source
            for trade in trades
            for source in _listish(trade.get("hardEvidenceSources"))
        ]
    )
    if _boolish(wallet.get("independentHardEvidenceFlag")) and not hard_sources:
        hard_sources.append("saved wallet hard-evidence flag")
    source_flags = _dedupe(wallet_source_flags)
    source_details = _dedupe(wallet_source_details + stable_source_details)
    source_text = " ".join([*hard_sources, *source_flags]).lower()
    high_impact_source_trade_ids = _detail_values(source_details, "trade_id")
    available_source_trade_ids = _dedupe(
        str(trade.get("id") or trade.get("tradeId") or trade.get("trade_id") or "").strip()
        for trade in (source_trades or [])
        if str(trade.get("id") or trade.get("tradeId") or trade.get("trade_id") or "").strip()
    )
    available_source_trade_id_set = set(available_source_trade_ids)
    high_impact_quality, high_impact_quality_reasons = _high_impact_source_quality(
        hard_sources=hard_sources,
        source_flags=source_flags,
        source_details=source_details,
        trades=trades,
        source_trades=source_trades or [],
    )
    (
        suspicious_quality,
        suspicious_reasons,
        suspicious_eligible,
        suspicious_support,
        suspicious_support_sources,
        suspicious_suppressor_conflict,
        suspicious_suppressor_reasons,
    ) = _suspicious_funding_quality_from_rows(
        wallet=wallet,
        trades=trades,
    )
    return {
        "beat_consensus": "beat_consensus" in flags or "beat_consensus" in source_text,
        "favorable_repricing": (
            "post_entry_repricing" in flags
            or "repricing" in summary.lower()
            or "repricing" in source_text
        ),
        "low_probability_winner": (
            "low_probability_winner" in flags
            or "low_probability_winner" in source_text
            or "low-probability" in source_text
        ),
        "dormant_reactivation": (
            "dormant_reactivation" in flags
            or "reactivated" in summary.lower()
            or "dormant" in source_text
        ),
        "split_wallet": (
            "split_wallet" in flags
            or "split-wallet" in summary.lower()
            or "split_wallet" in source_text
            or "split-wallet" in source_text
        ),
        "shared_funding": (
            funding_flags.startswith("Shared")
            or "shared-funding" in summary.lower()
            or "shared_funding" in source_text
            or "shared funding" in source_text
        ),
        "suspicious_funding": (
            "recent_opaque_funding" in flags
            or "suspicious_funding" in source_text
            or "recent_opaque_funding" in source_text
            or "opaque funding" in summary.lower()
            or ("funding" in source_text and "shared" not in source_text)
        ),
        "same_side_cluster": (
            "same_side_cluster" in flags
            or "same_side_cluster" in source_text
            or "same-side" in summary.lower()
        ),
        "independent_hard_evidence": _boolish(wallet.get("independentHardEvidenceFlag")) or bool(hard_sources),
        "hard_evidence_sources": hard_sources,
        "evidence_source_flags": source_flags,
        "hard_evidence_source_details": source_details,
        "high_impact_source_trade_ids": high_impact_source_trade_ids,
        "high_impact_source_trade_rows_available": len(available_source_trade_ids),
        "high_impact_source_trade_rows_missing": [
            trade_id for trade_id in high_impact_source_trade_ids if trade_id not in available_source_trade_id_set
        ],
        "high_impact_source_quality": high_impact_quality,
        "high_impact_source_quality_reasons": high_impact_quality_reasons,
        "suspicious_funding_quality": suspicious_quality,
        "suspicious_funding_quality_reasons": suspicious_reasons,
        "suspicious_funding_hard_evidence_eligible": suspicious_eligible,
        "suspicious_funding_independent_support": suspicious_support,
        "suspicious_funding_independent_support_sources": suspicious_support_sources,
        "suspicious_funding_suppressor_conflict": suspicious_suppressor_conflict,
        "suspicious_funding_suppressor_conflict_reasons": suspicious_suppressor_reasons,
    }


def _source_trade_rows_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        trade_id = _trade_id(row)
        if trade_id and trade_id not in by_id:
            by_id[trade_id] = row
    return by_id


def _merge_source_trade_packet_row(
    relevant_row: dict[str, Any] | None,
    source_row: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if relevant_row is None and source_row is None:
        return None
    if relevant_row is None:
        return dict(source_row or {})
    if source_row is None:
        return dict(relevant_row)

    merged = dict(relevant_row)
    for key, value in source_row.items():
        if key == "rawMetrics":
            source_metrics = value if isinstance(value, dict) else {}
            relevant_metrics = merged.get(key) if isinstance(merged.get(key), dict) else {}
            if source_metrics or relevant_metrics:
                merged[key] = {**source_metrics, **relevant_metrics}
            continue
        if key not in merged or _empty_value(merged.get(key)):
            merged[key] = value
    return merged


def _nullable_int_preserve_zero(value: Any) -> int | None:
    try:
        text = str(value if value is not None else "").replace(",", "").strip()
        if text.endswith("%"):
            text = text[:-1]
        return int(float(text)) if text else None
    except ValueError:
        return None


def _source_trades_for_wallet(
    wallet: dict[str, Any],
    *,
    relevant_trades: list[dict[str, Any]],
    source_trades_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    source_ids = _detail_values(_listish(wallet.get("walletHardEvidenceSourceDetails")), "trade_id")
    if not source_ids:
        return []

    relevant_by_id = {
        _trade_id(trade): trade
        for trade in relevant_trades
        if _trade_id(trade)
    }
    wallet_address = str(wallet.get("wallet") or "").strip().lower()
    source_trades: list[dict[str, Any]] = []
    for trade_id in source_ids:
        relevant_row = relevant_by_id.get(trade_id)
        source_row = source_trades_by_id.get(trade_id)
        row = _merge_source_trade_packet_row(relevant_row, source_row)
        if not row:
            continue
        if wallet_address and str(row.get("wallet") or "").strip().lower() != wallet_address:
            continue
        compact = dict(_compact_trade(row))
        raw_metrics = row.get("rawMetrics") if isinstance(row.get("rawMetrics"), dict) else {}
        if raw_metrics:
            compact["rawMetrics"] = dict(raw_metrics)
        source_score = _nullable_int_preserve_zero(row.get("eventForensicScore"))
        if source_score is not None:
            compact["eventForensicScore"] = source_score
        compact["source"] = "reviewer_relevant_trades" if relevant_row else "raw_event_bundle"
        if relevant_row and source_row:
            compact["enrichedSource"] = "raw_event_bundle"
        source_trades.append(compact)
    return _dedupe_trade_rows(source_trades)


def _dedupe_trade_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        trade_id = _trade_id(row)
        key = trade_id or "|".join(str(row.get(key) or "") for key in ("wallet", "timestamp", "conditionId", "price"))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _trade_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or row.get("tradeId") or row.get("trade_id") or "").strip()


def _has_high_impact_source(values: list[Any]) -> bool:
    return any(
        "high_impact_timing_or_repricing" in str(value or "").lower()
        or "high-impact timing/repricing" in str(value or "").lower()
        for value in values
    )


def _is_corroborating_hard_evidence_source(source: Any) -> bool:
    text = str(source or "").lower()
    if not text or text == "saved wallet hard-evidence flag" or _has_high_impact_source([text]):
        return False
    return any(
        token in text
        for token in (
            "split_wallet",
            "split-wallet",
            "shared_funding",
            "strict_shared_funding",
            "shared funding",
            "suspicious_funding",
            "suspicious_recent_funding",
            "recent_opaque_funding",
            "opaque funding",
            "low_probability_winner",
            "low_probability_early_winner",
            "low-probability",
            "dormant_reactivation",
            "dormant_wallet_reactivation",
            "dormant wallet",
            "event_family_repeat_narrow_context",
            "newly activated",
            "reactivated",
        )
    )


def _normalize_high_impact_source_quality(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {HIGH_IMPACT_SOURCE_QUALITY_STRONG, HIGH_IMPACT_SOURCE_QUALITY_WEAK, HIGH_IMPACT_SOURCE_QUALITY_MECHANICAL}:
        return text
    if text in {"public-news/thin-market", "mechanical/thin-market"}:
        return HIGH_IMPACT_SOURCE_QUALITY_MECHANICAL
    if text in {"weak/context-only", "needs data", "needs_data"}:
        return HIGH_IMPACT_SOURCE_QUALITY_WEAK
    return ""


def _repricing_quality_from_raw(raw: dict[str, Any]) -> str:
    return _normalize_high_impact_source_quality(
        raw.get("repricing_source_quality") or raw.get("repricingSourceQuality")
    )


def _repricing_quality_reasons_from_raw(raw: dict[str, Any]) -> list[str]:
    reasons = raw.get("repricing_source_quality_reasons") or raw.get("repricingSourceQualityReasons")
    if isinstance(reasons, list):
        return [str(reason) for reason in reasons if str(reason or "").strip()]
    text = str(reasons or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r";|\|", text) if part.strip()]


def _high_impact_source_quality(
    *,
    hard_sources: list[str],
    source_flags: list[str],
    source_details: list[str],
    trades: list[dict[str, Any]],
    source_trades: list[dict[str, Any]] | None = None,
) -> tuple[str, list[str]]:
    if not _has_high_impact_source(hard_sources + source_flags + source_details):
        return "", []

    corroborating = [
        source
        for source in [*hard_sources, *source_flags]
        if _is_corroborating_hard_evidence_source(source)
    ]
    if corroborating:
        return "strong", ["corroborated by non-high-impact hard evidence: " + "; ".join(_dedupe(corroborating))]

    detail_text = " ".join(source_details).lower()
    reasons: list[str] = []
    source_trade_ids = _detail_values(source_details, "trade_id")
    trades_by_id = {
        str(trade.get("id") or "").lower(): trade
        for trade in trades
        if str(trade.get("id") or "").strip()
    }
    source_trades_by_id = {
        str(trade.get("id") or trade.get("tradeId") or trade.get("trade_id") or "").lower(): trade
        for trade in (source_trades or [])
        if str(trade.get("id") or trade.get("tradeId") or trade.get("trade_id") or "").strip()
    }
    matching_source_trades = [
        trades_by_id[trade_id.lower()]
        for trade_id in source_trade_ids
        if trade_id.lower() in trades_by_id
    ]
    matching_raw_source_trades = [
        source_trades_by_id[trade_id.lower()]
        for trade_id in source_trade_ids
        if trade_id.lower() not in trades_by_id and trade_id.lower() in source_trades_by_id
    ]
    quality_candidates = [
        _normalize_high_impact_source_quality(value)
        for value in _detail_values(source_details, "repricing_source_quality")
    ]
    quality_reasons = _detail_values(source_details, "repricing_source_quality_reasons")
    for source_trade in [*matching_source_trades, *matching_raw_source_trades]:
        quality_candidates.append(_normalize_high_impact_source_quality(source_trade.get("repricingSourceQuality")))
        raw = source_trade.get("rawMetrics") if isinstance(source_trade.get("rawMetrics"), dict) else {}
        if raw:
            quality_candidates.append(_repricing_quality_from_raw(raw))
            quality_reasons.extend(_repricing_quality_reasons_from_raw(raw))
    source_quality = next((quality for quality in quality_candidates if quality), "")

    if source_trade_ids and not matching_source_trades and not matching_raw_source_trades and not source_quality:
        return HIGH_IMPACT_SOURCE_QUALITY_WEAK, ["source trade id is not present in Case Reviewer relevant trades"]
    if matching_source_trades and not any(_boolish(trade.get("openingExposure")) for trade in matching_source_trades):
        return HIGH_IMPACT_SOURCE_QUALITY_WEAK, ["source trade is not a clean opening exposure in the reviewer packet"]
    if matching_raw_source_trades:
        explicit_opening_values = [
            trade.get("openingExposure")
            for trade in matching_raw_source_trades
            if trade.get("openingExposure") is not None
        ]
        if explicit_opening_values and not any(_boolish(value) for value in explicit_opening_values):
            return HIGH_IMPACT_SOURCE_QUALITY_WEAK, ["source trade is not a clean opening exposure in the raw source rows"]
        if not matching_source_trades and not any(_boolish(value) for value in explicit_opening_values):
            return HIGH_IMPACT_SOURCE_QUALITY_WEAK, [
                "source trade row is available from raw event bundle but lacks reviewer opening-exposure context"
            ]

    if source_quality:
        reasons.extend(_dedupe(quality_reasons))
        if not reasons:
            reasons.append("saved repricing source-quality classifier is available")
        return source_quality, reasons

    if "offline_timeline_matched=yes" in detail_text:
        reasons.append("offline timeline match is recorded")
        if matching_source_trades:
            reasons.append("source trade is present in reviewer relevant trades")
        return HIGH_IMPACT_SOURCE_QUALITY_STRONG, reasons

    public_no_lag = "public_information_state=no public lag concern" in detail_text
    offline_no = "offline_timeline_matched=no" in detail_text
    mechanical_reducer = any(
        token in detail_text
        for token in ("near_certainty", "near certainty", "yield_farm", "theta_decay", "stale")
    )
    liquidity_shock = "liquidity_shock_signal=yes" in detail_text
    max_liquidity_ratio = _max_detail_number(source_details, "liquidity_ratio")
    min_market_liquidity = _min_positive_detail_number(source_details, "market_liquidity_usdc")
    thin_or_shock = (
        liquidity_shock
        or max_liquidity_ratio >= 5.0
        or (0.0 < min_market_liquidity <= 100000.0)
    )
    if mechanical_reducer:
        reasons.append("near-certainty, stale, yield, or theta marker appears in source detail")
        return HIGH_IMPACT_SOURCE_QUALITY_MECHANICAL, reasons
    if public_no_lag and offline_no and thin_or_shock:
        reasons.append("detail records no offline timeline match and no public-lag concern")
        if liquidity_shock:
            reasons.append("liquidity shock signal is present")
        if max_liquidity_ratio > 0:
            reasons.append(f"liquidity ratio reached {max_liquidity_ratio:g}%")
        if min_market_liquidity > 0:
            reasons.append(f"market liquidity was {min_market_liquidity:g} USDC")
        return HIGH_IMPACT_SOURCE_QUALITY_MECHANICAL, reasons

    if not source_trade_ids:
        reasons.append("source trade id is not available in high-impact detail")
    if not detail_text:
        reasons.append("high-impact source detail is not available")
    if public_no_lag:
        reasons.append("detail records no public-lag concern")
    if offline_no:
        reasons.append("detail records no offline timeline match")
    return HIGH_IMPACT_SOURCE_QUALITY_WEAK, reasons or ["high-impact source lacks enough detail for independent-quality interpretation"]


def _suspicious_funding_quality_from_rows(
    *,
    wallet: dict[str, Any],
    trades: list[dict[str, Any]],
) -> tuple[str, list[str], bool, bool, list[str], bool, list[str]]:
    quality_rank = {
        SUSPICIOUS_FUNDING_QUALITY_STRONG: 4,
        SUSPICIOUS_FUNDING_QUALITY_MODERATE: 3,
        SUSPICIOUS_FUNDING_QUALITY_WEAK: 2,
        "none": 1,
        SUSPICIOUS_FUNDING_QUALITY_UNKNOWN: 0,
    }
    qualities: list[str] = []
    reasons: list[str] = []
    eligible = _boolish(wallet.get("suspiciousFundingHardEvidenceEligible"))
    independent_support = _boolish(wallet.get("suspiciousFundingIndependentSupport"))
    support_sources: list[str] = _listish(wallet.get("suspiciousFundingIndependentSupportSources"))
    suppressor_conflict = _boolish(wallet.get("suspiciousFundingSuppressorConflict"))
    suppressor_reasons: list[str] = _listish(wallet.get("suspiciousFundingSuppressorConflictReasons"))

    def collect(row: dict[str, Any]) -> None:
        nonlocal eligible, independent_support, suppressor_conflict
        raw = row.get("rawMetrics") if isinstance(row.get("rawMetrics"), dict) else {}
        quality = str(
            row.get("suspiciousFundingQuality")
            or raw.get("suspiciousFundingQuality")
            or raw.get("suspicious_funding_quality")
            or ""
        ).strip()
        if quality:
            qualities.append(quality)
        reasons.extend(
            _listish(
                row.get("suspiciousFundingQualityReasons")
                or raw.get("suspiciousFundingQualityReasons")
                or raw.get("suspicious_funding_quality_reasons")
            )
        )
        eligible = eligible or _boolish(
            row.get("suspiciousFundingHardEvidenceEligible")
            or raw.get("suspiciousFundingHardEvidenceEligible")
            or raw.get("suspicious_funding_hard_evidence_eligible")
        )
        independent_support = independent_support or _boolish(
            row.get("suspiciousFundingIndependentSupport")
            or raw.get("suspiciousFundingIndependentSupport")
            or raw.get("suspicious_funding_independent_support")
        )
        support_sources.extend(
            _listish(
                row.get("suspiciousFundingIndependentSupportSources")
                or raw.get("suspiciousFundingIndependentSupportSources")
                or raw.get("suspicious_funding_independent_support_sources")
            )
        )
        suppressor_conflict = suppressor_conflict or _boolish(
            row.get("suspiciousFundingSuppressorConflict")
            or raw.get("suspiciousFundingSuppressorConflict")
            or raw.get("suspicious_funding_suppressor_conflict")
        )
        suppressor_reasons.extend(
            _listish(
                row.get("suspiciousFundingSuppressorConflictReasons")
                or raw.get("suspiciousFundingSuppressorConflictReasons")
                or raw.get("suspicious_funding_suppressor_conflict_reasons")
            )
        )

    collect(wallet)
    for trade in trades:
        collect(trade)

    best = ""
    for quality in qualities:
        if quality_rank.get(quality, -1) > quality_rank.get(best, -1):
            best = quality
    return (
        best or SUSPICIOUS_FUNDING_QUALITY_UNKNOWN,
        _dedupe(reasons),
        eligible,
        independent_support,
        _dedupe(support_sources),
        suppressor_conflict,
        _dedupe(suppressor_reasons),
    )


def _detail_values(details: list[str], key: str) -> list[str]:
    pattern = re.compile(rf"\b{re.escape(key)}=([^,;]+)")
    return _dedupe(
        match.group(1).strip()
        for detail in details
        for match in pattern.finditer(str(detail or ""))
        if match.group(1).strip()
    )


def _max_detail_number(details: list[str], key: str) -> float:
    values = [_number(value.rstrip("%")) for value in _detail_values(details, key)]
    return max(values, default=0.0)


def _min_positive_detail_number(details: list[str], key: str) -> float:
    values = [_number(value.rstrip("%")) for value in _detail_values(details, key)]
    positives = [value for value in values if value > 0]
    return min(positives, default=0.0)


def _trade_supporting_evidence(trade: dict[str, Any]) -> dict[str, Any]:
    flags = _string_list_text(trade.get("eventForensicFlags")).lower()
    summary = str(trade.get("summary") or "").lower()
    hard_sources = _listish(trade.get("hardEvidenceSources"))
    source_text = " ".join(hard_sources).lower()
    high_impact_present = _has_high_impact_source(hard_sources)
    high_impact_quality = (
        _normalize_high_impact_source_quality(trade.get("repricingSourceQuality"))
        if high_impact_present
        else ""
    )
    if high_impact_present and not high_impact_quality:
        high_impact_quality = HIGH_IMPACT_SOURCE_QUALITY_WEAK
    high_impact_quality_reasons = _listish(trade.get("repricingSourceQualityReasons")) if high_impact_quality else []
    raw = trade.get("rawMetrics") if isinstance(trade.get("rawMetrics"), dict) else {}
    suspicious_quality = str(
        trade.get("suspiciousFundingQuality")
        or raw.get("suspiciousFundingQuality")
        or raw.get("suspicious_funding_quality")
        or ""
    ).strip()
    suspicious_reasons = _listish(
        trade.get("suspiciousFundingQualityReasons")
        or raw.get("suspiciousFundingQualityReasons")
        or raw.get("suspicious_funding_quality_reasons")
    )
    return {
        "beat_consensus": "beat_consensus" in flags,
        "favorable_repricing": "post_entry_repricing" in flags or "repricing" in summary or "repricing" in source_text,
        "low_probability_winner": "low_probability_winner" in flags or "low-probability" in source_text,
        "dormant_reactivation": "dormant_reactivation" in flags or "dormant" in source_text,
        "split_wallet": "split_wallet" in flags or "split-wallet" in source_text,
        "shared_funding": "shared_funder" in flags or "shared funding" in source_text,
        "suspicious_funding": "recent_opaque_funding" in flags or ("funding" in source_text and "shared" not in source_text),
        "same_side_cluster": "same_side_cluster" in flags,
        "independent_hard_evidence": bool(hard_sources),
        "hard_evidence_sources": hard_sources,
        "evidence_source_flags": _listish(trade.get("eventForensicFlags")),
        "hard_evidence_source_details": [],
        "high_impact_source_quality": high_impact_quality,
        "high_impact_source_quality_reasons": high_impact_quality_reasons,
        "suspicious_funding_quality": suspicious_quality or SUSPICIOUS_FUNDING_QUALITY_UNKNOWN,
        "suspicious_funding_quality_reasons": suspicious_reasons,
        "suspicious_funding_hard_evidence_eligible": _boolish(
            trade.get("suspiciousFundingHardEvidenceEligible")
            or raw.get("suspiciousFundingHardEvidenceEligible")
            or raw.get("suspicious_funding_hard_evidence_eligible")
        ),
        "suspicious_funding_independent_support": _boolish(
            trade.get("suspiciousFundingIndependentSupport")
            or raw.get("suspiciousFundingIndependentSupport")
            or raw.get("suspicious_funding_independent_support")
        ),
        "suspicious_funding_independent_support_sources": _listish(
            trade.get("suspiciousFundingIndependentSupportSources")
            or raw.get("suspiciousFundingIndependentSupportSources")
            or raw.get("suspicious_funding_independent_support_sources")
        ),
        "suspicious_funding_suppressor_conflict": _boolish(
            trade.get("suspiciousFundingSuppressorConflict")
            or raw.get("suspiciousFundingSuppressorConflict")
            or raw.get("suspicious_funding_suppressor_conflict")
        ),
        "suspicious_funding_suppressor_conflict_reasons": _listish(
            trade.get("suspiciousFundingSuppressorConflictReasons")
            or raw.get("suspiciousFundingSuppressorConflictReasons")
            or raw.get("suspicious_funding_suppressor_conflict_reasons")
        ),
    }


def _reducers(wallet: dict[str, Any], trades: list[dict[str, Any]]) -> dict[str, bool]:
    reducer_text = " ".join(
        _string_list_text(trade.get("eventForensicReducers"))
        for trade in trades
    ).lower()
    event_trade_count = _int(wallet.get("eventTradeCount") or wallet.get("walletLoadedEventTradeCount"))
    winning_count = _winning_count(wallet)
    opening_count = _int(wallet.get("openingEntryCount") or wallet.get("walletOpeningEntryCount"))
    return {
        "high_volume_public_user": _boolish(wallet.get("walletPublicPowerUserFlag"))
        or _boolish(wallet.get("walletHighVolumeEventUserFlag"))
        or event_trade_count >= 25,
        "event_saturation": _boolish(wallet.get("walletEventSaturationFlag"))
        or (event_trade_count >= 30 and opening_count >= 20 and winning_count >= 15),
        "bot_like": str(wallet.get("botStatus") or "").startswith("Bot"),
        "specialist": str(wallet.get("specialistStatus") or "").startswith("Specialist"),
        "weak_economic_history": str(wallet.get("walletQualityStatus") or "").startswith("Weak"),
        "near_certainty": "near certainty" in reducer_text,
        "yield_farm": "yield-farm" in reducer_text or "yield farm" in reducer_text or "capital parking" in reducer_text,
        "theta_decay": "theta-decay" in reducer_text or "theta decay" in reducer_text or "deadline-decay" in reducer_text,
        "resolution_gap": _looks_like_resolution_gap_reducer(reducer_text),
    }


def _trade_reducers(trade: dict[str, Any]) -> dict[str, bool]:
    reducer_text = _string_list_text(trade.get("eventForensicReducers")).lower()
    return {
        "high_volume_public_user": False,
        "event_saturation": False,
        "bot_like": False,
        "specialist": False,
        "weak_economic_history": "weak" in reducer_text and "history" in reducer_text,
        "near_certainty": "near certainty" in reducer_text,
        "yield_farm": "yield-farm" in reducer_text or "yield farm" in reducer_text or "capital parking" in reducer_text,
        "theta_decay": "theta-decay" in reducer_text or "theta decay" in reducer_text or "deadline-decay" in reducer_text,
        "resolution_gap": _looks_like_resolution_gap_reducer(reducer_text),
    }


def _looks_like_resolution_gap_reducer(reducer_text: str) -> bool:
    return any(
        phrase in reducer_text
        for phrase in (
            "resolution gap",
            "public-news lag",
            "stale market pricing",
            "public information",
            "market absorbed slowly",
        )
    )


def _wallet_event_activity(wallet: dict[str, Any], relevant_trades: list[dict[str, Any]]) -> dict[str, int]:
    event_trade_count = _int(wallet.get("eventTradeCount") or wallet.get("walletLoadedEventTradeCount"))
    if event_trade_count <= 0:
        event_trade_count = len(relevant_trades)
    notable_count = _int(wallet.get("suspiciousTradeCount") or wallet.get("walletNotableTradeCount"))
    if notable_count <= 0:
        notable_count = sum(1 for trade in relevant_trades if _int(trade.get("eventForensicScore")) >= 40) or len(relevant_trades)
    opening_count = _int(wallet.get("openingEntryCount") or wallet.get("walletOpeningEntryCount"))
    if opening_count <= 0:
        opening_count = sum(1 for trade in relevant_trades if _boolish(trade.get("openingExposure")))
    winning_count = _winning_count(wallet)
    if winning_count <= 0:
        winning_count = sum(
            1
            for trade in relevant_trades
            if _boolish(trade.get("openingExposure")) and _boolish(trade.get("laterWon"))
        )
    unique_markets = _int(wallet.get("walletUniqueEventMarketsTraded"))
    if unique_markets <= 0:
        unique_markets = len({str(trade.get("market") or trade.get("conditionId") or "") for trade in relevant_trades if trade})
    return {
        "event_trade_count": event_trade_count,
        "notable_trade_count": notable_count,
        "opening_entry_count": opening_count,
        "winning_opening_entry_count": winning_count,
        "unique_event_markets_traded": unique_markets,
        "related_market_trade_count": _int(wallet.get("relatedMarketTradeCount")),
    }


def _compact_trade(trade: dict[str, Any]) -> dict[str, Any]:
    hard_sources = _hard_evidence_sources_from_trade_row(trade)
    raw = trade.get("rawMetrics") if isinstance(trade.get("rawMetrics"), dict) else {}
    return {
        "id": trade.get("id") or trade.get("tradeId") or trade.get("trade_id") or "",
        "wallet": trade.get("wallet") or "",
        "username": trade.get("username") or _raw_trade_username(trade),
        "conditionId": trade.get("conditionId") or trade.get("condition_id") or "",
        "timestamp": trade.get("timestamp") or "",
        "market": trade.get("market") or trade.get("title") or "",
        "side": trade.get("side") or "",
        "orderSide": trade.get("orderSide") or "",
        "price": _nullable_number(trade.get("price")),
        "positionSize": _nullable_number(trade.get("positionSize") or trade.get("size")),
        "laterWon": _nullable_bool(trade.get("laterWon")),
        "openingExposure": _nullable_bool(trade.get("openingExposure")),
        "eventForensicScore": _nullable_int(trade.get("eventForensicScore")),
        "existingModelScore": _nullable_int(trade.get("existingModelScore")),
        "relatedMarketTrades": _nullable_int(trade.get("relatedMarketTrades")),
        "eventForensicFlags": _listish(trade.get("eventForensicFlags")),
        "eventForensicReducers": _listish(trade.get("eventForensicReducers")),
        "eventForensicNotes": _listish(trade.get("eventForensicNotes")),
        "winnerRank": _nullable_int(trade.get("winnerRank")),
        "fundingEvidenceGrade": trade.get("fundingEvidenceGrade") or raw.get("funding_evidence_grade") or "",
        "suspiciousFundingQuality": (
            trade.get("suspiciousFundingQuality")
            or raw.get("suspiciousFundingQuality")
            or raw.get("suspicious_funding_quality")
            or ""
        ),
        "suspiciousFundingQualityReasons": (
            trade.get("suspiciousFundingQualityReasons")
            or raw.get("suspiciousFundingQualityReasons")
            or raw.get("suspicious_funding_quality_reasons")
            or ""
        ),
        "suspiciousFundingHardEvidenceEligible": (
            trade.get("suspiciousFundingHardEvidenceEligible")
            or raw.get("suspiciousFundingHardEvidenceEligible")
            or raw.get("suspicious_funding_hard_evidence_eligible")
            or ""
        ),
        "suspiciousFundingIndependentSupport": (
            trade.get("suspiciousFundingIndependentSupport")
            or raw.get("suspiciousFundingIndependentSupport")
            or raw.get("suspicious_funding_independent_support")
            or ""
        ),
        "suspiciousFundingIndependentSupportSources": (
            trade.get("suspiciousFundingIndependentSupportSources")
            or raw.get("suspiciousFundingIndependentSupportSources")
            or raw.get("suspicious_funding_independent_support_sources")
            or ""
        ),
        "suspiciousFundingSuppressorConflict": (
            trade.get("suspiciousFundingSuppressorConflict")
            or raw.get("suspiciousFundingSuppressorConflict")
            or raw.get("suspicious_funding_suppressor_conflict")
            or ""
        ),
        "suspiciousFundingSuppressorConflictReasons": (
            trade.get("suspiciousFundingSuppressorConflictReasons")
            or raw.get("suspiciousFundingSuppressorConflictReasons")
            or raw.get("suspicious_funding_suppressor_conflict_reasons")
            or ""
        ),
        "repricingSourceQuality": (
            trade.get("repricingSourceQuality")
            or raw.get("repricing_source_quality")
            or raw.get("repricingSourceQuality")
            or ""
        ),
        "repricingSourceQualityReasons": (
            trade.get("repricingSourceQualityReasons")
            or raw.get("repricing_source_quality_reasons")
            or raw.get("repricingSourceQualityReasons")
            or ""
        ),
        "hardEvidenceSources": hard_sources,
        "summary": trade.get("summary") or "",
    }


def _raw_trade_username(trade: dict[str, Any]) -> str:
    name = str(trade.get("trader_name") or "").strip()
    pseudonym = str(trade.get("trader_pseudonym") or "").strip()
    if name and pseudonym:
        return f"{name} ({pseudonym})"
    return name or pseudonym


def _raw_has_proxy_funding_grade(raw: dict[str, Any]) -> bool:
    grade = str(raw.get("funding_evidence_grade") or raw.get("fundingEvidenceGrade") or "").strip()
    if grade in PROXY_FUNDING_EVIDENCE_GRADES:
        return True
    return bool(raw.get("cex_proxy_cluster_flag") == "Yes" and not str(raw.get("funding_graph_key_strict") or "").strip())


def _hard_evidence_sources_from_trade_row(trade: dict[str, Any]) -> list[str]:
    saved_sources = _listish(trade.get("hardEvidenceSources"))
    if saved_sources:
        return _dedupe(saved_sources)
    flags = _string_list_text(trade.get("eventForensicFlags")).lower()
    summary = str(trade.get("summary") or "").lower()
    raw = trade.get("rawMetrics") if isinstance(trade.get("rawMetrics"), dict) else {}
    saved_raw_sources = _listish(raw.get("hardEvidenceSources"))
    if saved_raw_sources:
        return _dedupe(saved_raw_sources)
    sources: list[str] = []
    if "split_wallet" in flags or raw.get("split_wallet_pattern_flag") == "Yes":
        sources.append("split-wallet pattern")
    if "shared_funder" in flags or (
        raw.get("shared_funding_source_flag") == "Yes"
        and _int(raw.get("shared_funding_source_cluster_size")) >= 3
    ):
        sources.append("shared funding cluster")
    if (
        "recent_opaque_funding" in flags
        or raw.get("suspicious_funding_flag") == "Yes"
        or raw.get("recent_external_funding_flag") == "Yes"
    ) and not _raw_has_proxy_funding_grade(raw) and _boolish(raw.get("suspiciousFundingHardEvidenceEligible")):
        sources.append("suspicious or recent funding")
    if "low_probability_winner" in flags or _is_low_probability_winner(trade):
        sources.append("low-probability winning entry")
    if "dormant_reactivation" in flags or _hard_dormant_reactivation(raw, summary):
        sources.append("dormant wallet reactivation")
    if raw.get("coordinated_cluster_signal") == "Yes" and (
        raw.get("reactivated_after_dormancy_flag") == "Yes"
        or raw.get("wallet_recently_activated") == "Yes"
    ):
        sources.append("coordinated new/reactivated wallet cluster")
    if _hard_timing_repricing(raw):
        sources.append("high-impact timing/repricing edge")
    if raw.get("wallet_recently_activated") == "Yes" and (
        raw.get("wallet_size_anomaly") == "Yes" or _number(raw.get("liquidity_ratio")) >= 10.0
    ):
        sources.append("newly activated wallet with large/illiquid entry")
    return _dedupe(sources)


def _is_low_probability_winner(trade: dict[str, Any]) -> bool:
    price = _nullable_number(trade.get("price"))
    winner_rank = _nullable_int(trade.get("winnerRank"))
    return bool(price is not None and price <= 0.35 and winner_rank is not None and winner_rank <= 6)


def _hard_dormant_reactivation(raw: dict[str, Any], summary: str) -> bool:
    if raw.get("reactivated_after_dormancy_flag") != "Yes" and "reactivated" not in summary:
        return False
    gap = _number(raw.get("days_since_prior_wallet_trade"))
    return gap >= 90 or "long quiet" in summary


def _hard_timing_repricing(raw: dict[str, Any]) -> bool:
    if raw.get("beat_consensus_flag") != "Yes" and raw.get("favorable_repricing_flag") != "Yes":
        return False
    liquidity = _nullable_number(raw.get("market_liquidity_usdc"))
    liquidity_ratio = _number(raw.get("liquidity_ratio"))
    return (liquidity is not None and 0 < liquidity <= 100000) or liquidity_ratio >= 5.0


def _render_review_report(payload: dict[str, Any]) -> str:
    reviews = payload["reviews"]
    summary = payload["summary"]
    lines = [
        "# InsPoly AI Case Review",
        "",
        f"- Source event analysis: `{payload['source_event_analysis_json_path']}`",
        f"- Detected input directory: `{payload['detected_input_dir']}`",
        f"- Event: {payload['event']['title']} ({payload['event']['slug'] or 'no slug'})",
        f"- Cases reviewed: {summary['cases_reviewed']}",
        f"- Wallet cases: {summary['wallet_cases_reviewed']}",
        f"- Trade cases: {summary['trade_cases_reviewed']}",
        f"- Cluster cases: {summary['cluster_cases_reviewed']}",
        f"- Likely false positives: {summary['likely_false_positive_count']}",
        f"- Plausible insider-style cases: {summary['plausible_insider_style_count']}",
        f"- Ambiguous cases: {summary['ambiguous_count']}",
        "- Safety: deterministic local review only; no production code or scoring rules were modified.",
        "",
        "## Findings",
        "",
    ]
    if not reviews:
        lines.append("No case packets were produced because the saved input appears genuinely empty.")
        return "\n".join(lines)
    for review in reviews:
        lines.extend(
            [
                f"### {review['case_id']}",
                "",
                f"- Verdict: `{review['review_verdict']}`",
                f"- Interpretation: `{review['interpretation_class']}`",
                f"- Confidence: {review['confidence']}",
                f"- Main reason: {review['main_reason']}",
                f"- Weakening evidence: {'; '.join(review['evidence_that_weakens_concern']) or 'None recorded'}",
                f"- Supporting evidence: {'; '.join(review['evidence_that_supports_concern']) or 'None recorded'}",
                "",
            ]
        )
    return "\n".join(lines)


def _render_model_changes_report(payload: dict[str, Any]) -> str:
    reviews = payload["reviews"]
    packets_by_case = {
        str(packet.get("case_id") or ""): packet
        for packet in payload.get("case_packets") or []
        if isinstance(packet, dict)
    }
    false_positive_reviews = [
        review for review in reviews if review.get("review_verdict") == "likely_false_positive"
    ]
    lines = [
        "# InsPoly AI Case Review Model Notes",
        "",
        "This scaffold does not edit production code, does not change thresholds, and does not apply automatic scoring changes.",
        "",
        "## Observed False Positives",
        "",
    ]
    if not false_positive_reviews:
        lines.append("- None from deterministic review.")
    for review in false_positive_reviews:
        packet = packets_by_case.get(str(review.get("case_id") or ""), {})
        activity = packet.get("event_activity") if isinstance(packet.get("event_activity"), dict) else {}
        scores = packet.get("scores") if isinstance(packet.get("scores"), dict) else {}
        evidence = packet.get("supporting_evidence") if isinstance(packet.get("supporting_evidence"), dict) else {}
        reducers = packet.get("reducers") if isinstance(packet.get("reducers"), dict) else {}
        high_volume_flags = [
            name
            for name in ("high_volume_public_user", "event_saturation")
            if reducers.get(name)
        ]
        lines.extend(
            [
                f"### {packet.get('username') or 'unknown user'}",
                "",
                f"- Wallet: `{packet.get('wallet') or ''}`",
                f"- walletScore: {_int(scores.get('wallet_score'))}",
                f"- insiderStyleWalletScore: {_int(scores.get('insider_style_wallet_score'))}",
                f"- event_trade_count: {_int(activity.get('event_trade_count'))}",
                f"- notable_trade_count: {_int(activity.get('notable_trade_count'))}",
                f"- winning_opening_entry_count: {_int(activity.get('winning_opening_entry_count'))}",
                f"- High-volume flags: {', '.join(high_volume_flags) or 'none'}",
                f"- independentHardEvidenceFlag: {_boolish(evidence.get('independent_hard_evidence'))}",
                "- Why current ranking was misleading: repeated event activity and repeated wins were enough to look important, but the packet lacks independent hard evidence.",
                "- Proposed deterministic fix if needed: keep high-volume/public-power-user caps active unless independent hard evidence is exported for the wallet.",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## Current Rules That Can Cause Bad Ranking",
            "",
            "- High event trade count and repeated resolved wins can still be present in saved context rows.",
            "- Reviewer should require independent evidence before treating high-volume correctness as insider-style concern.",
            "",
            "## Recommended Deterministic Checks",
            "",
            "- Keep `walletPublicPowerUserFlag`, `walletHighVolumeEventUserFlag`, and `walletEventSaturationFlag` in wallet exports.",
            "- Keep `independentHardEvidenceFlag` as the escape hatch for split-wallet, shared-funding, opaque-funding, low-probability, or dormancy evidence.",
            "- Preserve tests where high-volume/event-saturation wallets remain in context exports but not primary high-concern rows.",
            "",
            "## Risk",
            "",
            "- Over-demotion can hide public high-volume wallets that also have real linkage; keep hard-evidence escape hatches tested.",
        ]
    )
    return "\n".join(lines)


def _recommended_model_changes(verdict: str, interpretation: str) -> list[str]:
    if verdict == "likely_false_positive" and interpretation == "high_volume_public_power_user":
        return ["Keep this class capped/demoted unless independent hard evidence appears."]
    if verdict == "ambiguous" and interpretation == "bot_or_low_analyst_value":
        return ["Keep bot/specialist handling advisory unless this pattern repeats across unrelated outputs."]
    if verdict == "ambiguous" and interpretation == "stale_or_resolution_gap":
        return ["Keep near-certainty, yield-farm, theta-decay, and stale-resolution handling advisory unless the pattern repeats across unrelated outputs."]
    if verdict == "plausible_insider_style":
        return ["Do not suppress this class solely for high volume; preserve the hard-evidence escape hatch."]
    return ["No automatic model change; inspect more saved context first."]


def _recommended_tests(verdict: str, interpretation: str) -> list[str]:
    if interpretation == "high_volume_public_power_user":
        return ["High-volume wallet with many winning entries remains context-only without hard evidence."]
    if interpretation == "bot_or_low_analyst_value":
        return ["Bot-like or specialist wallet without hard evidence remains advisory/ambiguous, not a scoring change."]
    if interpretation == "stale_or_resolution_gap":
        return ["Near-certainty, yield-farm, theta-decay, or stale-resolution packet without hard evidence remains advisory/ambiguous."]
    if interpretation == "cluster_or_linkage_case":
        return ["High-volume wallet with split-wallet/shared-funding evidence remains primary-review eligible."]
    return ["Ambiguous case packet keeps reviewer output non-mutating."]


def _missing_data(packet: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    profile = packet.get("profile_summary") if isinstance(packet.get("profile_summary"), dict) else {}
    if packet.get("case_type") == "wallet" and profile.get("total_predictions") is None:
        missing.append("Polymarket total prediction count")
    if packet.get("case_type") in {"wallet", "trade"} and not packet.get("relevant_trades"):
        missing.append("Saved relevant trade rows")
    return missing


def _review_summary(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cases_reviewed": len(reviews),
        "wallet_cases_reviewed": sum(1 for item in reviews if str(item.get("case_id", "")).startswith("wallet-")),
        "trade_cases_reviewed": sum(1 for item in reviews if str(item.get("case_id", "")).startswith("trade-")),
        "cluster_cases_reviewed": sum(1 for item in reviews if str(item.get("case_id", "")).startswith("cluster-")),
        "likely_false_positive_count": sum(1 for item in reviews if item["review_verdict"] == "likely_false_positive"),
        "plausible_insider_style_count": sum(1 for item in reviews if item["review_verdict"] == "plausible_insider_style"),
        "ambiguous_count": sum(1 for item in reviews if item["review_verdict"] == "ambiguous"),
    }


def _top_suggested_fixes(reviews: list[dict[str, Any]], limit: int = 5) -> list[str]:
    seen: set[str] = set()
    fixes: list[str] = []
    for review in reviews:
        for item in review.get("recommended_model_change") or []:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            fixes.append(text)
            if len(fixes) >= limit:
                return fixes
    return fixes


def _review_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")


def _reserve_review_output_paths(output_dir: Path, timestamp: str) -> tuple[str, Path, Path, Path]:
    attempt = 0
    while True:
        suffix = timestamp if attempt == 0 else f"{timestamp}_{attempt + 1}"
        cases_path = output_dir / f"AI_CASE_REVIEW_CASES_{suffix}.json"
        report_path = output_dir / f"AI_CASE_REVIEW_REPORT_{suffix}.md"
        model_changes_path = output_dir / f"AI_CASE_REVIEW_MODEL_CHANGES_{suffix}.md"
        if not (cases_path.exists() or report_path.exists() or model_changes_path.exists()):
            return suffix, cases_path, report_path, model_changes_path
        attempt += 1


def _wallet_graph_summary(wallet_graph: dict[str, Any]) -> dict[str, int]:
    nodes = wallet_graph.get("nodes") if isinstance(wallet_graph, dict) else []
    edges = wallet_graph.get("edges") if isinstance(wallet_graph, dict) else []
    return {
        "node_count": len(nodes) if isinstance(nodes, list) else 0,
        "edge_count": len(edges) if isinstance(edges, list) else 0,
    }


def _event_identity(event_analysis: dict[str, Any]) -> dict[str, str]:
    event = event_analysis.get("event") if isinstance(event_analysis.get("event"), dict) else {}
    return {
        "title": str(event.get("title") or event.get("slug") or "Unknown event"),
        "slug": str(event.get("slug") or ""),
    }


def _validate_case_sources(
    *,
    event_analysis: dict[str, Any],
    trade_rows: list[dict[str, Any]],
    wallet_rows: list[dict[str, Any]],
    cluster_rows: list[dict[str, Any]],
    suspicious_trades_csv_path: Path | None,
    suspicious_wallets_csv_path: Path | None,
    wallet_context_csv_path: Path | None,
) -> None:
    if wallet_context_csv_path is None and suspicious_wallets_csv_path is None and not (
        event_analysis.get("display_wallets") or event_analysis.get("suspicious_wallets")
    ):
        if not _input_is_genuinely_empty(event_analysis):
            raise ReviewInputError("Missing wallet CSVs and no wallet rows are embedded in event_analysis.json.")
    if suspicious_trades_csv_path is None and not (
        event_analysis.get("display_trades") or event_analysis.get("suspicious_trades")
    ):
        if not _input_is_genuinely_empty(event_analysis):
            raise ReviewInputError("Missing suspicious_trades.csv and no trade rows are embedded in event_analysis.json.")
    if not (wallet_rows or trade_rows or cluster_rows) and not _input_is_genuinely_empty(event_analysis):
        raise ReviewInputError("No case rows found in CSVs or event_analysis.json.")


def _input_is_genuinely_empty(event_analysis: dict[str, Any]) -> bool:
    summary = event_analysis.get("summary") if isinstance(event_analysis.get("summary"), dict) else {}
    count_keys = {"candidate_trade_count", "raw_trade_count", "forensic_suspicious_trade_count"}
    if not any(key in summary for key in count_keys):
        return False
    return (
        _int(summary.get("candidate_trade_count")) == 0
        and _int(summary.get("raw_trade_count")) == 0
        and _int(summary.get("forensic_suspicious_trade_count")) == 0
    )


def _validate_existing_file(path: Path, *, label: str) -> Path:
    path = Path(path)
    _reject_placeholder(path, label=label)
    if not path.exists():
        raise ReviewInputError(f"{label} does not exist: {path}")
    if not path.is_file():
        raise ReviewInputError(f"{label} is not a file: {path}")
    return path


def _optional_path(path: Path | None, *, must_be_file: bool = True) -> Path | None:
    if path is None:
        return None
    path = Path(path)
    _reject_placeholder(path, label="optional input path")
    if not path.exists():
        return None
    if must_be_file and not path.is_file():
        raise ReviewInputError(f"Expected file path but got directory: {path}")
    if not must_be_file and not path.is_dir():
        raise ReviewInputError(f"Expected directory path but got file: {path}")
    return path


def _reject_placeholder(path: Path, *, label: str) -> None:
    text = str(path)
    if any(part in text for part in PLACEHOLDER_PATH_PARTS):
        raise ReviewInputError(f"{label} looks like a placeholder path: {path}")


def _read_json_strict(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReviewInputError(f"Invalid JSON in {path}: {exc}") from exc
    except OSError as exc:
        raise ReviewInputError(f"Could not read {path}: {exc}") from exc


def _read_csv_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise ReviewInputError(f"Could not read {path}: {exc}") from exc


def _read_raw_trade_rows(raw_event_bundle_dir: Path | None) -> list[dict[str, Any]]:
    if raw_event_bundle_dir is None:
        return []
    source_rows = _read_raw_bundle_rows(raw_event_bundle_dir / "source_trades.json")
    trade_rows = _read_raw_bundle_rows(raw_event_bundle_dir / "trades.json")
    if not source_rows:
        return trade_rows
    source_ids = {_trade_id(row).lower() for row in source_rows if _trade_id(row)}
    fallback_rows = [
        row
        for row in trade_rows
        if not _trade_id(row) or _trade_id(row).lower() not in source_ids
    ]
    return source_rows + fallback_rows


def _read_raw_bundle_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = _read_json_or_list_strict(path)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    rows = (payload.get("source_trades") or payload.get("trades")) if isinstance(payload, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _read_json_or_list_strict(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReviewInputError(f"Invalid JSON in {path}: {exc}") from exc
    except OSError as exc:
        raise ReviewInputError(f"Could not read {path}: {exc}") from exc


def _merge_rich_rows(
    base_rows: list[dict[str, Any]],
    rich_rows: list[dict[str, Any]],
    *,
    key_fn,
) -> list[dict[str, Any]]:
    rich_by_key = {key_fn(row): row for row in rich_rows if key_fn(row)}
    merged_rows: list[dict[str, Any]] = []
    for row in base_rows:
        key = key_fn(row)
        rich = rich_by_key.get(key)
        if not rich:
            merged_rows.append(row)
            continue
        merged = dict(row)
        for rich_key, rich_value in rich.items():
            if rich_key not in merged or _empty_value(merged.get(rich_key)):
                merged[rich_key] = rich_value
        merged_rows.append(merged)
    return merged_rows


def _merge_wallet_rows(
    *,
    suspicious_wallet_rows: list[dict[str, Any]],
    wallet_context_rows: list[dict[str, Any]],
    embedded_wallet_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged_by_wallet: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def merge_row(row: dict[str, Any]) -> None:
        wallet = str(row.get("wallet") or "").strip()
        if not wallet:
            return
        if wallet not in merged_by_wallet:
            merged_by_wallet[wallet] = dict(row)
            order.append(wallet)
            return
        current = merged_by_wallet[wallet]
        for key, value in row.items():
            if _empty_value(value):
                continue
            if key in WALLET_COUNT_MERGE_KEYS and _int(current.get(key)) <= 0 < _int(value):
                current[key] = value
            elif key not in current or _empty_value(current.get(key)):
                current[key] = value

    for source_rows in (suspicious_wallet_rows, wallet_context_rows, embedded_wallet_rows):
        for row in source_rows:
            merge_row(row)
    return [merged_by_wallet[wallet] for wallet in order]


def _trade_merge_key(row: dict[str, Any]) -> str:
    composite = "|".join(
        str(row.get(key) or "").strip()
        for key in ("wallet", "timestamp", "conditionId", "market", "positionSize")
    )
    if composite.replace("|", ""):
        return composite
    trade_id = str(row.get("id") or row.get("tradeId") or row.get("trade_id") or "").strip()
    if trade_id:
        return f"id:{trade_id}"
    return ""


def _empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict)):
        return not value
    return str(value).strip() == ""


def _path_from_export(export_files: dict[str, Any], key: str) -> Path | None:
    value = export_files.get(key)
    return Path(str(value)) if value else None


def _winning_count(wallet: dict[str, Any]) -> int:
    value = _int(wallet.get("walletWinningOpeningEntryCount"))
    if value:
        return value
    text = str(wallet.get("eventResult") or "")
    match = re.search(r"(\d+)\s+winning opening", text, flags=re.IGNORECASE)
    if match:
        return _int(match.group(1))
    return 0


def _nullable_int(value: Any) -> int | None:
    parsed = _int(value)
    return parsed if parsed else None


def _nullable_number(value: Any) -> float | None:
    try:
        text = str(value or "").replace(",", "").strip()
        return float(text) if text else None
    except ValueError:
        return None


def _nullable_bool(value: Any) -> bool | None:
    text = str(value).strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def _int(value: Any) -> int:
    try:
        text = str(value or "").replace(",", "").strip()
        if text.endswith("%"):
            text = text[:-1]
        return int(float(text)) if text else 0
    except ValueError:
        return 0


def _number(value: Any) -> float:
    try:
        return float(str(value or "").replace(",", "").strip())
    except ValueError:
        return 0.0


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _listish(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    text = str(value or "").strip()
    if not text:
        return []
    if ";" in text:
        return [part.strip() for part in text.split(";") if part.strip()]
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _string_list_text(value: Any) -> str:
    return " ".join(_listish(value))


def _short_id(value: str) -> str:
    if len(value) <= 10:
        return value or "unknown"
    return f"{value[:6]}{value[-4:]}"


def _print_cli_summary(outputs: dict[str, Any]) -> None:
    print(f"Detected input directory: {outputs.get('detected_input_dir', '')}")
    print(f"Event: {outputs.get('event_title', 'Unknown')} ({outputs.get('event_slug', '') or 'no slug'})")
    print(f"Wallet cases reviewed: {outputs.get('wallet_cases_reviewed', 0)}")
    print(f"Trade cases reviewed: {outputs.get('trade_cases_reviewed', 0)}")
    print(f"Cluster cases reviewed: {outputs.get('cluster_cases_reviewed', 0)}")
    print(f"Likely false positives: {outputs.get('likely_false_positive_count', 0)}")
    print(f"Plausible insider-style cases: {outputs.get('plausible_insider_style_count', 0)}")
    print(f"Ambiguous cases: {outputs.get('ambiguous_count', 0)}")
    print(f"Case packets JSON: {outputs.get('cases_json_path', '')}")
    print(f"Review report: {outputs.get('review_report_md_path', '')}")
    print(f"Model changes: {outputs.get('model_changes_md_path', '')}")
    llm = outputs.get("llm") if isinstance(outputs.get("llm"), dict) else {}
    if llm.get("enabled"):
        print(llm.get("reason") or f"LLM status: {llm.get('status', '')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Review saved InsPoly event-forensic outputs without editing code.")
    parser.add_argument("--latest", action="store_true", help="Use newest valid event_forensic_outputs/event_forensic_* directory")
    parser.add_argument("--event-analysis", type=Path, help="Path to event_analysis.json")
    parser.add_argument("--event-forensic-outputs-dir", type=Path, default=DEFAULT_EVENT_FORENSIC_OUTPUTS_DIR)
    parser.add_argument("--suspicious-trades", type=Path, default=None)
    parser.add_argument("--suspicious-wallets", type=Path, default=None)
    parser.add_argument("--wallet-context", type=Path, default=None)
    parser.add_argument("--wallet-clusters", type=Path, default=None)
    parser.add_argument("--wallet-graph", type=Path, default=None)
    parser.add_argument("--model-gap-report", type=Path, default=None)
    parser.add_argument("--raw-event-bundle-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--use-llm", action="store_true", help="Run optional advisory LLM reviewer after deterministic review")
    args = parser.parse_args()

    try:
        if args.latest:
            outputs = review_latest_outputs(
                event_forensic_outputs_dir=args.event_forensic_outputs_dir,
                output_dir=args.output_dir,
                top_n=args.top_n,
                use_llm=args.use_llm,
            )
        elif args.event_analysis:
            outputs = review_event_outputs(
                event_analysis_json_path=args.event_analysis,
                suspicious_trades_csv_path=args.suspicious_trades,
                suspicious_wallets_csv_path=args.suspicious_wallets,
                wallet_context_csv_path=args.wallet_context,
                wallet_clusters_csv_path=args.wallet_clusters,
                wallet_graph_json_path=args.wallet_graph,
                model_gap_report_md_path=args.model_gap_report,
                raw_event_bundle_dir=args.raw_event_bundle_dir,
                output_dir=args.output_dir,
                top_n=args.top_n,
                use_llm=args.use_llm,
            )
        else:
            raise ReviewInputError("Pass --latest or --event-analysis.")
    except ReviewInputError as exc:
        print(f"Case Reviewer error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    _print_cli_summary(outputs)


if __name__ == "__main__":
    main()
