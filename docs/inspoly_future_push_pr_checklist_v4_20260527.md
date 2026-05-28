# InsPoly Future Push/PR Checklist V4 - 2026-05-27

## Status

RC V4 is local-only until the owner explicitly approves branch creation, push, and PR.

## Never Stage

- `PROJECT_MEMORY.md`
- `.inspoly_indexer/`
- `release_manifests/`
- `shadow_review_packets/`
- `side_outcome_review_packets/`
- raw DBs and bulky generated evidence
- unrelated local files

## Before Any Push

1. Confirm the owner wants remote publication.
2. Confirm branch strategy and PR grouping.
3. Rerun the RC V4 validation matrix or accept the latest recorded matrix.
4. Recheck `git status --short --branch`.
5. Confirm no local-only buckets are staged.
6. Confirm no live sidecar DBs or raw outputs are staged.
7. Confirm no push/PR has already been performed from this campaign.

## Recommended PR Strategy

Create a draft PR from a dedicated branch after owner approval. Suggested branch:

- `codex/inspoly-local-release-candidate-v4`

Recommended title:

- `Complete InsPoly local release candidate V4 readiness`

## Reviewer Focus

- W4 pointer metadata is optional and absent by default.
- Pointer is metadata-only and rejects copied metrics.
- Browser UI was not changed.
- Scoring/gates/funding/Phase 3 were not changed.
- Warehouse chain remains local sidecar tooling unless separately approved.
- Push/PR is an owner decision, not part of RC V4 local completion.

## Rollback Notes

The W4 implementation can be reverted by removing the pointer helper, optional writer keyword handling, tests, and docs. Historical saved reports and sidecar DBs are not mutated by the implementation.
