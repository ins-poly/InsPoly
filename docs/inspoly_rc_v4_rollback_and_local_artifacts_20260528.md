# InsPoly RC V4 Rollback And Local Artifacts - 2026-05-28

## Rollback Strategy

For the publication documentation packet:

1. Revert the publication documentation commit.
2. Delete the remote release branch if needed.
3. Close the Draft PR if it was opened.

For the W4 pointer implementation already present in RC V4:

1. Revert the W4 implementation commit if product review rejects pointer metadata.
2. Remove `app/report_pointer.py` and optional report-writer pointer arguments through a normal revert, not manual deletion.
3. Keep historical saved reports untouched.
4. Keep local sidecar DBs untouched.

## Local-Only Artifacts

These must not be staged or committed:

- `PROJECT_MEMORY.md`
- `.inspoly_indexer/`
- `release_manifests/`
- `shadow_review_packets/`
- `side_outcome_review_packets/`
- raw DBs and bulky generated evidence

## Files Included In The PR

The RC V4 PR should include committed source, tests, docs, and compact validation JSON. It should not include raw live sidecar DBs, raw run summaries, review packets, or local-only memory.

## Regenerating Sidecar Summaries

Sidecar summaries can be regenerated from local artifacts with the existing sidecar tools when the local DBs exist. The raw DB paths are machine-specific and local-only. Reviewers should rely on committed compact JSON summaries for PR review unless they intentionally reproduce sidecar runs locally.

## What Should Never Be Committed

- private keys or CLOB auth material;
- raw trading/order payloads;
- live sidecar SQLite DBs;
- local-only project memory;
- large generated evidence buckets;
- saved reports mutated only to attach metadata after the fact.

## Publication Rollback Notes

The Draft PR is publication-only. Closing it or deleting the release branch does not roll back local RC V4 code. Reverting RC V4 should be a separate decision, not a side effect of publication cleanup.
