# InsPoly Local Release Master Index

Date: 2026-05-25

Gate: `local_release_index_ready`

This is the master map for the local InsPoly reform series after the Side/Outcome, Event Forensic, donor-sidecar, Phase 3 evidence, replay/performance, archive completeness, browser asset, timeline, and Gamma fallback campaigns.

No push or PR has been performed. `PROJECT_MEMORY.md` remains local-only and must not be staged unless the owner explicitly changes that policy.

## Executive Summary

The local branch contains 16 reform/checkpoint commits on top of `origin/main`:

- 1 behavioral runtime commit for Side/Outcome model semantics and Event Forensic weak-history review-bucket demotion.
- 1 benchmark/validation tooling commit.
- 1 docs/RFC/reports/manifests commit.
- 4 sidecar checkpoint commits.
- 1 Event Forensic scope semantics product-metadata commit.
- 2 Phase 3 capital-at-risk evidence commits.
- 1 Event Forensic replay snapshot sidecar commit.
- 5 long-run completion commits covering archive completeness, pagination planning, performance preflight, replay scheduling, browser asset preflight, timeline template, Gamma fallback monitor, and final summary.

Latest recorded full suite: `1004 tests OK`.

Current policy:

- ready for future push/PR review after owner decision;
- generated evidence and review packets stay local by default;
- `PROJECT_MEMORY.md` stays local-only;
- remaining work is approval-gated, not automatic.

## Commit Ledger

| Commit | Title | Category | Runtime behavior changed | Tests / checks mentioned | Push status | Risk | Rollback note |
|---|---|---|---|---|---|---|---|
| `5d55158` | Normalize side/outcome semantics and demote weak-history review rows | runtime | yes | Side/Outcome, Event Forensic demotion, cross-mode scoring, scanner/browser compatibility | local only | medium | Revert commit to restore raw-token model semantics and pre-demotion Event Forensic review placement. |
| `0d22054` | Add local benchmark and validation tooling for forensic workflows | validation tooling | no | Known-case benchmark, side/outcome audits, Event Forensic validation/policy tools | local only | low | Revert sidecar tooling/tests; no saved-report or storage rollback needed. |
| `3fea696` | Document forensic reform gates and validation evidence | docs/RFC | no | Docs/manifests whitespace and staged-set checks | local only | low | Revert docs/manifests only. |
| `ed0431c` | Add static benchmark case schema helpers | sidecar helper | no | Benchmark schema compatibility tests, py_compile | local only | low | Revert benchmark schema helper/fixtures/tests. |
| `1c9a9bd` | Add read-only Polymarket protocol and ledger helpers | sidecar helper | no | Protocol/ledger/artifact audit tests, import isolation | local only | low | Revert protocol/ledger helpers, fixtures, and tests; no production dependency exists. |
| `a813951` | Add local indexer sidecar storage and fixture replay | sidecar helper | no | Indexer/alerts/storage/fixture dry-run tests, import isolation | local only | low | Revert indexer sidecar package and tests; no startup or production integration exists. |
| `2a6d11c` | Add shadow context sidecar evaluation helpers | sidecar helper | no | Shadow/profile/microstructure tests, force-added stable fixtures, import isolation | local only | low | Revert sidecar helpers/tools/fixtures/tests; report-copying remains blocked. |
| `6de3902` | Clarify Event Forensic scope semantics | product semantics | yes, additive report/UI metadata only | Event Forensic scope semantics tests, browser copy checks, full suite 954 OK | local only | low-medium | Revert additive scope metadata/browser copy and audit tool; no storage migration. |
| `13d29ba` | Assess Phase 3 capital-at-risk unblock requirements | blocked-evidence work | no | Phase 3 unblock, ledger/protocol, known-case, Side/Outcome, Event Forensic, full suite 962 OK | local only | low | Revert Phase 3 source inventory/cross-check/audit docs/tools/outputs. |
| `c7f8ed8` | Expand Phase 3 real SELL capital evidence | blocked-evidence work | no | Phase 3 real SELL evidence tests, focused suites, full suite 969 OK | local only | low | Revert discovery/review packet tooling and explicit evidence outputs. |
| `df5f5bd` | Add Event Forensic replay snapshot sidecar | sidecar helper | no | Performance inventory and replay snapshot tests, full suite 980 OK | local only | low | Revert replay snapshot helper/performance inventory/docs/output. |
| `795f4e4` | Add archive and event completeness audit sidecar | validation tooling | no | Archive/Event completeness audit tests, diff check | local only | low | Revert completeness audit tool/test/docs/output. |
| `d678f4c` | Add Event Forensic performance and replay schedule sidecars | sidecar helper | no | Bounded performance preflight and replay schedule tests | local only | low | Revert performance preflight and replay schedule sidecars/docs/outputs. |
| `58ac09c` | Add browser asset, timeline, and gamma fallback sidecars | sidecar helper | no | Browser asset, timeline template, Gamma fallback monitor tests | local only | low | Revert sidecar tools/tests/fixture/docs/outputs. |
| `47bf594` | Fix bounded performance preflight env handling | validation tooling | no | Full suite caught and re-test fixed explicit empty-env handling | local only | low | Revert one-line env handling fix if preflight policy changes. |
| `209fdaf` | Document long-run local completion gates | final summary | no | JSON validation, diff check, full suite state recorded | local only | low | Revert final summary docs/output only. |

## Gate Ledger

| Gate | Status | Evidence | Next allowed action | Blocked action |
|---|---|---|---|---|
| Side/Outcome Phase 2 | stable / complete | `docs/inspoly_side_outcome_phase2_post_migration_stabilization_20260522.md` | maintain regression tests | changing weights/thresholds without new approval |
| Side/Outcome Phase 4 | stable / complete | `docs/inspoly_side_outcome_phase4_post_migration_stabilization_20260522.md` | maintain cluster-direction contract | Phase 3 capital migration |
| Phase 3 capital runtime | blocked | `docs/inspoly_phase3_capital_unblock_decision_20260525.md` | sidecar source-quality evidence only | scanner/archive/Event Forensic capital runtime migration |
| Phase 3 sidecar/source quality | partial safe sidecar only | `docs/inspoly_phase3_real_sell_evidence_expansion_20260525.md` | find more real sensitive SELL evidence | treating old notional-only rows as max loss |
| Event Forensic weak-history demotion | implemented / release-ready | `docs/inspoly_event_forensic_weak_history_review_demotion_release_readiness_20260524.md` | replay affected cases when desired | scorer tuning or direct gate changes |
| Event Forensic scope semantics | implemented | `docs/inspoly_event_forensic_scope_semantics_implementation_20260525.md` | generate new reports with additive scope metadata | mutating old reports or broadening selected-market scope |
| Benchmark Suite V2 | ready | `docs/inspoly_known_case_benchmark_corpus_20260522.md`, `0d22054`, `ed0431c` | use for local regression | treating synthetic cases as production evidence |
| Protocol/ledger sidecars | read-only | `1c9a9bd`, protocol/ledger tests | use in sidecar audits | CLOB auth, trading, private keys, production integration |
| Indexer sidecar | local-only | `a813951` | fixture replay / local SQLite sidecar | live indexing, startup integration, Postgres/Redis requirement |
| Shadow context sidecar | sidecar-only | `2a6d11c`, Phase 9-12 docs | sidecar preview/evaluation | report-copying or scorer integration |
| Replay snapshot sidecar | ready | `docs/inspoly_event_forensic_performance_and_replay_decision_20260525.md` | build snapshots from saved reports | automatic storage-backed replay without RFC |
| Archive/Event completeness | local-ready | `docs/inspoly_archive_event_completeness_audit_20260525.md` | use local audit output; plan bounded measurement | broad live pagination crawler |
| Pagination | operator plan required | `docs/inspoly_archive_event_pagination_operator_plan_20260525.md` | one bounded operator-approved measurement | changing candidate admission/ranking via pagination patch |
| Whole-event performance measurement | blocked missing env / needs bounded live | `docs/inspoly_event_forensic_bounded_performance_measurement_20260525.md` | provide read-only env and exact target | runtime optimization without measurement |
| Browser offline assets | blocked missing assets / product decision | `docs/inspoly_browser_offline_asset_plan_20260525.md` | decide whether to vendor/localize assets | UI redesign or sorting/filtering changes |
| Timeline enrichment | template ready / needs human curation | `docs/inspoly_timeline_enrichment_template_pack_20260525.md` | human-curated CSV rows and validation | web feeds or inferred timestamps |
| Gamma fallback monitor | ready / optional live drift check | `docs/inspoly_gamma_fallback_drift_monitor_20260525.md` | run optional bounded live shape check later | removing fallback before replacement is proven |
| Push/PR | deferred by user | this index, packaging completion docs | owner decides push/PR grouping | automatic push/PR |

## Source Tree Map

### Runtime Files Changed

- `app/side_outcome.py` - shared raw-token/economic-side normalization and cluster direction helpers.
- `app/scanner.py` - approved Phase 2 model probability semantics and Phase 4 cluster direction usage; raw fields preserved.
- `app/archive_scanner.py` - approved additive Side/Outcome fields and archive semantics; old fields preserved.
- `app/event_forensic.py` - approved Side/Outcome semantics, weak-history review-bucket demotion, and additive scope metadata.
- `app/browser_ui.html` - display label compatibility for Token price vs Economic probability.
- `app/browser_event_forensic_ui.html` - Event Forensic display labels, demotion/context fields, and scope semantics copy.

### App Sidecar / Helper Files Added

- `app/benchmark_cases.py`
- `app/polymarket_protocol.py`
- `app/polymarket_ledger.py`
- `app/event_forensic_replay.py`
- `app/indexer/*`
- `app/shadow_metrics.py`
- `app/microstructure_context.py`
- `app/trader_profile_context.py`

These are not production scanner/archive/Event Forensic integrations unless explicitly documented by a runtime commit.

### Tools Added

Major tool families:

- Side/Outcome audits: Phase 2 impact, archive evidence, Phase 3 capital, Phase 4 cluster, drift, known-case benchmark.
- Event Forensic validation: weak-history saved-report/live validation, policy simulation, review-demotion checks, scope semantics audit, performance inventory, bounded measurement preflight, replay schedule runner.
- Protocol/ledger: Polymarket protocol semantics, ledger/PnL artifact audit, reconstruction validators.
- Indexer: fixture dry-run and local storage/adapters/health/alerts.
- Shadow context: normalization, evaluation, dashboard/review packet rendering, microstructure/profile context.
- Completion monitors: archive/Event completeness audit, browser offline asset preflight, timeline enrichment template, Gamma fallback drift monitor.

### Tests And Fixtures Added

- Side/Outcome Phase 1/2/3/4 contract and audit tests.
- Event Forensic weak-history demotion, policy simulation, scope semantics, replay snapshot, performance inventory, replay schedule tests.
- Known-case benchmark corpus and benchmark schema fixtures.
- Polymarket protocol/ledger fixtures and tests.
- Indexer fixtures and tests.
- Shadow context fixtures and tests.
- Gamma fallback `__NEXT_DATA__` fixture.

### Docs Added

- Side/Outcome RFCs, audit reports, runtime migration/stabilization/release-readiness docs.
- Event Forensic weak-history validation/policy/implementation/release-readiness docs.
- Event Forensic scope semantics product contract and implementation docs.
- Phase 3 capital formula/source-quality/unblock/real-evidence docs.
- Performance/replay persistence contracts, decisions, and operator plans.
- Archive/Event completeness and pagination strategy/operator docs.
- Browser offline asset, timeline enrichment, Gamma fallback, and long-run completion docs.
- Packaging strategy, completion, sidecar checkpoint, and this master index.

### Validation Outputs Added

Small committed JSON/CSV outputs exist under `validation_outputs/` for specific audit/report summaries. Bulky generated evidence and review packets remain local-only by default.

### Manifests Added

Packaging manifests exist under `release_manifests/`. Some were committed as part of `3fea696`; remaining visible sidecar/old manifests are local-only unless the owner asks to publish packaging metadata.

## Local-Only Inventory

Current visible untracked/local-only files:

| Path | Classification | Default action | Notes |
|---|---|---|---|
| `PROJECT_MEMORY.md` | local working memory | keep local | Ignored/local-only by policy; updated after tasks, not committed. |
| `release_manifests/side_outcome_reform_*.txt` | old release manifests | keep local | Superseded by later packaging docs; do not delete without user request. |
| `release_manifests/sidecar_checkpoint_summary_20260525.json` | sidecar packaging metadata | optional future commit | Already summarized in sidecar completion docs. |
| `release_manifests/sidecar_commit_*.txt` | sidecar staging manifests | optional future commit | Useful locally, not required for runtime release. |
| `release_manifests/sidecar_force_add_required_20260525.txt` | sidecar staging manifest | optional future commit | Keep local unless publishing checkpoint metadata. |
| `release_manifests/sidecar_local_only_do_not_stage_20260525.txt` | local-only policy manifest | keep local | Reinforces do-not-stage policy. |
| `release_manifests/sidecar_optional_generated_evidence_20260525.txt` | optional evidence manifest | keep local | Do not stage generated evidence by default. |
| `release_manifests/sidecar_verification_commands_20260525.md` | verification command manifest | optional future commit | Useful if publishing packaging metadata. |
| `shadow_review_packets/` | generated review packets | keep local | Generated/noisy; user decision required before any commit. |
| `side_outcome_review_packets/` | generated review packets | keep local | Generated/noisy; user decision required before any commit. |

Default deletion policy: do not delete any of these without explicit user instruction.

## Push / PR Readiness

Current branch: `main`, ahead of `origin/main` by the local reform series.

Push is deferred because the user explicitly requested local completion first. The committed series is ready for future review, but a push/PR should be a separate owner decision.

Before eventual push:

1. Decide whether to push all 16 local commits or split into PRs.
2. Keep generated review packets and `PROJECT_MEMORY.md` out by default.
3. Decide whether remaining local manifests belong in a packaging-metadata commit or should stay local.
4. Optionally rerun targeted tests or full suite if any new changes occur after this index.

Suggested future PR grouping:

1. Runtime/Product: `5d55158` and `6de3902`.
2. Validation and Benchmarking: `0d22054`, `ed0431c`, Phase 3 evidence commits, and completion/audit tools.
3. Sidecars: protocol/ledger, indexer, shadow context, replay/performance, archive completeness, browser/timeline/gamma sidecars.
4. Docs/RFC/Reports: `3fea696`, summaries, and master index.

If the owner wants one large PR, keep the commit history intact and call out blocked gates prominently.

## Remaining Strategic Work

1. Bounded live performance/pagination measurement
   - Why it matters: whole-event runs can be expensive and some reports are explicitly truncated.
   - Approval: operator/live/RPC approval with exact target and bounds.
   - Allowed scope: measurement-only, max one event/eight markets/30 minutes unless changed by user.
   - Stop conditions: rate limits, scope expansion, scorer/gate/storage/UI changes.
   - Type: operator-gated.

2. Browser offline asset vendoring decision
   - Why it matters: browser UI boot depends on CDN React/ReactDOM/Babel/fonts.
   - Approval: product/user decision to vendor or provide local assets.
   - Allowed scope: asset loading only, no redesign or sorting/filtering changes.
   - Stop conditions: missing exact assets, UI behavior drift, broad redesign.
   - Type: product-gated.

3. Phase 3 capital runtime evidence/RFC
   - Why it matters: capital-at-risk remains unsafe for old notional-only and sensitive-overlap rows.
   - Approval: separate runtime RFC and explicit implementation approval.
   - Allowed scope now: sidecar-only evidence expansion and source-quality analysis.
   - Stop conditions: direct `_score_trade()` / `_event_forensic_score()` capital changes, gate drift, old-report reinterpretation.
   - Type: product and evidence gated.

4. Optional Gamma live drift check
   - Why it matters: fallback depends on Polymarket frontend `__NEXT_DATA__` shape.
   - Approval: bounded live web/API check approval.
   - Allowed scope: shape validation only.
   - Stop conditions: resolver behavior changes or broad crawling.
   - Type: operator-gated.

5. Timeline human curation
   - Why it matters: public-lag/event-timeline evidence remains template-only.
   - Approval: human curator data and validation approval.
   - Allowed scope: curated CSV rows with source URL/timestamp/catalyst.
   - Stop conditions: inferred timestamps, external feeds, scorer/gate changes.
   - Type: product/human-data gated.

6. Push/PR
   - Why it matters: local work is not yet on remote.
   - Approval: explicit push/PR instruction.
   - Allowed scope: push reviewed commit series; do not add local-only files automatically.
   - Stop conditions: unreviewed generated evidence, `PROJECT_MEMORY.md`, review packets, or accidental broad staging.
   - Type: user-gated.

## Directions Not To Repeat

- Do not redo Side/Outcome Phase 2 or Phase 4 readiness/runtime migrations; they are stable and covered by tests.
- Do not redo Event Forensic weak-history policy selection; product-approved demotion is implemented.
- Do not repackage the sidecar checkpoint unless new files appear; it has already been committed.
- Do not rerun full packaging classification unless the worktree materially changes.
- Do not create another Phase 3 runtime RFC until real sensitive SELL evidence and old-report no-op requirements improve.

## Verification State

- Latest full suite recorded: `1004 tests OK`.
- Current cached area was empty before this index was created.
- This index campaign changes docs/JSON only; no full suite is required unless runtime/tests change.

## Rollback Notes

- Runtime rollback: revert `5d55158` and/or `6de3902` depending on whether reverting model semantics or scope metadata.
- Sidecar rollback: revert the relevant sidecar commit; no storage or saved-report rollback should be needed.
- Docs/evidence rollback: revert docs/JSON commits only.
- Keep local-only artifacts untouched unless the owner explicitly asks for cleanup.
