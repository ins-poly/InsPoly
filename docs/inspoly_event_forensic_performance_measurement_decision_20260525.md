# Event Forensic Performance Measurement Decision

Date: 2026-05-25

Gate: `needs_more_measurement`

## Measurement Outcome

The earlier bounded live precheck used `us-x-iran-permanent-peace-deal-by` and correctly stopped because the saved 6-market scope now resolves to 15 live markets.

The follow-up target-selection run resolved 8 candidate targets and found 3 safe targets. The selected target was:

- `russia-x-ukraine-ceasefire-by-january-31-2026`

That target resolved to 1 live market and completed a bounded measurement.

## Timing Breakdown

Completed safe-target measurement:

- Total runtime: 20.54 seconds
- `collect_event_trades_seconds`: 9.96
- `prefetch_wallet_context_seconds`: 8.09
- `score_candidates_seconds`: 1.99
- `collect_price_history_seconds`: 0.17
- `prepare_candidate_context_seconds`: 0.13
- `assemble_report_rows_seconds`: 0.02

Dominant bottleneck: `collect_event_trades_seconds`

## Counts

- Candidate targets resolved: 8
- Safe targets found: 3
- Measurement events: 1
- Live resolved markets for measured target: 1
- Raw trade rows loaded: 3,208
- Candidate rows scored: 144
- Candidate wallets: 83
- Truncated markets reported: 1
- Full analysis completed: true

## Interpretation

The target-selection blocker is reduced: current live scope must be pre-resolved before a whole-event measurement, and a safe <=8-market target can be measured without broad crawling.

The completed sample is a valid timing baseline, but it is not representative enough for large whole-event optimization because it has only one market. It does not justify changing candidate collection, scoring, ranking, gates, or pagination behavior.

## Optimization Decision

Decision: `needs_more_measurement`.

A behavior-preserving performance patch still needs either a larger <=8-market target or an explicitly approved subset measurement for a larger event. No optimization patch was implemented from this single-market sample.

## Preserved Invariants

- No scorer behavior changed.
- No thresholds changed.
- No direct Strong Risk/HER/funding/candidate-admission gate changed.
- No Phase 3 capital-at-risk runtime migration was performed.
- No storage schema changed.
- No UI sorting/filtering changed.

## Next Measurement Requirement

Use one of:

- a current whole-event target known to resolve to 8 markets or fewer; or
- an operator-approved explicit market subset for a larger event.

Until then, whole-event performance patching remains blocked.
