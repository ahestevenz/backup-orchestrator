# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""The run engine (CLAUDE.md §6.7-§6.9, §6.13, §6.14, §6.17; §8)."""

from __future__ import annotations

import json
import os
import shutil
import signal
from pathlib import Path
from typing import Any

import pytest
from conftest import config_data
from fakes import FakeFleet, FakeHost, FakeNotifier, make_env, pushing

from bn_backup import promotion
from bn_backup.env import Env
from bn_backup.fsutil import atomic_write_json
from bn_backup.runner import Runner, plan_run, prepare_staging
from bn_backup.state import LastComplete, load_history, load_last_complete, load_run, save_run


def fleet(**athena: Any) -> FakeFleet:
    return FakeFleet(FakeHost("galactica"), FakeHost("athena", **athena))


def setup(tmp_path: Path, f: FakeFleet | None = None, data: dict[str, Any] | None = None) -> Env:
    f = f or fleet()
    env = make_env(tmp_path, f, data)
    for h in f.hosts.values():
        if h.on_backup is None:
            h.on_backup = pushing(env.paths)  # type: ignore[assignment]
    from bn_backup.server_init import create_layout

    create_layout(env.paths, env.cfg.user_hosts())
    return env


def run(env: Env, notifier: FakeNotifier | None = None, **kw: Any) -> tuple[int, FakeNotifier]:
    n = notifier or FakeNotifier()
    opts = {"dry_run": False, "fresh": False, "wake": False, **kw}
    env.clock.advance(minutes=1)  # type: ignore[attr-defined]
    code = Runner(env, n, say=lambda *a: None, **opts).run()
    return code, n


def files(root: Path) -> dict[str, str]:
    """Every file under root with its content (for comparing trees)."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = p.read_text(errors="replace")
    return out


def tree(root: Path) -> list[tuple[str, int]]:
    """Every entry with its mtime. `.state/` itself is left out: the run's drive
    write test (D-54) creates and deletes a file there, changing only its mtime."""
    return sorted(
        (str(p.relative_to(root)), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p != root / ".state"
    )


# --------------------------------------------------------------------------- outcomes


def test_all_green_is_complete(tmp_path: Path) -> None:
    env = setup(tmp_path)
    code, n = run(env)
    assert code == 0
    r = load_run(env.paths)
    assert r is not None and r.status == "COMPLETE" and r.completed_at
    cur = env.paths.current
    assert (cur / "sofia-documents" / "Documents" / "photo.NEF").exists()
    assert (cur / "ariel-photo-archive" / "Photos" / "photo.NEF").exists()
    assert (cur / "sofia-athena" / "hosts").exists()
    assert (cur / "config.yml").read_bytes() == env.loaded.raw
    assert "COMPLETE" in (cur / "backup_report.log").read_text()
    assert load_last_complete(env.paths) is not None
    assert [h.status for h in load_history(env.paths)] == ["COMPLETE"]
    assert n.sent[0][0] == "[bn-backup] COMPLETE — 4/4 modules"
    # Staging was reset and the per-user folders recreated (§6.9 invariant).
    assert sorted(p.name for p in env.paths.staging.iterdir()) == ["athena", "galactica"]
    assert not any(env.paths.staging_user("athena", "sofia").iterdir())
    assert not env.paths.promotion_json.exists()


def test_one_red_is_unfinished_and_retry_redoes_only_red(tmp_path: Path) -> None:
    f = fleet(module_errors={"sofia-documents": ("tcc", "Operation not permitted")})
    env = setup(tmp_path, f)
    code, n = run(env)
    assert code == 2
    r = load_run(env.paths)
    assert r is not None and r.status == "UNFINISHED"
    assert r.modules["sofia-documents"].status == "red"
    assert r.modules["ariel-photo-archive"].status == "green"
    assert not env.paths.current.joinpath("ariel-photo-archive").exists(), "current/ unchanged"
    assert n.sent[0][0] == "[bn-backup] UNFINISHED — 1 of 4 modules red"
    report = env.paths.last_report.read_text()
    assert "re-run before" in report
    assert "hint: Switch on BNBackupAgent in Full Disk Access on athena" in report
    assert (env.paths.run_logs(r.run_id) / "athena-sofia-sofia-documents.log").exists()
    # Fix it and run again: only the red module is redone.
    f.hosts["athena"].module_errors = {}
    jobs_before = len(f.hosts["galactica"].jobs)
    code, _ = run(env)
    assert code == 0
    assert len(f.hosts["galactica"].jobs) == jobs_before, "galactica was all green"
    last = f.hosts["athena"].jobs[-1]
    assert [m["name"] for m in last["modules"]] == ["sofia-documents"]
    r2 = load_run(env.paths)
    assert r2 is not None and r2.status == "COMPLETE" and r2.attempts == 2
    assert r2.run_id == r.run_id


def test_exit_code_3_when_locked(tmp_path: Path) -> None:
    from bn_backup.state import run_lock

    env = setup(tmp_path)
    with run_lock(env.operator_paths.lock, "run"):
        code, _ = run(env)
    assert code == 3


# --------------------------------------------------------------------------- planner


def test_resume_reconciles_config_changes(tmp_path: Path) -> None:
    f = fleet(module_errors={"sofia-documents": ("tcc", "x")})
    env = setup(tmp_path, f)
    run(env)
    staged = env.paths.staging_module("athena", "sofia", "sofia-documents")
    assert staged.exists()
    data = config_data()
    data["modules"]["sofia-documents"]["src_path"] = "/Users/sofia/Docs"
    env2 = make_env(tmp_path, f, data)
    env2.clock = env.clock
    plan = plan_run(env2, fresh=False)
    assert not plan.new
    assert ("athena", "sofia", "sofia-documents") in plan.staging_to_delete
    assert plan.run.modules["sofia-documents"].src_path == "/Users/sofia/Docs"
    assert plan.run.attempts == 2


def test_ttl_counts_from_end_of_last_attempt(tmp_path: Path) -> None:
    f = fleet(module_errors={"sofia-documents": ("tcc", "x")})
    env = setup(tmp_path, f)
    run(env)
    r = load_run(env.paths)
    assert r is not None
    env.clock.advance(hours=29, minutes=59)  # type: ignore[attr-defined]
    assert not plan_run(env, fresh=False).new
    env.clock.advance(minutes=1)  # type: ignore[attr-defined]
    plan = plan_run(env, fresh=False)  # exactly 30 h: expired (>=)
    assert plan.new and plan.expired is not None and plan.run.previous_expired


def test_expired_keeps_staging_and_redoes_everything(tmp_path: Path) -> None:
    f = fleet(module_errors={"sofia-documents": ("tcc", "x")})
    env = setup(tmp_path, f)
    run(env)
    staged = env.paths.staging_module("galactica", "ariel", "ariel-photo-archive")
    marker = staged / "Photos" / "photo.NEF"
    assert marker.exists()
    env.clock.advance(hours=31)  # type: ignore[attr-defined]
    f.hosts["athena"].module_errors = {}
    seen: list[bool] = []

    def check(user: str, job: dict[str, Any]) -> None:
        seen.append(marker.exists())  # the staged data is there as rsync's basis
        pushing(env.paths)(user, job)

    f.hosts["galactica"].on_backup = check  # type: ignore[assignment]
    code, n = run(env)
    assert code == 0
    assert seen == [True]
    statuses = {h.run_id: h.status for h in load_history(env.paths)}
    assert "EXPIRED" in statuses.values() and "COMPLETE" in statuses.values()
    assert "previous run was not completed within 30 h" in n.sent[-1][1]


def test_fresh_discards_staging_only_after_gate(tmp_path: Path) -> None:
    f = fleet(module_errors={"sofia-documents": ("tcc", "x")})
    env = setup(tmp_path, f)
    run(env)
    staged = env.paths.staging_module("galactica", "ariel", "ariel-photo-archive")
    assert staged.exists()
    before = load_run(env.paths)
    # A red row: --fresh changes nothing (D-57).
    f.hosts["athena"].up = False
    snapshot = tree(env.paths.root)
    code, n = run(env, fresh=True)
    assert code == 1
    assert "NOT STARTED" in n.sent[0][0]
    assert tree(env.paths.root) == snapshot
    assert load_run(env.paths) == before
    # Green rows: staging deleted, the old run EXPIRED, a new run.
    f.hosts["athena"].up = True
    f.hosts["athena"].module_errors = {}
    old_file = staged / "Photos" / "photo.NEF"
    assert old_file.exists()
    seen: list[bool] = []
    f.hosts["galactica"].on_backup = lambda u, j: seen.append(old_file.exists())  # type: ignore[assignment,func-returns-value]
    code, _ = run(env, fresh=True)
    assert seen == [False], "the staged data was deleted before the jobs ran"
    discarded = [h for h in load_history(env.paths) if h.run_id == before.run_id]  # type: ignore[union-attr]
    assert discarded[0].status == "EXPIRED" and discarded[0].reason == "discarded by --fresh"


# --------------------------------------------------------------------------- gate


@pytest.mark.parametrize("resume", [False, True])
def test_gate_red_row_is_not_started_and_changes_nothing(tmp_path: Path, resume: bool) -> None:
    f = fleet()
    env = setup(tmp_path, f)
    if resume:
        f.hosts["athena"].module_errors = {"sofia-documents": ("tcc", "x")}
        run(env)
        f.hosts["athena"].module_errors = {}
    f.hosts["athena"].fda = "denied"
    snapshot = tree(env.paths.root)
    before = env.paths.run_json.read_bytes() if env.paths.run_json.exists() else None
    code, n = run(env)
    assert code == 1
    assert n.sent[0][0].startswith(
        "[bn-backup] NOT STARTED — athena: probe: Switch on BNBackupAgent"
    )
    assert tree(env.paths.root) == snapshot
    after = env.paths.run_json.read_bytes() if env.paths.run_json.exists() else None
    assert after == before


def test_new_user_not_configured_blocks_the_run(tmp_path: Path) -> None:
    f = fleet(users=set())
    env = setup(tmp_path, f)
    code, n = run(env)
    assert code == 1
    assert "hosts configure athena" in n.sent[0][0]
    assert not any(c.startswith("user-add") for c in f.hosts["athena"].calls)


def test_server_red_is_not_started(tmp_path: Path) -> None:
    env = setup(tmp_path)
    shutil.rmtree(env.cfg.server.backup_directory)
    code, n = run(env)
    assert code == 1, "a missing drive is NOT STARTED, not a held lock (D-56)"
    assert n.sent[0][0].startswith("[bn-backup] NOT STARTED — volume:")


# --------------------------------------------------------------------------- dry run


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    f = fleet(module_errors={"sofia-documents": ("tcc", "x")})
    env = setup(tmp_path, f)
    run(env)  # an UNFINISHED run with staged data
    env.clock.advance(hours=40)  # type: ignore[attr-defined]  # ...that is due to expire
    f.hosts["athena"].module_errors = {}
    snapshot = tree(env.paths.root)
    code, n = run(env, dry_run=True)
    assert code == 0
    assert tree(env.paths.root) == snapshot, "D-51: nothing under backup_directory changes"
    assert n.sent == []
    jobs = [j for h in f.hosts.values() for j in h.jobs if j["kind"] == "backup"]
    assert jobs[-1]["options"]["dry_run"] is True and jobs[-1]["options"]["verify"] is False


def test_dry_run_with_fresh_refused(tmp_path: Path) -> None:
    env = setup(tmp_path)
    code, _ = run(env, dry_run=True, fresh=True)
    assert code == 1


# --------------------------------------------------------------------------- abort


def test_source_drive_missing_aborts(tmp_path: Path) -> None:
    f = fleet(
        module_errors={
            "sofia-documents": ("drive_missing", "the external drive Photos is not connected")
        }
    )
    # Pre-flight probes pass; the drive vanishes during the backup job.
    probe_ok = {"done": False}

    def flip(user: str, job: dict[str, Any]) -> None:
        probe_ok["done"] = True

    env = setup(tmp_path, f)
    f.hosts["athena"].module_errors = {}
    original_run = f.agent  # noqa: F841

    def on_backup(user: str, job: dict[str, Any]) -> dict[str, Any]:
        pushing(env.paths)(user, job)
        mods = [
            {
                **m,
                "status": "failed",
                "error_kind": "drive_missing",
                "message": "the external drive Photos is not connected",
            }
            if m["name"] == "sofia-documents"
            else {"name": m["name"], "status": "ok"}
            for m in job["modules"]
        ]
        return {"modules": mods}

    f.hosts["athena"].on_backup = on_backup  # type: ignore[assignment]
    code, n = run(env)
    assert code == 4
    r = load_run(env.paths)
    assert r is not None and r.status == "ABORTED"
    assert (
        r.abort is not None
        and r.abort.cause == "source_drive_missing"
        and r.abort.drive == "Photos"
    )
    assert not any(env.paths.staging_user("galactica", "ariel").iterdir()), "staging wiped"
    assert env.paths.staging_user("athena", "sofia").is_dir()
    assert not (env.paths.current / "sofia-documents").exists()
    assert n.sent[-1][0] == "[bn-backup] ABORTED — Photos unplugged on athena"
    # The next run starts from zero.
    f.hosts["athena"].on_backup = pushing(env.paths)  # type: ignore[assignment]
    code, _ = run(env)
    assert code == 0
    r2 = load_run(env.paths)
    assert r2 is not None and r2.run_id != r.run_id and r2.attempts == 1


def test_backup_volume_lost_writes_marker_and_next_run_cleans_up(tmp_path: Path) -> None:
    f = FakeFleet(FakeHost("galactica", slow_polls=5), FakeHost("athena", slow_polls=5))
    env = setup(tmp_path, f)
    root = env.cfg.server.backup_directory
    parked = tmp_path / "parked"
    polls = {"n": 0}

    def unplug() -> None:
        polls["n"] += 1
        if polls["n"] == 2 and root.exists():
            root.rename(parked)

    f.hosts["galactica"].on_poll = unplug
    code, n = run(env)
    assert code == 4
    marker = env.operator_paths.abort_marker
    assert json.loads(marker.read_text())["cause"] == "backup_volume_lost"
    assert n.sent[-1][0] == "[bn-backup] ABORTED — backup drive unplugged"
    # Plugged back in: the next run cleans up first, then runs.
    parked.rename(root)
    for h in f.hosts.values():
        h.on_poll = None
        h.slow_polls = 0
    (env.paths.staging_user("athena", "sofia") / "leftover").mkdir()
    code, _ = run(env)
    assert code == 0
    assert not marker.exists()
    aborted = [h for h in load_history(env.paths) if h.status == "ABORTED"]
    assert aborted and aborted[0].abort is not None


def test_marker_with_finished_promotion_does_not_wipe(tmp_path: Path) -> None:
    env = setup(tmp_path)
    run(env)
    r = load_run(env.paths)
    assert r is not None
    env.operator_paths.abort_marker.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        env.operator_paths.abort_marker,
        {"run_id": r.run_id, "cause": "backup_volume_lost", "at": "x"},
    )
    # Pretend the promotion was interrupted at its last step.
    journal = {
        "run_id": r.run_id,
        "steps": [
            {"op": "write_report", "src": None, "dst": "current/backup_report.log", "done": False}
        ],
        "report": "finished report\n",
    }
    atomic_write_json(env.paths.promotion_json, journal)
    (env.paths.staging_user("athena", "sofia") / "keep").mkdir()
    runner = Runner(
        env, FakeNotifier(), dry_run=False, fresh=False, wake=False, say=lambda *a: None
    )
    from bn_backup.promotion import execute

    execute(env.paths)
    runner.cleanup_abort(finished_promotion=True)
    assert (env.paths.staging_user("athena", "sofia") / "keep").exists()
    assert not env.operator_paths.abort_marker.exists()


# --------------------------------------------------------------------------- timeouts and hangs


def test_no_job_timeout_waits_for_long_jobs(tmp_path: Path) -> None:
    f = fleet(slow_polls=500)  # a long first backup
    env = setup(tmp_path, f)
    code, _ = run(env)
    assert code == 0
    assert "stop sofia" not in f.hosts["athena"].calls


def test_job_timeout_stops_the_job(tmp_path: Path) -> None:
    f = fleet(slow_polls=10_000)
    data = config_data(settings={"job_timeout_minutes": 1})
    env = setup(tmp_path, f, data)
    env.poll_seconds = 30
    code, _ = run(env)
    assert code == 2
    r = load_run(env.paths)
    assert r is not None and r.modules["sofia-documents"].error_kind == "timeout"
    assert "stop sofia" in f.hosts["athena"].calls


def test_job_that_dies_without_result_does_not_hang(tmp_path: Path) -> None:
    f = fleet(hang=True)
    env = setup(tmp_path, f)
    code, _ = run(env)
    assert code == 2
    r = load_run(env.paths)
    assert r is not None
    assert r.modules["sofia-documents"].error_kind == "no_result"
    assert "stopped without reporting" in (r.modules["sofia-documents"].reason or "")


def test_lost_contact(tmp_path: Path) -> None:
    f = fleet(slow_polls=10_000)
    env = setup(tmp_path, f)

    def vanish() -> None:
        f.hosts["athena"].up = False

    f.hosts["athena"].on_poll = vanish
    code, _ = run(env)
    assert code == 2
    r = load_run(env.paths)
    assert r is not None and r.modules["sofia-documents"].error_kind == "lost_contact"


def test_interrupted_by_sigint(tmp_path: Path) -> None:
    f = fleet(slow_polls=10_000)
    env = setup(tmp_path, f)
    sent = {"done": False}

    def interrupt() -> None:
        if not sent["done"]:
            sent["done"] = True
            os.kill(os.getpid(), signal.SIGINT)

    f.hosts["athena"].on_poll = interrupt
    env.clock.sleep = lambda s: __import__("time").sleep(0.01)  # type: ignore[method-assign]
    code, _ = run(env)
    assert code == 2
    r = load_run(env.paths)
    assert r is not None and r.status == "UNFINISHED"
    assert r.modules["sofia-documents"].reason == "interrupted"
    assert "stop sofia" in f.hosts["athena"].calls


# --------------------------------------------------------------------------- staging


def test_prepare_staging_drops_folders_rsync_will_not_refresh(tmp_path: Path) -> None:
    env = setup(tmp_path)
    spec = env.cfg.module_set()["sofia-documents"]
    old = env.paths.current / "sofia-documents"
    (old / "Documents").mkdir(parents=True)
    (old / "Documents" / "a.txt").write_text("a")
    (old / "OldName").mkdir()
    prepare_staging(env.paths, spec)
    staged = env.paths.staging_module("athena", "sofia", "sofia-documents")
    assert (staged / "Documents" / "a.txt").exists()
    assert not (staged / "OldName").exists()
    assert (old / "OldName").exists(), "current/ untouched"
    hc = env.cfg.module_set()["sofia-athena"]
    hc_dir = env.paths.current / "sofia-athena"
    (hc_dir / "sofia").mkdir(parents=True)
    (hc_dir / "motd").write_text("old motd")
    prepare_staging(env.paths, hc)
    staged_hc = env.paths.staging_module("athena", "sofia", "sofia-athena")
    assert (staged_hc / "sofia").is_dir() and not (staged_hc / "motd").exists()


# --------------------------------------------------------------------------- promotion


def promoted_world(tmp_path: Path, mode: str) -> tuple[Env, dict[str, Any]]:
    data = config_data(settings={"mode": mode, "snapshot_keep": 2})
    env = setup(tmp_path, fleet(), data)
    p = env.paths
    # A v1-style current/: a module, a removed module, a v1 yml, host-config.
    for name in ("sofia-documents", "gone-module", "sofia-athena"):
        (p.current / name).mkdir(parents=True)
        (p.current / name / "old.txt").write_text(f"old {name}")
    (p.current / "backup.yml").write_text("v1 config")
    (p.current / "config.yml").write_text("old config")
    (p.current / "backup_report.log").write_text("old report")
    for spec in env.cfg.module_set().values():
        d = p.staging_module(spec.host, spec.user, spec.name)
        d.mkdir(parents=True, exist_ok=True)
        (d / "new.txt").write_text(f"new {spec.name}")
    from bn_backup.state import RunState

    run_state = RunState(
        run_id="20261110-213000",
        status="RUNNING",
        mode=mode,  # type: ignore[arg-type]
        first_attempt_at="2026-11-10T10:30:00Z",
        last_attempt_at="2026-11-10T10:30:00Z",
    )
    save_run(p, run_state)
    journal = promotion.build(
        p,
        run_state.run_id,
        mode,
        env.cfg.module_set(),
        "2026-11-10T11:00:00Z",
        "the report\n",
        "the config\n",
        env.cfg.user_hosts(),
        2,
    )
    return env, journal


@pytest.mark.parametrize("mode", ["mirror", "snapshot"])
def test_promotion_survives_a_crash_after_every_step(tmp_path: Path, mode: str) -> None:
    env, journal = promoted_world(tmp_path / "clean", mode)
    promotion.promote(env.paths, journal)
    expected = files(env.paths.root)
    expected_run = load_run(env.paths)
    assert expected_run is not None and expected_run.status == "COMPLETE"
    for crash_after in range(1, len(journal["steps"])):
        e2, j2 = promoted_world(tmp_path / f"crash{crash_after}", mode)
        count = {"n": 0}

        def stop(count: dict[str, int] = count, crash_after: int = crash_after) -> bool:
            count["n"] += 1
            return count["n"] >= crash_after

        with pytest.raises(promotion.Interrupted):
            promotion.promote(e2.paths, j2, should_stop=stop)
        assert e2.paths.promotion_json.exists()
        promotion.execute(e2.paths)  # what the next run does first
        assert files(e2.paths.root) == expected, f"crash after step {crash_after}"
        r = load_run(e2.paths)
        assert r is not None and r.status == "COMPLETE" and r.completed_at == "2026-11-10T11:00:00Z"
        assert load_last_complete(e2.paths) is not None
        assert load_history(e2.paths)[0].status == "COMPLETE"


def test_promotion_layout_mirror(tmp_path: Path) -> None:
    env, journal = promoted_world(tmp_path, "mirror")
    promotion.promote(env.paths, journal)
    p = env.paths
    assert (p.current / "sofia-documents" / "new.txt").exists()
    assert (p.current / "sofia-athena" / "new.txt").exists(), "host-config folders stay"
    assert (p.removed / "gone-module" / "old.txt").exists()
    assert (p.removed / "config.yml").read_text() == "old config"
    assert (p.removed / "backup_report.log").read_text() == "old report"
    assert (p.current / "backup.yml").exists(), "v1 yml files are not modules"
    assert (p.current / "config.yml").read_text() == "the config\n"
    assert not p.trash.exists()


def test_snapshot_names_and_pruning(tmp_path: Path) -> None:
    env, journal = promoted_world(tmp_path, "snapshot")
    p = env.paths
    assert journal["snapshot_name"] == promotion.PRE_V2_SNAPSHOT
    promotion.promote(p, journal)
    assert (p.snapshots / promotion.PRE_V2_SNAPSHOT / "sofia-documents" / "old.txt").exists()
    # Later backups are named after the completion time of the one they replace.
    atomic_write_json(
        p.last_complete, LastComplete(run_id="x", completed_at="2026-11-10T11:00:00Z").model_dump()
    )
    name = promotion.snapshot_name(p)
    assert name[:8].isdigit() and name != promotion.PRE_V2_SNAPSHOT
    (p.snapshots / name).mkdir()
    assert promotion.snapshot_name(p) == f"{name}-2"
    (p.snapshots / "20261201-000000").mkdir()
    promotion.prune_snapshots(p, 2)
    left = sorted(x.name for x in p.snapshots.iterdir())
    assert promotion.PRE_V2_SNAPSHOT not in left and len(left) == 2


# --------------------------------------------------------------------------- report


def test_report_and_subject_with_files_to_check(tmp_path: Path) -> None:
    from bn_backup.clock import FakeClock
    from bn_backup.report import render, subject
    from bn_backup.state import ModuleState, RunState

    r = RunState(
        run_id="20261110-213000",
        status="UNFINISHED",
        first_attempt_at="2026-11-10T10:30:00Z",
        last_attempt_at="2026-11-10T10:30:00Z",
        last_attempt_finished_at="2026-11-10T11:00:00Z",
        attempts=2,
        modules={
            "archive": ModuleState(
                host="galactica",
                user="ariel",
                type="path",
                status="green",
                suspect_count=25,
                suspect_files=[f"Photos/{i}.NEF" for i in range(25)],
            ),
            "lightroom": ModuleState(
                host="galactica",
                user="ariel",
                type="path",
                status="red",
                error_kind="source_empty",
                reason="/x is empty",
                src_path="/Users/ariel/Pictures/Lightroom",
            ),
        },
    )
    text = render(r, 30, 600, FakeClock().now())
    assert "Run:      20261110-213000   (attempt 2)" in text
    assert "Status:   UNFINISHED — re-run before" in text
    assert "lightroom (galactica/ariel): source_empty" in text
    assert "remove the module from the config" in text
    assert "Files to check (verify_backup):" in text
    assert "… and 5 more; see `bn-backup runs show 20261110-213000`" in text
    assert "Nothing was overwritten" in text
    assert text.rstrip().splitlines()[-1].startswith("# Date: ")
    assert subject(r) == "[bn-backup] UNFINISHED — 1 of 2 modules red — 25 files to check"


@pytest.mark.parametrize(
    "kind",
    ["tcc", "server_denied", "permission", "missing", "drive_missing", "source_empty",
     "network", "stalled", "timeout", "lost_contact", "no_result"],
)  # fmt: skip
def test_every_error_kind_has_a_hint(kind: str) -> None:
    from bn_backup.report import hint
    from bn_backup.state import ModuleState

    m = ModuleState(host="athena", user="sofia", type="path", error_kind=kind, src_path="/x")
    assert hint("m", m, 600) != "See the rsync log for details"


def test_notification_failure_does_not_change_the_outcome(tmp_path: Path) -> None:
    env = setup(tmp_path)
    code, _ = run(env, notifier=FakeNotifier(fail=True))
    assert code == 0
    assert "Notification failures" in env.paths.last_report.read_text()
