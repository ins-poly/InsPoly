# Indexer Warehouse Evidence Consolidation - 2026-05-27

## Decision Context

Current gate: `indexer_collection_hardening_ready_for_warehouse_rfc_no_runtime`.

Warehouse recheck: `warehouse_rfc_ready_no_implementation`.

The indexer evidence chain now supports drafting a sidecar-only warehouse RFC. It does not support warehouse implementation, production runtime integration, report/browser wiring, storage schema migration, scheduling, or broader live collection without a separate approval campaign.

## Live Sidecar Runs

| Campaign | Target set | DB rows | Readiness | Compare / drift | Gate |
| --- | --- | ---: | --- | --- | --- |
| First one-target run | `russia-x-ukraine-ceasefire-by-january-31-2026` | 1 market, 200 trades, 2 cursors | `indexer_sidecar_readiness_ready_no_runtime` | Not yet repeated | `bounded_live_indexer_success_needs_operator_hardening` |
| Same-slug repeat | same Russia slug | 1 market, 200 trades, 2 cursors | `indexer_sidecar_readiness_ready_no_runtime` | zero table/cursor/market/trade/provider/storage drift | `indexer_repeat_probe_success_ready_for_small_multitarget_run` |
| First three-target probe | Russia, Maduro, failed Iran event-family slug | 2 markets, 200 trades, 2 cursors | `indexer_sidecar_readiness_ready_no_runtime` | scoped compare unavailable; one provider lookup failed | `indexer_multitarget_probe_partial_success_needs_target_hardening` |
| Target-hardened three-target run | Russia, Maduro, Khamenei | 3 markets, 200 trades, 2 cursors | `indexer_sidecar_readiness_ready_no_runtime` | provider/collection-sampling drift, storage risk 0 | `indexer_multitarget_hardening_ready_for_repeat_operator_run` |
| Repeat2 same three-target run | Russia, Maduro, Khamenei | 3 markets, 200 trades, 2 cursors | `indexer_sidecar_readiness_ready_no_runtime` | zero drift versus prior hardened DB, but all trades on Khamenei | `indexer_repeatability_needs_collection_hardening` |
| Per-target hardened run | Russia, Maduro, Khamenei | 3 markets, 180 trades, 2 cursors | `indexer_sidecar_readiness_ready_no_runtime` | storage risk 0; intended collection-policy drift | `indexer_collection_hardening_ready_for_warehouse_rfc_no_runtime` |

## Target Set Maturity

Current approved warehouse-RFC evidence set:

1. `russia-x-ukraine-ceasefire-by-january-31-2026`
2. `maduro-in-us-custody-by-january-31`
3. `khamenei-out-as-supreme-leader-of-iran-by-february-28`

The previous failed slug, `us-x-iran-permanent-peace-deal-by`, was not a safe bounded market target. Resolver preflight classified it as a larger event-family/bounds mismatch and selected Khamenei as the single-market replacement.

## Collection Evidence

Aggregate collection was repeatable but not representative: both aggregate three-target runs stored all public trades on the active Khamenei condition and zero on Russia/Maduro.

Per-target collection is representative enough for RFC design:

- collection policy: `per_target_public_trade_cap`;
- per-target cap: 60;
- aggregate public-trade limit after market rows: 180;
- rows by target: 60 / 60 / 60;
- filter mismatch rows: 0;
- missing-condition rows: 0;
- malformed raw JSON rows: 0;
- duplicate indicators: 0.

## Storage And Cursor Evidence

The existing sidecar SQLite schema has repeatedly stayed healthy:

- expected tables present: 6;
- missing tables: 0;
- malformed raw JSON: 0 in current committed audits;
- duplicate indicators: 0 in current committed audits;
- cursor error count: 0 in current committed audits.

The current runner still writes aggregate `markets` and `public_trades` cursors. Per-condition cursor identity remains an RFC design question, not an implemented fact.

## Scoped Compare Evidence

Scoped compare now separates storage identity risk from provider or collection-policy drift:

- same-slug repeat had zero drift;
- target-hardened repeat evidence had no storage identity drift;
- per-target hardening produced expected trade identity/row-count drift because the collection policy changed;
- latest scoped compare storage risk count: 0.

## Proven

- Manual bounded public-read sidecar runs can write local SQLite DBs safely.
- The current three-market target set resolves cleanly.
- The sidecar schema handles repeated market/trade/cursor writes without readiness failures.
- Scoped compare can detect storage drift and classify provider/collection drift.
- Per-target trade collection prevents silent starvation under the bounded cap.
- The sidecar path remains isolated from production runtime paths.

## Not Proven

- Warehouse retention/deletion policy.
- Per-condition cursor recovery and resume semantics.
- Local DB growth under longer repeated runs.
- Longer target registries beyond the three-target proof set.
- Scheduled/background mode safety.
- Report/browser analyst integration value.
- Production runtime value.

## Implementation Still Requires Separate Approval

The evidence supports an RFC and a future W0 implementation proposal only. It does not approve:

- warehouse implementation;
- storage schema migration;
- production scanner/archive/Event Forensic/browser/report integration;
- background workers or scheduling;
- saved report mutation;
- scoring/gate/funding/Phase 3 changes;
- auth/private-key/trading/external writes.
