# Archive/Event Pagination Measurement Analysis

Date: 2026-05-25

Gate: `pagination_needs_operator_plan`

This report combines the bounded live measurement/precheck output with the existing local completeness audit. It does not change pagination, candidate admission, scoring, ranking, storage, or saved artifacts.

## Measurement Input

- Measurement gate: `performance_measurement_blocked_scope_risk`
- Output directory: `/Users/Root1/Documents/InsPoly/validation_outputs/event_forensic_performance_measurement_20260525_165052`
- Event slug: `us-x-iran-permanent-peace-deal-by`
- Live status: `blocked_scope_exceeded`
- Live error: `resolved_market_count_exceeds_bound`
- Saved analysis markets: 6
- Resolved live markets: 15
- Runtime behavior changed: False

## Local Completeness Baseline

- Reports evaluated: 78
- Explicit truncation reports: 20
- Unknown legacy reports: 22
- Candidate-admission risk reports: 20
- Ranking-risk reports: 3

## Findings

- Live target scope drifted from 6 saved analysis market(s) to 15 resolved market(s), exceeding the bounded campaign limit.
- Local completeness audit already contains explicit truncated-report evidence.
- Legacy reports without current completeness metadata remain unknown and must not be reinterpreted as complete.

## Recommendation

Do not broaden pagination automatically. A future operator run needs an exact bounded target or approved market subset before any live expansion.
