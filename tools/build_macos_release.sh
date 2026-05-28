#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

SKIP_LOCAL_BUILD=0
DRY_RUN=0
NOTARIZE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-local-build)
      SKIP_LOCAL_BUILD=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --notarize)
      NOTARIZE=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

APP_PATH="$ROOT_DIR/dist/InsPoly.app"
RELEASE_DIR="$ROOT_DIR/dist/release"
DMG_PATH="$RELEASE_DIR/InsPoly.dmg"
ENTITLEMENTS="$ROOT_DIR/packaging/entitlements.plist"
STAGING_ROOT="${INSPOLY_RELEASE_STAGING_ROOT:-$(mktemp -d "${TMPDIR:-/tmp}/inspoly_release.XXXXXX")}"
DMG_ROOT="$STAGING_ROOT/dmg_root"
STAGED_APP="$DMG_ROOT/InsPoly.app"

cleanup() {
  if [[ "${INSPOLY_KEEP_RELEASE_STAGING:-0}" != "1" && -d "$STAGING_ROOT" ]]; then
    rm -rf "$STAGING_ROOT"
  fi
}
trap cleanup EXIT

if [[ "$SKIP_LOCAL_BUILD" != "1" ]]; then
  tools/build_macos_app.sh
fi

if [[ ! -d "$APP_PATH" ]]; then
  echo "Missing local app bundle: $APP_PATH" >&2
  echo "Run tools/build_macos_app.sh first, or omit --skip-local-build." >&2
  exit 2
fi

rm -rf "$DMG_ROOT"
mkdir -p "$DMG_ROOT" "$RELEASE_DIR"
/usr/bin/ditto --norsrc --noextattr "$APP_PATH" "$STAGED_APP"

if [[ -x "/usr/bin/xattr" ]]; then
  /usr/bin/find "$STAGED_APP" -exec /usr/bin/xattr -c '{}' ';' -exec /usr/bin/xattr -c -s '{}' ';' 2>/dev/null || true
  /usr/bin/xattr -c "$STAGED_APP" 2>/dev/null || true
  /usr/bin/xattr -c -s "$STAGED_APP" 2>/dev/null || true
fi

if [[ "$DRY_RUN" == "1" ]]; then
  if [[ -x "/usr/bin/codesign" ]]; then
    /usr/bin/codesign --force --deep --sign - "$STAGED_APP" >/dev/null
    /usr/bin/codesign --verify --deep --strict --verbose=2 "$STAGED_APP"
  fi
  echo "Dry run OK: staged clean app at $STAGED_APP"
  echo "Default DMG builds locally with no Apple login or password."
  echo "Optional notarization is available only with --notarize and an existing notarytool keychain profile."
  exit 0
fi

SIGN_IDENTITY="${INSPOLY_MACOS_SIGN_IDENTITY:--}"
if [[ "$NOTARIZE" == "1" && "$SIGN_IDENTITY" == "-" ]]; then
  echo "Notarization needs INSPOLY_MACOS_SIGN_IDENTITY set to a Developer ID Application identity." >&2
  exit 2
fi

SIGN_ARGS=(--force --deep --options runtime --entitlements "$ENTITLEMENTS" --sign "$SIGN_IDENTITY")
if [[ "$SIGN_IDENTITY" != "-" ]]; then
  SIGN_ARGS+=(--timestamp)
fi

/usr/bin/codesign "${SIGN_ARGS[@]}" "$STAGED_APP"
/usr/bin/codesign --verify --deep --strict --verbose=2 "$STAGED_APP"

rm -f "$DMG_PATH" "$DMG_PATH.sha256"
/usr/bin/hdiutil create \
  -volname "InsPoly" \
  -srcfolder "$DMG_ROOT" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

if [[ "$SIGN_IDENTITY" != "-" ]]; then
  /usr/bin/codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG_PATH"
  /usr/bin/codesign --verify --verbose=2 "$DMG_PATH"
fi

if [[ "$NOTARIZE" == "1" ]]; then
  if [[ -z "${INSPOLY_NOTARYTOOL_PROFILE:-}" ]]; then
    echo "Missing INSPOLY_NOTARYTOOL_PROFILE." >&2
    echo "This script does not accept Apple ID or password environment variables." >&2
    echo "Create a notarytool keychain profile outside the repo, then rerun with --notarize." >&2
    exit 2
  fi
  /usr/bin/xcrun notarytool submit "$DMG_PATH" --keychain-profile "$INSPOLY_NOTARYTOOL_PROFILE" --wait
  /usr/bin/xcrun stapler staple "$DMG_PATH"
  /usr/bin/xcrun stapler validate "$DMG_PATH"
  /usr/sbin/spctl --assess --type open --context context:primary-signature -v "$DMG_PATH"
else
  echo "Built local DMG without notarization. Gatekeeper may warn on other Macs."
  echo "Use --notarize later only if a Developer ID identity and notarytool keychain profile already exist."
fi

/usr/bin/shasum -a 256 "$DMG_PATH" > "$DMG_PATH.sha256"

echo "Built DMG artifact: $DMG_PATH"
echo "Checksum: $DMG_PATH.sha256"
