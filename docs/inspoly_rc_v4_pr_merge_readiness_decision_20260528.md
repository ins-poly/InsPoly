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
- Historical tracked `release_manifests/` files were cleaned from the PR branch in the finalization pass; local manifest files remain ignored/local-only.
- Privacy/secret scan found no private-key blocks or common hosted-service tokens. Committed local machine path strings were redacted to neutral placeholders, and the follow-up scan reported 0 blocking findings.
- Automated PR body update is blocked in this environment because the GitHub CLI is unavailable and the GitHub integration returns `403`; replacement text is committed for manual owner update.

## Why Not Ready-For-Review Yet

This campaign is not authorized to mark the PR ready. The remaining non-code decisions are owner-level: accept no GitHub CI for this PR, paste the replacement PR body if desired, and explicitly mark ready for review.

## Why Not Merge-Ready Yet

Merge is not approved. Also, the large PR surface and historical packaging artifacts need owner/reviewer acceptance before merge readiness can be claimed.

## Next Owner Actions

1. Decide whether to manually update the PR description from `docs/inspoly_rc_v4_pr_body_replacement_20260528.md`.
2. Decide whether to configure or accept absent GitHub CI for this repository.
3. If satisfied, explicitly mark the Draft PR ready for review.
4. Treat merge as a separate explicit approval step after review.
