# Indexer Warehouse RFC Readiness After Collection Hardening - 2026-05-27

## Decision

Warehouse readiness state: `warehouse_rfc_ready_no_implementation`.

The sidecar indexer now has enough bounded evidence to draft a warehouse RFC. This does not authorize warehouse implementation, production runtime integration, background workers, report/browser wiring, storage schema migration, or broader live collection.

## What Changed

The bounded sidecar runner now supports an optional per-target public-trade cap for multi-target configs:

- collection policy: `per_target_public_trade_cap`
- per-target public-trade limit: 60
- aggregate public-trade limit after market rows: 180
- condition filter mode: one condition per public Data API request
- cursor identity: still aggregate `public_trades`
- SQLite schema: unchanged

Old configs without `maxPublicTradesPerTarget` still use the prior aggregate collection mode.

## Hardened Run Evidence

Fresh local-only DB:

- `.inspoly_indexer/bounded_live_multitarget_per_target_20260527/indexer.sqlite3`

Approved target set:

1. `russia-x-ukraine-ceasefire-by-january-31-2026`
2. `maduro-in-us-custody-by-january-31`
3. `khamenei-out-as-supreme-leader-of-iran-by-february-28`

Run result:

- Targets attempted/completed/failed: 3 / 3 / 0
- Market rows: 3
- Public trade rows: 180
- Cursor rows: 2
- Rows by target: 60 / 60 / 60
- Filter mismatch rows: 0
- Missing-condition rows: 0
- Malformed raw JSON: 0
- Duplicate indicators: 0
- Readiness gate: `indexer_sidecar_readiness_ready_no_runtime`

The previous aggregate collection stored 200 trades on Khamenei and 0 on Russia/Maduro. The hardened collection intentionally changes trade sampling to target-balanced rows.

## Scoped Compare

Scoped comparisons against the previous aggregate-capped DBs show:

- storage risk count: 0
- market identity drift: 0
- raw-hash storage drift: 0
- readiness remains clean
- drift is classified as provider/collection-policy drift because the new policy deliberately fetches 60 rows per target instead of 200 rows from the most active condition.

The compare output gate is `indexer_per_target_collection_compare_ready_no_storage_risk`.

## Readiness Questions

Is live sidecar collection repeatable enough?

Yes for the current three-market target set. Previous repeat evidence showed zero drift under aggregate collection, and the hardened run preserves clean storage/readiness while fixing target coverage.

Is target resolution stable enough?

Yes for these three explicit market slugs. The failed event-family Iran slug remains excluded from bounded market runs.

Is scoped compare strong enough?

Yes for RFC readiness. It can isolate matching market slugs and separate storage identity drift from expected collection-policy drift.

Is public-trade collection representative enough?

Yes for a first warehouse RFC. It now records bounded target-balanced public trades and explicit cap metadata. It is not yet enough for warehouse implementation.

What remains for the RFC?

- Decide whether warehouse cursors must become per-condition rather than aggregate.
- Define retention/deletion policy for local warehouse DBs.
- Define whether market metadata and public trades have separate retention tiers.
- Define repeat-run gates for the per-target policy.
- Define operator controls for target registry, caps, output paths, and rollback.

## First Warehouse RFC Scope

The first warehouse RFC should be sidecar-only and should propose:

- explicit target registry inputs;
- per-target/per-condition public trade collection;
- per-condition cursor design options;
- retained aggregate row caps;
- local-only output and deletion policy;
- readiness audit plus scoped compare gates after every run;
- no production scanner/archive/Event Forensic/browser/report integration.

## Still Blocked

Runtime integration remains blocked. Warehouse implementation remains blocked. Report/browser integration, storage schema migration, background scheduling, scoring/gate changes, saved report mutation, CLOB auth/private keys/trading, and push/PR remain blocked.
