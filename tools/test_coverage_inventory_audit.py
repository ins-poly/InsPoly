from __future__ import annotations

import argparse
import ast
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("tooling_audit_outputs")
HIGH_PRIORITY_APP_MODULES = {
    "scanner",
    "archive_scanner",
    "event_forensic",
    "funding_context",
    "polymarket",
    "event_context",
    "config",
}


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _module_files(root: Path, package: str) -> list[Path]:
    directory = _resolve(root / package) or (root / package)
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.py") if path.name != "__init__.py")


def _test_files(root: Path) -> list[Path]:
    directory = _resolve(root / "tests") or (root / "tests")
    if not directory.exists():
        return []
    return sorted(directory.glob("test_*.py"))


def _module_name(path: Path, package: str) -> str:
    return f"{package}.{path.stem}"


def _imports_from_test(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(("app.", "tools.")):
                    imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith(("app.", "tools.")):
                imports.add(node.module)
    return imports


def _module_rows(module_paths: Sequence[Path], package: str, test_imports_by_file: Mapping[str, set[str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in module_paths:
        module = _module_name(path, package)
        referenced_by = sorted(
            test_path
            for test_path, imports in test_imports_by_file.items()
            if module in imports or any(imported.startswith(f"{module}.") for imported in imports)
        )
        rows.append(
            {
                "module": module,
                "path": str(path),
                "testReferenceCount": len(referenced_by),
                "referencedByTests": referenced_by,
                "hasDirectTestReference": bool(referenced_by),
                "highPriority": package == "app" and path.stem in HIGH_PRIORITY_APP_MODULES,
            }
        )
    return rows


def build_audit(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    resolved_root = _resolve(repo_root) or repo_root
    app_paths = _module_files(resolved_root, "app")
    tool_paths = _module_files(resolved_root, "tools")
    tests = _test_files(resolved_root)
    test_imports_by_file = {str(path): _imports_from_test(path) for path in tests}
    app_rows = _module_rows(app_paths, "app", test_imports_by_file)
    tool_rows = _module_rows(tool_paths, "tools", test_imports_by_file)
    unreferenced_app_rows = [row for row in app_rows if not row["hasDirectTestReference"]]
    unreferenced_high_priority_app_rows = [row for row in unreferenced_app_rows if row["highPriority"]]
    coverage_status = (
        "high_priority_app_modules_unreferenced"
        if unreferenced_high_priority_app_rows
        else "direct_test_references_observed_for_high_priority_app_modules"
    )
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "test_coverage_inventory_audit",
        "repoRoot": str(resolved_root),
        "summary": {
            "testFileCount": len(tests),
            "appModuleCount": len(app_rows),
            "appModuleWithDirectTestReferenceCount": sum(1 for row in app_rows if row["hasDirectTestReference"]),
            "appModuleWithoutDirectTestReferenceCount": len(unreferenced_app_rows),
            "highPriorityAppModuleWithoutDirectTestReferenceCount": len(unreferenced_high_priority_app_rows),
            "toolModuleCount": len(tool_rows),
            "toolModuleWithDirectTestReferenceCount": sum(1 for row in tool_rows if row["hasDirectTestReference"]),
            "coverageInventoryStatus": coverage_status,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
        },
        "appModuleRows": app_rows,
        "toolModuleRows": tool_rows,
        "unreferencedHighPriorityAppModules": unreferenced_high_priority_app_rows,
        "limitations": [
            "This is a static import inventory, not executable branch coverage.",
            "A module can be exercised indirectly even when this audit does not see a direct import.",
            "The audit does not modify tests, production behavior, scoring, gates, or saved outputs.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Test Coverage Inventory Audit",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Test files: {summary.get('testFileCount', 0)}",
        f"- App modules: {summary.get('appModuleCount', 0)}",
        f"- App modules with direct test references: {summary.get('appModuleWithDirectTestReferenceCount', 0)}",
        f"- High-priority app modules without direct test references: {summary.get('highPriorityAppModuleWithoutDirectTestReferenceCount', 0)}",
        f"- Tool modules: {summary.get('toolModuleCount', 0)}",
        f"- Tool modules with direct test references: {summary.get('toolModuleWithDirectTestReferenceCount', 0)}",
        f"- Coverage inventory status: {summary.get('coverageInventoryStatus', 'unknown')}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Unreferenced High-Priority App Modules",
    ]
    rows = payload.get("unreferencedHighPriorityAppModules") if isinstance(payload.get("unreferencedHighPriorityAppModules"), list) else []
    if not rows:
        lines.append("- none")
    for row in rows:
        if isinstance(row, Mapping):
            lines.append(f"- `{row.get('module', '')}`: {row.get('path', '')}")
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"test_coverage_inventory_audit_{stamp}.json"
    markdown_path = resolved / f"test_coverage_inventory_audit_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory direct test references to app/tools modules.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    payload = build_audit(args.repo_root)
    outputs = write_outputs(payload, args.output_dir)
    summary = payload.get("summary", {})
    print(f"Test coverage inventory audit JSON: {outputs['json_path']}")
    print(f"Test coverage inventory audit markdown: {outputs['markdown_path']}")
    print(f"Coverage inventory status: {summary.get('coverageInventoryStatus', '')}")
    print(
        "High-priority app modules without direct test references: "
        f"{summary.get('highPriorityAppModuleWithoutDirectTestReferenceCount', 0)}"
    )
    print(f"Model behavior changed: {summary.get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
