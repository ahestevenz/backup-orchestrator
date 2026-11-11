# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""`bn-backup server init`: one-time setup of the server, no sudo (CLAUDE.md §6.1, §6.2)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Any

from .config import load_config, template
from .fsutil import atomic_write_text, ensure_dir
from .paths import BackupPaths, OperatorPaths
from .ssh import reachable

MIN_RSYNC = (3, 2, 3)


class InitError(Exception):
    pass


def find_rsync(platform: str = sys.platform) -> Path:
    """An rsync >= 3.2.3 for rrsync: Homebrew's on macOS (/usr/bin/rsync is openrsync)."""
    if platform == "darwin":
        candidates = []
        try:
            prefix = subprocess.run(
                ["brew", "--prefix", "rsync"], capture_output=True, text=True, check=False
            ).stdout.strip()
            if prefix:
                candidates.append(Path(prefix) / "bin" / "rsync")
        except OSError:
            pass
        candidates += [
            Path("/opt/homebrew/opt/rsync/bin/rsync"),
            Path("/usr/local/opt/rsync/bin/rsync"),
        ]
        hint = "brew install rsync"
    else:
        candidates = [Path("/usr/bin/rsync")]
        hint = "sudo apt install rsync"
    from .status import rsync_version

    for c in candidates:
        v = rsync_version(str(c)) if c.exists() else None
        if v is not None and v >= MIN_RSYNC:
            return c
    raise InitError(f"no rsync 3.2.3 or newer found; run: {hint}")


def rrsync_text(rsync: Path, python: str) -> str:
    """The vendored rrsync with its shebang and RSYNC path set (§6.2)."""
    text = (resources.files("bn_backup.vendor") / "rrsync").read_text(encoding="utf-8")
    lines = text.split("\n")
    lines[0] = f"#!{python}"
    text = "\n".join(lines)
    new, n = re.subn(
        r"^RSYNC = '/usr/bin/rsync'$", f"RSYNC = '{rsync}'", text, count=1, flags=re.MULTILINE
    )
    if n != 1:
        raise InitError("the vendored rrsync has no RSYNC line to set")
    return new


def install_rrsync(op: OperatorPaths, rsync: Path) -> Path:
    ensure_dir(op.rrsync.parent, 0o755)
    atomic_write_text(op.rrsync, rrsync_text(rsync, sys.executable), 0o755)
    return op.rrsync


def ensure_control_key(op: OperatorPaths) -> bool:
    """Create ~/.ssh/bn-backup_ed25519 if missing. Never touches other keys."""
    ensure_dir(op.control_key.parent, 0o700)
    if op.control_key.exists():
        return False
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "bn-backup-server",
         "-f", str(op.control_key)],
        check=True,
    )  # fmt: skip
    return True


def create_layout(paths: BackupPaths, user_hosts: list[tuple[str, str]]) -> None:
    root = paths.root
    if not root.exists():
        parent = root.parent
        if not parent.is_dir() or not os.access(parent, os.W_OK):
            raise InitError(
                f"cannot create {root}: {parent} is missing or not writable by you. "
                "Is the backup drive connected?"
            )
    ensure_dir(root, 0o700)
    os.chmod(root, 0o700)  # also when adopting an existing v1 folder
    for d in (
        paths.current,
        paths.removed,
        paths.snapshots,
        paths.staging,
        paths.state,
        paths.hosts_dir,
        paths.keys_dir,
        paths.history_dir,
        paths.logs,
    ):
        ensure_dir(d, 0o700)
    for host, user in user_hosts:
        ensure_dir(paths.staging_user(host, user), 0o700)


def adopt_v1(paths: BackupPaths) -> list[str]:
    """v1's previous/ becomes removed/; current/ is used as it is (D-23)."""
    notes = []
    previous = paths.root / "previous"
    if previous.is_dir():
        # create_layout made an empty removed/; it gives way to v1's folder.
        if paths.removed.is_dir() and not any(paths.removed.iterdir()):
            paths.removed.rmdir()
        if paths.removed.exists():
            notes.append("both previous/ and removed/ exist; previous/ was left as it is")
        else:
            previous.rename(paths.removed)
            notes.append("renamed the v1 folder previous/ to removed/")
    if paths.current.is_dir():
        modules = sorted(p.name for p in paths.current.iterdir() if p.is_dir())
        if modules:
            notes.append(
                f"adopted {len(modules)} existing folder(s) in current/: {', '.join(modules)}"
            )
    return notes


def cmd_server_init(ctx: Any) -> int:
    op: OperatorPaths = ctx.paths
    if ensure_control_key(op):
        print(f"created the control key {op.control_key}")
    try:
        rsync = find_rsync()
        install_rrsync(op, rsync)
        print(f"installed rrsync at {op.rrsync} (using {rsync})")
    except InitError as e:
        print(f"bn-backup: {e}", file=sys.stderr)
        return 1

    cfg_path: Path = ctx.config_path
    if not cfg_path.exists():
        ensure_dir(cfg_path.parent, 0o700)
        atomic_write_text(cfg_path, template(ctx.operator), 0o600)
        print(f"wrote a config template to {cfg_path}")
        print("edit it, then run `bn-backup server init` again")
        return 0

    loaded = load_config(cfg_path, home=op.home)
    cfg = loaded.config
    paths = BackupPaths(cfg.server.backup_directory)
    try:
        create_layout(paths, cfg.user_hosts())
    except InitError as e:
        print(f"bn-backup: {e}", file=sys.stderr)
        return 1
    for note in adopt_v1(paths):
        print(note)

    if not reachable("localhost", cfg.server.ssh_port, 5.0):
        if sys.platform == "darwin":
            print(
                "The SSH server does not answer. Turn on System Settings → General → Sharing → "
                "Remote Login."
            )
        else:
            print("The SSH server does not answer. Install it: sudo apt install openssh-server")
    if sys.platform == "darwin":
        print(
            "Reminder: in Remote Login's ⓘ, turn on 'Allow full disk access for remote users' "
            "(agents' pushes write to the backup drive). The status board checks it."
        )

    from .env import Env
    from .status import render_server, server_checks

    env = Env(loaded=loaded, operator_paths=op, operator=ctx.operator)
    rep = server_checks(env, write_test=True)
    print()
    print(render_server(rep))
    return 0 if rep.ok else 2
