# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Keys, releases, lock, wake and server init (CLAUDE.md §6.1-§6.3, §6.8, §6.10, §6.12)."""

from __future__ import annotations

import hashlib
import os
import urllib.error
from pathlib import Path

import pytest

from bn_backup.clock import FakeClock
from bn_backup.keys import BEGIN, END, apply_block, regenerate, render_block, store_key
from bn_backup.paths import BackupPaths, OperatorPaths
from bn_backup.releases import ReleaseError, get_package, package_name
from bn_backup.server_init import adopt_v1, create_layout, rrsync_text
from bn_backup.state import LockHeld, lock_holder, run_lock
from bn_backup.wake import magic_packet, wake_and_wait

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIsofia bn-backup-agent sofia@athena"


# --------------------------------------------------------------------------- keys


def test_authorized_keys_block_keeps_foreign_lines(tmp_path: Path) -> None:
    paths = BackupPaths(tmp_path / "My Backup" / "bn-backup")
    store_key(paths, "athena", "sofia", KEY)
    store_key(paths, "athena", "ariel", KEY.replace("sofia", "ariel"))
    auth = tmp_path / "home" / ".ssh" / "authorized_keys"
    auth.parent.mkdir(parents=True)
    auth.write_text("ssh-ed25519 AAAAmine me@laptop\n")
    rrsync = Path("/Users/ariel/.local/libexec/bn-backup/rrsync")
    regenerate(paths, auth, rrsync)
    regenerate(paths, auth, rrsync)  # idempotent
    lines = auth.read_text().splitlines()
    assert lines[0] == "ssh-ed25519 AAAAmine me@laptop"
    assert lines.count(BEGIN) == 1 and lines[-1] == END
    managed = lines[2:-1]
    assert [ln.split()[-1] for ln in managed] == ["ariel@athena", "sofia@athena"]  # sorted
    # Paths with spaces are quoted inside command="…".
    assert managed[1].startswith(
        f"restrict,command=\"{rrsync} -wo '{paths.staging_user('athena', 'sofia')}'\" ssh-ed25519"
    )
    assert oct(auth.stat().st_mode & 0o777) == "0o600"


def test_apply_block_replaces_in_place() -> None:
    existing = f"a\n{BEGIN}\nold\n{END}\nb\n"
    assert apply_block(existing, [BEGIN, "new", END]) == f"a\nb\n{BEGIN}\nnew\n{END}\n"


def test_invalid_public_key_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        store_key(BackupPaths(tmp_path), "h", "u", 'ssh-ed25519 AAAA" evil')
    assert render_block(BackupPaths(tmp_path), Path("/r")) == [BEGIN, END]


# --------------------------------------------------------------------------- releases


def test_package_names() -> None:
    assert package_name("2.0.0", "darwin", "arm64") == "bn-backup-agent-2.0.0.pkg"
    assert package_name("2.0.0", "linux", "x86_64") == "bn-backup-agent_2.0.0_amd64.deb"
    assert package_name("2.0.0", "linux", "aarch64") == "bn-backup-agent_2.0.0_arm64.deb"
    with pytest.raises(ReleaseError):
        package_name("2.0.0", "linux", "riscv64")


def _fetcher(files: dict[str, bytes]) -> tuple[list[str], object]:
    seen: list[str] = []

    def fetch(url: str) -> bytes:
        seen.append(url)
        name = url.rsplit("/", 1)[-1]
        if name not in files:
            raise urllib.error.URLError("offline")
        return files[name]

    return seen, fetch


def test_release_download_verify_and_cache(tmp_path: Path) -> None:
    deb = b"debian package bytes"
    name = "bn-backup-agent_2.0.0_amd64.deb"
    sums = f"{hashlib.sha256(deb).hexdigest()}  {name}\n".encode()
    seen, fetch = _fetcher({"SHA256SUMS": sums, name: deb})
    p = get_package("2.0.0", "linux", "x86_64", tmp_path, fetch=fetch)  # type: ignore[arg-type]
    assert p.read_bytes() == deb
    assert seen[0].endswith("/v2.0.0/SHA256SUMS")
    # Offline: the verified cached file is used.
    _, offline = _fetcher({})
    assert get_package("2.0.0", "linux", "x86_64", tmp_path, fetch=offline) == p  # type: ignore[arg-type]


def test_release_mismatch_refused(tmp_path: Path) -> None:
    name = "bn-backup-agent-2.0.0.pkg"
    _, fetch = _fetcher({"SHA256SUMS": f"{'0' * 64}  {name}\n".encode(), name: b"tampered"})
    with pytest.raises(ReleaseError, match="does not match"):
        get_package("2.0.0", "darwin", "arm64", tmp_path, fetch=fetch)  # type: ignore[arg-type]
    assert not (tmp_path / "2.0.0" / name).exists()


def test_release_override(tmp_path: Path) -> None:
    local = tmp_path / "dev.deb"
    local.write_bytes(b"x")
    assert get_package("2.0.0", "linux", "x86_64", tmp_path, override=local) == local
    with pytest.raises(ReleaseError):
        get_package("2.0.0", "linux", "x86_64", tmp_path, override=tmp_path / "missing")


# --------------------------------------------------------------------------- lock


def test_run_lock_is_exclusive_and_observable(tmp_path: Path) -> None:
    lock = tmp_path / "state" / "lock"
    assert lock_holder(lock) is None
    assert not lock.exists(), "looking at the lock never creates it"
    with run_lock(lock, "run"):
        holder = lock_holder(lock)
        assert holder is not None and holder["pid"] == os.getpid()
        with pytest.raises(LockHeld), run_lock(lock, "run", retry_seconds=0.2):
            pass
    assert lock_holder(lock) is None


# --------------------------------------------------------------------------- wake


def test_magic_packet_bytes() -> None:
    p = magic_packet("AA:BB:CC:DD:EE:01")
    assert len(p) == 6 + 16 * 6
    assert p[:6] == b"\xff" * 6
    assert p[6:12] == bytes.fromhex("aabbccddee01")
    assert p[6:] == bytes.fromhex("aabbccddee01") * 16
    with pytest.raises(ValueError):
        magic_packet("nope")


def test_wake_rechecks_every_15_seconds() -> None:
    clock = FakeClock()
    start = clock.now()
    sent: list[list[str]] = []
    checks = iter([False, False, True])
    assert wake_and_wait(["m"], lambda: next(checks), sent.append, clock, 180)
    assert sent == [["m"]]
    assert (clock.now() - start).total_seconds() == 45
    clock2 = FakeClock()
    assert not wake_and_wait(["m"], lambda: False, lambda m: None, clock2, 40)
    assert (clock2.now() - FakeClock().now()).total_seconds() == 40


# --------------------------------------------------------------------------- server init


def test_rrsync_text_sets_shebang_and_rsync() -> None:
    text = rrsync_text(Path("/opt/homebrew/opt/rsync/bin/rsync"), "/usr/bin/python3")
    assert text.startswith("#!/usr/bin/python3\n")
    assert "RSYNC = '/opt/homebrew/opt/rsync/bin/rsync'" in text
    assert "RSYNC = '/usr/bin/rsync'" not in text
    assert "-wo" in text  # really the upstream script


def test_server_init_adopts_v1_tree(tmp_path: Path) -> None:
    paths = BackupPaths(tmp_path / "bn-backup")
    (paths.root / "current" / "dir1-ahe").mkdir(parents=True)
    (paths.root / "current" / "backup.yml").write_text("v1")
    (paths.root / "previous" / "old-module").mkdir(parents=True)
    create_layout(paths, [("athena", "sofia")])
    notes = adopt_v1(paths)
    assert (paths.removed / "old-module").is_dir()
    assert not (paths.root / "previous").exists()
    assert any("previous/ to removed/" in n for n in notes)
    assert paths.staging_user("athena", "sofia").is_dir()
    assert oct(paths.root.stat().st_mode & 0o777) == "0o700"
    # Idempotent.
    create_layout(paths, [("athena", "sofia")])
    assert not any("previous" in n for n in adopt_v1(paths))
    assert (paths.current / "dir1-ahe").is_dir()


def test_operator_paths(tmp_path: Path) -> None:
    op = OperatorPaths(tmp_path)
    assert op.lock == tmp_path / ".local/state/bn-backup/lock"
    assert op.rrsync == tmp_path / ".local/libexec/bn-backup/rrsync"
    assert op.control_key.name == "bn-backup_ed25519"
