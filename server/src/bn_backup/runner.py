# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""`bn-backup run`: one backup run (CLAUDE.md §6.7, D-13…D-17, D-30, D-45…D-57).

All or nothing: work is staged, `current/` changes only when every module is
green, a re-run within the time limit redoes only the red modules, and a
drive unplugged mid-run aborts the run and deletes everything staged.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import FIRST_EXCEPTION, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from loguru import logger

from .agentctl import CtlError, TransportError
from .clock import iso, local_stamp, parse_iso
from .config import ModuleSpec
from .env import Env
from .fsutil import atomic_write_json, atomic_write_text, ensure_dir, read_json
from .jobs import build_job, wait_for_job
from .notify import ChannelNotifier, Notifier
from .paths import BackupPaths
from .promotion import Interrupted, build, execute, promote, reset_staging
from .report import render, subject
from .state import (
    AbortInfo,
    LockHeld,
    ModuleState,
    RunState,
    load_run,
    run_lock,
    save_run,
    write_history,
)
from .status import Row, ServerReport, evaluate_rows, render_rows, render_server, server_checks

EXIT_OK, EXIT_ERROR, EXIT_UNFINISHED, EXIT_LOCKED, EXIT_ABORTED = 0, 1, 2, 3, 4
STOP_BUDGET_SECONDS = 30


class AbortRun(Exception):
    """A drive vanished mid-run (D-46)."""

    def __init__(self, info: AbortInfo) -> None:
        self.info = info
        super().__init__(info.cause)


class Cancelled(Exception):
    """The run is stopping (Ctrl-C, SIGTERM or an abort elsewhere)."""


# --------------------------------------------------------------------------- plan


@dataclass
class Plan:
    run: RunState
    new: bool
    pending_fresh: RunState | None = None  # an UNFINISHED run --fresh discards after the gate
    staging_to_delete: list[tuple[str, str, str]] = field(default_factory=list)
    expired: RunState | None = None  # an UNFINISHED run past its time limit


def _module_state(spec: ModuleSpec) -> ModuleState:
    return ModuleState(
        host=spec.host,
        user=spec.user,
        type=spec.type,
        src_path=spec.src_path,
        excludes=list(spec.excludes),
    )


def _changed(old: ModuleState, spec: ModuleSpec) -> bool:
    return (old.host, old.user, old.src_path, tuple(old.excludes)) != (
        spec.host,
        spec.user,
        spec.src_path,
        tuple(spec.excludes),
    )


def _reconcile(run: RunState, module_set: dict[str, ModuleSpec], plan: Plan) -> None:
    """Resume or EXPIRED: follow the current config (§6.7 step 4)."""
    for name in list(run.modules):
        old = run.modules[name]
        if name not in module_set:
            plan.staging_to_delete.append((old.host, old.user, name))
            del run.modules[name]
        elif _changed(old, module_set[name]):
            plan.staging_to_delete.append((old.host, old.user, name))
            run.modules[name] = _module_state(module_set[name])
    for name, spec in module_set.items():
        if name not in run.modules:
            run.modules[name] = _module_state(spec)
    for m in run.modules.values():
        if m.status != "green":
            m.status = "pending"


def plan_run(env: Env, *, fresh: bool) -> Plan:
    now = env.clock.now()
    cfg = env.cfg
    module_set = cfg.module_set()
    old = load_run(env.paths)
    ttl = timedelta(hours=cfg.settings.unfinished_ttl_hours)

    def new_run(previous_expired: bool = False) -> RunState:
        return RunState(
            run_id=local_stamp(now),
            status="RUNNING",
            mode=cfg.settings.mode,
            first_attempt_at=iso(now),
            last_attempt_at=iso(now),
            attempts=1,
            config_sha256=env.loaded.sha256,
            previous_expired=previous_expired,
            modules={n: _module_state(s) for n, s in module_set.items()},
        )

    if old is not None and old.status == "RUNNING":
        # The previous process died without finishing (§6.8).
        old.status = "UNFINISHED"
        for m in old.modules.values():
            if m.status == "pending":
                m.status, m.reason, m.error_kind = "red", "interrupted", "interrupted"
        old.last_attempt_finished_at = old.last_attempt_finished_at or old.last_attempt_at
    if fresh:
        return Plan(
            run=new_run(),
            new=True,
            pending_fresh=old if old is not None and old.status == "UNFINISHED" else None,
        )
    if old is None or old.status in ("COMPLETE", "EXPIRED", "ABORTED"):
        return Plan(run=new_run(), new=True)
    finished = parse_iso(old.last_attempt_finished_at or old.last_attempt_at)
    if now - finished >= ttl:
        # D-14, D-39: expired; every module again, staged data reused.
        plan = Plan(run=new_run(previous_expired=True), new=True, expired=old)
        stale = RunState.model_validate(old.model_dump())
        _reconcile(stale, module_set, plan)
        return plan
    resumed = RunState.model_validate(old.model_dump())
    plan = Plan(run=resumed, new=False)
    _reconcile(resumed, module_set, plan)
    resumed.status = "RUNNING"
    resumed.attempts += 1
    resumed.last_attempt_at = iso(now)
    return plan


# --------------------------------------------------------------------------- staging


def prepare_staging(paths: BackupPaths, spec: ModuleSpec) -> None:
    """Clone current/<module> into staging if needed, then drop what rsync won't refresh."""
    from .clone import clone

    ensure_dir(paths.staging_user(spec.host, spec.user), 0o700)
    dst = paths.staging_module(spec.host, spec.user, spec.name)
    if not dst.exists():
        src = paths.current / spec.name
        if src.is_dir():
            clone(src, dst)
        else:
            dst.mkdir(mode=0o700)
    keep = {spec.basename} if spec.type == "path" else None
    for entry in list(dst.iterdir()):
        drop = (entry.name not in keep) if keep is not None else entry.name in ("hosts", "motd")
        if drop:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()


# --------------------------------------------------------------------------- the run


@contextmanager
def keep_awake(platform: str) -> Iterator[None]:
    """caffeinate (macOS) or systemd-inhibit (Linux) for the whole command."""
    if platform == "darwin":
        argv = ["/usr/bin/caffeinate", "-i", "-s", "-w", str(os.getpid())]
    else:
        argv = [
            "systemd-inhibit",
            "--what=sleep:idle",
            "--who=bn-backup",
            "--why=backup run",
            "--mode=block",
            "sleep",
            "infinity",
        ]
    proc = None
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except OSError as e:
        logger.debug(f"cannot keep the server awake: {e}")
    try:
        yield
    finally:
        if proc is not None:
            proc.kill()
            proc.wait()


class Runner:
    def __init__(
        self,
        env: Env,
        notifier: Notifier,
        *,
        dry_run: bool,
        fresh: bool,
        wake: bool,
        say: Any = print,
    ) -> None:
        self.env = env
        self.paths = env.paths
        self.notifier = notifier
        self.dry_run = dry_run
        self.fresh = fresh
        self.wake = wake
        self.say = say
        self.cancel = threading.Event()
        self.state_lock = threading.Lock()
        self.active: set[tuple[str, str]] = set()
        self.volume_failures = 0
        self.last_volume_check = env.clock.now()
        self.stop_requested = False

    # ------------------------------------------------------------ helpers

    def volume_ok(self) -> bool:
        return self.env.cfg.server.backup_directory.is_dir()

    def notify(self, subj: str, body: str) -> None:
        if self.dry_run:
            return
        failures = self.notifier.send(subj, body)
        if failures and self.volume_ok():
            with suppress(OSError), self.paths.last_report.open("a", encoding="utf-8") as f:
                f.write("\nNotification failures:\n" + "".join(f"  - {x}\n" for x in failures))

    def save(self, run: RunState) -> None:
        if not self.dry_run:
            with self.state_lock:
                save_run(self.paths, run)

    def user_hosts(self) -> list[tuple[str, str]]:
        return self.env.cfg.user_hosts()

    # ------------------------------------------------------------ main

    def run(self) -> int:
        if self.dry_run and self.fresh:
            self.say("bn-backup: --dry-run and --fresh cannot be combined")
            return EXIT_ERROR
        try:
            with run_lock(self.env.operator_paths.lock, "run"), keep_awake(self.env.platform):
                return self._locked()
        except LockHeld as e:
            self.say(f"bn-backup: another run is in progress (pid {e.info.get('pid', '?')})")
            return EXIT_LOCKED

    def _locked(self) -> int:
        env = self.env
        # 2. Recover an interrupted promotion and clean up an aborted run (D-52, D-46).
        journal_exists = self.volume_ok() and self.paths.promotion_json.exists()
        marker = env.operator_paths.abort_marker
        if self.dry_run and (journal_exists or marker.exists()):
            self.say("an interrupted run needs finishing first: run `bn-backup run`")
            return EXIT_ERROR
        finished_promotion = False
        if journal_exists:
            self.say("finishing an interrupted promotion")
            execute(self.paths)
            finished_promotion = True
            done = load_run(self.paths)
            if done is not None:
                text = self.paths.last_report.read_text(encoding="utf-8")
                self.notify(subject(done) + " (finished after an interruption)", text)
        if marker.exists() and self.volume_ok():
            self.cleanup_abort(finished_promotion)

        # 3. Server checks (D-32, D-54).
        rep = server_checks(env, write_test=not self.dry_run, own_lock=True)
        if not rep.ok:
            return self.not_started_server(rep)

        # 4. Plan.
        plan = plan_run(env, fresh=self.fresh)
        run = plan.run
        if plan.expired is not None and not self.dry_run:
            plan.expired.status = "EXPIRED"
            write_history(self.paths, plan.expired)
            save_run(self.paths, plan.expired)
        pending = {n for n, m in run.modules.items() if m.status == "pending"}
        specs = env.cfg.module_set()

        # 5. The gate (D-45): every row with work must be green.
        pairs = sorted({(run.modules[n].host, run.modules[n].user) for n in pending})
        rows = evaluate_rows(env, pairs, wake=self.wake, gate=True)
        if not all(r.ok for r in rows):
            return self.not_started_rows(rows)
        if not self.dry_run:
            if plan.pending_fresh is not None:
                plan.pending_fresh.status = "EXPIRED"
                plan.pending_fresh.reason = "discarded by --fresh"
                write_history(self.paths, plan.pending_fresh)
            if self.fresh:
                reset_staging(self.paths, self.user_hosts())  # D-57: only now
            for host, user, name in plan.staging_to_delete:
                path = self.paths.staging_module(host, user, name)
                if path.is_dir():
                    shutil.rmtree(path)
            for host, user in self.user_hosts():
                ensure_dir(self.paths.staging_user(host, user), 0o700)
            run.status = "RUNNING"
            save_run(self.paths, run)

        # 6. Prepare staging.
        if not self.dry_run:
            for name in sorted(pending):
                prepare_staging(self.paths, specs[name])

        # 7. Jobs.
        try:
            interrupted = self.run_jobs(run, pending, specs)
        except AbortRun as e:
            return self.abort(run, e.info)
        if interrupted:
            return self.finish_interrupted(run)

        # 8. Decide.
        if self.dry_run:
            return self.dry_run_summary(run, pending)
        now = env.clock.now()
        if all(m.status == "green" for m in run.modules.values()):
            return self.complete(run)
        run.status = "UNFINISHED"
        run.last_attempt_finished_at = iso(now)
        return self.finish(run, EXIT_UNFINISHED)

    # ------------------------------------------------------------ outcomes

    def not_started_server(self, rep: ServerReport) -> int:
        self.say(render_server(rep))
        first = rep.first_failure()
        reason = f"{first.name}: {first.detail}" if first else "server not ready"
        self.notify(f"[bn-backup] NOT STARTED — {reason}", render_server(rep))
        return EXIT_ERROR

    def not_started_rows(self, rows: list[Row]) -> int:
        board = render_rows(rows)
        self.say(board)
        first = next(r for r in rows if not r.ok)
        self.notify(f"[bn-backup] NOT STARTED — {first.host}: {first.reason}", board)
        return EXIT_ERROR

    def dry_run_summary(self, run: RunState, pending: set[str]) -> int:
        bad = False
        for name in sorted(pending):
            m = run.modules[name]
            if m.status == "green":
                self.say(f"  would run   {name} ({m.host}/{m.user})")
            else:
                bad = True
                self.say(f"  would fail  {name} ({m.host}/{m.user}): {m.error_kind} — {m.reason}")
        return EXIT_UNFINISHED if bad else EXIT_OK

    def report_text(self, run: RunState) -> str:
        s = self.env.cfg.settings
        return render(run, s.unfinished_ttl_hours, s.io_timeout_seconds, self.env.clock.now())

    def finish(self, run: RunState, code: int) -> int:
        save_run(self.paths, run)
        write_history(self.paths, run)
        text = self.report_text(run)
        atomic_write_text(self.paths.last_report, text, 0o600)
        self.say(text)
        self.notify(subject(run), text)
        return code

    def complete(self, run: RunState) -> int:
        completed = self.env.clock.now()
        run.completed_at = iso(completed)
        text = render(
            run.model_copy(update={"status": "COMPLETE"}),
            self.env.cfg.settings.unfinished_ttl_hours,
            self.env.cfg.settings.io_timeout_seconds,
            completed,
        )
        journal = build(
            self.paths,
            run.run_id,
            run.mode,
            self.env.cfg.module_set(),
            iso(completed),
            text,
            self.env.loaded.raw.decode("utf-8"),
            self.user_hosts(),
            self.env.cfg.settings.snapshot_keep,
        )
        save_run(self.paths, run)
        stop = {"flag": False}

        def on_signal(signum: int, frame: Any) -> None:
            stop["flag"] = True

        old = _set_signals(on_signal)
        try:
            promote(self.paths, journal, should_stop=lambda: stop["flag"])
        except Interrupted:
            self.say("stopped during promotion; the next `bn-backup run` finishes it")
            return EXIT_UNFINISHED
        finally:
            _restore_signals(old)
        done = load_run(self.paths) or run
        self.say(text)
        self.notify(subject(done), text)
        return EXIT_OK

    def finish_interrupted(self, run: RunState) -> int:
        for m in run.modules.values():
            if m.status == "pending":
                m.status, m.error_kind, m.reason = "red", "interrupted", "interrupted"
        if self.dry_run:
            return EXIT_UNFINISHED
        run.status = "UNFINISHED"
        run.last_attempt_finished_at = iso(self.env.clock.now())
        return self.finish(run, EXIT_UNFINISHED)

    # ------------------------------------------------------------ jobs

    def run_jobs(self, run: RunState, pending: set[str], specs: dict[str, ModuleSpec]) -> bool:
        """Returns True when interrupted. Raises AbortRun on a critical event."""
        by_host: dict[str, dict[str, list[str]]] = {}
        for name in sorted(pending):
            m = run.modules[name]
            by_host.setdefault(m.host, {}).setdefault(m.user, []).append(name)
        interrupted = False
        abort: AbortRun | None = None
        workers = max(1, self.env.cfg.settings.max_parallel_hosts)
        pool = ThreadPoolExecutor(max_workers=workers)
        # Interrupt handling is in place before any worker starts (no race).
        old = _set_signals(_raise_interrupt)
        try:
            futures: list[Future[None]] = [
                pool.submit(self.host_worker, run, host, users, specs)
                for host, users in sorted(by_host.items())
            ]
            remaining = set(futures)
            while remaining:
                done, remaining = wait(remaining, timeout=0.5, return_when=FIRST_EXCEPTION)
                for f in done:
                    exc = f.exception()
                    if isinstance(exc, AbortRun):
                        abort = abort or exc
                    elif exc is not None and not isinstance(exc, Cancelled):
                        raise exc
                if abort is not None:
                    break
        except KeyboardInterrupt:
            interrupted = True
            self.say("interrupted: stopping the jobs")
        finally:
            # Whatever happened, workers stop at their next poll.
            if interrupted or abort is not None or sys.exc_info()[0] is not None:
                self.cancel.set()
            _restore_signals(old)
            if interrupted or abort is not None:
                self.stop_active(STOP_BUDGET_SECONDS if abort else 10)
            pool.shutdown(wait=True, cancel_futures=True)
        if abort is not None:
            raise abort
        return interrupted

    def stop_active(self, budget: float) -> None:
        with self.state_lock:
            active = sorted(self.active)
        threads = []
        for host, user in active:

            def stop(h: str = host, u: str = user) -> None:
                with suppress(CtlError, TransportError):
                    self.env.agent(h).stop(u)

            t = threading.Thread(target=stop, daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=budget)

    def on_poll(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()
        if self.dry_run:
            return
        with self.state_lock:
            now = self.env.clock.now()
            if (now - self.last_volume_check).total_seconds() < self.env.poll_seconds:
                return
            self.last_volume_check = now
            self.volume_failures = 0 if self.volume_ok() else self.volume_failures + 1
            if self.volume_failures >= 2:
                raise AbortRun(AbortInfo(cause="backup_volume_lost", at=iso(now)))

    def host_worker(
        self,
        run: RunState,
        host: str,
        users: dict[str, list[str]],
        specs: dict[str, ModuleSpec],
    ) -> None:
        env = self.env
        cfg = env.cfg
        agent = env.agent(host)
        for user, names in users.items():
            if self.cancel.is_set():
                return
            timeout_s = cfg.settings.job_timeout_minutes * 60
            job = build_job(
                cfg,
                self.paths,
                "backup",
                host,
                user,
                [specs[n] for n in names],
                run_id=run.run_id,
                dry_run=self.dry_run,
                verify=cfg.settings.verify_backup and not self.dry_run,
                timeout_seconds=timeout_s,
            )
            try:
                agent.submit(user, job)
                agent.start(user)
            except (CtlError, TransportError) as e:
                self.mark(run, names, None, problem=("other", f"could not start the job: {e}"))
                continue
            with self.state_lock:
                self.active.add((host, user))
            try:
                out = wait_for_job(
                    agent,
                    user,
                    job["job_id"],
                    env.clock,
                    env.poll_seconds,
                    timeout_s + 300 if timeout_s else None,
                    self.on_poll,
                )
            finally:
                with self.state_lock:
                    self.active.discard((host, user))
            if out.problem == "timeout":
                with suppress(CtlError, TransportError):
                    agent.stop(user)
                self.mark(run, names, None, problem=("timeout", "timeout"))
            elif out.problem is not None:
                kind = "lost_contact" if out.problem == "lost_contact" else "no_result"
                self.mark(run, names, None, problem=(kind, out.detail))
            else:
                self.mark(run, names, out.result)
            if not self.dry_run:
                self.fetch_logs(run, agent, host, user, names)
                self.save(run)
                self.check_drive(run, names, out.result)

    def mark(
        self,
        run: RunState,
        names: list[str],
        result: dict[str, Any] | None,
        problem: tuple[str, str] | None = None,
    ) -> None:
        by_name = {m["name"]: m for m in (result or {}).get("modules", [])}
        now = iso(self.env.clock.now())
        with self.state_lock:
            for n in names:
                st = run.modules[n]
                st.attempt = run.attempts
                st.finished_at = now
                r = by_name.get(n)
                if problem is not None or r is None:
                    kind, reason = problem or ("other", "the agent reported no result for it")
                    st.status, st.error_kind, st.reason = "red", kind, reason
                    continue
                st.files_transferred = int(r.get("files_transferred") or 0)
                st.bytes_transferred = int(r.get("bytes_transferred") or 0)
                st.suspect_count = int(r.get("suspect_count") or 0)
                st.suspect_files = list(r.get("suspect_files") or [])
                if r.get("status") == "ok":
                    st.status, st.error_kind, st.reason = "green", None, None
                else:
                    st.status = "red"
                    st.error_kind = r.get("error_kind") or "other"
                    st.reason = r.get("message") or ""

    def fetch_logs(self, run: RunState, agent: Any, host: str, user: str, names: list[str]) -> None:
        for n in names:
            if run.modules[n].status != "red":
                continue
            try:
                lines = agent.log(user, n)
            except (CtlError, TransportError):
                continue
            if lines:
                path = self.paths.run_logs(run.run_id) / f"{host}-{user}-{n}.log"
                ensure_dir(path.parent, 0o700)
                atomic_write_text(path, "\n".join(lines) + "\n", 0o600)

    def check_drive(self, run: RunState, names: list[str], result: dict[str, Any] | None) -> None:
        for m in (result or {}).get("modules", []):
            if m.get("error_kind") == "drive_missing":
                st = run.modules[m["name"]]
                drive = (
                    (m.get("message") or "").split("the external drive ")[-1].split(" is not")[0]
                )
                raise AbortRun(
                    AbortInfo(
                        cause="source_drive_missing",
                        host=st.host,
                        user=st.user,
                        module=m["name"],
                        drive=drive,
                        at=iso(self.env.clock.now()),
                    )
                )

    # ------------------------------------------------------------ abort (D-46)

    def abort(self, run: RunState, info: AbortInfo) -> int:
        self.say(f"ABORTED: {info.cause}")
        run.status = "ABORTED"
        run.abort = info
        for m in run.modules.values():
            if m.status != "green":
                m.status = "red"
                m.error_kind = m.error_kind if m.error_kind == "drive_missing" else "aborted"
                m.reason = m.reason or "aborted"
        text = self.report_text(run)
        if self.volume_ok():
            reset_staging(self.paths, self.user_hosts())
            save_run(self.paths, run)
            write_history(self.paths, run)
            atomic_write_text(self.paths.last_report, text, 0o600)
        else:
            marker = self.env.operator_paths.abort_marker
            ensure_dir(marker.parent, 0o700)
            atomic_write_json(
                marker,
                {
                    "run_id": run.run_id,
                    "cause": info.cause,
                    "host": info.host,
                    "user": info.user,
                    "module": info.module,
                    "drive": info.drive,
                    "at": info.at,
                },
            )
            logger.error(f"run {run.run_id} aborted: the backup drive is gone; clean-up pending")
        self.say(text)
        self.notify(subject(run), text)
        return EXIT_ABORTED

    def cleanup_abort(self, finished_promotion: bool) -> None:
        marker = self.env.operator_paths.abort_marker
        try:
            data = read_json(marker)
        except (OSError, ValueError):
            data = {}
        if not finished_promotion:
            reset_staging(self.paths, self.user_hosts())
            run = load_run(self.paths)
            if run is not None and run.run_id == data.get("run_id") and run.status != "COMPLETE":
                run.status = "ABORTED"
                run.abort = AbortInfo.model_validate(
                    {k: data.get(k) for k in ("cause", "host", "user", "module", "drive", "at")}
                )
                for m in run.modules.values():
                    if m.status != "green":
                        m.status, m.error_kind, m.reason = "red", "aborted", "aborted"
                save_run(self.paths, run)
                write_history(self.paths, run)
        marker.unlink()
        logger.info(f"cleaned up aborted run {data.get('run_id', '?')}")


def _raise_interrupt(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


def _set_signals(handler: Any) -> tuple[Any, Any] | None:
    """Install a handler for SIGINT and SIGTERM (main thread only); return the old pair."""
    if threading.current_thread() is not threading.main_thread():
        return None
    old = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    signal.signal(
        signal.SIGINT, signal.default_int_handler if handler is _raise_interrupt else handler
    )
    signal.signal(signal.SIGTERM, handler)
    return old


def _restore_signals(old: tuple[Any, Any] | None) -> None:
    if old is not None:
        signal.signal(signal.SIGINT, old[0])
        signal.signal(signal.SIGTERM, old[1])


def cmd_run(ctx: Any) -> int:
    env = Env(loaded=ctx.loaded(), operator_paths=ctx.paths, operator=ctx.operator)
    dry = bool(ctx.args.dry_run or env.cfg.settings.dry_run)
    runner = Runner(
        env,
        ChannelNotifier(env.cfg),
        dry_run=dry,
        fresh=ctx.args.fresh,
        wake=not ctx.args.no_wake,
    )
    try:
        return runner.run()
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_UNFINISHED
