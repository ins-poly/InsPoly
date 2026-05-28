# Event Forensic Subset Measurement Approval Package

Date: 2026-05-25

Gate: `subset_measurement_needs_user_approval`

## Why This Is Needed

The bounded expansion found only single-market safe targets for completed measurement. Larger locally useful whole-event examples currently exceed the 8-market campaign cap or saved candidate-wallet/raw-row bounds.

The existing evidence is enough to show the measurement path works, but not enough to choose a safe behavior-preserving performance patch for large whole-event investigations.

## Candidate Larger Event

Recommended target: `us-x-iran-permanent-peace-deal-by`

Reason:

- Local saved report had 6 analysis markets, 13,465 raw rows, 1,552 candidate rows, 427 candidate wallets, and 2 truncation markers.
- Current live resolution returns 15 markets, so whole-event measurement is blocked by the 8-market cap.
- It is more representative than the single-market safe targets while still smaller than very large examples like `us-strikes-iran-by`.

## Proposed Subset Selection Method

Use an explicit market-slug allowlist from the local saved report family, capped at 8 markets.

Rules:

- The subset must be labeled `subset_only`.
- Results must not be described as whole-event complete.
- Market slugs must be written into the run config/output before measurement.
- No automatic top-liquidity discovery or broad crawling.
- Stop if live resolver returns markets outside the approved subset.
- Stop if raw rows exceed 50,000, candidate-wallet density exceeds 150 per market, or wall time exceeds 30 minutes.

## Claims The Subset Can Support

Allowed:

- timing breakdown for the approved subset;
- whether trade collection, wallet-context loading, scoring, or report assembly dominates in the subset;
- whether truncation appears within the subset;
- whether a behavior-preserving patch RFC is worth drafting.

Not allowed:

- whole-event completeness claims;
- candidate/ranking quality claims for excluded markets;
- pagination correctness claims for the full event family;
- scorer or gate tuning decisions.

## Approval Text For A Future Run

The user can approve a later run with wording like:

```text
Approval is granted for subset-only Event Forensic performance measurement on `us-x-iran-permanent-peace-deal-by`.
Use only the explicit <=8 market slug allowlist from the local saved report family.
Label outputs as subset-only, not whole-event complete.
Do not change scorer weights, thresholds, gates, Phase 3, storage, UI sorting/filtering, or saved artifacts.
Do not use private keys, CLOB auth, trading, or order placement.
```

## Stop Conditions

- More than 8 approved market slugs are required.
- Live resolver cannot map the approved market slugs.
- The run would broaden beyond the explicit subset.
- Raw rows exceed 50,000.
- Candidate-wallet density exceeds 150 per market.
- Wall time exceeds 30 minutes.
- Any change would affect scoring, ranking, gates, storage, UI sorting/filtering, or Phase 3.
