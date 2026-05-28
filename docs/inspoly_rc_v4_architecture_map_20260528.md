# InsPoly RC V4 Architecture Map - 2026-05-28

## Purpose

This document gives GitHub reviewers a compact map of the RC V4 architecture and the boundary between production report/runtime paths and sidecar-only indexer warehouse tooling.

## High-Level System

```mermaid
flowchart TD
    A["CLI / Local Launchers"] --> B["Recent Scanner"]
    A --> C["Archive Researcher"]
    A --> D["Event Forensic Analyzer"]
    B --> E["Local Reports and Browser Payloads"]
    C --> E
    D --> E
    E --> F["Browser UIs"]
    G["Sidecar Indexer / Warehouse Tools"] --> H["Compact Sidecar Summaries"]
    H --> I["Optional indexerWarehousePointer Metadata"]
    I -. "explicit pointer only" .-> E
    G -. "no production runtime import" .- B
    G -. "no production runtime import" .- C
    G -. "no production runtime import" .- D
```

## Production Runtime Paths

```mermaid
flowchart LR
    P["Polymarket Public APIs"] --> S["app/polymarket.py"]
    S --> R["app/scanner.py"]
    S --> A["app/archive_scanner.py"]
    S --> F["app/event_forensic.py"]
    R --> O[".inspoly reports"]
    A --> AO["archive outputs"]
    F --> EO["event forensic outputs"]
    O --> BU["app/browser_desktop.py / app/browser_ui.html"]
    EO --> EFU["app/event_forensic_desktop.py / app/browser_event_forensic_ui.html"]
```

Production runtime paths remain the scanner, archive researcher, Event Forensic analyzer, storage/report writers, and browser loaders. RC V4 does not add live indexer warehouse tools to these runtime paths.

## Sidecar Indexer Warehouse Boundary

```mermaid
flowchart TD
    L["Manual bounded sidecar runs"] --> DB["Local-only SQLite sidecar DBs"]
    DB --> W1["W1 manual no-network review command"]
    W1 --> W2["W2 registry and retention manifest"]
    W2 --> W3["W3 analyst sidecar query"]
    W3 --> W4["W4 optional report pointer payload"]
    W4 -. "metadata only, explicit payload" .-> Reports["New scanner/archive/Event Forensic reports"]
    DB -. "raw local-only, not committed" .-> Local[".inspoly_indexer/"]
```

Sidecar DBs and raw outputs remain local-only. W1/W2/W3 read compact local artifacts and produce advisory summaries. W4 only stores a pointer to compact sidecar artifacts when an explicit validated pointer payload is supplied.

## What Is Production Runtime vs Sidecar-Only

| Area | RC V4 Status |
| --- | --- |
| Scanner/archive/Event Forensic scoring | Production runtime, unchanged by publication |
| Browser report loading | Production runtime, no W4 UI panel |
| `indexerWarehousePointer` | Optional report metadata, absent by default |
| Indexer bounded live runner | Sidecar tool, not production runtime |
| Warehouse W1 manual command | Sidecar no-network tool |
| Warehouse W2 registry | Sidecar no-network manifest |
| Warehouse W3 query | Sidecar no-network query |
| Raw sidecar DBs | Local-only, not committed |
| Scheduler/background warehouse mode | Blocked |

## Review Focus

Reviewers should focus on whether optional pointer metadata stays additive and absent-safe, and whether sidecar tooling remains outside production runtime imports.
