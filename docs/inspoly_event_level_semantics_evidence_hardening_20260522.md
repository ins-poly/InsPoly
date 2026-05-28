# InsPoly Event-Level Semantics Evidence Hardening

- Date: 2026-05-22
- Scope: evidence hardening only; no runtime event-scope implementation
- Tool: `tools/event_level_semantics_evidence_audit.py`
- Machine output: `validation_outputs/event_level_semantics_evidence_audit_20260522.json`
- Runtime implementation: false
- Network/RPC used: false
- Gate decision: `event_level_semantics_needs_product_decision`

## Current Semantics

- `market` scope means primary scoring is selected-market only.
- `event` scope means primary scoring may cover the explicit event family.
- Related/sibling markets can be context; they must not silently broaden selected-market primary scoring.
- Side/Outcome economic direction does not decide event scope.

## Local Evidence

| Metric | Count |
|---|---:|
| artifacts scanned | 260 |
| loaded reports | 259 |
| skipped too large | 1 |
| selected-market reports | 206 |
| whole-event reports | 31 |
| reports with related market references | 42 |
| reports with sibling context rows | 1 |
| reports with clear scope copy | 237 |
| possible scope ambiguity | 1 |

## Assessment

Local evidence supports the existing RFC boundary: selected-market and whole-event semantics need explicit copy and product decision before runtime changes. One possible ambiguity remains enough to avoid runtime implementation.

## Requires Product/User Approval

- Any change that broadens selected-market scoring to event-wide.
- UI mode controls, copy, sorting, or filtering changes.
- Any candidate admission or rank semantics change based on event scope.

## Gate

Decision: `event_level_semantics_needs_product_decision`.
