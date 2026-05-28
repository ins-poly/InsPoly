# InsPoly RC V4 Post-Merge Verification - 2026-05-28

## Summary

PR #1, `InsPoly local release candidate V4`, has been merged into `main`.

- PR: https://github.com/ins-poly/InsPoly/pull/1
- Merge commit: `ac1b29bd1b342e38f43323d3b5a61517bdd93ed0`
- PR head before merge: `7b220a594a840bc4a14532e61849372bde162129`
- Local branch after sync: `main`
- Local `main` and `origin/main`: both at `ac1b29bd1b342e38f43323d3b5a61517bdd93ed0`

Final gate: `rc_v4_merged_post_merge_verified`.

## What Was Verified

- GitHub reports PR #1 as closed and merged.
- `origin/main` contains the merge commit.
- Local `main` was fast-forwarded to `origin/main`.
- No merge conflict or history rewrite was required.
- Local-only artifacts remained untracked and were not staged.
- Runtime behavior was not changed by this post-merge verification pass.

## Validation

Post-merge validation on `main`:

- Tracked JSON validation: `208` files parsed successfully.
- `compileall` passed for `app`, `tools`, and `tests`.
- Full unittest discovery passed: `1240` tests.
- Runtime import/coupling scan passed.
- Copied warehouse metrics scan passed.
- Refined privacy/secret scan passed across `779` tracked text files.
- Local-only tracking scan passed.
- `release_manifests/` tracked file count is `0`.
- `git diff --check` passed before state updates.

The full suite still emits the existing sqlite `ResourceWarning` noise and a known validation-terminal artifact message, but no tests failed.

## Current Release State

RC V4 is now the repository `main` state.

Included high-level changes remain:

- Side/Outcome economic semantics.
- Event Forensic weak-history review demotion.
- Event Forensic selected-market vs whole-event scope metadata.
- Local browser offline boot assets.
- Expanded benchmark and validation corpus.
- Sidecar indexer/warehouse tooling.
- Optional report-level `indexerWarehousePointer` metadata.
- Strategic control documentation.

## Still Not Included

The merge does not authorize or add:

- trading or order placement;
- private-key or CLOB auth handling;
- Phase 3 capital runtime;
- scoring/gate/funding/HER/candidate-admission rewrites;
- production warehouse daemon, scheduler, or background worker;
- copied warehouse metrics in reports;
- browser UI panels for warehouse data;
- production storage schema migration.

## Local-Only Artifacts

The following remain local-only and were not staged by this verification pass:

- `PROJECT_MEMORY.md`
- `.inspoly_indexer/`
- untracked `release_manifests/`
- `shadow_review_packets/`
- `side_outcome_review_packets/`

## Recommended Next Step

Do not start another large feature campaign immediately from the old PR branch. Use `main` as the active branch.

Recommended next campaign choices:

1. Post-merge branch cleanup after confirming no rollback is needed.
2. A lightweight release tag / release-notes pass if the owner wants a formal GitHub release.
3. A separate strategic campaign only for a newly approved workstream, such as visible W4 UI, Phase 3 source-field research, pagination/provider work, or exact-wallet benchmark intake.
