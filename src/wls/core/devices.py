# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Devices and what each of them can do.

A device reports, per capability, whether it is supported and if not, why.
Anything that needs hardware (a probe, a test action) declares the
capabilities it requires. A feature is usable on a device exactly when the
device supports everything the feature requires.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class DeviceKind(Enum):
    HOST = "host"  # the computer's own network stack
    WIFI_NIC = "wifi_nic"
    SDR = "sdr"  # USRP, HackRF and similar
    CELL_MODEM = "cell_modem"
    GNSS_RECEIVER = "gnss_receiver"


class Capability(Enum):
    NET_PROBE = "net_probe"  # latency, loss, throughput
    WIFI_LINK_INFO = "wifi_link_info"
    WIFI_SCAN = "wifi_scan"
    WIFI_MONITOR = "wifi_monitor"
    WIFI_INJECT = "wifi_inject"
    SDR_RX = "sdr_rx"
    SDR_TX = "sdr_tx"
    CELL_SERVING_INFO = "cell_serving_info"
    GNSS_NAV = "gnss_nav"
    GNSS_RAW = "gnss_raw"


@dataclass(frozen=True, slots=True)
class Support:
    supported: bool
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.supported and not self.reason:
            raise ValueError("an unsupported capability must say why")


SUPPORTED = Support(True)


def unsupported(reason: str) -> Support:
    return Support(False, reason)


@dataclass(frozen=True, slots=True)
class Device:
    id: str
    kind: DeviceKind
    name: str
    capabilities: Mapping[Capability, Support] = field(default_factory=dict)
    details: Mapping[str, str] = field(default_factory=dict)

    def support(self, capability: Capability) -> Support:
        return self.capabilities.get(capability, unsupported("not reported by this device"))

    def check(self, requires: Iterable[Capability]) -> Support:
        """Can a feature with these requirements run on this device?"""
        missing = [
            f"{cap.value}: {self.support(cap).reason}"
            for cap in sorted(requires, key=lambda c: c.value)
            if not self.support(cap).supported
        ]
        return unsupported("; ".join(missing)) if missing else SUPPORTED


class DeviceProvider(Protocol):
    name: str

    async def discover(self) -> list[Device]: ...


class DeviceManager:
    """Collects devices from all providers. One failing provider never hides the others."""

    def __init__(self, providers: Iterable[DeviceProvider]) -> None:
        self._providers = list(providers)
        self._devices: dict[str, Device] = {}
        self.provider_errors: dict[str, str] = {}

    async def refresh(self) -> list[Device]:
        devices: dict[str, Device] = {}
        errors: dict[str, str] = {}
        for provider in self._providers:
            try:
                found = await provider.discover()
            except Exception as exc:  # a broken driver must not break discovery
                errors[provider.name] = repr(exc)
                continue
            for device in found:
                devices[device.id] = device
        self._devices, self.provider_errors = devices, errors
        return list(devices.values())

    @property
    def devices(self) -> list[Device]:
        return list(self._devices.values())

    def get(self, device_id: str) -> Device | None:
        return self._devices.get(device_id)

    def usable_for(self, requires: Iterable[Capability]) -> list[tuple[Device, Support]]:
        """For every known device: can it run a feature with these requirements?"""
        requires = frozenset(requires)
        return [(device, device.check(requires)) for device in self._devices.values()]
