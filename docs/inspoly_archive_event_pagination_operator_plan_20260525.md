# Archive/Event Pagination Operator Plan

Date: 2026-05-25

This plan is required because local evidence shows explicit truncation markers but does not prove a safe deeper pagination strategy.

## Bounds

- Max events: 1
- Max markets: 8
- Max wall time: 30 minutes
- No broad discovery
- No score, threshold, gate, storage schema, or UI changes
- Output only under a new timestamped `validation_outputs/` directory

## Procedure

1. Select one saved report with explicit `truncated_market_count > 0`.
2. Re-run only the selected event/market scope with current settings.
3. Record per-market page counts, raw trade rows, truncation markers, and elapsed time.
4. Compare candidate IDs and visible review rows against the saved report.
5. Stop if the run exceeds bounds or hits rate limits.

## Required Output

- Bounded measurement summary JSON.
- Markdown report with event/market count, row counts, truncation markers, and whether pagination evidence supports a future RFC.

## Gate

`archive_event_completeness_needs_bounded_live_measurement_for_deeper_pagination`
