# InsPoly RC V4 PR Local Verification - 2026-05-28

## Scope

This refresh validates PR #1 from local branch `codex/inspoly-local-release-candidate-v4`. The original full-suite PR-readiness checkpoint was `40ebba2e61bbc83b0b15f8fc0fc0830a39df39b0`; this follow-up pass adds a docs/compact-output privacy hygiene patch only.

Full unittest discovery was run because the PR differs from `origin/main` in runtime files.

## Results

| Check | Result |
| --- | --- |
| Branch/tracking | `codex/inspoly-local-release-candidate-v4` tracking `origin/codex/inspoly-local-release-candidate-v4` |
| Diff summary | 655 files, 162,807 insertions, 310 deletions at inspected PR head |
| Changed JSON validation | 205 changed JSON files parsed after local-path redaction |
| Compile check | `python3 -m compileall -q app tools tests` passed |
| Focused release suites | 391 tests passed |
| Full unittest discovery | 1240 tests passed |
| Runtime import scan | passed |
| Pointer copied-metric scan | passed |
| Privacy/secret scan | passed after redacting committed `<local-user-home>` path strings; 0 blocking findings |
| Forbidden local-only artifact scan | passed for `PROJECT_MEMORY.md`, `.inspoly_indexer/`, `shadow_review_packets/`, `side_outcome_review_packets/` |
| Staged-file scan | passed |
| `git diff --check` | passed |
| `git diff --cached --check` | passed |

## Notes

- GitHub reports no commit statuses and no Actions workflow runs for the head commit.
- Tests emitted existing sqlite `ResourceWarning` noise and the known validation-corpus terminal failure artifact message, but unittest discovery completed successfully with `OK`.
- `release_manifests/` appears in the PR diff from historical commits and should be reviewed as a packaging decision.
- The privacy/secret scan found no private-key blocks or common hosted-service tokens. It did find local machine path strings in committed docs/JSON artifacts; this patch redacts those strings to `<repo>` / `<local-user-home>` placeholders.

## Local Verification Decision

Local verification supports keeping PR #1 open as a Draft and proceeding to human review. It does not by itself authorize merge or ready-for-review transition.
