#!/usr/bin/env python3
"""Read-only artifact audit for advisory shadow metrics.

This tool consumes local fixture/report-like artifacts only. It does not fetch
network data, mutate saved reports, or wire shadow metrics into production
scanner/archive/event-forensic paths.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.shadow_metrics import compute_shadow_metrics  # noqa: E402


STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ShadowArtifactAudit:
    artifact_dir: str
    status: str
    rows_loaded: int
    metrics: tuple[dict[str, object], ...]
    quality_notes: tuple[str, ...]
    network_used: bool = False
    production_integration: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "artifactDir": self.artifact_dir,
            "status": self.status,
            "rowsLoaded": self.rows_loaded,
            "metrics": list(self.metrics),
            "qualityNotes": list(self.quality_notes),
            "networkUsed": self.network_used,
            "productionIntegration": self.production_integration,
        }


def audit_shadow_metrics_artifact_dir(artifact_dir: str | Path) -> ShadowArtifactAudit:
    root = Path(artifact_dir)
    rows = _read_trade_rows(root)
    wallet_stats = _read_optional_object(root / "wallet_stats.json")
    current_prices = _read_optional_object(root / "current_prices.json")
    microstructure = _read_optional_rows(root / "orderbook_snapshots.json")
    report = compute_shadow_metrics(
        rows,
        wallet_stats=wallet_stats,
        current_prices=current_prices,
        microstructure=microstructure,
    )
    status = _status(report.quality_notes, len(rows))
    return ShadowArtifactAudit(
        artifact_dir=str(root),
        status=status,
        rows_loaded=len(rows),
        metrics=tuple(metric.to_dict() for metric in report.metrics),
        quality_notes=report.quality_notes,
    )


def write_shadow_artifact_audit(audit: ShadowArtifactAudit, output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"shadow_metrics_audit_{stamp}.json"
    md_path = target / f"shadow_metrics_audit_{stamp}.md"
    json_path.write_text(json.dumps(audit.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_markdown(audit), encoding="utf-8")
    return json_path, md_path


def _read_trade_rows(root: Path) -> list[dict[str, object]]:
    for name in ("shadow_trades.csv", "trades.csv", "normalized_trades.csv", "suspicious_trades.csv"):
        path = root / name
        if path.exists():
            return _read_csv(path)
    event_json = root / "event_analysis.json"
    if event_json.exists():
        payload = _read_json(event_json)
        if isinstance(payload, Mapping):
            for key in ("display_trades", "displayTrades", "suspicious_trades", "trades"):
                rows = payload.get(key)
                if isinstance(rows, list):
                    return [dict(row) for row in rows if isinstance(row, Mapping)]
    return []


def _read_csv(path: Path) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_optional_object(path: Path) -> dict[str, object]:
    payload = _read_json(path) if path.exists() else {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _read_optional_rows(path: Path) -> list[dict[str, object]]:
    payload = _read_json(path) if path.exists() else []
    if isinstance(payload, Mapping):
        rows = payload.get("rows") or payload.get("snapshots")
    else:
        rows = payload
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _status(notes: Sequence[str], rows_loaded: int) -> str:
    if rows_loaded == 0:
        return STATUS_UNKNOWN
    return STATUS_WARNING if any("unknown" in note for note in notes) else STATUS_OK


def _markdown(audit: ShadowArtifactAudit) -> str:
    lines = [
        "# Shadow Metrics Artifact Audit",
        "",
        f"- Status: {audit.status}",
        f"- Rows loaded: {audit.rows_loaded}",
        f"- Network used: {str(audit.network_used).lower()}",
        f"- Production integration: {str(audit.production_integration).lower()}",
        "",
        "## Metrics",
    ]
    for metric in audit.metrics:
        lines.append(
            f"- {metric.get('name')}: {metric.get('status')} / {metric.get('advisoryLevel')} / {metric.get('value')}"
        )
    if audit.quality_notes:
        lines.extend(["", "## Quality Notes"])
        lines.extend(f"- {note}" for note in audit.quality_notes)
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit advisory shadow metrics against local artifacts.")
    parser.add_argument("artifact_dir", help="Local artifact directory to read.")
    parser.add_argument("--output-dir", help="Optional explicit output directory.")
    args = parser.parse_args(argv)

    audit = audit_shadow_metrics_artifact_dir(args.artifact_dir)
    if args.output_dir:
        paths = write_shadow_artifact_audit(audit, args.output_dir)
        print(json.dumps({**audit.to_dict(), "outputPaths": [str(path) for path in paths]}, indent=2, sort_keys=True))
    else:
        print(json.dumps(audit.to_dict(), indent=2, sort_keys=True))
    return 0 if audit.status != STATUS_UNKNOWN else 2


if __name__ == "__main__":
    raise SystemExit(main())
