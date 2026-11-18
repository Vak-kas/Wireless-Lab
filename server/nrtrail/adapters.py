"""컴퓨터의 무선 어댑터(Wi-Fi, 블루투스)를 장비로 다룬다. SDR 과 달리 전파 자체(IQ)가 아니라 칩이 풀어 준 결과만 준다.

- 받는 것은 **방송 정보뿐**이다: Wi-Fi 는 운영체제의 주변 망 찾기 결과(비콘), 블루투스는 BLE 광고. 연결하지 않고, 아무것도 보내지 않는다.
- 내장(builtin)·외장(external) 은 운영체제가 알려 주는 연결 방식으로 가린다. 모르면 unknown.
- 관리자 권한이 필요한 일(모니터 모드 등)은 하지 않는다.
- macOS: Wi-Fi 는 CoreWLAN(pyobjc), 블루투스는 bleak. 망 이름·주소는 위치 권한을 준 프로그램에만 보인다.
  Windows: netsh / Linux: nmcli 로 읽는다.
- 블루투스 찾기는 따로 띄운 프로세스(ble_host)에서 한다. macOS 는 블루투스 권한이 없는 프로그램을 그 자리에서 끝내 버리기 때문에
  서버 안에서 직접 부르면 서버가 같이 죽는다.
"""

from __future__ import annotations

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
WIFI_PREFIX, BT_PREFIX = "wifi:", "bt:"
BLE_MAX_S = 10.0


class AdapterError(RuntimeError):
    """사용자에게 그대로 보여줄 문구."""


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
    nets, err = itf.scanForNetworksWithName_error_(None, None)
    if err is not None:
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
            found = _mac_list() if sys.platform == "darwin" else _win_list() if os.name == "nt" else _linux_list()
        except Exception:  # noqa: BLE001 — 운영체제마다 실패 모양이 달라, 목록만 비운다
            found = []
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
    if sys.platform == "darwin":
        out = _mac_wifi_scan(name)
    elif os.name == "nt":
        text = _run(["netsh", "wlan", "show", "networks", "mode=bssid"], 30)
        if not text:
            raise AdapterError("주변 Wi-Fi 를 읽지 못했습니다(netsh). Wi-Fi 와 위치 서비스가 켜져 있는지 확인하세요.")
        out = {"networks": parse_netsh_networks(text), "current": None}
    else:
        if not shutil.which("nmcli"):
            raise AdapterError("주변 Wi-Fi 를 읽으려면 NetworkManager(nmcli)가 필요합니다.")
        text = _run(["nmcli", "-t", "-f", "SSID,BSSID,CHAN,FREQ,SIGNAL", "dev", "wifi", "list", "ifname", name], 30)
        out = {"networks": parse_nmcli_networks(text), "current": None}
    nets = sorted(out["networks"], key=lambda r: -(r["rssi_dbm"] if r["rssi_dbm"] is not None else -999))
    return {"device": dev_id, "networks": nets, "current": out["current"], "took_s": round(time.monotonic() - started, 1),
            # 망 이름·주소가 전부 비어 있으면 운영체제가 가린 것이다(macOS·Windows 는 위치 권한이 있어야 보여 준다)
            "names_hidden": bool(nets) and all(r["ssid"] is None and r["bssid"] is None for r in nets)}


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
        raise AdapterError("운영체제가 블루투스 사용을 막았습니다. 시스템 설정 > 개인정보 보호 및 보안 > 블루투스에서 이 프로그램(터미널)을 허용하세요.")
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
                raise HTTPException(400, str(e)) from e

    @app.post("/api/adapters/bluetooth/scan")
    async def adapters_ble(body: BleScanBody) -> dict[str, Any]:
        async with lock:
            try:
                return await asyncio.to_thread(ble_scan, body.device, body.seconds)
            except AdapterError as e:
                raise HTTPException(400, str(e)) from e
