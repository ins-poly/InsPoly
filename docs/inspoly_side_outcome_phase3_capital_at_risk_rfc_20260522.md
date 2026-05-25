# InsPoly Side/Outcome Phase 3 Capital-at-Risk RFC

- Date: 2026-05-22
- Status: RFC + sidecar impact audit only
- Runtime implementation allowed: `false`
- Current gate decision: `keep_phase3_blocked`
- Related evidence:
  - `docs/inspoly_side_outcome_phase2_model_migration_rfc_20260522.md`
  - `docs/inspoly_side_outcome_phase2_runtime_migration_20260522.md`
  - `docs/inspoly_side_outcome_phase2_post_migration_stabilization_20260522.md`
  - `side_outcome_audits/side_outcome_phase3_capital_at_risk_audit_20260522.json`
  - `docs/inspoly_side_outcome_phase3_capital_at_risk_impact_audit_20260522.md`

## Non-Authorization

This RFC does not approve runtime implementation.

It must not be interpreted as permission to change `_score_trade()`, `_event_forensic_score()`,
scanner/archive/Event Forensic production behavior, scoring weights, thresholds, Strong Risk,
HER routing, funding eligibility, candidate admission, storage schema, browser sorting/filtering,
saved artifacts, or Phase 4 cluster direction normalization.

Phase 3 may proceed to implementation only after a separate explicit approval gate.

## Current Contract Inventory

### Core Model Objects

- `Trade.notional` is raw execution notional: `price * size`.
- `Trade.from_api()` reads `price` and `size` from Data API rows and does not currently use `usdcSize`.
- Phase 1 additive side/outcome fields separate raw token price from economic-side probability.
- Phase 2 model migration uses economic-side probability for approved probability/direction semantics, but it intentionally left capital-at-risk unchanged.

### Scanner

- `_capital_at_risk_usdc(trade, execution_state)` currently returns `trade.notional` for opening exposure and `0` otherwise.
- Opening BUY and opening SELL therefore both use raw token notional today.
- `_score_trade()` still uses `capital_at_risk_usdc` in downstream size/liquidity/funding-sensitive logic, including opening-size context and large-exposure patterns.
- Funding quality helpers compare funding amounts against preserved raw `trade_notional_usdc`, not a Phase 3 economic max-loss field.

### Archive Scanner

- Archive candidate metadata and CSV/JSON exports carry raw trade notional and current `capital_at_risk_usdc`.
- Archive reports must remain backward compatible. Old rows with only raw notional cannot be safely reinterpreted as economic max loss.
- Archive CSV rows may be lossy. Any future implementation must derive Phase 3 semantics from full in-memory trade objects or full JSON rows, not from lossy secondary exports.

### Event Forensic

- Event Forensic imports current capital-at-risk helper for pre-annotation/candidate metadata.
- Display `positionSize` remains raw trade notional.
- Event Forensic Phase 2 later-correctness semantics are separate from capital-at-risk. Phase 3 must not change event score weights, display sort order, or candidate admission.

### Ledger/PnL Sidecars

- `app/polymarket_ledger.py` already distinguishes explicit `usdcSize`, `size * price`, and unknown cash source for read-only ledger/PnL semantics.
- That helper is sidecar-only and is not a production capital-at-risk source.

## Terminology

- Raw token price: the price of the specific YES/NO token transacted.
- Raw fill notional: `size * raw_token_price`.
- Observed cash amount: explicit cash field such as `usdcSize` when present, otherwise raw fill notional if safe.
- Economic-side probability: Phase 2 BUY/SELL inverted probability for the trader's effective YES/NO exposure.
- Economic capital-at-risk: maximum loss/exposure for the economic position, not necessarily the same as raw fill notional.

## Target Semantics Under Review

### BUY YES / BUY NO

For an opening BUY:

- Economic capital-at-risk is cash paid.
- If an explicit cash field such as `usdcSize` is present and semantically represents fill cash, it may be the observed cash source.
- Otherwise, `size * price` is the fallback.
- Missing/malformed size or price remains unknown unless explicit cash is sufficient and its meaning is documented.

Examples:

- BUY YES, price `0.20`, size `100`: raw notional `20`, economic capital-at-risk `20`.
- BUY NO, price `0.20`, size `100`: raw notional `20`, economic capital-at-risk `20`.

### SELL YES / SELL NO

For an opening SELL:

- Raw fill notional/cash received is not the same as maximum loss.
- Economic max loss is the complement exposure: `size * (1 - raw_token_price)`.
- `usdcSize` should be preserved as observed cash, but it must not be silently treated as SELL max loss unless the provider/artifact explicitly documents it as collateral/max-loss.
- SELL complement math must remain blocked if size or price is missing/malformed.

Examples:

- SELL YES, price `0.20`, size `100`: current raw notional `20`; hypothetical economic max loss `80`.
- SELL NO, price `0.20`, size `100`: current raw notional `20`; hypothetical economic max loss `80`.
- SELL YES, price `0.98`, size `100`: current raw notional `98`; hypothetical economic max loss `2`.

## Source Field Rules

| Field / source | Allowed Phase 3 interpretation | Notes |
|---|---|---|
| `size` + `price` | Can derive raw fill notional and SELL complement if both are valid | Missing is unknown, not zero |
| `usdcSize` | Observed cash amount | For SELL, not automatically max loss |
| `trade_notional_usdc` | Existing raw/report notional | Display/backward compatibility field, not sufficient for SELL max loss alone |
| `capital_at_risk_usdc` | Current production raw capital-at-risk output | Must not be reinterpreted in old reports |
| `positionSize` | Event Forensic raw display size/notional | Display-only unless full trade fields are present |
| old `price_implied_probability` only | Not sufficient for Phase 3 | Requires side/outcome/size context |

## Missing / Malformed Semantics

- Missing size is `unknown`, not zero.
- Missing price is `unknown`, not zero.
- Malformed side/outcome/price is `unknown`, not guessed.
- Old report rows with only notional are not safe for rescoring.
- Inferred size from notional/price is review-only evidence, not implementation-grade proof.
- Source disagreements between `usdcSize` and `size * price` must be reported, not hidden.

## What Must Remain Preserved

- Phase 2 economic probability semantics.
- Raw token display/report fields.
- Old saved report compatibility.
- Current report keys unless a future additive field is approved.
- Scoring weights and thresholds.
- Strong Risk, HER, funding eligibility, candidate admission, and sorting unless a separate gate explicitly approves changes.
- Phase 4 same-side cluster normalization remains out of scope.

## Impact Audit Summary

The sidecar audit scanned local artifacts and synthetic fixtures read-only.

- Records scanned: `16123`
- Evaluable rows: `14108`
- Rows with capital delta under hypothetical Phase 3: `3000`
- Affected unique trade keys: `1179`
- Sensitive overlap rows: `2177`
- SELL rows with capital delta: `2991`
- BUY rows with capital delta: `9`
- Gate decision: `keep_phase3_blocked`

Key blocker evidence:

- Opening SELL complement exposure would materially change capital-at-risk for many rows.
- `2177` affected rows overlap sensitive contexts such as Strong Risk/HER/funding-related surfaces.
- `7145` rows look like old-report/notional-only evidence and cannot be safely rescored.
- `5043` rows required size inference from notional/price, which is audit-only and not a safe production source.
- `53` SELL rows carried explicit `usdcSize`; the audit treats that as observed cash, not max loss.
- `13` rows had explicit cash disagreement with `size * price`.

## Implementation Plan If Later Approved

1. Add a central runtime capital selector with explicit provenance and quality status.
2. Keep raw fill notional, observed cash, and economic max-loss as separate fields.
3. Migrate scanner opening capital-at-risk only for rows with validated opening exposure, side, outcome, size, and price.
4. Migrate archive only from full trade objects/full JSON rows, not lossy old CSVs.
5. Migrate Event Forensic only where capital metadata is used; do not alter event score weights or sort order.
6. Add additive report/debug fields if needed, without deleting old raw fields.
7. Re-run Phase 2 drift audit, Phase 3 capital audit, cross-mode scoring contracts, archive compatibility, Event Forensic score/export tests, and funding/HER/Strong Risk guard tests.
8. Defer Phase 4 cluster direction normalization to a separate RFC and approval.

## Stop Conditions

Stop before implementation if any of the following remain true:

- SELL `usdcSize` semantics are not documented well enough to distinguish observed cash from max loss.
- Old archive/report rows would need reinterpretation from notional-only data.
- Candidate admission, Strong Risk, HER, funding, or visibility semantics would change without separate approval.
- A future patch requires weight or threshold tuning.
- Phase 3 requires Phase 4 cluster direction normalization to be correct.
- Browser sorting/filter behavior would change.
- Any saved report would need mutation or schema-breaking migration.

## Tests Required Before Any Implementation

- `tests/test_side_outcome_phase3_capital_at_risk_audit.py`
- Side/outcome Phase 2 contract tests.
- Phase 2 post-migration drift tests.
- Cross-mode scoring contract tests.
- Scanner focused score/gate tests.
- Archive export/compatibility tests.
- Event Forensic score/export/loading tests.
- Funding/HER/Strong Risk guard tests.
- Old-report loading tests for scanner/archive/Event Forensic.
- Before/after audit outputs showing expected vs unexpected capital drift.

## Gate Decision

Decision: `keep_phase3_blocked`.

The audit proves that a formula is definable, but also proves that runtime migration would affect many SELL rows and sensitive contexts. Phase 3 needs a separate implementation approval and stronger accounting guardrails before production behavior can change.
