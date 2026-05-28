# InsPoly RC V4 GitHub Release Overview - 2026-05-28

## Executive Summary

Release Candidate V4 is a local-first review package for InsPoly. It consolidates the recent scanner/archive/Event Forensic compatibility work, the sidecar indexer warehouse evidence chain, and W4 pointer-only report metadata into a draft GitHub PR for review.

Publication status for this packet: draft PR packaging. This publication does not introduce new runtime behavior beyond the already committed RC V4 state.

## Reviewer Starting Points

Start with these files:

- `docs/inspoly_release_candidate_v4_state_20260527.md`
- `docs/inspoly_rc_v4_github_release_overview_20260528.md`
- `docs/inspoly_rc_v4_architecture_map_20260528.md`
- `docs/inspoly_rc_v4_data_flow_schemas_20260528.md`
- `docs/inspoly_rc_v4_validation_matrix_20260528.md`
- `docs/inspoly_rc_v4_reviewer_guide_20260528.md`
- `docs/inspoly_rc_v4_rollback_and_local_artifacts_20260528.md`

## Major Changes In RC V4

- Completed the bounded live sidecar indexer evidence chain through target hardening, scoped compare, per-target public trade collection, and warehouse W0-W4 readiness layers.
- Added W0 sidecar warehouse contracts and W1/W2/W3 no-network local review/query tools.
- Implemented W4 optional top-level `indexerWarehousePointer` metadata for newly generated reports when an explicit safe pointer payload is supplied.
- Kept W4 pointer metadata absent by default, advisory-only, sidecar-only, and without copied warehouse metrics.
- Consolidated remaining blockers into final local decisions so RC V4 is not blocked by Phase 3, pUSD runtime, pagination expansion, replay embedding, scheduler mode, browser pointer UI, or public exact-wallet labels.

## Explicit Non-Goals

RC V4 does not include:

- production warehouse daemon, scheduler, service mode, or automatic startup;
- copied warehouse metrics in reports;
- row-level sidecar context in reports;
- browser UI panel for warehouse pointer metadata;
- scoring, gate, label, HER, funding, candidate admission, or model behavior changes;
- Phase 3 capital-at-risk runtime;
- pUSD/CLOB funding runtime semantics;
- CLOB auth, private keys, trading, order placement, or external writes;
- saved report mutation;
- raw sidecar DB publication.

## Validation Summary

The prior RC V4 completion campaign recorded a passed full local validation matrix:

- full unittest discovery: 1240 tests passed;
- compile checks: `app`, `tools`, and `tests` passed;
- focused W4/report/browser compatibility tests passed;
- focused indexer warehouse W0/W1/W2/W3/W4 tests passed;
- cross-mode scoring and known-case benchmark tests passed;
- browser offline and label snapshot tests passed;
- runtime import scan passed;
- copied-metrics scan passed.

The GitHub publication campaign reruns the release validation matrix before pushing the release branch.

## Release Branch Strategy

Publication target:

- Branch: `codex/inspoly-local-release-candidate-v4`
- PR type: Draft
- Base: `origin/main`

The campaign must not push directly to `origin/main`.

## Current Gate

Local gate before publication: `local_release_candidate_v4_complete_no_push_pr`.

Expected publication gate after a successful draft PR: `local_release_candidate_v4_draft_pr_open`.
