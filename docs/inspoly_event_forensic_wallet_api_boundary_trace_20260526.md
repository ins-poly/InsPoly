# Event Forensic Wallet API Boundary Trace

Date: 2026-05-26

## Gates

- API boundary gate: `api_boundary_no_safe_patch`
- Pagination gate: `pagination_operator_plan_required`

## Scope

This campaign added additive wallet API-boundary trace metadata and ran the same approved high-density subset measurement:

- Event: `us-x-iran-permanent-peace-deal-by`
- Scope: 6 selected markets only
- Live event size: 15 markets
- Completeness claim: subset-only, not whole-event complete
- Raw live output: local-only under `validation_outputs/event_forensic_wallet_api_boundary_trace_live_20260526_122643/`
- Compact evidence: `validation_outputs/event_forensic_wallet_api_boundary_trace_20260526.json`

No scoring weights, thresholds, gates, candidate admission, review routing, exports, Phase 3 capital-at-risk behavior, storage schema, UI sorting/filtering, saved artifacts, private keys, CLOB auth, trading, or order placement were changed.

## Measurement

| Run | Raw rows | Candidates | Wallets | Total s | Score s | Wallet prefetch s | Truncated markets |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Latest scorer profile | 31,992 | 15,354 | 3,287 | 645.17 | 339.83 | 266.20 | 6 |
| Prepared scorer context | 31,980 | 15,354 | 3,292 | 678.99 | 318.00 | 303.42 | 6 |
| Wallet API trace | 31,985 | 15,354 | 3,296 | 725.10 | 341.56 | 330.98 | 6 |

The traced run stayed within measurement bounds and reported no runtime bound violations.

## API Boundary Findings

Wallet API-boundary trace summary:

- Requested wallet references: 15,354
- Unique requested wallets: 3,296
- Wallet context fetch records: 3,296
- Unique fetched wallets: 3,296
- Exact duplicate wallet-context requests: 0
- Repeated wallet references already deduped before API boundary: 12,058
- Inferred request count: 13,184, four per wallet context
- Wallet stats bundle cumulative worker time: 3,111.720626s
- Wallet positions cumulative worker time: 952.168366s
- Local wallet performance computation cumulative time: 6.189521s
- Wallet stats trade rows returned: 769,084
- Wallet position rows returned: 65,495

The cumulative worker time is higher than wall-clock prefetch time because wallet contexts are fetched concurrently. The wall-clock prefetch stage was 330.98s.

## Optimization Decision

No safe runtime API-boundary patch was implemented.

Reason:

- Event Forensic already dedupes wallet context requests by wallet before the API boundary.
- The trace found 0 exact duplicate wallet-context calls to remove.
- The remaining opportunity is not local exact-dedupe; it would require API-level batching or different request composition.
- Batching cannot be assumed equivalent without a separate API behavior proof, fallback semantics review, and bounded operator approval.

Safe future work can inspect batching only if it proves:

- identical wallet coverage;
- identical missing-data and fallback semantics;
- identical candidate IDs, scores, ranks, review routing, weak-history demotion, and exports;
- unchanged selected-market/whole-event scope;
- no persistent cache or storage schema change.

## Pagination Safety

The run again reported 6 truncated selected markets. This affects completeness and analyst interpretation, not the current score formula directly.

Current behavior is preserved:

- truncation is reported;
- subset-only claim is explicit;
- no deeper pagination is attempted automatically;
- old report compatibility remains unchanged.

Future pagination expansion must stay operator-gated. Do not implement unbounded continuation or time-window chunking without a separate bounded campaign.

## Equivalence

Static behavior snapshot before live measurement:

- Candidate rows checked: 15,353
- Export row keys checked: 15,353
- Candidate contract self-comparison: passed
- Network used: false
- Runtime behavior changed: false

The committed trace metadata is additive and does not alter candidate admission, scores, ranks, review buckets, weak-history demotion, or exports.

## Next Recommendation

Do not add another runtime optimization from this trace alone. The next useful work is either:

1. a wallet API batching proof-of-equivalence RFC with a small mocked API contract first; or
2. a pagination safety/operator campaign for bounded deeper trade collection on one selected market.

Until then, keep API-boundary behavior unchanged.
