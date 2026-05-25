#!/usr/bin/env python3
"""Build final strategic long-run campaign summary JSON outputs."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence


REPORT_TYPE = "inspoly_strategic_long_run_campaign_summary"
SCHEMA_VERSION = "inspoly_strategic_long_run_campaign_summary_v1"
DEFAULT_SUMMARY_OUTPUT = Path("validation_outputs/inspoly_strategic_long_run_campaign_summary_20260522.json")
DEFAULT_PHASE3_OUTPUT = Path("validation_outputs/inspoly_phase3_capital_unblock_requirements_20260522.json")


PROGRAM_OUTPUTS = {
    "event_forensic_saved_report_reliability": Path("validation_outputs/event_forensic_weak_history_saved_report_audit_20260522.json"),
    "benchmark_suite_v2_productization": Path("validation_outputs/inspoly_benchmark_suite_v2_20260522.json"),
    "event_level_semantics_evidence_hardening": Path("validation_outputs/event_level_semantics_evidence_audit_20260522.json"),
    "archive_visibility_monitoring_v2": Path("validation_outputs/archive_visibility_monitoring_v2_20260522.json"),
    "browser_label_compatibility_snapshot": Path("validation_outputs/browser_side_outcome_label_snapshot_20260522.json"),
}


def build_phase3_unblock_requirements(root: str | Path = ".") -> dict[str, object]:
    base = Path(root)
    phase3 = _read_json(base / "side_outcome_audits/side_outcome_phase3_capital_at_risk_audit_20260522.json")
    summary = _mapping(phase3.get("summary"))
    return {
        "reportType": "phase3_capital_unblock_requirements",
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeBehaviorChanged": False,
        "gateDecision": "phase3_unblock_requirements_documented_keep_blocked",
        "sourceAuditGate": phase3.get("gateDecision", "unknown"),
        "sourceAuditSummary": summary,
        "requiredSourceFields": {
            "buyExposure": ["raw order side", "raw token outcome", "raw token price", "share size", "observed cash field when available"],
            "sellMaxLossExposure": ["raw order side", "raw token outcome", "raw token price", "share size", "collateral/max-loss source or auditable complement formula"],
            "oldRows": ["must preserve original notional fields", "must mark missing side/outcome/price/size as unsafe"],
        },
        "blockedReasons": [
            "SELL rows require complement max-loss accounting rather than raw fill notional.",
            "usdcSize is observed cash/fill value and is not automatically a verified max-loss collateral field.",
            "Old notional-only rows are permanently unsafe for reinterpretation without side/outcome/price/size provenance.",
            "Sensitive funding/HER/Strong Risk contexts overlap capital deltas and require separate approval.",
        ],
        "testsRequiredBeforeRuntime": [
            "BUY YES/NO cash-paid exposure stays unchanged when source fields are complete.",
            "SELL YES/NO complement max-loss uses size * (1 - raw token price) only with sufficient source quality.",
            "usdcSize source disagreement is reported, not hidden.",
            "old/lossy rows remain unrescored.",
            "funding/HER/Strong Risk gates do not directly mutate without explicit approval.",
        ],
        "liveOrArtifactEvidenceRequired": [
            "bounded real artifact sample with side/outcome/price/size/usdcSize coverage",
            "source-quality distribution for SELL rows",
            "sensitive-overlap review packet with no gate tuning",
        ],
    }


def build_final_summary(root: str | Path = ".") -> dict[str, object]:
    base = Path(root)
    outputs = {key: _read_json(base / path) for key, path in PROGRAM_OUTPUTS.items()}
    phase3 = build_phase3_unblock_requirements(base)
    gates = {key: str(payload.get("gateDecision") or "unknown") for key, payload in outputs.items()}
    gates["phase3_capital_unblock_requirements"] = str(phase3["gateDecision"])
    final_gate = "long_run_campaign_complete_with_live_rpc_blocker"
    if any(gate.endswith("_bug_found") or gate.endswith("_needs_fix") for gate in gates.values()):
        final_gate = "long_run_campaign_needs_fix"
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "sidecarOnly": True,
        "networkUsed": False,
        "productionIntegration": False,
        "runtimeBehaviorChanged": False,
        "stagingCommitPushPerformed": False,
        "gateDecision": final_gate,
        "programGates": gates,
        "closed": [
            "saved-report Event Forensic weak-history contract audit is reproducible locally",
            "benchmark suite v2 registry and runner are local-only",
            "event-level semantics evidence is hardened without runtime scope change",
            "archive visibility monitoring v2 is local-only",
            "browser label compatibility snapshot distinguishes token price and economic probability",
            "Phase 3 unblock requirements are concrete while runtime remains blocked",
        ],
        "blocked": [
            "bounded live/RPC Event Forensic weak-history near-certainty validation",
            "Phase 3 capital-at-risk runtime implementation",
            "event-level runtime scope changes",
            "scoring weights/thresholds/direct gates/storage/UI sorting/live indexing",
        ],
        "approvalRequired": [
            "live/RPC/operator run for remembered weak-history case family",
            "product/user approval for event-level scope UI/semantics",
            "separate approval for Phase 3 or any direct Strong Risk/HER/funding/candidate-admission changes",
            "staging/commit policy decision",
        ],
        "bugsFound": [],
        "runtimeFixesApplied": [],
        "nextHighestValueCampaign": "bounded Event Forensic weak-history near-certainty validation with operator-approved saved/live inputs",
    }


def write_json(path: str | Path, payload: Mapping[str, object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--summary-output", default=str(DEFAULT_SUMMARY_OUTPUT))
    parser.add_argument("--phase3-output", default=str(DEFAULT_PHASE3_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    phase3 = build_phase3_unblock_requirements(args.root)
    summary = build_final_summary(args.root)
    write_json(args.phase3_output, phase3)
    write_json(args.summary_output, summary)
    if not args.quiet:
        print(f"phase3: {args.phase3_output}")
        print(f"summary: {args.summary_output}")
        print(f"gate: {summary['gateDecision']}")
    return 0


def _read_json(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


if __name__ == "__main__":
    raise SystemExit(main())
