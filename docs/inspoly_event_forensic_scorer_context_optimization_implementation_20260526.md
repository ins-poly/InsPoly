# Event Forensic Scorer Context Optimization Implementation

Date: 2026-05-26

## Gate

`scorer_context_patch_partial`

## Scope

This campaign implemented a narrow behavior-preserving scorer-context preparation patch. It did not change `_score_trade()` scoring semantics, `_event_forensic_score()` semantics, scoring weights, thresholds, candidate admission, Strong Risk/HER/funding gates, review routing, exports, storage schema, Phase 3 capital-at-risk behavior, or UI sorting/filtering.

Changed runtime surface:

- `app/scanner.py`
  - added `ScoreTradePreparedContext`;
  - added `build_score_trade_prepared_context()`;
  - added optional `prepared_context` input to `_score_trade()`;
  - default path remains unchanged for scanner/archive callers that do not pass prepared context.
- `app/event_forensic.py`
  - prepares the same score-call context fragments once per candidate during Event Forensic context preparation;
  - passes the prepared context to `_score_trade()`;
  - emits additive `performance.score_trade_prepared_context` counters.
- `app/event_forensic_performance.py`
  - adds pure metadata helper for prepared-context coverage.

## Optimization

The prepared context covers pure repeated scorer fragments:

- same-outcome market trades;
- same-market wallet trades;
- prior same-market trades;
- prior same-asset trades;
- related 30-minute wallet-window trades;
- wallet baseline notionals;
- wallet market conviction ratio.

The patch intentionally does not memoize final scores. The input audit found exact score-call duplicate-equivalent signatures are rare: 15 rows in repeated exact-signature groups out of 15,353 rows (`0.0977%` reuse ratio). Context fragments, not final score results, are the safe reuse target.

## Behavior Equivalence

Static saved-subset snapshot:

- Candidate rows checked: 15,353
- Export row keys checked: 15,353
- Contract self-comparison: passed
- Network used: false
- Runtime behavior changed by static snapshot: false

Focused direct scorer test also compares `_score_trade()` with and without a prepared context and asserts identical score, severity, flags, and raw metrics.

## Timing Comparison

| Run | Raw rows | Candidates | Wallets | Total s | Score s | Wallet prefetch s | Prepare s | Score s / 1k candidates |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pre scorer memoization | 31,919 | 15,353 | 3,239 | 663.47 | 388.20 | 236.57 | 5.31 | 25.285 |
| Post scorer memoization | 31,929 | 15,354 | 3,241 | 644.47 | 353.58 | 249.80 | 4.01 | 23.029 |
| Post wallet/context cache | 31,950 | 15,354 | 3,242 | 703.56 | 338.00 | 316.64 | 4.09 | 22.014 |
| Post scorer-context profile | 31,992 | 15,354 | 3,287 | 645.17 | 339.83 | 266.20 | 6.66 | 22.133 |
| Post prepared scorer context | 31,980 | 15,354 | 3,292 | 678.99 | 318.00 | 303.42 | 17.17 | 20.711 |

Compared with the scorer-context profile run:

- Score loop improved by 21.83s / 6.424% normalized.
- `_score_trade()` bucket improved from 332.66s to 310.91s.
- Total runtime worsened by 33.82s / 5.242% normalized.
- Wallet prefetch worsened by 37.22s / 13.809% normalized.
- Prepare context time increased from 6.66s to 17.17s because context fragments are built before scoring.

Prepared-context counters:

- `preparedContextRows`: 15,354
- `scoreCallCount`: 15,354
- `fallbackContextRows`: 0
- `preparedContextCoverageRatio`: 1.0
- `scoreCallCountUnchanged`: true

## Interpretation

The patch reduces score-loop cost but does not close the total runtime blocker. The improvement is real inside the scorer path, but current live measurements are still dominated by wallet prefetch/API variance plus high-density subset data movement. Because candidate count and score-call count are unchanged, this is a partial behavior-preserving improvement, not a complete performance fix.

## Remaining Bottleneck

The optimized run still reports `score_candidates_seconds` as the dominant measured stage, but wallet prefetch is close behind and worsened in this live sample:

- Score loop: 318.00s
- Wallet prefetch: 303.42s
- Prepare candidate context: 17.17s

Inside the score loop, `_score_trade()` remains the dominant bucket:

- `_score_trade()` call: 310.912613s / 97.7726%
- Wallet-domain profile annotation: 6.901139s / 2.1702%

## Next Work

Recommended next action: do not stack another scorer-context runtime patch immediately. The next highest-value work is either:

1. wallet API-boundary batching RFC / pagination operator plan, because prefetch variance is now comparable to score time; or
2. finer `_score_trade()` internal profiling if the owner wants one more pure local scorer pass.

Any follow-up runtime patch must again prove identical candidate IDs, scores, ranks, review buckets, weak-history demotion, and exports.

## Rollback

Rollback can remove:

- `ScoreTradePreparedContext`;
- `build_score_trade_prepared_context()`;
- the optional `prepared_context` path in `_score_trade()`;
- Event Forensic prepared-context construction and metadata.

No saved report mutation or storage migration is required.
