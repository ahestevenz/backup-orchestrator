# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Fakes for the outside world: agents on hosts, the operator's SSH, disks.

`FakeAgent` has the same methods as `agentctl.AgentClient`. A `FakeHost`
"runs" jobs at once when they are started; tests shape the results.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from conftest import config_data, write_config

from bn_backup.agentctl import AgentInfo, CtlError, TransportError
from bn_backup.clock import FakeClock
from bn_backup.config import load_config
from bn_backup.env import Env
from bn_backup.paths import OperatorPaths
from bn_backup.ssh import HostTarget

AGENT_VERSION = "2.0.0"


@dataclass
class FakeHost:
    name: str
    os: str = "linux"
    arch: str = "x86_64"
    accounts: set[str] = field(default_factory=lambda: {"ariel", "sofia"})
    resolves: bool = True
    up: bool = True
    wakes: bool = False  # becomes reachable after a magic packet
    installed: bool = True
    configured: bool = True
    agent_version: str = AGENT_VERSION
    protocol: tuple[int, int] = (1, 1)
    users: set[str] = field(default_factory=lambda: {"ariel", "sofia"})
    running: set[str] = field(default_factory=set)
    stuck: set[str] = field(default_factory=set)  # jobs that ignore ctl stop
    fda: str = "not_applicable"
    server_reachable: bool = True
    server_error_kind: str | None = None
    macs: list[str] = field(default_factory=lambda: ["aa:bb:cc:dd:ee:01"])
    # module name -> (error_kind, message): backup failures, and probe failures
    module_errors: dict[str, tuple[str, str]] = field(default_factory=dict)
    probe_errors: dict[str, tuple[str, str]] = field(default_factory=dict)
    # called with (user, job) when a backup job starts; may write into staging
    on_backup: Callable[[str, dict[str, Any]], dict[str, Any] | None] | None = None
    # Backup jobs only (probes always answer at once):
    # when set, start() leaves the job "running" with no result (a crash)
    hang: bool = False
    hang_probes: bool = False  # probes that never report
    # a job that reports "running" for this many result polls before it is done
    slow_polls: int = 0
    # called on every result poll (tests use it to pull drives or send signals)
    on_poll: Callable[[], None] | None = None
    jobs: list[dict[str, Any]] = field(default_factory=list)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)


class FakeAgent:
    def __init__(self, host: FakeHost) -> None:
        self.h = host

    def _need(self) -> None:
        if not self.h.up:
            raise TransportError("ssh: connect to host: Operation timed out")
        if not self.h.installed or not self.h.configured:
            raise TransportError("Permission denied (publickey)")

    def ping(self) -> None:
        self.h.calls.append("ping")
        self._need()

    def info(self) -> AgentInfo:
        self.h.calls.append("info")
        self._need()
        return AgentInfo(
            agent_version=self.h.agent_version,
            protocol_min=self.h.protocol[0],
            protocol_max=self.h.protocol[1],
            os=self.h.os,
            arch=self.h.arch,
            hostname=self.h.name,
            mac_addresses=[{"iface": "en0", "mac": m, "wired": True} for m in self.h.macs],  # type: ignore[misc]
            rsync_version="3.4.1",
            configured=self.h.configured,
            users=sorted(self.h.users),
            running=sorted(self.h.running),
        )

    def user_add(self, user: str) -> str:
        self.h.calls.append(f"user-add {user}")
        self._need()
        if user not in self.h.accounts:
            raise CtlError("no_such_user", user)
        self.h.users.add(user)
        return f"ssh-ed25519 AAAAC3Nz{self.h.name}{user} bn-backup-agent {user}@{self.h.name}"

    def user_remove(self, user: str) -> None:
        self._need()
        self.h.users.discard(user)

    def submit(self, user: str, job: dict[str, Any]) -> str:
        self.h.calls.append(f"submit {user} {job['kind']}")
        self._need()
        if user in self.h.running:
            raise CtlError("busy", "a job is still running")
        self.h.jobs.append(job)
        self.h.results.pop(user, None)
        return str(job["job_id"])

    def start(self, user: str) -> None:
        self.h.calls.append(f"start {user}")
        self._need()
        job = self.h.jobs[-1]
        self._kind = job["kind"]
        if job["kind"] == "probe":
            if self.h.hang_probes:
                self.h.results[user] = {"job_id": job["job_id"], "state": "running"}
            else:
                self.h.results[user] = self._run(user, job)
            return
        if self.h.hang:
            self.h.results[user] = {"job_id": job["job_id"], "state": "running"}
            return
        if self.h.slow_polls:
            self.h.running.add(user)
            self._polls_left = self.h.slow_polls
            self._pending = (user, job)
            self.h.results[user] = {"job_id": job["job_id"], "state": "running"}
            return
        self.h.results[user] = self._run(user, job)

    def _module(self, name: str, probe: bool) -> dict[str, Any]:
        err = (self.h.probe_errors if probe else self.h.module_errors).get(name)
        return {
            "name": name,
            "status": "failed" if err else "ok",
            "rsync_exit": None,
            "error_kind": err[0] if err else None,
            "message": err[1] if err else "",
            "files_transferred": 0 if err else 1,
            "bytes_transferred": 0 if err else 10,
            "suspect_count": 0,
            "suspect_files": [],
        }

    def _run(self, user: str, job: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "protocol": 1,
            "job_id": job["job_id"],
            "run_id": job["run_id"],
            "kind": job["kind"],
            "user": user,
            "agent_version": self.h.agent_version,
            "state": "done",
            "started_at": "2026-11-10T10:30:00Z",
            "finished_at": "2026-11-10T10:31:00Z",
            "fda": self.h.fda,
            "server_reachable": None,
            "server_error": None,
            "server_error_kind": None,
            "notes": [],
            "modules": [self._module(m["name"], job["kind"] == "probe") for m in job["modules"]],
        }
        if job["kind"] == "probe":
            result["server_reachable"] = self.h.server_reachable
            if not self.h.server_reachable:
                result["server_error"] = "rsync: [Receiver] mkstemp failed: Operation not permitted"
                result["server_error_kind"] = self.h.server_error_kind or "server_denied"
        elif self.h.on_backup is not None:
            changed = self.h.on_backup(user, job)
            if changed is not None:
                result.update(changed)
        return result

    def stop(self, user: str) -> None:
        self.h.calls.append(f"stop {user}")
        self._need()
        if user not in self.h.stuck:
            self.h.running.discard(user)
            self._pending = None

    def result(self, user: str) -> dict[str, Any] | None:
        self._need()
        if self.h.on_poll is not None and getattr(self, "_kind", None) == "backup":
            self.h.on_poll()
        pending = getattr(self, "_pending", None)
        if pending is not None and pending[0] == user and user in self.h.running:
            self._polls_left -= 1
            if self._polls_left <= 0:
                self.h.running.discard(user)
                self.h.results[user] = self._run(*pending)
                self._pending = None
        return self.h.results.get(user)

    def log(self, user: str, module: str) -> list[str]:
        self._need()
        return [f"log of {module}"]

    def open_fda_settings(self) -> dict[str, Any]:
        self.h.calls.append("open-fda-settings")
        return {"opened": True, "console_user": "sofia"}


class FakeFleet:
    def __init__(self, *hosts: FakeHost) -> None:
        self.hosts = {h.name: h for h in hosts}
        self.woken: list[str] = []

    def agent(self, target: HostTarget) -> FakeAgent:
        if not hasattr(self, "_agents"):
            self._agents: dict[str, FakeAgent] = {}
        return self._agents.setdefault(target.name, FakeAgent(self.hosts[target.name]))

    def by_address(self, address: str) -> FakeHost:
        return next(h for h in self.hosts.values() if address.startswith(h.name))

    def reachable(self, address: str, port: int, timeout: float) -> bool:
        return self.by_address(address).up

    def resolves(self, address: str) -> bool:
        return self.by_address(address).resolves

    def send_wake(self, macs: list[str]) -> None:
        self.woken += macs
        for h in self.hosts.values():
            if h.wakes and any(m in macs for m in h.macs):
                h.up = True


class FakeOperator:
    """The operator's own SSH login; records commands and plays the host's part."""

    def __init__(self, fleet: FakeFleet) -> None:
        self.fleet = fleet
        self.commands: list[tuple[str, str]] = []
        self.copies: list[tuple[str, str]] = []
        self.fail_on: str | None = None

    def _host(self, target: HostTarget) -> FakeHost:
        return self.fleet.hosts[target.name]

    def run(self, target: HostTarget, command: str, *, first_contact: bool = False) -> int:
        self.commands.append((target.name, command))
        if self.fail_on and self.fail_on in command:
            return 1
        h = self._host(target)
        if "apt-get install" in command or "installer -pkg" in command:
            h.installed = True
            h.agent_version = AGENT_VERSION
        elif " ctl setup " in command:
            h.configured = True
        elif " ctl uninstall" in command:
            h.installed = h.configured = False
            h.users.clear()
        return 0

    def capture(
        self, target: HostTarget, command: str, *, first_contact: bool = False
    ) -> tuple[int, str]:
        self.commands.append((target.name, command))
        h = self._host(target)
        if command.startswith("uname"):
            return 0, ("Darwin" if h.os == "darwin" else "Linux") + f"\n{h.arch}\n"
        if command.startswith("id -u "):
            user = command.split()[-1].strip("'")
            return (0, "501\n") if user in h.accounts else (1, "")
        return 0, ""

    def copy(self, target: HostTarget, local: Path, remote: str) -> int:
        self.copies.append((target.name, remote))
        return 0


class FakeVolumes:
    def __init__(self, info: dict[str, Any] | None = None) -> None:
        self.data = info or {
            "FilesystemType": "apfs",
            "FilesystemUserVisibleName": "APFS (Case-sensitive)",
            "GlobalPermissionsEnabled": True,
        }

    def info(self, path: Path) -> dict[str, Any] | None:
        return self.data


def fake_rsync(path: Path, version: str = "3.4.1") -> Path:
    path.write_text(f'#!/bin/sh\necho "rsync  version {version}  protocol version 32"\n')
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def make_env(
    tmp_path: Path,
    fleet: FakeFleet,
    data: dict[str, Any] | None = None,
    platform: str = "linux",
) -> Env:
    """An Env with the real file system under tmp_path and fakes for the rest."""
    home = tmp_path / "home"
    backup = tmp_path / "Backup" / "bn-backup"
    backup.mkdir(parents=True, exist_ok=True)
    data = data or config_data(server={"backup_directory": str(backup)})
    data["server"]["backup_directory"] = str(backup)
    cfg_path = write_config(home / ".config" / "bn-backup" / "config.yml", data)
    op = OperatorPaths(home)
    op.control_key_pub.parent.mkdir(parents=True, exist_ok=True)
    op.control_key_pub.write_text("ssh-ed25519 AAAAC3NzaCserver bn-backup-server\n")
    op.rrsync.parent.mkdir(parents=True, exist_ok=True)
    rsync = fake_rsync(tmp_path / "rsync")
    op.rrsync.write_text(f"#!/usr/bin/env python3\nRSYNC = '{rsync}'\n")
    op.rrsync.chmod(0o755)
    host_key = tmp_path / "ssh_host_ed25519_key.pub"
    host_key.write_text("ssh-ed25519 AAAAhostkey root@macmini\n")
    os.environ["BN_BACKUP_TEST_CLONE"] = "copy"
    return Env(
        loaded=load_config(cfg_path, home=home),
        operator_paths=op,
        operator="ariel",
        clock=FakeClock(),
        agent_factory=fleet.agent,
        operator_conn=FakeOperator(fleet),
        reachable=fleet.reachable,
        resolves=fleet.resolves,
        send_wake=fleet.send_wake,
        volumes=FakeVolumes(),
        platform=platform,
        server_host_key=host_key,
        poll_seconds=1,
        probe_poll_seconds=1,
    )


def standard_fleet(**overrides: Any) -> FakeFleet:
    """galactica (ariel) and athena (sofia), as in conftest.BASE_CONFIG."""
    return FakeFleet(
        FakeHost("galactica", **overrides),
        FakeHost("athena", **overrides),
    )


class FakeNotifier:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    def send(self, subject: str, body: str) -> list[str]:
        self.sent.append((subject, body))
        return ["email: SMTP refused"] if self.fail else []


def pushing(paths: Any, content: str = "v1") -> Callable[[str, dict[str, Any]], None]:
    """An on_backup hook that writes into staging the way rsync would."""

    def push(user: str, job: dict[str, Any]) -> None:
        if job["options"]["dry_run"] or not paths.root.exists():
            return  # a push to a missing drive writes nothing
        for m in job["modules"]:
            base = paths.staging_module(job["host_name"], user, m["name"])
            if m["type"] == "path":
                folder = base / m["src_path"].rstrip("/").rsplit("/", 1)[-1]
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "photo.NEF").write_text(f"{content} {job['run_id']}")
            else:
                (base / user).mkdir(parents=True, exist_ok=True)
                (base / "hosts").write_text("127.0.0.1 localhost")
                (base / user / ".zshrc").write_text("export X=1")

    return push
