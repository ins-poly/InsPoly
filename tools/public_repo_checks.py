from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


FORBIDDEN_TRACKED_ROOTS = {
    "AI_CONTROL",
    "validation_outputs",
    "phase3_capital_review_packets",
    "rfcs",
    "skills",
    "release_manifests",
    "review_packets",
    "shadow_review_packets",
    "side_outcome_review_packets",
}

SECRET_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}",
        r"(?<![A-Za-z0-9_])ghp_[A-Za-z0-9_]{20,}",
        r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{20,}",
        r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}",
        r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}",
        r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----",
        r"(?m)^\s*(?:export\s+)?OPENAI_API_KEY\s*=\s*[^<\s#'\"]",
        r"(?m)^\s*(?:export\s+)?(?:SECRET|SECRET_KEY|API_SECRET|CLOB_SECRET)\s*=\s*[^<\s#'\"]",
        r"(?m)^\s*(?:export\s+)?(?:TOKEN|API_TOKEN|ACCESS_TOKEN|GITHUB_TOKEN|GH_TOKEN)\s*=\s*[^<\s#'\"]",
        r"(?m)^\s*(?:export\s+)?PASSWORD\s*=\s*[^<\s#'\"]",
    )
]

LOCAL_PATH_PATTERNS = [
    re.compile("/" + "Users" + r"/(?!<local-user-home>)"),
    re.compile("/" + "home" + r"/(?!<local-user-home>)"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run public repository hygiene checks.")
    parser.add_argument("--json", action="store_true", help="Parse tracked JSON files.")
    parser.add_argument("--secrets", action="store_true", help="Scan tracked text for obvious secrets/local paths.")
    parser.add_argument("--generated", action="store_true", help="Reject tracked internal/generated roots.")
    parser.add_argument("--docs-links", action="store_true", help="Check local Markdown links in tracked docs.")
    parser.add_argument("--all", action="store_true", help="Run all checks.")
    args = parser.parse_args(argv)

    selected = args.all or not any((args.json, args.secrets, args.generated, args.docs_links))
    checks = []
    if selected or args.json:
        checks.append(check_tracked_json)
    if selected or args.secrets:
        checks.append(check_tracked_secrets)
    if selected or args.generated:
        checks.append(check_generated_roots)
    if selected or args.docs_links:
        checks.append(check_docs_links)

    failures: list[str] = []
    for check in checks:
        failures.extend(check())
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("public repo checks passed")
    return 0


def check_tracked_json() -> list[str]:
    failures: list[str] = []
    for path in _tracked_files():
        if not path.endswith(".json"):
            continue
        try:
            json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"invalid JSON: {path}: {exc}")
    return failures


def check_tracked_secrets() -> list[str]:
    failures: list[str] = []
    for path in _tracked_files():
        file_path = Path(path)
        if _is_probably_binary_or_vendor(path):
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                failures.append(f"possible secret in tracked file: {path}")
                break
        for pattern in LOCAL_PATH_PATTERNS:
            if pattern.search(text):
                failures.append(f"local machine path in tracked file: {path}")
                break
    return failures


def check_generated_roots() -> list[str]:
    failures: list[str] = []
    for path in _tracked_files():
        root = path.split("/", 1)[0]
        if root in FORBIDDEN_TRACKED_ROOTS:
            failures.append(f"public main must not track internal/generated root: {path}")
    return failures


def check_docs_links() -> list[str]:
    failures: list[str] = []
    for path in _tracked_files():
        if not path.endswith(".md"):
            continue
        markdown_path = Path(path)
        try:
            text = markdown_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if _is_external_or_anchor(target):
                continue
            clean = target.split("#", 1)[0]
            if not clean:
                continue
            linked = (markdown_path.parent / clean).resolve()
            if not linked.exists():
                failures.append(f"broken local markdown link in {path}: {target}")
    return failures


def _tracked_files() -> list[str]:
    result = subprocess.run(["git", "ls-files"], check=True, capture_output=True, text=True)
    return [line for line in result.stdout.splitlines() if line.strip() and Path(line).exists()]


def _is_probably_binary_or_vendor(path: str) -> bool:
    if path.startswith("app/vendor/"):
        return True
    return Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".pyc"}


def _is_external_or_anchor(target: str) -> bool:
    lowered = target.lower()
    return (
        lowered.startswith("#")
        or lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("mailto:")
    )


if __name__ == "__main__":
    raise SystemExit(main())
