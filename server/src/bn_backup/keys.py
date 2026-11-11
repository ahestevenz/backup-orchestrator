# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""The managed block of the operator's authorized_keys on the server (CLAUDE.md §6.3).

Each agent push key may only run `rrsync -wo` into its own
`.staging/<host>/<user>/` (D-21).
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from .fsutil import atomic_write_text, ensure_dir
from .paths import BackupPaths

BEGIN = "# BEGIN bn-backup managed — do not edit"
END = "# END bn-backup managed"
_PUBKEY_RE = re.compile(
    r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+) [A-Za-z0-9+/=]+( [^\n\"\\]*)?$"
)


class KeyError_(ValueError):
    pass


def check_public_key(key: str) -> str:
    key = key.strip()
    if not _PUBKEY_RE.match(key):
        raise KeyError_(f"not a valid public key: {key[:40]!r}")
    return key


def store_key(paths: BackupPaths, host: str, user: str, public_key: str) -> None:
    atomic_write_text(paths.key_file(host, user), check_public_key(public_key) + "\n", 0o644)


def forget_keys(paths: BackupPaths, host: str) -> None:
    d = paths.keys_dir / host
    if d.is_dir():
        for f in d.glob("*.pub"):
            f.unlink()
        d.rmdir()


def stored_keys(paths: BackupPaths) -> list[tuple[str, str, str]]:
    """(host, user, public key), sorted by host and user."""
    out = []
    if paths.keys_dir.is_dir():
        for f in sorted(paths.keys_dir.glob("*/*.pub")):
            out.append((f.parent.name, f.stem, f.read_text(encoding="utf-8").strip()))
    return sorted(out)


def render_block(paths: BackupPaths, rrsync: Path) -> list[str]:
    lines = [BEGIN]
    for host, user, key in stored_keys(paths):
        target = shlex.quote(str(paths.staging_user(host, user)))
        command = f"{shlex.quote(str(rrsync))} -wo {target}"
        lines.append(f'restrict,command="{command}" {key}')
    lines.append(END)
    return lines


def apply_block(existing: str, block: list[str]) -> str:
    """Replace the managed block (or append it), keeping every other line."""
    out: list[str] = []
    inside = False
    for line in existing.splitlines():
        if line.strip() == BEGIN:
            inside = True
            continue
        if line.strip() == END:
            inside = False
            continue
        if not inside:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join([*out, *block]) + "\n"


def regenerate(paths: BackupPaths, authorized_keys: Path, rrsync: Path) -> None:
    ensure_dir(authorized_keys.parent, 0o700)
    existing = authorized_keys.read_text(encoding="utf-8") if authorized_keys.exists() else ""
    atomic_write_text(authorized_keys, apply_block(existing, render_block(paths, rrsync)), 0o600)
