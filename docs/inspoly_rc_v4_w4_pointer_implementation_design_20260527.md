# InsPoly RC V4 W4 Pointer Implementation Design - 2026-05-27

## Decision

Chosen design: implement pointer helper plus explicit, absent-by-default new-report writer support.

## Options Considered

| Option | Decision | Reason |
| --- | --- | --- |
| Helper and tests only | Rejected for RC V4 | Safe but does not complete the approved W4 implementation. |
| Helper plus explicit report writer support | Chosen | Adds discoverability for newly generated reports only when a caller supplies a validated pointer. Normal reports remain unchanged. |
| Postprocessor copied report tool | Rejected | Creates a second report artifact and increases saved-report confusion. |
| Keep W4 unimplemented | Rejected | Contract audit shows a narrow safe path. |

## Implementation Shape

- Add a pure helper module: `app/report_pointer.py`.
- Keep the helper outside `app.indexer` package imports to avoid pulling sidecar indexer storage/tooling into scanner/archive/Event Forensic runtime paths.
- Add optional `indexer_warehouse_pointer` keyword arguments to scanner, archive, and Event Forensic report generation.
- Attach `indexerWarehousePointer` only when the optional payload is present.
- Validate and normalize the pointer before persistence.
- Preserve old reports and ordinary new reports without the pointer.

## Pointer Contract

Required normalized fields:

- `pointerVersion: indexer_warehouse_report_pointer_v1`
- `sidecarOnly: true`
- `advisoryOnly: true`
- `artifactType`
- `artifactPath`
- `artifactId`
- `generatedAt`
- `sourceReportId`
- `metricsCopied: false`
- `scoringEffect: false`
- `routingEffect: false`
- `uiRequired: false`
- `liveRefresh: false`
- `rawDbReadRequired: false`
- local-only, stale-data, and analyst-confusion warnings.

## Explicit Rejections

The helper rejects unknown fields and metric-like or row-level fields, including copied trade/market/cursor counts, row-level context, scoring labels, funding conclusions, Phase 3 conclusions, cases, trades, wallets, targets, and health verdicts.

## Regression Risk

Primary risk is report-writer compatibility. The implementation keeps pointer support optional and tests:

- scanner writer absent-by-default output;
- scanner/archive/Event Forensic explicit pointer persistence;
- browser payload ignoring pointer metadata;
- Event Forensic old-report loader preservation;
- unsafe pointer rejection.

## Stop Conditions

Stop and downgrade the W4 gate if pointer support requires UI changes, report sorting/filtering changes, copied metrics, row-level data, raw DB reads, live refresh, storage migration, scoring/gate/funding/Phase 3 changes, or sidecar live-tool imports.
