#!/usr/bin/env bash
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# Linux integration suite (CLAUDE.md §8): one server and two Debian 12 hosts
# with systemd, the real agent .deb, the real control key, rrsync and rsync.
#
# Needs: docker compose, and in ../../../dist: bn-backup-agent_<v>_amd64.deb
# and bn_backup-<v>-py3-none-any.whl (CI builds them first).
# Usage: tests/integration/linux/run.sh
set -euo pipefail
cd "$(dirname "$0")"

DC="docker compose"
PASS=0
step() { printf '\n=== %s\n' "$*"; }
ok() { PASS=$((PASS + 1)); echo "ok: $*"; }
fail() { echo "FAIL: $*" >&2; $DC logs --tail=50 >&2 || true; exit 1; }

srv() { $DC exec -T -u operator -e SSHPASS=admin-pass -e BN_BACKUP_TEST_CLONE=copy -e HOME=/home/operator server "$@"; }
bn() { srv /home/operator/venv/bin/bn-backup "$@"; }
host() { local h=$1; shift; $DC exec -T "$h" "$@"; }
expect() { # expect CODE command...
    local want=$1; shift
    set +e; "$@"; local got=$?; set -e
    [ "$got" = "$want" ] || fail "expected exit $want, got $got: $*"
}
state() { srv python3 -c "import json,sys; print(json.load(open('/srv/backup/bn-backup/.state/run.json'))$1)"; }
# Every entry with mtime and size; probes (D-56) and the mtime of .state/ itself
# (the run's drive write test, D-54) are left out.
listing() { srv sh -c 'cd /srv/backup/bn-backup && find . -path "./.staging/*/*/.probe" -prune -o -print0 | sort -z | xargs -0 stat -c "%n %Y %s"' | grep -v '^\./\.state '; }

write_config() { # write_config EXTRA_SETTINGS EXTRA_MODULES
    srv sh -c "mkdir -p ~/.config/bn-backup && chmod 700 ~/.config/bn-backup && cat > ~/.config/bn-backup/config.yml && chmod 600 ~/.config/bn-backup/config.yml" <<EOF
version: 2
server:
  backup_directory: /srv/backup/bn-backup
  ssh_host: server.test.lan
  receive_user: operator
settings:
  wake: {enabled: false}
  max_parallel_hosts: 2
$1
hosts:
  host1: {address: host1.test.lan, admin_user: admin}
  host2: {address: host2.test.lan, admin_user: admin}
modules:
  alice-docs: {host: host1, user: alice, src_path: /home/alice/docs}
  bob-docs: {host: host2, user: bob, src_path: /home/bob/docs}
  bob-photos: {host: host2, user: bob, src_path: /mnt/photos/Photos}
$2
EOF
}

photos_drive() { # mount a small "photo drive" (tmpfs) on host2
    host host2 sh -c 'mkdir -p /mnt/photos && (mountpoint -q /mnt/photos || mount -t tmpfs -o size=64m tmpfs /mnt/photos) \
        && mkdir -p /mnt/photos/Photos && echo raw-1 > /mnt/photos/Photos/DSC_0001.NEF && chown -R bob:bob /mnt/photos/Photos'
}

trap '$DC down -v --remove-orphans >/dev/null 2>&1 || true' EXIT

step "start the containers"
$DC up -d --build
for h in host1 host2; do
    for _ in $(seq 60); do host "$h" systemctl is-active --quiet ssh && break; sleep 1; done
done
WHEEL=$(ls ../../../dist/bn_backup-*-py3-none-any.whl | head -1)
DEB=$(ls ../../../dist/bn-backup-agent_*_amd64.deb | head -1)
srv sh -c "python3 -m venv ~/venv && ~/venv/bin/pip install -q /dist/$(basename "$WHEEL")"

step "source data"
host host1 sh -c 'mkdir -p /home/alice/docs && echo "letter v1" > /home/alice/docs/letter.txt && chown -R alice:alice /home/alice/docs'
host host2 sh -c 'mkdir -p /home/bob/docs && echo "notes" > /home/bob/docs/notes.txt && chown -R bob:bob /home/bob/docs'
photos_drive

step "server init"
bn server init >/dev/null || true # first run writes the template
write_config "" ""
expect 0 bn server init
ok "server init"

step "bootstrap with passwords (sshpass, harness only)"
expect 0 bn hosts bootstrap --agent-package "/dist/$(basename "$DEB")"
ok "bootstrap"

step "the control key cannot open a shell or copy files"
out=$(srv ssh -i /home/operator/.ssh/bn-backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes admin@host1.test.lan id 2>&1 || true)
echo "$out" | grep -q '"not_allowed"' || fail "control key ran: $out"
echo "$out" | grep -q 'uid=' && fail "control key opened a shell"
set +e
srv scp -i /home/operator/.ssh/bn-backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes /etc/hostname admin@host1.test.lan:/tmp/x >/dev/null 2>&1
[ $? -ne 0 ] || fail "scp with the control key worked"
set -e
host host1 test ! -e /tmp/x || fail "scp left a file"
ok "control key is locked"

step "status and a COMPLETE run"
expect 0 bn status
expect 0 bn run
[ "$(state "['status']")" = COMPLETE ] || fail "not COMPLETE"
srv test -f /srv/backup/bn-backup/current/alice-docs/docs/letter.txt || fail "alice's file missing"
srv test -f /srv/backup/bn-backup/current/bob-photos/Photos/DSC_0001.NEF || fail "bob's photo missing"
srv test -f /srv/backup/bn-backup/current/alice-host1/alice/.bashrc || fail "host-config dotfiles missing"
ok "COMPLETE"

step "a stopped host: NOT STARTED, nothing staged"
before=$(listing)
$DC stop host2 >/dev/null
expect 1 bn run
[ "$(listing)" = "$before" ] || fail "something changed under backup_directory"
$DC start host2 >/dev/null
for _ in $(seq 60); do host host2 systemctl is-active --quiet ssh && break; sleep 1; done
photos_drive
ok "NOT STARTED when a host is off"

step "a new user without hosts configure: NOT STARTED"
host host1 sh -c 'mkdir -p /home/bob/more && echo x > /home/bob/more/x && chown -R bob:bob /home/bob/more'
write_config "" "  bob-more: {host: host1, user: bob, src_path: /home/bob/more}"
expect 1 bn run
expect 0 bn hosts configure host1
expect 0 bn run
ok "configure needed for a new user"

step "a module fails mid-run: UNFINISHED, current/ unchanged; fixed: only it runs"
host host2 sh -c 'echo secret > /home/bob/docs/secret && chown root:root /home/bob/docs/secret && chmod 600 /home/bob/docs/secret'
host host1 sh -c 'echo "letter v2" > /home/alice/docs/letter.txt'
current_before=$(srv sh -c 'cd /srv/backup/bn-backup/current && find . -type f -exec md5sum {} + | sort')
expect 2 bn run
[ "$(state "['status']")" = UNFINISHED ] || fail "not UNFINISHED"
[ "$(state "['modules']['bob-docs']['error_kind']")" = permission ] || fail "bob-docs not permission"
[ "$(srv sh -c 'cd /srv/backup/bn-backup/current && find . -type f -exec md5sum {} + | sort')" = "$current_before" ] || fail "current/ changed"
host host2 chmod 644 /home/bob/docs/secret
expect 0 bn run
[ "$(state "['attempts']")" = 2 ] || fail "not a resumed run"
srv grep -q "letter v2" /srv/backup/bn-backup/current/alice-docs/docs/letter.txt || fail "promotion missing"
ok "UNFINISHED then COMPLETE"

step "a photo drive pulled during a run: ABORTED, staging empty"
host host2 sh -c 'head -c 400M /dev/urandom > /home/bob/docs/big.bin && chown bob:bob /home/bob/docs/big.bin'
(bn run > /tmp/bn-abort.log 2>&1; echo $? > /tmp/bn-abort.code) &
for _ in $(seq 120); do
    if srv sh -c 'ls -A /srv/backup/bn-backup/.staging/host2/bob/bob-docs/docs 2>/dev/null | grep -q big' ; then break; fi
    sleep 0.5
done
host host2 umount /mnt/photos
wait
[ "$(cat /tmp/bn-abort.code)" = 4 ] || { cat /tmp/bn-abort.log; fail "expected exit 4 (ABORTED)"; }
[ "$(state "['status']")" = ABORTED ] || fail "not ABORTED"
[ -z "$(srv find /srv/backup/bn-backup/.staging -mindepth 3)" ] || fail "staging not empty"
host host2 rm -f /home/bob/docs/big.bin
ok "ABORTED"

step "D-55: an empty folder where the drive belongs: NOT STARTED, current/ unchanged"
host host2 sh -c 'mkdir -p /mnt/photos/Photos'
expect 1 bn run
srv test -f /srv/backup/bn-backup/current/bob-photos/Photos/DSC_0001.NEF || fail "photo backup lost"
host host2 rm -rf /mnt/photos/Photos
photos_drive
expect 0 bn run
ok "drive guard"

step "a module removed from the config moves to removed/"
write_config "" ""
host host1 true
expect 0 bn run
srv test -d /srv/backup/bn-backup/removed/bob-more || fail "bob-more not in removed/"
ok "removed/"

step "snapshot mode keeps snapshot_keep backups"
write_config "  mode: snapshot
  snapshot_keep: 2" ""
for i in 1 2 3; do
    host host1 sh -c "echo v$i > /home/alice/docs/letter.txt"
    expect 0 bn run
    sleep 1
done
[ "$(srv sh -c 'ls /srv/backup/bn-backup/snapshots | wc -l')" = 2 ] || fail "snapshot count"
ok "snapshots"

step "--dry-run leaves the tree untouched"
before=$(listing)
host host1 sh -c 'echo dry > /home/alice/docs/letter.txt'
expect 0 bn run --dry-run
[ "$(listing)" = "$before" ] || fail "dry run changed something"
ok "dry run"

step "verify pass: a silent change is reported, nothing overwritten"
write_config "  verify_backup: true" ""
# Whole-second times on both sides first, as in spike S14.
host host1 sh -c 'f=/home/alice/docs/letter.txt; touch -d @$(stat -c %Y $f) $f'
expect 0 bn run
host host1 sh -c 'f=/home/alice/docs/letter.txt; t=$(stat -c %Y $f); printf "DRY\n" > $f; touch -d @$t $f'
expect 0 bn run
srv grep -q "Files to check" /srv/backup/bn-backup/current/backup_report.log || fail "no Files to check"
srv grep -q "^dry$" /srv/backup/bn-backup/current/alice-docs/docs/letter.txt || fail "backup was overwritten"
ok "verify pass"

printf '\nAll %d Linux integration scenarios passed.\n' "$PASS"
