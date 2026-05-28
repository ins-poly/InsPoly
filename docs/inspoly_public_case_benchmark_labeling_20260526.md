# InsPoly Public-Case Benchmark Labeling And Source Evidence Controls

Date: 2026-05-26

Base commit: `8300754` - `Expand known-case benchmark controls`

Runtime changed: `false`

Live/RPC used: `false`

Bounded web research used: `true`, for public source metadata only

Push/PR performed: `false`

Gate decision: `public_case_benchmark_pattern_level_only`

## Strategic Campaign Brief Summary

The benchmark had already expanded from 16 to 24 offline controls. The remaining validation gap was public-case source evidence: URLs, titles, publication dates, catalyst/public-knowledge timing, assertion levels, and explicit forbidden interpretations.

The selected path was conservative. The corpus now accepts source-backed public cases, but only at the assertion level supported by the source. No exact-wallet public case was added because no inspected public source or local artifact supplied a fixture-grade exact wallet/user/market identity chain.

## Corpus Change

| Metric | Before | After |
|---|---:|---:|
| total cases | 24 | 30 |
| required categories | 24 | 30 |
| public-case controls | 0 | 6 |
| unique public source URLs | 0 | 9 |
| exact-wallet public cases | 0 | 0 |
| named-user-only public cases | 0 | 2 |
| pattern-level-only public cases | 0 | 2 |
| market-level-only public cases | 0 | 2 |

Schema changed from `known_case_benchmark_v2` to `known_case_benchmark_v3`.

## Public Cases Added

| Case | Assertion level | Source basis | Safe use |
|---|---|---|---|
| `public_maduro_enforcement_named_user_control` | `named_user_only` | DOJ/CFTC enforcement source metadata | Named-user public case; not exact-wallet truth. |
| `public_maduro_pre_charge_market_timing_control` | `market_level_only` | Axios/Atlantic public reporting | Market-timing caution before official attribution. |
| `public_iran_military_cluster_pattern_control` | `pattern_level_only` | CBS/Cointelegraph reporting on connected accounts | Pattern-level cluster/timing benchmark only. |
| `public_zachxbt_axiom_pattern_control` | `pattern_level_only` | CoinDesk/Cointelegraph reporting | Advance-publication pattern control only. |
| `public_google_year_in_search_retrospective_control` | `market_level_only` | Atlantic secondary mention | Retrospective-only caution. |
| `public_trump_whale_high_volume_control` | `named_user_only` | Reuters-republished public trader report | High-volume public-user false-positive control. |

## Sources Used

- DOJ source: `https://www.justice.gov/usao-sdny/media/1437781/dl`
- CFTC source: `https://www.cftc.gov/media/13761/EnfGannonKenVanDykeComplaint042326/download`
- Axios source: `https://www.axios.com/2026/01/05/venezuela-polymarket-prediction-insider-trading`
- Atlantic source: `https://www.theatlantic.com/technology/2026/01/venezuela-maduro-polymarket-prediction-markets/685526/`
- CBS source: `https://www.cbsnews.com/news/betting-on-iran-war-insider-trading-concerns-prediction-markets-60-minutes/`
- Cointelegraph Iran source: `https://cointelegraph.com/news/bubblemaps-polymarket-cluster-win-military-bets`
- CoinDesk Axiom source: `https://www.coindesk.com/markets/2026/02/27/polymarket-bettors-appear-to-have-insider-traded-on-a-market-designed-to-catch-insider-traders`
- Cointelegraph Axiom source: `https://cointelegraph.com/news/suspected-insider-1-2m-zachxbt-axiom-expose`
- Reuters mirror: `https://www.investing.com/news/world-news/polymarket-says-mystery-trump-bettor-is-french-national-3680928`

Only compact metadata was recorded. No article text, raw web pages, raw reports, review packet directories, or generated evidence dumps were added.

## Schema Extension

`known_case_benchmark_v3` adds:

- `source_urls`
- `source_titles`
- `source_dates`
- `evidence_quality`
- `assertion_level`
- `public_knowledge_timing`
- `catalyst_timing`
- `requires_fresh_validation`

Allowed public assertion levels include:

- `exact_wallet_supported`
- `named_user_only`
- `pattern_level_only`
- `market_level_only`

Public-case controls must forbid:

- automatic action;
- exact-wallet detection;
- scoring/gate/routing use;
- production runtime interpretation without fresh validation.

## Deferred Or Rejected Candidates

| Candidate/source class | Decision | Reason |
|---|---|---|
| Exact-wallet public cases | deferred | No inspected public source supplied fixture-grade exact wallet identity. |
| Local `known_case_benchmarks/*` human labels | deferred/source context only | Useful calibration history, but all rows require fresh validation and funding/source fields are incomplete. |
| Raw review packet directories | rejected for fixture import | Generated/noisy local artifacts; compact source notes only. |
| Full article copies | rejected | URLs/titles/dates are enough; copying article text would be unnecessary and bulky. |
| Partial wallet snippets in articles | rejected for exact assertion | Truncated or article-only snippets are not exact-wallet benchmark truth. |

## What The Benchmark Now Proves

- Public source metadata can be tracked in compact benchmark fixtures.
- Exact-wallet assertions are refused unless source-backed.
- Pattern-level and named-user cases stay advisory and require fresh validation.
- Public-knowledge, catalyst-timing, retrospective-only, and false-positive cautions are now machine-checkable.

## What It Does Not Prove

- It does not prove exact-wallet public insider cases.
- It does not prove live recall or current provider completeness.
- It does not justify scoring weights, thresholds, gates, suppressors, candidate admission, Phase 3 runtime, storage, UI sorting/filtering, or pagination changes.
- It does not make public-source examples legal conclusions or automated accusations.

## Verification Summary

The updated fixture and runner produced:

- corpus gate: `known_case_corpus_ready`
- unified benchmark gate: `benchmark_suite_v2_ready`
- cases: `30`
- public cases: `6`
- exact-wallet public cases: `0`

Full command details are recorded in the campaign final response and `validation_outputs/inspoly_public_case_benchmark_labeling_20260526.json`.

Focused verification:

- `py_compile` passed for changed benchmark tools/tests.
- Benchmark and false-positive tests passed `31` tests.
- Focused Side/Outcome, Event Forensic, cross-mode, and scanner suites passed `269` tests.
- Phase 3 and weak-history guardrail suites passed `37` tests.
- Full unittest discovery passed `1112` tests with existing sqlite `ResourceWarning` noise and the known validation-interrupted terminal artifact message.
- JSON validation and path checks passed.

## Next Allowed Benchmark Work

The next safe step is human-curated exact-wallet evidence only if a source or local artifact can prove exact wallet/user/market identity. Until then, public cases should remain named-user, market-level, or pattern-level controls.
