# Indexer Warehouse W3 Analyst Query RFC - 2026-05-27

## Purpose

W3 adds a no-network analyst sidecar query command over compact W2 registry metadata. It helps an analyst inspect what local sidecar warehouse evidence exists without opening raw DBs, refreshing live data, mutating saved reports, or affecting production scoring and gates.

## Supported Query Modes

- `list-runs`: list compact registry runs and retention classifications.
- `summarize-run`: summarize one run by run id or label.
- `aggregate`: show aggregate market, public trade, cursor, malformed JSON, and duplicate counts.
- `target-coverage`: show target-level rows where compact registry metadata includes `rowsByTarget`.
- `health`: summarize W0/W1 readiness, malformed JSON, duplicate indicators, stale historical warnings, and collection metadata state.
- `retention-status`: show active, retained, cleanup, and blocked classifications with recommendations.
- `blocked-scopes`: list runtime scopes that remain unavailable without separate approval.

## Unsupported Query Modes

W3 must not support:

- score ranking;
- insider verdicts;
- funding conclusions;
- trading/order data;
- private/auth data;
- report embedding;
- browser UI panels;
- live refresh;
- raw DB mutation.

## Output Guarantees

Every W3 output must be:

- advisory-only;
- sidecar-only;
- no-network;
- no model/scoring effect;
- no report/schema effect;
- stale-data aware;
- explicit about local-only machine-specific paths;
- traceable back to the W2 registry and W1 source summaries.

## Input Boundary

The preferred input is W2 registry JSON. W3 should not read raw DBs. If a future query needs fields unavailable in the registry, the correct response is to harden W2 registry inputs or write a separate RFC, not to silently query raw DBs.

## Runtime Boundary

W3 does not implement warehouse ingestion, writer/copy behavior, append retention, cleanup automation, scheduling, production imports, report/browser integration, storage migration, saved report mutation, scoring/gate changes, funding/Phase 3 runtime, or CLOB auth/trading.

## Recommended Implementation

Add `tools/indexer_warehouse_query.py` with compact JSON and optional Markdown output. Keep tests fixture-based and no-network. Include explicit warnings for `sidecar_only`, `advisory_only`, `not_scoring_signal`, `not_report_integrated`, `local_paths_may_be_machine_specific`, and `stale_data_possible_no_live_refresh`.

## Exit Decision

W3 is safe to implement as a compact registry reader. W4 report-pointer work remains product-gated and must be pointer-only if approved later.
