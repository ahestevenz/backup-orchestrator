# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Where everything lives: the backup drive layout and the operator's files.

Backup drive layout (CLAUDE.md §6.9) and per-operator paths (§6.1).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# Entries of current/ that are not module folders (§6.9).
NON_MODULE_FILES = ("config.yml", "backup_report.log")


def is_non_module_entry(name: str) -> bool:
    """config.yml, backup_report.log and v1 leftovers (*.yml, *.yaml)."""
    return name in NON_MODULE_FILES or name.endswith((".yml", ".yaml"))


@dataclass(frozen=True)
class BackupPaths:
    """Paths under backup_directory."""

    root: Path

    @property
    def current(self) -> Path:
        return self.root / "current"

    @property
    def removed(self) -> Path:
        return self.root / "removed"

    @property
    def snapshots(self) -> Path:
        return self.root / "snapshots"

    @property
    def staging(self) -> Path:
        return self.root / ".staging"

    @property
    def trash(self) -> Path:
        return self.root / ".trash"

    @property
    def state(self) -> Path:
        return self.root / ".state"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def run_json(self) -> Path:
        return self.state / "run.json"

    @property
    def promotion_json(self) -> Path:
        return self.state / "promotion.json"

    @property
    def last_complete(self) -> Path:
        return self.state / "last_complete.json"

    @property
    def last_report(self) -> Path:
        return self.state / "last_report.log"

    @property
    def hosts_dir(self) -> Path:
        return self.state / "hosts"

    @property
    def keys_dir(self) -> Path:
        return self.state / "keys"

    @property
    def history_dir(self) -> Path:
        return self.state / "history"

    def host_record(self, host: str) -> Path:
        return self.hosts_dir / f"{host}.json"

    def key_file(self, host: str, user: str) -> Path:
        return self.keys_dir / host / f"{user}.pub"

    def history_file(self, run_id: str) -> Path:
        return self.history_dir / f"{run_id}.json"

    def staging_user(self, host: str, user: str) -> Path:
        return self.staging / host / user

    def staging_module(self, host: str, user: str, module: str) -> Path:
        return self.staging / host / user / module

    def run_logs(self, run_id: str) -> Path:
        return self.logs / run_id


@dataclass(frozen=True)
class OperatorPaths:
    """The operator's own files on the server (§6.1)."""

    home: Path

    @property
    def config(self) -> Path:
        return self.home / ".config" / "bn-backup" / "config.yml"

    @property
    def control_key(self) -> Path:
        return self.home / ".ssh" / "bn-backup_ed25519"

    @property
    def control_key_pub(self) -> Path:
        return self.home / ".ssh" / "bn-backup_ed25519.pub"

    @property
    def authorized_keys(self) -> Path:
        return self.home / ".ssh" / "authorized_keys"

    @property
    def rrsync(self) -> Path:
        return self.home / ".local" / "libexec" / "bn-backup" / "rrsync"

    @property
    def release_cache(self) -> Path:
        return self.home / ".cache" / "bn-backup" / "releases"

    @property
    def state_dir(self) -> Path:
        return self.home / ".local" / "state" / "bn-backup"

    @property
    def abort_marker(self) -> Path:
        return self.state_dir / "abort-pending.json"

    @property
    def lock(self) -> Path:
        return self.state_dir / "lock"

    @property
    def log_file(self) -> Path:
        if sys.platform == "darwin":
            return self.home / "Library" / "Logs" / "bn-backup.log"
        return self.state_dir / "bn-backup.log"

    @property
    def schedule_log(self) -> Path:
        if sys.platform == "darwin":
            return self.home / "Library" / "Logs" / "bn-backup-schedule.log"
        return self.state_dir / "bn-backup-schedule.log"
