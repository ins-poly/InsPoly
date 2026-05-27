# InsPoly Future Push/PR Checklist V3

Date: 2026-05-27

Base commit for this checklist: `2dd851f` - `Freeze legacy Tk UI as reference-only`

Push/PR performed: `false`

## Purpose

This checklist is for a future owner-approved push/PR pass. It is not permission to push.

## Pre-Push Verification

Run from a clean worktree with only intentional release files staged:

1. JSON/provenance validation
   - parse committed `validation_outputs/*.json` that are part of the release;
   - parse `app/vendor/browser/PROVENANCE.json`;
   - verify vendor SHA-256 hashes for React, ReactDOM, and Babel.
2. Browser checks
   - strict offline readiness;
   - browser static asset tests;
   - browser Side/Outcome label snapshots;
   - Event Forensic scope/demotion tests if Event Forensic browser UI changed.
3. Focused runtime checks
   - Side/Outcome Phase 2/4 tests;
   - scanner pattern tests;
   - Event Forensic weak-history and scope tests;
   - Event Forensic performance/equivalence contract tests;
   - cross-mode scoring contract.
4. Focused sidecar/checkpoint checks
   - known-case benchmark and public-case intake/evidence tests;
   - replay sidecar tests;
   - Phase 3 blocker/guardrail tests;
   - protocol/ledger tests;
   - indexer sidecar tests;
   - shadow context sidecar tests;
   - pagination/provider sidecar tests.
5. Full suite
   - `python3 -m unittest discover -s tests -p 'test_*.py'`
6. Safety scans
   - no scoring/model/gate drift;
   - no Phase 3 runtime implementation;
   - no storage schema migration;
   - no UI sorting/filtering behavior change;
   - no production pagination expansion;
   - no private-key/CLOB-auth/trading/order-placement implementation;
   - no remote browser boot dependency;
   - no saved artifact mutation.

## Staging Exclusions

Do not stage by default:

- `PROJECT_MEMORY.md`;
- root local-only `AGENTS.md` unless the owner explicitly changes policy;
- `release_manifests/*` unless the owner wants packaging metadata;
- `shadow_review_packets/`;
- `side_outcome_review_packets/`;
- raw live/RPC output directories;
- bulky/generated validation evidence;
- local SQLite/runtime directories such as `.inspoly*/`;
- credentials or `.inspoly_runtime.env`.

Commit only compact, intentional release artifacts.

## AI_CONTROL And Process Files

`AI_CONTROL/*.md`, `.gitignore` visibility rules, and `skills/strategic-autonomy-review/SKILL.md` are now committed repo process infrastructure.

Root `PROJECT_MEMORY.md` remains local-only. Root `AGENTS.md` remains local-only unless the owner explicitly decides to track it.

## Branch Strategy Recommendation

Recommended future push strategy:

1. Push a branch from current `main` only after owner approval.
2. Prefer a draft PR first, because the branch includes many local commits across runtime, sidecar, docs, benchmark, browser assets, and release packaging.
3. Keep commit history intact unless the owner asks for squashing/splitting.
4. In the PR description, separate:
   - runtime behavior changes;
   - sidecar/tooling additions;
   - benchmark/public-case validation;
   - browser strict offline assets;
   - docs/RFC/evidence;
   - blocked gates and local-only exclusions.

## PR Description Outline

```markdown
## Summary
- Side/Outcome Phase 2/4 semantics stabilized.
- Event Forensic weak-history demotion and scope semantics implemented.
- Event Forensic performance/pagination/provider evidence completed or blocked by RFC.
- Browser strict offline boot implemented with pinned local assets.
- Known-case benchmark expanded to 30 cases with public-source controls and human-label intake.
- Legacy Tk UI frozen as reference-only.

## Runtime Changes
- List scanner/archive/Event Forensic/browser runtime commits.

## Sidecar/Validation Changes
- List protocol/ledger/indexer/shadow/replay/benchmark tools.

## Blocked Gates
- Phase 3 capital runtime remains blocked.
- Replay persistence remains sidecar-only.
- Pagination/provider runtime expansion remains blocked/RFC-only.
- Public exact-wallet benchmark labels remain 0 pending accepted intake.

## Verification
- Focused matrix result.
- Full suite result.
- Safety scans.
- Browser vendor hash validation.

## Local-Only Exclusions
- PROJECT_MEMORY.md
- release manifests unless explicitly included
- review packet dirs
- raw/bulky validation outputs
- runtime env / credentials
```

## Current V3 Push Gate

`push_pr_user_gated`

No push or PR was performed.
