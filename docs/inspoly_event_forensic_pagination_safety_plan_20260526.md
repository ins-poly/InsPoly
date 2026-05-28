# Event Forensic Pagination Safety Plan

Date: 2026-05-26

Gate: `pagination_operator_plan_required`

## Why This Plan Exists

The latest wallet API-boundary trace reused the approved high-density subset for `us-x-iran-permanent-peace-deal-by` and again reported truncation:

- Selected markets: 6
- Live event markets: 15
- Truncated selected markets: 6
- Raw rows loaded: 31,985
- Candidate rows: 15,354

This confirms that truncation is a recurring completeness risk for the selected subset. It does not prove that deeper pagination is safe, and it does not authorize unbounded whole-event collection.

## Current Safety Contract

Current Event Forensic behavior:

- uses bounded offset pagination through existing `PolymarketClient.fetch_trades_in_range()`;
- reports `truncated_market_count`;
- keeps selected-market/subset scope explicit;
- does not reinterpret old reports as complete;
- does not change candidate admission, scoring, ranking, gates, storage, or UI sorting based on truncation.

This contract must remain unchanged unless a separate bounded pagination implementation campaign is approved.

## Future Operator-Gated Measurement

A future pagination campaign may run only with explicit approval and these bounds:

- Max events: 1
- Max selected markets: 1 for the first deeper-pagination probe
- Max raw rows: explicit hard cap supplied in the approval
- Max wall time: 30 minutes
- No broad event discovery
- No whole-event completeness claim unless all live markets are explicitly covered
- Output only under a timestamped `validation_outputs/` directory

Recommended first target:

- event: `us-x-iran-permanent-peace-deal-by`
- market: one of the six already selected markets with truncation in the latest subset run
- mode: pagination-only measurement, not scorer tuning

## Required Evidence Before Any Patch

A future pagination patch must prove:

- exact request bounds and stop conditions;
- per-market page counts;
- old bounded result versus deeper bounded result;
- whether candidate IDs change due additional rows;
- whether ranking/review changes are source-data expansion effects, not score formula changes;
- old report fallback remains safe;
- selected-market scope does not become whole-event scope.

## Forbidden In A Pagination Patch

- no unbounded pagination;
- no silent market expansion;
- no candidate-threshold, score-weight, gate, Strong Risk/HER/funding, or Phase 3 changes;
- no storage schema changes;
- no UI sorting/filtering changes;
- no saved report mutation;
- no private keys, CLOB auth, trading, or order placement.

## Stop Conditions

Stop before implementation if:

- API continuation semantics are ambiguous;
- response ordering is unstable enough to create duplicate or missing rows;
- deeper rows cannot be attributed to a bounded source-data expansion;
- candidate or rank changes cannot be explained without changing the scoring contract;
- the run exceeds the approved row or wall-time caps.

## Current Decision

Do not implement pagination expansion in this campaign. The current gate remains `pagination_operator_plan_required`.
