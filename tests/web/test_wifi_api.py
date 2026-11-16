# SPDX-License-Identifier: GPL-3.0-or-later
import sys

import pytest
from fastapi.testclient import TestClient

from wls.probes.wifi_link import LinkReading, ScanEntry, WifiBackend
from wls.providers.sim import SimProvider, sim_wifi_nic
from wls.web.app import create_app


def backend(reading=LinkReading(-48, -90, 866.0, 36, 5.0, 80), entries=None, fail=False):
    provider = SimProvider([sim_wifi_nic("wifi:test0")])

    def scanner(interface):
        def scan():
            if fail:
                raise RuntimeError("Wi-Fi scan failed: busy")
            return entries if entries is not None else [
                ScanEntry(-40.0, "home", "aa:bb:cc:dd:ee:ff", 36, 5.0, 80, "WPA2"),
                ScanEntry(-75.0, "cafe", None, 1, 2.4, 20, "open"),
            ]

        return scan

    return WifiBackend(provider, lambda interface: (lambda: reading), scanner, "wifi:")


def client(tmp_path, wifi):
    return TestClient(create_app(tmp_path, lambda: [], wifi=wifi))


def test_current_signal_is_reported(tmp_path):
    now = client(tmp_path, backend()).get("/api/wifi").json()
    assert now["supported"] is True and now["interface"] == "test0"
    assert now["link"]["rssi_dbm"] == -48.0 and now["link"]["channel"] == 36.0
    assert now["names_available"] is True


def test_not_connected_is_reported_without_an_error(tmp_path):
    now = client(tmp_path, backend(reading=None)).get("/api/wifi").json()
    assert now["supported"] is True and now["link"] is None


def test_system_without_wifi_support_says_so(tmp_path):
    now = client(tmp_path, None).get("/api/wifi").json()
    assert now["supported"] is False and now["reason"]
    assert client(tmp_path, None).get("/api/wifi/scan").status_code == 404


def test_scan_lists_networks(tmp_path):
    result = client(tmp_path, backend()).get("/api/wifi/scan").json()
    assert [n["ssid"] for n in result["networks"]] == ["home", "cafe"]
    assert result["networks"][1]["security"] == "open"
    assert result["names_hidden"] is False


def test_scan_says_when_the_os_hides_every_name(tmp_path):
    hidden = [ScanEntry(-40.0, None, None, 36, 5.0, 80, "WPA3"), ScanEntry(-60.0, None, None, 1, 2.4, 20, "")]
    result = client(tmp_path, backend(entries=hidden)).get("/api/wifi/scan").json()
    assert result["names_hidden"] is True and len(result["networks"]) == 2


def test_empty_scan_is_not_reported_as_hidden_names(tmp_path):
    result = client(tmp_path, backend(entries=[])).get("/api/wifi/scan").json()
    assert result == {"networks": [], "names_hidden": False, "names_reason": ""}


def test_failed_scan_is_a_503_with_the_reason(tmp_path):
    response = client(tmp_path, backend(fail=True)).get("/api/wifi/scan")
    assert response.status_code == 503 and "busy" in response.json()["detail"]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_macos_security_labels():
    from wls.providers.wifi_macos import security_label

    assert security_label({0}) == "open"
    assert security_label({1}) == "WEP"
    assert security_label({4, 5}) == "WPA2"
    assert security_label({5, 11, 13}) == "WPA2/WPA3"
    assert security_label({11}) == "WPA3"
    assert security_label({8, 9, 10}) == "enterprise"
    assert security_label(set()) == ""


def test_current_network_name_is_included_when_the_backend_knows_it(tmp_path):
    from dataclasses import replace

    known = replace(backend(), identity=lambda interface: ("home", "aa:bb:cc:dd:ee:ff"))
    now = client(tmp_path, known).get("/api/wifi").json()
    assert (now["ssid"], now["bssid"]) == ("home", "aa:bb:cc:dd:ee:ff")
    assert client(tmp_path, backend()).get("/api/wifi").json()["ssid"] is None


def test_names_setup_runs_the_backend_setup(tmp_path):
    from dataclasses import replace

    calls = []
    ready = replace(backend(), names_setup=lambda: calls.append(1) or "authorized")
    assert client(tmp_path, ready).get("/api/wifi").json()["can_setup_names"] is True
    assert client(tmp_path, ready).post("/api/wifi/names").json() == {"status": "authorized"}
    assert calls == [1]


def test_names_setup_is_absent_where_it_is_not_needed(tmp_path):
    assert client(tmp_path, backend()).get("/api/wifi").json()["can_setup_names"] is False
    assert client(tmp_path, backend()).post("/api/wifi/names").status_code == 404


def test_names_setup_failure_is_reported(tmp_path):
    from dataclasses import replace

    def failing():
        raise RuntimeError("the Swift compiler was not found")

    response = client(tmp_path, replace(backend(), names_setup=failing)).post("/api/wifi/names")
    assert response.status_code == 503 and "Swift" in response.json()["detail"]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_macos_helper_scan_answer_is_converted():
    from wls.providers.wifi_macos import entries_from_helper

    answer = {
        "location": "authorized",
        "networks": [
            {"rssi": -70, "ssid": "cafe", "bssid": None, "channel": 1, "band": 1, "width": 1,
             "security": [0]},
            {"rssi": -40, "ssid": "home", "bssid": "aa:bb:cc:dd:ee:ff", "channel": 36, "band": 2,
             "width": 3, "security": [5, 11, 13]},
        ],
    }  # fmt: skip
    assert entries_from_helper(answer) == [
        ScanEntry(-40.0, "home", "aa:bb:cc:dd:ee:ff", 36, 5.0, 80, "WPA2/WPA3"),
        ScanEntry(-70.0, "cafe", None, 1, 2.4, 20, "open"),
    ]
    assert entries_from_helper({"networks": []}) == []
