# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""The board and the hosts commands (CLAUDE.md §6.5, §6.6, D-34, D-35, D-45, D-49)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import config_data
from fakes import FakeFleet, FakeHost, FakeOperator, FakeVolumes, make_env, standard_fleet

from bn_backup import hosts
from bn_backup.config import ConfigError, load_config
from bn_backup.config_edit import add_host
from bn_backup.keys import BEGIN
from bn_backup.state import HostRecord, MacAddress, load_host, run_lock, save_host
from bn_backup.status import evaluate_rows, server_checks


def tree(root: Path) -> list[tuple[str, int]]:
    return sorted((str(p.relative_to(root)), p.stat().st_mtime_ns) for p in root.rglob("*"))


def row(rows, host):  # type: ignore[no-untyped-def]
    return next(r for r in rows if r.host == host)


# --------------------------------------------------------------------------- server


def test_server_checks_green(tmp_path: Path) -> None:
    env = make_env(tmp_path, standard_fleet(), platform="darwin")
    rep = server_checks(env, write_test=True)
    assert rep.ok, [c for c in rep.checks if not c.ok]
    names = [c.name for c in rep.checks]
    assert names == [
        "config",
        "volume",
        "apfs_case_sensitive",
        "ownership",
        "volume_writable",
        "free_space",
        "rrsync",
        "promotion",
        "lock",
    ]


def test_server_checks_catch_problems(tmp_path: Path) -> None:
    env = make_env(tmp_path, standard_fleet(), platform="darwin")
    env.volumes = FakeVolumes(
        {
            "FilesystemType": "apfs",
            "FilesystemUserVisibleName": "APFS",
            "GlobalPermissionsEnabled": False,
        }
    )
    env.paths.state.mkdir(parents=True)
    env.paths.promotion_json.write_text("{}")
    rep = server_checks(env, write_test=False)
    bad = {c.name for c in rep.checks if c.ok is False}
    assert bad == {"apfs_case_sensitive", "ownership", "promotion"}


def test_missing_volume(tmp_path: Path) -> None:
    env = make_env(tmp_path, standard_fleet(), platform="linux")
    env.cfg.server.backup_directory.rmdir()
    rep = server_checks(env, write_test=True)
    first = rep.first_failure()
    assert first is not None and first.name == "volume"
    assert "connected" in first.detail
    # Linux skips the APFS checks.
    assert "apfs_case_sensitive" not in [c.name for c in rep.checks]


def test_lock_and_abort_marker_shown(tmp_path: Path) -> None:
    env = make_env(tmp_path, standard_fleet())
    env.operator_paths.abort_marker.parent.mkdir(parents=True, exist_ok=True)
    env.operator_paths.abort_marker.write_text('{"run_id": "20261110-213000"}')
    with run_lock(env.operator_paths.lock, "run"):
        rep = server_checks(env, write_test=False)
    assert next(c for c in rep.checks if c.name == "lock").ok is False
    assert any("clean-up pending from aborted run 20261110-213000" in n for n in rep.notes)


def test_old_rsync_behind_rrsync_is_red(tmp_path: Path) -> None:
    from fakes import fake_rsync

    env = make_env(tmp_path, standard_fleet())
    old = fake_rsync(tmp_path / "old-rsync", "3.1.3")
    env.operator_paths.rrsync.write_text(f"RSYNC = '{old}'\n")
    rep = server_checks(env, write_test=False)
    assert next(c for c in rep.checks if c.name == "rrsync").ok is False


# --------------------------------------------------------------------------- rows


def test_all_rows_green_and_status_writes_nothing(tmp_path: Path) -> None:
    env = make_env(tmp_path, standard_fleet())
    before = tree(tmp_path)
    rows = evaluate_rows(env, env.cfg.user_hosts(), wake=True, gate=False)
    assert [(r.host, r.user, r.ok) for r in rows] == [
        ("athena", "sofia", True),
        ("galactica", "ariel", True),
    ]
    assert tree(tmp_path) == before, "status is read-only (D-49)"
    assert not env.operator_paths.lock.exists()


def test_probe_job_has_the_users_modules(tmp_path: Path) -> None:
    fleet = standard_fleet()
    env = make_env(tmp_path, fleet)
    evaluate_rows(env, [("athena", "sofia")], wake=False, gate=False)
    job = fleet.hosts["athena"].jobs[-1]
    assert job["kind"] == "probe"
    assert [m["name"] for m in job["modules"]] == ["sofia-athena", "sofia-documents"]
    assert job["server"] == {"host": "server.home.lan", "port": 22, "user": "ariel"}


def test_expect_nonempty_follows_current(tmp_path: Path) -> None:
    fleet = standard_fleet()
    env = make_env(tmp_path, fleet)
    data = env.paths.current / "sofia-documents" / "Documents"
    data.mkdir(parents=True)
    (data / "letter.txt").write_text("x")
    evaluate_rows(env, [("athena", "sofia")], wake=False, gate=False)
    mods = {m["name"]: m for m in fleet.hosts["athena"].jobs[-1]["modules"]}
    assert mods["sofia-documents"]["expect_nonempty"] is True


@pytest.mark.parametrize(
    ("change", "check", "words"),
    [
        ({"resolves": False}, "dns", "does not resolve"),
        ({"up": False, "macs": []}, "reachable", "unreachable"),
        ({"installed": False}, "agent", "hosts bootstrap"),
        ({"protocol": (2, 3)}, "agent", "agent upgrade"),
        ({"users": set()}, "user", "hosts configure"),
        ({"running": {"sofia"}}, "idle", "still running"),
        ({"fda": "denied"}, "probe", "Full Disk Access on athena"),
        (
            {"probe_errors": {"sofia-documents": ("drive_missing", "PhotoArchive")}},
            "probe",
            "drive_missing",
        ),
        ({"server_reachable": False}, "probe", "Allow full disk access for remote users"),
    ],
)
def test_red_rows(tmp_path: Path, change: dict, check: str, words: str) -> None:  # type: ignore[type-arg]
    fleet = FakeFleet(FakeHost("galactica"), FakeHost("athena", **change))
    env = make_env(tmp_path, fleet)
    rows = evaluate_rows(env, env.cfg.user_hosts(), wake=True, gate=False)
    r = row(rows, "athena")
    assert not r.ok
    assert r.reason.startswith(f"{check}:"), r.reason
    assert words in r.reason
    later = [c for c in r.checks if c.ok is None]
    assert all(c.detail == "–" for c in later)
    assert row(rows, "galactica").ok


def test_user_not_set_up_is_not_configured_by_status(tmp_path: Path) -> None:
    fleet = FakeFleet(FakeHost("galactica"), FakeHost("athena", users=set()))
    env = make_env(tmp_path, fleet)
    evaluate_rows(env, env.cfg.user_hosts(), wake=False, gate=False)
    assert not any(c.startswith("user-add") for c in fleet.hosts["athena"].calls)


def test_wake_on_lan(tmp_path: Path) -> None:
    fleet = FakeFleet(FakeHost("galactica"), FakeHost("athena", up=False, wakes=True))
    env = make_env(tmp_path, fleet)
    save_host(
        env.paths,
        HostRecord(
            host="athena",
            address="athena.home.lan",
            admin_user="ariel",
            mac_addresses=[MacAddress(iface="en0", mac="aa:bb:cc:dd:ee:01")],
        ),
    )
    rows = evaluate_rows(env, env.cfg.user_hosts(), wake=True, gate=False)
    assert row(rows, "athena").ok
    assert fleet.woken == ["aa:bb:cc:dd:ee:01"]
    # --no-wake: stays red.
    fleet.hosts["athena"].up = False
    rows = evaluate_rows(env, env.cfg.user_hosts(), wake=False, gate=False)
    assert row(rows, "athena").reason.startswith("reachable")


def test_gate_stops_leftover_job(tmp_path: Path) -> None:
    fleet = FakeFleet(FakeHost("galactica"), FakeHost("athena", running={"sofia"}))
    env = make_env(tmp_path, fleet)
    rows = evaluate_rows(env, env.cfg.user_hosts(), wake=False, gate=True)
    assert row(rows, "athena").ok
    assert "stop sofia" in fleet.hosts["athena"].calls
    # A job that will not stop stays red.
    fleet.hosts["athena"].running = {"sofia"}
    fleet.hosts["athena"].stuck = {"sofia"}
    rows = evaluate_rows(env, env.cfg.user_hosts(), wake=False, gate=True)
    assert "will not stop" in row(rows, "athena").reason


def test_probe_that_never_reports_is_red(tmp_path: Path) -> None:
    fleet = FakeFleet(FakeHost("galactica"), FakeHost("athena", hang_probes=True))
    env = make_env(tmp_path, fleet)
    rows = evaluate_rows(env, [("athena", "sofia")], wake=False, gate=False)
    assert "stopped without reporting" in rows[0].reason


# --------------------------------------------------------------------------- hosts


def fresh_fleet(os_name: str = "linux") -> FakeFleet:
    return FakeFleet(
        FakeHost("galactica", os=os_name, installed=False, configured=False, users=set()),
        FakeHost("athena", installed=False, configured=False, users=set()),
    )


def test_bootstrap_linux_host(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fleet = fresh_fleet()
    env = make_env(tmp_path, fleet)
    pkg = tmp_path / "bn-backup-agent_2.0.0_amd64.deb"
    pkg.write_bytes(b"deb")
    assert hosts.bootstrap(env, "galactica", override=pkg)
    op: FakeOperator = env.operator_conn  # type: ignore[assignment]
    cmds = [c for h, c in op.commands if h == "galactica"]
    assert cmds[0].startswith("uname")
    assert "id -u ariel" in cmds
    assert any("sudo apt-get install -y /tmp/bn-backup-agent_2.0.0_amd64.deb" in c for c in cmds)
    setup = next(c for c in cmds if " ctl setup " in c)
    assert "--server-known-hosts-line 'server.home.lan ssh-ed25519 AAAAhostkey'" in setup
    assert "--control-key 'ssh-ed25519 AAAAC3NzaCserver bn-backup-server'" in setup
    assert setup.startswith("sudo /usr/bin/bn-backup-agent ctl setup")
    rec = load_host(env.paths, "galactica")
    assert rec is not None and rec.bootstrapped and rec.os == "linux"
    assert rec.mac_addresses[0].mac == "aa:bb:cc:dd:ee:01"
    assert env.paths.key_file("galactica", "ariel").exists()
    assert env.paths.staging_user("galactica", "ariel").is_dir()
    auth = env.operator_paths.authorized_keys.read_text()
    assert BEGIN in auth and "galactica/ariel" in auth
    # Re-running skips the install.
    op.commands.clear()
    assert hosts.bootstrap(env, "galactica", override=pkg)
    assert not any("apt-get" in c for _, c in op.commands)


def test_bootstrap_macos_waits_for_full_disk_access(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fleet = fresh_fleet("darwin")
    fleet.hosts["galactica"].fda = "denied"
    env = make_env(tmp_path, fleet)
    pkg = tmp_path / "bn-backup-agent-2.0.0.pkg"
    pkg.write_bytes(b"pkg")
    calls = {"n": 0}
    original_sleep = env.clock.sleep

    def sleep(s: float) -> None:
        original_sleep(s)
        calls["n"] += 1
        if calls["n"] == 3:  # someone ticks the box at the Mac
            fleet.hosts["galactica"].fda = "granted"

    env.clock.sleep = sleep  # type: ignore[method-assign]
    assert hosts.bootstrap(env, "galactica", override=pkg)
    out = capsys.readouterr().out
    assert "Go to galactica and switch on BNBackupAgent" in out
    assert "open-fda-settings" in fleet.hosts["galactica"].calls
    op: FakeOperator = env.operator_conn  # type: ignore[assignment]
    assert ("galactica", "/Users/Shared/bn-backup-agent-2.0.0.pkg") in op.copies


def test_bootstrap_missing_account(tmp_path: Path) -> None:
    fleet = fresh_fleet()
    fleet.hosts["galactica"].accounts = {"someone"}
    env = make_env(tmp_path, fleet)
    with pytest.raises(hosts.HostError, match="no account 'ariel'"):
        hosts.bootstrap(env, "galactica", override=tmp_path)


def test_configure_adds_new_user(tmp_path: Path) -> None:
    fleet = standard_fleet()
    fleet.hosts["athena"].users = set()
    env = make_env(tmp_path, fleet)
    assert hosts.configure(env, "athena", say=lambda s: None) == ["sofia"]
    assert "sofia" in fleet.hosts["athena"].users
    assert hosts.configure(env, "athena", say=lambda s: None) == []
    rec = load_host(env.paths, "athena")
    assert rec is not None and rec.address == "athena.home.lan"


def test_forget_and_remove(tmp_path: Path) -> None:
    fleet = standard_fleet()
    data = config_data()
    del data["hosts"]["athena"]
    del data["modules"]["sofia-documents"]
    env = make_env(tmp_path, fleet, data)
    save_host(
        env.paths,
        HostRecord(host="athena", address="athena.home.lan", admin_user="ariel", os="linux"),
    )
    from bn_backup.keys import store_key

    store_key(env.paths, "athena", "sofia", "ssh-ed25519 AAAAx bn-backup-agent sofia@athena")
    # Refusals.
    with pytest.raises(hosts.HostError, match="still in the config"):
        hosts.remove(env, "galactica")
    with pytest.raises(hosts.HostError, match="unknown host"):
        hosts.remove(env, "columbia")
    fleet.hosts["athena"].up = False
    with pytest.raises(hosts.HostError, match="hosts forget athena"):
        hosts.remove(env, "athena")
    with (
        run_lock(env.operator_paths.lock, "run"),
        pytest.raises(hosts.HostError, match="in progress"),
    ):
        hosts.remove(env, "athena")
    # The real thing.
    fleet.hosts["athena"].up = True
    hosts.remove(env, "athena", say=lambda s: None)
    op: FakeOperator = env.operator_conn  # type: ignore[assignment]
    assert ("athena", "sudo /usr/bin/bn-backup-agent ctl uninstall") in op.commands
    assert ("athena", "sudo apt-get remove -y bn-backup-agent") in op.commands
    assert load_host(env.paths, "athena") is None
    assert not env.paths.key_file("athena", "sofia").exists()


def test_add_host_keeps_comments_and_rolls_back(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yml"
    original = (
        "# my backup\nversion: 2\nserver:\n  backup_directory: /Volumes/Backup/b  # drive\n"
        "  ssh_host: server.home.lan\n  receive_user: ariel\nhosts:\n"
        "  galactica:  # the studio Mac\n    address: galactica.home.lan\n    admin_user: ariel\n"
        "modules:\n  photos: {host: galactica, user: ariel, src_path: /Volumes/Photos/P}\n"
    )
    cfg.write_text(original)
    cfg.chmod(0o600)
    add_host(cfg, "columbia", "columbia.home.lan", "ariel", 2222)
    text = cfg.read_text()
    assert "# my backup" in text and "# the studio Mac" in text and "# drive" in text
    loaded = load_config(cfg)
    assert list(loaded.config.hosts) == ["galactica", "columbia"]
    assert loaded.config.hosts["columbia"].ssh_port == 2222
    assert oct(cfg.stat().st_mode & 0o777) == "0o600"
    # An invalid result restores the original bytes.
    before = cfg.read_bytes()
    with pytest.raises(ConfigError):
        add_host(cfg, "bad", "bare-name", "ariel", 22)
    assert cfg.read_bytes() == before
