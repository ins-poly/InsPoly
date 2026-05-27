# RFC: Indexer Warehouse W1 Manual Local Command - 2026-05-27

## Status

RFC status: `implemented_sidecar_read_only`.

Implementation scope: W1 manual local review command only.

This RFC does not approve live ingestion, warehouse data copying, append-mode warehouse storage, production runtime integration, report/browser integration, scheduling, storage migration, scoring/gate changes, funding changes, Phase 3 runtime, CLOB auth, private keys, trading, external writes, push, or PR.

## Command Purpose

W1 adds a manual command that summarizes an existing local indexer sidecar SQLite DB for warehouse review. It answers whether the DB is useful as local warehouse evidence and whether the next registry/retention stage is worth an approval packet.

It does not collect data. It does not create or mutate warehouse DBs.

## Command

Tool:

- `tools/indexer_warehouse_manual_command.py`

Inputs:

- `--db-path`: required existing local indexer sidecar SQLite DB.
- `--run-summary-json`: optional bounded-run summary JSON used only for collection metadata.
- `--output-json`: optional compact review output path.
- `--output-markdown`: optional human-readable review output path.

## Input DB Path Policy

The command expects an existing local SQLite sidecar DB. Missing DBs are blocked as `blocked_missing_db`. Remote/service paths are not useful for W1 and remain outside the local-only retention policy.

The command opens the DB in SQLite read-only mode and records whether the input DB modification time changed during review.

## Output Summary Policy

The command may write compact JSON and Markdown summaries. These are review artifacts, not saved reports and not production storage.

Raw `.inspoly_indexer/` DBs remain local-only by default and must not be committed unless separately approved.

## Config Validation

W1 does not execute live ingestion configs. Config validation remains owned by:

- `tools/indexer_bounded_live_config_validator.py`

Future W1+ live or writer work still needs separate approval and config validation before any network path.

## W0 Readiness Requirement

The W1 command reuses:

- `tools/indexer_sidecar_readiness_audit.py`
- `app/indexer/warehouse_contract.py`

It fails closed when W0 readiness is blocked by missing schema, missing cursor contract, cursor errors, malformed raw JSON, duplicate indicators, or unsafe local path policy.

Collection metadata is optional input from a bounded runner summary. If absent, W1 records `external_summary_required` and can still classify a DB as locally reviewable if the DB is otherwise W0-ready and has useful market/trade rows.

## No-Live / No-Network Guarantee

The command has no network flag and no provider client. It does not import or call the bounded live runner. It only reads local SQLite and optional local JSON.

## Read-Only Versus Output-Writing Boundary

Read-only:

- input DB;
- optional input run summary JSON;
- readiness audit;
- W0 contract classification;
- SQLite content summary.

Output-writing:

- compact W1 JSON summary;
- optional Markdown summary.

No saved reports or raw DBs are modified.

## Retention Summary

W1 summaries recommend:

- keep raw DBs local-only;
- commit only compact intentional review artifacts;
- delete the local sidecar output directory to rollback;
- define registry/retention policy in W2 before any append-mode or repeat-run retention behavior.

## Gate Classification

The command emits one of:

- `ready_for_local_warehouse_review`
- `blocked_missing_db`
- `blocked_w0_not_ready`
- `blocked_schema_or_cursor_risk`
- `blocked_empty_or_low_value_db`

The campaign-level final gate is separate and recorded in the W1 decision packet.

## Rollback

Rollback is local-only:

1. Stop running the W1 command.
2. Delete generated W1 compact summaries if desired.
3. Keep input sidecar DBs unchanged.
4. Revert the sidecar command/test changes if needed.

No production runtime or saved report rollback is required.

## Validation

Required validation:

- JSON validation for compact outputs;
- `py_compile` for W1 tool/tests and touched sidecar helpers;
- focused W1/W0/readiness/storage/compare/runner/config tests;
- runtime import scan;
- `git diff --check`;
- staged diff check before commit.

## Blocked Future Scopes

Still blocked after W1:

- live ingestion;
- scheduler/background/daemon mode;
- report/browser integration;
- production imports;
- production storage schema migration;
- warehouse service mode;
- saved report mutation;
- scoring/gate/funding/Phase 3 use;
- CLOB auth/private keys/trading/order placement/external writes.
