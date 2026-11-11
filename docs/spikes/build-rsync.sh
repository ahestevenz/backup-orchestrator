#!/bin/sh
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# Phase 0: build rsync 3.4.1 for this Mac's own CPU, with the same configure
# options the release build uses (CLAUDE.md §7). The release build is
# universal; for the spikes one architecture is enough.
#
# Usage: ./build-rsync.sh [WORK_DIR]      (default: ~/bnspike-build)
# Needs: Xcode Command Line Tools (xcode-select --install)
set -eu

VERSION=3.4.1
SHA256=2924bcb3a1ed8b551fc101f740b9f0fe0a202b115027647cf69850d65fd88c52
WORK="${1:-$HOME/bnspike-build}"

mkdir -p "$WORK"
cd "$WORK"
[ -f "rsync-$VERSION.tar.gz" ] ||
    curl -fLO "https://download.samba.org/pub/rsync/src/rsync-$VERSION.tar.gz"
echo "$SHA256  rsync-$VERSION.tar.gz" | shasum -a 256 -c -

rm -rf "rsync-$VERSION"
tar -xzf "rsync-$VERSION.tar.gz"
cd "rsync-$VERSION"
MACOSX_DEPLOYMENT_TARGET=13.0 ./configure \
    --disable-openssl --disable-xxhash --disable-zstd --disable-lz4 --disable-md2man
make -j"$(sysctl -n hw.ncpu)"

./rsync --version | head -1
echo "built: $WORK/rsync-$VERSION/rsync"
echo "rrsync: $WORK/rsync-$VERSION/support/rrsync"
