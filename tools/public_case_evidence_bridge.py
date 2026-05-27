#!/usr/bin/env python3
"""Summarize public-case benchmark evidence tiers without live access.

The bridge is sidecar-only. It validates that public-source benchmark cases do
not overclaim exact-wallet identity unless the fixture carries explicit proof.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.curate_known_case_benchmark import DEFAULT_OUTPUT as DEFAULT_CORPUS
from tools.curate_known_case_benchmark import validate_known_case_corpus


REPORT_TYPE = "public_case_exact_wallet_evidence_bridge"
SCHEMA_VERSION = "public_case_evidence_bridge_v1"
DEFAULT_OUTPUT = Path("validation_outputs/inspoly_public_case_exact_wallet_evidence_bridge_20260527.json")
PUBLIC_ASSERTION_TIERS = {
    "exact_wallet_supported",
    "named_user_local_wallet_candidate",
    "named_user_only",
    "pattern_level_only",
    "market_level_only",
    "insufficient_source_evidence",
    "defer_needs_human_label",
}
SOURCE_RECHECK_FINDINGS = [
    {
        "case_id": "known-public_maduro_enforcement_named_user_control",
        "finding": "DOJ/CFTC/Axios sources support named-user Maduro trading and proceeds, but do not publish a fixture-grade wallet address.",
        "exact_wallet_supported": False,
    },
    {
        "case_id": "known-public_maduro_pre_charge_market_timing_control",
        "finding": "Axios/Atlantic sources support suspicious timing and public-knowledge context, not wallet identity.",
        "exact_wallet_supported": False,
    },
    {
        "case_id": "known-public_iran_military_cluster_pattern_control",
        "finding": "CBS/Cointelegraph/CoinDesk reporting supports connected-account pattern evidence; inspected text does not provide exact wallet labels suitable for fixture truth.",
        "exact_wallet_supported": False,
    },
    {
        "case_id": "known-public_zachxbt_axiom_pattern_control",
        "finding": "CoinDesk/Cointelegraph sources describe concentrated wallets and Dune/source screenshots, but the fixture keeps this pattern-level without importing partial or image-only wallet labels.",
        "exact_wallet_supported": False,
    },
    {
        "case_id": "known-public_google_year_in_search_retrospective_control",
        "finding": "Atlantic source supports a retrospective public example only; no primary wallet/source bridge was found.",
        "exact_wallet_supported": False,
    },
    {
        "case_id": "known-public_trump_whale_high_volume_control",
        "finding": "Reuters-mirrored source names account handles/French national context but says Polymarket did not identify manipulation evidence and does not publish exact wallet identity.",
        "exact_wallet_supported": False,
    },
]
SUPPLEMENTARY_SOURCE_FINDINGS = [
    {
        "url": "https://ambcrypto.com/bubblemaps-trace-polymarket-accounts-linked-to-iran-strike-bets/",
        "finding": "Mentions a partial Iran wallet/user handle, but partial wallet evidence is not enough for exact-wallet fixture truth.",
        "used_for_fixture_upgrade": False,
    },
    {
        "url": "https://cointrenches.io/fredi9999-polymarket-trump-election-whale-85m/",
        "finding": "Lists a Fredi9999 wallet, but this third-party blog is not the fixture source and was not reconciled to local artifacts; kept out of exact-wallet assertions.",
        "used_for_fixture_upgrade": False,
    },
]


def build_public_case_evidence_bridge(
    corpus_path: str | Path = DEFAULT_CORPUS,
    *,
    root: str | Path = ".",
) -> dict[str, object]:
    corpus_file = Path(corpus_path)
    repo_root = Path(root)
    corpus = json.loads(corpus_file.read_text(encoding="utf-8"))
    schema_errors = validate_known_case_corpus(corpus)
    cases = [case for case in corpus.get("cases", []) if isinstance(case, Mapping)]
    public_cases = [case for case in cases if case.get("assertion_type") == "public_case_control"]
    case_results = [_case_result(case, repo_root) for case in public_cases]
    tier_counts = Counter(str(case.get("assertion_level") or "unknown") for case in public_cases)
    source_urls = sorted(
        {
            str(url)
            for case in public_cases
            for url in _as_list(case.get("source_urls"))
            if str(url).strip()
        }
    )
    local_refs = [
        ref
        for case in case_results
        for ref in _as_list(case.get("localArtifactRefs"))
        if isinstance(ref, Mapping)
    ]
    deferred = [
        {
            "case_id": str(case.get("case_id") or ""),
            "assertion_level": str(case.get("assertion_level") or ""),
            "deferred_reason": str(case.get("deferred_reason") or ""),
            "human_review_needed": bool(case.get("human_review_needed")),
        }
        for case in public_cases
        if str(case.get("assertion_level") or "") != "exact_wallet_supported"
    ]
    summary = {
        "publicCaseCount": len(public_cases),
        "tierCounts": dict(sorted(tier_counts.items())),
        "exactWalletSupportedCount": tier_counts.get("exact_wallet_supported", 0),
        "namedUserLocalWalletCandidateCount": tier_counts.get("named_user_local_wallet_candidate", 0),
        "namedUserOnlyCount": tier_counts.get("named_user_only", 0),
        "patternLevelOnlyCount": tier_counts.get("pattern_level_only", 0),
        "marketLevelOnlyCount": tier_counts.get("market_level_only", 0),
        "insufficientSourceEvidenceCount": tier_counts.get("insufficient_source_evidence", 0),
        "deferNeedsHumanLabelCount": tier_counts.get("defer_needs_human_label", 0),
        "publicSourceUrlCount": len(source_urls),
        "localArtifactRefCount": len(local_refs),
        "localArtifactRefsThatProveWalletIdentity": sum(1 for ref in local_refs if ref.get("proves_wallet_identity") is True),
        "casesRequiringHumanReview": sum(1 for case in public_cases if case.get("human_review_needed") is True),
        "schemaErrorCount": len(schema_errors),
    }
    return {
        "reportType": REPORT_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=UTC).isoformat(),
        "corpusPath": str(corpus_file),
        "sidecarOnly": True,
        "networkUsed": False,
        "runtimeBehaviorChanged": False,
        "savedArtifactsMutated": False,
        "productionIntegration": False,
        "gateDecision": _gate(summary),
        "summary": summary,
        "publicSourceUrls": source_urls,
        "sourceRecheck": {
            "boundedWebResearchUsed": True,
            "fixtureSourceUrlsRechecked": len(source_urls),
            "supplementarySourcesConsidered": len(SUPPLEMENTARY_SOURCE_FINDINGS),
            "articleTextPersisted": False,
            "exactWalletEvidenceFound": False,
            "findings": SOURCE_RECHECK_FINDINGS,
            "supplementaryFindings": SUPPLEMENTARY_SOURCE_FINDINGS,
        },
        "deferredExactWalletCandidates": deferred,
        "schemaErrors": list(schema_errors),
        "caseResults": case_results,
    }


def write_json(path: str | Path, payload: Mapping[str, object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = build_public_case_evidence_bridge(args.corpus, root=args.root)
    write_json(args.output, report)
    if not args.quiet:
        summary = report["summary"]
        print(f"public cases: {summary['publicCaseCount']}")
        print(f"exact wallet: {summary['exactWalletSupportedCount']}")
        print(f"gate: {report['gateDecision']}")
    return 0 if not report["schemaErrors"] else 1


def _case_result(case: Mapping[str, object], repo_root: Path) -> dict[str, object]:
    local_refs = []
    for ref in _as_list(case.get("local_artifact_refs")):
        if not isinstance(ref, Mapping):
            continue
        path = str(ref.get("path") or "")
        local_refs.append(
            {
                "path": path,
                "pathExists": bool(path and (repo_root / path).exists()),
                "match": str(ref.get("match") or ""),
                "confidence": str(ref.get("confidence") or ""),
                "proves_wallet_identity": bool(ref.get("proves_wallet_identity")),
            }
        )
    expected = case.get("expected_result") if isinstance(case.get("expected_result"), Mapping) else {}
    return {
        "case_id": str(case.get("case_id") or ""),
        "category": str(case.get("category") or ""),
        "assertionLevel": str(case.get("assertion_level") or ""),
        "identityConfidence": str(case.get("identity_confidence") or ""),
        "wallet": str(case.get("wallet") or ""),
        "market": str(case.get("market") or ""),
        "event": str(case.get("event") or ""),
        "sourceUrlCount": len(_as_list(case.get("source_urls"))),
        "localArtifactRefs": local_refs,
        "exactWalletDetectionAllowed": expected.get("exact_wallet_detection_allowed"),
        "humanReviewNeeded": bool(case.get("human_review_needed")),
        "deferredReason": str(case.get("deferred_reason") or ""),
    }


def _gate(summary: Mapping[str, object]) -> str:
    if summary.get("schemaErrorCount", 0):
        return "public_case_benchmark_blocked_by_source_quality"
    if summary.get("exactWalletSupportedCount", 0):
        return "public_case_exact_wallet_evidence_found"
    if summary.get("namedUserLocalWalletCandidateCount", 0):
        return "public_case_named_user_local_candidates_only"
    if summary.get("publicCaseCount", 0) and not summary.get("localArtifactRefsThatProveWalletIdentity", 0):
        return "public_case_evidence_bridge_no_safe_upgrade"
    return "public_case_pattern_level_confirmed"


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


if __name__ == "__main__":
    raise SystemExit(main())
