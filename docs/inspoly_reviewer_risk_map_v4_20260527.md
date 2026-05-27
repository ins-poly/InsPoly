# InsPoly Reviewer Risk Map V4 - 2026-05-27

## Highest-Risk Review Areas

| Area | Risk | Mitigation |
| --- | --- | --- |
| Report writer compatibility | Optional writer keyword could affect persisted JSON paths if mishandled. | Pointer absent by default; focused writer tests cover scanner/archive/Event Forensic. |
| Analyst confusion | Pointer could be mistaken for report evidence. | Helper enforces advisory/no-metrics/no-scoring/no-routing/no-UI flags. |
| Browser behavior | Pointer might accidentally affect payloads. | Browser payload test proves pointer metadata is not exposed as payload data. |
| Production sidecar coupling | Report runtime could import live warehouse tools. | Helper is pure; import scan blocks `tools/indexer_*` live/query/registry/manual tooling in production paths. |
| Scoring/gate drift | Report metadata changes could be mistaken for model changes. | No scoring/gate code is touched; diff scan and focused scoring tests cover this. |

## Deferred Risks

- Visible report/browser pointer UI remains product-gated.
- Warehouse scheduler/background mode remains blocked.
- Phase 3 and pUSD/CLOB runtime remain blocked.
- Pagination expansion remains blocked.
- Public exact-wallet benchmark labels remain blocked.

## Reviewer Questions

1. Is the pointer helper strict enough about copied metrics and row-level data?
2. Are report writer defaults demonstrably unchanged?
3. Should future W4 UI remain separate from the pointer metadata contract?
4. Is RC V4 ready for a draft PR after owner approval?
