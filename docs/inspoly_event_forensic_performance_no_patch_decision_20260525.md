# Event Forensic Performance No-Patch Decision

Date: 2026-05-25

Gate: `performance_needs_subset_measurement`

## Decision

Do not implement a behavior-preserving Event Forensic performance patch from the current evidence.

## Evidence

Three bounded measurements completed successfully, but all completed targets were single-market events:

- `russia-x-ukraine-ceasefire-by-january-31-2026`
- `maduro-in-us-custody-by-january-31`
- `nba-will-the-mavericks-beat-the-grizzlies-by-more-than-5pt5-points-in-their-december-4-matchup`

The two non-empty runs were similar in size:

- 2,517 to 3,208 raw rows
- 144 to 158 candidate rows
- 83 to 102 candidate wallets
- 20.54s to 22.44s total runtime

Bottlenecks were split:

- `collect_event_trades_seconds`: 2 runs, including the sparse control
- `prefetch_wallet_context_seconds`: 1 run

## Why No Patch

The evidence is not representative of large whole-event runs. It does not isolate one stable bottleneck across multi-market whole-event measurements, and it does not show that a specific cache, parsing reuse, timing instrumentation, or snapshot-reuse patch would improve larger cases without risking candidate-set, ranking, scoring, or pagination semantics.

## Blocked Patch Types

Do not implement:

- candidate skipping;
- lower candidate caps;
- market inclusion changes;
- scorer changes;
- threshold changes;
- gate changes;
- storage-schema changes;
- UI sorting/filtering changes.

## Allowed Next Step

Request explicit approval for a labeled subset-only measurement on a larger event, or find another current whole-event target that resolves to 8 markets or fewer and has enough candidate/trade volume to be representative.

Until then, the performance patch gate remains `performance_needs_subset_measurement`.
