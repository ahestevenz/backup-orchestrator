# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Agent packages from the GitHub release matching the server's version (§6.12, D-29)."""

from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .fsutil import atomic_write_bytes

BASE_URL = "https://github.com/bleiben-labs/backup-orchestrator/releases/download"
DEB_ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}

Fetch = Callable[[str], bytes]


class ReleaseError(Exception):
    pass


def package_name(version: str, os_name: str, arch: str) -> str:
    if os_name == "darwin":
        return f"bn-backup-agent-{version}.pkg"
    if os_name == "linux":
        try:
            return f"bn-backup-agent_{version}_{DEB_ARCH[arch]}.deb"
        except KeyError:
            raise ReleaseError(f"no Linux agent package for the {arch} architecture") from None
    raise ReleaseError(f"no agent package for {os_name}")


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        data: bytes = r.read()
        return data


def parse_sums(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            out[parts[1].lstrip("*")] = parts[0].lower()
    return out


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_package(
    version: str,
    os_name: str,
    arch: str,
    cache_root: Path,
    override: Path | None = None,
    fetch: Fetch = _download,
) -> Path:
    """The verified package for this host, downloaded or from the cache."""
    if override is not None:
        if not override.is_file():
            raise ReleaseError(f"--agent-package {override} does not exist")
        return override
    name = package_name(version, os_name, arch)
    cache = cache_root / version
    target = cache / name
    sums_file = cache / "SHA256SUMS"
    base = f"{BASE_URL}/v{version}"
    try:
        sums_text = fetch(f"{base}/SHA256SUMS").decode("utf-8")
        sums = parse_sums(sums_text)
        if name not in sums:
            raise ReleaseError(f"{name} is not listed in the v{version} SHA256SUMS")
        if not (target.is_file() and sha256(target.read_bytes()) == sums[name]):
            data = fetch(f"{base}/{name}")
            if sha256(data) != sums[name]:
                raise ReleaseError(f"{name}: the download does not match SHA256SUMS; refusing it")
            atomic_write_bytes(target, data, 0o644)
        atomic_write_bytes(sums_file, sums_text.encode(), 0o644)
        return target
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        # Offline: an already verified file in the cache will do.
        if target.is_file() and sums_file.is_file():
            sums = parse_sums(sums_file.read_text(encoding="utf-8"))
            if sums.get(name) == sha256(target.read_bytes()):
                return target
        raise ReleaseError(
            f"cannot download {name} for v{version} ({e}); "
            "check the network or pass --agent-package PATH"
        ) from e
