#!/usr/bin/env python3
"""Inspect browser HTML files for offline runtime asset risk."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "browser_offline_asset_preflight"
SCHEMA_VERSION = "browser_offline_asset_preflight_v1"
DEFAULT_OUTPUT = Path("validation_outputs/browser_offline_asset_preflight_20260525.json")
DEFAULT_HTML_FILES = ("app/browser_ui.html", "app/browser_event_forensic_ui.html")
URL_RE = re.compile(r"(?:src|href)=[\"'](https?://[^\"']+)[\"']|`(https?://[^`]+)`|\"(https?://[^\"]+)\"")


def build_browser_offline_asset_preflight(
    root: str | Path = ".",
    *,
    html_files: Sequence[str | Path] = DEFAULT_HTML_FILES,
) -> dict[str, object]:
    base = Path(root)
    rows: list[dict[str, object]] = []
    for html_file in html_files:
        path = Path(html_file)
        resolved = path if path.is_absolute() else base / path
        try:
            source = resolved.read_text(encoding="utf-8")
        except OSError:
            rows.append(
                {
                    "file": str(path),
                    "url": "",
                    "assetKind": "missing_file",
                    "runtimeRequiredForUiBoot": False,
                    "analystNavigationOnly": False,
                    "localAssetCandidate": "",
                    "localAssetExists": False,
                    "risk": "missing_file",
                }
            )
            continue
        for url in _urls(source):
            kind = _asset_kind(url)
            runtime_required = kind in {"react_cdn", "babel_cdn", "font_cdn"}
            candidate = _local_candidate(url)
            rows.append(
                {
                    "file": str(path),
                    "url": url,
                    "assetKind": kind,
                    "runtimeRequiredForUiBoot": runtime_required,
                    "analystNavigationOnly": kind in {"external_profile_link", "external_market_link", "external_chain_link"},
                    "localAssetCandidate": str(candidate) if candidate else "",
                    "localAssetExists": bool(candidate and (base / candidate).exists()),
                    "risk": "runtime_blocking_if_offline" if runtime_required else "navigation_only_or_dynamic",
                }
            )
    summary = _summary(rows)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "uiRuntimeChanged": False,
        "gateDecision": _gate(summary),
        "summary": summary,
        "dependencyRows": rows,
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _urls(source: str) -> list[str]:
    found: list[str] = []
    for match in URL_RE.finditer(source):
        for group in match.groups():
            if group and group not in found:
                found.append(group)
    return found


def _asset_kind(url: str) -> str:
    lower = url.lower()
    if "unpkg.com/react-dom" in lower:
        return "react_dom_cdn"
    if "unpkg.com/react@" in lower:
        return "react_cdn"
    if "babel" in lower and "unpkg.com" in lower:
        return "babel_cdn"
    if "fonts.googleapis.com" in lower:
        return "font_cdn"
    if "polygonscan.com" in lower:
        return "external_chain_link"
    if "polymarket.com/profile" in lower:
        return "external_profile_link"
    if "polymarket.com/event" in lower or "polymarket.com/market" in lower:
        return "external_market_link"
    return "external_url"


def _local_candidate(url: str) -> Path | None:
    lower = url.lower()
    if "react-dom" in lower:
        return Path("app/vendor/react-dom.development.js")
    if "react@" in lower:
        return Path("app/vendor/react.development.js")
    if "babel" in lower:
        return Path("app/vendor/babel.min.js")
    return None


def _summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    kinds = Counter(str(row.get("assetKind") or "unknown") for row in rows)
    runtime_rows = [row for row in rows if row.get("runtimeRequiredForUiBoot")]
    missing_runtime = [row for row in runtime_rows if not row.get("localAssetExists")]
    return {
        "fileCount": len({str(row.get("file") or "") for row in rows if row.get("file")}),
        "dependencyCount": len(rows),
        "runtimeRequiredDependencyCount": len(runtime_rows),
        "runtimeRequiredMissingLocalAssetCount": len(missing_runtime),
        "analystNavigationLinkCount": sum(1 for row in rows if row.get("analystNavigationOnly")),
        "assetKindCounts": dict(sorted(kinds.items())),
        "offlineRisk": "high" if missing_runtime else "low",
    }


def _gate(summary: Mapping[str, object]) -> str:
    if int(summary.get("runtimeRequiredMissingLocalAssetCount") or 0) > 0:
        return "browser_offline_assets_blocked_missing_assets"
    return "browser_offline_assets_ready_for_patch"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payload = build_browser_offline_asset_preflight(args.root)
    write_json(payload, args.output)
    if not args.quiet:
        print(f"gate: {payload['gateDecision']}")
        print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
