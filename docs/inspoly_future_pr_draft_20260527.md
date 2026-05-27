# InsPoly Future PR Draft Kit

Date: 2026-05-27

Prepared from local head: `fd12c0b` - `Add release candidate V3 strategic state`

Branch at preparation time: `main`

Ahead / behind at preparation time: `49 / 0`

Push/PR performed: `false`

Gate decision: `push_pr_dry_run_ready`

## Recommended Strategy

Do not push `main` directly.

When the owner explicitly approves publication, create a review branch from current local `main` and push that branch:

- proposed branch: `codex/inspoly-local-release-candidate-v3`
- proposed PR mode: draft PR first
- proposed history policy: preserve current commit history unless the owner explicitly asks for squashing or splitting

This gives reviewers a stable release-candidate branch without forcing direct updates to `origin/main`.

## Proposed PR Title

InsPoly local release candidate V3

## Summary

This local release candidate stabilizes InsPoly analyst workflows and validation around conservative, explainable review outputs.

Major themes:

- Side/Outcome Phase 2/4 semantics are implemented and covered by regression tests.
- Event Forensic weak-history demotion and selected-market scope semantics are implemented.
- Event Forensic performance work is behavior-preserving and measured; further performance/pagination changes remain evidence-gated.
- Browser strict offline boot is implemented with pinned local React, ReactDOM, and Babel assets.
- Phase 3 capital-at-risk runtime remains blocked until new source fields or stronger sensitive SELL evidence exists.
- Replay persistence remains sidecar-only.
- Known-case benchmark coverage is expanded to 30 compact cases, including false-positive, sidecar/context, and public-source controls.
- Public exact-wallet benchmark labels remain 0 and require accepted source-backed human intake before any fixture upgrade.
- Legacy Tk UI is frozen as historical/reference-only; release launch paths are browser-backed.

## Commit Groups

| Group | Count | Hashes | Reviewer focus |
|---|---:|---|---|
| Runtime behavior and browser boot | 7 | `5d55158`, `6de3902`, `3bf03ce`, `eae111e`, `f181b95`, `0ce05da`, `2dd851f` | scoring/routing invariants, Event Forensic equivalence, browser offline boot, Tk launch-path clarity |
| Sidecar/tooling/validation | 15 | `0d22054`, `ed0431c`, `1c9a9bd`, `a813951`, `2a6d11c`, `df5f5bd`, `795f4e4`, `d678f4c`, `58ac09c`, `47bf594`, `ffa8374`, `5d12334`, `8de1c3a`, `6818b0a`, `321bd53` | sidecar isolation, offline determinism, no production integration drift |
| Evidence, measurement, RFC, and release docs | 17 | `3fea696`, `13d29ba`, `c7f8ed8`, `209fdaf`, `b9702de`, `5a2f0bb`, `dfe965f`, `2552059`, `3b97fc7`, `338b559`, `f9ec8c5`, `36f6ee6`, `8d687c9`, `0eaa97a`, `ae1cb0b`, `6621c68`, `4a17553` | blocked gates, measurement conclusions, report accuracy, operator boundaries |
| Process, benchmark, public-case, and release state | 10 | `05d688d`, `ad27400`, `f2c8547`, `8300754`, `2d932ee`, `82fbfab`, `90e2434`, `a8af847`, `f4e4d69`, `fd12c0b` | benchmark overclaiming controls, AI_CONTROL workflow, replay sidecar decision, release state consistency |

## Runtime Behavior Changes To Review

- `app/scanner.py`, `app/archive_scanner.py`, `app/side_outcome.py`: Side/Outcome economic-side semantics and scanner contracts.
- `app/event_forensic.py`, `app/event_forensic_performance.py`: weak-history demotion, scope metadata, behavior-preserving memoization/cache/profiling helpers.
- `app/browser_desktop.py`, `app/browser_static_assets.py`, `app/browser_ui.html`, `app/browser_event_forensic_ui.html`, `app/event_forensic_desktop.py`, `app/vendor/browser/*`: strict offline browser boot.
- `app/desktop.py`: comment-only freeze marker; not the release UI.

Protected invariants:

- candidate admission unchanged unless explicitly documented by earlier approved runtime commits;
- scoring weights/thresholds/gates unchanged;
- Phase 3 capital runtime remains blocked;
- storage schema unchanged;
- UI sorting/filtering behavior unchanged;
- production pagination expansion not implemented;
- no trading, CLOB auth, private keys, or order placement.

## Sidecar And Tooling Changes

- Known-case benchmark and validation tooling.
- Polymarket protocol/ledger read-only helpers.
- Local indexer sidecar and fixture replay.
- Shadow context helpers.
- Event Forensic replay, performance, scorer-context, wallet/API, pagination, and provider-query sidecars.
- Public-case evidence bridge and human-label intake validator.

Reviewer focus:

- sidecars must remain outside production runtime paths unless explicitly approved;
- public-case fixtures must not imply exact-wallet truth without accepted source-backed intake;
- performance/pagination tools must not silently change production completeness or ranking.

## Docs, RFCs, And Product Decisions

Blocked or RFC-only decisions intentionally preserved:

- Phase 3 capital runtime: blocked until new source fields / stronger sensitive SELL evidence.
- Replay persistence: sidecar-only final.
- Pagination/provider runtime expansion: blocked/RFC-only.
- Browser build pipeline / runtime Babel removal: future RFC only.
- Public exact-wallet benchmark labels: 0 accepted labels; human intake required.
- Legacy Tk UI: frozen reference-only, not supported release UI.

## Verification Already Recorded

Release Candidate V3 recorded:

- focused matrix: 586 tests OK;
- full unittest discovery: 1122 tests OK;
- compileall passed for `app`, `tools`, and `tests`;
- JSON/provenance/path validation passed;
- browser vendor SHA-256 hashes matched provenance;
- safety scans passed;
- no live/RPC used;
- no push/PR performed.

Before actual push/PR, rerun or explicitly accept freshness of these checks using `docs/inspoly_push_approval_checklist_v3_20260527.md`.

## Local-Only Exclusions

Do not stage by default:

- `PROJECT_MEMORY.md`;
- root local-only `AGENTS.md` unless the owner changes policy;
- `release_manifests/`;
- `shadow_review_packets/`;
- `side_outcome_review_packets/`;
- raw live/RPC output dirs;
- bulky/generated validation outputs;
- runtime env or credential files.

## Rollback Notes

- Runtime Side/Outcome / Event Forensic rollback should be commit-targeted and must preserve old-report compatibility.
- Browser strict offline rollback should remove local vendor serving and HTML references together, but only after restoring a supported browser boot path.
- Sidecar rollback is generally low risk because sidecars are not production integrations.
- Docs/RFC/release outputs can be reverted independently.

## Short GitHub PR Body

```markdown
## Summary
- Stabilizes Side/Outcome Phase 2/4 semantics and Event Forensic weak-history/scope behavior.
- Adds behavior-preserving Event Forensic performance helpers and measured performance/pagination/provider evidence.
- Adds strict offline browser boot using pinned local React/ReactDOM/Babel assets.
- Expands known-case benchmark coverage to 30 compact cases and adds public-case evidence/intake controls.
- Records Phase 3 capital runtime, replay persistence, and pagination/provider expansion as blocked/RFC-only.
- Freezes legacy Tk UI as reference-only; release UI is browser-backed.

## Verification
- Focused RC V3 matrix: 586 tests OK.
- Full unittest discovery: 1122 tests OK.
- compileall passed for app/tools/tests.
- JSON/provenance/path validation passed.
- Browser vendor SHA-256 checks passed.
- Safety scans passed.

## Blocked / Not Included
- No Phase 3 capital runtime.
- No storage schema migration.
- No production pagination expansion.
- No replay persistence beyond sidecar.
- No public exact-wallet benchmark labels accepted.
- No generated review packets or local memory artifacts.
```

## Final Note

This is a dry-run PR kit only. No branch, push, or PR was created.
