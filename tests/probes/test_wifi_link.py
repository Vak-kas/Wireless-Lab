# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import sys

import pytest

from wls.analysis.summary import summarize_metric
from wls.cli import format_wifi, main
from wls.core.devices import Capability
from wls.core.storage import read_run, verify_run
from wls.probes.wifi_link import LinkReading, WifiLinkProbe


def test_reading_values_include_snr_and_skip_unknowns():
    full = LinkReading(-50, -90, 866.0, 36, 5.0, 80).values()
    assert full == {
        "associated": 1.0,
        "rssi_dbm": -50.0,
        "noise_dbm": -90.0,
        "snr_db": 40.0,
        "tx_rate_mbps": 866.0,
        "channel": 36.0,
        "band_ghz": 5.0,
        "width_mhz": 80.0,
    }
    assert LinkReading(-70).values() == {"associated": 1.0, "rssi_dbm": -70.0}


async def test_probe_reports_connection_loss_as_a_sample_not_an_error():
    readings = iter([LinkReading(-50, -90), None, LinkReading(-60, -90)])
    got: list[dict] = []
    done = asyncio.Event()

    def emit(values):
        got.append(dict(values))
        if len(got) == 3:
            done.set()

    probe = WifiLinkProbe("wifi:test0", lambda: next(readings), interval=0.001)
    task = asyncio.create_task(probe.run(emit))
    async with asyncio.timeout(5):
        await done.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert [v["associated"] for v in got] == [1.0, 0.0, 1.0]
    assert got[0]["snr_db"] == 40.0 and "rssi_dbm" not in got[1]


def test_live_line_formatting():
    assert format_wifi({"associated": 0.0}) == "not connected"
    line = format_wifi(LinkReading(-50, -90, 866.0, 36, 5.0, 80).values())
    assert line == "rssi  -50 dBm  snr  40 dB  ch 36 (5 GHz, 80 MHz)  866 Mbps"
    assert format_wifi(LinkReading(-70).values()) == "rssi  -70 dBm"


def test_metric_summary():
    rows = [(1, "wifi", "rssi_dbm", -50.0), (2, "wifi", "rssi_dbm", -60.0), (3, "x", "y", 1.0)]
    s = summarize_metric(rows, "wifi", "rssi_dbm")
    assert (s.count, s.min, s.avg, s.max) == (2, -60.0, -55.0, -50.0)
    assert summarize_metric(rows, "wifi", "missing").count == 0


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS has a Wi-Fi backend")
def test_wifi_command_says_when_the_os_is_not_supported_yet(capsys, tmp_path):
    assert main(["wifi", "--duration", "0.1", "--out", str(tmp_path)]) == 1
    assert "not supported" in capsys.readouterr().err


# --- macOS ------------------------------------------------------------------------

macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


@macos
def test_macos_raw_numbers_are_converted():
    from wls.providers.wifi_macos import to_reading

    assert to_reading(0, 0, 0.0, None, None, None) is None  # not connected
    reading = to_reading(-29, -82, 2401.0, 40, 2, 4)
    assert reading == LinkReading(-29.0, -82.0, 2401.0, 40, 5.0, 160)
    assert to_reading(-60, 0, 0.0, 6, 1, 1) == LinkReading(-60.0, None, None, 6, 2.4, 20)


@macos
async def test_macos_interfaces_are_discovered_with_honest_capabilities():
    from wls.providers.wifi_macos import MacWifiProvider

    devices = await MacWifiProvider().discover()
    if not devices:
        pytest.skip("this Mac has no Wi-Fi interface")
    device = devices[0]
    assert device.id.startswith("wifi:")
    assert device.support(Capability.WIFI_LINK_INFO).supported
    assert not device.support(Capability.WIFI_INJECT).supported
    identity = device.support(Capability.WIFI_IDENTITY)
    assert identity.supported or identity.reason


@macos
def test_macos_wifi_command_measures_and_saves(capsys, tmp_path):
    code = main(["wifi", "--duration", "0.35", "--interval", "0.1", "--out", str(tmp_path)])
    captured = capsys.readouterr()
    if "no Wi-Fi interface" in captured.err:
        pytest.skip("this Mac has no Wi-Fi interface")
    assert code == 0, captured
    (run,) = tmp_path.glob("*-wifi.sqlite")
    assert verify_run(run).intact
    _, samples = read_run(run)
    assert summarize_metric(samples, "wifi", "associated").count >= 2
