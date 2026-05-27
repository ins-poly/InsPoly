# InsPoly Sidecar Report-Pointer Product Decision

Date: 2026-05-27 EEST

Gate: `sidecar_report_pointer_keep_sidecar_only`

Runtime changed: `false`

## Decision Context

The sidecar context stack is useful for manual analyst review, but current product evidence does not justify copying sidecar metrics into reports or adding browser UI panels. Existing tools already create inventories, previews, review packets, and sidecar value dashboards without changing production outputs:

- `tools/shadow_artifact_corpus_inventory.py`
- `tools/render_shadow_context_preview.py`
- `tools/generate_shadow_review_packets.py`
- `tools/shadow_sidecar_value_dashboard.py`

The prior RFC marked pointer-only report metadata as RFC-ready, but not product-approved. This campaign turns that into an owner decision packet.

## Options Compared

| Option | Decision | Why |
| --- | --- | --- |
| Keep sidecar-only | Current path | Lowest analyst confusion and regression risk. Existing tools remain explicit sidecar artifacts. |
| Report-level pointer metadata only | Future RFC candidate | Improves traceability without copying metrics, but still changes report shape and needs product approval. |
| UI panel or report embedding | Blocked | Higher confusion risk, requires browser/report writer changes, and could make advisory context look like a verdict. |

## Future Pointer-Only Shape

If product approval is granted later, a report pointer block should be additive and absent-safe. It should contain only metadata like:

- `sidecarPointerVersion`
- `sidecarOnly`
- `artifactType`
- `artifactPath`
- `artifactId`
- `generatedAt`
- `sourceReportId`
- `advisoryScope`
- `metricsCopied: false`
- `scoringEffect: false`
- `routingEffect: false`
- `runtimeRequired: false`
- `qualityNotes`

This campaign adds only the static example `tests/fixtures/sidecar_report_pointer/sidecar_report_pointer_block_example.json`. It is not imported or wired into reports.

## Safety Requirements Before Implementation

A future pointer implementation would need:

- old report absent-safe loading tests;
- new report writer tests proving the pointer is metadata only;
- browser tests proving no sorting, filtering, labels, scoring, or routing changes;
- clear analyst copy that sidecar context is advisory and incomplete;
- no copied shadow metrics, profile PnL, microstructure, replay rows, or alert verdicts in production report payloads;
- rollback plan that removes the additive pointer field without touching sidecar artifacts.

## Confusion Risks

Pointer-only metadata is safer than copying metrics, but it still creates product risk:

- analysts may assume a pointer means sidecar context was complete;
- old reports would lack the pointer and must not look lower quality by comparison;
- sidecar paths may point to local-only artifacts that are absent on another machine;
- review packets may contain advisory context that duplicates or conflicts with production fields.

## Decision

Keep sidecar context sidecar-only for current product state. Pointer-only report metadata is decision-ready for a future product RFC, but not approved for implementation by this campaign.
