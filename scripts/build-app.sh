#!/usr/bin/env bash
# Builds ~/Applications/TuxPane.app for local use, signed with a stable Apple Development identity so the
# Accessibility permission survives rebuilds.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Build outside ~/Desktop: iCloud Drive adds Finder xattrs that make codesign fail.
SCRATCH="$HOME/Library/Caches/TuxPane/build"
cd "$ROOT/mac"
swift build -c release --scratch-path "$SCRATCH"
# Assemble and sign outside iCloud too: File Provider can re-add Finder info between `xattr -c` and codesign.
APP="$SCRATCH/app/TuxPane.app"
# Deliver to ~/Applications: a signed app inside the iCloud-synced Desktop can pick up Finder info again.
OUT="${TUXPANE_APP_DIR:-$HOME/Applications}/TuxPane.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$(swift build -c release --scratch-path "$SCRATCH" --show-bin-path)/TuxPane" "$APP/Contents/MacOS/TuxPane"
cp "$ROOT/mac/Info.plist" "$APP/Contents/Info.plist"
cp "$ROOT/mac/Assets/TuxPane.icns" "$APP/Contents/Resources/TuxPane.icns"
xattr -cr "$APP"
IDENTITY="${CODESIGN_IDENTITY:-$(security find-identity -v -p codesigning | awk -F'"' '/Apple Development/ {print $2; exit}')}"
if [ -z "$IDENTITY" ]; then
  # No Apple certificate: sign ad hoc. Works for your own Mac; macOS asks for Accessibility again after each rebuild.
  IDENTITY="-"
  echo "No Apple Development certificate found; signing ad hoc for this Mac."
fi
codesign --force --options runtime --sign "$IDENTITY" "$APP"
rm -rf "$OUT"
mkdir -p "$(dirname "$OUT")"
ditto "$APP" "$OUT"
codesign --verify --strict "$OUT"
echo "Built $OUT (signed by ${IDENTITY/#-/ad hoc})"
echo "Open it with: open \"$OUT\""
