#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Phase 0 spikes S10 and S11: can a Python process use the backup drive?

Usage: python3 volume_test.py VOLUME [WAIT_SECONDS]
       (for example: python3 volume_test.py /Volumes/Backup 180)

Logs who is running it, whether anyone is logged in at the screen, whether
VOLUME is mounted (waiting up to WAIT_SECONDS for it, since a job started at
boot can run before external drives are mounted), and whether it can create,
clone and delete a file there.
Every line also goes to /Users/Shared/bnspike/volume_test.log, so the result
of a run started by launchd after a reboot can be read later.
"""

import ctypes
import datetime
import getpass
import os
import subprocess
import sys
import time

LOG = os.environ.get("BNSPIKE_LOG", "/Users/Shared/bnspike/volume_test.log")
CLONE_NOFOLLOW = 0x0001


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 64
    vol = sys.argv[1]
    wait = int(sys.argv[2]) if len(sys.argv) == 3 else 0
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log = open(LOG, "a", encoding="utf-8")

    def say(msg: str) -> None:
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    console = subprocess.run(
        ["stat", "-f", "%Su", "/dev/console"], capture_output=True, text=True
    ).stdout.strip()
    say(f"--- {now} user={getpass.getuser()} python={sys.executable} pid={os.getpid()}")
    say(f"logged in at the screen: {console} (root means nobody)")
    deadline = time.monotonic() + wait
    mounted = os.path.ismount(vol)
    while not mounted and time.monotonic() < deadline:
        time.sleep(5)
        mounted = os.path.ismount(vol)
    waited = wait - max(0, round(deadline - time.monotonic())) if wait else 0
    say(f"{vol} mounted: {mounted} (waited up to {waited} s)")
    if not mounted:
        say("RESULT: volume not mounted")
        return 1

    work = os.path.join(vol, "bnspike-s10")
    f1, f2 = os.path.join(work, "test.txt"), os.path.join(work, "test-clone.txt")
    ok = True

    def attempt(label: str, action) -> None:
        nonlocal ok
        try:
            action()
            say(f"{label}: ok")
        except OSError as e:
            ok = False
            say(f"{label}: FAILED [{e.errno}] {e.strerror}")

    def create() -> None:
        os.makedirs(work, exist_ok=True)
        with open(f1, "w", encoding="utf-8") as fh:
            fh.write(now)

    def clone() -> None:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
        if os.path.exists(f2):
            os.remove(f2)
        if libc.clonefile(os.fsencode(f1), os.fsencode(f2), CLONE_NOFOLLOW) != 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))

    def delete() -> None:
        os.remove(f1)
        os.remove(f2)
        os.rmdir(work)

    attempt("create", create)
    if ok:
        attempt("clone", clone)
    if ok:
        attempt("delete", delete)
    say(f"RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
