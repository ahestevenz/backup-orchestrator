# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Command line: account rules and the config commands (CLAUDE.md §6.1, §6.18)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FIXTURES, config_data, write_config

from bn_backup import cli


@pytest.fixture(autouse=True)
def _no_log_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_logging", lambda verbose, log_file: None)


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "bn-backup 2.0.0" in capsys.readouterr().out


def test_refuses_root(
    monkeypatch: pytest.MonkeyPatch, config_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(cli, "current_user", lambda: "root")
    assert cli.main(["-c", str(config_file), "config", "validate"]) == 1
    assert "without sudo" in capsys.readouterr().err


def test_refuses_other_user(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = write_config(tmp_path / "c.yml", config_data(server={"receive_user": "someone-else"}))
    assert cli.main(["-c", str(cfg), "runs", "list"]) == 1
    assert "run bn-backup as someone-else" in capsys.readouterr().err


def test_config_commands_need_no_particular_user(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = write_config(tmp_path / "c.yml", config_data(server={"receive_user": "someone-else"}))
    assert cli.main(["-c", str(cfg), "config", "validate"]) == 0
    assert "valid" in capsys.readouterr().out


def test_config_validate_prints_every_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = config_data(settings={"snapshot_keep": 0, "mode": "copy"})
    cfg = write_config(tmp_path / "c.yml", data)
    assert cli.main(["-c", str(cfg), "config", "validate"]) == 1
    err = capsys.readouterr().err
    assert "settings.snapshot_keep" in err
    assert "settings.mode" in err


def test_config_migrate_to_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "new.yml"
    assert cli.main(["config", "migrate", str(FIXTURES / "v1_readme.yml"), "-o", str(out)]) == 0
    assert out.stat().st_mode & 0o777 == 0o600
    assert "TODO verify" in out.read_text()
    assert "Check these guesses" in capsys.readouterr().err
    # Never overwrites.
    assert cli.main(["config", "migrate", str(FIXTURES / "v1_readme.yml"), "-o", str(out)]) == 1


def test_config_migrate_refuses_v2(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["config", "migrate", str(config_file)]) == 1
    assert "already at version 2" in capsys.readouterr().err


def test_config_show_json(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["-c", str(config_file), "config", "show", "--json"]) == 0
    assert '"snapshot_keep": 8' in capsys.readouterr().out
