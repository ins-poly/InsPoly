#!/usr/bin/env python3
"""Analyze whether archive shadow win-rate confidence duplicates report fields."""

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

from app.shadow_metrics import (  # noqa: E402
    ADVISORY_NONE,
    SHADOW_WIN_RATE_CONFIDENCE,
    compute_shadow_metrics,
)


REPORT_TYPE = "archive_wallet_history_shadow_overlap"
SCHEMA_VERSION = "archive_wallet_history_shadow_overlap_v1"


def analyze_archive_report(path: str | Path) -> dict[str, object]:
    artifact_path = Path(path)
    payload = _read_json(artifact_path)
    cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    rows = []
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            continue
        trade = case.get("trade") if isinstance(case.get("trade"), Mapping) else {}
        raw = case.get("raw_metrics") if isinstance(case.get("raw_metrics"), Mapping) else {}
        resolved = _decimal(raw.get("wallet_closed_positions"))
        wins = _decimal(raw.get("wallet_closed_wins"))
        if resolved is None or wins is None or resolved <= 0:
            rows.append(
                {
                    "caseIndex": index,
                    "wallet": trade.get("wallet") or "unknown",
                    "status": "missing_wallet_history",
                    "duplicateProductionSemantics": False,
                    "shadowUseful": False,
                    "reason": "wallet closed-position count or win count missing",
                }
            )
            continue
        metric = compute_shadow_metrics([], wallet_stats={"resolved_trades": resolved, "winning_trades": wins}).metric(
            SHADOW_WIN_RATE_CONFIDENCE
        )
        rows.append(
            {
                "caseIndex": index,
                "wallet": trade.get("wallet") or "unknown",
                "status": metric.status,
                "resolvedTrades": _decimal_text(resolved),
                "winningTrades": _decimal_text(wins),
                "rawWinRate": _decimal_text(wins / resolved),
                "shadowValue": metric.value,
                "shadowAdvisoryLevel": metric.advisory_level,
                "shadowUseful": metric.advisory_level != ADVISORY_NONE and metric.status == "available",
                "duplicateProductionSemantics": True,
                "qualityNotes": list(metric.notes),
                "reason": "shadow confidence is computed entirely from existing archive wallet-history fields",
            }
        )
    return {
        "artifactPath": str(artifact_path),
        "caseCount": len(cases),
        "walletHistoryRows": rows,
        "summary": _artifact_summary(rows),
    }


def analyze_archive_reports(paths: Sequence[str | Path]) -> dict[str, object]:
    artifacts = [analyze_archive_report(path) for path in paths]
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


def discover_archive_reports(root: str | Path = REPO_ROOT, *, limit: int = 20) -> tuple[Path, ...]:
    base = Path(root) / ".inspoly_archive_researcher" / "reports"
    paths = sorted(base.glob("archive_research_*.json")) if base.exists() else []
    return tuple(paths[:limit] if limit > 0 else paths)


def write_overlap_outputs(report: Mapping[str, object], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"archive_wallet_history_shadow_overlap_{stamp}.json"
    md_path = target / f"archive_wallet_history_shadow_overlap_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: Mapping[str, object]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# Archive Wallet-History Shadow Overlap",
        "",
        f"- Schema: `{report.get('schemaVersion')}`",
        f"- Network used: {str(report.get('networkUsed')).lower()}",
        f"- Production integration: {str(report.get('productionIntegration')).lower()}",
        f"- Artifacts: {summary.get('artifactCount', 0)}",
        f"- Cases: {summary.get('caseCount', 0)}",
        f"- Duplicate rows: {summary.get('duplicateProductionSemanticRows', 0)}",
        f"- Useful shadow rows: {summary.get('usefulShadowRows', 0)}",
        f"- Recommendation: `{summary.get('recommendation')}`",
        "",
        "| Artifact | Cases | Duplicate rows | Useful shadow rows | Missing rows |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for artifact in report.get("artifacts", []):
        if not isinstance(artifact, Mapping):
            continue
        item = artifact.get("summary") if isinstance(artifact.get("summary"), Mapping) else {}
        lines.append(
            f"| `{artifact.get('artifactPath')}` | {artifact.get('caseCount')} | "
            f"{item.get('duplicateProductionSemanticRows', 0)} | {item.get('usefulShadowRows', 0)} | "
            f"{item.get('missingWalletHistoryRows', 0)} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _artifact_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "rowCount": len(rows),
        "duplicateProductionSemanticRows": sum(1 for row in rows if row.get("duplicateProductionSemantics")),
        "usefulShadowRows": sum(1 for row in rows if row.get("shadowUseful")),
        "missingWalletHistoryRows": sum(1 for row in rows if row.get("status") == "missing_wallet_history"),
    }


def _summary(artifacts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    case_count = sum(int(artifact.get("caseCount") or 0) for artifact in artifacts)
    duplicate_rows = 0
    useful_rows = 0
    missing_rows = 0
    status_counts: Counter[str] = Counter()
    for artifact in artifacts:
        item = artifact.get("summary") if isinstance(artifact.get("summary"), Mapping) else {}
        duplicate_rows += int(item.get("duplicateProductionSemanticRows") or 0)
        useful_rows += int(item.get("usefulShadowRows") or 0)
        missing_rows += int(item.get("missingWalletHistoryRows") or 0)
        for row in artifact.get("walletHistoryRows", []):
            if isinstance(row, Mapping):
                status_counts[str(row.get("status"))] += 1
    duplicate_ratio = Decimal(duplicate_rows) / Decimal(case_count) if case_count else Decimal("0")
    recommendation = "keep_sidecar_only_or_benchmark_only" if duplicate_ratio >= Decimal("0.5") else "insufficient_overlap_evidence"
    return {
        "artifactCount": len(artifacts),
        "caseCount": case_count,
        "duplicateProductionSemanticRows": duplicate_rows,
        "usefulShadowRows": useful_rows,
        "missingWalletHistoryRows": missing_rows,
        "duplicateRatio": _decimal_text(duplicate_ratio),
        "statusCounts": dict(sorted(status_counts.items())),
        "recommendation": recommendation,
    }


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Archive report root must be a JSON object")
    return payload


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
    parser = argparse.ArgumentParser(description="Analyze archive wallet-history shadow metric overlap.")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--artifact-json", action="append", default=[])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output-dir")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    paths = tuple(Path(path) for path in args.artifact_json) if args.artifact_json else discover_archive_reports(args.root, limit=args.limit)
    report = analyze_archive_reports(paths)
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
        write_overlap_outputs(report, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
