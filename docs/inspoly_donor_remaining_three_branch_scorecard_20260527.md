# InsPoly Donor Remaining Three-Branch Scorecard

Date: 2026-05-27 EEST

Gate: `three_branch_scorecard_ready_no_runtime`

## Current Repository State

- Branch: `main`
- Head at campaign start: `df043e24a4ad5e349e450d893db95b195732da23`
- Ahead of `origin/main`: `50`
- Tracked/staged diff at campaign start: none
- Protected local-only buckets present:
  - `release_manifests/`
  - `shadow_review_packets/`
  - `side_outcome_review_packets/`
  - ignored/local-only `PROJECT_MEMORY.md`

This campaign does not authorize push, PR creation, remote git operations, production integration, Phase 3 capital runtime, storage migration, report/UI integration, live indexing, trading, CLOB auth, or saved artifact mutation.

## Branch Scorecard

Scores are process scores from `0` to `5`; they do not affect product scoring.

| Branch | Product leverage | Risk reduction | Evidence readiness | Reversibility | Dependency unblocking | Approval load | Tunnel-vision control | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| A: optional live indexer / warehouse | 5 | 4 | 4 | 5 | 5 | 2 | 4 | Run as audit plus RFC. Implement only read-only DB readiness audit. |
| B: sidecar context to analyst reports/UI | 4 | 4 | 4 | 5 | 4 | 2 | 5 | Run inventory plus RFC. Do not implement preview index because equivalent sidecar tools exist. |
| C: pUSD / CLOB collateral and Phase 3 evidence | 4 | 5 | 3 | 5 | 4 | 1 | 5 | Run gap audit plus research RFC. Add static unknown-safe semantics helper/tests only. |

## Current Gates

- Push/PR: `push_pr_dry_run_ready`, still user-gated.
- Indexer sidecar: local-only; live indexing/startup integration blocked.
- Shadow context sidecars: sidecar-only; report-copying, scoring, and UI integration blocked.
- Phase 3 capital runtime: `phase3_sidecar_only_final`, blocker `phase3_blocked_until_new_source_fields`.
- Pagination/provider expansion: RFC/operator-gated, no production runtime expansion.
- Replay persistence: `replay_keep_sidecar_only_final`, no report/storage/browser persistence.

## Execution Decision

Run all three branches because each can produce sidecar/RFC evidence without crossing an approval gate. Stop at runtime, storage, UI/report, live-service, funding-runtime, or remote-git boundaries.
