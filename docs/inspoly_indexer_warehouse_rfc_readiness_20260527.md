# Indexer Warehouse RFC Readiness - 2026-05-27

## Decision

Warehouse readiness state: `warehouse_rfc_blocked_needs_collection_hardening`.

This campaign improves repeatability evidence, but it does not justify a warehouse RFC yet. The sidecar indexer is stable enough for more bounded operator probes. It is not representative enough for warehouse design because public-trade collection still uses one aggregate capped query across all targets.

## Readiness Questions

Is live sidecar collection repeatable enough?

Yes for the same three-target set under the current aggregate collection semantics. The latest repeat DB matched the prior hardened three-target DB with zero table, cursor, market identity, trade identity, raw-hash, provider, or storage drift.

Is target resolution stable enough?

Yes for the current three market slugs. The failed event-family slug has been removed from the bounded market set and classified as not directly usable.

Is scoped compare strong enough?

Yes for repeat-run evidence. Scoped compare now handles overlapping market/condition comparison and ignores unrelated targets safely.

Is public-trade collection representative enough?

No. Both three-target runs stored 200 trades for Khamenei and zero for the two anchors. This is repeatable, but it proves collection sampling, not target-balanced coverage.

What schema/retention questions remain?

- Whether warehouse rows should retain per-condition collection cursors.
- Whether run metadata should record effective cap, page count, and uncovered target conditions.
- Whether raw payload retention should be full, capped, or sampled.
- How to separate repeat-run probe DBs from any longer-lived warehouse DB.
- Whether market metadata and public trades should have separate retention tiers.

What operator controls would be required?

- Explicit target set or registry class.
- Max targets, pages, rows, time, and output directory.
- Per-target/per-condition trade caps.
- Fresh output directory requirement.
- No background scheduling unless separately approved.
- Rollback by deleting the sidecar output directory.
- Readiness audit and scoped compare after each run.

What must remain sidecar-only?

Everything in this branch for now: runner, DBs, readiness audits, scoped compares, resolver preflight, collection metadata, and RFC evidence.

## First Warehouse RFC Scope If Later Approved

The first warehouse RFC should not propose production runtime integration. It should propose a sidecar warehouse plan that:

- uses explicit target registries,
- fetches public trades per target or per condition,
- records per-condition cursors and cap metadata,
- preserves read-only/no-auth/no-trading constraints,
- defines retention and deletion rules,
- requires readiness and scoped compare gates before any promotion.

## Blockers

Warehouse RFC readiness is blocked by collection hardening, not by storage identity. The next useful campaign should either add an approved per-target/per-condition collection mode or explicitly scope the future warehouse RFC to market metadata only.

Runtime integration remains blocked.
