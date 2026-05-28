# InsPoly Sidecar Context Current Inventory

Date: 2026-05-27 EEST

Gate: `sidecar_context_keep_sidecar_only_final`

## Inventory

| Context family | Existing implementation | Evidence quality | Integration safety | Decision |
| --- | --- | --- | --- | --- |
| Shadow metrics | `app/shadow_metrics.py`, audit/evaluation tools | Medium: useful in narrow fixture/local artifact cases, but prior batch found only 3 useful advisory metrics and high duplicate/confusion risk | Safe as explicit sidecar preview/evaluation only | Keep sidecar-only |
| Trader profile | `app/trader_profile_context.py` | Medium: good static view model, but PnL can be unknown when any position lacks `total_pnl` | Safe for explicit preview, not report-copying | Keep sidecar-only |
| Microstructure | `app/microstructure_context.py`, `tools/audit_microstructure_context.py` | Medium-low: useful when snapshots exist; missing snapshots were a top unknown category | Safe for explicit DB audit only | Keep sidecar-only |
| Ledger/PnL | `app/polymarket_ledger.py`, ledger artifact audits | Medium: good accounting semantics and unknown cash handling; sample coverage remains limited | Safe for sidecar/source-quality work | Keep sidecar-only |
| Replay | `app/event_forensic_replay.py` | Medium-high for report-contained rows; old reports and all-candidate persistence remain incomplete | Safe sidecar snapshots only | Keep sidecar-only |
| Alerts/watchlists | `app/indexer/alerts.py` | Medium for static advisory alerts; no live alert runtime | Safe analyst-only sidecar storage | Keep sidecar-only |
| Preview/review packets | `tools/render_shadow_context_preview.py`, `tools/generate_shadow_review_packets.py` | Medium: useful for manual review, narrow packet sample | Safe explicit-output artifacts | Existing tools sufficient |

## B3 Decision

Do not implement a new preview index. Existing tools already provide equivalent sidecar-only index/preview behavior:

- `tools/shadow_artifact_corpus_inventory.py` inventories sidecar-relevant artifacts.
- `tools/render_shadow_context_preview.py` writes explicit preview JSON/Markdown.
- `tools/generate_shadow_review_packets.py` writes packet indexes and latest index files.
- `tools/shadow_sidecar_value_dashboard.py` consolidates Phase 10 sidecar value decisions.

Adding another indexer now would duplicate these tools and increase maintenance surface without reducing report/UI integration risk.

## Integration Safety

Report-copying and browser panels remain blocked because prior evidence found low useful metric density, duplicate/confusion risk, missing token/microstructure context, and analyst overclaim risk. Any production UI/report work requires a separate product approval and absent-safe compatibility tests.
