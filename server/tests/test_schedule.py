# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Scheduling (CLAUDE.md §6.15)."""

from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

from bn_backup import cli
from bn_backup.schedule import ScheduleError, parse_at, render_plist, render_service, render_timer


def test_parse_at() -> None:
    assert parse_at("02:00") == (2, 0)
    assert parse_at("23:59") == (23, 59)
    for bad in ("24:00", "2", "02:60", "noon"):
        with pytest.raises(ScheduleError):
            parse_at(bad)


def test_plist_weekly_and_daily(tmp_path: Path) -> None:
    raw = render_plist(
        "ariel",
        "/Users/ariel/.local/bin/bn-backup",
        Path("/Users/ariel/.config/bn-backup/config.yml"),
        "sun",
        2,
        0,
        Path("/Users/ariel/Library/Logs/bn-backup-schedule.log"),
    )
    data = plistlib.loads(raw)
    assert data["Label"] == "ar.bleiben.bn-backup.schedule"
    assert data["UserName"] == "ariel"
    assert data["ProgramArguments"] == [
        "/Users/ariel/.local/bin/bn-backup",
        "-c",
        "/Users/ariel/.config/bn-backup/config.yml",
        "run",
    ]
    assert data["StartCalendarInterval"] == {"Weekday": 0, "Hour": 2, "Minute": 0}
    daily = plistlib.loads(render_plist("a", "/x", Path("/c"), None, 21, 30, Path("/l")))
    assert daily["StartCalendarInterval"] == {"Hour": 21, "Minute": 30}
    if shutil.which("plutil"):
        f = tmp_path / "s.plist"
        f.write_bytes(raw)
        subprocess.run(["plutil", "-lint", str(f)], check=True, capture_output=True)


def test_systemd_units(tmp_path: Path) -> None:
    svc = render_service(
        "ariel",
        "/home/ariel/.local/bin/bn-backup",
        Path("/home/ariel/.config/bn-backup/config.yml"),
    )
    assert "User=ariel\n" in svc
    assert (
        "ExecStart=/home/ariel/.local/bin/bn-backup -c /home/ariel/.config/bn-backup/config.yml run\n"
        in svc
    )
    timer = render_timer("sun", 2, 0)
    assert "OnCalendar=Sun *-*-* 02:00:00\n" in timer
    assert "Persistent=true\n" in timer
    assert "OnCalendar=*-*-* 21:30:00\n" in render_timer(None, 21, 30)
    if shutil.which("systemd-analyze"):
        (tmp_path / "bn-backup-schedule.timer").write_text(timer)
        (tmp_path / "bn-backup-schedule.service").write_text(svc)
        subprocess.run(
            ["systemd-analyze", "verify", str(tmp_path / "bn-backup-schedule.timer")],
            check=False,
        )


def test_install_without_sudo_prints_the_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "setup_logging", lambda verbose, log_file: None)
    assert cli.main(["schedule", "install", "--weekly", "sun", "--at", "02:00"]) == 1
    out = capsys.readouterr().out
    assert 'sudo "$(command -v bn-backup)" schedule install --weekly sun --at 02:00' in out
