# InsPoly Phase 3 Capital Unblock Requirements

- Date: 2026-05-22
- Scope: unblock requirements only
- Machine output: `validation_outputs/inspoly_phase3_capital_unblock_requirements_20260522.json`
- Runtime implementation: false
- Network/RPC used: false
- Gate decision: `phase3_unblock_requirements_documented_keep_blocked`

## Required Fields For Safe BUY Exposure

- raw order side;
- raw token outcome;
- raw token price;
- share size;
- observed cash field when explicitly available.

## Required Fields For Safe SELL Max-Loss Exposure

- raw order side;
- raw token outcome;
- raw token price;
- share size;
- collateral or max-loss source, or an auditable complement formula.

For SELL rows, raw fill notional and `usdcSize` are not automatically equivalent to max-loss exposure. `usdcSize` may be observed cash/fill value; it must not be silently promoted to collateral semantics.

## Permanently Unsafe Old Rows

Old rows that only preserve notional, score, label, or visibility fields are unsafe for reinterpretation. Missing side/outcome/price/size remains unknown, not zero.

## Tests Required Before Runtime

- BUY YES/NO cash-paid exposure stays unchanged when fields are complete.
- SELL YES/NO complement max-loss uses `size * (1 - raw token price)` only with sufficient source quality.
- `usdcSize` disagreement is reported, not hidden.
- old/lossy rows remain unrescored.
- funding/HER/Strong Risk gates do not directly mutate without separate approval.

## Evidence Required Before Runtime

- bounded real artifact sample with side/outcome/price/size/`usdcSize` coverage;
- source-quality distribution for SELL rows;
- sensitive-overlap review packet with no gate tuning;
- approval for any live/RPC collection if local artifacts are insufficient.

## Why Phase 3 Remains Blocked

The Phase 3 audit found material SELL capital deltas and sensitive context overlap. The current evidence is sufficient to document requirements, not sufficient to implement runtime capital-at-risk normalization.

## Gate

Decision: `phase3_unblock_requirements_documented_keep_blocked`.
