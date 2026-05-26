# InsPoly Local Release Consolidation And Risk Audit

Date: 2026-05-26

Gate: `local_release_consolidated_ready_for_next_workstream`

Branch: `main`

Base: `origin/main` at `865b858`

Current head: `f9ec8c5`

Push/PR status: deferred by user

## Executive Summary

The local branch now contains 31 commits on top of `origin/main`. The series covers the Side/Outcome reform, Event Forensic weak-history policy, Event Forensic scope semantics, local benchmark/productization work, multiple sidecar systems, Phase 3 capital evidence, Event Forensic replay/performance/pagination campaigns, and final provider-query semantics documentation.

Runtime behavior changed in a bounded set of places:

- Side/Outcome model probability and cluster direction semantics.
- Event Forensic weak-history near-certainty later-win review-bucket demotion.
- Event Forensic scope metadata/report copy.
- Event Forensic performance instrumentation and behavior-preserving scorer/context optimizations.

Everything else is sidecar tooling, fixtures, tests, docs, or compact validation evidence. Phase 3 capital-at-risk runtime normalization remains blocked. Production pagination expansion remains blocked. Push/PR remains blocked by user preference, not by an immediate technical failure.

Latest recorded full suite: 1084 tests OK after `6818b0a`. Later `321bd53` and `f9ec8c5` were sidecar/docs-only and did not require a full-suite rerun.

## Commit Inventory

| Commit | Title | Category | Touched areas | Runtime change | Push status |
| --- | --- | --- | --- | --- | --- |
| `5d55158` | Normalize side/outcome semantics and demote weak-history review rows | runtime behavior | scanner, archive, Event Forensic, browser labels, tests | yes | local only |
| `0d22054` | Add local benchmark and validation tooling for forensic workflows | validation tooling | benchmark corpus, Side/Outcome audits, Event Forensic validation tools | no | local only |
| `3fea696` | Document forensic reform gates and validation evidence | docs/RFC | Side/Outcome and Event Forensic RFCs/reports/manifests | no | local only |
| `ed0431c` | Add static benchmark case schema helpers | sidecar/tooling | static benchmark schema helper, fixtures, tests | no | local only |
| `1c9a9bd` | Add read-only Polymarket protocol and ledger helpers | sidecar/tooling | protocol, ledger, artifact audit fixtures/tests | no | local only |
| `a813951` | Add local indexer sidecar storage and fixture replay | sidecar/tooling | local indexer models/storage/adapters/alerts | no | local only |
| `2a6d11c` | Add shadow context sidecar evaluation helpers | sidecar/tooling | shadow metrics, microstructure, trader-profile sidecars | no | local only |
| `6de3902` | Clarify Event Forensic scope semantics | runtime behavior | Event Forensic report metadata and browser copy | additive only | local only |
| `13d29ba` | Assess Phase 3 capital-at-risk unblock requirements | blocked-evidence work | Phase 3 source inventory, ledger cross-check, docs/tests | no | local only |
| `c7f8ed8` | Expand Phase 3 real SELL capital evidence | blocked-evidence work | real SELL discovery, sensitive review packets, docs/tests | no | local only |
| `df5f5bd` | Add Event Forensic replay snapshot sidecar | sidecar/tooling | replay snapshot helper, performance inventory | no | local only |
| `795f4e4` | Add archive and event completeness audit sidecar | validation tooling | archive/Event completeness audit, pagination RFC seed | no | local only |
| `d678f4c` | Add Event Forensic performance and replay schedule sidecars | sidecar/tooling | performance preflight, replay schedule runner | no | local only |
| `58ac09c` | Add browser asset, timeline, and gamma fallback sidecars | sidecar/tooling | browser offline preflight, timeline template, Gamma monitor | no | local only |
| `47bf594` | Fix bounded performance preflight env handling | validation tooling | measurement preflight env handling | no runtime product change | local only |
| `209fdaf` | Document long-run local completion gates | docs/RFC | long-run completion summary | no | local only |
| `b9702de` | Add local release master index | packaging/index | master commit/gate ledger | no | local only |
| `5a2f0bb` | Run bounded Event Forensic performance precheck | measurement/evidence | bounded measurement precheck and docs | no | local only |
| `dfe965f` | Select bounded Event Forensic performance targets | measurement/evidence | target inventory/resolution, safe-target measurement | no | local only |
| `2552059` | Expand bounded Event Forensic performance measurements | measurement/evidence | measurement expansion, aggregate, subset package | no | local only |
| `3b97fc7` | Run subset Event Forensic performance measurement | measurement/evidence | approved high-density subset measurement | no | local only |
| `ffa8374` | Prepare Event Forensic performance patch RFC | docs/RFC | high-density evidence review, bottleneck decomposition, RFC | no | local only |
| `3bf03ce` | Add behavior-preserving Event Forensic scorer memoization | runtime behavior | Event Forensic scorer input memoization and timing metadata | yes, behavior-preserving | local only |
| `338b559` | Measure Event Forensic post-patch bottlenecks | measurement/evidence | post-patch measurement docs/JSON/tool | no | local only |
| `eae111e` | Add behavior-preserving Event Forensic wallet context cache | runtime behavior | run-local wallet/context cache and metadata | yes, behavior-preserving | local only |
| `5d12334` | Profile Event Forensic scorer context bottlenecks | measurement/evidence | scorer-context profiler metadata and RFC | additive runtime metadata | local only |
| `f181b95` | Optimize Event Forensic scorer context preparation | runtime behavior | prepared scorer context path in scanner/Event Forensic | yes, behavior-preserving | local only |
| `8de1c3a` | Trace Event Forensic wallet API boundary costs | measurement/evidence | wallet API-boundary trace metadata/docs | additive runtime metadata | local only |
| `6818b0a` | Assess Event Forensic pagination impact | measurement/evidence | pagination impact sidecar, bounded deeper collection | no production runtime change | local only |
| `321bd53` | Probe Event Forensic granular pagination behavior | measurement/evidence | one-market granular pagination sidecar and evidence | no production runtime change | local only |
| `f9ec8c5` | Document Event Forensic provider query semantics | docs/RFC | provider/query semantics RFC and operator checklist | no | local only |

## Gate Matrix

| Workstream | Current gate | Evidence | Code commit(s) | Remaining blocker | Next allowed action |
| --- | --- | --- | --- | --- | --- |
| Side/Outcome Phase 2 | stable / complete | `docs/inspoly_side_outcome_phase2_post_migration_stabilization_20260522.md` | `5d55158` | none known | maintain regression tests |
| Side/Outcome Phase 4 | stable / complete | `docs/inspoly_side_outcome_phase4_post_migration_stabilization_20260522.md` | `5d55158` | Phase 3 is separate | maintain cluster-direction tests |
| Event Forensic weak-history demotion | implemented / release-ready | `docs/inspoly_event_forensic_weak_history_review_demotion_release_readiness_20260524.md` | `5d55158` | optional future live recall replay | do not tune scores without new approval |
| Event Forensic scope semantics | implemented | `docs/inspoly_event_forensic_scope_semantics_implementation_20260525.md` | `6de3902` | old reports lack new fields | keep additive metadata and fallback |
| Event Forensic performance/scorer | partial behavior-preserving improvements | scorer memoization and prepared-context docs | `3bf03ce`, `eae111e`, `5d12334`, `f181b95` | total runtime remains variable; wallet/API and pagination dominate some runs | no new runtime patch without fresh profiling/equivalence |
| Event Forensic wallet/API boundary | `api_boundary_no_safe_patch` | `docs/inspoly_event_forensic_wallet_api_boundary_trace_20260526.md` | `8de1c3a` | no exact duplicate API calls; batching needs separate proof | RFC/mock proof only |
| Event Forensic pagination/provider semantics | `provider_query_semantics_rfc_ready_no_runtime_change` | `docs/inspoly_event_forensic_provider_query_semantics_rfc_20260526.md` | `6818b0a`, `321bd53`, `f9ec8c5` | provider/query semantics not proven; no material new rows | one-query micro-probe from checklist if approved |
| Phase 3 capital runtime | blocked | `docs/inspoly_phase3_capital_unblock_decision_20260525.md` | `13d29ba`, `c7f8ed8` | real sensitive SELL evidence, old-report no-op, collateral/max-loss decision | sidecar source-quality work only |
| Benchmark / known-case suite | ready | `docs/inspoly_known_case_benchmark_corpus_20260522.md` | `0d22054`, `ed0431c` | synthetic cases are not production evidence | run before future behavior changes |
| Protocol/ledger sidecars | read-only | ledger/protocol tests and docs | `1c9a9bd` | no production integration approved | sidecar audits only |
| Indexer sidecar | local-only | indexer tests/fixtures | `a813951` | no live indexing/startup integration | fixture replay only |
| Shadow context sidecars | sidecar-only | shadow sidecar tests/docs | `2a6d11c` | no report-copying/scorer integration | offline evaluation only |
| Browser offline assets | `browser_offline_assets_blocked_missing_assets` | `docs/inspoly_browser_offline_asset_plan_20260525.md` | `58ac09c` | local React/ReactDOM/Babel/font assets missing | product decision on vendoring |
| Timeline enrichment | `timeline_template_pack_ready` | `docs/inspoly_timeline_enrichment_template_pack_20260525.md` | `58ac09c` | needs human curated rows | curate CSV, then validate |
| Gamma fallback monitor | `gamma_fallback_monitor_ready` | `docs/inspoly_gamma_fallback_drift_monitor_20260525.md` | `58ac09c` | optional live drift check | bounded shape check if approved |
| Push/PR/release | deferred by user | this report and prior packaging docs | all commits | user decision on grouping and local-only artifacts | explicit push/PR instruction only |

## Runtime Change Audit

### `app/side_outcome.py`

Behavior: shared normalization for raw token vs economic-side probability and cluster direction.

Preserved invariants: raw side/outcome/token price remain available; Phase 3 capital is untouched.

Tests: Side/Outcome normalization, Phase 2 model contract, Phase 4 cluster direction, known-case benchmark.

Risk: future callers can misuse economic probability as raw token price. Keep label/display tests.

### `app/scanner.py`

Behavior: uses Side/Outcome Phase 2/4 semantics; supports optional prepared scorer context without changing default `_score_trade()` semantics.

Preserved invariants: weights, thresholds, Strong Risk/HER/funding/candidate gates, and Phase 3 behavior are unchanged.

Tests: scanner patterns, cross-mode scoring contract, Side/Outcome tests, scorer-context optimization tests.

Risk: prepared-context path must stay equivalent to default scoring path.

### `app/archive_scanner.py`

Behavior: archive rows expose additive Side/Outcome-compatible fields and preserve old report compatibility.

Preserved invariants: storage schema and visibility policy unchanged.

Tests: archive evidence, archive visibility, browser label snapshot, cross-mode contract.

Risk: old archive rows can lack new additive fields; loaders must stay absent-safe.

### `app/event_forensic.py`

Behavior changes:

- Side/Outcome Phase 2/4 semantics in Event Forensic rows.
- Weak-history near-certainty later-winning rows demoted to review-required.
- Additive scope semantics metadata.
- Behavior-preserving scorer memoization, wallet/context cache, scorer-context preparation, and trace metadata.
- Pagination warnings remain monitor-only; no production pagination expansion.

Preserved invariants: candidate admission, scoring weights/thresholds, review row visibility, exports, direct gates, Phase 3, storage, UI sorting/filtering.

Tests: weak-history demotion, policy simulation, scope semantics, performance equivalence/contract tests, known-case benchmark, cross-mode scoring.

Risk: future performance edits could accidentally change candidate identity, score values, rank order, review buckets, weak-history demotion, or exports. Keep equivalence harness mandatory.

### Browser files

Files: `app/browser_ui.html`, `app/browser_event_forensic_ui.html`, `app/browser_desktop.py`.

Behavior: label/copy compatibility and additive Event Forensic scope/weak-history display. No sorting/filtering redesign.

Tests: browser label snapshot, scope semantics, offline asset preflight.

Risk: runtime CDN assets remain missing locally for full offline operation.

### Runtime-adjacent helpers

Files: `app/event_forensic_performance.py`, `app/event_forensic_replay.py`, `app/benchmark_cases.py`, `app/polymarket_protocol.py`, `app/polymarket_ledger.py`, `app/indexer/*`, `app/shadow_metrics.py`, `app/microstructure_context.py`, `app/trader_profile_context.py`.

Behavior: helper/sidecar modules. Only `app/event_forensic_performance.py` is used by Event Forensic runtime; the rest are local sidecars or test/support helpers unless explicitly imported by a campaign.

Risk: do not silently integrate sidecars into production scanner/archive/Event Forensic paths.

## Sidecar And Tooling Audit

Committed and useful:

- Known-case benchmark and benchmark schema helpers.
- Side/Outcome impact, archive evidence, drift, Phase 3, and cluster audits.
- Event Forensic weak-history validation, policy simulation, performance, replay, pagination, and query-strategy tools.
- Protocol/ledger, indexer, and shadow context sidecars.
- Browser offline asset, timeline enrichment, and Gamma fallback monitors.

Local-only generated evidence:

- Large raw live output directories under `validation_outputs/`.
- Generated `shadow_review_packets/` and `side_outcome_review_packets/`.
- `PROJECT_MEMORY.md`.

Candidate future cleanup, only with user approval:

- old release manifests that were superseded by later packaging reports;
- local-only raw live bundles once the owner confirms they are no longer needed;
- generated review packets if they are too noisy for local work.

Needs README/index link:

- the 2026-05-26 consolidation report should be treated as the current map; the 2025 master index is historical and now has a 2026-05-26 addendum.

## Local Worktree Hygiene

Visible untracked buckets:

| Bucket | Count / size observed | Classification | Recommendation |
| --- | ---: | --- | --- |
| `release_manifests/` untracked sidecar/old manifests | 12 files | local packaging metadata | keep local unless user asks to publish packaging metadata |
| `shadow_review_packets/` | 58 files | generated review packets | keep local; do not stage by default |
| `side_outcome_review_packets/` | 7 files | generated review packets | keep local; do not stage by default |
| ignored `validation_outputs/` | 600 untracked/ignored files, about 5.4 GB | bulky generated evidence | keep local; commit only compact explicit summaries |
| `PROJECT_MEMORY.md` | local working memory | local-only policy | update after tasks, do not stage |

No deletion or cleanup was performed.

## Documentation Consistency Check

The prior 2025 master index is stale because it stops at `209fdaf` / 16 commits. This is not a contradiction in historical context, but it is no longer the current state. The new current-state source is this report plus `validation_outputs/inspoly_local_release_consolidation_20260526.json`.

No major gate contradiction requiring runtime/doc rewrites was found. The current state is:

- Event Forensic performance has partial behavior-preserving improvements, not closure.
- Pagination has provider/query RFC readiness, not runtime expansion readiness.
- Phase 3 remains sidecar-only / blocked for runtime.
- Push/PR remains deferred.

## Eventual Push/PR Preparation

Before any push/PR:

1. Decide whether to push all 31 commits or split into PRs.
2. Keep `PROJECT_MEMORY.md`, generated review packets, bulky raw live outputs, and local-only manifests out unless explicitly approved.
3. Rerun at least targeted suites for runtime commits; rerun full suite if new runtime changes occur after this report.
4. Prepare PR notes that separate runtime behavior changes from sidecar/docs/evidence commits.
5. Call out blocked gates prominently: Phase 3 runtime, pagination runtime expansion, browser offline assets, and push/PR grouping.

Suggested PR grouping:

- Runtime/Product: `5d55158`, `6de3902`, `3bf03ce`, `eae111e`, `5d12334`, `f181b95`, `8de1c3a`.
- Validation/Benchmark/Evidence: `0d22054`, `ed0431c`, `13d29ba`, `c7f8ed8`, performance/pagination measurement commits.
- Sidecars: protocol/ledger, indexer, shadow, replay, browser/timeline/gamma sidecars.
- Docs/RFC/Packaging: docs and consolidation commits.

## Remaining Strategic Workstreams

1. Provider/query micro-probe.
   - Use `docs/inspoly_event_forensic_query_strategy_operator_checklist_20260526.md`.
   - One market, one query strategy, compact sidecar output only.
   - Stop if no material new rows.

2. Phase 3 capital source-quality expansion.
   - Find real sensitive SELL rows with direct fields.
   - Keep runtime blocked.

3. Browser offline asset decision.
   - Product decision on vendoring/local runtime assets.
   - No UI redesign or sorting/filtering change.

4. Replay persistence productization.
   - Sidecar replay snapshots are ready.
   - Storage-backed scheduling still needs RFC/approval.

5. Push/PR packaging.
   - User-gated.
   - Keep local-only artifacts out by default.

## Final Decision

Gate: `local_release_consolidated_ready_for_next_workstream`.

No code/runtime changes were made in this consolidation. The repository is ready for the next strategic local workstream or for a user decision on push/PR grouping.
