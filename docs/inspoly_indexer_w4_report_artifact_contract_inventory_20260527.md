# Indexer W4 Report Artifact Contract Inventory - 2026-05-27

## Scope

This inventory reviews where a future indexer warehouse report pointer could live if product approval is granted later. It does not implement W4 and does not edit report writers, browser loaders, storage, scoring, or saved artifacts.

## Current Report Writers

| Flow | Writer | Current saved JSON contract |
| --- | --- | --- |
| Recent Scanner | `app/scanner.py` / `Scanner._write_report_files` | Writes one report JSON plus Markdown and text summary. Top-level keys include run timestamps, counts, diagnostics, settings, funding resolver health, and `cases`. |
| Archive Researcher | `app/archive_scanner.py` / `ArchiveScanner._write_report_files` | Writes one report JSON plus Markdown/text/CSV side outputs. Top-level keys include archive range, counts, visible and secondary-review cases, rollups, `export_files`, diagnostics, and settings. |
| Event Forensic | `app/event_forensic.py` / `EventForensicAnalyzer._write_report_bundle` | Writes report JSON and bundle-local `event_analysis.json` with the same persisted payload. Top-level keys include event/scope/summary, markets, display rows, graph data, related markets, markdown text, model gap, and `export_files`. |

## Current Loaders And Browser Expectations

| Loader | Behavior relevant to W4 |
| --- | --- |
| `app/browser_desktop.py` | Loads JSON, makes a shallow report copy, normalizes known `cases`, and builds browser payloads from known keys. Unknown top-level fields are not used for sorting/filtering. |
| `app/browser_desktop.py` archive subclass | Reuses scanner normalization and adds archive `report_txt_path` fallback from `export_files.summary_txt_path`. |
| `app/event_forensic_desktop.py` | Deep-copies loaded reports, refreshes report text, restores display rows from compatible saved reports when needed, and keeps old reports absent-safe. |
| `app/browser_ui.html` | Consumes the server payload fields exposed by `browser_desktop.py`; it does not inspect arbitrary report top-level keys. |
| `app/browser_event_forensic_ui.html` | Consumes known Event Forensic report fields directly from the local server payload. It uses fallback helpers for older scope fields and ignores unrelated top-level metadata. |
| `app/storage.py` | Stores scan-run path/count metadata. It does not store full report JSON or validate report top-level keys. |

## Old-Report Compatibility

Current compatibility evidence supports an additive, absent-safe top-level pointer design:

- scanner/browser normalization keeps old reports safe when side/outcome fields are absent;
- Event Forensic report preparation keeps old reports safe when product-scope fields are absent;
- browser payload builders derive behavior from explicit known fields and do not require a fixed top-level JSON schema;
- no current path requires the future pointer to exist.

This does not by itself approve implementation. A future implementation must still add explicit old-report and new-report compatibility tests.

## Pointer Placement If Future-Approved

The least risky future location is one optional top-level object:

- `indexerWarehousePointer`

It should be absent-safe, metadata-only, and ignored by scoring, sorting, filtering, and routing. It should point to committed compact sidecar artifacts or local-only sidecar paths; it must not copy run counts, row counts, target rows, health metrics, or warehouse findings into report rows.

## Forbidden Content

The pointer must not contain:

- copied warehouse metrics;
- row-level sidecar context;
- scoring, gate, severity, HER, funding, candidate-admission, or Phase 3 conclusions;
- live-refresh instructions;
- raw DB query instructions;
- browser panel instructions;
- CLOB auth, private keys, trading, order placement, or external-write details.

## Analyst Confusion Risks

Even pointer-only metadata can confuse analysts if it appears to certify warehouse completeness. Any future implementation must state that the pointer is local, stale unless regenerated, sidecar-only, and advisory. Old reports without the pointer must not be downgraded or visually treated as incomplete.

## Inventory Decision

Top-level pointer metadata appears technically compatible enough for an RFC because current loaders tolerate absent/extra metadata and old reports remain fallback-safe. Implementation remains approval-gated and must not occur in this campaign.
