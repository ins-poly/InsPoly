# Timeline Enrichment Template Pack

Date: 2026-05-25

Gate: `timeline_template_pack_ready`

Follow-up gate: `timeline_enrichment_needs_human_curation`

Machine-readable output:

- `validation_outputs/timeline_enrichment_template_pack_20260525.json`
- `validation_outputs/timeline_enrichment_template_20260525.csv`

## What Was Added

`tools/timeline_enrichment_template_pack.py` creates a human-curated timeline enrichment CSV template and validates sample rows.

Required curated fields:

- `timeline_id`
- `source_url`
- `source_timestamp_utc`
- `catalyst`

## What It Does Not Do

- It does not fetch web data.
- It does not infer timestamps.
- It does not add external prediction feeds.
- It does not change scoring, gates, HER, funding eligibility, candidate admission, storage, or UI behavior.

## Next Step

Humans may curate rows using the template. Those rows must be separately validated and explicitly approved before any runtime use.
