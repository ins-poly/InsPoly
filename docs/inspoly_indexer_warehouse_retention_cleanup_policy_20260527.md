# Indexer Warehouse Retention And Cleanup Policy - 2026-05-27

## Policy Summary

This policy governs local sidecar indexer warehouse artifacts after W2. It does not delete, move, compact, or rewrite anything.

## Stays Local-Only

The following remain local-only by default:

- `.inspoly_indexer/` SQLite DBs;
- raw bounded-run summaries under `.inspoly_indexer/`;
- local operator configs;
- raw provider payload captures, if any are created by future approved runs;
- bulky validation outputs.

## Commit-Safe Artifacts

The following can be committed when compact and validated:

- W1 review summaries under `validation_outputs/`;
- W2 registry JSON under `validation_outputs/`;
- W2/W3 docs under `docs/`;
- compact decision JSON;
- tool and test files.

## Never Commit By Default

Do not commit:

- raw `.inspoly_indexer/` DBs;
- raw `.inspoly_indexer/` run directories;
- private/auth/trading material;
- copied saved-report artifacts;
- `PROJECT_MEMORY.md`;
- `release_manifests/`;
- `shadow_review_packets/`;
- `side_outcome_review_packets/`.

## Manual Cleanup Rules

Raw DBs may be deleted manually only after:

1. W1 summary JSON exists for the DB or the DB is explicitly deemed not useful.
2. W2 registry JSON records whether the DB was active, retained, stale, cleanup, or blocked.
3. Current gate docs no longer depend on the raw DB as the only evidence.
4. The operator understands that deletion removes the ability to re-audit that exact local DB.

No automatic deletion is allowed in W2.

## Current Retention Recommendation

- Preserve `.inspoly_indexer/bounded_live_multitarget_per_target_20260527/indexer.sqlite3` locally as the active review candidate until a future W3 or newer per-target run supersedes it.
- Retain the first one-target and same-slug repeat DBs locally as references while the compact W1/W2 evidence chain relies on them.
- Treat stale cursor warnings as expected for historical review; they do not by themselves require deletion.

## Reproducing Summaries

To reproduce W1 summaries, rerun the manual W1 command against an existing local DB and optional raw run summary. To reproduce W2, rerun the W2 registry command from compact W1 summary JSON.

## Rollback

W2 rollback means removing compact W2 docs/JSON and the W2 tool/test commit. Raw DBs should not be touched by rollback unless the operator separately asks.
