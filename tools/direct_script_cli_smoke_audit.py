from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("tooling_audit_outputs")


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


def _is_argparse_cli(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return "argparse.ArgumentParser" in text and 'if __name__ == "__main__"' in text


def _smoke_help(path: Path, *, cwd: Path, per_tool_timeout_seconds: float) -> dict[str, Any]:
    command = [sys.executable, str(path), "--help"]
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=per_tool_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "path": str(path),
            "command": " ".join(command),
            "status": "help_timeout",
            "returnCode": "",
            "stdoutPreview": (exc.stdout or "")[:400] if isinstance(exc.stdout, str) else "",
            "stderrPreview": (exc.stderr or "")[:400] if isinstance(exc.stderr, str) else "",
            "recommendedAction": "Inspect direct --help startup path and reduce import-time side effects or timeout risk.",
        }
    except OSError as exc:
        return {
            "path": str(path),
            "command": " ".join(command),
            "status": "help_os_error",
            "returnCode": "",
            "stdoutPreview": "",
            "stderrPreview": type(exc).__name__,
            "recommendedAction": "Inspect script path and direct CLI availability.",
        }

    output = f"{completed.stdout}\n{completed.stderr}".lower()
    help_ok = completed.returncode == 0 and "usage:" in output
    return {
        "path": str(path),
        "command": " ".join(command),
        "status": "help_ok" if help_ok else "help_failed",
        "returnCode": completed.returncode,
        "stdoutPreview": completed.stdout[:400],
        "stderrPreview": completed.stderr[:400],
        "recommendedAction": (
            "No direct --help action required."
            if help_ok
            else "Inspect argparse startup path; direct --help should exit 0 and show usage."
        ),
    }


def build_audit(
    tools_dir: Path = Path("tools"),
    *,
    repo_root: Path = REPO_ROOT,
    per_tool_timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    resolved_repo = _resolve(repo_root) or repo_root
    candidate_paths = [path for path in _tool_files(tools_dir) if _is_argparse_cli(path)]
    smoke_rows = [
        _smoke_help(path, cwd=resolved_repo, per_tool_timeout_seconds=per_tool_timeout_seconds)
        for path in candidate_paths
    ]
    ok_count = sum(1 for row in smoke_rows if row.get("status") == "help_ok")
    failure_count = sum(1 for row in smoke_rows if row.get("status") == "help_failed")
    timeout_count = sum(1 for row in smoke_rows if row.get("status") == "help_timeout")
    os_error_count = sum(1 for row in smoke_rows if row.get("status") == "help_os_error")
    risk_status = "direct_cli_help_ok" if failure_count + timeout_count + os_error_count == 0 else "direct_cli_help_issues"
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "direct_script_cli_smoke_audit",
        "toolsDir": str(_resolve(tools_dir) or tools_dir),
        "summary": {
            "argparseCliCandidateCount": len(candidate_paths),
            "helpOkCount": ok_count,
            "helpFailureCount": failure_count,
            "helpTimeoutCount": timeout_count,
            "helpOsErrorCount": os_error_count,
            "directCliRiskStatus": risk_status,
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "networkCallsIntended": False,
        },
        "smokeRows": smoke_rows,
        "issueRows": [row for row in smoke_rows if row.get("status") != "help_ok"],
        "limitations": [
            "This audit runs --help only for argparse CLIs with a main guard.",
            "It does not run validation, RPC calls, scanner analysis, or report mutation beyond its own output files.",
            "A passing --help smoke does not prove the tool's main workflow succeeds.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Direct Script CLI Smoke Audit",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Argparse CLI candidates: {summary.get('argparseCliCandidateCount', 0)}",
        f"- Help OK: {summary.get('helpOkCount', 0)}",
        f"- Help failures: {summary.get('helpFailureCount', 0)}",
        f"- Help timeouts: {summary.get('helpTimeoutCount', 0)}",
        f"- Direct CLI risk status: {summary.get('directCliRiskStatus', 'unknown')}",
        f"- Network calls intended: {summary.get('networkCallsIntended', False)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Issue Rows",
    ]
    issues = payload.get("issueRows") if isinstance(payload.get("issueRows"), list) else []
    if not issues:
        lines.append("- none")
    for row in issues:
        if isinstance(row, Mapping):
            lines.append(
                f"- `{row.get('path', '')}` status={row.get('status', '')} "
                f"return={row.get('returnCode', '')}: {row.get('recommendedAction', '')}"
            )
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"direct_script_cli_smoke_audit_{stamp}.json"
    markdown_path = resolved / f"direct_script_cli_smoke_audit_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded --help smoke checks for local argparse tools.")
    parser.add_argument("--tools-dir", type=Path, default=Path("tools"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--per-tool-timeout-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)
    payload = build_audit(args.tools_dir, per_tool_timeout_seconds=args.per_tool_timeout_seconds)
    outputs = write_outputs(payload, args.output_dir)
    summary = payload.get("summary", {})
    print(f"Direct script CLI smoke audit JSON: {outputs['json_path']}")
    print(f"Direct script CLI smoke audit markdown: {outputs['markdown_path']}")
    print(f"Direct CLI risk status: {summary.get('directCliRiskStatus', '')}")
    print(f"Help failures: {summary.get('helpFailureCount', 0)}")
    print(f"Help timeouts: {summary.get('helpTimeoutCount', 0)}")
    print(f"Model behavior changed: {summary.get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
