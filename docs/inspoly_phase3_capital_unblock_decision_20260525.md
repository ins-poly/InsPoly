# InsPoly Phase 3 Capital-at-Risk Unblock Decision

- Date: 2026-05-25
- Scope: unblock analysis, source inventory, ledger cross-check, and sidecar impact audit
- Runtime implementation authorized: `false`
- Network/RPC used: `false`
- Gate decision: `phase3_ready_for_partial_safe_sidecar_only`

## Inputs Reviewed

- `docs/inspoly_side_outcome_phase3_capital_at_risk_rfc_20260522.md`
- `docs/inspoly_side_outcome_phase3_capital_at_risk_impact_audit_20260522.md`
- `docs/inspoly_phase3_capital_source_quality_program_20260522.md`
- `docs/inspoly_phase3_capital_unblock_requirements_20260522.md`
- `side_outcome_audits/side_outcome_phase3_capital_at_risk_audit_20260522.json`
- `app/side_outcome.py`
- `app/polymarket_protocol.py`
- `app/polymarket_ledger.py`
- `tools/side_outcome_phase3_capital_at_risk_audit.py`
- `tools/validate_polymarket_ledger_against_artifacts.py`
- `tests/fixtures/polymarket_ledger_artifacts/`
- `docs/inspoly_event_forensic_scope_semantics_implementation_20260525.md`

## New Outputs

- `validation_outputs/phase3_capital_unblock_blocker_reconciliation_20260525.json`
- `validation_outputs/phase3_capital_source_inventory_20260525.json`
- `validation_outputs/phase3_capital_ledger_crosscheck_20260525.json`
- `validation_outputs/phase3_capital_unblock_impact_audit_20260525.json`
- `docs/inspoly_phase3_capital_at_risk_formula_contract_20260525.md`

## What Changed Since The Previous Blocker

The new protocol and ledger sidecars materially improve accounting evidence:

- ledger fixtures now prove explicit `usdcSize` is preferred over `size * price` for observed cash;
- SELL `usdcSize` remains cash/proceeds, not max loss;
- SELL complement max-loss can be computed in normalized ledger fixtures when side, outcome, price, and size are direct;
- source disagreements and missing fields are surfaced as quality notes rather than hidden.

This reduces formula ambiguity for sidecar/accounting evaluation. It does not remove runtime migration risk.

## Source Inventory Counts

From `validation_outputs/phase3_capital_source_inventory_20260525.json`:

| Metric | Count |
|---|---:|
| records evaluated | 16,340 |
| real local rows | 16,258 |
| safe for BUY cash | 6,527 |
| safe for SELL max loss | 852 |
| safe for display only | 1,796 |
| old notional-only unsafe | 7,134 |
| unknown/missing fields | 31 |
| runtime-safe candidate rows | 2,267 |
| real-local safe SELL max-loss rows | 848 |

Field coverage:

| Field | Rows |
|---|---:|
| side | 11,311 |
| outcome | 11,309 |
| price | 14,226 |
| size | 9,179 |
| `usdcSize` | 19 |
| cash paid / observed cash | 11,881 |
| collateral or max-loss field | 0 |
| token id | 9,006 |
| condition id | 14,230 |

## Ledger Cross-Check Counts

From `validation_outputs/phase3_capital_ledger_crosscheck_20260525.json`:

| Metric | Count |
|---|---:|
| artifact dirs evaluated | 5 |
| rows evaluated | 8 |
| SELL rows | 1 |
| safe SELL max-loss rows | 1 |
| rows where `usdcSize` is observed cash, not max loss | 1 |
| unknown exposure rows | 1 |

The ledger cross-check is useful but small. It proves the sidecar accounting rule, not production readiness.

## Impact Re-Audit Counts

From `validation_outputs/phase3_capital_unblock_impact_audit_20260525.json`:

| Metric | Count |
|---|---:|
| total rows evaluated | 16,340 |
| safe for BUY cash | 6,527 |
| safe for SELL max loss | 852 |
| still unsafe | 8,961 |
| old audit rows with capital delta | 3,000 |
| old audit sensitive overlap rows | 2,177 |
| affected rows if implemented only for safe rows | 7,379 |
| false-confidence risk | high |

## Gate Decision

Decision: `phase3_ready_for_partial_safe_sidecar_only`.

Why not `phase3_ready_for_implementation_rfc`:

- `7,134` rows remain old notional-only and unsafe for reinterpretation.
- `1,796` rows are display-only saved-report evidence, not safe runtime source evidence.
- `2,177` previously affected rows overlap sensitive funding/HER/Strong Risk-style contexts.
- No local source exposes a collateral/max-loss field; SELL max-loss is formula-derived from direct trade fields only.
- The ledger cross-check sample is strong but small: 8 rows, with 1 SELL row.

Why not `keep_phase3_blocked_accounting_ambiguous`:

- The formula itself is no longer ambiguous for sidecar rows with direct side/outcome/price/size.
- The ledger helper now explicitly distinguishes observed cash/proceeds from SELL max loss.
- A partial sidecar-only path can be useful for future evidence gathering and report previewing.

## Runtime RFC Status

No runtime migration RFC was created.

The current evidence supports partial sidecar-only analysis and stricter source-quality gates. It does not yet support changing `_score_trade()`, `_event_forensic_score()`, archive metadata, scanner capital-at-risk, funding/HER/Strong Risk behavior, saved report interpretation, or browser sorting/filtering.

## Requirements To Reconsider Runtime Implementation

Before any future `phase3_ready_for_implementation_rfc` gate:

1. Increase real/non-synthetic normalized trade evidence, especially SELL rows.
2. Prove runtime sources expose direct side/outcome/price/size before old report transformations.
3. Keep old notional-only reports no-op/unknown with tests.
4. Add sensitive overlap review packets proving no direct gate migration.
5. Decide whether formula-derived SELL max loss is sufficient without explicit collateral fields.
6. Run a before/after audit showing expected capital drift and no unexpected gate drift.

## Explicit Non-Authorization

This decision does not authorize:

- Phase 3 runtime capital normalization;
- `_score_trade()` or `_event_forensic_score()` capital changes;
- scoring weight or threshold changes;
- Strong Risk/HER/funding/candidate admission changes;
- storage schema changes;
- live/RPC/network collection;
- saved artifact mutation;
- UI sorting/filtering changes.
