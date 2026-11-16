# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Bluetooth on macOS through the helper app.

A command line process that uses Bluetooth itself is terminated by macOS
unless the program that started it declares Bluetooth use, so scanning goes
through the helper, which declares it and asks the user once.
"""

from __future__ import annotations

from wls.core.bluetooth import BluetoothBackend, BtDevice, BtScan, maker_name
from wls.providers import macos_helper


def scan_from_helper(answer: dict) -> BtScan:
    devices = [
        BtDevice(
            id=str(d["id"]),
            rssi_dbm=float(d["rssi"]),
            name=d.get("name") or None,
            maker=maker_name(d.get("company")),
            connectable=d.get("connectable"),
            services=tuple(d.get("services", [])),
        )
        for d in answer.get("devices", [])
        if "rssi" in d
    ]
    devices.sort(key=lambda d: d.rssi_dbm, reverse=True)
    return BtScan(str(answer.get("bluetooth", "unknown")), tuple(devices))


def scan(seconds: float) -> BtScan:
    answer = macos_helper.run("bluetooth", str(int(seconds)), timeout=seconds + 140)
    return scan_from_helper(answer)


def setup() -> str:
    """Build the helper if needed, then let macOS ask for Bluetooth permission."""
    macos_helper.setup()
    return scan(1).state


def backend() -> BluetoothBackend:
    return BluetoothBackend(scan, macos_helper.current, setup)
