#!/usr/bin/env python3
"""Analyze pagination/completeness evidence from bounded measurement output."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "archive_event_pagination_measurement_analysis"
SCHEMA_VERSION = "archive_event_pagination_measurement_analysis_v1"
DEFAULT_COMPLETENESS_AUDIT = Path("validation_outputs/archive_event_completeness_audit_20260525.json")
DEFAULT_OUTPUT = Path("validation_outputs/archive_event_pagination_measurement_analysis_20260525.json")
DEFAULT_MARKDOWN = Path("docs/inspoly_archive_event_pagination_measurement_analysis_20260525.md")


def build_pagination_measurement_analysis(
    measurement_summary: Mapping[str, object],
    completeness_audit: Mapping[str, object],
) -> dict[str, object]:
    measurement_gate = _measurement_gate(measurement_summary)
    live_result = measurement_summary.get("liveResult") if isinstance(measurement_summary.get("liveResult"), Mapping) else {}
    report_summary = measurement_summary.get("reportSummary") if isinstance(measurement_summary.get("reportSummary"), Mapping) else {}
    local_summary = completeness_audit.get("summary") if isinstance(completeness_audit.get("summary"), Mapping) else {}
    selected_target = {}
    target_selection = measurement_summary.get("targetSelection")
    if isinstance(target_selection, Mapping) and isinstance(target_selection.get("selectedTarget"), Mapping):
        selected_target = dict(target_selection.get("selectedTarget") or {})
    findings = _findings(measurement_gate, live_result, report_summary, selected_target, local_summary)
    gate = _gate(measurement_gate, findings)
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": bool(measurement_summary.get("networkUsed")),
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "storageMutated": False,
        "measurementGate": measurement_gate,
        "gateDecision": gate,
        "measurement": {
            "outputDir": str(measurement_summary.get("outputDir") or ""),
            "eventSlug": _text(report_summary.get("eventSlug") or live_result.get("eventSlug") or selected_target.get("eventSlug")),
            "status": _text(live_result.get("status")),
            "error": _text(live_result.get("error")),
            "savedAnalysisMarketCount": _int_or_none(selected_target.get("analysisMarketCount")),
            "resolvedMarketCount": _resolved_market_count(live_result),
            "analysisMarketCount": _int_or_none(report_summary.get("analysisMarketCount")),
            "rawTradeCount": _int_or_none(report_summary.get("rawTradeCount")),
            "candidateTradeCount": _int_or_none(report_summary.get("candidateTradeCount")),
            "truncatedMarketCount": _int_or_none(report_summary.get("truncatedMarketCount")),
        },
        "localCompletenessSummary": {
            "reportsEvaluated": local_summary.get("reportsEvaluated", 0),
            "truncatedReportedCount": local_summary.get("truncatedReportedCount", 0),
            "unknownLegacyCount": local_summary.get("unknownLegacyCount", 0),
            "candidateAdmissionRiskReports": local_summary.get(
                "candidateAdmissionRiskReports",
                local_summary.get("candidateAdmissionRiskReportCount", 0),
            ),
            "rankingRiskReports": local_summary.get("rankingRiskReports", local_summary.get("rankingRiskReportCount", 0)),
        },
        "findings": findings,
        "recommendation": _recommendation(gate),
    }


def write_json(payload: Mapping[str, object], output_path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def write_markdown_report(path: str | Path, analysis: Mapping[str, object]) -> Path:
    target = Path(path)
    measurement = analysis.get("measurement") if isinstance(analysis.get("measurement"), Mapping) else {}
    local = analysis.get("localCompletenessSummary") if isinstance(analysis.get("localCompletenessSummary"), Mapping) else {}
    findings = analysis.get("findings") if isinstance(analysis.get("findings"), list) else []
    lines = [
        "# Archive/Event Pagination Measurement Analysis",
        "",
        f"Date: {datetime.now(tz=UTC).date().isoformat()}",
        "",
        f"Gate: `{analysis.get('gateDecision', 'unknown')}`",
        "",
        "This report combines the bounded live measurement/precheck output with the existing local completeness audit. It does not change pagination, candidate admission, scoring, ranking, storage, or saved artifacts.",
        "",
        "## Measurement Input",
        "",
        f"- Measurement gate: `{analysis.get('measurementGate', 'unknown')}`",
        f"- Output directory: `{analysis.get('measurement', {}).get('outputDir', '') if isinstance(analysis.get('measurement'), Mapping) else ''}`",
        f"- Event slug: `{measurement.get('eventSlug', '')}`",
        f"- Live status: `{measurement.get('status', '')}`",
        f"- Live error: `{measurement.get('error', '')}`",
        f"- Saved analysis markets: {measurement.get('savedAnalysisMarketCount')}",
        f"- Resolved live markets: {measurement.get('resolvedMarketCount')}",
        f"- Runtime behavior changed: {analysis.get('runtimeBehaviorChanged', False)}",
        "",
        "## Local Completeness Baseline",
        "",
        f"- Reports evaluated: {local.get('reportsEvaluated', 0)}",
        f"- Explicit truncation reports: {local.get('truncatedReportedCount', 0)}",
        f"- Unknown legacy reports: {local.get('unknownLegacyCount', 0)}",
        f"- Candidate-admission risk reports: {local.get('candidateAdmissionRiskReports', 0)}",
        f"- Ranking-risk reports: {local.get('rankingRiskReports', 0)}",
        "",
        "## Findings",
        "",
    ]
    lines.extend(f"- {item}" for item in findings)
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            str(analysis.get("recommendation", "")),
        ]
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target


def load_json_object(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _measurement_gate(summary: Mapping[str, object]) -> str:
    nested = summary.get("summary") if isinstance(summary.get("summary"), Mapping) else {}
    return _text(nested.get("gateDecision") or summary.get("gateDecision"))


def _findings(
    measurement_gate: str,
    live_result: Mapping[str, object],
    report_summary: Mapping[str, object],
    selected_target: Mapping[str, object],
    local_summary: Mapping[str, object],
) -> list[str]:
    findings: list[str] = []
    if measurement_gate == "performance_measurement_blocked_scope_risk":
        saved = _int_or_none(selected_target.get("analysisMarketCount"))
        resolved = _int_or_none(live_result.get("resolvedMarketCount"))
        if resolved is not None and saved is not None and resolved > saved:
            findings.append(
                f"Live target scope drifted from {saved} saved analysis market(s) to {resolved} resolved market(s), exceeding the bounded campaign limit."
            )
        else:
            findings.append("Live measurement was blocked by scope-risk bounds before full analysis.")
    if (_int_or_none(report_summary.get("truncatedMarketCount")) or 0) > 0:
        findings.append("Completed measurement reported truncated markets.")
    if (_int_or_none(local_summary.get("truncatedReportedCount")) or 0) > 0:
        findings.append("Local completeness audit already contains explicit truncated-report evidence.")
    if (_int_or_none(local_summary.get("unknownLegacyCount")) or 0) > 0:
        findings.append("Legacy reports without current completeness metadata remain unknown and must not be reinterpreted as complete.")
    if not findings:
        findings.append("No pagination/truncation issue was visible in the combined evidence.")
    return findings


def _gate(measurement_gate: str, findings: Sequence[str]) -> str:
    if measurement_gate == "performance_measurement_complete":
        if any("truncated" in item.lower() for item in findings):
            return "pagination_needs_operator_plan"
        return "pagination_live_measurement_clean"
    if measurement_gate == "performance_measurement_blocked_scope_risk":
        return "pagination_needs_operator_plan"
    return "pagination_inconclusive"


def _recommendation(gate: str) -> str:
    if gate == "pagination_live_measurement_clean":
        return "No pagination patch is justified by this measurement. Keep local completeness audit coverage."
    if gate == "pagination_needs_operator_plan":
        return (
            "Do not broaden pagination automatically. A future operator run needs an exact bounded target or approved market subset before any live expansion."
        )
    return "Evidence is inconclusive; preserve current pagination behavior and collect a narrower bounded measurement before patching."


def _text(value: object) -> str:
    return str(value or "").strip()


def _int_or_none(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _resolved_market_count(live_result: Mapping[str, object]) -> int | None:
    direct = _int_or_none(live_result.get("resolvedMarketCount"))
    if direct is not None:
        return direct
    total = _int_or_none(live_result.get("totalEventMarketCount"))
    if total is not None:
        return total
    target = live_result.get("resolvedTarget")
    if isinstance(target, Mapping):
        count = _int_or_none(target.get("marketCount"))
        if count is not None:
            return count
        event = target.get("event")
        if isinstance(event, Mapping):
            return _int_or_none(event.get("marketCount"))
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurement-summary", required=True)
    parser.add_argument("--completeness-audit", default=str(DEFAULT_COMPLETENESS_AUDIT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown", default=str(DEFAULT_MARKDOWN))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    analysis = build_pagination_measurement_analysis(
        load_json_object(args.measurement_summary),
        load_json_object(args.completeness_audit),
    )
    write_json(analysis, args.output)
    write_markdown_report(args.markdown, analysis)
    if not args.quiet:
        print(json.dumps({"gate": analysis["gateDecision"], "output": args.output, "markdown": args.markdown}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
