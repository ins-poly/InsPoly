# RFC: Side/Outcome Price Normalization

Date: 2026-05-07

Status: Phase 1 display/schema implementation completed on 2026-05-22. Phase 2/3/4 model, capital-at-risk, and clustering migrations remain blocked without separate explicit approval.

## Problem

InsPoly currently stores and displays raw traded-token price as `price_implied_probability`. This is correct enough for `BUY Yes` and `BUY No`, but wrong for opening/increasing `SELL Yes` and `SELL No`.

Example:

- Market: `Will the U.S. invade Iran before 2027?`
- Trade: `SELL Yes`
- Entry token price: `19.9%`
- Current UI label: entry probability `19.9%`
- Economic exposure: No side, implied probability around `80.1%`

This can make an ordinary high-probability No exposure look like a low-probability Yes-side conviction trade.

## RFC Classification Summary

| Finding | Classification | Current status |
|---|---|---|
| UI labels raw token price as entry chance | `display_only_bug` | Confirmed |
| Reports lack token-vs-economic fields | `reporting_schema_gap` | Confirmed |
| Low-probability / later-correctness signals use raw token price/outcome | `model_behavior_risk` | Confirmed |
| Opening short capital-at-risk uses raw notional | `capital_at_risk_risk` | Confirmed |
| Same-side clusters do not group economic equivalents | `cluster_direction_risk` | Confirmed |
| Favorable repricing for SELL uses falling token price as favorable | `no_issue_found` | Confirmed, with field-label caveat |
| Opening SELL can be classified as opening short exposure | `no_issue_found` | Confirmed |

Phase 1 implementation note, 2026-05-22:

- Added additive raw-token/economic-side fields to new scanner raw metrics, archive CSV rows, Event Forensic payloads/CSV rows, browser payloads, and report text.
- Kept old raw fields, including `price_implied_probability` and `economic_direction`.
- Clarified browser labels so raw traded-token price is shown as token price, with separate economic-side probability context when safely derivable.
- Did not change `_score_trade()`, `_event_forensic_score()`, Strong Risk gates, HER routing, funding eligibility, candidate admission, severity labels, low-probability logic, later correctness, winner rank, capital-at-risk, or same-side clustering.

## Current Behavior

Current execution-state logic:

- `BUY` -> `increase_long`.
- Opening `SELL` with no prior same-token position -> `increase_short`.
- `economic_direction` string is `long_<outcome>` or `short_<outcome>`.

Current price/probability behavior:

- `price_implied_probability = trade.price * 100`.
- UI card/detail values are derived from `trade.price` first, then this raw metric.
- No field distinguishes traded-token price from economic-side probability.

Current outcome behavior:

- Event Forensic `laterWon` and winner rank compare `trade.outcome` to the resolved winning outcome.
- For opening shorts, this reverses economic correctness.

Current cluster behavior:

- Scanner same-side clusters use exact raw `side/outcome`.
- Event Forensic timing clusters use exact raw `orderSide/side`.
- Split-wallet and coordinated-sizing groups use `economic_direction`, but current values remain `short_yes` versus `long_no`, not normalized No exposure.

## Desired Normalization Contract

Introduce one shared normalizer, then consume its fields in separate approved phases.

Required normalized fields:

- `rawTokenOutcome`: `YES` or `NO`
- `rawOrderSide`: `BUY` or `SELL`
- `rawTokenPrice`: traded token price
- `economicSide`: `YES` or `NO`
- `economicSideProbability`: probability on the trader's economic event side
- `economicDirection`: normalized side key, preferably `long_yes` or `long_no`
- `economicCapitalAtRisk`: normalized stake/liability estimate
- `economicRepricingDirection`: `token_price_up` for long token, `token_price_down` for short token

Truth table:

| Trade | Economic side | Economic-side probability | Normalized direction |
|---|---|---:|---|
| BUY Yes | Yes | `YES price` | `long_yes` |
| SELL Yes | No | `1 - YES price` | `long_no` |
| BUY No | No | `NO price` | `long_no` |
| SELL No | Yes | `1 - NO price` | `long_yes` |

## Proposed Phases

### Phase 1: Reporting Schema And Display Only

Classification: `display_only_bug`, `reporting_schema_gap`

Allowed changes:

- Add a shared helper to compute normalized side/probability fields.
- Add fields to `raw_metrics`, archive CSV, Event Forensic payloads, scanner UI card payloads, and report text.
- Update UI label from `Entry chance` to either:
  - `Token price` when showing raw token price only, or
  - `Economic probability` when showing normalized probability.
- Keep old raw fields for backwards compatibility.

Forbidden in Phase 1:

- Do not change `_score_trade()` weights or thresholds.
- Do not change Strong Risk gates.
- Do not change HER routing.
- Do not change funding eligibility.
- Do not change candidate admission.
- Do not mutate saved outputs.

### Phase 2: Model Behavior Migration

Classification: `model_behavior_risk`

Candidate changes after Phase 1 is reviewed:

- Use `economicSideProbability` for:
  - `low_probability_conviction`
  - `near_certainty_trade`
  - `materially_uncertain_flag`
  - `low_probability_early_winner`
  - suspicious-funding low-probability support/suppressor checks
  - Event Forensic low-probability winner scoring
- Use `economicSide` for:
  - later correctness
  - winner rank
  - wallet winning opening entries
  - retrospective correctness gates

This phase changes model behavior and should be separately approved and validated.

### Phase 3: Capital-At-Risk Normalization

Classification: `capital_at_risk_risk`

Candidate changes:

- Preserve raw executed token notional.
- Add normalized economic capital-at-risk.
- For opening `BUY`, economic stake is token price times size.
- For opening `SELL`, assess complement-side stake/liability from `1 - token_price` times size, subject to verification against Polymarket accounting and Data API semantics.

Do not silently replace `trade_notional_usdc`; add fields first and compare distributions.

### Phase 4: Cluster Direction Normalization

Classification: `cluster_direction_risk`

Candidate changes:

- Normalize same-side scanner cluster keys to economic side.
- Normalize structural pre-admission direction keys.
- Normalize split-wallet and coordinated-sizing grouping.
- Normalize Event Forensic timing clusters.

Compatibility requirement: keep raw `side/outcome` fields in exports, and add normalized fields rather than replacing old columns.

## No-Issue Areas

`no_issue_found`:

- Opening `SELL` is already recognized as opening short exposure when no prior same-token position is visible.
- Favorable repricing math for `SELL` is directionally aligned because falling token price is favorable for a short token position.

Caveat: those paths still need clearer field labels because the saved values are traded-token values, not explicit economic-side values.

## Tests

Added audit-only tests in `tests/test_side_outcome_price_normalization_audit.py`.

Current behavior tests pass:

- Opening `SELL` classifies as `increase_short`.
- Opening `SELL` gets nonzero current capital-at-risk.
- Favorable repricing for `SELL Yes` uses falling Yes token price as favorable.

Expected-failure tests document future requirements:

- `SELL Yes @ 0.20` should expose economic probability `80.0%`.
- `SELL No @ 0.80` should expose economic probability `20.0%`.
- Low-probability flags should use economic-side probability.
- Same-side clustering should group `SELL Yes` with `BUY No`.
- UI should label raw entry values as token price when they are not normalized.

## Recommended Next Prompt

Implement Phase 1 only: add shared side/outcome normalization fields and clarify UI/report labels, while preserving `_score_trade()`, Strong Risk gates, scoring weights, severity labels, HER routing, funding eligibility, candidate admission, and old saved outputs. Do not migrate low-probability, later-correctness, capital-at-risk, or cluster logic until a separate Phase 2/3/4 prompt.
