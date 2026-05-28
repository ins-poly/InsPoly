# Indexer Target Provider Hardening - 2026-05-27

## Gate Context

Previous gate: `indexer_multitarget_probe_partial_success_needs_target_hardening`.

The first three-slug indexer run proved that the sidecar DB can store multiple targets safely, but it did not prove the target list is repeat-ready. Two requested slugs resolved and stored market rows. The third, `us-x-iran-permanent-peace-deal-by`, failed when used as a `marketSlugs` target.

## Failure Interpretation

The Iran slug should not be treated as a bad topic. Local Event Forensic evidence used it as an event-family target, and local performance docs record it as a larger event scope that can exceed narrow bounds. The failure is therefore most likely target-shape related:

- `market_vs_event_ambiguity`
- `target_exceeds_bounds_or_not_single_market`

Before reusing it, a bounded resolver preflight must prove a specific canonical market slug with exactly one market row, or a separate event/subset approval packet must define event-family handling.

## Taxonomy

| Class | Meaning | Repeat-run use |
| --- | --- | --- |
| `exact_slug_resolves_cleanly` | Requested slug resolves to one market row with condition ID and no alias ambiguity. | usable as repeat-run anchor |
| `provider_lookup_failed` | Provider returns no useful payload or fails before metadata. | not usable |
| `slug_redirects_or_aliases` | Requested slug resolves to a different canonical market slug. | usable only after alias is recorded |
| `market_vs_event_ambiguity` | Slug may refer to event family, selected market, or route page. | preflight or scope-control required |
| `no_public_trades` | Market resolves but capped public trade fetch returns zero rows. | scope-control only |
| `zero_row_sparse_control` | Intentional sparse target to prove zero-row handling. | scope-control only |
| `provider_api_transient_error` | Timeout/retryable provider failure. | retry only with operator approval |
| `target_exceeds_bounds` | Resolved target exceeds market/page/row/time caps. | not usable for bounded market run |
| `target_usable_as_repeat_run_anchor` | Prior sidecar rows and clean readiness evidence exist. | preferred repeat anchor |
| `target_usable_only_as_scope_control` | Safe metadata but weak/sparse evidence. | scope-control only |
| `target_not_usable` | Unresolved, too large, or needs broad discovery/event subset. | do not use |

## Metadata Required Before Live Run

Each live-run target should have: requested slug/type, resolved type, canonical market slug, condition ID, event slug, title/question, active/closed state, market count, alias/redirect flag, resolution source, classification, and operator-bound decision.

## Decision

Target hardening must run before another multi-target ingestion. Warehouse mode, runtime integration, report/browser wiring, storage schema changes, scoring/gate changes, CLOB auth/trading, and Phase 3 runtime remain blocked.
