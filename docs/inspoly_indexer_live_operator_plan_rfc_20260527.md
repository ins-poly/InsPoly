# InsPoly Live Indexer Operator Plan RFC

Date: 2026-05-27 EEST

Gate: `indexer_live_blocked_needs_operator_approval`

## Scope

This is an RFC only. It does not implement live indexing, a background worker, automatic startup, warehouse mode, report/UI integration, or production runtime reads.

## Allowed Data

A future approved live sidecar may collect only public, read-only data:

- markets and event metadata;
- public trades/fills;
- public orderbook snapshots;
- sidecar cursors;
- optional local health rows.

## Disallowed Data And Behavior

- private user socket data;
- CLOB auth, API keys, signatures, passphrases, private keys, or wallet secrets;
- order creation, cancellation, placement, trading, market making, or strategy execution;
- automatic startup;
- scanner/archive/Event Forensic/browser imports;
- saved report mutation;
- Postgres/Redis/Graph Node as required runtime dependencies.

## Operator Inputs For A Future Approved Run

A live run must be explicit and bounded:

- target market slugs, condition ids, token ids, or event slugs;
- maximum markets;
- maximum pages per endpoint;
- maximum rows;
- timeout;
- stale cursor policy;
- dry-run mode;
- output SQLite DB path;
- whether existing DB content may be reused;
- whether network failure should stop or record unknown health.

## Storage Policy

SQLite sidecar first. Postgres, Redis, queues, Graph Node, or hosted warehouses require a separate future RFC and must remain optional.

## Safety And Rollback

The live indexer must be idempotent, cursor-aware, dry-run capable, and absent-safe. Rollback is deleting the sidecar DB and disabling the operator command. No production report, storage, or UI rollback should be necessary because runtime paths must not depend on it.

## Stop Conditions

Stop before implementation if the design requires:

- production imports;
- background scheduling;
- persistent service startup;
- storage migration;
- saved artifact mutation;
- private/authenticated data;
- trading/order placement;
- changing scanner/archive/Event Forensic behavior.

## Decision

The operator plan is ready for future review, but live indexing remains blocked until explicit operator approval names target scope, network bounds, and allowed output DB policy.
