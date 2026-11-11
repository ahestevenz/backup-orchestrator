#!/bin/sh
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# Phase 0 stand-in for "bn-backup-agent ctl ssh-dispatch" (spikes S2, S8, S12).
# Installed as /usr/local/libexec/bnspike-dispatch by setup-control.sh and
# reached only through the locked control key, via sudo:
#     bnspike-dispatch ctl ssh-dispatch "<what the client asked to run>"
#
# It prints exactly what arrived (arguments, user, stdin size). For
# "ctl start USER" it also starts that user's spike job with
# launchctl kickstart, like the real "ctl start" (macOS only).

LABEL=ar.bleiben.bnspike

printf 'uid=%s\n' "$(id -u)"
printf 'argc=%s\n' "$#"
i=0
for a in "$@"; do
    i=$((i + 1))
    printf 'arg%s=[%s]\n' "$i" "$a"
done
# Like the real dispatcher, only "ctl submit" reads stdin (the job file).
case "${3:-}" in
"ctl submit"*) printf 'stdin_bytes=%s\n' "$(wc -c | tr -d ' ')" ;;
esac

case "${3:-}" in
"ctl start "*)
    user=${3#ctl start }
    case "$user" in
    *[!a-z0-9_-]* | "") echo "refused: bad user name" ; exit 1 ;;
    esac
    /bin/launchctl kickstart "system/$LABEL.$user"
    echo "kickstart exit=$?"
    ;;
esac
