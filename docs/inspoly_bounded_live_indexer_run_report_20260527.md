# Bounded Live Indexer Run Report - 2026-05-27

## Gate Decision

Final gate: `bounded_live_indexer_success_needs_operator_hardening`.

One approved read-only sidecar run was executed for market slug `russia-x-ukraine-ceasefire-by-january-31-2026`. The run stayed within the approved bounds, produced a local-only sidecar DB, and passed the existing DB readiness audit. It is useful enough to justify a future repeat-run/hardening RFC, but not enough to approve scheduling, warehouse mode, production integration, report/UI wiring, or broader target expansion.

## Live Scope

- Target type: `marketSlugs`.
- Target slug: `russia-x-ukraine-ceasefire-by-january-31-2026`.
- Config path: `.inspoly_indexer/bounded_live_20260527/operator_config.json` local-only.
- DB path: `.inspoly_indexer/bounded_live_20260527/indexer.sqlite3` local-only.
- Raw runner summary: `.inspoly_indexer/bounded_live_20260527/raw_run_summary.json` local-only.
- DB audit JSON: `validation_outputs/inspoly_bounded_live_indexer_db_audit_20260527.json`.
- Bounds: max 1 market, max 2 Data API pages, max 500 stored rows, max 120 seconds.

## Run Result

- Config validation: `indexer_bounded_live_config_valid_for_operator_review`.
- Runner gate: `bounded_live_indexer_success_needs_operator_hardening`.
- DB readiness gate: `indexer_sidecar_readiness_ready_no_runtime`.
- Elapsed time: 7.632 seconds.
- Provider failures: 0.
- Provider warnings: orderbook snapshots skipped because no approved public orderbook endpoint contract is wired into the manual runner.
- Live network used: yes, public read-only Gamma/Data API calls only.
- External writes/auth/trading/private keys/order placement: none.
- Background worker/daemon/repeat loop: none.
- Production integration/report mutation/browser integration: none.

## Stored Evidence

The local sidecar DB contains:

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
- Malformed payload counts: 0 markets, 0 trades, 0 orderbooks.

## Readiness Audit

The readiness audit found:

- DB exists: true.
- Expected tables present: 6.
- Expected tables missing: 0.
- Cursor count: 2.
- Stale cursors: 0.
- Cursor errors: 0.
- Malformed raw JSON rows: 0.
- Duplicate indicators: 0.

Recommended next action from the audit remains operator-review-only use; live indexer production integration still requires a separate approval.

## Isolation And Rollback

Rollback is local-only: delete `.inspoly_indexer/bounded_live_20260527/`. No production rollback is needed because nothing consumes this DB. The DB and raw local summaries must not be committed by default; only this report, compact JSON, and the DB audit JSON are intended for commit.

## Future RFC Outline

Before any repeat run or warehouse work, a future RFC should define:

- whether the next run proves idempotence by rerunning the same slug into a fresh DB and comparing row/cursor behavior;
- whether to add a controlled orderbook endpoint contract to the sidecar runner;
- how to distinguish market-not-found, endpoint-blocked, and closed-market no-trade states in operator reports;
- whether a second target class should be allowed, and under which cap;
- why scanner/archive/Event Forensic/browser/report/storage integration remains blocked until explicit product approval.

## Validation Notes

Required validation for this campaign:

- JSON validation for the run report and DB audit JSON.
- Python compile for the bounded runner, validator, readiness audit, and focused tests.
- Focused indexer/sidecar tests.
- Runtime import scan proving no production path imports the sidecar runner, validator, or readiness audit.
- `git diff --check` and staged diff check before commit.
