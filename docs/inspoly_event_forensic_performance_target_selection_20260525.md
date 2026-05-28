# Event Forensic Performance Target Selection

Date: 2026-05-25

Gate summary:

- Target resolution: `safe_target_found`
- Subset policy: `subset_policy_not_needed`
- Full bounded measurement: `performance_measurement_complete`
- Pagination: `pagination_needs_operator_plan`
- Performance patch: `needs_more_measurement`
- Replay schedule: `replay_schedule_updated_with_timing_budget`

Machine-readable output:

- `validation_outputs/event_forensic_measurement_target_inventory_20260525.json`
- `validation_outputs/event_forensic_measurement_target_resolution_20260525.json`
- `validation_outputs/event_forensic_performance_target_selection_20260525.json`

## Target Inventory

The inventory tool evaluated local performance rows and proposed 8 candidate event targets without network calls.

- Candidates proposed: 8
- Likely within live market bound from local evidence: 6
- Saved-local measurement-safe candidates: 4

The previous blocked target, `us-x-iran-permanent-peace-deal-by`, remained useful as negative evidence: local saved scope had 6 markets, but live resolution currently returns 15 markets.

## Live Target Resolution

The resolution tool performed bounded live scope metadata checks only. It did not load full trade history or run full analysis.

- Candidates resolved: 8
- Safe targets found: 3
- Selected safe target: `russia-x-ukraine-ceasefire-by-january-31-2026`
- Selected live market count: 1

Unsafe examples:

- `us-x-iran-permanent-peace-deal-by`: 15 live markets, above bound.
- `us-strikes-iran-by`: 65 live markets, above bound.
- Several locally interesting targets were rejected because saved candidate-wallet evidence already exceeded the campaign bound.

## Measurement Decision

Because a safe target was found, no subset policy RFC was needed for this run. The subset policy remains a future user-approval path for larger events that exceed 8 markets.

The selected safe target completed within the measurement bounds:

- Raw rows: 3,208
- Candidate rows: 144
- Candidate wallets: 83
- Runtime: 20.54 seconds
- Dominant bottleneck: `collect_event_trades_seconds`

## Performance Patch Decision

Gate: `needs_more_measurement`

The sample is valid but single-market. It is sufficient to close the immediate target-selection blocker, but not enough to justify a behavior-preserving performance patch for large whole-event runs.

## Preserved Invariants

- No scoring weights or thresholds changed.
- No Strong Risk/HER/funding/candidate-admission gate changed.
- No Phase 3 capital-at-risk runtime migration was performed.
- No storage schema changed.
- No UI sorting/filtering changed.
- No app saved reports were mutated.
- No private keys, CLOB auth, trading, or order placement were used.

## Next Action

For larger events, use one of:

- another pre-resolved whole-event target with 8 markets or fewer; or
- a separately approved subset measurement policy that labels results as subset-only and not whole-event complete.
