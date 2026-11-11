# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Wake-on-LAN from the server (CLAUDE.md §6.10, D-24)."""

from __future__ import annotations

import socket
from collections.abc import Callable

from .clock import Clock

PORTS = (9, 7)
RECHECK_SECONDS = 15


def magic_packet(mac: str) -> bytes:
    """6 × 0xFF followed by the MAC address 16 times."""
    hexdigits = mac.replace(":", "").replace("-", "")
    if len(hexdigits) != 12:
        raise ValueError(f"not a MAC address: {mac!r}")
    raw = bytes.fromhex(hexdigits)
    return b"\xff" * 6 + raw * 16


def send_magic_packets(macs: list[str]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for mac in macs:
            packet = magic_packet(mac)
            for port in PORTS:
                s.sendto(packet, ("255.255.255.255", port))


def wake_and_wait(
    macs: list[str],
    is_up: Callable[[], bool],
    send: Callable[[list[str]], None],
    clock: Clock,
    wait_seconds: int,
) -> bool:
    """Send magic packets, then recheck every 15 s for up to `wait_seconds`."""
    send(macs)
    waited = 0
    while waited < wait_seconds:
        step = min(RECHECK_SECONDS, wait_seconds - waited)
        clock.sleep(step)
        waited += step
        if is_up():
            return True
    return False
