# Indexer Repeatability, Collection Hardening, And Warehouse-RFC Readiness Campaign - 2026-05-27

## Final Gate

`indexer_repeatability_needs_collection_hardening`

The exact three-target set is repeatable at the sidecar DB level. Warehouse RFC readiness remains blocked because public-trade collection is still aggregate-capped and can underrepresent targets.

## Approved Target Set

1. `russia-x-ukraine-ceasefire-by-january-31-2026`
2. `maduro-in-us-custody-by-january-31`
3. `khamenei-out-as-supreme-leader-of-iran-by-february-28`

## Repeat2 Run Result

Fresh local-only output:

- `.inspoly_indexer/bounded_live_multitarget_repeat2_20260527/indexer.sqlite3`

Run summary:

- Targets attempted: 3
- Targets completed: 3
- Targets failed/skipped: 0
- Market rows: 3
- Public trade rows: 200
- Cursor rows: 2
- Malformed raw JSON: 0
- Duplicate indicators: 0
- Elapsed time: 2.178 seconds
- Readiness gate: `indexer_sidecar_readiness_ready_no_runtime`

Target trade rows:

- Russia: 0
- Maduro: 0
- Khamenei: 200

No daemon, scheduler, background loop, production import, saved-report mutation, auth, trading, or external write path was used.

## Scoped Compare Result

Previous hardened three-target DB vs repeat2 DB:

- Gate: `indexer_sidecar_compare_ready_for_repeat_run`
- Table drift: 0
- Cursor drift: 0
- Market identity drift: 0
- Trade identity drift: 0
- Raw-hash drift: 0
- Storage risk: 0

Russia same-slug repeat DB vs repeat2 DB:

- Gate: `indexer_sidecar_compare_warn_provider_drift`
- Storage risk: 0
- Drift reason: the multi-target aggregate collection stored no Russia trades while the single-slug run stored 200.

## Collection Hardening Result

The 200-row public-trade result is produced by current runner bounds:

- one aggregate condition filter,
- two pages,
- 100-row page size,
- aggregate `public_trades` cursor,
- no per-target cap,
- no per-condition cursor identity.

This is stable but not target-balanced. This campaign added sidecar-only future-run metadata and warnings to make the collection mode explicit. It did not change DB schema or live collection behavior.

## Warehouse RFC Readiness

Warehouse readiness state: `warehouse_rfc_blocked_needs_collection_hardening`.

The first future warehouse RFC, if later approved, should be sidecar-only and should start with per-target/per-condition public-trade collection, per-condition cursor identity, retention rules, and post-run readiness/compare gates. Production runtime integration remains blocked.

## Strategic Outcome

What is now proven:

- the exact three market slugs resolve and ingest repeatedly,
- the sidecar storage schema stays healthy,
- the same three-target DB content repeats with zero drift,
- scoped compare is usable for repeat-run review.

What remains unproven:

- representative trade coverage across multiple targets,
- per-condition cursor recovery,
- warehouse retention policy,
- any production runtime/report/browser integration.

## Next Step

Run a separate approval-gated sidecar collection-hardening campaign to add per-target or per-condition public-trade collection and compare it against the aggregate-capped behavior. Do not start warehouse implementation yet.
