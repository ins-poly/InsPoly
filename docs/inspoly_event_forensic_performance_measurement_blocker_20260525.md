# Event Forensic Performance Measurement Blocker

Date: 2026-05-25

Gate: `performance_measurement_blocked_scope_risk`

An approved bounded live precheck was attempted for whole-event performance measurement.

## Bounds

- Max events: 1
- Max markets: 8
- Max candidate wallets per market: 150
- Max total trade rows: 50,000
- Max wall time: 30 minutes
- Funding traces: disabled
- Output directory: `validation_outputs/event_forensic_performance_measurement_20260525_165052/`

## Target

- Event slug: `us-x-iran-permanent-peace-deal-by`
- Source: local performance inventory saved report
- Saved analysis-market count: 6
- Saved raw trade rows: 13,465
- Saved candidate rows: 1,552
- Saved candidate wallets: 427
- Saved truncated markets: 2

## Blocker

The live resolver returned 15 current event markets. The tool stopped before running full Event Forensic analysis because this exceeds the 8-market campaign bound.

This is a useful guardrail result: saved local performance evidence can become stale as event market sets change, so future bounded measurements must re-resolve scope before collecting trades.

## What Did Not Change

- No scoring weights or thresholds changed.
- No Strong Risk, HER, funding, or candidate-admission gates changed.
- No Phase 3 capital-at-risk runtime work was performed.
- No storage schema or UI sorting/filtering changed.
- No saved reports were mutated.
- No private keys, CLOB auth, trading credentials, or order placement were used.

## Next Gate

Use an exact current target that resolves within 8 markets, or approve an explicit bounded market subset. Do not broaden whole-event fetching automatically.
