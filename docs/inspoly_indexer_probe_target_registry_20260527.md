# Indexer Probe Target Registry - 2026-05-27

## Scope

This registry is a sidecar-only selection aid for bounded indexer probes. It does not authorize production integration, warehouse mode, report/UI wiring, scoring changes, CLOB authentication, trading, saved-report mutation, or background workers.

## Selection Policy

Future bounded runs should start from targets that have already produced clean sidecar evidence or have narrow local evidence. Candidate selection is intentionally conservative:

- Prefer repeat anchors that have already stored sidecar market/trade rows.
- Use exactly one replacement candidate when a prior target fails provider resolution.
- Reject large event-family slugs before live ingestion.
- Treat market/event ambiguity as a blocking condition until resolver preflight proves one canonical market.
- Keep sparse controls separate from primary replacement candidates.

## Preferred Anchors

| Slug | Classification | Evidence | Reason |
| --- | --- | --- | --- |
| `russia-x-ukraine-ceasefire-by-january-31-2026` | `preferred_repeat_anchor` | First run, same-slug repeat run, and partial multi-target run all stored one market with public trades and clean readiness. | Stable anchor for scoped compare and repeat-run validation. |
| `maduro-in-us-custody-by-january-31` | `preferred_repeat_anchor` | Partial multi-target run stored one market; local performance candidate evidence records one-market scope. | Second stable anchor for multi-target repeat validation. |

## Replacement Priority

| Priority | Slug | Classification | Evidence | Reason |
| --- | --- | --- | --- | --- |
| 1 | `khamenei-out-as-supreme-leader-of-iran-by-february-28` | `replacement_candidate` | Local Event Forensic expansion evidence records one saved analysis market and 3,600 saved raw rows. | Highest-priority replacement for the failed Iran slug if resolver preflight confirms a single market. |
| 2 | `nba-will-the-mavericks-beat-the-grizzlies-by-more-than-5pt5-points-in-their-december-4-matchup` | `sparse_control` | Local Event Forensic expansion evidence records one saved analysis market and zero saved raw rows. | Fallback sparse control if the first replacement fails or is ambiguous. |

## Failed Or Blocked Targets

| Slug | Classification | Evidence | Reason |
| --- | --- | --- | --- |
| `us-x-iran-permanent-peace-deal-by` | `failed_needs_review` | Failed provider lookup when used as an indexer market slug; local Event Forensic evidence treats it as useful event-family evidence. | Do not reuse directly until a canonical one-market slug is identified. |
| `us-strikes-iran-by` | `do_not_use` | Local evidence records 65 saved analysis markets and 179,486 saved raw rows. | Too large for bounded live indexer probes. |
| `strait-of-hormuz-traffic-returns-to-normal-by-april-30` | `do_not_use` | Local evidence records 97 saved analysis markets and 80,525 saved raw rows. | Too large for bounded live indexer probes. |
| `who-will-win-dem-nomination-for-nyc-mayor` | `do_not_use` | Local evidence records 23 saved analysis markets. | Too large for bounded live indexer probes. |

## Resolver Preflight Requirements

Before any repeat multi-target ingestion, a bounded resolver preflight must:

- Check no more than 10 candidates from this registry.
- Use public read-only provider resolution only.
- Fetch no trades and write no SQLite.
- Accept a slug only when it resolves to exactly one market row with a condition ID and canonical market slug.
- Record aliases or redirects when the canonical provider slug differs from the registry slug.
- Select exactly three targets: both anchors if still valid, plus the first valid replacement.

## Gate

Current registry gate: `indexer_probe_target_registry_ready_for_bounded_resolver_preflight`.

Warehouse/runtime integration remains blocked. This registry only prepares target selection for a bounded sidecar repeat probe.
