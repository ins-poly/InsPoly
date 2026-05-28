# InsPoly RC V4 Data Flow And Schemas - 2026-05-28

## Report Generation Flow

```mermaid
flowchart TD
    A["Scanner / Archive / Event Forensic run"] --> B["Score and assemble report data"]
    B --> C{"Explicit safe pointer supplied?"}
    C -- "No" --> D["Write legacy-compatible report shape"]
    C -- "Yes" --> E["Validate pointer with app/report_pointer.py"]
    E --> F{"Pointer is metadata-only?"}
    F -- "Yes" --> G["Attach top-level indexerWarehousePointer"]
    F -- "No" --> H["Reject pointer"]
    G --> I["Write report"]
    D --> I
```

Reports without `indexerWarehousePointer` remain valid. The pointer is optional and absent by default.

## Optional Pointer Schema Example

```json
{
  "indexerWarehousePointer": {
    "pointerVersion": "indexer_warehouse_report_pointer_v1",
    "sidecarOnly": true,
    "advisoryOnly": true,
    "artifactType": "indexer_warehouse_query",
    "artifactPath": "validation_outputs/inspoly_indexer_warehouse_w3_query_run_20260527.json",
    "artifactId": "w3-query-20260527",
    "generatedAt": "2026-05-27T14:51:26+00:00",
    "sourceReportId": "example-report-id",
    "metricsCopied": false,
    "scoringEffect": false,
    "routingEffect": false,
    "uiRequired": false,
    "liveRefresh": false,
    "rawDbReadRequired": false,
    "registryPath": "validation_outputs/inspoly_indexer_warehouse_registry_20260527.json",
    "queryRunPath": "validation_outputs/inspoly_indexer_warehouse_w3_query_run_20260527.json",
    "localOnlyWarning": "The referenced sidecar artifact may be local-only and machine-specific.",
    "staleDataWarning": "The referenced sidecar artifact is historical and does not refresh live data.",
    "analystConfusionNote": "This pointer is advisory metadata only; it is not a verdict, ranking input, or report metric.",
    "qualityNotes": [
      "Pointer references compact sidecar evidence only."
    ]
  }
}
```

Forbidden pointer content includes market/trade/cursor counts, row-level cases, target rows, health verdicts as report evidence, scoring labels, funding conclusions, Phase 3 conclusions, wallets, trades, or copied metrics.

## Side And Outcome Normalization Flow

```mermaid
flowchart LR
    A["Raw market / outcome labels"] --> B["Side/outcome normalization"]
    B --> C["Canonical side and outcome fields"]
    C --> D["Scanner/archive/Event Forensic evidence"]
    D --> E["Reports and exports"]
```

RC V4 does not change side/outcome scoring semantics. The GitHub publication packet only documents the current release state.

## Event Forensic Review Demotion Flow

```mermaid
flowchart TD
    A["Event Forensic candidate"] --> B["Scope and market resolution"]
    B --> C["Base scoring and evidence fields"]
    C --> D{"Weak-history near-certainty later win?"}
    D -- "Yes" --> E["Demote from primary review bucket"]
    D -- "No" --> F["Keep normal review routing"]
    E --> G["Still exported and reviewable"]
    F --> G
```

The demotion is already part of RC V4 history. This publication campaign does not alter it.

## Warehouse W0-W4 Sidecar Pipeline

```mermaid
flowchart TD
    W0["W0 contracts and readiness fields"] --> W1["W1 manual local DB review"]
    W1 --> W2["W2 registry and retention"]
    W2 --> W3["W3 analyst sidecar query"]
    W3 --> W4["W4 optional report pointer"]
    W4 --> R["New reports only when explicit pointer supplied"]
```

W0-W3 are sidecar/no-network review layers. W4 is a pointer to compact sidecar artifacts, not a warehouse integration.
