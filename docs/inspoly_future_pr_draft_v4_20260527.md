# Draft PR Text - InsPoly Local Release Candidate V4

## Title

Complete InsPoly local release candidate V4 readiness

## Summary

- Implements W4 optional `indexerWarehousePointer` metadata for newly generated reports when an explicit pointer payload is supplied.
- Keeps W4 pointer metadata sidecar/advisory only: no copied warehouse metrics, no row-level sidecar context, no UI panel, no scoring/gate/routing effect.
- Consolidates remaining RC V4 blockers and clarifies that Phase 3, pUSD/CLOB runtime, pagination expansion, replay persistence, warehouse UI/scheduler work, and push/PR remain approval-gated.
- Updates RC V4 release state and future push/PR packaging notes.

## Validation

- JSON validation for new compact outputs.
- Python compile checks for changed report pointer/report writer/test files.
- Focused W4/report/browser compatibility tests.
- Focused indexer warehouse W0/W1/W2/W3/W4 tests.
- Cross-mode scoring, known-case benchmark, Event Forensic, scanner/archive, and browser offline focused tests.
- Full unittest discovery after report writer changes.
- Runtime import scan for forbidden live warehouse/indexer tool imports.
- Scans for copied warehouse metrics and scoring/gate/Phase 3 changes.
- `git diff --check`.

## Risks For Reviewers

- Report writer signatures now accept an optional pointer payload. Defaults are unchanged.
- Pointer helper is intentionally pure and outside live indexer tooling.
- Browser UI does not surface pointer metadata; future visible UI requires separate product approval.

## Out Of Scope

- No push/PR from the local campaign itself.
- No live/network calls.
- No warehouse implementation beyond metadata pointer support.
- No scheduler/background worker.
- No saved report mutation.
- No scoring/gate/funding/Phase 3 changes.
