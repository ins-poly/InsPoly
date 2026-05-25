# InsPoly Benchmark Suite V2 Productization

- Date: 2026-05-22
- Scope: unified local benchmark registry and runner
- Registry: `tests/fixtures/inspoly_benchmark_registry/registry.json`
- Runner: `tools/run_inspoly_benchmark_suite.py`
- Machine output: `validation_outputs/inspoly_benchmark_suite_v2_20260522.json`
- Runtime implementation: false
- Network/RPC used: false
- Gate decision: `benchmark_suite_v2_ready`

## Inputs

The suite references existing corpora and audit outputs instead of copying them:

- known-case Side/Outcome corpus;
- weak-history Event Forensic saved-report audit;
- archive visibility monitoring v2 output;
- Phase 3 capital-at-risk audit.

## Result

| Metric | Count |
|---|---:|
| registry items | 9 |
| required categories covered | 9 |
| pass | 9 |
| fail | 0 |
| unknown | 0 |
| fixture-corpus sources | 6 |
| sidecar-audit sources | 3 |

## What It Can Prove

- Phase 2 economic probability contract remains executable locally.
- Phase 4 cluster direction contract remains executable locally.
- malformed rows remain unknown rather than guessed.
- old-report compatibility remains represented.
- Phase 3 remains blocked.
- sensitive overlap remains indirect and not a gate mutation.

## What It Cannot Prove

- scorer weights or threshold quality;
- current live Event Forensic distribution;
- Phase 3 capital-at-risk safety;
- UI product decisions or sorting/filtering behavior changes;
- direct Strong Risk/HER/funding/candidate-admission migration.

## How To Run

`python3 tools/run_inspoly_benchmark_suite.py --root .`

## Gate

Decision: `benchmark_suite_v2_ready`.
