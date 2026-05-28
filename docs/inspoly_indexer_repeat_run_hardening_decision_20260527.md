# Indexer Repeat-Run Hardening Decision - 2026-05-27

## Final Gate

Final gate: `indexer_repeat_run_ready_for_operator_approval`.

The offline hardening campaign added a read-only sidecar DB compare tool, re-audited the first bounded live DB, and self-compared that DB without any new live/network request. The result is strong enough to make a second bounded same-slug probe operator-decision-ready, but it does not approve that run by itself.

## Evidence Reviewed

- Prior live probe report: `docs/inspoly_bounded_live_indexer_run_report_20260527.md`.
- Prior compact run JSON: `validation_outputs/inspoly_bounded_live_indexer_run_report_20260527.json`.
- Prior DB audit JSON: `validation_outputs/inspoly_bounded_live_indexer_db_audit_20260527.json`.
- Repeat-run RFC: `docs/inspoly_indexer_repeat_run_hardening_rfc_20260527.md`.
- Repeat-run compact RFC JSON: `validation_outputs/inspoly_indexer_repeat_run_hardening_rfc_20260527.json`.
- Existing DB re-audit: `validation_outputs/inspoly_indexer_repeat_run_existing_db_readiness_audit_20260527.json`.
- Existing DB self-compare: `validation_outputs/inspoly_indexer_repeat_run_existing_db_self_compare_20260527.json`.

## Offline Audit Result

The existing local sidecar DB at `.inspoly_indexer/bounded_live_20260527/indexer.sqlite3` was read without mutation.

- Readiness gate: `indexer_sidecar_readiness_ready_no_runtime`.
- Expected tables present: 6.
- Expected tables missing: 0.
- Cursor count: 2.
- Cursor errors: 0.
- Malformed raw JSON rows: 0.
- Duplicate indicators: 0.
- Table counts: 1 indexed market, 200 indexed trades, 2 cursors, 0 orderbook snapshots, 0 wallet snapshots, 0 score history rows.

## Self-Compare Result

The same DB was compared against itself in `self_compare` mode.

- Compare gate: `indexer_sidecar_compare_ready_for_repeat_run`.
- Table-count drift: 0.
- Cursor drift: 0.
- Market identity drift: 0.
- Trade identity drift: 0.
- Raw hash drift: 0.
- Storage risk count: 0.
- Provider drift count: 0.

## Decision

The next safe owner decision is whether to approve one second bounded same-slug live probe into a fresh local-only DB. That future run should use the same slug, the same narrow caps, and no daemon/scheduler/background worker. It should be followed immediately by the readiness audit and `fresh_live` DB comparison against the first DB.

This campaign did not run the second live probe.

## What Remains Blocked

- Warehouse mode.
- Production runtime integration.
- Scanner/archive/Event Forensic/browser/report imports.
- Report writer or browser UI changes.
- Storage schema migration.
- Target expansion beyond the approved slug.
- Background workers, scheduling, or repeat loops.
- CLOB auth, private keys, trading, order placement, or external writes.
- Phase 3 runtime.
- Push or PR.

## Next Operator Approval Packet

If the owner approves the second probe, use these conditions:

- exact target slug: `russia-x-ukraine-ceasefire-by-january-31-2026`;
- target type: market slug unless explicitly changed;
- output DB: a new local-only path under `.inspoly_indexer/`;
- caps: one target, max one market row unless target expansion is approved, max two public data pages, max 500 stored rows, max 120 seconds;
- compare mode after run: `fresh_live`;
- acceptance: matching market identity and cursor keys, no malformed JSON, no duplicate indicators, and public trade drift within `max(25 rows, 10%)`;
- stop: any provider contract failure, market identity mismatch, cursor key mismatch, storage schema need, or production import requirement.

## Strategic State Update

The strategic state should move the indexer branch from "needs hardening/repeat-run RFC" to "repeat run ready for explicit operator approval." Runtime and warehouse gates remain blocked.

## Validation Completed

- JSON validation passed for the repeat-run RFC JSON, existing-DB re-audit JSON, existing-DB self-compare JSON, and repeat-run decision JSON.
- Python compile passed for the new DB compare tool/test and existing bounded runner, config validator, and readiness audit files.
- Focused indexer/sidecar tests passed: 77 tests.
- Runtime import scan passed for the compare tool, bounded runner, config validator, and readiness audit against scanner/archive/Event Forensic/browser/storage production paths.
- `git diff --check` passed.
