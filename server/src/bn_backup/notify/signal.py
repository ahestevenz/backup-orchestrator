# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Signal through signal-cli linked as a secondary device (CLAUDE.md §6.14)."""

from __future__ import annotations

import subprocess

from ..config import SignalConfig

TIMEOUT = 60


def commands(cfg: SignalConfig, text: str) -> list[list[str]]:
    cli = str(cfg.signal_cli)
    out = []
    if cfg.note_to_self:
        out.append([cli, "-a", cfg.account, "send", "--note-to-self", "-m", text])
    if cfg.recipients:
        out.append([cli, "-a", cfg.account, "send", "-m", text, *cfg.recipients])
    return out


def send(cfg: SignalConfig, text: str) -> None:
    for argv in commands(cfg, text):
        p = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT, check=False)
        if p.returncode != 0:
            err = (p.stderr.strip().splitlines() or [f"exit {p.returncode}"])[-1]
            raise RuntimeError(f"signal-cli: {err}")
