# InsPoly Browser Label Compatibility Snapshot

- Date: 2026-05-22
- Scope: static browser label contract snapshot
- Tool: `tools/browser_side_outcome_label_snapshot.py`
- Machine output: `validation_outputs/browser_side_outcome_label_snapshot_20260522.json`
- Runtime implementation: false
- Network/RPC used: false
- UI sorting/filtering changed: false
- Gate decision: `browser_label_contract_ok`

## Checks

| Check | Result |
|---|---|
| Token price label present | true |
| Economic probability label present | true |
| Raw token label present | true |
| misleading `Entry chance` copy absent | true |
| old-report fallback copy present | true |
| snapshot changed sort/filter behavior | false |

## Assessment

The browser copy distinguishes raw token price from economic probability in static source text. The snapshot does not render the UI and does not change sorting, filtering, or layout behavior.

## Gate

Decision: `browser_label_contract_ok`.
