from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_LEGACY_LOCAL_CASE = "legacy_local_case"
SCHEMA_CASE_LEVEL_BENCHMARK = "case_level_benchmark"
SCHEMA_UNKNOWN_OR_INVALID = "unknown_or_invalid"

DRAFT_ASSISTED_NOT_FINAL_PREFIX = "DRAFT_ASSISTED_NOT_FINAL:"

REQUIRED_LABEL_FIELDS = ("expectedAnalystDisposition", "humanLabelConfidence")
OPTIONAL_LABEL_FIELDS = (
    "expectedDetectorDisposition",
    "humanFalsePositiveReason",
    "humanInsiderStyleReason",
    "freshValidationRequired",
    "notes",
)
HUMAN_LABEL_FIELDS = (*REQUIRED_LABEL_FIELDS, *OPTIONAL_LABEL_FIELDS)

LEGACY_IMMUTABLE_FIELDS = ("localCaseId", "sourceType", "eventSlug", "market", "conditionId", "wallet")

CASE_LEVEL_FACTUAL_FIELDS = (
    "benchmarkCaseId",
    "parentEventRunId",
    "sourceArtifact",
    "queueRank",
    "eventSlug",
    "marketSlug",
    "conditionId",
    "marketQuestion",
    "wallet",
    "traderName",
    "traderPseudonym",
    "tradeId",
    "txHash",
    "side",
    "outcome",
    "price",
    "size",
    "notionalUsd",
    "timestamp",
    "strongRiskFlag",
    "strongRiskGateBranch",
    "hardEvidenceReviewFlag",
    "hardEvidenceSources",
    "fundingEvidenceGrade",
    "suspiciousFundingQuality",
    "suppressorConflicts",
    "falsePositiveAdvisoryMatches",
    "cacheOnlyWarning",
    "retrospectiveOnlyWarning",
    "missingCriticalFields",
    "whySuspiciousSummary",
    "whyMaybeFalsePositiveSummary",
    "whatToInspectNext",
)
CASE_LEVEL_REQUIRED_FIELDS = (*CASE_LEVEL_FACTUAL_FIELDS, *HUMAN_LABEL_FIELDS)

ALLOWED_ANALYST_DISPOSITIONS = {
    "likely_false_positive",
    "plausible_insider_style",
    "needs_fresh_validation",
    "inconclusive",
    "reporting_only_control",
    "ignore_not_benchmark",
}
ALLOWED_DETECTOR_DISPOSITIONS = {
    "keep_current_behavior",
    "reporting_only_note",
    "rfc_only_review_candidate",
    "needs_fresh_validation_before_decision",
}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_FRESH_VALIDATION = {"yes", "no", ""}


def text(value: Any) -> str:
    return str(value or "").strip()


def read_csv(path: Path | None) -> tuple[list[str], list[dict[str, str]]]:
    if not path or not path.exists():
        return [], []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = [{key: text(value) for key, value in row.items()} for row in reader]
    except OSError:
        return [], []
    return fieldnames, rows


def detect_schema(fieldnames: Sequence[str]) -> dict[str, Any]:
    fields = list(fieldnames or [])
    field_set = set(fields)
    if "benchmarkCaseId" in field_set:
        missing = [field for field in CASE_LEVEL_REQUIRED_FIELDS if field not in field_set]
        return {
            "schemaType": SCHEMA_CASE_LEVEL_BENCHMARK if not missing else SCHEMA_UNKNOWN_OR_INVALID,
            "candidateSchemaType": SCHEMA_CASE_LEVEL_BENCHMARK,
            "idField": "benchmarkCaseId",
            "missingRequiredColumns": missing,
            "detectedColumns": fields,
        }
    if "localCaseId" in field_set:
        missing = [field for field in REQUIRED_LABEL_FIELDS if field not in field_set]
        return {
            "schemaType": SCHEMA_LEGACY_LOCAL_CASE if not missing else SCHEMA_UNKNOWN_OR_INVALID,
            "candidateSchemaType": SCHEMA_LEGACY_LOCAL_CASE,
            "idField": "localCaseId",
            "missingRequiredColumns": missing,
            "detectedColumns": fields,
        }
    return {
        "schemaType": SCHEMA_UNKNOWN_OR_INVALID,
        "candidateSchemaType": "",
        "idField": "",
        "missingRequiredColumns": ["localCaseId or benchmarkCaseId"],
        "detectedColumns": fields,
    }


def detect_csv_schema(path: Path | None) -> dict[str, Any]:
    fieldnames, rows = read_csv(path)
    detected = detect_schema(fieldnames)
    detected["rowCount"] = len(rows)
    detected["path"] = str(path or "")
    return detected


def is_draft_assisted(row: Mapping[str, Any]) -> bool:
    return text(row.get("notes")).startswith(DRAFT_ASSISTED_NOT_FINAL_PREFIX)


def invalid_label_fields(row: Mapping[str, Any]) -> list[str]:
    invalid: list[str] = []
    disposition = text(row.get("expectedAnalystDisposition"))
    confidence = text(row.get("humanLabelConfidence")).lower()
    detector = text(row.get("expectedDetectorDisposition"))
    fresh = text(row.get("freshValidationRequired")).lower()
    if disposition and disposition not in ALLOWED_ANALYST_DISPOSITIONS:
        invalid.append("expectedAnalystDisposition")
    if confidence and confidence not in ALLOWED_CONFIDENCE:
        invalid.append("humanLabelConfidence")
    if detector and detector not in ALLOWED_DETECTOR_DISPOSITIONS:
        invalid.append("expectedDetectorDisposition")
    if fresh not in ALLOWED_FRESH_VALIDATION:
        invalid.append("freshValidationRequired")
    return invalid


def missing_required_label_fields(row: Mapping[str, Any]) -> list[str]:
    return [field for field in REQUIRED_LABEL_FIELDS if not text(row.get(field))]


def has_any_label_field(row: Mapping[str, Any]) -> bool:
    return any(text(row.get(field)) for field in HUMAN_LABEL_FIELDS)


def label_status(row: Mapping[str, Any]) -> tuple[str, list[str]]:
    invalid = invalid_label_fields(row)
    if invalid:
        return "invalid_label", invalid
    missing = missing_required_label_fields(row)
    if missing:
        if has_any_label_field(row):
            return "partial_required_label", missing
        return "missing_required_label", missing
    if is_draft_assisted(row):
        return "draft_assisted_label", []
    return "usable_label", []


def case_source_type(row: Mapping[str, Any]) -> str:
    return "event_forensic_child_trade" if text(row.get("parentEventRunId")) else "unique_review_packet_row"

