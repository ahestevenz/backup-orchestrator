#!/bin/sh
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# Phase 0: assemble BNSpike.app (bnspike + the rsync from build-rsync.sh),
# ad-hoc signed like the real agent (D-07).
#
# Usage:
#   ./make-app.sh                 build and install /Applications/BNSpike.app (asks for sudo)
#   ./make-app.sh --pkg OUT.pkg   build an unsigned installer package instead (spike S5)
#
# Needs: Rust (rustup), Xcode Command Line Tools, and build-rsync.sh run first.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
RSYNC_BIN=${RSYNC_BIN:-$HOME/bnspike-build/rsync-3.4.1/rsync}
[ -x "$RSYNC_BIN" ] || { echo "no rsync at $RSYNC_BIN: run ./build-rsync.sh first" >&2; exit 1; }

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
export CARGO_TARGET_DIR="$STAGE/target"
(cd "$HERE/bnspike" && cargo build --release)

APP="$STAGE/root/Applications/BNSpike.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$CARGO_TARGET_DIR/release/bnspike" "$APP/Contents/MacOS/bnspike"
cp "$RSYNC_BIN" "$APP/Contents/Resources/rsync"
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>ar.bleiben.bnspike</string>
  <key>CFBundleName</key><string>BNSpike</string>
  <key>CFBundleExecutable</key><string>bnspike</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.0.1</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
</dict>
</plist>
EOF

# Drop stray extended attributes before signing (codesign refuses some, such
# as Finder info). macOS may re-add com.apple.provenance, which shows up as
# "._" entries in the package payload; they are harmless: the signature still
# verifies after installation. Sign the inner rsync first, then the app (the
# app's seal covers Resources/).
xattr -cr "$APP"
codesign --force -s - "$APP/Contents/Resources/rsync"
codesign --force -s - "$APP"
echo "signature of the new build:"
codesign -dvvv "$APP" 2>&1 | grep -E '^(Identifier|CDHash)='

if [ "${1:-}" = "--pkg" ]; then
    OUT=${2:?usage: make-app.sh --pkg OUT.pkg}
    # pkgbuild marks app bundles "relocatable" by default: Installer would then
    # update an existing copy with the same bundle ID wherever it sits instead
    # of installing to /Applications. Turn that off, as the real build must.
    pkgbuild --analyze --root "$STAGE/root" "$STAGE/component.plist"
    plutil -replace 0.BundleIsRelocatable -bool NO "$STAGE/component.plist"
    pkgbuild --root "$STAGE/root" --component-plist "$STAGE/component.plist" \
        --identifier ar.bleiben.bnspike --version 0.0.1 --install-location / "$OUT"
    echo "package: $OUT"
else
    sudo rm -rf /Applications/BNSpike.app
    sudo ditto "$APP" /Applications/BNSpike.app
    sudo chown -R root:wheel /Applications/BNSpike.app
    echo "installed: /Applications/BNSpike.app"
fi
