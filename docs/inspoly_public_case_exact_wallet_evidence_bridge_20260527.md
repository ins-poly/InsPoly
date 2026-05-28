# InsPoly Public-Case Exact-Wallet Evidence Bridge

Date: 2026-05-27

Base commit: `2d932ee` - `Add public-case benchmark source labels`

Runtime changed: `false`

Live/RPC used: `false`

Bounded web research used: `true`, for public-source metadata and exact-wallet proof checks only.

Push/PR performed: `false`

Gate decision: `public_case_evidence_bridge_no_safe_upgrade`

## Strategic Campaign Brief Summary

The benchmark already contained 30 compact known cases, including 6 public-source controls with 9 recorded public URLs. The strategic objective was to determine whether any public case can safely move from named-user, pattern-level, or market-level evidence into `exact_wallet_supported`.

The chosen path was conservative: search local artifacts for identity bridges, recheck public sources for explicit wallet/user/market proof, then update the fixture and tooling with evidence-tier controls. No exact-wallet upgrade was made because no inspected source or local artifact proved fixture-grade wallet identity.

## Tier Counts

| Tier | Before | After |
|---|---:|---:|
| `exact_wallet_supported` | 0 | 0 |
| `named_user_local_wallet_candidate` | 0 | 0 |
| `named_user_only` | 2 | 2 |
| `pattern_level_only` | 2 | 2 |
| `market_level_only` | 2 | 2 |
| `insufficient_source_evidence` | 0 | 0 |
| `defer_needs_human_label` | 0 | 0 |

Public-source controls remain 6. Recorded fixture source URLs remain 9. All 6 public controls now carry explicit `identity_confidence`, `local_artifact_refs`, `deferred_reason`, and `human_review_needed` fields.

## Evidence Tier Rules

- `exact_wallet_supported` requires explicit wallet/user/market evidence from a public source or a local artifact that links public identity to wallet identity.
- `named_user_local_wallet_candidate` is allowed only when local artifacts suggest a possible wallet bridge; it still cannot assert exact-wallet truth and must require human review.
- `named_user_only` means a public source names a person/account but does not publish fixture-grade wallet identity.
- `pattern_level_only` cannot assert wallet recall or exact user detection.
- `market_level_only` cannot assert wallet/user detection.
- `insufficient_source_evidence` and `defer_needs_human_label` remain non-executable until stronger labels exist.
- Every non-exact public tier must include `forbidden_interpretation` and `deferred_reason`.

## Local Artifact Linkage

| Public case | Local refs added | What they prove | What they do not prove |
|---|---:|---|---|
| Maduro enforcement named-user | 2 | Local candidate/resolution outputs include Maduro event families. | They do not link Gannon Ken Van Dyke to an exact wallet. |
| Maduro pre-charge market timing | 1 | Local candidate pool includes Maduro market families. | It does not prove any named-user or wallet identity. |
| Iran military cluster pattern | 2 | Local outputs include Iran event/condition evidence and pagination probes. | They do not prove the public Bubblemaps/CBS cluster wallets are the same local wallets. |
| ZachXBT/Axiom pattern | 0 | No safe local bridge found. | No exact wallet assertion. |
| Google Year in Search retrospective | 0 | No safe local bridge found. | No exact wallet assertion. |
| Trump whale high-volume control | 0 | No safe local bridge found. | No exact wallet assertion. |

The local refs are compact metadata pointers only. Raw review packets and generated evidence directories remain local-only and were not imported.

## Public Source Recheck

The recheck confirmed source quality boundaries:

- DOJ/CFTC/Axios Maduro sources support a named-user case and named markets/proceeds, but do not provide a fixture-grade wallet address.
- Atlantic supports anonymous market-timing and retrospective caution cases, not wallet identity.
- CBS/Cointelegraph/CoinDesk Iran/Axiom sources support cluster or pattern-level evidence, but not an exact wallet fixture import.
- Reuters-mirrored Trump whale reporting names account handles/French national context and says Polymarket did not identify manipulation evidence; it does not publish a fixture-grade wallet bridge.
- Supplementary AMBCrypto Iran reporting mentions a partial wallet/user handle; partial wallet evidence remains insufficient.
- Supplementary Cointrenches Fredi9999 reporting lists a wallet, but it is a third-party source outside the existing fixture source chain and was not reconciled to local artifacts, so it was not used for an exact-wallet upgrade.

No article text, raw web pages, or bulky source material was committed.

## Cases Upgraded

None.

This is intentional. Upgrading without a strong identity bridge would make the benchmark look more precise than the evidence supports.

## Deferred Exact-Wallet Candidates

All 6 public controls remain deferred for exact-wallet use:

- `known-public_maduro_enforcement_named_user_control`
- `known-public_maduro_pre_charge_market_timing_control`
- `known-public_iran_military_cluster_pattern_control`
- `known-public_zachxbt_axiom_pattern_control`
- `known-public_google_year_in_search_retrospective_control`
- `known-public_trump_whale_high_volume_control`

Required unblocking evidence:

- public source publishes exact wallet/user/market identity; or
- local artifact links the public identity to wallet identity without inference; or
- human reviewer labels the wallet bridge and records source/provenance.

## What The Benchmark Now Proves

- Public-source cases remain advisory controls unless exact identity is proven.
- Pattern-level and market-level cases cannot be used to test exact wallet recall.
- Named-user public cases cannot be used as scoring/gate/routing evidence.
- Local artifacts can be referenced as context while explicitly preserving `proves_wallet_identity: false`.

## What It Does Not Prove

- It does not prove any public exact-wallet identity.
- It does not validate live source drift.
- It does not authorize runtime/model/scoring changes.
- It does not import local review packet rows or raw public article content.

## Next Allowed Work

- Human-label worksheet for exact-wallet candidates, with source/provenance requirements.
- Separate exact-wallet fixture additions only after source/local-artifact proof exists.
- Keep current public controls in the benchmark as false-positive and overclaiming guardrails.

## Files Changed

- `tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json`
- `tools/curate_known_case_benchmark.py`
- `tools/public_case_evidence_bridge.py`
- `tests/test_known_case_benchmark.py`
- `tests/test_public_case_evidence_bridge.py`
- `validation_outputs/inspoly_public_case_exact_wallet_evidence_bridge_20260527.json`

## Guardrails Preserved

- No runtime/model/scoring/gate change.
- No Phase 3 runtime.
- No storage or UI sorting/filtering change.
- No saved artifact mutation.
- No private-key/CLOB/trading/order-placement code.
- No push/PR.
