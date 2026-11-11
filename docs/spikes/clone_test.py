#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Phase 0 spike S6: clone a whole folder tree on the backup drive.

Usage: python3 clone_test.py SRC_DIR DST_DIR

SRC_DIR must hold files pushed with rsync --fake-super (spike S3); DST_DIR
must not exist yet and must be on the same APFS volume. Checks that
clonefile() copies the tree in one call, keeps the extended attributes
(including rsync's fake-super attribute), and that changing metadata on the
clone leaves the source untouched.
"""

import ctypes
import os
import subprocess
import sys

CLONE_NOFOLLOW = 0x0001


def clonefile(src: str, dst: str) -> None:
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    libc.clonefile.restype = ctypes.c_int
    if libc.clonefile(os.fsencode(src), os.fsencode(dst), CLONE_NOFOLLOW) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), dst)


def tree(root: str) -> list[str]:
    paths = []
    for base, dirs, files in os.walk(root):
        for name in dirs + files:
            paths.append(os.path.relpath(os.path.join(base, name), root))
    return sorted(paths)


def xattrs(path: str) -> str:
    out = subprocess.run(["xattr", "-l", path], capture_output=True, text=True, check=True)
    return out.stdout


def first_file(root: str) -> str:
    for base, _dirs, files in sorted(os.walk(root)):
        for name in sorted(files):
            return os.path.relpath(os.path.join(base, name), root)
    sys.exit(f"no files under {root}; run spike S3 first")


def report(label: str, ok: bool) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    return ok


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 64
    src, dst = sys.argv[1], sys.argv[2]
    rel = first_file(src)
    a, b = os.path.join(src, rel), os.path.join(dst, rel)

    clonefile(src, dst)
    print(f"clonefile({src!r}, {dst!r}): ok")
    print(f"\nxattrs of the source file {a}:\n{xattrs(a)}")

    results = [
        report("the clone has the same files and folders", tree(src) == tree(dst)),
        report("the clone keeps the extended attributes", xattrs(a) == xattrs(b)),
        report("rsync's fake-super attribute is present", "rsync.%stat" in xattrs(a)),
    ]

    before = (os.stat(a).st_mode, xattrs(a))
    os.chmod(b, 0o600)
    subprocess.run(["xattr", "-w", "com.bleiben.spike", "changed-on-clone", b], check=True)
    after = (os.stat(a).st_mode, xattrs(a))
    results.append(report("changing metadata on the clone leaves the source unchanged", before == after))

    print("\nS6:", "PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
