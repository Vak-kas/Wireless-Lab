"""컴퓨터의 Wi-Fi·블루투스 어댑터(adapters). 운영체제 명령은 부르지 않고 견본 출력과 가짜로 시험한다."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nrtrail import adapters

NETSH_IF = """
There is 1 interface on the system:

    Name                   : Wi-Fi 2
    Description            : Example USB Wireless Adapter
    GUID                   : 01234567-89ab-cdef-0123-456789abcdef
    Physical address       : 00:11:22:33:44:55
    State                  : connected
"""

# 한국어 Windows 의 모양(이름표는 번역되고 SSID/BSSID 는 그대로)
NETSH_NET = """
인터페이스 이름 : Wi-Fi 2
현재 2개의 네트워크가 표시됩니다.

SSID 1 : lab-ap
    네트워크 종류            : 인프라
    인증                     : WPA2-개인
    암호화                   : CCMP
    BSSID 1                 : 00:AA:BB:CC:DD:01
         신호               : 80%
         송수신 장치 종류   : 802.11ax
         대역               : 5 GHz
         채널               : 36
    BSSID 2                 : 00:AA:BB:CC:DD:02
         신호               : 40%
         송수신 장치 종류   : 802.11n
         채널               : 6

SSID 2 :
    네트워크 종류            : 인프라
    BSSID 1                 : 00:AA:BB:CC:DD:03
         신호               : 10%
         채널               : 11
"""


def test_channel_frequency_per_band() -> None:
    assert adapters.channel_freq_mhz(1, "2.4") == 2412
    assert adapters.channel_freq_mhz(14, "2.4") == 2484
    assert adapters.channel_freq_mhz(36, "5") == 5180
    assert adapters.channel_freq_mhz(1, "6") == 5955
    assert [adapters.band_of(f) for f in (2437, 5180, 5955)] == ["2.4", "5", "6"]
    assert [adapters.channel_of(f) for f in (2437, 2484, 5180, 5955)] == [6, 14, 36, 1]


def test_netsh_interfaces_read_by_position() -> None:
    assert adapters.parse_netsh_interfaces(NETSH_IF) == [{"name": "Wi-Fi 2", "description": "Example USB Wireless Adapter"}]


def test_netsh_networks_in_another_language() -> None:
    rows = adapters.parse_netsh_networks(NETSH_NET)
    assert [(r["ssid"], r["bssid"], r["rssi_dbm"], r["channel"], r["band"]) for r in rows] == [
        ("lab-ap", "00:aa:bb:cc:dd:01", -60, 36, "5"),
        ("lab-ap", "00:aa:bb:cc:dd:02", -80, 6, "2.4"),
        (None, "00:aa:bb:cc:dd:03", -95, 11, "2.4"),
    ]
    assert rows[0]["freq_mhz"] == 5180


def test_nmcli_networks_with_escaped_colons() -> None:
    text = "lab\\:ap:00\\:AA\\:BB\\:CC\\:DD\\:01:36:5180 MHz:70\n:00\\:AA\\:BB\\:CC\\:DD\\:02:1:2412 MHz:30\nbroken line\n"
    rows = adapters.parse_nmcli_networks(text)
    assert [(r["ssid"], r["bssid"], r["channel"], r["band"], r["rssi_dbm"]) for r in rows] == [
        ("lab:ap", "00:aa:bb:cc:dd:01", 36, "5", -65), (None, "00:aa:bb:cc:dd:02", 1, "2.4", -85)]


def test_linux_attach_by_bus(tmp_path: Path) -> None:
    usb = tmp_path / "devices" / "pci0000:00" / "usb1" / "1-2"
    pci = tmp_path / "devices" / "pci0000:00" / "0000:00:14.3"
    usb.mkdir(parents=True)
    pci.mkdir(parents=True)
    assert adapters.linux_attach(usb) == "external"
    assert adapters.linux_attach(pci) == "builtin"


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    found = [adapters._adapter("wifi:en0", "wifi", "builtin", "Wi-Fi", interface="en0"),
             adapters._adapter("bt:default", "bluetooth", "builtin", "Bluetooth")]
    monkeypatch.setattr(adapters, "list_adapters", lambda force=False: found)
    return found


def _ble(monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str) -> None:
    monkeypatch.setattr(adapters.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(adapters.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout=stdout, stderr=""))


def test_ble_scan_sorts_by_strength(fake: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    _ble(monkeypatch, 0, json.dumps({"devices": [{"address": "a", "rssi_dbm": -80}, {"address": "b", "rssi_dbm": -50}]}))
    out = adapters.ble_scan("bt:default", 2)
    assert [d["address"] for d in out["devices"]] == ["b", "a"]


def test_ble_scan_killed_by_os_is_a_permission_message(fake: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    _ble(monkeypatch, -6, "")
    with pytest.raises(adapters.AdapterError, match="블루투스 사용을 막았습니다"):
        adapters.ble_scan("bt:default", 2)


def test_ble_scan_rejects_wrong_device_and_length(fake: list[dict[str, Any]]) -> None:
    with pytest.raises(adapters.AdapterError):
        adapters.ble_scan("wifi:en0", 2)        # Wi-Fi 어댑터로 블루투스를 들을 수 없다
    with pytest.raises(adapters.AdapterError):
        adapters.ble_scan("bt:default", 60)


def test_routes(fake: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    adapters.register(app)
    client = TestClient(app)
    assert [a["id"] for a in client.get("/api/adapters").json()["adapters"]] == ["wifi:en0", "bt:default"]
    assert client.post("/api/adapters/wifi/scan", json={"device": "wifi:nope"}).status_code == 400
    _ble(monkeypatch, 0, json.dumps({"devices": []}))
    assert client.post("/api/adapters/bluetooth/scan", json={"device": "bt:default", "seconds": 1}).json()["devices"] == []


def test_no_transmit_or_connect_calls_in_source() -> None:
    """어댑터 쪽은 듣기만 한다: 연결·쓰기 API 를 부르지 않는다."""
    for name in ("adapters.py", "ble_host.py"):
        src = (Path(adapters.__file__).parent / name).read_text(encoding="utf-8")
        for word in ("BleakClient", "write_gatt", ".connect(", "associateTo", "startIBSS"):
            assert word not in src, f"{name}: {word}"


IW_PHY = "\n".join([
    "Wiphy phy0",
    "\tBand 1:",
    "\t\tCapabilities: 0x19ef",
    "\t\t\tHT20/HT40",
    "\tBand 2:",
    "\t\tVHT Capabilities (0x039071f6):",
    "\t\t\tSupported Channel Width: 160 MHz",
    "\tSupported interface modes:",
    "\t\t * managed",
    "\t\t * AP",
    "\t\t * monitor",
    "\tsoftware interface modes (can always be added):",
    "\t\t * AP/VLAN",
    "",
])


def test_iw_tells_bands_and_monitor_support() -> None:
    assert adapters.parse_iw_phy(IW_PHY) == {"bands": ["2.4", "5"], "monitor": "yes", "max_width_mhz": 160}
    no_monitor = IW_PHY.replace("\t\t * monitor\n", "")
    assert adapters.parse_iw_phy(no_monitor)["monitor"] == "no"
    assert adapters.parse_iw_phy("")["monitor"] == "unknown"       # 못 읽었으면 "안 됨"이 아니라 "알 수 없음"


def test_netsh_monitor_line() -> None:
    assert adapters.parse_netsh_capabilities("    Network monitor mode                         : Supported\n") == "yes"
    assert adapters.parse_netsh_capabilities("    Network monitor mode                         : Not supported\n") == "no"
    assert adapters.parse_netsh_capabilities("    네트워크 모니터 모드 : 지원됨\n") == "unknown"


def test_pcap_question_never_claims_support_for_a_missing_interface() -> None:
    assert adapters.pcap_rfmon("nrtrail-no-such-if0") in ("no", "unknown")


def test_abilities_are_asked_once_and_failures_do_not_hide_the_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def ask(name: str) -> list[dict[str, str]]:
        calls.append(name)
        if name == "bad0":
            raise OSError("boom")
        return [{"id": "monitor", "state": "yes"}]

    monkeypatch.setattr(adapters, "_wifi_abilities", ask)
    monkeypatch.setattr(adapters, "_abilities", {})
    good = adapters._adapter("wifi:ok0", "wifi", "external", "Wi-Fi", interface="ok0")
    assert adapters.abilities(good) == adapters.abilities(good) == [{"id": "monitor", "state": "yes"}]
    assert calls == ["ok0"]
    assert adapters.abilities(adapters._adapter("wifi:bad0", "wifi", "external", "Wi-Fi", interface="bad0")) == []
