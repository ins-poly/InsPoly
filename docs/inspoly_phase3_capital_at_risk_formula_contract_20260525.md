# InsPoly Phase 3 Capital-at-Risk Formula Contract

- Date: 2026-05-25
- Scope: formula contract only
- Runtime implementation authorized: `false`
- Network/RPC used: `false`
- Current Phase 3 gate before this campaign: `keep_phase3_blocked`

## Purpose

This contract defines the accounting semantics that any future Phase 3 runtime migration would have to satisfy. It does not approve changes to scanner/archive/Event Forensic runtime behavior, `_score_trade()`, `_event_forensic_score()`, scoring weights, thresholds, Strong Risk, HER, funding, candidate admission, storage schema, saved artifacts, or UI sorting/filtering.

## Existing Context

Phase 2 normalized model probability from raw token price to economic-side probability. Phase 4 normalized same-side cluster direction. Neither phase changed capital-at-risk.

The new Polymarket protocol and ledger helpers improve sidecar evidence:

- `app/polymarket_protocol.py` preserves CLOB/subgraph semantics without network or auth.
- `app/polymarket_ledger.py` distinguishes explicit `usdcSize`, `size * price`, unknown cash, source disagreement, and ledger/PnL quality notes.
- `tools/validate_polymarket_ledger_against_artifacts.py` checks reconstruction-style artifacts read-only.

These helpers clarify accounting, but they do not make Phase 3 a production signal.

## Definitions

- Raw token price: fill price of the YES/NO token transacted.
- Raw fill notional: `size * raw_token_price`.
- Observed cash: explicit cash/proceeds field such as `usdcSize`, when present.
- Cash paid: BUY-side maximum loss, normally observed cash or `size * price`.
- Proceeds: SELL-side cash received; not the same as max loss.
- Collateral / max loss: the SELL-side amount at risk if the sold token settles against the trader.
- Economic-side probability: Phase 2 side/outcome probability after BUY/SELL inversion.
- Cluster direction: Phase 4 same-side grouping key; useful for clustering, not for exposure sizing.

## BUY Opening Exposure

For opening or increasing BUY YES/NO:

1. If explicit cash is present and its source is documented as fill cash, BUY exposure may use that cash.
2. Otherwise, if `size` and raw token `price` are valid, BUY exposure may use `size * price`.
3. Missing/malformed size or price is `unknown`, not zero.

BUY examples:

- BUY YES, price `0.20`, size `100`: cash paid and max loss are `20`.
- BUY NO, price `0.20`, size `100`: cash paid and max loss are `20`.

## SELL Opening Max-Loss Exposure

For opening or increasing SELL YES/NO:

1. Raw fill notional and observed cash/proceeds must remain separate from max loss.
2. `usdcSize` is observed cash/proceeds unless a source explicitly documents it as collateral/max-loss.
3. If side, outcome, size, and raw token price are direct/auditable trade fields, SELL max loss can be computed as `size * (1 - raw_token_price)`.
4. If any required field is missing/malformed, exposure remains `unknown`.

SELL examples:

- SELL YES, price `0.20`, size `100`: observed proceeds are about `20`; max loss is `80`.
- SELL NO, price `0.20`, size `100`: observed proceeds are about `20`; max loss is `80`.
- SELL YES, price `0.98`, size `100`: observed proceeds are about `98`; max loss is `2`.

## What `usdcSize` Means

`usdcSize` is allowed as an explicit observed cash field. It is not sufficient by itself to identify SELL max loss.

For BUY rows, `usdcSize` can improve cash-paid precision.

For SELL rows, `usdcSize` must be preserved as cash/proceeds and reported separately from `size * (1 - price)`. If `usdcSize` disagrees with `size * price`, the disagreement is a quality note, not a reason to silently choose one accounting meaning.

## Interaction With Phase 2 And Phase 4

Phase 2 economic probability helps identify the effective YES/NO side and probability. It does not determine dollars at risk.

Phase 4 normalized cluster direction helps group economically equivalent BUY/SELL expressions. It does not determine collateral, proceeds, or max loss.

Capital-at-risk needs its own source-quality gate. A row can be safe for Phase 2/4 semantics and still unsafe for Phase 3 sizing.

## Old Report And Lossy Row Semantics

Old rows with only notional, `capital_at_risk_usdc`, score, label, or visibility fields cannot be reinterpreted as economic max loss.

Old reports must remain absent-safe:

- no migration in place;
- no backfill by guessing;
- no reinterpretation of existing keys;
- missing means `unknown`, not zero.

## No-Op Behavior For Unsafe Rows

Future runtime code, if approved, must no-op for rows with:

- missing/malformed side;
- missing/malformed outcome;
- missing/malformed raw token price;
- missing/malformed size;
- only old notional/capital fields;
- source cash disagreement without a documented choice;
- SELL rows where only observed cash/proceeds are known.

No-op means preserving current capital-at-risk behavior or marking the new economic exposure field unknown, depending on the approved implementation RFC. It must not silently change scoring or gates.

## Required Future Runtime Guardrails

Any future implementation RFC must include:

- a central capital selector/helper;
- separate fields for raw notional, observed cash/proceeds, and economic max loss;
- source-quality status and fallback reason;
- old-report no-op behavior;
- before/after sensitive gate audit;
- tests proving `_score_trade()` and `_event_forensic_score()` only change where explicitly approved.

This formula contract is sufficient for sidecar evaluation. It is not sufficient by itself for runtime migration.
