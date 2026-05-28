# Indexer Warehouse RFC Decision - 2026-05-27

## Decision

Final gate: `indexer_warehouse_rfc_ready_for_future_w0_implementation`.

The current evidence supports a future W0 implementation campaign for no-runtime warehouse schema/readiness cleanup. It does not support warehouse implementation in this campaign, and it does not approve production runtime integration, scheduling, report/browser integration, or storage schema migration.

## Why This Gate Is Supported

Evidence is now strong enough for RFC readiness:

- bounded manual sidecar runs work;
- same-slug repeat had zero drift;
- target/provider hardening produced a stable three-market set;
- scoped compare can isolate overlapping target drift;
- per-target collection prevents cap starvation and produced 60/60/60 rows;
- latest readiness audit is clean;
- latest scoped compare storage risk count is 0;
- sidecar helpers remain isolated from production runtime paths.

## Why Implementation Remains Blocked

The RFC still leaves important implementation decisions unresolved:

- per-condition cursor design;
- raw DB retention and deletion limits;
- append-mode versus fresh-run DB policy;
- old sidecar DB compatibility if any schema version is added;
- analyst packet shape;
- report pointer product approval;
- scheduling/background safety.

Those are W0/W1+ decisions, not current implementation approvals.

## Approved Future Direction

Recommended next campaign:

`W0 - no-runtime schema/readiness cleanup`

W0 may draft or refine schema/readiness contracts and tests. It must not run live ingestion, create a warehouse write command, migrate production storage, or integrate with reports/browser/scoring/runtime paths unless separately approved.

## Still Blocked

- Warehouse write command.
- Production runtime integration.
- Scheduled/background operation.
- Report/browser pointer or panel work.
- Production storage schema changes.
- Scoring/gate/funding/Phase 3 changes.
- Saved report mutation.
- CLOB auth/private keys/trading/order placement.
- Push/PR.
