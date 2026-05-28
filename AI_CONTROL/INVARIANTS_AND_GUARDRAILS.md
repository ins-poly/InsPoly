# Invariants And Guardrails

Last updated: 2026-05-26 EEST.

## Non-Negotiable Product Invariants
- InsPoly outputs analyst leads, not accusations or automated trading advice.
- Preserve explainability: every important scoring or routing outcome must have inspectable reasons/fields.
- Preserve local-first behavior and avoid hosted/backend assumptions unless explicitly requested.
- Preserve generated outputs as workflow artifacts; do not mutate or delete saved reports unless explicitly requested.
- Preserve backward compatibility with older report shapes unless a migration is explicitly approved.

## Approval Required Before Changing
- Scoring weights, thresholds, severity labels, suppressors, or Strong Risk / Hard Evidence Review gates.
- Candidate admission, visibility tiers, archive inclusion rules, or Event Forensic primary vs review-required routing.
- Event Forensic selected-market vs whole-event scope semantics.
- Funding quality semantics, especially `unknown` vs `none` and eligibility for hard evidence.
- Storage schema, report schema contracts, or browser payload contracts.
- Production pagination/fetch completeness behavior.
- Phase 3 capital-at-risk runtime behavior.
- Sidecar helper integration into scanner/archive/Event Forensic/browser/storage runtime paths.
- Browser build strategy, runtime Babel removal, or new frontend dependency pipeline.
- Replay embedding in reports or persistence in storage.
- New external dependencies, live network behavior, private-key/CLOB auth, trading, or order placement.
- Git staging, commits, pushes, or PRs unless explicitly requested.

## Stop Conditions
Stop and ask the operator before implementation if the task would:
- broaden inclusion criteria or make more rows primary-visible without a named product decision;
- lower false-positive controls;
- replace repository-specific compatibility logic with generic boilerplate;
- remove fallbacks, retries, legacy normalization, or API workarounds;
- treat failed funding lookup as clean evidence;
- infer final outcome truth for unresolved/live markets;
- make a large refactor where a smaller compatible change could solve the task;
- stage ignored/generated/local-only artifacts without an explicit staging policy.

## Safe Default Strategy
- Reuse existing code paths.
- Prefer additive fields and reports over breaking schema changes.
- Extend existing tests near the touched contract.
- Use sidecar/RFC/probe tools for strategic evidence before runtime integration.
- Keep external GPT advice as advisory input, then reconcile it against current code, root memory, and operator instructions.
