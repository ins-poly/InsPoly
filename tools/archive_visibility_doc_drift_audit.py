from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("docs_audit_outputs")
DOC_PATH = Path("docs/PROGRAMS.md")
ARCHIVE_CODE_PATH = Path("app/archive_scanner.py")
STALE_HARD_HIDE_PHRASES = (
    "вона йде в `Excluded`, навіть якщо score високий",
    "archive win-rate filter вирішує, чи ця картка взагалі буде показана користувачу",
)


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _read(path: Path) -> str:
    resolved = _resolve(path) or path
    try:
        return resolved.read_text(encoding="utf-8")
    except OSError:
        return ""


def _stale_hard_hide_phrase_count(doc_text: str) -> int:
    lowered = doc_text.lower()
    return sum(1 for phrase in STALE_HARD_HIDE_PHRASES if phrase.lower() in lowered)


def build_audit(doc_path: Path = DOC_PATH, code_path: Path = ARCHIVE_CODE_PATH) -> dict[str, Any]:
    doc_text = _read(doc_path)
    code_text = _read(code_path)
    stale_hard_hide_phrase_count = _stale_hard_hide_phrase_count(doc_text)
    checks = [
        {
            "checkId": "DOC-STATUS-001",
            "description": "Documentation explicitly marks itself stale or partially stale.",
            "docSignalPresent": "застар" in doc_text.lower() or "stale" in doc_text.lower(),
            "codeSignalPresent": True,
            "severity": "info",
            "recommendedAction": "Keep stale-status warning visible until the doc is reconciled with code.",
        },
        {
            "checkId": "ARCHIVE-ANNOTATE-001",
            "description": "Archive visibility is described as annotate-not-hide.",
            "docSignalPresent": "annotate-not-hide" in doc_text.lower(),
            "codeSignalPresent": "visibility_tier" in code_text or "_visibility_tier_for_case" in code_text,
            "severity": "medium",
            "recommendedAction": "If code and docs disagree, update documentation first; do not change archive visibility behavior from this audit.",
        },
        {
            "checkId": "ARCHIVE-EXCLUDED-001",
            "description": "Legacy excluded-case container is documented as compatibility, not primary hiding.",
            "docSignalPresent": "excluded_cases" in doc_text,
            "codeSignalPresent": "excluded_cases" in code_text,
            "severity": "low",
            "recommendedAction": "Preserve legacy loading/reporting normalization for excluded_cases.",
        },
        {
            "checkId": "ARCHIVE-NO-HARD-HIDE-001",
            "description": "Archive visibility documentation avoids old hard-hide wording for win-rate failures.",
            "docSignalPresent": stale_hard_hide_phrase_count == 0,
            "codeSignalPresent": "Promoted to secondary review rather than hidden." in code_text,
            "severity": "high",
            "recommendedAction": "Remove stale wording that says archive candidates are excluded/hidden solely by win-rate; document Secondary review compatibility instead.",
        },
        {
            "checkId": "ARCHIVE-SECONDARY-REVIEW-001",
            "description": "Secondary review is documented as a visible review tier/compatibility path, not a detector suppressor.",
            "docSignalPresent": "secondary review" in doc_text.lower() or "secondary-review" in doc_text.lower(),
            "codeSignalPresent": "Secondary review" in code_text,
            "severity": "medium",
            "recommendedAction": "Keep Secondary review wording visible in archive docs and report artifacts.",
        },
        {
            "checkId": "ARCHIVE-VISIBLE-INCLUSION-001",
            "description": "Archive docs mention the persisted visible inclusion fields used by reports.",
            "docSignalPresent": "visible_inclusion_status" in doc_text and "visibility_tier" in doc_text,
            "codeSignalPresent": "visible_inclusion_status" in code_text and "visibility_tier" in code_text,
            "severity": "medium",
            "recommendedAction": "Keep visible_inclusion_status / visibility_tier documented as reporting fields.",
        },
    ]
    drift_rows = []
    for check in checks:
        drift = bool(check["docSignalPresent"] != check["codeSignalPresent"] and check["severity"] != "info")
        row = dict(check)
        row["driftObserved"] = drift
        row["modelBehaviorChanged"] = False
        drift_rows.append(row)
    contract_rows = [
        {
            "contractId": "ARCHIVE-CONTRACT-001",
            "contract": "Archive scoring still happens before visibility annotation.",
            "codeEvidence": "_score_trade() candidate cases are later assigned visibility_tier in app/archive_scanner.py.",
            "behaviorChangedByAudit": False,
        },
        {
            "contractId": "ARCHIVE-CONTRACT-002",
            "contract": "Hard Evidence Review and Visible cases are written to flagged_cases.",
            "codeEvidence": 'visibility_tier in {"Visible", HARD_EVIDENCE_REVIEW_TIER} appends to flagged_cases.',
            "behaviorChangedByAudit": False,
        },
        {
            "contractId": "ARCHIVE-CONTRACT-003",
            "contract": "Secondary review cases are preserved under legacy excluded_cases naming with an explicit not-hidden explanation.",
            "codeEvidence": 'exclusion_reason = "Promoted to secondary review rather than hidden."',
            "behaviorChangedByAudit": False,
        },
        {
            "contractId": "ARCHIVE-CONTRACT-004",
            "contract": "Win-rate/economic quality affects visibility annotation and review interpretation, not production scoring or severity labels.",
            "codeEvidence": "_visibility_tier_for_case() reads economic_win_rate_clears_threshold / win_rate_clears_threshold after severity is assigned.",
            "behaviorChangedByAudit": False,
        },
    ]
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactType": "archive_visibility_doc_drift_audit",
        "docPath": str(_resolve(doc_path) or doc_path),
        "codePath": str(_resolve(code_path) or code_path),
        "summary": {
            "checkCount": len(drift_rows),
            "contractCheckCount": len(contract_rows),
            "driftObservedCount": sum(1 for row in drift_rows if row["driftObserved"]),
            "staleArchiveHardHidePhraseCount": stale_hard_hide_phrase_count,
            "hardHideStaleDocumentationDetected": stale_hard_hide_phrase_count > 0,
            "docsRequireVisibilityReconciliation": any(row["driftObserved"] for row in drift_rows),
            "docExists": bool((_resolve(doc_path) or doc_path).exists()),
            "codeExists": bool((_resolve(code_path) or code_path).exists()),
            "modelBehaviorChanged": False,
            "scoringChanged": False,
            "gatesChanged": False,
            "archiveVisibilityChanged": False,
        },
        "driftRows": drift_rows,
        "contractRows": contract_rows,
        "limitations": [
            "This is a text/code signal audit, not a behavior proof.",
            "Do not change archive visibility from this report alone.",
            "A future reconciliation task should update docs or add focused tests before code changes.",
        ],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Archive Visibility Doc Drift Audit",
        "",
        f"- Generated at: {payload.get('generatedAt', '')}",
        f"- Checks: {summary.get('checkCount', 0)}",
        f"- Contract checks: {summary.get('contractCheckCount', 0)}",
        f"- Drift observed: {summary.get('driftObservedCount', 0)}",
        f"- Stale hard-hide phrases: {summary.get('staleArchiveHardHidePhraseCount', 0)}",
        f"- Archive visibility changed: {summary.get('archiveVisibilityChanged', False)}",
        "",
        "## Drift Rows",
    ]
    for row in payload.get("driftRows") or []:
        if isinstance(row, Mapping):
            lines.append(
                f"- `{row.get('checkId', '')}` drift={row.get('driftObserved', False)}: {row.get('recommendedAction', '')}"
            )
    lines.extend(["", "## Archive Visibility Contract"])
    for row in payload.get("contractRows") or []:
        if isinstance(row, Mapping):
            lines.append(f"- `{row.get('contractId', '')}`: {row.get('contract', '')}")
    lines.extend(["", "## Limitations"])
    for item in payload.get("limitations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: Mapping[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    resolved = _resolve(output_dir) or output_dir
    resolved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = resolved / f"archive_visibility_doc_drift_audit_{stamp}.json"
    markdown_path = resolved / f"archive_visibility_doc_drift_audit_{stamp}.md"
    json_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit archive visibility documentation drift without changing behavior.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    payload = build_audit()
    outputs = write_outputs(payload, args.output_dir)
    print(f"Archive visibility doc drift JSON: {outputs['json_path']}")
    print(f"Archive visibility doc drift markdown: {outputs['markdown_path']}")
    print(f"Drift observed: {payload.get('summary', {}).get('driftObservedCount', 0)}")
    print(f"Archive visibility changed: {payload.get('summary', {}).get('archiveVisibilityChanged', False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
