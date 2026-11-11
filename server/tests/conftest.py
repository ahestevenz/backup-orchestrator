# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Shared test fixtures."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

FIXTURES = Path(__file__).parent / "fixtures"

BASE_CONFIG: dict[str, Any] = {
    "version": 2,
    "server": {
        "backup_directory": "/Volumes/Backup/bn-backup",
        "ssh_host": "server.home.lan",
        "receive_user": "ariel",
    },
    "hosts": {
        "galactica": {"address": "galactica.home.lan", "admin_user": "ariel"},
        "athena": {"address": "athena.home.lan", "admin_user": "ariel"},
    },
    "modules": {
        "ariel-photo-archive": {
            "host": "galactica",
            "user": "ariel",
            "src_path": "/Volumes/PhotoArchive/Photos",
        },
        "sofia-documents": {
            "host": "athena",
            "user": "sofia",
            "src_path": "/Users/sofia/Documents",
            "excludes": [".DS_Store"],
        },
    },
}


def config_data(**overrides: Any) -> dict[str, Any]:
    """A valid config as a dict, with top-level sections replaced or merged."""
    data = copy.deepcopy(BASE_CONFIG)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    return data


def write_config(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    return write_config(tmp_path / "config.yml", config_data())
