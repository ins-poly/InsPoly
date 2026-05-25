# InsPoly Side/Outcome Phase 4 Runtime Migration Verification

- Date: 2026-05-22
- Scope: post-implementation sidecar verification
- Runtime implementation verified: `true`
- Gate decision: `ready_for_phase4_implementation`

## Current Behavior Inventory

- Scanner same-side windows, structural pre-admission, split-wallet grouping, proxy tight cohorts, and coordinated sizing clusters now use safe normalized cluster direction.
- Legacy raw `economic_direction` remains preserved as a display/report compatibility field.
- Event Forensic timing clusters now use `clusterDirection` when normalization status is safe, with raw side/outcome fallback for malformed payloads.
- Archive exports preserve both legacy direction and Phase 2 additive model direction fields.
- Phase 3 capital-at-risk remains blocked and is not applied by this audit.

## Target Semantics

| Raw order | Raw token outcome | Normalized cluster direction |
|---|---|---|
| `BUY` | `YES` | `long_yes` |
| `SELL` | `NO` | `long_yes` |
| `BUY` | `NO` | `long_no` |
| `SELL` | `YES` | `long_no` |

## Audit Counts

- Records scanned: `16125`
- Evaluable rows: `14012`
- Rows where direction would change: `3101`
- Affected unique trade keys: `1191`
- Affected wallets: `706`
- Affected markets/scopes: `189`
- Affected events: `98`
- Rows in merge groups: `8045`
- Sensitive overlap rows: `2328`
- Phase 3 capital-at-risk blocked overlap rows: `3094`

| Evidence type | Rows | Direction-change rows |
|---|---:|---:|
| `existing_test_fixture` | 18 | 7 |
| `real_local` | 16073 | 3077 |
| `synthetic_fixture` | 34 | 17 |

| Artifact family | Rows |
|---|---:|
| `archive_candidates_csv` | 2062 |
| `archive_case_slice_csv` | 939 |
| `archive_excluded_json` | 399 |
| `archive_flagged_csv` | 897 |
| `archive_report_json` | 953 |
| `archive_secondary_review_csv` | 283 |
| `archive_trades_csv` | 2196 |
| `ceasefire_all_opening_csv` | 116 |
| `ceasefire_ranked_csv` | 24 |
| `ceasefire_suspicious_csv` | 12 |
| `event_forensic_json` | 5038 |
| `phase4_synthetic_csv` | 5 |
| `phase4_synthetic_json` | 11 |
| `reconstruction_normalized_trades_csv` | 66 |
| `scanner_report_json` | 3124 |

## Direction Transitions

| Transition | Rows |
|---|---:|
| `long_no->long_yes` | 55 |
| `long_yes->long_no` | 10 |
| `short_no->long_yes` | 1567 |
| `short_yes->long_no` | 1469 |

## Unsafe / Missing Field Taxonomy

| Note | Rows |
|---|---:|
| `current_cluster_direction_unknown` | 4 |
| `missing_or_malformed_raw_order_side` | 1 |
| `missing_or_malformed_raw_order_side_raw_token_outcome_raw_token_price` | 1 |
| `missing_or_malformed_raw_token_outcome` | 3 |
| `missing_or_malformed_raw_token_outcome_raw_token_price` | 1 |
| `missing_or_malformed_raw_token_price` | 2107 |
| `missing_scope_key` | 2106 |
| `old_economic_direction_only_not_safe_for_normalized_grouping` | 4751 |
| `overlaps_phase3_blocked_capital_at_risk_row` | 3198 |

## Compatibility Risks

- Legacy `economic_direction` must remain raw/legacy for old reports and exports.
- Old rows with only `economic_direction` are not safe for normalized cluster grouping unless a trusted Phase 2 `model_economic_direction` provenance field is present.
- Normalized grouping can merge previously split BUY/SELL expressions and affect cluster-derived evidence.
- Any downstream Strong Risk/HER/funding/candidate-admission movement must be treated as expected drift and guarded by tests, not hidden.
- Phase 3 capital-at-risk remains blocked and must not be bundled into Phase 4.

## Implemented Runtime Scope

1. Added a central cluster-direction selector that returns normalized direction plus provenance.
2. Migrated scanner same-side window grouping from raw side/outcome to normalized direction only when safe.
3. Migrated structural pre-admission diagnostics and grouped-candidate IDs to normalized direction with old-field compatibility.
4. Migrated split-wallet, proxy tight cohort, coordinated sizing, and Event Forensic timing cluster grouping in focused patches.
5. Kept raw/display direction fields and CSV/report keys additive/compatible.
6. Phase 3 capital-at-risk remains blocked; this verification does not apply exposure normalization.

## Verification Result

Decision: `ready_for_phase4_implementation`.

Runtime implementation was approved separately and this output verifies the bounded Phase 4 cluster/same-side migration. Further Phase 3, scoring-weight, threshold, storage, live/RPC, or UI sorting changes remain blocked.

## Explicit Blocks

- Additional Phase 4 changes beyond normalized cluster/same-side grouping
- scoring weights or thresholds
- Strong Risk/HER/funding eligibility/candidate admission direct changes
- Phase 3 capital-at-risk normalization
- storage schema, UI sorting/filter, live/RPC/network behavior
- saved report or artifact mutation
