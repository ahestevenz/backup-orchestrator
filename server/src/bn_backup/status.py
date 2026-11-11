# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""The board: would a backup start and succeed? (CLAUDE.md §6.5, D-45, D-49)

Read-only: no lock, no run.json, no config or host changes. It only wakes
hosts and runs probe jobs (whose one trace is the tiny `.probe/` folder, D-56).
The same row checks are the pre-flight gate of `bn-backup run`.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from .agentctl import Agent, AgentInfo, CtlError, TransportError
from .clock import local_display, parse_iso
from .config import ModuleSpec
from .env import Env
from .fsutil import read_json
from .jobs import build_job, wait_for_job
from .state import (
    load_history,
    load_host,
    load_run,
    lock_holder,
)
from .wake import wake_and_wait

PROBE_TIMEOUT_SECONDS = 120
STOP_WAIT_SECONDS = 30
MIN_RSYNC = (3, 2, 3)
ROW_CHECKS = ("dns", "reachable", "agent", "user", "idle", "probe")


@dataclass
class Check:
    name: str
    ok: bool | None  # None: not evaluated because an earlier check failed
    detail: str = ""


@dataclass
class ServerReport:
    checks: list[Check]
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def first_failure(self) -> Check | None:
        return next((c for c in self.checks if c.ok is False), None)


@dataclass
class Row:
    host: str
    user: str
    checks: list[Check] = field(default_factory=list)
    last_complete: str | None = None
    pending: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.checks) == len(ROW_CHECKS) and all(c.ok for c in self.checks)

    @property
    def reason(self) -> str:
        bad = next((c for c in self.checks if c.ok is False), None)
        return f"{bad.name}: {bad.detail}" if bad else ""

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name, ok, detail))

    def fail_rest(self) -> None:
        done = {c.name for c in self.checks}
        for name in ROW_CHECKS:
            if name not in done:
                self.checks.append(Check(name, None, "–"))


# --------------------------------------------------------------------------- server


def mount_point(path: Path) -> Path:
    p = path
    while not os.path.ismount(p) and p != p.parent:
        p = p.parent
    return p


def rrsync_rsync_path(rrsync: Path) -> str | None:
    try:
        text = rrsync.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^RSYNC = '([^']+)'", text, re.MULTILINE)
    return m.group(1) if m else None


def rsync_version(rsync: str) -> tuple[int, ...] | None:
    try:
        out = subprocess.run(
            [rsync, "--version"], capture_output=True, text=True, timeout=10, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.match(r"rsync\s+version\s+(\d+)\.(\d+)\.(\d+)", out)
    return tuple(int(x) for x in m.groups()) if m else None


def volume_write_test(state_dir: Path) -> str | None:
    """D-54: create, clone and delete a file. None on success, else the problem."""
    from .clone import clone

    a = state_dir / f".write-test-{os.getpid()}"
    b = state_dir / f".write-test-{os.getpid()}-clone"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        a.write_text("bn-backup write test\n")
        clone(a, b)
        return None
    except OSError as e:
        return str(e)
    finally:
        for f in (a, b):
            with contextlib.suppress(OSError):
                f.unlink()


def server_checks(env: Env, *, write_test: bool, own_lock: bool = False) -> ServerReport:
    """`own_lock`: the caller (a run) holds the run lock itself."""
    cfg = env.cfg
    paths = env.paths
    checks: list[Check] = [Check("config", True, str(env.loaded.path))]
    notes: list[str] = []
    root = cfg.server.backup_directory
    volume_ok = root.is_dir()
    checks.append(
        Check(
            "volume",
            volume_ok,
            f"{root} on {mount_point(root)}"
            if volume_ok
            else f"{root} is missing: is the backup drive connected and mounted?",
        )
    )
    if env.platform == "darwin":
        info = env.volumes.info(mount_point(root)) if volume_ok else None
        if not volume_ok:
            checks += [Check("apfs_case_sensitive", None, "–"), Check("ownership", None, "–")]
        elif info is None:
            checks += [
                Check("apfs_case_sensitive", False, "diskutil gave no information"),
                Check("ownership", None, "–"),
            ]
        else:
            fs_ok = info.get("FilesystemType") == "apfs" and "Case-sensitive" in str(
                info.get("FilesystemUserVisibleName", "")
            )
            checks.append(
                Check(
                    "apfs_case_sensitive",
                    fs_ok,
                    str(info.get("FilesystemUserVisibleName", ""))
                    if fs_ok
                    else "the backup drive must be formatted APFS (Case-sensitive)",
                )
            )
            perms = bool(info.get("GlobalPermissionsEnabled", False))
            checks.append(
                Check(
                    "ownership",
                    perms,
                    "" if perms else "untick 'Ignore ownership on this volume' (Finder → Get Info)",
                )
            )
    if not volume_ok:
        checks.append(Check("volume_writable", None, "–"))
        checks.append(Check("free_space", None, "–"))
    else:
        if write_test:
            problem = volume_write_test(paths.state)
            checks.append(
                Check(
                    "volume_writable",
                    problem is None,
                    problem or "created, cloned and deleted a test file",
                )
            )
        else:
            writable = os.access(paths.state, os.W_OK) or (
                not paths.state.exists() and os.access(root, os.W_OK)
            )
            checks.append(
                Check(
                    "volume_writable",
                    writable,
                    "" if writable else f"{paths.state} is not writable",
                )
            )
        free_gb = shutil.disk_usage(root).free / 2**30
        enough = free_gb >= cfg.settings.min_free_gb
        checks.append(
            Check(
                "free_space",
                enough,
                f"{free_gb:.0f} GB free"
                + ("" if enough else f" (min_free_gb: {cfg.settings.min_free_gb})"),
            )
        )
    rrsync = env.operator_paths.rrsync
    rsync = rrsync_rsync_path(rrsync) if os.access(rrsync, os.X_OK) else None
    version = rsync_version(rsync) if rsync else None
    rr_ok = version is not None and version >= MIN_RSYNC
    checks.append(
        Check(
            "rrsync",
            rr_ok,
            f"{rrsync} → rsync {'.'.join(map(str, version))}"
            if rr_ok and version
            else "rrsync is missing or its rsync is older than 3.2.3: run bn-backup server init",
        )
    )
    interrupted = volume_ok and paths.promotion_json.exists()
    checks.append(
        Check(
            "promotion",
            not interrupted,
            "a promotion was interrupted; bn-backup run finishes it" if interrupted else "",
        )
    )
    holder = None if own_lock else lock_holder(env.operator_paths.lock)
    checks.append(
        Check(
            "lock",
            holder is None,
            "" if holder is None else f"a run is in progress (pid {holder.get('pid', '?')})",
        )
    )
    marker = env.operator_paths.abort_marker
    if marker.is_file():
        try:
            run_id = read_json(marker).get("run_id", "?")
        except (OSError, ValueError):
            run_id = "?"
        notes.append(
            f"clean-up pending from aborted run {run_id}; "
            "the next bn-backup run deletes staging first"
        )
    return ServerReport(checks, notes)


# --------------------------------------------------------------------------- rows

SERVER_ERROR_HINTS = {
    "server_denied": (
        "the server refused the write. On a Mac server: System Settings → General → Sharing → "
        "Remote Login → ⓘ → turn on 'Allow full disk access for remote users', and check the "
        "drive is not read-only"
    ),
    "network": "{host} could not reach the server; check the network and the names",
}


def specs_for(env: Env, host: str, user: str) -> list[ModuleSpec]:
    return [s for s in env.cfg.module_set().values() if s.host == host and s.user == user]


def probe_verdict(host: str, result: dict[str, Any]) -> tuple[bool, str]:
    if result.get("fda") == "denied":
        return False, f"Switch on BNBackupAgent in Full Disk Access on {host}"
    bad = [m for m in result.get("modules", []) if m.get("status") != "ok"]
    if bad:
        parts = [f"{m['name']}: {m.get('error_kind')} — {m.get('message', '')}" for m in bad]
        return False, "; ".join(parts)
    if result.get("server_reachable") is False:
        kind = result.get("server_error_kind") or "network"
        hint = SERVER_ERROR_HINTS.get(kind, SERVER_ERROR_HINTS["network"]).format(host=host)
        return False, f"{hint} ({result.get('server_error', '')})"
    return True, ""


def probe_result(env: Env, agent: Agent, host: str, user: str) -> tuple[dict[str, Any] | None, str]:
    """Run one probe job; (result, problem)."""
    job = build_job(env.cfg, env.paths, "probe", host, user, specs_for(env, host, user))
    try:
        agent.submit(user, job)
        agent.start(user)
    except (CtlError, TransportError) as e:
        return None, f"could not start a probe job: {e}"
    out = wait_for_job(
        agent,
        user,
        job["job_id"],
        env.clock,
        env.probe_poll_seconds,
        PROBE_TIMEOUT_SECONDS,
    )
    return out.result, out.detail


def run_probe(env: Env, agent: Agent, host: str, user: str) -> tuple[bool, str]:
    result, problem = probe_result(env, agent, host, user)
    if result is None:
        return False, f"probe: {problem}"
    return probe_verdict(host, result)


def _wait_stopped(env: Env, agent: Agent, user: str) -> bool:
    waited = 0.0
    while waited < STOP_WAIT_SECONDS:
        env.clock.sleep(2)
        waited += 2
        try:
            if user not in agent.info().running:
                return True
        except (CtlError, TransportError):
            return False
    return False


def host_rows(env: Env, host: str, users: list[str], *, wake: bool, gate: bool) -> list[Row]:
    rows = [Row(host, u) for u in users]
    target = env.target(host)

    def fail(name: str, detail: str) -> list[Row]:
        for r in rows:
            r.add(name, False, detail)
            r.fail_rest()
        return rows

    if not env.resolves(target.address):
        return fail("dns", f"{target.address} does not resolve; fix DNS or the config")
    for r in rows:
        r.add("dns", True, target.address)

    up = env.reachable(target.address, target.ssh_port, 10.0)
    if not up and wake and env.cfg.settings.wake.enabled:
        rec = load_host(env.paths, host)
        macs = [m.mac for m in rec.mac_addresses] if rec else []
        if macs:
            logger.info(f"{host}: waking it up")
            up = wake_and_wait(
                macs,
                lambda: env.reachable(target.address, target.ssh_port, 10.0),
                env.send_wake,
                env.clock,
                env.cfg.settings.wake.wait_seconds,
            )
            if not up:
                return fail("reachable", "unreachable after wake attempt")
        else:
            for r in rows:
                r.notes.append("no known MAC address, so it was not woken")
    if not up:
        return fail("reachable", "unreachable (asleep, off or offline)")
    for r in rows:
        r.add("reachable", True)

    agent = env.agent(host)
    try:
        info: AgentInfo = agent.info()
    except (CtlError, TransportError) as e:
        return fail("agent", f"{e}; run bn-backup hosts bootstrap {host}")
    if not info.protocol_ok:
        return fail(
            "agent",
            f"agent {info.agent_version} speaks protocol {info.protocol_min}-{info.protocol_max}; "
            f"run bn-backup agent upgrade {host}",
        )
    for r in rows:
        r.add("agent", True, f"agent {info.agent_version}")

    for r in rows:
        if r.user not in info.users:
            r.add("user", False, f"run bn-backup hosts configure {host}")
            r.fail_rest()
            continue
        r.add("user", True)
        if r.user in info.running:
            if gate:
                logger.info(f"{host}/{r.user}: stopping a leftover job")
                with contextlib.suppress(CtlError, TransportError):
                    agent.stop(r.user)
                if not _wait_stopped(env, agent, r.user):
                    r.add(
                        "idle",
                        False,
                        "a job from an earlier run is still running and will not stop",
                    )
                    r.fail_rest()
                    continue
            else:
                r.add("idle", False, "a job from an earlier run is still running")
                r.fail_rest()
                continue
        r.add("idle", True)
        ok, detail = run_probe(env, agent, host, r.user)
        r.add("probe", ok, detail)
    return rows


def evaluate_rows(env: Env, pairs: list[tuple[str, str]], *, wake: bool, gate: bool) -> list[Row]:
    """Rows for (host, user) pairs; hosts in parallel, users of a host in order."""
    by_host: dict[str, list[str]] = {}
    for host, user in pairs:
        by_host.setdefault(host, []).append(user)
    with ThreadPoolExecutor(max_workers=env.cfg.settings.max_parallel_hosts) as pool:
        futures = {
            h: pool.submit(host_rows, env, h, us, wake=wake, gate=gate) for h, us in by_host.items()
        }
        rows = [r for h in sorted(futures) for r in futures[h].result()]
    annotate(env, rows)
    return rows


def annotate(env: Env, rows: list[Row]) -> None:
    """The `last complete` and `pending` columns."""
    history = sorted(load_history(env.paths), key=lambda r: r.completed_at or "", reverse=True)
    run = load_run(env.paths)
    ttl = timedelta(hours=env.cfg.settings.unfinished_ttl_hours)
    for row in rows:
        for h in history:
            if (
                h.status == "COMPLETE"
                and h.completed_at
                and any(m.host == row.host and m.user == row.user for m in h.modules.values())
            ):
                row.last_complete = local_display(parse_iso(h.completed_at))
                break
        if run and run.status == "UNFINISHED":
            todo = [
                m
                for m in run.modules.values()
                if m.host == row.host and m.user == row.user and m.status != "green"
            ]
            if todo and run.last_attempt_finished_at:
                left = parse_iso(run.last_attempt_finished_at) + ttl - env.clock.now()
                hours = left.total_seconds() / 3600
                row.pending = (
                    "EXPIRED" if hours <= 0 else f"{len(todo)} to redo, {hours:.0f} h left"
                )


# --------------------------------------------------------------------------- output


def _mark(ok: bool | None) -> str:
    return {True: "ok", False: "RED", None: "–"}[ok]


def render_server(rep: ServerReport) -> str:
    head = f"Server: {'green' if rep.ok else 'RED'}"
    lines = [head]
    for c in rep.checks:
        lines.append(f"  {_mark(c.ok):<3} {c.name:<20} {c.detail}")
    lines += [f"  note: {n}" for n in rep.notes]
    return "\n".join(lines)


def render_rows(rows: list[Row]) -> str:
    if not rows:
        return "No hosts have modules in the config."
    out = [f"{'HOST/USER':<28} {'STATUS':<7} {'LAST COMPLETE':<17} {'PENDING':<22} DETAIL"]
    for r in rows:
        out.append(
            f"{r.host + '/' + r.user:<28} {'green' if r.ok else 'RED':<7} "
            f"{r.last_complete or '–':<17} {r.pending or '–':<22} {r.reason}"
        )
        out += [f"{'':<28} note: {n}" for n in r.notes]
    return "\n".join(out)


def to_json(rep: ServerReport | None, rows: list[Row] | None, progress: Any = None) -> str:
    data: dict[str, Any] = {}
    if rep is not None:
        data["server"] = {
            "ok": rep.ok,
            "checks": [asdict(c) for c in rep.checks],
            "notes": rep.notes,
        }
    if rows is not None:
        data["rows"] = [{**asdict(r), "ok": r.ok, "reason": r.reason} for r in rows]
    if progress is not None:
        data["run_in_progress"] = progress
    return json.dumps(data, indent=2)


def run_progress(env: Env) -> dict[str, Any] | None:
    run = load_run(env.paths)
    if run is None:
        return None
    green, total = run.counts()
    return {
        "run_id": run.run_id,
        "status": run.status,
        "attempt": run.attempts,
        "green": green,
        "total": total,
        "red": sorted(run.red()),
    }


# --------------------------------------------------------------------------- commands


def _make_env(ctx: Any) -> Env:
    from .env import Env as _Env

    return _Env(loaded=ctx.loaded(), operator_paths=ctx.paths, operator=ctx.operator)


def _board(
    ctx: Any,
    *,
    server: bool,
    rows_wanted: bool,
    host: str | None,
    env_factory: Callable[[Any], Env],
) -> int:
    env = env_factory(ctx)
    rep = server_checks(env, write_test=False) if server else None
    rows: list[Row] | None = None
    progress = None
    if rows_wanted:
        if lock_holder(env.operator_paths.lock) is not None:
            # Never disturb a running backup: show its progress instead of probing.
            progress = run_progress(env) or {"note": "a run is starting"}
        else:
            pairs = [(h, u) for h, u in env.cfg.user_hosts() if host is None or h == host]
            if host is not None and not pairs:
                print(f"bn-backup: {host} has no modules in the config")
                return 1
            rows = evaluate_rows(env, pairs, wake=not ctx.args.no_wake, gate=False)
    if ctx.args.json:
        print(to_json(rep, rows, progress))
    else:
        if rep is not None:
            print(render_server(rep))
        if progress is not None:
            print(
                f"\nA run is in progress ({progress.get('run_id', '?')}, "
                f"{progress.get('green', 0)}/{progress.get('total', 0)} modules green); "
                "hosts are not probed while it runs."
            )
        if rows is not None:
            print()
            print(render_rows(rows))
    red = (rep is not None and not rep.ok) or (rows is not None and not all(r.ok for r in rows))
    return 2 if red else 0


def cmd_status(ctx: Any) -> int:
    return _board(ctx, server=True, rows_wanted=True, host=None, env_factory=_make_env)


def cmd_server_status(ctx: Any) -> int:
    return _board(ctx, server=True, rows_wanted=False, host=None, env_factory=_make_env)


def cmd_agent_status(ctx: Any) -> int:
    return _board(ctx, server=False, rows_wanted=True, host=ctx.args.host, env_factory=_make_env)
