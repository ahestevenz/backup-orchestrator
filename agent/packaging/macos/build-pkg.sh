#!/bin/sh
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# Assemble BNBackupAgent.app and build bn-backup-agent-<version>.pkg
# (CLAUDE.md §7). Ad-hoc signed only: no Developer ID, no notarization (D-07).
#
# Usage: build-pkg.sh VERSION AGENT_BINARY RSYNC_DIR OUT_DIR
#   AGENT_BINARY  the (universal) bn-backup-agent
#   RSYNC_DIR     output of packaging/rsync/build-macos-universal.sh
set -eu

VERSION=${1:?usage: build-pkg.sh VERSION AGENT_BINARY RSYNC_DIR OUT_DIR}
AGENT=${2:?missing AGENT_BINARY}
RSYNC_DIR=${3:?missing RSYNC_DIR}
OUT=$(mkdir -p "${4:?missing OUT_DIR}" && cd "$4" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

APP="$STAGE/root/Applications/BNBackupAgent.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
sed "s/@VERSION@/$VERSION/g" "$HERE/Info.plist" > "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist" >/dev/null
install -m 0755 "$AGENT" "$APP/Contents/MacOS/bn-backup-agent"
install -m 0755 "$RSYNC_DIR/rsync" "$APP/Contents/Resources/rsync"
install -m 0644 "$RSYNC_DIR/rsync-COPYING" "$APP/Contents/Resources/rsync-COPYING"
install -m 0644 "$RSYNC_DIR/rsync-SOURCE.txt" "$APP/Contents/Resources/rsync-SOURCE.txt"
for f in LICENSE LICENSING.md THIRD_PARTY_NOTICES.md; do
    install -m 0644 "$REPO/$f" "$APP/Contents/Resources/$f"
done

# Sign the inner rsync, then the app (the app's seal covers Resources/).
xattr -cr "$APP"
codesign --force -s - "$APP/Contents/Resources/rsync"
codesign --force -s - "$APP"
codesign --verify --strict "$APP"

# pkgbuild marks bundles relocatable by default; Installer would then update a
# copy with the same bundle ID wherever it sits instead of /Applications.
pkgbuild --analyze --root "$STAGE/root" "$STAGE/component.plist" >/dev/null
plutil -replace 0.BundleIsRelocatable -bool NO "$STAGE/component.plist"
pkgbuild --root "$STAGE/root" --component-plist "$STAGE/component.plist" \
    --identifier ar.bleiben.bn-backup-agent --version "$VERSION" \
    --install-location / --scripts "$HERE/scripts" \
    "$OUT/bn-backup-agent-$VERSION.pkg"
echo "built $OUT/bn-backup-agent-$VERSION.pkg"
