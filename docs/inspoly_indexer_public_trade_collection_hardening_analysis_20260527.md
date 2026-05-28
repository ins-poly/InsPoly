# Indexer Public Trade Collection Hardening Analysis - 2026-05-27

## Decision

Gate: `public_trade_collection_needs_per_target_hardening_before_warehouse_rfc`.

The current bounded runner is repeatable for the same three-target set, but its public-trade collection is not representative across targets. The safe improvement in this campaign is sidecar-only metadata and warnings; collection behavior itself still needs a separate approved hardening step before any warehouse RFC.

## What The Code Does

`tools/indexer_bounded_live_sidecar_run.py` resolves the approved market slugs, stores market rows, then fetches public trades once with a comma-separated condition filter:

- collection mode: aggregate condition filter
- cursor identity: one aggregate `public_trades` cursor
- per-target cursor rows: no
- per-target trade cap: no
- page size: `min(100, maxRowsAfterMarketRows)`
- configured pages: `maxPages`
- configured max rows in this campaign: `500`
- market rows stored first: `3`
- effective public-trade fetch cap: `min(497, 2 * 100) = 200`

So the observed 200 public-trade rows are a code-level bounded-run cap from two 100-row pages, not a storage schema limit and not evidence of provider exhaustion.

## Evidence

Single-target runs:

- Russia first run: 1 market, 200 Russia trades, 2 cursors.
- Russia repeat run: 1 market, 200 Russia trades, 2 cursors, zero drift.

Multi-target runs:

- First partial multi-target run: Russia 200 trades, Maduro 0 trades, failed Iran event-family slug.
- Hardened three-target run: Russia 0 trades, Maduro 0 trades, Khamenei 200 trades.
- Repeat2 three-target run: Russia 0 trades, Maduro 0 trades, Khamenei 200 trades.

The repeated three-target result is deterministic under the current query shape. It is not balanced across targets.

## Answers

- Is 200 a global cap? Yes for this runner configuration. `maxPages=2` and a 100-row page size make the effective public-trade fetch cap 200 even though `maxRows` is 500.
- Is it per-run, per-target, per-endpoint, or provider-imposed? It is per-run for one aggregate Data API query. It is not per-target.
- Are rows sampled in a way that can displace target coverage? Yes. The aggregate query can fill the cap with one active condition and leave other target conditions at zero.
- Are cursors stored per target? No. The runner stores aggregate `markets` and `public_trades` cursors only.
- Is collection fair across targets? No.
- Would per-target caps be safer? Yes, especially before warehouse mode.
- Would per-condition cursor identity be needed? Yes for warehouse-grade repeatability and recovery semantics.
- Can this be improved sidecar-only without changing production storage schema? Yes. The first safe step is richer summary metadata and warnings. A later sidecar-only collection behavior change could fetch per target while preserving the existing DB schema, but it should be separately approved and compared.
- Did this campaign change existing DB semantics? No. It only adds future runner summary metadata and warnings; it does not alter storage schema or mutate existing DBs.

## Safe Hardening Applied

The runner now emits `summary.publicTradeCollection` for future runs, including:

- collection mode and aggregate cursor identity
- effective public-trade fetch cap
- per-condition stored row counts
- targets without trade rows
- whether the global cap may underrepresent targets
- recommended hardening action

It also warns when a multi-target aggregate public-trade collection may underrepresent targets. This is sidecar-only output metadata and does not change production runtime behavior.

## Follow-Up

Before warehouse RFC readiness, choose one:

1. Keep aggregate collection and define warehouse scope as metadata/market-only first.
2. Add an approved sidecar-only per-target/per-condition public-trade collection mode with per-condition cursor identity and focused repeat comparisons.
3. Keep indexer work as bounded probe only.

The recommended next step is option 2.
