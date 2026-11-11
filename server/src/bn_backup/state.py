# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""What the server remembers: run.json, host records, history and the run lock.

CLAUDE.md §6.7 (run.json), §6.6 (host records), §6.8 (lock, D-56).
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .fsutil import atomic_write_json, read_json
from .paths import BackupPaths

RunStatus = Literal["RUNNING", "UNFINISHED", "COMPLETE", "EXPIRED", "ABORTED"]
ModuleStatus = Literal["pending", "green", "red"]


class _State(BaseModel):
    # State files may gain fields in later versions; never fail on them.
    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------------- hosts


class MacAddress(_State):
    iface: str
    mac: str
    wired: bool = True


class HostRecord(_State):
    """`.state/hosts/<host>.json`: what the server learned about a host."""

    host: str
    address: str
    ssh_port: int = 22
    admin_user: str
    os: str | None = None
    arch: str | None = None
    agent_version: str | None = None
    rsync_version: str | None = None
    mac_addresses: list[MacAddress] = Field(default_factory=list)
    installed_version: str | None = None
    setup_done: bool = False
    bootstrapped: bool = False


def load_host(paths: BackupPaths, host: str) -> HostRecord | None:
    p = paths.host_record(host)
    if not p.is_file():
        return None
    return HostRecord.model_validate(read_json(p))


def save_host(paths: BackupPaths, record: HostRecord) -> None:
    atomic_write_json(paths.host_record(record.host), record.model_dump(mode="json"))


def known_hosts(paths: BackupPaths) -> list[str]:
    if not paths.hosts_dir.is_dir():
        return []
    return sorted(p.stem for p in paths.hosts_dir.glob("*.json"))


# --------------------------------------------------------------------------- runs


class AbortInfo(_State):
    cause: Literal["backup_volume_lost", "source_drive_missing"]
    host: str | None = None
    user: str | None = None
    module: str | None = None
    drive: str | None = None
    at: str


class ModuleState(_State):
    host: str
    user: str
    type: Literal["path", "host-config"]
    src_path: str | None = None
    excludes: list[str] = Field(default_factory=list)
    status: ModuleStatus = "pending"
    error_kind: str | None = None
    reason: str | None = None
    attempt: int = 0
    finished_at: str | None = None
    files_transferred: int = 0
    bytes_transferred: int = 0
    suspect_count: int = 0
    suspect_files: list[str] = Field(default_factory=list)


class RunState(_State):
    run_id: str
    status: RunStatus
    mode: Literal["mirror", "snapshot"] = "mirror"
    first_attempt_at: str
    last_attempt_at: str
    last_attempt_finished_at: str | None = None
    completed_at: str | None = None
    attempts: int = 1
    config_sha256: str = ""
    previous_expired: bool = False
    reason: str | None = None
    abort: AbortInfo | None = None
    modules: dict[str, ModuleState] = Field(default_factory=dict)

    def counts(self) -> tuple[int, int]:
        """(green, total)."""
        green = sum(1 for m in self.modules.values() if m.status == "green")
        return green, len(self.modules)

    def red(self) -> dict[str, ModuleState]:
        return {n: m for n, m in self.modules.items() if m.status == "red"}


def load_run(paths: BackupPaths) -> RunState | None:
    if not paths.run_json.is_file():
        return None
    return RunState.model_validate(read_json(paths.run_json))


def save_run(paths: BackupPaths, run: RunState) -> None:
    atomic_write_json(paths.run_json, run.model_dump(mode="json"))


def write_history(paths: BackupPaths, run: RunState) -> None:
    atomic_write_json(paths.history_file(run.run_id), run.model_dump(mode="json"))


def load_history(paths: BackupPaths) -> list[RunState]:
    out = []
    if paths.history_dir.is_dir():
        for p in paths.history_dir.glob("*.json"):
            try:
                out.append(RunState.model_validate(read_json(p)))
            except (ValueError, OSError):
                continue
    return out


class LastComplete(_State):
    run_id: str
    completed_at: str


def load_last_complete(paths: BackupPaths) -> LastComplete | None:
    if not paths.last_complete.is_file():
        return None
    return LastComplete.model_validate(read_json(paths.last_complete))


# --------------------------------------------------------------------------- lock


class LockHeld(Exception):
    """Another run holds the lock."""

    def __init__(self, info: dict[str, Any] | None) -> None:
        self.info = info or {}
        super().__init__("another run is in progress")


def read_lock_info(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def lock_holder(path: Path) -> dict[str, Any] | None:
    """Who holds the run lock, without creating or taking it (§6.8).

    Returns the lock's contents when a live process holds it, else None.
    """
    if not path.is_file():
        return None
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return read_lock_info(path) or {}
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


@contextmanager
def run_lock(path: Path, command: str, retry_seconds: float = 2.0) -> Iterator[None]:
    """Hold the run lock for the duration of the block (D-30, D-56)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + retry_seconds
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                info = read_lock_info(path)
                os.close(fd)
                raise LockHeld(info) from None
            time.sleep(0.1)
    try:
        info = {
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "command": command,
        }
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, json.dumps(info).encode())
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
