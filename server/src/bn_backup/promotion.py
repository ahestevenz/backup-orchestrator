# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Promotion: staging becomes current/, step by step, from a journal (§6.9, D-52).

Every step is written to `.state/promotion.json` before any is taken, and each
one is idempotent, so a crash at any point is finished by the next `run`.
Only renames, rmtree, copies, mkdir and small file writes; all on one drive.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .clock import local_stamp, parse_iso
from .config import ModuleSpec
from .fsutil import atomic_write_json, atomic_write_text, ensure_dir, read_json
from .paths import BackupPaths, is_non_module_entry
from .state import LastComplete, load_last_complete, load_run, save_run, write_history

PRE_V2_SNAPSHOT = "00000000-000000-pre-v2"


class Interrupted(Exception):
    """Asked to stop between two steps; the journal stays for the next run."""


def snapshot_name(paths: BackupPaths) -> str:
    """Named after the completion time of the backup being replaced."""
    last = load_last_complete(paths)
    base = local_stamp(parse_iso(last.completed_at)) if last else PRE_V2_SNAPSHOT
    name, n = base, 1
    while (paths.snapshots / name).exists():
        n += 1
        name = f"{base}-{n}"
    return name


def build(
    paths: BackupPaths,
    run_id: str,
    mode: str,
    module_set: dict[str, ModuleSpec],
    completed_at: str,
    report: str,
    config_text: str,
    user_hosts: list[tuple[str, str]],
    snapshot_keep: int,
) -> dict[str, Any]:
    snap = snapshot_name(paths) if mode == "snapshot" else None
    steps: list[dict[str, Any]] = []

    def step(op: str, src: str | None = None, dst: str | None = None) -> None:
        steps.append({"op": op, "src": src, "dst": dst, "done": False})

    for name, spec in sorted(module_set.items()):
        if (paths.current / name).exists():
            old_home = f".trash/{run_id}/{name}" if mode == "mirror" else f"snapshots/{snap}/{name}"
            step("rename", f"current/{name}", old_home)
        step("rename", f".staging/{spec.host}/{spec.user}/{name}", f"current/{name}")
    gone = []
    if paths.current.is_dir():
        for entry in sorted(paths.current.iterdir()):
            if (
                entry.is_dir()
                and entry.name not in module_set
                and not is_non_module_entry(entry.name)
            ):
                gone.append(entry.name)
    for name in gone:
        step("rmtree", f"removed/{name}")
        step("rename", f"current/{name}", f"removed/{name}")
    if gone:
        step("copy", "current/config.yml", "removed/config.yml")
        step("copy", "current/backup_report.log", "removed/backup_report.log")
    step("write_config", dst="current/config.yml")
    step("write_report", dst="current/backup_report.log")
    step("rmtree", ".trash")
    if mode == "snapshot":
        step("prune_snapshots")
    step("reset_staging")
    step("finalize")
    return {
        "run_id": run_id,
        "mode": mode,
        "snapshot_name": snap,
        "snapshot_keep": snapshot_keep,
        "completed_at": completed_at,
        "report": report,
        "config_text": config_text,
        "user_hosts": [list(p) for p in user_hosts],
        "steps": steps,
    }


def _rename(root: Path, src: str, dst: str) -> None:
    s, d = root / src, root / dst
    if not s.exists() and d.exists():
        return  # done before a crash
    d.parent.mkdir(parents=True, exist_ok=True)
    s.rename(d)


def _rmtree(root: Path, rel: str) -> None:
    p = root / rel
    if p.is_dir():
        shutil.rmtree(p)


def _copy(root: Path, src: str, dst: str) -> None:
    s, d = root / src, root / dst
    if s.exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)


def prune_snapshots(paths: BackupPaths, keep: int) -> None:
    if not paths.snapshots.is_dir():
        return
    names = sorted(p.name for p in paths.snapshots.iterdir() if p.is_dir())
    for name in names[: max(0, len(names) - keep)]:
        shutil.rmtree(paths.snapshots / name)


def reset_staging(paths: BackupPaths, user_hosts: list[tuple[str, str]]) -> None:
    """Delete .staging/ and recreate every user's folder (rrsync needs them, §6.9)."""
    if paths.staging.is_dir():
        shutil.rmtree(paths.staging)
    ensure_dir(paths.staging, 0o700)
    for host, user in user_hosts:
        ensure_dir(paths.staging_user(host, user), 0o700)


def _finalize(paths: BackupPaths, journal: dict[str, Any]) -> None:
    run = load_run(paths)
    if run is None or run.run_id != journal["run_id"]:
        raise RuntimeError("promotion journal and run.json disagree")
    run.status = "COMPLETE"
    run.completed_at = journal["completed_at"]
    save_run(paths, run)
    atomic_write_json(
        paths.last_complete,
        LastComplete(run_id=run.run_id, completed_at=journal["completed_at"]).model_dump(),
    )
    atomic_write_text(paths.last_report, journal["report"], 0o600)
    write_history(paths, run)


def execute(paths: BackupPaths, should_stop: Callable[[], bool] = lambda: False) -> None:
    """Run the journal's remaining steps, saving it after each; then delete it."""
    root = paths.root
    journal: dict[str, Any] = read_json(paths.promotion_json)
    for st in journal["steps"]:
        if st["done"]:
            continue
        op = st["op"]
        if op == "rename":
            _rename(root, st["src"], st["dst"])
        elif op == "rmtree":
            _rmtree(root, st["src"])
        elif op == "copy":
            _copy(root, st["src"], st["dst"])
        elif op == "write_config":
            atomic_write_text(root / st["dst"], journal["config_text"], 0o600)
        elif op == "write_report":
            atomic_write_text(root / st["dst"], journal["report"], 0o600)
        elif op == "prune_snapshots":
            prune_snapshots(paths, int(journal["snapshot_keep"]))
        elif op == "reset_staging":
            reset_staging(paths, [(h, u) for h, u in journal["user_hosts"]])
        elif op == "finalize":
            _finalize(paths, journal)
        else:
            raise RuntimeError(f"unknown promotion step {op!r}")
        st["done"] = True
        atomic_write_json(paths.promotion_json, journal)
        if should_stop():
            raise Interrupted()
    paths.promotion_json.unlink()


def promote(
    paths: BackupPaths,
    journal: dict[str, Any],
    should_stop: Callable[[], bool] = lambda: False,
) -> None:
    atomic_write_json(paths.promotion_json, journal)
    execute(paths, should_stop)
