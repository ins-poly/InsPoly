# InsPoly Final Pre-Push Packaging Dry Run

Date: 2026-05-26

Branch: `main`

Base: `origin/main` at `865b858`

Current head before this dry run: `0ce05da` - `Add local browser offline runtime assets`

Local reform commits reviewed: `39`

Gate decision: `pre_push_dry_run_ready`

Runtime changed in this campaign: `false`

Push/PR performed: `false`

## Executive Summary

This dry run reviewed the full local reform series after strict offline browser assets were implemented. The branch is locally ahead of `origin/main` by 39 commits and is packaging-ready for a future owner-approved push/PR pass, subject to a fresh pre-push test run and careful staging.

The current release state is:

- Side/Outcome Phase 2/4 runtime semantics are implemented and stable.
- Event Forensic weak-history demotion and scope semantics are implemented.
- Event Forensic performance improvements are behavior-preserving and measured, but further optimization is evidence-gated.
- Event Forensic wallet/API and pagination/provider expansion remain blocked for production runtime.
- Phase 3 capital-at-risk runtime is blocked until new source fields or stronger direct sensitive SELL evidence exists.
- Replay persistence is final as sidecar-only for the current product state.
- Browser strict offline boot is ready with pinned local React, ReactDOM, and Babel assets.
- Push/PR remains explicitly user-gated.

No runtime code, scoring/model logic, gates, storage schema, UI sorting/filtering, saved artifacts, generated review packets, or local-only manifests were changed by this dry-run campaign.

## Commit Inventory

| # | Commit | Title | Category | Touched areas | Push relevance | Risk |
|---:|---|---|---|---|---|---|
| 1 | `5d55158` | Normalize side/outcome semantics and demote weak-history review rows | runtime | scanner, archive, Event Forensic, browser labels | core runtime | medium |
| 2 | `0d22054` | Add local benchmark and validation tooling for forensic workflows | sidecar/tooling | benchmark and validation tools | support | low |
| 3 | `3fea696` | Document forensic reform gates and validation evidence | docs/RFC | reform docs and manifests | support | low |
| 4 | `ed0431c` | Add static benchmark case schema helpers | sidecar/tooling | benchmark schema helpers and fixtures | support | low |
| 5 | `1c9a9bd` | Add read-only Polymarket protocol and ledger helpers | sidecar/tooling | protocol/ledger helpers | support | low |
| 6 | `a813951` | Add local indexer sidecar storage and fixture replay | sidecar/tooling | indexer sidecar | optional sidecar | low |
| 7 | `2a6d11c` | Add shadow context sidecar evaluation helpers | sidecar/tooling | shadow metrics/context helpers | optional sidecar | low |
| 8 | `6de3902` | Clarify Event Forensic scope semantics | runtime | Event Forensic metadata/UI copy | core runtime | low-medium |
| 9 | `13d29ba` | Assess Phase 3 capital-at-risk unblock requirements | evidence/measurement | Phase 3 source inventory and audit | support | low |
| 10 | `c7f8ed8` | Expand Phase 3 real SELL capital evidence | evidence/measurement | real SELL evidence tools/docs | support | low |
| 11 | `df5f5bd` | Add Event Forensic replay snapshot sidecar | sidecar/tooling | replay snapshot helper | support | low |
| 12 | `795f4e4` | Add archive and event completeness audit sidecar | sidecar/tooling | completeness audit | support | low |
| 13 | `d678f4c` | Add Event Forensic performance and replay schedule sidecars | sidecar/tooling | performance/replay schedule tools | support | low |
| 14 | `58ac09c` | Add browser asset, timeline, and gamma fallback sidecars | sidecar/tooling | browser/timeline/gamma monitors | support | low |
| 15 | `47bf594` | Fix bounded performance preflight env handling | sidecar/tooling | measurement preflight | support | low |
| 16 | `209fdaf` | Document long-run local completion gates | docs/RFC | long-run summary | support | low |
| 17 | `b9702de` | Add local release master index | release index | master index | support | low |
| 18 | `5a2f0bb` | Run bounded Event Forensic performance precheck | evidence/measurement | performance precheck | support | low |
| 19 | `dfe965f` | Select bounded Event Forensic performance targets | evidence/measurement | target resolution/selection | support | low |
| 20 | `2552059` | Expand bounded Event Forensic performance measurements | evidence/measurement | performance expansion | support | low |
| 21 | `3b97fc7` | Run subset Event Forensic performance measurement | evidence/measurement | subset measurement | support | low |
| 22 | `ffa8374` | Prepare Event Forensic performance patch RFC | docs/RFC | performance RFC/contracts | support | low |
| 23 | `3bf03ce` | Add behavior-preserving Event Forensic scorer memoization | runtime | Event Forensic scorer memoization | core runtime | medium |
| 24 | `338b559` | Measure Event Forensic post-patch bottlenecks | evidence/measurement | post-patch measurement | support | low |
| 25 | `eae111e` | Add behavior-preserving Event Forensic wallet context cache | runtime | run-local wallet/context cache | core runtime | medium |
| 26 | `5d12334` | Profile Event Forensic scorer context bottlenecks | evidence/measurement | scorer-context profiling | support | low-medium |
| 27 | `f181b95` | Optimize Event Forensic scorer context preparation | runtime | scorer context preparation | core runtime | medium |
| 28 | `8de1c3a` | Trace Event Forensic wallet API boundary costs | evidence/measurement | API-boundary trace metadata | support | low-medium |
| 29 | `6818b0a` | Assess Event Forensic pagination impact | evidence/measurement | pagination sidecar collection | support | low |
| 30 | `321bd53` | Probe Event Forensic granular pagination behavior | evidence/measurement | granular pagination probe | support | low |
| 31 | `f9ec8c5` | Document Event Forensic provider query semantics | docs/RFC | provider/query RFC and checklist | support | low |
| 32 | `36f6ee6` | Add local release consolidation audit | release index | consolidation report | support | low |
| 33 | `8d687c9` | Review Phase 3 capital runtime readiness | docs/RFC | Phase 3 final evidence review | support | low |
| 34 | `0eaa97a` | Assess analyst delivery readiness | docs/RFC | analyst/replay/browser readiness | support | low |
| 35 | `ae1cb0b` | Assess browser strict offline readiness | docs/RFC | browser offline readiness | support | low |
| 36 | `6621c68` | Document browser offline asset policy | docs/RFC | browser asset policy/plan | support | low |
| 37 | `f4e4d69` | Finalize Event Forensic replay persistence decision | docs/RFC | replay product decision/size audit | support | low |
| 38 | `4a17553` | Add final local release readiness audit | release index | release readiness V2 | support | low |
| 39 | `0ce05da` | Add local browser offline runtime assets | browser assets | local vendor assets/static serving/browser HTML | release-critical browser boot | medium-low |

## Final Gate Matrix

| Workstream | Current gate | Latest commit | Runtime changed? | Next allowed action | Blocked action |
|---|---|---|---|---|---|
| Side/Outcome Phase 2 model probability | stable / complete | `5d55158` | yes | maintain regression coverage | changing model probability semantics |
| Side/Outcome Phase 4 cluster direction | stable / complete | `5d55158` | yes | maintain cluster-direction contract | raw-token cluster reinterpretation |
| Event Forensic weak-history demotion | implemented / release-ready | `5d55158` | yes | preserve demotion metadata and tests | scoring/gate tuning without approval |
| Event Forensic scope semantics | implemented | `6de3902` | yes, additive | keep selected-market vs whole-event labels visible | silently broadening selected-market scope |
| Event Forensic performance/scorer | `scorer_context_patch_partial` | `f181b95` | yes, performance only | rerun equivalence/full tests before push | further runtime optimization without new evidence |
| Event Forensic wallet/API boundary | `api_boundary_no_safe_patch` | `8de1c3a` | additive trace only | sidecar/RFC work only | unsafe batching or request-shape changes |
| Event Forensic pagination/provider semantics | `provider_query_semantics_rfc_ready_no_runtime_change` | `f9ec8c5` | no production expansion | bounded sidecar micro-probes with approval | production pagination expansion |
| Phase 3 capital-at-risk | `phase3_sidecar_only_final`; blocker `phase3_blocked_until_new_source_fields` | `8d687c9` | no | sidecar/source-quality evidence only | runtime capital migration |
| Replay persistence | `replay_keep_sidecar_only_final` | `f4e4d69` | no | local sidecar snapshots only | storage/report/browser embedding without RFC |
| Browser strict offline | `browser_strict_offline_ready` | `0ce05da` | browser boot/static serving only | maintain pinned provenance and offline tests | UI rewrite/build pipeline without approval |
| Analyst delivery | `analyst_delivery_ready_local` | `0eaa97a` | no | local analyst use with documented caveats | promoting blocked workstreams as complete |
| Protocol/ledger sidecars | read-only | `1c9a9bd` | no production integration | sidecar audits | CLOB auth, trading, private keys |
| Indexer sidecar | local-only | `a813951` | no production integration | fixture replay / local sidecar only | live indexing/startup integration |
| Shadow context sidecars | sidecar-only | `2a6d11c` | no production integration | offline evaluation | scorer/report-copying integration |
| Push/PR packaging | user-gated / deferred | current dry run | n/a | run pre-push matrix, then await explicit approval | push/PR without user instruction |

## Runtime Diff Surface

| Surface | Exact behavior change across series | Tests/checks covering it | Residual risk | Rollback note |
|---|---|---|---|---|
| `app/side_outcome.py` | Shared raw-token vs economic-side normalization and cluster direction helpers. | Side/Outcome Phase 2/4 tests, known-case benchmark, cross-mode contracts. | Future code can conflate token price and economic probability. | Revert Side/Outcome runtime commits; preserve old reports. |
| `app/scanner.py` | Uses Side/Outcome semantics and prepared scoring context while preserving weights/gates. | scanner pattern tests, Side/Outcome tests, cross-mode contracts, scorer-context tests. | Shared scoring path is sensitive to accidental gate/threshold drift. | Revert prepared-context changes only if equivalence breaks. |
| `app/archive_scanner.py` | Additive Side/Outcome/report visibility metadata; old rows remain absent-safe. | archive evidence/completeness tests, browser label snapshots. | Legacy rows may lack new fields. | Revert additive metadata if compatibility breaks. |
| `app/event_forensic.py` | Weak-history demotion, scope metadata, performance memoization/cache/trace metadata, provider warnings. | Event Forensic demotion/scope/performance/equivalence tests, known-case benchmark. | Highest risk: candidate IDs, scores, ranks, review buckets, weak-history demotion, exports. | Use equivalence harness before any rollback decision. |
| `app/event_forensic_performance.py` | Runtime-adjacent pure performance helpers, cache keys, profiling, trace aggregation. | performance contract/equivalence tests. | Helpers must remain pure or proven behavior-equivalent when imported. | Revert helper use from runtime first; leave sidecar helpers if harmless. |
| `app/browser_desktop.py` | Narrowly serves `/vendor/browser/...` local runtime assets through safe helper. | browser static/offline tests. | Path exposure or MIME regression if future routes broaden. | Remove vendor route calls; browser returns to online/CDN dependency. |
| `app/event_forensic_desktop.py` | Same narrow vendor static serving for Event Forensic browser UI. | browser static/offline tests. | Same as desktop browser static serving. | Remove vendor route calls only. |
| `app/browser_ui.html` | Local React/ReactDOM/Babel boot scripts and system font fallback; labels/sorting preserved. | strict offline readiness, browser label snapshots. | Runtime Babel remains; future build work must prove UI equivalence. | Restore prior script/font references. |
| `app/browser_event_forensic_ui.html` | Local boot scripts and system font fallback for Event Forensic UI; scope labels preserved. | Event Forensic scope/demotion/browser tests. | Same UI boot risk, plus scope label regression risk. | Restore prior script/font references. |
| `app/vendor/browser/*` | Pinned local React `18.3.1`, ReactDOM `18.3.1`, Babel standalone `7.29.7`, provenance hashes. | provenance JSON validation, strict offline readiness. | Asset size is intentional; future version changes need provenance update. | Remove vendor assets only with explicit cleanup approval. |
| `app/browser_static_assets.py` | Shared safe read-only static asset helper for browser runtime assets. | `tests/test_browser_static_assets.py`. | Must not become a broad static file server. | Remove imports/routes and helper if offline support is rolled back. |
| `app/event_forensic_replay.py` | Sidecar snapshot helper only; no storage/report schema mutation. | replay snapshot/schedule/size tests. | Future product work may confuse sidecar with persistence approval. | Revert sidecar helper if not wanted. |
| Sidecar app files | Protocol/ledger/indexer/shadow/local helpers are committed but not production scanner/archive/Event Forensic integrations. | focused sidecar tests. | Accidental production import or startup integration. | Revert sidecar package or keep as isolated tooling. |

## Local-Only Hygiene

| Bucket | Observed state | Recommendation |
|---|---|---|
| `PROJECT_MEMORY.md` | ignored/local-only, updated after campaigns | keep local-only; do not stage |
| `release_manifests/` | 22 manifest files on disk; 12 currently visible as untracked in status | keep local unless owner explicitly wants packaging metadata committed |
| `shadow_review_packets/` | 58 generated packet files | keep local-only; do not stage in push packaging |
| `side_outcome_review_packets/` | 7 generated packet files plus `.DS_Store` ignored | keep local-only; do not stage |
| `validation_outputs/` | 657 files, about 5.0 GB on disk, including ignored raw live output dirs | commit only intentional compact summaries; keep raw dirs local |
| ignored workspace docs/outputs | many historical handoff/audit/output dirs are ignored | do not clean destructively; investigate only if staging risk appears |
| modified tracked files before dry run | none | if new modified tracked files appear before push, inspect before staging |
| cached area before dry run | empty | preserve clean staging policy |

No deletion, cleanup, artifact archiving, or saved report mutation was performed.

## Pre-Push Test Plan

Run this matrix immediately before any future push/PR:

1. Packaging hygiene
   - validate committed JSON outputs and `app/vendor/browser/PROVENANCE.json`;
   - run whitespace checks;
   - verify staged files exclude `PROJECT_MEMORY.md`, review packets, raw live dirs, and unapproved manifests;
   - verify branch/ahead state and cached area.

2. Browser strict offline checks
   - strict offline readiness tool;
   - browser static asset serving tests;
   - browser Side/Outcome label snapshot tests;
   - Event Forensic scope/demotion tests if Event Forensic UI files changed.

3. Runtime focused tests
   - Side/Outcome Phase 2/4 tests;
   - Event Forensic weak-history demotion and scope tests;
   - Event Forensic performance/equivalence/contract tests;
   - scanner pattern tests;
   - cross-mode scoring contract tests.

4. Sidecar focused tests
   - protocol/ledger tests;
   - indexer fixture/storage tests;
   - shadow context tests;
   - replay snapshot/schedule/size tests;
   - archive/completeness and pagination sidecar tests.

5. Phase 3 guardrails
   - Phase 3 unblock, real SELL evidence, and final source-quality tests;
   - direct scans for Phase 3 runtime changes in `_score_trade()` and `_event_forensic_score()`.

6. Full suite
   - `python3 -m unittest discover -s tests -p 'test_*.py'`;
   - latest recorded full-suite result after browser implementation: `1105` tests OK.

7. Optional live/RPC
   - not required for push;
   - only run with explicit target, strict bounds, validation-output-only writes, and no production artifact mutation.

## Packaging Risk Review

No blocking packaging risk was found.

Known risks and mitigations:

- The committed vendor browser assets are intentional release files, not generated evidence. Total vendored runtime size is about 4.33 MB and each asset has version/license/hash provenance.
- Historical reports/indexes may mention older gates. The dry-run report and the 2026-05-26 addenda are the current pointers; older evidence reports remain historical and should not be rewritten.
- Phase 3 runtime remains blocked. Do not promote sidecar-only capital evidence as runtime readiness.
- Replay persistence remains sidecar-only. Do not treat `app/event_forensic_replay.py` as storage/report schema approval.
- Pagination/provider expansion remains blocked for production runtime. Do not silently expand data collection.
- Local-only artifacts are intentionally left unstaged.

## Remaining Blockers

| Blocker | Current state | Required decision |
|---|---|---|
| Push/PR | user-gated/deferred | explicit push/PR instruction and grouping decision |
| Phase 3 capital runtime | blocked until new source fields | new direct source evidence plus separate runtime RFC/approval |
| Replay persistence beyond sidecar | sidecar-only final | report embedding/storage/browser RFC and product approval |
| Pagination runtime expansion | provider/query semantics blocked | material new-row evidence and separate runtime expansion RFC |
| Future browser build pipeline | strict offline works with runtime Babel | separate precompile/build-pipeline RFC if asset size/runtime Babel should be reduced |
| Local-only artifact cleanup | intentionally untouched | explicit cleanup/archive policy from owner |

## Final Decision

Gate: `pre_push_dry_run_ready`.

The local branch is ready for a future owner-approved packaging/push decision. Before push, rerun the pre-push test matrix and stage only intentional release files. No push or PR was performed.
