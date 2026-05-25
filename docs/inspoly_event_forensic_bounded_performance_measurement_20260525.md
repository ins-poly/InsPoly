# Event Forensic Bounded Performance Measurement

Date: 2026-05-25

Gate: `performance_measurement_blocked_scope_risk`

Machine-readable output:

- `validation_outputs/event_forensic_performance_measurement_20260525_165052/summary.json`
- `validation_outputs/event_forensic_performance_measurement_20260525_165052/target_selection.json`

## Result

An approved bounded read-only live precheck was run. The selected target came from local performance inventory:

- Event: `us-x-iran-permanent-peace-deal-by`
- Saved local scope: 6 whole-event markets
- Saved local evidence: 13,465 raw trade rows, 1,552 candidate rows, 427 candidate wallets, 2 truncated markets

The tool resolved the current live event before full analysis and blocked the run because the current event contains 15 markets, exceeding the 8-market campaign bound. No full Event Forensic replay was executed.

Bounds encoded in the plan:

- Max events: 1
- Max markets: 8
- Max candidate wallets per market: 150
- Max total trade rows: 50,000
- Max wall time: 30 minutes

## Preserved Invariants

- Network was used only for bounded target resolution/precheck.
- Funding traces were disabled; no private keys, CLOB auth, trading credentials, or order placement were used.
- Full analysis was not run after the live event exceeded the market-count bound.
- No scorer, threshold, gate, storage, or UI behavior changed.
- No saved reports were mutated.
- Validation-only isolated app data was written under the measurement output directory.

## Next Gate

A future measurement needs either a current target known to resolve within the 8-market bound, or explicit operator approval for a bounded market subset. Whole-event performance runtime patching remains blocked until a completed bounded timing sample exists.
