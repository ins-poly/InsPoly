# Bounded Live Indexer Repeat Probe - 2026-05-27

## Final Gate

Final gate: `indexer_repeat_probe_success_ready_for_small_multitarget_run`.

One approved same-slug repeat probe was executed for market slug `russia-x-ukraine-ceasefire-by-january-31-2026`. The run wrote to a fresh local-only sidecar DB, passed readiness audit independently, and compared cleanly against the first DB.

This gate supports a future owner decision for a small bounded multi-target operator run. It does not approve warehouse mode, scheduling, production runtime integration, report/browser wiring, storage schema changes, target expansion without approval, CLOB auth, trading, push, or PR.

## Scope

- Target type: `marketSlugs`.
- Target slug: `russia-x-ukraine-ceasefire-by-january-31-2026`.
- First DB: `.inspoly_indexer/bounded_live_20260527/indexer.sqlite3` local-only.
- Repeat DB: `.inspoly_indexer/bounded_live_repeat_20260527/indexer.sqlite3` local-only.
- Repeat config: `.inspoly_indexer/bounded_live_repeat_20260527/operator_config.json` local-only.
- Repeat raw summary: `.inspoly_indexer/bounded_live_repeat_20260527/raw_run_summary.json` local-only.
- Bounds: max 1 market, max 2 public Data API pages, max 500 stored rows, max 120 seconds.

## Repeat Run Result

- Run completed: yes.
- Runner gate: `bounded_live_indexer_success_needs_operator_hardening`.
- Config validation: `indexer_bounded_live_config_valid_for_operator_review`.
- Live network used: yes, public read-only Gamma/Data API calls only.
- Elapsed time: 8.659 seconds.
- Provider failures: 0.
- Provider warnings: orderbook snapshots skipped because no approved public orderbook endpoint contract is wired into the manual runner.
- External writes/auth/private keys/trading/order placement: none.
- Background worker/daemon/repeat loop: none.
- Production integration/report mutation/browser integration: none.

## Stored Evidence

The repeat local sidecar DB contains:

- `indexed_markets`: 1 row.
- `indexed_trades`: 200 rows.
- `indexer_cursors`: 2 rows.
- `orderbook_snapshots`: 0 rows.
- `wallet_index_snapshots`: 0 rows.
- `score_history`: 0 rows.

Observed market row:

- Condition ID: `0xb8c1bd306a8a4cedfb280e114e655c5092b3f37edccae05cd877d7f21a5774ce`.
- Question: `Russia x Ukraine ceasefire by January 31, 2026?`
- Event slug: `russia-x-ukraine-ceasefire-by-january-31-2026`.
- Active: true.
- Closed: true.

Trade sample summary:

- Distinct wallets: 156.
- Distinct token IDs: 2.
- Timestamp range stored: `1769880358` to `1769929968`.
- Malformed payload counts from runner: 0 markets, 0 trades, 0 orderbooks.

## Readiness Audit

The repeat DB readiness audit found:

- DB exists: true.
- Expected tables present: 6.
- Expected tables missing: 0.
- Cursor count: 2.
- Stale cursors: 0.
- Cursor errors: 0.
- Malformed raw JSON rows: 0.
- Duplicate indicators: 0.
- Readiness gate: `indexer_sidecar_readiness_ready_no_runtime`.

## Fresh DB Compare

Comparison mode: `fresh_live`.

- Compare gate: `indexer_sidecar_compare_ready_for_repeat_run`.
- Table-count drift: 0.
- Cursor drift: 0.
- Market identity drift: 0.
- Trade identity drift: 0.
- Raw market/trade hash drift: 0.
- Provider drift count: 0.
- Storage risk count: 0.

Cursor raw hashes changed only because cursor row timestamps differ between the first and second DBs; cursor keys, values, statuses, and errors matched exactly.

## Decision

Same-slug repeat behavior is clean enough to justify a future small multi-target operator approval packet. The next step should still be explicit and bounded: a small target list, fresh local DB, no daemon/background worker, no warehouse mode, and immediate readiness/compare review.

Runtime integration remains blocked. This evidence should not be used by scanner/archive/Event Forensic/browser/report/storage runtime paths.

## Validation Notes

Completed validation for this campaign:

- JSON validation passed for repeat probe, repeat DB audit, fresh DB compare, and local-only run/config JSON.
- Python compile passed for sidecar runner, config validator, readiness audit, compare tool, and focused tests.
- Focused indexer/sidecar tests passed: 77 tests.
- Runtime import scan passed for scanner/archive/Event Forensic/browser/storage production paths.
- `git diff --check` passed.
