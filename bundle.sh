#!/usr/bin/env bash
# Assemble Nib.app. SwiftPM only builds a bare executable, so the bundle -- and
# with it the icon, the Dock presence, and dropping files on the icon -- has to
# be put together by hand.
set -euo pipefail
cd "$(dirname "$0")"

CONFIG="${1:-release}"
swift build -c "$CONFIG"

APP="build/Nib.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp ".build/$CONFIG/Nib"      "$APP/Contents/MacOS/Nib"
cp Resources/Info.plist      "$APP/Contents/Info.plist"
cp Resources/AppIcon.icns    "$APP/Contents/Resources/"

# The Python half travels with the app, so a copied bundle still works.
cp -R nibd "$APP/Contents/Resources/nibd"
rm -rf "$APP/Contents/Resources/nibd/__pycache__"

# Ad-hoc signature: unsigned bundles get refused by Gatekeeper even locally.
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || \
  echo "note: could not sign; the app will still run from Finder after a right-click > Open"

touch "$APP"   # nudge LaunchServices into re-reading the icon
echo "built $APP"
