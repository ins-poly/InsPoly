# InsPoly Bounded Live Indexer Operator Approval Packet

Date: 2026-05-27 EEST

Gate: `indexer_bounded_live_approval_packet_ready`

Runtime changed: `false`

## Current Sidecar State

The optional indexer sidecar already has local-only pieces that can support a future bounded operator run:

- `app/indexer/storage.py` defines SQLite tables for cursors, markets, trades, orderbook snapshots, wallet snapshots, and score history.
- `app/indexer/adapters.py` normalizes Gamma market rows, Data API trade rows, and orderbook snapshots into sidecar models.
- `app/indexer/health.py` summarizes cursor freshness and cursor error state.
- `tools/indexer_fixture_dry_run.py` loads explicit local fixtures into a sidecar SQLite DB without network calls.
- `tools/indexer_sidecar_readiness_audit.py` inspects an existing sidecar DB in read-only mode.

These helpers are sidecar-only. They are not imported by scanner, archive, Event Forensic, browser, storage, or Polymarket runtime paths.

## What A Future Bounded Run Would Do

A future operator-approved run would fetch only public Polymarket data for an explicit target set and write it to a local SQLite sidecar DB. The allowed public data classes are:

- market metadata;
- public trades;
- public orderbook snapshots;
- cursors and health rows;
- optional local score-history rows derived from approved sidecar inputs.

The run would be manually invoked by an operator. It would not start automatically, run as a background service, or become a warehouse dependency for existing workflows.

## What It Would Not Do

The bounded live indexer run would not:

- use CLOB auth, private keys, API credentials, signatures, user socket auth, or order placement;
- place, cancel, or modify orders;
- write production reports or mutate saved artifacts;
- change scoring, gates, labels, candidate admission, funding semantics, sorting, or routing;
- import the sidecar into scanner, archive, Event Forensic, browser, or storage runtime;
- create a storage schema migration;
- require Postgres, Redis, Graph Node, or a hosted service.

## Required Operator Inputs

Before any live run, the operator must provide a config with:

- `dryRun: true` until the run itself is separately approved;
- `requiresOperatorApproval: true`;
- explicit target identifiers under `targets.marketSlugs`, `targets.conditionIds`, `targets.eventSlugs`, or `targets.tokenIds`;
- bounded limits for `maxMarkets`, `maxPages`, `maxRows`, and `timeoutSeconds`;
- `networkExecution: false`, `productionIntegration: false`, `autoStart: false`, `backgroundWorker: false`, `warehouseMode: false`, and `mutateSavedArtifacts: false` in the approval-review config;
- local SQLite output under `.inspoly_indexer/` or `indexer_sidecar_outputs/`.

## Bounds For First Approval

Recommended first-run hard caps:

| Bound | Maximum |
| --- | ---: |
| Target markets/events | 50 |
| Pages per data source | 25 |
| Rows total | 50000 |
| Timeout | 1800 seconds |

Any larger scope should be a separate approval packet.

## New Config Validator

This campaign adds `tools/indexer_bounded_live_config_validator.py` and focused tests. The validator reads a proposed config JSON and checks that it is explicit, bounded, local-only, and free of auth/trading fields. It does not fetch network data, initialize a database, start ingestion, or mutate saved artifacts. Its success gate is `indexer_bounded_live_config_valid_for_operator_review`, which is an input to owner review only, not permission to ingest.

## Failure And Rollback

If a future bounded run fails, rollback is limited to deleting the sidecar SQLite DB and validation outputs for that run. No production report, storage schema, browser state, or scoring output should need rollback because none is allowed to depend on the sidecar.

## Evidence Needed Before Warehouse Or Runtime Integration

Warehouse or runtime integration remains blocked until a future campaign proves:

- stable cursor replay across repeated live runs;
- bounded row growth and stale-cursor behavior;
- duplicate and malformed JSON rates;
- no production import path dependency;
- no report/schema/browser changes;
- old workflows remain identical when the sidecar DB is absent.

## Decision

The bounded live indexer approval packet is ready for owner review. Live ingestion is still not implemented or approved.
