#!/bin/sh
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# Phase 0: install (or replace) a LaunchDaemon that runs PROGRAM as USER,
# like the real per-user agent job (CLAUDE.md §5.7). Loads it; starts it only
# with --run-at-load.
#
# Usage: sudo ./install-daemon.sh NAME USER [--run-at-load] -- PROGRAM [ARGS...]
#   Label:  $LABEL.NAME          Plist: /Library/LaunchDaemons/$LABEL.NAME.plist
#   Output: $SPIKE/NAME.log      (stdout and stderr)
#
# Remove:  sudo launchctl bootout system/$LABEL.NAME
#          sudo rm /Library/LaunchDaemons/$LABEL.NAME.plist
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/spike.env"

[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
NAME=${1:?usage: install-daemon.sh NAME USER [--run-at-load] -- PROGRAM [ARGS...]}
RUN_USER=${2:?missing USER}
shift 2
RUN_AT_LOAD=false
if [ "${1:-}" = "--run-at-load" ]; then RUN_AT_LOAD=true; shift; fi
[ "${1:-}" = "--" ] && shift
[ $# -ge 1 ] || { echo "missing PROGRAM" >&2; exit 1; }

xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

mkdir -p "$SPIKE"
chmod 1777 "$SPIKE"
LOG="$SPIKE/$NAME.log"
touch "$LOG"
chmod 666 "$LOG"

PLIST="/Library/LaunchDaemons/$LABEL.$NAME.plist"
TMP=$(mktemp)
{
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$(xml "$LABEL.$NAME")</string>
  <key>UserName</key><string>$(xml "$RUN_USER")</string>
  <key>ProcessType</key><string>Standard</string>
  <key>RunAtLoad</key><$RUN_AT_LOAD/>
  <key>StandardOutPath</key><string>$(xml "$LOG")</string>
  <key>StandardErrorPath</key><string>$(xml "$LOG")</string>
  <key>ProgramArguments</key>
  <array>
EOF
    for arg in "$@"; do
        printf '    <string>%s</string>\n' "$(xml "$arg")"
    done
    cat <<'EOF'
  </array>
</dict>
</plist>
EOF
} > "$TMP"
plutil -lint "$TMP" >/dev/null

launchctl bootout "system/$LABEL.$NAME" 2>/dev/null || true
install -m 0644 -o root -g wheel "$TMP" "$PLIST"
rm -f "$TMP"
launchctl bootstrap system "$PLIST"
echo "loaded $LABEL.$NAME (runs as $RUN_USER); output: $LOG"
