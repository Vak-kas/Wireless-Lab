# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Simulated devices, probe and test action.

Used to develop and verify the controller without hardware. Faults (device
unplugged, probe crash, stall, hanging revert) are switched on per instance.
Nothing here touches a real interface or transmits anything.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field

from wls.core.devices import SUPPORTED, Capability, Device, DeviceKind, unsupported
from wls.core.interfaces import Emit


class DeviceLost(RuntimeError):
    pass


def sim_host(device_id: str = "sim-host") -> Device:
    return Device(device_id, DeviceKind.HOST, "Simulated host", {Capability.NET_PROBE: SUPPORTED})


def sim_wifi_nic(
    device_id: str = "sim-wlan0",
    *,
    standard: str = "ax",
    monitor: bool = True,
    inject: bool = False,
) -> Device:
    caps = {
        Capability.NET_PROBE: SUPPORTED,
        Capability.WIFI_LINK_INFO: SUPPORTED,
        Capability.WIFI_IDENTITY: SUPPORTED,
        Capability.WIFI_SCAN: SUPPORTED,
        Capability.WIFI_MONITOR: SUPPORTED
        if monitor
        else unsupported("driver does not offer monitor mode"),
        Capability.WIFI_INJECT: SUPPORTED
        if inject
        else unsupported("driver does not support frame injection"),
    }
    return Device(
        device_id,
        DeviceKind.WIFI_NIC,
        f"Simulated 802.11{standard} adapter",
        caps,
        {"standard": standard},
    )


def sim_sdr(device_id: str = "sim-sdr0", *, model: str = "HackRF One") -> Device:
    caps = {
        Capability.SDR_RX: SUPPORTED,
        Capability.SDR_TX: unsupported("transmitting is not available in this edition"),
    }
    return Device(device_id, DeviceKind.SDR, f"Simulated {model}", caps, {"model": model})


class SimProvider:
    name = "sim"

    def __init__(self, devices: Iterable[Device] = ()) -> None:
        self._devices = {d.id: d for d in devices}
        self.impaired = False  # set by SimTestAction, visible in SimProbe values
        self.discover_delay = 0.0

    async def discover(self) -> list[Device]:
        if self.discover_delay:
            await asyncio.sleep(self.discover_delay)
        return list(self._devices.values())

    def plug(self, device: Device) -> None:
        self._devices[device.id] = device

    def unplug(self, device_id: str) -> None:
        self._devices.pop(device_id, None)

    def connected(self, device_id: str) -> bool:
        return device_id in self._devices


async def _hang() -> None:
    await asyncio.Event().wait()


@dataclass
class SimProbe:
    provider: SimProvider
    device_id: str = "sim-host"
    name: str = "sim-link"
    requires: frozenset[Capability] = frozenset({Capability.NET_PROBE})
    interval: float = 0.005
    # faults
    never_start: bool = False
    crash_after: int | None = None
    stall_after: int | None = None
    ignore_cancel: bool = False
    # observations
    runs: int = field(default=0, init=False)

    async def run(self, emit: Emit) -> None:
        self.runs += 1
        produced = 0
        try:
            if self.never_start:
                await _hang()
            while True:
                if not self.provider.connected(self.device_id):
                    raise DeviceLost(f"device {self.device_id} disconnected")
                if self.crash_after is not None and produced >= self.crash_after:
                    raise RuntimeError("simulated probe crash")
                if self.stall_after is not None and produced >= self.stall_after:
                    await _hang()
                emit({"rtt_ms": 200.0 if self.provider.impaired else 20.0})
                produced += 1
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            if self.ignore_cancel:
                await asyncio.sleep(3600)
            raise


@dataclass
class SimTestAction:
    provider: SimProvider
    device_id: str = "sim-host"
    name: str = "sim-impairment"
    requires: frozenset[Capability] = frozenset({Capability.NET_PROBE})
    # faults
    fail_start: bool = False
    hang_start: bool = False
    fail_stop: bool = False
    fail_revert: bool = False
    hang_revert: bool = False
    # observations
    start_calls: int = field(default=0, init=False)
    stop_calls: int = field(default=0, init=False)
    revert_calls: int = field(default=0, init=False)

    async def start(self) -> None:
        self.start_calls += 1
        if self.hang_start:
            await _hang()
        self.provider.impaired = True
        if self.fail_start:
            raise RuntimeError("simulated test start failure")  # leaves a partial effect

    async def stop(self) -> None:
        self.stop_calls += 1
        if self.fail_stop:
            raise RuntimeError("simulated test stop failure")
        self.provider.impaired = False

    async def revert(self) -> None:
        self.revert_calls += 1
        if self.hang_revert:
            await _hang()
        if self.fail_revert:
            raise RuntimeError("simulated revert failure")
        self.provider.impaired = False
