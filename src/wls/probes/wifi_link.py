# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Wi-Fi link quality of the connected network, sampled at a fixed rate.

The probe is the same on every OS. Each OS provider supplies a ``reader``
that returns a ``LinkReading`` (or None while not connected).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from wls.core.devices import Capability
from wls.core.interfaces import Emit


@dataclass(frozen=True, slots=True)
class LinkReading:
    rssi_dbm: float
    noise_dbm: float | None = None
    tx_rate_mbps: float | None = None
    channel: int | None = None
    band_ghz: float | None = None  # 2.4, 5 or 6
    width_mhz: int | None = None

    def values(self) -> dict[str, float]:
        out: dict[str, float] = {"associated": 1.0, "rssi_dbm": float(self.rssi_dbm)}
        if self.noise_dbm is not None:
            out["noise_dbm"] = float(self.noise_dbm)
            out["snr_db"] = float(self.rssi_dbm - self.noise_dbm)
        for key in ("tx_rate_mbps", "channel", "band_ghz", "width_mhz"):
            value = getattr(self, key)
            if value is not None:
                out[key] = float(value)
        return out


Reader = Callable[[], LinkReading | None]


@dataclass(frozen=True, slots=True)
class ScanEntry:
    """One network seen in a scan. Name and BSSID are None when the OS hides them."""

    rssi_dbm: float
    ssid: str | None = None
    bssid: str | None = None
    channel: int | None = None
    band_ghz: float | None = None
    width_mhz: int | None = None
    security: str = ""  # "open", "WEP", "WPA", "WPA2", "WPA2/WPA3", "WPA3", "enterprise" or ""


Scanner = Callable[[], list[ScanEntry]]


@dataclass(frozen=True, slots=True)
class WifiBackend:
    """What an operating system offers for Wi-Fi."""

    provider: object  # a DeviceProvider
    link_reader: Callable[[str], Reader]
    scanner: Callable[[str], Scanner]
    id_prefix: str
    # (ssid, bssid) of the connected network; None values when the OS hides them
    # the second argument asks for a fresh reading instead of a recently cached one
    identity: Callable[..., tuple[str | None, str | None]] | None = None
    # one-time setup that makes network names available; returns a status word
    names_setup: Callable[[], str] | None = None


@dataclass
class WifiLinkProbe:
    device_id: str
    reader: Reader
    name: str = "wifi"
    requires: frozenset[Capability] = frozenset({Capability.WIFI_LINK_INFO})
    interval: float = 1.0

    async def run(self, emit: Emit) -> None:
        loop = asyncio.get_running_loop()
        next_at = loop.time()
        while True:
            reading = self.reader()
            emit({"associated": 0.0} if reading is None else reading.values())
            next_at = max(next_at + self.interval, loop.time())
            await asyncio.sleep(next_at - loop.time())
