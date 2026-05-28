#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT_DIR/packaging"
ICONSET="$OUT_DIR/InsPoly.iconset"
ICNS_PATH="$OUT_DIR/InsPoly.icns"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/inspoly_icon.XXXXXX")"
SOURCE_PNG="$TMP_DIR/InsPoly-1024.png"
SWIFT_FILE="$TMP_DIR/render_icon.swift"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$OUT_DIR"

cat > "$SWIFT_FILE" <<'SWIFT'
import AppKit
import Foundation

let output = CommandLine.arguments[1]
let size = NSSize(width: 1024, height: 1024)
let image = NSImage(size: size)

image.lockFocus()

NSColor(calibratedRed: 0.055, green: 0.320, blue: 0.345, alpha: 1.0).setFill()
NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: 1024, height: 1024), xRadius: 180, yRadius: 180).fill()

NSColor(calibratedRed: 0.920, green: 0.965, blue: 0.955, alpha: 1.0).setFill()
NSBezierPath(roundedRect: NSRect(x: 116, y: 126, width: 792, height: 772), xRadius: 112, yRadius: 112).fill()

NSColor(calibratedRed: 0.063, green: 0.416, blue: 0.438, alpha: 1.0).setFill()
NSBezierPath(roundedRect: NSRect(x: 170, y: 188, width: 684, height: 648), xRadius: 86, yRadius: 86).fill()

NSColor(calibratedRed: 0.980, green: 0.990, blue: 0.985, alpha: 1.0).setFill()
NSBezierPath(roundedRect: NSRect(x: 240, y: 584, width: 544, height: 58), xRadius: 29, yRadius: 29).fill()
NSBezierPath(roundedRect: NSRect(x: 240, y: 462, width: 382, height: 58), xRadius: 29, yRadius: 29).fill()
NSBezierPath(roundedRect: NSRect(x: 240, y: 340, width: 476, height: 58), xRadius: 29, yRadius: 29).fill()

let attrs: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: 190, weight: .heavy),
    .foregroundColor: NSColor(calibratedRed: 0.980, green: 0.990, blue: 0.985, alpha: 1.0),
    .kern: 0
]
let text = NSString(string: "IP")
let textSize = text.size(withAttributes: attrs)
let textRect = NSRect(x: (1024 - textSize.width) / 2, y: 650, width: textSize.width, height: textSize.height)
text.draw(in: textRect, withAttributes: attrs)

image.unlockFocus()

guard
    let tiff = image.tiffRepresentation,
    let bitmap = NSBitmapImageRep(data: tiff),
    let png = bitmap.representation(using: .png, properties: [:])
else {
    fputs("Unable to render InsPoly icon\n", stderr)
    exit(1)
}

try png.write(to: URL(fileURLWithPath: output))
SWIFT

/usr/bin/swift "$SWIFT_FILE" "$SOURCE_PNG"

rm -rf "$ICONSET"
mkdir -p "$ICONSET"

for spec in \
  "16 icon_16x16.png" \
  "32 icon_16x16@2x.png" \
  "32 icon_32x32.png" \
  "64 icon_32x32@2x.png" \
  "128 icon_128x128.png" \
  "256 icon_128x128@2x.png" \
  "256 icon_256x256.png" \
  "512 icon_256x256@2x.png" \
  "512 icon_512x512.png" \
  "1024 icon_512x512@2x.png"; do
  size="${spec%% *}"
  name="${spec#* }"
  /usr/bin/sips -s format png -z "$size" "$size" "$SOURCE_PNG" --out "$ICONSET/$name" >/dev/null
done

/usr/bin/iconutil -c icns "$ICONSET" -o "$ICNS_PATH"
rm -rf "$ICONSET"

echo "Created $ICNS_PATH"
