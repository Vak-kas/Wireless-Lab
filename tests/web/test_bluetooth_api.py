# SPDX-License-Identifier: GPL-3.0-or-later
import sys

import pytest
from fastapi.testclient import TestClient

from wls.core.bluetooth import BluetoothBackend, BtDevice, BtScan, maker_name
from wls.web.app import create_app


def backend(*, ready=True, state="on", fail=False, setup="on"):
    asked = []

    def scan(seconds):
        asked.append(seconds)
        if fail:
            raise RuntimeError("the helper did not answer")
        return BtScan(state, (
            BtDevice("A1", -45.0, "Headphones", "Sony", True, ("180F",)),
            BtDevice("B2", -80.0),
        ))  # fmt: skip

    made = BluetoothBackend(scan, lambda: ready, (lambda: setup) if setup else None)
    return made, asked


def client(tmp_path, bluetooth):
    return TestClient(create_app(tmp_path, lambda: [], wifi=None, bluetooth=bluetooth))


def test_status_reports_ready_or_needing_setup(tmp_path):
    assert client(tmp_path, backend()[0]).get("/api/bluetooth").json() == {
        "supported": True, "ready": True, "can_setup": True, "reason": "",
    }  # fmt: skip
    assert client(tmp_path, backend(ready=False)[0]).get("/api/bluetooth").json()["ready"] is False


def test_unsupported_system_says_so(tmp_path):
    c = client(tmp_path, None)
    assert c.get("/api/bluetooth").json()["supported"] is False
    assert c.get("/api/bluetooth/scan").status_code == 404
    assert c.post("/api/bluetooth/setup").status_code == 404


def test_scan_lists_devices_strongest_first_as_given(tmp_path):
    made, asked = backend()
    result = client(tmp_path, made).get("/api/bluetooth/scan?seconds=3").json()
    assert asked == [3.0]
    assert result["state"] == "on"
    assert result["devices"][0] == {
        "id": "A1", "rssi_dbm": -45.0, "name": "Headphones", "maker": "Sony",
        "connectable": True, "services": ["180F"],
    }  # fmt: skip
    assert result["devices"][1]["name"] is None


def test_scan_before_setup_is_refused(tmp_path):
    made, asked = backend(ready=False)
    assert client(tmp_path, made).get("/api/bluetooth/scan").status_code == 409
    assert asked == []


@pytest.mark.parametrize("seconds", ["0", "31", "abc"])
def test_scan_length_is_limited(tmp_path, seconds):
    made, asked = backend()
    assert client(tmp_path, made).get(f"/api/bluetooth/scan?seconds={seconds}").status_code == 422
    assert asked == []


def test_bluetooth_turned_off_is_a_state_not_an_error(tmp_path):
    result = client(tmp_path, backend(state="off")[0]).get("/api/bluetooth/scan").json()
    assert result["state"] == "off"


def test_failed_scan_is_a_503(tmp_path):
    assert client(tmp_path, backend(fail=True)[0]).get("/api/bluetooth/scan").status_code == 503


def test_setup_returns_the_state(tmp_path):
    assert client(tmp_path, backend()[0]).post("/api/bluetooth/setup").json() == {"state": "on"}


def test_maker_names():
    assert maker_name(0x004C) == "Apple"
    assert maker_name(0xFFFF) is None and maker_name(None) is None


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_macos_helper_answer_is_converted():
    from wls.providers.bluetooth_macos import scan_from_helper

    answer = {"bluetooth": "on", "devices": [
        {"id": "X", "rssi": -70, "seen": 3},
        {"id": "Y", "rssi": -40, "name": "Watch", "company": 76, "connectable": True,
         "services": ["180D"], "seen": 9},
        {"id": "Z", "seen": 1},
    ]}  # fmt: skip
    result = scan_from_helper(answer)
    assert result.state == "on"
    assert result.devices == (
        BtDevice("Y", -40.0, "Watch", "Apple", True, ("180D",)),
        BtDevice("X", -70.0),
    )
    assert scan_from_helper({"bluetooth": "unauthorized"}) == BtScan("unauthorized")
