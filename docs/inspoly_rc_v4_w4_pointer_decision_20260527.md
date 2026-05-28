# InsPoly RC V4 W4 Pointer Decision - 2026-05-27

## Decision

Final W4 gate: `indexer_w4_pointer_metadata_implemented_no_ui_no_metrics`.

## Why This Gate Is Supported

The contract audit showed that current report loaders tolerate optional top-level metadata. The implementation keeps the pointer absent by default and validates every explicit pointer payload before persistence. It does not import warehouse query/registry/manual-command tools into scanner/archive/Event Forensic/browser runtime paths.

## Product Boundary

The pointer is a breadcrumb to compact sidecar artifacts. It is not a score, not a report metric, not a row-level verdict, and not a UI feature.

## Still Blocked

- Browser-visible pointer UI.
- Copied warehouse metrics in reports.
- Row-level sidecar context.
- Report sorting/filtering changes.
- Scoring, gate, label, HER, funding, candidate-admission, model, or Phase 3 changes.
- Live refresh or raw DB reads from report runtime.
- Warehouse scheduler/background mode.
- Push/PR.

## Reversal Condition

If future review finds analysts need copied metrics or UI panels for the pointer to be useful, keep W4 metadata implemented but require a separate product RFC before expanding it. Do not silently widen the current contract.
