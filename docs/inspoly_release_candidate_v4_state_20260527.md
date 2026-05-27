# InsPoly Release Candidate V4 State - 2026-05-27

## Status

Local RC V4 gate: `local_release_candidate_v4_complete_no_push_pr`.

Current campaign started from `564eea4c556bfe0127138f47575fbcb2375d7072` on `main`, ahead of `origin/main` by 66 commits. After the RC V4 commit, the expected local ahead count is 67. No push or PR is part of this campaign.

## Major Local Changes Since RC V3

- Completed bounded indexer sidecar live-run evidence chain.
- Added warehouse W0 readiness contracts.
- Added W1 manual no-network local DB review command.
- Added W2 registry/retention manifest tooling.
- Added W3 no-network analyst sidecar query command.
- Implemented W4 optional pointer-only report metadata for new reports when explicitly supplied.
- Preserved sidecar-only boundaries for warehouse data and raw local DBs.

## W4 Status

Gate: `indexer_w4_pointer_metadata_implemented_no_ui_no_metrics`.

W4 now supports one optional top-level `indexerWarehousePointer` object. It is absent by default, advisory-only, sidecar-only, and rejects copied metrics, row-level data, scoring/gate effects, UI requirements, live refresh, and raw DB requirements.

## Indexer Warehouse Chain

| Stage | Status |
| --- | --- |
| W0 contracts | Ready |
| W1 manual local command | Ready |
| W2 registry/retention | Ready |
| W3 analyst sidecar query | Ready |
| W4 report pointer metadata | Implemented pointer-only; no UI/no metrics |

Current W3 evidence remains: 3 local DB references, 1 active review candidate, 2 retained references, 5 markets, 580 trades, 6 cursors, 0 malformed raw JSON, and 0 duplicate indicators.

## Other Product Areas

- Side/outcome: completed through prior local reform and review packets; raw review artifacts remain local-only.
- Event Forensic: selected-market scope, weak-history demotion, replay sidecar, and performance evidence remain intact; no Phase 3 runtime changes in RC V4.
- Browser offline: strict offline browser assets remain the active release path; no UI panel added for W4.
- Known-case benchmark: 30 compact cases remain available; public exact-wallet labels remain blocked pending accepted intake.

## Remaining Blockers

The remaining blockers are deferred approval gates, not RC V4 local blockers:

- Phase 3 capital-at-risk runtime.
- pUSD/CLOB collateral tracing runtime.
- Production pagination expansion.
- Replay persistence/report embedding.
- Warehouse pointer UI panel.
- Scheduler/background warehouse mode.
- Public exact-wallet benchmark labels.
- Push/PR publication.
- Root `AGENTS.md` tracking decision.
- Future browser build pipeline/runtime Babel replacement.

## Local-Only Artifacts

Keep local-only and unstaged:

- `.inspoly_indexer/`
- `PROJECT_MEMORY.md`
- `release_manifests/`
- `shadow_review_packets/`
- `side_outcome_review_packets/`
- raw DBs and bulky generated evidence

## Validation Matrix

Final validation is recorded in `validation_outputs/inspoly_release_candidate_v4_state_20260527.json`. Completed categories:

- JSON validation passed for new/changed compact outputs and the W4 fixture.
- Python compile checks passed for changed report pointer/report writer/test files, and full `compileall` passed for `app`, `tools`, and `tests`.
- Focused W4/report/browser compatibility tests passed.
- Focused indexer warehouse W0/W1/W2/W3/W4 tests passed.
- Cross-mode scoring and known-case benchmark tests passed.
- Browser offline and label snapshot tests passed.
- Full unittest discovery passed: 1240 tests.
- Runtime import scan found no live indexer/warehouse tool imports in scanner/archive/Event Forensic/browser/storage paths.
- Copied-metrics scan found metric-like pointer fields only in rejection tests/forbidden-list definitions.
- `git diff --check` and `git diff --cached --check` are required before commit and recorded in the final response.
