# InsPoly RC V4 Reviewer Guide - 2026-05-28

## Recommended Review Order

1. Read `docs/inspoly_rc_v4_github_release_overview_20260528.md`.
2. Read `docs/inspoly_rc_v4_architecture_map_20260528.md`.
3. Review W4 pointer files:
   - `app/report_pointer.py`
   - `app/scanner.py`
   - `app/archive_scanner.py`
   - `app/event_forensic.py`
   - `tests/test_indexer_report_pointer.py`
4. Review sidecar warehouse command boundaries:
   - `app/indexer/warehouse_contract.py`
   - `tools/indexer_warehouse_manual_command.py`
   - `tools/indexer_warehouse_registry.py`
   - `tools/indexer_warehouse_query.py`
5. Review validation evidence in `docs/inspoly_rc_v4_validation_matrix_20260528.md`.

## High-Risk Review Areas

| Area | Why it matters | Expected safe state |
| --- | --- | --- |
| Report pointer validation | Prevents sidecar metrics from becoming report evidence | Pointer is metadata-only and rejects copied metrics |
| Report writer defaults | Old reports and normal new reports must remain unchanged | Pointer absent unless explicit payload is supplied |
| Browser loaders | Browser must not need a W4 UI panel | Pointer is tolerated but not surfaced as UI behavior |
| Sidecar imports | Warehouse tools must not become production runtime | Import scans show no live tools in scanner/archive/Event Forensic/browser paths |
| Scoring/gates | Release packaging must not change model behavior | No scoring/gate/funding/Phase 3 changes |

## Low-Risk Files

The GitHub publication packet itself is docs and compact JSON only. These files are intended to help review and do not change runtime behavior.

## How To Check No Production Sidecar Integration Occurred

Review imports in:

- `app/scanner.py`
- `app/archive_scanner.py`
- `app/event_forensic.py`
- `app/browser_desktop.py`
- `app/event_forensic_desktop.py`
- `app/storage.py`

Safe state: production paths may import the pure `app.report_pointer` helper, but must not import live/manual warehouse tools such as `tools/indexer_bounded_live_sidecar_run.py`, `tools/indexer_warehouse_manual_command.py`, `tools/indexer_warehouse_registry.py`, or `tools/indexer_warehouse_query.py`.

## What Not To Confuse With Production Behavior

- Sidecar warehouse W1/W2/W3 tools are local no-network review commands.
- Local `.inspoly_indexer/` DBs are not committed release artifacts.
- `indexerWarehousePointer` is a pointer to compact sidecar artifacts, not copied report evidence.
- W4 does not add a browser UI panel.
- W4 does not change sorting, filtering, routing, or scoring.
