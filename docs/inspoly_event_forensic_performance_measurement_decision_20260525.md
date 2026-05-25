# Event Forensic Performance Measurement Decision

Date: 2026-05-25

Gate: `needs_more_measurement`

## Measurement Outcome

The bounded live precheck used the local performance inventory target `us-x-iran-permanent-peace-deal-by`. The saved report had 6 analysis markets, but the current live resolver returned 15 markets.

The run stopped before trade collection and scoring because the current event exceeded the 8-market bound.

## Timing Breakdown

No full timing breakdown was collected. The measurement did not enter trade collection, wallet-context loading, candidate scoring, or report assembly.

## Counts

- Events resolved: 1
- Saved analysis markets: 6
- Live resolved markets: 15
- Candidate rows scored: 0
- Raw trade rows loaded: 0
- Full analysis completed: false

## Interpretation

The result does not justify a performance optimization patch. It does prove that target scope can drift between saved reports and live runs, and that a safe measurement tool must pre-resolve current market count before analysis.

## Optimization Decision

Decision: `needs_more_measurement`.

A behavior-preserving performance patch still needs a completed bounded timing sample. Current evidence is insufficient to choose between caching, parsing reuse, timing instrumentation, or other patch candidates.

## Preserved Invariants

- No scorer behavior changed.
- No thresholds changed.
- No direct Strong Risk/HER/funding/candidate-admission gate changed.
- No Phase 3 capital-at-risk runtime migration was performed.
- No storage schema changed.
- No UI sorting/filtering changed.

## Next Measurement Requirement

Use one of:

- a current whole-event target known to resolve to 8 markets or fewer; or
- an operator-approved explicit market subset for a larger event.

Until then, whole-event performance patching remains blocked.
