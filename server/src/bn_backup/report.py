# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""The human report of a run and its notification subject (CLAUDE.md §6.13, §6.14).

Written for a non-specialist reader (D-37): each failure has one concrete
next step. The rsync exit-code table is ported from v1's command_executor.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .clock import local_display, local_stamp, parse_iso
from .state import ModuleState, RunState

# Exit codes documented in rsync(1) (from v1).
RSYNC_EXIT_CODES = {
    1: "syntax or usage error",
    2: "protocol incompatibility",
    3: "errors selecting input/output files or directories",
    4: "requested action not supported",
    5: "error starting client-server protocol",
    6: "daemon unable to append to log file",
    10: "error in socket I/O",
    11: "error in file I/O",
    12: "error in rsync protocol data stream",
    13: "errors with program diagnostics",
    14: "error in IPC code",
    20: "received SIGUSR1 or SIGINT",
    21: "some error returned by waitpid()",
    22: "error allocating core memory buffers",
    23: "partial transfer due to error",
    24: "partial transfer due to vanished source files",
    25: "the --max-delete limit stopped deletions",
    30: "timeout in data send/receive",
    35: "timeout waiting for daemon connection",
    127: "rsync not found",
    255: "SSH connection failed (host unreachable or authentication error)",
}

MAX_SUSPECTS_SHOWN = 20
SUSPECT_EXPLANATION = (
    "One of the two copies of each file is damaged. Nothing was overwritten. Open the "
    "original and the backup copy (in current/<module>/ on the server) and keep the good "
    "one: copy the backup over the original, or re-save the original so the next run copies it."
)


def hint(name: str, m: ModuleState, io_timeout_seconds: int) -> str:
    """One concrete next step per error kind (§6.13)."""
    host, user, src = m.host, m.user, m.src_path or "the folder"
    kind = m.error_kind or ""
    drive = (m.reason or "").split("the external drive ")[-1].split(" is not")[0]
    hints = {
        "tcc": (
            f"Switch on BNBackupAgent in Full Disk Access on {host}. If it is already on, the "
            "server may have refused the write: check 'Allow full disk access for remote users' "
            "on the server"
        ),
        "server_denied": (
            "The server refused to write to the backup drive. On the Mac mini: System Settings "
            "→ General → Sharing → Remote Login → ⓘ → turn on 'Allow full disk access for remote "
            "users', and check the drive is not read-only"
        ),
        "permission": f"{user} cannot read some files in {src} on {host}; fix their ownership or exclude them",
        "missing": f"{src} does not exist on {host}; check the path in the config",
        "drive_missing": f"Is the external drive {drive or '…'} connected to {host}? Connect it and run again",
        "source_empty": (
            f"{src} on {host} is empty, but its backup is not. If a drive belongs there, connect "
            "it and run again. If you emptied the folder on purpose, remove the module from the "
            "config (its backup moves to removed/)"
        ),
        "network": f"{host} could not reach the server; check the network and the names",
        "stalled": f"No progress for {io_timeout_seconds} s; check the network or a sleeping drive",
        "timeout": "The job ran longer than job_timeout_minutes; raise it or set it to 0",
        "lost_contact": (
            f"The server lost {host} during the run; check that it is awake and on the network, "
            "then run again"
        ),
        "no_result": f"The backup job on {host} stopped without reporting; check whether {host} restarted, then run again",
        "interrupted": "The run was interrupted; run bn-backup run again",
        "aborted": "The run was aborted because a drive was unplugged",
    }
    return hints.get(kind, "See the rsync log for details")


def _module_line(name: str, m: ModuleState) -> str:
    first = (m.reason or "").splitlines()[0] if m.reason else ""
    what = m.error_kind or "error"
    return f"  - {name} ({m.host}/{m.user}): {what}" + (f" — {first}" if first else "")


def status_line(run: RunState, ttl_hours: int) -> str:
    if run.status == "UNFINISHED" and run.last_attempt_finished_at:
        until = parse_iso(run.last_attempt_finished_at) + timedelta(hours=ttl_hours)
        return f"UNFINISHED — re-run before {local_display(until)} to complete it"
    if run.status == "ABORTED" and run.abort is not None:
        a = run.abort
        what = (
            "the backup drive"
            if a.cause == "backup_volume_lost"
            else f"the drive {a.drive or '?'} on {a.host or '?'}"
        )
        return (
            f"ABORTED — {what} was unplugged during the run; everything staged was deleted. "
            "Reconnect it and run again; the backup starts from zero. Your last complete backup "
            "is untouched."
        )
    return run.status


def render(run: RunState, ttl_hours: int, io_timeout_seconds: int, now: datetime) -> str:
    started = local_display(parse_iso(run.first_attempt_at))
    end = run.completed_at or run.last_attempt_finished_at
    finished = local_display(parse_iso(end)) if end else "–"
    lines = [
        "Backup Report",
        "====================",
        "",
        f"Run:      {run.run_id}   (attempt {run.attempts})",
        f"Status:   {status_line(run, ttl_hours)}",
        f"Started:  {started}   Finished: {finished}",
        f"Mode:     {run.mode}",
        "",
    ]
    if run.previous_expired:
        lines += [
            f"Note: the previous run was not completed within {ttl_hours} h of its last attempt; "
            "every module was backed up again (data already copied was reused).",
            "",
        ]
    ok = {n: m for n, m in run.modules.items() if m.status == "green"}
    bad = {n: m for n, m in run.modules.items() if m.status != "green"}
    lines.append("Successful:")
    lines += [f"  - {n} ({m.host}/{m.user})" for n, m in ok.items()] or ["  (none)"]
    lines.append("Failed:")
    if not bad:
        lines.append("  (none)")
    for n, m in bad.items():
        lines.append(_module_line(n, m))
        lines.append(f"    hint: {hint(n, m, io_timeout_seconds)}.")
    suspects = {n: m for n, m in run.modules.items() if m.suspect_count > 0}
    if suspects:
        lines += ["", "Files to check (verify_backup):"]
        for n, m in suspects.items():
            lines.append(
                f"  - {n}: {m.suspect_count} files differ from their backup although date and size match"
            )
            lines += [f"      {f}" for f in m.suspect_files[:MAX_SUSPECTS_SHOWN]]
            if m.suspect_count > MAX_SUSPECTS_SHOWN:
                lines.append(
                    f"      … and {m.suspect_count - MAX_SUSPECTS_SHOWN} more; "
                    f"see `bn-backup runs show {run.run_id}`"
                )
        lines.append(SUSPECT_EXPLANATION)
    lines += ["", f"# Date: {local_stamp(now)}"]
    return "\n".join(lines) + "\n"


def subject(run: RunState) -> str:
    green, total = run.counts()
    if run.status == "COMPLETE":
        s = f"[bn-backup] COMPLETE — {total}/{total} modules"
    elif run.status == "ABORTED" and run.abort is not None:
        a = run.abort
        what = (
            "backup drive unplugged"
            if a.cause == "backup_volume_lost"
            else f"{a.drive or 'a drive'} unplugged on {a.host or '?'}"
        )
        s = f"[bn-backup] ABORTED — {what}"
    else:
        s = f"[bn-backup] {run.status} — {total - green} of {total} modules red"
    files = sum(m.suspect_count for m in run.modules.values())
    if files:
        s += f" — {files} files to check"
    return s


def rsync_meaning(code: int | None) -> str:
    return RSYNC_EXIT_CODES.get(code, "") if code is not None else ""
