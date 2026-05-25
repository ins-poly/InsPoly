# InsPoly Side/Outcome Phase 4 Post-Migration Stabilization

- Date: 2026-05-22
- Scope: sidecar-only stabilization and drift audit
- Runtime code changed by this audit: `false`
- Gate decision: `phase4_stable`

## What Phase 4 Changed

- Scanner same-side windows, structural pre-admission direction groups, split-wallet groups, proxy tight cohorts, and coordinated sizing clusters now use safe normalized cluster direction.
- Event Forensic timing clusters now use `clusterDirection` when `clusterNormalizationStatus` is normalized, with raw side/outcome fallback for malformed payloads.
- Archive and Event Forensic outputs carry additive cluster-direction provenance fields.
- Legacy raw/display direction fields remain preserved.

## Expected Vs Unexpected Drift

- Evaluated rows: `16125`
- Affected rows: `3101`
- Affected unique trade keys: `1191`
- Affected wallets: `706`
- Affected markets/scopes: `189`
- Affected events: `98`
- Merge-group rows: `8045`
- Sensitive overlap rows: `2328`
- Phase 3 blocked overlap rows: `3094`

- No unexpected drift outside the Phase 4 RFC scope was detected by source scans and bounded artifact replay.

## Fallback / Missing Field Counts

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

## Sensitive Merge-Group Summary

- Sensitive merge groups in review packet: `40`
- Sensitive merge groups found: `93`
- Packet directory: `side_outcome_review_packets/phase4_post_migration_sensitive_merge_groups_20260522`
- Packet rows include wallet/market/event, raw side/outcome/price, old direction/group key, new normalized group key, RFC expectation, sensitive context, and risk-sizing unchanged confirmation.

## Cross-Mode Consistency

- `archiveExportsSameClusterFields`: `true`
- `centralHelperIsSourceOfTruth`: `true`
- `eventForensicUsesSameClusterPayload`: `true`
- `malformedRowsFallbackConservatively`: `true`
- `scannerUsesCentralClusterDirection`: `true`

## Compatibility Sweep

- Old legacy-direction-only rows stay fallback/review: `4751`
- Malformed/unknown rows stay not grouped: `2113`
- CSV/JSON exports additive by source scan: `true`
- Browser sorting/filtering unchanged by source scan: `true`
- Storage schema unchanged by source scan: `true`
- Saved artifacts mutated by this audit: `false`

## Remaining Blockers

- Phase 3 capital-at-risk normalization
- scoring weight or threshold changes
- direct Strong Risk/HER/funding/candidate-admission gate migration
- UI sorting/filtering behavior changes
- storage schema changes
- live/RPC/network behavior
- saved report/artifact mutation

## Gate Decision

Decision: `phase4_stable`.
