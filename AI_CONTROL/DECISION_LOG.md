# Decision Log

Last updated: 2026-05-28 EEST.

## Current Strategic Decisions
- Decision: Keep RC V4 PR #1 as Draft after merge-readiness audit; do not mark ready or merge yet.
  - Why: Local PR-readiness verification passed on the PR branch, and a follow-up privacy/secret hygiene scan found no private-key blocks or common hosted-service tokens after committed local machine path strings were redacted. GitHub still reports no commit statuses or Actions workflow runs, no reviews/comments exist yet, and the large PR still needs owner/reviewer acceptance of packaging scope including historical `release_manifests/` files.
  - Consequence: Current PR-review gate is `rc_v4_pr_stay_draft_needs_ci_or_review`. Draft PR `#1` remains https://github.com/ins-poly/InsPoly/pull/1 from `codex/inspoly-local-release-candidate-v4` into `main`; merge is not approved; ready-for-review transition is not approved. The next step is owner/reviewer decision on CI expectations, PR body/docs links, packaging artifacts, and whether the local-path redaction patch is sufficient for publication hygiene.
  - Reversal / revisit condition: If the owner accepts absent GitHub CI, accepts packaging artifacts or requests a cleanup commit, and explicitly approves marking ready, run a narrow ready-for-review checkpoint. Merge remains a separate explicit approval step.

- Decision: Publish RC V4 as a draft PR for review; keep merge owner-gated.
  - Why: RC V4 was locally complete and validated, and the owner manually created the draft pull request after the GitHub connector could not create it due integration permissions.
  - Consequence: Current publication gate is `local_release_candidate_v4_draft_pr_open`. Draft PR `#1` is https://github.com/ins-poly/InsPoly/pull/1 from branch `codex/inspoly-local-release-candidate-v4` into `main`. The publication branch was pushed, but `origin/main` was not pushed directly. Next work should be review/CI feedback or explicit merge preparation, not another local feature campaign.
  - Reversal / revisit condition: If the PR is closed or replaced, update AI_CONTROL with the replacement branch/PR URL before further publication work. If review/CI requires fixes, keep them scoped to the PR branch and preserve local-only artifact exclusions.

- Decision: Treat Release Candidate V4 as locally complete after W4 pointer-only metadata and validation; push/PR remains owner-gated.
  - Why: W4 was the only currently RFC-ready safe feature in the local warehouse chain. RC V4 implements one optional top-level `indexerWarehousePointer` object for newly generated scanner/archive/Event Forensic reports only when an explicit pointer payload is supplied. The helper rejects copied metrics, row-level sidecar context, scoring/gate effects, UI requirements, live refresh, raw DB requirements, and unknown pointer fields.
  - Consequence: Current W4 gate is `indexer_w4_pointer_metadata_implemented_no_ui_no_metrics`; current RC gate is `local_release_candidate_v4_complete_no_push_pr` after validation/commit. Browser UI panels, copied warehouse metrics, row-level context, report sorting/filtering changes, scoring/gate/funding/Phase 3 changes, warehouse scheduler/background mode, storage migration, saved-report mutation, live/network behavior, CLOB auth/trading, push, and PR remain blocked.
  - Reversal / revisit condition: If future product review needs visible UI or copied metrics, keep the current pointer metadata contract narrow and require a separate W4 UI/report embedding RFC before expanding it.

- Decision: Superseded by RC V4: warehouse W4 pointer-only report metadata was RFC-ready, not implemented.
  - Why: Current report writers persist plain JSON reports, current browser/report loaders are absent-safe for old reports and use known keys, and W3 sidecar artifacts are compact/advisory with explicit no-scoring/no-report-integration warnings. A single optional top-level `indexerWarehousePointer` can improve discoverability without copying metrics.
  - Consequence: Current W4 gate is `indexer_w4_pointer_metadata_rfc_ready`. The future allowed shape is metadata-only: pointer version, artifact path/id, timestamp, source report id, local/stale/advisory warnings, and `metricsCopied=false`, `scoringEffect=false`, `routingEffect=false`. Implementation remains separately product-approved. Report writer/browser changes, copied warehouse metrics, row-level sidecar context, scoring/gate/funding/Phase 3 changes, storage migration, live refresh, raw DB reads, saved report mutation, production imports, scheduler/background mode, CLOB auth/trading, push, and PR remain blocked.
  - Reversal / revisit condition: If future implementation needs UI panels, copied metrics, report sorting/filtering behavior, raw DB reads, production sidecar imports, or scoring/gate effects to be useful, downgrade to `indexer_w4_keep_sidecar_only` or a blocked-by-confusion-risk decision.

- Decision: Treat warehouse W3 analyst query as ready for sidecar review, not report/browser integration.
  - Why: W3 added a no-network sidecar query command that reads compact W2 registry JSON, supports list-runs/summarize-run/aggregate/target-coverage/health/retention-status/blocked-scopes modes, and emits advisory JSON/Markdown only. The current query run reported 3 runs, 1 active review candidate, 2 retained references, 5 markets, 580 trades, 6 cursors, 3 covered targets, 0 malformed raw JSON rows, and 0 duplicate indicators.
  - Consequence: Current warehouse W3 gate is `indexer_warehouse_w3_analyst_query_ready`. The next safe campaign is W4 report-pointer product decision, but only as pointer metadata if separately approved. Live ingestion, warehouse writer/copy behavior, raw DB mutation, copied report metrics, production imports, report/browser integration, storage schema migration, saved report mutation, scoring/gate/funding/Phase 3 changes, CLOB auth/trading, push, and PR remain blocked pending separate approval.
  - Reversal / revisit condition: If W4 needs copied metrics, UI panels, report sorting/filtering changes, production imports, or scoring/gate effects to be useful, stop and downgrade to `indexer_warehouse_w4_keep_sidecar_only` or an RFC-only blocker.

- Decision: Treat warehouse W2 registry/retention as ready for future sidecar analyst query packets, not ingestion or cleanup automation.
  - Why: W2 added a no-network sidecar registry tool that consumes compact W1 summaries only, records local-only DB references, classifies retention state, and writes compact registry JSON. The current registry has 3 runs, 1 active review candidate, 2 retained references, 5 markets, 580 trades, 6 cursors, 0 malformed raw JSON rows, and 0 duplicate indicators.
  - Consequence: Current warehouse W2 gate is `indexer_warehouse_w2_registry_retention_ready`. The next safe campaign is W3 analyst sidecar query/read command over compact registry/W1 summaries. Live ingestion, warehouse writer/copy behavior, append-mode retention, automatic deletion/move/compaction, production imports, report/browser integration, storage schema migration, saved report mutation, scoring/gate/funding/Phase 3 changes, CLOB auth/trading, push, and PR remain blocked pending separate approval.
  - Reversal / revisit condition: If W3 needs report/browser wiring, DB mutation, production imports, or copied report metrics to be useful, stop and downgrade to an RFC-only blocker before implementing those paths.

- Decision: Treat warehouse W1 manual command as ready for local DB review, not live ingestion or warehouse writing.
  - Why: W1 added a manual read-only sidecar command that opens existing SQLite DBs in read-only mode, runs W0/readiness checks, summarizes table/market/trade/cursor/raw JSON/duplicate/retention state, and writes only compact review JSON/Markdown. It reviewed three existing local sidecar DBs successfully: 5 market rows, 580 public trade rows, 6 cursors, 0 malformed raw JSON rows, and 0 duplicate indicators; all three returned `ready_for_local_warehouse_review`.
  - Consequence: Current warehouse W1 gate is `indexer_warehouse_w1_manual_command_ready`. The next safe campaign is W2 registry/retention, still no scheduler/background mode. Live ingestion, warehouse writer/copy behavior, append-mode retention, production imports, report/browser integration, storage schema migration, saved report mutation, scoring/gate/funding/Phase 3 changes, CLOB auth/trading, push, and PR remain blocked pending separate approval.
  - Reversal / revisit condition: If W2 needs append-mode writes, production storage migration, report/browser wiring, or live scheduling to be useful, stop and downgrade to an RFC-only blocker before implementing those paths.

- Decision: Treat warehouse W0 as ready for a future W1 manual-command approval/RFC, not a warehouse implementation.
  - Why: W0 now has a pure sidecar contract helper, explicit W0 fields in the read-only readiness audit, tests for table/cursor/raw JSON/collection metadata/retention/no-network behavior, and docs/JSON describing W0 boundaries. Old sidecar DBs remain readable without migration, and collection metadata remains an external run-summary requirement rather than a forced schema change.
  - Consequence: Current warehouse W0 gate is `indexer_warehouse_w0_ready_for_w1_manual_command_rfc`. A future W1 campaign may propose one manual local warehouse command, but warehouse writes, live ingestion, append-mode retention, production imports, report/browser integration, storage schema migration, scheduling/background mode, scoring/gate/funding/Phase 3 changes, CLOB auth/trading, push, and PR remain blocked pending separate approval.
  - Reversal / revisit condition: If future W1 planning discovers that useful warehouse behavior requires production storage migration, report/browser wiring, live background operation, or auth/trading/external writes, downgrade to a blocked RFC gate and do not implement W1.

- Decision: Treat indexer warehouse as RFC-ready for a future W0 cleanup campaign, not implementation-ready.
  - Why: The evidence chain now includes clean one-target and same-slug repeat runs, target/provider hardening, scoped compare support, repeatability over the same three-target set, and per-target public-trade collection with 60/60/60 target coverage, clean readiness, and latest scoped compare storage risk count 0.
  - Consequence: Current warehouse RFC gate is `indexer_warehouse_rfc_ready_for_future_w0_implementation`. A future W0 campaign may work on no-runtime schema/readiness cleanup and implementation-readiness contracts. Warehouse write commands, append-mode retention, scheduled/background mode, report/browser integration, storage schema migration, production imports, scoring/gate changes, CLOB auth/trading, push, and PR remain blocked.
  - Reversal / revisit condition: If W0 discovers old sidecar DB incompatibility, cursor corruption risk, retention risk, or need for production schema/runtime integration, downgrade to `indexer_warehouse_rfc_blocked_by_schema_risk` or an RFC-only blocker before implementing any write path.

- Decision: Per-target public-trade collection hardening is sufficient to draft a warehouse RFC, but not to implement warehouse mode.
  - Why: An approved sidecar-only hardening campaign added optional per-target public-trade caps while preserving old aggregate behavior for old configs. The approved three-target live probe stored 3 market rows, 180 public trade rows, and 2 cursors with 60 rows per target, clean readiness, no malformed raw JSON, no filter mismatches, and scoped compare storage risk count 0.
  - Consequence: Current indexer collection gate is `indexer_collection_hardening_ready_for_warehouse_rfc_no_runtime`; warehouse readiness is `warehouse_rfc_ready_no_implementation`. A future warehouse RFC may now be drafted around sidecar-only target registries, per-target/per-condition trade collection, per-condition cursor design, retention policy, readiness audits, scoped compares, and rollback. Warehouse implementation, production runtime integration, report/browser integration, storage schema migration, scoring/gate changes, background scheduling, CLOB auth/trading, push, and PR remain blocked.
  - Reversal / revisit condition: If a future per-target repeat run shows storage/cursor identity drift, malformed payloads, duplicate indicators, provider filter mismatch, or unstable target resolution, downgrade to collection hardening or provider-shape blocked before any warehouse RFC implementation work.

- Decision: Keep warehouse RFC readiness blocked until public-trade collection is hardened.
  - Why: A second approved three-target run repeated the prior hardened DB with zero drift and clean readiness, proving sidecar repeatability for the exact set. However, both three-target runs stored all 200 public trades on the Khamenei condition and zero on the two anchor targets because the runner uses one aggregate condition filter with a global two-page cap.
  - Consequence: Current repeatability gate is `indexer_repeatability_needs_collection_hardening`; warehouse readiness state is `warehouse_rfc_blocked_needs_collection_hardening`. The runner now emits sidecar-only public-trade collection metadata and warnings for future runs, but collection behavior and DB schema remain unchanged. Runtime, warehouse implementation, report/browser integration, storage schema changes, scoring/gate changes, and push/PR remain blocked.
  - Reversal / revisit condition: Revisit warehouse RFC readiness only after an approved sidecar-only per-target/per-condition public-trade collection mode proves representative target coverage with readiness audit and scoped compare evidence.

- Decision: Treat bounded indexer target hardening as ready for a future repeat operator run, not warehouse/runtime work.
  - Why: Resolver preflight selected two proven anchors plus a single-market Khamenei replacement, and the fresh three-target sidecar run reached clean readiness. Scoped compare found no storage identity drift, malformed payloads, duplicate indicators, cursor key/status errors, or schema issues.
  - Consequence: Current hardening gate is `indexer_multitarget_hardening_ready_for_repeat_operator_run`. The failed `us-x-iran-permanent-peace-deal-by` slug is classified as market-vs-event/bounds mismatch for bounded indexer use. Public-trade overlap drift is classified as provider/collection-sampling drift, so warehouse/runtime/report integration remains blocked until repeat evidence or per-target trade collection hardening exists.
  - Reversal / revisit condition: If a future repeat over the same three targets shows storage/cursor identity drift, malformed payloads, duplicate indicators, or unresolved target instability, downgrade to a target/compare hardening gate before any broader live run.

- Decision: Treat the bounded multi-target indexer probe as partial success requiring target hardening.
  - Why: The owner approved exactly one three-slug public read-only sidecar run into a fresh local-only DB. The runner completed without forbidden behavior and the DB readiness audit was clean, but one approved slug failed provider lookup and scoped overlapping-slug comparison is not yet supported.
  - Consequence: Current multi-target probe gate is `indexer_multitarget_probe_partial_success_needs_target_hardening`. The fresh DB contains 2 market rows, 200 public trade rows, and 2 cursors; readiness gate is `indexer_sidecar_readiness_ready_no_runtime`; malformed raw JSON and duplicate indicators are 0. No daemon, scheduler, warehouse mode, scanner/archive/Event Forensic/browser/report integration, storage schema change, saved-artifact mutation, auth/private-key/trading behavior, push, or PR occurred.
  - Reversal / revisit condition: Revisit through a target-hardening/scoped-compare campaign before approving a repeat multi-target run. Warehouse mode and production runtime integration remain separately blocked.

- Decision: Treat the same-slug bounded indexer repeat probe as successful and ready for a small multi-target approval packet.
  - Why: The owner approved exactly one second live/network probe for the same market slug into a fresh local-only DB, and the manual sidecar runner completed without provider failure, production integration, or scope expansion.
  - Consequence: Current repeat-probe gate is `indexer_repeat_probe_success_ready_for_small_multitarget_run`. The fresh DB contains 1 market row, 200 public trade rows, and 2 cursors; readiness gate is `indexer_sidecar_readiness_ready_no_runtime`; first-vs-repeat compare gate is `indexer_sidecar_compare_ready_for_repeat_run` with no table-count, cursor, market identity, trade identity, provider, storage, or market/trade raw-hash drift. No daemon, scheduler, warehouse mode, scanner/archive/Event Forensic/browser/report integration, storage schema change, saved-artifact mutation, auth/private-key/trading behavior, push, or PR occurred.
  - Reversal / revisit condition: Revisit only through an explicit small multi-target operator packet with fresh local DB output, strict caps, and immediate readiness/compare review; warehouse mode and production runtime integration remain separately blocked.

- Decision: Prepare bounded indexer repeat-run approval without running a second live probe.
  - Why: The first approved sidecar DB was useful but only proved a single narrow live slice. Before another run, the project needed explicit idempotence, fresh-DB comparison, drift tolerance, duplicate, malformed JSON, cursor, and retention policies.
  - Consequence: Current repeat-run gate is `indexer_repeat_run_ready_for_operator_approval`. Added `tools/indexer_sidecar_db_compare.py`, focused tests, repeat-run RFC/decision docs, compact JSON outputs, and read-only re-audit/self-compare evidence. The existing DB re-audit remains `indexer_sidecar_readiness_ready_no_runtime`, and self-compare is `indexer_sidecar_compare_ready_for_repeat_run`. No second live/network run, daemon, scheduler, warehouse mode, production import, report/browser change, storage schema change, saved-artifact mutation, auth/private-key/trading behavior, push, or PR occurred.
  - Reversal / revisit condition: Revisit only if the owner explicitly approves one second same-slug fresh-DB probe under the RFC bounds; then run readiness audit plus `fresh_live` compare before any longer run, warehouse design, target expansion, or runtime integration.

- Decision: Treat the first bounded live indexer sidecar probe as successful but still hardening-gated.
  - Why: The owner approved exactly one market slug, and the manual sidecar runner completed one public read-only run without production integration or provider failure.
  - Consequence: Current Branch A run gate is `bounded_live_indexer_success_needs_operator_hardening`. The local-only DB contains 1 market row, 200 public trade rows, and 2 cursors; the DB audit gate is `indexer_sidecar_readiness_ready_no_runtime`. No daemon, scheduler, warehouse mode, scanner/archive/Event Forensic/browser/report integration, saved-artifact mutation, auth/private-key/trading behavior, push, or PR occurred.
  - Reversal / revisit condition: Before any repeat run, target expansion, orderbook collection, scheduling, warehouse mode, or production integration, write a hardening/repeat-run RFC covering idempotence, endpoint contracts, retention, rollback, and operator stop conditions.

- Decision: Add a manual bounded live indexer sidecar runner, but block the first run until an exact operator target is supplied.
  - Why: Branch A was approved to the operator packet layer, and the owner selected "Require Slug" plus "Add Sidecar Tool". No exact market or event slug was present in the implementation request, so choosing a target automatically would violate the approval packet.
  - Consequence: `tools/indexer_bounded_live_sidecar_run.py` and focused tests now make a future one-target manual run executable. The current run report gate is `bounded_live_indexer_blocked_missing_operator_target`; no public provider calls, DB creation, background worker, warehouse mode, production import, report/UI change, saved-artifact mutation, trading, push, or PR occurred.
  - Reversal / revisit condition: Revisit only when the owner supplies exactly one market or event slug and accepts the bounded caps/output path; then run the manual sidecar command once and audit the produced DB before any repeat-run RFC.

- Decision: Prepare operator approval packets for the three remaining post-donor gates without runtime changes.
  - Why: The prior donor campaign made the branches decision-ready but left the owner-facing approval layer ambiguous. The next safe step was to make the approval decisions explicit, not to start live ingestion, report/UI integration, or funding/Phase 3 runtime work.
  - Consequence: Final combined gate is `operator_approval_readiness_packets_ready_no_runtime`. Branch A is `indexer_bounded_live_approval_packet_ready` with a no-network config validator; Branch B is `sidecar_report_pointer_keep_sidecar_only` with a static pointer example only; Branch C is `pusd_collateral_fixture_grade_sources_added` with static official-docs facts only. No live worker, report/browser wiring, funding runtime, Phase 3 runtime, scoring/gate changes, storage schema changes, trading, push, or PR was performed.
  - Reversal / revisit condition: Revisit only through explicit owner approval for one of three future campaigns: bounded live indexer operator run, pointer-only report metadata RFC/implementation, or pUSD collateral trace-policy/source reconciliation RFC.

- Decision: Complete the remaining donor-derived branches as sidecar/RFC work with no runtime integration.
  - Why: The indexer/warehouse, sidecar-to-analyst-surface, and pUSD/CLOB collateral branches all remain valuable, but each crosses approval-gated runtime, report/UI, live-network, or funding semantics boundaries if implemented directly.
  - Consequence: Final combined gate is `three_branch_execplan_no_safe_runtime_changes`. Added current-state reports, compact JSON summaries, a read-only indexer DB readiness audit, and static unknown-safe collateral semantics fixtures/tests. Live indexing, report-copying, UI panels, pUSD funding runtime, Phase 3 capital runtime, storage migration, CLOB auth/trading, push, and PR remain blocked.
  - Reversal / revisit condition: Revisit only through one of three future approval campaigns: bounded live indexer run approval, sidecar report-pointer/product approval, or verified pUSD/CLOB source research followed by a separate runtime RFC.

- Decision: Prepare a future push/PR kit but keep publication approval-gated.
  - Why: Release Candidate V3 is verified and ready for review, but the owner explicitly has not approved push/PR or branch creation.
  - Consequence: `docs/inspoly_future_pr_draft_20260527.md`, `docs/inspoly_reviewer_risk_map_v3_20260527.md`, `docs/inspoly_push_approval_checklist_v3_20260527.md`, and `validation_outputs/inspoly_future_push_pr_packaging_dry_run_20260527.json` are the current PR preparation references. Recommended future strategy is to create `codex/inspoly-local-release-candidate-v3` from local `main` and open a draft PR only after explicit owner approval. No branch, push, PR, squash, rebase, or remote git operation was performed.
  - Reversal / revisit condition: If the owner wants direct `main` push, multiple PRs, squashing, or continued local-only work, run a new approval-gated packaging campaign before remote actions.

- Decision: Treat Release Candidate V3 as the current verified local state.
  - Why: The earlier `ad27400` verification was stale after strategic control, benchmark, public-case intake, maintenance, and Tk launch-path commits.
  - Consequence: `docs/inspoly_release_candidate_v3_state_20260527.md` and `validation_outputs/inspoly_release_candidate_v3_state_20260527.json` are the current release-candidate state references. V3 verification passed 586 focused tests and 1122 full-suite tests at head `2dd851f` before the V3 report commit. Push/PR remains user-gated.
  - Reversal / revisit condition: Rerun RC verification if runtime files, fixtures, benchmark tooling, browser assets, or release packaging state changes before push.

- Decision: Freeze legacy Tk UI as historical/reference-only.
  - Why: The active `python3 -m app desktop`, archive, and Event Forensic desktop commands route to browser-backed local UIs, while `app/desktop.py` carries older Tk labels and duplicated UI logic that can mislead future edits.
  - Consequence: `app/desktop.py` remains in the tree for historical context and direct import compatibility, but it is not the release UI or supported fallback. Future support or deletion requires a separate RFC/retirement campaign.
  - Reversal / revisit condition: If the owner wants Tk supported or removed, first prove launch/test/doc dependencies and define UI equivalence or rollback requirements.

- Decision: Maintain known-case benchmark changes through the maintenance checklist and accepted-label intake path.
  - Why: The corpus is now broad enough to guard future model/runtime-adjacent work, but public exact-wallet evidence remains unproven and should not drift through ad hoc edits.
  - Consequence: `docs/inspoly_known_case_benchmark_maintenance_checklist_20260527.md` and `validation_outputs/inspoly_known_case_benchmark_maintenance_20260527.json` are the current maintenance references. The 30-case fixture remains unchanged by this maintenance campaign, with 0 accepted exact-wallet public labels and 6 public controls awaiting human/source labels.
  - Reversal / revisit condition: If an accepted intake label proves exact wallet/user/market identity, run a separate benchmark fixture update campaign with tests and rollback notes.

- Decision: Route future public exact-wallet benchmark upgrades through a human-label intake schema.
  - Why: The public-case evidence bridge found no safe exact-wallet upgrade, but future source-backed evidence should have a precise acceptance path rather than ad hoc fixture edits.
  - Consequence: `tests/fixtures/known_case_benchmark/public_case_label_intake_schema.json` and `tools/public_case_label_intake_validator.py` define the intake contract. The human labeling packet covers all 6 deferred public controls. No exact-wallet labels are accepted by this campaign.
  - Reversal / revisit condition: If an accepted intake label proves exact wallet/user/market identity, run a separate benchmark fixture update campaign with tests and rollback notes.

- Decision: Keep public-case exact-wallet assertions blocked until a fixture-grade identity bridge exists.
  - Why: The 2026-05-27 evidence bridge rechecked public sources and local artifacts. It found useful named-user, market-level, and pattern-level evidence, plus compact local event/market refs for Maduro and Iran, but no source/local-artifact chain that proves public identity to exact wallet identity.
  - Consequence: The known-case corpus remains at 30 cases with 6 public controls, 0 exact-wallet public cases, 0 named-user local wallet candidates, 2 named-user-only cases, 2 pattern-level-only cases, and 2 market-level-only cases. All public controls now carry `identity_confidence`, `local_artifact_refs`, `deferred_reason`, and `human_review_needed` metadata.
  - Reversal / revisit condition: Add exact-wallet public cases only after a public source, local artifact reconciliation, or human label proves the wallet/user/market bridge without inference.

- Decision: Keep public-case benchmark labels assertion-level scoped.
  - Why: Public sources found in this campaign support named-user, market-level, or pattern-level controls, but not fixture-grade exact wallet identity.
  - Consequence: `known_case_benchmark_v3` has 30 compact cases, including 6 public-source metadata controls with 9 unique source URLs, 2 named-user-only cases, 2 pattern-level-only cases, 2 market-level-only cases, and 0 exact-wallet public cases. Public controls require fresh validation and forbid exact-wallet detection, automatic action, and scoring/gate/routing use.
  - Reversal / revisit condition: Add exact-wallet public cases only when a source or local artifact proves exact wallet/user/market identity without inference.

- Decision: Expand known-case benchmark controls without runtime/model changes.
  - Why: Future scoring/runtime work needs stronger regression coverage for false-positive and overclaiming boundaries, but current release state does not justify model/gate changes.
  - Consequence: `known_case_benchmark_v2` has 24 compact offline cases, including four false-positive controls and four sidecar-context controls. These cases are advisory/regression evidence only and require `automatic_action_allowed: false` plus `safe_to_use_for_scoring_claims: false`.
  - Reversal / revisit condition: If a future human-curated public-case corpus provides stronger exact-wallet source proof, add separate exact-case fixtures instead of widening these advisory controls.

- Decision: Commit the compact AI_CONTROL layer and repo-local strategic skill as repo process infrastructure.
  - Why: The release candidate is verified, but future autonomous work needs a reviewable strategic handoff that is not dependent on long chat memory or root local-only memory.
  - Consequence: `AI_CONTROL/*.md`, `.gitignore` visibility rules, and `skills/strategic-autonomy-review/SKILL.md` are intended for commit. Root `AGENTS.md` and `PROJECT_MEMORY.md` remain local-only pending explicit owner decision.
  - Reversal / revisit condition: If the owner decides strategic control should remain machine-local, remove or ignore these files in a separate process-only cleanup campaign.

- Decision: Use repo-tracked AI_CONTROL files for strategic review loops.
  - Why: Codex has extensive local memory but can overfocus on local implementation details; external GPT needs compact, self-contained context.
  - Consequence: Major strategic cycles should produce or update `AI_CONTROL/STRATEGIC_REVIEW_PACKET.md`.

- Decision: Make `AI_CONTROL/STRATEGIC_OPERATING_SYSTEM.md` the required strategy engine for non-trivial work.
  - Why: The first AI_CONTROL packet was a strong external handoff layer, but did not itself force campaign selection, scoring, and anti-tunnel-vision checks inside the repo.
  - Consequence: Non-trivial work must follow ORIENT -> SELECT -> PLAN -> EXECUTE -> VALIDATE -> RECORD, classify the task, score candidate campaigns when strategic/open-ended, and stop before protected boundaries.
  - Reversal / revisit condition: Only if the process proves too heavy for normal maintenance; local patches can remain lightweight.

- Decision: Keep root `PROJECT_MEMORY.md` as the full operational memory.
  - Why: It already contains detailed history, validation records, and compatibility warnings.
  - Consequence: `AI_CONTROL/PROJECT_MEMORY.md` is only a compact external handoff layer.

- Decision: Preserve explainable heuristic scoring, not ML scoring.
  - Why: Analyst review requires auditable reasons, false-positive controls, and inspectable evidence.
  - Consequence: LLM review can advise but must not become production scoring logic without explicit design and tests.

- Decision: Keep Phase 3 capital-at-risk runtime blocked.
  - Why: Current evidence is sidecar/source-quality only; runtime needs stronger real field evidence, old-report no-op proof, and formula-vs-collateral decision.
  - Consequence: Future Phase 3 work remains RFC/sidecar-only unless explicitly approved.

- Decision: Keep replay persistence sidecar-only for current product state.
  - Why: Report embedding and storage persistence need size-budget, compatibility, and UX decisions.
  - Consequence: `app/event_forensic_replay.py` and related tools can support validation but should not mutate report/storage contracts.

- Decision: Browser offline boot uses vendored pinned UMD assets.
  - Why: Strict offline readiness required local React/ReactDOM/Babel boot assets without introducing a build pipeline.
  - Consequence: Provenance must stay current; replacing runtime Babel or adding a build pipeline needs a separate equivalence campaign.

- Decision: Event Forensic selected child-market scope remains exact by default.
  - Why: Direct market inputs should not silently broaden primary scoring to sibling markets.
  - Consequence: Use whole-event mode when event-wide primary ranking is intended.

- Decision: Weak-history near-certainty later-win Event Forensic rows are demoted from primary review buckets.
  - Why: This reduces misleading retrospective strength where economic history is weak and outcome was near-certain.
  - Consequence: Rows remain exported/reviewable but should not dominate primary rankings.

## Open Decisions Needed
- Whether and how to push/PR the current local commit series.
- Whether root `AGENTS.md` should remain local-only forever or be tracked as repository agent policy.
- Whether to run a bounded live/pagination micro-probe for a selected truncated market.
- Whether to prioritize known-case benchmark curation over more runtime optimization.
- Whether replay should ever be embedded in reports or persisted in storage.
- Whether Phase 3 capital-at-risk should remain permanently sidecar-only or get a future runtime RFC after stronger evidence.
- Whether future sessions should treat the repo-local skill copy, the user-level installed skill copy, or both as the canonical skill source.
- Whether to approve a bounded live indexer run against explicit target markets/events and SQLite output.
- Whether to approve pointer-only report metadata for sidecar artifacts.
- Which verified source types and addresses should become fixture-grade pUSD/CLOB collateral facts.
