from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence


FORBIDDEN_PRODUCTION_ACTION_FIELDS = {
    "risk_level",
    "riskLevel",
    "severity",
    "strongRisk",
    "Strong Risk",
    "hardEvidenceReview",
    "Hard Evidence Review",
    "candidateAdmission",
    "candidate_admission",
    "production_action",
    "productionAction",
    "threshold_change",
    "thresholdChange",
    "score_weight",
    "scoreWeight",
    "auto_label",
    "autoLabel",
}


@dataclass(frozen=True, slots=True)
class BenchmarkArtifactRef:
    kind: str
    path: str
    mutable: bool = False

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "path": self.path, "mutable": self.mutable}


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    title: str
    expected: Mapping[str, object]
    observed: Mapping[str, object]
    artifact_refs: tuple[BenchmarkArtifactRef, ...] = ()
    tags: tuple[str, ...] = ()
    notes: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "source": self.source,
            "expected": dict(self.expected),
            "observed": dict(self.observed),
            "artifact_refs": [ref.to_dict() for ref in self.artifact_refs],
            "tags": list(self.tags),
            "notes": self.notes,
        }


def load_benchmark_case(path: str | Path) -> BenchmarkCase:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Benchmark case root must be a JSON object")
    return validate_benchmark_case(payload)


def validate_benchmark_case(payload: Mapping[str, object]) -> BenchmarkCase:
    forbidden = _find_forbidden_fields(payload)
    if forbidden:
        raise ValueError(f"Benchmark case contains production-action field(s): {', '.join(sorted(forbidden))}")
    case_id = _required_text(payload, "case_id", "caseId")
    title = _required_text(payload, "title")
    expected = payload.get("expected")
    observed = payload.get("observed")
    if not isinstance(expected, Mapping):
        raise ValueError("Benchmark case expected must be an object")
    if not isinstance(observed, Mapping):
        raise ValueError("Benchmark case observed must be an object")
    return BenchmarkCase(
        case_id=case_id,
        title=title,
        source=_optional_text(payload.get("source")),
        expected=dict(expected),
        observed=dict(observed),
        artifact_refs=_artifact_refs(payload.get("artifact_refs") or payload.get("artifactRefs")),
        tags=tuple(str(item) for item in payload.get("tags", []) if isinstance(payload.get("tags"), list)),
        notes=_optional_text(payload.get("notes")),
    )


def _artifact_refs(value: object) -> tuple[BenchmarkArtifactRef, ...]:
    if not isinstance(value, list):
        return ()
    refs: list[BenchmarkArtifactRef] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        refs.append(
            BenchmarkArtifactRef(
                kind=_optional_text(item.get("kind")) or "artifact",
                path=_optional_text(item.get("path")),
                mutable=bool(item.get("mutable", False)),
            )
        )
    return tuple(refs)


def _required_text(payload: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        text = _optional_text(payload.get(key))
        if text:
            return text
    raise ValueError(f"Benchmark case missing required field: {keys[0]}")


def _optional_text(value: object) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _find_forbidden_fields(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text in FORBIDDEN_PRODUCTION_ACTION_FIELDS:
                found.add(key_text)
            found.update(_find_forbidden_fields(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_find_forbidden_fields(child))
    return found
