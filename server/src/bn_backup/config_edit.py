# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Editing the config for `hosts add`, keeping comments and layout (D-34, CLAUDE.md §6.6).

The only place that writes the config. ruamel.yaml is used in round-trip
mode here and nowhere else.
"""

from __future__ import annotations

import io
import stat
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .config import ConfigError, load_config
from .fsutil import atomic_write_bytes


def add_host(
    path: Path,
    host: str,
    address: str,
    admin_user: str,
    ssh_port: int,
    home: Path | None = None,
) -> None:
    """Append a host at the end of `hosts:`; restore the original bytes if invalid."""
    original = path.read_bytes()
    mode = stat.S_IMODE(path.stat().st_mode)
    yaml = YAML()
    yaml.preserve_quotes = True
    data = yaml.load(original)
    if data is None or not isinstance(data, CommentedMap):
        raise ConfigError(["config: the file must be a YAML mapping"])
    hosts = data.get("hosts")
    if hosts is None:
        hosts = CommentedMap()
        data["hosts"] = hosts
    if host in hosts:
        raise ConfigError([f"hosts.{host}: already in the config"])
    entry = CommentedMap()
    entry["address"] = address
    entry["admin_user"] = admin_user
    entry["ssh_port"] = ssh_port
    hosts[host] = entry
    buf = io.StringIO()
    yaml.dump(data, buf)
    atomic_write_bytes(path, buf.getvalue().encode("utf-8"), mode)
    try:
        load_config(path, home)
    except ConfigError:
        atomic_write_bytes(path, original, mode)
        raise
