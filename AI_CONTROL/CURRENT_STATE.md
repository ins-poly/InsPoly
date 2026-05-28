# Current State

Last updated: 2026-05-28 EEST.

## Repository State
- Branch inspected: `codex/inspoly-local-release-candidate-v4`.
- Draft PR inspected: https://github.com/ins-poly/InsPoly/pull/1.
- Active publication branch: `codex/inspoly-local-release-candidate-v4`.
- Latest pushed publication checkpoint before PR-readiness audit: `4cd7db9 Record RC V4 draft PR checkpoint`.
- Latest pushed PR-readiness checkpoint before the local-path hygiene patch: `40ebba2 Record RC V4 PR review readiness`.
- Current PR-review gate: `rc_v4_pr_stay_draft_needs_ci_or_review`.
- PR #1 remains Draft / not ready. It is mergeable, but GitHub reports no commit statuses or Actions workflow runs, and there are no comments, reviews, or review threads.
- Local PR-readiness refresh passed on `4cd7db9`: 201 changed JSON files parsed, compileall passed, 391 focused release tests passed, 1240 full unittest discovery tests passed, runtime import scan passed, pointer copied-metric scan passed, and diff checks passed.
- PR publication hygiene refresh found no private-key blocks or common hosted-service tokens. It did find committed `<local-user-home>` local path strings in docs/compact outputs; those were redacted to `<repo>` / `<local-user-home>` placeholders, with a follow-up scan reporting 0 blocking findings.
- Reviewer packaging note: 10 historical `release_manifests/` files are present in the PR diff and should be accepted or cleaned up before the PR leaves Draft.
- Latest release-candidate commit verified: `ad27400 Verify local release candidate state`.
- Latest Release Candidate V3 head verified: `2dd851f Freeze legacy Tk UI as reference-only`.
- Latest future push/PR packaging dry-run base inspected: `fd12c0b Add release candidate V3 strategic state`.
- Latest known-case maintenance base commit inspected: `90e2434 Add public-case human labeling packet`.
- Latest pre-push dry-run commit inspected: `05d688d Add final pre-push packaging dry run`.
- Latest runtime-affecting commit inspected: `0ce05da Add local browser offline runtime assets`.
- Current release-candidate publication gate: `local_release_candidate_v4_draft_pr_open`.
- Current Release Candidate V3 gate: `release_candidate_v3_state_ready`.
- Current future push/PR dry-run gate: `push_pr_dry_run_ready`.
- Full verification matrix at `ad27400`: focused matrix 660 tests OK, full unittest discovery 1105 tests OK.
- Release Candidate V3 verification at `2dd851f`: focused matrix 586 tests OK, full unittest discovery 1122 tests OK.
- Untracked local artifacts were present before this AI_CONTROL work:
  - `release_manifests/*`
  - `shadow_review_packets/*`
  - `side_outcome_review_packets/*`
- These local artifacts were not modified by this setup task.
- Pre-existing process-control state before consolidation:
  - `.gitignore` modified to make AI_CONTROL visible.
  - `AI_CONTROL/` untracked.
  - `skills/strategic-autonomy-review/` untracked.
  - root `AGENTS.md` ignored/local-only.
  - root `PROJECT_MEMORY.md` ignored/local-only.

## What Works
- Recent Scanner, Archive Researcher, and Event Forensic Analyzer have active browser/CLI paths.
- Browser UIs now boot from vendored local React/ReactDOM/Babel assets through narrow static serving.
- The active release launch path is browser-backed. The legacy Tk module `app/desktop.py` is frozen as historical/reference-only and is not used by `python3 -m app desktop`.
- Strategic Operating System files are present and wired into repo/global agent guidance for non-trivial work.
- The `strategic-autonomy-review` skill exists in `skills/strategic-autonomy-review/` and `<local-user-home>/.codex/skills/strategic-autonomy-review/`.
- The test suite has broad local regression coverage compared with early project state; Release Candidate V3 full unittest discovery passed 1122 tests at `2dd851f`.
- The known-case benchmark has been expanded to `known_case_benchmark_v3` with 30 compact cases, including false-positive, sidecar-context, and public-source metadata controls.
- Public-case evidence bridge tooling now enforces exact-wallet source discipline: 6 public controls remain non-exact, with 0 exact-wallet-supported public cases, 0 named-user local wallet candidates, 2 named-user-only, 2 pattern-level-only, and 2 market-level-only cases.
- Public-case human labeling packet and intake schema now define the only safe path for future exact-wallet public benchmark upgrades. No labels are accepted yet.
- Known-case benchmark maintenance is documented by `docs/inspoly_known_case_benchmark_maintenance_checklist_20260527.md`; future fixture changes should follow that checklist and remain validation-only unless a separate approved runtime/model campaign exists.
- Release Candidate V4 is documented by `docs/inspoly_release_candidate_v4_state_20260527.md` and published for review as draft PR `#1`: https://github.com/ins-poly/InsPoly/pull/1.
- Future push/PR packaging was executed for RC V4 through branch `codex/inspoly-local-release-candidate-v4`; the PR remains draft/not-ready pending review and owner merge approval.
- Remaining donor-derived integration branches have been assessed as sidecar/RFC-only in `docs/inspoly_donor_remaining_three_branch_decision_20260527.md`. Final combined gate: `three_branch_execplan_no_safe_runtime_changes`.
- Indexer/warehouse branch: read-only DB readiness audit tool exists, but live indexing remains `indexer_live_blocked_needs_operator_approval`.
- Sidecar context report/UI branch: current final path remains sidecar-only; pointer-only report metadata is RFC-ready but not approved.
- pUSD/CLOB collateral branch: static unknown-safe semantics helper exists for fixtures only; funding runtime and Phase 3 runtime remain blocked pending verified addresses/source fields and explicit approval.
- Operator approval readiness packets now exist for the three post-donor gates in `docs/inspoly_operator_approval_readiness_campaign_summary_20260527.md`. Final combined gate: `operator_approval_readiness_packets_ready_no_runtime`.
- Bounded live indexer branch: `indexer_bounded_live_approval_packet_ready`; config validation helper exists at `tools/indexer_bounded_live_config_validator.py`, but live ingestion remains operator-gated.
- Bounded live indexer operator run: first approved one-target sidecar probe completed for market slug `russia-x-ukraine-ceasefire-by-january-31-2026`. Gate: `bounded_live_indexer_success_needs_operator_hardening`. The run stored 1 market row, 200 public trade rows, and 2 cursors in local-only `.inspoly_indexer/bounded_live_20260527/indexer.sqlite3`; readiness audit gate was `indexer_sidecar_readiness_ready_no_runtime`.
- Bounded live indexer repeat-run hardening: offline RFC, read-only DB compare tool, readiness re-audit, and self-compare are complete. Gate: `indexer_repeat_run_ready_for_operator_approval`. No second live probe was run; warehouse mode, scheduling, target expansion, report/browser integration, storage schema migration, and production runtime integration remain blocked.
- Bounded live indexer same-slug repeat probe: second approved one-target sidecar probe completed into fresh local-only `.inspoly_indexer/bounded_live_repeat_20260527/indexer.sqlite3`. Gate: `indexer_repeat_probe_success_ready_for_small_multitarget_run`. The repeat run stored 1 market row, 200 public trade rows, and 2 cursors; readiness audit gate was `indexer_sidecar_readiness_ready_no_runtime`; first-vs-repeat fresh DB compare gate was `indexer_sidecar_compare_ready_for_repeat_run` with 0 table, cursor, market identity, trade identity, provider, storage, and market/trade raw-hash drift.
- Bounded live indexer multi-target probe: one approved three-slug sidecar run completed into fresh local-only `.inspoly_indexer/bounded_live_multitarget_20260527/indexer.sqlite3`. Gate: `indexer_multitarget_probe_partial_success_needs_target_hardening`. Two targets stored market rows (`russia-x-ukraine-ceasefire-by-january-31-2026`, `maduro-in-us-custody-by-january-31`); one target failed provider lookup (`us-x-iran-permanent-peace-deal-by`). The DB stored 2 market rows, 200 public trade rows, and 2 cursors; readiness audit gate was `indexer_sidecar_readiness_ready_no_runtime`. Scoped compare is not yet supported, so overlapping-slug drift remains a follow-up before repeat multi-target approval.
- Indexer target hardening/scoped compare: bounded resolver preflight, target registry, scoped DB compare support, and one approved fresh three-target repeat sidecar run are complete. Gate: `indexer_multitarget_hardening_ready_for_repeat_operator_run`. The failed Iran slug was classified as a 15-market event-family mismatch, and `khamenei-out-as-supreme-leader-of-iran-by-february-28` became the selected single-market replacement. The repeat DB stored 3 market rows, 200 public trade rows, and 2 cursors with readiness `indexer_sidecar_readiness_ready_no_runtime`; scoped compare found provider/collection-sampling drift but no storage identity drift. Warehouse/runtime/report integration remains blocked.
- Indexer repeatability/collection hardening: one approved repeat over the exact same three-target set completed into fresh local-only `.inspoly_indexer/bounded_live_multitarget_repeat2_20260527/indexer.sqlite3`. Gate: `indexer_repeatability_needs_collection_hardening`. The repeat2 DB stored 3 market rows, 200 public trade rows, and 2 cursors; readiness was `indexer_sidecar_readiness_ready_no_runtime`; previous hardened DB vs repeat2 scoped compare had zero drift. Public-trade collection remains aggregate-capped and stored all 200 trades on the Khamenei target, so warehouse RFC readiness is `warehouse_rfc_blocked_needs_collection_hardening`.
- Indexer per-target collection hardening: one approved sidecar-only code hardening plus one bounded live probe completed into fresh local-only `.inspoly_indexer/bounded_live_multitarget_per_target_20260527/indexer.sqlite3`. Gate: `indexer_collection_hardening_ready_for_warehouse_rfc_no_runtime`; warehouse readiness is `warehouse_rfc_ready_no_implementation`. The hardened run stored 3 market rows, 180 public trade rows, and 2 cursors, with 60 public trade rows for each approved target, readiness `indexer_sidecar_readiness_ready_no_runtime`, and scoped compare storage risk count 0. Warehouse implementation, production runtime integration, report/browser wiring, storage schema migration, scheduling, and broader live collection remain blocked.
- Indexer warehouse RFC: evidence consolidation, sidecar warehouse RFC, staged implementation plan, risk register, reviewer packet, and decision packet are complete. Gate: `indexer_warehouse_rfc_ready_for_future_w0_implementation`. Only a future W0 no-runtime schema/readiness cleanup campaign is decision-ready; warehouse write commands, production runtime integration, report/browser integration, storage schema migration, scheduling/background mode, and broader live collection remain blocked pending separate approval.
- Indexer warehouse W0 readiness: no-runtime sidecar schema/readiness contracts are complete. Gate: `indexer_warehouse_w0_ready_for_w1_manual_command_rfc`. W0 added pure contract classification, W0 fields in the read-only readiness audit, focused tests, a W0 inventory/readiness report, and a future W1 manual-command approval packet. No warehouse writer, live ingestion, production runtime import, report/browser integration, storage migration, scheduler, scoring/gate/funding/Phase 3 change, CLOB auth/trading, push, or PR was performed.
- Indexer warehouse W1 manual command: a sidecar-only read-only local DB review command is complete. Gate: `indexer_warehouse_w1_manual_command_ready`. The command summarizes existing sidecar DBs, runs readiness/W0 checks, emits compact JSON/optional Markdown, and blocks missing/W0-risk/empty DBs. It reviewed three local sidecar DBs with 5 total market rows, 580 public trade rows, 6 cursors, 0 malformed raw JSON rows, and 0 duplicate indicators; all three returned `ready_for_local_warehouse_review`. No live/network ingestion, warehouse writer/copy path, production import, report/browser integration, storage migration, scheduler, scoring/gate/funding/Phase 3 change, CLOB auth/trading, push, or PR was performed.
- Indexer warehouse W2 registry/retention: a sidecar-only no-network registry and retention policy layer is complete. Gate: `indexer_warehouse_w2_registry_retention_ready`. W2 consumes compact W1 summaries, records 3 local-only DB references, classifies 1 active review candidate and 2 retained references, and defines manual-only cleanup policy. No raw DB was opened or mutated by W2, no artifact was deleted or moved, and no live ingestion, warehouse writer/copy path, production import, report/browser integration, storage migration, scheduler, scoring/gate/funding/Phase 3 change, CLOB auth/trading, push, or PR was performed.
- Indexer warehouse W3 analyst query: a sidecar-only no-network query/read command over compact W2 registry metadata is complete. Gate: `indexer_warehouse_w3_analyst_query_ready`. W3 supports list-runs, summarize-run, aggregate, target-coverage, health, retention-status, and blocked-scopes query modes; the committed query run reported 3 runs, 1 active review candidate, 2 retained references, 5 markets, 580 trades, 6 cursors, 3 covered targets, 0 malformed raw JSON rows, and 0 duplicate indicators. No raw DB was read or mutated, no registry or saved report was mutated, and no live ingestion, warehouse writer/copy path, production import, report/browser integration, storage migration, scheduler, scoring/gate/funding/Phase 3 change, CLOB auth/trading, push, or PR was performed.
- Indexer warehouse W4 report-pointer metadata: pointer-only report metadata is implemented for new reports when an explicit pointer payload is supplied. Gate: `indexer_w4_pointer_metadata_implemented_no_ui_no_metrics`. W4 adds pure validation/normalization in `app/report_pointer.py` and optional absent-by-default report-writer support in scanner, archive, and Event Forensic. The persisted shape is one top-level `indexerWarehousePointer` object with no copied metrics, no row-level sidecar context, no scoring/routing effect, no UI requirement, and no live refresh. No browser UI, storage migration, scoring/gate/funding/Phase 3, saved-report mutation, live/network, DB mutation, scheduler, CLOB auth/trading, push, or PR change was performed.
- Sidecar report-pointer branch: `sidecar_report_pointer_keep_sidecar_only`; a static pointer example exists, but no report writer/browser implementation is approved.
- pUSD/CLOB collateral branch: `pusd_collateral_fixture_grade_sources_added`; official-docs static fixture facts were added, but funding runtime and Phase 3 runtime remain blocked.
- Event Forensic selected-market vs whole-event semantics are explicitly modeled.
- Weak-history near-certainty rows are demoted out of primary Event Forensic review buckets while remaining exported/reviewable.
- Side/Outcome reform Phase 2/4 is stable according to local benchmark/drift audits.

## What Is Partially Solved
- Event Forensic performance improved, but large whole-event runs still depend on wallet-context loading and trade collection costs.
- Replay persistence exists as sidecar tooling, not productized report/storage/browser persistence.
- Phase 3 capital-at-risk has sidecar/source-quality evidence, but runtime implementation remains blocked.
- Funding traces can work with cache/RPC settings, but unavailable traces must remain `unknown`.
- Pagination/truncation has probes and RFCs, but production pagination expansion remains blocked.
- The new indexer readiness audit and collateral semantics helper are sidecar/static support only and are not production runtime integrations.

## What Is Open
- Push/PR publication has happened as draft PR `#1`; merge remains explicit owner-gated.
- Current branch is published as `codex/inspoly-local-release-candidate-v4`; do not push directly to `origin/main`.
- Recommended next path is PR review / CI follow-up, not additional local feature work.
- Whether to include root `AGENTS.md` in a future public repo package remains an explicit user decision; for now it remains local-only.
- Future strategic cycles must use ORIENT -> SELECT -> PLAN -> EXECUTE -> VALIDATE -> RECORD and score candidate campaigns before implementation.
- Known-case benchmark coverage now includes local false-positive controls and six public-source metadata controls. Exact-wallet public-case labels remain at `0`; the 2026-05-27 evidence bridge records compact local refs where available, but none prove wallet identity. Future upgrades require an accepted `public_case_label_intake_v1` label.
- Benchmark maintenance now has an explicit checklist and machine-readable summary; future exact-wallet fixture updates require accepted intake plus a separate fixture update campaign.
- Archive/event pagination completeness needs provider/query proof before runtime changes.
- Further Event Forensic performance work needs measured bottleneck evidence before patches.
- Replay report embedding or storage persistence needs a separate RFC.
- Phase 3 capital-at-risk runtime needs stronger real source-field evidence and explicit product/accounting decisions.
- Live indexer/warehouse work now has an operator approval packet, no-network config validator, manual sidecar runner, bounded run evidence, W0/W1/W2/W3 sidecar warehouse layers, and W4 optional pointer metadata. Scheduling, warehouse service mode, copied report metrics, browser UI panels, storage schema changes, broader live collection, and production scoring/gate use remain blocked.
- Sidecar context report pointers remain product-gated for non-indexer sidecar context; indexer W4 is implemented as pointer-only metadata with no UI and no copied metrics.
- pUSD/CLOB collateral work has fixture-grade official-docs facts for pUSD and selected contracts, but adapter-address reconciliation, tracing semantics, and Phase 3 source-field blockers remain before any funding runtime or Phase 3 runtime changes.
- Legacy Tk retirement or support would need a separate RFC/campaign; current state is freeze/reference-only.

## Validation Baseline
- Use `python3 -m unittest discover -s tests -p 'test_*.py'` for full regression coverage.
- Use `python3 -m py_compile app/*.py tools/*.py tests/*.py` for syntax checks.
- Use targeted audit tools when touching the related area, especially archive visibility, browser offline assets, Event Forensic scope/demotion/performance, side/outcome, funding quality, and replay.
- For strategic/process-only markdown changes, `git diff --check` is the minimum validation; runtime tests are not required unless app behavior changes.
