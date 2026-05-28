# InsPoly Event Forensic Scope Semantics Implementation

- Date: 2026-05-25
- Contract: `docs/inspoly_event_forensic_scope_semantics_product_contract_20260525.md`
- Audit output: `validation_outputs/event_forensic_scope_semantics_audit_20260525.json`
- Runtime scope: additive metadata and browser/report copy only
- Commit gate: `scope_semantics_ready_for_commit`

## Exact Behavior Changed

New Event Forensic reports now carry explicit product-scope metadata in addition to the legacy scope fields. The scoring/filtering behavior is unchanged.

Added top-level and `summary` fields:

- `analysisScope`
- `primaryScoringScope`
- `selectedMarketSlug`
- `selectedMarketQuestion`
- `eventSlug`
- `relatedMarketsContextIncluded`
- `siblingMarketsPrimaryScored`
- `scopeExplanation`

Added `analysis_settings` fields:

- `primary_scoring_scope`
- `related_markets_context_included`
- `sibling_markets_primary_scored`

Added raw bundle field:

- `scope_product_metadata`

## Scope Semantics

Selected-market reports:

- legacy `analysis_scope`: `market`
- product `analysisScope`: `selected_market`
- `primaryScoringScope`: `selected_market`
- `siblingMarketsPrimaryScored`: `false`
- related/sibling markets are context-only

Whole-event reports:

- legacy `analysis_scope`: `event`
- product `analysisScope`: `whole_event`
- `primaryScoringScope`: `whole_event`
- `siblingMarketsPrimaryScored`: true only when related/case-family expansion is enabled

## UI Copy Added

The Event Forensic browser summary now shows:

- primary scoring scope;
- related context included;
- sibling markets primary-scored;
- scope explanation.

This is display-only. It does not change list tabs, sorting, filtering, row membership, or hidden rows.

## Export Compatibility

JSON reports and Markdown exports include the additive scope metadata. Existing CSV row-level scope columns remain intact; no existing columns were removed or renamed.

Old reports remain absent-safe:

- missing product fields are inferred from legacy `analysis_scope`;
- old reports are not mutated;
- saved report loaders continue to refresh display Markdown without requiring new fields.

## Local Audit Result

The local sidecar audit scanned 180 artifacts:

- loaded reports: 179
- skipped too large: 1
- selected-market reports: 134
- whole-event reports: 23
- unknown scope reports: 23
- reports with related-market references: 37
- reports with sibling context rows: 1
- reports with explicit new summary scope fields: 0
- possible legacy ambiguity count: 11

Gate from the audit: `scope_semantics_needs_new_report_metadata`.

Interpretation: old saved artifacts do not have the new additive fields. This is expected and is why the implementation adds explicit metadata to newly generated reports while keeping old reports fallback-safe.

## Tests

Added `tests/test_event_forensic_scope_semantics.py`.

Coverage:

- selected-market metadata is context-only;
- whole-event metadata is explicit;
- ineligible/report summary paths receive additive scope fields;
- old reports without new fields load safely;
- sidecar audit runs offline and writes JSON;
- browser copy includes the new scope semantics;
- audit tool is not imported by production runtime paths.

## Regression Boundaries

Preserved:

- selected-market primary scoring remains selected-market-only;
- whole-event scope remains explicit;
- scoring weights and thresholds;
- Strong Risk, HER, funding, and candidate-admission gates;
- storage schema;
- saved report compatibility;
- UI sorting/filtering behavior;
- Phase 3 capital-at-risk blocker.

## Rollback

Revert:

- `_scope_product_metadata()` / `_scope_summary_metadata()` additions and field assignments in `app/event_forensic.py`;
- `reportScopeSemantics()` and summary copy additions in `app/browser_event_forensic_ui.html`;
- `tools/event_forensic_scope_semantics_audit.py`;
- `tests/test_event_forensic_scope_semantics.py`;
- this document and the product contract.

No saved report migration or storage rollback is needed.

## Remaining Product Decisions

- Whether future UI controls should make selected-market vs whole-event scope more prominent before a run.
- Whether legacy saved reports should be re-run to populate product-scope metadata. They should not be mutated in place.
- Whether unknown-scope historical artifacts should be left as archival-only or reclassified through a read-only sidecar audit.

## Gate

Decision: `scope_semantics_ready_for_commit`.
