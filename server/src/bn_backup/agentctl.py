# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Typed wrappers for every `ctl` command, over the control connection (§5.2, §6.4).

Tests replace `AgentClient` with a fake that has the same methods.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from . import SERVER_PROTOCOL
from .ssh import ControlTransport, HostTarget
from .state import MacAddress

DEFAULT_TIMEOUT = 60.0
USER_ADD_TIMEOUT = 120.0


class CtlError(Exception):
    """The agent answered with {"error": code, "message": text}."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class TransportError(Exception):
    """The control connection failed: refused login, host gone, no agent, bad output."""


class AgentInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_version: str
    protocol_min: int
    protocol_max: int
    os: str
    arch: str
    hostname: str = ""
    mac_addresses: list[MacAddress] = Field(default_factory=list)
    rsync_path: str = ""
    rsync_version: str | None = None
    configured: bool = False
    users: list[str] = Field(default_factory=list)
    running: list[str] = Field(default_factory=list)

    @property
    def protocol_ok(self) -> bool:
        return self.protocol_min <= SERVER_PROTOCOL <= self.protocol_max


class Agent(Protocol):
    """What the server can ask an agent to do."""

    def ping(self) -> None: ...
    def info(self) -> AgentInfo: ...
    def user_add(self, user: str) -> str: ...
    def user_remove(self, user: str) -> None: ...
    def submit(self, user: str, job: dict[str, Any]) -> str: ...
    def start(self, user: str) -> None: ...
    def stop(self, user: str) -> None: ...
    def result(self, user: str) -> dict[str, Any] | None: ...
    def log(self, user: str, module: str) -> list[str]: ...
    def open_fda_settings(self) -> dict[str, Any]: ...


class AgentClient:
    def __init__(self, transport: ControlTransport, target: HostTarget) -> None:
        self.transport = transport
        self.target = target

    def _call(
        self, *args: str, stdin: bytes | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> dict[str, Any]:
        r = self.transport.call(self.target, ["ctl", *args], stdin, timeout)
        text = r.stdout.decode("utf-8", errors="replace").strip()
        try:
            data = json.loads(text) if text else None
        except ValueError:
            data = None
        if isinstance(data, dict) and "error" in data:
            raise CtlError(str(data["error"]), str(data.get("message", "")))
        if not isinstance(data, dict):
            err = r.stderr.decode("utf-8", errors="replace").strip().splitlines()
            reason = err[-1] if err else f"no answer (exit {r.returncode})"
            raise TransportError(reason)
        return data

    def ping(self) -> None:
        self._call("ping")

    def info(self) -> AgentInfo:
        return AgentInfo.model_validate(self._call("info"))

    def user_add(self, user: str) -> str:
        return str(self._call("user-add", user, timeout=USER_ADD_TIMEOUT)["public_key"])

    def user_remove(self, user: str) -> None:
        self._call("user-remove", user)

    def submit(self, user: str, job: dict[str, Any]) -> str:
        return str(self._call("submit", user, stdin=json.dumps(job).encode())["job_id"])

    def start(self, user: str) -> None:
        self._call("start", user)

    def stop(self, user: str) -> None:
        self._call("stop", user)

    def result(self, user: str) -> dict[str, Any] | None:
        data = self._call("result", user)
        return None if data.get("state") == "absent" else data

    def log(self, user: str, module: str) -> list[str]:
        return [str(x) for x in self._call("log", user, module).get("lines", [])]

    def open_fda_settings(self) -> dict[str, Any]:
        return self._call("open-fda-settings")
