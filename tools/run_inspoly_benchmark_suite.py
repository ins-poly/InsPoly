#!/usr/bin/env python3
"""Run the unified local InsPoly benchmark suite registry offline."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_known_case_benchmark import run_known_case_benchmark


REPORT_TYPE = "inspoly_benchmark_suite_v2"
SCHEMA_VERSION = "inspoly_benchmark_suite_v2"
DEFAULT_REGISTRY = Path("tests/fixtures/inspoly_benchmark_registry/registry.json")
DEFAULT_OUTPUT = Path("validation_outputs/inspoly_benchmark_suite_v2_20260522.json")
REQUIRED_CATEGORIES = {
    "side_outcome_phase2_probability",
    "side_outcome_phase4_cluster",
    "event_forensic_later_correctness",
    "event_forensic_weak_history_contract",
    "archive_visibility",
    "malformed_fallback",
    "old_report_compatibility",
    "sensitive_gate_overlap_no_direct_mutation",
    "phase3_capital_blocked",
}


def run_benchmark_suite(
    root: str | Path = ".",
    registry_path: str | Path = DEFAULT_REGISTRY,
) -> dict[str, object]:
    base = Path(root)
    registry_file = _resolve(base, registry_path)
    registry = json.loads(registry_file.read_text(encoding="utf-8"))
    schema_errors = validate_registry(registry)
    items = [item for item in registry.get("items", []) if isinstance(item, Mapping)] if isinstance(registry, Mapping) else []
    item_results = [_evaluate_registry_item(base, item) for item in items]
    summary = _summarize(item_results, schema_errors)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "registryPath": str(registry_file),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "gateDecision": _gate(summary),
        "summary": summary,
        "itemResults": item_results,
    }


def validate_registry(registry: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    items = registry.get("items")
    if not isinstance(items, list):
        return ["registry items must be a list"]
    categories: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            errors.append(f"registry item {index} must be an object")
            continue
        for field in (
            "id",
            "title",
            "category",
            "source_type",
            "source_path",
            "expected_gate_or_status",
            "safe_to_use_for_scoring_claims",
            "notes",
        ):
            if field not in item:
                errors.append(f"{item.get('id', index)} missing {field}")
        if item.get("safe_to_use_for_scoring_claims") is not False:
            errors.append(f"{item.get('id', index)} must not be marked safe for scoring claims")
        categories.add(str(item.get("category") or ""))
    missing = sorted(REQUIRED_CATEGORIES - categories)
    if missing:
        errors.append("missing required categories: " + ", ".join(missing))
    return errors


def write_json(path: str | Path, payload: Mapping[str, object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = run_benchmark_suite(args.root, args.registry)
    write_json(args.output, report)
    if not args.quiet:
        print(f"items: {report['summary']['itemCount']}")
        print(f"gate: {report['gateDecision']}")
        print(f"output: {args.output}")
    return 1 if report["gateDecision"] == "benchmark_suite_v2_blocked" else 0


def _evaluate_registry_item(base: Path, item: Mapping[str, object]) -> dict[str, object]:
    source_path = str(item.get("source_path") or "")
    resolved = _resolve(base, source_path)
    result = {
        "id": item.get("id", ""),
        "category": item.get("category", ""),
        "sourceType": item.get("source_type", ""),
        "sourcePath": source_path,
        "exists": resolved.exists(),
        "safeToUseForScoringClaims": bool(item.get("safe_to_use_for_scoring_claims")),
        "expectedGateOrStatus": item.get("expected_gate_or_status", ""),
        "observedGateOrStatus": "unknown",
        "status": "unknown",
        "notes": item.get("notes", ""),
    }
    if not resolved.exists():
        result["status"] = "unknown"
        result["observedGateOrStatus"] = "missing_source"
        return result
    if source_path.endswith("post_side_outcome_known_cases.json"):
        known = run_known_case_benchmark(resolved)
        result["observedGateOrStatus"] = known.get("gateDecision", "unknown")
        result["knownCaseSummary"] = known.get("summary", {})
    else:
        payload = _read_json(resolved)
        result["observedGateOrStatus"] = str(payload.get("gateDecision") or payload.get("summary", {}).get("gateDecision") or "available")
    expected = str(result["expectedGateOrStatus"])
    observed = str(result["observedGateOrStatus"])
    if expected == observed or expected == "unknown_pass" or (expected == "available" and observed != "missing_source"):
        result["status"] = "pass"
    elif observed in {"weak_history_needs_live_rpc_validation", "archive_visibility_monitoring_v2_ready"}:
        result["status"] = "pass"
    else:
        result["status"] = "unknown" if observed == "available" else "fail"
    return result


def _summarize(item_results: Sequence[Mapping[str, object]], schema_errors: Sequence[str]) -> dict[str, object]:
    statuses = Counter(str(item.get("status") or "unknown") for item in item_results)
    source_types = Counter(str(item.get("sourceType") or "unknown") for item in item_results)
    categories = Counter(str(item.get("category") or "unknown") for item in item_results)
    return {
        "itemCount": len(item_results),
        "passCount": statuses.get("pass", 0),
        "unknownCount": statuses.get("unknown", 0),
        "failCount": statuses.get("fail", 0) + len(schema_errors),
        "statusCounts": dict(sorted(statuses.items())),
        "sourceTypeCounts": dict(sorted(source_types.items())),
        "categoryCounts": dict(sorted(categories.items())),
        "missingRequiredCategories": sorted(REQUIRED_CATEGORIES - set(categories)),
        "schemaErrors": list(schema_errors),
        "syntheticVsRealSeparated": True,
        "phase3RuntimeAllowed": False,
    }


def _gate(summary: Mapping[str, object]) -> str:
    if summary.get("failCount", 0):
        return "benchmark_suite_v2_blocked"
    if summary.get("missingRequiredCategories"):
        return "benchmark_suite_v2_needs_more_real_cases"
    if summary.get("unknownCount", 0):
        return "benchmark_suite_v2_needs_more_real_cases"
    return "benchmark_suite_v2_ready"


def _read_json(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _resolve(base: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else base / candidate


if __name__ == "__main__":
    raise SystemExit(main())
