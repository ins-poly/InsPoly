# InsPoly pUSD / CLOB Collateral Semantics Gap Audit

Date: 2026-05-27 EEST

Gate: `phase3_runtime_still_blocked`

## Current Funding And Capital State

- `app/funding_context.py` traces Polygon USDC/USDC.e addresses only.
- Missing funding remains `unknown`, not clean evidence.
- `app/polymarket_ledger.py` separates explicit `usdcSize`, `size * price`, unknown cash, and source disagreement.
- `docs/inspoly_phase3_capital_at_risk_formula_contract_20260525.md` separates raw notional, observed cash/proceeds, and SELL max loss.
- Phase 3 final evidence remains `phase3_sidecar_only_final` with blocker `phase3_blocked_until_new_source_fields`.

## Current USDC Assumptions

Funding trace settings are `polygon_usdc_v1` and include only two USDC-family token addresses. There is no pUSD token, CLOB collateral token, exchange/onramp, wrapping, or settlement-contract source map in production funding analysis.

## Ledger Cash Ambiguity

Ledger logic intentionally preserves ambiguity:

- `usdcSize` is explicit observed cash/proceeds.
- `size_price` is fallback cash when price and size are present.
- missing price/size/cash remains unknown.
- source cash disagreement is a quality note, not a silent reinterpretation.
- SELL proceeds are not automatically SELL max loss.

## Phase 3 Blockers

Runtime remains blocked because:

- safe real sensitive-overlap SELL rows remain `0`;
- old notional-only rows remain unsafe for reinterpretation;
- display-only saved-report SELL rows dominate unsafe evidence;
- no explicit collateral/max-loss source field exists;
- formula-derived SELL max loss needs explicit product approval or stronger source fields;
- pUSD/collateral addresses and tracing semantics are unverified.

## C3 Static Semantics

Implemented: `app/polymarket_collateral_semantics.py` with static fixture tests.

The helper is sidecar/static only. It classifies source facts as unknown, rejected, fixture-only, or verified static source, while keeping runtime integration disabled. It does not hardcode real pUSD/collateral addresses as production truth and is not imported by funding, scanner, archive, Event Forensic, browser, storage, or Polymarket runtime paths.

## Decision

pUSD/CLOB collateral semantics need verified source research before any funding runtime integration. Phase 3 runtime remains blocked.
