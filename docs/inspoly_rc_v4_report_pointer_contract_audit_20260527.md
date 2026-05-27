# InsPoly RC V4 Report Pointer Contract Audit - 2026-05-27

## Scope

This audit reviews whether W4 pointer-only indexer warehouse metadata can be added to newly generated scanner, archive, and Event Forensic reports without changing scoring, routing, browser behavior, report sorting/filtering, saved historical reports, or sidecar warehouse runtime behavior.

## Current Writers And Loaders

| Flow | Writer | Loader / consumer | Compatibility finding |
| --- | --- | --- | --- |
| Recent Scanner | `app/scanner.py` / `Scanner._write_report_files` | `app/browser_desktop.py` | Writer persists a plain JSON object and Markdown/text summaries. Browser normalization preserves unknown top-level fields and builds payloads from known report keys. |
| Archive Researcher | `app/archive_scanner.py` / `ArchiveResearchScanner._write_report_files` | `app/browser_desktop.py` archive subclass | Writer persists a plain JSON object and export path metadata. Browser fallback logic reads known archive fields and ignores unrelated metadata. |
| Event Forensic | `app/event_forensic.py` / `EventForensicAnalyzer._write_report_bundle` | `app/event_forensic_desktop.py` | Writer persists report JSON plus bundle-local `event_analysis.json`. Desktop loader deep-copies report JSON and preserves unknown fields while rebuilding known report text. |

## Old-Report Compatibility

Old reports without `indexerWarehousePointer` remain valid because the field is optional and absent by default. Existing loader tests already cover old scanner reports without newer side/outcome fields and old Event Forensic reports without newer scope fields. RC V4 adds pointer-specific compatibility tests.

## Unknown Top-Level Key Tolerance

Current browser paths use explicit known keys for payloads, filters, labels, and counts. They do not iterate arbitrary top-level report fields into visible rows, sorting, filtering, scoring, or labels. A top-level optional pointer is therefore the least invasive placement.

## Safe Pointer Placement

Approved placement:

- top-level key: `indexerWarehousePointer`;
- JSON object only;
- emitted only when an explicit pointer payload is supplied;
- absent from ordinary reports by default;
- metadata only, with no copied warehouse counts or row-level data.

## Must Not Add Pointer Here

The pointer must not be added to:

- individual report rows;
- `cases`, `secondary_review_cases`, `suspicious_trades`, or wallet rows;
- scoring subscores or raw metrics;
- browser UI payload fields;
- storage scan-run rows;
- saved historical reports.

## Rollback

Rollback is local and additive: remove optional pointer attachment and helper tests. Historical saved reports are not mutated. Reports generated without an explicit pointer never contain the field.

## Audit Decision

The narrow safe path is available: implement a pure pointer validator plus explicit absent-by-default writer support. Any copied metrics, row-level context, UI panel, scoring/gate effect, report sorting/filtering change, raw DB read, or warehouse live-tool import remains blocked.
