# Event Forensic Performance Patch Post-Measurement - 2026-05-25

## Gate

`patch_partial_needs_next_optimization`

## Context

Compared commits:

- Pre-patch baseline evidence: `3b97fc7` subset-only measurement for `us-x-iran-permanent-peace-deal-by`.
- RFC: `ffa8374` (`docs/inspoly_event_forensic_performance_patch_rfc_20260525.md`).
- Implemented patch: `3bf03ce` (`Add behavior-preserving Event Forensic scorer memoization`).

The post-patch run used the same approved 6-market subset identities from the saved-report family. It did not claim whole-event completeness; the live event still resolved to 15 markets.

## Bounds And Scope

- Event: `us-x-iran-permanent-peace-deal-by`
- Scope: subset-only, 6 selected markets out of 15 live event markets
- Raw row cap: 50,000
- Wall-time cap: 30 minutes
- Funding traces: disabled
- Storage: isolated validation output directory
- Private keys/CLOB auth/trading/order placement: not used
- Normal saved reports/artifacts: not mutated

Post-patch output directory:

`validation_outputs/event_forensic_performance_patch_post_measurement_20260525_190410/`

## Behavior Equivalence

Static equivalence passed before live measurement:

- Candidate rows checked: 15,353
- Export row keys checked: 15,353
- Gate: `static_equivalence_passed`

Live before/after output cannot be treated as strict behavioral equivalence because current live data drifted slightly:

- Raw rows: +10
- Candidate rows: +1
- Candidate wallets: +2
- Candidate IDs added: 34
- Candidate IDs removed: 33
- Common-ID score changes: 269
- Common-ID review bucket changes: 14
- Weak-history demotion changes on common IDs: 0

Interpretation: static behavior contract and tests remain the behavior guard; live output drift is small and consistent with changed live source data.

## Timing Comparison

| Metric | Pre-patch | Post-patch | Delta | Improvement |
|---|---:|---:|---:|---:|
| Total seconds | 663.47 | 644.47 | -19.00 | 2.864% |
| Score candidates seconds | 388.20 | 353.58 | -34.62 | 8.918% |
| Wallet prefetch seconds | 236.57 | 249.80 | +13.23 | -5.592% |
| Raw rows | 31,919 | 31,929 | +10 | n/a |
| Candidate rows | 15,353 | 15,354 | +1 | n/a |
| Candidate wallets | 3,239 | 3,241 | +2 | n/a |
| Truncated markets | 6 | 6 | 0 | n/a |

Normalized comparison:

| Metric | Pre-patch | Post-patch | Improvement |
|---|---:|---:|---:|
| Total seconds / 1k candidates | 43.214356 | 41.974078 | 2.870% |
| Score seconds / 1k candidates | 25.284961 | 23.028527 | 8.924% |
| Prefetch seconds / 1k wallets | 73.037975 | 77.074977 | -5.527% |
| Total seconds / 1k raw rows | 20.786052 | 20.184472 | 2.894% |

## Memoization Counters

Post-patch memoization metadata:

- Candidate rows: 15,354
- Unique wallets: 3,241
- Unique markets: 6
- Unique domains: 1
- Repeated wallet/candidate opportunities: 12,113
- Estimated cache hits: 12,113
- Estimated cache misses: 3,241
- Effective reuse ratio: 0.788915
- Cache scopes: wallet-window trades, market notional samples, domain notional samples, funding resolver health

## Small-Target Controls

| Target | Pre-patch | Post-patch | Candidate delta | Improvement |
|---|---:|---:|---:|---:|
| `russia-x-ukraine-ceasefire-by-january-31-2026` | 20.54s | 17.22s | 0 | 16.164% |
| `maduro-in-us-custody-by-january-31` | 22.44s | 16.37s | 0 | 27.050% |

These controls suggest the patch does not harm small Event Forensic runs, but they are not representative of large whole-event/subset density.

## Decision

Gate: `patch_partial_needs_next_optimization`.

Reason:

- Behavior contract held statically.
- High-density score loop improved by ~8.9% normalized per candidate.
- Total runtime improved by ~2.9%.
- The run remains large and slow: `score_candidates_seconds` is still the dominant bottleneck at 353.58s, and wallet prefetch rose to 249.80s.
- Pagination/truncation remains unresolved: 6 of 6 subset markets were truncated.

The scorer memoization patch should stay. It is behavior-preserving and measurably helps, but it is not enough to close high-density performance risk.

## Next Recommended Campaign

Create and review a behavior-preserving wallet/context prefetch optimization RFC, while also profiling deeper scorer-context work. Do not change candidate admission, scoring weights, thresholds, review routing, storage schema, Phase 3, or UI sorting/filtering.

Related RFC:

`docs/inspoly_event_forensic_wallet_prefetch_optimization_rfc_20260525.md`
