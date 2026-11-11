#!/bin/sh
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# Phase 0: install the locked control key on a host (spikes S2, S8, S12),
# the same way "ctl setup" will (CLAUDE.md §5.6 and §5.11), but pointing at
# the stand-in dispatcher. Works on macOS and Debian.
#
# Usage (on the host):  sudo ./setup-control.sh ADMIN_USER PUBKEY_FILE
# Undo:                 sudo ./setup-control.sh --remove ADMIN_USER
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DISPATCH=/usr/local/libexec/bnspike-dispatch
SUDOERS=/etc/sudoers.d/bnspike
COMMENT=bnspike-control

[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
REMOVE=false
if [ "${1:-}" = "--remove" ]; then REMOVE=true; shift; fi
ADMIN=${1:?usage: setup-control.sh ADMIN_USER PUBKEY_FILE}
HOME_DIR=$(eval echo "~$ADMIN")
[ -d "$HOME_DIR" ] || { echo "no home folder for $ADMIN" >&2; exit 1; }
GROUP=$(id -gn "$ADMIN")
AUTH="$HOME_DIR/.ssh/authorized_keys"

# Remove any earlier bnspike-control line, keep every other line.
strip_old_line() {
    [ -f "$AUTH" ] || return 0
    tmp=$(mktemp)
    grep -v " $COMMENT\$" "$AUTH" > "$tmp" || true
    cat "$tmp" > "$AUTH"
    rm -f "$tmp"
}

if $REMOVE; then
    strip_old_line
    rm -f "$SUDOERS" "$DISPATCH"
    echo "removed the control key line, $SUDOERS and $DISPATCH"
    exit 0
fi

PUBKEY_FILE=${2:?missing PUBKEY_FILE}
read -r KEYTYPE KEYDATA _ < "$PUBKEY_FILE"

# 1. The stand-in dispatcher, owned by root.
mkdir -p "$(dirname "$DISPATCH")"
install -m 0755 -o root -g "$(id -gn root)" "$HERE/dispatch.sh" "$DISPATCH"

# 2. Sudoers drop-in: only the dispatcher's "ctl" commands, no password (S8).
tmp=$(mktemp)
printf '%s ALL=(root) NOPASSWD: %s ctl *\n' "$ADMIN" "$DISPATCH" > "$tmp"
visudo -cf "$tmp"
install -m 0440 -o root -g "$(id -gn root)" "$tmp" "$SUDOERS"
rm -f "$tmp"

# 3. The locked key line in the admin account's authorized_keys (§5.11).
mkdir -p "$HOME_DIR/.ssh"
chown "$ADMIN:$GROUP" "$HOME_DIR/.ssh"
chmod 700 "$HOME_DIR/.ssh"
touch "$AUTH"
strip_old_line
printf 'restrict,command="/usr/bin/sudo -n %s ctl ssh-dispatch \\"$SSH_ORIGINAL_COMMAND\\"" %s %s %s\n' \
    "$DISPATCH" "$KEYTYPE" "$KEYDATA" "$COMMENT" >> "$AUTH"
chown "$ADMIN:$GROUP" "$AUTH"
chmod 600 "$AUTH"

echo "installed for $ADMIN:"
cat "$SUDOERS"
grep " $COMMENT\$" "$AUTH"
