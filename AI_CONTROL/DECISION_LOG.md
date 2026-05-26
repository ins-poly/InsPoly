# Decision Log

Last updated: 2026-05-26 EEST.

## Current Strategic Decisions
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
