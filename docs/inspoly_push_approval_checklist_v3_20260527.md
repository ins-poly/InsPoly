# InsPoly Push Approval Checklist V3

Date: 2026-05-27

Prepared from local head: `fd12c0b`

Recommended branch after approval: `codex/inspoly-local-release-candidate-v3`

Push/PR performed: `false`

## Approval Required

Before any push:

- Owner confirms push is allowed.
- Owner confirms whether to create `codex/inspoly-local-release-candidate-v3` from current local `main`.
- Owner confirms draft PR vs ready PR. Recommendation: draft PR.
- Owner confirms no direct push to `origin/main`.
- Owner confirms no squash/rebase unless explicitly requested.

## Local State Checks

Before approved push:

1. Confirm branch and head.
2. Confirm ahead/behind count.
3. Confirm cached area is empty before staging.
4. Confirm no unexpected modified tracked files.
5. Confirm `PROJECT_MEMORY.md` is not staged.
6. Confirm local-only artifact dirs are not staged:
   - `release_manifests/`
   - `shadow_review_packets/`
   - `side_outcome_review_packets/`
   - raw live/RPC outputs
   - bulky/generated validation outputs
7. Confirm no credentials or runtime env files are staged.

## Verification To Rerun Or Explicitly Accept

Recommended before push:

- JSON/provenance/path validation.
- Browser strict offline readiness tests.
- Browser static asset tests.
- Browser label snapshots.
- Known-case benchmark tests.
- Public-case intake/evidence bridge tests.
- Side/Outcome Phase 2/4 tests.
- Scanner pattern tests.
- Event Forensic weak-history, scope, performance/equivalence tests.
- Cross-mode scoring contract.
- Replay sidecar tests.
- Phase 3 blocker/guardrail tests.
- Protocol/ledger/indexer/shadow sidecar tests.
- Full unittest discovery:
  - `python3 -m unittest discover -s tests -p 'test_*.py'`

Latest recorded baseline:

- focused RC V3 matrix: 586 tests OK;
- full unittest discovery: 1122 tests OK;
- compileall passed for `app`, `tools`, and `tests`;
- browser vendor SHA-256 hashes matched provenance.

## Safety Scans

Confirm:

- no scoring/model/gate drift;
- no Phase 3 runtime implementation;
- no storage schema migration;
- no UI sorting/filtering behavior change;
- no production pagination expansion;
- no private-key/CLOB-auth/trading/order-placement implementation;
- no hard remote browser boot dependency;
- no saved artifact mutation.

## Commands Only After Approval

These are examples for an approved future run. Do not run them from this dry run.

```bash
git status --short
git diff --cached --name-only
git switch -c codex/inspoly-local-release-candidate-v3
git push -u origin codex/inspoly-local-release-candidate-v3
```

Then open a draft PR using the body in:

- `docs/inspoly_future_pr_draft_20260527.md`

## Stop Conditions

Stop before push if:

- any local-only artifact is staged;
- `PROJECT_MEMORY.md` is staged;
- branch target is ambiguous;
- owner has not approved remote publication;
- test freshness is rejected by owner or reviewer;
- a safety scan finds runtime/scoring/storage/UI/pagination/Phase 3 drift.

## Final Note

This checklist is approval-gated. It is not permission to push.
