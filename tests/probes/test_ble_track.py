# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio

import pytest

from wls.core.bluetooth import BtDevice, BtScan
from wls.measurements import PlanError, plan_bt_track
from wls.probes.ble_track import BleTrackProbe, BluetoothUnavailable


def scans(*results):
    it = iter(results)

    def scan(seconds):
        try:
            return next(it)
        except StopIteration:
            return results[-1]

    return scan


async def collect(probe, count):
    got = []
    done = asyncio.Event()

    def emit(values):
        got.append(dict(values))
        if len(got) >= count:
            done.set()

    task = asyncio.create_task(probe.run(emit))
    try:
        async with asyncio.timeout(5):
            await done.wait()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return got[:count]


async def test_reports_signal_while_the_device_is_heard():
    present = BtScan("on", (BtDevice("A", -55.0, "Watch"), BtDevice("B", -80.0)))
    probe = BleTrackProbe(scans(present), "A", window=0.01)
    assert await collect(probe, 2) == [
        {"heard": 1.0, "rssi_dbm": -55.0},
        {"heard": 1.0, "rssi_dbm": -55.0},
    ]


async def test_reports_not_heard_when_the_device_is_absent():
    first = BtScan("on", (BtDevice("A", -55.0),))
    gone = BtScan("on", (BtDevice("B", -70.0),))
    probe = BleTrackProbe(scans(first, gone), "A", window=0.01)
    assert await collect(probe, 2) == [{"heard": 1.0, "rssi_dbm": -55.0}, {"heard": 0.0}]


async def test_bluetooth_turned_off_stops_the_probe():
    probe = BleTrackProbe(scans(BtScan("off")), "A", window=0.01)
    with pytest.raises(BluetoothUnavailable, match="off"):
        await probe.run(lambda values: None)


def test_plan_requires_a_backend_and_a_device():
    from wls.core.bluetooth import BluetoothBackend

    backend = BluetoothBackend(lambda s: BtScan("on"), lambda: True)
    plan = plan_bt_track("A", "My Watch", backend=backend)
    assert plan.kind == "bt-track" and plan.title == "My Watch"
    assert plan.probes[0].target_id == "A"

    with pytest.raises(PlanError):
        plan_bt_track("", backend=backend)
