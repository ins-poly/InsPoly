# InsPoly Indexer Sidecar Current Capability Audit

Date: 2026-05-27 EEST

Gate: `indexer_live_operator_plan_ready_no_runtime`

## Current Capability

The current indexer package is a local-only sidecar under `app/indexer/`. It is not imported by scanner, archive, Event Forensic, browser, storage, or Polymarket runtime paths.

Already available:

- SQLite schema and storage for `indexer_cursors`, `indexed_markets`, `indexed_trades`, `orderbook_snapshots`, `wallet_index_snapshots`, and `score_history`.
- Cursor upsert and health assessment, including stale and error status detection.
- Gamma market, Data API trade, and orderbook snapshot normalizers that preserve raw payloads.
- Idempotent trade upsert by stable trade id.
- Idempotent orderbook replay for the same token, condition, and timestamp.
- Append-only score history with filtered latest reads.
- Analyst-only watchlist and advisory alert sidecar tables.
- Fixture-only dry run that loads local fixture JSON into a sidecar DB without network calls.

## Missing For Live Indexing

Still missing and not approved:

- No live network fetcher for Gamma/Data/CLOB.
- No background worker, scheduler, daemon, or automatic startup.
- No operator-bound runtime command for live ingestion.
- No freshness contract for warehouse reads.
- No retry/rate-limit policy for live provider behavior.
- No production fallback policy if the sidecar is absent, stale, corrupt, or partial.
- No report/UI integration and no scanner/archive/Event Forensic dependency.
- No Postgres, Redis, Graph Node, or durable warehouse backend.

## A3 Tool Decision

Implemented: `tools/indexer_sidecar_readiness_audit.py`.

Reason: existing fixture dry-run validates replay into a DB, but no existing tool directly inspects an already-existing sidecar DB for schema/table/cursor/raw-JSON/duplicate readiness. The new tool is read-only, local-only, no-network, and sidecar-only. It does not initialize missing DBs or import production runtime paths.

## Production Boundary

Production integration remains blocked. A sidecar DB becoming healthy must not make scanner, archive, Event Forensic, reports, browser UI, storage, scoring, routing, or candidate admission depend on it. Any live indexer or warehouse mode requires separate operator approval and a runtime RFC.

## Simulated Review

- Strategy: high leverage because it turns donor warehouse ideas into an operator decision without making a service required.
- Architecture: aligned with the existing SQLite sidecar package and avoids Postgres/Redis as required dependencies.
- Regression: low because the only code is a read-only tool and import-isolation tests.
- Validation: focused tests cover missing DB behavior, read-only behavior, malformed JSON, stale cursor detection, no-network behavior, and runtime import isolation.
