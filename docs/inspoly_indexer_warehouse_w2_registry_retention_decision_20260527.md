# Indexer Warehouse W2 Registry And Retention Decision - 2026-05-27

## Decision

Final W2 gate: `indexer_warehouse_w2_registry_retention_ready`.

W2 is ready as a no-network registry and retention metadata layer for local sidecar warehouse review. It is not a warehouse writer, ingestion command, scheduler, report/browser integration, production runtime integration, or cleanup executor.

## What Changed

W2 added:

- `tools/indexer_warehouse_registry.py`
- `tests/test_indexer_warehouse_registry.py`
- W2 RFC docs/JSON
- compact registry JSON and registry docs
- retention/cleanup policy docs/JSON
- W2 decision docs/JSON
- future W3 analyst sidecar query packet

## Evidence

The W2 registry consumed the existing W1 compact summary and recorded:

- runs: 3
- active review candidates: 1
- retained references: 2
- cleanup candidates: 0
- blocked W0/W1 candidates: 0
- markets: 5
- public trade rows: 580
- cursor rows: 6
- malformed raw JSON rows: 0
- duplicate indicators: 0

The active review candidate is the per-target multi-target DB with 60/60/60 public trade coverage across the approved three-target set.

## Why The Gate Is Ready

The registry is useful without expanding runtime scope because W1 already performs the DB review. W2 only records compact metadata and retention recommendations from validated W1 summaries.

The tool fails closed on malformed summaries, marks raw DB references as local-only, records blocked runtime scopes, and performs no network calls, DB mutation, artifact deletion, saved-report mutation, schema migration, or production integration.

## Still Blocked

- Live/network ingestion.
- Warehouse writer or copy pipeline.
- Append-mode DB retention.
- Scheduler/background/daemon mode.
- Production scanner/archive/Event Forensic/browser/report imports.
- Report/browser integration.
- Production storage schema migration.
- Saved report mutation.
- Scoring/gate/funding/Phase 3 use.
- CLOB auth/private keys/trading/order placement.
- Push/PR.

## Next Recommended Campaign

Prepare W3 analyst sidecar query/read command. W3 should read compact registry/W1 summaries and answer analyst questions from local sidecar evidence only. It must not copy metrics into reports, change browser UI, affect scoring/gates, or become production runtime.
