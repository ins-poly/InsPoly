# Indexer Warehouse W3 Analyst Query Decision - 2026-05-27

## Decision

Final W3 gate: `indexer_warehouse_w3_analyst_query_ready`.

W3 is ready as a no-network analyst query/read command over compact W2 registry metadata. It is not report/browser integration, not scoring, not live refresh, not raw DB mutation, and not warehouse ingestion.

## What Changed

W3 added:

- `tools/indexer_warehouse_query.py`
- `tests/test_indexer_warehouse_query.py`
- query fixtures under `tests/fixtures/indexer_warehouse_query/`
- W3 RFC docs/JSON
- W3 query run docs/JSON
- W3 decision docs/JSON
- future W4 report-pointer packet docs/JSON

## Evidence

The W3 query tool supports:

- `list-runs`
- `summarize-run`
- `aggregate`
- `target-coverage`
- `health`
- `retention-status`
- `blocked-scopes`

The committed query run against the current W2 registry returned:

- runs: 3
- active review candidates: 1
- retained references: 2
- markets: 5
- trades: 580
- cursors: 6
- malformed raw JSON: 0
- duplicate indicators: 0
- target coverage count: 3

## Why The Gate Is Ready

The tool answers analyst inventory questions from compact metadata that W2 already validated as local-only and commit-safe. It fails closed on malformed registry input, warns that output is sidecar-only/advisory/not scoring/not report-integrated, and does not touch raw DBs or production runtime paths.

## Still Blocked

- Live/network ingestion or refresh.
- Warehouse writer/copy pipeline.
- Raw DB mutation.
- Registry mutation.
- Saved report mutation.
- Scheduler/background/daemon mode.
- Production scanner/archive/Event Forensic/browser/report imports.
- Report/browser integration.
- Production storage schema migration.
- Scoring/gate/funding/Phase 3 use.
- CLOB auth/private keys/trading/order placement.
- Push/PR.

## Next Recommended Campaign

Prepare W4 report-pointer product decision only if the owner wants a report-level pointer to sidecar registry artifacts. W4 must be pointer-only, with no copied metrics, no UI panel, and no scoring/gate effect.
