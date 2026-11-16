# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 서민재
"""Ready-made measurements, shared by the command line and the web UI.

A ``Plan`` says which probes to run; ``run_plan`` drives the controller from
prepare to a finished run. Neither prints nor stores anything by itself.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from wls.core.bluetooth import BluetoothBackend
from wls.core.controller import Controller, ExperimentConfig
from wls.core.devices import Capability, Device, DeviceManager, DeviceProvider
from wls.core.interfaces import Probe, Recorder
from wls.core.state_machine import Command, State
from wls.probes.ble_track import BleTrackProbe
from wls.probes.ping import PingProbe, ping_command
from wls.probes.speed import DEFAULT_DOWN_URL, DEFAULT_UP_URL, SpeedProbe, check_url
from wls.probes.wifi_link import WifiBackend, WifiLinkProbe
from wls.providers.host import LocalHostProvider
from wls.providers.netinfo import default_gateway
from wls.providers.sim import SimProbe, SimProvider, sim_host

TERMINAL = (State.COMPLETED, State.FAILED)


class PlanError(ValueError):
    """The measurement cannot be set up as requested; the message says why."""


@dataclass
class Plan:
    kind: str
    title: str
    probes: tuple[Probe, ...]
    stall_timeout: float
    done: asyncio.Event | None = None  # set by a probe that ends by itself
    notes: tuple[str, ...] = ()
    max_duration: float | None = None  # hard limit even when the caller gives none
    extra_providers: tuple[DeviceProvider, ...] = field(default=())


def wifi_backend() -> WifiBackend | None:
    """Wi-Fi support of this operating system, if any."""
    if sys.platform == "darwin":
        try:
            from wls.providers import wifi_macos
        except ImportError:
            return None
        return wifi_macos.backend()
    return None


def bluetooth_backend() -> BluetoothBackend | None:
    """Bluetooth support of this operating system, if any."""
    if sys.platform == "darwin":
        from wls.providers import bluetooth_macos

        return bluetooth_macos.backend()
    return None


def providers() -> list[DeviceProvider]:
    found: list[DeviceProvider] = [LocalHostProvider()]
    backend = wifi_backend()
    if backend is not None:
        found.append(backend.provider)
    return found


async def pick_wifi(prefix: str, iface: str | None) -> Device:
    manager = DeviceManager(providers())
    devices = [d for d in await manager.refresh() if d.id.startswith(prefix)]
    if iface is not None:
        devices = [d for d in devices if d.id == prefix + iface]
        if not devices:
            raise PlanError(f"no Wi-Fi interface named {iface}")
    if not devices:
        raise PlanError("no Wi-Fi interface found")
    return devices[0]


def _checked_host(host: str) -> str:
    try:
        ping_command(host, 1.0)
    except ValueError as exc:
        raise PlanError(str(exc)) from None
    return host


def plan_ping(host: str, interval: float = 1.0, timeout: float = 1.0) -> Plan:
    probe = PingProbe(_checked_host(host), interval=interval, timeout=timeout)
    return Plan("ping", host, (probe,), interval + timeout + 5.0)


async def plan_wifi(iface: str | None = None, interval: float = 1.0) -> Plan:
    backend = wifi_backend()
    if backend is None:
        raise PlanError(f"Wi-Fi measurement is not supported on {sys.platform} yet")
    make_reader, prefix = backend.link_reader, backend.id_prefix
    device = await pick_wifi(prefix, iface)
    notes = []
    identity = device.support(Capability.WIFI_IDENTITY)
    if not identity.supported:
        notes.append(f"network name is not shown: {identity.reason}")
    reader = make_reader(device.id.removeprefix(prefix))
    probe = WifiLinkProbe(device.id, reader, interval=interval)
    return Plan("wifi", device.name, (probe,), interval + 5.0, notes=tuple(notes))


async def plan_diagnose(target: str = "1.1.1.1", interval: float = 1.0) -> Plan:
    probes: list[Probe] = [PingProbe(_checked_host(target), name="internet", interval=interval)]
    notes = []
    gateway = await asyncio.to_thread(default_gateway)
    if gateway is not None:
        probes.append(PingProbe(gateway, name="router", interval=interval))
    else:
        notes.append("the router address could not be determined")
    backend = wifi_backend()
    if backend is not None:
        make_reader, prefix = backend.link_reader, backend.id_prefix
        try:
            device = await pick_wifi(prefix, None)
        except PlanError:
            device = None
        if device is not None:
            reader = make_reader(device.id.removeprefix(prefix))
            probes.append(WifiLinkProbe(device.id, reader, interval=interval))
    title = "router, internet and Wi-Fi" if len(probes) == 3 else "the connection"
    return Plan("diagnose", title, tuple(probes), interval + 7.0, notes=tuple(notes))


def plan_speed(
    down_url: str = DEFAULT_DOWN_URL, up_url: str = DEFAULT_UP_URL, seconds: float = 5.0
) -> Plan:
    try:
        check_url(down_url)
        check_url(up_url)
    except ValueError as exc:
        raise PlanError(str(exc)) from None
    done = asyncio.Event()
    probe = SpeedProbe(down_url, up_url, phase_seconds=seconds, on_cycle=done.set)
    return Plan(
        "speed",
        f"speed against {urlsplit(down_url).hostname}",
        (probe,),
        15.0,
        done=done,
        notes=("this transfers real data for the whole duration",),
        max_duration=2 * seconds + 30.0,
    )


def plan_bt_track(
    device_id: str, name: str | None = None, backend: BluetoothBackend | None = None
) -> Plan:
    backend = backend if backend is not None else bluetooth_backend()
    if backend is None:
        raise PlanError("Bluetooth is not supported on this system yet")
    if not device_id:
        raise PlanError("a device is required")
    probe = BleTrackProbe(backend.scan, device_id)
    title = name or "a Bluetooth device"
    return Plan("bt-track", title, (probe,), stall_timeout=12.0)


def plan_demo(interval: float = 0.2) -> Plan:
    """A simulated measurement: no network, no hardware."""
    provider = SimProvider([sim_host()])
    probe = SimProbe(provider, name="sim", interval=interval)
    return Plan("demo", "a simulated device", (probe,), interval + 5.0,
                extra_providers=(provider,))  # fmt: skip


async def run_plan(
    plan: Plan,
    recorder: Recorder,
    *,
    duration: float | None = None,
    stop: asyncio.Event | None = None,
) -> State:
    """Prepare, measure until duration / stop / the plan is done / a failure, then finish."""
    stop = stop or asyncio.Event()
    limits = [d for d in (duration, plan.max_duration) if d is not None]
    manager = DeviceManager([*providers(), *plan.extra_providers])
    controller = Controller(manager, recorder)
    config = ExperimentConfig(plan.probes, stall_timeout=plan.stall_timeout)

    controller.submit(Command.PREPARE, config=config)
    state = (await controller.wait_state(State.READY, *TERMINAL, timeout=30)).state
    if state is State.READY:
        controller.submit(Command.START_MEASUREMENT)
        state = (await controller.wait_state(State.MEASURING, *TERMINAL, timeout=30)).state
    if state is State.MEASURING:
        waiters = [
            asyncio.ensure_future(stop.wait()),
            asyncio.ensure_future(controller.wait_state(*TERMINAL, timeout=None)),
        ]
        if plan.done is not None:
            waiters.append(asyncio.ensure_future(plan.done.wait()))
        try:
            await asyncio.wait(
                waiters,
                timeout=min(limits) if limits else None,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for waiter in waiters:
                waiter.cancel()
            controller.submit(Command.STOP)
    return (await controller.wait_state(*TERMINAL, timeout=60)).state
