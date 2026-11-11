# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Platform tests: real OS facilities, no hosts (CLAUDE.md §8).

macOS: a Case-sensitive APFS disk image attached with hdiutil (no sudo).
Linux: a loopback Btrfs image (needs sudo; enabled with BN_PLATFORM_SUDO=1,
as in CI), and an ext4 one for the clear refusal.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fakes import FakeFleet, FakeHost, make_env

from bn_backup.clone import CloneError, clone
from bn_backup.env import DiskutilInspector
from bn_backup.status import server_checks, volume_write_test

pytestmark = pytest.mark.platform

MAC = sys.platform == "darwin" and shutil.which("hdiutil") is not None
LINUX_SUDO = sys.platform.startswith("linux") and os.environ.get("BN_PLATFORM_SUDO") == "1"


@pytest.fixture(autouse=True)
def _real_clone(monkeypatch: pytest.MonkeyPatch) -> None:
    # The unit-test fakes set BN_BACKUP_TEST_CLONE=copy; these tests use the real thing.
    monkeypatch.delenv("BN_BACKUP_TEST_CLONE", raising=False)


def xattr(path: Path) -> str:
    return subprocess.run(
        ["xattr", "-l", str(path)], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def apfs(tmp_path: Path) -> Iterator[Path]:
    """A mounted Case-sensitive APFS volume, with ownership on."""
    image = tmp_path / "backup.sparseimage"
    mnt = tmp_path / "mnt"
    mnt.mkdir()
    subprocess.run(
        ["hdiutil", "create", "-size", "64m", "-fs", "Case-sensitive APFS", "-volname", "BNTest",
         "-type", "SPARSE", str(tmp_path / "backup")],
        check=True, capture_output=True,
    )  # fmt: skip
    subprocess.run(
        ["hdiutil", "attach", "-nobrowse", "-owners", "on", "-mountpoint", str(mnt), str(image)],
        check=True, capture_output=True,
    )  # fmt: skip
    try:
        yield mnt
    finally:
        subprocess.run(["hdiutil", "detach", "-force", str(mnt)], capture_output=True, check=False)


@pytest.mark.skipif(not MAC, reason="needs macOS and hdiutil")
def test_mac_clonefile_tree_keeps_xattrs_and_is_independent(apfs: Path) -> None:
    src = apfs / "current" / "photos"
    (src / "2019").mkdir(parents=True)
    f = src / "2019" / "DSC_0001.NEF"
    f.write_bytes(b"raw" * 1000)
    subprocess.run(["xattr", "-w", "rsync.%stat", "100640 0,0 501:20", str(f)], check=True)
    dst = apfs / ".staging" / "athena" / "sofia" / "photos"
    dst.parent.mkdir(parents=True)
    clone(src, dst)
    g = dst / "2019" / "DSC_0001.NEF"
    assert g.read_bytes() == f.read_bytes()
    assert "rsync.%stat: 100640 0,0 501:20" in xattr(g)
    before = (f.stat().st_mode, xattr(f))
    os.chmod(g, 0o600)
    subprocess.run(["xattr", "-w", "rsync.%stat", "100600 0,0 501:20", str(g)], check=True)
    assert (f.stat().st_mode, xattr(f)) == before, (
        "a metadata change on the clone leaves the source alone"
    )
    with pytest.raises(CloneError):
        clone(src, dst)  # the destination must not exist


@pytest.mark.skipif(not MAC, reason="needs macOS and hdiutil")
def test_mac_server_checks_against_a_real_volume(apfs: Path, tmp_path: Path) -> None:
    env = make_env(
        tmp_path / "w", FakeFleet(FakeHost("galactica"), FakeHost("athena")), platform="darwin"
    )
    os.environ.pop("BN_BACKUP_TEST_CLONE", None)  # make_env sets it; use real clones here
    env.volumes = DiskutilInspector()
    backup = apfs / "bn-backup"
    backup.mkdir()
    env.cfg.server.backup_directory = backup  # type: ignore[misc]
    rep = server_checks(env, write_test=True)
    by = {c.name: c for c in rep.checks}
    assert by["volume"].ok, by["volume"].detail
    assert by["apfs_case_sensitive"].ok, by["apfs_case_sensitive"].detail
    assert by["ownership"].ok, by["ownership"].detail
    assert by["volume_writable"].ok, by["volume_writable"].detail
    assert volume_write_test(backup / ".state") is None


@pytest.mark.skipif(not MAC, reason="needs macOS and hdiutil")
def test_mac_case_insensitive_volume_is_red(tmp_path: Path) -> None:
    mnt = tmp_path / "ci"
    mnt.mkdir()
    subprocess.run(
        ["hdiutil", "create", "-size", "32m", "-fs", "APFS", "-volname", "BNTestCI", "-type", "SPARSE", str(tmp_path / "ci")],
        check=True, capture_output=True,
    )  # fmt: skip
    subprocess.run(
        ["hdiutil", "attach", "-nobrowse", "-mountpoint", str(mnt), str(tmp_path / "ci.sparseimage")],
        check=True, capture_output=True,
    )  # fmt: skip
    try:
        env = make_env(
            tmp_path / "w", FakeFleet(FakeHost("galactica"), FakeHost("athena")), platform="darwin"
        )
        env.volumes = DiskutilInspector()
        backup = mnt / "bn-backup"
        backup.mkdir()
        env.cfg.server.backup_directory = backup  # type: ignore[misc]
        by = {c.name: c for c in server_checks(env, write_test=False).checks}
        assert by["apfs_case_sensitive"].ok is False
    finally:
        subprocess.run(["hdiutil", "detach", "-force", str(mnt)], capture_output=True, check=False)


# --------------------------------------------------------------------------- Linux


def _loop_fs(tmp_path: Path, fs: str) -> Iterator[Path]:
    image = tmp_path / f"{fs}.img"
    mnt = tmp_path / f"mnt-{fs}"
    mnt.mkdir()
    subprocess.run(["truncate", "-s", "200M", str(image)], check=True)
    mkfs = ["mkfs.btrfs", "-q"] if fs == "btrfs" else ["mkfs.ext4", "-q", "-F"]
    subprocess.run([*mkfs, str(image)], check=True)
    subprocess.run(["sudo", "mount", "-o", "loop", str(image), str(mnt)], check=True)
    subprocess.run(["sudo", "chown", f"{os.getuid()}:{os.getgid()}", str(mnt)], check=True)
    try:
        yield mnt
    finally:
        subprocess.run(["sudo", "umount", str(mnt)], check=False)


@pytest.fixture
def btrfs(tmp_path: Path) -> Iterator[Path]:
    yield from _loop_fs(tmp_path, "btrfs")


@pytest.fixture
def ext4(tmp_path: Path) -> Iterator[Path]:
    yield from _loop_fs(tmp_path, "ext4")


@pytest.mark.skipif(not LINUX_SUDO, reason="needs Linux, sudo and BN_PLATFORM_SUDO=1")
def test_linux_reflink_on_btrfs(btrfs: Path) -> None:
    src = btrfs / "current" / "photos"
    src.mkdir(parents=True)
    (src / "a.NEF").write_bytes(b"raw" * 1000)
    dst = btrfs / ".staging" / "photos"
    dst.parent.mkdir()
    clone(src, dst)
    assert (dst / "a.NEF").read_bytes() == (src / "a.NEF").read_bytes()
    assert volume_write_test(btrfs / ".state") is None


@pytest.mark.skipif(not LINUX_SUDO, reason="needs Linux, sudo and BN_PLATFORM_SUDO=1")
def test_linux_ext4_is_refused_clearly(ext4: Path) -> None:
    problem = volume_write_test(ext4 / ".state")
    assert problem is not None and "reflink" in problem


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("systemd-analyze") is None,
    reason="needs systemd-analyze",
)
def test_linux_units_verify(tmp_path: Path) -> None:
    from bn_backup.schedule import render_service, render_timer

    (tmp_path / "bn-backup-schedule.service").write_text(
        render_service("root", "/bin/true", Path("/etc/hosts"))
    )
    (tmp_path / "bn-backup-schedule.timer").write_text(render_timer("sun", 2, 0))
    agent_unit = (
        Path(__file__).parents[2] / "agent" / "packaging" / "linux" / "bn-backup-agent@.service"
    )
    shutil.copy(agent_unit, tmp_path / "bn-backup-agent@.service")
    p = subprocess.run(
        ["systemd-analyze", "verify", str(tmp_path / "bn-backup-schedule.timer"), str(tmp_path / "bn-backup-schedule.service")],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert p.returncode == 0, p.stderr
