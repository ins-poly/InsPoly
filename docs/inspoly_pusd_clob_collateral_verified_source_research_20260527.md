# InsPoly pUSD / CLOB Collateral Verified Source Research

Date: 2026-05-27 EEST

Gate: `pusd_collateral_fixture_grade_sources_added`

Runtime changed: `false`

## Research Scope

This campaign improves static source confidence for pUSD and CLOB collateral semantics only. It does not change funding runtime, Phase 3 runtime, scoring, gates, report schema, storage, browser UI, or trading behavior.

Sources reviewed:

- Polymarket contracts documentation: `https://docs.polymarket.com/resources/contracts`
- Polymarket CTF split documentation: `https://docs.polymarket.com/trading/ctf/split`
- Polymarket 101 collateral overview: `https://docs.polymarket.com/polymarket-101`
- Polymarket exchange upgrade help article: `https://help.polymarket.com/en/articles/14762452-polymarket-exchange-upgrade-april-28-2026`
- Polymarket CTF Exchange V2 repository: `https://github.com/Polymarket/ctf-exchange-v2`

## Source-Quality Matrix

| Source | Claim | Confidence | Fixture-grade? | Runtime-grade? | Unknowns |
| --- | --- | --- | --- | --- | --- |
| Polymarket contracts documentation | All Polymarket contracts are on Polygon mainnet, chain ID 137, and the docs page is the single source of truth for platform contract addresses. | High for static address inventory | Yes | No | Does not define InsPoly tracing semantics or Phase 3 max-loss source fields. |
| Polymarket contracts documentation | pUSD CollateralToken proxy is `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`. | High | Yes | No | Still not authorization to trace pUSD in funding runtime. |
| Polymarket contracts documentation | pUSD CollateralToken implementation is `0x6bBCef9f7ef3B6C592c99e0f206a0DE94Ad0925f`. | High | Yes | No | Proxy-vs-implementation handling is not needed in runtime until approved. |
| Polymarket contracts documentation | CollateralOnramp is `0x93070a847efEf7F70739046A929D47a521F5B8ee`; CollateralOfframp is `0x2957922Eb93258b93368531d39fAcCA3B4dC5854`; PermissionedRamp is `0xebC2459Ec962869ca4c0bd1E06368272732BCb08`. | High | Yes | No | Which transfers should count as funding context remains a product/accounting decision. |
| Polymarket contracts documentation | CTF Exchange V2 is `0xE111180000d2663C0091e4f400237545B87B996B`; Neg Risk CTF Exchange is `0xe2222d279d744050d28e00520010520000310F59`. | High | Yes for static reference | No | Exchange fills and settlement semantics are not funding runtime rules. |
| Polymarket CTF split documentation | pUSD is the collateral token used by CTF split flows, and the adapter handles pUSD-native CTF plumbing. | Medium-high | Yes as semantic support | No | Does not expose a per-trade collateral or max-loss field for InsPoly Phase 3. |
| Polymarket 101 and Help Center | pUSD is ERC-20 collateral on Polygon and is backed 1:1 by USDC; Yes/No pairs are fully backed. | Medium-high | Yes as contextual support | No | Does not provide enough row-level data to reinterpret old reports or Phase 3 sensitive SELL rows. |
| Polymarket CTF Exchange V2 repository | The README describes a wrapped collateral layer and PMCT/pUSD-style collateral components. | Medium | Yes as architecture support | No | Adapter addresses in the README differ from the contracts documentation, so adapter address facts need reconciliation before fixture inclusion. |

## Fixture Updates

`tests/fixtures/pusd_collateral_semantics/static_fixture_facts.json` now records official-docs source facts for:

- pUSD proxy;
- pUSD implementation;
- collateral onramp;
- collateral offramp;
- permissioned ramp;
- CTF Exchange V2.

These facts are fixture-grade only. `productionTruth` is not set, `runtimeGrade` remains false, and `classify_trade_collateral_semantics()` keeps pUSD trade collateral status `unknown` unless a future explicit runtime approval and production-truth policy exists.

Adapter address facts are intentionally not added to the fixture because the Polymarket docs and the Polymarket CTF Exchange V2 README currently disagree on CtfCollateralAdapter and NegRiskCtfCollateralAdapter addresses. The safe action is to record the discrepancy and keep adapters out of static fixture truth until reconciled.

## Phase 3 Implication

The new source facts improve address confidence, but they do not close the Phase 3 runtime blockers:

- no explicit per-trade collateral or max-loss source field was found;
- safe real sensitive-overlap SELL evidence remains unproven;
- old notional-only and display-only saved-report rows remain unsafe for reinterpretation;
- funding `unknown` remains distinct from `none`;
- pUSD tracing semantics require a future product/accounting decision.

## Decision

Static fixture-grade source facts were added. Funding runtime and Phase 3 runtime remain blocked.
