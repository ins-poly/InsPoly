# InsPoly Side/Outcome Phase 2 Post-Migration Stabilization

- Date: 2026-05-22
- Scope: sidecar-only stabilization and drift audit
- Runtime code changed by this audit: `false`
- Gate decision: `phase2_stable`

## What Phase 2 Changed

- Scanner low-probability and near-certainty model checks now use economic-side `model_probability` when side/outcome/price normalize safely.
- Event Forensic later-correctness, winner-entry ranks, low-probability winner, and near-certainty checks now use economic-side semantics.
- Raw token display fields remain raw and additive model/provenance fields explain the economic-side basis.

## Drift Replay Summary

- Evaluated rows: `20881`
- Unique trade keys: `6346`
- Expected affected rows: `3583`
- Expected affected unique trade keys: `986`
- Sensitive affected rows: `697`
- Sensitive affected unique trade keys: `102`

| Surface | Rows | Unique trade keys |
|---|---:|---:|
| `lowProbability30Changed` | 2173 | 760 |
| `lowProbability35Changed` | 2428 | 818 |
| `nearCertainty95Changed` | 891 | 209 |
| `nearCertainty98Changed` | 772 | 140 |
| `directionChanged` | 3583 | 986 |
| `laterCorrectnessChanged` | 1616 | 215 |
| `anyModelRelevantChange` | 3583 | 986 |
| `sensitiveGateContextAffected` | 697 | 102 |

## Expected Vs Unexpected Drift

- No unexpected drift outside the Phase 2 RFC scope was detected by source scans and bounded artifact replay.

## Compatibility Sweep

- Old/raw field rows without `model_probability`: `19324`
- Rows with unknown economic probability: `1287`
- Raw fields preserved by source scan: `true`
- Old report absent-safe loading markers present: `true`
- Browser entry-probability sort remains raw-token local sorting: `true`
- CSV/JSON export changes remain additive-only by audit scope: `true`

## Sensitive Review Packet

- Packet directory: `side_outcome_review_packets/phase2_post_migration_sensitive_cases_20260522`
- Packet cases: `40`
- Each packet row records raw side/outcome/price, economic side/probability, old/new interpretations, affected surface, and whether the change is expected by the RFC.

## Remaining Blockers

- Phase 3 capital-at-risk normalization
- Phase 4 cluster direction normalization
- Any direct Strong Risk/HER/funding/candidate-admission gate migration
- Any UI sorting/filter behavior change
- Any storage schema migration
- Any live/RPC/network behavior change

## Gate Decision

Decision: `phase2_stable`.
