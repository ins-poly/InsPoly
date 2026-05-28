# Browser Offline Asset Implementation Plan

Date: 2026-05-26

Status: `planned_only_requires_product_approval`

This plan is intentionally not implemented in the current campaign.

## Recommended Implementation Campaign

1. Approve asset policy.

   Required decision: exact React, ReactDOM, Babel standalone, and optional font assets; strict local-only versus local-preferred fallback; runtime Babel versus precompiled UI.

2. Create local vendor directory.

   Planned paths:

   - `app/vendor/browser/manifest.json`
   - `app/vendor/browser/react/<version>/react.development.js`
   - `app/vendor/browser/react-dom/<version>/react-dom.development.js`
   - `app/vendor/browser/babel-standalone/<version>/babel.min.js`

3. Record provenance.

   For every asset:

   - package name
   - exact version
   - source URL
   - license
   - SHA-256
   - byte size
   - vendoring date
   - approval note

4. Add narrow static serving in `app/browser_desktop.py`.

   Requirements:

   - serve only the approved vendor directory;
   - reject path traversal;
   - keep existing API routes unchanged;
   - do not expose arbitrary local files.

5. Update browser HTML references.

   Files:

   - `app/browser_ui.html`
   - `app/browser_event_forensic_ui.html`

   Requirements:

   - preserve script order;
   - preserve labels and report rendering behavior;
   - do not change sorting/filtering;
   - keep old-report compatibility.

6. Choose font policy.

   Default recommended implementation: use system font fallback for strict offline. Vendor fonts only with explicit approval and provenance.

7. Update tests.

   Required tests:

   - strict offline readiness detects no hard remote boot dependencies;
   - local asset manifest schema is valid;
   - desktop static serving rejects path traversal;
   - browser label snapshots still pass;
   - Event Forensic UI scope/weak-history snapshots still pass if that HTML is touched.

8. Verification.

   Required checks:

   - `py_compile` for changed Python files;
   - strict offline readiness tests;
   - browser label snapshot tests;
   - Event Forensic UI tests if touched;
   - JSON validation for provenance manifest and readiness output;
   - `git diff --check`;
   - direct scan for no scoring/model/gate/Phase 3/storage/UI sorting changes.

## Stop Conditions

Stop before implementation if:

- exact asset versions are not approved;
- license/provenance cannot be recorded;
- asset sizes are unexpectedly large;
- static serving needs broad filesystem access;
- UI script extraction or Babel removal becomes necessary;
- browser label/snapshot tests show drift;
- the patch touches model/scoring/gate/storage paths.

## Non-Goals

- No broad browser UI rewrite.
- No build pipeline in the first implementation campaign.
- No model/scoring/gate changes.
- No Phase 3 runtime.
- No storage schema changes.
- No UI sorting/filtering changes.
