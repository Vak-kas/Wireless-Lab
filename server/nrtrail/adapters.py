"""컴퓨터의 무선 어댑터(Wi-Fi, 블루투스)를 장비로 다룬다. SDR 과 달리 전파 자체(IQ)가 아니라 칩이 풀어 준 결과만 준다.

구조

    list_adapters() ─▶ 이 운영체제(this_os())에 물어 어댑터 목록 ─▶ 능력(abilities)과 지금 모드를 붙인다
    wifi_scan()     ─▶ 이 운영체제의 방법으로 주변 망 찾기 ─▶ 같은 모양의 결과
    ble_scan()      ─▶ 따로 띄운 프로세스(ble_host)가 광고를 듣는다

- **운영체제마다 묻는 법이 다르다.** 그 차이는 Os 의 세 갈래(MacOs, WindowsOs, LinuxOs)에만 있고, 나머지 코드는 운영체제를 모른다.
  각 갈래는 같은 세 가지에 답한다: list()(어떤 어댑터가 있나), wifi_scan()(주변 망), wifi_facts()(대역·폭·규격·모니터 모드).
- **어댑터가 주는 것은 SDR 과 다르다.** SDR(devices.py)은 IQ 샘플을, 어댑터는 칩이 풀어 준 결과(망 목록, 광고)를 준다.
  모니터 모드로 받는 프레임은 세 번째 종류가 된다(아직 읽는 기능은 없다. 모드 전환만 있다).

- 받는 것은 **방송 정보뿐**이다: Wi-Fi 는 운영체제의 주변 망 찾기 결과(비콘), 블루투스는 BLE 광고. 연결하지 않고, 아무것도 보내지 않는다.
- 내장(builtin)·외장(external) 은 운영체제가 알려 주는 연결 방식으로 가린다. 모르면 unknown.
- 관리자 권한이 필요한 일(모니터 모드 켜기 등)은 하지 않는다. 다만 어댑터가 **무엇을 할 수 있는지**는 묻기만 해서 보여 준다(abilities):
  받을 수 있는 대역·폭·규격, 모니터 모드를 지원하는지(libpcap 의 pcap_can_set_rfmon, Linux 는 iw), 지금 권한으로 프레임을 잡을 수 있는지.
- macOS: Wi-Fi 는 CoreWLAN(pyobjc), 블루투스는 bleak. 망 이름·주소는 위치 권한을 준 프로그램에만 보인다.
  Windows: netsh / Linux: nmcli 로 읽는다.
- **모드 전환**(일반 ↔ 모니터)은 사람이 화면에서 누르고 확인했을 때만 한다(set_mode). Linux 에서만 된다: `ip link` 와 `iw` 로 바꾸고,
  관리자 권한이 필요하면 운영체제의 인증 창(pkexec)에 맡긴다 — 이 도구는 암호를 받지도 보지도 않는다. 인증 창을 쓸 수 없으면
  직접 실행할 명령을 알려 준다. macOS 는 캡처하는 동안에만 모니터 모드가 켜지는 방식이라 미리 바꿔 둘 수 없고, Windows 는 지원하지 않는다.
- 블루투스 찾기는 따로 띄운 프로세스(ble_host)에서 한다. macOS 는 블루투스 권한이 없는 프로그램을 그 자리에서 끝내 버리기 때문에
  서버 안에서 직접 부르면 서버가 같이 죽는다.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

CACHE_S = 30.0
EBUSY = 16                  # CoreWLAN 이 "리소스 사용 중"으로 돌려주는 오류 번호(errno EBUSY)
SCAN_TRIES = 3
SCAN_RETRY_S = 2.0
LOCATION_WAIT_S = 60.0      # 권한 창에서 사용자가 고르기를 기다리는 시간
SETTINGS = {
    "darwin": {"location": ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_LocationServices"],
               "bluetooth": ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Bluetooth"]},
    "win32": {"location": ["cmd", "/c", "start", "ms-settings:privacy-location"],
              "bluetooth": ["cmd", "/c", "start", "ms-settings:bluetooth"]},
}
WIFI_PREFIX, BT_PREFIX = "wifi:", "bt:"
BLE_MAX_S = 10.0


class AdapterError(RuntimeError):
    """사용자에게 그대로 보여줄 문구. status: 400 일반, 403 운영체제 권한이 없음, 409 잠깐 바쁨(다시 하면 됨)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _run(cmd: list[str], timeout: float = 20.0) -> str:
    """명령의 출력. 없거나 실패하면 빈 문자열."""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if p.returncode != 0:
        return ""
    for enc in ("utf-8", "cp949", "mbcs"):
        try:
            return p.stdout.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return p.stdout.decode("utf-8", errors="replace")


def _adapter(dev_id: str, kind: str, attach: str, label: str, **detail: Any) -> dict[str, Any]:
    return {"id": dev_id, "kind": kind, "attach": attach, "label": label,
            "detail": {k: v for k, v in detail.items() if v not in (None, "", [])}}


# ---------- 채널·대역 ----------
def band_of(freq_mhz: float) -> str:
    return "2.4" if freq_mhz < 3000 else "5" if freq_mhz < 5925 else "6"


def channel_freq_mhz(channel: int, band: str) -> float:
    """채널 번호 → 가운데 주파수 (IEEE 802.11-2020 17.3.8.4.2, 19.3.15.2 / 802.11ax 27.3.23.2)."""
    if band == "2.4":
        return 2484.0 if channel == 14 else 2407.0 + 5 * channel
    if band == "6":
        return 5950.0 + 5 * channel
    return 5000.0 + 5 * channel


def channel_of(freq_mhz: float) -> int:
    if freq_mhz == 2484:
        return 14
    base = 2407 if freq_mhz < 3000 else 5950 if freq_mhz >= 5925 else 5000
    return round((freq_mhz - base) / 5)


# ---------- macOS ----------
def _corewlan() -> Any:
    if importlib.util.find_spec("CoreWLAN") is None:
        return None
    return importlib.import_module("CoreWLAN")


_MAC_BAND = {1: "2.4", 2: "5", 3: "6"}
_MAC_WIDTH = {1: 20, 2: 40, 3: 80, 4: 160}


def _mac_list() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cw = _corewlan()
    if cw is not None:
        for itf in cw.CWWiFiClient.sharedWiFiClient().interfaces() or []:
            name = str(itf.interfaceName())
            # macOS 가 스스로 지원하는 Wi-Fi 는 내장 카드뿐이다(외장 USB 랜카드는 따로 드라이버가 있어야 하고 여기 안 잡힌다)
            out.append(_adapter(f"{WIFI_PREFIX}{name}", "wifi", "builtin", "Wi-Fi", interface=name, power=bool(itf.powerOn())))
    else:
        ports = _run(["networksetup", "-listallhardwareports"])
        for m in re.finditer(r"Hardware Port: (Wi-Fi|AirPort)\s+Device: (\S+)", ports):
            out.append(_adapter(f"{WIFI_PREFIX}{m.group(2)}", "wifi", "builtin", "Wi-Fi", interface=m.group(2)))
    raw = _run(["system_profiler", "SPBluetoothDataType", "-json"], 30)
    try:
        ctl = json.loads(raw)["SPBluetoothDataType"][0].get("controller_properties", {})
    except (ValueError, KeyError, IndexError):
        ctl = {}
    if ctl:
        usb = "usb" in str(ctl.get("controller_transport", "")).lower()
        out.append(_adapter(f"{BT_PREFIX}default", "bluetooth", "external" if usb else "builtin", "Bluetooth",
                            chipset=str(ctl.get("controller_chipset", "")).replace("_", " "),
                            power=ctl.get("controller_state") == "attrib_on"))
    return out


def _mac_wifi_scan(name: str) -> dict[str, Any]:
    cw = _corewlan()
    if cw is None:
        raise AdapterError("이 컴퓨터의 Wi-Fi 를 읽는 데 필요한 패키지(pyobjc-framework-CoreWLAN)가 없습니다.")
    itf = cw.CWWiFiClient.sharedWiFiClient().interfaceWithName_(name)
    if itf is None:
        raise AdapterError(f"Wi-Fi 장비를 찾지 못했습니다: {name}")
    if not itf.powerOn():
        raise AdapterError("Wi-Fi 가 꺼져 있습니다. 켠 뒤 다시 시도하세요.")
    nets, err = None, None
    for attempt in range(SCAN_TRIES):
        nets, err = itf.scanForNetworksWithName_error_(None, None)
        if err is None or int(err.code()) != EBUSY:
            break
        if attempt < SCAN_TRIES - 1:
            time.sleep(SCAN_RETRY_S)                  # 운영체제가 스스로 찾는 중이면 "리소스 사용 중"이 난다. 잠깐 뒤 다시 한다
    if err is not None:
        if int(err.code()) == EBUSY:
            raise AdapterError("Wi-Fi 가 지금 다른 찾기를 하고 있습니다. 잠시 뒤 다시 찾습니다.", 409)
        raise AdapterError(f"주변 Wi-Fi 를 찾지 못했습니다: {err.localizedDescription()}")
    rows = []
    for n in nets or []:
        ch = n.wlanChannel()
        band = _MAC_BAND.get(int(ch.channelBand()), "")
        rows.append({"ssid": None if n.ssid() is None else str(n.ssid()), "bssid": None if n.bssid() is None else str(n.bssid()),
                     "rssi_dbm": int(n.rssiValue()), "channel": int(ch.channelNumber()), "band": band,
                     "width_mhz": _MAC_WIDTH.get(int(ch.channelWidth())),
                     "freq_mhz": channel_freq_mhz(int(ch.channelNumber()), band) if band else None})
    cur = itf.wlanChannel()
    current = None
    if cur is not None and int(itf.rssiValue()) != 0:
        current = {"channel": int(cur.channelNumber()), "band": _MAC_BAND.get(int(cur.channelBand()), ""),
                   "width_mhz": _MAC_WIDTH.get(int(cur.channelWidth())), "rssi_dbm": int(itf.rssiValue()),
                   "noise_dbm": int(itf.noiseMeasurement())}
    return {"networks": rows, "current": current}


# ---------- Windows ----------
def parse_netsh_interfaces(text: str) -> list[dict[str, str]]:
    """`netsh wlan show interfaces` — 표시 언어에 따라 이름표가 달라서, 블록의 첫 줄(이름)과 둘째 줄(설명)을 자리로 읽는다."""
    out = []
    for block in re.split(r"\r?\n\s*\r?\n", text):
        pairs = [m.groups() for m in re.finditer(r"^\s{2,}(\S[^:\r\n]*?)\s*:\s(.*?)\s*$", block, re.M)]
        if len(pairs) >= 2 and any(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}", v) for _, v in pairs):
            out.append({"name": pairs[0][1], "description": pairs[1][1]})
    return out


def parse_netsh_networks(text: str) -> list[dict[str, Any]]:
    """`netsh wlan show networks mode=bssid` — SSID/BSSID 줄은 어느 언어에서나 그대로이고, 나머지는 값의 모양으로 읽는다
    (신호는 '80%', 채널은 BSSID 아래에서 처음 나오는 정수 한 개짜리 값)."""
    rows: list[dict[str, Any]] = []
    ssid: str | None = None
    row: dict[str, Any] | None = None
    for line in text.splitlines():
        m = re.match(r"^SSID \d+\s*:\s?(.*)$", line.strip())
        if m and not line.startswith(" "):
            ssid, row = m.group(1).strip() or None, None
            continue
        m = re.match(r"^\s+BSSID \d+\s*:\s*([0-9a-fA-F:]{17})", line)
        if m:
            row = {"ssid": ssid, "bssid": m.group(1).lower(), "rssi_dbm": None, "channel": None, "band": "", "width_mhz": None, "freq_mhz": None}
            rows.append(row)
            continue
        if row is None or ":" not in line:
            continue
        value = line.split(":", 1)[1].strip()
        if (m := re.fullmatch(r"(\d+)\s*%", value)) and row["rssi_dbm"] is None:
            row["rssi_dbm"] = round(int(m.group(1)) / 2 - 100)      # Windows 의 신호 품질(%) → dBm 근사 (WLAN_ASSOCIATION_ATTRIBUTES 설명)
        elif (m := re.fullmatch(r"(2\.4|5|6)\s*GHz", value)):
            row["band"] = m.group(1)
        elif re.fullmatch(r"\d{1,3}", value) and row["channel"] is None:
            row["channel"] = int(value)
    for r in rows:
        if r["channel"] is not None:
            r["band"] = r["band"] or ("2.4" if r["channel"] <= 14 else "5")
            r["freq_mhz"] = channel_freq_mhz(r["channel"], r["band"])
    return rows


def _win_list() -> list[dict[str, Any]]:
    out = []
    for itf in parse_netsh_interfaces(_run(["netsh", "wlan", "show", "interfaces"])):
        attach = "external" if "usb" in itf["description"].lower() else "unknown"
        out.append(_adapter(f"{WIFI_PREFIX}{itf['name']}", "wifi", attach, itf["description"] or "Wi-Fi", interface=itf["name"]))
    if importlib.util.find_spec("bleak") is not None:
        out.append(_adapter(f"{BT_PREFIX}default", "bluetooth", "unknown", "Bluetooth"))
    return out


# ---------- Linux ----------
def parse_nmcli_networks(text: str) -> list[dict[str, Any]]:
    """`nmcli -t -f SSID,BSSID,CHAN,FREQ,SIGNAL dev wifi list` — 값 안의 ':' 는 '\\:' 로 적혀 나온다."""
    rows = []
    for line in text.splitlines():
        parts = [p.replace("\\:", ":").replace("\\\\", "\\") for p in re.split(r"(?<!\\):", line)]
        if len(parts) < 5:
            continue
        ssid, bssid, chan, freq, signal = parts[:5]
        try:
            f = float(freq.split()[0])
            rows.append({"ssid": ssid or None, "bssid": bssid.lower() or None, "rssi_dbm": round(int(signal) / 2 - 100),
                         "channel": int(chan), "band": band_of(f), "width_mhz": None, "freq_mhz": f})
        except (ValueError, IndexError):
            continue
    return rows


def linux_attach(sys_device: Path) -> str:
    """/sys/class/.../device 가 USB 버스 아래면 외장으로 본다(노트북 내장 블루투스도 안에서는 USB 인 경우가 있어 블루투스는 unknown)."""
    try:
        return "external" if "/usb" in str(sys_device.resolve()) else "builtin"
    except OSError:
        return "unknown"


def _linux_list() -> list[dict[str, Any]]:
    out = []
    for p in sorted(Path("/sys/class/net").glob("*/wireless")):
        name = p.parent.name
        out.append(_adapter(f"{WIFI_PREFIX}{name}", "wifi", linux_attach(p.parent / "device"), "Wi-Fi", interface=name))
    for p in sorted(Path("/sys/class/bluetooth").glob("hci*")):
        out.append(_adapter(f"{BT_PREFIX}{p.name}", "bluetooth", "unknown", "Bluetooth", interface=p.name))
    return out


# ---------- 운영체제별 묶음 ----------
class Os:
    """운영체제 하나가 어댑터에 대해 답하는 법. 갈래마다 아래 세 가지를 채운다."""

    def list(self) -> list[dict[str, Any]]:
        """이 컴퓨터의 Wi-Fi·블루투스 어댑터."""
        raise NotImplementedError

    def wifi_scan(self, name: str) -> dict[str, Any]:
        """주변 망 찾기: {"networks": [...], "current": 지금 이어진 망 또는 None}."""
        raise NotImplementedError

    def wifi_facts(self, name: str) -> dict[str, Any]:
        """어댑터가 할 수 있는 일: bands, width, standards, monitor(yes/no/unknown), capture(yes/admin/unknown). 모르는 것은 뺀다."""
        return {}


class MacOs(Os):
    """macOS: Wi-Fi 는 CoreWLAN, 규격은 system_profiler, 모니터 모드는 libpcap 에 묻는다."""

    def list(self) -> list[dict[str, Any]]:
        return _mac_list()

    def wifi_scan(self, name: str) -> dict[str, Any]:
        return _mac_wifi_scan(name)

    def wifi_facts(self, name: str) -> dict[str, Any]:
        facts: dict[str, Any] = {}
        cw = _corewlan()
        itf = cw.CWWiFiClient.sharedWiFiClient().interfaceWithName_(name) if cw is not None else None
        if itf is not None:
            chans = list(itf.supportedWLANChannels() or [])
            facts["bands"] = [b for k, b in sorted(_MAC_BAND.items()) if any(int(c.channelBand()) == k for c in chans)]
            facts["width"] = max((_MAC_WIDTH.get(int(c.channelWidth()), 0) for c in chans), default=0) or None
        try:
            port = json.loads(_run(["system_profiler", "SPAirPortDataType", "-json"], 30))["SPAirPortDataType"][0]
            facts["standards"] = next((str(i.get("spairport_supported_phymodes", "")) for i in port.get("spairport_airport_interfaces", [])
                                       if i.get("_name") == name), "")
        except (ValueError, KeyError, IndexError):
            pass
        facts["monitor"] = pcap_rfmon(name)
        facts["capture"] = "yes" if os.access("/dev/bpf0", os.R_OK) else "admin"      # 프레임을 잡으려면 bpf 장치를 열 수 있어야 한다
        return facts


class WindowsOs(Os):
    """Windows: netsh 의 출력을 읽는다."""

    def list(self) -> list[dict[str, Any]]:
        return _win_list()

    def wifi_scan(self, name: str) -> dict[str, Any]:
        text = _run(["netsh", "wlan", "show", "networks", "mode=bssid"], 30)
        if not text:
            raise AdapterError("주변 Wi-Fi 를 읽지 못했습니다(netsh). Wi-Fi 와 위치 서비스가 켜져 있는지 확인하세요.")
        return {"networks": parse_netsh_networks(text), "current": None}

    def wifi_facts(self, name: str) -> dict[str, Any]:
        return {"monitor": parse_netsh_capabilities(_run(["netsh", "wlan", "show", "wirelesscapabilities"]))}


class LinuxOs(Os):
    """Linux: 어댑터는 sysfs, 주변 망은 NetworkManager(nmcli), 능력은 iw 에 묻는다."""

    def list(self) -> list[dict[str, Any]]:
        return _linux_list()

    def wifi_scan(self, name: str) -> dict[str, Any]:
        if not shutil.which("nmcli"):
            raise AdapterError("주변 Wi-Fi 를 읽으려면 NetworkManager(nmcli)가 필요합니다.")
        text = _run(["nmcli", "-t", "-f", "SSID,BSSID,CHAN,FREQ,SIGNAL", "dev", "wifi", "list", "ifname", name], 30)
        return {"networks": parse_nmcli_networks(text), "current": None}

    def wifi_facts(self, name: str) -> dict[str, Any]:
        try:
            phy = (Path("/sys/class/net") / name / "phy80211" / "name").read_text(encoding="utf-8").strip()
        except OSError:
            phy = ""
        info = parse_iw_phy(_run(["iw", "phy", phy, "info"])) if phy and shutil.which("iw") else {"bands": [], "monitor": "unknown", "max_width_mhz": None}
        return {"bands": info["bands"], "width": info["max_width_mhz"],
                "monitor": info["monitor"] if info["monitor"] != "unknown" else pcap_rfmon(name),
                "capture": "yes" if hasattr(os, "geteuid") and os.geteuid() == 0 else "admin"}


def this_os() -> Os:
    """지금 돌고 있는 운영체제의 갈래. 부를 때마다 정한다."""
    return MacOs() if sys.platform == "darwin" else WindowsOs() if os.name == "nt" else LinuxOs()


# ---------- 능력 ----------
def pcap_rfmon(name: str) -> str:
    """모니터 모드를 켤 수 있는 어댑터인가: "yes" / "no" / "unknown". 묻기만 하고 아무것도 켜지 않는다(pcap_can_set_rfmon)."""
    path = ctypes.util.find_library("pcap")
    if not path:
        return "unknown"
    try:
        lib = ctypes.CDLL(path)
        lib.pcap_create.restype = ctypes.c_void_p
        lib.pcap_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        lib.pcap_can_set_rfmon.argtypes = [ctypes.c_void_p]
        lib.pcap_close.argtypes = [ctypes.c_void_p]
        handle = lib.pcap_create(name.encode(), ctypes.create_string_buffer(256))
        if not handle:
            return "unknown"
        try:
            got = int(lib.pcap_can_set_rfmon(handle))
        finally:
            lib.pcap_close(handle)
    except (OSError, AttributeError):
        return "unknown"
    return "yes" if got == 1 else "no" if got == 0 else "unknown"


def parse_iw_phy(text: str) -> dict[str, Any]:
    """`iw phy <phy> info` → 대역과 모니터 모드 지원. Band 1 = 2.4, 2 = 5, 4 = 6 GHz (nl80211 의 대역 번호)."""
    bands = [b for n, b in (("1", "2.4"), ("2", "5"), ("4", "6")) if re.search(rf"^\s*Band {n}:", text, re.M)]
    block = re.search(r"Supported interface modes:\s*\n((?:\s*\*\s*.+\n?)+)", text)
    modes = re.findall(r"\*\s*(\S.*?)\s*$", block.group(1), re.M) if block else []
    widths = [w for w, mark in ((160, "160 MHz"), (80, "VHT Capabilities"), (40, "HT20/HT40")) if mark in text]
    return {"bands": bands, "monitor": ("yes" if "monitor" in modes else "no") if block else "unknown", "max_width_mhz": max(widths, default=None)}


def parse_netsh_capabilities(text: str) -> str:
    """`netsh wlan show wirelesscapabilities` 의 "Network monitor mode" 줄. 영어 표시가 아니면 알 수 없다."""
    m = re.search(r"network monitor mode\s*:\s*(not\s+)?supported", text, re.I)
    return "unknown" if not m else "no" if m.group(1) else "yes"


def _ability(name: str, state: str = "", value: str = "") -> dict[str, str]:
    return {k: v for k, v in (("id", name), ("state", state), ("value", value)) if v}


def _wifi_abilities(name: str) -> list[dict[str, str]]:
    """운영체제가 답한 것(wifi_facts)을 화면에 보여 줄 능력 목록으로 바꾼다."""
    facts = this_os().wifi_facts(name)
    monitor = str(facts.get("monitor") or "unknown")
    out = [_ability("scan", "yes")]
    if facts.get("bands"):
        out.append(_ability("bands", value=" / ".join(facts["bands"]) + " GHz"))
    if facts.get("width"):
        out.append(_ability("width", value=f"{facts['width']} MHz"))
    if facts.get("standards"):
        out.append(_ability("standards", value=str(facts["standards"])))
    out.append(_ability("monitor", monitor))
    if monitor == "yes":
        out.append(_ability("capture", str(facts.get("capture") or "unknown")))
    return out


_abilities: dict[str, list[dict[str, str]]] = {}


def abilities(adapter: dict[str, Any]) -> list[dict[str, str]]:
    """어댑터가 할 수 있는 일. 하드웨어의 능력은 바뀌지 않으므로 한 번 물은 뒤 기억한다."""
    key = adapter["id"]
    if key not in _abilities:
        try:
            if adapter["kind"] == "wifi":
                _abilities[key] = _wifi_abilities(str(adapter["detail"].get("interface", key[len(WIFI_PREFIX):])))
            else:
                _abilities[key] = [_ability("le_scan", "yes" if importlib.util.find_spec("bleak") is not None else "no")]
        except Exception:  # noqa: BLE001 — 능력을 못 물어도 장비 목록은 보여 준다
            return []
    return _abilities[key]


# ---------- 모드 전환 (Linux) ----------
MODES = ("managed", "monitor")
IFNAME = re.compile(r"[A-Za-z0-9_.-]{1,15}")
# $1 = 인터페이스, $2 = 모드. 이름은 IFNAME 으로 검사한 것만 인수로 넘긴다(명령 문자열에 끼워 넣지 않는다).
SWITCH_SH = 'ip link set "$1" down && iw dev "$1" set type "$2" && ip link set "$1" up'


def _exec(cmd: list[str], timeout: float = 60.0) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return p.returncode, (p.stdout + p.stderr).strip()


def parse_iw_dev(text: str) -> str | None:
    """`iw dev <if> info` 의 "type" 줄: managed / monitor / 그 밖의 값은 그대로."""
    m = re.search(r"^\s*type\s+(\S+)", text, re.M)
    return m.group(1) if m else None


def current_mode(name: str) -> str | None:
    if not sys.platform.startswith("linux") or not shutil.which("iw") or not IFNAME.fullmatch(name):
        return None
    return parse_iw_dev(_run(["iw", "dev", name, "info"]))


def switch_support(monitor: str) -> dict[str, str]:
    """이 컴퓨터에서 모드를 바꿀 수 있는가. how: direct(권한 있음) / pkexec(운영체제가 암호를 물음) / manual(명령을 직접 실행) / no."""
    if sys.platform == "darwin":
        return {"how": "no", "reason": "macos"}
    if not sys.platform.startswith("linux"):
        return {"how": "no", "reason": "os"}
    if monitor == "no":
        return {"how": "no", "reason": "unsupported"}
    if not shutil.which("iw") or not shutil.which("ip"):
        return {"how": "no", "reason": "tools"}
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return {"how": "direct"}
    return {"how": "pkexec"} if shutil.which("pkexec") else {"how": "manual"}


def switch_commands(name: str, mode: str) -> list[str]:
    """사람이 직접 실행할 때의 명령(화면에 그대로 보여 준다)."""
    lines = [f"sudo ip link set {name} down", f"sudo iw dev {name} set type {mode}", f"sudo ip link set {name} up"]
    if shutil.which("nmcli"):
        nm = f"nmcli device set {name} managed {'no' if mode == 'monitor' else 'yes'}"
        lines = [nm, *lines] if mode == "monitor" else [*lines, nm]
    return lines


def set_mode(dev_id: str, mode: str, confirmed: bool, run: Any = _exec) -> dict[str, Any]:
    """Wi-Fi 어댑터를 일반(managed) ↔ 모니터(monitor) 모드로 바꾼다. 확인 표시가 없으면 거부한다."""
    if not confirmed:
        raise AdapterError("모드를 바꾸기 전에 확인이 필요합니다.")
    if mode not in MODES:
        raise AdapterError("바꿀 수 있는 모드는 managed(일반)와 monitor(모니터)입니다.")
    adapter = _find(dev_id, "wifi")
    name = str(adapter["detail"].get("interface", ""))
    if not IFNAME.fullmatch(name):
        raise AdapterError("어댑터 이름을 알 수 없습니다.")
    monitor = next((a.get("state", "unknown") for a in adapter.get("abilities", []) if a["id"] == "monitor"), "unknown")
    how = switch_support(monitor)
    if how["how"] == "no":
        raise AdapterError({"macos": "macOS 는 받는 동안에만 모니터 모드가 켜지는 방식이라 미리 바꿔 둘 수 없습니다.",
                            "os": "이 운영체제에서는 모드 전환을 지원하지 않습니다.",
                            "unsupported": "이 어댑터는 모니터 모드를 지원하지 않습니다.",
                            "tools": "모드를 바꾸려면 iw 와 ip 명령이 필요합니다."}[how["reason"]])
    commands = switch_commands(name, mode)
    if how["how"] == "manual":
        raise AdapterError("관리자 권한이 필요합니다. 터미널에서 직접 실행하세요: " + " ; ".join(commands))
    nm = shutil.which("nmcli")
    if nm and mode == "monitor":
        run([nm, "device", "set", name, "managed", "no"], 20)          # NetworkManager 가 다시 일반 모드로 돌려놓지 않게(실패해도 계속한다)
    core = ["sh", "-c", SWITCH_SH, "sh", name, mode]
    code, text = run(core if how["how"] == "direct" else ["pkexec", *core], 120)
    if code != 0:
        if how["how"] == "pkexec" and code in (126, 127):               # 126: 인증 창을 닫음, 127: 인증 실패·인증 창을 띄울 수 없음
            raise AdapterError("인증이 취소됐거나 인증 창을 띄울 수 없습니다. 터미널에서 직접 실행할 수도 있습니다: " + " ; ".join(commands))
        raise AdapterError("모드를 바꾸지 못했습니다: " + text[-300:])
    if nm and mode == "managed":
        run([nm, "device", "set", name, "managed", "yes"], 20)
    now = current_mode(name)
    list_adapters(force=True)
    return {"device": dev_id, "mode": now or mode, "changed": now in (None, mode)}


# ---------- 공통 ----------
_cache: tuple[float, list[dict[str, Any]]] | None = None
_cache_lock = threading.Lock()


def list_adapters(force: bool = False) -> list[dict[str, Any]]:
    """이 컴퓨터의 Wi-Fi·블루투스 어댑터. 운영체제에 묻는 데 몇 초 걸릴 수 있어 잠깐 기억해 둔다."""
    global _cache
    with _cache_lock:
        if not force and _cache is not None and time.monotonic() - _cache[0] < CACHE_S:
            return _cache[1]
        try:
            found = this_os().list()
        except Exception:  # noqa: BLE001 — 운영체제마다 실패 모양이 달라, 목록만 비운다
            found = []
        found = [a | {"abilities": abilities(a)} for a in found]
        for a in found:
            if a["kind"] == "wifi":
                name = str(a["detail"].get("interface", ""))
                monitor = next((x.get("state", "unknown") for x in a["abilities"] if x["id"] == "monitor"), "unknown")
                a["mode"] = current_mode(name)
                a["mode_switch"] = switch_support(monitor)
                if a["mode_switch"]["how"] != "no":
                    a["mode_switch"] = a["mode_switch"] | {"to_monitor": switch_commands(name, "monitor"), "to_managed": switch_commands(name, "managed")}
        _cache = (time.monotonic(), found)
        return found


def _find(dev_id: str, kind: str) -> dict[str, Any]:
    for a in list_adapters():
        if a["id"] == dev_id and a["kind"] == kind:
            return a
    raise AdapterError(f"장비를 찾지 못했습니다: {dev_id}")


def wifi_scan(dev_id: str) -> dict[str, Any]:
    """주변 Wi-Fi 망(비콘으로 알린 것)을 한 번 찾는다. 연결하지 않는다."""
    name = str(_find(dev_id, "wifi")["detail"].get("interface", dev_id[len(WIFI_PREFIX):]))
    started = time.monotonic()
    out = this_os().wifi_scan(name)
    nets = sorted(out["networks"], key=lambda r: -(r["rssi_dbm"] if r["rssi_dbm"] is not None else -999))
    hidden = bool(nets) and all(r["ssid"] is None and r["bssid"] is None for r in nets)
    return {"device": dev_id, "networks": nets, "current": out["current"], "took_s": round(time.monotonic() - started, 1),
            # 이름이 가려졌을 때 화면이 "허용 요청"과 "설정 열기" 가운데 무엇을 보여 줄지 정하는 데 쓴다
            "location": location_state() if hidden else None,
            # 망 이름·주소가 전부 비어 있으면 운영체제가 가린 것이다(macOS·Windows 는 위치 권한이 있어야 보여 준다)
            "names_hidden": hidden}


def _location(*args: str, timeout: float = 15.0) -> str:
    if sys.platform != "darwin":
        return "unknown"
    try:
        p = subprocess.run([sys.executable, "-m", "nrtrail.mac_location", *args], capture_output=True, text=True, timeout=timeout)
        return str(json.loads(p.stdout.strip().splitlines()[-1]).get("state", "unknown"))
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return "unknown"


def location_state() -> str:
    """위치 권한의 지금 상태: undetermined(아직 안 물음) / authorized / denied / restricted / off(위치 서비스 꺼짐) / unknown."""
    return _location()


def ask_location() -> dict[str, str]:
    """운영체제의 권한 창을 띄워 묻는다(아직 묻지 않았을 때만 창이 뜬다). 사용자가 고를 때까지 기다린다."""
    if sys.platform != "darwin":
        raise AdapterError("이 운영체제에서는 설정 창에서 직접 허용해야 합니다.")
    return {"state": _location("ask", f"{LOCATION_WAIT_S:g}", timeout=LOCATION_WAIT_S + 15)}


def open_settings(pane: str, run: Any = None) -> dict[str, str]:
    """운영체제의 권한 설정 창을 연다(설정을 바꾸지는 않는다. 허용은 사용자가 그 창에서 한다)."""
    cmd = SETTINGS.get(sys.platform, {}).get(pane)
    if cmd is None:
        raise AdapterError("이 운영체제에서는 설정 창을 대신 열 수 없습니다.")
    code, text = (run or _exec)(cmd, 15)
    if code != 0:
        raise AdapterError("설정 창을 열지 못했습니다: " + text[-200:])
    return {"opened": pane}


def ble_scan(dev_id: str, seconds: float = 4.0) -> dict[str, Any]:
    """주변 BLE 광고를 seconds 초 동안 듣는다. 연결하지 않는다."""
    _find(dev_id, "bluetooth")
    if not 1.0 <= seconds <= BLE_MAX_S:
        raise AdapterError(f"듣는 시간은 1 ~ {BLE_MAX_S:g} 초 사이여야 합니다.")
    if importlib.util.find_spec("bleak") is None:
        raise AdapterError("이 컴퓨터의 블루투스를 쓰는 데 필요한 패키지(bleak)가 없습니다.")
    try:
        p = subprocess.run([sys.executable, "-m", "nrtrail.ble_host", f"{seconds:g}"], capture_output=True, text=True, timeout=seconds + 20)
    except subprocess.TimeoutExpired as e:
        raise AdapterError("블루투스가 시간 안에 답하지 않았습니다.") from e
    if p.returncode < 0:
        # macOS: 블루투스 권한이 없는 프로그램은 운영체제가 그 자리에서 끝낸다
        raise AdapterError("운영체제가 블루투스 사용을 막았습니다. 시스템 설정 > 개인정보 보호 및 보안 > 블루투스에서 이 프로그램(터미널)을 허용하세요.", 403)
    try:
        out: dict[str, Any] = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as e:
        raise AdapterError("블루투스 결과를 읽지 못했습니다: " + (p.stderr.strip()[-200:] or "출력 없음")) from e
    if out.get("error"):
        raise AdapterError("블루투스를 쓸 수 없습니다: " + str(out["error"]))
    out["devices"].sort(key=lambda d: -d["rssi_dbm"])
    return {"device": dev_id, "seconds": seconds, **out}


class WifiScanBody(BaseModel):
    device: str


class ModeBody(BaseModel):
    device: str
    mode: str
    confirmed: bool = False


class PaneBody(BaseModel):
    pane: str


class BleScanBody(BaseModel):
    device: str
    seconds: float = Field(default=4.0)


def register(app: FastAPI) -> None:
    import asyncio
    lock = asyncio.Lock()

    @app.get("/api/adapters")
    async def adapters_list(refresh: int = 0) -> dict[str, Any]:
        return {"adapters": await asyncio.to_thread(list_adapters, bool(refresh))}

    @app.post("/api/adapters/wifi/scan")
    async def adapters_wifi(body: WifiScanBody) -> dict[str, Any]:
        async with lock:
            try:
                return await asyncio.to_thread(wifi_scan, body.device)
            except AdapterError as e:
                raise HTTPException(e.status, str(e)) from e

    @app.post("/api/adapters/wifi/mode")
    async def adapters_mode(body: ModeBody) -> dict[str, Any]:
        async with lock:
            try:
                return await asyncio.to_thread(set_mode, body.device, body.mode, body.confirmed)
            except AdapterError as e:
                raise HTTPException(e.status, str(e)) from e

    @app.post("/api/adapters/permission/location")
    async def adapters_location() -> dict[str, str]:
        try:
            return await asyncio.to_thread(ask_location)
        except AdapterError as e:
            raise HTTPException(e.status, str(e)) from e

    @app.post("/api/adapters/settings")
    async def adapters_settings(body: PaneBody) -> dict[str, str]:
        try:
            return await asyncio.to_thread(open_settings, body.pane)
        except AdapterError as e:
            raise HTTPException(e.status, str(e)) from e

    @app.post("/api/adapters/bluetooth/scan")
    async def adapters_ble(body: BleScanBody) -> dict[str, Any]:
        async with lock:
            try:
                return await asyncio.to_thread(ble_scan, body.device, body.seconds)
            except AdapterError as e:
                raise HTTPException(e.status, str(e)) from e
