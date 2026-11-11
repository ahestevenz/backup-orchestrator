# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Building agent jobs and waiting for their results (CLAUDE.md §5.4, §6.5, §6.7)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from . import SERVER_PROTOCOL
from .agentctl import Agent, CtlError, TransportError
from .clock import Clock
from .config import Config, ModuleSpec
from .paths import BackupPaths

# A job that has not started reporting is given this long before the
# "stopped without a result" check applies (CLAUDE.md §6.7 step 7).
START_GRACE_SECONDS = 30
# Poll failures for this long mean the host was lost.
LOST_CONTACT_SECONDS = 300


def expect_nonempty(paths: BackupPaths, spec: ModuleSpec) -> bool:
    """D-55: does the module's backup already hold data?"""
    if spec.type != "path" or not spec.basename:
        return False
    folder = paths.current / spec.name / spec.basename
    try:
        return folder.is_dir() and any(folder.iterdir())
    except OSError:
        return False


def module_entry(paths: BackupPaths, spec: ModuleSpec) -> dict[str, Any]:
    if spec.type == "host-config":
        return {"name": spec.name, "type": "host-config"}
    return {
        "name": spec.name,
        "type": "path",
        "src_path": spec.src_path,
        "excludes": list(spec.excludes),
        "expect_nonempty": expect_nonempty(paths, spec),
    }


def build_job(
    cfg: Config,
    paths: BackupPaths,
    kind: Literal["backup", "probe"],
    host: str,
    user: str,
    specs: list[ModuleSpec],
    *,
    run_id: str = "",
    dry_run: bool = False,
    verify: bool = False,
    timeout_seconds: int = 0,
) -> dict[str, Any]:
    return {
        "protocol": SERVER_PROTOCOL,
        "kind": kind,
        "job_id": uuid.uuid4().hex,
        "run_id": run_id,
        "user": user,
        "host_name": host,
        "server": {
            "host": cfg.server.ssh_host,
            "port": cfg.server.ssh_port,
            "user": cfg.server.receive_user,
        },
        "options": {
            "verify": verify,
            "partial": cfg.settings.resume_backup,
            "dry_run": dry_run,
            "io_timeout_seconds": cfg.settings.io_timeout_seconds,
        },
        "timeout_seconds": timeout_seconds,
        "modules": [module_entry(paths, s) for s in specs],
    }


@dataclass
class JobOutcome:
    result: dict[str, Any] | None = None
    # "timeout" | "no_result" | "lost_contact" when there is no result
    problem: str | None = None
    detail: str = ""


def wait_for_job(
    agent: Agent,
    user: str,
    job_id: str,
    clock: Clock,
    interval: float,
    timeout: float | None,
    on_poll: Callable[[], None] | None = None,
) -> JobOutcome:
    """Poll `ctl result` until the job is done.

    Never waits on the result file alone: if the user's job is not running
    on two consecutive polls (after a short grace period) and no finished
    result exists, the job ended without reporting (the host restarted, or
    the agent crashed) and waiting stops.
    """
    start = clock.now()
    failing_since = None
    not_running = 0
    while True:
        elapsed = (clock.now() - start).total_seconds()
        try:
            r = agent.result(user)
            failing_since = None
            if r and r.get("job_id") == job_id and r.get("state") == "done":
                return JobOutcome(result=r)
            if elapsed >= START_GRACE_SECONDS:
                running = user in agent.info().running
                not_running = 0 if running else not_running + 1
                if not_running >= 2:
                    r = agent.result(user)
                    if r and r.get("job_id") == job_id and r.get("state") == "done":
                        return JobOutcome(result=r)
                    return JobOutcome(
                        problem="no_result",
                        detail="the backup job stopped without reporting a result",
                    )
        except (TransportError, CtlError) as e:
            failing_since = failing_since or clock.now()
            if (clock.now() - failing_since).total_seconds() >= LOST_CONTACT_SECONDS:
                return JobOutcome(problem="lost_contact", detail=f"lost contact with host ({e})")
        if timeout is not None and elapsed >= timeout:
            return JobOutcome(problem="timeout", detail=f"no result within {timeout:.0f} s")
        if on_poll is not None:
            on_poll()
        clock.sleep(interval)
