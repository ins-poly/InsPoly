# Indexer Warehouse Implementation Stage Plan - 2026-05-27

## Stage Policy

This campaign implements no stage. The stages below are future approval gates.

## W0 - No-Runtime Schema And Readiness Cleanup

- Goal: make sidecar warehouse implementation reviewable without writing new warehouse data.
- Allowed files: docs, validation outputs, existing sidecar readiness/compare tools, focused tests if needed.
- Forbidden changes: live ingestion, schema migration, production imports, report/browser integration.
- Validation: JSON validation, py_compile/tests only if tools change, runtime import scan.
- Rollback: revert docs/tool changes.
- Approval required: yes, future W0 implementation approval.
- Exit gate: `warehouse_w0_schema_readiness_ready_for_w1_manual_command`.

## W1 - Manual Local Warehouse Command

- Goal: add a manual command that writes to an explicit local sidecar warehouse DB under bounded config.
- Allowed files: `tools/indexer_*`, `app/indexer/*` sidecar modules, focused tests.
- Forbidden changes: scanner/archive/Event Forensic/browser/report/storage production imports, daemon mode, schema changes outside sidecar, saved report mutation.
- Validation: config validation, fixture/no-network tests, py_compile, focused indexer storage/adapters/readiness/compare tests, import isolation scan.
- Rollback: delete local warehouse output and revert sidecar tool changes.
- Approval required: yes.
- Exit gate: `warehouse_w1_manual_command_ready_for_repeat_registry`.

## W2 - Repeat-Run Registry And Retention

- Goal: define registry-driven repeat runs and local retention/deletion controls.
- Allowed files: target registry docs/JSON, sidecar tools, retention docs, tests.
- Forbidden changes: automatic scheduling, production runtime integration, report/browser integration.
- Validation: no-network registry tests, retention-path tests, readiness/compare tests.
- Rollback: delete local sidecar output dirs and revert tool changes.
- Approval required: yes.
- Exit gate: `warehouse_w2_registry_retention_ready_for_sidecar_packets`.

## W3 - Analyst Sidecar Query / Report Packet

- Goal: produce standalone analyst packets from warehouse sidecar DBs without mutating reports.
- Allowed files: sidecar packet tools, docs, compact JSON outputs, tests.
- Forbidden changes: saved report mutation, report schema changes, browser panels, scoring/gate changes.
- Validation: fixture DB tests, packet shape tests, no production import scan.
- Rollback: delete sidecar packets and revert tools.
- Approval required: yes.
- Exit gate: `warehouse_w3_sidecar_packets_ready_for_pointer_decision`.

## W4 - Optional Report Pointer Only

- Goal: add pointer-only metadata to reports only if product-approved.
- Allowed files: to be defined by a future report-pointer RFC.
- Forbidden changes: copied warehouse metrics, UI sorting/filtering changes, scoring/routing changes.
- Validation: old-report compatibility, report writer/loader tests, browser sanity checks.
- Rollback: disable pointer emission and preserve old-report no-op behavior.
- Approval required: yes, separate product approval.
- Exit gate: `warehouse_w4_pointer_metadata_ready_no_metric_copying`.

## W5 - Scheduled / Background Mode

- Goal: consider scheduled local sidecar collection only after manual warehouse value is proven.
- Allowed files: to be defined by a future scheduler RFC.
- Forbidden changes: automatic startup by default, hosted service assumptions, production runtime dependency.
- Validation: lifecycle tests, stop/rollback tests, disk cap tests, operator-control tests.
- Rollback: disable scheduling and delete local sidecar outputs.
- Approval required: yes, separate high-risk approval.
- Exit gate: `warehouse_w5_scheduler_ready_for_limited_operator_use`.

## Recommended Next Stage

Only W0 is ready for a future implementation campaign. W1-W5 should stay blocked until W0 exits cleanly and the operator approves the next stage.
