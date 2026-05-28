#!/usr/bin/env python3
"""Render a manual advisory shadow-context preview artifact.

This is not a production report renderer. It reads an explicit local JSON input
and writes preview JSON/Markdown only under an explicit output directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.shadow_metrics import compute_shadow_metrics_from_payload  # noqa: E402
from app.trader_profile_context import build_trader_profile_context  # noqa: E402


def render_shadow_context_preview(input_json: str | Path, output_dir: str | Path) -> dict[str, Any]:
    payload = _read_payload(Path(input_json))
    shadow = compute_shadow_metrics_from_payload(payload)
    profile_payload = payload.get("profile") if isinstance(payload.get("profile"), Mapping) else {}
    positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
    wallet = str(profile_payload.get("wallet") or payload.get("wallet") or "unknown")
    profile = build_trader_profile_context(
        wallet=wallet,
        positions=positions,
        shadow_metrics=[metric.to_dict() for metric in shadow.metrics],
        trade_count=int(profile_payload.get("trade_count") or profile_payload.get("tradeCount") or len(payload.get("trades", []))),
        high_volume_public_user=bool(profile_payload.get("high_volume_public_user") or profile_payload.get("highVolumePublicUser")),
    )
    preview = {
        "previewType": "shadow_context_advisory",
        "wallet": wallet,
        "profile": profile.to_dict(),
        "shadowMetrics": shadow.to_dict()["shadowMetrics"],
        "qualityNotes": shadow.to_dict()["qualityNotes"],
        "productionIntegration": False,
        "networkUsed": False,
    }
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    json_path = target / f"shadow_context_preview_{stamp}.json"
    md_path = target / f"shadow_context_preview_{stamp}.md"
    json_path.write_text(json.dumps(preview, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_markdown(preview), encoding="utf-8")
    return {**preview, "outputPaths": [str(json_path), str(md_path)]}


def _read_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Preview input root must be a JSON object")
    return payload


def _markdown(preview: Mapping[str, object]) -> str:
    profile = preview.get("profile") if isinstance(preview.get("profile"), Mapping) else {}
    lines = [
        "# Shadow Context Preview",
        "",
        f"- Wallet: {preview.get('wallet')}",
        "- Scope: advisory sidecar only",
        f"- Production integration: {str(preview.get('productionIntegration')).lower()}",
        f"- Total PnL: {profile.get('totalPnl') or 'unknown'}",
        f"- PnL status: {profile.get('pnlStatus')}",
        "",
        "## Advisory Metrics",
    ]
    for metric in preview.get("shadowMetrics", []):
        if isinstance(metric, Mapping):
            lines.append(
                f"- {metric.get('name')}: {metric.get('status')} / {metric.get('advisoryLevel')} / {metric.get('value')}"
            )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a local shadow context preview artifact.")
    parser.add_argument("--input-json", required=True, help="Local JSON input with trades/profile/positions.")
    parser.add_argument("--output-dir", required=True, help="Explicit output directory for preview artifacts.")
    args = parser.parse_args(argv)
    preview = render_shadow_context_preview(args.input_json, args.output_dir)
    print(json.dumps(preview, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
