from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = Path("ui_readiness_outputs")
DEFAULT_OUTPUT_DIR = Path("ui_readiness_outputs")


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _latest_file(directory: Path, pattern: str) -> Path | None:
    root = _resolve(directory) or directory
    if not root.exists():
        return None
    candidates = sorted(root.glob(pattern), key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
    return candidates[0] if candidates else None


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _target_filename(url: str, dependency_kind: str) -> str:
    if dependency_kind == "react_cdn":
        return "react.development.js"
    if dependency_kind == "react_dom_cdn":
        return "react-dom.development.js"
    if dependency_kind == "babel_cdn":
        return "babel.min.js"
    if dependency_kind == "google_font":
        return "inter-jetbrains-mono.css"
    tail = url.rstrip("/").rsplit("/", 1)[-1] or dependency_kind
    return re.sub(r"[^A-Za-z0-9._-]+", "_", tail)


def _target_path(url: str, dependency_kind: str) -> str:
    if dependency_kind in {"react_cdn", "react_dom_cdn"}:
        directory = Path("app/vendor/react")
    elif dependency_kind == "babel_cdn":
        directory = Path("app/vendor/babel")
    elif dependency_kind == "google_font":
        directory = Path("app/vendor/fonts")
    else:
        directory = Path("app/vendor/ui")
    return str(directory / _target_filename(url, dependency_kind))


def build_manifest(
    audit_payload: Mapping[str, Any],
    plan_payload: Mapping[str, Any] | None = None,
    *,
    audit_path: Path | None = None,
    plan_path: Path | None = None,
) -> dict[str, Any]:
    plan_payload = plan_payload or {}
    audit_summary = audit_payload.get("summary") if isinstance(audit_payload.get("summary"), Mapping) else {}
    plan_summary = plan_payload.get("summary") if isinstance(plan_payload.get("summary"), Mapping) else {}
    dependency_rows = audit_payload.get("dependencyRows") if isinstance(audit_payload.get("dependencyRows"), list) else []
    asset_rows: list[dict[str, Any]] = []
    navigation_rows: list[dict[str, Any]] = []
    seen_targets: set[tuple[str, str]] = set()
    for row in dependency_rows:
        if not isinstance(row, Mapping):
            continue
        kind = str(row.get("dependencyKind") or "external_url")
        url = str(row.get("url") or "")
        source_file = str(row.get("file") or "")
        runtime_required = bool(row.get("runtimeRequiredForUiBoot"))
        analyst_navigation = bool(row.get("analystNavigationOnly"))
        if analyst_navigation:
            navigation_rows.append(
                {
                    "sourceFile": source_file,
                    "sourceUrl": url,
                    "dependencyKind": kind,
                    "runtimeRequiredForUiBoot": False,
                    "localAssetRequired": False,
                    "note": "Analyst navigation link; keep separate from UI boot dependencies.",
                }
            )
            continue
        if not runtime_required:
            continue
        target = _target_path(url, kind)
        dedupe_key = (url, target)
        if dedupe_key in seen_targets:
            continue
        seen_targets.add(dedupe_key)
        target_abs = _resolve(target) or Path(target)
        asset_rows.append(
            {
                "assetId": f"UI-ASSET-{len(asset_rows) + 1:03d}",
                "sourceUrl": url,
                "dependencyKind": kind,
                "sourceFiles": sorted(
                    {
                        str(candidate.get("file") or "")
                        for candidate in dependency_rows
                        if isinstance(candidate, Mapping)
                        and str(candidate.get("url") or "") == url
                        and bool(candidate.get("runtimeRequiredForUiBoot"))
                    }
                ),
                "suggestedLocalPath": target,
                "targetExistsNow": target_abs.exists(),
                "requiredForOfflineBoot": True,
                "implementationStatus": "not_vendored_manifest_only",
                "safeImplementationAllowedNow": False,
                "approvalRequiredBeforeRuntimeChange": True,
            }
        )
    asset_rows.sort(key=lambda item: (str(item.get("dependencyKind", "")), str(item.get("sourceUrl", ""))))
    missing_targets = [row for row in asset_rows if not row.get("targetExistsNow")]
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "ui_offline_asset_manifest",
        "sourceUiAuditPath": str(audit_path or ""),
        "sourceOfflinePlanPath": str(plan_path or ""),
        "summary": {
            "offlineRisk": audit_summary.get("offlineRisk", plan_summary.get("offlineRisk", "unknown")),
            "runtimeRequiredDependencyCount": audit_summary.get("runtimeRequiredDependencyCount", 0),
            "uniqueRuntimeAssetCount": len(asset_rows),
            "missingRuntimeAssetCount": len(missing_targets),
            "analystNavigationLinkCount": len(navigation_rows),
            "implementationApproved": False,
            "uiRuntimeChanged": False,
            "oldOutputsMutated": False,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
        },
        "assetRows": asset_rows,
        "analystNavigationRows": navigation_rows,
        "loaderBoundary": {
            "allowedNow": [
                "Use this manifest to scope a future UI-offline implementation.",
                "Reference suggested local paths in review/planning artifacts.",
                "Keep analyst external links separate from UI boot dependencies.",
            ],
            "requiresSeparateApproval": [
                "Downloading or vendoring CDN assets.",
                "Changing script/link tags in browser UI files.",
                "Adding a local-vs-CDN fallback loader.",
            ],
            "forbidden": [
                "Do not rewrite the browser UI as part of manifest generation.",
                "Do not change Python report payload contracts.",
                "Do not change scoring, gates, HER routing, funding eligibility, or candidate admission.",
            ],
        },
        "recommendedNextPrompt": (
            "Approve or reject a narrow UI-offline implementation patch. If approved, vendor only the manifest-listed "
            "runtime boot assets, add fallback loading without changing report payloads, and run browser/UI smoke checks."
        ),
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# UI Offline Asset Manifest",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Offline risk: {summary.get('offlineRisk', '')}",
        f"- Runtime dependencies: {summary.get('runtimeRequiredDependencyCount', 0)}",
        f"- Unique runtime assets: {summary.get('uniqueRuntimeAssetCount', 0)}",
        f"- Missing runtime assets: {summary.get('missingRuntimeAssetCount', 0)}",
        f"- Analyst navigation links: {summary.get('analystNavigationLinkCount', 0)}",
        f"- Implementation approved: {summary.get('implementationApproved', False)}",
        f"- UI runtime changed: {summary.get('uiRuntimeChanged', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Runtime Asset Rows",
    ]
    for row in payload.get("assetRows") or []:
        if isinstance(row, Mapping):
            lines.append(
                "- "
                f"`{row.get('assetId', '')}` {row.get('dependencyKind', '')}: "
                f"{row.get('sourceUrl', '')} -> `{row.get('suggestedLocalPath', '')}` "
                f"(exists now: {row.get('targetExistsNow', False)})"
            )
    lines.extend(["", "## Analyst Navigation Links"])
    for row in payload.get("analystNavigationRows") or []:
        if isinstance(row, Mapping):
            lines.append(f"- {row.get('dependencyKind', '')}: {row.get('sourceUrl', '')}")
    boundary = payload.get("loaderBoundary") if isinstance(payload.get("loaderBoundary"), Mapping) else {}
    lines.extend(["", "## Loader Boundary", "", "### Allowed Now"])
    for item in boundary.get("allowedNow") or []:
        lines.append(f"- {item}")
    lines.extend(["", "### Requires Separate Approval"])
    for item in boundary.get("requiresSeparateApproval") or []:
        lines.append(f"- {item}")
    lines.extend(["", "### Forbidden"])
    for item in boundary.get("forbidden") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Recommended Next Prompt", "", str(payload.get("recommendedNextPrompt", ""))])
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"ui_offline_asset_manifest_{stamp}.json"
    markdown_path = resolved / f"ui_offline_asset_manifest_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a manifest-only UI offline asset boundary from local audits.")
    parser.add_argument("--audit", type=Path, default=None)
    parser.add_argument("--plan", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    audit_path = args.audit or _latest_file(DEFAULT_INPUT_DIR, "ui_runtime_dependency_audit_*.json")
    plan_path = args.plan or _latest_file(DEFAULT_INPUT_DIR, "ui_offline_readiness_plan_*.json")
    payload = build_manifest(_load_json(audit_path), _load_json(plan_path), audit_path=audit_path, plan_path=plan_path)
    outputs = write_outputs(payload, args.output_dir)
    print(f"UI offline asset manifest JSON: {outputs['json_path']}")
    print(f"UI offline asset manifest markdown: {outputs['markdown_path']}")
    print(f"Unique runtime assets: {payload.get('summary', {}).get('uniqueRuntimeAssetCount', 0)}")
    print(f"UI runtime changed: {payload.get('summary', {}).get('uiRuntimeChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
