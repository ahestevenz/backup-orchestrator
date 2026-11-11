# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""OpenSSH from the server to hosts (CLAUDE.md §6.4, D-48).

Two kinds of connection that must never be mixed:

* the **control** connection: the server's locked control key, non-interactive,
  for `ctl` commands only;
* the **operator** connection: the operator's own SSH login (their keys or a
  typed password), interactive, only for installing, upgrading and removing
  agents.
"""

from __future__ import annotations

import shlex
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class HostTarget:
    name: str
    address: str
    ssh_port: int
    admin_user: str

    @property
    def login(self) -> str:
        return f"{self.admin_user}@{self.address}"


def reachable(address: str, port: int, timeout: float = 10.0) -> bool:
    """A TCP connect to the SSH port; needs no login."""
    try:
        with socket.create_connection((address, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolves(address: str) -> bool:
    try:
        socket.getaddrinfo(address, None)
        return True
    except OSError:
        return False


@dataclass
class CallResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class ControlTransport(Protocol):
    def call(
        self, target: HostTarget, argv: list[str], stdin: bytes | None, timeout: float
    ) -> CallResult: ...


class SshControl:
    """The control connection: `ssh -i <control key> … <admin>@<host> '<ctl …>'`."""

    def __init__(self, control_key: Path, home: Path) -> None:
        self.control_key = control_key
        self.control_path = str(home / ".ssh" / "cm-bn-%C")

    def argv(self, target: HostTarget, command: list[str]) -> list[str]:
        return [
            "ssh",
            "-i",
            str(self.control_key),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ControlMaster=auto",
            "-o",
            f"ControlPath={self.control_path}",
            "-o",
            "ControlPersist=60",
            "-p",
            str(target.ssh_port),
            target.login,
            shlex.join(command),
        ]

    def call(
        self, target: HostTarget, argv: list[str], stdin: bytes | None, timeout: float
    ) -> CallResult:
        try:
            p = subprocess.run(
                self.argv(target, argv),
                input=stdin if stdin is not None else b"",
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CallResult(255, b"", f"timed out after {timeout:.0f} s".encode())
        return CallResult(p.returncode, p.stdout, p.stderr)


class OperatorConnection(Protocol):
    """The operator's own login, used to install, upgrade and remove agents."""

    def run(self, target: HostTarget, command: str, *, first_contact: bool = False) -> int:
        """Run interactively (a terminal, so sudo can ask for the password)."""
        ...

    def capture(
        self, target: HostTarget, command: str, *, first_contact: bool = False
    ) -> tuple[int, str]:
        """Run and capture stdout (still may prompt for a password)."""
        ...

    def copy(self, target: HostTarget, local: Path, remote: str) -> int: ...


class SshOperator:
    """Plain ssh/scp with the operator's own configuration; never the control key."""

    @staticmethod
    def _opts(first_contact: bool) -> list[str]:
        return ["-o", "StrictHostKeyChecking=accept-new"] if first_contact else []

    def run(self, target: HostTarget, command: str, *, first_contact: bool = False) -> int:
        argv = ["ssh", "-t", *self._opts(first_contact), "-p", str(target.ssh_port)]
        return subprocess.run([*argv, target.login, command], check=False).returncode

    def capture(
        self, target: HostTarget, command: str, *, first_contact: bool = False
    ) -> tuple[int, str]:
        argv = ["ssh", *self._opts(first_contact), "-p", str(target.ssh_port)]
        p = subprocess.run(
            [*argv, target.login, command], stdout=subprocess.PIPE, text=True, check=False
        )
        return p.returncode, p.stdout

    def copy(self, target: HostTarget, local: Path, remote: str) -> int:
        argv = ["scp", "-P", str(target.ssh_port), str(local), f"{target.login}:{remote}"]
        return subprocess.run(argv, check=False).returncode
