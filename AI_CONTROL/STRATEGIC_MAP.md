# Strategic Map

Last updated: 2026-05-26 EEST.

## Product North Star
InsPoly should help a human analyst find, explain, and review suspicious Polymarket trading patterns with transparent evidence and conservative false-positive controls. It should make investigations faster without silently widening accusations, weakening review gates, or hiding uncertainty.

## Main Programs
- Recent Scanner: fast recent-window triage across selected categories.
- Archive Researcher: historical-window research with CSV/JSON/Markdown exports, visible/secondary/excluded tiers, and bulk review artifacts.
- Event Forensic Analyzer: deep investigation of one event or one selected child market, with trade replay, wallet ranking, clusters, graph output, and model-gap diagnostics.

## Supporting Systems
- Shared scanner model: base scoring and severity contracts.
- Wallet analytics: historical behavior, performance, bot-like and high-volume suppressors.
- Funding context: optional Polygon funding traces and funding-quality classification.
- Event context: timing, final outcome, public-lag, and optional offline timeline enrichment.
- Browser UIs: local analyst interfaces and legacy report loaders.
- Validation/audit tools: read-only tools for known cases, side/outcome drift, archive visibility, replay, performance, and release checks.
- Sidecar context: protocol/ledger/indexer/shadow/profile/microstructure helpers kept out of production runtime by default.

## Strategic Directions
- Highest leverage near term: improve analyst reliability and strategic review packets without changing scoring semantics.
- Performance direction: continue only from measured bottlenecks; current evidence points to wallet-context loading and event-wide trade collection, not scorer math.
- Evidence direction: build curated known-case benchmarks and source-quality sidecar evidence before any model broadening.
- Product direction: keep browser/offline and replay workflows practical, but avoid storage/report schema changes without RFCs.
- Release direction: push/PR only after an explicit user staging decision and pre-push verification matrix.

## Strategy Boundaries
- Do not optimize for more flags at the cost of false-positive controls.
- Do not treat performance work as permission to change candidate scope, pagination completeness, scoring gates, or visibility tiers.
- Do not convert sidecar evidence into production scoring without a separate approval, tests, and rollback plan.
- Do not let external GPT recommendations override current code, root memory, or explicit user instructions.
