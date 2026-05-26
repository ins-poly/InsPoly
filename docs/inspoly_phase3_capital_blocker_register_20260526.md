# InsPoly Phase 3 Capital-at-Risk Blocker Register

- Date: 2026-05-26
- Current gate: `phase3_sidecar_only_final`
- Runtime blocker state: `phase3_blocked_until_new_source_fields`
- Runtime implementation authorized: `false`

## Active Runtime Blockers

| Blocker | Current evidence | Runtime implication | Removal condition |
|---|---|---|---|
| Sensitive overlap lacks safe real SELL evidence | Prior audit found 2,177 sensitive-overlap rows; latest expansion found 0 safe real sensitive SELL rows | Runtime capital migration could affect Strong Risk, HER, funding, high-review, or candidate-admission-adjacent interpretation without direct evidence | Find real/non-synthetic sensitive-overlap SELL rows with direct side/outcome/price/size and run before/after gate audit |
| Old notional-only rows remain unsafe | Source inventory found 7,134 old notional-only unsafe rows | Old reports cannot be reinterpreted as economic max loss | Add no-op/unknown runtime tests and prove old reports never backfill Phase 3 from notional-only fields |
| Old saved-report/display-only SELL rows dominate latest SELL evidence | Real SELL expansion found 2,895 old saved-report/display-only SELL rows | Display fields can mislead analysts if treated as runtime capital source | Keep display-only rows sidecar-only and source-quality marked until direct fields are available |
| No explicit collateral/max-loss source field | Field coverage found 0 collateral/max-loss fields | SELL max loss remains formula-derived, not independently sourced | Either approve formula-derived max loss explicitly in an RFC or obtain a direct collateral/max-loss field |
| Ledger cross-check sample is too small | 5 artifact dirs, 8 rows, 1 safe SELL row | Proves semantics, not production coverage | Expand ledger/reconstruction evidence with real rows, especially sensitive SELL cases |
| Runtime gate drift not proven safe | Impact audit still reports high false-confidence risk | Capital changes may affect sensitive scoring context | Add before/after audit proving no unintended Strong Risk/HER/funding/candidate-admission drift |

## Allowed Work

- Sidecar source-quality audits.
- Analyst-only review packets.
- Direct-field BUY cash and SELL max-loss classification.
- Ledger/reconstruction cross-check expansion.
- Known-case and fixture tests for old-report no-op behavior.

## Blocked Work

- Phase 3 runtime capital-at-risk migration.
- `_score_trade()` or `_event_forensic_score()` capital semantics changes.
- Scoring weight or threshold changes.
- Strong Risk, HER, funding, or candidate-admission changes.
- Storage schema changes.
- UI sorting/filtering changes.
- Saved report mutation or old-report backfill.

## Future RFC Entry Criteria

A future `phase3_runtime_ready_for_rfc` decision requires:

1. Safe real sensitive SELL evidence.
2. Old-report no-op proof.
3. Explicit formula-vs-collateral product decision.
4. Before/after sensitive gate audit.
5. Additive field contract separating raw notional, observed cash/proceeds, economic max loss, and source quality.
6. Explicit user approval for runtime behavior change after the RFC is reviewed.

Until then, the durable decision is sidecar-only final with runtime blocked.
