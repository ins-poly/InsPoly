# Future W2 Registry And Retention Packet - 2026-05-27

## Status

Packet status: `ready_for_owner_review`.

Implementation status: not implemented.

W2 is not approved by W1. This packet defines the next safe approval question.

## W2 Objective

Define how local warehouse sidecar evidence should be inventoried, retained, deleted, and reviewed across repeated manual runs without adding a scheduler, daemon, background worker, report/browser integration, production runtime imports, or live ingestion beyond separate approvals.

## Allowed W2 Scope

W2 may define:

- target registry format;
- local DB inventory format;
- compact retained-run manifest;
- raw DB local-only policy;
- max retained DB count;
- max retained byte warning;
- manual deletion guidance;
- rollback rules;
- readiness/W1 summary requirements for retained DBs;
- no-network tests using generated fixture DBs.

## Forbidden W2 Scope

W2 must not implement:

- live ingestion;
- automatic repeat runs;
- scheduler/background/daemon mode;
- report/browser integration;
- production storage schema migration;
- production runtime imports;
- saved report mutation;
- scoring/gate/funding/Phase 3 use;
- CLOB auth/private keys/trading/order placement;
- push/PR.

## Registry Requirements

A W2 registry should include:

- target slug;
- canonical market slug;
- condition ID;
- target classification;
- approved cap profile;
- source/provenance;
- last reviewed W1 summary path;
- last readiness gate;
- whether per-target collection metadata is present;
- operator approval status for future live collection.

No wildcard or broad event-family target should be accepted without a separate resolver preflight.

## Retention Requirements

Retention policy should define:

- raw DB root;
- compact summary root;
- max raw DB count;
- max raw DB bytes or warning threshold;
- stale DB warning policy;
- deletion command or manual deletion instructions;
- rollback by deleting local sidecar output directory;
- rule that raw `.inspoly_indexer/` DBs are not committed by default.

## Required Validation For W2

- JSON validation for registry and retained-run manifest.
- No-network tests for registry validation.
- Generated fixture DB tests for W1 summary compatibility.
- Runtime import scan.
- `git diff --check`.
- Staged diff check before commit.

## W2 Exit Gate Options

- `indexer_warehouse_w2_registry_retention_ready_for_sidecar_packets`
- `indexer_warehouse_w2_needs_retention_policy_revision`
- `indexer_warehouse_w2_blocked_by_registry_quality`
- `indexer_warehouse_w2_not_needed`

## Approval Question

Should the next campaign implement a no-network registry/retention manifest for local W1 summaries and raw sidecar DB inventory?

Recommended default: approve only a fixture/no-network W2 registry and retention manifest first. Keep scheduled/background mode and live repeat collection separately blocked.
