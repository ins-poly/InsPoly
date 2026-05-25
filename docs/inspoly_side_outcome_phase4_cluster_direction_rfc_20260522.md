# InsPoly Side/Outcome Phase 4 Cluster Direction RFC

- Date: 2026-05-22
- Status: RFC + sidecar impact audit only
- Runtime implementation allowed: `false`
- Current evidence gate: `ready_for_phase4_implementation`
- Related evidence:
  - `docs/inspoly_side_outcome_phase2_model_migration_rfc_20260522.md`
  - `docs/inspoly_side_outcome_phase2_runtime_migration_20260522.md`
  - `docs/inspoly_side_outcome_phase2_post_migration_stabilization_20260522.md`
  - `docs/inspoly_side_outcome_phase3_capital_at_risk_rfc_20260522.md`
  - `docs/inspoly_side_outcome_phase3_capital_at_risk_impact_audit_20260522.md`
  - `side_outcome_audits/side_outcome_phase4_cluster_direction_audit_20260522.json`
  - `docs/inspoly_side_outcome_phase4_cluster_direction_impact_audit_20260522.md`

## Non-Authorization

This RFC does not approve runtime implementation.

It must not be interpreted as permission to change `_score_trade()`, `_event_forensic_score()`,
scoring weights, thresholds, Strong Risk, HER routing, funding eligibility, candidate admission,
storage schema, browser sorting/filtering, live/RPC behavior, saved artifacts, or Phase 3
capital-at-risk behavior.

The gate `ready_for_phase4_implementation` means the sidecar evidence and synthetic fixtures are
sufficient to request a separate implementation approval. It is not itself implementation approval.

## Current Cluster Contract Inventory

### Scanner Same-Side Window

- `_score_trade()` currently computes same-side wallet counts using raw `side` + `outcome`.
- `BUY No` and `SELL Yes` are split even though both are economic `long_no`.
- `BUY Yes` and `SELL No` are split even though both are economic `long_yes`.
- The current expected-failure test documents this: SELL YES does not group with BUY NO yet.

### Scanner Structural / Linkage Groups

- `_pre_admission_direction_hint()` returns legacy raw directions:
  - BUY YES -> `long_yes`
  - BUY NO -> `long_no`
  - SELL YES -> `short_yes`
  - SELL NO -> `short_no`
- Structural pre-admission groups by condition + this legacy direction.
- Proxy tight cohorts, split-wallet grouping, and coordinated sizing clusters also group with legacy `economic_direction`.
- These paths can affect structural concern, candidate admission diagnostics, cluster flags, and downstream review tiers.

### Phase 2 Fields

- Phase 2 already writes `model_economic_direction` and `economic_direction_normalized`.
- Cluster logic does not use those fields yet.
- Raw/display fields remain preserved and must stay preserved.

### Archive / Reports

- Archive JSON/CSV exports carry legacy `economic_direction` and additive Phase 2 fields where available.
- Old reports may only have legacy direction or raw side/outcome/price.
- Old saved outputs must not be mutated or reinterpreted unsafely.

### Event Forensic

- Event Forensic wallet clusters use scanner raw metrics such as `coordinated_cluster_signal`.
- Event Forensic timing clusters currently group by `marketSlug`, `orderSide`, and token `side`.
- A future Phase 4 migration can change synchronized same-side entry grouping, but must not change event score weights or sorting in the same patch.

## Target Normalized Direction Semantics

Cluster model direction should describe the trader's economic exposure, not the raw token expression.

| Raw order | Raw token outcome | Normalized cluster direction |
|---|---|---|
| `BUY` | `YES` | `long_yes` |
| `SELL` | `NO` | `long_yes` |
| `BUY` | `NO` | `long_no` |
| `SELL` | `YES` | `long_no` |
| unknown/malformed | unknown/malformed | no normalized cluster grouping unless a trusted Phase 2 provenance field is available |

Expected grouping after implementation:

- `BUY YES` and `SELL NO` should share the `long_yes` cluster key.
- `BUY NO` and `SELL YES` should share the `long_no` cluster key.
- `BUY YES` must not group with `BUY NO`.
- `SELL YES` must not group with `SELL NO`.

## Fields That Must Remain Raw / Compatible

These must remain raw/display/compatibility fields:

- raw `side`
- raw `outcome`
- raw `orderSide`
- `price`
- `price_implied_probability`
- `entryProbability`
- legacy `economic_direction`
- `raw_token_outcome`
- `raw_order_side`
- `raw_token_price`
- existing archive/Event Forensic CSV columns

Future implementation should add or use explicit normalized fields instead:

- `economic_direction_normalized`
- `model_economic_direction`
- `cluster_direction_normalized` if a new field is needed
- `cluster_direction_basis` / provenance if a new field is needed

## Missing / Malformed Semantics

- Missing side, outcome, or price means no normalized cluster grouping.
- Malformed side/outcome/price is `unknown`, not guessed.
- Old reports with only legacy `economic_direction` are not safe for normalized grouping unless a trusted Phase 2 `model_economic_direction` provenance field is present.
- Existing Phase 2 `model_economic_direction` can be used only when its provenance indicates normalized side/outcome semantics.
- Unknown values must not collapse into one shared "unknown" cluster.

## Separation From Phase 3

Phase 4 is direction/grouping only.

It must not:

- change `capital_at_risk_usdc`;
- reinterpret `trade.notional`;
- use SELL complement exposure;
- change liquidity ratio, size basis, funding amount alignment, or any capital-sensitive signal;
- unblock Phase 3.

Rows may overlap Phase 3 blocked capital-at-risk evidence. That overlap is a review risk, not permission to bundle Phase 3 into Phase 4.

## Impact Audit Summary

The Phase 4 sidecar audit scanned local artifacts and synthetic fixtures read-only.

- Records scanned: `16125`
- Evaluable rows: `14012`
- Rows where cluster direction would change: `3101`
- Affected unique trade keys: `1191`
- Affected wallets: `706`
- Affected markets/scopes: `189`
- Affected events: `98`
- Rows in previously split merge groups: `8045`
- Sensitive overlap rows: `2328`
- Phase 3 blocked capital-at-risk overlap rows: `3094`
- Gate decision: `ready_for_phase4_implementation`

Direction transitions:

- `short_no -> long_yes`: `1567`
- `short_yes -> long_no`: `1469`
- `long_no -> long_yes`: `55`
- `long_yes -> long_no`: `10`

The `short_*` transitions are expected SELL normalization. The `long_*` transitions indicate rows where legacy/exported direction and raw side/outcome/model fields disagree enough to require provenance checks before runtime migration.

## Compatibility Risks

- Legacy reports may display or export `economic_direction` as `short_yes` / `short_no`; that field must stay unchanged.
- Runtime migration can merge previously split BUY/SELL expressions and therefore change cluster flags.
- Cluster flags can indirectly affect structural concern, Strong Risk attribution, HER context, and funding/linkage narratives even if weights and thresholds are unchanged.
- Event Forensic timing clusters can change if `orderSide` + token `side` grouping is replaced with normalized direction.
- Old rows with insufficient raw fields must remain absent/unknown, not backfilled.

## Implementation Outline If Later Approved

1. Add a central normalized cluster-direction selector.
2. Keep legacy `_economic_direction()` and `economic_direction` output for display/report compatibility unless a separate migration approves renaming.
3. Migrate scanner same-side window grouping to normalized direction only when side/outcome/price normalize safely.
4. Migrate structural pre-admission grouping with explicit before/after diagnostics.
5. Migrate split-wallet, proxy tight cohort, and coordinated sizing grouping in small patches.
6. Migrate Event Forensic timing clusters only after scanner/archive behavior is stable.
7. Add additive provenance fields if needed; do not delete old keys.
8. Re-run Phase 2 drift, Phase 3 capital audit, cross-mode scoring, scanner/archive/Event Forensic, old-report loading, and sensitive gate tests.

## Required Tests Before Implementation

- Truth table for BUY YES / SELL NO -> `long_yes`, BUY NO / SELL YES -> `long_no`.
- Same-side window test showing SELL YES groups with BUY NO.
- Same-side window test showing SELL NO groups with BUY YES.
- Negative tests showing BUY YES does not group with BUY NO and SELL YES does not group with SELL NO.
- Structural pre-admission diagnostic tests for normalized condition/direction groups.
- Split-wallet and coordinated sizing tests for normalized direction.
- Event Forensic timing cluster tests.
- Old-report loading tests with missing Phase 2 fields.
- Malformed side/outcome/price tests: no normalized grouping.
- Phase 3 regression tests proving capital-at-risk remains unchanged.
- Cross-mode scoring contract tests.
- Direct source scans proving weights, thresholds, storage, UI sorting/filtering, and live/RPC behavior did not change.

## Stop Conditions

Stop before implementation if any of the following are true:

- The patch needs scoring weight or threshold tuning.
- Candidate admission, Strong Risk, HER, or funding behavior changes directly instead of only through approved normalized cluster grouping.
- Old saved reports would need mutation.
- Legacy `economic_direction` would need to be renamed or reinterpreted.
- Unknown/malformed rows would be grouped together.
- Phase 3 capital-at-risk changes appear necessary to make Phase 4 work.
- UI sorting/filter behavior would change.
- Event Forensic sorting/ranking would change outside explicit cluster display context.

## Gate Decision

Decision: `ready_for_phase4_implementation`.

This is an evidence gate only. Runtime Phase 4 implementation still requires separate explicit approval.
