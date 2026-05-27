from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

POINTER_FIELD = "indexerWarehousePointer"
POINTER_SCHEMA_VERSION = "indexer_warehouse_report_pointer_v1"

_ALLOWED_ARTIFACT_TYPES = {"indexer_warehouse_registry", "indexer_warehouse_query"}
_REQUIRED_FALSE_FLAGS = (
    "metricsCopied",
    "scoringEffect",
    "routingEffect",
    "uiRequired",
    "liveRefresh",
    "rawDbReadRequired",
)
_ALLOWED_KEYS = {
    "pointerVersion",
    "sidecarOnly",
    "advisoryOnly",
    "artifactType",
    "artifactPath",
    "artifactId",
    "generatedAt",
    "sourceReportId",
    "metricsCopied",
    "scoringEffect",
    "routingEffect",
    "uiRequired",
    "reportUiRequired",
    "liveRefresh",
    "rawDbReadRequired",
    "registryPath",
    "queryRunPath",
    "localOnlyWarning",
    "staleDataWarning",
    "analystConfusionNote",
    "qualityNotes",
}
_FORBIDDEN_KEYS = {
    "aggregate",
    "capitalAtRisk",
    "case",
    "cases",
    "cursorCount",
    "cursor_count",
    "cursors",
    "display_trades",
    "funding",
    "health",
    "marketCount",
    "market_count",
    "markets",
    "metrics",
    "phase3",
    "rowLevelContext",
    "row_count",
    "row_level_context",
    "rows",
    "rowsByTarget",
    "rows_by_target",
    "score",
    "scoring",
    "severity",
    "suspicious_trades",
    "targetRows",
    "target_rows",
    "tradeCount",
    "trade_count",
    "trades",
    "wallets",
}


class ReportPointerValidationError(ValueError):
    """Raised when an indexer warehouse report pointer is not metadata-only."""


def normalize_indexer_warehouse_pointer(
    pointer: Mapping[str, Any],
    *,
    source_report_id: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Return a safe, metadata-only report pointer."""

    if not isinstance(pointer, Mapping):
        raise ReportPointerValidationError("indexer warehouse pointer must be a JSON object")

    _reject_unsafe_keys(pointer)

    unknown_keys = set(pointer) - _ALLOWED_KEYS
    if unknown_keys:
        raise ReportPointerValidationError(
            "indexer warehouse pointer contains unsupported fields: "
            + ", ".join(sorted(str(key) for key in unknown_keys))
        )

    version = _text(pointer.get("pointerVersion", POINTER_SCHEMA_VERSION), "pointerVersion")
    if version != POINTER_SCHEMA_VERSION:
        raise ReportPointerValidationError(f"unsupported pointerVersion: {version}")

    artifact_type = _text(pointer.get("artifactType"), "artifactType")
    if artifact_type not in _ALLOWED_ARTIFACT_TYPES:
        raise ReportPointerValidationError(f"unsupported artifactType: {artifact_type}")

    artifact_path = _text(pointer.get("artifactPath"), "artifactPath")
    artifact_id = _text(pointer.get("artifactId"), "artifactId")
    generated_at_value = pointer.get("generatedAt")
    if generated_at_value is None:
        generated_at_value = (generated_at or datetime.now(UTC)).isoformat()
    generated_at_text = _text(generated_at_value, "generatedAt")
    source_report_value = pointer.get("sourceReportId") or source_report_id or ""

    normalized: dict[str, Any] = {
        "pointerVersion": POINTER_SCHEMA_VERSION,
        "sidecarOnly": _flag(pointer, "sidecarOnly", expected=True),
        "advisoryOnly": _flag(pointer, "advisoryOnly", expected=True),
        "artifactType": artifact_type,
        "artifactPath": artifact_path,
        "artifactId": artifact_id,
        "generatedAt": generated_at_text,
        "sourceReportId": _text(source_report_value, "sourceReportId"),
        "metricsCopied": _flag(pointer, "metricsCopied", expected=False),
        "scoringEffect": _flag(pointer, "scoringEffect", expected=False),
        "routingEffect": _flag(pointer, "routingEffect", expected=False),
        "uiRequired": _ui_required(pointer),
        "liveRefresh": _flag(pointer, "liveRefresh", expected=False),
        "rawDbReadRequired": _flag(pointer, "rawDbReadRequired", expected=False),
        "localOnlyWarning": _text(
            pointer.get(
                "localOnlyWarning",
                "The referenced sidecar artifact may be local-only and machine-specific.",
            ),
            "localOnlyWarning",
        ),
        "staleDataWarning": _text(
            pointer.get(
                "staleDataWarning",
                "The referenced sidecar artifact is historical and does not refresh live data.",
            ),
            "staleDataWarning",
        ),
        "analystConfusionNote": _text(
            pointer.get(
                "analystConfusionNote",
                "This pointer is advisory metadata only; it is not a verdict, ranking input, or report metric.",
            ),
            "analystConfusionNote",
        ),
    }

    for field in ("registryPath", "queryRunPath"):
        if pointer.get(field) is not None:
            normalized[field] = _text(pointer.get(field), field)

    quality_notes = pointer.get("qualityNotes", [])
    if not isinstance(quality_notes, list) or any(not isinstance(note, str) for note in quality_notes):
        raise ReportPointerValidationError("qualityNotes must be a list of strings")
    normalized["qualityNotes"] = list(quality_notes)

    return normalized


def attach_indexer_warehouse_pointer(
    report: Mapping[str, Any],
    pointer: Mapping[str, Any],
    *,
    source_report_id: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Return a report copy with a validated top-level warehouse pointer."""

    updated = dict(report)
    updated[POINTER_FIELD] = normalize_indexer_warehouse_pointer(
        pointer,
        source_report_id=source_report_id,
        generated_at=generated_at,
    )
    return updated


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReportPointerValidationError(f"{field} must be a non-empty string")
    return value


def _flag(pointer: Mapping[str, Any], field: str, *, expected: bool) -> bool:
    value = pointer.get(field, expected)
    if value is not expected:
        raise ReportPointerValidationError(f"{field} must be {str(expected).lower()}")
    return expected


def _ui_required(pointer: Mapping[str, Any]) -> bool:
    if "uiRequired" in pointer:
        return _flag(pointer, "uiRequired", expected=False)
    if "reportUiRequired" in pointer:
        if pointer.get("reportUiRequired") is not False:
            raise ReportPointerValidationError("reportUiRequired must be false")
        return False
    return False


def _reject_unsafe_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key) in _FORBIDDEN_KEYS:
                raise ReportPointerValidationError(f"forbidden pointer field: {key}")
            _reject_unsafe_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_unsafe_keys(nested)
