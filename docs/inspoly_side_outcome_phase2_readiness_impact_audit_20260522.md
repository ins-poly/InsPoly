# InsPoly Side/Outcome Phase 2 Readiness Impact Audit

- Date: 2026-05-22
- Scope: sidecar-only evidence audit
- Runtime implementation allowed: `false`
- Gate decision: `ready_for_phase2_rfc`

## Phase 1 Baseline

- Phase 1 added additive raw-token/economic-side fields to new reports, exports, and browser payloads.
- Old raw fields remain preserved: `price_implied_probability`, `entryProbability`, `economic_direction`, and existing CSV/report fields.
- `_score_trade()` calls/imports side-outcome helper inside scorer body: `false`.
- `_event_forensic_score()` calls/imports side-outcome helper inside scorer body: `false`.
- Phase 1 is therefore reporting/display/schema clarity only, not model migration.

## Current Model Signal Inventory

- app/scanner.py: price_implied_probability = trade.price * 100
- app/scanner.py: low_probability_conviction uses trade.price <= 0.30
- app/scanner.py: near_certainty_trade uses trade.price >= 0.95/0.98
- app/scanner.py: suspicious funding support/suppressors read price_implied_probability
- app/scanner.py: same-side clusters use raw side/outcome or legacy economic_direction
- app/event_forensic.py: laterWon and winner ranks compare traded token outcome to winning outcome
- app/event_forensic.py: _event_forensic_score uses case.trade.price for low-probability and near-certainty
- app/event_forensic.py: hard-evidence attribution uses raw price <= 0.35 for low_probability_early_winner
- app/browser*.html: entryProbability sort/filter values remain raw token price

## Artifact Coverage

- Records scanned: `5259`
- Evaluable records: `5259`
- Unique trade keys: `3263`
- Phase 1 field coverage records: `0`

| Artifact family | Records |
|---|---:|
| `ceasefire_all_opening_csv` | 116 |
| `ceasefire_ranked_csv` | 24 |
| `ceasefire_suspicious_csv` | 12 |
| `event_forensic_json` | 982 |
| `reconstruction_normalized_trades_csv` | 66 |
| `scanner_report_json` | 4059 |

Missing or not found in this bounded local sample:
- `archive_report_or_csv`

## Affected / Unaffected Cases

| Impact surface | Unique affected trade keys |
|---|---:|
| `lowProbability30Changed` | 325 |
| `lowProbability35Changed` | 352 |
| `nearCertainty95Changed` | 100 |
| `nearCertainty98Changed` | 52 |
| `directionChanged` | 412 |
| `laterCorrectnessChanged` | 35 |
| `anyModelRelevantChange` | 412 |
| `sensitiveGateContextAffected` | 40 |

- Unaffected unique trade keys: `2851`

## Unsafe / Missing Fields

| Issue | Records |
|---|---:|
| `event_forensic_later_correctness_would_invert` | 46 |
| `opening_sell_requires_accounting_verification_before_capital_migration` | 502 |
| `opening_sell_size_inferred_from_notional_and_price` | 46 |

## What Would Change In Phase 2

- Low-probability conviction would stop treating every low raw token price as low economic-side probability.
- Near-certainty suppressors would be evaluated on the trader's economic side, so opening `SELL Yes @ 0.05` becomes near-certain No exposure rather than low-probability Yes exposure.
- Event Forensic `laterWon`, winner-rank, and low-probability winner attribution could invert for opening `SELL Yes` / `SELL No` rows.
- Same-side cluster logic would need normalized economic direction to group `SELL Yes` with `BUY No` and `SELL No` with `BUY Yes`.
- Capital-at-risk requires a separate accounting migration because opening SELL complement exposure cannot be safely inferred for all artifact shapes.
- Funding/HER/Strong Risk must remain gated because they consume low-probability, winner-rank, near-certainty, and hard-evidence meanings.

## Event Forensic Impact

- Current `laterWon` and `winnerRank` semantics are traded-token-outcome based.
- Hypothetical Phase 2 would need economic-side correctness for opening/increasing SELL rows.
- This audit marks row-level later-correctness inversions when `winningOutcome` is present, but full winner-rank migration still needs full chronological market candidate sets, not only top/display rows.
- Browser sort/filter labels may remain raw token price unless a separate UI behavior change is approved; Phase 2 should not silently change sorting.

## Cluster Direction Pre-Audit

- Current scanner/Event grouping uses raw side/outcome or legacy directions such as `short_yes`.
- Hypothetical normalized grouping would use `long_yes` / `long_no` economic direction.
- This audit counts direction changes as cluster-relevant evidence only; it does not alter cluster logic.

## Capital-At-Risk Pre-Audit

- Current `capital_at_risk_usdc` and notional fields are raw execution/notional context.
- Opening SELL complement exposure can be estimated when size/price are available, but this remains unsafe for production until Polymarket accounting semantics are verified across artifacts.
- Missing size/notional or inferred-size rows are blockers for Phase 3, not reasons to change Phase 2 scoring now.

## Funding / HER / Strong Risk Safety

- Funding support, suppressor conflicts, HER routing, and Strong Risk traces can consume low-probability, near-certainty, winner-rank, or hard-evidence meanings.
- Any migration that changes those meanings requires a separate approval gate and targeted gate-preservation tests.
- This report does not permit funding, HER, Strong Risk, candidate-admission, severity-label, or sorting changes.

## Affected Examples

- `scanner_report_json` `0x58cadc42e39f17b810ba914061680177584baddf25cd95df83b699405ed414bc`: SELL NO raw=0.992 economic=YES@0.008 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `scanner_report_json` `0xf4e759adc4161ecff5a15b889110a373e91161c1a2fca74ef47873552b28d5ff`: SELL NO raw=0.989 economic=YES@0.011 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `scanner_report_json` `0x6852537676f7ad97ae63021735553e62acd8aac95c65bfd550d8c3ee88058529`: SELL YES raw=0.986 economic=NO@0.014 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `scanner_report_json` `0x4db8b087539b63cc89ef52e1c4337b811dcad032e4cac6d9f607ab884ab96833`: SELL YES raw=0.857 economic=NO@0.143 changes=lowProbability30Changed, lowProbability35Changed, directionChanged
- `scanner_report_json` `0x9c0480af0b72fc69d9d85faf4e657ec4aaf69ec67b8406f5ba8ba473ee59450b`: SELL NO raw=0.91 economic=YES@0.09 changes=lowProbability30Changed, lowProbability35Changed, directionChanged
- `scanner_report_json` `0x9d8fb897fdf3ed217486c0b8fb1bf69971751c15a18b168235becc476ff1fcdd`: SELL NO raw=0.9828929385751127 economic=YES@0.0171070614248873 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `scanner_report_json` `0x86fba411a3aaeecd3bc16a71bd3ad05a4b3dff56830a2f75fedce2cd8d4e98d0`: SELL NO raw=0.81 economic=YES@0.19 changes=lowProbability30Changed, lowProbability35Changed, directionChanged
- `scanner_report_json` `0x06a64147c5abb1d54882f581bd9bfd886040c15c7e2fba1b2a582fe443f9969d`: SELL NO raw=0.91 economic=YES@0.09 changes=lowProbability30Changed, lowProbability35Changed, directionChanged
- `scanner_report_json` `0x0f19234c337b218df3711cea6b75055378fd2a2036138cde52328d94e82bc77b`: SELL NO raw=0.996 economic=YES@0.004 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `scanner_report_json` `0x497cf2843394bee1473f391deb0de38077b60a2e110b0fbe69704107e54f18e4`: SELL NO raw=0.87 economic=YES@0.13 changes=lowProbability30Changed, lowProbability35Changed, directionChanged
- `scanner_report_json` `0xa1211e9a5eb5c903242ca189b56a7b087499c09c123cf5be7189189bb6a9c4fd`: SELL YES raw=0.988 economic=NO@0.012 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, nearCertainty98Changed, directionChanged
- `scanner_report_json` `0xb58f93c57bccaadf37e2e63cf51bab3cf345cbb04ff73e5345aaffbe7c6c9112`: SELL NO raw=0.9523418066666667 economic=YES@0.0476581933333333 changes=lowProbability30Changed, lowProbability35Changed, nearCertainty95Changed, directionChanged

## Unsafe Examples

- `scanner_report_json` `0x104b1a9d635281d8ab91f56c9a76d1725a36142bae2337b156ad3a23486070db`: opening_sell_requires_accounting_verification_before_capital_migration
- `scanner_report_json` `0x0eb9a981fac5d1de15235b19e121b7ec0f633dea180eca39ab8aace93d648372`: opening_sell_requires_accounting_verification_before_capital_migration
- `scanner_report_json` `0xfdfc920a7429fd4d4a103da92ff6089997eb6df6c519e2ec4a525b171d4668fc`: opening_sell_requires_accounting_verification_before_capital_migration
- `scanner_report_json` `0xcf778a920d4bd54c6dc966f9aeef1d208a00c695589576facaa3ac1b047d45fb`: opening_sell_requires_accounting_verification_before_capital_migration
- `scanner_report_json` `0xcf778a920d4bd54c6dc966f9aeef1d208a00c695589576facaa3ac1b047d45fb`: opening_sell_requires_accounting_verification_before_capital_migration
- `scanner_report_json` `0x4f5b09ba31efe190ce2754c9762300ed7fdeab31185f5e0ccc6ccd584e06e16d`: opening_sell_requires_accounting_verification_before_capital_migration
- `scanner_report_json` `0x3ed140f43991d572fbf275e906c1eebcd0f8bd02c3aa72fa00f921856fbd0373`: opening_sell_requires_accounting_verification_before_capital_migration
- `scanner_report_json` `0x92fba16409009a649391f39e7a8f0d1795ac9324f24a55f96fb228978d2e0232`: opening_sell_requires_accounting_verification_before_capital_migration
- `scanner_report_json` `0x20928097b8a19dd3b9ba13d691791ddf01d834e7a64de48153693f018195d2b6`: opening_sell_requires_accounting_verification_before_capital_migration
- `scanner_report_json` `0xf12694c3016c2ecc2f9b7ddafe98641d6de349fb96831181dfd74b4da43f4a29`: opening_sell_requires_accounting_verification_before_capital_migration
- `scanner_report_json` `0x0d7c387535afd51ac0be5299fc76973953c7fecbd871e1ed455fb3cc774b2f06`: opening_sell_requires_accounting_verification_before_capital_migration
- `scanner_report_json` `0x8e27ce49e750dbe56dba86af5a8f70c0896b05938f75d6a3423ef84c4d1120d3`: opening_sell_requires_accounting_verification_before_capital_migration

## Gate Decision

Decision: `ready_for_phase2_rfc`.

This audit does not authorize Phase 2 implementation. It is enough to justify a narrow Phase 2 RFC only if the gate is `ready_for_phase2_rfc`; implementation still requires separate explicit approval and tests that preserve all existing gates until migration semantics are accepted.

## Explicit Blocks

- _score_trade() changes
- _event_forensic_score() changes
- scoring weights or severity labels
- Strong Risk/HER routing
- funding eligibility
- candidate admission
- browser runtime sorting/filter behavior
- storage schema or saved artifact mutation
- Phase 3 capital-at-risk migration
- Phase 4 cluster-direction migration
