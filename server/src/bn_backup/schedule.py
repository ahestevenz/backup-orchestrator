# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Scheduled runs on the server (CLAUDE.md §6.15, D-26).

`install` and `remove` are the only commands that run as root: they write a
LaunchDaemon (macOS) or a systemd service and timer (Linux) that runs
`bn-backup run` as the operator.
"""

from __future__ import annotations

import os
import plistlib
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from .fsutil import atomic_write_bytes, atomic_write_text
from .paths import OperatorPaths

LABEL = "ar.bleiben.bn-backup.schedule"
PLIST = Path(f"/Library/LaunchDaemons/{LABEL}.plist")
UNIT_DIR = Path("/etc/systemd/system")
SERVICE = "bn-backup-schedule.service"
TIMER = "bn-backup-schedule.timer"
WEEKDAYS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
SYSTEMD_DAYS = {
    "sun": "Sun",
    "mon": "Mon",
    "tue": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
}


class ScheduleError(Exception):
    pass


def parse_at(value: str) -> tuple[int, int]:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", value)
    if not m:
        raise ScheduleError(f"--at {value!r}: use HH:MM, for example 02:00")
    return int(m.group(1)), int(m.group(2))


def render_plist(
    operator: str,
    exe: str,
    config: Path,
    weekday: str | None,
    hour: int,
    minute: int,
    log: Path,
) -> bytes:
    interval: dict[str, int] = {"Hour": hour, "Minute": minute}
    if weekday is not None:
        interval = {"Weekday": WEEKDAYS[weekday], **interval}
    data: dict[str, Any] = {
        "Label": LABEL,
        "UserName": operator,
        "ProgramArguments": [exe, "-c", str(config), "run"],
        "StartCalendarInterval": interval,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }
    return plistlib.dumps(data)


def render_service(operator: str, exe: str, config: Path) -> str:
    return (
        "[Unit]\n"
        "Description=bleiben Backup Orchestrator scheduled run\n"
        "Wants=network-online.target\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"User={operator}\n"
        f"ExecStart={shlex.quote(exe)} -c {shlex.quote(str(config))} run\n"
    )


def render_timer(weekday: str | None, hour: int, minute: int) -> str:
    day = f"{SYSTEMD_DAYS[weekday]} " if weekday else ""
    return (
        "[Unit]\n"
        "Description=bleiben Backup Orchestrator schedule\n\n"
        "[Timer]\n"
        f"OnCalendar={day}*-*-* {hour:02d}:{minute:02d}:00\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def sudo_hint(args: Any) -> str:
    when = f"--weekly {args.weekly}" if args.weekly else "--daily"
    return f'sudo "$(command -v bn-backup)" schedule install {when} --at {args.at}'


def _operator() -> str:
    user = os.environ.get("SUDO_USER", "")
    if not user or user == "root":
        raise ScheduleError("run it through sudo from your own account, not as root directly")
    return user


def _run(*argv: str) -> None:
    subprocess.run(list(argv), check=False, capture_output=True)


def cmd_install(ctx: Any) -> int:
    a = ctx.args
    if os.geteuid() != 0:
        print("Installing a schedule needs administrator rights. Run:")
        print(f"  {sudo_hint(a)}")
        return 1
    try:
        operator = _operator()
        hour, minute = parse_at(a.at)
    except ScheduleError as e:
        print(f"bn-backup: {e}", file=sys.stderr)
        return 1
    ctx.loaded()  # the operator's config must be valid
    exe = os.path.abspath(sys.argv[0])
    config = ctx.config_path.resolve()
    op: OperatorPaths = ctx.paths
    weekday = a.weekly if a.weekly else None
    if sys.platform == "darwin":
        _run("/bin/launchctl", "bootout", f"system/{LABEL}")
        atomic_write_bytes(
            PLIST,
            render_plist(operator, exe, config, weekday, hour, minute, op.schedule_log),
            0o644,
        )
        os.chown(PLIST, 0, 0)
        _run("/bin/launchctl", "bootstrap", "system", str(PLIST))
    else:
        atomic_write_text(UNIT_DIR / SERVICE, render_service(operator, exe, config), 0o644)
        atomic_write_text(UNIT_DIR / TIMER, render_timer(weekday, hour, minute), 0o644)
        _run("systemctl", "daemon-reload")
        _run("systemctl", "enable", "--now", TIMER)
    when = f"every {weekday}" if weekday else "every day"
    print(f"scheduled: bn-backup run as {operator}, {when} at {hour:02d}:{minute:02d}")
    return 0


def cmd_show(ctx: Any) -> int:
    if sys.platform == "darwin":
        if not PLIST.exists():
            print("No schedule.")
            return 0
        data = plistlib.loads(PLIST.read_bytes())
        iv = data.get("StartCalendarInterval", {})
        days = {v: k for k, v in WEEKDAYS.items()}
        when = f"every {days[iv['Weekday']]}" if "Weekday" in iv else "every day"
        print(
            f"{when} at {iv.get('Hour', 0):02d}:{iv.get('Minute', 0):02d}, as {data.get('UserName')}"
        )
        return 0
    timer = UNIT_DIR / TIMER
    if not timer.exists():
        print("No schedule.")
        return 0
    m = re.search(r"^OnCalendar=(.*)$", timer.read_text(), re.MULTILINE)
    print(f"OnCalendar={m.group(1) if m else '?'}")
    return 0


def cmd_remove(ctx: Any) -> int:
    if os.geteuid() != 0:
        print(
            'Removing the schedule needs administrator rights. Run:\n  sudo "$(command -v bn-backup)" schedule remove'
        )
        return 1
    if sys.platform == "darwin":
        _run("/bin/launchctl", "bootout", f"system/{LABEL}")
        PLIST.unlink(missing_ok=True)
    else:
        _run("systemctl", "disable", "--now", TIMER)
        (UNIT_DIR / TIMER).unlink(missing_ok=True)
        (UNIT_DIR / SERVICE).unlink(missing_ok=True)
        _run("systemctl", "daemon-reload")
    print("schedule removed")
    return 0
