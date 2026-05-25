# InsPoly Event Forensic Reliability Program

- Date: 2026-05-22
- Scope: post-Side/Outcome Event Forensic reliability planning and evidence review
- Machine output: `validation_outputs/inspoly_event_forensic_reliability_program_20260522.json`
- Runtime implementation in this program: false
- Network/RPC used: false
- Gate decision: `event_forensic_needs_live_rpc_validation`

## Current Evidence

Local evidence confirms that Phase 2 economic-side probability semantics and Phase 4 normalized cluster-direction semantics are stable in offline replay.

Relevant counts:

| Evidence | Count |
|---|---:|
| post-replay near-certainty rows | 1,339 |
| post-replay Event Forensic later-correctness rows | 68 |
| Phase 2 stabilization later-correctness rows | 1,616 |
| runtime bugs found by post replay | 0 |

The remembered weak-history / near-certain later-win ranking risk remains open because local replay does not prove ranking distribution on the affected live case family.

## What Is Closed

- Side/Outcome Phase 2 later-correctness semantics are economic-side aware.
- Side/Outcome Phase 4 timing/cluster direction is normalized where fields are safe.
- The known-case corpus includes one Event Forensic later-correctness affected case.
- No local runtime bug was found in current offline evidence.

## Still Blocked

- Weak economic history / near-certain later-win ranking validation.
- Whole-event versus selected-market distribution validation.
- Any scorer, ranking, gate, threshold, storage, UI sorting/filtering, or Phase 3 change.

## Allowed Local Work

- Load stable saved Event Forensic reports if they already exist locally.
- Add sidecar-only comparison tests for saved packets.
- Add review packets that do not mutate saved reports.

## Approval Required

- Bounded live/RPC rerun.
- Any runtime scoring/ranking/gate change.
- Any UI scope/sort/filter behavior change.

## Stop Conditions

Stop before implementation if validation requires:

- live/RPC access without explicit approval;
- Phase 3 capital-at-risk normalization;
- weight or threshold tuning;
- direct Strong Risk/HER/funding/candidate-admission changes;
- selected-market scope broadening.

## Gate Decision

Decision: `event_forensic_needs_live_rpc_validation`.

The next highest-value step is a bounded saved-report or live/RPC validation run for the remembered weak-history near-certainty case family.
