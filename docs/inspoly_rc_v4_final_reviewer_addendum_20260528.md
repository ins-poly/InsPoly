# InsPoly RC V4 Final Reviewer Addendum - 2026-05-28

## Review State

PR: https://github.com/ins-poly/InsPoly/pull/1

Branch: `codex/inspoly-local-release-candidate-v4`

This addendum is the final reviewer entry point for RC V4. It supersedes the earlier draft-review ambiguity around reviewer links, no-CI handling, and historical `release_manifests/` packaging files.

## What Changed In This Finalization Pass

- Added direct reviewer-facing checklist docs.
- Removed tracked historical `release_manifests/` files from the PR branch while leaving local manifest files local-only.
- Kept GitHub CI deferred for this PR and documented the no-CI release policy.
- Prepared replacement PR body text with direct links to the reviewer docs.
- Attempted to update the PR body automatically, but local GitHub CLI support is unavailable and the GitHub integration cannot edit this PR. Manual owner PR-body update remains the only open publication polish item.
- Left the PR Draft; no ready-for-review transition and no merge were performed.

## Reviewer Starting Points

1. `docs/inspoly_rc_v4_github_release_overview_20260528.md`
2. `docs/inspoly_rc_v4_reviewer_guide_20260528.md`
3. `docs/inspoly_rc_v4_data_flow_schemas_20260528.md`
4. `docs/inspoly_rc_v4_validation_matrix_20260528.md`
5. `docs/inspoly_rc_v4_pr_local_verification_20260528.md`
6. `docs/inspoly_rc_v4_not_included_still_blocked_20260528.md`
7. `docs/inspoly_rc_v4_merge_checklist_20260528.md`

## Current Safe Interpretation

RC V4 is ready for owner-directed human review. It is not merged, not marked ready, and not a signal that blocked runtime work is approved.

## Remaining Human Decisions

- Whether to accept local validation plus no GitHub CI for this PR.
- Whether to paste the replacement PR body from `docs/inspoly_rc_v4_pr_body_replacement_20260528.md`.
- Whether to mark the Draft PR ready for review.
- Whether to merge after review.
