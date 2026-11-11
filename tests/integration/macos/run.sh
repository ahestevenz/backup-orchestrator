#!/usr/bin/env bash
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# macOS integration suite (CLAUDE.md §8), for a disposable macOS machine such
# as the GitHub macos-14 runner. NEVER run it on a computer you use: it creates
# users, installs the agent, edits sudoers and changes privacy settings.
#
# The server and the agent .pkg run on the same machine and talk over SSH to
# 127.0.0.1. Two extra users (alice, bob); sources outside privacy-protected
# folders; the backup drive and a "photo drive" are Case-sensitive APFS images.
#
# Full Disk Access: the probe requires it, and only a person or MDM can grant
# it on a normal Mac. On a runner with SIP disabled the script grants it in
# the TCC database; otherwise it stops with exit 78 and says so (record it in
# docs/spikes.md; the fallback is a self-hosted macOS runner).
#
# Needs in ../../../dist: bn-backup-agent-<v>.pkg and bn_backup-<v>-py3-none-any.whl.
set -euo pipefail
cd "$(dirname "$0")"
[ "${BN_INTEGRATION_DISPOSABLE:-}" = 1 ] || {
    echo "refusing to run: set BN_INTEGRATION_DISPOSABLE=1 on a throwaway machine only" >&2
    exit 64
}

DIST=$(cd ../../../dist && pwd)
PKG=$(ls "$DIST"/bn-backup-agent-*.pkg | head -1)
WHEEL=$(ls "$DIST"/bn_backup-*-py3-none-any.whl | head -1)
ME=$(id -un)
WORK=$(mktemp -d)
BACKUP=/Volumes/BNBackup
PHOTOS=/Volumes/BNPhotos
PASS=0
step() { printf '\n=== %s\n' "$*"; }
ok() { PASS=$((PASS + 1)); echo "ok: $*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }
expect() {
    local want=$1; shift
    set +e; "$@"; local got=$?; set -e
    [ "$got" = "$want" ] || fail "expected exit $want, got $got: $*"
}
bn() { BN_BACKUP_TEST_CLONE= "$WORK/venv/bin/bn-backup" "$@"; }
state() { python3 -c "import json; print(json.load(open('$BACKUP/bn-backup/.state/run.json'))$1)"; }
image() { # image NAME MOUNTPOINT
    hdiutil create -quiet -size 512m -fs "Case-sensitive APFS" -volname "$1" -type SPARSE "$WORK/$1"
    sudo mkdir -p "$2"
    hdiutil attach -quiet -nobrowse -owners on -mountpoint "$2" "$WORK/$1.sparseimage"
}

step "Remote Login, users, images"
sudo launchctl enable system/com.openssh.sshd || true
sudo launchctl bootstrap system /System/Library/LaunchDaemons/ssh.plist 2>/dev/null || true
for u in alice bob; do
    id "$u" >/dev/null 2>&1 || sudo sysadminctl -addUser "$u" -password "pw-$u" >/dev/null 2>&1
    sudo createhomedir -c -u "$u" >/dev/null 2>&1 || true
done
sudo mkdir -p /Users/alice/bn-src && echo "letter" | sudo tee /Users/alice/bn-src/letter.txt >/dev/null
sudo chown -R alice /Users/alice/bn-src
image BNBackup "$BACKUP"
image BNPhotos "$PHOTOS"
sudo mkdir -p "$PHOTOS/Photos" && echo raw | sudo tee "$PHOTOS/Photos/DSC_0001.NEF" >/dev/null
sudo chown -R bob "$PHOTOS/Photos"

step "operator credentials for the operator connection (the runner account)"
mkdir -p ~/.ssh && chmod 700 ~/.ssh
[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
for _ in $(seq 30); do nc -z 127.0.0.1 22 && break; sleep 1; done
ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes "$ME@127.0.0.1" true || fail "no SSH to 127.0.0.1"

step "server install and init"
python3 -m venv "$WORK/venv" && "$WORK/venv/bin/pip" install -q "$WHEEL"
brew list rsync >/dev/null 2>&1 || brew install -q rsync
mkdir -p ~/.config/bn-backup && chmod 700 ~/.config/bn-backup
cat > ~/.config/bn-backup/config.yml <<EOF
version: 2
server:
  backup_directory: $BACKUP/bn-backup
  ssh_host: 127.0.0.1
  receive_user: $ME
settings:
  wake: {enabled: false}
hosts:
  localmac: {address: 127.0.0.1, admin_user: $ME}
modules:
  alice-src: {host: localmac, user: alice, src_path: /Users/alice/bn-src}
  bob-photos: {host: localmac, user: bob, src_path: $PHOTOS/Photos}
EOF
chmod 600 ~/.config/bn-backup/config.yml
expect 0 bn server init
ok "server init"

step "install the agent (bootstrap stops at Full Disk Access)"
APP=/Applications/BNBackupAgent.app
( bn hosts bootstrap --agent-package "$PKG" > "$WORK/bootstrap.log" 2>&1 ) &
BOOT=$!
for _ in $(seq 120); do [ -d "$APP" ] && grep -q "Full Disk Access" "$WORK/bootstrap.log" && break; sleep 1; done
[ -d "$APP" ] || { cat "$WORK/bootstrap.log"; fail "the agent was not installed"; }

step "grant Full Disk Access (only possible with SIP disabled)"
if csrutil status | grep -q "disabled"; then
    REQ=$(codesign -d -r- "$APP" 2>&1 | sed -n 's/^designated => //p')
    echo "$REQ" | csreq -r- -b "$WORK/csreq.bin"
    HEX=$(xxd -p "$WORK/csreq.bin" | tr -d '\n')
    sudo sqlite3 "/Library/Application Support/com.apple.TCC/TCC.db" \
        "INSERT OR REPLACE INTO access (service, client, client_type, auth_value, auth_reason, auth_version, csreq, flags) VALUES ('kTCCServiceSystemPolicyAllFiles', 'ar.bleiben.bn-backup-agent', 0, 2, 4, 1, X'$HEX', 0);"
else
    kill "$BOOT" 2>/dev/null || true
    echo "Full Disk Access cannot be granted here: SIP is enabled on this runner." >&2
    echo "Record this in docs/spikes.md; the fallback is a self-hosted runner (CLAUDE.md §8)." >&2
    exit 78
fi
wait "$BOOT" || { cat "$WORK/bootstrap.log"; fail "bootstrap failed"; }
ok "bootstrap"

step "COMPLETE"
expect 0 bn status
expect 0 bn run
[ "$(state "['status']")" = COMPLETE ] || fail "not COMPLETE"
test -f "$BACKUP/bn-backup/current/bob-photos/Photos/DSC_0001.NEF" || fail "photo missing"
ok "COMPLETE"

step "UNFINISHED, then retry: COMPLETE"
sudo sh -c 'echo secret > /Users/alice/bn-src/secret && chmod 600 /Users/alice/bn-src/secret && chown root /Users/alice/bn-src/secret'
expect 2 bn run
sudo chmod 644 /Users/alice/bn-src/secret
expect 0 bn run
ok "UNFINISHED then COMPLETE"

step "NOT STARTED: the photo drive is not connected"
hdiutil detach -quiet "$PHOTOS"
expect 1 bn run
sudo mkdir -p "$WORK/p" && hdiutil attach -quiet -nobrowse -owners on -mountpoint "$PHOTOS" "$WORK/BNPhotos.sparseimage"
ok "NOT STARTED"

step "ABORTED: the photo drive is detached during the run"
sudo dd if=/dev/urandom of="$PHOTOS/Photos/big.bin" bs=1m count=300 status=none
sudo chown bob "$PHOTOS/Photos/big.bin"
sudo sh -c 'dd if=/dev/urandom of=/Users/alice/bn-src/big.bin bs=1m count=300 status=none; chown alice /Users/alice/bn-src/big.bin'
( bn run > "$WORK/abort.log" 2>&1; echo $? > "$WORK/abort.code" ) &
for _ in $(seq 120); do ls -A "$BACKUP/bn-backup/.staging/localmac/alice/alice-src/bn-src" 2>/dev/null | grep -q big && break; sleep 0.5; done
hdiutil detach -force -quiet "$PHOTOS"
wait
[ "$(cat "$WORK/abort.code")" = 4 ] || { cat "$WORK/abort.log"; fail "expected ABORTED"; }
hdiutil attach -quiet -nobrowse -owners on -mountpoint "$PHOTOS" "$WORK/BNPhotos.sparseimage"
ok "ABORTED (source drive)"

step "ABORTED: the backup drive is detached during the run; marker, then clean-up"
( bn run > "$WORK/abort2.log" 2>&1; echo $? > "$WORK/abort2.code" ) &
for _ in $(seq 120); do ls -A "$BACKUP/bn-backup/.staging/localmac/alice/alice-src/bn-src" 2>/dev/null | grep -q big && break; sleep 0.5; done
hdiutil detach -force -quiet "$BACKUP"
wait
[ "$(cat "$WORK/abort2.code")" = 4 ] || { cat "$WORK/abort2.log"; fail "expected ABORTED"; }
test -f ~/.local/state/bn-backup/abort-pending.json || fail "no abort marker"
hdiutil attach -quiet -nobrowse -owners on -mountpoint "$BACKUP" "$WORK/BNBackup.sparseimage"
sudo rm -f /Users/alice/bn-src/big.bin "$PHOTOS/Photos/big.bin"
expect 0 bn run
test ! -f ~/.local/state/bn-backup/abort-pending.json || fail "marker not cleaned up"
ok "ABORTED (backup drive) and clean-up"

step "schedule install renders and loads"
expect 0 sudo "$WORK/venv/bin/bn-backup" schedule install --weekly sun --at 02:00
sudo launchctl print system/ar.bleiben.bn-backup.schedule >/dev/null || fail "schedule not loaded"
expect 0 sudo "$WORK/venv/bin/bn-backup" schedule remove
ok "schedule"

printf '\nAll %d macOS integration scenarios passed.\n' "$PASS"
