from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import re
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("validation_corpus_outputs")
PROJECT_MEMORY_PATH = Path("PROJECT_MEMORY.md")
UNKNOWN = "unknown"

METRIC_NAMES = (
    "rawRowsScanned",
    "rowsInspected",
    "eventRows",
    "archiveRows",
    "visibleRows",
    "rawVisibleRows",
    "uniqueVisibleRows",
    "visibleDedupeRatio",
    "normalCandidates",
    "preAdmittedCandidates",
    "strongRiskRows",
    "rawStrongRiskRows",
    "uniqueStrongRiskRows",
    "strongRiskDedupeRatio",
    "hardEvidenceReviewRows",
    "rawHardEvidenceReviewRows",
    "uniqueHardEvidenceReviewRows",
    "hardEvidenceReviewDedupeRatio",
    "targetCount",
    "completedTargets",
    "auditOnlyTargets",
    "freshRerunnableTargets",
    "cacheOnlyTargets",
    "fundingEnabledTargets",
    "fundingBlockedTargets",
)

REQUIRED_SUMMARY_METRICS = (
    "rowsInspected",
    "rawVisibleRows",
    "uniqueVisibleRows",
    "rawStrongRiskRows",
    "uniqueStrongRiskRows",
    "rawHardEvidenceReviewRows",
    "uniqueHardEvidenceReviewRows",
    "targetCount",
    "completedTargets",
)


@dataclass(frozen=True)
class ReportSource:
    name: str
    kind: str
    json_path: Path | None
    markdown_path: Path | None
    payload: Mapping[str, Any]
    metrics: dict[str, Any]


def _unknown_metrics() -> dict[str, Any]:
    return {name: UNKNOWN for name in METRIC_NAMES}


def _value(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return UNKNOWN
        current = current.get(key, UNKNOWN)
    if current is None or current == "":
        return UNKNOWN
    return current


def _counter_value(payload: Mapping[str, Any], key: str, status: str) -> Any:
    counters = payload.get(key)
    if not isinstance(counters, Mapping):
        return UNKNOWN
    return counters.get(status, UNKNOWN)


def _tag_value(payload: Mapping[str, Any], tag: str) -> Any:
    counters = payload.get("completed_target_tag_counts")
    if not isinstance(counters, Mapping):
        return UNKNOWN
    return counters.get(tag, UNKNOWN)


def _load_json(path: Path | None) -> Mapping[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _latest_file(pattern: str, *, exclude: tuple[str, ...] = ()) -> Path | None:
    candidates = [
        path
        for path in (REPO_ROOT / DEFAULT_OUTPUT_DIR).glob(pattern)
        if all(token not in path.name for token in exclude)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))


def _latest_corpus_file() -> Path | None:
    candidates = [
        path
        for path in (REPO_ROOT / DEFAULT_OUTPUT_DIR).glob("post_v2_corpus_*.json")
        if "_audit_" not in path.name
    ]
    usable: list[Path] = []
    for path in candidates:
        payload = _load_json(path)
        if payload.get("validationPolicy") == "network_probe":
            continue
        corpus_name = str(payload.get("corpus_name") or payload.get("corpusName") or "")
        if corpus_name.endswith("_smoke") or "_smoke" in corpus_name:
            continue
        usable.append(path)
    if not usable:
        usable = candidates
    if not usable:
        return None
    return max(usable, key=lambda path: (path.stat().st_mtime, path.name))


def _latest_strong_risk_diagnostic_file() -> Path | None:
    directory = REPO_ROOT / "strong_risk_diagnostic_outputs"
    candidates = list(directory.glob("strong_risk_gate_diagnostic_*.json"))
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name)) if candidates else None


def _paired_markdown(json_path: Path | None) -> Path | None:
    if not json_path:
        return None
    candidate = json_path.with_suffix(".md")
    return candidate if candidate.exists() else None


def _resolve_report_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path if path.exists() else None


def _same_report_path(left: Path | None, right_value: Any) -> bool:
    right = _resolve_report_path(right_value)
    if not left or not right:
        return False
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left.name == right.name


def _report_references_corpus(payload: Mapping[str, Any], corpus_json: Path | None) -> bool:
    if corpus_json is None:
        return False
    for key in ("inputArtifacts", "input_artifacts"):
        artifacts = payload.get(key)
        if not isinstance(artifacts, Mapping):
            continue
        for artifact_key in ("corpus", "corpus_json", "corpus_output", "corpusOutput"):
            if _same_report_path(corpus_json, artifacts.get(artifact_key)):
                return True
    sources = payload.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if isinstance(source, Mapping) and str(source.get("kind") or "") == "corpus":
                if _same_report_path(corpus_json, source.get("json_path")):
                    return True
    return False


def _metric_matches_corpus(payload: Mapping[str, Any], corpus_payload: Mapping[str, Any]) -> bool:
    corpus_metrics = _extract_corpus_metrics(corpus_payload)
    report_metrics = _extract_count_hygiene_metrics(payload)
    metric_keys = (
        "rawVisibleRows",
        "uniqueVisibleRows",
        "rawStrongRiskRows",
        "uniqueStrongRiskRows",
        "rawHardEvidenceReviewRows",
        "uniqueHardEvidenceReviewRows",
    )
    compared = 0
    for key in metric_keys:
        corpus_value = corpus_metrics.get(key, UNKNOWN)
        report_value = report_metrics.get(key, UNKNOWN)
        if corpus_value == UNKNOWN or report_value == UNKNOWN:
            continue
        compared += 1
        if str(corpus_value) != str(report_value):
            return False
    return compared >= 2


def _latest_matching_file(pattern: str, *, corpus_json: Path | None, corpus_payload: Mapping[str, Any]) -> Path | None:
    candidates = sorted(
        (REPO_ROOT / DEFAULT_OUTPUT_DIR).glob(pattern),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for path in candidates:
        payload = _load_json(path)
        if _report_references_corpus(payload, corpus_json) or _metric_matches_corpus(payload, corpus_payload):
            return path
    return None


def _latest_matching_strong_risk_diagnostic_file(
    *,
    corpus_json: Path | None,
    corpus_payload: Mapping[str, Any],
) -> Path | None:
    directory = REPO_ROOT / "strong_risk_diagnostic_outputs"
    candidates = sorted(
        directory.glob("strong_risk_gate_diagnostic_*.json"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for path in candidates:
        payload = _load_json(path)
        if _report_references_corpus(payload, corpus_json) or _metric_matches_corpus(payload, corpus_payload):
            return path
    return None


def _linked_acceptance_file(corpus_json: Path | None) -> Path | None:
    candidates = list((REPO_ROOT / DEFAULT_OUTPUT_DIR).glob("post_v2_acceptance_report_*.json"))
    if not candidates:
        return None
    if corpus_json:
        linked: list[Path] = []
        for path in candidates:
            payload = _load_json(path)
            if _same_report_path(corpus_json, payload.get("source_corpus_json")):
                linked.append(path)
        if linked:
            return max(linked, key=lambda path: (path.stat().st_mtime, path.name))
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))


def _extract_corpus_metrics(payload: Mapping[str, Any]) -> dict[str, Any]:
    audit = payload.get("audit_summary")
    if not isinstance(audit, Mapping):
        audit = {}
    metrics = _unknown_metrics()
    metrics.update(
        {
            "rowsInspected": _value(audit, "total_rows_inspected"),
            "eventRows": _value(audit, "event_forensic_rows_inspected"),
            "archiveRows": _value(audit, "archive_rows_inspected"),
            "visibleRows": _value(audit, "visible_rows"),
            "rawVisibleRows": _value(audit, "rawVisibleRows"),
            "uniqueVisibleRows": _value(audit, "uniqueVisibleRows"),
            "visibleDedupeRatio": _value(audit, "visibleDedupeRatio"),
            "normalCandidates": _value(audit, "normal_candidate_rows"),
            "preAdmittedCandidates": _value(audit, "pre_admitted_candidate_rows"),
            "strongRiskRows": _value(audit, "strong_risk_rows"),
            "rawStrongRiskRows": _value(audit, "rawStrongRiskRows"),
            "uniqueStrongRiskRows": _value(audit, "uniqueStrongRiskRows"),
            "strongRiskDedupeRatio": _value(audit, "strongRiskDedupeRatio"),
            "hardEvidenceReviewRows": _value(audit, "hard_evidence_review_rows"),
            "rawHardEvidenceReviewRows": _value(audit, "rawHardEvidenceReviewRows"),
            "uniqueHardEvidenceReviewRows": _value(audit, "uniqueHardEvidenceReviewRows"),
            "hardEvidenceReviewDedupeRatio": _value(audit, "hardEvidenceReviewDedupeRatio"),
            "targetCount": _value(payload, "total_targets"),
            "completedTargets": _value(payload, "completed_targets"),
            "auditOnlyTargets": _counter_value(payload, "target_status_counts", "audit_only_saved_output"),
            "freshRerunnableTargets": _tag_value(payload, "fresh_rerunnable"),
            "cacheOnlyTargets": _value(payload, "cache_only_targets"),
            "fundingEnabledTargets": _value(payload, "funding_enabled_targets"),
            "fundingBlockedTargets": _value(payload, "funding_blocked_targets"),
        }
    )
    return metrics


def _extract_audit_metrics(payload: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _unknown_metrics()
    metrics.update(
        {
            "rowsInspected": _value(payload, "total_rows_inspected"),
            "eventRows": _value(payload, "event_forensic_rows_inspected"),
            "archiveRows": _value(payload, "archive_rows_inspected"),
            "visibleRows": _value(payload, "visible_rows"),
            "rawVisibleRows": _value(payload, "rawVisibleRows"),
            "uniqueVisibleRows": _value(payload, "uniqueVisibleRows"),
            "visibleDedupeRatio": _value(payload, "visibleDedupeRatio"),
            "normalCandidates": _value(payload, "normal_candidate_rows"),
            "preAdmittedCandidates": _value(payload, "pre_admitted_candidate_rows"),
            "strongRiskRows": _value(payload, "strong_risk_rows"),
            "rawStrongRiskRows": _value(payload, "rawStrongRiskRows"),
            "uniqueStrongRiskRows": _value(payload, "uniqueStrongRiskRows"),
            "strongRiskDedupeRatio": _value(payload, "strongRiskDedupeRatio"),
            "hardEvidenceReviewRows": _value(payload, "hard_evidence_review_rows"),
            "rawHardEvidenceReviewRows": _value(payload, "rawHardEvidenceReviewRows"),
            "uniqueHardEvidenceReviewRows": _value(payload, "uniqueHardEvidenceReviewRows"),
            "hardEvidenceReviewDedupeRatio": _value(payload, "hardEvidenceReviewDedupeRatio"),
        }
    )
    return metrics


def _extract_deep_dive_metrics(payload: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _unknown_metrics()
    metrics["strongRiskRows"] = _value(payload, "strong_risk_rows")
    return metrics


def _extract_count_hygiene_metrics(payload: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _unknown_metrics()
    metrics.update(
        {
            "visibleRows": _value(payload, "rawVisibleRows"),
            "rawVisibleRows": _value(payload, "rawVisibleRows"),
            "uniqueVisibleRows": _value(payload, "uniqueVisibleRows"),
            "visibleDedupeRatio": _value(payload, "visibleDedupeRatio"),
            "strongRiskRows": _value(payload, "rawStrongRiskRows"),
            "rawStrongRiskRows": _value(payload, "rawStrongRiskRows"),
            "uniqueStrongRiskRows": _value(payload, "uniqueStrongRiskRows"),
            "strongRiskDedupeRatio": _value(payload, "strongRiskDedupeRatio"),
            "hardEvidenceReviewRows": _value(payload, "rawHardEvidenceReviewRows"),
            "rawHardEvidenceReviewRows": _value(payload, "rawHardEvidenceReviewRows"),
            "uniqueHardEvidenceReviewRows": _value(payload, "uniqueHardEvidenceReviewRows"),
            "hardEvidenceReviewDedupeRatio": _value(payload, "hardEvidenceReviewDedupeRatio"),
        }
    )
    if metrics["rawStrongRiskRows"] == UNKNOWN:
        strong = payload.get("strongRisk")
        if isinstance(strong, Mapping):
            metrics["strongRiskRows"] = metrics["rawStrongRiskRows"] = _value(strong, "totalStrongRiskRows")
            metrics["uniqueStrongRiskRows"] = _value(strong, "uniqueStrongRiskRows")
            metrics["strongRiskDedupeRatio"] = _value(strong, "strongRiskDuplication", "strongRiskDuplicationRatio")
    if metrics["rawHardEvidenceReviewRows"] == UNKNOWN:
        hard = payload.get("hardEvidenceReview")
        if isinstance(hard, Mapping):
            metrics["hardEvidenceReviewRows"] = metrics["rawHardEvidenceReviewRows"] = _value(hard, "totalHardEvidenceReviewRows")
            metrics["uniqueHardEvidenceReviewRows"] = _value(hard, "uniqueHardEvidenceReviewRows")
            metrics["hardEvidenceReviewDedupeRatio"] = _value(hard, "hardEvidenceReviewDuplication", "hardEvidenceReviewDuplicationRatio")
    return metrics


def _extract_acceptance_metrics(payload: Mapping[str, Any]) -> dict[str, Any]:
    status_counts = payload.get("target_status_counts")
    completed_statuses = {
        "completed_funding_enabled",
        "completed_cache_only",
        "completed_no_funding_candidates",
        "completed_funding_blocked",
        "audit_only_saved_output",
    }
    derived_target_count: Any = UNKNOWN
    derived_completed: Any = UNKNOWN
    if isinstance(status_counts, Mapping):
        derived_target_count = sum(int(value or 0) for value in status_counts.values())
        derived_completed = sum(int(status_counts.get(status) or 0) for status in completed_statuses)
    metrics = _unknown_metrics()
    metrics.update(
        {
            "rawRowsScanned": _value(payload, "rawRowsScanned"),
            "rowsInspected": _value(payload, "rows_inspected"),
            "eventRows": _value(payload, "event_rows"),
            "archiveRows": _value(payload, "archive_rows"),
            "visibleRows": _value(payload, "visible_rows"),
            "rawVisibleRows": _value(payload, "rawVisibleRows"),
            "uniqueVisibleRows": _value(payload, "uniqueVisibleRows"),
            "visibleDedupeRatio": _value(payload, "visibleDedupeRatio"),
            "normalCandidates": _value(payload, "normal_candidate_rows"),
            "preAdmittedCandidates": _value(payload, "pre_admitted_candidate_rows"),
            "strongRiskRows": _value(payload, "strong_risk_rows"),
            "rawStrongRiskRows": _value(payload, "rawStrongRiskRows"),
            "uniqueStrongRiskRows": _value(payload, "uniqueStrongRiskRows"),
            "strongRiskDedupeRatio": _value(payload, "strongRiskDedupeRatio"),
            "hardEvidenceReviewRows": _value(payload, "hard_evidence_review_rows"),
            "rawHardEvidenceReviewRows": _value(payload, "rawHardEvidenceReviewRows"),
            "uniqueHardEvidenceReviewRows": _value(payload, "uniqueHardEvidenceReviewRows"),
            "hardEvidenceReviewDedupeRatio": _value(payload, "hardEvidenceReviewDedupeRatio"),
            "targetCount": _value(payload, "total_targets")
            if _value(payload, "total_targets") != UNKNOWN
            else derived_target_count,
            "completedTargets": _value(payload, "completed_targets")
            if _value(payload, "completed_targets") != UNKNOWN
            else derived_completed,
            "auditOnlyTargets": _counter_value(payload, "target_status_counts", "audit_only_saved_output"),
            "freshRerunnableTargets": _tag_value(payload, "fresh_rerunnable"),
            "cacheOnlyTargets": _value(payload, "cache_only_targets")
            if _value(payload, "cache_only_targets") != UNKNOWN
            else _counter_value(payload, "target_status_counts", "completed_cache_only"),
            "fundingEnabledTargets": _value(payload, "funding_enabled_targets")
            if _value(payload, "funding_enabled_targets") != UNKNOWN
            else _counter_value(payload, "target_status_counts", "completed_funding_enabled"),
            "fundingBlockedTargets": _value(payload, "funding_blocked_targets")
            if _value(payload, "funding_blocked_targets") != UNKNOWN
            else _counter_value(payload, "target_status_counts", "completed_funding_blocked"),
        }
    )
    return metrics


def _extract_recall_metrics(payload: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _unknown_metrics()
    # Candidate recall audits summarize admission opportunities, not audited row volume.
    # Keep row/candidate totals unknown so final summaries do not mix metric families.
    return metrics


def _markdown_metric_values(path: Path | None) -> dict[str, int]:
    if not path or not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    labels = {
        "rowsInspected": ("Rows inspected",),
        "eventRows": ("Event rows",),
        "archiveRows": ("Archive rows",),
        "visibleRows": ("Visible rows",),
        "normalCandidates": ("Normal candidates",),
        "preAdmittedCandidates": ("Pre-admitted candidates",),
        "strongRiskRows": ("Strong Risk rows", "Strong Risk rows total"),
        "hardEvidenceReviewRows": ("Hard Evidence Review rows",),
        "targetCount": ("Total targets",),
    }
    found: dict[str, int] = {}
    for line in text.splitlines():
        for metric, metric_labels in labels.items():
            if metric in found:
                continue
            for label in metric_labels:
                match = re.match(rf"^\s*-\s*{re.escape(label)}\s*:\s*([0-9][0-9,]*)\s*$", line, flags=re.IGNORECASE)
                if match:
                    found[metric] = int(match.group(1).replace(",", ""))
                    break
    return found


def _headline_raw_only_warnings(sources: list[ReportSource]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    labels = ("Visible rows", "Strong Risk rows", "Hard Evidence Review rows")
    for source in sources:
        path = source.markdown_path
        if not path or not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            for label in labels:
                if not re.match(rf"^\s*-\s*{re.escape(label)}\s*:", line, flags=re.IGNORECASE):
                    continue
                lower = line.lower()
                if " raw / " not in lower or " unique" not in lower:
                    warnings.append(
                        {
                            "code": "headline_counts_raw_only",
                            "source": source.name,
                            "label": label,
                            "line": line.strip(),
                        }
                    )
    return warnings


def _raw_unique_warnings(sources: list[ReportSource]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    pairs = (
        ("rawVisibleRows", "uniqueVisibleRows"),
        ("rawStrongRiskRows", "uniqueStrongRiskRows"),
        ("rawHardEvidenceReviewRows", "uniqueHardEvidenceReviewRows"),
    )
    for source in sources:
        for raw_key, unique_key in pairs:
            raw = source.metrics.get(raw_key, UNKNOWN)
            unique = source.metrics.get(unique_key, UNKNOWN)
            if raw == UNKNOWN or unique == UNKNOWN:
                continue
            try:
                raw_int = int(raw)
                unique_int = int(unique)
            except (TypeError, ValueError):
                continue
            if raw_int < unique_int:
                warnings.append(
                    {
                        "code": "raw_unique_count_inversion",
                        "source": source.name,
                        "raw_metric": raw_key,
                        "unique_metric": unique_key,
                        "raw": raw_int,
                        "unique": unique_int,
                    }
                )
    return warnings


def _build_sources(
    *,
    corpus_json: Path | None = None,
    audit_json: Path | None = None,
    deep_dive_json: Path | None = None,
    acceptance_json: Path | None = None,
    recall_json: Path | None = None,
) -> list[ReportSource]:
    explicit_corpus = corpus_json is not None
    corpus_json = corpus_json or _latest_corpus_file()
    corpus_payload = _load_json(corpus_json)
    audit_paths = corpus_payload.get("audit_output_paths")
    if not isinstance(audit_paths, Mapping):
        audit_paths = {}
    audit_json = audit_json or _resolve_report_path(audit_paths.get("json_path")) or _latest_file("post_v2_corpus_audit_*.json")
    deep_dive_json = (
        deep_dive_json
        or _resolve_report_path(audit_paths.get("strong_risk_deep_dive_json_path"))
        or _latest_file("strong_risk_deep_dive_*.json")
    )
    use_latest_diagnostics = not explicit_corpus or (
        corpus_json is not None and corpus_json.parent.resolve() == (REPO_ROOT / DEFAULT_OUTPUT_DIR).resolve()
    )
    drilldown_json = (
        _latest_matching_file("corpus_provenance_drilldown_*.json", corpus_json=corpus_json, corpus_payload=corpus_payload)
        or _latest_file("corpus_provenance_drilldown_*.json")
        if use_latest_diagnostics
        else None
    )
    strong_diag_json = (
        _latest_matching_strong_risk_diagnostic_file(corpus_json=corpus_json, corpus_payload=corpus_payload)
        or _latest_strong_risk_diagnostic_file()
        if use_latest_diagnostics
        else None
    )
    acceptance_json = acceptance_json or _linked_acceptance_file(corpus_json)
    recall_dir = REPO_ROOT / "candidate_recall_audit_outputs"
    if recall_json is None:
        recall_candidates = list(recall_dir.glob("candidate_recall_audit_*.json"))
        recall_json = max(recall_candidates, key=lambda path: (path.stat().st_mtime, path.name)) if recall_candidates else None

    source_specs = [
        ("corpus", "corpus", corpus_json, _extract_corpus_metrics),
        ("audit", "audit", audit_json, _extract_audit_metrics),
        ("strong_risk_deep_dive", "deep_dive", deep_dive_json, _extract_deep_dive_metrics),
        ("corpus_provenance_drilldown", "drilldown", drilldown_json, _extract_count_hygiene_metrics),
        ("strong_risk_gate_diagnostic", "strong_risk_diagnostic", strong_diag_json, _extract_count_hygiene_metrics),
        ("acceptance", "acceptance", acceptance_json, _extract_acceptance_metrics),
        ("candidate_recall", "recall", recall_json, _extract_recall_metrics),
    ]
    sources: list[ReportSource] = []
    for name, kind, path, extractor in source_specs:
        if name == "acceptance" and path is None:
            continue
        payload = _load_json(path)
        sources.append(
            ReportSource(
                name=name,
                kind=kind,
                json_path=path,
                markdown_path=_paired_markdown(path),
                payload=payload,
                metrics=extractor(payload),
            )
        )
    return sources


def _metric_conflicts(sources: list[ReportSource]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for metric in METRIC_NAMES:
        values: dict[Any, list[str]] = {}
        for source in sources:
            value = source.metrics.get(metric, UNKNOWN)
            if value == UNKNOWN:
                continue
            values.setdefault(value, []).append(source.name)
        if len(values) > 1:
            warnings.append(
                {
                    "code": "metric_value_mismatch",
                    "metric": metric,
                    "values": {str(value): names for value, names in values.items()},
                }
            )
    return warnings


def _markdown_conflicts(sources: list[ReportSource]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for source in sources:
        md_values = _markdown_metric_values(source.markdown_path)
        for metric, md_value in md_values.items():
            json_value = source.metrics.get(metric, UNKNOWN)
            if json_value == UNKNOWN:
                continue
            try:
                comparable = int(json_value)
            except (TypeError, ValueError):
                continue
            if md_value != comparable:
                warnings.append(
                    {
                        "code": "json_markdown_metric_mismatch",
                        "source": source.name,
                        "metric": metric,
                        "json_value": comparable,
                        "markdown_value": md_value,
                    }
                )
    return warnings


def _missing_field_warnings(sources: list[ReportSource]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for source in sources:
        if source.kind not in {"corpus", "acceptance"}:
            continue
        missing = [metric for metric in REQUIRED_SUMMARY_METRICS if source.metrics.get(metric) == UNKNOWN]
        if missing:
            warnings.append(
                {
                    "code": "missing_json_fields_for_reliable_summary",
                    "source": source.name,
                    "missing_metrics": missing,
                }
            )
    return warnings


def _raw_row_warnings(sources: list[ReportSource]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for source in sources:
        raw = source.metrics.get("rawRowsScanned", UNKNOWN)
        inspected = source.metrics.get("rowsInspected", UNKNOWN)
        if raw == UNKNOWN or inspected == UNKNOWN:
            continue
        if raw == inspected:
            warnings.append(
                {
                    "code": "raw_rows_scanned_reported_as_rows_inspected",
                    "source": source.name,
                    "value": raw,
                }
            )
    return warnings


def _project_memory_mentions(project_memory_path: Path, latest_corpus_name: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not project_memory_path.exists():
        return [], []
    text = project_memory_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    mentions: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    path_pattern = re.compile(r"post_v2_corpus_\d{8}_\d{6}")
    count_before_pattern = re.compile(r"([0-9][0-9,]*)\s+rows inspected", re.IGNORECASE)
    count_after_pattern = re.compile(r"rowsInspected\s*[:=]\s*([0-9][0-9,]*)", re.IGNORECASE)
    for index, line in enumerate(lines, start=1):
        matches = list(count_before_pattern.finditer(line)) + list(count_after_pattern.finditer(line))
        if not matches:
            continue
        context = "\n".join(lines[max(0, index - 4) : min(len(lines), index + 3)])
        paths = path_pattern.findall(line)
        for count_match in matches:
            count = int(count_match.group(1).replace(",", ""))
            mention = {
                "line": index,
                "count": count,
                "paths": sorted(set(paths)),
                "text": line.strip(),
                "context": context,
            }
            mentions.append(mention)
            if latest_corpus_name and latest_corpus_name in paths:
                warnings.append(
                    {
                        "code": "project_memory_latest_corpus_rows_inspected_mention",
                        "line": index,
                        "count": count,
                        "latest_corpus": latest_corpus_name,
                    }
                )
    return mentions, warnings


def summarize_report_consistency(
    *,
    corpus_json: Path | None = None,
    audit_json: Path | None = None,
    deep_dive_json: Path | None = None,
    acceptance_json: Path | None = None,
    recall_json: Path | None = None,
    project_memory_path: Path = REPO_ROOT / PROJECT_MEMORY_PATH,
) -> dict[str, Any]:
    sources = _build_sources(
        corpus_json=corpus_json,
        audit_json=audit_json,
        deep_dive_json=deep_dive_json,
        acceptance_json=acceptance_json,
        recall_json=recall_json,
    )
    latest_corpus_name = None
    for source in sources:
        if source.name == "corpus" and source.json_path:
            latest_corpus_name = source.json_path.stem
            break
    warnings = []
    warnings.extend(_metric_conflicts(sources))
    warnings.extend(_markdown_conflicts(sources))
    warnings.extend(_missing_field_warnings(sources))
    warnings.extend(_raw_row_warnings(sources))
    warnings.extend(_headline_raw_only_warnings(sources))
    warnings.extend(_raw_unique_warnings(sources))
    memory_mentions, memory_warnings = _project_memory_mentions(project_memory_path, latest_corpus_name)

    latest_rows = UNKNOWN
    for source in sources:
        if source.name == "corpus":
            latest_rows = source.metrics.get("rowsInspected", UNKNOWN)
            break
    for warning in memory_warnings:
        count = warning.get("count")
        if latest_rows != UNKNOWN and count != latest_rows:
            warnings.append(
                {
                    "code": "project_memory_latest_corpus_rows_inspected_mismatch",
                    "latest_corpus": warning.get("latest_corpus"),
                    "project_memory_count": count,
                    "current_report_count": latest_rows,
                    "line": warning.get("line"),
                }
            )

    historical_conflicts = [
        mention
        for mention in memory_mentions
        if latest_rows != UNKNOWN
        and mention.get("count") != latest_rows
        and (not latest_corpus_name or latest_corpus_name not in mention.get("paths", []))
    ]
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "classification": "reporting consistency repair needed" if warnings else "count_reporting_consistent",
        "sources": [
            {
                "name": source.name,
                "kind": source.kind,
                "json_path": str(source.json_path) if source.json_path else "",
                "markdown_path": str(source.markdown_path) if source.markdown_path else "",
                "metrics": source.metrics,
            }
            for source in sources
        ],
        "metrics": {source.name: source.metrics for source in sources},
        "warnings": warnings,
        "project_memory_rows_inspected_mentions": memory_mentions,
        "historical_different_run_count_mentions": historical_conflicts,
        "count_discrepancy_resolved": not warnings
        and any(mention.get("count") != latest_rows for mention in historical_conflicts),
    }
    return summary


def render_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Report Consistency Check",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Classification: {summary.get('classification', '')}",
        f"- Count discrepancy resolved: {summary.get('count_discrepancy_resolved', False)}",
        "",
        "## Metrics",
    ]
    for source in summary.get("sources", []):
        if not isinstance(source, Mapping):
            continue
        lines.append(f"### {source.get('name', '')}")
        lines.append(f"- JSON: {source.get('json_path', '') or 'missing'}")
        metrics = source.get("metrics")
        if isinstance(metrics, Mapping):
            for metric in METRIC_NAMES:
                lines.append(f"- {metric}: {metrics.get(metric, UNKNOWN)}")
    lines.extend(["", "## Warnings"])
    warnings = summary.get("warnings")
    if isinstance(warnings, list) and warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")
    lines.extend(["", "## Project Memory Rows-Inspected Mentions"])
    mentions = summary.get("project_memory_rows_inspected_mentions")
    if isinstance(mentions, list) and mentions:
        for mention in mentions:
            lines.append(
                f"- line {mention.get('line')}: {mention.get('count')} paths={mention.get('paths')}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Interpretation"])
    if summary.get("count_discrepancy_resolved"):
        lines.append(
            "- Historical row-count mentions differ from the latest corpus because they refer to older corpus paths."
        )
    elif summary.get("classification") in {"consistent", "count_reporting_consistent"}:
        lines.append("- Linked latest reports use consistent metric values.")
    else:
        lines.append("- Resolve warning rows before using summary counts for model interpretation.")
    return "\n".join(lines) + "\n"


def write_outputs(summary: Mapping[str, Any], output_dir: Path = REPO_ROOT / DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"report_consistency_{stamp}.json"
    markdown_path = output_dir / f"report_consistency_{stamp}.md"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    markdown_path.write_text(render_markdown(summary), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate consistency across latest InsPoly validation reports.")
    parser.add_argument("--corpus-json", type=Path)
    parser.add_argument("--audit-json", type=Path)
    parser.add_argument("--deep-dive-json", type=Path)
    parser.add_argument("--acceptance-json", type=Path)
    parser.add_argument("--recall-json", type=Path)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    summary = summarize_report_consistency(
        corpus_json=args.corpus_json,
        audit_json=args.audit_json,
        deep_dive_json=args.deep_dive_json,
        acceptance_json=args.acceptance_json,
        recall_json=args.recall_json,
    )
    outputs = write_outputs(summary, args.output_dir)
    print(f"Report consistency: {summary['classification']}")
    print(f"JSON: {outputs['json_path']}")
    print(f"Markdown: {outputs['markdown_path']}")
    if summary.get("warnings"):
        print(f"Warnings: {len(summary['warnings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
