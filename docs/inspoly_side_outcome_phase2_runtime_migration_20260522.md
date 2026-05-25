# InsPoly Side/Outcome Phase 2 Runtime Migration

- Date: 2026-05-22
- Scope: approved Phase 2 runtime migration only
- Phase 3 capital-at-risk migration: blocked
- Phase 4 cluster direction migration: blocked

## What Changed

Phase 2 moved approved model semantics from raw-token interpretation to economic-side interpretation:

- Scanner `low_probability_conviction` now uses `model_probability`, derived from economic-side probability when side/outcome/price normalize safely.
- Scanner near-certainty checks now use the same economic-side `model_probability`.
- Scanner raw metrics now carry additive provenance fields:
  - `model_probability`
  - `model_probability_basis`
  - `model_economic_direction`
  - `side_outcome_normalization_status`
  - `side_outcome_fallback_reason`
- Event Forensic `laterWon` and winning-entry rank semantics now compare economic side to resolved winning outcome for opening/increasing rows.
- Event Forensic low-probability winner and near-certainty checks now use economic-side model probability.
- Archive/Event Forensic CSV outputs gained additive provenance columns only.

## What Stayed Raw

These fields remain raw-token display/compatibility fields:

- `price_implied_probability`
- `entryProbability`
- `entryProbabilityLabel`
- raw `side`
- raw `outcome`
- raw `orderSide`
- raw `price`
- `raw_token_price`
- `rawTokenPrice`
- existing report/CSV raw trade fields

Old saved reports are not rewritten. Browser sorting/filter values remain raw-token display behavior.

## Fallbacks

If side/outcome/price cannot be normalized safely:

- economic-side fields stay `unknown` / unavailable;
- scanner uses `raw_token_price_fallback` for model probability to preserve prior behavior;
- missing/malformed values are not coerced to zero;
- lossy old archive flagged/secondary CSV rows are not used as rescoring sources.

## Audit Evidence

After implementation, the bounded Phase 2 impact audit was rerun with `--max-files 60 --max-rows-per-file 120`:

| Metric | Count |
|---|---:|
| Records scanned | 2,244 |
| Evaluable records | 2,244 |
| Unique trade keys | 1,376 |
| Affected unique keys | 218 |
| Low-probability 30 changes | 192 |
| Low-probability 35 changes | 205 |
| Near-certainty 95 changes | 37 |
| Near-certainty 98 changes | 20 |
| Sensitive gate-context affected | 41 |

The archive evidence audit was rerun with `--max-files 120 --max-rows-per-file 100 --max-bytes 2000000`:

| Metric | Count |
|---|---:|
| Artifacts discovered | 4,835 |
| Artifacts selected | 120 |
| Artifacts scanned | 102 |
| Records loaded | 3,308 |
| Evaluable records | 2,021 |
| Affected rows | 787 |
| Affected unique trade keys | 121 |
| Lossy CSV rows without price | 1,284 |

Machine-readable verification:

- `side_outcome_audits/side_outcome_phase2_runtime_migration_verification_20260522.json`

## Preserved Invariants

- No scoring weights changed.
- No thresholds changed.
- Strong Risk, HER, funding eligibility, candidate admission, sorting, UI runtime behavior, and storage schema were not directly changed.
- Raw/display fields were preserved.
- Saved reports/artifacts were not mutated.
- No live/RPC/network behavior was added.
- No Phase 3 capital-at-risk normalization was implemented.
- No Phase 4 cluster direction normalization was implemented.

## Remaining Risk

The migration intentionally changes which trades are considered low-probability or near-certainty under the model. That can indirectly affect downstream labels and gates because those gates consume existing flags. The gate logic itself was not rewritten.

Lossy old archive CSV rows still cannot support safe rescoring. Future archive work must use full archive JSON/trade-object fields or current in-memory `Trade` objects.

## Remaining Blocks

- Phase 3 capital-at-risk normalization requires separate approval and accounting validation.
- Phase 4 cluster direction normalization requires separate approval because cluster grouping and split-wallet semantics can change.
- Any direct Strong Risk/HER/funding/candidate-admission migration requires a new gate and targeted tests.
- UI sort/filter behavior changes remain out of scope.
