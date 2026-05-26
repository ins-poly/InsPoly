#!/usr/bin/env python3
"""Build a strict-offline readiness inventory for browser UI assets."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

REPORT_TYPE = "browser_strict_offline_readiness"
SCHEMA_VERSION = "browser_strict_offline_readiness_v1"
DEFAULT_OUTPUT = Path("validation_outputs/inspoly_browser_strict_offline_readiness_20260526.json")
DEFAULT_HTML_FILES = ("app/browser_ui.html", "app/browser_event_forensic_ui.html")

TAG_RE = re.compile(r"<(?P<tag>script|link)\b(?P<attrs>[^>]*)>", re.IGNORECASE | re.DOTALL)
ATTR_RE = re.compile(r"(?P<name>[a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)")
INLINE_BABEL_RE = re.compile(r"<script\b[^>]*type=[\"']text/babel[\"'][^>]*>", re.IGNORECASE)

LOCAL_VENDOR_CANDIDATES = {
    "react": Path("app/vendor/react.development.js"),
    "react_dom": Path("app/vendor/react-dom.development.js"),
    "babel": Path("app/vendor/babel.min.js"),
}


def build_strict_offline_readiness(
    root: str | Path = ".",
    *,
    html_files: Sequence[str | Path] = DEFAULT_HTML_FILES,
) -> dict[str, object]:
    base = Path(root)
    html_rows: list[dict[str, object]] = []
    dependencies: list[dict[str, object]] = []
    for html_file in html_files:
        path = Path(html_file)
        resolved = path if path.is_absolute() else base / path
        try:
            source = resolved.read_text(encoding="utf-8")
        except OSError:
            html_rows.append(
                {
                    "path": str(path),
                    "exists": False,
                    "inlineBabelScriptCount": 0,
                    "usesRuntimeBabel": False,
                }
            )
            continue
        inline_babel_count = len(INLINE_BABEL_RE.findall(source))
        html_rows.append(
            {
                "path": str(path),
                "exists": True,
                "sizeBytes": resolved.stat().st_size,
                "inlineBabelScriptCount": inline_babel_count,
                "usesRuntimeBabel": inline_babel_count > 0,
            }
        )
        dependencies.extend(_dependencies_for_html(base, path, source))

    local_assets = _local_asset_rows(base)
    server = _server_capabilities(base)
    summary = _summary(html_rows, dependencies, local_assets, server)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "uiRuntimeChanged": False,
        "storageSchemaChanged": False,
        "gateDecision": _gate(summary),
        "chosenStrategy": _strategy(summary),
        "summary": summary,
        "htmlFiles": html_rows,
        "dependencies": dependencies,
        "localAssets": local_assets,
        "browserDesktopLauncher": server,
        "productDecisionsNeeded": _product_decisions(summary),
        "invariantsPreserved": [
            "no_scoring_or_model_changes",
            "no_phase3_runtime",
            "no_storage_schema_changes",
            "no_ui_sorting_filtering_changes",
            "no_saved_artifact_mutation",
            "no_external_assets_vendored",
            "no_push_pr",
        ],
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _dependencies_for_html(base: Path, html_path: Path, source: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for match in TAG_RE.finditer(source):
        tag = match.group("tag").lower()
        attrs = _attrs(match.group("attrs"))
        reference = attrs.get("src") if tag == "script" else attrs.get("href")
        if not reference:
            continue
        kind = _asset_kind(reference, tag, attrs)
        candidate = _replacement_candidate(kind)
        local_path = _resolve_local_reference(base, html_path, reference) if not _is_remote(reference) else None
        rows.append(
            {
                "htmlFile": str(html_path),
                "tag": tag,
                "reference": reference,
                "isRemote": _is_remote(reference),
                "assetKind": kind,
                "riskClass": _risk_class(kind),
                "requiredForBoot": _required_for_boot(kind),
                "requiredForReportRendering": _required_for_report_rendering(kind),
                "optionalCosmetic": kind == "font_stylesheet",
                "devOnlyTranspileRuntime": kind == "babel_runtime",
                "safeFallbackExists": kind in {"font_stylesheet", "external_navigation_link"},
                "localPath": str(local_path) if local_path else "",
                "localExists": bool(local_path and local_path.exists()),
                "localSizeBytes": local_path.stat().st_size if local_path and local_path.exists() else None,
                "replacementCandidate": str(candidate) if candidate else "",
                "replacementExists": bool(candidate and (base / candidate).exists()),
                "notes": _dependency_notes(kind),
            }
        )
    return rows


def _attrs(source: str) -> dict[str, str]:
    return {match.group("name").lower(): match.group("value") for match in ATTR_RE.finditer(source)}


def _asset_kind(reference: str, tag: str, attrs: Mapping[str, str]) -> str:
    lower = reference.lower()
    if "unpkg.com/react-dom" in lower:
        return "react_dom_runtime"
    if "unpkg.com/react@" in lower:
        return "react_runtime"
    if "babel" in lower and "unpkg.com" in lower:
        return "babel_runtime"
    if "fonts.googleapis.com" in lower or "fonts.gstatic.com" in lower:
        return "font_stylesheet"
    if lower.startswith("http://") or lower.startswith("https://"):
        return "external_navigation_link"
    if tag == "script":
        return "local_script"
    if attrs.get("rel", "").lower() == "stylesheet":
        return "local_stylesheet"
    return "local_asset"


def _replacement_candidate(kind: str) -> Path | None:
    if kind == "react_runtime":
        return LOCAL_VENDOR_CANDIDATES["react"]
    if kind == "react_dom_runtime":
        return LOCAL_VENDOR_CANDIDATES["react_dom"]
    if kind == "babel_runtime":
        return LOCAL_VENDOR_CANDIDATES["babel"]
    return None


def _risk_class(kind: str) -> str:
    if kind in {"react_runtime", "react_dom_runtime", "babel_runtime"}:
        return "hard_offline_boot_blocker"
    if kind == "font_stylesheet":
        return "cosmetic_font_remote_dependency"
    if kind == "external_navigation_link":
        return "navigation_only_remote_link"
    return "local_asset"


def _required_for_boot(kind: str) -> bool:
    return kind in {"react_runtime", "react_dom_runtime", "babel_runtime", "local_script"}


def _required_for_report_rendering(kind: str) -> bool:
    return kind in {"react_runtime", "react_dom_runtime", "babel_runtime", "local_script", "local_stylesheet"}


def _dependency_notes(kind: str) -> list[str]:
    if kind == "babel_runtime":
        return ["inline_text_babel_requires_babel_runtime_or_precompiled_build"]
    if kind in {"react_runtime", "react_dom_runtime"}:
        return ["react_runtime_required_for_current_browser_boot"]
    if kind == "font_stylesheet":
        return ["font_failure_can_fall_back_to_css_font_family"]
    if kind == "external_navigation_link":
        return ["external_link_not_required_for_local_report_rendering"]
    return []


def _resolve_local_reference(base: Path, html_path: Path, reference: str) -> Path:
    if reference.startswith("/"):
        return base / reference.lstrip("/")
    return base / html_path.parent / reference


def _is_remote(reference: str) -> bool:
    return reference.startswith(("http://", "https://"))


def _local_asset_rows(base: Path) -> list[dict[str, object]]:
    rows = []
    for name, path in LOCAL_VENDOR_CANDIDATES.items():
        resolved = base / path
        rows.append(
            {
                "name": name,
                "path": str(path),
                "exists": resolved.exists(),
                "sizeBytes": resolved.stat().st_size if resolved.exists() else None,
                "sourcePolicyStatus": "not_vendored" if not resolved.exists() else "present_local_review_required",
            }
        )
    return rows


def _server_capabilities(base: Path) -> dict[str, object]:
    source_path = base / "app/browser_desktop.py"
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError:
        return {
            "path": "app/browser_desktop.py",
            "exists": False,
            "servesRootHtml": False,
            "servesApiJson": False,
            "servesStaticAssetPaths": False,
        }
    serves_static = any(token in source for token in ('"/static"', '"/vendor"', "parsed.path.startswith('/static')", "parsed.path.startswith('/vendor')"))
    return {
        "path": "app/browser_desktop.py",
        "exists": True,
        "servesRootHtml": 'parsed.path == "/"' in source,
        "servesApiJson": 'parsed.path == "/api/bootstrap"' in source,
        "servesStaticAssetPaths": serves_static,
    }


def _summary(
    html_rows: Sequence[Mapping[str, object]],
    dependencies: Sequence[Mapping[str, object]],
    local_assets: Sequence[Mapping[str, object]],
    server: Mapping[str, object],
) -> dict[str, object]:
    kinds = Counter(str(row.get("assetKind") or "unknown") for row in dependencies)
    risk = Counter(str(row.get("riskClass") or "unknown") for row in dependencies)
    hard_remote = [
        row
        for row in dependencies
        if row.get("isRemote") and row.get("riskClass") == "hard_offline_boot_blocker"
    ]
    remote_fonts = [
        row for row in dependencies if row.get("isRemote") and row.get("riskClass") == "cosmetic_font_remote_dependency"
    ]
    missing_candidates = [row for row in local_assets if not row.get("exists")]
    inline_babel_count = sum(int(row.get("inlineBabelScriptCount") or 0) for row in html_rows)
    return {
        "htmlFileCount": len(html_rows),
        "htmlFilesMissing": sum(1 for row in html_rows if not row.get("exists")),
        "dependencyCount": len(dependencies),
        "assetKindCounts": dict(sorted(kinds.items())),
        "riskClassCounts": dict(sorted(risk.items())),
        "remoteHardBootDependencyCount": len(hard_remote),
        "remoteFontDependencyCount": len(remote_fonts),
        "localVendorCandidateCount": len(local_assets),
        "missingLocalVendorCandidateCount": len(missing_candidates),
        "inlineBabelScriptCount": inline_babel_count,
        "usesRuntimeBabel": inline_babel_count > 0,
        "browserDesktopServesStaticAssetPaths": bool(server.get("servesStaticAssetPaths")),
        "strictOfflineBootPossibleNow": not hard_remote and not remote_fonts and not missing_candidates and bool(server.get("servesStaticAssetPaths")),
        "strictOfflineBootBlockedBy": _blocked_by(hard_remote, remote_fonts, missing_candidates, server, inline_babel_count),
    }


def _blocked_by(
    hard_remote: Sequence[Mapping[str, object]],
    remote_fonts: Sequence[Mapping[str, object]],
    missing_candidates: Sequence[Mapping[str, object]],
    server: Mapping[str, object],
    inline_babel_count: int,
) -> list[str]:
    blockers: list[str] = []
    if hard_remote:
        blockers.append("remote_react_reactdom_babel_boot_assets")
    if missing_candidates:
        blockers.append("missing_local_vendor_asset_candidates")
    if not server.get("servesStaticAssetPaths"):
        blockers.append("browser_desktop_static_asset_serving_not_implemented")
    if remote_fonts:
        blockers.append("remote_google_font_stylesheets")
    if inline_babel_count:
        blockers.append("inline_text_babel_requires_babel_runtime_or_build_pipeline")
    return blockers


def _gate(summary: Mapping[str, object]) -> str:
    if summary.get("strictOfflineBootPossibleNow"):
        return "browser_strict_offline_ready"
    if int(summary.get("remoteHardBootDependencyCount") or 0) == 0 and int(summary.get("missingLocalVendorCandidateCount") or 0) == 0:
        return "browser_offline_partial_local_assets_ready"
    if summary.get("usesRuntimeBabel") and int(summary.get("remoteHardBootDependencyCount") or 0) > 0:
        return "browser_offline_blocked_requires_asset_policy"
    return "browser_offline_no_safe_change"


def _strategy(summary: Mapping[str, object]) -> dict[str, object]:
    gate = _gate(summary)
    if gate == "browser_strict_offline_ready":
        return {
            "strategy": "strict_offline_ready",
            "implementedThisCampaign": False,
            "reason": "no hard remote boot dependencies remain",
        }
    if gate == "browser_offline_partial_local_assets_ready":
        return {
            "strategy": "prepare_local_asset_patch",
            "implementedThisCampaign": False,
            "reason": "local assets appear present but HTML/server still need an explicit patch",
        }
    return {
        "strategy": "keep_online_boot_and_document_asset_policy_blocker",
        "implementedThisCampaign": False,
        "reason": "required local React/ReactDOM/Babel assets are not present and the desktop server does not serve static asset paths",
    }


def _product_decisions(summary: Mapping[str, object]) -> list[str]:
    decisions = []
    if int(summary.get("missingLocalVendorCandidateCount") or 0) > 0:
        decisions.append("approve_or_provide_exact_local_react_reactdom_babel_assets")
    if int(summary.get("remoteFontDependencyCount") or 0) > 0:
        decisions.append("choose_remote_fonts_vs_local_fonts_vs_system_font_fallback")
    if not summary.get("browserDesktopServesStaticAssetPaths"):
        decisions.append("approve_static_asset_serving_path_for_browser_desktop")
    if summary.get("usesRuntimeBabel"):
        decisions.append("choose_runtime_babel_vendoring_vs_precompiled_ui_build_pipeline")
    return decisions


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    payload = build_strict_offline_readiness(args.root)
    write_json(payload, args.output)
    if not args.quiet:
        print(f"gate: {payload['gateDecision']}")
        print(f"output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
