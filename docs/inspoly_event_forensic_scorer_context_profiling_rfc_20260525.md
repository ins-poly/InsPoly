# Event Forensic Scorer Context Profiling RFC

Date: 2026-05-25

Status: RFC only

Gate: `scorer_context_profiling_rfc_ready`

## Background

After scorer input memoization and the wallet/context pure-cache patch, the
high-density subset still spends most runtime in candidate scoring plus wallet
context fetch/prefetch:

- score loop: 338.00s;
- wallet prefetch/context fetch: 316.64s;
- total: 703.56s;
- candidate rows: 15,354;
- candidate wallets: 3,242.

The latest patch reduced score-loop time versus the post-scorer-memoization
baseline, but total runtime did not improve because wallet prefetch became
slower in the live run. The remaining safe work is deeper profiler evidence
inside scorer-context construction before any broader runtime optimization.

## Goals

- Identify which scorer context components dominate CPU time after current
  memoization.
- Preserve candidate admission, candidate order, scores, ranks, review routing,
  and export rows.
- Keep profiling sidecar or additive-only until an exact behavior-preserving
  patch is justified.

## Non-Goals

- No scoring weight or threshold tuning.
- No Strong Risk, HER, funding, or candidate-admission gate changes.
- No Phase 3 capital-at-risk runtime normalization.
- No storage schema migration.
- No UI sorting/filtering change.
- No broader pagination or market-scope expansion.

## Profiling Targets

1. `wallet_window_trades` usage inside `_score_trade()`.
2. `wallet_history_trades` reducer and annotation usage.
3. Market/domain notional sample lookup and percentile calculations.
4. Event-context resolver output usage.
5. Funding health/context lookup path when funding traces are disabled.
6. Weak-history near-certainty review demotion metadata checks.

## Safe Patch Options

### Option A — Per-candidate scorer timing buckets

Add additive timing counters around pure scorer sub-steps. This is low risk but
may add overhead, so it should be gated behind validation/performance mode.

Required proof:

- candidate IDs unchanged;
- scores unchanged;
- rank order unchanged;
- review buckets unchanged;
- timing metadata additive-only.

### Option B — Precompute immutable percentile inputs

Precompute market/domain percentile inputs before the score loop. Some of this
already exists after scorer memoization. Further work must prove that input
lists are byte-for-byte equivalent to the old call path.

Required proof:

- exact market/domain sample values unchanged;
- missing-sample fallback unchanged;
- old report loading unaffected.

### Option C — Profile-only scorer trace sample

Create a sidecar profiler that samples saved candidate rows and reports which
raw-metric fields are expensive to reconstruct. This is safest, but it cannot
prove live runtime benefit without a follow-up measurement.

Required proof:

- no network calls;
- no runtime imports into scanner/archive/browser paths;
- output labeled profiler-only.

## Stop Conditions

Stop before implementation if:

- optimization requires changing `_score_trade()` semantics;
- candidate admission/ranking/routing would change;
- missing-field fallback would change;
- pagination/fetch boundaries would change;
- source drift prevents equivalence proof;
- performance gain depends on reducing candidate or market coverage.

## Recommended Next Step

Create a sidecar scorer-context profiler first, then run it against the saved
high-density subset and the two small controls. Do not implement another
runtime optimization until the profiler isolates a pure, testable repeated
computation.
