# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Injectable clock, so tests can control time."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class FakeClock:
    """A clock that only moves when told to (or when something sleeps)."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 11, 10, 10, 30, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)


def iso(dt: datetime) -> str:
    """UTC ISO 8601 with a Z suffix, as stored in state files."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def local_stamp(dt: datetime) -> str:
    """Local time as YYYYMMDD-HHMMSS (run IDs, snapshot names)."""
    return dt.astimezone().strftime("%Y%m%d-%H%M%S")


def local_display(dt: datetime) -> str:
    """Local time for people: 2026-11-11 21:30."""
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")
