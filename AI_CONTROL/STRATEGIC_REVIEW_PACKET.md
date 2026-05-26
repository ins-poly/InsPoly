# Strategic Review Packet

Generated: 2026-05-26 EEST.
Audience: external GPT reviewer with no access to the full repository or Codex thread.

## 1. Project Purpose
InsPoly is a local-first investigation toolkit for suspicious Polymarket trading patterns. It has three main programs: Recent Scanner, Archive Researcher, and Event Forensic Analyzer. It uses explainable heuristic scoring and conservative false-positive controls to produce analyst leads, not accusations or trading advice. The tool analyzes trade timing, wallet behavior, event context, funding traces when available, split-wallet/shared-funder structure, and final-outcome context when valid. It writes local JSON/CSV/Markdown/SQLite artifacts that analysts can reopen and inspect. It must preserve old reports, compatibility logic, and uncertainty labels because many outputs are generated from unstable public APIs and optional RPC traces. LLMs may help review packets, but production scoring must remain deterministic and auditable unless a separate tested design is approved.

## 2. Current Architecture Summary
- `app/cli.py` routes `python3 -m app` commands.
- `app/scanner.py` is the shared base scoring engine.
- `app/archive_scanner.py` reuses scanner logic for historical exports and archive visibility tiers.
- `app/event_forensic.py` resolves event/market inputs, replays scoring, builds Event Forensic rankings/clusters, and writes bundles.
- `app/polymarket.py`, `app/wallet_analytics.py`, `app/event_context.py`, and `app/funding_context.py` provide external API, wallet, event, and funding context.
- `app/browser_desktop.py` / `app/event_forensic_desktop.py` serve local browser UIs.
- `app/browser_ui.html` / `app/browser_event_forensic_ui.html` are active frontends.
- Sidecar helpers exist for benchmark schemas, protocol/ledger context, indexing, shadow/profile/microstructure context, replay, and audits; they are not production runtime paths by default.

## 3. Current State And Gate Decisions
- Latest release-candidate commit verified: `ad27400 Verify local release candidate state`.
- Latest pre-push dry-run commit inspected: `05d688d Add final pre-push packaging dry run`.
- Latest runtime-affecting commit inspected: `0ce05da Add local browser offline runtime assets`.
- Local release-candidate gate: `local_release_candidate_verified`.
- Verification baseline: focused matrix 660 tests OK and full unittest discovery 1105 tests OK.
- Browser strict offline boot is ready: React, ReactDOM, and Babel are vendored locally and served by narrow static routes.
- Side/Outcome Phase 2/4 is stable after local benchmark/drift audits.
- Event Forensic selected-market vs whole-event semantics are implemented and must remain explicit.
- Event Forensic weak-history near-certainty rows are demoted from primary review while remaining exported/reviewable.
- Event Forensic performance improved, but large whole-event runs still depend on wallet-context loading and event-wide trade collection.
- Pagination/provider changes are RFC/probe-only; production pagination expansion remains blocked.
- Phase 3 capital-at-risk runtime remains blocked; sidecar/source-quality evidence only.
- Replay persistence is sidecar-only in the current product state.
- Push/PR/release remains user-gated.
- Root `PROJECT_MEMORY.md` and root `AGENTS.md` remain local-only by default; AI_CONTROL and the repo-local skill are the reviewable process-control layer.

## 4. What Changed In The Strategic-Control Consolidation Cycle
- Added an `AI_CONTROL/` strategic control layer:
  - `PROJECT_MEMORY.md`
  - `STRATEGIC_OPERATING_SYSTEM.md`
  - `STRATEGIC_MAP.md`
  - `CURRENT_STATE.md`
  - `INVARIANTS_AND_GUARDRAILS.md`
  - `DECISION_LOG.md`
  - `STRATEGIC_BACKLOG.md`
  - `REVIEW_PACKET_TEMPLATE.md`
  - `STRATEGIC_REVIEW_PACKET_TEMPLATE_V2.md`
  - `STRATEGIC_STATE_TEMPLATE.md`
  - `LAST_STRATEGIC_REVIEW.md`
  - `STRATEGIC_REVIEW_PACKET.md`
- Kept root `AGENTS.md` local-only for now; its current local copy requires future substantial strategic work to read the AI_CONTROL layer.
- Appended a Strategic Addendum to `/Users/Root1/.codex/AGENTS.md`.
- Added `skills/strategic-autonomy-review/SKILL.md` and installed the same skill under `/Users/Root1/.codex/skills/strategic-autonomy-review/SKILL.md`.
- Updated `.gitignore` so `AI_CONTROL/*.md` and `skills/strategic-autonomy-review/SKILL.md` are visible for explicit staging even though root `PROJECT_MEMORY.md` and root `AGENTS.md` remain local-only.
- Updated root `PROJECT_MEMORY.md` with this process-only change.
- No runtime code, scoring, browser behavior, storage, report schema, saved outputs, pushes, or PRs were changed.

## 5. Why These Changes Were Made
The user observed that Codex can overfocus on small technical loops and asked for files that can be given to ChatGPT for strategic review. The repository already had detailed root memory, but external GPT does not have access to the full local thread or all repo files. The new AI_CONTROL layer gives both Codex and external GPT a compact, self-contained handoff without replacing root memory or current code as sources of truth.

## 6. Files Changed, Grouped By Function
- Strategic handoff:
  - `AI_CONTROL/PROJECT_MEMORY.md`
  - `AI_CONTROL/STRATEGIC_OPERATING_SYSTEM.md`
  - `AI_CONTROL/STRATEGIC_MAP.md`
  - `AI_CONTROL/CURRENT_STATE.md`
  - `AI_CONTROL/INVARIANTS_AND_GUARDRAILS.md`
  - `AI_CONTROL/DECISION_LOG.md`
  - `AI_CONTROL/STRATEGIC_BACKLOG.md`
  - `AI_CONTROL/REVIEW_PACKET_TEMPLATE.md`
  - `AI_CONTROL/STRATEGIC_REVIEW_PACKET_TEMPLATE_V2.md`
  - `AI_CONTROL/STRATEGIC_STATE_TEMPLATE.md`
  - `AI_CONTROL/LAST_STRATEGIC_REVIEW.md`
  - `AI_CONTROL/STRATEGIC_REVIEW_PACKET.md`
- Strategic skill:
  - `skills/strategic-autonomy-review/SKILL.md`
  - `/Users/Root1/.codex/skills/strategic-autonomy-review/SKILL.md`
- Agent instructions:
  - `AGENTS.md`
  - `/Users/Root1/.codex/AGENTS.md`
- Git visibility:
  - `.gitignore`
- Persistent local memory:
  - `PROJECT_MEMORY.md`

## 7. Tests / Validation
- This cycle changed only markdown/process files, so no app tests were required for runtime behavior.
- Recommended verification for any future runtime task:
  - `python3 -m py_compile app/*.py tools/*.py tests/*.py`
  - `python3 -m unittest discover -s tests -p 'test_*.py'`
  - targeted audit tools for the touched area.

## 8. Known Unresolved Issues
- Push/PR grouping is still operator-gated.
- Whether root `AGENTS.md` should be tracked as repository policy remains a user decision.
- Known-case benchmark coverage remains incomplete.
- Event/archive pagination can truncate deep histories; production pagination expansion remains blocked.
- Whole-event Event Forensic can still be expensive on large events.
- Replay persistence is not embedded into reports or storage.
- Phase 3 capital-at-risk runtime remains blocked.
- Funding traces must preserve `unknown` when lookups fail or are unavailable.

## 9. Strategic Risks / Tunnel-Vision Risks
- Codex may continue optimizing local diagnostics instead of choosing a product-level next campaign.
- Codex may treat Strategic Operating System autonomy as permission to cross approval-gated boundaries; the guardrails explicitly forbid that.
- Performance work could accidentally alter scope, completeness, or ranking semantics.
- Sidecar helpers may look ready to integrate but still need approval gates.
- Pagination evidence could tempt unbounded production fetch expansion without provider-contract proof.
- Phase 3 evidence work could drift into runtime scoring without source-field and accounting decisions.
- External GPT may recommend generic architecture changes that conflict with repo-specific compatibility logic.

## 10. Next Strategic Directions
- Recommended Direction: Known-case benchmark expansion.
  - Pros: improves strategic validation, false-positive control, and future model-change confidence without changing runtime.
  - Cons: requires careful curation and source classification; may not produce immediate UI/runtime changes.
- Alternative Direction: Push/PR packaging.
  - Pros: makes current local progress reviewable and shareable.
  - Cons: explicitly user-gated; must avoid staging generated/local-only artifacts.
- Alternative Direction: Legacy Tk UI freeze/retire decision.
  - Pros: reduces UI confusion with docs/RFC-only work.
  - Cons: lower validation leverage than benchmark expansion.
- Avoid repeating now: Phase 3 runtime evidence, pagination/provider probes, and performance tuning unless new evidence or operator approval appears.

## 11. Operator Decision Questions
- Should the next Codex campaign focus on known-case benchmark expansion, or should push/PR packaging take precedence despite the current user-gated status?
- Should root `AGENTS.md` remain local-only, or become tracked repository policy in a future process-control commit?
- Should any AI_CONTROL files be made part of a future public/tracked repo package, or remain local agent-control documentation?
- Is external GPT allowed to propose approval-gated scoring/gate changes, or should it be restricted to planning and validation recommendations only?

## 12. Guardrail Excerpts
- "Do not change scoring/gates/visibility semantics without explicit approval."
- "Keep funding `unknown` distinct from `none`."
- "Keep selected-market vs whole-event semantics explicit."
- "Keep sidecar helpers out of production runtime paths."
- "Production pagination expansion is RFC/probe-only until separately approved."
- "Phase 3 capital-at-risk runtime remains blocked."
- "Replay persistence is sidecar-only in the current product state."
- "External GPT advice is advisory input; reconcile it against current code, root memory, and operator instructions."
