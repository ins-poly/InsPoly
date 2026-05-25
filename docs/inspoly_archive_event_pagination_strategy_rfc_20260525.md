# Archive/Event Pagination Strategy RFC

Date: 2026-05-25

Status: RFC only. This is not approval for broader live fetching or runtime behavior changes.

## Current Contract

Archive Scanner and Event Forensic fetch Polymarket trade pages with bounded `limit`/`offset` pagination through `app.polymarket.PolymarketClient.fetch_trades_in_range()`. Event Forensic collects per-market slices and records `truncated_market_count`, trade collection progress, and risk-class fields. Archive Scanner records `truncated_market_count` in the JSON/Markdown/Text reports.

The current local reports already expose truncation where the page cap is reached.

## Target Contract

Future pagination work must remain bounded and explicit:

- preserve max page and page-size controls;
- preserve selected-market vs whole-event scope;
- record per-market truncation markers;
- record whether a report is complete, explicitly truncated, unknown legacy, or insufficient metadata;
- avoid changing candidate admission, ranking, scoring thresholds, or gates as part of pagination metadata work.

## Possible Future Strategies

1. Keep current bounded offset pagination and improve reporting metadata only.
2. Add a bounded per-market continuation strategy when the API cap is hit.
3. Add bounded time-window chunking for large resolved markets.
4. Add operator-gated replay mode using a saved target list.

## Stop Conditions

Stop before implementation if:

- the change requires broad event discovery;
- the change changes candidate admission, scoring, ranking, thresholds, or gates;
- the change silently broadens selected-market analysis to whole-event analysis;
- source API behavior cannot be verified with bounded measurement;
- old reports would be reinterpreted as complete without metadata.

## Tests Required Before Any Patch

- explicit truncation marker propagation;
- old report fallback;
- selected-market scope does not become whole-event;
- pagination bounds enforced;
- no score/candidate/gate behavior change;
- no saved artifact mutation.

## Gate

`pagination_requires_operator_plan_before_live_expansion`
