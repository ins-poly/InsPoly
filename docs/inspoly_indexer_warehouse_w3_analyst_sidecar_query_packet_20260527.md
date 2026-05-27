# Future W3 Analyst Sidecar Query Packet - 2026-05-27

## Status

Packet status: `ready_for_owner_review`.

Implementation status: not implemented.

## W3 Objective

W3 should add a sidecar-only analyst query/read command over compact W1/W2 summaries and registry metadata. It should help an analyst answer what local warehouse sidecar evidence exists, which run is current, which targets are covered, and which runtime scopes remain blocked.

## Allowed W3 Scope

W3 may:

- read W2 registry JSON;
- read W1 compact summaries referenced by the registry;
- summarize target coverage, run quality, retention classification, and readiness gates;
- emit compact JSON and optional Markdown;
- remain no-network and no-DB-mutation by default;
- make local-only path references explicit.

## Analyst Questions W3 Can Answer

- Which sidecar DB is the current active review candidate?
- Which target set has per-target public trade coverage?
- How many market, trade, and cursor rows are represented by compact summaries?
- Which runs are retained references versus cleanup candidates?
- Which W0/W1/W2 blockers remain?
- What raw DBs must stay local-only?
- What would need separate approval before report/browser/runtime use?

## Forbidden W3 Scope

W3 must not:

- run live/network ingestion;
- open a scheduler, background worker, daemon, or repeat loop;
- mutate input DBs or saved reports;
- copy sidecar metrics into reports;
- change report/browser UI;
- change scoring, gates, HER, funding, candidate admission, or Phase 3 behavior;
- import query tooling into scanner/archive/Event Forensic/browser/report production paths;
- perform storage schema migration;
- use CLOB auth, private keys, trading, or order placement.

## Validation Required

- JSON validation for query outputs.
- `py_compile` for new tool/tests.
- focused W3 registry-query tests.
- W1/W2 regression tests.
- runtime import scan.
- `git diff --check` and staged diff check before commit.

## Exit Gate Options

- `indexer_warehouse_w3_sidecar_query_ready`
- `indexer_warehouse_w3_needs_registry_enrichment`
- `indexer_warehouse_w3_blocked_by_report_integration_pressure`
- `indexer_warehouse_w3_not_needed`

## Recommended Default

Approve W3 only as a local sidecar summary reader. Keep report pointer implementation, UI panels, production imports, and any copied metrics blocked.
