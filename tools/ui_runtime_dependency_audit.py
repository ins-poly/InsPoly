from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("ui_readiness_outputs")
DEFAULT_INPUTS = (
    Path("app/browser_ui.html"),
    Path("app/browser_event_forensic_ui.html"),
    Path("app/browser_desktop.py"),
    Path("app/event_forensic_desktop.py"),
)
URL_RE = re.compile(r"https?://[^'\"\s)>]+")


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _read(path: Path) -> str:
    resolved = _resolve(path) or path
    try:
        return resolved.read_text(encoding="utf-8")
    except OSError:
        return ""


def _dependency_kind(url: str) -> str:
    if "fonts.googleapis.com" in url:
        return "google_font"
    if "unpkg.com/react-dom" in url:
        return "react_dom_cdn"
    if "unpkg.com/react" in url:
        return "react_cdn"
    if "babel" in url:
        return "babel_cdn"
    if "polymarket.com" in url:
        return "analyst_external_link"
    if "polygonscan.com" in url:
        return "analyst_external_link"
    if "127.0.0.1" in url or "localhost" in url:
        return "local_server"
    return "external_url"


def build_audit(input_paths: Sequence[Path] = DEFAULT_INPUTS) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in input_paths:
        resolved = _resolve(path) or path
        text = _read(path)
        urls = sorted(set(URL_RE.findall(text)))
        for url in urls:
            kind = _dependency_kind(url)
            rows.append(
                {
                    "file": str(resolved),
                    "url": url,
                    "dependencyKind": kind,
                    "runtimeRequiredForUiBoot": kind in {"google_font", "react_cdn", "react_dom_cdn", "babel_cdn"},
                    "analystNavigationOnly": kind == "analyst_external_link",
                }
            )
    runtime_required = [row for row in rows if row["runtimeRequiredForUiBoot"]]
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "ui_runtime_dependency_audit",
        "summary": {
            "fileCount": len(input_paths),
            "externalUrlCount": len(rows),
            "runtimeRequiredDependencyCount": len(runtime_required),
            "cdnRuntimeDependencyCount": sum(1 for row in runtime_required if row["dependencyKind"].endswith("_cdn")),
            "googleFontDependencyCount": sum(1 for row in rows if row["dependencyKind"] == "google_font"),
            "analystExternalLinkCount": sum(1 for row in rows if row["analystNavigationOnly"]),
            "offlineRisk": "high" if runtime_required else "low",
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
        },
        "dependencyRows": rows,
        "recommendedActions": _recommended_actions(runtime_required),
    }


def _recommended_actions(runtime_required: Sequence[Mapping[str, Any]]) -> list[str]:
    if runtime_required:
        return [
            "Document runtime CDN dependency clearly for offline/restricted-network operators.",
            "If offline UI is required, create a separate approved vendoring task; do not change app behavior from this audit.",
            "Keep analyst external links separate from UI boot dependencies.",
        ]
    return [
        "Keep local browser boot assets pinned with provenance.",
        "Keep analyst external links separate from UI boot dependencies.",
        "Do not add new hard remote boot dependencies without updating strict-offline readiness tests.",
    ]


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# UI Runtime Dependency Audit",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Files inspected: {summary.get('fileCount', 0)}",
        f"- External URLs: {summary.get('externalUrlCount', 0)}",
        f"- Runtime-required dependencies: {summary.get('runtimeRequiredDependencyCount', 0)}",
        f"- Offline risk: {summary.get('offlineRisk', '')}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Runtime Dependencies",
    ]
    for row in payload.get("dependencyRows") or []:
        if isinstance(row, Mapping) and row.get("runtimeRequiredForUiBoot"):
            lines.append(f"- `{row.get('dependencyKind', '')}` {row.get('url', '')} in {row.get('file', '')}")
    lines.extend(["", "## Recommended Actions"])
    for item in payload.get("recommendedActions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"ui_runtime_dependency_audit_{stamp}.json"
    markdown_path = resolved / f"ui_runtime_dependency_audit_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit UI runtime dependencies without changing frontend behavior.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    payload = build_audit()
    outputs = write_outputs(payload, args.output_dir)
    print(f"UI runtime dependency audit JSON: {outputs['json_path']}")
    print(f"UI runtime dependency audit markdown: {outputs['markdown_path']}")
    print(f"Offline risk: {payload.get('summary', {}).get('offlineRisk', '')}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
