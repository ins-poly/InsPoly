# Indexer Per-Target Collection Hardening Campaign - 2026-05-27

## Final Gate

`indexer_collection_hardening_ready_for_warehouse_rfc_no_runtime`

The sidecar runner now prevents silent multi-target public-trade starvation when an operator config opts into per-target caps. One approved live probe over the exact three approved slugs completed with balanced target coverage and clean readiness. Warehouse RFC drafting is now justified; warehouse implementation and runtime integration remain blocked.

## Policy Implemented

Selected policy: `per_target_public_trade_cap_with_aggregate_safety_guard`.

The runner behavior is:

- old configs continue using `aggregate_condition_filter`;
- new multi-target configs may set `limits.maxPublicTradesPerTarget`;
- each resolved condition is fetched separately;
- the configured per-target cap limits each target;
- `maxRows` remains the aggregate safety bound;
- run summaries record `collectionPolicy`, `perTargetPublicTradeLimit`, `aggregatePublicTradeLimit`, `rowsByTarget`, `targetStarvationWarnings`, and `capExhaustionWarnings`;
- SQLite schema and production runtime imports are unchanged.

The config validator now rejects unsafe per-target cap combinations that cannot fit inside `maxRows` after one market row per target.

## Preflight

Config: `.inspoly_indexer/bounded_live_multitarget_per_target_20260527/operator_config.json`

Preflight gate: `indexer_bounded_live_config_valid_for_operator_review`

Bounds:

- max markets: 3
- max pages: 2
- max rows: 183
- per-target public-trade cap: 60
- timeout: 120 seconds
- output DB: `.inspoly_indexer/bounded_live_multitarget_per_target_20260527/indexer.sqlite3`

No auth, private keys, trading, background worker, warehouse mode, production integration, saved artifact mutation, or report/browser integration was present in the config.

## Live Probe

Approved target set:

1. `russia-x-ukraine-ceasefire-by-january-31-2026`
2. `maduro-in-us-custody-by-january-31`
3. `khamenei-out-as-supreme-leader-of-iran-by-february-28`

Result:

- Targets attempted/completed/failed/skipped: 3 / 3 / 0 / 0
- Market rows: 3
- Public trade rows: 180
- Cursor rows: 2
- Rows by target: Russia 60, Maduro 60, Khamenei 60
- Filter mismatch rows: 0
- Missing-condition rows: 0
- Malformed raw JSON: 0
- Duplicate indicators: 0
- Elapsed time: 1.585 seconds
- Readiness gate: `indexer_sidecar_readiness_ready_no_runtime`

Warnings were limited to explicit per-target cap notices and the known skipped orderbook snapshot note.

## Compare And Drift

Scoped compare output: `validation_outputs/inspoly_indexer_per_target_collection_scoped_compare_20260527.json`

The compare gate is `indexer_per_target_collection_compare_ready_no_storage_risk`.

The prior aggregate-capped DBs stored 200 Khamenei rows and 0 Russia/Maduro rows. The hardened DB stores 60 rows for each target, so trade identity and row-count drift are expected collection-policy drift, not storage drift.

Storage risk count is 0.

## Warehouse Recheck

Warehouse readiness state: `warehouse_rfc_ready_no_implementation`.

This means a future warehouse RFC can now be drafted. It does not approve:

- warehouse implementation;
- production runtime integration;
- background scheduling;
- storage schema migration;
- report/browser wiring;
- scoring/gate/funding/Phase 3 changes.

The first RFC should focus on sidecar-only warehouse scope, per-condition cursor design, retention policy, target registry rules, operator caps, readiness audit gates, scoped compare gates, and rollback.

## Local-Only Artifacts

The following raw artifacts remain local-only and should not be staged:

- `.inspoly_indexer/bounded_live_multitarget_per_target_20260527/operator_config.json`
- `.inspoly_indexer/bounded_live_multitarget_per_target_20260527/raw_run_summary.json`
- `.inspoly_indexer/bounded_live_multitarget_per_target_20260527/indexer.sqlite3`

## Preserved Boundaries

No production scanner/archive/Event Forensic/browser/report/storage path imports the sidecar runner or audit tools. No saved reports were mutated. No daemon, scheduler, background worker, warehouse mode, CLOB auth, private key, trading, order placement, push, or PR was used.
