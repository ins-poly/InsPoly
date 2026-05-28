#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

SKIP_FULL_SUITE=0
APP_PATH="$ROOT_DIR/dist/InsPoly.app"
DMG_PATH="$ROOT_DIR/dist/release/InsPoly.dmg"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-full-suite)
      SKIP_FULL_SUITE=1
      shift
      ;;
    --app-path)
      APP_PATH="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
      shift 2
      ;;
    --dmg-path)
      DMG_PATH="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

echo "== Python syntax =="
python3 -m py_compile app/*.py tools/*.py tests/*.py

echo "== Focused native/release tests =="
python3 -m unittest \
  tests.test_app_workflow_contracts \
  tests.test_event_forensic_review_artifacts \
  tests.test_event_forensic_performance_inventory \
  tests.test_event_forensic_performance_equivalence \
  -v

if [[ "$SKIP_FULL_SUITE" != "1" ]]; then
  echo "== Full regression suite =="
  python3 -m unittest discover -s tests -p 'test_*.py'
fi

echo "== Public repository hygiene =="
python3 tools/public_repo_checks.py --all

echo "== Browser asset checks =="
test -f app/browser_ui.html
test -f app/browser_event_forensic_ui.html
test -d app/vendor/browser
test -f app/vendor/browser/react/18.3.1/react.development.js
test -f app/vendor/browser/react-dom/18.3.1/react-dom.development.js
test -f app/vendor/browser/babel-standalone/7.29.7/babel.min.js
echo "vendored browser assets present"

if [[ -d "$APP_PATH" ]]; then
  echo "== App bundle checks =="
  test -x "$APP_PATH/Contents/MacOS/InsPoly"
  /usr/bin/plutil -lint "$APP_PATH/Contents/Info.plist"
  test -n "$(/usr/bin/find "$APP_PATH/Contents" -name browser_ui.html -print -quit)"
  test -n "$(/usr/bin/find "$APP_PATH/Contents" -name browser_event_forensic_ui.html -print -quit)"
  test -n "$(/usr/bin/find "$APP_PATH/Contents" -path '*/vendor/browser/*react.development.js' -print -quit)"
else
  echo "App bundle not found at $APP_PATH; skipping bundle checks."
fi

if [[ -f "$DMG_PATH" ]]; then
  echo "== DMG checks =="
  /usr/bin/hdiutil imageinfo "$DMG_PATH" >/dev/null
  if /usr/bin/codesign --verify --verbose=2 "$DMG_PATH"; then
    echo "DMG signature verifies"
  else
    echo "DMG is not Developer ID signed; acceptable for local builds."
  fi
  if /usr/bin/xcrun stapler validate "$DMG_PATH"; then
    echo "DMG notarization staple validates"
  else
    echo "DMG is not notarized/stapled; acceptable for local builds."
  fi
  if /usr/sbin/spctl --assess --type open --context context:primary-signature -v "$DMG_PATH"; then
    echo "Gatekeeper assessment passed"
  else
    echo "Gatekeeper assessment did not pass; expected for unsigned/non-notarized local DMGs."
  fi
  if [[ -f "$DMG_PATH.sha256" ]]; then
    (cd "$(dirname "$DMG_PATH")" && /usr/bin/shasum -a 256 -c "$(basename "$DMG_PATH").sha256")
  else
    /usr/bin/shasum -a 256 "$DMG_PATH" > "$DMG_PATH.sha256"
  fi
else
  echo "Notarized DMG not found at $DMG_PATH; skipping release artifact checks."
fi

cat <<'CHECKLIST'
== Manual macOS acceptance checklist ==
- Double-click dist/InsPoly.app and confirm the start window opens without Terminal.
- Start Recent Scanner, Archive Researcher, and Event Forensic Analyzer from the native window.
- Run one short analysis, stop it, close the window, and confirm no stuck backend process remains.
- Confirm Open outputs and Open logs open the expected local folders/files.
- Run one screen-off long run and confirm analysis continues while the Mac stays awake.
- Confirm explicit Sleep, lid close, low battery, shutdown, and user-initiated sleep limitations are documented.
- Open the local DMG and confirm it installs/opens on this Mac. If notarized later, confirm Gatekeeper accepts it on another Mac.
CHECKLIST

echo "macOS release validation checks completed"
