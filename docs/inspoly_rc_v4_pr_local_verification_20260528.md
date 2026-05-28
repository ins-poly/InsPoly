# InsPoly RC V4 PR Local Verification - 2026-05-28

## Scope

This refresh validates PR #1 from local branch `codex/inspoly-local-release-candidate-v4` at commit `4cd7db9f8ebd49b5e7f5decf246637c5f7902ed2`.

Full unittest discovery was run because the PR differs from `origin/main` in runtime files.

## Results

| Check | Result |
| --- | --- |
| Branch/tracking | `codex/inspoly-local-release-candidate-v4` tracking `origin/codex/inspoly-local-release-candidate-v4` |
| Diff summary | 647 files, 162,489 insertions, 310 deletions |
| Changed JSON validation | 201 changed JSON files parsed |
| Compile check | `python3 -m compileall -q app tools tests` passed |
| Focused release suites | 391 tests passed |
| Full unittest discovery | 1240 tests passed |
| Runtime import scan | passed |
| Pointer copied-metric scan | passed |
| Forbidden local-only artifact scan | passed for `PROJECT_MEMORY.md`, `.inspoly_indexer/`, `shadow_review_packets/`, `side_outcome_review_packets/` |
| Staged-file scan | passed |
| `git diff --check` | passed |
| `git diff --cached --check` | passed |

## Notes

- GitHub reports no commit statuses and no Actions workflow runs for the head commit.
- Tests emitted existing sqlite `ResourceWarning` noise and the known validation-corpus terminal failure artifact message, but unittest discovery completed successfully with `OK`.
- `release_manifests/` appears in the PR diff from historical commits and should be reviewed as a packaging decision.

## Local Verification Decision

Local verification supports keeping PR #1 open as a Draft and proceeding to human review. It does not by itself authorize merge or ready-for-review transition.
