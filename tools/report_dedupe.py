from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Sequence


LOW_CONFIDENCE_KEY_SOURCES = {"wallet_condition_timebucket_notional", "insufficient_metadata"}


def _lookup_sources(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = [record]
    for key in ("_raw_record", "rawMetrics", "raw_metrics", "supportingEvidence", "supporting_evidence"):
        value = record.get(key)
        if isinstance(value, Mapping):
            sources.append(value)
    return sources


def _value(record: Mapping[str, Any], *keys: str) -> str:
    for source in _lookup_sources(record):
        for key in keys:
            value = source.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
    return ""


def _timestamp_bucket(value: str) -> str:
    text = str(value or "").strip()
    return text[:16] if len(text) >= 16 else text


def dedupe_key(record: Mapping[str, Any]) -> tuple[str, str]:
    wallet = _value(record, "wallet", "walletAddress", "wallet_address", "username")
    condition_id = _value(record, "condition_id", "conditionId")
    trade_id = _value(record, "trade_id", "tradeId", "id", "row_id")
    if trade_id and trade_id != "unknown" and wallet and condition_id:
        return f"trade:{trade_id}|wallet:{wallet}|condition:{condition_id}", "trade_wallet_condition"

    tx_hash = _value(record, "transactionHash", "transaction_hash", "txHash", "tx_hash")
    if tx_hash and wallet and condition_id:
        return f"tx:{tx_hash}|wallet:{wallet}|condition:{condition_id}", "tx_wallet_condition"

    timestamp = _value(record, "timestamp", "tradeTimestamp", "trade_timestamp", "createdAt", "created_at", "time")
    side = _value(record, "side", "tradeSide", "trade_side")
    outcome = _value(record, "outcome", "outcomeName", "outcome_name")
    price = _value(record, "price", "tradePrice", "trade_price", "outcomePrice", "outcome_price")
    size = _value(record, "size", "tradeSize", "trade_size")
    if wallet and condition_id and timestamp and side and outcome and price and size:
        return (
            f"wallet:{wallet}|condition:{condition_id}|timestamp:{timestamp}|side:{side}|outcome:{outcome}|price:{price}|size:{size}",
            "full_trade_fingerprint",
        )

    notional = _value(
        record,
        "notional",
        "notionalUsd",
        "notional_usd",
        "amountUsd",
        "amount_usd",
        "tradeNotionalUsd",
        "trade_notional_usd",
    )
    if not any([wallet, condition_id, timestamp, notional]):
        source = _value(record, "source_path", "_audit_source_path") or "unknown"
        row_id = _value(record, "row_id", "source_row", "_audit_source_row", "id", "trade_id", "tradeId") or str(id(record))
        return f"insufficient:{source}|row:{row_id}", "insufficient_metadata"
    return (
        f"wallet:{wallet or 'unknown'}|condition:{condition_id or 'unknown'}|"
        f"timestampBucket:{_timestamp_bucket(timestamp)}|notional:{notional or 'unknown'}",
        "wallet_condition_timebucket_notional",
    )


def target_label(record: Mapping[str, Any]) -> str:
    explicit = _value(record, "target_label", "validationTargetLabel")
    if explicit:
        return explicit
    source = _value(record, "source_path", "_audit_source_path")
    return Path(source).parent.name if source else "unknown"


def annotate_dedupe(records: Iterable[MutableMapping[str, Any]]) -> list[MutableMapping[str, Any]]:
    rows = list(records)
    keys: list[tuple[str, str]] = []
    counts: Counter[str] = Counter()
    for record in rows:
        key = str(record.get("dedupeKey") or record.get("dedupe_key") or "")
        source = str(record.get("dedupeKeySource") or record.get("dedupe_key_source") or "")
        if not key:
            key, source = dedupe_key(record)
        keys.append((key, source))
        counts[key] += 1
    for record, (key, source) in zip(rows, keys, strict=False):
        group_size = counts[key]
        record["dedupeKey"] = key
        record["dedupe_key"] = key
        record["dedupeKeySource"] = source
        record["dedupe_key_source"] = source
        record["dedupeGroupSize"] = group_size
        record["dedupe_group_size"] = group_size
        record["isDuplicateRow"] = group_size > 1
        record["is_duplicate_row"] = group_size > 1
    return rows


def unique_records(records: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    seen: set[str] = set()
    unique: list[Mapping[str, Any]] = []
    for record in records:
        key = str(record.get("dedupeKey") or record.get("dedupe_key") or "")
        if not key:
            key, _source = dedupe_key(record)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def dedupe_summary(records: Sequence[Mapping[str, Any]], *, row_type: str) -> dict[str, Any]:
    rows = list(records)
    raw_count = len(rows)
    key_counts = Counter(str(record.get("dedupeKey") or record.get("dedupe_key") or dedupe_key(record)[0]) for record in rows)
    source_by_key: dict[str, str] = {}
    targets_by_key: dict[str, Counter[str]] = defaultdict(Counter)
    for record in rows:
        key = str(record.get("dedupeKey") or record.get("dedupe_key") or dedupe_key(record)[0])
        source_by_key.setdefault(key, str(record.get("dedupeKeySource") or record.get("dedupe_key_source") or dedupe_key(record)[1]))
        targets_by_key[key][target_label(record)] += 1
    unique_count = len(key_counts)
    duplicate_targets: Counter[str] = Counter()
    for key, count in key_counts.items():
        if count > 1:
            duplicate_targets.update(targets_by_key[key])
    low_confidence_count = sum(
        count for key, count in key_counts.items() if source_by_key.get(key) in LOW_CONFIDENCE_KEY_SOURCES
    )
    prefix = row_type[0].lower() + row_type[1:]
    raw_key = f"raw{row_type}Rows"
    unique_key = f"unique{row_type}Rows"
    ratio_key = f"{prefix}DedupeRatio"
    legacy_ratio_key = f"{prefix}DuplicationRatio"
    ratio = round(raw_count / unique_count if unique_count else 0.0, 4)
    return {
        raw_key: raw_count,
        unique_key: unique_count,
        ratio_key: ratio,
        legacy_ratio_key: ratio,
        "rawRowCount": raw_count,
        "uniqueRowCount": unique_count,
        "dedupeRatio": ratio,
        "lowConfidenceDedupeKeyRows": low_confidence_count,
        "lowConfidenceDedupeKeyShare": round(low_confidence_count / raw_count if raw_count else 0.0, 4),
        "topDuplicateKeys": [
            {
                "dedupeKey": key,
                "count": count,
                "dedupeKeySource": source_by_key.get(key, ""),
                "targets": dict(sorted(targets_by_key[key].items())),
            }
            for key, count in key_counts.most_common(25)
            if count > 1
        ],
        "topDuplicateTargets": dict(sorted(duplicate_targets.items(), key=lambda item: (-item[1], item[0]))[:25]),
    }


def _pick(summary: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in summary:
            return summary[key]
    return 0


def build_count_hygiene_summary(records: Sequence[MutableMapping[str, Any]]) -> dict[str, Any]:
    rows = annotate_dedupe(records)
    visible = [record for record in rows if bool(record.get("visible"))]
    strong = [record for record in rows if bool(record.get("strong_risk"))]
    hard = [record for record in rows if bool(record.get("hard_evidence_review"))]
    visible_summary = dedupe_summary(visible, row_type="Visible")
    strong_summary = dedupe_summary(strong, row_type="StrongRisk")
    hard_summary = dedupe_summary(hard, row_type="HardEvidenceReview")
    duplicate_targets = Counter()
    for summary in (visible_summary, strong_summary, hard_summary):
        duplicate_targets.update(summary.get("topDuplicateTargets") or {})
    return {
        "rawVisibleRows": visible_summary["rawVisibleRows"],
        "uniqueVisibleRows": visible_summary["uniqueVisibleRows"],
        "visibleDedupeRatio": visible_summary["visibleDedupeRatio"],
        "rawStrongRiskRows": strong_summary["rawStrongRiskRows"],
        "uniqueStrongRiskRows": strong_summary["uniqueStrongRiskRows"],
        "strongRiskDedupeRatio": strong_summary["strongRiskDedupeRatio"],
        "rawHardEvidenceReviewRows": hard_summary["rawHardEvidenceReviewRows"],
        "uniqueHardEvidenceReviewRows": hard_summary["uniqueHardEvidenceReviewRows"],
        "hardEvidenceReviewDedupeRatio": hard_summary["hardEvidenceReviewDedupeRatio"],
        "topDuplicateStrongRiskKeys": strong_summary["topDuplicateKeys"],
        "topDuplicateHardEvidenceReviewKeys": hard_summary["topDuplicateKeys"],
        "topDuplicateVisibleKeys": visible_summary["topDuplicateKeys"],
        "topDuplicateTargets": dict(sorted(duplicate_targets.items(), key=lambda item: (-item[1], item[0]))[:25]),
        "visibleDedupe": visible_summary,
        "strongRiskDedupe": strong_summary,
        "hardEvidenceReviewDedupe": hard_summary,
    }


def count_hygiene_warnings(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    strong_ratio = float(summary.get("strongRiskDedupeRatio") or 0)
    her_ratio = float(summary.get("hardEvidenceReviewDedupeRatio") or 0)
    if strong_ratio >= 2.0:
        warnings.append({"code": "strong_risk_dedupe_inflation_concern", "ratio": strong_ratio})
    elif strong_ratio >= 1.5:
        warnings.append({"code": "strong_risk_dedupe_inflation_warning", "ratio": strong_ratio})
    if her_ratio >= 2.0:
        warnings.append({"code": "her_dedupe_inflation_concern", "ratio": her_ratio})
    elif her_ratio >= 1.5:
        warnings.append({"code": "her_dedupe_inflation_warning", "ratio": her_ratio})
    for bucket in ("visibleDedupe", "strongRiskDedupe", "hardEvidenceReviewDedupe"):
        details = summary.get(bucket)
        if not isinstance(details, Mapping):
            continue
        raw = int(details.get("rawRowCount") or 0)
        low = int(details.get("lowConfidenceDedupeKeyRows") or 0)
        if raw >= 10 and low / raw >= 0.25:
            warnings.append({"code": "dedupe_key_low_confidence", "bucket": bucket, "rows": low, "rawRows": raw})
    for target, count in (summary.get("topDuplicateTargets") or {}).items():
        duplicate_total = sum(int(value or 0) for value in (summary.get("topDuplicateTargets") or {}).values())
        if duplicate_total and int(count or 0) / duplicate_total > 0.3:
            warnings.append({"code": "duplicate_target_dominance", "target": target, "duplicateRows": count})
            break
    return warnings
