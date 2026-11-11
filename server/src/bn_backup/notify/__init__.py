# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Notifications by Email and Signal (CLAUDE.md §6.14, D-25).

A failing channel is logged and reported; it never changes a run's status
or exit code.
"""

from __future__ import annotations

import getpass
import sys
from collections.abc import Callable
from typing import Any, Protocol

from loguru import logger

from ..config import Config
from ..fsutil import atomic_write_text, ensure_dir
from . import email, signal


class Notifier(Protocol):
    def send(self, subject: str, body: str) -> list[str]:
        """Send on every enabled channel; return one line per failed channel."""
        ...


class ChannelNotifier:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def send(self, subject: str, body: str) -> list[str]:
        failures = []
        n = self.cfg.notifications
        if n.email.enabled:
            try:
                email.send(n.email, subject, body)
            except Exception as e:
                failures.append(f"email: {e}")
        if n.signal.enabled:
            try:
                signal.send(n.signal, f"{subject}\n\n{body}")
            except Exception as e:
                failures.append(f"signal: {e}")
        for f in failures:
            logger.warning(f"notification failed: {f}")
        return failures


def cmd_test(ctx: Any) -> int:
    cfg = ctx.loaded().config
    n = cfg.notifications
    if not n.email.enabled and not n.signal.enabled:
        print("No channel is enabled under notifications: in the config.")
        return 1
    failed = False
    text = "bn-backup test message"
    channels: list[tuple[str, bool, Callable[[], None]]] = [
        ("email", n.email.enabled, lambda: email.send(n.email, text, text)),
        ("signal", n.signal.enabled, lambda: signal.send(n.signal, text)),
    ]
    for name, enabled, fn in channels:
        if not enabled:
            continue
        try:
            fn()
            print(f"{name}: sent")
        except Exception as e:
            print(f"{name}: FAILED — {e}")
            failed = True
    return 1 if failed else 0


def cmd_set_smtp_password(ctx: Any) -> int:
    cfg = ctx.loaded().config
    path = cfg.notifications.email.password_file or (
        ctx.paths.home / ".config" / "bn-backup" / "smtp_password"
    )
    password = getpass.getpass("Email app password: ")
    if not password:
        print("nothing stored", file=sys.stderr)
        return 1
    ensure_dir(path.parent, 0o700)
    atomic_write_text(path, password + "\n", 0o600)
    print(f"stored in {path} (only you can read it)")
    return 0
