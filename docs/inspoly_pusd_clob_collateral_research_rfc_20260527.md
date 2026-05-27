# InsPoly pUSD / CLOB Collateral Source Research RFC

Date: 2026-05-27 EEST

Gate: `pusd_collateral_research_rfc_ready`

## Research Need

Before InsPoly can reason about pUSD or CLOB collateral in funding/capital runtime, it needs verified static facts and a product decision about tracing semantics.

Required facts:

- canonical pUSD token address and chain;
- canonical CLOB collateral token or contract address;
- relevant exchange, onramp, wrapping, settlement, or bridge addresses;
- whether pUSD transfers, wraps, exchange fills, or collateral locks should count as funding context;
- whether a direct collateral/max-loss source field exists.

## Acceptable Source Types

- official Polymarket or protocol documentation with addresses;
- verified contracts;
- local chain artifacts captured from a trusted source;
- trusted explorer pages with contract verification.

## Unacceptable Source Types

- blogs without addresses;
- timing inference;
- heuristic wallet clustering;
- screenshots without verifiable address data;
- any source that requires private keys, auth, or trading access.

## Fixture Strategy

Encode source facts in static fixtures with:

- source type;
- role;
- symbol;
- chain;
- address;
- source URL or local artifact reference;
- production-truth flag;
- quality notes.

Fixtures may contain fake addresses for tests, but fake/static fixture facts must not become production truth. Missing facts remain `unknown`.

## Runtime Approval Requirements

Funding runtime integration requires:

- verified addresses;
- explicit tracing semantics;
- unknown-safe behavior for missing facts;
- no old-report reinterpretation;
- no Phase 3 scoring/routing change unless separately approved;
- focused tests proving old reports and missing facts stay absent-safe;
- operator approval for any live/RPC source collection.

## Decision

Research RFC is ready. No funding runtime integration or Phase 3 runtime implementation is approved.
