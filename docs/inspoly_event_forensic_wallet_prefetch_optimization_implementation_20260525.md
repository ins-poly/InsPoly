# Event Forensic Wallet/Context Optimization Implementation

Date: 2026-05-25

Gate decision: `wallet_prefetch_patch_partial`

## Scope

This campaign implemented a behavior-preserving run-local cache for pure Event
Forensic wallet/context work. It did not change market selection, candidate
admission, scoring weights, thresholds, review routing, exports, storage schema,
or UI sorting.

The patch affects:

- scoped wallet-history filtering during candidate context preparation;
- wallet-history replay-metric reuse during candidate context preparation;
- wallet domain-profile reuse during score-loop annotation;
- additive performance metadata under `performance.wallet_context_reuse`.

The patch does not affect:

- wallet context fetch boundaries;
- `fetch_wallet_stats()` / `fetch_wallet_positions()` request semantics;
- `_score_trade()` or `_event_forensic_score()` scoring formulas;
- weak-history near-certainty review demotion predicate;
- Phase 3 capital-at-risk behavior.

## Behavior Invariants

Static behavior snapshot on the saved high-density subset passed:

- candidate rows checked: 15,353;
- export row keys checked: 15,353;
- candidate identity/order: unchanged in static contract;
- scores/rank/review bucket/export rows: unchanged in static contract;
- weak-history demotion values: preserved.

The live post-patch subset run had source drift versus the prior live run:

- common candidate IDs: 15,341;
- added candidate IDs: 13;
- removed candidate IDs: 13;
- score changes on common IDs: 577;
- review-bucket changes on common IDs: 8;
- weak-history demotion changes on common IDs: 0.

This is treated as live-source drift, not strict equivalence proof. The static
snapshot remains the behavior guard for the patch.

## Measurement Scope

High-density subset:

- event: `us-x-iran-permanent-peace-deal-by`;
- selected markets: same 6-market allowlist from the approved subset package;
- live event size: 15 markets;
- claim: subset-only, not whole-event complete;
- funding traces: disabled;
- storage: isolated validation output directory only;
- raw rows: 31,950;
- candidate rows: 15,354;
- candidate wallets: 3,242;
- truncated markets: 6.

Output:

- `validation_outputs/event_forensic_wallet_prefetch_optimization_measurement_20260525.json`

Raw live bundle is local-only and should not be committed by default:

- `validation_outputs/event_forensic_wallet_prefetch_optimization_live_20260525_195106/`

## Timing Comparison

| Measurement | Raw rows | Candidates | Wallets | Total s | Score s | Wallet prefetch s | Prepare s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pre scorer memoization | 31,919 | 15,353 | 3,239 | 663.47 | 388.20 | 236.57 | 5.31 |
| Post scorer memoization | 31,929 | 15,354 | 3,241 | 644.47 | 353.58 | 249.80 | 4.01 |
| Post wallet/context cache | 31,950 | 15,354 | 3,242 | 703.56 | 338.00 | 316.64 | 4.09 |

Normalized post-scorer to post-wallet/context comparison:

- score seconds per 1,000 candidates: 23.03 -> 22.01, improvement 4.406%;
- prefetch seconds per 1,000 wallets: 77.07 -> 97.67, regression 26.718%;
- total seconds per 1,000 candidates: 41.97 -> 45.82, regression 9.169%;
- prepare seconds per 1,000 candidates: 0.261 -> 0.266, regression 1.995%.

The new cache recorded:

- repeated wallet/context opportunities: 12,112;
- scoped history cache hits: 12,112;
- scoped history cache misses: 3,242;
- domain profile cache hits: 12,112;
- domain profile cache misses: 3,242;
- effective scoped-history reuse ratio: 0.78885;
- effective domain-profile reuse ratio: 0.78885;
- wallet fetch boundary preserved: true.

## Small Controls

| Control | Prior post-scorer s | Post wallet/context s | Candidate delta |
| --- | ---: | ---: | ---: |
| `russia-x-ukraine-ceasefire-by-january-31-2026` | 17.22 | 20.80 | 0 |
| `maduro-in-us-custody-by-january-31` | 16.37 | 24.21 | 0 |

Both controls completed, but total time worsened due wallet prefetch / trade
collection variability. Candidate counts did not change.

## Decision

Gate: `wallet_prefetch_patch_partial`

Reason:

- behavior-preserving static contract passed;
- score loop improved again on the high-density subset;
- the cache produced high reuse in pure wallet/context transforms;
- total runtime did not improve because live wallet prefetch became slower;
- small controls also worsened in total time, indicating network/API prefetch
  variability remains the larger unresolved bottleneck.

## Remaining Risks

- Wallet context fetching still requires one stats/positions context per unique
  wallet and remains sensitive to API/network latency.
- Truncated markets remain present in the high-density subset.
- Whole-event completeness is still not proven for the 15-market event.
- Live source drift prevents strict live candidate equality across runs.

## Rollback

The patch is local and reversible:

- remove the scoped wallet-history cache in `_prepare_candidate_contexts`;
- remove cached domain-profile calls in `_annotate_wallet_domain_diversity`;
- remove `performance.wallet_context_reuse` metadata.

Rollback should not require schema migration or saved artifact mutation.
