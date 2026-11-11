# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Everything a command needs from the outside world, in one place.

Commands receive an `Env`; tests build one with fakes (agents, SSH, clock,
network, disk) and the real file system under a temporary folder.
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from . import __version__
from .agentctl import Agent, AgentClient
from .clock import Clock, SystemClock
from .config import Config, LoadedConfig
from .paths import BackupPaths, OperatorPaths
from .ssh import HostTarget, OperatorConnection, SshControl, SshOperator, reachable, resolves
from .state import load_host


class VolumeInspector(Protocol):
    def info(self, path: Path) -> dict[str, Any] | None:
        """`diskutil info -plist` of the volume holding `path` (macOS), or None."""
        ...


class DiskutilInspector:
    def info(self, path: Path) -> dict[str, Any] | None:
        if sys.platform != "darwin":
            return None
        try:
            out = subprocess.run(
                ["/usr/sbin/diskutil", "info", "-plist", str(path)],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if out.returncode != 0:
            return None
        data = plistlib.loads(out.stdout)
        return data if isinstance(data, dict) else None


def _send_magic_packets(macs: list[str]) -> None:
    from .wake import send_magic_packets

    send_magic_packets(macs)


@dataclass
class Env:
    loaded: LoadedConfig
    operator_paths: OperatorPaths
    operator: str
    clock: Clock = field(default_factory=SystemClock)
    agent_factory: Callable[[HostTarget], Agent] | None = None
    operator_conn: OperatorConnection = field(default_factory=SshOperator)
    reachable: Callable[[str, int, float], bool] = reachable
    resolves: Callable[[str], bool] = resolves
    send_wake: Callable[[list[str]], None] = _send_magic_packets
    volumes: VolumeInspector = field(default_factory=DiskutilInspector)
    platform: str = sys.platform
    version: str = __version__
    server_host_key: Path = Path("/etc/ssh/ssh_host_ed25519_key.pub")
    poll_seconds: float = 10.0
    probe_poll_seconds: float = 2.0

    @property
    def cfg(self) -> Config:
        return self.loaded.config

    @property
    def paths(self) -> BackupPaths:
        return BackupPaths(self.cfg.server.backup_directory)

    def target(self, host: str) -> HostTarget:
        """Connection details from the config, or from the host record (removed hosts)."""
        h = self.cfg.hosts.get(host)
        if h is not None:
            return HostTarget(host, h.address, h.ssh_port, h.admin_user)
        rec = load_host(self.paths, host)
        if rec is None:
            raise KeyError(host)
        return HostTarget(host, rec.address, rec.ssh_port, rec.admin_user)

    def agent(self, host: str | HostTarget) -> Agent:
        target = self.target(host) if isinstance(host, str) else host
        if self.agent_factory is not None:
            return self.agent_factory(target)
        control = SshControl(self.operator_paths.control_key, self.operator_paths.home)
        return AgentClient(control, target)
