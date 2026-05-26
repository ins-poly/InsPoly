# Event Forensic Query Strategy Operator Checklist

Date: 2026-05-26

Purpose: provide a practical checklist for any future bounded provider/query experiment. This checklist does not approve production pagination expansion.

## Gate

Current gate: `provider_query_semantics_rfc_ready_no_runtime_change`

Runtime expansion gate: blocked until a future sidecar experiment finds material analyst impact and a separate implementation RFC is approved.

## Qualifying Target

A target qualifies for a future query-strategy probe only if all are true:

- exactly one event is named;
- exactly one market is named for the first probe;
- the market already has local truncation evidence;
- the market has saved high-review, weak-history demotion, or sensitive-context overlap;
- the event/market identifiers come from existing local reports, validation outputs, or a user/operator-supplied slug;
- the live resolver can match the market by condition id or slug;
- the operator accepts that the result is selected-market or subset-only, not whole-event complete.

Do not use broad discovery or arbitrary Polymarket search.

## Default Bounds

For a micro-probe:

- Max events: 1
- Max markets: 1
- Max query strategies: 1
- Max pages: 3
- Page size: 100
- Max rows: 300
- Max wall time: 5 minutes
- Output: compact JSON under `validation_outputs/`

For a one-market collection probe:

- Max events: 1
- Max markets: 1
- Max chunks/windows: 8
- Max pages per window: 31
- Page size: 100
- Max unique rows: 50,000
- Max wall time: 30 minutes
- Output: compact JSON under `validation_outputs/`

For any larger subset:

- Require explicit user/operator approval.
- Label the run `subset_only_not_whole_event_complete`.
- Do not exceed the approved market list.

## Environment Requirements

- Read-only public/API configuration only.
- No private keys.
- No CLOB auth.
- No trading credentials.
- No order placement.
- No app storage mutation.
- No saved report/artifact mutation.
- Secrets must not be printed.

If env/config is missing, stop with a blocked report instead of broadening scope.

## Preflight

Before any live/RPC call:

- Confirm cached git area is empty or contains only the current approved staging set.
- Confirm `PROJECT_MEMORY.md` will remain local-only.
- Record the exact event slug, market slug, and condition id.
- Record bounds in the output.
- Record the query strategy being tested.
- Confirm the strategy cannot change production runtime behavior.
- Confirm stop conditions.

## Output Locations

Plan-only output:

- `validation_outputs/event_forensic_query_strategy_plan_YYYYMMDD.json`

Live micro-probe output:

- `validation_outputs/event_forensic_query_strategy_micro_probe_YYYYMMDD_HHMMSS/summary.json`

Compact campaign summary:

- `validation_outputs/event_forensic_query_strategy_assessment_YYYYMMDD.json`

Reports:

- `docs/inspoly_event_forensic_query_strategy_assessment_YYYYMMDD.md`

Do not commit bulky raw response dumps unless the operator explicitly approves a small fixture subset.

## Baseline Comparison

Compare every alternative query against the current baseline:

- baseline row count;
- alternative row count;
- added unique rows;
- baseline-only rows;
- duplicate rows;
- no-new-row plateaus;
- cursor stalls;
- provider/page-cap markers;
- candidate-floor rows added;
- high-review / weak-history / sensitive overlap if sidecar replay is available;
- runtime and request count.

Use stable trade identity for dedupe. Do not rely only on row count.

## Material Impact Decision

Classify as material only if one of these is true:

- candidate-floor rows increase by at least 1%;
- at least 25 candidate-floor rows are added on a high-volume market;
- sidecar replay finds at least one added row entering high-review, weak-history demotion, or sensitive-context analysis.

Classify as not material if:

- added rows are zero;
- added rows are low-notional only;
- alternative rows replace baseline rows without net evidence gain;
- provider/query behavior remains ambiguous;
- sidecar replay is not possible and candidate impact cannot be estimated.

## Required Tests Before Runtime RFC

- Query-plan bounds validation.
- Duplicate page detection.
- Cursor stall detection.
- No-new-row plateau detection.
- Old-report fallback.
- Selected-market scope preservation.
- Side/Outcome Phase 2/4 contracts.
- Event Forensic behavior equivalence on existing rows.
- Known-case benchmark.
- Phase 3 guardrails.
- Cross-mode scoring contract.
- Report/UI warning compatibility.

## Stop Conditions

Stop if:

- bounds are exceeded;
- live resolver maps to unexpected event/market scope;
- provider returns repeated/cursor-stalled pages without new evidence;
- query strategy cannot be proven selected-market scoped;
- env/config requires private credentials;
- result would require storage schema change;
- result would change scoring, thresholds, gates, candidate admission, UI sorting/filtering, or Phase 3 behavior;
- saved reports would need mutation;
- whole-event completeness would be implied from a subset.

## What Must Not Be Touched

- Production pagination defaults.
- Event Forensic scoring formula.
- Event Forensic candidate admission.
- Review routing and weak-history demotion policy.
- Strong Risk, HER, funding, or candidate gates.
- Phase 3 capital-at-risk runtime.
- Storage schema.
- Browser UI sorting/filtering.
- Saved reports/artifacts.
- Private keys, CLOB auth, trading credentials, or order placement.
- GitHub push/PR.

## Approval Text For Future Runtime Work

A future implementation prompt should explicitly say:

`Approve bounded production pagination RFC implementation for strategy <name>, using evidence <doc/json>, preserving candidate admission, scores, ranks, review routing, exports, gates, storage, Phase 3, and UI sorting.`

Without that explicit approval, work remains sidecar-only and RFC-only.
