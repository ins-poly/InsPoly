# Event Forensic Pagination Operator Plan

Date: 2026-05-26

Gate before this campaign: `pagination_operator_plan_required`

This plan converts the open pagination blocker into a bounded, report-only path. It does not approve production pagination expansion.

## Current Behavior

Event Forensic currently uses `PolymarketClient.fetch_trades_in_range()` with bounded offset pagination. The public Data API offset cap is treated as an operational limit, not a recoverable production loop.

Current runtime behavior:

- fetches each selected market independently;
- fetches the normal trade slice and a large-trade backfill slice;
- marks truncation when a slice reaches the public page cap;
- reports `truncated_market_count`, trade collection progress, and evidence warnings;
- preserves selected-market/subset scope;
- does not silently retry with deeper pagination;
- does not change candidate admission, scoring, ranking, review routing, exports, gates, storage, or UI sorting because of truncation.

## Preserved Invariants

- No Phase 3 capital-at-risk runtime implementation.
- No scoring weights, thresholds, Strong Risk/HER/funding/candidate-admission gate changes.
- No storage schema change.
- No UI sorting/filtering change.
- No saved report/artifact mutation.
- No private keys, CLOB auth, trading credentials, or order placement.
- No whole-event completeness claim from a selected subset.
- No production pagination behavior change.

## Bounded Deeper Collection Design

Approved sidecar probe:

- Event: `us-x-iran-permanent-peace-deal-by`
- Markets: the same 6 approved subset markets from `validation_outputs/event_forensic_subset_measurement_selection_20260525.json`
- Live event size: 15 markets
- Collection mode: sidecar-only, report-only
- Max events: 1
- Max selected markets: 6
- Max time chunks per market: 2
- Max pages per slice: 31
- Page size: 100
- Max deduped rows: 50,000
- Max wall time: 30 minutes
- Minimum notional floor for candidate-like comparison: 250
- Output: compact JSON only under `validation_outputs/`

The probe compares current single-window offset pagination against a two-window bounded time split. It counts raw rows and candidate-floor rows. It does not replay scoring, claim rank deltas, or write raw trade dumps.

## Stop Conditions

Stop if:

- selected markets cannot be matched in the live event;
- selected market count exceeds bounds;
- row cap or wall-time cap is hit;
- API behavior cannot be attributed to the selected subset;
- any result would require a whole-event completeness claim;
- candidate/rank/review changes would require a full scorer replay;
- implementation would require production runtime pagination changes.

## Required Evidence Before Any Runtime RFC

A future runtime pagination RFC must prove:

- exact request bounds and fallback semantics;
- selected-market scope stays selected-market;
- old reports are not reinterpreted as complete;
- deeper rows materially change analyst evidence or demonstrably reduce truncation;
- candidate IDs, scores, ranks, review buckets, weak-history demotion, and exports remain explainable;
- performance cost stays inside an operator-approved budget;
- rollback restores current bounded offset behavior without saved artifact mutation.

## Current Operator Decision

The sidecar collector is allowed for bounded evidence only. Production pagination expansion remains blocked pending impact evidence and a separate RFC.

## 2026-05-26 Granular Probe Addendum

A follow-up one-market granular probe tested the highest-overlap truncated market from the approved Iran subset:

- Market: `us-x-iran-permanent-peace-deal-by-april-30-2026-925`
- Condition id: `0xceb6dfaa2cf5abc9d47ebc867b984a7715104944249274e8a483a2e17473e5f5`
- Bounds: one market, 8 time chunks, 31 pages per window, 100 rows per page, 50,000 max unique rows, 30-minute wall time.
- Result: baseline 5,874 rows and 3,100 candidate-floor rows; granular collection 3,593 rows and 819 candidate-floor rows; 0 rows and 0 candidate-floor rows were added beyond baseline.
- Gate: `granular_probe_no_new_rows_provider_or_query_bound`

The addendum does not prove full market completeness because the active chunk still hit the provider/page cap. It does reduce evidence for an immediate local pagination expansion: the bounded granular strategy found no material new rows and should stay monitor-only unless a future provider-semantics campaign defines a different bounded query strategy.
