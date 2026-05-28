# InsPoly Strategic Control Layer Consolidation

Date: 2026-05-26

Base release-candidate commit: `ad27400` - `Verify local release candidate state`

Branch: `main`

Gate decisions:

- `strategic_control_layer_committed`
- `strategic_next_workstream_selected`

Runtime changed: `false`

Push/PR performed: `false`

## Strategic Campaign Brief Summary

Classification: `strategic_campaign` and `release_packaging`.

The release candidate is already verified, but the repo-local process-control layer was still unresolved: `.gitignore` had local visibility changes, `AI_CONTROL/` and `skills/` were untracked, and root `AGENTS.md` remained ignored/local-only. The strategic objective was to make the compact strategic-control layer coherent and reviewable without changing product runtime or staging local memory/generated artifacts.

Recommended path chosen:

- Commit `AI_CONTROL/*.md` as the compact strategic handoff layer.
- Commit `skills/strategic-autonomy-review/SKILL.md` as the repo-local workflow skill.
- Commit `.gitignore` visibility rules for those process-control files.
- Leave root `AGENTS.md` and `PROJECT_MEMORY.md` local-only until the owner explicitly decides otherwise.
- Refresh AI_CONTROL state to the latest verified release candidate, then select a single next workstream.

This path is highest leverage because it resolves the worktree ambiguity around strategic process files and reduces future tunnel-vision risk without touching scoring, gates, storage, UI behavior, saved artifacts, or push/PR state.

## Current State

| Item | State |
|---|---|
| Latest release-candidate commit | `ad27400` |
| Release-candidate gate | `local_release_candidate_verified` |
| Browser strict offline | `browser_strict_offline_ready` |
| Phase 3 runtime | blocked until new source fields / stronger sensitive SELL evidence |
| Replay persistence | `replay_keep_sidecar_only_final` |
| Pagination/provider expansion | blocked / RFC-only |
| Push/PR | user-gated; not performed |
| Latest full suite | 1105 tests OK |

## Process-Control File Classification

| Path | Classification | Decision | Reason |
|---|---|---|---|
| `.gitignore` | repo process infrastructure | commit | Makes the approved compact control layer and repo-local skill visible while keeping local memory ignored. |
| `AI_CONTROL/` | repo process infrastructure | commit | Compact strategic handoff/review layer; no secrets, no runtime behavior, useful for future Codex/GPT reviews. |
| `skills/strategic-autonomy-review/SKILL.md` | repo process infrastructure | commit | Documents the workflow explicitly requested by the operator and used by this campaign. |
| `AGENTS.md` | local agent policy | leave local-only | Currently ignored and broad in effect; tracking it should be a separate user decision. |
| `PROJECT_MEMORY.md` | local operational memory | leave local-only | Contains detailed local history and workflow notes; repository policy keeps it unstaged. |
| `release_manifests/` | local packaging metadata | leave local-only | Historical manifests are useful locally but not part of this process-control consolidation. |
| `shadow_review_packets/` | generated review packets | leave local-only | Generated/noisy review artifacts; do not stage by default. |
| `side_outcome_review_packets/` | generated review packets | leave local-only | Generated/noisy review artifacts; do not stage by default. |
| bulky/raw `validation_outputs/` | generated evidence | leave local-only by default | Commit only compact intentional summaries, not raw live/probe bundles. |

## Strategic Control Consistency Result

The control layer is coherent after refresh:

- `AI_CONTROL/STRATEGIC_OPERATING_SYSTEM.md` defines ORIENT -> SELECT -> PLAN -> EXECUTE -> VALIDATE -> RECORD.
- `AI_CONTROL/INVARIANTS_AND_GUARDRAILS.md` preserves approval gates for scoring, visibility, Phase 3, pagination, storage, browser build strategy, replay persistence, live behavior, and sidecar integration.
- `AI_CONTROL/CURRENT_STATE.md` now points at verified release-candidate commit `ad27400`.
- `AI_CONTROL/DECISION_LOG.md` records the decision to commit the compact control layer while leaving root `AGENTS.md` and `PROJECT_MEMORY.md` local-only.
- `AI_CONTROL/STRATEGIC_BACKLOG.md` now prioritizes known-case benchmark expansion as the highest-leverage safe next product workstream.
- `AI_CONTROL/LAST_STRATEGIC_REVIEW.md` and `AI_CONTROL/STRATEGIC_REVIEW_PACKET.md` now reflect the release-candidate verification state.

No contradiction requiring runtime or product changes was found. The only unresolved process question is whether root `AGENTS.md` should remain local-only or become tracked repository policy later.

## Next-Workstream Scoring

Scores use the strategic-autonomy model: 0 to 5 for product leverage, risk reduction, evidence readiness, reversibility, dependency unblocking, approval load, and tunnel-vision risk control.

| Candidate | Product leverage | Risk reduction | Evidence readiness | Reversibility | Dependency unblocking | Approval load | Tunnel-vision control | Total | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| A - Future push/PR packaging | 5 | 4 | 5 | 4 | 5 | 1 | 4 | 28 | not now; user-gated |
| B - Known-case benchmark expansion | 4 | 5 | 4 | 5 | 4 | 5 | 5 | 32 | recommended |
| C - Analyst report clarity polish | 3 | 3 | 3 | 5 | 3 | 4 | 4 | 25 | defer until a concrete ambiguity is identified |
| D - Tk legacy UI freeze/retire decision | 2 | 3 | 4 | 5 | 2 | 4 | 4 | 24 | useful later, lower leverage |
| E - Phase 3 evidence only | 3 | 4 | 2 | 5 | 3 | 2 | 2 | 21 | avoid repeating without new source fields |
| F - Pagination/provider work | 3 | 3 | 2 | 4 | 3 | 2 | 2 | 19 | avoid repeating without new provider evidence |
| G - No new product work; maintain verified RC | 2 | 3 | 5 | 5 | 1 | 5 | 5 | 26 | safe fallback, but lower leverage |

Recommended next campaign: **Known-case Benchmark Expansion**.

Rationale:

- It improves validation quality and false-positive control without touching runtime gates.
- It is reversible and can remain fixture/docs/tooling-only.
- It directly addresses a long-standing root memory gap: public investigative material is not fully represented as machine-readable exact-wallet or pattern-level assertions.
- It avoids repeating already-blocked Phase 3, pagination, replay, and performance work.

## Ready-To-Paste Next Campaign Prompt

```text
Use the strategic-autonomy-review workflow.
Act as the strategic implementation lead for this repository.
First produce a Strategic Campaign Brief before editing.

Campaign: InsPoly Known-Case Benchmark Expansion And False-Positive Controls

Repository:
 <repo>

Context:
- Latest strategic control commit should include AI_CONTROL and the local strategic-autonomy-review skill.
- Current release gate: local_release_candidate_verified.
- Full suite at latest verification: 1105 tests OK.
- Do not push/PR.
- Do not change runtime scoring, gates, Phase 3, storage schema, UI sorting/filtering, pagination, replay persistence, or sidecar runtime integration.

Goal:
Expand the known-case benchmark corpus and false-positive controls using local docs/fixtures/source notes only, without changing production runtime behavior.

Phases:
1. Read AGENTS.md, PROJECT_MEMORY.md, AI_CONTROL files, existing known-case docs/tools/tests.
2. Inventory existing benchmark cases and source notes.
3. Classify candidate public cases as exact-wallet assertions, event/market-level pattern assertions, or false-positive controls.
4. Add only well-supported fixtures/source notes/tests.
5. Do not infer unnamed wallets or timestamps; mark uncertain cases as pattern-level only.
6. Run benchmark/known-case/Side-Outcome/Event Forensic focused tests and full suite if fixtures/tools changed materially.
7. Produce docs/JSON report and update PROJECT_MEMORY.md local-only.
8. Commit only intentional benchmark fixtures/tools/tests/docs/compact JSON; do not push.

Final response must include commit hash, cases added, assertion types, tests run, remaining gaps, and no-push confirmation.
```

## Verification Plan For This Campaign

This campaign is process/docs-only and does not require the full runtime suite. Required checks:

- validate the new JSON output;
- verify referenced paths exist;
- run `git diff --check`;
- run `git diff --cached --check`;
- confirm no `app/`, runtime, tests, storage, browser UI, saved artifact, manifest, packet, or raw output changes are staged;
- confirm `PROJECT_MEMORY.md` is not staged;
- confirm no push/PR.

## Final Decision

Primary gate: `strategic_control_layer_committed`.

Secondary gate: `strategic_next_workstream_selected`.

The compact strategic control layer should be committed as process infrastructure. Root `AGENTS.md` remains local-only pending a separate user decision. The recommended next product workstream is known-case benchmark expansion. No push or PR was performed.
