#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  python3 -m venv .venv
fi

tools/create_macos_icon.sh

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[macos-app]"
.venv/bin/python -m PyInstaller --clean --noconfirm packaging/InsPoly.spec

APP_PATH="dist/InsPoly.app"
STAGING_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/inspoly_local_app.XXXXXX")"
trap 'rm -rf "$STAGING_ROOT"' EXIT
/usr/bin/ditto --norsrc --noextattr "$APP_PATH" "$STAGING_ROOT/InsPoly.app"
rm -rf "$APP_PATH"
/usr/bin/ditto --norsrc --noextattr "$STAGING_ROOT/InsPoly.app" "$APP_PATH"

if [[ -x "/usr/bin/xattr" ]]; then
  /usr/bin/find "$APP_PATH" -exec /usr/bin/xattr -c '{}' ';' -exec /usr/bin/xattr -c -s '{}' ';' 2>/dev/null
  /usr/bin/xattr -c "$APP_PATH" 2>/dev/null || true
  /usr/bin/xattr -c -s "$APP_PATH" 2>/dev/null || true
fi
if [[ -x "/usr/bin/codesign" ]]; then
  /bin/rm -rf "$APP_PATH/Contents/_CodeSignature"
  if /usr/bin/codesign --force --deep --sign - "$APP_PATH" \
    && /usr/bin/codesign --verify --deep --strict --verbose=2 "$APP_PATH"; then
    echo "Ad-hoc signature verified"
  else
    echo "Warning: built app, but local ad-hoc signing did not verify. Run production signing/notarization separately."
  fi
fi

echo "Built dist/InsPoly.app"
