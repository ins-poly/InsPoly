# Browser Offline Asset Readiness

Date: 2026-05-26

Gate: `browser_offline_assets_need_product_decision`

Runtime/UI patch in this campaign: `false`

## Summary

The browser UIs are usable in the current local workflow when their CDN runtime assets are available, but full offline boot is not ready. The UI HTML still loads React, ReactDOM, Babel standalone, and Google Fonts from remote URLs. No local vendor assets are present in this checkout.

This campaign did not download or vendor assets. Asset vendoring remains a product/local-asset decision.

## Current Asset Inventory

Source: `validation_outputs/browser_offline_asset_preflight_20260525.json`

| Metric | Count |
|---|---:|
| HTML files inspected | 2 |
| External dependencies found | 12 |
| Runtime-required boot dependencies | 6 |
| Missing local runtime assets | 6 |
| Analyst navigation links | 4 |

Runtime-required missing assets:

- React UMD for `app/browser_ui.html`
- ReactDOM UMD for `app/browser_ui.html`
- Babel standalone for `app/browser_ui.html`
- React UMD for `app/browser_event_forensic_ui.html`
- ReactDOM UMD for `app/browser_event_forensic_ui.html`
- Babel standalone for `app/browser_event_forensic_ui.html`

Remote font dependency:

- Google Fonts Inter / JetBrains Mono in both browser HTML files.

Navigation-only links:

- Polymarket profile/market links.
- Polygon explorer links.

## Current Fallback Behavior

The local app serves the HTML through `app/browser_desktop.py`, and report data is local. If CDN scripts are unavailable, the React app cannot boot. The Python server and saved report data are still local, but the browser UI runtime is unavailable.

There is no checked-in local React/ReactDOM/Babel fallback path today.

## Safe Future Patch

A future asset patch should be limited to asset loading only:

- add exact local runtime files under a clear vendor path;
- change HTML script/font references to local paths or add a deterministic local-first fallback;
- keep browser UI layout, sorting, filtering, labels, and report data behavior unchanged;
- keep analyst navigation links external;
- add smoke tests for both scanner and Event Forensic browser pages.

Recommended local candidates from the existing preflight tool:

- `app/vendor/react.development.js`
- `app/vendor/react-dom.development.js`
- `app/vendor/babel.min.js`

Fonts require a separate decision. They can remain remote with system-font fallback, or a future patch can vendor specific font files if size and licensing are explicitly accepted.

## Product Choices Needed

1. Whether to vendor React/ReactDOM/Babel in the repository.
2. Whether to keep Google Fonts remote or vendor fonts.
3. Whether offline support must be strict, or whether the app may require network for UI boot.
4. Whether minified production assets are required, or current development UMD assets are acceptable for the local desktop app.

## Stop Conditions

Stop before:

- UI redesign;
- sorting/filtering changes;
- report schema changes;
- broad asset downloading;
- adding tracking/analytics/CDN substitutions;
- changing saved report loading behavior.

## Release Readiness

Browser offline assets are not release-ready for strict offline operation.

Browser analyst functionality is locally usable with current network/CDN availability and saved report data. Strict offline mode needs an explicit product/local asset decision before implementation.
