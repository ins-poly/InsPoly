# InsPoly RC V4 Post-Merge Smoke Checklist - 2026-05-28

Run this only after an explicitly approved merge.

## Local Smoke

- Start the scanner browser flow.
- Start the archive researcher browser flow.
- Start the Event Forensic browser flow.
- Confirm browser assets load from local vendored files.
- Open at least one old saved report if local artifacts exist.
- Generate a small new report only if live/network use is separately acceptable for that smoke pass.

## Static Smoke

- Re-run full unittest discovery.
- Re-run browser vendor hash validation.
- Re-run runtime import scan.
- Re-run copied warehouse metrics scan.
- Confirm `indexerWarehousePointer` is absent by default in normal new reports unless an explicit pointer payload is supplied.

## Artifact Smoke

- Confirm local-only buckets are still ignored.
- Confirm no `.inspoly_indexer/` DBs or raw run outputs became tracked.
- Confirm no saved reports were mutated by merge.

## Blocked After Merge

Even after merge, the following remain blocked until separate approval:

- Phase 3 capital runtime.
- pUSD/CLOB funding runtime.
- Warehouse scheduler/background mode.
- Live indexer production integration.
- Warehouse/browser UI panels.
- Copied warehouse metrics.
- Storage schema migration.
- Trading, private keys, order placement, or CLOB auth.
