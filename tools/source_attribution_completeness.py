from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALIDATION_OUTPUT_DIR = Path("validation_corpus_outputs")
DEFAULT_STRONG_RISK_DIR = Path("strong_risk_diagnostic_outputs")
DEFAULT_REVIEW_PACKET_DIR = Path("review_packets")
DEFAULT_AI_REVIEW_DIR = Path("ai_review_outputs")
DEFAULT_OUTPUT_DIR = Path("source_attribution_outputs")

REQUIRED_FIELD_GROUPS = {
    "gate_branch": (
        "strongRiskExactGateBranch",
        "strong_risk_exact_gate_branch",
        "strong_risk_exact_gate_branch",
        "gateName",
        "gate_name",
        "strong_risk_exact_gate_branch",
    ),
    "gate_type": ("strongRiskGateType", "strong_risk_gate_type", "strong_risk_gate_type", "gateFamily", "gate_family"),
    "composition": (
        "strongRiskCompositionClass",
        "strong_risk_composition_class",
        "strong_risk_composition_class",
        "gate_family",
    ),
    "hard_evidence_sources": ("hardEvidenceSources", "hard_evidence_sources", "hard_evidence_sources"),
    "suppressors": ("suppressors", "strongRiskSuppressorConflictReasons", "strong_risk_suppressor_conflict_reasons"),
}

EMPTY_VALUES = {"", "unknown", "none", "null", "[]", "{}", "not_available"}


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _latest_file(directory: Path, pattern: str) -> Path | None:
    root = _resolve(directory) or directory
    if not root.exists():
        return None
    candidates = sorted(root.glob(pattern), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return candidates[0] if candidates else None


def _latest_files(directory: Path, pattern: str, limit: int) -> list[Path]:
    root = _resolve(directory) or directory
    if not root.exists():
        return []
    return sorted(root.glob(pattern), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)[:limit]


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _get(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row.get(key)
    lower_map = {str(key).lower(): key for key in row}
    for key in keys:
        actual = lower_map.get(key.lower())
        if actual is not None:
            return row.get(actual)
    return None


def _listify(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_listify(item))
        return result
    if isinstance(value, tuple | set):
        result = []
        for item in value:
            result.extend(_listify(item))
        return result
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped.replace("'", '"'))
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return _listify(parsed)
        return [part.strip() for part in stripped.split(",") if part.strip()]
    return [str(value).strip()]


def _present(value: Any) -> bool:
    if isinstance(value, list | tuple | set):
        return any(_present(item) for item in value)
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text.lower() not in EMPTY_VALUES


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _string(row: Mapping[str, Any], *keys: str) -> str:
    value = _get(row, *keys)
    return value.strip() if isinstance(value, str) else str(value).strip() if value is not None else ""


def _nested(row: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = _get(row, key)
    return value if isinstance(value, Mapping) else {}


def _row_id(row: Mapping[str, Any]) -> str:
    return (
        _string(row, "packet_id", "case_id", "tradeId", "trade_id", "row_id")
        or _string(row, "wallet")
        or _string(row, "sourceRow", "source_row")
        or "unknown"
    )


def _is_review_relevant(row: Mapping[str, Any]) -> bool:
    group = _string(row, "group")
    judgment = _string(row, "judgment", "severity")
    gate_type = _string(row, "strongRiskGateType", "strong_risk_gate_type", "strong_risk_gate_type", "gateFamily", "gate_family")
    hard_sources = _listify(_get(row, "hardEvidenceSources", "hard_evidence_sources", "hard_evidence_sources"))
    return (
        group in {"strong_risk", "hard_evidence_review", "overlap"}
        or "strong risk" in judgment.lower()
        or bool(hard_sources)
        or _present(gate_type)
    )


def _missing_fields(row: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    for group_name, keys in REQUIRED_FIELD_GROUPS.items():
        if not any(_present(_get(row, key)) for key in keys):
            missing.append(group_name)
    return missing


def _example(row: Mapping[str, Any], *, source_path: str, source_type: str, missing: Sequence[str]) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "source_path": source_path,
        "row_id": _row_id(row),
        "wallet": _string(row, "wallet"),
        "market": _string(row, "market", "event", "question"),
        "judgment": _string(row, "judgment", "severity"),
        "group": _string(row, "group"),
        "missing_fields": list(missing),
        "gate_type": _string(row, "strongRiskGateType", "strong_risk_gate_type", "strong_risk_gate_type", "gateFamily", "gate_family"),
        "gate_branch": _string(row, "strongRiskExactGateBranch", "strong_risk_exact_gate_branch", "strong_risk_exact_gate_branch", "gateName", "gate_name"),
        "hard_evidence_sources": _listify(_get(row, "hardEvidenceSources", "hard_evidence_sources", "hard_evidence_sources")),
        "suppressors": _listify(_get(row, "suppressors", "strongRiskSuppressorConflictReasons")),
    }


def _rows_from_review_packets(payload: Mapping[str, Any], source_path: Path) -> list[dict[str, Any]]:
    rows = payload.get("packets")
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows:
        if isinstance(row, Mapping):
            copied = dict(row)
            copied["_source_type"] = "unique_review_packet"
            copied["_source_path"] = str(source_path)
            result.append(copied)
    return result


def _rows_from_case_reviewer(payload: Mapping[str, Any], source_path: Path) -> list[dict[str, Any]]:
    reviews = {
        str(review.get("case_id")): review
        for review in payload.get("reviews", [])
        if isinstance(review, Mapping) and review.get("case_id")
    }
    rows = payload.get("case_packets")
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        copied = dict(row)
        copied["_source_type"] = "case_reviewer_packet"
        copied["_source_path"] = str(source_path)
        support = _nested(copied, "supporting_evidence")
        if "hardEvidenceSources" not in copied and "hard_evidence_sources" not in copied:
            copied["hardEvidenceSources"] = support.get("hard_evidence_sources") or support.get("hardEvidenceSources")
        review = reviews.get(str(copied.get("case_id")))
        if review and "suppressors" not in copied:
            copied["suppressors"] = _listify(review.get("evidence_that_weakens_concern"))
        result.append(copied)
    return result


def _rows_from_diagnostic(payload: Mapping[str, Any], source_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("topManualInspectionRows", "topPotentialGateLeakageCandidates"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for row in value:
            if isinstance(row, Mapping):
                copied = dict(row)
                copied["_source_type"] = key
                copied["_source_path"] = str(source_path)
                rows.append(copied)
    stratified = payload.get("stratifiedExamples")
    if isinstance(stratified, Mapping):
        for key, value in stratified.items():
            if not isinstance(value, list):
                continue
            for row in value:
                if isinstance(row, Mapping):
                    copied = dict(row)
                    copied["_source_type"] = f"stratifiedExamples.{key}"
                    copied["_source_path"] = str(source_path)
                    rows.append(copied)
    return rows


def discover_input_paths(
    *,
    review_packet_dir: Path = DEFAULT_REVIEW_PACKET_DIR,
    ai_review_dir: Path = DEFAULT_AI_REVIEW_DIR,
    validation_output_dir: Path = DEFAULT_VALIDATION_OUTPUT_DIR,
    strong_risk_dir: Path = DEFAULT_STRONG_RISK_DIR,
    max_case_reviewer_files: int = 10,
) -> dict[str, list[Path]]:
    paths = {
        "review_packets": [],
        "case_reviewer": [],
        "diagnostics": [],
    }
    packet = _latest_file(review_packet_dir, "unique_review_packets_*.json")
    if packet:
        paths["review_packets"].append(packet)
    paths["case_reviewer"].extend(_latest_files(ai_review_dir, "AI_CASE_REVIEW_CASES_*.json", max_case_reviewer_files))
    for candidate in (
        _latest_file(validation_output_dir, "corpus_provenance_drilldown_*.json"),
        _latest_file(strong_risk_dir, "strong_risk_gate_diagnostic_*.json"),
        _latest_file(validation_output_dir, "post_v2_corpus_audit_*.json"),
    ):
        if candidate:
            paths["diagnostics"].append(candidate)
    return paths


def _load_rows(paths: Mapping[str, Sequence[Path]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths.get("review_packets", []):
        rows.extend(_rows_from_review_packets(_load_json(path), path))
    for path in paths.get("case_reviewer", []):
        rows.extend(_rows_from_case_reviewer(_load_json(path), path))
    for path in paths.get("diagnostics", []):
        rows.extend(_rows_from_diagnostic(_load_json(path), path))
    return rows


def build_completeness_matrix(paths: Mapping[str, Sequence[Path]]) -> dict[str, Any]:
    rows = [row for row in _load_rows(paths) if _is_review_relevant(row)]
    by_artifact: dict[str, Counter[str]] = defaultdict(Counter)
    by_source_type: dict[str, Counter[str]] = defaultdict(Counter)
    missing_counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    complete_rows = 0

    for row in rows:
        missing = _missing_fields(row)
        source_path = str(row.get("_source_path") or "")
        source_type = str(row.get("_source_type") or "unknown")
        artifact_key = Path(source_path).name if source_path else "unknown"
        by_artifact[artifact_key]["rows"] += 1
        by_source_type[source_type]["rows"] += 1
        if missing:
            by_artifact[artifact_key]["rows_with_missing_fields"] += 1
            by_source_type[source_type]["rows_with_missing_fields"] += 1
            for field in missing:
                missing_counts[field] += 1
                by_artifact[artifact_key][f"missing_{field}"] += 1
                by_source_type[source_type][f"missing_{field}"] += 1
            if len(examples) < 50:
                examples.append(_example(row, source_path=source_path, source_type=source_type, missing=missing))
        else:
            complete_rows += 1

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "input_paths": [str(path) for values in paths.values() for path in values],
            "rows_inspected": len(rows),
            "complete_rows": complete_rows,
            "rows_with_missing_fields": len(rows) - complete_rows,
            "missing_field_counts": dict(missing_counts),
            "artifact_count": len(by_artifact),
        },
        "by_artifact": {key: dict(counter) for key, counter in sorted(by_artifact.items())},
        "by_source_type": {key: dict(counter) for key, counter in sorted(by_source_type.items())},
        "examples": examples,
        "limitations": [
            "This is a saved-artifact schema completeness diagnostic only.",
            "Missing fields in cache-only or legacy rows do not prove a model bug.",
            "No scoring, gate, severity, HER routing, or funding eligibility behavior is changed.",
        ],
        "invariants_preserved": [
            "_score_trade() unchanged",
            "Strong Risk gates unchanged",
            "scoring weights unchanged",
            "production severity labels unchanged",
            "Hard Evidence Review routing unchanged",
            "old saved outputs not mutated",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Source Attribution Completeness Matrix",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Rows inspected: {summary.get('rows_inspected', 0)}",
        f"- Complete rows: {summary.get('complete_rows', 0)}",
        f"- Rows with missing fields: {summary.get('rows_with_missing_fields', 0)}",
        f"- Artifact count: {summary.get('artifact_count', 0)}",
        "",
        "## Missing Field Counts",
    ]
    missing_counts = summary.get("missing_field_counts") if isinstance(summary.get("missing_field_counts"), Mapping) else {}
    if not missing_counts:
        lines.append("- none")
    for key, value in sorted(missing_counts.items(), key=lambda item: (-int(item[1]), item[0])):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## By Artifact"])
    for artifact, counts in (payload.get("by_artifact") or {}).items():
        lines.append(f"- {artifact}: {counts}")
    lines.extend(["", "## Examples"])
    examples = payload.get("examples") if isinstance(payload.get("examples"), list) else []
    if not examples:
        lines.append("- none")
    for example in examples[:25]:
        lines.append(
            f"- {example.get('source_type', '')} `{example.get('row_id', '')}` "
            f"missing={example.get('missing_fields', [])} wallet={example.get('wallet', '')} market={example.get('market', '')}"
        )
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Input Paths"])
    for path in summary.get("input_paths") or []:
        lines.append(f"- {path}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved_output_dir = _resolve(output_dir) or output_dir
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved_output_dir / f"source_attribution_completeness_{stamp}.json"
    markdown_path = resolved_output_dir / f"source_attribution_completeness_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a read-only source-attribution completeness matrix.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-case-reviewer-files", type=int, default=10)
    args = parser.parse_args(argv)
    paths = discover_input_paths(max_case_reviewer_files=args.max_case_reviewer_files)
    payload = build_completeness_matrix(paths)
    outputs = write_outputs(payload, args.output_dir)
    summary = payload.get("summary", {})
    print(f"Source attribution completeness JSON: {outputs['json_path']}")
    print(f"Source attribution completeness markdown: {outputs['markdown_path']}")
    print(f"Rows inspected: {summary.get('rows_inspected', 0)}")
    print(f"Rows with missing fields: {summary.get('rows_with_missing_fields', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
