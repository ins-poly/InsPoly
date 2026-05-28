#!/usr/bin/env python3
"""Inventory local artifacts that can feed shadow sidecar evaluation.

This tool is read-only with respect to source artifacts. It classifies local
report/output files by artifact family so later sidecar phases can select a
representative corpus without changing production reports or runtime paths.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]

REPORT_TYPE = "shadow_artifact_corpus_inventory"
SCHEMA_VERSION = "shadow_artifact_corpus_inventory_v1"

FAMILY_RECENT_SCANNER_JSON = "recent_scanner_report_json"
FAMILY_ARCHIVE_REPORT_JSON = "archive_report_json"
FAMILY_ARCHIVE_CSV = "archive_output_csv"
FAMILY_EVENT_FORENSIC_REPORT_JSON = "event_forensic_report_json"
FAMILY_EVENT_FORENSIC_BUNDLE = "event_forensic_bundle"
FAMILY_CASE_SPECIFIC_INVESTIGATION = "case_specific_investigation_output"
FAMILY_RECONSTRUCTION_REPORT_DIR = "reconstruction_report_dir"
FAMILY_SIDECAR_OUTPUT = "sidecar_output"
FAMILY_SIDECAR_DB = "sidecar_db"

STATUS_SUPPORTED = "normalizer_supported"
STATUS_COVERAGE_ONLY = "coverage_only"
STATUS_SIDECAR_OUTPUT_ONLY = "sidecar_output_only"
STATUS_UNSUPPORTED = "unsupported"

METRIC_LOW_ODDS = "shadow_low_odds_position_size"
METRIC_ENTRY_EDGE = "shadow_entry_price_edge"
METRIC_NET_PNL = "shadow_net_position_pnl"
METRIC_WIN_RATE = "shadow_win_rate_confidence"
METRIC_MICROSTRUCTURE = "shadow_microstructure_context"
METRIC_SCORE_HISTORY = "shadow_score_history_trend"
METRIC_ALERTS = "shadow_alert_watchlist_eligibility"

KNOWN_OUTPUT_DIRS = (
    ".inspoly",
    ".inspoly_archive_researcher",
    ".inspoly_event_forensic_analyzer",
    "archive_outputs",
    "event_forensic_outputs",
    "ceasefire_forensic_outputs",
    "shadow_context_evaluation_outputs",
    "shadow_context_preview_outputs",
    "shadow_review_packets",
)

SIDECAR_OUTPUT_DIR_PREFIXES = (
    "shadow_context_evaluation_outputs",
    "shadow_context_preview_outputs",
    "shadow_review_packets",
)

EVENT_BUNDLE_FILES = (
    "event_analysis.json",
    "suspicious_trades.csv",
    "wallet_context.csv",
    "wallet_graph.json",
    "wallet_clusters.csv",
    "candidate_admission_funnel.json",
)

CASE_SPECIFIC_FILES = (
    "event_analysis.json",
    "suspicious_trades.csv",
    "ranked_suspicious_trades.csv",
    "ranked_suspicious_wallets.csv",
    "wallet_context.csv",
    "wallet_graph.json",
    "wallet_clusters.csv",
)

RECONSTRUCTION_FILES = (
    "normalized_trades.csv",
    "chronological_ledger.csv",
    "summary_calculations.csv",
    "raw_activity.json",
    "raw_positions_current.json",
    "raw_positions_closed.json",
)


@dataclass(frozen=True, slots=True)
class ArtifactStatus:
    generated_like: bool
    git_ignored: str
    stale: str
    modified_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "generatedLike": self.generated_like,
            "gitIgnored": self.git_ignored,
            "stale": self.stale,
            "modifiedAt": self.modified_at,
        }


@dataclass(frozen=True, slots=True)
class ArtifactInventoryItem:
    artifact_path: str
    family: str
    detected_files: tuple[str, ...]
    likely_supported_metrics: tuple[str, ...]
    support_status: str
    support_reason: str
    status: ArtifactStatus
    source_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "artifactPath": self.artifact_path,
            "family": self.family,
            "detectedFiles": list(self.detected_files),
            "likelySupportedMetrics": list(self.likely_supported_metrics),
            "supportStatus": self.support_status,
            "supportReason": self.support_reason,
            "sourceStatus": self.status.to_dict(),
            "sourceNotes": list(self.source_notes),
        }


@dataclass(frozen=True, slots=True)
class CorpusInventory:
    root: str
    artifacts: tuple[ArtifactInventoryItem, ...]
    generated_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        artifacts = [item.to_dict() for item in self.artifacts]
        return {
            "reportType": REPORT_TYPE,
            "schemaVersion": SCHEMA_VERSION,
            "generatedAt": self.generated_at,
            "root": self.root,
            "networkUsed": False,
            "productionIntegration": False,
            "summary": _summary(artifacts),
            "artifacts": artifacts,
        }


def discover_corpus_inventory(
    root: str | Path = REPO_ROOT,
    *,
    max_per_family: int | None = None,
    stale_days: int = 30,
) -> CorpusInventory:
    base = Path(root)
    items: list[ArtifactInventoryItem] = []

    items.extend(_scanner_reports(base, stale_days=stale_days))
    items.extend(_archive_reports(base, stale_days=stale_days))
    items.extend(_archive_csvs(base, stale_days=stale_days))
    items.extend(_event_reports(base, stale_days=stale_days))
    items.extend(_event_bundles(base, stale_days=stale_days))
    items.extend(_case_specific_outputs(base, stale_days=stale_days))
    items.extend(_reconstruction_reports(base, stale_days=stale_days))
    items.extend(_sidecar_outputs(base, stale_days=stale_days))
    items.extend(_sidecar_dbs(base, stale_days=stale_days))

    deduped = _dedupe_items(items)
    capped = _cap_per_family(deduped, max_per_family)
    return CorpusInventory(root=str(base), artifacts=tuple(capped))


def write_inventory_outputs(report: Mapping[str, object], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"shadow_artifact_corpus_inventory_{stamp}.json"
    md_path = target / f"shadow_artifact_corpus_inventory_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, md_path


def markdown_report(report: Mapping[str, object]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# Shadow Artifact Corpus Inventory",
        "",
        f"- Schema: `{report.get('schemaVersion')}`",
        f"- Root: `{report.get('root')}`",
        f"- Network used: {str(report.get('networkUsed')).lower()}",
        f"- Production integration: {str(report.get('productionIntegration')).lower()}",
        f"- Artifacts: {summary.get('artifactCount', 0)}",
        "",
        "## Family Counts",
        "",
        "| Family | Count |",
        "| --- | ---: |",
    ]
    family_counts = summary.get("familyCounts") if isinstance(summary.get("familyCounts"), Mapping) else {}
    for family, count in sorted(family_counts.items()):
        lines.append(f"| `{family}` | {count} |")
    lines.extend(
        [
            "",
            "## Support Counts",
            "",
            "| Support status | Count |",
            "| --- | ---: |",
        ]
    )
    support_counts = summary.get("supportStatusCounts") if isinstance(summary.get("supportStatusCounts"), Mapping) else {}
    for status, count in sorted(support_counts.items()):
        lines.append(f"| `{status}` | {count} |")
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "| Family | Artifact | Support | Metrics |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in report.get("artifacts", []):
        if not isinstance(item, Mapping):
            continue
        metrics = ", ".join(f"`{metric}`" for metric in item.get("likelySupportedMetrics", [])) or "`none`"
        lines.append(
            f"| `{item.get('family')}` | `{item.get('artifactPath')}` | "
            f"`{item.get('supportStatus')}` | {metrics} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _scanner_reports(base: Path, *, stale_days: int) -> list[ArtifactInventoryItem]:
    root = base / ".inspoly" / "reports"
    return [
        _item(
            base,
            path,
            family=FAMILY_RECENT_SCANNER_JSON,
            detected_files=(path.name,),
            metrics=(METRIC_LOW_ODDS,),
            support_status=STATUS_SUPPORTED,
            support_reason="Phase 9D normalizer supports scanner report JSON for low-odds exposure records.",
            stale_days=stale_days,
        )
        for path in _glob(root, "scan_*.json")
    ]


def _archive_reports(base: Path, *, stale_days: int) -> list[ArtifactInventoryItem]:
    root = base / ".inspoly_archive_researcher" / "reports"
    return [
        _item(
            base,
            path,
            family=FAMILY_ARCHIVE_REPORT_JSON,
            detected_files=(path.name,),
            metrics=(METRIC_LOW_ODDS, METRIC_WIN_RATE),
            support_status=STATUS_SUPPORTED,
            support_reason="Phase 9D normalizer supports archive report JSON for low-odds and wallet-history records.",
            stale_days=stale_days,
        )
        for path in _glob(root, "archive_research_*.json")
    ]


def _archive_csvs(base: Path, *, stale_days: int) -> list[ArtifactInventoryItem]:
    root = base / "archive_outputs"
    items = []
    for path in _glob(root, "archive_research_*.csv"):
        metrics = _archive_csv_metrics(path.name)
        items.append(
            _item(
                base,
                path,
                family=FAMILY_ARCHIVE_CSV,
                detected_files=(path.name,),
                metrics=metrics,
                support_status=STATUS_COVERAGE_ONLY if metrics else STATUS_UNSUPPORTED,
                support_reason=_archive_csv_reason(path.name),
                stale_days=stale_days,
                source_notes=("lossy_csv_export",),
            )
        )
    return items


def _event_reports(base: Path, *, stale_days: int) -> list[ArtifactInventoryItem]:
    root = base / ".inspoly_event_forensic_analyzer" / "reports"
    return [
        _item(
            base,
            path,
            family=FAMILY_EVENT_FORENSIC_REPORT_JSON,
            detected_files=(path.name,),
            metrics=(METRIC_LOW_ODDS,),
            support_status=STATUS_SUPPORTED,
            support_reason="Phase 9D normalizer supports Event Forensic report JSON for exposure-only low-odds records.",
            stale_days=stale_days,
            source_notes=("event_forensic_position_size_is_exposure_not_shares",),
        )
        for path in _glob(root, "event_forensic_*.json")
    ]


def _event_bundles(base: Path, *, stale_days: int) -> list[ArtifactInventoryItem]:
    root = base / "event_forensic_outputs"
    items = []
    for path in _dirs(root, "event_forensic_*"):
        detected = _present_files(path, EVENT_BUNDLE_FILES)
        if not detected:
            continue
        metrics = (METRIC_LOW_ODDS,) if "event_analysis.json" in detected else ()
        support_status = STATUS_COVERAGE_ONLY if metrics else STATUS_UNSUPPORTED
        reason = (
            "Bundle contains event_analysis.json; use coverage/normalization only with explicit family selection."
            if metrics
            else "Bundle lacks event_analysis.json and cannot feed current shadow normalizer."
        )
        items.append(
            _item(
                base,
                path,
                family=FAMILY_EVENT_FORENSIC_BUNDLE,
                detected_files=detected,
                metrics=metrics,
                support_status=support_status,
                support_reason=reason,
                stale_days=stale_days,
                source_notes=("event_bundle_directory",),
            )
        )
    return items


def _case_specific_outputs(base: Path, *, stale_days: int) -> list[ArtifactInventoryItem]:
    root = base / "ceasefire_forensic_outputs"
    items = []
    for path in _dirs(root, "*"):
        detected = _present_files(path, CASE_SPECIFIC_FILES)
        if not detected:
            continue
        metrics = (METRIC_LOW_ODDS, METRIC_ENTRY_EDGE) if any(name.endswith(".csv") for name in detected) else ()
        items.append(
            _item(
                base,
                path,
                family=FAMILY_CASE_SPECIFIC_INVESTIGATION,
                detected_files=detected,
                metrics=metrics,
                support_status=STATUS_COVERAGE_ONLY,
                support_reason=(
                    "Case-specific investigation outputs can support coverage studies, but mappings are not general "
                    "production-report semantics."
                ),
                stale_days=stale_days,
                source_notes=("case_specific_shape_not_generalized",),
            )
        )
    return items


def _reconstruction_reports(base: Path, *, stale_days: int) -> list[ArtifactInventoryItem]:
    items = []
    for path in _dirs(base, "polymarket_*_report"):
        detected = _present_files(path, RECONSTRUCTION_FILES)
        if not detected:
            continue
        supported = {"normalized_trades.csv", "raw_positions_current.json"}.issubset(set(detected))
        items.append(
            _item(
                base,
                path,
                family=FAMILY_RECONSTRUCTION_REPORT_DIR,
                detected_files=detected,
                metrics=(METRIC_NET_PNL, METRIC_LOW_ODDS) if supported else (METRIC_NET_PNL,),
                support_status=STATUS_SUPPORTED if supported else STATUS_COVERAGE_ONLY,
                support_reason=(
                    "Reconstruction report has normalized trades plus current positions for ledger/PnL sidecar input."
                    if supported
                    else "Reconstruction report is incomplete for full PnL but useful for coverage/quality notes."
                ),
                stale_days=stale_days,
                source_notes=("reconstruction_artifact_not_production_report",),
            )
        )
    return items


def _sidecar_outputs(base: Path, *, stale_days: int) -> list[ArtifactInventoryItem]:
    items = []
    for prefix in SIDECAR_OUTPUT_DIR_PREFIXES:
        root = base / prefix
        if not root.exists():
            continue
        for path in _dirs(root, "*"):
            detected = tuple(
                sorted(
                    rel.as_posix()
                    for rel in _relative_known_files(path, suffixes=(".json", ".md", ".csv"))
                )
            )
            if not detected:
                continue
            items.append(
                _item(
                    base,
                    path,
                    family=FAMILY_SIDECAR_OUTPUT,
                    detected_files=detected,
                    metrics=(),
                    support_status=STATUS_SIDECAR_OUTPUT_ONLY,
                    support_reason="Existing sidecar output is evidence/reference material, not source input for production reports.",
                    stale_days=stale_days,
                    source_notes=("sidecar_output_no_production_integration",),
                )
            )
    return items


def _sidecar_dbs(base: Path, *, stale_days: int) -> list[ArtifactInventoryItem]:
    items = []
    for root_name in KNOWN_OUTPUT_DIRS:
        root = base / root_name
        for path in _glob(root, "*.sqlite*") + _glob(root, "*.db"):
            items.append(
                _item(
                    base,
                    path,
                    family=FAMILY_SIDECAR_DB,
                    detected_files=(path.name,),
                    metrics=(METRIC_MICROSTRUCTURE, METRIC_SCORE_HISTORY, METRIC_ALERTS),
                    support_status=STATUS_COVERAGE_ONLY,
                    support_reason="Local sidecar database can support future audits only through explicit sidecar tools.",
                    stale_days=stale_days,
                    source_notes=("database_not_mutated_by_inventory",),
                )
            )
    return items


def _item(
    base: Path,
    path: Path,
    *,
    family: str,
    detected_files: Sequence[str],
    metrics: Sequence[str],
    support_status: str,
    support_reason: str,
    stale_days: int,
    source_notes: Sequence[str] = (),
) -> ArtifactInventoryItem:
    return ArtifactInventoryItem(
        artifact_path=_display_path(base, path),
        family=family,
        detected_files=tuple(detected_files),
        likely_supported_metrics=tuple(metrics),
        support_status=support_status,
        support_reason=support_reason,
        status=_status(base, path, stale_days=stale_days),
        source_notes=tuple(source_notes),
    )


def _archive_csv_metrics(name: str) -> tuple[str, ...]:
    if name.endswith("_flagged.csv"):
        return (METRIC_LOW_ODDS,)
    if name.endswith("_wallets.csv"):
        return (METRIC_WIN_RATE,)
    return ()


def _archive_csv_reason(name: str) -> str:
    if name.endswith("_flagged.csv"):
        return "Archive flagged CSV is lossy; it can support coverage checks but not Phase 9D normalization."
    if name.endswith("_wallets.csv"):
        return "Archive wallet CSV may support wallet-history coverage, but can duplicate production wallet semantics."
    return "Archive CSV is not a current normalized shadow input family."


def _present_files(root: Path, names: Sequence[str]) -> tuple[str, ...]:
    return tuple(name for name in names if (root / name).exists())


def _relative_known_files(root: Path, *, suffixes: Sequence[str]) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in suffixes:
            yield path.relative_to(root)


def _glob(root: Path, pattern: str) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.glob(pattern) if path.is_file())


def _dirs(root: Path, pattern: str) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.glob(pattern) if path.is_dir())


def _display_path(base: Path, path: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _status(base: Path, path: Path, *, stale_days: int) -> ArtifactStatus:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        mtime = datetime.fromtimestamp(0, tz=UTC)
    age_days = (datetime.now(tz=UTC) - mtime).total_seconds() / 86400
    stale = "yes" if age_days > stale_days else "no"
    return ArtifactStatus(
        generated_like=_is_generated_like(base, path),
        git_ignored=_git_ignored(base, path),
        stale=stale,
        modified_at=mtime.isoformat(),
    )


def _is_generated_like(base: Path, path: Path) -> bool:
    rel = _display_path(base, path)
    return rel.startswith(KNOWN_OUTPUT_DIRS) or "/reports/" in rel or rel.startswith("polymarket_")


def _git_ignored(base: Path, path: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "check-ignore", "-q", "--", str(path)],
            cwd=base,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, ValueError):
        return "unknown"
    if completed.returncode == 0:
        return "yes"
    if completed.returncode == 1:
        return "no"
    return "unknown"


def _dedupe_items(items: Sequence[ArtifactInventoryItem]) -> list[ArtifactInventoryItem]:
    seen: set[tuple[str, str]] = set()
    deduped: list[ArtifactInventoryItem] = []
    for item in items:
        key = (item.family, item.artifact_path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return sorted(deduped, key=lambda item: (item.family, item.artifact_path))


def _cap_per_family(
    items: Sequence[ArtifactInventoryItem],
    max_per_family: int | None,
) -> list[ArtifactInventoryItem]:
    if not max_per_family or max_per_family <= 0:
        return list(items)
    counts: defaultdict[str, int] = defaultdict(int)
    capped: list[ArtifactInventoryItem] = []
    for item in items:
        if counts[item.family] >= max_per_family:
            continue
        capped.append(item)
        counts[item.family] += 1
    return capped


def _summary(artifacts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    family_counts = Counter(str(item.get("family")) for item in artifacts)
    support_counts = Counter(str(item.get("supportStatus")) for item in artifacts)
    metric_counts: Counter[str] = Counter()
    for item in artifacts:
        for metric in item.get("likelySupportedMetrics", []):
            metric_counts[str(metric)] += 1
    return {
        "artifactCount": len(artifacts),
        "familyCounts": dict(sorted(family_counts.items())),
        "supportStatusCounts": dict(sorted(support_counts.items())),
        "likelyMetricCounts": dict(sorted(metric_counts.items())),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory local artifacts for shadow sidecar evaluation.")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository/artifact root to inspect.")
    parser.add_argument("--max-per-family", type=int, default=0, help="Optional cap per artifact family; 0 means uncapped.")
    parser.add_argument("--stale-days", type=int, default=30, help="Age threshold for stale status.")
    parser.add_argument("--output-dir", help="Optional explicit output directory for JSON and Markdown artifacts.")
    parser.add_argument("--output-json", help="Optional explicit JSON output path.")
    parser.add_argument("--output-md", help="Optional explicit Markdown output path.")
    parser.add_argument("--quiet", action="store_true", help="Do not print the full JSON report to stdout.")
    args = parser.parse_args(argv)

    inventory = discover_corpus_inventory(
        args.root,
        max_per_family=args.max_per_family,
        stale_days=args.stale_days,
    )
    report = inventory.to_dict()
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
        write_inventory_outputs(report, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
