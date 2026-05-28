# Event Forensic Behavior-Preserving Performance Patch RFC

Date: 2026-05-25

Gate: `performance_patch_rfc_ready`

Implementation status: RFC and executable contracts only. No runtime optimization is implemented by this document.

## Background

The approved high-density subset evidence comes from `validation_outputs/event_forensic_subset_measurement_20260525_181811/`.

The run was explicitly subset-only:

- Event: `us-x-iran-permanent-peace-deal-by`
- Selected markets: 6
- Live event markets: 15
- Whole-event completeness claim: no

The original run exceeded the prior candidate-wallet density bound and therefore remained `subset_measurement_blocked_scope`. Product/operator approval now allows using the run as RFC-only high-density performance evidence.

## Observed Bottlenecks

Summary:

- Raw rows: 31,919
- Candidate rows: 15,353
- Candidate wallets: 3,239
- Truncated markets: 6
- Total seconds: 663.47
- Previous safe-target median: 20.54s
- Subset vs previous median: 32.301x

Timing:

| Stage | Seconds | Share |
|---|---:|---:|
| `score_candidates_seconds` | 388.20 | 58.51% |
| `prefetch_wallet_context_seconds` | 236.57 | 35.66% |
| `collect_event_trades_seconds` | 14.74 | 2.22% |
| `prepare_candidate_context_seconds` | 5.31 | 0.80% |
| `assemble_report_rows_seconds` | 4.22 | 0.64% |

Derived density:

- Score seconds per candidate row: 0.025285
- Wallet-prefetch seconds per candidate wallet: 0.073038
- Candidate rows per wallet: 4.740043
- Candidate wallets per market: 539.833333
- Repeated wallet/candidate opportunities: 12,114

## Non-Negotiable Invariants

Any future implementation must preserve:

- candidate IDs;
- candidate count;
- score values;
- rank order;
- candidate admission;
- review placement/routing;
- exported rows and visibility;
- scoring weights and thresholds;
- Strong Risk/HER/funding/candidate-admission gates;
- Phase 3 capital behavior;
- storage schema;
- UI sorting/filtering.

No optimization may skip candidates, lower fetch limits, drop markets, change selected-market vs whole-event semantics, or reinterpret incomplete pagination as complete.

## Patch Option 1: Scorer Input/Context Memoization

Proposal:

Cache pure repeated scorer-input fragments during a single Event Forensic run, such as stable wallet/domain/market context projections that are currently reused across many candidate rows.

Expected benefit:

- Targets the dominant stage, `score_candidates_seconds`.
- The high-density subset had 15,353 candidate rows but 3,239 candidate wallets, giving 12,114 repeated wallet/candidate opportunities.

Risk:

- High if cache keys omit any field that can change score output.
- Medium if cached structures accidentally include mutable report objects.

Likely files:

- `app/event_forensic.py`
- Optional pure helpers in `app/event_forensic_performance.py`
- Focused tests under `tests/`

Required proof:

- Candidate IDs unchanged.
- Score values unchanged.
- Rank order unchanged.
- Candidate admission unchanged.
- Review bucket unchanged.
- Before/after replay on fixed fixture produces byte-equivalent candidate contract output.

Rollback:

- Remove memoization path and restore direct context construction.

## Patch Option 2: Wallet-Context Prefetch Dedup/Reuse

Proposal:

Keep the existing wallet-level cache behavior, but audit whether prestarted futures, wallet stats, wallet positions, or related context can be reused more consistently inside one run without changing fetched inputs.

Expected benefit:

- Targets `prefetch_wallet_context_seconds`, 236.57s / 35.66% of total.
- Per-wallet cost was 0.073038s across 3,239 wallets.

Risk:

- Medium. Wallet context must remain per-wallet and per-analysis-scope correct.
- Do not share cache across runs without a separate freshness/replay-persistence decision.

Likely files:

- `app/event_forensic.py`
- Tests with mocked wallet fetches and fixed candidate rows.

Required proof:

- Number of wallet fetch attempts does not increase.
- Candidate IDs/scores/ranks/review routing unchanged.
- Scope filtering remains selected-market or subset/event correct.

Rollback:

- Remove reuse bridge and use current wallet prefetch path.

## Patch Option 3: Timing Instrumentation

Proposal:

Add finer-grained timing fields around the scoring loop and wallet-context prefetch without changing control flow.

Potential fields:

- score loop candidates per second;
- wallet prefetch wallets per second;
- scorer progress chunk duration;
- per-stage warning metadata.

Expected benefit:

- Low runtime speed benefit, high observability benefit.
- Helps confirm whether future memoization actually improves the intended stage.

Risk:

- Low if additive-only and not used for ranking/filtering.

Likely files:

- `app/event_forensic.py`
- Browser/report display only if additive timing fields need surface area.

Required proof:

- Candidate IDs/scores/ranks unchanged.
- Old report loading tolerant when fields are absent.

Rollback:

- Remove additive timing fields.

## Patch Option 4: Replay Snapshot Reuse

Proposal:

Use existing replay snapshot sidecar payloads to compare before/after optimization contracts and optionally seed local-only validation runs from already-collected report data.

Expected benefit:

- Reduces validation cost for patch review.
- Does not by itself speed live analysis unless a separate replay execution path is approved.

Risk:

- Low for sidecar validation.
- Medium if runtime starts trusting stale snapshots without approval.

Likely files:

- `app/event_forensic_replay.py`
- sidecar validation tools/tests

Required proof:

- Snapshot contains no secrets.
- Replay comparison preserves candidate IDs/scores/ranks.
- Snapshot-only results are labeled as replay validation, not fresh live evidence.

Rollback:

- Keep snapshots sidecar-only and remove any integration hooks.

## Patch Option 5: Candidate Chunking For Operator Feedback

Proposal:

Chunk scoring progress and optional report feedback so long runs remain observable. Chunking must not skip, hide, reorder, or cap candidate rows.

Expected benefit:

- Improves operator experience on high-density runs.
- Enables clearer timeout/interrupt reporting.

Risk:

- Low if metadata-only.
- High if chunking becomes candidate admission or result pagination.

Likely files:

- `app/event_forensic.py`
- `app/event_forensic_performance.py`
- tests for chunk coverage

Required proof:

- Chunk metadata covers every row exactly once.
- Candidate IDs/scores/ranks unchanged.
- Exports still include all rows.

Rollback:

- Remove chunk metadata and use current progress messages.

## Required Tests Before Any Implementation

Executable contracts added in `tests/test_event_forensic_performance_patch_contract.py` define the minimum safety bar:

- candidate IDs must not change;
- score values must not change;
- rank order must not change;
- candidate admission/review bucket must not change;
- cache keys must be deterministic;
- chunk metadata must not hide rows;
- offline decomposition must not use network or mutate runtime behavior.

Future implementation tests must also include a fixed Event Forensic fixture with before/after candidate contract comparison.

## Stop Conditions

Stop implementation if any patch requires:

- scorer weight or threshold changes;
- candidate skipping, pruning, or cap changes;
- direct Strong Risk/HER/funding/candidate-admission changes;
- Phase 3 capital behavior;
- storage schema migration;
- UI sorting/filtering changes;
- live/RPC broad crawling;
- reclassifying subset evidence as whole-event complete.

## Decision

Gate: `performance_patch_rfc_ready`

Recommended next campaign: implement a narrow behavior-preserving patch starting with instrumentation plus scorer input/context memoization proof, or run a narrower/lower-density subset if the owner wants another measurement before implementation.
