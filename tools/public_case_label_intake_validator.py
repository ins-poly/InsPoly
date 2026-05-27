#!/usr/bin/env python3
"""Validate human-curated public-case label intake files.

The validator is sidecar-only. It checks whether a future human label packet is
complete enough to be reviewed for benchmark inclusion, but it never applies
labels to the benchmark fixture.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "public_case_label_intake_validation"
SCHEMA_VERSION = "public_case_label_intake_validation_v1"
INTAKE_SCHEMA_VERSION = "public_case_label_intake_v1"
DEFAULT_OUTPUT = Path("validation_outputs/public_case_label_intake_validation_20260527.json")

ALLOWED_ASSERTION_LEVELS = {
    "exact_wallet_supported",
    "named_user_local_wallet_candidate",
    "named_user_only",
    "pattern_level_only",
    "market_level_only",
    "insufficient_source_evidence",
    "defer_needs_human_label",
}
ALLOWED_REVIEW_STATUSES = {"draft", "pending_review", "accepted", "rejected", "deferred"}
ALLOWED_CONFIDENCE = {"low", "medium", "high", "fixture_grade"}
NON_EXACT_LEVELS = ALLOWED_ASSERTION_LEVELS - {"exact_wallet_supported", "named_user_local_wallet_candidate"}
WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
REQUIRED_LABEL_FIELDS = (
    "label_id",
    "benchmark_case_id",
    "proposed_assertion_level",
    "source_urls",
    "source_titles",
    "evidence_summary",
    "evidence_timestamp",
    "curator",
    "confidence",
    "limitations",
    "forbidden_interpretation",
    "review_status",
    "accepted_for_benchmark",
)


def validate_intake_file(path: str | Path) -> dict[str, object]:
    intake_path = Path(path)
    payload = json.loads(intake_path.read_text(encoding="utf-8"))
    errors = validate_intake_payload(payload)
    labels = payload.get("labels") if isinstance(payload, Mapping) else []
    label_rows = [label for label in labels if isinstance(label, Mapping)]
    tier_counts = Counter(str(label.get("proposed_assertion_level") or "unknown") for label in label_rows)
    accepted_count = sum(1 for label in label_rows if label.get("accepted_for_benchmark") is True)
    exact_count = tier_counts.get("exact_wallet_supported", 0)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "intakePath": str(intake_path),
        "sidecarOnly": True,
        "runtimeBehaviorChanged": False,
        "labelsApplied": False,
        "gateDecision": "public_case_label_intake_valid" if not errors else "public_case_label_intake_invalid",
        "summary": {
            "labelCount": len(label_rows),
            "acceptedForBenchmarkCount": accepted_count,
            "exactWalletLabelCount": exact_count,
            "tierCounts": dict(sorted(tier_counts.items())),
            "errorCount": len(errors),
        },
        "errors": errors,
    }


def validate_intake_payload(payload: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["intake payload must be an object"]
    if payload.get("schema_version") != INTAKE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {INTAKE_SCHEMA_VERSION}")
    if payload.get("sidecar_only") is not True:
        errors.append("sidecar_only must be true")
    labels = payload.get("labels")
    if not isinstance(labels, list):
        return errors + ["labels must be a list"]
    seen_ids: set[str] = set()
    for index, label in enumerate(labels):
        if not isinstance(label, Mapping):
            errors.append(f"labels[{index}] must be an object")
            continue
        label_id = str(label.get("label_id") or f"labels[{index}]")
        if label_id in seen_ids:
            errors.append(f"{label_id}: duplicate label_id")
        seen_ids.add(label_id)
        missing = [field for field in REQUIRED_LABEL_FIELDS if field not in label]
        if missing:
            errors.append(f"{label_id}: missing fields: {', '.join(missing)}")
        level = str(label.get("proposed_assertion_level") or "")
        if level not in ALLOWED_ASSERTION_LEVELS:
            errors.append(f"{label_id}: unsupported proposed_assertion_level {level}")
        confidence = str(label.get("confidence") or "")
        if confidence not in ALLOWED_CONFIDENCE:
            errors.append(f"{label_id}: unsupported confidence {confidence}")
        review_status = str(label.get("review_status") or "")
        if review_status not in ALLOWED_REVIEW_STATUSES:
            errors.append(f"{label_id}: unsupported review_status {review_status}")
        if label.get("accepted_for_benchmark") is True and review_status != "accepted":
            errors.append(f"{label_id}: accepted_for_benchmark requires review_status=accepted")
        _validate_sources(label_id, label, errors)
        _validate_local_refs(label_id, label, errors)
        _validate_evidence_text(label_id, label, errors)
        _validate_assertion_level(label_id, label, level, confidence, errors)
    return errors


def write_json(path: str | Path, payload: Mapping[str, object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intake")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = validate_intake_file(args.intake)
    write_json(args.output, report)
    if not args.quiet:
        print(f"labels: {report['summary']['labelCount']}")
        print(f"errors: {report['summary']['errorCount']}")
        print(f"gate: {report['gateDecision']}")
    return 0 if report["gateDecision"] == "public_case_label_intake_valid" else 1


def _validate_sources(label_id: str, label: Mapping[str, object], errors: list[str]) -> None:
    source_urls = label.get("source_urls")
    source_titles = label.get("source_titles")
    if not isinstance(source_urls, list) or not source_urls:
        errors.append(f"{label_id}: source_urls must be a non-empty list")
    elif any(not str(url).startswith(("http://", "https://")) for url in source_urls):
        errors.append(f"{label_id}: source_urls must contain web URLs")
    if not isinstance(source_titles, list) or not source_titles:
        errors.append(f"{label_id}: source_titles must be a non-empty list")
    if isinstance(source_urls, list) and isinstance(source_titles, list) and len(source_urls) != len(source_titles):
        errors.append(f"{label_id}: source_urls and source_titles must have equal length")


def _validate_local_refs(label_id: str, label: Mapping[str, object], errors: list[str]) -> None:
    refs = label.get("local_artifact_refs", [])
    if refs in ("", None):
        return
    if not isinstance(refs, list):
        errors.append(f"{label_id}: local_artifact_refs must be a list when present")
        return
    for ref_index, ref in enumerate(refs):
        if not isinstance(ref, Mapping):
            errors.append(f"{label_id}: local_artifact_refs[{ref_index}] must be an object")
            continue
        path = str(ref.get("path") or "")
        if not path or path.startswith("/") or len(path) > 180:
            errors.append(f"{label_id}: local_artifact_refs[{ref_index}] must use a compact relative path")
        if not str(ref.get("match") or "").strip():
            errors.append(f"{label_id}: local_artifact_refs[{ref_index}] must describe the match")
        if not isinstance(ref.get("proves_wallet_identity"), bool):
            errors.append(f"{label_id}: local_artifact_refs[{ref_index}] must set proves_wallet_identity")


def _validate_evidence_text(label_id: str, label: Mapping[str, object], errors: list[str]) -> None:
    for field in ("evidence_summary", "limitations", "forbidden_interpretation", "curator"):
        if not str(label.get(field) or "").strip():
            errors.append(f"{label_id}: {field} is required")
    quote = str(label.get("evidence_quote_short") or "")
    if len(quote) > 300:
        errors.append(f"{label_id}: evidence_quote_short must stay under 300 characters")


def _validate_assertion_level(
    label_id: str,
    label: Mapping[str, object],
    level: str,
    confidence: str,
    errors: list[str],
) -> None:
    wallet = str(label.get("wallet_address") or "")
    username = str(label.get("polymarket_username") or "")
    market = str(label.get("market_slug") or "")
    condition_id = str(label.get("condition_id") or "")
    accepted = label.get("accepted_for_benchmark") is True
    local_refs = [ref for ref in label.get("local_artifact_refs", []) if isinstance(ref, Mapping)]
    refs_proving_identity = [ref for ref in local_refs if ref.get("proves_wallet_identity") is True]

    if level == "exact_wallet_supported":
        if not WALLET_RE.match(wallet):
            errors.append(f"{label_id}: exact_wallet_supported requires a full 0x wallet_address")
        if not (market or condition_id):
            errors.append(f"{label_id}: exact_wallet_supported requires market_slug or condition_id")
        if not (username or refs_proving_identity or "wallet" in str(label.get("evidence_summary") or "").lower()):
            errors.append(f"{label_id}: exact_wallet_supported requires explicit wallet/user linkage evidence")
        if accepted and confidence != "fixture_grade":
            errors.append(f"{label_id}: accepted exact-wallet labels require confidence=fixture_grade")
    elif level == "named_user_local_wallet_candidate":
        if not (wallet or username or local_refs):
            errors.append(f"{label_id}: named_user_local_wallet_candidate requires wallet, username, or local_artifact_refs")
        if accepted:
            errors.append(f"{label_id}: named_user_local_wallet_candidate cannot be accepted as benchmark exact-wallet truth")
    elif level in NON_EXACT_LEVELS:
        if wallet:
            errors.append(f"{label_id}: {level} must not include wallet_address")
        if accepted and level != "defer_needs_human_label":
            errors.append(f"{label_id}: non-exact labels cannot be accepted for benchmark exact-wallet upgrade")


if __name__ == "__main__":
    raise SystemExit(main())
