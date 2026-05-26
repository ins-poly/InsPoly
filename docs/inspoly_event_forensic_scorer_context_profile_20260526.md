# Event Forensic Scorer Context Profile

Date: 2026-05-26

## Scope

This campaign reviewed the Event Forensic wallet/context cache introduced in `eae111e` after a high-density subset run showed ambiguous performance:

- Pre scorer memoization: 663.47s total, 388.20s scoring, 236.57s wallet prefetch.
- After scorer memoization (`338b559`): 644.47s total, 353.58s scoring, 249.80s wallet prefetch.
- After wallet/context cache (`eae111e`): 703.56s total, 338.00s scoring, 316.64s wallet prefetch.

The new measurement reused the same approved subset-only target:

- Event: `us-x-iran-permanent-peace-deal-by`
- Scope: 6 selected markets out of 15 live markets.
- Claim boundary: subset-only performance evidence, not whole-event completeness.
- Output: `validation_outputs/event_forensic_scorer_context_profile_live_20260526_112806/`

No Phase 3 capital runtime, scorer tuning, gate change, storage schema change, UI sorting change, private key, CLOB auth, trading, or order placement was used.

## Static Equivalence

Static saved-subset equivalence was rerun before the live measurement.

- Candidate rows checked: 15,353
- Export row keys checked: 15,353
- Candidate contract self-comparison: passed
- Network used by static check: false
- Runtime behavior changed by static check: false

The profiler adds timing metadata only. It does not change candidate admission, scores, ranks, review buckets, weak-history demotion, or export rows.

## Timing Comparison

| Run | Raw rows | Candidates | Wallets | Total s | Score s | Wallet prefetch s | Prepare s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pre scorer memoization | 31,919 | 15,353 | 3,239 | 663.47 | 388.20 | 236.57 | 5.31 |
| Post scorer memoization | 31,929 | 15,354 | 3,241 | 644.47 | 353.58 | 249.80 | 4.01 |
| Post wallet/context cache | 31,950 | 15,354 | 3,242 | 703.56 | 338.00 | 316.64 | 4.09 |
| Post scorer-context profile | 31,992 | 15,354 | 3,287 | 645.17 | 339.83 | 266.20 | 6.66 |

Normalized against the post-scorer baseline, the profile run was effectively flat on total runtime (-0.109% normalized total change), improved normalized scoring by 3.889%, and worsened normalized prefetch by 5.074%. Compared with the ambiguous `eae111e` live run, the profile run improved total runtime by 8.299% and prefetch time by 17.081%.

## Profiler Buckets

The score-loop profiler found that most scoring time is still inside `_score_trade()`:

| Bucket | Seconds | Share of score loop | Seconds/candidate |
| --- | ---: | ---: | ---: |
| `score_trade_call` | 332.662750 | 97.8917% | 0.021666 |
| `wallet_domain_profile_annotation` | 6.903115 | 2.0314% | 0.000450 |
| `progress_emit` | 0.142590 | 0.0420% | 0.000009 |
| `score_input_lookup` | 0.033212 | 0.0098% | 0.000002 |
| `funding_context_lookup` | 0.029512 | 0.0087% | 0.000002 |

The wallet/context cache still showed 12,067 repeated wallet-context opportunities and 78.5919% effective scoped-history/domain-profile reuse. The profile run does not show meaningful overhead in the new external lookup/cache buckets.

## Retention Assessment

The `eae111e` cache does not change the upstream wallet fetch boundary; the expensive prefetch phase occurs before the run-local scoped-history/domain-profile cache is used. The prior prefetch/API worsening is therefore not supported as a code-level cache overhead finding. The new run recovered most of the prior total regression while preserving the same subset scope.

Decision: keep the wallet/context cache as-is. Do not guard, narrow, or revert it from this evidence.

## Gate Decision

Gate: `wallet_cache_keep_confirmed`

Supporting evidence:

- Static equivalence passed.
- Live profile run remained subset-only and bounded.
- Current total runtime returned to post-scorer baseline levels.
- `_score_trade()` remains the dominant score-loop bucket.
- Wallet API/prefetch remains material, but the cache is not proven to worsen that boundary.

## Next Recommendation

Create a scorer-context optimization RFC before any new runtime patch. The next patch should instrument or decompose `_score_trade()` internals rather than changing candidate admission, scoring weights, thresholds, gates, review routing, exports, storage, or UI behavior.
