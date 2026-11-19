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


# ---------- 모드 전환: 실제 명령은 실행하지 않는다(가짜 실행기) ----------
def linux_rig(monkeypatch: pytest.MonkeyPatch, *, root: bool = False, pkexec: bool = True, monitor: str = "yes") -> list[list[str]]:
    found = [adapters._adapter("wifi:wlan1", "wifi", "external", "Wi-Fi", interface="wlan1") | {"abilities": [{"id": "monitor", "state": monitor}]}]
    monkeypatch.setattr(adapters, "list_adapters", lambda force=False: found)
    monkeypatch.setattr(adapters.sys, "platform", "linux")
    have = {"iw", "ip", "nmcli"} | ({"pkexec"} if pkexec else set())
    monkeypatch.setattr(adapters.shutil, "which", lambda name: f"/usr/bin/{name}" if name in have else None)
    monkeypatch.setattr(adapters.os, "geteuid", lambda: 0 if root else 1000, raising=False)
    monkeypatch.setattr(adapters, "current_mode", lambda name: None)
    return []


def test_mode_switch_needs_confirmation_and_a_known_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = linux_rig(monkeypatch)
    run = lambda cmd, timeout=0: (ran.append(cmd), (0, ""))[1]   # noqa: E731
    with pytest.raises(adapters.AdapterError, match="확인"):
        adapters.set_mode("wifi:wlan1", "monitor", False, run)
    with pytest.raises(adapters.AdapterError, match="모드"):
        adapters.set_mode("wifi:wlan1", "ap", True, run)
    with pytest.raises(adapters.AdapterError):
        adapters.set_mode("bt:default", "monitor", True, run)
    assert ran == []


def test_mode_switch_runs_the_shown_commands_through_the_os_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = linux_rig(monkeypatch)
    run = lambda cmd, timeout=0: (ran.append(cmd), (0, ""))[1]   # noqa: E731
    out = adapters.set_mode("wifi:wlan1", "monitor", True, run)
    assert out == {"device": "wifi:wlan1", "mode": "monitor", "changed": True}
    assert ran[0] == ["/usr/bin/nmcli", "device", "set", "wlan1", "managed", "no"]           # NetworkManager 가 되돌리지 않게 먼저
    assert ran[1] == ["pkexec", "sh", "-c", adapters.SWITCH_SH, "sh", "wlan1", "monitor"]   # 이름과 모드는 인수로만 넘어간다
    ran.clear()
    adapters.set_mode("wifi:wlan1", "managed", True, run)
    assert ran[0][:1] == ["pkexec"] and ran[0][-2:] == ["wlan1", "managed"]
    assert ran[1] == ["/usr/bin/nmcli", "device", "set", "wlan1", "managed", "yes"]


def test_mode_switch_as_root_skips_the_prompt_and_reports_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = linux_rig(monkeypatch, root=True)
    adapters.set_mode("wifi:wlan1", "monitor", True, lambda cmd, timeout=0: (ran.append(cmd), (0, ""))[1])
    assert ran[1][0] == "sh"
    with pytest.raises(adapters.AdapterError, match="Operation not supported"):
        adapters.set_mode("wifi:wlan1", "monitor", True, lambda cmd, timeout=0: (1, "command failed: Operation not supported (-95)"))


def test_mode_switch_without_a_prompt_only_shows_the_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = linux_rig(monkeypatch, pkexec=False)
    with pytest.raises(adapters.AdapterError, match="sudo iw dev wlan1 set type monitor"):
        adapters.set_mode("wifi:wlan1", "monitor", True, lambda cmd, timeout=0: (ran.append(cmd), (0, ""))[1])
    assert ran == []
    assert adapters.switch_commands("wlan1", "monitor")[0] == "nmcli device set wlan1 managed no"
    assert adapters.switch_commands("wlan1", "managed")[-1] == "nmcli device set wlan1 managed yes"


def test_mode_switch_cancelled_prompt_and_unsupported_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    linux_rig(monkeypatch)
    with pytest.raises(adapters.AdapterError, match="인증이 취소"):
        adapters.set_mode("wifi:wlan1", "monitor", True, lambda cmd, timeout=0: (126, "") if cmd[0] == "pkexec" else (0, ""))
    linux_rig(monkeypatch, monitor="no")
    with pytest.raises(adapters.AdapterError, match="지원하지 않습니다"):
        adapters.set_mode("wifi:wlan1", "monitor", True, lambda cmd, timeout=0: (0, ""))
    assert adapters.switch_support("yes") == {"how": "pkexec"}
    monkeypatch.setattr(adapters.sys, "platform", "darwin")
    assert adapters.switch_support("yes") == {"how": "no", "reason": "macos"}
    with pytest.raises(adapters.AdapterError, match="macOS"):
        adapters.set_mode("wifi:wlan1", "monitor", True, lambda cmd, timeout=0: (0, ""))


def test_odd_interface_names_never_reach_a_command(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = linux_rig(monkeypatch)
    bad = [adapters._adapter("wifi:x", "wifi", "external", "Wi-Fi", interface="wlan1; rm -rf ~") | {"abilities": []}]
    monkeypatch.setattr(adapters, "list_adapters", lambda force=False: bad)
    with pytest.raises(adapters.AdapterError, match="이름"):
        adapters.set_mode("wifi:x", "monitor", True, lambda cmd, timeout=0: (ran.append(cmd), (0, ""))[1])
    assert ran == []


def test_iw_dev_type_line() -> None:
    assert adapters.parse_iw_dev("Interface wlan1\n\tifindex 4\n\ttype monitor\n\twiphy 1\n") == "monitor"
    assert adapters.parse_iw_dev("") is None


def test_mode_route_refuses_without_confirmation(fake: list[dict[str, Any]]) -> None:
    app = FastAPI()
    adapters.register(app)
    r = TestClient(app).post("/api/adapters/wifi/mode", json={"device": "wifi:en0", "mode": "monitor"})
    assert r.status_code == 400 and "확인" in r.json()["detail"]


# ---------- 권한 안내 ----------
def test_settings_pane_is_opened_not_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []
    monkeypatch.setattr(adapters.sys, "platform", "darwin")
    assert adapters.open_settings("location", lambda cmd, timeout=0: (ran.append(cmd), (0, ""))[1]) == {"opened": "location"}
    assert ran[0][0] == "open" and ran[0][1].endswith("Privacy_LocationServices")     # 설정 창을 여는 것뿐이다(값을 쓰는 명령이 아니다)
    adapters.open_settings("bluetooth", lambda cmd, timeout=0: (ran.append(cmd), (0, ""))[1])
    assert ran[1][1].endswith("Privacy_Bluetooth")
    with pytest.raises(adapters.AdapterError):
        adapters.open_settings("anything-else", lambda cmd, timeout=0: (0, ""))
    monkeypatch.setattr(adapters.sys, "platform", "linux")
    with pytest.raises(adapters.AdapterError, match="대신 열 수 없습니다"):
        adapters.open_settings("location", lambda cmd, timeout=0: (0, ""))


def test_location_is_only_asked_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapters.sys, "platform", "linux")
    assert adapters.location_state() == "unknown"
    with pytest.raises(adapters.AdapterError):
        adapters.ask_location()


def test_location_helper_never_starts_location_updates() -> None:
    """권한만 묻는다. 위치를 읽는 호출은 소스에 없다."""
    src = (Path(adapters.__file__).parent / "mac_location.py").read_text(encoding="utf-8")
    for word in ("startUpdatingLocation", "requestLocation", ".location()", "requestAlwaysAuthorization"):
        assert word not in src


def test_errors_carry_their_status_to_the_route(fake: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    adapters.register(app)
    client = TestClient(app)

    def busy(dev_id: str) -> dict[str, Any]:
        raise adapters.AdapterError("바쁨", 409)

    monkeypatch.setattr(adapters, "wifi_scan", busy)
    assert client.post("/api/adapters/wifi/scan", json={"device": "wifi:en0"}).status_code == 409
    _ble(monkeypatch, -6, "")
    assert client.post("/api/adapters/bluetooth/scan", json={"device": "bt:default", "seconds": 1}).status_code == 403
