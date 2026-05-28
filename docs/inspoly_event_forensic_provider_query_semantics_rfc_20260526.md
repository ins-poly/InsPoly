# Event Forensic Provider Query Semantics RFC

Date: 2026-05-26

Status: RFC only

Decision: no production runtime implementation now

Gate: `provider_query_semantics_rfc_ready_no_runtime_change`

## Summary

Event Forensic pagination remains operator-gated. The latest evidence shows truncation is real and analyst-visible, but the tested bounded query strategies did not find material new rows or candidate-floor evidence. Production pagination expansion is therefore not justified.

Current production behavior should remain unchanged:

- fetch the selected analysis markets with bounded offset pagination;
- attempt the existing large-trade backfill slice;
- mark truncated markets;
- warn analysts that the loaded market sample is partial;
- avoid silently changing candidate admission, scoring, ranking, review routing, exports, storage, or UI sorting.

No external provider documentation was used for this RFC. The decision is based on repository code and bounded local/live evidence. Provider-side semantics that are not visible from those sources remain explicitly unknown.

## Evidence Summary

| Evidence | Scope | Key result | Decision impact |
| --- | --- | --- | --- |
| API boundary trace, commit `8de1c3a` | Iran high-density 6-market subset | 15,354 wallet references collapsed to 3,296 unique wallet context fetches; 0 exact duplicate wallet API-boundary requests; 6 truncated selected markets | No safe API-boundary dedupe patch; pagination remains a separate operator issue |
| Offline truncation inventory, commit `6818b0a` | 59 local reports, 576 markets | 28 truncated reports; 149 truncated/inferred market rows; 210 high-review, 64 weak-history demotion, and 112 sensitive saved top-slice rows affected by truncation | Truncation is analyst-relevant and must stay visible |
| Bounded 6-market deeper collection, commit `6818b0a` | Iran approved 6-market subset, two time chunks per market | Baseline 31,984 rows; deeper 31,984 rows; candidate-floor delta 0; all 6 markets still truncated | Two-window sidecar collection did not materially change evidence |
| One-market granular probe, commit `321bd53` | April 30 Iran selected market, 8 time chunks | Baseline 5,874 rows / 3,100 candidate-floor rows; granular 3,593 rows / 819 candidate-floor rows; added rows 0; provider/page cap still detected; no-new-row plateau detected | More granular splitting did not discover rows outside baseline under the current strategy |

## Current Code Semantics

The live production path calls `PolymarketClient.fetch_trades_in_range()` from `EventForensicAnalyzer._fetch_market_trade_slice()`.

Current request shape:

- endpoint: Polymarket Data API `/trades`;
- market filter: one condition id at a time for Event Forensic market slices;
- pagination: offset and limit;
- bounds: `max_trade_pages`, `trade_page_size`, and the repository constant `MAX_TRADES_OFFSET`;
- optional backfill: a second slice with `filterType=CASH` and `filterAmount` when a minimum notional is configured;
- local time filtering: rows newer than `end_ts` are skipped, rows older than `start_ts` stop the page loop;
- truncation marker: a market is considered truncated when either normal or filtered slice reaches the maximum retrievable row count.

Current report semantics:

- `truncated_market_count` is included in report summary/performance fields;
- report text warns that markets hit the public trade pagination cap and that the loaded sample is partial;
- collection risk becomes `truncated_collection_risk` or `truncated_collection_high_cost`;
- selected-market/subset scope remains explicit and must not be reinterpreted as whole-event complete.

## Observed Provider/Query Behavior

### Provider/Page Cap

Both baseline and granular probes reached the public offset/page cap on active high-volume slices. The code treats this as an operational limit, not a retryable production loop.

### No-New-Row Plateau

The one-market granular probe observed no-new-row plateaus in quiet time chunks. This indicates that some window queries returned no accepted rows under the current local time filters and endpoint behavior. It does not prove the provider has no older rows.

### Duplicate/Capped Pages

The granular probe tooling can detect duplicate page signatures and cursor stalls. In the committed April 30 market run, duplicate page count and cursor stall count were both 0. The observed blocker was not duplicate pages; it was page cap plus no-new-row plateau behavior.

### Query-Window Limit

The one-market granular strategy used 8 time chunks. It still produced no added rows beyond baseline. The active chunk remained capped, while other chunks were quiet or stopped on older rows. This suggests the current endpoint/query shape is not enough to recover missing rows simply by adding more local windows.

### Baseline Larger Than Granular

The baseline had more rows than the granular result because the baseline full-window query captured the current provider-ordered top slice, while granular windows filtered by local timestamp windows. The granular result is not a replacement for baseline and must not be used to reduce production rows.

### Why More Chunks Did Not Produce More Unique Rows

More chunks did not materially help because the limiting factor appears to be the provider/query ordering and offset cap for the active high-volume portion of the market. Splitting the local timestamp window did not force the provider to return a disjoint complete slice for each time period under the tested request shape.

### Remaining Unknowns

The repository evidence does not prove:

- whether the Data API supports a documented timestamp-sort or cursor mode for complete trade history;
- whether other filters can reliably partition a market without missing or duplicating trades;
- whether market slug, condition id, token id, outcome, side, user, or time-window queries have equivalent fallback semantics;
- whether an alternative provider endpoint returns complete historical rows with stable ordering;
- whether deeper collection would materially change scored candidates without a separate sidecar replay.

## Query Strategy Alternatives

| Strategy | Expected benefit | Risk | Correctness concern | Performance cost | Analyst impact | Required bounds/tests | Rollback |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Current baseline query | Preserves known behavior and warnings | Truncated high-volume markets stay partial | Top slice may omit older or lower-priority rows | Known cost | Current analyst warnings remain valid | Existing regression tests and truncation monitoring | No change |
| Smaller time windows | May partition high-volume history | Proven low yield in current probes | Provider may not order/filter by timestamp as assumed | More requests per market | Could imply false completeness if unlabeled | One market first, fixed chunks, row/time caps, duplicate/plateau detection | Return to baseline-only collection |
| Token/outcome split queries | May separate YES/NO or token-side liquidity | Requires exact endpoint support proof | Side/Outcome semantics can be misread if raw token and economic side are mixed | Up to 2x/4x requests | Could change candidate pool if incomplete | Contract tests for raw side/outcome normalization; compare union to baseline | Disable split and preserve baseline |
| Buyer/seller direction split | May partition BUY/SELL trade streams | Endpoint support and semantics unknown | SELL economic exposure and Phase 3 capital remain blocked | More requests and merge complexity | Could overstate completeness or side direction | Side/Outcome Phase 2/4 tests plus union/dedupe fixtures | Disable split and keep warnings |
| Wallet-specific follow-up queries | Can deepen context for already-admitted wallets | Cannot discover unknown wallets | Biases toward current candidate set | High per-wallet cost | Useful for explanation, not admission completeness | Clear label: follow-up context only; no candidate admission claims | Drop follow-up rows from primary admission |
| Market-level vs condition-level query | Could resolve slug/condition mismatch | Current code already uses condition id for market slices | Slug drift and child-market mapping can change | Moderate | Can improve audit traceability, not completeness alone | Resolver fixtures for slug drift and selected-market scope | Keep condition-id path |
| Existing alternative endpoint in code | Could compare Data/Gamma/CLOB shapes already supported | Endpoints may not expose equivalent historical trades | Mixing provider schemas can break old reports | Unknown | Only safe as sidecar validation until proven equivalent | Schema contracts, source precedence rules, old-report fallback tests | Keep alternative out of runtime |
| Replay from local saved artifacts only | No live/network risk | Cannot add missing rows | Replays known incomplete slices | Low | Good for regression, not completeness | Snapshot/replay schema tests | No runtime effect |

## Future Acceptable Evidence Threshold

Production runtime pagination expansion remains blocked unless a future bounded campaign proves all of the following:

- one named query strategy finds material new rows beyond current baseline on at least one high-value truncated market;
- new rows include candidate-floor evidence or analyst-relevant rows, not only low-notional noise;
- sidecar replay shows how candidate IDs, scores, ranks, review buckets, weak-history demotion, and exports would change;
- selected-market and whole-event scope labels remain correct;
- old reports are not reinterpreted as complete;
- request bounds, retry behavior, duplicate handling, and fallback semantics are deterministic;
- performance cost fits an operator-approved budget;
- report/UI warnings identify partial, subset, or expanded collection status without changing UI sorting/filtering;
- rollback restores current bounded offset behavior and warnings without saved artifact mutation.

Suggested materiality threshold for a future runtime RFC:

- at least 1% added candidate-floor rows, or at least 25 added candidate-floor rows for a high-volume market;
- or at least one newly discovered row that would enter high-review, weak-history demotion, or sensitive-context analysis in sidecar replay;
- plus no regression in existing known-case, Side/Outcome, Event Forensic routing, Phase 3 guardrail, and cross-mode scoring tests.

## Bounded Experiment Ladder

1. Offline inventory refresh.
   - No network.
   - Identify one market with truncation, high-review overlap, and saved baseline rows.

2. Plan-only query design.
   - Validate one event, one market, explicit output directory, and hard row/page/time limits.

3. One-query micro-probe.
   - Test exactly one alternative request shape on the selected market.
   - Max 3 pages, max 300 rows, max 5 minutes.
   - Output only compact JSON.

4. One-market bounded collection.
   - Max 8 chunks, max 31 pages per chunk, max 50,000 unique rows, max 30 minutes.
   - Compare baseline, alternative, added rows, duplicate rows, and plateau/cap markers.

5. Sidecar replay.
   - Only if rows are materially added.
   - Compare candidate IDs, scores, ranks, review buckets, weak-history demotion, exports, and warnings.

6. Runtime RFC.
   - Only if sidecar replay shows material analyst impact and preserves behavior contracts.

7. Runtime implementation.
   - Requires separate explicit approval.
   - Must remain bounded, reversible, and warning-preserving.

## Stop Conditions

Stop before runtime implementation if:

- no material new rows are found;
- new rows cannot be attributed to the selected market;
- duplicate pages or cursor stalls make completeness unclear;
- provider errors or rate limits appear;
- row/time/page caps are exceeded;
- sidecar replay is not behavior-equivalent on existing rows;
- UI/report copy would imply whole-event completeness for a selected subset;
- implementation would require storage schema changes, UI sorting/filtering changes, scoring changes, gate changes, or Phase 3 capital runtime work.

## Implementation Guardrails

Any future patch must:

- be disabled until a separate implementation approval exists;
- preserve the current bounded baseline path and warning behavior;
- keep expanded collection metadata additive;
- record source/query strategy per row or per collection slice;
- dedupe by stable trade identity;
- keep selected-market scope selected-market;
- preserve old-report loading;
- fail closed to the current baseline query when an alternative query is ambiguous;
- avoid private keys, CLOB auth, trading credentials, order placement, and saved artifact mutation.

## Report And UI Warning Implications

If a future sidecar or runtime path expands collection, reports should distinguish:

- `baseline_bounded_offset`;
- `expanded_sidecar_probe`;
- `expanded_runtime_approved`;
- `partial_provider_or_query_bound`;
- `subset_only_not_whole_event_complete`.

UI/report warnings must remain additive. They may explain the collection status, but must not reorder, filter, hide, or promote rows without separate product approval.

## Old-Report Compatibility

Old reports may have aggregate truncation status without per-market page evidence. They should continue loading as partial/unknown rather than being upgraded to complete or reinterpreted through a future query strategy.

Future expanded reports should carry explicit version metadata and collection strategy fields so old reports and new reports are not silently compared as equivalent.

## Rollback Plan

Rollback for any future implementation must:

- restore current `fetch_trades_in_range()` bounded offset behavior;
- preserve existing warning fields;
- ignore expanded-collection metadata if present;
- avoid deleting saved reports or sidecar evidence;
- keep old reports readable;
- rerun Event Forensic, Side/Outcome, Phase 3 guardrail, known-case, and cross-mode tests.

## Final Decision

Do not implement production pagination expansion now.

The evidence supports `provider_query_semantics_rfc_ready_no_runtime_change`: truncation remains real and analyst-visible, but current bounded alternative query strategies found no material added evidence and provider/query semantics remain insufficiently proven for runtime migration.
