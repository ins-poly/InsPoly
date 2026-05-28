# InsPoly Event Forensic Scope Semantics Product Contract

- Date: 2026-05-25
- Scope: product decision plus additive runtime/report/UI metadata
- Runtime scoring changes: false
- Storage schema changes: false
- Network/RPC used: false
- Gate after contract: `scope_semantics_contract_implementable_additive_only`

## Product Decision

Event Forensic scope must be explicit in reports and browser copy.

Selected-market mode remains selected-market-first. Related markets, sibling markets, and title-similar event-family markets may be loaded as context, but they must not silently become primary scoring rows unless whole-event scope is explicitly active.

Whole-event mode is explicit. When whole-event scope is selected, the loaded event markets are primary scope. If related case-family markets are enabled, they may contribute only because the operator explicitly chose whole-event scope.

## Scope Definitions

### `selected_market`

- Product meaning: the selected child market is the primary analysis target.
- Legacy runtime value: `analysis_scope == "market"`.
- Primary scoring: selected market only.
- Related/sibling rows: context only.
- Required copy: say that primary ranking uses the selected market and related/sibling markets are enrichment only.

### `whole_event`

- Product meaning: the full resolved event is the primary analysis target.
- Legacy runtime value: `analysis_scope == "event"`.
- Primary scoring: explicitly loaded event markets.
- Related case-family expansion: allowed only because whole-event scope is active and the related-markets option is enabled.
- Required copy: say that event-wide rows are primary.

### `related_context_only`

- Product meaning: related/sibling market activity is visible context, not selected-market primary scoring.
- Applies when selected-market scope is active.
- Must not change scoring weights, thresholds, sorting, gates, candidate admission, funding, HER, or Strong Risk semantics.

## Additive Report Fields

New reports must include the following additive fields at top level and in `summary`:

- `analysisScope`: `selected_market` or `whole_event`.
- `primaryScoringScope`: `selected_market` or `whole_event`.
- `selectedMarketSlug`: selected market slug when selected-market scope is active, otherwise empty.
- `selectedMarketQuestion`: selected market question when selected-market scope is active, otherwise empty.
- `eventSlug`: parent event slug.
- `relatedMarketsContextIncluded`: boolean.
- `siblingMarketsPrimaryScored`: boolean.
- `scopeExplanation`: analyst-facing sentence explaining the primary/context boundary.

Existing fields remain unchanged:

- `analysis_scope`: legacy runtime value `market` or `event`.
- `selected_condition_id`
- `selected_market_slug`
- `selected_market_title`
- `parent_event_slug`
- `scope_note`
- row-level `analysisScope` fields in exports where already present.

## Old Report Fallback

Old reports may lack the additive product-scope fields. Loaders and browser copy must infer absent-safe scope from existing legacy fields:

- `analysis_scope == "market"` -> product `selected_market`.
- `analysis_scope == "event"` -> product `whole_event`.
- missing scope -> `whole_event` fallback for display only, without rescoring.
- missing selected market fields -> display `All child markets` or `Unknown`, not synthetic identifiers.

Fallback must not mutate saved reports.

## Browser Copy Rules

The Event Forensic browser summary must display:

- legacy analysis scope label (`Single market` or `Whole event`);
- primary scoring scope;
- selected market details if available;
- whether related context is included;
- whether sibling markets were primary-scored;
- scope explanation.

This is copy/payload clarity only. It does not change sorting, filtering, tab order, hidden rows, or list membership.

## Export Compatibility

JSON reports receive additive fields. Markdown reports include the scope explanation and primary/context boundary. Existing CSV row-level scope columns remain available; no existing columns are renamed or removed.

Old reports and old export bundles remain loadable. There is no migration of saved artifacts.

## Non-Changes

This contract explicitly does not authorize:

- silent selected-market broadening;
- scoring weight or threshold changes;
- Strong Risk, HER, funding, or candidate-admission changes;
- Phase 3 capital-at-risk implementation;
- storage schema changes;
- UI sorting/filtering changes;
- live/RPC/network runs.

## Tests Required

- selected-market report summary contains explicit product-scope fields;
- selected-market reports keep sibling/related markets as context-only;
- whole-event reports expose `whole_event` metadata;
- old reports without product-scope fields load safely;
- browser copy contains primary scoring scope and context copy;
- sidecar audit reads local artifacts offline;
- cross-mode scoring contract remains unchanged;
- focused Event Forensic and known-case tests still pass.

## Rollback

Rollback is local and additive:

1. Remove the additive product-scope helper and field assignments.
2. Revert the browser copy additions.
3. Keep legacy `analysis_scope`, `scope_note`, and existing row-level fields intact.

No saved report migration or storage rollback is required because no schema mutation is introduced.

## Gate

Decision: `scope_semantics_contract_implementable_additive_only`.

Implementation can proceed only as additive metadata/copy. If any step requires score math, gates, storage, sorting/filtering, or selected-market broadening, stop and request a separate approval.
