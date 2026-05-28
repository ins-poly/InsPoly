# InsPoly Side/Outcome Phase 2 Model Migration RFC

- Date: 2026-05-22
- Status: RFC, evidence gate, and Phase 2 runtime migration contract
- Runtime implementation authorized: true for Phase 2 only by separate explicit user approval on 2026-05-22
- Source evidence:
  - `rfcs/SIDE_OUTCOME_PRICE_NORMALIZATION_RFC_20260507.md`
  - `docs/inspoly_side_outcome_phase2_readiness_impact_audit_20260522.md`
  - `side_outcome_audits/side_outcome_phase2_readiness_impact_audit_20260522.json`
  - `tools/side_outcome_phase2_impact_audit.py`

## Authorization Boundary

This RFC originally did not authorize Phase 2 runtime implementation. Separate explicit approval was granted on 2026-05-22 for the narrow Phase 2 runtime migration described here.

That approval is limited to economic-side probability/correctness semantics. It must not be used as permission to change scoring weights, thresholds, severity labels, Strong Risk gates, Hard Evidence Review routing, funding eligibility, candidate admission, sorting, UI runtime behavior, storage schema, saved report compatibility, old saved artifacts, live/RPC/network behavior, Phase 3 capital-at-risk behavior, or Phase 4 cluster-direction behavior.

## Phase 1 Baseline

Phase 1 has already implemented additive reporting/display clarity:

- `app/side_outcome.py` exposes `normalize_side_outcome()` as a pure helper.
- New reports and payloads can carry raw-token and economic-side fields side by side.
- Existing raw fields remain intact, including `price_implied_probability`, `entryProbability`, `economic_direction`, raw `side`, raw `outcome`, raw `orderSide`, and existing CSV/report fields.
- Browser copy now distinguishes raw token price from economic-side probability where safe.
- Old scanner reports without the new fields still load and can derive display-only labels from existing raw side/outcome/price when safe.
- Missing or malformed side/outcome/price stays unknown, not zero.

Current model behavior remains raw-token based:

- `_score_trade()` uses `trade.price` to write `price_implied_probability`.
- `_score_trade()` uses `trade.price <= 0.30` for `low_probability_conviction`.
- `_score_trade()` uses `trade.price >= 0.95` and `trade.price >= 0.98` for near-certainty suppressors.
- Funding support and suppressor explanations consume raw `price_implied_probability` meanings.
- Scanner same-side clustering still uses raw `side/outcome`.
- Event Forensic `laterWon`, winner rank, and low-probability winner attribution compare traded-token outcome and raw token price against resolved outcome.
- Browser sort/filter values for entry probability remain raw token price.

## Evidence Classification

The Phase 2 readiness audit is sidecar-only, read-only, and did not mutate production behavior. It scanned 5,259 evaluable records across 3,263 unique trade keys.

### Artifact Coverage

| Artifact family | Records |
|---|---:|
| `scanner_report_json` | 4,059 |
| `event_forensic_json` | 982 |
| `reconstruction_normalized_trades_csv` | 66 |
| `ceasefire_all_opening_csv` | 116 |
| `ceasefire_ranked_csv` | 24 |
| `ceasefire_suspicious_csv` | 12 |

Missing from the bounded local sample:

- `archive_report_or_csv`

This archive coverage gap blocks implementation readiness. It does not block writing this RFC.

### Affected Cases

| Impact surface | Unique affected trade keys |
|---|---:|
| `lowProbability30Changed` | 325 |
| `lowProbability35Changed` | 352 |
| `nearCertainty95Changed` | 100 |
| `nearCertainty98Changed` | 52 |
| `directionChanged` | 412 |
| `laterCorrectnessChanged` | 35 |
| `sensitiveGateContextAffected` | 40 |
| `anyModelRelevantChange` | 412 |

Unaffected unique trade keys: 2,851.

### Unsafe Or Missing Evidence

| Issue | Records |
|---|---:|
| `opening_sell_requires_accounting_verification_before_capital_migration` | 502 |
| `opening_sell_size_inferred_from_notional_and_price` | 46 |
| `event_forensic_later_correctness_would_invert` | 46 |

These counts show that Phase 2 semantics matter. They also show that Phase 3 capital-at-risk and Event Forensic retrospective gates are sensitive enough to require explicit guardrails before implementation.

## Target Semantics Contract

### Raw-Token Display Fields

The following fields remain raw-token display or legacy compatibility fields:

- `price_implied_probability`
- `entryProbability`
- `entryProbabilityLabel`
- raw `side`
- raw `outcome`
- raw `orderSide`
- `price`
- `raw_token_outcome`
- `raw_order_side`
- `raw_token_price`
- `raw_token_price_label`
- `rawTokenOutcome`
- `rawOrderSide`
- `rawTokenPrice`
- `rawTokenPriceLabel`
- existing archive/Event Forensic CSV columns that currently expose traded-token values

These fields describe the token the trader bought or sold. They must not be silently reinterpreted as economic-side model fields. If future implementation needs a model probability, it must use an explicitly named economic/model field or selector.

### Economic/Model Fields

The following fields are eligible economic-side context fields:

- `economic_side`
- `economic_side_probability`
- `economic_side_probability_label`
- `economic_direction_normalized`
- `economicSide`
- `economicSideProbability`
- `economicSideProbabilityLabel`
- `economicDirectionNormalized`

Future Phase 2 model logic may use economic-side probability only where this RFC or a later implementation approval explicitly names that model behavior. Display should continue showing both raw token price and economic-side probability when both are useful to analysts.

### Truth Table

| Raw order | Raw token outcome | Raw token price | Economic side | Economic probability | Normalized direction |
|---|---|---:|---|---:|---|
| `BUY` | `YES` | `p` | `YES` | `p` | `long_yes` |
| `SELL` | `YES` | `p` | `NO` | `1 - p` | `long_no` |
| `BUY` | `NO` | `p` | `NO` | `p` | `long_no` |
| `SELL` | `NO` | `p` | `YES` | `1 - p` | `long_yes` |

Malformed, missing, non-binary, or out-of-range values remain `unknown` / not computed. They must not be coerced to zero or guessed from labels.

## Where Model Behavior Would Change

Phase 2 implementation, if later approved, is limited to economic-probability and economic-side correctness semantics.

Candidate migration surfaces:

1. Low-probability conviction:
   - Current: raw token price.
   - Target: economic-side probability.
   - Example: `SELL Yes @ 0.20` is economic `No @ 0.80`, so it should not be treated as low-probability conviction.

2. Near-certainty checks:
   - Current: raw token price.
   - Target: economic-side probability.
   - Example: `SELL Yes @ 0.05` is economic `No @ 0.95`, so it becomes near-certainty economic exposure.

3. Event Forensic later correctness:
   - Current: traded-token outcome equals resolved winning outcome.
   - Target: economic side equals resolved winning outcome for opening/increasing rows.
   - Example: `SELL Yes` in a market resolved `No` is economically correct, even though the sold Yes token did not win.

4. Event Forensic low-probability winner:
   - Current: raw token price <= 0.35 and raw token outcome wins.
   - Target: economic-side probability <= 0.35 and economic side wins.

5. Winner rank and wallet winning entries:
   - Current: raw winning token entries only.
   - Target candidate: economic-side winning opening entries.
   - Guardrail: this needs chronological candidate-set reconstruction and cannot be inferred only from top/display rows.

6. Suspicious funding support/suppressor checks that consume low-probability or near-certainty meanings:
   - Current: raw `price_implied_probability` semantics.
   - Target candidate: explicitly named economic-model probability inputs.
   - Guardrail: must preserve funding `unknown` semantics and Strong Risk/HER gates unless separately approved.

## Where Behavior Must Not Change In Phase 2

The following are out of scope for Phase 2:

- `_score_trade()` replacement or broad rewrite.
- `_event_forensic_score()` replacement or broad rewrite.
- scoring weights.
- severity labels.
- Strong Risk routing.
- Hard Evidence Review routing.
- funding eligibility.
- funding missing/unavailable semantics.
- candidate admission.
- structural pre-admission.
- browser runtime sorting/filter behavior.
- storage schema.
- report writer/loader compatibility.
- old saved outputs.
- raw-token display fields.
- Phase 3 capital-at-risk normalization.
- Phase 4 cluster-direction normalization.
- live/RPC/network behavior.

## Backward Compatibility Contract

1. Old reports without Phase 1 fields must still load.
2. Old raw fields must stay raw and available.
3. New economic/model fields must be additive and absent-safe.
4. If an old report lacks enough raw side/outcome/price data to derive economic context safely, the result is unknown/unavailable, not zero and not inferred.
5. Saved report keys must not be renamed without explicit migration and tests.
6. CSV exports may add columns only. Existing columns must not be renamed or reinterpreted.
7. UI copy may clarify labels, but sorting/filter values must not change in Phase 2 unless separately approved.

## Phase 2 Must Not Include Phase 3 Or Phase 4

Phase 3 capital-at-risk migration remains blocked.

Reason: opening/increasing SELL complement exposure needs verified Polymarket accounting semantics across Data API, CLOB, reconstruction artifacts, and archive outputs. The readiness audit found 502 rows requiring accounting verification and 46 rows with inferred size.

Phase 4 cluster direction normalization remains blocked.

Reason: same-side clustering affects candidate grouping, structural pre-admission, split-wallet interpretation, and possibly Strong Risk context. The readiness audit found 412 direction changes, but this only proves impact, not implementation safety.

## Migration Plan If Later Approved

Implementation must be staged and reversible:

1. Introduce an internal economic probability selector.
   - It must call the existing pure normalizer or an equivalent pure selector.
   - It must return unknown when raw side/outcome/price are unsafe.
   - It must not change raw display fields.

2. Migrate low-probability conviction.
   - Use economic-side probability for the low-probability threshold.
   - Preserve old raw fields for display and diagnostics.
   - Add before/after audit output.

3. Migrate near-certainty checks.
   - Use economic-side probability for near-certainty suppressors.
   - Preserve existing suppressor names unless a separate label migration is approved.
   - Add tests for `SELL Yes @ 0.05` and `SELL No @ 0.99` inversion cases.

4. Migrate Event Forensic later-correctness semantics.
   - Use economic side for opening/increasing correctness.
   - Rebuild winner rank and wallet winning-entry counts from full candidate sets, not display slices.
   - Preserve raw token outcome and raw winner fields for auditability.

5. Preserve raw display fields.
   - Keep `price_implied_probability` / `entryProbability` raw unless a separate compatibility migration is approved.
   - Add model-specific fields if needed instead of reusing legacy keys.

6. Run the Phase 2 impact audit before and after implementation.
   - Compare changed cases and explain every difference.
   - Include archive fixtures before any implementation merge.

7. Only then discuss Phase 3 and Phase 4.
   - Capital-at-risk and cluster normalization need separate RFCs and approvals.

## Test Contract Before Any Implementation

Required tests before implementation:

- `BUY Yes`, `BUY No`, `SELL Yes`, `SELL No` truth table for economic-side probability.
- malformed/missing side, outcome, and price stay unknown.
- decimal and percent input produce the same economic probability.
- low-probability threshold inversion cases:
  - `SELL Yes @ 0.20`: raw low-probability true, economic low-probability false.
  - `SELL No @ 0.80`: raw low-probability false, economic low-probability true.
- near-certainty inversion cases:
  - `SELL Yes @ 0.05`: raw near-certainty false, economic near-certainty true.
  - `SELL No @ 0.99`: raw near-certainty true, economic near-certainty false.
- Event Forensic later-correctness inversion for `SELL Yes` and `SELL No`.
- scanner/archive/Event Forensic old report compatibility.
- archive CSV fixture coverage, including old exports and Phase 1 additive exports.
- cross-mode scoring contract.
- Strong Risk/HER/funding/candidate-admission preservation tests.
- direct source scan showing no Phase 3 capital-at-risk or Phase 4 cluster normalization was included.
- before/after sidecar impact audit against local artifacts.

The executable Phase 2 contract tests live in `tests/test_side_outcome_phase2_model_contract.py`. They describe target semantics without requiring production scorers to use them yet.

## Risk Matrix

| Risk | Why it matters | Guardrail |
|---|---|---|
| Old report compatibility | Historical reports lack Phase 1 fields and must still load | absent-safe derivation, no key rename, old-report tests |
| Historical benchmark drift | Model migration will change which rows trigger low-probability and near-certainty logic | sidecar before/after audit and fixture corpus |
| Strong Risk false positives/false negatives | Strong Risk consumes low-probability, winner-rank, near-certainty, hard-evidence context | no gate changes without separate approval and targeted tests |
| HER routing drift | HER depends on hard evidence and retrospective correctness sources | keep HER unchanged until explicit approval |
| Funding semantics drift | Funding support/suppressors consume price/probability meanings | preserve funding `unknown`, add funding-specific preservation tests |
| Candidate admission drift | Structural admission can be affected by opening exposure and grouping semantics | no candidate-admission change in Phase 2 |
| Cross-mode divergence | Scanner, Archive, and Event Forensic share `_score_trade()` but differ in display/ranking | cross-mode contract tests and mode-specific fixtures |
| Browser display confusion | Raw token price and economic probability can both be useful but mean different things | keep labels explicit, do not silently change sort/filter values |
| Archive coverage gap | Initial readiness audit missed archive artifacts; follow-up archive audit found real local archive rows but also lossy old CSV shapes | use `docs/inspoly_side_outcome_phase2_archive_evidence_gap_20260522.md`, synthetic archive fixtures, and do not rescore from lossy old flagged/secondary CSV rows |
| Phase 3/4 scope bleed | Capital-at-risk and clustering are related but not the same migration | explicit block in tests and RFC |

## Stop Conditions

Stop and do not implement Phase 2 if any of the following are true:

- archive evidence fixtures fail, or the archive evidence report cannot be reproduced on a bounded local sample.
- any implementation plan would rename or reinterpret old raw fields.
- any implementation plan changes Strong Risk, HER, funding eligibility, candidate admission, severity labels, or sorting without separate approval.
- any implementation plan changes capital-at-risk or cluster grouping.
- economic probability cannot be derived safely from raw side/outcome/price.
- Event Forensic winner rank cannot be rebuilt from full candidate rows.
- old report compatibility tests fail.
- cross-mode scoring contract tests fail.
- the before/after impact audit cannot explain changed cases.
- `_score_trade()` or `_event_forensic_score()` would need a broad rewrite rather than a narrow selector migration.

## Approval Gate Decision

Gate decision: `ready_for_phase2_implementation`.

Rationale:

- The readiness audit supports writing this RFC because 412 unique trade keys would change under economic-side model semantics.
- The archive evidence gap campaign found real local archive artifacts and added synthetic archive JSON/CSV fixtures for BUY/SELL YES/NO, missing/malformed prices, old-fields-only rows, Phase 1 additive fields, and lossy archive CSV shapes.
- The bounded archive audit discovered 4,835 archive artifacts, selected 120 balanced artifacts/fixtures, scanned 102 after size skips, loaded 3,308 rows, evaluated 2,021 rows, and found 121 affected unique archive trade keys.
- Evidence categories stayed separated: 112 real local artifacts contributed 3,285 rows / 2,003 evaluable rows / 775 affected rows; 5 existing fixtures contributed 5 rows / 3 evaluable rows / 0 affected rows; 3 synthetic fixtures contributed 18 rows / 15 evaluable rows / 12 affected rows.
- Archive impacts are material and testable: 109 unique keys changed low-probability-30 interpretation, 113 changed low-probability-35 interpretation, 77 changed near-certainty-95 interpretation, 65 changed near-certainty-98 interpretation, and 121 changed direction interpretation.
- Archive compatibility risk is now bounded rather than unknown: archive JSON and trade/candidate CSV rows carry enough raw side/outcome/price evidence, while old flagged/secondary CSV rows can be lossy and must remain unknown for future rescoring.
- Sensitive contexts are affected: 40 sensitive gate-context rows and 35 later-correctness unique-key changes were observed.
- Phase 3 and Phase 4 remain explicitly blocked.

Next allowed step:

- Request separate explicit approval for a narrow Phase 2 implementation that only migrates approved model probability selectors and keeps raw display fields, archive compatibility, Strong Risk/HER/funding/candidate admission, sorting, UI runtime behavior, storage schema, Phase 3 capital-at-risk, and Phase 4 cluster normalization unchanged.

Next blocked step:

- Any further behavior expansion remains blocked. Phase 2 runtime implementation was later approved separately on 2026-05-22, but Phase 3 capital-at-risk normalization, Phase 4 cluster normalization, Strong Risk/HER/funding/candidate-admission changes, storage changes, and UI behavior changes still require separate explicit approval.

## Archive Evidence Appendix, 2026-05-22

Follow-up evidence lives in:

- `tools/side_outcome_archive_evidence_audit.py`
- `tests/test_side_outcome_archive_evidence_audit.py`
- `tests/fixtures/side_outcome_phase2_archive/`
- `docs/inspoly_side_outcome_phase2_archive_evidence_gap_20260522.md`
- `side_outcome_audits/side_outcome_phase2_archive_evidence_gap_20260522.json`

Archive implementation guardrails from the evidence run:

- Use full archive JSON/trade-object fields or current in-memory `Trade` objects for Phase 2 model migration.
- Do not use old flagged/secondary archive CSV rows as a rescoring source when raw token price is missing.
- Preserve old archive report keys and CSV columns as raw-token semantics.
- Add only additive fields if future archive exports need economic/model context.
- Treat missing price/side/outcome as unknown, not zero.
- Do not mutate saved archive reports or generated `archive_outputs`.
- Do not change archive visibility tiers, candidate admission, Strong Risk/HER/funding routing, sorting, browser runtime behavior, Phase 3 capital-at-risk, or Phase 4 cluster-direction behavior in Phase 2.
