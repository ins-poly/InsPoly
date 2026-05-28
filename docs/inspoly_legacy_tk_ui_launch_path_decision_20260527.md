# InsPoly Legacy Tk UI Launch Path Decision

Date: 2026-05-27

Base commit: `a8af847` - `Add known-case benchmark maintenance checklist`

Runtime behavior changed: `false`

Push/PR performed: `false`

Gate decision: `legacy_tk_ui_frozen_reference_only`

## Strategic Campaign Brief Summary

The release UI path is the local browser UI. The legacy Tk module in `app/desktop.py` remains in the tree, but current CLI entrypoints and launcher scripts do not route normal users to it.

The safest decision is to freeze Tk as historical/reference-only instead of deleting it or reviving it as a supported fallback.

## Current Launch Path

| User command or launcher | Actual target | Browser-backed? | Tk-backed? |
|---|---|---:|---:|
| `python3 -m app desktop` | `app.browser_desktop.launch_browser_desktop_app()` | yes | no |
| `python3 -m app archive-desktop` | `app.browser_desktop.launch_archive_research_browser_app()` | yes | no |
| `python3 -m app event-desktop` | `app.event_forensic_desktop.launch_event_forensic_browser_app()` | yes | no |
| `Launch InsPoly.command` | `python3 -m app desktop` | yes | no |
| `Launch InsPoly Archive Researcher.command` | `python3 -m app archive-desktop` | yes | no |
| `Launch InsPoly Event Forensic Analyzer.command` | `python3 -m app event-desktop` | yes | no |
| Direct Python import of `app.desktop.launch_desktop_app()` | `DesktopApp().run()` | no | yes |

The command router is `app/cli.py`.

## Reference Audit

Repository references show:

- `app/cli.py` imports browser launch functions for active desktop commands.
- `README.md`, `docs/PROGRAMS.md`, `docs/OPERATIONS.md`, and `docs/ARCHITECTURE.md` document the active launch path as browser UI / CLI.
- `tests/test_app_workflow_contracts.py` imports `app.desktop` only to keep the legacy launch helper importable and to avoid opening a real window in tests.
- No `python3 -m app ...` command routes to `app.desktop`.

## Legacy Tk Risk Summary

`app/desktop.py` is still informative as an older local UI reference, but it is not release UI:

- it carries old label casing such as `Worth a look`;
- it owns independent sort/filter UI code that should not be treated as the browser UI contract;
- it does not represent Event Forensic scope semantics, weak-history demotion warnings, browser offline assets, replay decisions, or current release-readiness state;
- updating it as if it were supported fallback would require a separate test and UX campaign;
- deleting it could remove historical context and break direct import tests without a clear product benefit.

No storage mutation or saved-artifact behavior was changed by this decision. The only code change is a source comment marking the legacy status.

## Decision Options

| Option | Product leverage | Regression risk | Maintenance burden | Evidence readiness | Approval load | Decision |
|---|---:|---:|---:|---:|---:|---|
| Freeze as historical/reference-only | high | low | low | high | low | chosen |
| Keep as supported fallback | medium | medium-high | high | low | medium | rejected for now |
| Retire/delete | medium | high | low after deletion | medium | high | RFC-only later |
| Leave as-is | low | low immediate / medium future | medium | high | low | rejected |

## Chosen Decision

Gate: `legacy_tk_ui_frozen_reference_only`.

`app/desktop.py` is retained as historical/reference-only. The supported release UI path remains:

- `python3 -m app desktop`
- `python3 -m app archive-desktop`
- `python3 -m app event-desktop`

All three route to browser-backed local UIs.

## Future-Agent Rules

Future agents must not:

- route `python3 -m app desktop` to `app.desktop` without explicit approval;
- update Tk labels/sorting/filtering as if they were the release UI contract;
- delete `app/desktop.py` without a separate retirement RFC and dependency check;
- use Tk UI behavior as evidence for current browser UI behavior;
- treat this freeze as permission to change scoring, gates, report schemas, storage, or browser sorting/filtering.

Future agents may:

- inspect `app/desktop.py` for historical context;
- keep the import/delegation test passing;
- propose a separate retirement RFC if the owner wants to remove it later.

## Verification

Required checks for this campaign:

- `python3 -m py_compile app/desktop.py tests/test_app_workflow_contracts.py`
- `python3 -m unittest tests.test_app_workflow_contracts`
- JSON validation for `validation_outputs/inspoly_legacy_tk_ui_launch_path_decision_20260527.json`
- referenced-path validation
- `git diff --check`
- `git diff --cached --check`

Full suite is not required because the decision is docs/comment/static-test only and does not change launch behavior.

## Rollback / Retirement Notes

Rollback this campaign by reverting:

- the `app/desktop.py` comment;
- the static launch-path test;
- this decision report and JSON;
- related AI_CONTROL state entries.

If retirement is desired later, create an RFC that proves:

- no active launcher, CLI path, test, documentation, or packaging flow depends on Tk;
- historical context is no longer needed;
- removing `app/desktop.py` does not hide compatibility lessons;
- rollback is straightforward.

## Final Status

No push or PR was performed. `PROJECT_MEMORY.md` remains local-only and must not be staged.
