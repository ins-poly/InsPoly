# InsPoly Strategic Long-Run Campaign Summary

- Date: 2026-05-22
- Scope: strategic local-only hardening after Side/Outcome reform
- Machine output: `validation_outputs/inspoly_strategic_long_run_campaign_summary_20260522.json`
- Runtime implementation: false
- Network/RPC used: false
- Staging/commit/push: false
- Final gate decision: `long_run_campaign_complete_with_live_rpc_blocker`

## Program Gates

| Program | Gate |
|---|---|
| Event Forensic saved-report reliability | `weak_history_needs_live_rpc_validation` |
| Operator-ready live/RPC plan | `live_rpc_plan_ready_not_executed` |
| Benchmark Suite V2 | `benchmark_suite_v2_ready` |
| Event-level semantics evidence | `event_level_semantics_needs_product_decision` |
| Archive visibility monitoring v2 | `archive_visibility_monitoring_v2_ready` |
| Browser label snapshot | `browser_label_contract_ok` |
| Phase 3 capital unblock requirements | `phase3_unblock_requirements_documented_keep_blocked` |

## Closed

- Saved-report Event Forensic weak-history contract audit is reproducible locally.
- Benchmark Suite V2 registry and runner are local-only and passing.
- Event-level semantics evidence has a concrete product-decision gate.
- Archive visibility monitoring v2 is local-only and annotate-not-hide.
- Browser label snapshot confirms raw token price and economic probability are not conflated in static copy.
- Phase 3 unblock requirements are explicit while runtime remains blocked.

## Still Blocked

- Bounded live/RPC Event Forensic weak-history near-certainty validation.
- Phase 3 capital-at-risk runtime implementation.
- Event-level runtime scope changes.
- Scoring weights/thresholds/direct gates/storage/UI sorting/live indexing.

## Requires Product/User Approval

- Event-level selected-market vs whole-event product semantics.
- UI scope/sort/filter behavior changes.
- Staging/commit policy for the broad local worktree.
- Whether generated evidence should be versioned.

## Bugs And Runtime Fixes

- Bugs found: none.
- Runtime fixes applied: none.

## Next Highest-Value Campaign

Run a bounded Event Forensic weak-history near-certainty validation with operator-approved saved/live inputs. Keep it measurement-only unless a separate narrow bug is proven and approved.

## 2026-05-24 Update

The approval-gated Event Forensic weak-history near-certainty line progressed beyond the original 2026-05-22 blocker:

- Bounded live/RPC validation was executed under explicit approval and remained measurement-only.
- Live validation reproduced the remembered blocker: 1 event, 1 market, 3,208 raw trade rows, 144 candidate rows, 4 weak-history near-certain later-win rows, and 3 high-rank rows.
- The live result showed reducers were present and Phase 2/Phase 4 semantics matched, so the issue was classified as model-policy ambiguity rather than a narrow runtime bug.
- A model-policy RFC and offline simulation were completed.
- Product approval selected `review_bucket_demotion`.
- Event Forensic review-bucket demotion was implemented for the approved pattern only.
- Post-implementation verification found 4 demoted rows, including the 3 reproduced high-rank rows, with 0 rows hidden or removed from export coverage.
- Full unittest after implementation passed: 936 tests OK.

Current gate for this line: `review_demotion_ready_for_commit_review`.

Remaining blockers:

- Phase 3 capital-at-risk remains blocked.
- Scorer tuning and scoring weight/threshold changes remain blocked.
- Direct Strong Risk/HER/funding/candidate-admission changes remain blocked.
- Event-level selected-market vs whole-event product semantics still require product/user approval.
- Live/RPC follow-up requires explicit approval.
- Commit/push/staging requires explicit approval.
