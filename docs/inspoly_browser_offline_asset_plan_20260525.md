# Browser Offline Asset Plan

Date: 2026-05-25

Gate: `browser_offline_assets_blocked_missing_assets`

Machine-readable output:

- `validation_outputs/browser_offline_asset_preflight_20260525.json`

## Result

The scanner and Event Forensic browser HTML files still depend on runtime CDN assets:

- React UMD
- ReactDOM UMD
- Babel standalone
- Google Fonts

Local vendor candidates were not present, so this campaign did not patch the UI.

## Counts

- HTML files inspected: 2
- External dependencies found: 12
- Runtime-required boot dependencies: 6
- Missing local runtime assets: 6
- Analyst navigation links: 4

## Safe Future Patch

A future patch may replace CDN boot assets with checked-in local files only if:

- the exact asset files are present locally or explicitly approved for vendoring;
- UI sorting/filtering behavior remains unchanged;
- the patch is limited to asset loading paths;
- browser smoke tests pass.

## Stop Conditions

Stop before:

- redesigning the browser UI;
- changing filters/sorting;
- adding network fetches;
- vendoring assets without a user decision.
