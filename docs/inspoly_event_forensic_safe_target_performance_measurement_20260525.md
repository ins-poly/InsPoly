# Event Forensic Safe-Target Performance Measurement

Date: 2026-05-25

Gate: `performance_measurement_complete`

Machine-readable output:

- `validation_outputs/event_forensic_safe_target_performance_measurement_20260525.json`
- Raw validation-only output directory: `validation_outputs/event_forensic_performance_measurement_SAFE_TARGET_20260525_170511/`

## Bounds Used

- Max events: 1
- Max markets: 8
- Max candidate wallets per market: 150
- Max raw trade rows: 50,000
- Max wall time: 30 minutes
- Scope: read-only live/RPC measurement for one pre-resolved safe target

No private keys, CLOB auth, trading credentials, order placement, storage mutation, scorer change, gate change, Phase 3 change, or UI sorting/filtering change was used.

## Target

- Event: `russia-x-ukraine-ceasefire-by-january-31-2026`
- Live resolved markets: 1
- Saved local markets: 1
- Saved source report: `event_forensic_outputs/event_forensic_20260504_082642/event_analysis.json`

This target was selected because live target resolution confirmed it stayed within the 8-market bound.

## Measurement Result

- Raw trade rows: 3,208
- Candidate rows: 144
- Candidate wallets: 83
- Analysis markets: 1
- Total event markets: 1
- Truncated markets reported: 1
- Total runtime: 20.54 seconds
- Dominant bottleneck: `collect_event_trades_seconds`

Timing breakdown:

- `collect_event_trades_seconds`: 9.96
- `prefetch_wallet_context_seconds`: 8.09
- `score_candidates_seconds`: 1.99
- `collect_price_history_seconds`: 0.17
- `prepare_candidate_context_seconds`: 0.13
- `assemble_report_rows_seconds`: 0.02
- `total_seconds`: 20.54

## Interpretation

The run proves the measurement path can execute safely when the live event scope is pre-resolved and remains within bounds. It does not prove that larger whole-event performance is safe because the measured target has only one market.

The completed run still reported truncation metadata, so pagination/completeness remains operator-gated for larger event expansion.

## Follow-Up Gates

- Pagination: `pagination_needs_operator_plan`
- Performance patch: `needs_more_measurement`
- Replay schedule: `replay_schedule_updated_with_timing_budget`

No behavior-preserving performance patch was implemented from this single-market sample.
