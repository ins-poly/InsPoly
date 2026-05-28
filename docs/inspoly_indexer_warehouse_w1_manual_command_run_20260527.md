# Indexer Warehouse W1 Manual Command Run - 2026-05-27

## Scope

Command: `tools/indexer_warehouse_manual_command.py`

This run used only existing local sidecar DBs and local raw run summaries. No live/network call was made. No DB was mutated. No saved report was mutated. No production runtime path was integrated.

## Selected Local DBs

| Label | DB | Gate | Markets | Trades | Cursors | Collection metadata |
| --- | --- | --- | ---: | ---: | ---: | --- |
| First one-target run | `.inspoly_indexer/bounded_live_20260527/indexer.sqlite3` | `ready_for_local_warehouse_review` | 1 | 200 | 2 | `external_summary_required` |
| Same-slug repeat | `.inspoly_indexer/bounded_live_repeat_20260527/indexer.sqlite3` | `ready_for_local_warehouse_review` | 1 | 200 | 2 | `external_summary_required` |
| Per-target multi-target | `.inspoly_indexer/bounded_live_multitarget_per_target_20260527/indexer.sqlite3` | `ready_for_local_warehouse_review` | 3 | 180 | 2 | `per_target_metadata_ready` |

Aggregate reviewed rows:

- DBs reviewed: 3
- DBs ready for local warehouse review: 3
- Markets: 5
- Trades: 580
- Cursors: 6
- Malformed raw JSON: 0
- Duplicate indicators: 0

## Per-Target Coverage Evidence

The per-target hardened DB retained the current strongest warehouse-review evidence:

- `russia-x-ukraine-ceasefire-by-january-31-2026`: 60 public trade rows
- `maduro-in-us-custody-by-january-31`: 60 public trade rows
- `khamenei-out-as-supreme-leader-of-iran-by-february-28`: 60 public trade rows

The older first and same-slug DBs are still locally reviewable, but their older summaries do not provide per-target collection metadata and are classified as `external_summary_required`.

## W1 Findings

- W1 command can summarize useful local sidecar DBs without touching live providers.
- W0 readiness is sufficient for all selected local DBs.
- The command records stale cursor warnings because these historical DBs are not fresh live state; that is expected for local warehouse review and does not imply production readiness.
- The current sidecar cursor model remains aggregate: `markets` and `public_trades`.
- W2 must define registry/retention policy before append mode or repeat-run retention.

## Boundaries Preserved

- No live ingestion.
- No network.
- No input DB mutation.
- No saved report mutation.
- No warehouse writer/copy command.
- No scheduler/background/daemon mode.
- No scanner/archive/Event Forensic/browser/report integration.
- No storage schema migration.
- No scoring/gate/funding/Phase 3 changes.
- No CLOB auth/private keys/trading/order placement.
- No push/PR.

## Local-Only Policy

Raw `.inspoly_indexer/` DBs and raw summaries remain local-only and were not staged. The committed artifacts should remain compact W1 review docs/JSON only.
