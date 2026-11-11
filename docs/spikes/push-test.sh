#!/bin/sh
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# Phase 0, on the source Mac, in Terminal as the admin account: push test
# data to the server Mac through rrsync with the bundled rsync and the exact
# options the agent will use (CLAUDE.md §5.9). Spikes S3, S13, S14.
#
# Usage:
#   ./push-test.sh setup    create the push key and the test files
#   ./push-test.sh all      S3 (and S13 with the server setting off)
#   ./push-test.sh s14      S14: same size and date, different content
. "$(cd "$(dirname "$0")" && pwd)/spike.env"

RSYNC=/Applications/BNSpike.app/Contents/Resources/rsync
KEY="$HOME/.ssh/bnspike_push"
SRC="$SPIKE/src/Photos"
DEST="$OPERATOR@$SERVER:mod/"
E="ssh -i $KEY -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o ServerAliveInterval=30"

push() {
    "$RSYNC" --archive --hard-links --numeric-ids --xattrs --delete -M--fake-super \
        "--log-file=$SPIKE/push.log" "--out-format=%i %n" -e "$E" --timeout=600 "$@"
    echo "exit=$?"
}
step() { printf '\n=== %s\n' "$*"; }

case "${1:-}" in
setup)
    [ -f "$KEY" ] || ssh-keygen -t ed25519 -N "" -C bnspike-push -f "$KEY"
    mkdir -p "$SRC/2019"
    printf 'raw-file-1' > "$SRC/2019/DSC_0001.NEF"
    printf 'raw-file-2' > "$SRC/2019/DSC_0002.NEF"
    ln -f "$SRC/2019/DSC_0001.NEF" "$SRC/2019/DSC_0001-hardlink.NEF"
    xattr -w com.bleiben.tag keeper "$SRC/2019/DSC_0001.NEF"
    chmod 640 "$SRC/2019/DSC_0002.NEF"
    echo "test files in $SRC"
    echo "copy this public key to the server Mac and run setup-rrsync.sh with it:"
    echo "  $KEY.pub"
    ;;
all)
    step "1. transfer (with --partial): expect exit=0"
    push --partial "$SRC" "$DEST"
    step "2. --dry-run: expect exit=0"
    push --dry-run "$SRC" "$DEST"
    step "3. verify pass --checksum --dry-run: expect exit=0, no file lines"
    push --checksum --dry-run "$SRC" "$DEST"
    step "4. --delete: remove DSC_0002 locally, push, expect '*deleting' and exit=0"
    mv "$SRC/2019/DSC_0002.NEF" "$SPIKE/DSC_0002.NEF.saved"
    push "$SRC" "$DEST"
    mv "$SPIKE/DSC_0002.NEF.saved" "$SRC/2019/DSC_0002.NEF"
    push "$SRC" "$DEST"
    step "5. probe-style push into .probe/: expect exit=0"
    tmp=$(mktemp -d)
    date -u +%Y-%m-%dT%H:%M:%SZ > "$tmp/probe"
    push --recursive "$tmp/" "$OPERATOR@$SERVER:.probe/"
    rm -rf "$tmp"
    step "6. reading back must be REFUSED: expect an rrsync error and a non-zero exit"
    "$RSYNC" -a -e "$E" "$OPERATOR@$SERVER:mod/" "$SPIKE/readback/"
    echo "exit=$?"
    ;;
s14)
    f="$SRC/s14.bin"
    step "upload the original (content AAAAAAAA)"
    printf 'AAAAAAAA' > "$f"
    touch -t 202001010000 "$f"
    push "$SRC" "$DEST"
    step "change the content, keep size and date"
    printf 'BBBBBBBB' > "$f"
    touch -t 202001010000 "$f"
    step "plain --dry-run: expect NO line for Photos/s14.bin"
    push --dry-run "$SRC" "$DEST"
    step "verify pass --checksum --dry-run: expect '<fc......... Photos/s14.bin' (c set, s and t '.')"
    push --checksum --dry-run "$SRC" "$DEST"
    echo
    echo "Now, on the server Mac, this must still print AAAAAAAA (nothing was transferred):"
    echo "  cat $BACKUP_VOL/bnspike-staging/testhost/$TESTUSER/mod/Photos/s14.bin"
    ;;
*)
    echo "usage: push-test.sh setup | all | s14" >&2
    exit 64
    ;;
esac
