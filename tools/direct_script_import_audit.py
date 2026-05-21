from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("tooling_audit_outputs")
IMPORT_RE = re.compile(r"^\s*(?:from\s+(app|tools)(?:\.|\s+import)|import\s+(app|tools)(?:[.\s,]|$))")
PATH_GUARD_RE = re.compile(r"sys\.path\.(?:insert|append)\s*\(.*(?:REPO_ROOT|Path\(__file__\).*parents\[1\])")


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _tool_files(tools_dir: Path) -> list[Path]:
    root = _resolve(tools_dir) or tools_dir
    if not root.exists():
        return []
    return sorted(path for path in root.glob("*.py") if path.name != "__init__.py")


def _scan_file(path: Path) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        load_error = ""
    except (OSError, UnicodeDecodeError) as exc:
        lines = []
        load_error = type(exc).__name__

    import_rows: list[dict[str, Any]] = []
    first_repo_import_line = 0
    for index, line in enumerate(lines, start=1):
        match = IMPORT_RE.match(line)
        if not match:
            continue
        root_package = match.group(1) or match.group(2) or ""
        if first_repo_import_line <= 0:
            first_repo_import_line = index
        import_rows.append(
            {
                "line": index,
                "rootPackage": root_package,
                "statement": line.strip(),
            }
        )

    guard_before_import = False
    if first_repo_import_line > 0:
        preceding = "\n".join(lines[: first_repo_import_line - 1])
        guard_before_import = bool(PATH_GUARD_RE.search(preceding))

    has_main_guard = any('if __name__ == "__main__"' in line or "if __name__ == '__main__'" in line for line in lines)
    app_or_tools_import_count = len(import_rows)
    missing_guard = app_or_tools_import_count > 0 and not guard_before_import
    return {
        "path": str(path),
        "loadError": load_error,
        "hasRepoRootImport": app_or_tools_import_count > 0,
        "repoRootImportCount": app_or_tools_import_count,
        "firstRepoRootImportLine": first_repo_import_line,
        "hasRepoRootPathGuardBeforeImport": guard_before_import,
        "missingRepoRootPathGuard": missing_guard,
        "hasMainGuard": has_main_guard,
        "importRows": import_rows,
        "directRunRisk": "missing_repo_root_path_guard" if missing_guard else "none_observed",
        "recommendedAction": (
            "Add the existing REPO_ROOT sys.path guard before app/tools imports."
            if missing_guard
            else "No direct-run import guard action required."
        ),
    }


def build_audit(tools_dir: Path = Path("tools")) -> dict[str, Any]:
    tool_rows = [_scan_file(path) for path in _tool_files(tools_dir)]
    repo_import_rows = [row for row in tool_rows if row["hasRepoRootImport"]]
    missing_guard_rows = [row for row in repo_import_rows if row["missingRepoRootPathGuard"]]
    direct_run_risk_status = "missing_repo_root_path_guards" if missing_guard_rows else "repo_root_import_guards_ok"
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "direct_script_import_audit",
        "toolsDir": str(_resolve(tools_dir) or tools_dir),
        "summary": {
            "toolFileCount": len(tool_rows),
            "repoRootImportToolCount": len(repo_import_rows),
            "guardedRepoRootImportToolCount": sum(1 for row in repo_import_rows if row["hasRepoRootPathGuardBeforeImport"]),
            "missingGuardToolCount": len(missing_guard_rows),
            "directRunRiskStatus": direct_run_risk_status,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
        },
        "toolRows": tool_rows,
        "missingGuardRows": missing_guard_rows,
        "limitations": [
            "This audit scans static Python import text only.",
            "It does not execute tools and does not prove all runtime dependencies are available.",
            "It does not change model behavior, scoring, gates, HER routing, funding eligibility, or saved outputs.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Direct Script Import Audit",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Tool files inspected: {summary.get('toolFileCount', 0)}",
        f"- Tools with `app`/`tools` imports: {summary.get('repoRootImportToolCount', 0)}",
        f"- Guarded import tools: {summary.get('guardedRepoRootImportToolCount', 0)}",
        f"- Missing guard tools: {summary.get('missingGuardToolCount', 0)}",
        f"- Direct-run risk status: {summary.get('directRunRiskStatus', 'unknown')}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Missing Guard Rows",
    ]
    missing = payload.get("missingGuardRows") if isinstance(payload.get("missingGuardRows"), list) else []
    if not missing:
        lines.append("- none")
    for row in missing:
        if isinstance(row, Mapping):
            lines.append(
                f"- `{row.get('path', '')}` first import line {row.get('firstRepoRootImportLine', 0)}: "
                f"{row.get('recommendedAction', '')}"
            )
    lines.extend(["", "## Repo Root Import Tools"])
    for row in payload.get("toolRows") or []:
        if isinstance(row, Mapping) and row.get("hasRepoRootImport"):
            lines.append(
                f"- `{row.get('path', '')}` imports={row.get('repoRootImportCount', 0)} "
                f"guarded={row.get('hasRepoRootPathGuardBeforeImport', False)} "
                f"risk={row.get('directRunRisk', '')}"
            )
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"direct_script_import_audit_{stamp}.json"
    markdown_path = resolved / f"direct_script_import_audit_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit direct-run import guards for tools that import app/tools modules.")
    parser.add_argument("--tools-dir", type=Path, default=Path("tools"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    payload = build_audit(args.tools_dir)
    outputs = write_outputs(payload, args.output_dir)
    summary = payload.get("summary", {})
    print(f"Direct script import audit JSON: {outputs['json_path']}")
    print(f"Direct script import audit markdown: {outputs['markdown_path']}")
    print(f"Direct-run risk status: {summary.get('directRunRiskStatus', '')}")
    print(f"Missing guard tools: {summary.get('missingGuardToolCount', 0)}")
    print(f"Model behavior changed: {summary.get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
