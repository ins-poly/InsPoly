# Indexer Warehouse Registry - 2026-05-27

## Registry Result

Registry gate: `indexer_warehouse_registry_ready`.

Input summary:

- `validation_outputs/inspoly_indexer_warehouse_w1_manual_command_summary_20260527.json`

The registry includes 3 current local sidecar DB references. These are local-only references; raw DBs are not committed.

| Label | Classification | Markets | Trades | Cursors | Collection metadata |
| --- | --- | ---: | ---: | ---: | --- |
| `per_target_multitarget` | `active_review_candidate` | 3 | 180 | 2 | `per_target_metadata_ready` |
| `first_one_target` | `retained_reference` | 1 | 200 | 2 | `external_summary_required` |
| `same_slug_repeat` | `retained_reference` | 1 | 200 | 2 | `external_summary_required` |

Aggregate registry counts:

- Runs: 3
- Active review candidates: 1
- Retained references: 2
- Cleanup candidates: 0
- Blocked W0/W1 candidates: 0
- Markets: 5
- Public trade rows: 580
- Cursor rows: 6
- Malformed raw JSON rows: 0
- Duplicate indicators: 0

## Active Review Candidate

The active review candidate is the per-target multi-target DB:

- `.inspoly_indexer/bounded_live_multitarget_per_target_20260527/indexer.sqlite3`

Rows by target:

- `russia-x-ukraine-ceasefire-by-january-31-2026`: 60
- `maduro-in-us-custody-by-january-31`: 60
- `khamenei-out-as-supreme-leader-of-iran-by-february-28`: 60

This DB is the strongest current local warehouse review candidate because it has per-target public trade coverage metadata.

## Retained References

The first one-target DB and same-slug repeat DB remain useful retained references for the evidence chain. Their summaries do not include per-target collection metadata, so they should not supersede the active per-target candidate.

## Boundaries

The registry tool:

- used compact W1 summary JSON only;
- did not open or mutate raw DBs;
- did not delete, move, or compact artifacts;
- did not perform network calls;
- did not integrate with production runtime paths;
- did not mutate saved reports.

## Next Allowed Action

Use this registry for local retention review only. A future W3 analyst sidecar query/read command still requires a separate campaign and must remain sidecar-only unless explicitly approved.
