from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("schema_normalization_outputs")
SEARCH_PATTERNS = (
    (Path("review_packets"), "unique_review_packets_*.json", "unique_review_packets"),
    (Path("ai_review_outputs"), "AI_CASE_REVIEW_CASES_*.json", "case_reviewer_cases"),
    (Path("validation_corpus_outputs"), "corpus_provenance_drilldown_*.json", "corpus_provenance_drilldown"),
    (Path("strong_risk_diagnostic_outputs"), "strong_risk_gate_diagnostic_*.json", "strong_risk_diagnostic"),
)

FIELD_ALIASES = {
    "wallet": ("wallet", "walletAddress", "wallet_address"),
    "market": ("market", "event", "question"),
    "condition_id": ("conditionId", "condition_id"),
    "trade_id": ("tradeId", "trade_id", "row_id", "txHash", "transactionHash"),
    "hard_evidence_sources": ("hardEvidenceSources", "hard_evidence_sources", "hard_evidence_sources"),
    "suppressors": ("suppressors", "strongRiskSuppressorConflictReasons", "strong_risk_suppressor_conflict_reasons"),
    "gate_type": ("strongRiskGateType", "strong_risk_gate_type", "gateFamily", "gate_family"),
    "gate_branch": ("strongRiskExactGateBranch", "strong_risk_exact_gate_branch", "gateName", "gate_name"),
    "composition": ("strongRiskCompositionClass", "strong_risk_composition_class", "gate_family"),
}


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _latest_files(directory: Path, pattern: str, limit: int) -> list[Path]:
    root = _resolve(directory) or directory
    if not root.exists():
        return []
    return sorted(root.glob(pattern), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)[:limit]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _iter_rows(payload: Mapping[str, Any], source_kind: str) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for key in ("packets", "case_packets", "topManualInspectionRows", "topPotentialGateLeakageCandidates"):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, Mapping))
    stratified = payload.get("stratifiedExamples")
    if isinstance(stratified, Mapping):
        for value in stratified.values():
            if isinstance(value, list):
                rows.extend(row for row in value if isinstance(row, Mapping))
    if source_kind == "case_reviewer_cases":
        rows.extend(row for row in payload.get("reviews", []) if isinstance(row, Mapping))
    return rows


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, list | tuple | set):
        return bool(value)
    return str(value).strip().lower() not in {"", "unknown", "none", "null", "[]"}


def _alias_presence(row: Mapping[str, Any], aliases: Sequence[str]) -> list[str]:
    keys = set(row.keys())
    lower = {str(key).lower(): key for key in keys}
    present: list[str] = []
    for alias in aliases:
        actual = alias if alias in row else lower.get(alias.lower())
        if actual is not None and _present(row.get(actual)):
            present.append(str(actual))
    return present


def discover_paths(limit_per_kind: int = 3) -> list[tuple[Path, str]]:
    paths: list[tuple[Path, str]] = []
    for directory, pattern, kind in SEARCH_PATTERNS:
        paths.extend((path, kind) for path in _latest_files(directory, pattern, limit_per_kind))
    return paths


def build_schema_normalization_check(paths: Sequence[tuple[Path, str]]) -> dict[str, Any]:
    alias_counts: dict[str, Counter[str]] = defaultdict(Counter)
    missing_by_field: Counter[str] = Counter()
    by_artifact: dict[str, Counter[str]] = defaultdict(Counter)
    examples: list[dict[str, Any]] = []
    rows_inspected = 0

    for path, kind in paths:
        payload = _load_json(path)
        for row in _iter_rows(payload, kind):
            rows_inspected += 1
            artifact = path.name
            by_artifact[artifact]["rows"] += 1
            missing: list[str] = []
            for field, aliases in FIELD_ALIASES.items():
                present_aliases = _alias_presence(row, aliases)
                if present_aliases:
                    for alias in present_aliases:
                        alias_counts[field][alias] += 1
                else:
                    missing_by_field[field] += 1
                    by_artifact[artifact][f"missing_{field}"] += 1
                    missing.append(field)
            if missing and len(examples) < 50:
                examples.append(
                    {
                        "artifact": artifact,
                        "source_kind": kind,
                        "missing_fields": missing,
                        "available_keys": sorted(str(key) for key in row.keys())[:40],
                    }
                )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "input_paths": [str(path) for path, _ in paths],
            "rows_inspected": rows_inspected,
            "missing_by_field": dict(missing_by_field),
            "artifact_count": len(by_artifact),
        },
        "alias_usage": {field: dict(counter) for field, counter in sorted(alias_counts.items())},
        "by_artifact": {artifact: dict(counter) for artifact, counter in sorted(by_artifact.items())},
        "examples": examples,
        "limitations": [
            "This check validates read-only field availability and alias coverage.",
            "It does not rewrite legacy artifacts.",
            "It does not change scoring, gates, labels, HER routing, or funding eligibility.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Review Schema Normalization Check",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Rows inspected: {summary.get('rows_inspected', 0)}",
        f"- Artifact count: {summary.get('artifact_count', 0)}",
        "",
        "## Missing By Canonical Field",
    ]
    for key, value in sorted((summary.get("missing_by_field") or {}).items(), key=lambda item: (-int(item[1]), item[0])):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Alias Usage"])
    for field, aliases in (payload.get("alias_usage") or {}).items():
        lines.append(f"- {field}: {aliases}")
    lines.extend(["", "## Examples"])
    for example in (payload.get("examples") or [])[:25]:
        lines.append(f"- {example.get('artifact', '')} missing={example.get('missing_fields', [])}")
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"review_schema_normalization_check_{stamp}.json"
    md_path = resolved / f"review_schema_normalization_check_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(md_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check saved review schema alias normalization.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit-per-kind", type=int, default=3)
    args = parser.parse_args(argv)
    payload = build_schema_normalization_check(discover_paths(limit_per_kind=args.limit_per_kind))
    outputs = write_outputs(payload, args.output_dir)
    print(f"Review schema normalization JSON: {outputs['json_path']}")
    print(f"Review schema normalization markdown: {outputs['markdown_path']}")
    print(f"Rows inspected: {payload.get('summary', {}).get('rows_inspected', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
