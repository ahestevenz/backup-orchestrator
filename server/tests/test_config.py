# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Configuration: validation rules, migrate and show (CLAUDE.md §4, §8)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import FIXTURES, config_data, write_config

from bn_backup.config import (
    AlreadyCurrentError,
    ConfigError,
    load_config,
    migrate,
    parse_yaml,
    show,
    validate_data,
)


def errors_for(data: dict[str, Any], home: Path | None = None) -> list[str]:
    with pytest.raises(ConfigError) as exc:
        validate_data(data, home)
    return exc.value.errors


def test_base_config_is_valid() -> None:
    cfg = validate_data(config_data())
    assert cfg.settings.mode == "mirror"
    assert cfg.settings.job_timeout_minutes == 0
    assert cfg.settings.io_timeout_seconds == 600
    assert cfg.hosts["galactica"].ssh_port == 22


@pytest.mark.parametrize(
    "address",
    ["galactica.home.lan", "galactica.local", "192.168.1.20", "fd00::20", "galactica.home.lan."],
)
def test_valid_addresses(address: str) -> None:
    data = config_data()
    data["hosts"]["galactica"]["address"] = address
    validate_data(data)


@pytest.mark.parametrize("address", ["galactica", "bad_name.lan", "-x.lan", "a..b"])
def test_invalid_addresses(address: str) -> None:
    data = config_data()
    data["hosts"]["galactica"]["address"] = address
    errs = errors_for(data)
    assert any(e.startswith("hosts.galactica.address") for e in errs)


def test_bare_ssh_host_refused() -> None:
    errs = errors_for(config_data(server={"ssh_host": "macmini"}))
    assert any("bare host name" in e and "D-18" in e for e in errs)


def test_version_required_and_v1_hint() -> None:
    data = config_data()
    del data["version"]
    assert "config migrate" in errors_for(data)[0]
    data["version"] = 1
    assert any(e.startswith("version") for e in errors_for(data))


def test_unknown_keys_are_errors() -> None:
    errs = errors_for(config_data(settings={"moed": "mirror"}))
    assert errs == ["settings.moed: unknown key (check the spelling)"]


def test_all_errors_are_reported_together() -> None:
    data = config_data(settings={"snapshot_keep": 0, "io_timeout_seconds": 10})
    data["modules"]["sofia-documents"]["src_path"] = "relative/path"
    errs = errors_for(data)
    assert len(errs) == 3


@pytest.mark.parametrize(
    ("src", "message"),
    [
        ("Users/sofia", "absolute"),
        ("/", "must not be /"),
        ("/Users/sofia/Documents/", "must not end with /"),
    ],
)
def test_src_path_rules(src: str, message: str) -> None:
    data = config_data()
    data["modules"]["sofia-documents"]["src_path"] = src
    assert any(message in e for e in errors_for(data))


def test_module_host_must_exist() -> None:
    data = config_data()
    data["modules"]["sofia-documents"]["host"] = "columbia"
    assert any("not listed under hosts" in e for e in errors_for(data))


@pytest.mark.parametrize("name", ["bad name", "a.b", "x" * 65, ".hidden"])
def test_module_name_rule(name: str) -> None:
    data = config_data()
    data["modules"][name] = data["modules"].pop("sofia-documents")
    assert errors_for(data)


@pytest.mark.parametrize("key", ["Galactica", "-x", "a_b", "a" * 64])
def test_host_key_rule(key: str) -> None:
    data = config_data()
    data["hosts"][key] = data["hosts"].pop("athena")
    data["modules"]["sofia-documents"]["host"] = key
    assert errors_for(data)


def test_module_name_clashing_with_host_config_module() -> None:
    data = config_data()
    data["modules"]["sofia-athena"] = {"host": "galactica", "user": "x", "src_path": "/x"}
    errs = errors_for(data)
    assert any("clashes with the generated host-config module" in e for e in errs)
    # Allowed when host-config backup is off.
    data["settings"] = {"host_config_backup": False}
    validate_data(data)


def test_generated_host_config_names_must_not_collide() -> None:
    data = config_data(
        hosts={
            "c": {"address": "c.home.lan", "admin_user": "ariel"},
            "b-c": {"address": "bc.home.lan", "admin_user": "ariel"},
        }
    )
    data["modules"] = {
        "one": {"host": "c", "user": "a-b", "src_path": "/x"},
        "two": {"host": "b-c", "user": "a", "src_path": "/y"},
    }
    errs = errors_for(data)
    assert any("would both get the host-config module 'a-b-c'" in e for e in errs)


def test_duplicate_module_names_refused() -> None:
    text = """
version: 2
modules:
  same: {host: a, user: u, src_path: /x}
  same: {host: a, user: u, src_path: /y}
"""
    with pytest.raises(ConfigError) as exc:
        parse_yaml(text)
    assert "duplicate key 'same'" in exc.value.errors[0]


def test_tilde_expands_against_operator_home(tmp_path: Path) -> None:
    pw = tmp_path / "pw"
    pw.write_text("secret")
    os.chmod(pw, 0o600)
    data = config_data(
        server={"backup_directory": "~/backup"},
        notifications={
            "email": {
                "enabled": True,
                "smtp_host": "smtp.example.com",
                "from": "you@example.com",
                "to": ["you@example.com"],
                "password_file": "~/pw",
            }
        },
    )
    cfg = validate_data(data, home=tmp_path)
    assert cfg.server.backup_directory == tmp_path / "backup"
    assert cfg.notifications.email.password_file == pw


def test_email_password_file_mode(tmp_path: Path) -> None:
    pw = tmp_path / "pw"
    pw.write_text("secret")
    os.chmod(pw, 0o644)
    email = {
        "enabled": True,
        "smtp_host": "smtp.example.com",
        "from": "a@example.com",
        "to": ["a@example.com"],
        "password_file": str(pw),
    }
    errs = errors_for(config_data(notifications={"email": email}))
    assert any("mode 0600" in e for e in errs)
    email["password_file"] = str(tmp_path / "missing")
    errs = errors_for(config_data(notifications={"email": email}))
    assert any("set-smtp-password" in e for e in errs)


def test_signal_rules() -> None:
    sig = {"enabled": True, "account": "0400", "note_to_self": True}
    assert errors_for(config_data(notifications={"signal": sig}))
    sig = {"enabled": True, "account": "+61400000000", "note_to_self": False}
    assert any("recipient" in e for e in errors_for(config_data(notifications={"signal": sig})))
    sig["recipients"] = ["+61400000001"]
    validate_data(config_data(notifications={"signal": sig}))


def test_disabled_channels_need_nothing() -> None:
    cfg = validate_data(config_data(notifications={"email": {"enabled": False}}))
    assert cfg.notifications.signal.enabled is False


def test_module_set_includes_host_config_modules() -> None:
    cfg = validate_data(config_data())
    ms = cfg.module_set()
    assert set(ms) == {
        "ariel-photo-archive",
        "sofia-documents",
        "ariel-galactica",
        "sofia-athena",
    }
    assert ms["sofia-athena"].type == "host-config"
    assert ms["sofia-documents"].basename == "Documents"


def test_load_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "nope.yml")
    assert "server init" in exc.value.errors[0]


def test_load_config_keeps_raw_bytes(config_file: Path) -> None:
    loaded = load_config(config_file)
    assert loaded.raw == config_file.read_bytes()
    assert len(loaded.sha256) == 64


def test_show_fills_defaults() -> None:
    cfg = validate_data(config_data())
    out = yaml.safe_load(show(cfg, as_json=False))
    assert out["settings"]["snapshot_keep"] == 8
    assert out["settings"]["wake"] == {"enabled": True, "wait_seconds": 180}
    assert out["notifications"]["email"]["from"] == ""
    as_json = json.loads(show(cfg, as_json=True))
    assert as_json == out


# --------------------------------------------------------------------------- migrate


def test_migrate_v1_readme_example() -> None:
    text = (FIXTURES / "v1_readme.yml").read_text()
    new, guesses = migrate(text, "ariel")
    data = parse_yaml(new)
    assert data["version"] == 2
    assert data["server"]["backup_directory"] == "/path/to/backup"
    assert data["settings"]["resume_backup"] is True
    assert set(data["hosts"]) == {"galactica", "columbia"}
    assert data["hosts"]["galactica"]["admin_user"] == "ahestevenz"
    assert data["modules"]["dir3-ahe"] == {
        "host": "columbia",
        "user": "ahestevenz",
        "src_path": "/home/ahestevenz/dir3",
    }
    assert new.count("# TODO verify") == 2 + 1 + 2 * 2
    assert any("ssh_host" in g for g in guesses)
    # Not valid until the placeholders are edited, by design.
    with pytest.raises(ConfigError):
        validate_data(data)
    data["server"]["ssh_host"] = "macmini.home.lan"
    for h in data["hosts"].values():
        h["address"] = h["address"].replace("CHANGE-ME.", "home.")
    validate_data(data)


def test_migrate_refuses_v2() -> None:
    with pytest.raises(AlreadyCurrentError):
        migrate("version: 2\n", "ariel")


def test_migrate_quotes_odd_values() -> None:
    text = """
settings: {backup_directory: "/path with space/b", resume_backup: false}
modules:
  m1: {host: h1, user: "yes", src_path: "/a: b"}
"""
    new, _ = migrate(text, "ariel")
    data = parse_yaml(new)
    assert data["server"]["backup_directory"] == "/path with space/b"
    assert data["settings"]["resume_backup"] is False
    assert data["modules"]["m1"]["user"] == "yes"
    assert data["modules"]["m1"]["src_path"] == "/a: b"


def test_template_is_valid(tmp_path: Path) -> None:
    from bn_backup.config import template

    path = write_config(tmp_path / "c.yml", {})
    path.write_text(template("ariel"))
    loaded = load_config(path, home=tmp_path)
    assert loaded.config.server.receive_user == "ariel"
