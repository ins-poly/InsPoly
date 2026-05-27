# Indexer Warehouse Reviewer Packet - 2026-05-27

## Current State

The optional indexer sidecar has moved from one-off probes to RFC readiness. The latest gate is `indexer_collection_hardening_ready_for_warehouse_rfc_no_runtime`; warehouse readiness is `warehouse_rfc_ready_no_implementation`.

No production runtime behavior has changed. The warehouse is not implemented.

## Evidence Snapshot

- First single-target run: 1 market, 200 trades, 2 cursors, clean readiness.
- Same-slug repeat: zero drift.
- First multi-target run: partial success; failed event-family slug identified.
- Target hardening: stable three-market set selected.
- Scoped compare: implemented and used.
- Repeat same three-target run: clean storage repeat, but aggregate collection starved two targets.
- Per-target collection hardening: 3 markets, 180 trades, 2 cursors, 60/60/60 rows by target, clean readiness, storage risk 0.

## Proposed RFC Decision

`indexer_warehouse_rfc_ready_for_future_w0_implementation`.

Meaning: future W0 can be approved as a no-runtime schema/readiness cleanup campaign. It does not mean warehouse write commands, scheduling, report/browser integration, or production imports are approved.

## Protected Invariants

- No scoring/gate/HER/funding/candidate/Phase 3 changes.
- No scanner/archive/Event Forensic/browser/report/storage production imports.
- No storage schema migration in this campaign.
- No saved report mutation.
- No background workers or daemons.
- No CLOB auth, private keys, trading, or order placement.
- Raw `.inspoly_indexer/` DBs remain local-only by default.
- No push or PR.

## Open Questions For Reviewer

1. Should W0 avoid schema changes entirely, or should it draft a sidecar schema version before W1?
2. Should per-condition cursor identity be a separate table or encoded as cursor keys?
3. What local retention cap is acceptable for raw sidecar DBs?
4. Should the first warehouse command append to one DB or continue fresh-run DBs?
5. Is sidecar packet generation useful before report pointer metadata?
6. What evidence threshold should precede any W4 report pointer work?
7. Should scheduled/background mode remain out of roadmap until after analyst packet value is proven?

## Reviewer Task

Check whether the RFC keeps the warehouse as a sidecar evidence system, whether W0 is narrow enough, and whether any proposed stage accidentally crosses production runtime, schema, report/browser, scoring, or operator gates.
