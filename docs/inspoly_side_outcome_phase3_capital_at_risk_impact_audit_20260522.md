# InsPoly Side/Outcome Phase 3 Capital-at-Risk Impact Audit

- Date: 2026-05-22
- Scope: sidecar-only RFC evidence and impact audit
- Runtime implementation allowed: `false`
- Gate decision: `keep_phase3_blocked`

## Current Behavior Inventory

- `Trade.notional` is raw token notional: `price * size`.
- Scanner opening capital-at-risk currently uses raw token notional for opening exposure.
- Archive and Event Forensic reuse that raw capital context for candidate/report metadata.
- Funding-quality helpers compare funding amounts to preserved raw `trade_notional_usdc`.
- Event Forensic display `positionSize` remains raw trade notional, not economic max loss.

## Proposed Economic Formula

- BUY YES/NO: economic capital-at-risk is cash paid, preferring explicit `usdcSize` only as observed cash when present; otherwise `size * price`.
- SELL YES/NO: economic max loss is complement exposure, `size * (1 - price)`, while raw fill cash remains separate.
- Missing or malformed side/outcome/price/size remains `unknown`, not zero.

## Audit Counts

- Records scanned: `16123`
- Evaluable rows: `14108`
- Affected rows: `3000`
- Affected unique trade keys: `1179`
- Sensitive overlap rows: `2177`

| Evidence type | Rows | Affected rows |
|---|---:|---:|
| `existing_test_fixture` | 13 | 5 |
| `real_local` | 16073 | 2972 |
| `synthetic_fixture` | 37 | 23 |

| Artifact family | Rows |
|---|---:|
| `archive_candidates_csv` | 2062 |
| `archive_case_slice_csv` | 934 |
| `archive_excluded_json` | 399 |
| `archive_flagged_csv` | 897 |
| `archive_report_json` | 953 |
| `archive_secondary_review_csv` | 283 |
| `archive_trades_csv` | 2196 |
| `ceasefire_all_opening_csv` | 116 |
| `ceasefire_ranked_csv` | 24 |
| `ceasefire_suspicious_csv` | 12 |
| `event_forensic_json` | 5038 |
| `phase3_synthetic_csv` | 8 |
| `phase3_synthetic_json` | 11 |
| `reconstruction_normalized_trades_csv` | 66 |
| `scanner_report_json` | 3124 |

## Source Field Usage

| Source | Rows |
|---|---:|
| `explicit_usdc_size_cash_paid` | 15 |
| `non_opening_zero` | 207 |
| `size_complement_price_max_loss` | 2993 |
| `size_price_cash_paid` | 10893 |
| `unknown` | 2015 |

## Unsafe / Missing Field Taxonomy

| Note | Rows |
|---|---:|
| `capital_at_risk_would_change` | 3000 |
| `current_reported_notional_missing` | 4 |
| `hypothetical_economic_capital_unknown` | 2015 |
| `missing_or_malformed_raw_order_side_raw_token_outcome` | 1 |
| `missing_or_malformed_raw_token_outcome_raw_token_price` | 1 |
| `missing_or_malformed_raw_token_price` | 2108 |
| `missing_or_unknown_size` | 2107 |
| `observed_cash_unknown` | 2110 |
| `old_report_notional_only_not_safe_for_rescoring` | 7145 |
| `opening_exposure_unknown` | 4886 |
| `opening_sell_complement_exposure_requires_accounting_gate` | 3200 |
| `sell_usdc_size_recorded_as_observed_cash_not_max_loss` | 53 |
| `size_inferred_from_reported_notional_and_price` | 5043 |
| `size_inferred_not_direct` | 5043 |
| `source_cash_disagreement` | 13 |

## Compatibility Risks

- Old reports that only preserve raw notional cannot be safely reinterpreted as economic max loss.
- Existing raw display fields must remain raw-token fields after any future migration.
- Phase 3 would change downstream size/liquidity/funding-sensitive semantics if applied inside scoring.
- Archive CSV rows without side/outcome/price/size must stay unknown and must not be rescored from notional alone.

## Implementation Plan If Later Approved

1. Add a central runtime capital selector with explicit source/provenance fields.
2. Use BUY cash-paid semantics only where explicit fields are available or `size * price` is safe.
3. Use SELL complement max-loss semantics only for opening/increasing exposure with validated size and price.
4. Preserve raw fill notional, observed cash, and display fields separately.
5. Re-run scanner/archive/Event Forensic before/after audits and gate-sensitive tests.
6. Keep Phase 4 cluster normalization separate.

## Gate Decision

Decision: `keep_phase3_blocked`.

This audit does not authorize runtime implementation. A separate approval gate is required before changing `_score_trade()`, `_event_forensic_score()`, archive candidate metadata, funding/HER/Strong Risk semantics, or any report/UI runtime path.

## Explicit Blocks

- runtime capital-at-risk behavior changes
- _score_trade() or _event_forensic_score() Phase 3 edits
- scoring weights or thresholds
- Strong Risk/HER/funding eligibility/candidate admission changes
- Phase 4 cluster direction normalization
- storage schema, UI sorting/filter, live/RPC/network behavior
- saved report or artifact mutation
