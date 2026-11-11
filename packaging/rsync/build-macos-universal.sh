#!/bin/sh
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# Build rsync as one universal macOS binary (Apple silicon + Intel) for the
# agent package (CLAUDE.md §7, D-08). The tarball is checked against the
# pinned SHA256 before anything is built, and kept for the release (D-44).
#
# Usage: packaging/rsync/build-macos-universal.sh OUT_DIR
# Produces: OUT_DIR/rsync (universal), OUT_DIR/rsync-COPYING,
#           OUT_DIR/rsync-SOURCE.txt and OUT_DIR/rsync-<version>.tar.gz
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$(mkdir -p "${1:?usage: build-macos-universal.sh OUT_DIR}" && cd "$1" && pwd)
VERSION=$(cat "$HERE/VERSION")
TARBALL="rsync-$VERSION.tar.gz"
URL="https://download.samba.org/pub/rsync/src/$TARBALL"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

cd "$OUT"
[ -f "$TARBALL" ] || curl -fsSLO "$URL"
shasum -a 256 -c "$HERE/SHA256"

NATIVE=$(uname -m)
for ARCH in arm64 x86_64; do
    mkdir -p "$WORK/$ARCH"
    tar -xzf "$OUT/$TARBALL" -C "$WORK/$ARCH"
    cd "$WORK/$ARCH/rsync-$VERSION"
    HOST_ARG=""
    if [ "$ARCH" != "$NATIVE" ]; then
        HOST_ARG="--host=$( [ "$ARCH" = arm64 ] && echo aarch64 || echo x86_64 )-apple-darwin"
    fi
    # shellcheck disable=SC2086
    CC="clang -arch $ARCH" CFLAGS="-O2 -mmacosx-version-min=13.0" \
    MACOSX_DEPLOYMENT_TARGET=13.0 \
        ./configure $HOST_ARG --disable-openssl --disable-xxhash --disable-zstd \
        --disable-lz4 --disable-md2man >"$WORK/configure-$ARCH.log"
    make -j"$(sysctl -n hw.ncpu)" rsync >"$WORK/make-$ARCH.log"
    cp rsync "$WORK/rsync-$ARCH"
done

lipo -create "$WORK/rsync-arm64" "$WORK/rsync-x86_64" -output "$OUT/rsync"
cp "$WORK/arm64/rsync-$VERSION/COPYING" "$OUT/rsync-COPYING"
printf 'rsync %s (GPL-3.0-or-later)\nSource: %s\nThe same tarball is attached to every bleiben Backup Orchestrator release.\n' \
    "$VERSION" "$URL" > "$OUT/rsync-SOURCE.txt"
lipo -info "$OUT/rsync"
"$OUT/rsync" --version | head -1
