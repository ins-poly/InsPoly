# Indexer W4 Pointer Metadata Schema - 2026-05-27

## Status

Schema status: static draft only.

Implementation status: implemented in RC V4 as optional, absent-by-default metadata.

## Top-Level Field

Future-approved reports may include one optional top-level object:

```json
{
  "indexerWarehousePointer": {}
}
```

Reports without this field remain valid and must load normally.

## Draft Pointer Object

Required fields:

- `pointerVersion`: `indexer_warehouse_report_pointer_v1`
- `sidecarOnly`: `true`
- `advisoryOnly`: `true`
- `artifactType`: `indexer_warehouse_registry` or `indexer_warehouse_query`
- `artifactPath`: local or committed compact artifact reference
- `artifactId`: stable compact artifact id if available
- `generatedAt`: ISO-8601 timestamp for pointer generation
- `sourceReportId`: source report id/path/name if available
- `metricsCopied`: `false`
- `scoringEffect`: `false`
- `routingEffect`: `false`
- `uiRequired`: `false`
- `liveRefresh`: `false`
- `rawDbReadRequired`: `false`
- `localOnlyWarning`: human-readable warning
- `staleDataWarning`: human-readable warning
- `analystConfusionNote`: human-readable warning

Optional fields:

- `registryPath`
- `queryRunPath`
- `qualityNotes`

## Forbidden Fields

The pointer object must not contain:

- market/trade/cursor counts;
- target row counts;
- health verdicts as report evidence;
- scoring labels;
- funding or Phase 3 conclusions;
- row-level sidecar context;
- raw DB credentials or private paths beyond an advisory local artifact path;
- live refresh instructions.

## Static Example

Example fixture:

- `tests/fixtures/indexer_w4_report_pointer_example.json`

The fixture is validated by focused tests. Report writers only emit the pointer when an explicit pointer payload is supplied.

## Compatibility Rules

- Missing pointer means no sidecar pointer is available, not that the report is lower quality.
- Pointer presence must not change sorting, filtering, labels, scoring, candidate admission, or routing.
- Local paths may not resolve on another machine.
- Stale sidecar data must not be interpreted as live evidence.
