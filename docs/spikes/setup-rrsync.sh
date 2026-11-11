#!/bin/sh
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# Phase 0, on the server Mac, as your own account (not sudo): install rrsync
# from rsync 3.4.1 and lock a test push key to one staging folder, the way
# "server init" and "hosts configure" will (CLAUDE.md §6.2, §6.3).
# Spikes S3, S13, S14.
#
# Usage:  ./setup-rrsync.sh PUSH_PUBKEY_FILE
# Undo:   ./setup-rrsync.sh --remove
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/spike.env"

VERSION=3.4.1
SHA256=2924bcb3a1ed8b551fc101f740b9f0fe0a202b115027647cf69850d65fd88c52
DIR="$HOME/bnspike"
STAGING="$BACKUP_VOL/bnspike-staging/testhost/$TESTUSER"
AUTH="$HOME/.ssh/authorized_keys"
COMMENT=bnspike-push

[ "$(id -u)" != 0 ] || { echo "run as your own account, without sudo" >&2; exit 1; }

strip_old_line() {
    [ -f "$AUTH" ] || return 0
    tmp=$(mktemp)
    grep -v " $COMMENT\$" "$AUTH" > "$tmp" || true
    cat "$tmp" > "$AUTH"
    rm -f "$tmp"
}

if [ "${1:-}" = "--remove" ]; then
    strip_old_line
    echo "removed the $COMMENT line; delete $DIR and $BACKUP_VOL/bnspike-staging by hand"
    exit 0
fi
PUBKEY_FILE=${1:?usage: setup-rrsync.sh PUSH_PUBKEY_FILE}
read -r KEYTYPE KEYDATA _ < "$PUBKEY_FILE"

# rsync >= 3.2.3 from Homebrew (macOS /usr/bin/rsync is openrsync).
RSYNC="$(brew --prefix rsync)/bin/rsync"
[ -x "$RSYNC" ] || { echo "brew install rsync" >&2; exit 1; }
"$RSYNC" --version | head -1
PY=$(command -v python3)
echo "python for rrsync: $PY ($("$PY" --version 2>&1))"

mkdir -p "$DIR"
cd "$DIR"
[ -f "rsync-$VERSION.tar.gz" ] ||
    curl -fLO "https://download.samba.org/pub/rsync/src/rsync-$VERSION.tar.gz"
echo "$SHA256  rsync-$VERSION.tar.gz" | shasum -a 256 -c -
tar -xzf "rsync-$VERSION.tar.gz" "rsync-$VERSION/support/rrsync"
sed -e "1s|.*|#!$PY|" \
    -e "s|^RSYNC = '/usr/bin/rsync'|RSYNC = '$RSYNC'|" \
    "rsync-$VERSION/support/rrsync" > rrsync
chmod 755 rrsync
grep -n '^RSYNC = ' rrsync

mkdir -p "$STAGING"
chmod 700 "$BACKUP_VOL/bnspike-staging" "$STAGING"

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$AUTH"
strip_old_line
printf 'restrict,command="%s -wo %s" %s %s %s\n' \
    "$DIR/rrsync" "$STAGING" "$KEYTYPE" "$KEYDATA" "$COMMENT" >> "$AUTH"
chmod 600 "$AUTH"
grep " $COMMENT\$" "$AUTH"
echo "pushes with this key land in: $STAGING"
