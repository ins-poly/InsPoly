# Indexer Warehouse W1 Manual Command Decision - 2026-05-27

## Decision

Final gate: `indexer_warehouse_w1_manual_command_ready`.

W1 is ready as a manual local read-only command for existing sidecar DB review. It is not a live ingestion command, not a warehouse writer, and not production runtime integration.

## Evidence

W1 added:

- `tools/indexer_warehouse_manual_command.py`
- `tests/test_indexer_warehouse_manual_command.py`
- W1 command RFC and compact JSON
- W1 local run summary docs/JSON

The command:

- opens the input SQLite DB read-only;
- runs existing readiness and W0 contract checks;
- optionally uses a local bounded-run summary JSON for collection metadata;
- summarizes tables, markets, trades, cursors, malformed raw JSON, duplicate indicators, retention policy, blocked runtime scopes, and next allowed action;
- writes compact review JSON and optional Markdown outputs;
- never calls network;
- never mutates the input DB or saved reports;
- never starts background work.

## Local DB Review Result

Selected existing DBs reviewed:

1. `.inspoly_indexer/bounded_live_20260527/indexer.sqlite3`
2. `.inspoly_indexer/bounded_live_repeat_20260527/indexer.sqlite3`
3. `.inspoly_indexer/bounded_live_multitarget_per_target_20260527/indexer.sqlite3`

All three returned `ready_for_local_warehouse_review`.

Aggregate reviewed evidence:

- DBs reviewed: 3
- Markets: 5
- Public trade rows: 580
- Cursor rows: 6
- Malformed raw JSON rows: 0
- Duplicate indicators: 0
- W0-ready DBs: 3

The strongest current warehouse-review DB remains the per-target hardened multi-target DB, which records 60/60/60 public trade rows across the approved three-target set.

## Why The Gate Is Ready

W1 reduces the next-stage risk because there is now a repeatable local command that turns sidecar DBs into compact review artifacts without creating an ingestion/write path.

The command makes these risks explicit:

- missing DB;
- W0 readiness blockers;
- schema/cursor/raw JSON/duplicate risk;
- empty or low-value DBs;
- missing per-target collection metadata;
- local-only retention boundaries;
- blocked runtime scopes.

## Still Blocked

- Live/network ingestion.
- Warehouse writer/copy command.
- Append-mode retention.
- Scheduler/background/daemon mode.
- Production scanner/archive/Event Forensic/browser/report imports.
- Report/browser integration.
- Production storage schema migration.
- Saved report mutation.
- Scoring/gate/funding/Phase 3 use.
- CLOB auth/private keys/trading/order placement.
- Push/PR.

## Next Recommended Campaign

Prepare W2 registry and retention. W2 should remain no scheduler/background mode. It should define:

- approved target registry format;
- retained local DB inventory format;
- local deletion/retention policy;
- maximum raw DB count and byte warnings;
- summary manifest shape;
- rollback rules;
- whether repeat-run retention is worth a future approval.

Do not implement scheduled collection or report/browser integration in W2.
