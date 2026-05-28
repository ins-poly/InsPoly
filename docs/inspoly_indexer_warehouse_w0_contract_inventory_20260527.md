# Indexer Warehouse W0 Contract Inventory - 2026-05-27

## Scope

Campaign classification: `approval_gated_proposal` plus W0 no-runtime implementation readiness.

W0 is allowed to harden sidecar schema/readiness contracts, fixtures, docs, validation helpers, and tests. W0 is not allowed to implement warehouse writes, live ingestion, production runtime integration, report/browser integration, scheduling, storage migration, scoring/gate/funding/Phase 3 changes, CLOB auth, private keys, trading, or external writes.

## Current Sidecar Model Contracts

`app/indexer/models.py` defines frozen dataclasses for:

- `IndexerCursor`
- `IndexedMarket`
- `IndexedTrade`
- `OrderbookSnapshot`
- `WalletIndexSnapshot`
- `ScoreHistoryEntry`

These are sidecar primitives. They do not define production scanner/archive/Event Forensic scoring or report contracts.

## Current Storage Tables

`app/indexer/storage.py` owns the local SQLite sidecar schema:

| Table | Current primary/key behavior | W0 contract status |
| --- | --- | --- |
| `indexer_cursors` | primary key `(source, cursor_key)` | Required for W0 readiness. Missing cursor rows make a DB sidecar-readable but not W0-ready. |
| `indexed_markets` | primary key `condition_id` | Required. Upsert preserves raw JSON as JSON object text. |
| `indexed_trades` | primary key `stable_trade_id` | Required. Duplicate trade replay is idempotent through upsert. |
| `orderbook_snapshots` | autoincrement `id`; replay updates same `(token_id, condition_id, timestamp)` | Required table even when empty. Current bounded runs skip orderbooks. |
| `wallet_index_snapshots` | primary key `wallet` | Required table even when empty. |
| `score_history` | append-only rows plus subject index | Required table even when empty. |

W0 does not introduce a schema migration or automatic upgrade command.

## Cursor Semantics

Current bounded runs write aggregate cursors:

- `markets`
- `public_trades`

This is enough for sidecar review and bounded run evidence. It is not a full warehouse resume contract. Per-condition public-trade cursor identity remains a W1/W2 design question and must not be inferred from current DBs.

W0 readiness now distinguishes:

- complete cursor rows;
- missing cursor rows;
- stale cursor warnings;
- cursor status/error blockers;
- aggregate public-trade cursor warning.

## Raw JSON Handling

Current storage writes JSON object text for market, trade, orderbook, wallet profile, and score metrics payloads. The readiness audit checks:

- `indexed_markets.raw_json`
- `indexed_trades.raw_json`
- `orderbook_snapshots.raw_json`
- `wallet_index_snapshots.raw_profile_json`
- `score_history.raw_metrics_json`

Malformed or non-object JSON blocks W0 readiness.

## Orderbook Snapshot Idempotence

`IndexerStorage.insert_orderbook_snapshot()` updates an existing row with the same `(token_id, condition_id, timestamp)` instead of duplicating it. W0 preserves this sidecar contract. Orderbook collection remains skipped by the bounded runner unless a future endpoint contract is approved.

## Readiness Audit Assumptions

`tools/indexer_sidecar_readiness_audit.py` is read-only against an existing SQLite DB and does not initialize missing DBs. Existing readiness gate meanings are preserved.

W0 adds a supplemental `warehouseW0` block plus compact summary fields:

- `warehouseW0Ready`
- `warehouseW0BlockingReasons`
- `tableContractStatus`
- `cursorContractStatus`
- `collectionMetadataStatus`
- `retentionPolicyStatus`

These fields are advisory W0 contract status and do not change production behavior.

## Scoped Compare Assumptions

`tools/indexer_sidecar_db_compare.py` remains the repeat-run drift tool. It can compare scoped market slugs or condition IDs and separates storage risk from provider/collection drift. W0 does not change compare behavior.

## Bounded Runner Output Assumptions

`tools/indexer_bounded_live_sidecar_run.py` already emits per-target public-trade collection metadata in run summaries:

- collection policy;
- per-target cap;
- aggregate cap;
- rows by target;
- per-condition stored rows;
- starvation warnings;
- cap exhaustion warnings;
- fetch details.

This metadata is not stored in the SQLite DB. W0 treats missing collection metadata in DB-only readiness as `external_summary_required`, not as a schema blocker.

## Local-Only Artifact Policy

Raw sidecar DBs remain local-only by default under `.inspoly_indexer/` or another operator-approved sidecar path. Compact docs/JSON may be committed intentionally. `PROJECT_MEMORY.md`, `.inspoly_indexer/`, release manifests, review packets, and bulky raw outputs remain unstaged unless separately approved.

## Already Sufficient For W0

- The sidecar schema is explicit and test-covered.
- Existing readiness audit is read-only.
- Existing scoped compare is read-only.
- Per-target collection metadata exists in run summaries.
- Old sidecar DBs remain readable without migration.
- Production runtime paths do not import sidecar warehouse contracts.

## Needs Contract Hardening

W0 added:

- `app/indexer/warehouse_contract.py` for pure W0 contract classification;
- readiness audit W0 summary fields;
- tests covering table, cursor, raw JSON, collection metadata, old DB compatibility, retention, and no-network/no-runtime behavior.

Remaining W1+ questions:

- whether per-condition cursors should be encoded in cursor keys or new sidecar metadata;
- whether append-mode retention is safe;
- how to cap local warehouse DB growth;
- whether analyst packets should remain sidecar-only or later use pointer metadata;
- how to validate old DB compatibility if a future sidecar schema version is introduced.
