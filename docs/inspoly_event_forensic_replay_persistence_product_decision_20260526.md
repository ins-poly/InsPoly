# Event Forensic Replay Persistence Product Decision

Date: 2026-05-26

Primary gate: `replay_keep_sidecar_only_final`

Secondary gates:

- `replay_storage_persistence_blocked`
- `replay_browser_viewer_blocked_by_assets`

Runtime implementation: `false`

Storage schema migration: `false`

Report schema mutation: `false`

Browser embedding: `false`

Network/RPC used: `false`

## Decision

Keep Event Forensic replay persistence sidecar-only for the current product state.

Top-level report embedding remains a possible future RFC, but it is not approved for implementation. Storage-backed replay persistence and browser replay viewing remain blocked until separate product, storage, artifact-size, and browser/offline decisions are made.

## Current Replay Capability

Current helper:

- `app/event_forensic_replay.py`

Current safe behavior:

- builds deterministic sidecar snapshots from already-collected Event Forensic report data;
- does not run live/RPC collection;
- does not run Event Forensic analysis;
- does not mutate saved reports;
- does not write application storage;
- does not change candidate admission, scores, ranks, review buckets, weak-history demotion, exports, or browser UI.

Snapshots currently capture:

- analysis scope and legacy scope;
- selected event and market metadata;
- source report metadata;
- candidate identities and stable trade keys where report rows contain them;
- score values, review bucket, later-won, and winner-rank fields where present;
- winner resolution metadata;
- score-input settings;
- timing/performance fields;
- schema/version metadata;
- quality notes for old or incomplete reports.

Snapshots currently omit:

- fresh live/RPC reconstruction;
- fresh candidate admission;
- wallet context refetch;
- complete raw event trade history;
- complete all-candidate rows when reports only contain display/top-slice rows;
- storage-backed schedule state;
- browser replay view state;
- Phase 3 sidecar context;
- shadow context;
- provider pagination proof beyond the source report.

## Size And Stability Audit

Machine-readable size audit:

- `validation_outputs/event_forensic_replay_size_audit_20260526.json`

Audit scope:

- largest 30 local Event Forensic report-like JSON artifacts from saved report and validation-output locations;
- report files above 50 MB skipped by design;
- snapshot candidates sampled up to 250 rows per report for sizing;
- all-candidate snapshot size estimated from report summary candidate counts where available;
- no saved reports were modified.

Findings:

- Reports discovered: 30
- Reports audited: 29
- Reports skipped: 1
- Total audited report bytes: 203,513,768
- Estimated current report-row snapshot bytes: 2,536,254
- Max current report-row snapshot bytes: 214,046
- Median current report-row snapshot bytes: 55,695
- Max current report row count captured by snapshot: 208
- Max summary candidate trade count observed: 15,354
- Reports where snapshot rows are only a top slice of all candidate trades: 29
- Max estimated all-candidate snapshot bytes: 9,514,557
- High-risk all-candidate embedding reports: 10
- Medium-risk all-candidate embedding reports: 3
- Restricted-field reports: 0
- Old-report fallback reports: 27
- Old reports load absent-safe: true

Interpretation:

- Current sidecar snapshots from saved report rows are small and stable enough for local validation.
- Report embedding of the current top-slice snapshot would be technically manageable, but it would not mean all-candidate replay persistence.
- All-candidate embedding for high-density Event Forensic runs can approach 10 MB per report and needs an explicit artifact-size budget, retention policy, and browser UX decision.
- Old reports remain absent-safe, but many lack product-scope fields and complete candidate rows.

## Product Decision Matrix

| Option | Decision | Benefit | Risk | Required approval |
|---|---|---|---|---|
| A. Keep replay sidecar-only | current final path | Low-risk validation, no schema mutation, no UI/storage dependency | Analysts must know sidecar location; not a polished report view | none beyond current local use |
| B. Top-level report embedding later | future RFC only | Easier report traceability and bundle portability | Report grows; top-slice vs all-candidate semantics can confuse analysts | product approval, size budget, old-report tests |
| C. Storage-backed replay persistence later | blocked | Queryable replay history and scheduling state | storage schema, migration, cleanup, retention, compatibility risk | storage RFC and product approval |
| D. Browser replay viewer later | blocked | Analyst-friendly replay timeline | browser UI/product complexity; strict offline assets still blocked | browser/product approval and asset policy |

## Why Sidecar-Only Is Final For Now

Sidecar-only remains the safest current product decision because it preserves all established runtime behavior and avoids turning incomplete old report rows into a persistence contract.

The size audit shows that embedding current snapshot rows is small, but complete all-candidate replay persistence is materially larger for dense runs. That is a product decision, not a sidecar default.

## Future Top-Level Embedding Requirements

Before adding `replaySnapshot` or a similar field to normal report JSON:

- define whether the embedded snapshot contains top-slice report rows or all candidate rows;
- define a maximum embedded snapshot byte budget;
- label selected-market, subset, and whole-event scope clearly;
- keep old reports absent-safe;
- preserve pagination/truncation warnings;
- prove browser load time and report opening remain acceptable;
- add rollback logic for removing the field;
- run Event Forensic replay snapshot tests and browser report compatibility tests.

## Future Storage Persistence Requirements

Before storage-backed replay persistence:

- write a storage RFC;
- define schema, indexes, retention, cleanup, and migration;
- prove no report/schema ambiguity with sidecar snapshots;
- define whether replay stages are manual, scheduled, or operator-triggered;
- prove no private keys, CLOB auth, trading credentials, API keys, or mutable secrets are stored;
- keep live/RPC replay execution separately approved and bounded.

## Browser Viewer Blocker

Browser replay viewing is not product-ready because:

- replay snapshots are machine-readable sidecars today;
- browser strict offline assets are still product-gated;
- replay UI placement and labels need product design;
- report embedding semantics are not yet approved.

Browser replay viewing should wait until the browser offline asset policy and replay embedding policy are settled.

## What Analysts Can Use Now

Analysts can use replay snapshots as local sidecar evidence for:

- scope preservation;
- candidate ID and score/bucket preservation for report-contained rows;
- timing and quality-note inspection;
- future sidecar comparisons.

Analysts should not treat snapshots as:

- fresh analysis reruns;
- complete all-candidate persistence for top-slice reports;
- proof of full event completeness;
- storage-backed replay history;
- browser-ready replay timelines.

## Rollback

No runtime/schema change was made. Rollback is limited to removing:

- `tools/event_forensic_replay_size_audit.py`
- `tests/test_event_forensic_replay_size_audit.py`
- this report
- `validation_outputs/event_forensic_replay_size_audit_20260526.json`
- `validation_outputs/event_forensic_replay_persistence_product_decision_20260526.json`

## Final Gate

Primary gate: `replay_keep_sidecar_only_final`.

Next allowed action: continue using replay snapshots as local sidecars. If the owner wants report-embedded replay metadata, run a separate report-embedding RFC with explicit size budget and product approval. If the owner wants storage persistence, start a storage-schema RFC first.
