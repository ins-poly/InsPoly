# Indexer Repeat-Run Hardening RFC - 2026-05-27

## Decision Boundary

This RFC prepares the next operator decision after the first bounded live sidecar probe. It does not approve a second live run, warehouse mode, scheduling, background workers, production imports, report/browser integration, storage schema changes, CLOB auth, private keys, trading, or external writes.

Current prior gate: `bounded_live_indexer_success_needs_operator_hardening`.

Target proven once: `russia-x-ukraine-ceasefire-by-january-31-2026`.

Recommended next gate from this RFC: `indexer_repeat_run_ready_for_operator_approval`.

## What The First Probe Proved

- The manual sidecar runner can validate a bounded config before network access.
- One operator-approved market slug can be fetched with public read-only Gamma/Data API calls.
- The sidecar DB schema can store a narrow live market/trade slice without production consumers.
- The first DB contains 1 market row, 200 public trade rows, and 2 cursors.
- The DB readiness audit reports complete schema, no malformed raw JSON, no duplicate indicators, no cursor errors, and no stale cursors.

## What Remains Unproven

- Whether a fresh second DB for the same slug produces stable market identity and acceptable public trade drift.
- Whether an idempotent replay into the same DB leaves table counts, cursor values, trade IDs, and raw hashes unchanged.
- Whether cursor updates remain stable across repeated operator runs.
- Whether provider drift can be separated from suspicious storage drift.
- Whether orderbook snapshots should ever be added; no approved endpoint contract exists today.
- Whether any longer run is operationally worthwhile before warehouse-mode design.

## Required Repeat-Run Evidence

### Same-Slug Fresh DB Comparison

If the owner approves a second probe, it should use the same market slug and write to a new local-only DB path. The comparison should use the first DB as the baseline and the fresh DB as the candidate.

Required checks:

- exact market `condition_id`, `slug`, and `event_slug` match;
- cursor key set matches;
- expected schema remains complete;
- malformed raw JSON count remains zero;
- duplicate indicators remain zero;
- public trade row count drift is within tolerance;
- no production runtime path imports the runner or compare tool.

### Idempotent Replay Comparison

If an operator chooses to test replay into an existing DB, the replay comparison must be exact. The following must not change:

- table counts;
- cursor keys and cursor values;
- market IDs and slugs;
- trade stable IDs;
- raw payload hashes for common markets and trades.

Any exact replay drift is a storage-risk blocker, not provider drift.

### Cursor Stability

Cursor key mismatches are always storage risk. Cursor value drift in a fresh live comparison is provider/operator-review drift only when market identity is stable and trade drift stays within tolerance. Cursor errors or stale cursor acceptance require explicit operator notes before a longer run.

### Duplicate And Malformed JSON Policy

- Any malformed raw JSON in `indexed_markets`, `indexed_trades`, `orderbook_snapshots`, `wallet_index_snapshots`, or `score_history` blocks repeat-run approval.
- Any duplicate indicator from the readiness audit blocks warehouse/runtime work and requires operator inspection before further live runs.
- Exact replay duplicates are storage risk, even if they do not affect user-facing artifacts.

### Row-Count Drift Tolerance

For `fresh_live` comparison only, public trade row drift is acceptable when the magnitude is within:

`max(25 rows, 10% of baseline indexed_trades rows)`.

Drift inside that window is classified as provider drift and requires review before expansion. Drift outside that window is storage or provider-contract risk and blocks repeat-run expansion.

### Provider Drift Taxonomy

- `provider_drift_within_tolerance`: market identity and cursor keys match, but public trade rows or cursor values differ within tolerance.
- `provider_payload_drift`: common market/trade raw hashes changed while identity remained stable; review before using as warehouse evidence.
- `provider_contract_risk`: target missing, endpoint returns incompatible shapes, row drift exceeds tolerance, or orderbook behavior lacks a documented endpoint contract.
- `storage_risk`: missing schema, malformed JSON, duplicate indicators, exact replay drift, market identity mismatch, cursor key mismatch, or unreadable DB.

## Output Retention Policy

- Raw SQLite DBs under `.inspoly_indexer/` remain local-only by default.
- Raw runner summaries and operator configs remain local-only by default.
- Compact JSON reports under `validation_outputs/` may be committed when they avoid bulky payloads.
- Markdown decision/RFC docs may be committed.
- Deleting the sidecar output directory is sufficient rollback because no production path consumes the DB.

## Offline Tooling

This campaign adds `tools/indexer_sidecar_db_compare.py`.

The tool is:

- read-only;
- no-network;
- SQLite-only;
- deterministic;
- safe on missing or unreadable DBs;
- explicit about `self_compare`, `idempotent_replay`, and `fresh_live` modes;
- blocked from production runtime imports by validation scan.

The tool output uses:

- `reportType`: `indexer_sidecar_db_compare`;
- `schemaVersion`: `indexer_sidecar_db_compare_v1`;
- `readOnly`: true;
- `networkUsed`: false;
- `productionIntegration`: false.

## Future Repeat-Run Approval Conditions

A future second live probe may be approved only if all are true:

- the owner explicitly approves the second one-shot run;
- the target remains exactly `russia-x-ukraine-ceasefire-by-january-31-2026` unless a separate target-expansion approval exists;
- the run writes to a fresh local-only DB path;
- no daemon, scheduler, loop, or background worker is used;
- config caps remain narrow: one target, no wildcard discovery, strict page/row/time limits;
- the compare tool and readiness audit are run immediately after the probe;
- compact outputs are reviewed before any longer run.

## Warehouse And Runtime Block Conditions

Warehouse mode and production runtime remain blocked if any of the following are true:

- no second-run operator approval exists;
- market identity does not match across runs;
- cursor key sets differ;
- public trade drift exceeds tolerance;
- malformed raw JSON or duplicate indicators appear;
- the runner needs storage schema changes;
- any scanner/archive/Event Forensic/browser/report import is required;
- orderbook collection requires undocumented endpoint assumptions;
- the run requires auth, private keys, CLOB signing, order placement, or external writes.

## Current Offline Evidence

The existing local DB was re-audited and self-compared without network access:

- Readiness re-audit: `validation_outputs/inspoly_indexer_repeat_run_existing_db_readiness_audit_20260527.json`.
- Self-compare: `validation_outputs/inspoly_indexer_repeat_run_existing_db_self_compare_20260527.json`.
- Re-audit gate: `indexer_sidecar_readiness_ready_no_runtime`.
- Self-compare gate: `indexer_sidecar_compare_ready_for_repeat_run`.

The evidence supports operator approval for a second bounded same-slug probe only. It does not approve scheduling, warehouse mode, target expansion, report/browser integration, storage schema migration, or production runtime use.
