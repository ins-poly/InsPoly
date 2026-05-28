# InsPoly RC V4 No-CI Release Policy - 2026-05-28

## Decision

Do not add GitHub CI in this finalization campaign.

## Rationale

This repository has no configured GitHub Actions workflow for PR #1. Adding CI now would be a repository automation change during a publication-readiness pass. The local validation matrix is already extensive, and this campaign is not authorized to add new automation, background behavior, runtime behavior, or product features.

## Local Validation Used Instead

- Full unittest discovery: 1240 tests passed in the PR-readiness refresh.
- Compile checks passed for `app`, `tools`, and `tests`.
- Focused release suites passed in the PR-readiness refresh.
- JSON validation passed for changed compact JSON.
- Runtime import scan passed.
- Copied warehouse metrics scan passed.
- Privacy/secret scan passed after local path redaction.
- Diff hygiene checks passed.

## Reviewer Guidance

The absence of GitHub CI should be treated as an explicit owner decision point before marking the PR ready or merging. If the owner wants CI before review, add it in a separate automation campaign rather than inside this finalization patch. If the owner accepts local validation for this repo, no CI change is needed before marking the PR ready.

## Gate Effect

No-CI policy does not authorize merge by itself. Merge remains a separate owner approval after review.
