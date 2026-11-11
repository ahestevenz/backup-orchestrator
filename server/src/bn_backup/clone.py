# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Cheap copies: APFS clones on macOS, reflinks on Linux (CLAUDE.md §6.11, D-20).

Never falls back to hard links: rsync changes metadata in place, which would
reach the file in current/ through a hard link.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

CLONE_NOFOLLOW = 0x0001


class CloneError(OSError):
    pass


def _mode() -> str:
    # Tests only (containers have no reflink filesystem); read nowhere else.
    return os.environ.get("BN_BACKUP_TEST_CLONE", "")


def clone(src: Path, dst: Path) -> None:
    """Clone a file or a whole folder tree. `dst` must not exist."""
    if _mode() == "copy":
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
        return
    if sys.platform == "darwin":
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
        libc.clonefile.restype = ctypes.c_int
        if libc.clonefile(os.fsencode(src), os.fsencode(dst), CLONE_NOFOLLOW) != 0:
            err = ctypes.get_errno()
            raise CloneError(err, f"cannot clone {src} to {dst}: {os.strerror(err)}")
        return
    p = subprocess.run(
        ["cp", "-a", "--reflink=always", str(src), str(dst)],
        capture_output=True,
        text=True,
        check=False,
    )
    if p.returncode != 0:
        raise CloneError(
            0,
            "filesystem without reflink support is not supported "
            f"(cp --reflink=always: {p.stderr.strip()})",
        )
