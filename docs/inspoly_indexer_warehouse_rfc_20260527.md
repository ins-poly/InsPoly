# RFC: Optional Local Indexer Warehouse - 2026-05-27

## Status

RFC status: `ready_for_future_w0_review`.

Implementation status: not approved.

This RFC proposes a local sidecar warehouse path for indexer evidence. It does not change production runtime behavior and does not approve implementation in this campaign.

## Purpose

Create an optional local SQLite sidecar warehouse that can retain bounded public Polymarket market/trade evidence across approved manual runs, with clear health checks, scoped comparison, retention controls, and rollback.

The warehouse is an evidence and validation layer. It is not a replacement for scanner/archive/Event Forensic scoring.

## Non-Goals

- No production scoring replacement.
- No Strong Risk, HER, funding, candidate-admission, or label changes.
- No report writer or browser UI integration by default.
- No copied sidecar metrics into saved reports.
- No live background worker, scheduler, daemon, or automatic startup by default.
- No CLOB auth, private keys, signatures, trading, or order placement.
- No Phase 3 capital runtime.
- No Postgres, Redis, Graph Node, hosted service, or required network service.

## Storage Boundary

The first implementation should remain local SQLite sidecar-first:

- default root: `.inspoly_indexer/warehouse_*` or another operator-approved local sidecar path;
- raw DBs remain local-only by default;
- compact summaries and RFC evidence may be committed when intentionally staged;
- production `.inspoly*` scanner/archive/Event Forensic storage remains untouched.

No production storage schema migration is allowed by this RFC.

## Schema Ownership

The current sidecar schema lives in `app/indexer/storage.py` and includes:

- `indexer_cursors`
- `indexed_markets`
- `indexed_trades`
- `orderbook_snapshots`
- `wallet_index_snapshots`
- `score_history`

W0 should not require a schema migration. It may add read-only schema/readiness reports and migration design notes. If W1 or later needs new run-metadata or per-condition cursor tables, that must be proposed as a sidecar-only schema version with:

- old sidecar DB read compatibility;
- explicit migration/no-migration choice;
- fallback read-only behavior for older DBs;
- readiness audit updates;
- focused storage tests.

## Ingestion Model

Initial ingestion remains manual and bounded:

- explicit target registry or exact slug set;
- no wildcard discovery;
- config validation before any live network call;
- public read-only Gamma/Data API calls only;
- per-target public-trade caps for multi-target runs;
- aggregate `maxRows`, `maxPages`, `maxMarkets`, and `timeoutSeconds` as hard guards;
- fresh local output path unless a future stage explicitly approves append mode;
- no daemon, scheduler, or repeat loop.

The existing manual runner proves the collection shape, but a warehouse command should be reviewed separately before implementation.

## Freshness And Retention

The RFC recommends operator-controlled local retention:

- raw DBs are local-only by default;
- each run writes a compact summary with target set, caps, row counts, warnings, and readiness gate;
- retention policy should define max kept run DBs, max local bytes, and manual deletion guidance;
- rollback is deletion of the local sidecar output directory;
- no saved reports are mutated.

## Idempotence And Replay

Warehouse review must preserve these policies:

- duplicate market rows are keyed by `condition_id`;
- duplicate trades are keyed by `stable_trade_id`;
- malformed raw JSON blocks readiness;
- duplicate indicators block or warn according to readiness audit severity;
- scoped DB compare is required after repeat runs;
- fresh live row-count drift is classified separately from storage identity drift.

Cursor policy remains open for implementation design. Current bounded runs use aggregate `markets` and `public_trades` cursors. Warehouse-grade recovery likely needs per-condition public-trade cursor identity, but that is not implemented here.

## Analyst Use

Allowed analyst use in the first warehouse design:

- sidecar-only review packets;
- DB readiness summaries;
- scoped compare outputs;
- target registry evidence;
- collection-quality summaries.

Not allowed without future product approval:

- report writer changes;
- browser panels;
- report sorting/filtering changes;
- copied sidecar metrics in saved reports;
- production scoring or routing use.

Future pointer-only report metadata can be considered separately under the existing sidecar report-pointer gate.

## Security

The warehouse must remain public-read-only:

- no private keys;
- no CLOB auth credentials;
- no user sockets;
- no trading or order placement;
- no external writes;
- no hosted service dependency.

Config validation must reject auth/trading fields before any live network path.

## Observability

Every warehouse-related run should produce:

- config validation report;
- run summary;
- rows by target and condition;
- collection policy and cap metadata;
- provider warnings and failure classification;
- DB readiness audit;
- scoped DB compare for repeat evidence;
- explicit gate decision.

## Rollback

Rollback is local-only:

1. Stop using the warehouse command.
2. Delete the local sidecar warehouse DB/output directory.
3. Keep production scanner/archive/Event Forensic/browser storage untouched.
4. Revert docs/tools changes if needed.

No production report, saved artifact, or runtime storage rollback should be required.

## Operator Gates

Approval is required before:

- first W0 implementation;
- any warehouse write command;
- repeated live runs beyond approved bounds;
- append-mode retention;
- scheduled/background mode;
- report/browser integration;
- production imports;
- schema migration;
- target expansion beyond an approved registry;
- any auth/trading/private-key behavior.

## Recommended RFC Decision

`indexer_warehouse_rfc_ready_for_future_w0_implementation`.

The next safe campaign is W0 only: no-runtime warehouse schema/readiness cleanup and implementation design hardening. It should not run live ingestion or implement warehouse writes unless separately approved.
