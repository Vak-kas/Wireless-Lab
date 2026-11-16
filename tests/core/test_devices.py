# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from wls.core.devices import Capability, DeviceManager, Support
from wls.providers.sim import SimProvider, sim_host, sim_sdr, sim_wifi_nic


def test_card_with_monitor_mode_can_run_monitor_features():
    card = sim_wifi_nic(standard="ax", monitor=True)
    assert card.check({Capability.WIFI_SCAN, Capability.WIFI_MONITOR}).supported


def test_card_without_monitor_mode_says_why():
    support = sim_wifi_nic(standard="n", monitor=False).check({Capability.WIFI_MONITOR})
    assert not support.supported
    assert "monitor mode" in support.reason


def test_only_the_missing_capability_is_reported():
    card = sim_wifi_nic(monitor=True, inject=False)
    support = card.check({Capability.WIFI_MONITOR, Capability.WIFI_INJECT})
    assert not support.supported
    assert "wifi_inject" in support.reason
    assert "wifi_monitor" not in support.reason


def test_sdr_can_receive_but_transmit_is_reported_unavailable():
    sdr = sim_sdr(model="USRP B210")
    assert sdr.check({Capability.SDR_RX}).supported
    assert not sdr.check({Capability.SDR_TX}).supported
    assert sdr.details["model"] == "USRP B210"


def test_capability_a_device_never_mentioned_is_unsupported_with_a_reason():
    support = sim_host().support(Capability.GNSS_RAW)
    assert not support.supported and support.reason


def test_unsupported_without_a_reason_cannot_be_built():
    with pytest.raises(ValueError):
        Support(False)


async def test_manager_tells_which_connected_devices_can_run_a_feature():
    provider = SimProvider([sim_host(), sim_wifi_nic(monitor=True), sim_sdr()])
    manager = DeviceManager([provider])
    await manager.refresh()

    usable = {d.id: s.supported for d, s in manager.usable_for({Capability.WIFI_MONITOR})}
    assert usable == {"sim-host": False, "sim-wlan0": True, "sim-sdr0": False}


async def test_plugging_and_unplugging_shows_up_after_refresh():
    provider = SimProvider([sim_host()])
    manager = DeviceManager([provider])
    await manager.refresh()
    assert manager.get("sim-sdr0") is None

    provider.plug(sim_sdr())
    await manager.refresh()
    assert manager.get("sim-sdr0") is not None

    provider.unplug("sim-sdr0")
    await manager.refresh()
    assert manager.get("sim-sdr0") is None


async def test_a_broken_provider_does_not_hide_other_devices():
    class Broken:
        name = "broken"

        async def discover(self):
            raise OSError("driver crashed")

    manager = DeviceManager([Broken(), SimProvider([sim_host()])])
    devices = await manager.refresh()
    assert [d.id for d in devices] == ["sim-host"]
    assert "driver crashed" in manager.provider_errors["broken"]
