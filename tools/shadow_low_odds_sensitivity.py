#!/usr/bin/env python3
"""Evaluate low-odds exposure thresholds as sidecar-only sensitivity."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "shadow_low_odds_sensitivity"
SCHEMA_VERSION = "shadow_low_odds_sensitivity_v1"

DEFAULT_PRICE_CEILING = Decimal("0.15")
DEFAULT_CONTEXT_NOTIONAL = Decimal("1000")
DEFAULT_NOTABLE_NOTIONAL = Decimal("5000")

PRICE_VARIANTS = (Decimal("0.10"), Decimal("0.15"), Decimal("0.20"), Decimal("0.30"))


def evaluate_low_odds_sensitivity(
    batch_normalization: Mapping[str, object],
    *,
    price_variants: Sequence[Decimal] = PRICE_VARIANTS,
) -> dict[str, object]:
    records = _trade_exposure_records(batch_normalization)
    variants = [
        _evaluate_variant(records, price_ceiling=price_ceiling)
        for price_ceiling in price_variants
    ]
    report = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "networkUsed": False,
        "productionIntegration": False,
        "defaultThresholdsUnchanged": True,
        "summary": {
            "tradeExposureRecordCount": len(records),
            "nearCertaintyControlCount": sum(1 for record in records if _price(record) is not None and _price(record) >= Decimal("0.85")),
            "staleResolutionControlCount": sum(1 for record in records if _truthy(record.get("stale_resolution") or record.get("staleResolution"))),
            "variantCount": len(variants),
            "defaultPriceCeiling": _decimal_text(DEFAULT_PRICE_CEILING),
            "defaultTriggeredCount": next(
                (variant["triggeredCount"] for variant in variants if variant["priceCeiling"] == _decimal_text(DEFAULT_PRICE_CEILING)),
                0,
            ),
            "decisionHint": _decision_hint(variants),
        },
        "variants": variants,
    }
    return report


def write_sensitivity_outputs(report: Mapping[str, object], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"shadow_low_odds_sensitivity_{stamp}.json"
    md_path = target / f"shadow_low_odds_sensitivity_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: Mapping[str, object]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# Shadow Low-Odds Sensitivity",
        "",
        f"- Schema: `{report.get('schemaVersion')}`",
        f"- Network used: {str(report.get('networkUsed')).lower()}",
        f"- Production integration: {str(report.get('productionIntegration')).lower()}",
        f"- Default thresholds unchanged: {str(report.get('defaultThresholdsUnchanged')).lower()}",
        f"- Exposure records: {summary.get('tradeExposureRecordCount', 0)}",
        f"- Near-certainty controls: {summary.get('nearCertaintyControlCount', 0)}",
        f"- Stale-resolution controls: {summary.get('staleResolutionControlCount', 0)}",
        f"- Decision hint: `{summary.get('decisionHint')}`",
        "",
        "| Price ceiling | Triggered | Total cash | Context | Notable |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ]
    for variant in report.get("variants", []):
        if isinstance(variant, Mapping):
            lines.append(
                f"| {variant.get('priceCeiling')} | {variant.get('triggeredCount')} | "
                f"{variant.get('triggeredCash')} | {variant.get('contextCount')} | {variant.get('notableCount')} |"
            )
    return "\n".join(lines).rstrip() + "\n"


def _trade_exposure_records(batch_normalization: Mapping[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    artifacts = batch_normalization.get("artifacts") if isinstance(batch_normalization.get("artifacts"), list) else []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        for record in artifact.get("normalizedRecords", []):
            if not isinstance(record, Mapping) or record.get("recordType") != "trade_exposure":
                continue
            fields = record.get("fields")
            if isinstance(fields, Mapping):
                rows.append({**fields, "_artifactPath": artifact.get("artifactPath")})
    return rows


def _evaluate_variant(records: Sequence[Mapping[str, object]], *, price_ceiling: Decimal) -> dict[str, object]:
    triggered_cash = Decimal("0")
    triggered_count = 0
    context_count = 0
    notable_count = 0
    source_counts: Counter[str] = Counter()
    for record in records:
        side = str(record.get("side") or record.get("order_side") or "").upper()
        if side and side != "BUY":
            continue
        price = _price(record)
        cash = _cash(record)
        if price is None or cash is None:
            continue
        if _truthy(record.get("stale_resolution") or record.get("staleResolution")):
            continue
        if price >= Decimal("0.85"):
            continue
        if price <= price_ceiling:
            triggered_count += 1
            triggered_cash += cash
            source_counts[str(record.get("_artifactPath") or "unknown")] += 1
            if cash >= DEFAULT_CONTEXT_NOTIONAL:
                context_count += 1
            if cash >= DEFAULT_NOTABLE_NOTIONAL:
                notable_count += 1
    return {
        "priceCeiling": _decimal_text(price_ceiling),
        "triggeredCount": triggered_count,
        "triggeredCash": _decimal_text(triggered_cash),
        "contextCount": context_count,
        "notableCount": notable_count,
        "topArtifacts": [
            {"artifactPath": artifact, "count": count}
            for artifact, count in source_counts.most_common(5)
        ],
        "evaluationOnly": True,
    }


def _decision_hint(variants: Sequence[Mapping[str, object]]) -> str:
    default = next((variant for variant in variants if variant.get("priceCeiling") == _decimal_text(DEFAULT_PRICE_CEILING)), None)
    wider = next((variant for variant in variants if variant.get("priceCeiling") == "0.3"), None)
    if not default or int(default.get("triggeredCount") or 0) == 0:
        return "keep_default_sidecar_metric_no_threshold_change"
    if wider and int(wider.get("triggeredCount") or 0) > int(default.get("triggeredCount") or 0) * 3:
        return "wider_threshold_adds_many_cases_review_false_positive_risk"
    return "default_threshold_behaves_as_expected"


def _price(record: Mapping[str, object]) -> Decimal | None:
    return _decimal(record.get("price") or record.get("entry_price") or record.get("entryPrice"))


def _cash(record: Mapping[str, object]) -> Decimal | None:
    explicit = _decimal(record.get("cash_amount") or record.get("usdcSize") or record.get("usdc_size"))
    if explicit is not None:
        return explicit
    size = _decimal(record.get("size") or record.get("shares"))
    price = _price(record)
    if size is None or price is None:
        return None
    return size * price


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _read_json(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Input JSON root must be an object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate low-odds threshold sensitivity from normalized sidecar records.")
    parser.add_argument("--batch-normalization-json", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = evaluate_low_odds_sensitivity(_read_json(args.batch_normalization_json))
    text = json.dumps(report, indent=2, sort_keys=True)
    if not args.quiet:
        print(text)
    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(markdown_report(report), encoding="utf-8")
    if args.output_dir:
        write_sensitivity_outputs(report, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
