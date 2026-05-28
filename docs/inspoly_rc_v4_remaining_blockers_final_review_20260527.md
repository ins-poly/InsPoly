# InsPoly RC V4 Remaining Blockers Final Review - 2026-05-27

## Purpose

RC V4 stops treating every remaining idea as an active local-completion task. The items below remain approval-gated or deferred unless the owner explicitly selects them after RC V4.

## Blocker Decisions

| Item | Current gate | Needed for RC V4 | Decision |
| --- | --- | --- | --- |
| Phase 3 capital-at-risk runtime | `phase3_runtime_blocked` | No | Defer. Requires stronger field evidence, old-report no-op proof, and formula/collateral decision. |
| pUSD/CLOB collateral tracing runtime | `pusd_collateral_fixture_grade_sources_added` | No | Defer. Static fixture-grade facts are useful, but runtime funding semantics remain blocked. |
| Production pagination expansion | `pagination_runtime_blocked_needs_micro_probe` | No | Defer. Needs selected target and bounded live/provider probe before changing production collection. |
| Replay persistence/report embedding | `replay_persistence_sidecar_only` | No | Defer. Needs size-budget and old-report compatibility RFC. |
| Report/browser UI panel for warehouse pointer | `indexer_w4_ui_panel_blocked_product_approval_required` | No | Defer. W4 is metadata-only; UI panel requires product approval. |
| Scheduler/background warehouse mode | `warehouse_scheduler_blocked` | No | Defer. Current warehouse chain remains manual/no-network for W1-W3 and explicit for pointer metadata. |
| Public exact-wallet benchmark labels | `public_exact_wallet_labels_blocked_no_fixture_grade_identity_bridge` | No | Defer. Requires accepted source-backed intake. |
| Push/PR/release publication | `push_pr_owner_gated` | No | Owner decision. RC V4 prepares checklist and draft, but performs no remote operation. |
| Root `AGENTS.md` tracking decision | `root_agents_tracking_unresolved` | No | Defer process decision. Do not stage root `AGENTS.md` without explicit approval. |
| Future browser build pipeline/runtime Babel replacement | `browser_build_pipeline_rfc_only` | No | Defer. Current offline browser path remains pinned UMD assets. |

## Active Backlog After RC V4

The active backlog should focus on owner decisions rather than another automatic local campaign:

1. Decide whether to push/open a draft PR from the local RC V4 state.
2. Decide whether W4 visible UI is product-worthy after metadata-only pointer use.
3. Decide whether Phase 3, pUSD, pagination, or replay deserve separate approval campaigns.

## Final Review Gate

Gate: `rc_v4_blockers_consolidated_push_pr_owner_gated`.

RC V4 does not require the blocked items above. They are deferred approval gates, not local release blockers.
