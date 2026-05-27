# Current State

Last updated: 2026-05-27 EEST.

## Repository State
- Branch inspected: `main`.
- Latest release-candidate commit verified: `ad27400 Verify local release candidate state`.
- Latest Release Candidate V3 head verified: `2dd851f Freeze legacy Tk UI as reference-only`.
- Latest future push/PR packaging dry-run base inspected: `fd12c0b Add release candidate V3 strategic state`.
- Latest known-case maintenance base commit inspected: `90e2434 Add public-case human labeling packet`.
- Latest pre-push dry-run commit inspected: `05d688d Add final pre-push packaging dry run`.
- Latest runtime-affecting commit inspected: `0ce05da Add local browser offline runtime assets`.
- Current release-candidate gate: `local_release_candidate_verified`.
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
- The `strategic-autonomy-review` skill exists in `skills/strategic-autonomy-review/` and `/Users/Root1/.codex/skills/strategic-autonomy-review/`.
- The test suite has broad local regression coverage compared with early project state; Release Candidate V3 full unittest discovery passed 1122 tests at `2dd851f`.
- The known-case benchmark has been expanded to `known_case_benchmark_v3` with 30 compact cases, including false-positive, sidecar-context, and public-source metadata controls.
- Public-case evidence bridge tooling now enforces exact-wallet source discipline: 6 public controls remain non-exact, with 0 exact-wallet-supported public cases, 0 named-user local wallet candidates, 2 named-user-only, 2 pattern-level-only, and 2 market-level-only cases.
- Public-case human labeling packet and intake schema now define the only safe path for future exact-wallet public benchmark upgrades. No labels are accepted yet.
- Known-case benchmark maintenance is documented by `docs/inspoly_known_case_benchmark_maintenance_checklist_20260527.md`; future fixture changes should follow that checklist and remain validation-only unless a separate approved runtime/model campaign exists.
- Release Candidate V3 is documented by `docs/inspoly_release_candidate_v3_state_20260527.md` and future push preparation by `docs/inspoly_future_push_pr_checklist_v3_20260527.md`.
- Future push/PR packaging has a dry-run kit: `docs/inspoly_future_pr_draft_20260527.md`, `docs/inspoly_reviewer_risk_map_v3_20260527.md`, `docs/inspoly_push_approval_checklist_v3_20260527.md`, and `validation_outputs/inspoly_future_push_pr_packaging_dry_run_20260527.json`.
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
- Push/PR/release grouping requires explicit operator decision.
- Current branch is locally verified at V3 but still push/PR user-gated.
- Recommended future publication path is an owner-approved draft PR branch `codex/inspoly-local-release-candidate-v3` from current local `main`; no branch or push has been created.
- Whether to include root `AGENTS.md` in a future public repo package remains an explicit user decision; for now it remains local-only.
- Future strategic cycles must use ORIENT -> SELECT -> PLAN -> EXECUTE -> VALIDATE -> RECORD and score candidate campaigns before implementation.
- Known-case benchmark coverage now includes local false-positive controls and six public-source metadata controls. Exact-wallet public-case labels remain at `0`; the 2026-05-27 evidence bridge records compact local refs where available, but none prove wallet identity. Future upgrades require an accepted `public_case_label_intake_v1` label.
- Benchmark maintenance now has an explicit checklist and machine-readable summary; future exact-wallet fixture updates require accepted intake plus a separate fixture update campaign.
- Archive/event pagination completeness needs provider/query proof before runtime changes.
- Further Event Forensic performance work needs measured bottleneck evidence before patches.
- Replay report embedding or storage persistence needs a separate RFC.
- Phase 3 capital-at-risk runtime needs stronger real source-field evidence and explicit product/accounting decisions.
- Live indexer/warehouse work now has an operator approval packet, no-network config validator, manual sidecar runner, one successful bounded probe, repeat-run hardening RFC/compare tool, one clean same-slug fresh-DB repeat probe, and one partial multi-target probe. Target hardening and scoped compare support are needed before repeat multi-target approval; scheduling, warehouse mode, production integration, report/UI wiring, storage schema changes, and broader target expansion remain blocked.
- Sidecar context report pointers remain product-gated; current decision is keep sidecar-only unless a future pointer-only RFC is approved.
- pUSD/CLOB collateral work has fixture-grade official-docs facts for pUSD and selected contracts, but adapter-address reconciliation, tracing semantics, and Phase 3 source-field blockers remain before any funding runtime or Phase 3 runtime changes.
- Legacy Tk retirement or support would need a separate RFC/campaign; current state is freeze/reference-only.

## Validation Baseline
- Use `python3 -m unittest discover -s tests -p 'test_*.py'` for full regression coverage.
- Use `python3 -m py_compile app/*.py tools/*.py tests/*.py` for syntax checks.
- Use targeted audit tools when touching the related area, especially archive visibility, browser offline assets, Event Forensic scope/demotion/performance, side/outcome, funding quality, and replay.
- For strategic/process-only markdown changes, `git diff --check` is the minimum validation; runtime tests are not required unless app behavior changes.
