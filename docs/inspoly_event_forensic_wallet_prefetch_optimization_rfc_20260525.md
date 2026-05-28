# Event Forensic Wallet Prefetch Optimization RFC - 2026-05-25

## Gate

`wallet_prefetch_optimization_rfc_ready`

No implementation is included in this RFC.

## Why This Exists

The post-patch high-density subset measurement showed the scorer memoization patch helped but did not close performance risk:

- Score loop improved from 388.20s to 353.58s.
- Total runtime improved from 663.47s to 644.47s.
- Wallet prefetch increased from 236.57s to 249.80s.
- The subset still had 3,241 candidate wallets and 6 truncated markets.

The scorer remains the dominant stage, but wallet prefetch is still a large secondary bottleneck and is likely to dominate once deeper scorer work lands.

## Current Bottleneck

Current wallet/context cost:

- Candidate wallets: 3,241
- Prefetch wallet context seconds: 249.80
- Prefetch seconds per 1k wallets: 77.074977

Existing behavior must be preserved:

- wallet context remains scoped to the analyzed event/subset;
- selected-market vs subset/whole-event semantics remain explicit;
- no candidate skipping;
- no score or rank changes;
- no Strong Risk/HER/funding/candidate gate changes;
- no storage schema migration;
- no live funding traces unless explicitly requested.

## Safe Optimization Options

### Option 1: Per-Run Wallet Context Dedup Audit

Add instrumentation that records:

- requested wallet count;
- distinct wallet context fetch count;
- cache-hit/cache-miss counts;
- duplicate future reuse count;
- slowest wallet-context calls.

Benefit: confirms whether current prefetch already dedups fully or whether repeated requests remain.

Risk: low if additive-only.

Required proof: candidate IDs, scores, rank order, review buckets, and exports unchanged.

### Option 2: Deterministic Per-Run Wallet Context Cache

Ensure each wallet has one per-run context object reused by all candidate rows in the same analysis scope.

Benefit: reduces repeated context assembly if any code path rebuilds wallet context after prefetch.

Risk: medium if cached objects are mutable or scope-dependent.

Required proof:

- identical candidate IDs and score values;
- identical review routing;
- identical wallet-context raw fields for common rows;
- no cache reuse across different event scopes.

### Option 3: Wallet Prefetch Timing Buckets

Break `prefetch_wallet_context_seconds` into:

- position/history loading;
- wallet performance computation;
- context serialization;
- queue/future wait time.

Benefit: identifies whether the next patch should target IO, computation, or serialization.

Risk: low if additive-only.

### Option 4: Replay Snapshot Reuse For Validation

Use replay snapshots to test wallet-context optimization against fixed candidate exports before a live run.

Benefit: reduces validation cost.

Risk: medium if replay snapshots are mistaken for fresh live evidence.

## Required Tests Before Implementation

- Same candidate IDs.
- Same candidate count.
- Same score values.
- Same rank order.
- Same candidate admission.
- Same review bucket and weak-history demotion.
- Same export row count.
- Same selected-market/subset/whole-event scope labels.
- Old reports load without new timing fields.
- No storage schema changes.
- No private-key/CLOB/trading/order-placement markers.

## Measurement Plan

1. Implement instrumentation-only patch first if needed.
2. Run fixed-output static equivalence.
3. Run one bounded subset measurement on `us-x-iran-permanent-peace-deal-by` with the same 6 selected markets.
4. Run the two one-market controls:
   - `russia-x-ukraine-ceasefire-by-january-31-2026`
   - `maduro-in-us-custody-by-january-31`
5. Compare normalized timing per 1k wallets and per 1k candidates.

## Stop Conditions

Stop before implementation or rollback if:

- candidate IDs change;
- scores change without source-data drift explanation;
- review routing changes;
- candidate admission changes;
- cache crosses selected-market/subset/whole-event boundaries;
- storage schema would be needed;
- live funding traces or trading credentials would be required;
- Phase 3 capital-at-risk becomes entangled.

## Rollback

Keep the change isolated to wallet-prefetch instrumentation/cache helpers. Reverting those files must restore current runtime behavior while preserving the already-committed scorer memoization patch.
