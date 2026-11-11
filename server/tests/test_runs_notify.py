# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Notifications and the runs commands (CLAUDE.md §6.14, §6.16)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from conftest import config_data, write_config

from bn_backup import cli
from bn_backup.config import EmailConfig, SignalConfig
from bn_backup.notify import email, signal
from bn_backup.paths import BackupPaths
from bn_backup.state import ModuleState, RunState, save_run, write_history


class TinySMTP:
    """Just enough SMTP to receive one message (no TLS)."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.data = ""
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self) -> None:
        conn, _ = self.sock.accept()
        f = conn.makefile("rwb")

        def say(line: str) -> None:
            f.write((line + "\r\n").encode())
            f.flush()

        say("220 tiny ready")
        in_data = False
        while True:
            line = f.readline().decode().rstrip("\r\n")
            if in_data:
                if line == ".":
                    in_data = False
                    say("250 queued")
                else:
                    self.data += line + "\n"
                continue
            cmd = line.split(" ")[0].upper()
            if cmd in ("EHLO", "HELO"):
                say("250 tiny")
            elif cmd == "DATA":
                in_data = True
                say("354 go ahead")
            elif cmd == "QUIT":
                say("221 bye")
                break
            else:
                say("250 ok")
        conn.close()


def test_email_reaches_a_local_smtp_server(tmp_path: Path) -> None:
    server = TinySMTP()
    pw = tmp_path / "pw"
    pw.write_text("secret\n")
    cfg = EmailConfig.model_validate(
        {
            "enabled": False,
            "smtp_host": "127.0.0.1",
            "smtp_port": server.port,
            "starttls": False,
            "from": "you@example.com",
            "to": ["you@example.com"],
            "password_file": str(pw),
        }
    )
    email.send(cfg, "[bn-backup] COMPLETE — 4/4 modules", "the report")
    server.thread.join(timeout=5)
    assert "Subject: [bn-backup] COMPLETE" in server.data
    assert "the report" in server.data


def test_signal_command_lines() -> None:
    cfg = SignalConfig(
        enabled=True,
        signal_cli=Path("/opt/homebrew/bin/signal-cli"),
        account="+61400000000",
        note_to_self=True,
        recipients=["+61400000001"],
    )
    assert signal.commands(cfg, "hi") == [
        [
            "/opt/homebrew/bin/signal-cli",
            "-a",
            "+61400000000",
            "send",
            "--note-to-self",
            "-m",
            "hi",
        ],
        ["/opt/homebrew/bin/signal-cli", "-a", "+61400000000", "send", "-m", "hi", "+61400000001"],
    ]


def test_notify_test_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "setup_logging", lambda verbose, log_file: None)
    monkeypatch.setattr(cli, "current_user", lambda: "ariel")
    monkeypatch.setattr(cli, "operator_home", lambda user: tmp_path / "home")
    server = TinySMTP()
    pw = tmp_path / "pw"
    pw.write_text("x")
    os.chmod(pw, 0o600)
    data = config_data(
        notifications={
            "email": {
                "enabled": True,
                "smtp_host": "127.0.0.1",
                "smtp_port": server.port,
                "starttls": False,
                "from": "you@example.com",
                "to": ["you@example.com"],
                "password_file": str(pw),
            }
        }
    )
    cfg = write_config(tmp_path / "c.yml", data)
    assert cli.main(["-c", str(cfg), "notify", "test"]) == 0
    assert "email: sent" in capsys.readouterr().out
    server.thread.join(timeout=5)
    assert "bn-backup test message" in server.data


# --------------------------------------------------------------------------- runs


def runs_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, BackupPaths]:
    monkeypatch.setattr(cli, "setup_logging", lambda verbose, log_file: None)
    monkeypatch.setattr(cli, "current_user", lambda: "ariel")
    monkeypatch.setattr(cli, "operator_home", lambda user: tmp_path / "home")
    backup = tmp_path / "b"
    paths = BackupPaths(backup)
    cfg = write_config(tmp_path / "c.yml", config_data(server={"backup_directory": str(backup)}))
    mods = {
        "docs": ModuleState(
            host="athena", user="sofia", type="path", status="green", files_transferred=3
        ),
        "photos": ModuleState(
            host="galactica",
            user="ariel",
            type="path",
            status="red",
            error_kind="tcc",
            reason="Operation not permitted",
        ),
    }
    old = RunState(
        run_id="20261101-210000",
        status="COMPLETE",
        first_attempt_at="2026-11-01T10:00:00Z",
        last_attempt_at="2026-11-01T10:00:00Z",
        completed_at="2026-11-01T11:00:00Z",
        modules={"docs": mods["docs"]},
    )
    cur = RunState(
        run_id="20261110-213000",
        status="UNFINISHED",
        first_attempt_at="2026-11-10T10:30:00Z",
        last_attempt_at="2026-11-10T10:30:00Z",
        last_attempt_finished_at="2026-11-05T11:00:00Z",  # long past the 30 h limit
        attempts=2,
        modules=mods,
    )
    write_history(paths, old)
    save_run(paths, cur)
    return cfg, paths


def test_runs_list_and_show(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg, _ = runs_world(tmp_path, monkeypatch)
    assert cli.main(["-c", str(cfg), "runs", "list"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1].startswith("20261110-213000")  # newest first
    assert "EXPIRED" in out[1], "an UNFINISHED run past its time limit shows as EXPIRED"
    assert "1/2" in out[1]
    assert out[2].startswith("20261101-210000") and "COMPLETE" in out[2]
    assert cli.main(["-c", str(cfg), "runs", "show", "20261110-213000"]) == 0
    shown = capsys.readouterr().out
    assert "photos (galactica/ariel): red" in shown and "tcc: Operation not permitted" in shown
    assert cli.main(["-c", str(cfg), "runs", "show", "nope"]) == 1


def test_runs_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg, _ = runs_world(tmp_path, monkeypatch)
    assert cli.main(["-c", str(cfg), "runs", "cancel"]) == 1
    assert "no run in progress" in capsys.readouterr().out
    lock = tmp_path / "home" / ".local" / "state" / "bn-backup" / "lock"
    holder = textwrap.dedent(
        f"""
        import signal, sys, time
        from pathlib import Path
        from bn_backup.state import run_lock
        signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
        with run_lock(Path({str(lock)!r}), "run"):
            print("locked", flush=True)
            time.sleep(60)
        """
    )
    proc = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None and proc.stdout.readline().strip() == "locked"
    start = time.monotonic()
    assert cli.main(["-c", str(cfg), "runs", "cancel"]) == 0
    assert "cancelled; run 20261110-213000 is UNFINISHED" in capsys.readouterr().out
    assert proc.wait(timeout=10) == 0
    assert time.monotonic() - start < 30


def test_runs_list_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    cfg, _ = runs_world(tmp_path, monkeypatch)
    assert cli.main(["-c", str(cfg), "runs", "list", "--json", "--limit", "1"]) == 0
    data: list[dict[str, Any]] = json.loads(capsys.readouterr().out)
    assert len(data) == 1 and data[0]["run_id"] == "20261110-213000"
