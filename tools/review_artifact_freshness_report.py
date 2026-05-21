from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("artifact_manifests")
INPUT_PATTERNS = {
    "review_output_index": (Path("review_index_outputs"), "review_output_index_*.json"),
    "artifact_manifest": (Path("artifact_manifests"), "review_artifact_manifest_*.json"),
    "analyst_handoff_bundle": (Path("analyst_review_bundles"), "analyst_review_bundle_*.json"),
}


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


def discover_inputs() -> dict[str, Path | None]:
    return {name: _latest_file(directory, pattern) for name, (directory, pattern) in INPUT_PATTERNS.items()}


def _summary(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("summary")
    return value if isinstance(value, Mapping) else {}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def build_freshness_report(payloads: Mapping[str, Mapping[str, Any]], *, input_paths: Mapping[str, Path | None] | None = None) -> dict[str, Any]:
    index_payload = payloads.get("review_output_index", {})
    manifest_payload = payloads.get("artifact_manifest", {})
    bundle_payload = payloads.get("analyst_handoff_bundle", {})
    index_summary = _summary(index_payload)
    manifest_summary = _summary(manifest_payload)
    bundle_summary = _summary(bundle_payload)
    latest_by_kind = index_summary.get("latest_by_kind") if isinstance(index_summary.get("latest_by_kind"), Mapping) else {}
    entries = index_payload.get("entries") if isinstance(index_payload.get("entries"), list) else []
    entry_rows = []
    now = datetime.now(UTC)
    stale_count = 0
    missing_count = 0
    for kind, path_text in latest_by_kind.items():
        path = _resolve(str(path_text)) if path_text else None
        exists = bool(path and path.exists())
        modified_at = ""
        age_seconds: int | None = None
        if exists and path:
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            modified_at = modified.isoformat()
            age_seconds = int((now - modified).total_seconds())
        if not exists:
            missing_count += 1
        if age_seconds is not None and age_seconds > 86400:
            stale_count += 1
        entry_rows.append(
            {
                "kind": str(kind),
                "path": str(path_text or ""),
                "exists": exists,
                "modifiedAt": modified_at,
                "ageSeconds": age_seconds,
                "staleOver24h": bool(age_seconds is not None and age_seconds > 86400),
            }
        )
    related_reference_count = int(index_summary.get("related_reference_count") or 0)
    paths = input_paths or {}
    return {
        "generatedAt": now.isoformat(),
        "inputPaths": {key: str(value) if value else "" for key, value in paths.items()},
        "summary": {
            "indexedKindCount": len(latest_by_kind),
            "indexEntryCount": len(entries),
            "missingLatestArtifactCount": missing_count,
            "staleOver24hCount": stale_count,
            "relatedReferenceCount": related_reference_count,
            "manifestArtifactCount": manifest_summary.get("artifact_count", 0),
            "manifestMissingArtifactCount": manifest_summary.get("missing_artifact_count", 0),
            "manifestHashCoveredArtifactCount": manifest_summary.get("hash_covered_artifact_count", 0),
            "bundlePacketCount": bundle_summary.get("packet_count", 0),
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "candidateAdmissionChanged": False,
            "oldOutputsMutated": False,
        },
        "latestArtifactRows": sorted(entry_rows, key=lambda row: (not row["exists"], row["kind"])),
        "navigationHealth": {
            "indexExists": bool(paths.get("review_output_index") and paths["review_output_index"].exists()),
            "manifestExists": bool(paths.get("artifact_manifest") and paths["artifact_manifest"].exists()),
            "bundleExists": bool(paths.get("analyst_handoff_bundle") and paths["analyst_handoff_bundle"].exists()),
            "relatedReferencesPresent": related_reference_count > 0,
            "readyForAnalystHandoff": missing_count == 0 and bool(latest_by_kind),
        },
        "limitations": [
            "Freshness is based on local artifact timestamps only.",
            "This report does not mutate old outputs or validate production detector behavior.",
            "Stale reporting artifacts do not imply stale detector logic.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    health = payload.get("navigationHealth") if isinstance(payload.get("navigationHealth"), Mapping) else {}
    lines = [
        "# Review Artifact Freshness Report",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Indexed kinds: {summary.get('indexedKindCount', 0)}",
        f"- Index entries: {summary.get('indexEntryCount', 0)}",
        f"- Missing latest artifacts: {summary.get('missingLatestArtifactCount', 0)}",
        f"- Stale over 24h: {summary.get('staleOver24hCount', 0)}",
        f"- Ready for analyst handoff: {health.get('readyForAnalystHandoff', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Latest Artifact Rows",
    ]
    for row in payload.get("latestArtifactRows") or []:
        if isinstance(row, Mapping):
            lines.append(
                f"- `{row.get('kind', '')}`: exists={row.get('exists', False)}, "
                f"staleOver24h={row.get('staleOver24h', False)}, path={row.get('path', '')}"
            )
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"review_artifact_freshness_report_{stamp}.json"
    markdown_path = resolved / f"review_artifact_freshness_report_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a read-only review artifact freshness/navigation report.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    paths = discover_inputs()
    payload = build_freshness_report({name: _load_json(path) for name, path in paths.items()}, input_paths=paths)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Review artifact freshness JSON: {outputs['json_path']}")
    print(f"Review artifact freshness markdown: {outputs['markdown_path']}")
    print(f"Missing latest artifacts: {payload.get('summary', {}).get('missingLatestArtifactCount', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
