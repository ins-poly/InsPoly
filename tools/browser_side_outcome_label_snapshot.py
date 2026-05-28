#!/usr/bin/env python3
"""Static Side/Outcome browser label compatibility snapshot."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "browser_side_outcome_label_snapshot"
SCHEMA_VERSION = "browser_side_outcome_label_snapshot_v1"
DEFAULT_OUTPUT = Path("validation_outputs/browser_side_outcome_label_snapshot_20260522.json")
BROWSER_FILES = (
    Path("app/browser_ui.html"),
    Path("app/browser_event_forensic_ui.html"),
    Path("app/browser_desktop.py"),
)


def build_browser_label_snapshot(root: str | Path = ".") -> dict[str, object]:
    base = Path(root)
    file_checks = [_check_file(base, relative) for relative in BROWSER_FILES]
    combined = "\n".join(str(item.get("text") or "") for item in file_checks)
    checks = {
        "tokenPriceLabelPresent": "Token price" in combined or "Raw token" in combined,
        "economicProbabilityLabelPresent": "Economic prob" in combined or "Economic probability" in combined or "Economic side" in combined,
        "entryChanceMisleadingLabelAbsent": "Entry chance" not in combined and "entry chance" not in combined.lower(),
        "rawTokenLabelPresent": "Raw token" in combined,
        "sortFilterBehaviorTouchedBySnapshot": False,
        "oldReportFallbackCopyPresent": "unknown" in combined.lower() or "Unavailable" in combined,
    }
    gate = "browser_label_contract_ok"
    if not checks["tokenPriceLabelPresent"] or not checks["economicProbabilityLabelPresent"]:
        gate = "browser_label_contract_needs_copy_fix"
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "root": str(base.resolve()),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeBehaviorChanged": False,
        "uiSortingFilteringChanged": False,
        "savedArtifactsMutated": False,
        "gateDecision": gate,
        "summary": checks,
        "files": [{key: value for key, value in item.items() if key != "text"} for item in file_checks],
        "limitations": [
            "Static text snapshot only; it does not render or interact with the browser UI.",
            "Raw entry-probability filter/sort behavior is reported as unchanged by this sidecar-only snapshot.",
        ],
    }


def write_json(path: str | Path, payload: Mapping[str, object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_browser_label_snapshot(args.root)
    write_json(args.output, report)
    if not args.quiet:
        print(f"gate: {report['gateDecision']}")
        print(f"output: {args.output}")
    return 0


def _check_file(base: Path, relative: Path) -> dict[str, object]:
    path = base / relative
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    return {
        "path": str(relative),
        "exists": path.exists(),
        "tokenPriceLabelPresent": "Token price" in text or "Raw token" in text,
        "economicProbabilityLabelPresent": "Economic prob" in text or "Economic probability" in text or "Economic side" in text,
        "entryChanceMisleadingLabelPresent": "Entry chance" in text or "entry chance" in text.lower(),
        "sortFilterTokensPresent": "sort" in text or "filter" in text,
        "text": text,
    }


if __name__ == "__main__":
    raise SystemExit(main())
