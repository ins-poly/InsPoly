# Indexer W4 Pointer Metadata Implementation Packet - 2026-05-27

## Status

Packet status: `superseded_by_rc_v4_implementation`.

Implementation status: implemented in RC V4 as optional, pointer-only report metadata with no UI panel and no copied metrics.

## Future Campaign Objective

Add one optional top-level pointer object to newly generated reports so analysts can find related sidecar warehouse registry/query artifacts. The implementation must not copy metrics, add UI panels, or affect scoring/gates.

## Likely Files Touched If Approved Later

- `app/scanner.py`
- `app/archive_scanner.py`
- `app/event_forensic.py`
- `tests/test_app_workflow_contracts.py`
- `tests/test_event_forensic_scope_semantics.py` or a new pointer-specific report compatibility test
- `tests/fixtures/indexer_w4_report_pointer_example.json`

Browser files should not be edited unless product separately approves visible pointer UI. If browser files are touched, the future campaign must prove no sorting/filtering/label behavior changes.

## Required Implementation Constraints

- Write only one top-level `indexerWarehousePointer` object.
- Emit it only when a caller supplies an explicit approved pointer payload.
- Keep reports without the pointer valid.
- Keep old saved reports unmodified.
- Do not import `tools/indexer_warehouse_query.py` or other sidecar tooling into scanner/archive/Event Forensic/browser runtime.
- Do not read raw sidecar DBs from report writers.
- Do not copy warehouse metrics, target rows, health counts, or row-level context into reports.

## Required Tests

- Old scanner/archive reports without pointer load normally.
- Old Event Forensic reports without pointer load normally.
- New reports can persist the pointer when explicitly supplied.
- Pointer fields remain metadata-only with `metricsCopied=false`, `scoringEffect=false`, and `routingEffect=false`.
- Browser payloads do not expose pointer counts as review metrics.
- Runtime import scan proves no sidecar warehouse query/registry/manual command imports in scanner/archive/Event Forensic/browser/storage paths.

## Rollback

Rollback should remove pointer emission and related tests. It must not mutate historical saved reports or sidecar artifacts.

## Stop Conditions

Stop the future implementation if it requires copied metrics, row-level sidecar context, report/browser UI panels, scoring/gate changes, storage migration, raw DB reads, live refresh, production imports of sidecar tools, saved report mutation, scheduler/background work, CLOB auth/private keys/trading, push, or PR.

## Future Approval Gate

Recommended future implementation gate:

- `indexer_w4_pointer_metadata_ready_for_implementation`

This packet does not grant that approval.
