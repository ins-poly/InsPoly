# InsPoly Reviewer Risk Map V3

Date: 2026-05-27

Prepared from local head: `fd12c0b`

Push/PR performed: `false`

## High-Risk Review Surface

These files deserve careful review because they affect analyst-facing runtime behavior or browser boot:

| Area | Files | Review focus |
|---|---|---|
| Shared scoring and Side/Outcome semantics | `app/scanner.py`, `app/archive_scanner.py`, `app/side_outcome.py` | scoring weights/thresholds unchanged; token price vs economic probability semantics; cluster direction normalization |
| Event Forensic runtime | `app/event_forensic.py`, `app/event_forensic_performance.py` | candidate IDs, score values, rank order, review buckets, weak-history demotion, selected-market vs whole-event scope, export rows |
| Browser strict offline | `app/browser_desktop.py`, `app/browser_static_assets.py`, `app/browser_ui.html`, `app/browser_event_forensic_ui.html`, `app/event_forensic_desktop.py`, `app/vendor/browser/*` | local asset serving safety, path traversal protection, no hard remote boot dependency, no sorting/filtering changes |
| Known-case benchmark fixtures | `tests/fixtures/known_case_benchmark/post_side_outcome_known_cases.json`, `tests/fixtures/known_case_benchmark/public_case_label_intake_schema.json` | advisory controls not treated as labels; exact-wallet public labels remain 0; fixture compactness |

## Medium-Risk Review Surface

| Area | Files | Review focus |
|---|---|---|
| Event Forensic sidecars | `tools/event_forensic_*`, Event Forensic tests | tools remain offline/sidecar unless explicitly documented; live/RPC bounded where present in historical evidence |
| Phase 3 evidence | `tools/phase3_*`, `docs/inspoly_phase3_*`, Phase 3 tests | no runtime capital migration; old notional-only evidence remains unsafe |
| Replay sidecar | `app/event_forensic_replay.py`, replay tools/tests/docs | sidecar-only; no report/storage/browser persistence |
| Protocol/ledger/indexer/shadow helpers | `app/polymarket_protocol.py`, `app/polymarket_ledger.py`, `app/indexer/*`, `app/shadow_metrics.py`, `app/microstructure_context.py`, `app/trader_profile_context.py` | read-only/local-only sidecar boundaries; no CLOB auth, private keys, trading, or startup integration |

## Low-Risk / Process Review Surface

| Area | Files | Review focus |
|---|---|---|
| Strategic control layer | `AI_CONTROL/*.md`, `skills/strategic-autonomy-review/SKILL.md` | process clarity; approval gates preserved |
| Release docs | `docs/inspoly_*readiness*`, `docs/inspoly_*release*`, `docs/inspoly_*checklist*` | current-state accuracy; no overclaiming blocked gates |
| Compact validation outputs | selected `validation_outputs/*.json` | parseable, compact, referenced by docs |

## Reviewer Roles

### Scoring / Model Reviewer

Focus on:

- `app/scanner.py`
- `app/archive_scanner.py`
- `app/event_forensic.py`
- `app/side_outcome.py`
- `tests/test_cross_mode_scoring_contract.py`
- Side/Outcome and Event Forensic focused tests

Questions:

- Are scoring weights, thresholds, labels, Strong Risk/HER/funding gates unchanged unless explicitly approved?
- Are Side/Outcome economic probability semantics clear and backward-compatible?
- Do weak-history demotion and scope metadata reduce overclaiming without hiding rows?

### UI / Browser Reviewer

Focus on:

- browser HTML files;
- local vendor asset serving;
- browser label snapshots;
- strict offline readiness tests.

Questions:

- Does strict offline boot avoid hard CDN dependencies?
- Are labels clear without changing sorting/filtering behavior?
- Are legacy report shapes still normalized safely?

### Data / Provider Reviewer

Focus on:

- Event Forensic pagination/provider docs and probes;
- wallet/API boundary trace reports;
- Phase 3 source-quality docs.

Questions:

- Are pagination/provider conclusions evidence-only and not production runtime expansion?
- Does Phase 3 remain sidecar-only until stronger direct source fields exist?
- Are live/RPC measurements historical and bounded?

### Release / Process Reviewer

Focus on:

- AI_CONTROL;
- release master index and V3 docs;
- PR kit/checklists;
- staging exclusions.

Questions:

- Are local-only artifacts excluded?
- Does the branch strategy avoid direct push to `main`?
- Is the PR body honest about blocked gates and non-goals?

## Generated And Local-Only Artifacts

Keep out unless separately approved:

- `PROJECT_MEMORY.md`
- `release_manifests/`
- `shadow_review_packets/`
- `side_outcome_review_packets/`
- raw live/RPC output directories
- bulky/generated validation evidence

## Final Note

This risk map supports review planning only. It does not authorize push, PR creation, staging local-only artifacts, or runtime changes.
