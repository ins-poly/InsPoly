#!/usr/bin/env python3
"""Evaluate reconstruction-report PnL as advisory sidecar context only."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.evaluate_normalized_shadow_context import (  # noqa: E402
    METRIC_NET_PNL,
    evaluate_artifact,
)
from tools.normalize_shadow_inputs_from_artifacts import (  # noqa: E402
    RECORD_CURRENT_PRICE,
    RECORD_LEDGER_TRADE,
    normalize_artifact,
)


REPORT_TYPE = "reconstruction_shadow_pnl_evaluation"
SCHEMA_VERSION = "reconstruction_shadow_pnl_evaluation_v1"


def evaluate_reconstruction_dir(path: str | Path) -> dict[str, object]:
    artifact_path = Path(path)
    normalization = normalize_artifact("reconstruction_report_dir", artifact_path).to_dict()
    evaluation = evaluate_artifact("reconstruction_report_dir", artifact_path)
    pnl_metric = _metric(evaluation, METRIC_NET_PNL)
    records = normalization.get("normalizedRecords") if isinstance(normalization.get("normalizedRecords"), list) else []
    ledger_records = [record for record in records if isinstance(record, Mapping) and record.get("recordType") == RECORD_LEDGER_TRADE]
    current_price_records = [
        record for record in records if isinstance(record, Mapping) and record.get("recordType") == RECORD_CURRENT_PRICE
    ]
    quality_notes = sorted(
        {
            *(str(note) for note in normalization.get("qualityNotes", [])),
            *(str(note) for note in pnl_metric.get("qualityNotes", [])),
        }
    )
    return {
        "artifactPath": str(artifact_path),
        "status": pnl_metric.get("evaluatedStatus"),
        "advisoryLevel": pnl_metric.get("advisoryLevel"),
        "pnlValue": pnl_metric.get("value"),
        "pnlIsContextOnly": True,
        "ledgerRecordCount": len(ledger_records),
        "currentPriceRecordCount": len(current_price_records),
        "currentPriceAvailable": bool(current_price_records),
        "cashSourceQualityNotes": [note for note in quality_notes if "cash" in note or "source" in note],
        "qualityNotes": quality_notes,
        "skippedUnsafeFieldCount": normalization.get("skippedUnsafeFieldCount", 0),
        "metricDetails": pnl_metric.get("details", {}),
    }


def evaluate_reconstruction_dirs(paths: Sequence[str | Path]) -> dict[str, object]:
    artifacts = [evaluate_reconstruction_dir(path) for path in paths]
    report = {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "networkUsed": False,
        "productionIntegration": False,
        "summary": _summary(artifacts),
        "artifacts": artifacts,
    }
    return report


def discover_reconstruction_dirs(root: str | Path = REPO_ROOT) -> tuple[Path, ...]:
    base = Path(root)
    return tuple(sorted(path for path in base.glob("polymarket_*_report") if path.is_dir()))


def write_reconstruction_pnl_outputs(report: Mapping[str, object], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"reconstruction_shadow_pnl_evaluation_{stamp}.json"
    md_path = target / f"reconstruction_shadow_pnl_evaluation_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: Mapping[str, object]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# Reconstruction Shadow PnL Evaluation",
        "",
        f"- Schema: `{report.get('schemaVersion')}`",
        f"- Network used: {str(report.get('networkUsed')).lower()}",
        f"- Production integration: {str(report.get('productionIntegration')).lower()}",
        f"- Artifacts: {summary.get('artifactCount', 0)}",
        f"- PnL available: {summary.get('availablePnlCount', 0)}",
        f"- Current price missing: {summary.get('missingCurrentPriceCount', 0)}",
        f"- Total known PnL: {summary.get('totalKnownPnl') or 'unknown'}",
        "",
        "| Artifact | Status | PnL | Ledger rows | Current prices | Quality notes |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for artifact in report.get("artifacts", []):
        if not isinstance(artifact, Mapping):
            continue
        notes = ", ".join(str(note) for note in artifact.get("qualityNotes", [])[:4])
        lines.append(
            f"| `{artifact.get('artifactPath')}` | `{artifact.get('status')}` | "
            f"{artifact.get('pnlValue') or 'unknown'} | {artifact.get('ledgerRecordCount')} | "
            f"{artifact.get('currentPriceRecordCount')} | {notes} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _metric(evaluation: Mapping[str, object], name: str) -> dict[str, object]:
    metrics = evaluation.get("metricEvaluations") if isinstance(evaluation.get("metricEvaluations"), list) else []
    for metric in metrics:
        if isinstance(metric, Mapping) and metric.get("metric") == name:
            return dict(metric)
    return {"metric": name, "evaluatedStatus": "unknown", "value": None, "qualityNotes": ["metric_missing_unknown"]}


def _summary(artifacts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    status_counts = Counter(str(item.get("status")) for item in artifacts)
    total: Decimal | None = None
    for item in artifacts:
        value = _decimal(item.get("pnlValue"))
        if value is None:
            continue
        total = value if total is None else total + value
    return {
        "artifactCount": len(artifacts),
        "availablePnlCount": status_counts.get("available", 0),
        "unknownPnlCount": status_counts.get("unknown", 0),
        "missingCurrentPriceCount": sum(1 for item in artifacts if not item.get("currentPriceAvailable")),
        "ledgerRecordCount": sum(int(item.get("ledgerRecordCount") or 0) for item in artifacts),
        "currentPriceRecordCount": sum(int(item.get("currentPriceRecordCount") or 0) for item in artifacts),
        "totalKnownPnl": _decimal_text(total),
        "statusCounts": dict(sorted(status_counts.items())),
        "pnlContextOnly": True,
    }


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate reconstruction report PnL as sidecar context.")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Root used for default reconstruction report discovery.")
    parser.add_argument("--artifact-dir", action="append", default=[], help="Reconstruction report directory. Repeatable.")
    parser.add_argument("--output-dir", help="Optional explicit output directory for JSON and Markdown artifacts.")
    parser.add_argument("--output-json", help="Optional explicit JSON output path.")
    parser.add_argument("--output-md", help="Optional explicit Markdown output path.")
    parser.add_argument("--quiet", action="store_true", help="Do not print the full JSON report to stdout.")
    args = parser.parse_args(argv)

    paths = tuple(Path(path) for path in args.artifact_dir) if args.artifact_dir else discover_reconstruction_dirs(args.root)
    report = evaluate_reconstruction_dirs(paths)
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
        write_reconstruction_pnl_outputs(report, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
