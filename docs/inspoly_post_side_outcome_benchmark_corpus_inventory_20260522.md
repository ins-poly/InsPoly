# InsPoly Post-Side/Outcome Benchmark Corpus Inventory

- Date: 2026-05-22
- Scope: offline corpus inventory after Side/Outcome Phase 2/4 stabilization
- Machine-readable output: `validation_outputs/post_side_outcome_benchmark_corpus_inventory_20260522.json`
- Network/RPC used: false
- Saved artifacts mutated: false

## Summary

The inventory found `20,481` local corpus items.

| Classification | Count |
|---|---:|
| real local artifact | 19,188 |
| existing fixture | 53 |
| synthetic fixture | 7 |
| generated audit output | 74 |
| incomplete/local-only | 1,159 |

| Model conclusion safety | Count |
|---|---:|
| usable with caveats | 16,592 |
| contract fixture only | 7 |
| summary evidence only | 74 |
| unsafe for model conclusions | 3,808 |

## Corpus Families

| Family | Count |
|---|---:|
| Event Forensic | 11,249 |
| Archive | 7,788 |
| Validation corpus | 1,063 |
| Strategic backlog | 94 |
| Shadow sidecar | 86 |
| Case-specific investigation | 79 |
| Reconstruction or ledger | 49 |
| Other | 46 |
| Side/Outcome | 23 |
| Benchmark | 4 |

## Interpretation

Usable with caveats:

- local archive outputs;
- local Event Forensic outputs;
- case-specific investigation outputs;
- replayable JSON/CSV rows with side/outcome/price evidence.

Contract fixture only:

- synthetic Side/Outcome Phase 2/3/4 fixtures;
- these prove expected semantics but are not production evidence.

Summary evidence only:

- generated side-outcome audit JSON;
- generated review packets;
- validation output summaries.

Unsafe for model conclusions:

- strategic backlog documents;
- generated next-action histories;
- shadow-sidecar packets not tied to Side/Outcome model behavior;
- old local docs without row-level trade data.

## Gaps

- The remembered weak-history Event Forensic near-certainty case still needs a stable saved rerun or live RPC replay.
- Known-insider/journalist notes are not yet a complete labeled benchmark corpus.
- Archive rows remain mixed: full JSON/CSV rows are useful, but lossy old rows without side/outcome/price/size are unsafe for rescoring.

## Recommendation

Use the corpus for offline regression and drift detection, not final model-quality claims. For model-quality conclusions, curate labeled known-case fixtures and rerun the remembered fragile Event Forensic cases with operator approval.
