# Event Forensic Replay Persistence RFC

Date: 2026-05-26

Status: RFC only

Runtime implementation: `false`

Storage schema migration: `false`

Gate: `replay_persistence_rfc_ready_no_runtime`

## Decision

Keep replay persistence sidecar-only for now.

The existing replay snapshot helper is safe for local analyst validation because it builds deterministic JSON from already-collected Event Forensic report data. It does not fetch live data, run Event Forensic analysis, mutate reports, change scores, write storage, or start a scheduler. It is ready for local replay packet preparation and future comparison harnesses.

Embedding replay persistence into reports or storage is not ready without a product/storage RFC and explicit approval.

## Current Safe Surface

Current safe components:

- `app/event_forensic_replay.py`
  - builds `event_forensic_replay_snapshot` payloads from saved reports;
  - preserves selected-market vs whole-event scope;
  - preserves candidate IDs, score values, review buckets, winner metadata, timing fields, and source-report metadata where present;
  - detects restricted secret-like key paths;
  - handles old reports with missing scope, timing, or candidate rows by adding quality notes.
- `tools/event_forensic_replay_schedule_runner.py`
  - creates planned-only stages: `initial`, `+1h`, `+4h`, `+24h`;
  - records optional bounded timing budget metadata;
  - does not run background jobs, live/RPC calls, or storage writes.

Safe use now:

- generate local replay snapshots from saved reports;
- generate local schedule plans from those snapshots;
- compare snapshots in future sidecar validation;
- keep outputs under validation/report sidecar directories.

## What Replay Captures

Snapshots capture:

- event slug, title, resolution status, and outcome-context availability;
- selected market condition/slug/question;
- product scope and legacy scope;
- related-market and sibling-market scope flags;
- source report status/version/path metadata;
- candidate row IDs and stable trade keys where available;
- wallet, condition, timestamp, raw side/outcome, economic side, scores, review buckets, later-won, and winner-rank fields;
- winner resolution metadata;
- score-input settings;
- timing fields;
- schema/version metadata;
- quality notes.

## What Replay Omits

Snapshots do not provide:

- a full scoring engine;
- fresh candidate admission;
- live/RPC recollection;
- wallet context refetch;
- complete raw event trade history when the source report was truncated;
- storage-backed scheduled replay state;
- proof that old reports are complete.

These omissions are intentional. They keep replay sidecar-safe and prevent old reports from being silently upgraded.

## Analyst Readability

Replay snapshots are primarily machine-readable today. They are useful to technical analysts and future validation tools, but they are not yet a polished analyst-facing report format.

Before embedding replay results in report UI or Markdown, a future product pass should decide:

- where replay-stage labels appear;
- how to explain selected-market vs whole-event replay scope;
- how to show incomplete/truncated source reports;
- how to distinguish replay metadata from fresh analysis;
- whether replay snapshots should be downloadable from the browser UI.

## Persistence Options

| Option | Status | Benefit | Risk | Approval needed |
|---|---|---|---|---|
| Keep sidecar-only JSON snapshots | approved current path | Low-risk local validation and future comparisons | Analysts must know where sidecar files live | No new approval |
| Embed replay metadata in report JSON | future RFC | Easier analyst/report traceability | Report schema grows; old-report compatibility must be tested | Product approval |
| Write snapshots next to report bundles | future RFC | Local persistence without app DB migration | Artifact size and retention policy need definition | Product/operator approval |
| Add storage-backed replay table | blocked | Queryable replay history | Storage schema migration and old-report compatibility risk | Storage RFC and approval |
| Automatic +1h/+4h/+24h scheduler | blocked | Full replay workflow | Background jobs, live/RPC, timing, and cost risk | Operator/product approval |

## Required Guardrails Before Persistence

Any future replay persistence implementation must prove:

1. No candidate admission, score, rank, review bucket, weak-history demotion, or export drift.
2. Old reports without replay fields still load unchanged.
3. Storage schema changes, if any, have a migration and rollback plan.
4. Replay scope labels do not imply whole-event completeness for selected-market or subset runs.
5. Truncation/pagination warnings remain visible.
6. No secrets, private keys, CLOB auth, trading credentials, or order placement can enter snapshots.
7. Replay scheduling is opt-in and bounded.

## Current Gate

Gate: `replay_persistence_rfc_ready_no_runtime`.

Recommended next action: keep using sidecar snapshots locally. Create a separate storage/report-embedding RFC only if analysts need replay stages visible inside normal report bundles.
