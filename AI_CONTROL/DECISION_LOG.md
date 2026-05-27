# Decision Log

Last updated: 2026-05-27 EEST.

## Current Strategic Decisions
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
