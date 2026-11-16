# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Bluetooth Low Energy devices seen nearby.

Only what devices broadcast about themselves is read; nothing is connected to.
Many devices broadcast no name, and phones change their identifier every few
minutes, so the same device can appear as a new entry later.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

# Bluetooth SIG company identifiers of common makers (best effort, not complete).
COMPANIES = {
    0x0006: "Microsoft", 0x000D: "Texas Instruments", 0x004C: "Apple", 0x0059: "Nordic Semiconductor",
    0x0075: "Samsung", 0x0087: "Garmin", 0x009E: "Bose", 0x00C4: "LG Electronics", 0x00E0: "Google",
    0x012D: "Sony", 0x0157: "Huami", 0x0171: "Amazon", 0x02E5: "Espressif", 0x038F: "Xiaomi",
    0x0499: "Ruuvi",
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class BtDevice:
    id: str  # stable only on this computer and only for a while
    rssi_dbm: float
    name: str | None = None
    maker: str | None = None
    connectable: bool | None = None
    services: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class BtScan:
    state: str  # "on", "off", "unauthorized", "unsupported" or "unknown"
    devices: tuple[BtDevice, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class BluetoothBackend:
    """What an operating system offers for Bluetooth."""

    scan: Callable[[float], BtScan]  # blocks for about the given number of seconds
    ready: Callable[[], bool]  # False while a one-time setup is still needed
    setup: Callable[[], str] | None = None  # returns the Bluetooth state afterwards


def maker_name(company: int | None) -> str | None:
    return COMPANIES.get(company) if company is not None else None
