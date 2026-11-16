# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Follow one Bluetooth device's signal over time.

The probe listens in short windows and, each time, reports whether the chosen
device was heard and how strong its advertisement was. It reads only what the
device broadcasts; it never connects to it. A device that stops advertising,
moves out of range, or rotates its identifier simply stops being heard.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from wls.core.bluetooth import BtScan
from wls.core.devices import Capability
from wls.core.interfaces import Emit
from wls.providers.host import HOST_ID


class BluetoothUnavailable(RuntimeError):
    pass


@dataclass
class BleTrackProbe:
    scan: Callable[[float], BtScan]  # blocks for about the given number of seconds
    target_id: str
    name: str = "bt"
    device_id: str = HOST_ID
    requires: frozenset[Capability] = frozenset()
    window: float = 2.0

    async def run(self, emit: Emit) -> None:
        while True:
            result = await asyncio.to_thread(self.scan, self.window)
            if result.state != "on":
                raise BluetoothUnavailable(f"bluetooth is {result.state}")
            device = next((d for d in result.devices if d.id == self.target_id), None)
            if device is None:
                emit({"heard": 0.0})
            else:
                emit({"heard": 1.0, "rssi_dbm": float(device.rssi_dbm)})
