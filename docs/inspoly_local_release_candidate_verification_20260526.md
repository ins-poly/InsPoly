# InsPoly Local Release Candidate Verification

Date: 2026-05-26

Verified commit: `05d688d` - `Add final pre-push packaging dry run`

Branch: `main`

Base: `origin/main` at `865b858`

Ahead / behind before this report: `40 / 0`

Gate decision: `local_release_candidate_verified`

Runtime changed in this campaign: `false`

Push/PR performed: `false`

## Strategic Context

This campaign used the `strategic-autonomy-review` workflow and classified the task as `release_packaging` plus `diagnostic_probe`.

The objective was to verify the local release candidate without changing product behavior. The verification covered packaging hygiene, release JSONs, vendor provenance, focused runtime and sidecar tests, the full test suite, direct safety scans, and local-only artifact state.

No product/runtime feature work was done. No scoring/model/gate, Phase 3 runtime, storage schema, UI sorting/filtering, production pagination, saved report, generated packet, destructive cleanup, push, or PR action was performed.

## Baseline State Capture

| Item | Result |
|---|---|
| Branch | `main` |
| Verified head | `05d688d` |
| Base | `origin/main` at `865b858` |
| Ahead / behind before this report | `40 / 0` |
| Cached area before verification report | empty |
| Modified tracked files before report | pre-existing `.gitignore`; generated strict-offline readiness JSON changed during validation |
| Untracked local-control files | `AI_CONTROL/`, `skills/` |
| Untracked local artifact buckets | `release_manifests/`, `shadow_review_packets/`, `side_outcome_review_packets/` |
| Ignored/local memory | `PROJECT_MEMORY.md` |
| Push/PR | not performed |

The `.gitignore`, `AI_CONTROL/`, and `skills/` changes were already present at campaign startup and were treated as local strategic-control work outside this verification commit. They were not staged.

## Docs And JSON Validation

| Check | Result |
|---|---|
| Release/dry-run JSON parse | passed, 7 JSON files |
| Referenced path validation | passed, 12 key paths |
| Browser vendor provenance parse | passed |
| React SHA-256 | matched `28348fef6cb0ed8b2ceeb22deaf824428fd13875d84c73d38f77dd216fc24e7f` |
| ReactDOM SHA-256 | matched `f9044a5e9c39db8bb1a204dff924e526ec0a621e695bb69de1035811be8709e4` |
| Babel standalone SHA-256 | matched `7f55bd5c3efadeaa83d4de97dc91da8bf0733789801cf28b9273c4284739798e` |
| Strict offline readiness tool | passed, gate `browser_strict_offline_ready` |

Verification found one stale validation-output inconsistency: `validation_outputs/inspoly_browser_strict_offline_readiness_20260526.json` still reflected the pre-implementation blocked state. Rerunning the committed readiness tool regenerated that compact JSON with the current `browser_strict_offline_ready` state. This is a validation-output correction only; no browser/runtime code changed.

## Focused Runtime Test Matrix

| Focus area | Command scope | Result |
|---|---:|---|
| Side/Outcome Phase 2/4, scanner patterns, cross-mode scoring | 9 test modules | 245 tests OK |
| Archive/Event Forensic scope, weak-history, performance equivalence | 11 test modules | 73 tests OK |
| Event Forensic pagination/performance measurement/profiling sidecars | 13 test modules | 63 tests OK |
| Phase 3 guardrails, protocol/ledger, replay sidecars | 9 test modules | 79 tests OK |
| Browser strict offline, labels, known-case benchmark | 9 test modules | 56 tests OK |
| Indexer, shadow, microstructure, trader profile sidecars | 23 test modules | 144 tests OK |
| Focused targeted total | 74 test modules | 660 tests OK |

## Full Suite

`python3 -m unittest discover -s tests -p 'test_*.py'`

Result: `1105` tests OK in `8.894s`.

Observed non-failing noise:

- existing sqlite `ResourceWarning` messages for unclosed test database connections;
- known validation-interrupted terminal failure artifact message emitted by the validation-corpus test path.

No expected failures, skipped failures, or test failures were observed.

## Syntax Compilation

`python3 -m compileall -q app tools tests`

Result: passed.

## Safety Scans

| Scan | Result |
|---|---|
| Uncommitted app/runtime diff | none |
| Cached area during scan | empty |
| Browser hard remote boot dependencies | none in `app/browser_ui.html` or `app/browser_event_forensic_ui.html` |
| Phase 3 runtime implementation | no new runtime diff; existing `capital_at_risk_usdc` fields are pre-existing non-Phase-3 runtime behavior |
| Trading/order placement/CLOB auth scan | no order-placement implementation found; hits were secret-redaction keys, optional OpenAI review helper usage, tests, and safety strings |
| Storage schema migration | no migration/runtime diff found |
| UI sorting/filtering change | no browser/runtime diff found |
| Production pagination expansion | no runtime diff found |
| `PROJECT_MEMORY.md` staged | no |

## Local-Only Artifact Audit

| Bucket | State | Classification | Push packaging action |
|---|---|---|---|
| `PROJECT_MEMORY.md` | ignored/local-only | expected local memory | do not stage |
| `.gitignore` | modified at campaign startup | pre-existing local strategic-control change | needs user decision before push |
| `AI_CONTROL/` | untracked at campaign startup | local strategic-control layer | needs user decision before push |
| `skills/` | untracked at campaign startup | local workflow skill | needs user decision before push |
| `release_manifests/` | 22 files on disk, 12 visible untracked in status | old/local packaging metadata | keep local unless owner requests |
| `shadow_review_packets/` | 58 generated files | generated review packets | keep local-only |
| `side_outcome_review_packets/` | 7 generated files plus ignored `.DS_Store` | generated review packets | keep local-only |
| `validation_outputs/` | 657 files, about 5.0 GB on disk | compact committed summaries plus bulky/raw local evidence | commit only explicit compact outputs |

No local-only files were deleted, cleaned, archived, or pushed.

## Remaining Blockers

| Blocker | Current state | Required decision |
|---|---|---|
| Push/PR | user-gated/deferred | explicit push/PR instruction and grouping decision |
| Pre-existing AI_CONTROL / skill local files | untracked plus `.gitignore` modified | decide whether to include in a future process-control commit |
| Phase 3 capital runtime | blocked until new source fields | new direct source evidence plus separate runtime RFC/approval |
| Replay persistence beyond sidecar | sidecar-only final | report embedding/storage/browser RFC and product approval |
| Pagination runtime expansion | provider/query semantics blocked | material new-row evidence and runtime expansion RFC |
| Future browser build pipeline | not required for strict offline | separate build/precompile RFC if desired |
| Local-only artifact cleanup | intentionally untouched | explicit cleanup/archive policy |

## Future Push/PR Checklist

Before any future push/PR:

1. Decide whether to include the pre-existing `.gitignore`, `AI_CONTROL/`, and `skills/` strategic-control changes.
2. Re-run JSON/provenance validation.
3. Re-run browser strict offline readiness and static asset tests.
4. Re-run focused Side/Outcome, scanner, Event Forensic, Phase 3 guardrail, replay, protocol/ledger, indexer, shadow, browser, benchmark, and cross-mode suites.
5. Re-run full unittest discovery.
6. Run safety scans for Phase 3 runtime, scoring/gate drift, storage schema, UI sorting/filtering, trading/CLOB/private-key behavior, production pagination expansion, and remote browser boot dependencies.
7. Stage only intentional release files.
8. Exclude `PROJECT_MEMORY.md`, generated review packets, raw live output dirs, bulky generated evidence, and unapproved manifests.
9. Confirm cached area before push.

## Strategic Record Note

The `AI_CONTROL/` strategic layer was read and used for this campaign. Because `AI_CONTROL/`, `skills/`, and the `.gitignore` change were already untracked/unstaged local work at startup, this verification commit does not stage them. Future state updates for those files should happen as a separate process-control commit or remain local-only by owner decision.

## Final Decision

Gate: `local_release_candidate_verified`.

The local release candidate at `05d688d` passed the verification matrix. A future push/PR is technically ready after owner approval and after rerunning or accepting this matrix as sufficiently fresh. No push or PR was performed.
