# Bounded Live Indexer Multi-Target Probe - 2026-05-27

## Final Gate

Final gate: `indexer_multitarget_probe_partial_success_needs_target_hardening`.

One approved bounded multi-target sidecar run was executed for exactly three market slugs. The run wrote to a fresh local-only sidecar DB, used public read-only provider calls only, and passed DB readiness for the rows that were stored. Two approved targets completed; one approved target failed provider lookup.

This gate supports a future target-hardening decision before another multi-target run. It does not approve repeat loops, background workers, warehouse mode, production runtime integration, report/browser wiring, storage schema changes, target expansion beyond approved caps, CLOB auth, trading, push, or PR.

## Scope

- Target type: `marketSlugs`.
- Approved target slugs:
  - `russia-x-ukraine-ceasefire-by-january-31-2026`
  - `maduro-in-us-custody-by-january-31`
  - `us-x-iran-permanent-peace-deal-by`
- Output DB: `.inspoly_indexer/bounded_live_multitarget_20260527/indexer.sqlite3` local-only.
- Config: `.inspoly_indexer/bounded_live_multitarget_20260527/operator_config.json` local-only.
- Raw summary: `.inspoly_indexer/bounded_live_multitarget_20260527/raw_run_summary.json` local-only.
- Bounds: max 3 markets, max 2 public Data API pages, max 500 stored rows, max 120 seconds.

## Run Result

- Run completed: partial.
- Runner gate: `bounded_live_indexer_success_needs_operator_hardening`.
- Config validation: `indexer_bounded_live_config_valid_for_operator_review`.
- Live network used: yes, public read-only Gamma/Data API calls only.
- Elapsed time: 1.101 seconds.
- Targets attempted: 3.
- Targets completed: 2.
- Targets failed: 1.
- Targets skipped: 0.
- External writes/auth/private keys/trading/order placement: none.
- Background worker/daemon/repeat loop: none.
- Production integration/report mutation/browser integration: none.

## Target Outcomes

| Target slug | Status | Market rows | Trade rows | Notes |
| --- | --- | ---: | ---: | --- |
| `russia-x-ukraine-ceasefire-by-january-31-2026` | completed | 1 | 200 | Condition ID `0xb8c1bd306a8a4cedfb280e114e655c5092b3f37edccae05cd877d7f21a5774ce`. |
| `maduro-in-us-custody-by-january-31` | completed | 1 | 0 | Condition ID `0xbfa45527ec959aacc36f7c312bd4f328171a7681ef1aeb3a7e34db5fb47d3f1d`; no public trade rows returned inside the capped fetch window. |
| `us-x-iran-permanent-peace-deal-by` | failed | 0 | 0 | Provider lookup returned not found or failed for the approved slug. |

## Stored Evidence

The multi-target local sidecar DB contains:

- `indexed_markets`: 2 rows.
- `indexed_trades`: 200 rows.
- `indexer_cursors`: 2 rows.
- `orderbook_snapshots`: 0 rows.
- `wallet_index_snapshots`: 0 rows.
- `score_history`: 0 rows.

Observed market rows:

- `russia-x-ukraine-ceasefire-by-january-31-2026`: `Russia x Ukraine ceasefire by January 31, 2026?`, active true, closed true.
- `maduro-in-us-custody-by-january-31`: `Maduro in U.S. custody by January 31?`, active true, closed true.

Trade sample summary:

- Distinct wallets: 156.
- Distinct token IDs: 2.
- Timestamp range stored: `1769880358` to `1769929968`.
- Malformed payload counts from runner: 0 markets, 0 trades, 0 orderbooks.

## Readiness Audit

The multi-target DB readiness audit found:

- DB exists: true.
- Expected tables present: 6.
- Expected tables missing: 0.
- Cursor count: 2.
- Stale cursors: 0.
- Cursor errors: 0.
- Malformed raw JSON rows: 0.
- Duplicate indicators: 0.
- Readiness gate: `indexer_sidecar_readiness_ready_no_runtime`.

## Compare And Drift Review

Scoped comparison is not supported by the current read-only DB compare tool. The single-slug repeat DB and this multi-target DB should not be compared as full DBs because the target sets intentionally differ.

- Scoped compare supported: false.
- Compare JSON produced: false.
- Follow-up: add scoped sidecar DB comparison before using overlapping-slug identity/drift claims as repeat-run evidence for multi-target runs.
- Storage/cursor drift observed from readiness audit: none.
- Provider drift observed: one approved target failed provider lookup; one completed target produced no trades under the capped public-trades fetch window.

## Decision

The sidecar storage path remained safe, but the approved target list was not clean enough to promote directly to repeat multi-target approval. The next campaign should harden target selection and provider lookup behavior before another multi-target live probe.

Runtime, warehouse, report, browser, storage schema, scoring, gate, funding, CLOB, and Phase 3 integration remain blocked.

## Validation Notes

Completed validation for this campaign:

- JSON validation passed for the multi-target probe report, DB audit, local-only config, config validation, and raw run summary.
- Python compile passed for the sidecar runner, config validator, readiness audit, DB compare tool, and focused tests.
- Focused indexer/sidecar tests passed: 79 tests.
- Runtime import scan passed for scanner/archive/Event Forensic/browser/storage production paths.
