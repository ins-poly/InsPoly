# InsPoly RC V4 Merge Checklist - 2026-05-28

## Before Marking Ready For Review

- Confirm the owner accepts local validation plus no GitHub CI for this PR, or add CI in a separate campaign.
- Confirm the final PR body links to the reviewer docs. If automation could not update it, paste from `docs/inspoly_rc_v4_pr_body_replacement_20260528.md`.
- Confirm tracked `release_manifests/` files are absent from the PR branch.
- Confirm local-only buckets remain unstaged:
  - `PROJECT_MEMORY.md`
  - `.inspoly_indexer/`
  - `release_manifests/`
  - `shadow_review_packets/`
  - `side_outcome_review_packets/`
- Confirm no new runtime files changed after the latest validation checkpoint.

## Before Merge

- PR must no longer be Draft.
- Owner must explicitly approve merge.
- Recheck mergeability.
- Recheck PR comments and review threads.
- Re-run at minimum:
  - JSON validation for changed compact JSON;
  - `python3 -m compileall -q app tools tests`;
  - `python3 -m unittest discover -s tests -p 'test_*.py'`;
  - runtime import scan for sidecar tools;
  - copied warehouse metrics scan;
  - privacy/secret scan;
  - `git diff --check`.

## Merge Must Not Imply

- Phase 3 runtime approval.
- Warehouse runtime approval.
- Scheduler/background worker approval.
- Trading/CLOB auth approval.
- Report UI panel approval.
- Scoring/gate/funding/HER changes beyond the reviewed RC V4 behavior.

## Rollback

If review rejects the PR, close the Draft PR or revert the release branch. Do not mutate saved reports or local sidecar DBs as part of rollback.
