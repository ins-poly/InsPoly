# InsPoly RC V4 Post-Publication Checkpoint - 2026-05-28

## Summary

Release Candidate V4 has been published to GitHub as a draft pull request.

- Pull request: https://github.com/ins-poly/InsPoly/pull/1
- PR number: `#1`
- PR state at checkpoint: draft / not ready
- Branch: `codex/inspoly-local-release-candidate-v4`
- Base branch: `main`
- Latest pushed commit before this checkpoint: `7ac4dc6d0e3263e4a96c6872b6f454f32c295511`
- Publication gate: `local_release_candidate_v4_draft_pr_open`

The publication did not push to `origin/main`.

## What Was Published

The draft PR publishes the RC V4 branch and the RC V4 GitHub documentation packet:

- `docs/inspoly_rc_v4_github_release_overview_20260528.md`
- `docs/inspoly_rc_v4_architecture_map_20260528.md`
- `docs/inspoly_rc_v4_data_flow_schemas_20260528.md`
- `docs/inspoly_rc_v4_validation_matrix_20260528.md`
- `docs/inspoly_rc_v4_reviewer_guide_20260528.md`
- `docs/inspoly_rc_v4_rollback_and_local_artifacts_20260528.md`

The PR description summarizes the major RC V4 changes, validation, non-goals, local-only artifacts, and remaining approval gates.

## Current Review State

- GitHub shows the PR as draft.
- GitHub shows the PR can merge into `main` without conflicts at creation time.
- Reviewers, assignees, labels, projects, and milestone were not required for initial publication.
- No CI result was recorded in this checkpoint.

## Preserved Boundaries

The publication did not add new runtime behavior beyond the already committed RC V4 state.

Still not included:

- direct push to `origin/main`;
- trading, order placement, private keys, or CLOB auth;
- Phase 3 capital-at-risk runtime;
- production warehouse daemon, scheduler, or automatic startup;
- copied warehouse metrics in reports;
- browser UI panel for warehouse data;
- scoring, gate, funding, HER, or candidate-admission rewrite;
- saved-report mutation;
- raw sidecar DB publication.

## Local-Only Artifacts

These remain intentionally local-only and were not staged for the PR:

- `PROJECT_MEMORY.md`
- `.inspoly_indexer/`
- `release_manifests/`
- `shadow_review_packets/`
- `side_outcome_review_packets/`
- raw/bulky validation output directories

## Next Steps

The next highest-leverage step is PR review and CI/validation follow-up, not new feature work.

Recommended order:

1. Wait for GitHub checks or reviewer feedback.
2. If checks fail, fix only the failing scope on `codex/inspoly-local-release-candidate-v4`.
3. Keep the PR in draft until the owner decides it is ready for review.
4. Do not merge until the owner explicitly approves merge.
5. Do not start a new local feature campaign unless it is explicitly separated from RC V4 publication.

## Gate

`local_release_candidate_v4_draft_pr_open`
