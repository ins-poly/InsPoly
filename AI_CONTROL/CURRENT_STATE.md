# Current State

Last updated: 2026-05-27 EEST.

## Repository State
- Branch inspected: `main`.
- Latest release-candidate commit verified: `ad27400 Verify local release candidate state`.
- Latest pre-push dry-run commit inspected: `05d688d Add final pre-push packaging dry run`.
- Latest runtime-affecting commit inspected: `0ce05da Add local browser offline runtime assets`.
- Current release-candidate gate: `local_release_candidate_verified`.
- Full verification matrix at `ad27400`: focused matrix 660 tests OK, full unittest discovery 1105 tests OK.
- Untracked local artifacts were present before this AI_CONTROL work:
  - `release_manifests/*`
  - `shadow_review_packets/*`
  - `side_outcome_review_packets/*`
- These local artifacts were not modified by this setup task.
- Pre-existing process-control state before consolidation:
  - `.gitignore` modified to make AI_CONTROL visible.
  - `AI_CONTROL/` untracked.
  - `skills/strategic-autonomy-review/` untracked.
  - root `AGENTS.md` ignored/local-only.
  - root `PROJECT_MEMORY.md` ignored/local-only.

## What Works
- Recent Scanner, Archive Researcher, and Event Forensic Analyzer have active browser/CLI paths.
- Browser UIs now boot from vendored local React/ReactDOM/Babel assets through narrow static serving.
- Strategic Operating System files are present and wired into repo/global agent guidance for non-trivial work.
- The `strategic-autonomy-review` skill exists in `skills/strategic-autonomy-review/` and `/Users/Root1/.codex/skills/strategic-autonomy-review/`.
- The test suite has broad local regression coverage compared with early project state; the latest full suite after public-case benchmark labeling passed 1112 tests.
- The known-case benchmark has been expanded to `known_case_benchmark_v3` with 30 compact cases, including false-positive, sidecar-context, and public-source metadata controls.
- Public-case evidence bridge tooling now enforces exact-wallet source discipline: 6 public controls remain non-exact, with 0 exact-wallet-supported public cases, 0 named-user local wallet candidates, 2 named-user-only, 2 pattern-level-only, and 2 market-level-only cases.
- Event Forensic selected-market vs whole-event semantics are explicitly modeled.
- Weak-history near-certainty rows are demoted out of primary Event Forensic review buckets while remaining exported/reviewable.
- Side/Outcome reform Phase 2/4 is stable according to local benchmark/drift audits.

## What Is Partially Solved
- Event Forensic performance improved, but large whole-event runs still depend on wallet-context loading and trade collection costs.
- Replay persistence exists as sidecar tooling, not productized report/storage/browser persistence.
- Phase 3 capital-at-risk has sidecar/source-quality evidence, but runtime implementation remains blocked.
- Funding traces can work with cache/RPC settings, but unavailable traces must remain `unknown`.
- Pagination/truncation has probes and RFCs, but production pagination expansion remains blocked.

## What Is Open
- Push/PR/release grouping requires explicit operator decision.
- Whether to include root `AGENTS.md` in a future public repo package remains an explicit user decision; for now it remains local-only.
- Future strategic cycles must use ORIENT -> SELECT -> PLAN -> EXECUTE -> VALIDATE -> RECORD and score candidate campaigns before implementation.
- Known-case benchmark coverage now includes local false-positive controls and six public-source metadata controls. Exact-wallet public-case labels remain at `0`; the 2026-05-27 evidence bridge records compact local refs where available, but none prove wallet identity.
- Archive/event pagination completeness needs provider/query proof before runtime changes.
- Further Event Forensic performance work needs measured bottleneck evidence before patches.
- Replay report embedding or storage persistence needs a separate RFC.
- Phase 3 capital-at-risk runtime needs stronger real source-field evidence and explicit product/accounting decisions.

## Validation Baseline
- Use `python3 -m unittest discover -s tests -p 'test_*.py'` for full regression coverage.
- Use `python3 -m py_compile app/*.py tools/*.py tests/*.py` for syntax checks.
- Use targeted audit tools when touching the related area, especially archive visibility, browser offline assets, Event Forensic scope/demotion/performance, side/outcome, funding quality, and replay.
- For strategic/process-only markdown changes, `git diff --check` is the minimum validation; runtime tests are not required unless app behavior changes.
