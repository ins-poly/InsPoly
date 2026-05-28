# InsPoly Side/Outcome Phase 2 Archive Evidence Gap

- Date: 2026-05-22
- Scope: sidecar-only archive evidence audit
- Runtime implementation allowed: `false`
- Gate decision: `ready_for_phase2_implementation`

## Summary

- Artifacts discovered: `4835`
- Artifacts selected for bounded scan: `120`
- Artifacts scanned: `102`
- Artifacts skipped: `18`
- Records loaded: `3308`
- Evaluable records: `2021`
- Unique trade keys: `659`
- Affected unique trade keys: `121`

## Evidence Categories

| Evidence type | Artifacts | Records | Evaluable records | Affected rows |
|---|---:|---:|---:|---:|
| `real_local` | 112 | 3285 | 2003 | 775 |
| `existing_test_fixture` | 5 | 5 | 3 | 0 |
| `synthetic_fixture` | 3 | 18 | 15 | 12 |

## Artifact Families

| Family | Records |
|---|---:|
| `archive_candidates_csv` | 1133 |
| `archive_case_slice_csv` | 438 |
| `archive_excluded_json` | 178 |
| `archive_flagged_csv` | 697 |
| `archive_report_json` | 706 |
| `archive_secondary_review_csv` | 152 |
| `archive_trades_csv` | 4 |

## Archive Field Coverage

| Field category | Rows |
|---|---:|
| `raw_side_outcome_price_available` | 2021 |
| `old_probability_available` | 672 |
| `phase1_additive_fields_present` | 8 |
| `price_missing_or_unknown` | 1287 |
| `side_missing_or_unknown` | 0 |
| `outcome_missing_or_unknown` | 1 |
| `lossy_csv_without_price` | 1284 |
| `old_fields_only_rows` | 2015 |

## Affected Archive Rows

| Surface | Rows | Unique trade keys |
|---|---:|---:|
| `lowProbability30Changed` | 749 | 109 |
| `lowProbability35Changed` | 757 | 113 |
| `nearCertainty95Changed` | 647 | 77 |
| `nearCertainty98Changed` | 627 | 65 |
| `directionChanged` | 787 | 121 |
| `laterCorrectnessChanged` | 0 | 0 |
| `anyModelRelevantChange` | 787 | 121 |
| `sensitiveGateContextAffected` | 0 | 0 |

## Missing Field Taxonomy

| Note | Rows |
|---|---:|
| `missing_or_unknown_token_outcome` | 1 |
| `missing_or_unknown_token_price` | 1287 |
| `opening_sell_missing_size_or_inferable_notional` | 32 |
| `opening_sell_requires_accounting_verification_before_capital_migration` | 44 |
| `opening_sell_size_inferred_from_notional_and_price` | 2 |

## Compatibility Findings

- Archive JSON reports preserve raw trade side/outcome/price in `trade`, so old report loading can derive display-only economic context without mutating saved reports.
- New archive trade/candidate CSV shape includes additive Phase 1 raw/economic fields; old columns must remain raw-token.
- Old archive flagged/secondary CSV rows can be lossy because they may include side/outcome without price; these rows must stay unknown for Phase 2 rescoring and must not be coerced.
- Lossy archive CSV rows were observed; future Phase 2 implementation should not use old flagged CSV exports as a scoring source.
- Phase 1 additive fields are present in at least some archive evidence rows, confirming additive-only export shape is testable.

## Affected Examples

- `real_local` `archive_candidates_csv` `0x692a5a8e04516c2e2ca2bcb6b407acb326ac25f54fd41a1b863239c417a29f09`: SELL NO raw=0.992039306465401 economic=YES@0.007960693534599 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `real_local` `archive_candidates_csv` `0xabe6cce5b2e02293a4713b0dca6baddf193b97781268e41514a381d820fd3d48`: SELL NO raw=0.9927990915928919 economic=YES@0.0072009084071081 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `real_local` `archive_candidates_csv` `0xe0fdd7cf0942c42bf709f3c33230959a43f94072be20c9efeec5ff8a9542f5d0`: SELL NO raw=0.9920460127288058 economic=YES@0.0079539872711942 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `real_local` `archive_candidates_csv` `0x962882dd88746e2042e862b4f9db09e67bebf8432e33acf1acc2db94d7846acc`: SELL NO raw=0.994 economic=YES@0.006 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `real_local` `archive_candidates_csv` `0xb0ef54ea38b45a051c32221a6206421ee4b57db6f9a7bce01cf73dda8f958146`: SELL NO raw=0.994 economic=YES@0.006 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `real_local` `archive_candidates_csv` `0xc860534d669e4093a8919d9e92d13444bc0c067ed8ac77df98b869cc2787fc54`: SELL NO raw=0.995 economic=YES@0.005 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `real_local` `archive_candidates_csv` `0x41d6e67e0fe1324db5de966dac83bd86c953acc91cd66483da9e0e77d9bae990`: SELL NO raw=0.996 economic=YES@0.004 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `real_local` `archive_candidates_csv` `0xb06dff144f7dda8bfea78210d1da2bcf83a6bbe24ddb54bfc8bdc0cc0eac2837`: SELL NO raw=0.995 economic=YES@0.005 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `real_local` `archive_candidates_csv` `0x11af765765c417c5c2b0a461912e206d0ef1f227f421aaecb8f269ac0657255c`: SELL NO raw=0.997 economic=YES@0.003 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `real_local` `archive_candidates_csv` `0xb3bdf51a61345ef0dba3828a772e6caec7449aae41f941f174988e6a110b4485`: SELL NO raw=0.993 economic=YES@0.007 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `real_local` `archive_candidates_csv` `0xd021de11a40cfecfabf2a8f666a65016bb79e22fe5f5436b6207e6fea28c0736`: SELL NO raw=0.9928325576732592 economic=YES@0.0071674423267408 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `real_local` `archive_candidates_csv` `0xdd7b1ab470133b866a37952980f75312123d8d6830a9381e2cffcfb56b7c6994`: SELL YES raw=0.9855626129268156 economic=NO@0.0144373870731844 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged

## Implementation Guardrails

- Use full archive JSON/trade-object fields or current in-memory Trade objects for Phase 2 model migration; do not rescore from lossy old flagged CSV rows.
- Keep old archive report keys and CSV columns raw-token and additive-only.
- Treat missing price/side/outcome in old archive CSV rows as unknown, not zero.
- Do not mutate saved archive reports or archive_outputs CSV files.
- Do not change archive visibility tiers, candidate admission, Strong Risk/HER/funding routing, sorting, or browser runtime behavior in this campaign.
- Keep Phase 3 capital-at-risk and Phase 4 cluster-direction normalization out of Phase 2.

## Gate Decision

Decision: `ready_for_phase2_implementation`.

This sidecar does not authorize implementation. It only resolves the archive-evidence question for a future separately approved Phase 2 implementation.

## Explicit Blocks

- _score_trade() changes
- _event_forensic_score() changes
- production archive/scanner/Event Forensic behavior changes
- scoring weights, labels, Strong Risk, HER, funding eligibility, candidate admission, sorting, UI runtime, storage schema, or saved report compatibility changes
- saved report/artifact mutation
- Phase 2 runtime implementation
- Phase 3 capital-at-risk normalization
- Phase 4 cluster-direction normalization
- live/RPC/network behavior
