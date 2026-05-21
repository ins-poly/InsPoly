from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = Path("known_case_benchmarks")
DEFAULT_OUTPUT_DIR = Path("known_case_benchmarks")
LABEL_FIELDS = (
    "expectedAnalystDisposition",
    "expectedDetectorDisposition",
    "humanLabelConfidence",
    "humanFalsePositiveReason",
    "humanInsiderStyleReason",
    "freshValidationRequired",
    "notes",
)


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


def _rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("benchmarkRows")
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def build_workbench(payload: Mapping[str, Any], *, source_path: Path | None = None, limit: int = 150) -> dict[str, Any]:
    source_rows = _rows(payload)[:limit]
    rows = []
    for row in source_rows:
        labels = {field: "" for field in LABEL_FIELDS}
        labels["freshValidationRequired"] = "yes"
        rows.append(
            {
                "localCaseId": row.get("localCaseId", ""),
                "sourceType": row.get("sourceType", ""),
                "sourceArtifact": row.get("sourceArtifact", ""),
                "eventSlug": row.get("eventSlug", ""),
                "market": row.get("market", ""),
                "conditionId": row.get("conditionId", ""),
                "wallet": row.get("wallet", ""),
                "observedLabels": row.get("observedLabels", {}),
                "benchmarkStatus": "awaiting_human_label",
                "labelFields": labels,
                "allowedUse": "manual_review_and_future_regression_expectation_only",
                "forbiddenUse": "Do not use labels to change production scoring, gates, HER routing, funding eligibility, or admission without separate approval.",
                "modelBehaviorChanged": False,
            }
        )
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "benchmark_labeling_workbench",
        "sourceBenchmarkPath": str(source_path or ""),
        "summary": {
            "sourceRowCount": len(source_rows),
            "labelTemplateRowCount": len(rows),
            "requiredLabelFieldCount": len(LABEL_FIELDS),
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "herRoutingChanged": False,
            "fundingEligibilityChanged": False,
            "oldOutputsMutated": False,
        },
        "labelFieldDefinitions": {
            "expectedAnalystDisposition": "human triage bucket, e.g. likely_false_positive / plausible_insider_style / needs_fresh_validation",
            "expectedDetectorDisposition": "future expected detector behavior after approval, not current production change",
            "humanLabelConfidence": "low / medium / high",
            "humanFalsePositiveReason": "why the case may be benign or public-power-user behavior",
            "humanInsiderStyleReason": "why the case may be high-value suspicious behavior",
            "freshValidationRequired": "yes/no, default yes because current evidence is saved/cache-only",
            "notes": "free-form analyst notes",
        },
        "labelRows": rows,
        "limitations": [
            "This workbench is a labeling template only.",
            "It does not mark rows as truth automatically.",
            "It does not change production detector behavior.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Benchmark Labeling Workbench",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Source rows: {summary.get('sourceRowCount', 0)}",
        f"- Label template rows: {summary.get('labelTemplateRowCount', 0)}",
        f"- Model behavior changed: {summary.get('modelBehaviorChanged', False)}",
        "",
        "## Label Fields",
    ]
    definitions = payload.get("labelFieldDefinitions") if isinstance(payload.get("labelFieldDefinitions"), Mapping) else {}
    for field, description in definitions.items():
        lines.append(f"- `{field}`: {description}")
    lines.extend(["", "## First Rows"])
    for row in (payload.get("labelRows") or [])[:25]:
        if isinstance(row, Mapping):
            lines.append(f"- `{row.get('localCaseId', '')}` {row.get('sourceType', '')}: {row.get('eventSlug') or row.get('market') or 'unknown'}")
    return "\n".join(lines).rstrip() + "\n"


def _write_csv(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    fieldnames = [
        "localCaseId",
        "sourceType",
        "eventSlug",
        "market",
        "conditionId",
        "wallet",
        *LABEL_FIELDS,
        "sourceArtifact",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            labels = row.get("labelFields") if isinstance(row.get("labelFields"), Mapping) else {}
            writer.writerow(
                {
                    "localCaseId": row.get("localCaseId", ""),
                    "sourceType": row.get("sourceType", ""),
                    "eventSlug": row.get("eventSlug", ""),
                    "market": row.get("market", ""),
                    "conditionId": row.get("conditionId", ""),
                    "wallet": row.get("wallet", ""),
                    **{field: labels.get(field, "") for field in LABEL_FIELDS},
                    "sourceArtifact": row.get("sourceArtifact", ""),
                }
            )


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"benchmark_labeling_workbench_{stamp}.json"
    markdown_path = resolved / f"benchmark_labeling_workbench_{stamp}.md"
    csv_path = resolved / f"benchmark_labeling_workbench_{stamp}.csv"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    _write_csv([row for row in payload.get("labelRows", []) if isinstance(row, Mapping)], csv_path)
    return {"json_path": str(json_path), "markdown_path": str(markdown_path), "csv_path": str(csv_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a human-labeling workbench from the local known-case benchmark scaffold.")
    parser.add_argument("--benchmark", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    source = args.benchmark or _latest_file(DEFAULT_INPUT_DIR, "local_known_case_benchmark_*.json")
    payload = build_workbench(_load_json(source), source_path=source)
    outputs = write_outputs(payload, args.output_dir)
    print(f"Benchmark labeling workbench JSON: {outputs['json_path']}")
    print(f"Benchmark labeling workbench markdown: {outputs['markdown_path']}")
    print(f"Benchmark labeling workbench CSV: {outputs['csv_path']}")
    print(f"Rows: {payload.get('summary', {}).get('labelTemplateRowCount', 0)}")
    print(f"Model behavior changed: {payload.get('summary', {}).get('modelBehaviorChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
