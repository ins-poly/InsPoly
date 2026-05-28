# InsPoly Benchmark System Productization

- Date: 2026-05-22
- Scope: local benchmark system productization after Side/Outcome reform
- Machine output: `validation_outputs/inspoly_benchmark_system_productization_20260522.json`
- Runtime implementation in this program: false
- Network/RPC used: false
- Gate decision: `benchmark_system_local_regression_ready`

## Current State

The stable known-case benchmark corpus is ready for fast local regression checks.

| Metric | Count |
|---|---:|
| known cases | 16 |
| pass | 15 |
| unknown-pass | 1 |
| fail | 0 |
| synthetic fixtures | 7 |
| real local artifact cases | 2 |
| generated audit evidence cases | 3 |
| review-packet cases | 4 |

`unknown-pass` is expected for the malformed fallback case: it passes because malformed input remains `unknown`, not zero or guessed.

## Productized Local Contracts

The corpus covers:

- BUY YES and BUY NO unaffected controls.
- SELL YES / SELL NO low-price economic probability inversion.
- SELL YES / SELL NO near-certainty inversion.
- BUY YES + SELL NO cluster `long_yes`.
- BUY NO + SELL YES cluster `long_no`.
- malformed/missing fallback.
- old-report row without Phase 2/4 additive fields.
- sensitive overlap without direct gate mutation.
- Phase 3 capital-at-risk blocked overlap.
- Event Forensic, Archive, and Scanner affected cases.

## What This Enables

- Quick no-RPC regression checks before future Side/Outcome edits.
- Machine-readable pass/fail/unknown outputs.
- Explicit synthetic-vs-real provenance.

## What This Does Not Enable

- Scorer tuning.
- Label/threshold changes.
- Direct gate migration.
- Live Event Forensic recall validation.

## Allowed Local Work

- Add stable saved-output packets when locally available.
- Add human-labeled public-case fixtures only with explicit provenance and no production action fields.

## Approval Required

- Scoring weight or threshold tuning.
- Product decision on whether benchmark outputs should be staged/committed.
- Live/RPC validation.

## Gate Decision

Decision: `benchmark_system_local_regression_ready`.

The benchmark is ready as a local guardrail, not as a model-quality tuning dataset.
