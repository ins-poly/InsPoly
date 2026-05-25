#!/usr/bin/env python3
"""Archive-only evidence audit for Side/Outcome Phase 2.

This sidecar reads local archive artifacts and synthetic fixtures, then compares
current raw-token interpretation with hypothetical economic-side interpretation.
It does not import scanner/archive/Event Forensic runtime modules.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.side_outcome_phase2_impact_audit import evaluate_trade_record


REPORT_TYPE = "side_outcome_phase2_archive_evidence_gap"
SCHEMA_VERSION = "side_outcome_phase2_archive_evidence_v1"
SYNTHETIC_FIXTURE_DIR = Path("tests/fixtures/side_outcome_phase2_archive")
REAL_ARCHIVE_JSON_PATTERN = ".inspoly_archive_researcher/reports/archive_research_*.json"
REAL_ARCHIVE_OUTPUT_PATTERN = "archive_outputs/archive_research_*"
ARCHIVE_CSV_SUFFIXES = (
    "_trades.csv",
    "_candidates.csv",
    "_flagged.csv",
    "_secondary_review.csv",
    "_resolution_gap_cases.csv",
    "_yield_farm_cases.csv",
    "_theta_decay_cases.csv",
    "_off_hours_cases.csv",
    "_zombie_distortion_cases.csv",
    "_bot_like_cases.csv",
    "_domain_specialist_cases.csv",
)


def discover_archive_artifacts(root: str | Path = ".") -> list[dict[str, object]]:
    base = Path(root)
    refs: list[dict[str, object]] = []
    for path in sorted(base.glob(REAL_ARCHIVE_JSON_PATTERN)):
        if path.is_file():
            refs.append(_artifact_ref(base, path, family="archive_report_json", evidence_type="real_local"))
    for path in sorted(base.glob(REAL_ARCHIVE_OUTPUT_PATTERN)):
        if not path.is_file():
            continue
        if path.name.endswith("_excluded_hidden.json"):
            refs.append(_artifact_ref(base, path, family="archive_excluded_json", evidence_type="real_local"))
        elif path.suffix.lower() == ".csv" and any(path.name.endswith(suffix) for suffix in ARCHIVE_CSV_SUFFIXES):
            refs.append(_artifact_ref(base, path, family=_archive_csv_family(path), evidence_type="real_local"))
    for path in sorted((base / "tests/fixtures").glob("**/archive*.json")):
        if path.is_file() and SYNTHETIC_FIXTURE_DIR not in path.relative_to(base).parents:
            refs.append(_artifact_ref(base, path, family="archive_report_json", evidence_type="existing_test_fixture"))
    for path in sorted((base / "tests/fixtures").glob("**/archive*.csv")):
        if path.is_file() and SYNTHETIC_FIXTURE_DIR not in path.relative_to(base).parents:
            refs.append(_artifact_ref(base, path, family=_archive_csv_family(path), evidence_type="existing_test_fixture"))
    synthetic_root = base / SYNTHETIC_FIXTURE_DIR
    if synthetic_root.exists():
        for path in sorted(synthetic_root.glob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() == ".json":
                refs.append(_artifact_ref(base, path, family="archive_report_json", evidence_type="synthetic_fixture"))
            elif path.suffix.lower() == ".csv":
                refs.append(_artifact_ref(base, path, family=_archive_csv_family(path), evidence_type="synthetic_fixture"))
    return refs


def load_archive_records(
    artifacts: Sequence[Mapping[str, object]],
    *,
    max_files: int | None = None,
    max_rows_per_file: int | None = None,
    max_bytes: int | None = 5_000_000,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    records: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for index, artifact in enumerate(artifacts):
        if max_files is not None and index >= max_files:
            break
        path = Path(str(artifact["path"]))
        try:
            size = path.stat().st_size
        except OSError as exc:
            skipped.append({**artifact, "reason": f"stat_failed:{type(exc).__name__}"})
            continue
        if max_bytes is not None and size > max_bytes:
            skipped.append({**artifact, "reason": "file_too_large", "sizeBytes": size})
            continue
        if path.suffix.lower() == ".json":
            loaded = _records_from_archive_json(path, artifact=artifact, max_rows=max_rows_per_file)
        elif path.suffix.lower() == ".csv":
            loaded = _records_from_archive_csv(path, artifact=artifact, max_rows=max_rows_per_file)
        else:
            loaded = []
        records.extend(loaded)
    return records, skipped


def select_artifacts_for_scan(
    artifacts: Sequence[Mapping[str, object]],
    *,
    max_files: int | None = None,
) -> list[Mapping[str, object]]:
    """Return a bounded but balanced sidecar sample.

    Real archive outputs dominate the local workspace. A naive first-N slice can
    exclude the synthetic/fixture guardrails entirely, so keep fixtures in every
    bounded run and spread real artifacts across output families.
    """
    if max_files is None:
        return list(artifacts)
    fixtures = [item for item in artifacts if item.get("artifactEvidenceType") != "real_local"]
    real = [item for item in artifacts if item.get("artifactEvidenceType") == "real_local"]
    remaining = max(max_files - len(fixtures), 0)
    by_family: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for item in real:
        by_family[str(item.get("artifactFamily") or "unknown")].append(item)
    selected: list[Mapping[str, object]] = []
    family_names = sorted(by_family)
    while len(selected) < remaining:
        added = False
        for family in family_names:
            bucket = by_family[family]
            if not bucket:
                continue
            selected.append(bucket.pop(0))
            added = True
            if len(selected) >= remaining:
                break
        if not added:
            break
    return selected + fixtures


def build_archive_evidence_audit(
    records: Sequence[Mapping[str, object]],
    *,
    artifacts: Sequence[Mapping[str, object]] | None = None,
    discovered_artifacts: Sequence[Mapping[str, object]] | None = None,
    skipped_artifacts: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    evaluated: list[dict[str, object]] = []
    original_by_id: dict[tuple[str, int], Mapping[str, object]] = {}
    for record in records:
        original_by_id[(str(record.get("artifactPath") or ""), int(record.get("rowIndex") or 0))] = record
        item = evaluate_trade_record(record)
        item["artifactEvidenceType"] = record.get("artifactEvidenceType", "unknown")
        item["sourceCollection"] = record.get("sourceCollection", "")
        item["sourceShape"] = record.get("sourceShape", "")
        evaluated.append(item)
    selected_artifacts = artifacts or []
    all_discovered_artifacts = discovered_artifacts or selected_artifacts
    summary = _summary(
        records,
        evaluated,
        selected_artifacts,
        skipped_artifacts or [],
        discovered_count=len(all_discovered_artifacts),
    )
    gate_decision = _gate_decision(summary)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "implementationAllowed": False,
        "phase2RuntimeImplementationAllowed": False,
        "gateDecision": gate_decision,
        "summary": summary,
        "artifactInventory": _artifact_inventory(all_discovered_artifacts, skipped_artifacts or []),
        "affectedExamples": _examples(evaluated, require_change=True),
        "missingOrAmbiguousExamples": _examples(evaluated, require_notes=True),
        "compatibilityFindings": _compatibility_findings(summary),
        "implementationGuardrails": [
            "Use full archive JSON/trade-object fields or current in-memory Trade objects for Phase 2 model migration; do not rescore from lossy old flagged CSV rows.",
            "Keep old archive report keys and CSV columns raw-token and additive-only.",
            "Treat missing price/side/outcome in old archive CSV rows as unknown, not zero.",
            "Do not mutate saved archive reports or archive_outputs CSV files.",
            "Do not change archive visibility tiers, candidate admission, Strong Risk/HER/funding routing, sorting, or browser runtime behavior in this campaign.",
            "Keep Phase 3 capital-at-risk and Phase 4 cluster-direction normalization out of Phase 2.",
        ],
        "explicitBlocks": [
            "_score_trade() changes",
            "_event_forensic_score() changes",
            "production archive/scanner/Event Forensic behavior changes",
            "scoring weights, labels, Strong Risk, HER, funding eligibility, candidate admission, sorting, UI runtime, storage schema, or saved report compatibility changes",
            "saved report/artifact mutation",
            "Phase 2 runtime implementation",
            "Phase 3 capital-at-risk normalization",
            "Phase 4 cluster-direction normalization",
            "live/RPC/network behavior",
        ],
    }


def archive_evidence_markdown(report: Mapping[str, object]) -> str:
    summary = _mapping(report.get("summary"))
    evidence_counts = _mapping(summary.get("evidenceTypeCounts"))
    family_counts = _mapping(summary.get("artifactFamilyCounts"))
    field_counts = _mapping(summary.get("fieldCoverageCounts"))
    affected = _mapping(summary.get("affectedRows"))
    unique_affected = _mapping(summary.get("affectedUniqueTradeKeys"))
    missing = _mapping(summary.get("missingFieldTaxonomy"))
    lines = [
        "# InsPoly Side/Outcome Phase 2 Archive Evidence Gap",
        "",
        "- Date: 2026-05-22",
        "- Scope: sidecar-only archive evidence audit",
        "- Runtime implementation allowed: `false`",
        f"- Gate decision: `{report.get('gateDecision')}`",
        "",
        "## Summary",
        "",
        f"- Artifacts discovered: `{summary.get('artifactsDiscovered', 0)}`",
        f"- Artifacts selected for bounded scan: `{summary.get('artifactsSelected', 0)}`",
        f"- Artifacts scanned: `{summary.get('artifactsScanned', 0)}`",
        f"- Artifacts skipped: `{summary.get('artifactsSkipped', 0)}`",
        f"- Records loaded: `{summary.get('recordsLoaded', 0)}`",
        f"- Evaluable records: `{summary.get('evaluableRecords', 0)}`",
        f"- Unique trade keys: `{summary.get('uniqueTradeKeys', 0)}`",
        f"- Affected unique trade keys: `{unique_affected.get('anyModelRelevantChange', 0)}`",
        "",
        "## Evidence Categories",
        "",
        "| Evidence type | Artifacts | Records | Evaluable records | Affected rows |",
        "|---|---:|---:|---:|---:|",
    ]
    for evidence_type in ("real_local", "existing_test_fixture", "synthetic_fixture", "unknown"):
        counts = _mapping(evidence_counts.get(evidence_type))
        if not counts:
            continue
        lines.append(
            f"| `{evidence_type}` | {counts.get('artifacts', 0)} | {counts.get('records', 0)} | "
            f"{counts.get('evaluableRecords', 0)} | {counts.get('affectedRows', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Artifact Families",
            "",
            "| Family | Records |",
            "|---|---:|",
        ]
    )
    for family, count in sorted(family_counts.items()):
        lines.append(f"| `{family}` | {count} |")
    lines.extend(
        [
            "",
            "## Archive Field Coverage",
            "",
            "| Field category | Rows |",
            "|---|---:|",
        ]
    )
    for key in (
        "raw_side_outcome_price_available",
        "old_probability_available",
        "phase1_additive_fields_present",
        "price_missing_or_unknown",
        "side_missing_or_unknown",
        "outcome_missing_or_unknown",
        "lossy_csv_without_price",
        "old_fields_only_rows",
    ):
        lines.append(f"| `{key}` | {field_counts.get(key, 0)} |")
    lines.extend(
        [
            "",
            "## Affected Archive Rows",
            "",
            "| Surface | Rows | Unique trade keys |",
            "|---|---:|---:|",
        ]
    )
    for key in (
        "lowProbability30Changed",
        "lowProbability35Changed",
        "nearCertainty95Changed",
        "nearCertainty98Changed",
        "directionChanged",
        "laterCorrectnessChanged",
        "anyModelRelevantChange",
        "sensitiveGateContextAffected",
    ):
        lines.append(f"| `{key}` | {affected.get(key, 0)} | {unique_affected.get(key, 0)} |")
    lines.extend(
        [
            "",
            "## Missing Field Taxonomy",
            "",
            "| Note | Rows |",
            "|---|---:|",
        ]
    )
    if missing:
        for key, count in sorted(missing.items()):
            lines.append(f"| `{key}` | {count} |")
    else:
        lines.append("| `none` | 0 |")
    lines.extend(
        [
            "",
            "## Compatibility Findings",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("compatibilityFindings", []))
    lines.extend(
        [
            "",
            "## Affected Examples",
            "",
        ]
    )
    examples = report.get("affectedExamples") if isinstance(report.get("affectedExamples"), list) else []
    if examples:
        for item in examples:
            lines.append(
                f"- `{item.get('artifactEvidenceType')}` `{item.get('artifactFamily')}` `{item.get('rowId')}`: "
                f"{item.get('rawOrderSide')} {item.get('rawTokenOutcome')} raw={item.get('rawTokenPrice')} "
                f"economic={item.get('economicSide')}@{item.get('economicSideProbability')} "
                f"changes={', '.join(item.get('changedFields', []))}"
            )
    else:
        lines.append("- No affected archive rows were found in the scanned sample.")
    lines.extend(
        [
            "",
            "## Implementation Guardrails",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("implementationGuardrails", []))
    lines.extend(
        [
            "",
            "## Gate Decision",
            "",
            f"Decision: `{report.get('gateDecision')}`.",
            "",
            "This sidecar does not authorize implementation. It only resolves the archive-evidence question for a future separately approved Phase 2 implementation.",
            "",
            "## Explicit Blocks",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("explicitBlocks", []))
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(report: Mapping[str, object], *, markdown_path: str | Path, json_path: str | Path) -> dict[str, str]:
    md = Path(markdown_path)
    js = Path(json_path)
    md.parent.mkdir(parents=True, exist_ok=True)
    js.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(archive_evidence_markdown(report), encoding="utf-8")
    js.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"markdownPath": str(md), "jsonPath": str(js)}


def _artifact_ref(base: Path, path: Path, *, family: str, evidence_type: str) -> dict[str, object]:
    try:
        rel = path.resolve().relative_to(base.resolve())
    except ValueError:
        rel = path
    return {
        "path": str(path),
        "relativePath": str(rel),
        "artifactFamily": family,
        "artifactEvidenceType": evidence_type,
    }


def _archive_csv_family(path: Path) -> str:
    name = path.name
    if name.endswith("_trades.csv"):
        return "archive_trades_csv"
    if name.endswith("_candidates.csv"):
        return "archive_candidates_csv"
    if name.endswith("_flagged.csv"):
        return "archive_flagged_csv"
    if name.endswith("_secondary_review.csv"):
        return "archive_secondary_review_csv"
    if name.startswith("archive_") and name.endswith(".csv"):
        return "archive_case_slice_csv"
    return "archive_csv"


def _records_from_archive_json(path: Path, *, artifact: Mapping[str, object], max_rows: int | None) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows: list[dict[str, object]] = []
    if isinstance(payload, list):
        _append_json_items(rows, payload, path=path, artifact=artifact, source_collection="root_list", max_rows=max_rows)
        return rows
    if not isinstance(payload, Mapping):
        return rows
    for source_collection in ("cases", "secondary_review_cases", "flagged_cases", "excluded_cases"):
        values = payload.get(source_collection)
        if isinstance(values, list):
            _append_json_items(rows, values, path=path, artifact=artifact, source_collection=source_collection, max_rows=max_rows)
        if max_rows is not None and len(rows) >= max_rows:
            return rows[:max_rows]
    return rows


def _append_json_items(
    rows: list[dict[str, object]],
    values: Sequence[object],
    *,
    path: Path,
    artifact: Mapping[str, object],
    source_collection: str,
    max_rows: int | None,
) -> None:
    for index, item in enumerate(values):
        if max_rows is not None and len(rows) >= max_rows:
            return
        if not isinstance(item, Mapping):
            continue
        trade = item.get("trade") if isinstance(item.get("trade"), Mapping) else {}
        raw = item.get("raw_metrics") if isinstance(item.get("raw_metrics"), Mapping) else {}
        row = {**trade, **raw}
        row.update(
            {
                "artifactFamily": artifact.get("artifactFamily"),
                "artifactEvidenceType": artifact.get("artifactEvidenceType"),
                "artifactPath": str(path),
                "rowIndex": index,
                "sourceCollection": source_collection,
                "sourceShape": "archive_json_case",
                "id": trade.get("trade_id") or item.get("id") or item.get("trade_id") or index,
                "severity": item.get("severity"),
                "flags": item.get("flags"),
            }
        )
        rows.append(row)


def _records_from_archive_csv(path: Path, *, artifact: Mapping[str, object], max_rows: int | None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader):
                row["artifactFamily"] = artifact.get("artifactFamily")
                row["artifactEvidenceType"] = artifact.get("artifactEvidenceType")
                row["artifactPath"] = str(path)
                row["rowIndex"] = index
                row["sourceCollection"] = path.name
                row["sourceShape"] = "archive_csv_row"
                rows.append(row)
                if max_rows is not None and len(rows) >= max_rows:
                    break
    except OSError:
        return []
    return rows


def _summary(
    records: Sequence[Mapping[str, object]],
    evaluated: Sequence[Mapping[str, object]],
    artifacts: Sequence[Mapping[str, object]],
    skipped: Sequence[Mapping[str, object]],
    *,
    discovered_count: int | None = None,
) -> dict[str, object]:
    family_counts = Counter(str(item.get("artifactFamily") or "unknown") for item in evaluated)
    unique_keys = {str(item.get("uniqueTradeKey")) for item in evaluated if item.get("uniqueTradeKey")}
    evidence_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"artifacts": 0, "records": 0, "evaluableRecords": 0, "affectedRows": 0})
    for artifact in artifacts:
        evidence_counts[str(artifact.get("artifactEvidenceType") or "unknown")]["artifacts"] += 1
    field_counts: Counter[str] = Counter()
    affected_rows: Counter[str] = Counter()
    affected_unique: dict[str, set[str]] = defaultdict(set)
    missing_notes: Counter[str] = Counter()
    for original, item in zip(records, evaluated):
        evidence_type = str(item.get("artifactEvidenceType") or "unknown")
        evidence_counts[evidence_type]["records"] += 1
        if item.get("rawTokenPrice") != "unknown" and item.get("economicSideProbability") != "unknown":
            evidence_counts[evidence_type]["evaluableRecords"] += 1
            field_counts["raw_side_outcome_price_available"] += 1
        if item.get("anyModelRelevantChange"):
            evidence_counts[evidence_type]["affectedRows"] += 1
        if original.get("price_implied_probability") not in (None, ""):
            field_counts["old_probability_available"] += 1
        if item.get("phase1FieldsPresent"):
            field_counts["phase1_additive_fields_present"] += 1
        if item.get("rawTokenPrice") == "unknown":
            field_counts["price_missing_or_unknown"] += 1
        if item.get("rawOrderSide") == "unknown":
            field_counts["side_missing_or_unknown"] += 1
        if item.get("rawTokenOutcome") == "unknown":
            field_counts["outcome_missing_or_unknown"] += 1
        if _old_fields_only(original):
            field_counts["old_fields_only_rows"] += 1
        if _lossy_csv_without_price(original, item):
            field_counts["lossy_csv_without_price"] += 1
        key = str(item.get("uniqueTradeKey") or "")
        for note in item.get("qualityNotes", []):
            missing_notes[str(note)] += 1
        for surface in (
            "lowProbability30Changed",
            "lowProbability35Changed",
            "nearCertainty95Changed",
            "nearCertainty98Changed",
            "directionChanged",
            "laterCorrectnessChanged",
            "anyModelRelevantChange",
        ):
            if item.get(surface):
                affected_rows[surface] += 1
                if key:
                    affected_unique[surface].add(key)
        if item.get("anyModelRelevantChange") and item.get("sensitiveGateContext"):
            affected_rows["sensitiveGateContextAffected"] += 1
            if key:
                affected_unique["sensitiveGateContextAffected"].add(key)
    return {
        "artifactsDiscovered": discovered_count if discovered_count is not None else len(artifacts),
        "artifactsSelected": len(artifacts),
        "artifactsScanned": len(artifacts) - len(skipped),
        "artifactsSkipped": len(skipped),
        "recordsLoaded": len(records),
        "evaluableRecords": sum(counts["evaluableRecords"] for counts in evidence_counts.values()),
        "uniqueTradeKeys": len(unique_keys),
        "artifactFamilyCounts": dict(sorted(family_counts.items())),
        "evidenceTypeCounts": {key: dict(value) for key, value in sorted(evidence_counts.items())},
        "fieldCoverageCounts": dict(sorted(field_counts.items())),
        "affectedRows": dict(sorted(affected_rows.items())),
        "affectedUniqueTradeKeys": {key: len(value) for key, value in sorted(affected_unique.items())},
        "missingFieldTaxonomy": dict(sorted(missing_notes.items())),
        "skippedArtifacts": [dict(item) for item in skipped[:50]],
    }


def _gate_decision(summary: Mapping[str, object]) -> str:
    evidence = _mapping(summary.get("evidenceTypeCounts"))
    real = _mapping(evidence.get("real_local"))
    synthetic = _mapping(evidence.get("synthetic_fixture"))
    field_counts = _mapping(summary.get("fieldCoverageCounts"))
    affected = _mapping(summary.get("affectedUniqueTradeKeys"))
    real_evaluable = int(real.get("evaluableRecords") or 0)
    synthetic_evaluable = int(synthetic.get("evaluableRecords") or 0)
    if real_evaluable < 50 or synthetic_evaluable < 8:
        return "needs_more_archive_fixtures"
    if int(affected.get("anyModelRelevantChange") or 0) <= 0:
        return "keep_phase1_only"
    if int(field_counts.get("raw_side_outcome_price_available") or 0) <= int(field_counts.get("lossy_csv_without_price") or 0):
        return "needs_more_archive_fixtures"
    return "ready_for_phase2_implementation"


def _artifact_inventory(artifacts: Sequence[Mapping[str, object]], skipped: Sequence[Mapping[str, object]]) -> dict[str, object]:
    by_evidence = Counter(str(item.get("artifactEvidenceType") or "unknown") for item in artifacts)
    by_family = Counter(str(item.get("artifactFamily") or "unknown") for item in artifacts)
    return {
        "byEvidenceType": dict(sorted(by_evidence.items())),
        "byFamily": dict(sorted(by_family.items())),
        "sampleArtifacts": [dict(item) for item in artifacts[:30]],
        "skippedArtifacts": [dict(item) for item in skipped[:30]],
    }


def _compatibility_findings(summary: Mapping[str, object]) -> list[str]:
    field_counts = _mapping(summary.get("fieldCoverageCounts"))
    findings = [
        "Archive JSON reports preserve raw trade side/outcome/price in `trade`, so old report loading can derive display-only economic context without mutating saved reports.",
        "New archive trade/candidate CSV shape includes additive Phase 1 raw/economic fields; old columns must remain raw-token.",
        "Old archive flagged/secondary CSV rows can be lossy because they may include side/outcome without price; these rows must stay unknown for Phase 2 rescoring and must not be coerced.",
    ]
    if int(field_counts.get("lossy_csv_without_price") or 0) > 0:
        findings.append("Lossy archive CSV rows were observed; future Phase 2 implementation should not use old flagged CSV exports as a scoring source.")
    if int(field_counts.get("phase1_additive_fields_present") or 0) > 0:
        findings.append("Phase 1 additive fields are present in at least some archive evidence rows, confirming additive-only export shape is testable.")
    return findings


def _examples(
    evaluated: Sequence[Mapping[str, object]],
    *,
    require_change: bool = False,
    require_notes: bool = False,
    limit: int = 12,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    surfaces = [
        "lowProbability30Changed",
        "lowProbability35Changed",
        "nearCertainty95Changed",
        "nearCertainty98Changed",
        "directionChanged",
        "laterCorrectnessChanged",
    ]
    for item in evaluated:
        if require_change and not item.get("anyModelRelevantChange"):
            continue
        if require_notes and not item.get("qualityNotes"):
            continue
        rows.append(
            {
                "artifactEvidenceType": item.get("artifactEvidenceType"),
                "artifactFamily": item.get("artifactFamily"),
                "artifactPath": item.get("artifactPath"),
                "rowId": item.get("rowId"),
                "rawOrderSide": item.get("rawOrderSide"),
                "rawTokenOutcome": item.get("rawTokenOutcome"),
                "rawTokenPrice": item.get("rawTokenPrice"),
                "economicSide": item.get("economicSide"),
                "economicSideProbability": item.get("economicSideProbability"),
                "changedFields": [surface for surface in surfaces if item.get(surface)],
                "qualityNotes": list(item.get("qualityNotes") or []),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _old_fields_only(record: Mapping[str, object]) -> bool:
    has_old = record.get("price_implied_probability") not in (None, "") or record.get("price") not in (None, "")
    has_phase1 = any(
        record.get(key) not in (None, "")
        for key in (
            "raw_token_price",
            "economic_side_probability",
            "rawTokenPrice",
            "economicSideProbability",
        )
    )
    return bool(has_old and not has_phase1)


def _lossy_csv_without_price(record: Mapping[str, object], evaluated: Mapping[str, object]) -> bool:
    return (
        str(record.get("sourceShape") or "") == "archive_csv_row"
        and evaluated.get("rawOrderSide") != "unknown"
        and evaluated.get("rawTokenOutcome") != "unknown"
        and evaluated.get("rawTokenPrice") == "unknown"
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sidecar-only Side/Outcome Phase 2 archive evidence gap audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-md", default="docs/inspoly_side_outcome_phase2_archive_evidence_gap_20260522.md")
    parser.add_argument("--output-json", default="side_outcome_audits/side_outcome_phase2_archive_evidence_gap_20260522.json")
    parser.add_argument("--max-files", type=int, default=350)
    parser.add_argument("--max-rows-per-file", type=int, default=200)
    parser.add_argument("--max-bytes", type=int, default=5_000_000)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    artifacts = discover_archive_artifacts(args.root)
    selected_artifacts = select_artifacts_for_scan(artifacts, max_files=args.max_files)
    records, skipped = load_archive_records(
        selected_artifacts,
        max_files=None,
        max_rows_per_file=args.max_rows_per_file,
        max_bytes=args.max_bytes,
    )
    report = build_archive_evidence_audit(
        records,
        artifacts=selected_artifacts,
        discovered_artifacts=artifacts,
        skipped_artifacts=skipped,
    )
    written = write_outputs(report, markdown_path=args.output_md, json_path=args.output_json)
    if not args.quiet:
        print(json.dumps({"gateDecision": report["gateDecision"], **written}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
