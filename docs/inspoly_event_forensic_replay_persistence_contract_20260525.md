# InsPoly Event Forensic Replay Persistence Contract

- Date: 2026-05-25
- Scope: replay snapshot sidecar contract
- Runtime implementation: `false`
- Storage schema migration: `false`
- Network/RPC used: `false`
- Gate decision: `replay_snapshot_sidecar_ready`

## Purpose

A replay snapshot is a stable, machine-readable sidecar payload that preserves enough already-collected Event Forensic context to compare future runs without rerunning live/RPC collection.

Snapshots are not a scoring engine, not a report replacement, and not a storage migration. They are a replay/audit substrate for local validation.

## Required Snapshot Fields

Each snapshot must include:

- `reportType`: `event_forensic_replay_snapshot`
- `schemaVersion`
- `generatedAt`
- `replayStage`: `initial`, `+1h`, `+4h`, `+24h`, or a documented custom stage
- `event`:
  - event slug
  - event id if available
  - event title
  - canonical URL
  - resolution status
  - outcome-context availability
- `market`:
  - selected condition id
  - selected market slug
  - selected market question/title
  - analysis-market count
  - total event-market count
- `scope`:
  - product analysis scope
  - legacy analysis scope
  - primary scoring scope
  - related-market context flag
  - sibling-markets-primary-scored flag
- `sourceReport`:
  - source report generated timestamp
  - analysis version
  - status
  - report JSON path if available
- `candidateCounts`:
  - raw trade count
  - candidate trade count
  - normal candidate trade count
  - candidate rows included in the snapshot
  - candidate trade set ids
- `candidates`:
  - candidate id
  - trade id / trade key if available
  - wallet
  - condition id
  - timestamp
  - market
  - raw side/outcome
  - economic side
  - Event Forensic score
  - existing model score
  - review bucket
  - later-won / winner-rank metadata if available
- `winnerResolutionMetadata`
- `scoreInputs`
- `timing`
- `versionMetadata`
- `qualityNotes`

## Forbidden Snapshot Fields

Snapshots must not store:

- private keys;
- CLOB auth credentials;
- API keys;
- bearer/access/refresh tokens;
- passwords;
- mnemonic phrases;
- mutable runtime credentials.

Market token identifiers and raw token outcome labels are allowed. They are market data, not authentication material.

## Replay Stages

The intended stages are:

- `initial`: source run at first saved report time;
- `+1h`: one-hour replay after initial candidate capture;
- `+4h`: four-hour replay;
- `+24h`: twenty-four-hour replay.

The snapshot helper supports stage labels without running those replays itself. A future runtime or operator flow may write staged snapshots only after separate approval.

## Backward Compatibility

Old reports may lack product-scope fields, timing fields, or full candidate rows. The helper must:

- infer selected-market vs whole-event from legacy `analysis_scope` when possible;
- mark missing candidate rows as `no_candidate_rows_available_in_source_report`;
- mark missing timings as `timing_fields_missing`;
- never mutate the old report;
- never synthesize scores or candidate admission fields.

## Storage Contract

This campaign does not authorize a storage schema migration.

Recommended future sidecar path:

- write snapshots as JSON artifacts next to report bundles or validation outputs;
- keep existing report JSON and CSV exports unchanged;
- add a storage-backed replay table only after a separate RFC, migration, and old-report compatibility tests.

## Rollback

Because the current implementation is sidecar-only:

- remove `app/event_forensic_replay.py`;
- remove `tests/test_event_forensic_replay_snapshot.py`;
- remove this contract and related inventory/decision docs.

No saved reports, storage schema, UI behavior, scoring behavior, or runtime paths require rollback.
