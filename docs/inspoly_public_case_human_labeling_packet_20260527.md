# InsPoly Public-Case Human Labeling Packet

Date: 2026-05-27

Base commit: `82fbfab` - `Add public-case evidence bridge`

Runtime changed: `false`

Live/RPC used: `false`

Push/PR performed: `false`

Gate decision: `public_case_human_labeling_packet_ready`

## Purpose

This packet gives a human reviewer or external research thread the exact evidence intake path for future public-case exact-wallet benchmark labels.

It does not accept any exact-wallet labels. It defines what evidence must be provided before a future campaign can upgrade a public benchmark case to `exact_wallet_supported`.

## Current Public Benchmark State

| Metric | Count |
|---|---:|
| total known-case corpus | 30 |
| public controls | 6 |
| exact-wallet public cases | 0 |
| named-user local wallet candidates | 0 |
| named-user-only cases | 2 |
| pattern-level-only cases | 2 |
| market-level-only cases | 2 |
| deferred exact-wallet candidates | 6 |

## Exact-Wallet Acceptance Criteria

An exact-wallet label may be accepted only if the intake provides at least one of:

- a public source explicitly publishing the full wallet address and market/user context;
- a public source naming the account/user plus a local artifact that proves the user-to-wallet mapping;
- a transaction/source trail linking named entity, wallet, market, and condition with enough specificity for fixture use;
- a human curator note with URL/path, timestamp, limitations, and fixture-grade confidence.

Reject exact-wallet upgrades based on:

- timing inference alone;
- unnamed cluster claims;
- market-level source without wallet identity;
- partial wallet snippets without reconciliation;
- "likely same user" claims without proof;
- local heuristic scores or review routing as identity evidence.

## Intake Schema

Use `tests/fixtures/known_case_benchmark/public_case_label_intake_schema.json`.

Required label fields:

- `label_id`
- `benchmark_case_id`
- `proposed_assertion_level`
- `wallet_address`
- `polymarket_username`
- `market_slug`
- `condition_id`
- `source_urls`
- `source_titles`
- `evidence_quote_short`
- `evidence_summary`
- `evidence_timestamp`
- `curator`
- `confidence`
- `limitations`
- `forbidden_interpretation`
- `review_status`
- `accepted_for_benchmark`

`evidence_quote_short` is optional in the JSON schema and must stay short when provided. Do not copy full articles or raw page text.

Validate future intake files with `tools/public_case_label_intake_validator.py`. The validator writes a compact report and never applies labels to the benchmark.

## Deferred Cases

### `known-public_maduro_enforcement_named_user_control`

Current level: `named_user_only`

Sources:

- `https://www.justice.gov/usao-sdny/media/1437781/dl`
- `https://www.cftc.gov/media/13761/EnfGannonKenVanDykeComplaint042326/download`

Known local refs:

- `validation_outputs/event_forensic_performance_expansion_candidates_20260525.json`
- `validation_outputs/event_forensic_performance_expansion_resolution_20260525.json`

Missing evidence:

- full wallet address;
- source/local artifact linking Gannon Ken Van Dyke to that wallet;
- market or condition proof.

Reviewer questions:

- Does any source explicitly publish the wallet used by Gannon Ken Van Dyke?
- Can a local artifact link that public identity to a wallet without inference?
- Which market or condition does the proof cover?

Upgrade only if the intake proves the named identity to wallet bridge. Otherwise keep `named_user_only`.

Forbidden overclaim: do not infer the exact Polymarket wallet from named-user enforcement metadata.

### `known-public_maduro_pre_charge_market_timing_control`

Current level: `market_level_only`

Sources:

- `https://www.axios.com/2026/01/05/venezuela-polymarket-prediction-insider-trading`
- `https://www.theatlantic.com/technology/2026/01/venezuela-maduro-polymarket-prediction-markets/685526/`

Known local refs:

- `validation_outputs/event_forensic_performance_expansion_candidates_20260525.json`

Missing evidence:

- wallet address;
- named user;
- specific market or condition proof tied to the wallet.

Reviewer questions:

- Is there a primary source naming a wallet for the pre-charge Maduro bets?
- Does the source prove a wallet/market pair or only anonymous market timing?
- Should the case stay market-level if no identity proof exists?

Upgrade only with source-backed identity proof. Otherwise keep `market_level_only`.

Forbidden overclaim: do not convert anonymous pre-charge market timing into exact-wallet truth.

### `known-public_iran_military_cluster_pattern_control`

Current level: `pattern_level_only`

Sources:

- `https://www.cbsnews.com/news/betting-on-iran-war-insider-trading-concerns-prediction-markets-60-minutes/`
- `https://cointelegraph.com/news/bubblemaps-polymarket-cluster-win-military-bets`

Known local refs:

- `validation_outputs/event_forensic_performance_expansion_candidates_20260525.json`
- `validation_outputs/event_forensic_granular_pagination_probe_20260526.json`

Missing evidence:

- full public wallet list or full wallet address;
- proof that the public cluster identity matches local artifact identity;
- market or condition proof for the specific wallet.

Reviewer questions:

- Does any source publish complete wallet addresses for the Iran cluster?
- Can those addresses be reconciled to local Iran event artifacts?
- Are partial addresses or screenshots enough? Current policy says no.

Upgrade only with complete wallet and market proof. Otherwise keep `pattern_level_only`.

Forbidden overclaim: do not assert that InsPoly should identify a specific wallet from connected-account reporting alone.

### `known-public_zachxbt_axiom_pattern_control`

Current level: `pattern_level_only`

Sources:

- `https://www.coindesk.com/markets/2026/02/27/polymarket-bettors-appear-to-have-insider-traded-on-a-market-designed-to-catch-insider-traders`
- `https://cointelegraph.com/news/suspected-insider-1-2m-zachxbt-axiom-expose`

Known local refs: none.

Missing evidence:

- full wallet address;
- local market/condition bridge;
- proof tying the wallet to the public Axiom/ZachXBT case.

Reviewer questions:

- Is there a source with full wallet addresses for the Axiom case?
- Can those addresses be linked to a local market/condition?
- If only snippets are available, should the case stay pattern-level?

Upgrade only with complete identity proof. Otherwise keep `pattern_level_only`.

Forbidden overclaim: do not treat partial snippets, handles, screenshots, or article summaries as exact-wallet benchmark truth.

### `known-public_google_year_in_search_retrospective_control`

Current level: `market_level_only`

Sources:

- `https://www.theatlantic.com/technology/2026/01/venezuela-maduro-polymarket-prediction-markets/685526/`

Known local refs: none.

Missing evidence:

- primary source for the market;
- wallet address;
- market or condition proof;
- catalyst timing strong enough for fixture use.

Reviewer questions:

- Is there a primary source for this market and wallet behavior?
- Does it publish wallet identity?
- Should this stay retrospective-only without primary evidence?

Upgrade only with primary source and wallet proof. Otherwise keep `market_level_only`.

Forbidden overclaim: do not use a secondary article mention as exact case evidence or runtime tuning approval.

### `known-public_trump_whale_high_volume_control`

Current level: `named_user_only`

Sources:

- `https://www.investing.com/news/world-news/polymarket-says-mystery-trump-bettor-is-french-national-3680928`

Known local refs: none.

Missing evidence:

- full wallet address;
- proof that public account/user maps to that wallet;
- specific market or condition proof.

Reviewer questions:

- Is a full Fredi/Fredi9999 wallet address source-backed and tied to this fixture source chain?
- Can it be reconciled to local artifacts without inference?
- Does the evidence still support false-positive caution rather than suspicion?

Upgrade only with source-backed identity proof. Otherwise keep `named_user_only`.

Forbidden overclaim: do not infer manipulation, insider status, or exact wallet identity solely from high volume or named handles.

## Ready-To-Paste Reviewer Prompt

```text
You are reviewing InsPoly public-case benchmark candidates for exact-wallet evidence.

Goal: decide whether any deferred public case can be upgraded to exact_wallet_supported.

For each case, provide only source-backed facts:
- full wallet address if published;
- Polymarket username/account if published;
- market slug or condition ID;
- source URL/title/date;
- a short quote or summary proving wallet/user/market linkage;
- limitations and uncertainty.

Do not infer wallet identity from timing, market-level reporting, unnamed clusters, partial wallet snippets, screenshots without reconciliation, or local heuristic scores.

Return a JSON object matching public_case_label_intake_v1. If no case is proven, mark review_status as deferred and accepted_for_benchmark as false.
```

## Validation And Application Policy

1. Human/researcher prepares an intake JSON.
2. Run `tools/public_case_label_intake_validator.py`.
3. If validation fails, do not update benchmark fixtures.
4. If validation passes with `exact_wallet_supported`, run a separate benchmark update campaign.
5. That future campaign must update fixture, docs, tests, and rollback notes.
6. No model/scoring/gate change may use unaccepted labels as proof.

## Output

Machine-readable packet:

- `validation_outputs/inspoly_public_case_human_labeling_packet_20260527.json`

Intake schema:

- `tests/fixtures/known_case_benchmark/public_case_label_intake_schema.json`

Validator:

- `tools/public_case_label_intake_validator.py`
