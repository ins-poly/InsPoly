# Indexer Warehouse W0 Readiness - 2026-05-27

## Decision

Final W0 gate: `indexer_warehouse_w0_ready_for_w1_manual_command_rfc`.

W0 is implemented as no-runtime contract hardening only. It does not implement warehouse mode, live ingestion, a warehouse writer command, a scheduler, report/browser integration, production storage migration, scoring/gate changes, funding changes, Phase 3 runtime, CLOB auth, private keys, trading, or external writes.

## What Changed

W0 added a pure sidecar contract helper:

- `app/indexer/warehouse_contract.py`

It classifies:

- expected sidecar table contract;
- cursor contract;
- malformed raw JSON policy;
- duplicate indicator policy;
- per-target collection metadata status;
- old DB compatibility;
- local-only retention/output path policy;
- no-runtime/no-network boundary metadata.

W0 also extended the read-only readiness audit:

- `tools/indexer_sidecar_readiness_audit.py`

Existing readiness fields and gates are preserved. The audit now adds a supplemental `warehouseW0` block and compact summary fields:

- `warehouseW0Ready`
- `warehouseW0BlockingReasons`
- `tableContractStatus`
- `cursorContractStatus`
- `collectionMetadataStatus`
- `retentionPolicyStatus`

## Runtime Boundary

Runtime behavior changed: no.

The helper is pure and performs no network calls. The readiness audit remains read-only against an existing SQLite DB and still does not initialize or mutate missing DBs.

No scanner/archive/Event Forensic/browser/report path imports the W0 helper or sidecar tools.

## Old Sidecar DB Compatibility

Old sidecar DBs remain readable. W0 does not require migration.

DB-only readiness cannot prove per-target public-trade collection metadata because that metadata currently lives in bounded runner summaries, not in SQLite. W0 intentionally reports this as `external_summary_required` rather than forcing a schema migration.

This means an old DB can be:

- sidecar-readable;
- W0-ready for table/cursor/raw JSON/retention contracts;
- limited for collection-policy proof unless paired with the run summary.

## W1 Approval Impact

W1 manual local warehouse command is now safer to review because:

- expected tables are centralized in a pure helper;
- readiness audits report W0 contract fields explicitly;
- missing cursor rows are distinguishable from generic DB readiness;
- malformed raw JSON and duplicate indicators are W0 blockers;
- collection metadata is explicitly required from run summaries;
- local-only retention paths are classified;
- no-runtime boundaries are test-covered.

W1 is not approved by this campaign. The next campaign should still be an RFC/approval packet for the exact manual command behavior before implementation.

## Fixtures And Legacy Compatibility

No real `.inspoly_indexer/` DBs were copied into tests.

Focused tests generate temporary DBs and synthetic metadata for:

- complete table contract;
- missing table classification;
- missing cursor classification;
- cursor error classification;
- malformed raw JSON classification;
- missing per-target collection metadata;
- per-target collection metadata;
- old DB compatibility;
- local-only retention policy;
- no-network/no-runtime behavior.

## Tests Proving W0 Boundaries

Focused tests added or updated:

- `tests/test_indexer_warehouse_contract.py`
- `tests/test_indexer_sidecar_readiness_audit.py`

Required validation for this campaign includes:

- JSON validation for new compact outputs;
- `py_compile` for changed Python helper/tool/tests;
- focused warehouse/readiness/indexer tests;
- runtime import scan;
- `git diff --check`;
- staged diff check before commit.

## Still Blocked

- Warehouse writer command.
- Live ingestion.
- Scheduled/background/daemon operation.
- Append-mode warehouse retention.
- Production scanner/archive/Event Forensic/browser/report integration.
- Storage schema migration.
- Report pointer/panel work.
- Scoring/gate/funding/Phase 3 changes.
- Saved report mutation.
- CLOB auth/private keys/trading/order placement.
- Push/PR.

## Next Recommended Campaign

Prepare a future W1 manual local warehouse command RFC/approval packet. That packet should define the command shape, input registry, config validation, output path, no-production-import scan, retention and rollback, and exact stop conditions before any command implementation.
