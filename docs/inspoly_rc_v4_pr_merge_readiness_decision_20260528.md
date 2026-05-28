# InsPoly RC V4 PR Merge-Readiness Decision - 2026-05-28

## Decision

Final gate: `rc_v4_pr_stay_draft_needs_ci_or_review`.

## Evidence

- PR #1 is open, Draft, and mergeable.
- Local verification passed:
  - 201 changed JSON files parsed;
  - compileall passed;
  - 391 focused release tests passed;
  - 1240 full unittest discovery tests passed;
  - runtime import scan passed;
  - pointer copied-metric scan passed;
  - local-only artifact scan passed for the main forbidden local buckets.
- GitHub reports no commit statuses and no Actions workflow runs.
- There are no PR comments, reviews, or review threads.
- The PR description would benefit from direct links to the 2026-05-28 reviewer docs, but the GitHub integration could not update the body due permission error.
- Historical `release_manifests/` files are present in the PR diff and should be accepted or cleaned up before the PR leaves Draft.

## Why Not Ready-For-Review Yet

This campaign is not authorized to mark the PR ready. Beyond that, the PR has no GitHub CI signal and no human review signal yet. The right state is a validated Draft with explicit review instructions.

## Why Not Merge-Ready Yet

Merge is not approved. Also, the large PR surface and historical packaging artifacts need owner/reviewer acceptance before merge readiness can be claimed.

## Next Owner Actions

1. Decide whether to manually update the PR description to link the reviewer docs.
2. Decide whether the historical `release_manifests/` files should stay in the PR.
3. Decide whether to configure or accept absent GitHub CI for this repository.
4. If satisfied, explicitly instruct marking the PR ready for review.
5. Treat merge as a separate explicit approval step after review.
