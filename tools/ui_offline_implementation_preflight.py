from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
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


def _status(
    *,
    runtime_dependency_count: int,
    unique_asset_count: int,
    missing_asset_count: int,
    implementation_approved: bool,
) -> str:
    if runtime_dependency_count <= 0 and unique_asset_count <= 0:
        return "no_runtime_dependencies_detected"
    if missing_asset_count > 0:
        return "blocked_missing_runtime_assets"
    if not implementation_approved:
        return "assets_present_approval_required"
    return "ready_for_bounded_ui_offline_smoke"


def build_preflight(
    audit_payload: Mapping[str, Any] | None = None,
    plan_payload: Mapping[str, Any] | None = None,
    manifest_payload: Mapping[str, Any] | None = None,
    *,
    audit_path: Path | None = None,
    plan_path: Path | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    audit_payload = audit_payload or {}
    plan_payload = plan_payload or {}
    manifest_payload = manifest_payload or {}
    audit_summary = audit_payload.get("summary") if isinstance(audit_payload.get("summary"), Mapping) else {}
    plan_summary = plan_payload.get("summary") if isinstance(plan_payload.get("summary"), Mapping) else {}
    manifest_summary = manifest_payload.get("summary") if isinstance(manifest_payload.get("summary"), Mapping) else {}
    asset_rows = manifest_payload.get("assetRows") if isinstance(manifest_payload.get("assetRows"), list) else []
    preflight_rows: list[dict[str, Any]] = []
    for row in asset_rows:
        if not isinstance(row, Mapping):
            continue
        target = str(row.get("suggestedLocalPath") or "")
        resolved_target = _resolve(target)
        target_exists_now = bool(row.get("targetExistsNow")) or bool(resolved_target and resolved_target.exists())
        preflight_rows.append(
            {
                "assetId": row.get("assetId", ""),
                "dependencyKind": row.get("dependencyKind", ""),
                "suggestedLocalPath": target,
                "targetExistsNow": target_exists_now,
                "requiredForOfflineBoot": bool(row.get("requiredForOfflineBoot", True)),
                "approvalRequiredBeforeRuntimeChange": bool(row.get("approvalRequiredBeforeRuntimeChange", True)),
                "sourceFiles": list(row.get("sourceFiles") or []),
                "implementationStatus": "present_not_wired" if target_exists_now else "missing_not_vendored",
            }
        )
    runtime_dependency_count = int(
        manifest_summary.get(
            "runtimeRequiredDependencyCount",
            audit_summary.get("runtimeRequiredDependencyCount", plan_summary.get("runtimeRequiredDependencyCount", 0)),
        )
        or 0
    )
    unique_asset_count = len(preflight_rows) or int(manifest_summary.get("uniqueRuntimeAssetCount", 0) or 0)
    missing_asset_count = sum(1 for row in preflight_rows if row["requiredForOfflineBoot"] and not row["targetExistsNow"])
    if not preflight_rows:
        missing_asset_count = int(manifest_summary.get("missingRuntimeAssetCount", 0) or 0)
    implementation_approved = bool(
        manifest_summary.get("implementationApproved") or plan_summary.get("implementationApproved")
    )
    preflight_status = _status(
        runtime_dependency_count=runtime_dependency_count,
        unique_asset_count=unique_asset_count,
        missing_asset_count=missing_asset_count,
        implementation_approved=implementation_approved,
    )
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "ui_offline_implementation_preflight",
        "sourceUiAuditPath": str(audit_path or ""),
        "sourceOfflinePlanPath": str(plan_path or ""),
        "sourceAssetManifestPath": str(manifest_path or ""),
        "summary": {
            "preflightStatus": preflight_status,
            "offlineRisk": manifest_summary.get(
                "offlineRisk",
                audit_summary.get("offlineRisk", plan_summary.get("offlineRisk", "unknown")),
            ),
            "runtimeRequiredDependencyCount": runtime_dependency_count,
            "uniqueRuntimeAssetCount": unique_asset_count,
            "missingRuntimeAssetCount": missing_asset_count,
            "existingRuntimeAssetCount": sum(1 for row in preflight_rows if row["targetExistsNow"]),
            "implementationApproved": implementation_approved,
            "approvalRequiredBeforeRuntimeChange": not implementation_approved,
            "uiRuntimeChanged": False,
            "oldOutputsMutated": False,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
        },
        "assetPreflightRows": preflight_rows,
        "stopConditions": [
            "Stop before downloading or vendoring assets without explicit UI implementation approval.",
            "Stop before changing browser UI script/link tags without explicit approval.",
            "Stop before changing Python report payload contracts.",
            "Stop before changing detector scoring, gates, HER routing, funding eligibility, or candidate admission.",
        ],
        "readyToCopyNextPrompt": (
            "Approve a bounded UI-offline implementation patch only if local offline boot is now a priority. "
            "If approved, inspect ui_readiness_outputs/ui_offline_implementation_preflight_*.json, vendor only "
            "the listed missing runtime boot assets, add local fallback loading, and verify scanner/archive/event "
            "browser UIs still load saved reports. Do not change scoring, gates, HER routing, funding eligibility, "
            "candidate admission, old outputs, credentials, or RPC URLs."
        ),
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# UI Offline Implementation Preflight",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Preflight status: {summary.get('preflightStatus', '')}",
        f"- Offline risk: {summary.get('offlineRisk', '')}",
        f"- Runtime dependencies: {summary.get('runtimeRequiredDependencyCount', 0)}",
        f"- Unique runtime assets: {summary.get('uniqueRuntimeAssetCount', 0)}",
        f"- Missing runtime assets: {summary.get('missingRuntimeAssetCount', 0)}",
        f"- Implementation approved: {summary.get('implementationApproved', False)}",
        f"- UI runtime changed: {summary.get('uiRuntimeChanged', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Asset Preflight Rows",
    ]
    for row in payload.get("assetPreflightRows") or []:
        if isinstance(row, Mapping):
            lines.append(
                "- "
                f"`{row.get('assetId', '')}` {row.get('dependencyKind', '')}: "
                f"`{row.get('suggestedLocalPath', '')}` exists={row.get('targetExistsNow', False)} "
                f"status={row.get('implementationStatus', '')}"
            )
    lines.extend(["", "## Stop Conditions"])
    for item in payload.get("stopConditions") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Ready-To-Copy Next Prompt", "", str(payload.get("readyToCopyNextPrompt", ""))])
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"ui_offline_implementation_preflight_{stamp}.json"
    markdown_path = resolved / f"ui_offline_implementation_preflight_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight UI-offline implementation readiness without changing UI files.")
    parser.add_argument("--audit", type=Path, default=None)
    parser.add_argument("--plan", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    audit_path = args.audit or _latest_file(DEFAULT_INPUT_DIR, "ui_runtime_dependency_audit_*.json")
    plan_path = args.plan or _latest_file(DEFAULT_INPUT_DIR, "ui_offline_readiness_plan_*.json")
    manifest_path = args.manifest or _latest_file(DEFAULT_INPUT_DIR, "ui_offline_asset_manifest_*.json")
    payload = build_preflight(
        _load_json(audit_path),
        _load_json(plan_path),
        _load_json(manifest_path),
        audit_path=audit_path,
        plan_path=plan_path,
        manifest_path=manifest_path,
    )
    outputs = write_outputs(payload, args.output_dir)
    print(f"UI offline implementation preflight JSON: {outputs['json_path']}")
    print(f"UI offline implementation preflight markdown: {outputs['markdown_path']}")
    print(f"Preflight status: {payload.get('summary', {}).get('preflightStatus', '')}")
    print(f"UI runtime changed: {payload.get('summary', {}).get('uiRuntimeChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
