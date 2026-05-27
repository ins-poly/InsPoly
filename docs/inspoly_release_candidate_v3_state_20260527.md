# InsPoly Release Candidate V3 State

Date: 2026-05-27

Verified head before this report: `2dd851f` - `Freeze legacy Tk UI as reference-only`

Branch: `main`

Ahead / behind before this report: `48 / 0`

Gate decision: `release_candidate_v3_state_ready`

Runtime changed in this campaign: `false`

Live/RPC used: `false`

Push/PR performed: `false`

## Executive Summary

Release Candidate V3 refreshes the prior `ad27400` verification after seven additional local commits:

- strategic control layer consolidation;
- known-case benchmark expansion;
- public-case benchmark source labels;
- public-case exact-wallet evidence bridge;
- public-case human labeling packet and intake validator;
- known-case benchmark maintenance checklist;
- legacy Tk UI reference-only launch decision.

Current state is coherent and locally verified. The repository is still not pushed. Remaining blockers are explicit product/operator decisions, not hidden implementation work.

## Branch And Worktree Recovery

| Item | State |
|---|---|
| Branch | `main` |
| Verified head before V3 report | `2dd851f` |
| Base remote | `origin/main` |
| Ahead / behind before V3 report | `48 / 0` |
| Cached area before report | empty |
| Modified tracked files before report | none |
| Visible untracked buckets | `release_manifests/`, `shadow_review_packets/`, `side_outcome_review_packets/` |
| Ignored local memory | `PROJECT_MEMORY.md` |
| Push/PR | not performed |

## Local-Only Artifact Policy

| Bucket | State | Classification | Action |
|---|---|---|---|
| `PROJECT_MEMORY.md` | ignored/local-only | expected local memory | keep unstaged |
| `release_manifests/` | 22 files, 76,249 bytes | old/local packaging metadata | keep local unless owner requests |
| `shadow_review_packets/` | 58 files, 58,511 bytes | generated review packets | keep local-only |
| `side_outcome_review_packets/` | 7 files, 510,108 bytes | generated review packets | keep local-only |
| `validation_outputs/` | 668 files, about 5.42 GB | compact summaries plus bulky/raw local evidence | commit only explicit compact summaries |

No local-only files were deleted, cleaned, archived, pushed, or staged by this campaign.

## Post-`ad27400` Commit Inventory

| Commit | Title | Category | Runtime changed? | Key files / areas | Validation state |
|---|---|---|---:|---|---|
| `f2c8547` | Consolidate strategic control layer | process/control | no | `.gitignore`, `AI_CONTROL/`, strategic skill, consolidation report | docs/JSON checks |
| `8300754` | Expand known-case benchmark controls | benchmark | no runtime | known-case fixture, benchmark runner/tests/docs | full suite previously 1109 OK |
| `2d932ee` | Add public-case benchmark source labels | public-case evidence | no runtime | fixture public metadata, benchmark schema/docs | full suite previously 1112 OK |
| `82fbfab` | Add public-case evidence bridge | public-case evidence | no runtime | fixture evidence tiers, bridge tool/tests/docs | full suite previously 1116 OK |
| `90e2434` | Add public-case human labeling packet | public-case intake | no runtime | intake schema, validator, labeling packet | focused tests passed |
| `a8af847` | Add known-case benchmark maintenance checklist | docs/process | no | maintenance checklist, master-index addendum, AI_CONTROL | focused tests passed |
| `2dd851f` | Freeze legacy Tk UI as reference-only | UI launch-path docs/test | comment/test only; no behavior change | `app/desktop.py` comment, workflow test, decision docs | workflow tests passed |

## Gate Matrix V3

| Workstream | Current gate | Latest relevant commit | Runtime changed? | Key docs | Validation status | Next allowed action | Blocked condition |
|---|---|---|---:|---|---|---|---|
| Side/Outcome Phase 2 | stable / complete | `5d55158` | yes | Phase 2 stabilization docs | focused matrix + full suite V3 passed | maintain regression tests | changing model probability semantics |
| Side/Outcome Phase 4 | stable / complete | `5d55158` | yes | Phase 4 stabilization docs | focused matrix + full suite V3 passed | maintain cluster direction contract | raw-token cluster reinterpretation |
| Event Forensic weak-history demotion | implemented / release-ready | `5d55158` | yes | weak-history release readiness docs | focused matrix + full suite V3 passed | preserve demotion metadata | scorer/gate tuning without approval |
| Event Forensic scope semantics | implemented | `6de3902` | yes, additive | scope semantics implementation docs | focused matrix + full suite V3 passed | keep scope labels visible | silently broadening selected-market scope |
| Event Forensic performance/scorer | `scorer_context_patch_partial` | `f181b95` | yes, performance only | scorer context reports/RFCs | focused matrix + full suite V3 passed | evidence-only future optimization | runtime optimization without measured proof |
| Event Forensic wallet/API boundary | `api_boundary_no_safe_patch` | `8de1c3a` | additive trace only | API boundary trace report | focused matrix + full suite V3 passed | monitor/RFC-only | unsafe request batching |
| Event Forensic pagination/provider | blocked/RFC-only | `f9ec8c5` | no production expansion | provider query semantics RFC | focused matrix + full suite V3 passed | bounded sidecar probes with approval | production pagination expansion |
| Phase 3 capital runtime | `phase3_sidecar_only_final`; blocker `phase3_blocked_until_new_source_fields` | `8d687c9` | no | final evidence review | focused matrix + full suite V3 passed | sidecar/source-quality only | runtime capital migration |
| Replay persistence | `replay_keep_sidecar_only_final` | `f4e4d69` | no | replay product decision | focused matrix + full suite V3 passed | sidecar snapshots only | report/storage/browser persistence |
| Browser strict offline | `browser_strict_offline_ready` | `0ce05da` | browser boot/static serving | strict offline implementation docs | focused matrix + full suite V3 passed; hashes matched | maintain provenance | build pipeline/runtime Babel removal without RFC |
| Analyst delivery | `analyst_delivery_ready_local` | `0eaa97a` | no | analyst delivery readiness | V3 docs reviewed | local use with caveats | promoting blocked features as complete |
| Known-case benchmark | `known_case_benchmark_maintenance_ready` | `a8af847` | no runtime | maintenance checklist | focused matrix + full suite V3 passed | use as validation guardrail | treating advisory cases as scoring labels |
| Public-case exact-wallet evidence | `public_case_evidence_bridge_no_safe_upgrade` | `82fbfab` | no runtime | evidence bridge report | focused matrix + full suite V3 passed | human/source evidence only | exact-wallet claims without proof |
| Public-case human label intake | `public_case_human_labeling_packet_ready` | `90e2434` | no runtime | labeling packet/update policy | focused matrix + full suite V3 passed | validate future intake labels | applying labels automatically |
| Legacy Tk UI | `legacy_tk_ui_frozen_reference_only` | `2dd851f` | no launch behavior change | Tk launch decision | focused matrix + full suite V3 passed | RFC only if support/retire desired | routing CLI to Tk without approval |
| Strategic control layer | `strategic_control_layer_committed` | `f2c8547` | no | strategic consolidation report | V3 docs reviewed | keep current-state files fresh | treating AI_CONTROL above code/user instructions |
| Protocol/ledger sidecars | read-only | `1c9a9bd` | no production integration | protocol/ledger docs/tests | focused matrix + full suite V3 passed | sidecar validation | CLOB auth/trading/private keys |
| Indexer sidecar | local-only | `a813951` | no production integration | indexer sidecar tests | focused matrix + full suite V3 passed | local fixture replay | live indexing/startup integration |
| Shadow context sidecars | sidecar-only | `2a6d11c` | no production integration | shadow context reports/tests | focused matrix + full suite V3 passed | offline evaluation | scorer/report integration |
| Push/PR readiness | user-gated | current V3 | n/a | V3 push checklist | V3 verification passed | owner-approved push/PR campaign | pushing without explicit instruction |

## Runtime Change Summary

This V3 campaign made no runtime change. The only post-`ad27400` app file touched was `app/desktop.py` in `2dd851f`, with a comment-only status marker. The active release UI remains browser-backed.

Current runtime-affecting local series work remains the earlier reviewed set:

- Side/Outcome semantics and Event Forensic weak-history demotion;
- Event Forensic scope metadata;
- behavior-preserving Event Forensic performance helpers;
- browser strict offline local vendor asset serving.

Those surfaces were covered by focused V3 tests and full unittest discovery.

## Docs / Process-Only Summary

Post-`ad27400` work is mostly validation/process:

- AI_CONTROL strategic operating layer committed.
- Known-case benchmark expanded to 30 compact cases.
- Public-case evidence is explicitly non-exact: 0 exact-wallet labels.
- Human label intake schema and validator define the only exact-wallet upgrade path.
- Known-case maintenance checklist documents safe fixture process.
- Legacy Tk UI is frozen as reference-only.

## Benchmark And Public-Case State

| Metric | Count |
|---|---:|
| total known-case corpus | 30 |
| side-outcome contract cases | 16 |
| sidecar/context controls | 4 |
| false-positive controls | 4 |
| public controls | 6 |
| exact-wallet public labels | 0 |
| named-user local wallet candidates | 0 |
| named-user-only public cases | 2 |
| pattern-level-only public cases | 2 |
| market-level-only public cases | 2 |
| public cases requiring human review | 6 |

Exact-wallet public benchmark upgrades require accepted source-backed intake and a separate fixture update campaign.

## Documentation Consistency Fixes

V3 fixed one current user-facing documentation inconsistency:

- `README.md` and `docs/ARCHITECTURE.md` now state that browser UIs boot from local vendored React/ReactDOM/Babel assets and system font stacks, not public CDN/font boot dependencies.

Historical reports remain historical and were not rewritten unless current-state addenda were appropriate.

## V3 Verification Matrix

| Check | Result |
|---|---|
| Focused matrix | 586 tests OK |
| Full unittest discovery | 1122 tests OK |
| Compileall | passed for `app`, `tools`, and `tests` |
| Vendor provenance JSON parse | passed |
| React SHA-256 | matched `28348fef6cb0ed8b2ceeb22deaf824428fd13875d84c73d38f77dd216fc24e7f` |
| ReactDOM SHA-256 | matched `f9044a5e9c39db8bb1a204dff924e526ec0a621e695bb69de1035811be8709e4` |
| Babel standalone SHA-256 | matched `7f55bd5c3efadeaa83d4de97dc91da8bf0733789801cf28b9273c4284739798e` |
| Existing worktree app/test/tool diff before report | none |
| Live/RPC | skipped by rule; no live/RPC used |

Observed non-failing noise:

- existing sqlite `ResourceWarning` messages for unclosed test database connections;
- known validation-interrupted terminal failure artifact message emitted by the validation-corpus test path.

## Safety Scan Summary

| Scan | Result |
|---|---|
| No app/runtime diff from this campaign before docs | passed |
| No scoring/model/gate changes | passed; no runtime diff |
| No Phase 3 runtime implementation | passed; existing capital fields are historical/current code, not V3 changes |
| No storage schema change | passed; no runtime diff |
| No UI sorting/filtering behavior change | passed; no browser/runtime diff |
| No production pagination expansion | passed; no runtime diff |
| No hard remote browser boot dependency | passed; only analyst navigation URLs remain in browser HTML |
| No private-key/CLOB-auth/trading/order-placement implementation | passed; hits are existing read-only protocol constants, tests, or safety strings |
| No saved artifact mutation | passed |
| `PROJECT_MEMORY.md` staged | no |
| Review packet/raw output dirs staged | no |

## Future Push/PR Conditions

Use [Future Push/PR Checklist V3](inspoly_future_push_pr_checklist_v3_20260527.md).

Current push gate: `push_pr_user_gated`.

Do not push until the owner explicitly approves staging and push/PR grouping.

## Ranked Strategic Roadmap

Scores use the strategic-autonomy scale from 0 to 5.

| Rank | Campaign | Product leverage | Risk reduction | Evidence readiness | Reversibility | Dependency unblocking | Approval load | Tunnel-vision control | Trigger |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | Future push/PR packaging and draft PR description | 5 | 5 | 5 | 4 | 5 | 1 | 5 | Owner says to publish or asks for PR packaging |
| 2 | Analyst report clarity polish around warning surfaces | 4 | 4 | 4 | 5 | 3 | 4 | 4 | A concrete current output ambiguity is identified |
| 3 | Known-case benchmark periodic maintenance / source refresh | 4 | 5 | 3 | 5 | 4 | 4 | 5 | New public sources or human labels arrive |
| 4 | Replay top-slice embedding RFC | 3 | 3 | 4 | 5 | 3 | 2 | 4 | Product wants portable report replay beyond sidecars |
| 5 | Browser build-pipeline / remove runtime Babel RFC | 3 | 3 | 3 | 4 | 3 | 2 | 4 | Product wants smaller assets or no runtime Babel |

Do not prioritize Phase 3 runtime or pagination expansion unless new source fields, sensitive SELL evidence, or provider semantics materially change.

## Final Decision

Gate: `release_candidate_v3_state_ready`.

The repository is freshly verified at the V3 state and ready for a future owner-approved push/PR packaging campaign. No push or PR was performed.
