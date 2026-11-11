# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""`runs list`, `runs show` and `runs cancel` (CLAUDE.md §6.16, D-35)."""

from __future__ import annotations

import json
import os
import signal
import time
from datetime import datetime, timedelta
from typing import Any

from .clock import SystemClock, local_display, parse_iso
from .env import Env
from .paths import BackupPaths
from .report import status_line
from .state import RunState, load_history, load_run, lock_holder


def all_runs(paths: BackupPaths) -> list[RunState]:
    """History plus run.json when it is newer and not yet in history."""
    runs = {r.run_id: r for r in load_history(paths)}
    current = load_run(paths)
    if current is not None:
        runs[current.run_id] = current
    return sorted(runs.values(), key=lambda r: r.run_id, reverse=True)


def shown_status(run: RunState, ttl_hours: int, now: datetime) -> str:
    """An UNFINISHED run past its time limit is shown as EXPIRED."""
    if (
        run.status == "UNFINISHED"
        and run.last_attempt_finished_at
        and now - parse_iso(run.last_attempt_finished_at) >= timedelta(hours=ttl_hours)
    ):
        return "EXPIRED"
    return run.status


def _when(value: str | None) -> str:
    return local_display(parse_iso(value)) if value else "–"


def _env(ctx: Any) -> Env:
    return Env(loaded=ctx.loaded(), operator_paths=ctx.paths, operator=ctx.operator)


def cmd_list(ctx: Any) -> int:
    env = _env(ctx)
    ttl = env.cfg.settings.unfinished_ttl_hours
    now = SystemClock().now()
    runs = all_runs(env.paths)[: max(0, ctx.args.limit)]
    if ctx.args.json:
        out = []
        for r in runs:
            green, total = r.counts()
            out.append(
                {
                    "run_id": r.run_id,
                    "status": shown_status(r, ttl, now),
                    "attempts": r.attempts,
                    "green": green,
                    "total": total,
                    "first_attempt_at": r.first_attempt_at,
                    "completed_at": r.completed_at,
                }
            )
        print(json.dumps(out, indent=2))
        return 0
    if not runs:
        print("No runs yet.")
        return 0
    print(
        f"{'RUN':<17} {'STATUS':<11} {'ATTEMPTS':<9} {'GREEN':<9} {'FIRST ATTEMPT':<17} COMPLETED"
    )
    for r in runs:
        green, total = r.counts()
        print(
            f"{r.run_id:<17} {shown_status(r, ttl, now):<11} {r.attempts:<9} "
            f"{f'{green}/{total}':<9} {_when(r.first_attempt_at):<17} {_when(r.completed_at)}"
        )
    return 0


def cmd_show(ctx: Any) -> int:
    env = _env(ctx)
    run = next((r for r in all_runs(env.paths) if r.run_id == ctx.args.run_id), None)
    if run is None:
        print(f"bn-backup: no run {ctx.args.run_id}")
        return 1
    if ctx.args.json:
        print(json.dumps(run.model_dump(mode="json"), indent=2))
        return 0
    s = env.cfg.settings
    print(f"Run:      {run.run_id}   (attempt {run.attempts})")
    print(f"Status:   {status_line(run, s.unfinished_ttl_hours)}")
    print(
        f"Started:  {_when(run.first_attempt_at)}   Finished: {_when(run.completed_at or run.last_attempt_finished_at)}"
    )
    print(f"Mode:     {run.mode}\n")
    for name, m in sorted(run.modules.items()):
        log = env.paths.run_logs(run.run_id) / f"{m.host}-{m.user}-{name}.log"
        print(f"{name} ({m.host}/{m.user}): {m.status}")
        if m.error_kind:
            print(f"  {m.error_kind}: {(m.reason or '').splitlines()[0] if m.reason else ''}")
        print(
            f"  attempt {m.attempt}, {m.files_transferred} files, {m.bytes_transferred} bytes"
            + (f", {m.suspect_count} files to check" if m.suspect_count else "")
        )
        for f in m.suspect_files:
            print(f"    check: {f}")
        if log.exists():
            print(f"  log: {log}")
    return 0


def cmd_cancel(ctx: Any) -> int:
    holder = lock_holder(ctx.paths.lock)
    if holder is None:
        print("no run in progress")
        return 1
    pid = holder.get("pid")
    if not isinstance(pid, int):
        print("bn-backup: the lock does not name a process")
        return 1
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if lock_holder(ctx.paths.lock) is None:
            run = load_run(BackupPaths(ctx.loaded().config.server.backup_directory))
            run_id = run.run_id if run else "?"
            print(f"cancelled; run {run_id} is UNFINISHED")
            return 0
        time.sleep(1)
    print("still stopping")
    return 1
