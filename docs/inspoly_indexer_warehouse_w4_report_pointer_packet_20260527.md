# Future W4 Report Pointer Packet - 2026-05-27

## Status

Packet status: `ready_for_owner_review`.

Implementation status: not implemented.

## W4 Objective

W4 may propose a report-level pointer to sidecar warehouse registry artifacts so an analyst can find the relevant local sidecar evidence from a report context. It must be pointer-only.

## Allowed W4 Scope

If separately approved, W4 may define:

- a compact pointer block that references a W2/W3 sidecar artifact path or id;
- pointer schema/version;
- generated timestamp;
- source report id if available;
- `metricsCopied=false`;
- `scoringEffect=false`;
- local-only warning;
- stale-data warning;
- analyst confusion note.

## Forbidden W4 Scope

W4 must not implement:

- copied sidecar metrics in reports;
- UI panel or browser integration by default;
- scoring, gate, HER, funding, candidate admission, or Phase 3 effect;
- report sorting/filtering changes;
- live refresh;
- raw DB reads from report runtime;
- production imports of sidecar query tools;
- CLOB auth/private keys/trading/order placement.

## Product Approval Required

W4 requires explicit product approval before implementation because it touches report metadata boundaries. This W3 campaign does not approve implementation.

## Validation Required If Approved Later

- report schema compatibility tests;
- old report load tests;
- no copied metrics proof;
- no scoring/gate effect proof;
- browser/report import scan;
- rollback plan that removes pointer metadata without mutating saved historical reports.

## Exit Gate Options

- `indexer_warehouse_w4_report_pointer_ready_for_implementation`
- `indexer_warehouse_w4_keep_sidecar_only`
- `indexer_warehouse_w4_blocked_by_confusion_risk`
- `indexer_warehouse_w4_not_needed`

## Recommended Default

Keep W4 as product-gated and pointer-only. Do not implement a UI panel or copy metrics into reports from the W3 query tool.
