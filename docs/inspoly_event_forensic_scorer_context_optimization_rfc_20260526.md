# Event Forensic Scorer Context Optimization RFC

Date: 2026-05-26

## Status

Gate: `scorer_context_next_patch_ready`

This RFC is implementation guidance only. It does not approve scorer tuning, threshold changes, candidate admission changes, review-routing changes, storage schema changes, Phase 3 capital-at-risk runtime work, UI sorting/filtering changes, or live crawling expansion.

## Evidence

The 2026-05-26 scorer-context profiler measured the approved high-density subset:

- Event: `us-x-iran-permanent-peace-deal-by`
- Scope: 6 selected markets out of 15 live markets.
- Candidate rows: 15,354
- Candidate wallets: 3,287
- Total runtime: 645.17s
- Score loop: 339.83s
- Wallet prefetch/context: 266.20s

Inside the score loop, coarse buckets were:

- `_score_trade()` call: 332.662750s, 97.8917% of score-loop time.
- Wallet domain profile annotation: 6.903115s, 2.0314%.
- Progress emit and external lookups: less than 0.1% combined.

The existing scorer input memoization and wallet/context cache are behavior-equivalent, but the remaining bottleneck is inside `_score_trade()`.

## Target Optimization Surface

Future work may optimize only pure, repeated context computations inside or immediately adjacent to `_score_trade()`.

Allowed candidates:

- Factor repeated low-probability input derivation into deterministic, run-local memoized helpers.
- Memoize immutable near-certainty context checks when the cache key includes all score-relevant inputs.
- Reuse deterministic market/domain percentile summaries already present in scorer inputs.
- Add finer-grained timing buckets inside `_score_trade()` without changing formula or output.
- Add chunk/progress metadata for operator visibility without hiding or skipping rows.

Forbidden candidates:

- Changing score weights or thresholds.
- Changing candidate admission or visibility.
- Changing rank sort keys.
- Changing weak-history review demotion semantics.
- Changing Strong Risk, HER, funding, or candidate gates.
- Changing storage schema or persisted report compatibility.
- Changing selected-market versus whole-event scope.
- Broadening pagination or live fetch behavior in the same patch.

## Required Invariants

Any implementation must prove:

- Same candidate IDs.
- Same candidate row keys.
- Same score values.
- Same rank order.
- Same review buckets.
- Same weak-history near-certainty demotion results.
- Same export row count and export row keys.
- Same raw/display side/outcome fields and Phase 2/4 semantics.

Live-source drift must be separated from code behavior by static saved-subset equivalence.

## Proposed Patch Shape

1. Add finer-grained `_score_trade()` profiler buckets.
2. Identify one pure repeated sub-computation with a deterministic cache key.
3. Keep the cache run-local and disabled for any missing/ambiguous key.
4. Preserve exact fallback behavior when fields are missing or malformed.
5. Emit additive performance metadata only.

The first implementation should be narrow enough to revert by removing one helper and one callsite.

## Tests Required

- Unit tests for deterministic cache keys.
- Unit tests for missing/malformed key fallback.
- Static equivalence on the high-density saved subset.
- Event Forensic focused tests.
- Weak-history demotion tests.
- Known-case benchmark tests.
- Side/Outcome Phase 2/4 tests.
- Phase 3 guardrail tests.
- Cross-mode scoring contract.
- Full unittest discover if runtime code changes.

## Stop Conditions

Stop before implementation or commit if:

- Any score/rank/review/export drift appears in static equivalence.
- The optimization requires changing `_score_trade()` weights or thresholds.
- The optimization changes candidate filtering, scope, pagination, or fetch bounds.
- Missing-field behavior becomes less conservative.
- The implementation requires persistent storage or schema changes.

## Rollback

Rollback should remove the new profiler/cache helper and restore the previous direct `_score_trade()` path. Because the intended patch is run-local and additive, rollback must not require data migration or saved-report mutation.
