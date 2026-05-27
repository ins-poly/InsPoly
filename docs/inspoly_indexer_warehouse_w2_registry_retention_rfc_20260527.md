# Indexer Warehouse W2 Registry And Retention RFC - 2026-05-27

## Purpose

W2 adds a compact registry and retention policy for local sidecar warehouse review artifacts. It does not add live ingestion, a warehouse writer, a scheduler, background work, report/browser integration, production imports, or any storage migration.

The registry answers which local sidecar DBs are current review candidates, which are retained references, which are stale or cleanup candidates, and which are blocked by W0/W1 quality gates.

## Manifest Location Policy

Committed artifacts:

- compact registry JSON under `validation_outputs/`;
- human-readable registry and retention docs under `docs/`;
- compact W2 decision JSON under `validation_outputs/`.

Local-only artifacts:

- raw `.inspoly_indexer/` SQLite DBs;
- raw bounded-run summaries under `.inspoly_indexer/`;
- local configs and validation scratch outputs under `.inspoly_indexer/`.

## Allowed Metadata Fields

W2 may store compact metadata only:

- run id and label;
- local DB path reference marked local-only;
- raw summary path reference marked local-only;
- source W1 summary path;
- observed timestamp when available;
- target slugs when available from W1 summaries;
- target-set identity hash;
- market, trade, and cursor counts;
- W0/W1 readiness gates;
- malformed raw JSON and duplicate counts;
- collection metadata status;
- rows by target when present;
- retention classification and recommendation;
- blocked runtime scopes.

## Forbidden Metadata Fields

W2 must not store:

- private keys, auth tokens, API secrets, or signatures;
- order placement or trading payloads;
- wallet private data;
- copied report metrics;
- production scoring, label, HER, funding, or Phase 3 decisions;
- browser/report integration state.

## DB Path Handling

Registry entries may include local DB path references for operator review, but raw DB files remain local-only and are not committed by default. Paths with service or remote schemes are not valid W2 local sidecar references.

The registry tool must not open or mutate input DBs. W1 is responsible for DB review. W2 consumes W1 summaries.

## Raw DB Retention Policy

Raw sidecar DBs remain local evidence, not source artifacts. Recommended defaults:

- keep current active review candidate DBs until a newer W2/W3 review supersedes them;
- keep retained-reference DBs while their compact summaries are still used for current gates;
- warn when raw DB inventory becomes too large rather than deleting automatically;
- delete raw DB directories only by manual operator action after compact registry, W1 summary, and decision docs are preserved.

## Compact Summary Retention Policy

Compact JSON and Markdown summaries are commit-safe when they do not contain secrets, copied report metrics, raw payload dumps, or bulky data. They are the preferred long-term evidence trail for W2 and later reviewer packets.

## Stale DB Classification

Stale cursor warnings are expected for historical local DB review. A stale cursor warning alone does not block W2 if W1 readiness and W0 checks passed. Stale runs become cleanup or refresh candidates only when they are no longer needed for an active gate.

## Run Identity Policy

Run ids are deterministic hashes over label, DB path, and source summary path. Target-set identity is deterministic from target slugs when available, otherwise from the local DB path reference.

## No-Live Guarantee

W2 registry tooling:

- reads compact JSON summaries only;
- performs no network calls;
- performs no live provider resolution;
- writes only the requested compact registry output;
- does not mutate input DBs, raw summaries, saved reports, or production artifacts.

## Rollback

Rollback is local and simple:

1. Delete the compact W2 registry JSON and docs from the branch if the campaign is reverted.
2. Leave raw `.inspoly_indexer/` DBs untouched unless the operator separately deletes them.
3. No production runtime rollback is needed because W2 has no runtime integration.

## Future W3 Boundary

W3 may propose a sidecar-only analyst query/read command over compact registry and W1/W2 summaries. W3 must not copy metrics into reports, change UI/browser behavior, alter scoring/gates, or import sidecar tools into production paths without separate approval.

## RFC Decision

W2 should proceed as no-network registry/retention metadata only. The registry is useful because W1 already proves current DB quality, and W2 can now preserve the review trail without increasing runtime scope.
