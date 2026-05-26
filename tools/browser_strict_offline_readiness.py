#!/usr/bin/env python3
"""Build a strict-offline readiness inventory for browser UI assets."""

from __future__ import annotations

import argparse
import hashlib
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
    "react": Path("app/vendor/browser/react/18.3.1/react.development.js"),
    "react_dom": Path("app/vendor/browser/react-dom/18.3.1/react-dom.development.js"),
    "babel": Path("app/vendor/browser/babel-standalone/7.29.7/babel.min.js"),
}
PROVENANCE_MANIFEST = Path("app/vendor/browser/PROVENANCE.json")


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

    provenance = _provenance_manifest(base)
    local_assets = _local_asset_rows(base, provenance)
    server = _server_capabilities(base, html_files)
    summary = _summary(html_rows, dependencies, local_assets, server, provenance)
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
        "vendorProvenance": provenance,
        "browserDesktopLauncher": server,
        "productDecisionsNeeded": _product_decisions(summary),
        "invariantsPreserved": [
            "no_scoring_or_model_changes",
            "no_phase3_runtime",
            "no_storage_schema_changes",
            "no_ui_sorting_filtering_changes",
            "no_saved_artifact_mutation",
            "vendored_assets_are_pinned_and_provenance_recorded",
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
        is_remote = _is_remote(reference)
        local_path = _resolve_local_reference(base, html_path, reference) if not is_remote else None
        rows.append(
            {
                "htmlFile": str(html_path),
                "tag": tag,
                "reference": reference,
                "isRemote": is_remote,
                "assetKind": kind,
                "riskClass": _risk_class(kind, is_remote=is_remote),
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
    if "/vendor/browser/react-dom/" in lower:
        return "react_dom_runtime"
    if "/vendor/browser/react/" in lower:
        return "react_runtime"
    if "/vendor/browser/babel-standalone/" in lower:
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


def _risk_class(kind: str, *, is_remote: bool) -> str:
    if kind in {"react_runtime", "react_dom_runtime", "babel_runtime"}:
        return "hard_offline_boot_blocker" if is_remote else "local_boot_runtime_asset"
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
        if reference.startswith("/vendor/browser/"):
            return base / "app" / reference.lstrip("/")
        return base / reference.lstrip("/")
    return base / html_path.parent / reference


def _is_remote(reference: str) -> bool:
    return reference.startswith(("http://", "https://"))


def _local_asset_rows(base: Path, provenance: Mapping[str, object]) -> list[dict[str, object]]:
    manifest_assets = {
        str(row.get("localPath") or ""): row
        for row in provenance.get("assets", [])
        if isinstance(row, Mapping)
    }
    rows = []
    for name, path in LOCAL_VENDOR_CANDIDATES.items():
        resolved = base / path
        manifest_row = manifest_assets.get(str(path))
        digest = _sha256(resolved) if resolved.exists() else ""
        expected_digest = str(manifest_row.get("sha256") or "") if isinstance(manifest_row, Mapping) else ""
        expected_size = manifest_row.get("sizeBytes") if isinstance(manifest_row, Mapping) else None
        size = resolved.stat().st_size if resolved.exists() else None
        rows.append(
            {
                "name": name,
                "path": str(path),
                "exists": resolved.exists(),
                "sizeBytes": size,
                "sha256": digest,
                "manifestEntryPresent": bool(manifest_row),
                "manifestSha256Matches": bool(expected_digest and digest == expected_digest),
                "manifestSizeMatches": bool(size is not None and expected_size == size),
                "sourcePolicyStatus": _asset_policy_status(resolved.exists(), bool(manifest_row), digest, expected_digest, size, expected_size),
            }
        )
    return rows


def _asset_policy_status(
    exists: bool,
    manifest_entry_present: bool,
    digest: str,
    expected_digest: str,
    size: int | None,
    expected_size: object,
) -> str:
    if not exists:
        return "not_vendored"
    if not manifest_entry_present:
        return "present_missing_provenance"
    if digest != expected_digest or size != expected_size:
        return "present_provenance_mismatch"
    return "present_pinned_with_provenance"


def _provenance_manifest(base: Path) -> dict[str, object]:
    path = base / PROVENANCE_MANIFEST
    if not path.exists():
        return {"path": str(PROVENANCE_MANIFEST), "exists": False, "validJson": False, "assetCount": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(PROVENANCE_MANIFEST), "exists": True, "validJson": False, "assetCount": 0}
    assets = payload.get("assets") if isinstance(payload, Mapping) else None
    return {
        "path": str(PROVENANCE_MANIFEST),
        "exists": True,
        "validJson": isinstance(payload, Mapping),
        "schemaVersion": payload.get("schemaVersion") if isinstance(payload, Mapping) else "",
        "assetCount": len(assets) if isinstance(assets, list) else 0,
        "assets": assets if isinstance(assets, list) else [],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _server_capabilities(base: Path, html_files: Sequence[str | Path]) -> dict[str, object]:
    requires_event_server = any(str(path).endswith("browser_event_forensic_ui.html") for path in html_files)
    browser_server = _server_row(base, Path("app/browser_desktop.py"))
    event_server = _server_row(base, Path("app/event_forensic_desktop.py"))
    return {
        "servesStaticAssetPaths": bool(browser_server.get("servesStaticAssetPaths"))
        and (not requires_event_server or bool(event_server.get("servesStaticAssetPaths"))),
        "browserDesktop": browser_server,
        "eventForensicDesktop": event_server,
        "requiresEventForensicDesktop": requires_event_server,
    }


def _server_row(base: Path, relative_path: Path) -> dict[str, object]:
    source_path = base / relative_path
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError:
        return {
            "path": str(relative_path),
            "exists": False,
            "servesRootHtml": False,
            "servesApiJson": False,
            "servesStaticAssetPaths": False,
        }
    serves_static = "load_browser_vendor_asset" in source and "is_browser_vendor_asset_path" in source
    return {
        "path": str(relative_path),
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
    provenance: Mapping[str, object],
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
    unverified_candidates = [row for row in local_assets if row.get("sourcePolicyStatus") != "present_pinned_with_provenance"]
    inline_babel_count = sum(int(row.get("inlineBabelScriptCount") or 0) for row in html_rows)
    local_babel_ready = any(row.get("name") == "babel" and row.get("sourcePolicyStatus") == "present_pinned_with_provenance" for row in local_assets)
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
        "unverifiedLocalVendorCandidateCount": len(unverified_candidates),
        "provenanceManifestExists": bool(provenance.get("exists")),
        "provenanceManifestValid": bool(provenance.get("validJson")),
        "provenanceAssetCount": int(provenance.get("assetCount") or 0),
        "inlineBabelScriptCount": inline_babel_count,
        "usesRuntimeBabel": inline_babel_count > 0,
        "browserDesktopServesStaticAssetPaths": bool(server.get("servesStaticAssetPaths")),
        "strictOfflineBootPossibleNow": (
            not hard_remote
            and not remote_fonts
            and not missing_candidates
            and not unverified_candidates
            and bool(server.get("servesStaticAssetPaths"))
            and bool(provenance.get("validJson"))
        ),
        "strictOfflineBootBlockedBy": _blocked_by(
            hard_remote,
            remote_fonts,
            missing_candidates,
            unverified_candidates,
            server,
            inline_babel_count,
            local_babel_ready,
            provenance,
        ),
    }


def _blocked_by(
    hard_remote: Sequence[Mapping[str, object]],
    remote_fonts: Sequence[Mapping[str, object]],
    missing_candidates: Sequence[Mapping[str, object]],
    unverified_candidates: Sequence[Mapping[str, object]],
    server: Mapping[str, object],
    inline_babel_count: int,
    local_babel_ready: bool,
    provenance: Mapping[str, object],
) -> list[str]:
    blockers: list[str] = []
    if hard_remote:
        blockers.append("remote_react_reactdom_babel_boot_assets")
    if missing_candidates:
        blockers.append("missing_local_vendor_asset_candidates")
    if unverified_candidates:
        blockers.append("local_vendor_asset_provenance_missing_or_mismatch")
    if not provenance.get("validJson"):
        blockers.append("vendor_provenance_manifest_missing_or_invalid")
    if not server.get("servesStaticAssetPaths"):
        blockers.append("browser_desktop_static_asset_serving_not_implemented")
    if remote_fonts:
        blockers.append("remote_google_font_stylesheets")
    if inline_babel_count and not local_babel_ready:
        blockers.append("inline_text_babel_requires_babel_runtime_or_build_pipeline")
    return blockers


def _gate(summary: Mapping[str, object]) -> str:
    if summary.get("strictOfflineBootPossibleNow"):
        return "browser_strict_offline_ready"
    if (
        int(summary.get("remoteHardBootDependencyCount") or 0) == 0
        and int(summary.get("missingLocalVendorCandidateCount") or 0) == 0
        and int(summary.get("unverifiedLocalVendorCandidateCount") or 0) == 0
    ):
        return "browser_offline_partial_local_assets_ready"
    if summary.get("usesRuntimeBabel") and int(summary.get("remoteHardBootDependencyCount") or 0) > 0:
        return "browser_offline_blocked_requires_asset_policy"
    return "browser_offline_no_safe_change"


def _strategy(summary: Mapping[str, object]) -> dict[str, object]:
    gate = _gate(summary)
    if gate == "browser_strict_offline_ready":
        return {
            "strategy": "strict_offline_ready",
            "implementedThisCampaign": True,
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
    if int(summary.get("unverifiedLocalVendorCandidateCount") or 0) > 0 or not summary.get("provenanceManifestValid"):
        decisions.append("fix_local_vendor_asset_provenance")
    if int(summary.get("remoteFontDependencyCount") or 0) > 0:
        decisions.append("choose_remote_fonts_vs_local_fonts_vs_system_font_fallback")
    if not summary.get("browserDesktopServesStaticAssetPaths"):
        decisions.append("approve_static_asset_serving_path_for_browser_desktop")
    if summary.get("usesRuntimeBabel") and not summary.get("strictOfflineBootPossibleNow"):
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
